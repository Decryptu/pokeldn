#!/usr/bin/env python3
"""Host a Legends Arceus local trade network, so the console joins and speaks first.

A console waiting on the trade search screen scans as well as advertising, so it will join a
network carrying Arceus's own title, passphrase, advertisement and link code. A joiner sends the
session protocol's join request before anything else, and that request is the thing this project
cannot synthesise yet: it states the protocol list, the versions and the field layout this Pia band
uses. Hosting is how to read it.

    sudo ./.venv/bin/python bin/pla_host.py --code 00000000 --seconds 240

    (them) Jubilife Village, the trading post, Simona (Trado) -> echanger des pokemon !
           -> local -> the warning -> the SAME eight digits -> wait on the search screen

Every datagram in and out goes to --capture as one JSON line. Inbound packets are authenticated
with the session key derived from our own SSID, and every message inside is printed by protocol id.
`docs/pla.md` has the layouts this decodes.
"""
import argparse
import binascii
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import pla
from pokeldn.ldn import pia6, pia_connect, reliable5, rtt_protocol
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, find_ap_phy
from pokeldn.host_support import resolve_keys

# The 6.16-6.30 protocol ids, from docs/pla.md. A name makes a capture readable at a glance.
PROTOCOL_NAMES = {
    0x08: "keep alive", 0x2C: "net", 0x30: "turn", 0x58: "rtt", 0x65: "sync",
    0x68: "unreliable", 0x74: "clone atomic", 0x75: "clone event",
    0x76: "clone broadcast event", 0x77: "clone clock", 0x7B: "voice", 0x7C: "reliable",
    0x80: "broadcast reliable", 0x81: "stream broadcast reliable", 0x98: "session",
    0xA0: "nat traversal result", 0xA4: "monitoring data", 0xAC: "wan nat",
    0xB0: "reckoning 1d", 0xB4: "reckoning 3d",
}

# Whoever is waited on speaks first. At Pia 6.32 the HOST opens the exchange with a Net Protocol
# connection request and the joiner only answers it; `host_pia.build_net_probe` is that move for the
# GBA app. A joiner that gets no 0x11 sends nothing at all and leaves on a timer, which is what both
# an emulated and a retail Arceus do. Net is protocol 0x2C at this band.
# THE DISPATCH KEY IS THE SOURCE VARIABLE ID, NOT THE PROTOCOL. The parser copies the packet's
# source variable id into the message's lookup field and walks the station registry for it; a
# station it has never heard of makes the message unroutable and it is skipped, protocol and all.
# A joiner's registry holds its own station under an id it re-rolls every session, so a host that
# invents a fixed id can never match. Message flag 0x01 at this band is "skip the source variable
# id check", which is what a message sent before the peer knows the sender is for.
ESTABLISHING_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK

PROTO_NET = 0x2C
PROTO_RTT = 0x58
PROTO_SESSION = 0x98
PROTO_CLONE_CLOCK = 0x77
PROTO_CLONE_ATOMIC = 0x74
PROTO_BROADCAST_RELIABLE = 0x81
PIA_HOST_VAR = 0x00C6
HOST_STATION_INDEX = 0
CONSOLE_STATION_INDEX = 1
NET_REPEAT_SECONDS = 0.5
SESSION_JOIN_REQUEST = 0
RTT_REQUEST = 0
RTT_RESPONSE = 1

SESSION_MESSAGE_NAMES = {
    0: "join request", 1: "join request ack", 2: "join response", 3: "leave request",
    5: "update session", 6: "update session ack", 7: "left station sync",
    8: "left station sync ack", 9: "start host migration", 10: "start host migration ack",
}


def _describe(msg):
    name = PROTOCOL_NAMES.get(msg.protocol, "?")
    extra = ""
    if msg.protocol == 0x98 and msg.payload:
        extra = f" {SESSION_MESSAGE_NAMES.get(msg.payload[0], '?')}({msg.payload[0]})"
    return (f"proto 0x{msg.protocol:02x} {name}{extra} port={msg.port} "
            f"flags=0x{msg.message_flags:02x} len={len(msg.payload)}")


def build_net_probe(keys, our_ip, our_mac, station_ips, seqid, nonce8, max_stations,
                    protocol=PROTO_NET):
    """The host's Net 0x11, in a version-11 packet: dst 0, src the host variable id, packet id 0.

    The body is `pia_connect.build_net_conn_request`, which is the 6.39 layout and the one the GBA
    app's host sends at 6.32. Whether 6.16 to 6.23 lays the station array out the same way is
    unread; the joiner's answer, or its silence, is the measurement.
    """
    body = pia6.build_message(
        pia_connect.build_net_conn_request(seqid, PIA_HOST_VAR, our_mac, keys.network_id,
                                           station_ips, max_stations=max_stations,
                                           station_size=21),
        protocol=protocol, port=0, message_flags=ESTABLISHING_FLAGS)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, body,
                             dst_var=0, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


def build_rtt_probe(keys, our_ip, systime, nonce8, version=5, subject=PIA_HOST_VAR):
    """An RTT type-0 request, the cheapest thing a peer can answer.

    RTT keeps no state, so a reply proves the packet authenticated, the message framing parsed and
    the protocol id reached a registered protocol. Silence to both this and the Net request puts the
    fault below the Net layout. [wiki RTT-Protocol]
    """
    body = bytearray(21)
    body[0] = 0
    body[3] = version & 0xFF
    body[8:16] = (systime & ((1 << 64) - 1)).to_bytes(8, "little")
    body[19:21] = (subject & 0xFFFF).to_bytes(2, "big")
    msg = pia6.build_message(bytes(body), protocol=PROTO_RTT, port=0,
                             message_flags=ESTABLISHING_FLAGS)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=0, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


def build_reply(keys, our_ip, body, dst_var, nonce8, *, protocol=PROTO_SESSION,
                flags=ESTABLISHING_FLAGS):
    """Wrap a message body in a version-11 packet addressed to the joiner.

    A reply carries the host variable id as its source and the console's as its destination. The
    session and mesh messages dispatch on the source variable id, so the skip-source-check flag is set
    the way an establishing message is; a station the console already registered would route on the id
    too, but skipping the check costs nothing and avoids a re-roll racing the reply.
    """
    msg = pia6.build_message(body, protocol=protocol, port=0, message_flags=flags)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=dst_var, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", default="00000000", help="the eight digits the player types")
    ap.add_argument("--seconds", type=float, default=240.0, help="how long to hold the network up")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--channel", type=int, default=None)
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--capture", default=None, help="write every datagram here as JSON lines")
    ap.add_argument("--app-version", type=int, default=0,
                    help="the LDN application version; the console's own is unread")
    ap.add_argument("--ssid", default=None, help="hex, 16 bytes; default lets the LDN layer pick")
    ap.add_argument("--ip-host", action="store_true",
                    help="host over ldn_mitm on the LAN for an emulator; no radio and no root")
    ap.add_argument("--net-protocol", type=lambda v: int(v, 0), default=PROTO_NET,
                    help="the Net protocol id to send the connection request under")
    ap.add_argument("--player-name", default="PkCamp",
                    help="the LDN node name; a retail console publishes its profile name here")
    ap.add_argument("--rtt-probe", action="store_true",
                    help="also send an RTT request, which a peer answers with no state at all")
    ap.add_argument("--rtt-version", type=int, default=5, help="the RTT protocol version byte")
    ap.add_argument("--no-net-probe", action="store_true",
                    help="stay silent after a join, to measure what the joiner does unprompted")
    ap.add_argument("--our-ip", default=None,
                    help="with --ip-host, the address to advertise and serve on")
    ap.add_argument("--no-session-ack", action="store_true",
                    help="do not answer a join request with the type-1 ack (buys 8 s, completes nothing)")
    ap.add_argument("--no-session-response", action="store_true",
                    help="do not answer a join request with the type-2 join response")
    ap.add_argument("--join-seq", type=int, default=1,
                    help="the sequence id the join response promises; a type-5 update must reach it")
    ap.add_argument("--session-update", action="store_true",
                    help="after the response, send a type-5 station-list update (sets job+0x7c). Its "
                         "per-station layout is provisional pending the 0x739050 decode")
    ap.add_argument("--sustain", action="store_true",
                    help="once joined, echo RTT and acknowledge the reliable stream so the console "
                         "does not time out after 12 s and leave")
    ap.add_argument("--reliable-hello", default=None,
                    help="hex: once the console speaks on reliable, send this as the host's own "
                         "reliable seq-1 data (the game leaves at +10 s if the host never speaks)")
    ap.add_argument("--reliable-mirror", action="store_true",
                    help="progress the host's reliable stream in lockstep: for each console reliable "
                         "data message, send the host's own next-sequence data with the same payload "
                         "(the console advances only as the host advances)")
    ap.add_argument("--hello-protocol", type=lambda v: int(v, 0), default=PROTO_BROADCAST_RELIABLE,
                    help="the protocol the host sends its reliable game data on; the game's own reader "
                         "polls 0x80 (BroadcastReliable), so 0x80 puts data where the game drains it")
    ap.add_argument("--host-player-name", default="PkCamp",
                    help="the host's player name in the station-list update, which the game reads as "
                         "identity; a real name in place of the placeholder single space")
    ap.add_argument("--host-player-id", default="00000000000000020000000000000000",
                    help="hex, 16 bytes: the host's player id in the station-list update, a real "
                         "principal id in place of the placeholder")
    ap.add_argument("--clock", action="store_true",
                    help="answer the console's clone-clock (0x77) with a host clock message; the "
                         "console's ClockProtocol is parked in state 4 and an inbound clock message "
                         "resets its state machine (report 157)")
    ap.add_argument("--atomic-announce", action="store_true",
                    help="once the mesh is running, send one Atomic (0x74) kind-0 announce; a probe "
                         "for whether a host announce fills an element slot (report 163)")
    ap.add_argument("--reliable-dest-bits", type=int, default=2,
                    help="destination-bit count on the host's reliable message; 2 so the console's "
                         "own station index (1) is in range of the body destination-bitmap check")
    ap.add_argument("--reliable-bitmap", type=lambda v: int(v, 0), default=0x00000002,
                    help="destination bitmap word, big-endian at wire[9]; the console drops a message "
                         "unless the bit for its own station index (1) is set, so bit 1 = 0x2")
    args = ap.parse_args()

    if len(args.code) != pla.LINK_CODE_LEN or not args.code.isdigit():
        ap.error(f"--code is {pla.LINK_CODE_LEN} digits")
    try:
        host_player_id = binascii.unhexlify(args.host_player_id)
    except binascii.Error:
        ap.error("--host-player-id must be hex")
    if len(host_player_id) != 16:
        ap.error("--host-player-id must be 16 bytes")
    if not args.ip_host and os.geteuid() != 0:
        ap.error("hosting over the radio needs root; re-run under sudo, or pass --ip-host")

    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
        if phy is None:
            print("[pla] no AP-capable phy")
            return 1

    app_data = pla.build_advertise_data(args.code)
    print(f"[pla] advertising code {args.code}, {len(app_data)} bytes of application data")

    factory = IpHostTransport if args.ip_host else HostTransport
    transport = factory(
        app_data=app_data, password=pla.PASSPHRASE, nickname=args.player_name,
        keys_path=resolve_keys(args.keys), local_comm_id=pla.COMM_ID, scene_id=pla.SCENE_ID,
        app_version=args.app_version, max_participants=pla.MAX_PARTICIPANTS, phyname=phy,
        channel=args.channel, protocol=pla.LDN_PROTOCOL,
        ssid=binascii.unhexlify(args.ssid) if args.ssid else None,
        **({"mirror_comm_version": True} if args.ip_host else {}),
        **({"our_ip": args.our_ip} if args.ip_host and args.our_ip else {}))

    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[pla] the network did not come up: {exc}")
        return 2

    keys = pla.session_keys(transport.ssid)
    print(f"[pla] ssid={transport.ssid.hex()} network_id={keys.network_id:#010x} "
          f"us={transport.our_ip}")
    record(rec="host", ssid=transport.ssid.hex(), network_id=keys.network_id,
           our_ip=transport.our_ip, code=args.code, app_data=app_data.hex())

    deadline = time.time() + args.seconds
    seen, authed, failed = 0, 0, 0
    net_seqid, net_sent, answered, seen_ips = 2, {}, set(), set()
    reliable_high = {}          # src_ip -> highest reliable sequence id seen on the stream
    hello_sent = set()          # src_ip we have sent the host reliable seq-1 hello to
    host_seq = {}               # src_ip -> the host's own reliable send sequence, for --reliable-mirror
    atomic_sent = set()         # src_ip we have sent the Atomic kind-0 announce probe to
    try:
        while time.time() < deadline:
            now = time.time()
            # Open the Net exchange with every station that has joined, and keep repeating it until
            # that station answers. A joiner waiting on this sends nothing before it arrives.
            #
            # A console on the trade search screen holds the discovery TCP open only for the sliver
            # of its cycle when it is scanning, but its Pia UDP socket stays bound through the whole
            # station phase (measured with lsof). So probe every address that has ever joined, not
            # just the current TCP participants, or the short window is missed and the console reads
            # almost nothing (measured: one datagram in a whole run of the participants-only sweep).
            for entry in list(transport.participants):
                seen_ips.add(entry[1])
            if not args.no_net_probe:
                for ip in list(seen_ips):
                    # Do NOT stop once a station has acked: a console on the search screen tears its
                    # station down and rebinds every cycle, and each new station window needs the
                    # Net 0x11 again to fill its +0xb8 and pass WaitConnected. Gating on `answered`
                    # gave exactly one working window, then silence for every cycle after.
                    if ip == transport.our_ip:
                        continue
                    if now - net_sent.get(ip, 0) < NET_REPEAT_SECONDS:
                        continue
                    net_sent[ip] = now
                    net_seqid += 1
                    probe = build_net_probe(keys, transport.our_ip, transport.our_mac,
                                            [transport.our_ip, ip], net_seqid, os.urandom(8),
                                            pla.MAX_PARTICIPANTS, protocol=args.net_protocol)
                    transport.send(probe, ip)
                    record(rec="out", dst=ip, kind="net conn request", seqid=net_seqid,
                           hex=probe.hex(), t=now)
                    print(f"[pla] -> {ip}: net 0x11 connection request on "
                          f"protocol 0x{args.net_protocol:02x}, seqid={net_seqid}")
                    if args.rtt_probe:
                        rtt = build_rtt_probe(keys, transport.our_ip, int(now * 1000) & 0xFFFFFFFF,
                                              os.urandom(8), version=args.rtt_version)
                        transport.send(rtt, ip)
                        record(rec="out", dst=ip, kind="rtt request", hex=rtt.hex(), t=now)
                        print(f"[pla] -> {ip}: rtt request, version {args.rtt_version}")
            transport.wait_readable(0.05)
            for payload, src_ip in transport.recv():
                seen += 1
                record(rec="in", src=src_ip, hex=payload.hex(), t=time.time())
                if not pia6.is_pia6(payload):
                    print(f"[pla] {src_ip}: not a version-11 packet, {payload[:8].hex()}")
                    continue
                header, plain, ids = pia6.parse_packet(keys.session_key, src_ip,
                                                       keys.network_id, payload)
                if plain is None:
                    failed += 1
                    print(f"[pla] {src_ip}: {header!r} DID NOT AUTHENTICATE")
                    continue
                authed += 1
                print(f"[pla] {src_ip}: {header!r} footer={ids}")
                for msg in pia6.parse_messages(plain):
                    print(f"       {_describe(msg)}  {msg.payload.hex()}")
                    record(rec="msg", src=src_ip, protocol=msg.protocol, port=msg.port,
                           flags=msg.message_flags, payload=msg.payload.hex())
                    if msg.protocol == PROTO_NET and len(msg.payload) > 1:
                        if msg.payload[1] == pia_connect.NET_CONN_RESPONSE:
                            answered.add(src_ip)
                            print(f"[pla] {src_ip} answered the connection request; "
                                  f"waiting for its session join")
                    if (msg.protocol == PROTO_SESSION and msg.payload
                            and msg.payload[0] == SESSION_JOIN_REQUEST):
                        j = pia_connect.parse_session_join_v11(msg.payload)
                        if j is None:
                            print(f"[pla] {src_ip}: join request did not parse, "
                                  f"{msg.payload[:16].hex()}")
                            continue
                        # A new join is a fresh session: the console re-rolls its variable id and
                        # restarts its reliable stream at seq 1. Reset the per-station reliable state
                        # so we do not ack a stale sequence from the previous session or skip the
                        # hello (measured: a carried-over high made the next window ack seq 3 for a
                        # stream that had just restarted at 1).
                        reliable_high.pop(src_ip, None)
                        hello_sent.discard(src_ip)
                        host_seq.pop(src_ip, None)
                        atomic_sent.discard(src_ip)
                        # Echo the console's own record of the host ids (what it wrote into the
                        # request's destination fields) so the four id compares cannot miss.
                        host_const = j["destination_constant_id"]
                        host_var = j["destination_var"]
                        console_const = j["source_constant_id"]
                        console_var = j["source_var"]
                        version = dict(j["protocols"]).get(PROTO_SESSION, 0)
                        if not args.no_session_ack:
                            ack = pia_connect.build_session_join_ack_v11(
                                host_const, host_var, console_const, console_var)
                            pkt = build_reply(keys, transport.our_ip, ack,
                                                      console_var, os.urandom(8))
                            transport.send(pkt, src_ip)
                            record(rec="out", dst=src_ip, kind="session join ack",
                                   hex=pkt.hex(), t=time.time())
                            print(f"[pla] -> {src_ip}: session join-request-ack (type 1)")
                        if not args.no_session_response:
                            resp = pia_connect.build_session_join_response_v11(
                                host_const, host_var, console_const, console_var,
                                version=version, sequence_id=args.join_seq)
                            pkt = build_reply(keys, transport.our_ip, resp,
                                                      console_var, os.urandom(8))
                            transport.send(pkt, src_ip)
                            record(rec="out", dst=src_ip, kind="session join response",
                                   hex=pkt.hex(), t=time.time())
                            print(f"[pla] -> {src_ip}: session join response (type 2, status 1, "
                                  f"seq={args.join_seq})")
                        if args.session_update:
                            # The console's own request tail carries a placeholder identity (id 00..01,
                            # a 1-byte " " name). The game reads the peer's player entry as identity
                            # rather than transport, so the host station carries a real id and name;
                            # the console station keeps the placeholder, since the console knows itself.
                            host_player = dict(player_id=host_player_id, name=args.host_player_name)
                            console_player = dict(player_id=pia_connect.DEFAULT_PLAYER_ID, name=" ")
                            stations = [
                                dict(constant_id=host_const, variable_id=host_var,
                                     ip=transport.our_ip, port=12345, station_index=0,
                                     route=(0, 0), join_order=0, token=b"\x00" * 32,
                                     players=[host_player]),
                                dict(constant_id=console_const, variable_id=console_var,
                                     ip=src_ip, port=j["port"], station_index=1, route=(0, 1),
                                     join_order=1, token=j["identification_token"],
                                     players=[console_player]),
                            ]
                            upd = pia_connect.build_session_update_v11(
                                host_const, host_var, stations, sequence_id=args.join_seq)
                            pkt = build_reply(keys, transport.our_ip, upd,
                                                      console_var, os.urandom(8))
                            transport.send(pkt, src_ip)
                            record(rec="out", dst=src_ip, kind="session update", hex=pkt.hex(),
                                   t=time.time())
                            print(f"[pla] -> {src_ip}: session station-list update (type 5, "
                                  f"seq={args.join_seq}, 2 stations)")
                    # Once joined, the console streams RTT, the clone clock and the reliable window and
                    # times out after 12 s if none of it is answered (report 133). Echo RTT and
                    # acknowledge the reliable stream to hold the session.
                    # The console's ClockProtocol (0x77) message is [0] kind, [1] sequence, [2] u64 BE
                    # originate tick, [0xA] u64 BE responder clock (report 159). Kind 0 is a request the
                    # console discards (its handler is gated on my_station == master); kind 1 is the
                    # reply that advances the state machine 1 -> 2 (synchronised). Answer a request with
                    # kind 1: echo the sequence and originate tick, and put the host's own ms clock in
                    # the last field.
                    if (args.clock and msg.protocol == PROTO_CLONE_CLOCK and len(msg.payload) >= 18
                            and msg.payload[0] == 0):
                        host_ms = int(time.monotonic() * 1000) & ((1 << 64) - 1)
                        reply = (bytes([1]) + msg.payload[1:2] + msg.payload[2:10]
                                 + host_ms.to_bytes(8, "big"))
                        pkt = build_reply(keys, transport.our_ip, reply, header.src_var,
                                          os.urandom(8), protocol=PROTO_CLONE_CLOCK)
                        transport.send(pkt, src_ip)
                        record(rec="out", dst=src_ip, kind="clone clock reply", hex=pkt.hex(),
                               t=time.time())
                        # Probe the Atomic protocol once the mesh is running (the clock is flowing):
                        # a kind-0 announce on element 0. It cannot create the slot from outside, but
                        # it draws a kind-2 reply, and a slot at 0x1d5625dbe0 going non-zero would mean
                        # a host announce does fill the table (report 163). Value is a marker to spot.
                        if args.atomic_announce and src_ip not in atomic_sent:
                            atomic_sent.add(src_ip)
                            announce = (bytes([0, 0]) + (0).to_bytes(4, "big")
                                        + (0x1122334455667788).to_bytes(8, "big"))
                            apkt = build_reply(keys, transport.our_ip, announce, header.src_var,
                                               os.urandom(8), protocol=PROTO_CLONE_ATOMIC)
                            transport.send(apkt, src_ip)
                            record(rec="out", dst=src_ip, kind="atomic announce", hex=apkt.hex(),
                                   t=time.time())
                            print(f"[pla] -> {src_ip}: atomic kind-0 announce (element 0, probe)")
                    if args.sustain and msg.protocol == PROTO_RTT and msg.payload:
                        if msg.payload[0] == RTT_REQUEST:
                            # Echo the timestamp and target unchanged, kind 1. A target of 0 is
                            # accepted by everyone, and the console sends 0 here.
                            echo = bytes([RTT_RESPONSE]) + msg.payload[1:]
                            pkt = build_reply(keys, transport.our_ip, echo, header.src_var,
                                              os.urandom(8), protocol=PROTO_RTT)
                            transport.send(pkt, src_ip)
                            record(rec="out", dst=src_ip, kind="rtt response", hex=pkt.hex(),
                                   t=time.time())
                    if (args.sustain and msg.protocol == PROTO_BROADCAST_RELIABLE
                            and len(msg.payload) >= reliable5.HEADER_SIZE):
                        try:
                            rm = reliable5.parse(msg.payload)
                        except ValueError:
                            rm = None
                        if rm and (rm["flags"] & reliable5.FLAG_APPLICATION_DATA):
                            is_new = rm["sequence_id"] > reliable_high.get(src_ip, 0)
                            high = max(reliable_high.get(src_ip, 0), rm["sequence_id"])
                            reliable_high[src_ip] = high
                            # The consumer reads the entry at the receiver's own index (the console is
                            # index 1, so it reads entry[1]) and requires that entry's station byte to
                            # equal the SENDER's index, which is the host, 0. So every entry's station
                            # byte is 0, and entry[1] carries the ack of the console's stream: ack_id
                            # one past the highest sequence received.
                            entries = [
                                dict(stream_id=HOST_STATION_INDEX, ack_id=high, field_0x50=high),
                                dict(stream_id=HOST_STATION_INDEX, ack_id=high + 1, field_0x50=high),
                            ]
                            payload = reliable5.build_ack_payload(entries)
                            body = (reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                                           lowest_pending=high + 1,
                                                           stream_id=rm["stream_id"]) + payload)
                            pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                              os.urandom(8), protocol=PROTO_BROADCAST_RELIABLE)
                            transport.send(pkt, src_ip)
                            record(rec="out", dst=src_ip, kind="reliable ack",
                                   ack_id=high + 1, hex=pkt.hex(), t=time.time())
                            print(f"[pla] -> {src_ip}: reliable ack (stream {rm['stream_id']}, "
                                  f"seq {high}, ack_id {high + 1})")
                            # The console acks a host reliable stream it never receives and leaves at
                            # +10 s if the host stays silent. Speak on reliable: send the host's own
                            # seq-1 data once, with the INITIALIZED flags the console's first message
                            # carries.
                            if args.reliable_hello and src_ip not in hello_sent:
                                hello_sent.add(src_ip)
                                data = bytes.fromhex(args.reliable_hello)
                                flags = (reliable5.FLAG_APPLICATION_DATA
                                         | reliable5.FLAG_MESSAGE_START
                                         | reliable5.FLAG_MESSAGE_END
                                         | reliable5.FLAG_IS_INITIALIZED)
                                body = (reliable5.build_header(
                                    flags, 1, len(data), lowest_pending=1, stream_id=0,
                                    destination_bits=args.reliable_dest_bits,
                                    bitmap=[args.reliable_bitmap]) + data)
                                pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                  os.urandom(8), protocol=args.hello_protocol)
                                transport.send(pkt, src_ip)
                                record(rec="out", dst=src_ip, kind="reliable hello",
                                       hex=pkt.hex(), t=time.time())
                                print(f"[pla] -> {src_ip}: reliable hello (host seq 1, "
                                      f"{len(data)}B payload)")
                            # Progress the host stream in lockstep: the console advances its own
                            # stream only after the host's matching sequence lands (its seq 2 came
                            # 66 ms after the host's seq 1 was applied). Mirror each console data
                            # message as the host's own next sequence with the same payload.
                            if args.reliable_mirror and is_new:
                                s = host_seq.get(src_ip, 0) + 1
                                host_seq[src_ip] = s
                                flags = (reliable5.FLAG_APPLICATION_DATA
                                         | reliable5.FLAG_MESSAGE_START
                                         | reliable5.FLAG_MESSAGE_END
                                         | (reliable5.FLAG_IS_INITIALIZED if s == 1 else 0))
                                body = (reliable5.build_header(
                                    flags, s, len(rm["payload"]), lowest_pending=s, stream_id=0,
                                    destination_bits=args.reliable_dest_bits,
                                    bitmap=[args.reliable_bitmap]) + rm["payload"])
                                pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                  os.urandom(8), protocol=args.hello_protocol)
                                transport.send(pkt, src_ip)
                                record(rec="out", dst=src_ip, kind="reliable mirror",
                                       host_seq=s, hex=pkt.hex(), t=time.time())
                                print(f"[pla] -> {src_ip}: reliable mirror (host seq {s}, "
                                      f"payload {rm['payload'].hex()})")
    except KeyboardInterrupt:
        print("\n[pla] interrupted")
    finally:
        transport.stop()
        if cap:
            cap.close()

    print(f"[pla] {seen} datagram(s) in, {authed} authenticated, {failed} not. "
          f"joins={transport.join_events}")
    if seen and not authed:
        print("[pla] nothing authenticated: the SSID the key came from is the one we advertised, "
              "so a failure here is the header layout or the source address, not the session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

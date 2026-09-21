#!/usr/bin/env python3
"""Host a Scarlet / Violet local trade network, so a searching retail console joins and speaks.

A console on the offline Link Trade search alternates scanning and hosting, and it joins a network
carrying its own title id, passphrase and advertisement. This host puts one up, runs the layers
below the game the way `bin/pla_host.py` runs them for Arceus (the same Pia band), acknowledges
every reliable stream the console opens, and records every datagram both ways.

    sudo ./.venv/bin/python bin/sv_host.py --seconds 240 --capture scratchpad/svNN_host.jsonl

    (them) X -> Poke Portal -> Link Trade, offline, no code -> search

`docs/sv.md` has what the console sends.
"""
import argparse
import binascii
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import config
from pokeldn import sv
from pokeldn.ldn import pia6, pia_connect, reliable5
from pokeldn.pla import game_channel
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, find_ap_phy
from pokeldn.host_support import resolve_keys

PROTOCOL_NAMES = {
    0x08: "keep alive", 0x2C: "net", 0x30: "turn", 0x58: "rtt", 0x65: "sync",
    0x68: "unreliable", 0x74: "clone atomic", 0x75: "clone event",
    0x76: "clone broadcast event", 0x77: "clone clock", 0x7B: "voice", 0x7C: "reliable",
    0x80: "broadcast reliable", 0x81: "stream broadcast reliable", 0x98: "session",
    0xA0: "nat traversal result", 0xA4: "monitoring data", 0xAC: "wan nat",
}
SESSION_MESSAGE_NAMES = {
    0: "join request", 1: "join request ack", 2: "join response", 3: "leave request",
    5: "update session", 6: "update session ack", 7: "left station sync",
    8: "left station sync ack", 9: "start host migration", 10: "start host migration ack",
}

# The dispatch and addressing rules are the band's, read on Arceus (`bin/pla_host.py`,
# `docs/pla.md`): a message sent before the peer registered the sender carries flag 0x01; RTT and
# both broadcast reliable protocols are addressed to the mesh with the recipient in the footer.
ESTABLISHING_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK
PROTO_NET = 0x2C
PROTO_RTT = 0x58
PROTO_UNRELIABLE = 0x68
PROTO_CLONE_CLOCK = 0x77
PROTO_RELIABLE = 0x7C
PROTO_BROADCAST_RELIABLE = 0x80
PROTO_STREAM_BROADCAST_RELIABLE = 0x81
PROTO_SESSION = 0x98
# Reliable 0x7C belongs here too: it is the channel the game's own messages run on, and a host that
# leaves it out never acknowledges the joiner's channel table, which the console then retransmits
# for the whole session.
RELIABLE_PROTOCOLS = (PROTO_RELIABLE, PROTO_BROADCAST_RELIABLE, PROTO_STREAM_BROADCAST_RELIABLE)
MESH_DESTINATION = 0x0001
MESH_ADDRESSED = (PROTO_RTT, PROTO_BROADCAST_RELIABLE, PROTO_STREAM_BROADCAST_RELIABLE)
PIA_HOST_VAR = 0x00C6
HOST_STATION_INDEX = 0
CONSOLE_STATION_INDEX = 1
JOINER_BITMAP = 0x02
NET_REPEAT_SECONDS = 0.5
SESSION_JOIN_REQUEST = 0
RTT_REQUEST = 0
RTT_RESPONSE = 1
# A retail pair's bulk ack (sv02): four entries, every station byte 0, entry k acknowledging
# station k's stream on that port, ack id one past the highest sequence received, 1 when nothing was.
ACK_ENTRIES = 4


def _describe(msg):
    name = PROTOCOL_NAMES.get(msg.protocol, "?")
    extra = ""
    if msg.protocol == PROTO_SESSION and msg.payload:
        extra = f" {SESSION_MESSAGE_NAMES.get(msg.payload[0], '?')}({msg.payload[0]})"
    return (f"proto 0x{msg.protocol:02x} {name}{extra} port={msg.port} "
            f"flags=0x{msg.message_flags:02x} len={len(msg.payload)}")


def build_net_probe(keys, our_ip, our_mac, station_ips, seqid, nonce8, max_stations,
                    net_flags=ESTABLISHING_FLAGS):
    body = pia6.build_message(
        pia_connect.build_net_conn_request(seqid, PIA_HOST_VAR, our_mac, keys.network_id,
                                           station_ips, max_stations=max_stations,
                                           station_size=21),
        protocol=PROTO_NET, port=0, message_flags=net_flags)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, body,
                             dst_var=0, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


def build_reply(keys, our_ip, body, dst_var, nonce8, *, protocol=PROTO_SESSION,
                flags=ESTABLISHING_FLAGS, port=0, packet_id=0):
    msg = pia6.build_message(body, protocol=protocol, port=port, message_flags=flags)
    footer_ids = ()
    if protocol in MESH_ADDRESSED:
        footer_ids, dst_var = (dst_var,), MESH_DESTINATION
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=dst_var, src_var=PIA_HOST_VAR, packet_id=packet_id,
                             nonce8=nonce8, footer_ids=footer_ids)


def build_bulk_ack(port_high, host_next_seq, stream_id=0, unknown0=0):
    """The reliable bulk ack in the retail shape: `port_high[k]` is the highest sequence received
    from station k on this port, `host_next_seq` the host's own next sequence on it."""
    entries = []
    for k in range(ACK_ENTRIES):
        high = port_high.get(k, 0)
        entries.append(dict(stream_id=0, ack_id=high + 1, field_0x50=high + 1))
    payload = reliable5.build_ack_payload(entries, unknown0=unknown0)
    header = reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                    lowest_pending=host_next_seq, stream_id=stream_id,
                                    destination_bits=3, bitmap=[JOINER_BITMAP])
    return header + payload


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=240.0)
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--channel", type=int, default=None)
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--capture", default=None, help="write every datagram here as JSON lines")
    ap.add_argument("--violet", action="store_true",
                    help="advertise Violet's local communication id instead of Scarlet's")
    ap.add_argument("--comm-id", type=lambda v: int(v, 0), default=None,
                    help="advertise this local communication id")
    ap.add_argument("--app-version", type=int, default=sv.APP_VERSION)
    ap.add_argument("--platform", type=int, default=sv.PLATFORM,
                    help="the station platform byte: 1 is a Switch 2, which is what both retail "
                         "consoles advertise; 0 is a Switch and what the LDN layer defaults to")
    ap.add_argument("--ssid", default=None, help="hex, 16 bytes; default lets the LDN layer pick")
    ap.add_argument("--ip-host", action="store_true",
                    help="host over ldn_mitm on the LAN for an emulator; no radio and no root")
    ap.add_argument("--our-ip", default=None)
    ap.add_argument("--player-name", default="PkCamp", help="the LDN node name")
    ap.add_argument("--no-net-probe", action="store_true")
    ap.add_argument("--no-session-ack", action="store_true")
    ap.add_argument("--no-session-response", action="store_true")
    ap.add_argument("--no-session-update", action="store_true")
    ap.add_argument("--join-seq", type=int, default=1)
    ap.add_argument("--host-player-name", default="PkCamp")
    ap.add_argument("--host-player-id", default="00000000000000020000000000000000")
    ap.add_argument("--no-rtt", action="store_true", help="do not answer RTT requests")
    ap.add_argument("--no-ack", action="store_true", help="do not acknowledge reliable streams")
    ap.add_argument("--ack-period", type=float, default=1.0,
                    help="seconds between the periodic bulk acks on every port the console used")
    ap.add_argument("--clock", action="store_true", help="answer clone clock requests, if any")
    ap.add_argument("--update-seq", type=int, default=1,
                    help="the sequence id in the station-list update; a Scarlet host sends 1 where "
                         "its join response sent 0")
    ap.add_argument("--update-delay", type=float, default=0.0,
                    help="seconds between the Session join response and the station-list update; a "
                         "Scarlet host leaves about 1.5 s")
    ap.add_argument("--session-flags", type=lambda v: int(v, 0), default=None,
                    help="the message flags on the Session replies; a Scarlet host sends 0x00, "
                         "this host's own default is 0x01")
    ap.add_argument("--session-packet-id", type=int, default=0,
                    help="the packet id in the Pia header of the Session replies; a Scarlet host's "
                         "join response carries 1")
    ap.add_argument("--scarlet-response", action="store_true",
                    help="the 41-byte Session join response a Scarlet host sends, with no route "
                         "bytes, rather than Arceus's 43-byte one")
    ap.add_argument("--net-flags", type=lambda v: int(v, 0), default=None,
                    help="the message flags on the Net 0x11 opening; a retail host sends 0x31, "
                         "this host's own default is 0x01")
    ap.add_argument("--net-stations", type=int, default=None,
                    help="how many 21-byte station slots the Net 0x11 carries; a retail host "
                         "writes four whatever the game's participant limit is")
    ap.add_argument("--game-data", help="hex, the 40 game bytes of the advertisement; a searching "
                                        "console leaves them zero, a host that a joiner reached "
                                        "carried 648cf4 at +0x21")
    ap.add_argument("--send", action="append", default=[],
                    help="PROTO:PORT:HEX, a reliable data message to send once the console has "
                         "joined (host seq 1 on that port, INITIALIZED); repeatable")
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    try:
        host_player_id = binascii.unhexlify(args.host_player_id)
    except binascii.Error:
        ap.error("--host-player-id must be hex")
    if len(host_player_id) != 16:
        ap.error("--host-player-id must be 16 bytes")
    if not args.ip_host and os.geteuid() != 0:
        ap.error("hosting over the radio needs root; re-run under sudo, or pass --ip-host")
    comm_id = args.comm_id or (sv.COMM_ID_VIOLET if args.violet else sv.COMM_ID_SCARLET)

    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
        if phy is None:
            print("[sv] no AP-capable phy")
            return 1

    session_flags = (ESTABLISHING_FLAGS if args.session_flags is None else args.session_flags)
    pending_update = {}
    game_data = binascii.unhexlify(args.game_data) if args.game_data else None
    app_data = sv.build_advertise_data(game_data=game_data)
    print(f"[sv] advertising comm id {comm_id:#018x}, {len(app_data)} bytes of application data, "
          f"platform {args.platform}")
    machine = config.load_project_host_file_config()
    factory = IpHostTransport if args.ip_host else HostTransport
    transport = factory(
        app_data=app_data, password=sv.PASSPHRASE, nickname=args.player_name,
        keys_path=resolve_keys(args.keys), local_comm_id=comm_id, scene_id=sv.SCENE_ID,
        app_version=args.app_version, max_participants=sv.MAX_PARTICIPANTS, phyname=phy,
        channel=args.channel, protocol=sv.LDN_PROTOCOL,
        ssid=binascii.unhexlify(args.ssid) if args.ssid else None,
        # The platform byte and the radio profile belong to the air; ldn_mitm carries neither.
        **({"mirror_comm_version": True} if args.ip_host else {}),
        **({"our_ip": args.our_ip} if args.ip_host and args.our_ip else {}),
        **({} if args.ip_host else dict(platform=args.platform,
                                        skip_encryption=machine.skip_encryption,
                                        accept_decrypted_ccmp=machine.accept_decrypted_ccmp)))
    if not args.ip_host:
        print(f"[sv] radio profile: skip_encryption={machine.skip_encryption} "
              f"accept_decrypted_ccmp={machine.accept_decrypted_ccmp}")

    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[sv] the network did not come up: {exc}")
        return 2

    keys = sv.session_keys(transport.ssid)
    print(f"[sv] ssid={transport.ssid.hex()} network_id={keys.network_id:#010x} us={transport.our_ip}")
    record(rec="host", ssid=transport.ssid.hex(), network_id=keys.network_id,
           our_ip=transport.our_ip, comm_id=comm_id, app_data=app_data.hex())

    deadline = time.time() + args.seconds
    seen, authed, failed = 0, 0, 0
    net_seqid, net_sent, seen_ips = 2, {}, set()
    station_ids = {}            # src_ip -> the ids session named
    # (src_ip, protocol, port) -> highest data sequence received from the console on that stream
    stream_high = {}
    # (src_ip, protocol, port) -> the host's next send sequence on that stream
    host_seq = {}
    last_ack = {}               # (src_ip, protocol, port) -> when the last bulk ack went out
    sent_once = set()           # (src_ip, index of --send) already sent
    counts = {}
    advertised_players = [1]

    def next_seq(src_ip, protocol, port):
        s = host_seq.get((src_ip, protocol, port), 1)
        host_seq[(src_ip, protocol, port)] = s + 1
        return s

    def send_ack(src_ip, protocol, port, dst_var, why):
        high = stream_high.get((src_ip, protocol, port), 0)
        if protocol == PROTO_RELIABLE:
            # Reliable 0x7C is addressed to one station, so its acknowledgement is the one-entry
            # form with no destination bitmap. The four-entry broadcast form belongs to 0x80 and
            # 0x81; sent on 0x7C the console never counts its channel table acknowledged and
            # retransmits it for as long as the session lasts.
            body = game_channel.build_ack(high + 1, lowest_pending=high + 1)
        else:
            body = build_bulk_ack({CONSOLE_STATION_INDEX: high},
                                  host_seq.get((src_ip, protocol, port), 1))
        pkt = build_reply(keys, transport.our_ip, body, dst_var, os.urandom(8),
                          protocol=protocol, port=port, flags=0)
        transport.send(pkt, src_ip)
        last_ack[(src_ip, protocol, port)] = time.time()
        record(rec="out", dst=src_ip, kind="reliable ack", protocol=protocol, port=port,
               ack_id=high + 1, hex=pkt.hex(), t=time.time())
        print(f"[sv] -> {src_ip}: ack 0x{protocol:02x}:{port} ack_id {high + 1} ({why})")

    try:
        while time.time() < deadline:
            now = time.time()
            for entry in list(transport.participants):
                seen_ips.add(entry[1])
            # THE PIA BLOCK'S PLAYER COUNT IS THE GAME'S VIEW OF THE SESSION, and the LDN
            # participant list is not. A retail console advertises 2 the moment a station is
            # seated (sv02); a beacon left saying 1 while a station sits in it is a session the
            # joining game can see is not counting it.
            players = 1 + len(transport.participants)
            if players != advertised_players[0]:
                advertised_players[0] = players
                transport.set_application_data(
                    sv.build_advertise_data(num_players=players, game_data=game_data))
                print(f"[sv] advertising {players} player(s)")
            if not args.no_net_probe:
                for ip in list(seen_ips):
                    if ip == transport.our_ip or now - net_sent.get(ip, 0) < NET_REPEAT_SECONDS:
                        continue
                    net_sent[ip] = now
                    net_seqid += 1
                    probe = build_net_probe(
                        keys, transport.our_ip, transport.our_mac, [transport.our_ip, ip],
                        net_seqid, os.urandom(8),
                        sv.MAX_PARTICIPANTS if args.net_stations is None else args.net_stations,
                        net_flags=(ESTABLISHING_FLAGS if args.net_flags is None
                                   else args.net_flags))
                    transport.send(probe, ip)
                    record(rec="out", dst=ip, kind="net conn request", seqid=net_seqid,
                           hex=probe.hex(), t=now)
                    print(f"[sv] -> {ip}: net 0x11 connection request, seqid={net_seqid}")
            for ip, (due, pkt) in list(pending_update.items()):
                if now >= due:
                    del pending_update[ip]
                    transport.send(pkt, ip)
                    record(rec="out", dst=ip, kind="session update", hex=pkt.hex(), t=now)
                    print(f"[sv] -> {ip}: session station-list update (type 5)")
            # The periodic bulk ack on every stream the console has used, as a retail station
            # sends one a second on every port it has open.
            if not args.no_ack:
                for (ip, protocol, port), at in list(last_ack.items()):
                    if now - at >= args.ack_period and ip in station_ids:
                        send_ack(ip, protocol, port, station_ids[ip]["console_var"], "periodic")
            transport.wait_readable(0.05)
            for payload, src_ip in transport.recv():
                seen += 1
                record(rec="in", src=src_ip, hex=payload.hex(), t=time.time())
                if not pia6.is_pia6(payload):
                    print(f"[sv] {src_ip}: not a version-11 packet, {payload[:8].hex()}")
                    continue
                header, plain, ids = pia6.parse_packet(keys.session_key, src_ip,
                                                       keys.network_id, payload)
                if plain is None:
                    failed += 1
                    print(f"[sv] {src_ip}: {header!r} DID NOT AUTHENTICATE")
                    continue
                authed += 1
                try:
                    msgs = list(pia6.parse_messages(plain))
                except Exception as exc:
                    print(f"[sv] {src_ip}: {header!r} messages did not parse: {exc} {plain.hex()}")
                    continue
                for msg in msgs:
                    counts[msg.protocol] = counts.get(msg.protocol, 0) + 1
                    print(f"[sv] <- {src_ip} {header!r} footer={ids}")
                    print(f"       {_describe(msg)}  {msg.payload.hex()}")
                    record(rec="msg", src=src_ip, protocol=msg.protocol, port=msg.port,
                           flags=msg.message_flags, src_var=header.src_var, dst_var=header.dst_var,
                           payload=msg.payload.hex(), t=time.time())
                    try:
                        if (msg.protocol == PROTO_SESSION and msg.payload
                                and msg.payload[0] == SESSION_JOIN_REQUEST):
                            j = pia_connect.parse_session_join_v11(msg.payload)
                            if j is None:
                                print(f"[sv] {src_ip}: join request did not parse")
                                continue
                            print(f"[sv] {src_ip}: join request: protocols "
                                  + " ".join(f"0x{p:02x}v{v}" for p, v in j["protocols"])
                                  + f" app_version={j.get('application_version')!r}")
                            record(rec="join", src=src_ip, parsed={k: (v.hex() if isinstance(v, bytes) else v)
                                                                   for k, v in j.items()}, t=time.time())
                            for d in (stream_high, host_seq, last_ack):
                                for k in [k for k in d if k[0] == src_ip]:
                                    d.pop(k)
                            sent_once = {s for s in sent_once if s[0] != src_ip}
                            host_const, host_var = j["destination_constant_id"], j["destination_var"]
                            console_const, console_var = j["source_constant_id"], j["source_var"]
                            station_ids[src_ip] = dict(host_const=host_const, host_var=host_var,
                                                       console_var=console_var, at=time.time())
                            version = dict(j["protocols"]).get(PROTO_SESSION, 0)
                            if not args.no_session_ack:
                                ack = pia_connect.build_session_join_ack_v11(
                                    host_const, host_var, console_const, console_var)
                                pkt = build_reply(keys, transport.our_ip, ack, console_var,
                                                  os.urandom(8), flags=session_flags,
                                                  packet_id=args.session_packet_id)
                                transport.send(pkt, src_ip)
                                record(rec="out", dst=src_ip, kind="session join ack", hex=pkt.hex(),
                                       t=time.time())
                                print(f"[sv] -> {src_ip}: session join-request-ack (type 1)")
                            if not args.no_session_response:
                                resp = pia_connect.build_session_join_response_v11(
                                    host_const, host_var, console_const, console_var,
                                    version=version, sequence_id=args.join_seq,
                                    route=None if args.scarlet_response else (0, 1),
                                    random4=os.urandom(4))
                                pkt = build_reply(keys, transport.our_ip, resp, console_var,
                                                  os.urandom(8), flags=session_flags,
                                                  packet_id=args.session_packet_id)
                                transport.send(pkt, src_ip)
                                record(rec="out", dst=src_ip, kind="session join response",
                                       hex=pkt.hex(), t=time.time())
                                print(f"[sv] -> {src_ip}: session join response (type 2)")
                            if not args.no_session_update:
                                host_player = dict(player_id=host_player_id, name=args.host_player_name)
                                console_player = dict(player_id=pia_connect.DEFAULT_PLAYER_ID, name=" ")
                                stations = [
                                    dict(constant_id=host_const, variable_id=host_var,
                                         ip=transport.our_ip, port=12345, station_index=0,
                                         route=None if args.scarlet_response else (0, 0),
                                         join_order=0, token=b"\x00" * 32,
                                         players=[host_player]),
                                    dict(constant_id=console_const, variable_id=console_var,
                                         ip=src_ip, port=j["port"], station_index=1,
                                         route=None if args.scarlet_response else (0, 1),
                                         join_order=1, token=j["identification_token"],
                                         players=[console_player]),
                                ]
                                upd = pia_connect.build_session_update_v11(
                                    host_const, host_var, stations, sequence_id=args.update_seq)
                                pkt = build_reply(keys, transport.our_ip, upd, console_var,
                                                  os.urandom(8), flags=session_flags,
                                                  packet_id=args.session_packet_id)
                                # A Scarlet host answers the join request with the type 2 alone and
                                # sends the station list about a second and a half later; sent in
                                # the same breath the console takes neither.
                                pending_update[src_ip] = (time.time() + args.update_delay, pkt)
                        if (not args.no_rtt and msg.protocol == PROTO_RTT and msg.payload
                                and msg.payload[0] == RTT_REQUEST):
                            echo = bytes([RTT_RESPONSE]) + msg.payload[1:]
                            pkt = build_reply(keys, transport.our_ip, echo, header.src_var,
                                              os.urandom(8), protocol=PROTO_RTT)
                            transport.send(pkt, src_ip)
                            record(rec="out", dst=src_ip, kind="rtt response", hex=pkt.hex(), t=time.time())
                        if (args.clock and msg.protocol == PROTO_CLONE_CLOCK and len(msg.payload) >= 18
                                and msg.payload[0] == 0):
                            host_ms = int(time.monotonic() * 1000) & ((1 << 64) - 1)
                            reply = (bytes([1]) + msg.payload[1:2] + msg.payload[2:10]
                                     + host_ms.to_bytes(8, "big"))
                            pkt = build_reply(keys, transport.our_ip, reply, header.src_var,
                                              os.urandom(8), protocol=PROTO_CLONE_CLOCK)
                            transport.send(pkt, src_ip)
                            record(rec="out", dst=src_ip, kind="clone clock reply", hex=pkt.hex(), t=time.time())
                        if (msg.protocol in RELIABLE_PROTOCOLS
                                and len(msg.payload) >= reliable5.HEADER_SIZE):
                            try:
                                rm = reliable5.parse(msg.payload)
                            except ValueError as exc:
                                print(f"[sv] {src_ip}: reliable did not parse: {exc}")
                                rm = None
                            key = (src_ip, msg.protocol, msg.port)
                            if rm and (rm["flags"] & reliable5.FLAG_APPLICATION_DATA):
                                print(f"[sv] <- {src_ip}: DATA 0x{msg.protocol:02x}:{msg.port} "
                                      f"stream {rm['stream_id']} seq {rm['sequence_id']} "
                                      f"{reliable5.flag_names(rm['flags'])} bits={rm['destination_bits']} "
                                      f"map={rm['bitmap']} {len(rm['payload'])}B "
                                      f"{rm['payload'].hex()}")
                                record(rec="data", src=src_ip, protocol=msg.protocol, port=msg.port,
                                       seq=rm["sequence_id"], flags=rm["flags"],
                                       payload=rm["payload"].hex(), t=time.time())
                                stream_high[key] = max(stream_high.get(key, 0), rm["sequence_id"])
                                if not args.no_ack and src_ip in station_ids:
                                    send_ack(src_ip, msg.protocol, msg.port,
                                             station_ids[src_ip]["console_var"],
                                             f"seq {rm['sequence_id']}")
                            elif rm:
                                a = reliable5.parse_ack_payload(rm["payload"])
                                print(f"[sv] <- {src_ip}: ACK 0x{msg.protocol:02x}:{msg.port} "
                                      f"low={rm['lowest_pending']} bits={rm['destination_bits']} "
                                      f"map={rm['bitmap']} u0={a['unknown0']} "
                                      + " ".join(f"[s{e['stream_id']} ack={e['ack_id']} f={e['field_0x50']}]"
                                                 for e in a["entries"]))
                                # Answer the console's periodic ack in kind, once per period, so
                                # every port it opens has a host ack flowing on it.
                                if (not args.no_ack and src_ip in station_ids
                                        and key not in last_ack):
                                    send_ack(src_ip, msg.protocol, msg.port,
                                             station_ids[src_ip]["console_var"], "first")
                            # Anything the run was asked to originate, once the console is seated.
                            if src_ip in station_ids:
                                for index, spec in enumerate(args.send):
                                    if (src_ip, index) in sent_once:
                                        continue
                                    sent_once.add((src_ip, index))
                                    p, port, hx = spec.split(":", 2)
                                    # A trailing ":z" marks a payload that is already zlib, which
                                    # is how a host's announcement on 0x80 port 2 goes out.
                                    zlib_flag = hx.endswith(":z")
                                    if zlib_flag:
                                        hx = hx[:-2]
                                    p, port, data = int(p, 0), int(port), bytes.fromhex(hx)
                                    s = next_seq(src_ip, p, port)
                                    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
                                             | reliable5.FLAG_MESSAGE_END
                                             | (reliable5.FLAG_IS_INITIALIZED if s == 1 else 0)
                                             | (reliable5.FLAG_ZLIB if zlib_flag else 0))
                                    body = (reliable5.build_header(flags, s, len(data), lowest_pending=s,
                                                                   stream_id=0, destination_bits=3,
                                                                   bitmap=[JOINER_BITMAP]) + data)
                                    pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                      os.urandom(8), protocol=p, port=port, flags=0)
                                    transport.send(pkt, src_ip)
                                    record(rec="out", dst=src_ip, kind="send", protocol=p, port=port,
                                           seq=s, hex=pkt.hex(), t=time.time())
                                    print(f"[sv] -> {src_ip}: data 0x{p:02x}:{port} seq {s} {len(data)}B")
                    except Exception:
                        print(f"[sv] {src_ip}: the message handler raised, still serving")
                        traceback.print_exc()
    except KeyboardInterrupt:
        print("\n[sv] interrupted")
    finally:
        transport.stop()
        if cap:
            cap.close()

    print(f"[sv] {seen} datagram(s) in, {authed} authenticated, {failed} not. "
          f"joins={transport.join_events}")
    print("[sv] messages by protocol: "
          + " ".join(f"0x{p:02x}={n}" for p, n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

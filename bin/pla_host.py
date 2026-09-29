#!/usr/bin/env python3
"""Host a Legends Arceus local trade network that a searching console joins (docs/pla.md).

    sudo ./.venv/bin/python bin/pla_host.py --code 00000000 --seconds 240

    (them) Jubilife Village, the trading post, Simona (Trado) -> echanger des pokemon !
           -> local -> the warning -> the SAME eight digits -> wait on the search screen
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
from pokeldn import gen8, pla
from pokeldn.ldn import pia6, pia_connect, reliable5, rtt_protocol, show_done
from pokeldn.pla import channel_table, data_exchange, game_channel, trade_box
from pokeldn.pla import pokemon as pla_pokemon
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
from pokeldn.host_support import resolve_keys

PROTOCOL_NAMES = {
    0x08: "keep alive", 0x2C: "net", 0x30: "turn", 0x58: "rtt", 0x65: "sync",
    0x68: "unreliable", 0x74: "clone atomic", 0x75: "clone event",
    0x76: "clone broadcast event", 0x77: "clone clock", 0x7B: "voice", 0x7C: "reliable",
    0x80: "broadcast reliable", 0x81: "stream broadcast reliable", 0x98: "session",
    0xA0: "nat traversal result", 0xA4: "monitoring data", 0xAC: "wan nat",
    0xB0: "reckoning 1d", 0xB4: "reckoning 3d",
}

# The host speaks first: a joiner that gets no Net 0x11 sends nothing and leaves on a timer.
# Messages dispatch on the source variable id; flag 0x01 skips that check (docs/pla.md, What a
# message is routed by).
ESTABLISHING_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK
JOINER_BITMAP = 0x02              # the destination station mask a host writes: the first joiner
DATA_EXCHANGE_FLAGS = 0           # the Pia message flags a reference host puts on its record

PROTO_NET = 0x2C
PROTO_RTT = 0x58
PROTO_SESSION = 0x98
PROTO_CLONE_CLOCK = 0x77
PROTO_CLONE_ATOMIC = 0x74
PROTO_BROADCAST_RELIABLE = 0x81
PIA_HOST_VAR = 0x00C6
PIA_PORT_DEFAULT = 12345        # the port the station list advertises the host on
HOST_STATION_INDEX = 0
CONSOLE_STATION_INDEX = 1
NET_REPEAT_SECONDS = 0.5
GAME_CHANNEL_RESEND = 0.4
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
    """The host's Net 0x11 in a version-11 packet: dst 0, src the host variable id, packet id 0."""
    body = pia6.build_message(
        pia_connect.build_net_conn_request(seqid, PIA_HOST_VAR, our_mac, keys.network_id,
                                           station_ips, max_stations=max_stations,
                                           station_size=21),
        protocol=protocol, port=0, message_flags=ESTABLISHING_FLAGS)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, body,
                             dst_var=0, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


def build_rtt_probe(keys, our_ip, systime, nonce8, version=5, subject=PIA_HOST_VAR):
    """An RTT type-0 request. RTT keeps no state, so a reply proves the packet authenticated."""
    body = bytearray(21)
    body[0] = 0
    body[3] = version & 0xFF
    body[8:16] = (systime & ((1 << 64) - 1)).to_bytes(8, "little")
    body[19:21] = (subject & 0xFFFF).to_bytes(2, "big")
    msg = pia6.build_message(bytes(body), protocol=PROTO_RTT, port=0,
                             message_flags=ESTABLISHING_FLAGS)
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=0, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8)


# RTT and 0x81 go to the mesh destination with the recipient in the footer; a 0x81 addressed to the
# station never reaches the game's stream (docs/pla.md).
MESH_DESTINATION = 0x0001
MESH_ADDRESSED = (PROTO_RTT, PROTO_BROADCAST_RELIABLE)


def build_reply(keys, our_ip, body, dst_var, nonce8, *, protocol=PROTO_SESSION,
                flags=ESTABLISHING_FLAGS, port=0):
    """A version-11 packet to the console; a mesh-addressed one names it in the footer."""
    msg = pia6.build_message(body, protocol=protocol, port=port, message_flags=flags)
    footer_ids = ()
    if protocol in MESH_ADDRESSED:
        footer_ids, dst_var = (dst_var,), MESH_DESTINATION
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=dst_var, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8,
                             footer_ids=footer_ids)


def build_bundle(keys, our_ip, messages, dst_var, nonce8, *, protocol, flags=ESTABLISHING_FLAGS):
    """One protocol's messages in one packet, the rest inheriting the first's flags, as the
    reference host sends its record and stream open."""
    plaintext = b""
    for index, (body, port) in enumerate(messages):
        plaintext += pia6.build_message(body, protocol=protocol, port=port, message_flags=flags,
                                        inherit=("port" if index else False))
    footer_ids = ()
    if protocol in MESH_ADDRESSED:
        footer_ids, dst_var = (dst_var,), MESH_DESTINATION
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, plaintext,
                             dst_var=dst_var, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8,
                             footer_ids=footer_ids)


def build_parser():
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
    ap.add_argument("--data-exchange", action="store_true",
                    help="send the host's own record on the 0x81 data exchange once the console "
                         "opens its stream; the exchange the trade scene is the success branch of")
    ap.add_argument("--data-exchange-name", default=None,
                    help="the player name in that record; the game shows it as the trade partner")
    ap.add_argument("--data-exchange-id", default=None,
                    help="hex: the four-byte player id in that record")
    ap.add_argument("--game-channel", action="store_true",
                    help="open the game's own reliable channel (0x7c) once the data exchange is "
                         "done: answer the console's channel message, send the same back, and open "
                         "the host's own port-0 channel, which is what the trade flow's step 0x20 "
                         "ticks its network object for")
    ap.add_argument("--trade-box", action="store_true",
                    help="offer the host's own Pokemon on the game channel: answer the console's "
                         "trade box with one of ours at sequence 2 on port 0")
    ap.add_argument("--trade-box-ours", action="store_true",
                    help="offer a record of the host's own rather than the captured one: the same "
                         "Pokemon under the data exchange's player name and id and a new identity, "
                         "so the console is not offered the record it is itself holding")
    ap.add_argument("--trade-box-level", type=int, default=None,
                    help="the level byte in the offered record's party tail")
    ap.add_argument("--trade-box-experience", type=int, default=None,
                    help="the experience in the offered record; the level the game shows is the "
                         "curve's, so this and --trade-box-level go together")
    ap.add_argument("--trade-box-pid", default=None,
                    help="hex: the personality value in the offered record. HYPOTHESIS: a record is "
                         "shiny when the trainer id, the secret id and the two halves of this value "
                         "exclusive-or to under 16, which is the Gen-6 rule and is untested here")
    ap.add_argument("--trade-box-nickname", default=None,
                    help="the nickname in the offered record")
    ap.add_argument("--trade-box-collect", default=None,
                    help="write every record the console shows or offers to this directory, one "
                         "file per distinct record, named by species and nickname")
    ap.add_argument("--fresh-pid", action="store_true",
                    help="offer the record under a new PID and encryption constant, drawn once per "
                         "run, shiny state kept, so a save that took it before takes it again")
    ap.add_argument("--trade-box-record", default=None,
                    help="offer this record file instead of the reference one; stored or party, "
                         "encrypted or decrypted")
    ap.add_argument("--interrupt-before-phase-6", action="store_true",
                    help="after answering phase 3, wait for the console's phase 6, then leave "
                         "without answering it; this deliberately triggers the game's trade "
                         "restriction")
    ap.add_argument("--leave-after", type=float, default=None,
                    help="seconds after a station's session join to send it the type-3 leave and "
                         "end the run; the one direction no capture shows")
    ap.add_argument("--leave-sends", type=int, default=4,
                    help="how many times to send it; a console sends four")
    ap.add_argument("--stay-after-leave", action="store_true",
                    help="keep the network up and go silent after the leave instead of ending the "
                         "run; separates what a console reads in the leave from what it reads in "
                         "the network going down")
    ap.add_argument("--data-exchange-skip-source-check", action="store_true",
                    help="put the skip-source-check flag on the record, where a reference host "
                         "sends none; one variable if a run shows the record is not dispatched")
    ap.add_argument("--data-exchange-record", default=None,
                    help="send this 139-byte record file instead of building one")
    ap.add_argument("--reliable-dest-bits", type=int, default=2,
                    help="destination-bit count on the host's reliable message; 2 so the console's "
                         "own station index (1) is in range of the body destination-bitmap check")
    ap.add_argument("--reliable-bitmap", type=lambda v: int(v, 0), default=0x00000002,
                    help="destination bitmap word, big-endian at wire[9]; the console drops a message "
                         "unless the bit for its own station index (1) is set, so bit 1 = 0x2")
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()

    if len(args.code) != pla.LINK_CODE_LEN or not args.code.isdigit():
        ap.error(f"--code is {pla.LINK_CODE_LEN} digits")
    try:
        host_player_id = binascii.unhexlify(args.host_player_id)
    except binascii.Error:
        ap.error("--host-player-id must be hex")
    if len(host_player_id) != 16:
        ap.error("--host-player-id must be 16 bytes")
    if not args.ip_host and os.geteuid() != 0 and not board_radio():
        ap.error("hosting over the radio needs root; re-run under sudo, or pass --ip-host")

    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
        if phy is None:
            print("[pla] no AP-capable phy")
            return 1

    app_data = pla.build_advertise_data(args.code)
    print(f"[pla] advertising code {args.code}, {len(app_data)} bytes of application data")

    # The radio profile flags come from config/host.toml: an adapter that hands up decrypted CCMP
    # frames reads nothing without them.
    machine = config.load_project_host_file_config()
    factory = IpHostTransport if args.ip_host else HostTransport
    transport = factory(
        app_data=app_data, password=pla.PASSPHRASE, nickname=args.player_name,
        keys_path=resolve_keys(args.keys), local_comm_id=pla.COMM_ID, scene_id=pla.SCENE_ID,
        app_version=args.app_version, max_participants=pla.MAX_PARTICIPANTS, phyname=phy,
        channel=args.channel, protocol=pla.LDN_PROTOCOL,
        ssid=binascii.unhexlify(args.ssid) if args.ssid else None,
        **({"mirror_comm_version": True} if args.ip_host else {}),
        **({"our_ip": args.our_ip} if args.ip_host and args.our_ip else {}),
        **({} if args.ip_host else dict(skip_encryption=machine.skip_encryption,
                                        accept_decrypted_ccmp=machine.accept_decrypted_ccmp)))
    if not args.ip_host:
        print(f"[pla] radio profile: skip_encryption={machine.skip_encryption} "
              f"accept_decrypted_ccmp={machine.accept_decrypted_ccmp}")

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
    reliable_high = {}
    hello_sent = set()
    host_seq = {}
    if args.data_exchange_record:
        exchange_record = open(os.path.expanduser(args.data_exchange_record), "rb").read()
    else:
        exchange_record = data_exchange.build_record(
            player_id=(bytes.fromhex(args.data_exchange_id) if args.data_exchange_id else None),
            name=args.data_exchange_name)
    exchange_sent = set()
    box_edits = {k: v for k, v in dict(
        level=args.trade_box_level, experience=args.trade_box_experience,
        nickname=args.trade_box_nickname,
        pid=(int(args.trade_box_pid, 16) if args.trade_box_pid else None)).items()
        if v is not None}
    box_file = os.path.expanduser(args.trade_box_record) if args.trade_box_record else None

    fresh_draw = os.urandom(6) if args.fresh_pid else None

    def build_offer():
        """-> the encrypted offer; a rebuild keeps the run's one --fresh-pid draw."""
        template = (pla_pokemon.encrypt(pla_pokemon.load(open(box_file, "rb").read()))
                    if box_file else trade_box.REFERENCE_RECORD)
        if args.trade_box_ours:
            template = trade_box.build_our_record(
                template=template, **data_exchange.read_record(exchange_record))
        if box_edits:
            template = pla_pokemon.encrypt(
                pla_pokemon.write(pla_pokemon.decrypt(template), **box_edits))
        if fresh_draw:
            draw = iter((fresh_draw[:2], fresh_draw[2:]))
            template = pla_pokemon.encrypt(gen8.fresh_identity(
                pla_pokemon.decrypt(template), rand=lambda n: next(draw)))
        return template

    # Re-read when the file changes, so a new offer needs no restart of the session.
    box_state = {"mtime": os.path.getmtime(box_file) if box_file else None,
                 "record": build_offer()}

    def offer_record():
        if box_file:
            mtime = os.path.getmtime(box_file)
            if mtime != box_state["mtime"]:
                box_state.update(mtime=mtime, record=build_offer())
                print("[pla] offer reloaded: "
                      f"{pla_pokemon.describe(pla_pokemon.decrypt(box_state['record']))}")
        return box_state["record"]

    if args.trade_box:
        print(f"[pla] offering {pla_pokemon.describe(pla_pokemon.decrypt(box_state['record']))}")
    if args.trade_box_collect:
        os.makedirs(os.path.expanduser(args.trade_box_collect), exist_ok=True)
    collected = set()
    rx_windows = {}
    tx_window = reliable5.SendWindow(GAME_CHANNEL_RESEND)
    # One send sequence per stream, mirrors included: a mirror reusing the console's id makes its
    # window drop our next message as already delivered.
    box_seq = {}

    def next_seq(src_ip, port):
        seq = box_seq.get((src_ip, port), 1)
        box_seq[(src_ip, port)] = seq + 1
        return seq

    def own_lowest(src_ip, port):
        """-> the host's lowest unacknowledged sequence on a port, else its next: the most any host
        message may declare lowest pending, or the console skips a message still to be resent."""
        return tx_window.lowest((src_ip, port), box_seq.get((src_ip, port), 1))

    def send_reliable(src_ip, dst_var, body, *, protocol, port):
        seq = reliable5.parse(body)["sequence_id"]
        body = reliable5.set_lowest_pending(body, min(seq, own_lowest(src_ip, port)))
        pkt = build_reply(keys, transport.our_ip, body, dst_var, os.urandom(8), protocol=protocol,
                          port=port)
        transport.send(pkt, src_ip)
        tx_window.sent((src_ip, port), seq, (body, dst_var, protocol), time.time())
        return pkt

    channel_mirrored = set()
    channel_opened = set()
    atomic_sent = set()
    station_ids = {}
    left = set()
    phase3_sent = set()

    def leave(src_ip):
        """The type-3 leave a quitting console bursts; it takes no reply (docs/pla.md, Leaving)."""
        ids = station_ids.get(src_ip)
        if ids is None or src_ip in left:
            return
        left.add(src_ip)
        for _ in range(args.leave_sends):
            body = pia_connect.build_session_leave_v11(
                ids["host_const"], ids["host_var"], transport.our_ip, PIA_PORT_DEFAULT,
                random4=os.urandom(4))
            pkt = build_reply(keys, transport.our_ip, body, ids["console_var"], os.urandom(8))
            transport.send(pkt, src_ip)
            record(rec="out", dst=src_ip, kind="session leave", hex=pkt.hex(), t=time.time())
        if args.leave_sends:
            print(f"[pla] -> {src_ip}: session leave request (type 3) x{args.leave_sends}")
        else:
            print(f"[pla] {src_ip}: stopping WITHOUT a leave request (--leave-sends 0)")

    try:
        while time.time() < deadline:
            now = time.time()
            if args.leave_after is not None:
                for ip, ids in list(station_ids.items()):
                    if ip not in left and now - ids["at"] >= args.leave_after:
                        leave(ip)
                if left and all(ip in left for ip in station_ids) and not args.stay_after_leave:
                    print("[pla] left the session; the run ends here")
                    break
            # Probe every address that ever joined, and keep probing after an answer: a searching
            # console rebinds its station every cycle, and each needs the Net 0x11 to pass
            # WaitConnected.
            for entry in list(transport.participants):
                seen_ips.add(entry[1])
            if not args.no_net_probe:
                for ip in list(seen_ips):
                    if ip == transport.our_ip or ip in left:
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
            # A lost host message stalls silently; a resend keeps its sequence id under a new nonce
            # (docs/pla.md, Acknowledgement).
            for (ip, port), seq, (body, dst_var, protocol) in tx_window.due(now):
                if ip in left:
                    continue
                pkt = build_reply(keys, transport.our_ip, body, dst_var, os.urandom(8),
                                  protocol=protocol, port=port)
                transport.send(pkt, ip)
                record(rec="out", dst=ip, kind="game channel resend", port=port, seq=seq,
                       hex=pkt.hex(), t=now)
                print(f"[pla] -> {ip}: game channel resend (port {port}, seq {seq})")
            transport.wait_readable(0.05)
            for payload, src_ip in transport.recv():
                seen += 1
                record(rec="in", src=src_ip, hex=payload.hex(), t=time.time())
                if src_ip in left:
                    continue
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
                # A fault in one message is reported and the session kept.
                try:
                    for msg in pia6.parse_messages(plain):
                        if src_ip in left:
                            break
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
                            # A new join is a fresh session: the console re-rolls its variable id
                            # and restarts its streams at 1.
                            reliable_high.pop(src_ip, None)
                            hello_sent.discard(src_ip)
                            host_seq.pop(src_ip, None)
                            atomic_sent.discard(src_ip)
                            exchange_sent.discard(src_ip)
                            channel_opened.discard(src_ip)
                            box_seq = {k: v for k, v in box_seq.items() if k[0] != src_ip}
                            rx_windows = {k: v for k, v in rx_windows.items() if k[0] != src_ip}
                            tx_window.forget(lambda stream: stream[0] == src_ip)
                            channel_mirrored = {c for c in channel_mirrored if c[0] != src_ip}
                            phase3_sent.discard(src_ip)
                            # The console's own record of the host ids, so the four id compares
                            # cannot miss.
                            host_const = j["destination_constant_id"]
                            host_var = j["destination_var"]
                            console_const = j["source_constant_id"]
                            console_var = j["source_var"]
                            station_ids[src_ip] = dict(host_const=host_const, host_var=host_var,
                                                       console_var=console_var, at=time.time())
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
                                # The game reads the peer's player entry as identity: the host
                                # station carries a real id and name, the console's the placeholder
                                # its request sent.
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
                        # docs/pla.md, The game's reliable channel.
                        if (args.game_channel and msg.protocol == game_channel.PROTOCOL
                                and len(msg.payload) >= reliable5.HEADER_SIZE):
                            try:
                                cm = reliable5.parse(msg.payload)
                            except ValueError:
                                cm = None
                            # The console's acknowledgement releases the host's messages below its
                            # id and those its mask names (0x74f0ec); the rest are resent.
                            if cm and not cm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                                try:
                                    entries = reliable5.parse_ack_payload(cm["payload"])["entries"]
                                except ValueError:
                                    entries = []
                                if entries:
                                    tx_window.acked((src_ip, msg.port), entries[0]["ack_id"],
                                                    entries[0]["mask"])
                            # Each sequence once and in order, never deduplicated by body: a second
                            # trade repeats every message byte for byte (docs/pla.md).
                            ready = []
                            if cm and (cm["flags"] & reliable5.FLAG_APPLICATION_DATA):
                                window = rx_windows.setdefault((src_ip, msg.port),
                                                               reliable5.ReceiveWindow())
                                ready = window.take(cm["sequence_id"], cm)
                                lowest = min(max(1, window.next - 1), own_lowest(src_ip, msg.port))
                                body = game_channel.build_ack(window.next, lowest_pending=lowest,
                                                              mask=window.mask())
                                pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                  os.urandom(8), protocol=game_channel.PROTOCOL,
                                                  port=msg.port)
                                transport.send(pkt, src_ip)
                                record(rec="out", dst=src_ip, kind="game channel ack",
                                       ack_id=window.next, hex=pkt.hex(), t=time.time())
                                if not ready:
                                    print(f"[pla] -> {src_ip}: game channel ack (port {msg.port}, "
                                          f"seq {cm['sequence_id']}, "
                                          + ("a repeat)" if cm["sequence_id"] < window.next
                                             else f"held behind {window.next})"))
                            for cm in ready:
                                key, payload_body = game_channel.split_message(cm["payload"])
                                announced = (msg.port == game_channel.JOINER_PORT
                                             and channel_table.is_announcement(cm["payload"]))
                                print(f"[pla] -> {src_ip}: game channel ack (port {msg.port}, "
                                      f"seq {cm['sequence_id']}, "
                                      + ("channel table)" if announced else
                                         f"key {key.hex()}, body {payload_body[:16].hex()}"
                                         f"{'...' if len(payload_body) > 16 else ''} "
                                         f"{len(payload_body)}B)"))
                                offered = trade_box.read_payload(cm["payload"])
                                if offered is not None:
                                    print(f"[pla] <- {src_ip}: trade box, "
                                          f"{trade_box.selector_name(offered['selector'])} "
                                          f"{trade_box.describe(offered['record'])}")
                                    record(rec="box", src=src_ip, selector=offered["selector"],
                                           hex=offered["record"].hex(), t=time.time())
                                    if args.trade_box_collect and offered["record"] not in collected:
                                        collected.add(offered["record"])
                                        try:
                                            fields = pla_pokemon.read(
                                                pla_pokemon.decrypt(offered["record"]))
                                            stem = (f"{fields['species']:04d}_{fields['nickname']}"
                                                    f"_lv{fields['level']}_{fields['ot_name']}"
                                                    f"_{offered['record'][:4].hex()}")
                                        except ValueError:
                                            stem = f"unreadable_{len(collected):02d}"
                                        stem = "".join(c if c.isalnum() or c in "_-" else "_"
                                                       for c in stem)
                                        path = os.path.join(os.path.expanduser(args.trade_box_collect),
                                                            f"{stem}.pa8")
                                        with open(path, "wb") as fh:
                                            fh.write(offered["record"])
                                        print(f"[pla] wrote {path}")
                                # Announce back every key the console opens on port 1; it sends on a
                                # key only once the peer has (pokeldn.pla.channel_table).
                                if announced:
                                    for ckey, opened in channel_table.parse(cm["payload"]):
                                        print(f"[pla] <- {src_ip}: channel {ckey.hex()} "
                                              f"{'open' if opened else 'closed'}")
                                        # the phase key closes once the trade is written
                                        if not opened and ckey == trade_box.PHASE_KEY:
                                            show_done()
                                            print(f"[pla] {src_ip}: trade complete, the phase key "
                                                  "closed")
                                        if not opened:
                                            continue
                                        announce = game_channel.build_payload_message(
                                            channel_table.build([(ckey, True)]),
                                            next_seq(src_ip, msg.port), flags=cm["flags"])
                                        pkt = send_reliable(src_ip, header.src_var, announce,
                                                            protocol=game_channel.PROTOCOL,
                                                            port=msg.port)
                                        record(rec="out", dst=src_ip, kind="channel table",
                                               key=ckey.hex(), hex=pkt.hex(), t=time.time())
                                        print(f"[pla] -> {src_ip}: channel {ckey.hex()} open "
                                              f"announced (port {msg.port})")
                                # A mirror is owed once per handler key, not per port (docs/pla.md).
                                mirror = (src_ip, msg.port, key)
                                if not announced and (key != bytes(game_channel.KEY_SIZE)
                                                      or cm["flags"] & reliable5.FLAG_IS_INITIALIZED) \
                                        and mirror not in channel_mirrored:
                                    channel_mirrored.add(mirror)
                                    mirrored = game_channel.build_message(
                                        key, payload_body, next_seq(src_ip, msg.port),
                                        flags=cm["flags"])
                                    pkt = send_reliable(src_ip, header.src_var, mirrored,
                                                        protocol=game_channel.PROTOCOL, port=msg.port)
                                    record(rec="out", dst=src_ip, kind="game channel mirror",
                                           hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: game channel message back "
                                          f"(port {msg.port}, key {key.hex()})")
                                # Mirroring the console's selector 5 completes the state its own
                                # sender set.
                                selector = trade_box.read_selector(cm["payload"])
                                if (args.trade_box and offered is None and selector is not None
                                        and selector[0] in trade_box.MIRRORED_SELECTORS):
                                    seq = next_seq(src_ip, msg.port)
                                    body = game_channel.build_message(
                                        bytes(game_channel.KEY_SIZE), selector[1], seq)
                                    pkt = send_reliable(src_ip, header.src_var, body,
                                                        protocol=trade_box.PROTOCOL,
                                                        port=trade_box.PORT)
                                    record(rec="out", dst=src_ip, kind="trade step",
                                           selector=selector[0], hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: trade step "
                                          f"({trade_box.selector_name(selector[0])}, "
                                          f"{selector[1].hex()})")
                                # Selector 2 on the phase key is the host's to send; the joiner's
                                # job waits in state 2 for it (docs/pla.md).
                                phase = trade_box.read_phase(cm["payload"])
                                if (args.trade_box and phase is not None
                                        and phase[0] == trade_box.PHASE_SELECTOR_MINE):
                                    if (args.interrupt_before_phase_6 and phase[1] == 6
                                            and src_ip in phase3_sent):
                                        record(rec="phase6_interrupted", src=src_ip,
                                               t=time.time())
                                        print(f"[pla] {src_ip}: console reached phase 6 after "
                                              "our phase 3; leaving without phase 6 reply")
                                        leave(src_ip)
                                        if not args.stay_after_leave:
                                            deadline = time.time()
                                        break
                                    seq = next_seq(src_ip, msg.port)
                                    body = trade_box.build_phase(
                                        trade_box.PHASE_SELECTOR_HOST, phase[1], seq,
                                        flags=cm["flags"])
                                    pkt = send_reliable(src_ip, header.src_var, body,
                                                        protocol=trade_box.PROTOCOL, port=msg.port)
                                    record(rec="out", dst=src_ip, kind="trade phase",
                                           phase=phase[1], hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: trade phase {phase[1]} as the host "
                                          f"(port {msg.port}, seq {seq})")
                                    if args.interrupt_before_phase_6 and phase[1] == 3:
                                        phase3_sent.add(src_ip)
                                if src_ip not in channel_opened:
                                    channel_opened.add(src_ip)
                                    opened = game_channel.build_open(
                                        game_channel.HOST_OPEN_PAYLOAD,
                                        next_seq(src_ip, game_channel.HOST_PORT))
                                    pkt = send_reliable(src_ip, header.src_var, opened,
                                                        protocol=game_channel.PROTOCOL,
                                                        port=game_channel.HOST_PORT)
                                    record(rec="out", dst=src_ip, kind="game channel open",
                                           hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: game channel open "
                                          f"(port {game_channel.HOST_PORT}, key eight zero bytes)")
                                # Answer with the selector we were sent: a showing and an offer land
                                # in different slots.
                                if args.trade_box and offered is not None:
                                    box_record = offer_record()
                                    seq = next_seq(src_ip, msg.port)
                                    body = trade_box.build_message(
                                        box_record, sequence_id=seq,
                                        selector=offered["selector"], counter=offered["counter"])
                                    pkt = send_reliable(src_ip, header.src_var, body,
                                                        protocol=trade_box.PROTOCOL,
                                                        port=trade_box.PORT)
                                    record(rec="out", dst=src_ip, kind="trade box", hex=pkt.hex(),
                                           t=time.time())
                                    print(f"[pla] -> {src_ip}: trade box (port {trade_box.PORT}, "
                                          f"{trade_box.selector_name(offered['selector'])}, "
                                          f"{trade_box.describe(box_record)})")

                        # Clock kind 0 is answered with kind 1: the sequence and originate tick
                        # echoed, then the host's ms clock (docs/pla.md, The Clone Clock and Atomic
                        # protocols).
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
                            # A kind-0 announce on element 0 draws a kind-2 reply (docs/pla.md).
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
                                # A target of 0 is accepted by everyone.
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
                                # The console reads entry[1] and requires its station byte to be the
                                # sender's index, 0 (docs/pla.md, Sustaining the mesh).
                                entries = [
                                    dict(stream_id=HOST_STATION_INDEX, ack_id=high, field_0x50=high),
                                    dict(stream_id=HOST_STATION_INDEX, ack_id=high + 1, field_0x50=high),
                                ]
                                payload = reliable5.build_ack_payload(entries)
                                # The reference's ack declares the destination its content messages
                                # declare.
                                body = (reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                                               lowest_pending=high + 1,
                                                               stream_id=rm["stream_id"],
                                                               destination_bits=1,
                                                               bitmap=[JOINER_BITMAP]) + payload)
                                pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                  os.urandom(8), protocol=PROTO_BROADCAST_RELIABLE,
                                                  port=msg.port)
                                transport.send(pkt, src_ip)
                                record(rec="out", dst=src_ip, kind="reliable ack",
                                       ack_id=high + 1, hex=pkt.hex(), t=time.time())
                                print(f"[pla] -> {src_ip}: reliable ack (stream {rm['stream_id']}, "
                                      f"seq {high}, ack_id {high + 1}, port {msg.port})")
                                # The console sends its record only after the host's; the ten-second
                                # leave waits on it (docs/pla.md).
                                if args.data_exchange and src_ip not in exchange_sent:
                                    exchange_sent.add(src_ip)
                                    # Record on port 0 and stream open on port 1 in one packet, the
                                    # reference host's byte for byte.
                                    content = data_exchange.build_content_message(
                                        exchange_record, JOINER_BITMAP)
                                    opened = data_exchange.build_stream_open(JOINER_BITMAP)
                                    pkt = build_bundle(
                                        keys, transport.our_ip,
                                        [(content, data_exchange.HOST_PORT),
                                         (opened, data_exchange.JOINER_PORT)],
                                        header.src_var, os.urandom(8),
                                        protocol=data_exchange.PROTOCOL,
                                        flags=(ESTABLISHING_FLAGS
                                               if args.data_exchange_skip_source_check
                                               else DATA_EXCHANGE_FLAGS))
                                    transport.send(pkt, src_ip)
                                    record(rec="out", dst=src_ip, kind="data exchange record",
                                           hex=pkt.hex(), t=time.time())
                                    who = data_exchange.read_record(exchange_record)
                                    print(f"[pla] -> {src_ip}: data exchange record "
                                          f"(player {who['name']!r}, {len(content)}B on port 0) "
                                          f"and stream open ({len(opened)}B on port 1)")
                                # With no host data on reliable the console leaves at +10 s.
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
                                # The console advances its stream only after the host's matching
                                # sequence lands.
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
                except Exception:
                    print(f"[pla] {src_ip}: the message handler raised, still serving")
                    traceback.print_exc()
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

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
import hashlib
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import config
from pokeldn import gen8, pla
from pokeldn.ldn import pia6, pia_connect, reliable5, rtt_protocol
from pokeldn.pla import channel_table, data_exchange, game_channel, trade_box
from pokeldn.pla import pokemon as pla_pokemon
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
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


# RTT and the stream broadcast reliable protocol are addressed to the mesh rather than to a station:
# both reference stations put the mesh destination in the header and name the recipients in the
# plaintext footer, where the session, clock and reliable protocols carry the peer's variable id in
# the header and no footer. A 0x81 message addressed the second way never reaches the game's stream
# (`docs/pla.md`, The data exchange).
MESH_DESTINATION = 0x0001
MESH_ADDRESSED = (PROTO_RTT, PROTO_BROADCAST_RELIABLE)


def build_reply(keys, our_ip, body, dst_var, nonce8, *, protocol=PROTO_SESSION,
                flags=ESTABLISHING_FLAGS, port=0):
    """Wrap a message body in a version-11 packet addressed to the joiner.

    A reply carries the host variable id as its source and the console's as its destination. The
    session and mesh messages dispatch on the source variable id, so the skip-source-check flag is set
    the way an establishing message is; a station the console already registered would route on the id
    too, but skipping the check costs nothing and avoids a re-roll racing the reply.

    A mesh-addressed protocol is addressed the way both reference stations address it: the mesh
    destination in the header and the recipient's variable id in the footer.
    """
    msg = pia6.build_message(body, protocol=protocol, port=port, message_flags=flags)
    footer_ids = ()
    if protocol in MESH_ADDRESSED:
        footer_ids, dst_var = (dst_var,), MESH_DESTINATION
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=dst_var, src_var=PIA_HOST_VAR, packet_id=0, nonce8=nonce8,
                             footer_ids=footer_ids)


def build_bundle(keys, our_ip, messages, dst_var, nonce8, *, protocol, flags=ESTABLISHING_FLAGS):
    """Several messages of one protocol in a single packet, as a reference host bundles them.

    The first message carries every header field and the rest inherit the flags while naming their
    own port, which is the shape of the reference host's record-and-open packet.
    """
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

    # OVER THE AIR THE ADAPTER'S OWN PROFILE DECIDES WHETHER THE HOST READS ANYTHING. The proven
    # TP-Link Archer T3U (rtw88_8822bu) hands its monitor interface already-decrypted frames that
    # still carry the CCMP header and MIC, so a host built for standard CCMP reads nothing at all
    # from it. Those two flags live in config/host.toml with this machine's values, the same layer
    # every other host here runs with; over IP there is no radio and they do not apply.
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
    reliable_high = {}          # src_ip -> highest reliable sequence id seen on the stream
    hello_sent = set()          # src_ip we have sent the host reliable seq-1 hello to
    host_seq = {}               # src_ip -> the host's own reliable send sequence, for --reliable-mirror
    if args.data_exchange_record:
        exchange_record = open(os.path.expanduser(args.data_exchange_record), "rb").read()
    else:
        exchange_record = data_exchange.build_record(
            player_id=(bytes.fromhex(args.data_exchange_id) if args.data_exchange_id else None),
            name=args.data_exchange_name)
    exchange_sent = set()       # src_ip we have sent the data exchange record to
    box_edits = {k: v for k, v in dict(
        level=args.trade_box_level, experience=args.trade_box_experience,
        nickname=args.trade_box_nickname,
        pid=(int(args.trade_box_pid, 16) if args.trade_box_pid else None)).items()
        if v is not None}
    box_file = os.path.expanduser(args.trade_box_record) if args.trade_box_record else None

    fresh_draw = os.urandom(6) if args.fresh_pid else None

    def build_offer():
        """-> the encrypted record to offer, from the file if one was named. A rebuild after the
        file changes keeps the run's one --fresh-pid draw."""
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

    # THE OFFER IS RE-READ WHEN THE FILE CHANGES. A console in the box screen offers over and over,
    # so writing a different record to the file swaps what the next answer carries without
    # restarting the host and dropping the session the console is in.
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
    collected = set()           # records already written, so a retransmit is not written twice
    box_sent = set()            # (src_ip, selector) of a trade box message we have answered
    # ONE SEND SEQUENCE PER STREAM. Each station's sliding window on a port is its own, so every
    # message the host originates on a port takes the next id in the host's own sequence, mirrors
    # included. Numbering a mirror with the id the console used collides as soon as the host sends
    # two messages where the console sent one, and the console's window drops the second as already
    # delivered without dispatching it (ph36: the phase message reused the mirror's id).
    box_seq = {}                # (src_ip, port) -> the host's next sequence on the game channel

    def next_seq(src_ip, port):
        seq = box_seq.get((src_ip, port), 1)
        box_seq[(src_ip, port)] = seq + 1
        return seq
    channel_mirrored = set()    # (src_ip, port) of a console channel message we have answered
    channel_announced = set()   # (src_ip, key) the host has announced open on port 1
    channel_opened = set()      # src_ip we have opened the host's own port-0 channel to
    atomic_sent = set()         # src_ip we have sent the Atomic kind-0 announce probe to
    station_ids = {}            # src_ip -> the ids that session named, for the leave the host owes
    left = set()                # src_ip the host has told it is going

    def leave(src_ip):
        """Send the station the type-3 leave a console sends when it quits.

        A console bursts this and waits for nothing, and the band pairs a leave with no reply, so
        the host sends one and stops. `docs/pla.md`, Leaving.
        """
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
            # The control for the leave: everything else the same, the message not sent. What a
            # console does about a host that stops answering is then its own timeout, not the leave.
            print(f"[pla] {src_ip}: stopping WITHOUT a leave request (--leave-sends 0)")

    try:
        while time.time() < deadline:
            now = time.time()
            # The host leaving is the one direction the captures never show, so it is timed from
            # the join rather than triggered by the game.
            if args.leave_after is not None:
                for ip, ids in list(station_ids.items()):
                    if ip not in left and now - ids["at"] >= args.leave_after:
                        leave(ip)
                if left and all(ip in left for ip in station_ids) and not args.stay_after_leave:
                    print("[pla] left the session; the run ends here")
                    break
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
            transport.wait_readable(0.05)
            for payload, src_ip in transport.recv():
                seen += 1
                record(rec="in", src=src_ip, hex=payload.hex(), t=time.time())
                if src_ip in left:
                    continue          # silent after the leave; the network stays up
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
                # A FAULT IN ONE MESSAGE DOES NOT DROP THE SESSION. A live run costs a console
                # rejoining and a player walking back to the trade screen, so the loop reports
                # what it hit and keeps answering.
                try:
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
                            exchange_sent.discard(src_ip)
                            channel_opened.discard(src_ip)
                            box_sent = {b for b in box_sent if b[0] != src_ip}
                            box_seq = {k: v for k, v in box_seq.items() if k[0] != src_ip}
                            channel_mirrored = {c for c in channel_mirrored if c[0] != src_ip}
                            channel_announced = {c for c in channel_announced if c[0] != src_ip}
                            # Echo the console's own record of the host ids (what it wrote into the
                            # request's destination fields) so the four id compares cannot miss.
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
                        # The game's own reliable channel. The trade flow's later step ticks the game's
                        # network object, which advances on what the game reads here rather than on
                        # anything the transport does (`docs/pla.md`, The game's reliable channel).
                        if (args.game_channel and msg.protocol == game_channel.PROTOCOL
                                and len(msg.payload) >= reliable5.HEADER_SIZE):
                            try:
                                cm = reliable5.parse(msg.payload)
                            except ValueError:
                                cm = None
                            if cm and (cm["flags"] & reliable5.FLAG_APPLICATION_DATA):
                                body = game_channel.build_ack(cm["sequence_id"] + 1,
                                                              lowest_pending=cm["sequence_id"])
                                pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                  os.urandom(8), protocol=game_channel.PROTOCOL,
                                                  port=msg.port)
                                transport.send(pkt, src_ip)
                                record(rec="out", dst=src_ip, kind="game channel ack", hex=pkt.hex(),
                                       t=time.time())
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
                                    # A console sends one of these every time the box cursor moves, so
                                    # a run with the cursor walked across a pasture is a library of
                                    # records the game itself considers legal.
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
                                # Port 1 is the channel table: the console announces each handler
                                # key it opens or closes, and sends on a key only once the peer has
                                # announced it open (`pokeldn.pla.channel_table`). Announce back
                                # every key the console opens, once; a close is read and left alone.
                                if announced:
                                    for ckey, opened in channel_table.parse(cm["payload"]):
                                        print(f"[pla] <- {src_ip}: channel {ckey.hex()} "
                                              f"{'open' if opened else 'closed'}")
                                        if not opened or (src_ip, ckey) in channel_announced:
                                            continue
                                        channel_announced.add((src_ip, ckey))
                                        announce = game_channel.build_payload_message(
                                            channel_table.build([(ckey, True)]),
                                            next_seq(src_ip, msg.port), flags=cm["flags"])
                                        pkt = build_reply(keys, transport.our_ip, announce,
                                                          header.src_var, os.urandom(8),
                                                          protocol=game_channel.PROTOCOL,
                                                          port=msg.port)
                                        transport.send(pkt, src_ip)
                                        record(rec="out", dst=src_ip, kind="channel table",
                                               key=ckey.hex(), hex=pkt.hex(), t=time.time())
                                        print(f"[pla] -> {src_ip}: channel {ckey.hex()} open "
                                              f"announced (port {msg.port})")
                                # A reference station answers the peer's channel message with the
                                # same message on the same port, then opens its own on port 0. The
                                # handler key is what a message is addressed to rather than the port,
                                # and a station opens more than one key on a port, so a mirror is owed
                                # once per key.
                                mirror = (src_ip, msg.port, key)
                                if not announced and (key != bytes(game_channel.KEY_SIZE)
                                                      or cm["flags"] & reliable5.FLAG_IS_INITIALIZED) \
                                        and mirror not in channel_mirrored:
                                    channel_mirrored.add(mirror)
                                    mirrored = game_channel.build_message(
                                        key, payload_body, next_seq(src_ip, msg.port),
                                        flags=cm["flags"])
                                    pkt = build_reply(keys, transport.our_ip, mirrored,
                                                      header.src_var, os.urandom(8),
                                                      protocol=game_channel.PROTOCOL, port=msg.port)
                                    transport.send(pkt, src_ip)
                                    record(rec="out", dst=src_ip, kind="game channel mirror",
                                           hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: game channel message back "
                                          f"(port {msg.port}, key {key.hex()})")
                                # The selectors that carry no record are two bytes and are answered
                                # as they stand. The console sends 5 when the player confirms the
                                # trade, and its own sender sets the state that the arriving 5
                                # completes, so mirroring it is what closes the rendezvous.
                                selector = trade_box.read_selector(cm["payload"])
                                if (args.trade_box and offered is None and selector is not None
                                        and selector[0] in trade_box.MIRRORED_SELECTORS
                                        and (src_ip, selector[1]) not in box_sent):
                                    box_sent.add((src_ip, selector[1]))
                                    seq = next_seq(src_ip, msg.port)
                                    body = game_channel.build_message(
                                        bytes(game_channel.KEY_SIZE), selector[1], seq)
                                    pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                      os.urandom(8), protocol=trade_box.PROTOCOL,
                                                      port=trade_box.PORT)
                                    transport.send(pkt, src_ip)
                                    record(rec="out", dst=src_ip, kind="trade step",
                                           selector=selector[0], hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: trade step "
                                          f"({trade_box.selector_name(selector[0])}, "
                                          f"{selector[1].hex()})")
                                # Selector 2 on the phase key is the host's to send: the joiner's own
                                # sender is behind a flag that is zero on anything but the host, so its
                                # job cannot leave state 2 until the host announces the phase.
                                phase = trade_box.read_phase(cm["payload"])
                                if (args.trade_box and phase is not None
                                        and phase[0] == trade_box.PHASE_SELECTOR_MINE
                                        and (src_ip, "phase", phase[1]) not in box_sent):
                                    box_sent.add((src_ip, "phase", phase[1]))
                                    seq = next_seq(src_ip, msg.port)
                                    body = trade_box.build_phase(
                                        trade_box.PHASE_SELECTOR_HOST, phase[1], seq,
                                        flags=cm["flags"])
                                    pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                      os.urandom(8), protocol=trade_box.PROTOCOL,
                                                      port=msg.port)
                                    transport.send(pkt, src_ip)
                                    record(rec="out", dst=src_ip, kind="trade phase",
                                           phase=phase[1], hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: trade phase {phase[1]} as the host "
                                          f"(port {msg.port}, seq {seq})")
                                if src_ip not in channel_opened:
                                    channel_opened.add(src_ip)
                                    opened = game_channel.build_open(
                                        game_channel.HOST_OPEN_PAYLOAD,
                                        next_seq(src_ip, game_channel.HOST_PORT))
                                    pkt = build_reply(keys, transport.our_ip, opened, header.src_var,
                                                      os.urandom(8), protocol=game_channel.PROTOCOL,
                                                      port=game_channel.HOST_PORT)
                                    transport.send(pkt, src_ip)
                                    record(rec="out", dst=src_ip, kind="game channel open",
                                           hex=pkt.hex(), t=time.time())
                                    print(f"[pla] -> {src_ip}: game channel open "
                                          f"(port {game_channel.HOST_PORT}, key eight zero bytes)")
                                # The console offers its Pokemon the moment the trade screen is up and
                                # does not wait to be spoken to. Answer with ours on the same channel.
                                # The selector says whether the console is showing a Pokemon or
                                # offering it, and the two land in different slots on its side. Answer
                                # with the selector we were sent: a showing answered with an offer, or
                                # an offer answered with a showing, leaves the other slot empty.
                                # One answer per distinct message: a retransmission carries the same
                                # selector, round and record and is already answered.
                                box_key = (src_ip, offered["selector"], offered["counter"],
                                           hashlib.sha256(offered["record"]).digest()) \
                                    if offered is not None else None
                                if args.trade_box and offered is not None and box_key not in box_sent:
                                    box_sent.add(box_key)
                                    box_record = offer_record()
                                    seq = next_seq(src_ip, msg.port)
                                    body = trade_box.build_message(
                                        box_record, sequence_id=seq,
                                        selector=offered["selector"], counter=offered["counter"])
                                    pkt = build_reply(keys, transport.our_ip, body, header.src_var,
                                                      os.urandom(8), protocol=trade_box.PROTOCOL,
                                                      port=trade_box.PORT)
                                    transport.send(pkt, src_ip)
                                    record(rec="out", dst=src_ip, kind="trade box", hex=pkt.hex(),
                                           t=time.time())
                                    print(f"[pla] -> {src_ip}: trade box (port {trade_box.PORT}, "
                                          f"{trade_box.selector_name(offered['selector'])}, "
                                          f"{trade_box.describe(box_record)})")

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
                                # The reference's acknowledgement declares the destination the content
                                # messages declare; ours carried a nine-byte header with neither.
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
                                # The data exchange: the trade scene is the success branch of the
                                # matching sequence, and the sequence completes when both stations have
                                # sent their record and had it acknowledged. The console sends its own
                                # only after it has received the host's, so a host that never sends one
                                # is what the ten-second deadline is waiting on (`docs/pla.md`).
                                if args.data_exchange and src_ip not in exchange_sent:
                                    exchange_sent.add(src_ip)
                                    # One packet carrying the record on port 0 and the host's own
                                    # stream open on port 1, which is the reference host's packet byte
                                    # for byte (`docs/pla.md`, The data exchange).
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

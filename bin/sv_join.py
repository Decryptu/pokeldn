#!/usr/bin/env python3
"""Join the network a searching Scarlet / Violet console puts up, and let its Pia speak to us.

A console on the offline Link Trade search alternates: a few seconds hosting its own network, then
scanning. It registers its Pia protocols while it hosts, so the session is entered from that side:
we scan in a loop, take the seat the moment the network appears, and answer what arrives.

    sudo ./.venv/bin/python bin/sv_join.py --seconds 600 --capture scratchpad/svNN_join.jsonl

    (them) X -> Poke Portal -> Link Trade, offline, no code -> search

Against an emulated console over the LAN (Ryujinx in ldn_mitm mode), no root and no radio:

    ./.venv/bin/python bin/sv_join.py --ip-join --host-ip 172.16.86.1 --our-ip 172.16.86.128 \
        --session-join --capture scratchpad/svNN_join.jsonl

The band is Pia header version 11 (`pokeldn.ldn.pia6`), the same as Legends Arceus, so the Net,
Session and RTT layouts are `pokeldn.ldn.pia_connect`'s v11 ones. Every datagram in and out goes to
--capture as one JSON line. `docs/sv.md` has what the console sends.
"""
import argparse
import json
import os
import socket
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(BUNDLED_LDN):
    sys.path.insert(0, BUNDLED_LDN)

import trio
import ldn

from pokeldn import sv
from pokeldn.ldn import ldn_mitm, pia6, pia_connect, reliable5
from pokeldn.sv import pokemon, port2, streams, trade
from pokeldn.pla import game_channel
from pokeldn.ldn.transport import board_radio, find_ap_phy
from pokeldn.host_support import resolve_keys

PROTO_NET = 0x2C
PROTO_RTT = 0x58
PROTO_CLONE_CLOCK = 0x77
PROTO_RELIABLE = 0x7C
PROTO_BROADCAST_RELIABLE = 0x80
PROTO_STREAM_BROADCAST_RELIABLE = 0x81
PROTO_SESSION = 0x98
RELIABLE_PROTOCOLS = (PROTO_BROADCAST_RELIABLE, PROTO_STREAM_BROADCAST_RELIABLE)
MESH_ADDRESSED = (PROTO_RTT, PROTO_BROADCAST_RELIABLE, PROTO_STREAM_BROADCAST_RELIABLE)
MESH_DESTINATION = 0x0001
NET_CONN_STATUS = 0x11
NET_CONN_STATUS_ACK = 0x12
# The host's 0x50 and the answer a joiner sends it, alongside the 0x11 and its 0x12 (docs/sv.md).
NET_0x50 = 0x50
NET_0x51 = 0x51
ESTABLISHING_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK
# The variable id we send as our own until the host assigns one. A retail joiner does not invent
# one: the host names the joiner's id in the plaintext footer of its first mesh-addressed packet,
# 0.14 s after the association and before the joiner has sent anything, and the joiner then uses
# that value as its own source id (`docs/sv.md`). This is the fallback for a host that never does.
OUR_VAR = 0xC493
OUR_STATION_INDEX = 1
PROTO_CLOCK = 0x77
# The Clone Clock request a joiner sends the moment it is seated: eighteen zero bytes. The host
# answers with a one, sixteen bytes and a trailing byte (docs/sv.md).
CLOCK_REQUEST = bytes(18)
# The 15 bytes a joiner sends to open 0x7c port 2, from a pair trading (docs/sv.md).
CHANNEL_PORT2_OPEN = bytes.fromhex("03b90200bc09000000000000000000")
HOST_BITMAP = 0x01                # the destination mask a joiner writes: the host, station 0
ACK_ENTRIES = 4                   # what a retail station's bulk ack carries (sv02)

PROTOCOL_NAMES = {
    0x2C: "net", 0x58: "rtt", 0x68: "unreliable", 0x74: "clone atomic", 0x77: "clone clock",
    0x7C: "reliable", 0x80: "broadcast reliable", 0x81: "stream broadcast reliable",
    0x98: "session", 0xA4: "monitoring data",
}
SESSION_MESSAGE_NAMES = {
    0: "join request", 1: "join request ack", 2: "join response", 3: "leave request",
    5: "update session", 6: "update session ack", 7: "start host migration",
    8: "start host migration ack",
}
# Type 7 at this band is written by LeaveMeshWithHostMigrationJob (0x6d8de0) and the job then waits
# in "WaitStartHostMigrationAck" for a type 8, repeating every second: it is the host leaving the
# mesh and handing the host role to the station it addresses (sv18), not the wiki's left-station sync.

STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]


def cleanup_stale():
    if board_radio():
        return
    import subprocess
    for name in STALE_VIFS:
        subprocess.run(["iw", "dev", name, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def set_mac(phy, mac, log=print):
    """Give the phy's own interface this MAC, so the vif the association creates inherits it.

    An interface has to be down to take a new address. The driver reload every launcher runs puts
    the adapter's own address back, so nothing here has to undo it.
    """
    import subprocess

    if board_radio():
        from pokeldn.ldn import esp32_wlan
        esp32_wlan.set_station_mac(mac)
        log(f"[sv] the board's station joins as {mac}")
        return True
    base = os.path.join("/sys/class/ieee80211", phy, "device", "net")
    try:
        names = os.listdir(base)
    except OSError:
        log(f"[sv] no interface under {base}; the MAC is unchanged")
        return False
    for name in names:
        subprocess.run(["ip", "link", "set", "dev", name, "down"], check=False)
        r = subprocess.run(["ip", "link", "set", "dev", name, "address", mac], check=False)
        if r.returncode:
            log(f"[sv] {name} refused the address {mac}")
            return False
        log(f"[sv] {name} is now {mac}")
    return True


def make_socket(ifname, our_ip=None):
    """Over the radio the socket is bound to the LDN interface; over IP to our own address."""
    from pokeldn.ldn import userspace_ip  # no kernel interface (ESP32 on macOS)
    if our_ip is None and (user := userspace_ip.udp_socket(ifname, sv.PIA_PORT)) is not None:
        user.setblocking(False)
        return user
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if our_ip is None:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, ifname.encode())
        except (PermissionError, OSError):
            pass
    s.bind((our_ip or "", sv.PIA_PORT))
    s.setblocking(False)
    return s


def ip_scan_once(our_ip, host_ip, timeout):
    """-> the emulated host's NetworkInfo, or None. The scan leaves from our own address: ldn_mitm
    drops one whose source is the host's own address, and answers to wherever it came from."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as us:
        us.settimeout(timeout)
        us.bind((our_ip, 0))
        try:
            us.sendto(ldn_mitm.build(ldn_mitm.SCAN), (host_ip, ldn_mitm.PORT))
            while True:
                data, _ = us.recvfrom(4096)
                kind, info = ldn_mitm.parse(data)
                if kind == ldn_mitm.SCAN_RESP:
                    return info
        except (socket.timeout, OSError, ValueError):
            return None


def ip_associate(our_ip, host_ip, our_mac, name, timeout):
    """-> (NetworkInfo, held TCP socket). The host keeps the connection open for the session."""
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(timeout)
    tcp.bind((our_ip, 0))
    tcp.connect((host_ip, ldn_mitm.PORT))
    tcp.sendall(ldn_mitm.build(ldn_mitm.CONNECT,
                               ldn_mitm.build_node_info(our_ip, our_mac, name.encode())))
    kind, synced = ldn_mitm.parse(tcp.recv(8192))
    if kind != ldn_mitm.SYNC_NETWORK:
        tcp.close()
        raise RuntimeError(f"the host answered our connect with type {kind}, not SyncNetwork")
    tcp.settimeout(None)
    return synced, tcp


def ip_comm_id(network_info):
    """The local communication id a NetworkInfo opens with (NetworkId.IntentId, u64 LE at 0)."""
    return int.from_bytes(bytes(network_info[:8]), "little")


def describe(net):
    known = {sv.COMM_ID_SCARLET: "Scarlet", sv.COMM_ID_VIOLET: "Violet"}
    tag = known.get(net.local_communication_id, "")
    return (f"comm_id=0x{net.local_communication_id:016x}{' (' + tag + ')' if tag else ''} "
            f"scene={net.scene_id} version={net.version} app_version={net.app_version} "
            f"ch={net.channel} {net.num_participants}/{net.max_participants}")


def _describe_msg(msg):
    name = PROTOCOL_NAMES.get(msg.protocol, "?")
    extra = ""
    if msg.protocol == PROTO_SESSION and msg.payload:
        extra = f" {SESSION_MESSAGE_NAMES.get(msg.payload[0], '?')}({msg.payload[0]})"
    return (f"proto 0x{msg.protocol:02x} {name}{extra} port={msg.port} "
            f"flags=0x{msg.message_flags:02x} len={len(msg.payload)}")


def build_out(keys, our_ip, body, dst_var, *, protocol, port=0, flags=0, src_var=OUR_VAR):
    """A version-11 packet from us to the host, addressed the way the band addresses that protocol.

    `dst_var` is 0 for an establishing message: the console has no station for us yet and its parser
    dispatches on the destination variable id, so a message addressed to the host's own id before it
    knows us is unroutable (`docs/pla.md`, and `bin/pla_join.py` sends both of its openers to 0)."""
    msg = pia6.build_message(body, protocol=protocol, port=port, message_flags=flags)
    footer_ids = ()
    if protocol in MESH_ADDRESSED:
        footer_ids, dst_var = (dst_var,), MESH_DESTINATION
    return pia6.build_packet(keys.session_key, keys.network_id, our_ip, msg,
                             dst_var=dst_var, src_var=src_var, packet_id=0, nonce8=os.urandom(8),
                             footer_ids=footer_ids)


def build_bulk_ack(high, our_next_seq, stream_id=0):
    """The bulk ack in the shape both retail stations send: four entries, every station byte our
    own index, entry k acknowledging station k's stream on this port (sv02)."""
    entries = [dict(stream_id=0, ack_id=(high if k == 0 else 0) + 1,
                    field_0x50=(high if k == 0 else 0) + 1) for k in range(ACK_ENTRIES)]
    payload = reliable5.build_ack_payload(entries)
    header = reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                    lowest_pending=our_next_seq, stream_id=stream_id,
                                    destination_bits=3, bitmap=[HOST_BITMAP])
    return header + payload


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default=None,
                    help="local communication id to join, hex; default is either cartridge's")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--ip-join", action="store_true",
                    help="join an emulated console over the LAN through ldn_mitm instead of the "
                         "radio: no root, no phy, no prod.keys")
    ap.add_argument("--host-ip", default="172.16.86.1", help="--ip-join: the emulator's address")
    ap.add_argument("--our-ip", default="172.16.86.128", help="--ip-join: our own address")
    ap.add_argument("--scan-timeout", type=float, default=1.0,
                    help="--ip-join: seconds to wait for one ldn_mitm scan answer")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="1,6,11")
    ap.add_argument("--dwell", type=float, default=0.35,
                    help="seconds per channel in the scan; the console's hosting window is a few "
                         "seconds, so a long dwell misses it")
    ap.add_argument("--seconds", type=float, default=600.0, help="how long to keep trying")
    ap.add_argument("--hold", type=float, default=60.0,
                    help="how long to stay in one joined session before scanning again")
    ap.add_argument("--name", default="PkCamp", help="the LDN node name we publish")
    ap.add_argument("--platform", type=int, default=sv.PLATFORM,
                    help="the station platform byte we publish; 1 is what a Switch 2 sends")
    ap.add_argument("--mac", default=None,
                    help="set the adapter's MAC before associating, e.g. 48:f1:eb:11:22:33. Pia "
                         "derives a station's constant id from its MAC, and the two consoles' are "
                         "Nintendo OUIs where the adapter's is not. The driver reload in the "
                         "launcher puts the adapter's own address back")
    ap.add_argument("--scan-only", action="store_true",
                    help="report what the console advertises and join nothing")
    ap.add_argument("--session-join", action="store_true",
                    help="send the Pia Session join request in the retail layout (docs/sv.md, The "
                         "Session join request): ten protocols with their versions, a four-byte "
                         "nonce, both location ids, a seven-byte station address and one player "
                         "record. A mesh join is unicast, so no passive capture shows a retail one")
    ap.add_argument("--send-record", metavar="FILE",
                    help="after the seat, send this 1395-byte identity record on 0x81 port 1 "
                         "(our station stream) as the game's data exchange, retransmitting until "
                         "the host acknowledges it. A retail joiner sends its own identity here")
    ap.add_argument("--no-clock", action="store_true",
                    help="do not send the Clone Clock request. A seated joiner sends eighteen "
                         "zero bytes on 0x77 before anything else and the host answers")
    ap.add_argument("--game-channel", action="store_true",
                    help="announce our own channel table on 0x7c. A station opens the game's "
                         "channel by sending the same 31-byte table its peer sends on port 1, an "
                         "open on port 2, and a mirror of every later table update; the peer sends "
                         "the game on port 0 only once ours is announced (docs/sv.md)")
    ap.add_argument("--record-set", metavar="DIR",
                    help="send this directory's records as our own on 0x81 port 1, in sequence "
                         "order, in place of --mirror-records. `scratchpad/sv_extract_records.py` "
                         "writes one from a station's own log, so a whole real identity can be "
                         "replayed rather than the host's mirrored back")
    ap.add_argument("--mirror-records", action="store_true",
                    help="send every record the host puts on 0x81 port 0 back on port 1 as our "
                         "own, in order. A retail joiner answers the host's records with a set of "
                         "its own; this fills that set with records the game itself composed")
    ap.add_argument("--record-delay", type=float, default=0.9,
                    help="seconds after the seat before the first identity record goes out")
    ap.add_argument("--no-channel-ack", action="store_true",
                    help="do not acknowledge the host's messages on the game's reliable channel 0x7c")
    ap.add_argument("--port2-now", action="store_true",
                    help="send the game's type-3 join on 0x7c port 2 with the channel table, "
                         "rather than in answer to the console's type-7 announcement on 0x80 "
                         "port 2. A pair's joiner answers the announcement (docs/sv.md, Port 2)")
    ap.add_argument("--send-on-open", action="append", default=[],
                    help="DELAY:PROTO:PORT:HEX[:z][:start|:end], sent that many seconds after the "
                         "host announces key 0x80 open on 0x7c port 1. A station's identity is "
                         "four messages on 0x7c port 0, the two fragments twice, and nothing sent "
                         "on that port before the announcement reaches the game; repeatable")
    ap.add_argument("--trade-offer", action="append", default=[],
                    help="a file holding the 348-byte record this joiner offers (raw, or hex "
                         "text; a 352-byte game message is stripped of its header). With it the "
                         "joiner answers the host's offer with its own, confirms, commits, and "
                         "echoes the four exchange steps the way a pair's joiner does "
                         "(pokeldn.sv.trade). Repeatable: the second and later records are "
                         "offered in the same seat, one per trade, as each trade closes")
    ap.add_argument("--offer-set", action="append", metavar="FIELD=VALUE", default=[],
                    help="a field written into the offered record before it is sealed, by its "
                         "pokeldn.sv.pokemon name: nickname=SHINY, species=906, ivs=31,31,31,31,"
                         "31,31, trainer_id=12345, ball=4. Repeatable, and `shiny` alone rolls a "
                         "personality value shiny against the record's own ids")
    ap.add_argument("--offer-dump", default=None,
                    help="write the offered record's 348-byte body to this file as hex and exit, "
                         "which needs no radio")
    ap.add_argument("--offer-out", default=None,
                    help="a file to write the host's own offer to, the 348-byte body of its "
                         "80 00 02 00 message, as hex text")
    ap.add_argument("--offer-after-open", type=float, default=None,
                    help="seconds after the host's key-0x80 open at which the joiner offers "
                         "first, before the host does; without it the joiner answers the host's "
                         "offer")
    ap.add_argument("--confirm-delay", type=float, default=1.0,
                    help="seconds after the host's confirmation before the joiner's own")
    ap.add_argument("--commit-delay", type=float, default=1.5,
                    help="seconds after the host's confirmation before the joiner commits; the "
                         "pair's joiner committed 1.5 s after its own confirmation and its host "
                         "answered in kind")
    ap.add_argument("--quiet-seat", type=float, default=None, metavar="SECONDS",
                    help="end a seat on which the console has sent nothing at all for this many "
                         "seconds, and go back to scanning. An association taken outside the "
                         "console's host phase carries no traffic; without this the run holds it "
                         "for the whole --hold")
    ap.add_argument("--leave-on-migration", type=float, default=None, metavar="SECONDS",
                    help="end the seat this many seconds after the console asks us to take the "
                         "host role, and go back to scanning. A console that sends Session type 7 "
                         "was seated late in its five-second host phase and sends nothing but "
                         "NetStartHostMigration afterwards, so the seat is spent; without this "
                         "the run holds it for the whole --hold")
    ap.add_argument("--announce-timeout", type=float, default=None, metavar="SECONDS",
                    help="end a seat whose console has not announced on 0x80 port 2 this many "
                         "seconds after the seat, and go back to scanning. A seat can carry every "
                         "stream to completion and never be announced (docs/sv.md, Unresolved); "
                         "board seats that traded announced at 5.8 and 7.7 s")
    ap.add_argument("--answer-migration", action="store_true",
                    help="answer the host's type-7 leave-with-host-migration with a type-8 ack, "
                         "telling it we accept the host role it is handing over")
    ap.add_argument("--no-update-ack", action="store_true",
                    help="do not answer a Session type-5 station update with the type 6")
    ap.add_argument("--join-repeat", type=float, default=2.0,
                    help="with --session-join, re-send it every N seconds (0 sends it once)")
    ap.add_argument("--join-player-id", default="arceus",
                    help="the 16-byte player id in the join request: 'arceus' (1 then 0 as two "
                         "big-endian u64, what a retail Arceus states), 'random', 'high' (random "
                         "with a leading 0xff) or 32 hex digits. A Scarlet host's own is "
                         "10047bd4a25543e057cee5c71ab1f2a2 (sv18)")
    ap.add_argument("--join-player-name", default=" ",
                    help="the player name in the join request's one player record; a retail "
                         "console's is a single space")
    ap.add_argument("--join-flags", type=lambda v: int(v, 0), default=ESTABLISHING_FLAGS,
                    help="message flags on the join request; a joining Arceus sends 0x01, skip "
                         "the source check, on every repeat of it")
    ap.add_argument("--join-dst-var", choices=["zero", "host"], default="zero",
                    help="the packet header's destination variable id on the join request: 0, "
                         "which is what a joining Arceus uses, or the host's own")
    ap.add_argument("--net-ack", action="store_true",
                    help="answer the host's Net 0x11 with the 0x12 ack. A retail joiner does not, "
                         "and the ack makes the console ask for host migration instead (sv08)")
    ap.add_argument("--connect-timeout", type=float, default=8.0,
                    help="seconds to allow the association itself; a console whose host phase "
                         "ends mid-connect leaves ldn.connect blocked with no timeout of its own")
    ap.add_argument("--open-delay", type=float, default=0.75,
                    help="seconds after the join response (after the seat without --session-join) "
                         "before the eleven acks and the two stream opens go out; a retail joiner "
                         "opens 0.75 s after its join")
    ap.add_argument("--rtt-period", type=float, default=0.4,
                    help="seconds between our own RTT requests (0 sends none)")
    ap.add_argument("--no-rtt", action="store_true", help="do not answer RTT requests")
    ap.add_argument("--rtt-delay", type=float, default=0.0, metavar="SECONDS",
                    help="answer each RTT request SECONDS late; a host that never gets an answer "
                         "never announces the station (docs/sv.md)")
    ap.add_argument("--no-ack", action="store_true", help="do not acknowledge reliable streams")
    ap.add_argument("--repeat-ack-gap", type=float, default=0.05, metavar="SECONDS",
                    help="acknowledge a record already held at most once per SECONDS per stream; "
                         "a new record is acked at once. 0 acks every repeat (docs/sv.md)")
    ap.add_argument("--ack-highest", action="store_true",
                    help="ack one past the highest id received, with no mask, instead of the "
                         "contiguous run and a mask as a retail station does (docs/sv.md)")
    ap.add_argument("--ack-flags", type=lambda v: int(v, 0), default=streams.MESSAGE_FLAGS_ACK,
                    help="the Pia message flags on our bulk acks; 0xa0 is what both retail "
                         "stations send, and bit 5 is what routes a message to the guest's ack "
                         "deserialiser")
    ap.add_argument("--ack-entries", type=int, default=streams.ACK_ENTRIES,
                    help="entries in the ack payload; a retail station sends four")
    ap.add_argument("--ack-dest-bits", type=int, default=3,
                    help="the reliable header's destination bits; 3 adds the four-byte bitmap a "
                         "retail station sends, 0 leaves the nine-byte header")
    ap.add_argument("--ack-sweep", action="store_true",
                    help="rotate every combination of --ack-flags, --ack-entries and "
                         "--ack-dest-bits through the seat, one per --ack-sweep-period, and print "
                         "each as it goes live. One seat then says which shape the guest parses")
    ap.add_argument("--ack-sweep-period", type=float, default=7.0,
                    help="seconds each sweep variant stays live")
    ap.add_argument("--ack-period", type=float, default=1.0,
                    help="seconds between the periodic bulk acks on every stream the host uses")
    ap.add_argument("--unicast", action="store_true",
                    help="send to the host's address instead of the LDN broadcast address. Both "
                         "retail stations broadcast every Pia packet (sv11), and a broadcast needs "
                         "no ARP resolution of the peer")
    ap.add_argument("--verbose-rtt", action="store_true", help="print the RTT traffic too")
    ap.add_argument("--capture", default=None, help="write every datagram here as JSON lines")
    return ap


def describe_offer(body):
    """-> what a 348-byte offer holds, or why it does not read as a record."""
    try:
        return pokemon.describe(pokemon.from_wire(body))
    except ValueError as exc:
        return f"{len(body)} bytes that do not read as a record: {exc}"


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    # A run that is killed rather than ended loses a block-buffered stdout, and with it the whole
    # log of the seat (sv32). Line buffering costs nothing here.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    if args.trade_offer and args.offer_dump:
        with open(args.offer_dump, "w") as fh:
            for path in args.trade_offer:
                offer = trade.load_offer(open(path, "rb").read(), args.offer_set)
                fh.write(offer.hex() + "\n")
                print(f"[sv] offering {describe_offer(offer)}")
        print(f"[sv] offer written to {args.offer_dump}")
        return 0
    if (args.offer_set or args.offer_dump or args.offer_after_open is not None) \
            and not args.trade_offer:
        ap.error("--offer-set, --offer-dump and --offer-after-open need --trade-offer")
    if args.ip_join:
        return main_ip(args)
    if os.geteuid() != 0 and not board_radio():
        ap.error("joining needs the raw radio; re-run under sudo")
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[sv] no AP-capable phy")
        return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[sv] prod.keys not found at {keys_path!r}")
        return 2
    want = {int(args.comm_id, 16)} if args.comm_id else {sv.COMM_ID_SCARLET, sv.COMM_ID_VIOLET}
    channels = [int(c) for c in args.channels.split(",") if c.strip()]
    print(f"[sv] phy={phy} channels={channels} dwell={args.dwell}s "
          f"comm_id={' or '.join(f'{c:#018x}' for c in sorted(want))}")
    cleanup_stale()
    if args.mac:
        set_mac(phy, args.mac)
    keys_file = ldn.load_keys(keys_path)

    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    deadline = time.time() + args.seconds
    scans = seats = 0
    try:
        while time.time() < deadline:
            scans += 1

            async def find():
                return await ldn.scan(keys_file, phyname=phy, channels=channels,
                                      dwell_time=args.dwell)
            try:
                nets = trio.run(find)
            except Exception as exc:
                print(f"[sv] the scan raised: {exc}")
                time.sleep(0.5)
                continue
            target = None
            for n in nets:
                if n.local_communication_id in want:
                    print(f"[sv] scan {scans}: {describe(n)} ssid={n.ssid.hex()}")
                    record(rec="scan", comm_id=n.local_communication_id, ssid=n.ssid.hex(),
                           channel=n.channel, participants=n.num_participants,
                           max_participants=n.max_participants,
                           app_data=bytes(n.application_data).hex(), t=time.time())
                    if n.num_participants < n.max_participants:
                        target = n
            if target is None:
                continue
            if args.scan_only:
                continue
            keys = sv.session_keys(target.ssid)
            print(f"[sv] joining: ssid={target.ssid.hex()} network_id={keys.network_id:#010x} "
                  f"channel={target.channel}")

            param = ldn.ConnectNetworkParam()
            param.keys, param.network, param.password = keys_file, target, sv.PASSPHRASE
            param.name, param.app_version = args.name.encode(), target.app_version
            param.platform = args.platform
            param.phyname, param.ifname = phy, args.ifname

            async def seat():
                # ldn.connect can block for minutes when the console's host phase ends under it
                # (sv89: one attempt held the loop for six). The cancel scope bounds the
                # association alone; once the session is running the scope is lifted.
                with trio.move_on_after(args.connect_timeout) as scope:
                    async with ldn.connect(param) as network:
                        scope.deadline = float("inf")
                        info = network.info()
                        parts = list(getattr(info, "participants", []) or [])
                        print(f"[sv] *** SEATED *** ssid={info.ssid.hex()}")
                        for i, p in enumerate(parts[:2]):
                            name = bytes(getattr(p, "name", b"") or b"").split(b"\0")[0]
                            print(f"[sv]   participant {i}: ip={getattr(p, 'ip_address', '?')} "
                                  f"mac={bytes(getattr(p, 'mac_address', b'')).hex()} "
                                  f"name={name!r} connected={getattr(p, 'connected', '?')}")
                        host = parts[0] if parts else None
                        host_ip = str(getattr(host, "ip_address", "") or "169.254.1.1")
                        host_mac = bytes(getattr(host, "mac_address", b"") or b"")
                        ours = parts[1] if len(parts) > 1 else None
                        our_ip = str(getattr(ours, "ip_address", "")
                                     or host_ip.rsplit(".", 1)[0] + ".2")
                        our_mac = bytes(getattr(ours, "mac_address", b"") or b"")
                        record(rec="seat", ssid=info.ssid.hex(), host_ip=host_ip,
                               host_mac=host_mac.hex(), our_ip=our_ip, our_mac=our_mac.hex(),
                               t=time.time())
                        await run_session(args, keys, host_ip, host_mac, our_ip, our_mac, record)

            try:
                trio.run(seat)
                seats += 1
            except Exception as exc:
                # Trio wraps what the association raised in a nursery group, sometimes twice over.
                def leaves(e):
                    inner = getattr(e, "exceptions", ())
                    return [x for i in inner for x in leaves(i)] if inner else [e]
                detail = "; ".join(f"{type(e).__name__}: {e}" for e in leaves(exc))
                print(f"[sv] the seat ended: {detail}")
                record(rec="seat_failed", detail=detail, t=time.time())
    except KeyboardInterrupt:
        print("\n[sv] interrupted")
    finally:
        if cap:
            cap.close()
    print(f"[sv] {scans} scan(s), {seats} seat(s)")
    return 0


def main_ip(args):
    """The same session against a Ryujinx host on the LAN: ldn_mitm scan, connect, then Pia on
    12345 between our two real addresses. What the game does above the seat is what it does on
    the radio; only the transport differs (`docs/ldn.md`, Hosting for an emulator)."""
    want = {int(args.comm_id, 16)} if args.comm_id else {sv.COMM_ID_SCARLET, sv.COMM_ID_VIOLET}
    our_mac = b"\x02\x00" + socket.inet_aton(args.our_ip)
    print(f"[sv] ip-join: host {args.host_ip}, us {args.our_ip}, "
          f"comm_id={' or '.join(f'{c:#018x}' for c in sorted(want))}")
    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    deadline = time.time() + args.seconds
    scans = seats = 0
    try:
        while time.time() < deadline:
            scans += 1
            info = ip_scan_once(args.our_ip, args.host_ip, args.scan_timeout)
            if info is None:
                continue
            comm_id = ip_comm_id(info)
            ssid = ldn_mitm.session_id(info)
            record(rec="scan", comm_id=comm_id, ssid=ssid.hex(), t=time.time(),
                   app_data=bytes(ldn_mitm.advertise_data(info)).hex())
            if comm_id not in want:
                print(f"[sv] scan {scans}: comm_id={comm_id:#018x} is not Scarlet or Violet")
                time.sleep(args.scan_timeout)
                continue
            keys = sv.session_keys(ssid)
            print(f"[sv] scan {scans}: the emulator is hosting. ssid={ssid.hex()} "
                  f"network_id={keys.network_id:#010x}")
            if args.scan_only:
                time.sleep(args.scan_timeout)
                continue
            try:
                synced, tcp = ip_associate(args.our_ip, args.host_ip, our_mac, args.name,
                                           args.scan_timeout * 4)
            except (OSError, RuntimeError) as exc:
                print(f"[sv] the association failed: {exc}")
                continue
            seats += 1
            host_mac = bytes(ldn_mitm.host_mac(synced))
            print(f"[sv] *** SEATED *** over IP, host mac={host_mac.hex()}")
            record(rec="seat", ssid=ssid.hex(), host_ip=args.host_ip, host_mac=host_mac.hex(),
                   our_ip=args.our_ip, our_mac=our_mac.hex(), network_info=synced.hex(),
                   t=time.time())
            try:
                trio.run(run_session, args, keys, args.host_ip, host_mac, args.our_ip, our_mac,
                         record)
            except Exception as exc:
                print(f"[sv] the seat ended: {type(exc).__name__}: {exc}")
            finally:
                try:
                    tcp.close()
                except OSError:
                    pass
    except KeyboardInterrupt:
        print("\n[sv] interrupted")
    finally:
        if cap:
            cap.close()
    print(f"[sv] {scans} scan(s), {seats} seat(s)")
    return 0


async def run_session(args, keys, host_ip, host_mac, our_ip, our_mac, record):
    """Everything above the seat: answer the host's Net, join its session, hold the streams."""
    sock = make_socket(args.ifname, our_ip if args.ip_join else None)
    t0 = time.monotonic()
    host_var = None
    host_const = pia_connect.ldn_constant_id(host_mac) if len(host_mac) == 6 else bytes(8)
    our_const = pia_connect.ldn_constant_id(our_mac) if len(our_mac) == 6 else bytes(8)
    join_sent = 0.0
    joined = False
    joined_at = 0.0
    join_sequence = None
    pending_update = None       # a type-5 update that arrived before the join response
    migration_sent = 0
    migration_at = None         # when the console first asked us to take the host role
    identity = None
    if args.send_record:
        identity = streams.compress(open(args.send_record, "rb").read())
    record_seq = 1
    # Our own 0x7c state: the host's table, whether ours has gone, and its key-0x80 open.
    channel = {"opened": False, "table": None, "key80": False, "port2": False}
    stage = None
    if args.trade_offer:
        stage = trade.JoinerTradeStage(
            [trade.load_offer(open(path, "rb").read(), args.offer_set)
             for path in args.trade_offer],
            confirm_delay=args.confirm_delay, commit_delay=args.commit_delay)
        for n, one in enumerate(stage.offers, 1):
            print(f"[sv] offer {n} of {len(stage.offers)}: {describe_offer(one)}")
    pending_trade = []          # (due, port, payload) the trade stage asked to send

    def schedule_trade(delay, port, payload):
        """Queue a trade message, never before one already queued for the same port. The stage's
        delays are gaps between messages, not positions on a clock, and a station that confirms a
        trade whose own record is not yet on the wire crashes the game (sv97)."""
        due = time.time() + delay
        for other in pending_trade:
            if other[1] == port:
                due = max(due, other[0] + delay)
        pending_trade.append((due, port, payload))
    pending_open = []           # (due, spec) hung on the host's own key-0x80 open
    offers_seen = 0             # how many of the host's offers have been printed
    trades_done = 0             # how many trades the stage has carried through the exchange
    record_set = []
    if args.record_set:
        for name in sorted(os.listdir(args.record_set)):
            if name.endswith(".bin"):
                record_set.append((int(name[:-4]), open(os.path.join(args.record_set, name),
                                                        "rb").read()))
        print(f"[sv] the record set holds {len(record_set)} record(s), "
              f"sequence ids {record_set[0][0]}..{record_set[-1][0]}")
    set_sent = False
    mirrored = set()            # host sequence ids already sent back under --mirror-records
    record_acked = False
    last_record_send = 0.0
    stream_high = {}            # (protocol, port) -> highest sequence received from the host
    stream_got = {}             # (protocol, port) -> every sequence received from the host
    peer_lowest = {}            # (protocol, port) -> the host's own lowest pending on that stream
    our_seq = {}                # (protocol, port) -> our next send sequence on that stream
    last_ack = {}
    counts = {}
    seen = authed = 0
    last_in = time.monotonic()  # when the console last sent anything, for --quiet-seat

    # Both retail stations address every Pia datagram to the link-local broadcast of their own
    # /24 (sv11: 169.254.86.2 -> 169.254.86.255), never to the peer's address.
    # Over the LAN the emulated host is one address, and the IP host direction sends unicast too.
    dest_ip = host_ip if (args.unicast or args.ip_join) else our_ip.rsplit(".", 1)[0] + ".255"

    ours = {"var": OUR_VAR, "assigned": False}
    # (flags, entries, destination bits). The first is what both retail stations send; the last is
    # the one shape a Scarlet guest has been seen to parse on this path (docs/sv.md).
    sweep = [(f, e, d) for f in (args.ack_flags, 0x00)
             for e in (args.ack_entries, 1) for d in (args.ack_dest_bits, 0)]
    sweep = list(dict.fromkeys(sweep))
    ack_shape = {"i": -1, "flags": args.ack_flags, "entries": args.ack_entries,
                 "dest": args.ack_dest_bits}

    def ack_variant(elapsed):
        """The shape our acks carry now, and a line when the sweep moves on."""
        if not args.ack_sweep:
            return
        i = int(elapsed // args.ack_sweep_period) % len(sweep)
        if i != ack_shape["i"]:
            ack_shape.update(i=i, flags=sweep[i][0], entries=sweep[i][1], dest=sweep[i][2])
            print(f"[sv] ack shape {i + 1}/{len(sweep)}: flags {sweep[i][0]:#04x}, "
                  f"{sweep[i][1]} entr{'y' if sweep[i][1] == 1 else 'ies'}, "
                  f"{sweep[i][2]} destination bits")
            record(rec="ack_shape", index=i, flags=sweep[i][0], entries=sweep[i][1],
                   dest_bits=sweep[i][2], t=time.time())

    def our_ack(key):
        """A bulk ack for one stream in the shape the sweep currently says."""
        if args.ack_highest:
            through, masks = stream_high.get(key, 0), None
        else:
            through, mask = streams.ack_position(stream_got.get(key, ()), peer_lowest.get(key, 1))
            masks = {streams.HOST_INDEX: mask}
        return streams.build_ack({streams.HOST_INDEX: through},
                                 our_seq.get(key, 1), streams.JOINER_INDEX,
                                 entry_count=ack_shape["entries"],
                                 destination_bits=ack_shape["dest"], masks=masks)
    player_id = {"arceus": pia6.DEFAULT_PLAYER_ID, "random": os.urandom(16),
                 "high": b"\xff" + os.urandom(15)}.get(args.join_player_id)
    if player_id is None:
        player_id = bytes.fromhex(args.join_player_id)

    def out(body, dst_var, **kw):
        return build_out(keys, our_ip, body, dst_var, src_var=ours["var"], **kw)

    def send(pkt, what, to=None, **extra):
        to = to or dest_ip
        sock.sendto(pkt, (to, sv.PIA_PORT))
        record(rec="out", dst=to, kind=what, hex=pkt.hex(), t=time.time(), **extra)

    def next_seq(protocol, port):
        """-> our next sequence on one stream, stepping it. Every send goes through here, so the
        bulk acks state the same number as their window's lowest pending: a sender's own lowest
        pending is what drives its peer's receive base (docs/pia.md)."""
        key = (protocol, port)
        seq = our_seq.get(key, 1)
        our_seq[key] = seq + 1
        return seq

    def send_channel(port, payload, what, flags=None):
        """A 0x7c data message under our own next sequence on that port. 0x7c carries no
        destination bitmap and states its own sequence as the lowest pending."""
        seq = next_seq(PROTO_RELIABLE, port)
        if flags is None:
            body = game_channel.build_open(payload, seq, initialized=(seq == 1))
        else:
            body = game_channel.build_payload_message(
                payload, seq,
                flags=flags | (reliable5.FLAG_IS_INITIALIZED if seq == 1 else 0))
        send(out(body, host_var or 0, protocol=PROTO_RELIABLE, port=port),
             what, port=port, to=host_ip, seq=seq)
        return seq

    def send_join():
        # The host's constant id is the one its own Net 0x11 states, not the LDN MAC from the
        # participant list: on the GBA app those differ, and the join must address the stated one.
        body = pia6.build_session_join(
            our_const, ours["var"], our_ip, host_const, host_var or 0, args.join_player_name,
            os.urandom(4), player_id=player_id)
        dst = (host_var or 0) if args.join_dst_var == "host" else 0
        # A Session message is addressed to one station, so it goes to the host's own address
        # whatever the mesh-addressed messages go to (a joining Arceus sent its to the host's IP).
        send(out(body, dst, protocol=PROTO_SESSION, flags=args.join_flags), "session join request",
             to=host_ip)
        print(f"[sv] -> {host_ip}: session join request (type 0, {len(body)} bytes), "
              f"host_var={host_var if host_var is None else hex(host_var)}, "
              f"host_const={host_const.hex()}, header dst_var={dst}")

    def send_update_ack(upd):
        if args.no_update_ack or upd["sequence_id"] < (join_sequence or 0):
            return
        ack = pia_connect.build_session_update_ack_v11(our_const, upd["sequence_id"])
        send(out(ack, host_var or 0, protocol=PROTO_SESSION), "session update ack", to=host_ip)
        print(f"[sv] -> {host_ip}: session update ack (type 6), sequence {upd['sequence_id']}")

    def send_opening():
        """The eleven bulk acks and the two stream opens a retail joiner sends at once, 0.9 s
        after it associates (sv11). Everything is one packet per message, as the console sends it."""
        for protocol, port in streams.every_stream():
            body = streams.build_ack({}, 1, streams.JOINER_INDEX, unknown0=1,
                                     entry_count=ack_shape["entries"],
                                     destination_bits=ack_shape["dest"])
            send(out(body, host_var or 0, protocol=protocol, port=port,
                           flags=ack_shape["flags"]), "reliable ack", protocol=protocol,
                 port=port)
            last_ack[(protocol, port)] = time.time()
            if port in streams.OPEN_PORTS[streams.JOINER_INDEX] and protocol == streams.PROTOCOL_STREAM:
                body = streams.build_open(port, streams.JOINER_INDEX)
                our_seq[(protocol, port)] = 2
                send(out(body, host_var or 0, protocol=protocol, port=port,
                               flags=streams.MESSAGE_FLAGS_DATA), "stream open",
                     protocol=protocol, port=port)
        print(f"[sv] -> {host_ip}: eleven acks and the two stream opens "
              f"(0x81 ports {streams.OPEN_PORTS[streams.JOINER_INDEX]})")

    print(f"[sv] host {host_ip} ({host_mac.hex()}), us {our_ip} ({our_mac.hex()}), "
          f"sending to {dest_ip}; listening on {sv.PIA_PORT} for {args.hold}s")
    opened = False
    last_rtt = 0.0
    pending_rtt = []            # (due, request payload, requester var)
    while time.monotonic() - t0 < args.hold:
        now = time.time()
        for due, request, requester in [e for e in pending_rtt if e[0] <= now]:
            send(out(streams.build_rtt_response(request, requester), requester,
                     protocol=PROTO_RTT), "rtt response")
        pending_rtt = [e for e in pending_rtt if e[0] > now]
        elapsed = time.monotonic() - t0
        if (args.quiet_seat is not None and seen == 0
                and time.monotonic() - last_in >= args.quiet_seat):
            print(f"[sv] the seat is silent: nothing from the console in "
                  f"{args.quiet_seat:.1f} s. Scanning again")
            record(rec="left_silent_seat", t=time.time())
            break
        if (args.announce_timeout is not None and args.game_channel and not channel["port2"]
                and elapsed >= args.announce_timeout):
            print(f"[sv] the seat was never announced in {args.announce_timeout:.1f} s. "
                  f"Scanning again")
            record(rec="left_unannounced", t=time.time())
            break
        if (args.leave_on_migration is not None and migration_at is not None
                and time.monotonic() - migration_at >= args.leave_on_migration):
            print(f"[sv] the seat is spent: the console asked for the host role "
                  f"{args.leave_on_migration:.1f} s ago. Scanning again")
            record(rec="left_after_migration", t=time.time())
            break
        ack_variant(elapsed)
        # A retail joiner's opening follows its join by about 0.75 s (sv11: the join at 0.14 s, the
        # opening at 0.89 s). With --session-join the opening waits for the seat.
        if not opened and elapsed >= args.open_delay and (
                not args.session_join or (joined_at and now - joined_at >= args.open_delay)):
            opened = True
            send_opening()
        # The host addresses the joiner by its variable id 0.14 s after the association, before the
        # joiner has broadcast anything (sv11), so something unicast carries that id to it. The
        # Session join request is the only message in the band that states a station's own ids, and
        # a unicast one would not appear in a passive capture.
        if args.session_join and host_var is not None and not joined and (
                join_sent == 0.0 or (args.join_repeat and now - join_sent >= args.join_repeat)):
            join_sent = now
            send_join()
        # Our identity record on 0x81 port 1 (our station stream), retransmitted every 0.25 s
        # until the host's bulk ack for port 1 names it. A retail joiner sends this at ~0.9 s.
        if identity is not None and joined and not record_acked and (
                now - joined_at >= args.record_delay) and (now - last_record_send >= 0.25):
            last_record_send = now
            body = streams.build_record_message(identity, record_seq, streams.JOINER_INDEX,
                                                initialized=(record_seq == 1))
            send(out(body, host_var or 0, protocol=streams.PROTOCOL_STREAM,
                     port=streams.JOINER_INDEX, flags=streams.MESSAGE_FLAGS_DATA),
                 "identity record", port=streams.JOINER_INDEX)
            our_seq[(streams.PROTOCOL_STREAM, streams.JOINER_INDEX)] = record_seq + 1
        # A retail joiner sends its own RTT request about twice a second from the moment it is
        # seated, and it is the first thing it puts on the wire.
        if args.rtt_period and opened and now - last_rtt >= args.rtt_period:
            last_rtt = now
            clock = int(time.monotonic() * 1e6) & ((1 << 64) - 1)
            send(out(streams.build_rtt_request(clock.to_bytes(8, "big")),
                           host_var or 0, protocol=PROTO_RTT), "rtt request")
        # Our own channel table, once the opening has gone and the host's table is in hand.
        if args.game_channel and opened and channel["table"] and not channel["opened"]:
            channel["opened"] = True
            send_channel(1, channel["table"], "channel table")
            print(f"[sv] -> {host_ip}: our own channel table on 0x7c port 1 "
                  f"({len(channel['table'])} bytes)")
            if args.port2_now:
                channel["port2"] = True
                send_channel(2, CHANNEL_PORT2_OPEN, "channel port 2 open")
                print(f"[sv] -> {host_ip}: the port-2 join, without waiting for an announcement")
        # Our own identity, as a whole set of records under their original sequence ids.
        if record_set and joined and not set_sent and now - joined_at >= args.record_delay:
            set_sent = True
            for seq, payload in record_set:
                body = streams.build_record_message(payload, seq, streams.JOINER_INDEX,
                                                    initialized=(seq == record_set[0][0]))
                send(out(body, host_var or 0, protocol=streams.PROTOCOL_STREAM,
                         port=streams.JOINER_INDEX, flags=streams.MESSAGE_FLAGS_DATA),
                     "record set", port=streams.JOINER_INDEX, seq=seq)
            # Our next bulk ack on our own stream declares one past the highest id we sent, which
            # is what closes a set numbered with the reference's gap at 5 and 6: left at 1 the
            # host acknowledges id 5 and waits for the rest of the set for the whole session
            # (docs/sv.md, The sender's own lowest pending).
            our_seq[(streams.PROTOCOL_STREAM, streams.JOINER_INDEX)] = max(
                seq for seq, _ in record_set) + 1
            print(f"[sv] -> {host_ip}: our identity, {len(record_set)} records on 0x81 port 1, "
                  f"our next sequence there {our_seq[(streams.PROTOCOL_STREAM, streams.JOINER_INDEX)]}")
        for due, spec in [e for e in pending_open if e[0] <= now]:
            proto, port, hx = spec.split(":", 2)
            proto, port = int(proto, 0), int(port)
            data, flags = streams.parse_send_spec(hx)
            if proto == PROTO_RELIABLE:
                send_channel(port, data, "send-on-open", flags=flags)
            else:
                seq = next_seq(proto, port)
                body = streams.build_record_message(data, seq, streams.JOINER_INDEX,
                                                    initialized=(seq == 1))
                send(out(body, host_var or 0, protocol=proto, port=port,
                         flags=streams.MESSAGE_FLAGS_DATA), "send-on-open",
                     protocol=proto, port=port, seq=seq)
            print(f"[sv] -> {host_ip}: send-on-open {len(data)}B on "
                  f"0x{proto:02x}:{port} {data.hex()[:48]}")
        pending_open = [e for e in pending_open if e[0] > now]
        for due, out_port, payload in [e for e in pending_trade if e[0] <= now]:
            seq = send_channel(out_port, payload, "trade")
            print(f"[sv] -> {host_ip}: trade {payload[:4].hex()} on 0x7c port {out_port}, "
                  f"our sequence {seq}")
        pending_trade = [e for e in pending_trade if e[0] > now]
        if not args.no_ack:
            for key, at in list(last_ack.items()):
                if now - at >= args.ack_period:
                    protocol, port = key
                    body = our_ack(key)
                    send(out(body, host_var or 0, protocol=protocol,
                                   port=port, flags=ack_shape["flags"]), "reliable ack",
                         protocol=protocol, port=port)
                    last_ack[key] = now
        # Wait in trio, never in select(): on the ESP32 board the frames reach this socket through
        # trio tasks, and a blocking wait starves them, 50 ms per packet (docs/hardware_esp32.md).
        ready = False
        with trio.move_on_after(0.05):
            await trio.lowlevel.wait_readable(sock)
            ready = True
        if not ready:
            continue
        try:
            data, addr = sock.recvfrom(4096)
        except OSError:
            continue
        if addr[0] == our_ip:
            continue
        seen += 1
        last_in = time.monotonic()
        record(rec="in", src=addr[0], hex=data.hex(), t=time.time())
        if not pia6.is_pia6(data):
            print(f"[sv] <- {addr[0]}: not a version-11 packet, {data[:8].hex()}")
            continue
        header, plain, ids = pia6.parse_packet(keys.session_key, addr[0], keys.network_id, data)
        if plain is None:
            print(f"[sv] <- {addr[0]}: {header!r} DID NOT AUTHENTICATE")
            continue
        authed += 1
        if host_var is None:
            host_var = header.src_var
            print(f"[sv] the host's variable id is {host_var:#06x}")
            # A host that drew our fallback id for itself drops a join whose source id is its own
            # (a Ryujinx host did, sv27). Draw another before anything states ours.
            if not ours["assigned"] and ours["var"] == host_var:
                while ours["var"] in (0, host_var):
                    ours["var"] = int.from_bytes(os.urandom(2), "big")
                print(f"[sv] the host holds our fallback id; ours is now {ours['var']:#06x}")
        # The footer of a mesh-addressed packet names its recipients. A host that has created a
        # station for us names the id it gave us there, and that id is ours from then on.
        if not ours["assigned"]:
            for fid in ids:
                if fid not in (0, host_var):
                    ours.update(var=fid, assigned=True)
                    print(f"[sv] the host assigned us variable id {fid:#06x}")
                    break
        try:
            msgs = list(pia6.parse_messages(plain))
        except Exception as exc:
            print(f"[sv] <- {addr[0]}: messages did not parse: {exc} {plain.hex()}")
            continue
        for msg in msgs:
            counts[msg.protocol] = counts.get(msg.protocol, 0) + 1
            record(rec="msg", src=addr[0], protocol=msg.protocol, port=msg.port,
                   flags=msg.message_flags, src_var=header.src_var, dst_var=header.dst_var,
                   payload=msg.payload.hex(), t=time.time())
            if msg.protocol not in (PROTO_RTT,) or args.verbose_rtt:
                print(f"[sv] <- {addr[0]} {_describe_msg(msg)}  {msg.payload.hex()[:160]}")
            if msg.protocol == PROTO_NET and len(msg.payload) > 1:
                req = pia_connect.parse_net_conn_request(msg.payload)
                if req is not None:
                    stated_var, stated_const, seqid = req
                    if (stated_var, stated_const) != (host_var, host_const):
                        host_var, host_const = stated_var, stated_const
                        print(f"[sv] the console states host_var={host_var:#06x} "
                              f"host_const={host_const.hex()}")
                    if args.net_ack:
                        send(out(pia_connect.build_net_response(seqid), 0,
                                       protocol=PROTO_NET, flags=ESTABLISHING_FLAGS),
                             "net conn response", seqid=seqid)
                        print(f"[sv] -> {host_ip}: net 0x12 ack, seqid={seqid}")
                # The host's 0x50 carries its own sequence at [4:8], and a joiner answers it with a
                # 0x51 of the same shape as the 0x12 (a pair: 0x50 sequence 1, 0x51 sequence 1).
                if args.net_ack and len(msg.payload) >= 8 and msg.payload[0] == 1 \
                        and msg.payload[1] == NET_0x50:
                    seq50 = int.from_bytes(msg.payload[4:8], "big")
                    body = bytes([0x01, NET_0x51, 0, 0]) + seq50.to_bytes(4, "big")
                    send(out(body, 0, protocol=PROTO_NET, flags=ESTABLISHING_FLAGS),
                         "net 0x51", seqid=seq50)
                    print(f"[sv] -> {host_ip}: net 0x51 ack, seqid={seq50}")
            if msg.protocol == PROTO_SESSION and msg.payload:
                kind = msg.payload[0]
                print(f"[sv] the host spoke Session: {SESSION_MESSAGE_NAMES.get(kind, '?')}")
                if kind == pia_connect.SESSION_JOIN_RESPONSE:
                    resp = pia_connect.parse_session_join_response_v11(msg.payload)
                    if resp is None:
                        print(f"[sv] join response did not parse: {msg.payload.hex()}")
                    else:
                        print(f"[sv] JOIN RESPONSE status {resp['status']} ({resp['status_name']}), "
                              f"protocol {resp['protocol']:#04x} v{resp['version']}, "
                              f"station index {resp['station_index']}, route {resp['route']}, "
                              f"join order {resp['join_order']}, sequence {resp['sequence_id']}")
                        record(rec="join_response", t=time.time(), **{
                            k: (v.hex() if isinstance(v, bytes) else v) for k, v in resp.items()})
                        if resp["status"] == 1:
                            joined = True
                            joined_at = now
                            if not args.no_clock:
                                send(out(CLOCK_REQUEST, host_var or 0, protocol=PROTO_CLOCK),
                                     "clock request")
                                print(f"[sv] -> {host_ip}: the clone clock request")
                            join_sequence = resp["sequence_id"]
                            if pending_update is not None:
                                send_update_ack(pending_update)
                                pending_update = None
                elif kind == pia_connect.SESSION_UPDATE:
                    upd = pia_connect.parse_session_update_v11(msg.payload, route_bytes=0)
                    if upd is None:
                        print(f"[sv] station update did not parse: {msg.payload.hex()}")
                    else:
                        print(f"[sv] STATION UPDATE sequence {upd['sequence_id']}, "
                              f"{len(upd['stations'])} station(s): "
                              + " ".join(f"{st['ip']}#{st['station_index']}/var {st['variable_id']:#06x}"
                                         f"/player {st['players'][0]['player_id'].hex() if st['players'] else '-'}"
                                         for st in upd["stations"]))
                        record(rec="station_update", t=time.time(), sequence=upd["sequence_id"],
                               stations=[{k: (v.hex() if isinstance(v, bytes) else v)
                                          for k, v in st.items() if k != "players"}
                                         for st in upd["stations"]])
                        # A retail Scarlet seats a joiner with this update alone and sends no
                        # join response at all: the update names our variable id and the player id
                        # our request stated. That is the seat, and a joiner that waits for a type
                        # 1 sends nothing for the rest of the session (sv83).
                        if not joined and any(st["variable_id"] == ours["var"]
                                              for st in upd["stations"]):
                            joined = True
                            joined_at = now
                            join_sequence = upd["sequence_id"]
                            print(f"[sv] the station update SEATS US at variable id "
                                  f"{ours['var']:#06x}; no join response was sent")
                            record(rec="seated_by_update", t=time.time(),
                                   sequence=upd["sequence_id"], var=ours["var"])
                            if not args.no_clock:
                                send(out(CLOCK_REQUEST, host_var or 0, protocol=PROTO_CLOCK),
                                     "clock request")
                                print(f"[sv] -> {host_ip}: the clone clock request")
                        # A joiner answers with the type 6 once it holds the join response and an
                        # update whose sequence reaches the one the response named (docs/pla.md,
                        # The type-5 station-list update). The host sends the update first (sv18).
                        if join_sequence is None:
                            pending_update = upd
                        else:
                            send_update_ack(upd)
                elif kind == pia_connect.SESSION_JOIN_ACK:
                    print(f"[sv] the host acknowledged the join request; it now has 8 s to answer it")
                elif kind == 7:
                    migration_sent += 1
                    if migration_at is None:
                        migration_at = time.monotonic()
                    mig = pia_connect.parse_session_migration_v11(msg.payload)
                    print(f"[sv] the host is LEAVING WITH HOST MIGRATION to us ({migration_sent}x): "
                          f"target var {mig['target_var']:#06x}" if mig else msg.payload.hex())
                    if args.answer_migration and mig and mig["target_var"] == ours["var"]:
                        ack = pia_connect.build_session_migration_ack_v11(
                            mig["target_constant_id"], mig["target_var"],
                            mig["host_constant_id"], mig["host_var"])
                        send(out(ack, host_var or 0, protocol=PROTO_SESSION),
                             "migration ack", to=host_ip)
                        print(f"[sv] -> {host_ip}: start-host-migration ack (type 8)")
            if msg.protocol == PROTO_CLOCK:
                print(f"[sv] <- the host answered the clone clock: {msg.payload.hex()}")
            if not args.no_rtt and msg.protocol == PROTO_RTT and msg.payload and msg.payload[0] == 0:
                if args.rtt_delay > 0:
                    pending_rtt.append((time.time() + args.rtt_delay, msg.payload, header.src_var))
                else:
                    send(out(streams.build_rtt_response(msg.payload, header.src_var),
                             header.src_var, protocol=PROTO_RTT), "rtt response")
            # The game's own unicast channel, Reliable 0x7c: the host opens its channel table on
            # port 1 (sv18: `b90104b902b9027b0001...`, the Arceus form, pokeldn.pla.channel_table)
            # and retransmits every 65 ms until the one-entry ack Arceus's host answers with.
            if msg.protocol == PROTO_RELIABLE and len(msg.payload) >= reliable5.HEADER_SIZE:
                try:
                    cm = reliable5.parse(msg.payload)
                except ValueError as exc:
                    print(f"[sv] 0x7c did not parse: {exc}")
                    continue
                if cm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                    print(f"[sv] <- CHANNEL 0x7c:{msg.port} seq {cm['sequence_id']} "
                          f"{reliable5.flag_names(cm['flags'])} {cm['payload'].hex()}")
                    record(rec="channel", src=addr[0], port=msg.port, seq=cm["sequence_id"],
                           flags=cm["flags"], payload=cm["payload"].hex(), t=time.time())
                    if args.game_channel and cm["flags"] & reliable5.FLAG_IS_INITIALIZED \
                            and msg.port == 1 and channel["table"] is None:
                        # Held until the eleven acks and the stream opens have gone: a pair's
                        # joiner announces its table in the same breath as its opening, never
                        # before it (docs/sv.md).
                        channel["table"] = cm["payload"]
                    elif args.game_channel and msg.port == 1 and channel["opened"] \
                            and stage is None \
                            and not (cm["flags"] & reliable5.FLAG_IS_INITIALIZED):
                        # Every later table update is mirrored back under our own sequence. With a
                        # trade stage the mirror is its own: it answers each open and close in the
                        # order a pair's joiner does, and nothing else on port 1.
                        seq = send_channel(1, cm["payload"], "channel table update")
                        print(f"[sv] -> {host_ip}: mirrored the channel table update "
                              f"({len(cm['payload'])} bytes), our sequence {seq}")
                    if not args.no_channel_ack:
                        # The lowest pending is OUR own next sequence on this port, not one drawn
                        # from the host's numbering: the field is the peer's receive base, and a
                        # station declaring a number above its own next sequence walks that base
                        # past its own later messages, which then arrive below it and are
                        # acknowledged and discarded at 0x6f03cc (docs/pia.md).
                        ack = game_channel.build_ack(
                            cm["sequence_id"] + 1,
                            lowest_pending=our_seq.get((PROTO_RELIABLE, msg.port), 1))
                        send(out(ack, host_var or 0, protocol=PROTO_RELIABLE, port=msg.port),
                             "channel ack", port=msg.port, to=host_ip)
                    if (msg.port == 1 and not channel["key80"]
                            and cm["payload"] == trade.table_update(trade.KEY_TRADE, True)):
                        # The host's own open of the trade key. Nothing sent on port 0 before it
                        # reaches the game, and neither does anything sent after it on that port.
                        channel["key80"] = True
                        print(f"[sv] the host opened key 0x80, "
                              f"{len(args.send_on_open)} send(s) follow")
                        for spec in args.send_on_open:
                            delay, rest = spec.split(":", 1)
                            pending_open.append((time.time() + float(delay), rest))
                        if stage is not None and args.offer_after_open is not None:
                            for delay, out_port, payload in stage.offer_first():
                                schedule_trade(args.offer_after_open + delay, out_port, payload)
                    if stage is not None:
                        for delay, out_port, payload in stage.on_message(msg.port, cm["payload"]):
                            schedule_trade(delay, out_port, payload)
                        while offers_seen < len(stage.host_offers):
                            body = stage.host_offers[offers_seen]
                            offers_seen += 1
                            print(f"[sv] {host_ip}: offers {describe_offer(body)}")
                            if args.offer_out:
                                path = (args.offer_out if offers_seen == 1
                                        else f"{args.offer_out}.{offers_seen}")
                                with open(path, "w") as fh:
                                    fh.write(trade.build(trade.KEY_TRADE, trade.KIND_OFFER, 0,
                                                         body).hex() + "\n")
                                print(f"[sv] the host's offer written to {path}")
                        if stage.trades > trades_done:
                            trades_done = stage.trades
                            record(rec="trade_done", n=trades_done, t=time.time())
                            if stage.done:
                                print(f"[sv] TRADE {trades_done} COMPLETE; no record left to offer")
                            else:
                                print(f"[sv] TRADE {trades_done} COMPLETE; offering "
                                      f"{describe_offer(stage.offer)} next")
                                if args.offer_after_open is not None:
                                    for delay, out_port, payload in stage.offer_first():
                                        schedule_trade(args.offer_after_open + delay,
                                                       out_port, payload)
                continue
            if msg.protocol in RELIABLE_PROTOCOLS and len(msg.payload) >= reliable5.HEADER_SIZE:
                try:
                    rm = reliable5.parse(msg.payload)
                except ValueError as exc:
                    print(f"[sv] reliable did not parse: {exc}")
                    continue
                key = (msg.protocol, msg.port)
                peer_lowest[key] = max(peer_lowest.get(key, 1), rm["lowest_pending"])
                if (identity is not None and not record_acked and rm.get("is_ack")
                        and msg.protocol == streams.PROTOCOL_STREAM and msg.port == streams.JOINER_INDEX):
                    e = reliable5.parse_ack_payload(rm["payload"])
                    if len(e["entries"]) > streams.JOINER_INDEX and \
                            e["entries"][streams.JOINER_INDEX]["ack_id"] > record_seq:
                        record_acked = True
                        print(f"[sv] the host ACKNOWLEDGED our identity record on port 1")
                if rm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                    body = rm["payload"]
                    note = ""
                    if rm["flags"] & reliable5.FLAG_ZLIB:
                        try:
                            body = streams.decompress(body)
                            note = f" zlib -> {len(body)}B"
                        except Exception as exc:
                            note = f" zlib failed: {exc}"
                    print(f"[sv] <- RECORD 0x{msg.protocol:02x}:{msg.port} seq {rm['sequence_id']} "
                          f"{reliable5.flag_names(rm['flags'])} {len(rm['payload'])}B{note}")
                    print(f"       {body.hex()[:400]}")
                    if (args.game_channel and msg.protocol == PROTO_BROADCAST_RELIABLE
                            and msg.port == 2 and body[:1] == bytes([port2.TYPE_ANNOUNCE])
                            and not channel["port2"]):
                        # The console's own trade announcement. A pair's joiner answers it with the
                        # type-3 join 0.09 s later, and the host then sends the type 9 carrying the
                        # joiner's station id (docs/sv.md, Port 2).
                        channel["port2"] = True
                        station = body[-9:-1].hex() if len(body) > 9 else "?"
                        print(f"[sv] the console ANNOUNCED on 0x80 port 2, station {station}")
                        record(rec="announce", station=station, plain=body.hex(), t=time.time())
                        send_channel(2, CHANNEL_PORT2_OPEN, "channel port 2 join")
                        print(f"[sv] -> {host_ip}: the type-3 join on 0x7c port 2")
                    if (args.mirror_records and joined and msg.protocol == streams.PROTOCOL_STREAM
                            and msg.port == streams.HOST_INDEX and rm["sequence_id"] not in mirrored):
                        mirrored.add(rm["sequence_id"])
                        back = streams.build_record_message(
                            rm["payload"], record_seq, streams.JOINER_INDEX,
                            initialized=(record_seq == 1))
                        send(out(back, host_var or 0, protocol=streams.PROTOCOL_STREAM,
                                 port=streams.JOINER_INDEX, flags=streams.MESSAGE_FLAGS_DATA),
                             "mirrored record", port=streams.JOINER_INDEX, seq=record_seq)
                        record_seq += 1
                    record(rec="data", src=addr[0], protocol=msg.protocol, port=msg.port,
                           seq=rm["sequence_id"], flags=rm["flags"],
                           payload=rm["payload"].hex(),
                           plain=body.hex() if note.startswith(" zlib ->") else None,
                           t=time.time())
                    stream_high[key] = max(stream_high.get(key, 0), rm["sequence_id"])
                    got = stream_got.setdefault(key, set())
                    repeat = rm["sequence_id"] in got
                    got.add(rm["sequence_id"])
                    # A host retransmitting its set sends ~140 repeats a second, and one ack each
                    # nearly fills what the board transmits (docs/sv.md).
                    held_off = repeat and time.time() - last_ack.get(key, 0.0) < args.repeat_ack_gap
                    if not args.no_ack and not held_off:
                        ack = our_ack(key)
                        send(out(ack, host_var or 0, protocol=msg.protocol,
                                       port=msg.port, flags=ack_shape["flags"]),
                             "reliable ack", protocol=msg.protocol, port=msg.port)
                        last_ack[key] = time.time()
                if key not in last_ack:
                    last_ack[key] = 0.0
    sock.close()
    print(f"[sv] seat over: {seen} datagram(s) in, {authed} authenticated. messages by protocol: "
          + " ".join(f"0x{p:02x}={n}" for p, n in sorted(counts.items())))


if __name__ == "__main__":
    sys.exit(main())

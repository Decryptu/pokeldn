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
import select
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
from pokeldn.sv import streams
from pokeldn.pla import game_channel
from pokeldn.ldn.transport import find_ap_phy
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
ESTABLISHING_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK
# The variable id we send as our own until the host assigns one. A retail joiner does not invent
# one: the host names the joiner's id in the plaintext footer of its first mesh-addressed packet,
# 0.14 s after the association and before the joiner has sent anything, and the joiner then uses
# that value as its own source id (`docs/sv.md`). This is the fallback for a host that never does.
OUR_VAR = 0xC493
OUR_STATION_INDEX = 1
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
    ap.add_argument("--record-delay", type=float, default=0.9,
                    help="seconds after the seat before the first identity record goes out")
    ap.add_argument("--no-channel-ack", action="store_true",
                    help="do not acknowledge the host's messages on the game's reliable channel 0x7c")
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
    ap.add_argument("--open-delay", type=float, default=0.75,
                    help="seconds after the join response (after the seat without --session-join) "
                         "before the eleven acks and the two stream opens go out; a retail joiner "
                         "opens 0.75 s after its join")
    ap.add_argument("--rtt-period", type=float, default=0.4,
                    help="seconds between our own RTT requests (0 sends none)")
    ap.add_argument("--no-rtt", action="store_true", help="do not answer RTT requests")
    ap.add_argument("--no-ack", action="store_true", help="do not acknowledge reliable streams")
    ap.add_argument("--ack-period", type=float, default=1.0,
                    help="seconds between the periodic bulk acks on every stream the host uses")
    ap.add_argument("--unicast", action="store_true",
                    help="send to the host's address instead of the LDN broadcast address. Both "
                         "retail stations broadcast every Pia packet (sv11), and a broadcast needs "
                         "no ARP resolution of the peer")
    ap.add_argument("--verbose-rtt", action="store_true", help="print the RTT traffic too")
    ap.add_argument("--capture", default=None, help="write every datagram here as JSON lines")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.ip_join:
        return main_ip(args)
    if os.geteuid() != 0:
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
                async with ldn.connect(param) as network:
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
                print(f"[sv] the seat ended: {type(exc).__name__}: {exc}")
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
    identity = None
    if args.send_record:
        identity = streams.compress(open(args.send_record, "rb").read())
    record_seq = 1
    record_acked = False
    last_record_send = 0.0
    stream_high = {}            # (protocol, port) -> highest sequence received from the host
    our_seq = {}                # (protocol, port) -> our next send sequence on that stream
    last_ack = {}
    counts = {}
    seen = authed = 0

    # Both retail stations address every Pia datagram to the link-local broadcast of their own
    # /24 (sv11: 169.254.86.2 -> 169.254.86.255), never to the peer's address.
    # Over the LAN the emulated host is one address, and the IP host direction sends unicast too.
    dest_ip = host_ip if (args.unicast or args.ip_join) else our_ip.rsplit(".", 1)[0] + ".255"

    ours = {"var": OUR_VAR, "assigned": False}
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

    def send_join():
        # The host's constant id is the one its own Net 0x11 states, not the LDN MAC from the
        # participant list: on the GBA app those differ, and the join must address the stated one.
        body = pia6.build_session_join(
            our_const, OUR_VAR, our_ip, host_const, host_var or 0, args.join_player_name,
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
            body = streams.build_ack({}, 1, streams.JOINER_INDEX, unknown0=1)
            send(out(body, host_var or 0, protocol=protocol, port=port,
                           flags=streams.MESSAGE_FLAGS_ACK), "reliable ack", protocol=protocol,
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
    while time.monotonic() - t0 < args.hold:
        now = time.time()
        elapsed = time.monotonic() - t0
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
            body = streams.build_record_message(identity, record_seq, streams.JOINER_INDEX)
            send(out(body, host_var or 0, protocol=streams.PROTOCOL_STREAM,
                     port=streams.JOINER_INDEX, flags=streams.MESSAGE_FLAGS_DATA),
                 "identity record", port=streams.JOINER_INDEX)
        # A retail joiner sends its own RTT request about twice a second from the moment it is
        # seated, and it is the first thing it puts on the wire.
        if args.rtt_period and opened and now - last_rtt >= args.rtt_period:
            last_rtt = now
            clock = int(time.monotonic() * 1e6) & ((1 << 64) - 1)
            send(out(streams.build_rtt_request(clock.to_bytes(8, "big")),
                           host_var or 0, protocol=PROTO_RTT), "rtt request")
        if not args.no_ack:
            for key, at in list(last_ack.items()):
                if now - at >= args.ack_period:
                    protocol, port = key
                    body = streams.build_ack({streams.HOST_INDEX: stream_high.get(key, 0)},
                                             our_seq.get(key, 1), streams.JOINER_INDEX)
                    send(out(body, host_var or 0, protocol=protocol,
                                   port=port, flags=streams.MESSAGE_FLAGS_ACK), "reliable ack",
                         protocol=protocol, port=port)
                    last_ack[key] = now
        ready = select.select([sock], [], [], 0.05)[0]
        if not ready:
            await trio.sleep(0)
            continue
        try:
            data, addr = sock.recvfrom(4096)
        except OSError:
            continue
        if addr[0] == our_ip:
            continue
        seen += 1
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
            if not args.no_rtt and msg.protocol == PROTO_RTT and msg.payload and msg.payload[0] == 0:
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
                    if not args.no_channel_ack:
                        ack = game_channel.build_ack(cm["sequence_id"] + 1,
                                                     lowest_pending=cm["sequence_id"])
                        send(out(ack, host_var or 0, protocol=PROTO_RELIABLE, port=msg.port),
                             "channel ack", port=msg.port, to=host_ip)
                continue
            if msg.protocol in RELIABLE_PROTOCOLS and len(msg.payload) >= reliable5.HEADER_SIZE:
                try:
                    rm = reliable5.parse(msg.payload)
                except ValueError as exc:
                    print(f"[sv] reliable did not parse: {exc}")
                    continue
                key = (msg.protocol, msg.port)
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
                    record(rec="data", src=addr[0], protocol=msg.protocol, port=msg.port,
                           seq=rm["sequence_id"], flags=rm["flags"],
                           payload=rm["payload"].hex(),
                           plain=body.hex() if note.startswith(" zlib ->") else None,
                           t=time.time())
                    stream_high[key] = max(stream_high.get(key, 0), rm["sequence_id"])
                    if not args.no_ack:
                        ack = streams.build_ack({streams.HOST_INDEX: stream_high[key]},
                                                our_seq.get(key, 1), streams.JOINER_INDEX)
                        send(out(ack, host_var or 0, protocol=msg.protocol,
                                       port=msg.port, flags=streams.MESSAGE_FLAGS_ACK),
                             "reliable ack", protocol=msg.protocol, port=msg.port)
                        last_ack[key] = time.time()
                if key not in last_ack:
                    last_ack[key] = 0.0
    sock.close()
    print(f"[sv] seat over: {seen} datagram(s) in, {authed} authenticated. messages by protocol: "
          + " ".join(f"0x{p:02x}={n}" for p, n in sorted(counts.items())))


if __name__ == "__main__":
    sys.exit(main())

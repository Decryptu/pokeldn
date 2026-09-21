#!/usr/bin/env python3
"""Join a Legends Arceus network the console is hosting, and let its Pia speak to us.

The game alternates: a station open and one second of scanning, then two to four seconds hosting
its own network, then teardown, on a five-second cycle. It registers its Pia protocols only while
it is HOSTING; as a joiner it registers none, which is why a packet sent to it while it sits in our
network is parsed, accounted for, and then routed to nobody. So the session has to be entered from
the other side: we join the network it puts up, and its Pia is the one that is running.

    ./.venv/bin/python bin/pla_join.py --ip-join --host-ip 172.16.86.1 --our-ip 172.16.86.128

The host window is short, so this scans in a loop and joins the moment the network appears. Over
ldn_mitm nothing here needs root or a radio. Every datagram goes to --capture as one JSON line.
`docs/pla.md` has the layouts.
"""
import argparse
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import pla
from pokeldn.ldn import ldn_mitm, pia6, pia_connect

PROTO_NET = 0x2C
PROTO_SESSION = 0x98
# [wiki Net-Protocol] 0x11 update network connection status, 0x12 its ack, 0x40 start host
# migration, 0x41 update network host. A console whose 0x40 goes unanswered repeats it twice a
# second and sends nothing else.
NET_CONN_STATUS = 0x11
NET_CONN_STATUS_ACK = 0x12
NET_START_HOST_MIGRATION = 0x40
NET_UPDATE_NETWORK_HOST = 0x41
PROTO_RTT = 0x58
ESTABLISHING_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK


def establishing_flags(args):
    """0x01 skip-source-check by default. At this band, hosting side, 0x01 takes the branch at
    main+0x74432c that skips the station lookup and sets no wake bit, so --no-skip-source-check
    (flags 0) is the path that can wake the session when the console has a station for us."""
    return ESTABLISHING_FLAGS if getattr(args, "skip_source_check", True) else 0

# Our own station's variable id. A joiner invents one and states it; the host learns it from the
# packets we send, which is the direction that works. 6.32's joiner uses the same constant.
OUR_VAR = 0xC493


def scan_once(our_ip, host_ip, timeout):
    """-> the host's NetworkInfo, or None. The scan must leave from our own address: ldn_mitm drops
    one whose source is the host's own address, and answers to wherever it came from."""
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


def fast_scan(sock, host_ip, interval, deadline, last_ssid):
    """A tight scan: send SCAN and poll non-blocking every `interval` until a ScanResp for an SSID
    other than `last_ssid` arrives, or `deadline` passes. Returns (NetworkInfo, t_seen) or (None, _).

    The host latches its node list once when it creates the network, so the joiner has to be present
    before that latch. A per-request socket with a full timeout loses the race; this reuses one
    socket and reacts within one `interval` of the network appearing.
    """
    while time.time() < deadline:
        try:
            sock.sendto(ldn_mitm.build(ldn_mitm.SCAN), (host_ip, ldn_mitm.PORT))
        except OSError:
            pass
        t_end = time.time() + interval
        while time.time() < t_end:
            try:
                data, _ = sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                time.sleep(0.001)
                continue
            try:
                kind, info = ldn_mitm.parse(data)
            except ValueError:
                continue
            if kind == ldn_mitm.SCAN_RESP:
                if ldn_mitm.session_id(info) != last_ssid:
                    return info, time.time()
    return None, time.time()


def associate(our_ip, host_ip, our_mac, name, timeout):
    """-> (NetworkInfo, held TCP socket). The host holds the connection open for the session."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip-join", action="store_true",
                    help="join over ldn_mitm on the LAN; no radio and no root")
    ap.add_argument("--host-ip", default="172.16.86.1", help="the console's address")
    ap.add_argument("--our-ip", default="172.16.86.128", help="our address on that network")
    ap.add_argument("--name", default="PkCamp", help="the LDN node name we publish")
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--scan-timeout", type=float, default=0.4)
    ap.add_argument("--race", action="store_true",
                    help="pre-armed low-latency join: hold one scan socket, poll fast, and connect "
                         "the instant a fresh network appears, to land before the host latches its "
                         "node list at mesh creation")
    ap.add_argument("--scan-interval", type=float, default=0.02,
                    help="race mode: seconds between SCAN sends (default 20 ms)")
    ap.add_argument("--hold", type=float, default=20.0,
                    help="how long to stay in one joined session before scanning again")
    ap.add_argument("--no-answer-migration", dest="answer_migration", action="store_false",
                    help="leave the console's start-host-migration unanswered, to measure it")
    ap.add_argument("--swap-host-fields", action="store_true",
                    help="send the network id before the constant id in the host update")
    ap.add_argument("--join-address", choices=["kind", "band"], default="band",
                    help="which builder writes the join request: pia_connect's 6.32 layout, or "
                         "pia6's, which reproduces a retail console's request byte for byte")
    ap.add_argument("--join-protocols", choices=["6.32", "band"], default="band",
                    help="the protocol list the join request states")
    ap.add_argument("--no-skip-source-check", dest="skip_source_check", action="store_false",
                    help="clear message flag 0x01; the unflagged path runs the station lookup and "
                         "can set the wake bit when the host has a station for us")
    ap.add_argument("--join-repeat", type=float, default=0.0,
                    help="re-send the join request every N seconds until the console answers "
                         "on 0x98 (0 = send it once)")
    ap.add_argument("--capture", default=None)
    args = ap.parse_args()

    if not args.ip_join:
        ap.error("only --ip-join is implemented; the radio joiner needs the scan/host window timed")

    our_mac = b"\x02\x00" + socket.inet_aton(args.our_ip)
    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    deadline = time.time() + args.seconds
    attempts = joined = 0
    race_sock = None
    last_ssid = b""
    if args.race:
        race_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        race_sock.setblocking(False)
        race_sock.bind((args.our_ip, 0))
        print(f"[pla] race mode: scanning every {args.scan_interval*1000:.0f} ms, "
              f"joining the instant a fresh network appears")
    try:
        while time.time() < deadline:
            attempts += 1
            if args.race:
                info, t_seen = fast_scan(race_sock, args.host_ip, args.scan_interval,
                                         deadline, last_ssid)
                if info is None:
                    continue
                last_ssid = ldn_mitm.session_id(info)
            else:
                info = scan_once(args.our_ip, args.host_ip, args.scan_timeout)
            if info is None:
                continue
            code = "?"
            try:
                code = pla.parse_advertise_data(ldn_mitm.advertise_data(info))["code"]
            except (ValueError, KeyError):
                pass
            ssid = ldn_mitm.session_id(info)
            keys = pla.session_keys(ssid)
            print(f"[pla] scan {attempts}: the console is hosting. code={code} "
                  f"ssid={ssid.hex()} network_id={keys.network_id:#010x}")
            try:
                synced, tcp = associate(args.our_ip, args.host_ip, our_mac, args.name,
                                        args.scan_timeout * 4)
            except (OSError, RuntimeError) as exc:
                print(f"[pla] the association failed: {exc}")
                continue
            joined += 1
            latency = (time.time() - t_seen) if args.race else None
            nodes = synced[0x67] if len(synced) > 0x67 else "?"
            msg = f"[pla] *** JOINED *** synced, nodes={nodes}"
            if latency is not None:
                msg += f", seen->synced {latency*1000:.0f} ms"
            print(msg)
            record(rec="joined", ssid=ssid.hex(), network_id=keys.network_id, code=code,
                   network_info=synced.hex(), t=time.time(), join_latency=latency)
            run_session(args, keys, tcp, record)
    except KeyboardInterrupt:
        print("\n[pla] interrupted")
    finally:
        if cap:
            cap.close()
    print(f"[pla] {attempts} scan(s), {joined} join(s)")
    return 0


def run_session(args, keys, tcp, record):
    """Hold the joined session and speak Pia to the console until it drops us or --hold runs out."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.our_ip, pla.PIA_PORT))
    sock.setblocking(False)
    end = time.time() + args.hold
    host_var, sent_join, session_answered = None, False, False
    join_sent_at, join_to = 0.0, None
    try:
        while time.time() < end:
            if sent_join and args.join_repeat > 0 and not session_answered \
                    and time.time() - join_sent_at >= args.join_repeat:
                join = build_join(args, keys, host_mac, host_var)
                sock.sendto(join, (join_to, pla.PIA_PORT))
                join_sent_at = time.time()
                record(rec="out", dst=join_to, kind="session join", hex=join.hex())
            try:
                payload, addr = sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                time.sleep(0.02)
                continue
            src_ip = addr[0]
            record(rec="in", src=src_ip, hex=payload.hex(), t=time.time())
            if not pia6.is_pia6(payload):
                print(f"[pla] {src_ip}: not version 11, {payload[:8].hex()}")
                continue
            header, plain, ids = pia6.parse_packet(keys.session_key, src_ip, keys.network_id,
                                                   payload)
            if plain is None:
                print(f"[pla] {src_ip}: {header!r} DID NOT AUTHENTICATE")
                continue
            print(f"[pla] {src_ip}: {header!r} footer={ids}")
            for msg in pia6.parse_messages(plain):
                print(f"       proto 0x{msg.protocol:02x} port={msg.port} "
                      f"flags=0x{msg.message_flags:02x} len={len(msg.payload)} "
                      f"{msg.payload.hex()}")
                record(rec="msg", src=src_ip, protocol=msg.protocol, port=msg.port,
                       flags=msg.message_flags, payload=msg.payload.hex())
                if msg.protocol == PROTO_NET and len(msg.payload) > 1 \
                        and msg.payload[1] == NET_START_HOST_MIGRATION and args.answer_migration:
                    body = build_update_network_host(
                        pia_connect.ldn_constant_id(our_mac_for(args)), keys.network_id, OUR_VAR,
                        swap=args.swap_host_fields)
                    reply = pia6.build_packet(
                        keys.session_key, keys.network_id, args.our_ip,
                        pia6.build_message(body, protocol=PROTO_NET,
                                           port=0, message_flags=establishing_flags(args)),
                        dst_var=0, src_var=OUR_VAR, packet_id=0, nonce8=os.urandom(8))
                    sock.sendto(reply, (src_ip, pla.PIA_PORT))
                    record(rec="out", dst=src_ip, kind="update network host", hex=reply.hex())
                    print("[pla] -> answered the host migration")
                if msg.protocol == PROTO_NET and len(msg.payload) > 1:
                    req = pia_connect.parse_net_conn_request(msg.payload)
                    if req is not None:
                        host_var, host_mac, seqid = req
                        print(f"[pla] the console's connection request: host_var={host_var:#06x} "
                              f"mac={host_mac.hex()} seqid={seqid}")
                        reply = pia6.build_packet(
                            keys.session_key, keys.network_id, args.our_ip,
                            pia6.build_message(pia_connect.build_net_response(seqid),
                                               protocol=PROTO_NET, port=0,
                                               message_flags=establishing_flags(args)),
                            dst_var=0, src_var=OUR_VAR, packet_id=0, nonce8=os.urandom(8))
                        sock.sendto(reply, (src_ip, pla.PIA_PORT))
                        record(rec="out", dst=src_ip, kind="net conn response", hex=reply.hex())
                        print("[pla] -> answered with the connection response")
                        if not sent_join:
                            sent_join = True
                            join = build_join(args, keys, host_mac, host_var)
                            sock.sendto(join, (src_ip, pla.PIA_PORT))
                            join_sent_at, join_to = time.time(), src_ip
                            record(rec="out", dst=src_ip, kind="session join", hex=join.hex())
                            print("[pla] -> sent the session join request")
                if msg.protocol == PROTO_SESSION:
                    session_answered = True
                    print(f"[pla] THE CONSOLE ANSWERED ON 0x98: {msg.payload.hex()}")
    finally:
        sock.close()
        try:
            tcp.close()
        except OSError:
            pass
        print("[pla] left the session")


def build_join(args, keys, host_mac, host_var):
    """The session join request as one packet, in the layout the flags select.

    The constant id is the wiki's MAC reordering [Pia-Types, constant id], not the raw MAC:
    `pia_connect.ldn_constant_id`. host_mac already arrives in constant-id form from the Net 0x11.
    """
    our_cid = pia_connect.ldn_constant_id(our_mac_for(args))
    if args.join_address == "kind":
        body = pia_connect.build_session_join(
            our_cid, OUR_VAR.to_bytes(2, "big"), args.our_ip, host_mac,
            host_var.to_bytes(2, "big"), args.name, os.urandom(4),
            protocols=(pia_connect.DEFAULT_PROTOCOLS if args.join_protocols == "6.32"
                       else pia6.BAND_PROTOCOLS))
    else:
        body = pia6.build_session_join(
            our_cid, OUR_VAR, args.our_ip, host_mac, host_var, args.name, os.urandom(4),
            protocols=(pia_connect.DEFAULT_PROTOCOLS if args.join_protocols == "6.32"
                       else pia6.BAND_PROTOCOLS))
    return pia6.build_packet(
        keys.session_key, keys.network_id, args.our_ip,
        pia6.build_message(body, protocol=PROTO_SESSION, port=0,
                           message_flags=establishing_flags(args)),
        dst_var=0, src_var=OUR_VAR, packet_id=0, nonce8=os.urandom(8))


def build_update_network_host(constant_id, network_id, variable_id, swap=False):
    """NetUpdateNetworkHostMessage, 22 bytes, from the console's own serializer at 0x6fe03c.

    That function writes a big-endian u64 at wire +4, another at +0xc and a big-endian u16 at +0x14,
    and states the size as 0x16. The 0x11 header next to it carries the variable id, the constant id
    and the network id in that order, so which u64 is which here is a deduction rather than a
    reading: `swap` sends the other order.
    """
    constant_id = bytes(constant_id).ljust(8, b"\x00")[:8]
    network = (network_id & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
    first, second = (network, constant_id) if swap else (constant_id, network)
    return build_net(NET_UPDATE_NETWORK_HOST,
                     first + second + (variable_id & 0xFFFF).to_bytes(2, "big"))


def build_net(kind, body=b""):
    """A Net message: header version 1, the type, a big-endian payload size, then the body."""
    return bytes([1, kind & 0xFF]) + len(body).to_bytes(2, "big") + bytes(body)


def our_mac_for(args):
    return b"\x02\x00" + socket.inet_aton(args.our_ip)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Join the network a searching Scarlet / Violet console puts up, and let its Pia speak to us.

A console on the offline Link Trade search alternates: a few seconds hosting its own network, then
scanning. It registers its Pia protocols while it hosts, so the session is entered from that side:
we scan in a loop, take the seat the moment the network appears, and answer what arrives.

    sudo ./.venv/bin/python bin/sv_join.py --seconds 600 --capture scratchpad/svNN_join.jsonl

    (them) X -> Poke Portal -> Link Trade, offline, no code -> search

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
from pokeldn.ldn import pia6, pia_connect, reliable5
from pokeldn.sv import streams
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
    5: "update session", 6: "update session ack", 7: "left station sync",
    8: "left station sync ack", 9: "start host migration", 10: "start host migration ack",
}
STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]


def cleanup_stale():
    import subprocess
    for name in STALE_VIFS:
        subprocess.run(["iw", "dev", name, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_socket(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, ifname.encode())
    except (PermissionError, OSError):
        pass
    s.bind(("", sv.PIA_PORT))
    s.setblocking(False)
    return s


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
    ap.add_argument("--scan-only", action="store_true",
                    help="report what the console advertises and join nothing")
    ap.add_argument("--session-join", action="store_true",
                    help="send the Pia Session join request. A retail joiner sends none: Scarlet "
                         "runs no Session protocol, and the host reads the ack as a host-migration "
                         "cue (sv08). Kept as an instrument, off by default")
    ap.add_argument("--join-repeat", type=float, default=2.0,
                    help="with --session-join, re-send it every N seconds (0 sends it once)")
    ap.add_argument("--join-app-ver", type=lambda v: int(v, 0), default=0,
                    help="application communication version stated in the join request")
    ap.add_argument("--net-ack", action="store_true",
                    help="answer the host's Net 0x11 with the 0x12 ack. A retail joiner does not, "
                         "and the ack makes the console ask for host migration instead (sv08)")
    ap.add_argument("--open-delay", type=float, default=0.8,
                    help="seconds after the seat before the eleven acks and the two stream opens "
                         "go out; a retail joiner waits about 0.9 s")
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


async def run_session(args, keys, host_ip, host_mac, our_ip, our_mac, record):
    """Everything above the seat: answer the host's Net, join its session, hold the streams."""
    sock = make_socket(args.ifname)
    t0 = time.monotonic()
    host_var = None
    host_const = pia_connect.ldn_constant_id(host_mac) if len(host_mac) == 6 else bytes(8)
    our_const = pia_connect.ldn_constant_id(our_mac) if len(our_mac) == 6 else bytes(8)
    join_sent = 0.0
    joined = False
    stream_high = {}            # (protocol, port) -> highest sequence received from the host
    our_seq = {}                # (protocol, port) -> our next send sequence on that stream
    last_ack = {}
    counts = {}
    seen = authed = 0

    # Both retail stations address every Pia datagram to the link-local broadcast of their own
    # /24 (sv11: 169.254.86.2 -> 169.254.86.255), never to the peer's address.
    dest_ip = host_ip if args.unicast else our_ip.rsplit(".", 1)[0] + ".255"

    ours = {"var": OUR_VAR, "assigned": False}

    def out(body, dst_var, **kw):
        return build_out(keys, our_ip, body, dst_var, src_var=ours["var"], **kw)

    def send(pkt, what, **extra):
        sock.sendto(pkt, (dest_ip, sv.PIA_PORT))
        record(rec="out", dst=dest_ip, kind=what, hex=pkt.hex(), t=time.time(), **extra)

    def send_join():
        # The host's constant id is the one its own Net 0x11 states, not the LDN MAC from the
        # participant list: on the GBA app those differ, and the join must address the stated one.
        body = pia6.build_session_join(
            our_const, OUR_VAR, our_ip, host_const, host_var or 0, args.name, os.urandom(4),
            app_ver=args.join_app_ver)
        send(out(body, 0, protocol=PROTO_SESSION), "session join request")
        print(f"[sv] -> {host_ip}: session join request (type 0), "
              f"host_var={host_var if host_var is None else hex(host_var)}, "
              f"host_const={host_const.hex()}")

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
        if not opened and elapsed >= args.open_delay:
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
                if msg.payload[0] in (1, 2, 5):
                    joined = True
                print(f"[sv] the host spoke Session: {SESSION_MESSAGE_NAMES.get(msg.payload[0], '?')}")
            if not args.no_rtt and msg.protocol == PROTO_RTT and msg.payload and msg.payload[0] == 0:
                send(out(streams.build_rtt_response(msg.payload, header.src_var),
                         header.src_var, protocol=PROTO_RTT), "rtt response")
            if msg.protocol in RELIABLE_PROTOCOLS and len(msg.payload) >= reliable5.HEADER_SIZE:
                try:
                    rm = reliable5.parse(msg.payload)
                except ValueError as exc:
                    print(f"[sv] reliable did not parse: {exc}")
                    continue
                key = (msg.protocol, msg.port)
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

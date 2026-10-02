#!/usr/bin/env python3
"""Join a Let's Go Pikachu / Eevee LDN session: scan, take a seat, trade.

  --scan-only  report every advertisement and decode the Pia application-data header
  --hold N     hold the seat N seconds; a quiet screen is expected
  --capture F  every datagram on port 12345, hex, one JSON line each

docs/lgpe_session.md has the constants and their addresses.
"""
from pathlib import Path
import argparse
import contextlib
import json
import os
import socket
import struct
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED_LDN = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED_LDN):
    sys.path.insert(0, BUNDLED_LDN)

import trio
import ldn
from pokeldn.host_support import open_output
from pokeldn import pokemon as pokemon_service
from pokeldn.ldn import pia3, pia4, station9, station4
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn import clone, sync_clock, ldn_mitm
from pokeldn.ldn import rtt_protocol as rtt
from pokeldn.ldn import reliable3
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn.station_protocol import ldn_constant_id, ldn_service_variable_id, station_location
from pokeldn.ldn.transport import board_radio, find_ap_phy
from pokeldn.host_support import resolve_keys, needs_root, write_file
from pokeldn.lgpe import (COMM_ID_PIKACHU, PASSPHRASE, PIA_PORT, PIA_VERSION, packet_iv,
                          session_keys)
from pokeldn.lgpe.session import APP_HEADER_SIZE
from pokeldn.lgpe import pb7, reference
from pokeldn.lgpe.leave import Leaver, host_departure
from pokeldn.lgpe.trade import (TRADE_IN_PROGRESS, _answer_commit, _answer_offer,  # noqa: F401
                                _note_result, _send_step, _warn_if_mid_trade, answer_console)


def _survive_netlink_overflow():
    """Swallow the netlink reader's ENOBUFS, which otherwise kills the run: an interrupted retail
    trade leaves the save refusing the next one, with no restore."""
    import errno
    import socket as _socket
    try:
        import netlink
    except ImportError:
        return
    inner = netlink.NetlinkSocket.start

    async def start(self):
        try:
            self._socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_RCVBUF, 8 << 20)
        except OSError:
            pass
        while True:
            try:
                await inner(self)
                return
            except OSError as exc:
                if exc.errno != errno.ENOBUFS:
                    raise
                print("[lg] netlink: event queue overflowed, continuing")

    netlink.NetlinkSocket.start = start


_survive_netlink_overflow()

STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]

KNOWN = {0x0100000011D90000: "BDSP", 0x0100ABF008968000: "Sword",
         COMM_ID_PIKACHU: "Let's Go Pikachu"}


def cleanup_stale():
    if board_radio():
        return
    import subprocess
    for name in STALE_VIFS:
        subprocess.run(["iw", "dev", name, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def describe(net):
    tag = KNOWN.get(net.local_communication_id, "")
    return (f"comm_id=0x{net.local_communication_id:016x}{' (' + tag + ')' if tag else ''} "
            f"scene={net.scene_id} version={net.version} app_version={net.app_version} "
            f"ch={net.channel} {net.num_participants}/{net.max_participants}")


def app_header(app):
    """The Pia 5.9-5.18 application-data header, little-endian, as a dict."""
    if len(app) < APP_HEADER_SIZE:
        return {"short": len(app)}
    network_id, crc, sysver, hsize, _pad, param, zero8 = struct.unpack_from("<IIBBHIQ", app, 0)
    return {"network_id": f"{network_id:#010x}", "password_crc32": f"{crc:#010x}",
            "system_comm_version": sysver, "header_size": hsize,
            "session_param": f"{param:#010x}", "zero8": f"{zero8:#x}",
            "game_data": app[hsize:].hex() if hsize <= len(app) else None}


def facts_of(net):
    app = bytes(getattr(net, "application_data", b"") or b"")
    return {
        "ssid": net.ssid.hex(),
        "server_random": bytes(getattr(net, "server_random", b"") or b"").hex(),
        "application_data": app.hex(),
        "app_header": app_header(app),
        "nonce": bytes(getattr(net, "nonce", b"") or b"").hex(),
        "challenge": getattr(net, "challenge", None),
        "local_communication_id": f"{net.local_communication_id:#018x}",
        "scene_id": net.scene_id,
        "version": net.version,
        "app_version": net.app_version,
        "channel": net.channel,
        "num_participants": net.num_participants,
        "max_participants": net.max_participants,
        "address": str(net.address),
        "participants": [
            {"ip": str(getattr(p, "ip_address", "")),
             "mac": bytes(getattr(p, "mac_address", b"") or b"").hex(),
             "name": bytes(getattr(p, "name", b"") or b"").split(b"\0")[0].decode("utf-8", "replace"),
             "connected": bool(getattr(p, "connected", False))}
            for p in (getattr(net, "participants", []) or [])],
    }


class _IpParticipant:
    def __init__(self, ip, mac, name=b""):
        self.ip_address, self.mac_address, self.name = ip, mac, name
        self.connected = True


class _IpNetwork:
    """A network reached over IP (an emulator's Pia socket on :12345). Only `application_data`
    decides the session key."""

    def __init__(self, app, host_ip, host_mac, our_ip, our_mac):
        self.application_data = app
        self.ssid = b""
        self.server_random = self.nonce = b""
        self.challenge = None
        self.local_communication_id = COMM_ID_PIKACHU
        self.scene_id = self.version = self.app_version = 0
        self.channel = 0
        self.num_participants, self.max_participants = 1, 8
        self.address = host_ip
        self.participants = [_IpParticipant(host_ip, host_mac),
                             _IpParticipant(our_ip, our_mac)]


class _IpSession:
    def __init__(self, net):
        self._net = net

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def info(self):
        return self._net


def _mac(text):
    raw = bytes.fromhex(text.replace(":", "").replace("-", ""))
    if len(raw) != 6:
        raise ValueError(f"a MAC is six bytes, got {len(raw)}")
    return raw


def _blob(text):
    if text.startswith("@"):
        return Path(text[1:]).read_bytes()
    return bytes.fromhex(text)


def make_socket(ifname, bind_ip=None):
    from pokeldn.ldn import userspace_ip  # no kernel interface on the ESP32
    if bind_ip is None and (user := userspace_ip.udp_socket(ifname, PIA_PORT)) is not None:
        user.setblocking(False)
        return user
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if bind_ip is None:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, ifname.encode())
        except (PermissionError, OSError):
            pass
    s.bind((bind_ip or "", PIA_PORT))
    s.setblocking(False)
    return s


def try_decrypt(keys, data, macs):
    """-> (header, plaintext or None, source_mac or None). The datagram does not carry the sender's
    MAC the IV needs, so every known MAC is tried with source id 0 and the header's station."""
    hdr = pia4.PiaHeader4.parse(data)
    ct = pia4.ciphertext(data)
    for mac in macs:
        for sid in sorted({hdr.station, 0}):
            iv = packet_iv(keys, mac, hdr.nonce8, source_id=sid)
            pt = pia4.decrypt_payload(keys.session_key, iv, ct, hdr.tag)
            if pt is not None:
                return hdr, pt, mac, sid
    return hdr, None, None, None


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default=None,
                    help="local_communication_id to join, hex. Omit to join the only unknown one")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="1,6,11,36,40,44,48")
    ap.add_argument("--dwell", type=float, default=0.8)
    ap.add_argument("--scan-seconds", type=float, default=300.0,
                    help="keep scanning this long for a console before giving up")
    ap.add_argument("--name", default="PkCamp")
    ap.add_argument("--passphrase", default=None, help="override, as ASCII")
    ap.add_argument("--hold", type=float, default=60.0)
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--facts", default="lgpe_net_facts.json")
    ap.add_argument("--capture", default=None,
                    help="jsonl of every datagram seen while seated, hex, with its verdict")
    ap.add_argument("--connect", action="store_true",
                    help="send a version-9 station connection request to the host and classify the "
                         "reply, retransmitting every 0.5 s the way Pia does. Without it, listen only")
    ap.add_argument("--variable-id", type=lambda s: int(s, 0), default=0x0B0B0B0B,
                    help="our own variable id, any nonzero value (the console's is random)")
    ap.add_argument("--connect-seconds", type=float, default=20.0,
                    help="how long to retransmit the connection request and listen for its reply")
    ap.add_argument("--grace", type=float, default=300.0,
                    help="seconds past --connect-seconds or --hold to keep a seat whose trade is half "
                         "done: a trade left mid-way locks the console out of trading")
    ap.add_argument("--player-name", default="PkCamp",
                    help="the nickname the connection response carries, what the console shows as "
                         "the partner (a real station sends its Switch profile's)")
    ap.add_argument("--short-response", action="store_true",
                    help="send the 0x3c-byte connection response instead of the full 0x348-byte "
                         "one, which carries no network id and no player")
    ap.add_argument("--public-address", action="store_true",
                    help="put our own address in the station location's public field as well as "
                         "its private one. A Let's Go joiner leaves the public field empty")
    ap.add_argument("--nat-location", action="store_true",
                    help="send nat flags 5 and nat location 1. A Let's Go joiner sends zero for "
                         "both on local wireless")
    ap.add_argument("--reliable-payload", default=reference.IDENTITY,
                    help="files, comma-separated, holding the game payloads to send on the "
                         "Reliable Protocol (0x7c) once the clone elements are up; by default the "
                         "recorded identity in pokeldn.lgpe.reference, and an empty value sends "
                         "nothing there")
    ap.add_argument("--reliable-interval", type=float, default=4.0,
                    help="seconds between the payloads of --reliable-payload")
    ap.add_argument("--no-rtt", action="store_true",
                    help="once in the mesh, do not answer the host's RTT requests and send none "
                         "of our own. Default: answer them and send one a second")
    ap.add_argument("--no-sync-clock", action="store_true",
                    help="once in the mesh, do not run the Sync Clock Protocol (0x1c): a request "
                         "every 2 s, the host's reply carrying the mesh clock in ms. Default: run it")
    ap.add_argument("--no-clone", action="store_true",
                    help="once in the mesh, do not run the clone clock exchange (requests every "
                         "0.2 s, replies with our ms clock, participate after ten answers: "
                         "docs/lgpe_session.md). Default: run it")
    ap.add_argument("--over-ip", action="store_true",
                    help="reach the peer over plain UDP instead of the radio: no scan, no LDN "
                         "association, the Pia socket straight at --host-ip:12345. For an "
                         "emulated host under a debugger. Needs --app-data, --host-mac, --our-mac")
    ap.add_argument("--host-ip", default="127.0.0.2")
    ap.add_argument("--host-mac", help="the hosting station's MAC, as it appears in its own "
                                       "advertisement")
    ap.add_argument("--our-ip", default="127.0.0.3")
    ap.add_argument("--our-mac", help="the MAC we present; any value the host has not seen")
    ap.add_argument("--app-data", help="the host's advertise data as hex, or @FILE, instead of "
                                       "scanning for it. Needs --host-mac alongside")
    ap.add_argument("--discover-timeout", type=float, default=5.0,
                    help="how long to wait for the scan response and the sync")
    ap.add_argument("--ack-peer-clock", action="store_true",
                    help="carry the peer's announcement clock in our acknowledgement on clone type "
                         "2 rather than the clock round-tripped from our own announcement, which "
                         "is what a reference joiner carries")
    ap.add_argument("--our-trainer", metavar="TID:SID",
                    help="replace the trainer id pair in the first message. A payload captured "
                         "between two emulators that share a save carries the host's own pair, "
                         "which presents the joiner as the station it is trading with")
    ap.add_argument("--leave-after", type=float, default=None, metavar="SECONDS",
                    help="leave the session the way a console backs out of its trade screen, "
                         "this long after the first trade step we answered (docs/lgpe_session.md)")
    ap.add_argument("--received", help="write the peer's offered PB7 here")
    ap.add_argument("--fresh-pid", action="store_true",
                    help="offer every --offer structure under a new PID and encryption constant, "
                         "shiny state kept, so a save that took it before takes it again")
    ap.add_argument("--offer", metavar="echo|PATH", action="append",
                    help="answer the host's offers with a box structure of our own. 'echo' returns "
                         "the host's own, which the game accepts by construction; a path is a "
                         "232-byte structure, encrypted or not. Repeatable, one per trade on the "
                         "seat; trade N writes what it received to --received with -N. After the "
                         "last, a further trade is not answered and the player backs out")
    ap.add_argument("--withhold-announce", type=int, default=0, metavar="N",
                    help="test only: skip the first N of our announcements to the host alone, as "
                         "if lost, so the resend carries them")
    ap.add_argument("--ack-re-announce", action="store_true",
                    help="answer a peer re-announcement with an acknowledgement carrying its "
                         "clock rather than a second take-over. A reference joiner takes a clone "
                         "over once and never again")
    ap.add_argument("--publish-delay", type=float, default=0.09,
                    help="seconds after the take-over burst to publish our copy, with "
                         "--publish-on-announce. Zero puts it in the burst's own frame")
    ap.add_argument("--publish-once", action="store_true",
                    help="answer only the first of a peer's repeated publishes with a copy of our "
                         "own and acknowledge the rest. Measured to stop the peer publishing at "
                         "all, so the default answers each one")
    ap.add_argument("--own-takeover-clock", action="store_true",
                    help="stamp our own clock on the take-over instead of the clock the peer's "
                         "announcement carried. The peer completes a take-over only when it "
                         "matches the sequence it allocated, so the echo is the default")
    ap.add_argument("--announce-after-burst", action="store_true",
                    help="send the announcement of our own copy a tick after the take-over burst. "
                         "Both stations of a session that works put all seven in one frame, which "
                         "is the default here")
    ap.add_argument("--publish-on-announce", action="store_true",
                    help="publish our copy of a clone on clone type 2 as part of the announce "
                         "burst. A real joiner waits for the peer to publish its own copy first, "
                         "which is the default here")
    ap.add_argument("--publish-fallback", type=float, default=3.0,
                    help="publish anyway this many seconds after the announce if the peer never "
                         "published its own copy. Not a measured value")
    ap.add_argument("--peer-announce-dest", action="store_true",
                    help="address our own clone announce to the peer alone. A real joiner "
                         "addresses the first announce of a clone to the whole mesh "
                         "(dest 0x0003), which is the default here")
    ap.add_argument("--clone-requests", type=int, default=10,
                    help="answered clock requests of our own before the participate (measured 10)")
    return ap


def pick(nets, want):
    if want is not None:
        return next((n for n in nets if n.local_communication_id == want), None)
    unknown = [n for n in nets if n.local_communication_id not in KNOWN
               or n.local_communication_id == COMM_ID_PIKACHU]
    if len(unknown) == 1:
        return unknown[0]
    return None


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    args.offers = [path if path == "echo" else
                   pokemon_service.prepare_file("lgpe", path, fresh=args.fresh_pid)
                   for path in args.offer or ()]
    args.offer = args.offers[0] if args.offers else None
    args.fresh_pid = False
    if args.over_ip:
        if not args.our_mac:
            ap.error("--over-ip needs --our-mac")
        if args.app_data and not args.host_mac:
            ap.error("--app-data replaces the scan, so it needs --host-mac with it")
        return _main_over_ip(args)
    if needs_root():
        ap.error("must run as root (LDN needs the raw radio)")
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[lg] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[lg] prod.keys not found at {keys_path!r}"); return 2

    want = int(args.comm_id, 16) if args.comm_id else None
    pw = args.passphrase.encode() if args.passphrase else PASSPHRASE
    channels = [int(c) for c in args.channels.split(",") if c.strip()]
    print(f"[lg] phy={phy} comm_id={'any unknown' if want is None else f'0x{want:016x}'} "
          f"channels={channels} passphrase={len(pw)} B")
    cleanup_stale()
    keys_file = ldn.load_keys(keys_path)

    async def find():
        # A console on the search screen advertises only while it hosts.
        deadline = trio.current_time() + args.scan_seconds
        while True:
            nets = await ldn.scan(keys_file, phyname=phy, channels=channels, dwell_time=args.dwell)
            for n in nets:
                print(f"[lg] saw {describe(n)}")
            if nets or trio.current_time() >= deadline:
                return nets

    nets = trio.run(find)
    if not nets:
        print("[lg] nothing on the air - is the console on the link-trade search screen right now?")
        return 3
    with open_output(args.facts, "w") as fh:
        json.dump([facts_of(n) for n in nets], fh, indent=2)
    print(f"[lg] {len(nets)} network(s) -> {args.facts}")

    net = pick(nets, want)
    if net is None:
        print("[lg] no single target: pass --comm-id with one of the ids above")
        return 4
    facts = facts_of(net)
    print(f"[lg] target: {describe(net)} ssid={net.ssid.hex()}")
    for k, v in facts.items():
        print(f"[net] {k:24s} {v}")
    if args.scan_only:
        return 0
    if net.num_participants >= net.max_participants:
        print("[lg] session is FULL, no seat to take"); return 5

    keys = session_keys(net)
    print(f"[lg] {keys}")

    param = ldn.ConnectNetworkParam()
    param.keys, param.network, param.password = keys_file, net, pw
    param.name, param.app_version = args.name.encode(), net.app_version
    param.phyname, param.ifname = phy, args.ifname

    return _run(args, net, keys, facts, lambda: ldn.connect(param))


def _discover(args, our_mac):
    """The ldn_mitm association: scan the host, then hold a TCP connection open so its game has a
    node for us. -> (advertise data, host MAC, socket)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as us:
        us.settimeout(args.discover_timeout)
        # ldn_mitm drops a scan whose source is the host's own LDN address.
        us.bind((args.our_ip, 0))
        us.sendto(ldn_mitm.build(ldn_mitm.SCAN), (args.host_ip, ldn_mitm.PORT))
        print(f"[ldn] scan -> {args.host_ip}:{ldn_mitm.PORT}")
        while True:
            data, _ = us.recvfrom(4096)
            kind, info = ldn_mitm.parse(data)
            if kind == ldn_mitm.SCAN_RESP:
                break
            print(f"[ldn] ignoring type {kind}")
    print(f"[ldn] scan response: NetworkInfo {len(info)} B, host mac "
          f"{ldn_mitm.host_mac(info).hex()}")

    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(args.discover_timeout)
    tcp.bind((args.our_ip, 0))
    tcp.connect((args.host_ip, ldn_mitm.PORT))
    node = ldn_mitm.build_node_info(args.our_ip, our_mac, args.name.encode())
    tcp.sendall(ldn_mitm.build(ldn_mitm.CONNECT, node))
    kind, synced = ldn_mitm.parse(tcp.recv(8192))
    if kind != ldn_mitm.SYNC_NETWORK:
        raise RuntimeError(f"the host answered our connect with type {kind}, not SyncNetwork")
    print("[ldn] *** JOINED *** the host synced the network with us in it; holding the connection")
    tcp.settimeout(None)
    return ldn_mitm.advertise_data(synced), ldn_mitm.host_mac(synced), tcp


def _main_over_ip(args):
    """Join a host over plain UDP (an emulated console), no radio and no LDN association."""
    our_mac = _mac(args.our_mac)
    held = None
    if args.app_data:
        app, host_mac = _blob(args.app_data), _mac(args.host_mac)
    else:
        app, host_mac, held = _discover(args, our_mac)
        print(f"[ldn] advertise data {app.hex()} ({len(app)} B)")
    net = _IpNetwork(app, args.host_ip, host_mac, args.our_ip, our_mac)
    net.held_connection = held  # the host FINs it when its game leaves
    keys = session_keys(net)
    facts = facts_of(net)
    print(f"[lg] over IP: host {args.host_ip}:{PIA_PORT} mac={host_mac.hex()}, "
          f"us {args.our_ip} mac={our_mac.hex()}")
    print(f"[lg] {keys}")
    for k in ("app_header",):
        print(f"[net] {k:24s} {facts[k]}")
    return _run(args, net, keys, facts, lambda: _IpSession(net))


def _run(args, net, keys, facts, opener):
    cap = open_output(args.capture, "w") if args.capture else None

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw) + "\n"); cap.flush()

    record(rec="target", **facts, session_key=keys.session_key.hex())

    async def attempt():
        async with opener() as network, contextlib.AsyncExitStack() as cleanup:
            info = network.info()
            parts = list(getattr(info, "participants", []) or [])
            macs = [bytes(getattr(p, "mac_address", b"") or b"") for p in parts]
            macs = [m for m in macs if len(m) == 6]
            print(f"[lg] *** ASSOCIATED *** ssid={info.ssid.hex()}")
            for i, p in enumerate(parts):
                name = bytes(getattr(p, "name", b"") or b"").split(b"\0")[0]
                print(f"[lg]   participant {i}: ip={getattr(p, 'ip_address', '?')} "
                      f"mac={bytes(getattr(p, 'mac_address', b'')).hex()} "
                      f"name={name!r} connected={getattr(p, 'connected', '?')}")
            record(rec="seat", macs=[m.hex() for m in macs])
            host = parts[0] if parts else None
            host_ip = str(getattr(host, "ip_address", "") or "169.254.105.1")
            host_mac = bytes(getattr(host, "mac_address", b"") or b"")
            ours = parts[1] if len(parts) > 1 else None
            our_ip = str(getattr(ours, "ip_address", "") or host_ip.rsplit(".", 1)[0] + ".2")
            our_mac = macs[1] if len(macs) > 1 else (macs[0] if macs else bytes(6))
            sock = cleanup.enter_context(make_socket(args.ifname, args.our_ip if args.over_ip else None))
            t0 = time.monotonic()
            n_rx = n_ok = n_v3 = 0
            versions = {}

            out_nonce = [0]
            def send_connection_request():
                if len(host_mac) != 6 or len(our_mac) != 6:
                    print("[lg] a MAC is missing; cannot build the request"); return False
                host_const = ldn_constant_id(host_mac)
                our_const = ldn_constant_id(our_mac)
                # what a Let's Go joiner sends on local wireless: no public address, no NAT
                loc = station_location(our_ip, PIA_PORT, our_const, args.variable_id,
                                       ldn_service_variable_id(our_mac),
                                       nat_flags=0 if not args.nat_location else 5,
                                       nat_location=0 if not args.nat_location else 1,
                                       public=args.public_address)
                msg = station9.build_connection_request(host_const, 0, loc, ack_id=0)
                body = pia3.build_message(msg, protocol=station9.PROTOCOL, source=our_const,
                                          port=0, destination=host_const)
                out_nonce[0] += 1
                nonce8 = out_nonce[0].to_bytes(8, "big")
                iv = packet_iv(keys, our_mac, nonce8, source_id=0)
                pkt = pia3.build_packet(keys.session_key, iv, body, station=0, nonce8=nonce8)
                sock.sendto(pkt, (host_ip, PIA_PORT))
                record(rec="tx", t=round(time.monotonic() - t0, 3), to=host_ip, len=len(pkt),
                       data=pkt.hex(), kind="station9_connection_request")
                return True

            state = {"acked_inverse": False, "sent_response": False, "host_accepted": False,
                     "our_ack": [1], "acked_response": False, "mesh_joined": False,
                     "mesh_join_sent": False}
            HOST_STATION_BIT = 0x0001
            KEEPALIVE_PROTOCOL = 0x08
            def to_host_bitmap(payload, protocol, port=0):
                our_const = ldn_constant_id(our_mac) if len(our_mac) == 6 else 0
                send_packet(pia3.build_message(payload, protocol=protocol, source=our_const,
                                               port=port, destination=HOST_STATION_BIT,
                                               message_flags=pia3.MESSAGE_FLAG_BITMAP))
            def clone_send(payload):
                to_host_bitmap(payload, clone.PROTOCOL)
            def send_packet(body, **what):
                out_nonce[0] += 1
                nonce8 = out_nonce[0].to_bytes(8, "big")
                iv = packet_iv(keys, our_mac, nonce8, source_id=0)
                pkt = pia3.build_packet(keys.session_key, iv, body, station=0, nonce8=nonce8)
                sock.sendto(pkt, (host_ip, PIA_PORT))
                record(rec="tx", t=round(time.monotonic() - t0, 3), to=host_ip, len=len(pkt),
                       data=pkt.hex(), **what)
                return pkt
            def complete_handshake(inverse_req):
                host_const = ldn_constant_id(host_mac); our_const = ldn_constant_id(our_mac)
                ack_id = station9.ack_id_of(inverse_req)
                loc = inverse_req[station9.OFF_LOCATION:-4]
                try:
                    host_var = station4.parse_station_location(loc)["variable_id"]
                except Exception:
                    host_var = 0
                ack = pia3.build_message(station9.build_ack(ack_id), protocol=station9.PROTOCOL,
                                         source=our_const, port=0, destination=host_const)
                send_packet(ack, kind="ack_inverse", ack_id=ack_id)
                net_id = int.from_bytes(keys.network_id_le, "little")
                resp = station9.build_connection_response(
                    host_const, host_var, ack_id=state["our_ack"][0],
                    network_id=None if args.short_response else net_id,
                    player_name=args.player_name.encode("utf-8"))
                state["our_ack"][0] += 1
                body = pia3.build_message(resp, protocol=station9.PROTOCOL, source=our_const,
                                          port=0, destination=host_const)
                send_packet(body, kind="connection_response", host_var=host_var)
                print(f"[lg] connection response {len(resp)} B, player "
                      f"{args.player_name!r}, network id {net_id:#010x}")
                print(f"[lg] acked inverse (ack id {ack_id:#x}) and sent connection response "
                      f"(host var {host_var:#x})")

            if args.connect:
                host_const = ldn_constant_id(host_mac) if len(host_mac) == 6 else 0
                print(f"[lg] --connect: sending v9 connection request to host {host_ip} "
                      f"(constant {host_const:#018x}), our constant "
                      f"{ldn_constant_id(our_mac) if len(our_mac)==6 else 0:#018x}, "
                      f"variable id {args.variable_id:#x}")
                deadline = args.connect_seconds
                next_tx = 0.0
            else:
                deadline = args.hold
                print(f"[lg] listening on :{PIA_PORT} for {deadline:.0f}s")
            while (time.monotonic() - t0 < deadline
                   or state.get("mid_trade") and time.monotonic() - t0 < deadline + args.grace):
                # Our own leave sends its disconnection request first: that, not the network
                # leaving, returns a console host's player at once (docs/lgpe_session.md).
                lv = state.get("leaver")
                if state.get("host_left") and (lv is None or lv.disconnect_sent is not None):
                    break
                if (args.leave_after is not None and state.get("leave_at") is None
                        and state.get("answered_step")):
                    state["leave_at"] = time.monotonic() + args.leave_after
                    print(f"[lg] leaving in {args.leave_after:.0f} s")
                if (state.get("leave_at") is not None and state.get("leaver") is None
                        and time.monotonic() >= state["leave_at"]):
                    part = state["clone"]
                    offered = [cid for cid, d in part.shared.items() if d[:4] == b"\x01\0\0\0"]
                    cid = max(offered or part.held or [3])
                    shared = part.shared.get(cid, bytes(20))
                    state["leaver"] = Leaver(
                        part, cid, state.get("step", 1), int.from_bytes(shared[16:20], "little"),
                        int.from_bytes(shared[8:12], "little"),
                        station=state.get("station_index", 1), host_bit=HOST_STATION_BIT,
                        clone_ids=[c for c in (1, 0, 2, 3) if c in part.held or c < 2])
                    print(f"[lg] *** LEAVING *** state 4 on clone {cid}, then the releases, "
                          "the leave request and the disconnection")
                if state.get("leaver") is not None:
                    now = time.monotonic()
                    for payload, proto, port in state["leaver"].poll(now):
                        to_host_bitmap(payload, proto, port=port)
                    if state["leaver"].done:
                        TRADE_IN_PROGRESS["offer"] = TRADE_IN_PROGRESS["commit"] = False
                        state["mid_trade"] = False
                        print("[lg] *** LEFT *** " + "; ".join(state["leaver"].log))
                        break
                if args.connect and not state["host_accepted"] and time.monotonic() - t0 >= next_tx:
                    if not send_connection_request():
                        break
                    next_tx += 0.5
                left = state.get("leaver") is not None and state["leaver"].leave_answered
                if args.connect and not args.no_sync_clock and state["mesh_joined"] \
                        and not left and len(our_mac) == 6 and len(host_mac) == 6:
                    now = time.monotonic()
                    if state.get("sync") is None:
                        state["sync"] = sync_clock.SyncClock(now)
                        print("[lg] sync clock: a request every 2 s (protocol 0x1c)")
                    for out in state["sync"].poll(now):
                        to_host_bitmap(out, sync_clock.PROTOCOL)
                if args.connect and args.reliable_payload and state["mesh_joined"] \
                        and state.get("clone") is not None \
                        and state["clone"].published and state.get("window") is None \
                        and len(our_mac) == 6:
                    state["window"] = reliable3.Window()
                    state["payloads"] = list(args.reliable_payload.split(","))
                    state["next_payload"] = time.monotonic()
                if state.get("payloads") and time.monotonic() >= state.get("next_payload", 0):
                    path = state["payloads"].pop(0)
                    state["next_payload"] = time.monotonic() + args.reliable_interval
                    body = Path(path).read_bytes()
                    if args.our_trainer:
                        # A capture between two emulators sharing a save carries the host's own
                        # trainer id.
                        msg = pb7.parse_message(body)
                        tid, sid = (int(v, 0) for v in args.our_trainer.split(":"))
                        if msg:
                            body = pb7.build_message(
                                msg["kind"], pb7.set_trainer_id(msg["body"], tid, sid))
                            print(f"[lg] reliable: trainer id "
                                  f"{pb7.trainer_id(msg['body'])} -> ({tid}, {sid})")
                    to_host_bitmap(state["window"].send(body), reliable3.PROTOCOL)
                    print(f"[lg] reliable: sent {len(body)} B from {path}")
                if args.connect and not args.no_rtt and state["mesh_joined"] and not left \
                        and len(our_mac) == 6 and len(host_mac) == 6 \
                        and time.monotonic() >= state.get("next_rtt", 0):
                    now = time.monotonic()
                    state["next_rtt"] = now + 1.0
                    to_host_bitmap(rtt.build_v3(rtt.REQUEST, int(now * rtt.TICK_HZ_V3)),
                                   rtt.PROTOCOL)
                if args.connect and not args.no_clone and state["mesh_joined"] and not left \
                        and len(our_mac) == 6 and len(host_mac) == 6:
                    now = time.monotonic()
                    if state.get("clone") is None:
                        our_index = state.get("station_index", 1)
                        state["clone"] = clone.Participant(
                            now, dest=HOST_STATION_BIT, own=1 << our_index, station=our_index,
                            requests_before_participate=args.clone_requests)
                        state["clone"].announce_mesh_dest = not args.peer_announce_dest
                        state["clone"].announce_in_burst = not args.announce_after_burst
                        state["clone"].echo_takeover_clock = not args.own_takeover_clock
                        state["clone"].publish_once = args.publish_once
                        state["clone"].publish_delay = args.publish_delay
                        state["clone"].ack_peer_clock = args.ack_peer_clock
                        state["clone"].ack_re_announcement = args.ack_re_announce
                        state["clone"].publish_on_announce = args.publish_on_announce
                        state["clone"].publish_fallback = args.publish_fallback
                        state["clone"].withhold_announces = args.withhold_announce
                        print("[lg] clone: sending clock requests every 0.2 s")
                    sc = state.get("sync")
                    if sc is not None and sc.now_ms(now) is not None:
                        state["clone"].mesh_ms = sc.now_ms(now)
                    for out in state["clone"].poll(now):
                        clone_send(out)
                        if out[1] == clone.PARTICIPATE:
                            print(f"[lg] clone: *** PARTICIPATE sent after "
                                  f"{state['clone'].answered} answered requests ***")
                    for event in state["clone"].events:
                        print(f"[lg] clone: {event}")
                    state["clone"].events.clear()
                if args.connect and state["host_accepted"] and not state["mesh_joined"] \
                        and time.monotonic() - t0 >= next_tx:
                    jr = pia3.build_message(mp.build_join_request(state["our_ack"][0]),
                        protocol=mp.PROTOCOL, source=ldn_constant_id(our_mac), port=0,
                        destination=ldn_constant_id(host_mac))
                    send_packet(jr)
                    if not state["mesh_join_sent"]:
                        print("[lg] host accepted; sending mesh join request on 0x18")
                    state["mesh_join_sent"] = True
                    state["our_ack"][0] += 1
                    next_tx += 0.5
                # Wait in trio, never in select() (docs/hardware_esp32.md, The userspace stack).
                r = False
                with trio.move_on_after(0.1):
                    await trio.lowlevel.wait_readable(sock)
                    r = True
                if not r:
                    continue
                data, addr = sock.recvfrom(4096)
                n_rx += 1
                entry = {"rec": "rx", "t": round(time.monotonic() - t0, 3), "from": addr[0],
                         "len": len(data), "data": data.hex()}
                if pia4.is_pia4(data) or (len(data) >= 8 and data[:4] == b"\x32\xab\x98\x64"):
                    hdr, pt, mac, sid = try_decrypt(keys, data, macs)
                    versions[hdr.version] = versions.get(hdr.version, 0) + 1
                    if hdr.version == PIA_VERSION:
                        n_v3 += 1
                    entry.update(version=hdr.version, station=hdr.station,
                                 session_id=hdr.session_id, nonce=hdr.nonce8.hex())
                    if pt is not None:
                        n_ok += 1
                        msgs = pia3.parse_packet(pt)
                        entry.update(plaintext=pt.hex(), source_mac=mac.hex(), source_id=sid,
                                     messages=[{"protocol": m["protocol"], "port": m["port"],
                                                "flags": m["flags"], "version": m["version"],
                                                "size": m["size"]} for m in msgs])
                        our_const = ldn_constant_id(our_mac) if len(our_mac) == 6 else 0
                        host_const = ldn_constant_id(host_mac) if len(host_mac) == 6 else 0
                        def to_host(body, proto):
                            send_packet(pia3.build_message(body, protocol=proto, source=our_const,
                                                           port=0, destination=host_const))
                        for m in msgs:
                            pl = m["payload"]
                            if state.get("leaver") is not None:
                                for payload, proto, port in state["leaver"].receive(
                                        m["protocol"], pl, time.monotonic()):
                                    to_host_bitmap(payload, proto, port=port)
                            replies, leave = host_departure(m["protocol"], pl,
                                                            state.get("station_index", 1))
                            for payload, proto, port in replies:
                                to_host_bitmap(payload, proto, port=port)
                            if replies and not state.get("host_migrating"):
                                state["host_migrating"] = True
                                print("[lg] *** THE HOST IS LEAVING *** answered its migration "
                                      "start")
                            if leave and not state.get("host_left"):
                                state["host_left"] = True
                                print("[lg] *** THE HOST CLOSED ITS NETWORK *** "
                                      "(start host migration); leaving it")
                            if m["protocol"] == station9.PROTOCOL:
                                kind, result = station9.parse_reply(pl)
                                is_inverse = kind == 1 and len(pl) > 3 and pl[3] == 1
                                if args.connect and is_inverse and not state["sent_response"]:
                                    complete_handshake(pl)
                                    state["acked_inverse"] = state["sent_response"] = True
                                if kind == station9.CONNECTION_RESPONSE and result == 0:
                                    to_host(station9.build_ack(station9.ack_id_of(pl)),
                                            station9.PROTOCOL)
                                    if not state["host_accepted"]:
                                        print("[lg] *** HOST ACCEPTED (connection response, "
                                              f"result 0, {len(pl)}B) *** acked "
                                              f"{station9.ack_id_of(pl):#x}")
                                    state["host_accepted"] = state["acked_response"] = True
                                print(f"[lg] station reply type={kind} result={result} "
                                      f"inverse={is_inverse} {len(pl)}B pl[:24]={pl[:24].hex()}")
                            elif m["protocol"] == mp.PROTOCOL:
                                acked = mp.ack_for(pl)
                                if acked:
                                    to_host(acked[1], acked[0])
                                if pl and pl[0] == mp.JOIN_RESPONSE and not state["mesh_joined"]:
                                    state["mesh_joined"] = True
                                    try:
                                        jr = mp.parse_join_response(pl)
                                        if not jr.get("refused"):
                                            state["station_index"] = jr["our_index"]
                                    except Exception:
                                        pass
                                    print("[lg] *** MESH JOIN RESPONSE - station index "
                                          f"{state.get('station_index', 1)} in the mesh, acked "
                                          "on 0x14 ***")
                                print(f"[lg] mesh 0x18 type={pl[0]:#x} {len(pl)}B "
                                      f"pl[:24]={pl[:24].hex()}")
                            elif m["protocol"] == reliable3.PROTOCOL:
                                w = state.get("window")
                                r = reliable3.parse(pl)
                                if w is not None and r is not None:
                                    for out in w.receive(pl):
                                        to_host_bitmap(out, reliable3.PROTOCOL)
                                    if r["size"]:
                                        print(f"[lg] reliable: *** GAME PAYLOAD *** "
                                              f"{r['size']}B seq={r['sequence']:#x} "
                                              f"{r['payload'][:32].hex()}")
                                        n = len(w.received)
                                        if args.capture:
                                            write_file(f"{args.capture}.payload{n}.bin", r["payload"])
                                        msg = pb7.parse_message(r["payload"])
                                        if msg:
                                            answer_console(args, state, msg, to_host_bitmap)
                                    else:
                                        print(f"[lg] reliable: acked, expects "
                                              f"{r['expected']:#x}")
                            elif m["protocol"] == rtt.PROTOCOL:
                                ans = rtt.response_for_v3(pl) if args.connect else None
                                if ans is not None and not args.no_rtt:
                                    to_host_bitmap(ans, rtt.PROTOCOL)
                                    state["rtt_answered"] = state.get("rtt_answered", 0) + 1
                                    if state["rtt_answered"] == 1:
                                        print("[lg] RTT: answering the host's requests (0x58)")
                            elif m["protocol"] == sync_clock.PROTOCOL:
                                sc = state.get("sync")
                                if sc is not None:
                                    sc.receive(pl, time.monotonic())
                                    if sc.replies == 1:
                                        print(f"[lg] sync clock: *** MESH CLOCK {sc.clock_ms} ms "
                                              f"*** (the host answered our request)")
                            elif m["protocol"] == KEEPALIVE_PROTOCOL:
                                to_host_bitmap(b"", KEEPALIVE_PROTOCOL)
                                state["keepalives"] = state.get("keepalives", 0) + 1
                                if state["keepalives"] == 1:
                                    print("[lg] keep-alive (0x08): answering in kind")
                            elif m["protocol"] == clone.PROTOCOL:
                                part = state.get("clone")
                                kind = pl[1] if len(pl) > 1 else -1
                                if part is not None:
                                    for out in part.receive(pl, time.monotonic()):
                                        clone_send(out)
                                    seen = state.setdefault("clone_types", {})
                                    seen[kind] = seen.get(kind, 0) + 1
                                    if seen[kind] == 1:
                                        print(f"[lg] clone: first type {kind:#04x} "
                                              f"({len(pl)}B) {pl.hex()}")
                                    if kind == clone.PARTICIPATE:
                                        print("[lg] clone: *** HOST PARTICIPATE (0x31) *** "
                                              "acked with 0x33")
                                    elif kind == clone.EXIT_REQUEST:
                                        print("[lg] clone: the host asked us to leave the clone "
                                              "session (0x32); acked with 0x41")
                                    elif kind == clone.STATE_DATA:
                                        d = clone.parse_data_message(pl)
                                        r = d and d["record"]
                                        print(f"[lg] clone: *** CLONE DATA *** {r}")
                                    elif kind >= 0x80 and seen[kind] == 1:
                                        print("[lg] clone: *** ELEMENT MESSAGE from the host: "
                                              "the clock is agreed ***")
                            elif m["protocol"] == lp.PROTOCOL and pl and pl[1:2] == b"\x11":
                                # Ack the update session (0x21) so the host knows the seat is alive;
                                # RTT never drops a silent station.
                                try:
                                    seq = lp.parse_update_session(pl).sequence_id
                                    to_host(lp.build_ack(seq), lp.PROTOCOL)
                                except Exception:
                                    pass
                        # Our copy's announcement goes in the same frame as the take-over, as a real
                        # joiner's.
                        part = state.get("clone")
                        if part is not None and part.announce_in_burst:
                            for out in part.poll(time.monotonic()):
                                clone_send(out)
                        if n_ok <= 8:
                            print(f"[rx] v{hdr.version} st={hdr.station} sid={hdr.session_id:#x} "
                                  f"{len(data)}B from {addr[0]} AUTH mac={mac.hex()} "
                                  f"pt[:32]={pt[:32].hex()} msgs="
                                  + ",".join(f"{m['protocol']:#x}:{m['port']}/{m['size']}"
                                             for m in msgs))
                    elif n_rx <= 8:
                        print(f"[rx] v{hdr.version} st={hdr.station} sid={hdr.session_id:#x} "
                              f"{len(data)}B from {addr[0]} no key fits")
                elif n_rx <= 8:
                    print(f"[rx] {len(data)}B from {addr[0]} not Pia: {data[:16].hex()}")
                record(**entry)
            print(f"[lg] {n_rx} datagrams, {n_v3} with header version {PIA_VERSION}, "
                  f"{n_ok} authenticated; versions seen {versions}")
            print("[lg] releasing")

    try:
        trio.run(attempt)
        _warn_if_mid_trade()
        return 0
    except BaseException as e:
        print(f"[lg] failed: {type(e).__name__}: {e}")
        for sub in getattr(e, "exceptions", ()) or ():
            print(f"[lg]   caused by: {type(sub).__name__}: {sub}")
        import traceback; traceback.print_exc()
        cleanup_stale()
        _warn_if_mid_trade()
        return 6
    finally:
        if cap:
            cap.close()


if __name__ == "__main__":
    sys.exit(main())

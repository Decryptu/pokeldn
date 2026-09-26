#!/usr/bin/env python3
"""Join the network a Legends Arceus console hosts, and trade with it.

The game alternates: a station open and one second of scanning, then two to four seconds hosting
its own network, then teardown, on a five-second cycle. It registers its Pia protocols only while
it is hosting, so the session is entered from that side: scan in a loop and join the moment the
network appears. `pokeldn.pla.joiner` then answers the console the way a retail joiner does, from
the Net answer through the phase protocol.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/pla_join.py \\
        --keys ~/Documents/Switch/prod.keys --code 00000000 --capture scratchpad/pjNN.jsonl

    (them) Jubilife Village, the trading post, Simona -> echanger des pokemon ! -> local
           -> the SAME eight digits -> wait on the search screen

Over ldn_mitm, against an emulated console on the LAN, nothing needs root or a radio:

    ./.venv/bin/python bin/pla_join.py --ip-join --host-ip 172.16.86.1 --our-ip 172.16.86.128

Every datagram goes to --capture as one JSON line. `docs/pla.md` has the layouts.
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

from pokeldn import pla
from pokeldn.host_support import resolve_keys
from pokeldn.ldn import ldn_mitm, pia6
from pokeldn.ldn.transport import board_radio, find_ap_phy
from pokeldn.pla import data_exchange, joiner, trade_box
from pokeldn.pla import pokemon as pla_pokemon

STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]


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


def make_socket(ifname, our_ip=None):
    """The Pia socket: the board's userspace stack when it owns `ifname`, else a kernel socket."""
    from pokeldn.ldn import userspace_ip  # no kernel interface (ESP32 on macOS)
    if our_ip is None and (user := userspace_ip.udp_socket(ifname, pla.PIA_PORT)) is not None:
        user.setblocking(False)
        return user
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if our_ip is None and hasattr(socket, "SO_BINDTODEVICE"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, ifname.encode())
        except (PermissionError, OSError):
            pass
    s.bind((our_ip or "", pla.PIA_PORT))
    s.setblocking(False)
    return s


def build_offer(args, exchange):
    """-> the encrypted party record to trade away: a file, or the reference under our name."""
    if args.offer:
        return pla_pokemon.encrypt(pla_pokemon.load(open(os.path.expanduser(args.offer),
                                                         "rb").read()))
    return trade_box.build_our_record(**data_exchange.read_record(exchange))


async def run_session(args, keys, sock, host_ip, our_ip, our_mac, offer, exchange, record):
    """Hold one seat: feed every authenticated packet to the joiner and send what it owes.

    Wait in trio, never in select(): the ESP32 board's frames reach this socket through trio
    tasks (docs/hardware_esp32.md, The userspace stack).
    """
    session = joiner.JoinerSession(keys, our_ip, our_mac, offer, exchange,
                                   player_id=bytes.fromhex(args.join_player_id),
                                   drive=args.drive, net_answer=not args.no_net_answer, log=print)
    end = time.monotonic() + args.hold
    traded_at = None
    seen = authed = 0

    def send(packets, note=""):
        for pkt in packets:
            sock.sendto(pkt, (host_ip, pla.PIA_PORT))
            record(rec="out", dst=host_ip, hex=pkt.hex(), t=time.time(), note=note)

    try:
        while time.monotonic() < end and not session.host_left:
            if args.take_host and session.migration_asked is not None:
                print("[pla] leaving the seat to take the host role")
                break
            with trio.move_on_after(0.05):
                await trio.lowlevel.wait_readable(sock)
            while True:
                try:
                    data, addr = sock.recvfrom(4096)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                seen += 1
                src_ip = addr[0]
                record(rec="in", src=src_ip, hex=data.hex(), t=time.time())
                if src_ip != host_ip or not pia6.is_pia6(data):
                    continue
                header, plain, _ = pia6.parse_packet(keys.session_key, src_ip, keys.network_id,
                                                     data)
                if plain is None:
                    print(f"[pla] {src_ip}: {header!r} DID NOT AUTHENTICATE")
                    continue
                authed += 1
                messages = pia6.parse_messages(plain)
                for m in messages:
                    record(rec="msg", src=src_ip, protocol=m.protocol, port=m.port,
                           flags=m.message_flags, payload=m.payload.hex())
                try:
                    send(session.receive(messages))
                except Exception as exc:
                    # A fault in one message does not drop the seat: the console is still there.
                    print(f"[pla] the joiner raised on a message, still seated: "
                          f"{type(exc).__name__}: {exc}")
            send(session.poll())
            if session.traded and traded_at is None:
                traded_at = time.monotonic()
                if args.offer_out and session.received is not None:
                    with open(args.offer_out, "wb") as fh:
                        fh.write(session.received)
                    print(f"[pla] wrote the record the console traded, {args.offer_out}")
            if traded_at is not None and time.monotonic() - traded_at >= args.after_trade:
                send(session.leave(), note="leave")
                print("[pla] left the session after the trade")
                break
    finally:
        if args.collect:
            os.makedirs(args.collect, exist_ok=True)
            for selector, counter, rec in session.console_records:
                path = os.path.join(args.collect, f"{rec[:4].hex()}_{selector}.pa8")
                with open(path, "wb") as fh:
                    fh.write(rec)
        print(f"[pla] seat over: {seen} datagrams in, {authed} authenticated, "
              f"seated={session.seated}, traded={session.traded}")
    return session


def main_ip(args, offer, exchange, record):
    our_mac = b"\x02\x00" + socket.inet_aton(args.our_ip)
    deadline = time.time() + args.seconds
    attempts = joined = 0
    race_sock = None
    last_ssid = b""
    if args.race:
        race_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        race_sock.setblocking(False)
        race_sock.bind((args.our_ip, 0))
        print(f"[pla] race mode: scanning every {args.scan_interval * 1000:.0f} ms")
    while time.time() < deadline:
        attempts += 1
        t_seen = time.time()
        if args.race:
            info, t_seen = fast_scan(race_sock, args.host_ip, args.scan_interval, deadline,
                                     last_ssid)
            if info is None:
                continue
            last_ssid = ldn_mitm.session_id(info)
        else:
            info = scan_once(args.our_ip, args.host_ip, args.scan_timeout)
        if info is None:
            continue
        ssid = ldn_mitm.session_id(info)
        keys = pla.session_keys(ssid)
        print(f"[pla] scan {attempts}: the console is hosting. ssid={ssid.hex()} "
              f"network_id={keys.network_id:#010x}")
        try:
            synced, tcp = associate(args.our_ip, args.host_ip, our_mac, args.name,
                                    args.scan_timeout * 4)
        except (OSError, RuntimeError) as exc:
            print(f"[pla] the association failed: {exc}")
            continue
        joined += 1
        synced_id = ldn_mitm.session_id(synced)
        if synced_id != ssid:
            keys = pla.session_keys(synced_id)
        print(f"[pla] *** JOINED *** over IP, {(time.time() - t_seen) * 1000:.0f} ms after the scan")
        record(rec="seat", ssid=synced_id.hex(), network_id=keys.network_id, t=time.time())
        sock = make_socket(None, our_ip=args.our_ip)
        try:
            session = trio.run(run_session, args, keys, sock, args.host_ip, args.our_ip, our_mac,
                               offer, exchange, record)
        finally:
            sock.close()
            tcp.close()
        if session.traded:
            break
    print(f"[pla] {attempts} scan(s), {joined} join(s)")
    return 0


def main_radio(args, offer, exchange, record):
    import ldn

    if os.geteuid() != 0 and not board_radio():
        print("[pla] joining needs the raw radio; re-run under sudo, or set POKELDN_RADIO")
        return 1
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[pla] no AP-capable phy")
        return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[pla] prod.keys not found at {keys_path!r}")
        return 2
    if not board_radio():
        import subprocess
        for name in STALE_VIFS:
            subprocess.run(["iw", "dev", name, "del"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    if args.mac and board_radio():
        from pokeldn.ldn import esp32_wlan
        esp32_wlan.set_station_mac(args.mac)
    keys_file = ldn.load_keys(keys_path)
    channels = [int(c) for c in args.channels.split(",") if c.strip()]
    print(f"[pla] phy={phy} channels={channels} dwell={args.dwell}s code={args.code}")
    deadline = time.time() + args.seconds
    scans = seats = 0
    while time.time() < deadline:
        scans += 1

        async def find():
            return await ldn.scan(keys_file, phyname=phy, channels=channels,
                                  dwell_time=args.dwell)
        started = time.monotonic()
        try:
            nets = trio.run(find)
        except Exception as exc:
            print(f"[pla] the scan raised: {exc}")
            time.sleep(0.5)
            continue
        target = pick(args, nets, record)
        print(f"[pla] scan {scans}: {len(nets)} network(s) in {time.monotonic() - started:.1f}s"
              + ("" if target is None else f", Legends Arceus on channel {target.channel}"))
        if target is None:
            continue
        outcome = {}

        async def one_seat():
            outcome["session"] = await seat(args, keys_file, target, phy, offer, exchange,
                                            record)

        try:
            trio.run(one_seat)
            seats += 1
        except Exception as exc:
            def leaves(e):
                inner = getattr(e, "exceptions", ())
                return [x for i in inner for x in leaves(i)] if inner else [e]
            detail = "; ".join(f"{type(e).__name__}: {e}" for e in leaves(exc))
            print(f"[pla] the seat ended: {detail}")
            record(rec="seat_failed", detail=detail, t=time.time())
        if outcome.get("session") is not None and outcome["session"].traded:
            break
        if args.take_host and outcome.get("session") is not None \
                and outcome["session"].migration_asked is not None:
            return {"take_host": target.channel, "remaining": deadline - time.time()}
    print(f"[pla] {scans} scan(s), {seats} seat(s)")
    return 0


async def seat(args, keys_file, target, phy, offer, exchange, record):
    """Associate with the scanned network and hold one seat. -> the session, or None if the
    association did not complete within --connect-timeout."""
    import ldn

    keys = pla.session_keys(target.ssid)
    param = ldn.ConnectNetworkParam()
    param.keys, param.network, param.password = keys_file, target, pla.PASSPHRASE
    param.name, param.app_version = args.name.encode(), target.app_version
    param.phyname, param.ifname = phy, args.ifname
    with trio.move_on_after(args.connect_timeout) as scope:
        async with ldn.connect(param) as network:
            scope.deadline = float("inf")
            host = list(getattr(network.info(), "participants", []) or [])[0]
            ours = network.participant()
            host_ip, our_ip = str(host.ip_address), str(ours.ip_address)
            our_mac = bytes(ours.mac_address)
            print(f"[pla] *** SEATED *** host {host_ip}, us {our_ip} {our_mac.hex()}")
            record(rec="seat", ssid=target.ssid.hex(), host_ip=host_ip, our_ip=our_ip,
                   our_mac=our_mac.hex(), t=time.time())
            sock = make_socket(args.ifname)
            try:
                return await run_session(args, keys, sock, host_ip, our_ip, our_mac, offer,
                                         exchange, record)
            finally:
                sock.close()
    return None


def pick(args, nets, record):
    """-> the Legends Arceus network to join, or None: its communication id, the code if one was
    given, and a free seat."""
    for n in nets:
        if n.local_communication_id != pla.COMM_ID:
            continue
        app = bytes(n.application_data)
        record(rec="scan", ssid=n.ssid.hex(), channel=n.channel, app_data=app.hex(),
               participants=n.num_participants, t=time.time())
        if args.code:
            try:
                if pla.parse_advertise_data(app)["code"] != args.code:
                    continue
            except (ValueError, KeyError, IndexError):
                continue
        if n.num_participants < n.max_participants:
            return n
    return None


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip-join", action="store_true",
                    help="join over ldn_mitm on the LAN; no radio and no root")
    ap.add_argument("--host-ip", default="172.16.86.1", help="--ip-join: the console's address")
    ap.add_argument("--our-ip", default="172.16.86.128", help="--ip-join: our address")
    ap.add_argument("--scan-timeout", type=float, default=0.4)
    ap.add_argument("--race", action="store_true",
                    help="--ip-join: hold one scan socket and connect the instant a fresh network "
                         "appears, to land before the host latches its node list")
    ap.add_argument("--scan-interval", type=float, default=0.02)
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--channels", default="1,6,11")
    ap.add_argument("--dwell", type=float, default=0.4, help="seconds per channel in a scan")
    ap.add_argument("--connect-timeout", type=float, default=6.0)
    ap.add_argument("--mac", default=None, help="give the board this station MAC first")
    ap.add_argument("--code", default="00000000", help="the eight digits; '' joins any code")
    ap.add_argument("--name", default="PkCamp", help="the LDN node name we publish")
    ap.add_argument("--seconds", type=float, default=900.0, help="the whole run")
    ap.add_argument("--hold", type=float, default=600.0, help="how long one seat is held")
    ap.add_argument("--player-name", default="PkCamp",
                    help="the name in our data exchange record; the console shows it")
    ap.add_argument("--player-id", default="504b4c44",
                    help="hex, four bytes: the player id in our data exchange record")
    ap.add_argument("--join-player-id", default=pia6.DEFAULT_PLAYER_ID.hex(),
                    help="hex, sixteen bytes: the player id in the session join request")
    ap.add_argument("--offer", default=None,
                    help="the record to trade away, stored or party, encrypted or not; the "
                         "default is the reference Azelf under our player name")
    ap.add_argument("--offer-out", default=None,
                    help="write the record the console traded to this file")
    ap.add_argument("--collect", default=None,
                    help="write every record the console showed or offered to this directory")
    ap.add_argument("--after-trade", type=float, default=5.0,
                    help="seconds to stay seated after the trade before leaving")
    ap.add_argument("--drive", action="store_true",
                    help="act as the player too: offer once the host shows, confirm once it "
                         "offers, then selector 7; without it the console's player leads")
    ap.add_argument("--capture", default=None, help="every datagram as one JSON line")
    ap.add_argument("--no-net-answer", action="store_true",
                    help="send the Session join request with no Net 0x12 answer to the host's 0x11; "
                         "the 0x12 is what a console answers by asking for host migration")
    ap.add_argument("--take-host", action=argparse.BooleanOptionalAction, default=True,
                    help="when the console hands us the host role, leave its network and become "
                         "the host with bin/pla_host.py on the same code and channel")
    return ap


def host_argv(args, channel, seconds):
    """-> bin/pla_host.py's command line for the host role a console handed over: the retail
    host line, on the joiner's code, channel, keys and offer."""
    host = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pla_host.py")
    argv = [sys.executable, "-u", host, "--keys", args.keys, "--code", args.code,
            "--channel", str(channel), "--seconds", str(int(max(seconds, 60))),
            "--player-name", args.player_name, "--session-update", "--sustain", "--clock",
            "--data-exchange", "--game-channel", "--trade-box"]
    if args.offer:
        argv += ["--trade-box-record", args.offer]
    if args.collect:
        argv += ["--trade-box-collect", args.collect]
    if args.capture:
        root, ext = os.path.splitext(args.capture)
        argv += ["--capture", f"{root}_host{ext or '.jsonl'}"]
    return argv


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    exchange = data_exchange.build_record(player_id=bytes.fromhex(args.player_id),
                                          name=args.player_name)
    offer = build_offer(args, exchange)
    print(f"[pla] offering {trade_box.describe(offer)}")
    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    try:
        if args.ip_join:
            return main_ip(args, offer, exchange, record)
        result = main_radio(args, offer, exchange, record)
        if isinstance(result, dict) and "take_host" in result:
            argv = host_argv(args, result["take_host"], result["remaining"])
            print("[pla] *** TAKING THE HOST ROLE *** " + " ".join(argv[2:]))
            if cap:
                cap.close()
                cap = None
            sys.stdout.flush()
            os.execv(argv[0], argv)
        return result
    except KeyboardInterrupt:
        print("\n[pla] interrupted")
        return 0
    finally:
        if cap:
            cap.close()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Host a Legends Z-A local Link Trade, so a searching console joins it and trades.

A console on the Link Trade search alternates hosting and scanning, and joins a network carrying
the title's advertisement and its own link code. This host puts one up and runs the host's side of
the session and of the trade, `pokeldn.za.host`.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/za_host.py --keys KEYS \\
        --trade-offer scratchpad/za_offer_glaceon_built.bin --capture scratchpad/zhNN.jsonl

    (them) Link Trade -> local communication -> search, code 00000000

`--ip-host --our-ip 127.0.0.2` hosts an emulated console over ldn_mitm instead of the radio.
`docs/za.md` has what the host sends and why.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import config, za
from pokeldn.za import host as za_host
from pokeldn.za import streams
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
from pokeldn.host_support import resolve_keys


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--channel", type=int, default=6,
                    help="a searching console put both of its measured sessions on channel 6")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--code", default="00000000", help="the link code the player types")
    ap.add_argument("--capture", default=None, help="every datagram as one JSON line")
    ap.add_argument("--player-name", default=" ",
                    help="the LDN node name; a searching console advertises one space")
    ap.add_argument("--game-dir", default="scratchpad",
                    help="where the reference payloads za_ref_identity10.bin, "
                         "za_ref_identity11b.bin and za_ref_selection.bin live")
    ap.add_argument("--trade-offer", default=None,
                    help="the 354-byte offer message: the preview, then our pick")
    ap.add_argument("--offer-at", type=float, default=None,
                    help="make our pick this many seconds after the preview, without waiting for "
                         "the console's; the default answers the console's pick")
    ap.add_argument("--offer-out", default=None,
                    help="write the console's last offer message here, hex")
    ap.add_argument("--ip-host", action="store_true",
                    help="host an emulated console over ldn_mitm, with no radio")
    ap.add_argument("--our-ip", default=None)
    ap.add_argument("--comm-id", default=None,
                    help="hex; the default is the title's. An emulated Z-A advertises and scans "
                         "for ffffffffffffffff over ldn_mitm")
    ap.add_argument("--hold-after-trade", type=float, default=90.0,
                    help="seconds to keep the seat after the console's fourth step; the trade "
                         "animation runs past that step")
    return ap


def load_payloads(args):
    def read(name):
        path = os.path.join(args.game_dir, name)
        with open(path, "rb") as fh:
            return fh.read()
    identity = read("za_ref_identity10.bin")
    # The nine-byte message after the identity on protocol 11, stored with the joiner's prefix.
    tail = read("za_ref_identity11b.bin")[streams.PREFIX_SIZE:]
    selection = read("za_ref_selection.bin")
    offer = None
    if args.trade_offer:
        with open(args.trade_offer, "rb") as fh:
            offer = fh.read()
        if len(offer) != za.pokemon.OFFER_SIZE:
            raise SystemExit(f"--trade-offer is {len(offer)} bytes, an offer is "
                             f"{za.pokemon.OFFER_SIZE}")
        _hdr, plain, _tr = za.pokemon.parse_offer(offer)
        print(f"[za-host] offering {za.pokemon.read(plain)}")
    return identity, tail, selection, offer


def describe_offer(body):
    try:
        _hdr, plain, _tr = za.pokemon.parse_offer(body)
        return str(za.pokemon.read(plain))
    except ValueError as exc:
        return f"{len(body)} bytes that do not read as a record: {exc}"


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    if not args.ip_host and os.geteuid() != 0 and not board_radio():
        ap.error("hosting over the radio needs root or POKELDN_RADIO; or pass --ip-host")
    identity, tail, selection, offer = load_payloads(args)
    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
        if phy is None:
            print("[za-host] no AP-capable phy")
            return 1
    app_data = za.build_advertise_data(args.code)
    factory = IpHostTransport if args.ip_host else HostTransport
    machine = config.load_project_host_file_config()
    transport = factory(
        app_data=app_data, password=za.PASSPHRASE, nickname=args.player_name,
        keys_path=resolve_keys(args.keys), local_comm_id=int(args.comm_id, 16) if args.comm_id else za.COMM_ID, scene_id=za.SCENE_ID,
        app_version=za.APP_VERSION, max_participants=za.MAX_PARTICIPANTS, phyname=phy,
        channel=args.channel, protocol=za.LDN_PROTOCOL,
        **({"our_ip": args.our_ip} if args.ip_host and args.our_ip else {}),
        **({} if args.ip_host else dict(skip_encryption=machine.skip_encryption,
                                        accept_decrypted_ccmp=machine.accept_decrypted_ccmp)))
    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[za-host] the network did not come up: {exc}")
        return 2
    print(f"[za-host] hosting code {args.code}: ssid={transport.ssid.hex()} us={transport.our_ip}"
          f" channel={args.channel}")
    record(rec="host", ssid=transport.ssid.hex(), our_ip=transport.our_ip,
           our_mac=bytes(transport.our_mac).hex(), app_data=app_data.hex(), t=time.time())

    sessions = {}
    done_at = None
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            seated = {p[1] for p in list(transport.participants)}
            for ip in seated - set(sessions):
                print(f"[za-host] a console is seated at {ip}")
                record(rec="seat", ip=ip, t=time.time())
                sessions[ip] = za_host.HostSession(
                    ssid=transport.ssid, our_ip=transport.our_ip, our_mac=transport.our_mac,
                    guest_ip=ip, code=args.code, identity=identity, identity_tail=tail,
                    selection=selection, offer=offer, offer_at=args.offer_at,
                    log=print, record=record)
            for ip in set(sessions) - seated:
                s = sessions.pop(ip)
                print(f"[za-host] the console at {ip} left; {s.console_offers} offer(s), "
                      f"{s.steps} step(s)")
                record(rec="left", ip=ip, t=time.time())
            transport.wait_readable(0.01)
            for payload, src_ip in transport.recv():
                s = sessions.get(src_ip)
                if s is not None:
                    before = s.console_offer
                    s.receive(payload, src_ip)
                    if s.console_offer is not None and s.console_offer is not before:
                        print(f"[za-host] the console offers {describe_offer(s.console_offer)}")
                        if args.offer_out:
                            with open(args.offer_out, "w") as fh:
                                fh.write(s.console_offer.hex() + "\n")
            for s in list(sessions.values()):
                for data, ip in s.tick():
                    transport.send(data, ip)
                if s.trade_complete and done_at is None:
                    done_at = time.time()
            if done_at is not None and time.time() - done_at > args.hold_after_trade:
                print("[za-host] the trade is complete; closing")
                break
    except KeyboardInterrupt:
        print("\n[za-host] interrupted")
    finally:
        transport.stop()
        if cap:
            cap.close()
    for ip, s in sessions.items():
        print(f"[za-host] {ip}: {s.console_offers} console offer(s), {s.steps} step(s), "
              f"trade_complete={s.trade_complete}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Host a Sword/Shield Link Trade network, so a console searching for a partner joins it.

    ./.venv/bin/python bin/swsh_host.py --ip-host --our-ip 127.0.0.2 --advert FILE --seconds 300
    (them) Y-Comm -> Link Trade -> local communication, no code -> search

The layers below the game are `pokeldn.ldn.host4`: the Local Protocol, the station handshake, the
mesh, RTT and both reliable windows, answered as a retail Sword answers them while it hosts. Above
them this host speaks the sync framework the way the console spoke it to our joiner: it opens with
`ping` on 0x7C and answers what the joiner sends. Every datagram goes to --capture as JSON lines.
docs/swsh_session.md, docs/swsh_trade.md.
"""
import argparse
import binascii
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import config
from pokeldn.host_support import resolve_keys
from pokeldn.ldn import host4, reliable4
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
from pokeldn.swsh import trade
from pokeldn.swsh.session import COMM_ID, PASSPHRASE, session_keys

SCENE_ID = 60001                  # a retail Sword's Link Trade network
APP_VERSION = 7
LDN_PROTOCOL = 1
MAX_PARTICIPANTS = 2
ADVERT_SIZE = 0x180
GAME_DATA_OFF = 0x18
PING_PERIOD = 0.5                 # the console's own ping cadence before the joiner answers


def build_advert(template, network_id=None, session_param=None):
    """-> the 384 bytes of application data: the Pia header rebuilt, the game's record kept.

        0x00 network id, 0x04 CRC of the user password (0), 0x08 05, 0x09 0x18 (header size),
        0x0C session parameter, 0x10 eight zero bytes, 0x18 the game's own record
    """
    out = bytearray(bytes(template).ljust(ADVERT_SIZE, b"\0")[:ADVERT_SIZE])
    out[0:4] = network_id or os.urandom(4)
    out[4:8] = bytes(4)
    out[8:12] = bytes([5, GAME_DATA_OFF, 0, 0])
    out[12:16] = struct.pack("<I", session_param if session_param is not None
                             else struct.unpack("<I", os.urandom(4))[0])
    out[16:24] = bytes(8)
    return bytes(out)


def load_advert(path):
    """A file of hex (one advertisement) or 384 raw bytes, or a swsh_net_facts.json list."""
    raw = open(path, "rb").read()
    if path.endswith(".json"):
        return bytes.fromhex(json.loads(raw)[0]["application_data"])
    try:
        return binascii.unhexlify(raw.strip())
    except (binascii.Error, ValueError):
        return raw


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keys", default=None)
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--channel", type=int, default=None)
    ap.add_argument("--ip-host", action="store_true",
                    help="host over ldn_mitm on the LAN for an emulator; no radio and no root")
    ap.add_argument("--our-ip", default=None, help="with --ip-host, the address to advertise")
    ap.add_argument("--comm-id", type=lambda s: int(s, 0), default=COMM_ID)
    ap.add_argument("--scene-id", type=int, default=SCENE_ID)
    ap.add_argument("--app-version", type=int, default=APP_VERSION)
    ap.add_argument("--protocol", type=int, default=LDN_PROTOCOL, choices=(1, 3))
    ap.add_argument("--advert", required=True,
                    help="a Sword's own advertisement (hex, raw, or swsh_net_facts.json); its "
                         "game record from 0x18 is kept and the Pia header rebuilt")
    ap.add_argument("--player-name", default="PkCamp")
    ap.add_argument("--no-ping", action="store_true", help="never open with ping")
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--capture", default=None)
    return ap


def main():
    args = build_parser().parse_args()
    if not args.ip_host and os.geteuid() != 0 and not board_radio():
        print("[sw] hosting over the radio needs root, a board (POKELDN_RADIO), or --ip-host")
        return 1
    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    app_data = build_advert(load_advert(args.advert))

    class Net:
        application_data = app_data
    keys = session_keys(Net())
    cap = open(args.capture, "w") if args.capture else None

    def record(row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    machine = config.load_project_host_file_config()
    factory = IpHostTransport if args.ip_host else HostTransport
    transport = factory(
        app_data=app_data, password=PASSPHRASE, nickname=args.player_name,
        keys_path=resolve_keys(args.keys), local_comm_id=args.comm_id, scene_id=args.scene_id,
        app_version=args.app_version, max_participants=MAX_PARTICIPANTS, phyname=phy,
        channel=args.channel, protocol=args.protocol,
        **({"our_ip": args.our_ip} if args.ip_host and args.our_ip else {}),
        **({"mirror_comm_version": True} if args.ip_host else {}),
        **({} if args.ip_host else dict(skip_encryption=machine.skip_encryption,
                                        accept_decrypted_ccmp=machine.accept_decrypted_ccmp)))
    print(f"[sw] advertising comm id {args.comm_id:#018x} scene {args.scene_id} "
          f"app version {args.app_version}; {keys}")
    record({"rec": "host", "comm_id": args.comm_id, "app_data": app_data.hex(),
            "session_key": keys.session_key.hex()})

    said = {}                     # (ip, protocol, port) -> the joiner's newest payload
    queues = {}
    ping_state = {}               # ip -> [pings sent, when last, answered]

    def on_data(st, protocol, port, payload):
        key = (st.ip, protocol, port)
        said[key] = payload
        print(f"[sw] <- {st.ip} {protocol:#04x}/{port} {payload.hex()[:96]}")
        if protocol == reliable4.PROTOCOL and port == 0 and payload[:4] == b"\x61\0\0\0":
            ping_state.setdefault(st.ip, [0, 0.0, False])[2] = True
        answer, queues[key] = trade.next_answer(payload, queues.get(key, ()))
        if answer is not None and answer != payload:
            host.send_data(st.ip, protocol, port, answer)
            print(f"[sw] -> {st.ip} {protocol:#04x}/{port} {answer.hex()[:96]}")

    def on_other(st, protocol, port, payload):
        print(f"[sw] <- {st.ip} {protocol:#04x}/{port} (unhandled) {payload.hex()[:96]}")

    host = host4.Pia4Host(keys.network_id_le, keys.session_key, transport.our_ip,
                          transport.our_mac, transport.send, on_data=on_data,
                          on_other=on_other, name=args.player_name, capture=record)
    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[sw] the network did not come up: {exc}")
        return 2
    print(f"[sw] up at {transport.our_ip}; waiting for a console")
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            now = time.time()
            present = {p[1]: p for p in transport.participants}
            for ip, (index, _ip, mac, name) in present.items():
                if ip not in host.stations:
                    host.seat(ip, mac, index)
                    print(f"[sw] {ip} seated at LDN node {index} ({name!r})")
            for ip in list(host.stations):
                if ip not in present:
                    host.unseat(ip)
                    ping_state.pop(ip, None)
            for payload, src_ip in transport.recv():
                host.on_packet(payload, src_ip, now)
            host.tick(now)
            for ip, st in host.stations.items():
                if args.no_ping or st.state != "joined":
                    continue
                ps = ping_state.setdefault(ip, [0, 0.0, False])
                if not ps[2] and now - ps[1] >= PING_PERIOD:
                    host.send_data(ip, reliable4.PROTOCOL, 0, trade.sync(trade.SYNC_PING,
                                                                         trade.PING))
                    ps[0] += 1
                    ps[1] = now
            transport.wait_readable(0.02)
    except KeyboardInterrupt:
        print("\n[sw] stopping")
    finally:
        transport.stop()
        if cap:
            cap.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

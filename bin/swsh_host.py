#!/usr/bin/env python3
"""Host a Sword/Shield Link Trade network, so a console searching for a partner joins it.

    ./.venv/bin/python bin/swsh_host.py --ip-host --our-ip 127.0.0.2 --advert FILE --seconds 300
    (them) Y-Comm -> Link Trade -> local communication, no code -> search

The layers below the game are `pokeldn.ldn.host4`: the Local Protocol, the station handshake, the
mesh, RTT and both reliable windows, answered as a retail Sword answers them while it hosts. Above
them `pokeldn.swsh.host_trade` runs the trade the way a hosting Sword leads it: ping rounds, both
snapshots, the box, the exchange, the confirmation ladder and the host migration. Every datagram
goes to --capture as JSON lines. docs/swsh_session.md, docs/swsh_trade.md.
"""
import argparse
import binascii
import traceback
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import config
from pokeldn.host_support import resolve_keys
from pokeldn.ldn import host4, mesh_protocol as mesh, reliable4
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
from pokeldn.swsh import beacon, host_trade, pokemon as swsh_pokemon, trade_payload
from pokeldn.swsh.session import COMM_ID, PASSPHRASE, session_keys

SCENE_ID = 60001                  # a retail Sword's Link Trade network
APP_VERSION = 7
LDN_PROTOCOL = 1
MAX_PARTICIPANTS = 2
ADVERT_SIZE = 0x180
GAME_DATA_OFF = 0x18
RECORD_LEN = 0x168
# A searcher joins only a larger advertise-0x00 id than its own (0x006cba8c) and blacklists an id
# whose join failed for the rest of its search, so each run draws a fresh one near the top.
NETWORK_ID_HIGH = b"\xff\xff"


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
    record = out[GAME_DATA_OFF:GAME_DATA_OFF + RECORD_LEN]
    struct.pack_into("<H", out, GAME_DATA_OFF, beacon.crc16(record[2:]))
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
    ap.add_argument("--snapshot", default="scratchpad/sw70_0x84_payload.bin",
                    help="a Sword's 3456-byte 0x84 snapshot; its identity is moved to ours")
    ap.add_argument("--trainer-name", default="PkCamp")
    ap.add_argument("--trainer-tid", type=lambda s: int(s, 0), default=12345)
    ap.add_argument("--trainer-sid", type=lambda s: int(s, 0), default=54321)
    ap.add_argument("--offer-slot", type=int, default=1, help="the party slot we offer")
    ap.add_argument("--end-delay", type=float, default=host_trade.END_DELAY,
                    help="with --migrate, ladder done to box command 3 and the migration")
    ap.add_argument("--migrate", action="store_true",
                    help="end with box command 3 and MIGRATION_START, as the retail Sword that "
                         "led our joiner did; by default the host keeps the session")
    ap.add_argument("--received", default=None, help="write the joiner's Pokemon here")
    ap.add_argument("--network-id", default=None,
                    help="advertise 0x00, hex; a searching Sword joins only a larger one than its "
                         "own; default 0xFFFF and two random bytes")
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
    network_id = (bytes.fromhex(args.network_id) if args.network_id
                  else os.urandom(2) + NETWORK_ID_HIGH)       # little-endian: the high half last
    app_data = build_advert(load_advert(args.advert), network_id=network_id)
    snapshot = open(args.snapshot, "rb").read()
    if len(snapshot) != trade_payload.PAYLOAD_LENGTH:
        snapshot = trade_payload.inflate_short(snapshot)
    snapshot = trade_payload.rewrite(snapshot, trainer_name=args.trainer_name,
                                     trainer_id=args.trainer_tid, secret_id=args.trainer_sid)
    at = (args.offer_slot - 1) * swsh_pokemon.SIZE_PARTY
    offer = snapshot[at:at + swsh_pokemon.SIZE_PARTY]
    mon = swsh_pokemon.read(offer)
    print(f"[sw] our trainer {args.trainer_name} {args.trainer_tid}/{args.trainer_sid}; "
          f"offering slot {args.offer_slot}: species {mon['species']} {mon['nickname']!r} "
          f"level {mon['level']}")

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

    trades = {}                   # ip -> HostTrade

    def guarded(fn, *a):
        # A reader that raises stops the host mid-trade; the console calls that an interruption.
        try:
            fn(*a)
        except Exception:
            traceback.print_exc()

    def on_data(st, protocol, port, payload):
        record({"rec": "app_rx", "src": st.ip, "protocol": protocol, "port": port,
                "payload": payload.hex()})
        if protocol == mesh.PROTOCOL:
            print(f"[sw] <- {st.ip} mesh {payload.hex()}")
            return
        if st.ip in trades:
            guarded(trades[st.ip].on_data, protocol, port, payload)

    def on_broadcast(st, port, payload, flags):
        if st.ip in trades:
            guarded(trades[st.ip].on_broadcast, port, payload, bool(flags & 0x10))

    def on_other(st, protocol, port, payload):
        print(f"[sw] <- {st.ip} {protocol:#04x}/{port} (unhandled) {payload.hex()[:96]}")

    def start_trade(st):
        def send(protocol, port, payload):
            host.send_data(st.ip, protocol, port, payload)
            record({"rec": "app_tx", "dst": st.ip, "protocol": protocol, "port": port,
                    "payload": payload.hex()})

        def send_broadcast(port, message, compressed):
            host.send_broadcast(st.ip, port, message, compressed)

        def send_mesh(payload):
            host.send_data(st.ip, mesh.PROTOCOL, mesh.PORT_RELIABLE, payload)

        def on_record(**row):
            kind = row.pop("rec", None)
            record({"rec": "trade", "kind": kind, **row})
            if kind == "peer_exchange" and args.received:
                open(args.received, "wb").write(bytes.fromhex(row["pk8"]))
                print(f"[sw] the joiner's Pokemon written to {args.received}")

        trades[st.ip] = host_trade.HostTrade(host.constant, st.constant, snapshot, offer, send,
                                             send_broadcast, send_mesh,
                                             end_delay=args.end_delay, record=on_record,
                                             migrate=args.migrate)
        print(f"[sw] {st.ip}: the trade starts")

    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[sw] the network did not come up: {exc}")
        return 2
    # The board's MAC and address exist only once the transport is up.
    host = host4.Pia4Host(keys.network_id_le, keys.session_key, transport.our_ip,
                          transport.our_mac, transport.send, on_data=on_data,
                          on_other=on_other, on_broadcast=on_broadcast,
                          name=args.player_name, capture=record)
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
                    trades.pop(ip, None)
            for payload, src_ip in transport.recv():
                host.on_packet(payload, src_ip, now)
            host.tick(now)
            for ip, st in host.stations.items():
                if st.state == "joined" and ip not in trades:
                    start_trade(st)
            for tr in list(trades.values()):
                guarded(tr.tick, now)
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

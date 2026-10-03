#!/usr/bin/env python3
"""Host a Sword/Shield Link Trade network, so a console searching for a partner joins it.

    ./.venv/bin/python bin/swsh_host.py --ip-host --our-ip 127.0.0.2 --offer-file FILE
    (them) Y-Comm -> Link Trade -> local communication, no code (or --code) -> search

Below the game `pokeldn.ldn.host4`, above it `pokeldn.swsh.host_trade`. docs/swsh_session.md,
docs/swsh_trade.md.
"""
from pathlib import Path
import argparse
import binascii
import traceback
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.host_support import open_output
from pokeldn import pokemon as pokemon_service
from pokeldn.host_support import write_file
from pokeldn import config, gen8
from pokeldn.host_support import resolve_keys, needs_root
from pokeldn.ldn import host4, left_after_trade, mesh_protocol as mesh, reliable4
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, board_radio, find_ap_phy
from pokeldn.swsh import beacon, host_trade, league_card, pokemon as swsh_pokemon, trade_payload
from pokeldn.ldn.pia5 import password_crc
from pokeldn.swsh.session import COMM_ID, PASSPHRASE, session_keys
from pokeldn.app import screen

SCENE_ID = 60001  # a retail Sword's Link Trade network
APP_VERSION = 7
LDN_PROTOCOL = 1
MAX_PARTICIPANTS = 2
ADVERT_SIZE = 0x180
GAME_DATA_OFF = 0x18
RECORD_LEN = 0x168
STATION_PAGE_OFF = 0x1E
STATION_PROFILE_OFF = 0x1F
# A searcher joins only a larger id than its own (0x006cba8c) and blacklists one whose join failed,
# so each run draws a fresh one near the top (docs/swsh_session.md).
NETWORK_ID_HIGH = b"\xff\xff"


def build_advert(template=None, network_id=None, session_param=None, code="", player_name="POKELDN"):
    """-> the 384 advertise bytes: rebuild the Pia header and use a station record at 0x18,
    either fresh or copied from a console (docs/swsh_session.md)."""
    if template is None:
        out = bytearray(ADVERT_SIZE)
        out[GAME_DATA_OFF + 2:GAME_DATA_OFF + 4] = struct.pack("<H", beacon.NETWORK_ID)
        out[STATION_PAGE_OFF] = 1
        profile = STATION_PROFILE_OFF
        out[profile + trade_payload.TAIL_DEVICE_ID:
            profile + trade_payload.TAIL_DEVICE_ID + trade_payload.DEVICE_ID_LENGTH] = os.urandom(16)
        out[profile + trade_payload.TAIL_ACCOUNT_UID:
            profile + trade_payload.TAIL_ACCOUNT_UID + trade_payload.ACCOUNT_UID_LENGTH] = os.urandom(16)
        name = player_name.encode("utf-16-le")
        if len(name) > trade_payload.TAIL_NAME_LENGTH - 2:
            raise ValueError("player name is too long for the station profile")
        out[profile + trade_payload.TAIL_NAME_OFFSET:
            profile + trade_payload.TAIL_NAME_OFFSET + len(name)] = name
        out[profile + trade_payload.TAIL_ACTIVITY] = 13   # Link Trade
    else:
        if len(template) != ADVERT_SIZE:
            raise ValueError(f"advertisement is {len(template)} bytes, expected {ADVERT_SIZE}")
        out = bytearray(template)
    out[0:4] = network_id or os.urandom(4)
    out[4:8] = password_crc(code)
    out[8:12] = bytes([5, GAME_DATA_OFF, 0, 0])
    out[12:16] = struct.pack("<I", session_param if session_param is not None
                             else struct.unpack("<I", os.urandom(4))[0])
    out[16:24] = bytes(8)
    record = out[GAME_DATA_OFF:GAME_DATA_OFF + RECORD_LEN]
    struct.pack_into("<H", out, GAME_DATA_OFF, beacon.crc16(record[2:]))
    return bytes(out)


def load_advert(path):
    """A file of hex (one advertisement) or 384 raw bytes, or a swsh_net_facts.json list."""
    raw = Path(path).read_bytes()
    if path.endswith(".json"):
        return bytes.fromhex(json.loads(raw)[0]["application_data"])
    try:
        return binascii.unhexlify(raw.strip())
    except (binascii.Error, ValueError):
        return raw


def offer_record(args, offer_file, renew, slot_record):
    """-> the encrypted party record we offer: the file's, or the snapshot slot's."""
    if offer_file:
        raw = swsh_pokemon.encrypt(gen8.load(Path(offer_file).read_bytes()))
    else:
        raw = slot_record
    if struct.unpack_from("<I", raw)[0] == 0:
        raise ValueError(f"offer slot {args.offer_slot} is empty; pass --offer-file")
    if args.fresh_pid or renew:
        raw = swsh_pokemon.encrypt(gen8.fresh_identity(gen8.decrypt(raw)))
    if getattr(args, "validate_offer", False):
        raw = pokemon_service.prepare("swsh", raw)
        raw = swsh_pokemon.encrypt(gen8.load(raw))
    return raw


def prepare_snapshot(source, args, app_data, offer_file=None, renew=False):
    """Build this host's trade payload from a saved or joining console's 0x84 snapshot."""
    snapshot = trade_payload.inflate_short(source)
    original = snapshot
    identity = {}
    if args.advert is None or args.snapshot is None:
        profile = app_data[STATION_PROFILE_OFF:STATION_PROFILE_OFF + trade_payload.PROFILE_LENGTH]
        identity = dict(
            device_id=profile[trade_payload.TAIL_DEVICE_ID:
                              trade_payload.TAIL_DEVICE_ID + trade_payload.DEVICE_ID_LENGTH],
            account_uid=profile[trade_payload.TAIL_ACCOUNT_UID:
                                trade_payload.TAIL_ACCOUNT_UID + trade_payload.ACCOUNT_UID_LENGTH],
            nsa_id=profile[trade_payload.TAIL_NSA_ID:
                           trade_payload.TAIL_NSA_ID + trade_payload.NSA_ID_LENGTH])
    snapshot = trade_payload.rewrite(snapshot, trainer_name=args.trainer_name,
                                     trainer_id=args.trainer_tid, secret_id=args.trainer_sid,
                                     **identity)
    snapshot = original[:swsh_pokemon.PARTY_BLOCK] + snapshot[swsh_pokemon.PARTY_BLOCK:]
    at = (args.offer_slot - 1) * swsh_pokemon.SIZE_PARTY
    raw = offer_record(args, offer_file, renew, original[at:at + swsh_pokemon.SIZE_PARTY])
    snapshot = snapshot[:at] + raw + snapshot[at + swsh_pokemon.SIZE_PARTY:]
    if args.card_set:
        edits = {}
        for item in args.card_set:
            name, value = item.split("=", 1)
            edits[name] = value if name == "name" else int(value, 0)
        tc = trade_payload.TRAINER_CARD_OFFSET
        card = league_card.set_fields(snapshot[tc:tc + league_card.LENGTH], **edits)
        snapshot = snapshot[:tc] + card + snapshot[tc + league_card.LENGTH:]
        print(f"[sw] League Card: {league_card.read(card)}")
    mon = swsh_pokemon.read(raw)
    print(f"[sw] our trainer {args.trainer_name} {args.trainer_tid}/{args.trainer_sid}; "
          f"offering slot {args.offer_slot}: species {mon['species']} {mon['nickname']!r} "
          f"level {mon['level']}")
    return snapshot, raw


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
    ap.add_argument("--advert", default=None,
                    help="optional Sword advertisement (hex, raw, or swsh_net_facts.json); "
                         "without one, build a fresh station record")
    ap.add_argument("--player-name", default="POKELDN")
    ap.add_argument("--snapshot", default=None,
                    help="optional saved Sword 0x84 snapshot; otherwise use the joining console's "
                         "snapshot from this session")
    ap.add_argument("--trainer-name", default="POKELDN")
    ap.add_argument("--trainer-tid", type=lambda s: int(s, 0), default=12345)
    ap.add_argument("--trainer-sid", type=lambda s: int(s, 0), default=54321)
    ap.add_argument("--offer-slot", type=int, default=1, help="the party slot we offer")
    ap.add_argument("--offer-file", action="append", default=[],
                    help="a PK8 to place in the offered party slot, encrypted or PKHeX export. "
                         "Repeatable, one per trade: the player trades again from the box, or "
                         "searches again; the last serves every later trade")
    ap.add_argument("--fresh-pid", action="store_true",
                    help="draw a new encryption constant and PID for the offered Pokemon")
    ap.add_argument("--card-set", action="append", default=[], metavar="FIELD=VALUE",
                    help="set a field of the League Card the console may keep after the trade "
                         "(pokeldn.swsh.league_card: name, trainer_id, dex_owned, poke1_species, ...)")
    ap.add_argument("--end-delay", type=float, default=host_trade.END_DELAY,
                    help="with --migrate, ladder done to box command 3 and the migration")
    ap.add_argument("--migrate", action="store_true",
                    help="end with box command 3 and MIGRATION_START, as the retail Sword that "
                         "led our joiner did; by default the host keeps the session")
    ap.add_argument("--accept-first", action="store_true",
                    help="accept without waiting for the joiner's acceptance, as a player would; "
                         "for our own joiner, which accepts after its partner")
    ap.add_argument("--lead", type=float, default=None, metavar="SECONDS",
                    help="test only, for bin/swsh_connect.py: act as a console host's player: "
                         "after a trade with another --offer-file queued, offer it from the box this "
                         "many seconds after the ladder, without waiting for the joiner's offer")
    ap.add_argument("--received", default=None,
                    help="write the joiner's Pokemon here; trade N > 1 writes FILE-N")
    ap.add_argument("--code", default="",
                    help="the Link Code the player searches with, e.g. 12345678; none by default")
    ap.add_argument("--network-id", default=None,
                    help="advertise 0x00, hex; a searching Sword joins only a larger one than its "
                         "own; default 0xFFFF and two random bytes")
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--capture", default=None)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.offer_file = [pokemon_service.prepare_file("swsh", path, fresh=args.fresh_pid)
                       for path in args.offer_file]
    # A trade past the queue offers the last file again, under a new PID with --fresh-pid.
    args.renew_offer, args.fresh_pid = args.fresh_pid, False
    if not args.ip_host and needs_root():
        print("[sw] hosting over the radio needs root, a board (POKELDN_RADIO), or --ip-host")
        return 1
    phy = None
    if not args.ip_host:
        phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    network_id = (bytes.fromhex(args.network_id) if args.network_id
                  else os.urandom(2) + NETWORK_ID_HIGH)       # little-endian: the high half last
    app_data = build_advert(load_advert(args.advert) if args.advert else None,
                            network_id=network_id, code=args.code, player_name=args.player_name)
    if not 1 <= args.offer_slot <= swsh_pokemon.PARTY_SLOTS:
        raise ValueError(f"offer slot must be 1..{swsh_pokemon.PARTY_SLOTS}")
    def offer_file(n):
        return args.offer_file[min(n, len(args.offer_file) - 1)] if args.offer_file else None

    def build_snapshot(source, n):
        snapshot, offer = prepare_snapshot(source, args, app_data, offer_file(n),
                                           renew=args.renew_offer and n >= len(args.offer_file))
        screen.offer("swsh", offer)
        return snapshot, offer

    class Net:
        application_data = app_data
    keys = session_keys(Net())
    cap = open_output(args.capture, "w") if args.capture else None

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

    trades = {}
    completed = [0]     # trades that reached the end of the ladder, every session
    seen = {}           # HostTrade -> trades counted from it

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

        n = completed[0]    # trade k of this session is trade n + k of the run

        def on_record(**row):
            kind = row.pop("rec", None)
            record({"rec": "trade", "kind": kind, **row})
            if kind == "peer_exchange" and args.received:
                path = pokemon_service.trade_path(args.received, n + trades[st.ip].trades + 1)
                write_file(path, bytes.fromhex(row['pk8']))
                print(f"[sw] the joiner's Pokemon written to {path}")

        def next_offer(k):
            i = n + k - 1
            print(f"[sw] {st.ip}: trade {i + 1} offers "
                  f"{offer_file(i) or 'the snapshot slot again'}")
            return offer_record(args, offer_file(i), args.renew_offer and i >= len(args.offer_file),
                                trades[st.ip].offer_pk8)

        snapshot = offer = None
        if args.snapshot:
            snapshot, offer = build_snapshot(Path(args.snapshot).read_bytes(), n)
        trades[st.ip] = host_trade.HostTrade(host.constant, st.constant, snapshot, offer, send,
                                             send_broadcast, send_mesh,
                                             end_delay=args.end_delay, record=on_record,
                                             migrate=args.migrate,
                                             snapshot_builder=(lambda peer: build_snapshot(peer, n))
                                             if snapshot is None else None,
                                             next_offer=next_offer, accept_first=args.accept_first,
                                             lead=args.lead, queued=len(args.offer_file) - n)
        print(f"[sw] {st.ip}: trade {n + 1} starts")

    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[sw] the network did not come up: {exc}")
        return 2
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
            if left_after_trade(present):
                print("[sw] the console left after the trade; closing")
                break
            for payload, src_ip in transport.recv():
                host.on_packet(payload, src_ip, now)
            host.tick(now)
            for ip, st in host.stations.items():
                if st.state == "joined" and ip not in trades:
                    start_trade(st)
            for tr in list(trades.values()):
                guarded(tr.tick, now)
                if tr.trades > seen.get(tr, 0):
                    completed[0] += tr.trades - seen.get(tr, 0)
                    seen[tr] = tr.trades
                    left = len(args.offer_file) - completed[0]
                    print(f"[sw] trade {completed[0]} complete"
                          + (f"; {left} queued" if left > 0 else ""))
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

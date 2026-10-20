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
import random
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.host_support import open_output
from pokeldn import pokemon as pokemon_service
from pokeldn.host_support import write_file
from pokeldn import config, gen8
from pokeldn.host_support import resolve_keys, needs_root
from pokeldn.ldn import host4, left_after_trade, mesh_protocol as mesh
from pokeldn.ldn.ldn_mitm_host import IpHostTransport
from pokeldn.ldn.transport import HostTransport, find_ap_phy
from pokeldn.swsh import beacon, host_trade, lair, lair_host, league_card, pokemon as swsh_pokemon, raid, raid_event, raid_host, trade_payload
from pokeldn.ldn.pia5 import password_crc
from pokeldn.swsh.session import COMM_ID, PASSPHRASE, session_keys
from pokeldn.app import screen
from pokeldn.online import session as online

SCENE_ID = 60001  # a retail Sword's Link Trade network
RAID_SCENE_ID = 60006  # a den lobby (docs/swsh_raid.md)
LAIR_SCENE_ID = 50000  # a Max Lair lobby
LAIR_HANDOVER = 10.0   # a hosting Sword destroys its network within 10 s of the handover
RAID_PARTICIPANTS = 4
RAID_UID_COPY = 0x55
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
    ap.add_argument("--raid-boss", default=None, metavar="PK8",
                    help="host a Max Raid den lobby with this boss instead of a Link Trade "
                         "(docs/swsh_raid.md)")
    ap.add_argument("--raid-reward", action="append", default=[], metavar="ITEM:COUNT",
                    help="a reward row, item id and count; up to 15; none gives an emulated den's rows")
    ap.add_argument("--raid-seed", type=lambda s: int(s, 0), default=None,
                    help="the BattleSeed value; random by default")
    ap.add_argument("--raid-ready", type=float, default=3.0, metavar="SECONDS",
                    help="our player readies this long after the guest's lobby opens")
    ap.add_argument("--raid-event", default=None, metavar="FOLDER",
                    help="host a Max Raid with a boss of this Wild Area Event delivery (an EventsGallery "
                         "'Index NNN' folder) instead of --raid-boss; its rewards unless --raid-reward "
                         "(docs/swsh_raid.md, Event raids)")
    ap.add_argument("--raid-stars", type=int, default=None, metavar="N",
                    help="with --raid-event: the star rank, 1 to 5")
    ap.add_argument("--raid-event-boss", type=int, default=None, metavar="N",
                    help="with --raid-event: the boss, numbered as the list printed without it")
    ap.add_argument("--raid-version", choices=("sword", "shield"), default=None,
                    help="with --raid-event: whose table the boss comes from; the advertisement's "
                         "version by default")
    ap.add_argument("--raid-area", choices=[a for _, a in raid_event.AREAS], default=raid_event.AREAS[0][1],
                    help="with --raid-event: the den area whose table the boss comes from")
    ap.add_argument("--raid-event-drops", choices=("roll", "all"), default="roll",
                    help="with --raid-event: roll each drop's chance as a den does, or give every drop")
    ap.add_argument("--raid-gigantamax", action="store_true",
                    help="the --raid-boss boss is Gigantamax; a retail console accepts it where a base "
                         "den holds that Gigantamax Pokemon (docs/swsh_raid.md)")
    ap.add_argument("--raid-console-serves", action="store_true",
                    help="put the console first in BattleStart and framework object 0, so it serves "
                         "the battle and the board answers as a client (docs/swsh_raid.md)")
    ap.add_argument("--lair-legendary", type=int, default=None, metavar="SPECIES",
                    help="host a Dynamax Adventure (Max Lair) lobby whose legendary is this species; "
                         "the host leaves once the adventure starts (docs/swsh_raid.md)")
    ap.add_argument("--lair-seed", type=lambda s: int(s, 0), default=None,
                    help="the adventure seed (ChikaBattleSeed): the rentals and encounters; random "
                         "by default")
    ap.add_argument("--lair-leave", type=float, default=5.0, metavar="SECONDS",
                    help="leave this long after the legendary is sent; a computer partner then takes "
                         "our seat and picks our rental")
    online.add_arguments(ap)
    return ap


def lair_code(code):
    """A Max Lair lobby's Link Code as its advertisement hashes it: the decimal value, leading zeros
    dropped (docs/swsh_raid.md)."""
    return str(int(code)) if code else ""


def station_advert(app_data, player_name="POKELDN"):
    """A lobby advertisement with fresh device and account ids and our name."""
    out = bytearray(app_data)
    # A guest's Y-Comm list leaves out a raid that carries its own account (docs/swsh_raid.md).
    for at, n in ((trade_payload.TAIL_DEVICE_ID, trade_payload.DEVICE_ID_LENGTH),
                  (trade_payload.TAIL_ACCOUNT_UID, trade_payload.ACCOUNT_UID_LENGTH)):
        out[STATION_PROFILE_OFF + at:STATION_PROFILE_OFF + at + n] = os.urandom(n)
    out[RAID_UID_COPY:RAID_UID_COPY + 10] = out[0x2D:0x37]   # the same 10 bytes, in both adverts read
    name = player_name.encode("utf-16-le")[:trade_payload.TAIL_NAME_LENGTH - 2]
    at = STATION_PROFILE_OFF + trade_payload.TAIL_NAME_OFFSET
    out[at:at + trade_payload.TAIL_NAME_LENGTH] = name.ljust(trade_payload.TAIL_NAME_LENGTH, b"\0")
    struct.pack_into("<H", out, GAME_DATA_OFF, beacon.crc16(out[GAME_DATA_OFF + 2:GAME_DATA_OFF + RECORD_LEN]))
    return bytes(out)


def raid_advert(app_data, boss_pk8, player_name="POKELDN", rank=None):
    """The den advertisement with the boss's species and encryption constant written in."""
    return raid.den_advert(station_advert(app_data, player_name), boss_pk8, rank)


def event_raid(args, app_data):
    """-> (boss record, rank, reward rows) the --raid-event flags pick, or an error to print."""
    if args.raid_boss:
        return "--raid-event and --raid-boss each name the boss; pass one"
    try:
        event = raid_event.load(args.raid_event)
    except (OSError, ValueError) as error:
        return f"{args.raid_event}: {error}"
    if args.raid_area not in event.areas():
        return f"this event has no {args.raid_area} table; it has {', '.join(event.areas())}"
    version = ({"sword": 1, "shield": 2}[args.raid_version] if args.raid_version
               else 2 if app_data[raid.ADVERT_VERSION] & 2 else 1)
    if args.raid_stars is None or not 1 <= args.raid_stars <= raid_event.RANKS:
        ranks = sorted({r + 1 for b in event.bosses if b.version == version and b.area == args.raid_area
                        for r in b.ranks})
        return f"--raid-stars takes the star rank, 1 to 5; this event has {ranks}"
    rank = args.raid_stars - 1
    bosses = event.choices(version, rank, args.raid_area)
    if not bosses:
        return f"no {args.raid_stars}-star boss in {raid_event.VERSIONS[version]}'s {args.raid_area} table"
    if args.raid_event_boss is None or not 1 <= args.raid_event_boss <= len(bosses):
        lines = "\n".join(f"  {n}. {raid_event.describe(b, rank)}" for n, b in enumerate(bosses, 1))
        return (f"--raid-event-boss picks one of the {args.raid_stars}-star bosses of "
                f"{raid_event.VERSIONS[version]}'s {args.raid_area} table:\n{lines}")
    boss = bosses[args.raid_event_boss - 1]
    missing = raid_event.missing_rewards(event, boss)
    if missing and not args.raid_reward:
        print(f"[raid] no {' and '.join(missing)} reward table for this boss in the event or the game")
    rewards = raid_event.rewards(event, boss, rank,
                                 None if args.raid_event_drops == "all" else random.SystemRandom())
    print(f"[raid] event index {event.index}: {raid_event.describe(boss, rank)}, {args.raid_stars} stars")
    return raid_event.boss_pk8(boss), rank, rewards


def raid_rewards(args, app_data, event_rewards):
    """-> the Rewards rows the advertised den's guest accepts, or an error to print. A guest leaves
    unless every row fits its den slot's tables at the rank (0x01032570): chosen rows that do not are
    refused, an event's are left out, and without either the den's own go."""
    rewards = [tuple(int(x, 0) for x in r.split(":")) for r in args.raid_reward] or event_rewards
    if len(rewards) > raid.REWARD_SLOTS:
        return f"a Max Raid gives at most {raid.REWARD_SLOTS} rewards"
    if any(not 1 <= count <= 999 for _, count in rewards):
        return "a reward's count is 1 to 999"
    row, den_rank = raid.den_of(app_data)
    if row is None:
        return rewards
    if args.raid_reward:
        refused = raid.fitting_rewards(row, den_rank, rewards)[1]
        if refused:
            choices = raid.reward_choices(row, den_rank)
            return (f"not rewards of this den: {refused}; it gives "
                    + ", ".join(f"{item} x{'any' if n is None else n}" for item, n in choices.items()))
    elif args.raid_event:
        rewards, refused = raid.fitting_rewards(row, den_rank, rewards)
        if refused:
            print(f"[raid] left out, not in this den's rewards: {refused}")
        rewards = rewards or raid.den_rewards(row, den_rank)[:raid.REWARD_SLOTS]
    else:
        rewards = raid.den_rewards(row, den_rank)[:raid.REWARD_SLOTS]
    print(f"[raid] rewards {rewards}")
    return rewards


def show_lobby(app_data, boss_pk8, legendary, code):
    """A hosted Max Raid's boss or a Dynamax Adventure's legendary on the board's screen."""
    names = raid_event.tables()["species_names"]
    if boss_pk8 is not None:
        plain = gen8.decrypt(bytes(boss_pk8))
        boss = gen8.read(plain)
        screen.lobby("Max Raid", boss["species"], names.get(str(boss["species"]), ""), RAID_PARTICIPANTS - 1,
                     stars=(app_data[raid.ADVERT_RANK] >> 4) + 1, code=code, form=boss["form"],
                     gigantamax=bool(plain[raid.PK8_GIGANTAMAX] & 0x10))
    elif legendary is not None:
        screen.lobby("Adventure", legendary, names.get(str(legendary), ""), RAID_PARTICIPANTS - 1, code=code)


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.online and args.offer_file:
        print("[sw] --online offers the partner's Pokemon; --offer-file is ignored")
        args.offer_file = []
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
    event_only = [flag for flag, value in (("--raid-stars", args.raid_stars), ("--raid-event-boss", args.raid_event_boss),
                                           ("--raid-version", args.raid_version)) if value is not None]
    if event_only and not args.raid_event:
        print(f"[raid] {', '.join(event_only)} pick from an event; pass --raid-event FOLDER")
        return 1
    raiding = bool(args.raid_boss or args.raid_event)
    lairing = args.lair_legendary is not None
    if lairing:
        if raiding:
            print("[lair] --lair-legendary hosts a Dynamax Adventure; drop the --raid flags")
            return 1
        if args.lair_legendary not in lair.legendaries():
            print(f"[lair] {args.lair_legendary} is not a Max Lair legendary; one of {lair.legendaries()}")
            return 1
        args.advert = args.advert or str(lair_host.ADVERT)
        args.snapshot = args.snapshot or str(raid.DEN_SNAPSHOT)
        args.scene_id = LAIR_SCENE_ID
        lair_seed = (args.lair_seed if args.lair_seed is not None
                     else struct.unpack("<Q", os.urandom(8))[0])
        offer, encounters = lair.adventure(lair_seed)
        print(f"[lair] seed {lair_seed:#018x}: rentals {[r[0] for r in offer[:3]]}, "
              f"encounters {[r[0] for r in encounters]}")
    if raiding:
        args.advert = args.advert or str(raid.DEN_ADVERT)
        args.snapshot = args.snapshot or str(raid.DEN_SNAPSHOT)
    app_data = build_advert(load_advert(args.advert) if args.advert else None,
                            network_id=network_id, code=lair_code(args.code) if lairing else args.code,
                            player_name=args.player_name)
    boss_pk8 = None
    if raiding:
        rank, event_rewards = None, list(raid.DEN_REWARDS)
        if args.raid_event:
            picked = event_raid(args, app_data)
            if isinstance(picked, str):
                print(f"[raid] {picked}")
                return 1
            boss_pk8, rank, event_rewards = picked
        else:
            boss_file = pokemon_service.prepare_file("swsh", args.raid_boss)
            plain = bytearray(gen8.load(Path(boss_file).read_bytes()))
            if args.raid_gigantamax:
                plain[raid.PK8_GIGANTAMAX] |= 0x10
            boss_pk8 = raid.boss_record(swsh_pokemon.encrypt(bytes(plain)))
        if os.environ.get("POKELDN_RAID_BOSS_EDIT"):
            # Test only: OFFSET=HEX,... written into the plain boss record, to bisect a refusal.
            plain = bytearray(gen8.decrypt(boss_pk8))
            for edit in os.environ["POKELDN_RAID_BOSS_EDIT"].split(","):
                at, value = edit.split("=")
                data = bytes.fromhex(value)
                plain[int(at, 0):int(at, 0) + len(data)] = data
            boss_pk8 = swsh_pokemon.encrypt(bytes(plain))
            print(f"[raid] boss edited: {os.environ['POKELDN_RAID_BOSS_EDIT']}")
        app_data = raid_advert(app_data, boss_pk8, args.player_name, rank)
        if app_data[raid.ADVERT_DEN:raid.ADVERT_DEN + 8] == bytes(8):
            print("[raid] no den of this version holds the boss: a retail console lists the raid and "
                  "leaves at Ready (docs/swsh_raid.md, The boss record)")
        args.scene_id = RAID_SCENE_ID
        if args.raid_reward:
            bag = {entry["id"] for entry in pokemon_service.SERVICE.names("swsh", "bag")}
            unknown = sorted({int(r.split(":")[0], 0) for r in args.raid_reward} - bag)
            if unknown:
                print(f"[raid] items {unknown} cannot go in a Sword/Shield bag")
                return 1
        rewards = raid_rewards(args, app_data, event_rewards)
        if isinstance(rewards, str):
            print(f"[raid] {rewards}")
            return 1
        seed = args.raid_seed if args.raid_seed is not None else struct.unpack("<Q", os.urandom(8))[0]
    if lairing:
        app_data = station_advert(app_data, args.player_name)
    if not 1 <= args.offer_slot <= swsh_pokemon.PARTY_SLOTS:
        raise ValueError(f"offer slot must be 1..{swsh_pokemon.PARTY_SLOTS}")
    def offer_file(n):
        return args.offer_file[min(n, len(args.offer_file) - 1)] if args.offer_file else None

    def build_snapshot(source, n):
        # Online, the snapshot's slot keeps the console's own Pokemon: the offer goes on 20030.
        snapshot, offer = prepare_snapshot(source, args, app_data, offer_file(n),
                                           renew=args.renew_offer and n >= len(args.offer_file))
        if partner is None:
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
        app_version=args.app_version,
        max_participants=RAID_PARTICIPANTS if boss_pk8 or lairing else MAX_PARTICIPANTS, phyname=phy,
        channel=args.channel, protocol=args.protocol,
        **({"our_ip": args.our_ip} if args.ip_host and args.our_ip else {}),
        **({"mirror_comm_version": True} if args.ip_host else {}),
        **({} if args.ip_host else dict(skip_encryption=machine.skip_encryption,
                                        accept_decrypted_ccmp=machine.accept_decrypted_ccmp)))
    print(f"[sw] advertising comm id {args.comm_id:#018x} scene {args.scene_id} "
          f"app version {args.app_version}; {keys}")
    record({"rec": "host", "comm_id": args.comm_id, "app_data": app_data.hex(),
            "session_key": keys.session_key.hex()})

    partner = online.partner("swsh", args, code=args.code, name=args.trainer_name)
    trades = {}
    party = [None]      # the raid lobby every joined console shares
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
        if boss_pk8 is not None or lairing:
            def send_lobby(protocol, port, payload, compress):
                host.send_data(st.ip, protocol, port, payload, compress=compress)
                record({"rec": "app_tx", "dst": st.ip, "protocol": protocol, "port": port,
                        "payload": payload.hex()})

            if lairing:
                trades[st.ip] = lair_host.LairHost(
                    host.constant, st.constant, snapshot, offer, send_lobby, send_broadcast, send_mesh,
                    args.lair_legendary, lair_seed, struct.unpack("<Q", os.urandom(8))[0],
                    name=args.player_name, ready_after=args.raid_ready, leave_after=args.lair_leave,
                    record=on_record,
                    snapshot_builder=(lambda peer: build_snapshot(peer, n)) if snapshot is None else None)
                print(f"[lair] {st.ip}: lobby opens, legendary {args.lair_legendary}")
                return

            def on_battle(lobby):
                print(f"[raid] {st.ip}: both sides started; the battle on 0x7C follows")
            trades[st.ip] = raid_host.RaidHost(
                host.constant, st.constant, snapshot, offer, boss_pk8, send_lobby, send_broadcast,
                send_mesh, rewards=rewards, seed=seed, name=args.player_name,
                ready_after=args.raid_ready, record=on_record,
                snapshot_builder=(lambda peer: build_snapshot(peer, n)) if snapshot is None else None,
                on_battle=on_battle, console_serves=args.raid_console_serves, party=party[0])
            print(f"[raid] {st.ip}: lobby opens, seed {seed:#018x}")
            return
        trades[st.ip] = host_trade.HostTrade(host.constant, st.constant, snapshot, offer, send,
                                             send_broadcast, send_mesh,
                                             end_delay=args.end_delay, record=on_record,
                                             migrate=args.migrate,
                                             snapshot_builder=(lambda peer: build_snapshot(peer, n))
                                             if snapshot is None else None,
                                             next_offer=next_offer, accept_first=args.accept_first,
                                             lead=args.lead, queued=len(args.offer_file) - n,
                                             partner=partner)
        print(f"[sw] {st.ip}: trade {n + 1} starts")

    try:
        transport.start()
    except RuntimeError as exc:
        print(f"[sw] the network did not come up: {exc}")
        return 2
    host = host4.Pia4Host(keys.network_id_le, keys.session_key, transport.our_ip,
                          transport.our_mac, transport.send, on_data=on_data,
                          on_other=on_other, on_broadcast=on_broadcast,
                          name=args.player_name, capture=record,
                          max_stations=RAID_PARTICIPANTS if boss_pk8 or lairing else 2)
    if boss_pk8 is not None:
        party[0] = raid_host.RaidParty(host.constant, args.raid_console_serves)
    show_lobby(app_data, boss_pk8, args.lair_legendary, args.code)
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
                    gone = trades.pop(ip, None)
                    if party[0] is not None:
                        party[0].remove(gone)
            if boss_pk8 is not None or lairing:
                screen.joined(min(len(present), RAID_PARTICIPANTS - 1))
            if left_after_trade(present):
                print("[sw] the console left after the trade; closing")
                break
            for payload, src_ip in transport.recv():
                host.on_packet(payload, src_ip, now)
            host.tick(now)
            for ip, st in host.stations.items():
                if st.state == "joined" and ip not in trades:
                    start_trade(st)
            # Hand the session to the console as a leaving host does, then close the network.
            if host.migrating is None and any(getattr(tr, "finished", False) for tr in trades.values()):
                host.leave_with_migration(now)
                print("[lair] the adventure has started; handing the session to the console")
            if host.migrating is not None and (not host.stations or now - host.migrating >= LAIR_HANDOVER):
                print(f"[lair] closing the network {now - host.migrating:.1f} s after the handover, "
                      f"{len(host.stations)} station(s) left in it")
                break
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
        screen.drain()
        transport.stop()
        if partner:
            partner.close()
        if cap:
            cap.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

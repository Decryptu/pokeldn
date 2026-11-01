"""The Max Raid den lobby's messages: id 2000, `net_contents.nesthole.protocol_buffers.
NestholeAsyncDataHolder`, each field a holder of one `bytes` field (main `0x1bfde43`, `0x20677b0`).
A joining guest sends PlayerInfo, BattleReady and SelectPokemon after the snapshot; the host adds
the time limit and, at the start, BattleStart, BossPokemon, Rewards and BattleSeed (docs/swsh_raid.md)."""
import json
import struct
from pathlib import Path

from pokeldn import gen8
from pokeldn.swsh import beacon
from pokeldn.swsh.trade import field, message

NESTHOLE = 2000
TIME_LIMIT, PLAYER_INFO, BATTLE_READY, SELECT_POKEMON = 1, 2, 3, 4
BATTLE_START, BOSS_POKEMON, REWARDS, BATTLE_SEED = 5, 6, 7, 8
NAME_CHARS = 13
STATIONS = 4
REWARD_SLOTS = 15
# An emulated den's reward rows (item id, count): what a hosted raid gives when none are chosen.
DEN_REWARDS = ((1124, 5), (1125, 1), (1129, 1), (50, 1), (1149, 1))
# BossPokemon's 20-byte head and BattleSeed's last 8 bytes, the same in two emulated raids; unread.
BOSS_HEAD = bytes(19) + b"\xff"
SEED_TAIL = bytes.fromhex("00ffffff1e000300")


def holder(which, data):
    return message(NESTHOLE, field(which, field(1, data)))


def player_info(name):
    """40 bytes as two emulated Shields sent them: 8 zero, u32 0x12, the UTF-16 name, then 0x03."""
    raw = name.encode("utf-16-le")
    if len(raw) > 2 * (NAME_CHARS - 1):
        raise ValueError(f"{name!r} is longer than {NAME_CHARS - 1} characters")
    body = bytes(8) + struct.pack("<I", 0x12) + raw.ljust(2 * NAME_CHARS, b"\0") + b"\0\x03"
    return holder(PLAYER_INFO, body)


def battle_ready(ready=False, started=False):
    """16 bytes, zero until ready; a retail host's ready sets byte 8 to 1, and byte 12 once it has
    sent BattleStart."""
    body = bytearray(16)
    body[8] = 1 if ready else 0
    body[12] = 1 if started else 0
    return holder(BATTLE_READY, bytes(body))


def select_pokemon(pk8):
    """8 zero bytes and the chosen Pokemon in its encrypted party form."""
    pk8 = bytes(pk8)
    if len(pk8) != 0x158:
        raise ValueError(f"{len(pk8)} bytes is not a party PK8 (0x158)")
    return holder(SELECT_POKEMON, bytes(8) + pk8)


def time_limit(seconds):
    return holder(TIME_LIMIT, struct.pack("<I", seconds))


def battle_start(stations):
    """The participants' Pia constant ids, the host's first, as u64 in four slots."""
    if not 0 < len(stations) <= STATIONS:
        raise ValueError(f"{len(stations)} stations, a raid holds 1 to {STATIONS}")
    return holder(BATTLE_START, b"".join(struct.pack("<Q", s) for s in stations).ljust(8 * STATIONS, b"\0"))


def boss_pokemon(pk8):
    pk8 = bytes(pk8)
    if len(pk8) != 0x158:
        raise ValueError(f"{len(pk8)} bytes is not a party PK8 (0x158)")
    return holder(BOSS_POKEMON, BOSS_HEAD + pk8)


def rewards(items):
    """(item id, count) pairs, at most 15."""
    if len(items) > REWARD_SLOTS:
        raise ValueError(f"{len(items)} rewards, the record holds {REWARD_SLOTS}")
    return holder(REWARDS, b"".join(struct.pack("<II", i, n) for i, n in items).ljust(8 * REWARD_SLOTS, b"\0"))


def battle_seed(seed):
    return holder(BATTLE_SEED, struct.pack("<Q", seed) + SEED_TAIL)


# The den advertisement (docs/swsh_raid.md, The den record): the boss shown at 0xB0, the den record at
# 0xD4 a guest checks against its encounter table 0xDE, slot 0xE0, of the version 0x5F bit 1 names.
ADVERT_GAME_DATA = 0x18
ADVERT_RECORD_END = 0x180
ADVERT_VERSION, ADVERT_SHOWN, ADVERT_DEN, ADVERT_TABLE, ADVERT_SLOT = 0x5F, 0xB0, 0xD4, 0xDE, 0xE0
ADVERT_KIND, ADVERT_RANK = 0xAF, 0xDC   # kind 0x11 rank 0, 0x13 + 2 (rank - 1) above; rank high nibble
# Advertised levels 15 and 17 sat at rank 0, 58 at rank 4; a 20 under rank 4 was refused.
RANK_FLOORS = (25, 35, 45, 55)


def rank_for_level(level):
    return sum(level >= floor for floor in RANK_FLOORS)
PK8_GIGANTAMAX = 0x16                 # bit 4 (PKHeX PK8.CanGigantamax)
NEST_SLOTS = Path(__file__).with_name("data") / "nest_slots.json"
# An emulated Shield den host's advertisement and 0x84 snapshot, renamed POKELDN and with no account
# ids: what a hosted raid starts from (the host sends its snapshot before the guest's).
DEN_ADVERT = Path(__file__).with_name("data") / "raid_advert.bin"
DEN_SNAPSHOT = Path(__file__).with_name("data") / "raid_snapshot.bin"


NEST_REWARDS = Path(__file__).with_name("data") / "nest_rewards.json"
DYNAMAX_KIND = gen8.OFF_DYNAMAX_TYPE   # 1 normal, 2 Gigantamax: what the guest matches (0x011226b0)


def den_entry(version, species, form, gigantamax):
    """-> the base den slot row [table, slot, species, form, gigantamax, drop id, bonus id] of `version`
    (1 Sword, 2 Shield) holding this Pokemon, or None."""
    slots = json.loads(NEST_SLOTS.read_text())["slots"][str(version)]
    return next((row for row in slots
                 if (row[2], row[3], bool(row[4])) == (species, form, bool(gigantamax))), None)


def den_slot(version, species, form, gigantamax):
    """-> (table, slot) of a den encounter of `version` with this Pokemon, or None."""
    row = den_entry(version, species, form, gigantamax)
    return None if row is None else (row[0], row[1])


def den_of(advert):
    """-> (den slot row, rank) an advertisement names, or (None, rank) for a zero den record."""
    version = 2 if advert[ADVERT_VERSION] & 2 else 1
    rank = advert[ADVERT_RANK] >> 4
    table, slot = struct.unpack_from("<HH", advert, ADVERT_TABLE)
    if advert[ADVERT_DEN:ADVERT_DEN + 8] == bytes(8):
        return None, rank
    slots = json.loads(NEST_SLOTS.read_text())["slots"][str(version)]
    return next((row for row in slots if row[:2] == [table, slot]), None), rank


def den_rewards(row, rank):
    """-> the reward pairs a guest accepts for this den slot at `rank` (0x01032570): each bonus row at
    exactly its count for the rank, and every drop with a chance at the rank, one each."""
    tables = json.loads(NEST_REWARDS.read_text())
    bonus = [(item, values[rank]) for item, *values in tables["bonus"].get(row[6], []) if values[rank]]
    drops = [(item, 1) for item, *values in tables["drop"].get(row[5], []) if values[rank]]
    return bonus + drops


def reward_choices(row, rank):
    """-> {item: count}: what a guest accepts for this den slot at `rank` (0x01032570), a bonus row's
    item at its exact count, a drop's item at None (any count). No item is in both tables of a slot."""
    tables = json.loads(NEST_REWARDS.read_text())
    out = {item: values[rank] for item, *values in tables["bonus"].get(row[6], []) if values[rank]}
    out.update({item: None for item, *values in tables["drop"].get(row[5], []) if values[rank]})
    return out


def fitting_rewards(row, rank, wanted):
    """-> (kept, refused): the wanted pairs a guest accepts for this den slot, and the others."""
    choices = reward_choices(row, rank)
    kept = [(item, n) for item, n in wanted if item in choices and choices[item] in (None, n)]
    return kept, [pair for pair in wanted if pair not in kept]


def boss_den(boss_pk8, rank=None):
    """-> (den slot row, rank) a hosted raid of `boss_pk8` advertises from the shipped den host's
    advertisement, or (None, rank) for a boss no base den holds."""
    return den_of(den_advert(DEN_ADVERT.read_bytes(), boss_pk8, rank))


def _boss_record(old, species, form, gigantamax, ec):
    kind = (old[2] & ~0x30) | (2 if gigantamax else 1) << 4
    return struct.pack("<HB", species | form << 10, kind) + ec + old[7:8]


def den_advert(app_data, boss_pk8, rank=None):
    """The den advertisement showing `boss_pk8`. A boss no den of the host's version holds gets a zero
    den record, which a guest lists without the encounter check and a retail Sword then refuses at
    BossPokemon."""
    out = bytearray(app_data)
    plain = gen8.decrypt(bytes(boss_pk8))
    boss = gen8.read(plain)
    gmax = bool(plain[PK8_GIGANTAMAX] & 0x10)
    ec = bytes(boss_pk8[:4])
    version = 2 if out[ADVERT_VERSION] & 2 else 1
    # A guest searches the version the advertisement names: the other one where only it holds the boss.
    if den_slot(version, boss["species"], boss["form"], gmax) is None and den_slot(
            3 - version, boss["species"], boss["form"], gmax) is not None:
        version = 3 - version
        out[ADVERT_VERSION] = (out[ADVERT_VERSION] & ~2) | (2 if version == 2 else 0)
    rank = rank_for_level(boss["level"]) if rank is None else rank
    out[ADVERT_KIND] = 0x11 if rank == 0 else 0x13 + 2 * (rank - 1)
    out[ADVERT_RANK] = (out[ADVERT_RANK] & 0x0F) | rank << 4
    out[ADVERT_SHOWN:ADVERT_SHOWN + 8] = _boss_record(out[ADVERT_SHOWN:ADVERT_SHOWN + 8], boss["species"],
                                                      boss["form"], gmax, ec)
    found = den_slot(version, boss["species"], boss["form"], gmax)
    if found is None:
        out[ADVERT_DEN:ADVERT_DEN + 8] = bytes(8)
    else:
        out[ADVERT_DEN:ADVERT_DEN + 8] = _boss_record(out[ADVERT_DEN:ADVERT_DEN + 8], boss["species"],
                                                      boss["form"], gmax, ec)
        struct.pack_into("<HH", out, ADVERT_TABLE, *found)
    record = out[ADVERT_GAME_DATA:ADVERT_RECORD_END]
    struct.pack_into("<H", out, ADVERT_GAME_DATA, beacon.crc16(record[2:]))
    return bytes(out)


# What a boss record takes from the Pokemon it shows; everything else comes from a den host's boss
# record (no trainer, version, met data or ball). A retail Sword guest left on a traded record.
BOSS_FIELDS = ("species", "form", "ability", "nature", "gender", "ivs", "evs", "moves", "move_pp",
               "experience", "pid", "encryption_constant", "held_item")
WILD_BOSS = Path(__file__).with_name("data") / "raid_boss_template.ek8"


def same_shine(pid, ids, new_ids):
    """-> `pid` with its high half moved so that under TID ^ SID `new_ids` it keeps the shine it has under
    `ids`: square (xor 0), star (1 to 15) or none. A PID that is not shiny under either stays as it is."""
    xor = ids ^ (pid >> 16) ^ (pid & 0xFFFF)
    if xor >= 16 and (new_ids ^ (pid >> 16) ^ (pid & 0xFFFF)) >= 16:
        return pid
    return (new_ids ^ (pid & 0xFFFF) ^ xor) << 16 | pid & 0xFFFF


SHINY_RANDOM, SHINY_NEVER, SHINY_ALWAYS = 0, 1, 2
OFF_ABILITY_NUMBER = 0x16    # bits 0-2, one bit per ability slot
OFF_HEIGHT, OFF_WEIGHT = 0x50, 0x51
OFF_DYNAMAX_LEVEL = 0x90
OFF_HP_CURRENT = 0x8A


def roll(seed, flawless, abilities, ratio, gender=None, nature=None, natures=None, shiny=SHINY_RANDOM):
    """-> a den boss drawn from `seed` [PKHeX RaidRNG.TryApply]: encryption constant, the trainer id the
    record keeps (`ids`, SID << 16 | TID), PID, IVs in record order, ability slot, gender, nature,
    height and weight. `abilities` lists the slots drawn among, `natures` Toxtricity's form table;
    `gender` and `nature` fix them (docs/swsh_raid.md, A boss a catch keeps legal)."""
    from pokeldn.sv.raid_encounter import Xoroshiro
    rand = Xoroshiro(seed)
    ec, ids, pid = rand.next_int(), rand.next_int(), rand.next_int()
    xor = (ids >> 16) ^ (ids & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)
    if shiny == SHINY_NEVER and xor < 16:
        pid ^= 0x10000000
    elif shiny == SHINY_ALWAYS and xor >= 16:
        pid = ((ids >> 16) ^ (ids & 0xFFFF) ^ (pid & 0xFFFF)) << 16 | pid & 0xFFFF
    ivs = [None] * 6                          # HP Atk Def SpA SpD Spe, the draw's order
    while ivs.count(31) < flawless:
        k = rand.next_int(6)
        if ivs[k] is None:
            ivs[k] = 31
    ivs = [rand.next_int(32) if iv is None else iv for iv in ivs]
    slot = abilities[rand.next_int(len(abilities))] if len(abilities) > 1 else abilities[0]
    if gender is None:
        gender = (2 if ratio == 0xFF else 1 if ratio == 0xFE else 0 if ratio == 0
                  else int(rand.next_int(253) + 1 < ratio))
    if nature is None:
        nature = natures[rand.next_int(len(natures))] if natures else rand.next_int(25)
    height = rand.next_int(129) + rand.next_int(128)
    weight = rand.next_int(129) + rand.next_int(128)
    return {"encryption_constant": ec, "ids": ids, "pid": pid,
            "ivs": (ivs[0], ivs[1], ivs[2], ivs[5], ivs[3], ivs[4]), "slot": slot, "gender": gender,
            "nature": nature, "height": height, "weight": weight}


def boss_record(pk8, template=None, rolled=False):
    """-> the encrypted party record a den host sends as BossPokemon for the Pokemon in `pk8`.
    `rolled`: `pk8` is a den roll (pokeldn.pokemon.Service.raid_boss), whose trainer id, PID, size,
    ability slot and Dynamax level the record keeps, with the party HP a den boss carries."""
    plain = gen8.decrypt(bytes(pk8))
    wild = gen8.decrypt(template if template is not None else WILD_BOSS.read_bytes())
    got = gen8.read(plain)
    fields = {k: got[k] for k in BOSS_FIELDS if k in got}
    fields["encryption_constant"] = struct.unpack_from("<I", plain, 0)[0]
    den = gen8.read(wild)
    if rolled:
        fields.update(trainer_id=got["trainer_id"], secret_id=got["secret_id"])
    else:
        # Shininess is the PID against the record's own TID/SID, and the record keeps the den boss's.
        fields["pid"] = same_shine(got["pid"], got["trainer_id"] ^ got["secret_id"],
                                   den["trainer_id"] ^ den["secret_id"])
    out = bytearray(gen8.write(wild, **fields))
    out[PK8_GIGANTAMAX] = (out[PK8_GIGANTAMAX] & ~0x10) | (plain[PK8_GIGANTAMAX] & 0x10)
    out[DYNAMAX_KIND] = 2 if plain[PK8_GIGANTAMAX] & 0x10 else 1
    if len(plain) == gen8.SIZE_PARTY:
        # The party stats, but not the Dynamax kind (+0x156), which a guest matches with the den slot.
        out[gen8.SIZE_STORED:gen8.OFF_DYNAMAX_TYPE] = plain[gen8.SIZE_STORED:gen8.OFF_DYNAMAX_TYPE]
    if rolled:
        out[OFF_ABILITY_NUMBER] = (out[OFF_ABILITY_NUMBER] & ~0x07) | (plain[OFF_ABILITY_NUMBER] & 0x07)
        for at in (OFF_HEIGHT, OFF_WEIGHT, OFF_DYNAMAX_LEVEL):
            out[at] = plain[at]
        hp = struct.unpack_from("<H", out, gen8.OFF_STATS)[0] * (150 + 5 * plain[OFF_DYNAMAX_LEVEL]) // 100
        struct.pack_into("<H", out, gen8.OFF_STATS, hp)
        struct.pack_into("<H", out, OFF_HP_CURRENT, hp)
    return gen8.encrypt(bytes(out))


def parse(payload):
    """-> (field number, data) for an id-2000 payload, or None."""
    if len(payload) < 4 or struct.unpack_from("<I", payload, 0)[0] != NESTHOLE:
        return None
    b = payload[4:]
    which = b[0] >> 3
    i, n, s = 1, 0, 0
    while True:
        c = b[i]; i += 1
        n |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            break
    inner = b[i:i + n]
    j, m, s = 1, 0, 0
    while True:
        c = inner[j]; j += 1
        m |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            break
    return which, inner[j:j + m]

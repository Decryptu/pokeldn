"""An event Max Raid from a Wild Area Event delivery (docs/swsh_raid.md, Event raids): the den encounter
tables (`normal_encount`, and `normal_encount_rigel1` / `_rigel2` for the Isle of Armor and the Crown
Tundra) and the drop and bonus reward tables (`drop_rewards`, `bonus_rewards`) of one BCAT index, as
Project Pokemon's EventsGallery keeps them; the bosses each version shows at each star rank, the boss
record a den host sends for one, and its Rewards rows.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import struct

from pokeldn import gen8
from pokeldn.sv import raid_encounter as encounter
from pokeldn.swsh import raid

AREAS = (("normal_encount", "Wild Area"), ("normal_encount_rigel1", "Isle of Armor"),
         ("normal_encount_rigel2", "Crown Tundra"))
DROP, BONUS = "drop_rewards", "bonus_rewards"
FILES = (*(name for name, _ in AREAS), DROP, BONUS)
VERSIONS = {1: "Sword", 2: "Shield"}
RANKS = 5
# A delivery file: u8 BCAT index at 0, u32 0x20 at 8, u32 size - 4 at 0x10, the FlatBuffer from 0x20,
# a CRC in the last four bytes [pkNX GameDumperSWSH.GetDistributionContents].
HEADER = 0x20
# Encounter fields in vtable order [pkNX NestHoleDistributionEncounterArchive.fbs], checked against
# Index 010's tables; None names an unread field.
ENTRY = (("entry", "i"), ("species", "i"), ("form", "i"), ("level", "i"), ("dynamax_level", "H"),
         *((None, "I"),) * 6, ("ability", "B"), ("gigantamax", "?"), ("drop_table", "Q"),
         ("bonus_table", "Q"), ("probabilities", None), ("gender", "b"), ("flawless_ivs", "b"),
         ("shiny", "B"), (None, "B"), (None, "B"), ("nature", "b"), (None, "i"),
         ("move0", "I"), ("move1", "I"), ("move2", "I"), ("move3", "I"), ("dynamax_boost", "f"),
         (None, "I"), (None, "I"), ("shield", "I"),
         ("extra1_rate", "I"), ("extra1_move", "I"), ("extra1_value", "I"),
         ("extra2_rate", "I"), ("extra2_move", "I"), ("extra2_value", "I"))
PROBABILITIES = 15
# Ability: 0, 1, 2 the personal entry's first, second, hidden; 3 either of the first two; 4 any.
ABILITY_DRAWS = {0: (0,), 1: (1,), 2: (2,), 3: (0, 1), 4: (0, 1, 2)}
SHINY_RANDOM, SHINY_NEVER, SHINY_ALWAYS = 0, 1, 2
NATURE_RANDOM = 25
GENDER_RANDOM = 0             # 1 male, 2 female, 3 genderless: the record's gender + 1
OFF_ABILITY_NUMBER = 0x16     # bits 0-2, one bit per ability slot (PKHeX G8PKM.AbilityNumber)
OFF_HP_CURRENT = 0x8A
OFF_DYNAMAX_LEVEL = 0x90
DATA = Path(__file__).with_name("data")


def _species():
    with open(DATA / "species.json", encoding="utf-8") as fh:
        return json.load(fh)


def _nest_rewards():
    with open(DATA / "nest_rewards.json", encoding="utf-8") as fh:
        return json.load(fh)


_CACHE = {}


def tables():
    """-> species.json and nest_rewards.json, read once."""
    if not _CACHE:
        _CACHE.update(_species(), nest=_nest_rewards())
    return _CACHE


@dataclass(frozen=True)
class Boss:
    area: str
    version: int                  # 1 Sword, 2 Shield
    entry: int                    # the table's EntryIndex
    species: int
    form: int
    level: int
    dynamax_level: int
    gigantamax: bool
    ability: int                  # ABILITY_DRAWS
    gender: int
    flawless_ivs: int
    shiny: int
    nature: int
    moves: tuple
    probabilities: tuple          # per rank 0 to 4, percent
    drop_table: int
    bonus_table: int
    dynamax_boost: float
    shield: int
    extra_moves: tuple            # ((rate, move, value), (rate, move, value)) as the table holds them

    @property
    def ranks(self):
        return tuple(r for r, p in enumerate(self.probabilities) if p)

    @property
    def name(self):
        name = tables()["species_names"].get(str(self.species), f"#{self.species}")
        return ("Gigantamax " if self.gigantamax else "") + name + (f"-{self.form}" if self.form else "")

    def same(self, other):
        """Whether two rows make the same boss, whatever their entry and chance."""
        skip = {"entry", "probabilities"}
        return all(getattr(self, k) == getattr(other, k) for k in self.__dataclass_fields__ if k not in skip)


@dataclass(frozen=True)
class Event:
    index: int                    # the BCAT index the files carry
    bosses: tuple
    drops: dict                   # table id -> ((item, value at ranks 0 to 4), ...)
    bonuses: dict

    def choices(self, version, rank, area=AREAS[0][1]):
        """-> the distinct bosses `version` shows at `rank` (0 to 4) in `area`, table order, each
        with its chance summed over its rows."""
        out = []
        for boss in self.bosses:
            if boss.area != area or boss.version != version or not boss.probabilities[rank]:
                continue
            for k, seen in enumerate(out):
                if seen.same(boss):
                    chance = list(seen.probabilities)
                    chance[rank] += boss.probabilities[rank]
                    out[k] = _with(seen, probabilities=tuple(chance))
                    break
            else:
                out.append(boss)
        return out

    def areas(self):
        return list(dict.fromkeys(b.area for b in self.bosses))


def _with(boss, **fields):
    return Boss(**{**{k: getattr(boss, k) for k in boss.__dataclass_fields__}, **fields})


def contents(raw):
    """-> (BCAT index, FlatBuffer) of a delivery file; ValueError for one without the header."""
    raw = bytes(raw)
    if len(raw) < HEADER + 4 or struct.unpack_from("<I", raw, 8)[0] != HEADER \
            or struct.unpack_from("<I", raw, 0x10)[0] != len(raw) - 4:
        raise ValueError("not a Wild Area Event delivery file")
    return raw[0], raw[HEADER:-4]


def _fields(buf, pos):
    vtable = pos - struct.unpack_from("<i", buf, pos)[0]
    length = struct.unpack_from("<H", buf, vtable)[0]
    return [struct.unpack_from("<H", buf, vtable + 4 + 2 * i)[0] for i in range((length - 4) // 2)]


def _vector(buf, at):
    target = at + struct.unpack_from("<I", buf, at)[0]
    return target + 4, struct.unpack_from("<I", buf, target)[0]


def _tables(buf, pos, field):
    start, count = _vector(buf, pos + _fields(buf, pos)[field])
    return [start + 4 * i + struct.unpack_from("<I", buf, start + 4 * i)[0] for i in range(count)]


def read_encounters(raw, area=AREAS[0][1]):
    """-> (BCAT index, [Boss]) of an encounter file, every row with a non-zero chance."""
    index, buf = contents(raw)
    out = []
    for table in _tables(buf, struct.unpack_from("<I", buf, 0)[0], 0):
        offsets = _fields(buf, table)        # TableID, GameVersion, two bytes, Entries
        version = struct.unpack_from("<I", buf, table + offsets[1])[0] if offsets[1] else 0
        for row in _tables(buf, table, 4):
            at = _fields(buf, row)
            got = {}
            for k, (name, kind) in enumerate(ENTRY):
                offset = at[k] if k < len(at) else 0
                if name == "probabilities":
                    start, count = _vector(buf, row + offset)
                    got[name] = struct.unpack_from(f"<{count}i", buf, start)
                elif name:
                    got[name] = struct.unpack_from("<" + kind, buf, row + offset)[0] if offset else 0
            if not any(got["probabilities"]):
                continue
            out.append(Boss(
                area, version, got["entry"], got["species"], got["form"], got["level"],
                got["dynamax_level"], bool(got["gigantamax"]), got["ability"], got["gender"],
                got["flawless_ivs"], got["shiny"], got["nature"],
                tuple(got[f"move{i}"] for i in range(4)), tuple(got["probabilities"]),
                got["drop_table"], got["bonus_table"], round(got["dynamax_boost"], 3), got["shield"],
                tuple((got[f"extra{i}_rate"], got[f"extra{i}_move"], got[f"extra{i}_value"]) for i in (1, 2))))
    return index, out


def read_rewards(raw):
    """-> (BCAT index, {table id: ((item, value at ranks 0 to 4), ...)}) of a drop or bonus file
    [pkNX NestHoleDistributionRewardArchive.fbs]: an entry is five u8 values and a u16 item."""
    index, buf = contents(raw)
    out = {}
    for table in _tables(buf, struct.unpack_from("<I", buf, 0)[0], 0):
        identifier = struct.unpack_from("<Q", buf, table + _fields(buf, table)[0])[0]
        rows = []
        for row in _tables(buf, table, 1):
            at = _fields(buf, row) + [0] * 6
            values = tuple(buf[row + o] if o else 0 for o in at[:5])
            item = struct.unpack_from("<H", buf, row + at[5])[0] if at[5] else 0
            rows.append((item, values))
        out[identifier] = tuple(rows)
    return index, out


def load(folder):
    """-> the Event a delivery folder holds; ValueError for files that do not read."""
    def raw(name):
        with open(os.path.join(folder, name), "rb") as fh:
            return fh.read()

    try:
        index, bosses = None, []
        for name, area in AREAS:
            if os.path.isfile(os.path.join(folder, name)):
                found, rows = read_encounters(raw(name), area)
                index = found if index is None else index
                bosses += rows
        if index is None:
            raise FileNotFoundError(f"no {AREAS[0][0]} in {folder}")
        drops = read_rewards(raw(DROP))[1] if os.path.isfile(os.path.join(folder, DROP)) else {}
        bonuses = read_rewards(raw(BONUS))[1] if os.path.isfile(os.path.join(folder, BONUS)) else {}
        return Event(index, tuple(bosses), drops, bonuses)
    except (struct.error, IndexError) as error:
        raise ValueError(f"{folder} holds no readable Wild Area Event ({error})") from error


def deliveries(base):
    """-> every folder under `base` holding an encounter file, in name order."""
    for folder, dirs, files in os.walk(base):
        dirs.sort()
        if AREAS[0][0] in files:
            yield folder


def _reward_table(event, kind, identifier):
    """-> the rows of a reward table: the game's own first, as the game looks it up [pkNX
    NestHoleDistributionEncounterTable.GetPrettySummary], then the delivery's; None for neither."""
    base = tables()["nest"][kind].get(str(identifier))
    if base is not None:
        return tuple((row[0], tuple(row[1:6])) for row in base)
    return (event.drops if kind == "drop" else event.bonuses).get(identifier)


def rewards(event, boss, rank, rand=None):
    """-> the Rewards rows (item, count) of a boss at `rank`: its bonus table's items at their count,
    then each drop with a non-zero chance, one each. `rand` (a random.Random) rolls each drop's
    percent as the game does; None keeps every drop. An emulated den host's Rewards held the bonus
    rows, then its won drops (raid.DEN_REWARDS). At most raid.REWARD_SLOTS rows."""
    out = []
    for item, values in _reward_table(event, "bonus", boss.bonus_table) or ():
        if values[rank] and item:
            out.append((item, values[rank]))
    for item, values in _reward_table(event, "drop", boss.drop_table) or ():
        if values[rank] and item and (rand is None or rand.randrange(100) < values[rank]):
            out.append((item, 1))
    return out[:raid.REWARD_SLOTS]


def missing_rewards(event, boss):
    """-> the reward kinds whose table neither the game nor the delivery holds."""
    return [kind for kind, identifier in (("bonus", boss.bonus_table), ("drop", boss.drop_table))
            if _reward_table(event, kind, identifier) is None]


def personal(species, form):
    """-> (base stats HP Atk Def Spe SpA SpD, gender ratio, growth, abilities)."""
    e = tables()["personal"].get(f"{species}/{form}")
    if e is None:
        raise ValueError(f"species {species} form {form} is not in Sword/Shield")
    return tuple(e[:6]), e[6], e[7], tuple(e[8:11])


def party_stats(base, ivs, level, nature, dynamax_level):
    """-> a den boss's six party stats: HP Atk Def Spe SpA SpD, HP raised by its Dynamax level,
    HP * (150 + 5 * level) / 100 (both recorded den bosses: Pidove level 15, Torkoal level 58)."""
    out = list(encounter.stats(base, ivs, level, nature))
    out[0] = out[0] * (150 + 5 * dynamax_level) // 100
    return tuple(out)


def boss_pk8(boss, rand=None, template=None):
    """-> the encrypted party record a den host sends as BossPokemon for `boss`, on the den boss
    record raid.boss_record starts from: species, form, level, experience, moves and their PP, the
    ability the table allows, the table's flawless IVs, nature, gender and shiny rule, Gigantamax and
    Dynamax level, party stats. What the table leaves open is drawn from `rand` (a random.Random)."""
    rand = rand or random.SystemRandom()
    base, ratio, growth, abilities = personal(boss.species, boss.form)
    plain = bytearray(gen8.decrypt(template if template is not None else raid.WILD_BOSS.read_bytes()))
    old = gen8.read(bytes(plain))
    slot = rand.choice(ABILITY_DRAWS[boss.ability])
    ivs = [None] * 6
    for k in rand.sample(range(6), min(max(boss.flawless_ivs, 0), 6)):
        ivs[k] = 31
    ivs = tuple(rand.randrange(32) if iv is None else iv for iv in ivs)
    if boss.nature != NATURE_RANDOM:
        nature = boss.nature
    elif boss.species == encounter.TOXTRICITY:
        nature = rand.choice(encounter.TOXTRICITY_NATURES[boss.form])
    else:
        nature = rand.randrange(25)
    if boss.gender != GENDER_RANDOM:
        gender = boss.gender - 1
    else:
        gender = (2 if ratio == 0xFF else 1 if ratio == 0xFE else 0 if ratio == 0
                  else int(rand.randrange(100) < encounter.GENDER_CUTOFF.get(ratio, ratio * 100 // 253)))
    pid = rand.getrandbits(32)
    xor = old["trainer_id"] ^ old["secret_id"] ^ (pid >> 16) ^ (pid & 0xFFFF)
    if boss.shiny == SHINY_NEVER and xor < 16:
        pid ^= 0x10000000
    elif boss.shiny == SHINY_ALWAYS and xor >= 16:
        pid = ((old["trainer_id"] ^ old["secret_id"] ^ (pid & 0xFFFF)) << 16) | (pid & 0xFFFF)
    stats = party_stats(base, ivs, boss.level, nature, boss.dynamax_level)
    pp = tables()["move_pp"]
    out = bytearray(gen8.write(
        bytes(plain), species=boss.species, form=boss.form, level=boss.level,
        experience=encounter.experience(boss.level, growth), moves=boss.moves,
        move_pp=tuple(pp.get(str(m), 0) if m else 0 for m in boss.moves), move_pp_ups=(0,) * 4,
        ability=abilities[slot], ivs=ivs, evs=(0,) * 6, nature=nature, gender=gender, pid=pid,
        encryption_constant=rand.getrandbits(32), held_item=0, stats=stats))
    out[OFF_ABILITY_NUMBER] = (out[OFF_ABILITY_NUMBER] & ~0x07) | 1 << slot
    out[raid.PK8_GIGANTAMAX] = (out[raid.PK8_GIGANTAMAX] & ~0x10) | (0x10 if boss.gigantamax else 0)
    out[raid.DYNAMAX_KIND] = 2 if boss.gigantamax else 1
    out[OFF_DYNAMAX_LEVEL] = boss.dynamax_level
    struct.pack_into("<H", out, OFF_HP_CURRENT, stats[0])
    return gen8.encrypt(bytes(out))


def describe(boss, rank):
    """-> one line: the boss, its level and chance at `rank`, and what the table fixes."""
    parts = [f"{boss.name} Lv {boss.level}", f"{boss.probabilities[rank]}%",
             f"{boss.flawless_ivs} perfect IVs"]
    if boss.shiny == SHINY_ALWAYS:
        parts.append("always shiny")
    elif boss.shiny == SHINY_NEVER:
        parts.append("never shiny")
    return ", ".join(parts)


def hostable(event):
    """-> (version name, stars, number, area, boss) for every boss of `event` a hosted raid can show:
    one a base den of either version holds as the same species, form and Gigantamax state (a guest
    refuses any other, docs/swsh_raid.md, The boss record). `number` counts as --raid-event-boss does."""
    out = []
    for area in event.areas():
        for version in VERSIONS:
            for rank in range(RANKS):
                for number, boss in enumerate(event.choices(version, rank, area), 1):
                    if any(raid.den_slot(v, boss.species, boss.form, boss.gigantamax) for v in VERSIONS):
                        out.append((VERSIONS[version].lower(), rank + 1, number, area, boss))
    return out

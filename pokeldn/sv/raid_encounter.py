"""A standard or black-crystal Tera Raid from its 32-bit seed: the encounter that a game version, a
region, the story progress and the crystal colour select, the boss's PK9 fields, and the ordered
rewards (docs/sv_raid.md, The seed). The RNG is PKHeX's `Encounter9RNG` and `Tera9RNG`; the tables
are `data/raid_base.json` (scripts/gen_sv_raid_data.py) over `data/species.json`
(scripts/gen_sv_species_data.py). An event raid's encounter (`pokeldn.sv.raid_event`) goes through
the same boss and reward draws, with the fields its table fixes.
"""

from dataclasses import dataclass
from functools import cache
import json
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raid_base.json")
SPECIES = os.path.join(os.path.dirname(DATA), "species.json")
MASK64 = (1 << 64) - 1

VERSIONS = ("scarlet", "violet")
MAPS = ("paldea", "kitakami", "blueberry")
PROGRESS = ("beginning", "tera", "3star", "4star", "5star", "6star")
CONTENTS = ("standard", "black")

# The first draw, a hundred-sided roll, against inclusive upper bounds per story stage.
STAR_LOTTERY = {
    "beginning": ((80, 1), (100, 2)),
    "tera": ((80, 1), (100, 2)),
    "3star": ((30, 1), (70, 2), (100, 3)),
    "4star": ((20, 1), (40, 2), (70, 3), (100, 4)),
    "5star": ((40, 3), (75, 4), (100, 5)),
    "6star": ((30, 3), (70, 4), (100, 5)),
}
# The second draw's range per region and version, stars 1 to 6 [EncounterTera9.cs GetRateTotal*].
RATE_TOTALS = {
    ("paldea", "scarlet"): (5800, 5300, 7400, 8800, 9100, 6500),
    ("paldea", "violet"): (5800, 5300, 7400, 8700, 9100, 6500),
    ("kitakami", "scarlet"): (1500, 1500, 2500, 2100, 2250, 2475),
    ("kitakami", "violet"): (1500, 1500, 2500, 2100, 2250, 2574),
    ("blueberry", "scarlet"): (1100, 1100, 2000, 1900, 2100, 2600),
    ("blueberry", "violet"): (1100, 1100, 2000, 1900, 2100, 2600),
}
# Lottery reward counts per star level, by the seed's hundred-sided roll [Tera-Finder RewardUtil.cs];
# a seven-star event raid draws as a six-star one.
REWARD_SLOTS = ((4, 5, 6, 7, 8), (4, 5, 6, 7, 8), (5, 6, 7, 8, 9), (5, 6, 7, 8, 9),
                (6, 7, 8, 9, 10), (7, 8, 9, 10, 11), (7, 8, 9, 10, 11))
REWARD_COLUMNS = (10, 40, 70, 90)
# The Tera Shard item per Tera type, in type order.
TERA_SHARDS = (1862, 1868, 1871, 1869, 1870, 1874, 1873, 1875, 1878,
               1863, 1864, 1866, 1865, 1872, 1867, 1876, 1877, 1879)
REWARD_MATERIAL, REWARD_SHARD = 1, 2
TOXTRICITY = 849
# Toxtricity's nature comes from its form's list [ToxtricityUtil.cs].
TOXTRICITY_NATURES = ((3, 4, 2, 8, 9, 19, 22, 11, 13, 14, 0, 6, 24),
                      (1, 5, 7, 10, 12, 15, 16, 17, 18, 20, 21, 23))
GENDER_CUTOFF = {0x1F: 12, 0x3F: 25, 0x7F: 50, 0xBF: 75, 0xE1: 89}
TERA_NONE = 19          # a PK9's Tera override when none applies
TERA_TYPES = ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost", "Steel",
              "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon", "Dark", "Fairy")
NATURES = ("Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish",
           "Lax", "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful",
           "Rash", "Calm", "Gentle", "Sassy", "Careful", "Quirky")
# A raid table's shiny rule (RareType): drawn, never, always.
SHINY_RANDOM, SHINY_NEVER, SHINY_ALWAYS = 0, 1, 2
# A raid table's scale rule (SizeType): 0 two draws as height and weight, 1 to 5 one draw in a band
# (range, base), 6 the table's own value [PKHeX SizeType9.GetSizeValue].
SCALE_BANDS = {1: (0x10, 0), 2: (0x20, 0x10), 3: (0xA0, 0x30), 4: (0x20, 0xD0), 5: (0x10, 0xF0)}
SCALE_RANDOM, SCALE_VALUE = 0, 6


class Xoroshiro:
    """xoroshiro128+ seeded with a 32-bit value and the game's fixed second word."""

    def __init__(self, seed):
        self.s0, self.s1 = seed & MASK64, 0x82A2B175229D6A5B

    def next(self):
        s0, s1 = self.s0, self.s1
        result = (s0 + s1) & MASK64
        s1 ^= s0
        self.s0 = (((s0 << 24) | (s0 >> 40)) ^ s1 ^ (s1 << 16)) & MASK64
        self.s1 = ((s1 << 37) | (s1 >> 27)) & MASK64
        return result

    def next_int(self, maximum=0xFFFFFFFF):
        """-> a value under `maximum`, rejecting draws above the next power of two."""
        mask = (1 << (maximum - 1).bit_length()) - 1
        while True:
            value = self.next() & mask
            if value < maximum:
                return value


@cache
def tables():
    """-> raid_base.json with species.json's personal entries, move PP and names, every species' and
    move's."""
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(SPECIES, encoding="utf-8") as fh:
        every = json.load(fh)
    return {**data, **{key: every[key] for key in ("personal", "move_pp", "species_names")}}


def personal(species, form=0):
    """-> (base stats HP Atk Def Spe SpA SpD, types, gender ratio, friendship, growth, abilities)."""
    e = tables()["personal"][f"{species}/{form}"]
    return tuple(e[:6]), tuple(e[6:8]), e[8], e[9], e[10], tuple(e[11:14])


def experience(level, growth):
    """-> the least experience at `level` for one of the six growth curves."""
    n = level
    if growth == 0:
        return n ** 3
    if growth == 1:
        if n <= 50:
            return n ** 3 * (100 - n) // 50
        if n <= 68:
            return n ** 3 * (150 - n) // 100
        if n <= 98:
            return n ** 3 * ((1911 - 10 * n) // 3) // 500
        return n ** 3 * (160 - n) // 100
    if growth == 2:
        if n <= 15:
            return n ** 3 * ((n + 1) // 3 + 24) // 50
        if n <= 36:
            return n ** 3 * (n + 14) // 50
        return n ** 3 * (n // 2 + 32) // 50
    if growth == 3:
        return max(0, 6 * n ** 3 // 5 - 15 * n ** 2 + 100 * n - 140)
    if growth == 4:
        return 4 * n ** 3 // 5
    return 5 * n ** 3 // 4


def stats(base, ivs, level, nature, evs=(0,) * 6):
    """-> the six party stats, HP Atk Def Spe SpA SpD."""
    out = [(2 * b + iv + ev // 4) * level // 100 + 5 for b, iv, ev in zip(base, ivs, evs)]
    out[0] += level + 5
    # The nature's order is Atk Def Spe SpA SpD, the stats' after HP.
    up, down = nature // 5 + 1, nature % 5 + 1
    if up != down:
        out[up] = out[up] * 110 // 100
        out[down] = out[down] * 90 // 100
    return tuple(out)


def select(seed, version, map_name, progress, content):
    """-> (encounter row, stars) the seed draws from that region's table."""
    if version not in VERSIONS or map_name not in MAPS or progress not in PROGRESS \
            or content not in CONTENTS:
        raise ValueError(f"no raid table for {version}/{map_name}/{progress}/{content}")
    rand = Xoroshiro(seed)
    stars = 6
    if content == "standard":
        roll = rand.next_int(100)
        stars = next(s for ceiling, s in STAR_LOTTERY[progress] if roll <= ceiling)
    choice = rand.next_int(RATE_TOTALS[(map_name, version)][stars - 1])
    for row in tables()["encounters"][f"{map_name}_{content}"]:
        low = row["rate_min"][version]
        if row["stars"] == stars and 0 <= low <= choice < low + row["rate"]:
            return row, stars
    raise ValueError(f"no {stars}-star encounter for seed {seed:08X}")


def tera_type(seed, row):
    """-> the boss's Tera type: the table's own, or any of 18."""
    # Table values 0 and 1 both draw any of 18 (0xe27414); docs/sv_raid.md, The seed.
    if row["tera"] >= 2:
        return row["tera"] - 2
    return Xoroshiro(seed).next_int(18)


def battle_pid(pid, fake_id, shiny):
    """-> the PID the boss fights with under its table's shiny rule against the fake trainer: a
    shiny draw turned away, or the draw made the square sparkle; a drawn rule keeps the draw
    [Encounter9RNG.GetAdaptedPID, its battle half]."""
    tid, sid, low = fake_id & 0xFFFF, fake_id >> 16, pid & 0xFFFF
    sparkles = (tid ^ sid ^ (pid >> 16) ^ low) < 16
    if shiny == SHINY_NEVER and sparkles:
        return pid ^ 0x10000000
    if shiny == SHINY_ALWAYS and not sparkles:
        return ((tid ^ sid ^ low) << 16) | low
    return pid


def boss_fields(seed, row):
    """-> the boss's `pokeldn.gen9.write` fields; every field not named stays zero. What an event
    row fixes takes no draw: `ivs` (HP Atk Def SpA SpD Spe), `gender`, `nature`, a `scale_type` of
    a band or a value; its `shiny` rule adjusts the PID and its `held_item` is the boss's."""
    base, _types, ratio, friendship, growth, abilities = personal(row["species"], row["form"])
    rand = Xoroshiro(seed)
    ec, fake_id = rand.next_int(), rand.next_int()
    pid = battle_pid(rand.next_int(), fake_id, row.get("shiny", SHINY_RANDOM))
    ivs = list(row.get("ivs") or [None] * 6)          # HP Atk Def SpA SpD Spe, the draw's order
    for _ in range(row["flawless_ivs"]):
        index = rand.next_int(6)
        while ivs[index] is not None:
            index = rand.next_int(6)
        ivs[index] = 31
    ivs = [rand.next_int(32) if iv is None else iv for iv in ivs]
    ability = {0: lambda: rand.next_int(2), 1: lambda: rand.next_int(3),
               2: lambda: 0, 3: lambda: 1, 4: lambda: 2}[row["ability"]]()
    if row.get("gender") is not None:
        gender = row["gender"]
    else:
        gender = (2 if ratio == 0xFF else 1 if ratio == 0xFE else 0 if ratio == 0
                  else int(rand.next_int(100) < GENDER_CUTOFF[ratio]))
    if row.get("nature") is not None:
        nature = row["nature"]
    elif row["species"] == TOXTRICITY:
        table = TOXTRICITY_NATURES[row["form"]]
        nature = table[rand.next_int(len(table))]
    else:
        nature = rand.next_int(25)
    height = rand.next_int(0x81) + rand.next_int(0x80)
    weight = rand.next_int(0x81) + rand.next_int(0x80)
    scale_type = row.get("scale_type", SCALE_RANDOM)
    if scale_type == SCALE_VALUE:
        scale = row["scale"]
    elif scale_type == SCALE_RANDOM:
        scale = rand.next_int(0x81) + rand.next_int(0x80)
    else:
        span, low = SCALE_BANDS[scale_type]
        scale = rand.next_int(span) + low
    ivs = (ivs[0], ivs[1], ivs[2], ivs[5], ivs[3], ivs[4])
    party = stats(base, ivs, row["level"], nature, row["evs"])
    return {
        "species": row["species"], "form": row["form"], "level": row["level"],
        "met_level": row["level"], "experience": experience(row["level"], growth),
        "encryption_constant": ec, "trainer_id": fake_id & 0xFFFF, "secret_id": fake_id >> 16,
        "pid": pid, "ability": abilities[ability], "ability_number": 1 << ability,
        "gender": gender, "nature": nature, "stat_nature": nature, "ivs": ivs,
        "evs": tuple(row["evs"]),
        "height_scalar": height, "weight_scalar": weight, "scale": scale,
        "tera_type_original": tera_type(seed, row), "tera_type_override": TERA_NONE,
        "moves": tuple(row["moves"]),
        "move_pp": tuple(tables()["move_pp"][str(move)] for move in row["moves"]),
        "current_hp": party[0], "stats": party, "ot_friendship": friendship,
        "nickname": tables()["species_names"][str(row["species"])],
        "language": 2, "affixed_ribbon": -1, "held_item": row.get("held_item", 0),
    }


def rewards(seed, row, stars, fixed=None, lottery=None):
    """-> [(item, quantity)]: the encounter's fixed rows, then the seed's lottery draws. `fixed`
    and `lottery` are the reward tables by name, the base game's unless an event brings its own."""
    data = tables()
    gem = tera_type(seed, row)
    out = []

    def add(entry):
        item = entry["item"] or {
            REWARD_MATERIAL: int(data["material_items"].get(str(row["species"]), 0)),
            REWARD_SHARD: TERA_SHARDS[gem]}.get(entry["category"], 0)
        if item and entry["amount"]:
            out.append((item, entry["amount"]))

    fixed = data["fixed_rewards"] if fixed is None else fixed
    lottery = data["lottery_rewards"] if lottery is None else lottery
    # An event's record can name a table its delivery lacks; a lottery without weight draws nothing
    # (a draw under a total of 0 never ends).
    for entry in fixed.get(row["fixed_rewards"], ()):
        add(entry)
    draws = lottery.get(row["lottery_rewards"], ())
    total = sum(entry["probability"] for entry in draws)
    if not total:
        return out
    rand = Xoroshiro(seed)
    roll = rand.next_int(100)
    count = REWARD_SLOTS[stars - 1][sum(roll >= edge for edge in REWARD_COLUMNS)]
    for _ in range(count):
        threshold = rand.next_int(total)
        for entry in draws:
            if entry["probability"] > threshold:
                add(entry)
                break
            threshold -= entry["probability"]
    return out


@dataclass(frozen=True)
class Raid:
    seed: int
    version: str
    map_name: str
    progress: str
    content: str
    stars: int
    row: dict
    boss: dict
    rewards: tuple

    @property
    def species(self):
        return self.boss["species"]

    @property
    def tera_type(self):
        return self.boss["tera_type_original"]

    @property
    def is_shiny(self):
        b = self.boss
        return (b["trainer_id"] ^ b["secret_id"] ^ (b["pid"] >> 16) ^ (b["pid"] & 0xFFFF)) < 16

    @property
    def context(self):
        return {"version": self.version, "map_name": self.map_name, "progress": self.progress,
                "content": self.content}


def generate(seed, version="violet", map_name="paldea", progress="4star", content="standard"):
    """-> the Raid a console in that state makes of the seed."""
    seed &= 0xFFFFFFFF
    row, stars = select(seed, version, map_name, progress, content)
    return Raid(seed, version, map_name, progress, content, stars, row, boss_fields(seed, row),
                tuple(rewards(seed, row, stars)))

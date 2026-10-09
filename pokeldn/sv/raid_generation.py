"""Seed-driven Scarlet/Violet Tera Raid profile generation.

This module intentionally has no radio or replay dependency.  A caller supplies the raid encounter
pool appropriate to its game, map, and story progress; :func:`generate_raid` selects the encounter
and produces the boss PK9 fields and compact lobby metadata before a host sends anything.

The encounter context is JSON so game-table extraction can evolve independently from the LDN host.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


MASK64 = (1 << 64) - 1
XOROSHIRO_CONST = 0x82A2B175229D6A5B


class Xoroshiro128Plus:
    """The xoroshiro128+ variant used by Gen 9 raids."""

    def __init__(self, seed: int):
        self.s0 = seed & 0xFFFFFFFF
        self.s1 = XOROSHIRO_CONST

    @staticmethod
    def _rotl(value: int, shift: int) -> int:
        return ((value << shift) | (value >> (64 - shift))) & MASK64

    def next(self) -> int:
        s0, s1 = self.s0, self.s1
        result = (s0 + s1) & MASK64
        s1 ^= s0
        self.s0 = (self._rotl(s0, 24) ^ s1 ^ ((s1 << 16) & MASK64)) & MASK64
        self.s1 = self._rotl(s1, 37)
        return result

    def next_int(self, maximum: int = 0xFFFFFFFF) -> int:
        if maximum <= 0:
            raise ValueError("xoroshiro maximum must be positive")
        mask = (1 << ((maximum - 1).bit_length())) - 1
        while True:
            value = self.next() & mask
            if value < maximum:
                return value


def _stars(rand: Xoroshiro128Plus, progress: str) -> int:
    roll = rand.next_int(100)
    thresholds = {
        "beginning": ((80, 1), (100, 2)),
        "tera": ((80, 1), (100, 2)),
        "3star": ((30, 1), (70, 2), (100, 3)),
        "4star": ((20, 1), (40, 2), (70, 3), (100, 4)),
        "5star": ((40, 3), (75, 4), (100, 5)),
        "6star": ((30, 3), (70, 4), (100, 5)),
    }
    try:
        for ceiling, stars in thresholds[progress]:
            if roll <= ceiling:
                return stars
    except KeyError as exc:
        raise ValueError(f"unknown game progress {progress!r}") from exc
    raise AssertionError("unreachable raid star roll")


def _gender(ratio: int, rand: Xoroshiro128Plus) -> int:
    # PK9 gender: 0 male, 1 female, 2 genderless.
    if ratio == 0xFF:
        return 2
    if ratio == 0xFE:
        return 1
    if ratio == 0x00:
        return 0
    roll = rand.next_int(100)
    cutoffs = {0x1F: 12, 0x3F: 25, 0x7F: 50, 0xBF: 75, 0xE1: 89}
    try:
        return 1 if roll < cutoffs[ratio] else 0
    except KeyError as exc:
        raise ValueError(f"unsupported gender ratio {ratio:#x}") from exc


def _tera_type(seed: int, encounter: dict) -> int:
    gem = encounter.get("tera", "random")
    if isinstance(gem, int):
        return gem
    if gem == "random":
        return Xoroshiro128Plus(seed).next_int(18)
    if gem == "default":
        types = encounter["personal"]["types"]
        return types[Xoroshiro128Plus(seed).next_int(2)]
    raise ValueError(f"unknown Tera specification {gem!r}")


def _experience(level: int, growth: int) -> int:
    # Growth IDs are the Gen 9 personal-table values. Values are the minimum EXP for `level`.
    n = level
    if growth == 0:  # medium-fast
        return n ** 3
    if growth == 1:  # erratic
        return (n ** 3 * (100 - n) // 50 if n <= 50 else
                n ** 3 * (150 - n) // 100 if n <= 68 else
                n ** 3 * ((1911 - 10 * n) // 3) // 500 if n <= 98 else n ** 3 * (160 - n) // 100)
    if growth == 2:  # fluctuating
        return (n ** 3 * ((n + 1) // 3 + 24) // 50 if n <= 15 else
                n ** 3 * (n + 14) // 50 if n <= 36 else n ** 3 * (n // 2 + 32) // 50)
    if growth == 3:  # medium-slow
        return max(0, (6 * n ** 3) // 5 - 15 * n ** 2 + 100 * n - 140)
    if growth == 4:  # fast
        return 4 * n ** 3 // 5
    if growth == 5:  # slow
        return 5 * n ** 3 // 4
    raise ValueError(f"unknown experience growth {growth}")


def _stats(personal: dict, ivs: tuple[int, ...], level: int, nature: int) -> tuple[int, ...]:
    base = personal["base_stats"]  # HP, Atk, Def, Spe, SpA, SpD
    values = [((2 * stat + iv) * level) // 100 + 5 for stat, iv in zip(base, ivs)]
    values[0] += level + 5
    up, down = nature // 5, nature % 5
    # Nature order is Atk, Def, Spe, SpA, SpD; stored stats include HP at index zero.
    if up != down:
        values[up + 1] = values[up + 1] * 110 // 100
        values[down + 1] = values[down + 1] * 90 // 100
    return tuple(values)


def _move_pp(encounter: dict) -> tuple[int, ...]:
    pp = encounter.get("move_pp")
    if pp is None:
        raise ValueError("encounter is missing move_pp; PK9 profile generation requires exact base PP")
    if len(pp) != 4:
        raise ValueError("move_pp must contain four values")
    return tuple(pp)


def _select_encounter(seed: int, context: dict) -> tuple[dict, int]:
    rand = Xoroshiro128Plus(seed)
    stars = 6 if context.get("content") == "black" else _stars(rand, context["progress"])
    version = context.get("version", "violet")
    totals = context["rate_totals"]
    try:
        total = totals[str(stars)][version]
    except KeyError as exc:
        raise ValueError(f"context has no {version} rate total for {stars}-star raids") from exc
    choice = rand.next_int(total)
    for encounter in context["encounters"]:
        if encounter["stars"] != stars:
            continue
        minimum = encounter["rate_min"].get(version, -1)
        if minimum >= 0 and minimum <= choice < minimum + encounter["rate"]:
            return encounter, stars
    raise ValueError(f"no encounter selected for seed {seed:08X}, stars {stars}, choice {choice}")


def generate_raid(seed: int, context: dict) -> dict:
    """Generate a complete PK9-ready normal raid profile for an arbitrary 32-bit seed.

    ``context`` holds the game/version-specific encounter pool. It is deliberately explicit: a
    seed alone does not identify an encounter without map, game version, and story-progress tables.
    """
    seed &= 0xFFFFFFFF
    encounter, stars = _select_encounter(seed, context)
    personal = encounter["personal"]
    rand = Xoroshiro128Plus(seed)
    ec = rand.next_int()
    fake_id = rand.next_int()
    pid = rand.next_int()
    # Standard raids are non-shiny unless the encounter requests a special distribution behavior.
    if encounter.get("shiny", "random") == "never":
        if ((pid >> 16) ^ (pid & 0xFFFF) ^ (fake_id >> 16) ^ (fake_id & 0xFFFF)) < 16:
            pid ^= 0x10000000

    ivs = [-1] * 6  # HP, Atk, Def, SpA, SpD, Spe: game RNG order.
    fixed_ivs = encounter.get("ivs")
    if fixed_ivs is not None:
        ivs = list(fixed_ivs)
    else:
        for _ in range(encounter["flawless_ivs"]):
            while True:
                index = rand.next_int(6)
                if ivs[index] < 0:
                    ivs[index] = 31
                    break
        for index, value in enumerate(ivs):
            if value < 0:
                ivs[index] = rand.next_int(32)

    ability_mode = encounter.get("ability", "any12")
    if ability_mode == "any12":
        ability_index = rand.next_int(2)
    elif ability_mode == "any12h":
        ability_index = rand.next_int(3)
    elif ability_mode.startswith("fixed"):
        ability_index = int(ability_mode[-1])
    else:
        raise ValueError(f"unknown ability mode {ability_mode!r}")
    ability = personal["abilities"][ability_index]
    gender_mode = encounter.get("gender", "random")
    gender = (_gender(personal["gender_ratio"], rand)
              if gender_mode == "random" else int(gender_mode))
    nature = encounter.get("nature")
    if nature is None:
        nature = rand.next_int(25)
    height = rand.next_int(0x81) + rand.next_int(0x80)
    weight = rand.next_int(0x81) + rand.next_int(0x80)
    scale = rand.next_int(0x81) + rand.next_int(0x80)
    tera = _tera_type(seed, encounter)
    # Translate RNG's speed-last IV order to PK9's HP, Atk, Def, Spe, SpA, SpD order.
    pk9_ivs = (ivs[0], ivs[1], ivs[2], ivs[5], ivs[3], ivs[4])
    level = encounter["level"]
    profile = {
        "species": encounter["species"],
        "nickname": encounter.get("nickname", ""),
        "form": encounter.get("form", 0),
        "held_item": encounter.get("held_item", 0),
        "level": level,
        "met_level": level,
        "experience": _experience(level, personal["growth"]),
        "encryption_constant": ec,
        "trainer_id": fake_id & 0xFFFF,
        "secret_id": fake_id >> 16,
        "pid": pid,
        "ability": ability,
        "ability_number": 1 << ability_index,
        "gender": gender,
        "nature": nature,
        "stat_nature": nature,
        "ivs": pk9_ivs,
        "height_scalar": height,
        "weight_scalar": weight,
        "scale": scale,
        "tera_type_original": tera,
        "tera_type_override": 19,
        "moves": tuple(encounter["moves"]),
        "move_pp": _move_pp(encounter),
        "move_pp_ups": (0, 0, 0, 0),
        "current_hp": _stats(personal, pk9_ivs, level, nature)[0],
        "stats": _stats(personal, pk9_ivs, level, nature),
        "ot_friendship": personal["base_friendship"],
    }
    return {
        "seed": seed,
        "profile": profile,
        "metadata": {
            "species": encounter["species"],
            "stars": stars,
            "tera_type": tera,
            "encounter_identifier": encounter["identifier"],
        },
        "rewards": {
            "fixed": encounter.get("fixed_rewards", []),
            "lottery": encounter.get("lottery_rewards", []),
        },
    }


def generate_seed_raid(seed: int, *, version: str = "violet", progress: str = "4star",
                       map_name: str = "paldea", content: str = "standard") -> dict:
    """Generate an encounter, PK9 profile, and ordered rewards from the bundled retail tables.

    Unlike :func:`generate_raid`, this needs no caller-authored encounter context.  The remaining
    arguments are game state, not additional encounter data: the same seed legitimately resolves
    differently between versions, maps, progress stages, and standard/black tables.
    """
    # Imported here to keep raid_catalog's use of Xoroshiro128Plus free of an import cycle.
    from pokeldn.sv import raid_catalog

    catalog = raid_catalog.load_catalog()
    resolved = raid_catalog.resolve_raid(
        seed, version=version, progress=progress, map_name=map_name, content=content)
    source = resolved["encounter"]
    personal = raid_catalog.personal_entry(source["species"], source["form"], catalog=catalog)
    ability = {0: "any12", 1: "any12h", 2: "fixed0", 3: "fixed1", 4: "fixed2"}[
        source["ability"]]
    tera = ("default" if source["tera"] == 0 else "random" if source["tera"] == 1
            else source["tera"] - 2)
    gender = "random" if source["gender"] == 0 else source["gender"] - 1
    shiny = {0: "random", 1: "never", 2: "always"}[source["shiny"]]
    encounter = {
        "identifier": source["identifier"],
        "species": source["species"],
        "nickname": resolved["species_name"],
        "form": source["form"],
        "stars": source["stars"],
        "rate": 1,
        "rate_min": {version: 0},
        "flawless_ivs": source["flawless_ivs"],
        "ability": ability,
        "gender": gender,
        "shiny": shiny,
        "level": source["level"],
        "moves": source["moves"],
        "move_pp": [catalog["move_pp"][move] for move in source["moves"]],
        "tera": tera,
        "held_item": source["held_item"],
        "personal": personal,
    }
    # The ordinary generator's encounter selection is already resolved above.  A one-entry
    # context with a deterministic rate roll lets it retain a single profile-generation path.
    context_data = {
        "version": version,
        "progress": progress,
        "content": content,
        "rate_totals": {str(source["stars"]): {version: 1}},
        "encounters": [encounter],
    }
    # _select_encounter would roll stars again, which is appropriate but then its second draw must
    # fit the one-entry table.  The selected stars are guaranteed to agree with the same seed.
    generated = generate_raid(seed, context_data)
    generated["rewards"] = resolved["rewards"]
    generated["encounter"] = source
    return generated


def load_context(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def json_ready(raid: dict) -> dict:
    """Convert tuples into JSON-native lists without changing the in-memory PK9 profile."""
    return json.loads(json.dumps(raid))

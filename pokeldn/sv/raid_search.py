"""Fast local search over generated Scarlet/Violet raid encounters."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Callable

from pokeldn.sv.raid_generation import generate_seed_raid


VALIDATED_CONTEXT = {
    "version": "violet",
    "progress": "4star",
    "map_name": "paldea",
    "content": "standard",
}

OBJECTIVES = {
    "overall": ("Lowest overall bulk", True),
    "physical": ("Lowest physical bulk", True),
    "special": ("Lowest special bulk", True),
    "offense": ("Weakest offense", True),
    "hardest": ("Highest total stats", False),
}


@dataclass(frozen=True)
class RaidCandidate:
    seed: int
    species: int
    name: str
    form: int
    stars: int
    level: int
    tera_type: int
    shiny: bool
    ivs: tuple[int, int, int, int, int, int]
    stats: tuple[int, int, int, int, int, int]
    score: int


def _score(stats: tuple[int, ...], objective: str) -> int:
    hp, attack, defense, special_attack, special_defense, _speed = stats
    if objective == "physical":
        return hp * defense
    if objective == "special":
        return hp * special_defense
    if objective == "offense":
        return max(attack, special_attack)
    if objective == "hardest":
        return sum(stats)
    if objective == "overall":
        return hp * (defense + special_defense)
    raise ValueError(f"unknown raid-search objective {objective!r}")


def candidate(seed: int, objective: str = "overall") -> RaidCandidate:
    raid = generate_seed_raid(seed & 0xFFFFFFFF, **VALIDATED_CONTEXT)
    encounter, profile = raid["encounter"], raid["profile"]
    stats = tuple(profile["stats"])
    shiny_xor = (profile["trainer_id"] ^ profile["secret_id"]
                 ^ (profile["pid"] >> 16) ^ (profile["pid"] & 0xFFFF))
    return RaidCandidate(
        seed=seed & 0xFFFFFFFF,
        species=profile["species"],
        name=profile["nickname"],
        form=profile["form"],
        stars=encounter["stars"],
        level=profile["level"],
        tera_type=raid["metadata"]["tera_type"],
        shiny=shiny_xor < 16,
        ivs=tuple(profile["ivs"]),
        stats=stats,
        score=_score(stats, objective),
    )


def search(start: int, count: int, objective: str = "overall", *, stars: int | None = None,
           shiny: bool | None = None,
           limit: int = 12, progress: Callable[[int, int], None] | None = None) -> list[RaidCandidate]:
    """Return the best candidates from a wrapping 32-bit seed interval."""
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown raid-search objective {objective!r}")
    if not 1 <= count <= 1_000_000:
        raise ValueError("seed search count must be from 1 to 1,000,000")
    if not 1 <= limit <= 100:
        raise ValueError("seed search result limit must be from 1 to 100")
    if stars is not None and stars not in (1, 2, 3, 4):
        raise ValueError("the validated raid search supports star levels 1 through 4")

    minimize = OBJECTIVES[objective][1]
    best: list[tuple[int, int, RaidCandidate]] = []
    for offset in range(count):
        found = candidate((start + offset) & 0xFFFFFFFF, objective)
        if ((stars is None or found.stars == stars)
                and (shiny is None or found.shiny is shiny)):
            # Heap quality is always larger-is-better. The negative seed makes
            # an equal-score result deterministic and favors the earlier seed.
            quality = -found.score if minimize else found.score
            entry = (quality, -found.seed, found)
            if len(best) < limit:
                heapq.heappush(best, entry)
            elif entry[:2] > best[0][:2]:
                heapq.heapreplace(best, entry)
        if progress and ((offset + 1) % 5000 == 0 or offset + 1 == count):
            progress(offset + 1, count)
    return sorted((entry[2] for entry in best), key=lambda row: (row.score, row.seed),
                  reverse=not minimize)

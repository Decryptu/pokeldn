"""Fast local search over generated Scarlet/Violet raid encounters."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from itertools import product
from typing import Callable

from pokeldn.sv.raid_generation import generate_seed_raid


VALIDATED_CONTEXT = {
    "version": "violet",
    "progress": "4star",
    "map_name": "paldea",
    "content": "standard",
}

VERSIONS = ("scarlet", "violet")
MAPS = ("paldea", "kitakami", "blueberry")
PROGRESS_STAGES = ("beginning", "tera", "3star", "4star", "5star", "6star")
CONTENTS = ("standard", "black")
MAX_SEARCH_WORK = 1_000_000

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
    nature: int
    ability: int
    gender: int
    version: str
    map_name: str
    progress: str
    content: str
    score: int

    @property
    def context(self) -> dict[str, str]:
        return {"version": self.version, "map_name": self.map_name,
                "progress": self.progress, "content": self.content}


def context_combinations(*, version: str = "any", map_name: str = "any",
                         progress: str = "any", content: str = "any") -> list[dict[str, str]]:
    """Expand optional search dimensions into valid, non-duplicate raid contexts."""
    dimensions = ((version, VERSIONS, "version"), (map_name, MAPS, "map"),
                  (progress, PROGRESS_STAGES, "progress"), (content, CONTENTS, "content"))
    for value, choices, label in dimensions:
        if value != "any" and value not in choices:
            raise ValueError(f"unknown raid-search {label} {value!r}")
    versions = VERSIONS if version == "any" else (version,)
    maps = MAPS if map_name == "any" else (map_name,)
    contents = CONTENTS if content == "any" else (content,)
    result = []
    for selected_version, selected_map, selected_content in product(versions, maps, contents):
        # Progress does not participate in retail black-crystal selection. Canonicalize it so an
        # "Any" search does not evaluate the identical six-star raid six times.
        progresses = (("6star",) if selected_content == "black" else
                      PROGRESS_STAGES if progress == "any" else (progress,))
        for selected_progress in progresses:
            result.append({"version": selected_version, "map_name": selected_map,
                           "progress": selected_progress, "content": selected_content})
    return result


def raid_species() -> list[dict[str, int | str]]:
    """Return the searchable species that occur in the bundled raid tables."""
    from pokeldn.sv.raid_catalog import load_catalog

    catalog = load_catalog()
    ids = {row["species"] for rows in catalog["encounters"].values() for row in rows}
    names = catalog["species_names"]
    return [{"id": species, "name": (names[species] if species < len(names)
                                      else f"Species {species}")}
            for species in sorted(ids, key=lambda value: names[value].casefold())]


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


def candidate(seed: int, objective: str = "overall", *, context: dict | None = None) -> RaidCandidate:
    raid = generate_seed_raid(seed & 0xFFFFFFFF, **(context or VALIDATED_CONTEXT))
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
        nature=profile["nature"],
        ability=profile["ability"],
        gender=profile["gender"],
        version=raid["encounter"]["version"],
        map_name=raid["encounter"]["map"],
        progress=raid["encounter"]["progress"],
        content=raid["encounter"]["content"],
        score=_score(stats, objective),
    )


def search(start: int, count: int, objective: str = "overall", *, stars: int | None = None,
           shiny: bool | None = None, context: dict | None = None,
           contexts: list[dict] | None = None, species: str | int | None = None,
           tera_type: int | None = None, nature: int | None = None,
           ability: int | None = None, gender: int | None = None,
           iv_ranges: tuple[tuple[int, int], ...] | None = None,
           unique_species: bool = False,
           limit: int = 12, progress: Callable[[int, int], None] | None = None,
           cancelled: Callable[[], bool] | None = None) -> list[RaidCandidate]:
    """Return the best matching candidates from one or more raid contexts."""
    if objective not in OBJECTIVES:
        raise ValueError(f"unknown raid-search objective {objective!r}")
    if not 1 <= count <= 1_000_000:
        raise ValueError("seed search count must be from 1 to 1,000,000")
    if not 1 <= limit <= 100:
        raise ValueError("seed search result limit must be from 1 to 100")
    if stars is not None and stars not in (1, 2, 3, 4, 5, 6):
        raise ValueError("raid search supports star levels 1 through 6")
    if contexts is not None and context is not None:
        raise ValueError("pass either context or contexts, not both")
    selected_contexts = list(contexts) if contexts is not None else [context or VALIDATED_CONTEXT]
    if not selected_contexts:
        raise ValueError("raid search needs at least one context")
    total = count * len(selected_contexts)
    if total > MAX_SEARCH_WORK:
        raise ValueError(f"search covers {total:,} seed/context combinations; maximum is "
                         f"{MAX_SEARCH_WORK:,}")
    if tera_type is not None and not 0 <= tera_type < 18:
        raise ValueError("Tera type must be from 0 to 17")
    if nature is not None and not 0 <= nature < 25:
        raise ValueError("nature must be from 0 to 24")
    if gender is not None and gender not in (0, 1, 2):
        raise ValueError("gender must be male (0), female (1), or genderless (2)")
    if ability is not None and ability < 0:
        raise ValueError("ability ID cannot be negative")
    if iv_ranges is not None:
        if len(iv_ranges) != 6 or any(not (0 <= low <= high <= 31)
                                      for low, high in iv_ranges):
            raise ValueError("IV filters must contain six ranges between 0 and 31")

    species_value = str(species or "").strip()
    if species_value == "-":  # Optional GUI dropdown sentinel: "Not set" means any species.
        species_value = ""
    species_id = (species if isinstance(species, int) else
                  int(species_value) if species_value.isdecimal() else None)
    species_text = species_value.casefold() if species_id is None else ""

    def matches(found: RaidCandidate) -> bool:
        return ((stars is None or found.stars == stars)
                and (shiny is None or found.shiny is shiny)
                and (species_id is None or found.species == species_id)
                and (not species_text or species_text in found.name.casefold())
                and (tera_type is None or found.tera_type == tera_type)
                and (nature is None or found.nature == nature)
                and (ability is None or found.ability == ability)
                and (gender is None or found.gender == gender)
                and (iv_ranges is None or all(low <= iv <= high
                                               for iv, (low, high) in zip(found.ivs, iv_ranges))))

    minimize = OBJECTIVES[objective][1]
    best: list[tuple[int, int, int, RaidCandidate]] = []
    best_species: dict[int, tuple[int, int, int, RaidCandidate]] = {}
    done = 0
    for selected_context in selected_contexts:
        for offset in range(count):
            if cancelled and cancelled():
                break
            found = candidate((start + offset) & 0xFFFFFFFF, objective, context=selected_context)
            if matches(found):
                # Heap quality is always larger-is-better. The negative seed makes
                # an equal-score result deterministic and favors the earlier seed.
                quality = -found.score if minimize else found.score
                entry = (quality, -found.seed, -done, found)
                if unique_species:
                    previous = best_species.get(found.species)
                    if previous is None or entry[:3] > previous[:3]:
                        best_species[found.species] = entry
                elif len(best) < limit:
                    heapq.heappush(best, entry)
                elif entry[:2] > best[0][:2]:
                    heapq.heapreplace(best, entry)
            done += 1
            if progress and (done % 5000 == 0 or done == total):
                progress(done, total)
        if cancelled and cancelled():
            break
    entries = best_species.values() if unique_species else best
    return sorted((entry[3] for entry in entries), key=lambda row: (row.score, row.seed),
                  reverse=not minimize)[:limit]

"""Search a range of raid seeds for the bosses that match a filter, ranked by a stat score: the
app's raid finder (docs/sv_raid.md, Finding a seed)."""

from dataclasses import dataclass
import heapq
from itertools import product

from pokeldn.sv import raid_encounter as encounter, raid_event

MAX_WORK = 1_000_000              # seeds times contexts in one search
MAX_RESULTS = 100
# (label, score, lowest first). Stats are HP Atk Def Spe SpA SpD.
OBJECTIVES = {
    "overall": ("Lowest overall bulk", lambda s: s[0] * (s[2] + s[5]), True),
    "physical": ("Lowest physical bulk", lambda s: s[0] * s[2], True),
    "special": ("Lowest special bulk", lambda s: s[0] * s[5], True),
    "offense": ("Weakest offense", lambda s: max(s[1], s[4]), True),
    "hardest": ("Highest total stats", sum, False),
}


@dataclass(frozen=True)
class Found:
    seed: int
    context: dict
    stars: int
    boss: dict
    score: int

    @property
    def is_shiny(self):
        b = self.boss
        return (b["trainer_id"] ^ b["secret_id"] ^ (b["pid"] >> 16) ^ (b["pid"] & 0xFFFF)) < 16


def contexts(version="any", map_name="any", progress="any", content="any", event=None, group="any"):
    """-> the raid contexts a search covers; "any" widens a dimension. A black crystal ignores the
    story progress, so it is searched once. With an event, the contexts are its dens' (`group` one
    of them): Paldea, and one progress per stage, since the progresses of a stage draw alike."""
    if event is not None:
        return _event_contexts(event, version, progress, group)
    for value, choices in ((version, encounter.VERSIONS), (map_name, encounter.MAPS),
                           (progress, encounter.PROGRESS), (content, encounter.CONTENTS)):
        if value != "any" and value not in choices:
            raise ValueError(f"{value!r} is not one of {choices}")
    pick = lambda value, choices: choices if value == "any" else (value,)
    out = []
    for v, m, c in product(pick(version, encounter.VERSIONS), pick(map_name, encounter.MAPS),
                           pick(content, encounter.CONTENTS)):
        stages = ("6star",) if c == "black" else pick(progress, encounter.PROGRESS)
        out += [{"version": v, "map_name": m, "progress": p, "content": c} for p in stages]
    return out


def _event_contexts(event, version, progress, group):
    out = []
    for v in raid_event.versions(event):
        if version not in ("any", v):
            continue
        for den in raid_event.dens(event, v):
            if str(group) not in ("any", str(den.group)):
                continue
            stages = {}
            for p in raid_event.progresses(event, v, den.group):
                if progress in ("any", p):
                    stages.setdefault(raid_event.STAGES[p], p)
            out += [{"version": v, "map_name": "paldea", "progress": p, "content": den.content,
                     "event": event, "group": den.group, "den": den.label} for p in stages.values()]
    return out


def generate(seed, context):
    """-> the Raid the seed gives in a context as `contexts` makes it, an event's when it names one."""
    if "event" in context:
        return raid_event.generate(context["event"], seed, context["version"], context["progress"],
                                   context["group"])
    return encounter.generate(seed, context["version"], context["map_name"], context["progress"],
                              context["content"])


def _drawer(context):
    """-> seed -> (row, stars) in the context; an event's rows are gathered once, not per seed."""
    if "event" not in context:
        return lambda seed: encounter.select(seed, context["version"], context["map_name"],
                                             context["progress"], context["content"])
    rows = raid_event.candidates(context["event"], context["version"], context["progress"], context["group"])

    def draw(seed):
        row = raid_event.draw(rows, seed)
        return row, row["stars"]
    return draw


def species(event=None):
    """-> [(species, name)] of every standard and black-crystal raid boss, or of an event's, by name."""
    names = encounter.tables()["species_names"]
    if event is not None:
        found = {r["species"] for r in event.rows if r["rate"]}
    else:
        found = {row["species"] for rows in encounter.tables()["encounters"].values() for row in rows}
    return sorted(((s, names[str(s)]) for s in found), key=lambda pair: pair[1].casefold())


def search(start, count, scope, objective="overall", *, stars=None, shiny=None, species_id=None,
           tera_type=None, nature=None, gender=None, ability=None, ivs=None, one_per_species=False,
           limit=12, progress=None, cancelled=None):
    """-> up to `limit` matches among seeds start..start+count-1 in every context of `scope`, best
    score first. `ivs` is six (low, high) ranges, HP Atk Def Spe SpA SpD."""
    if objective not in OBJECTIVES:
        raise ValueError(f"no objective {objective!r}")
    if not scope or count < 1 or count * len(scope) > MAX_WORK:
        raise ValueError(f"a search covers 1 to {MAX_WORK:,} seeds over its contexts")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"a search returns 1 to {MAX_RESULTS} results")
    _, score, lowest_first = OBJECTIVES[objective]
    best, by_species = [], {}
    total, done = count * len(scope), 0
    for context in scope:
        draw = _drawer(context)
        for offset in range(count):
            if cancelled and cancelled():
                return _ranked(best, by_species, one_per_species, limit)
            done += 1
            if progress and done % 5000 == 0:
                progress(done, total)
            seed = (start + offset) & 0xFFFFFFFF
            row, found_stars = draw(seed)
            if (stars is not None and found_stars != stars) or (
                    species_id is not None and row["species"] != species_id):
                continue
            boss = encounter.boss_fields(seed, row)
            found = Found(seed, context, found_stars, boss, score(boss["stats"]))
            if ((shiny is not None and found.is_shiny != shiny)
                    or (tera_type is not None and boss["tera_type_original"] != tera_type)
                    or (nature is not None and boss["nature"] != nature)
                    or (gender is not None and boss["gender"] != gender)
                    or (ability is not None and boss["ability"] != ability)
                    or (ivs is not None and not all(lo <= iv <= hi for iv, (lo, hi)
                                                     in zip(boss["ivs"], ivs)))):
                continue
            # Larger is better on the heap; the earlier seed wins a tie.
            entry = (-found.score if lowest_first else found.score, -seed, done, found)
            if one_per_species:
                kept = by_species.get(boss["species"])
                if kept is None or entry[:2] > kept[:2]:
                    by_species[boss["species"]] = entry
            elif len(best) < limit:
                heapq.heappush(best, entry)
            elif entry[:2] > best[0][:2]:
                heapq.heapreplace(best, entry)
    if progress:
        progress(total, total)
    return _ranked(best, by_species, one_per_species, limit)


def _ranked(best, by_species, one_per_species, limit):
    entries = by_species.values() if one_per_species else best
    return [e[3] for e in sorted(entries, reverse=True)[:limit]]

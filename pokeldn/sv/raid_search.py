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
    rewards: tuple = ()           # [(item, quantity)], drawn when the search wants rewards

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


def _rows(context):
    """-> [(row, stars)] every encounter the context can draw."""
    if "event" in context:
        return [(r, r["stars"]) for r in raid_event.candidates(context["event"], context["version"],
                                                               context["progress"], context["group"])]
    content = context["content"]
    stars = {6} if content == "black" else {s for _, s in encounter.STAR_LOTTERY[context["progress"]]}
    return [(r, r["stars"]) for r in encounter.tables()["encounters"][f"{context['map_name']}_{content}"]
            if r["stars"] in stars and r["rate"] and r["rate_min"][context["version"]] >= 0]


def _reward_tables(context):
    """-> (fixed, lottery) tables a context's raids draw their rewards from; None the base game's."""
    event = context.get("event")
    return (event.fixed, event.lottery) if event is not None else (None, None)


def _gems(row):
    """-> the Tera types the boss of a row can have, which pick its Tera shards."""
    if row["tera"] >= 2:
        return {row["tera"] - 2}
    if row["tera"] == 1:
        return set(range(len(encounter.TERA_TYPES)))
    return set(encounter.personal(row["species"], row["form"])[1])


def _sums(amounts, counts):
    """-> every total of exactly k draws from `amounts`, k one of `counts`."""
    reach, out = {0}, {0} if 0 in counts else set()
    for k in range(1, max(counts, default=0) + 1):
        reach = {s + a for s in reach for a in amounts}
        if k in counts:
            out |= reach
    return out


def _totals(row, stars, fixed, lottery, gem):
    """-> {item: every total of it a raid of the row gives with that Tera type}: its fixed rows, plus
    any number of the lottery's draws of it up to the most a raid draws (all of them when the
    lottery holds nothing else)."""
    data = encounter.tables()
    material = int(data["material_items"].get(str(row["species"]), 0))

    def item(entry):
        return entry["item"] or {encounter.REWARD_MATERIAL: material,
                                 encounter.REWARD_SHARD: encounter.TERA_SHARDS[gem]}.get(entry["category"], 0)
    fixed = data["fixed_rewards"] if fixed is None else fixed
    lottery = data["lottery_rewards"] if lottery is None else lottery
    given = {}
    for entry in fixed.get(row["fixed_rewards"], ()):
        if item(entry) and entry["amount"]:
            given[item(entry)] = given.get(item(entry), 0) + entry["amount"]
    draws = [(item(e), e["amount"]) for e in lottery.get(row["lottery_rewards"], ()) if e["probability"]]
    counts = set(encounter.REWARD_SLOTS[stars - 1]) if draws else {0}
    out = {}
    for wanted in set(given) | {i for i, n in draws if i and n}:
        amounts = {n for i, n in draws if i == wanted and n}
        others = any(i != wanted or not n for i, n in draws)
        drawn = _sums(amounts, set(range(max(counts) + 1)) if others else counts)
        totals = {given.get(wanted, 0) + s for s in drawn} - {0}
        if totals:
            out[wanted] = totals
    return out


def reward_choices(scope, *, stars=None, species_id=None, tera_type=None):
    """-> {item: (every total of it, lowest first)} of the items the raids of `scope` can give,
    narrowed to a star level, species and Tera type as the search would be."""
    out, seen = {}, {}
    for context in scope:
        fixed, lottery = _reward_tables(context)
        for row, row_stars in _rows(context):
            if (stars is not None and row_stars != stars) or (species_id is not None
                                                              and row["species"] != species_id):
                continue
            for gem in _gems(row) if tera_type is None else _gems(row) & {tera_type}:
                key = (row["fixed_rewards"], row["lottery_rewards"], row["species"], row_stars, gem, id(fixed))
                if key not in seen:
                    seen[key] = _totals(row, row_stars, fixed, lottery, gem)
                for item, totals in seen[key].items():
                    out.setdefault(item, set()).update(totals)
    return {item: tuple(sorted(totals)) for item, totals in out.items()}


def _can_give(row, stars, tables, wanted):
    """-> whether some raid of the row gives at least the wanted quantity of every wanted item."""
    best = {}
    for gem in _gems(row):
        for item, totals in _totals(row, stars, *tables, gem).items():
            best[item] = max(best.get(item, 0), max(totals))
    return all(best.get(item, 0) >= least for item, least in wanted.items())


def gives(rewards, wanted):
    """-> whether the rewards hold at least the wanted quantity of every wanted item."""
    totals = {}
    for item, quantity in rewards:
        totals[item] = totals.get(item, 0) + quantity
    return all(totals.get(item, 0) >= least for item, least in wanted.items())


def species(event=None):
    """-> [(species, name)] of every standard and black-crystal raid boss, or of an event's, by name."""
    names = encounter.tables()["species_names"]
    if event is not None:
        found = {r["species"] for r in event.rows if r["rate"]}
    else:
        found = {row["species"] for rows in encounter.tables()["encounters"].values() for row in rows}
    return sorted(((s, names[str(s)]) for s in found), key=lambda pair: pair[1].casefold())


def search(start, count, scope, objective="overall", *, stars=None, shiny=None, species_id=None,
           tera_type=None, nature=None, gender=None, ability=None, ivs=None, rewards=None,
           one_per_species=False, limit=12, progress=None, cancelled=None):
    """-> up to `limit` matches among seeds start..start+count-1 in every context of `scope`, best
    score first. `ivs` is six (low, high) ranges, HP Atk Def Spe SpA SpD; `rewards` {item: least
    quantity}, a raid's quantities of an item summed, and a match carries its rewards."""
    if objective not in OBJECTIVES:
        raise ValueError(f"no objective {objective!r}")
    if not scope or count < 1 or count * len(scope) > MAX_WORK:
        raise ValueError(f"a search covers 1 to {MAX_WORK:,} seeds over its contexts")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"a search returns 1 to {MAX_RESULTS} results")
    _, score, lowest_first = OBJECTIVES[objective]
    best, by_species = [], {}
    total, done = count * len(scope), 0
    wanted = dict(rewards or {})
    for context in scope:
        draw = _drawer(context)
        tables = _reward_tables(context)
        able = {}                     # a row's id -> whether its raids can give what is wanted
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
            given = ()
            if wanted:
                if id(row) not in able:
                    able[id(row)] = _can_give(row, found_stars, tables, wanted)
                if not able[id(row)]:
                    continue
                given = tuple(encounter.rewards(seed, row, found_stars, *tables))
                if not gives(given, wanted):
                    continue
            boss = encounter.boss_fields(seed, row)
            found = Found(seed, context, found_stars, boss, score(boss["stats"]), given)
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

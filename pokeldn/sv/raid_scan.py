"""raid_search's seed scan in the PKHeX helper (services/pkhex/RaidScan.cs): each seed's encounter, its
boss up to the nature, the score, every filter and the rewards, over every core. It only names the
seeds worth keeping; raid_search then makes their raids with the plain Python code, so a search finds
what the Python scan finds, faster (docs/sv_raid.md, Finding a seed). The scan runs in a helper process
of its own, so a search never waits on the app's other PKHeX requests."""

import threading

from pokeldn.sv import raid_encounter as encounter, raid_event

CHUNK = 1 << 24                       # seeds per request: progress and Stop between requests
MODE_STANDARD, MODE_BLACK, MODE_EVENT = range(3)
OBJECTIVE_INDEX = {"overall": 0, "physical": 1, "special": 2, "offense": 3, "hardest": 4}
# A packed encounter row's columns, as RaidScan.cs reads them.
(SPECIES, STARS, FLAWLESS, ABILITY_RULE, GENDER, CUTOFF, RATIO, NATURE, TOXTRICITY, SHINY, TERA, LEVEL,
 MATERIAL, NFIXED, NLOTTERY, LOTTERY_TOTAL) = range(16)
IVS, ABILITIES, TYPES, BASE, EVS = 16, 22, 25, 27, 33
COLUMNS = 39

_SERVICE = None
_LOCK = threading.Lock()


def available() -> bool:
    """Whether the PKHeX helper is there to scan."""
    from pokeldn import pokemon
    try:
        pokemon._command()
    except pokemon.BuilderError:
        return False
    return True


def _service():
    global _SERVICE
    with _LOCK:
        if _SERVICE is None:
            from pokeldn import pokemon
            _SERVICE = pokemon.Service()
        return _SERVICE


def pack(context):
    """-> the context's draw tables and encounter rows as the helper reads them."""
    event = context.get("event")
    data = encounter.tables()
    version = context["version"]
    if event is not None:
        rows = raid_event.candidates(event, version, context["progress"], context["group"])
        mode, fixed_t, lottery_t, lottery_stars = MODE_EVENT, event.fixed, event.lottery, ()
        totals = [sum(r["rate"] for r in rows)] + [0] * 7
    else:
        rows = [r for r in data["encounters"][f"{context['map_name']}_{context['content']}"]
                if r["rate"] and r["rate_min"][version] >= 0]
        mode = MODE_BLACK if context["content"] == "black" else MODE_STANDARD
        fixed_t, lottery_t = data["fixed_rewards"], data["lottery_rewards"]
        lottery_stars = encounter.STAR_LOTTERY[context["progress"]]
        totals = [0, *encounter.RATE_TOTALS[(context["map_name"], version)], 0]
    width = max(totals) + 1
    lut = [-1] * (8 * width)
    if mode == MODE_EVENT:            # raid_event.draw: the rates one after the other
        low = 0
        for i, r in enumerate(rows):
            lut[low:low + r["rate"]] = [i] * r["rate"]
            low += r["rate"]
    else:                             # encounter.select: the first row whose range holds the choice
        for i, r in reversed(list(enumerate(rows))):
            first = r["rate_min"][version]
            last = min(first + r["rate"], totals[r["stars"]])
            lut[r["stars"] * width + first:r["stars"] * width + last] = [i] * (last - first)
    fixed = [fixed_t.get(r["fixed_rewards"], ()) for r in rows]
    lottery = [lottery_t.get(r["lottery_rewards"], ()) for r in rows]
    fixed_width = max(map(len, fixed), default=0) or 1
    lottery_width = max(map(len, lottery), default=0) or 1
    table, fixed_a, lottery_a = [], [0] * (len(rows) * fixed_width * 3), [0] * (len(rows) * lottery_width * 4)
    for i, r in enumerate(rows):
        base, types, ratio, _friendship, _growth, abilities = encounter.personal(r["species"], r["form"])
        line = [0] * COLUMNS
        line[SPECIES], line[STARS], line[FLAWLESS] = r["species"], r["stars"], r["flawless_ivs"]
        line[ABILITY_RULE] = r["ability"]
        line[GENDER] = -1 if r.get("gender") is None else r["gender"]
        line[CUTOFF], line[RATIO] = encounter.GENDER_CUTOFF.get(ratio, 0), ratio
        line[NATURE] = -1 if r.get("nature") is None else r["nature"]
        line[TOXTRICITY] = r["form"] if r["species"] == encounter.TOXTRICITY else -1
        line[SHINY], line[TERA], line[LEVEL] = r.get("shiny", encounter.SHINY_RANDOM), r["tera"], r["level"]
        line[MATERIAL] = int(data["material_items"].get(str(r["species"]), 0))
        line[NFIXED], line[NLOTTERY] = len(fixed[i]), len(lottery[i])
        line[LOTTERY_TOTAL] = sum(e["probability"] for e in lottery[i])
        line[IVS:IVS + 6] = [-1 if v is None else v for v in (r.get("ivs") or [None] * 6)]
        line[ABILITIES:ABILITIES + 3], line[TYPES:TYPES + 2] = abilities, types
        line[BASE:BASE + 6], line[EVS:EVS + 6] = base, r["evs"]
        table += line
        for j, e in enumerate(fixed[i]):
            at = (i * fixed_width + j) * 3
            fixed_a[at:at + 3] = e["item"], e["category"], e["amount"]
        for j, e in enumerate(lottery[i]):
            at = (i * lottery_width + j) * 4
            lottery_a[at:at + 4] = e["item"], e["category"], e["amount"], e["probability"]
    natures = encounter.TOXTRICITY_NATURES
    longest = max(len(t) for t in natures)
    return {
        "mode": mode, "star_ceil": [c for c, _ in lottery_stars], "star_val": [s for _, s in lottery_stars],
        "totals": totals, "lut": lut, "lut_width": width, "rows": table,
        "fixed": fixed_a, "fixed_width": fixed_width, "lottery": lottery_a, "lottery_width": lottery_width,
        "toxt_tab": [n for t in natures for n in (*t, *[0] * (longest - len(t)))],
        "toxt_n": [len(t) for t in natures], "shards": list(encounter.TERA_SHARDS),
        "slots": [n for row in encounter.REWARD_SLOTS for n in row], "columns": list(encounter.REWARD_COLUMNS),
    }


def offsets(start, count, context, objective, lowest, limit, one_per_species, *, stars=None, shiny=None,
            species_id=None, tera_type=None, nature=None, gender=None, ability=None, ivs=None, rewards=None,
            progress=None, cancelled=None, stop_at_first=False):
    """-> the offsets from `start`, in order, of the seeds among start..start+count-1 that can be a
    match raid_search keeps in this context: its best `limit`, each species' best, or with
    `stop_at_first` the earliest match alone, and every seed whose table has no encounter before it.
    Scanned in chunks; `progress(n)` after each, and a Stop answers what was found so far."""
    request = {"cmd": "raid_scan", "game": "sv", **pack(context), "objective": OBJECTIVE_INDEX[objective],
               "lowest": bool(lowest), "limit": limit,
               "keep": "first" if stop_at_first else "species" if one_per_species else "best",
               "filters": [-1 if v is None else int(v)
                           for v in (stars, shiny, species_id, tera_type, nature, gender, ability)],
               "ivs": [n for pair in (ivs if ivs is not None else [(0, 31)] * 6) for n in pair],
               "want": [n for pair in (rewards or {}).items() for n in pair]}
    service = _service()
    kept, by_species, visits = [], {}, []
    for first in range(0, count, CHUNK):
        if cancelled and cancelled():
            break
        n = min(CHUNK, count - first)
        reply = service._ask({**request, "start": (start + first) & 0xFFFFFFFF, "count": n})
        visits += [first + v for v in reply["visits"]]
        if stop_at_first and reply["first"] >= 0:
            return sorted(visits) + [first + reply["first"]]
        for species, rank in reply["species"]:
            by_species[species] = min(rank, by_species.get(species, rank))
        kept = sorted(kept + reply["ranks"])[:limit]
        if progress:
            progress(first + n)
    if one_per_species:
        kept = by_species.values()
    return sorted({((rank & 0xFFFFFFFF) - start) & 0xFFFFFFFF for rank in kept} | set(visits))

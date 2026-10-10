"""raid_search's seed scan compiled with numba: each seed's encounter, its boss up to the nature, the
score, every filter and the rewards, millions of seeds a second over every core. It only picks the
seeds worth keeping; raid_search then makes their raids with the plain Python code, so a search finds
what it finds without numba, only faster. Without numba, `offsets` answers None and raid_search scans
every seed itself.

The compiled code is cached for a generic CPU of the architecture, so the cache scripts/pack_app.py
builds (scripts/build_jit_cache.py) loads on every user's machine: the app opens its first search
without the 20-odd seconds numba takes to compile (docs/sv_raid.md, Finding a seed)."""

import hashlib
import importlib.util
import os
import shutil
import sys
import threading
from pathlib import Path

from pokeldn.sv import raid_encounter as encounter, raid_event

# Code for the architecture's baseline, not this CPU's: numba then keys its cache on
# (triple, "generic", "") and a cache built on the release runner loads anywhere. A search runs at
# the same speed either way, as it is integer work.
os.environ.setdefault("NUMBA_CPU_NAME", "generic")
# CacheLocator first; numba's own when its folder cannot be written.
os.environ["NUMBA_CACHE_LOCATOR_CLASSES"] = f"{__name__}.CacheLocator,InTreeCacheLocator,UserWideCacheLocator"
CACHE_ENV = "POKELDN_JIT_CACHE"       # where the cache is read and written, as scripts/build_jit_cache.py sets it
SHIPPED = "jit_cache"                 # the packed app's prebuilt cache, under its root
CHUNK = 1 << 22                       # seeds per call: progress and Stop between calls, 52 MB of answers
NO_MATCH = (1 << 63) - 1
VISIT = -1                            # a seed whose table has no encounter: raid_search raises on it
SCORE_LIMIT = 1 << 31

# A context's encounter rows, one line of numbers each.
(SPECIES, STARS, FLAWLESS, ABILITY_RULE, GENDER, CUTOFF, RATIO, NATURE, TOXTRICITY, SHINY, TERA, LEVEL,
 MATERIAL, NFIXED, NLOTTERY, LOTTERY_TOTAL) = range(16)
IVS, ABILITIES, TYPES, BASE, EVS = 16, 22, 25, 27, 33
COLUMNS = 39
# The filters, -1 for none.
F_STARS, F_SHINY, F_SPECIES, F_TERA, F_NATURE, F_GENDER, F_ABILITY = range(7)
MODE_STANDARD, MODE_BLACK, MODE_EVENT = range(3)
SHINY_NEVER, SHINY_ALWAYS = 1, 2      # literals, so the cache's stamp (code_stamp) covers them
assert (SHINY_NEVER, SHINY_ALWAYS) == (encounter.SHINY_NEVER, encounter.SHINY_ALWAYS)


def cache_dir() -> Path:
    """-> the folder numba reads and writes the cache in: one per app version, outside the app."""
    if os.environ.get(CACHE_ENV):
        return Path(os.environ[CACHE_ENV])
    from pokeldn import __version__
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "pokeldn" / "numba" / __version__


def seed_cache(target: Path) -> None:
    """Copies the packed app's prebuilt cache to `target` once; in the default place, other app
    versions' caches beside it go."""
    shipped = Path(getattr(sys, "_MEIPASS", "")) / SHIPPED
    if not getattr(sys, "frozen", False) or not shipped.is_dir() or target.is_dir():
        return
    try:
        shutil.copytree(shipped, target)
        if not os.environ.get(CACHE_ENV):
            for old in target.parent.iterdir():
                if old != target and old.is_dir():
                    shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


def _hash_code(code, h) -> None:
    h.update(code.co_code)
    h.update(repr(code.co_names).encode())
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            _hash_code(const, h)
        elif isinstance(const, frozenset):         # set order changes with the process's hash seed
            h.update(repr(sorted(map(repr, const))).encode())
        else:
            h.update(repr(const).encode())


def code_stamp() -> str:
    """-> a hash of this module's bytecode, the helpers numba inlines included, file names left out:
    the same in the build's venv and the packed app wherever it is installed."""
    spec = importlib.util.find_spec(__name__)
    h = hashlib.sha256()
    _hash_code(spec.loader.get_code(__name__), h)
    return h.hexdigest()


try:
    import numpy as np
    from numba import njit, prange, uint64, int64
    from numba.core.caching import _CacheLocator
except ImportError:                   # pure Python: raid_search scans every seed itself
    njit = None
else:
    class CacheLocator(_CacheLocator):
        """cache_dir(), fresh while this module's bytecode is: numba's own locators key a frozen app's
        cache on its executable and its install path."""
        stamp = None

        def __init__(self, py_func, py_file):
            self._lineno = py_func.__code__.co_firstlineno
            self._path = cache_dir()

        def get_cache_path(self):
            return str(self._path)

        def get_source_stamp(self):
            if CacheLocator.stamp is None:
                CacheLocator.stamp = code_stamp()
            return CacheLocator.stamp

        def get_disambiguator(self):
            return str(self._lineno)

        @classmethod
        def from_function(cls, py_func, py_file):
            self = cls(py_func, py_file)
            seed_cache(self._path)
            try:
                self.ensure_cache_path()
            except OSError:
                return None
            return self


if njit is not None:
    K = uint64(0x82A2B175229D6A5B)

    @njit(inline="always")
    def _next(s0, s1):
        result = s0 + s1
        s1 ^= s0
        return (((s0 << uint64(24)) | (s0 >> uint64(40))) ^ s1 ^ (s1 << uint64(16)),
                (s1 << uint64(37)) | (s1 >> uint64(27)), result)

    @njit(inline="always")
    def _next_int(s0, s1, maximum):
        """encounter.Xoroshiro.next_int: a draw under `maximum`, rejecting those above its power of two."""
        m, mask = uint64(maximum - 1), uint64(0)
        while m:
            mask = (mask << uint64(1)) | uint64(1)
            m >>= uint64(1)
        while True:
            s0, s1, value = _next(s0, s1)
            value &= mask
            if value < uint64(maximum):
                return s0, s1, int64(value)

    @njit(inline="always")
    def _item(entry_item, category, row, gem, shards):
        if entry_item:
            return entry_item
        if category == 1:
            return row[MATERIAL]
        return shards[gem] if category == 2 else 0

    @njit(parallel=True, cache=True, nogil=True)
    def _scan(start, count, mode, lowest, objective, star_ceil, star_val, totals, lut, rows, fixed, lottery,
              flt, ivr, want, toxt_tab, toxt_n, shards, slots, columns, rank, species):
        """rank[i]: seed start+i's score and seed as one number, lowest best, NO_MATCH when a filter
        turns it away; species[i] its boss. As encounter.select, boss_fields, rewards and tera_type."""
        for off in prange(count):
            seed = (start + off) & 0xFFFFFFFF
            rank[off] = NO_MATCH
            species[off] = -1
            s0, s1 = uint64(seed), K
            stars = 6
            if mode == MODE_STANDARD:
                s0, s1, roll = _next_int(s0, s1, 100)
                for k in range(star_ceil.shape[0]):
                    if roll <= star_ceil[k]:
                        stars = star_val[k]
                        break
                s0, s1, choice = _next_int(s0, s1, totals[stars])
                r = lut[stars, choice]
            elif mode == MODE_BLACK:
                s0, s1, choice = _next_int(s0, s1, totals[6])
                r = lut[6, choice]
            else:
                s0, s1, roll = _next_int(s0, s1, 100)
                s0, s1, choice = _next_int(s0, s1, totals[0])
                r = lut[0, choice]
                if r >= 0:
                    stars = rows[r, STARS]
            if r < 0:
                rank[off] = VISIT
                continue
            row = rows[r]
            species[off] = row[SPECIES]
            if ((flt[F_STARS] >= 0 and stars != flt[F_STARS])
                    or (flt[F_SPECIES] >= 0 and row[SPECIES] != flt[F_SPECIES])):
                continue
            if row[TERA] >= 2:
                gem = row[TERA] - 2
            else:
                t0, t1 = uint64(seed), K
                if row[TERA] == 1:
                    t0, t1, gem = _next_int(t0, t1, 18)
                else:
                    t0, t1, pick = _next_int(t0, t1, 2)
                    gem = row[TYPES + pick]
            if want.shape[0]:
                short = 0
                for w in range(want.shape[0]):
                    got = 0
                    for j in range(row[NFIXED]):
                        item = _item(fixed[r, j, 0], fixed[r, j, 1], row, gem, shards)
                        if item == want[w, 0] and fixed[r, j, 2]:
                            got += fixed[r, j, 2]
                    if row[LOTTERY_TOTAL]:
                        a0, a1 = uint64(seed), K
                        a0, a1, roll = _next_int(a0, a1, 100)
                        column = 0
                        for e in range(columns.shape[0]):
                            if roll >= columns[e]:
                                column += 1
                        for _ in range(slots[stars - 1, column]):
                            a0, a1, threshold = _next_int(a0, a1, row[LOTTERY_TOTAL])
                            for j in range(row[NLOTTERY]):
                                weight = lottery[r, j, 3]
                                if weight > threshold:
                                    item = _item(lottery[r, j, 0], lottery[r, j, 1], row, gem, shards)
                                    if item == want[w, 0] and lottery[r, j, 2]:
                                        got += lottery[r, j, 2]
                                    break
                                threshold -= weight
                    if got < want[w, 1]:
                        short += 1
                if short:
                    continue
            b0, b1 = uint64(seed), K
            b0, b1, _ec = _next_int(b0, b1, 0xFFFFFFFF)
            b0, b1, fake = _next_int(b0, b1, 0xFFFFFFFF)
            b0, b1, pid = _next_int(b0, b1, 0xFFFFFFFF)
            tid, sid, low = fake & 0xFFFF, fake >> 16, pid & 0xFFFF
            sparkles = (tid ^ sid ^ (pid >> 16) ^ low) < 16
            if row[SHINY] == SHINY_NEVER and sparkles:
                pid ^= 0x10000000
            elif row[SHINY] == SHINY_ALWAYS and not sparkles:
                pid = ((tid ^ sid ^ low) << 16) | low
            shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 16
            if (flt[F_SHINY] >= 0 and shiny != (flt[F_SHINY] == 1)) or (flt[F_TERA] >= 0 and gem != flt[F_TERA]):
                continue
            w6 = np.empty(12, np.int64)           # IVs in draw order, then the stats
            for k in range(6):
                w6[k] = row[IVS + k]
            for _ in range(row[FLAWLESS]):
                b0, b1, index = _next_int(b0, b1, 6)
                while w6[index] >= 0:
                    b0, b1, index = _next_int(b0, b1, 6)
                w6[index] = 31
            for k in range(6):
                if w6[k] < 0:
                    b0, b1, value = _next_int(b0, b1, 32)
                    w6[k] = value
            rule = row[ABILITY_RULE]
            if rule == 0:
                b0, b1, ability = _next_int(b0, b1, 2)
            elif rule == 1:
                b0, b1, ability = _next_int(b0, b1, 3)
            else:
                ability = rule - 2
            ratio = row[RATIO]
            if row[GENDER] >= 0:
                gender = row[GENDER]
            elif ratio == 0xFF:
                gender = 2
            elif ratio == 0xFE:
                gender = 1
            elif ratio == 0:
                gender = 0
            else:
                b0, b1, value = _next_int(b0, b1, 100)
                gender = 1 if value < row[CUTOFF] else 0
            if row[NATURE] >= 0:
                nature = row[NATURE]
            elif row[TOXTRICITY] >= 0:
                b0, b1, value = _next_int(b0, b1, toxt_n[row[TOXTRICITY]])
                nature = toxt_tab[row[TOXTRICITY], value]
            else:
                b0, b1, nature = _next_int(b0, b1, 25)
            if ((flt[F_NATURE] >= 0 and nature != flt[F_NATURE]) or (flt[F_GENDER] >= 0 and gender != flt[F_GENDER])
                    or (flt[F_ABILITY] >= 0 and row[ABILITIES + ability] != flt[F_ABILITY])):
                continue
            # Drawn HP Atk Def SpA SpD Spe; the boss's IVs and stats are HP Atk Def Spe SpA SpD.
            w6[6] = w6[0]
            w6[7] = w6[1]
            w6[8] = w6[2]
            w6[9] = w6[5]
            w6[10] = w6[3]
            w6[11] = w6[4]
            outside = 0
            for k in range(6):
                if w6[6 + k] < ivr[k, 0] or w6[6 + k] > ivr[k, 1]:
                    outside += 1
            if outside:
                continue
            level = row[LEVEL]
            for k in range(6):
                w6[6 + k] = (2 * row[BASE + k] + w6[6 + k] + row[EVS + k] // 4) * level // 100 + 5
            w6[6] += level + 5
            up, down = nature // 5 + 1, nature % 5 + 1
            if up != down:
                w6[6 + up] = w6[6 + up] * 110 // 100
                w6[6 + down] = w6[6 + down] * 90 // 100
            hp, atk, dfn, spe, spa, spd = w6[6], w6[7], w6[8], w6[9], w6[10], w6[11]
            if objective == 0:
                score = hp * (dfn + spd)
            elif objective == 1:
                score = hp * dfn
            elif objective == 2:
                score = hp * spd
            elif objective == 3:
                score = max(atk, spa)
            else:
                score = hp + atk + dfn + spe + spa + spd
            rank[off] = ((score if lowest else SCORE_LIMIT - score) << 32) | seed

    @njit(cache=True, nogil=True)
    def _best_per_species(rank, species, best):
        """best[s]: the lowest rank of species s, for a search keeping one boss per species."""
        for i in range(rank.shape[0]):
            if 0 <= rank[i] < best[species[i]]:
                best[species[i]] = rank[i]


_LOCK = threading.Lock()                 # one scan at a time: numba's thread pool takes one caller
_PACKED = {}
OBJECTIVE_INDEX = {"overall": 0, "physical": 1, "special": 2, "offense": 3, "hardest": 4}


def available() -> bool:
    return njit is not None


def _pack(context):
    """-> the context's draw tables and rows as arrays; kept, as a context's tables never change. An
    entry holds its event, so no other event takes its id while it is kept."""
    event = context.get("event")
    key = (id(event), context["version"], context["map_name"], context["progress"], context["content"],
           context.get("group"))
    if key in _PACKED and _PACKED[key][0] is event:
        return _PACKED[key][1]
    if len(_PACKED) > 256:
        _PACKED.clear()
    data = encounter.tables()
    version = context["version"]
    if event is not None:
        rows = raid_event.candidates(event, version, context["progress"], context["group"])
        mode, fixed_t, lottery_t = MODE_EVENT, event.fixed, event.lottery
        lottery_stars = ()
        totals = [sum(r["rate"] for r in rows)] + [0] * 7
    else:
        rows = [r for r in data["encounters"][f"{context['map_name']}_{context['content']}"]
                if r["rate"] and r["rate_min"][version] >= 0]
        mode = MODE_BLACK if context["content"] == "black" else MODE_STANDARD
        fixed_t, lottery_t = data["fixed_rewards"], data["lottery_rewards"]
        lottery_stars = encounter.STAR_LOTTERY[context["progress"]]
        totals = [0, *encounter.RATE_TOTALS[(context["map_name"], version)], 0]
    lut = np.full((8, max(totals) + 1), -1, np.int64)
    if mode == MODE_EVENT:            # raid_event.draw: the rates one after the other
        low = 0
        for i, r in enumerate(rows):
            lut[0, low:low + r["rate"]] = i
            low += r["rate"]
    else:                             # encounter.select: the first row whose range holds the choice
        for i, r in reversed(list(enumerate(rows))):
            first = r["rate_min"][version]
            lut[r["stars"], first:min(first + r["rate"], totals[r["stars"]])] = i
    fixed = [fixed_t.get(r["fixed_rewards"], ()) for r in rows]
    lottery = [lottery_t.get(r["lottery_rewards"], ()) for r in rows]
    table = np.zeros((len(rows), COLUMNS), np.int64)
    fixed_a = np.zeros((len(rows), max(map(len, fixed), default=0) or 1, 3), np.int64)
    lottery_a = np.zeros((len(rows), max(map(len, lottery), default=0) or 1, 4), np.int64)
    for i, r in enumerate(rows):
        base, types, ratio, _friendship, _growth, abilities = encounter.personal(r["species"], r["form"])
        line = table[i]
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
        for j, e in enumerate(fixed[i]):
            fixed_a[i, j] = e["item"], e["category"], e["amount"]
        for j, e in enumerate(lottery[i]):
            lottery_a[i, j] = e["item"], e["category"], e["amount"], e["probability"]
    natures = encounter.TOXTRICITY_NATURES
    longest = max(len(t) for t in natures)
    packed = (
        mode, np.array([c for c, _ in lottery_stars] or [0], np.int64),
        np.array([s for _, s in lottery_stars] or [0], np.int64), np.array(totals, np.int64), lut, table,
        fixed_a, lottery_a, np.array([list(t) + [0] * (longest - len(t)) for t in natures], np.int64),
        np.array([len(t) for t in natures], np.int64), np.array(encounter.TERA_SHARDS, np.int64),
        np.array(encounter.REWARD_SLOTS, np.int64), np.array(encounter.REWARD_COLUMNS, np.int64))
    _PACKED[key] = event, packed
    return packed


def offsets(start, count, context, objective, lowest, limit, one_per_species, *, stars=None, shiny=None,
            species_id=None, tera_type=None, nature=None, gender=None, ability=None, ivs=None, rewards=None,
            progress=None, cancelled=None):
    """-> the offsets from `start`, in order, of the seeds among start..start+count-1 that can be a
    match raid_search keeps in this context: its best `limit` or each species' best; None without
    numba. Scanned in chunks; `progress(n)` after each, and a Stop answers what was found so far."""
    if njit is None:
        return None
    (mode, star_ceil, star_val, totals, lut, rows, fixed, lottery, toxt_tab, toxt_n, shards, slots,
     columns) = _pack(context)
    flt = np.array([-1 if v is None else int(v)
                    for v in (stars, shiny, species_id, tera_type, nature, gender, ability)], np.int64)
    ivr = np.array(ivs if ivs is not None else [(0, 31)] * 6, np.int64).reshape(6, 2)
    want = np.array(list((rewards or {}).items()), np.int64).reshape(-1, 2)
    kept, visit = np.empty(0, np.int64), []
    best = np.full(max(int(rows[:, SPECIES].max(initial=0)) + 1, 1), NO_MATCH, np.int64)
    rank, species = np.empty(min(count, CHUNK), np.int64), np.empty(min(count, CHUNK), np.int64)
    with _LOCK:
        for first in range(0, count, CHUNK):
            if cancelled and cancelled():
                break
            n = min(CHUNK, count - first)
            _scan((start + first) & 0xFFFFFFFF, n, mode, int(lowest), OBJECTIVE_INDEX[objective], star_ceil, star_val,
                  totals, lut, rows, fixed, lottery, flt, ivr, want, toxt_tab, toxt_n, shards, slots, columns,
                  rank[:n], species[:n])
            visit += (np.flatnonzero(rank[:n] == VISIT) + first).tolist()
            if one_per_species:
                _best_per_species(rank[:n], species[:n], best)
            else:
                part = rank[:n]
                if n > limit:
                    part = np.partition(part, limit)[:limit]
                kept = np.sort(np.concatenate([kept, part[part != NO_MATCH]]))[:limit]
            if progress:
                progress(first + n)
    if one_per_species:
        kept = best[best != NO_MATCH]
    seeds = (kept & 0xFFFFFFFF) if len(kept) else kept
    return sorted({(int(s) - start) & 0xFFFFFFFF for s in seeds} | set(visit))


def warm() -> None:
    """Loads the scan (or compiles it, once per machine without the packed app's cache) before the
    first search needs it."""
    if njit is not None:
        context = {"version": "violet", "map_name": "paldea", "progress": "6star", "content": "black"}
        offsets(0, 2, context, "overall", True, 1, False)
        offsets(0, 2, context, "overall", True, 1, True)

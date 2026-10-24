"""Bounded offline search and calibration. Indices are RNG advances, never VBlank frames."""
from dataclasses import asdict, dataclass

from .compat import backend, predict

BUILD_CODES = ("BPRE", "BPGE", "BPRF", "BPGF")
ENCOUNTERS = ("scripted", "mewtwo", "articuno", "zapdos", "moltres", "snorlax")
IV_ORDER = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")


def bounded(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def validate_ivs(ivs):
    if len(ivs) != 6:
        raise ValueError("Exactly six IVs are required in HP, Atk, Def, SpA, SpD, Spe order")
    for value in ivs:
        bounded(value, 0, 31, "IV")


def context(build, encounter):
    if build not in BUILD_CODES or encounter not in ENCOUNTERS:
        raise ValueError("Unsupported cartridge or encounter label")
    return {"build": build, "encounter": encounter, "profile_verified": False,
            "live_synchronized": False, "auto_a_available": False, "iv_order": IV_ORDER}


@dataclass(frozen=True)
class Criteria:
    shiny: bool = True
    nature: int | None = None
    pid: int | None = None
    iv_min: tuple = (0, 0, 0, 0, 0, 0)
    iv_max: tuple = (31, 31, 31, 31, 31, 31)

    def __post_init__(self):
        if type(self.shiny) is not bool:
            raise ValueError("shiny must be boolean")
        if self.nature is not None:
            bounded(self.nature, 0, 24, "nature")
        if self.pid is not None:
            bounded(self.pid, 0, 0xFFFFFFFF, "PID")
        validate_ivs(self.iv_min)
        validate_ivs(self.iv_max)
        if any(minimum > maximum for minimum, maximum in zip(self.iv_min, self.iv_max)):
            raise ValueError("Each minimum IV must be no greater than its maximum IV")

    def matches(self, mon):
        return ((not self.shiny or mon["shiny"])
                and (self.nature is None or self.nature == mon["nature"])
                and (self.pid is None or self.pid == mon["personality"])
                and all(minimum <= actual <= maximum
                        for actual, minimum, maximum in zip(mon["ivs"], self.iv_min, self.iv_max)))


def search(seed, tid, sid, *, build="BPRE", encounter="scripted", method=1, advances=100000,
           start=0, max_results=10, criteria=None, offset=None, progress=None, cancel=None):
    meta = context(build, encounter)
    bounded(seed, 0, 0xFFFFFFFF, "seed")
    bounded(tid, 0, 65535, "TID")
    bounded(sid, 0, 65535, "SID")
    bounded(advances, 1, 10_000_000, "candidate count")
    bounded(start, 0, 0xFFFFFFFF, "start index")
    bounded(max_results, 1, 1000, "result limit")
    if start + advances > 0x100000000:
        raise ValueError("Search must not wrap the 32-bit index")
    if type(method) is not int or method not in (1, 2, 4):
        raise ValueError("method must be 1, 2 or 4")
    if offset is not None:
        bounded(offset, 0, 1_000_000, "offset in RNG advances")
    if progress is not None and not callable(progress):
        raise ValueError("progress must be callable")
    if cancel is not None and not callable(cancel):
        raise ValueError("cancel must be callable")
    criteria = criteria or Criteria()
    lcg, _ = backend()
    state = lcg.advance(seed, start)
    hits = []
    tested = 0
    reason = "range_exhausted"
    for index in range(start, start + advances):
        if cancel and cancel():
            reason = "cancelled"
            break
        mon = predict(state, tid, sid, method)
        tested += 1
        if criteria.matches(mon):
            actionable = offset is not None and index >= offset
            hits.append({"predicted_generation_seed": state, "predicted_generation_index": index,
                         "pid": mon["personality"], "nature": mon["nature"],
                         "nature_name": mon["nature_name"], "ivs": mon["ivs"],
                         "shiny": mon["shiny"], "shiny_value": mon["shiny_value"],
                         "trigger_seed": lcg.advance(seed, index - offset) if actionable else None,
                         "trigger_index": index - offset if actionable else None,
                         "trigger_status": ("predicted_only" if actionable else
                                            "offset_missing" if offset is None else "already_passed")})
            if len(hits) >= max_results:
                reason = "result_limit"
                break
        if progress and tested % 4096 == 0:
            progress(tested, advances)
        state = lcg.step(state)
    if progress:
        progress(tested, advances)
    return {"schema": 1, "kind": "offline_search", **meta, "seed": seed, "tid": tid, "sid": sid,
            "method": method, "seed_boundary": "before_first_pid_draw", "start": start,
            "requested_candidates": advances, "candidates_tested": tested, "stop_reason": reason,
            "criteria": asdict(criteria), "offset_advances": offset, "targets": hits}


def calibrate(hit_seed, pid, ivs, *, build="BPRE", encounter="scripted", max_offset=4096,
              hit_boundary="unspecified"):
    meta = context(build, encounter)
    bounded(hit_seed, 0, 0xFFFFFFFF, "HIT seed")
    bounded(pid, 0, 0xFFFFFFFF, "PID")
    bounded(max_offset, 0, 1_000_000, "maximum plausible offset")
    validate_ivs(ivs)
    if hit_boundary not in ("unspecified", "post-vblank"):
        raise ValueError("Unknown HIT sampling boundary")
    lcg, _ = backend()
    hp, atk, defense, spa, spd, speed = ivs
    recovered = lcg.recover_wild_state(pid, (hp, atk, defense, speed, spa, spd), max_gap=1)
    placements = {(0, 0): 1, (1, 0): 2, (0, 1): 4}
    candidates = []
    for candidate in recovered:
        method = placements.get((candidate["gap"], candidate["iv_gap"]))
        if (method is None or candidate["order"] != "low-half first"
                or candidate["iv_order"] != "HP/ATK/DEF first"):
            continue
        distance = lcg.distance(hit_seed, candidate["before"])
        if distance <= max_offset:
            candidates.append({"generation_seed": candidate["before"], "method": method,
                               "offset_advances": distance})
    return {"schema": 1, "kind": "calibration_sample", **meta,
            "hit_seed": hit_seed, "pid": pid, "ivs": tuple(ivs), "max_offset": max_offset,
            "hit_boundary": hit_boundary,
            "generation_boundary": "before_first_pid_draw", "candidates": candidates,
            "result": "unique" if len(candidates) == 1 else "ambiguous" if candidates else "no_match"}

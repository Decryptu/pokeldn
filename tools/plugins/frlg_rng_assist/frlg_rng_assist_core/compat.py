"""The only dependency on PokeLDN's *internal*, non-stable RNG modules.

The plugin UI uses public API 1.8. These math imports are deliberately isolated and checked;
they are not advertised by PokeLDN as a stable plugin API. No payload builder is imported.
"""
from functools import lru_cache


@lru_cache(maxsize=1)
def backend():
    try:
        from pokeldn.frlg.rom import lcg, rng_countdown
        required = ("step", "advance", "distance", "draws", "recover_wild_state")
        if not all(callable(getattr(lcg, name, None)) for name in required):
            raise ValueError("LCG API is incomplete")
        if not callable(getattr(rng_countdown, "_mon_from", None)):
            raise ValueError("Method 1 predictor is missing")
        if lcg.step(0) != 0x6073 or lcg.step(0x6073) != 0xE97E7B6A:
            raise ValueError("unexpected LCG constants")
        check = rng_countdown._mon_from(0, 0, 0)
        if check["personality"] != 0xE97E0000 or len(check["ivs"]) != 6:
            raise ValueError("unexpected PID model")
        if len(rng_countdown.NATURE_NAMES) != 25:
            raise ValueError("unexpected nature table")
    except (ImportError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("This PokeLDN RNG backend is incompatible; no console action was taken.") from exc
    return lcg, rng_countdown


def predict(seed, tid, sid, method):
    """Use the upstream Method 1 predictor, adding explicit Method 2/4 IV placement only."""
    lcg, countdown = backend()
    mon = dict(countdown._mon_from(seed, tid, sid))
    if method != 1:
        draws, _ = lcg.draws(seed, 5)
        first, second = (draws[3], draws[4]) if method == 2 else (draws[2], draws[4])
        mon["ivs"] = (first & 31, first >> 5 & 31, first >> 10 & 31,
                      second & 31, second >> 5 & 31, second >> 10 & 31)
    # Upstream stored order is HP, Atk, Def, Spe, SpA, SpD; public plugin order is the summary screen.
    hp, atk, defense, speed, spa, spd = mon["ivs"]
    mon["ivs"] = (hp, atk, defense, spa, spd, speed)
    mon["iv_total"] = sum(mon["ivs"])
    mon["nature_name"] = countdown.NATURE_NAMES[mon["nature"]]
    return mon

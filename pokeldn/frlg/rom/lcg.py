"""The game's RNG as arithmetic: where a state came from, and how far. docs/frlg_rng.md.

`Random` is a full-period affine map on 32 bits [decomp:include/random.h:18]: a distance always
exists, so one is evidence only when it is small.
"""

RAND_MULT = 1103515245                  # 0x41C64E6D [decomp:include/random.h:18]
RAND_ADD = 24691                        # ISO_RANDOMIZE1's addend [:19]
MASK = 0xFFFFFFFF
STATES = 1 << 32
SEED_LIMIT = 1 << 16                    # SeedRng takes a u16 [decomp:src/random.c:15]

_INV_MULT = pow(RAND_MULT, -1, STATES)  # RAND_MULT is odd, so it is invertible mod 2**32


def step(value):
    return (value * RAND_MULT + RAND_ADD) & MASK


def unstep(value):
    return ((value - RAND_ADD) * _INV_MULT) & MASK


def draw(value):
    """(the u16 Random() returns, the state it leaves) from the state before the call."""
    value = step(value)
    return value >> 16, value


def draws(value, count):
    """(the `count` u16s Random() returns, the state it leaves) from the state before the first."""
    out = []
    for _ in range(int(count)):
        got, value = draw(value)
        out.append(got)
    return out, value


# f(x) = a*x + c is closed under composition, so f**n is one (a, c) pair reachable by squaring.

def _compose(first, second):
    """The pair for `first` then `second`."""
    fa, fc = first
    sa, sc = second
    return ((sa * fa) & MASK, (sa * fc + sc) & MASK)


def _power(pair, n):
    result = (1, 0)
    while n:
        if n & 1:
            result = _compose(result, pair)
        pair = _compose(pair, pair)
        n >>= 1
    return result


def _invert(pair):
    a, c = pair
    inverse = pow(a, -1, STATES)
    return (inverse, (-inverse * c) & MASK)


_STEP = (RAND_MULT, RAND_ADD)


def advance(value, n):
    """`n` may be negative and is taken modulo the period."""
    a, c = _power(_STEP, int(n) % STATES)
    return (a * (value & MASK) + c) & MASK


_GIANT = 1 << 16                        # 2**16 baby steps and at most 2**16 giant steps


def distance(start, target):
    """Turns from `start` to `target`, 0 <= d < 2**32, by baby-step/giant-step; never fails."""
    start, target = start & MASK, target & MASK
    seen = {}
    value = start
    for baby in range(_GIANT):          # f**baby(start) for every baby step, first wins
        if value not in seen:
            seen[value] = baby
        value = step(value)
    back = _invert(_power(_STEP, _GIANT))
    value = target
    for giant in range(_GIANT):
        baby = seen.get(value)
        if baby is not None:
            return giant * _GIANT + baby
        value = (back[0] * value + back[1]) & MASK
    raise AssertionError("the LCG is a permutation of 2**32 states; a distance always exists")


# Reading a state back to its seed.

def predecessors(value, limit=1 << 20, count=1):
    """[(steps, seed), ...]: states under 0x10000 (SeedRng [decomp:src/random.c:15]) within `limit`
    turns BEFORE `value`. One turns up every ~65536 steps by chance; a candidate is evidence
    only when `steps` matches an independently measured elapsed time."""
    found = []
    current = value & MASK
    for steps in range(1, int(limit) + 1):
        current = unstep(current)
        if current < SEED_LIMIT:
            found.append((steps, current))
            if len(found) >= int(count):
                break
    return found


def seconds(turns, per_frame=2, fps=59.7275):
    """`turns` as seconds. per_frame = 2 is measured at the Mystery Gift link menu only."""
    return turns / float(per_frame) / float(fps)


# A wild Pokemon is four draws: personality (d1, d2), HP/ATK/DEF (d3), SPEED/SPATK/SPDEF (d4)
# [decomp:src/wild_encounter.c:233]. docs/frlg_rng.md, Reading a Pokemon back.

MAX_IV_MASK = 31                        # [decomp:include/constants/pokemon.h]
NUM_NATURES = 25


def iv_word(first, second, third):
    for value in (first, second, third):
        if not 0 <= value <= MAX_IV_MASK:
            raise ValueError(f"an IV is 0..{MAX_IV_MASK}, got {value}")
    return (first & 31) | ((second & 31) << 5) | ((third & 31) << 10)


def nature_of(personality):
    return (personality & MASK) % NUM_NATURES


def recover_wild_state(personality, ivs, max_gap=32):
    """[{...}]: the RNG states that would build this Pokemon; `ivs` in stored order (hp..spdef).

    Both half-orders, both IV orders, and a stray draw before (`gap`, Method 2) or between (`iv_gap`,
    Method 4) the IV draws are searched [docs/frlg_rng.md]. `before` is gRngValue before the PID draw."""
    personality &= MASK
    if len(ivs) != 6:
        raise ValueError(f"six IVs, got {len(ivs)}")
    first_word = iv_word(ivs[0], ivs[1], ivs[2])
    second_word = iv_word(ivs[3], ivs[4], ivs[5])
    orders = (("low-half first", personality & 0xFFFF, personality >> 16),
              ("high-half first", personality >> 16, personality & 0xFFFF))
    iv_orders = (("HP/ATK/DEF first", first_word, second_word),
                 ("SPEED/SPATK/SPDEF first", second_word, first_word))
    found = []
    for order, first, second in orders:
        for low in range(1 << 16):
            state = (first << 16) | low
            after_personality = step(state)
            if after_personality >> 16 != second:
                continue
            # The PID pair leaves ~1 candidate in 2**16, so the gap loops run over a handful of
            # states.
            walked = after_personality
            for gap in range(int(max_gap) + 1):
                one = step(walked)
                between = one
                for iv_gap in range(int(max_gap) + 1):
                    two = step(between)
                    for iv_order, early, late in iv_orders:
                        if (one >> 16) & 0x7FFF == early and (two >> 16) & 0x7FFF == late:
                            found.append({"before": unstep(state), "after": two, "order": order,
                                          "iv_order": iv_order, "gap": gap, "iv_gap": iv_gap,
                                          "nature": nature_of(personality)})
                    between = step(between)
                walked = step(walked)
    return found


def nature_draw_before(state, nature, limit=4096):
    """Turns before `state` that `Random() % NUM_NATURES` chose `nature`. CreateMonWithNature
    rejects whole pairs of draws, so only even offsets count."""
    current = state & MASK
    for steps in range(1, int(limit) + 1):
        current = unstep(current)
        if steps % 2 == 0 and (step(current) >> 16) % NUM_NATURES == nature:
            return steps
    return None

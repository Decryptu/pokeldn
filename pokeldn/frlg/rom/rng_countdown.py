"""When to press A, and how far off the last press was.

The state advances exactly 2 turns per frame and the mon is the next four draws after the state the
script prints, so a press lands on `advance(S, 2k)` and a miss is a signed frame count. docs/frlg_rng.md.
"""

from pokeldn.frlg.rom import lcg

SHINY_ODDS = 8
FPS = 59.7275                   # for a spoken countdown only
TURNS_PER_FRAME = 2             # measured [docs/frlg_rng.md]

# Index == `personality % NUM_NATURES` [decomp:include/constants/pokemon.h]; native_script parses
# criteria against this list.
NATURE_NAMES = ("Hardy Lonely Brave Adamant Naughty Bold Docile Relaxed Impish Lax Timid Hasty "
                "Serious Jolly Naive Modest Mild Quiet Bashful Rash Calm Gentle Sassy Careful "
                "Quirky").split()
NUM_NATURES = len(NATURE_NAMES)         # 25 [decomp:include/constants/pokemon.h:163]


def _mon_from(state, tid, sid):
    """-> the mon `setwildbattle` would build from `state`: the next four draws, in order."""
    (d1, d2, d3, d4), _end = lcg.draws(state, 4)
    personality = d1 | (d2 << 16)               # low half first, at this call site
    ivs = (d3 & 31, (d3 >> 5) & 31, (d3 >> 10) & 31,
           d4 & 31, (d4 >> 5) & 31, (d4 >> 10) & 31)
    shiny_value = tid ^ sid ^ (personality >> 16) ^ (personality & 0xFFFF)
    return {"state": state, "personality": personality, "ivs": ivs, "iv_total": sum(ivs),
            "nature": personality % 25, "shiny_value": shiny_value,
            "shiny": shiny_value < SHINY_ODDS}


def scan(state, tid, sid, frames=20000, want=None):
    """-> every frame within `frames` whose press would produce a shiny, narrowed by `want(mon)`."""
    out, current = [], int(state)
    for k in range(int(frames) + 1):
        mon = _mon_from(current, tid, sid)
        if mon["shiny"] and (want is None or want(mon)):
            out.append({**mon, "frames": k, "turns": k * TURNS_PER_FRAME,
                        "seconds": k / FPS})
        current = lcg.advance(current, TURNS_PER_FRAME)
    return out


def press_error(target, actual):
    """-> how far a press missed, signed (positive = late), in turns and frames. A miss past half
    the period reads negative; a miss of millions of turns is a different seed."""
    turns = lcg.distance(int(target), int(actual))
    if turns > lcg.STATES // 2:
        turns -= lcg.STATES
    return {"turns": turns, "frames": turns / TURNS_PER_FRAME,
            "on_target": turns == 0,
            "usable": abs(turns) < 10 ** 6}


def describe(state, tid, sid, frames=20000, limit=5):
    natures = NATURE_NAMES
    hits = scan(state, tid, sid, frames)
    lines = [f"from 0x{int(state):08X}, TID {tid} / SID {sid}",
             f"scanning {frames:,} frames ahead ({frames / FPS:,.0f} s at 59.7275 Hz)",
             f"{len(hits)} shiny frame(s); ~1 in {SHINY_ODDS and 65536 // SHINY_ODDS:,} presses"]
    if not hits:
        lines.append("  none in range - scan further ahead")
    for hit in hits[:limit]:
        lines.append(
            f"  +{hit['frames']:>6,} frames  ({hit['seconds']:>6.1f} s)  "
            f"PID 0x{hit['personality']:08X}  {natures[hit['nature']]:<8} "
            f"IVs {'/'.join(str(v) for v in hit['ivs'])}  (total {hit['iv_total']})")
    if len(hits) > limit:
        lines.append(f"  ... and {len(hits) - limit} more")
    lines.append("PRESS A SO THAT THE SCRIPT READS ON THAT FRAME. A miss costs one A press: read"
                 " the BEFORE it prints and pass both to press_error.")
    return lines


def main(argv=None):
    import argparse
    from pokeldn.frlg.rom import rng_script
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("low", type=lambda v: int(v, 0), help="RNG LO, as the NPC printed it")
    parser.add_argument("high", type=lambda v: int(v, 0), help="RNG HI, as the NPC printed it")
    parser.add_argument("--tid", type=int, default=12345)
    parser.add_argument("--sid", type=int, default=2791)
    parser.add_argument("--frames", type=int, default=20000)
    parser.add_argument("--target-frames", type=int, default=None, metavar="N",
                        help="not a hunt, a CALIBRATION: print the state N frames ahead and when "
                             "to press, so the miss can be measured against a target we chose")
    parser.add_argument("--aimed-at", type=lambda v: int(v, 0), default=None, metavar="STATE",
                        help="the state the last press was aiming at: report the miss instead")
    args = parser.parse_args(argv)
    state = rng_script.seed_from_printed(args.low, args.high)
    if args.target_frames is not None:
        target = lcg.advance(state, TURNS_PER_FRAME * args.target_frames)
        print(f"read     0x{state:08X}")
        print(f"target   0x{target:08X}   {args.target_frames:,} frames ahead")
        print(f"press A  {args.target_frames / FPS:.2f} s after the press that gave the reading")
        print("  then:  --aimed-at 0x%08X <the new LO> <the new HI>" % target)
        return 0
    if args.aimed_at is not None:
        miss = press_error(args.aimed_at, state)
        print(f"aimed at 0x{args.aimed_at:08X}, read 0x{state:08X}")
        if not miss["usable"]:
            print("  that is not a miss, it is a different seed - the game reseeded in between")
        else:
            print(f"  {miss['turns']:+,} turns = {miss['frames']:+,.1f} frames "
                  + ("(ON TARGET)" if miss["on_target"] else
                     "(LATE: press sooner)" if miss["turns"] > 0 else "(EARLY: press later)"))
        return 0
    for line in describe(state, args.tid, args.sid, args.frames):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

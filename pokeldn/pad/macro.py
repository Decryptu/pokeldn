"""Macro files (`.pokemacro`) and their compilation into the board's program [docs/hardware_pad.md,
Macros]. A macro is JSON; the board plays the compiled program on its own clock."""
import json
import struct
from dataclasses import dataclass, field

FORMAT = "pokeldn-macro"
VERSION = 1
EXTENSION = ".pokemacro"

BUTTONS = {
    "Y": 0x0001, "B": 0x0002, "A": 0x0004, "X": 0x0008, "L": 0x0010, "R": 0x0020,
    "ZL": 0x0040, "ZR": 0x0080, "MINUS": 0x0100, "PLUS": 0x0200, "LSTICK": 0x0400,
    "RSTICK": 0x0800, "HOME": 0x1000, "CAPTURE": 0x2000,
}
DPAD = {"UP": 0, "UPRIGHT": 1, "RIGHT": 2, "DOWNRIGHT": 3, "DOWN": 4, "DOWNLEFT": 5, "LEFT": 6,
        "UPLEFT": 7}
CENTRE = 8
KEYS = (*BUTTONS, *DPAD)

MAX_ENTRIES = 8192      # firmware/pad/main/pad.c MAX_ENTRIES
MAX_MS = 3_600_000      # one step lasts at most an hour
MAX_DEPTH = 8


class MacroError(ValueError):
    pass


def report(buttons=0, hat=CENTRE, lx=128, ly=128, rx=128, ry=128) -> bytes:
    return struct.pack("<HBBBBBB", buttons, hat, lx, ly, rx, ry, 0)


NEUTRAL = report()


def axis(value: float) -> int:
    """-1.0 .. 1.0 to the report's 0 .. 255, 128 at rest."""
    return max(0, min(255, round(128 + value * 127.5)))


def state(keys=(), left=(0.0, 0.0), right=(0.0, 0.0)) -> bytes:
    """Keys held and stick positions (x right, y up, each -1.0 .. 1.0) as one report."""
    buttons, dpad = 0, set()
    for key in keys:
        key = key.upper()
        if key in BUTTONS:
            buttons |= BUTTONS[key]
        elif key in DPAD:
            dpad.add(key)
        else:
            raise MacroError(f"unknown button {key!r}")
    return report(buttons, hat_of(dpad), axis(left[0]), axis(-left[1]), axis(right[0]), axis(-right[1]))


def hat_of(dpad) -> int:
    up, down = "UP" in dpad, "DOWN" in dpad
    left, right = "LEFT" in dpad, "RIGHT" in dpad
    for name in ("UPRIGHT", "DOWNRIGHT", "DOWNLEFT", "UPLEFT"):
        if name in dpad:
            return DPAD[name]
    name = ("UP" if up and not down else "DOWN" if down and not up else "") + \
           ("RIGHT" if right and not left else "LEFT" if left and not right else "")
    return DPAD.get(name, CENTRE)


@dataclass
class Macro:
    name: str = "New macro"
    description: str = ""
    author: str = ""
    game: str = ""
    press_ms: int = 100        # how long a step without "ms" holds its input
    gap_ms: int = 150          # the pause after a step without "after"
    setup: list = field(default_factory=list)
    loop: list = field(default_factory=list)
    loops: int = 1             # times the loop part runs; 0 = until stopped

    def to_json(self) -> dict:
        return {"format": FORMAT, "version": VERSION, "name": self.name,
                "description": self.description, "author": self.author, "game": self.game,
                "press_ms": self.press_ms, "gap_ms": self.gap_ms, "setup": self.setup,
                "loop": self.loop, "loops": self.loops}

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n"


def _ms(value, what, low=0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= MAX_MS:
        raise MacroError(f"{what} must be a number of milliseconds from {low} to {MAX_MS}")
    return int(value)


def _stick(value, what):
    if not (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and -1 <= v <= 1 for v in value)):
        raise MacroError(f"{what} must be [x, y], each from -1 to 1")
    return float(value[0]), float(value[1])


def check_steps(steps, depth=0, where="steps"):
    if not isinstance(steps, list):
        raise MacroError(f"{where} must be a list")
    if depth > MAX_DEPTH:
        raise MacroError(f"repeats nest deeper than {MAX_DEPTH}")
    for n, step in enumerate(steps, 1):
        at = f"{where} {n}"
        if not isinstance(step, dict):
            raise MacroError(f"{at} must be an object")
        kinds = [k for k in ("press", "wait", "repeat") if k in step] or \
                (["press"] if "left" in step or "right" in step else [])
        if len(kinds) != 1:
            raise MacroError(f"{at} must have exactly one of press, wait, repeat")
        known = {"press": {"press", "left", "right", "ms", "after", "note"},
                 "wait": {"wait", "note"}, "repeat": {"repeat", "steps", "note"}}[kinds[0]]
        if extra := set(step) - known:
            raise MacroError(f"{at}: unknown field {sorted(extra)[0]!r}")
        if "note" in step and not isinstance(step["note"], str):
            raise MacroError(f"{at}: note must be text")
        if kinds[0] == "wait":
            _ms(step["wait"], f"{at} wait")
        elif kinds[0] == "repeat":
            count = step["repeat"]
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10_000:
                raise MacroError(f"{at}: repeat must be a whole number from 1 to 10000")
            check_steps(step.get("steps"), depth + 1, f"{at} steps")
        else:
            keys = step.get("press", [])
            keys = [keys] if isinstance(keys, str) else keys
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise MacroError(f"{at}: press must be a button name or a list of them")
            state(keys, *(_stick(step[s], f"{at} {s}") for s in ("left", "right") if s in step))
            if "ms" in step:
                _ms(step["ms"], f"{at} ms", 1)
            if "after" in step:
                _ms(step["after"], f"{at} after")


def loads(text: str) -> Macro:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MacroError(f"not a macro file: {e}") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise MacroError("not a macro file")
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        raise MacroError("this macro needs a newer version of the app")
    m = Macro()
    for key in ("name", "description", "author", "game"):
        if key in data:
            if not isinstance(data[key], str):
                raise MacroError(f"{key} must be text")
            setattr(m, key, data[key])
    m.press_ms = _ms(data.get("press_ms", m.press_ms), "press_ms", 1)
    m.gap_ms = _ms(data.get("gap_ms", m.gap_ms), "gap_ms")
    m.setup, m.loop = data.get("setup", []), data.get("loop", [])
    check_steps(m.setup, where="setup step")
    check_steps(m.loop, where="loop step")
    loops = data.get("loops", 1)
    if isinstance(loops, bool) or not isinstance(loops, int) or not 0 <= loops <= 1_000_000:
        raise MacroError("loops must be a whole number from 0 (until stopped) to 1000000")
    m.loops = loops
    return m


def _expand(steps, macro, out):
    for step in steps:
        if "wait" in step:
            out.append((NEUTRAL, int(step["wait"])))
        elif "repeat" in step:
            for _ in range(step["repeat"]):
                _expand(step["steps"], macro, out)
                if len(out) > MAX_ENTRIES:
                    raise MacroError(f"the macro is longer than the board's {MAX_ENTRIES} steps")
        else:
            keys = step.get("press", [])
            keys = [keys] if isinstance(keys, str) else keys
            out.append((state(keys, step.get("left", (0, 0)), step.get("right", (0, 0))),
                        int(step.get("ms", macro.press_ms))))
            out.append((NEUTRAL, int(step.get("after", macro.gap_ms))))


def _merge(entries):
    """Joins neighbours holding the same report, drops empty holds, splits holds over 65535 ms."""
    merged = []
    for r, ms in entries:
        if ms == 0:
            continue
        if merged and merged[-1][0] == r:
            merged[-1] = (r, merged[-1][1] + ms)
        else:
            merged.append((r, ms))
    out = []
    for r, ms in merged:
        while ms > 0xFFFF:
            out.append((r, 0xFFFF))
            ms -= 0xFFFF
        out.append((r, ms))
    return out


@dataclass(frozen=True)
class Program:
    entries: list           # (report, ms)
    loop_start: int
    loops: int

    @property
    def setup_ms(self) -> int:
        return sum(ms for _, ms in self.entries[:self.loop_start])

    @property
    def loop_ms(self) -> int:
        return sum(ms for _, ms in self.entries[self.loop_start:])


def compile_macro(macro: Macro) -> Program:
    setup, loop = [], []
    _expand(macro.setup, macro, setup)
    _expand(macro.loop, macro, loop)
    setup, loop = _merge(setup), _merge(loop)
    if loop and loop[-1][0] != NEUTRAL:
        loop.append((NEUTRAL, 1))
    entries = setup + loop
    if len(entries) > MAX_ENTRIES:
        raise MacroError(f"the macro is longer than the board's {MAX_ENTRIES} steps")
    if not entries:
        raise MacroError("the macro has no steps")
    return Program(entries, len(setup), macro.loops if loop else 1)


def encode_entry(r: bytes, ms: int) -> bytes:
    return r + struct.pack("<H", ms)

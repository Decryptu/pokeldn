"""Read-only/live-session helpers for the FRLG RNG Assist tools.

The plugin deliberately calls the host's existing buffer-script launcher instead of opening a
second radio implementation.  Keeping that boundary here makes the UI tools easy to test without
a console and makes a missing/newer host fail before any session is started.
"""
from __future__ import annotations

import json
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


PLUGIN_VERSION = "0.2.0"
RESIDENT_BASE = 0x0203FC00
DEFAULT_STATE = 0x0203FF80
STATE_SIZE = 64
BUILD_CODES = ("BPRE", "BPGE", "BPRF", "BPGF")
VERSION_FOR_BUILD = {
    "BPRE": "firered", "BPRF": "firered", "BPGE": "leafgreen", "BPGF": "leafgreen",
}
CONSOLE_FOR_BUILD = {"BPRE": "firered", "BPRF": "firered", "BPGE": "leafgreen", "BPGF": "leafgreen"}

STATE_FIELDS = (
    "current_seed", "current_index", "predicted_generation_seed", "predicted_generation_index",
    "trigger_seed", "trigger_index", "hit_seed", "hit_index", "hit_frame", "frame_counter",
    "target_pid", "target_nature", "candidates_tested", "flags", "mode", "display_bottom",
)
FLAG_NAMES = (
    (1, "initialized"), (2, "pending_a"), (4, "fired"), (8, "hit_locked"),
    (16, "armed"), (32, "target_found"), (64, "missed"),
)


def add_live_arguments(parser: argparse.ArgumentParser, *, output=True) -> None:
    """Add the small, shared live-session surface used by all four UI tools."""
    parser.add_argument("--build", choices=BUILD_CODES, default="BPRE")
    parser.add_argument(
        "--radio", default="", help="Optional PokeLDN radio override, for example esp32:COM8")
    parser.add_argument("--keys", help="Optional prod.keys path; normally supplied by PokeLDN")
    if output:
        parser.add_argument("--output", help="Capture/report path; defaults to the plugin library")


def build_info(code: str):
    """Return the host Build object after checking that the code is known."""
    code = str(code).upper()
    if code not in BUILD_CODES:
        raise ValueError(f"unsupported cartridge build {code!r}; use {', '.join(BUILD_CODES)}")
    try:
        from pokeldn.frlg.rom import builds
        return builds.resolve(code)
    except (ImportError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("this PokeLDN host does not expose the FRLG build table") from exc


def version_args(build: str) -> tuple[str, str]:
    build = str(build).upper()
    build_info(build)
    return VERSION_FOR_BUILD[build], CONSOLE_FOR_BUILD[build]


def validate_state_address(value: int) -> int:
    """Validate a 64-byte state location against the resident image and EWRAM bounds."""
    value = int(value)
    if value % 4 or not 0x0203FBB4 <= value or value + STATE_SIZE > 0x02040000:
        raise ValueError("state-address must be a 64-byte word-aligned slot in resident EWRAM")
    try:
        from pokeldn.frlg.rom.resident_stubs import STUBS
        code_end = RESIDENT_BASE + len(STUBS["rng-assist"][0])
    except (ImportError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "the installed PokeLDN host has no rng-assist resident runtime; update PokeLDN first"
        ) from exc
    code_start = RESIDENT_BASE
    if value < code_end and value + STATE_SIZE > code_start:
        raise ValueError("state-address overlaps the resident code image")
    return value


def timestamp_path(suffix: str, output: str | None = None) -> Path:
    """Choose an exclusive, player-visible capture path when the UI did not provide one."""
    if output:
        return Path(output).expanduser()
    try:
        from pokeldn.plugins import library_folder
        folder = library_folder("frlg-rng-assist")
    except (ImportError, LookupError) as exc:
        raise ValueError("Load FRLG RNG Assist first, or provide --output FILE") from exc
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return folder / f"{stamp}-{uuid4().hex[:8]}{suffix}"


def ensure_parent(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_json(value, output: str | None = None, *, suffix=".json") -> Path:
    path = ensure_parent(timestamp_path(suffix, output))
    # Reports are records; do not silently replace an earlier observation.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path


def host_common(build: str, *, keys: str | None = None) -> list[str]:
    """Arguments common to every live FRLG host session."""
    version, expected = version_args(build)
    result = ["--live", "--console-build", str(build).upper(), "--expect-console", expected,
              "--version", version]
    if keys:
        result.extend(("--keys", str(Path(keys).expanduser())))
    return result


def run_host(arguments, *, radio: str | None = None) -> int:
    """Run the existing host launcher in-process and turn argparse exits into a return code."""
    try:
        from bin import frlg_mg_host
    except ImportError as exc:
        raise RuntimeError("this PokeLDN host does not include bin.frlg_mg_host") from exc
    old_radio = os.environ.get("POKELDN_RADIO")
    if radio:
        os.environ["POKELDN_RADIO"] = radio
    try:
        try:
            result = frlg_mg_host.main(list(arguments))
        except SystemExit as exc:
            result = exc.code
    finally:
        if radio:
            if old_radio is None:
                os.environ.pop("POKELDN_RADIO", None)
            else:
                os.environ["POKELDN_RADIO"] = old_radio
    if result is None:
        return 0
    try:
        return int(result)
    except (TypeError, ValueError):
        return 2


def read_words(data: bytes, count: int) -> tuple[int, ...]:
    data = bytes(data)
    if len(data) < count * 4:
        raise ValueError(f"expected at least {count * 4} bytes, got {len(data)}")
    return tuple(int.from_bytes(data[i:i + 4], "little") for i in range(0, count * 4, 4))


def decode_state(data: bytes) -> dict:
    """Decode the 64-byte resident state without assuming that flags are mutually exclusive."""
    words = read_words(data, len(STATE_FIELDS))
    result = dict(zip(STATE_FIELDS, words))
    result["flags_names"] = [name for bit, name in FLAG_NAMES if result["flags"] & bit]
    result["state_size"] = len(bytes(data))
    return result


def read_trace(data: bytes) -> dict:
    try:
        from pokeldn.frlg.rom import buffer_script
        return buffer_script.read_rng_trace(data)
    except (ImportError, AttributeError, ValueError) as exc:
        raise RuntimeError("this PokeLDN host cannot decode rng-trace output") from exc


def read_chain(data: bytes) -> dict:
    try:
        from pokeldn.frlg.rom import buffer_script
        return buffer_script.read_call_chain(data)
    except (ImportError, AttributeError, ValueError) as exc:
        raise RuntimeError("this PokeLDN host cannot decode call-chain output") from exc


def resident_addresses() -> dict[str, int]:
    """Return external parameter addresses from the generated resident stub table."""
    try:
        from pokeldn.frlg.rom.resident_stubs import STUBS
        symbols = STUBS["rng-assist"][2]
    except (ImportError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "the installed PokeLDN host has no rng-assist resident runtime; update PokeLDN first"
        ) from exc
    names = ("p_auto_a", "p_trigger_index", "p_offset", "p_target_pid", "p_target_nature",
             "p_mode", "p_state")
    try:
        return {name: RESIDENT_BASE + int(symbols[name]) for name in names}
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("the installed rng-assist runtime has incomplete parameter symbols") from exc


def print_state(state: dict) -> None:
    print("RNG Assist resident state (read-only):")
    for key in STATE_FIELDS:
        value = state[key]
        if key.endswith(("seed", "pid")):
            print(f"  {key}: 0x{value:08X}")
        else:
            print(f"  {key}: {value}")
    names = ", ".join(state["flags_names"]) or "none"
    print(f"  flags: {names}")

import os
import random
import shlex
import time
from functools import cache

from gui.catalog import Field, Tool
from gui.introspect import flags_of


@cache
def accepted(script: str) -> frozenset[str]:
    return frozenset(f.option for f in flags_of(script))


def value_of(field: Field, values: dict):
    return values.get(field.key, field.default)


def applies(field: Field, tool: Tool, values: dict) -> bool:
    if not field.when:
        return True
    flag, wanted = field.when
    other = next(f for f in tool.fields if f.key == flag)
    return str(value_of(other, values)) == wanted


def _args(field: Field, value, work_dir: str) -> list[str]:
    flags = field.flag if isinstance(field.flag, tuple) else (field.flag,)
    if field.kind == "switch":
        return list(flags) if bool(value) != field.invert else []
    if value in ("", None, []):
        return list(field.unset)
    if field.kind == "argsfile":
        with open(os.path.join(work_dir, value)) as f:
            return shlex.split(f.read())
    items = list(value) if field.kind == "files" else \
        str(value).split() if field.kind == "multi" else [str(value)]
    if not field.flag:
        return items
    return [a for item in items for flag in flags for a in (flag, item)]


def build(tool: Tool, values: dict, extra: dict, settings, stamp: str | None = None) -> list[str]:
    """The entry point's argument list: tested flags, the tool's fields, then the All tab's."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    args = [a.replace("{src_var}", f"0x{random.getrandbits(32):08x}") for a in tool.fixed]
    for field in tool.fields:
        if applies(field, tool, values):
            value = value_of(field, values)
            if field.kind == "save" and isinstance(value, str):
                value = value.replace("{stamp}", stamp)
            args += _args(field, value, settings.work_dir)
    known = accepted(tool.script)
    used = set(args)
    if "--keys" in known and "--keys" not in used:
        args += ["--keys", os.path.expanduser(settings.keys)]
    if "--capture" in known and "--capture" not in used and settings.capture:
        args += ["--capture", f"captures/{tool.key}-{stamp}.jsonl"]
    for flag, value in extra.items():
        args += ([flag] if value is True else [] if value in (False, "", None) else [flag, str(value)])
    return args


def needed_files(tool: Tool, values: dict) -> list[tuple[str, str]]:
    """(label, path relative to the work folder) of every input file the run reads."""
    files = [(f.label, value_of(f, values)) for f in tool.fields
             if f.kind in ("file", "dir", "argsfile") and applies(f, tool, values)
             and (f.required or value_of(f, values))]
    files += [(os.path.basename(p), p) for p in tool.needs]
    return [(label, p) for label, p in files if isinstance(p, str) and p and p != "echo"]


def output_dirs(args: list[str]) -> set[str]:
    return {os.path.dirname(a) for a in args if a.startswith(("received/", "captures/", "scratchpad/"))
            and os.path.dirname(a)}

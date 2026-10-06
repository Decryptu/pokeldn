import os
import random
import time
from functools import cache

from pokeldn.app import gift_builder
from pokeldn.app.catalog import Field, Tool
from pokeldn.app.introspect import flags_of
from pokeldn.lgpe.session import code_picks


@cache
def accepted(script: str) -> frozenset[str]:
    return frozenset(f.option for f in flags_of(script))


def value_of(field: Field, values: dict):
    if field.kind == "builder" and field.key not in values:
        return values.get("--record", field.default)
    return values.get(field.key, field.default)


def applies(field: Field, tool: Tool, values: dict) -> bool:
    if field.unless:
        source = next(f for f in tool.fields if f.key == field.unless)
        if value_of(source, values):
            return False
    if not field.when:
        return True
    flag, wanted = field.when
    other = next(f for f in tool.fields if f.key == flag)
    return str(value_of(other, values)) == wanted


def offers(value) -> list[dict]:
    """A pokemon field holds what the builder made, {"file": path, "summary": ..., ...}, or a list
    of them, one per trade in the queue."""
    if isinstance(value, list):
        return [v if isinstance(v, dict) else {} for v in value]
    return [value] if isinstance(value, dict) else []


def _args(field: Field, value, tool: Tool) -> list[str]:
    if field.kind == "builder":
        return gift_builder.args(tool, value)
    flags = field.flag if isinstance(field.flag, tuple) else (field.flag,)
    if field.kind == "switch":
        on = bool(value) != field.invert
        return [flags[0], field.template] if (on and field.template) else list(flags) if on else []
    if field.kind == "pokemon":
        files = [f for v in offers(value)[:field.queue] if (f := v.get("file", ""))]
        if not files:
            return list(field.unset)
        out = files if not field.flag else [a for n, f in enumerate(files)
                                             for a in ((field.more if n and field.more else flags[0]), f)]
        return out + ([field.count, str(len(files))] if field.count else [])
    if value in ("", None):
        return list(field.unset)
    items = str(value).split() if field.kind == "multi" else [field.template.format(value) if field.template
                                                               else str(value)]
    if not field.flag:
        return items
    return [a for item in items for flag in flags for a in (flag, item)]


def build(tool: Tool, values: dict, extra: dict, settings, stamp: str | None = None) -> list[str]:
    """The entry point's argument list: tested flags, the tool's fields, then the All tab's."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    game = tool.key.split("-")[0]
    tid, sid = settings.ids(game)
    tokens = {"{received}": os.path.expanduser(settings.received), "{stamp}": stamp,
              "{src_var}": f"0x{random.getrandbits(32):08x}",
              "{ot}": settings.name(game), "{tid}": str(tid), "{sid}": str(sid),
              "{language}": str(settings.language)}
    args = []
    for arg in tool.fixed:
        for token, value in tokens.items():
            arg = arg.replace(token, value)
        args.append(arg)
    for field in tool.fields:
        if applies(field, tool, values):
            items = _args(field, value_of(field, values), tool)
            if field.kind == "builder":     # a backup's file is named after the run
                items = [item.replace("{stamp}", stamp) for item in items]
            args += items
    known = accepted(tool.script)
    if "--keys" in known and "--keys" not in args:
        args += ["--keys", os.path.expanduser(settings.keys)]
    if "--capture" in known and settings.capture:
        args += ["--capture", f"captures/{tool.key}-{stamp}.jsonl"]
    for flag, value in extra.items():
        args += ([flag] if value is True else [] if value in (False, "", None) else [flag, str(value)])
    return args


def limit_error(field: Field, value) -> str:
    """Why a NAME=VALUE field's value is refused, or ""."""
    for item in str(value or "").split():
        name, _, number = item.partition("=")
        for limit_name, highest, why in field.limits:
            if name == limit_name:
                try:
                    if int(number, 0) > highest:
                        return why
                except ValueError:
                    return f"{name} must be an integer."
    return ""


def problems(tool: Tool, values: dict) -> list[str]:
    errors = [error for f in tool.fields if applies(f, tool, values)
            if (error := limit_error(f, value_of(f, values)) if f.limits else code_error(f, value_of(f, values)))]
    for field in tool.fields:
        if field.kind == "builder" and (error := gift_builder.problem(tool, value_of(field, values))):
            errors.append(error)
    return errors


def prepare(tool: Tool, values: dict) -> None:
    """Write what the arguments name but no field holds yet: a built gift's file."""
    for field in tool.fields:
        if field.kind == "builder":
            gift_builder.prepare(tool, value_of(field, values))


def code_error(field: Field, value) -> str:
    """A console code is eight digits, or empty where the field allows none; a Let's Go link code must
    name three picker Pokemon. Either partial one would host under another code."""
    if field.kind == "code":
        value = str(value or "")
        if (value == "" and not field.default) or (len(value) == 8 and value.isdigit()):
            return ""
        return f"{field.label}: all eight digits" + ("." if field.default else ", or none.")
    if field.kind != "linkcode":
        return ""
    try:
        code_picks(str(value or "").split(","))
    except ValueError:
        return "Pick three Pokemon for the link code."
    return ""


def missing_offer(tool: Tool, values: dict) -> str:
    for field in tool.fields:
        if field.kind != "pokemon" or not applies(field, tool, values):
            continue
        entries = offers(value_of(field, values))[:field.queue] or [{}]
        for n, entry in enumerate(entries, start=1):
            which = f" for trade {n}" if len(entries) > 1 else ""
            path = entry.get("file", "")
            if not path and not field.required and len(entries) == 1:
                continue
            if not path or not os.path.isfile(path):
                return f"Build the Pokemon to offer{which} first."
            if entry.get("legal") is False:
                return f"The Pokemon{which} is not legal."
    return ""

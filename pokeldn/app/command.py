import os
import random
import re
import time
from functools import cache

from pokeldn import gen9
from pokeldn.app import events_gallery, gift_builder
from pokeldn.app.catalog import Field, Tool
from pokeldn.app.i18n import t as tr
from pokeldn.app.introspect import flags_of
from pokeldn.lgpe.session import code_picks
from pokeldn.sv import raid_partners
from pokeldn.app import raid_rewards


@cache
def accepted(script: str) -> frozenset[str]:
    return frozenset(f.option for f in flags_of(script))


def value_of(field: Field, values: dict):
    if field.kind == "builder" and field.key not in values:
        return values.get("--record", field.default)
    return values.get(field.key, field.default)


def steps(tool: Tool, values: dict) -> list[str]:
    """The tool's console steps as its fields stand: a (step, (flag, value)) only while that field
    has that value."""
    shown = []
    for step in tool.steps:
        if isinstance(step, tuple):
            step, (flag, wanted) = step
            if str(value_of(next(f for f in tool.fields if f.key == flag), values)) != wanted:
                continue
        shown.append(step)
    return shown


def raid_consoles(tool: Tool, values: dict) -> int:
    """-> the consoles a Tera Raid host waits for, by its Consoles joining field; 1 without one."""
    field = next((f for f in tool.fields if f.key == "--raid-players"), None)
    try:
        return int(value_of(field, values)) if field else 1
    except (TypeError, ValueError):
        return 1


def raid_pokemon_level(values: dict) -> int:
    """-> the level of the Pokemon a Tera Raid host's player brings, read from its record; 0 when none
    is built or it cannot be read."""
    value = values.get("--raid-pokemon")
    try:
        with open(value["file"], "rb") as fh:
            return gen9.read(gen9.load(fh.read())).get("level", 0)
    except (OSError, KeyError, TypeError, ValueError):
        return 0


def applies(field: Field, tool: Tool, values: dict) -> bool:
    if field.unless:
        source = next(f for f in tool.fields if f.key == field.unless)
        if value_of(source, values):
            return False
    if field.requires:
        source = next(f for f in tool.fields if f.key == field.requires)
        if not value_of(source, values):
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


GIFT_EVENT = "--gift-event"     # pokeldn.receiver_gift


def locked(field: Field, tool: Tool, values: dict) -> str:
    """Why a switch is held off and cannot be turned on, or "": Made for the receiving player while every
    Mystery Gift Pokemon chosen has its card's own trainer, which no save replaces, or is legal only with a
    handler, which its own trainer's save clears (docs/gift_simulated.md)."""
    if not field.your_ot:
        return ""
    chosen = [v for f in tool.fields if f.events for v in offers(value_of(f, values)) if v.get("file")]
    if not chosen or any(v.get("your_ot") is not False for v in chosen):
        return ""
    if any(v.get("handled") for v in chosen):
        return tr("command.handled_gift", "This gift is legal only with a handler, which its own trainer's save clears: it goes with your trainer.")
    owners = ", ".join(dict.fromkeys(v["ot"] for v in chosen if v.get("ot")))
    if len(chosen) == 1:
        return (tr("command.own_trainer_ot", "This gift has its card's own trainer, OT {owners}, and goes as made.", owners=owners)
                if owners else tr("command.own_trainer", "This gift has its card's own trainer and goes as made."))
    return (tr("command.own_trainers_ot", "These gifts have their cards' own trainers, OT {owners}, and go as made.", owners=owners)
            if owners else tr("command.own_trainers", "These gifts have their cards' own trainers and go as made."))


def _args(field: Field, value, tool: Tool) -> list[str]:
    if field.kind == "builder":
        return gift_builder.args(tool, value)
    flags = field.flag if isinstance(field.flag, tuple) else (field.flag,)
    if field.kind == "switch":
        on = bool(value) != field.invert
        return [flags[0], field.template] if (on and field.template) else list(flags) if on else []
    if field.kind == "pokemon":
        chosen = [v for v in offers(value)[:field.queue] if v.get("file", "")]
        files = [v["file"] for v in chosen]
        if not files:
            return list(field.unset)
        out = files if not field.flag else [a for n, f in enumerate(files)
                                             for a in ((field.more if n and field.more else flags[0]), f)]
        # Each Mystery Gift Pokemon's card, in the same order, for a copy made for the receiving player.
        gifts = ([a for v in chosen for a in (GIFT_EVENT, v.get("event", ""))]
                 if field.events and GIFT_EVENT in accepted(tool.script) else [])
        return out + gifts + ([field.count, str(len(files))] if field.count else [])
    if field.kind == "rewards":
        return [part for row in (value or ())
                for part in (flags[0], f"{row.get('item_id', '')}:{row.get('quantity', '')}")]
    if field.kind == "raidevent":     # the event's folder in the app's gallery
        return [flags[0], events_gallery.event_path(value, game=tool.key.split("-")[0])] if value else []
    if field.kind == "raideventboss":   # version:stars:number:area, one value per flag
        parts = str(value or "").split(":", 3)
        return [a for flag, v in zip(flags, parts) for a in (flag, v)] if len(parts) == 4 else []
    if field.kind == "encounter":
        return encounter_args(value)
    if field.kind == "raidpartners":  # {"progress": a stage or "", "picks": trainers in slot order}
        value = value if isinstance(value, dict) else {}
        progress = [flags[1], value["progress"]] if value.get("progress") else []
        return progress + [a for name in value.get("picks", ()) for a in (flags[0], name)]
    if value in ("", None):
        return list(field.unset)
    items = str(value).split() if field.kind == "multi" else [field.template.format(value) if field.template
                                                               else str(value)]
    if not field.flag:
        return items
    return [a for item in items for flag in flags for a in (flag, item)]


ENCOUNTER_FLAGS = (("form", "--spawn-form"), ("tera", "--spawn-tera"), ("nature", "--spawn-nature"),
                   ("gender", "--spawn-gender"), ("ability", "--spawn-ability"), ("scale", "--spawn-scale"),
                   ("item", "--spawn-item"), ("ivs", "--spawn-ivs"))


def encounter_args(value) -> list[str]:
    """bin/sv_join.py's crafted spawn of an encounter field's value: {"legal", "species" (National),
    "level", "shiny", and any of form, tera, nature, gender, ability, scale, item and ivs (HP/ATK/DEF/SPA/SPD/SPE),
    None or absent for one drawn at random} (gui/views/encounter.py)."""
    value = value if isinstance(value, dict) else {}
    if not value.get("species"):
        return []
    out = ["--spawn", f"{gen9.internal_index(int(value['species']))}:{int(value.get('level') or 1)}"]
    for key, flag in ENCOUNTER_FLAGS:
        if value.get(key) not in (None, "") and not (key == "item" and not value[key]):
            out += [flag, str(value[key])]
    return out + (["--spawn-shiny"] if value.get("shiny") else []) + (["--spawn-legal"] if value.get("legal") else [])


def encounter_error(value) -> str:
    """Why an encounter field's value cannot go out, or ""."""
    value = value if isinstance(value, dict) else {}
    if not value.get("species"):
        return tr("command.pick_spawn", "Pick the Pokemon to spawn.")
    if not 1 <= int(value.get("level") or 0) <= 100:
        return tr("command.level_range", "The level is 1 to 100.")
    return ""


# Settings' PKHeX language id -> a Gen 3 launcher's --language; Korean and Chinese have no Gen 3 build.
GBA_LANGUAGES = {1: "japanese", 2: "english", 3: "french", 4: "italian", 5: "german", 7: "spanish"}


def build(tool: Tool, values: dict, extra: dict, settings, stamp: str | None = None) -> list[str]:
    """The entry point's argument list: tested flags, the tool's fields, then the All tab's."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    game = tool.key.split("-")[0]
    tid, sid = settings.ids(game)
    trainer = settings.own(game)
    tokens = {"{received}": os.path.expanduser(settings.received), "{stamp}": stamp,
              "{src_var}": f"0x{random.getrandbits(32):08x}",
              "{ot}": settings.name(game), "{tid}": str(tid), "{sid}": str(sid),
              "{language}": str(trainer["language"]), "{gender}": str(trainer["gender"]),
              "{gba_language}": GBA_LANGUAGES.get(trainer["language"], "english"),
              "{keys}": os.path.expanduser(settings.keys)}
    # A banked Pokemon keeps its PID and encryption constant: they are who it is [docs/gui.md, The bank].
    banked = any(entry.get("bank") for field in tool.fields if field.kind == "pokemon"
                 for entry in offers(value_of(field, values)))
    args = []
    for arg in tool.fixed:
        for token, value in tokens.items():
            arg = arg.replace(token, value)
        args.append(arg)
    for field in tool.fields:
        if banked and field.key == "--fresh-pid":
            continue
        if applies(field, tool, values):
            items = _args(field, False if locked(field, tool, values) else value_of(field, values), tool)
            if field.kind == "builder":     # a backup's file is named after the run
                items = [item.replace("{stamp}", stamp) for item in items]
            args += [tokens.get(item, item) for item in items]
    known = accepted(tool.script)
    if "--keys" in known and "--keys" not in args:
        args += ["--keys", os.path.expanduser(settings.keys)]
    if "--capture" in known and settings.capture:
        args += ["--capture", f"captures/{tool.key}-{stamp}.jsonl"]
    owned = (gift_builder.owned_flags(tool) if any(f.kind == "builder" for f in tool.fields)
             else frozenset())
    for flag, value in extra.items():
        if (banked and flag == "--fresh-pid") or flag in owned:
            continue
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


def reward_den(tool: Tool, values: dict):
    """-> raid_rewards.swsh_den for the boss a Max Raid (Host) form names: {item: count or None}, or
    None; also None for every other tool."""
    if tool.key != "swsh-raid-host":
        return None
    event = values.get("--raid-event") or ""
    boss = "" if event else next((v.get("file", "") for v in offers(values.get("--raid-boss"))), "")
    try:
        stamp = os.stat(os.path.expanduser(boss)).st_mtime_ns if boss else 0
    except OSError:
        return None
    return _reward_den(boss, stamp, not event and bool(values.get("--raid-gigantamax")), event,
                       str(values.get("--raid-version") or "") if event else "")


@cache
def _reward_den(boss, _stamp, gigantamax, event, event_boss):
    try:
        loaded = events_gallery.load(event, game="swsh") if event else None
    except (OSError, ValueError):
        return None
    choices = raid_rewards.swsh_den(boss, gigantamax, loaded, event_boss)
    return None if choices is None else tuple(choices.items())


def reward_problem(tool: Tool, values: dict, rows) -> str:
    """A Sword/Shield guest refuses a raid whose rewards are not its den's (docs/swsh_raid.md)."""
    if tool.key != "swsh-raid-host" or not rows:
        return ""
    den = reward_den(tool, values)
    if den is None:
        return tr("command.boss_first", "Choose a boss a den holds before choosing rewards.")
    den = dict(den)
    for n, row in enumerate(rows, 1):
        item, quantity = str(row.get("item_id", "")), str(row.get("quantity", ""))
        if not item.isdigit() or int(item) not in den:
            return tr("command.reward_not_den", "Reward {n} is not one this den gives.", n=n)
        if den[int(item)] is not None and quantity != str(den[int(item)]):
            return tr("command.reward_quantity_den", "Reward {n}: this den gives it {count} at a time.", n=n, count=den[int(item)])
    return ""


def problems(tool: Tool, values: dict) -> list[str]:
    errors = [error for f in tool.fields if applies(f, tool, values)
            if (error := limit_error(f, value_of(f, values)) if f.limits
                else code_error(f, value_of(f, values), tool.key.split("-")[0]))]
    for field in tool.fields:
        if field.kind == "builder" and (error := gift_builder.problem(tool, value_of(field, values))):
            errors.append(error)
        if field.kind == "rewards" and not code_error(field, value_of(field, values), tool.key.split("-")[0]) \
                and (error := reward_problem(tool, values, value_of(field, values))):
            errors.append(error)
        if field.kind == "raidpartners" and applies(field, tool, values):
            value = value_of(field, values)
            picks = list(value.get("picks", ())) if isinstance(value, dict) else []
            consoles = raid_consoles(tool, values)
            free = raid_partners.slots(consoles)
            if len(picks) > free:
                errors.append(tr("command.partner_seats", "With {consoles} consoles joining, the raid seats {free} partner.",
                                 consoles=consoles, free=free) if free else
                              tr("command.no_partner_seat", "With {consoles} consoles joining, the raid seats no partner.",
                                 consoles=consoles))
    return errors


def prepare(tool: Tool, values: dict, game: str = "", trainer: dict | None = None,
            version: str = "") -> dict:
    """Write what the arguments name but no field holds yet: a built gift's file, and a random legal
    Pokemon for an empty offer. -> the values to build the arguments from; `values` keeps the
    empty offer, so the next run draws again."""
    filled = dict(values)
    for field in tool.fields:
        if field.kind == "builder":
            gift_builder.prepare(tool, value_of(field, values))
        elif (field.random and game and applies(field, tool, values)
              and not any(e.get("file") for e in offers(value_of(field, values)))):
            filled[field.key] = [random_offer(game, trainer or {}, version)]
    return filled


def random_offer(game: str, trainer: dict, version: str = "", tries: int = 20,
                 rng=random) -> dict:
    """A random species of `game` that PKHeX builds legally for `trainer`, as the builder holds it."""
    from pokeldn import pokemon
    species = pokemon.SERVICE.species(game)
    for _ in range(tries):
        try:
            info = pokemon.SERVICE.make(game, rng.choice(species)["id"], trainer, version=version)
        except Exception:  # noqa: BLE001  - a species with no legal encounter here; draw again
            continue
        if info.get("legal"):
            return {"file": info["file"], "summary": pokemon.summary(info), "legal": True}
    raise ValueError(tr("command.random_offer", "PKHeX built no legal Pokemon to offer; pick one."))


def code_error(field: Field, value, game: str = "sv") -> str:
    """A console code is all its digits, or empty where the field allows none; a Let's Go link code
    must name three picker Pokemon. Either partial one would host under another code. A bounded
    number lies within its bounds. A raid seed is eight
    hex digits; a raid reward row names an item and a quantity from 1 to 999; a raid event is in the
    app's event gallery."""
    if field.kind == "raidseed":
        return "" if re.fullmatch(r"[0-9A-Fa-f]{8}", str(value or "")) else tr("command.raid_seed", "Enter eight hexadecimal digits.")
    if field.kind == "lairseed":
        return "" if re.fullmatch(r"[0-9A-Fa-f]{0,16}", str(value or "")) else tr("command.lair_seed", "Enter up to sixteen hexadecimal digits.")
    if field.kind == "encounter":
        return encounter_error(value)
    if field.kind == "raidpartners":
        value = value if isinstance(value, dict) else {}
        picks = list(value.get("picks", ()))
        if len(picks) > raid_partners.HOSTED:
            return tr("command.partners_at_most", "A raid seats {count} partners at most.", count=raid_partners.HOSTED)
        if value.get("progress") and value["progress"] not in raid_partners.STAGES:
            return tr("command.partner_progress", "Choose the partners' progress again.")
        stage = (raid_partners.STAGES.index(value["progress"]) if value.get("progress")
                 else raid_partners.SIX_STARS)
        known = {p.trainer for p in raid_partners.pool(stage)}
        if any(name not in known for name in picks):
            return tr("command.partner_unknown", "A chosen partner is not among this progress's trainers.")
        return ""
    if field.kind == "raidevent":
        if not value or events_gallery.holds(value, game=game):
            return ""
        if not events_gallery.present(game=game):
            return tr("command.gallery_missing", "Download the event gallery in Raid event, or choose no event.")
        return tr("command.event_gone", "The chosen event is not in the event gallery any more.")
    if field.kind == "rewards":
        rows = list(value or ())
        if len(rows) > raid_rewards.rows(game):
            return tr("command.rewards_at_most", "A raid gives at most {count} rewards.", count=raid_rewards.rows(game))
        for n, row in enumerate(rows, 1):
            item = str(row.get("item_id", ""))
            quantity = str(row.get("quantity", ""))
            if not item.isascii() or not item.isdigit() or not int(item):
                return tr("command.reward_item", "Choose an item for reward {n}.", n=n)
            if not quantity.isascii() or not quantity.isdigit() or not 1 <= int(quantity) <= 999:
                return tr("command.reward_quantity", "Reward {n} needs a quantity from 1 to 999.", n=n)
        return ""
    if field.kind == "code":
        value = str(value or "")
        if ((value == "" and not field.default and not field.required)
                or (len(value) == field.length and value.isdigit())):
            return ""
        digits = {4: tr("command.four", "four"), 8: tr("command.eight", "eight")}.get(field.length, field.length)
        if field.default or field.required:
            return tr("command.code_digits", "{label}: all {digits} digits.", label=field.label, digits=digits)
        return tr("command.code_digits_or_none", "{label}: all {digits} digits, or none.", label=field.label, digits=digits)
    if field.kind == "number" and field.bounds:
        low, high = field.bounds
        value = str(value if value is not None else "").strip()
        if value.isascii() and value.isdigit() and low <= int(value) <= high:
            return ""
        return tr("command.number_range", "{label}: a whole number from {low:,} to {high:,}.", label=field.label, low=low, high=high)
    if field.kind != "linkcode":
        return ""
    try:
        code_picks(str(value or "").split(","))
    except ValueError:
        return tr("command.link_code_picks", "Pick three Pokemon for the link code.")
    return ""


def missing_offer(tool: Tool, values: dict) -> str:
    for field in tool.fields:
        if field.kind != "pokemon" or not applies(field, tool, values):
            continue
        entries = offers(value_of(field, values))[:field.queue] or [{}]
        for n, entry in enumerate(entries, start=1):
            many = len(entries) > 1
            path = entry.get("file", "")
            if not path and not field.required and len(entries) == 1:
                continue
            if not path or not os.path.isfile(path):
                return (tr("command.choose_gift", "Choose the Mystery Gift Pokemon first.") if field.events else
                        tr("command.build_offer_n", "Build the Pokemon to offer for trade {n} first.", n=n) if many else
                        tr("command.build_offer", "Build the Pokemon to offer first."))
            if entry.get("legal") is False:
                return (tr("command.offer_illegal_n", "The Pokemon for trade {n} is not legal.", n=n) if many else
                        tr("command.offer_illegal", "The Pokemon is not legal."))
    return ""

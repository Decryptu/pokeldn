"""The official Sword/Shield Wonder Cards the app offers, from projectpokemon EventsGallery
(scripts/gen_swsh_events.py; docs/swsh_gift.md, Official event cards)."""

import base64
import functools
import json
import struct
from pathlib import Path

from pokeldn.swsh import gift_file, wc8

DATA = Path(__file__).parent / "data" / "events.json"
GROUPS = ("Pokemon", "Items", "Battle Points", "Clothing")
ENGLISH = 1                 # the record's name slots run Japanese, English, French, ...
VERSIONS = {1: "Sword only", 2: "Shield only"}


@functools.cache
def load() -> tuple[dict, ...]:
    return tuple({**e, "record": base64.b64decode(e["record"])} for e in json.loads(DATA.read_text()))


@functools.cache
def by_key() -> dict:
    return {e["key"]: e for e in load()}


def gift(key):
    try:
        event = by_key()[key]
    except KeyError:
        raise ValueError("Pick an event card.") from None
    return gift_file.from_record(event["record"], name=event["label"])


def item_pairs(raw):
    return [p for p in (struct.unpack_from("<HH", raw, 0x20 + 4 * i) for i in range(6)) if p[0] and p[1]]


def item_ids(raw):
    """Every item a card puts in the bag or a Pokemon's hand."""
    if raw[wc8.GIFT_KIND_AT] == 2:
        return [i for i, _ in item_pairs(raw)]
    if raw[wc8.GIFT_KIND_AT] == wc8.GIFT_KIND_POKEMON:
        return [i for i in (wc8.read(raw)["held_item"],) if i]
    return []


def receipt(raw):
    """How often a console takes the card, by the record flags the receipt check 0x00ff1750 reads
    [docs/swsh_gift.md, What the menu refuses]."""
    card_id = struct.unpack_from("<H", raw, 0x08)[0]
    if raw[0x10] & 1:
        return f"Card id {card_id}: a console takes it once"
    if raw[0x10] & 4:
        return f"Card id {card_id}: a console takes it once for its date, at most ten such cards a day"
    return f"Card id {card_id}: a console takes it again"


def _name(raw, base, index=ENGLISH):
    at = base + index * wc8.LANG_STRIDE
    text = raw[at:at + wc8.NAME_BYTES].decode("utf-16-le").split("\0")[0]
    return text or (_name(raw, base, 0) if index else "")


def describe(raw, name=lambda kind, n: f"{kind} #{n}"):
    """(when it applies, [what happens]); `name(kind, id)` names a species or an item."""
    kind = raw[wc8.GIFT_KIND_AT]
    when = "Listed under Mystery Gift; the player picks it, then it lands in the save."
    if kind == wc8.GIFT_KIND_POKEMON:
        f = wc8.read(raw)
        line = f"Gives {name('species', f['species'])}, " + (
            f"level {f['level']}" if f["level"] else "a level the game rolls")
        line += ", shiny" if f["shiny_type"] in (2, 3) else ""
        line += ", can Gigantamax" if f["gigantamax"] else ""
        lines = [line + (" (an egg)" if f["egg"] else "")]
        if f["held_item"]:
            lines.append(f"Holding {name('item', f['held_item'])}")
        ot = _name(raw, wc8.OT_NAMES)
        lines.append(f"Original trainer {ot}" if ot and not (f["tid"] == f["sid"] == 0)
                     else "The player is its original trainer")
    elif kind == 2:
        lines = [f"Gives {name('item', i)} x{q}" for i, q in item_pairs(raw)]
    elif kind == 3:
        lines = [f"Adds {struct.unpack_from('<I', raw, 0x20)[0]} Battle Points"]
    elif kind == 4:
        pairs = [struct.unpack_from("<II", raw, 0x20 + 8 * i) for i in range(6)]
        pieces = sum(i != 0xFFFFFFFF and (c, i) != (0, 0) for c, i in pairs)   # official cards pad with (0, 0)
        lines = [f"Puts {pieces} piece{'s' * (pieces != 1)} of clothing in the wardrobe; the player gets "
                 f"the version for their own character"]
    else:
        lines = [f"Gift kind {kind}"]
    version = VERSIONS.get(struct.unpack_from("<H", raw, 0x0E)[0])
    if version:
        lines.append(f"{version}: the other version skips the card")
    lines.append(receipt(raw))
    return when, lines

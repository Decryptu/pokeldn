"""The official Sword/Shield Wonder Cards the app offers, from projectpokemon EventsGallery
(scripts/gen_swsh_events.py; docs/swsh_gift.md, Official event cards)."""

import base64
import functools
import json
import struct
from pathlib import Path

from pokeldn.swsh import gift_file, wc8
from pokeldn.app import i18n
from pokeldn.app.i18n import ref, message_ref

DATA = Path(__file__).parent / "data" / "events.json"
HOME = "Pokemon HOME"
GROUPS = ("Pokemon", HOME, "Items", "Battle Points", "Clothing")
GROUP_LABELS = dict(zip(GROUPS, (ref("core.swsh.event.group.pokemon"), ref("core.swsh.event.home"),
    ref("core.gift.kind.items"), ref("core.swsh.event.group.bp"), ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"))))
# Card ids from 9000 are the community's cards for the gifts Pokemon HOME gave (PKHeX's WC8.IsHOMEGift).
HOME_CARDS = 9000
HOME_WHY = ref("core.swsh.event.home_why")
ENGLISH = 1                 # the record's name slots run Japanese, English, French, ...
VERSIONS = {1: ref("core.swsh.event.sword"), 2: ref("core.swsh.event.shield")}


@functools.cache
def load() -> tuple[dict, ...]:
    cards = json.loads(DATA.read_text(encoding="utf-8"))      # Windows reads cp1252 by default
    return tuple({**e, "label": ref(f"core.swsh.event.{e['key']}.title"),
                  "record": base64.b64decode(e["record"])} for e in cards)


@functools.cache
def by_key() -> dict:
    return {e["key"]: e for e in load()}


def card_id(raw):
    return struct.unpack_from("<H", raw, 0x08)[0]


def _once(raw):
    return raw[0x10] & 5


def max_card_id(raw):
    """A once-per-id card's bit is read from a 2048-bit bitmap with no bound (0x00ff1a8c)."""
    return 2047 if raw[0x10] & 1 else 0xFFFF


def record(key, new_id=None):
    """The card's record, its id changed when `new_id` is given; raises ValueError with what to fix."""
    try:
        raw = by_key()[key]["record"]
    except KeyError:
        raise ValueError("Pick an event card.") from None
    if new_id in (None, "", card_id(raw)):
        return raw
    if not 0 < int(new_id) <= max_card_id(raw):
        raise ValueError(f"The card id is 1 to {max_card_id(raw)}.")
    out = bytearray(raw)
    struct.pack_into("<H", out, 0x08, int(new_id))
    return wc8.seal(out)


def gift(key, new_id=None):
    return gift_file.from_record(record(key, new_id), name=by_key()[key]["label"])


def sharing(key, new_id=None):
    """The labels of the other once-only cards with this card's id: a save that took one refuses the
    rest [docs/swsh_gift.md, Cards that share an id]."""
    raw = record(key, new_id)
    if not _once(raw):
        return []
    label = by_key()[key]["label"]
    return sorted({e["label"] for e in load() if e["key"] != key and e["label"] != label
                   and _once(e["record"]) and card_id(e["record"]) == card_id(raw)})


def from_home(raw):
    """A community card of a gift Pokemon HOME gave [docs/swsh_gift.md, Official event cards]."""
    return card_id(raw) >= HOME_CARDS


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
    number = card_id(raw)
    if raw[0x10] & 1:
        return message_ref("core.swsh.event.receipt.once", card_id=number)
    if raw[0x10] & 4:
        return message_ref("core.swsh.event.receipt.daily", card_id=number)
    return message_ref("core.swsh.event.receipt.again", card_id=number)


def _name(raw, base, index=ENGLISH):
    at = base + index * wc8.LANG_STRIDE
    text = raw[at:at + wc8.NAME_BYTES].decode("utf-16-le").split("\0")[0]
    return text or (_name(raw, base, 0) if index else "")


def describe(raw, name=lambda kind, n: f"{kind} #{n}"):
    """(when it applies, [what happens]); `name(kind, id)` names a species or an item."""
    kind = raw[wc8.GIFT_KIND_AT]
    when = ref("core.pokeldn.swsh.gift_builder.listed_under_mystery_gift_the_player_picks_it_then_it_l_dade4d6f")
    if kind == wc8.GIFT_KIND_POKEMON:
        f = wc8.read(raw)
        details = [message_ref("core.gift.pokemon.level", level=f['level']) if f["level"] else ref("core.gift.pokemon.random_level")]
        if f["shiny_type"] in (2, 3):
            details.append(ref("core.presentation.shiny"))
        if f["gigantamax"]:
            details.append(ref("core.gift.pokemon.gigantamax"))
        lines = [message_ref("core.gift.egg.description", species=name('species', f['species'])) if f["egg"] else
                 message_ref("core.gift.pokemon.description", species=name('species', f['species']), details=i18n.join(details))]
        if f["held_item"]:
            lines.append(message_ref("core.gift.pokemon.holding", item=name('item', f['held_item'])))
        ot = _name(raw, wc8.OT_NAMES)
        lines.append(message_ref("core.swsh.event.ot", ot=ot) if ot and not (f["tid"] == f["sid"] == 0)
                     else ref("core.swsh.event.your_ot"))
    elif kind == 2:
        lines = [message_ref("core.gift.item.description", item=name('item', i), quantity=q) for i, q in item_pairs(raw)]
    elif kind == 3:
        lines = [message_ref("core.gift.bp.description", quantity=struct.unpack_from('<I', raw, 0x20)[0])]
    elif kind == 4:
        pairs = [struct.unpack_from("<II", raw, 0x20 + 8 * i) for i in range(6)]
        pieces = sum(i != 0xFFFFFFFF and (c, i) != (0, 0) for c, i in pairs)   # official cards pad with (0, 0)
        lines = [message_ref("core.swsh.event.clothing", quantity=pieces)]
    else:
        lines = [message_ref("core.swsh.event.kind", kind=kind)]
    version = VERSIONS.get(struct.unpack_from("<H", raw, 0x0E)[0])
    if version:
        lines.append(message_ref("core.swsh.event.version", version=version))
    lines.append(receipt(raw))
    return when, lines

"""The app's Sword/Shield gift builder: a plain form state (JSON) -> a sealed WC8 record. Each kind
mirrors a record a retail Sword listed and redeemed (docs/swsh_gift.md, A card delivered)."""

import struct
from dataclasses import dataclass

from pokeldn.swsh import gift_file, wc8

KINDS = (("pokemon", "Pokemon", "gift"), ("egg", "Egg", "package"), ("items", "Items", "bulletlist"),
         ("bp", "Battle Points", "zap"))
MAX_ITEM = 1607          # the 1.3.2 item table; a higher id crashes the bag screen
TITLE_AT, PAYLOAD_AT = 0x15, 0x20
# Title indexes into text_wondercard8 [docs/swsh_gift.md]: 1 Pokemon egg, 3 the item's name, 39 Battle Points.
TITLE_EGG, TITLE_ITEM, TITLE_BP = 1, 3, 39


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    group: str
    summary: str
    state: dict
    args: tuple = ()


def blank(**changes):
    state = {"kind": "pokemon", "species": 25, "level": 25, "form": 0, "moves": [84, 45, 86, 98],
             "item": 0, "ball": 0, "shiny": False, "nickname": "PKCAMP", "ot": "POKELDN",
             "items": [[1, 3]], "bp": 10, "card_id": 9999}
    state.update(changes)
    return state


PRESETS = (
    Preset("pikachu", "Pikachu", "Pokemon", "A level 25 Pikachu nicknamed PKCAMP.", blank()),
    Preset("egg", "Pikachu egg", "Pokemon", "An egg that hatches into Pikachu.",
           blank(kind="egg", level=1, nickname="")),
    Preset("master-balls", "Three Master Balls", "Items", "Three Master Balls in the bag.",
           blank(kind="items", items=[[1, 3]])),
    Preset("bp", "10 Battle Points", "Items", "Adds 10 BP, up to the game's 9999.", blank(kind="bp", bp=10)),
)
PRESET = {p.key: p for p in PRESETS}


def _int(state, key, default=0):
    return int(state.get(key) or default)


def record(state):
    """Form state -> a sealed 720-byte record. Raises ValueError with what to fix."""
    kind, card_id = state.get("kind", "pokemon"), _int(state, "card_id", 9999)
    if not 0 < card_id <= 0xFFFF:
        raise ValueError("The card id is 1 to 65535.")
    if kind in ("pokemon", "egg"):
        egg = kind == "egg"
        level = 1 if egg else _int(state, "level")
        if not egg and not 0 <= level <= 100:
            raise ValueError("The level is 0 to 100; 0 lets the game roll one.")
        if (item := _int(state, "item")) > MAX_ITEM:
            raise ValueError(f"Sword and Shield have no item above {MAX_ITEM}.")
        moves = [int(m or 0) for m in (list(state.get("moves", ())) + [0] * 4)[:4]]
        fields = {"ot_gender": 2, "held_item": item, "ball": _int(state, "ball")}
        if state.get("shiny") and not egg:
            fields["shiny_type"] = 2
        if egg:
            fields["egg"] = 1
        try:
            raw = wc8.pokemon_card(_int(state, "species", 25), level=level, form=_int(state, "form"),
                                   moves=moves, nickname=state.get("nickname") or None,
                                   ot=None if egg else state.get("ot") or None, card_id=card_id, **fields)
        except ValueError as exc:
            raise ValueError(f"Names: {exc}") from None
        if egg:
            raw = _patch(raw, {TITLE_AT: bytes([TITLE_EGG])})
        return raw
    if kind == "items":
        pairs = [(int(i or 0), int(q or 0)) for i, q in state.get("items", ()) if int(i or 0)]
        if not pairs:
            raise ValueError("Add at least one item.")
        if len(pairs) > 6:
            raise ValueError("A card carries six items at most.")
        for item, quantity in pairs:
            if not 0 < item <= MAX_ITEM:
                raise ValueError(f"Sword and Shield have no item {item}.")
            if not 0 < quantity <= 999:
                raise ValueError("Each quantity is 1 to 999.")
        payload = b"".join(struct.pack("<HH", i, q) for i, q in pairs)
        return wc8.build(card_id=card_id, extra={wc8.GIFT_KIND_AT: b"\x02", TITLE_AT: bytes([TITLE_ITEM]),
                                                 PAYLOAD_AT: payload})
    if kind == "bp":
        amount = _int(state, "bp")
        if not 0 < amount <= 9999:
            raise ValueError("Battle Points are 1 to 9999.")
        return wc8.build(card_id=card_id, extra={wc8.GIFT_KIND_AT: b"\x03", TITLE_AT: bytes([TITLE_BP]),
                                                 PAYLOAD_AT: struct.pack("<I", amount)})
    raise ValueError(f"Unknown gift kind {kind!r}.")


def _patch(raw, extra):
    data = bytearray(raw)
    for offset, value in extra.items():
        data[offset:offset + len(value)] = value
    return wc8.seal(data)


def compile(state):
    names = {"pokemon": state.get("nickname") or "Pokemon", "egg": "Pokemon egg", "items": "Items",
             "bp": "Battle Points"}
    return gift_file.from_record(record(state), name=names.get(state.get("kind"), "Sword/Shield gift"))


def describe(state, name=lambda kind, n: f"{kind} #{n}"):
    """(when it applies, [what happens]); `name(kind, id)` names a species or an item."""
    kind = state.get("kind", "pokemon")
    when = "Listed under Mystery Gift; the player picks it, then it lands in the save."
    if kind == "pokemon":
        level = _int(state, "level")
        lines = [f"Gives {name('species', state.get('species'))}, "
                 + (f"level {level}" if level else "a level the game rolls")
                 + (", shiny" if state.get("shiny") else "")]
        if _int(state, "item"):
            lines.append(f"Holding {name('item', state.get('item'))}")
    elif kind == "egg":
        lines = [f"Gives a {name('species', state.get('species'))} egg"]
    elif kind == "items":
        lines = [f"Gives {name('item', i)} x{q}" for i, q in state.get("items", ()) if int(i or 0)]
    else:
        lines = [f"Adds {_int(state, 'bp')} Battle Points"]
    lines.append(f"Card id {_int(state, 'card_id', 9999)}: a console takes the same id again")
    return when, lines

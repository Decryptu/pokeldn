"""The app's Sword/Shield gift builder: a plain form state (JSON) -> a sealed WC8 record. Each kind
mirrors a record a retail Sword listed and redeemed (docs/swsh_gift.md, A card delivered)."""

import struct
from dataclasses import dataclass

from pokeldn.swsh import gift_file, wc8

KINDS = (("pokemon", "Pokemon", "gift"), ("egg", "Egg", "package"), ("items", "Items", "bulletlist"),
         ("clothing", "Clothing", "shirt"), ("bp", "Battle Points", "zap"), ("money", "Money", "coins"))
MAX_ITEM = 1607          # the 1.3.2 item table; a higher id crashes the bag screen
MAX_MONEY = 9_999_999    # the kind-5 clamp 0x01438f2c
TITLE_AT, PAYLOAD_AT = 0x15, 0x20
# Title indexes into text_wondercard8 [docs/swsh_gift.md]: 1 Pokemon egg, 3 the item's name,
# 21 "{species} (Gigantamax Pokemon)", 34 pocket money, 36 clothing, 39 Battle Points.
TITLE_EGG, TITLE_ITEM, TITLE_GMAX, TITLE_MONEY, TITLE_CLOTHING, TITLE_BP = 1, 3, 21, 34, 36, 39
KIND_ITEMS, KIND_BP, KIND_CLOTHING, KIND_MONEY = 2, 3, 4, 5
CLOTHING_SLOTS = 6       # per player gender; the redemption 0x01015eb0 reads six pairs for each
NO_CLOTHING = (0, 0xFFFFFFFF)   # an index of -1 is skipped


@dataclass(frozen=True)
class Outfit:
    key: str
    label: str
    male: tuple          # (category, index) pairs; the first six on the card
    female: tuple        # the last six


# The pairs of projectpokemon EventsGallery's official clothing cards (card ids in the comments).
OUTFITS = (
    Outfit("pikachu-uniform", "Pikachu uniform", ((9, 20), (11, 21), (12, 20), (13, 20), (14, 19)),
           ((9, 2), (11, 3), (12, 2), (13, 2), (14, 19))),                                       # 1607
    Outfit("eevee-uniform", "Eevee uniform", ((9, 21), (11, 22), (12, 21), (13, 21), (14, 20)),
           ((9, 3), (11, 4), (12, 3), (13, 3), (14, 20))),                                       # 1608
    Outfit("tracksuit", "Tracksuit", ((7, 0), (8, 0), (12, 24), (10, 0), (11, 25), (13, 26)),
           ((7, 0), (8, 0), (12, 24), (10, 0), (11, 25), (13, 25))),                             # 1605
    Outfit("leon-cap-tights", "Leon's cap and tights", ((7, 80), (13, 89)), ((7, 80), (13, 121))),  # 1624
    Outfit("gold-backpack", "Gold studded backpack", ((10, 45),), ((10, 48),)),                     # 1606
    Outfit("tee-poke-ball", "Poke Ball Guy tee", ((9, 101),), ((9, 89),)),                          # 0001
    Outfit("tee-great-ball", "Great Ball Guy tee", ((9, 102),), ((9, 90),)),                        # 0001
    Outfit("tee-ultra-ball", "Ultra Ball Guy tee", ((9, 103),), ((9, 91),)),                        # 0001
    Outfit("tee-quest", "Pokemon Quest tee", ((9, 104),), ((9, 92),)),                              # 0105
)
OUTFIT = {o.key: o for o in OUTFITS}
TEES = ["tee-poke-ball", "tee-great-ball", "tee-ultra-ball", "tee-quest"]


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
             "item": 0, "ball": 0, "shiny": False, "nickname": "POKELDN", "ot": "POKELDN",
             "gigantamax": False, "items": [[1, 3]], "outfits": ["pikachu-uniform"], "bp": 10,
             "money": 10000, "card_id": 9999}
    state.update(changes)
    return state


PRESETS = (
    Preset("pikachu", "Pikachu", "Pokemon", "A level 25 Pikachu nicknamed POKELDN.", blank()),
    Preset("gmax-pikachu", "Gigantamax Pikachu", "Pokemon",
           "A level 25 Pikachu that can Gigantamax, at the top Dynamax level.",
           blank(gigantamax=True, dynamax_level=10)),
    Preset("egg", "Pikachu egg", "Pokemon", "An egg that hatches into Pikachu.",
           blank(kind="egg", level=1, nickname="")),
    Preset("master-balls", "Three Master Balls", "Items", "Three Master Balls in the bag.",
           blank(kind="items", items=[[1, 3]])),
    Preset("rare-candies", "Ten Rare Candies", "Items", "Ten Rare Candies in the bag.",
           blank(kind="items", items=[[50, 10]])),
    Preset("training-kit", "Training kit", "Items",
           "Rare Candies, Exp. Candy XL, PP Max, an Ability Capsule and Bottle Caps.",
           blank(kind="items", items=[[50, 10], [1128, 5], [53, 3], [645, 1], [795, 3], [796, 1]])),
    Preset("bp", "10 Battle Points", "Items", "Adds 10 BP, up to the game's 9999.", blank(kind="bp", bp=10)),
    Preset("money", "Pocket money", "Items", "Adds 100,000 to the player's money.",
           blank(kind="money", money=100000)),
    Preset("pikachu-uniform", "Pikachu uniform", "Clothing", "The Pikachu outfit, in the wardrobe.",
           blank(kind="clothing", outfits=["pikachu-uniform"])),
    Preset("eevee-uniform", "Eevee uniform", "Clothing", "The Eevee outfit, in the wardrobe.",
           blank(kind="clothing", outfits=["eevee-uniform"])),
    Preset("tracksuit", "Tracksuit", "Clothing", "The tracksuit set, in the wardrobe.",
           blank(kind="clothing", outfits=["tracksuit"])),
    Preset("leon-cap-tights", "Leon's cap and tights", "Clothing", "Leon's cap and tights, in the wardrobe.",
           blank(kind="clothing", outfits=["leon-cap-tights"])),
    Preset("gold-backpack", "Gold studded backpack", "Clothing", "A gold studded backpack, in the wardrobe.",
           blank(kind="clothing", outfits=["gold-backpack"])),
    Preset("tees", "Four Poke Ball tees", "Clothing", "The four Poke Ball Guy and Pokemon Quest tees.",
           blank(kind="clothing", outfits=TEES)),
)
PRESET = {p.key: p for p in PRESETS}


def card_gender(species, form=0):
    """A gender drawn now from the species' ratio, so the reveal and the party agree; 3 (the game
    rolls each build apart) when PKHeX is missing."""
    from pokeldn import pokemon
    try:
        return wc8.roll_gender(pokemon.SERVICE.gender_ratio("swsh", species, form))
    except pokemon.BuilderError:
        return 3


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
        species, form = _int(state, "species", 25), _int(state, "form")
        fields = {"ot_gender": 2, "held_item": item, "ball": _int(state, "ball"),
                  "gender": card_gender(species, form)}
        if state.get("shiny") and not egg:
            fields["shiny_type"] = 2
        if state.get("gigantamax") and not egg:
            fields["gigantamax"] = 1
            fields["dynamax_level"] = min(max(_int(state, "dynamax_level"), 0), 10)
        if egg:
            fields["egg"] = 1
        try:
            raw = wc8.pokemon_card(species, level=level, form=form,
                                   moves=moves, nickname=state.get("nickname") or None,
                                   ot=None if egg else state.get("ot") or None, card_id=card_id, **fields)
        except ValueError as exc:
            raise ValueError(f"Names: {exc}") from None
        if egg or fields.get("gigantamax"):
            raw = _patch(raw, {TITLE_AT: bytes([TITLE_EGG if egg else TITLE_GMAX])})
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
        return _card(card_id, KIND_ITEMS, TITLE_ITEM, payload)
    if kind == "clothing":
        return _card(card_id, KIND_CLOTHING, TITLE_CLOTHING, clothing_payload(state.get("outfits", ())))
    if kind == "bp":
        amount = _int(state, "bp")
        if not 0 < amount <= 9999:
            raise ValueError("Battle Points are 1 to 9999.")
        return _card(card_id, KIND_BP, TITLE_BP, struct.pack("<I", amount))
    if kind == "money":
        amount = _int(state, "money")
        if not 0 < amount <= MAX_MONEY:
            raise ValueError(f"Money is 1 to {MAX_MONEY:,}.")
        return _card(card_id, KIND_MONEY, TITLE_MONEY, struct.pack("<I", amount))
    raise ValueError(f"Unknown gift kind {kind!r}.")


def clothing_payload(keys):
    """Outfit keys -> the 96 bytes at +0x20: six (category, index) u32 pairs for a male player, then six
    for a female one (0x01015eb0 picks a set by the player's gender, 0x01424c20)."""
    try:
        outfits = [OUTFIT[k] for k in dict.fromkeys(keys)]
    except KeyError as exc:
        raise ValueError(f"Unknown outfit {exc.args[0]!r}.") from None
    if not outfits:
        raise ValueError("Pick at least one outfit.")
    payload = b""
    for side in ("male", "female"):
        pairs = [pair for o in outfits for pair in getattr(o, side)]
        if len(pairs) > CLOTHING_SLOTS:
            raise ValueError(f"A card carries {CLOTHING_SLOTS} pieces of clothing at most; pick fewer outfits.")
        pairs += [NO_CLOTHING] * (CLOTHING_SLOTS - len(pairs))
        payload += b"".join(struct.pack("<II", c, i) for c, i in pairs)
    return payload


def _card(card_id, kind, title, payload):
    return wc8.build(card_id=card_id, extra={wc8.GIFT_KIND_AT: bytes([kind]), TITLE_AT: bytes([title]),
                                             PAYLOAD_AT: payload})


def _patch(raw, extra):
    data = bytearray(raw)
    for offset, value in extra.items():
        data[offset:offset + len(value)] = value
    return wc8.seal(data)


def compile(state):
    names = {"pokemon": state.get("nickname") or "Pokemon", "egg": "Pokemon egg", "items": "Items",
             "clothing": "Clothing", "bp": "Battle Points", "money": "Money"}
    return gift_file.from_record(record(state), name=names.get(state.get("kind"), "Sword/Shield gift"))


def describe(state, name=lambda kind, n: f"{kind} #{n}"):
    """(when it applies, [what happens]); `name(kind, id)` names a species or an item."""
    kind = state.get("kind", "pokemon")
    when = "Listed under Mystery Gift; the player picks it, then it lands in the save."
    if kind == "pokemon":
        level = _int(state, "level")
        lines = [f"Gives {name('species', state.get('species'))}, "
                 + (f"level {level}" if level else "a level the game rolls")
                 + (", shiny" if state.get("shiny") else "")
                 + (", can Gigantamax" if state.get("gigantamax") else "")]
        if _int(state, "item"):
            lines.append(f"Holding {name('item', state.get('item'))}")
    elif kind == "egg":
        lines = [f"Gives a {name('species', state.get('species'))} egg"]
    elif kind == "items":
        lines = [f"Gives {name('item', i)} x{q}" for i, q in state.get("items", ()) if int(i or 0)]
    elif kind == "clothing":
        lines = [f"Puts the {OUTFIT[k].label} in the wardrobe" for k in state.get("outfits", ()) if k in OUTFIT]
        lines.append("The card holds a male and a female version; the player gets their own")
    elif kind == "money":
        lines = [f"Adds {_int(state, 'money'):,} to the player's money, up to {MAX_MONEY:,}"]
    else:
        lines = [f"Adds {_int(state, 'bp')} Battle Points"]
    lines.append(f"Card id {_int(state, 'card_id', 9999)}: a console takes the same id again")
    return when, lines

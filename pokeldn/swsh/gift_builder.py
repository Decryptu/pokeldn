from pokeldn.app.i18n import message_ref as _message
from pokeldn.app.i18n import ref as _ref
"""The app's Sword/Shield gift builder: a plain form state (JSON) -> a sealed WC8 record. Each kind
mirrors a record a retail Sword listed and redeemed (docs/swsh_gift.md, A card delivered)."""

import struct
from dataclasses import dataclass

from pokeldn.pokemon import NATURES
from pokeldn.swsh import events as OFFICIAL, gift_file, wc8

KINDS = (("pokemon", _ref("core.pokeldn.swsh.gift_builder.pokemon_22464231"), "gift"), ("egg", "Egg", "package"), ("items", "Items", "bulletlist"),
         ("clothing", _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), "shirt"), ("bp", _ref("core.pokeldn.swsh.gift_builder.battle_points_c484f837"), "zap"), ("money", "Money", "coins"))
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
    Outfit("pikachu-uniform", _ref("core.pokeldn.swsh.gift_builder.pikachu_uniform_ac84b0e7"), ((9, 20), (11, 21), (12, 20), (13, 20), (14, 19)),
           ((9, 2), (11, 3), (12, 2), (13, 2), (14, 19))),                                       # 1607
    Outfit("eevee-uniform", _ref("core.pokeldn.swsh.gift_builder.eevee_uniform_39e4bad7"), ((9, 21), (11, 22), (12, 21), (13, 21), (14, 20)),
           ((9, 3), (11, 4), (12, 3), (13, 3), (14, 20))),                                       # 1608
    Outfit("tracksuit", _ref("core.pokeldn.swsh.gift_builder.tracksuit_62ac1521"), ((7, 0), (8, 0), (12, 24), (10, 0), (11, 25), (13, 26)),
           ((7, 0), (8, 0), (12, 24), (10, 0), (11, 25), (13, 25))),                             # 1605
    Outfit("leon-cap-tights", _ref("core.pokeldn.swsh.gift_builder.leon_s_cap_and_tights_bb408f8d"), ((7, 80), (13, 89)), ((7, 80), (13, 121))),  # 1624
    Outfit("gold-backpack", _ref("core.pokeldn.swsh.gift_builder.gold_studded_backpack_adef657f"), ((10, 45),), ((10, 48),)),                     # 1606
    Outfit("tee-poke-ball", _ref("core.pokeldn.swsh.gift_builder.poke_ball_guy_tee_97868992"), ((9, 101),), ((9, 89),)),                          # 0001
    Outfit("tee-great-ball", _ref("core.pokeldn.swsh.gift_builder.great_ball_guy_tee_cced69ca"), ((9, 102),), ((9, 90),)),                        # 0001
    Outfit("tee-ultra-ball", _ref("core.pokeldn.swsh.gift_builder.ultra_ball_guy_tee_4b9cd872"), ((9, 103),), ((9, 91),)),                        # 0001
    Outfit("tee-quest", _ref("core.pokeldn.swsh.gift_builder.pokemon_quest_tee_1fa586d4"), ((9, 104),), ((9, 92),)),                              # 0105
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

    @property
    def species_id(self):
        return self.state["species"] if self.state["kind"] in ("pokemon", "egg") else 0

    @property
    def shiny(self):
        return self.state["kind"] == "pokemon" and bool(self.state.get("shiny"))


def blank(**changes):
    state = {"kind": "pokemon", "species": 25, "level": 25, "form": 0, "moves": [84, 45, 86, 98],
             "item": 0, "ball": 0, "shiny": False, "nickname": "POKELDN", "ot": "POKELDN",
             "gigantamax": False, "items": [[1, 3]], "outfits": ["pikachu-uniform"], "bp": 10,
             "money": 10000, "card_id": 9999}
    state.update(changes)
    return state


PRESETS = (
    Preset("pikachu", _ref("core.pokeldn.swsh.gift_builder.pikachu_a7c280e7"), _ref("core.pokeldn.swsh.gift_builder.pokemon_22464231"), _ref("core.pokeldn.swsh.gift_builder.a_level_25_pikachu_nicknamed_pokeldn_e0280b36"), blank()),
    Preset("gmax-pikachu", _ref("core.pokeldn.swsh.gift_builder.gigantamax_pikachu_9599164e"), _ref("core.pokeldn.swsh.gift_builder.pokemon_22464231"),
           _ref("core.pokeldn.swsh.gift_builder.a_level_25_pikachu_that_can_gigantamax_at_the_top_dynam_8106641e"),
           blank(gigantamax=True, dynamax_level=10)),
    Preset("egg", _ref("core.pokeldn.swsh.gift_builder.pikachu_egg_db0a4bdd"), _ref("core.pokeldn.swsh.gift_builder.pokemon_22464231"), _ref("core.pokeldn.swsh.gift_builder.an_egg_that_hatches_into_pikachu_7f0e9844"),
           blank(kind="egg", level=1, nickname="")),
    Preset("master-balls", _ref("core.pokeldn.swsh.gift_builder.three_master_balls_c74548de"), "Items", _ref("core.pokeldn.swsh.gift_builder.three_master_balls_in_the_bag_dbb9a06b"),
           blank(kind="items", items=[[1, 3]])),
    Preset("rare-candies", _ref("core.pokeldn.swsh.gift_builder.ten_rare_candies_6fc8f9d9"), "Items", _ref("core.pokeldn.swsh.gift_builder.ten_rare_candies_in_the_bag_943c500a"),
           blank(kind="items", items=[[50, 10]])),
    Preset("training-kit", _ref("core.pokeldn.swsh.gift_builder.training_kit_076e65c4"), "Items",
           _ref("core.pokeldn.swsh.gift_builder.rare_candies_exp_candy_xl_pp_max_an_ability_capsule_and_351ae7e6"),
           blank(kind="items", items=[[50, 10], [1128, 5], [53, 3], [645, 1], [795, 3], [796, 1]])),
    Preset("bp", _ref("core.pokeldn.swsh.gift_builder.10_battle_points_4ef116e9"), "Items", _ref("core.pokeldn.swsh.gift_builder.adds_10_bp_up_to_the_game_s_9999_5169a377"), blank(kind="bp", bp=10)),
    Preset("money", _ref("core.pokeldn.swsh.gift_builder.pocket_money_0c8a15ef"), "Items", _ref("core.pokeldn.swsh.gift_builder.adds_100_000_to_the_player_s_money_62f1dfa1"),
           blank(kind="money", money=100000)),
    Preset("pikachu-uniform", _ref("core.pokeldn.swsh.gift_builder.pikachu_uniform_ac84b0e7"), _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), _ref("core.pokeldn.swsh.gift_builder.the_pikachu_outfit_in_the_wardrobe_1d6f24ab"),
           blank(kind="clothing", outfits=["pikachu-uniform"])),
    Preset("eevee-uniform", _ref("core.pokeldn.swsh.gift_builder.eevee_uniform_39e4bad7"), _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), _ref("core.pokeldn.swsh.gift_builder.the_eevee_outfit_in_the_wardrobe_26614934"),
           blank(kind="clothing", outfits=["eevee-uniform"])),
    Preset("tracksuit", _ref("core.pokeldn.swsh.gift_builder.tracksuit_62ac1521"), _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), _ref("core.pokeldn.swsh.gift_builder.the_tracksuit_set_in_the_wardrobe_eb12aacf"),
           blank(kind="clothing", outfits=["tracksuit"])),
    Preset("leon-cap-tights", _ref("core.pokeldn.swsh.gift_builder.leon_s_cap_and_tights_bb408f8d"), _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), _ref("core.pokeldn.swsh.gift_builder.leon_s_cap_and_tights_in_the_wardrobe_c5323f78"),
           blank(kind="clothing", outfits=["leon-cap-tights"])),
    Preset("gold-backpack", _ref("core.pokeldn.swsh.gift_builder.gold_studded_backpack_adef657f"), _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), _ref("core.pokeldn.swsh.gift_builder.a_gold_studded_backpack_in_the_wardrobe_1e6e4d4a"),
           blank(kind="clothing", outfits=["gold-backpack"])),
    Preset("tees", _ref("core.pokeldn.swsh.gift_builder.four_poke_ball_tees_61ec16b7"), _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), _ref("core.pokeldn.swsh.gift_builder.the_four_poke_ball_guy_and_pokemon_quest_tees_2da45d5f"),
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
        raise ValueError(_ref("core.pokeldn.swsh.gift_builder.the_card_id_is_1_to_65535_b5091d1d"))
    if kind in ("pokemon", "egg"):
        egg = kind == "egg"
        level = 1 if egg else _int(state, "level")
        if not egg and not 0 <= level <= 100:
            raise ValueError(_ref("core.pokeldn.swsh.gift_builder.the_level_is_0_to_100_0_lets_the_game_roll_one_c61399f5"))
        if (item := _int(state, "item")) > MAX_ITEM:
            raise ValueError(_message('core.pokeldn.swsh.gift_builder.sword_and_shield_have_no_item_above_value0_3b116fb4', value0=MAX_ITEM))
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
        if (nature := state.get("nature")) not in (None, ""):
            if not 0 <= int(nature) < len(NATURES):
                raise ValueError(_message('core.pokeldn.swsh.gift_builder.the_nature_is_0_to_value0_e7bdc32e', value0=len(NATURES) - 1))
            fields["nature"] = int(nature)
        try:
            raw = wc8.pokemon_card(species, level=level, form=form,
                                   moves=moves, nickname=state.get("nickname") or None,
                                   ot=None if egg else state.get("ot") or None, card_id=card_id, **fields)
        except ValueError as exc:
            raise ValueError(_message('core.pokeldn.swsh.gift_builder.names_value0_ea870e9d', value0=exc)) from None
        if egg or fields.get("gigantamax"):
            raw = _patch(raw, {TITLE_AT: bytes([TITLE_EGG if egg else TITLE_GMAX])})
        return raw
    if kind == "items":
        pairs = [(int(i or 0), int(q or 0)) for i, q in state.get("items", ()) if int(i or 0)]
        if not pairs:
            raise ValueError(_ref("core.pokeldn.swsh.gift_builder.add_at_least_one_item_027d7846"))
        if len(pairs) > 6:
            raise ValueError(_ref("core.pokeldn.swsh.gift_builder.a_card_carries_six_items_at_most_800c28f9"))
        for item, quantity in pairs:
            if not 0 < item <= MAX_ITEM:
                raise ValueError(_message('core.pokeldn.swsh.gift_builder.sword_and_shield_have_no_item_value0_5cf14a71', value0=item))
            if not 0 < quantity <= 999:
                raise ValueError(_ref("core.pokeldn.swsh.gift_builder.each_quantity_is_1_to_999_8be3dbfe"))
        payload = b"".join(struct.pack("<HH", i, q) for i, q in pairs)
        return _card(card_id, KIND_ITEMS, TITLE_ITEM, payload)
    if kind == "clothing":
        return _card(card_id, KIND_CLOTHING, TITLE_CLOTHING, clothing_payload(state.get("outfits", ())))
    if kind == "bp":
        amount = _int(state, "bp")
        if not 0 < amount <= 9999:
            raise ValueError(_ref("core.pokeldn.swsh.gift_builder.battle_points_are_1_to_9999_2e6591ba"))
        return _card(card_id, KIND_BP, TITLE_BP, struct.pack("<I", amount))
    if kind == "money":
        amount = _int(state, "money")
        if not 0 < amount <= MAX_MONEY:
            raise ValueError(_message('core.pokeldn.swsh.gift_builder.money_is_1_to_value0_60e05a52', value0=MAX_MONEY))
        return _card(card_id, KIND_MONEY, TITLE_MONEY, struct.pack("<I", amount))
    raise ValueError(_message('core.pokeldn.swsh.gift_builder.unknown_gift_kind_value0_r_ec9c77c5', value0=kind))


def clothing_payload(keys):
    """Outfit keys -> the 96 bytes at +0x20: six (category, index) u32 pairs for a male player, then six
    for a female one (0x01015eb0 picks a set by the player's gender, 0x01424c20)."""
    try:
        outfits = [OUTFIT[k] for k in dict.fromkeys(keys)]
    except KeyError as exc:
        raise ValueError(_message('core.pokeldn.swsh.gift_builder.unknown_outfit_value0_r_f3aa65c7', value0=exc.args[0])) from None
    if not outfits:
        raise ValueError(_ref("core.pokeldn.swsh.gift_builder.pick_at_least_one_outfit_a88f8a11"))
    payload = b""
    for side in ("male", "female"):
        pairs = [pair for o in outfits for pair in getattr(o, side)]
        if len(pairs) > CLOTHING_SLOTS:
            raise ValueError(_message('core.pokeldn.swsh.gift_builder.a_card_carries_value0_pieces_of_clothing_at_most_c4bc7c37', value0=CLOTHING_SLOTS))
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
    names = {"pokemon": state.get("nickname") or _ref("core.pokeldn.swsh.gift_builder.pokemon_22464231"), "egg": _ref("core.pokeldn.swsh.gift_builder.pokemon_egg_671f2394"), "items": "Items",
             "clothing": _ref("core.pokeldn.swsh.gift_builder.clothing_5bea3ab3"), "bp": _ref("core.pokeldn.swsh.gift_builder.battle_points_c484f837"), "money": "Money"}
    return gift_file.from_record(record(state), name=names.get(state.get("kind"), "Sword/Shield gift"))


def describe(state, name=lambda kind, n: f"{kind} #{n}"):
    """(when it applies, [what happens]); `name(kind, id)` names a species or an item."""
    kind = state.get("kind", "pokemon")
    when = _ref("core.pokeldn.swsh.gift_builder.listed_under_mystery_gift_the_player_picks_it_then_it_l_dade4d6f")
    if kind == "pokemon":
        level = _int(state, "level")
        from pokeldn.app import i18n
        details = [_message("core.gift.pokemon.level", level=level) if level else _ref("core.gift.pokemon.random_level")]
        if state.get("nature") not in (None, ""):
            details.append(i18n.EntityRef("swsh", i18n.EntityKind.NATURE, int(state["nature"])))
        if state.get("shiny"):
            details.append(_ref("core.presentation.shiny"))
        if state.get("gigantamax"):
            details.append(_ref("core.gift.pokemon.gigantamax"))
        details = i18n.text("core.presentation.list_separator").join(i18n.render(part) for part in details)
        lines = [_message("core.gift.pokemon.description", species=name("species", state.get("species")), details=details)]
        if _int(state, "item"):
            lines.append(_message("core.gift.pokemon.holding", item=name("item", state.get("item"))))
    elif kind == "egg":
        lines = [_message("core.gift.egg.description", species=name("species", state.get("species")))]
    elif kind == "items":
        lines = [_message("core.gift.item.description", item=name("item", i), quantity=q) for i, q in state.get("items", ()) if int(i or 0)]
    elif kind == "clothing":
        lines = [_message("core.gift.clothing.destination", clothing=OUTFIT[k].label) for k in state.get("outfits", ()) if k in OUTFIT]
        lines.append(_ref("core.pokeldn.swsh.gift_builder.the_card_holds_a_male_and_a_female_version_the_player_g_97694f8b"))
    elif kind == "money":
        lines = [_message("core.gift.money.description", quantity=_int(state, "money"), maximum=MAX_MONEY)]
    else:
        lines = [_message("core.gift.bp.description", quantity=_int(state, "bp"))]
    lines.append(_message("core.gift.card.repeat", card_id=_int(state, "card_id", 9999)))
    return when, lines

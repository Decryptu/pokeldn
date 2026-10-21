from pokeldn.app.i18n import message_ref as _message
from pokeldn.app.i18n import ref as _ref
"""The app's FireRed/LeafGreen gift builder: a preset, or a gift built from a plain form state (JSON),
compiled to a .pokegift for every cartridge [docs/gifts.md]."""

import hashlib
import copy
import re
from dataclasses import dataclass, field
from typing import Callable

from pokeldn import gifts
from pokeldn.frlg.gift import file as gift_file, wonder_news
from pokeldn.frlg.gift import gift_composer as gc, wonder_card_events as events
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
from pokeldn.frlg.rom import buffer_script, builds, custom_code
from pokeldn.frlg.save.species_names import SPECIES

CARTRIDGES = {code: _ref(f"core.frlg.cartridge.{code}") for code in builds.BUILDS}
KINDS = (("card", _ref("core.pokeldn.frlg.gift.builder.wonder_card_81ebceeb"), "gift"), ("news", _ref("core.pokeldn.frlg.gift.builder.wonder_news_d58adf54"), "book-open"), ("code", _ref("core.pokeldn.frlg.gift.builder.console_code_33f04c21"), "cpu"))
# (key, who, where, map group, map number, object id); a bound script replaces that person's own.
GIVERS = (
    ("deliveryman", _ref("core.pokeldn.frlg.gift.builder.the_delivery_man_2949b642"), _ref("core.pokeldn.frlg.gift.builder.any_pokemon_center_after_the_card_is_saved_1f2cd6a9"), None, None, None),
    ("mom", _ref("core.gift.giver.mom"), _ref("core.pokeldn.frlg.gift.builder.the_player_s_house_0733cb87"), events.MAP_GROUP_PLAYERS_HOUSE, events.MAP_NUM_PLAYERS_HOUSE,
     events.PLAYERS_HOUSE_OBJECT_MOM),
    ("pallet-man", _ref("core.pokeldn.frlg.gift.builder.the_man_in_pallet_town_6793700c"), _ref("core.pokeldn.frlg.gift.builder.south_of_pallet_town_93a22f7b"), events.MAP_GROUP_PALLET_TOWN,
     events.MAP_NUM_PALLET_TOWN, events.PALLET_TOWN_OBJECT_FAT_MAN),
)
STEPS = (("pokemon", _ref("core.pokeldn.frlg.gift.builder.pokemon_22464231")), ("item", _ref("core.gift.step.item")), ("egg", _ref("core.gift.step.egg")), ("battle", _ref("core.pokeldn.frlg.gift.builder.wild_battle_b53d82b0")),
         ("message", _ref("core.pokeldn.frlg.gift.builder.message_2f77668a")))
FULL = "Oh, there is no room!\nPlease make room and come back."

# Internal ids 277..411, matched by species name to pret/pokefirered's
# include/constants/pokedex.h. Ids 252..276 are the old Unown slots, not Hoenn Pokemon.
NATIONAL_SPECIES = (
    252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266,
    267, 268, 269, 270, 271, 272, 273, 274, 275, 290, 291, 292, 276, 277, 285,
    286, 327, 278, 279, 283, 284, 320, 321, 300, 301, 352, 343, 344, 299, 324,
    302, 339, 340, 370, 341, 342, 349, 350, 318, 319, 328, 329, 330, 296, 297,
    309, 310, 322, 323, 363, 364, 365, 331, 332, 361, 362, 337, 338, 298, 325,
    326, 311, 312, 303, 307, 308, 333, 334, 360, 355, 356, 315, 287, 288, 289,
    316, 317, 357, 293, 294, 295, 366, 367, 368, 359, 353, 354, 336, 335, 369,
    304, 305, 306, 351, 313, 314, 345, 346, 347, 348, 280, 281, 282, 371, 372,
    373, 374, 375, 376, 377, 378, 379, 382, 383, 384, 380, 381, 385, 386, 358,
)


def national_species(species):
    """A builder's GBA species id -> National Dex number for its app preview."""
    if 0 <= species <= 251:
        return species
    return NATIONAL_SPECIES[species - 277] if 277 <= species <= 411 else 0


def internal_species(species):
    """National Dex -> the FRLG cartridge's internal species ID, only at an adapter boundary."""
    species = int(species or 0)
    if 0 <= species <= 251:
        return species
    return 277 + NATIONAL_SPECIES.index(species) if species in NATIONAL_SPECIES else 0


def entity_state(state):
    """Versioned application state always stores national species IDs."""
    result = copy.deepcopy(state)
    if result.get("entity_schema") == 1:
        return result
    for step in result.get("steps", ()):
        if "species" in step:
            step["species"] = national_species(int(step["species"] or 0))
    if result.get("card", {}).get("icon") is not None:
        result["card"]["icon"] = national_species(int(result["card"]["icon"] or 0))
    result["entity_schema"] = 1
    return result


def cartridge_state(state):
    """Convert application references to native IDs without mutating saved input."""
    result = copy.deepcopy(state)
    if result.pop("entity_schema", None) != 1:
        return result
    for step in result.get("steps", ()):
        if "species" in step:
            step["species"] = internal_species(step["species"])
    if result.get("card", {}).get("icon") is not None:
        result["card"]["icon"] = internal_species(result["card"]["icon"])
    return result


def species_names():
    """[(internal id, name)] the GBA cartridge knows, by name."""
    return sorted(((n, name.replace("_", " ").title()) for n, name in SPECIES.items()
                   if 0 < n <= gc.MAX_POKEMON_SPECIES and not name.startswith("OLD_UNOWN")),
                  key=lambda pair: pair[1])


def species_name(n):
    return SPECIES.get(int(n or 0), f"#{n}").replace("_", " ").title()


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    group: str
    summary: str
    args: tuple
    when: str = ""                  # where the player uses it, shown before sending
    species_id: int = 0             # National Pokedex number for the app sprite, not a GBA internal id

    @property
    def state(self):
        """The preset as an editable form, or None when the form cannot express it."""
        if self.args[0] != "--gift" or "--event-pokemon" in self.args:
            return None
        return state_of(GIFT_REGISTRY.entry(self.args[1]).definition)


def _card(slug, label, summary, species_id=0):
    return Preset(slug, label, _ref("core.pokeldn.frlg.gift.builder.wonder_cards_012636f6"), summary, ("--gift", slug), species_id=species_id)


EVENTS = _ref("core.pokeldn.frlg.gift.builder.event_pokemon_b208bbb6")
ANNIVERSARY = _ref("core.pokeldn.frlg.gift.builder.10th_anniversary_pokemon_17668fbc")


def _event(name, species_id, summary, group=EVENTS):
    """A fresh copy PKHeX makes at launch [docs/frlg_gift.md, Event Pokemon]."""
    key = "event-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return Preset(key, _ref(f"core.frlg.gift.{key}.title"), group, summary, ("--gift", events.GIFT_EVENT_POKEMON, "--event-pokemon", name),
                  species_id=species_id)


POKEMON_TOOLS = _ref("core.pokeldn.frlg.gift.builder.change_a_pokemon_34e02aca")
GAME_CHANGES = _ref("core.pokeldn.frlg.gift.builder.game_changes_b81b90ad")
MORE_GIFTS = _ref("core.pokeldn.frlg.gift.builder.more_gifts_db70eb44")
# A card the delivery man turns into a per-frame hook; it stops any game boost [docs/frlg_gift.md].
STOPS_BOOSTS = _ref("core.gift.boost.stops")
DELIVERY_MAN = _ref("core.pokeldn.frlg.gift.builder.after_the_card_is_saved_talk_to_the_delivery_man_on_2f__a9f3aa59")


def _team(slug, label, group, summary, species_id=0):
    """A GB-Link Team card [team_cards.py]: the player talks to the delivery man to use it."""
    return Preset(slug, label, group, summary, ("--gift", slug), when=DELIVERY_MAN, species_id=species_id)


def _code(key, label, summary, *args):
    return Preset(key, label, _ref("core.pokeldn.frlg.gift.builder.read_the_save_2faa2733"), summary, args,
                  when=_ref("core.pokeldn.frlg.gift.builder.receive_it_through_mystery_gift_then_read_the_results_i_495dc852"))


@dataclass(frozen=True)
class Option:
    """One setting: a switch when `choices` is empty, else (value, label) pairs."""
    key: str
    label: str
    default: object
    choices: tuple = ()
    help: str = ""


def _settings(options, chosen):
    """`chosen` with every unknown or missing setting at its default."""
    chosen = chosen if isinstance(chosen, dict) else {}
    out = {}
    for option in options:
        value = chosen.get(option.key, option.default)
        valid = isinstance(value, bool) if not option.choices else value in {k for k, _ in option.choices}
        out[option.key] = value if valid else option.default
    return out


@dataclass(frozen=True)
class Boost:
    """One resident hook [docs/frlg_rom.md, install-resident] and the settings the app shows for it."""
    key: str
    label: str
    summary: str
    hook: str
    compose: Callable = field(compare=False)    # settings -> (hook parameters, [what the console gets])
    options: tuple = ()


# Several hooks run at once as a chain [buffer_script.CHAIN]; the save keeps one set.
BOOSTS = _ref("core.pokeldn.frlg.gift.builder.game_boosts_810e5297")
BOOSTS_INTRO = (_ref("core.pokeldn.frlg.gift.builder.a_game_boost_is_a_change_to_how_your_game_plays_such_as_d95993c5"))
GROUP_INTROS = {
    BOOSTS: BOOSTS_INTRO,
    "Read the save": _ref("core.pokeldn.frlg.gift.builder.read_your_trainer_id_tid_secret_id_sid_or_your_party_s__f07c2cf0"),
}
MOM = _ref("core.pokeldn.frlg.gift.builder.mom_restores_your_boosts_4729dd92")
R, B, SELECT = "0x100", "0x2", "0x4"
# L opens the Help System; only R's toggle has a flag the hooks hold off [docs/frlg_rom.md, turbo].
BUTTONS = ((R, _ref("core.pokeldn.frlg.gift.builder.hold_r_5be9c8e4")), (B, _ref("core.pokeldn.frlg.gift.builder.hold_b_also_runs_ec2b0b51")), (SELECT, _ref("core.pokeldn.frlg.gift.builder.hold_select_also_uses_the_registered_item_c1d02a61")))
BUTTON_NAME = {R: "R", B: "B", SELECT: "Select"}
MOM_STEPS = _message("core.gift.boost.restore", mom=MOM)
KEEP = Option("keep", _ref("core.pokeldn.frlg.gift.builder.save_boosts_for_later_1aecdbec"), False,
              help=_ref("core.pokeldn.frlg.gift.builder.keep_a_copy_of_these_boosts_in_your_save_dab0a0ea") + MOM_STEPS)
SPEEDS = (("1", "x1"), ("2", "x2"), ("3", "x3"), ("4", "x4"))
WHERE = (("both", _ref("core.pokeldn.frlg.gift.builder.overworld_and_battles_3e80a007")), ("field", _ref("core.pokeldn.frlg.gift.builder.overworld_only_a0d0984b")), ("battle", _ref("core.pokeldn.frlg.gift.builder.battles_only_47397c2b")))
SLOWER = (("1", _ref("core.pokeldn.frlg.gift.builder.x2_slower_7c149c29")), ("3", _ref("core.pokeldn.frlg.gift.builder.x4_slower_ec7b3453")), ("7", _ref("core.pokeldn.frlg.gift.builder.x8_slower_4274cd87")))
# A pass budget in scanlines: measured smooth at field=3 battle=3, stuttering without it [frlg_rom.md].
BUDGET = 228
RESIDENT_AREA = 0x400                       # 0x0203FC00..0x02040000


def _turbo(o):
    speed, text = int(o["speed"]), o["text"]
    if speed == 1 and not text:
        raise ValueError(_ref("core.pokeldn.frlg.gift.builder.speed_up_the_game_pick_a_speed_above_x1_or_faster_text_13a06277"))
    params = {"extra": 4 if text else 0,
              "field": speed - 1 if o["where"] in ("both", "field") else 0,
              "battle": speed - 1 if o["where"] in ("both", "battle") else 0,
              "hold": 0 if o["button"] == "always" else int(o["button"], 0)}
    if speed >= 3:
        params["budget"] = BUDGET
    lines = []
    if speed > 1:
        how = _ref("core.gift.boost.always") if o["button"] == "always" else _message("core.gift.boost.held", button=BUTTON_NAME[o['button']])
        lines.append(_message("core.gift.boost.turbo", where=dict(WHERE)[o['where']], speed=speed, when=how))
    if text:
        lines.append(_ref("core.pokeldn.frlg.gift.builder.text_prints_faster_5a4694d9"))
    return params, lines


def _shiny(o):
    return {"slow": int(o["button"], 0), "slow_frames": int(o["slower"])}, [
        _ref("core.pokeldn.frlg.gift.builder.counts_down_to_the_next_shiny_wild_pokemon_in_the_grass_b10a3129"),
        _message("core.gift.boost.shiny", slower=dict(SLOWER)[o['slower']], button=BUTTON_NAME[o['button']])]


def _noclip(o):
    return {"hold": int(o["button"], 0)}, [
        _message("core.gift.boost.noclip", button=BUTTON_NAME[o['button']])]


def _plain(*lines):
    return lambda o: ({}, list(lines))


BOOST_LIST = (
    Boost("hook-turbo", _ref("core.pokeldn.frlg.gift.builder.speed_up_the_game_108bf789"), _ref("core.pokeldn.frlg.gift.builder.x2_x3_or_x4_in_the_overworld_and_in_battle_and_faster_t_f54d6c59"),
          "turbo-lite", _turbo, (Option("speed", _ref("core.pokeldn.frlg.gift.builder.game_speed_2e6651c0"), "2", SPEEDS), Option("where", _ref("core.gift.boost.where"), "both", WHERE),
                            Option("button", _ref("core.gift.boost.when"), R, (("always", _ref("core.pokeldn.frlg.gift.builder.always_on_044ba8a9")),) + BUTTONS),
                            Option("text", _ref("core.pokeldn.frlg.gift.builder.faster_text_d6ce51e9"), True, help=_ref("core.pokeldn.frlg.gift.builder.dialogue_prints_several_letters_a_frame_6247dfaa")))),
    Boost("hook-noclip", _ref("core.pokeldn.frlg.gift.builder.walk_through_walls_00607718"), _ref("core.pokeldn.frlg.gift.builder.hold_a_button_to_walk_through_walls_trees_and_water_a6ca9eb2"),
          "noclip", _noclip, (Option("button", _ref("core.gift.boost.when"), R, BUTTONS),)),
    Boost("hook-noencounter", _ref("core.pokeldn.frlg.gift.builder.no_wild_encounters_4c3abfd8"), _ref("core.pokeldn.frlg.gift.builder.no_grass_water_or_roaming_encounters_4e4a5e7a"), "noencounter",
          _plain(_ref("core.pokeldn.frlg.gift.builder.no_grass_water_or_roaming_encounters_fishing_and_sweet__9b8ab620"))),
    Boost("hook-shiny", _ref("core.pokeldn.frlg.gift.builder.shiny_countdown_e785be46"), _ref("core.pokeldn.frlg.gift.builder.counts_down_to_the_next_shiny_in_the_grass_ea598dd3"), "shiny", _shiny,
          (Option("button", _ref("core.pokeldn.frlg.gift.builder.slow_the_game_down_a606f821"), R, BUTTONS), Option("slower", _ref("core.gift.boost.by"), "3", SLOWER))),
    Boost("hook-ivs", _ref("core.pokeldn.frlg.gift.builder.lead_s_ivs_on_screen_d577b8c0"), _ref("core.pokeldn.frlg.gift.builder.the_lead_pokemon_s_ivs_and_nature_top_right_c3e7b189"), "ivs",
          _plain(_ref("core.pokeldn.frlg.gift.builder.the_lead_pokemon_s_six_ivs_and_its_nature_top_right_of__0cac3a28"))),
    Boost("hook-follower", _ref("core.pokeldn.frlg.gift.builder.pokemon_follower_48ee91f3"), _ref("core.pokeldn.frlg.gift.builder.your_lead_pokemon_walks_behind_you_d91a3e43"), "follower",
          _plain(_ref("core.pokeldn.frlg.gift.builder.the_lead_pokemon_walks_behind_you_hops_ledges_with_you__cfff206c"))),
)
BOOST = {b.key: b for b in BOOST_LIST}
# Each draws in the top-right corner [docs/frlg_rom.md, turbo overlay]; one at a time.
DRAWING = ("hook-shiny", "hook-ivs")


def _hook_args(name, params, keep):
    script = (("--buffer-script", "save-write") if keep
              else ("--buffer-script", "install-resident", "--write-unsafe"))
    out = [*script, "--resident", name]
    for key, value in params.items():
        out += ["--resident-param", f"{key}={value}"]
    return tuple(out)


@dataclass(frozen=True)
class Boosts:
    """The Game boosts preset: the ticked boosts, each with its settings, sent as one chain. Settings:
    {"on": [boost keys], "keep": bool, boost key: {its settings}}."""
    key: str = "boosts"
    label: str = _ref("core.pokeldn.frlg.gift.builder.game_boosts_810e5297")
    group: str = BOOSTS
    summary: str = _ref("core.pokeldn.frlg.gift.builder.select_boosts_to_run_together_save_them_for_mom_to_rest_c9dbaf19")
    members: tuple = BOOST_LIST
    state = None

    @property
    def args(self):
        return self.arguments()

    def settings(self, chosen=None) -> dict:
        chosen = chosen if isinstance(chosen, dict) else {}
        on = chosen.get("on", ["hook-turbo"])
        out = {"on": [b.key for b in self.members if isinstance(on, list) and b.key in on],
               **_settings((KEEP,), chosen)}
        for boost in self.members:
            out[boost.key] = _settings(boost.options, chosen.get(boost.key))
        return out

    def size(self, chosen=None) -> int:
        """Bytes of the resident area the ticked boosts take."""
        from pokeldn.frlg.rom.resident_stubs import STUBS
        return sum(len(STUBS[BOOST[key].hook][0]) for key in self.settings(chosen)["on"])

    def built(self, chosen=None):
        """-> (launcher args, [what the console gets], kept because too large); raises ValueError."""
        s = self.settings(chosen)
        on = [BOOST[key] for key in s["on"]]
        if not on:
            raise ValueError(_ref("core.pokeldn.frlg.gift.builder.tick_at_least_one_boost_baddb14e"))
        if len(on) > 1 and BOOST["hook-follower"] in on:
            raise ValueError(_ref("core.pokeldn.frlg.gift.builder.the_pokemon_follower_runs_alone_untick_the_other_boosts_b60adc24"))
        drawing = [b.label for b in on if b.key in DRAWING]
        if len(drawing) > 1:
            raise ValueError(_message('core.pokeldn.frlg.gift.builder.value0_both_draw_in_the_top_right_corner_untick__af986e7e', value0=' and '.join(drawing)))
        if self.size(s) > RESIDENT_AREA:
            raise ValueError(_message('core.pokeldn.frlg.gift.builder.these_boosts_take_value0_bytes_together_the_cons_08b7a675', value0=self.size(s), value1=RESIDENT_AREA))
        name = buffer_script.CHAIN.join(b.hook for b in on)
        params, lines = {}, []
        for boost in on:
            own, said = boost.compose(s[boost.key])
            params.update({(f"{boost.hook}.{k}" if len(on) > 1 else k): v for k, v in own.items()})
            lines += said
        too_large = False
        try:
            for code in CARTRIDGES:
                buffer_script.build_resident_save_blob(name, build=code, **params)
            buffer_script.build_install_resident(name, build="BPRF", **params)
        except buffer_script.BufferScriptError as exc:
            if "receive buffer" not in str(exc):
                raise ValueError(str(exc)) from None
            too_large = True
        keep = s["keep"] or too_large
        lines.append((_ref("core.pokeldn.frlg.gift.builder.these_boosts_are_saved_in_your_game_ec49a072") + MOM_STEPS) if keep else
                     _ref("core.pokeldn.frlg.gift.builder.these_boosts_stop_when_you_restart_the_game_or_turn_off_16017922"))
        return _hook_args(name, params, keep), lines, too_large

    def arguments(self, chosen=None) -> tuple:
        """The launcher's flags; settings problem() refuses fall back to the defaults'."""
        try:
            return self.built(chosen)[0]
        except ValueError:
            return self.built()[0]

    def effects(self, chosen=None) -> list:
        try:
            return self.built(chosen)[1]
        except ValueError:
            return []

    def problem(self, chosen=None) -> str:
        try:
            self.built(chosen)
        except ValueError as exc:
            return str(exc)
        return ""


PRESETS = (
    _card("beast-cutscene", _ref("core.pokeldn.frlg.gift.builder.legendary_beast_6ffe34af"), _ref("core.pokeldn.frlg.gift.builder.two_berries_a_master_ball_and_a_battle_with_the_beast_t_30133f22")),
    _card("celebi", _ref("core.frlg.gift.celebi.title"), _ref("core.pokeldn.frlg.gift.builder.a_level_50_celebi_from_the_delivery_man_aac580f1"), 251),
    _card("master-ball", _ref("core.pokeldn.frlg.gift.builder.master_ball_ac04a988"), _ref("core.pokeldn.frlg.gift.builder.one_master_ball_6055bba9")),
    _card("altering-cave", _ref("core.pokeldn.frlg.gift.builder.altering_cave_6a83ccf4"), _ref("core.pokeldn.frlg.gift.builder.changes_which_pokemon_live_in_altering_cave_15e72483")),
    _card("wish-egg", _ref("core.pokeldn.frlg.gift.builder.wish_egg_5bf7bd6f"), _ref("core.pokeldn.frlg.gift.builder.one_of_six_eggs_that_knows_wish_picked_by_the_console_a573a75a")),
    _card("pokepark-egg", _ref("core.pokeldn.frlg.gift.builder.pokepark_egg_406a0928"), _ref("core.pokeldn.frlg.gift.builder.one_of_fifteen_eggs_with_special_moves_picked_by_the_co_5baafa32")),
    _card("pc-japan-egg", _ref("core.pokeldn.frlg.gift.builder.pokemon_center_japan_egg_44b75dec"), _ref("core.pokeldn.frlg.gift.builder.one_of_four_eggs_with_special_moves_371ee477")),
    _card("starter-egg", _ref("core.pokeldn.frlg.gift.builder.starter_egg_4a1e1652"), _ref("core.pokeldn.frlg.gift.builder.an_egg_of_one_of_the_nine_first_partners_5c55ddb2")),
    _card("rare-berries", _ref("core.pokeldn.frlg.gift.builder.rare_berries_4b5897d0"), _ref("core.pokeldn.frlg.gift.builder.an_enigma_a_lansat_and_a_starf_berry_8b141140")),
    _card("national-dex", _ref("core.pokeldn.frlg.gift.builder.national_pokedex_fe9f1cb9"), _ref("core.pokeldn.frlg.gift.builder.upgrades_the_pokedex_to_the_national_pokedex_0341a59f")),
    _card("porygon-tm-gift", _ref("core.pokeldn.frlg.gift.builder.porygon_tm_gift_0f42a5a7"), _ref("core.pokeldn.frlg.gift.builder.a_porygon_and_a_tm_a5f0bb81"), 137),
    _card("solrock-stamp", _ref("core.pokeldn.frlg.gift.builder.sun_and_moon_rally_solrock_fcc9f89a"), _ref("core.pokeldn.frlg.gift.builder.a_rally_stamp_810675bd")),
    _card("lunatone-stamp", _ref("core.pokeldn.frlg.gift.builder.sun_and_moon_rally_lunatone_06053701"), _ref("core.pokeldn.frlg.gift.builder.a_rally_stamp_810675bd")),
    _card("visiting-trainer", _ref("core.pokeldn.frlg.gift.builder.visiting_trainer_b2cc805e"), _ref("core.pokeldn.frlg.gift.builder.a_trainer_who_waits_in_the_pokemon_center_2a6280c6")),
    _card("battle-count-card", _ref("core.pokeldn.frlg.gift.builder.battle_count_card_8bf1036e"), _ref("core.pokeldn.frlg.gift.builder.a_card_that_counts_link_battles_1cd19f30")),
    _card("worlds-xp", _ref("core.pokeldn.frlg.gift.builder.worlds_xp_68b7757d"), _ref("core.pokeldn.frlg.gift.builder.the_worlds_card_5d5e052f")),
    _team("nature-mint", _ref("core.pokeldn.frlg.gift.builder.nature_mint_2152eb5e"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.pick_which_stat_a_pokemon_s_nature_raises_and_lowers_08f8bb7a")),
    _team("ability-capsule", _ref("core.pokeldn.frlg.gift.builder.ability_capsule_63750efc"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.switches_a_pokemon_to_its_other_ability_8d71f353")),
    _team("poke-ball-changer", _ref("core.pokeldn.frlg.gift.builder.poke_ball_changer_2c9c295f"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.moves_a_pokemon_into_the_ball_you_choose_6a1d2c53")),
    _team("pokemon-gender", _ref("core.pokeldn.frlg.gift.builder.gender_change_abfce378"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.switches_a_pokemon_between_male_and_female_a012d7b9")),
    _team("nickname", _ref("core.pokeldn.frlg.gift.builder.nickname_change_6dd659ac"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.a_new_nickname_or_the_species_name_back_59c7bbaa")),
    _team("stat-judge", _ref("core.pokeldn.frlg.gift.builder.iv_and_ev_judge_14c5ee26"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.shows_a_pokemon_s_nature_six_ivs_and_evs_on_screen_f6aa8c92")),
    _team("hidden-power", _ref("core.pokeldn.frlg.gift.builder.hidden_power_and_max_ivs_3e18c48e"), POKEMON_TOOLS,
          _ref("core.pokeldn.frlg.gift.builder.shows_its_hidden_power_then_can_set_every_iv_to_31_964fff8a")),
    _team("hidden-power-type", _ref("core.pokeldn.frlg.gift.builder.hidden_power_type_155724da"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.gives_hidden_power_the_type_you_pick_fc706f34")),
    _team("ev-training", _ref("core.pokeldn.frlg.gift.builder.ev_training_4bc4cbbb"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.resets_evs_or_maxes_the_stats_you_pick_no_battles_f6ef2e0a")),
    _team("friendship", _ref("core.pokeldn.frlg.gift.builder.friendship_checker_f612b654"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.shows_friendship_and_can_max_it_39e87a53")),
    _team("pp-max", _ref("core.pokeldn.frlg.gift.builder.pp_max_bc56deed"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.every_move_in_the_party_gets_its_most_pp_7d1c856c")),
    _team("max-conditions", _ref("core.pokeldn.frlg.gift.builder.max_conditions_99cb993b"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.contest_stats_to_the_max_feebas_then_evolves_a059fc2e")),
    _team("pokerus", _ref("core.pokeldn.frlg.gift.builder.pokerus_afa5a790"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.the_party_catches_pokerus_which_doubles_evs_earned_52fd52cc")),
    _team("unown-letters", _ref("core.pokeldn.frlg.gift.builder.unown_letter_633103d0"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.gives_an_unown_any_letter_87e0bbb6")),
    _team("trade-evolution", _ref("core.pokeldn.frlg.gift.builder.trade_evolution_347cc317"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.evolves_a_trade_evolution_pokemon_no_trade_b4df035b")),
    _team("espeon-umbreon", _ref("core.pokeldn.frlg.gift.builder.espeon_or_umbreon_2abf2a5d"), POKEMON_TOOLS, _ref("core.pokeldn.frlg.gift.builder.a_friendly_eevee_evolves_into_the_one_you_pick_7f26e828")),
    _team("move-tutor", _ref("core.pokeldn.frlg.gift.builder.move_relearner_and_deleter_dad3e63f"), POKEMON_TOOLS,
          _ref("core.pokeldn.frlg.gift.builder.relearn_or_forget_a_move_the_move_tutors_teach_again_36c06d16")),
    _team("speed-2", _ref("core.pokeldn.frlg.gift.builder.double_speed_d03c9dbb"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.r_turns_double_speed_on_and_off_9b2bf78f") + STOPS_BOOSTS),
    _team("speed-3", _ref("core.pokeldn.frlg.gift.builder.triple_speed_48f29734"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.r_turns_triple_speed_on_and_off_97ad1028") + STOPS_BOOSTS),
    _team("speed-4", _ref("core.pokeldn.frlg.gift.builder.quadruple_speed_a6358a6f"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.r_turns_x4_speed_on_and_off_ef9b9848") + STOPS_BOOSTS),
    _team("speed-0-75", _ref("core.pokeldn.frlg.gift.builder.slower_game_a915a260"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.r_plays_a_little_slower_42e82c76") + STOPS_BOOSTS),
    _team("speed-0-5", _ref("core.pokeldn.frlg.gift.builder.half_speed_fb3f333d"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.r_plays_at_half_speed_9cd37977") + STOPS_BOOSTS),
    _team("fast-text", _ref("core.pokeldn.frlg.gift.builder.fast_text_2407ed1f"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.all_text_prints_at_once_until_the_game_is_reset_0c105d69")
          + STOPS_BOOSTS),
    _team("travel-anywhere", _ref("core.pokeldn.frlg.gift.builder.fly_with_r_1213d061"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.r_flies_from_outdoors_no_hm_run_and_bike_anywhere_d120d669")
          + STOPS_BOOSTS),
    _team("pc-anywhere", _ref("core.pokeldn.frlg.gift.builder.pc_anywhere_6c86d4fa"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.r_opens_the_pokemon_boxes_from_anywhere_ac7d7798") + STOPS_BOOSTS),
    _team("hm-moves", _ref("core.pokeldn.frlg.gift.builder.hm_moves_without_hms_0e13254c"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.cut_surf_strength_and_more_with_only_the_badge_0979700a")
          + STOPS_BOOSTS),
    _team("reusable-tms", _ref("core.pokeldn.frlg.gift.builder.reusable_tms_a5a2fa88"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.teaching_a_tm_no_longer_uses_it_up_b24551af") + STOPS_BOOSTS),
    _team("physical-special-split", _ref("core.pokeldn.frlg.gift.builder.physical_special_split_5bc19087"), GAME_CHANGES,
          _ref("core.pokeldn.frlg.gift.builder.each_move_is_physical_or_special_as_in_later_games_2500cc6d") + STOPS_BOOSTS),
    _team("exp-share", _ref("core.pokeldn.frlg.gift.builder.exp_share_for_all_cd25b222"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.the_whole_party_gets_exp_from_every_battle_87ceaf67")
          + STOPS_BOOSTS),
    _team("shiny-hunting", _ref("core.pokeldn.frlg.gift.builder.shiny_chain_12bb5ce5"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.meeting_one_species_again_and_again_makes_it_shiny_more_9bee65b7") + STOPS_BOOSTS),
    _team("roamer", _ref("core.pokeldn.frlg.gift.builder.roaming_pokemon_finder_a62fa8c2"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.says_where_the_roaming_pokemon_is_and_can_lure_it_65356aed")
          + STOPS_BOOSTS),
    _team("no-encounters", _ref("core.pokeldn.frlg.gift.builder.no_encounters_or_repel_edca67f7"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.no_wild_pokemon_or_only_stronger_ones_until_the_game_is_8e001558")),
    _team("legendary-respawn", _ref("core.pokeldn.frlg.gift.builder.legendary_respawn_cecc2bb8"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.legendaries_you_beat_without_catching_come_back_ca258685")),
    _team("instant-eggs", _ref("core.pokeldn.frlg.gift.builder.instant_eggs_04f4621c"), GAME_CHANGES, _ref("core.pokeldn.frlg.gift.builder.hatches_the_eggs_you_carry_or_readies_the_day_care_egg_ebc4f492")),
    _team("gift-box", _ref("core.pokeldn.frlg.gift.builder.gift_box_643f6280"), MORE_GIFTS, _ref("core.pokeldn.frlg.gift.builder.100_000_money_99_rare_candies_and_1_000_coins_addbbdd9")),
    _team("pocket-casino", _ref("core.pokeldn.frlg.gift.builder.pocket_casino_e5d72a6c"), MORE_GIFTS, _ref("core.pokeldn.frlg.gift.builder.play_the_slot_machines_from_the_delivery_man_4803ecfb")),
    _team("gift-ribbons", _ref("core.pokeldn.frlg.gift.builder.gift_ribbons_a2bec92e"), MORE_GIFTS, _ref("core.pokeldn.frlg.gift.builder.the_party_gets_the_seven_event_ribbons_4571aa42")),
    _team("trainer-ids", _ref("core.pokeldn.frlg.gift.builder.trainer_id_and_secret_id_on_screen_c3272287"), MORE_GIFTS,
          _ref("core.pokeldn.frlg.gift.builder.the_delivery_man_tells_your_trainer_id_and_secret_id_fc1ffb0a")),
    _team("gender-swap", _ref("core.pokeldn.frlg.gift.builder.new_trainer_name_or_look_aeead89a"), MORE_GIFTS, _ref("core.pokeldn.frlg.gift.builder.rename_yourself_or_switch_between_boy_and_girl_468b6824")),
    _team("rival-name", _ref("core.pokeldn.frlg.gift.builder.rename_your_rival_68b63168"), MORE_GIFTS, _ref("core.pokeldn.frlg.gift.builder.gives_your_rival_a_new_name_3ba493ed")),
    _event("WISHMKR Jirachi", 385, _ref("core.pokeldn.frlg.gift.builder.the_colosseum_bonus_disc_jirachi_level_5_034748be")),
    _event("CHANNEL Jirachi", 385, _ref("core.pokeldn.frlg.gift.builder.the_pokemon_channel_jirachi_level_5_2033eef7")),
    _event("Aura Mew", 151, _ref("core.pokeldn.frlg.gift.builder.the_aura_mew_level_10_5738e39d")),
    _event("MYSTRY Mew", 151, _ref("core.pokeldn.frlg.gift.builder.the_mystry_mew_level_10_b25aedfe")),
    _event("DOEL Deoxys", 386, _ref("core.pokeldn.frlg.gift.builder.the_doel_deoxys_level_70_c947c1cd")),
    _event("SPACE C Deoxys", 386, _ref("core.pokeldn.frlg.gift.builder.the_space_c_deoxys_level_70_6e507e3d")),
    _event("ROCKS Metang", 375, _ref("core.pokeldn.frlg.gift.builder.the_rocks_metang_level_30_with_the_national_ribbon_2f22be9d")),
    *(_event(f"10 ANIV {name}", species, _ref("core.pokeldn.frlg.gift.builder.level_70_from_the_10th_anniversary_02247f22"), ANNIVERSARY)
      for species, name in ((1, _ref("core.pokeldn.frlg.gift.builder.bulbasaur_41c74c2e")), (6, "Charizard"), (9, "Blastoise"), (25, _ref("core.pokeldn.frlg.gift.builder.pikachu_a7c280e7")),
                            (65, "Alakazam"), (144, "Articuno"), (145, "Zapdos"), (146, "Moltres"),
                            (149, "Dragonite"), (157, "Typhlosion"), (196, "Espeon"), (197, "Umbreon"),
                            (243, "Raikou"), (244, "Entei"), (245, "Suicune"), (248, "Tyranitar"),
                            (251, "Celebi"), (257, "Blaziken"), (359, "Absol"), (380, "Latias"), (381, "Latios"))),
    _team("box-eggs", _ref("core.pokeldn.frlg.gift.builder.pokemon_box_eggs_addea864"), EVENTS, _ref("core.pokeldn.frlg.gift.builder.a_swablu_zigzagoon_skitty_or_pichu_egg_with_a_special_m_05c2f355")),
    _team("colosseum-pikachu", _ref("core.pokeldn.frlg.gift.builder.colosseum_pikachu_b9f505f8"), EVENTS, _ref("core.pokeldn.frlg.gift.builder.the_japanese_colosseum_bonus_disc_pikachu_its_japanese__17da228e"), 25),
    _team("ageto-celebi", _ref("core.pokeldn.frlg.gift.builder.ageto_celebi_68ba9c1d"), EVENTS, _ref("core.pokeldn.frlg.gift.builder.the_japanese_colosseum_bonus_disc_celebi_its_japanese_t_521f67e7"), 251),
    _team("mattle-ho-oh", _ref("core.pokeldn.frlg.gift.builder.mattle_ho_oh_afd2e3e5"), EVENTS, _ref("core.pokeldn.frlg.gift.builder.the_ho_oh_colosseum_gave_for_100_mt_battle_wins_89100c2c"), 250),
    Preset("news-pokeldn", _ref("core.pokeldn.frlg.gift.builder.one_berry_in_cerulean_city_c051d44e"), _ref("core.pokeldn.frlg.gift.builder.wonder_news_d58adf54"),
           _ref("core.pokeldn.frlg.gift.builder.a_short_news_the_man_in_cerulean_city_hands_over_a_berr_e8f2f1f5"), ("--news", "pokeldn")),
    Preset("news-berry", _ref("core.pokeldn.frlg.gift.builder.ten_line_news_33606df2"), _ref("core.pokeldn.frlg.gift.builder.wonder_news_d58adf54"), _ref("core.pokeldn.frlg.gift.builder.a_long_news_that_scrolls_with_a_berry_92774b1d"),
           ("--news", "berry")),
    Boosts(),
    Preset("mom-resident", MOM, BOOSTS, _ref("core.pokeldn.frlg.gift.builder.send_after_saving_your_boosts_talk_to_mom_in_pallet_tow_832b55a6"),
           ("--gift", "resident-save"),
           when=_ref("core.pokeldn.frlg.gift.builder.first_send_boosts_saved_in_your_game_using_save_boosts__155bc7b9")),
    _code("trainer-id", _ref("core.pokeldn.frlg.gift.builder.trainer_id_tid_and_secret_id_sid_dcd99112"),
          _ref("core.pokeldn.frlg.gift.builder.shows_both_ids_in_the_session_log_your_trainer_card_s_i_4a640255"),
          "--buffer-script", "trainer-id-probe"),
    _code("dump-sav2", _ref("core.pokeldn.frlg.gift.builder.trainer_name_ids_and_play_time_7b33af76"), _ref("core.pokeldn.frlg.gift.builder.shows_your_name_trainer_id_tid_secret_id_sid_and_play_t_7be07730"),
          "--buffer-script", "save-dump", "--dump-block", "sav2"),
    _code("dump-sav1", _ref("core.pokeldn.frlg.gift.builder.your_party_s_ivs_and_natures_fe0be449"), _ref("core.pokeldn.frlg.gift.builder.shows_each_pokemon_in_your_last_saved_party_nature_six__fa889a6d"),
          "--buffer-script", "save-dump", "--dump-block", "sav1", "--dump-offset", "0x34", "--dump-size", "608"),
)
PRESET = {p.key: p for p in PRESETS}
# Presets an older settings file may name -> (preset, settings).
ALIASES = {**{b.key: ("boosts", {"on": [b.key]}) for b in BOOST_LIST},
           "save-shiny": ("boosts", {"on": ["hook-shiny"], "keep": True}),
           "save-noclip": ("boosts", {"on": ["hook-noclip"], "keep": True})}


def blank():
    return {"kind": "card", "giver": "deliveryman",
            "card": {"title": "MYSTERY GIFT", "subtitle": "A gift from pokeldn", "body": ["", "", "", ""],
                     "icon": 25, "flag_id": 1003, "repeatable": False, "shareable": False},
            "steps": [{"type": "pokemon", "species": 25, "level": 5, "item": 0, "moves": [0, 0, 0, 0]},
                      {"type": "message", "text": "{PLAYER} received a gift!"}],
            "news": {"title": "POKELDN NEWS", "lines": ["Hello from pokeldn!"], "id": 1},
            "code": {"source": custom_code.TEMPLATE, "binary": "", "expect": "", "dump_size": "", "build": ""}}


# Form state <-> composer actions

def _action(step):
    kind = step.get("type")
    number = lambda key, default=0: int(step.get(key) or default)
    moves = tuple(int(m) for m in step.get("moves", ()) if int(m or 0))
    if kind == "pokemon":
        return gc.GivePokemon(number("species"), number("level", 5), held_item=number("item"),
                              moves=moves, fateful_encounter=True, failure_message=FULL)
    if kind == "egg":
        return gc.GiveEgg(number("species"), moves=moves, failure_message=FULL)
    if kind == "item":
        return gc.GiveItem(number("item"), number("quantity", 1), failure_message=FULL)
    if kind == "battle":
        return gc.BattlePokemon(number("species"), number("level", 5), held_item=number("item"))
    if kind == "message":
        return gc.Message(str(step.get("text") or "").replace("\r", ""))
    raise ValueError(_message('core.pokeldn.frlg.gift.builder.unknown_step_value0_r_1fcd0fc2', value0=kind))


def _step(action):
    if isinstance(action, gc.GivePokemon):
        return {"type": "pokemon", "species": action.species, "level": action.level,
                "item": action.held_item, "moves": list(action.moves) + [0] * (4 - len(action.moves))}
    if isinstance(action, gc.GiveEgg):
        return {"type": "egg", "species": action.species}
    if isinstance(action, gc.GiveItem):
        return {"type": "item", "item": action.item, "quantity": action.quantity}
    if isinstance(action, gc.BattlePokemon):
        return {"type": "battle", "species": action.species, "level": action.level, "item": action.held_item}
    if isinstance(action, gc.Message):
        return {"type": "message", "text": action.text}
    return None


def state_of(definition):
    """A registered card as a form state, or None when it uses more than the form offers."""
    if (definition is None or not isinstance(definition.event, gc.GiftSpec) or definition.mevent
            or definition.trainer or definition.for_build is not None):
        return None
    plan = definition.delivery
    if plan.pre_stages or plan.post_stages:
        return None
    steps = []
    for stage in plan.delivery:
        if stage.condition is not None:
            return None
        for action in stage.actions:
            if (step := _step(action)) is None:
                return None
            steps.append(step)
    card = definition.card
    state = blank()
    state["card"] = {"title": card.title, "subtitle": card.subtitle,
                     "body": list(card.body) + [""] * (4 - len(card.body)), "icon": card.icon_species,
                     "flag_id": card.default_flag_id,
                     "repeatable": definition.event.repeatable,
                     "shareable": definition.event.shareable != gc.SHARE_NEVER}
    state["steps"] = steps
    return state


def definition(state):
    card, steps = state.get("card", {}), state.get("steps", [])
    actions = tuple(_action(step) for step in steps)
    if not actions:
        raise ValueError(_ref("core.pokeldn.frlg.gift.builder.add_at_least_one_step_to_the_gift_bc50edfc"))
    giver = next((g for g in GIVERS if g[0] == state.get("giver")), GIVERS[0])
    mevent = None
    if giver[3] is not None:
        mevent = events.build_mevent_npc_script(map_group=giver[3], map_num=giver[4], object_id=giver[5],
                                                actions=actions)
        actions = (gc.Message(f"{giver[1]} has your gift."),)
    return gc.WonderGift(
        slug="built", intro_message="A MYSTERY GIFT arrived!",
        card=gc.WonderCardSpec(icon_species=int(card.get("icon") or 25), title=card.get("title", ""),
                               subtitle=card.get("subtitle", ""),
                               body=tuple(line for line in card.get("body", ()) if line),
                               footer1="pokeldn",
                               default_flag_id=int(card.get("flag_id") or 1003)),
        event=gc.GiftSpec(repeatable=bool(card.get("repeatable")),
                          shareable=gc.SHARE_ALWAYS if card.get("shareable") else gc.SHARE_NEVER),
        delivery=gc.DeliveryPlan(delivery=tuple(gc.DeliveryStage(action) for action in actions)),
        mevent=mevent)


def code_bytes(code_state):
    """The machine code a code state names: the opened .bin, else the assembled source."""
    if path := code_state.get("binary"):
        with open(path, "rb") as stream:
            return stream.read(0x401)
    return _assembled(code_state.get("source", ""))


_ASSEMBLED, _CHECKED = {}, {}


def _assembled(source):
    key = hashlib.sha256(source.encode()).hexdigest()
    if key not in _ASSEMBLED:
        _ASSEMBLED[key] = custom_code.assemble(source)
    return _ASSEMBLED[key]


def checked(code):
    """custom_code.check, once per distinct payload."""
    if code not in _CHECKED:
        _CHECKED[code] = custom_code.check(code)
    return _CHECKED[code]


def compile(state):
    """Form state -> gifts.Gift with a variant for every cartridge. Raises ValueError with what to fix."""
    kind = state.get("kind", "card")
    if kind == "news":
        news = state.get("news", {})
        lines = [line for line in news.get("lines", ()) if line]
        raw = wonder_news.build_wonder_news(news_id=int(news.get("id") or 1), title=news.get("title", ""),
                                            body=lines)
        per_build = {code: MysteryGiftDistribution(card=None, ram_script=None, news=wonder_news.for_build(raw, code)) for code in CARTRIDGES}
        return gift_file.from_distributions(news.get("title") or _ref("core.pokeldn.frlg.gift.builder.wonder_news_d58adf54"), per_build)
    if kind == "code":
        code_state = state.get("code", {})
        expect, size = code_state.get("expect", ""), code_state.get("dump_size", "")
        code = code_bytes(code_state)
        checked(code)
        gift = gift_file.from_code(code, build="BPRF", name=_ref("core.pokeldn.frlg.gift.builder.console_code_33f04c21"),
                                   expect=int(expect, 0) if str(expect).strip() else None,
                                   dump_size=int(size, 0) if str(size).strip() else None)
        targets = [code_state["build"]] if code_state.get("build") in CARTRIDGES else CARTRIDGES
        return gifts.Gift("frlg", gift.name, {target: gift.variants["BPRF"] for target in targets})
    try:
        built = definition(state)
        per_build = {code: gc.compile_definition(built, build=builds.BUILDS[code]) for code in CARTRIDGES}
    except gc.GiftValidationError as exc:
        raise ValueError(_message('core.pokeldn.frlg.gift.builder.value0_value1_6a776812', value0=_where(exc.path), value1=exc.message)) from None
    return gift_file.from_distributions(built.card.title or _ref("core.pokeldn.frlg.gift.builder.mystery_gift_68b50f5f"), per_build)


def _where(path):
    """A composer path as the form names it: "Step 2", "Card title"."""
    if match := re.search(r"actions\[(\d+)\]", path):
        return f"Step {int(match[1]) + 1}"
    if match := re.search(r"card\.(\w+)(?:\[(\d+)\])?", path):
        return f"Card {match[1]}" + (f" line {int(match[2]) + 1}" if match[2] else "")
    return "The gift"


def _step_line(step, name):
    kind = step.get("type")
    if kind == "pokemon":
        return _message("core.gift.pokemon.level_description", species=name("species", step.get("species")), level=step.get("level") or 5)
    if kind == "egg":
        return _message("core.gift.egg.description", species=name("species", step.get("species")))
    if kind == "item":
        quantity = int(step.get("quantity") or 1)
        return _message("core.gift.item.description", item=name("item", step.get("item")), quantity=quantity)
    if kind == "battle":
        return _message("core.gift.battle.description", species=name("species", step.get("species")), level=step.get("level") or 5)
    return _message('core.pokeldn.frlg.gift.builder.says_value0_f4eca325', value0=str(step.get('text', '')).splitlines()[0] if step.get('text') else '')


def describe(state, name=lambda kind, n: f"{kind} #{n}"):
    """(when it runs, [what happens]) for the summary before sending; `name(kind, id)` names an item."""
    kind = state.get("kind", "card")
    if kind == "news":
        return _ref("core.pokeldn.frlg.gift.builder.shown_on_the_wonder_news_screen_as_soon_as_it_is_receiv_313429b4"), [
            _message("core.gift.news.title", title=state.get("news", {}).get("title", ""))]
    if kind == "code":
        code = state.get("code", {})
        target = CARTRIDGES.get(code.get("build"), _ref("core.gift.code.any_cartridge"))
        return _ref("core.pokeldn.frlg.gift.builder.runs_on_the_console_while_it_receives_inside_the_myster_bb1288df"), [
            _ref("core.pokeldn.frlg.gift.builder.your_arm_code_checked_offline_before_it_is_sent_819c4c2d"), _message("core.gift.code.target", target=target)]
    giver = next((g for g in GIVERS if g[0] == state.get("giver")), GIVERS[0])
    when = _message("core.gift.giver.deliveryman" if giver[0] == "deliveryman" else "core.gift.giver.npc",
                    giver=giver[1], location=giver[2])
    lines = [_step_line(step, name) for step in state.get("steps", [])]
    card = state.get("card", {})
    if giver[0] != "deliveryman":
        # build_bound_script ends in `end` with no receipt flag [gift_composer.py].
        lines.append(_message("core.gift.giver.repeat", giver=giver[1]))
    else:
        lines.append(_ref("core.pokeldn.frlg.gift.builder.can_be_received_again_485c28bc") if card.get("repeatable") else _ref("core.pokeldn.frlg.gift.builder.received_once_per_save_6afa6cb8"))
    if card.get("shareable"):
        lines.append(_ref("core.pokeldn.frlg.gift.builder.the_player_can_pass_the_card_on_3be4ae4c"))
    return when, lines

"""The app's FireRed/LeafGreen gift builder: a preset, or a gift built from a plain form state (JSON),
compiled to a .pokegift for every cartridge [docs/gifts.md]."""

import hashlib
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

CARTRIDGES = {"BPRF": "FireRed (French)", "BPGF": "LeafGreen (French)",
              "BPRE": "FireRed (English)", "BPGE": "LeafGreen (English)"}
KINDS = (("card", "Wonder Card", "gift"), ("news", "Wonder News", "book-open"), ("code", "Console code", "cpu"))
# (key, who, where, map group, map number, object id); a bound script replaces that person's own.
GIVERS = (
    ("deliveryman", "The delivery man", "any Pokemon Center, after the card is saved", None, None, None),
    ("mom", "Mom", "the player's house", events.MAP_GROUP_PLAYERS_HOUSE, events.MAP_NUM_PLAYERS_HOUSE,
     events.PLAYERS_HOUSE_OBJECT_MOM),
    ("pallet-man", "The man in Pallet Town", "south of Pallet Town", events.MAP_GROUP_PALLET_TOWN,
     events.MAP_NUM_PALLET_TOWN, events.PALLET_TOWN_OBJECT_FAT_MAN),
)
STEPS = (("pokemon", "Pokemon"), ("item", "Item"), ("egg", "Egg"), ("battle", "Wild battle"),
         ("message", "Message"))
FULL = "Oh, there is no room!\nPlease make room and come back."


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

    @property
    def state(self):
        """The preset as an editable form, or None when the form cannot express it."""
        if self.args[0] != "--gift" or "--event-pokemon" in self.args:
            return None
        return state_of(GIFT_REGISTRY.entry(self.args[1]).definition)


def _card(slug, label, summary):
    return Preset(slug, label, "Wonder Cards", summary, ("--gift", slug))


EVENTS = "Event Pokemon"
ANNIVERSARY = "10th Anniversary Pokemon"


def _event(name, summary, group=EVENTS):
    """A fresh copy PKHeX makes at launch [docs/frlg_gift.md, Event Pokemon]."""
    key = "event-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return Preset(key, name, group, summary, ("--gift", events.GIFT_EVENT_POKEMON, "--event-pokemon", name))


def _code(key, label, summary, *args):
    return Preset(key, label, "Read the save", summary, args)


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
BOOSTS = "Game boosts"
R, B, SELECT = "0x100", "0x2", "0x4"
# L opens the Help System; only R's toggle has a flag the hooks hold off [docs/frlg_rom.md, turbo].
BUTTONS = ((R, "Hold R"), (B, "Hold B (also runs)"), (SELECT, "Hold Select (also uses the registered item)"))
BUTTON_NAME = {R: "R", B: "B", SELECT: "Select"}
KEEP = Option("keep", "Keep them after a reset", False, help="Also writes them into the save. After a reset "
              "or power-off, talk to Mom to turn them back on; send Mom turns boosts back on once for that.")
SPEEDS = (("1", "x1"), ("2", "x2"), ("3", "x3"), ("4", "x4"))
WHERE = (("both", "Overworld and battles"), ("field", "Overworld only"), ("battle", "Battles only"))
SLOWER = (("1", "x2 slower"), ("3", "x4 slower"), ("7", "x8 slower"))
# A pass budget in scanlines: measured smooth at field=3 battle=3, stuttering without it [frlg_rom.md].
BUDGET = 228
RESIDENT_AREA = 0x400                       # 0x0203FC00..0x02040000


def _turbo(o):
    speed, text = int(o["speed"]), o["text"]
    if speed == 1 and not text:
        raise ValueError("Speed up the game: pick a speed above x1 or faster text.")
    params = {"extra": 4 if text else 0,
              "field": speed - 1 if o["where"] in ("both", "field") else 0,
              "battle": speed - 1 if o["where"] in ("both", "battle") else 0,
              "hold": 0 if o["button"] == "always" else int(o["button"], 0)}
    if speed >= 3:
        params["budget"] = BUDGET
    lines = []
    if speed > 1:
        how = "all the time" if o["button"] == "always" else f"while {BUTTON_NAME[o['button']]} is held"
        lines.append(f"{dict(WHERE)[o['where']]} run up to x{speed} {how}")
    if text:
        lines.append("Text prints faster")
    return params, lines


def _shiny(o):
    return {"slow": int(o["button"], 0), "slow_frames": int(o["slower"])}, [
        "Counts down to the next shiny wild Pokemon in the grass, top right of the screen",
        f"The game runs {dict(SLOWER)[o['slower']]} while {BUTTON_NAME[o['button']]} is held, to hit the frame"]


def _noclip(o):
    return {"hold": int(o["button"], 0)}, [
        f"Walk through walls, trees and water while {BUTTON_NAME[o['button']]} is held; people still block the way"]


def _plain(*lines):
    return lambda o: ({}, list(lines))


BOOST_LIST = (
    Boost("hook-turbo", "Speed up the game", "x2, x3 or x4 in the overworld and in battle, and faster text.",
          "turbo-lite", _turbo, (Option("speed", "Game speed", "2", SPEEDS), Option("where", "Where", "both", WHERE),
                            Option("button", "When", R, (("always", "Always on"),) + BUTTONS),
                            Option("text", "Faster text", True, help="Dialogue prints several letters a frame."))),
    Boost("hook-noclip", "Walk through walls", "Hold a button to walk through walls, trees and water.",
          "noclip", _noclip, (Option("button", "When", R, BUTTONS),)),
    Boost("hook-noencounter", "No wild encounters", "No grass, water or roaming encounters.", "noencounter",
          _plain("No grass, water or roaming encounters; fishing and Sweet Scent still work")),
    Boost("hook-shiny", "Shiny countdown", "Counts down to the next shiny in the grass.", "shiny", _shiny,
          (Option("button", "Slow the game down", R, BUTTONS), Option("slower", "By", "3", SLOWER))),
    Boost("hook-ivs", "Lead's IVs on screen", "The lead Pokemon's IVs and nature, top right.", "ivs",
          _plain("The lead Pokemon's six IVs and its nature, top right of the overworld")),
    Boost("hook-follower", "Pokemon follower", "Your lead Pokemon walks behind you.", "follower",
          _plain("The lead Pokemon walks behind you, hops ledges with you, and smiles and cries when you face "
                 "it and press A")),
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
    label: str = "Game boosts"
    group: str = BOOSTS
    summary: str = "Tick one or several: they run together until a reset, or stay in the save."
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
            raise ValueError("Tick at least one boost.")
        if len(on) > 1 and BOOST["hook-follower"] in on:
            raise ValueError("The Pokemon follower runs alone: untick the other boosts.")
        drawing = [b.label for b in on if b.key in DRAWING]
        if len(drawing) > 1:
            raise ValueError(f"{' and '.join(drawing)} both draw in the top-right corner: untick one.")
        if self.size(s) > RESIDENT_AREA:
            raise ValueError(f"These boosts take {self.size(s)} bytes together; the console has room for "
                             f"{RESIDENT_AREA}. Untick one.")
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
        lines.append(("Kept in the save: too large to send any other way. " if too_large else
                      "Kept in the save. " if keep else "Lasts until a soft reset or power-off")
                     + ("After a reset, talk to Mom to turn it back on (send Mom turns boosts back on once)"
                        if keep else ""))
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
    _card("beast-cutscene", "Legendary beast", "Two berries, a Master Ball and a battle with the beast "
          "that follows the starter."),
    _card("celebi", "Celebi", "A level 50 Celebi from the delivery man."),
    _card("master-ball", "Master Ball", "One Master Ball."),
    _card("altering-cave", "Altering Cave", "Changes which Pokemon live in Altering Cave."),
    _card("wish-egg", "Wish Egg", "One of six eggs that knows Wish, picked by the console."),
    _card("pokepark-egg", "PokePark egg", "One of fifteen eggs with special moves, picked by the console."),
    _card("pc-japan-egg", "Pokemon Center Japan egg", "One of four eggs with special moves."),
    _card("starter-egg", "Starter egg", "An egg of one of the nine first partners."),
    _card("rare-berries", "Rare berries", "An Enigma, a Lansat and a Starf Berry."),
    _card("national-dex", "National Pokedex", "Upgrades the Pokedex to the National Pokedex."),
    _card("porygon-tm-gift", "Porygon TM gift", "A Porygon and a TM."),
    _card("solrock-stamp", "Sun and Moon Rally: Solrock", "A rally stamp."),
    _card("lunatone-stamp", "Sun and Moon Rally: Lunatone", "A rally stamp."),
    _card("visiting-trainer", "Visiting trainer", "A trainer who waits in the Pokemon Center."),
    _card("battle-count-card", "Battle count card", "A card that counts link battles."),
    _card("worlds-xp", "Worlds XP", "The Worlds card."),
    _event("WISHMKR Jirachi", "The Colosseum Bonus Disc Jirachi, level 5."),
    _event("CHANNEL Jirachi", "The Pokemon Channel Jirachi, level 5."),
    _event("Aura Mew", "The Aura Mew, level 10."),
    _event("MYSTRY Mew", "The MYSTRY Mew, level 10."),
    _event("DOEL Deoxys", "The DOEL Deoxys, level 70."),
    _event("SPACE C Deoxys", "The SPACE C Deoxys, level 70."),
    _event("ROCKS Metang", "The ROCKS Metang, level 30, with the National Ribbon."),
    *(_event(f"10 ANIV {name}", "Level 70, from the 10th anniversary.", ANNIVERSARY)
      for name in ("Bulbasaur", "Charizard", "Blastoise", "Pikachu", "Alakazam", "Articuno", "Zapdos",
                   "Moltres", "Dragonite", "Typhlosion", "Espeon", "Umbreon", "Raikou", "Entei", "Suicune",
                   "Tyranitar", "Celebi", "Blaziken", "Absol", "Latias", "Latios")),
    Preset("news-pokeldn", "One berry in Cerulean City", "Wonder News",
           "A short news; the man in Cerulean City hands over a berry.", ("--news", "pokeldn")),
    Preset("news-berry", "Ten-line news", "Wonder News", "A long news that scrolls, with a berry.",
           ("--news", "berry")),
    Boosts(),
    Preset("mom-resident", "Mom turns boosts back on", BOOSTS, "Send once after boosts kept in the save.",
           ("--gift", "resident-save")),
    _code("trainer-id", "Read the trainer id", "Reads only. The answer is the save's trainer id.",
          "--buffer-script", "trainer-id-probe"),
    _code("dump-sav2", "Read the trainer block", "Reads only. The first bytes of SaveBlock2 land in "
          "Received; the size is on the Advanced tab.", "--buffer-script", "save-dump", "--dump-block", "sav2"),
    _code("dump-sav1", "Read party, bag and flags", "Reads only. The first bytes of SaveBlock1 land in "
          "Received.", "--buffer-script", "save-dump", "--dump-block", "sav1"),
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
    raise ValueError(f"Unknown step {kind!r}.")


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
        raise ValueError("Add at least one step to the gift.")
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
        per_build = {code: MysteryGiftDistribution(card=None, ram_script=None, news=raw) for code in CARTRIDGES}
        return gift_file.from_distributions(news.get("title") or "Wonder News", per_build)
    if kind == "code":
        code_state = state.get("code", {})
        expect, size = code_state.get("expect", ""), code_state.get("dump_size", "")
        code = code_bytes(code_state)
        checked(code)
        gift = gift_file.from_code(code, build="BPRF", name="Console code",
                                   expect=int(expect, 0) if str(expect).strip() else None,
                                   dump_size=int(size, 0) if str(size).strip() else None)
        targets = [code_state["build"]] if code_state.get("build") in CARTRIDGES else CARTRIDGES
        return gifts.Gift("frlg", gift.name, {target: gift.variants["BPRF"] for target in targets})
    try:
        built = definition(state)
        per_build = {code: gc.compile_definition(built, build=builds.BUILDS[code]) for code in CARTRIDGES}
    except gc.GiftValidationError as exc:
        raise ValueError(f"{_where(exc.path)}: {exc.message}") from None
    return gift_file.from_distributions(built.card.title or "Mystery Gift", per_build)


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
        return f"Gives {species_name(step.get('species'))}, level {step.get('level') or 5}"
    if kind == "egg":
        return f"Gives a {species_name(step.get('species'))} egg"
    if kind == "item":
        quantity = int(step.get("quantity") or 1)
        return f"Gives {name('item', step.get('item'))}" + (f" x{quantity}" if quantity > 1 else "")
    if kind == "battle":
        return f"Starts a battle with a wild {species_name(step.get('species'))}, level {step.get('level') or 5}"
    return f"Says “{str(step.get('text', '')).splitlines()[0] if step.get('text') else ''}”"


def describe(state, name=lambda kind, n: f"{kind} #{n}"):
    """(when it runs, [what happens]) for the summary before sending; `name(kind, id)` names an item."""
    kind = state.get("kind", "card")
    if kind == "news":
        return "Shown on the Wonder News screen as soon as it is received.", [
            f"News “{state.get('news', {}).get('title', '')}”"]
    if kind == "code":
        code = state.get("code", {})
        target = CARTRIDGES.get(code.get("build"), "any cartridge; call no ROM address")
        return "Runs on the console while it receives, inside the Mystery Gift menu.", [
            "Your ARM code, checked offline before it is sent", f"Built for {target}"]
    giver = next((g for g in GIVERS if g[0] == state.get("giver")), GIVERS[0])
    when = (f"Runs when the player talks to {giver[1].lower()}, {giver[2]}." if giver[0] == "deliveryman"
            else f"Runs when the player talks to {giver[1].lower()} in {giver[2]}. "
                 "The card is not shown while that person holds the gift.")
    lines = [_step_line(step, name) for step in state.get("steps", [])]
    card = state.get("card", {})
    if giver[0] != "deliveryman":
        # build_bound_script ends in `end` with no receipt flag [gift_composer.py].
        lines.append(f"Every time the player talks to {giver[1].lower()}, until another gift is received")
    else:
        lines.append("Can be received again" if card.get("repeatable") else "Received once per save")
    if card.get("shareable"):
        lines.append("The player can pass the card on")
    return when, lines

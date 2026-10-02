"""The app's FireRed/LeafGreen gift builder: a preset, or a gift built from a plain form state (JSON),
compiled to a .pokegift for every cartridge [docs/gifts.md]."""

import hashlib
import re
from dataclasses import dataclass

from pokeldn import gifts
from pokeldn.frlg.gift import file as gift_file, wonder_news
from pokeldn.frlg.gift import gift_composer as gc, wonder_card_events as events
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
from pokeldn.frlg.rom import builds, custom_code
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
        if self.args[0] != "--gift":
            return None
        return state_of(GIFT_REGISTRY.entry(self.args[1]).definition)


def _card(slug, label, summary):
    return Preset(slug, label, "Wonder Cards", summary, ("--gift", slug))


def _code(key, label, summary, *args):
    return Preset(key, label, "Console code", summary, args)


HOOK = ("--buffer-script", "install-resident", "--write-unsafe", "--resident")
PRESETS = (
    _card("beast-cutscene", "Legendary beast", "Two berries, a Master Ball and a battle with the beast "
          "that follows the starter."),
    _card("celebi", "Celebi", "A level 50 Celebi from the delivery man."),
    _card("master-ball", "Master Ball", "One Master Ball."),
    _card("altering-cave", "Altering Cave", "Changes which Pokemon live in Altering Cave."),
    _card("porygon-tm-gift", "Porygon TM gift", "A Porygon and a TM."),
    _card("solrock-stamp", "Sun and Moon Rally: Solrock", "A rally stamp."),
    _card("lunatone-stamp", "Sun and Moon Rally: Lunatone", "A rally stamp."),
    _card("visiting-trainer", "Visiting trainer", "A trainer who waits in the Pokemon Center."),
    _card("battle-count-card", "Battle count card", "A card that counts link battles."),
    _card("worlds-xp", "Worlds XP", "The Worlds card."),
    Preset("news-pkcamp", "One berry in Cerulean City", "Wonder News",
           "A short news; the man in Cerulean City hands over a berry.", ("--news", "pkcamp")),
    Preset("news-berry", "Ten-line news", "Wonder News", "A long news that scrolls, with a berry.",
           ("--news", "berry")),
    _code("trainer-id", "Read the trainer id", "Reads only. The answer is the save's trainer id.",
          "--buffer-script", "trainer-id-probe"),
    _code("dump-sav2", "Read the trainer block", "Reads only. The first bytes of SaveBlock2 land in "
          "Received; the size is on the Advanced tab.", "--buffer-script", "save-dump", "--dump-block", "sav2"),
    _code("dump-sav1", "Read party, bag and flags", "Reads only. The first bytes of SaveBlock1 land in "
          "Received.", "--buffer-script", "save-dump", "--dump-block", "sav1"),
    _code("hook-turbo", "Turbo text", "Writes RAM until a soft reset: dialogue runs faster.", *HOOK, "turbo"),
    _code("hook-shiny", "Shiny countdown", "Writes RAM until a soft reset: a countdown to the next "
          "shiny wild encounter.", *HOOK, "shiny"),
    _code("hook-ivs", "IVs on screen", "Writes RAM until a soft reset: the lead's IVs and nature.",
          *HOOK, "ivs"),
    _code("hook-noencounter", "No wild encounters", "Writes RAM until a soft reset: no grass, water or "
          "roaming encounters.", *HOOK, "noencounter"),
)
PRESET = {p.key: p for p in PRESETS}


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
    lines.append("Can be received again" if card.get("repeatable") else "Received once per save")
    if card.get("shareable"):
        lines.append("The player can pass the card on")
    return when, lines

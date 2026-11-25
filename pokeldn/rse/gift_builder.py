"""The app's Emerald Mystery Gifts (pokeldn.app.gift_builder): presets and opened files. Compiled
presets build an Emerald .pokegift; event and GameCube distributions go through --gift event-pokemon
so PKHeX rolls a fresh legal copy at launch."""

import re
from dataclasses import dataclass

from pokeldn.frlg.gift import gift_composer as gc, wonder_card_events as events
from pokeldn.rse import constants as em, gift_file, gifts

KINDS = (("card", "Wonder Card", "gift"),)
BUILD = False                       # no "Build your own" form for Emerald yet
OFFICIAL_GIFTS = "Official Emerald gifts"
GAMECUBE = "GameCube & Bonus Disc"
EVENTS = "Event Pokemon"
ANNIVERSARY = "10th Anniversary Pokemon"
MORE = "More gifts"
WHEN = "After the card is saved, talk to the delivery man on 2F of any Pokemon Center."
EVENT_WHEN = "Delivered straight to your party when the card is saved. Make sure you have a free slot."
NATIONAL = {410: 386, 250: 250, 151: 151, 235: 235}     # internal icon species -> National Dex


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    group: str
    summary: str
    state: dict | None = None
    args: tuple = ()
    species_id: int = 0
    shiny: bool = False
    when: str = WHEN


def _composed(slug, title, body, actions, icon, *, subtitle="MYSTERY GIFT"):
    return gc.WonderGift(slug=slug, card=gc.WonderCardSpec(icon_species=icon, title=title, body=body,
                                                           subtitle=subtitle),
                         intro_message=gifts.THANKS,
                         event=gc.GiftSpec(), delivery=gc.DeliveryPlan(delivery=(gc.DeliveryStage(*actions),)))


def _event(name, species_id, summary, group=EVENTS, *, shiny=False):
    """A fresh copy PKHeX makes at launch [docs/rse_gift.md, Event and GameCube Pokemon]."""
    key = "event-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return Preset(key, name, group, summary, None,
                  args=("--gift", events.GIFT_EVENT_POKEMON, "--event-pokemon", name),
                  species_id=species_id, shiny=shiny, when=EVENT_WHEN)


# Pokemon Box: Ruby & Sapphire bonus eggs [PKHeX EncountersWC3]: internal species and official moves.
COMPOSED = {
    "master-ball": (_composed("master-ball", "MASTER BALL", ("A MASTER BALL for you.",),
                              (gc.GiveItem(1),), 25), 1004),
    "rare-candy": (_composed("rare-candy", "RARE CANDY", ("Five RARE CANDIES for you.",),
                             (gc.GiveItem(68, 5),), 25), 1005),
    "surf-pichu": (_composed("surf-pichu", "POKéMON EGG", ("An EGG of a PICHU that knows SURF.",),
                             (gc.GiveEgg(172, moves=(84, 204, 57), fateful_encounter=True),), 172,
                             subtitle="POKéMON BOX BONUS"), 1006),
    "box-swablu": (_composed("box-swablu", "POKéMON EGG", ("An EGG of a SWABLU with FALSE SWIPE.",),
                             (gc.GiveEgg(358, moves=(64, 45, 206), fateful_encounter=True),), 358,
                             subtitle="POKéMON BOX BONUS"), 1008),
    "box-zigzagoon": (_composed("box-zigzagoon", "POKéMON EGG", ("An EGG of a ZIGZAGOON that knows", "EXTREMESPEED."),
                                (gc.GiveEgg(288, moves=(33, 45, 39, 245), fateful_encounter=True),), 288,
                                subtitle="POKéMON BOX BONUS"), 1009),
    "box-skitty": (_composed("box-skitty", "POKéMON EGG", ("An EGG of a SKITTY with PAY DAY.",),
                             (gc.GiveEgg(315, moves=(45, 33, 39, 6), fateful_encounter=True),), 315,
                             subtitle="POKéMON BOX BONUS"), 1010),
    "wish-egg": (events.WISH_EGG_GIFT, None),
    "pokepark-egg": (events.POKEPARK_EGG_GIFT, None),
    "pc-japan-egg": (events.PC_JAPAN_EGG_GIFT, None),
    "battle-count-card": (gifts.BATTLE_COUNT_GIFT, None),
    "national-dex": (gifts.NATIONAL_DEX_GIFT, None),
    "rare-berries": (events.RARE_BERRIES_GIFT, 1012),
    "starter-egg": (events.STARTER_EGG_GIFT, 1013),
}
EON_FLAG_ID = 1007


def _eon_ticket():
    """The ticket handout the game itself makes for the Eon Ticket [pokeemerald
    data/scripts/cable_club.inc:33]: done once the ship flag is set or the ticket held."""
    from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
    from pokeldn.frlg.gift.wonder_card import build_wonder_card
    script = gifts.ticket_script(em.ITEM_EON_TICKET, em.EMERALD_RULES.flag_for_flag_id(EON_FLAG_ID),
                                 (em.FLAG_ENABLE_SHIP_SOUTHERN_ISLAND,), em.FLAG_ENABLE_SHIP_SOUTHERN_ISLAND,
                                 f"{gifts.THANKS}\fLet me confirm--you are {{PLAYER}}?\f"
                                 "We received this EON TICKET\naddressed to you.")
    card = build_wonder_card(flag_id=EON_FLAG_ID, icon_species=407, title="EON TICKET",
                             subtitle="MYSTERY GIFT", body=("A ticket for the ferry", "at LILYCOVE CITY port."),
                             footer1="Talk to the delivery man on", footer2="2F of a POKéMON CENTER.")
    return MysteryGiftDistribution(card, script, game="emerald")


PRESETS = (
    *(Preset(o.key, o.label, OFFICIAL_GIFTS, o.summary, {"kind": "official", "gift": o.key},
             species_id=NATIONAL.get(o.icon_species, 0)) for o in gifts.OFFICIAL[:3]),
    Preset("eon-ticket", "Eon Ticket", OFFICIAL_GIFTS,
           "The ferry to Southern Island, where Latias or Latios waits.",
           {"kind": "eon-ticket"}, species_id=380),
    *(Preset(o.key, o.label, OFFICIAL_GIFTS, o.summary, {"kind": "official", "gift": o.key},
             species_id=NATIONAL.get(o.icon_species, 0)) for o in gifts.OFFICIAL[3:]),
    Preset("wish-egg", "Wish Egg", OFFICIAL_GIFTS,
           "One of six eggs that knows Wish, picked by the console.", {"kind": "composed", "gift": "wish-egg"}),
    Preset("pokepark-egg", "PokePark egg", OFFICIAL_GIFTS,
           "One of fifteen eggs with special moves, picked by the console.",
           {"kind": "composed", "gift": "pokepark-egg"}),
    Preset("pc-japan-egg", "Pokemon Center Japan egg", OFFICIAL_GIFTS,
           "One of four eggs with special moves.", {"kind": "composed", "gift": "pc-japan-egg"}),
    Preset("battle-count-card", "Battle count card", OFFICIAL_GIFTS,
           "A card that counts link battles.", {"kind": "composed", "gift": "battle-count-card"}),
    _event("WISHMKR Jirachi", 385, "The Colosseum Bonus Disc Jirachi, level 5.", GAMECUBE),
    _event("CHANNEL Jirachi", 385, "The Pokemon Channel Jirachi, level 5.", GAMECUBE),
    _event("Colosseum Pikachu", 25,
           "The Japanese Colosseum bonus disc Pikachu, level 10. Its Japanese trainer name shows as dots.",
           GAMECUBE),
    _event("AGETO Celebi", 251,
           "The Japanese Colosseum bonus disc Celebi, level 10. Its Japanese trainer name shows as dots.",
           GAMECUBE),
    _event("MATTLE Ho-Oh", 250, "The Ho-Oh Colosseum gave for 100 Mt. Battle wins, level 70.", GAMECUBE),
    _event("DUKING Plusle", 311, "Duking's Plusle from Pokemon Colosseum, level 13.", GAMECUBE),
    _event("XD Eevee", 133, "The starter Eevee from Pokemon XD: Gale of Darkness, level 10.", GAMECUBE),
    _event("XD Chikorita", 152, "Mt. Battle prize from Pokemon XD, level 5, knowing Frenzy Plant.", GAMECUBE),
    _event("XD Cyndaquil", 155, "Mt. Battle prize from Pokemon XD, level 5, knowing Blast Burn.", GAMECUBE),
    _event("XD Totodile", 158, "Mt. Battle prize from Pokemon XD, level 5, knowing Hydro Cannon.", GAMECUBE),
    _event("XD Lugia", 249, "Purified Shadow Lugia (XD001) from Pokemon XD, level 50, knowing Psycho Boost.", GAMECUBE),
    Preset("box-swablu", "Pokemon Box Swablu egg", GAMECUBE,
           "A Swablu egg from Pokemon Box that hatches knowing False Swipe.",
           {"kind": "composed", "gift": "box-swablu"}, species_id=333),
    Preset("box-zigzagoon", "Pokemon Box Zigzagoon egg", GAMECUBE,
           "A Zigzagoon egg from Pokemon Box that hatches knowing ExtremeSpeed.",
           {"kind": "composed", "gift": "box-zigzagoon"}, species_id=263),
    Preset("box-skitty", "Pokemon Box Skitty egg", GAMECUBE,
           "A Skitty egg from Pokemon Box that hatches knowing Pay Day.",
           {"kind": "composed", "gift": "box-skitty"}, species_id=300),
    Preset("surf-pichu", "Surfing Pichu egg", GAMECUBE,
           "A Pichu egg from Pokemon Box that hatches knowing Surf.",
           {"kind": "composed", "gift": "surf-pichu"}, species_id=172),
    _event("RUBY Zigzagoon", 263, "The Berry Glitch Fix shiny Zigzagoon (Ruby), level 5.", EVENTS, shiny=True),
    _event("SAPHIRE Zigzagoon", 263, "The Berry Glitch Fix shiny Zigzagoon (Sapphire), level 5.", EVENTS, shiny=True),
    _event("Aura Mew", 151, "The Aura Mew, level 10.", EVENTS),
    _event("MYSTRY Mew", 151, "The MYSTRY Mew, level 10.", EVENTS),
    _event("DOEL Deoxys", 386, "The DOEL Deoxys, level 70.", EVENTS),
    _event("SPACE C Deoxys", 386, "The SPACE C Deoxys, level 70.", EVENTS),
    _event("ROCKS Metang", 375, "The ROCKS Metang, level 30, with the National Ribbon.", EVENTS),
    *(_event(f"10 ANIV {name}", species, "Level 70, from the 10th anniversary.", ANNIVERSARY)
      for species, name in ((1, "Bulbasaur"), (6, "Charizard"), (9, "Blastoise"), (25, "Pikachu"),
                            (65, "Alakazam"), (144, "Articuno"), (145, "Zapdos"), (146, "Moltres"),
                            (149, "Dragonite"), (157, "Typhlosion"), (196, "Espeon"), (197, "Umbreon"),
                            (243, "Raikou"), (244, "Entei"), (245, "Suicune"), (248, "Tyranitar"),
                            (251, "Celebi"), (257, "Blaziken"), (359, "Absol"), (380, "Latias"), (381, "Latios"))),
    Preset("national-dex", "National Pokedex", MORE, "Upgrades the Pokedex to the National Pokedex.",
           {"kind": "composed", "gift": "national-dex"}),
    Preset("rare-berries", "Rare berries", MORE, "An Enigma, a Lansat and a Starf Berry.",
           {"kind": "composed", "gift": "rare-berries"}),
    Preset("starter-egg", "Starter egg", MORE, "An egg of one of the nine first partners.",
           {"kind": "composed", "gift": "starter-egg"}),
    Preset("master-ball", "Master Ball", MORE, "One Master Ball.", {"kind": "composed", "gift": "master-ball"}),
    Preset("rare-candy", "Rare Candy x5", MORE, "Five Rare Candies.", {"kind": "composed", "gift": "rare-candy"}),
)
PRESET = {p.key: p for p in PRESETS}


def blank():
    return dict(PRESETS[0].state)


def distribution(state):
    kind = state.get("kind") if isinstance(state, dict) else None
    if kind == "official":
        return gifts.official(state["gift"])
    if kind == "eon-ticket":
        return _eon_ticket()
    if kind == "composed":
        definition, flag_id = COMPOSED[state["gift"]]
        return gifts.composed(definition, flag_id=flag_id)
    raise ValueError("Choose an Emerald preset.")


def compile(state):
    preset = next((p for p in PRESETS if p.state == state), None)
    return gift_file.from_distribution(distribution(state),
                                       name=preset.label if preset else "Emerald gift")


def describe(state, name=lambda kind, n: f"{kind} #{n}"):
    """(when it applies, [what happens])."""
    preset = next((p for p in PRESETS if p.state == state), None)
    return (preset.when if preset else WHEN), [preset.summary if preset else "An Emerald Wonder Card."]

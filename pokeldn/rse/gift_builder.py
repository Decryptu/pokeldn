"""The app's Emerald Mystery Gifts (pokeldn.app.gift_builder): Emerald's own official gifts, then the
cards and event Pokemon every GBA title offers, from the FireRed builder's tables
(pokeldn.frlg.gift.builder) and built under Emerald's numbers. A card compiles to an Emerald
.pokegift; an event Pokemon goes to the launcher as --gift event-pokemon, which asks PKHeX for a
fresh legal copy."""

from dataclasses import dataclass

from pokeldn.frlg.gift import builder as frlg
from pokeldn.rse import constants as em, gift_file, gifts

KINDS = (("card", "Wonder Card", "gift"),)
BUILD = False                       # no "Build your own" form for Emerald yet
OFFICIAL_GIFTS = "Official Emerald gifts"
WHEN = "After the card is saved, talk to the delivery man on 2F of any Pokemon Center."
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


def _eon_ticket():
    """The ticket handout the game itself makes for the Eon Ticket [pokeemerald
    data/scripts/cable_club.inc:33]: done once the ship flag is set or the ticket held."""
    from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
    from pokeldn.frlg.gift.wonder_card import build_wonder_card
    script = gifts.ticket_script(em.ITEM_EON_TICKET, em.EMERALD_RULES.flag_for_flag_id(gifts.EON_FLAG_ID),
                                 (em.FLAG_ENABLE_SHIP_SOUTHERN_ISLAND,), em.FLAG_ENABLE_SHIP_SOUTHERN_ISLAND,
                                 f"{gifts.THANKS}\fLet me confirm--you are {{PLAYER}}?\f"
                                 "We received this EON TICKET\naddressed to you.")
    card = build_wonder_card(flag_id=gifts.EON_FLAG_ID, icon_species=407, title="EON TICKET",
                             subtitle="MYSTERY GIFT", body=("A ticket for the ferry", "at LILYCOVE CITY port."),
                             footer1="Talk to the delivery man on", footer2="2F of a POKéMON CENTER.")
    return MysteryGiftDistribution(card, script, game="emerald")


def _official(o):
    return Preset(o.key, o.label, OFFICIAL_GIFTS, o.summary, {"kind": "official", "gift": o.key},
                  species_id=NATIONAL.get(o.icon_species, 0))


PRESETS = (
    *(_official(o) for o in gifts.OFFICIAL[:3]),
    Preset("eon-ticket", "Eon Ticket", OFFICIAL_GIFTS, "The ferry to Southern Island, where Latias or Latios waits.",
           {"kind": "eon-ticket"}, species_id=380),
    *(_official(o) for o in gifts.OFFICIAL[3:]),
    *(Preset(p.key, p.label, p.group, p.summary, {"kind": "composed", "gift": p.key}, species_id=p.species_id)
      for p in frlg.GBA_CARDS),
    *(Preset(p.key, p.label, p.group, p.summary, args=p.args, species_id=p.species_id, shiny=p.shiny,
             when=p.when) for p in frlg.EVENT_PRESETS),
)
PRESET = {p.key: p for p in PRESETS}


def blank():
    return dict(PRESETS[0].state)


def distribution(state):
    kind = state.get("kind")
    if kind == "official":
        return gifts.official(state["gift"])
    if kind == "eon-ticket":
        return _eon_ticket()
    if kind == "composed":
        return gifts.composed(gifts.CARDS[state["gift"]])
    raise ValueError("Choose an Emerald preset.")


def compile(state):
    preset = next((p for p in PRESETS if p.state == state), None)
    return gift_file.from_distribution(distribution(state),
                                       name=preset.label if preset else "Emerald gift")


def describe(state, name=lambda kind, n: f"{kind} #{n}"):
    """(when it applies, [what happens])."""
    preset = next((p for p in PRESETS if p.state == state), None)
    return (preset.when if preset else WHEN), [preset.summary if preset else "An Emerald Wonder Card."]

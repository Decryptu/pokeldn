"""The app's Emerald Mystery Gifts (pokeldn.app.gift_builder): presets and opened files. Every
preset compiles to a .pokegift the launcher takes with --gift-file --version emerald."""

from dataclasses import dataclass

from pokeldn.frlg.gift import gift_composer as gc
from pokeldn.rse import constants as em, gift_file, gifts

KINDS = (("card", "Wonder Card", "gift"),)
BUILD = False                       # no "Build your own" form for Emerald yet
OFFICIAL_GIFTS = "Official Emerald gifts"
MORE = "More gifts"
WHEN = "After the card is saved, talk to the delivery man on 2F of any Pokemon Center."
NATIONAL = {410: 386, 250: 250, 151: 151, 235: 235}     # internal icon species -> National Dex


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    group: str
    summary: str
    state: dict
    args: tuple = ()
    species_id: int = 0
    when: str = WHEN


def _composed(slug, title, body, actions, icon):
    return gc.WonderGift(slug=slug, card=gc.WonderCardSpec(icon_species=icon, title=title, body=body,
                                                           subtitle="MYSTERY GIFT"),
                         intro_message="Thank you for using the MYSTERY\nGIFT System.",
                         event=gc.GiftSpec(), delivery=gc.DeliveryPlan(delivery=(gc.DeliveryStage(*actions),)))


COMPOSED = {
    "master-ball": (_composed("master-ball", "MASTER BALL", ("A MASTER BALL for you.",),
                              (gc.GiveItem(1),), 25), 1004),
    "rare-candy": (_composed("rare-candy", "RARE CANDY", ("Five RARE CANDIES for you.",),
                             (gc.GiveItem(68, 5),), 25), 1005),
    "surf-pichu": (_composed("surf-pichu", "POKéMON EGG", ("An EGG of a PICHU that knows SURF.",),
                             (gc.GiveEgg(172, moves=(57,), fateful_encounter=True),), 172), 1006),
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
             species_id=NATIONAL.get(o.icon_species, 0)) for o in gifts.OFFICIAL),
    Preset("eon-ticket", "Eon Ticket", MORE, "The ferry to Southern Island, where Latias or Latios waits.",
           {"kind": "eon-ticket"}, species_id=380),
    Preset("master-ball", "Master Ball", MORE, "One Master Ball.", {"kind": "composed", "gift": "master-ball"}),
    Preset("rare-candy", "Rare Candy x5", MORE, "Five Rare Candies.", {"kind": "composed", "gift": "rare-candy"}),
    Preset("surf-pichu", "Surfing Pichu egg", MORE, "A Pichu egg that hatches knowing Surf.",
           {"kind": "composed", "gift": "surf-pichu"}, species_id=172),
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
    return WHEN, [preset.summary if preset else "An Emerald Wonder Card."]

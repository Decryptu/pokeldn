"""The app's Emerald Mystery Gifts (pokeldn.app.gift_builder): presets and opened files. Every
preset compiles to a .pokegift the launcher takes with --gift-file --version emerald."""

from dataclasses import dataclass
from pokeldn.app.i18n import ref as _ref

from pokeldn.frlg.gift import gift_composer as gc
from pokeldn.rse import constants as em, gift_file, gifts

KINDS = (("card", _ref("core.pokeldn.frlg.gift.builder.wonder_card_81ebceeb"), "gift"),)
BUILD = False                       # no "Build your own" form for Emerald yet
OFFICIAL_GIFTS = _ref("core.rse.gift.official")
MORE = _ref("core.rse.gift.more")
WHEN = _ref("core.rse.gift.when")
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
    *(Preset(o.key, _ref(f"core.rse.gift.{o.key}.title"), OFFICIAL_GIFTS, _ref(f"core.rse.gift.{o.key}.description"), {"kind": "official", "gift": o.key},
             species_id=NATIONAL.get(o.icon_species, 0)) for o in gifts.OFFICIAL),
    Preset("eon-ticket", _ref("core.rse.gift.eon-ticket.title"), MORE, _ref("core.rse.gift.eon-ticket.description"),
           {"kind": "eon-ticket"}, species_id=380),
    Preset("master-ball", _ref("core.rse.gift.master-ball.title"), MORE, _ref("core.rse.gift.master-ball.description"), {"kind": "composed", "gift": "master-ball"}),
    Preset("rare-candy", _ref("core.rse.gift.rare-candy.title"), MORE, _ref("core.rse.gift.rare-candy.description"), {"kind": "composed", "gift": "rare-candy"}),
    Preset("surf-pichu", _ref("core.rse.gift.surf-pichu.title"), MORE, _ref("core.rse.gift.surf-pichu.description"),
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
    return WHEN, [preset.summary if preset else _ref("core.rse.gift.unknown")]

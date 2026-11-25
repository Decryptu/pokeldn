"""Emerald's Mystery Gifts: the four official gift scripts pokeemerald ships
(data/scripts/gift_*.inc), op for op with pokeldn's own text, and gifts composed by
pokeldn.frlg.gift.gift_composer under Emerald's numbers. docs/rse.md, Mystery Gift."""

from dataclasses import dataclass

from pokeldn.frlg.gift import gift_composer as gc, wonder_card_events as events
from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
from pokeldn.frlg.gift.wonder_card import build_wonder_card
from pokeldn.frlg.rom.scrcmd import VAR_0x8008
from pokeldn.rse import constants as em
from pokeldn.rse.scripts import LOCK, FACEPLAYER, RELEASE, END, SETFLAG, ADDVAR, SETVAR, VAR_RESULT, Script

THANKS = "Thank you for using the MYSTERY\nGIFT System."
FULL = "Oh, I'm sorry, {PLAYER}.\nYour BAG's KEY ITEMS POCKET is full.\fPlease store something on your PC,\nthen come back for this."
AT_PORT = "It appears to be for use at the\nLILYCOVE CITY port.\fWhy not give it a try and see what\nit is about?"


def ticket_script(item, received_flag, done_flags, ship_flag, offer):
    """gift_aurora_ticket.inc, gift_mystic_ticket.inc and gift_old_sea_map.inc: one shape, three
    tickets [pokeemerald data/scripts]."""
    s = Script()
    s.op(LOCK)
    s.op(FACEPLAYER)
    s.vgoto_if_set(received_flag, "obtained")
    for flag in done_flags:
        s.vgoto_if_set(flag, "obtained")
    s.checkitem(item)
    s.vgoto_if_eq(VAR_RESULT, 1, "obtained")
    s.vmessage(offer)
    s.checkitemspace(item)
    s.vgoto_if_eq(VAR_RESULT, 0, "no_space")
    s.giveitem(item)
    s.op(SETFLAG, ship_flag)
    s.op(SETFLAG, received_flag)
    s.vmessage(AT_PORT)
    s.op(RELEASE)
    s.op(END)
    s.label("no_space")
    s.vmessage(FULL)
    s.op(RELEASE)
    s.op(END)
    s.label("obtained")
    s.vmessage(THANKS)
    s.op(RELEASE)
    s.op(END)
    return s.assemble()


def altering_cave_script():
    """gift_altering_cave.inc: the next of the cave's nine wild tables, wrapping to the first."""
    s = Script()
    s.op(ADDVAR, em.VAR_ALTERING_CAVE_WILD_SET, 1)
    s.vgoto_if_ne(em.VAR_ALTERING_CAVE_WILD_SET, em.NUM_ALTERING_CAVE_TABLES + 1, "talk")
    s.op(SETVAR, em.VAR_ALTERING_CAVE_WILD_SET, 0)
    s.label("talk")
    s.op(LOCK)
    s.op(FACEPLAYER)
    s.vmessage(THANKS + "\fThere appears to be a rumor about\nrare POKéMON sightings.\f"
               "The sightings reportedly came from\nthe ALTERING CAVE on ROUTE 103.")
    s.op(RELEASE)
    s.op(END)
    return s.assemble()


@dataclass(frozen=True)
class Official:
    key: str
    label: str
    summary: str
    flag_id: int                    # its sReceivedGiftFlags entry [mystery_gift.c:229]
    icon_species: int               # an internal species number
    title: str
    body: tuple
    script: object


def _ticket(item, received, done, ship, what):
    return lambda: ticket_script(item, received, done, ship,
                                 f"{THANKS}\fLet me confirm--you are {{PLAYER}}?\f"
                                 f"We received this {what}\naddressed to you.")


OFFICIAL = (
    Official("aurora-ticket", "Aurora Ticket", "The ferry to Birth Island, where Deoxys waits.",
             1000, 410, "AURORA TICKET", ("A ticket for the ferry", "at LILYCOVE CITY port."),
             _ticket(em.ITEM_AURORA_TICKET, em.FLAG_RECEIVED_AURORA_TICKET, (em.FLAG_BATTLED_DEOXYS,),
                     em.FLAG_ENABLE_SHIP_BIRTH_ISLAND, "AURORA TICKET")),
    Official("mystic-ticket", "Mystic Ticket", "The ferry to Navel Rock, where Ho-Oh and Lugia wait.",
             1001, 250, "MYSTIC TICKET", ("A ticket for the ferry", "at LILYCOVE CITY port."),
             _ticket(em.ITEM_MYSTIC_TICKET, em.FLAG_RECEIVED_MYSTIC_TICKET,
                     (em.FLAG_CAUGHT_LUGIA, em.FLAG_CAUGHT_HO_OH), em.FLAG_ENABLE_SHIP_NAVEL_ROCK,
                     "MYSTIC TICKET")),
    Official("old-sea-map", "Old Sea Map", "The ferry to Faraway Island, where Mew waits.",
             1002, 151, "OLD SEA MAP", ("A map of a faraway island,", "for the LILYCOVE CITY port."),
             _ticket(em.ITEM_OLD_SEA_MAP, em.FLAG_RECEIVED_OLD_SEA_MAP, (em.FLAG_CAUGHT_MEW,),
                     em.FLAG_ENABLE_SHIP_FARAWAY_ISLAND, "OLD SEA MAP")),
    Official("altering-cave", "Altering Cave rumor", "Rare Pokemon appear in the Altering Cave on Route 103.",
             1003, 235, "ALTERING CAVE", ("Rare POKéMON sightings", "on ROUTE 103."),
             altering_cave_script),
)
OFFICIAL_BY_KEY = {o.key: o for o in OFFICIAL}


def official(key):
    """-> the MysteryGiftDistribution of an official gift."""
    gift = OFFICIAL_BY_KEY[key]
    card = build_wonder_card(flag_id=gift.flag_id, icon_species=gift.icon_species, title=gift.title,
                             subtitle="MYSTERY GIFT", body=gift.body,
                             footer1="Talk to the delivery man on", footer2="2F of a POKéMON CENTER.")
    return MysteryGiftDistribution(card, gift.script(), game="emerald")


def composed(definition, flag_id=None):
    """-> the MysteryGiftDistribution of a gift_composer definition, under Emerald's numbers."""
    built = gc.compile_definition(definition, flag_id=flag_id, rules=em.EMERALD_RULES)
    if isinstance(built, dict):
        raise ValueError("A stamp rally is not offered for Emerald.")
    return MysteryGiftDistribution(built.card, built.ram_script, mevent=built.mevent, game="emerald")


BATTLE_COUNT_PRIZE_TAKEN = em.VAR_GIFT_SLOT_VARS[0]

BATTLE_COUNT_GIFT = gc.WonderGift(
    slug=events.GIFT_BATTLE_COUNT,
    card=gc.WonderCardSpec(
        icon_species=events.SPECIES_CLEFAIRY_MEVENT,
        card_type=gc.CARD_TYPE_LINK_STAT,
        title="BATTLE COUNT CARD",
        subtitle="Your record against holders",
        body=(
            "This CARD keeps track of your",
            "battles against TRAINERS who",
            "hold the same CARD.",
            "Win three for a prize!",
        ),
        footer1="pokeldn",
        default_flag_id=events.BATTLE_COUNT_FLAG_ID,
    ),
    intro_message=THANKS,
    event=gc.GiftSpec(repeatable=True),
    delivery=gc.DeliveryPlan(delivery=(
        gc.DeliveryStage(
            gc.SetVar(VAR_RESULT, gc.GET_CARD_BATTLES_WON),
            gc.ReadSpecial(VAR_0x8008, em.SPECIAL_GET_MYSTERY_GIFT_CARD_STAT),
        ),
        gc.DeliveryStage(
            gc.Message(
                "Congratulations!\n"
                "You have won a prize for winning\n"
                "three battles!"),
            gc.GiveItem(events.ITEM_POTION),
            gc.SetVar(BATTLE_COUNT_PRIZE_TAKEN, 1),
            condition=gc.AllOf((
                gc.VarEquals(VAR_0x8008, events.BATTLE_COUNT_PRIZE_WINS),
                gc.Not(gc.VarEquals(BATTLE_COUNT_PRIZE_TAKEN, 1)),
            )),
        ),
        gc.DeliveryStage(
            gc.Message(
                "Look for and battle TRAINERS who\n"
                "have the same CARD as you."),
        ),
    )),
    completed_message="Look for and battle TRAINERS who\nhave the same CARD as you.",
)

NATIONAL_DEX_GIFT = gc.WonderGift(
    slug="national-dex",
    card=gc.WonderCardSpec(
        icon_species=137,
        title="NATIONAL POKéDEX",
        subtitle="Every POKéMON, right away",
        body=("Upgrade your POKéDEX to the", "NATIONAL POKéDEX now. Visit", "the delivery man on the 2nd",
              "floor of a POKéMON CENTER."),
        footer1="pokeldn",
        default_flag_id=1011,
    ),
    intro_message=THANKS,
    event=gc.GiftSpec(),
    delivery=gc.DeliveryPlan(delivery=(
        gc.DeliveryStage(gc.Exit(), condition=gc.FlagSet(em.FLAG_SYS_NATIONAL_DEX)),
        gc.DeliveryStage(gc.ReadSpecial(VAR_0x8008, em.SPECIAL_ENABLE_NATIONAL_POKEDEX),
                         gc.Message("Done! Your POKéDEX is now the\nNATIONAL POKéDEX.")),
    )),
    completed_message="Your POKéDEX is the\nNATIONAL POKéDEX!",
)


def event_pokemon(pk3=events.WISHMKR_JIRACHI_PK3, *, name="WISHMKR Jirachi", flag_id=None):
    """-> an Emerald distribution sending `pk3` straight to the party via `givepokemon`."""
    return composed(events.build_event_pokemon_gift(pk3, name=name), flag_id=flag_id)


@dataclass(frozen=True)
class EmeraldPayload:
    """An Emerald gift file for bin/frlg_mg_host.py: one distribution for every Emerald cartridge,
    since nothing in it names a ROM address. `file` makes the host log it as an imported file."""
    file: object
    dump_file: str | None = None
    definition = None
    requires_build_selection = False

    @property
    def distribution(self):
        from pokeldn.rse import gift_file
        return gift_file.distribution(self.file.variants[gift_file.TARGET])

    @property
    def gift(self):
        return self.file.name

    @property
    def flag_id(self):
        return int.from_bytes(self.distribution.card[:2], "little")

    @property
    def receipt_flag(self):
        return em.EMERALD_RULES.flag_for_flag_id(self.flag_id)

    def build_distribution(self, build=None):
        return self.distribution

    def build(self, build=None):
        return self.distribution.card, self.distribution.ram_script

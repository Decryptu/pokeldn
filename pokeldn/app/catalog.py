"""What the app offers per game: each tool is an entry point, the tested flags it always gets, the
fields a user fills in, and what to press on the console. Fixed arguments may carry {received}
(the Received folder), {stamp} (the run's time) and {src_var} (a fresh random id)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    flag: str | tuple[str, ...]   # "" is positional; a tuple passes the same value to each flag
    label: str
    kind: str = "text"            # text number choice switch pokemon file multi, or a PKHeX name list:
                                  # species move item ball
    help: str = ""
    default: str | bool = ""
    choices: tuple[tuple[str, str], ...] = ()
    required: bool = False
    group: str = ""               # fields sharing a group render on one card
    invert: bool = False          # a switch that passes its flag when turned off
    unset: tuple[str, ...] = ()   # arguments passed when the field is left empty
    exts: tuple[str, ...] = ()
    when: tuple[str, str] = ()    # (flag, value): the field applies only while that field has that value
    template: str = ""            # the value is passed as template.format(value), e.g. "ball={}"
    limits: tuple[tuple[str, int, str], ...] = ()   # (NAME, highest, why) for NAME=VALUE text
    choice_help: tuple[tuple[str, str], ...] = ()
    queue: int = 1                # a pokemon field: how many trades one session can carry
    more: str = ""                # a pokemon field: the flag for the second and later offers
    count: str = ""               # a pokemon field: the flag that carries how many there are
    hidden: bool = False          # applied with its default, set on the Advanced tab instead of Basic
    shiny: bool = False           # a switch that makes the species field's Pokemon shiny, for its sprite

    @property
    def key(self) -> str:
        if isinstance(self.flag, tuple):
            return self.flag[0]
        if self.template:
            return f"{self.flag} {self.template}"
        return self.flag or f"#{self.label}"


@dataclass(frozen=True)
class Tool:
    key: str
    name: str
    script: str
    summary: str
    steps: tuple[str, ...]
    fields: tuple[Field, ...] = ()
    fixed: tuple[str, ...] = ()
    doc: str = ""
    unavailable: str = ""         # why the tool cannot run yet; it is shown greyed out


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    short: str
    doc: str
    tools: tuple[Tool, ...]


VERSIONS = (("firered", "FireRed"), ("leafgreen", "LeafGreen"))
LANGUAGES = (("english", "English"), ("french", "French"), ("german", "German"),
             ("italian", "Italian"), ("spanish", "Spanish"))
CHANNELS = (("1", "1"), ("6", "6"), ("11", "11"))
FRESH_PID = Field("--fresh-pid", "New PID each run", "switch", default=True, hidden=True,
                  help="Offer the Pokemon under a new PID and encryption constant, so a save that "
                       "already received it takes it again. Turn it off for a file whose PID must stay, "
                       "such as an event Pokemon.")
CHANNEL_HELP = "The wireless channel of the network pokeldn hosts."
CODE_HELP = "The same code the player enters on the console."


def host_seconds(default: str, extra: str = "") -> Field:
    return Field("--seconds", "Time limit (seconds)", "number", default=default, hidden=True,
                 help=" ".join(p for p in ("How long the host stays up after Start, then it closes on "
                                           "its own. Leave time for every trade in the queue.", extra) if p))


def join_seconds(default: str) -> Field:
    return Field("--hold", "Time limit (seconds)", "number", default=default, hidden=True,
                 help="How long the joiner stays connected once it joins the console, then it leaves "
                      "on its own.")


QUEUE = 6   # a party's worth


def offer(flag: str = "", required: bool = True, help: str = "", queue: int = 1, more: str = "",
          count: str = "") -> Field:
    return Field(flag, "Pokemon to offer", "pokemon", required=required,
                 help=help or "Pick a species; PKHeX builds a legal one for this game.",
                 queue=queue, more=more, count=count)


def queued(flag: str = "", help: str = "", **kw) -> Field:
    """An offer field whose session trades each entry in turn, on one seat."""
    help = help or "Pick a species; PKHeX builds a legal one for this game."
    return offer(flag, help=f"{help} Add a trade to queue more: one session trades them in order.",
                 queue=QUEUE, **kw)


CARD = ("--news", "")
SAVE_DUMP = ("--buffer-script", "save-dump")
HOOK = ("--buffer-script", "install-resident")
FRLG_PATH = "Pokemon Center 2F, third attendant, Direct Corner, Trade Center"

FRLG = Game("frlg", "FireRed & LeafGreen", "FRLG", "frlg.md", (
    Tool("frlg-trade-host", "Trade (Host)", "bin/frlg_trade_host.py",
         "Host a Direct Corner trade. The console joins pokeldn's group.",
         ("Start the host and wait for 'Hosting Direct Corner' in the log.",
          f"{FRLG_PATH}, Join Group, then pick PkCamp.",
          "Choose the Pokemon to trade and confirm.",
          "With several queued, trade again after each save; the host offers the next one.",
          "Back on the trade menu after the last save, wait for the host's prompt, then Cancel and Yes."),
         (queued(count="--trades"),
          Field("--version", "Version", "choice", default="firered", choices=VERSIONS, group="Console",
                help="The game pokeldn's own trainer reports on the link, and the one the Pokemon is built for."),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, hidden=True,
                help="The language pokeldn's own trainer reports on the link."),
          Field("--channel", "Channel", "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live", "--phy", "auto", "--slot", "0", "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-trade-join", "Trade (Join)", "bin/frlg_trade_join.py",
         "Join a trade group the console leads.",
         ("Start the joiner first: it scans until the console appears.",
          f"{FRLG_PATH}, Become Leader.",
          "Accept PkCamp when it appears, then choose and confirm.",
          "With several queued, trade again after each save; the joiner offers the next one."),
         (queued(count="--trades"),),
         fixed=("--live", "--phy", "auto", "--slot", "0", "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-gift", "Mystery Gift", "bin/frlg_mg_host.py",
         "Send a Wonder Card or Wonder News. Collect the gift from the delivery man in any Pokemon Center.",
         ("Title screen: Mystery Gift, Wonder Cards, Friend. For news: the second entry, Wonder News.",
          "Start the host, then pick PkCamp when it appears.",
          "Answer Yes if the console asks to replace its card.",
          "Back out of the search screen between two runs."),
         (Field("--news", "Send", "choice", help="A Wonder Card brings a gift; Wonder News is a message "
                                                 "that can carry a berry.", choices=(
             ("", "A Wonder Card"), ("pkcamp", "Wonder News: one berry in Cerulean City"),
             ("berry", "Wonder News: ten lines, one berry"))),
          Field("--gift", "Wonder Card", "choice", default="beast-cutscene", when=CARD,
                help="The gift the card holds.", choices=(
              ("beast-cutscene", "Legendary beast (follows the starter)"),
              ("celebi", "Celebi"), ("master-ball", "Master Ball"),
              ("altering-cave", "Altering Cave"), ("porygon-tm-gift", "Porygon TM gift"),
              ("solrock-stamp", "Sun and Moon Rally: Solrock stamp"),
              ("lunatone-stamp", "Sun and Moon Rally: Lunatone stamp"),
              ("visiting-trainer", "Visiting trainer"), ("battle-count-card", "Battle count card"),
              ("worlds-xp", "Worlds XP"))),
          Field("--flag-id", "Card flag id", "number", when=CARD, hidden=True,
                help="1000 to 1019. A console refuses the id of the card it already holds; "
                     "alternate between two. Empty uses the gift's own."),
          Field(("--version", "--expect-console"), "Version", "choice", default="firered",
                choices=VERSIONS, group="Console",
                help="The console's cartridge: another one is refused before anything is sent."),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, hidden=True,
                help="The language pokeldn's own trainer reports on the link."),
          Field("--channel", "Channel", "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live",), doc="frlg_gift.md"),
    Tool("frlg-code", "Console code", "bin/frlg_mg_host.py",
         "Run native code on the console through Mystery Gift: read the save, or install a per-frame hook.",
         ("Title screen: Mystery Gift, Wonder Cards, Friend.",
          "Start the host, then pick PkCamp when it appears.",
          "Keep the host running until the log shows the result; a dump is written a few seconds later."),
         (Field("--buffer-script", "Action", "choice", default="save-dump",
                help="What the code does on the console. A read leaves the game unchanged.", choices=(
             ("trainer-id-probe", "Read the trainer id (reads only)"),
             ("save-dump", "Read part of the save (reads only)"),
             ("install-resident", "Install a hook until the next reset (writes RAM)"))),
          Field("--dump-block", "Save block", "choice", default="sav2", group="Save dump",
                help="The part of the save to read, and how many bytes; the file lands in Received.",
                choices=(("sav2", "Trainer (sav2)"), ("sav1", "Party, bag, flags (sav1)")),
                when=SAVE_DUMP),
          Field("--dump-size", "Bytes", "number", default="64", group="Save dump", when=SAVE_DUMP),
          Field("--resident", "Hook", "choice", default="turbo", when=HOOK, choices=(
              ("turbo", "Turbo"), ("shiny", "Shiny encounters"), ("ivs", "IVs on screen"),
              ("noencounter", "No wild encounters")),
                help="Applies until the next soft reset.", choice_help=(
                    ("turbo", "Speeds up dialogue text. Movement and battle speed can be adjusted "
                              "with --resident-param in Advanced."),
                    ("shiny", "Shows a countdown to the next shiny wild encounter."),
                    ("ivs", "Displays the lead Pokemon's six IVs and nature number on screen."),
                    ("noencounter", "Disables grass, water and roaming encounters. "
                                    "Fishing and Sweet Scent still work."))),
          Field("--write-unsafe", "Allow writes", "switch", default=True, when=HOOK, hidden=True,
                help="A hook needs it: it changes the running game until a soft reset."),
          Field(("--version", "--expect-console"), "Version", "choice", default="firered",
                choices=VERSIONS, group="Console",
                help="The console's cartridge: another one is refused before anything is sent."),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, hidden=True,
                help="The language pokeldn's own trainer reports on the link.")),
         fixed=("--live", "--dump-file", "{received}/frlg-dump-{stamp}.bin"), doc="frlg_rom.md"),
))

LGPE_STEPS = "X, Communicate, Local Communication, Trade, enter the same link code, then search."

LGPE = Game("lgpe", "Let's Go Pikachu & Eevee", "LGPE", "lgpe.md", (
    Tool("lgpe-host", "Trade (Host)", "bin/lgpe_host.py",
         "Host a trade under a link code; the console joins.",
         ("Start the host first.", LGPE_STEPS, "Choose a Pokemon and confirm."),
         (queued("--offer", more="--next-offer"),
          Field("--code", "Link code", default="pikachu,pikachu,pikachu",
                help="Three picker names or indices 0 to 9, comma-separated."),
          FRESH_PID,
          host_seconds("1200", "A trade under way when it runs out is finished first.")),
         fixed=("--first", "echo", "--received", "{received}/lgpe-{stamp}.pb7"), doc="lgpe.md"),
    Tool("lgpe-join", "Trade (Join)", "bin/lgpe_join.py",
         "Join the console's trade search.",
         ("Start the joiner: it scans for up to five minutes.", LGPE_STEPS,
          "Offer and confirm once PkCamp shows. Queued Pokemon follow, one per trade."),
         (queued("--offer"), FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "2.5", "--connect", "--connect-seconds", "1800",
                "--ack-peer-clock", "--ack-re-announce", "--facts", "lgpe_net_facts.json",
                "--received", "{received}/lgpe-{stamp}.pb7"),
         doc="lgpe_session.md"),
))

SWSH = Game("swsh", "Sword & Shield", "SwSh", "swsh.md", (
    Tool("swsh-gift", "Mystery Gift", "bin/swsh_gift_host.py",
         "Advertise a Wonder Card. Nothing joins; the console reads it off the air.",
         ("Mystery Gift, Receive a Gift, via local wireless.",
          "Start the host: the card is listed within a few seconds or not at all.",
          "Accept the card, then stop the host."),
         (Field("--species", "Species", "species", default="25", group="Pokemon",
                help="The Pokemon on the card and its level."),
          Field("--level", "Level", "number", default="25", group="Pokemon", help="0 lets the game roll one."),
          Field("--move1", "Move 1", "move", default="84", group="Moves", help="The four moves it knows."),
          Field("--move2", "Move 2", "move", default="45", group="Moves"),
          Field("--move3", "Move 3", "move", default="86", group="Moves"),
          Field("--move4", "Move 4", "move", default="98", group="Moves"),
          Field("--set", "Held item", "item", template="held_item={}", group="Extras",
                help="Empty for no item and the game's default ball."),
          Field("--set", "Ball", "ball", template="ball={}", group="Extras"),
          Field("--set", "Shiny", "switch", template="shiny_type=2", default=False, shiny=True,
                help="The Pokemon arrives shiny."),
          Field("--nickname", "Nickname", default="PKCAMP", group="Names",
                help="The Pokemon's nickname and the original trainer name it shows."),
          Field("--ot", "OT", default="POKELDN", group="Names"),
          Field("--set", "Other fields", "multi", hidden=True,
                help="Any other record field, space-separated NAME=VALUE: nature=10 gender=1 iv_hp=31.",
                limits=(("held_item", 1607, "Sword and Shield have no item above 1607; a higher id crashes "
                                            "the bag screen."),)),
          Field("--card-id", "Card id", "number", default="9999",
                help="Change it when the console already holds this card."),
          Field("--record", "Or send a .wc8 file", "file", exts=("wc8",),
                help="A Wonder Card file from PKHeX or an event archive. It replaces everything above."),
          Field("--seconds", "Time limit (seconds)", "number", default="300", hidden=True,
                help="How long the card is advertised after Start.")),
         doc="swsh_gift.md"),
    Tool("swsh-join", "Trade (Join)", "bin/swsh_connect.py", "Join the console's Link Trade search.",
         ("Y-Comm, Link Trade, local communication, no code; press A on both messages.",
          "Start the joiner while the console searches.",
          "PkCamp appears on the trade screen: choose a Pokemon and confirm.",
          "Queued Pokemon follow, one per trade: pick again from the box."),
         (queued("--offer-file", required=False,
                 help="Pick a species; PKHeX builds a legal one. Empty offers your own first party "
                      "Pokemon back, renamed PKCAMP."),
          FRESH_PID,
          join_seconds("900")),
         fixed=("--preset", "trade", "--send-snapshot", "live",
                "--save-offered", "{received}/swsh-{stamp}.pk8"),
         doc="swsh_trade.md"),
    Tool("swsh-host", "Trade (Host)", "bin/swsh_host.py", "Host a Link Trade the console joins.",
         ("Start the host and wait for the network to come up.",
          "Y-Comm, Link Trade, local communication; press A on both messages, then wait in the overworld.",
          "Choose a Pokemon and confirm when PkCamp appears.",
          "Queued Pokemon follow, one per trade: pick again from the box."),
         (queued("--offer-file"), FRESH_PID,
          Field("--code", "Link Code", help="Eight digits. Empty for a plain trade."),
          Field("--channel", "Channel", "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("900")),
         fixed=("--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}",
                "--received", "{received}/swsh-{stamp}.pk8"), doc="swsh_trade.md"),
))

BDSP_ROOM = "Pokemon Center 2F, left attendant, plain Yes (no password, not the group option)."

BDSP = Game("bdsp", "Brilliant Diamond & Shining Pearl", "BDSP", "bdsp.md", (
    Tool("bdsp-join", "Trade (Join)", "bin/bdsp_connect.py",
         "Join the console's Union Room as a character and trade.",
         (f"{BDSP_ROOM} Wait in the room, clear of the walls.",
          "Start the joiner and wait for the character to appear.",
          "Y, Communicate, Trade Pokemon, and wait: the greeting comes up on its own.",
          "Between runs, leave and re-enter the room."),
         (queued("--trade-template"),
          Field("--trade-nickname", "Nickname", hidden=True,
                help="A nickname given to every offered Pokemon; empty keeps the one it was built with."),
          FRESH_PID,
          join_seconds("600")),
         fixed=("--channels", "1,6,11", "--count", "9", "--connect", "5", "--join", "6",
                "--reliable-ack", "--reliable-sweep", "3", "--room-walk", "15", "--room-pattern", "fixed",
                "--room-walk-steps", "0", "--join-avatar", "0", "--answer-requests", "--state", "0",
                "--recruiting", "0", "--answer-talk", "--can-talk", "0", "--initiate-talk",
                "--initiate-delay", "3", "--after-approach", "0x06:0001000000", "--trade-reply",
                "--complete-trade", "--src-var", "{src_var}",
                "--trade-save-poke", "{received}/bdsp-{stamp}.pb8"),
         doc="bdsp_trade.md"),
    Tool("bdsp-host", "Trade (Host)", "bin/bdsp_host.py",
         "Host a Union Room the console enters.",
         ("Start the host before the player enters the room.",
          f"{BDSP_ROOM} Our character appears.",
          "Y, Communicate, Trade Pokemon; accept the greeting, then choose and confirm."),
         (queued("--offer"),
          FRESH_PID,
          Field("--password", "Room password", help="Eight digits. Empty for the plain room."),
          host_seconds("1500")),
         fixed=("--ldn-protocol", "1", "--complete-trade", "--save-theirs", "{received}/bdsp-{stamp}"),
         doc="bdsp_trade.md"),
))

PLA_STEPS = ("Talk to the trade NPC in Jubilife Village: trade, local, past the warning.",
             "Enter the same eight-digit code and press + to search.")
PLA_OFFER_HELP = "Pick a species; PKHeX builds a legal one. Empty offers pokeldn's own Azelf."

PLA = Game("pla", "Legends Arceus", "PLA", "pla.md", (
    Tool("pla-host", "Trade (Host)", "bin/pla_host.py",
         "Host a trade under a link code; the console joins.",
         ("Start the host first.", *PLA_STEPS, "Offer a Pokemon and confirm.",
          "Leave the host running until the trade ends: an interrupted trade locks trading for a while."),
         (queued("--trade-box-record", required=False, help=PLA_OFFER_HELP),
          Field("--code", "Link code", default="00000000", help=CODE_HELP),
          FRESH_PID,
          host_seconds("900")),
         fixed=("--channel", "6", "--session-update", "--sustain", "--clock", "--data-exchange",
                "--game-channel", "--trade-box", "--trade-box-collect", "{received}/pla-{stamp}"),
         doc="pla.md"),
    Tool("pla-join", "Trade (Join)", "bin/pla_join.py",
         "Join the console's search. It hands pokeldn the host role, which the joiner takes on its own.",
         (*PLA_STEPS, "Start the joiner.", "Offer and confirm once the partner shows."),
         (queued("--offer", required=False, help=PLA_OFFER_HELP),
          Field("--code", "Link code", default="00000000", help=CODE_HELP),
          FRESH_PID),
         fixed=("--offer-out", "{received}/pla-{stamp}.pa8", "--collect", "{received}/pla-{stamp}"),
         doc="pla.md"),
))

SV_SEARCH = "X, Poke Portal, Link Trade, offline, then search."

SV = Game("sv", "Scarlet & Violet", "SV", "sv.md", (
    Tool("sv-join", "Trade (Join)", "bin/sv_join.py",
         "Join the console's Link Trade search.",
         (SV_SEARCH, "Start the joiner.", "Offer and confirm on the trade screen.",
          "If the console keeps refusing, leave and re-enter the search screen."),
         (queued("--trade-offer"),
          Field("--code", "Link Code", help="Empty joins a search with no code."),
          FRESH_PID),
         fixed=("--phy", "auto", "--seconds", "1500", "--hold", "900", "--channels", "1,6,11",
                "--dwell", "0.4", "--connect-timeout", "6", "--open-delay", "0.3", "--record-delay", "0.3",
                "--session-join", "--answer-migration", "--net-ack", "--ack-flags", "0x00",
                "--game-channel", "--announce-timeout", "20", "--rtt-delay", "0.3",
                "--offer-out", "{received}/sv-{stamp}.pk9"), doc="sv.md"),
    Tool("sv-host", "Trade (Host)", "bin/sv_host.py",
         "Host a trade the searching console joins.",
         ("Start the host first.", SV_SEARCH, "Offer and confirm on the trade screen."),
         (queued("--trade-offer"),
          Field("--code", "Link Code", help="Empty hosts a search with no code.",
                unset=("--game-data",
                       "000000000000000000000000000000000000000000000000000000000000000000648cf400000000")),
          FRESH_PID),
         fixed=("--channel", "6", "--seconds", "900", "--host-player-id", "00000000000000010000000000000000",
                "--player-name", "RyuPlayer", "--rtt-probe", "--net-property", "--clock", "--net-stations", "4",
                "--scarlet-response", "--join-seq", "0", "--update-first-seq", "0", "--update-seq", "1",
                "--session-flags", "0x00", "--no-session-ack", "--update-delay", "2.03",
                "--host-player-name", " ", "--record-delay", "0.17",
                "--send-at", "0.06:0x7c:1:b90104b902b9027b0001b902b902320201b902b902320101b902b902320301",
                "--send-at", "0.06:0x81:1:0000000000f38800000000",
                "--send-at", "0.04:0x81:5:000500000ff00800000000",
                "--announce", "--announce-delay", "5.25",
                "--send-at", "6.00:0x7c:1:b90101b902b90280800001", "--offer-after-open", "2",
                "--offer-out", "{received}/sv-{stamp}.pk9"),
         doc="sv.md"),
))

ZA = Game("za", "Legends Z-A", "PLZA", "za.md", (
    Tool("za-join", "Trade (Join)", "bin/za_join.py",
         "Join the console's Link Trade search.",
         ("Link Trade, local communication, search with the link code.",
          "Start the joiner. Refusals while seating are normal; let it run.",
          "Pick on the trade box and confirm once PKLDN appears. Queued Pokemon follow, one per trade."),
         (queued("--trade-offer"),
          Field("--code", "Link code", default="00000000", help=CODE_HELP),
          FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "0.35", "--seconds", "1200", "--hold", "900",
                "--quiet-seat", "25", "--connect-timeout", "6", "--mac", "02:11:32:54:76:98", "--game",
                "--offer-delay", "4", "--offer-out", "{received}/za-{stamp}.pa9"),
         doc="za.md"),
    Tool("za-host", "Trade (Host)", "bin/za_host.py",
         "Host a trade the searching console joins.",
         ("Start the host first.",
          "X, Link Play, Link Trade, Nearby Players, the same code, then search.",
          "Pick on the trade box, offer, then trade. Queued Pokemon follow, one per trade.",
          "Back out with B after the last trade."),
         (queued("--trade-offer"),
          Field("--code", "Link code", default="00000000", help=CODE_HELP),
          FRESH_PID,
          host_seconds("900")),
         fixed=("--offer-out", "{received}/za-{stamp}.pa9"), doc="za.md"),
))

GAMES = (FRLG, LGPE, SWSH, BDSP, PLA, SV, ZA)

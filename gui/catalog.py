"""What the app offers per game: each tool is an entry point, the tested flags it always gets, the
fields a user fills in, and what to press on the console."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    flag: str | tuple[str, ...]   # "" is positional; a tuple passes the same value to each flag
    label: str
    kind: str = "text"            # text number choice switch file files dir save argsfile multi
    help: str = ""
    default: str | bool = ""
    choices: tuple[tuple[str, str], ...] = ()
    required: bool = False
    group: str = ""               # fields sharing a group render on one card
    invert: bool = False          # a switch that passes its flag when turned off
    unset: tuple[str, ...] = ()   # arguments passed when the field is left empty
    exts: tuple[str, ...] = ()
    when: tuple[str, str] = ()    # (flag, value): the field applies only while that field has that value

    @property
    def key(self) -> str:
        if isinstance(self.flag, tuple):
            return self.flag[0]
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
    needs: tuple[str, ...] = ()   # reference files the entry point reads from the work folder
    radio: bool = True
    doc: str = ""
    warning: str = ""
    setup: bool = False           # a preparation step, listed after the main tools


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
FRESH_PID = Field("--fresh-pid", "New PID each run", "switch", default=True,
                  help="Offer the Pokemon under a new PID and encryption constant, so a save that "
                       "already received it takes it again.")


def _party(flag=""):
    return Field(flag, "Party", "files", required=True, exts=("pk3", "ek3"),
                 help="One to six .pk3 or .ek3 files, in party order.")


CARD = ("--news", "")
SAVE_DUMP = ("--buffer-script", "save-dump")
HOOK = ("--buffer-script", "install-resident")
FRLG_PATH = "Pokemon Center 2F, third attendant, Direct Corner, Trade Center"

FRLG = Game("frlg", "FireRed & LeafGreen", "FRLG", "frlg.md", (
    Tool("frlg-trade-host", "Trade", "bin/frlg_trade_host.py",
         "Host a Direct Corner trade. The console joins pokeldn's group.",
         ("Start the host and wait for 'Hosting Direct Corner' in the log.",
          f"{FRLG_PATH}, Join Group, then pick PkCamp.",
          "Choose the Pokemon to trade and confirm.",
          "Back on the trade menu after the save, wait for the host's prompt, then Cancel and Yes."),
         (_party(),
          Field("--slot", "Offered slot", "number", default="1",
                help="Zero-based party slot pokeldn offers."),
          Field("--out", "Save received Pokemon to", "save", default="received/frlg-{stamp}.pk3"),
          Field("--version", "Version", "choice", default="firered", choices=VERSIONS, group="Trainer"),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, group="Trainer"),
          Field("--channel", "Channel", "choice", default="11", choices=CHANNELS)),
         fixed=("--live", "--phy", "auto"), doc="frlg_link.md"),
    Tool("frlg-trade-join", "Trade (console hosts)", "bin/frlg_trade_join.py",
         "Join a trade group the console leads.",
         ("Start the joiner first: it scans until the console appears.",
          f"{FRLG_PATH}, Become Leader.",
          "Accept PkCamp when it appears, then choose and confirm."),
         (_party(),
          Field("--out", "Save received Pokemon to", "save", default="received/frlg-{stamp}.pk3")),
         fixed=("--live", "--phy", "auto"), doc="frlg_link.md"),
    Tool("frlg-gift", "Mystery Gift", "bin/frlg_mg_host.py",
         "Send a Wonder Card or Wonder News. Collect the gift from the delivery man in any Pokemon Center.",
         ("Title screen: Mystery Gift, Wonder Cards, Friend. For news: the second entry, Wonder News.",
          "Start the host, then pick PkCamp when it appears.",
          "Answer Yes if the console asks to replace its card.",
          "Back out of the search screen between two runs."),
         (Field("--news", "Send", "choice", choices=(
             ("", "A Wonder Card"), ("pkcamp", "Wonder News: one berry in Cerulean City"),
             ("berry", "Wonder News: ten lines, one berry"))),
          Field("--gift", "Wonder Card", "choice", default="beast-cutscene", when=CARD, choices=(
             ("beast-cutscene", "Legendary beast (follows the starter)"),
             ("celebi", "Celebi"), ("master-ball", "Master Ball"),
             ("altering-cave", "Altering Cave"), ("porygon-tm-gift", "Porygon TM gift"),
             ("solrock-stamp", "Sun and Moon Rally: Solrock stamp"),
             ("lunatone-stamp", "Sun and Moon Rally: Lunatone stamp"),
             ("visiting-trainer", "Visiting trainer"), ("battle-count-card", "Battle count card"),
             ("worlds-xp", "Worlds XP"))),
          Field("--flag-id", "Card flag id", "number", when=CARD,
                help="1000 to 1019. A console refuses the id of the card it already holds; "
                     "alternate between two. Empty uses the gift's own."),
          Field(("--version", "--expect-console"), "Version", "choice", default="firered",
                choices=VERSIONS, group="Console"),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, group="Console"),
          Field("--channel", "Channel", "choice", default="11", choices=CHANNELS)),
         fixed=("--live",), doc="frlg_gift.md"),
    Tool("frlg-code", "Console code", "bin/frlg_mg_host.py",
         "Run native code on the console through Mystery Gift: read the save, or install a per-frame hook.",
         ("Title screen: Mystery Gift, Wonder Cards, Friend.",
          "Start the host, then pick PkCamp when it appears.",
          "Keep the host running until the log shows the result; a dump is written a few seconds later."),
         (Field("--buffer-script", "Action", "choice", default="save-dump", choices=(
             ("trainer-id-probe", "Read the trainer id (reads only)"),
             ("save-dump", "Read part of the save (reads only)"),
             ("install-resident", "Install a hook until the next reset (writes RAM)"))),
          Field("--dump-block", "Save block", "choice", default="sav2", group="Save dump",
                choices=(("sav2", "Trainer (sav2)"), ("sav1", "Party, bag, flags (sav1)")),
                when=SAVE_DUMP),
          Field("--dump-size", "Bytes", "number", default="64", group="Save dump", when=SAVE_DUMP),
          Field("--dump-file", "Write the dump to", "save", default="received/frlg-dump-{stamp}.bin",
                when=SAVE_DUMP),
          Field("--resident", "Hook", "choice", default="turbo", when=HOOK, choices=(
              ("turbo", "Turbo"), ("shiny", "Shiny encounters"), ("ivs", "IVs on screen"),
              ("noencounter", "No wild encounters"))),
          Field("--write-unsafe", "Allow writes", "switch", default=False, when=HOOK,
                help="Required to install a hook. It changes the running game; a soft reset undoes it."),
          Field(("--version", "--expect-console"), "Version", "choice", default="firered",
                choices=VERSIONS, group="Console"),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, group="Console")),
         fixed=("--live",), doc="frlg_rom.md",
         warning="Writes act on the real game. Read docs: Code on the console first."),
))

LGPE_STEPS = "X, Communicate, Local Communication, Trade, enter the same link code, then search."

LGPE = Game("lgpe", "Let's Go Pikachu & Eevee", "LGPE", "lgpe.md", (
    Tool("lgpe-host", "Trade", "bin/lgpe_host.py",
         "Host a trade under a link code; the console joins.",
         ("Start the host first.", LGPE_STEPS, "Choose a Pokemon and confirm."),
         (Field("--offer", "Pokemon to offer", "file", required=True, exts=("pb7", "bin"),
                help="A 232-byte PB7 box structure, or 'echo' to return the console's own."),
          Field("--code", "Link code", default="pikachu,pikachu,pikachu",
                help="Three picker names or indices 0 to 9, comma-separated."),
          FRESH_PID,
          Field("--our-trainer", "Trainer TID:SID", default="41234:12345", group="Trainer"),
          Field("--player-name", "Name", default="PkCamp", group="Trainer"),
          Field("--seconds", "Seconds", "number", default="600")),
         fixed=("--first", "echo"), doc="lgpe.md"),
    Tool("lgpe-join", "Trade (console hosts)", "bin/lgpe_join.py",
         "Join the console's trade search.",
         ("Start the joiner: it scans for up to five minutes.", LGPE_STEPS,
          "Offer and confirm once PkCamp shows."),
         (Field("--reliable-payload", "Identity message", "file", required=True,
                default="scratchpad/lgpe_joiner_first_named.bin",
                help="A captured kind-1 identity message (docs: Let's Go)."),
          Field("--offer", "Pokemon to offer", "file", required=True, exts=("pb7", "bin")),
          FRESH_PID,
          Field("--our-trainer", "Trainer TID:SID", default="41234:12345")),
         fixed=("--channels", "1,6,11", "--dwell", "2.5", "--connect", "--connect-seconds", "900",
                "--ack-peer-clock", "--ack-re-announce"), doc="lgpe_session.md"),
))

SWSH_SEARCH = "Y-Comm, Link Trade, local communication; wait on the search screen."

SWSH = Game("swsh", "Sword & Shield", "SwSh", "swsh.md", (
    Tool("swsh-join", "Trade", "bin/swsh_connect.py",
         "Join the console's Link Trade search and trade from a party snapshot.",
         (SWSH_SEARCH, "Start the joiner.", "Choose and confirm on the trade screen.",
          "After a stopped run the console needs a fresh search."),
         (Field("--send-snapshot", "Party snapshot", "file", required=True,
                default="scratchpad/swsh_snapshot.bin", help="Made by Capture snapshot, then Extract snapshot."),
          Field("--offer-slot", "Offered slot", "number", default="1", help="1 to 6."),
          Field("--offer-file", "Pokemon to offer", "file", exts=("pk8",),
                help="A .pk8 placed in the offered slot. Empty offers the snapshot's own."),
          Field("--save-offered", "Save received Pokemon to", "save", default="received/swsh-{stamp}.pk8")),
         fixed=("--preset", "trade"), doc="swsh_trade.md"),
    Tool("swsh-host", "Trade (pokeldn hosts)", "bin/swsh_host.py",
         "Host a Link Trade the console joins.",
         ("Start the host first.",
          "Y-Comm, Link Trade, trade; press A on both messages, then wait in the overworld.",
          "Offer and confirm on the trade screen."),
         (Field("--advert", "Advertisement", "file", required=True, default="scratchpad/swsh_net_facts.json",
                help="Made by Record advertisement."),
          Field("--snapshot", "Party snapshot", "file", required=True, default="scratchpad/swsh_snapshot.bin"),
          Field("--offer-slot", "Offered slot", "number", default="1"),
          Field("--code", "Link Code", help="Eight digits. Empty for none."),
          Field("--received", "Save received Pokemon to", "save", default="received/swsh-{stamp}.pk8")),
         fixed=("--scene-id", "60001", "--channel", "6", "--seconds", "900"), doc="swsh_trade.md"),
    Tool("swsh-gift", "Mystery Gift", "bin/swsh_gift_host.py",
         "Advertise a Wonder Card. Nothing joins; the console reads it off the air.",
         ("Mystery Gift, Receive a Gift, via local wireless.",
          "Start the host: the card is listed within a few seconds or not at all.",
          "Accept the card, then stop the host."),
         (Field("--species", "Species", "number", default="25", group="Pokemon"),
          Field("--level", "Level", "number", default="25", group="Pokemon", help="0 lets the game roll one."),
          Field("--move1", "Move 1", "number", default="84", group="Moves"),
          Field("--move2", "Move 2", "number", default="45", group="Moves"),
          Field("--move3", "Move 3", "number", default="86", group="Moves"),
          Field("--move4", "Move 4", "number", default="98", group="Moves"),
          Field("--nickname", "Nickname", default="PKCAMP", group="Names"),
          Field("--ot", "OT", default="POKELDN", group="Names"),
          Field("--set", "Other fields", "multi",
                help="Space-separated NAME=VALUE: shiny_type=3 ball=1 held_item=236 nature=10 iv_hp=31."),
          Field("--card-id", "Card id", "number", default="9999",
                help="Change it when the console already holds this card."),
          Field("--record", "Or send a .wc8 file", "file", exts=("wc8",)),
          Field("--no-validate", "Check with the game's validator", "switch", default=True, invert=True,
                help="Runs the record through Sword's own check. Needs the game image below."),
          Field("--image", "Game image (main.bin)", "file", default="scratchpad/swsh/main.bin",
                when=("--no-validate", "True")),
          Field("--seconds", "Seconds", "number", default="300")),
         doc="swsh_gift.md",
         warning="Item ids above 1607 crash the bag screen; the host rejects them."),
    Tool("swsh-capture", "Capture snapshot", "bin/swsh_connect.py",
         "Record the console's party snapshot once. Sends nothing.",
         (SWSH_SEARCH, "Start the capture and wait for it to end.", "Then run Extract snapshot."),
         (Field("--capture", "Write the capture to", "save", default="scratchpad/swsh_first.jsonl"),),
         fixed=("--preset", "capture"), doc="swsh_trade.md", setup=True),
    Tool("swsh-extract", "Extract snapshot", "tools/switch/swsh_snapshot.py",
         "Pull the 3456-byte party snapshot out of a capture. No board needed.",
         ("Run it after Capture snapshot.",),
         (Field("", "Capture", "file", required=True, default="scratchpad/swsh_first.jsonl"),
          Field("", "Write the snapshot to", "save", default="scratchpad/swsh_snapshot.bin")),
         radio=False, setup=True),
    Tool("swsh-advert", "Record advertisement", "bin/swsh_join.py",
         "Save a searching Sword's advertisement, which the host needs.",
         (SWSH_SEARCH, "Start it; it stops once it has scanned."),
         (Field("--facts", "Write it to", "save", default="scratchpad/swsh_net_facts.json"),),
         fixed=("--scan-only",), setup=True),
))

BDSP_ROOM = "Pokemon Center 2F, left attendant, plain Yes (no password, not the group option)."

BDSP = Game("bdsp", "Brilliant Diamond & Shining Pearl", "BDSP", "bdsp.md", (
    Tool("bdsp-join", "Trade", "bin/bdsp_connect.py",
         "Join the console's Union Room as a character and trade.",
         (f"{BDSP_ROOM} Wait in the room, clear of the walls.",
          "Start the joiner. Wait for the character to appear and finish walking.",
          "Y, Communicate, Trade Pokemon, and wait: the greeting comes up on its own.",
          "Between runs, leave and re-enter the room."),
         (Field("--trade-template", "Pokemon to offer", "file", required=True, exts=("pb8",),
                help="A legal PB8. An illegal one crashes the game where it draws the offer."),
          Field("--trade-nickname", "Nickname", default="PKCAMP"),
          FRESH_PID,
          Field("--hold", "Seconds", "number", default="600")),
         fixed=("--channels", "1,6,11", "--count", "9", "--connect", "5", "--join", "6",
                "--reliable-ack", "--reliable-sweep", "3", "--room-walk", "15", "--room-pattern", "fixed",
                "--room-walk-steps", "8", "--join-avatar", "0", "--answer-requests", "--state", "0",
                "--recruiting", "0", "--answer-talk", "--can-talk", "0", "--initiate-talk",
                "--initiate-delay", "3", "--after-approach", "0x06:0001000000", "--trade-reply",
                "--complete-trade", "--src-var", "{src_var}"),
         doc="bdsp_trade.md"),
    Tool("bdsp-host", "Trade (pokeldn hosts)", "bin/bdsp_host.py",
         "Host a Union Room the console enters.",
         ("Start the host before the player enters the room.",
          f"{BDSP_ROOM} Our character appears.",
          "Y, Communicate, Trade Pokemon; accept the greeting, then choose and confirm."),
         (Field("--offer", "Pokemon to offer", "file", required=True, exts=("pb8",),
                help="A legal PB8 whose PID the save does not hold."),
          FRESH_PID,
          Field("--password", "Room password", help="Eight digits. Empty for the plain room."),
          Field("--seconds", "Seconds", "number", default="1500")),
         fixed=("--ldn-protocol", "1", "--complete-trade"), doc="bdsp_trade.md"),
))

PLA_STEPS = ("Talk to the trade NPC in Jubilife Village: trade, local, past the warning.",
             "Enter the same eight-digit code and press + to search.")

PLA = Game("pla", "Legends Arceus", "PLA", "pla.md", (
    Tool("pla-host", "Trade", "bin/pla_host.py",
         "Host a trade under a link code; the console joins.",
         ("Start the host first.", *PLA_STEPS, "Offer a Pokemon and confirm."),
         (Field("--code", "Link code", default="00000000"),
          Field("--trade-box-record", "Pokemon to offer", "file", exts=("pa8", "bin"),
                help="Empty offers the reference Azelf."),
          Field("--trade-box-collect", "Save what the console shows to", "dir", default="received/pla"),
          Field("--seconds", "Seconds", "number", default="300")),
         fixed=("--channel", "6", "--session-update", "--sustain", "--clock", "--data-exchange",
                "--game-channel", "--trade-box"), doc="pla.md",
         warning="A failed commit locks trading for a while (docs: Legends Arceus, The trade restriction)."),
    Tool("pla-join", "Trade (console hosts)", "bin/pla_join.py",
         "Join the console's search. It hands pokeldn the host role, which the joiner takes on its own.",
         (*PLA_STEPS, "Start the joiner.", "Offer and confirm once the partner shows."),
         (Field("--code", "Link code", default="00000000"),
          Field("--offer", "Pokemon to offer", "file", exts=("pa8", "bin")),
          Field("--offer-out", "Save received Pokemon to", "save", default="received/pla-{stamp}.pa8"),
          FRESH_PID), doc="pla.md"),
))

SV_SEARCH = "X, Poke Portal, Link Trade, offline, then search."

SV = Game("sv", "Scarlet & Violet", "SV", "sv.md", (
    Tool("sv-join", "Trade", "bin/sv_join.py",
         "Join the console's Link Trade search with a composed record.",
         (SV_SEARCH, "Start the joiner.", "Offer and confirm on the trade screen.",
          "If the console keeps refusing, leave and re-enter the search screen."),
         (Field("--trade-offer", "Pokemon to offer", "file", required=True,
                default="scratchpad/sv_join_offer.hex", exts=("hex", "bin")),
          Field("--code", "Link Code", help="Empty joins a search with no code."),
          Field("--record-set", "Record set", "dir", required=True, default="scratchpad/sv_joiner_records"),
          Field("", "Identity arguments", "argsfile", required=True, default="scratchpad/sv_identity_open.txt"),
          Field("--offer-out", "Save the console's offer to", "save", default="received/sv-{stamp}.hex")),
         fixed=("--phy", "auto", "--seconds", "1500", "--hold", "900", "--channels", "1,6,11",
                "--dwell", "0.4", "--connect-timeout", "6", "--open-delay", "0.3", "--record-delay", "0.3",
                "--session-join", "--answer-migration", "--net-ack", "--ack-flags", "0x00",
                "--game-channel", "--announce-timeout", "20", "--rtt-delay", "0.3"), doc="sv.md"),
    Tool("sv-host", "Trade (pokeldn hosts)", "bin/sv_host.py",
         "Host a trade the searching console joins.",
         ("Start the host first.", SV_SEARCH, "Offer and confirm on the trade screen."),
         (Field("--trade-offer", "Pokemon to offer", "file", required=True,
                default="scratchpad/sv_join_offer.hex", exts=("hex", "bin")),
          Field("--code", "Link Code", help="Empty hosts a search with no code.",
                unset=("--game-data",
                       "000000000000000000000000000000000000000000000000000000000000000000648cf400000000")),
          Field("--record-set", "Record set", "dir", required=True, default="scratchpad/sv_host_records"),
          Field("", "Identity arguments", "argsfile", required=True, default="scratchpad/sv_identity_open.txt"),
          Field("--offer-out", "Save the console's offer to", "save", default="received/sv-{stamp}.hex")),
         fixed=("--channel", "6", "--seconds", "900", "--host-player-id", "00000000000000010000000000000000",
                "--player-name", "RyuPlayer", "--rtt-probe", "--net-property", "--clock", "--net-stations", "4",
                "--scarlet-response", "--join-seq", "0", "--update-first-seq", "0", "--update-seq", "1",
                "--session-flags", "0x00", "--no-session-ack", "--update-delay", "2.03",
                "--host-player-name", " ", "--record-delay", "0.17",
                "--send-at", "0.06:0x7c:1:b90104b902b9027b0001b902b902320201b902b902320101b902b902320301",
                "--send-at", "0.06:0x81:1:0000000000f38800000000",
                "--send-at", "0.04:0x81:5:000500000ff00800000000",
                "--announce", "--announce-delay", "5.25",
                "--send-at", "6.00:0x7c:1:b90101b902b90280800001", "--offer-after-open", "2"),
         doc="sv.md"),
))

ZA_REFS = ("scratchpad/za_ref_identity10.bin", "scratchpad/za_ref_identity11b.bin",
           "scratchpad/za_ref_selection.bin")

ZA = Game("za", "Legends Z-A", "PLZA", "za.md", (
    Tool("za-join", "Trade", "bin/za_join.py",
         "Join the console's Link Trade search.",
         ("Link Trade, local communication, search with the link code.",
          "Start the joiner. Refusals while seating are normal; let it run.",
          "Pick on the trade box and confirm once PKLDN appears."),
         (Field("--trade-offer", "Pokemon to offer", "file", required=True, exts=("bin",),
                help="The 354-byte offer message (docs: Legends Z-A)."),
          Field("--code", "Link code", default="00000000"),
          FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "0.35", "--seconds", "900", "--hold", "450",
                "--quiet-seat", "25", "--connect-timeout", "6", "--mac", "02:11:32:54:76:98", "--game",
                "--offer-delay", "4"),
         needs=ZA_REFS, doc="za.md"),
    Tool("za-host", "Trade (pokeldn hosts)", "bin/za_host.py",
         "Host a trade the searching console joins.",
         ("Start the host first.",
          "X, Link Play, Link Trade, Nearby Players, the same code, then search.",
          "Pick on the trade box, offer, then trade."),
         (Field("--trade-offer", "Pokemon to offer", "file", required=True, exts=("bin",)),
          Field("--code", "Link code", default="00000000"),
          FRESH_PID,
          Field("--offer-out", "Save the console's offer to", "save", default="received/za-{stamp}.hex"),
          Field("--seconds", "Seconds", "number", default="900")),
         needs=ZA_REFS, doc="za.md"),
))

GAMES = (FRLG, LGPE, SWSH, BDSP, PLA, SV, ZA)

"""What the app offers per game: each tool is an entry point, the tested flags it always gets, the
fields a user fills in, and what to press on the console. Fixed arguments may carry {received}
(the Received folder), {stamp} (the run's time) and {src_var} (a fresh random id)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    flag: str | tuple[str, ...]   # "" is positional; a tuple passes the same value to each flag
    label: str
    kind: str = "text"            # text number choice switch pokemon rewards file builder multi linkcode,
                                  # raidseed, or a PKHeX
                                  # name list: species move item ball
    help: str = ""
    default: str | bool = ""
    choices: tuple[tuple[str, str], ...] = ()
    required: bool = False
    group: str = ""               # fields sharing a group render on one card
    invert: bool = False          # a switch that passes its flag when turned off
    unset: tuple[str, ...] = ()   # arguments passed when the field is left empty
    exts: tuple[str, ...] = ()
    when: tuple[str, str] = ()    # (flag, value): the field applies only while that field has that value
    unless: str = ""             # hide and omit the field while this source field has a value
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


FRLG_PATH = "Pokemon Center 2F, third attendant, Direct Corner, Trade Center"

FRLG = Game("frlg", "FireRed & LeafGreen", "FRLG", "frlg.md", (
    Tool("frlg-trade-host", "Trade (Host)", "bin/frlg_trade_host.py",
         "Host a Direct Corner trade. The console joins pokeldn's group.",
         ("Start the host and wait for 'Hosting Direct Corner' in the log.",
          f"{FRLG_PATH}, Join Group, then pick POKELDN.",
          "Choose the Pokemon to trade and confirm.",
          "With several queued, trade again after each save; the host offers the next one.",
          "Back on the trade menu after the last save, wait for the host's prompt, then Cancel and Yes."),
         (queued(count="--trades"),
          Field("--version", "Version", "choice", default="firered", choices=VERSIONS, group="Console",
                help="The game pokeldn's own trainer reports on the link, and the one the Pokemon is built for."),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, hidden=True,
                help="The language pokeldn's own trainer reports on the link."),
          Field("--channel", "Channel", "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live", "--phy", "auto", "--slot", "0", "--ot", "{ot}", "--id", "{tid}:{sid}",
                "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-trade-join", "Trade (Join)", "bin/frlg_trade_join.py",
         "Join a trade group the console leads.",
         ("Start the joiner first: it scans until the console appears.",
          f"{FRLG_PATH}, Become Leader.",
          "Accept POKELDN when it appears, then choose and confirm.",
          "With several queued, trade again after each save; the joiner offers the next one."),
         (queued(count="--trades"),),
         fixed=("--live", "--phy", "auto", "--slot", "0", "--ot", "{ot}", "--id", "{tid}:{sid}",
                "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-gift", "Mystery Gift", "bin/frlg_mg_host.py",
         "Send a Wonder Card, Wonder News or console code: pick a preset or build your own.",
         ("Title screen: Mystery Gift, Wonder Cards, Friend. For news: the second entry, Wonder News.",
          "Start the host, then pick POKELDN when it appears.",
          "Answer Yes if the console asks to replace its card.",
          "Console code: keep the host running until the log shows the result.",
          "Back out of the search screen between two runs."),
         (Field("--gift-file", "Gift", "builder"),
          Field(("--version", "--expect-console"), "Version", "choice", default="firered",
                choices=VERSIONS, group="Console",
                help="The console's cartridge: another one is refused before anything is sent."),
          Field("--language", "Language", "choice", default="english", choices=LANGUAGES, hidden=True,
                help="The language pokeldn's own trainer reports on the link."),
          Field("--channel", "Channel", "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live", "--ot", "{ot}", "--id", "{tid}:{sid}", "--dump-file",
                "{received}/frlg-dump-{stamp}.bin"), doc="frlg_gift.md"),
))

LGPE_STEPS = "X, Communicate, Local Communication, Trade, enter the same link code, then search."

LGPE = Game("lgpe", "Let's Go Pikachu & Eevee", "LGPE", "lgpe.md", (
    Tool("lgpe-host", "Trade (Host)", "bin/lgpe_host.py",
         "Host a trade under a link code; the console joins.",
         ("Start the host first.", LGPE_STEPS, "Choose a Pokemon and confirm."),
         (queued("--offer", more="--next-offer"),
          Field("--code", "Link code", "linkcode", required=True,
                help="The three Pokemon the player picks on the console, in the same order."),
          FRESH_PID,
          host_seconds("1200", "A trade under way when it runs out is finished first.")),
         fixed=("--first", "echo", "--trainer-name", "{ot}", "--our-trainer", "{tid}:{sid}",
                "--received", "{received}/lgpe-{stamp}.pb7"), doc="lgpe.md"),
    Tool("lgpe-join", "Trade (Join)", "bin/lgpe_join.py",
         "Join the console's trade search.",
         ("Start the joiner: it scans for up to five minutes.", LGPE_STEPS,
          "Offer and confirm once POKELDN shows. Queued Pokemon follow, one per trade."),
         (queued("--offer"), FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "2.5", "--connect", "--connect-seconds", "1800",
                "--ack-peer-clock", "--ack-re-announce", "--facts", "lgpe_net_facts.json",
                "--trainer-name", "{ot}", "--our-trainer", "{tid}:{sid}",
                "--received", "{received}/lgpe-{stamp}.pb7"),
         doc="lgpe_session.md"),
))

SWSH = Game("swsh", "Sword & Shield", "SwSh", "swsh.md", (
    Tool("swsh-host", "Trade (Host)", "bin/swsh_host.py", "Host a Link Trade the console joins.",
         ("Start the host and wait for the network to come up.",
          "Y-Comm, Link Trade, local communication; press A on both messages, then wait in the overworld.",
          "Choose a Pokemon and confirm when POKELDN appears.",
          "Queued Pokemon follow, one per trade: pick again from the box."),
         (queued("--offer-file"), FRESH_PID,
          Field("--code", "Link Code", help="Eight digits. Empty for a plain trade."),
          Field("--channel", "Channel", "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("900")),
         fixed=("--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}",
                "--received", "{received}/swsh-{stamp}.pk8"), doc="swsh_trade.md"),
    Tool("swsh-join", "Trade (Join)", "bin/swsh_connect.py", "Join the console's Link Trade search.",
         ("Y-Comm, Link Trade, local communication, no code; press A on both messages.",
          "Start the joiner while the console searches.",
          "POKELDN appears on the trade screen: choose a Pokemon and confirm.",
          "Queued Pokemon follow, one per trade: pick again from the box."),
         (queued("--offer-file", required=False,
                 help="Pick a species; PKHeX builds a legal one. Empty offers your own first party "
                      "Pokemon back, renamed POKELDN."),
          FRESH_PID,
          join_seconds("900")),
         fixed=("--preset", "trade", "--send-snapshot", "live",
                "--snapshot-name", "{ot}", "--snapshot-tid", "{tid}", "--snapshot-sid", "{sid}",
                "--save-offered", "{received}/swsh-{stamp}.pk8"),
         doc="swsh_trade.md"),
    Tool("swsh-gift", "Mystery Gift", "bin/swsh_gift_host.py",
         "Advertise a Wonder Card: pick a preset or build your own. The console reads it off the air.",
         ("Mystery Gift, Receive a Gift, via local wireless.",
          "Start the host: the card is listed within a few seconds or not at all.",
          "Accept the card, then stop the host."),
         (Field("--gift-file", "Gift", "builder"),
          Field("--seconds", "Time limit (seconds)", "number", default="300", hidden=True,
                help="How long the card is advertised after Start.")),
         doc="swsh_gift.md"),
))

BDSP_ROOM = "Pokemon Center 2F, left attendant, plain Yes (no password, not the group option)."

BDSP = Game("bdsp", "Brilliant Diamond & Shining Pearl", "BDSP", "bdsp.md", (
    Tool("bdsp-host", "Trade (Host)", "bin/bdsp_host.py",
         "Host a Union Room the console enters.",
         ("Start the host before the player enters the room.",
          f"{BDSP_ROOM} Our character appears.",
          "Y, Communicate, Trade Pokemon; accept the greeting, then choose and confirm."),
         (queued("--offer"),
          FRESH_PID,
          Field("--password", "Room password", help="Eight digits. Empty for the plain room."),
          host_seconds("1500")),
         fixed=("--ldn-protocol", "1", "--complete-trade", "--save-theirs", "{received}/bdsp-{stamp}",
                "--language", "{language}", "--name", "{ot}", "--trainer", "{ot}:{tid}:{sid}"),
         doc="bdsp_trade.md"),
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
                "--trade-save-poke", "{received}/bdsp-{stamp}.pb8", "--language", "{language}",
                "--name", "{ot}", "--trade-name", "{ot}", "--trade-tid", "{tid}", "--trade-sid", "{sid}"),
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
                "--game-channel", "--trade-box", "--player-name", "{ot}",
                "--offer-out", "{received}/pla-{stamp}.pa8"),
         doc="pla.md"),
    Tool("pla-join", "Trade (Join)", "bin/pla_join.py",
         "Join the console's search. It hands pokeldn the host role, which the joiner takes on its own.",
         (*PLA_STEPS, "Start the joiner.", "Offer and confirm once the partner shows."),
         (queued("--offer", required=False, help=PLA_OFFER_HELP),
          Field("--code", "Link code", default="00000000", help=CODE_HELP),
          FRESH_PID),
         fixed=("--player-name", "{ot}", "--offer-out", "{received}/pla-{stamp}.pa8"),
         doc="pla.md"),
))

SV_SEARCH = "X, Poke Portal, Link Trade, offline, then search."

SV = Game("sv", "Scarlet & Violet", "SV", "sv.md", (
    Tool("sv-host", "Trade (Host)", "bin/sv_host.py",
         "Host a trade the searching console joins.",
         ("Start the host first.", SV_SEARCH, "Offer and confirm on the trade screen."),
         (queued("--trade-offer"),
          Field("--code", "Link Code", help="Empty hosts a search with no code.",
                unset=("--game-data",
                       "000000000000000000000000000000000000000000000000000000000000000000648cf400000000")),
          FRESH_PID),
         fixed=("--channel", "6", "--seconds", "900", "--host-player-id", "00000000000000010000000000000000",
                "--player-name", "POKELDN", "--rtt-probe", "--net-property", "--clock", "--net-stations", "4",
                "--scarlet-response", "--join-seq", "0", "--update-first-seq", "0", "--update-seq", "1",
                "--session-flags", "0x00", "--no-session-ack", "--update-delay", "2.03",
                "--host-player-name", " ", "--record-delay", "0.17",
                "--send-at", "0.06:0x7c:1:b90104b902b9027b0001b902b902320201b902b902320101b902b902320301",
                "--send-at", "0.06:0x81:1:0000000000f38800000000",
                "--send-at", "0.04:0x81:5:000500000ff00800000000",
                "--announce", "--announce-delay", "5.25",
                "--send-at", "6.00:0x7c:1:b90101b902b90280800001", "--offer-after-open", "2",
                "--trainer-name", "{ot}", "--offer-out", "{received}/sv-{stamp}.pk9"),
         doc="sv.md"),
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
                "--trainer-name", "{ot}", "--offer-out", "{received}/sv-{stamp}.pk9"), doc="sv.md"),
    Tool("sv-raid-host", "Tera Raid (Host)", "bin/sv_raid_host.py",
         "Host a generated Tera Raid with a custom battler and optional exact rewards.",
         ("Choose the Pokemon POKELDN should bring; it becomes a bot after POKELDN disconnects.",
          "Choose a raid Pokemon from its seed and stats. Pick one your team can defeat.",
          "Optionally replace the seed rewards with the exact rewards you want.",
          "Start the session in pokeldn.",
          "On the console, open the Poké Portal and join an offline Tera Raid Battle.",
          "Enter the Link Code 4970.",
          "A communication warning may appear while entering the raid. This is expected; dismiss it and continue.",
          "Defeat the raid Pokemon to receive the configured rewards. Catching it is optional."),
         (Field("--raid-player-pokemon", "POKELDN's Pokemon", "pokemon", required=True,
                help="Pick a species; PKHeX builds a legal Pokemon for POKELDN to use in the "
                     "fully generated raid."),
          Field("--raid-version", "Game", "choice", default="violet",
                choices=(("scarlet", "Scarlet"), ("violet", "Violet")), group="Raid context",
                help="Some seeds select a different encounter between versions."),
          Field("--raid-map", "Region", "choice", default="paldea",
                choices=(("paldea", "Paldea"), ("kitakami", "Kitakami"),
                         ("blueberry", "Blueberry")), group="Raid context",
                help="Use the encounter table for this region."),
          Field("--raid-progress", "Story progress", "choice", default="4star",
                choices=(("beginning", "Beginning"), ("tera", "Tera unlocked"),
                         ("3star", "3-star unlocked"), ("4star", "4-star unlocked"),
                         ("5star", "5-star unlocked"), ("6star", "6-star unlocked")),
                group="Raid context", help="Controls the standard raid star distribution; "
                                             "black raids are always six-star."),
          Field("--raid-content", "Raid type", "choice", default="standard",
                choices=(("standard", "Standard"), ("black", "Black crystal")),
                group="Raid context", help="Black-crystal tables generate six-star raids."),
          Field("--raid-seed", "Raid Pokemon seed", "raidseed", default="000F34C3", required=True,
                help="Eight hexadecimal digits. The seed determines the boss species, Tera type, "
                     "stats, ability, and moves."),
          Field("--reward", "Raid rewards", "rewards",
                help="Optionally replace the seed rewards with 1 to 16 rows in display order. "
                     "Duplicate items are allowed."),
          host_seconds("600")),
         fixed=("--generated-bootstrap",),
         doc="sv_raid.md"),
    Tool("sv-raid-join", "Tera Raid (Join)", "bin/sv_join.py",
         "Join a retail-hosted Tera Raid with a legal custom Pokemon, then leave it as a bot.",
         ("On the console, open an offline Tera Raid lobby and choose Challenge as a group.",
          "Choose the Pokemon POKELDN should bring to the raid.",
          "Start the joiner while the host is waiting for participants.",
          "Confirm POKELDN appears and becomes ready, then choose Start Raid Battle.",
          "POKELDN disconnects at the battle transition; its Pokemon remains as a bot."),
         (Field("--raid-pokemon", "Raid Pokemon", "pokemon",
                required=True,
                help="Pick a species; PKHeX builds the legal Pokemon placed in the generated "
                     "raid lobby record."),
          join_seconds("240")),
         fixed=("--scene-id", "7", "--raid-guest", "--raid-guest-ready-delay", "2",
                "--seconds", "900", "--max-seats", "1", "--name", "POKELDN",
                "--trainer-name", "POKELDN", "--join-player-name", "POKELDN"),
         doc="sv_raid_guest.md"),
))

ZA = Game("za", "Legends Z-A", "PLZA", "za.md", (
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
         fixed=("--trainer-name", "{ot}", "--offer-out", "{received}/za-{stamp}.pa9"), doc="za.md"),
    Tool("za-join", "Trade (Join)", "bin/za_join.py",
         "Join the console's Link Trade search.",
         ("Link Trade, local communication, search with the link code.",
          "Start the joiner. Refusals while seating are normal; let it run.",
          "Pick on the trade box and confirm once POKELDN appears. Queued Pokemon follow, one per trade."),
         (queued("--trade-offer"),
          Field("--code", "Link code", default="00000000", help=CODE_HELP),
          FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "0.35", "--seconds", "1200", "--hold", "900",
                "--quiet-seat", "25", "--connect-timeout", "6", "--mac", "02:11:32:54:76:98", "--game",
                "--offer-delay", "4", "--trainer-name", "{ot}", "--offer-out", "{received}/za-{stamp}.pa9"),
         doc="za.md"),
))

GAMES = (FRLG, LGPE, SWSH, BDSP, PLA, SV, ZA)

<p align="center">
  <img src=".github/assets/banner.png" alt="pokeldn: ESP32-powered local wireless toolkit for Pokémon on Nintendo Switch" width="100%">
</p>

<p align="center">
  <a href="https://discord.gg/PyvaVYnpXC"><img alt="Discord" src="https://img.shields.io/badge/discord-join-5865F2?style=flat-square&logo=discord&logoColor=white"></a>
  <a href="https://decryptu.github.io/pokeldn/"><img alt="Documentation" src="https://img.shields.io/badge/docs-decryptu.github.io%2Fpokeldn-3fa9f5?style=flat-square&logo=readthedocs&logoColor=white"></a>
  <img alt="Python 3.13" src="https://img.shields.io/badge/python-3.13-3fa9f5?style=flat-square&logo=python&logoColor=white">
</p>

# pokeldn

An ESP32 board on USB serial is the radio: pokeldn hosts or joins Nintendo Switch local wireless
(LDN) sessions with retail Pokémon games through it, from any computer that runs Python. Nothing is
installed on the Switch or Switch 2. Seven games are supported:

| | FRLG | LGPE | SwSh | BDSP | PLA | SV | PLZA |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Trade | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Online trade, two players far apart | ✓ | ○ | ○ | ○ | ○ | ✓ | ○ |
| Mystery Gift | ✓ | ∅ | ✓ | ∅ | ∅ | ∅ | ∅ |
| Link battle | ✓ | ✗ | ✗ | ✗ | ∅ | ✗ | ✗ |
| Code on the console, save read and write | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

✓ works on a retail console · ○ built and tested offline, untried on a retail console · ✗ not done ·
∅ the game has no such feature over local wireless
FRLG FireRed/LeafGreen · LGPE Let's Go Pikachu/Eevee · SwSh Sword/Shield · BDSP Brilliant Diamond/Shining Pearl · PLA Legends Arceus · SV Scarlet/Violet · PLZA Legends Z-A

FRLG supports both versions in English, French, German, Italian, Spanish and Japanese. The added
editions have offline cartridge-ROM tests; their wireless delivery still needs retail checks.

Scarlet and Violet also host and join local Tera Raids, with a chosen boss and rewards
([Tera Raids](docs/sv_raid.md)). Every game trades through the ESP32 board. Online trade joins two players far apart: each hosts
their own console, and the two apps meet through public Nostr relays under a shared code, with no
server to run ([online trade](docs/online.md)). Protocol documentation:
[decryptu.github.io/pokeldn](https://decryptu.github.io/pokeldn/).

---

## Why?

Direct local wireless communication with retail Pokémon games, and the protocols documented for work
such as an unofficial GTS or online battles. AI tools helped reverse engineer the protocols and write
parts of the code.

## Desktop app

<img src=".github/assets/desktop-app.webp" alt="The pokeldn desktop app offering a shiny Chansey for a FireRed trade" width="100%">

The [releases](https://github.com/Decryptu/pokeldn/releases) carry a desktop app for macOS (Apple
silicon), Windows and Linux. It includes the radio firmware and flashes the board, builds legal
Pokemon to offer with [PKHeX.Core](https://github.com/kwsch/PKHeX), and runs every trade and Mystery
Gift below with the tested settings. The only file it asks for is `prod.keys`. Its Bank keeps every
Pokemon a trade brings in and trades one into another game wherever HOME would move it, converted
and checked by PKHeX ([the bank](docs/gui.md#the-bank)). Its GTS lists a banked Pokemon on public
Nostr relays against a wanted species and trades it with another player's app, neither of them online
at the same time ([the GTS](docs/online.md#the-gts)). Its Control page turns an ESP32-S3 into a
wired controller for the Switch, or a classic ESP32 into a wireless Pro Controller: press its buttons from the computer, record and edit macros, and
share them as `.pokemacro` files ([the controller](docs/gui.md#the-controller)).

- macOS: the app is unsigned, so the first launch is blocked. Open it once and close the warning,
  then System Settings, Privacy & Security, scroll down to Security, Open Anyway next to pokeldn,
  and confirm with your password. Later launches open normally.
- Windows: extract the zip and run `pokeldn.exe` inside the `pokeldn` folder; keep the `_internal`
  folder beside it. SmartScreen may stop the unsigned app; choose More info, then Run anyway. A classic
  ESP32 needs its USB chip's driver (CP210x or CH340) before it gets a COM port; the Board page links
  both and names the one missing ([Windows USB drivers](docs/gui.md#windows-usb-drivers)).
- Linux: it needs GTK 3 and libsecret, present on desktop distributions, and serial access
  (`sudo usermod -aG dialout $USER`; the group is `uucp` on Arch). On Ubuntu 22.04, brltty takes
  CH340 boards and their port never appears: `sudo apt remove brltty` ([Linux serial ports](docs/gui.md#linux-serial-ports)).
- From source: `pip install -r gui/requirements.txt`, then `python gui/main.py`; the Pokemon builder
  needs `dotnet build -c Release services/pkhex` (.NET 10 SDK), and file drops need the client
  `python scripts/build_client.py` builds (Flutter). `python scripts/pack_app.py` builds the
  app for the current OS into `dist/`, with firmware and that client required. See [desktop builds](docs/gui.md).
- `python -m pokeldn --list` lists the shared GUI/CLI presets. For example,
  `python -m pokeldn --radio esp32:auto swsh-host --offer-file offer.pk8`.
  See [code organization](docs/architecture.md) for the shared modules and legality checks.

## Mystery Gift files

The FRLG and Sword/Shield Mystery Gift tools send a preset, a gift built in the app, or a shared
`.pokegift` file; FRLG also accepts `.wc3` and Sword/Shield `.wc8`. FRLG builds Wonder Cards, Wonder News and ARM
console code; Sword/Shield builds Pokemon (Gigantamax included), eggs, items, clothing, Battle
Points and money, and offers 171 official event cards, searchable by name. Save gift file exports the selected gift without a board, as a `.pokegift` or a
native `.wc3` or `.wc8`; `--export-gift FILE.wc3` does the same from the command line.

```bash
./.venv/bin/python bin/frlg_mg_host.py --gift celebi --export-gift celebi.pokegift
./.venv/bin/python bin/swsh_gift_host.py --species 25 --export-gift pikachu.pokegift
./.venv/bin/python bin/frlg_mg_host.py --buffer-script trainer-id-probe --export-gift probe.pokegift
./.venv/bin/python -m pokeldn.gifts inspect celebi.pokegift
```

Both launchers accept `--gift-file FILE`. Native conversion and the file schema are in
[Mystery Gift files](docs/gifts.md).

## Requirements

- A classic ESP32 board with a USB serial bridge, or an ESP32-S3, ESP32-C3 or ESP32-C6 through native USB
  Serial/JTAG, flashed with [`firmware/esp32`](firmware/esp32) for its chip. All use 2.4 GHz.
  Board requirements and hardware verification are on [ESP32 radio](docs/hardware_esp32.md#supported-boards).
- Optional: a 128x64 SSD1306, SSD1315 or SSD1309 I2C OLED on the board (classic ESP32: SDA D21, SCL
  D22; ESP32-S3: SDA GPIO8, SCL GPIO9; VCC 3V3), or the 72x40 screen built into the 0.42-inch
  ESP32-C3 OLED board (ABRobot and its clones), shows
  the radio's traffic, the Pokemon each trade sends and receives, and the Mystery Gift card; idle,
  it dims after a minute and turns off after ten, and BOOT wakes it
  ([The screen](docs/hardware_esp32.md#the-screen)).
- Python 3.11+ and a venv with `requirements.txt` installed. No root. The bundled
  [`vendor/LDN`](vendor/LDN) is installed by it; do not substitute the PyPI `ldn` package.
- Source trade tools also need the .NET 10 SDK and `dotnet build -c Release services/pkhex`.
  Released desktop apps include the helper.
- A Switch or Switch 2 with one of the games. FireRed / LeafGreen needs the Direct Corner unlocked
  (20 to 40 minutes of play) and at least two `.pk3` party members.
- Switch `prod.keys` (default `~/.switch/prod.keys`; `--keys PATH` elsewhere, absolute under `sudo`).

## Setup

The desktop app flashes the board from its Board page; building the firmware is optional. A copy run
from source has no image until its Board page's Download the firmware fetches the firmware images
of the latest release and checks them against its `SHA256SUMS`.

Building it yourself needs ESP-IDF v6.1, which provides `idf.py`; this repository does not ship it:

```bash
git clone -b v6.1 --recursive https://github.com/espressif/esp-idf.git ~/esp/esp-idf
~/esp/esp-idf/install.sh esp32,esp32s3,esp32c3,esp32c6
. ~/esp/esp-idf/export.sh   # puts idf.py on PATH, once per shell
cd firmware/esp32
idf.py set-target esp32   # esp32s3, esp32c3 or esp32c6 for those chips
idf.py build
idf.py -p PORT flash
cd ../..
./.venv/bin/python tools/ldn/esp32_first_contact.py --port PORT           # HELLO, counters, networks
export POKELDN_RADIO=esp32:auto
```

`PORT` is the board's serial device (`/dev/cu.usbserial-*` or `/dev/cu.usbmodem*` on macOS,
`/dev/ttyUSB*` or `/dev/ttyACM*` on Linux, `COM4` on Windows) and follows the USB socket.
`esp32:auto` takes the only USB serial port present; `esp32:PORT` names one.
An S3, C3 or C6 board with two USB sockets needs its native USB socket for radio communication.
`POKELDN_ESP32_TRACE=FILE` records every serial message and the board's counters. The exact IDF
version is on [ESP32 radio](docs/hardware_esp32.md).

A Linux Wi-Fi card (legacy, root, no `POKELDN_RADIO`) is covered on [Adapters](docs/hardware_adapters.md).

## Layout

| | |
|---|---|
| [`bin/`](bin) | entry points, named for the game: `frlg_*`, `lgpe_*`, `swsh_*`, `bdsp_*`, `pla_*`, `sv_*`, `za_*` (`_host` hosts, `_join` / `_connect` joins; `bin/X --help` lists flags) |
| [`tools/ldn/`](tools/ldn) | the radio, any target: `esp32_first_contact.py`, `esp32_sniff.py` (second board as air sniffer), `ldn_scan.py` |
| [`tools/frlg/`](tools/frlg), [`tools/switch/`](tools/switch) | offline readers: a FireRed console's dumps; a retail Switch title's own code |
| [`pokeldn/`](pokeldn) | the package: `ldn/` wireless layer, `gba/` GBA link, one package per game, `gen8.py` and `gen9.py` shared Pokémon codecs |
| [`pokeldn/app/`](pokeldn/app), [`services/pkhex/`](services/pkhex), [`gui/`](gui) | shared tool runtime; PKHeX service; desktop views |
| [`firmware/esp32/`](firmware/esp32), [`asm/`](asm) | the radio's firmware; ARM sources for the payloads the console runs |
| [`scripts/`](scripts), [`config/`](config), [`vendor/`](vendor) | setup and code generation; host profiles; bundled LDN and the mt7601u driver |
| [`docs/`](docs), [`tests/`](tests) | the protocol findings, with citations; `pip install -r requirements-dev.txt`, then `python -m pytest tests/ -q -n auto` |

Run entry points from the repo root with `POKELDN_RADIO` set, as `./.venv/bin/python -u bin/NAME.py
...`. Config files and default output paths resolve against the working directory.

## Usage

### FireRed and LeafGreen

```bash
./.venv/bin/python bin/frlg_trade_join.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3   # join the Switch's trade
./.venv/bin/python bin/frlg_trade_host.py -o output.pk3 PARTY1.pk3 PARTY2.pk3          # host a Direct Corner trade
```

The host advertises the group and leads the trade. By default it offers `PARTY2.pk3` and writes what
it receives to `output.pk3`. Defaults come from `config/host.toml`, then the ignored
`config/host.local.toml`; flags override both; `--print-effective-config` shows the result.

1. Run the host and wait for `Hosting Direct Corner`.
2. On the Switch: Direct Corner, Join Group, pick pokeldn's trainer. Wait until the host reports
   that trade selection is active.
3. Select the Pokémon to trade away and confirm.
4. The console returns to the trade menu after each trade. `--trades N` (1 to 6) offers party
   slots 0 to N-1, one per trade, on the same link. After the last trade, wait for the host prompt,
   then **CANCEL**, **YES**; the room exit and disconnect follow on their own.

| flag | purpose |
|---|---|
| `--keys PATH` | `prod.keys` location |
| `--slot N` | zero-based party member offered |
| `--capture FILE` | JSONL diagnostic capture |
| `--config` / `--local-config` / `--no-local-config` | replace or disable a config layer |
| `--ot NAME`, `--version firered\|leafgreen`, `--id TID[:SID]` | per-run trainer overrides (0..65535 each; the LinkPlayer ID is `(SID << 16) \| TID`) |
| `--verbose` | per-packet output, logged synchronously inside the frame-timed loop; use it with `--replay` only |

`DEFAULT_TRAINER` in [`pokeldn/config.py`](pokeldn/config.py) holds the defaults with no flag
(gender, language, National Dex). The link protocol is in [The link protocol](docs/frlg_link.md).

**Union Room.** `--union-room` advertises on the middle NPC's path; the console shows itself
connected after the keepalive wait, about 10 s ([The link protocol](docs/frlg_link.md)). A Union
Room link carries one trade, then the console returns to the field (`union_room.c:1744`).
`--board-type normal` registers the offered Pokémon on the trading board, `--union-room-chat` with
`--chat-message` / `--chat-file` chats, `--union-room-battle --battle-fight` battles (the console needs two non-egg Pokémon at level 30 or lower).

```bash
./.venv/bin/python bin/frlg_trade_host.py --union-room --union-room-keepalive 120 PARTY1.pk3 PARTY2.pk3
```

**Mystery Gift.** `bin/frlg_mg_host.py` advertises on the Friend path and sends a Wonder Card plus a
delivery script. On the Switch: **Mystery Gift → Wonder Cards → Friend**, then pokeldn's host; the
save must have Mystery Gift unlocked. `--make-artifact` writes a `.ram.lst` listing of the bytes sent.
The catalogue, authoring system and Friend path requirement are in [Mystery Gift](docs/frlg_gift.md).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --gift beast-cutscene --flag-id 1005 --capture mystery-gift.jsonl
```

The beast follows the save's starter (Bulbasaur Suicune, Squirtle Entei, Charmander Raikou). A shared
Stamp Rally card is `--gift solrock-stamp` and `--gift lunatone-stamp`, in either order.

**Wonder News.** `--news` serves the console's second Mystery Gift column (**Mystery Gift → Wonder
News → Friend**): 444 bytes of title and body, rewarding a berry in Cerulean City. A console keeps
news only if it differs from what it holds; `--news-id N` forces a new one.

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --news berry --news-id 7
```

**Save backup and restore.** The same Friend path copies the whole 128 KB save to a `.sav` file, or
writes a `.sav` back: beside the console's own save, every sector read back, then the game loads it
and saves; anything short of that leaves the console's save as it was. In the app, the Mystery Gift
tool's Your save tab keeps the backups, names them, imports and exports `.sav` files and edits the
trainer and party through PKHeX. A backup took about four minutes on a retail French FireRed; a
restore on a retail English FireRed loaded with CONTINUE, a French save included. [Save backup and restore](docs/frlg_gift.md#save-backup-and-restore).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-backup backup.sav --save-resume-dir partial
./.venv/bin/python -u bin/frlg_mg_host.py --live --save-restore backup.sav
```

**Console save.** A Mystery Gift session runs native ARM code on the console. `save-dump` reads the
live save back (secret ID, every party Pokémon's PID, IVs and nature); nothing is written.
`flash-patch` edits one field: it reads the save sector, changes only the named bytes, recomputes the
checksum, writes the sector back and bumps a counter so the game loads it. It edits a real save; read
[Composing a sector from a RAM snapshot](docs/frlg_rom.md#composing-a-sector-from-a-ram-snapshot) first. Payloads: [Code on the console](docs/frlg_rom.md).

```bash
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin
./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2
./.venv/bin/python -u bin/frlg_mg_host.py --buffer-script flash-patch --flash-id 0 \
  --flash-patch-offset 0x00 --flash-patch-hex cac9c5bfc6bec8ff --write-unsafe
```

### Let's Go Pikachu and Eevee

The trade screen alternates hosting and scanning, so pokeldn can host or join. Both send a kind-1
identity message: the joiner the one `pokeldn.lgpe.reference` ships, the host the console's own back
(`--first echo`) or a file. Both offer a 232-byte PB7 (`pokeldn.lgpe.pb7`; `--offer echo` returns the
console's own). The host's `--next-offer` and the joiner's repeated `--offer` queue one record per
later trade on the same seat. The joiner's `--leave-after S` backs out S seconds after it answers
the first trade step, the way a player leaves the trade screen; without it the seat stays up for
later trades.

```bash
./.venv/bin/python bin/lgpe_host.py --seconds 600 --player-name POKELDN \
  --first echo --our-trainer 41234:12345 --offer offer.pb7
./.venv/bin/python bin/lgpe_join.py --connect --connect-seconds 300 \
  --ack-peer-clock --ack-re-announce \
  --our-trainer 41234:12345 --offer offer.pb7
```

Console: Communiquer, Communication locale, Échange, link code Pikachu ×3, wait on the search
screen. For an emulated console over the LAN, use `lgpe_host.py --ip-host --our-ip IP`. See
[Let's Go](docs/lgpe.md).

### Sword and Shield

Console: Y-Comm → Link Trade → local communication, A on both messages, wait on the search screen.

```bash
# join the console's session and trade: the console's own party snapshot is sent back, rewritten
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_connect.py --keys PROD_KEYS \
  --preset trade --offer-slot 1 [--offer-file your.pk8 --offer-file next.pk8 --fresh-pid] \
  --save-offered received.pk8

# or host, and let the console join: its snapshot is taken from this trade
POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_host.py --keys PROD_KEYS \
  --offer-file your.pk8 --fresh-pid --received received.pk8 --channel 6 --seconds 900
```

The host builds its own station advertisement and rewrites the joining console's live snapshot.
When hosting, the console joins from Y-Comm → Link Trade → trade, after A on both messages that
follow; `--received FILE` saves what it sends, `--code 12345678` hosts for a Link Code search.
`--advert` and `--snapshot` still accept saved records for comparison. The host and the joiner
take a repeated `--offer-file`, one per trade on the session, as the player picks again from the box;
trade N writes what it received with `-N`. Details: [Trading](docs/swsh_trade.md).

Mystery Gift needs no session; the gift screen scans and a distributor advertises the card. Console:
Mystery Gift → receive a gift → via local wireless.

```bash
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 \
  --move1 84 --move2 45 --move3 86 --move4 98 --nickname POKELDN --ot POKELDN --seconds 300
./.venv/bin/python bin/swsh_gift_host.py --record card.wc8 --seconds 300
```

`--set FIELD=VALUE` sets any record field (`shiny_type=3`, `ball=1`, `held_item=236`, `iv_hp=31`,
`gigantamax=1`), `--ribbon N` adds a ribbon, `--dump FILE` writes the record without a radio. Item ids
are checked against the item table; an id with no row is accepted and then aborts the game when its
bag row is shown. See [Mystery Gift](docs/swsh_gift.md).

### Brilliant Diamond and Shining Pearl

pokeldn joins the console's Union Room as a character. Console: any Pokémon Center → 2F → left
attendant → plain "yes" (not the password or group option), then wait in the Union Room clear of the
walls.

```bash
./.venv/bin/python tools/ldn/ldn_scan.py --channels 1,6,11 --dwell 0.8      # see the session
./.venv/bin/python bin/bdsp_connect.py --channels 1,6,11 --count 9 --connect 5 --join 6 \
  --hold 420 --reliable-ack --reliable-sweep 3 --room-walk 15 --room-pattern fixed \
  --room-walk-steps 0 --join-avatar 0 --answer-requests --state 0 --recruiting 0 \
  --answer-talk --can-talk 0 --initiate-talk --initiate-delay 3 \
  --after-approach 0x06:0001000000 --trade-reply --complete-trade \
  --trade-template offer.pb8 --trade-nickname POKELDN --src-var 0x2B7F4C12
```

Association can fail (`Connect failed with status code 1`); retry the run before diagnosing
([Session](docs/bdsp_session.md)). `--room-pattern fixed` sends joins until the console asks for the
character's state, at most `--room-walk` (15 above). A repeated `--trade-template` queues one
Pokémon per trade in the session; the last is offered again. Use a fresh
`--src-var` every run (the console keeps ids it has seen), and after a hand-stopped run the player
leaves and re-enters the room. `--complete-trade` lets the console write its save; without it the
trade stops at the last confirmation. Once the character has appeared and finished walking: Y →
communication menu → trade Pokémon.

To host instead, start the host first, then the player enters the room the same way and raises the
trade emote (Y → communication menu → trade Pokémon):

```bash
./.venv/bin/python bin/bdsp_host.py --offer offer.pb8 --complete-trade --capture host.jsonl
```

`--offer` must be a legal PB8 whose PID the save does not hold; repeated, it queues one per trade,
the last offered again. `--password 00000000` hosts a room
entered with that password. See [Brilliant Diamond and Shining Pearl](docs/bdsp.md).

### Legends Arceus

A console hosting a trade runs it with the station that joins, or hands that station the host role
when the join lands late ([Legends Arceus](docs/pla.md)). `bin/pla_host.py` hosts and the console
joins by link code; `bin/pla_join.py` joins the console's search, trades one repeated `--offer` per
trade on the seat, and takes the host role when it is handed.

```bash
./.venv/bin/python bin/pla_host.py --code 00000000 --channel 6 --seconds 1800 \
  --session-update --sustain --clock --data-exchange --data-exchange-name POKELDN \
  --data-exchange-id 11223344 --game-channel --trade-box --trade-box-record offer.pa8 \
  --offer-out received.pa8
./.venv/bin/python bin/pla_host.py --ip-host --our-ip 172.16.86.128 --code 00000000 ...   # emulated console, no radio
```

Console: Simona at Jubilife Village → trade → someone nearby → the same eight-digit code, offer a
Pokémon and confirm. The host re-reads its record file between offers and writes the record the console
traded to `--offer-out` (`-2` and on for later trades); `--trade-box-collect DIR` keeps every record
the console shows or offers, its cursor included. A repeated `--trade-box-record` queues one record per trade in the
session, the last offered again. `pokeldn.pla.pokemon` reads, writes and `build`s a record from 376
zero bytes; `pokeldn.pla.stats` computes stats and size. See [Legends Arceus](docs/pla.md).

### Scarlet and Violet

The offline Link Trade search alternates scanning and hosting, so pokeldn hosts (`bin/sv_host.py`) or
joins (`bin/sv_join.py`).

```bash
./.venv/bin/python bin/sv_host.py --seconds 240 --player-name POKELDN \
  --rtt-probe --net-property --clock --net-stations 4 --scarlet-response \
  --record-delay 0.17 --announce --announce-delay 5.25 \
  --send-at 6.00:0x7c:1:b90101b902b90280800001 \
  --trade-offer offer.hex --offer-after-open 8
```

Console: X → Poké Portal → Link Trade → offline, no code → search. A repeated `--trade-offer`
offers one record per trade in the same seat. The wire-level requirements
(identity message order, acknowledgement `lowest_pending`) are in [Scarlet and Violet](docs/sv.md).

Both also run a local Tera Raid. `--raid-seed` hosts one the console joins (Poké Portal → Tera
Raid Battle, Link Code 4970): the seed and four context flags choose the boss, `--raid-reward
ITEM:QUANTITY` replaces its rewards, and `--raid-pokemon` is the Pokémon pokeldn's player brings.
`--raid-event FOLDER` draws the boss and rewards from a Poké Portal News delivery instead, an event
of Project Pokemon's [EventsGallery](https://github.com/projectpokemon/EventsGallery).
`bin/sv_join.py --raid-pokemon FILE` joins a raid the console hosts. In both, pokeldn's player
leaves as the battle starts and its Pokémon stays to fight beside the console's. The app's two
Tera Raid tools carry the flags; see [Tera Raids](docs/sv_raid.md).

### Legends Z-A

The Link Trade search alternates hosting and scanning, so pokeldn joins or hosts. Console: Link Trade →
local communication → search with code 00000000. The joiner rescans until it takes a seat.

```bash
# host: start it first, then search on the console
POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/za_host.py --keys prod.keys --trade-offer offer.bin --capture zh.jsonl
# join
./.venv/bin/python bin/za_join.py --channels 1,6,11 --dwell 0.35 --seconds 900 \
  --hold 450 --quiet-seat 25 --connect-timeout 6 --game --trade-offer offer.bin --offer-delay 4
```

Pick a Pokémon on the trade box and confirm when the other side's shows. Both roles answer another
offer in the same session; a repeated `--trade-offer` queues records, one per trade. Back out with
B when finished; the host closes when the console leaves.
`--offer-out FILE` keeps what the console offered. For an emulated console over the LAN, use
`za_host.py --ip-host --our-ip IP --comm-id ffffffffffffffff` and
`za_join.py --ip-join --host-ip IP --our-ip IP --comm-id ffffffffffffffff`. The offer file is 354 bytes
(nine-byte header, 344-byte record, one trailing byte); `pokeldn.gen9.build` composes the record
because Z-A's layout is Scarlet's. See [Legends Z-A](docs/za.md).

### Diagnostics

- `tools/ldn/ldn_scan.py` lists discoverable LDN networks; `esp32_sniff.py` makes a second board an
  air sniffer for one MAC on one channel.
- `POKELDN_ESP32_TRACE=FILE` records the board's serial traffic and counters; `--capture FILE` on
  every entry point writes the protocol trace as JSONL.
- [Host implementation](docs/frlg_host.md): component boundaries, protocol flow, timing, shutdown.

## Credits

pokeldn is a fork of [MercuryEnigma/frlg-ldn-trade](https://github.com/MercuryEnigma/frlg-ldn-trade)
by [MercuryEnigma](https://github.com/MercuryEnigma), itself a fork of
[tornadus/frlg-ldn-trade](https://github.com/tornadus/frlg-ldn-trade) by
[tornadus](https://github.com/tornadus), with contributions from
[trowgundam](https://github.com/trowgundam).

Contributors to this repository (GitHub does not list contributors on a fork):

- [Gr3nSkyDragon](https://github.com/Gr3nSkyDragon): ESP32-S3 firmware
- [ismailhasannnnnn](https://github.com/ismailhasannnnnn): Scarlet/Violet Tera Raid hosting and joining
- [easyworld](https://github.com/easyworld): ESP32 serial reconnects after a high-baud session

- [kinnay](https://github.com/kinnay): the [LDN library](https://github.com/kinnay/LDN) this builds on,
  and the [NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki)
- [pokefirered](https://github.com/pret/pokefirered): decompilation of FireRed/LeafGreen, including
  the Switch port
- [GB-Link Team](https://github.com/GB-Link/GB-Link-Switch-LDN): the custom FireRed/LeafGreen Wonder
  Cards in `vendor/gblink-cards/` (GPL-3.0)
- [xCyrusBR](https://github.com/xCyrusBR): [TeraLoop-Bridge](https://github.com/xCyrusBR/TeraLoop-Bridge)
  and [SV-Past-Tera-Raid](https://github.com/xCyrusBR/SV-Past-Tera-Raid), Scarlet/Violet Tera Raid
  work
- [Project Pokemon](https://github.com/projectpokemon): the [EventsGallery](https://github.com/projectpokemon/EventsGallery)
  of Scarlet/Violet raid event deliveries, with pkNX's text of each

## License

The code is licensed under AGPLv3. The license covers this repository's code and nothing else.

pokeldn is an unofficial fan project. It is not affiliated with, endorsed by or sponsored by
Nintendo, The Pokemon Company, Game Freak or Creatures. Pokemon, Nintendo Switch and the related
names and characters are trademarks of their owners. Under section 7(e) of the AGPL, no right to
use those trademarks or any other Pokemon intellectual property is granted.

The authors do not endorse using pokeldn for commercial, promotional or branded events, including
Mystery Gift distributions. Anyone who does so is responsible for obtaining the rights it requires.

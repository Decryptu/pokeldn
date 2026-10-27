---
title: Desktop builds
---
# Desktop builds

The desktop app is the pokeldn interface for macOS, Windows and Linux. A release bundles PKHeX and
radio firmware for ESP32, ESP32-S3, ESP32-C3 and ESP32-C6; the user supplies `prod.keys`.

1. Settings: choose `prod.keys`.
2. Board page: select the USB board and install the Wireless firmware. An install selects the
   chip's bundled image; an image from a file is checked against the chip. S3, C3 and C6 connect
   through native USB Serial/JTAG; S2 chips are refused.
3. Choose a game and a tool, prepare a Pokemon or a file, follow the console steps and press Start.
   Received Pokemon go to the Settings folder, opened by the button beside Output.

Every trade tool's Pokemon to offer may be left empty: Start has PKHeX build a random legal Pokemon
of that game for your trainer (`command.prepare`), new at each run.

Mystery Gift tools share one builder (preset, build your own, `.pokegift`, `.wc8` on Sword/Shield).
Save gift file exports without a board as `.pokegift`, `.wc3` or `.wc8`
([Mystery Gift files](gifts.md#desktop-app)).

## First launch

macOS keeps its native window buttons; Windows and Linux draw them in the app header, which drags
the window and maximizes on double-click.

| system | steps |
|---|---|
| macOS | unsigned: open once, close the warning, then System Settings, Privacy & Security, Open Anyway |
| Windows | extract the zip and run `pokeldn.exe`, `_internal` beside it; SmartScreen: More info, Run anyway. No COM port: [Windows USB drivers](#windows-usb-drivers) |
| Linux | GTK 3 and libsecret; `sudo usermod -aG dialout $USER` (`uucp` on Arch), then log in again. See [Linux serial ports](#linux-serial-ports) |

## Android setup requirements

The [Android app](../examples/android/README.md) is this interface on a phone. The Board page
rereads USB state on plug, unplug, the USB prompt closing and return from Settings. A native-USB
board (`303a:1001`) opens the app when plugged in.

| detected state | guidance |
|---|---|
| no compatible USB device | check the data cable; show the phone's USB host or OTG setting (OnePlus has an OTG toggle) |
| USB permission missing or denied | explain Android's prompt; offer a retry |
| board handshake fails | check the board and firmware; show the error |
| board answers | show board and firmware; continue |
| board disconnects, or return from Settings | refresh and resume when ready |

A classic ESP32 works only on a CP210x bridge (`10c4:ea60`, `UsbStream.java`); CH34x and FTDI are
named as unsupported. PKHeX runs on the phone. Saving and "Open the folder" (a zip) use Android's
file picker.

## iOS setup

The [iOS app](../examples/ios/README.md) is this interface on an iPhone or iPad (AltStore or
SideStore). It reaches the board over Bluetooth: install the Bluetooth wireless firmware from the
desktop Board page (`pokeldn-radio-ble-c6.bin` for an ESP32-C6, `pokeldn-radio-ble.bin` for a
classic ESP32); USB only powers it. While the phone holds the board, the board ignores USB: close the
iOS app before using it elsewhere. App files are under Files, On My iPhone, pokeldn.

## Window sizes

A page's panels are laid out by the width they have, measured as the window changes
(`gui/theme.py` `Panes`). The options column never gets narrower than 440 points beside the others.

| width left for the panels | layout |
|---|---|
| side panels at full width plus 440 | side by side |
| side panels at 88% plus 440 | side by side, side panels narrowed |
| the last panel at 88% plus 440 (a page of three) | the first two on a switcher, the last beside them |
| less | one panel at a time on a switcher |

Narrowing a window from side by side brings the options column forward. On a wide window the options
column keeps to 720 points, centred, and fields go as many to a row as fit; Settings and Plugins keep
to 760. A page opened after a resize starts in the layout its width allows.

The desktop window goes down to 380 points wide. Below 760 it switches to the phone layout below,
live, and back when widened; a desktop window keeps its title bar row above the content.

## Phones

Below 760 points wide, pages sit in a bottom tab bar and panels show one at a time on a switcher
(Games, Options, Session). Android and iOS have no Control or Update page.

## The Games page

A game's list shows one row per activity: Trade, Mystery Gift, then each raid kind and the Union
Circle. The row's ways of running it are buttons above its options, one line per choice:

| choice | buttons | shown on |
|---|---|---|
| Your console | Joins (pokeldn hosts), Hosts (pokeldn joins) | Trade on a board or LAN, raids, Dynamax Adventure |
| Connection | Board, Wi-Fi with no board, Online | Trade; Wi-Fi only on Sword/Shield |
| Mode | Quests, Encounters | Union Circle |

Each combination is one catalog tool (`pokeldn/app/catalog.py`, a `Tool`'s `activity` and
`variant`), so a run, its saved fields and `python -m pokeldn TOOL` keep the tool's key. A choice
with one option is not shown: an online trade has no console choice. Changing one choice keeps the
others last picked on that row. A plugin tool joins a row the same way
([A tool's row](plugins.md#a-tools-row-112)).

## App language

Settings, App language lists English and installed language packs
([Language packs](plugins.md#language-packs-15)); a change applies after restart, missing strings
fall back to English. Trainer language is separate. The bundled Noto Sans CJK SC font covers
Chinese, Japanese and Korean (`gui/assets/fonts/LICENSE`). Its own ‘ ’ “ ” · … are full-width, so
Noto Sans Punctuation, the Latin-width forms of the same six from the same font
(`scripts/gen_punctuation_font.py`), comes ahead of it; a pack's `font_family` still comes first.

## Your trainer

Settings, Your trainer is the original trainer of every Pokemon the app builds: name, gender,
language and two ID pairs as the games show them. A record stores a 16-bit TID and 16-bit SID, the
halves of one 32-bit id.

| games | ID shown | secret ID | stored id |
|---|---|---|---|
| FireRed, LeafGreen | TID, 0 to 65535 | SID, 0 to 65535 | `SID << 16 \| TID` |
| Let's Go, Sword/Shield, BDSP, Legends Arceus, Scarlet/Violet, Legends Z-A | id mod 10^6 | id div 10^6, 0 to 4294 | `secret * 10^6 + ID` |

`Settings.ids` converts per game. Every console-linking tool presents this trainer as its player
(`tests/test_gui_catalog.py`). FireRed/LeafGreen names are cut to seven Gen III characters; an
unencodable name becomes `POKELDN` (`Settings.name`). Legends Z-A treats a received Pokemon as the
player's own only when gender, IDs and name match
([the received record](za.md#what-the-trade-writes-into-a-received-record)); Legends Arceus's record
carries the gender ([the record](pla.md#the-games-reader-and-the-pre-handler-phase)).

### Find your trainer

Find mine fills one row's ID and secret ID, with the name, gender and language, from the newest
trainer a run read off a console. The Switch games never display the secret ID; the link carries it.

| row | what names the trainer |
|---|---|
| FireRed, LeafGreen | the console's LinkPlayer, `trainerId` = `SID << 16 \| TID`, in every trade, Mystery Gift and Union Room session, both roles |
| Switch | the console's session data in a Let's Go, BDSP, Legends Arceus, Scarlet/Violet or Legends Z-A trade, both roles ([Whose save it is](gift_simulated.md#whose-save-it-is)); in Sword/Shield, and in any title, a Pokemon the console traded that its save caught (handler 0, the game's own version, not an egg) |

A launcher prints `[trainer] {json}` once per trainer (`pokeldn.console_trainer`); the app keeps the
newest per row in `settings.json` `found_trainers` and logs it under the private-log masks. The Switch
row serves every Switch title, so it takes the last one traded with. With nothing found, Find mine
asks for a trade.

## Windows USB drivers

A classic ESP32's USB-to-serial bridge needs a driver before Windows gives a COM port (Device
Manager problem code 28). S3, C3 and C6 on native USB need none.

| bridge | USB id | driver |
|---|---|---|
| CP210x | `10c4:ea60` | [CP210x VCP drivers](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers): right-click `silabser.inf`, Install, replug |
| CH340 | `1a86:7523` | [CH341SER.EXE](https://www.wch-ic.com/downloads/CH341SER_EXE.html): Install, replug |

With no COM port, the Board page polls `Win32_PnPEntity` (`ConfigManagerErrorCode <> 0`) every 2 s
and names a known bridge (`gui/board.py` `bridges_without_driver`).

## Linux serial ports

The port needs the `dialout` group (`uucp` on Arch); on `EACCES` the Board page names the group.

| service | board | effect |
|---|---|---|
| brltty 6.4 (Ubuntu 22.04) | CH340 | claims it, no `/dev/ttyUSB*` ([LP 1990357](https://bugs.launchpad.net/bugs/1990357)); fix: `sudo apt remove brltty` |
| brltty 6.6 (Ubuntu 24.04) | CH340 | claimed only behind a `1a40:0101` hub ([LP 1958224](https://bugs.launchpad.net/bugs/1958224)) |
| ModemManager 1.23 | all | no ignore rule for `10c4`, `1a86`, `303a` |

With no port, the Board page reads `/sys/bus/usb/devices` and names a bridge with no tty
(`gui/board.py` `bridges_without_port`).

## Local storage

Settings, Storage shows reclaimable space; Clear local files removes it in the background after a
confirmation, and holds off sessions and flashes meanwhile. Save anything needed for a bug report
first.

| removed | kept |
|---|---|
| `session/` (captures, traces, temporary offers), `logs/`, unused generated or imported offers in `pokemon/`, empty folders | offers under a minute old or referenced by saved settings and queues; received files, bank, saves, keys, firmware, settings; symlinks; files changed after the check |

## Your saves

The FireRed/LeafGreen Mystery Gift tool's Your save tab backs up or restores the console's save
([Save backup and restore](frlg_gift.md#save-backup-and-restore)). Saves live in
`Documents/pokeldn/Saves` (`pokeldn.app.saves`; inside `POKELDN_DATA` when set), a `.sav` and a
`.json` each.

| action | what happens |
|---|---|
| Back up from the Switch | writes `backup-<run>.sav`; a cut-short backup stays in `Saves/.partial` and the next resumes it |
| Put a save on the Switch | passes `--save-restore`; Start is blocked until a save is chosen |
| `+` or a dropped `.sav` | copied in; a 16-byte emulator footer is dropped, other sizes than 128 KB refused |
| Rename, Export, Delete | Delete removes both files locally |
| View and edit | PKHeX reads trainer, party and boxes |

A restore is blocked without a whole save copy or with an illegal party Pokemon, until Restore
anyway is on. The editor changes trainer name, gender, money, coins and the party; Keep as a new save
writes through PKHeX, recomputing sector checksums, as a new entry.

## The bank

The Bank page keeps every received Pokemon and trades one into any game HOME would move it to.
Records live in `Documents/pokeldn/Bank` (`pokeldn.app.bank`; inside `POKELDN_DATA` when set) in
their game's format with a `.json`.

| step | what happens |
|---|---|
| a trade completes | each received file is banked once by its bytes |
| a Pokemon is banked | `.json` keeps species, summary, verdict, source, SHA-256, a random 63-bit tracker, `home_tracker` |
| destinations | the helper's `destinations` tries all seven games |
| a destination is chosen | `move` converts it into that tool's queue with `"bank": id` |
| trade N completes | `[done] trade N complete` removes it from the bank |
| the run fails | it stays in the bank and queue |

A move uses PKHeX's HOME conversion (`EntityConverter.ConvertToType` through `PKH`) and the
destination's legality check. The app's trainer becomes handler (`IHandlerUpdate`,
`PB8.UpdateHandler`); invalid moves get PKHeX's suggested moveset; PID, encryption constant, OT and
IDs are kept, and the run omits `--fresh-pid`.

| refusal | source |
|---|---|
| nothing back to FireRed/LeafGreen | `EntityConverter.IsConvertibleToFormat` |
| nothing to Let's Go | HOME only takes from it |
| eggs; FireRed/LeafGreen Pokemon with an item or HM move | HOME's FireRed/LeafGreen screen |
| species or form absent | destination's personal table |
| Legends Z-A records out | PKHeX.Core 26.8.26 has no route |

The box lists every banked Pokemon with a search over its summary, a sort (newest, oldest, Pokedex
number, name), a filter (shiny, waiting to trade, not legal) and Select, which picks several Pokemon (a long press starts it too) for one Export to a
folder, Take out of trades or Remove. A sprite's crop is kept with its SHA-256 in the sprite cache's
`index.json`, so a box opens without decoding a PNG it has shown before.

A Pokemon's pane shows its battle set from the helper's `check` (`battle`): IVs, effort and stats in
Showdown's order, and its Showdown set in English for Copy as a Showdown set. The effort column is
Let's Go's AVs (`IAwakened`), Legends Arceus's GVs as the game shows them (stored value plus
`GanbaruExtensions.GetBias` of the IV) and EVs elsewhere.

The Pokedex box lists every species one of the bank's seven games holds (the union of the helper's
`species`), with the bank's count, a sprite and a shiny mark for each one it holds; a filter shows
the held, the missing, or those with no shiny yet. A held species opens the box searched for it.

Edit allows what the game allows: nickname, level upward, moves, held item. The helper's `check`
refuses an edit that makes a legal Pokemon illegal. Queued Pokemon are not editable.
`tests/test_bank.py` covers moves, refusals, edits and imports through the real helper.

### The HOME tracker setting

PKHeX flags a missing tracker (`TransferTrackerMissing`) on a Pokemon moved into another game and on
a gift that came through HOME. HOME 3.1.0+ refuses a tracker it did not issue (error 10015).
Settings, advanced, HOME tracker (`Settings.home_tracker`) is sent with every helper request and to
runs as `POKELDN_HOME_TRACKER`.

| setting | tracker written | legality | warning |
|---|---|---|---|
| `empty` (default) | none | accepted when legal with a tracker | PKHeX flags the missing HOME tracker |
| `made` | random 63-bit (the bank's) | unchanged | Can't be deposited in HOME |

Under `empty` the helper judges a record on a tracked copy with HOME's changes (`ValidWithTracker`),
since PKHeX gates evolutions across HOME games and Z-A realigned abilities on a tracker. Gifts follow
the setting (`MendGift`); a made tracker comes with HOME's changes (`HomeSeen`: scale as height on
Scarlet/Violet, Z-A height, weight and Alpha mark). Sword/Shield Mystery Gift cards never carry one
([Pokemon HOME](swsh_gift.md#pokemon-home)).

### Importing

The plus button or a dropped file imports a PKSM bank, a save (`SaveUtil.TryGetSaveFile`; a 3DS save
is a file named `main`) or one record of any PKHeX format (`FileUtil.TryGetPKM`). A save yields party
then box slots; a PKSM bank yields its box slots in order.

| PKSM bank (`.bnk`) | layout (PKSM `common/source/BankFile.cpp`) |
|---|---|
| header | `PKSMBANK`, u32 version, u32 box count (absent in version 1, read from the length) |
| entry | u32 generation tag, then the decrypted record padded with `0xFF`; 264 bytes in versions 1 and 2, 0x150 in version 3 |
| slots | 30 per box, at most 500 boxes |
| tags (PKSM-Core `Generation.hpp`) | 0 Gen 4, 1 Gen 5, 2 Gen 6, 3 Gen 7, 4 Let's Go, 5 Gen 8 (PK8), 6 Gen 3, 7 Gen 1, 8 Gen 2; `0xFFFFFFFF` empty |

A Gen 1 or 2 entry is a one-Pokemon list with both names: 59 or 69 bytes for Gen 1, 63 or 73 for Gen 2,
the Japanese length when its last byte is `0x50` or 0 (PKSM `3ds/source/Bank.cpp`, `Bank::pkm`). A
version above 3 is refused. Box names live in PKSM's `.json` beside the bank and are not read.

| record | kept as |
|---|---|
| a bank game's format | as is, when legal |
| any other | held item removed, Gen 3/4 HM moves forgotten; if legal, moved to the first game taking it: FireRed/LeafGreen, Scarlet/Violet, Sword/Shield, BDSP, Legends Arceus, Legends Z-A |

Illegal records, bad checksums, other games' eggs and unreachable species are refused.
`Bank/.imported` keeps the SHA-256 of each imported record, so re-importing a save brings only
changed records.

### Unresolved

- Whether HOME accepts a made tracker, or an empty one on a Pokemon moved across games.
- Whether HOME's FireRed/LeafGreen rules go beyond eggs, held items and HM moves.
- Which field carries HOME's Switch FireRed/LeafGreen origin icon; PKHeX converts a `.pk3` by the Pal
  Park lineage.

## The GTS

The GTS page lists open listings filtered by species and the player's own under Yours. Shiny only
keeps listings offering a shiny; My bank can answer keeps those a legal, unqueued banked Pokemon
answers. The listings sort newest first, by end date, by Pokedex number or by level. A shiny Pokemon,
offered, asked for or picked to deposit, carries sparkles. Deposit takes a legal,
unqueued banked Pokemon, held in `Documents/pokeldn/GTS` while listed, and asks for up to three
species, each optionally shiny, under one level range. The app answers offers whenever it runs
([The GTS](online.md#the-gts)).

## Boards and firmware

The Board page lists every plugged board, with its firmware, version and Up to date or Update
available. The Firmware card (`gui.board.FIRMWARES`) installs Wireless or Controller after a
confirmation; Install from a file takes a pokeldn `.bin`.

| board | found by | version from |
|---|---|---|
| Wireless | serial port | HELLO reply |
| Controller, classic ESP32 | serial port | status frame |
| Controller, ESP32-S3 | USB id `0f0d:0092` | Bluetooth status |
| none | serial port, no answer | none |

The shipped version is the ESP-IDF app descriptor's `version` (magic `0xABCD5432`, at `0x10020` in a
merged image). An S3 running the Controller firmware gets the download command over Bluetooth; the app
waits 20 s for the loader port and flashes with `--from-loader`.

A board kept as a [portable beacon](hardware_esp32.md#portable-beacon) shows Kept gift with Remove.

### Board details

Copy board details, on the Board page with or without a board selected, copies the details as plain text
and saves them as `logs/board-report-DATE.txt` in the data folder (`gui/board_report.py`). Copying them
opens the selected port, so the board may restart; during a run it lists the ports only.

| section | what it holds |
|---|---|
| This computer | app version, packaged or source, system, Python, pyserial and esptool versions |
| USB serial ports | every port pyserial lists, with its USB ids, serial number, location and `hwid` |
| Drivers | Windows bridges with no driver, Linux bridges with no tty, controller boards on USB |
| Opening the port | the open's error with `errno`/`winerror`, or the bytes read in the first 2 s |
| pokeldn firmware | HELLO and STATUS, or why none answered |
| ESP32 bootloader | esptool's chip, description, features, crystal, MAC and USB-Serial/JTAG mode |
| Activity | the page's last 80 lines |

## The controller

The Control page presses a Switch's buttons through the Controller firmware
([Controller board](hardware_pad.md)) and plays macros. An ESP32-S3 plugs into the Switch and is
reached over Bluetooth LE; a classic ESP32 stays on the computer's USB and pairs from Change
Grip/Order. Reinstalling clears the pairing. When the link drops the page searches until the board
answers or Stop looking.

| part | what it does |
|---|---|
| on-screen controller | holds buttons; sticks in eight directions, L3/R3 at centre |
| Keyboard | arrows D-pad, X A, Z B, S X, A Y, Q L, W R, 1 ZL, 2 ZR, Enter +, Backspace -, H HOME, C Capture |
| Record into the macro | each press becomes a step with hold time and pause |
| macro editor | buttons, sticks, waits, nested repeats; Run once and Loop parts |
| Play on the board | the board plays the macro on its own clock |

Macros are `.pokemacro` files in `Documents/pokeldn/Macros`
([Controller board, Macros](hardware_pad.md#macros)). The page talks to `pokeldn.pad.service` on
`127.0.0.1:47800`. On macOS 26 a process signed as a bundle's main executable gets no Bluetooth
discoveries, so the packaged app runs the service from `Contents/Helpers/pokeldn-bluetooth`, a
bare-signed copy with `_internal` linked to `../Frameworks`.

## The board's screen

Settings, Show the board's screen, draws the board's 128x64 pixel screen at the top of the Session
panel, whether or not a screen is wired to the board ([The screen](hardware_esp32.md#the-screen)).
The app sets `POKELDN_SCREEN_MIRROR=1` for a run; the run then prints each DISPLAY command it sends
and, once a second, the board's mode, seated stations, data frames and BOOT presses from STATUS:

    [screen] reset
    [screen] cmd HEX
    [screen] radio MODE STATIONS RX TX PRESSES

`pokeldn.app.screen_render` replays them through a Python copy of the firmware's `scene.c` and
`screen.c`; `tests/test_screen_render.py` holds every frame to the compiled C. The panel draws at the
firmware's 50 ms frame, dims with the board and turns off after its ten idle minutes.

## Pokemon sprites

Images come from [PokeAPI](https://github.com/PokeAPI/sprites) on demand, cached in `sprites/`.
Settings, Pokemon sprites disables downloads and clears the cache. A missing image shows a
placeholder; a missing shiny falls back to normal.

## Raid events

The Scarlet/Violet Tera Raid (Host) Raid event card hosts raids from
[EventsGallery](https://github.com/projectpokemon/EventsGallery)
([Event raids](sv_raid.md#event-raids)), copied into `EventsGallery/` (`pokeldn.app.events_gallery`).
Download fetches the newest commit touching `Released/Gen 9/SV/Raid Events` from
`codeload.github.com` and keeps each event's newest tables; Check for updates compares that commit.
A copy replaces the old only once complete; Windows opens long paths as `\\?\`.

Choosing an event limits the raid card to its versions, progresses and crystals
(`raid_event.constrain`), and Find a raid to its crystals, bosses and reward tables
([Finding a seed](sv_raid.md#finding-a-seed), [Size marks](sv_raid.md#size-marks)). A catch-once boss
offers "Let it be caught again" (`--raid-catch-normal`). Folding the card reverts to a standard raid
("Off: Event"); an event missing from the copy reads "Missing: Event" and the run refuses it.

## Hosted raid rewards

The Rewards card offers templates (training items, mints, battle items, berries, evolution items, Tera
Shards, Herba Mystica, treasure, balls) with a shared quantity of 1 to 999; editing switches to Custom
rewards, up to 45 rows. Raid's own rewards clears the overrides ([Hosting](sv_raid.md#hosting); `gui/views/rewards.py`).

## Raid NPC partners

The Raid NPC partners card fills slots the consoles leave empty ([Partners](sv_raid.md#partners);
`gui/views/raid_partners.py`); with nothing chosen the host draws them as a console does. Partners'
progress passes `--raid-partner-progress`; each card shows trainer, Pokemon (level four fifths of Our
Pokemon's), Tera type, ability and moves, and favoured partners carry a blue or silver strip
([Favoured partners](sv_raid.md#favoured-partners)). Each click passes `--raid-partner` in slot
order; a pick the stage lacks is dropped.

## Union Circle

Scarlet/Violet's Union Circle tools join a console's circle under a four-digit Link Code
([Union Circle](sv_union_circle.md)); the field starts empty.

- Quests: unlock remaining Snacksworth legendaries or give BP (1 to 9,999,999); a Snacksworth run
  draws a [progress](#progress) bar of clears.
- Encounters: the spawn card (`gui/views/encounter.py`) sets species, shiny, form, level, Tera Type,
  nature, gender, ability, item, scale and IVs; Legal encounters only (default) restricts them to what
  PKHeX accepts and lists the valid locations. It passes `--spawn` and `--spawn-*`.

`[panel]` cards ([Status cards](plugins.md#status-cards-18)) show atop the tool's options while a run
lasts. `--verbose-circle` logs every circle message.

## Mystery Gift - Simulated

The tool's card on Let's Go, BDSP, Legends Arceus, Scarlet/Violet and Legends Z-A lists gift Pokemon
from PKHeX's event table ([Simulated Mystery Gifts](gift_simulated.md#the-gifts);
`gui/views/event_gifts.py`), newest first, searchable. A click queues a fresh copy for the Settings
trainer; up to six gifts trade in one hosted session. A copy keeps the trainer it was made with.

A gift naming a receiver whose language no save reached shows an illegal tile
([Saves a card reached](gift_simulated.md#saves-a-card-reached)). Made for the receiving player
(default on) remakes such gifts for the console's save
([Made for the receiving player](gift_simulated.md#made-for-the-receiving-player)); when no queued
gift qualifies the switch is disabled and no `--for-receiver` is passed. A HOME gift is outlined in
amber and takes [the HOME tracker setting](#the-home-tracker-setting)
([The copy a trade offers](gift_simulated.md#the-copy-a-trade-offers)).

## Private logs

Settings, Hide personal details in logs (default on) masks shown and copied logs
(`pokeldn/app/redact.py`):

| masked | shown as |
|---|---|
| home folder in a path | `~` |
| iOS app container | `<app>` |
| device half of a MAC | `**:**:**` |
| quoted value after `ot_name`, `ht_name`, `OT`, `nickname`, `trainer`, `player`, `name` (except `POKELDN`, `PKLDN`) | `***` |
| value after `TID`, `SID`, `trainer_id` | `***` |
| a seen trainer name, and the Settings one, as a whole word | `***` |

Session records (`captures/`) are unmasked. Link-local addresses stay.

## Pop-ups

Runs, child processes and the app can open pop-ups over any page (`pokeldn.popup`, plugin API 1.2).

| kind | callback |
|---|---|
| `acknowledge(title, text)` | `on_ack` |
| `confirm(title, text, agree, disagree)` | `on_agree`, `on_disagree`, `on_dismiss` |
| `choose(title, text, options)` (1.7, 2 to 8 options) | `on_choice(index)`, `on_dismiss` |

Options: `id` (reopening an open id replaces it and drops its callbacks) and `tone` (`info`,
`warning`, `error`). Opening returns the id; callbacks run on the answer thread unless
`set_dispatcher(dispatch)` is set. `cancel(id)` closes one. 32 unanswered pop-ups raise
`RuntimeError`. Without an app (`available()` false) a pop-up is a `[pop-up]` output line.

`runner.Process(..., popups=app.popups)` sets `POKELDN_POPUPS=1`; the child writes `[popup]` and JSON
on stdout and reads `[popup] {"id", "n", "answer"}` on stdin (`pokeldn.app.runner.child`); `n` makes
a late answer to a replaced pop-up fire nothing. `pokeldn.app.popups.Manager` keeps them,
`gui.popups.Dialogs` draws them. The app's own pop-ups report a failed update, a disabled plugin and a
receiver gift sent with the Settings trainer ([The trade](gift_simulated.md#the-trade)).

## Progress

A run prints `[progress] DONE TOTAL UNIT TITLE` (`pokeldn.progress.show`, API 1.7; `UNIT` is `bytes`
or `items`) to draw a bar with amount, 30 s rate and time left, at most four lines a second per
title. `[save]` lines draw the same bar.

## Updates

At launch the app asks `api.github.com/repos/Decryptu/pokeldn/releases/latest` (5 s timeout). A
`vX.Y.Z` tag above `pokeldn.__version__` adds an Update entry with Update now or Download.

Update now (`pokeldn.app.update`) downloads the platform archive and `SHA256SUMS` into `update/`,
refuses a checksum mismatch, unpacks (`ditto -x -k`, `tarfile` `data` filter, `zipfile`), and starts
`pokeldn --apply-update NEW TARGET PID VERSION` (`gui/updating.py`). The helper waits for the old app
to quit (and on Windows for its processes), renames it to `.<name>.old`, copies the new one in and
opens it; any failure restores the old app. The new app reads `update/outcome.json` once. The checksum
detects corruption and does not authenticate the release.

| situation | behaviour |
|---|---|
| pre-release, draft, odd tag | not offered |
| no network | Check now says GitHub did not answer |
| Updates off in Settings | no launch request |
| no archive or `SHA256SUMS`, a source checkout, App Translocation, an unwritable folder (macOS, Linux) | Download only |
| Windows, `C:\Program Files` | Update now behind UAC (`ShellExecuteExW` `runas`) |
| Windows, the root of another drive (`D:\pokeldn`) | Update now without UAC: the swap only adds folders beside the app, which a volume's root allows users. A release before 0.34.0 probed the root with a file, asked for UAC there, and a standard user's update stopped on "Windows did not give pokeldn permission to change D:\"; from such a release the next version is downloaded once by hand |
| Windows, a mapped or `subst` drive | the drive letter is kept; the helper finds the old app's processes under either spelling; behind UAC the helper gets the folder the letter stands for, since an elevated process sees no letter the user's session mapped |
| a session, flash or cleanup running | asks to finish first |

`scripts/check_update.py ARCHIVE FOLDER` tests a packed app's update against 127.0.0.1;
`POKELDN_UPDATE_URL` replaces the endpoint (`tests/test_app_update.py`). Whether macOS asks for App
Management permission in `/Applications` is unmeasured.

## File drops

| target | takes |
|---|---|
| a trade's Pokemon | a Pokemon file or Showdown `.txt`; extras fill the next trades |
| Add a trade | one trade per file |
| a Gift card | `.pokegift`, `.wc8`, `.wc3` |
| Board Firmware card | a pokeldn `.bin` |
| any path field | the file, or its folder |

Flet 1.0.2's client takes no drops; `scripts/build_client.py` builds Flet's client with
`gui/flet_drop` ([desktop_drop](https://pub.dev/packages/desktop_drop)) into `gui/client/<platform>`,
using the Flutter version `python -m flet_cli.cli --version --json` names, with a macOS deployment
target of 12.0. Without it `gui/main.py` runs Flet's own client, without drops.

## The docs page

The Docs page shows the app guide and every navigable page of this site; search matches sections,
every word required, heading matches first (`gui/views/docs.py`).

## Unreleased titles

A title ahead of its Switch release shows in Games, Bank and Docs only from a source checkout
(`pokeldn/app/preview.py`). `POKELDN_PREVIEW=1` shows it anywhere, `0` hides it. Its docs page sets
`nav_exclude` and `search_exclude`.

## Run from source

Install Python 3.13 and the .NET 10 SDK:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r gui/requirements.txt
dotnet build -c Release services/pkhex -warnaserror
python scripts/build_client.py    # optional: file drops; needs Flutter
python gui/main.py
```

Raspberry Pi OS adds piwheels as a package index, and piwheels' `flet_web-1.0.2-py3-none-any.whl`
(25 KB) lacks the `flet_web/web` client that PyPI's wheel (27 MB) carries; the app then answers
`RuntimeError: Web root path not found`. Install that package from PyPI alone:
`python -m pip install --force-reinstall --no-cache-dir --index-url https://pypi.org/simple flet-web==1.0.2`.
There is no Linux arm64 release; a Raspberry Pi runs the app from source.

A checkout has no firmware image. Download the firmware on the Board page fetches all images from the
newest release with `SHA256SUMS` and writes them only when all match.

## Build a desktop app

With ESP-IDF v6.1 active, build each image into `gui/firmware`, then pack:

```sh
mkdir -p gui/firmware
OUT="$PWD/gui/firmware"
cd firmware/esp32
for t in esp32:radio esp32s3:radio-s3 esp32c3:radio-c3 esp32c6:radio-c6; do
  chip=${t%%:*}; name=${t#*:}
  idf.py -B build/$chip -D SDKCONFIG="$PWD/build/$chip/sdkconfig" set-target $chip
  idf.py -B build/$chip -D SDKCONFIG="$PWD/build/$chip/sdkconfig" build
  idf.py -B build/$chip merge-bin -o "$OUT/pokeldn-$name.bin"
done
export POKELDN_BLE=1   # Bluetooth images for the iOS app (hardware_esp32.md, Bluetooth)
DEF="sdkconfig.defaults;sdkconfig.defaults.ble"
for t in esp32:ble esp32c6:ble-c6; do
  chip=${t%%:*}; name=${t#*:}
  idf.py -B build/$name -D SDKCONFIG="$PWD/build/$name/sdkconfig" -D SDKCONFIG_DEFAULTS="$DEF" set-target $chip
  idf.py -B build/$name -D SDKCONFIG="$PWD/build/$name/sdkconfig" -D SDKCONFIG_DEFAULTS="$DEF" build
  idf.py -B build/$name merge-bin -o "$OUT/pokeldn-radio-$name.bin"
done
unset POKELDN_BLE
cd ../pad
idf.py -B build -D SDKCONFIG="$PWD/build/sdkconfig" set-target esp32s3
idf.py -B build -D SDKCONFIG="$PWD/build/sdkconfig" build
idf.py -B build merge-bin -o "$OUT/pokeldn-pad-s3.bin"
cd ../..
python scripts/build_client.py
python scripts/build_unicorn.py   # needs CMake
python scripts/pack_app.py
```

The frozen app check verifies every image, the `flet_drop` client and Unicorn are bundled. The
version is `pokeldn.__version__`, bumped with `.github/release-notes.md`, whose first line must be
`# pokeldn X.Y.Z` (`tests/test_release.py`). A `v*` tag publishes nine files and `SHA256SUMS`; only
hyphenated tags are pre-releases.

The apps are one-folder PyInstaller builds (`pokeldn.app`; a `pokeldn` folder with `_internal`
elsewhere): on an M4 the Games page opens in 0.7 s and a run starts in 0.08 s. `scripts/pack_app.py`
passes `--onedir` after Flet's `--onefile` and sets `LSBackgroundOnly` so only the viewer has a Dock
icon.

| part | size | kept small by |
|---|---|---|
| Flet viewer | 31 MB (9.4 MB xz on macOS) | no optional extensions, one architecture, `--split-debug-info` |
| Unicorn | 3 MB | ARM and ARM64 engines only |
| PKHeX helper | 16 MB | full trimming |
| Python | 8 MB | excluded web, image, test and syntax modules; `strip -x` on macOS |

Packaging traps:

- Trimming disables reflection JSON; `JsonSerializerIsReflectionEnabledByDefault` restores it. A
  `DynamicDependency` keeps PKHeX.Core's Gen 3 event table.
- The macOS viewer archive is xz named `flet-macos.tar.gz`; `gui/flet_client.py` opens it with
  compression detection, and removes stale `~/.flet/client` folders marked `pokeldn-drop`.
- Never strip the executable or the PKHeX helper: both carry an archive after the Mach-O image.
- `scripts/pack_flet.py` keeps the viewer's entitlements; without
  `com.apple.security.files.user-selected.read-write` choosing `prod.keys` raises
  `ENTITLEMENT_NOT_FOUND`.
- On Linux `pokeldn/app/paths.py` restores the user's `LD_LIBRARY_PATH` (the bundled `libstdc++`
  breaks Fedora's EGL) and sets `FLET_LINUX_DISTRO`.
- Unicorn aborts under Control Flow Guard with `0xC0000409`
  ([unicorn#2281](https://github.com/unicorn-engine/unicorn/issues/2281)); the packer clears
  `GUARD_CF` in `pokeldn.exe` (`0xC160` to `0x8160`). Never enable `faulthandler` in the frozen
  check.

### The app icon

`gui/AppIcon.icon` is an Icon Composer document, the one source of the macOS and iOS icons.
`actool` (Xcode 26) compiles it into `Assets.car` and `AppIcon.icns`; `scripts/pack_app.py` puts both
in `pokeldn.app` and in the Flet viewer, with `CFBundleIconName` set. macOS 26 draws the layered icon
from the catalog; macOS 12 to 15 draw its flat renditions, which sit on Apple's icon grid (the
tile spans 102 of 128 pixels). Windows takes `gui/assets/icon.ico` and Linux `gui/assets/icon.png`,
both full-bleed: neither platform insets an icon.

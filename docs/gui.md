---
title: Desktop builds
---
# Desktop builds

Released apps include PKHeX and merged radio firmware for ESP32, ESP32-S3, ESP32-C3
and ESP32-C6.
Users provide their own `prod.keys`.

Open the app and choose `prod.keys` in Settings. On the Board page, select the USB board to use
as the radio and install the Wireless firmware. Choose a game and a tool, prepare a Pokemon or select a file,
then follow the console instructions and press Start. Received Pokemon are saved to the folder
chosen in Settings; the folder button beside Output opens it. An install detects the chip and selects
its bundled image; an image from a file is checked against that chip before writing. Connect an S3,
C3 or C6 through native USB Serial/JTAG. S2 chips are refused.

Mystery Gift tools share one builder: use a preset, build your own, or open a `.pokegift` file;
Sword/Shield also opens `.wc8` cards. Save gift file exports the selected gift without a board, as
a `.pokegift` or, by its extension, a `.wc3` (FireRed/LeafGreen) or `.wc8` (Sword/Shield).
[Mystery Gift files](gifts.md#desktop-app) describes the forms, cartridge variants and native-format
conversion.

## Your trainer

Settings, Your trainer is the original trainer of every Pokemon the app builds: a name, a language
and two ID pairs, entered as the games show them. A record stores the trainer as a 16-bit TID and a
16-bit SID, the low and high halves of one 32-bit id.

| games | ID shown | secret ID | stored id |
|---|---|---|---|
| FireRed, LeafGreen | the TID, 0 to 65535 | the SID, 0 to 65535 | `SID << 16 \| TID` |
| Let's Go, Sword/Shield, BDSP, Legends Arceus, Scarlet/Violet, Legends Z-A | id mod 10^6, six digits | id div 10^6, 0 to 4294 | `secret * 10^6 + ID`, below 2^32 |

The Switch pair is converted per game in `pokeldn/app/settings.py` `Settings.ids`. Settings saved
before the Switch pair existed derive it from the first pair, so records built from them keep the
same stored id.

Every tool that links to a console presents this trainer as its own player, in place of the name a
recorded message carries (`tests/test_gui_catalog.py`). The ids go wherever a launcher takes them:
FireRed and LeafGreen, Let's Go, Sword/Shield and BDSP. FireRed and LeafGreen hold seven Gen III
characters; a longer name is cut to seven, and a name outside the Gen III characters becomes
`POKELDN` (`Settings.name`).

## Windows USB drivers

A classic ESP32 board reaches the computer through a USB-to-serial bridge chip, printed next to its
USB socket. Windows gives the board a COM port only once the bridge's driver is installed; without
it the board is absent from the app's list and Device Manager shows it with a warning (problem code
28, drivers not installed). ESP32-S3, C3 and C6 boards on their native USB port need no driver.

| bridge | USB id | driver | install |
|---|---|---|---|
| Silicon Labs CP2102 / CP210x | `10c4:ea60` | [CP210x VCP drivers](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers), the CP210x Universal Windows Driver zip | extract it, right-click `silabser.inf`, Install, then unplug and replug the board |
| WCH CH340 | `1a86:7523` | [CH341SER.EXE](https://www.wch-ic.com/downloads/CH341SER_EXE.html) | run it, Install, then unplug and replug the board |

With no COM port listed, the Board page asks Windows for USB devices with a Device Manager problem
(`Get-CimInstance Win32_PnPEntity`, `ConfigManagerErrorCode <> 0`) every 2 s and names a known bridge
it finds, with that driver's install steps (`gui/board.py` `bridges_without_driver`).

## Linux serial ports

The app opens the board as the user, with no root and no kernel networking. Opening the port needs
the `dialout` group (`uucp` on Arch); a port the user may not open fails with `EACCES`, and the Board
page then names the group instead of a busy port.

| service | board | effect |
|---|---|---|
| brltty 6.4 (Ubuntu 22.04) | CH340 `1a86:7523` | claimed by `85-brltty.rules`; no `/dev/ttyUSB*` appears while brltty is installed ([LP 1990357](https://bugs.launchpad.net/bugs/1990357)). Fix: `sudo apt remove brltty` |
| brltty 6.6 (Ubuntu 24.04) | CP210x `10c4:ea60`, CH340 | CP210x rules commented out ([LP 1958224](https://bugs.launchpad.net/bugs/1958224)); CH340 claimed only behind a `1a40:0101` hub |
| ModemManager 1.23 (Ubuntu 24.04) | all | no ignore rule for `10c4`, `1a86` or `303a`; its strict filter passes a `cdc_acm` port only with interface protocol 1 to 6 (`mm-filter.c`) |

With no serial port listed on Linux, the Board page reads `/sys/bus/usb/devices` and names a known
bridge that has no tty under its interfaces, with the brltty fix for a CH340
(`gui/board.py` `bridges_without_port`).

## Local storage

Settings, Storage shows the space occupied by reclaimable local files. Clear local files asks for
confirmation, removes the files in the check and reports how much space was freed. Save records
needed for a bug report before clearing them.

Cleanup includes the app's `session/` working files (captures, serial traces, temporary offers and
session metadata), `logs/`, and unused generated or imported offers in `pokemon/`. Built offers
less than a minute old are kept so a build still finishing can save its selection. Offers referenced
by saved tool settings and queues are kept. Received files and their selected folder, the bank, Switch keys,
selected firmware and settings are preserved, including when they are stored under a cleanup folder.
Pokemon records and binary dumps outside the app's named temporary offers are kept even after the
Received folder changes. Generated offers are identified by the builder's timestamp and random suffix.
Symlinks are skipped; files changed after the check are kept. Empty subfolders are removed.

Finish any active session, flash or board check before cleanup. Cleanup runs in the background and
holds off new sessions and flashes until it finishes. A file that cannot be removed is reported and
can be retried. The Pokemon sprites cache has its own Clear the cache button under advanced settings.

## Your saves

The FireRed and LeafGreen Mystery Gift tool's Your save tab backs the console's save up, or puts one
back, over the Wonder Cards, Friend path ([Save backup and restore](frlg_gift.md#save-backup-and-restore)).
The saves live in `Documents/pokeldn/Saves` (`pokeldn.app.saves`), one `.sav` each with a `.json`
beside it holding its name, where it came from and the console's game code. Clear local files never
touches the folder; with `POKELDN_DATA` set, the library is `Saves` inside that folder instead.

| action | what happens |
|---|---|
| Back up from the Switch | the launcher writes `backup-<run>.sav` and its `.json`; a backup the link cut short is kept in `Saves/.partial` and the next one goes on from it |
| Put a save on the Switch | the chosen save goes to `--save-restore`; Start stays blocked until one is chosen |
| `+`, or a `.sav` dropped on the card | the file is copied in; a 16-byte emulator footer is dropped, any other size than 128 KB is refused |
| Rename, Export .sav, Delete | the name is cosmetic and kept in the `.json`; Delete removes both files from this computer only |
| View and edit | PKHeX reads the trainer, party and PC boxes; see below |

During a run the Session panel draws the launcher's `[save] backup N of 128 KB` or
`[save] restore N of M sectors` lines as a progress bar, and the list refreshes when the run ends.

A restore is blocked when the save has no whole copy, and when PKHeX finds a party Pokemon not legal,
until Restore anyway is turned on. A save's name defaults to the trainer and the cartridge, which only
a backup knows.

The editor changes the trainer's name, gender, money and coins, and the party: reorder, remove, or add
a Pokemon PKHeX builds for this save's own trainer (name, ID, secret ID and language). Each party
Pokemon shows PKHeX's verdict; Check legality runs it over one box, which takes seconds. Keep as a new
save writes the result through PKHeX, which recomputes every sector checksum, checks that the game's
own sector test passes and adds it to the library as a new entry; the original is unchanged.

## The bank

The Bank page keeps every Pokemon a trade brings in and trades one into any game that HOME would move
it to. The records live in `Documents/pokeldn/Bank` (`pokeldn.app.bank`), one record each in its
game's own format (`.pk3`, `.pb7`, `.pk8`, `.pb8`, `.pa8`, `.pk9`, `.pa9`) with a `.json` beside it.
Clear local files never touches the folder; with `POKELDN_DATA` set, the bank is `Bank` inside that
folder instead.

| step | what happens |
|---|---|
| a trade completes | the session panel reads each received file with PKHeX and banks a copy; the Received file stays; bytes already in the bank are not banked twice |
| a Pokemon is banked | its `.json` keeps the species, the summary, PKHeX's verdict, the source file, a SHA-256 of the bytes and a random 63-bit HOME tracker |
| the page lists the destinations | the helper's `destinations` command tries a move to all seven games and reports each refusal |
| a destination's trade tool is chosen | the helper's `move` command converts the record, the result joins that tool's offer queue with `"bank": id`, and the app opens the tool |
| the run's trade N completes | the `[done] trade N complete` line removes the banked Pokemon queued as trade N; at the run's end its queue entry goes too |
| the run fails or is stopped first | the Pokemon stays in the bank and in the queue |

A move goes through PKHeX's own HOME conversion (`EntityConverter.ConvertToType`, through `PKH`), then
PKHeX's legality check in the destination game; a move that is not legal there is refused with
PKHeX's reason, its per-move lines folded into one ("2 of its moves are not legal") and each problem
listed once. On the way:

- A Pokemon from another game takes the bank's HOME tracker. PKHeX marks one without a tracker
  invalid (`HomeTrackerUtil.IsRequired`, `HOMETransferSettings.HOMETransferTrackerNotPresent`).
- The app's trainer becomes its handler, as a save it is moved into would (`IHandlerUpdate`, and
  `PB8.UpdateHandler`). When the check still finds it invalid with its own trainer as the current
  handler, the app's trainer is set as the handling trainer; Sword/Shield asks for it.
- A move that leaves an invalid move gets PKHeX's suggested moveset for the destination.
- PID, encryption constant, original trainer and IDs are kept. A run that offers a banked Pokemon
  is built without `--fresh-pid`.

| refusal | source |
|---|---|
| nothing goes back to FireRed/LeafGreen | `EntityConverter.IsConvertibleToFormat` |
| nothing goes to Let's Go | HOME only takes from it; the converter alone takes a `PK3` into `PB7`, Let's Go's format (7) being above FireRed's (3) |
| an egg | HOME's screen for FireRed and LeafGreen; the converter would hatch it |
| a FireRed/LeafGreen Pokemon holding an item or knowing an HM move | HOME's screen for FireRed and LeafGreen |
| a species or form absent from the destination | the destination's personal table |
| no conversion route | PKHeX.Core 26.8.26 converts no Legends Z-A record out to another game |

Edit changes what a player can change in the game itself: the nickname (empty restores the species
name), the level (upward only), the moves and the held item. The helper's `check` command applies the
fields and runs PKHeX's legality check; an edit that would make a legal Pokemon not legal is refused and
the record is left as it was. A saved edit rewrites the record and its `.json` (summary, verdict,
SHA-256) and the destinations are checked again. A Pokemon queued for a trade is not editable.

A record received from a retail Sword and moved to Legends Z-A, with the bank's tracker and its PID
kept, showed its level and original trainer on a retail Z-A's trade box and completed the trade.

`tests/test_bank.py` moves records between six pairs of games through the real helper and checks
that the destination's launcher takes them, along with each refusal, an edit kept and refused, and the
run that takes a traded Pokemon out of the bank.

### Unresolved

- Whether Pokemon HOME accepts a Pokemon that carries a tracker the bank made, or one moved by the
  bank, when it is later deposited there. Nothing has been sent to HOME.
- Whether HOME's own FireRed/LeafGreen import rules go beyond the eggs, held items and HM moves its
  screen names.
- Which record field carries the origin icon HOME shows on a Pokemon imported from the Switch
  FireRed/LeafGreen, which a cartridge Pokemon moved through Pokemon Bank lacks (players' screenshots,
  unmeasured here). PKHeX.Core 26.8.26 converts a `.pk3` by the Pal Park lineage, so a bank move from
  FireRed/LeafGreen may differ from the record HOME writes.

## The GTS

The GTS page lists other players' open listings, filtered by the species offered or wanted, and the
player's own listings and offers under Yours. Deposit a Pokemon takes a legal banked Pokemon that is
not queued for a trade; a listing's detail offers each banked Pokemon that answers it. While listed or
offered, a Pokemon is in `Documents/pokeldn/GTS`, out of the bank. The app answers offers whenever it
runs, on any page, once a listing or an offer exists. The events and the rules are in
[The GTS](online.md#the-gts).

## Boards and firmware

The Board page lists every board plugged into this computer. The header of the selected board names
its firmware and version, says Up to date or Update available, and offers the one action that status
needs. The Firmware card lists each firmware the app ships (`gui.board.FIRMWARES`: Wireless, then
Controller); the installed one is marked, a firmware the chip cannot run says so, and any other
installs after a confirmation. Install from a file takes a pokeldn `.bin`, recognised by the project
name in its app descriptor.

| board | how the page finds it | where the version comes from |
|---|---|---|
| Wireless firmware | its serial port | the HELLO reply |
| Controller firmware, classic ESP32 | its serial port, after the radio check fails | the status frame on the port |
| Controller firmware, ESP32-S3 | the USB bus (`0f0d:0092`: `ioreg` on macOS, `/sys/bus/usb/devices` on Linux, `Win32_PnPEntity` on Windows); it has no serial port | the status read over Bluetooth |
| no pokeldn firmware | its serial port, when nothing answers | none |

The version the app ships is the `version` field of the image's ESP-IDF app descriptor (magic
`0xABCD5432`, at `0x10020` in a merged image). Update available means that version is newer than
the board's. An install on a serial port lets esptool reset the chip into its loader; on an S3
running the Controller firmware it sends the download command over Bluetooth, waits up to 20 s for
the loader's port, and flashes with `--from-loader`.

## The controller

The Control page presses a Switch's buttons through a board running the controller firmware
([Controller board](hardware_pad.md)) and plays macros on it. Install the Controller firmware from
the Board page (ESP32-S3 or classic ESP32). An ESP32-S3 goes into the Switch's USB-C port, and
Connect reaches it over Bluetooth LE. A classic ESP32 stays on this computer's USB and pairs with the
Switch from HOME, Controllers, Change Grip/Order; Connect reaches it over its serial port. Installing
the firmware again clears the pairing.

The status line says where the board is: plugged into this computer (it is on this computer's USB
bus), into the Switch (its USB is configured and it is not on this computer's bus), or into neither.
The firmware's `mounted` flag says only that some USB host configured the board.

| part | what it does |
|---|---|
| the on-screen controller | holding a button holds it on the console; the sticks take eight directions at full tilt, L3 and R3 are their centres |
| Keyboard | while on, keys tap buttons for the macro's press time: arrows D-pad, X A, Z B, S X, A Y, Q L, W R, 1 ZL, 2 ZR, Enter +, Backspace -, H HOME, C Capture |
| Record into the macro | each press becomes a step with how long it was held, and the pause before the next press becomes that step's pause |
| the macro editor | steps that press buttons and sticks, waits, and repeats that nest; a Run once part and a Loop part repeated a number of times or until stopped |
| Play on the board | compiles the macro, loads it and starts it; the board plays it on its own clock and keeps going if the computer sleeps or disconnects |

A board running the Controller firmware is listed on the Board page while it is plugged into this
computer; [Boards and firmware](#boards-and-firmware) has how it is found and changed. With no
controller connected, the Control page says what is plugged in and links the Board page.

Macros live in `Documents/pokeldn/Macros` (with `POKELDN_DATA` set, `Macros` inside that folder), one
`.pokemacro` file each, written on every edit. Export writes a copy to share; import checks a file
and copies it in under a free name. The format is in [Controller board, Macros](hardware_pad.md#macros).

When the link drops (the board loses power moving from the computer to the Switch), the page looks
for the board again until it answers or Stop looking is pressed.

The page talks to `pokeldn.pad.service`, a child process that holds the Bluetooth link on
`127.0.0.1:47800`. macOS stops a process that opens Bluetooth unless its app declares
`NSBluetoothAlwaysUsageDescription`; the packaged app does, and only the child stops when one does
not. The child exits when the app closes its stdin.

On macOS 26, `bluetoothd` gives a background process signed as an app bundle's main executable a
passive "ThirdPartyApp scan" and delivers it no discoveries, with or without a service UUID filter;
a bare-signed binary (`Info.plist=not bound`) gets an active scan. The packaged app therefore
starts the service from `Contents/Helpers/pokeldn-bluetooth`, a copy of its executable signed with
that identifier, with `_internal` linked to `../Frameworks`; it runs under the app's Bluetooth
permission. From the main executable, a scan saw 0 devices; from the helper, 19, the board among
them. An app that finds a service running other code
(`code` in its status reply) tells it to quit and starts its own.

## Pokemon sprites

The sprites are the 96x96 PNGs behind `sprites.front_default` and `sprites.front_shiny` of
`https://pokeapi.co/api/v2/pokemon/{id}`, read from `raw.githubusercontent.com/PokeAPI/sprites`
(`sprites/pokemon/{id}.png`, `sprites/pokemon/shiny/{id}.png`). The JSON (300 KB per species) is not fetched; the sprite path is fixed by the id. Twelve National Dex numbers sampled from 1 to 1025
all have both sprites; 1026 returns 404. When a shiny sprite is missing, the normal one is shown.

| where | size |
|---|---|
| the trade picker, beside Species, shiny when Shiny is on | 96 px, the whole canvas |
| the card of a Species field (Sword/Shield Mystery Gift), shiny when the tool's Shiny switch is on | 46 px tile |
| Session panel, Offering: each queued offer in trade order, its summary as a tooltip | 46 px tile |
| Session panel, Received: each Pokemon file the run saved, read by PKHeX, with its summary | 46 px tile |

Sprites are drawn with nearest-neighbour filtering at 1:1, never at a size in between. A 46 px tile
crops the canvas around the visible pixels (`pokeldn.app.sprites.bounds`) and draws them at 1:1 when
they fit in 46 px, else at 1:2. Of 33 sprites sampled, the visible box ran from 36x29 (Eevee) to the
full 96 px width (Lugia, Reshiram). At 1:2 a sprite lands on whole device pixels of a 2x display.

The Received list matches files by the run's `{stamp}`, which every tool's output path carries; a
launcher adds `-N` for trade N (`pokeldn.pokemon.trade_path`) or writes into a folder or prefix so
named. A file still growing is read again on the next second. What the list holds is what the
launcher wrote: some launchers write the console's offer when the console picks it, before the trade
completes.

The cache is `sprites/` in the app's data folder, one file per sprite under `normal/` and `shiny/`.
A sprite downloads on first use and is read from disk afterwards, with no network access. Rules:

| situation | behaviour |
|---|---|
| no network, nothing cached | the pixelarticons `circle-question` icon; no error; the next attempt waits 60 s |
| HTTP 404 | a `{id}.none` marker; not asked again for 7 days |
| reply that is not a PNG, or over 200 KB | not cached |
| damaged cached file | deleted, downloaded again |
| data folder not writable | the sprite shows for the session and is not saved |
| Settings, Pokemon sprites off | the cache is read, nothing is downloaded |

Settings has the switch and a button that empties the cache. `POKELDN_SPRITE_BASE` replaces the sprite
host, for tests (`tests/test_sprites.py`).

## Updates

At launch the app asks `api.github.com/repos/Decryptu/pokeldn/releases/latest` for the newest stable
release, in the background with a 5 s timeout. A tag above the app's `pokeldn.__version__` adds an
Update entry to the sidebar. It opens a dialog with the release notes and either Update now or
Download.

Update now (`pokeldn.app.update`) installs the release in place:

1. Download this computer's archive (`pokeldn-macos-arm64.zip`, `pokeldn-windows-x64.zip`,
   `pokeldn-linux-x64.tar.gz`) and the release's `SHA256SUMS` into the data folder's `update/`.
2. Refuse the archive unless its SHA-256 matches the line `SHA256SUMS` gives for its name.
3. Unpack it: `ditto -x -k` on macOS, which keeps the bundle's symlinks and modes; `tarfile` with
   the `data` filter on Linux; `zipfile` on Windows.
4. Start the new app as a helper, `pokeldn --apply-update NEW TARGET PID VERSION`
   (`gui/updating.py`). Its small "Updating pokeldn" window touches `update/helper.ready`; the old
   app quits on that file, or after 15 s without it, so one window is always on screen.
5. The helper waits for the old app's process to end (120 s), then on Windows for every process
   whose executable lies in the installed app (the PKHeX service) and terminates any left after
   10 s. It renames the installed app to `.<name>.old` beside it (retrying for 30 s while Windows
   releases the folder), copies the new app into its place, deletes the old copy and opens the new
   app. Any failure puts the old app back and opens it. The swap runs whether or not the helper's
   window came up.
   The helper runs from the unpacked copy's folder: Windows refuses to rename a folder that is any
   process's working folder, and Explorer starts the app with its own folder as one.
6. The app that opens reads `update/outcome.json` once: "pokeldn updated to X", or a dialog saying
   why the old app stayed. Removing the file closes the helper (it gives up after 60 s); the app
   then removes the unpacked copy once the helper's process has ended, and any `.old` folder.

A download made by the app carries no quarantine attribute (macOS) or Mark of the Web (Windows), so
neither Gatekeeper nor SmartScreen asks again. `SHA256SUMS` comes from the same GitHub release as the
archive: the check catches a corrupted or truncated download and does not authenticate the release.

| situation | behaviour |
|---|---|
| pre-release or draft, or a tag that is not `vX.Y.Z` | not offered |
| no network, HTTP error, reply that is not a release | nothing shown at launch; Check now says GitHub did not answer |
| Settings, Updates off | no request at launch; Check now still asks |
| no archive for this computer, or no `SHA256SUMS` in the release | Download opens the file or the release page |
| a source checkout, a macOS app run from Downloads (App Translocation), a folder the user cannot write | Download, with the reason |
| a session, flash or cleanup running | Update now asks to finish it first |
| checksum mismatch or a failed download | nothing changes; the dialog offers Download |

Settings, keys and received Pokemon live outside the app and stay. Whether macOS asks for App
Management permission when the helper replaces an app in `/Applications` is unmeasured; a refusal
leaves the old app in place and the dialog names the error.

The request carries no user data. GitHub allows 60 unauthenticated requests per hour per address.
`POKELDN_UPDATE_URL` replaces the endpoint, for tests (`tests/test_app_update.py`).

## File drops

Files dragged from the desktop land on these targets:

| target | takes |
|---|---|
| a trade's Pokemon to offer | a Pokemon file (imported as Or use a Pokemon file does) or a `.txt` of Showdown sets (read as Import paste); further files go to the following trades |
| Add a trade | one new trade per file, filling untouched trades at the end first, up to the session's limit |
| the Gift card of a Mystery Gift tool | a `.pokegift`, or a `.wc8` (Sword/Shield) or `.wc3` (FireRed/LeafGreen) card; it switches to Open a file |
| the Board page's Firmware card | a pokeldn `.bin`, installed after a confirmation |
| any path field, the welcome dialog | the file the field asks for; a folder field takes a dropped file's folder |

Flet 1.0.2's desktop client takes no file drops. `scripts/build_client.py` checks out Flet's source
at the installed version, adds `gui/flet_drop` (a Flet extension around
[desktop_drop](https://pub.dev/packages/desktop_drop)) to its client, and builds it into
`gui/client/<platform>`. `gui/drop.py` declares the matching `FileDrop` control. `gui/main.py` runs
that client when it is built and otherwise runs Flet's own, where no target is shown; a frozen app
always carries the built one. The script needs Flutter, at the version
`python -m flet_cli.cli --version --json` names (3.44.8 for Flet 1.0.2). It raises the macOS client's
deployment target from 11.0 to 12.0: Xcode 27 builds nothing older. The Linux client is Flet's light
flavor, as Flet's own CI builds it.

## Run from source

For source development, install Python 3.13 and the .NET 10 SDK:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r gui/requirements.txt
dotnet build -c Release services/pkhex -warnaserror
python scripts/build_client.py    # optional: file drops; needs Flutter
python gui/main.py
```

A source checkout has no firmware image (`gui/firmware` is build output). The Board page's Download
the firmware takes every known image from the newest non-draft release that carries the classic
ESP32 image and `SHA256SUMS`, checks each against that release's `SHA256SUMS`, and writes them only
when all match. A release that predates a chip carries no image for it. An image from an
older release than the checkout can carry an older serial protocol; the board check then reports the
firmware as out of date.

## Build a desktop app

To package an app, install ESP-IDF v6.1 for `esp32`, `esp32s3`, `esp32c3` and `esp32c6` and activate its
environment. Build the four radio images with separate configurations, and the controller image
(`firmware/pad`, which fetches `espressif/esp_tinyusb` through the component manager):

```sh
mkdir -p gui/firmware
POKELDN_IMAGES="$PWD/gui/firmware"
cd firmware/esp32
idf.py -B build/esp32 -D SDKCONFIG="$PWD/build/esp32/sdkconfig" set-target esp32
idf.py -B build/esp32 -D SDKCONFIG="$PWD/build/esp32/sdkconfig" build
idf.py -B build/esp32 merge-bin -o "$POKELDN_IMAGES/pokeldn-radio.bin"
idf.py -B build/esp32s3 -D SDKCONFIG="$PWD/build/esp32s3/sdkconfig" set-target esp32s3
idf.py -B build/esp32s3 -D SDKCONFIG="$PWD/build/esp32s3/sdkconfig" build
idf.py -B build/esp32s3 merge-bin -o "$POKELDN_IMAGES/pokeldn-radio-s3.bin"
idf.py -B build/esp32c3 -D SDKCONFIG="$PWD/build/esp32c3/sdkconfig" set-target esp32c3
idf.py -B build/esp32c3 -D SDKCONFIG="$PWD/build/esp32c3/sdkconfig" build
idf.py -B build/esp32c3 merge-bin -o "$POKELDN_IMAGES/pokeldn-radio-c3.bin"
idf.py -B build/esp32c6 -D SDKCONFIG="$PWD/build/esp32c6/sdkconfig" set-target esp32c6
idf.py -B build/esp32c6 -D SDKCONFIG="$PWD/build/esp32c6/sdkconfig" build
idf.py -B build/esp32c6 merge-bin -o "$POKELDN_IMAGES/pokeldn-radio-c6.bin"
cd ../pad
idf.py -B build -D SDKCONFIG="$PWD/build/sdkconfig" set-target esp32s3
idf.py -B build -D SDKCONFIG="$PWD/build/sdkconfig" build
idf.py -B build merge-bin -o "$POKELDN_IMAGES/pokeldn-pad-s3.bin"
cd ../..
python scripts/build_client.py
python scripts/build_unicorn.py
python scripts/pack_app.py
```

The absolute output paths keep the images in `gui/firmware`. The packer requires all five images,
the client from `scripts/build_client.py` and the Unicorn from `scripts/build_unicorn.py` (needs CMake); the frozen app check verifies all are included and
that the bundled client carries `flet_drop`. The release workflow builds each target separately
and supplies all five images to every desktop packer.

The app version is `pokeldn.__version__`. It appears in Settings and in the macOS and Windows
package metadata. Update it and `.github/release-notes.md` together before preparing a release.
The workflow produces `SHA256SUMS` for the three desktop downloads and five firmware images.
Manual workflow runs produce artifacts; `v*` tags publish a release named `pokeldn vX.Y.Z` with
`.github/release-notes.md` as its body, whose first line must be `# pokeldn X.Y.Z` (the workflow and
`tests/test_release.py` check it), and with the same nine files every time.
Only tags with a hyphen, such as `v0.3.0-rc1`, are marked as pre-releases; GitHub shows the
newest other release as Latest in the repository sidebar.

The apps are one-folder PyInstaller builds: `pokeldn.app` on macOS, a `pokeldn` folder holding
`pokeldn` or `pokeldn.exe` and `_internal` on Linux and Windows. A single file unpacks its whole bundle (about 180 MB) to a temporary folder at every launch, and every
run is the app relaunching itself, so a run paid it again. On an M4 the one-folder app reaches the
Games page in 0.7 s instead of 2.9 s, and a run's process starts in 0.08 s instead of 1.5 s. Flet's
packer refuses `--onedir` on macOS; `scripts/pack_app.py` passes it to PyInstaller after Flet's own
`--onefile`, and the later flag wins. The bundle's Python process never checks in with the Dock: as a
foreground app it shows a second icon that bounces until the app quits. The packer sets
`LSBackgroundOnly` in its `Info.plist`, so only the viewer has a Dock icon, as under the single-file
bootloader.

| part | size | what keeps it small |
|---|---|---|
| Flet viewer (`scripts/build_client.py`) | 31 MB, 9.4 MB as the macOS archive | no optional Flet extension (video, maps, camera, webview and the rest; the app draws core controls only), on macOS only the build machine's architecture, Dart symbols split out (`--split-debug-info`), and on macOS an xz archive |
| Unicorn (`scripts/build_unicorn.py`) | 3 MB | the installed release built from source with the ARM and ARM64 engines only; the wheel's library carries every CPU family (16 MB) |
| PKHeX helper (`services/pkhex`) | 16 MB | full trimming: framework and PKHeX.Core code the helper never reaches is dropped; EventSource, debugger and hot-reload support are off |
| Python | 8 MB of modules | the packer excludes Flet's web server, auth and image extras (`flet_web`, FastAPI, Uvicorn, Pydantic, httpx, Pillow), pytest, Pygments and rich's syntax, Markdown and traceback modules, `multiprocessing`, `_pydecimal`, and on macOS the East Asian codecs; macOS libraries lose their local symbols (`strip -x`) |

Trimming turns off reflection-based JSON in .NET; the helper's replies need it, so the project turns it
back on (`JsonSerializerIsReflectionEnabledByDefault`). Without it every command answers
`JsonTypeInfo metadata for type 'System.String' was not provided`. The Gen 3 event table is internal to
PKHeX.Core and read by name; a `DynamicDependency` attribute keeps it through trimming.

The macOS packer writes the viewer as xz under Flet's file name `flet-macos.tar.gz` (9.4 MB instead of
13.6 MB); flet_desktop 1.0.2 opens that file with mode `r:gz`, so the frozen app hands flet_desktop a
`tarfile` whose `open` detects the compression (`gui/flet_client.py`). The executable and the PKHeX
helper are never stripped: both carry an archive after their Mach-O image. Flet's macOS project runs
`dart run rive_native:setup` on every build; with Rive gone that step fails, so the client build
replaces it with `exit 0`.

The viewer is unpacked once per build into `~/.flet/client/flet-desktop-full-<version>-<fingerprint>`,
and Flet never removes an older build's folder. At each launch the frozen app marks its own folder
with `pokeldn-drop` and removes the other folders carrying that marker or, from earlier macOS builds,
a `pokeldn.app` (`gui/flet_client.py`); another Flet app's viewer stays.

Flet 1.0.2's packer re-signs the macOS viewer without its existing entitlements. The packaging
wrapper in `scripts/pack_flet.py` retains them when signing the viewer after its metadata changes.
The frozen check reads the sealed `com.apple.security.files.user-selected.read-write` entitlement
from the embedded viewer; without it, choosing `prod.keys` raises `ENTITLEMENT_NOT_FOUND`.

The Linux bootloader sets `LD_LIBRARY_PATH` to the bundle folder, which carries the build
machine's `libstdc++.so.6` (Ubuntu 22.04). Loaded first, it leaves Fedora 44's Mesa with no EGL
client extensions, and the Flet viewer aborts in libepoxy (`No provider of eglGetPlatformDisplayEXT`).
`pokeldn/app/paths.py` restores the user's `LD_LIBRARY_PATH` for every program the app starts, and
sets `FLET_LINUX_DISTRO` to the bundled viewer's build: Flet otherwise picks a viewer by glibc and
downloads one the bundle does not carry. The frozen check asserts both on Linux.

The app bundles Unicorn for Check offline. It loads its architecture modules by name, so the
packer collects its submodules and adds the ARM-only library to `unicorn/lib` itself, under the wheel's
file names; the frozen check asserts ARM64 is there and x86 is not. PyInstaller's Windows bootloader
is linked with Control Flow Guard (DllCharacteristics `0xC160`), and Unicorn ends a CFG process
with `0xC0000409` on its first `uc_mem_map`
([unicorn#2281](https://github.com/unicorn-engine/unicorn/issues/2281)); a 64 MiB thread stack
does not change it. The packer clears `GUARD_CF` in `pokeldn.exe`, giving `0x8160`, the flags of
`python.exe`. The frozen check runs a payload under Unicorn on every platform. Unicorn raises and
handles an access violation of its own there: never enable `faulthandler` in the frozen check, it
logs that exception to stderr and fails the check.

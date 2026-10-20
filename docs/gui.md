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

## First launch

The checkerboard covers the whole window, the transparent header included; the navigation rail
floats on it as a glass panel like the others. The header has no visible app title and supports dragging and double-clicking
to maximize or restore. macOS retains its native window buttons; Windows and Linux use buttons
in the app header. The integrated header has been visually checked on macOS; Windows and Linux
window-manager behavior remains unverified.

- macOS: the app is unsigned. Open it once and close the warning, then open System Settings →
  Privacy & Security → Security → Open Anyway next to pokeldn. Confirm with your password.
  Later launches open normally.
- Windows: extract the zip and run `pokeldn.exe` inside the `pokeldn` folder. Keep `_internal`
  beside it. If SmartScreen blocks the app, choose More info → Run anyway.
  See [Windows USB drivers](#windows-usb-drivers) if the board has no COM port.
- Linux: install GTK 3 and libsecret if your distribution does not include them. Serial access
  needs `sudo usermod -aG dialout $USER` (`uucp` on Arch); log out and back in after changing groups.
  See [Linux serial ports](#linux-serial-ports) for missing ports and brltty conflicts.

## Android setup requirements

The [Android app](../examples/android/README.md) is this interface on a phone. Its Board page
follows the table below; it reads the USB state again when a board is plugged or unplugged, when
Android's USB prompt closes and when the player returns from Settings. A native-USB board
(`303a:1001`) opens the app when plugged in. On the tested OnePlus CPH2621, enabling the phone's OTG
connection setting powered and enumerated the connected ESP32C6 without replugging the cable.

| detected state | required guidance |
|---|---|
| No compatible USB device | Check the data-capable cable and connection; show relevant USB host or OTG setting instructions for the phone, including OnePlus's OTG connection toggle. Device absence alone cannot identify which check failed. |
| Device present, USB permission missing or denied | Explain the Android USB access prompt and provide an explicit retry. |
| Permission granted, board handshake fails | Check the board connection and supported radio firmware; show the actual error. |
| Board answers the handshake | Show the detected board and firmware, then allow the game workflow to continue. |
| Board disconnects or the user returns from Settings | Refresh detection and permission state, update the guidance and resume setup when the board is ready. |

A classic ESP32 on a Silicon Labs CP210x bridge (`10c4:ea60`) is driven through the bridge's vendor
requests (`UsbStream.java`); one seen through a CH34x or FTDI bridge is named as one the phone app
cannot drive. PKHeX runs on the phone, compiled for Android. The received Pokemon is saved
through Android's file picker.

Settings guidance uses verified manufacturer-specific paths or searchable setting names, with
a Settings shortcut where Android supports it. The flow presents the relevant next action and
keeps setup progress visible. Developer tooling such as ADB and wireless debugging remains
separate from user setup.


On Android "Open the folder" saves a zip of the folder where the player picks, and file choosers are
Android's own.

## iOS setup

The [iOS app](../examples/ios/README.md) is this interface on an iPhone or iPad, installed with
AltStore or SideStore. An iPhone cannot open a USB serial device, so the app reaches the board over
Bluetooth: the board runs the **Bluetooth wireless** firmware, installed once from the desktop app's
Board page (`pokeldn-radio-ble-c6.bin` for an ESP32-C6, `pokeldn-radio-ble.bin` for a classic ESP32),
and needs USB only for power. The Board page lists it as "Bluetooth radio" once the phone has
connected; the first launch asks for Bluetooth access. While the phone holds the board, the board
answers nothing on its USB cable: close the iOS app before using the board from a computer or an
Android phone. File choosers are iOS's own and copy the chosen file into the app; the app's files
are under Files, On My iPhone, pokeldn.

## Phones

Below 760 points wide the app shows its pages through a bottom tab bar and each page's panels one
at a time, picked on a switcher above them: Games, Options and Session on the Games page; choosing
a tool brings its options forward and Start brings the session. Dialogs take the screen's width.
The Control and Update pages are absent on Android and iOS.

## App language

Settings, App language lists English and installed community language packs. Choosing a pack enables
it; restart the app to apply the choice. Missing strings fall back to English. Trainer language
controls built Pokemon separately. [Language packs](plugins.md#language-packs-15) describes the
package format and translator template. The desktop app ships English defaults only. The bundled [Noto Sans CJK SC](https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese) fallback font
covers Chinese, Japanese and Korean text offline; its SIL Open Font License is in
`gui/assets/fonts/LICENSE`.

## Your trainer

Settings, Your trainer is the original trainer of every Pokemon the app builds: a name, a gender, a
language and two ID pairs, entered as the games show them. Legends Z-A takes a received Pokemon as its
player's own only when the original trainer's gender, IDs and name match
([the received record](za.md#what-the-trade-writes-into-a-received-record)). Legends Arceus's data
exchange record carries that gender and a look that matches it
([the record](pla.md#the-games-reader-and-the-pre-handler-phase)); on retail trades the screen
showed the partner's gender nowhere. A record stores the trainer as a
16-bit TID and a 16-bit SID, the low and high halves of one 32-bit id.

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
| a Pokemon is banked | its `.json` keeps the species, the summary, PKHeX's verdict, the source file, a SHA-256 of the bytes, a random 63-bit HOME tracker for a move under "made", and `home_tracker`: `empty`, `made` or empty |
| the page lists the destinations | the helper's `destinations` command tries a move to all seven games and reports each refusal |
| a destination's trade tool is chosen | the helper's `move` command converts the record, the result joins that tool's offer queue with `"bank": id`, and the app opens the tool |
| the run's trade N completes | the `[done] trade N complete` line removes the banked Pokemon queued as trade N; at the run's end its queue entry goes too |
| the run fails or is stopped first | the Pokemon stays in the bank and in the queue |

A move goes through PKHeX's own HOME conversion (`EntityConverter.ConvertToType`, through `PKH`), then
PKHeX's legality check in the destination game; a move that is not legal there is refused with
PKHeX's reason, its per-move lines folded into one ("2 of its moves are not legal") and each problem
listed once. On the way:

- A Pokemon from another game gets the HOME tracker the [HOME tracker
  setting](#the-home-tracker-setting) asks for: none, or the bank's.
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

### The HOME tracker setting

PKHeX marks a Pokemon invalid when it lacks a HOME tracker it needs (`HomeTrackerUtil.IsRequired`,
`LegalityCheckResultCode.TransferTrackerMissing`, severity `HOMETransferTrackerNotPresent`): one moved
into another game, and an event gift that reached its game only through HOME. HOME 3.1.0 and later refuse
a tracker HOME did not issue (error 10015). Settings, advanced settings, HOME tracker picks what the app
puts there (`Settings.home_tracker`); `pokeldn.pokemon.Service` sends it as `home_tracker` with every
helper request, and a run inherits it as `POKELDN_HOME_TRACKER`.

| setting | bank move, import, and the builder's gift repair | legality | warning shown |
|---|---|---|---|
| `empty` (default) | the tracker stays unset | accepted when PKHeX finds the record legal with a tracker; any other problem is refused | PKHeX flags the missing HOME tracker |
| `made` | a random 63-bit tracker, the bank's for a banked Pokemon | unchanged | Can't be deposited in HOME |

Every helper reply carries `home_tracker` (`empty`, `made` or empty), and `destinations` gives it per
game. The warning shows on a built or loaded offer, a bank entry, a bank destination and an import line.
PKHeX 26.8.26 conditions other checks on a tracker being present: without one it lets no evolution happen
in another HOME game (`EvolutionGroupHOME.CheckAllAdjacent`), so a Pikachu hatched as a Pichu in Scarlet
reads as an impossible evolution in Sword/Shield, and Legends Z-A keeps the ability HOME realigned only on a
tracked record (`AbilityVerifier.VerifyBirthAbility`, the Black 2 Patrat's Hidden Ability in
`tests/data/bank_import.json`). Under `empty` the helper judges such a record on a copy that carries a tracker
and what HOME changes on a Pokemon it has seen (`ValidWithTracker`); the record itself keeps none.

Mystery Gift - Simulated follows the setting too ([Mystery Gift - Simulated](#mystery-gift---simulated)).
Among the gifts, PKHeX wants a tracker only on one HOME gave: under `empty` its copy has none, under
`made` a made one (`MendGift` in `services/pkhex/Program.cs`). A made tracker comes with what HOME
changes on a Pokemon it has seen, which PKHeX's check expects of one with a tracker
[HomeQuirks]:
a Scarlet/Violet Pokemon's height is its scale, a Legends Z-A one's height and weight, and a Legends Z-A
Alpha carries the Alpha mark (`HomeSeen`). PKHeX.Core 26.8.26 holds 16 such gifts for Sword/Shield, 4
each for Brilliant Diamond/Shining Pearl, Legends Arceus and Legends Z-A, and 5 for Scarlet/Violet, and
every gift passes the check under either setting. The Sword/Shield Mystery Gift sends its 16 as the
community's cards (Official events, Pokemon HOME): the console makes the Pokemon, so it never carries a
tracker, whatever the setting ([Pokemon HOME](swsh_gift.md#pokemon-home)).

### Importing

The Bank page's plus button, or a file dropped on its grid, imports a Pokemon file or a game save. The
helper's `import` command reads the file with PKHeX: `SaveUtil.TryGetSaveFile` first, the file name
helping (a 3DS save is a file named `main` with no extension), then `FileUtil.TryGetPKM` for a single
record of any format PKHeX knows (`.pk1` to `.pk9`, `.pb7`, `.pb8`, `.pa8`, `.pa9`, `.ck3`, `.xk3`,
`.bk4`, `.rk4` and the rest). A save gives each occupied party slot, then each occupied box slot. The
file is only read.

| record | what the bank keeps |
|---|---|
| of a game the bank holds (`PK3`, `PB7`, `PK8`, `PB8`, `PA8`, `PK9`, `PA9`) | the record as it is, held item and moves included, when PKHeX finds it legal |
| any other format | the record with its held item taken off, as a Pokemon enters HOME without one, and, in a Gen 3 or Gen 4 record, its HM moves forgotten, as Pal Park and Poke Transfer refuse them; when PKHeX then finds it legal, it moves as a bank move would to the first game that takes it, in the order FireRed/LeafGreen, Scarlet/Violet, Sword/Shield, Brilliant Diamond/Shining Pearl, Legends Arceus, Legends Z-A |

A record PKHeX finds not legal in its own format is refused with PKHeX's reason; the move's moveset
suggestion never stands in for a move the record's own game did not allow. A record with a bad checksum,
an egg of another game and a species no reachable game holds are refused too. The `.json` of an
imported Pokemon carries `imported`: the file name, the slot, the source format and what was taken off.

`Bank/.imported` holds one key per imported record: the SHA-256 of its decrypted stored bytes, before
anything is taken off. A record whose key is there is not imported again, even once a trade has taken it
out of the bank; a record whose bytes are already banked is not banked twice. A save imported again after
the game was played brings in only the records that changed.

A Ditto imported from a FireRed save completed a trade into a retail Scarlet from the Bank page, and
importing that save again banked none of its 104 records.

A record received from a retail Sword and moved to Legends Z-A, with the bank's tracker and its PID
kept, showed its level and original trainer on a retail Z-A's trade box and completed the trade.

`tests/test_bank.py` moves records between six pairs of games through the real helper and checks
that the destination's launcher takes them, along with each refusal, an edit kept and refused, and the
run that takes a traded Pokemon out of the bank. It imports a Black 2 save, a Gen 4 and a Gen 6 file built by
PKHeX's encounter generator (`tests/data/bank_import.json`): the held item and the HM go,
an illegal record is refused, and a second import banks nothing.

### Unresolved

- Whether Pokemon HOME accepts a Pokemon the bank moved with a made tracker. HOME 3.1.0 and later
  refuse a tracker HOME did not issue (error 10015), and a made tracker is of that kind.
- Whether HOME accepts an empty tracker on a Pokemon moved into a different game.
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

Pokemon images come from [PokeAPI](https://github.com/PokeAPI/sprites) and are downloaded on demand.
Downloaded images are cached in `sprites/` in the app's data folder and remain available offline.

Settings, Pokemon sprites disables downloads; cached images still appear. The same settings section
has a button to clear the sprite cache.

An unavailable species or form shows a placeholder. If a shiny image is unavailable, the normal
image of the same form is shown. Missing images do not prevent building or trading Pokemon.

## Raid events

The Scarlet/Violet Tera Raid (Host) tool's Raid event card hosts a raid from Project Pokemon's
[EventsGallery](https://github.com/projectpokemon/EventsGallery) ([Event raids](sv_raid.md#event-raids)).
The app keeps its own copy of the gallery's raid events in `EventsGallery/` in its data folder
(`pokeldn.app.events_gallery`); Clear local files leaves it.

| action | what happens |
|---|---|
| Download | asks `api.github.com` for the newest commit of master that changed `Released/Gen 9/SV/Raid Events`, downloads `codeload.github.com/projectpokemon/EventsGallery/zip/<commit>` (22 MB, October 2026) and unpacks each event's four tables of its newest patch, about 17 MB; `gallery.json` keeps the commit and its date |
| Check for updates | one request for that newest commit; an update when it differs from the copy's. A change elsewhere in the gallery is none |
| Update | the download again |

A new copy replaces the old one only once complete; a failed or cancelled download leaves the old
one. An event's folder name reaches 152 characters, so on Windows the app opens the files as `\\?\`
paths.

The event list holds every event of the copy but `000 Base Data`, the game's own table: 152 on
2026-09-06, newest first, the arrow beside it turning the order. Each entry is the folder's name
without its number (a round, "Event · Round") over its bosses; typing filters on both. Choosing one:

- The raid card offers the game versions the event spawns in, Paldea alone, the progresses at which
  the chosen crystal draws, and in place of Crystal the event's crystals for that version, each a
  delivery group with its stars and bosses ("7 stars: Charizard", "4-5 stars: Florges, Mimikyu"). A
  value the event cannot spawn moves to the nearest one it can (`raid_event.constrain`).
- Find a raid searches the event's crystals only, one progress per stage, with its bosses as
  species, and its Rewards section offers the items and quantities of the event's own reward tables
  ([Finding a seed](sv_raid.md#finding-a-seed); `gui/views/reward_filter.py`). Its Size mark
  eligibility greys out a mark no boss of the chosen crystal, stars and species can take
  ([Size marks](sv_raid.md#size-marks)).
- An event with a boss a save catches once shows "Let it be caught again" (`--raid-catch-normal`),
  unchecked at each launch and for each event chosen ([Event raids](sv_raid.md#event-raids)).

Folding the card sets its event aside (`#raid-event-folded` in the tool's values,
`GamesView.show_raid_event`): the raid card, Find a raid and the command are a standard raid's, and
the header reads "Off: Event". Unfolding brings the event back. The card opens at launch when an
event is in use. An event the copy lacks (not downloaded, or an update dropped it) stays chosen: the
header reads "Missing: Event" in red, and the run refuses it until the copy has it or another event
is chosen (`pokeldn.app.command.code_error`).

## Hosted raid rewards

The Tera Raid (Host) tool's Rewards card offers training items, Tera Shards (Stellar included),
Herba Mystica, treasure and balls as templates. Choosing a bundle replaces the current reward rows.
Quantity each changes every row in that bundle, from 1 to 999. Editing an item or an individual
quantity switches to Custom rewards; rows can be added or removed, up to 45. Incomplete rows or
invalid quantities prevent a launch. The saved selection keeps the items and quantities.

Raid's own rewards clears the overrides and uses the selected raid's reward tables
([Hosting](sv_raid.md#hosting); `gui/views/rewards.py`).

## Raid NPC partners

The Tera Raid (Host) tool's Raid NPC partners card, below Consoles joining, chooses the NPC trainers
who fill the slots the consoles leave empty: two with one console joining, one with two, none with
three ([Partners](sv_raid.md#partners); `gui/views/raid_partners.py`). With nothing chosen it passes
nothing, and the host draws them from the story progress's pool as a console does.

- Partners' progress: the five unlock stages, Beginning left out, starting on the story progress's
  (six stars for a black crystal or a seven-star event raid). Another stage passes
  `--raid-partner-progress`.
- The stage's trainers, three cards to a row, two in a narrow window. A card shows the trainer and
  the Pokemon, its level (four fifths of Our Pokemon's, `command.raid_pokemon_level`) and Tera type
  as chips, then its ability and its three moves, one to a line. A partner raiders favour ends on a
  strip tinted gold or silver with a star and why ([Favoured partners](sv_raid.md#favoured-partners));
  its tooltip says why at more length.

A click seats a trainer, numbered by the slot it takes; a second click leaves the slot to the draw.
Each pick passes `--raid-partner`, in order. Raising Consoles joining drops the last pick, and a
pick the chosen stage lacks (Dylan or Luke below four stars) is dropped. Folding only hides the card
(`GamesView.show_raid_partners`): the choice still goes to the raid, and the header names it.

## Union Circle

Scarlet/Violet's two Union Circle tools join the circle a console hosts under a four-digit Link Code
([Union Circle](sv_union_circle.md)). A circle's code is new each time, so the field starts empty at
every launch (`Field.remembered`).

- Union Circle - Quests: Task unlocks every remaining Snacksworth legendary or gives BP;
  the BP field takes 1 to 9,999,999 (`Field.bounds`). The console steps follow the task chosen: a
  step given as `(text, (flag, value))` shows only while that field has that value
  (`command.steps`). A Snacksworth run draws a bar of the host's clears against those it lacked
  ([Progress](#progress)).
- Union Circle - Encounters: the Pokemon to spawn card (`gui/views/encounter.py`, field kind
  `encounter`) sets the species, shiny, form, level, Tera Type, nature, gender, ability, held item,
  scale and IVs. Nature, ability, scale and IVs left empty are drawn as the host's own wild ones
  are. A new species resets the fields below it. With Legal encounters only, on by default, the card
  offers the species, forms and levels PKHeX's wild slots give and the Tera Types PKHeX accepts
  somewhere, and lists every location where PKHeX accepts the spawn caught, or why it accepts it
  nowhere. The card passes `--spawn` and the `--spawn-*` flags (`command.encounter_args`).

A built-in run's `[panel]` cards ([Status cards](plugins.md#status-cards-18)) show at the top of its
tool's options while it runs, and only there (`GamesView.show_run_cards`); they go when the run
ends. The encounters run shows its area search this way.

A circle run's log keeps to what a user follows: the join, the host's totals, the BP clear, the
spawns coming out or being battled, and the host's area found or lost. `--verbose-circle` (in the
Advanced tab's Advanced options) adds every circle message sent and each step of the area search.

## Mystery Gift - Simulated

The Mystery Gift - Simulated tool's card, on Let's Go, Brilliant Diamond/Shining Pearl, Legends
Arceus, Scarlet/Violet and Legends Z-A, lists the game's gift Pokemon from PKHeX's event table
([Simulated Mystery Gifts](gift_simulated.md#the-gifts); `gui/views/event_gifts.py`). Tiles go two
to a row, newest first: a sprite, the card's title, then the Pokemon, whose it is and when it was
given; a hover shows the moves. Twenty-four show at a time, Show more adds as many, and a search
narrows them by any word a tile shows, the ball, a move or the card number. Ten tiles or fewer show
whole; more scroll in a box of their own (`event_gifts.FIT`).

A click makes a fresh copy for the trainer in Settings and appends it to the queue above the list,
with its legality, moves and OT. Up to six gifts trade in order in one hosted session. The same
event can be picked several times; each pick makes its own copy. Remove a queued gift with its
close button before Start. A full queue holds further picks off until a gift is removed.
A copy keeps the trainer it was made with: remove it and pick the gift again after changing the trainer.
A gift that names its receiver but
never reached saves in the trainer's language, such as Let's Go's Chinese Meltan and Melmetal for any
other, has an illegal tile that says why, and a click on it says so and keeps the offer
([Saves a card reached](gift_simulated.md#saves-a-card-reached)). With Made for the receiving player
(Advanced tab) on, the default, the trade makes a gift that names its receiver again for the console's own save
([Made for the receiving player](gift_simulated.md#made-for-the-receiving-player)). A gift with its
card's own trainer goes as made. While every queued gift goes as made, the switch is off, disabled
and faded, and the note under it says why (`command.locked`). The launch then passes no
`--for-receiver`. A queue containing a gift that can name its receiver gives the switch back as it
was set; the host applies it to each eligible card.

A gift HOME gave, on any game but Let's Go, has the tracker the HOME tracker setting gives it
([The HOME tracker setting](#the-home-tracker-setting)). Its tile is outlined in amber and, as the
chosen copy, shows the setting's warning: "PKHeX flags the missing HOME tracker" or "Can't be
deposited in HOME". The trade offers it like any other
([The copy a trade offers](gift_simulated.md#the-copy-a-trade-offers)).

## Private logs

Settings, Hide personal details in logs (on by default) masks, in the session and board logs the app
shows and copies (`pokeldn/app/redact.py`):

| masked | shown instead | kept |
|---|---|---|
| the home folder in a path (`/Users/NAME`, `/home/NAME`, `C:\Users\NAME`) | `~` | the rest of the path |
| the iOS app container (`/var/mobile/Containers/Data/Application/UUID`) | `<app>` | |
| the device half of a MAC address, with or without colons | `**:**:**`, `******` | the vendor half (Nintendo, Espressif) |
| a quoted value (`'…'`, `"…"`, `b'…'`) after `ot_name`, `ht_name`, `OT`, `nickname`, `trainer`, `player` or `name` | `***` | `POKELDN` and `PKLDN` in any case, the program's own names |
| a value after `TID`, `SID`, `tid`, `sid`, `trainer_id` | `***` | |
| a trainer name seen once, and the trainer name from Settings, wherever it appears again in the run, as a whole word | `***` | |

A nickname is masked where it stands and nowhere else: it is often the species' own name. Session
records (`captures/`) carry the raw messages and are not masked. Local link addresses (`169.254.x.x`,
`127.0.0.x`) identify nobody and stay.

## Pop-ups

A run the app started, another of its child processes, or the app's own code can put a pop-up over
whatever page shows (`pokeldn.popup`, in the plugin API since 1.2). There are three kinds:

| kind | buttons | callback |
|---|---|---|
| `acknowledge(title, text)` | one, `label` (OK) | `on_ack`: the button, Esc or a click outside |
| `confirm(title, text, agree, disagree)` | agree and disagree, the caller's labels | `on_agree`, `on_disagree` or `on_dismiss`, which Esc and a click outside fire |
| `choose(title, text, options)` (1.7) | one per option, 2 to 8, full width under the text in the caller's order | `on_choice(index)`, or `on_dismiss`, which Esc and a click outside fire |

Opening one never waits: it returns the pop-up's id, and the answer comes later as its callback. A
callback runs on the thread that reads the app's answers, unless `set_dispatcher(dispatch)` hands it to the program's own loop; in the app, it runs on a worker
thread so no callback stalls the window. A callback that raises prints its traceback.

| option | what it does |
|---|---|
| `id` | names the pop-up among the program's own; one opened under the id of a pop-up still open replaces it in place, its callbacks dropped. Without one, a new id is made |
| `tone` | `info`, `warning` or `error`, which pick the icon |

`cancel(id)` closes a pop-up; none of its callbacks fires once `cancel` has returned, except one an
earlier answer already handed to the dispatcher. A program holding 32
pop-ups unanswered gets `RuntimeError`. A pop-up's header names the program that opened it: the
tool, Board installer or Controller service, and nothing for the app's own.

When a program exits, its confirmations and choices close and its acknowledgements stay with no answer
to go back. With no app (`available()` is false, as in a terminal), a pop-up is a `[pop-up]` line in the
output, no answer comes, and it does not count toward the 32.

`runner.Process(..., popups=app.popups, label=...)` sets `POKELDN_POPUPS=1` in the child. The child
sends each pop-up as a `[popup]` line and a JSON object on stdout, which the app keeps out of the log
and finds wherever in a line another thread's print left it; the app answers with
`[popup] {"id", "n", "answer"}` on the child's stdin (a choice's answer is the option's index, `"0"`
to `"7"`), which `pokeldn.app.runner.child` reads. `n`
tells a pop-up from one opened again under its id, so a late answer to a replaced pop-up fires
nothing. Code in the app reaches the manager directly (`popup.attach`). `pokeldn.app.popups.Manager`
keeps the open pop-ups; `gui.popups.Dialogs` draws them. An app dialog's
`page.pop_dialog()` closes the app's own top dialog, never a pop-up opened above it.

## Progress

A run prints `[progress] DONE TOTAL UNIT TITLE` (`pokeldn.progress.show`, plugin API 1.7; `UNIT` is
`bytes` or `items`) to put a bar in the Session panel in place of a log line: the amount
(`1.05 of 5.20 GB`), the rate over the last 30 s and the time left. `show` prints at most four lines a
second per title and always the last one. A save backup's or restore's `[save]` lines draw the same bar.

Mystery Gift - Simulated raises a warning when a gift made for the receiving player goes with the
trainer from Settings instead, saying why: the save names no one, or its copy stopped at the card,
PKHeX, the offer check or the loader ([The trade](gift_simulated.md#the-trade)). There is one per
console (`receiver_gift.pop_up`), a newer reason replacing the one open. The app raises its own for
an update that did not install and for a plugin it turned off.

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
| a source checkout, a macOS app run from Downloads (App Translocation), a macOS or Linux folder the user cannot write | Download, with the reason |
| Windows, a folder the user cannot write (`C:\Program Files`) | Update now; Windows asks for administrator permission (UAC) before the helper starts, and a refusal leaves the app unchanged |
| a session, flash or cleanup running | Update now asks to finish it first |
| checksum mismatch or a failed download | nothing changes; the dialog offers Download |

On Windows in a folder only an administrator may change, the helper starts through
`ShellExecuteExW` with the `runas` verb, reads and writes its outcome beside the unpacked copy (an
administrator's helper may run as another user), and opens the new app through Explorer, so it runs at
the user's own level. `scripts/check_update.py ARCHIVE FOLDER` runs a packed app's own update against a
release served on 127.0.0.1; the Update check workflow runs it on Windows (a user folder and
`C:\Program Files`) and Linux from a Release run's archives.

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

## The docs page

The Docs page shows the app guide and every page of this site that its navigation lists. The search
field above the page list matches sections: each heading and the text under it, every word of the
query required. A word in a heading or a page title ranks first. Picking a result opens the page at
that heading; a link to `page.md#heading` scrolls the same way (`gui/views/docs.py`).

## Unreleased titles

A title prepared ahead of its Switch release appears in the Games list, the Bank and the Docs page
only when the app runs from a source checkout (`pokeldn/app/preview.py`). A packaged release is
frozen and carries no `.git`, so it never shows one. `POKELDN_PREVIEW=1` shows them anywhere;
`POKELDN_PREVIEW=0` hides them in a checkout. Its docs page sets `nav_exclude` and `search_exclude`.

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
export POKELDN_BLE=1   # the Bluetooth builds for the iOS app (hardware_esp32.md, Bluetooth)
BLE_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.ble"
idf.py -B build/ble -D SDKCONFIG="$PWD/build/ble/sdkconfig" -D SDKCONFIG_DEFAULTS="$BLE_DEFAULTS" set-target esp32
idf.py -B build/ble -D SDKCONFIG="$PWD/build/ble/sdkconfig" -D SDKCONFIG_DEFAULTS="$BLE_DEFAULTS" build
idf.py -B build/ble merge-bin -o "$POKELDN_IMAGES/pokeldn-radio-ble.bin"
idf.py -B build/ble-c6 -D SDKCONFIG="$PWD/build/ble-c6/sdkconfig" -D SDKCONFIG_DEFAULTS="$BLE_DEFAULTS" set-target esp32c6
idf.py -B build/ble-c6 -D SDKCONFIG="$PWD/build/ble-c6/sdkconfig" -D SDKCONFIG_DEFAULTS="$BLE_DEFAULTS" build
idf.py -B build/ble-c6 merge-bin -o "$POKELDN_IMAGES/pokeldn-radio-ble-c6.bin"
unset POKELDN_BLE
cd ../pad
idf.py -B build -D SDKCONFIG="$PWD/build/sdkconfig" set-target esp32s3
idf.py -B build -D SDKCONFIG="$PWD/build/sdkconfig" build
idf.py -B build merge-bin -o "$POKELDN_IMAGES/pokeldn-pad-s3.bin"
cd ../..
python scripts/build_client.py
python scripts/build_unicorn.py
python scripts/pack_app.py
```

The absolute output paths keep the images in `gui/firmware`. The packer requires the radio, Bluetooth radio and controller images,
the client from `scripts/build_client.py` and the Unicorn from `scripts/build_unicorn.py` (needs CMake); the frozen app check verifies all are included and
that the bundled client carries `flet_drop`. The release workflow builds each target separately
and supplies every image to every desktop packer.

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

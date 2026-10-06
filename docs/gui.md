---
title: Desktop builds
---
# Desktop builds

Released apps include PKHeX and merged radio firmware for ESP32, ESP32-S3, ESP32-C3
and ESP32-C6.
Users provide their own `prod.keys`.

Open the app and choose `prod.keys` in Settings. On the Board page, select the USB board to use
as the radio and flash its firmware. Choose a game and a tool, prepare a Pokemon or select a file,
then follow the console instructions and press Start. Received Pokemon are saved to the folder
chosen in Settings; the folder button beside Output opens it. Flash detects the chip and selects
its bundled image; a custom image is checked against that chip before writing. Connect an S3,
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
by saved tool settings and queues are kept. Received files and their selected folder, Switch keys,
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
Update entry to the sidebar; it opens the release notes or downloads this computer's archive from the
release (`pokeldn-macos-arm64.zip`, `pokeldn-windows-x64.zip`, `pokeldn-linux-x64.tar.gz`), or the
release page when none fits. The user replaces the app with the download; settings, keys and received
Pokemon live outside it.

| situation | behaviour |
|---|---|
| pre-release or draft, or a tag that is not `vX.Y.Z` | not offered |
| no network, HTTP error, reply that is not a release | nothing shown at launch; Check now says GitHub did not answer |
| Settings, Updates off | no request at launch; Check now still asks |

The request carries no user data. GitHub allows 60 unauthenticated requests per hour per address.
`POKELDN_UPDATE_URL` replaces the endpoint, for tests (`tests/test_app_update.py`).

## File drops

Files dragged from the desktop land on these targets:

| target | takes |
|---|---|
| a trade's Pokemon to offer | a Pokemon file (imported as Or use a Pokemon file does) or a `.txt` of Showdown sets (read as Import paste); further files go to the following trades |
| Add a trade | one new trade per file, filling untouched trades at the end first, up to the session's limit |
| the Gift card of a Mystery Gift tool | a `.pokegift`, or a `.wc8` (Sword/Shield) or `.wc3` (FireRed/LeafGreen) card; it switches to Open a file |
| Flash the firmware | a `.bin`, used as the custom image |
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
environment. Build all four images with separate configurations:

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
cd ../..
python scripts/build_client.py
python scripts/build_unicorn.py
python scripts/pack_app.py
```

The absolute output paths keep the images in `gui/firmware`. The packer requires all four images,
the client from `scripts/build_client.py` and the Unicorn from `scripts/build_unicorn.py` (needs CMake); the frozen app check verifies all are included and
that the bundled client carries `flet_drop`. The release workflow builds each target separately
and supplies all four images to every desktop packer.

The app version is `pokeldn.__version__`. It appears in Settings and in the macOS and Windows
package metadata. Update it and `.github/release-notes.md` together before preparing a release.
The workflow produces `SHA256SUMS` for the three desktop downloads and four firmware images.
Manual workflow runs produce artifacts; `v*` tags publish a release named `pokeldn vX.Y.Z` with
`.github/release-notes.md` as its body, whose first line must be `# pokeldn X.Y.Z` (the workflow and
`tests/test_release.py` check it), and with the same eight files every time.
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
| Flet viewer (`scripts/build_client.py`) | 33 MB | no optional Flet extension (video, maps, camera, webview and the rest; the app draws core controls only), and on macOS only the build machine's architecture |
| Unicorn (`scripts/build_unicorn.py`) | 3 MB | the installed release built from source with the ARM and ARM64 engines only; the wheel's library carries every CPU family (16 MB) |
| PKHeX helper (`services/pkhex`) | 18 MB | partial trimming: framework code PKHeX.Core never reaches is dropped |
| Python | | the packer excludes Flet's web server, auth and image extras (`flet_web`, FastAPI, Uvicorn, Pydantic, httpx, Pillow) and pytest |

Trimming turns off reflection-based JSON in .NET; the helper's replies need it, so the project turns it
back on (`JsonSerializerIsReflectionEnabledByDefault`). Without it every command answers
`JsonTypeInfo metadata for type 'System.String' was not provided`. Flet's macOS project runs
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

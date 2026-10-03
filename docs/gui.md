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
Sword/Shield also opens `.wc8` cards. Save gift file exports the selected gift without a board.
[Mystery Gift files](gifts.md#desktop-app) describes the forms, cartridge variants and native-format
conversion.

## Linux serial ports

The app opens the board as the user, with no root and no kernel networking: the v0.6.2 Linux bundle,
run by an unprivileged user in an amd64 Ubuntu 24.04 container, completed a retail Sword host trade
over a XIAO ESP32-C6. Opening the port needs the `dialout` group (`uucp` on Arch); a port the user
may not open fails with `EACCES`, and the Board page then names the group instead of a busy port.

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

## Pokemon sprites

The sprites are the 96x96 PNGs behind `sprites.front_default` and `sprites.front_shiny` of
`https://pokeapi.co/api/v2/pokemon/{id}`, read from `raw.githubusercontent.com/PokeAPI/sprites`
(`sprites/pokemon/{id}.png`, `sprites/pokemon/shiny/{id}.png`). The JSON is not fetched: it is 300 KB
per species, and the sprite path is fixed by the id. Twelve National Dex numbers sampled from 1 to 1025
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
release (`pokeldn-macos-arm64.zip`, `pokeldn-windows-x64.exe`, `pokeldn-linux-x64.tar.gz`), or the
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
python scripts/pack_app.py
```

The absolute output paths keep the images in `gui/firmware`. The packer requires all four images
and the client from `scripts/build_client.py`; the frozen app check verifies all are included and
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

Flet 1.0.2's packer re-signs the macOS viewer without its existing entitlements. The packaging
wrapper in `scripts/pack_flet.py` retains them when signing the viewer after its metadata changes.
The frozen check reads the sealed `com.apple.security.files.user-selected.read-write` entitlement
from the embedded viewer; without it, choosing `prod.keys` raises `ENTITLEMENT_NOT_FOUND`.

The Linux bootloader sets `LD_LIBRARY_PATH` to the unpacked bundle, which carries the build
machine's `libstdc++.so.6` (Ubuntu 22.04). Loaded first, it leaves Fedora 44's Mesa with no EGL
client extensions and the Flet viewer aborts in libepoxy (`No provider of eglGetPlatformDisplayEXT`).
`pokeldn/app/paths.py` restores the user's `LD_LIBRARY_PATH` for every program the app starts, and
sets `FLET_LINUX_DISTRO` to the bundled viewer's build: Flet otherwise picks a viewer by glibc and
downloads one the bundle does not carry. The Ubuntu 22.04 viewer runs on Fedora 44 under Wayland.
The frozen check asserts both on Linux.

The app bundles Unicorn for Check offline. It loads its architecture modules by name, so the
packer collects its submodules and adds the platform's library to `unicorn/lib` itself: PyInstaller's
library patterns match `lib*.so`, not Linux's `libunicorn.so.2`. PyInstaller's Windows bootloader
is linked with Control Flow Guard (DllCharacteristics `0xC160`), and Unicorn ends a CFG process
with `0xC0000409` on its first `uc_mem_map`
([unicorn#2281](https://github.com/unicorn-engine/unicorn/issues/2281)); a 64 MiB thread stack
does not change it. The packer clears `GUARD_CF` in `pokeldn.exe`, giving `0x8160`, the flags of
`python.exe`. The frozen check runs a payload under Unicorn on every platform. Unicorn raises and
handles an access violation of its own there: never enable `faulthandler` in the frozen check, it
logs that exception to stderr and fails the check.

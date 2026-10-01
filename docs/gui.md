---
title: Desktop builds
---
# Desktop builds

Released apps include PKHeX and merged radio firmware for ESP32, ESP32-S3 and ESP32-C3.
Users provide their own `prod.keys`.

Open the app and choose `prod.keys` in Settings. On the Board page, select the USB board to use
as the radio and flash its firmware. Choose a game and a tool, prepare a Pokemon or select a file,
then follow the console instructions and press Start. Received Pokemon are saved to the folder
chosen in Settings; the folder button beside Output opens it. Flash detects the chip and selects
its bundled image; a custom image is checked against that chip before writing. Connect an S3
or C3 through native USB Serial/JTAG. C6 and S2 chips are refused.

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

## Run from source

For source development, install Python 3.13 and the .NET 10 SDK:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r gui/requirements.txt
dotnet build -c Release services/pkhex -warnaserror
python gui/main.py
```

A source checkout has no firmware image (`gui/firmware` is build output). The Board page's Download
the firmware takes the three images from the newest non-draft release that carries them, checks each
against that release's `SHA256SUMS`, and writes them only when all three match. An image from an
older release than the checkout can carry an older serial protocol; the board check then reports the
firmware as out of date.

## Build a desktop app

To package an app, install ESP-IDF v6.1 for `esp32`, `esp32s3` and `esp32c3` and activate its environment.
Build all three images with separate configurations:

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
cd ../..
python scripts/pack_app.py
```

The absolute output paths keep the images in `gui/firmware`. The packer requires all three images;
the frozen app check verifies all are included. The release workflow builds each target separately
and supplies all three images to every desktop packer.

The app version is `pokeldn.__version__`. It appears in Settings and in the macOS and Windows
package metadata. Update it and `.github/release-notes.md` together before preparing a release.
The workflow produces `SHA256SUMS` for the three desktop downloads and three firmware images.
Manual workflow runs produce artifacts; `v*` tags publish a release named `pokeldn vX.Y.Z` with
`.github/release-notes.md` as its body, whose first line must be `# pokeldn X.Y.Z` (the workflow and
`tests/test_release.py` check it), and with the same seven files every time.
Only tags with a hyphen, such as `v0.3.0-rc1`, are marked as pre-releases; GitHub shows the
newest other release as Latest in the repository sidebar.

Flet 1.0.2's packer re-signs the macOS viewer without its existing entitlements. The packaging
wrapper in `scripts/pack_flet.py` retains them when signing the viewer after its metadata changes.
The frozen check reads the sealed `com.apple.security.files.user-selected.read-write` entitlement
from the embedded viewer; without it, choosing `prod.keys` raises `ENTITLEMENT_NOT_FOUND`.

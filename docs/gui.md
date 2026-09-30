---
title: Desktop builds
---
# Desktop builds

Released apps include PKHeX and merged radio firmware for ESP32 and ESP32-S3.
Users provide their own `prod.keys`.

Open the app and choose `prod.keys` in Settings. On the Board page, select the USB board to use
as the radio and flash its firmware. Choose a game and a tool, prepare a Pokemon or select a file,
then follow the console instructions and press Start. Received Pokemon are saved to the folder
chosen in Settings; the folder button beside Output opens it. Flash detects the chip and selects
its bundled image; a custom image is checked against that chip before writing. Connect an S3
through native USB Serial/JTAG. C3 and C6 chips are refused.

## Run from source

For source development, install Python 3.13 and the .NET 10 SDK:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r gui/requirements.txt
dotnet build -c Release services/pkhex -warnaserror
python gui/main.py
```

## Build a desktop app

To package an app, install ESP-IDF v6.1 for `esp32` and `esp32s3` and activate its environment.
Build both images with separate configurations:

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
cd ../..
python scripts/pack_app.py
```

The absolute output paths keep the images in `gui/firmware`. The packer requires both images;
the frozen app check verifies both are included. The release workflow builds each target separately
and supplies both images to every desktop packer.

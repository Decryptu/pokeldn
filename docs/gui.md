---
title: Desktop builds
---
# Desktop builds

Released apps include PKHeX and the merged ESP32 radio firmware. Users provide their own `prod.keys`.

Open the app and choose `prod.keys` in Settings. On the Board page, select the USB board to use
as the radio and flash its firmware. Choose a game and a tool, prepare a Pokemon or select a file,
then follow the console instructions and press Start. Received Pokemon are saved to the folder
chosen in Settings; the folder button beside Output opens it.

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

To package an app, install ESP-IDF v6.1 and activate its environment, then build the tracked firmware:

```sh
mkdir -p gui/firmware
idf.py -C firmware/esp32 build
idf.py -C firmware/esp32 merge-bin -o ../../../gui/firmware/pokeldn-radio.bin
python scripts/pack_app.py
```

The output path is relative to the firmware build directory.
The release workflow performs this build and supplies the image to each desktop packer.

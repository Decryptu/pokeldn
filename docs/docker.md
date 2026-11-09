---
title: Docker web app
---
# Docker web app

`docker compose` runs the desktop app on a server and serves it to a browser. The server has no
board on USB: it reaches the radio through the [network bridge](hardware_esp32.md#the-network-bridge),
a second XIAO ESP32S3 wired to the radio's UART build.

    cp .env.example .env        # set BRIDGE_HOST and BRIDGE_PORT
    mkdir -p keys && cp ~/.switch/prod.keys keys/
    docker compose up -d --build

Then open `http://SERVER:8550`.

| `.env` | meaning |
|---|---|
| `BRIDGE_HOST` | the bridge's address (required); its setup page shows it |
| `BRIDGE_PORT` | the bridge's TCP port, 47811 unless set on its setup page |
| `WEB_PORT` | the port the web app answers on, 8550 |
| `KEYS_DIR` | the folder holding `prod.keys`, `./keys` |

Compose passes the bridge as `POKELDN_BRIDGE=HOST:PORT`, which lists it on the Board page as
`socket://HOST:PORT` beside any USB boards (`gui/board.py` `ports`); with no USB board it is the one
sessions use. Runs open it as `POKELDN_RADIO=esp32:socket://HOST:PORT`. Flashing needs USB: install
the firmware on both boards from a computer first.

Settings, the bank, received Pokemon and logs live in `./docker-data` (`POKELDN_DATA=/data`, home
folder `/data/home`). The image builds PKHeX with the .NET SDK and points `POKELDN_PKHEX` at it.

`RUN_LOG=/data/logs` keeps each run's whole output in `docker-data/logs`, one file per run with the
seconds since its start on every line (`POKELDN_RUN_LOG`, `pokeldn/app/runner.py`), for reading along
from outside the browser. It is not redacted.

Neither the web app nor the bridge asks for a password: keep both on a trusted network. The bridge
serves one host at a time, and a new connection replaces the old one, so a second pokeldn reaching
the same bridge ends the first one's run.

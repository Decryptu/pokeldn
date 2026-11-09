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

## Coolify

An alternative to the compose setup above: [Coolify](https://coolify.io) 4.x builds the same image from
`docker-compose.coolify.yml` and puts its Traefik proxy in front, so there is no host port.

1. New resource → Public or Private Git repository → build pack **Docker Compose**, compose file
   location `/docker-compose.coolify.yml`.
2. Give service `pokeldn` the domain `https://pokeldn.example.lan:8550`. The `:8550` suffix is the
   container port Traefik forwards to.
3. Environment variables:

   | variable | meaning |
   |---|---|
   | `POKELDN_BRIDGE` | `HOST:PORT` of the bridge, e.g. `10.0.1.50:47811`; its setup page shows it. Give the bridge a fixed DHCP lease. Empty lists USB boards only |
   | `TZ` | optional, `Europe/Berlin` |
   | `POKELDN_RUN_LOG` | optional, e.g. `/data/logs` (unredacted) |

4. `prod.keys`: Persistent Storage → add a **File Mount** with destination
   `/data/home/.switch/prod.keys` and paste the file's content (it is text). Never commit it.
5. Settings, the bank, received Pokemon and logs persist in the `pokeldn-data` volume.

The first build takes minutes: the .NET SDK stage builds PKHeX. There is no password, so keep the
domain LAN-only (DNS that resolves only internally). The bridge serves one host at a time, so a
desktop pokeldn on the same bridge ends the Coolify app's run.

# Start here

pokeldn trades with Pokemon games on a Switch or Switch 2 over local wireless. An ESP32 board on USB is
the radio. Nothing is installed on the console.

## What you need

- A classic ESP32 board (ESP32-D0WD, WROOM-32E) with a USB serial bridge, or an ESP32-S3
  connected through its native USB port. Both use 2.4 GHz. C3 and C6 boards are unsupported.
- A USB data cable. Charge-only cables show no port.
- `prod.keys` dumped from your own Switch. The app asks for it once.
- One of the seven games on the Games page.

## First run

1. Board: plug the board in, select it, press Flash. The app detects the chip and selects its
   firmware. Identify reads the MAC; classic ESP32 boards with a GPIO2 LED also blink.
2. Games: pick a game and a tool.
3. Pokemon to offer: search a species and press Build. PKHeX makes a legal one for that game, owned by
   the trainer in Settings.
4. Follow the steps under On the console, then press Start.

The Pokemon the console sends you are saved in `Documents/pokeldn/Received`.

## Basic and All options

Basic shows the fields most runs need; the tested settings for each game are applied underneath. All
options lists every option the game's session accepts, with its own help text. A value set there
overrides the Basic field.

## Your own Pokemon files

Or use a Pokemon file takes a file exported from PKHeX. The app checks it with PKHeX and shows whether
it is legal before you offer it. An illegal Pokemon can crash the other game when it is drawn.

## When a run fails

- Stop, then back out of the console's search screen and search again. Most games keep a stale session
  for a short while.
- Change one thing per run.
- Settings, Session records opens the recording of every session; attach the latest one to a bug
  report.

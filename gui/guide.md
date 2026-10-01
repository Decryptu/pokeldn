# Start here

pokeldn trades with Pokemon games on a Switch or Switch 2 over local wireless. An ESP32 board on USB is
the radio. Nothing is installed on the console.

## What you need

- A classic ESP32 board (ESP32-D0WD, WROOM-32E) with a USB serial bridge, or an ESP32-S3 or
  ESP32-C3 connected through its native USB port. All use 2.4 GHz. C6 and S2 boards are unsupported.
  Attach the supplied antenna on a Seeed Studio XIAO ESP32C3.
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

More options, under the species, sets the nature, ability, gender, held item, ball, IVs and EVs (AVs in
Let's Go, effort levels in Legends Arceus). Empty fields stay random. The lists hold only what the
species can legally have in that game, and Build refuses a combination PKHeX finds illegal, with the
reason.

Add a trade, below the Pokemon, queues up to six for one session; each completed trade offers the
next. It shows on every trade tool except Let's Go join and Sword/Shield, which trade once per session. Each trade's received Pokemon gets its own file.

The Pokemon the console sends you are saved in `Documents/pokeldn/Received`.

## Basic and All options

Basic shows the fields most runs need; the tested settings for each game are applied underneath. All
options lists every option the game's session accepts, with its own help text. A value set there
overrides the Basic field.

The settings most players never change sit at the top of All options, already set: the time limit
before a session stops on its own, the wireless channel, and New PID each run. New PID gives each
offered Pokemon a new PID so a save that already received it takes it again; turn it off for a file
whose PID must stay, such as an event Pokemon.

## Your own Pokemon files

Or use a Pokemon file takes a file exported from PKHeX. The app checks it with PKHeX and shows whether
it is legal before you offer it. An illegal Pokemon can crash the other game when it is drawn.

## When a run fails

- Stop, then back out of the console's search screen and search again. Most games keep a stale session
  for a short while.
- Change one thing per run.
- Settings, Session records opens the recording of every session; attach the latest one to a bug
  report.

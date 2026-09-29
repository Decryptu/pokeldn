# Start here

pokeldn trades with Pokemon games on a Switch or Switch 2 over local wireless. An ESP32 board on USB is
the radio. Nothing is installed on the console.

## What you need

- A classic ESP32 board (ESP32-D0WD, WROOM-32E) with a CP2102 or CH340 USB chip. It is 2.4 GHz only.
- A USB data cable. Charge-only cables show no port.
- `prod.keys` dumped from your own Switch.
- One of the seven games on the Games page.

## First run

1. Settings: choose `prod.keys` and a work folder.
2. Board: plug the board in, select it, press Flash. Identify blinks its blue LED, so two boards can be
   told apart.
3. Games: pick a game and a tool, fill in the fields, follow the steps under On the console, then
   press Start.

## The work folder

Every session runs in the work folder. Relative paths in a tool are inside it.

| folder | holds |
|---|---|
| `received/` | Pokemon and records the console sent |
| `captures/` | a record of every session, one `.jsonl` each; attach it to a bug report |
| `scratchpad/` | reference files some tools read, such as a Sword party snapshot |

The Files card of a session lists what the tool reads and marks anything missing.

## Basic and All options

Basic shows the fields most runs need; the tested flags for each game are applied underneath. All options
lists every option the entry point accepts, with its own help text. A value set there is added last and
overrides the Basic field.

## Setup tools

Some games need a file captured once from your console before the first trade. Sword and Shield: run
Capture snapshot, then Extract snapshot, and Record advertisement before hosting. These are listed under
Setup for that game.

## When a run fails

- Stop, then back out of the console's search screen and search again. Most games keep a stale session
  for a short while.
- Change one thing per run.
- The session's capture in `captures/` holds every datagram; the Docs pages explain each game's protocol.

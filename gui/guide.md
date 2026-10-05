# Start here

pokeldn trades with Pokemon games on a Switch or Switch 2 over local wireless. An ESP32 board on USB is
the radio. Nothing is installed on the console.

## What you need

- A classic ESP32 board (ESP32-D0WD, WROOM-32E) with a USB serial bridge, or an ESP32-S3,
  ESP32-C3 or ESP32-C6 connected through its native USB port. All use 2.4 GHz. S2 boards are
  unsupported. Attach the supplied antenna on a Seeed Studio XIAO ESP32C3; a XIAO ESP32C6 uses its
  built-in antenna.
- A USB data cable. Charge-only cables show no port.
- `prod.keys` dumped from your own Switch. The app asks for it once.
- One of the seven games on the Games page.

## First run

1. Board: plug the board in and press Flash. The app detects the chip, writes its firmware, then
   checks the board on its own. The top of the page says Board ready when it answers.
2. Games: pick a game and a tool. A Host tool waits for your console to join; a Join tool finds the
   console's own search.
3. Pokemon to offer: search a species and press Build. PKHeX makes a legal one for that game, owned by
   the trainer in Settings.
4. Before you start, in the Session panel, lists anything still missing, with a button to fix it.
   Follow the steps under On the console, then press Start.

An ESP32-S3, C3 or C6 board with two USB ports talks to the app only through the port marked USB. Flashing
through the other one (COM or UART) works, but the board then never answers; the Board page says so.
With several boards plugged in, Use this board picks the one sessions use.

More options, under the species, sets the nature, ability, gender, held item, ball, IVs and EVs (AVs in
Let's Go, effort levels in Legends Arceus). Empty fields stay random. The lists hold only what the
species can legally have in that game, and Build refuses a combination PKHeX finds illegal, with the
reason.

Add a trade, below the Pokemon, queues up to six for one session; each completed trade offers the
next. It shows on every trade tool. Each trade's received Pokemon gets its own file.

Files can be dragged onto the app: a Pokemon file or a Showdown team (`.txt`) onto a trade fills it,
and onto Add a trade queues one trade per file. A gift file dropped on the Gift card opens it, and a
`.bin` dropped on Flash the firmware becomes the custom image.

The Pokemon the console sends you are saved in `Documents/pokeldn/Received`.

## Free up storage

Settings, Storage shows how much space can be freed. Press Clear local files, then Clear files to
remove saved session records, logs, temporary offers and unused built Pokemon. Save any records
needed for a bug report first. Received Pokemon, selected offers, keys, firmware and settings are
kept. Finish the current run before clearing files.

## Basic and Advanced

Basic shows the fields most runs need; the tested settings for each game are applied underneath.
Advanced lists every option the game's session accepts, with its own help text. A value set there
overrides the Basic field. Leave it alone unless a guide or a bug report asks for a change.

The settings most players never change sit at the top of Advanced, already set: the time limit
before a session stops on its own, the wireless channel, and New PID each run. New PID gives each
offered Pokemon a new PID so a save that already received it takes it again; turn it off for a file
whose PID must stay, such as an event Pokemon.

## Your own Pokemon files

Or use a Pokemon file takes a file exported from PKHeX. The app checks it with PKHeX and shows whether
it is legal before you offer it. An illegal Pokemon can crash the other game when it is drawn.

## Mystery Gift

Each Mystery Gift tool starts with three choices, four on Sword/Shield. Use a preset sends a ready-made gift. On
Sword/Shield, Official events lists real event cards (Pokemon, items, clothing, Battle Points) with
a search box. Build your
own opens a form: on FireRed/LeafGreen a Wonder Card with its text, who hands it over and what it
gives, a Wonder News, or your own ARM code; on Sword/Shield a Pokemon, an egg, items or Battle
Points. Open a file sends a `.pokegift` someone shared, a `.wc3` card on FireRed/LeafGreen or a
`.wc8` card on Sword/Shield.

Customize turns a preset into a form you can change. Before you send shows what the console gets,
when it happens and which cartridges it works on; a problem shows there in red and Start stays off.

On FireRed/LeafGreen, Game boosts lets you change how the game plays, such as speeding it up or adding a
Pokemon follower. Select the boosts and send them; they start immediately and stop when the game
restarts. To use them again after a restart, enable Save boosts for later, send the boosts, then send
Mom restores your boosts. Talk to Mom at home in Pallet Town after each restart to turn them back
on. The follower is always saved. Receiving another Wonder Card replaces Mom's gift; send it again
to restore her ability to turn the saved boosts on.

Read the save shows results in the Session log. Trainer ID (TID) is the number on your Trainer Card;
Secret ID (SID) is normally hidden. The party readout shows each Pokemon in your last saved party,
with its nature, six IVs (individual stat values from 0 to 31) and EVs (training points). These tools
keep your save and Wonder Card unchanged. The trainer-details and party tools also save a copy of
the read data in Received.

Console code runs inside the game while it receives the gift. Check offline runs it on a simulated
console first; code that would hang the menu is refused. Native code can change the running game or
its save. Send only code whose source and behavior you have checked.

Save gift file stores the selected gift for reuse or sharing. It works without a board.

## When a run fails

- Stop, then back out of the console's search screen and search again. Most games keep a stale session
  for a short while.
- Change one thing per run.
- Settings, Record every session, Open the records shows the recording of every session; attach the
  latest one to a bug report.

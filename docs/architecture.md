---
title: Code organization
---
# Code organization

The GUI and CLI share tool presets and Pokémon preparation. Game modules keep their measured wire
formats and timing; shared components belong outside a game directory.

| Location | Responsibility |
| --- | --- |
| `pokeldn/app/` | Tool catalog, argument assembly, parser inspection, settings, paths and child processes |
| `pokeldn/pokemon.py` | PKHeX service, imports, final offer validation and received files |
| `services/pkhex/` | Pinned PKHeX.Core dependency; legal encounter generation and game compatibility checks |
| `pokeldn/ldn/` | Radio transport, IP, Pia, reliability and channel tables |
| `pokeldn/gba/` | GBA wireless link protocols |
| `pokeldn/gen8.py`, `pokeldn/gen9.py` | Shared Pokémon record codecs |
| `pokeldn/<game>/` | Game identities, messages, state machines and protocol-specific variations |
| `bin/` | Parsers and session orchestration |
| `gui/` | Views, widgets, theme and board controls |

FRLG profiles, advertising and gift settings live in `pokeldn/frlg/`. The older configuration and
codec import paths retain small compatibility shims.

## Pokémon preparation

The shared service generates legal encounters and saves imports in the selected game's format.
Each trading launcher prepares a supplied file before opening its radio. Edits and requested fresh
identities are checked after they are applied. Incompatible formats, unavailable species and
illegal final records are refused. A session's trainer identity does not overwrite an imported
Pokémon's original trainer.

PID and encryption-constant changes can invalidate encounter correlations, especially events and
raids. Fresh identity is opt-in and must pass PKHeX; a fixed event trainer is preserved.

A built Pokémon is an encounter converted to a record. Shininess is requested from the encounter, so a
Generation 3 PID keeps the RNG correlation PKHeX expects. The PID, IVs and, for a wild slot, the level
are rolled at random, so an encounter gets up to eight rolls before it is skipped. A species reached by
evolving the encounter is raised to its evolution level when no encounter fits as caught.

A record that fails after a level or species change is repaired in steps, each on top of the last, and the
first legal result is kept:

1. Moves, relearn moves, plus-move flags, mastery flags and Legends Arceus size are refitted.
2. The ability is refreshed to the evolved species in the slot it was caught with.
3. A trade evolution receives a second handling trainer, `PkCamp`.
4. An evolution that counts something (critical hits, damage taken, Rage Fist uses, coins) starts from
   that count.

Applying the ability refresh before step 1 breaks Gholdengo in Legends Z-A, so the order is fixed.

A request PKHeX cannot satisfy is refused with the reason. A level below the lowest encounter level
reports that level; a species without an encounter in the game reports that. Shiny-locked legendaries,
fixed-level gifts and event-only species have no legal shiny or lower-level form. Sweeping every species of
every game with six request shapes (plain, shiny, level 50, level 100, shiny at level 50, nickname), plain
builds that fail are:

| game | species | failing |
|---|---|---|
| FireRed/LeafGreen | 386 | 0 |
| Let's Go | 153 | 0 |
| Legends Arceus | 226 | 0 |
| Brilliant Diamond/Shining Pearl | 493 | 7 |
| Sword/Shield | 664 | 5 |
| Legends Z-A | 364 | 8 |
| Scarlet/Violet | 733 | 35 |

Scarlet/Violet failures are mostly legendaries that only arrive from HOME. The rest are evolutions with
a condition PKHeX checks against the moveset or the form: Milotic, Shedinja, Sirfetch'd, Runerigus,
Perrserker, Wyrdeer, Ursaluna, Sneasler and Hydrapple in the games where they fail.

Sword/Shield Mystery Gift validates the WC8 seal and checks supported species, forms, moves and safe
items with PKHeX. Custom WC8 cards are distributions, and this structural check does not make them
official events. The optional `--image` research check uses a user-supplied game binary; it is not
required to distribute a card.

## Local files and releases

`config/host.toml` and runtime reference messages are tracked. `host.local.toml`, keys, notes, logs,
research images and generated build outputs stay local. ROM checksum comparisons require an explicit
`--sum-reference` file. No production default reads from `scratchpad/` or a local decompilation.

Settings and prepared offers use the platform's application data folder. `POKELDN_DATA` overrides it
for isolated runs. Received records use `.pk3`, `.pb7`, `.pk8`, `.pb8`, `.pa8`, `.pk9` or `.pa9`.

The packer takes tracked runtime files, the published self-contained PKHeX executable and the merged
radio firmware for ESP32, ESP32-S3 and ESP32-C3. Any missing image stops the build.
It excludes machine configuration and notes.
Windows builds keep standard input and output for child-process logs and stop handling, with the
owned console hidden. PyInstaller's windowed mode removes those streams on Windows.
Linux archives contain the portable executable; desktop entries with build-machine paths are omitted.

## Verification

```sh
dotnet build -c Release services/pkhex -warnaserror
python -m pytest tests/ -q -W error
```

CI runs these checks on Linux, macOS and Windows. Private research fixtures are optional; a clean
checkout tests the shipped reference data and shared PKHeX service without them.

Release builds run `scripts/check_app.py` against the frozen executable: GUI imports, all launchers,
seven PKHeX formats, serial discovery and esptool. The check needs no keys or connected board.

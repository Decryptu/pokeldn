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
| `pokeldn/gifts.py` | Shared [Mystery Gift file](gifts.md) envelope, reader, writer and native conversion |
| `services/pkhex/` | Pinned PKHeX.Core dependency; legal encounter generation and game compatibility checks |
| `pokeldn/ldn/` | Radio transport, IP, Pia, reliability and channel tables |
| `pokeldn/gba/` | GBA wireless link protocols |
| `pokeldn/gen8.py`, `pokeldn/gen9.py` | Shared Pokémon record codecs |
| `pokeldn/<game>/` | Game identities, messages, state machines and protocol-specific variations |
| `bin/` | Parsers and session orchestration |
| `gui/` | Views, widgets, theme and board controls |

FRLG profiles, advertising and gift settings live in `pokeldn/frlg/`. The older configuration and
codec import paths retain small compatibility shims.

The app runs one session at a time, since one board serves one process. Stop appears only on the tool
whose session is running; Start on another tool stops that session, waits for it to exit, then
starts. A flash holds the board too, and Start waits for it.

## Pokémon preparation

The shared service generates legal encounters and saves imports in the selected game's format.
Each trading launcher prepares a supplied file before opening its radio. Edits and requested fresh
identities are checked after they are applied. Incompatible formats, unavailable species and
illegal final records are refused. A session's trainer identity does not overwrite an imported
Pokémon's original trainer.

PID and encryption-constant changes can invalidate encounter correlations, especially events and
raids. Fresh identity is opt-in and must pass PKHeX; a fixed event trainer is preserved. A record legal
as supplied and illegal under a fresh identity keeps its own PID and encryption constant, and the
launcher logs `the offer kept its own PID`. A build tries Mystery Gift encounters after every other
encounter of the species, so a species with a wild, static or egg encounter is never built as an event.

A built Pokémon is an encounter converted to a record. Shininess is requested from the encounter, so a
Generation 3 PID keeps the RNG correlation PKHeX expects. A single-gender species asks for that gender
from the encounter: a female-only Vespiquen or Froslass comes only from a female Combee or Snorunt. The
PID, IVs and, for a wild slot, the level are rolled at random, so an encounter gets up to eight rolls
before it is skipped. A species reached by evolving the encounter is raised to its evolution level when no
encounter fits as caught. An evolved record takes the evolved species' gender when it is genderless
(Shedinja from Nincada) and form 0 when the evolved species has no form the encounter had (Sirfetch'd
from Galarian Farfetch'd).

A record that fails after a level or species change is repaired in steps, each on top of the last, and the
first legal result is kept:

1. An event gift that reached the game only through HOME (Zeraora and Melmetal in Sword/Shield)
   receives a HOME tracker. This precedes the refit, which would replace the event's fixed moves.
2. Moves, relearn moves, TM and TR record flags, plus-move flags, mastery flags and Legends Arceus size
   are refitted. A suggested moveset holds TM and TR moves that are legal only with their record flags.
3. An evolved record's ability is refreshed to the evolved species in the slot it was caught with.
4. A record with no handling trainer receives a second one, `PkCamp`: a trade evolution has been traded,
   and some gifts (Magearna in Legends Z-A) arrive already handled.
5. An evolution that counts something (critical hits, damage taken, Rage Fist uses, coins) starts from
   that count.
6. A Brilliant Diamond/Shining Pearl evolution at a Beauty threshold (Milotic, 170) sets that Beauty and
   the lowest Sheen its poffins imply.

Applying the ability refresh before the refit breaks Gholdengo in Legends Z-A, so the order is fixed.

A request PKHeX cannot satisfy is refused with the reason. A level below the lowest encounter level
reports that level; a shiny request whose every encounter is shiny-locked reports that; a species without
an encounter in the game reports that. Fixed-level gifts and event-only species have no lower-level form.
Sweeping every species of every game with six request shapes (plain, shiny, level 50, level 100, shiny at
level 50, nickname), plain builds that fail are:

| game | species | failing |
|---|---|---|
| FireRed/LeafGreen | 386 | 0 |
| Let's Go | 153 | 0 |
| Legends Arceus | 226 | 0 |
| Brilliant Diamond/Shining Pearl | 493 | 2 |
| Sword/Shield | 664 | 3 |
| Legends Z-A | 364 | 5 |
| Scarlet/Violet | 733 | 32 |

Every failure but three is a species PKHeX has no encounter for in that game: Celebi and Deoxys in
Brilliant Diamond/Shining Pearl, Diancie, Magearna and Meltan in Sword/Shield, Scatterbug, Spewpa,
Vivillon and Zygarde in Legends Z-A, and in Scarlet/Violet the legendaries that arrive only from HOME.
The three with an encounter are Milotic in Legends Z-A and Wyrdeer and Ursaluna in Scarlet/Violet. PKHeX
gives Wyrdeer and Ursaluna no Generation 9 evolution. For a Z-A Milotic built from Feebas with a
handling trainer, PKHeX's evolution chain stops at Milotic; the game's records refuse contest stats.

### Offer options

A build can also ask for a nature, ability, gender, held item, ball, IVs and effort values. Nature,
ability, gender and IVs go into the encounter criteria, so the record is generated with them; a
Generation 3 PID is searched for the requested nature. When an encounter rolls something else, the
record is moved to the request the way a player would, and the legality analysis judges the result:

| differs | change |
|---|---|
| nature | a mint sets the stat nature, Generation 8 onward |
| ability | the slot that holds the ability (capsule or patch) |
| an IV asked to be 31 | hyper training |

Held item, ball and effort values are set after the build. A Generation 3 or 4 EV above 100 is legal
only once the Pokémon has gained experience since it was met, so such a record gets one experience
point, below the next level. A Legends Arceus effort level is the stored value plus a bias from the IV
(1 from 20, 2 from 26, 3 at 31), and a stored value past 10 minus the bias is illegal, so the request
is taken as the level the game shows and the bias is subtracted.

The record must carry every request and pass the legality analysis. The first encounter that does is
kept, and the first request no encounter can carry is named in the refusal.

The options offered are the ones a species can have in that game:

| option | listed when |
|---|---|
| ball | PKHeX permits it for at least one encounter of the species |
| ability | a legal build carrying it exists; Legends Z-A lists none |
| held item | PKHeX lists it as a released held item for the game; Let's Go and Legends Arceus have none |
| effort | EVs, 252 each and 510 in all; AVs in Let's Go, 200 each; effort levels in Legends Arceus, 10 each |

Sampling 25 species per game and building each with every listed ball, every nature, a fixed IV set,
fixed effort values, each gender and a held item, 8088 of 8095 builds are legal. PKHeX refuses Hardy,
Docile and Bashful on the Sword/Shield event Celebi, and the same three and Quirky on the Legends Z-A
gift Melmetal.

Custom offer options are also verified by a retail Sword round trip: the received Pokemon was
traded back on the next queued exchange and its saved record compared with the outgoing offer
([The offered record](swsh_trade.md#the-offered-record)).

Sword/Shield Mystery Gift validates the WC8 seal and checks supported species, forms, moves and safe
items with PKHeX. Custom WC8 cards are distributions, and this structural check does not make them
official events. The optional `--image` research check uses a user-supplied game binary; it is not
required to distribute a card.

### The Let's Go link code

The Let's Go host's code is three slots. A slot opens the console's ten picker Pokemon, two rows of five as on the console, as sprites with
their names under them, so a sprite that never downloaded still reads; the pick fills the slot and
opens the next empty one. The value is the three English names, comma-separated, as `--code` takes
them, and Start waits until all three are set: an empty slot would host under the launcher's default
code, which the console's search never finds.

### The trade queue

A tool whose entry point completes several trades on one seat takes up to six Pokemon; "Add a trade"
adds a picker, and the session offers them in order, one per completed trade. The pickers become
repeated offer flags:

| tool | offers as | after the last |
|---|---|---|
| FireRed/LeafGreen host and join | party files, `--trades N`, slots 0 to N-1 | the host declines a further trade (`PLAYER_CANCEL_TRADE`) and waits for the player's Cancel and Yes; the joiner cancels to leave |
| Let's Go host | `--offer`, then `--next-offer` per later trade | the launcher answers no further trade (`pokeldn/lgpe/trade.py`); the player backs out |
| Let's Go join | `--offer`, repeated | the launcher answers no further trade; the player backs out |
| Brilliant Diamond/Shining Pearl host and join | `--offer` / `--trade-template`, repeated | the last is offered again |
| Legends Arceus host and join | `--trade-box-record` / `--offer`, repeated; the joiner hands the list to the host role | the last is offered again |
| Scarlet/Violet host and join | `--trade-offer`, repeated | the launcher's trade stage answers no further message (`pokeldn/sv/trade.py`, `done`) |
| Sword/Shield host and join | `--offer-file`, repeated; each later trade runs from the box on the same session | the last is offered again |
| Legends Z-A host and join | `--trade-offer`, repeated; each new record is previewed when its trade starts | the last is offered again, under a new PID with `--fresh-pid` |

Every trade launcher calls `pokeldn.ldn.show_done()` once per completed trade, at the step its
title's table above ends on; it flashes the board's LED and prints `[done] trade N complete`. The
Session panel's Offering strip counts that line and marks the first N queued Pokemon as traded. The
Received list cannot stand in for it: some launchers write the console's Pokemon when the console
picks it, before the trade completes.

`--fresh-pid` gives every queued record its own PID and encryption constant. Trade N above 1 writes
what it received to the output path with `-N` before the extension (FireRed/LeafGreen: `_tradeN_` and
the species; Scarlet/Violet: `.N`, counted by distinct offers; Brilliant Diamond/Shining Pearl host:
`_N`; Legends Z-A and Sword/Shield: `-N`).

### Ending a run

A trade run ends on its own when the console has left after a trade, so the app's Stop is never
needed after a session that worked.

| role | ends when |
|---|---|
| host, every title | the console has left the network after at least one completed trade (`pokeldn.ldn.left_after_trade`); a console that leaves before any trade may come back, and the host stays up |
| FireRed/LeafGreen host | the console has left the network, after a trade or not |
| joiner | the console's host closes its network or hands its role on (FireRed/LeafGreen, Let's Go, Sword/Shield, Brilliant Diamond/Shining Pearl); Scarlet/Violet, Legends Arceus and Legends Z-A search again after a seat that traded nothing, and close after one that did |

The time limit (`--seconds`, `--hold`) still bounds a run whose console never leaves.

App runs completed queued trades, marked their offers complete and returned to idle after the
console left in all seven title families, in both roles. Game-specific departure measurements and
remaining questions are on each title's Leaving section; screen delays before the first leave
message remain separate from the answered departure exchange.

## Local files and releases

`config/host.toml` and runtime reference messages are tracked. `host.local.toml`, keys, notes, logs,
research images and generated build outputs stay local. ROM checksum comparisons require an explicit
`--sum-reference` file. No production default reads from `scratchpad/` or a local decompilation.

Settings and prepared offers use the platform's application data folder. `POKELDN_DATA` overrides it
for isolated runs. Received records use `.pk3`, `.pb7`, `.pk8`, `.pb8`, `.pa8`, `.pk9` or `.pa9`.

Settings exposes manual cleanup through `pokeldn.app.storage`
([Local storage](gui.md#local-storage)). A scan inventories reclaimable files; deletion uses that
inventory, rechecks current selections and preserves changed files. Cleanup holds the app's busy
state, so sessions and flashes cannot start during deletion.

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

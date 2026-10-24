---
title: Code organization
---
# Code organization

The GUI and the command line share tool presets and Pokémon preparation; game modules keep their wire
formats and timing, and shared components live outside any game directory.

| Location | Responsibility |
| --- | --- |
| `pokeldn/app/` | Tool catalog, argument assembly, parser inspection, settings, paths and child processes |
| `pokeldn/popup.py` | [Pop-ups](gui.md#pop-ups) a program shows in the app; `pokeldn/app/popups.py` decides which show |
| `pokeldn/pokemon.py` | PKHeX service, imports, final offer validation and received files |
| `pokeldn/gifts.py` | Shared [Mystery Gift file](gifts.md) envelope, reader, writer and native conversion |
| `pokeldn/receiver_gift.py` | A trade host's Mystery Gift Pokemon made for the console's save ([Made for the receiving player](gift_simulated.md#made-for-the-receiving-player)) |
| `services/pkhex/` | Pinned PKHeX.Core; legal encounter generation and compatibility checks |
| `pokeldn/ldn/` | Radio transport, IP, Pia, reliability and channel tables |
| `pokeldn/online/` | [Online trade](online.md): relays, matching and the encrypted partner channel |
| `pokeldn/gba/` | GBA wireless link protocols |
| `pokeldn/gen8.py`, `pokeldn/gen9.py` | Shared Pokémon record codecs |
| `pokeldn/<game>/` | Game identities, messages, state machines and protocol variations |
| `bin/` | Parsers and session orchestration |
| `gui/` | Views, widgets, theme and board controls |

The app runs one session at a time, since one board serves one process. Start on another tool stops
the running session, waits for it to exit, then starts; Start also waits for a running flash.

## Pokémon preparation

Each trade launcher prepares a supplied file through the PKHeX service before opening its radio.
Incompatible formats, unavailable species and illegal final records are refused. A session's trainer
identity never overwrites an imported Pokémon's original trainer.

| behaviour | rule |
|---|---|
| incomplete analysis | `LegalityAnalysis.Parsed` false restarts the helper and retries once under the service lock; a second failure raises |
| fresh identity | opt-in new PID and encryption constant; a record illegal under it keeps its own and logs `the offer kept its own PID` |
| shiny, single gender | requested from the encounter, so a Generation 3 PID keeps its RNG correlation |
| random rolls | PID, IVs and a wild slot's level, up to eight rolls per encounter |
| evolved species | raised to its evolution level when no encounter fits as caught; takes the evolved gender when genderless (Shedinja) and form 0 when the encounter's form does not exist (Sirfetch'd) |

A record that fails after a level or species change is repaired in order, each step on the last; the
first legal result is kept:

1. A HOME-only event (Zeraora, Melmetal in Sword/Shield) receives a HOME tracker when the setting is
   "made" ([The HOME tracker setting](gui.md#the-home-tracker-setting)).
2. Moves, relearn moves, TM/TR record flags, plus-move and mastery flags and Legends Arceus size are
   refitted.
3. An evolved record's ability is refreshed in its caught slot. This must follow the refit (Gholdengo
   in Legends Z-A).
4. A record with no handling trainer gets `POKELDN`.
5. A counting evolution (critical hits, damage taken, Rage Fist uses, coins) starts from its count.
6. A Beauty evolution in Brilliant Diamond/Shining Pearl (Milotic, 170) sets that Beauty and the
   lowest Sheen its poffins imply.

An unsatisfiable request is refused with the reason. Plain builds fail only for 2 species in Brilliant
Diamond/Shining Pearl (Celebi, Deoxys), 2 in Sword/Shield (Diancie, Meltan), 1 in Legends Z-A (Milotic,
whose game records refuse contest stats) and 31 in Scarlet/Violet (HOME-only legendaries, and Wyrdeer,
which PKHeX gives no Generation 9 evolution).

A request naming no form takes the first form that builds. Species present only in a later form:

| game | species | forms PKHeX builds |
|---|---|---|
| Sword/Shield | Zygarde | 10%-C, 50%-C (Power Construct) |
| Sword/Shield | Magearna | Original Color, an event |
| Legends Arceus | Giratina | Origin |
| Scarlet/Violet | Ursaluna | Bloodmoon |
| Legends Z-A | Zygarde | 10%-C, 50%-C, Complete |
| Legends Z-A | Scatterbug, Spewpa | Garden, Meadow |
| Legends Z-A | Vivillon | Garden, Meadow, Marine |

### Encounter order

A build tries PKHeX's encounters (`EncounterMovesetGenerator`) one version at a time, the player's own
first, and in each version by kind, each kind cut at its first 80 encounters:

| order | kind | the record built from it |
|---|---|---|
| 1 | wild slot | a catch at the slot's location and level, any catchable ball |
| 2 | static encounter | a gift, a legendary, a raid or a Max Lair Pokemon |
| 3 | in-game trade | an NPC's Pokemon |
| 4 | egg | a hatch, in the ball its parent passed on |
| 5 | Mystery Gift | after every other kind and version, since an event's fixed PID makes a new-PID offer illegal |

An evolved Pokemon below its evolution level is tested at level 100, then a bisection finds the lowest
legal level. Hydrapple in Scarlet/Violet is legal only at scattered levels.

### Offer options

A build can ask for a form, nature, ability, gender, held item, ball, friendship, up to four moves, IVs
and effort values, and in Legends Arceus and Legends Z-A whether it is an Alpha. Moves, form and Alpha
narrow the encounter search; nature, ability, gender and IVs go into
the encounter criteria. When the encounter rolls something else, the record is changed as a player
would:

| differs | change |
|---|---|
| nature | a mint, Generation 8 onward |
| ability | capsule or patch |
| an IV asked to be 31 | hyper training, at level 100 (Generations 7, 8) or 50 (Generation 9) |
| form | set on species whose form the player changes, such as Rotom |

Held item, ball, friendship and effort values are set after the build. A Generation 3 or 4 EV above 100
needs experience gained since meeting, so the record gets one experience point. A Legends Arceus
effort level is taken as shown in game, and the IV bias (1 from IV 20, 2 from 26, 3 at 31) is
subtracted before storing.

Friendship is the original trainer's. A receiving console keeps it only when its player is the
original trainer, so Settings, [Your trainer](gui.md#your-trainer) must be the player's; each title's
trade page says what a trade rewrites. FireRed/LeafGreen set 70 on every received non-egg Pokemon
[trade_scene.c:1071].

| option | listed when |
|---|---|
| ball | PKHeX permits it for at least one encounter |
| Alpha | Legends Arceus or Legends Z-A has an Alpha encounter of the species (`IAlphaReadOnly.IsAlpha`) |
| ability | a legal build carrying it exists; Legends Z-A lists none |
| held item | a released held item for the game; Let's Go and Legends Arceus have none |
| effort | EVs 252 each, 510 in all; AVs in Let's Go, 200 each; effort levels in Legends Arceus, 10 each |

The first encounter in the [encounter order](#encounter-order) carrying every request legally is kept;
otherwise the refusal names the first request none can carry.

### Showdown sets

Import paste reads a Showdown, Smogon or PKHeX set with `ShowdownParsing.GetShowdownSets`, in any
language PKHeX exports and in PKHeX's spelling. No `Level:` line means 100; an IV absent from `IVs:` is
31.

| the set names | result |
|---|---|
| an unreadable line, or a species, form, ability, item or move the game lacks, EVs over 510 | refused; nothing is filled |
| Tera Type, Gigantamax, Dynamax level, Hidden Power type; EVs in Let's Go or Legends Arceus; an ability in Legends Z-A | left out, with a note |
| no `IVs:` or `Friendship:` line | the encounter's own values |
| several sets in a trade queue | one trade each from the pasted picker, up to the queue's limit; any refusal refuses the paste |
| several sets outside a queue | the first fills the form |

Sword/Shield Mystery Gift validates the WC8 seal and checks species, forms, moves and items with
PKHeX; a custom card is a distribution, not an official event.

### The Let's Go link code

The Let's Go host's code is three slots, each picked from the console's ten picker Pokemon, passed to
`--code` as three comma-separated English names. Start waits until all three are set.

### The trade queue

A tool that completes several trades on one seat takes up to six Pokemon, offered in order:

| tool | offers as | after the last |
|---|---|---|
| FireRed/LeafGreen host and join | party files, `--trades N` | the host declines (`PLAYER_CANCEL_TRADE`) and waits for Cancel and Yes; the joiner cancels |
| Let's Go host | `--offer`, then `--next-offer` | answers no further trade (`pokeldn/lgpe/trade.py`) |
| Let's Go join | `--offer`, repeated | answers no further trade |
| Brilliant Diamond/Shining Pearl | `--offer` / `--trade-template`, repeated | the last again |
| Legends Arceus | `--trade-box-record` / `--offer`, repeated | the last again |
| Scarlet/Violet | `--trade-offer`, repeated | no further message (`pokeldn/sv/trade.py`, `done`) |
| Sword/Shield | `--offer-file`, repeated | the last again |
| Legends Z-A | `--trade-offer`, repeated | the last again, under a new PID with `--fresh-pid` |

Each completed trade calls `pokeldn.ldn.show_done()`, which flashes the LED and prints
`[done] trade N complete`; the Session panel counts that line. Trade N above 1 writes to the output
path with a suffix: `_tradeN_` and the species (FireRed/LeafGreen), `.N` (Scarlet/Violet), `_N`
(Brilliant Diamond/Shining Pearl host), `-N` (Legends Z-A, Sword/Shield).

### Trade back

`--trade-back`, on every trade host and joiner (the app's Send it back switch), follows each queued
trade with one that offers the Pokemon the console just sent, so a Pokemon that evolves by trade
evolves on the console. The player offers ours back in that second trade. `pokeldn/trade_back.py`
holds the order:

| trade | offers |
|---|---|
| 1, 3, 5, ... | queued offer 1, 2, 3, ... |
| 2, 4, 6, ... | the record the console sent in the trade before, byte for byte |

A returned record never takes `--fresh-pid` or any other offer edit. A launcher that stops after its
last queued trade stops after twice as many; one that offers its last again keeps alternating.

| launcher | how the record comes back |
|---|---|
| native hosts | `TradeBack` stands in for the online partner (`pokeldn.online.link.Partner`): the console's last offer before `done` is the next round's record |
| FireRed/LeafGreen host and join | each offered party slot is offered again; TradeMons has put the received Pokemon there [trade_scene.c:1054-1083]. A session runs up to 12 trades |
| native joiners | `Rounds` chooses each trade's record in the launcher's own offer path |

An emulated French FireRed hosted by `bin/frlg_trade_host.py --over-ip --trade-back` traded its Kadabra
in trade 1, took it back in trade 2 and evolved it into Alakazam; the save kept a legal Alakazam.
An emulated Shield hosted by `bin/swsh_host.py --ip-host --trade-back` traded its Kubfu for the
offered Onix, then took the Kubfu back for the Onix in trade 2 and left on B.

`--trade-back` refuses `--online`, the gift made for the receiving player, and the raid, lair and
Union Circle modes. Mystery Gift - Simulated never offers it.

### Ending a run

| role | ends when |
|---|---|
| host | the console leaves after at least one trade (`pokeldn.ldn.left_after_trade`) |
| FireRed/LeafGreen host | the console leaves |
| joiner | the host closes or hands its role on; Scarlet/Violet, Legends Arceus and Legends Z-A search again after a seat with no trade |

`--seconds` and `--hold` bound a run whose console never leaves.

## Local files and releases

`host.local.toml`, keys, notes, logs and build outputs stay local; no production default reads
`scratchpad/`. Settings and prepared offers live in the platform's data folder, overridden by
`POKELDN_DATA`. Cleanup runs through `pokeldn.app.storage` ([Local storage](gui.md#local-storage)).

The packer bundles tracked runtime files, the PKHeX executable and firmware for ESP32, S3, C3 and C6;
a missing image stops the build. Windows builds keep standard streams for child-process logs, with the
console hidden.

## Verification

```sh
pip install -r requirements-dev.txt
dotnet build -c Release services/pkhex -warnaserror
python -m pytest tests/ -q -W error -n auto --dist worksteal
```

CI runs these on Linux, macOS and Windows. Release builds run `scripts/check_app.py` against the frozen
executable; it needs no keys or board.

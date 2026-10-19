---
title: Max Raid Battles
parent: Sword and Shield
nav_order: 5
---

# Max Raid Battles

A local Max Raid Battle is a Sword/Shield session of up to four stations on LDN scene 60006. The
host opens it from a den with "Invite Others"; a guest finds it in its Y-Comm list and joins with
"Start Battle" over the host's name. The lobby runs on the reliable broadcast protocol 0x80, the
battle on 0x7C. `bin/swsh_connect.py --scene 60006 --raid-join --offer-slot N` takes a guest seat
in a console's lobby; the lobby shows it with the chosen Pokemon.

## The network

| field | value |
|---|---|
| LDN scene id | 60006 (65535 in the overworld) |
| participants | 1 of 4 when opened |
| advertise data byte `0x97` | `0x11` |
| Pia session maximum | 4 (`0x0110e5e0`, called from the den lobby at `0x01031c74`) |
| advertise `0xb0` and `0xd4` | the boss and the den record ([The den record](#the-den-record)) |

The den lobby's code sits among `View_NestHole`, `StateGuestReady` and `StateHostReady`
(`0x0102aba4..0x010370cc`). Dynamax Adventures match through `ChikaMatchingState*`
(`0x00bd1978..0x00bda158`), which calls the same Pia session maximum from `0x00bd9b30`.

A guest's Y-Comm list leaves out a raid whose advertisement carries the guest's own device id and
account uid ([The den record](#the-den-record)).

## The lobby messages

Every lobby message is id 2000, `net_contents.nesthole.protocol_buffers.NestholeAsyncDataHolder`
(descriptors at `0x1bfde43` and `0x20677b0` in `main`). Each field is a holder with one `bytes`
field 1.

| field | name | size | content |
|---|---|---|---|
| 1 | NestholeTimeLimit | 4 | u32 seconds left; the host sends it three times a second |
| 2 | NestholePlayerInfo | 40 | 8 zero bytes, u32 (0x11 retail Sword, 0x12 emulated Shield), UTF-16 name in 13 characters, `00 03` |
| 3 | NestholeBattleReady | 16 | byte 8 is 1 once the player pressed ready; byte 12 is 1 once the battle starts |
| 4 | NestholeSelectPokemon | 352 | 8 zero bytes, then the chosen Pokemon as an encrypted party PK8 (0x158) |
| 5 | NestholeBattleStart | 32 | the participants' Pia constant ids as four u64, the host's first, unused slots zero |
| 6 | NestholeBossPokemon | 364 | 19 zero bytes and `ff`, then the boss as an encrypted party PK8 |
| 7 | NestholeRewards | 120 | fifteen u32 pairs: item id, count; unused pairs zero |
| 8 | NestholeBattleSeed | 16 | u64 seed, then `00 ff ff ff 1e 00 03 00` |

PlayerInfo goes out zlib-compressed with a 4 KB window (header `48 4b`) under reliable flag 0x10;
the others go out plain. `pokeldn/swsh/raid.py` builds every field; its output equals the bytes of an
emulated guest (2, 3, 4) and an emulated host (5 to 8).

The boss record carries the boss in full: species, level, moves, IVs and PID. In two emulated
raids, the den's raid generator applied to the BattleSeed value gives neither the boss's
encryption constant nor its PID. What the seed feeds is unread.

## The guest's sequence

Recorded between two emulated Shields, a whole raid won:

1. The snapshot exchange on 0x84, as in a link trade; the host's snapshot went first.
2. PlayerInfo, BattleReady (zero) and SelectPokemon on 0x80 port 0, sequences 1 to 3.
3. BattleReady with byte 8 set when the player presses ready.
4. Once every player is ready, the host sends BattleStart, its SelectPokemon again, BossPokemon,
   Rewards, BattleSeed and BattleReady with bytes 8 and 12 set.
5. The guest answers with its SelectPokemon again, then BattleReady with bytes 8 and 12 set.
6. The battle starts on 0x7C: sync ping 80 on port 0, framework messages 40000 on port 1, then
   10000 and 20000 messages on port 0 for every turn.

Against a retail Sword host, a guest that stops after BattleReady with byte 8 set leaves the host's
player on "Connexion en cours" after the host's own ready, ending in error 2-ALZAA-0016.

## The battle

The host runs the battle; a guest answers on 0x7C. `pokeldn/swsh/raid_battle.py` is the guest's side,
built from an emulated Shield guest; `bin/swsh_connect.py --raid-join` with it fought a whole raid as
a guest of an emulated host, to a won raid.

Before the battle, from the mesh join, the guest runs SyncClockProtocol 0x1C (a request a second)
and sends one ClockProtocol 0x77 request (`00` x16 then `00 6f`), both to destination bitmap 1.

| port | message | the guest |
|---|---|---|
| 0 | sync 80: ping, pingReply, pingSynced | answers ping with ping and pingReply, pingSynced with pingSynced |
| 1 | 40000, content 0's framework: field 2 base (10000 or 20000, absent for 0), 3 station constant id, 4 clock, 5 body | after its pingSynced sends three base-10000 / base-20000 pairs (bodies `00000000`, `000018fc`), then mirrors each host base-20000 body under its own station id |
| 0 | 10000, field 3 {1 station, 2 slot, 3 version} | sent once the host lists its own seat (base 0, 16-byte body: constant id, slot, version byte 0x6e) |
| 0 | 10000, field 1 empty | sent after the host's base-8 message (24-byte body, the battle's seed) |
| 0 | 20000, field 1 {1 sender, 2 slot, 3 counter, 4 data} | answers every host command |
| 0 | 20000, field 3 {1 state, 2 slot} | sends {1: 2, 2: slot} before its action |

A host command's data opens with four u16: serial, type, length, a tag. The guest answers with the
same serial, type and tag, length 4 and four zero bytes, except:

| type | the guest sends |
|---|---|
| 0x02 | the state message, then its action: serial, 0x02, 0x58, tag, then 88 bytes |
| 0x21 | the end: sender 1, data `0000 1e00 0000 2f00` |

Types seen from a host: 0x01, 0x0d, 0x07 (123 bytes), 0x0e, 0x02, 0x10 (47 bytes), 0x09 (the turn's
log, zlib, 0.4 to 2.4 KB), 0x04, 0x11 and 0x0a after the guest's Pokemon fainted, 0x21 at the end.

### Which station serves

The server is the station whose ServerVersion record wins a table each console keeps; neither the
Pia host check (`0x110e620`, no caller in the battle or lobby code) nor BattleStart's order decides it.

ServerVersion is `btl.net.protocol_buffers.BtlDataHolder` (id 10000) field 3: station id u64, client
id u32, version u32. Every copy sends version `0x6e` (`0x8b1778`). A console keeps eight slots of
{station, client id, version, valid} (battle network object `+0x190 + 16 * i`); `0x8b4030` takes the
client id of the first valid slot whose version equals the highest seen, and `0x8b1990` (IsServer)
compares it with the console's own client id. The collecting station files a record in the slot of the
sender's Pia station index (`0x8b4440`, `0x6b5850`); every other console receives the slots as 40000
framework objects 0 to 7, the object number in field 2. In the recorded raid the host published object
0 (its own record, client id 0) and object 1 (the guest's, client id 1).

A console's client id is its position in BattleStart among the lobby's members (`0x1025120`,
`0x10253bc`). Removing a station clears its slot and reruns the choice (`0x8b3f70`), and every console
holds a standby server it promotes once IsServer turns true (`0x7f838c`, `0x7f87f0`).

### The action

The 88-byte action is eleven 8-byte entries. Only entry 2 changed between four moves of one guest:
as a little-endian u24 it is `move id << 13 | target << 8 | 0xc1`.

| move | entry 2 | target |
|---|---|---|
| Pound (1) | `c1 28 00` | 8 |
| Bind (20) | `c1 88 02` | 8 |
| Growl (45) | `c1 a2 05` | 2 |
| Water Gun (55) | `c1 e8 06` | 8 |

Growl hits every foe and carries target 2; the single-target moves carry 8. A turn on which the
guest could not act sent entry 2 as zero. `raid_battle.action(move, target)` builds it;
`--raid-move N` picks the move slot of the guest's Pokemon.

The 0x7C acknowledgement carries 32 slots; only slot 0 tracks the guest's stream, the others hold
stale ids (34460 seen). A resend gated on the maximum over slots never resends.

## The den record

A den host's advertisement describes its raid; a guest's Y-Comm entry builder (`0x00fa1560`) reads it.

| offset | content |
|---|---|
| `0x5F` bit 1 | the host's version: clear Sword, set Shield |
| `0xAF` | activity kind: `0x11` at rank 0, `0x13 + 2 (rank - 1)` above; `0xFF` is never listed |
| `0xB0` | the boss shown: u16 species (bits 0 to 9) and form (10 to 15), a byte whose bits 4 and 5 are 1 normal, 2 Gigantamax, the u32 encryption constant |
| `0xD4` | the den record, the same eight-byte layout |
| `0xDC` | high nibble: the star rank, 0 to 4 |
| `0xDD` | bits 3 to 5: den kind, 0 for a normal den |
| `0xDE`, `0xE0` | u16 encounter table, counted among the host version's tables, and u16 slot |
| `0xE6` to `0xED` | CRC16s of files 8, 6, 7 and 9 of `bin/archive/field/resident/data_table.gfpak` |

With a non-zero species at `0xD4`, a guest lists the raid only when its own table CRCs match, the den
kind is 0, and table `0xDE` slot `0xE0` of the host's version holds that species, form and Gigantamax
flag (`0x00ea5160`, `0x00ea51d0`). A species of 0 skips those checks. The rank must not exceed the
guest's own rank, from its badge count, when the byte at `0x02510b2c` is 1 or 2 and the host is not a
friend. The record at `0xB0` is range-checked only. `pokeldn/swsh/data/nest_slots.json` holds the
1.3.2 slots (`scripts/gen_swsh_nest_data.py`); `raid.den_advert` points the den record at a slot
holding the boss, or zeroes it.

A guest drops a station whose device id and account uid (`0x1F` to `0x3E`) both equal its own
(`0x0111b160`).

### The boss record

A guest checks BossPokemon and Rewards before it sends its started BattleReady (`0x01030d14`, state
10); a failed check leaves with 2-ALZAA-0016.

| check | code | passes when |
|---|---|---|
| the boss | `0x01032270` | species, form and party `+0x156` (1 normal, 2 Gigantamax) equal the entry the den record names: kind 0 the base table `0xDE`, slot `0xE0` of the advertised version; kinds 1 to 3 the guest's own saved event encounters, slot `0xE0`; kind 4 its saved crystal encounters |
| the rewards | `0x01032570` | every pair with an item and a count is a bonus row of the slot's bonus table at exactly its count for the advertised rank, or an item of its drop table with a chance at that rank (count free) |

Level, moves, IVs, PID, ability, shininess and trainer fields are not compared. A zero den record
names kind 0, table 0, slot 0 (Tyrogue). Base dens hold no legendary or mythical Pokemon, so a hosted
boss is one of the species, forms and Gigantamax states `nest_slots.json` lists; `raid.den_advert`
switches the advertised version when only the other one holds the boss, and an event boss is shown as
the base den slot holding its species, form and Gigantamax state. `raid.reward_choices` lists what
the slot allows at a rank (each bonus item at its count, each drop at any count); `raid.den_rewards`
builds the slot's own rows from it.

A retail Sword guest left with 2-ALZAA-0016 on BossPokemon when the boss was a traded record (a
trainer, version, met data and ball), when its party Dynamax type (`+0x156`) was 0, and when the
advertisement's den record was zero (a boss no base den holds: Mew on an accepted record, an event's
Gigantamax Toxtricity with or without its Gigantamax bit), though it listed each of those raids; both recorded
den bosses have no trainer data and Dynamax type 1. A boss on a den boss's record with only the species
changed, and a level-20 boss built by `raid.boss_record` (the Pokemon's species, form, moves, IVs, EVs,
nature, ability, PID, encryption constant and party stats on a den boss's record), were accepted.

In three recorded den bosses (an emulated Pidove at Dynamax level 1 and Hoothoot at level 2, a retail
Torkoal at level 7), the party HP stat and current HP are the plain HP stat times
`(150 + 5 * Dynamax level) / 100`, rounded down; the other five stats are plain. The Dynamax level is
at `+0x90`, the ability slot bit at `+0x16` bits 0 to 2, and the experience is the level's least.

## Hosting

`bin/swsh_host.py --raid-boss PK8 --raid-console-serves` hosts a den lobby a console joins from its
Y-Comm list (`pokeldn/swsh/raid_host.py`). The advertisement and the snapshot are an emulated Shield
den host's, renamed and with no account ids (`pokeldn/swsh/data/raid_advert.bin`,
`raid_snapshot.bin`; `--advert` and `--snapshot` replace them). The advertisement goes out with a
fresh station profile, the board's name, the boss and a den record for it
([The den record](#the-den-record)); `--raid-boss` takes any PK8 and sends it through
`raid.boss_record`. The snapshot goes out before the guest's. `--raid-reward ITEM:COUNT` fills Rewards and `--raid-seed` BattleSeed.
The host refuses a `--raid-reward` row the advertised den slot does not give at its rank, and prints
what the slot gives; an event's rows that do not fit are left out.

The app's Max Raid (Host) tool runs these flags with a boss (or a Wild Area Event and one of its
bosses a base den holds, `raid_event.hostable`), our Pokemon and up to 15 reward rows; without rows the
host gives the den slot's own rewards. Its reward editor offers only the items of the den slot the
chosen boss is advertised from (`raid.boss_den`, `pokeldn.app.raid_rewards.swsh_den`), fixes a bonus
item's count, and follows the boss when it changes; a boss no base den holds leaves it empty. Run from the app with a level-20
Wooloo boss and the template "Every reward of this den" at 7, a retail Sword won the raid and
received all ten rows: Exp. Candy XS x5, Exp. Candy S x1 and Dynamax Candy x1 (the bonus rows), and
seven drops at 7 each.

With `--raid-console-serves` the joined console serves the battle and the host answers as client 1
(`raid_battle.Master`):

| step | the host |
|---|---|
| BattleStart | lists the console first, so the console's client id is 0 |
| 0x7C port 0 | sends ping; answers the console's ping and pingSynced |
| framework objects | publishes object 0 = the console's ServerVersion record, object 1 = its own |
| 0x7C port 0 | sends its own ServerVersion (client id 1) |
| base 20000 | publishes the counter and its own body, 0000 / 00000100, then 0100 / 01000100, 01000200, 0200 / 02000200, each once the console mirrors the last body |
| object 8 | the console publishes it (24 bytes, a seed); the host answers EmptyCommand (10000 field 1) |
| battle commands | answered as a guest answers them, the action naming the host's Pokemon's first move |

An emulated Shield guest and a retail Sword each served a whole raid this way, won it and received
the host's Rewards, then sent the mesh leave request.

### Several consoles

Up to three consoles share one hosted lobby (`raid_host.RaidParty`). The host starts the battle once
every joined console has pressed ready; BattleStart lists the consoles in join order, then the host.
The first console serves. The host publishes framework object k as console k's ServerVersion record
and its own record last, and steps the base-20000 barrier once every console mirrors its body.

| layer | what a second console needs from the Pia host |
|---|---|
| Local Protocol | the session update reaches it; on loopback each station gets its own copy |
| mesh join response | byte 8, the active station maximum, above the stations already seated: with 2, the first guest answered the second's connection request with result 1 and the second showed error 2618-0502 |
| 0x84 | an ack on the port of the sender's stream; a station's stream is on the port of its station index (host 0, the first joiner 1, the second 2), and an unacked stream repeats without end |

The guests connect to each other directly: station connection requests, each other's snapshots on
0x84 and lobby messages on 0x80 addressed to the host and the other guest together. Two emulated
Shield guests joined one hosted lobby, readied and fought a raid served by the first to its
ten-turn end (command 0x1e), then both sent the mesh leave request.

## Event raids

A Wild Area Event is a BCAT delivery of den encounter and reward tables, one numbered index per
delivery. Project Pokemon's EventsGallery keeps each index under
`Released/Gen 8/SwSh/Wild Area Events/Index NNN/`, its `readme.md` naming the event each index carries.
`pokeldn/swsh/raid_event.py` reads one; `pokeldn.app.events_gallery` keeps a copy under game `swsh`.

| file | content |
|---|---|
| `normal_encount` | the Wild Area dens' event encounters |
| `normal_encount_rigel1`, `normal_encount_rigel2` | the Isle of Armor's and the Crown Tundra's (in Index 080 and 117, not in 010) |
| `drop_rewards`, `bonus_rewards` | the delivery's reward tables |
| `dai_encount` | the Dynamax crystal encounters [pkNX `NestHoleCrystalEncounterArchive`]; unread here |

Every file opens with a 0x20-byte header: the u8 BCAT index at 0, `ff ff ff ff` at 4, u32 `0x20` at 8,
u32 file size - 4 at `0x10`. The FlatBuffer runs from `0x20` to four bytes before the end, which
hold a CRC [pkNX `GameDumperSWSH.GetDistributionContents`].

An encounter file is a vector of tables (field 0): TableID u64, GameVersion u32 (1 Sword, 2 Shield),
two bytes, and Entries (field 4). Index 010's tables hold 30 entries each; every entry's vtable has
37 fields, read here as follows (field number, type, content).

| field | type | content |
|---|---|---|
| 0 | i32 | entry index, 1 to 30 |
| 1, 2, 3 | i32 | species, form, level |
| 4 | u16 | Dynamax level |
| 5 to 10 | u32 | absent in every Index 010 entry |
| 11 | u8 | ability: 0, 1, 2 the first, second, hidden; 3 either of the first two; 4 any |
| 12 | bool | Gigantamax |
| 13, 14 | u64 | drop and bonus reward table ids |
| 15 | [i32] | five chances in percent, star ranks 1 to 5; each rank's sum is 100 per version |
| 16 | i8 | gender: 0 drawn, else the record's gender + 1 |
| 17 | i8 | perfect IV count |
| 18 | u8 | shiny: 0 drawn, 1 never, 2 always |
| 19, 20 | u8 | 3 or 2 in Index 010; unread |
| 21 | i8 | nature, 25 drawn |
| 22 | i32 | 0 in Index 010 |
| 23 to 26 | u32 | the four moves |
| 27 | f32 | 1.4, 1.6, 1.9, 2.5, 3.0 at ranks 1 to 5 in Index 010; unread |
| 28, 29 | u32 | unread |
| 30 | u32 | 0 to 6; the shield, by PyNXBot's schema |
| 31 to 33, 34 to 36 | u32 | rate, move, value: two extra moves by PyNXBot's schema (move 150 at rate 0) |

Index 010 decodes to Wild Area Event #7 as its readme describes it: Gigantamax Toxtricity at ranks 3
to 5 (form 0 in Sword, form 1 in Shield), Gigantamax Milcery at every rank, Kingler and Grimmsnarl in
Sword, Orbeetle and Hatterene in Shield. Its rank-5 Toxtricity (level 60, Dynamax level 10, five
perfect IVs, moves 786, 586, 482, 506) is PKHeX's `encounter_sw_dist.pkl` record for index 10.

A delivery reward file is a vector of tables (field 0): TableID u64 and Entries (field 1), each entry
five u8 values for ranks 1 to 5 (fields 0 to 4) and a u16 item (field 5). The game's own tables,
`data_table.gfpak` files 7 (drops) and 6 (bonus), hold TableID, then entries of u32 entry index, u32
item and a u32 vector of five values (`pokeldn/swsh/data/nest_rewards.json`,
`scripts/gen_swsh_nest_data.py`). An encounter names its tables by id among both, the game's first
[pkNX `NestHoleDistributionEncounterTable`]; every Index 010 boss's bonus table and all but Milcery's
drop table are the game's.

A bonus value is a count, a drop value a percent chance. An emulated 1-star den host's Rewards
(`raid.DEN_REWARDS`) opened with the rows of the game's bonus table `0xf966212316b78eb6` at rank 1 at
their count (Exp. Candy XS x5, S x1, Dynamax Candy x1), then held two items, one each.
`raid_event.rewards` builds bonus rows, then one row per drop, rolling each drop's chance or keeping
them all.

`raid_event.boss_pk8` builds the boss on the den boss record `raid.boss_record` starts from: the
table's species, form, level, moves, Gigantamax and Dynamax level, an ability, IVs, nature, gender and
PID the table allows, and the party stats of [The boss record](#the-boss-record), from the personal
table in `pokeldn/swsh/data/species.json` (`scripts/gen_swsh_species_data.py`).

    bin/swsh_host.py --raid-event "FOLDER/Index 010" --raid-stars 5 --raid-event-boss 4 --raid-console-serves

Without `--raid-stars` or `--raid-event-boss` the host lists what it takes. `--raid-version` picks
the table's version (the advertisement's by default), `--raid-area` the den area, `--raid-event-drops
all` every drop; `--raid-reward` rows replace the event's.

## Dynamax Adventures

A Dynamax Adventure (Max Lair, `chika` in the binary) over local communication matches when every
player picks Invite Others at the Max Lair: the first opens a network, the others find it by scan and
connect. Y-Comm never lists it: the host advertises activity kind 0xFF, which Y-Comm's list skips.
The network carries local communication id `0x0100abf008968000`, scene 50000, NodeCountMax 4. The
host counts down from 3:00 under "Communicating"; with no guest it calls the adventure off for lack
of participants. Computer partners fill the empty seats once the adventure starts.

Two message holders run on the reliable 0x80 port 0, each field a holder with one field 1:

- id 7000, `net_contents.chika.protocol_buffers.ChikaAsyncDataHolder` (descriptors `0x1c3adb5`,
  `0x2066654`), the lobby;
- id 8000, `net_contents.underground.protocol_buffers.UndergroundAsyncDataHolder` (descriptors
  `0x1c36fab`, `0x20681cc`), between battles.

Den messages (id 2000) sent into a Max Lair lobby are acknowledged and seat no one. The battles run on
0x7C as a den raid's do (ping 80, then 40000, 10000 and 20000 messages), with two differences:

- the action is entry 1 `01 ff ff ff ff ff ff ff`, entry 2 the move as in a den raid, the other nine
  entries `0xff`; entry 2's byte 3 is `0x80` on a Dynamax turn, and the state message before it then
  carries state 1 instead of 2;
- after the guest's Pokemon fainted, the host sent type 0x04 with data `01 00 ff ff ff ff`; the guest
  answered with an 88-byte action whose entry 2 is zero.

`pokeldn/swsh/lair.py` is the guest's side of both holders. `bin/swsh_connect.py --lair-join`
seated as player 1 in an emulated Shield's lobby and in a retail Sword's, took the first offer
place the host left (rentals go in turns, the host's first), built as `lair.rental_pk8` builds one
from the seed's row, and fought as the player's partner in the first battle. The retail host
accepted the built rental.

A rental is the recorded rental's record with the row's species, form, level 65 and moves, four IVs
of 31 and the others random, a random nature, ability slot 1 or 2, gender, PID and encryption
constant; OT Scientist, Poke Ball, met at level 65. Both recorded rentals' party stats follow from
their IVs and nature at level 65 with no Dynamax bonus.

### The lobby holder, id 7000

Measured between two emulated Shields, a whole adventure won. A record that names a player starts
with its Pia constant id (u64) and its player index byte; computer partners have a zero id and
indexes 2 and 3.

| field | name | size | content |
|---|---|---|---|
| 1 | ChikaTimeLimit | uint32 | seconds left, from the host |
| 2 | ChikaPlayerInfo | 48 | 12 zero bytes, UTF-16 name in 13 characters, then `02 00 00 00 00 2d 00 00 00`; sent zlib-compressed (reliable flag 0x10) |
| 3 | ChikaBattleReady | 16 | byte 8 is 1 once the player pressed ready; byte 12 is 1 once the adventure starts |
| 4 | ChikaSelectPokemon | 360 | 8 zero bytes, u32 the rental's place in the shared offer, the rental as an encrypted party PK8 (level 65, OT Scientist), four zero bytes |
| 5 | ChikaBattleStart | 32 | the human players' constant ids, the guest's first |
| 8 | ChikaBattleSeed | uint64 | from the host; seeds the rental offer and the encounters ([The adventure seed](#the-adventure-seed)) |
| 9 | ChikaRentalPokemonSeed | uint64 | from the host, before the rental choice |
| 11 | ChikaPlayerNumber | 40 | four constant ids (host, guest, zero, zero), then the player indexes `00 01 02 03` |
| 12 | ChikaBigBoss | 16 | byte 12 is 1; each player sends its own with PlayerInfo |
| 13 | ChikaBigBossFixed | 4 | u32 species of the adventure's legendary (480 Uxie in the recording) |

Fields 6, 7 and 10 were not sent. Order: PlayerInfo, BattleReady and BigBoss from each player on
joining; BattleReady with byte 8 set; then from the host BattleStart, BattleSeed,
RentalPokemonSeed, PlayerNumber, BattleReady with byte 12 set and BigBossFixed; then each player's
SelectPokemon.

### The adventure holder, id 8000

| field | name | size | content |
|---|---|---|---|
| 1 | UndergroundWaySelect | 16 | constant id, player index, chosen path |
| 3 | UndergroundWayResult | 1 | the path taken, from the host |
| 4 | UndergroundTradeWant | 16 | constant id, player index, 1 to swap for the caught Pokemon |
| 6 | UndergroundTradeResult | 360 | the swapping player's constant id, index, two bytes, then the new Pokemon as an encrypted party PK8 at +11 |
| 10 | UndergroundRaidCapture | 16 | constant id, player index, byte 9 |
| 11 | UndergroundRaidWant | 16 | constant id, player index, 1 to take the caught Pokemon |
| 12 | UndergroundRaidResult | 360 | 8 zero bytes, the taking player's index (`ff` for none), a byte, then the Pokemon as an encrypted party PK8 at +10 |
| 14 | UndergroundTimeLimit | 8 | u32 seconds left, u32 stage, from the host three times a second |

Fields 2, 5, 7, 8, 9 and 13 were not sent. Each guest sends its own WaySelect, TradeWant,
RaidCapture and RaidWant; the host answers with its own and one for each computer partner, then the
result. When one player left after the win, the other emulator showed error 2618-0006.

### Hosting an adventure

`bin/swsh_host.py --lair-legendary SPECIES [--lair-seed N]` (`pokeldn/swsh/lair_host.py`) advertises a
Max Lair network from an emulated Shield host's advertisement (scene 50000), exchanges snapshots as a
link trade does, then sends the emulated host's lobby: PlayerInfo, BattleReady and BigBoss, the time
limit three times a second, ready; once the guest readies, BattleStart, BattleSeed,
RentalPokemonSeed and PlayerNumber; once the guest answers started, BattleReady started and
BigBossFixed. Five seconds later it leaves as a hosting Sword does ([Leaving](swsh_session.md#leaving)):
MIGRATION_START `44 00 01`, the update session with its host-migration byte, START_HOST_MIGRATION
every 0.33 s, and it closes the network once the console has left or after 10 s.

The app's Dynamax Adventure (Host) tool runs these flags: the legendary, an optional Link Code and
the adventure seed. Its seed picker shows the three rentals and ten encounters `lair.adventure`
gives for a seed, draws a new one, and searches random seeds for one whose offer holds a chosen
rental (about one seed in 75 offers a given rental).

An emulated Shield that joined this way showed the three rentals `lair.adventure(seed)` gives for
places 0 to 2. Rentals are chosen in turns, the host's first: the screen read "POKELDN is
deciding..." until the network closed, then a computer partner took POKELDN's seat and picked a
rental, and the player picked theirs. The legendary at the end of the map was the species
BigBossFixed named (Mewtwo, 150), and the guest's own BigBoss was all zero. A retail Sword over the ESP32 board joined
the same way, readied and answered started, and its adventure went on after the network closed; the map's
last Pokemon carried the type of the legendary BigBossFixed named (Lugia, 249).

A Max Lair Link Code is set with + at the receptionist. The advertisement carries CRC32 of the
code's decimal value, leading zeros dropped (`7777` for 0000 7777); a retail Sword searching with
0000 7777 joined a lobby advertising it, and one searching with no code never listed it. With a
code, a host that closed its network without MIGRATION_START left the guest on error 2618-0006 at
the rental screen (2 of 2); with the handover the guest left the network 0.1 s after
MIGRATION_START and its adventure went on. With no code, both leaves went on.

### The adventure seed

The adventure's Pokemon are the rows of RomFS `bin/appli/chika/data_table/underground_exploration_poke.bin`,
a FlatBuffer of 273 rows: 226 rentals and encounters at level 65, then 47 legendaries at level 70
(boss flag set). A row carries species, form, level and four moves.

ChikaBattleSeed sets the six-rental offer and the encounters; `lair.adventure(seed)` computes them.
Xoroshiro128+ is seeded with the u64 and `0x82A2B175229D6A5B`. Each pick seeds MT19937 with the next
32-bit output, shuffles the 273 row indexes (index i swaps with i plus a draw up to 272 - i, masked
by `0x1ff` and redrawn while above), and takes the first row that is not a legendary and not already
picked. Four picks, then one draw of 0 to 2 before each of the next two picks and one more, each
while more than 2, 1 and 0 computer partners are seated, then draws of 0 to 2 and 0 to 9, then ten
encounter picks, each followed by one more output when the row has two types. With three computer
partners a draw of 0 to 27 comes first.

| seed | partners | offer, places 0 to 2 | measured |
|---|---|---|---|
| `0x000000000a577170` | 2 | Alcremie, Lopunny, Grimmsnarl | the host took place 0, the guest place 2; first battle Rotom |
| `0x2721e8ab192583ff` | 2 | Frosmoth, Whiscash, Charjabug | an emulated Shield guest's offer |
| `0x0bdda7b984481ac3` | 2 | Crawdaunt, Armaldo, Slowking | on a retail Sword, the partner in our seat took Crawdaunt and the player Slowking |
| `0x0e9dfb0030f07a8e` | 2 | Flareon, Eldegoss, Ditto | a retail Sword's offer, the seed chosen in the app for its Ditto |

Places 3 to 5 of that retail seed are Doublade, Lampent and Combusken; its two other computer
partners brought a Copperajah and a Beheeyem, so where their Pokemon come from is unknown.
A taken rental is replaced on the screen for the next player. With seed `0x0e9dfb0030f07a8e` (places
3 to 5 Vileplume, Glalie, Orbeetle) a retail Sword showed Glalie in place of the Eldegoss the
partner in our seat took, then Dedenne in place of the player's Ditto; what draws the replacements
is unknown.
ChikaRentalPokemonSeed gives none of these. A Jolteon a guest swapped for was not among the ten
encounters of its seed; which encounters a path meets is unknown.

## Leaving

Once its player leaves the reward screens, a retail Sword host closes the network with
START_HOST_MIGRATION every 0.33 s for 10 s, as after a link trade ([Leaving](swsh_session.md#leaving)).
A guest that does not leave holds the host's player frozen in the overworld until the timeout;
`--leave-with-host` leaves on the first one.

## Unresolved

- Whether a console that is not the Pia host would publish framework objects 0 to 7; in every
  recording and hosted raid the Pia host published them.
- Several consoles in one hosted lobby on retail hardware; measured on emulated Shields only.

- The meaning of PlayerInfo's u32 and final bytes.
- The action's other ten entries, Dynamax, and the target codes beyond 8 and 2. Replayed unchanged, a
  recorded Water Gun action makes any guest Pokemon use Water Gun, on a retail Sword host too.
- Dynamax Adventures: PlayerInfo's trailing bytes, BigBoss, the byte after the player index in
  RaidCapture and the result records, and the unsent fields of both holders.
- Whether a retail guest takes an event boss from a den advertisement whose den record is zero, and
  what a retail event den host writes in the den kind bits and the den record.
- The encounter fields read above as unread or by PyNXBot's names.

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
in a console's lobby.

## The network

| field | value |
|---|---|
| LDN scene id | 60006 (65535 in the overworld) |
| participants | 1 of 4 when opened |
| advertise data byte `0x97` | `0x11` |
| Pia session maximum | 4 (`0x0110e5e0`, called from the den lobby at `0x01031c74`) |
| advertise `0xb0` and `0xd4` | the boss and the den record ([The den record](#the-den-record)) |

The den lobby's code sits in `0x0102aba4..0x010370cc` (`View_NestHole`, `StateGuestReady`,
`StateHostReady`). A guest's Y-Comm list leaves out a raid whose advertisement carries the guest's
own device id and account uid.

## The lobby messages

Every lobby message is id 2000, `net_contents.nesthole.protocol_buffers.NestholeAsyncDataHolder`
(descriptors `0x1bfde43`, `0x20677b0` in `main`). Each field is a holder with one `bytes` field 1.

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
the others go out plain. `pokeldn/swsh/raid.py` builds every field. The boss record carries the
boss in full; what the BattleSeed feeds is unread (the den's raid generator applied to it gives
neither the boss's encryption constant nor its PID).

## The guest's sequence

Snapshot exchange on 0x84 (the host's first); PlayerInfo, BattleReady and SelectPokemon on 0x80
port 0; BattleReady with byte 8 set on ready. Once every player is ready the host sends
BattleStart, SelectPokemon, BossPokemon, Rewards, BattleSeed and BattleReady with bytes 8 and 12 set;
the guest answers with its SelectPokemon and the same BattleReady, and the battle starts on 0x7C
(ping 80 on port 0, framework 40000 on port 1, then 10000 and 20000 per turn). A guest that stops
after BattleReady with byte 8 set leaves a retail Sword host on "Connexion en cours", ending in
error 2-ALZAA-0016.

## The battle

The host runs the battle; a guest answers on 0x7C (`pokeldn/swsh/raid_battle.py`). From the mesh
join the guest runs SyncClockProtocol 0x1C (a request a second) and sends one ClockProtocol 0x77
request (`00` x16 then `00 6f`), both to destination bitmap 1.

| port | message | the guest |
|---|---|---|
| 0 | sync 80: ping, pingReply, pingSynced | answers ping with ping and pingReply, pingSynced with pingSynced |
| 1 | 40000, content 0's framework: field 2 base (10000 or 20000, absent for 0), 3 station constant id, 4 clock, 5 body | after its pingSynced sends three base-10000 / base-20000 pairs (bodies `00000000`, `000018fc`), then mirrors each host base-20000 body under its own station id |
| 0 | 10000, field 3 {1 station, 2 slot, 3 version} | sent once the host lists its own seat (base 0, 16-byte body: constant id, slot, version byte 0x6e) |
| 0 | 10000, field 1 empty | sent after the host's base-8 message (24-byte body, the battle's seed) |
| 0 | 20000, field 1 {1 sender, 2 slot, 3 counter, 4 data} | answers every host command |
| 0 | 20000, field 3 {1 state, 2 slot} | sends {1: 2, 2: slot} before its action |

A host command's data opens with four u16: serial, type, length, a tag. The guest answers with the
same serial, type and tag, length 4 and four zero bytes, except type 0x02 (the state message, then
its action: serial, 0x02, 0x58, tag, 88 bytes) and type 0x21 (the end: sender 1, data
`0000 1e00 0000 2f00`). Host types seen: 0x01, 0x0d, 0x07, 0x0e, 0x02, 0x10, 0x09 (the turn's log,
zlib), 0x04, 0x11, 0x0a, 0x21.

### Which station serves

The server is the station whose ServerVersion record wins a table each console keeps. ServerVersion
is `btl.net.protocol_buffers.BtlDataHolder` (id 10000) field 3: station id u64, client id u32,
version u32 (version `0x6e`). Eight slots of {station, client id, version, valid} sit at battle
network object `+0x190 + 16 * i`; `0x8b4030` picks the first valid slot with the highest version and
`0x8b1990` (IsServer) compares its client id with the console's own. A console's client id is its
position in BattleStart (`0x1025120`). The collecting station publishes the slots as 40000
framework objects 0 to 7.

### The action

The 88-byte action is eleven 8-byte entries. Entry 2 as a little-endian u24 is
`move id << 13 | target << 8 | 0xc1`.

| move | entry 2 | target |
|---|---|---|
| Pound (1) | `c1 28 00` | 8 |
| Bind (20) | `c1 88 02` | 8 |
| Growl (45) | `c1 a2 05` | 2 |
| Water Gun (55) | `c1 e8 06` | 8 |

Growl hits every foe and carries target 2; single-target moves carry 8. A turn on which the guest
could not act sends entry 2 as zero. `raid_battle.action(move, target)` builds it; `--raid-move N`
picks the move slot. The 0x7C acknowledgement carries 32 slots; only slot 0 tracks the guest's
stream, so a resend gated on the maximum over slots never resends.

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
flag (`0x00ea5160`). A species of 0 skips those checks. The rank must not exceed the guest's own
rank, from its badge count, when the byte at `0x02510b2c` is 1 or 2 and the host is not a friend.
The record at `0xB0` is range-checked only. A guest drops a station whose device id and account uid
(`0x1F` to `0x3E`) both equal its own (`0x0111b160`). `pokeldn/swsh/data/nest_slots.json` holds the
1.3.2 slots (`scripts/gen_swsh_nest_data.py`); `raid.den_advert` points the den record at a slot
holding the boss, or zeroes it.

### The boss record

A guest checks BossPokemon and Rewards before it sends its started BattleReady (`0x01030d14`); a
failed check leaves with 2-ALZAA-0016.

| check | code | passes when |
|---|---|---|
| the boss | `0x01032270` | species, form and party `+0x156` (1 normal, 2 Gigantamax) equal the entry the den record names: kind 0 the base table `0xDE`, slot `0xE0` of the advertised version; kinds 1 to 3 the guest's own saved event encounters, slot `0xE0`; kind 4 its saved crystal encounters |
| the rewards | `0x01032570` | every pair with an item and a count is a bonus row of the slot's bonus table at exactly its count for the advertised rank, or an item of its drop table with a chance at that rank (count free) |

Level, moves, IVs, PID, ability, shininess and trainer fields are not compared. A zero den record
names kind 0, table 0, slot 0 (Tyrogue). Observed on a retail Sword guest: a boss record with
trainer data, a party Dynamax type of 0, or a zero den record for a boss no base den holds (Mew, an
event's Gigantamax Toxtricity) leaves with 2-ALZAA-0016 although the raid is listed; a den boss's
record with only the species changed, and a boss built by `raid.boss_record`, are accepted. Base dens
hold no legendary or mythical Pokemon, so a hosted boss is a species, form and Gigantamax state
`nest_slots.json` lists; `raid.den_advert` switches the advertised version when only the other holds
the boss, and shows an event boss as the base den slot holding its species. `raid.reward_choices`
lists what the slot allows at a rank; `raid.den_rewards` builds the slot's own rows.

In den bosses the party HP stat and current HP are the plain HP stat times
`(150 + 5 * Dynamax level) / 100`, rounded down; the other stats are plain. The Dynamax level is at
`+0x90`, the ability slot bit at `+0x16` bits 0 to 2, and the experience is the level's least.

## Hosting

`bin/swsh_host.py --raid-boss PK8 --raid-console-serves` hosts a den lobby a console joins from its
Y-Comm list (`pokeldn/swsh/raid_host.py`). The advertisement and snapshot are an emulated Shield den
host's with a fresh station profile, the board's name and no account ids
(`pokeldn/swsh/data/raid_advert.bin`, `raid_snapshot.bin`; `--advert` and `--snapshot` replace
them). `--raid-boss` takes any PK8 through `raid.boss_record`. The host's snapshot goes out before the
guest's. `--raid-reward ITEM:COUNT` fills Rewards and `--raid-seed` BattleSeed; the host refuses a
row the advertised den slot does not give at its rank and prints what the slot gives.

The app's Max Raid (Host) tool runs these flags with a boss (or a Wild Area Event boss a base den
holds, `raid_event.hostable`), the player's Pokemon and up to 15 reward rows; without rows the host
gives the den slot's own rewards. Its reward editor offers only the items of the den slot the boss is
advertised from (`raid.boss_den`, `pokeldn.app.raid_rewards.swsh_den`) and fixes a bonus item's count.

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

A retail Sword served a whole raid this way, won it and received the host's Rewards, then sent the
mesh leave request.

### Several consoles

Up to three consoles share one hosted lobby (`raid_host.RaidParty`). The host starts the battle once
every joined console is ready; BattleStart lists the consoles in join order, then the host. The
first console serves. The host publishes framework object k as console k's ServerVersion record and
its own last, and steps the base-20000 barrier once every console mirrors its body.

A second console needs from the Pia host: the session update delivered to it (on loopback each
station gets its own copy); mesh join response byte 8, the active station maximum, above the stations
already seated (otherwise result 1 and error 2618-0502); and an ack on the port of the sender's
stream (host 0, first joiner 1, second 2), since an unacked stream repeats without end.

The guests connect to each other directly: station connection requests, each other's snapshots on
0x84 and lobby messages on 0x80 addressed to the host and the other guest together.

## Event raids

A Wild Area Event is a BCAT delivery of den encounter and reward tables, one numbered index per
delivery. Project Pokemon's EventsGallery keeps each under
`Released/Gen 8/SwSh/Wild Area Events/Index NNN/`. `pokeldn/swsh/raid_event.py` reads one;
`pokeldn.app.events_gallery` keeps a copy under game `swsh`.

| file | content |
|---|---|
| `normal_encount` | the Wild Area dens' event encounters |
| `normal_encount_rigel1`, `normal_encount_rigel2` | the Isle of Armor's and the Crown Tundra's (in Index 080 and 117, not in 010) |
| `drop_rewards`, `bonus_rewards` | the delivery's reward tables |
| `dai_encount` | the Dynamax crystal encounters [pkNX `NestHoleCrystalEncounterArchive`]; unread |

Every file opens with a 0x20-byte header: the u8 BCAT index at 0, `ff ff ff ff` at 4, u32 `0x20` at 8,
u32 file size - 4 at `0x10`. The FlatBuffer runs from `0x20` to four bytes before the end, which
hold a CRC [pkNX `GameDumperSWSH.GetDistributionContents`].

An encounter file is a vector of tables (field 0): TableID u64, GameVersion u32 (1 Sword, 2 Shield)
and Entries (field 4). Entry fields: 0 index; 1, 2, 3 species, form, level; 4 Dynamax level; 11
ability (0, 1, 2 first, second, hidden; 3 either of the first two; 4 any); 12 Gigantamax; 13, 14 drop
and bonus table ids (u64); 15 five rank chances in percent (each rank sums to 100 per version); 16
gender (0 drawn, else gender + 1); 17 perfect IV count; 18 shiny (0 drawn, 1 never, 2 always); 21
nature (25 drawn); 23 to 26 the four moves; 30 the shield and 31 to 36 two extra moves, by PyNXBot's
schema.

Other fields are unread. Index 010 decodes
to Wild Area Event #7: Gigantamax Toxtricity at ranks 3 to 5, Gigantamax Milcery at every rank,
Kingler and Grimmsnarl in Sword, Orbeetle and Hatterene in Shield; its rank-5 Toxtricity equals
PKHeX's `encounter_sw_dist.pkl` record for index 10.

A delivery reward file is a vector of tables (field 0): TableID u64 and Entries (field 1), each entry
five u8 values for ranks 1 to 5 (fields 0 to 4) and a u16 item (field 5). The game's own tables,
`data_table.gfpak` files 7 (drops) and 6 (bonus), hold TableID, then entries of u32 entry index, u32
item and a u32 vector of five values (`pokeldn/swsh/data/nest_rewards.json`,
`scripts/gen_swsh_nest_data.py`). An encounter names its tables by id among both, the game's first
[pkNX `NestHoleDistributionEncounterTable`]. A bonus value is a count, a drop value a percent chance.
A 1-star den's Rewards (`raid.DEN_REWARDS`) open with the rows of bonus table `0xf966212316b78eb6` at
rank 1 at their count (Exp. Candy XS x5, S x1, Dynamax Candy x1), then two items, one each.
`raid_event.rewards` builds bonus rows, then one row per drop, rolling each drop's chance or keeping
them all.

`raid_event.boss_pk8` builds the boss on `raid.boss_record`: the table's species, form, level, moves,
Gigantamax and Dynamax level, and an ability, IVs, nature, gender and PID the table allows, with
party stats from `pokeldn/swsh/data/species.json` (`scripts/gen_swsh_species_data.py`).

    bin/swsh_host.py --raid-event "FOLDER/Index 010" --raid-stars 5 --raid-event-boss 4 --raid-console-serves

Without `--raid-stars` or `--raid-event-boss` the host lists what it takes. `--raid-version` picks
the table's version (the advertisement's by default), `--raid-area` the den area, `--raid-event-drops
all` every drop; `--raid-reward` rows replace the event's.

## Dynamax Adventures

A Dynamax Adventure (Max Lair, `chika` in the binary) over local communication matches when every
player picks Invite Others at the Max Lair: the first opens a network, the others scan and connect.
Y-Comm never lists it: the host advertises activity kind 0xFF. The network carries local
communication id `0x0100abf008968000`, scene 50000, NodeCountMax 4 (Pia maximum called from
`0x00bd9b30`, in `ChikaMatchingState*` `0x00bd1978..0x00bda158`). The host counts down from 3:00
under "Communicating"; with no guest it calls the adventure off. Computer partners fill the empty
seats once the adventure starts.

Two message holders run on the reliable 0x80 port 0, each field a holder with one field 1:

- id 7000, `net_contents.chika.protocol_buffers.ChikaAsyncDataHolder` (descriptors `0x1c3adb5`,
  `0x2066654`), the lobby;
- id 8000, `net_contents.underground.protocol_buffers.UndergroundAsyncDataHolder` (descriptors
  `0x1c36fab`, `0x20681cc`), between battles.

Den messages (id 2000) sent into a Max Lair lobby are acknowledged and seat no one. The battles run on
0x7C as a den raid's do, with two differences:

- the action is entry 1 `01 ff ff ff ff ff ff ff`, entry 2 the move as in a den raid, the other nine
  entries `0xff`; entry 2's byte 3 is `0x80` on a Dynamax turn, and the state message before it then
  carries state 1 instead of 2;
- after the guest's Pokemon fainted, the host sends type 0x04 with data `01 00 ff ff ff ff`; the
  guest answers with an 88-byte action whose entry 2 is zero.

`pokeldn/swsh/lair.py` is the guest's side of both holders; `bin/swsh_connect.py --lair-join` seats as
player 1 and takes the first offer place the host left (rentals go in turns, the host's first). A
rental built by `lair.rental_pk8` is the recorded rental's record with the row's species, form,
level 65 and moves, four IVs of 31 and the others random, a random nature, ability slot 1 or 2,
gender, PID and encryption constant; OT Scientist, Poke Ball, met at level 65, party stats with no
Dynamax bonus. A retail Sword host accepted it.

### The lobby holder, id 7000

A record that names a player starts with its Pia constant id (u64) and its player index byte;
computer partners have a zero id and indexes 2 and 3.

| field | name | size | content |
|---|---|---|---|
| 1 | ChikaTimeLimit | uint32 | seconds left, from the host |
| 2 | ChikaPlayerInfo | 48 | 12 zero bytes, UTF-16 name in 13 characters, then `02 00 00 00 00 2d 00 00 00`; zlib-compressed (reliable flag 0x10) |
| 3 | ChikaBattleReady | 16 | byte 8 is 1 once the player pressed ready; byte 12 is 1 once the adventure starts |
| 4 | ChikaSelectPokemon | 360 | 8 zero bytes, u32 the rental's place in the shared offer, the rental as an encrypted party PK8, four zero bytes |
| 5 | ChikaBattleStart | 32 | the human players' constant ids, the guest's first |
| 8 | ChikaBattleSeed | uint64 | from the host; seeds the rental offer and the encounters ([The adventure seed](#the-adventure-seed)) |
| 9 | ChikaRentalPokemonSeed | uint64 | from the host, before the rental choice |
| 11 | ChikaPlayerNumber | 40 | four constant ids (host, guest, zero, zero), then the player indexes `00 01 02 03` |
| 12 | ChikaBigBoss | 16 | byte 12 is 1; each player sends its own with PlayerInfo |
| 13 | ChikaBigBossFixed | 4 | u32 species of the adventure's legendary |

Fields 6, 7 and 10 are not sent. Order: PlayerInfo, BattleReady and BigBoss from each player on
joining; BattleReady with byte 8 set; from the host BattleStart, BattleSeed, RentalPokemonSeed,
PlayerNumber, BattleReady with byte 12 set and BigBossFixed; then each player's SelectPokemon.

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

Fields 2, 5, 7, 8, 9 and 13 are not sent. Each guest sends its own WaySelect, TradeWant, RaidCapture
and RaidWant; the host answers with its own and one for each computer partner, then the result.

### Hosting an adventure

`bin/swsh_host.py --lair-legendary SPECIES [--lair-seed N]` (`pokeldn/swsh/lair_host.py`) advertises a
Max Lair network from an emulated Shield host's advertisement (scene 50000), exchanges snapshots as a
link trade does, then sends the lobby: PlayerInfo, BattleReady and BigBoss, the time limit three
times a second, ready; once the guest readies, BattleStart, BattleSeed, RentalPokemonSeed and
PlayerNumber; once the guest answers started, BattleReady started and BigBossFixed. Five seconds
later it leaves as a hosting Sword does ([Leaving](swsh_session.md#leaving)): MIGRATION_START
`44 00 01`, the update session with its host-migration byte, START_HOST_MIGRATION every 0.33 s, and it
closes the network once the console has left or after 10 s.

The app's Dynamax Adventure (Host) tool runs these flags: the legendary, an optional Link Code and
the seed. Its seed picker shows the three rentals and ten encounters `lair.adventure` gives for a
seed, draws a new one, and searches seeds for a chosen rental (about one in 75 offers a given one).
The legendary at the end of the map is the species BigBossFixed names; the guest's own BigBoss is
all zero. Rentals are chosen in turns, the host's first, and a computer partner takes the seat of a
player who has left.

A Max Lair Link Code is set with + at the receptionist. The advertisement carries CRC32 of the
code's decimal value, leading zeros dropped (`7777` for 0000 7777); a search with a different code
or none never lists the lobby. With a code, a host that closed its network without MIGRATION_START
left the guest on error 2618-0006 at the rental screen; with the handover the guest left 0.1 s after
MIGRATION_START and its adventure went on.

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

A taken rental is replaced on the screen for the next player; what draws the replacements is
unknown, as is where the computer partners' own Pokemon come from. ChikaRentalPokemonSeed gives
none of these. Which encounters a path meets is unknown.

## Leaving

Once its player leaves the reward screens, a retail Sword host closes the network with
START_HOST_MIGRATION every 0.33 s for 10 s, as after a link trade ([Leaving](swsh_session.md#leaving)).
A guest that does not leave holds the host's player frozen in the overworld until the timeout;
`--leave-with-host` leaves on the first one.

## Unresolved

- Whether a console that is not the Pia host would publish framework objects 0 to 7.
- Several consoles in one hosted lobby on retail hardware; measured on emulated Shields only.
- The meaning of PlayerInfo's u32 and final bytes.
- The action's other ten entries, Dynamax, and the target codes beyond 8 and 2. Replayed unchanged, a
  recorded Water Gun action makes any guest Pokemon use Water Gun, on a retail Sword host too.
- Dynamax Adventures: PlayerInfo's trailing bytes, BigBoss, the byte after the player index in
  RaidCapture and the result records, and the unsent fields of both holders.
- Whether a retail guest takes an event boss from a den advertisement whose den record is zero, and
  what a retail event den host writes in the den kind bits and the den record.

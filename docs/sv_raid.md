---
title: Tera Raids
parent: Scarlet and Violet
nav_order: 1
---

# Tera Raids

A local Tera Raid is a Scarlet/Violet session of up to four stations on LDN scene 7. The host runs
the lobby, then sends every participant one bootstrap message holding the four players' Pokemon, the
boss and its RaidPoint, and each console fights the battle on its own. `bin/sv_host.py --raid-seed`
hosts a raid a retail console joins, `bin/sv_join.py --raid-pokemon` joins one a console hosts; in
both, the program's player leaves as the battle begins and its Pokemon fights on as the console's
AI partner. Addresses are offsets into the decompressed `main` of Scarlet 4.0.0; Violet 4.0.0 has the
same code at the same offsets ([docs/sv.md](sv.md)).

## Hosting

The host advertises scene 7, four participants and Link Code 4970. The console joins from
X, Poke Portal, Tera Raid Battle, offline search. `--raid-seed` with the four context flags picks the
raid ([The seed](#the-seed)), `--raid-pokemon` is the party record our player brings (PKHeX checks
it), and `--raid-reward ITEM:QUANTITY`, repeated, replaces the seed's rewards with rows of items the
Scarlet/Violet bag holds (the PKHeX helper's `bag` list: every pouch but the key items, unreleased
items out). The app's Tera Raid (Host) tool carries the flags below.

    --channel 1 --scene-id 7 --max-participants 4 --code 4970 --scarlet-response --session-flags 0
    --session-packet-id 1 --no-session-ack --join-seq 0 --update-seq 0 --update-delay 0.02
    --rtt-probe --clock --net-stations 4 --record-delay 0.1 --record-spacing 0.003
    --host-player-id 00000000000000010000000000000000

In raid mode the host differs from a trade host in what it addresses and when:

| | a raid host |
|---|---|
| mesh-addressed messages (RTT, 0x80, 0x81), the Session station lists | to the subnet broadcast, not the console's address (unicast over ldn_mitm, which carries no broadcast to a peer) |
| Net 0x11 | one sequence, repeated until the 0x12 |
| the station list's console entry | the player the console's join request named; with a placeholder player the console is seated and absent from the lobby |
| the station list | resent every 2 s until the console's type 6 |
| the opening | only after that type 6: the eleven first bulk acks, the 0x81 port 5 open and an RTT request in one packet; the 0x81 port 1 open, the channel table and the port-2 type 6; the identity 20 ms later, one record every 3 ms |
| the port-2 type 3 | answered with two type 9s: the host's station with code 0, the console's with code 1 |

The opening's 0x7C, 0x81 port 5 and 0x80 port 2 messages repeat every 0.25 s until acknowledged,
and every ack the host sends declares the lowest unacknowledged sequence of the stream.

A random player id of the form `10 00` and fourteen random bytes drew no type 6 from a retail
console; the anonymous id `00000000000000010000000000000000` (`pia_connect.DEFAULT_PLAYER_ID`) seated
it.

## The lobby

A raid message is a game message on 0x80 port 0: a u16 handler key, a kind byte, a step byte
([The trade](sv.md#the-trade)), then the game serializer's header and a payload.

| bytes | field |
|---|---|
| 0 | handler key, u16 |
| 2 | kind, step |
| 4 | a counter, u16, per sender: a retail host's lobby runs 0x0105 to 0x010e, a guest's 1, 2, 3... |
| 6 | compression, u32: 0 none, 2 LZ4 |
| 10 | the payload's plain size, u32 |
| 14 | four bytes no reader is known for (zero, or stale bytes in retail messages) |
| 18 | the payload |

| key | kind | what |
|---|---|---|
| 0x3380 | 0x2c | the raid's descriptor: species (DevID), form, stars, Tera type, gender, the encounter's record number |
| 0x3380 | 0x2d | a participant's state: 0x18 idle, 0x01 ready, 0x0c the host's start, 0x0d a guest's answer to it |
| 0x3380 | 0x2e | a participant's Pokemon, its encrypted 344-byte party record |
| 0x3380 | 0x2f | the battle bootstrap |
| 0x3380 | 0x30 | the lobby timer, in seconds left (0x91 downwards) |
| 0x0132 | 0x6e, 0x73 | a console loading the battle, then loaded |
| 0x3480 | 0x93 | the battle begins |
| 0x007b | 0x13 | the battle-start messages a host sends after 0x3480 |

The channel table a raid host announces on 0x7C port 1 holds six keys, zlib-compressed: a Link
Trade's four (`0x007b`, `0x0132`, `0x0232`, `0x0332`) and `0x3380`, `0x3480`. A retail guest
announces them as two messages: the four, then the raid's two 0.79 s later. Port 2 carries a type 6
from the host: the type 7's session block under kind 5 and capacity 4, then a list of four slots
with the host's station id in the first (`port2.build_session`).

`pokeldn.sv.raid.RaidHost` releases the host's twenty messages in order, each at its time from the
port-2 answer and after the console's previous step:

| seq | message | released by |
|---|---|---|
| 1 | descriptor (zlib, INITIALIZED) | the console's own lobby Pokemon (0x2e) |
| 2, 3 | state 0x18, our Pokemon | |
| 4, 5, 6 | timer 0x91, 0x90, 0x8f | 0.73, 1.76, 2.75 s |
| 7 | state 0x01 | 3.19 s |
| 8, 9 | timer 0x8e, 0x8d | 3.76, 4.79 s |
| 10 | state 0x0c, the start | 5.39 s |
| | Net 0x50, property state 7 | the console's state 0x0d |
| | Session station list, sequence 1 | the console's Net 0x51 |
| 11, 12 | the bootstrap, two fragments | the console's type 6 for it |
| 13 | loaded, `0x320173` | the console's 0x6e or 0x73 |
| 14 | the battle begins, `0x803493` | the console's 0x73 |
| 15 to 20 | the battle-start messages | the console's 0x93; then 0, 0.10, 0.12, 0.16, 0.18 s |

A gated message leaves 50 ms after its milestone; the Net 0x50 and the station list repeat every
0.5 s until answered, and the raid messages every 0.5 s until acknowledged. A retail console once
answered the bootstrap with 0x73 and no 0x6e, so message 13 waits for either.

Five seconds after message 20 the host hands the console its network as a leaving retail host does
([docs/sv.md](sv.md#leaving)): Session type 7 naming the console, every second until its type 8;
Net 0x11 in its is-migrating form, every 0.5 s until its 0x12; NetStartHostMigration `01400000`
every 0.3 s until the console leaves the network or 4 s pass. A host that destroyed its network 5 s
after message 20 instead drew 2318-0006 on the console's screen at the battle's opening in one of
four retail raids, the battle going on offline after it.

The Net 0x50 is the trade host's property body (`NET_PROPERTY_BODY`) with sequence 1, the network
id, byte 27 set to 7 and the host's 132 application bytes at +38, zlib-compressed under message flags
0x31. Sent uncompressed under 0x31, it drew no 0x51.

## The battle bootstrap

Message 0x2f carries a 0xaa0-byte record, LZ4-compressed (the block format alone, `pokeldn.sv.lz4`):

| offset | size | what |
|---|---|---|
| 0x000 | 4 x 0x158 | the four participants' party records, encrypted, the host's in slot 0 |
| 0x560 | 0x158 | the boss's party record |
| 0x6b8 | 0x3e8 | the RaidPoint |

The serializer `0xe327fc` writes the five records from the message object's `+0x440`, `+0x448`,
`+0x450`, `+0x458` and `+0x50` through `0xe329b4` (0x158 bytes each), then four quadwords from
`+0x58` and 0x3c8 bytes from `+0x78`. The object (0x460 bytes) is made by `0x18bb4fc`, typed by
`0x18bb5f8`; `0x1592b7c` writes the serializer header and picks the compression, `0x1592dac` and
`0x1592e80` run LZ4 (`0x71d940`). The RaidPoint is copied whole: `0x1bae670` calls `0x1bae760`, which
takes it through the reflected-field getter `0x1baff98` (the pointer at `+8`, or a zeroed 0x3c8-byte
singleton) into `+0x78` by `0x1bb0018`.

An empty participant slot holds species 0 at level 1, nicknamed `Egg`, Tera types 19, language 2,
current HP 11 and stats 11/5/5/5/5/5, the same record in every retail bootstrap; a bootstrap with
all-zero empty slots crashed a retail console as its battle began. The guest's slot 1 is the record
from its lobby message 0x2e. A retail host split the message at 1395 bytes, the second fragment
zlib-compressed.

The RaidPoint, offsets from its start:

| offset | size | what |
|---|---|---|
| 0x000 | 24 | the point's name, ASCII, `RaidPoint_` and a suffix (`RaidPoint_POKELDN_0` is accepted) |
| 0x018 | u32 | 0x40 (one retail black point held `0x458F9952`; 0x40 is accepted) |
| 0x020 | 4 x u32 | stars, the crystal (0 standard, 1 black), the record's `captureRate` (1), its `captureLv` |
| 0x04c | 37 x u32 | the boss's action profile: HP coefficient, the shield's nine values, six extra actions (action, timing, value, move), the double action's three values |
| 0x038 | u32 | nonzero in retail points, zero from `raid_point` |
| 0x0e4 | 45 x 16 | reward rows: item, quantity, 0, subject |
| 0x3b8 | 7 x u32 | stars, species (DevID), form, gender, level, 0, Tera type |
| 0x3d8 | 2 x u32 | nonzero in retail points, zero from `raid_point` |
| 0x3e0 | u32 | 4 in every retail point seen; `raid_point` writes 2, which a retail Scarlet accepts |

The action profile is the record's `bossDesc` in the game's raid tables, in that order; the
actions are 0 none, 1 reset the boss's stat changes, 2 reset the players', 3 a move, 4 drain the
Tera orb, and the timings 0 none, 1 time, 2 HP. HP coefficients run 500, 500, 800, 1200, 2000 and
2500 for one to six stars.

A retail point's reward rows are the seed's fixed rows, then its lottery draws, then the host's
bonus rows: three under subject 4 and one under subject 5. A fixed row's subject is the reward
table's `SubjectType` (0 every player, 1 the host, 2 the guests, 3 once). `raid_point` writes the
seed's rows (or the chosen ones) under subject 0 and no bonus rows, so a guest receives every row,
the host's included. A retail console awarded a row rewritten to Quick Ball x500, with the other
rows cleared and one bonus row left, as written.

## The seed

A raid is drawn from a 32-bit seed and the console's state: version, region (Paldea, Kitakami,
Blueberry, table prefixes `""`, `su1_`, `su2_`), story progress and the crystal. xoroshiro128+
starts from the seed and the constant `0x82A2B175229D6A5B` (`0xe29340`); its first draw, a hundred
values, picks a standard crystal's stars against the story stage's bounds (a black crystal has six),
the second picks the encounter by rate within that star level and version. `0xe29404` builds the
table name with `%sdifficulty_%02d` and passes the record to `0x1eab5e4`, which reads its
`raidEnemyInfo`; `0x2935b68` walks all three prefixes and six levels. A fresh xoroshiro from the
same seed then draws the boss: EC (the low half of the seed plus `0x229D6A5B`, so a boss record
gives its seed back), a fake trainer id, PID, flawless IVs, IVs, ability, gender,
nature (Toxtricity's from its form's list), height, weight and scale, as PKHeX's
`Encounter9RNG.GenerateData` does; the Tera type and the reward lottery each take another fresh
generator.

`pokeldn.sv.raid_encounter` implements it over `pokeldn/sv/data/raid_base.json`, built by
`scripts/gen_sv_raid_data.py` from Tera-Finder's encounter lists and reward tables, PKHeX's personal
table and the eighteen `raid_enemy_XX_array` tables of the game's RomFS
(`arc/worlddataraidraid_gem_item_reward_boostdata.bin.trpak`, FlatBuffers with their own `.bfbs`
schemas). Over 12600 seeds in every context its bosses equal PKHeX.Core 26.8.26's field for field,
except six Paldea encounters (records 5094 to 5099) whose Tera rule the retail table gives as the
species' own types where PKHeX has any type; the generator follows the game's table. A boss record
built from seed `BD13FB43` (Violet, Paldea, four stars) equals a retail bootstrap's byte for byte;
one from `7B741233` (Scarlet, Paldea, five stars) equals a French retail Scarlet's but for the
nickname and language: a retail host writes its own language and that language's species name
(`Embrylex`, 3), the generator English (2). The console shows the boss under its own language's
name either way.

Species in the raid tables are the game's DevID: the National Dex number up to 916, the game's own
order from 917 (Tinkatink 957 is 1000), as `gen9.internal_index`. The descriptor and the RaidPoint
carry the DevID too: a retail Scarlet shown a descriptor and RaidPoint with species 1000 listed
and fought Tinkatink.
A black-crystal record holds a battle level of 90 with effort values (for example 128 Defense and
128 Special Defense) and a capture level of 75; a standard record's two levels agree and its effort
values are zero. The bootstrap's boss record and the RaidPoint summary carry the battle level and
the effort values, the RaidPoint's `+0x2c` the capture level: a black boss built from `09F3E337`
(Scarlet, Paldea) equals a French retail Scarlet's but for the nickname and language.

## Finding a seed

The app's raid seed field shows the boss and rewards the seed gives in the tool's context, and Find
a raid searches up to a million seed and context pairs (`pokeldn.sv.raid_search`) for a species,
star level, Tera type, nature, gender, shininess and IV ranges, ranked by a score of the boss's
stats: HP times the sum of its defenses, either defense alone, its better attacking stat, or its
total. One result per species is kept unless a species is chosen. A search covers about 40 000
seeds a second.

## Joining

`bin/sv_join.py --raid-pokemon FILE` joins a scene-7 network and takes part as a guest. The
console's player opens a crystal, chooses Challenge as a group and waits; the app's Tera Raid (Join)
tool runs it. `pokeldn.sv.raid.RaidGuest` and the joiner do, in order:

| step | the guest |
|---|---|
| Net | answers 0x11 and 0x50 under message flags 0x11 |
| Session | leaves the station list that comes with the join response unanswered, acknowledges its retransmission at least 1 s later, then every later list, and sends the clock request with byte 9 set |
| channels | splits the host's six-key table into the four and the raid's two, announces the four, joins port 2 0.24 s later and announces the raid's keys 0.79 s after the table; delays its 0x7C acks 0.25 s |
| identity | the standard record set (`pokeldn.sv.reference`) 0.44 s after the seat, record 1 under the trainer name |
| lobby | state 0x18 and its Pokemon 0.27 s after that; state 0x01 2 s later |
| start | state 0x0d once the host's state 0x0c arrives; a guest that sent 0x0d as its ready was acknowledged and never shown ready |
| battle | acknowledges the host's 0x3480 0x93, sends the Session type-3 leave every 0.5 s until the type 4 (four sends at most) and leaves the network; a retail Scarlet in the battle answered none of the four |

Against a retail host the guest appeared in the lobby under the trainer name, became ready and let
the host start; its Pokemon stayed in the battle.

## Unresolved

- What the two words in the battle-start messages (`05050726` in message 15, `ceaf29` in message
  16) are; both are sent as a retail host sent them.
- The serializer header's last four bytes, and whether a nonzero counter or a zero one matters.
- What separates bonus subjects 4 and 5; what the words at 0x038, 0x3b4, 0x3d8 and 0x3e4 of a
  retail RaidPoint hold.
- Whether the six Paldea encounters with the species' own Tera types roll as the retail table says.
- Event raids, whose encounters and rewards come from the active Poke Portal News tables.

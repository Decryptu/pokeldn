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
AI partner. Addresses are offsets into the decompressed `main` of Scarlet 4.0.0, the version the
retail Scarlet measured here runs; Violet 4.0.0 has the same code at the same offsets
([docs/sv.md](sv.md)).

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
| 2 | kind, step: one u16 message id (0x012f the bootstrap, 0x0193 the battle begins) |
| 4 | a counter, u16, per sender, incremented on every send by `0xa583fc`: a retail host's lobby runs 0x0105 to 0x010e, a guest's 1, 2, 3... |
| 6 | compression, u32: 0 none, 2 LZ4 |
| 10 | the payload's plain size, u32 |
| 14 | a network-object id, u16, zero unless the sender's `0x14ede48` finds one |
| 16 | two bytes of padding the constructor never writes (stale heap in retail messages) |
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

The header is message object `+0x40..+0x4f`. The receive path `0x18bec54` copies the id, the
counter and the object id back into the object and compares none of them; it does not check the LZ4
return value, and uses the plain size only as the output capacity.

A battle-start frame on key 0x007b is a 12-byte port address (three u32), a u32 length and a
payload whose first 32 bytes are a header struct copied verbatim by `0x1227714`: u32 type at 0x00,
u64 at 0x08 and 0x10, u8 at 0x18 and 0x19, and padding at 0x04 and 0x1a..0x1f. Message 15 carries
`05 05` at 0x18 then padding `07 26 5a 00 00 00`; message 16 (type 0x46, builder `0x2898350`)
carries `ceaf29` in the padding its builder never writes. The readers `0xf5a2fc` (+0, +8, +0x10,
+0x18, which accepts 5 or the receiver's own index) and the type switch `0xe10088` (0x46 handler
`0x2897afc`) read no padding. `0x14ab234` drops a frame unless one of the receiver's ports
registered its address: message 15 is addressed (0x2713, 1, 2), messages 16 to 20 (0x2713, 3, 5),
where 0x2713 is a runtime u32 at `+0x40` of an object whose writer is untraced.
An emulated Scarlet 4.0.0 given messages 13, 15 and 16 with that padding zeroed acknowledged every
battle-start message on its first send and began the battle with the host's Pokemon, as with the
retail bytes.
An emulated Scarlet 4.0.0 took the keep branch `0x14ab210` 13 ms after the host sent messages 15
and 16: `0x14ab234` matched a battle-start frame's address and `0x14ab298` stored it.

The battle reads message 16 by its type. The reader `0xe0fd68` pops a frame and, when the header's
u64 at +0x08 is 0, switches on the type at +0x00 (`0xe10088`): type 0x46 calls `0x2897afc` with
`[reader+0x48]` as its only argument, and `0x2897afc` stores 1 at its `+0x71`. That argument is the
per-frame update `0x289358c`'s own object: `0xfa4bb4` builds it with the initialiser `0x28950c8`
(`+0x40` the battle state machine, here `sm`; `+0x48` the stepped object `[sm+0xa8]`, `+0x50` the reader
`[sm+0xb0]`), stores it at `[sm+0x148]` (`0xfa4c18`) and assigns it to `reader+0x48` (`0x2892ab4`
at `0xfa4c68`). The state `0x28932a4` calls the update with `[sm+0x148]` (`0x28932d0`). The update
reads `+0x71`: while the byte is 0 it pumps
the reader (`0xe0f014`) and calls `0xfc363c([+0x48], 0)`; while it is 1 it stops pumping and calls
`0xfc363c([+0x48], 1)` each frame, and `0x28935b8` clears the byte when that returns true. With 1,
`0xfc363c` takes an item from the source at `+0xa8` and hands it to the sinks at `+0xa0` and `+0xb8`
while the sink at `[+0xb8]+0xa0` is empty. The sink holds a deque (map `+0x60`, start `+0x98`,
size `+0xa0`) and steps each element's vf `+0x68` every frame (`0xfc38dc`). The update's result is
unused (`0x28932d4`) and nothing on this path writes the state machine's state at `+0x68`.
An emulated Scarlet 4.0.0 popped on the type-0x46 branch a frame carrying a marker the host wrote into
message 16's padding (`46000000 d16a1616`, `0500 161616161616`): the frame was message 16. The pop
came after the network had gone down, after the Error 7 dialog and before the first command menu,
on the update's own pump (return addresses `0x28935d0`, then `0x28932d4`).

In 4.0.0 no decision reads the padding. The receive path loads the serializer header's last two
bytes (`0x18bec98`) and stores them at `+0x4e` (`0x18bece4`) with no comparison; of the 49 message
classes, only the serializers `0x290b150` and `0x14c7904` load `+0x4e`, to write the header out. The
battle-start readers `0xe0fd68`, `0xe106a4`, `0xf5a2fc`, `0xf5a810` and `0xf5bc10` read the 32-byte
header at +0x00, +0x08, +0x10, +0x18 and +0x19; `0xf5a454` and `0xf5ae40` copy all 32 bytes into a
frame `0xf5bb4c` re-sends, and compare none. The transport copies (`0x14ab150`, `0x14ab234`,
`0x16a319c`) compare only the 12-byte address.

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
| 0x020 | 4 x u32 | stars, the crystal (0 standard, 1 black; [2 and 3 for an event](#event-raids)), the record's `captureRate` (1; an event's 0 or 2), its `captureLv` |
| 0x030 | 7 x u32 | the record's `raidTimeData`: active (a bool), `gameLimit`, `clientLimit`, `commandLimit`, `pokeReviveTime`, `aiIntervalTime`, `aiIntervalRand`; `raid_point` writes an active record's, zero for an inactive one |
| 0x04c | 37 x u32 | the boss's action profile: HP coefficient, the shield's nine values, six extra actions (action, timing, value, move), the double action's three values |
| 0x0e4 | 45 x 16 | reward rows: item, quantity, a rare-item flag, subject |
| 0x3b4 | u8 | 0 in a retail standard point, 1 in a retail black one |
| 0x3b8 | 7 x u32 | stars, species (DevID), form, gender, level, 0, Tera type |
| 0x3d8 | u64 | nonzero in retail points, zero from `raid_point` |
| 0x3e0 | u32 | 4 in every retail point seen; `raid_point` writes 2, which a retail Scarlet accepts |

In the raid tables every six-star record's `raidTimeData` is active with `gameLimit` 450 and
`commandLimit` 60, every one-star record's inactive with `gameLimit` 300, and the rest zero; a retail
black point (record 6045) carried 1, 450, 0, 60, a retail three-star point (record 3019) an inactive bool byte with three stale bytes after it, then zeros.
Bytes 0x3b5..0x3b7, 0x3d4..0x3d7 and 0x3e4..0x3e7 held stale bytes in both retail points.

The action profile is the record's `bossDesc` in the game's raid tables, in that order; the
actions are 0 none, 1 reset the boss's stat changes, 2 reset the players', 3 a move, 4 drain the
Tera orb, and the timings 0 none, 1 time, 2 HP. HP coefficients run 500, 500, 800, 1200, 2000 and
2500 for one to six stars.

A retail point's reward rows are the seed's fixed rows, then its lottery draws, then the host's
bonus rows: three under subject 4 and one under subject 5. A fixed row's subject is the reward
table's `SubjectType` (0 every player, 1 the host, 2 the guests, 3 once); the game's enum
`RaidRewardItemSubjectType` has no 4 or 5. In both retail points the subject-4 rows were the seed's
lottery drawn three more times on the same generator, and the subject-5 row the boss's Tera Shard
with the count `RaidGemItemRewardBoost` gives its difficulty (0, 0, 2, 5, 10, 12 and 0 for one to
seven stars; 2 at three stars, 12 at six). The meal-power table reader `0xef885c` reads one raid
field, `AddRewardSlots`. A row's third word was 1 on a Bottle Cap lottery row and 0 elsewhere.

An emulated Scarlet 4.0.0 guest sent one row under each subject 0 to 5 listed subjects 0, 2, 3 and 5
on its reward screen and left out 1 and 4. With a meal's Raid Power: Ghost Lv. 1 active it left out
subject 4 against a Steel Tera boss and listed it against a Ghost Tera boss; sent three subject-4
rows there, it listed the first only.

Scarlet 4.0.0's Lua reward filter, `C07C34FC3B976E5A7.F316609DEA110601D`
(source lines 78707 to 78765), keeps subject 0 for every player, 1 for the host, 2 for a guest
and 3 when its once-reward eligibility argument is true. It keeps the first N subject-4 rows,
where N is the highest level of an active Raid Power matching the boss's Tera type. Meal kind 5
is Raid Power; type 18 matches every Tera type. Subject 5 requires item 2481, the Glimmering Charm,
in the receiving player's inventory. The row counter advances for every subject-4 row.
Executing the unchanged Lua function with native environment getters supplied by a test harness
kept zero, one, two and three subject-4 rows at levels 0 to 3, for both host and guest, with and
without the charm. Mismatched types kept zero; multiple matching powers used the highest level.

A host matching retail reward construction preserves each fixed row's subject and each row's
rare-item flag, writes ordinary lottery rows under subject 0, then appends three continued
lottery draws under subject 4. It appends the difficulty's Tera Shard boost under subject 5
when its quantity is positive. Each receiver applies its own meal and charm eligibility.

The timer initializer `C2D7F486425487755.F0C64BA9B6853E61A` (source lines 79486 to 79513)
uses supplied time fields when `raidTimeData.active` is true. With it false, a group battle uses
game limit 300, command limit 60, client limit 0, revive time 30, AI interval 17 and AI interval
randomness 6. Executing its unchanged Lua function with the six-star table data yielded
450, 60, 0, 0, 0 and 0 respectively; a zeroed RaidPoint yielded the defaults.
Both functions are in Lua chunk `be21e65463b9a98f`, SHA-256
`c1a4f4e2625912cf0b739a642a79ba3357df0557a544b92da22a6cb139de2815`.

`raid_point` writes the seed's rows (or the chosen ones) under subject 0 and no bonus rows, so a
guest receives every row, the host's included. A retail console awarded a row rewritten to Quick Ball x500, with the other
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
including six Paldea encounters (records 5094 to 5099) whose retail table gives Tera rule 0 (the
species' own types), which PKHeX holds as rule 1 (any type). The crystal builder `0xe26ff0` reads
`gemType` and draws any of 18 for both 0 and 1 (`cmp w9, #2` at `0xe27414`, redrawing until the
value is under 18), as PKHeX does; the generic converter `0x160e108` treats 0 as the species' types
but is not on the raid's path. A boss record
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

## Event raids

A Poke Portal News delivery holds five files: `raid_enemy_array`, `fixed_reward_item_array`,
`lottery_reward_item_array` and `raid_priority_array`, FlatBuffers with the base tables' layout, and
`event_raid_identifier`, a u32 that repeats the priority table's `VersionNo` (`20221202`). From 1.3.0 a
delivery carries each again under the patch it is for (`_1_3_0`, `_2_0_0`, `_3_0_0`), the older copy
dummied out; the newest is read. A `raid_enemy_array` record is a standard one's, with
`RomVer` (0 both versions, 1 Scarlet, 2 Violet), `DeliveryGroupID`, `Difficulty` as the stars (7 a
seven-star raid), `CaptureRate` (0 never caught, 1, 2 caught once) and its own reward table names, and
its `BossPokePara` fixes what a standard boss draws:

| field | an event record |
|---|---|
| `Sex` | 0 drawn; 1 male, 2 female, and the gender draw is skipped |
| `Seikaku` | 0 drawn; the nature plus 1, no draw |
| `TalentType` | 1: `TalentVnum` flawless IVs; 2: `TalentValue`'s six IVs, no draws |
| `RareType` | 0 drawn; 1 never: a PID shiny against the fake trainer has bit 28 flipped; 2 always: its high half is rewritten to a shiny xor of 0 |
| `ScaleType` | 0 two draws; 1 to 5 one draw in 0-15, 16-47, 48-207, 208-239, 240-255; 6 `ScaleValue` |
| `Item`, `EffortValue` | the boss's held item and battle EVs (a seven-star Pikachu holds a Light Ball) |

A record's `TimeDesc` is its `raidTimeData`, and the RaidPoint carries it at 0x030: every seven-star
record's is active, `gameLimit` 450 to 900 and `commandLimit` 60, as are five five-star records'
(`gameLimit` 320 to 450); the other 420 records' are inactive (gallery of 2026-09-06).

A den belongs to a delivery group, 1 to 10; `raid_priority_array` counts the dens of each. xoroshiro
from the seed draws the hundred-sided roll a standard crystal's stars take and drops it, then a value
under the total rate of the group's records that are the console's version and of a star level the
story stage allows, and takes the record whose span holds it, in table order [PKHeX
`EncounterDist9.GetIsPossibleSlot`]:

| progress | stage | stars drawn |
|---|---|---|
| beginning, Tera Raids | 0 | 1, 2 |
| 3-star | 1 | 1 to 3 |
| 4-star | 2 | 1 to 4 |
| 5-star, 6-star | 3 | 3 to 7 |

A record of rate 0 is never drawn. The boss and its Tera type are drawn as a standard raid's with
the record's fixed fields; the rewards are the record's fixed table, then the lottery's draws from
the delivery's own tables, a seven-star raid's count as a six-star one's. A lottery slot with a rate
and no item weighs in the total and gives nothing, as does a row of quantity 0. The lottery tables of
Gimmighoul's first 2023 round in Scarlet are malformed so, every slot empty or of quantity 0, and its
raids give their fixed rows only.

`pokeldn.sv.raid_event` reads a delivery folder (an [EventsGallery](https://github.com/projectpokemon/EventsGallery)
event, or its `Files`) and generates the `Raid` the host stages:

    ./.venv/bin/python bin/sv_host.py ... --raid-pokemon FILE --raid-seed 52E6B438 \
        --raid-event "EventsGallery/Released/Gen 9/SV/Raid Events/002 Charizard the Unrivaled" \
        --raid-version scarlet --raid-progress 6star [--raid-event-group 1] [--raid-catch-normal]

The RaidPoint carries the record's capture rate and, as the crystal, the save's raid content: 2 an
event, 3 a seven-star event (Tera-Finder `RaidContent`).

An emulated Scarlet 4.0.0 guest fought both. Eevee Spotlight (20221125) at seed `00000002`,
beginning progress, crystal 2: a one-star Eevee, caught, its reward screen listing the seed's rows in
order. Charizard the Unrivaled (20221202) at seed `00000001`, six-star progress, crystal 3 and
`raidTimeData` 1, 600, 0, 60: the boss named "Charizard the Unrivaled", its timer bar losing about a
tenth of its length a minute, a 600 s limit where the console's own is 300 s.

The app's Tera Raid (Host) tool picks the event from its own copy of the gallery, which it downloads
and updates, and narrows the raid's version, progress and crystal to what the event spawns
([Raid events](gui.md#raid-events)). The crystals offered come from `raid_event.dens`: a delivery
group with dens in the priority table and a record in that version; Walking Wake's spotlight offers
Scarlet its group 1 and Violet its group 2.

A capture rate of 2 is a catch once per save: every seven-star record has it, and so do the five-star
Walking Wake and Iron Leaves of each spotlight round, Dialga and Palkia's spotlight and the shiny
Rayquaza. The save keeps the record numbers caught, eight bytes each, the number and a captured flag
(block `0x8B14392F`; from 2.0.1 the defeated flags are `0xA4BA4848`'s, PKHeX `RaidSevenStar9`), and a
rerun repeats its number (Walking Wake is 2023022801 in all seven rounds), so a catch in one round
closes the others. The
shiny Treasures of Ruin spotlights' records have 0: never caught. The host's summary names the rule
(`caught once per save`, `cannot be caught`).

A console checks that list by the record number of the lobby descriptor (0x2c). A retail Violet
that had caught Mighty Mewtwo (2023090101), shown the host's descriptor of it, said "you won't be able to
catch the Tera Pokemon" in the lobby, with the RaidPoint's capture rate written 1 or 2 alike, as no
RaidPoint is sent before the battle. Against Magikarp the Unrivaled (2026071701), which its save had
caught, the same console:

| descriptor's record number | RaidPoint's capture rate | the lobby | after the win |
|---|---|---|---|
| 2026071701, the record's | 2 | won't be able to catch | no catch |
| 2026071701 | 1 | won't be able to catch | no catch |
| 2026071799, a stand-in | 1 | no warning | caught |
| 2026071799, again | 1 | no warning | caught |

A record number the save lists as caught blocks the catch after the win whatever capture rate the
RaidPoint carries (the second row). A catch under capture rate 1 does not add the stand-in to the
list (the fourth row). `--raid-catch-normal` serves a catch-once record as a normal catch: the
RaidPoint's capture rate 1, and in the descriptor a stand-in record number, the record's date with
the suffix 99 (`raid_event.stand_in`: 2026071799). No delivery has that suffix (every one's is at
most 14). The summary says `served as a normal catch of record 2026071799`. A never-caught record
stays 0.

The stand-in is in the descriptor alone: the boss record and the RaidPoint but its capture rate are
the event's, byte for byte, and no PK9 field holds a record number. PKHeX.Core 26.8.26's raid
encounters (`EncounterDist9`, `EncounterMight9`) have none either, only their delivery group, so a
catch's legality cannot depend on it. Every catch-once record of the gallery but Kingambit's second
round (newer than that release), in each version it spawns in, at three seeds each and Magikarp at
`000FD5D7`, 331 raids: the boss record the host sends, given a test trainer as PKHeX's own conversion
of the encounter gives it, equals PKHeX's catch of that raid from that seed and is legal. A seven-star catch
is legal only with the Mightiest Mark (`RibbonMarkMightiest`), which the console gives it: the
Magikarp the console caught under 2026071799 has it.

A fixed reward row's subject 3 (`Only Once` in `Encounters.txt`: a seven-star raid's TM and Ability
Patch) is a separate rule, and `raid_point` gives every row to every player anyway.
An event boss can be any species, so the personal entries, move PP and names past the raid bosses'
come from `pokeldn/sv/data/species.json` (`scripts/gen_sv_species_data.py`, the PKHeX revision of
`raid_base.json`).

Against EventsGallery's 153 delivery folders (2026-09-06): every table decodes as its JSON; the
distribution and seven-star encounters pkNX's ripper makes of them equal PKHeX.Core 26.8.26's 174 and
55, all of them (Kingambit's second round is newer than that release, `000 Base Data` the game's own
placeholder); 20 080 bosses, forty seeds for every event, version, stage and group, equal PKHeX's
`GenerateSeed32` field for field, PKHeX allowing each record at its stage; and
`scripts/check_sv_raid_events.py` finds every delivery's 537 encounters, and raids drawn from them,
agree with its `Encounters.txt`, Gimmighoul's malformed round aside. Each of PKHeX's 229 encounters
at seeds `00000001`, `12345678`, `9ABCDEF0`, `DEADBEEF`, `52E6B438` and `0000F00D` gives the
encryption constant, IVs, ability number, gender, nature, height, weight and scale that
`boss_fields` draws for the gallery's record of it.

## Finding a seed

The app's raid seed field shows the boss and rewards the seed gives in the tool's context, and Find
a raid searches seeds from a first one, typed or picked at random, in every context the filters
leave (`pokeldn.sv.raid_search`) for a species, star level, Tera type, nature, gender, shininess and
IV ranges, ranked by a score of the boss's stats: HP times the sum of its defenses, either defense
alone, its better attacking stat, or its total. One result per species is kept unless a species is
chosen.

Its Rewards section, folded until opened, wants rewards: rows of an item and the least quantity a
raid must give of it, the raid's quantities of an item summed and two rows of one item added up.
A result then shows its rewards. Folded, the rows stay and the search ignores them. The items and
quantities offered are those the raids searched can give (`raid_search.reward_choices`): for every
encounter a context draws (its star levels at that progress, in that version, or an event's den),
narrowed to the stars, species and Tera type chosen, its fixed rows plus any number of its lottery's
draws of an item up to the most a raid draws (exactly as many as it draws when the lottery holds
nothing else), each Tera type the boss can take naming its shards and the species its material.
Every Paldea, Kitakami and Blueberry context at once lists 343 items in about a second, so the list
is made off the page. The search skips an encounter that cannot give what is wanted, then draws a
seed's rewards before its boss, which keeps its speed.

The PKHeX helper scans the seeds over every core (`services/pkhex/RaidScan.cs`, packed and sent by
`pokeldn.sv.raid_scan`, in a helper process of its own): a seed's encounter, its boss up to the
nature, the score, every filter and the rewards, the work of `select`, `boss_fields`, `rewards` and
`tera_type` on the context's tables. It names a context's best seeds (or each species' best), and
`search` makes their raids with the plain Python code, so the results, their order and the ties
between seeds and contexts are the Python scan's (`tests/test_sv_raid.py` compares both). On an
Apple M4, ten million seeds of one context take 0.36 s, 0.12 s for shiny ones, and ten million in
each of the 42 contexts 9.1 s. A search covers up to 4 294 967 296 seed and context pairs, sent to
the helper 16 777 216 seeds at a time, and the finder offers ten million seeds. Without the helper
(a source checkout that has not built it), Python scans every seed, about 22 000 a second, up to a
million pairs, and the finder offers 100 000.

The finder's Every seed searches all 4 294 967 296 seeds of one context (a game, region, progress
and crystal chosen), 41 s on that machine. Stop at the first match answers the first raid that
matches, whatever its score, instead of the best ones (`stop_at_first`): the earliest seed of the
first context that has one, the contexts searched one after the other.

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

- Whether a listener of the GlueCode dispatcher `0x18beef4` reads `+0x4c` as a word (listeners
  register at run time; groups 1 to 3 are called at `0x18bf87c`), and which consumer drains the
  per-slot queues `0xe106a4` fills (`0x113d5e0` from `0xe107ac`). Message 16, with +0x08 zero,
  enters neither queue: the reader switches on it and `0xf5bc10` returns at `0xf5bc30`.
- What the source at `+0xa8` of the object `0xfc363c` steps holds, and which item message 16
  releases into the sink: the item `0xfc363c` returns through x8 at `0xfc36ac`, then its vtable's
  `+0x68`. The source is `[[sm+0x48]+0x128]` (`0xfa46d4`); what fills `[sm+0x48]` is untraced.
- What writes the 0x2713 word of the battle-start port address. The builders read it at `+0x40`
  of the object at the battle network object's `+0x110` (`0xfa7320`, `0xfa8628`, `0xfb1cf8`,
  `0x28949f4`); no instruction in the image materialises 0x2713. On an emulated Scarlet 4.0.0 guest that object (vtable `0x44ff6c8`,
  constructor `0x16b21f0`, which zeroes `+0x40`, destructor `0x2894604`) held the u32 pair
  `0x1527b, 7` at `+0x38` and 0x2713 at `+0x40` when the builders first read it at the join.
  Every raid hosted with it began its battle, on retail and emulated consoles.
- End-to-end reward-screen checks for Raid Power Lv. 2 and 3 and six-star bonus rows.
- What the RaidPoint's u64 at 0x3d8 and byte 0x3b4 hold.
- What a retail console does with an event RaidPoint's crystal word, 2 or 3 (an emulated one fought
  both), and with a fixed reward row's subject (host, guests, once), which `raid_point` writes as 0,
  every player's.
- Whether the five-star catch-once records go in the save's list as the seven-star ones do.

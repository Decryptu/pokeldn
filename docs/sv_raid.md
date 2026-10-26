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
AI partner. Addresses are offsets into the decompressed `main` of Scarlet 4.0.0; Violet 4.0.0 has
the same code at the same offsets ([docs/sv.md](sv.md)).

## Hosting

The host advertises scene 7, four participants and Link Code 4970. The console joins from
X, Poke Portal, Tera Raid Battle, offline search. `--raid-seed` with the four context flags picks the
raid ([The seed](#the-seed)), `--raid-pokemon` is the party record our player brings (PKHeX checks
it), and `--raid-reward ITEM:QUANTITY`, repeated, replaces the seed's rewards with rows of items the
Scarlet/Violet bag holds (the PKHeX helper's `bag` list: every pouch but the key items, unreleased
items out). `--raid-partner TRAINER`, up to once for each slot the consoles leave empty (two with
one console, one with two), seats those NPC partners in slot order, and
`--raid-partner-progress STAGE` picks the stage they come from ([Partners](#partners)). The app's
Tera Raid (Host) tool carries the flags below.

    --channel 1 --scene-id 7 --max-participants 4 --code 4970 --scarlet-response --session-flags 0
    --session-packet-id 1 --no-session-ack --join-seq 0 --update-seq 0 --update-delay 0.02
    --rtt-probe --clock --net-stations 4 --record-delay 0.1 --record-spacing 0.003
    --host-player-id 00000000000000010000000000000000

In raid mode the host differs from a trade host in what it addresses and when:

| | a raid host |
|---|---|
| mesh-addressed messages (RTT, 0x80, 0x81), the Session station lists | to the subnet broadcast; unicast over ldn_mitm, which carries no broadcast to a peer |
| Net 0x11 | one sequence, repeated until the 0x12 |
| the station list's console entry | the player the console's join request named; with a placeholder player the console is seated and absent from the lobby |
| the station list | resent every 2 s until the console's type 6 |
| the opening | only after that type 6: the eleven first bulk acks, the 0x81 port 5 open and an RTT request in one packet; the 0x81 port 1 open, the channel table and the port-2 type 6; the identity 20 ms later, one record every 3 ms |
| the port-2 type 3 | answered with two type 9s: the host's station with code 0, the console's with code 1 |

The opening's 0x7C, 0x81 port 5 and 0x80 port 2 messages repeat every 0.25 s until acknowledged,
and every ack the host sends declares the lowest unacknowledged sequence of the stream.

### Several consoles

`--raid-players N` (1 to 3, the app's "Consoles joining") seats up to three consoles in one lobby,
each at the lowest free station index. They share the lobby and the start; from the first turn each
fights its own battle with its own NPC partners and rewards ([Which station runs the
server](#which-station-runs-the-server)). The host keeps one set of streams per console, using that
console's index *k* where a single console's raid has 1:

| | the console at index *k* |
|---|---|
| join response | station index and join order *k* |
| station list | every seated station, ours first; each seat change goes to every seated console under the next sequence, resent until each one's type 6 |
| Net 0x11 | our station, the seated consoles by index, then the joiner |
| destination bitmap | `1 << k` under three destination bits |
| bulk ack | entry *k* |
| opening | 0x81 ports *k* and 4 + *k* |
| port-2 type 6 | ours and the members already seated, in join order, with codes and count |
| port-2 type 9s | ours under code 0, each seated member's under its code, the console's last under code *k*; each seated member receives the console's |
| bootstrap | its Pokemon in slot *k*; an empty slot for a free seat |

A join that finds every seat taken, or comes after the start, is left unanswered. The host drops
every packet whose header and footer do not name its variable id and every reliable message whose
bitmap lacks station 0, since consoles in one lobby address each other through the same broadcast.

A port-2 slot keeps its members at slot `+0x170` as a u8 code and a u64 station id; `0x138d208`
returns a station's code, 0xfd for a non-member. A host's type-3 handler `0x1981e94` takes the lowest
code 0 to 7 that no member holds and no queued type 9 names (`0x279c9a0`), then broadcasts one type
9 per member and one for the joiner. The receiver `0x18b68fc` appends a `(code, id)` it has not
listed and never changes a listed code. The type 6 (`0x12fbf8c`, composer `0xe457cc`) carries member
ids at `+0xa0`, codes at `+0xc0`, count `+0xc4` and the closed byte `+0xc5`; its receiver `0x279b9c4`
replays a type 9 per member. The Lua lobby (chunk `be21e654`, receiver `0.15829`; `0.N` is the main
function's prototype N) files every message under its sender's code, 253 for none. A console
entering the lobby sends state 0x18 and its Pokemon; a station receiving 0x18 answers with its Ready
state and Pokemon.

The reliable header's receive check (`0x6f0410`..`0x6f0430`) tests the receiver's bit `index & 31`
of word `index >> 5` for any destination count 1 to 23; a retail sender writes three, the station
capacity 4 (`0x44dfcb0`) less one (`0x6e71c4`).

The host hands the network to the lowest index still on it. The other consoles get the is-migrating
Net 0x11 (ranking every seated station) only after the next host's type 8, then NetStartHostMigration
once every console has answered 0x12, with no Session type 7. What keeps the consoles in one battle:

| condition | code |
|---|---|
| a console seeing another leave keeps it only once migrating: `[net+0x249]` set by an is-migrating 0x11, or `[net+0x1c0]` by NetStartHostMigration | station-left handler `0x69d08c`, `0x69d174` |
| a Net 0x11 with a newer sequence drops every station marked gone | `0x69e008`, `0x6b5074` |
| the next host waits up to 8000 ms for every Net station to reach state 2, drops the rest, sends Net 0x11, waits for every 0x12 and sends Session type 5 | NetHostMigrationJob `0x6a9cd4`, `0x6aa2a8`; `0x6d44f0` |
| the other console waits 10000 ms for that type 5, then fails | `0x6dc024`, `0x6dc124` |
| the type 7's last u16 at most the next host's applied list sequence | `0x6d9164` |

A Pia host sends Net 0x11 to every station on each change of LDN participants (`0x69c310`,
`0x69c79c` increments `[NetProtocol+0x60]`, rankings in ascending IPv4 order `0x6a05ec`). On LDN a
joiner's 0x11 receiver `0x69db14` creates no station (`0x6a2fac` returns 0); its stations come from
`nn::ldn::GetNetworkInfo` (`0x6b43a8`), port 12345. The type-5 receiver `0x6d7f8c` creates a listed
station (`0x6d840c`) only when its address is in that node list (`0x6a8320`); otherwise it sends no
type 6 and resets its applied sequence to 0xffff (`0x6d81a4`). Session type 9 (`0x6d4ef0`), `09 |
constant id | count | constant ids`, names stations a joiner has not heard from (`0x6d4a60`) every
3000 ms; the host's receiver `0x6d940c` hands a single named station to the kick job (`0x6dc878`).

After a console's join a raid host sends packet id 0: a seated console drops what follows a higher
id ([docs/pia.md](pia.md#version-11-what-a-receiver-drops-scarlet-400)). The station list's player id
is the anonymous `00000000000000010000000000000000` (`pia_connect.DEFAULT_PLAYER_ID`); a random id
draws no type 6.

## The lobby

A raid message is a game message on 0x80 port 0 ([The trade](sv.md#the-trade)):

| bytes | field |
|---|---|
| 0 | handler key, u16 |
| 2 | kind, step: one u16 message id (0x012f the bootstrap, 0x0193 the battle begins) |
| 4 | a per-sender counter, u16, incremented by `0xa583fc` |
| 6 | compression, u32: 0 none, 2 LZ4 |
| 10 | the payload's plain size, u32 |
| 14 | a network-object id, u16, zero unless `0x14ede48` finds one |
| 16 | two bytes of padding the constructor never writes |
| 18 | the payload |

| key | kind | what |
|---|---|---|
| 0x3380 | 0x2c | the raid's descriptor: species (DevID), form, stars, Tera type, gender, the encounter's record number |
| 0x3380 | 0x2d | a participant's state: 0x00 not ready, 0x01 ready, 0x0c the host's start, 0x0d a guest's answer, 0x18 entering the lobby, 0x1e the host refusing a late station (`0.30822`) |
| 0x3380 | 0x2e | a participant's Pokemon, its encrypted 344-byte party record |
| 0x3380 | 0x2f | the battle bootstrap |
| 0x3380 | 0x30 | the lobby timer, in seconds left |
| 0x0132 | 0x6e, 0x73 | a console loading the battle, then loaded |
| 0x3480 | 0x93 | the battle begins |
| 0x007b | 0x13 | the battle-start messages a host sends after 0x3480 |

The receive path `0x18bec54` copies the header into message object `+0x40..+0x4f` and compares none
of it; it ignores the LZ4 return value and uses the plain size only as output capacity.

A battle-start frame on key 0x007b is a 12-byte port address (three u32), a u32 length and a payload
whose first 32 bytes are a header copied by `0x1227714`: u32 type 0x00, u64 0x08 and 0x10, u8 0x18
and 0x19, padding at 0x04 and 0x1a..0x1f. No reader compares the padding (`0xf5a2fc`, `0xe10088`,
`0xe0fd68`, `0xe106a4`, `0xf5a810`, `0xf5bc10`; the 18-byte header's last two bytes are stored at
`+0x4e` by `0x18bece4` and read only by the serializers `0x290b150`, `0x14c7904`). A retail
Scarlet guest started and won a battle with bytes 0x1a..0x1f of messages 15 and 16 and the 18-byte
header's last two bytes zeroed. `0x14ab234` drops a
frame unless a receiver port registered its address: message 15 is addressed (0x2713, 1, 2),
messages 16 to 20 (0x2713, 3, 5); 0x2713 is the setup's u32 `+0x2c`.

The battle reads message 16 (type 0x46) through `0xe0fd68`: with the u64 at +0x08 zero it switches on
the type (`0xe10088`), and `0x2897afc` sets `+0x71` of the per-frame update `0x289358c`'s object
(built by `0xfa4bb4` with `0x28950c8`, stored at `[sm+0x148]`). While `+0x71` is 0 the update pumps the
reader (`0xe0f014`) and calls `0xfc363c([+0x48], 0)`; while 1 it calls `0xfc363c([+0x48], 1)` each
frame until that returns true (`0x28935b8` clears it).

The channel table a raid host announces on 0x7C port 1 holds six keys: a Link Trade's four (`0x007b`,
`0x0132`, `0x0232`, `0x0332`) and `0x3380`, `0x3480`. A retail guest announces the four, then the
raid's two 0.79 s later. Port 2 carries the host's type 6: the type 7's session block under kind 5
and capacity 4, then four slots with the host's station id first (`port2.build_session`).

`pokeldn.sv.raid.RaidHost` releases the host's messages to one console in order, each after the
console's previous step; `RaidGroup` holds what the consoles of one lobby share:

| seq | message | released by |
|---|---|---|
| 1 | descriptor (zlib, INITIALIZED) | the console's lobby Pokemon (0x2e) |
| 2, 3 | state 0x18, our Pokemon | |
| | the timer, each time it drops | one step a second from 0.73 s after the first console's answer |
| | state 0x01 | 3.19 s |
| | state 0x0c, the start | once `--raid-players` consoles are seated and all sent 0x01, or at timer 0 |
| | Net 0x50, property state 7 | the console's 0x0d |
| | Session station list, the next sequence | the console's Net 0x51 |
| | the bootstrap, two fragments | the console's type 6 |
| | loaded, `0x320173` | the console's 0x6e or 0x73 |
| | the battle begins, `0x803493` | the console's 0x73 |
| | the six battle-start messages | the console's 0x93; then 0, 0.10, 0.12, 0.16, 0.18 s |

A retail host opens a 180 s lobby and sends the timer once a second (`0.27104`); the pokeldn host's
starts at 180 at the first console's answer. A console's 0x00 or 0x18 withdraws its 0x01. A guest
answers 0x0c with 0x0d at once with no Ready check, and only the host starts a battle
(`Raid_Start_Ready`, `0.27137`). On a host, `Raid_Start_Ready` enables the start item only while every
guest is ready; at timer 0 it breaks up a lobby with no ready member and starts otherwise.
`Raid_Start_Go` (`0.27140`) resends 0x0c until every member answered 0x0d, then sends the bootstrap,
slot *k* the Pokemon of the member with code *k*.

Gated messages leave 50 ms after their milestone; Net 0x50 and the station list repeat every 0.5 s
until answered, raid messages every 0.5 s until acknowledged. The Net 0x50 is the trade host's
property body with sequence 1, byte 27 set to 7 and the 132 application bytes at +38,
zlib-compressed under flags 0x31; uncompressed it draws no 0x51.

Five seconds after the last console's message 20 the host hands the console its network as a leaving
retail host does ([docs/sv.md](sv.md#leaving)): Session type 7 every second until type 8, the
is-migrating Net 0x11 every 0.5 s until 0x12, NetStartHostMigration every 0.3 s for up to 4 s. Never
destroy the network instead: a retail console can show 2318-0006 at the battle's opening.

## The battle bootstrap

Message 0x2f carries a 0xaa0-byte record, LZ4-compressed (block format, `pokeldn.sv.lz4`):

| offset | size | what |
|---|---|---|
| 0x000 | 4 x 0x158 | the four participants' party records, encrypted, the host's in slot 0 |
| 0x560 | 0x158 | the boss's party record |
| 0x6b8 | 0x3e8 | the RaidPoint |

The serializer `0xe327fc` writes the five records from message object `+0x440`..`+0x458` and `+0x50`
(`0xe329b4`), then four quadwords from `+0x58` and 0x3c8 bytes from `+0x78`; `0x1592b7c` picks the
compression and `0x71d940` runs LZ4. The RaidPoint is copied whole (`0x1bae670` -> `0x1bae760`,
getter `0x1baff98`). A retail host splits the message at 1395 bytes.

An empty participant slot holds species 0 at level 1, nicknamed `Egg`, Tera type 19, language 2,
current HP 11 and stats 11/5/5/5/5/5. Never send all-zero empty slots: a retail console crashes as
its battle begins.

| RaidPoint offset | size | what |
|---|---|---|
| 0x000 | 24 | the name, ASCII, `RaidPoint_` and a suffix (`RaidPoint_POKELDN_0` is accepted) |
| 0x018 | u32 | 0x40 |
| 0x020 | 4 x u32 | stars, the crystal (0 standard, 1 black, [2 and 3 an event](#event-raids)), `captureRate`, `captureLv` |
| 0x030 | 7 x u32 | `raidTimeData`: active, `gameLimit`, `clientLimit`, `commandLimit`, `pokeReviveTime`, `aiIntervalTime`, `aiIntervalRand` |
| 0x04c | 37 x u32 | the boss's action profile (`bossDesc`): HP coefficient, the shield's nine values, six extra actions (action, timing, value, move), the double action's three values |
| 0x0e4 | 45 x 16 | reward rows: item, quantity, rare-item flag, subject |
| 0x3b4 | u8 | 0 in a retail standard point, 1 in a black one |
| 0x3b8 | 7 x u32 | stars, species (DevID), form, gender, level, 0, Tera type |
| 0x3d8 | u64 | `randSeed`, the partner seed ([Partners](#partners)) and battle seed ([The battle's random numbers](#the-battles-random-numbers)) |
| 0x3e0 | u32 | `raidNpcGroupID`, the host's raid unlock stage ([Partners](#partners)) |

Six-star records' `raidTimeData` is active with `gameLimit` 450 and `commandLimit` 60, one-star
records' inactive with `gameLimit` 300, the rest zero. With it inactive the timer initializer
`C2D7F486425487755.F0C64BA9B6853E61A` uses game limit 300, command limit 60, revive time 30, AI
interval 17 and randomness 6. Actions are 0 none, 1 reset the boss's stat changes, 2 reset the
players', 3 a move, 4 drain the Tera orb; timings 0 none, 1 time, 2 HP; a value is the HP or time
share that triggers it. An HP trigger at P percent fires once 100 x the boss's HP / its HP pool, in integer division, is P or less: at 414 of 816 HP the 50 percent action fires. HP coefficients are 500, 500, 800, 1200, 2000 and 2500 for one to six stars.

A retail point's reward rows are the seed's fixed rows (subject = the table's `SubjectType`: 0 every
player, 1 the host, 2 guests, 3 once), its lottery draws under subject 0, three more lottery draws
under subject 4, and the boss's Tera Shard under subject 5 with `RaidGemItemRewardBoost`'s count (0,
0, 2, 5, 10, 12, 0 for one to seven stars) when positive. The reward screen lists a rare-item row
first.

The Lua reward filter `C07C34FC3B976E5A7.F316609DEA110601D` keeps subject 0 for everyone, 1 for the
host, 2 for a guest, 3 when once-eligible, the first N subject-4 rows where N is the highest level of
an active Raid Power (meal kind 5) matching the boss's Tera type (type 18 matches all), and subject 5
when the player holds the Glimmering Charm (item 2481). An active meal power is u32 kind, u32 type,
u32 level and an f32 of seconds left (1800 when eaten). Both functions are in Lua chunk
`be21e65463b9a98f`, SHA-256 `c1a4f4e2625912cf0b739a642a79ba3357df0557a544b92da22a6cb139de2815`.

`raid_point` builds rows the same way; for seeds 7B741233 and 09F3E337 its 45 rows equal the retail
points' bytes. Chosen rewards (`--raid-reward`) go under subject 0 with no bonus rows.

## Partners

Every console fills the participant slots no lobby member holds with the same NPC trainers, drawn
from two RaidPoint words, `randSeed` (u64 at 0x3d8) and `raidNpcGroupID` (u32 at 0x3e0) (`0.4453`;
getters `0x1be5ac0`, `0x1be5c20`). A retail host draws a new `randSeed` at each start
(`Raid_Start_Go`, `0.27140`). The u64 seeds xoroshiro128+ (`0x17ebec0`) with `0x82A2B175229D6A5B` as
the second word. Three trainers are drawn (`0.7804`), each `next_int(n)` over the n still in the pool
(masked to the bits of n - 1, redrawn while n or more) and removed. Empty slots take the draws in slot
order (`0.4455`).

A partner's record takes five draws from the same `randSeed`, shared by every partner of a battle
(`raid_partners.identity`): encryption constant (redrawn while 0xffffffff), TID | SID << 16, PID
(bit 28 flipped when shiny), height and weight, each 0x30 + next_int(0xa0). The rest comes from the
trainer's entry, with language 2 and the species' base friendship. The binding `f92C18AA6`
(`0x1905a10`) builds a pml InitialSpec seeded with `randSeed` (`0x1905ce0`, converter `0x160ffd0`,
creation `0xdef2b8`, draw order `0xdf011c`); its third argument makes random sizes class M (SizeType
3, `0x1611cc4`). An entry with `sex` 0 is female when the species' percent female is at least 15,
male otherwise (`0x1611d1c`). A `gemType` of 0 takes the Tera type from table `0xe78418`, keyed by
species x 10000 + form.

The pools are `world/data/raid/raid_trainer_01` (16 rows, stages 0 and 1), `_02` (18, stage 2) and
`_03` (18, stages 3 and 4), field `difficulty_0`*N+1* (`0.7797`). A row holds the trainer id
`raid_assist_NPC_*`, `npcPresetIndex` and `nameTextLabel`; the trainer's Pokemon is `poke1` of its
`trdata_array` entry: ability slot 1, 2 or hidden, three moves, `gemType`, IVs 31/10/31/31/10/31,
EVs 252 HP, 128 Def, 128 SpD, Hardy, Poke Ball, scale 128, no item.
`scripts/gen_sv_partner_data.py` decodes them into `pokeldn/sv/data/raid_partners.json`. A partner is
built at level int(0.8 x the level of battle slot 0's Pokemon), the host's (`0.4455`, `0.4901`).
Stage 5 gives Pikachu partners named after the boss and a crash, so `raid_point` refuses a stage past 4.

A retail host's `raidNpcGroupID` is its raid unlock stage, from native `0xe2826c` (Lua `0x193a560`,
`0.2895`): the highest of four save flags set, read through `0xeb1cf4`:

| flag key | name (PKHeX) | stage |
|---|---|---|
| none set | | 0 |
| `0xEC95D8EF` | `FSYS_RAID_DIFFICTLTY3_RELEASE` | 1 |
| `0xA9428DFE` | `FSYS_RAID_DIFFICTLTY4_RELEASE` | 2 |
| `0x9535F471` | `FSYS_RAID_DIFFICTLTY5_RELEASE` | 3 |
| `0x6E7F8220` | `FSYS_RAID_DIFFICTLTY6_RELEASE` | 4 |

The stage is the story progress less one; seven-star events share stage 4. A console ignores party
records in slots no lobby station holds. A guest that leaves the lobby before the start never holds
the RaidPoint.

`bin/sv_host.py` writes the stage of `--raid-progress` (six stars for a black crystal or seven-star
event), or `--raid-partner-progress`, and draws a new partner seed each run. With `--raid-partner` it
searches seeds until the first draws are those trainers in that order (about 306 seeds for two of
eighteen). Our player and each console hold a slot, so one console leaves two partners, two leave
one, three none (`raid_partners.slots`); extra `--raid-partner` flags are refused.

| # | trainer | stage 0, 1 | 2 | 3, 4 |
|---|---|---|---|---|
| 0 | Austin | Growlithe | Camerupt | Arcanine |
| 1 | Ava | Buizel | Floatzel | Toxapex |
| 2 | Logan | Skiddo | Gogoat | Arboliva |
| 3 | Hailey | Magnemite | Magneton | Bellibolt |
| 4 | Evan | Skwovet | Greedent | Dudunsparce |
| 5 | Charlotte | Staravia | Altaria | Staraptor |
| 6 | Kylie | Crabrawler | Primeape | Tauros |
| 7 | Hunter | Drifloon | Drifblim | Drifblim |
| 8 | Gianna | Stunky | Sneasel | Umbreon |
| 9 | Eli | Kirlia | Hypno | Gardevoir |
| 10 | Henry | Pawniard | Bronzong | Corviknight |
| 11 | Chase | Dedenne | Sylveon | Sylveon |
| 12 | Claire | Kricketune | Scyther | Heracross |
| 13 | Brooklyn | Rockruff | Lycanroc | Garganacl |
| 14 | Zoe | Sandile | Sandaconda | Mudsdale |
| 15 | Samantha | Snorunt | Glalie | Weavile |
| 16 | Dylan | | Dragonair | Haxorus |
| 17 | Luke | | Toxicroak | Clodsire |

### Favoured partners

Raiders rate ten partners of the stage 3 and 4 pool (Serebii's level 80) above the rest.
`raid_partners.RECOMMENDED` holds them, and the app's card for each ends on why and a star: blue for
the four raiders favour, silver for the next tier.

| rank | trainer | Pokemon | why |
|---|---|---|---|
| favoured | Eli | Gardevoir | Life Dew heals the whole team; seven-star solo guides ask for it, often with Bellibolt. |
| favoured | Hailey | Bellibolt | Light Screen, when she sets it, cuts the boss's special damage; Discharge can paralyze. |
| favoured | Logan | Arboliva | Safeguard keeps status conditions off the team; Grassy Terrain heals each turn and also powers a boss's Grass moves. |
| favoured | Charlotte | Staraptor | Intimidate on every respawn and Feather Dance cut the boss's physical Attack. |
| next tier | Austin | Arcanine | Intimidate on every respawn; Leer lowers the boss's Defense. |
| next tier | Kylie | Tauros | Intimidate on every respawn; Raging Bull breaks the boss's screens. |
| next tier | Hunter | Drifblim | Will-O-Wisp burns the boss, halving its physical damage. |
| next tier | Gianna | Umbreon | Thunder Wave paralysis can give a free turn, by chance. |
| next tier | Evan | Dudunsparce | Glare paralyzes at 100% accuracy, except a boss with an Electric Tera type. |
| next tier | Samantha | Weavile | Leer lowers the boss's Defense before its shield; Ice Punch can freeze. |

Intimidate raises the Attack of a Defiant or Competitive boss, such as Annihilape, on every respawn.
The earlier stages' pools have no Life Dew, Light Screen or Safeguard. The partners' moves changed
with The Teal Mask update; the sets above are Serebii's, which the sources describe.

Sources: Amiibo Doctor's Tera Raid NPC Partners Tier List (June 2025); Game8's
seven-star event guides (Skeledirge, Goodra, Dragonite); Smogon's seven-star raid threads
(Porygon2, Glimmora, Annihilape and others).

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
but is not on the raid's path. A boss record built from seed `BD13FB43` (Violet, Paldea, four stars) equals a retail bootstrap's byte for byte;
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

A Poke Portal News delivery holds `raid_enemy_array`, `fixed_reward_item_array`,
`lottery_reward_item_array`, `raid_priority_array` (FlatBuffers in the base tables' layout) and
`event_raid_identifier` (a u32 equal to the priority table's `VersionNo`). Later deliveries repeat
each file under a patch suffix (`_1_3_0`, `_2_0_0`, `_3_0_0`); the newest is read. A record adds
`RomVer` (0 both, 1 Scarlet, 2 Violet), `DeliveryGroupID`, `Difficulty` (7 for seven stars),
`CaptureRate` (0 never, 1, 2 once per save) and its own reward tables; its `BossPokePara` fixes:

| field | an event record |
|---|---|
| `Sex` | 0 drawn; 1 male, 2 female, no draw |
| `Seikaku` | 0 drawn; the nature plus 1, no draw |
| `TalentType` | 1: `TalentVnum` flawless IVs; 2: `TalentValue`'s six IVs, no draws |
| `RareType` | 0 drawn; 1 never shiny (bit 28 flipped); 2 always: the PID's high half rewritten to a shiny xor of 0 |
| `ScaleType` | 0 two draws; 1 to 5 one draw in 0-15, 16-47, 48-207, 208-239, 240-255; 6 `ScaleValue` |
| `Item`, `EffortValue` | the boss's held item and battle EVs |

`TimeDesc` is the record's `raidTimeData` (RaidPoint 0x030): active on every seven-star record
(`gameLimit` 450 to 900, `commandLimit` 60) and five five-star ones.

A den belongs to a delivery group, 1 to 10. xoroshiro from the seed draws and drops the standard
star roll, then a value under the total rate of the group's records of the console's version and an
allowed star level, and takes the record whose span holds it [PKHeX `EncounterDist9.GetIsPossibleSlot`]:

| progress | stage | stars drawn |
|---|---|---|
| beginning, Tera Raids | 0 | 1, 2 |
| 3-star | 1 | 1 to 3 |
| 4-star | 2 | 1 to 4 |
| 5-star, 6-star | 3 | 3 to 7 |

A rate-0 record is never drawn. Rewards are the record's fixed table, then lottery draws from the
delivery's tables (seven-star counts as six-star). An empty or quantity-0 lottery slot gives nothing;
Gimmighoul's first Scarlet round has only such slots.

`pokeldn.sv.raid_event` reads a delivery folder (an [EventsGallery](https://github.com/projectpokemon/EventsGallery)
event or its `Files`):

    ./.venv/bin/python bin/sv_host.py ... --raid-pokemon FILE --raid-seed 52E6B438 \
        --raid-event "EventsGallery/Released/Gen 9/SV/Raid Events/002 Charizard the Unrivaled" \
        --raid-version scarlet --raid-progress 6star [--raid-event-group 1] [--raid-catch-normal]

The RaidPoint carries the record's capture rate and, as the crystal, 2 for an event or 3 for a
seven-star event (Tera-Finder `RaidContent`). The app's Tera Raid (Host) tool downloads the gallery
and narrows version, progress and crystal to what the event spawns ([Raid events](gui.md#raid-events),
`raid_event.dens`).

A capture rate of 2 is a catch once per save. The save lists caught record numbers (block
`0x8B14392F`; defeated flags `0xA4BA4848`, PKHeX `RaidSevenStar9`), and reruns share a number, so one
catch closes every round. A console checks the list by the lobby descriptor's record number; a listed
number blocks the catch whatever capture rate the RaidPoint carries. `--raid-catch-normal` serves a
catch-once record as a normal catch: capture rate 1 and a stand-in record number in the descriptor,
the record's date with suffix 99 (`raid_event.stand_in`), which no delivery uses and which the save
does not list after the catch. No PK9 field or PKHeX encounter holds the record number, so legality
does not depend on it; the boss the host sends equals PKHeX's catch of that raid over 331 catch-once
raids. A seven-star catch is legal only with the Mightiest Mark, which the console gives.

A fixed row's subject 3 (a seven-star TM and Ability Patch) is applied by each console's reward
filter. Species data past the raid bosses comes from `pokeldn/sv/data/species.json`
(`scripts/gen_sv_species_data.py`). Over EventsGallery's 153 deliveries, pkNX's encounters equal
PKHeX.Core 26.8.26's, 20 080 generated bosses equal PKHeX's `GenerateSeed32`, and
`scripts/check_sv_raid_events.py` agrees with every `Encounters.txt`.

## Finding a seed

The app's raid seed field shows the boss and rewards the seed gives in the tool's context, and Find
a raid searches seeds from a first one, typed or picked at random, in every context the filters
leave (`pokeldn.sv.raid_search`) for a species, star level, Tera type, nature, gender, shininess,
size mark and IV ranges. It ranks the results by a score of the boss's stats (HP times the sum of
its defenses, either defense alone, its better attacking stat, or its total) or by the rewards
wanted (Most desired rewards, below). One result per species is kept unless a species is chosen.

### Size marks

PKHeX allows the Mini mark at scale 0 and the Jumbo mark at scale 255 (`MarkRules`); the finder's
Size mark filter wants either. The scale is drawn after the height and weight:

| scale rule | scale | chance of 0 or of 255 |
|---|---|---|
| two draws (rule 0), every standard and black boss | `next_int(0x81) + next_int(0x80)` | 1 in 16 512 each |
| an event band from 0 (rule 1) or from 240 (rule 5) | `next_int(16) + low` | 1 in 16 for the end it touches |
| an event's own value (rule 6) | the record's `scale` | always or never |

`raid_search.size_marks` names the marks an event's bosses can take; the finder greys out the others.

### Wanted rewards

The Rewards section wants rows of an item and the least quantity a raid must give of it, quantities
of one item summed. Offered items and quantities are those the searched raids can give
(`raid_search.reward_choices`). The search skips an encounter that cannot give what is wanted, then
draws a seed's rewards before its boss.

Most desired rewards ranks results by the wanted items in order. A raid's total of an item counts as
a digit, its place among the totals the searched raids can give (`raid_search.ranked_rewards`); the
leading items' digits make one score under 2^31, kept beside the seed in a 64-bit rank. Five items
fit in every known raid.

### The helper's scan

The PKHeX helper scans seeds over every core (`services/pkhex/RaidScan.cs`, driven by
`pokeldn.sv.raid_scan`): encounter, boss up to the scale, score, filters and rewards. It names a
context's best seeds, and `search` rebuilds their raids in Python, so results and ties are the
Python scan's (`tests/test_sv_raid.py` compares both). Each encounter row's best possible rank is
computed once per request, and a seed whose row cannot beat the kept ranks stops there.

A request holds 16 777 216 seeds, then as many as the helper scans in about 0.25 s, up to
268 435 456. A search covers up to 2^32 seeds per context (`most_seeds`); the finder offers a
hundred million, or every seed. Stop at the first match (`stop_at_first`) returns the earliest
matching seed. Without the helper, Python scans about 22 000 seeds a second and the finder offers
100 000.

| search, Apple M4, helper warm | time |
|---|---|
| 100 000 000 seeds in each of the 42 contexts, the finder's default | 5.2 s |
| every seed of one context | 6.1 s |
| every seed of the 42 contexts | 4 min 3 s |

## The battle between consoles

Measured between two emulated Scarlet 4.0.0, one hosting a 4-star crystal and one joining from the
Poke Portal, two NPC partners in the free seats. The hosting console stays in the session for the
whole battle. Every battle message is a battle-start frame on key 0x007b addressed (0x2713, x, y), its
32-byte header's type at +0x00, a u64 step counter at +0x08, a u64 round at +0x10, then 5 and a
battler or station byte at +0x18 and +0x19:

| type | from | size | what |
|---|---|---|---|
| 0x01, 0x05, 0x11, 0x15, 0x25, 0x29, 0x47, 0x49 | the host, address (0x2713, 1, 2) | 50 to 20626 | a step; each guest answers type + 1 under the same counters |
| 0x02, 0x12, 0x16, 0x26, 0x2a, 0x48, 0x4a | every station, address (0x2713, 3, 5) or (0x2713, 2, 2) | 50 | the answer to a step |
| 0x06 | a station for its own battler; the host for its own, for each NPC's and again for the guest's | 250 | one battler's command; +0x19 is the battler slot (0 host, 2 the guest, 3 and 4 the NPCs) |
| 0x15 | the host, one per acting battler, the boss included | 20626 | the round: five 0x70-byte action blocks (slots 0 host, 1 boss, 2 guest, 3 and 4 NPCs) at +0x20, a byte per slot counting the actions in its block at +0x250 ([Actions](#actions)), the server command queue's length at +0x258 and the queue from +0x25c; 123 to 802 bytes deflated |
| 0x46 | the host, 62 times at the start | 54 | |
| 0x51 | the host | 86 | |

The battle is server and client. The host's builder `0x113c8a0` (type 0x15 at `0x113c908`) copies the
action blocks, runs the round (`0x113e3d0`) and appends the server command queue it produced; the
host's AI makes the NPCs' commands, and the boss's action reaches a guest only inside a 0x15. A guest
plays the queue, and for types 0x13, 0x15, 0x17, 0x19, 0x1f, 0x23, 0x25 and 0x4d it rebuilds the body
from the host's action blocks with the same builder and compares size and bytes (`0xf5cfa4`); a
mismatch goes to `0xf5bfd4`, the receive-timeout handler. A station that hosts a battle has to produce
the queue Scarlet's own engine produces from the same state.

### Which station runs the server

The battle server is the first entry of the port-2 member list every console builds from the lobby
host's Session type 6 and type 9s; `pokeldn.sv.port2.build_session` puts the host first.

| step | code |
|---|---|
| the raid start `0.4455` sets the server slot to 0: `setup:f4891D27C(0)` | `0x182ca10` -> `0x2d36398`, setup `+0x94` |
| member i maps to slot 0, 2, 3, 4; its code goes to `+0x99+slot`, and for its own code the slot to `+0x90` | `0x1ccd15c` over port-2 `+0x170`; `0x2d363a0`, `0x130ea2c` |
| `0x2a1cd74` copies setup `+0x94` to `net+0x58` and `+0x90` to `net+0x5c` at battle start | from `0x18915c4` |
| a console is the server when `!setup.710 && slot == net+0x58` | net vf `+0x78` = `0x2a1d994` |
| the 0x15 checker is installed only on a non-server | `0xfb0ee8` |
| a receive timeout or failed check calls net vf `+0x70` = `0x2a1d920`; in a raid `0x18e217c` sets `net+0x58` to the console's own slot | `0xf5bfd4` |

Setup `+0x710` is set only by `0x7faed0` (Lua `f3AF42713`), never by the raid start. A console that
loses the server makes itself the server, so when the lobby host stops sending each console fights
its own battle. The member vector is append-only, written through `0x18b65c8` -> `0x18b68fc` by a type
6 or 7 session block (`0x18b566c`, appended first), the type-6 replay (`0x279ba2c`) and type 9
(`0x1954bac`); a type 9 before any block is dropped (`0x18b65e4`). Bootstrap participant k belongs to
the member with code k; a member code naming an empty participant aborts loading (2162-0001). A
failed-over console runs every other battler by its own AI (`0xfa52b0`, `0xfa5314`). Its code is that
of the first vector entry with its station (`0xd5f3b4`); the Lua slot loop has no break, so the last
matching entry sets its slot.

### The battle's random numbers

Every random draw of a round comes from one xoroshiro128+ object of 0x28 bytes (vtable `0x4500bd0`):

| offset | size | what |
|---|---|---|
| 0x00 | 8 | vtable |
| 0x08 | 2 x u64 | the state |
| 0x18 | u64 | the seed |
| 0x20 | u64 | the number of draws made |

The server's main module (0x378 bytes, constructor `0x12742d0`) holds it at `+0x10`; round code
reaches it as `[[x+0x10]+0x10]` (`0x11440e8`). The module's initialiser `0x127d824` sets the state
to the seed and `0x82A2B175229D6A5B`, the count to 0 (`0x127d9a8`), taking the seed from `+0x20` of
its parameter block. A guest's checker fills that word from the battle setup's `+0x718`
(`0x2891748`); the raid start `0.4455` (@1152..@1157) sets `+0x718` through the Lua binding
`fAF4A81E0` (setter `0x7faf1c`) to the RaidPoint's `randSeed`. The partner seed is also the battle
seed, and the station that writes the bootstrap chooses it. The per-slot modules a server builds
(`0x126ba88`, from `0xfa9f90`) are initialised with seed 0.


A draw adds `s0 + s1` and steps the state; the count rises by one per call, not per redraw:

| function | draw |
|---|---|
| `0x11440f0(rand, n)` | a u64 below n: `s0 + s1` masked to the bits of n − 1, redrawn while n or more; n below 2 returns 0 and draws nothing |
| `0x114da8c(rand, p)` | `(s0 + s1) & 0x7f` redrawn while 100 or more; true when below p |

Many round functions inline the step instead of calling these.

### Damage and draws per move

A move use draws, in this order:

| draw | when | what it decides |
|---|---|---|
| `chance(25)` | the user is paralysed | a full paralysis |
| `chance(33)` | the user is confused | hitting itself, whose roll is a `below(16)` that replaces the move's draws |
| `chance(accuracy)` | the move has an accuracy; 100 still draws | a hit |
| `below(24)`, `below(8)`, `below(2)` | a damaging move, by critical-hit stage 0, 1, 2 | a critical hit when 0 |
| `below(16)` | a damaging move | the roll r: the damage times (100 − r) / 100 |
| `chance(p)` | a secondary effect of chance p (Body Slam's 30) | the effect |

A flinch secondary against the boss draws nothing ([A move in the round queue](#a-move-in-the-round-queue)
has the rule). A confusion secondary steps the generator once, through a call outside `below` and
`chance`, before its `chance(p)`: 20 of 20 confusion draws with every draw logged (Confusion, Psybeam,
Water Pulse, Strange Steam, Magical Torque), whatever the step's output. A confusion that lands draws
no duration. A stat-lowering secondary of 100 percent (Spirit Break, Bulldoze) draws `chance(0)` in
some rounds and nothing in others. Battlers of equal Speed draw `below(2)` in the speed sorts ([Speed
ties](#speed-ties)). A flinch secondary draws
nothing against the boss or a target with Inner Focus (ability 39), unless the user has Mold Breaker,
Turboblaze or Teravolt (104, 163, 164); against a player that already moved in the round it draws its
`chance(p)`, and a flinch that lands there adds nothing to the queue. A contact move into Static, Poison
Point, Flame Body or Cute Charm (abilities 9, 38, 49, 56), or from a user with Poison Touch (143), draws
`chance(30)` after the move's secondaries; into Cute Charm only between a male and a female. A hit that
knocks the boss out draws no secondary and no contact chance. Over the 156 oracle
battles that log every draw, the draws of every round the plugin builds equal the logged ones.

A battle draws `below(100)` once before its first round. The damage is Showdown's Gen 9 formula (data
from Pokemon Showdown's `moves.json` and `typechart`) with the party record's stats and the boss
defending as its Tera type only: 921 of 1346 hits on the boss before any stat stage change fit it, and
for 137 of 140 hits with every draw logged the logged roll and critical draw give the recorded damage.
Hits that do not fit come during the boss's shield (about 0.45 of the formula), from moves with their
own rules (Body Press, Rising Voltage, multi-hit moves) or are capped at the HP left.

Abilities change the formula as Showdown's do, each applied alone with its own 4096ths modifier
(a pair chained into one modifier is unmeasured): Hustle (55) raises a physical move's Attack 1.5 times
and lowers its accuracy to 3277/4096; Compound Eyes (14) raises accuracy 5325/4096, capped at 100;
Thick Fat (47) halves the attacker's stat for Fire and Ice; Strong Jaw (173) raises a biting move's
power 1.5 times, Reckless (120) a recoil move's 4915/4096; Tinted Lens (110) doubles a not very
effective hit after the type multiplier; Ice Scales (246) halves a special hit after a burn's halving,
unless the attacker has Mold Breaker, Turboblaze or Teravolt. Skill Link (92) gives five hits and still
draws the hit-count roll. Serene Grace (32) doubles every secondary chance; Stench (1) adds a 10 percent
flinch drawn before the move's own secondaries; Shield Dust (19) on the target removes the secondaries
and their draws. Rock Head (69) takes no recoil. Gluttony, Pickpocket, Symbiosis, Ripen and Cud Chew
(82, 124, 180, 247, 291) do nothing while no battler holds an item.

Sun raises a Fire hit's base damage 1.5 times and halves a Water hit's, rain the reverse, before the
critical hit (Showdown's `onWeatherModifyDamage`; 125 corpus rounds with such a hit build equal). Swift
Swim, Chlorophyll, Sand Rush and Slush Rush (33, 34, 146, 202) double Speed in their weather, for the
order keys, the sorts and `0x5a` alike; Sand Veil and Snow Cloak (8, 81) lower a move's accuracy against
their holder to 3277/4096 in theirs (83 corpus rounds with one of the six in its weather build equal).
Sand Veil, Overcoat, Sand Rush and Sand Force (8, 142, 146, 159) take no sandstorm damage.

A terrain (Grassy 1, Misty 2, Electric 3, Psychic 4) changes the power of a move: 5325/4096 for a move of
its type from a grounded user (Grass, Electric, Psychic; Misty Terrain boosts none), a half for a Dragon
move into a grounded target in Misty Terrain and for Earthquake or Bulldoze into one in Grassy Terrain.
A battler is grounded unless it is Flying, has Levitate or holds an Air Balloon. 151 corpus rounds under
Electric, Psychic or Misty Terrain (42, 57, 52) build equal with these rules.

A boss's HP pool is its record's HP times the RaidPoint's HP coefficient over 100 ([The battle
bootstrap](#the-battle-bootstrap)): of the oracle battles won, 78 at one star, 84 at two, 125 at three and 35 at
four ended after exactly 5, 5, 8 and 12 times the record's HP in `0x37 (2, 2, damage)`; the others took
less, through the shield and moves with their own rules.

### Statuses

A secondary that lands a major status runs, after the hit's record: `0x13 (T, condition, 0, value, A)`,
`0x90 (T, condition)`, `0xa7 (T's position, code)` and `0xcb (A, text, T)`:

| status | condition | value | code | text |
|---|---|---|---|---|
| paralysis | 1 | 1 | 46 | 92 |
| sleep | 2 | turns << 3 \| 2 | 42 | 103 |
| freeze | 3 | 1 | 45 | 97 |
| burn | 4 | 1 | 44 | 86 |
| poison | 5 | 1 | 43 | 79 |
| bad poison | 5 | 7801 | 43 | 80 |
| confusion | 6 (no `0x90`) | turns << 3 \| 2 | 47 | 116 |

A sleep secondary draws its turns as 2 + `below(3)` and a confusion secondary 2 + `below(4)` before its
`chance(p)`, through a call the draw log does not show (the call counter at `rand+0x20` still counts it).
A target already statused, or immune by its types (Electric to paralysis, Fire to burn, Ice to freeze,
Poison and Steel to poison), takes nothing. A confusion secondary into Own Tempo (20) still draws and
shows nothing.

Before a move, a flinched battler shows `0xcb (A, 122, A)` and `0x52 (A, 0)`; a frozen one draws
`chance(20)` to thaw and, staying frozen, shows `0xcb (A, 98, A)`, `0xa7 (A's position, 45)`, `0x52 (A,
0)` and `0x1d (A, P, type, 0, 0, M, M)`; a paralysed one draws `chance(25)` and, fully paralysed, shows
message 93 and code 46 the same way; asleep, message 104 and code 42. Each ends with `0x5b (A, M)` twice
and `0x1e (A, 0)`, after the move's handler `0x5a (A, M, 0x72000 + speed)`. A paralysed battler's Speed
is halved after its stage. A burned user's physical damage is halved after the type effectiveness, at
least 1. A Fire hit on a frozen target thaws it after its `0xd1`: `0x14 (T)`, `0x90 (T, 0)`, `0xcb (T, 99,
T)`. The shield going up and the boss's own stat reset (between its `0x0f (2)` and `0xc2 (3, 2, 2)`)
cure the boss's status with `0x14 (2)` and `0x90 (2, 0)`; the shield also ends its confusion with `0x15
(2, 6)`.

Confusion acts before a move, after a freeze or sleep check; a battler both confused and paralysed is
unmeasured. Its turns run down by one; at 0 it ends with `0x15 (A, 6)` and `0xcb (A, 118, A)` and the move goes on.
Otherwise it shows `0xa7 (A's position, 47)` and `0xcb (A, 117, A)` and draws `chance(33)`; a hit on
itself draws its roll `below(16)` and nothing else: Showdown's 40-power typeless physical damage at the
battler's own Attack and Defense stages, shown as `0x91 (A)`, `0x01 (A, the battler that confused it,
damage, 2)`, `0x9a (A, -damage)`, `0xca (A, 576, A)`, `0x52 (A, 0)`, then the stopped move's end (the
boss's with its `0x1d`). The boss's extra-action move checks its confusion the same way inside its
`0xc1 (9, 0)` and `0xc1 (9, 1)`.

A faint clears the battler's status and confusion.

At a turn's end a burn deals a sixteenth of the battler's record HP (the boss's record HP, not its pool)
right after its `0x19 (b, 4)`, a poison an eighth after `0x19 (b, 5)`, a bad poison n sixteenths on its
n-th turn end: `0xa7 (b's position, 44 or 43)`, `0x01 (b, the battler that inflicted it, damage, 39 or
38)`, `0x9a (b, -damage)` and `0xcb (b, 88 or 82, b)`. Speed Boost (ability 3) raises Speed after the
`0x44` list (`0x25`, `0xc7`, `0x0c (b, 5, 1)`, `0x92`, message 15, `0xc8`), before the turn end's last
three battler sorts, except in the turn the battler was revived (Showdown's `activeTurns`). Shed Skin
(61) and Hydration (93) without a status, and Healer (131) on the boss, which has no ally, show and
draw nothing at a turn's end.

### Speed ties

The battle orders battlers and actions by Speed with an exchange sort: each entry is compared with
every later one, and the later one moves ahead when its key is greater. Equal keys draw `below(2)`,
and 1 moves the later one ahead, so a tie draws once per comparison of the two tied entries. Battler
ids are 1 to 5, the boss 2. Over 142 oracle battles with two battlers forced to one Speed, the sort
over the five battlers in id order gives the logged number of draws at the battle start in 142.

| when | over, in this input order | sorts | what reads the result |
|---|---|---|---|
| the battle start, before Trace's draw | the five battlers, id order | 1 | the switch-in events |
| a round's start | the round's actions, command order; key priority, then not Stall, then Speed | 3, each of the previous one's result | the first: the second `0x51` pass; the third: the order of the moves |
| after each move but the last | the actions | 1 | nothing in the queue |
| a round's end | the standing battlers, id order each time | 3 | the second: `0x43` |
| a turn's end (every fourth round) | the standing battlers, id order each time | 8 | the fourth and fifth agree with `0x19`; the seventh, after the turn's end: `0x43` |

The round-end `0x43` order matched the second sort in 109 of 123 battles; the 14 others had a battler's
Speed changed by a move in that round. The chained action sorts matched the `0x51` and move orders in
27 of 27 rounds whose two actors tied, and the draw after the first move came in 3 of 3 rounds that
reached both moves. The turn-end orders matched in 8 of 8 turn ends whose sorts disagreed.

The boss's Trace draws `below(N)` over the players whose ability it can copy, in id order: `below(3)`
with one player holding Embody Aspect. A move into Shell Armor (ability 75) draws no critical hit.

### A move in the round queue

In a round's queue a battler's move is one run of commands. A battler's client position is 0 to 3 for
battlers 1, 3, 4 and 5 and 4 for the boss; A is the user, T the target, M the move, `type` the move's
type index and `cat` its category (1 physical, 2 special). Measured on oracle rounds where a player's
move hits the boss and the boss's reply hits a player:

| command | meaning |
|---|---|
| `0x05 (A, slot, pp)` | a player's move begins, spending pp (2 against a target with Pressure, else 1); the boss's has none; `slot` is the move's index in the user's moveset, as in `0x07 (A, slot)` and `0x08 (A, slot)`; a raid action's move outside the boss's moveset has no `0x07` and no `0x08` |
| `0x07 (A, slot)` | the move is used |
| `0xc9 (A, 0, M, T's position, 0)` | the move and its target |
| `0x7b (M, n, A)` | n counts the rounds before this one |
| six `0xcf` groups of zeros | 20, 5, 5, 5, 19 and 20 bytes |
| `0x7e (0, ...)`, `0x7e (1, ...)`, `0x7e (2, e, e, e, e, e)` | the first: 1 at T's position + 1; the second: 1 there for a critical hit; the third: an effectiveness code per position, 7 for none |
| `0x8b (A's position, T's position, M, type, 0, 0, 1, tera, class, 0)` | the hit; `tera` is 1 when the boss uses a damaging move of its Tera type (448 of 448 such hits), else 0; `class` is the move's target class: 0 one target, 1 adjacent ally or self, 4 all adjacent, 5 all adjacent foes, 6 allies, 7 self, 9 a random foe, 10 the field, 11 the foe side, 12 the ally side, 13 scripted (Showdown's `target` names, over 19,245 oracle hits) |
| `0x37 (T, 2, damage)`, `0x37 (T, 5, 1)`, `0x02 (T, A, damage, 3)` | the damage |
| `0xd0` with bytes `T, e` | e is the effectiveness: 7 neutral, 6 not very effective, 8 super effective |
| `0x8e (1, 1, M)`; `0x8e (1, 3, M)` and `0xca (A, 575, 0xffff0000)` when not very effective; `0x8e (1, 2, M)` and `0xca (A, 574, 0xffff0000)` when super effective | the effectiveness message |
| `0xa7 (T's position, 131)`, `0x20 (A, 26)` | only for a critical hit, then `0x37 (A, 0, 1)` also comes just before the damage commands |
| `0x20 (A, 24)` | only for a super-effective hit |
| `0x42 (T, A, A's position, type, cat, M, damage)` | the hit's record |
| `0x25 (T)`, `0xc7 (T, 0)`, `0x0c (T, 5, 1)`, `0x92 (T, 5, 1, 0)`, `0xcb (T, 15, T)`, `0xc8 (T)` | Rattled (ability 155) raising T's Speed after a Bug, Dark or Ghost hit |
| `0xcb (T, 138, T)`, `0x1e (T, 15)`, `0x26 (T, 0)`, `0x4f (T, 0)`, `0x62 (T)` | T's Air Balloon (item 541) popping; it leaves T |
| the drain, when the move drains and its user is below full HP | `0xa7 (A's position, 51)`, `0x03 (A, heal)`, `0x9a (A, heal)`, `0xcb (A, 290, T)`; heal is damage times the drain fraction, rounded half up, uncapped even when the user lacks less (2 of 2 such rounds); the HP it restores stops at full |
| the secondary effect, if any | for example a paralysis: `0x13`, `0x90`, `0xa7`, `0xcb (2, 92, T)` |
| `0xd1` with bytes `01 00`, `0x2e (2, A − 1)` | |
| `0x85 (7, damage)` | only for damage to the boss |
| `0x7c ()`, `0x08 (A, 0)`, `0x1d (A, T's position, type, 1, 0, M, M)`, `0x5b (A, M)` twice, `0x1e (A, 0)` | the move ends |

A round ends with `0xb2 (0)`, `0x37 (b, 7, 1)` for each battler that moved, `0x75 (3, n)`, `0xc5 (1)`,
`0x43 (b)` for each battler in speed order (party record speed at its stat stage, the boss among them), `0x23 (b)` for
each of the round's actors in id order, or all five in the battle's first round, and `0x2d (0)`;
`0x75 (3, n)` counts the command rounds of the current turn, this one included. A turn ends with every
fourth command round, whichever slots sent them (3,606 of 4,090 turn ends in the oracle corpora; the rest
have one or two raid-action rounds between, which do not count): its `0x75 (3, 0)` is followed by
`0xc5 (0)`, `0x50 (0)`, `0x19 (b, k)` for each end-of-turn kind k in the order 36, 21, 18, 5, 4, 9, 10, 8,
46, 43, 48, 11, 12, 23, 13, 31, 33, 15, 19, 29, 30, 38, 37, 39, 40, 41, 24, 45, 14, 20, 1, 2, 3, 7, 6,
16, 17, 22, 25, 26, 27, 28, 32, 34, 35, each over the battlers in speed order, then `0x44 (k)` for k 1
to 13, before the usual `0xc5 (1)`. A weather lasts five turn ends, the turn it rises in counting as
the first: at its fifth it ends right after `0x50 (0)` with `0x99 (w)`, `0x54 ()`, `0x6a (0)`, and a
sandstorm ending does no damage that turn (7 of 7 weather ends in the oracle corpora). Sun, rain and
snow add nothing at a turn's end. A terrain lasts five turn ends as well and ends between `0x44 (8)`
and `0x44 (9)` with `0x34 (8)`, `0x6a (8)`, `0xca (0, text)`, `0x32 (0, 0, 1, 0)`, `0x6a (8)`, `0xb2 (0)`,
`0xaa (0)`, `0x69 (8, 0)`; the end text is 705 Grassy, 709 Electric, 829 Psychic (Misty's is not in the
corpora). A sandstorm adds, after `0x50 (0)`, for each battler in speed
order it damages (a sixteenth of its maximum HP): `0xcb (b, 133, b)`, `0xa7 (b's position, 14)`, `0x01
(b, s, damage, 1)` with s the battler that raised the sandstorm (its Sand Stream or Sand Spit, or the
boss's Sandstorm), and `0x9a (b, -damage)`. Moody (ability 141) acts at a turn's end. Other held items
and Grassy Terrain's heal at a turn's end are unmeasured.

A damaging move the target's types are immune to draws nothing, not even its accuracy, and runs
`0x05`, `0x07`, `0xc9 (A, 0, M, P, 1)`, `0x7b`, five `0xcf` groups (20, 5, 5, 5 and 19 zero bytes), `0xcb
(A, 72, T)`, `0x52 (A, 3)`, `0x08 (A, slot)`, `0x52 (A, 0)`, `0x1d (A, P, type, 0, 0, M, M)`, `0x5b (A, M)`
twice and `0x1e (A, 0)`: 5,353 of the 5,550 message-72 runs in the oracle corpora (the rest open an ability activation).
A Ground move into a target with Levitate (26) that its types do not already make immune runs the same
way with message 72 inside the target's ability activation: `0x25 (T)`, `0xc7 (T, 0)`, `0xcb (T, 72, T)`,
`0xc8 (T)`, then `0x52 (A, 3)`.

A damaging move that misses its accuracy draw runs as an immune one with message 73 and `0x52 (A, 1)` in
place of message 72 and `0x52 (A, 3)`. A player's move with no PP left (the party record's PP, less 1 per
use, 2 against Pressure) runs only `0xc9 (A, 0, M, 10, 1)`, `0xca (A, 578, A)`, `0x52 (A, 0)`, `0x5b (A,
M)` twice and `0x1e (A, 0)`, before a paralysis draws its `chance(25)`.

A status move aimed at the boss while its shield is up fails before it runs, with no draw: `0x05`,
`0x07`, `0xc9 (A, 0, M, P, 1)`, `0xca (A, 567, A)`, `0x52 (A, 0)`, `0x1d (A, P, type, 0, 0, M, M)`, `0x5b
(A, M)` twice and `0x1e (A, 0)` (120 of 120 stat-dropping and status-inflicting moves into the shield in
the oracle corpora; a move on its user still runs). A stat-dropping move into a target whose dropped
stats are all at -6 runs as an immune move with `0xcb (A, 60, T)` alone in place of message 72 and
`0x52 (A, 3)`, with no draw.

A weather move (Sunny Day, Rain Dance, Snowscape, Sandstorm) runs as a stat-stage status move with the
field class (10) and, in place of the stat changes, the weather's start: `0x6a (0)`, `0x69 (0, w)`,
`0x79 (w, 5, 0, A, 0)` and `0x88 (w, A, 0)`, w 1 sun, 2 rain, 3 snow, 4 sand; a status move that inflicts a
status (Thunder Wave, Will-O-Wisp, Toxic, Spore) runs the infliction there ([Statuses](#statuses)). A
terrain move runs the same way with the terrain's start: `0x32 (t, 0, 42, A)`, `0x6a (8)`, `0xb2 (0)`,
`0xaa (t)`, `0x69 (8, t)` and `0xca (A, text)`, the start text 704 Grassy, 706 Misty, 708 Electric, 828
Psychic; a terrain already up fails it with text 567. Weather is field slot 0 and terrain field slot 8 in
`0x6a`, `0x69` and `0x44`.

Tailwind (366) raises side condition 4 on its user's side (0 the players', 1 the boss's) for four turn
ends, the turn it rises in counting as the first. It runs as a weather move with the side class (12) and
position 10 in its `0x8b` (the `0xc9` keeps the commanded position), then `0x4a (side, 4, 0, 34, A)`,
`0x65` with the same arguments and `0xca (A, 643, side)`. It doubles the Speed of its side's battlers in
the order keys and the sorts but not in a handler's `0x5a`. Each turn end it is up adds `0x4c (side, 4)`
after the last `0x19` and before `0x44 (1)`; at its fourth come `0x4b (side, 4)`, `0x66 (side, 4)` and
`0xca (A, 645, side)` with A the battler that raised it. Side conditions 0, 1 and 2 end the same way with
texts 625, 629 and 637. A battler with Wind Power (277) on the Tailwind's side is charged right after the
start text: `0x25 (b)`, `0xc7 (b, 0)`, `0xcb (b, 1024, b, 366)`, `0xc8 (b)`, `0x1e (b, 20)`, `0x7d (20, b,
0, 0)`; Wind Rider (274) beside a Tailwind is unmeasured. 47 corpus
rounds with a Tailwind up, three with its end, build equal.

A two-to-five-hit move rolls its hit count right after the accuracy draw (`0x19d4f2c`): one draw of the
battle generator's low 7 bits, redrawn while 100 or more, gives 2 hits under 35, 3 under 70, 4 under 85,
else 5; a fixed count (Double Kick's 2, Triple Dive's 3) draws nothing. Each hit draws its critical hit and
its roll and runs, after a 20-byte zero group, its own `0x7e` triple, `0x8b` with the hit index as the
sixth argument and the hit count as the tenth, the damage commands with `0x8e (1, e, M)` only, `0x42` and
`0xd1`; a hit that knocks its target out ends the run, and its knockout commands carry no fainted
message. The tenth argument of every hit's `0x8b` is the number of hits that landed, so the hits are
counted before their commands go out. After the last hit come the effectiveness message
`0xca (A, 574 or 575)` when not neutral, `0xca (A, 516, hits)`, `0x20 (A, 24)` once per hit when super
effective, `0xa6 (96)`, then the move's usual end with `0x85 (7, total damage)` on the boss; Dragon
Darts shows no message 516. Every two-to-five-hit round of the corpora builds equal this way.

A status move whose only effect is stat stages runs `0x05` (a player's), `0x07 (A, 0)`, `0xc9 (A, 0,
M, P, 0)` with P the commanded position, `0x7b (M, n, A)`, one `0xcf` group of 20 zero bytes, `0x7e (0,
0, 0, 0, 0, 0)`, `0x7e (1, 0, 0, 0, 0, 0)`, `0x7e (2, 7, 7, 7, 7, 7)`, `0x8b (A's position, T's position,
M, type, 0, 0, 0, 0, class, 0)` (T is A for a move on itself, class 7), the stat changes, then `0x7c ()`,
`0x08 (A, 0)`, `0x1d (A, P, type, 1, 0, M, M)`, `0x5b (A, M)` twice and `0x1e (A, 0)`. A raise is `0x0c
(b, stat, n)`, `0x92 (b, stat, n, 0)` and `0xcb (b, text, b)`; a drop is `0x0d (b, stat, n)`, `0x93 (b,
stat, n, 0)` and `0xcb (A, text, b, stat)`. The text is 10, 17 or 24 plus the stat for a raise of 1, 2 or
3 stages and 31 or 38 plus the stat for a drop of 1 or 2 (stats 1 Attack to 7 evasion), in stat order
(Coil raises Attack, Defense, then accuracy), over every
stat change in the oracle corpora. A move that cannot miss (Showdown accuracy `true`) draws no accuracy.

A spread move (Showdown target `allAdjacent` or `allAdjacentFoes`) hits only the position its
command names, with the single-target damage and no spread modifier: every oracle round holding one
builds equal as a one-target hit, with `class` 4 or 5. Moves run in priority bracket order, then by
Speed at its stat stage: a boss's Aqua Jet or Shadow Sneak moves before a faster player.

A hit that knocks the boss out wins the battle. After its `0x42` come `0x49 (2, A, M)`, `0x09 (A, slot)`
with `slot` M's index in A's moveset (382 of 383 oracle knockouts),
`0x37 (2, 1, 1)`, `0xcb (2, 0, 2)`, `0x94 (2, 0)`, `0x37 (2, 8, 1)`, `0x5f (2)`, `0x62 (2)`, `0x6c (2)`,
`0x5d (2)`, `0x41 (b, 2)` for each player in id order, `0x33 (2, k)` for k 0 to 13 (8 only while a
terrain is up), `0x80 (2)`,
`0x29 (2)` and `0x38 (A)`, then the move's usual end. Nobody moves after it, and the round ends with
only the `0x43` of the battlers left standing, the `0x23` list and `0x2d (0)`. The `0x85 (7, damage)`
and the damage commands carry the HP the boss had left.

The prefix starts with `0xb5 (0)`, then runs `0x51 (b, 1)` once for the round's actors in id order and
once in the order of the first action sort; in the second run a battler with Stall (ability 100) carries
`0x51 (b, 0)`, and from then on its actions sort last in their bracket; the round's first sort still
counts it as 1. Mycelium Might (298) carries `0x51 (b, 0)` the same way for a status move only, and
Prankster (158) raises a status move's priority by 1. Every action sort ([Speed ties](#speed-ties)) first computes each move
action's order key in the list's order, and a move that registers its own handler shows that as `0x5a
(b, M, speed)`, speed at its stat stage, and `0x5b (b, M)`. The round's first move to run computes every
move action's key once more, and a mover whose move registers a handler adds `0x5a (b, M, 0x72000 +
speed)` just before its `0x05` (the oracle's command log interleaved with its sorts and action runs).
347 of 631 moves register one (Facade and Body Slam among them, Night Slash not).

The boss is Terastallized from the start: a damaging move of its Tera type hitting under 60 power after
its base power modifiers, with no priority and a single hit, hits at 60, Gen 9's Tera rule (a Smoliv's
Tera Normal Tackle did 4 where 40 base power gives 2; a Rivalry boss's Tera Dark Bite into a player of
the other gender did 25, the unmodified 60-power damage, where Rivalry's 45 gives at most 21). A move's secondaries each draw `chance(n)` in Showdown's order, except
a flinch against the boss, which draws nothing: a player's Ice Fang on the boss draws only its
freeze chance (a freeze shows as `0x13 (2, 3, 0, 1, 4)` with messages 97 and 98, and the boss draws
`chance(20)` to thaw before it moves), the boss's Ice Fang on a player draws both. A hit that knocks
the boss out draws `chance(0)` first, with or without a secondary.

Built this way from Showdown's move data and the Gen 9 damage formula, 56 of 554 oracle battles'
first rounds equal the oracle's byte for byte and none differ (the others hold something refused);
20 whole battles equal the oracle's in every round, and served against a scripted console 19 of 19
send every frame the oracle server sends, at the same frame.
A round is refused when a battler that acts or is hit holds an ability or item whose Showdown callback
can change the round (Hustle's attack, Rivalry's power, Friend Guard's 0.75, Rattled's speed raise
after a Dark hit, Gale Wings' priority), unless the corpus measured that ability or item idle, or
when the battle holds an ability that acts on switching in (Intimidate lowers the attacker's Attack
before the first round).

### Actions

A round's action header (the request block, 0x238 bytes) is five 0x70-byte blocks, one per client
slot, each up to seven 16-byte actions (a u64 action word, a u32 actor battler id, 4 bytes no code
writes), and at +0x230 a byte per slot counting the actions in its block. The server decodes them in
slot order into 0x8c-byte action
entries (`0x1145e40`, decoder `0x11461b4`). The action word's low four bits are the kind:

| kind | entry kind | fields of the word |
|---|---|---|
| 1 | 1, a move | bits 4..7 the target's battle position, 8..23 the move, bit 25 a flag |
| 2 | 2 | bits 4..19 and 20..27; the next u32 |
| 3 | 3, a switch | bits 4..7 the party index (the actor is that party member), 8..11, bit 12 |
| 4 | 6 | bits 4..11, 12..15 and 16..23 |
| 5 | 4 | bit 4 |
| 6 | 5 | bits 4..11 |
| 7, 10, 11 | 7, 8, 9 | none |
| 9 | 10 | bits 4..11 |
| 12 | 11 | bits 4..11; the next u32 |
| 13 | 14 | bits 4..7, 8..11, 12..15, 16..27, 32..43, 44..55, 56..59, 60..63 |

A word whose bits 0..3 are 3 and bit 12 is set is skipped, as are kinds 0, 8, 14 and 15. A recorded
player action `41 67 03 00 ...` is a move (kind 1) at target position 4, move 871 (Torch Song).

Battler ids in a raid: 1 the Pokemon in slot 0, 2 the boss, 3 slot 2, 4 slot 3, 5 slot 4. A station's
type-0x06 command is 0xe8 bytes: the 0x20-byte header (+0x19 the slot), a count byte at +0x20, then
(u64 word, u64 actor) pairs from +0x28. It carries the slot's own action and the boss's reply to that
slot: a guest's command for slot 2 held `move 871 at position 4 by battler 3` and `move 204 at position 1
by battler 2`. The station chooses the boss's move against its own Pokemon.

The server fills one round's request block per acting slot:

| step | code |
|---|---|
| a 0x240-byte block on the poster's stack: every action's word and actor zeroed, the counts zeroed, the kind (0x15) at +0x238 | `0xf6e6a8` in the per-slot reader's step `0xf6df44`; `0xf71d10` for other kinds |
| the slot's type-6 message (reader +0x30 the store, u32 +0x38 the slot) copied in: count byte cleared, each pair's u64 word and the actor's low u32 appended, the count raised; no bound, a count over 7 runs into the next slot | `0xf702ec` -> `0xf7065c` (key 6, 0xe8-byte messages); key 0x10 goes to `0xf72038` (0x30-byte messages of one action, taken while the slot holds at most six) |
| the 0x240 bytes posted as a job of type hash `0xae1b39fccfd09053` | `0xf6ffb8`, job class vtable `0x4494198` (constructor `0x17b52a4` copies the 0x240 bytes to job +0x78) |
| the job copies the block to the server object's +0x210 (the builder's [o+0x40]) | `0x16e4f84` -> `0x113bac0` |
| the step counter +0x198 raised; a body already received for that step (`0xe63734` over the deque at [[server+0x448]+0x38]) replaces the build; otherwise the builder with kind 0x15 | `0x113bad8` -> `0x113c8a0` |

### The server command queue

A type-0x15 record's queue (+0x23c of the body, its length at +0x238) is a run of commands. A
command is a big-endian u16 id, then its arguments packed by the id's format as one big-endian bit
stream, padded at the front to whole bytes (writer `0x119bf58`, jump table `0x3c6aa7c`). The id to
format map is built from 208 rows of (u16 id, u8 format, u8 0) at `0x3c6abe4`, a later row for the
same id winning; ids run 0 to 205. Ids 0xce to 0xd4 are read by the reader `0xe515f0` itself (jump
table `0x3c6a90c`):

| id | body |
|---|---|
| 0xce | none: the end of the queue |
| 0xcf, 0xd2 | a group: a u8 byte count, then that many bytes |
| 0xd0 | a u8 count, at most 4, then that many bytes |
| 0xd1 | two bytes |
| 0xd3 | one byte |
| 0xd4 | none |

Format bytes and their argument widths in bits:

| format | widths | format | widths |
|---|---|---|---|
| 0x00 | none | 0x57 | 32, 8, 8, 8, 8, 8, 8 |
| 0x01 | 8 | 0x62 | 32, 16 |
| 0x02 | 8, 8 | 0x63 | 8, 8, 32 |
| 0x04 | 5, 3, 8, 16 | 0x65 | 32, 16, 16, 16, 16 |
| 0x10, 0x20 | 32, 16, then eight of 32 | 0x66 | 8, then five of 32 |
| 0x11 | 16 | 0x67 | 32, then six of 16 |
| 0x12 | 8, 16 | 0x72 | 32, 32 |
| 0x14 | 5, 3, 5, 3 | 0x75 | 32, 8, 32, 32, 32 |
| 0x17 | seven of 16 | 0x83 | 32, 32, 32 |
| 0x1a | ten of 16 | 0x84 | 8, 32, 32, 32 |
| 0x21 | 32 | 0x85 | 8, 8, 32, 32, 32 |
| 0x22 | 8, 32 | 0x86 | six of 8 |
| 0x23 | 5, 5, 5, after one pad bit | 0x93 | 32, 8, 8 |
| 0x28 | eight of 32 | 0x96 | six of 32 |
| 0x29 | 32, then eight of 8 | 0xa3 | 32, 8, 16 |
| 0x42 | 5, 3 | 0xa4 | 32, 8, 8, 8 |
| 0x43 | 8, 8, 8 | 0xb3 | 32, 8, 32 |
| 0x45 | 16, 16, 16, 32, 16 | 0xc3 | 32, 32, 16 |
| 0x52 | 32, 8 | 0xc4 | 32, 32, 16, 16 |
| 0x53 | 8, 8, 16 | 0xd3 | 32, 16, 16 |
| | | 0xd4 | 32, 32, 16, 8 |

### The battle-start body

Message 0x11's body is a command queue with no length word ([The server command queue](#the-server-command-queue)).
Battler ids are 1 for slot 0, 2 for the boss (slot 1), 3 for slot 2, and 4 and 5 for slots 3 and 4; a
battler sits at position id − 1. The body sends each battler out in id order, then runs the switch-in
events, then ends with `0x2b (0)`:

| commands | what |
|---|---|
| `0x3d (pos)`, `0x16 (pos, 0, 0, 0)`, `0x5e (id, ability)`, `0x61 (id)`, `0x6b (id)`, `0x4e (id)` | one battler sent out; `ability` is its ability id |
| `0x25 (id)`, `0xc7 (id, 0)`, the effect, `0xc8 (id)` | an ability's activation |
| `0xcb (id, text, params..., 0xffff0000)`, padded with zeros to ten arguments | a battle message |

| switch-in event | effect |
|---|---|
| Pressure (46) | the activation around `0xcb (id, 162, id)` |
| Intimidate (22) | the activation around, per target, `0x0d (target, 1, 1)`, `0x93 (target, 1, 1, 0)`, `0xcb (id, 32, target, 1)` |
| Frisk (119) | the activation around `0xcb (0, 146, id, target, item)` per foe holding an item |
| Unnerve (127) | `0x25 (id)`, `0xc7 (id, 127)`, `0xca (id, 679, side, 0xffff0000)`, `0xc8 (id)`, before every other event; `side` is 1 for a player's Unnerve, 0 for the boss's |
| Anticipation (107) | the activation around `0xcb (id, 145, id)` when a foe knows a damaging move super effective on it or a one-hit KO move |
| Trace (36) | `0x25 (id)`, `0xc7 (id, A)`, `0x89 (id, 36, A)`, `0xcb (id, 128, S, A)`, `0x5f (id)`, `0x24 (id, A)`, `0x5e (id, A)`, `0xc8 (id)` twice, copying ability A from S: a player's Trace copies the boss, the boss's copies the player that `below(4)` picks among battlers 1, 3, 4 and 5 (6 of 6 battles) |
| Shields Down (197) | none for Minior in a Meteor form (forms 0 to 6) above half HP; a Core form (7 to 13) shows `0x25`, `0xc7`, `0x57 (id, form − 7, 0)`, `0xac (id)`, `0xca (id, 842)`, `0xc8` (9 of 9 battles) |
| Air Balloon (541) held | `0xcb (id, 137, id)`, after the battler's ability |

The events run in the battlers' speed order (party record speed), Unnerve first. Intimidate
affects each foe in id order. A foe with Own Tempo answers inside it with its own
`0x25`/`0xc7`, `0xcb (F, 69, F, 0xffff0000)` and `0xc8`, and loses nothing. A foe with Defiant answers
after its drop with `0x0c (F, 1, 2)`, `0x92 (F, 1, 2, 0)` and `0xcb (F, 18, F, 0xffff0000)`. Frisk
names the first foe that holds an item with `0xcb (0, 146, I, F, item, 0xffff0000)` and each later
one with `0xca (0, 752, F, item, 0xffff0000)`; with no item among the foes it has no event. Built this way, 420 of 554
oracle start bodies are equal and none differ.

### The server's messages

Every message the server sends is one step of `0x113bad8(server, kind, destination)`:

| step | code |
|---|---|
| the step counter `server+0x198` raised | |
| a body already received for that step ([[server+0x448]+0x38], `0xe63734`) is reused; otherwise the builder runs with that kind and the round counter `server+0x488` | `0x113c8a0` |
| the 32-byte header: u32 kind, u64 step +0x08, u64 round +0x10, the destination +0x18 (5 for every station), 5 at +0x19 | stack bytes +0x04..+0x07 and +0x1a..+0x1f are never written |
| the message object: 0x50 bytes from the server's allocator `[server+8]`, vtable `0x44ed338`, a buffer of header and body at +0x40, its length u32 at +0x48 | `0x1227714`, destructor `0x28015b4` |
| onto the link of each destination slot (dest 5: slots 0 to 4 and 0xff) when `server+0x490` is set: links by slot in the map at `server+0x1a0`, each link's outgoing deque at `[link+0x48]` | `0x113cd5c`, `0x113e17c`, `0x113d33c`, `0x113d4a0` |
| onto the server's log `[server+0x50]` and the sent entry of each seated destination slot, unless the log or entry holds that step already | `0x113c718`, `0x113c4cc` |
| writes {u8 `[[server+0x448]+0xc4a5]`, u64 step, u8 `+0xc4a4`} to x8: the round's result | |

A message deque is libc++ `deque<message*>`: map at +0x40, start +0x80, size +0x88, 0x200 pointers a
block (`0x113d5e0`, `0x113d810`, erase `0x131be1c`). The server keeps two entries per slot: what it sent
the slot (map at `server+0xc8`, `0xf6f324`) and what the slot sent it (map at `server+0x130`, `0xe634c8`).
`0xf6f0a8` finds a message by header type, `0xf6fd7c` erases it, `0xe63380` asks whether a slot sent a
message of a given step. A link's messages reach the wire as a battle-start frame addressed (0x2713, 1,
slot): u16 key 0x7b, u32 setup `+0x2c`, u32 1, u32 the slot, u32 the length, then the message. The code
that drains a link onto the network was not located.

### The boss's actions

The raid boss's extra actions wait in a list of four (u8 kind at +0x5c + 8i, u32 value at +0x60 + 8i,
count +0x7c), after a copy of the RaidPoint's action profile at +0x10. The round engine's list is
`[module+0x1b0]` (`0x16e5c90`), reset with every round; the server's per-frame machine keeps its own.

| kind | queued by | value |
|---|---|---|
| 1 | the shield (`0xf6f87c`): by time at or below profile +0x14 percent, or HP at or below +0x12, before it starts | `0xf70af0` of the timer by time, 0 by HP |
| 2 | the shield's end (`0xf6f87c`, `0xf70010` against +0x18) | 1 |
| 3 | `0xf6dd84` when a time check finds 10 percent or less left | 1 |
| 4 | the six extra actions (`0xf6fa5c`: kind, timing 1 time / 2 HP, threshold, move at +0x24 + 8i), each once (record +0x86 + i) | the action's index |
| 5 | the double action (`0xf6de7c`): HP at or below profile +0x54 | 0 |

A double action whose value is 0 fires when a hit leaves the boss standing at an HP share of 0 (2 of 2
oracle battles with an all-zero profile), between that move and the next. None of them draws a random number: every trigger is a threshold on the boss's HP share or the time
left (`0xf91070` on the battle timer). As request block actions (`0x114fb2c`) the word's kind is 12,
bits 4..11 the list's kind, bits 32..47 its value, and the actor the raid battler's id (`0x114fc70`).

During a round, an empty list is filled from the HP triggers (`0x11425b0`); without a shield among them
the actions run in that round (`0x1145be0`). After a round, the result's byte `0xc4a5` picks the next step; ServerCommand
(`0x16e4f6c`) passes 8 instead when the builder's `0xc4a4` is set, a raid action passes the byte as it is (`0x16e4ff0`, jump table `0x3c61c38`): 0 none, 4 an empty round
(`0x16e5cac`), 6 the round's list when it holds a shield (`0x16e5ad0`), 7 the battle's end
([The battle's end](#the-battles-end)). A raid action (`0x18c92a8`, payload copied by `0x17b5f3c`) runs in four states:

| state | the server |
|---|---|
| 0 | sends message 0x47 to every station; pauses the battle timer for reason 0 (`0x18c9a68`) |
| 1 | waits until every seated slot sent a message of that step (`0xe63380`) |
| 2 | a request block whose slot 1 holds the actions (count byte +0x231); the battle timer resumed for reason 0 (`0xe63ac4`); the block sent as a round (0x15) |
| 3 | the round's result's next step, the list cleared (`0xfaf024`), each slot's 0x47 and its answer 0x48 erased |

A list without a shield starts at state 2. The per-frame machine checks the profile's time triggers on a
copy of the list while the boss's list is empty (`0xf6d62c`); when one fires it sends the copy as message
0x51 (`0xf71b74`). The 0x51 comes back to the machine through the server's own slot and fills its list ([The
server's flow](#the-servers-flow)); a machine list holding actions posts a raid action (`0xf6d8d4`).

A raid action's round queue, over the 547 such rounds of the oracle corpora: `0xb5 (0)`, `0x51 (2, 1)`,
`0x85 (kind, x)`, `0xc1 (kind, y)`, the action's effect, `0xb2 (0)`, `0x37 (2, 7, 1)` (twice after a move
or a stat reset), `0xc5 (1)`, `0x43`, `0x23 (2)` and `0x2d (0)`. For an extra action `x` is its index (213 of 213)
and `y` the profile action's kind (1 to 4); kind 3 has `x` and `y` 0 and no effect commands (121
rounds); a shield start has both equal to its value (95 with value 0, the rest the timer's). An extra action that
resets the players' stat changes ends its effect with `0xc2 (60, 2, 0)`, after `0x10 (b)` and `0x13 (b,
16, 0, w, 2)` for each player it clears; one that resets the boss's ends with `0x0f (2)`, `0xc2 (3, 2,
2)`.

### Raid actions in the action list

A queued raid action becomes an action entry of kind 11 (word kind 12; its kind at +0x28, its value at
+0x2c). Entries are ordered by the round's action sort ([Speed ties](#speed-ties)) on the key `0x113ecdc`
builds: class in bits 22..24 (4 for kind 11, 2 for kind 13, 1 for a move), the move's priority plus 7 in
bits 16..21, 1 (0 for Stall) in bits 13..15 and Speed in bits 0..12. The boss's raid entries all share
one key, so every comparison between two of them draws `below(2)`. The oracle's sort and run log:

| entry run | what the queue gets | what joins the list |
|---|---|---|
| shield (kind 1) | `0x85 (1, v)`, `0xc1 (1, v)`; `0x14 (2)` and `0x90 (2, 0)` when it cures the boss's status | |
| shield end (kind 2) | `0x85 (2, 1)`, `0xc1 (2, 1)` | |
| time left (kind 3) | `0x85 (3, 0)`, `0xc1 (3, 0)` | |
| extra action i (kind 4) | `0x85 (4, i)`, `0xc1 (4, action)`; nothing at all when action i already ran | action 1 or 2: a kind-13 entry (class 2); action 3: a move entry (class 1) for the profile's move |
| double action (kind 5) | `0x85 (5, 0)`, `0xc1 (5, 0)` | |
| kind 13 after action 1 | `0x0f (2)`, `0xc2 (3, 2, 2)` | |
| kind 13 after action 2 | `0x10 (b)` for each standing player in id order, `0x13 (b, 16, 0, b << 26 \| 12, 2)` for each of them whose ability can be suppressed, `0xc2 (60, 2, 0)` | |
| the extra action's move | the boss's move run between `0xc1 (9, 0)` and `0xc1 (9, 1)` (before the move's `0x1e (2, 0)`) | |

Action 2 clears the players' stat changes and gives condition 16 (ability suppressed): `0x13` skipped
an Arceus with Multitype (Showdown flag `cantsuppress`). Action 4 (drain the Tera orb) adds `0x76 (2, k)`
for some client slots and no entry. A Sandstorm or Snowscape extra move aims at position 10, Iron Defense
at the boss (4); a move aimed at one player draws its target with `below(n)` over the standing players in
position order when its entry joins the list (before the next sort's draws); one aimed at all of them
(Snarl, Leer) carries position 10.

After every action run (`0x11405a0`), while the battle goes on and the boss stands, `0x11425b0` fills an
empty list of waiting raid actions from the HP triggers: without a shield among them they join the
round's action list; with one they wait for a raid action round. The list empties at each round's start,
and running a shield empties it too, so the next run refills it with every HP trigger still met, actions
already in the list included: those run again later and show nothing. A raid action round leaves its
list as it stands: a shield refilled there behind the one that ran waits for the next raid action round,
where it shows nothing. While the boss is frozen its HP
triggers leave out an extra action of kind 3 (a move) and keep the others: a boss reset fires and runs
while it stays frozen, the move action comes in after the boss thaws. A move action skipped while the
boss's status blocks it can come in after the shield cures that status. The extra action's move checks
the boss's confusion before it runs, as a commanded move does. While the shield is up, a hit on
the boss does damage times the shield's percent (`0x2a`, 20 in standard profiles; 80 or 40 for a
Terastallized attacker's own-type or other move), over 100, rounded up from a remainder of 50
(`0x1535c8c`). The shield ends once the boss has lost the profile's end percent (20) of its HP pool
since it went up.

The round end puts one `0x37 (b, 7, 1)` per entry of the list, run or not, in the list's last order: 7
for a shield, an extra boss reset and an extra move whose three entries were queued again by the
shield. `0x75 (3, n)` counts only rounds with a player's entry, and a raid action round still counts in
`0x7b (M, n, A)`. A raid action round otherwise ends as a command round: three battler sorts, `0x43` in
the second one's order and `0x23 (2)`.

### The battle timer

The battle timer is a 0x28-byte object at the server context's +0x38 (the per-frame machine's and every
job's `[+0x40]`, which also holds N at +8, the server's module at +0x10 and the server at +0x18):

| offset | field |
|---|---|
| +0x00 | u64 start, ns of `nn::os::GetSystemTick`; 0 while paused |
| +0x08 | u64 ns accumulated before the last pause |
| +0x10 | u64 the last pause's time |
| +0x18 | u8 started |
| +0x19, +0x1a | u8 pause reasons; the timer runs while both are 0 |
| +0x20 | the limit it was made with |

| event | code |
|---|---|
| made, started and at once paused for reason 0, with the battle's first job when the limit N+0x8a is not 0 | `0xf70864`, `0xf70a58` |
| resumed for reason 0 when Wild::Setup ends (a timer never started starts there) | `0x2a1fbfc`, the steps of `0xe63a6c` |
| paused for reason 0 from a raid action's message 0x47 until its round | `0x18c9a68`, `0xe63ac4` |
| read: the limit plus the i16 at `[[module+0x1b0]+8]`, minus the whole seconds run since the start and the whole seconds accumulated; while paused, the limit minus the accumulated seconds; 1 for a zero limit | `0xf91070` |

The per-frame machine checks the time triggers only once the timer has started (+0x18) and with setup
+0x499 bit 2 set (`0xf6d538`). A trigger at P percent of the time fires when 100 x time left / limit, in
integer division, is P or less: on a 300 s timer the 80 percent trigger fires with 242 s left, after 58 s
of running time. In the served battle below the timer started when the last station's answer to message
0x11 reached the server, and the 80 percent action went out 58.1 s later.

### The battle's end

After a round whose result byte is 7 (`0x16e4ff0`), the server runs:

| step | code |
|---|---|
| asks the source whether a Pokemon joins; a raid's source (vtable `0x4492e58`) answers 0 | `0x16e56a0`, `0x2a0fb40` |
| the result judged into N+0x90 (u32) and N+0x94 (u8) | `0x16e5120`, `0xe7d58c`, `0xe7d570` |
| the 0x29 body at server+0x208: u16 N's slot, u16 the outcome, u8 N+0x94 | `0xe7d4c8`, `0x166882c` |
| AddExpBattleEnd: message 0x25 (an empty round), every answer awaited | `0x18826d8` |
| the exit message by setup kind +0x30: kind 0 0x29 for outcome 1, 0x2b for 0 or 2, 0x2d for 6; kind 1 0x31, 2 0x33, 3 0x2f | `0x1882b14` |
| ExitBattleEnd: that message, every answer awaited | `0x20185ac` |
| with setup +0x498 bit 0x400 and 0x29, RaidCapture: message 0x49 | `0x186d680`, `0x1934808` |
| ExitFadeOut: message 0x35, then 0x37, every answer awaited | vtable `0x4493dd8`, `0x171d648`, `0x171d8b0` |

Nothing in the server's jobs ends the battle after 0x37. Result byte 8 belongs to battles a Pokemon
joins (written only via message 0x1d, which a raid never sends). The judge `0xe7d58c` counts each
side's able members (side by battle mode, table `0x3c6a450`); the first deciding test gives the winner:

| test | code | N+0x94 |
|---|---|---|
| with setup +0x49c bit 1: side 1 while it has an able member, else side 0 | | 0 or 1 |
| a side with no able member loses | `0xe7d748` | 1 |
| with N+0x8c and no setup +0x710: the side with fewer empty slots | `0xe7e520` | 2 |
| setup kinds 2 and 3, no able member either side: the rule value | `0xe7d738`, `0xe7ecd8` | 1 |
| fewer members lost, larger HP share, larger HP | `0xe7f160`, `0x282361c`, `0x28239ac`, `0x2823a5c` | 2 |

The result is 1 when N's side wins, 0 when it loses, 2 undecided. A won raid sends 0x25, 0x29 with
body `00 00 01 00 01 00` and 0x49, each once every station answered the one before.

### The battle timer running out

At the top of each frame the per-frame machine (`0xf6d538`) reads the battle timer (`0xf91070`); a
result of 0 or less takes the time-up branch `0xf6d830`:

| step | code |
|---|---|
| result 0 with N+0x94 = 2 kept in N, unless a result is already there | `0xe7d570(N, 0, 2, 0)` |
| the 0x29 body at server+0x208: N's slot, the outcome (`0x166882c`), N+0x94 | `0xe7d4c8` |
| a raid (setup +0x499 bit 2): ExitBattleEnd with message 0x2b | `0x201602c` (hash `0x2da7b4584624a364`, constructor `0x1882dbc`) |
| otherwise: AddExpBattleEnd with kind 0 | `0x16e5230` (hash `0x23607a0597b3a656`) |

The machine runs only while no job runs, so a timer that runs out during a round is seen once the
job ends. A raid time-up sends no 0x25: the boss's last timed round, then 0x2b with body `00 00 00 00
02 00`, 0x35 and 0x37 ([The battle's end](#the-battles-end)). A raid the boss wins ends the same way:
each faint of the host's or the console's Pokemon (not an NPC partner's) takes n seconds off the timer
(the i16 at `[[module+0x1b0]+8]`, `0x287f3d4`): n is the time limit times 0.125 times the mean level of
the four players over the boss's level, in float32, truncated (339 of 339 oracle battles; 28 to 61 s
on a 300 s timer), and the knockout's queue carries `0x81 (-n)`.

A slot whose Pokemon fainted goes through its reader's sub-states:

| message | to | what |
|---|---|---|
| 0x21 | the fainted slot, header only | once the slot has no able member; its answer 0x22 starts the reader's timer (reader+0x50) for 5, 10, 15, 20, 25 or 30 s by how many times the slot's Pokemon fainted (`0x1ffe4e8`, table `0x3c69d1c`) |
| 0x23 | every slot, 20608 bytes | once that timer runs out (`0x2016bc8`, a kind 0x23 block of the slot's one action, kind 8), built by kind 35 (`0x1153350`): HP restored (`0x288cde8`), command 3 (battler, HP), the member sent back in (`0x2887044`, `0x11482a0`: command 0x98) |

A revive's queue: `0x03 (b, HP)` with its full HP, `0xcb (0, 1, b)`, then the battle start's send-out
with the client slot c (`0x3d (c)`, `0x16 (c, 0, 0, n)` with n the rounds so far, `0x5e (b, ability)`,
`0x61`, `0x6b`, `0x4e`), `0x98 (c, 0, 0, 1)`, `0x20 (b, 18)` and its switch-in ability (Pressure's
message 162). Its stat changes are gone. The next round's `0x23` list starts with the battlers revived
since the round before, in revive order, then that round's actors not already listed.

A player's Pokemon knocked out runs, after the hit's `0x42`, the boss's knockout commands with its own
id ([A move in the round queue](#a-move-in-the-round-queue)): `0x49 (V, A, M)`, `0x09 (A, slot)`, `0x37
(V, 1, 1)`, `0xcb (V, 0, V)`, `0x94 (V, 0)`, `0x37 (V, 8, 1)` (its faint count), `0x5f`, `0x62`, `0x6c`, `0x5d`,
`0x41 (b, V)` for each battler still standing in id order, `0x33 (V, k)` for k 0 to 13 (8 only while a
terrain is up), `0x29
(V)`, the timer's `0x81 (-n)` for the host's or the console's Pokemon, and `0x38 (A)`; no `0x80`. Its
actions in the round are marked run, the hit draws `chance(0)` like the boss's knockout, a stat-drop
secondary draws nothing, a flinch or confusion secondary and a contact ability still draw.

When the boss's shield ends with value 1, its record sets the five per-slot counters (u16 at record
`+0x7c`) to -1 (`0x15661e0` event 2). At each round's start (`0x114d390`), a boss move aimed at a slot
whose counter is negative is dropped with the boss's other actions, the counter reset (event 6) and `0x85
(6, slot)` queued after the round start's `0x51` run: each player's next turn goes unanswered (271 such
rounds in the oracle corpora).

### The server's flow

On the console the steps are jobs: Wild::Setup, ServerRequest (`0x138d178`, message 5 to one slot),
ServerCommand (`0x16e4f10`, a posted request block as a round), RaidAction and the battle's end.
Wild::Setup (`0x2a1f54c`, jump table `0x3c61c1e`) sends message 1, waits for every answer, sends 0x11,
waits, clears what each slot sent (`0xe0f5f8`), sends message 3 only when the start flag
[[o+0x40]+0x28] is 1 (set only by `0x2840fac`; a raid leaves it 0), and starts the battle timer. A
raid's setup +0x30 is kind 0. The per-frame machine (`0xf6d538`) steps five per-slot readers
(`0xf6df44`) and the boss's list:

| reader state | when | then |
|---|---|---|
| 0 | the slot's sent entry holds none of 5, 0xd, 0xb, 0xf, 9, 7, 0x21, 3, 0x23, 0x15, 0x17, 0x19, 0x13, 0x47, 0x1f, 0x1d | a ServerRequest for the slot (`0xf70078`), state 1 |
| 0 | otherwise | each answered pair erased (`0xf6edf4`) |
| 1 | the slot was sent 5 and sent 6 | a block with the slot's command (`0xf6e6a8`, `0xf702ec`) posted as a ServerCommand, state 2 |
| 2 | the slot answered a round (0x15 / 0x16) | state 0 |

The server keeps, per slot, the messages it sent and the messages the slot sent in arrival order;
`0xf6edf4` erases the first sent message of a type and the first received answer, one pair per call, and
state 0 calls it once for each of the pairs (0x15, 0x16), (0x23, 0x24), (0x11, 0x12), (0x13, 0x14), (0x17,
0x18), (0x19, 0x1a), (0x1b, 0x1c), (0x1d, 0x1e), (0x25, 0x26) and (0x1f, 0x20) a frame. A slot whose
reader was held while rounds went out (a fainted slot) therefore erases its backlog one round a frame
before it is asked again: 12 frames after a revive for 12 rounds. Wild::Setup's end clears both lists.

The boss's slot (table `0x3c6a45a` against N+0x95) only erases answered pairs. Other reader paths: a
slot that sent 4 gets a kind 0x13 block; on N's side in a raid the sub-states at reader+9 handle a
fainted slot ([The battle timer running out](#the-battle-timer-running-out)); 0xd/0xe posts kind
0x1b; 7/8, 0xb/0xc, 0xf/0x10 and a received 0xa post kinds 0x17, 0x19, 0x15 and 0x17.

Every frame the run step `0x2d383b8(N)` steps the server's incoming links (`0xe0f040`, `0xe0fd68`,
`0xe0f854` on [N+0xb0]) and then the job graph `0xfc363c(G, 1)`, G = [N+0xa8] (vtable `0x44ee6e8`):

| G+ | object | |
|---|---|---|
| 0x98 | the request factory | a posted request is a 0x50-byte object: job type hash, counter, payload |
| 0xa0 | the scheduler (vtable `0x44eea68`) | posted requests at +0x40..+0x50, appended by `0x1479b10` |
| 0xa8 | the source (vtable `0x44947d8`) | vf 0x68 `0x14641ec` picks the request to start |
| 0xb0 | the per-frame machine (vtable `0x4493530`) | vf 0x68 `0xf6d538` |
| 0xb8 | the executor (vtable `0x4493688`) | a stack of jobs |

`0xfc363c(G, 1)` runs the executor alone while it holds a job. Otherwise it runs the machine, then
the source's pick: in a raid the first posted raid action (hash `0x5c307d44ea569b63`), before the
module starts the first Wild::Setup (hash `0x2e9e7a3009002c36`), otherwise the first posted. The
executor (`0xfc38dc`) runs the top job's vf 0x68: 0 ends the frame; 2 pops it, pushes its
continuation [job+0x70] and ends the frame; anything else runs it again. One posted request starts per
frame, and a raid action jumps the queue.

The machine's timed check sends its copy of the boss list as message 0x51 into the server's own
incoming link (`0xe0f440(server, N+0x95)`); next frame `0x2016290` copies its 0x24 bytes to the
machine's boss list, which posts the raid action. Without that step the timed action never fires.
The machine's vf 0x70 `0x20162bc` also takes `0x0ab4bce035f3012b` (posted to `0x201665c`) and
`0xde3856ecc4fe200c` (one kind-14 action, posted as a ServerCommand).

On a frame with no job the machine (`0xf6d538`) reads the battle timer first, and a time left of 0 or
less posts the time-up; then, while armed (`+0x118`, cleared when a 0x51 goes out and set again when a raid
action is posted), it ends the frame if its boss list holds actions, or evaluates the time triggers on a
copy and, when one fires, sends the 0x51 and ends the frame; a boss list holding actions is posted as a
raid action and the frame ends; only then are the readers stepped. A round whose boss list holds a shield
first posts the raid action itself (`0x16e5ad0`); a raid action jumps the posted queue. Over the 794
oracle battles of the corpora, a server built this way sends every message the oracle sends at the same
server time up to the first round it refuses (31,581 messages; 25 battles through a faint, 8 through a
revive, 5 through a shield's 0x47).

The machine's clock is the 19.2 MHz system tick: each frame moves it to the frame's time if that is
later, and every `nn::os::GetSystemTick` read adds 256 ticks. A frame run again at the same time (a host
starts each run of frames at the time the last one ended) therefore reads slightly later, and a timer
that ends on a whole second (a fainted slot's 5 s wait) can end on either instance; over the corpora
that moves a revive by one frame in 10 battles.

`Server`, a Python port of this flow, runs at 30 frames a second on the machine's clock; no frame
can be skipped, since a reader waiting on a fainted slot's timer moves the machine every frame. The
host relays every message its server reads to the guest in one queue, so that queue's order is the
order the server read them in. From an emulated host's bootstrap and the relayed messages, the port
sends all 24 of the console's frames byte for byte outside unwritten bytes, and under unicorn the
game's own code for all 216 ported functions leaves the same pages, including time-up and a boss win.

### Reproducing a round

A round replays exactly under unicorn from an emulated console halted at the builder `0x113c8a0`
with type 0x15: memory is fetched from the GDB stub one page at a time, the thread-local page behind
`tpidrro_el0` is a stand-in whose `+0x1f8` names a fake thread, and SVCs 0x10, 0x11, 0x12, 0x1a,
0x1b, 0x1d and 0x1e return 0. A round touches 159 to 353 pages.

A Python port of the server runs one function per game function, keyed by its offset from main: the
builder for kinds 1, 5, 17 and 21, the round driver `0x113e3d0` (damage `0xf7c344`, fainting
`0x1144df8`, end of turn `0x114a094`), the battle start `0x113dca8`, the build steps `0x2891748`,
`0x2892ac0`, `0x2d381a4` and `0x2892dd4`, and the SDK's `nn::mem::StandardAllocator` with its thread
cache and TinyMT32 key (`0x525f448`). Over 86 halted consoles it leaves the same body and memory
pages as the game. `__cxa_guard_acquire` (`0x53c49a0`) returns 1 and sets byte 1 of the guard to 2
when neither byte 0 nor byte 1 is set.

The data tables are romfs files held by function-local statics:

| static | file | object |
|---|---|---|
| `0x47420b8` | `avalon/data/personal_array.bin` | map, key species * 10000 + form (u32) |
| `0x47420d8` | `avalon/data/growTable.bin` | the FlatBuffers root, through vf +0x70 of [T+0x30] |
| `0x4742568` | `avalon/data/waza_array.bin` | map, key move (u16) |
| `0x4742548` | `avalon/data/tokusei_array.bin` | map, key ability (u16) |
| `0x4734e50` | `world/data/battle/battle_item_conversion/battle_item_conversion_array.bin` | array |

A map is a libc++ `unordered_map` at +0x68: buckets +0x68, bucket count +0x70 (the next prime at
or above the record count), first node +0x98, size +0xc0, load factor +0xc8 (1.0), default record
+0xd0. A node is {next, hash = key, key, record pointer}; +0x30 is the file resource (FNV hash
+0x48, path +0x50). The item array (filled by `0x1821674`) holds 0x18-byte entries from +0x28: u32
index, u32 0, u64 hash (main `0x3c61260 + 8 * index`), u16 item, 6 zero bytes. The files come out of
`arc/data.trpfs` (`tools/switch/trpfs_read.py`; Oodle through the game's `OodleLZ_Decompress`
`0xcc8750`). The data system's init `0x1641afc` runs `0x1643a48` (personal, growth), `0x1641cf0`
(moves) and `0x1641d78` (abilities); each table is reset into its static (`0x1643e68`) and appended
through `0xf0ba9c` to the registry at `0x4763a18`. Inserting a file's records in file order, after
reserving their count, gives the console's node list.

From the static image and the romfs alone the port also builds the game heap (the "Application"
allocator `0x3b78d3d`, limit 0xa0000000, over GlobalHeap `0x4763918`), the weak-handle table
(`0x165dd08`) and the session, and its battle-start bodies and later rounds equal the console's
outside the request block's unwritten stack bytes. A changed battle seed leaves the start body
unchanged and changes 123 bytes of a round; heap addresses and weak-handle ids reach no body.

| step | code | what it makes |
|---|---|---|
| boot | `0x168ca58` -> `0x168cb20`, constructor `0x168cc48` | the session manager `[[0x46d38e0]]` (0xc0 bytes, vtable 0x4483f68): sessions by id at +0x28, next id u32 +0xb0, at +0xb8 the communication holder of a 0x7660-byte object (vtable 0x4492468, constructor `0x168d59c`, port 0x7b) |
| raid start | `0x159dba0` -> `0x159dc10`, constructor `0x159e860` | the session S (0x110 bytes, vtable 0x4484008): job +0x40, battle setup (0x730 bytes, vtable 0x44ff070, constructor `0x159f8f0`, reset `0x159fe68`) at +0xe0 |
| raid start | the setup's Lua bindings, setters `0x7fa0cc`..`0x7faf24` | the setup's battle fields |
| battle start | `0x1891274(id)` -> `0x1891440` -> `0x18915c4(S, mgr + 0xb8, ...)` | N+0x48 (vtable 0x44fef38), the named-parameter table at +0x148, the election object (vtable 0x4492a48) at +0x108, then N (`0x16af068`, constructor `0x16b0fb8`) in S+0x48 |

### The server's flow, measured

These hold for an oracle server over the scripted console of [Serving the battle](#serving-the-battle),
and a server built from them sends the console the same frames, notices included, over nine whole
battles that the players won:

| rule | measured |
|---|---|
| header counters | `step` rises by one per send, a broadcast or one request; `round` is 0 for message 1, 1 from 0x11, and rises with each 0x15 and with 0x25 |
| one job a frame | message 1 starts Wild::Setup, which sends 0x11 once every slot answered 1, and ends one frame after every slot answered 0x11 |
| requests | on a frame with no job running, a slot with nothing unanswered is posted a request (5); requests start one a frame, in slot order 0, 2, 3, 4 |
| a command | the slot's 6 is posted as a job that sends the round (0x15) to every slot |
| asked again | a slot that has answered every round sent to it is asked again on the next frame |
| a win | the round that wins is followed, on the next frame, by an empty round 0x25 (20576 zero bytes), then 0x29 with the body `00 00 01 00 01 00`, 0x49, 0x35 and 0x37, each sent once every slot answered the one before: 2 frames after the last answer to 0x25 and to 0x49, on the same frame after the others |
| a time-up | 0x2b with the body `00 00 00 00 02 00` (63 of 233 battles) |
| the notice 0x46 | one for each frame on which a job starts, or on which, with no job running, a round's answer (0x16) is read |

### Serving the battle

`bin/sv_host.py --raid-serve [NAME]` keeps the network through the battle and serves it from the
host's station with `pokeldn.sv.raid_battle.RaidBattle`: a plugin's battle server ([A battle
server](plugins.md#a-battle-server)) built from the bootstrap and two NPC partners, and the stations a
console host keeps for itself. pokeldn ships no battle server; without a plugin that adds one, the flag
is refused. The served session seats our Pokemon, the boss, one console at station index 1 (bootstrap
participant 1, slot 2) and two NPC partners, so the flag takes one console.

| part | what the host sends |
|---|---|
| the server's messages to the console | frames addressed (0x2713, 1, 2) |
| slots 0, 1, 3 and 4 | each odd step answered with type + 1 after 0.05 s; a request (5) for slots 0, 3 and 4 with a type-6 command in which the slot's Pokemon uses its first move on the boss and the boss its first move on that Pokemon ([Actions](#actions)) |
| every message the server reads, the console's own included | relayed to the console, addressed (0x2713, 3, 5) |
| each server frame that moved the battle | after that frame's messages, a notice 0x46 from slot 0 (step 0, a 4-byte zero body), addressed (0x2713, 3, 5) |

Each frame goes on 0x80 port 0 as one deflated reliable message (flags `COMPLETE_ZLIB`); the largest
seen deflated to 903 bytes. A server that reproduces Scarlet 4.0.0's sends, as its first six frames,
the six battle-start messages a retail host sent (`raid.HANDOFF`) outside the header bytes its stack
filled, in the same order, so `--raid-serve` sends them in place of `HANDOFF`.

The host stops serving once the console answered 0x37, or 5 s after 0x37 was sent, and closes the
network. Answering 0x37 itself re-runs the time-up on the server ([The server's flow](#the-servers-flow)),
so the local stations leave it unanswered. A failure (the server raising, or failing to build) stops
the serving and hands the network over as a host without the flag does; the console then fails over
and fights its own battle ([Which station runs the server](#which-station-runs-the-server)).

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

## Unresolved

- What the `chance(0)` draws before some stat-drop secondaries stand for, when the target is not
  knocked out.
- Which of the fourth and fifth turn-end speed sorts orders the residuals (`0x19`) and the
  sandstorm, what the second action sort and the other turn-end sorts order, and whether the round
  that knocks the boss out runs the three round-end sorts ([Speed ties](#speed-ties)).
- Why a player's Whirlpool (a move that registers a handler and traps) hit a Fairy-Tera boss for 7
  where the damage formula gives 14 to 17.
- Whether a listener of the GlueCode dispatcher `0x18beef4` reads `+0x4c` as a word (listeners
  register at run time; groups 1 to 3 are called at `0x18bf87c`), and which consumer drains the
  per-slot queues `0xe106a4` fills (`0x113d5e0` from `0xe107ac`). Message 16, with +0x08 zero,
  enters neither queue: the reader switches on it and `0xf5bc10` returns at `0xf5bc30`.
- Which item message 16 releases on a guest. On the server the source `0xfc363c` steps (G+0xa8, the
  same object as N+0x48's +0x128, which `0x18915c4` fills through `0xfa493c` with the object
  `0x1849e10` makes) picks the next posted request from the scheduler at its +0x48
  ([The server's flow](#the-servers-flow)).
- Whether the battle timer a guest runs on a six-star point is the point's `gameLimit` 450; the
  reward-screen check did not measure it.
- What the RaidPoint's byte 0x3b4 holds.
- The code that drains a server link's deque (`[link+0x48]`) onto the network.
- What ends a raid battle after message 0x37. The run step `0x2d383b8` returns 1 (the battle over) when
  N+0x9e bits 0 and 1 are both set, when every seated client's step (the objects at N+0xb8..N+0xd8,
  `0xf59e54`, through the pointer to member at +0xd0) has answered 1 (bytes N+0x78..N+0x7c), or when
  N+0xa0 is set; N's constructor zeroes N+0xa0 (`0x16b1058`) and no code was found to set it. Bit 1 of
  N+0x9e is set only by N's outer sequence `0x1269824`; bit 0, on the raid path, when the election object
  [N+0x138] answers yes from vf 0x68 (`0x2a1d428`: its +0xca, set only by its vf 0x70 `0x2a1d920`), which
  also marks every client finished (`0x2893238`). No server job sets any of them; the clients read their
  own incoming links ([client+0x60]), which the unlocated code above would fill.
- Whether a retail console's reward screen follows the Lua filter for subjects 2 to 4; subjects 1
  and 5 are measured on a retail guest, the rest on an emulated one.
- Whether the five-star catch-once records go in the save's list as the seven-star ones do.
- Why a retail Violet that associated to the next host's network sent no Pia for 46 s, with the handover
  of an earlier host (is-migrating 0x11 to both at once).

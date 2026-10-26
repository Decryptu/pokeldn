---
title: Union Circle
parent: Scarlet and Violet
nav_order: 2
---

# Union Circle

A Union Circle is a Scarlet/Violet session of up to four players who share the field. Its code calls
it the team circle (`TeamCircle`), and a Blueberry Quest (BBQ) is a `bbmission`. pokeldn joins a
console's local Union Circle as a guest, reports BBQ clears that pay the host BP and release
Snacksworth's legendaries, and spawns wild Pokemon around the host's player
([Overworld encounters](#overworld-encounters)). The app's two Union Circle tools are in
[the app guide](gui.md#union-circle).

The Lua below is chunk `be21e65463b9a98f` of Scarlet 4.0.0 (`main.blua`, SHA-256
`c1a4f4e2625912cf0b739a642a79ba3357df0557a544b92da22a6cb139de2815`, the chunk of
[Tera Raids](sv_raid.md)) unless it says `main_dynamic`. A `0.N` is prototype N of the chunk's main
function, counted from 0. The prototype numbers are the same in the public 3.0.1 decompilation
(Martmists-GH/SV-Script-RE). Names in angle brackets come from its hash list; the others are still
hashes.

## Getting the Lua

The chunk is `script/lua/bin/release/main/main.blua` in `arc/data.trpfs`, stored with Oodle. The
4.0.0 update's virtual RomFS needs the base game's: part of `arc/data.trpfd` sits in the base.

    ./.venv/bin/python tools/switch/nso_read.py main main.bin
    ./.venv/bin/python tools/switch/trpfs_read.py --update UPDATE.nsp --base BASE.nsp --keys prod.keys \
        --image main.bin --extract script/lua/bin/release/main/main.blua --out-dir OUT

`--image` runs `main`'s `OodleLZ_Decompress` (`0xcc8750`). The chunk is Lua 5.4 bytecode with
30,829 top-level prototypes; `main_dynamic` (`script/lua/bin/release/main_dynamic/main_dynamic.blua`)
holds the event scripts and is extracted the same way.

## The team circle's messages

`TeamCircleNetReceiver` (`CF1D074B6B410BDB8`) dispatches on the message id (`0.15862`):

| id | handled by | what |
|---|---|---|
| 100 to 104, 106 to 109, 111 | `TeamCircleUI` (`C93F9A3AD3A3226ED`) | the circle's menus and member state; 103 goes to the UI only when its first field is 1 or 2 |
| 105 | the receiver | clock and weather: `gameTime`, `realTime`, elapsed real and game seconds into the game-time manager, then a weather seed and its lottery (pairs of {type, duration}, current and next) into `WeatherManager.Sync` |
| 110 | the receiver (`0.15872`) | a member's current field, kept per station index in `SDD109BA7EC57B7E8` |
| 112, 113, 114 | `CBB172410B8487694` | synchro Pokemon |
| 115 | the receiver | a per-station value kept in `S79D9A18B272E7093` when its inner flag is 1 |
| 700 | `CA854ADB0543ACD17` | |

A station sends 110 (`0.15863`) with its new field on every map change
(`main.event.general.system.map_change.MapChangeCore`). The BBQ code reads it back (below).

## BBQs

Quest progress is native, in the Lua module `c5137FC87`. Lua game events report into it through
`C00099C1DFBF96B11.S110BDDB84DEB4379` (`0.7064`), which passes (quest type, two values, count) to
`c5137FC87.f4246D9CA`; an evolution, for example, reports type 28 with a count of 1. The circle's
side of the quests is a second native module, `c4D400AC0`.

Every quest has a grade, the `mission_grade` of its `MissionInfo` row in the club data
(`arc/worlddataclubMissionDifficultyWeightAdvanced.bin.trpak`): 0 Normal, 1 Bonus, 2 Team.
Snacksworth calls Team quests group quests. A clear event carries its quest's grade.

The pack's quest table is a FlatBuffer of 64 `MissionInfo` structs: category (1 Battle, 2 Field,
3 Camera), `mission_type`, `mission_id`, goal, reward BP, reload BP (to swap the quest out), release
type, grade, difficulty (0 Beginner to 2 Advanced) and weight. A quest's id in every message is its
row's `mission_type`; `mission_id` tells apart the rows of one type, which differ in grade,
difficulty, goal or BP. The BBQ list finds a quest by the pair (`0x29de0f4`). A second table,
`MissionSettings`, gives a type's text per variation (a Pokemon type, a biome, a flavor), in
`club_bbmission`. The types the quest table uses:

| id | the quest | grades |
|---|---|---|
| 1 | defeat wild Pokemon with Auto Battle | Normal, Bonus |
| 2 | travel a distance | Normal |
| 3 | take a photo with friends all wearing the same kind of thing | Team |
| 5 | make a four-star sandwich with friends | Team |
| 6 | make a sandwich of one flavor | Bonus |
| 7 | make a sandwich with a number of ingredients | Bonus |
| 8 | wash a Pokemon | Bonus |
| 9 | surprise wild Pokemon from behind | Normal |
| 10 | hatch an Egg | Bonus |
| 11 | pick up items from the ground | Normal |
| 14 | catch the Pokemon the hints describe | Team |
| 15 | find Ditto blocks in a biome | Team |
| 21 | photograph a wild Pokemon of one type | Bonus |
| 22 | photograph a wild Pokemon in flight | Normal |
| 23 | photograph a swimming wild Pokemon | Normal |
| 25 | take a photo with friends in a biome | Team |
| 27 | win a Tera Raid Battle | Bonus |
| 29 | make a TM | Normal |
| 30 | battle a wild Tera Pokemon | Bonus |
| 31 | defeat a wild Pokemon after Terastallizing | Normal |
| 32 | catch Pokemon of one type | Normal |
| 33 | photograph a wild Pokemon in a biome | Normal |
| 34 | catch Pokemon | Normal |

Every Normal row pays 20 to 40 BP, every Bonus row 100 to 200, every Team row 400 to 600.

When the BBQ manager is created (`0.7062`), it hands getters to the native side. `c16FE4B25` gets
the player's own field (`f61488ABA`, the save's `currentFieldId`) and a member's field
(`f45B80F87`, the 110 value for a station index). `c5137FC87` gets whether the player is in the
field (`f01FF34BD`) and the two club level flags `FSYS_CLUB_BBMISSION_LVUP_01` and `_02`.

Each frame the manager's `PreUpdate` (`0.7069`) drains three native queues:

| queue | source | what the Lua does |
|---|---|---|
| `c5137FC87.fB8D11637` / `f35493666` | the player's own clears | hands each clear to `c4D400AC0.fAC449469` while `c4D400AC0.f5770F782` holds. A Bonus clear made in a circle (`c4D400AC0.f48603105`) goes to `c4D400AC0.f263D7D28` and `f07578A96` on the host (`c4D400AC0.fE8E53DDE`), and a guest credits nothing for it. Any other clear is queued for BP |
| `c4D400AC0.fD7C6549F` / `f37737462` | other members' clears | shows each as a notice; queues it for BP unless it is a Bonus clear |
| `c4D400AC0.fD961BFD2` / `f541C4B17` | BP grants from the circle | queues each grant for BP |

`0.7075` merges a queued event into one of the same grade and sums their BP (`fBCA6AEB8`). `0.7076`
adds the queued total to the currency manager, and `0.7077` shows the BP message. The manager's add
(`0.15120`) clamps the player's BP to 0 to 9,999,999 (`0.15128`), so one clear counts for at most
9,999,999 BP although its BP is an s32.

The Lua checks nothing: a member's Normal or Team clear pays the host straight from the second queue,
and a Bonus clear pays only through a grant the native circle module puts in the third.

## Native modules

The addresses below are in Scarlet 4.0.0's `main`.

Native module and function names are plain strings in `main`'s rodata; each module has a
`luaL_Reg`-style table of {name, function} pairs in `.data`: `c4D400AC0` at `0x442e500` (22
functions), `c5137FC87` at `0x4420630` (45). A clear event is userdata (methods at `0x441dc50`):
`fBCA6AEB8` returns the BP (s32 at `+0x10`), `f0C278E84` the grade (s8 at `+0xd`). `0x29dd878` builds
it from the quest's row: quest id (u16 at `+0x0`), the u32 at `+0x4`, the grade and the BP.

`c4D400AC0`'s functions work on one circle object, a lazily built singleton at `0x4739410`:

| function | does |
|---|---|
| `f5770F782` | whether the circle is ready (`0xa0d038`) |
| `f48603105`, `fE8E53DDE` | whether the player is in a circle, and whether they host it (`0xa0e9ac`) |
| `fAC449469` | sends the player's clear as message 3 (`0xa0db20`) |
| `f263D7D28` | on the host, sends a Bonus clear as message 5 (`0xa0dcf4`) |
| `f07578A96` | on the host, credits its own Bonus clear (`0xa0df34`, then the grant push `0xa0e164`) |

The circle sends these on its own channel (the object's `+0x70`): game key 0x0048 on 0x80 port 0,
the message type in the kind byte. Each is the clear event in the game's tagged format (`0xb9`, 18
fields, read by `0xa17694`), then the sender's message sequence (`+0xb8`). Message 3 also carries the
sender's BBQ status record (`0xa0f37c`, read by `0xa17170`). In the tagged format an integer from -64
to 127 is its own byte, a wider one goes behind a signed tag (0x84 to 0x86), a float behind 0x88.

The clear event's fields:

| field | value |
|---|---|
| 0 | quest id |
| 3, 11 | the quest's slot |
| 4 | grade |
| 5 | BP |
| 6 | a tuple of the sender's station id (u64, tag 0x83) |
| 7 | the quest's `MissionInfo` row |
| 12, 13 | the quest that takes the slot, and its row |

The other fields are zero or an empty row. A tenth of a second before a clear the host sends kind 2:
the quest, -1, -1, its progress (1.0), its sequence, and its status record.

### The BBQ status record

Each player's BBQ manager keeps its status record at its `+0x40`; the circle writes it (`0xa0f37c`)
into messages 1, 2 and 3. Message 1 (kind 1) is the sender's message sequence and the record alone.
A player sends one when the circle starts, step 1, then a bodiless kind 4 (`480004`), then step 2,
and the host sends another after each member's clear. The record is a tuple of 11:

| element | record offset | value |
|---|---|---|
| 0 | `+0x0` | 1 in every record: the manager's byte at `+0x40` |
| 1 to 3 | `+0x4`, `+0x50`, `+0x9c` | the player's three quest slots |
| 4 | `+0xe8` | a byte string of one byte, 1 in every record |
| 5, 6 | `+0xec`, `+0x138` | two further slots, empty in every record seen |
| 7 | `+0x184` | a signed byte, equal to element 9 in every record |
| 8 | `+0x185` | the player's Bonus clears toward the next grant |
| 9 | `+0x188` | the solo total (the manager's `+0x1c8`) |
| 10 | `+0x18c` | the Team total (the manager's `+0x1cc`) |

A slot (`0xa0fa18`) is 0x4c bytes, of which the record carries the quest id (u16, 0 when empty),
its progress (float), its text variant (the `MissionSettings` variation, 0 without one) and the row's
`mission_id`. A member whose host's fifth slot names another quest than its own takes the host's
(`0xa14290`).

`circle.bbq_record` reads the record that ends a message 1, 2 or 3.

A retail host's slots hold its quest types' Beginner Normal rows (`mission_id` 0: 20 BP, a goal of
10 defeats for quest 1 and 1 for the others), at progress 0 until a report finishes one; the further
slots stay empty and the Bonus count 0.

### A member's progress on the host's quests

A member finishes one of the host's quests by reporting progress on it with message 2 (kind 2, 0x80
port 0): the quest, two values (-1, -1 for a quest without a variant), the count, its message
sequence and its own status record. The host answers with its record showing the progress, then its
own message 3: the clear crediting the member's station id (field 6), the BP, the slot and the quest
taking it. Its solo total rises by one.

Message 2 carries what the Lua's progress report (`c5137FC87.f4246D9CA`) passes: the quest, its two
values and the count. The host's receive handler hands the four, with a member flag and the sender,
to the same native progress dispatcher (`0x29dc838`) its own reports reach (`0x29dc6b0`). So the
host counts a member's progress as its own, finishes the quest and clears it itself, and the clear
counts toward its solo total like any of its own.

`circle.progress_message` builds message 2. A Snacksworth run ([Joining](#joining)) sends each to
the next of the host's three slots as its latest record shows them, with a count of 500 (the largest
goal of a Normal row) and the slot's variant as the first value, -1 without one; a retail host clears
each.

## What the host does with a member's clear

The receive handler (`0xa13b00`) dispatches on the type through the jump table at `0x3c5b7a4`. For
a message 3 the host:

1. stores the member's Bonus count in that member's slot of its BBQ state;
2. looks the quest up in its own BBQ list (`0x29de0f4`, by quest id and the u32 at `+0x4`). Only a
   match to one of its own Bonus quests counts the clear toward the host's own tally, and only then
   does the host queue its own notice for it. Beyond a flag in step 4, the result decides nothing
   below;
3. queues the clear as a member's notice (the `fD7C6549F` queue);
4. if the clear is a Bonus, sets the event's `+0x7c` to min(3, the host's own Bonus count plus the
   three member slots) and its `+0x80` to whether step 2 matched, sends it to every member as
   message 5, and credits itself through the grant push with the event as received;
5. if the clear is a Team clear and the host's BBQ manager is active, adds 1 to the host's Team
   total (below).

Only after that does the host compare the message's sequence with the member's last one, and the
sequence gates only the member's status record.

A member that gets message 5 credits the event through the same grant push, unless its sequence is
older than the last one seen from the host.

The host pays out what the member's message names: nothing checks the BP at `+0x10` or whether the
quest exists. A Normal or Team clear is paid at once,
by the Lua. A Bonus clear goes through the grant push, the only ordering. It stages each event and
releases it into the grant queue (the object's `+0x108`) only when its `+0x7c` is one more than the
last released event's, or two less, or both are 0. That value is built from the slots, so a
member's next Bonus clear must report a count one past its last.

## Snacksworth

The BBQ manager keeps two running totals, read by `c5137FC87.f6ED7C9B6` (`+0x1c8`) and
`fECB0EBF0` (`+0x1cc`):

| total | goes up on | also read by |
|---|---|---|
| solo, `+0x1c8` | the player's own Normal or Bonus clear (`0x29dda40`) | the club's BBQ level-up events, at 15 and 45 |
| Team, `+0x1cc` | the player's own Team clear, and on the host each member's Team clear in message 3 (`0xa14918`) | |

Snacksworth is event `s2_sub_012`, and his 25 legendaries are events `s2_sub_013` to `s2_sub_037`,
each with its state in `WEVT_S2_SUB_0NN_STATE`. The event's class in `main_dynamic` (prototypes
`0.1995` to `0.2032`) reads the solo total through `0.2019` and the Team total through `0.2020`.
When the player talks to him, `0.2002` releases the next solo-route legendary once the solo total,
less `missionReleaseCount` for each one already released on a solo route, reaches
`missionReleaseCount`; `0.2003` does the same for the Team routes with the Team total and
`teamMissionReleaseCount`. Both counts come from the event's config table
(`s2_sub_012.ReleaseConfigTable`, in
`arc/worlddataeventcommandcommand_data_rootcommand_data_root.bin.trpak`). The pack's only table of
that shape holds 10 and 1.

`s2_sub_012.ReleasePokeTable` in the same pack puts each legendary on two of four routes, two solo
(`MissionA`, `MissionB`) and two Team (`TeamMissionA`, `TeamMissionB`):

| on | legendaries |
|---|---|
| both solo routes | Articuno, Zapdos, Moltres, Kubfu |
| both Team routes | Rayquaza, Kyurem, Necrozma |
| one of each | the other 18 |

The script asks `CA4C5F9FA83D2AF80.SDF0C255E6E08D740` which pair of routes the player is on, the A
routes or the B routes; Scarlet is on the A routes (a Team clear released Zekrom, only on
`TeamMissionA`). Each pair splits the 25 legendaries with none shared: 13 on the solo
route and 12 on the Team route. A talk releases at most one snack, trying the Team route first. Each
route picks at random among its legendaries not yet released (`0.2007`). A route's next release
needs its total to reach its count times one more than the legendaries on it already released. So
all 25 need a solo total of 130 and a Team total of 12, and 25 talks.

No message names a snack: the script compares the host's own totals with the config. Each message 3
carrying a Team clear adds one to the host's Team total, with no check that the quest is a Team quest
it has and no sequence check against a repeat; with a `teamMissionReleaseCount` of 1 each is one
Team-route snack. Each of the host's quests a member finishes ([A member's progress on the host's
quests](#a-members-progress-on-the-hosts-quests)) adds one to its solo total, which feeds the 13 on
the solo route.

## Joining

`bin/sv_join.py --union-circle` joins a circle a console hosts the way a raid guest joins a raid
(`pokeldn.sv.circle`). It takes the seat, sends its identity records, mirrors the host's channel
table on 0x7C port 1, and holds the seat for `--hold`, by default the whole `--seconds`. It sends no
lobby message and does not take the host role when the console leaves. When the host's field is up
it puts its player on it (`circle.Member`, [The field](#the-field)). It prints what a user follows;
`--verbose-circle` adds each circle message it sends and each step of the area search, which the
`--capture` file keeps anyway.

    ./.venv/bin/python bin/sv_join.py --union-circle --code 3707 --hold 540 --capture circle.jsonl

A retail Scarlet 4.0.0 hosting a circle under a Link Code advertises scene 5, four participants at
most, and the trade's application data: the code in the password and in the game bytes, its length
at +0x24. The game bytes also hold `aa 08 3e` at +0x21, which a searching console leaves zero.

It seats a guest the way a Link Trade or Tera Raid host does: the join response, station lists, the
channel table (keys 0x007B, 0x0132, 0x0232 and 0x0332), both stream opens, the clock answer and its
identity records. The guest then waits until the host's player starts the circle.

## Starting the circle

On the start the host sends Net 0x50 with its advertisement counting the members, the type-7
announcement on 0x80 port 2 (and a type 9 accepting each member), and its circle messages on 0x80
port 0.

The circle messages are the Lua's net messages. Each is a game message (handler key, kind, step,
then the serializer header; [Tera Raids](sv_raid.md#the-lobby)) under key 0x0132, and its kind is
the Lua message id. The raid's "loading" and "loaded" (0x0132, kinds 0x6E and 0x73) are messages 110
and 115 of the same receiver. Some payloads are FlatBuffer tables, the others fixed structures; 104
and 106 are LZ4-compressed (serializer compression 2).

| message | from | payload | handled by `TeamCircleUI` |
|---|---|---|---|
| 100 | the host, on the start | a table of one u32, always 12345678 | the start sound; the guest's start flag |
| 101 | every station, the host right after its 100, a member on the host's 100 | 32 bytes: where the station stands (field id, three Pokemon Center flags) | per station |
| 103 | every station | a table of one u32, the sync point's id | 1 and 2 to the UI (the start demo loaded, ended), every other id to the sync object |
| 111 | the host | 5916 bytes: four zero bytes, then a FlatBuffer of two vectors of tables (30 and 10) | a flag only; the content is read natively |
| 104 | the host | a table: game time, real time and their elapsed seconds (floats), the weather seed (u64), the lottery's length and its pairs of {type, duration} for the current and next weather | the clock and weather, into the game-time manager and `WeatherManager.Sync` |
| 102 | the host | two u32: the fly point the members warp to | the warp |
| 106 | every station | 300 six-byte slots, its Tera Raid crystals; `ffffffff0000` an empty slot | per station |

The host sends them in the order of the table, with three key-0x0048 messages after its 101, within
two seconds of the start.

Every station reaches sync point 2215, waits for every station's 101, sends its 106, and waits for
every other's 106 (`IsGemInfo`); the start demo's 103s with ids 1 and 2 are waited on the same way.
A sync point is reached when every member has sent a 103 with its id (`CEEE8D2836ABEDE23`).

A retail console splits a message longer than 1395 bytes into fragments and leaves an unfragmented
longer one unacknowledged, so the 106 goes LZ4-compressed, as the host's own does.

Once every 106 is in, the host warps to the fly point of its 102 and sends 115 (1, 0).

## The field

The host's player then enters the field. It opens 14 more channel keys (low bytes 0x1E to 0x2A, some
with sub-channels 0 and 1) with an update on 0x7C port 1 to each member, zlib-compressed. A retail
member sends the same update back the same way. The host sends key 0x0024 kind 1 step 1 with no
body, and from then on sends its player:

| what | how |
|---|---|
| animation state | reliable, 0x80 port 0, key 0x001E kind 5, the state's name (`Top/pc_field/move/defaultwait01`), every 3 to 7 s |
| transform | the unreliable protocol 0x68 (mesh-addressed like 0x80), key 0x011E kind 4, 38 bytes of floats, about 20 a second; kinds 6 and 7 once |

Before building the start demo, the host waits (`F9FFADFE613D572B7`) until each other station's
player object exists on its field. A member that sends no player leaves it on a black
"communicating" screen. The host spawns members as `playables.Player` objects through the native
module `c2A8846F6` (its `f6BD530B6` runs just before the wait).

The player objects travel between each member and the host on 0x7C port 0, after the field keys:

| key | message | what |
|---|---|---|
| 0x001F | id (u16), type (u16) | a console declares one of its own objects |
| 0x001E | kind 0, 0, id (u16) | a console asks for an object the other declared |
| 0x001E | kind 1, 2 or 3, 0, id (u16), the state | the answer: the object's state, its kind 1, 2 or 3 by the object's place in the declarations |

Each console declares four objects (types 0, 1 or 2, 3 and 10), ids stepping by 4 from the station
index. A console asks for every object the other declares; nobody answers an ask for the type-10
object. States are 70 bytes (kind 2) or 214 (kinds 1 and 3), zlib-compressed: handles, scale,
rotation, position; kind 1 is the player and carries a FlatBuffer. The host starts its demo half a
second after the member's kind-1 answer.

The member then asks the host about lists of u64 ids on key 0x0025, and the host answers each list
with flags ([Overworld encounters](#overworld-encounters)).

Key 0x0048, the BBQ module's ([Native modules](#native-modules)), is in the host's first channel
table. Around its port-2 announcement the host sends kind 1 step 1, a bodiless kind 4 (`480004`),
and kind 1 step 2, both steps carrying its status record ([The BBQ status
record](#the-bbq-status-record)).

`circle.Member` does the following:
- It answers the host's 100 with a copy of the host's own 101, so the guest's player stands where
  the host's does.
- It echoes every 103 the host sends.
- It answers the host's 106 with 300 empty slots, LZ4-compressed: a world without crystals.
- It sends a copy of each 110 and 115 the host sends as its own, following the host's field.
- Once `sv_join` has sent the field keys back, it declares station 1's four objects and asks for
  each of the host's. It answers each of the host's asks with the state of the host's own object of
  that type under the guest's id, so the guest's player stands as the host's does.

With `--follow-host`, the guest's player also moves with the host's: each host frame on 0x68 and
object message on key 0x001E goes out under the guest's matching object, on the guest's own 60 Hz
clock, replaying the host 0.3 s late (the host's transforms arrive about 27 times a second). The
guest stays within 5 m of the host, faces it, and scales the host's move blend by its own pace.

With `--circle-task`, the guest's player leaves the circle once the task is done, and the run ends:
- `snacksworth` reads the host's solo and Team totals from its first status record. From the start
  demo's end (its 103 with id 2) it sends, one a second, the Team clears its Team total lacks for
  12, then reports finishing the host's quests until its solo total is 130 ([A member's progress on
  the host's quests](#a-members-progress-on-the-hosts-quests)), then a Team clear more while its
  Team total still lacks any ([Snacksworth](#snacksworth)). Each Team clear is of a Team quest drawn
  as the game draws them (`circle.TEAM_QUESTS`, each quest and BP with its odds) and pays that
  quest's BP. It prints its progress as the host's totals rise, and stops when
  they have not risen over 20 sends in a row.
- `bp` sends, a second after the start demo's end, one Normal clear of quest 29 paying the
  `--bbq-clear` BP, 1 to 9,999,999.

Each clear is a message 3 with its BP, the guest's station id and the guest's status record.

A retail host pays every such clear with no message 1 from the guest before it; the notices and BP
show once its player closes the BP side bar. One Team clear, of any quest, releases the next
Team-route legendary ([Snacksworth](#snacksworth)), with the host inside or outside the Blueberry
Academy.

## Overworld encounters

Every console in a circle spawns the wild Pokemon around its own player from its own game version,
and broadcasts each one to the others, so a member catches the other version's exclusives (a
Scarlet host in Area Zero spawns dev id 982, a Violet member 992). No version is exchanged, and the
host has no special role.

The shared Pokemon travel on 0x80 port 0 and the unreliable protocol, broadcast by their owner;
only the ask for one and its refusal go to a single station, on 0x7c port 0:

| key | message | what |
|---|---|---|
| 0x0026 | kind 1, its 96-byte record as a byte string | the owner spawned entity (station, n) |
| 0x0026 | kind 2, (station, n) | the entity is gone |
| 0x0026 | kind 5, ((station, n), (station, n)) | a console asks the owner for the entity to battle it, under the asker's own id; on 0x7c port 0 to the owner alone |
| 0x0026 | kind 6, the same pair | the owner refuses; back to the asker |
| 0x0026 | kind 7, the same pair | the entity now belongs to the second id's station, which battles it; one came 15 s before that entity's kind 2 |
| 0x0126 | kind 3, (station, n), (a float, 0.0, 0.0, 0, 0 or 1) | the entity's state, every 0.2 s (member) to 0.5 s (host); the last element is its status |
| 0x011E | kind 4 on 0x68, by object id | the entity's transform, as for a player |

An entity's object id is station + 4n, the u16 that opens its record. A console shares its entities
only with a member whose player stands near its own. Every id is a pair of unsigned integers (the
dispatcher `0x1dbd4b0` reads no signed tag).

A console files another's entity as unsettled (status 1) and refuses to battle it
(`BattleStartWait`) until a state names status 0. Walking into a settled one, it shows the "!"
and asks the owner (`0x1972664`): it takes a new id of its own for the entity, stores the pair
and a callback, and its manager update (`0x1593884`) sends the kind 5 to the station that sent the
entity's record. The encounter (`GameEventEncount`, NetInitWait) then waits, with no timeout, for
the owner's answer naming the same pair (`0x1dbdd70`). The owner hands the entity over
(`0x1dbdc20`, then the update's broadcast at `0x15934c8`) when it is one of its own and no other
console holds it, else refuses (`0x1593914`). Handing over, every console renames the entity to
the asker's id (`0x1595a1c`) and marks it engaged; the asker files it as its own and starts the
battle. When it battles its own entity, a console broadcasts a kind 7 with the pair the same
twice.

The record is 96 bytes. `EncountManager.UpdateNetworkSpawn` copies its fields into a
`pml.pokepara.InitialSpec` through the getters the Lua module `c4CF1D719` binds (native
`0x90e344` to `0x90e588`), then sets the ribbon, the Tera Type and an Alcremie's decoration on the
Pokemon itself. Every record captured fits this layout:

| offset | bits | field |
|---|---|---|
| 0x00 | u16 | object id |
| 0x04 | u64 bits 0-10 | dev species |
| | 11-22 | held item |
| | 23-30 | scale |
| | 31 | sex (1 female) |
| | 32 | shiny; the spawn is shiny when set |
| | 33-37 | form |
| | 38-44 | level |
| | 45-52 | ribbon (mark), applied when not 0 |
| | 53-57 | nature |
| | 58-62 | Tera Type |
| 0x0C | u32 bits 0-3 | Alcremie decoration |
| | 8-27 | IVs HP, Attack, Defense, Speed, 5 bits each |
| 0x10 | u16 bits 0-9 | IVs Sp. Atk, Sp. Def |
| | 10-11 | ability slot |
| 0x24 | s32 | -1; 0 in the only Ditto and Zorua seen |
| 0x30 | 3 floats | position |
| 0x40 | 4 floats | rotation, the identity in every sample |

The other bytes are 0 (retail records hold stale memory at 0x02, 0x28 and 0x54). Before its record
the owner sends the entity's frames on 0x68: kind 6 with no parent
(`00000000 00000000 0000003f 0000003f 00000000 0000003f 0000003f`) and kind 7 with scale 1.0.
`circle.Spawner` sends the guest's own spawns the same way ([Crafted encounters](#crafted-encounters)).

`UpdateNetworkSpawn` builds the Pokemon from the record alone; the shiny bit sets the rarity word
(`+0x18`) to `0x2ffffffff` or `0x1ffffffff`, so the owner decides either way. The record holds no
moves, PID or encryption constant; a catch adds the catcher's trainer, ball, location, date and level.

The game accepts any record; PKHeX (Core 26.8.26) judges the catch as a wild encounter at
the location where it was caught:

| field | PKHeX accepts |
|---|---|
| species, form, level | a Scarlet / Violet wild slot at the catch location with that species and form and a level range holding the level; a shiny-locked or static-only species such as Rayquaza never |
| Tera Type | one of the species' own types, unless a distribution outbreak covers the species there |
| sex | within the species' ratio |
| mark | not Mightiest or Titan; Jumbo only with scale 255, Mini only with scale 0; a weather mark only where a slot names that weather |
| shiny, nature, IVs, ability slot (hidden too), scale, held item | anything |

PKHeX lists every Scarlet / Violet wild slot under both versions, so the other version's exclusive
is legal, and time-of-day slots do not restrict a stored Pokemon. The record's species is the
internal index (`gen9.national` gives the National Dex number).

The rest of the field:

| what | key |
|---|---|
| the host's outbreaks | 0x0029 kind 1, broadcast once per outbreak as the field opens |
| the host's own state | 0x0024 kind 1 and 0x002A kinds 3 to 5, a few small integers |
| a member's id queries | 0x0025, member to host only |

Both games ship one encounter table per map (`world/data/encount/pokedata/pokedata*_array.bin`)
holding both versions' rows; field 28 names the versions a row is drawn in.

An outbreak message is a tuple: the center (three floats, from `world/data/encount/point_data/
outbreak_point_data`), a second point near it, the species, 0, the form, 0, a count of 90 to 110, the
map (0 Paldea, 1 Kitakami, 2 Blueberry) and 0.

Key 0x0025 is a periodic member-to-host query: kind 1 lists u64 ids, kind 3 answers each
`((id,), flag)` with 0 or 1, kind 2 lists ids the member lets go. The ids' top five bits are a
category; a member walks categories 1, 2, 3, 4, 5, 9, 10, 13 and 16 about every nine seconds.

## Crafted encounters

`sv_join --spawn SPECIES:LEVEL` joins the circle as a member and keeps three spawns of a Pokemon the
user crafts around the host's player; with `--follow-host` the guest's player follows the host's.
The `--spawn-*` flags set what a record carries: form, shiny, Tera Type, nature, gender, ability
slot, size, held item and IVs. One left out is drawn as the host's own wild ones were: the size, the
nature and each IV at random, the ability slot 0 or 1, no held item. Each spawn comes 15 to 25 m
from the host's player. One the host battles (its ask, handed over), removes (a kind 2 naming it) or
walks more than 50 m from is let go and another comes near the host.

With `--spawn-legal`, PKHeX decides: the helper's `wild_areas` command lists the Scarlet / Violet
wild slots by location, and `wild_legal` runs PKHeX's legality analysis on the crafted spawn caught
from each, once per Tera Type. A spawn PKHeX accepts at no location stops the run.

The spawns then wait for the host's area (`wild.Locator`). Each wild Pokemon the host's console
shares (key 0x0026 kind 1, once the guest's player is near) narrows the locations to those with a
slot for its species, form and level. The area counts as found once every location left is one where
PKHeX accepts the spawn; it need not be one. Then the spawns come, and they all go when the host
walks more than 50 m from where it stood when the area was found; finding starts over. Before that,
finding also starts over when the host is more than 100 m from a spawn it weighed, and from a spawn
no location left holds. A spawn no wild slot holds (a raid's, an event's) is left out.

In Area Zero the host's console sends no transform of its player. With no transform for 2 s, the
host is placed at the middle of its six newest spawns of the last 30 s; with none, no new spawn comes.
A transform within 10 m of the origin never places the host.

The search shows as a `[panel]` status card with id `zone` in the app.

## Unresolved

- Whether the merge in the grant push (`0xa112c0`) changes an event's BP.
- Whether the two totals are saved, and what the host's BBQ manager flag that gates the Team total
  (its `+0x40`) stands for.
- Whether a group BBQ counts only members in the same field, as the 110 getter suggests.
- What `aa 08 3e` in the game bytes is, the fields of 101 and 111, and the BBQ message 4.
- Which two values a message 2 names for a quest with a variant, and whether the host caps a count
  above the quest's goal.
- What the status record's further slots, its byte string and its element 7 hold.
- What the type-10 objects are, and what the key-0x0025 ids and queries arbitrate.

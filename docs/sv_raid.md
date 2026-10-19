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
| mesh-addressed messages (RTT, 0x80, 0x81), the Session station lists | to the subnet broadcast, not the console's address (unicast over ldn_mitm, which carries no broadcast to a peer) |
| Net 0x11 | one sequence, repeated until the 0x12 |
| the station list's console entry | the player the console's join request named; with a placeholder player the console is seated and absent from the lobby |
| the station list | resent every 2 s until the console's type 6 |
| the opening | only after that type 6: the eleven first bulk acks, the 0x81 port 5 open and an RTT request in one packet; the 0x81 port 1 open, the channel table and the port-2 type 6; the identity 20 ms later, one record every 3 ms |
| the port-2 type 3 | answered with two type 9s: the host's station with code 0, the console's with code 1 |

The opening's 0x7C, 0x81 port 5 and 0x80 port 2 messages repeat every 0.25 s until acknowledged,
and every ack the host sends declares the lowest unacknowledged sequence of the stream.

### Several consoles

`--raid-players N` (1 to 3, the app's "Consoles joining") seats up to three consoles in one lobby,
each at the lowest free station index, 1 to 3. The consoles share the lobby and the start;
from the first turn each one fights its own battle, with its own NPC partners, and gets its own
rewards ([Which station runs the server](#which-station-runs-the-server)). The host keeps one set of streams per console, as for
a single one, with that console's index wherever a single console's raid has 1:

| | the console at index *k* |
|---|---|
| join response | station index and join order *k* |
| station list | every seated station, ours first; each new seat and each departure from the lobby sends the list to every seated console under the next sequence, resent until each one's type 6 |
| Net 0x11 | our station, then the seated consoles by index, then the joiner; each change of seats goes to every seated console under its next sequence |
| destination bitmap | `1 << k` under three destination bits |
| bulk ack | entry *k* |
| opening | 0x81 ports *k* and 4 + *k*, the ports the console sends on |
| port-2 type 6 | ours and the members already seated, in join order, with their codes and count |
| port-2 type 9s | ours under code 0, each seated member's under its code, the console's last under code *k*; each seated member receives the console's |
| bootstrap | its Pokemon in slot *k*; an empty slot for a free seat |

A join that finds every seat taken, or comes after the start, is left unanswered, and a console with
no free seat gets no Net 0x11. The host drops every packet whose header and footer do not name its
own variable id, and every reliable message whose bitmap lacks station 0: consoles in one lobby
address each other through the same broadcast.

A port-2 slot keeps its members at slot `+0x170` as a u8 code and a u64 station id;
`0x138d208` returns a station's code, 0xfd for a non-member. A retail host's type-3 handler
`0x1981e94` takes the lowest code 0 to 7 that no member holds and no queued type 9 names
(`0x279c9a0`), then broadcasts one type 9 per member with its own code and one for the joiner. The
receiver `0x18b68fc` appends a `(code, id)` it has not listed, never changing a listed member's code;
for its own id it raises a member-joined event for every other member, and the code becomes its
own. The type 6 (`0x12fbf8c`, composer `0xe457cc`, to the joining station only) carries the members'
ids at `+0xa0`, their codes at `+0xc0`, the count at `+0xc4` and the closed byte at `+0xc5`; its
receiver `0x279b9c4` replays a type 9 for each member.

The lobby's participants are the port-2 members: the Lua lobby (chunk `be21e654`, receiver
`0.15829`; a `0.N` here is the chunk's main function's prototype N, counted from 0) files every
message under its sender's code, and under 253 a sender with no code. Each console sends its state
0x18 and its Pokemon to the others on entering the lobby, and a station receiving a 0x18 answers
with its own Ready state and Pokemon; the consoles of one lobby exchange their Pokemon among
themselves.

The reliable header's receive check (`0x6f0410`..`0x6f0430`) tests the receiver's own bit,
`index & 31` of word `index >> 5` (bit 0 station 0), for any destination count from 1 to 23. A
retail sender writes three, the station capacity 4 (`0x44dfcb0`) less one (`0x6e71c4`), whatever
the number of stations.

The host hands the network to the lowest index still on it, as for one console; the other consoles
draw the is-migrating Net 0x11 and NetStartHostMigration with no Session type 7. The is-migrating
0x11 to each console ranks every seated station (a rank is who hosts next) and goes to the others only
after the next host's type 8; NetStartHostMigration goes out once every console has answered its 0x11
with 0x12, and no plain Net 0x11 follows. The run ends once every console has left the network or each
handover has run out.

What decides whether the consoles stay in one battle:

| condition | code |
|---|---|
| a console that sees another leave keeps it only once it is migrating: `[net+0x249]` set by an is-migrating 0x11, or `[net+0x1c0]` set by NetStartHostMigration; otherwise it drops it from its session and resets its Net station | station-left handler `0x69d08c`, `0x69d174` |
| a Net 0x11 with a newer sequence drops every station marked as gone | `0x69e008`, `0x6b5074` |
| the next host waits up to 8000 ms for every Net station to reach state 2 (seen on its new network), then drops those still in state 1, sends Net 0x11, waits for every 0x12 and sends the Session type 5 | NetHostMigrationJob `0x6a9cd4`, `0x6aa2a8`; `0x6d44f0` |
| the other console waits 10000 ms for that type 5, then fails | `0x6dc024`, `0x6dc124` |
| the type 7's last u16 at most the next host's applied list sequence | `0x6d9164` |

Two emulated Scarlets handed over this way formed one session on the next host's network (type 5
answered with type 6, no error on either screen) and fought on with an NPC in the free seat.

A Pia host sends the new Net 0x11 to every station on each change of LDN participants: `0x69c310`
compares the previous and current connection status, `0x69c79c` increments the one counter
`[NetProtocol+0x60]` and sends every slot to each station but its own, rankings in ascending IPv4
order (`0x6a05ec`). On LDN a joiner's 0x11 receiver `0x69db14` creates no station from its entries
(`0x6a2fac` returns 0): it stores the host's address and ids, copies rankings onto stations it already
has and answers 0x12. A joiner's stations come from the LDN node list (`nn::ldn::GetNetworkInfo`,
`0x6b43a8`), port 12345.

The type-5 receiver `0x6d7f8c` creates each newly listed station in `0x6d840c` only when its IPv4
and port are in that node list (`0x6a8320`); otherwise it sends no type 6 and resets its applied
sequence to 0xffff (`0x6d81a4`), so a later copy of the same list is evaluated again.

Session type 9 (`0x6d4ef0`), from a joiner to the host, `09 | its constant id | count | count
constant ids`, names the stations it has not heard from (`0x6d4a60`) and repeats every 3000 ms. The
host's receiver `0x6d940c` hands a single named station to the kick job (`0x6dc878`) and resends the
station list to every station.

After a console's join a raid host sends packet id 0, or the seated console drops what follows a
higher id
([docs/pia.md](pia.md#version-11-what-a-receiver-drops-scarlet-400)): a station list resent under
packet id 1 after a packet with id 87 left the first console of a two-console lobby on its old list
(retail and emulated), and the second showed "Communicating..." until it reported the first silent.
Sent the later lists under packet id 0, two emulated consoles and two retail Scarlets listed each
other and fought one raid, in sync after the host left.

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
| 0x3380 | 0x2d | a participant's state: 0x00 not ready, 0x01 ready, 0x0c the host's start, 0x0d a guest's answer to it, 0x18 entering the lobby, 0x1e the host refusing a late station (`0.30822`) |
| 0x3380 | 0x2e | a participant's Pokemon, its encrypted 344-byte party record |
| 0x3380 | 0x2f | the battle bootstrap |
| 0x3380 | 0x30 | the lobby timer, in seconds left (0x91 downwards) |
| 0x0132 | 0x6e, 0x73 | a console loading the battle, then loaded |
| 0x3480 | 0x93 | the battle begins |
| 0x007b | 0x13 | the battle-start messages a host sends after 0x3480 |

A retail guest sends 0x18 and its Pokemon on entering the lobby and 0x01 when its player presses
Ready: in seven retail raids four guests sent 0x01, 1.9 to 3.6 s after their Pokemon, and three sent
none before the host's start at 5.39 s; all seven answered the start with 0x0d and fought.

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

`pokeldn.sv.raid.RaidHost` releases the host's messages to one console in order, each at its time
from the port-2 answer and after the console's previous step; `pokeldn.sv.raid.RaidGroup` holds what
the consoles of one lobby share. With one console that readies within 5 s the sequence numbers are a
retail host's:

| seq | message | released by |
|---|---|---|
| 1 | descriptor (zlib, INITIALIZED) | the console's own lobby Pokemon (0x2e) |
| 2, 3 | state 0x18, our Pokemon | |
| 4, 5, 6 | timer 0x91, 0x90, 0x8f | 0.73, 1.76, 2.75 s |
| 7 | state 0x01 | 3.19 s |
| 8, 9 | timer 0x8e, 0x8d | 3.76, 4.79 s |
| | the timer, each time it drops | one step a second from 0.73 s after the first console's answer |
| 10 | state 0x0c, the start | 5.39 s, once `--raid-players` consoles are seated and every one has sent 0x01, or once the timer has sent 0 |
| | Net 0x50, property state 7 | the console's state 0x0d |
| | Session station list, the next sequence | the console's Net 0x51 |
| 11, 12 | the bootstrap, two fragments | the console's type 6 for it |
| 13 | loaded, `0x320173` | the console's 0x6e or 0x73 |
| 14 | the battle begins, `0x803493` | the console's 0x73 |
| 15 to 20 | the battle-start messages | the console's 0x93; then 0, 0.10, 0.12, 0.16, 0.18 s |

The timer is the seconds left before the host's lobby deadline: a retail host opens a 180 s lobby
and sends the value once a second (`0.27104`), so the 0x91 of the table came 35 s after it opened.
Our timer starts at 180 at the first console's answer; a console that joins a running lobby
receives it at its current value. A console's 0x00 or 0x18 withdraws its 0x01; its Pokemon does
not, since a ready console resends it to each newcomer.

In the game's code a guest answers 0x0c with 0x0d at once, with no Ready check, and a guest whose
timer reaches 0 waits for the bootstrap (`Raid_Start_Ready`, `0.27137`): only the host starts a
battle. A guest that holds the bootstrap without having readied ends its lobby before the timer
(`0.27104`) and goes to the battle the same way. A retail host readies on its player's first choice
and sends 0x0c on the second (`0.27095`). `Raid_Start_Ready` turns the menu's first three items off
(`f6277C172(false)`) on entry, on host and guest alike; on a host it turns the first, the one that
starts, and the menu back on while every other member is ready, and off again when one is not: its
player can start only once every guest is ready. Whether `f6277C172(false)` hides an item or greys
it out is unresolved. At timer 0 it breaks the lobby up when no member is ready and starts
otherwise. `Raid_Start_Go` (`0.27140`) resends 0x0c until every member has answered 0x0d, then sends
the bootstrap, slot *k* the Pokemon of the member with code *k*; ours waits for every console's 0x0d
too, and starts once every console is ready or at timer 0 whoever is ready.

A gated message leaves 50 ms after its milestone; the Net 0x50 and the station list repeat every
0.5 s until answered, and the raid messages every 0.5 s until acknowledged. A retail console once
answered the bootstrap with 0x73 and no 0x6e, so message 13 waits for either.

Five seconds after the last console's message 20 the host hands the console its network as a leaving retail host does
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
| 0x3d8 | u64 | `randSeed`, the partner seed ([Partners](#partners)) and the battle's random seed ([The battle's random numbers](#the-battles-random-numbers)): nonzero in retail points; `raid_point` writes the one it is given, 0 by default |
| 0x3e0 | u32 | `raidNpcGroupID`, the host's raid unlock stage, which picks the partner pool ([Partners](#partners)): 4 in every retail point seen; `raid_point` writes the stage of the raid's progress unless given one |

In the raid tables every six-star record's `raidTimeData` is active with `gameLimit` 450 and
`commandLimit` 60, every one-star record's inactive with `gameLimit` 300, and the rest zero; a retail
black point (record 6045) carried 1, 450, 0, 60, a retail three-star point (record 3019) an inactive bool byte with three stale bytes after it, then zeros.
Bytes 0x3b5..0x3b7, 0x3d4..0x3d7 and 0x3e4..0x3e7 held stale bytes in both retail points.

The action profile is the record's `bossDesc` in the game's raid tables, in that order; the
actions are 0 none, 1 reset the boss's stat changes, 2 reset the players', 3 a move, 4 drain the
Tera orb, and the timings 0 none, 1 time, 2 HP. An action's value is the share of the boss's HP or
of the time left that brings it, and the shield's first two values are the HP and time shares that
raise it, either one; Serebii's scripted actions for the seven-star Kingambit of August 2026 read
the same from its record. HP coefficients run 500, 500, 800, 1200, 2000 and 2500 for one to six
stars.

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
rows there, it listed the first only. Sent four subject-4 rows against the Ghost Tera boss, it listed
the first two with the power at level 2 and the first three at level 3.

An active meal power is held in memory as u32 kind, u32 type, u32 level and an f32 of seconds left,
1800 when eaten and counting down in the field. The level 2 and 3 checks above, and the one below,
wrote the level and type words of a Jambon-Beurre's Raid Power: Ghost Lv. 1 record.

On a black-crystal point (seed `09F3E337`, Kingambit with Tera type Fairy) with a Raid Power: Fairy
Lv. 3, the same guest listed 18 of the point's 19 rows: every subject-0 row, the subject-2 row, the
three subject-4 rows and the subject-5 Fairy Tera Shard x12; it left out the subject-1 row. The one
row carrying the rare-item flag, the subject-4 Bottle Cap, came first on the screen; the others kept
the point's order. The point was `raid_point`'s with only the action profile replaced (HP coefficient
100, the rest zero) so that a single guest could win; its stars, crystal, `raidTimeData` and rows
were the seed's.

Scarlet 4.0.0's Lua reward filter, `C07C34FC3B976E5A7.F316609DEA110601D`
(lines 78707 to 78765 as its bytecode records them), keeps subject 0 for every player, 1 for the host, 2 for a guest
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

The timer initializer `C2D7F486425487755.F0C64BA9B6853E61A` (lines 79486 to 79513 as its bytecode records them)
uses supplied time fields when `raidTimeData.active` is true. With it false, a group battle uses
game limit 300, command limit 60, client limit 0, revive time 30, AI interval 17 and AI interval
randomness 6. Executing its unchanged Lua function with the six-star table data yielded
450, 60, 0, 0, 0 and 0 respectively; a zeroed RaidPoint yielded the defaults.
Both functions are in Lua chunk `be21e65463b9a98f`, SHA-256
`c1a4f4e2625912cf0b739a642a79ba3357df0557a544b92da22a6cb139de2815`.

`raid_point` builds the seed's rows as a retail host does: each fixed row's table subject, the
lottery table's rare flag, three more lottery draws under subject 4 and the difficulty's Tera Shard
boost under subject 5. For seeds 7B741233 (three stars) and 09F3E337 (black) its 45 rows equal the
retail points' bytes. A retail Scarlet guest holding the Glimmering Charm, sent seed 7B741233's
rows, listed Ice Tera Shard x1 and x2: the subject-5 row, and not the host's subject-1 x1 row.
Chosen rewards go under subject 0 with no bonus rows, so a guest receives
every one. A retail console awarded a row rewritten to Quick Ball x500, with the other
rows cleared and one bonus row left, as written.

## Partners

Every console fills the participant slots no lobby member holds with the same NPC trainers, drawn
from two RaidPoint words the Lua calls `randSeed` (u64 at 0x3d8) and `raidNpcGroupID` (u32 at 0x3e0)
(`0.4453`). The natives behind their getters read +0x3b8 (`0x1be5ac0`) and +0x3c0 (`0x1be5c20`) of
the 0x3c8-byte struct that follows the RaidPoint's first 0x20 bytes. The guest's bootstrap handler
reads both (`0.15829`); a retail host draws a new `randSeed` at each start and writes both
(`Raid_Start_Go`, `0.27140`). The u64 seeds xoroshiro128+ whole (native `0x17ebec0`), with
`0x82A2B175229D6A5B` as the second word. The console draws three trainers (`0.7804`), each
`next_int(n)` over the n trainers still in the pool (masked to the bits of n − 1, redrawing values
of n or more) and taken out of the pool, so in the full pool the bounds run 18, 17, 16. The empty
slots take the draws in slot order (`0.4455`): one empty slot takes the first, wherever it sits.

A partner's record takes five xoroshiro128+ draws from the same `randSeed`, and every partner of a
battle shares them (`raid_partners.identity`): draw 0 is the encryption constant (redrawn while
0xffffffff), draw 1 TID | SID << 16, draw 2 the PID (bit 28 flipped when it would be shiny), draw 3
the height and draw 4 the weight, each 0x30 + next_int(0xa0). Everything else comes from the
trainer's entry (below), with language 2 and the species' base friendship. From the seed, the stage
and the level alone, these rules give all ten partner records of five emulated raid battles, 0x148
bytes each.

The raid start (`0.4455` -> `0.4459` -> `0.4901`) hands each partner's `poke1` table, its level and
`randSeed` to the Lua binding `f92C18AA6` (`0x1905a10`). It builds a pml InitialSpec whose seed is
`randSeed` (`0x1905ce0`), converts the table into it (`0x160ffd0`) and creates the PokemonParam
(`0xdebe4c` -> `0xdec698` -> `0xdef2b8`). A seeded `0xdef2b8` takes every draw from its own
xoroshiro128+ (`0xdf78bc`, `next_int` `0xdf78d8`), for the fields the spec leaves unset, in this
order: EC, ID, PID, IVs, ability, gender, nature, height, weight, scale (`0xdf011c`). The binding's
third argument is true, so the converter turns a height, weight or scale left random into size class
M (SizeType 3, `0x1611cc4`), which `0xdf011c` draws as 0x30 + next_int(0xa0); a random one would be
next_int(0x81) + next_int(0x80). Executed under unicorn, `0xdef2b8` reproduces the ten records' EC,
PID, height and weight with size class M and with no other class.

The converter sets the gender of an entry whose `sex` is 0 before the encryption constant is drawn,
from that unset field: female when the species' percent female is at least (2^64 - 1) mod 100 = 15,
male below 15 and at 50 (where the binding's fourth argument, 0, decides); a one-gender or genderless
species keeps its own (`0x1611d1c`). Growlithe and Arcanine are female, Magnemite, Magneton and
Bronzong genderless, the other partners male. A `gemType` of 0 leaves the Tera type to a
per-species table `0xe78418` reads, keyed by species x 10000 + form; Haxorus takes Dragon and
Clodsire Ground.

The u32 at 0x3e0 picks the pool, the data table field `difficulty_0`*N+1* (`0.7797`), its trainers
and their Pokemon (the table below): 0 and 1 the first 16 trainers, 2 all 18, 3 and 4 all 18. The
pools are the RomFS tables `world/data/raid/raid_trainer_01` (16 rows, stages 0 and 1), `_02` (18,
stage 2) and `_03` (18, stages 3 and 4). A row holds `raidTrainerInfo`, the trainer id
`raid_assist_NPC_1` to `_52`, `npcPresetIndex` (the row's index, which `0.4459` passes to the
trainer's model) and `nameTextLabel` (`TRNAME_RAID_ASSIST_01` for row 0 onwards in every pool). The
trainer's one Pokemon is `poke1` of its entry in `world/data/trainer/trdata/trdata_array`, a
`PokeDataBattle`: species, form, level 16, 40 or 80, `tokusei` 2 to 4 (ability slot 1, 2 or hidden),
three moves, `gemType` (2 + the Tera type), IVs 31/10/31/31/10/31 (HP Atk Def Spe SpA SpD), EVs 252
HP, 128 Def, 128 SpD, Hardy, Poke Ball, not shiny, `sex` 0, scale 128 and no held item.
`raid_trainer_04` to `_07` list field trainers (`area04_trainer_*`, `area05_trainer_*`); what reads
them is unknown. `scripts/gen_sv_partner_data.py` decodes the pools into
`pokeldn/sv/data/raid_partners.json` (`raid_partners.game_pool`). A
partner's Pokemon is built at level int(0.8 × the level of the Pokemon in battle slot 0, the
host's), not its preset's (`0.4455`, `0.4901`), so Serebii's levels 16, 40 and 80 are those of Lv
20, 50 and 100 hosts. In a pokeldn raid slot 0 holds `--raid-pokemon`. Retail Scarlets showed Eli's
Gardevoir at Lv 80 beside a Lv 100 one and at Lv 29 beside a Lv 37 one, whatever their own Pokemon's
levels (100 and 84), and the first stages' Eli's Kirlia and Charlotte's Staravia at Lv 80 beside a
Lv 100 one, past their pool's 16. At 5 a retail Scarlet's partners were Pikachu named after the boss
and its battle crashed later, so `raid_point` refuses a stage past 4.

A retail host writes its raid unlock stage at 0x3e0: `raidNpcGroupID` comes from native `0xe2826c`
(Lua binding `0x193a560`, `0.2895`), which reads four save flags through the flag getter `0xeb1cf4`
and returns the highest set, no other flag counting:

| flag key | name (PKHeX) | stage |
|---|---|---|
| none set | | 0 |
| `0xEC95D8EF` | `FSYS_RAID_DIFFICTLTY3_RELEASE` (`KUnlockedRaidDifficulty3`) | 1 |
| `0xA9428DFE` | `FSYS_RAID_DIFFICTLTY4_RELEASE` (`KUnlockedRaidDifficulty4`) | 2 |
| `0x9535F471` | `FSYS_RAID_DIFFICTLTY5_RELEASE` (`KUnlockedRaidDifficulty5`) | 3 |
| `0x6E7F8220` | `FSYS_RAID_DIFFICTLTY6_RELEASE` (`KUnlockedRaidDifficulty6`) | 4 |

Executed under unicorn with a mocked flag store, all 16 flag combinations return this mapping. The
Tera Raid unlock flag (`0x27025EBF`) is not read, so 0 is a save with one- and two-star raids or
none. The stage is the story progress less one (`raid_encounter.PROGRESS` from `tera`), and the
seven-star events share stage 4. The pool of stage 2 (Serebii's level 40) comes with four stars, one
stage after the "3 Star Raids Unlocked" heading Serebii gives it.

One den gives different partners on different attempts. A retail console ignored party records in
bootstrap slots no lobby station held: it still drew two partners. The bootstrap goes out after the
host's start, so a guest that leaves the lobby before it never holds the RaidPoint.

`pokeldn.sv.raid_partners` holds the table and the draw. `bin/sv_host.py` writes the stage of
`--raid-progress`, six stars for a black crystal or a seven-star event raid, or the one
`--raid-partner-progress` names, and draws a new partner seed for each run. With `--raid-partner` it
draws seeds until the first draws are those trainers in that order: 306 seeds on average for two of
eighteen, about a millisecond. Its log names the seed, the partners it seats and their level, four
fifths of `--raid-pokemon`'s (`raid_partners.level_for`). Our player and each console joining
(`--raid-players`) hold a slot, so a pokeldn raid seats two partners with one console, one with two
and none with three (`raid_partners.slots`); more `--raid-partner` than that are refused before the
radio. The host takes the seed's first draws to fill the empty slots left to right; a console that
misses the start leaves one more empty slot, which a further draw fills. Two retail Scarlets joining
`--raid-players 2 --raid-partner Eli` showed Eli's Gardevoir in the one empty slot, the fourth.

The pool, in draw-index order. The game's tables give the species, abilities and moves Serebii's Tera
Raid Battle partners page lists, and Henry's Tera type is Steel in every pool where Serebii says
random:

| # | trainer | 0x3e0 0, 1 | 2 | 3, 4 |
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

A retail Scarlet joining `bin/sv_host.py` (two empty slots) showed, with these two words in the
RaidPoint:

| 0x3d8 | 0x3e0 | partners |
|---|---|---|
| 0 | 2 | Samantha (Glalie), Zoe (Sandaconda) |
| 0x12345678deadbeef | 2 | Henry (Bronzong), Ava (Floatzel) |
| 0x26 | 2 | Ava (Floatzel), Logan (Gogoat) |
| 0 | 0, 1 | Chase (Dedenne), Samantha (Snorunt) |
| 0 | 3, 4 | Samantha (Weavile), Zoe (Mudsdale) |
| 0xaf05b3d1838735c0 | 4 | Eli (Gardevoir), Ava (Toxapex) |

### Favoured partners

Raiders rate ten partners of the stage 3 and 4 pool (Serebii's level 80) above the rest.
`raid_partners.RECOMMENDED` holds them, and the app's card for each ends on why and a star: gold for
the four raiders favour, silver for the next tier.

| rank | trainer | Pokemon | why |
|---|---|---|---|
| gold | Eli | Gardevoir | Life Dew heals the whole team; seven-star solo guides ask for it, often with Bellibolt. |
| gold | Hailey | Bellibolt | Light Screen, when she sets it, cuts the boss's special damage; Discharge can paralyze. |
| gold | Logan | Arboliva | Safeguard keeps status conditions off the team; Grassy Terrain heals each turn and also powers a boss's Grass moves. |
| gold | Charlotte | Staraptor | Intimidate on every respawn and Feather Dance cut the boss's physical Attack. |
| silver | Austin | Arcanine | Intimidate on every respawn; Leer lowers the boss's Defense. |
| silver | Kylie | Tauros | Intimidate on every respawn; Raging Bull breaks the boss's screens. |
| silver | Hunter | Drifblim | Will-O-Wisp burns the boss, halving its physical damage. |
| silver | Gianna | Umbreon | Thunder Wave paralysis can give a free turn, by chance. |
| silver | Evan | Dudunsparce | Glare paralyzes at 100% accuracy, except a boss with an Electric Tera type. |
| silver | Samantha | Weavile | Leer lowers the boss's Defense before its shield; Ice Punch can freeze. |

Intimidate raises the Attack of a Defiant or Competitive boss, such as Annihilape, on every respawn.
The earlier stages' pools have no Life Dew, Light Screen or Safeguard. The partners' moves changed
with The Teal Mask update; the sets above are Serebii's, which the sources describe.

Sources, read 2026-10-11: Amiibo Doctor's Tera Raid NPC Partners Tier List (June 2025); Game8's
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
A retail Scarlet over the ESP32 board fought the same two raids: the one-star Eevee won, its catch
offered and the seed's rewards given; Charizard the Unrivaled shown as seven stars, its timer bar
shrinking slowly. It also fought a standard black raid (seed `00000004`, Pincurchin) whose RaidPoint
carried the record's `raidTimeData` 1, 450, 0, 60.

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
Patch) is a separate rule; `raid_point` writes the table's subject and each console's reward
filter applies it.
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
leave (`pokeldn.sv.raid_search`) for a species, star level, Tera type, nature, gender, shininess,
size mark and IV ranges. It ranks the results by a score of the boss's stats (HP times the sum of
its defenses, either defense alone, its better attacking stat, or its total) or by the rewards
wanted (Most desired rewards, below). One result per species is kept unless a species is chosen.

### Size marks

PKHeX allows the Mini mark on a Pokemon that has been in Scarlet or Violet at scale 0 and the Jumbo
mark at scale 255 (`MarkRules.IsMarkAllowedMini`, `IsMarkAllowedJumbo`). The finder's Size mark
eligibility wants the boss's scale at 0 (Mini mark), 255 (Jumbo mark) or either (Any mark). The
scale is drawn after the height and weight (`boss_fields`):

| scale rule | scale | chance of 0 or of 255 |
|---|---|---|
| two draws (rule 0), every standard and black crystal boss | `next_int(0x81) + next_int(0x80)` | 1 in 16 512 each |
| an event band from 0 (rule 1) or from 240 (rule 5) | `next_int(16) + low` | 1 in 16 for the end it touches |
| an event's own value (rule 6) | the record's `scale` | always or never |

`raid_search.size_marks` names the marks an event's bosses of the chosen crystal, stars and species
can take, and the finder greys out the others.

### Wanted rewards

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
seed's rewards before its boss.

Most desired rewards ranks the results by the rewards wanted, in their order: more of the first item
wins, then more of the second, each row's least still a minimum. A raid's total of an item counts as
a digit, its place among the totals the raids searched can give, from the least up
(`raid_search.ranked_rewards`): a black crystal gives a material 8 to 30 by twos, 12 places. The
leading items' digits make one score under 2^31, which the helper keeps beside the seed in a 64-bit
rank; the items after those only want their least. Five items fit in every raid known (an event's
Exp. Candy L has 59 totals, the most of any item), and a black crystal ranks four herbas, patches or
caps and four materials.

### The helper's scan

The PKHeX helper scans the seeds over every core (`services/pkhex/RaidScan.cs`, packed and sent by
`pokeldn.sv.raid_scan`, in a helper process of its own): a seed's encounter, its boss up to the
scale, the score, every filter and the rewards, the work of `select`, `boss_fields`, `rewards` and
`tera_type` on the context's tables. It names a context's best seeds (or each species' best), and
`search` makes their raids with the plain Python code, so the results, their order and the ties
between seeds and contexts are the Python scan's (`tests/test_sv_raid.py` compares both).

The scan turns most seeds away after their encounter. Each encounter row's best rank is worked out
once per request: its flawless IVs at 31 wherever they can fall, its other IVs the best the IV filter
lets through, the best of its natures, and ranked by rewards the most the row gives of each item. A
seed whose row cannot beat the ranks kept so far stops there; one that passes is checked again after
its flawless IVs and after all its IVs, against the best any nature makes of them (a nature changes
a stat by a tenth, and every score grows with each stat). Ranked by rewards, the rewards are drawn
first, a draw looks only at the lottery rows that give a wanted item, and the draws stop once those
left cannot bring the first item to the kept ranks' first digit. Each request carries the ranks the
earlier ones kept (each species' with one boss per species), and only a search's first request
carries a context's tables, which the helper keeps by their digest.

A request holds 16 777 216 seeds, then as many as the helper scans in about a quarter of a second, up
to 268 435 456. A search covers up to 4 294 967 296 seeds in each context, in as many contexts as
chosen (`most_seeds`); the finder offers a hundred million, and Every seed searches all of them.
Stop at the first match answers the first raid that matches, whatever its score, instead of the best
ones (`stop_at_first`): the earliest seed of the first context that has one, the contexts searched
one after the other. Without the helper (a source checkout that has not built it), Python scans
about 22 000 seeds a second, up to a million seed and context pairs, and the finder offers 100 000.

Measured on an Apple M4 (10 cores), the helper warm:

| search | time |
|---|---|
| 10 000 000 seeds of one context (Scarlet, Paldea, 6-star, standard) | 0.02 s, 0.03 s wanting a shiny |
| 10 000 000 seeds in each of the 42 contexts | 0.51 s |
| 100 000 000 seeds in each of the 42 contexts, the finder's default | 5.2 s |
| every seed of one context | 6.1 s |
| every seed of the 42 contexts | 4 min 3 s |
| every seed of Scarlet's Paldea black crystal, two Bitter Herba Mystica then two Ability Patches ranked, one boss per species | 20.9 s |
| every seed of that crystal, wanting the Jumbo mark | 3.3 s |

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

In about 4 minutes the joiner's two directions carried 475 reliable messages on 0x80 port 0, 27979
bytes on the wire, at most 80 in one second one way. Only the host sends the NPCs' commands and the type-0x15 records.

The battle is server and client. The host's builder `0x113c8a0` (type 0x15 at `0x113c908`) copies the
action blocks, runs the round (`0x113e3d0`) and appends the server command queue it produced; the
host's AI makes the NPCs' commands, and the boss's action reaches a guest only inside a 0x15. A guest
plays the queue, and for types 0x13, 0x15, 0x17, 0x19, 0x1f, 0x23, 0x25 and 0x4d it rebuilds the body
from the host's action blocks with the same builder and compares size and bytes (`0xf5cfa4`); a
mismatch goes to `0xf5bfd4`, the receive-timeout handler. A station that hosts a battle has to produce
the queue Scarlet's own engine produces from the same state.

### Which station runs the server

The battle server is the first entry of the port-2 member list, the list every console builds from
the lobby host's Session type 6 (members at `+0xa0`, codes `+0xc0`, count `+0xc4`; composer
`0xe457cc`) and type-9 receiver `0x18b68fc`; `pokeldn.sv.port2.build_session` puts the host first.

| step | code |
|---|---|
| the raid start `0.4455` (Lua) sets the server slot to 0: `setup:f4891D27C(0)` | `0x182ca10` -> `0x2d36398`, setup `+0x94` |
| for member i it maps i to slot 0, 2, 3, 4, stores the member's code at `+0x99+slot` and, for its own code, the slot at `+0x90` | `0x1ccd15c` walks the member vector at port-2 `+0x170`; `0x2d363a0`, `0x130ea2c` |
| `0x2a1cd74` copies setup `+0x94` to `net+0x58` and `+0x90` to `net+0x5c`, once, at battle start | from `0x18915c4` |
| a console is the server when `!setup.710 && slot == net+0x58` | net vf `+0x78` = `0x2a1d994`; config `+0x2c` via `0xfa363c`, kept at server `+0x490` |
| the 0x15 checker is installed only on a console that is not the server | `0xfb0ee8` |
| a receive timeout or a failed check calls net vf `+0x70` = `0x2a1d920`; in a raid it sets `net+0xca` and `0x18e217c` sets `net+0x58` to the console's own slot (`net+0xf0`, written once at `0x2a1cda8`) | `0xf5bfd4` |

Setup `+0x710` is set only by `0x7faed0`, from the Lua binding `f3AF42713` when builder field 22 is
true; the raid start never sets it. No message names the server: member order does. A console that
loses its link to the server makes itself the server for the rest of the battle, and every console
does so independently. When the lobby host listed first stops sending, each console fights its own
battle.

The member vector is append-only and has three writers, all through `0x18b65c8` -> `0x18b68fc`:
the session block of a type 6 or 7 (`0x18b566c`, entry `(block+0x98 code, block+0x90 host
station)`, appended first), the type-6 member replay (`0x279ba2c`) and the type 9 (`0x1954bac`). A
type 9 before any block is dropped (`0x18b65e4`). Entry 0 on every console is the host its first
block names. Measured on two emulated Scarlet 4.0.0:

| what the lobby host sent | what the consoles did |
|---|---|
| a type 6 whose block host is the receiving console's own station | sent no port-2 join, Error 7 |
| port-2 type 10 (`0a b9 02 <slot> b9 01 <u64 station>`, parser `0x279bbdc`, erase `0x194562c`) naming the block host, in the lobby | left the session |
| the same type 10 after the bootstrap | "The raid has been abandoned!" |
| the same type 10 once the console reported 320173 (loaded) | each fought alone with two NPC partners |
| a member code naming an empty bootstrap participant | the battle's loading aborted (2162-0001) |
| five members, the fifth (mapped to slot 0 by the Lua, which remaps only indexes 1 to 3) a console | the lobby listed no member; after the start and the bootstrap both consoles left before any battle frame |

Bootstrap participant k belongs to the member with code k. A console that fails over runs every
other battler by its own AI: the per-slot readers are built only for a console that was the server
at battle start (`0xfa52b0`, `0xfa5314`). Its own code is the code of the first vector entry with
its own station (`0xd5f3b4`), and the Lua's slot loop (`0.4455` @1206..@1248) has no break, so the
last matching entry sets the console's slot.

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

On an emulated Scarlet 4.0.0 fighting a raid hosted with `randSeed` `D64EB3974D89705E`, the
server's random held that seed and a state equal to it advanced seven steps, with a count of 7, at
a later round; that round drew four times.

A draw adds `s0 + s1` and steps the state; the count rises by one per call, not per redraw:

| function | draw |
|---|---|
| `0x11440f0(rand, n)` | a u64 below n: `s0 + s1` masked to the bits of n − 1, redrawn while n or more; n below 2 returns 0 and draws nothing |
| `0x114da8c(rand, p)` | `(s0 + s1) & 0x7f` redrawn while 100 or more; true when below p |

Many round functions inline the step instead of calling these.

### Damage and draws per move

Measured on oracle battles of random Pokemon against standard raids (233 battles, 29 with every draw
logged). A move use draws, in this order:

| draw | when | what it decides |
|---|---|---|
| `chance(25)` | the user is paralysed | a full paralysis |
| `chance(accuracy)` | the move has an accuracy; 100 still draws | a hit |
| `below(24)`, `below(8)`, `below(2)` | a damaging move, by critical-hit stage 0, 1, 2 | a critical hit when 0 |
| `below(16)` | a damaging move | the roll r: the damage times (100 − r) / 100 |
| `chance(p)` | a secondary effect of chance p (Body Slam's 30) | the effect |

A flinch secondary against the boss draws nothing ([A move in the round queue](#a-move-in-the-round-queue)
has the rule). A stat-lowering secondary of 100 percent (Spirit Break, Bulldoze) draws `chance(0)` in
some rounds and nothing in others. Two battlers of equal speed draw `below(2)` before the first move.

A battle draws `below(100)` once before its first round. The damage is Showdown's Gen 9 formula (data
from Pokemon Showdown's `moves.json` and `typechart`) with the party record's stats and the boss
defending as its Tera type only: 921 of 1346 hits on the boss before any stat stage change fit it, and
for 137 of 140 hits with every draw logged the logged roll and critical draw give the recorded damage.
Hits that do not fit come during the boss's shield (about 0.45 of the formula), from moves with their
own rules (Body Press, Rising Voltage, multi-hit moves) or are capped at the HP left.

A boss's HP pool is its record's HP times the RaidPoint's HP coefficient over 100 ([The battle
bootstrap](#the-battle-bootstrap)): of the oracle battles won, 78 at one star, 84 at two, 125 at three and 35 at
four ended after exactly 5, 5, 8 and 12 times the record's HP in `0x37 (2, 2, damage)`; the others took
less, through the shield and moves with their own rules.

### A move in the round queue

In a round's queue a battler's move is one run of commands. A battler's client position is 0 to 3 for
battlers 1, 3, 4 and 5 and 4 for the boss; A is the user, T the target, M the move, `type` the move's
type index and `cat` its category (1 physical, 2 special). Measured on oracle rounds where a player's
move hits the boss and the boss's reply hits a player:

| command | meaning |
|---|---|
| `0x05 (A, 0, pp)` | a player's move begins, spending pp (2 against a target with Pressure, else 1); the boss's has none |
| `0x07 (A, 0)` | the move is used |
| `0xc9 (A, 0, M, T's position, 0)` | the move and its target |
| `0x7b (M, n, A)` | n counts the rounds before this one |
| six `0xcf` groups of zeros | 20, 5, 5, 5, 19 and 20 bytes |
| `0x7e (0, ...)`, `0x7e (1, 0, 0, 0, 0, 0)`, `0x7e (2, e, e, e, e, e)` | the first: 1 at T's position + 1; the third: an effectiveness code per position, 7 for none |
| `0x8b (A's position, T's position, M, type, 0, 0, 1, tera, 0, 0)` | the hit; `tera` is 1 when the boss uses a damaging move of its Tera type (448 of 448 such hits), else 0 |
| `0x37 (T, 2, damage)`, `0x37 (T, 5, 1)`, `0x02 (T, A, damage, 3)` | the damage |
| `0xd0` with bytes `T, e` | e is the effectiveness: 7 neutral, 6 not very effective, 8 super effective |
| `0x8e (1, 1, M)`; `0x8e (1, 3, M)` and `0xca (A, 575, 0xffff0000)` when not very effective; `0x8e (1, 2, M)` and `0xca (A, 574, 0xffff0000)` when super effective | the effectiveness message |
| `0x20 (A, 24)` | only for a super-effective hit |
| `0x42 (T, A, A's position, type, cat, M, damage)` | the hit's record |
| the drain, when the move drains and its user is below full HP | `0xa7 (T, 51)`, `0x03 (A, heal)`, `0x9a (A, heal)`, `0xcb (A, 290, T)`; heal is damage times the drain fraction, rounded half up, capped at the HP the user lacks |
| the secondary effect, if any | for example a paralysis: `0x13`, `0x90`, `0xa7`, `0xcb (2, 92, T)` |
| `0xd1` with bytes `01 00`, `0x2e (2, A − 1)` | |
| `0x85 (7, damage)` | only for damage to the boss |
| `0x7c ()`, `0x08 (A, 0)`, `0x1d (A, T's position, type, 1, 0, M, M)`, `0x5b (A, M)` twice, `0x1e (A, 0)` | the move ends |

A round ends with `0xb2 (0)`, `0x37 (b, 7, 1)` for each battler that moved, `0x75 (3, n)`, `0xc5 (1)`,
`0x43 (b)` for each battler in speed order (party record speed, the boss among them), `0x23 (b)` for
each of the round's actors in id order, or all five in the battle's first round, and `0x2d (0)`;
`0x75 (3, n)` counts the rounds so far, this one included.

A hit that knocks the boss out wins the battle. After its `0x42` come `0x49 (2, A, M)`, `0x09 (A, 0)`,
`0x37 (2, 1, 1)`, `0xcb (2, 0, 2)`, `0x94 (2, 0)`, `0x37 (2, 8, 1)`, `0x5f (2)`, `0x62 (2)`, `0x6c (2)`,
`0x5d (2)`, `0x41 (b, 2)` for each player in id order, `0x33 (2, k)` for k 0 to 13 except 8, `0x80 (2)`,
`0x29 (2)` and `0x38 (A)`, then the move's usual end. Nobody moves after it, and the round ends with
only the `0x43` of the battlers left standing, the `0x23` list and `0x2d (0)`. The `0x85 (7, damage)`
and the damage commands carry the HP the boss had left.

The prefix starts with `0xb5 (0)`, then runs `0x51 (b, 1)` once for the round's actors in id order and
once in the order they move; in the second run a battler with Stall (ability 100) moves last and
carries `0x51 (b, 0)`. A battler whose chosen move registers its own handler adds `0x5a (b, M, speed)`
and `0x5b (b, M)` after each run, in that run's order, then twice more in move order. Before each
battler after the first moves, every such battler repeats the pair once more, and a mover whose move
registers a handler adds `0x5a (b, M, 0x72000 + speed)` just before its `0x05`. Which moves register
a handler is measured by using each move in an oracle battle and watching for `0x5a`: 347 of the 631
moves seen used register one (Facade and Body Slam among them, Night Slash not).

The boss is Terastallized from the start: a damaging move of its Tera type under 60 base power, with
no priority and a single hit, hits at 60, Gen 9's Tera rule (a Smoliv's Tera Normal Tackle did 4
where 40 base power gives 2). A move's secondaries each draw `chance(n)` in Showdown's order, except
a flinch against the boss, which draws nothing: a player's Ice Fang on the boss draws only its
freeze chance (a freeze shows as `0x13 (2, 3, 0, 1, 4)` with messages 97 and 98, and the boss draws
`chance(20)` to thaw before it moves), the boss's Ice Fang on a player draws both. A hit that knocks
the boss out draws `chance(0)` first, with or without a secondary.

Built this way, from Showdown's move data and the Gen 9 damage formula, 56 of 554 oracle battles'
first rounds equal the oracle's byte for byte and none differ; the others hold something refused.
Chained from the start body through the boss's knockout, 20 whole battles equal the oracle's in
every round. Served end to end against the same scripted console, a server built this way sent
the console every frame the oracle server sent, in order and at the same frame, in 19 of 19 battles
both served (the twentieth the oracle server failed).
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

A round's block therefore holds one slot's actions. The 4 unwritten bytes of each action and bytes
0x235..0x237 come from the poster's stack and reach the type-0x15 body unchanged; the round reads
none of them. Each type-0x15 record between two emulated Scarlet 4.0.0 equals, outside those bytes,
the block built from the type-6 command of its acting slot (10 of 10 records whose command was on the
wire; the boss's own slot-1 blocks have none: [The boss's actions](#the-bosss-actions)). The rounds of four emulated sessions,
run from their actions alone, give the console's 20576-byte bodies outside those bytes.

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

Every queue starts with command 0xb5. A round in which slot 2 used Hex (move 506) on the boss
carried `0x5a (3, 506, 212)`, `0x5b (3, 506)` and `0xc9 (3, 0, 506, 4, 0)`. Every queue recorded
from emulated Scarlet 4.0.0 servers and the type-0x15 records between two emulated consoles, 20 in
all, decodes to its last byte and encodes back to the same bytes.
The 0xcf groups seen so far are zero-filled.

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
| Air Balloon (541) held | `0xcb (id, 137, id)`, after the battler's ability |

In 224 of 233 oracle battles the events run in the battlers' speed order (party record speed). The 9 others
involve Unnerve (127), which acts first, or speed ties. Over the same battles, 161 abilities produced no
switch-in event and, of the items Leftovers (234), Life Orb (247), 270 and Focus Sash (275), none did.

Intimidate opens with `0x25 (I)` and `0xc7 (I, 0)`, then for each foe in id order (the four players
for the boss, the boss for a player) `0x0d (F, 1, 1)`, `0x93 (F, 1, 1, 0)` and `0xcb (I, 32, F, 1,
0xffff0000)`, and closes with `0xc8 (I)`. A foe with Own Tempo answers inside it with its own
`0x25`/`0xc7`, `0xcb (F, 69, F, 0xffff0000)` and `0xc8`, and loses nothing. A foe with Defiant answers
after its drop with `0x0c (F, 1, 2)`, `0x92 (F, 1, 2, 0)` and `0xcb (F, 18, F, 0xffff0000)`. Frisk
names the first foe that holds an item with `0xcb (0, 146, I, F, item, 0xffff0000)` and each later
one with `0xca (0, 752, F, item, 0xffff0000)`; with no item among the foes it has no event. Defiant,
Hyper Cutter, Klutz, Light Metal, Moxie, Poison Touch and Wind Power have no start event. Built this
way, 420 of 554 oracle start bodies are equal and none differ.

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

None of them draws a random number: every trigger is a threshold on the boss's HP share or the time
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

Between two emulated Scarlet 4.0.0, a 4-star boss with the profile (3 Sunny Day at 80 percent time, 1 at
75 percent HP, 2 at 40 percent HP, shield at 50 percent HP or 30 percent time) gave three slot-1 rounds:
kind 4 value 0 alone (no 0x47, a 0x51 sent with it), then after a guest's attack 0x47 and kind 1 with kind
4 value 2, then 0x47 and kind 1 again. The 75 percent action ran inside the slot-0 round that crossed it.

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

After a round whose result byte is 7 (`0x16e4ff0`), the server runs, in order:

| step | code |
|---|---|
| a Pokemon joining at the end: the source `[[N+0x48]+0x138]` asked through its vf 0x90 with {N, module}; the raid's source (vtable `0x4492e58`) answers 0 | `0x16e56a0`, `0x16e59a4`, `0x2a0fb40`; ServerCommandIntrudePokeIn (`0x2017b2c`) on a yes |
| the result judged and kept in N+0x90 (u32) and N+0x94 (u8) while N+0x90 is 7 (none yet) | `0x16e5120`, `0xe7d58c`, `0xe7d570` |
| the 0x29 body at server+0x208: u16 N's own slot, u16 the outcome, u8 N+0x94 | `0xe7d4c8`, `0x166882c` |
| AddExpBattleEnd: a zeroed request block into the server and message 0x25, a round built from it; every seated slot's answer awaited | `0x18826d8` (made by `0x17b5b0c` for request hash `0x23607a0597b3a656`) |
| the exit message by setup kind +0x30: kind 0 0x29 for outcome 1, 0x2b for 0 or 2, 0x2d for 6; kind 1 0x31, 2 0x33, 3 0x2f; 0x35 for none | `0x1882b14` |
| ExitBattleEnd: that message, every answer awaited | `0x20185ac` |
| with setup +0x498 bit 0x400 and message 0x29, RaidCapture: message 0x49, every answer awaited | `0x186d680`, `0x1934808` |
| the fade-out (otherwise straight after ExitBattleEnd): message 0x35, every answer awaited, then message 0x37 and every answer | ExitFadeOut (vtable `0x4493dd8`, update `0x171d648`, made by `0x186d934`), its continuation `0x171d8b0` (update sends at `0x1598b38`) |

Nothing in the server's jobs ends the battle after 0x37: run alone, the game's server code finds its
executor empty again and its per-frame machine resumes. Result byte 8 makes the same AddExpBattleEnd, which
goes on through `0x1882e24` instead: the fade-out's maker `0x186d934` as its continuation, no exit message.
Only the builder of message 0x1d (kind 29, `0x1150adc`) writes `0xc4a4` (`0x1150f48`, from `0x288d688`),
and 0x1d is sent only by the job of update `0x185e0a4` (hash `0x287fc18d19661403`, constructor `0xe7f404`)
and by ServerCommandIntrudePokeIn (`0x20186a8`, hash `0x809e7c342dc76a3c`, posted by `0x201665c` from the
machine's vf 0x70 for event `0x0ab4bce035f3012b`). The raid's executor (`0x17b410c`) makes no job of hash
`0x287fc18d19661403`, and the event comes from `0x16a5fa0`, vf 0x90 of the source class at vtable
`0x4492bd8`, while a raid's source (vtable `0x4492e58`) answers 0; a raid reaches neither, so result byte
8 and `0x1882e24` belong to battles a Pokemon joins. The judge
`0xe7d58c` counts over every seated slot's party, by side (a slot's side by battle mode, table
`0x3c6a450`: mode 0 (0, 1, 2, 2, 2), mode 1 (0, 1, 0, 1, 2), mode 2 (0, 1, 0, 0, 0)), the able members,
the members, and with N+0x8c set the slots whose u16 at `[module+0x1b0]+0xa+2 slot` is 0 (`0xe7de94`).
The first test that decides gives the winning side:

| test | code | N+0x94 |
|---|---|---|
| with setup +0x49c bit 1: side 1 while it has an able member, else side 0 | | 0 or 1 |
| a side with no able member loses; both or neither, undecided | `0xe7d748` | 1 |
| with N+0x8c and no setup +0x710: the side with fewer empty slots | `0xe7e520` | 2 |
| setup kinds 2 and 3 only: with no able member on either side, the rule value of `[module+0x110]` | `0xe7d738`, `0xe7ecd8`, `0x2823b34` | 1 |
| then the side that lost fewer members, the larger HP share, the larger HP | `0xe7f160`, `0x282361c`, `0x28239ac`, `0x2823a5c` | 2 |

The result is 1 when the winning side is N's own slot's (N+0x95), 0 when it is the other, 2 undecided.
The outcome `0x166882c` (also kept at `[N+0x40]+0x30`) is 1 for setup kind 4, 5 with N+0x9e bit 0, the
listed slots' verdict when `[[N+0x150]+0x230]` names any (`0x16688c8`), else N+0x90 with 7 read as 1.
Between two emulated consoles the guest received 0x25 (an empty queue) 40 ms after the round that knocked
the boss out, 0x29 with the body `00 00 01 00 01 00` once every station answered 0x25, and 0x49 once every
station answered 0x29.

### The battle timer running out

At the top of every frame it runs, the per-frame machine (`0xf6d538`) reads the battle timer with the
limit N+0x8a and the i16 at [[module+0x1b0]+8] (`0xf91070`); a result of 0 or less, as a signed value,
takes the time-up branch `0xf6d830`, before the boss's list and the readers:

| step | code |
|---|---|
| the result 0 with N+0x94 = 2 kept in N, unless a result is already there (not forced) | `0xe7d570(N, 0, 2, 0)` |
| the 0x29 body at server+0x208: N's own slot, the outcome (`0x166882c`), N+0x94 | `0xe7d4c8` |
| with setup +0x499 bit 2 (a raid): ExitBattleEnd with message 0x2b posted | `0x201602c` (hash `0x2da7b4584624a364`, constructor `0x1882dbc` keeps the message at +0x78) |
| otherwise: AddExpBattleEnd with kind 0 posted | `0x16e5230` (hash `0x23607a0597b3a656`) |

The machine runs only while no job runs, so a timer that runs out during a round or a raid action is
seen once that job ends. ExitBattleEnd sends 0x2b to every station and waits for every answer; 0x2b is not
0x29, so no RaidCapture follows, and the fade-out sends 0x35 and then 0x37 ([The battle's
end](#the-battles-end)). A raid sends no 0x25 on time-up.

On the rme10 session (below) with the recorded messages up to 416.5 s, then stations that answer every odd
message but 5 and 0x37 0.1 s later and send no command, the clock run to 700 s in 10 s steps: the game's own
server code under unicorn and `Server` send every slot the same messages in the same order, byte for byte
outside the unwritten bytes. They are the boss's round of its last timed action (kind 3, 10 percent of the
time left), then 0x2b with the body `00 00 00 00 02 00` (slot 0, outcome 0, decided by 2), 0x35 and 0x37.

A raid the boss wins ends the same way. On the same session from 414.5 s, with stations that answer every
request with a command in which their Pokemon uses Growl (move 45) on the boss and the boss answers with
move 0x1cc on that Pokemon, the game's server code and `Server` sent every slot the same 1311 messages in
the same order. A player's Pokemon that faints costs the timer 75 seconds of its 300 (the i16 at
[[module+0x1b0]+8] fell to -75, -150, then -225 at 439.7 s), and at -225 the time-up branch sent 0x2b
(slot 0, outcome 0, decided by 2), 0x35 and 0x37. A slot whose Pokemon fainted goes through its reader's
sub-states ([The server's flow](#the-servers-flow)):

| message | to | what |
|---|---|---|
| 0x21 | the fainted slot alone, header only | sent once the slot has no able member; its answer 0x22 starts the reader's timer (reader+0x50, limit from `0x1ffe4e8`) |
| 0x23 | every slot, 20608 bytes | once that timer has run out (`0x2016bc8`, a kind 0x23 block whose only action is the slot's, count 1, action kind 8), built by kind 35 (`0x1153350`, as kind 37 with `0x288d734` for `0x114c390`): the member's HP restored (`0x288cde8`, vf 0x2e8 and 0x488) and command 3 (battler, HP), then the member sent back in at its position (`0x2887044`, `0x11482a0`: command 0x98, triggers 0xc, 0x16, 0x20) and its entry steps |

One revival round queued `3 (5, 277)`, `cb`, `3d (4)`, `16 (4, 0, 0, 113)`, `5e`, `61`, `6b`, `4e`,
`98 (4, 0, 0, 1)`, `20 (5, 0x12)`, `25`, `c7`, `cb`, `c8`. The test checks `Server` against the game's
messages for this battle too.

### The server's flow

On the console the steps are jobs: Wild::Setup first, ServerRequest (`0x138d178`, message 5 to one
slot), ServerCommand (`0x16e4f10`, a posted request block as a round, then its result's next step),
RaidAction, and the battle's end. Wild::Setup (`0x2a1f54c`, eleven states, jump table `0x3c61c1e`) sends
message 1, waits for every slot's answer, sends 0x11 (setup kind 4 takes `0x2017ba4` instead; a raid's setup +0x30 is kind 0, the kind that
sends 0x29 on a win, as the capture's 0x29 shows), waits for
every answer, clears what each seated slot sent (`0xe0f5f8`), sends message 3 when the 0x11 result byte is
1 (then 0x13 after its answers; that byte is the start flag [[o+0x40]+0x28], which only `0x2840fac`
sets to 1, called through `0x2840f70` from seven sites (`0x284b710`, `0x284b8f0`, `0x285c5d0`,
`0x286d480`, `0x286d784`, `0x286d9b0`, `0x28780f8`); no measured raid start set it), erases each seated slot's 3 and 4, and starts the battle timer. A per-frame machine (`0xf6d538`) steps five per-slot readers (`0xf6df44`) and the boss's
list. A reader for a player's slot on the server's side:

| reader state | when | then |
|---|---|---|
| 0 | the slot's sent entry holds none of 5, 0xd, 0xb, 0xf, 9, 7, 0x21, 3, 0x23, 0x15, 0x17, 0x19, 0x13, 0x47, 0x1f, 0x1d | a ServerRequest for the slot (`0xf70078`), state 1 |
| 0 | otherwise | each answered pair erased from both entries (`0xf6edf4` for 0x15/0x16, 0x23/0x24, 0x11/0x12, 0x13/0x14, 0x17/0x18, 0x19/0x1a, 0x1b/0x1c, 0x1d/0x1e, 0x25/0x26, 0x1f/0x20) |
| 1 | the slot was sent 5 and sent 6 | a zeroed block with the slot's command gathered in (`0xf6e6a8`, `0xf702ec` key 6, done key 5) posted as a ServerCommand, state 2 |
| 2 | the slot answered a round (0x15 / 0x16) | state 0 |

A slot is the boss's side by the table `0x3c6a45a` (0, 1, 0, 0, 0) against N+0x95; its reader only
erases answered pairs. The reader (`0xf6df44`..`0xf6edf0`) has more paths than the table: a slot that sent 4
is answered with a kind 0x13 block; on N's side in a raid it runs sub-states at reader+9 (0 asks the slot
{slot, 0x21} through an 8-byte request of hash `0x935acb1823e1803f`, `0xf6f6d8`; 3 makes a timer at
reader+0x50 with the limit `0x1ffe4e8` reads from table `0x3c69d1c`; 1 posts a kind 0x23 block once that
timer runs out, `0x2016bc8`; 2 waits for 0x23/0x24); 0xd/0xe posts a kind 0x1b block, or the request
{slot, 7} when the 0xe body's first byte is 0; 7/8, 0xb/0xc, 0xf/0x10 and a received 0xa post blocks of
kinds 0x17, 0x19, 0x15 and 0x17. A posted block's bytes +0x23c..+0x23f, after the kind, are stack.

Every frame the raid's run step `0x2d383b8(N)` steps, at `0x2d38694`, the server's incoming links
(`0xe0f040`, `0xe0fd68`, `0xe0f854` on [N+0xb0]) and then the job graph `0xfc363c(G, 1)`, G = [N+0xa8]
(0xe8 bytes, vtable `0x44ee6e8`; its +0x40 is the jobs' context, vtable `0x44ee808`):

| G+ | object | |
|---|---|---|
| 0x98 | the request factory (0x48 bytes) | a posted request is a 0x50-byte message object: a job type hash, a counter, the job's payload |
| 0xa0 | the scheduler (0x78 bytes, vtable `0x44eea68`) | posted requests in a vector at +0x40..+0x50, appended by `0x1479b10` |
| 0xa8 | the source (vtable `0x44947d8`) | vf 0x68 `0x14641ec` picks the request to start |
| 0xb0 | the per-frame machine (vtable `0x4493530`, made by `0x17e1c5c`) | vf 0x68 `0xf6d538`; +0x40 the context, +0x48 the factory, +0x50 the scheduler |
| 0xb8 | the executor (vtable `0x4493688`) | a stack of jobs (deque, count +0xa0) |

`0xfc363c(G, 1)` runs the executor alone while it holds a job. With an empty executor it runs the
machine, then the source's pick: in a raid (setup +0x498 bit 0x400) the first posted request of hash
`0x5c307d44ea569b63` (a raid action, `0xf71928`), before the module's started flag
([[module+0x1f0]+8]) the first of hash `0x2e9e7a3009002c36` (Wild::Setup, `0xf7093c`), otherwise the
first posted. The pick leaves the scheduler (`0xfc3f58`), the executor's vf 0x68 `0x17b410c` makes the
job its hash names and pushes it, and the executor runs. The executor (`0xfc38dc`) runs the top job's vf
0x68: 0 ends the frame; 2 pops it, pushes its continuation [job+0x70] when it has one, and ends the frame;
any other value runs the top job again. The machine and its readers therefore run only on frames with no
job, one posted request starts per frame, and a raid action posted after other requests starts before
them; that gives the capture's order of three commands sent as rounds after a raid action.

The machine's timed check sends its copy of the boss list as message 0x51 (`0xf71b74`) into the
incoming link of the server's own slot (`0xe0f440(server, N+0x95)`, `0xf71980`); on the next frame the
incoming-link step hands it to the machine's vf 0x78 `0x2016290`, which copies its 0x24 bytes to the
machine's boss list [+0xf8]+0x5c, and the machine posts the raid action from there. The machine's vf 0x70
`0x20162bc` takes two other messages, told apart by the u64 at their +0x40: `0x0ab4bce035f3012b` (a
0x2588-byte payload, posted as a job of `0x201665c`) and `0xde3856ecc4fe200c` (a request block of one
kind-14 action, posted as a ServerCommand).

Scarlet's own server code under unicorn on the session the engine builds
(`scratchpad/battle/timeup/gameserve.py`: `0x2d383b8` every frame at 30 frames a second, the stations'
messages in the relayed order at their capture times) sends the guest the console's 24 frames, each
byte for byte outside the header's and the request blocks' unwritten bytes. Without the incoming-link
step the 0x51 copy never reaches the boss list and the 80 percent action never fires.

`Server`, a Python port of this flow over a built session, runs each frame as the server's part of the
run step (`0xe0f040`, `0xe0fd68`, `0xe0f854`, `0xfc363c(G, 1)`, and `0x2898350` when that step moved), at
30 frames a second on
the machine's clock up to the time of each message it is given, and for one frame period after each.
No frame can be skipped as idle: a reader waiting on a fainted slot's timer makes the machine report a
move every frame, and each such frame queues a message 0x46 on the server's own link. Under unicorn the
game's own code for all 216 ported functions leaves the same pages after every event as the port over the
recorded battle, the timer running out, the victory's end and a battle the boss wins (below).

The host relays every message its server receives, its local clients' and the guest's alike, to the
guest through one queue (address x 3, one frame every 0.05 to 0.15 s, the guest's own messages
included), so that queue's order is the order the server read them in: a guest's answer sent 0.5 s
before a local client's can reach the server after it. From the emulated host's own bootstrap (message
0x2f in the capture) and the stations' messages in that relayed order, each at its capture time on the
machine's clock, the server sends the guest all 24 of the console's frames in the same order: type 1,
0x11, four requests, 13 rounds of which three are the boss's, two 0x47, then 0x25, 0x29 and 0x49. Every
one is byte for byte the console's outside the header's unwritten bytes and the request blocks'
([Actions](#actions)); the boss's timed action fires at the console's frame from the timer's own start.
Under unicorn, the game's own code for every lifted step leaves the same pages through the whole served
battle.

### Reproducing a round

A round is replayed exactly under unicorn from an emulated console halted at the builder
`0x113c8a0` with type 0x15: memory comes from the GDB stub one page at a time as the replay first
touches it, the thread-local page behind `tpidrro_el0` is a stand-in whose `+0x1f8` names a fake
thread, and SVCs 0x10, 0x11, 0x12, 0x1a, 0x1b, 0x1d and 0x1e return 0. Eleven replayed rounds
equalled, byte for byte, the bodies the console then built itself; a round touched 159 to 353 pages.

A Python port of the server runs it, one function per game function, keyed by its
offset from main. The builder `0x113c8a0` runs in Python for message kinds 1, 5, 17 and 21: the
round driver `0x113e3d0` with move selection, damage `0xf7c344`, fainting `0x1144df8` and end of
turn `0x114a094`, and the battle start `0x113dca8` with its send-out, item, ability and entry
handlers. Over 86 halted consoles (49 rounds, 5 battle starts) the port leaves the same body and
the same memory pages as the game's own code, with no call handed back to it. The heap it allocates
from is the SDK's `nn::mem::StandardAllocator` over a thread cache, ported with the cache's creation
and its TinyMT32 key (`0x525f448`). The battle-state build steps `0x2891748`, `0x2892ac0`,
`0x2d381a4` and `0x2892dd4` also run in Python, entry included, and leave the same pages as the
game. `__cxa_guard_acquire` (`0x53c49a0`) returns 1 and sets byte 1
of the guard to 2 when neither byte 0 nor byte 1 is set.

A Hex round reads 16838 bytes it did not write: 1496 from the static image, 5372 from the
command-format map and 2926 from the server object (both made by `0x2d381a4`), 2414 from the
battlers and their Pokemon (made by `0x2892ac0`), 1756 from the main module family (made by
`0x2891748`), 2278 from the data tables and 576 from the round's action blocks.

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
+0xd0 (the record for key 0). A node is {next, hash = key, key, record pointer into the loaded
file}; +0x30 is the file resource (FNV hash +0x48, path +0x50). The item array (filled by
`0x1821674`) holds 0x18-byte entries from +0x28: u32 index, u32 0, u64 hash, u16 item, 6 zero
bytes; entry i is file record i, and its hash is the u64 at main `0x3c61260 + 8 * index`. The files
come out of `arc/data.trpfs` (`tools/switch/trpfs_read.py`; Oodle entries through the game's own
`OodleLZ_Decompress` at `0xcc8750`), and every byte of them held by 97 halted consoles equals the
extracted file.

The battle start also runs in the port with no halted console. From the static
image and the romfs alone, the
port builds the game heap, the "Application" counted allocator
(`0x3b78d3d`, limit 0xa0000000, over the GlobalHeap allocator 0x4763918), the weak-handle table
(`0x165dd08`) and the five data tables (personal `0x164498c`, id-hash `0x1730f6c`). The session and
the server object N then come from the game's own creators (below), with the raid start's setup
fields from the bootstrap. After that, N's start states run the four build steps, and the builder
with type 0x11 runs. The battle-start bodies of five sessions (268, 345, 328, 422 and
268 bytes) equal the console's, and so do nine later rounds' 20576-byte bodies, each round built from
its acting slot's two actions ([Actions](#actions)), outside the request block's unwritten stack bytes. A changed battle seed leaves the start body unchanged
and changes 123 bytes of a round. Neither heap addresses nor weak-handle ids reach a body: the
console's ids are 0x1b5xx of generation 3, and the port's are 0..0x58 with all its objects at other
addresses.

The session is made in four steps:

| step | code | what it makes |
|---|---|---|
| boot | `0x168ca58` -> `0x168cb20`, constructor `0x168cc48` | the session manager `[[0x46d38e0]]` (0xc0 bytes, vtable 0x4483f68): sessions by id at +0x28, a mutex at +0x90, the next id u32 +0xb0, and at +0xb8 the communication holder (0x48 bytes, vtable 0x4492338) of a 0x7660-byte object (vtable 0x4492468, constructor `0x168d59c`: port 0x7b, 16 entries of 12 bytes, 32 of 0x18) |
| raid start | `0x159dba0` -> `0x159dc10`, constructor `0x159e860` | the session S (0x110 bytes, vtable 0x4484008) under the next id: its job at +0x40, the battle setup (0x730 bytes, vtable 0x44ff070, constructor `0x159f8f0`, reset `0x159fe68`) at +0xe0, a 0x288-byte object at +0xe8 |
| raid start | the setup's Lua bindings, setters `0x7fa0cc`..`0x7faf24` | the setup's battle fields, below |
| battle start | `0x1891274(id)` -> `0x1891440` -> `0x18915c4(S, mgr + 0xb8, ...)` | N+0x48 (vtable 0x44fef38) with five 0x3e8-byte and five 0xb70-byte counted resources under keys 0..4, the named-parameter table at +0x148, the election object (vtable 0x4492a48) at +0x108, then N (`0x16af068`, constructor `0x16b0fb8`) in S+0x48 |

N's start states `0x1269824` follow: state 0 copies the setup's time limits (+0x48a..) to N+0x8a,
takes the election object into N+0x138 and [N+0x48]+0x140 into N+0x190, runs the server build
`0x2891748`, seeds the random holder (N+0x1a0) with setup+0x718 (`0x281c260`, which draws once), sets
N+0x30 to that seed, makes the 6 x 5 command pairs of N+0x120 (`0x132ecfc`) and gives [N+0x110] the
u32 setup+0x2c with N+0x120 and the manager's communication holder (`0x169ffa0`). State 2 picks the
step machine by mode (`0x2d380a4` for a raid), and state 3 runs it: its state 0 sets the format bytes
N+0x98.. by the rule and N+0x95, then the steps `0x2892ac0`, `0x2d381a4` and `0x2892dd4`.

The 29 named parameters are code: `0x146496c` stores one u32 per 0x10-byte entry of main
`0x3c60f80` (the name hash, then the same value at +8), in table order.

The raid start writes the setup from Lua (0.4455 -> 0.4893 -> 0.4945) through the setup's bindings.
These fields held the same values in four consoles' setups: u32 +0x2c 10003 (`fD8E195CA`, so the
0x2713 the builders read at [N+0x110]+0x40), u32 +0x34 mode 2, +0x8c 1, +0x8d rule 5, u32 +0x90 the
console's slot 2, u32 +0x94 the server slot 0, the member codes +0x99.. (0, 0xff, 1, 0xff, 0xff),
+0x488 and +0x489 1, +0x498 0x400, u32 +0x4b0 12000, u32 +0x4b4 400, +0x4dd and +0x4df 1, u32 +0x4ec 0,
+0x706 1, +0x714 8, and per participant six 0x1c-byte entries from +0x18 with u16 +0x10 30 (26 for
the boss) and u8 +0xd 1 (the host's entries 1 to 5, the guest's 0 to 5). The
bootstrap gives the seed (+0x718), the time limits (+0x48a, +0x48c, +0x48e), the boss's action profile
(+0x514) and the party holders (+0xa0..). Under unicorn the game's own code makes the same manager, S,
N+0x48, N and state 0's writes from these fields as the port, except bytes the game copies from stack
padding.

Four parts stay outside: S's job (`0x159f018`; its constructor needs the engine's job scheduler,
and no battle code reads S+0x40), the job graph links (`0x1193e44`, `0x11fd13c`), the resource
system (setup+0x720 through `0x1ffbb68`, the loader N+0x1a8 through `0x1802edc` and `0x1929dc4`,
which state 1 waits for), and the Pia network manager `[[0x46d6ca0]]` that gives the election
object its station ids.

The data system's init `0x1641afc` runs `0x1643a48` (personal, growth), `0x1641cf0` (moves) and
`0x1641d78` (abilities). Each table is created from the allocator, reset into its static (`0x1643e68`)
and appended through `0xf0ba9c` to the registry at 0x4763a18 (count u32 0x4765a18, at most 0x400).
Inserting a file's records in file order, after reserving their count, gives the console's node list.
The static image and the five tables come from the player's own dump:
main and the SDK from the v4.0.0 update's ExeFS (main's build id
`421c5411b487eb4d049dd065fec9547773e8e598`), each NSO's segments at their memory offsets with .bss, RELATIVE relocations at main
`0x8504000` and SDK main + `0x4e6d000`, then the GLOB_DAT, JUMP_SLOT and ABS64 slots bound to the
first module exporting the symbol, main before the SDK; the tables from the update's RomFS over the
base game's (`arc/data.trpfs`, Oodle through `0xcc8750`). Reading them takes 3 s on an M4; building
the session and N's start states 2.4 s.

A weak-handle entry is 0x20 bytes: u64 id (u32 index | u32 generation << 32), +8 the resolved value,
+0x10 the object, u16 +0x18 weak count, u16 +0x1a strong count, u32 +0x1c state (-1 freed, -2 live).
Blocks hold 0x400 entries (`0xc1adec`); freed ids go to a `deque<u32>` grown by `0xb44724`.

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

Against a retail host the guest appeared in the lobby under the trainer name, became ready and let
the host start; its Pokemon stayed in the battle.

## Unresolved

- What the `chance(0)` draws before some stat-drop secondaries stand for, when the target is not
  knocked out.
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

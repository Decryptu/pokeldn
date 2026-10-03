---
title: The Mystery Gift menu
parent: Sword and Shield
nav_order: 4
---

# The local-wireless branch of the Mystery Gift menu

Sword and Shield's Mystery Gift menu receives Wonder Cards over local wireless: a distributor
advertises an LDN network whose advertise data carries the card in fragments. Addresses are Shield
1.3.2's `main` unless marked Sword; on-air behaviour is measured against retail consoles.

## The menu

The receive-method chooser `StateSelectReceiveDataBase` has one subclass per menu button
(`L_mystery_top_btn_00` .. `_04`):

| state | method |
|---|---|
| `StateSelectReceiveDataInternet` | over the network |
| `StateSelectReceiveDataSerial` | a serial code or password |
| `StateSelectReceiveDataLocal` | local wireless |
| `StateSelectReceiveDataFromBall` | the Poke Ball Plus |
| `StateSelectReceiveDataRankMatch` | ranked-battle rewards |

The receive states are `StateReceiveBase`, `StateReceiveInternet`, `StateReceiveSerial`,
`StateReceiveLocal` (`0x01004938`, whose own code references only its progress-bar layout),
`StateReceiveFromBall`, `StateReceiveRankMatch`, `StateReceiveNews` and `StateReceiveComplete`. The
play-record keys `fushigi_net`, `fushigi_serial` and `fushigi_p2p` count receipts per channel, beside
`yy_battle_single_p2p` / `_net`.

`/bin/message/French/common/mystery.dat` in the base RomFS:

| line | text |
|---|---|
| 9 | `Recherche de cadeau en cours...` |
| 11 | `Aucun cadeau n'a été trouvé.` |
| 39 | `Connexion à Internet activée.` |
| 42 | `Communication sans fil locale activée.` |
| 63 | `Via Internet` |
| 64 | `Via un code ou mot de passe` |
| 65 | `Voir vos Cadeaux Mystère` |
| 69 | `Via communication sans fil locale` |
| 72-75 | the top menu: `Recevoir un Cadeau Mystère`, the Wild Area news, the Poké Ball Plus, the Battle Stadium rewards |

### The app's state machine

The dispatcher `0x00FE6F80` reads a request object at `app+0x718`: a ready flag at `+0x60`, the next
state id at `+0x64`. With the flag set and the id at most 16 it jumps through `0x020641A4` and builds
that state. `SetNextState(id)` is `0x00FF0DE0`, with 63 call sites.

| id | state | id | state |
|---|---|---|---|
| 0 | TopMenu | 9 | SelectReceiveDataSerial |
| 1 | ReceiveMenu | 10 | SelectReceiveDataRankMatch |
| 2 | ReceiveLocal | 11 | SelectReceiveDataFromBall |
| 3 | ReceiveInternet | 12 | ConfirmGift |
| 4 | ReceiveSerial | 13 | ReceiveNews |
| 5 | ReceiveRankMatch | 14 | ReceiveComplete |
| 6 | ReceiveFromBall | 15 | ConnectPalma |
| 7 | SelectReceiveDataLocal | 16 | (default, TopMenu) |
| 8 | SelectReceiveDataInternet | | |

Local wireless is state 2, the search, then 7, the pick from what a distributor offers. What advances
2 to 7 is unread; `StateReceiveLocal` sets no next state itself. `0x00FE700C` is `mov w8, w21`, the
dispatcher's jump-table index; patching it to `mov w8, #N` forces state N. Forced state 7 draws an
empty list and touches the network in no way (no `Connect`, `OpenStation` or session creation, no
change to the maximum, the registration table or the advertisement byte, also over 100 s seated with
the maximum patched), so its list is filled before it is entered.

The class's primary vtable is `0x025737C8`; its group base `0x025737B8` is held only in
`main+0x2624698`, and the constructor `0x00FE5D60` has no caller (the applet framework builds the app
through a vtable). Nothing in `main` points at the app; find it by scanning the heap for the vtable.
The image has no Mystery Gift protocol-buffer module: every `.pb.cc` belongs to `gflnet3`'s p2p
framework or to trade, the three battle modules, the raid dens, the underground, the camp,
`comp_organize` or `btl_spot`.

## The gift screen's network

On the local-wireless screen the console advertises its always-on local-play network: local
communication id `0x0100ABF008968000` (both titles), version 4, scene id 65535 (60001 on the link
trade), accept policy ALL, `NodeCountMax` 2, 384 bytes of advertise data, password CRC zero. The game
creates that access point once, some seconds after loading (16 to 31 s measured); entering or leaving
Mystery Gift makes no
LDN call. The gift screen only sets its advertise data and arms the Pia join filter.

On the screen the game calls `nn::ldn::Scan` about forty times a minute (33 in a 40 s IPC trace),
interleaved with `SetAdvertiseData` and `GetNetworkInfo`, never `Connect` or `CreateNetwork`. The
scan is passive at the 802.11 layer. Its filter names only the local communication id and the network
type; `SessionId` and `SceneId` are unfiltered.

Monitor captures, the console hosting on channel 6:

| channel | beacons from it | LDN advertisement action frames | probe requests |
|---|---|---|---|
| 1 | 0 | 153 in 90 s | 0 |
| 6 | 339 in 70 s | 435 in 70 s | 0 |
| 11 | 0 | 95 in 90 s | 0 |

### The mode byte

`session_config+0x70` is the local-play mode. `0x01096730` maps it to a Pia scene id and participant
count through the jump table `0x02066C14`; `0x010961a8` maps it to the advertise-data byte `0x97`
(advertisement `0xAF`; the game's data starts at `0x18`) through `0x02066C40`:

| mode | scene id | participants | advertise data `0x97` |
|---|---|---|---|
| 0 | none, the creator returns false at `0x01096764` | | 0xFF |
| 1 | 60021 | 2 | 0x01 |
| 2 | 60001 | 2 | 0x0D |
| 3 | 60002 | 2 | 0x0E |
| 4 | 60003 | 2 | 0x0F |
| 5 | 60004 | 4 | 0x10 |
| 6 | 60005 | 2 | 0x1E |

The link trade is mode 2 (0x0D measured); the gift screen runs mode 0 (0xFF measured), which creates
no session. Entering the app reads the mode (`0x01096d20`), saves it at `app+0xFE8` and sets 0
(`0x01022f08`); leaving restores it (`0x01023198`). The byte stays `0xFF` across idling, leaving and
re-entering. A Max Raid host advertises `0x11`, which is not in the table.

Across five trade and four gift advertisements from one console, the only other byte that differs by
screen is `0xB9` (0x00 gift, 0xAA trade), meaning unread; the rest is fixed or random per session.
The LDN `SceneId` reads 60001 on a scanned Link Trade network and 65535 on the gift screen
([Taking a seat](swsh_session.md#taking-a-seat)).

## The Pia mesh on the gift screen

The mesh on this screen admits no joiner, and a station seated in it by force receives nothing; the
card uses [the beacon transport](#the-card-travels-in-beacon-advertise-data).

A joiner completes the station handshake on 0x14 (the console's connection request, a result-0
response, its type-5 ack, its 840-byte type-2 station record) and the mesh join request on 0x18 is
refused:

    02 00 ff ff 01        JOIN_RESPONSE, refused, reason 1

The same join against the link trade draws a 148-byte response. Nothing follows on
0x58, 0x7C or 0x80. Held with no join sent, the console sends nothing after the handshake but its
update session, which lists the joiner as seat 1 with `allow_participating` set.

`ProcessJoinRequestJob` runs `InitialStep`, `CheckApprovalJoin`, `SendJoinRefused`,
`SendJoinResponse`, `WaitResponseAck` and `JoinSucceeded`. Reason 1 comes only from the application
callback; the transport check gives the others.

| | Sword | Shield |
|---|---|---|
| state-name strings | `0x03ad0f4e`..`0x03ad1010` | |
| `CheckApprovalJoin` | `0x01553d20` | `0x017cc450` |
| reason-1 store | `0x01553d58 strb w9, [x19, #0xbc]` | `0x017cc59c strb w9, [x19, #0xba]` |
| `MeshProtocol` global | `0x04c4db60` | |
| Pia trampoline at `MeshProtocol+0x60` | `0x0157fcfc`, global `0x04c4b848` | `0x018414b0`, global `0x02616a30` |
| trampoline installed by | `0x0171a0b4`, from slot `0x04c513f8` | |
| `SendJoinRefused` | `0x01553d80`; `0x0154cd00` writes `0xFFFF0002`, then the reason at offset 4 | |
| transport check | `0x0154806c`: `0xFF`, or reason 0, 2, 4, 5 | `0x017bb2e0` |

    0x01553cc0  ldr  x8, [x8, #0x60]      ; the approval callback (Sword)
    0x01553cc4  cbz  x8, #0x1553d34       ; no callback installed -> accept
    0x01553d2c  blr  x8
    0x01553d30  tbz  w0, #0, #0x1553d4c   ; bit 0 clear -> refuse
    0x01553d54  mov  w9, #1

    0x018414b0  adrp x8, #0x2616000 ; ldr x8, [x8, #0xa30] ; ldr x8, [x8]    (Shield)
    0x018414bc  ldr  x1, [x8, #0xb0]
    0x018414c0  cbz  x1, #0x18414c8      ; null -> mov w0, #1 ; ret
    0x018414c4  br   x1

The trampoline approves when `+0xb0` of its object is null and otherwise tail-calls it. The game
writes that field with `0x01841490` (`str x1, [x0, #0xb0]`), called at `0x006b47b0` with the
filter `0x006b41c0` from slot `0x02616a38`, and clears it with `0x018414a0` (`str xzr`), called at
`0x006b5340`; both sites are reached from the mode switch `0x006a9af0`.

### The join filter 0x006b41c0

`manager` is `[0x02610000 + 0x4b0]` and `session` (the game session) is `[manager+0x58]`. The filter
runs four gates in order; the values are read live on the search screen:

| order | site | test | live value | verdict |
|---|---|---|---|---|
| 1 | `0x006b4204` | block list enabled (`manager+0x21C`) and non-empty (`+0x1C0`, 16-byte entries walked by `0x006be4a0`) | enabled, empty | passes |
| 2 | `0x006b8260` in `0x006b8230` | Pia station count `pia_obj+0x1A8` below `session+0x1F0`, unsigned `b.lo` | count 1, max 0 | refuses |
| 3 | `0x006b827c` | recruiting predicate, `session` vtable `+0xB0` = `0x006ccb00` (`ldrb w0, [x0, #0x4f5]; ret`); non-zero walks the allow list at `session+0x4c0`, count `+0x4c8` (`0x006b8290`) | flag 0 | approves |
| 4 | `0x006b4248` | `cbz` on the halfword at identity `+0x10`; else it is looked up in `[manager+0x2b0]` (count `+0x2b8`) and compared with `[manager+0x220]` | 0 for any IPv4 station | approves |

The allow-list flag `session+0x4f5` is set by `0x006b86c4` and `0x006cc7bc` and cleared at
`0x006ca848`, just before `LdnCreateSessionSetting` is built at `0x006ca86c`. Entries are appended via
`0x006b5c80` -> `0x006b9920` and emptied via `0x006b5c70` -> `0x006b9910`.

The identity is built by `0x0177b7b0` and filled by `0x017b1bd0`, which copies 32 bytes from `+0x10`
of the joiner's mesh station-location entry (the one whose `+0x448` is the station and `+0x440` is
3):

    0x017b1c50  add x1, x23, #0x10 ; mov w2, #0x20 ; mov x0, x20 ; bl 0x18fde50

`InetAddress` (deserializer `0x01767a10`) has a zero-filled 16-byte address field at `+0x08` holding a
big-endian IPv4 unless the size byte is 0x12, and the port at `+0x18`. A location keeps its public
address at `+0x00` and its private one at `+0x28`, so the identity lies in the public address and
identity `+0x10` is address byte 8, zero for IPv4; the lists the callback walks are keyed on the
joiner's address. The version-4 location deserializer (`0x0185eff8` onward) stores the relay port at
`+0x60`, constant id `+0x68`, variable id `+0x70`, service variable id `+0x74` and nat quad
`+0x78`..`+0x7b`, outside the copied window. The constant id `0x1249a221d8580000` is refused on the
gift scene and accepted on the trade scene.

The maximum `session+0x1F0` is written only by `0x006b9900` (`str w1, [x0, #0x1f0]`), reached through
the uncalled thunk `0x006b5c00` and the wrapper `0x0110e5e0`, whose two callers `0x00bd9b30` and
`0x01031c74` (`SetMax(GetCount())`) are the raid-den and rental-multi matching paths. Read live in one
running game it is 0 on the gift screen, 2 hosting a link trade and 4 hosting a Max Raid, with the
same filter armed in all three. The raid host advertises `NodeCountMax` 4; the gift screen advertises
2 over a Pia maximum of 0.

`game_session+0x3F8` is 1 on the gift screen and 0 on both accepting sessions. `+0x365`, `+0x33D`
and advertisement `+0xF9` keep their raid values after a raid, so they are mode residue. `manager` is
byte-identical between the gift screen and a trade host.

### The transport check

`0x017bb2e0` runs in `CheckApprovalJoin` before the callback and returns `0xFF` or the reason byte,
sent unchanged:

    0x017bb358  bl   0x017bab70        the live station count
    0x017bb35c  ldrh w9, [x19, #0xa8]  the maximum
    0x017bb368  b.hs 0x017bb380        count >= max, reason 0
    0x017bb370  bl   0x017bb5a0        the index of the first free station slot
    0x017bb378  cmp  w8, #0xfd         no free slot, reason 0

Its object is `read_u64(read_u64(main + 0x0262F7B0))`, distinct from `pia_obj` (`main + 0x02616A30`)
and `game_session`.

| field | width | what it holds |
|---|---|---|
| `+0xA8` | u16 | the maximum station count |
| `+0xAA` | u8 | an enable byte; zero returns 2 before any other test |
| `+0xAB` | u8 | selects which bitmask word the count reads |
| `+0xAC` | u8 | how many bits of the bitmask the count walks |
| `+0xC4` | u32 | the occupancy bitmask, read when `[0xAC] == [0xAB]` |
| `+0xC8` | u32 | the occupancy bitmask otherwise, the only one the free-slot search reads |

The count is 1 plus one per set bit (`0x017bad94`); the free-slot search returns the first clear bit,
or `0xFD`. Live on the emulator's link-trade screen, idle and across 49 attempts: max 8, enable 1,
sel 0, bits 0, `+0xC4` 0, `+0xC8` 1, so the first two tests pass. Three more exits return 0:

| site | the test |
|---|---|
| `0x017bb380` | `count >= max`, or the free-slot search returns `0xFD`; measured passing |
| `0x017bb498` | the table at `mesh_obj+0x370`: its size against a u16 at `read_u64(main + 0x02616710) + 0x70`, then against its capacity at `table+0x48`; a joiner already in the table skips both (`0x017bb41c`) |
| `0x017bb4d4` | the byte at `mesh_obj+0x132`, set by the handler at `mesh_obj+0x120` on a type-0x18 event and cleared as read |

It returns 2 when `+0xAA` is zero or a preliminary predicate holds, and 4 when `mesh_obj+0x131` is set
by the type-0x19 event.

### With a station seated

- Writing 8 to `game_session+0x1F0` on the search screen admits the join at once (148-byte response,
  station count 1 to 2); writing 0 brings reason 1 back.
- On the emulator, with `+0x1F0` and `+0x1F4` patched to 2, the join drew `02 00 ff ff 00` (reason 0,
  the transport check's short form), the same five bytes a link-trade host there answers with. Every
  packet authenticates.
- Once an LDN node joins, the console broadcasts a Local Protocol update session about six times a
  second listing it as seat 1, and none with no node. One ack stops it; unacked
  (`--no-ack-update`) it continues. Trap: the emulator's wildcard
  socket on 12345 can take another listener's broadcasts; observe updates with an external capture.
- The only flows between the nodes are Pia on 12345 and ldn_mitm's control channel on 11452 (every
  port captured, 48,123 UDP ports listened on).
- Seated, the scene sends RTT probes, reliable-window opens on two ports and mesh updates, and no
  application payload; nothing opens on 0x84. It acks pings on 0x7C in sequence.
- A 0x2D0 record behind the trade driver's 4-byte header (`u16 id, u8 disc, u8 0`), sent on 0x7C and
  0x80, ports 0 and 1, is acked and never reaches the receive job.
- Advertisements built from the console's own sessions, six variants and scene ids 60001..60021, are
  returned by its scan and filed at `pia_obj+0x3C0`, and none draws a `Connect`, an `OpenStation`, an
  accept-policy call, or a change to the maximum or `+0x3F8`.

## The receive job and the importer

The gfl net manager is `read_u64(read_u64(main+0x0261CBA8))` (vtable `0x025819A0`); a null global is
the no-session guard on every send stub. It has no entry array at `+0xD0`/`+0xD8`. Entering the
local-wireless case, `StateReceiveLocal`'s driver `0x01004C80` (a case machine on `state+0x2A0`)
builds a receive job through `0x010B7100` (ctor `0x010B73E0`, vtable group `0x0257DD88`, poll
`0x010B74D0`), links it at `manager+0x68`, and installs a receive delegate at `state+0xB0`
(`0x0100504C` group).

The job holds the data sink at `job+0x60` (target `0x01005BC0`), a progress callback at `job+0xE0`
(`0x01005C70`) and its message source, the session object at `job+0x08` (vtable `0x0250DAE0`). It
appears when the search screen opens and is freed when it closes. Trap: re-entering the screen
rebuilds the job and the sink's object at new addresses.

The sink tail-calls `0x00FF0E00` -> `0x00FF1FB0` -> `0x00FF2170`, the importer. The importer refuses
a body that is not a whole number of 0x2D0-byte records (720 bytes, PKHeX's Gen 8 Wonder Card size;
the app also allocates a 0x2D0 object at `0x00feba7c`):

    0x00ff22e4  umulh x8, x21, x8        ; x21 = the length
    0x00ff22e8  lsr   x28, x8, #7        ; x28 = length / 0x2d0, the record COUNT
    0x00ff22ec  mov   w8, #0x2d0
    0x00ff22f0  msub  x8, x28, x8, x21   ; the remainder
    0x00ff22f4  cbnz  x8, #0xff272c      ; not a whole number of records -> refuse

Each record passes the checks of [What a record must carry](#what-a-record-must-carry) at
`0x00FF2354`, is filtered through `0x01449820` and materialised by `0x00FF3EC0`. With nothing
received, forcing `StateConfirmGift` (12) faults on a null card (`0x015C9230 ldrb w8,[x0,#0x1AC]`,
from the controller `0x015BFFA0` via app `0x00FFA458`) and `StateReceiveComplete` (14) draws an empty
panel.

The importer's second argument is the route. It passes unchanged through `0x00FF0E00` and
`0x00FF1FB0` to `0x00FF2170`, which keeps it at `[sp+0x35c]`; it becomes card `+0x64`
(`0x00FF3F5C`) and, as `route != 0`, header `+0x0E` (`0x010B5FAC`). Each caller is a lambda in slot
16 of a receive state's vtable:

| state | route | call sites |
|---|---|---|
| `StateReceiveLocal` | 0 | `0x01005bf8` |
| `StateReceiveInternet` | 1 | `0x01011588`, `0x010115f0` |
| `StateReceiveSerial` | 2 | `0x0100a268`, `0x0100a2d0` |
| `StateReceiveFromBall` | 2 | `0x0100fc78`, `0x0100fce0` |
| `StateReceiveRankMatch` | 3, 4 | `0x01012458`, `0x010124c0` |

Any route but 0 overwrites the record's date ([The card's date](#the-cards-date)). After the import
(`0x00ff24e0..0x00ff26d4`), routes 3 and 4 set bytes from 2 to 4 in blocks `0xa83021c1` (0x268
bytes) and `0xce07d358` (0x1c bytes): route 3 at an index from record `+0x1c` (at most 0x2f), in the
half chosen by `+0x1e` and the group chosen by the kind at `+0x11`; route 4 when the u32 at record
`+0x18` equals the block's first word. Route 0 touches neither block.

## The card travels in beacon advertise data

A distributor joins nothing. It advertises a network whose advertise data carries the card, and the
receiver reassembles it from its `Scan` results.

The gift is a consumer of the gflnet3 core, separate from the trade sync pump (registration array
`0x006db3b0`, manager `read_u64(read_u64(main+0x02616750))`, empty on the gift screen), which drains
0x7C/0x80 with a 4-byte header. The core manager `read_u64(read_u64(main+0x02616B80))` names itself
`BeaconCommunication` (`0x02068858`, and at `conn+0x278` and `conn+0x308`) and drives
`nn::ldn::Scan`, `GetNetworkInfo`, `SetAdvertiseData` and `OpenAccessPoint` (wrappers `0x017978F0`,
`0x01794C3C`/`0x01799BE0`, `0x017961B0`, `0x01794CF0`). Its connection object at `core+0x50` exists
before any peer, its send gate `+0x2FA` never arms, and a Pia mesh join changes nothing in it but the
mirrored LDN node count. The core send `0x006C2840` queues at `core+0xF8`. On the send path `0x136`
is a `memset` length at `0x010F7E00` and the message id comes from the getter `0x010F7050`.

## The beacon body frame

The 0x180 bytes of LDN advertise data are a 0x18-byte header and a 0x168-byte body framed by the
beacon core.

| offset in the body | size | field |
|---|---|---|
| `+0x00` | 2 | CRC-16/ARC over `body[2:0x168]`, init 0, no final xor |
| `+0x02` | 12 bits | network id, low 8 bits in `body[2]`, high 4 in the low nibble of `body[3]` |
| `+0x03` high nibble | 4 bits | zero on every capture |
| `+0x04` | 1 | zero on every capture |
| `+0x05` | up to 0x163 | application payload |

The network id is `0xD70` on every captured beacon, on the Mystery Gift, link trade and Max Raid
screens. The payload bound is `cmp x2, #0x163` at `0x006c2174`, guarding the `memcpy` to `body+5`
(`add x0, x8, #5`, `0x006c2148`).

The checksum routine `0x0065dcb0` is table-driven; `0x0065def0` builds the table lazily behind
`0x02615fd8`. It is the reflected CRC-16/ARC table for polynomial `0xA001`, updated as
`crc = T[(crc ^ byte) & 0xFF] ^ (crc >> 8)` from 0. Forty captured bodies reproduce their stored
checksum and rebuild byte for byte from their decoded fields.

The builder `0x006c1fa0` zeroes the body, writes the network id at `body+2` with the bit-packed writer
`0x006c1830`, copies the payload to `body+5`, and stores the checksum over `body+2`, `0x166` bytes, at
`body+0`; a missing or oversize payload stores `0xFFFF` instead (`0x006c21d4`).

## The gate a received beacon passes

`0x006c1be0` takes one entry object and returns 1 to accept it. On the build path it checks a body
before `SetAdvertiseData` (`0x006b5ba8` builds, `0x006b5bb0` validates; `0x006c3de4` and `0x006c42c4`
validate the advertise object at `conn+0x360` before the 0x168 copy at `0x017760e0`). On ingestion,
`0x006bb9d4`, `0x006c4b38` and `0x006ca0dc` copy a received advertisement into a stack entry through
`0x006c2360`, call the gate, and offer the entry to the store `0x006c53b0` only when bit 0 is set. Any
test failing rejects:

1. the core object behind `0x02616b80` exists;
2. `body+0` equals the checksum recomputed over `body[2:0x168]`;
3. the body's network id differs from the halfword behind `0x02616b88`, the builder's fallback when
   the core is absent;
4. the network id agrees with the core's own nibble by nibble (`0x006c1cf0`): the low nibble must be
   equal; a differing second nibble accepts; otherwise the third nibble must be equal.

A beacon with a stale checksum is scanned and never stored; the same beacon with the correct
checksum is stored on its first scan (0.21 s measured).

Trap: the 0x480-byte `NetworkInfo` scan-result slots, `pia_obj+0x3C0` among them, take a full 0x180
copy of any body whatever its checksum; a marker there proves only reception.

`0x006c53b0` compares an accepted entry with each stored one (`0x006c1da0`: the body and the id
struct) and appends through `0x006c5460` only when it is new. A store has its array at `+0x40`, count
at `+0x48`, capacity at `+0x50` (0x32) and mutex at `+0x60`. An entry is 0x180 bytes, a vtable
pointer then the body at `+8`; the same vtable sits at `conn+0x360`, 8 bytes before the console's
own body at `conn+0x368`. Two stores alternate through `0x006c5300`.

`0x010f6600` walks a store, reading the network id through `0x006c1d50` and the payload through
`0x006c1f80` (returns `body+5`; sole caller `0x010f66c4`), and passes the payload to `0x010f8cf0`,
which stores it in a message object for the handler at `[gfl_job+0x68]` vtable `+0x38`. A receiver's
station-information structure is this payload, so its offsets sit 0x1d bytes into the advertise data.

## The message the poll reassembles

Payload byte 0 is the message type. `0x010f6600` builds a typed view for each known type, pointing at
`payload+1`:

| type | view | goes to |
|---|---|---|
| 0 | `0x010f8730` | `0x0110f270`, with the object behind `0x02610958`; a receiver's own beacon (station information) |
| 1 | `0x010f8830` | the job at `[manager+0x68]`, vtable slot `+0x38` |

On the gift screen that job is the receive job and slot `+0x38` (`0x0257dd88+0x48`; the vtable
pointer is the group plus 0x10) is its poll `0x010b74d0`, so a type-1 payload feeds the importer.

The poll reads a ten-byte header at `payload+1` through `0x010f7bf0` (field accessors
`0x010F7A40..0x010F7A80`; the send side lays it out at `0x010F7C08`); the fragment follows it:

| offset | size | meaning |
|---|---|---|
| `+0` | 4 | zero, or the poll returns at once |
| `+4` | 2 | total message length |
| `+6` | 1 | fragment count |
| `+7` | 1 | this fragment's index, refused unless below the count |
| `+8` | 2 | CRC-16/ARC of the reassembled message (`0x0065dcb0`) |

Reassembly contexts of 0x88 bytes, one per message in flight, sit between `job+0x160` and
`job+0x168`. `0x010f7550` matches a fragment to a context on every header field but the index;
failing a match, `0x010f7360` appends a context, storing the fields at `+0`, `+8`, `+0x10`, `+0x18`,
sizing the buffer at `+0x20` from the length (`0x010f6fa0`) and the arrival bitmap behind `+0x58`
from the count. `0x010f7430` accepts a fragment and `0x010f7100` copies it to `index * 300`, the last
fragment taking the remainder; an index past the buffer or an already-set bit is dropped. A message is
at most 65535 bytes and 256 fragments; a 720-byte card is fragments of 300, 300 and 120.

When `0x010f7610` reports every bit set, `0x010f7680` compares `context+0x18` with `0x010f71e0` (the
buffer through `0x0065dcb0`) and returns null on a mismatch. The poll skips the sink on null
(`0x010b77fc`) and erases the context either way, within one poll.

Traps:

- A message with a wrong checksum leaves no trace. Its context is only ever sampled one fragment
  short, then vanishes; the sink `0x01005bc0` is never reached.
- An empty context list after a beacon is what a completed message leaves.
- With header `+0` non-zero, `job+0x160` stays null and no context list is allocated; with it zero
  the list is allocated and `manager+0x80` takes its first stamp.

## What a record must carry

| offset | size | field |
|---|---|---|
| `+0x00` | 8 | the date ([The card's date](#the-cards-date)) |
| `+0x08` | 4 | card id, u16, compared as a whole word: `+0x0A..+0x0B` must be zero |
| `+0x0C` | 2 | inert |
| `+0x0E` | 2 | game-version mask |
| `+0x10` | 1 | flags: bit 0 skips the once-per-card table, bit 2 once per card date |
| `+0x11` | 1 | gift kind, 1 to 5 |
| `+0x12` | 1 | once-per-card limit |
| `+0x13` | 1 | once-per-card tag |
| `+0x15` | 1 | title index |
| `+0x1C` | 1 | kept in header `+0xf` |
| `+0x20` | | the kind's payload |
| `+0x2CC` | 2 | CRC-16/CCITT-FALSE of the record with this field zeroed |

Version mask: the importer calls `0x007d4270` (Shield: `mov w0,#0x2d; ret`) and tests `1 << 1`
against the mask when the value is `0x2D`, else `1 << 0` (`0x00ff2330..0x00ff2358`). A Shield takes
bit 1; `0xFFFF` passes either version; zero is skipped.

Once-per-card table: when `+0x13` is non-zero (`0x00ff236c`), `0x01449820` refuses the record if an
entry of the table at album `+0x1660` (block `0x112D5141` offset `0x1600`; fifty four-byte entries, a
halfword card id and a byte) matches the card id at `+8` and the byte at `+0x13`. On keep,
`0x00ff1544` calls `0x014494a0(album, record)` when `+0x12` is non-zero and bit 0 of `+0x10` is
clear (`0x00ff152c`): it shifts the fifty entries down, appends `{card id, +0x13}` at `+0x1724`, and
when this id's entries with a non-zero byte reach `+0x12` it zeroes them among the first 49. A card
is imported every time when `+0x13` or `+0x12` is zero or bit 0 of `+0x10` is set.

Last-receipt table: bit 2 of `+0x10` makes the keep path call `0x01449560(album, record)`
(`0x00ff1548`, `0x00ff1558`): ten 16-byte entries at album `+0x15c0`, a u64 date at `+0` and the
u16 card id at `+8`. An entry holding the id takes the record's date (`0x01449650`); otherwise the
first entry whose date is older (`0x016cc1f0`, unsigned) takes id and date (`0x01449804`,
`0x0144980c`). An empty entry is taken because its zero date is older.

An accepted record is copied into a `0x338`-byte structure (leading `0x68` bytes zeroed, record at
`+0x68`, `0x00ff2380`) and handed with length `0x2D0` to the validator `0x010b5de0`. The card object
built is `0x3A8` bytes and keeps the structure at `+0x70`.

`0x010b5de0` copies the record to its stack, zeroes `+0x2CC`, and runs CRC-16/CCITT-FALSE over all
0x2D0 bytes: table MSB-first from polynomial `0x1021` (`0x010b5e60`), init `0xFFFF`, update
`T[(byte ^ (crc >> 8)) & 0xFF] ^ (crc << 8)` (`0x010b5f54`). It returns `0x80000000` for a null
pointer or a length other than `0x2D0`, `0x80000001` for a checksum mismatch (the importer maps it to
1 at `0x00ff23d0`), and 0 otherwise, kinds outside 1..5 included (`0x010b6004`); the kind-1 and
kind-4 builders' results are discarded. It fills the `0x68`-byte header (`0x010b5f98..0x010b5fbc`):
card id to `+8`, `+0x15` to `+0xa`, `+0x11` to `+0xc`, `route != 0` to `+0xe`, `+0x1C` to `+0xf`.
Under emulation a sealed record is accepted and reaches the kind-3 path with the word from `+0x20`;
the same record unsealed, and an all-zero record, return `0x80000001`.

Card id: after the import loop `0x00ff2760` collects the cards whose id matches; `0x00ff2f50` reads
the u32 at record `+0x08` (`0x00ff30c0`, `ldr w8,[card+0xe0]`) against the 16-bit id, so anything
non-zero at `+0x0A` or `+0x0B` matches nothing and the importer reports 2 (a gift that cannot be
obtained in this game). On a retail console `80 06` at `+0x0A` was refused that way; `+0x0A` zero
with `a5 6a` at `+0x0C` was received. Nothing read touches `+0x0C`. All 161 SwSh cards in
projectpokemon's EventsGallery carry zero at `+0x0A` and at `+0x0C` either 3 or their title index.

Title: `+0x15` indexes the title table PKHeX ships as `text_wondercard8_<lang>.txt`, shown in the
list before the card is accepted. Index 0 is the species name alone (a record with `0b 00` at `+0x0C`
and title 0 was listed as "Pikachu"); index 11 is "{species} de {original trainer}", listed and kept
as "Pikachu de POKELDN" on a French console.

Kind: 1 to 5 dispatch through `0x02067620`; anything else returns success with nothing built. Kinds
3 and 5 (`0x010b5fd8`) keep the word at `+0x20` in header `+0x30` and build nothing. Kind 1 goes to
`0x010b58f0`, kind 2 copies its item pairs, kind 4 goes to `0x010b5bb0`.

## The Pokemon a kind-1 record carries

`0x010b58f0` parses the record; the builder `0x010b6110` receives length 0x2D0 at its three call
sites (`0x00fe3a50`, `0x00fe4b60`, `0x01015a0c`). The map is PKHeX's `WC8.cs`; the right column is
what a retail console produced.

| offset | size | field | on the console |
|---|---|---|---|
| `+0x20` | 2 | trainer id; 0 with the secret id gives the player's own | 12345/54321 showed ID 993401 |
| `+0x22` | 2 | secret id | |
| `+0x28` | 4 | encryption constant, 0 rolls one | |
| `+0x2C` | 4 | PID, 0 rolls one | |
| `+0x030` | 9 x 0x1C | nicknames, one per language: 0x1A bytes UTF-16, language byte at `+0x1A` | the displayed name |
| `+0x12C` | 9 x 0x1C | original trainer names, 0x1A bytes UTF-16 | the original trainer |
| `+0x228` | 2 | egg location | |
| `+0x22A` | 2 | met location | |
| `+0x22C` | 2 | ball | 1 gave a Master Ball |
| `+0x22E` | 2 | held item; header `+0x10` | 236 gave a Light Ball |
| `+0x230` | 4 x 2 | moves, legality unchecked | an unrelated species' four moves were kept |
| `+0x238` | 8 | four relearn moves | |
| `+0x240` | 2 | species, national index | 25 gave Pikachu |
| `+0x242` | 1 | form | 77 with 1 gave a Galarian Ponyta |
| `+0x243` | 1 | gender, 0 male, 1 female, 2 genderless, 3 random (`0x010b62ac`); header `+0x64` | 1 gave a female |
| `+0x244` | 1 | level, 0 rolls one | |
| `+0x245` | 1 | egg; header `+0x12` | 1 gave an egg |
| `+0x246` | 1 | nature, `0xFF` random below 25 (`0x7672c8`) | 10 gave Timid |
| `+0x247` | 1 | ability, 0/1/2 slot 1/2/hidden, 3 random of two, 4 random of three | 2 gave Lightning Rod |
| `+0x248` | 1 | shiny, 0 never, 1 random, 2 star, 3 square, 4 the PID as given | 3 gave a shiny |
| `+0x249` | 1 | met level | |
| `+0x24A` | 1 | Dynamax level | 10 showed the maximum |
| `+0x24B` | 1 | Gigantamax | 1 gave the mark |
| `+0x24C` | 32 | ribbon indices, `0xFF` ends the list | all `0xFF` gave none |
| `+0x25C` | 1 | header `+0x63` | |
| `+0x26C` | 6 | IVs, HP Atk Def Spe SpA SpD | |
| `+0x272` | 1 | original trainer gender, applied when below 2, else the game's own | |
| `+0x273` | 6 | EVs, same order | |

The language index comes from the table at `0x02067650` (game language to 0..8). Ribbon bytes go to
`0x00775d50`; indices above 127 set nothing. A record with zero ribbon bytes names ribbon 0
thirty-two times: fill the list with `0xFF`.

The parser does not read the level or the met level. Both offsets come from cards, not code:
`+0x244` and `+0x249` are the only offsets in `0x238..0x272` that predict two claimed cards' distinct
levels (28 and 63 for the level, 32 and 59 for the met level).

Level 0: the builder draws `r = random & 0x7f` until `r <= 99` and takes `r + 1`, uniform over
1..100 (`0x010b6218`); one record gave 20 then 35. An egg (`+0x245` = 1) gets level 1 regardless
(`0x010b6400`). A rolled Pokemon shows met level 0, the empty `+0x249`. Experience always matches the
species' growth group (a cube-curve species had 8000 at level 20, a slower one 96 at level 4).

IVs: the builder tests the six bytes in the order HP, Atk, Def, SpA, SpD, Spe; the first in
`0xFC..0xFE` stores a flawless count `byte - 0xFB` (1 to 3) at `[sp+0x110]` and sets all six spec IVs
to `0xFFFF`, discarding the rest (`0x010b6300..0x010b63c4`). Otherwise a byte of 32 or more becomes
`0xFFFF` and a byte below 32 is kept. The spec reaches `0x007667a0` through `0x007662a0`,
`0x00777f40` and `0x00766660`, which caps the level at 100 (`0x00766a14`) and, for a count of 1 to 5,
writes 31 to that many distinct random positions (`0x00766a50..0x00766b04`); a count of 6 or more
(out of a card's reach) gives no 31 (`0x00766a2c..0x00766a44`). Every IV still `0xFFFF` is rolled
0..31 (`0x00766de8`, `0x007660d0(0x20)`, the game's random below `n`). So `0xFC`, `0xFD` or `0xFE` in
any IV byte gives exactly 1, 2 or 3 random IVs of 31.

A record left at zero gives a male, Hardy Pokemon with its first ability and IVs of 0, as the
builder run under unicorn showed. `pokeldn.swsh.wc8.pokemon_card` writes gender 3, nature `0xFF`,
ability 3 and every IV byte `0xFF` unless the field is given, so the game rolls each one.

## A card delivered by beacon, end to end

A 720-byte record split into three fragments and served from a synthesised beacon reaches the
importer on an unmodified emulated console, with no memory or code patch. The importer's result is
at `bound+0x2C0`, `bound` being `job+0x80`. Two records differing only in their version mask:

| version mask | result | the console's message |
|---|---|---|
| `0x0000` | 2 | a gift was received but cannot be obtained in this game |
| `0xFFFF` | 1 | receiving the gift failed |

`0x00ff1fb0` returns the importer's value when non-zero, else 2 when the card list is empty: a
record the mask filters out leaves the list empty. The `0xFFFF` record had a zero checksum at
`+0x2CC`, and the validator's `0x80000001` came back as 1. Neither faulted.

A sealed kind-3 record is listed, confirmed and saved. The screen shows the title from the kind at
`+0x11`, the quantity from the word at `+0x20`, and 1 January 2070 for a zeroed date; with a zero
identifier it delivers nothing.

## A card delivered to a retail console

`bin/swsh_gift_host.py` delivers a card to a retail Sword over LDN. A retail Sword lists a card only
when the advertise data opens with the Pia header:

| what the host advertised | listed |
|---|---|
| LDN protocol 3 (the GBA app's), advertise data opening with 24 zero bytes | no |
| LDN protocol 1, the console's own, 24 zero bytes | no |
| LDN protocol 1, the Pia header at the front of the advertise data | yes |

The Pia header is the one the console's own gift advertisement opens with
([Sword sessions](swsh_session.md)): a random network id, a zero password CRC, system communication
version 5, header size 0x18, a random session parameter and eight zero bytes. Scene id 0 and
application version 4 were accepted; the console's own advertisement carries scene 65535 and
application version 7, so neither is filtered on. ldn_mitm carries no 802.11 advertisement, so an
emulator cannot test these variables.

| kind | record | result on the console |
|---|---|---|
| 1 | `+0x245` = 1, level-1 Pikachu, title index 1 | listed "Oeuf de Pokemon", an egg in the party |
| 2 | item id at `+0x20`, quantity at `+0x22`: `01 00 03 00`, title index 3 | listed "Master Ball", three in the bag |
| 3 | amount 10 at `+0x20`, title index 1 | listed with the title "Oeuf de Pokemon", 10 BP added |
| 3 | amount 10 at `+0x20`, title index 39, as the EventsGallery Battle Points cards carry | listed "Points de Combat", 10 BP added |

The title comes from `+0x15` alone, whatever the kind; the kind decides what is delivered.

A kind-2 record needs only the kind, the item pairs and a quantity. The parser copies exactly six
id/quantity pairs from record `+0x20..+0x37` to header `+0x30..+0x47` (`0x010b6024..0x010b6080`) and
sets header `+0x0D` to the number of non-zero quantities (`0x010b6084..0x010b60e4`); the redemption
calls `Bag::AddItem` per pair with a non-zero quantity (`0x01015d00..0x01015dd0`). The 1.3.2 item
table has 1607 entries; those whose name in `bin/message/<lang>/common/itemname.dat` starts with `★`
are dummies (1279 to 1578 among them).

Kind 4 (clothing) passes up to twelve category/index pairs to `0x0143a450`
(`0x01015eb0..0x010160a8`), which accepts categories 0..14 and indices 0..1023 and sets one bit in
the clothing block. Kinds 3 and 5 add the word at `+0x20` to clamped counters in the status object
`[[0x2610798]+0x208]`:

    kind 3  0x01015e00   [status+0x17c] = min(old + amount, 9999)                  0x014390fc
    kind 5  0x010160b0   [status+0x64]: an amount above 9,999,999 sets 9,999,999;
                         otherwise old + amount, clamped to 9,999,999              0x01438f2c

`status+0x64` is pocket money: `AddPocketMoney_` (`0x014ad5e0`) calls the same `0x01438f20`
(`0x014ad624`) and `GetPocketMoney_` (`0x014ad700`) reads it through `0x01438ef0`.

The kind-1 redemption `0x010159d0` builds the Pokemon (`0x010b6110`; null returns 0) and offers it to
the party (`0x01015b78`, virtual `+0x28`). If the party refuses, it asks the box store
`[[0x2610798]+0x220]` for a free slot (`0x01408000`, `0x01015bd0`) and places it only if one exists
(`0x01406b00`, `0x01015c08`). It returns `{1, 0}` for the party, `{1, 1}` for a box, `{0, 1}` when
not placed (`0x01015cd0`, `0x01015cf4`); the caller stores that at `+0x78` of the object `0x00feb610`
returns (`0x01014fe4`) and never tests it. A card that fails the room test never gets here
([What the menu refuses](#what-the-menu-refuses)).

`Bag::AddItem` (`0x01420790`; bag, id, count, new-flag) takes the pocket from item field 14
(`0x00788c50(id, 14)`, item byte `+0x11 & 0xF`), finds the slot holding the id or the first empty
one, and writes `id | min(count + n, 999) << 15`; a slot already at 999 refuses. A slot is one u32:
id in bits 0-14, count in bits 15-29, bit 30 the new-item flag. The save block is registered by
`0x0141fae0`, key `0x1177C2C4`, `0x12F8` bytes. Pockets, from `bag+0x1358`:

| field 14 | pocket | slots |
|---|---|---|
| 0 | Medicine | 60 |
| 1 | Balls | 30 |
| 2 | Battle | 20 |
| 3 | Berries | 80 |
| 4 | Items | 550 |
| 5 | TMs | 210 |
| 6 | Treasures | 100 |
| 7 | Ingredients | 100 |
| 8 | Key | 64 |

## What the menu refuses

Before redeeming a selected card, `0x01014a60` reads the kind `card[+0x7c]` (`0x01014bcc`),
`w25 = 0x00ff1750(card) - 1` (`0x01014bd4`, `0x01014be4`) and bit 2 of the record flags `[card+0xe8]`
(`0x01014be8 ubfx w24,w8,#2,#1`), and for kind 1 runs the room test `0x013adee0` (`0x01014d68`). In
order:

    0x00ff1750 returned 1, 2 or 3    message 7, 0x10 or 0x11     0x01014d9c cmp w25,#3; table 0x02065360 = 7, 16, 17
    kind 1 and no room               message 8                   0x01014c14 mov w21,#8
    flag bit 2 set                   message 0xF, then state 3   0x01014d38 mov w1,#0xf; continuation 0x010156f0
    otherwise                        state 3, the redemption     0x01014e70

`0x02064f80` holds `mystery.tbl` label hashes, one u64 per message index; the initializer from
`0x01000718` resolves entry k into `owner+0x5f8+8k`, read back by `0x01002da0`. From the 1.3.2
English `mystery.dat`:

| message | label | text |
|---|---|---|
| 7 | `msg_o_mystery_win_13` | You can't get that gift, since you've already received the same gift before. |
| 8 | `msg_o_mystery_win_14` | There's no room for another Pokémon. Make room in your party or Pokémon Boxes, and then try again. |
| 0xF | `msg_o_mystery_win_34` | You can receive this gift just once a day. Once you've received it, you can't claim another one until the next day. |
| 0x10 | `msg_o_mystery_win_35` | You can only receive this gift once per day. You've already claimed the one for today, so check in tomorrow for your next chance. |
| 0x11 | `msg_o_mystery_win_36` | You can only receive 10 gifts per day. You've already claimed 10 gifts today, so check in tomorrow to be able to claim more. |

A refusal's continuation `0x01015740` stores 0 at `+0x80`, the menu's first state. A refused card is
neither placed nor kept and can be claimed again once the cause is gone.

`0x013adee0` returns 1 (no room) when the box store has no free slot (`0x013adfb4 cset w20,eq`) and
the party reports full (party vtable `+0x60`, slot 12, `0x013adfc4`; `0x013adfd0 and`).

`0x00ff1750`, called only from `0x01014bd4`, is the receipt check. It returns 1 at once when
`[card+0x60]` or `[card+0x68]` is zero (`0x00ff1750..0x00ff1770`); for routes 0 to 2 it continues
through `0x00ff17b4` to `0x00ff1a30`:

    data = album+0x60 (0x014480e0)
    record flag bit 0, and the card id's bit set in the bitmap at data+0x1450 (album +0x14b0)   -> 1
    record flag bit 2 clear (0x00ff1ab0)                                                       -> 0
    the record's day invalid (0x00ff1b84)                                                      -> 3
    ten entries of 0x10 bytes from data+0x1560 (album +0x15c0), 0x00ff1b88..0x00ff1c70:
        entry id == card id and card day <= entry day (0x016cc210, cset ls)                   -> 2
        card day > entry day (0x016cc1f0, cset hi): a free entry
    a free entry                                                                               -> 0
    none                                                                                       -> 3

The bitmap read takes byte `id >> 3` (`0x00ff1a8c ubfx x9, x23, #3, #0xd`) with no bound: the
bitmap is 0x100 bytes (ids 0 to 2047), so a record with flag bit 0 and an id of 2048 or more reads
past it, and from id 13000 past the block's 0x17C8 bytes. A record with flag bit 0 clear never
reads it. The bit is set on receipt; its writer is not located. On a retail Sword, EventsGallery's
Poke Ball x100 card (id 0x6A, flags 1) sent a second time over local wireless was refused with message
7 and then no longer listed, while records with flags 0 and the same id 0x270F were received ten
times over.

The entries are written only by `0x01449560`, whose only caller `0x00ff1558` sits behind
`0x00ff154c tbz w8,#2` on `[card+0xe8]`, and they store the record's own date (`0x01449570`,
`0x01449648`), not the receipt time. A card with flag bit 2 is taken once per card date and at most
ten a day; resent with an unchanged date it is refused with message 0x10 while its entry survives.

The keep path `0x00ff13f0` has one caller, `0x01014f74` in the redemption `0x01014eb0`, before the
Pokemon is placed (`0x01014fb0 bl 0x010159d0`). Its body `0x00ff14c0` (sole caller `0x00ff1404`)
calls `0x01449470`, `0x014494a0`, `0x01449560`, `0x01444f80`, `0x018fdc60`, `0x01444d60`,
`0x01445000` and `0x01444de0`, none of which reads the Pokemon; `0x00ff13f0` then writes the current
time (`0x01449ca0` -> `0x01900050`) to `card+0x70` for routes 1 to 4, or copies `card+0xd8` there for
route 0, and files the card (`0x014480f0`). The keep path checks no legality.

The build and the redemption check no move, relearn move, nature, ball, held item or form against
the species. The builder `0x010b6110` has one exit and no refusal: it stores the four moves and the
four relearn moves as given (`0x77bfb0`, `0x77b9a0`; the store at `0x770c7c`), and a move id above
826 changes only the PP lookup (`0x00781490`). The redemption `0x010159d0` tests only the kind byte,
a non-null build and room in the party (`0x7840f0` refuses species 0 or a full party) or the boxes
(`0x1406b00` needs an empty slot). Run under unicorn with the 1.3.2 personal table, the builder kept
Pikachu's illegal moves 14, 337, 57, 900 and relearn moves 1, 2, 3, 9999, nature 200, ball 200 and
item 9999 as given.

The one species test is in the PokemonParam constructor `0x777f40` (`0x778118..0x778148`): a
species whose personal entry has bit 6 of byte 0x21 clear (`0x764990`, `0x77f530`) gets bit 2 of
the record's `+0x04` word set (`0x76eb40`). With that bit set, every accessor reads and writes a
static stand-in whose species is 0x383 (`0x776c50`). A species above 898 reads personal entry 0,
which is marked present, and a form at or above the species' form count reads the base species, so
neither is flagged. Never send a species absent from Sword and Shield; the PKHeX check in the
desktop app refuses one.

Gender is the one field the build corrects (`0x777490`, personal field 0x14 read at `0x7774a4`):
ratios 0, 254 and 255 force male, female and genderless (table `0x1c4d2d0`); on any other ratio a
requested 2 becomes 0 (`0x7774d8`). The builder turns record gender 3 into 0xFF, random
(`0x010b62ac`).

## The card's date

The first eight bytes of the record are the date the album shows, a little-endian u64 bitfield of an
absolute UTC time. No published map names it; PKHeX's `WC8.cs` starts at the card id at `+0x08`.

| bits | field |
|---|---|
| 0-5 | seconds |
| 6-11 | minutes |
| 12-16 | hours |
| 17-21 | day of the month |
| 22-25 | month, 1 to 12 |
| 26-39 | year, absolute |

`0x016cc5e0` converts it to posix time by days-from-civil (the `146097`, `1461` and divide-by-100
constants are in it) and returns 0 when the value equals the sentinel behind `main+0x2616900`. The
album draw `0x00ffbaa0` passes that to `nn::time::ToCalendarTime` (`0x00ffbaf0`), so the console's
zone applies, falling back to `ToCalendarTimeInUtc`. The year is drawn with two digits.

| record bytes | shown on a French retail console |
|---|---|
| zero | 01/01/2070 01:00 |
| 18 October, 16:26 UTC | 18/10/2018 18:26 |
| year 8218 | 2018 |
| `01 02 03 04 05 06 07 08` (month 0 of year 321) | 01/12/2020 15:53 |

Only a local-wireless card keeps its date. Every other route overwrites the eight bytes with
`nn::time::StandardNetworkSystemClock::GetCurrentTime` (`0x00ff3f8c` -> `0x01449ca0`; PLT
`0x01900050`, GOT `0x0260fbb8`), packed by `0x016cbfd0` and `0x016cc1d0`.

## Where the album keeps a card

The album is save block `0x112D5141` (PKHeX's `KMysteryGift`), `0x17C8` bytes, loaded by
`0x01447eb0` into the album object at `+0x60` and written back by `0x01449d90`. It keeps a re-encoded
header, never the 720-byte wire record or its strings. `tools/switch/swsh_save.py` reads a `main`
into its blocks (PKHeX's SwishCrypto: a static xorpad over the file, a XorShift32 stream per block
seeded by its key, a SHA-256 over the encrypted body between two constants); `--key 112d5141 --out
FILE` writes this block out, and `--patch KEY OFF HEX --write OUT` rewrites bytes of a block and
reseals the file.

    0x0000  50 slots of 0x68 bytes, newest in slot 0; an insert moves every slot down one
            (0x01449880 indexes them, cmp w1, #0x31; a slot is in use when its +0x0C is non-zero)
    0x1450  0x378 bytes, zero in every save read; the last-receipt table is 0x1560..0x15FF
            (album +0x15c0) and the once-per-card table 0x1600..0x16C8 (album +0x1660)

A slot is the `0x68`-byte header the importer fills from the record:

    +0x00  8    the record's date bitfield (zero draws 1 January 2070)
    +0x08  u16  card id
    +0x0A  u16  the record's byte at +0x15 (0 on Pokemon cards, 1 on kind-3, 3 on an item card)
    +0x0C  u8   kind: 1 Pokemon, 2 item, 3 the empty kind
    +0x0D  u8   kind 2: how many of the six item quantities are non-zero; 0 otherwise
    +0x0E  u8   1 when the card came by any route but local wireless
    +0x0F  u8   the record's byte at +0x1C (1 on kind-3 cards)
    +0x12  u16  level (kind 1)
    +0x30  u32  species (kind 1); kind 2: the item pairs (u16 id, u16 quantity) as at record +0x20
    +0x38  4 x u32  moves (kind 1)
    +0x48  26   nickname, UTF-16 (kind 1)
    +0x62  u8   3 on every Pokemon card

Zeroing a slot's `+0x0C..+0x62` removes the card from the album; items it delivered stay in `MyItem`
(`0x1177C2C4`).

## The per-frame update that drains the store

`0x010f65a0` is the gfl net manager's per-frame update, called with the manager from `0x0261cba8`.
It takes a steady-clock reading, drains the receiver at `manager+0x60` through the swap `0x006c5300`,
walks the entries, and writes the reading to `manager+0x80` on every pass that finds a non-empty
store. The `+0x80` accesses around the importer `0x00ff2170` are a different thing: the thread-local
guard stack `nn::os::GetTlsValue` returns, the same push and pop around the store append at
`0x006c54a4`.

In some sessions the store is never drained: accepted bodies accumulate (a first body still there
after 27 minutes), `manager+0x80` stays constant and `job+0x160` stays null. Other sessions drain
normally; the cause is unresolved. Trap: check that `manager+0x80`
advances before reading any beacon result.

What ticks the update is unresolved. Its only caller is `0x01109240`, a sequence of per-subsystem
updates, inside `0x00f1df30`, which has neither a `bl` caller nor a vtable slot and is reached
through a registered callback.

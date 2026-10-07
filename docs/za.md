---
title: Legends Z-A
nav_order: 10
has_children: false
---

# Legends Z-A

Pokemon Legends: Z-A (title id `0100f43008c44000`) is a native Switch title with Pia statically
linked into `main`. Its packet header is version 16, the one `pokeldn.ldn.crypto` writes for the
GBA application.

## The dump

Base application `v0` (4.3 GB), update `0100f43008c44800` `v393216` (2.1 GB), Mega Dimension DLC
`0100f43008c45002`.

| NCA | id | container offset | section key |
|---|---|---|---|
| Program (update) | `4a70b3ff963bfe412681185cea68bf55` | `0x2085d0` | `b9de1a0334576634f8fdafdd703f7f9a` |
| Control | `3e7ba1cd223145fa4f299a8f4cafd4cb` | `0xbd0` | `a8cb59338ce785237048d52452eb6adf` |

The Program NCA has the exeFS in section 0 and a BKTR RomFS in section 1. The exeFS holds `main`
(33,970,422 bytes), `main.npdm` (1,700), `rtld` (8,550) and `sdk` (6,247,676), no `subsdk0`.
Decompressed, `main` is text `0..0x3163f70`, rodata from `0x3164000`, data from `0x3bc2000`;
addresses on this page are offsets into that image. The Control RomFS data is at NCA `+0x14c00`,
section counter `0000000000000005`; `control.nacp` gives display version 2.0.2 and eight local
communication ids at `+0x30b0`, all `0100f43008c44000`.

## The wireless layer

| value | | where |
|---|---|---|
| LDN passphrase | `BM7cXkadR9ugiXdHiurkiyhrQwcR3rMgCM5BF47dranKXWAGpGEA9z3ncXRnPjCX` | rodata `0x33391fc`, data `0x3eeda1f` |
| Pia game key | `p3bwdaSsywFXUkDu` | data `0x3eeda0e` |

Both match the [NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Game-Keys).

## The packet header

Header version 16, Pia 6.39 to 7.2 in the wiki's table. The layout is
`pokeldn.ldn.crypto.PiaHeader` (29 bytes, magic `32AB9864`, version byte with `0x80` when
encrypted; see [Pia](pia.md)).

    0x24fadbc   initializer: magic at object +0x08, 0x10 at +0x0c, memsets nonce +0x15 (8), tag +0x1d (16)
    0x24faefc   validator: magic, (version & 0x7f) == 0x10, (length - 0x1d) >> 6 below 0x71
    0x24fb1e0   receive path, branches on bit 7 of the version byte
    0x24fb4b0   send path, writes 0x10 back to +0x0c when it seals nothing
    0x24fb46c   padding-size setter: ORs into bits 4..7 of object +0x0d (wire byte 0x05)

The object keeps nonce and tag eight bytes above their wire offsets, as Legends Arceus's version-11
header does in `pokeldn.ldn.pia6`.

## The advertisement

A console on the local search screen hosts a network and advertises 112 bytes: the 0x5C Pia system
property block and 20 game bytes. Fields that do not change with the link code:

| field | value |
|---|---|
| local communication id | `0100f43008c44000` |
| LDN protocol | 1 |
| advertisement version | 4 |
| scene id | 1 |
| application version | 6 |
| security mode | 1 |
| accept policy | ALL |
| participants | 1/2 |
| system / application communication version | 22 / 6 |
| player name | one byte, a space, UTF-8 |

SSID and channel are per session. The game bytes are the link code in ASCII,
NUL-padded to sixteen, then its length as a little-endian `u32`. Layout and password field are
Legends Arceus's ([pla.md](pla.md), The link code in the advertisement); Z-A's game key gives the
mask `1068a742ac3a8787ab6066a161f5d5e1`. `pokeldn.za.build_advertise_data(code)` reproduces each
advertisement from the code alone; `tests/test_za.py` pins both.

## The seat

A searching console accepts a station and speaks Pia at once: first datagram (109 bytes) at 0.02 s.
Packets authenticate under `AES_ECB(game_key, ssid)` with network id `CRC32(ssid[1:16])` (32 of 32
decrypted). Unanswered, it sends on protocol 1 (Net) from its variable id to destination 0:

| message | |
|---|---|
| `01 11 ...`, 118 bytes | connection status, sequence ids 2 and 3, twice a second |
| `01 40 00 00` | start host migration, once the status goes unanswered |

The connection status is the layout `pokeldn.ldn.pia_connect.parse_net_conn_request` reads: four
slots, two filled, both on port 12345, host `169.254.x.1`, joiner `169.254.x.2`. It stops after
about 14 s (14.4 s measured) but leaves the station seated.

In an emulated pair (768 packets captured) the opening is:

- the host transmits first, 109 bytes, 48 ms after association; the joiner answers 47 ms later
  with 45 bytes, then 125;
- the header nonce is a per-station counter from a random 64-bit base, +1 per packet sent;
- the joiner's first packet has source 0, destination 0, packet id 0, no footer, uncompressed; its
  second carries its own source id, zstd-compressed;
- the host's next packet is addressed to that id and carries the two-byte recipient footer.

A joiner whose LDN connect succeeded on a network with no Pia host behind it disconnects cleanly
after 7.94 s. The timer is the Net connect deadline, 8000 ms:

    0x251b1bc   LdnProtocol vtable 0x3c8aef8 slot 0x1d8: mov w0, #0x1f40
    0x2513520   NetBackgroundProcessJob StartConnectNetwork: job+0xa0 = now + ticks_per_ms * 8000
    0x25141c4   the WaitConnected step 0x25140bc, while the host is unknown: deadline against now
    0x25143a0   expiry: result 0x647a, state byte +0x100 = 5, a 5000 ms deadline (slot 0x1e8),
                then StartDisconnectNetwork

The deadline starts before the LDN connect completes, so the wait is 0.06 s short of 8 s.
LdnProtocol's timing slots 0x1b0 to 0x1f8 return 6000, 1000, 500, 10500, 4500, 8000, 20000, 5000,
5000 and 10000 ms; only 0x1d8 and 0x1e8 are identified.

## The session, on a retail console

A station sending a reference joiner's Session join is admitted at once. The console's sends:

| from the seat | what the console sends |
|---|---|
| 0.02 s | Net connection status, 118 bytes |
| 0.05 s | Session join response, type 2, 37 bytes, to the joiner's variable id |
| 0.06 s | Reliable (protocol 10), 106 bytes, and two Broadcast Reliable (protocol 11) |
| 0.08 s | Net update property, type 0x50, 150 bytes |
| from 0.5 s | RTT requests, about three a second |
| 1.12 s, repeating | Session update session, type 5, 185 bytes |

The join owes, over the Net acknowledgement: ten protocols
(`1:0 3:5 5:1 6:0 9:1 10:3 11:4 12:4 13:7 15:0`), application communication version 6, an
identification token `0x06` then zeroes, and a PlayerInfo name of one space. A join listing
the GBA application's six protocols and version 0x58 goes unanswered and the console starts host
migration 8.7 s after the seat. A join with the ten protocols above whose game messages go
unanswered ends in host migration and "no partner found" 27 s after the seat. A joiner answering
every Net, Session, RTT and Reliable message and no game message (`bin/za_join.py` without `--game`)
keeps a retail search's seat for 150 s, until it leaves: the console sends about 32 packets a second,
answers the leave, then shows "no partner found".

A join whose protocol count differs from the host's is dropped by the type-0 handler `0x254a030`
(`0x254a090`, against `0x256c9f0`) with no answer and no station; a wrong protocol version or
application version is answered with a 37-byte type 2, result 3 (`0x254a2e4`) or 4 (`0x254a290`).
The host's WaitMember draws 3000 ± 999 ms (the random u64 is read signed). On its expiry, with the
joiner on the Net layer and not in the session, LeaveMeshWithHostMigration polls 8000 ms for a next
host (`0x255a520`), then sends Net 0x11 sequence 3 and Net 0x40. A joiner listing nine of the
ten protocols draws no Session message from a retail search; the first Net 0x40 comes 8.74 to
11.01 s after the seat (predicted 8.05 to 12.1 s) and the console opens a new network under a new
SSID, still searching. The 8.7 s above is this path.

The same joiner sending no RTT answer, and so nothing at all after its type 6 at 1.16 s, is kicked
(The kick): Session type 13 from 14.24 s, nine of them about 0.5 s apart, then Net 0x11 sequence 3
every 0.5 s from 19.31 s, Net 0x40 every 0.3 s from 23.31 s, the last packet at 25.13 s, then "no
partner found" on the console. The 27 s ending is this sequence: a joiner that sends nothing from
its own variable id for 10 s.

## The game's own exchange

Above Pia the game runs on Reliable (protocol 10) and Broadcast Reliable (protocol 11), the
sub-header `pokeldn.ldn.reliable` parses. A trade carries the application payloads below
(twenty distinct ones in a reference capture), each re-sent until acknowledged, the same set from both
stations apart from the station id. By message
id, in order of first appearance:

| id | bytes | what it carries |
|---|---|---|
| `1400` | 106 | the station's identity, player name in UTF-16 |
| `1403` | 9 | the identity's checksum (SyncDataSet), below |
| `0100` | 1211 | the record the selection screen is drawn from |
| `0101` | 354 | the offer: nine-byte header, 344-byte Pokemon record, one trailing byte |
| `0102`, `0104` | 5 | step messages |
| `0200` | 5 | the confirmation steps, last byte 3, 6, 0x0b, 0x0e |

`pokeldn.za.reference` ships the identity, its follow-up, the protocol-11 opening and the selection
record, recorded from an emulated pair whose player is `Player`; `bin/za_join.py` and
`bin/za_host.py` send them (`--game-dir` names another set).

The identity is a `b9` tuple of two: a u32, then a one-member tuple holding a 0x5d-byte `bc` blob.
The blob is a six-member tuple: a u32, two small integers, the player name and a 32-byte field of
zeroes, then the rest.

    1400 b902 82<u32> b901 bc5d b906 82<u32> 01 02 bc1a <name> bc20 <32 bytes> ...

The name is 26 bytes, UTF-16LE, NUL-padded: at most twelve characters, at offset 0x18 of the
protocol-10 message (0x1c behind the protocol-11 station prefix). With the recorded `Player` there,
a retail console showed `Player` for its trade partner. Both launchers write `--trainer-name`
(default `POKELDN`) into it (`pokeldn.za.reference.named`).

Channel 0x14 carries a key-value store the game keeps in sync between stations
(`gfa::network::p2p`, built at `0x7796a0`; message id `0x1400 | index`): 1400 is UpdateValue
(`0xc1bdf4`), 1402 DeleteAllValues and 1403 SyncDataSet (`0xc4b1b4`). The identity's outer u32
`0x2abe85e2` is the value's key, a constant at `0xdf1b30`. 1403 carries one u32 over the sender's
values sorted by key, `h = crc32(le32(fnv1a32(value) + h))` from `h = 0` (`0xc4b270`, FNV-1a at
`0xc4b31c`, standard CRC-32 at `0xc4b420`); for the identity the value is the 0x5d bytes after `bc5d`.
The receiver recomputes it and moves on only when every station's matches (`0xb8c724`, `0xb8c660`).
The recorded `Player` identity gives `1403b9018269fb308f`, the recorded message. A renamed identity
sent with that stale 1403 leaves a retail console on its search screen: it sends its 1400s and 1403
but never its 0100. `pokeldn.za.reference.sync_message` builds the 1403 for the
identity sent.

### The trade commands

The trade session setup `0xca2928` subscribes five command types (named by ctti strings) on the
session's command channel (session+0xc8). The id is `0x100 | index`, the type's position in the
channel's list at +0x60 (`0x96129c`, a `strcmp` walk). Each payload is a `b9` struct opening with a
u16 round.

| id | command | handler | payload as the handler reads it | what the handler does |
|---|---|---|---|---|
| `0100` | CommandReady | `0x2dc4c7c` | round, 1200 bytes | copies the 1200 bytes to session+0x604, sets session+0xf0 |
| `0101` | CommandSelectPokemon | `0xb2a44c` | round, 344-byte record, one byte | loads the record (The offered Pokemon); bit 0 of the byte clear makes it a pick |
| `0102` | CommandConfirmTrade | `0xc8dda0` | round | ignored when session+0x152 is above the round; else partner state +0x134 = 4 |
| `0103` | CommandCancelTrade | `0x2dc51ac` | round, u32 reason | +0xab4 = reason with 1 and 2 swapped, else 0; +0x152 = round; +0x150 += 1; then `0x2dc41f8` |
| `0104` | CommandFinalAgreement | `0x2dc52b4` | round | ignored when +0x152 is above the round or own state +0x130 is not 4 or 5; else partner state 5 |

The cancel sender `0x964a60` sends nothing while own state +0x130 is 2 or 5; otherwise it sends
round +0x150 + 1, sets +0x130 = 2, advances +0x150 and +0x152, and drops the partner's state from
3..5 to 2 (3 when the reason is 0). The handlers reject only a round strictly below +0x152, so a
stale ConfirmTrade or FinalAgreement is ignored after a cancel and a higher round is accepted.
SelectPokemon reads no round.

The session object (0xab8 bytes; `0xca2658`, built by `0xca2704`, vtable `0x3e3a6e8`) holds a
configuration at +0x40 (u16 0x201, low byte the channel), callables at +0x48 and +0x88, and a zeroed
+0x150..+0xab7, so both rounds start at 0 and a session's first `0102` and `0104` are `b90100`.
`0x964568` (own state 6; caller `0x9601dc` in the live trade path `0x95f8f4`) clears the own offer
+0x120 and partner PokemonParam +0x128, sets both states to 2, clears +0x118, +0x11a, +0xd0 and zeroes
+0x150/+0x152: the next trade on the seat starts at round 0, and an answer still at round 1 is
accepted. `pokeldn.za.host` resets its round with each trade.

| own state | written by | when |
|---|---|---|
| 5 | session update `0x95f600` (`0x95f680`) | own state 3 or 4, byte +0x148 set, timer +0x138 at least 1.5 s, partner state 4 or 5, `0x963710` true |
| 6 | delegate invoke `0xdfda8c`, filled at `0x964e78` | the exchange worker's state-6 delegate |
| 7 | `0x2dc4b94`, installed by `0x964f0c` | the worker's state-7 delegate; unreachable in 2.0.2 |

`0x9610a4` (caller `0x95fdbc`) runs at own state 5 or more when the worker at +0xd0 is absent or its
+9 is 0 or 0x10: it calls the callable at session+0x48 with (+0x118, +0x120, +0x128), builds the
exchange worker (`0x966af0`, 0xb0 bytes) into +0xd0 and gives it the state-6 and state-7 delegates
(`0x9649e0`, `0x964a20`), stored by `0x9655a4` at worker+0x20 and +0x60. The trade object is built by
`0xc8ad1c` (`adr` at `0xca2578`; constructor `0xc8ae70`, vtable `0x3d8a0d0`: +0x68 `0xdd07cc`, +0x78
`0x2a67168`, +0x80 `0xcbc68c`); the store making it the callable at session+0x48 is untraced.

The worker's start `0x965660` stores the host test `0x9157d0` at +0x14, clears +0x15, stores
`0x34f2b0(rng, 0x12c) + 2` (2..302) at +0x18, zeroes +0xc and +0x10, sets +9 to 1. Its update
`0x960c20` (one caller, `0x95f750`) switches on +9 through the table `0x33a360d`.
`0x962ac0(peer, step)` stores `0x100 | step` at peer+0x48 and sends it; a wait compares the
partner's step at +0x70, valid when +0x71 is set.

| +9 | handler | what it does | next |
|---|---|---|---|
| 1 | `0x960d20` | trade object vfunc +0x68; result 1: +0x15 = (+0x14 != 0), result 0: +0x15 = 1 (`0x960e50`, `0x960e90`), else +0x15 = 0; send step 3 | 2 |
| 2 | `0x960cc0` | wait for the partner's 3 | 3 |
| 3 | `0x960d64` | trade object vfunc +0x78; false: state 4, send step 6 | 5 |
| 5 | `0x960ce0` | wait for the partner's 6 | 6 |
| 6 | `0x960da0` | `0x9628e8`: trade object +0x40 = 1, then vfunc +0x80 (`0xcbc68c`, the handler update in What the trade writes into a received record) | 7 |
| 7 | `0x960c84` | wait for trade object +0x40 == 3; +0x15 set: send 0xb | 8, else 9 |
| 9 | `0x960c40` | count +0x18 down once per update, then send 0xb | 10 |
| 8, 10 | `0x960ca0` | wait for the partner's 0xb | 11 |
| 11 | `0x960db0` | trade object +0x40 = 4 (`0x961098`) | 12 |
| 12 | `0x960dc0` | wait for trade object +0x40 == 5 (`0x9626e4`), send 0xe | 13 |
| 13 | `0x960d00` | wait for the partner's 0xe | 14 |
| 14 | `0x960de8` | +0x10 == 0: the state-6 delegate (`0x963810`); else the state-7 delegate (`0x9a0b00`); then `0x9637b8` | 0x10 |

Own state 6 is the exchange completed, after both stations passed the `0200b901XX` steps 3, 6, 0x0b
and 0x0e. Handler 14 picks the state-7 delegate when the worker's error word +0x10 is non-zero, and
nothing in 2.0.2 writes a non-zero value there: its only stores zero it, in the constructor
`0x966ba4` (`0x966bcc`) and the start `0x965660` (`0x9656a0`). The worker's abort phase +0xc is read
by the session tick `0x95f6e4` (`0x95f738`): 1 asks the trade object to cancel (`0x9636f8` sets trade
object +0x44 = 1) and parks the worker at step 0xf; 2 waits for trade object +0x44 == 3, then sets
step 14 and phase 3 (`0x95f7e0`). No code stores 1, so the abort phase never starts and no path
through the worker reaches own state 7. A store through a computed address is not excluded; a write
breakpoint on worker+0x10 would settle it. A station whose +0x15 is clear waits the random 2..302
updates before its 0x0b. What `0xdd07cc` returns and how the stored halfword maps onto the `b901XX`
bytes are untraced.

A Z-A choosing Cancel on the trade prompt sends `0103b9020100` (round 1, reason 0) and, once its
player picks again, redraws the prompt with the host's earlier offer without a resend. Its next
confirmation is `0102b90101` and `0104b90101`. A host answering under round 0 is ignored (the
handlers reject a round below +0x152) and the console waits on "Communicating"; round 1 completes the
trade. `pokeldn.za.host`
takes the round from the console's own `0102`, `0103` and `0104`.

### What a joiner owes on those streams

Measured against a reference pair and an emulated host's acknowledgements:

- protocol 10 goes to the host's variable id, protocol 11 to the mesh id 0x0001; both carry the
  host's variable id in the two-byte recipient footer;
- every game packet is zstd-compressed;
- a pure acknowledgement rides the stream's base, 0xfff0, and message flags 0x40; one that advances
  the sequence is read as data with a hole behind it. Application data carries no message flags;
- an acknowledgement on protocol 11 is 74 bytes: the station's four bytes, a stream byte, a count of
  four, then four entries of a next-expected halfword and a sixteen-byte mask, the last cut short.
  Entry 1 is the joiner's stream; the host reports the idle base 0xfff0 in the other three;
- the identity goes out under INIT, the selection record after it and then repeatedly under a fresh
  sequence, the same 1211 bytes each time (measured: about 0.5 s later, then about four a second);
- the sub-header's recipient count is three on protocol 11, zero on protocol 10;
- on protocol 11 the sub-header length counts the payload after the four-byte station prefix, so
  every frame carries four bytes more than it declares: the opening is `00000001` and `1402 b900`,
  the identity is the prefix and the whole protocol-10 identity, the nine-byte message is
  `1403b9018269fb308f`, an acknowledgement is the prefix and four full 18-byte entries. A frame cut
  at its declared length is dropped (the host resends its opening about ten times a second); one
  whose last four bytes are wrong is acknowledged but leaves the host on its search screen.

The LDN NodeInfo local communication version (+0x2E of 0x40 bytes) is 6 on reference stations; 0
is treated the same.

### The kick

A host kicks a station whose own variable id has sourced no packet for 10 s, whatever its player's
screen: its RTT to the station stops and it repeats Session type 13 every 501 ms (0x0d, its
eight-byte constant id big-endian, length ten, a reason byte of 1), composed at `0x2551320` in
`0x25512b4`, whose two callers `0x255bad4` and `0x255bd70` are in
`nn::pia::session::KickoutManageJob` (`vfunc6` `0x255bda0`). 0x0001 is only a destination; a joiner
sending from it is heard by no one. In captures of a kick it came 18 to 25 s after
the seat.

    0x2547700   from SessionProtocol vfunc 10 (0x2547170), while the local station's byte +0x48 is 2
                and +0x1b0 is non-zero: for each station in state 2, reason 1 through 0x2547dd0 (map at
                session+0x1048) when now > last_heard(+0xb8) + ticks_per_ms * (s32)[+0x1b0]
    0x24f5f08   ticks per ms: GetSystemTickFrequency() / 1000, computed once
    0x25504c8   writes +0x1b0 on session+0x18, and +0x338 of the object 0x24f11f0 returns
    0x253d9d4   session start 0x253d4f0: max([setting+0x28c], 4000) to 0x25504c8
                (0x253d9cc ldr x0,[x20,#0x18]), [setting+0x290] to 0x257d12c just before
    0x199eb48   setting constructors store (+0x28c, +0x290) = (10000, 1000) as one u64; also
                0x199edf0, 0x199f07c, 0x199f2f8, 0x19a0494, 0x19a0a4c, and Pia's default 0x251a4c8
    0x255c990   one-shot table [0x3ee51d8][station id], read and cleared: also kicks with reason 1
    0x2548b60   drains the map into 0x255b4a0, which takes a slot in KickoutManageJob's 24-entry
                table and sends the first type 13; the job's update 0x255bc10 resends every 501 ms
    0x2567280   refreshes last-heard for each station whose bit (byte +0x30) is set in the mask
                0x2566740 builds from the received-data map, keyed by the header's source id

session+0x18 is the `SessionProtocol` (0xd8e8 bytes, vtable `0x3c8db18`, protocol type 0xd), made
by `0x253f284` at `0x253cacc` in the Session initialisation `0x253c880`, which also stores
framework+0xb8 at session+0x30.

### The keepalive

The setting's +0x290 is a send-silence limit in ms (`0x257d12c` -> `0x256a238`; negative fails with
0x10407, 0 becomes 1000). `SessionPacketWriter` (vtable `0x3c8da30`) vfunc 7 `0x2544004` calls
`0x256a2d0` with each send's station mask (`0x2568924`): every other station in state 2 with id at
most 0x17 and byte +0xa0 clear (`0x25770d8`) is stamped at +0xb0 when sent to, and flagged when +0xb0
is older than the limit (never sent to included). Flagged stations (`0x2568928`) get an extra packet
(`0x256a89c(p, 0, 0)`): one Pia message with protocol 0, bit-0x10 byte 0xfd, port 0, flags 0, empty
payload. So a seated station is sent a packet whenever nothing has gone to it for a second; no
capture has been checked against this. The message's header is the presence byte `04` and protocol
`00`: the writer `0x256dccc` emits only the fields that differ from a fresh header (protocol 0xFF,
middle byte 0xFD, port 0). The receiving reader files a message under its key (protocol, middle
byte, port) in a bucket table with no protocol check (`0x2566844`, `0x25670f0`); no Protocol class
has id 0, so no protocol reads it. A protocol only walks its own key's chain (Reliable `0x256fed0`
removes nothing). PacketReader vfunc 6 `0x2565ce0` first calls `0x2566030` (`0x2565d34`, its only
caller), which unlinks every node of every bucket, returns it to the pool's free list and zeroes the
bucket, so an unread message is reclaimed at the start of the next receive pass and protocol-0
messages cannot accumulate. A full node pool (`0x10c10`) drops the rest of the packet. Byte +0xa0 marks a station being kicked, set only by
`0x2577094` from `0x255b4a0` and a non-host's drain `0x2548b60`.

### Packet ids

Packet ids run on two counters per sender: one for destination 0x0001, one for every other
destination (0 and the host's variable id share it). `nn::pia::session::SessionPacketReader::vfunc11`
`0x2566920` checks before any protocol: an unknown source or no station is accepted; otherwise the
destination selects a controller (station+0x78 for 0x0001, station+0x50 otherwise) and `0x2576ad0`
checks the packet id (wire 0x0a) and big-endian nonce (wire 0x0d):

    id == 0                                         accept, nothing recorded
    last id == 0                                    last id = id - 1
    last nonce == 0 and nonce != 0                  last nonce = nonce - 1
    (s16)(id - last id) < 1                         reject
    nonce != 0 and (s64)(nonce - last nonce) < 1    reject
    otherwise                                       last id = id, last nonce = nonce if non-zero

A rejected packet goes to `0x25655d8` and is dropped: a repeated id, or one 0x8000 or more ahead. A
joiner with a separate counter for destination 0 has every Net 0x51 dropped until it passes the
host-id counter; the host repeats its Net 0x50 until one passes (about 10 s, measured) and its
update sequence 1 is delayed.
The Net 0x51 handler `0x2504100` reads no header field: it deserializes (`0x250f930`), checks length
and type 0x51 (`0x2504150`), matches the source against its stations (`0x250c60c`, `0x24fba00`) and
passes station and the acknowledged sequence at message +4 to `0x250daa8`.

### The rest of the join

- Net: the connection status 0x11 is answered with 0x12, the update property 0x50 with 0x51.
- Session: a type-5 update session is answered with fifteen bytes: the type, the station's LDN
  constant id, the update's sequence as a big-endian u32, and 0x0001. The GBA application's answer
  (raw MAC, no sequence) makes a Z-A host repeat its update every two seconds indefinitely.

A host that accepts update sequence 1 sends its selection record about 50 ms later (1.2 and 1.25 s
after the seat, measured) and moves to its trade box.

### The trade on protocol 10

Each side sends a 354-byte `0101` after the selection records (about 2.5 s after, measured). The
offer's last byte is 1 on a preview the station sends unasked (a retail console sends one each time its cursor moves on
the trade box) and 0 on a player's pick; a host keys on that byte, not on a count. A pick sent with 1
is acknowledged and drawn as nothing, and the partner waits on "Communicating" with an empty slot.

The joiner answers the host's pick with its own and confirms with `0102b90100`; the host confirms
with the same, both send `0104b90100` (the host 1.5 s after the joiner's `0102`), and the joiner
sends four `0200b901XX` steps, 03 and 06 at once, 0b and 0e after the trade animation and the
exchange worker's random wait ([The trade commands](#the-trade-commands)). The host sends
`0000000202` on protocol 11 and answers each step with `0201b901XX` under its prefix.
`bin/za_join.py --trade-offer` runs the joiner.

## The offered Pokemon

The offer's record is the generation 8 and 9 entity: four 0x50-byte blocks shuffled by the
encryption constant, 0x148 bytes stored, 0x158 with the party tail, the checksum over the stored
body. `pokeldn.gen9.decrypt` and `read` handle it unchanged; the sample offer reads a shiny
Noibat, level 44, perfect IVs, ball 22, ability 151, moves 542, 103, 403 and 162. Nine records from
three reference sessions all read version 52, language 10, met locations 200 to 212, met dates in
October 2025, trainer id 5071, secret id 14217, original trainer "XS", zero height and weight
scalars; the handler's name reads "Player" only when the current handler is set.

A record composed from 344 zero bytes by `pokeldn.gen9.build` (or edited with
`pokeldn.za.pokemon.build_offer`) trades and is kept:

| field | what the receiving game does |
|---|---|
| nickname 0x58, nicknamed bit 0x8F bit 7, IVs 0x8C | kept, Scarlet's layout |
| species 0x08 | national below 917, from 917 the generation 9 internal index (`pokeldn.gen9.internal_index`, `national`) |
| moves 0x72, four u16 | kept as sent (446, 328, 103, 784 arrived as Stealth Rock, Sand Tomb, Screech, Breaking Swipe) |
| level | from the experience at 0x10: 1,000,000 on an Onix with the party level byte at 44 arrived at level 100 |
| stats, current HP | recomputed from the species; left at zero they are filled in |
| nature, ball, held item, shininess | kept |
| trainer id 12345, secret id 54321 | shown as 993401, the six-digit form of `54321 << 16 \| 12345` |
| met location 202 | Wild Zone 18 |
| ability | not shown on the summary |

A composed Glaceon (experience 125,000, language 3, met 2025-10-16, scale 128) showed level 50,
origin France, size class M. A record the save already holds trades again under a new encryption
constant and PID with the same `hi ^ lo` (`--fresh-pid`).

### The record in memory

Every field accessor takes the record's accessor object in `x0`:

| offset | what |
|---|---|
| +0x08 | pointer to the 0x10-byte party tail, null for a stored record |
| +0x10 | pointer to the 0x148-byte core |
| +0x18 | 1 while the core is encrypted |
| +0x19 | fast mode: 1 keeps the core decrypted between accessor calls |
| +0x1c | `nn::os::LightEventType`, signalled on release when a waiter is counted |
| +0x1e | spin-lock owner byte, 0x5f when free |
| +0x1f | waiter count |

    0xe5d810             16-bit word sum over the 0x140 bytes at core+8; checksum at core+6
    0xe5d8c0, 0xe5d940   crypt: seed = seed * 0x41c64e6d + 0x6073, XOR with seed >> 16, seeded by the
                         encryption constant at core+0 over core+8..+0x147, re-seeded over the tail
    0x3303ab0            block order: 32 rows of four bytes indexed by (EC >> 13) & 31, byte k for
                         block k; rows 0..23 are PKHeX's BlockPosition, rows 24..31 repeat 0..7

An accessor (the 141 table references lie in `0xe48000..0xe5d000`) locks, decrypts when +0x18 is
set, recomputes the checksum and ORs 4 into the halfword at core+4 on a mismatch; unless fast mode is
on it then rewrites the checksum and re-encrypts. Bit 2 of core+4 is the Bad Egg bit, outside the
encrypted range (`0xe485f0` tests it). A getter finding it set, the species getter `0xe49940` among
23 in block A, reads from a default record at `0x3f7eda0` in .bss, initialized by `0xe5cdb4` to zeroes
with 1 at `0x3f7ed98`+2, language (0xd5) `[0x3f0784()+0x378]` and ball (0x124) 4. The serializers
`0xe47a20` (0x158 bytes) and `0xe47c60` (0x148) write the encrypted, shuffled form.

### The fields main 2.0.2 reads and writes

Offsets in the decrypted, unshuffled record. A name the code does not show is PKHeX's
(`PKM/PA9.cs`).

| offset | size | getter | setter | field |
|---|---|---|---|---|
| 0x00 | 4 | every accessor | `0xe514d0` | encryption constant |
| 0x04 | 2 | `0xe485f0` | `0xe51698` | flags; bit 2 Bad Egg |
| 0x06 | 2 | load path | `0xe48250` | checksum |
| 0x08 | 2 | `0xe49940` | `0xe52aa0` | species: national below 917, generation 9 internal index from 917 |
| 0x0a | 2 | `0xe49b40` | `0xe52cc0` | held item |
| 0x0c | 4 | `0xe49d50` | `0xe52ee0` | trainer id and secret id as one u32 |
| 0x10 | 4 | `0xe49f60` | `0xe53100` | experience; level = `0xe5ce70(species, form, exp)` |
| 0x14 | 2 | `0xe4a3c0` | `0xe535b0` | ability |
| 0x16 | 2 | `0xe4d7c0` bit 1, `0xe4d9d0` bit 2 | `0xe56ad0..0xe57130` | ability slot: bit 2 hidden, bit 1 second |
| 0x18 | 2 | `0xe4a5d0` | `0xe537d0` | markings |
| 0x1c | 4 | `0xe4dbe0` | `0xe57350` | PID |
| 0x20 | 1 | `0xe4d3a0` | `0xe56690` | nature |
| 0x21 | 1 | `0xe4d5b0` | `0xe568b0` | stat nature, the one the stat routine reads |
| 0x22 | 1 | `0xe4cd70` bit 0, `0xe4cf80` bits 1-2 | `0xe56030`, `0xe56250` | fateful encounter, gender |
| 0x23 | 1 | `0xe5bcf0` | `0xe5bf00` | IsAlpha in PKHeX (below) |
| 0x24 | 2 | `0xe4d190` | `0xe56470` | form |
| 0x26..0x2b | 6 | `0xe4aa30..0xe4b480` | `0xe53c10..0xe546b0` | EVs |
| 0x48, 0x49 | 2 | none | `0xe5a7e0`, `0xe5aa00` | height and weight scalars, written only |
| 0x4a | 1 | `0xe512c0` | `0xe5ac20` | scale |
| 0x4b | 1 | `0xe5c120` | `0xe5c330` | level bonus, LevelBoost in PKHeX (below) |
| 0x58..0x71 | 26 | `0xe4ddf0` | `0xe57570` | nickname, 13 UTF-16 units |
| 0x72..0x79 | 8 | `0xe4b690(i)` | `0xe548d0(i)` | four moves |
| 0x7a..0x7d | 4 | `0xe4b8b0(i)` | `0xe54b10(i)` | PP |
| 0x7e..0x81 | 4 | `0xe4bad0(i)` | `0xe54d50(i)` | PP ups |
| 0x8a | 2 | `0xe48820` | `0xe51ec0` | current HP |
| 0x8c | 4 | `0xe4bcf0..0xe4cb60` | `0xe54f90..0xe55e10` | six 5-bit IVs from bit 0, egg bit 30, nicknamed bit 31 |
| 0x90 | 4 | `0xe48600` | `0xe516c0` | status condition |
| 0x94..0x9f | 12 | `0xe5cb00(i)` | `0xe5c550(i)` | per-move flags 264..359 |
| 0xa8..0xc1 | 26 | `0xe50840`, `0xe50a70` | `0xe5a190` | handler's name |
| 0xc2 | 1 | `0xe50ca0` | `0xe5a3a0` | handler's gender |
| 0xc3 | 1 | `0xe50eb0` | `0xe5a5c0` | handler's language |
| 0xc4 | 1 | `0xe4f780`, as `!= 0` | `0xe58a70` | current handler |
| 0xc6 | 2 | `0xe4f990` | none | handler's id ("unused?" in PKHeX) |
| 0xc8 | 1 | `0xe4fdb0` | `0xe58eb0` | handler's friendship; `0xe4a170` returns it when 0xc4 is 1, else 0x112 |
| 0xc9..0xcd | 5 | none | `0xe59910`, `0xe59b30`, `0xe59f70`, `0xe59d50` (u16 at 0xcc) | handler's memory, written only |
| 0xce | 1 | `0xe4e2a0` | `0xe57780` | version |
| 0xd0 | 4 | `0xe5b280` | `0xe5b060` | form argument |
| 0xd4 | 1 | none | `0xe5ae40` | affixed ribbon, written only |
| 0xd5 | 1 | `0xe4a7e0` | `0xe539f0` | language |
| 0xd6..0xf6 | 33 | `0xe5cb00(i)` | `0xe5c550(i)` | per-move flags 0..263 |
| 0xf8..0x111 | 26 | `0xe4e4b0` | `0xe579a0` | original trainer's name |
| 0x112 | 1 | `0xe4fba0` | `0xe58c90` | original trainer's friendship |
| 0x113..0x118 | 6 | `0xe590d0`, `0xe592e0`, `0xe594f0`, `0xe59700` | `0xe4ffc0`, `0xe501e0`, `0xe50400`, `0xe50620` | original trainer's memory: 0x113, 0x114, u16 at 0x116, 0x118 |
| 0x11c..0x11e | 3 | `0xe4e910`, `0xe4eb20`, `0xe4ed30` | `0xe57bb0..0xe57ff0` | met date |
| 0x11f | 1 | `0xe5bae0` | `0xe5b8c0` | obedience level |
| 0x122 | 2 | `0xe4ef40` | `0xe58210` | met location |
| 0x124 | 1 | `0xe4f150` | `0xe58430` | ball |
| 0x125 | 1 | `0xe4f360` bits 0-6, `0xe4f570` bit 7 | `0xe58650`, `0xe58860` | met level, original trainer's gender |
| 0x126 | 1 | `0xe5b6b0` | `0xe5b490` | hyper training bits |
| 0x148 | 1 | `0xe49760` | `0xe518f0` | level, party tail |
| 0x14a..0x155 | 12 | `0xe48a40` and five more | `0xe51ae0..0xe528b0` | max HP and the five stats |
| 0x156 | 2 | `0xe48c20` | `0xe51cd0` | signed max-HP offset |

No function in the accessor range touches these bytes, and all are zero on every console-made
record:

    0x1a..0x1b  0x2c..0x47  0x4c..0x57  0x82..0x89  0xa0..0xa7  0xc5  0xcf  0xf7
    0x115  0x119..0x11b  0x120..0x121  0x127..0x147

In Scarlet's layout (kept by PA9.cs) they hold contest stats, Pokerus, ribbons and marks
(0x2c..0x47), relearn moves (0x82), battle version (0xcf), egg date and location, HOME tracker
(0x127) and TM record (0x12f). PA9.cs maps 0x4b..0x57 as a DLC TM record; main reads only 0x4b.

| byte | use |
|---|---|
| 0x4b | stat level = `level + [0x4b]`, capped at 200 (`0x10f558`) |
| 0x156 (s16, unmapped in PA9.cs) | `0xe4163c` uses `max(1, maxhp + (s16)[0x156])`; the load path never writes it, so a composed value persists |
| 0x23 | model descriptor `0x106a48` stores `[0x23] != 0` (`0x106ba0`) at +0x13, beside egg-or-bad at +0x12 and scale as `(scale / 255) * 2 - 1`; only setter called from `0xe3f140`. 1 on exactly the two console-made records with scale 255 (Roserade 407, Glaceon 471) |

0x4b and 0x156 are zero on every console-made record.

#### Per-move flags

PA9.cs's plus move record: 360 bits, bit k at 0xd6 + k/8 for k below 264, at 0x94 + (k - 264)/8
above (Scarlet's Tera types at 0x94/0x95 are flags 264..279 here). A move's index is its position in
the 340 u16 move ids at rodata `0x3303fb0`, found by the linear search `0xe669e0` (-1 when absent;
every caller then skips the flag). `0x631834` sets a flag, `0x673448` clears one, `0xe438e4` clears
the array, `0xe43068` reads one. An Onix with moves 446, 328, 103, 784 flags 33 38 88 91 103 106 157
174 225 231 328 444 446 457 784. Moves 58, 103, 162, 247, 328, 403, 423, 446, 542, 573 and 784
are in the list.

`0xe343a0(species, form, move)` reads field 25 of the personal entry (vtable +0x36, through
`0xe3cb88` and `0xe36850`), a vector of {u16 move, u8 level, u8 unlock level}, and returns the
matching unlock level or 0. Learn levels are 1..100, 253 or 254. In the 2.0.2 table:

| learn level | unlock level |
|---|---|
| 1 (4,803 entries) | 10 |
| 3..100 (14,717) | learn level + 3; exceptions 99 gives 100 (six) and 102 (one), 33 gives 37 (two) |
| 254, present species | 10 on 266 of 274; 19, 20 or 22 on the rest |
| 253 | 10 on 48 of 192; 39, 15, 12, 33, 38 and others on the rest |

The PokemonParam wrapper with vtable `0x3e28e58` (321 slots, each a thunk to the PokemonParam at
+0x50) uses it three ways:

| slot | function | what it does |
|---|---|---|
| 135 | `0x6a30b0` | lists the moves whose unlock level is non-zero and equal to its level argument |
| 145 | `0x631834` | sets a move's flag, skipping a move `0xe669e0` does not find |
| 150 | `0x699308` | true when the unlock level is non-zero and the level (`0xe49760`, or `0xe5ce70` from the experience on a stored record) reaches it; otherwise the flag |

A flag unlocks a move the level rule does not; a record with all flags zero still has every
learnset move at or below its level unlocked. `0xe669e0`'s callers are `0x631848` (set), `0x67345c`
(clear), `0x6993c8` (slot 150), `0xe4307c` (read). The bit writer `0xe5c550` is entered only by `b`
from `0x631864` (set) and `0x673478` (clear); slot 145 (`0x63182c`, +0x488 of both wrapper vtables)
has four call sites, so a console sets flags two ways:

- `0x52fff0`, `0x824eb0` and `0x28eec70` call slot 135 and flag every move it lists for the level.
- `0x6568c4`, in the construction routine `0x656060` (five callers), runs only when wrapper slot
  +0x8b8 (`0xdf5488`, `0x106ba0`, the byte-0x23 getter) is true: it looks a move up by species (slot
  +0x1b0) and form (slot +0x1b8) in `0x657ae0` (a map from GOT `0x3eca658` = `0x6137848`, through
  `0x511f90`; source file not found), checks it with `0x41ea50`, writes it into move slot 0 through
  slot +0x110 (`0x6568a4`) and flags it.

A received or loaded record brings its flags whole; nothing on the receive path reads the array.

The summary screen `0x8d0610` marks each move "/plus_on" or "/plus_off" by slot 150 (`0x8d1a18`),
swapped while the game flag `flag_megaevo_disable` is set (`0x393b8`, the named-flag read, at
`0x8d1438`; key record `0x3db5548`, FNV-1a-64 hash `0x5d0f3c74b46a0ff5`).

Console-made records against {unlock level <= level}:

| record | level | flags | extra flags | unflagged |
|---|---|---|---|---|
| Noibat 714 | 44 | equal | | held 542 (unlock level 47) |
| Swablu 333 | 44 | equal | | held 297 (unlock level 47) |
| Xerneas 716 | 100 | equal | | held 583 (index 214, not in its learnset) |
| Onix 95 | 72 | 350 missing (level 254) | | |
| Roserade 407 | 63 | 866 missing (level 254) | 605 (index 227), the byte-0x23 move in slot 0 | |
| Glaceon 471 | 63 | equal | 247 (index 112), the byte-0x23 move in slot 0 | |

Glaceon also carries Eevee's 36, 38, 129, 204 and 273 (254 entries in its own learnset); Roserade
carries 40, a 253 entry of Roselia (315).

#### The ability

Scarlet's u16 at 0x14, slot bits at 0x16. GetAbility `0xe43bec` returns the stored value below 299
(0x12b), otherwise `0xe5d368(species, form, bit 2 ? 2 : bit 1)` from the personal table. Other
readers of 0x14 are only the type getters `0x99c84` and `0xa4354` (species 493 with ability 121 and
773 with 225 take their type from the held item, `0xe5d528`, `0xe5d5a0`). The creation routines
`0xe3eb34` and `0xbb8f04` write it from `0xe5d368`. Console-made records store 5, 30, 38, 81, 151,
187.

No screen shows the stored ability. `0xe43bec` is entered only by `b` from `0x288d894`, slot 42
(`0x3d1a918`) of an engine component (vtable address point `0x3d1a7c8`, type id `0xfb63b93a`,
constructor `0x2890cb8`); every other path to the raw getter `0xe4a3c0` is a type getter. The seven
321-slot PokemonParam wrapper vtables (`0x3e28e58`, `0x3e29950`, `0x3e2a438`, `0x3e2af50`,
`0x3e2ba38`, `0x3e2c520`, `0x3e2d360`) make slot 42 `mov w0,wzr; ret` (`0x2d6fd88` and three
copies). The battle ability window `0x2d52468` ("BTL_STRID_STD_TokWin", "tokusei" `0x31e3d5f`) reads
slot 42 (`0x2d524f4`). On an emulated 2.0.2 the summary pages hit none of `0x288d894`, `0x2d52468`,
`0x2d6fd88`; a Wild Zone battle hits only `0x2d6fd88`, from `0xdc68c`. The component registry
`0xd8a04` caches slot 42 at handler+0x4c (`0x2ae8f4`, handler vtable `0x3d1b0a0`); its reader is
untraced.

### What loading a received record checks

A partner's `0101` reaches `0xb2a44c`, registered for CommandSelectPokemon (`0xca33d8`, called
from `0xca2928`). The deserializer `0xb4e248` requires tag 0xb9 with three members (`0xb4e33c`),
reads the first as a u16 (`0xa91178`), requires the second to be tag 0xbc of exactly 0x158 bytes
(`0xb4e4b8`) and keeps the third at struct+0x15a; on any error the handler is not called
(`0xb4e1c8`). The handler allocates a PokemonParam (`0x82713c`) and loads the 344 bytes with
`0x270994`:

1. `0xe47e94` copies 0x148 bytes to the core and 16 to the tail, decrypts both and compares the
   checksum; a mismatch sets the Bad Egg bit. It clears fast mode, so the load ends by rewriting the
   checksum and re-encrypting: a bad checksum is kept corrected, with the Bad Egg bit set.
2. `0xe3f18c`: for a non-zero species, `0x2901a4(species, form)` looks the pair up in the personal
   table (`0xe366b0`, a map keyed `species * 10000 + form`) and reads the byte of FlatBuffers field
   1 (vtable +6, `0xe3bbfc`), 0 when absent. Zero sets the Bad Egg bit (`0xe51698(acc, 1)`). A
   missing key falls back to map+0x80, the species-0 entry, which has no field 1.
3. `0xe41750(pp, 1)` writes the level from the experience into the tail and recomputes max HP and
   the five stats from species, form, stat level, IVs, hyper training bits, EVs and stat nature.
   Current HP stays 0 when 0, else rises by the max-HP gain.
4. `0xe42584` clamps the PP of the non-zero moves counted from slot 0 to the maximum with PP ups
   (`0xe6646c`); an egg or Bad Egg (`0xe4c950`, `0xe485f0`) is skipped unless
   `[0x3f0784()+0x380]` is set or `0xe483b4` is true.
5. `0xb2a4a4` calls the callable at session+0x88 with the PokemonParam, ignoring its result, moves
   it into session+0x128, and sets partner state +0x134 to 3 (a pick) when bit 0 of the third member
   is clear. The callable is always `0xad2c68`, the name check below (`0xca20a4` builds the
   configuration with it at `0xca2520`, `0xca25d8`; nothing else references it).

Nothing checks moves against a learnset, the ball, met data, trainer ids, the ability or the tail's
level. A composed record fails only by a wrong checksum or a personal-table field 1 of zero, and
both make a Bad Egg, never a refusal; a rejected name is rewritten. A record with a bad checksum is drawn
as an egg icon, level 0, male symbol, under the offer's nickname, with "Trade it" offered; traded, it
lands in the box as "Egg" with an empty summary and the game keeps running.

### The name check on a received Pokemon

`0xad2c68` returns for an empty record (IsEmpty `0x13778`), else runs `0x89f250` (other caller
`0x89de34`): it opens an `nn::ngc::ProfanityFilter` into the global `0x612d3d0` with a 0x20000-byte
buffer (`0x912e10`), checks three names with `0x9138d4(str, len, language)` and finalizes
(`0x912d80`).

| name | language passed | on failure |
|---|---|---|
| nickname, 0x58 | the record's, 0xd5 | `0x8a0370` writes the species name in that language (`0xe33ca0`) and clears the nicknamed bit (0x8c bit 31) |
| original trainer's, 0xf8 | the record's, 0xd5 | `0x3d8a248[language]`, written with `0xe579a0` |
| handler's, 0xa8 | the handler's, 0xc3 | `0x3d8a248[language]`, written with `0xe5a190` |

A language of 12 or more indexes the table as 0. `0x8a0370` writes nothing for an egg or Bad Egg
(`0xe4c950`, `0xe485f0`) when `[0x3f0784()]+0x380` and accessor+0x1a are both 0. The replacement
table `0x3d8a248` holds twelve UTF-16 strings: 0, 1, 6 `ゼット.`; 2 `Z`; 3 `Zed`; 4, 7, 11 `Zeta`; 5
`Zett`; 8 `제트.`; 9, 10 `Z.`.

`0x9138d4` fails a name when:

- its length is 0 or its first unit is 0;
- it is 7 units or longer and any unit is in 0x3041..0x3090, 0x30a1..0x30fa, 0x4e00..0x9fcc or
  0xac00..0xd7a3 (lanes at `0x3308840`, `0x33087b8`);
- the language is 1..5, 7 or 11 and any unit before the first 0 is in 0x4e00..0x9fa0 other than
  0x4edd;
- L (from `0x444330`) is 0, 6 or above 11;
- the filter's vfunc +0x28, called by `0x913ad0` as `(&result, pattern, &str, 1)` with pattern
  `0x339f650[L - 1]`, leaves a non-zero result.

A string the length scan `0x913a80` (skipping 0x10-tagged runs) measures as 0 passes without the
filter, as does a filter call returning an error (`0x913b08`). An empty handler name with handler
language 0 becomes `ゼット.`, and an empty original trainer's name the string of the record's
language; a completed trade then overwrites the handler's name. PKLDN and the reference names pass.

L, the game's text language, is byte +0x14 of the singleton `0x6131800` (GOT `0x3ec7800`; read by
`0x444330` through `0x410a20` once +0x80 marks it constructed). It is numbered as the record's
language byte and indexes the message directory table `0x3e278b8` (stride 0x18, `0x940dd8`): 0, 1, 6
"jpn", 2 "English", 3 "French", 4 "Italian", 5 "German", 7 "Spanish", 8 "Korean", 9 "Simp_Chinese",
10 "Trad_Chinese", 11 "Latam", 12 "item". The loader `0x410a30` uses L when its language argument is
0 (`0x410a68`).

At boot `0xaa1340` stores at +0x10 the index `0x17d6368` makes of `nn::oe::GetDesiredLanguage()`
(ja, en-US, fr, de, it, es, zh-Hans, ko, nl, pt, ru, zh-Hant, en-GB, fr-CA, es-419 as 0..14, else 15),
and `0x741760` maps it to L through `0x330f728`, `1 2 3 5 4 7 9 8 2 2 2 10 2 3 11` (2 above 14), so
the boot value is 1..5 or 7..11. The setter `0x17d62ec` is the one writer of +0x14; its other callers
are the language-select view (`0x2c204ac`), `0xbb9d30` with the trainer record's +0x47, and a
script binding `0x1673170` (Lua name `f21813187` in module `cE461829E`, `0x16734c0`) that stores any
integer. None of the four shipped Lua packs (`/arc` `scriptluabinrelease` dll_util, event_ik, main,
main_dynamic) names the binding or its module.

The language-select view stores only the ten values it lists. Its vfunc `0x2c20b80` fills a vector
of two-byte entries (L, label index) at +0x50 of its model `[view+0x118]` (`0x2c200d4`): the current
L first when it is one of the ten, then 2, 7, 11, 3, 5, 4, 1, 8, 9, 10 without it (the bytes at
`0x33a19b5`, also built inline), padded with `01 00` to ten. `0x2c20c98` gives `Button_00` to
`Button_09` a handler holding (view, i); the handler `0x2c21234` calls `0x2c2047c([view+0x118], i)`,
which passes the first byte of entry i of that same vector to the setter (`0x2c204ac`).

The pattern `0x339f650[L - 1]` is a set of `nn::ngc` word lists, so the receiving console's
language picks them, whatever the record's language:

| L | pattern | lists |
|---|---|---|
| 1 Japanese | 0x13 | Japanese, American and British English |
| 2 English | 0x12 | American and British English |
| 3 French | 0x36 | American and British English, Canadian French, French |
| 4 Italian | 0x92 | American and British English, Italian |
| 5 German | 0x52 | American and British English, German |
| 6 | 0 | none; the name has already failed |
| 7 Spanish, 11 Latin American Spanish | 0x11a | American and British English, Latin American Spanish, Spanish |
| 8 Korean | 0x412 | American and British English, Korean |
| 9, 10 Chinese | 0x8813 | Japanese, American and British English, Chinese, Taiwanese |

### What the trade writes into a received record

Step 6 of the exchange calls trade object vfunc +0x80, `0xcbc68c`, which calls `0xcbc7fc`. Unless
`0xcbc9e8` returns null (`0xcbc854`, skipping the update), it fills a struct from the player's
trainer record (`0x505c30` on the singleton from GOT `0x3ec28d8`) with `0x882104`: u32 +0x40 (trainer
id and secret id), gender +0x45, language +0x47, 13 units of name from +0x50. It wraps the partner's
PokemonParam (trade object +0x78) with `0x825358` and calls wrapper slot 167 (`0xcbc888`, +0x538;
`0xcebfe0` in both wrapper vtables), a thunk to `0xcebfe8`:

- original trainer's gender (`0xe4f570`, 0x125 bit 7), u32 0x0c (`0xe49d50`) and name (`0xe510c0`)
  all match the struct: 0xc4 = 0 (`0xe58a70`), call `0xe3f900`, return 1;
- otherwise 0xc4 = 1, the struct's name (`0xe5a190`), gender to 0xc2 (`0xe5a3a0`) and language to
  0xc3 (`0xe5a5c0`), 0 to the handler's memory 0xc9, 0xca, 0xcb and u16 0xcc (`0xe59910`, `0xe59b30`,
  `0xe59f70`, `0xe59d50`), `0xe340ac(species, form)` to friendship 0xc8 (`0xe58eb0`), call
  `0xe3f900`, return 0.

A received Pokemon carries the receiving player as handler unless that player is its original
trainer. Each setter, on a record still marked encrypted (+0x18), re-sums (`0xe5d810`) and sets the
Bad Egg bit on a mismatch (`0xe58b60..0xe58b80`); on a Bad Egg it writes into a sink at `0x3f7ef98`
(`0xe58bcc`).

### The personal table

`0xe380c0` loads `personal_array.bin` from the directory `0x7961b0` configures as "avalon/data"
(`[[0x3f7f038]]`), as it does `waza_array.bin`, `tokusei_array.bin` and `growTable.bin`:

| | |
|---|---|
| `/arc/data.trpfd` | 9,877,520 bytes: 238,546 file hashes, 13,181 packs |
| `/arc/data.trpfs` | 4,753,821,072 bytes, magic `ONEPACK` |
| name hash | FNV-1a 64, basis `0xcbf29ce484222645` (`0xe38438`) |
| `avalon/data/personal_array.bin` | hash `0x68ab38e2cf1281ed`, file index 97074 |
| its pack | 169, `arc/avalondatatokusei_array.bin.trpak`, trpfs `+0x4bc1840`, 131,488 bytes, 4 files |
| its entry | compression type 3, 110,132 bytes, 384,260 decompressed by `OodleLZ_Decompress` `0x1a9c9e0` |

A FlatBuffers vector of 1445 tables, 1445 distinct keys. Field 0 opens with the species and form
halfwords, keyed by the map builder `0xe36170` as `species * 10000 + form` (key 0 at map+0x80).
Species run 0..1010, all present, 434 entries with a form above 0; keys from 917 are the generation 9
internal index. Field 1 is 1 on 594 (species, form) pairs over 364 species, absent on the other 851.
Those 594 equal PKHeX's `personal_za` presence list up to 1010; PKHeX's 1011..1016 (14 pairs) have
no entry and arrive as Bad Eggs. The Mega Dimension DLC ships no personal table (its one PublicData
NCA, 101,376 bytes, holds a 692-byte RomFS). Species 95, 333, 407, 471, 707, 714 and 716 are
present in form 0.

No refusal of a Bad Egg was found on the boxing or exchange path. `0x962388` boxes only a Pokemon
neither empty (IsEmpty `0x13778`) nor egg-or-bad (IsEgg `0x18e4c`), but the live trade path
`0x95f8f4` boxes the pick through `0x961964` (`0x960000`) directly. On the exchange the egg and Bad
Egg tests only skip work: the PP clamp `0xe42584` and the stat recomputation `0xe41750` (skipped by
`0xc34b5c`).

## A trade with a retail console

A retail Z-A on its Link Trade search trades with `bin/za_join.py` and keeps a composed record.
After a trade the console returns to its trade box on the same seat and can trade again: `0x964568`
resets both states to 2 and both rounds to 0 ([The trade commands](#the-trade-commands)).

The joiner takes a repeated `--trade-offer`: 2.7 s after its fourth step it previews the next record
and picks it on the console's next pick, under round 0. `bin/za_join.py` and `bin/za_host.py` trade a
queue of records in order over ldn_mitm (`tests/test_za_host.py` scripts the joiner's side), and the
joiner traded two queued records with a retail Z-A host on one seat.

The console's trade animation runs after its fourth step and carries no trade command. With a retail
Z-A joining `bin/za_host.py`, from the fourth step: the animation starts at 1.1 s, the received
Pokemon appears at about 26 s (hand-pressed, up to 2 s late), the console's next preview (`01 01`,
354 bytes) arrives at 30.2 s and the player has control at about 31.7 s. The console sends no
protocol-10 message in between.
A seat formed late in the console's host phase is handed over: the first datagram comes late, no
update sequence 1 follows, and the console repeats Session type 9 once a second (start host migration
in the wiki's numbering, which puts the kick at 12 where Z-A uses 13) until it restarts its Net
(measured: first datagram 1.4 s after association against under 0.1 s on a normal seat, Net restarted
at 6.5 s). A retail Scarlet's search behaved the same on hardware; no code on either side is traced.

## Hosting

A searching console also scans, and joins a network carrying the title's advertisement and its link
code. `bin/za_host.py` hosts one; `pokeldn.za.host` is pinned byte for byte against an emulated
pair's trade.

| from the seat | what the host sends |
|---|---|
| 0 s, every 0.46 s until answered | Net connection status 0x11: sequence 2, four slots, host and joiner on 12345 |
| on the Session join | join response (type 2, 37 bytes) to the joiner's id, update session (type 5, sequence 0) to 0x0001 |
| with it | the identity on protocol 10 under INIT; the identity and `1403b9018269fb308f` bundled on protocol 11, prefix `00000002` |
| with it | Net update property 0x50, every 0.5 s until 0x51 |
| from 0.2 s | RTT requests to 0x0001, about three a second; a response to each of the joiner's |
| 1.15 s after update 0 is acknowledged | update session sequence 1 |
| once update 1 is acknowledged | the 1211-byte selection record twice, 60 ms apart |
| 2.7 s later | the preview `0101` |

Unlike the GBA application's host:

- the host's station entry in the update session carries identification token `0x06`;
- the update's sequence is written twice, at +1 and at +21;
- the property update carries `02` after the scene id where the GBA application writes `01`
  (CloseParticipation, below);
- a broadcast acknowledgement reports the joiner's stream in entry 1, 0xfff0 in the other three.

A retail Z-A joins `bin/za_host.py` and trades (offer marker: [The trade on protocol
10](#the-trade-on-protocol-10)). Any link code works in both roles (`--code`, tested with 12345678).

The host keeps the session after the fourth trade step and closes when the console leaves. A console
returns to its box after trading and leaves with B without an error; the host closes after its
departure. `--hold-after-trade` opts into a timed close; the overall `--seconds` limit still
applies. A host that closes the network on a timer after the trade's save, with no handover, draws
"Error Number: 6" on the console. On the timed close, the `--seconds` limit and Ctrl-C,
`bin/za_host.py` hands a seated console the session first ([A host leaving](#a-host-leaving)).
An emulated Z-A 2.0.2 back on its box answered that handover with the type 10 and the 0x12, showed
"Your trading partner chose to quit trading. The Link Trade will now end." and returned to Link
Play with no error (two runs of two); a retail Z-A on its box after a hosted trade showed the
same message and no error with `--hold-after-trade 5`. The same handover sent 20 s after the fourth step, while the
console was still in the trade animation, drew "Error Number: 6"; the trade had been saved. The
console's first preview after a trade came 30 s after its fourth step, so the timed close counts
from that preview.

A hosted seat trades a queue of records in turn from a repeated `--trade-offer`: the next record is
previewed after the fourth step of the previous trade. The console leaves when its player backs out.
Back on its box after a trade, the console previews the Pokemon under its cursor, so `--offer-out`
keeps only picks.

### The property update

The Net update property (type 0x50) is built by `0x2502960` (sequence at NetProtocol+0x160, through
`0x250f5d0`) and serialized big-endian by `0x250e414`. Offsets from the start of the 0x26-byte Net
message:

| wire | size | field |
|---|---|---|
| 0x04 | 4 | sequence id, NetProtocol+0x160 |
| 0x08 | 8 | network id, session property +0x90 |
| 0x10 | 2 | participant count (`0x25050dc`) |
| 0x12 | 2 | station slots, NetProtocol+0x1216 |
| 0x14 | 8 | session property value (`vfunc +0x10`); the LDN property keeps the scene id, NetworkInfo +0x0a, at +0x98 |
| 0x1c | 1 | accept state (`0x2505ec0`) |
| 0x1d | 1 | session property `vfunc +0x80`, bit 0 |
| 0x1e | 4 | system property size (`0x24fe4dc`) |
| 0x22 | 4 | game data size (`vfunc +0x50`) |

`0x2505ec0` returns the byte at NetProtocol+0x340 once the host address (+0x1280) and the station's
own (+0x1260) are set, or when +0x12d0 is non-zero; else 0. Its writers:

| writer | value |
|---|---|
| network create and auto-connect jobs (`0x2511b94`, `0x2511658`), a third job site `0x2515714` | 1 when session property byte +0xa6 is set, 2 when clear |
| `0x2515434`, from job byte +0xc0 (stored by `0x2515220`) | 1 through `0x250758c` (`NetFacade` vfunc 17), 2 through `0x2507828` (vfunc 19) |
| host migration `0x250b060` | re-runs the 1 path when the byte is 1, the 2 path otherwise |
| setter `0x2500a9c` | 1 from `0x25fdc90` and `0x25fe1ec` |
| a station receiving a 0x50 (`0x25035bc`) | the message's byte; `0x2502e70` sets its own +0xa6 to `byte != 2` |

The LDN session property sets +0xa6 to `stationAcceptPolicy == 0` (NetworkInfo +0x62, `0x25234b8`).
1 means accept all; 2 means the flag is clear.

The 2 path, top down:

    0x1a25454   game task slot 13 (vtable 0x3c17cc0, constructor 0x1a25390): calls 0x253e744 only
                while the session's (u64, u16) at +0xe0/+0xe8 is non-zero and equals +0xf0/+0xf8,
                the host test 0x9157d0 makes; returns when 0x253da70 finds the state object at 1
    0x253e744   -> 0x253e780 -> 0x253e7bc (0x10408 while state +0xd0 reads 1 or byte +0x528 is 0)
                -> 0x2546fe8(0), close -> 0x255c118, OpenCloseParticipationJob (facade session+0x30
                at job+0xc8): OpenParticipation 0x255c264 calls facade index 17, CloseParticipation
                0x255c404 calls index 19 (0x255c484)
    0x25183bc   facade index 19 (Net, Local, Lan, Wan, Nplnd facades): operation 0xa via 0x2507828;
                index 17 (0x251826c): operation 9 via 0x250758c
    0x2515220   0x250758c passes 1, 0x2507828 passes 2; when [[job+0xe0]+0x344] is 1 and 0x2513c0c
                returns 0, stores it at job+0xc0 (0x25152c0), else fails with 0x10408
    0x2513c0c   stores it at LdnBackgroundProcessJob+0x9b (0x2513c6c, the only writer), schedules
                vfunc 37 0x2513ccc: LDN protocol index 23 when +0x9b is 1, else 24 (0x2513d1c)
    0x2515434   copies job+0xc0 into the accept state (0x2500a9c), builds the Net 0x50 (0x2502960)

`nn::ldn::SetStationAcceptPolicy` (PLT `0x3163b60`) has three callers in `LdnProtocol`: index 23
`0x251f18c` sets 0 (accept all), index 24 `0x251f110` sets 1 (reject), index 21 `0x251f208` sets 3
(whitelist, after `AddAcceptFilterEntry`). Within Pia, `0x255c484` is the only virtual call to facade
index 19 and `0x2513d1c` the only call through 0xc0 on the LDN protocol, so the game closes
participation, and policy 1 follows, only while it is session host. CloseParticipation's chain
`0x255c118`, `0x2546fe8` (open flag always 0), `0x253e7bc`, `0x253e744` has one caller, the
CloseSession task's update (`0x1a25454`). Host migration calls
`0x250758c` and `0x2507828` directly (`0x250b098`, `0x250b0f8`).

The task builder `0x1a228f0` is called with "CloseSession" (hash `0x0dd344f64c81e84d`) from four
places on two session drivers. The network manager (vtable `0x3c16978`) keeps its driver at +0x38;
its vfunc 26 `0x199e850` replaces it by mode (jump table `0x3313828`): 0 none, 1 the local driver
(`0x199eaa0`, address point `0x3c16dc8`, built on `nn::pia::local::LocalSessionProperty`), 2 a third
driver (`0x199ecc0`, address point `0x3c151b0`) with its own CloseSession builder `0x19961e0`, 3 the
LAN driver (`0x199ef70`, address point `0x3c17f10`, built on `nn::pia::lan::LanSessionProperty`).
The step names each slot builds are the same on both drivers: 14 "CreateSession", 15 and 17
"BrowseSession", 16 "JoinSession", 18 "LeaveSession", 19 "CloseSession", 20 "UpdateSessionSetting";
slot 13 is the random matching ("RandomMatchingSeq" on the local driver, "JoinRandomSession",
"WaitMember" and "CloseSession" on the LAN driver).

| builder | driver, slot | game feature |
|---|---|---|
| `0x19d7a70` | local, 13 (the CloseSession step of its sequence, registered at `0x19a2180`) | Link Trade search |
| `0x1a35710` | LAN, 13 (registered at `0x1a25e88`) | the same callers, under mode 3 |
| `0x19a7590` | local, 19 | Private Battles |
| `0x1a2ab10` | LAN, 19 | Private Battles, under mode 3 |

Slot 13 has one call in the manager, `0xc8a224`, made by the closure `0xc8a170` that `0xc9fd60`
builds; its one caller `0xc9fa58` is called by Link Trade (`0xc9f8ec`, session name "BoxTrade" and
the Link Code) and by Ranked Battles (`0x2a48bf8`, "BattleRandom", from `0x2cc1d18`). The local
driver's slot 13 (`0x19a1310`) runs the sequence `0x19a1470`; its CloseSession step passes bit 0 of
slot 13's fourth argument to `0x19d7a70`, which builds the task when set and names "NoNeedToClose"
when clear.

Slot 19 has one call in the manager, `0x199dec4`, from the request built by `0x2a48ea0`
(constructor `0x2a49bc4`); `0x2a49218` builds it when the network service at `0x6133e40` exists
(guard `0x6133ec0`). Its three callers are Private Battle pages: `0x2cb5238` runs when the room's
player answers Yes to "Do you want to start a battle with this group?" (`0x2cb59f4`, handler
`0x2cb6e44`, with more than one member, before the battle start `0x29fe8a0`) and from the lobby
update (`0x911f48`); `0x915630` from the lobby update through `0x913e00`
(PrivateBattleLobbyPage, vtable `0x3e0b3e8` slot 15 `0x911cc4`); `0xae0eb8` from
PrivateBattleTopPage's slot 15 `0xae0aa0` (vtable `0x3e0e038`). Link Trade code reaches none of the
three.

An emulated console hosting a Link Trade search under code 00000000 ran slot 13 once a joiner was
admitted, called from `0xc8a198` with the fourth argument the constant 1 (`mov w3, #1` at
`0xc8a194`). About 10 s later the task builder `0x1a228f0` was entered from the CloseSession step
`0x19d7a70` (return address `0x19d7acc`), and facade index 19 from CloseParticipation (return
address `0x255c490`), while the joiner stayed seated and the trade box opened. Backing out of the
box reached neither again.

On a retail console's Link Trade search the advertisement holds policy 0 with 2 of 2 nodes at the
seat, the Pia player count (advertise data +0x16, `e1 01 01 00` to `e1 01 02 00`, the only changing
byte) moves to 2, then policy 1 is advertised just before the console's one Net 0x50 (150 bytes,
sequence 1, accept state `02`), and the policy stays 1 for the seated session. No host migration
precedes it, so the retail `02` is CloseParticipation's, started by the slot-13 step `0x19d7a70`,
the only builder Link Trade code reaches on the local driver.
Measured over four seated sessions decrypted by a joiner board: player count 2 at 0.07 to 0.59 s,
policy 1 first advertised 2 to 48 ms before the Net 0x50 at 0.09 to 0.64 s. With 2 of 2 participants
the policy refuses nothing the capacity did not.

## Leaving

A station leaves through one of two `nn::pia::session` jobs, each waiting on a reply from the other
station. Session types read by the dispatcher `0x2547490` (table `0x336a9b7`, types 0 to 17):

| type | size | sender | message |
|---|---|---|---|
| 3 | 22 | a joiner leaving | leave request: type, random u32, its constant id (8, big-endian), its variable id (2), address type 0, its IPv4, port |
| 4 | 15 | the host | leave response: type, random u32, the leaver's constant and variable ids copied from the request |
| 9 | 30 | the host leaving | start host migration: type, host constant and variable ids, 0, host IPv4 and port, the next host's constant and variable ids, `00 01` |
| 10 | 21 | the station a type 9 names | its acknowledgement: type, its own constant and variable ids, then the host's |

`pokeldn.za` builds all four (`build_leave_request`, `build_leave_response`, `build_migration_ack`).

### A joiner leaving

`LeaveMeshJob::SendLeaveRequest` (`0x2557e54`) sends the type 3 to the host and sets a 500 ms
deadline; `WaitLeaveResponse` (`0x2558098`) completes on a type 4 and re-sends on each deadline,
four sends in all (counter +0x9c, `cmp w8, #2; b.gt` at `0x25581e0`), then completes without one.
The type 4 is taken by `0x25474f8` only at 15 bytes and only when bytes 5 to 14 are the station's
own ids (+0x1b8, +0x1c0); it sets the job's byte +0x99. The host's type-3 handler `0x254c5ac` (22 or
34 bytes, host only) writes the type 4 at `0x254c740` and removes the station (`0x2548500`).

A retail Z-A joined to a host that sends no type 4 sent four type 3 about 0.5 s apart and
deauthenticated 2.0 s after the first (1.99, 2.02 and 2.03 s over three departures).
`bin/za_host.py` answers each type 3 with a type 4; `bin/za_join.py` sends its own type 3 when it
leaves on `--hold` or `--hold-after-trade`, and goes on the type 4 or after the fourth send.

### A host leaving

`LeaveMeshWithHostMigrationJob` names the next host (`CalcNextHost` `0x255a6fc`), then
`SendStartHostMigrationMessage` (`0x255a91c`) sends the type 9 once a second until a 5000 ms
deadline (`0x255a8c8`), after which the job fails with `0x6c0e`. `WaitStartHostMigrationAck`
(`0x255abb4`) completes as soon as byte +0xe0 is set. The type-10 reader `0x2550a64` takes a 21-byte
message only on the host, only when bytes 11 to 20 are the host's own ids, and sets +0xe0 through
`0x255a630` when bytes 1 to 10 are the named next host's.

With the type 9 unanswered, a retail Z-A hosting a trade whose player backed out sent five type 9 one
second apart, then Net 0x11 sequence 3 from source 0 every 0.5 s for about 4 s, then Net 0x40 for
about 2 s, and went silent 10.82 to 10.86 s after its first type 9 (four departures); its network
went down 11.26 s after it in the one traced on the board. In an emulated pair the joiner answered
the type 9 with a type 10 48 ms later, the host sent Net 0x11 sequence 3 and the joiner answered
`0112000000000003`; the host's network was gone 0.25 s after its type 9. The joiner's type 10 and
0x12 went out with header flags 2, destination 0, packet id 0 and no footer.

With the type 10 and the 0x12 sent at once, a retail host sent the 0x11 0.04 s after its type 9
and then Net 0x40 (`01 40 00 00`, source 0) every 0.3 s for 4.06 s while the joiner stayed on its
network; no second type 9 came.

The Net 0x11 is the leaving host's connection status in the migration form of
`NetDestroyNetworkJob` (`0x2516444`, flag at job+0xd8, set when the disconnecting station is host,
`0x2503c44`): `0x2501930` bumps the sequence (NetProtocol+0x15c) and byte 29, the is-migrating byte,
is 1 while the NetHostMigration state NetProtocol+0x12d0 is 1 (`0x250f084`). It asks every client
for a Net 0x12 of that sequence; a client stores the sequence, sets NetProtocol+0x308 and answers
(`0x2503164`, `0x25035c0`). The host waits up to 4000 ms for every 0x12, then sends the 0x40 every
300 ms for 4000 ms, or 2000 ms when the wait expired, until it is alone, and destroys its network
(`0x251693c`, `0x25169f8`).

The migration form differs from the opening 0x11 in three places: the sequence, byte 26 (1 in the
opening form, 2 in the migration form; meaning unread) and byte 29. Retail and emulated hosts send it
from source 0, destination 0, packet id 0, header flags `0x3` (establishing, compressed), no footer;
the 0x40 goes out the same way with flags 2. The type 9 goes to the named station's variable id
from the host's, with the footer.

The 0x40 starts the next host's work: `0x2503d44`, on a station that is not host, calls
NetHostMigration start `0x25099a4`, which picks the next host (`0x2505d10`) and runs
`NetHostMigrationJob` (`0x2509da0`). On LDN it leaves the old network (`0x2503b14`); the next host
opens a network (`0x2507050`) and waits 6000 ms for the remaining clients, dropping any that do not
come back (`0x250acf0`); a client waits 1000 ms and reconnects. Success clears NetProtocol+0x12d0
and stores result 1 or 2 (host) or 3 (client) at NetProtocol+0x12d4; failure stores 4 with error
`0xc406`.

A Link Trade ends at the handover. The type-9 handler `0x2550684` removes the leaving host's station
(`0x2548500`) before starting `ProcessHostMigrationJob`, which drops the session's station count
(session+0x110). The trade scene update `0x95f398` runs the trade only while that count is above 1
(`0x95f45c`) and otherwise ends it with reason 3 (`0x95f508`), the ending a partner's leave request
also reaches. In a two-station trade the leaver is the only partner, so the trade ends whatever the
migration does, and the leaving console destroys its network.

Measured on two emulated Z-A 2.0.2 consoles (Ryujinx, LDN over loopback), seated in the trade box
when the host's player backed out (B, then Yes): the other station received the 30-byte type 9
naming it, answered with the type 10, received the Net 0x11 of sequence 3 with byte 29 set, answered
with the 0x12, and received the 0x40 0.12 s after the type 9. It left the network 4 ms after the
0x40 and finalized its LDN service 0.24 s later with no network created. Its screen showed "Your
trading partner chose to quit trading. The Link Trade will now end." and A returned it to the Link
Play menu. Two runs of two matched.

Leaving on that first 0x40, the joiner was off the network 0.09 s after the type 9 (no trade, the
player backing out of the box).

`bin/za_join.py` answers a type 9 naming it with the type 10, and the Net 0x11 after it with the
0x12, and leaves the network on the first Net 0x40 (or once the console has been silent for a
second).

`pokeldn.za.host.HostSession.leave` runs the same departure: the type 9 (`build_start_migration`)
each second until the type 10 or 5 s, the migration 0x11 every 0.5 s until the 0x12 of its sequence
or 4 s, then the 0x40 every 0.3 s for 4 s (2 s when the 0x12 never came) or until the console leaves
the network. Unanswered, it ends 11 s after its first type 9. `tests/test_za_host.py` runs it
against `bin/za_join.py` and pins the type 9 and both Net messages to the emulated pair's bytes.

## Mystery Gift

Mystery Gift in 2.0.2 offers Get via Internet, Get with Code/Password and Check Mystery Gifts; there
is no local-wireless path.

## Unresolved

- Which modes the network manager's vfunc 26 `0x199e850` receives for Link Trade, Private Battles
  and Ranked Battles: no caller passes a constant, so whether the LAN driver's builders
  (`0x1a2ab10`, `0x1a35710`) ever run, and which driver Ranked Battles and Private Battles use, is
  unknown ([The property update](#the-property-update)).

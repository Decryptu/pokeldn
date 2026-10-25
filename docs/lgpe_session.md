---
title: The Let's Go cartridge and session
parent: Let's Go Pikachu and Eevee
nav_order: 1
---

# The cartridge, its keys, and the session

This page covers Let's Go Pikachu and Eevee from the cartridge's keys to the trade's commit. Addresses
are offsets into Let's Go Pikachu 1.0.2's decompressed `main` as `tools/switch/nso_read.py` lays it
out: text `0..0xd32ba8`, rodata from `0xd33000`, data from `0x1527000`.

## What the title is built from

The update NSP carries the Program NCA `2b7730a9e56498bbafac2002d4908c6b` (title `010003f003a34000`,
rights id `010003f003a348000000000000000007`, key generation 6). Every `nn::pia` and `gflnet3`
reference is in its exefs `main`.

    ./.venv/bin/python tools/switch/xci_read.py "<the .nsp>" --keys prod.keys \
        --nca 2b7730a9e56498bbafac2002d4908c6b --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main main.bin
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0xd32ba8

Pia is statically linked: 269 `nn::pia` classes, 2112 named virtual methods, `nn::pia::local` holding
`LdnCreateNetworkJob`, `LdnCreateSessionSetting`, `LdnJoinSessionSetting` and `LocalProtocol`.
`nn::ldn` is imported from nnSdk, GOT slots `0x15fa1e0..0x15fa2a8`. Above Pia, `gflnet3` bundles
protocol buffers.

## The LDN passphrase

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL

64 bytes at `0xf73a50`, used raw, the same as Sword and Shield's. `0x004db6b4` passes it with length
`0x40` to the `LdnCreateSessionSetting` setter `0x5c0fb0`, `0x004dbba4` to the
`LdnJoinSessionSetting` setter `0x5c1280`. `LdnCreateNetworkJob` (`0x5ce640`) keeps it at +0xC4, its
length at +0x104, and builds the `nn::ldn::SecurityConfig` before `nn::ldn::CreateNetwork`
(`0x5ce988`, PLT stub `0xd31c78`).

## The Pia game key

    p1frXqxmeCZWFv0X

Sixteen ASCII bytes at `0xefd659`, the key of Sword/Shield, Legends: Arceus and Scarlet/Violet.
`0x0011a364..0x0011a384` stores it at crypto setting +0x24c when the mode field `[x19+0x98]` is 0 or 2.

## The Pia header

Version 3 (the wiki's Pia 5.11-5.17). The initializer `0xd122d4` writes `0x00000003_32AB9864`; the
validator `0xd12400` checks the magic and `(byte & 0x7f) == 3`. The layout is Sword's version 4 but
for the version byte (`pokeldn/ldn/pia4.py`):

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version = 3
    0x05  1  connection id
    0x06  2  packet id
    0x08  8  AES-GCM nonce
    0x10  16 AES-GCM tag
    0x20     ciphertext

## The message framing

A fixed 22-byte message header (Pia 5.11-5.12; deserializer `0x5ae870`, writer `0x5aeb00`),
`pokeldn/ldn/pia3.py`:

    0x00  1  flags: 1 destination is a bitmap, 2 relay needed, 4 relayed, 8 unbundled
    0x01  1  version, 1
    0x02  2  payload size, big-endian
    0x04  1  protocol type
    0x05  1  protocol port
    0x06  8  destination, big-endian: a constant id, or a station bitmap under flag 1
    0x0E  8  source constant id, big-endian
    0x16     payload, padded to a multiple of 4

## The session key

`LocalProtocol`'s derivation `0x5cd560` is BDSP's and Sword's: a SEAD xorshift128 seeded from the
session param (`0x57cfc0`), four draws, AES-128-ECB under the game key at `LocalProtocol+0x49c`.
`pokeldn.ldn.pia5.ldn_session_key`. The IV is pia4's: three bytes of
`crc32(network id little-endian || host MAC)`, a source-id byte 0, the header nonce.

The advertisement's application data opens with a 24-byte header:

    0x00  4  network id, random per session
    0x04  4  CRC32 of the user password, 0
    0x08  1  system communication version, 4
    0x09  1  header size, 0x18
    0x0C  4  session param, the key seed
    0x18     the game's application data

## LAN mode

Let's Go 1.0.2 has a LAN path its code never takes. The network setup `0x5dabb0` builds the local
factory for mode 0, Nex for 1 and the Lan factory for 2 (`0x5ddaf0`, LanNetworkFactory constructor
`0xd14a20`), and the matching start `0x4da710` accepts 1 or 2. Every writer of the mode passes 0 or 1:
`0x115818` passes 1, the session object's constructor zeroes its mode at `+0xa4`, and its one setter
`0x348eb0` stores 0 or 1. The English option, matching, menu and error messages carry no LAN text.

## The link code

The link code is the NetworkInfo scene id, `1000a + 100b + 10c + 1`, each pick its index in the
picker (Pikachu 0, Eevee 1, Bulbasaur 2, Charmander 3, Squirtle 4, Pidgey 5, Caterpie 6, Rattata 7,
Jigglypuff 8, Diglett 9); the SSID stays `01000000000000000000000000000000`. `0x891580` folds the
picks, `0x978080` computes `10 * number + mode` (mode 1 a trade), and the session constructor
`0x4db1e0` puts it into `LdnCreateSessionSetting+0x60` (`0x4db6ac`), which Pia copies into
`NetworkConfig.intentId.sceneId`.

The same constructor picks the channel a searching console hosts on: `{1, 6, 11}[scene % 3]`, table
`0xf73a44`; `pokeldn.lgpe.search_channel(code)`. Pikachu x3 is scene 1, channel 6; Bulbasaur,
Charmander, Squirtle is 2341, channel 6; Pikachu, Pikachu, Bulbasaur is 21, channel 1.

A searching console joins a network only when it advertises the console's scene id on the console's
own channel. `bin/lgpe_host.py --code NAMES` hosts on that channel (`--channel auto` scans for the
console's network). `bin/lgpe_join.py` sends no code.

## The Local Protocol

The session state goes out on protocol 0x24, port 0: the wiki's 5.7-5.45 update-session message
(`pokeldn.ldn.local_protocol.parse_update_session`), local header version 1, type 0x11, eight nodes:
host `169.254.105.1` ranking 0, joiner `169.254.105.2` ranking 1, the rest 255. The body carries the
host constant id little-endian (`000048f120229beb` for MAC `48:f1:eb:20:9b:22`); the message header
carries it big-endian.

## The station protocol, for a mesh join

A connection request on protocol 0x14, then a mesh join on 0x18. The handler `0x5b8800` reads the
wiki's 5.10-5.18 layout, station-protocol version 9:

    [0]     message type            1
    [1]     connection id
    [2]     version number          must be 9 (0x5b8848)
    [3]     is inverse connection request; rejected above 1
    [4]     target constant id      big-endian u64, the console's own (0x5b6830)
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1
    [0x10]  inverse connection id
    [0x11]  station location        36 bytes for a joiner: no public address, zero NAT fields
    [...]   ack id                  u32, the message size minus four

A retail console runs the full sequence with the inverse request:

    ->  connection request (is_inverse 0)
    <-  ack; inverse connection request (is_inverse 1) with the host's location
    ->  ack; connection response (type 2, result 0, padded to 0x38)
    <-  connection response, 840 bytes, repeated until acknowledged
    ->  ack

### The connection response a station sends

0x348 bytes (the parser `0x5b9270` accepts 0x3C):

    0x00  1  message type 2
    0x01  1  result
    0x02  1  version 9
    0x03  1  platform 4
    0x05  8  the receiver's constant id, big-endian
    0x0D  4  the receiver's variable id, big-endian
    0x31  4  the network id, big-endian
    0x35  2  01 01
    0x37  0xC3  a PlayerInfo (`station_protocol.player_info`); its first byte must be below 5
    0x344 4  the ack id

`station9.build_connection_response`; `bin/lgpe_join.py --player-name NAME`. A console host given a
0x3C-byte response never sends its clone data and leaves the clone session.

## Joining the mesh

A mesh join request on 0x18 (`mesh_protocol.build_join_request`, local station index 253) draws a
148-byte join response (host index 0, joiner index 1, max active 2, max total 8), acknowledged on
0x14, then an update mesh (type 0x20). The host then streams update session (0x24, acked with 0x21),
RTT (0x58), Sync Clock (0x1C) and Clone (0x73). Keep-alive is protocol 0x08, no body, answered in
kind.

## The RTT Protocol (0x58), version 3

Sixteen bytes: kind a big-endian u32 at [0], the sender's 19.2 MHz tick a u64 at [8]; a response
copies the tick with kind 1. `rtt_protocol.build_v3`; `--no-rtt` turns it off.

## The Sync Clock Protocol (0x1C)

A mesh clock the host controls. Request: [0] u64 tick, [8] zero. Reply: [0] the tick back, [8] u64
the mesh clock in ms. A station requests every two seconds from the join response and adds half the
round trip. Clone Protocol clocks are this clock; a host given clone clocks on the joiner's own uptime
releases the clone and leaves. `pokeldn.ldn.sync_clock`.

## The Reliable Protocol (0x7C), where the game's data is

Pia 5.11's header is 24 bytes; sequence ids start at 0xFFFFF82F.

    0x00  1  flags
    0x01  1  stream id, 3 for the game, 0 on an acknowledgement
    0x02  2  payload size, big-endian
    0x08  4  sequence id, big-endian
    0x0C  4  the next sequence id expected from the peer
    0x18     the payload

An acknowledgement is the header alone. `pokeldn.ldn.reliable3`.

## The Clone Protocol (0x73)

`nn::pia::clone::CloneProtocol` (`PiaCommon-5_11_4`) carries the partner sync. Every message starts
with version 3, a type byte (high nibble the structure, low nibble a variant) and the sender's frame
counter as a big-endian u16.

### Clock sync, the first two seconds

Both sides send clock requests (type 0x11, 18 bytes, `0x51f9b0`) about 5 per second and answer with
replies (type 0x21, 22 bytes, `0x51fab0`):

    clock request                              clock reply
    [4]   4  sender message count              [4]   4  sender message count
    [8]   2  destination bitmap                [8]   2  destination bitmap
    [0xA] 8  sender system tick                [0xA] 4  sender clone clock, ms
                                               [0xE] 8  the request's tick, echoed

The message count runs from 1 over a sender's requests, replies and participates. The bitmap is
`1 << station index`. A reply with clone clock 0 leaves a retail console requesting.

### Participate

After ten answered requests the joiner sends a participate (type 0x31, 10 bytes, bitmap 0x0003); the
host answers 0x33 and sends its own, which the joiner answers 0x33. Clock replies then become 0x22
and clock requests stop.

### Clone elements

A clone is keyed by a clone type (1 to 4), the owning station (0xFD none) and a u32 clone id. Both
stations publish their own copy.

    every command message   [4] u8 clone type, [5] u8 owning station, [8] u32 clone id
    types 0x81 to 0xc4      [0xC] u32 message count, [0x10] u16 destination bitmap, then fields
    types 0xd1 to 0xf4      [0xC] the data

The low nibble is the command token plus one: 1 announce, 2 request, 3 end, 4 lock. `0x51c110`
dispatches the high nibble through table `0xf769c4`:

| type | adds | length |
|---|---|---|
| 0x8N | nothing | 0x12 |
| 0x9N | a u32 clock in ms at [0x12] | 0x16 |
| 0xaN | the clock, a u8 count at [0x16] | 0x1a |
| 0xbN | the clock, a u32 participant bitmap at [0x16] | 0x1a |
| 0xcN | the clock, the count, the bitmap at [0x1A] | 0x1e |
| 0xeN | a zlib stream at [0xD] | acknowledging state |
| 0xfN | a byte at [0xD], a zlib stream at [0xE] | state with data |

The zlib streams inflate to a record, tag 0x20:

    0x20 0x06 u16 clone id  0x01  0x00                               empty copy
    0x20 len  u16 clone id  0x03  u8 station  u16 0  u16 participants  u32 clock  data
    0x20 0x0A u16 clone id  0x05  u8 the station acknowledged  u32 clock

`clone.pack_record` reproduces every captured stream (one compress, a sync flush, a final empty
block).

| exchange | messages |
|---|---|
| owner announces | 0xa1 and 0xb1; the other answers 0xa2 and 0xc1 before the data |
| take-over | the other answers an 0xa1 with 0x91 |
| data | the owner's 0xf3; the other's 0xe3 with the same clock |
| release | 0x83; 0x84 acknowledges |
| leave the clone session | 0x32; 0x41 answers |

An 0xa2 carries the mesh clock and the count, 1 on clone type 4 and 0 on clone type 2. Bytes
`0x17..0x19` of an 0xaN are stack residue no receiver reads (`01 2808ab`). The 0xa1 handler of clone
types 3 and 4 (`0x522a60`) answers with an 0xa2, an 0x91 or nothing; an 0xa1 for an unknown clone
draws an 0x91. `0x51c110` drops silently on destination, a message count not above the sender's last
(`0x51c1e0`), length and type range. The participate handshake completes when the protocol's
pending mask `+0xc0` empties.

### The clone 0 pair

The owner of clone 0 on clone type 3 announces it with an 0xa1 and an 0xb1 and publishes only after
the other's 0xa2 and 0xc1. A host whose answer is lost leaves the console on "vous allez bientôt être
connecté"; `bin/lgpe_host.py` repeats the pair every 110 ms, at most 20 times, until an 0xa2, 0xc1
or 0x91 arrives.

### What the announce's destination field decides

An 0x81 announcing a clone for the first time carries the whole mesh (0x0003); the 0xa1s behind it
carry the peer alone (0x0001). Given the peer bitmap on the 0x81, a peer answers neither 0xa2 and the
gate `0x11b080` never passes.

### The game's messages on the reliable protocol

Every message on `0x7c` is a 16-byte header and a body:

```
+0x00  4  kind: the channel id
+0x04  4  body length: 0x168 kind 1, 0xe8 kinds 2 and 4, 4 kind 3
+0x08  4  step, counting every message a station sends from 1
+0x0c  1  tag, 0 on every trade message
+0x0d  1  destination station index, 0xff for every station
+0x10     the body
```

`0x116f30` builds the header; trade senders go through `0x4d94e0`. The receive `0x1171d0` takes the
first queued message whose step is its station's next, drops one addressed elsewhere or of an
unregistered kind, and leaves one of another kind or tag queued, blocking everything behind it.

The kind is a channel id from a per-session u32 counter from 1 (`0x116e80`), registered at most 16
live at a time. A trade registers 1 (the trade session), 2 (the offer), 3 (the commit) and 4 (the
offer object the post-trade save re-creates). Each registration announces a clone set, so clone ids
differ from channel ids. Dead channels are compacted every frame, so one seat holds about four and
chains trades without limit.

Kind 1, body 0x168, the identity: the save's MyStatus block (PKHeX `MyStatus7b`, names UTF-16LE),
sent by both stations before either has received anything:

```
+0x00  4  trainer id, then secret id
+0x04  1  version: 42 Pikachu, 43 Eevee
+0x05  1  gender
+0x35  1  language
+0x38 26  trainer name; --trainer-name on both launchers
+0x52 16  Pokemon name
+0x90  4  the trade lock
```

A gift made for the receiving player reads the trainer here
([Made for the receiving player](gift_simulated.md#made-for-the-receiving-player)).
`pokeldn.lgpe.reference` ships one with trainer `POKELDN`; `--our-trainer` replaces its id pair.

Kind 2, body 0xe8, the offer, goes when the station's published state word reaches 2, and again under
a new step each time its player changes the selection. A new step is answered; a repeated step is a
retransmit. Answering an offer under a fresh step instead of its own opens a new round without end.
The sender is the party-offer object (`0x349bf0`, at `mgr+0x68`), which `0x34a3d0` refills on each
selection change when the trade status allows.

Kind 3, body 4, the commit ([The commit and the trade lock](#the-commit-and-the-trade-lock)): each
station sends a 1, and one sends a 2 on taking the peer's 1. A 2 received commits; any other body
after the 1 is ignored.

Kind 4, body 0xe8, rides the offer object the normal save re-creates 3000 ms after its save, after
the trade demo: first the station's first slot, then one per selection. It opens the next trade.

| step | kind | body |
|---|---|---|
| 1 | 1 | identity |
| 2 | 2 | the offer, again per selection |
| 5 | 3 | commit, 1 |
| 6 | 3 | commit, 2 |
| 7 | 4 | the first slot, again per selection |

Trade r, counted from 0, offers on kind 2 + 2r, commits on 3 + 2r and ends on 4 + 2r. Its party
clones are 2 + 3r and 3 + 3r, its commit clone 4 + 3r.

| launcher | chained trades |
|---|---|
| `bin/lgpe_host.py --next-offer` | answers each later trade's selections with the next record |
| `bin/lgpe_join.py --offer ...` | answers the console host's kind 4 with the next record; after the last it answers nothing |
| `bin/lgpe_host.py --lead` | plays a console host's part for `bin/lgpe_join.py`; `tests/test_esp32.py` |

Both launchers write the received record when the 2 is exchanged; a withdrawn offer writes nothing.

The body of kinds 2 and 4 is a 232-byte box structure: the generation 7 layout under generation 6
encryption, four 56-byte blocks from +0x08 permuted by `((ec >> 13) & 0x1F) % 24` and XORed with a
LCRNG stream seeded with the encryption constant. `pokeldn.lgpe.pb7`. The console saves it
unchecked: a shiny level 100 Ditto with a hidden ability, all IVs 31 and all AVs 200 shows unchanged
on the summary.

### What gates the game's own first message

The link-trade object's state machine is `0x349200` (jump table `0xf4e994` on +0x68).

| state | what it does |
|---|---|
| 3 | announces clone 1's set (`0x11aec0`), sets 4 |
| 4 | waits for the gate `0x11b080` |
| 6 | sends kind 1 with no network input |
| 7 | counts kind 1 messages, its own loopback included; moves to 8 at two |
| 8 | terminal; the screen says a player has been found |

The gate passes when the SendClone at +0x90 and the SharingClone at +0x1258 have every participating
station in their acknowledged set `clone+0xA8`, every party clone's completion byte `+0x110` is set,
and the station index at +0x1430 is not 0xFD. A station's bit reaches `clone+0xA8` only through an
0xa2 on clone type 2 from that station.

`0x11aec0` announces a station's clone set in one frame: `0x81` on clone type 2, `0xa1` on type 4
and `0xa1` on type 1. Clone ids 2 and 3 come about 3.2 s after id 1 from the trade dispatcher
`0x886530`, which publishes only while the mode word `+0x8C` is 3; the writer of that 3 is unknown.

### Hosting a retail console to its trade screen

- The Local Protocol body carries the host's constant id little-endian; big-endian, the console
  cannot resolve the sender and waits at state 7.
- The update session goes out when the session changes and once more behind it, never on a timer.
- The host announces clone 1 in the frame it publishes clone 0; the console announces its own about
  31 ms later, and a host that waits loses the race and the roles swap.
- The `0xa2` answering the peer's announcement of a host-owned clone carries the clock of the peer's
  `0xa1`; with the host's own clock the console re-announces forever.
- Both stations answer every clone type 2 publish with a copy of their own.
- A host must publish clone data on clone types 4 and 1, or a joining console stays on its search
  screen.

### The sequence a take-over has to carry

`0x520c30` allocates a sequence into `+0x10C` when it announces; the completion `0x520ce0` (an
`0xa2`) sets `+0x110` only when the value equals `+0x10C`, and `0x520d30` (a `0x91`) unlinks without
setting it. The value is the clock of the other station's latest `0xa1` for the clone. An `0xa2`
built from the joiner's own clock misses and the state word never leaves 4. An inbound `0x82` also
allocates, so answering each re-announcement with an `0x82` burst mints sequences without end.

### The take-over exchange a joiner runs once per clone

A take-over cancels the peer's announcement and announces the clone under the joiner's own clock:

```
+0 ms   host    0x81 clone 2, 0x81 clone 3, dest 0x0003
        host    0xa1 x2 per clone                        clock 0x197e, the host's
+5 ms   joiner  0x82, 0x91 x2, 0x82, 0x91 x2, 0x84 x2    echoing 0x197e
+75 ms  joiner  0x81 clone 2, 0x81 clone 3, 0xa1 x2 each clock 0x19c1, the joiner's own
+102 ms host    0xa2 per clone                           clock 0x19c1
        host    0xa1 per clone                           clock 0x19e2, the host's own
+141 ms joiner  0xa2 per clone                           clock 0x19e2
```

The joiner takes each clone over once. Every later re-announcement gets one `0xa2` carrying that
announcement's clock, on clone type 2 under the joiner's station, payload `<clock> 00 00 00 02`; a
second take-over makes the peer re-announce without limit.

A peer-only re-announcement draws the peer's `0x82` on clone type 1, which draws the host's type 4
copy the console answers with `1 1 1`. A host that receives no `0x82` for the commit clone stays on
its confirmation screen with its trade lock saved; `pokeldn.ldn.clone` resends the peer-only `0x81`
every 100 ms, at most 20 times, until the `0x82` arrives.

### The two clone records a trade walks

The clone type 2 copy's 20-byte data:

```
+0x00  4  state: 1 a vote, 2 a vote withdrawn, 4 a forced leave
+0x04  4  argument, 1 on selection and 2 on confirmation
+0x08  4  a counter, incremented on each call
+0x0c  4  the station's own step
+0x10  4  the trailing word
```

The clone type 4 copy's 32-byte data is the session host's (the authority's) view:

```
+0x00  4  A, the agreed argument
+0x04  4  B
+0x08 16  per station index: the counter of the vote it last saw withdrawn
+0x18  4  the station's step
+0x1c  4  the trailing word
```

The authority `0x11b6c0` moves A to X only when every station publishes state 1 with argument X on
the current trailing word, publishing A and the trailing word plus one together; a state 4 moves A
at once. For a station in state 2 whose argument differs from A it records the counter and moves the
trailing word on. A copy is replaced only by a record with a strictly newer clock;
`pokeldn.ldn.clone.Participant.record_clock` keeps each record's clock above the last. A host
publishing 32 zeros on type 4 leaves the console on "communication en cours".

The trade screen's status (`0x34a300`) comes from A and the local state:

| A | local state 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| 0 | 0 | 1 | 1 | 0 | 0 |
| 1 | 2 | 3 | 3 | 0 | 2 |
| 2 | 4 | 4 | 4 | 4 | 4 |
| 3 | 5 | 5 | 5 | 5 | 5 |

Status 4 starts the sync save, status 2 returns to the selection, 5 is the partner leaving.

The offered party clone walks `1 1 1`, trailing word 1, then `x 2 2`, trailing word 2. The commit
clone, one id above, takes the first two and then a zero:

```
+0 ms     type 4 data, 32 zeros, with the announcement
          the peer publishes 1 1 1 step 0 once its player has confirmed
          1 1 1 step 0                 the host's own confirmation
+30 ms    1 1 1 step 1                 type 4 data 1, zeros, step, 1
+8 ms     the peer answers 0 1 1 step 1
+27 ms    0 1 1 step+1 1               the offered clone goes 0 2 2 step+1 2,
                                       and the kind 3 carrying 1 goes under that step
+3 ms     the peer's kind 3 carrying 1
+63 ms    kind 3 carrying 2 under the next step, every copy republished under it
after the trade demo and the normal save:
          two more clones announced, 32 zeros on type 4; the peer publishes 0 0 0 on each
then      kind 4 under the next step
```

The peer answers trailing word 1 only when the type 4 copy's first word is 1. A console host
announces every clone and votes first; a joiner that takes each clone over and republishes the host's
first three words and trailing word under its own state word completes the trade.

Pressing A again on the confirmation withdraws the vote: `2 2 3` after `1 2 2`. Answering it with A
2 commits the trade lock without completing the exchange ([Unresolved](lgpe.md#unresolved)). The
answer `1 0 0 3 0 0 step T+1` returns the console to the selection; a withdrawn selection `2 1 4`
under A 0 takes `0 0 0 4 0 0 step T+1`. `bin/lgpe_host.py` answers so;
`tests/test_lgpe_host_withdraw.py` runs both through the game's code.

### The trade animation

The console plays its trade animation after its step `0e` and sends no trade payload during it. From
that step: the animation starts at about 1.7 s, the received Pokemon appears at about 15.3 s, the
console's type 4 payload (248 bytes) arrives at 27.0 s, and the player has control at about 28.8 s.

### The commit and the trade lock

The trade lock is a u32 countdown in seconds at MyStatus `+0x90` (`savedata.bin` `0x1090`; setter
`0x1c9d40`). A trade's sync save sets it to 600 and commits that before the commit exchange; the
exchange completing commits it back to 0. The link menu's check `0x9765f4` refuses a trade while it
is non-zero (`0x976634`, message `0x0248810f825b1fee`). The lock counts down only with counted play
time while the game is in focus, one second per second, at most one second per update.

`0x347190` builds one of three save sequences: normal save, sync save, fatal error. A trade uses the
sync save (update `0x838070`, jump table `0xf867c4`):

| state | what it does |
|---|---|
| 0 | waits for `SaveThread` (600 committed), decides whether this station sends the 2 (`0x838660`), applies the received Pokemon and zeroes the lock in memory (`0x838800`), starts `FirstSaveThread` |
| 1 | waits for `FirstSaveThread` to write, then a random delay of `2000 + r % 6000` ms |
| 2 | registers the commit channel |
| 3 | votes 1 on the commit clone, waits for the channel's gate |
| 4 | sends a kind 3 carrying 1 |
| 5 | takes the peer's kind 3; a body other than 1 aborts; the sending station sends a 2 |
| 6 | a received 2 signals the commit; any other body is ignored |
| 7 | waits for `FirstSaveThread` to commit |

No state has a timeout. Any network error recorded between the end of state 0 and the 2 aborts:
`FirstSaveThread` does not commit, the save keeps 600, and the dispatcher pushes the fatal error
`error_fatal_save` ("An error occurred. You couldn't trade Pokémon. Press the HOME Button to end the
game.", label id `0x191615296121e064` in `common/message_error.dat`), from which the game never
returns. A partner leaving the mesh during the commit records such an error.

| for a peer | consequence |
|---|---|
| an authority publishing A 2 | the console commits 600; the authority owes the whole commit exchange |
| a first kind 3 carrying anything but 1 | abort, lock set |
| a kind 3 sent before the receiver registered the commit channel | dropped; the state 3 vote holds it until both have registered |

`0x838660` decides who sends the 2: a station giving Articuno, Zapdos, Moltres, Mewtwo, Mew, Meltan
or Melmetal for any other Pokemon sends it, the reverse does not, and otherwise the station that was
the session host at session start (`mgr+0x128c`) does.

`0x838800` writes the received Pokemon over the own offered box slot and applies the trade's side
effects: Pokedex registration, trade evolution (method 5 always, 6 with the held item; method 7,
Shelmet with Karrablast, never matches because the arriving copy is passed as both Pokemon; the held
item is cleared for methods 6, 19, 20), and game record 476 (local trades) or 477 (trades while the
internet connection is up).

### The trade dispatcher

`0x886530` runs the link from the menu to its exit, switching on `[obj+0x68]` through `0xf87bc4`:

| state | what it does |
|---|---|
| 0 | setup; the link menu process writes the mode word `+0x8c` |
| 1 | mode 1 or 2 starts a link battle, then 6; mode 3 waits for the party-offer object to be ready; a network error goes to 8 |
| 2 | `[obj+0x100]` 5, the trade UI's proceed, starts the sync save; anything else goes to 8 |
| 3 | waits for the sync save; result 2 pushes the fatal error; otherwise destroys the offer object and starts the trade demo |
| 4 | releases the demo, state 5 |
| 5 | writes the received Pokemon into the box slot, starts a normal save, state 7 |
| 6 | state 8 |
| 7 | waits for the save; result 1 goes to 8, any other to 1 |
| 8 | destroys the offer object and leaves |

The save process gets a block at `obj+0x178`:

```
+0x00  save type: 0 sync save, 1 normal save, 2 or 3 fatal error
+0x04  result: 0 done, 2 aborted, 1 the link ends
+0x08  box index of the own offered Pokemon
+0x10  the received Pokemon
```

The normal save waits 3000 ms after its `SaveThread`, then re-creates the party-offer object on a new
channel. The dispatcher returns from state 7 to state 1, so one seat carries one trade after
another. The link menu's choice 1, the trade, stores mode 3; choices 2 and 3 store 1 and 2, single
and double link battles, which register their own channel with tags 1 and 3 and count into
`local_btl_single_cnt` and `local_btl_double_cnt`. A trade counts into `local_trade_cnt` (`0x1dc`)
or `net_trade_cnt` (`0x1dd`).

### A joiner leaving

A console backing out with Retour publishes state 4 on the offered clone, argument 0 then 3; the host
answers each with zeros in the first three words, the trailing word plus one, and the argument as the
type 4 copy's first word. Both release their clones (0x83, answered by 0x84). Once its clone protocol
is idle ([The wait before leaving](#the-wait-before-leaving)), the console sends a mesh leave request
`04 01` on the mesh protocol's reliable port.

It is owed the reliable acknowledgement and a leave response `08 00` (the mesh host's index) on the
unreliable port. `LeaveMeshJob` retransmits the request every 40 ms for up to 5000 ms. Answered
`08 00`, the console sends its own disconnection request and deauthenticates within 0.1 s;
unanswered, it deauthenticates at 5.0 s. After a Retour the host sends a station disconnection
request, type 3; the console answers type 4.

A console host answers a joiner's leave request with `08 00` twice, then repeats a Local Protocol
start host migration (type 0x13) every 0.3 s. A joiner's disconnection request returns the host's
player to the menu. `bin/lgpe_join.py --leave-after SECONDS` runs the exit (`pokeldn.lgpe.leave`);
`--stall-leave` (default 5) runs it when a vote stands unagreed before any kind 3. The exit does not
lift the trade lock.

### A host leaving

A console host whose player backs out publishes state 4, argument 3, releases its clones, and once
idle sends a mesh migration start `44 00 01` (host index, next host's index), retransmitted every
45 ms for up to 5000 ms until each station answers `48 <index>`. It then broadcasts an update
session carrying host migration state 1 and repeats start host migration (type 0x13) every 301 ms
until no other station is connected or 10000 ms have passed, then destroys the network (eight LDN
disconnect frames, reason 3). `bin/lgpe_join.py` answers the ack and `48 01` and leaves on the first
0x13 (`pokeldn.lgpe.leave.host_departure`).

### The wait before leaving

The teardown step `0x116bc0` ends the clone session and leaves at once when the clone protocol is
idle; otherwise it waits 150 calls, about 2.5 s. The protocol reaches idle once no clone has data
unacknowledged and every station has answered its 0x32 with 0x41. After its clone 0 release a console
keeps publishing clone type 2 copies about every 100 ms; a peer answering each with an 0xe3 on clone
type 1, station 0xFD, carrying the publisher's station and clock, lets it go idle and leave within
0.3 s. A peer answering with its own copies holds it for the full wait. `pokeldn.ldn.clone.Participant`
acks after the peer's clone 0 release.

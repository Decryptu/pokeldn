---
title: The Let's Go cartridge and session
parent: Let's Go Pikachu and Eevee
nav_order: 1
---

# The cartridge, its keys, and the session

Addresses are offsets into Let's Go Pikachu 1.0.2's decompressed `main` as `tools/switch/nso_read.py`
lays it out: text `0..0xd32ba8`, rodata from `0xd33000`, data from `0x1527000`.

## What the title is built from

The update NSP carries the Program NCA `2b7730a9e56498bbafac2002d4908c6b` (title `010003f003a34000`,
rights id `010003f003a348000000000000000007`, key generation 6). Its exefs holds `main` (13.0 MB
compressed), `rtld`, `sdk`, `subsdk0` and `subsdk1`; every `nn::pia` and `gflnet3` reference is in
`main`.

    ./.venv/bin/python tools/switch/xci_read.py "<the .nsp>" --keys prod.keys \
        --nca 2b7730a9e56498bbafac2002d4908c6b --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main main.bin
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0xd32ba8

Pia is statically linked: 269 `nn::pia` classes, 2112 named virtual methods. `nn::pia::local`
carries the `Ldn*` and `Local*` families (`LdnCreateNetworkJob`, `LdnCreateSessionSetting`,
`LdnJoinSessionSetting`, `LocalProtocol`). `nn::ldn` is imported from nnSdk (`CreateNetwork`,
`Connect`, `Scan`, `SetAdvertiseData`, `GetSecurityParameter`, the `*Private` variants), GOT slots
`0x15fa1e0..0x15fa2a8`. Above Pia, `gflnet3` bundles protocol buffers
(`lib/gflnet3/external/include/google/protobuf/`).

## The LDN passphrase

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL

64 bytes at `0xf73a50`, used raw, the same as Sword and Shield's. Two call sites pass it with a
literal length `0x40`:

    0x004db6b4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004db6c4  mov  w2, #0x40
    0x004db6c8  bl   #0x5c0fb0              LdnCreateSessionSetting passphrase setter

    0x004dbba4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004dbbb0  mov  w2, #0x40
    0x004dbbbc  bl   #0x5c1280              LdnJoinSessionSetting passphrase setter

`LdnCreateNetworkJob` (constructor `0x5ce640`, Sword's offsets) keeps the passphrase at +0xC4 and
its length at +0x104 and builds the `nn::ldn::SecurityConfig` from them before
`nn::ldn::CreateNetwork` (`0x5ce988`, PLT stub `0xd31c78`).

## The Pia game key

    p1frXqxmeCZWFv0X

Sixteen ASCII bytes at `0xefd659`, the literal key the wiki lists for Sword/Shield, Legends: Arceus
and Scarlet/Violet. One call site stores it into a crypto setting, conditional on a mode field:

    0x0011a364  ldr  w9, [x19, #0x98]
    0x0011a368  orr  w9, w9, #2 ; cmp w9, #2 ; b.ne   (mode 0 or 2 takes the key)
    0x0011a374  adrp x9, #0xefd000 ; add x9, x9, #0x659
    0x0011a380  ldp  x10, x9, [x9]
    0x0011a384  stp  x10, x9, [x8]          x8 = setting + 0x24c

## The Pia header

Version 3 (the wiki's Pia 5.11-5.17). The initializer `0xd122d4` writes magic and version as one
64-bit store, `0x00000003_32AB9864`; the validator `0xd12400` checks the magic and
`(byte & 0x7f) == 3`.

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 3
    0x05  1  connection id
    0x06  2  packet id
    0x08  8  AES-GCM nonce
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext

The wiki's 5.11-5.21 layout, Sword's version 4 but for the version byte; `pokeldn/ldn/pia4.py`.

## The message framing

A fixed 22-byte message header (Pia 5.11-5.12; 5.18 and later are presence-flagged).
`ProtocolMessageAccessor::Header`'s deserializer `0x5ae870` refuses fewer than `0x16` bytes; the
writer `0x5aeb00` stores a literal 1 at byte 1.

    0x00  1  message flags: 1 = destination is a bitmap, 2 = relay needed, 4 = relayed, 8 = unbundled
    0x01  1  version, always 1
    0x02  2  payload size, big-endian
    0x04  1  protocol type
    0x05  1  protocol port
    0x06  8  destination, big-endian: a constant id, or a station bitmap when flag 1 is set
    0x0E  8  source constant id, big-endian
    0x16     payload, then padding to a multiple of 4

`pokeldn/ldn/pia3.py` implements it over pia4's header.

## The session key

`LocalProtocol`'s derivation `0x5cd560` is BDSP's and Sword's: seed a SEAD xorshift128 from one
32-bit value (`0x57cfc0`, recurrence around `0x6C078965`), four draws into sixteen bytes,
AES-128-ECB under the game key at `LocalProtocol+0x49c` (enabled flag +0x498).
`pokeldn.ldn.pia5.ldn_session_key`.

The advertisement's application data (Pia 5.9-5.18) opens with a 24-byte header:

    0x00  4  network id, random per session
    0x04  4  CRC32 of the user password
    0x08  1  system communication version, 4 for 5.11-5.17
    0x09  1  header size, 0x18
    0x0A  2  padding
    0x0C  4  session param
    0x10  8  zero
    0x18     the game's application data

The seed is the session param at +0x0C. 392 of 392 datagrams from a Let's Go Pikachu host
authenticated under `ldn_session_key(game key, session param)` with the pia4 IV (three bytes of
`crc32(network id little-endian || host MAC)`, a source-id byte 0, the eight-byte header nonce).

## The link code

The link code is the NetworkInfo scene id; the password CRC32 at application-data +4 stays 0 and
the SSID stays `01000000000000000000000000000000`. The scene id is `1000a + 100b + 10c + 1`, each
pick its index in the picker (Pikachu 0, Eevee 1, Bulbasaur 2, Charmander 3, Squirtle 4, Pidgey 5,
Caterpie 6, Rattata 7, Jigglypuff 8, Diglett 9).

It is built at runtime: `0x891580` folds the picks into `100a + 10b + c`, `0x978080` computes
`10 * number + mode`, mode 1 for a trade (modes 2 and 3 come from the switch at `0x9765f4`, their
features unread). The value passes `0x349010` and `0x4da710` to the session constructor `0x4db1e0`
(`u16` at `+0x302`); `0x4db6ac` puts it into `LdnCreateSessionSetting+0x60`, and Pia copies it into
`NetworkConfig.intentId.sceneId` before `nn::ldn::CreateNetwork` (`0x5ce988`).

The same constructor picks the channel a searching console hosts on: `{1, 6, 11}[scene % 3]`, table
`0xf73a44`, indexed at `0x4db248..0x4db254`; `pokeldn.lgpe.search_channel(code)`.

| code a console searched with | scene id advertised | channel |
|---|---|---|
| Pikachu, Pikachu, Pikachu | 1 | 6 |
| Bulbasaur, Charmander, Squirtle | 2341 | 6 |
| Bulbasaur, Charmander, Bulbasaur | 2321 | 11 |
| Eevee, Pikachu, Diglett | 1091 | 11 |
| Pikachu, Pikachu, Bulbasaur | 21 | 1 |

A searching console hosts its own network and joins another only when that network advertises its
scene id on its own channel (`{1, 6, 11}[scene % 3]`). `bin/lgpe_host.py --code NAMES` hosts on the
code's channel (`--channel auto` scans for the console's network instead); Let's Go Pikachu and Let's
Go Eevee join it. `bin/lgpe_join.py` sends no code, and a console host trades with it.

## The Local Protocol, measured

The session state goes out on Pia protocol 0x24, port 0, as on BDSP and Sword: the wiki's 5.7-5.45
update-session message (`pokeldn.ldn.local_protocol.parse_update_session`). A 12-byte local header
(version 1, type 0x11), a sequence id, the local network id, the host variable id, service variable
id and constant id, an allow-participating byte, and eight nodes (IPv4 address, port, migration
ranking): host `169.254.105.1` ranking 0, joiner `169.254.105.2` ranking 1, the rest 255.

The body carries the host constant id little-endian (`000048f120229beb`,
`station_protocol.ldn_constant_id` over MAC `48:f1:eb:20:9b:22`); the Pia message header carries it
big-endian as the source (`eb9b2220f1480000`), as on Sword.

## The station protocol, for a mesh join

A connection request on protocol 0x14, then a mesh join on 0x18. The connection-request handler
`0x5b8800` reads the wiki's 5.10-5.18 layout, station-protocol version 9:

    [0]     message type            1
    [1]     connection id
    [2]     version number          must be 9 (`cmp w8, #9` at 0x5b8848; 5.27-5.45 checks a platform)
    [3]     is inverse connection request; rejected above 1
    [4]     target constant id      big-endian u64, compared against the console's own at 0x5b6830
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1 (0x5b6840)
    [0x10]  inverse connection id   compared against the station's own record at +0xA0
    [0x11]  station location        the 5.11-5.45 layout, unchanged from Sword
    [...]   ack id                  u32, the message size minus four

Sword's version-4 request (platform byte at [2], shift flag at [3]) and the 5.29-5.45 layout
(protocol list at [1]) land every field in the wrong place here. The target constant id is the
console's own, from its MAC; the joiner's location carries its constant id, variable id and service
variable id.

A retail Let's Go Pikachu runs the full version-9 sequence, with the inverse connection request
that 5.27 removed:

    ->  connection request (type 1, is_inverse 0, target the host constant id, own location)
    <-  type-5 ack; inverse connection request (type 1, is_inverse 1) to the joiner's constant and
        variable ids, with the host's location and a trailing ack id
    ->  type-5 ack; connection response (type 2, result 0, host constant id at [5], variable id at
        [0xD], gate byte 1 at [0x37], padded to 0x38)
    <-  connection response (type 2, result 0, 840 bytes, platform 4, the joiner's ids, a network
        id, one player info), repeated until acknowledged
    ->  type-5 ack

The connection-response parser `0x5b9270` reads `[1]` the result, `[5]` a big-endian u64 and
`[0xD]` a big-endian u32 against its own ids, and `[0x37]` a gate byte the result-0 path drops when
5 or more.

### The connection response a station sends

0x348 bytes (the parser accepts 0x3C):

    0x00  1  message type 2
    0x01  1  result
    0x02  1  version 9
    0x03  1  platform 4
    0x05  8  the receiver's constant id, big-endian
    0x0D  4  the receiver's variable id, big-endian
    0x31  4  the network id, big-endian: the advertise data's first u32, read little-endian
    0x35  2  01 01
    0x37  0xC3  a PlayerInfo: the station name "username", then the Switch profile's nickname,
             then the language. Its first byte is the gate the parser drops when 5 or more
    0x344 4  the ack id

The PlayerInfo is the 195-byte structure `station_protocol.player_info` builds; a retail console
fills it with its profile name. `station9.build_connection_response(..., network_id=N,
player_name=B)`; `bin/lgpe_join.py --player-name NAME` (`--short-response` sends 0x3C bytes).

A joiner's station location in the connection request is 36 bytes: an empty public address (a
zero port) and zero NAT flags and location, `station_location(..., public=False, nat_flags=0,
nat_location=0)`.

## Joining the mesh

A mesh join request on 0x18 (`mesh_protocol.build_join_request`, type 1, local station index 253, a
trailing ack id) draws the join response: type 2, 148 bytes, two stations, host index 0, joining
index 1, one fragment, two station infos with both locations, max active 2, max total 8. The host
then broadcasts an update mesh (type 0x20, 524 bytes, update counter 1). The join response is
acknowledged by a type-5 ack on 0x14 (`mesh_protocol.ack_for`); the joiner is station index 1.

The host then streams the Local Protocol update-session (0x24, acked with a 0x21), RTT (0x58), Sync
Clock (0x1C) and Clone (0x73). A joiner answers each and sends its own RTT and sync clock requests
from the moment it is seated.

## The RTT Protocol (0x58), version 3

Sixteen bytes: the kind a big-endian u32 at [0] (a byte on Sword), the sender's 19.2 MHz system tick
as a u64 at [8]. A response copies the tick with kind 1. Each station requests about once a second.

    00000000 00000000 0000000049845557     request
    00000001 00000000 0000000049845557     the answer to it

`rtt_protocol.build_v3` and `response_for_v3`; `bin/lgpe_join.py --connect` runs both directions
(`--no-rtt` turns them off).

## The Sync Clock Protocol (0x1C)

A monotonic mesh clock the host controls (wiki Sync-Clock-Protocol). A station requests every two
seconds and adds half the round trip to the value the host replies with.

    request, 16 bytes   [0] u64 the sender's system tick (19.2 MHz), [8] u64 zero
    reply,   16 bytes   [0] u64 the tick copied back, [8] u64 the mesh clock in milliseconds

A joiner sends its first request right after the mesh join response. Clone Protocol clocks are this
clock: a host given clone messages timed on the joiner's own uptime was measured releasing the clone
and leaving. `pokeldn.ldn.sync_clock`; `bin/lgpe_join.py --connect` runs it (`--no-sync-clock` to
stop).

Keep-alive is protocol 0x08, no body, answered in kind.

## The Reliable Protocol (0x7C), where the game's data is

Pia 5.11's header is 24 bytes (9 or 13 in 5.29-5.43); 32-bit sequence ids start at 0xFFFFF82F on
both stations.

    0x00  1  flags
    0x01  1  stream id, 3 for the game's stream and 0 on an acknowledgement
    0x02  2  payload size, big-endian
    0x04  4  zero
    0x08  4  sequence id, big-endian
    0x0C  4  the next sequence id expected from the peer, big-endian
    0x10  8  zero
    0x18     the payload

An acknowledgement is the header alone, stream and size zero. `pokeldn.ldn.reliable3`. The payload
is the game's framing ("The game's messages on the reliable protocol" below).

## The Clone Protocol (0x73)

`nn::pia::clone::CloneProtocol` (GetProtocolId `0x158aab8`; SDK string `PiaCommon-5_11_4`) carries
the partner sync. Type byte `0xAB`: high nibble the structure, low nibble a variant. Every message
starts with version 3, the type, and the sender's frame counter as a big-endian u16 (about 60 per
second from the sender's Pia session start). Measured between two Let's Go Pikachu 1.0.2 endpoints
under Ryujinx over ldn_mitm; both sides run the same state machine.

### Clock sync, the first two seconds

Both sides send clock requests (type 0x11, 18 bytes, serializer `0x51f9b0`) about 5 per second and
answer the other's with a reply (type 0x21, 22 bytes, `0x51fab0`).

    clock request                              clock reply
    [0]   1  version 3                         [0]   1  version 3
    [1]   1  type 0x11                         [1]   1  type 0x21
    [2]   2  sender frame counter              [2]   2  sender frame counter
    [4]   4  sender message count              [4]   4  sender message count
    [8]   2  destination station bitmap       [8]   2  destination station bitmap
    [0xA] 8  sender system tick                [0xA] 4  sender clone clock, ms
                                               [0xE] 8  the request's system tick, echoed

- The message count is one counter per sender over its clock requests, replies and participates,
  from 1.
- The bitmap is the destination, `1 << station index`: host (0) sends 0x0002, joiner (1) 0x0001. A
  reply goes to the requester.
- The tick is the sender's `os::GetSystemTick`, 19.2 MHz; a reply echoes the request's tick and
  nothing else.
- The clone clock is milliseconds since the sender's clone protocol started (element +0x14), about
  60 ms before its first request. A reply with the clock zero leaves a retail console requesting.

### Participate

After ten answered requests the joiner sends a participate (type 0x31, 10 bytes, serializer
`0x51fbd0`): header, message count, bitmap 0x0003. The host answers with 0x33, bitmap 0x0002, and
then sends its own participate, which the joiner acknowledges with 0x33, 0x0001 (2.1 s, 30 ms and
1.1 s between the two emulated endpoints).
From the first participate, clock replies are type 0x22.

### Clone elements

A clone is keyed by a clone type (1 to 4), the owning station (0xFD when none) and a 32-bit clone
id. Both stations publish their own copy. In the first trade the host creates ids 1, 2, 3 as the
trade screens advance; each later trade announces more. Clone type 3 id 0 exists once both sides
have participated.

    every command message   [0] version 3, [1] type, [2] u16 the sender's frame counter,
                            [4] u8 clone type, [5] u8 owning station, [6] u16 0,
                            [8] u32 clone id
    types 0x81 to 0xc4      [0xC] u32 the sender's message count, [0x10] u16 destination bitmap,
                            then the structure's own fields
    types 0xd1 to 0xf4      [0xC] the data, with no message count and no bitmap

The low nibble is the command token plus one: 1 announce (`SendClone::AnnounceCommandToken`,
`0x522480`), 2 request (`ReceiveClone::RequestCommandToken`, `0x520df0`), 3 end
(`SendClone::EndCommandToken`, `0x522490`), 4 lock (`AtomicSharingClone::LockCommandToken`,
`0x517820`). The high nibble is the structure; `0x51c110` dispatches it through table `0xf769c4`:

| type | adds | message, length | receive case |
|---|---|---|---|
| 0x8N | nothing | 0x12 | `0x51c614` |
| 0x9N | a u32 clock in ms at [0x12] | ClockCloneCommandMessage, 0x16 | `0x51c62c` |
| 0xaN | the clock, a u8 count at [0x16], a u8 and a u16 | ClockAndCount, 0x1a | `0x51c64c` |
| 0xbN | the clock, a u32 participant bitmap at [0x16] | ClockAndParticipant, 0x1a | `0x51c66c` (`0x51c680`) |
| 0xcN | the clock, the count, the bitmap at [0x1A] | ClockAndCountAndParticipant, 0x1e | `0x51c68c` |
| 0xeN | a zlib stream at [0xD] | the clone's state, acknowledging | |
| 0xfN | a byte at [0xD], a zlib stream at [0xE] | the clone's state, with its data | |

The zlib streams inflate to a record: tag 0x20, its length, a u16 clone id, and 1 while the copy is
empty, 3 once full:

    0x20 0x06 u16 clone id  0x01  0x00
                                          a copy with nothing in it yet
    0x20 len  u16 clone id  0x03  u8 the station the data belongs to  u16 0
              u16 participant bitmap  u32 clock  then the clone's data
    0x20 0x0A u16 clone id  0x05  u8 the station being acknowledged   u32 clock

A station publishes the six-byte form first, the filled one after; the six-byte form is a publish
being retried, and a settled session builds no records. The deflate is one compress, a sync flush
and a final empty block at a level 2 to 5; `clone.pack_record` reproduces every captured stream.
The 0xfN header's byte at [0xC] carries the record's participant bitmap, the 0xeN header's the
station it acknowledges.

| exchange | messages |
|---|---|
| owner announces | 0xa1, and 0xb1 with the participant bitmap; the other answers 0xa2 and 0xc1 before the data |
| take-over | the other answers an 0xa1 with 0x91 |
| data | the owner's 0xf3; the other's 0xe3 with the same clock |
| release | 0x83; 0x84 acknowledges |
| leave the clone session | 0x32; 0x41 (14 bytes, the answerer's bitmap at [0xA]); an unanswered 0x32 repeats until the game gives up |

An 0xa2 carries the mesh clock and the count, 1 on clone type 4 and 0 on clone type 2.

`ClockAndCountCloneCommandMessage` (vtable `0x158ac58`, serializer `0x51f4c0`) writes, big-endian,
`+0x1c` (clock) at [0x12], `+0x20` (count) at [0x16], `+0x21` at [0x17], `+0x22` (u16) at [0x18].
The count is the clone's vfunc 16: 0 for a SendClone (`0x519290`), `+0x112` for a ReceiveClone
(`0x520de0`), `+0x188` for an AtomicSharingClone (`0x517800`). Bytes `0x17..0x19` are stack residue
no receiver reads: the builders (`0x51b3b0`, `0x51cb64`, `0x51ccf0`, `0x51cd8c`) store nothing past
the count, and the sweeper `0x51b380` reuses a buffer whose 0xbN path leaves a participant word
there (`0x51b7a0`), hence `01 2808ab`. `0x51c110` parses in place; every payload reaches it from the
receive loop `0x51ad90` or the loopback (`0x51e330`, `0x51e4c4`).

`0x51c110` reads the common header (`0x51c2c0`: `[8]`, `[4]`, `[5]`), for groups 0x80..0xc0 bytes
0x10-0x11 (`0x51ce80`, table `0xf76e08` -> `0x51ced0`), then the fields in the table above and no
further. The clone-type table `0xf769e4` (index `[4] - 1`) routes 0xa1 and 0xa2 to handlers taking clone,
station and clock, never the buffer:

| clone type | 0xa1 | 0xa2 |
|---|---|---|
| 1 | `0x51c714` -> `0x51cb38`, `0x522350(clone, station, clock)`; an unknown clone draws a 0x91 | ignored |
| 2 | ignored (`0x51c3b8`) | `0x51cafc`, `[5]` must be the local station, `0x520ce0(clone, clock)` |
| 3 | `0x51c934` -> `0x51cc00`, `0x522a60` | `0x51c838`, `0x522b20(clone, station, clock)` |
| 4 | `0x51c8c0` -> `0x51cbc4`, `0x522a60` | `0x51c838` |

The onward calls carrying the buffer (`0x51c268`, `0x51c2fc`, `0x51c32c`, `0x51c784`, `mov x3,x22;
b 0x51d450`) serve other message types.

`0x522a60`, the 0xa1 handler of clone types 3 and 4, returns 1 when the element's state
`[x0+0x38]` is not 1, 2 when the sender's bit is set in `[[x0+0x30]+0xc0]`, else records the station
and returns 0. The caller answers 0 with an 0xa2 of type `0xfd04` (`0xfd03` on clone type 3,
`0x51cd00`), 1 with an 0x91 (`0x51cbe4`), 2 with nothing. An 0xa1 for an unknown clone draws an
0x91 directly (`0x51c494`). `0x51c110` drops silently at the destination check `0x51ce80`, the
per-sender count filter (`0x51c1e0`: the count at `proto+0x714+4*station` at least the message's
`[0xC]`), and the length and type range checks.

The mask `+0xc0` belongs to the clone protocol object, beside its station mask `+0x38` and state
word `+0x40`:

| event | effect on `+0xc0` | address |
|---|---|---|
| state becomes `0x22` (when `[[proto+0x48]+0x24]` is 2 to 4) | set to `+0x38` | `0x51b060..0x51b06c` |
| state becomes `0x42` | set to `+0x38` | `0x51b140..0x51b150` |
| a station joins in state `0x22` or `0x31` | its bit set | `0x51bc64..0x51bc88` |
| a 10-byte 0x33 in state `0x31` or `0x22` | sender's bit cleared | `0x51c354..0x51c3b4` |
| a 14-byte 0x41 with `[0xa..0xd]` equal to `[proto+0x3c]`, in state `0x42` | sender's bit cleared | `0x51c380..0x51c3b4` |
| a station leaves | its bit cleared | `0x51bce0..0x51bce8` |
| a station leaves in state `0x42` | set to `+0x38` | `0x51bd04..0x51bd18` |
| other paths | zeroed | `0x519a1c`, `0x519ccc`, `0x51a2d4`, `0x51a7d0`, `0x51a9c0` |

In state `0x22` the protocol waits for the mask to empty before moving to `0x31`
(`0x51b074..0x51b084`).

### The game's messages on the reliable protocol

Every message on `0x7c` is a 16-byte header and a body:

```
+0x00  4  kind: the channel id, 1 to 4 in one trade
+0x04  4  body length: 0x168 for kind 1, 0xe8 for kinds 2 and 4, 4 for kind 3
+0x08  4  step, counting every message a station sends from 1
+0x0c  1  tag, 0 on every trade message
+0x0d  1  destination station index, 0xff for every station
+0x0e  2  zero
+0x10     the body
```

`0x116f30(mgr, kind, buf, len, tag, dest)` builds the header at `mgr+0x288`, step `mgr+0x274` plus
one. Trade senders go through `0x4d94e0` (tag 0, destination 0xff): `0x34945c` (kind 1), `0x34a24c`
(the offer), `0x838300` and `0x83838c` (the commit). `0x4d9520` takes both from its caller; its
callers are the battle scene's senders in `0x9dce94..0x9dede8`, one with tag 3.

The receive `0x1171d0` takes the first queued message, from any station, whose step is its
station's next (`mgr+0x278[station] + 1`, `0x117334..0x117354`), counting every message taken or
dropped. It drops (`0x11722c`) a message addressed neither to 0xff nor to the local station index
`mgr+0x1288` (0xfd before a session), or of a kind no channel registered (16-entry table
`mgr+0x110`, `0x117398..0x1173f8`). A message of another registered kind or tag stays queued and
blocks every message behind it from any station. Trade receivers (`0x4d9570`) ask for tag 0
(`0x11746c..0x117478`).

The kind is a channel id, handed out by `0x116e80` from a per-session counter `mgr+0x270` from 1
(zeroed with the step counter only at session start, `0x116a10`) and stored at `chan+0x60` by
`0x4d9450`; with 16 channels registered (`mgr+0x118 > 0xf`) the id is 0. `0x117920` compacts out
channels whose live count `+0x54` is zero. `0x4d9450`'s five callers: the trade session object
(`0x3492f8`), the party-offer object (`0x349d88`), the sync save's state 2 (`0x8382a8`), the
`0x347e10` class (`0x3481fc`), the battle scene (`0x9dce1c`). A trade registers 1, 2, 3 with the
first three and 4 with the party-offer object the post-trade save re-creates. Each registration also
announces a clone set (`0x4d94b8`, the thunk `0x11b4c0` into `0x11aec0`), so clone ids differ from
channel ids.

Kind 1, body 0x168, the identity: the save's MyStatus block copied to `obj+0x450` (`0x3493f4`),
sent from state 6 by both stations before either has received anything. UTF-16LE names at body
offsets:

```
+0x34  2  0x0002
+0x38 16  trainer name
+0x52 16  Pokemon name
```

`pokeldn.lgpe.reference` ships one, recorded from an emulated save whose trainer is `POKELDN`.
`bin/lgpe_join.py` sends it by default, the trainer id pair replaced by `--our-trainer`.

Kind 2, body 0xe8, the offer, goes the instant the station's published state word reaches 2, and
again under the next step each time its player changes the offered Pokemon (the selection browses
the box). A new step is answered; a repeated step is a retransmit and is not.

The sender is the party-offer object (constructor `0x349bf0`, 0x278 bytes, at `mgr+0x68`). Its
update `0x34a210` sends the structure at `+0xa0` whenever `+0x270` is set and `+0x272` clear, then
clears `+0x270`. `0x34a3d0`, called by the trade UI on a selection change (`0x8f0c04`, `0x8f0c38`,
`0x8f8fb0`, `0x90b87c`, `0x90b8c0`), packs a Pokemon into `+0xa0` (`0x7294e0`) and sets `+0x270` when
the status allows (A 0: local state other than 1 or 2; A 1: local state 3 or above 4; A 2: never;
A 3: the partner leaving, `0x3490c0`). `0x344620` destroys the object after the commit (`0x886c70`)
and when the link ends (`0x8869f0`); the normal save after a trade re-creates it (`0x8375a4`) on a
new channel id.

Kind 3, body 4, the commit, a u32 sent by the sync save ("The commit and the trade lock" below):
each station sends a 1, and one sends a 2 after the peer's 1. The station that sends the 2 sends it
on taking the peer's 1 (state 5, `0x838310`); a 2 received in state 6 commits, any other body is
ignored (`0x83839c`), so a joiner also answering the 2 with a 2 is tolerated.
After its commit a station shows a spinner with no button prompt. An incomplete exchange leaves the
trade lock set.

Kind 4, body 0xe8, rides the channel of the party-offer object the normal save re-creates 3000 ms
after its `SaveThread` (`0x8377ec`, `0x8375a4`), after the trade demo, and carries the next trade's
selection: first the station's first slot (byte-identical to its step-2 offer), then one per
selection. A trade is saved before kind 4 goes out; kind 4 opens the next trade.

Trade r, counted from 0, offers on kind 2 + 2r, commits on 3 + 2r and ends on 4 + 2r, the offer
channel of trade r + 1 (`0x116e80` hands out ids from a per-session counter; the dispatcher
re-registers both channels each trade). In the two consecutive trades measured, trade r's party pair
was clones 2 + 3r and 3 + 3r and its commit clone 4 + 3r; the pair announced after a trade's save
belongs to the next trade. Hosting, `bin/lgpe_host.py
--next-offer` answers the console's selections in each later trade with the next record. Joining,
the console host's first kind 4 is its first slot: `bin/lgpe_join.py` answers it and each later
selection with its next `--offer`, answers the commit on kind 5, and takes kind 6 as that trade's
end; after its last record it answers nothing.

A console host runs each later trade as the first: the next party pair announced before its first
kind 4, a kind 4 step per selection, the commit clone at its confirmation, the commit on kind 5, and
the following pair announced before kind 6. `bin/lgpe_host.py --lead` plays a console host's part,
offering and voting unprompted, for `bin/lgpe_join.py`; `tests/test_esp32.py` trades two records
each way between the two.

A complete trade, both stations counting their own steps:

```
step 1  kind 1   identity
step 2  kind 2   the offer, again under a fresh step per selection
step 5  kind 3   commit, body 1
step 6  kind 3   commit, body 2
step 7  kind 4   the first slot, again under a fresh step per selection
```

The body of kinds 2 and 4 is a 232-byte box structure: the generation 7 layout under generation 6
encryption, encryption constant at +0x00, zero sanity word at +0x04, checksum at +0x06, four 56-byte
blocks from +0x08 permuted by `((ec >> 13) & 0x1F) % 24` and XORed with a 16-bit LCRNG stream seeded
with the constant. `pokeldn.lgpe.pb7` round-trips a captured offer byte for byte.

The state word is byte 12 of the `f3` state data and walks 0, 1, 2 on every clone a station owns. A
station that publishes 2 and sends its kind 2 waits for the peer's kind 2.

### What gates the game's own first message

The link-trade object's per-frame state machine is `0x349200` (jump table `0xf4e994` on +0x68).
State 6 sends the first game message with no network input: two stations send it 18 ms apart before
either has received anything. The only gate is state 4, `0x11b080`, asking whether the Pia channel
is ready:

- a SendClone at the object's +0x90 reports ready (`0x5221b0`): its element's participating
  stations, `element+0x3C`, must all be in the clone's acknowledged set, `clone+0xA8`;
- a SharingClone at +0x1258 reports ready the same way (`0x522610`);
- every station's entry at +0x250, one per 0x118 bytes, has 1 in its first word and a non-zero
  byte at +0xD8;
- the byte at +0x1430, a station index, is not 0xFD ("none"; every such path returns 0).

The SendClone's check is `(element+0x3C & ~clone+0xA8) == 0`, the SharingClone's
`((clone+0x114 | ~clone+0xA8) & element+0x3C) == 0`; both share one element. In a working session
the acknowledged set fills, `+0x114` drains and every `+0xD8` becomes 1, while the participating set
is full from the start. A station's bit reaches `clone+0xA8` only through an 0xa2 on clone type 2
from that station (`0x51c52c`'s jump table `0xf76c38` into `0x522350`).

State 7 stores each arriving first message at `this + node * 0x1C8 + 0xC0` and counts them at
`this+0x470`; its own loops back, so a silent partner leaves the count at one.

### Hosting a retail console to its trade screen

What a console joining a hosted session needs, above the joiner's layers:

- The Local Protocol body carries the host's constant id little-endian. The game resolves a sender
  through the station table (`0x1171b0` -> `0x5bbe70` -> `0x5b6130`) and the receive at `0x117334`
  skips an unresolved one (node 0xFD): with the id big-endian the console waits at state 7, its
  screen saying it will soon be connected.
- The update session goes out when the session changes and once more behind it, never on a timer.
  Its node list holds one node until the peer has joined the mesh.
- A station stops its clone clock requests the moment it participates.
- The host announces clone 1 in the frame it publishes clone 0; the console announces its own tens
  of milliseconds later (31 ms measured), and a host that waits loses the race and the roles swap.
- The `0xa2` answering the peer's announcement of a host-owned clone carries the clock from the
  `0xa1` behind the `0x81`, so it is built after the whole datagram is parsed. Carrying the host's
  clock, it leaves the console re-announcing every half second and never publishing its copy.
- Both stations answer every clone type 2 publish with a copy of their own, about ten a second for
  the whole session.
- An offer is answered under the step it carried; answering under a fresh step opens a new round
  and the stations answer each other without end.

### The two clone records a trade walks

The trade object publishes its state on its own clone and reads the peer's. The clone type 2 copy's
20-byte data is five words, written by `0x11bc00` and its siblings:

```
+0x00  4  the state: 1 a vote (0x11bc00), 2 a vote withdrawn (0x11b4e0), 4 a forced leave (0x11bcf0)
+0x04  4  that call's argument, 1 on selection and 2 on confirmation
+0x08  4  a counter, incremented on each call
+0x0c  4  the station's own step, the number of game messages it has sent
+0x10  4  the trailing word
```

The clone type 4 copy's 32-byte data is the session host's (the authority's) view:

```
+0x00  4  A, the agreed argument
+0x04  4  B
+0x08 16  one counter per station index (host 0, joiner 1): the counter of the vote it last saw withdrawn
+0x18  4  the station's step
+0x1c  4  the trailing word
```

The authority `0x11b6c0` runs every tick on the session host. It moves A to X only when every
station publishes state 1 with argument X on the current trailing word, publishing A and the
trailing word plus one together; a state 4 moves A at once. For a station in state 2 whose argument
differs from A it writes that station's counter into its slot, moves the trailing word on by one,
keeps A and B, and republishes its own type 2 under the new trailing word.

The trade screen's status comes from A and its own record's state through `0x34a300` (jump table
`0xf4e9b0` on A); `+0x271` set with `+0x272` clear gives 1 first.

| A | local state 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| 0 (table `0xf4e9d0`) | 0 | 1 | 1 | 0 | 0 |
| 1 (table `0xf4e9f0`) | 2 | 3 | 3 | 0 | 2 |

A 2 gives 4 whatever the local state, and A 3 gives 5, the partner leaving (`0x3490c0`).

The similar status function `0x3488b0` (tables `0xf4e920..0xf4e980`, loop `0x9c3300`) belongs to the
class `0x347e10` (0x718 bytes at `mgr+0x70`, created by `0x344690`), which `0x886530` creates in
modes 1 and 2.

The trade UI's update (`0x756a20`, sub-state `[ui+0xa8]`) works off the party-offer object
(`0x7568ec`). Confirmation votes 2 (`0x756e34` -> `0x34a4e0` -> `0x11bc00`), sub-state 2
(`0x757058`). There status 4 writes 5 at `[[x21+0x78]+0x60]`, calls `0x74a590(ui, 2)` and proceeds
(`0x756c0c..0x756c38`); status 2 returns to the selection (`0x756cb4`); menu result 3 under status 1
or 3 withdraws the vote (`0x756d94` -> `0x34a500` -> `0x11b4e0`, state 2). In sub-state 0, status 1
with `[x22+0x258]` zero calls `0x34a4a0` (`0x756b94`), the other withdrawal.

`0x11b688` stages an arriving clone type 4 record at `+0x1638`; `0x11ba20` compares `+0x1638` with
`obj+0x04`, `+0x163c` with `obj+0x10`, and one word per node from `+0x1640` with `obj+0x0c`. A host
publishing 32 zeros there leaves the console on "communication en cours" with every button but
Retour greyed.

The offered party clone walks `1 1 1`, trailing word 1, then `x 2 2`, trailing word 2. The commit
clone, one id above the party clones, takes the first two and then a zero. The host's frames,
retail and emulated alike, clone type 2 data as five words:

```
+0 ms     type 4 data, 32 zeros, with the announcement
          the peer publishes 1 1 1 step 0 once its player has confirmed
          1 1 1 step 0                 the host's own confirmation
+30 ms    1 1 1 step 1                 type 4 data 1, zeros, step, 1
+8 ms     the peer answers 0 1 1 step 1
+27 ms    0 1 1 step+1 1               the offered clone goes 0 2 2 step+1 2 in the same frame,
                                       and the kind 3 carrying 1 goes under that step
+3 ms     the peer's kind 3 carrying 1, its copies under its own next step
+63 ms    kind 3 carrying 2 under the next step, every copy republished under it
after the trade demo and the normal save (3000 ms past SaveThread, 0x8377ec):
          two more clones announced, 32 zeros on type 4; the peer publishes 0 0 0 on each
then      kind 4 under the next step, every copy republished under it
```

The peer answers trailing word 1 only when the type 4 copy's first word is 1; built before the
peer's `1 1 1` landed, it carries 0 and the console waits. Walking the commit clone on to `1 2 2`
draws `0 1 1`, trailing word 2, no kind 3, and the console sits on its confirmation screen.

A console host announces every clone first: clone 1, the party pair 2 and 3 before its first slot,
the commit clone 4 after its A 2 (state 1's random delay, `0x8380d8`), and the next pair 5 and 6
after its save, then its first kind 4. It votes first as well: `1 1 1` on clone 3, A 1 with trailing
word 1, `1 2 2`, A 2 with trailing word 2; on the commit clone `0 0 0`, `1 1 1`, A 1 with trailing
word 1, then `0 1 1` with the kind 3 carrying 1, 152 ms after announcing it. A joiner that takes
each clone over and republishes the host's first three words and trailing word under its own state
word completes the trade.

Pressing A again as the confirmation greys the buttons withdraws the vote: `2 2 3` (state 2,
argument 2, counter 3) after `1 2 2`. Answering A 2 gives status 4: the console starts the sync
save, which commits the trade lock (600) before the commit exchange. A console answered so
republished `0 2 3`, announced its commit clone 5.0 s later and went silent on it; the exchange never
completed, so the lock stayed set and the link menu refused the next trade (`0x976634`). The right
answer, type 4 `1 0 0 3 0 0 step T+1`,
takes that record to state 0 under `0x11ba20`; A 1 with state 0 is status 2 (`0xf4e9f0[0]`), back to
the selection. A withdrawn selection `2 1 4` under A 0 takes `0 0 0 4 0 0 step T+1`.
`bin/lgpe_host.py` answers so and agrees the next vote in one publish;
`tests/test_lgpe_host_withdraw.py` runs both through the game's code.

A trade between two retail consoles carries no clone data on clone types 4 and 1 in either
direction; a host publishing none there leaves a joining console short of the gate `0x11b080`, on
its search screen.

### The commit and the trade lock

The trade lock is a u32 countdown in seconds in the save's MyStatus block. A trade's save sets it to
600 and commits that before the commit exchange; the exchange completing commits it back to 0.

The MyStatus block object is `[[[0x15fad08]]+0x98]+0x58` -> `+0x78`, data `obj+0x58`, 0x168 bytes
(`0x1c9ff0`, `0x1ca000`, slots 5 and 6 of vtable `0x153e0b0`), the kind 1 body. The counter is
`obj+0xe8`, MyStatus `+0x90` (setter `0x1c9d40`, getter `0x1c9d50`). In `savedata.bin` the block is
`0x1000..0x1168` (trainer name at `0x1038`) and the counter `0x1090`: a save kept after an
interrupted trade holds `58 02 00 00` there and no other change in the block. Every captured kind 1
carries 0 at `+0x90`.

The setter's callers: the sync save with 600 (`0x837f90`, `0x837fb0`), the received Pokemon's
application with 0 (`0x838bec`, `0x838c0c`), the countdown (`0x1ca54c`, `0x1ca56c`); loading the save
writes the block. The link menu's check `0x9765f4` switches on the link mode: mode 1 (trade) reads
the counter (`0x976634`) and, non-zero, returns -1 with refusal `0x0248810f825b1fee` (`0x97663c`);
zero goes on to a count check (message `0x0248800f825b1e3b`). Mode 3 refuses when
`[x22+0x62] <= 1` (message `0x02487f0f825b1c88`).

The lock counts down with the play time. `0x1ca450(playtime, seconds)` returns at once when
`seconds > 1` (`0x1ca46c`) or `playtime+0x100` is clear (`0x1ca474`); otherwise it subtracts
`seconds` from the counter, floored at 0 (`0x1ca500`), and adds them to the play time (`+0x54` hours
u16, `+0x56` minutes, `+0x57` seconds, capped at 999:59:59, `0x1ca5a0`). `0x1ca7e0` writes
`playtime+0x100` as `nn::oe::GetCurrentFocusState() != 3` (Background). Its caller `0x1462a0` runs
every 20th call (counter `+0x70`) while its enable byte `+0x54` is set and no save thread exists
(`0x1ce8f0`): it converts `GetSystemTick` minus a base tick (`+0x68`) to whole seconds and passes
the increase over the seconds already counted (`+0x60`) to `0x1ca450` (`0x146314..0x14637c`); the
base moves only when the tick goes backwards (`0x146384..0x1463c0`). A jump of two or more seconds
is dropped, so the clock gains at most one second per gated call. A lock of 600 lasts ten minutes
of counted play time: in focus states 1 and 2, never in the background or while the game is closed
(base re-read at start, `0x14628c`).

`0x13c944` is in `0x13c850` (which also runs `0x145560`, `0x13f0d0`, `0x142cd0`, `0x1427a0`), reached
only from `0x13c5a0`, slot `+0x40` of a 0x210-byte job (vtable `0x15379d8`, built by `0x13c440` from
`0x13bfa0` in the setup `0x13b650`, stored at `G+0x50`, done byte `+0x204`). The executor `0x231a0`,
from the worker loop `0x20f30`, runs it while `+0x204` is clear (`0x23264..0x23288`). `0x13bfa0`
chains the job into a dependency graph with `0x1ca00` (`0x13c02c..0x13c120`); what submits the graph
each frame, and so how often the play-time tick runs, is unknown. The frame period table `0xf7eeb8`
holds 16666667 to 83333334 ns in five steps, indexed by `0x39600`; the frame loop starts at
33333334 ns (`0x38ba0..0x38bb8`, vtable `0x1529968`) and presents every
`clamp(period / 16666666, 1, 5)` vsyncs (`0x29e80..0x29eb4`).

`0x347190` builds one of three save sequences: 0 "normal save" (`0x3474d0`), 1 "sync save"
(`0x347670` -> `0x347ae0`, 0xc8 bytes), 2 "fatal error" (`0x347810`). A trade uses the sync save. Its
init `0x837c70` creates the commit channel object (`0x4d9030`) at `seq+0xb8`, sets the counter to 600
(`0x837f88`), and starts `SaveThread` (`0x1cdc80`), which serializes on the calling thread and
commits once written (`0x1cedd4..0x1cede0`, `nn::fs::CommitSaveData`). Its update `0x838070` runs on
`seq+0xa8` through jump table `0xf867c4`:

| state | address | what it does |
|---|---|---|
| 0 | `0x8380ac` | a recorded network error (`0x4d8a70`) writes result 2 and leaves; otherwise waits for `SaveThread` (`0x1cdf40`), stores at `seq+0xc0` whether this station sends the 2 (`0x838660`), applies the received Pokemon and zeroes the counter in memory (`0x838800`), sets `netmgr+0x121` (`0x4d8b10`), starts `FirstSaveThread` (`0x1ce050`) |
| 1 | `0x8380d8` | waits for `FirstSaveThread` to write (`0x1ce310`), then draws a delay of `2000 + r % 6000` ms from an MT19937-64 seeded with `GetSystemTick` |
| 2 | `0x838234` | after the delay, registers the commit channel (`0x8382a8`) |
| 3 | `0x8382b4` | votes 1 on the commit clone once (`0x4d9690`: `chan+0x64 = 1`, `0x11bc00`), then waits for the channel's gate (`0x4d94d0`) and the clone idle with `[chan+0x74]` 1 |
| 4 | `0x8382ec` | sends a kind 3 carrying 1 |
| 5 | `0x838310` | takes the other station's kind 3 (skipping its loopback); a body other than 1 is the error path (`0x83836c`); if `seq+0xc0` is set, sends a kind 3 carrying 2 (a failed send stays in 5 with the peer's 1 consumed) |
| 6 | `0x83839c` | takes a kind 3 from any station: a 2 clears `netmgr+0x121` (`0x4d8b20`) and signals the commit (`0x1ce3f0`); any other body is ignored |
| 7 | `0x8383e8` | waits for `FirstSaveThread` to commit (`0x1ce410`), result 0 |

`FirstSaveThread` serializes as it starts (`0x1ce154`), after the counter was zeroed, signals
`mgr+0x78` once written, waits on `mgr+0x84`, and commits only if the abort byte `mgr+0x100090` is
clear (`0x1cedf4..0x1cee18`). The error paths (`0x8383b0` for states 2, 3, 5, 6; `0x838520` for a
wrong body; `0x8380c8` for state 0) write result 2 into the parent (`[x0+0x88]+4`); the first two
call `0x1ce520`, which sets the abort byte and waits for the thread to end. Every path ends with
`0x838540(seq, 0)`. The second save is dropped and the save on disk keeps 600.

The dispatcher's state 3 (`0x886684`) reads that result: 2 calls `0x345b10` (`0x886690`) and returns
without advancing. `0x345b10` pushes a fatal-error wrapper (vtable `0x154f1f8`, 0xa8 bytes, `+0x88 =
0`) on the root process stack (`0x13a6b0`); its `0x346140` builds a save process of type
`[proc+0x88] != 0 ? 3 : 2` (`0x3461b8..0x3461d0`), both the fatal error sequence, whose init
`0x836320` shows message `0x191615296121e064` for 2 and `0x977c18bf4135ff42` for 3 (`0x8365f0`,
through `0x7ed60`) and whose update (`0x836780`) is a bare `ret`. An aborted commit ends on that
screen, no later save follows, and the save holds 600 at the next boot.

Both ids are labels of `common/message_error.dat` (string at `0xf22dfc`), FNV-1a-64 with basis
`0xcbf29ce484222645`, the same in all ten languages of update v131072:

| id | label | English | French |
|---|---|---|---|
| `0x191615296121e064` | `error_fatal_save` | An error occurred. You couldn't trade Pokémon. Press the HOME Button to end the game. | Une erreur s'est produite. L'échange de Pokémon n'a pas pu être effectué. Veuillez appuyer sur le bouton HOME et fermer le jeu. |
| `0x977c18bf4135ff42` | `erro_fatal_storage` (sic) | Save data in the Nintendo Switch couldn't be recognized. Please turn off the system, and then try again. | L'identification des données de sauvegarde de la console Nintendo Switch a échoué. Veuillez éteindre votre console, la rallumer, puis réessayer. |

The game has one process stack, rooted at `[G+0x68]` (`G = [0x160d310]`). The runner `0x13a780`
updates only the top `[root+0x78]` through `0x13a160`: 3 runs the new top in the same frame, 1 pops
it or swaps in the pending `[root+0x80]`. The wrapper never returns 1 (`0x346140` hands the fatal
process to the manager `[G+0x60]` through `0x39c20`), so the dispatcher beneath it is never updated
again.

The link menu's refusal ids `0x02487f0f825b1c88`, `0x0248800f825b1e3b`, `0x0248810f825b1fee` differ
pairwise by the FNV prime `0x100000001b3`: FNV-1a-64 hashes of three strings differing only in the
last byte (times the prime's inverse modulo 2^64 they end `dd58`, `dd59`, `dd5a`). The strings are
unknown; the text is in the romfs message archives.

While `netmgr+0x121` is set, `0x4d8750` records every network error at severity 4
(`0x4d8760..0x4d877c`), which states 2, 3, 5 and 6 test for (`0x4d8a80`). A recorded error is
replaced only by a higher severity (`0x4d879c`), so an error above 4 recorded before `+0x121` was set
fails the test. `+0x121` is set at the end of state 0 (`0x4d8b10` at `0x8384f8`) and cleared by state
6 on a received 2 (`0x4d8b20` at `0x838494`). No state has a timeout: a quiet peer leaves the
sequence waiting until the link fails.

The recorders: `0x345790` (code 0xe), `0x3457d0` (0x11), `0x345810` (0xf), `0x345860`, `0x3458a0`,
`0x345900` (an `nn::err::ErrorCode`), `0x345940` (the serial-code client), `0x3459f0`, `0x345a50`,
`0x345aa0`. The listener at `mgr+0x60` (vtable `0x154f068`) routes `0x344c30`, `0x344c60`,
`0x344c70`, `0x344c80` to `0x345790`, `0x344c40` to `0x345900`, `0x344c50` to `0x345860`, `0x344c90`
to `0x3457d0`. The trade session object (vtable `0x154f608`) forwards slot 9 (`0x349650`, code 0xe),
slot 10 (`0x3497d0`) and slots 11 to 14 (`0x349880`, `0x3498e0`, `0x349940`, `0x3499a0`; 14 is code
0x11) to it through `0x3496b0`.

The link state machine `0x4d9b70` (from `0x349520`) enters state 6 when its state is 5 or less, no
operation is pending (`[x19+0x20]` null) and the pump `0x1175d0` returns 0 (`0x4d9b98..0x4d9bc8`);
state 6 (`0x4d9fb0`) calls slot 9. The pump returns 0 when `[x19+0x80]` is null, the transport's
`+0x48` is not 5 (`0x11c560`), or the session's u16 `+0x1e6` is 1 or less (`0x1176b0..0x1176bc`).
Only `0x59eab0` writes `+0x1e6`: the sum over the stations in `s+0x178` of byte `+0x415` of each
state-3 station record (`0x5b5900`, `0x5a9cd0`), filled from connection-response wire byte `0x35`
(`0x5b962c..0x5b9658`). A retail Let's Go sends 1 there, so the value is the station count. The
recount runs only when `[s+0xd8]` is outside 2 to 6, `[s+0xd4]` is 2 or 4 and `0x52abf0(s+0x38)` is
false (`0x59eacc..0x59eaf8`).

The link machine calls the trade session object (vtable `0x154f618`) at six offsets, each from
`[x19+0x10]`:

| offset | function | call | when |
|---|---|---|---|
| `+0x30` | `0x3495e0` | `0x4da584` in `0x4da4b0` (from `0x4d9cf0`) | state 4 to 5 (`0x4d9cf4`) |
| `+0x38` | `0x349600` | `0x4d9f2c` | matching succeeded, before `0x116890` |
| `+0x40` | `0x349620` | in `0x4da5e0` (from `0x4d9e24`) | state 9 to 10 (`0x4d9e28`) |
| `+0x48`, slot 9 | `0x349650` | `0x4da084` in `0x4d9fb0` (from `0x4d9bc8`); `0x4da0e0` (from `0x4d9ee0`) | a pump failure; a failed match with `[job+0x300]` clear (`0x4d9e30`) and a zero result or bits 10 to 12 not 1 or 2 (`0x4da114..0x4da128`) |
| `+0x50`, slot 10 | `0x3497d0` | `0x4da38c` in `0x4da0e0`, from `0x4da294`, two out-arguments | a failed match with `[job+0x300]` clear and bits 10 to 12 of the result 1 or 2 |
| `+0x70`, slot 14 | `0x3499a0` | `0x4d9efc` | a failed match with `[job+0x300]` set |

Both failed-match paths then set state 6 (`0x4d9ee4`, `0x4d9f14`). For result `0xa46e` (module 110,
NIFM, description 82), slot 10's out1 is the u32 at `+0x40` of the object in global `0x163ce00`
(`0x4da2a4..0x4da2c4`; slot 9 instead when the global is null, `0x4da3bc`), written by
`LoginJob::Logout` (`0x5de3ac..0x5de42c`) from the transport's virtual `+0xb0`. Any other result
becomes an `nn::err::ErrorCode` in out2 through `0x5298a0` (for `0xe437` a stored code from
`0x1601e38`, else N / 10000 and N % 10000 of `0x529940(result)`). Slot 10 records a non-zero out1
through `0x345860`, else the ErrorCode through `0x345900`; the manager repeats the test at
`0x3443f4..0x34443c`. Slots 11 to 13 have no caller found.

`0x838660` decides who sends the 2. With S = {144, 145, 146, 150, 151} (`species - 0x90` in mask
`0xc7`) and M = {808, 809}: a station offering from S or M and receiving from neither sends it; the
reverse does not; otherwise the station for which `0x4d9720` is true (`[mgr+0x128c] != 0`) does. So
a station giving Articuno, Zapdos, Moltres, Mewtwo, Mew, Meltan or Melmetal for an ordinary Pokemon
sends the 2 in either role.

The parent block (`[parent+0x88]`, "The trade dispatcher" below) holds the own offered Pokemon's box
index at `+8` and the arriving Pokemon at `+0x10`. State 0 calls `0x838660` while the box slot still
holds the own Pokemon (`0x1c0d30`: the object at `box + 0x3f800 + idx*8`, 0x3e9 none, box
`[[[[0x15fad08]]+0x98]+0x58]+0xb0`), then `0x838800` writes a copy of `[block+0x10]` over that slot
(`0x838afc bl 0x1c0f30`) and applies the trade's side effects:

- Pokedex registration by `0x1cfe80` (`0x83897c`, again once evolved at `0x838ab0`) on
  `[[[[0x15fad08]]+0x98]+0x58]+0x88`; `0x1cff60` skips eggs and species 0 or above 809, else sets
  per-species bits at `obj+0xdc` indexed by `species - 1`. The form is zeroed when
  `0x1760a0(species, form)` is true.
- Trade evolution, `0x728250(pkm, partner, &species, &index)`: `0x723220` keeps the species for an
  egg, or for any species but 64 (Kadabra) when the held item passes the manager's vfunc `+0x28`;
  otherwise the first evolution entry `0x723340` accepts: method 5 always, 6 when the held item
  equals the parameter, 7 for Shelmet (616) with Karrablast (588). The arriving copy is passed as
  both Pokemon (`0x838a44..0x838a4c`), so method 7 never matches. `0x7282c0` applies it: species
  through `0x7283c0`, form plus one for method `0x22`, held item cleared for methods 6, 19, 20 (mask
  `0x180040`).
- Game record 477 when `0x115860` is true, else 476 (`0x1ca840(id, 1)`, `0x838828..0x838840`): the
  u32 at `obj+0x54+4*id` on `[[[[0x15fad08]]+0x98]+0x58]+0xc8`, capped by `0xf48368[0xf4b760[id]]`;
  nothing is written while `obj+0x10f8` is set (`0x1ca8f8`) or for an id above 999. `0x115860`
  returns the byte `0x1614076`, set by `0x1157f0` from `InternetConnectThread` (`0xb2ea98`) and
  cleared by `0x115830` from its exit and both `InternetDisconnectThread` bodies (`0xb2ebf8`,
  `0xb2f178`): 476 counts local trades, 477 trades made while the internet connection is up.

`mgr+0x128c` is whether the local station was the session host at session start, written only by
`0x116890` (`0x59e920(session) & 1` at `0x116a48`) on the link machine's step from state 2 to 4
(`0x4d9f54`), after matching; a Pia host migration does not re-run it. `0x59e920` returns 1 when
`[s+0xe0]` (local station, set on create `0x59f864` and join) equals `[s+0xe8]` (session host,
`0x59f920` on join) and the station `[s + 0x148 + 8*[s+0x142]]` answers true to its vfunc `+0xe0`.
`mgr+0x1288` also comes from `[s+0xe0]` (`0x116a3c`).

For a peer:

- A 2 in the confirmation sub-state gives status 4, which starts the sync save and commits 600: an
  authority that publishes A 2 owes the whole commit exchange.
- A peer's first kind 3 carrying anything but 1 aborts with the lock set.
- A kind 3 sent before the receiver's state 2 registered the commit channel is dropped; the state 3
  vote holds each station's kind 3 until both have registered.
- State 1's delay moves a console's kind 3 by up to six seconds (commit clone announced 5.0 s and
  9.0 s after the host's A 2).
- Any network error recorded between the end of state 0 and the 2 aborts the commit: the save keeps
  600 and the console ends on the fatal error screen.

### The trade dispatcher

`0x886530` runs the link from the menu to its exit, switching on `[obj+0x68]` through the table
`0xf87bc4`:

| state | entry | what it does |
|---|---|---|
| 0 | `0x886578` | setup |
| 1 | `0x88669c` | waits for its child; a recorded network error (`0x345af0`) goes to 8; mode `+0x8c` 1 or 2 creates the `0x347e10` object (`0x886f04`) and the battle scene (`0x886f18`), then 6; mode 3 waits for `0x344510`'s party-offer object to report ready (`0x886f30`: the channel's and clone set's readiness, `0x4d94d0 & 0x11b4d0`) |
| 2 | `0x8866f4` | copies box slot `[obj+0xf8]` to `obj+0x148` as the outgoing Pokemon; a network error goes to 8; `[obj+0x100]` 5, the trade UI's proceed, starts the sync save, any other value goes to 8 |
| 3 | `0x886670` | waits for its child (a weak reference at `[obj+0x90]`, destroyed before the fatal wrapper is pushed); result 2 calls `0x345b10`, the fatal error, and stays; otherwise destroys the party-offer object (`0x886c70`), puts `[obj+0xf0]` at `obj+0x150`, starts the trade demo (`0x875f40`), state 4 |
| 4 | `0x886930` | releases `[obj+0x150]`, state 5 |
| 5 | `0x886950` | waits for its child; writes `[obj+0x158]` into box slot `[obj+0xf8]` (`0x1c0f30`), starts a normal save, state 7 |
| 6 | `0x886ee8` | state 8 |
| 7 | `0x886908` | waits for its child; result 1 goes to 8, any other to 1 |
| 8 | `0x8869cc` | destroys the party-offer object (`0x8869f0`) and the `mgr+0x70` object (`0x3447a0`) and leaves |

A save starts through `0x887340`, which builds a save process (`0x346670`, 0x128 bytes); the
dispatcher stores `&obj+0x178` into it at `+0x90` (`0x8868dc`, `0x886e48`). Its first update
`0x8345d0` maps the save type through `0xef9a80 = {1, 0, 2, 2}` to the sequence kind of `0x347190`
and hands the pointer on (`0x834688`) as `[parent+0x88]`:

```
obj+0x178  +0x00  save type: 0 sync save, 1 normal save, 2 or 3 fatal error
obj+0x17c  +0x04  result, written by the sequence: 0 done, 2 aborted, 1 the link ends
obj+0x180  +0x08  box index of the own offered Pokemon, [obj+0xf8]
obj+0x188  +0x10  the received Pokemon, [obj+0xf0]
```

State 2 fills it for the sync save (`0x88685c..0x88689c`); state 5 sets the type to 1
(`0x886e00..0x886e04`). The normal save's update `0x8374b0` runs `SaveThread` (`0x8377bc`), waits
3000 ms (`0x8377ec`), then, if the trade session object is in state 8 (`0x349090`), creates the
party-offer object (`0x8375a4`, retried each frame) and writes result 0 (`0x8375b8`); in any other
state it writes 0 alone. Result 1 comes only from `0x837860`, gated on `[x20+0x258]` and a queue at
`[x20+0x250]` (`0x83776c..0x8377a0`). After a trade the dispatcher returns from state 7 to state 1
(`0x88691c..0x88692c`) with a new party-offer object on a new channel, so one seat carries one trade
after another.

### The battle scene's channel

The senders in `0x9dce94..0x9dede8`, the only non-zero tags, keep their state in a global block at
`0x1640eb0` whose first word is their channel (`0x9dce10..0x9dce1c`: `ldr x0,[0x1640eb0]; b
0x4d9450`). `0x9dce50` sends four bytes from block `+0x78f0` (a u16 station byte, a u16 0x6e) under
tag 1 to 0xff; `0x9dd3ec` packs a Pokemon (`0x721ef0`) into `+0x348` and `0x9dd3fc..0x9dd40c` send it
under tag 3. Per-station records are 0x1788 bytes (`0x9dcee8`).

The registration (`0x9d2d90`) sits in the battle process's stepped setup `0x9d2c30` (jump table
`0xf92c1c`; the process references `Pop_BGM_battle_to_field`, `vs_wild` and `btl_sky.gfbmdl`),
reached from the dispatcher's state 1 only in modes 1 and 2 (`0x886f18` -> `0x95c470` -> `0x95c5c0`
-> `0x28cd10` -> `0x28e630` -> `0x9cbba0`). In mode 3 the battle channel never registers. Step 0
creates the channel (`0x9dc5c0`) and stores it at `0x1640eb0` (`0x9dc6f4`) only when the link session
object `[[[0x15faec8]]+0x50]` is in state 8 (`0x9dc61c..0x9dc634`); `0x9dce10` registers nothing
while `0x1640eb0` is null, and readiness `0x9dce30` returns 1 with no channel, so a wild battle
registers none. The teardown (`0x9d3df0` -> `0x9dcce0`) clears the pointer.

### What a hosted trade puts in the save

The offered box structure lands in the save as sent, unchecked. A record carrying these values
reads back unchanged on a Let's Go Pikachu's summary screen: species 132, experience 1,000,000 (level
100), ability 150 in the hidden slot, a PID with shiny xor 0 against TID 41234 and SID 12345 (shown
as 083154, `(sid << 16 | tid) % 1000000`), nature 10, genderless, 31 in every IV, 200 in every AV (HP
437 at level 100, the game's maximum), one move, met level 30, met location 4 (Route 2), language 2,
OT `POKELDN`. Offsets are PKHeX's PB7 map.

### A joiner leaving

A console backing out with Retour publishes state 4 on the offered clone, argument 0 under a fresh
counter, then argument 3. The host answers each 30 ms later with zeros in the first three words, the
trailing word plus one, and the argument as the type 4 copy's first word. The console then releases
its clones with a 0x83 on clone type 4, station 0xFD (clone 0 on clone type 3), repeated (about
every 100 ms, measured) until a 0x84 answers; the host releases its own (0x83 on clone type 2 under
its station, and on clone type 4). After the last release (2.45 s measured, a delay no answer moved)
the console sends a mesh leave request
on the mesh protocol's reliable port, under the 24-byte reliable header:

```
04 01        leave request, station index
```

It is owed the reliable acknowledgement on that port and a two-byte leave response on the
unreliable port, `08` and the mesh host's index (`08 00`). The leaver's handler `0x591bf4` takes the
response only when its byte [1] is the index of the station the host getter `0x58e5d0` (`ldrb
[x0,#0xa3]`) names, then clears the leave job's flag `+0x78`. The job (`LeaveMeshJob`, constructor
`0x589470`) arms a 5000 ms deadline when it sends the request (`0x5895bc`); `WaitLeaveResponse`
(`0x5896c0`) waits for the flag or the deadline, retransmitting the request (every 40 ms, measured),
then disconnects its stations and leaves the network. A response naming the leaver (`08 01`) is
dropped: the console then deauthenticates 5.00 s after its leave request (six runs, two consoles,
4.98 to 5.01 s, the host's disconnection request answered in each); answered `08 00` twice, it
sent its own disconnection request 0.04 s after the leave request and deauthenticated about 0.06 s
after it. After a Retour the host sends a one-byte station
disconnection request, type 3; the console answers type 4 within 50 ms.

A console host answers a joiner's leave request with `08 00` twice, then repeats a Local Protocol
start host migration (type 0x13, every 0.3 s, measured). A joiner's disconnection request sent as
the leave response arrives returns the host's player to the menu ("l'autre joueur a choisi
d'annuler l'échange"); a joiner that waits leaves the host repeating 0x13 (five seconds, measured).
`bin/lgpe_join.py --leave-after SECONDS` runs the exit (`pokeldn.lgpe.leave`).

### A host leaving

A console host whose player backs out publishes state 4, argument 3, releases its clones (0x83,
answered by 0x84), and 2.49 s after the last release sends a mesh migration start on the reliable
port, `44 00 01` (host index, next host's index). Its wait (`0x58aeb0`) keeps a flag per connected
station at `job+0x6e+index` and ends when every flag is clear or 5000 ms (`0x58a8f0`) have passed; a
migration response `48 <index>` clears that station's flag (handler `0x591e98` -> `0x58b010`), and
so does the station leaving. Unanswered, the console retransmits the start every 45 ms for 5.0 s.

It then broadcasts an update session carrying host migration state 1 with its node list unchanged,
and repeats a Local Protocol start host migration (type 0x13) every 301 ms (`0x5d40ac`) until no
station but itself is connected to the LDN network (`0x5cc2d0` counts them) or 10000 ms have passed
(`0x5d4050`), then destroys the network: eight LDN disconnect frames, reason 3, broadcast over
200 ms. A joiner that answers neither holds the console host 15.0 s after the migration start (two
retail runs). An emulated host answered with the ack and `48 01` sent its update session and the
first 0x13 34 ms later; a retail host answered the same way sent its first 0x13 0.06 s after the
migration start. `bin/lgpe_join.py` sends both answers and leaves the network on the first
0x13 (`pokeldn.lgpe.leave.host_departure`).

### What a host does with a joiner that holds no clone data

A console host given a 0x3C-byte connection response (no network id, no player) answers a clone
announcement and announces its own, never sends the clone's data (no 0xb1), and leaves the clone
session (0x32) a few seconds after the mesh join. A joiner that sent a full response gets the clone's
data after its participate (1.1 s measured).

### Past the gate

A host goes from state 4 to the settled state 8 once the gate passes (66 ms and seven refusals in
one measured session): state 6 sends the first message (0x168 bytes from `obj+0x450`), and state 7
counts its own loopback and the joiner's into `obj+0x470`, leaving for 8 at exactly two (`b.ne`) and
receiving no more. The host's screen then reads that a player has been found. Headers of the first
messages:

    01000000 68010000 01000000 00ff0000    kind 1, 0x168 bytes, step 1
    02000000 e8000000 02000000 00ff0000    kind 2, 0xe8 bytes, step 2
    02000000 e8000000 03000000 00ff0000    kind 2, 0xe8 bytes, step 3

In a working session the kind 1 messages are acknowledged, clone ids 2 and 3 are announced, and the
kind 2 messages follow (70 ms, 3.2 s and 0.4 s apart in one measured session). State 8 is terminal
for `0x349200`: while the mode word `+0x8C` stays 0, clone ids 2 and 3 are never announced.

### The state machine above the gate

State 3 of `0x349200` allocates the session sub-object at `+0xB8`, calls `0x11aec0` through the thunk
`0x11b4c0` (object `[x0+0x20]`, clone id `[x0+0x18]`), and sets state 4 unconditionally; state 4
calls the gate through `0x11b4d0` and advances on true. States 3 and 4 read nothing from the network.
Three setters over the same guard sit in consecutive vtable slots, reached only through the vtable:
`0x154f648` -> `0x3495e0` (state 3, from any state but 9, 10, 11), `0x154f650` -> `0x349600` (state
2), `0x154f658` -> `0x349620` (state 11, then the abort `0x4d8b00`); `0x349650`, `0x3497d0`,
`0x349880`, `0x3498e0`, `0x349940` follow.

`0x11aec0` registers and announces a station's whole clone set in one frame: the type-1 clone at
`game+0x90` from `game+0x678`, the type-4 clone at `game+0x1258` from `game+0x13f0`, then one per
party member (stride 0x118 from `game+0x218`, source stride 0x260 from `game+0x8d8`). Each goes to
`0x51a550` or `0x51a510`, which enqueue an announcer on the element's list `+0xD8`. The sweeper
`0x51b380` drains it a tick later, the type byte from the table `0xf46acc` (0x81, 0xa1, 0x83, 0xb1)
by the queued object's kind: hence `0x81` on clone type 2, `0xa1` on type 4 and `0xa1` on type 1 in
one frame.

The announcement comes before the gate: a station emitting that triple has passed state 3; one that
never emits it has not reached state 3, and no message aimed at the gate's inputs helps it. A
console host emits the triple from the trade state machine for clone id 1 only; ids 2 and 3 come
from the second publisher (`0x349a90`, below). Joining, it emits no `0x81`, only the take-over
burst. A station runs `0x11aec0` once per clone id, 1 then 2 and 3.

### The second publisher and its mode word

`0x11aec0` has two callers. The trade state machine calls it once, in state 3, for clone id 1. Ids 2
and 3 come about 3.2 s later from another per-frame dispatcher: `0x13a780` -> `0x13a160` ->
`0x886530` -> `0x344510` -> `0x349bf0` -> `0x349a90`, one game object per party Pokemon, 0x1680
apart, while the state word stays 8.

`0x886530` runs every frame from the overworld on and branches on the mode word `+0x8C`
(`0x886ed0..0x886ee8`): 1 or 2 the battle scene (`0x886ef8`), 3 the publish arm (`0x886f24`),
anything else parks at 8. `0x344510` is a one-shot: it returns early when `[x19+0x68]` is non-null,
else allocates 0x278 bytes and calls `0x349bf0`.

Setters `0x7c4530` (mode 1), `0x7c4580` (mode 2) and `0x7c45d0` (mode 3; the last two then call
`0x147c90` with 0) write the word through `[singleton+0x288]`; the class vtable `0x15afa68` (slot 9
= `0x886530`) is filled by relocations around `0xe13388`. Traced from the overworld to a settled
trade, the three setters and `0x5a733c` never fire while the mode word moves from 0 to 3. No class
method stores to `+0x8C`, and none of the sixteen constant stores to `+0x8C` in `.text` writes 3: the
writer is unknown.

### The sequence a take-over has to carry

A station announcing a clone allocates a sequence and stamps it on its announcement. `0x520c30`, the
request side, returns early when the clone's `+0x38` is zero, `+0x110` is set, or `+0xB0` and `+0xB8`
are both non-null; otherwise it allocates the sequence into `+0x10C` and enqueues the announcer.
`0x520ce0`, the completion, unqueues the announcer and writes 1 to `+0x110` only when `+0xB0` and
`+0xB8` are non-null and `+0x10C` equals the value given. `+0x110` is the gate's per-station term:
the entries at `+0x250` are the party clones, `station[i]` = `partyClone[i]+0x38`.

A joiner's take-over (`0x91` on the clone's types) echoes the clock of the peer's announcement; its
announcement of its own copy carries its own clock:

    host   0xa1 clone type 4   00000cfe 01 2808ab      the sequence it allocated
    host   0xa1 clone type 1   00000cfe 01 2808ab
    joiner 0x91 clone type 4   00000cfe               echoed
    joiner 0x91 clone type 2   00000cfe               echoed
    joiner 0xa1 clone type 4   00000d21 01 2808ab      its own clock, the host's content
    joiner 0xa1 clone type 1   00000d21 01 2808ab

`+0xB0` and `+0xB8` are the list links (`sub+0x08`, `sub+0x10`) of the announcer embedded at
`clone+0xA8` (`0x51e790` links, `0x51e810` unlinks); null means it is not in the announce list. In a
working session both clones arrive linked and nothing is allocated; a party clone arriving unlinked
allocates, and the completion that follows is refused. An inbound `0x82` also makes `0x520c30`
allocate, so answering each re-announcement with a burst carrying `0x82` mints a sequence per burst,
about thirty a second.

Each clone carries one announcement clock: the announcer stamps its mesh clock on the `0xa1`, the
peer's acknowledgement and next `0xa1` for that clone carry the same number, and `+0x10C` holds it.
A record matches when it carries the clock of the other station's latest `0xa1` for the clone.
`0x520d30` handles a `0x91` on clone type 2 (the negative acknowledgement) and `0x520ce0` the
`0xa2`, under the same preconditions; both unlink the announcer, and only the `0xa2` writes 1 to
`+0x110`. A matching `0x91` cancels the announcement, a matching `0xa2` completes it; an `0xa2`
built from the joiner's own clock misses.

The sequence is per party clone and re-allocated (at `0x520cb8`), stepping 0x34 to 0x38 per
allocation. With a take-over carrying the joiner's own clock, a host allocated `0x1114b` for both
party clones; clone 0's completion carried `0x1114b` and set `+0x110`, clone 1's carried `0x111b0`
and was refused: the gate `0x11b080` stays false and the state word never leaves 4. Answering only
the peer's first clone type 2 publish and acknowledging the rest returns it to re-announcing under a
fresh sequence each time.

### The take-over exchange a joiner runs once per clone

A take-over is an ownership transfer: `0x520d30` cancels the peer's announcement and the joiner
announces the clone under its own clock. The reference exchange for the two party clones, host's
announcement at zero:

```
+0 ms   host    0x81 clone 2, 0x81 clone 3, dest 0x0003
        host    0xa1 x2 per clone                        clock 0x197e, the host's
+5 ms   joiner  0x82, 0x91 x2, 0x82, 0x91 x2, 0x84 x2    echoing 0x197e
+75 ms  joiner  0x81 clone 2, 0xa1 x2                    clock 0x19c1, the joiner's own
        joiner  0x81 clone 3, 0xa1 x2                    clock 0x19c1
+102 ms host    0xa2 per clone                           clock 0x19c1, the joiner's
        host    0xa1 per clone                           clock 0x19e2, the host's own
+141 ms joiner  0xa2 per clone                           clock 0x19e2, the host's
```

The joiner takes each clone over once, at the first announcement of a clone it does not own. Every
later re-announcement gets one `0xa2` carrying that announcement's clock, on clone type 2 under the
joiner's station, payload `<clock> 00 00 00 02`. A second take-over cancels an announcement that was
never meant to change hands, and the peer re-announces without limit.

The `0xa2` drives completion. A station's own announcer completes off the loopback of its own `0xa2`
within about 6 ms, so the first party clone always completes; the second needs the joiner's. The
working joiner's burst carries no acknowledgement: the peer's `0xa2` pair arrives at +37 ms and the
joiner's single `0xa2` goes at +72 ms, as a reply. A peer that never re-announces never unlinks
(the per-tick builder's unlink, about 30 ms after linking) and allocates no sequences.

### What the announce's destination field decides

The command header `0x51f820` lays out `+0x10` as a station bitmap. An 0x81 announcing a clone for
the first time carries the whole mesh (0x0003); the two 0xa1s behind it on clone types 4 and 1, and
the announce repeated 35 ms later, carry the peer alone (0x0001). Given the mesh bitmap a peer
answers with two 0xa2s, on clone type 4 and on clone type 2 under its own station; given the peer
bitmap it answers neither and keeps sending 0xa1 on clone type 1, and the gate `0x11b080` never sees
the acknowledged set fill.

The retransmit count of `0xa1` on clone type 1 tells a working session from a stalled one: nine per
station when working, one every 0.12 s without end from a peer taken over at every
re-announcement, its game silent.

Every clone message is built through `0x51e3d0`, the protocol object's ninth vtable slot (the fourth
returns 0x73). Literal types at their call sites: 0xa2 on clone type 2 `0x51cbb8`, 0x81 `0x51e92c`,
0xa2 on clone type 3 `0x51cdd4`, 0xc1 `0x51c9e4`, 0x82 `0x51c60c` and `0x51cd5c`, 0xe3 `0x51ad2c`,
0xf3 `0x51ef18`. The game holds three clone objects over one element, type 1 at `game+0x90` and
`game+0x1710`, type 4 at `game+0x1258`; a message's clone type does not map one to one onto them.

| address | role |
|---|---|
| `0x51ab20` | CloneProtocol::vfunc9, the per-element receive |
| `0x51c100` | receive dispatch: table `0xf7673c` on (type - 0x11) splits clock from command messages, `0xf76800` on (type - 0x84) reaches the command path |
| `0xf769c4`, `0xf769e4` | structure by high nibble; clone type |
| `0x51b010` | reply state machine, table `0xf76674` on (type - 0x21) |
| `0x51b1d0` | clock-driven retransmit scheduler |
| `0x51f9b0`, `0x51fab0`, `0x51fbd0`, `0x51f820`, `0x51f4c0` | serializers: clock request, clock reply, participate, command header, ClockAndCount |
| `0x51c1e0` | drops a message whose count at [0xC] does not exceed the sender's last |

Element offsets: +0x34 station, +0x40 state, +0x50 clock, +0x7a0 send time, +0x32c result.

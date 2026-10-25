---
title: The Pia layer
parent: The wireless layer
nav_order: 1
---

# The Pia layer

Pia is Nintendo's peer-to-peer session middleware, on UDP port 12345 in every title examined. Every
datagram begins with the magic `32 AB 98 64`. The Pia version decides the header layout:

| | FireRed/LeafGreen (the GBA app) | Brilliant Diamond / Shining Pearl | Sword / Shield |
|---|---|---|---|
| Pia version byte | 15/16 (6.32+) | 9 (5.27-5.45) | 4 |
| header size | 0x1D | 0x20 | 0x20 |
| variable ids | 2 bytes each | 4 bytes each | 1 byte + a halfword |
| GCM tag on the wire | | 8, truncated from 16 | all 16 |
| module | `pokeldn/ldn/pia_connect.py` | `pokeldn/ldn/pia5.py` | `pokeldn/ldn/pia4.py` |

Unless a section names another build, `0x01...` addresses are Shield 1.3.2's decompressed `main`
(as `tools/switch/nso_read.py` lays it out) and `main.bin 0x01...` addresses are BDSP 1.3.0's.

## Packet headers

### Version 9 (Pia 5.27-5.45)

From `nn::pia::common::Packet::Header`:

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F)
    0x05  4  destination variable id, big-endian   (0 = broadcast to the mesh)
    0x09  4  source variable id, big-endian
    0x0d  2  packet id, big-endian
    0x0f  1  footer size
    0x10  8  AES-GCM nonce, a monotonic counter
    0x18  8  AES-GCM tag, truncated from 16
    0x20     ciphertext: the plaintext padded to a multiple of 16

### Version 4

From the deserializer `0x01774730` (more than 0x1f bytes required):

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 4
    0x05  1  connection id
    0x06  2  packet id, big-endian
    0x08  8  AES-GCM nonce, a monotonic counter
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext

Both small fields are per destination station and 0 on a packet to no station in particular; a
retail Sword sends 0 in both, which passes every receive path.

- Connection id: the receiver (`0x017bdbd0`) drops an id of 2 or more that differs from the one it
  holds; 0 and 1 pass.
- Packet id: the receiver (`0x0185dd20`) passes 0 as unsequenced and drops a non-zero id not above
  the last one from that station.

Below the header, version 4 shares version 9's session key, IV and framing.

### Version 11: what a receiver drops (Scarlet 4.0.0)

`0x6e9744` accepts or drops a whole packet before any protocol reads it. With `st` the station at
the source address, `V` the receiver's variable id, `D` the header destination and `S` the source:

| check | dropped when |
|---|---|
| sender | `st` flagged (`+0x78`) or in state 3 |
| destination | `D >= 2` and `D != V` |
| source id | `S != 0` names no station, when `D == V`, or when `D` is 0 or 1 with a footer |
| packet id, `D == 1` | not newer than the last from `st` on its destination-1 counter (`st+0x60`) |
| packet id, other `D` | not newer than the last from `st` on its other counter (`st+0x48`) |

Packet id 0 always passes and stores nothing; otherwise `(int16)(id - last) >= 1` is required, so a
resend under the same id is dropped. With no station at the source address (a join), no packet id is
checked. A retail sender numbers destination-1 packets from one counter and unicasts from a
per-recipient counter; both skip 0.

## Message framing

A Pia payload carries one or more messages, each opening with a presence byte saying which header
fields follow. An omitted field is inherited from the previous message in the packet (`0x01853050`).
The walk stops at `0xFF` and nothing else: `0x00` is a legal one-byte header inheriting every field.

| header version | title read | reader | next message starts |
|---|---|---|---|
| 4 | Sword | `0x01852da0` | on a multiple of four |
| 9 (5.27-5.45) | Shining Pearl 1.3.0 | `0x159b980` | on a multiple of four |
| 11 (6.16-6.30) | Legends Arceus 1.1.1 | `0x7484cc` | where the payload ends |
| 11 | Scarlet 4.0.0 | `0x6ed2d0` | where the payload ends |
| 16 (6.39-7.2) | Legends Z-A | `0x256e088`; no `0xFF` stop, the packet header states its padding | where the payload ends |

Stations bundle runs of equal-sized messages behind presence 0x00 (Scarlet's zero-filled record
chunks, Shining Pearl's reliable messages, Arceus's second 24-byte record). Never stop a walk at
0x00. `tests/test_pia_bundled.py` pins one packet of each title.

Version 3 (Let's Go 1.0.2) has no presence byte: a fixed 0x16-byte header whose second byte must be
1 (`0x5ae7d0`), the walk stopping at `0xFF`.

Version 4's header is one byte plus five conditional fields:

    bit 0x01  +1  message flags
    bit 0x02  +2  payload size, big-endian
    bit 0x04  +4  protocol id and a 3-byte port
    bit 0x08  +8  destination
    bit 0x10  +8  the sender's station constant id

Presence 0x7F gives 24 bytes (version 9: 16); bits 0x20/0x40 add nothing. The constant id is
`station_protocol.ldn_constant_id` over the sender's MAC, big-endian here and little-endian in the
Local Protocol body.

Version 16 (Z-A) has one byte each for flags, protocol (0x04), port (0x08) and bit 0x10, two for
size; the bit-0x10 byte sits between protocol and port (`0x256df54`). A size of 0x590 or more is
rejected. `pokeldn.ldn.reliable.parse_messages` reads it.

In versions 4 and 9 each message is padded to a multiple of four; the packet tail is `0xFF`.
`pia4.parse_packet()` resolves the inheritance, `pia4.parse_messages()` returns each header as sent.
A walk is correct when consumed bytes plus `0xFF` padding account for the whole plaintext.

### Compression

A payload may be a zlib stream, flagged in the message flags: 0x20 in 5.27-5.45, 0x10 in version 4.
The version-5 reliable header has its own zlib flag, 0x10, which BDSP sets on some game messages
([BDSP's protocol](bdsp_protocol.md)). BDSP switches compression on mid-session. A zlib stream's
first two bytes, as a big-endian halfword, are a multiple of 31.

### The footer

A packet sent to more than one console carries a footer: one big-endian halfword per recipient, the
low half of its variable id, length in header byte 0x0f. The GCM tag does not cover it: the
ciphertext is `data[0x20 : len(data) - footer_size]` (`pia5.ciphertext()`). A footer left in fails
authentication with no other symptom.

## Session keys

| network type | class | derivation |
|---|---|---|
| LDN (local wireless) | `nn::pia::local::LocalProtocol` | AES-128-ECB under the game key, over 16 bytes from an xorshift128 seeded from a session value |
| LAN | `nn::pia::lan::LanProtocol` | first 16 bytes of HMAC-SHA256(game key, a 32-byte parameter whose last byte is incremented) ([LAN mode](#lan-mode)) |
| NEX (internet) | `nn::pia::nex::*` | session key from the matchmaking server |

### The game key

    key = cryptoKeyDataSeed                     the game's own 16-byte constant
    key[1]  = (version >> 8) & 0xFF
    key[3]  = (version >> 4) & 0xFF             version = the local communication version,
    key[7]  = (version >> 1) & 0xFF                       which the advertisement carries
    key[12] = (version >> 0) & 0xFF

`ldn_game_key()` computes it. Sword/Shield's key is a 16-byte ASCII literal used unchanged, with no
seed and no version substitution.

### The LDN session key

For Pia 5.9-5.45:

    rnd = four SEAD draws, seeded with the session parameter from the advertisement (+0x0c),
          packed little-endian into 16 bytes
    session key = AES-128-ECB(game key).encrypt(rnd)

SEAD seeds `s[i] = (prev ^ (prev >> 30)) * 0x6C078965 + i` and runs an xorshift128 with shifts 11, 8
and 19 (`pokeldn/ldn/sead.py`; `pia5.ldn_session_key()`). For Pia 6.16+ the session key is AES of
the SSID under the game key ([The wireless layer](ldn.md#hosting-for-an-emulator)).

### The AES-GCM IV

For Pia 5.27-5.45 and version 4 (`ldn_nonce_crc()`, `gcm_iv()`):

    IV[0..2]  = first three bytes of crc32( network id (little-endian) || source MAC address )
    IV[3]     = source variable id & 0xFF        from the packet header
    IV[4..11] = the packet's 8-byte header nonce

The plaintext's `0xFF` padding is known plaintext that tests a candidate key in one AES block.

## LAN mode

LAN mode carries Pia over UDP on an ordinary IP network: a station finds a session by broadcast,
with no radio and no LDN. `pokeldn/ldn/pia_lan.py` implements Pia 5.45 and earlier; every fact below
was measured against an emulated Shield 1.3.2 (`tests/test_swsh_lan.py` pins them to its bytes).

| port | carries |
|---|---|
| 30000 | browse requests (broadcast) and browse replies (unicast to the requester), not wrapped in Pia |
| 49152-49155 | a station's Pia packets; a console takes the first free one |
| 40000 | broadcast reliable (0x80) messages a station sends to the subnet broadcast |

### Browse request and reply

A browse request is `00`, a u32 size `0x23A`, the 0x23A-byte search criteria and a 0x12A-byte crypto
challenge. A reply is `01`, a u32 size `0x511`, the session info and a 0x3A-byte challenge reply.

| criteria offset | field |
|---|---|
| 0x00 | minimum participants, a (maximum, minimum) pair of u16 |
| 0x04 | maximum participants, the same pair |
| 0x08 | opened only, vacant only |
| 0x0A | result offset, result size (u32 each) |
| 0x12 | game mode (u32) |
| 0x16 | session type (u32) |
| 0x236 | search flags: 0x1 minimum, 0x2 maximum, 0x4 opened, 0x8 vacant, 0x10 game mode, 0x20 session type |

| session info offset | field |
|---|---|
| 0x00 | game mode, network id (u32 each) |
| 0x08 | six u32 attributes |
| 0x20 | participants, minimum, maximum (u16 each) |
| 0x26 | system communication version, application communication version (u8 each; 7 and 7 in Sword) |
| 0x28 | session type (u16) |
| 0x2A | 384 bytes of application data, then its u32 size at 0x1AA |
| 0x1AE | opened |
| 0x1AF | host address: IPv4, 12 zero bytes, u16 port |
| 0x1C1 | host constant id (u64), variable id (u32), service variable id (u32) |
| 0x1D1 | sixteen 50-byte stations: role (1 host, 2 player), name encoding (1 UTF-8), 40-byte name, u64 constant id |
| 0x4F1 | 32-byte session key parameter |

A station's ids come from its address: the constant id is the IPv4 address over the port
(`c0a8011f0000c001` for 192.168.1.31:49153), the service variable id is the address's low half over
the port, and the network id equals the host's service variable id.

### The challenge

    challenge  = version 2, enabled 1, u64 counter, 16-byte challenge key, 16-byte tag,
                 256 random bytes under AES-GCM(AES-ECB(game key, challenge key),
                                                 nonce = receiver's broadcast address || counter)
    reply      = HMAC-SHA256(game key, the 256 bytes)[:16]
                 under AES-GCM(HMAC-SHA256(game key, reply key || request key)[:16], the same nonce)
    key param  = the first answered reply's challenge key || its request's challenge key
    session key = HMAC-SHA256(game key, key param with its last byte plus one)[:16]

The nonce opens with the broadcast address of the receiver's subnet (`local | ~mask`). A host draws a
new 16-byte challenge key for every reply and encrypts the response under it and the challenge key of
the request it answers; the key param, stored in the session info at 0x4F1, keeps the pair of the
first request it answered (Sword 1.3.2 `0x0178b464`). A searching station checks a reply under the
reply's challenge key and the challenge key of its own latest request, never under the key param
(`0x0178ab2c`), and drops a reply that fails. A host answers only a request whose criteria its session
matches (`0x0178e590`): game mode, session type, both participant ranges (a bound of 0xFFFF is
open), opened only and vacant only.

A station picks a session from the replies to its browse (`0x01778c80`): criteria matched, opened,
not a session whose join already failed, the same system and application communication versions,
and room for the joining stations. With none, it creates its own session.

### Host request and the AES-GCM IV

After the browse the joiner sends a host request, protocol 0x44 type 3: `03`, 11 zero bytes, the
u32 network id. The host answers type 4: `04`, 11 zero bytes, the network id, its station location.
The station handshake that follows is the same as over LDN; there is no Local Protocol (0x24). A
retail Sword's host request carries source constant id 0; its constant id is its address over its
station port, and a host's connection request to any other id goes unanswered.

Once in the mesh, a retail Sword sends a session request, type 5: `05`, 11 zero bytes, the network
id. The host answers with the session info in session messages, type 6: `06`, 11 zero bytes, a u32
value shared by the fragments, a u16 sequence id, the fragment index and count (u8 each), a u32
fragment size, then at most 800 bytes of the session info. A Sword left without one goes silent 5 s
later and leaves the mesh.

A station sends a keep-alive, type 7 (`07` and 11 zero bytes), every two seconds, in plaintext
outside a session; the receiver ignores it.

    IV[0..3]  = the sender's IPv4 address
    IV[4]     = the connection id from the packet header
    IV[5..11] = the last seven bytes of the header nonce

## The protocols

From `GetProtocolId` (vfunc4 on every `nn::pia` protocol object):

| id | class | notes |
|---|---|---|
| 0x14 | MeshStationProtocol | the connection handshake; every mesh acknowledgement |
| 0x18 | MeshProtocol | join, update mesh, host migration |
| 0x1c | SyncClockProtocol | |
| 0x24 | LocalProtocol | the update session a host rebroadcasts |
| 0x54 | BandwidthCheckProtocol | |
| 0x58 | RttProtocol | round-trip timing |
| 0x68 | UnreliableProtocol | |
| 0x77 | ClockProtocol | |
| 0x7c | ReliableProtocol | the reliable sliding window |
| 0x80 | BroadcastReliableProtocol | |
| 0x84 | ReliableBroadcastProtocol | a different class from 0x80 |
| 0x94 | SessionProtocol | |
| 0xa4 | MonitoringDataProtocol | |

BDSP registers nine: 0x14 v2, 0x18 v3, 0x1c v0, 0x24 v0, 0x58 v3, 0x68 v1, 0x7c v3, 0x94 v1, 0xa4
v0, which pins its library to Pia 5.31-5.43.

### Joining a mesh

A station joins through the update session (0x24), the connection request (0x14) and the join
request (0x18), in order; each retransmits every 500 ms until acknowledged.

A mesh message is acked on 0x14 with the eight-byte type-5 ack, `05 00 00 00` and the ack id
big-endian; the ack id is the message's last four bytes (`mesh_protocol.ack_for()`). A host acks a
join request before sending the join response; the receiver acks every copy.

### Leaving a session (Pia 6)

`Session::LeaveAsync` runs `LeaveSessionJob`, whose LeaveMesh step starts `LeaveMeshJob` on a
non-host (`LeaveMeshWithHostMigrationJob` on the host). Its SendLeaveRequest step sends the Session
type-3 leave request and waits 500 ms for the host's type-4 response, four sends at most. Any delay
before the first type 3 belongs to the game.

| | Legends Arceus 1.1.1 | GBA app (Pia 6.39) |
|---|---|---|
| `Session::LeaveAsync` | `0x72a6dc` | `0xb1060` |
| SendLeaveRequest | `0x73b898` | `0xcacf4` |

## The Local Protocol (0x24)

The host broadcasts an update session (type 0x11) about every 100 ms until every station acks it:

    local message header  version 1, type 0x11, size 73
    sequence id
    network id            random, not the advertisement's network id
    host variable id      the packet header's source variable id
    host constant id
    allow participating
    node 0..7             address:port and a ranking byte each
    host migration state

The Pia message header is big-endian, these fields little-endian, a local address inside them
big-endian. `pokeldn/ldn/local_protocol.py` parses it and version 4's.

### The ack

The ack (type 0x21) is 20 bytes (`LocalAckMessage::Serialize`, `main.bin 0x016bc0f4`): `1` at 0,
the type at 1, the payload-size halfword at 2, six zero bytes, the sequence id at 0x0C, four zero
bytes. It is framed like the update session: presence `0x7F`, flags `0x11`, protocol 36, port 0,
destination 0. A client broadcasts it; the rebroadcast stopping is the pass signal.

The host attributes an ack by the sender's address and port (`0x016aec94`). The client's variable id
feeds the IV, so it must be stable within a run and non-zero.

## The Mesh Station Protocol (0x14)

Byte 0 is the type: 1 connection request, 2 response, 3 and 4 disconnection request and response, 5
ack, 6 and 7 relay connection request and response (dispatcher: version 4 `0x017c5f50`, BDSP
`0x0154e848`).

### The version-9 connection request

Checked in order:

| offset | field | a failure gives |
|---|---|---|
| | size 15..949 | drop |
| 0x0 | message type, connection result, platform id | drop |
| 0x3 | target constant id, big-endian u64, the console's own | silence |
| 0xB | target variable id, big-endian u32, the console's own | silence |
| 0xF | number of protocols, the console's own count | silence |
| 0x10 | that many (id, version) pairs | version low → result 2, high → result 3 |
| | station location size, big-endian u16, 0x20..0x40 | drop |
| | the station location | drop |

The protocol ids are never checked. The station location's address-size byte must be 2, 6 or 18; a
malformed location reads as variable id 0.

Result codes (`0x0154f5e8`):

| result | meaning |
|---|---|
| 2 | the requester's version too low |
| 3 | too high |
| 7 | every version matched and the second stage refused it, or the variable id is already one of the console's stations (cleared when the station leaves, or by a fresh id) |

Sizes: ack 8 bytes, denial 15, disconnection response 1.

### The version-4 connection request

The handler `0x017c62a0`:

    [0]     message type            1
    [1]     nat flags
    [2]     platform id             must be 9
    [3]     0 or 1; 1 means the request also names a target variable id
    [4]     target constant id      big-endian u64, the console's own
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1
    [0x10]  nat location / protocol count
    [0x11]  the sender's station location (deserializer `0x0185ee20`)

There is no protocol list. With [3] = 1 the console does not answer. A wrong platform is answered
with `02 02 09 00` and 13 zero bytes (result 2); later checks are silent.

The handshake, [3] cleared:

    ->   the console's connection request
    <-   the joiner's connection response, result 0, carrying the console's constant and variable ids
    ->   a type-5 ack
    ->   its own connection response, ~600 bytes, carrying the joiner's ids and the player's name,
         repeated until acknowledged

Sending the type-5 ack of the console's request stops its retransmission (`--ack-request`); a
response is accepted without it.

### What a connection response must satisfy to be read

Types 2 and 7 reach `0x017c6e70`. A response whose result is not 2 is dropped in silence unless:

| field | requirement |
|---|---|
| `[5]` big-endian u64 | the receiver's own constant id |
| `[0xD]` big-endian u32 | the receiver's own variable id |
| the station location | resolves to a station it knows |
| `[0x37]`, result 0 only | under 5 |
| station state | 4, checked after the ack is sent; 5 on acceptance |

The console acks the response after the `[0x37]` check: a response never acked failed the ids, the
location or `[0x37]`. A 17-byte response leaves `[0x37]` in stale buffer bytes past its end;
`station4.build_connection_response(..., min_size=ACCEPTED_RESPONSE_SIZE)` pads to 0x38 and writes 1
there. Acceptance at this layer does not start the game above it
([Reaching the game layer](swsh_session.md#reaching-the-game-layer)).

The console's own connection response is acceptance; its request retransmitted every 500 ms with the
same trailing counter is rejection; silence alone is neither.

## The Mesh Protocol (0x18)

Byte 0 minus one indexes a 129-entry table (version 4: `0x017c0c80`); version 4 lacks BDSP's 0x22
DUMMY_MESSAGE and 0x23 DUMMY_ACK.

The join request is six bytes: type 1, station index 253 ("not in a mesh yet"), an ack id. Pia
retransmits it for about ten seconds.

The join response header is sixteen bytes. A refusal is `[1] == 0`, `[2] == [3] == 0xFF`, reason
at [4]; otherwise [1] is the station count and 0xC the big-endian update counter. Station entries:

| version | entry | layout |
|---|---|---|
| 5.31-5.45 | 68 bytes | 64-byte station location, station index, big-endian join order |
| 4 | 64 bytes | index at 0x3E, no join order, 32 stations at most |

Version 4 walks `stations` entries when unfragmented and [6] entries into slot [7] when fragmented;
5.31-5.45 takes [6] in both. `parse_join_response(version4=True)` follows both paths.

UPDATE_MESH (0x20), about once a second, lists who is in the mesh; BDSP always sends 556 bytes with
unused seats zeroed, so walk the `entries` byte (`mesh_protocol.parse_update_mesh()`).

### Host migration

Mesh messages on 0x18 port 1 arrive under the reliable header. A station named next host must
answer.

| message | bytes | handler requires |
|---|---|---|
| MIGRATION_START (0x44) | `[0x44, host index, new host index]` | size 3, [1] the mesh's host index, [2] <= 0x1F and not the host index (`0x017c1f00`) |
| MIGRATION_RESPONSE (0x48) | `[0x48, own station index]` | size 2 (`0x017c10ac`) |
| MIGRATION_FINISH (0x41) | `[0x41, host index, flag & 1]` | size 3, [1] the host index (`0x017c0fb0`) |

Responses go to the new host, which broadcasts MIGRATION_FINISH. `pokeldn/ldn/mesh_protocol.py`
builds and parses all three.

## The RTT protocol (0x58)

The host times each station from its entry into the mesh. Version 9's message is thirteen bytes:

    u8   kind        0 = request, 1 = response
    u64  timestamp   big-endian, the sender's own clock
    u32  target      big-endian, whose reply this is; zero is accepted by everyone

Version 4 reads a flat sixteen bytes and ignores a thirteen-byte answer;
`rtt_protocol.response_for_v4()` echoes the request and sets only the kind.

A station answers kind 1 with the timestamp echoed. The host keeps a nine-sample ring per station
whose median is the RTT; BDSP timestamps run at about 31.36 MHz. A silent station is not dropped,
only no longer sampled. BDSP requests every 410 ms while unanswered and every 508 ms once every ring
is full (`0x015ace54`); the reliable retransmit interval follows the RTT.

## The reliable sliding window (0x7c)

### Version 9 (Pia 5.29-5.43)

    0x0  1  flags     1 application data, 2 message start, 4 message end, 8 is initialized,
                      16 zlib, 32 reset, 64 reset ack
    0x1  1  stream id
    0x2  2  payload size, big-endian
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  number of destination bits (N)
    0x9  4 * ceil(N / 32)  destination bitmap words, big-endian
            payload

N of 0x20 or more and a payload of 0x5a1 or more are refused.

With the application-data flag clear the payload is a bulk acknowledgement:

    0x0  1   a bitfield, 0 in every captured ack
    0x1  1   entry count, refused at 0x21 or more
    0x2  21 * n  entries: u8 stream id, u16be ack id, u16be `ack id - 1`, 16-byte ack mask

A retail console's ack to sequences 0 and 1:

    00 00 0017 ffff 0003 00   00 01   00 0002 0001  00 * 16

A control message has sequence id 0xFFFF. `ack id` is one more than the highest sequence received.
`reliable5.build_ack_message()` reproduces it byte for byte. A data message with sequence 0 draws no
ack; sequence 1 does.

### What the receiver discards in silence

The receive path (Scarlet 4.0.0 `0x006f0330`, BDSP 1.3.0 `0x159fb98`) discards a message and still
returns success when:

| the message is discarded when | Scarlet | ack still sent |
|---|---|---|
| the window is uninitialised and the flags lack `is initialized` | `0x6f037c` | no |
| the sequence id is below the window base | `0x6f03cc` | yes |
| the destination count is non-zero and the bitmap lacks the receiver's bit | `0x6f0430` | no |
| the stream id differs from the one latched at initialisation | `0x6f0454` | no |
| the ring slot is already occupied | `0x6f0540` | yes |

The two acked cases make the sender read an ack for a message the application never receives. A
sequence past the window's end returns `0x4c0d`, a reassembly over `0x5a1` bytes `0x10407`, a zlib
payload that does not inflate `0x2c03`.

The first message on a stream sets the base to its own sequence id. The receiver also advances its
base to the sender's `lowest pending` (Scarlet `0x6eff24`). A sender declaring `lowest pending`
above its next sequence makes the peer discard those messages with an ack, on Scarlet and BDSP.
An ack carries the sender's own lowest unacknowledged sequence, in the header and in the entry's
second halfword. BDSP sends an owed ack on a timer and alongside data, to every live peer.

### Who a window sends to (Pia 6)

A `ReliableSlidingWindow`'s destinations are station pointers by station index, filled by Pia on
station join and leave events with no game code (Scarlet 4.0.0: registration `0x6ef588`). A station
is missing from the list only before its join event, after its leave, while the protocol has station
index 0xfd, or when registration refused it (index taken, or the station already registered). The
bulk-ack composer `0x6f2138` reads the same list: a bit in an ack shows the window registered the
station, nothing about messages sent to it.

### Version 4

One header class serves 0x7C and 0x80 (`ReliableSlidingWindow::MessageHeader`, Deserialize
`0x0184e390`):

    0x0  1  flags
    0x1  1  stream id
    0x2  2  payload size, big-endian    refused at 0x589 and above
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  destination count           refused at 0x20 and above
    0x9  8 * count  station constant ids, big-endian

The versions agree at count 0, which is every 0x7C message either side sends.

The receive path (`0x01859338`) refuses in silence a payload over `0x57F - 8 * count`, a message
length other than `9 + 8 * count + size`, a stream id other than the window's for that station, a
destination list without the receiver, and a first message without FLAG_IS_INITIALIZED. Flags bit 5
is RESET, bit 6 RESET_ACK, bit 0 APPLICATION_DATA; anything else is an ack.

A console sends flags 0x0F on its first message and 0x07 after.
`reliable4.build_data_message(bytes.fromhex("610000000a00"))` reproduces a console's sequence 1:
`0f0000060001000100610000000a00`.

The ack payload is exactly 0x260 bytes, 32 entries of 19 bytes: u8 stream id, u16be ack id, 16-byte
mask (handler `0x01859a84`; any other size answers 0x2c03). `reliable4.build_ack_payload` fills
every slot with the same entry. A Shield leaves unused slots holding stale bytes: read only the entry
for the acked stream, or a sender overruns the console's window and it stops acking.

Growing sequence ids over a fixed `lowest_pending` mean a growing backlog.

A message too long for one payload is split over consecutive sequence ids, flag 0x02 on the first,
0x04 on the last, and 0x10 on each fragment that is deflated on its own. A Shield host's battle turn
log (2074 to 2657 bytes) goes as two: flags 0x03 with 1407 bytes unchanged, then 0x15 with the rest
as a zlib stream; the message is the first body followed by the second inflated. On an emulated
loopback the closing fragment arrived before its opener for 3 of 11 split messages: reassemble in
sequence order, never in arrival order.

## Protocol 0x80, the broadcast reliable window

`nn::pia::transport::BroadcastReliableProtocol`. Its messages are compressed (version-4 flag 0x10):
the reliable header with destination count 1 and one station constant id over the 0x260 ack
payload, 625 bytes decompressed. The ack has one slot per station index: a console fills 0..7 and
leaves 8..31 zero, 8 being `max_total` from the join response.

## Protocol 0x81, the stream broadcast reliable transfer (Pia 6)

`StreamBroadcastReliableProtocol` moves one fixed-size block from a station to every station that
asked for it, in chunks (Scarlet 4.0.0, update `0x6f5360`). It retransmits on the same deadline as
0x7C and 0x80, and never with no RTT sample for any destination.

Each message carries an eleven-byte StreamData header (`0x6f60e8`):

    +0  1  kind: 0 a receive posted, 1 the first chunk, 2 a later chunk, 3 to 6 control
    +1  1  transfer id
    +2  1  percent of the block delivered after this chunk
    +3  4  big-endian u32: the receive capacity in a kind 0, zero in a chunk
    +7  4  big-endian u32: the length of the data that follows
    +11    the data

A posted receive sends a kind 0 carrying its capacity; the smallest capacity posted bounds the block
the send API accepts. A send is refused for a size above that, id 0xff, or no station having posted
a receive for the id. Chunks are `[window+0x70] - 11` bytes.

| kind | what the receiver does |
|---|---|
| 0, receive posted | records the sender's id and capacity, or answers kind 3 while busy |
| 1, first chunk | resets the received count, then as kind 2 |
| 2, chunk | copies the data if it fits; the receive completes at percent 100 |
| 3, busy sender refuses a receive | resets the transfer |
| 4, sender cancels | resets the transfer |
| 5, receiver cancels | drops that receiver; the sender answers kind 6 |
| 6, sender acks the cancel | resets |

Control kinds carry id 0xff. A send completes when every destination's window acknowledges the last
chunk.

## Protocol 0x84, the reliable broadcast transfer

`nn::pia::transport::ReliableBroadcastProtocol` carries Sword/Shield's trade snapshot:

| kind | meaning |
|---|---|
| 0x11 / 0x12 | a data fragment; a counter at [4] and a capacity at [10] |
| 0x19 | the transfer is complete |
| 0x21 | an ack carrying a contiguous base and a bitmask of what arrived early |
| 0x28 | the answer to 0x19 |

A receiver that never answers never sees the last three, and the sender keeps retransmitting.
`pokeldn/ldn/broadcast4.py`. A console sends its own transfer on port 0 and acks the peer's on port
1.

## Unresolved

- Whether a LAN host's reply to the session's first request keeps a 0xFF last key-parameter byte at
  0xFF or carries into the byte before it when it increments.

- What a retail Sword reads at `[0x37]` of a 17-byte connection response, in bytes the sender does
  not write.
- What writes the nat-flags byte at [1] of a version-4 connection request; it varies between
  connections.
- Which error code a live refusal hands to the waiting context (`0x01769720`).

## Credits

The header version table, the session-key derivations and the nonce layouts come from the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol)
([Reverse-engineering a Switch title](switch_re.md) covers searching it). Which derivation belongs
to which network type, the `cryptoKeyDataSeed` value and the version rule were read out of retail
titles' own code.

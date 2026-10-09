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
| module | `pokeldn/ldn/pia_connect.py` | `pokeldn/ldn/pia5.py` (round-trips captures byte for byte) | `pokeldn/ldn/pia4.py` |

Unless a section names another build, `0x01...` addresses are Shield 1.3.2's decompressed `main`
(as `tools/switch/nso_read.py` lays it out) and `main.bin 0x01...` addresses are BDSP 1.3.0's.

## Packet headers

### Version 9 (Pia 5.27-5.45)

From `nn::pia::common::Packet::Header`; the parser byte-swaps three fields with `rev`.

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

From the deserializer `0x01774730`, which requires more than 0x1f bytes (`cmp w2, #0x1f; b.hi`):

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 4
    0x05  1  connection id
    0x06  2  packet id, big-endian
    0x08  8  AES-GCM nonce, a monotonic counter
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext

The two small fields are per destination station, both 0 on a packet sent to no station in
particular: every one of 484 packets a retail Sword sent (`0x017beb14`, `0x017beb20`). Sent to one
station (`0x017beb74`, `0x017beb78`, byte from the caller, halfword from a session object):

- Connection id: the sender's byte at station +0x78, set at connection to `2 + (tick mod 254)`
  (`0x017c6a00`); the peer's arrives in the connection setup and is kept at +0x79. The receiver
  (`0x017bdbd0`) drops an id of 2 or more that differs from the one it holds; 0 and 1 pass.
- Packet id: a per-station counter stepped by `0x0185dd00` before each send, 1 to 0xFFFF. The
  receiver (`0x0185dd20`) passes 0 as unsequenced; a non-zero id not above the last one from that
  station is dropped, and a gap is added to the station's lost-packet count at +0x18.

Sending 0 in both, as the console does, passes every path. The initializer `0x017748bc` stores
`0x00000004_32AB9864` as one 64-bit word and zeroes nonce and tag; validators `0x017749f0`,
`0x01774b60`, `0x01774d00` check `(byte & 0x7f) == 4` (BDSP: the same with 9). Below the header,
version 4 shares version 9's session key and IV, and its framing plus one field.

## Message framing

A Pia payload carries one or more messages, each opening with a presence byte saying which header
fields follow. A field it omits is inherited from the previous message in the packet (`0x01853050`,
bit by bit): flags at +9, size at +0xA, protocol|port at +0xC, destination at +0x10, source at
+0x18. An inherited size is bounds-checked against 0x589. The walk stops at `0xFF` and nothing else:
`0x00` is a legal one-byte header, a message inheriting every field.

Each band's reader copies the previous header forward, then reads the fields whose bits are set:

| header version | title read | reader | stop test | next message starts |
|---|---|---|---|---|
| 4 | Sword | `0x01852da0` | `0xFF` | on a multiple of four |
| 9 (5.27-5.45) | Shining Pearl 1.3.0 | `0x159b980`, copy `0x159b9ec`..`0x159ba10`, fields `0x159bb60` | `cmp w8, #0xff` at `0x159b9d4` | on a multiple of four (`0x15abf68`..`0x15abf70`, all seven callers) |
| 11 (6.16-6.30) | Legends Arceus 1.1.1 | `0x7484cc`, copy `0x748538`..`0x74855c`, fields `0x7486a8` | `0x748520` | where the payload ends (`0x743f14`..`0x743f18`) |
| 11 | Scarlet 4.0.0 | `0x6ed2d0`, copy `0x6ed348`..`0x6ed360`, fields `0x6ed4b4` | `0x6ed324` | where the payload ends (`0x6e9054`..`0x6e905c`) |
| 16 (6.39-7.2) | Legends Z-A | `0x256e088`, copy `0x256dac4`, fields `0x256de5c` | none: the packet header states its padding | where the payload ends |

Stations bundle runs of equal-sized messages behind presence 0x00: Scarlet its zero-filled record
chunks, Shining Pearl a reliable message after one of the same size, Arceus its second 24-byte
record. Treating 0x00 as a message ends every walk exactly on the `0xFF` padding (5,866 Shining
Pearl, 11,501 Arceus, 38,350 Scarlet packets); stopping at 0x00 leaves bytes unread in 3,444 of them
and drops everything after. `tests/test_pia_bundled.py` pins one packet of each title.

Version 3 (Let's Go 1.0.2) has no presence byte: a fixed 0x16-byte header whose second byte must be
1 (`0x5ae7d0`), the walk stopping at `0xFF` (`0x5ae790`).

Version 4 computes the header size inline at eighteen sites, always as five conditional adds over a
base of one:

    tst w9, #1    -> +1       message flags
    tst w9, #2    -> +2       payload size, big-endian
    tst w9, #4    -> +4       protocol id and a 3-byte port
    tst w9, #8    -> +8       destination
    tst w9, #0x10 -> +8       the sender's station constant id

Presence 0x7F gives a 24-byte header; bits 0x20/0x40 add nothing, as in version 9, whose header is
16 bytes. The eight-byte constant id is `station_protocol.ldn_constant_id` over the sender's MAC, the
Local Protocol's `host_constant_id`: big-endian here, little-endian in the Local Protocol body.

Version 16 (Z-A) narrows the fields: header size `0x256dfc8` is one byte plus one for flags, two for
size, and one each for bits 0x04 (protocol), 0x08 (port) and 0x10. The bit-0x10 byte sits between
protocol and port (`0x256df54`, setter `0x256a8e8`); a fresh header holds protocol 0xFF, 0xFD there
and port 0 (`0x256a8c0`). The reader ignores bits 0x20 to 0x80 and rejects a size of 0x590 or more
(`0x256df04`). Bit 0x10 has not been seen on the air. `pokeldn.ldn.reliable.parse_messages` reads it.

In versions 4 and 9 each message is padded to a multiple of four (Shining Pearl pads with 0x00),
stepped over unread; the packet tail is `0xFF`. `pia4.parse_packet()` resolves the inheritance,
`pia4.parse_messages()` returns each header as sent. A walk is correct when consumed bytes plus
`0xFF` padding account for every packet's whole plaintext.

### Compression

A payload may be a zlib stream, flagged per message in the message flags: 0x20 in 5.27-5.45, 0x10
in version 4. The version-5 reliable header has its own zlib flag, 0x10; BDSP sets it on some game messages (a
23-byte one went as a 20-byte stream with a 4 KB window) ([BDSP's protocol](bdsp_protocol.md)).

BDSP switches compression on mid-session. Read raw, a compressed 31-byte message parses into a
header claiming a payload of 0x6260. Over 2835 version-4 messages, `flags & 0x10` predicts
decompressibility exactly (256 set, all valid; 2579 clear, none). A zlib stream's first two bytes,
read as a big-endian halfword, are a multiple of 31.

### The footer

A packet sent to more than one console carries a footer: one big-endian halfword per recipient, the
low half of its variable id, length in the header byte at 0x0f. The GCM tag does not cover it: the
ciphertext is `data[0x20 : len(data) - footer_size]` (`pokeldn/ldn/pia5.ciphertext()`), and a
footer left in fails authentication with no other symptom. When only some packets authenticate,
group the failures by footer size first.

## Session keys

One session-key implementation per network type, in separate classes:

| network type | class | derivation |
|---|---|---|
| LDN (local wireless, the Union Room) | `nn::pia::local::LocalProtocol` | AES-128-ECB under the game key, over 16 bytes drawn from an xorshift128 seeded from a session value |
| LAN | `nn::pia::lan::LanProtocol` | first 16 bytes of HMAC-SHA256(game key, a 32-byte parameter whose last byte is incremented) |
| NEX (internet) | `nn::pia::nex::*` | session key from the matchmaking server |

"The SSID or random values seeded with the session parameter", in published prose, names two
implementations; the class name says which one a capture used.

### The game key

    key = cryptoKeyDataSeed                     the game's own 16-byte constant
    key[1]  = (version >> 8) & 0xFF
    key[3]  = (version >> 4) & 0xFF             version = the local communication version,
    key[7]  = (version >> 1) & 0xFF                       which the advertisement carries
    key[12] = (version >> 0) & 0xFF

A published per-game key is this value for one game version and differs from the seed in exactly
bytes 1, 3, 7 and 12 (`ldn_game_key()`). Sword/Shield's key is a 16-byte ASCII literal loaded with
one `ldp` and used unchanged, with no seed and no version substitution.

### The LDN session key

For Pia 5.9-5.45:

    rnd = four SEAD draws, seeded with the session parameter from the advertisement (+0x0c),
          packed little-endian into 16 bytes
    session key = AES-128-ECB(game key).encrypt(rnd)

SEAD, Nintendo's standard-library RNG, seeds its state by `s[i] = (prev ^ (prev >> 30)) *
0x6C078965 + i` and runs an xorshift128 with shifts 11, 8 and 19 (`pokeldn/ldn/sead.py`;
`pia5.ldn_session_key()`). For Pia 6.16+ (FireRed) the session key is AES of the SSID under the game
key ([The wireless layer](ldn.md#hosting-for-an-emulator)).

### The AES-GCM IV

For Pia 5.27-5.45 and version 4 (`ldn_nonce_crc()`, `gcm_iv()`):

    IV[0..2]  = first three bytes of crc32( network id (little-endian) || source MAC address )
    IV[3]     = source variable id & 0xFF        from the packet header
    IV[4..11] = the packet's 8-byte header nonce

The source MAC is not in the packet; the rest comes from the capture or the advertisement. The
plaintext is padded with `0xFF` to a multiple of 16, known plaintext that tests a candidate key in
one AES block.

## The protocols

From `GetProtocolId` (vfunc4 on every `nn::pia` protocol object, a two-word body), read over the
RTTI vtables.

| id | class | notes |
|---|---|---|
| 0x14 | MeshStationProtocol | the connection handshake; also carries every mesh acknowledgement |
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
v0. Mesh version 3 pins the library to Pia 5.30-5.45, reliable version 3 to 5.31-5.43.

### Joining a mesh

A station joins through the update session (0x24), the connection request (0x14) and the join
request (0x18), in order; each retransmits every 500 ms until acknowledged.

The Mesh Protocol has no ack type (5.31-5.43 has no builder): the four sites acking a mesh message
call `MeshStationProtocol`, so the ack is the eight-byte type-5 ack on 0x14, `05 00 00 00` and the
ack id big-endian. The ack id is the message's last four bytes whatever its
length (`size - 4` with a borrow check; 0 under four bytes). `pokeldn/ldn/mesh_protocol.ack_for()`.
A host acks a join request before sending the join response; the receiver acks every copy.

### Leaving a session (Pia 6)

`Session::LeaveAsync` starts `LeaveSessionJob`, whose first step, LeaveSessionJob::LeaveMesh, starts
`LeaveMeshJob` on a station that is not the host (`LeaveMeshWithHostMigrationJob` on the host).
`LeaveMeshJob`'s first step, SendLeaveRequest, sends the Session type-3 leave request and waits 500 ms
for the host's type-4 response, four sends at most. No timer runs inside Pia between the call and the
first type 3; a delay before it belongs to the game.

| | Legends Arceus 1.1.1 | GBA app (Pia 6.39) |
|---|---|---|
| `Session::LeaveAsync` | `0x72a6dc` | `0xb1060` |
| `LeaveSessionJob` startup, first step LeaveMesh | `0x72c5a4` -> `0x72c640` | `0xb460c` -> `0xb46f0` |
| non-host branch to the `LeaveMeshJob` startup | `0x734f04` -> `0x734dd0` -> `0x73b820` | |
| SendLeaveRequest | `0x73b898` | `0xcacf4` |

The steps are named by strings the job stores beside each step pointer (`LeaveSessionJob::LeaveMesh`
at `0x37a2eb9` in Arceus, `0x174e53` in the GBA app). Its other steps are WaitLeaveMesh,
WaitLeaveMeshWithHostMigration, WaitHostMigrated, MeshCleanup and DisconnectNetwork, and in 6.39
also WaitDisconnectNetwork, SendMonitoringData and CompleteProcess.

## The Local Protocol (0x24)

The host broadcasts an update session (type 0x11) about every 100 ms until every station acks it:

    local message header  version 1, type 0x11, size 73
    sequence id
    network id            random, not the advertisement's network id
    host variable id      the same value as the packet header's source variable id
    host constant id
    allow participating
    node 0..7             address:port and a ranking byte each
    host migration state

Eight nine-byte node slots and one byte. The Pia message header is big-endian, these fields
little-endian, a local address inside them big-endian. `pokeldn/ldn/local_protocol.py` parses it and
version 4's.

### The ack

The ack (type 0x21) is 20 bytes, from `LocalAckMessage::Serialize` (`main.bin 0x016bc0f4`): `1` at
0, the type at 1, the payload-size halfword at 2, six zero bytes at 4, the sequence id at 0x0C, four
zero bytes at 0x10. The constructor (`0x016bc0c8`, `mov w8, #0x14; str w8, [x0, #0x14]`) writes 20
into the halfword at +0x14 and zeroes the payload size at +0x16.

`LocalProtocol` has one send path (`0x016af22c`) for all four types, so an ack is framed like the
update session: presence `0x7F`, flags `0x11` ("destination is a bitmap" plus "may not be bundled"),
protocol 36, port 0, destination 0. The bitmap (`0x0159a15c`) is `1 << station index`, or 0 for
broadcast. A client broadcasts its ack to the network broadcast address, packet `dst_var` 0, message
destination 0; the rebroadcast stopping is the pass signal.

An ack is attributed by the sender's address: `0x016af96c` calls `0x016aec94`, which walks nine node
slots at `this+0x188` (stride 0x40) comparing 16 bytes of address at +8 and the port at +0x18. The
client's variable id feeds the IV (low byte of the source variable id), so it must be stable within a
run and non-zero.

## The Mesh Station Protocol (0x14)

The dispatcher indexes a seven-entry table with byte 0 minus one (version 4: `0x017c5f50`, table
`0x02081804`; BDSP: `0x0154e848`, table `0x3e6b38f`): connection request and response,
disconnection request and response, ack, relay connection request and response.

### The version-9 connection request

Checked in order:

| offset | field | a failure gives |
|---|---|---|
| | size 15..949 | drop |
| 0x0 | message type, connection result, platform id | drop |
| 0x3 | target constant id, big-endian u64, compared with the console's own | silence |
| 0xB | target variable id, big-endian u32, compared with the console's own | silence |
| 0xF | number of protocols, compared with the console's own count | silence (error 0x11c26) |
| 0x10 | that many (id, version) pairs | version low → result 2, high → result 3, both replied |
| | station location size, big-endian u16, 0x20..0x40 | drop |
| | the station location | drop |

`0x0159b850` returns version 0 for an unregistered id, so `(0xFF, 1)` always draws "too high": the N
of `(0xFF, 1)` pairs that draws a denial is the console's protocol count.

The result byte maps from internal errors at `0x0154f5e8`:

| error | result | meaning |
|---|---|---|
| 0x646f | 2 | the requester's version too low |
| 0x6470 | 3 | too high |
| 0xc24 | 4 | |
| 0xc25 | 1 | |
| 0x11c0f | 7 | parsed, every version matched, the second stage refused it; also "this variable id is already one of my stations" (cleared when the station leaves, the player re-entering the room, or by a fresh id) |
| 0x11c26 | *(none)* | protocol count mismatch: silence |

The ids are never checked: nine `(0xFF, 0)` entries pass the negotiation.

The station location's address-size byte counts the port: the InetAddress parser tests `1 << size`
against `0x00040044`, so only 2, 6 and 18 pass. The request parser discards the location's error, so
a malformed location reads as a request with variable id 0 and every variable id draws the same
refusal.

Sizes from the binary: ack 8 bytes (`0x0154fa2c`), denial 15 (`0x015501ec`), disconnection response
1 (`0x0154ea60`).

### The version-4 connection request

The handler `0x017c62a0` reads a different message on the same protocol:

    [0]     message type            1
    [1]     a byte compared against the station's own byte at +0x79
    [2]     platform id             must be 9   (5.27-5.45 checks 4)
    [3]     0 or 1; anything higher is rejected. 1 means the request also names a target variable id
    [4]     target constant id      big-endian u64, compared against the console's own
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1
    [0x10]  protocol count          compared against the console's own count at +0x78
    [0x11]  the sender's station location

From offset 3 on, version 9's fields sit one byte earlier. There is no protocol list: from 0x11 on is
the station location (one serializer call capped at 0x40 bytes), unchanged from version 9
(deserializer `0x0185ee20`, same offsets, address size 2, 6 or 18), which makes [1] and [0x10] its
nat flags and nat location.

With [3] = 1 the console does not answer (96 requests). With [3] = 0 the console answers with its own request: its
location, constant id, the variable id the update session gave the joiner, a service variable id, a
nat quad, then an ack id, a per-message counter `0x017d5750` reads at message size minus four.

The platform check (`0x017c62e8`) runs first and a mismatch is answered: the response sender
`0x017c6c30` allocates 17 bytes, `[0] = 2`, `[1] = result`, `[2] = 9`, `[3] = 0`. Later checks are
silent, so a wrong platform tells "never reached the handler" from "failed a later check". Platform 4
drew from a retail Sword `02 02 09 00 00 00 00 00 00 00 00 00 00 00 00 00 00`: result 2.

The handshake, [3] cleared:

    ->   the console's connection request
    <-   the joiner's connection response, result 0, carrying the console's constant and variable ids
    ->   `05 00 00 00 <ack id>`, a type-5 ack, eight bytes
    ->   its own connection response, result 0, ~600 bytes, carrying the joiner's constant id,
         variable id and the player's name in plain ASCII, repeated until acknowledged

The u32 in an ack is the acked message's trailing counter. Send the type-5 ack of the console's
request: a Shield 1.3.2 under Ryujinx ignores the response without one and re-requests every 10 s
(`--ack-request` on the bridge driver sends it).

### What a connection response must satisfy to be read

Both types reach handler `0x017c6e70` (`0x017c60c0` sets a flag for a request, the type-2 dispatch
entry clears it). A response whose result is not 2 is checked field by field, each failure a silent
drop:

| the handler reads | it requires | a failure gives |
|---|---|---|
| `[1]` the result byte | 2 takes a separate path | |
| `[5]` a big-endian u64 | the receiver's own constant id | drop, `0x017c6f48` |
| `[0xD]` a big-endian u32 | the receiver's own variable id | drop, `0x017c6f68` |
| the sender's station location | resolves to a station it knows | drop, `0x017c6f04` |
| `[0x37]` one byte, result 0 only | under 5 | drop, `0x017c6ff0` |

A 17-byte response (`RESPONSE_SIZE`, the short-form allocation `mov w3, #0x11` at `0x017c6c30`)
leaves `[0x37]` 38 bytes past its end, in stale buffer bytes, so whether it is read depends on
memory the sender does not control: an emulated Shield accepted 3 of 22 byte-identical responses
and, after a restart, 0 of 49; a retail Sword accepted those it was sent. The console's own
accepted response is 840 bytes with 1 at `[0x37]`;
`station4.build_connection_response(..., min_size=ACCEPTED_RESPONSE_SIZE)` pads to 0x38 and writes 1.

After the response: the console's connection response is acceptance; its request retransmitted every
500 ms with the same trailing counter is rejection (a response carrying the joiner's own ids drew
20 retransmits, then silence); silence alone is neither, and it re-requests about 10 s later.

The nat-flags byte at [1] of the console's request varies between connections and follows no byte
the joiner controls (both readings of each tried over 26 connections). What writes it is unknown; its
record is filled by the station-location parser `0x0185ee20`.

## The Mesh Protocol (0x18)

`MeshProtocol::vfunc9` (the receive slot) takes byte [0] minus one, bounded at 0x80, through a table
(version 4: dispatcher `0x017c0c80`, table `0x02081564`). Nineteen of 129 entries are live; version
4's are BDSP's minus 0x22 DUMMY_MESSAGE and 0x23 DUMMY_ACK.

The join request is six bytes: type 1, station index 253 ("not in a mesh yet"), an ack id. The
version-4 handler (`0x017c1700`) checks [1] against 0xFD, takes the ack id with `0x017d5750` and
acks on 0x14 (`0x017c6dd0`). Pia retransmits it for about ten seconds.

The join response header is sixteen bytes in both bands. The version-4 parser `0x017b4830` reads the
refusal shape first (`[1] == 0`, `[2] == 0xFF`, `[3] == 0xFF`, reason at [4]), then the station count
at [1] against its maximum, [8] [9] [0xA] as one big-endian 24-bit value, and the update counter
big-endian at 0xC.

Station entries: 5.31-5.45 uses 68 bytes (64-byte station location, station index, big-endian
halfword join order); version 4 uses 64 with the index at 0x3E and no join order (cursor starts at
`0x10 + 0x3E`, `ldrb w8, [x20], #0x40`; a response over `0x810 = 0x10 + 32 * 0x40` is refused
against the 32-station bound at `0x017bfa34`). Two lengths confirm it:

    join response   148 B  =  0x10 + 2 * 0x40 + 4        68-byte entries would give 156
    update mesh     524 B  =  12   + 8 * 0x40            BDSP's eight 68-byte seats give 556

Version 4 takes the entry count from a different field per path: unfragmented (`fragments == 1`,
`0x017b48f4`) walks `stations` entries from base 0 and never reads [6] or [7]; fragmented
(`0x017b4b6c`, at most three fragments) walks [6] entries into slot [7] and checks [1]-[4] against
the first fragment. 5.31-5.45 takes [6] in both, so a single-fragment response with [6] zero reads
as an empty mesh there. `parse_join_response(version4=True)` follows both paths.

UPDATE_MESH (0x20), about once a second, is the host's list of who is in the mesh; in BDSP always
the full 556 bytes with unused seats zeroed, so walk the `entries` byte
(`mesh_protocol.parse_update_mesh()`). The 5.31-5.45 join order counts joins since the mesh was created: after three
successive connections from one machine it read 0 for the host and 3 for the client at index 1.

### Host migration

A station named next host must answer. Mesh messages on 0x18 port 1 arrive under the reliable
header.

MIGRATION_START (0x44) is three bytes. The handler `0x017c1f00` refuses the message unless

    size == 3                                     0x017c1f54
    [1] == the mesh's HOST index, byte 0xAB       0x017c1f64, getter 0x017bbfe0
    [2] <= 0x1F                                   0x017c1f78, the 32-station bound
    [2] != that host index                        0x017c1f8c

and the sender `0x017c31b8` builds exactly `[0x44, host index, new host index]`.

The answer is `[0x48, own station index]`: the MIGRATION_RESPONSE handler `0x017c10ac` requires
`size == 2`, and the builder `0x017c3310` writes `[0x48, w22]` with w22 from `0x017bc430`. The getters
are one byte apart: `0x017bbfe0` `ldrb w0, [x0, #0xAB]` (host index), `0x017bc430` `ldrb w0, [x0,
#0xAC]` (own index), equal on the station hosting the mesh.

MIGRATION_FINISH (0x41) closes it: `[0x41, host index, flag & 1]` (`0x017c2ef0`), handler
`0x017c0fb0` checking `size == 3` and [1] against the host index.

Responses go to the new host (`0x017c3250`, called by `0x017ca1a0`). That station broadcasts
`MIGRATION_FINISH`; sending a response to the departing host does not complete the handover.

`pokeldn/ldn/mesh_protocol.py`: `parse_migration_start`, `build_migration_response`,
`build_migration_finish`, `parse_migration_finish`. None of the four published Sword/Shield
clients handles migration; between two consoles the named station answers it.

## The RTT protocol (0x58)

The host times each station from its entry into the mesh (no wiki page covers this). Version 9's
message is thirteen bytes:

    u8   kind        0 = request, 1 = response; anything else is dropped
    u64  timestamp   big-endian, the sender's own clock
    u32  target      big-endian, whose reply this is; zero is accepted by everyone

Version 4 keeps id 0x58 (vfunc4 `0x0185d590`); its parser (`0x0185d2a0`) reads a flat sixteen bytes
and ignores a thirteen-byte answer. Bytes 1..7 are zero in every request observed, meaning unknown;
`rtt_protocol.response_for_v4()` echoes them and sets only the kind.

A station answers kind 1 with the timestamp echoed. The host puts `(now - echoed) / ticks per ms`
into a nine-sample ring per station, whose median is the RTT once full; BDSP timestamps run at about
31.36 MHz. In the BDSP sessions measured the RTT protocol dropped no silent station; it stopped
sampling it. The update's request period has two branches behind `0x015ace54`, 410 ms and 500 ms:
unanswered, BDSP requested every 410 ms; once every ring was full, every 508 ms, and the reliable
retransmit interval followed the small measured RTT (about six rounds a second).

BDSP addresses: id and version `0x015ada10`/`0x015ada18`, size (`mov w0, #0xd`) `0x015adab4`,
serialise/parse `0x015ada24`/`0x015ad54c`, update `0x015acd90`, answer builder `0x015ad024`, target
check `0x015ad000`, sample ring `0x015ad058`.

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

`GetSize` is `9 + (((N + 0x1f) >> 3) & 0x3c)`, so 9 or 13 bytes. N of 0x20 or more and a payload of
0x5a1 or more are refused.

With the application-data flag clear the payload is a bulk acknowledgement:

    0x0  1   a bitfield; 0 in every captured ack. Its bit 0 sets a flag on the receiver
    0x1  1   entry count, refused at 0x21 or more
    0x2  21 * n  entries: u8 stream id, u16be ack id, u16be `ack id - 1`, 16-byte ack mask

A retail console's ack to sequences 0 and 1:

    00 00 0017 ffff 0003 00   00 01   00 0002 0001  00 * 16

No flags, stream 0, sequence id 0xFFFF (a control message has no sequence), then the lowest id the
sender still waits on. `ack id` is one more than the highest sequence received.
`pokeldn/ldn/reliable5.build_ack_message()` reproduces it byte for byte. A data message with sequence 0 draws
no ack; sequence 1 draws the ack.

### What the receiver discards in silence

The receive path checks one message against the port's window and copies the payload into a slot:
Scarlet 4.0.0 `main.bin` `0x006f0330`; Brilliant Diamond 1.3.0 `0x159fb98`, reached from the
`ReliableSlidingWindow` receive `0x159f1e4` for flag bit 0 (bit 5 reset, bit 6 reset ack, anything
else an ack for window slot 13; `0x159f88c..0x159f8b8`). Five conditions discard the message and
still return success; two also set the "ack owed" byte (Scarlet protocol `+0x48`, BDSP window
`+0x738`), so the sender reads an ack for a message the application never receives.

| the message is discarded when | Scarlet | BDSP | ack still sent |
|---|---|---|---|
| the window is uninitialised and the flags lack `is initialized` (bit 3) | `0x6f037c` | `0x159fbd8..0x159fbe4` | no |
| the sequence id is below the window base `+0x18` | `0x6f03cc` | `0x159fc30..0x159fc3c` | yes, `0x6f03d0` / `0x159fc3c` |
| the destination count (parsed header `+0x10`) is non-zero and the bitmap lacks the receiver's bit | `0x6f0430` | `0x159fc7c..0x159fca4` | no |
| the stream id (wire byte 1, parsed header `+9`) differs from the one latched at initialisation at window `+0x1e` (BDSP `strb w26, [x24, #0x1e]` `0x159fc14`) | `0x6f0454` | `0x159fcc0..0x159fcc8` | no |
| the ring slot is already occupied | `0x6f0540` | `0x159fdb0..0x159fdb4` | yes, `0x6f0530` / `0x159fda4` (before the test) |

Three conditions return a readable result (Scarlet): a sequence past the window's end `0x4c0d`
(`0x6f04a4`), a reassembly over `0x5a1` bytes `0x10407` (`0x6f05cc`), a zlib payload that does not
inflate `0x2c03` (`0x6f0580`).

The BDSP receive ring sits at window `+0x38`: slot buffer `+0x8`, slot count `+0x10`, ring head
`+0x14`, base sequence `+0x18`, stream id `+0x1e`, initialised flag `+0x1f`. Slots are `0x5b8` bytes;
the ring index wraps by subtraction. A slot: occupied byte `+0`, message-end flag `+1`, zlib flag
`+2`, payload size `+4`, payload from `+6`, per-port handle `+0x5a8`, timestamp `+0x5b0`. The
message-start flag is not stored; reassembly runs from the base to the first slot with the end flag.

The first message on a stream sets the base to its own sequence id (`strh w25, [x24, #0x18]`
`0x159fc10`); the initialised flag is set only after the destination and stream-id tests pass
(`0x159fce4`). A sequence is refused with `0x4c0d` when `seq - base + [ring+0x1c] >= [ring+0x10]`
(`0x159fc60..0x159fc78`); `+0x1c` is a ring head offset, 0 on a fresh stream.

The BDSP window update `0x159fea8` sends the owed ack when the timer (window `+0x740` plus period
`+0x778`) runs out (`0x15a003c..0x15a005c`), calling window slot 11 `0x15a1c78` with the packet
writer at `+0x750` (`0x15a0318`, `0x15a0354..0x15a0364`). Slot 11 returns if `+0x738` is 0
(`0x15a1cb8`), builds a control message with sequence 0xFFFF (`0x15a1de4`), optionally compressed
like data (`+0x7ac`, `0x15a1f70`), sends it through slot 10 (`0x15a203c..0x15a2044`), clears
`+0x738` (`0x15a1fe8`) and restarts the timer (`0x15a1ff8`). Slot 10 writes the protocol-and-port
word at `+0x748` into the header (`0x15a1be8`) and hands the packet to the writer (`0x15a1c0c`,
`0x15a1c20`). The ack goes to every live peer at window `+0x638`; with none, nothing is sent and the
byte is cleared (`0x15a1eb4`, `0x15a1fd8..0x15a1ff8`). Slot 11 also runs on the data path
(`0x15a0298..0x15a02b8`), so acks ride along with data.

Scarlet writes the base at window `+0x18` in `0x6f03a8` (initialisation), `0x6f0238` (one step per
delivered message) and `0x6f1734`/`0x6f176c`, a walk over empty slots towards a target at window
`+0x20` (-1 from `0x6ef228`, no walk while negative, stops at the first occupied slot). The receive
function `0x6efc2c` deserialises the header to `sp+0x18` before the window checks (`0x6efdc8`,
`MessageHeader` vfunc3); `0x6eff24`/`0x6eff28` copy its `lowest pending` (header `+0x6`,
`[sp+0x26]`) to window `+0x20`, and the walk at `0x6eff2c` advances base and ring head up to
`lowest pending - base` slots.

A sender's own `lowest pending` therefore drives the peer's receive base. Declared above the
sender's next sequence, it moves the base past messages not yet sent, which then arrive below it and
are discarded at `0x6f03cc` with an ack: an emulated Scarlet station discarded a host's commit
(sequence 7) at a base of 8, and a BDSP console acked a host's sequences 5 and 6 as `(7, 7)` and
`(8, 8)` and never delivered them. An ack carries the sender's own lowest unacknowledged sequence, in the
header and in the entry's second halfword.

### Who a window sends to (Pia 6)

A `ReliableSlidingWindow`'s destinations are station pointers at window `+0x40`, by station index,
sized by `[[0x46d0860]]+0x50` (Scarlet 4.0.0 `main`), filled by Pia on station events with no game
code. The only non-null store is `0x6ef69c` (`str x23, [x8, x25, lsl #3]`) in `0x6ef588`, which
registers a station at an index; nulls are stored at `0x6ef3dc`, `0x6ef4e0`, `0x6ef9b4`. `0x6ef588`
refuses when:

| refusal | code |
|---|---|
| the window has no capacity, `[w+0x28]` zero | 0x1040c |
| the station is null, is the window's own `[w+8]`, or the index is the window's own `[w+0x10]` | not read |
| the index is already taken | 0x10407 |
| the index's per-station record (window vfunc `0x40`) has byte `+0x1f` set (`0x6ef650`..`0x6ef664`) | 0x10408 |
| the station is already registered at another index | 0x10408 |

On success it resets that record (vfunc `0x10`), writes the index at `+0x24` and a u16 from `w3` at
`+0x26`, and sets the index's bit in `[w+0x74]`. Its callers are slot-11 station-event methods: `0x6e6288`, BroadcastReliableProtocol (0x80),
`bl` at `0x6e630c`, called first by StreamBroadcastReliableProtocol's slot 11 `0x6f51a8`
(`0x6f51bc`); and `0x6ee528`, ReliableProtocol (0x7C), call site `0x6ee5d4`. `0x6e6288` looks the
event's station up by the id at event `+8` (`[[0x46d0860]]` -> `0x1e7c4e8` -> vfunc `+0x38`) and
returns when the protocol's own station index is 0xfd (`0x6ec4f0`) or the station is its own
(`0x6ec4a8`, against `[station+0x30]`). Event 0 registers `[station+0x30]` at index
`[station+0x28]` with `[station+0x38]`; event 1 removes the index (`0x6ef75c`).

A station is missing from the list only before its join event, after its leave, while the protocol
has station index 0xfd, or when `0x6ef588` refused it. The bulk-ack composer `0x6f2138` reads the same list: it skips nulls (`0x6f2324`..`0x6f232c`) and
sets a station's header destination bit (`0x6f22f8`..`0x6f230c`) after checking its ack state,
falling back to the caller's mask (`0x6f2360`..`0x6f2370`). A bit in an ack shows the window
registered the station, nothing about messages sent to it.

### Version 4

One header class serves 0x7C and 0x80: `nn::pia::transport::ReliableSlidingWindow::MessageHeader`
(GetSize `0x0184e480`, Deserialize `0x0184e390`, Serialize `0x0184e230`).

    0x0  1  flags
    0x1  1  stream id
    0x2  2  payload size, big-endian    refused at 0x589 and above (0x0184e3cc)
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  destination count           refused at 0x20 and above (0x0184e404)
    0x9  8 * count  station constant ids, big-endian

`GetSize` is `9 + 8 * count`. The two versions agree only at count 0, which is every 0x7C message
either side sends, so version 9's parser reads 221887 version-4 messages without a field out of
place.

The receive path (`0x01859338`) refuses five things in silence:

    0x0185952c   payload size <= 0x57F - 8 * count     tighter than the deserialiser's own bound
    0x0185954c   the Pia message length equals 9 + 8 * count + size exactly
    0x0185956c   the stream id is the window's own for this station, [w + 0x18*st + 0x46]
    0x01859578   a count above 0 is a list the receiver must find itself in; count 0 is unfiltered
    0x01859ca0   the first message on a stream carries FLAG_IS_INITIALIZED

It dispatches on the flags at `0x01859734`: bit 5 RESET, bit 6 RESET_ACK, bit 0 APPLICATION_DATA;
anything else, including no flags, goes to the ack handler `0x01859a70`.

While the per-station byte `[window + 0x18*station + 0x47]` is zero the stream does not exist; the
first data message must carry FLAG_IS_INITIALIZED and sets the stream id (`+0x46`) and starting
sequence (`+0x40`). A console sends flags 0x0F on its first message and 0x07 after.
`reliable4.build_data_message(bytes.fromhex("610000000a00"))` reproduces a console's sequence 1 byte
for byte: `0f0000060001000100610000000a00`.

The ack payload is exactly 0x260 bytes, the wiki's original "Ack Data" that 5.29 replaced with a
counted list:

    5.29-5.43   1 unknown byte, 1 count, then `count` x 21 bytes
                    u8 stream id, u16be ack id, u16be the window's field 0x50, 16-byte mask
    version 4   32 entries of 19 bytes, always
                    u8 stream id, u16be ack id, 16-byte mask

The handler `0x01859a84` opens `ldrh w8, [x2, #0xa]; cmp w8, #0x260; b.ne` and answers 0x2c03
without reading the body; the serialiser `0x0185bfb0` loops 0x20 times writing a stream id, a
big-endian ack id and sixteen mask bytes as two big-endian u64 halves. The slot read is a station
index taken from the handler's fourth argument, whose station the site does not say; the slot's
stream id must match the window's (`0x01859c1c`). `reliable4.build_ack_payload` fills every slot with
the same entry, correct under either reading.

A Shield leaves the slots it does not use holding stale bytes under stream id 0 (`22284`, `16`,
`57080`, `2517` in slots 1, 2, 4, 5 while slot 0 held 2). Read only the entry for the acked stream:
the maximum over all slots is a stale value, and a sender following it overruns the console's
window (401 messages sent against a window at 97), which then stops acking.

Growing sequence ids over a fixed `lowest_pending` mean a growing backlog; measure `lowest_pending`
per message and retransmits per sequence id.

## Protocol 0x80, the broadcast reliable window

`nn::pia::transport::BroadcastReliableProtocol` (vfunc4 `0x0184d880` returns 0x80), a different
class from 0x84's `ReliableBroadcastProtocol`. Its messages are compressed (version-4 flag 0x10):
42 bytes raw, 625 decompressed, the reliable header with destination count 1 and one eight-byte
station constant id over the 0x260 ack payload (version 9's bitmap rule would give 621). The ack has
one slot per station the mesh can hold, by station index: a console fills 0..7 with the real ack id
and leaves 8..31 zero, 8 being `max_total` from the join response.

## Protocol 0x81, the stream broadcast reliable transfer (Pia 6)

`StreamBroadcastReliableProtocol` moves one fixed-size block from a station to every station that
asked for it, in chunks (Scarlet 4.0.0 `main`). Slot 10 is its update `0x6f5360`, slot 11
`0x6f51a8`, slot 17 `0x6e6818`, slot 19 BroadcastReliableProtocol's `0x6e69a0`, which loads the
window from `[proto+0x70]` and runs the `ReliableSlidingWindow` send loop `0x6f0638` (`bl` at
`0x6e69c0`) with byte budget `[proto+0x64]`; the loop takes each slot's next time from the retransmit
deadline `0x6f0d14` (`bl` at `0x6f073c`). Chunks are enqueued through `0x6f1994` (`0x6f5c2c`,
`x0 = [proto+0x70]`), which stamps the slot with now (`0x6f1bd4`). A 0x81 transfer retransmits on
the same deadline as 0x7C and 0x80, and never with no RTT sample for any destination.

Each message carries an eleven-byte StreamData header, written by `0x6f60e8`:

    +0  1  kind: 0 a receive posted, 1 the first chunk, 2 a later chunk, 3 to 6 control
    +1  1  transfer id
    +2  1  percent of the block delivered after this chunk
    +3  4  big-endian u32: the receive capacity in a kind 0, zero in a chunk
    +7  4  big-endian u32: the length of the data that follows
    +11    the data

The game's send API takes a buffer, a size and a transfer id; its receive API a sender, a buffer, a
capacity and an id, and a posted receive sends a kind 0 carrying the capacity. A send is refused for
a size above `[proto+0xa0]`, id 0xff, or no station's `[proto+0x98]` byte equal to the id. The chunk
loop (`0x6f5b54`..`0x6f5c58`, in `0x6f5560`) enqueues while `0x6f1ef8` finds a free slot: chunks of
`[window+0x70] - 11` bytes, kind `(offset != 0) + 1` (`0x6f5bb0`..`0x6f5bbc`), id from `+0xa4`,
percent `(offset + chunk) * 100 / size` (`0x6f5b78`..`0x6f5b98`), also kept at `+0xba`.

The receive loop `0x6f5cdc`, called from the update after `0x6f5560`, pulls each message with
BroadcastReliableProtocol vfunc13 (`0x6e644c`, sender at `sp+0xb80`), decodes the header with
StreamData vfunc3 (`0x6f635c`), resolves the sender's index with `0xe42ddc` and switches on the kind
through the byte table at `0x3c0d5e5`, ignoring kinds above 6:

| kind | target | what the receiver does |
|---|---|---|
| 0, receive posted | `0x6f5e5c` | in its own state 1, 2, 4, 5, 8, 9 or 10 (mask 0x736), flags the sender in `[+0xc0]`; otherwise (`0x6f6094`) `[+0x98][sender] = id` and `[+0xa0] = min([+0xa0], capacity)` |
| 1, first chunk | `0x6f5e90` | clears the received count `+0xac` and `+0xba`, state 4 to 5, then as kind 2 |
| 2, chunk | `0x6f5eb4` | in state 5 only, for id `+0xa5` from sender `+0xb0`: copies the data to `[+0x88] + [+0xac]` if it fits `+0x90`, adds its length, keeps the percent at `+0xba` |
| 3, busy sender refuses a receive | `0x6f5f2c` | in state 4 only: resets the transfer, every `[+0x98]` to 0xff, state 7 |
| 4, sender cancels | `0x6f5f9c` | resets the transfer, every `[+0x98]` to 0xff, state 0xC |
| 5, receiver cancels | `0x6f6000` | `[+0x98][sender] = 0xff`, flags the sender in `[+0xc8]` |
| 6, sender acks the cancel | `0x6f6024` | in state 0xA only: resets, state 0xB |

Control kinds carry id 0xff. The update `0x6f5560` sends kind 3 to stations flagged in `[+0xc0]`
(`0x6f6268` with `w2 = 3`, `0x6f5750`), kind 6 to those flagged in `[+0xc8]` (`0x6f57d8`), in state
9 kind 5 to the expected sender `[+0xb0]` (`0x6f5904`, unicast through `0x6f1de8`) then state 0xA,
and in state 8 kind 4 to its destinations (`0x6f5984`). The smallest capacity posted bounds the block
the send API accepts.

The state at `+0x78` (`0x6f53b0`): a receive goes from 5 to 6 when `+0xba` reaches 0x64
(`0x6f5460`); a send from 2 to 3 when an entry of `[+0x98]` equals `+0xa4` and the window reports
sequence `+0xb8` acknowledged (`0x6e7128`, `0x6f54e4`), and to 0xC with no matching entry.

## Protocol 0x84, the reliable broadcast transfer

`nn::pia::transport::ReliableBroadcastProtocol` carries Sword/Shield's trade snapshot:

| kind | meaning |
|---|---|
| 0x11 / 0x12 | a data fragment; a counter at [4] and a capacity at [10] |
| 0x19 | the transfer is complete |
| 0x21 | an ack carrying a contiguous base and a bitmask of what arrived early |
| 0x28 | the answer to 0x19 |

A receiver that never answers never sees the last three, and the sender keeps retransmitting (no
limit measured).
`pokeldn/ldn/broadcast4.py`. A console sends its own transfer on port 0 and acks the peer's on port
1.

## Unresolved

- Whether a retail Sword reads a version-4 connection response sent without the type-5 ack of its
  request. One did; an emulated Shield 1.3.2 did not.

## Credits

The header version table, the session-key derivations and the nonce layouts come from the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol) (its
`Pokemon-Brilliant-Diamond.md` states the game-key derivation; `Pia-Game-Keys` lists only derived
keys; searching it is on [Reverse-engineering a Switch title](switch_re.md)). Which derivation
belongs to which network type, the `cryptoKeyDataSeed` value and the version rule were read out of
retail titles' own code.

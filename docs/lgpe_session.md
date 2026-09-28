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
compressed), `rtld`, `sdk`, `subsdk0` and `subsdk1`. Every `nn::pia` and `gflnet3` reference is in
`main`; the three sdk modules carry none.

    ./.venv/bin/python tools/switch/xci_read.py "<the .nsp>" --keys prod.keys \
        --nca 2b7730a9e56498bbafac2002d4908c6b --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main main.bin
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0xd32ba8

Pia is statically linked: 269 `nn::pia` classes and 2112 named virtual methods. The `nn::pia::local`
namespace carries both the `Ldn*` and the `Local*` class families (`LdnCreateNetworkJob`,
`LdnCreateSessionSetting`, `LdnJoinSessionSetting`, `LocalProtocol`). `nn::ldn` is imported from
nnSdk: `CreateNetwork`, `Connect`, `Scan`, `SetAdvertiseData`, `GetSecurityParameter` and the
`*Private` variants all have GOT slots at `0x15fa1e0..0x15fa2a8`.

Above Pia the game uses protocol buffers through `gflnet3`: the build paths name
`lib/gflnet3/external/include/google/protobuf/`.

## The LDN passphrase

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL

64 bytes at `0xf73a50`, used raw, byte for byte the passphrase Sword and Shield use. Two call sites
hand it to Pia with a literal length of `0x40`: the create-session setting at `0x4db6c8` and the
join-session setting at `0x4dbbbc`.

    0x004db6b4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004db6c4  mov  w2, #0x40
    0x004db6c8  bl   #0x5c0fb0              LdnCreateSessionSetting passphrase setter

    0x004dbba4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004dbbb0  mov  w2, #0x40
    0x004dbbbc  bl   #0x5c1280              LdnJoinSessionSetting passphrase setter

`nn::pia::local::LdnCreateNetworkJob` keeps the passphrase at +0xC4 and its length at +0x104, and
builds the `nn::ldn::SecurityConfig` from them before `nn::ldn::CreateNetwork` (`0x5ce988`, through
the PLT stub at `0xd31c78`). The job's constructor is `0x5ce640`; the same offsets Sword's job uses.

## The Pia game key

    p1frXqxmeCZWFv0X

Sixteen ASCII bytes at `0xefd659`, the key the wiki lists for Sword/Shield, Legends: Arceus and
Scarlet/Violet. One call site, `0x11a374`, loads it with a single `ldp` and stores it into a crypto
setting with an enabled flag, conditional on a mode field:

    0x0011a364  ldr  w9, [x19, #0x98]
    0x0011a368  orr  w9, w9, #2 ; cmp w9, #2 ; b.ne   (mode 0 or 2 takes the key)
    0x0011a374  adrp x9, #0xefd000 ; add x9, x9, #0x659
    0x0011a380  ldp  x10, x9, [x9]
    0x0011a384  stp  x10, x9, [x8]          x8 = setting + 0x24c

No version substitution: the key is the literal.

## The Pia header

Version 3, which the NintendoClients wiki places at Pia 5.11-5.17. The header initializer at
`0xd122d4` writes magic and version as one 64-bit store, `0x00000003_32AB9864`; the validator at
`0xd12400` checks the magic and `(byte & 0x7f) == 3`.

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 3
    0x05  1  connection id
    0x06  2  packet id
    0x08  8  AES-GCM nonce
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext

The layout is the wiki's 5.11-5.21 table, the one Sword's version 4 uses; only the version byte
differs. `pokeldn/ldn/pia4.py` implements it.

## The message framing

Pia 5.11-5.12: a fixed 22-byte message header; 5.18 and later use a presence-flagged one.
`nn::pia::transport::ProtocolMessageAccessor::Header`'s deserializer at `0x5ae870` refuses fewer
than `0x16` bytes and copies field by field; the writer at `0x5aeb00` stores a literal 1 at byte 1.

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

`LocalProtocol`'s derivation at `0x5cd560` is the one BDSP and Sword use: seed a SEAD xorshift128
from one 32-bit value (`0x57cfc0`, the recurrence around `0x6C078965`), take four draws into sixteen
bytes, AES-128-ECB them under the game key kept at `LocalProtocol+0x49c` (enabled flag at +0x498).
`pokeldn.ldn.pia5.ldn_session_key` implements it.

The advertisement's application data for Pia 5.9-5.18 opens with a 24-byte header:

    0x00  4  network id, random per session
    0x04  4  CRC32 of the user password
    0x08  1  system communication version, 4 for 5.11-5.17
    0x09  1  header size, 0x18
    0x0A  2  padding
    0x0C  4  session param
    0x10  8  zero
    0x18     the game's application data

The seed is the session param at application-data +0x0C. A Let's Go Pikachu host broadcast 392
datagrams while a seat was held in its session; every one authenticated under
`ldn_session_key(game key, session param)` with the version-3 header and the pia4 IV (three bytes of
`crc32(network id little-endian || the host MAC)`, a source-id byte of 0, the eight-byte header
nonce). Header version 3, tag sixteen bytes, not truncated.

## The link code

The link code reaches the advertisement as the NetworkInfo scene id; the password CRC32 at
application-data +4 stays 0 and the SSID stays `01000000000000000000000000000000`.

The scene id is the three picks as decimal digits followed by a 1: `1000a + 100b + 10c + 1`, each
pick its index in the picker (Pikachu 0, Eevee 1, Bulbasaur 2, Charmander 3, Squirtle 4, Pidgey 5,
Caterpie 6, Rattata 7, Jigglypuff 8, Diglett 9).

The game builds it at runtime, so 0x925 is no immediate in `main` (Let's Go Pikachu 1.0.2):
`0x891580` folds the three pick bytes into `100a + 10b + c`, `0x978080` computes `10 * number +
mode` with mode 1 for a trade (modes 2 and 3 come from the switch at `0x9765f4`; which features
they are is unread), and the value travels through `0x349010` and `0x4da710` to the session
constructor `0x4db1e0`, which stores it as a `u16` at `+0x302`. `0x4db6ac` puts it into
`LdnCreateSessionSetting` at `+0x60`, and Pia copies it into `NetworkConfig.intentId.sceneId`
before `nn::ldn::CreateNetwork` (`0x5ce988`).

The same constructor picks the channel of the network a searching console hosts:
`{1, 6, 11}[scene % 3]`, the table at `0xf73a44`, indexed at `0x4db248`..`0x4db254`.
`pokeldn.lgpe.search_channel(code)` computes it.

| code a console searched with | scene id advertised | channel |
|---|---|---|
| Pikachu, Pikachu, Pikachu | 1 | 6 |
| Bulbasaur, Charmander, Squirtle | 2341 | 6 |
| Bulbasaur, Charmander, Bulbasaur | 2321 | 11 |
| Eevee, Pikachu, Diglett | 1091 | 11 |
| Pikachu, Pikachu, Bulbasaur | 21 | 1 |

A searching console hosts its own network and joins another only when that network advertises its
scene id on its own channel. Under Bulbasaur, Charmander, Bulbasaur it ignored `bin/lgpe_host.py`
advertising scene id 1 or 2321 on channel 6 while its own network was on channel 11, and joined at
once on channel 11 with 2321, then traded.
`bin/lgpe_host.py --code NAMES` hosts on the channel the code gives (`--channel auto` scans for
the console's network instead); a retail Let's Go Pikachu and a Let's Go Eevee joined it on
channel 1 under Pikachu, Pikachu, Bulbasaur, and the Eevee traded.

The host side checks no code on a joiner: a console hosting under Bulbasaur, Charmander, Squirtle
traded with `bin/lgpe_join.py`, which sends none.

## The Local Protocol, measured

The console broadcasts its session state on Pia protocol 0x24 (Local Protocol, 36), port 0, the same
protocol BDSP and Sword carry it on. The message is the wiki's 5.7-5.45 update-session message, and
`pokeldn.ldn.local_protocol.parse_update_session` reads it without change: a 12-byte local header
(version 1, type 0x11), a sequence id, the random local network id, the host variable id, service
variable id and constant id, an allow-participating byte, and a list of eight local nodes, each an
IPv4 address, a port and a host-migration ranking. The held session read back host
`169.254.105.1` ranking 0 and the joiner `169.254.105.2` ranking 1, the rest empty at ranking 255.

The host constant id in the Local Protocol body is `000048f120229beb`, little-endian, which is
`station_protocol.ldn_constant_id` over the host MAC `48:f1:eb:20:9b:22`. The same id rides the Pia
message header as the big-endian source `eb9b2220f1480000`. The two fields carry the same value in
opposite byte orders, as they do on Sword.

## The station protocol, for a mesh join

Reaching the game means joining the mesh: a connection request on protocol 0x14, then a mesh join on
protocol 0x18. The connection-request handler at `0x5b8800` reads the wiki's 5.10-5.18 layout,
station-protocol version number 9:

    [0]     message type            1
    [1]     connection id
    [2]     version number          must be 9 (`cmp w8, #9` at 0x5b8848; 5.27-5.45 checks a platform)
    [3]     is inverse connection request; rejected above 1
    [4]     target constant id      big-endian u64, compared against the console's own at 0x5b6830
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1 (0x5b6840)
    [0x10]  inverse connection id   compared against the station's own record at +0xA0
    [0x11]  station location        the 5.11-5.45 layout, unchanged from Sword
    [...]   ack id                  u32, the message size minus four

This is neither Sword's version-4 request (a platform byte at [2], a shift flag at [3]) nor the
repo's 5.29-5.45 module (a protocol list at [1]). It is the classic station protocol with a version
byte, so a version-4 or a 5.29 request sent here lands every field in the wrong place. The target
constant id is the console's own, derived from its MAC; the joiner's own location carries the
joiner's constant id, variable id and service variable id.

The handshake, measured on a retail Let's Go Pikachu, completes the full version-9 sequence (the
inverse connection request the 5.27 simplification later removed):

    ->  the joiner's connection request (type 1, is_inverse 0, target the host constant id, its location)
    <-  the host's type-5 ack, then its inverse connection request (type 1, is_inverse 1),
        addressed to the joiner's constant id and the variable id it sent, carrying its own location and a
        trailing ack id
    ->  the joiner's type-5 ack of that ack id, then its connection response (type 2, result 0, the host's
        constant id at [5] and variable id at [0xD], gate byte 1 at [0x37], padded to 0x38)
    <-  the host's connection response (type 2, result 0, 840 bytes, platform 4, carrying the joiner's
        ids, a network id and one player info), repeated until acknowledged
    ->  the joiner's type-5 ack of that response

The connection-response parser at `0x5b9270` reads `[1]` the result, `[5]` a big-endian u64 against
its own constant id, `[0xD]` a big-endian u32 against its own variable id, and `[0x37]` a gate byte
the result-0 path drops when 5 or more. `station9.build_connection_response` writes exactly those.

### The connection response a station sends

A Let's Go station answers a connection request with 0x348 bytes, where the station protocol accepts
0x3C. The body carries the network the station joined and who is playing:

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

A retail Let's Go Pikachu sends the same layout with its own profile name. The PlayerInfo is the
same 195-byte structure `station_protocol.player_info` builds.

A Let's Go joiner's station location, in the connection request, leaves the public address empty
(two bytes, a port of zero) and sends zero for the NAT flags and the NAT location, which makes it
36 bytes rather than 40. `station_location(..., public=False, nat_flags=0, nat_location=0)`.
`station9.build_connection_response(..., network_id=N, player_name=B)` builds it, and
`bin/lgpe_join.py --player-name NAME` sends it (`--short-response` sends the 0x3C body instead).

## Joining the mesh

With the station connected, a mesh join request on protocol 0x18 (`mesh_protocol.build_join_request`,
type 1, local station index 253, a trailing ack id) draws the host's join response: type 2, 148
bytes, two stations, host index 0, joining index 1, one fragment, two station infos, max active 2,
max total 8, carrying both stations' locations. The host then broadcasts an update mesh (type 0x20,
524 bytes, update counter 1). The join response is acknowledged with a type-5 ack on protocol 0x14,
not with a mesh message (`mesh_protocol.ack_for`). The joiner is then station index 1 in the mesh.

Once in the mesh the host streams its Local Protocol update-session (0x24, acked with a 0x21), RTT
requests (0x58), the Sync Clock Protocol (0x1C) and the Pia Clone Protocol (0x73). A real joiner
answers every one of them and sends its own RTT and sync clock requests from the moment it is
seated.

## The RTT Protocol (0x58), version 3

Sixteen bytes, as Sword's, with the kind a big-endian u32 at [0] where Sword has a byte, and the
timestamp is the sender's own system tick at 19.2 MHz in a u64 at [8]. A response copies the
timestamp and sets the kind to 1. Each station sends its own requests about once a second and
answers the other's.

    00000000 00000000 0000000049845557     request
    00000001 00000000 0000000049845557     the answer to it

`rtt_protocol.build_v3` and `response_for_v3`; `bin/lgpe_join.py --connect` runs both directions
(`--no-rtt` turns them off).

## The Sync Clock Protocol (0x1C)

The mesh carries a monotonic clock the host controls, and every station keeps its own estimate of
it (wiki Sync-Clock-Protocol). A station sends a request every two seconds and the host replies;
the station halves the round trip and adds it to the value it was given.

    request, 16 bytes   [0] u64 the sender's system tick (19.2 MHz), [8] u64 zero
    reply,   16 bytes   [0] u64 the tick copied back, [8] u64 the mesh clock in milliseconds

A joiner sends its first request 46 ms after the mesh join response; 436 of these carried a
seven-minute session between two Let's Go endpoints. The clocks in the Clone Protocol's messages
are this clock: a Let's Go host that receives clone messages timed against a station's own uptime
releases the clone and leaves. `pokeldn.ldn.sync_clock`, and
`bin/lgpe_join.py --connect` runs it from the mesh join (`--no-sync-clock` turns it off).

The keep-alive protocol is 0x08, a message with no body; each side answers one in kind.

## The Reliable Protocol (0x7C), where the game's data is

The game's own messages ride on protocol 0x7C. Pia 5.11's header is 24 bytes, where 5.29-5.43 have
9 or 13, and its sequence ids are 32 bits starting at 0xFFFFF82F on both stations.

    0x00  1  flags
    0x01  1  stream id, 3 for the game's stream and 0 on an acknowledgement
    0x02  2  payload size, big-endian
    0x04  4  zero
    0x08  4  sequence id, big-endian
    0x0C  4  the next sequence id expected from the peer, big-endian
    0x10  8  zero
    0x18     the payload

An acknowledgement is the header alone with the stream and the size zero. `pokeldn.ldn.reliable3`.

The payload is framed by the game: a 16-byte header of channel id, body length, step, tag and
destination station, then the body ("The game's messages on the reliable protocol" below). The kind 1 body carries the two
stations' names in the clear; the kind 2 and kind 4 bodies are encrypted box structures. A retail
console acknowledges a kind 1 message replayed from another session on the reliable window and sends
no message of its own.

## The Clone Protocol (0x73)

Protocol 0x73 is `nn::pia::clone::CloneProtocol` (GetProtocolId at `0x158aab8` returns 0x73; the
SDK string in `main` is `PiaCommon-5_11_4`). The game's partner sync runs on it. The message type
byte is `0xAB`: the high nibble the structure, the low nibble a variant. Every message starts with
the version byte 3, the type byte, and the sender's frame counter as a big-endian u16 (about 60 per
second, starting when the sender's Pia session started).

The exchange below is measured between two Let's Go Pikachu 1.0.2 endpoints (a Ryujinx host and a
Ryujinx joiner over ldn_mitm, link code Pikachu x3, one trade completed). Both sides run the same
state machine; nothing is host-only.

### Clock sync, the first two seconds

Both sides send clock requests (type 0x11, 18 bytes) at about 5 per second, and each side answers
the other's with a clock reply (type 0x21, 22 bytes). Serializers `0x51f9b0` and `0x51fab0`.

    clock request                              clock reply
    [0]   1  version 3                         [0]   1  version 3
    [1]   1  type 0x11                         [1]   1  type 0x21
    [2]   2  sender frame counter              [2]   2  sender frame counter
    [4]   4  sender message count              [4]   4  sender message count
    [8]   2  destination station bitmap       [8]   2  destination station bitmap
    [0xA] 8  sender system tick                [0xA] 4  sender clone clock, ms
                                               [0xE] 8  the request's system tick, echoed

- The message count is one counter per sender over its clock requests, replies and participate
  messages, starting at 1. Requests and replies alternate, so it runs 1, 2, 3 on each side.
- The station bitmap is the destination, `1 << station index`: the host (index 0) sends 0x0002 to
  the joiner (index 1), the joiner sends 0x0001 back. A reply is addressed to the requester.
- The system tick is `os::GetSystemTick`, 19.2 MHz, the sender's own. The reply echoes the
  request's tick unchanged; nothing else in the request is echoed.
- The clone clock is milliseconds since the sender's clone protocol started (element +0x14 in the
  reply serializer), about 60 ms before its first request.

A reply that copies the request's counter, count and bitmap, with the clock field zero, leaves the
retail console requesting; a peer fills the clock.

### Participate

After ten of its own requests were answered (2.1 s), the joiner sent a participate (type 0x31,
10 bytes, serializer `0x51fbd0`): header, its message count, then the destination bitmap 0x0003,
every station. The host answered within 30 ms with type 0x33, same layout, bitmap 0x0002. The host
sent its own participate 1.1 s later (bitmap 0x0003) and the joiner acknowledged with 0x33 carrying
0x0001.
From the first participate onward each side's clock replies are type 0x22 instead of 0x21, same
layout.

### Clone elements

A clone is keyed by three fields every command message carries: a clone type (1 to 4), the owning
station (0xFD for one no single station owns) and a 32-bit clone id. Both stations publish their
own copy of a clone; the host creates ids 1, 2, 3 for the trade as the screens advance, and clone
type 3 id 0 exists from the moment both sides have participated.

    every command message   [0] version 3, [1] type, [2] u16 the sender's frame counter,
                            [4] u8 clone type, [5] u8 owning station, [6] u16 0,
                            [8] u32 clone id
    types 0x81 to 0xc4      [0xC] u32 the sender's message count, [0x10] u16 destination bitmap,
                            then the structure's own fields
    types 0xd1 to 0xf4      [0xC] the data, with no message count and no bitmap

The structure is the type's high nibble and the command the low nibble, in the order the command
tokens report themselves (`SendClone::AnnounceCommandToken::vfunc0` at `0x522480` returns 0,
`ReceiveClone::RequestCommandToken` 1 at `0x520df0`, `SendClone::EndCommandToken` 2 at `0x522490`,
`AtomicSharingClone::LockCommandToken` 3 at `0x517820`): command = the low nibble minus one.

    0x81 announce   0x82 request   0x83 end   0x84 lock
    0x9N  + a u32 clock in ms at [0x12]                       ClockCloneCommandMessage, 22 bytes
    0xaN  + the clock, a u8 count at [0x16], a u8 and a u16   ClockAndCount, 26 bytes
    0xbN  + the clock and a u32 participant bitmap at [0x16]  ClockAndParticipant, 26 bytes
    0xcN  + the clock, the count and the bitmap at [0x1A]     ClockAndCountAndParticipant, 30
    0xeN  + a zlib stream at [0xD]                            the clone's state, acknowledging
    0xfN  + one byte at [0xD] and a zlib stream at [0xE]      the clone's state, with its data

The zlib streams inflate to a record that starts with the tag 0x20 and its own plaintext length,
then a u16 clone id and a byte that is 1 while the copy is empty and 3 once it is full:

    0x20 0x06 u16 clone id  0x01  0x00
                                          a copy with nothing in it yet
    0x20 len  u16 clone id  0x03  u8 the station the data belongs to  u16 0
              u16 participant bitmap  u32 clock  then the clone's data
    0x20 0x0A u16 clone id  0x05  u8 the station being acknowledged   u32 clock

A station publishes the six-byte form first and the filled one after it. The six-byte form is a
publish being retried: a settled session builds no clone records at all.

The deflate is one compress, a sync flush and a final empty block, at a level between 2 and 5:
every captured stream is reproduced byte for byte by `clone.pack_record`. The 0xfN header's two
bytes at [0xC] carry the record's participant bitmap and the 0xeN header's one byte the station
it acknowledges.

A host announces the clone it owns with an 0xa1 and an 0xb1 carrying the participant bitmap, and
the other station answers with an 0xa2 and an 0xc1 before the data is published. An 0xa2 carries
the mesh clock and the count byte, 1 on clone type 4 and 0 on clone type 2.

A station announces a clone with 0xa1 and the other answers 0x91; the owner then sends its data in
an 0xf3 and the other acknowledges with an 0xe3 carrying the same clock. 0x83 releases a clone and
0x84 acknowledges the release. Type 0x32 asks the other station to leave the clone session and
0x41 is its 14-byte acknowledgement, carrying the answering station's own bitmap at [0xA]; a host
whose 0x32 is never answered repeats it until the game gives up.

`ClockAndCountCloneCommandMessage` (vtable `0x158ac58`, serializer `0x51f4c0`, deserializer
`0x51d2b0`, size 0x1a) writes object `+0x1c` as the clock at [0x12], `+0x20` as the count at
[0x16], the byte at `+0x21` at [0x17] and the halfword at `+0x22` at [0x18], big-endian. The count
is the clone's vfunc 16 (`vtable+0x80`): 0 for a SendClone (`0x519290`), the byte at `+0x112` for a
ReceiveClone (`0x520de0`), the byte at `+0x188` for an AtomicSharingClone (`0x517800`).

No builder writes the byte and the halfword after the count. The 0xa2 builders in
`0x51c110..0x51cf6c` build the message on the stack and store nothing past the count, so an 0xa2
carries what the stack held: `01 000002` two milliseconds into an emulator's clone session, 0xd858
in the halfword on a console fifty-five seconds into one. The sweeper `0x51b380` reuses one buffer
at `sp+0x28` for every clone it announces, and its 0xbN path stores a u32 at `sp+0x48` (`0x51b7a0`),
so an 0xa1 built after an 0xb1 on clone type 3 in the same sweep carries bytes 1 to 3 of that
participant word, and otherwise earlier residue. Two stations whose call paths leave the same
bytes send the same value (`01 2808ab` on clone type 4 id 1 from both); clone type 3 id 0 differs.
No code reads wire bytes `0x17..0x19` of a received 0xa1 or 0xa2, so a sender may put any value
there. The receive `0x51c110` parses the buffer in place and builds no message object for either:
the class's vtable is referenced only by the four builders (`0x51b3b0`, `0x51cb64`, `0x51ccf0`,
`0x51cd8c`), and its deserializer `0x51d2b0` is reached only from its vtable slot `0x158ac70` and
from `0x51d41c` inside another class's deserializer (`0x51d3e0`, slot `0x158ad10`), neither called by
`0x51c110`. Every payload reaches `0x51c110` from the receive loop `0x51ad90` (`0x51aef4`, after the
protocol's vfunc `+0xc8` at `0x51ae0c`) or from the loopback of the station's own messages
(`0x51e330`, `0x51e4c4`).

`0x51c110` reads the common header (`0x51c2c0`: `[8]`, `[4]`, `[5]`), then for the groups 0x80..0xc0
bytes 0x10 and 0x11 only (`0x51ce80`, table `0xf76e08` -> `0x51ced0`), then the structure's own
fields by the high nibble (table `0xf769c4`):

| group | case | length | reads |
|---|---|---|---|
| 0x80 | `0x51c614` | 0x12 | nothing |
| 0x90 | `0x51c62c` | 0x16 | the clock `[0x12..0x15]` |
| 0xa0 | `0x51c64c` | 0x1a | the clock (`ldur w9,[x22,#0x12]`), the count `[0x16]` (`ldrb w3,[x22,#0x16]`) |
| 0xb0 | `0x51c66c` | 0x1a | the clock and a u32 `[0x16..0x19]` (`0x51c680`) |
| 0xc0 | `0x51c68c` | 0x1e | the clock, the count `[0x16]`, a u32 `[0x1a..0x1d]` |

The clone-type table `0xf769e4` (index `[4] - 1`) then routes 0xa1 and 0xa2, each handler taking the
clone, the station and the clock and none the buffer:

| clone type | 0xa1 | 0xa2 |
|---|---|---|
| 1 | `0x51c714` -> `0x51cb38`, `0x522350(clone, station, clock)`; an unknown clone draws a 0x91 | ignored |
| 2 | ignored (`0x51c3b8`) | `0x51cafc`, `[5]` must be the local station, `0x520ce0(clone, clock)` |
| 3 | `0x51c934` -> `0x51cc00`, `0x522a60` | `0x51c838`, `0x522b20(clone, station, clock)` |
| 4 | `0x51c8c0` -> `0x51cbc4`, `0x522a60` | `0x51c838` |

The only onward calls carrying the buffer, `0x51c268`, `0x51c2fc`, `0x51c32c` and `0x51c784`
(`mov x3,x22; b 0x51d450`), are reached from other message types.

`0x522a60`, the 0xa1 handler of clone types 3 and 4 (called from `0x51cbd0` and `0x51cc0c`), returns
1 when the element's state `[x0+0x38]` is not 1, 2 when the sender's station bit is set in the mask
`[[x0+0x30]+0xc0]`, and otherwise records the station and returns 0 (`0x522a70..0x522b10`). The
caller answers 0 with an 0xa2 of type `0xfd04` (`0x51cbd8 cbz w22,0x51cce0`, `0x51cd00`), 1 with an
0x91 (`0x51cbe4..0x51cbf8`), and 2 with nothing (`0x51cbe0 b.ne 0x51c3b8`); clone type 3
(`0x51cc00..0x51cc34`, type `0xfd03`) has the same three outcomes. `0x51c110` also drops a message
silently before that handler: at the destination check `0x51ce80` (`0x51c170`), at the per-sender
count filter (`0x51c1e0..0x51c1f0`: dropped when the count stored at `proto+0x714+4*station` is at
least the message's `[0xC]`), and at its length and type range checks. An 0xa1 for an unknown clone
draws an 0x91 without reaching `0x522a60` (`0x51c494`, `0x51c8c0`).

The mask at `+0xc0` belongs to the clone protocol object, beside its station mask `+0x38` and its
state word `+0x40`:

| event | effect on `+0xc0` | address |
|---|---|---|
| the state becomes `0x22` (when `[[proto+0x48]+0x24]` is 2 to 4) | the whole station mask `+0x38` copied in | `0x51b060..0x51b06c` |
| the state becomes `0x42` | the same copy | `0x51b140..0x51b150` |
| a station joins in state `0x22` or `0x31` | its bit set | `0x51bc64..0x51bc88` |
| a 10-byte 0x33 (the participate acknowledgement) in state `0x31` or `0x22` | the sender's bit cleared | `0x51c354..0x51c3b4` |
| a 14-byte 0x41 whose bytes `[0xa..0xd]` equal `[proto+0x3c]`, in state `0x42` | the sender's bit cleared | `0x51c380..0x51c3b4` |
| a station leaves | its bit cleared | `0x51bce0..0x51bce8` |
| a station leaves in state `0x42` | the whole mask re-copied from `+0x38` | `0x51bd04..0x51bd18` |
| other paths | zeroed | `0x519a1c`, `0x519ccc`, `0x51a2d4`, `0x51a7d0`, `0x51a9c0` |

In state `0x22` the protocol waits for the mask to empty before it moves to `0x31`
(`0x51b074..0x51b084`).

The full decode of a real session is `scratchpad/037_clone_parsed.txt`, its data messages
`scratchpad/lgpe_clone_data.py`. The decoders: `scratchpad/lgpe_pcap_decode.py` for an ldn_mitm
pcap, `scratchpad/lgpe_jsonl_clone.py` for a `--capture` log.

### The game's messages on the reliable protocol

The trade's own traffic is protocol `0x7c`, `reliable3`, sequences starting at `0xFFFFF82F`. Every
message is a 16-byte header and a body of the stated length:

```
+0x00  4  kind: the channel id, 1 to 4 in one trade
+0x04  4  body length: 0x168 for kind 1, 0xe8 for kinds 2 and 4, 4 for kind 3
+0x08  4  step, counting every message a station sends from 1
+0x0c  1  tag, 0 on every trade message
+0x0d  1  destination station index, 0xff for every station
+0x0e  2  zero
+0x10     the body
```

`0x116f30(mgr, kind, buf, len, tag, dest)` builds the header at `mgr+0x288`, the step being
`mgr+0x274` plus one. Every trade sender goes through `0x4d94e0`, which passes tag 0 and destination
0xff: `0x34945c` (kind 1), `0x34a24c` (the offer), `0x838300` and `0x83838c` (the commit).
`0x4d9520` passes both from its caller; its callers all sit in `0x9dce94..0x9dede8`, the battle
scene's senders ("The battle scene's channel" below), and one of them sends tag 3.

The receive `0x1171d0` takes the first queued message, across all stations, whose step is its
station's next (`mgr+0x278[station] + 1`, `0x117334..0x117354`), and bumps that counter for every
message it takes or drops. It drops, counted and erased (`0x11722c`), a message whose destination is
neither 0xff nor the local station index at `mgr+0x1288` (0xfd before a session, set at
`0x116a3c`), and a message whose kind is no registered channel (the 16-entry table at `mgr+0x110`,
`0x117398..0x1173f8`), whichever receiver is polling. A message of another registered kind, or with
a tag other than the one asked for, makes the receive return 0 with the message left queued, and
every message behind it, from any station, waits. The tag is compared only when the caller passes no
tag pointer (`0x11746c..0x117478`); every trade receiver calls `0x4d9570` with none and asks for
tag 0, so a trade message carries tag 0.

The kind is a channel id. `0x116e80` hands out ids from a per-session counter at `mgr+0x270`,
starting at 1, incremented on every registration (`0x116ea4..0x116eac`) and zeroed with the step
counter only at session start (`0x116a10`); its one caller, `0x4d9494` in `0x4d9450`, stores the id
at `chan+0x60`, and the channel's sends (`0x4d94e0`, `0x4d9520`) pass `[chan+0x60]` to `0x116f30`,
which writes it as the header's kind at `mgr+0x288` (`0x116fa4`). A registration while the table
holds 16 channels (`mgr+0x118 > 0xf`, `0x116e94`) gets id 0. `0x117920`, called only from the
receive path (`0x11761c`), compacts out every entry of the `+0xd0` table whose channel's live count
`+0x54` is zero, so a destroyed channel does not hold its slot.

`0x4d9450` has exactly five callers: the trade session object (`0x3492f8`), the party-offer object
(`0x349d88`), the sync save's state 2 (`0x8382a8`), the `0x347e10` class (`0x3481fc`) and the battle
scene (`0x9dce1c`). In a trade the first three register 1, 2 and 3 in every captured trade, and the
party-offer object the post-trade save re-creates registers 4. Every registration also announces a
clone set: `0x4d9450` ends with `0x11b4c0(chan+0x70)` (`0x4d94b8`), the thunk into `0x11aec0`.
Clone ids therefore count announcements and differ from channel ids.

**Kind 1**, body 0x168 bytes, is the identity, sent from state 6 by both stations before either has
received anything. The body is the save's MyStatus block, copied from the block's data into
`obj+0x450` (`0x3493f4`), and the header is prepended to that buffer. Names are UTF-16LE, at body
offsets:

```
+0x34  2  0x0002
+0x38 16  trainer name
+0x52 16  Pokemon name
```

**Kind 2**, body 0xe8 bytes, is the offer, sent the instant the station's published state word
reaches 2 and again under the next step every time the station's player changes the Pokemon it is
offering. A station moving its cursor over a party of three sent steps 2 through 7 in a minute,
carrying its first Pokemon twice and its second four times. The selection browses the box: one
console offered nine different structures in a row. A new step is answered; a repeated step is a
retransmit and is not.

The offer is sent by the party-offer object (constructor `0x349bf0`, 0x278 bytes), which
`0x344510` creates at `mgr+0x68` unless one exists. Its update `0x34a210` sends the 0xe8 structure
at `+0xa0` whenever `+0x270` is set and `+0x272` clear, and clears `+0x270` once sent. `0x34a3d0`
packs a Pokemon into `+0xa0` (`0x7294e0`) and sets `+0x270` when the status allows it (A 0: local
state other than 1 or 2; A 1: local state 3 or above 4; A 2: never; A 3: the partner leaving,
`0x3490c0`). The trade UI calls it on a selection change (`0x8f0c04`, `0x8f0c38`, `0x8f8fb0`,
`0x90b87c`, `0x90b8c0`). `0x344620` destroys the object: in a trade at `0x886c70`, once the commit
has succeeded and before the trade demo starts, and at `0x8869f0` when the link ends (states 3 and 8
of `0x886530`, "The trade dispatcher" below). The normal save after a trade creates it again
(`0x8375a4`), and `0x886f30` asks for it, each construction registering a new channel id.

**Kind 3**, body 4 bytes, is the commit: one u32, sent by the sync save ("The commit and the trade
lock" below). Each station sends a 1, and one station sends a 2 after the peer's 1. In the captured
trades the host sends its 1 and its 2 63 to 66 ms apart; the joiner sends its 1 within a frame of
the host's first, and the host's 2 follows the joiner's 1. A joiner that also answers the 2 with a 2
is tolerated. A station that has sent a commit shows a spinner with no button prompt and waits for
the peer's. A commit exchange that does not complete leaves the save's trade lock set.

**Kind 4**, body 0xe8 bytes, a box structure, rides the channel of the party-offer object the
normal save re-creates about 3 s after its own save, the fourth registration of the session. It
follows the trade animation. In every completed hosted trade the console's kind 4 is byte-identical,
over all 232 bytes, to the first kind 2 it sent in the session, while the Pokemon it traded differs
from that first offer. The body is one structure, so the comment on `RESULT_MESSAGE` in
`pokeldn/lgpe/pb7.py` ("a box structure per slot, the party as it stands once the trade has gone")
does not describe it. That kind 4 opens the next round's offers is a reading from the registration
order; no capture shows a second round's offer after it. A retail host sent its
first 26.8 s after its second commit and an emulated host 29.9 s; the emulated joiner's followed the
host's by 34 ms. The first carries the station's first slot, the structure it offered under step 2,
and a new one follows each selection: one console sent fourteen, under steps 13 to 26, species 1,
150, 143, 138, 118, 126, 132, 126, 113, 105, 106, 107, 108 and 16, and others sent one. A joiner
that sends none leaves a retail host's trade complete. A retail console joining a hosted trade
announced the two clones of its new party-offer object 30.5 s after the last kind 3 and sent its
kind 4 31.2 s after it.

A complete trade, both stations counting their own steps:

```
step 1  kind 1   identity
step 2  kind 2   the offer, again under a fresh step per selection
step 5  kind 3   commit, body 1
step 6  kind 3   commit, body 2
step 7  kind 4   the first slot, again under a fresh step per selection
```

The body of kinds 2 and 4 is one 232-byte box structure: the generation 7 layout under the
generation 6 encryption, with an encryption constant at +0x00, a zero sanity word at +0x04, a
checksum at +0x06, and four 56-byte blocks from +0x08 permuted by `((ec >> 13) & 0x1F) % 24` and
XORed with a 16-bit stream from an LCRNG seeded with the constant. `pokeldn.lgpe.pb7` reads and
writes it; a captured offer decrypts to a checksum that agrees and re-encrypts to the bytes that
arrived.

The state word is byte 12 of the `f3` state data and walks 0, 1, 2 on every clone a station owns. A
station that publishes 2 and sends its kind 2 message waits there until the peer answers with one of
its own.

### What gates the game's own first message

The game's link-trade object runs a per-frame state machine (`0x349200`, jump table `0xf4e994` on
the state word at +0x68). State 6 sends the first game message, and nothing from the network
reaches it: two stations send the same message 18 ms apart, before either has received anything.
The only gate is state 4, `0x11b080`, which asks whether the Pia channel is ready:

- a SendClone at the object's +0x90 reports ready (`0x5221b0`): its element's participating
  stations, `element+0x3C`, must all be in the clone's acknowledged set, `clone+0xA8`;
- a SharingClone at +0x1258 reports ready the same way (`0x522610`);
- every station's entry at +0x250, one per 0x118 bytes, has 1 in its first word and a non-zero
  byte at +0xD8;
- the byte at +0x1430 is not 0xFD. It is a station index and 0xFD is this build's "none"; every
  path where it is 0xFD returns 0.

The SendClone's check is `(element+0x3C & ~clone+0xA8) == 0` and the SharingClone's is
`((clone+0x114 | ~clone+0xA8) & element+0x3C) == 0`, so the second also needs the element's
participants clear of `+0x114`. Both clones share one element. Measured on a session that works,
the fields that move from refusing to ready are only three: the SendClone's acknowledged set fills,
the SharingClone's `+0x114` drains, and every station's `+0xD8` becomes 1. The participating set is
already full while the gate still refuses, so participate messages are not what is missing.

A station's bit reaches `clone+0xA8` in one place: receiving an 0xa2 on **clone type 2** from that
station (`0x51c52c`'s jump table `0xf76c38`, entry for 0xa2, into `0x522350`). No other clone type
and no other message sets it.

The receiving side stores each arriving message at `this + node * 0x1C8 + 0xC0` and counts them at
`this+0x470`; at two it advances and goes quiet. The barrier is two because the sender delivers its
own message to itself, so a partner that never sends leaves the count at one.

### Hosting a retail console to its trade screen

A console that joins a hosted session renders both Pokemon on its trade screen and exchanges the
game's own messages. What it takes, above the layers a joiner already needed:

- **The Local Protocol's body carries the host's constant id little-endian**, where the message
  header carries the same value big-endian. The game resolves an arriving message to a node through
  the session's station table (`0x1171b0` to `0x5bbe70` to `0x5b6130`), and a sender it cannot
  resolve is given node 0xFD, which the receive at `0x117334` compares against 3 and skips. With the
  id big-endian every game message from the host is dropped before it is counted, while the mesh and
  clone protocols, which read the mesh table, are unaffected: the console sends its own first message
  and waits at state 7 forever, its screen reading that it will soon be connected to another player.
- The update session goes out when the session changes and once more behind it, never on a timer.
  A reference host sent four in 441 seconds. Its node list holds one node until the peer has joined
  the mesh and two from the frame after.
- A station stops sending clone clock requests the moment it participates.
- The host announces clone 1 in the frame it publishes clone 0. The console announces its own copy
  31 milliseconds later, so a host that waits loses the race and the two roles are reversed.
- The answer to the peer's announcement of a clone the host owns is built after the whole datagram
  is parsed. The clock its `0xa2` must carry arrives in the `0xa1` behind the `0x81` that asks for
  it, and an answer built from the `0x81` alone carries the host's own clock, which no completion
  matches: the console then retransmits that announcement every half second for the rest of the
  session and never publishes its own copy.
- Both stations answer every clone type 2 publish with a copy of their own, about ten times a second
  for the whole session. The completed trade carried 2410 records from the console and 2393 from the
  joiner.
- The 20-byte data a clone type 2 copy carries holds the station's own step counter at +12. It moves
  with every game message the station sends, and the two stations' counters track each other.
- An offer is answered under the step the offer carried, not the next one. A station that answers
  under a fresh step opens a round of its own, and the two then answer each other without end.

### The two clone records a trade walks

The trade object publishes its state on the clone it owns and reads the peer's back. Two records
carry it.

The clone type 2 copy's 20-byte data is five words, written by `0x11bc00` and its siblings:

```
+0x00  4  the state: 1 a vote (0x11bc00), 2 a vote withdrawn (0x11b4e0), 4 a forced leave (0x11bcf0)
+0x04  4  that call's argument, 1 on selection and 2 on confirmation
+0x08  4  a counter, incremented on each call
+0x0c  4  the station's own step, the number of game messages it has sent
+0x10  4  the trailing word
```

The clone type 4 copy's 32-byte data is the session host's, the authority's, view:

```
+0x00  4  A, the agreed argument
+0x04  4  B
+0x08 16  one counter per station index (host 0, joiner 1): the counter of the vote it last saw withdrawn
+0x18  4  the station's step
+0x1c  4  the trailing word
```

The authority `0x11b6c0` runs every tick on the session host. It moves A to X only when every
station publishes state 1 with argument X on the current trailing word, and then publishes A and
the trailing word on by one together; a state 4 moves A at once. For a station in state 2 whose
argument differs from A it writes that station's counter into its slot, moves the trailing word on
by one, keeps A and B, and republishes its own type 2 under the new trailing word.

The trade screen reads a status from A and its own record's state through the party-offer object's
`0x34a300` (jump table `0xf4e9b0` on A). Before any table, `+0x271` set with `+0x272` clear gives 1.

| A | local state 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| 0 (table `0xf4e9d0`) | 0 | 1 | 1 | 0 | 0 |
| 1 (table `0xf4e9f0`) | 2 | 3 | 3 | 0 | 2 |

A 2 gives 4 whatever the local state, and A 3 gives 5, the partner leaving (`0x3490c0`).

The status function `0x3488b0`, its tables `0xf4e920..0xf4e980` and the loop at `0x9c3300` belong to
another class, `0x347e10` (0x718 bytes at `mgr+0x70`, record at `+0x70`, created by `0x344690`).
`0x886530` creates that object when its mode word `+0x8C` is 1 or 2 and the party-offer object when
it is 3 (`0x886ed0..0x886f30`).

The trade UI's update (`0x756a20`, sub-state `[ui+0xa8]`) works off the party-offer object
(`0x7568ec`). On confirmation it votes 2 (`0x756e34` -> `0x34a4e0` -> `0x11bc00`) and moves to
sub-state 2 (`0x757058`). In sub-state 2, status 4 writes 5 at `[[x21+0x78]+0x60]`, calls
`0x74a590(ui, 2)`, and the trade proceeds (`0x756c0c..0x756c38`); status 2 returns to the selection
(`0x756cb4`); a menu result of 3 under status 1 or 3 withdraws the vote (`0x756d94` -> `0x34a500` ->
`0x11b4e0`, record state 2). In sub-state 0, status 1 with `[x22+0x258]` zero calls `0x34a4a0`
(`0x756b94`), the other withdrawal.

`0x11b688` stages an arriving clone type 4 record into the trade object at `+0x1638`, and `0x11ba20`
compares it field for field against the object's own: `+0x1638` against `obj+0x04`, `+0x163c`
against `obj+0x10`, and one word per node from `+0x1640` against `obj+0x0c`. A host that publishes
32 zeros there leaves every comparison unsatisfied: the console renders both Pokemon, holds
"communication en cours" and greys every button but Retour. Carrying the state unlocks them.

The offered party clone walks 1 in each of the first three words, then a trailing word of 1, then 2
in the second and third, then a trailing word of 2. The clone the commit creates, one id above the
party clones, takes the first two of those and then a zero. The host's frames, the same on a retail
host and an emulated one, with the clone type 2 data as five words:

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
+27 s     two more clones announced, 32 zeros on type 4; the peer publishes 0 0 0 on each
+0.5 s    kind 4 under the next step, every copy republished under it
```

The peer answers the trailing word 1 only when the type 4 copy's first word is 1: a host that
publishes the type 4 copy off the record it held before the peer's 1 1 1 landed carries a 0
there, and the console mirrors 1 1 1 and waits. A host that walks the commit clone on to 1 2 2
gets 0 1 1 with the trailing word 2 and no kind 3, and the console sits on its confirmation
screen.

A console whose player pressed A again as the confirmation greyed the buttons (the cursor then
sits on Retour) withdrew its vote: `2 2 3` (state 2, argument 2, counter 3) after its `1 2 2`. A host
that answered with A 2 gave it status 4, which in the confirmation sub-state proceeds to the trade:
the console republished `0 2 3`, never answered the commit clone, held a warning screen, and its
save refused the next trade. That console started its sync save: 3.9 s after its `0 2 3` (5.0 s
after the host's A 2) it announced a new clone, id 4, with the usual `0x81` on clone type 2 and
`0xa1` on clone types 4 and 1, a second `0xa1` on clone type 1 19 ms later and one `0xe3`, the
announcement the sync save's state 2 makes when it registers the commit channel, which runs only
after the 600 was committed. It then sent nothing more on clone 4 for the 214 s the capture ran,
neither the `0xa2`s nor the vote a completing console sends there, while it kept its clones 1, 2
and 3 and its link protocols (0x1c, 0x58) alive. The console never answered the host's `0xa1` on
clone type 4, which a completing console answers with an `0xa2` 19 ms later. Every unicast frame
the host's radio sent in that session, the seven packets of the host's answer among them, was
acknowledged by the console's radio (9672 TX_DONE records, all acknowledged). The authority's answer, type 4 `1 0 0 3 0 0 step T+1`, takes the same
console record to state 0 under the game's own `0x11ba20`, and with A 1 that is status 2
(`0xf4e9f0[0]`), which returns the screen to the selection. `bin/lgpe_host.py` answers that way and agrees a second vote in one publish;
`tests/test_lgpe_host_withdraw.py` runs both through the game's code. On a retail Let's Go Pikachu
a withdrawn selection, `2 1 4` with A 0, took the answer `0 0 0 4 0 0 step T+1`: the console
republished `0 1 4` and stayed on the trade screen, then voted 1 and 2 again, each agreed in one
publish, and the trade went through.

Publishing no clone data on clone types 4 and 1 at all, which is what two retail consoles exchange,
leaves a console that joins short of the gate at `0x11b080` and on its search screen.

### The commit and the trade lock

The trade lock is a u32 countdown in seconds in the save's MyStatus block. A trade's save sets it to
600 and commits that before the commit exchange; the exchange completing commits it back to 0.

The MyStatus block object is `[[[0x15fad08]]+0x98]+0x58` -> `+0x78`, its data `obj+0x58`, 0x168
bytes (`0x1c9ff0`, `0x1ca000`, slots 5 and 6 of vtable `0x153e0b0`), the body of the kind 1
message. The counter is `obj+0xe8`, MyStatus `+0x90` (setter `0x1c9d40`, getter `0x1c9d50`). In
`savedata.bin` the block is `0x1000..0x1168` and the counter `0x1090`: a save kept after an
interrupted trade holds `58 02 00 00` there and differs from the clean save in no other byte of the
block, whose trainer name at `0x1038` places it. Every captured kind 1 body carries 0 at `+0x90`.

The setter `0x1c9d40` has six callers: the sync save with 600 (`0x837f90`, `0x837fb0`), the
application of the received Pokemon with 0 (`0x838bec`, `0x838c0c`), and the countdown (`0x1ca54c`,
`0x1ca56c`). No relocation reaches it, and no store to `+0xe8` through a base loaded from `+0x78`
within 12 instructions appears anywhere in `.text`; that search does not exclude an inline write by
another path or a block copy. Loading the save writes the block. The getter is called by the countdown and by the
link menu's check. That check, `0x9765f4`, switches on the link mode: mode 1, trade, reads the
counter (`0x976634`), and a non-zero value stores the refusal message `0x0248810f825b1fee` and
returns -1 (`0x97663c`); zero goes on to a count check (message `0x0248800f825b1e3b`). Mode 3
refuses when `[x22+0x62] <= 1` (message `0x02487f0f825b1c88`).

`0x1ca450(playtime, seconds)` is the play-time tick. It returns at once when `seconds > 1`
(`0x1ca46c`) or when `playtime+0x100` is clear (`0x1ca474`); otherwise it subtracts `seconds` from
the counter, floored at 0 (`0x1ca500`), and adds them to the play time (`+0x54` hours as a u16,
`+0x56` minutes, `+0x57` seconds, capped at 999:59:59). `0x1ca7e0` writes `playtime+0x100` as
`nn::oe::GetCurrentFocusState() != 3`, 3 being the SDK's Background. Its only caller, `0x1462a0`
(called only from `0x13c944`), runs it once every 20 calls (counter `+0x70`, `cmp w8, #0x14`), while
its enable byte `+0x54` is set and no save thread exists (`0x1ce8f0`, `[[0x15fd9d8]+0x58] != 0`
skips the whole function and the counter). It keeps three u64 fields: `+0x58` the last
`GetSystemTick`, `+0x68` a base tick, `+0x60` the whole seconds since the base already counted. On
the gated call it converts `tick - base` to whole seconds (`0x146314..0x146354`) and, when that
exceeds `+0x60`, passes the difference to `0x1ca450` (`0x146358..0x14636c`) and stores the new total
in `+0x60` (`0x14637c`). The base moves only when the tick reads lower than the last value
(`0x146384..0x1463c0`). The seconds are system-tick seconds (`nn::os::GetSystemTick` at `0x1462e8`,
`nn::os::ConvertToTimeSpan` at `0x146324`), not frames. Seconds are counted from a fixed base, so no
fraction is lost between calls, and a call that sees two or more new seconds passes them to a tick
that ignores them: the clock adds at most one second per gated call.

The lock and the play time move in the same call, by the same one second: while the lock is
non-zero, every second added to the play time takes one second off it. A lock of 600 therefore
lasts ten minutes of counted play time, whatever the call rate; a second the clock drops, the lock
drops too. The two part only at the 999:59:59 cap, which stops the play time (`0x1ca5a0 b.eq
0x1ca610`) after the lock has been written. The clock runs in focus states 1 and 2, in focus and out
of focus, and stops only in state 3, the background; it does not run while the game is closed (the
base tick is re-read at start, `0x14628c`) or while the gated call is skipped.

`0x13c944` sits in `0x13c850`, which also runs `0x145560`, `0x13f0d0`, `0x142cd0` and `0x1427a0` on
each call and is reached only from `0x13c5a0` (`ldr x1,[x0,#0x208]; b 0x13c850`), slot `0x1537a28`
of the vtable `0x15379d8`. That object is a 0x210-byte job built by `0x13c440` (`0x13c490`, `+0x204`
its done byte) from `0x13bfa0`, in the game's setup `0x13b650`. The job executor `0x231a0`, reached
from the worker loop at `0x20f30`, calls its slot `+0x40` (`0x23278..0x23288`) while `+0x204` is
clear (`0x23264`).

The frame period is chosen at run time from the table `0xf7eeb8` (GOT `0x15fb438`): 16666667,
33333334, 50000000, 66666667 and 83333334 ns, indexed by `0x39600` (`0x39610`). `0x29e80..0x29eb4`
turns the current period into a present interval `clamp(period / 16666666, 1, 5)` for `0x358b0`. The
class at vtable `0x1529968` (GOT `0x15fb6c8`) starts both of its entries at table entry 1,
33333334 ns (`0x38ba0..0x38bb8`), so the frame loop starts at a 33.3 ms period. Whether anything
changes that period during a session, and how often the job `0x13c5a0` runs, is unread.

`0x347190` builds one of three save sequences: 0 "normal save" (`0x3474d0`), 1 "sync save"
(`0x347670` -> `0x347ae0`, 0xc8 bytes), 2 "fatal error" (`0x347810`); the names are the strings at
`0xf04ca7`, `0xf04cb3`, `0xf04cbd`. A trade saves through the sync save. Its init `0x837c70` (vtable
slot 17, `0x15aa770`) creates the commit channel object (`0x4d9030`) at `seq+0xb8`, sets the counter
to 600 (`0x837f88`), and starts `SaveThread` (`0x1cdc80`, at `0x83803c`), which serializes the save
on the calling thread before it starts (`0x1cdd84` -> `0x1cc990`) and commits as soon as it has
written (`0x1cedd4..0x1cede0`, `nn::fs::CommitSaveData`). Its update `0x838070` (slot 18,
`0x15aa778`) runs on the state word `seq+0xa8` through the jump table `0xf867c4`:

| state | address | what it does |
|---|---|---|
| 0 | `0x8380ac` | any recorded network error (`0x4d8a70`) writes result 2 and leaves (`0x8383c8`); otherwise waits for `SaveThread` (`0x1cdf40`), stores whether this station sends the 2 (`0x838660`) at `seq+0xc0`, applies the received Pokemon and zeroes the counter in memory (`0x838800`, `0x838bec`), sets `netmgr+0x121` (`0x4d8b10`) and starts `FirstSaveThread` (`0x1ce050`) |
| 1 | `0x8380d8` | waits for `FirstSaveThread` to write (`0x1ce310`), then draws a delay of `2000 + r % 6000` ms from an MT19937-64 seeded with `GetSystemTick` (`0x838180`, `0x8381d8`) |
| 2 | `0x838234` | after the delay, registers the commit channel (`0x8382a8`) |
| 3 | `0x8382b4` | votes 1 on the commit clone on its first pass (`0x4d9690`: `chan+0x64 = 1`, `0x11bc00`), then waits for the channel's gate (`0x4d94d0`) and for the clone to be idle with `[chan+0x74]` equal to 1 |
| 4 | `0x8382ec` | sends a kind 3 carrying 1 |
| 5 | `0x838310` | takes a kind 3 from the other station, skipping its own loopback (`0x838360`); a body other than 1 is the error path (`0x83836c`); if `seq+0xc0` is set, sends a kind 3 carrying 2, and a failed send stays in state 5 with the peer's 1 consumed |
| 6 | `0x83839c` | takes a kind 3 from any station: a 2 clears `netmgr+0x121` (`0x4d8b20`) and signals the commit (`0x1ce3f0`); any other body is consumed and ignored |
| 7 | `0x8383e8` | waits for `FirstSaveThread` to commit (`0x1ce410`) and ends with result 0 |

`FirstSaveThread` serializes the save as it starts (`0x1ce154`), after the counter was zeroed,
signals `mgr+0x78` once written, waits on `mgr+0x84`, and commits only if the abort byte
`mgr+0x100090` is clear (`0x1cedf4..0x1cee18`). The error path of states 2, 3, 5 and 6 (`0x8383b0`)
and of state 5's wrong body (`0x838520`) writes result 2 into the parent (`[x0+0x88]+4`) and calls
`0x1ce520`, which sets the abort byte, signals `mgr+0x84` and sleeps in 1 ms steps until the thread
has ended. State 0's recorded-error path (`0x8380c8..0x8380d4`) writes the same 2. Every error path
then ends the sequence with `0x838540(seq, 0)`, as the success path does after writing 0
(`0x838400`); the sequence itself never selects the fatal error. The second save is dropped, and the
save on disk keeps 600.

The trade dispatcher (`0x886530`, "The trade dispatcher" below) reads that result in its state 3
(`0x886684`): a 2 calls `0x345b10` (`0x886690`) and
returns without advancing. `0x345b10` builds a process of vtable `0x154f1f8` (0xa8 bytes, `+0x88 =
0` at `0x345d68`) and pushes it on the root process stack (`0x13a6b0`: the new process's `+0x60` is
the old top, root `+0x78` the new one). Its method `0x346140` (slot `0x154f248`) builds a save
process of type `[proc+0x88] != 0 ? 3 : 2` (`0x3461b8..0x3461d0`), and both types map to the fatal
error sequence. Its init `0x836320` picks the message by the save type, `0x191615296121e064` for 2
and `0x977c18bf4135ff42` for 3 (`0x8365f0`), and shows it through `0x7ed60` (`0x836714`); it calls
nothing that leaves the sequence (`0x838540`, `0x11ce20`), and its update (`0x836780`, vtable
`0x15aa3b8`) is a bare `ret`. An aborted sync save in a trade therefore ends on the fatal error
screen with message `0x191615296121e064`, nothing in that sequence returns to the game, and no later
save of the running game follows it: the save on disk holds 600 at the next boot.

The game has one process stack, rooted at `[G+0x68]` (`G = [0x160d310]`): its only constructor
`0x13a4e0` is called once, from `0x13b978` in the setup `0x13b650`, and stores `G` at `root+0x60`.
The dispatcher and the fatal-error wrapper are pushed on that same root (`0x8860e4`, `0x345e80`).
The runner `0x13a780` (one caller, `0x13b0f4`) updates only the top process `[root+0x78]`, through
`0x13a160`: a return of 3 runs the new top in the same frame, 1 pops the top or swaps in the pending
`[root+0x80]`, anything else returns. The wrapper's vfuncs are `+0x38 = 0x346130` (returns 1),
`+0x40 = 0x346140`, which hands the fatal save process to the manager at `[G+0x60]` through
`0x39c20`, `+0x48 = 0x346210` (returns 0) and `+0x50 = 0x346220`. Its update never returns 1, so the
runner never pops it, and the dispatcher below it, whose state 3 returns 0 right after the push
(`0x886694`), is never updated again: one fatal process per aborted commit.

The link menu's three refusal ids, `0x02487f0f825b1c88`, `0x0248800f825b1e3b` and
`0x0248810f825b1fee`, are consistent with FNV-1a-64 hashes of three strings that differ only in their
last byte: adjacent ids differ by the 64-bit FNV prime `0x100000001b3`, the outer pair by twice it,
and multiplying each by the prime's inverse modulo 2^64 gives values ending `dd58`, `dd59`, `dd5a`.
That the strings are message label names is a reading. The fatal init stores only the id
(`0x8366ac`, at `+0x58`) in the object it hands to `0x7ed60` and references no archive name; the
text is in the romfs message archives.

While `netmgr+0x121` is set, `0x4d8750` records every network error at severity 4
(`0x4d8760..0x4d877c`), and states 2, 3, 5 and 6 test for exactly that (`0x4d8a80`: an error
recorded, at severity 4). A recorded error is replaced only by one of higher severity (`0x4d879c`),
so an error above 4 recorded before `+0x121` was set fails that test. `+0x121` is set at the end of
state 0 (`0x4d8b10` at `0x8384f8`) and cleared by state 6 on a received 2 (`0x4d8b20` at
`0x838494`). No state has a timeout: a peer that goes quiet leaves the sequence waiting until the
link fails.

The recorders are `0x345790` (code 0xe), `0x3457d0` (0x11), `0x345810` (0xf), `0x345860`,
`0x3458a0`, `0x345900` (an `nn::Result`), `0x345940` (the online serial-code client `0x94fa00`),
`0x3459f0`, `0x345a50` and `0x345aa0`. The listener at `mgr+0x60` (built at `0x343d34..0x343d70`,
vtable `0x154f068`) routes its seven slots `0x154f0b0..0x154f0e0` to three of them: `0x344c30`,
`0x344c60`, `0x344c70` and `0x344c80` to `0x345790`, `0x344c40` to `0x345900`, `0x344c50` to
`0x345860`, `0x344c90` to `0x3457d0`. The trade session object holds it at `+0x98` (`0x349540`) and
its vtable `0x154f608` forwards slot 9 (`0x349650`) to the listener's `+0x38`, slot 10 (`0x3497d0`)
to `+0x48`/`+0x40`, slots 11 to 14 (`0x349880`, `0x3498e0`, `0x349940`, `0x3499a0`) to `+0x50` to
`+0x68`. The link state machine `0x4d9b70` (from `0x349520`) enters state 6 when its state is 5 or
less, no operation is pending (`[x19+0x20]` null) and the per-frame pump `0x1175d0` returns 0
(`0x4d9b98..0x4d9bc8`), and state 6 (`0x4d9fb0`) calls slot 9 (`0x4da078..0x4da084`), recording code
0xe. `0x1175d0` returns 0 when `[x19+0x80]` is null, when the transport object's `+0x48` is not 5
(`0x11c560`), or when the session's u16 at `+0x1e6` (`0x59ea70`) is 1 or less
(`0x1176b0..0x1176bc`). The same machine's state `0x4d9ef0` calls slot 14, code 0x11, then enters
state 6.

Only `0x59eab0` writes `+0x1e6` (`0x59eb58`, `0x59ebb0`). It sums, over the stations in the
session's list at `s+0x178`, the byte `0x5b5900` returns for each (`0x59eafc..0x59eb58`): byte
`+0x415` of that station's record (`0x5a9cd0`, a record in state 3, none found adding nothing), which
the connection-response parser fills from wire byte `0x35` (`0x5b962c..0x5b9658`, `0x5a9430`). A
retail Let's Go sends 1 there, so with retail peers the value is the number of stations in the list.
`+0x1e8` is the same sum over `0x5b5960`. The recount runs from `0x59dfc4`, `0x59f08c`, `0x59f158`
and `0x59f21c`, and only when `[s+0xd8]` is outside 2 to 6, `[s+0xd4]` is 2 or 4 and
`0x52abf0(s+0x38)` is false (`0x59eacc..0x59eaf8`).

The link machine also calls the session's slot 10 (`+0x50`, `0x3497d0`) at `0x4da38c`, in
`0x4da294`, with two out-arguments (`0x4da378..0x4da38c`).

`0x838660` decides who sends the 2. With S = {144, 145, 146, 150, 151} (`species - 0x90` in the
mask `0xc7`) and M = {808, 809}: a station whose offered species is in S or M and whose received
species is in neither sends it; a station in the reverse case does not; otherwise the station for
which `0x4d9720` returns true sends it (`[mgr+0x128c] != 0`). A station giving Mewtwo, Mew,
Articuno, Zapdos, Moltres, Meltan or Melmetal for an ordinary Pokemon sends the 2 whether it hosts
or joins, and its partner sends none.

The parent block (`[parent+0x88]`, "The trade dispatcher" below) carries the box index of the
station's own offered Pokemon at `+8` and the arriving Pokemon at `+0x10`. `0x838660` takes the own
species from box slot `[block+8]` (`0x8386c0`, `0x1c0d30` returning the object at `box + 0x3f800 +
idx*8`, 0x3e9 meaning none, box `[[[[0x15fad08]]+0x98]+0x58]+0xb0`) and the received species from
`[block+0x10]` (`0x838718`). State 0 calls it before `0x838800` (`0x8384e0`, `0x8384f0`), which
copies `[block+0x10]` into a new Pokemon object (`0x8389fc`, `0x838a38`) and writes it over the same
box slot (`0x838af0 ldr w2,[x25,#8]; 0x838afc bl 0x1c0f30`), so the slot still holds the own
Pokemon when the species are compared.

`0x838800` also runs the trade's side effects on the arriving copy:

- `0x1cfe80` registers it in the Pokedex (`0x83897c`), and the evolved copy again when it evolves
  (`0x838ab0`), on the object `[[[[0x15fad08]]+0x98]+0x58]+0x88`. It builds a record of species,
  form, `0x727ab0`, `0x728b00 & 1`, the egg flag `0x727fb0(pkm, 2)` and `0x728b50`, and `0x1cff60`
  returns on an egg, on species 0 or above 809, and otherwise sets bits in per-species arrays at
  `obj+0xdc` indexed by `species - 1`. The form is zeroed when `0x1760a0(species, form)` is true.
- `0x728250(pkm, partner, &species, &index)` is the trade-evolution check. `0x723220` returns the
  species unchanged for an egg or, for any species but 64 (Kadabra), when the held item passes the
  manager's vfunc `+0x28`; otherwise it walks the species' evolution list and returns the first
  entry `0x723340` accepts: method 5 always, method 6 when the held item equals the entry's
  parameter, method 7 when the two Pokemon are species 616 and 588 (Shelmet and Karrablast) in
  either order. `0x838800` passes the arriving copy as both Pokemon (`0x838a44..0x838a4c`), so
  method 7 never matches.
- `0x7282c0` applies a match: it changes the species through `0x7283c0` (`0x728338`), adds one to
  the form for method `0x22` (`0x728328`), and clears the held item for methods 6, 19 and 20 (mask
  `0x180040`, `0x7318f0(.., 0)` at `0x728364`).
- `0x1ca840(id, 1)` adds to game record 477 when `0x115860` is true and 476 otherwise
  (`0x838828..0x838840`). It adds `n` to the u32 at `obj+0x54+4*id`, capped by
  `0xf48368[0xf4b760[id]]`, on the object `[[[[0x15fad08]]+0x98]+0x58]+0xc8`; while the byte
  `obj+0x10f8` is set it writes nothing for any id (`0x1ca8f8`), and an id above 999 writes nothing
  there.

`mgr+0x128c` is written only by the session-start function `0x116890` (one caller, `0x4d9f54`): 0
at `0x116a14`, then `0x59e920(session) & 1` at `0x116a48`; `0x4d9730` and `0x4da860` read it.
`0x116890` runs only on the link machine `0x4d9b70`'s step from state 2 to state 4 (jump table
`0xf73a0c`; state 3 at `0x4d9f48`, the call, state 4 at `0x4d9f5c`), after the matching job has
finished with success and the transport's `+0x48` is 5. State 2 is written only at `0x4da7fc`, in
`0x4da710`, which starts `MatchingThread`. A host migration is Pia's own job and does not re-run
`0x116890`.
`0x59e920` returns 1 when `[s+0xe0]` is non-null, equals `[s+0xe8]`, and the station
`[s + 0x148 + 8*[s+0x142]]` answers true to its vfunc `+0xe0`. `[s+0xe0]` is the local station and
`[s+0xe8]` the session host: creating a session (`0x59f810`, from `CreateSessionJob` at `0x582a2c`
and `RandomMatchmakeJob` at `0x59b3f0`) stores the local station into both (`0x59f864 stp
x0,x0,[x19,#0xe0]`), joining (`0x59f890`, from `JoinSessionJob` at `0x586ea0` and
`RandomMatchmakeJob` at `0x59be40`) stores the local station into `+0xe0` and the station looked up
by another id (`0x58e5d0` -> `0x5b8030`) into `+0xe8` (`0x59f920`); the local station index at
`mgr+0x1288` comes from `[s+0xe0]` too (`0x59e970`, `0x116a3c`). `mgr+0x128c` is whether the local
station was the session host at session start.

For a peer this means:

- The console's record reading A 2 in the confirmation sub-state gives status 4, which starts the
  sync save and commits 600. An authority that publishes A 2 owes the whole commit exchange.
- A first kind 3 from the peer carrying anything but 1 aborts with the lock set; the 2 follows the 1.
- A kind 3 sent before the receiver's state 2 has registered the commit channel is dropped as an
  unregistered kind. The vote in state 3 is agreed only once both stations vote, and each votes only
  after registering, so it holds each station's kind 3 until the other has registered.
- The delay of state 1 moves a console's kind 3 by up to six seconds from one trade to the next. A
  retail console announced its commit clone 5.0 s and 9.0 s after the host published A 2 in two
  sessions.
- Any network error the game records from the end of state 0 until a 2 arrives aborts the commit:
  the save keeps 600 and the console ends on the fatal error screen.

### The trade dispatcher

`0x886530` runs the link from the menu to its exit, switching on `[obj+0x68]` through the table
`0xf87bc4`:

| state | entry | what it does |
|---|---|---|
| 0 | `0x886578` | setup |
| 1 | `0x88669c` | waits for its child; a recorded network error (`0x345af0` -> `0x4d8a70`) goes to 8 (`0x886ec8`); mode `+0x8c` 1 or 2 creates the `0x347e10` object (`0x886f04`) and the battle scene (`0x886f18 bl 0x95c470`) and goes to 6; mode 3 asks `0x344510` for the party-offer object (`0x886f30`) and stays until it reports ready (`0x886f34`) |
| 2 | `0x8866f4` | copies the Pokemon in box slot `[obj+0xf8]` to `obj+0x148` as the outgoing one (`0x886748..0x886760`); a recorded network error goes to 8; `[obj+0x100]` 5, the trade UI's proceed, starts the sync save, any other value goes to 8 (`0x886700..0x88670c`) |
| 3 | `0x886670` | waits for its child; result 2 calls `0x345b10`, the fatal error, and does not advance (`0x886684..0x886698`); otherwise destroys the party-offer object (`0x886c70`), puts `[obj+0xf0]` at `obj+0x150` and starts the trade demo on `obj+0x148` (`0x886c7c bl 0x875f40`), state 4 |
| 4 | `0x886930` | releases `[obj+0x150]`, state 5 |
| 5 | `0x886950` | waits for its child; writes `[obj+0x158]` into box slot `[obj+0xf8]` (`0x8869a8..0x8869b4 bl 0x1c0f30`), starts a normal save, state 7 (`0x886e94`) |
| 6 | `0x886ee8` | state 8 |
| 7 | `0x886908` | waits for its child; result 1 goes to 8, any other to 1 (`0x88691c..0x886928`) |
| 8 | `0x8869cc` | destroys the party-offer object (`0x8869f0`) and the `mgr+0x70` object (`0x8869f8 bl 0x3447a0`) and leaves |

`0x344510`, when the party-offer object already exists, creates nothing and returns
`0x4d94d0([mgr+0x68]) & 0x11b4d0(mgr+0x70)`, the channel's and the clone set's readiness
(`0x34452c..0x344538` -> `0x34a1d0`).

A save starts through `0x887340`, which builds a save process (`0x346670`, 0x128 bytes, vtable
`0x15aa2a0`); the dispatcher stores the address of its own `obj+0x178` into the process at `+0x90`
(`0x8868dc`, `0x886e48`). The process's first update `0x8345d0` maps the save type `[[proc+0x90]]`
through `0xef9a80 = {1, 0, 2, 2}` to the sequence kind of `0x347190` and hands the same pointer to
the sequence (`0x834688 bl 0x839ba0`), which reads it as `[parent+0x88]`:

```
obj+0x178  +0x00  save type: 0 sync save, 1 normal save, 2 or 3 fatal error
obj+0x17c  +0x04  result, written by the sequence: 0 done, 2 aborted, 1 the link ends
obj+0x180  +0x08  box index of the own offered Pokemon, [obj+0xf8]
obj+0x188  +0x10  the received Pokemon, [obj+0xf0]
```

State 2 fills it for the sync save (`0x88685c..0x88689c`); state 5 sets the type to 1
(`0x886e00..0x886e04`). The normal save's update `0x8374b0` runs `SaveThread` (`0x8377bc`), waits
3000 ms (`0x8377ec`), then, if the trade session object's state is 8 (`0x349090`), creates the
party-offer object (`0x8375a4`, retried each frame on failure) and writes result 0 (`0x8375b8`); in
any other session state it writes 0 without creating it. Result 1 comes only from `0x837860`, on a
path gated on `[x20+0x258]` and a queue at `[x20+0x250]` (`0x83776c..0x8377a0`). After a completed
trade the dispatcher therefore returns from state 7 to state 1 with a new party-offer object on a
new channel, ready for the next round.

### The battle scene's channel

The senders in `0x9dce94..0x9dede8`, the only code that sends a non-zero tag, keep their state in a
global block at `0x1640eb0` whose first word is their channel (`0x9dce10..0x9dce1c`: `ldr
x0,[0x1640eb0]; b 0x4d9450`). `0x9dce50` sends four bytes from block `+0x78f0`, a u16 station byte
and a u16 0x6e, under tag 1 to 0xff; `0x9dd3ec` packs a Pokemon (`0x721ef0`) into block `+0x348` and
`0x9dd3fc..0x9dd40c` send it under tag 3. Per-station records are 0x1788 bytes (`0x9dcee8`).

The registration's one caller is `0x9d2d90` in `0x9d2c30`, whose one caller is `0x9cbf34` in
`0x9cbf00`, slot `0x15c7200` of the process vtable `0x15c71b0`. Only `0x9cbba0` builds that process,
called only from `0x28e6cc` in `0x28e630`, reached from `0x28cd10` and `0x28e4d0`. The code there
references `Pop_BGM_battle_to_field` (`0x28d6cc`) and `vs_wild` (`0x28c9fc`), the process loads
`bin/battle/background/btl_sky/btl_sky.gfbmdl` (`0x9ca548`), and the UI beside it the
`layout_setting_NBR_battleInfo_00` and `NBR_temochiButton_00` layouts (`0x9b8048`, `0x9b8fe8`).
`0x28cd10` is called from `0x28be20` and from `0x95cdd8`, in slot `0x15bed60` of the vtable
`0x15bed08` of the process `0x95c5c0` builds; `0x95c5c0` is called only by `0x95c470`, and
`0x95c470` only by the dispatcher's state 1 in modes 1 and 2 (`0x886f18`). The dispatcher never
builds the battle scene in mode 3, so its channel never registers in a trade session.

`0x9d2c30` is a stepped setup (jump table `0xf92c1c`, the step incremented at `0x9d3054..0x9d3060`).
Step 0 creates the channel object in `0x9dc5c0` (from `0x9d2f90`) and stores it at `0x1640eb0`
(`0x9dc6f4`, the only store of a channel there) only when the link session object
`[[[0x15faec8]]+0x50]` is in state 8 (`0x349090`, `0x9dc61c..0x9dc634`). Step 1 registers it with
no condition (`0x9d2d90 bl 0x9dce10`), and `0x9dce10` registers nothing while `0x1640eb0` is null;
the channel's readiness test `0x9dce30` returns 1 with no channel. A wild battle outside a link session
therefore registers no channel. The byte `[ctx+0x64]` read at `0x9d2d80` belongs to step 0 and gates
the setup's network-error test in step 2 (`0x9d2d9c..0x9d2da8`). The battle's teardown (`0x9d3df0` ->
`0x9dcce0`, `0x9dccf8`) clears the pointer.

### What a hosted trade puts in the save

The box structure the host offers goes into the console's save as sent. Measured on a retail Let's
Go Pikachu with a structure built from a donor Pidgey's, every changed field read back on the
console's own summary screen: species 132, experience 1,000,000 (level 100), ability 150 in the
hidden slot, a PID with a shiny xor of 0 against trainer id 41234 and secret id 12345 (shown as
the six-digit id 083154, `(sid << 16 | tid) % 1000000`), nature 10, genderless, 31 in every IV
("exceptionnel"), 200 in every AV (HP 437 at level 100, the game's own maximum), one move,
met level 30, met location 4 (Route 2), language 2, original trainer `POKELDN`. The game checks
none of it on receipt. `scratchpad/lgpe_make_ditto.py` builds it; the offsets are PKHeX's PB7 map.

### A joiner leaving

A console that backs out of the trade screen with Retour publishes the offered clone with 4 in its
state word: argument 0 under a fresh counter as it drops its selection, then argument 3 as it
leaves. The host answers each 30 ms later with zeros in the first three words, the trailing word
one further on, and the argument in the type 4 copy's first word; the console mirrors it with a
zero first word. The console then releases its clones with a 0x83 on clone type 4, station 0xFD
(clone 0 on clone type 3), and repeats each every 100 ms until a 0x84 on the same clone type and
id answers it; the host releases its own copies behind it, a 0x83 on clone type 2 under its
station to both stations and one on clone type 4 to the console, and the console acknowledges
each. 2.45 s after the last release, the console sends a mesh leave request on the mesh
protocol's reliable port, two bytes under the 24-byte reliable header:

```
04 01        leave request, station index
```

It is owed that header's acknowledgement on the same port and a two-byte leave response, `08`
and the station index, on the unreliable port; unanswered it repeats every 40 ms for five
seconds. The host then closes the connection with a one-byte station disconnection request,
type 3, which the console answers with type 4 within 20 ms and deauthenticates; a host that
does not, gets the console's own request five seconds later. The 2.45 s before the leave request
did not move with any of these answers and is the console's own.

A retail host answers a joiner's leave request with `08 00`, its own station index, twice, and
then sends a Local Protocol start host migration, type 0x13, every 0.3 s. A joiner that sends
its station disconnection request the instant the leave response arrives puts the host's player
back on the menu at once, with "l'autre joueur a choisi d'annuler l'échange"; one that waits
leaves the host repeating the 0x13 for five seconds. `bin/lgpe_join.py --leave-after SECONDS`
runs the whole exit (`pokeldn.lgpe.leave`).

An emulated host leaving does the releases first and then a migration start on the reliable
port, `44 00 01`, which the joiner acknowledges and answers with `48 01`, then the 0x13.

### What a host does with a joiner that holds no clone data

Measured against the retail Let's Go Pikachu, with a 0x3C-byte connection response that carries no
network id and no player. With the clock exchange and the sync clock both running, the console
answers the announcement of a clone, announces its own, and then releases it about five seconds
after the mesh join and sends 0x32. It sends no 0xb1 and no clone data. A real joiner reaches the
same point 1.1 seconds after its own participate and the host then sends the clone's data.

### Past the gate

The gate at `0x11b080` has been passed, and a Let's Go host has taken the joiner through its whole
trade handshake to state 8, the settled state, in 66 milliseconds:

    4 -> 5    the gate passes after seven refusals
    5 -> 6
    6 -> 7    state 6 sends the game's first message, 0x168 bytes from obj+0x450
    7         receives its own back, count 0 -> 1
    7         receives the joiner's, count 1 -> 2
    7 -> 8

State 7 counts the first messages it receives into `obj+0x470` and leaves for 8 at exactly two, its
own and the peer's, compared with `b.ne` rather than a bound. It stops receiving once it leaves, so
the count cannot overshoot. The host's screen reads that a player has been found.

The game's first message is the 376 bytes a joiner sends on the Reliable Protocol: a 16-byte header
and the 0x168-byte body state 6 transmits. The header's length, tag and destination are the
arguments of the `0x116f30` call in state 6:

    01000000 68010000 01000000 00ff0000    kind 1, 0x168 bytes, step 1
    02000000 e8000000 02000000 00ff0000    kind 2, 0xe8 bytes, step 2
    02000000 e8000000 03000000 00ff0000    kind 2, 0xe8 bytes, step 3

In a session that works the kind 1 messages are exchanged and acknowledged within 70 milliseconds,
the clone ids 2 and 3 are announced 3.2 seconds later, and the kind 2 messages follow 0.4 seconds
after that.

A host that has reached state 8 sends nothing further on its own. Its clone element's clock stops
advancing and the mode word at `+0x8C` stays 0, so the subsystem that announces clone ids 2 and 3
never runs. State 8 is terminal for `0x349200`, and what drives the phase after it is a different
subsystem.

### The state machine above the gate

The gate at `0x11b080` is state 4 of the trade session's own state machine, `0x349200`, dispatched on
the object's `+0x68` through `0xf4e994`. State 3 allocates the session sub-object at `+0xB8`, calls
`0x11aec0` through the thunk at `0x11b4c0`, and sets the state word to 4 with no condition of any
kind; state 4 calls the gate through `0x11b4d0` and advances to 5 when it returns true; state 5 sends
the game's first message. `0x3495e0` is the setter that puts the object into state 3, guarded only on
the state word: states 9, 10 and 11 are left alone and everything else becomes 3. Nothing in state 3
or state 4 reads the network.

Three setters sit in consecutive slots of the vtable at `0x154f648`, each the same seven
instructions over the same guard:

    0x154f648 -> 0x3495e0    state := 3
    0x154f650 -> 0x349600    state := 2
    0x154f658 -> 0x349620    state := 11, then the abort at 0x4d8b00

None is reached by a direct branch; all three are called through the vtable, which is why a scan for
callers finds nothing. `0x349650`, `0x3497d0`, `0x349880`, `0x3498e0` and `0x349940` follow them in
the same table.

    0x0011b4c0  ldr   x8, [x0, #0x20]      the thunk into 0x11aec0
    0x0011b4c4  ldrh  w1, [x0, #0x18]      the clone id
    0x0011b4c8  mov   x0, x8
    0x0011b4cc  b     #0x11aec0

    0x0011b4d0  ldr   x0, [x0, #0x20]      the thunk into the gate
    0x0011b4d4  b     #0x11b080

`0x11aec0` registers and announces a station's whole own clone set in one frame: the type-1 clone at
`game+0x90` from `game+0x678`, the type-4 clone at `game+0x1258` from `game+0x13f0`, then one clone
per party member, stride 0x118 from `game+0x218` with its source stride 0x260 from `game+0x8d8`. Each
goes to `0x51a550` or `0x51a510`, which enqueue an announcer on the element's list at `+0xD8`. The
sweeper `0x51b380` drains that list a tick later, one record per entry, and the type byte comes from
the table at `0xf46acc` (0x81, 0xa1, 0x83, 0xb1) indexed by the queued object's kind, not from the
call site. That is why an announcement arrives as `0x81` on clone type 2, `0xa1` on clone type 4 and
`0xa1` on clone type 1 in one frame: three entries off one queue in one tick.

The announcement is therefore upstream of the gate rather than an input to it. A station that emits
that triple has already passed state 3 and is asking the gate; a station that never emits it has not
reached state 3, and no message shape addressed to the gate's inputs can reach it.

Measured against the retail Let's Go Pikachu, the two directions differ. Hosting, it emits the triple
for clone id 1 and never for id 2. Joining, it emits no `0x81` at all and only the take-over burst. A
station in a two-console session runs `0x11aec0` once per clone id, ids 1 then 2 and 3.

### The second publisher and its mode word

`0x11aec0` has two callers. The trade state machine calls it once, during state 3, for clone id 1.
Clone ids 2 and 3 come about 3.2 seconds later from a different subsystem and a different per-frame
dispatcher: `0x13a780` -> `0x13a160` -> `0x886530` -> `0x344510` -> `0x349bf0` -> `0x349a90`, with
its own game object per pass, 0x1680 apart, one per party Pokemon. The state word is 8 by then and
never returns to 3.

`0x886530` runs every frame from the overworld onward. It reaches the publisher only through one
comparison on a mode word at `+0x8C` of its object:

    0x886ed0  ldr  w8, [x19, #0x8c]
    0x886ed4  sub  w9, w8, #1
    0x886ed8  cmp  w9, #2
    0x886edc  b.lo #0x886ef8        1 or 2: the battle scene
    0x886ee0  cmp  w8, #3
    0x886ee4  b.eq #0x886f24        3: the publish arm
    0x886ee8  mov  w8, #8           anything else: park at 8

`0x344510` behind it is a one-shot: it returns early when `[x19+0x68]` is already non-null, and
otherwise allocates a 0x278-byte object and calls `0x349bf0`.

Three setters write that word, each six instructions over the same singleton indirection, loading the
object from `[singleton+0x288]`:

    0x7c4530   mode := 1
    0x7c4580   mode := 2, then 0x147c90 with w1 = 0
    0x7c45d0   mode := 3, then 0x147c90 with w1 = 0

None of the three setters is the target of a branch or appears in a vtable in the image, and none of
them runs: on a session traced from the overworld through to a settled trade, all three and
`0x5a733c` fire zero times on both stations while the mode word moves from 0 to 3.

The object is `0x886530`'s `this`, and its class's vtable is `0x15afa68`, whose slot 9 is `0x886530`.
The vtable is populated by relocations rather than stored in the image: the entries around `0xe13388`
are `(r_offset, 0x403, r_addend)` triples writing each slot, which is also how the three setters are
reached and why no branch or table in the image names them.

None of the class's eleven methods stores to `+0x8C`, so the mode word is written by a function that
takes the object as an argument. Of the 192 stores to `+0x8C` in `.text`, sixteen write a small
constant; after the four ruled out by tracing, none of the remainder writes 3. The value therefore
arrives in a register, and the writer cannot be found by scanning for an immediate.

On every capture against the retail console the only clone ids on the wire are 0 and 1. A station in
a session that works publishes ids 2 and 3 as well, and all three shapes for each.

### The sequence a take-over has to carry

A station that announces a clone allocates a sequence for it and stamps it on its own announcement.
`0x520c30` is the request side: it returns early when the clone's `+0x38` is zero, when `+0x110` is
already set, or when `+0xB0` and `+0xB8` are both non-null, and otherwise allocates that sequence into
`+0x10C` and enqueues the announcer. `0x520ce0` is the completion side, a separate function: given a
clone and a value, it unqueues the announcer and writes 1 to `+0x110` only when `+0xB0` and `+0xB8`
are non-null and `+0x10C` equals the value it was given.

That byte at `+0x110` is the gate's per-station term. The station entries the gate walks at `+0x250`
are the party clones, one per party Pokemon: `station[i]` is `partyClone[i]+0x38`.

The value reaching `0x520ce0` comes from the take-over, the `0x91` on the clone's types. A joiner in
a session that works echoes the clock the peer's announcement carried, where the announcement of its
own copy keeps its own clock:

    host   0xa1 clone type 4   00000cfe 01 2808ab      the sequence it allocated
    host   0xa1 clone type 1   00000cfe 01 2808ab
    joiner 0x91 clone type 4   00000cfe               echoed
    joiner 0x91 clone type 2   00000cfe               echoed
    joiner 0xa1 clone type 4   00000d21 01 2808ab      its own clock, the host's content
    joiner 0xa1 clone type 1   00000d21 01 2808ab

Measured against an emulated host with the take-over carrying the joiner's own clock instead: the
host allocated `0x1114b` for both party clones, the completion for party clone 0 arrived with
`0x1114b` and set its `+0x110`, and the completion for party clone 1 arrived with `0x111b0`, 101
milliseconds high, and was refused. One clone's term stays false, the gate at `0x11b080` returns
false forever, and the state word never leaves 4.

The sequence is per party clone and it is re-allocated. Over one stalled session an emulated host
stamped three on its announcements in the first 102 milliseconds, `0x1414f`, `0x1418f` and `0x141c7`,
0x38 apart each time, and then retransmitted the last unchanged for the remaining 200 seconds. Read
live, the two party clones held different values at the same instant: `0x1418f` on party clone 0 and
`0x141c7` on party clone 1, the second re-allocated at `0x520cb8` 16 milliseconds after the first
completed. A take-over echoing the value that was current when it was built is stale from the moment
the peer allocates the next one, so a take-over is owed once per sequence rather than once per clone.

With the take-over carrying the peer's sequence, a party clone's `+0x110` was set by a joiner's own
message for the first time: party clone 0 completed on `0x1418f`. With a take-over owed once per
sequence rather than once per clone, the peer's `0xa1` retransmits on clone type 1 fell from 1992
over 200 seconds to 3, and it published its own copy on clone type 2 carrying real content, which no
run against a console or an emulator had produced before.

A peer retransmits that publish about ten times a second, and each of ours is answered with another
of its own: 1981 each way over 200 seconds, where the reference pair exchanges 31 in total. The
exchange is nonetheless what keeps the peer satisfied. Answering only the first and acknowledging the
rest stops the peer publishing at all and returns it to re-announcing, with a fresh sequence on every
retransmission: 1082 distinct sequences over one run against three when the publishes flow.

A peer's retransmitted announcement does not repeat its sequence, and the reason it re-announces at
all is the `0x82` in the take-over burst. `0x520c30` is the request side: an inbound `0x82` makes it
enqueue an announcer and allocate the next sequence. Answering each re-announcement with the whole
burst therefore mints one sequence per burst, and the pair can trade bursts and allocations about
thirty times a second without ever converging. A station in a session that works allocates none,
because nobody sends it a second `0x82`.

Answering a re-announcement with the two `0x91` take-overs carrying the new sequence, and nothing
else, took the sequences a host allocated over one run from more than 1200 to four, and its `0xa1`
retransmits on clone type 1 from 1230 to three. It is still not what a joiner does; see the take-over
exchange below.

The value a completion matches against `+0x10C` is not the one the take-over carried. Over one run a
host announced `0x14688`, `0x146bc` and `0x1472d`, the joiner echoed each within a millisecond, and
the completion that was refused carried `0x146f0`, which appears in no message either station sent.
The allocator steps by about 0x34 between announcements and `0x146f0` is one step past the value that
was allocated, so both numbers are the host's own and the take-over's clock does not decide the
comparison.

`0x520c30` allocates when the clone's `+0xB0` or `+0xB8` is null. Those two are not fields but
`sub+0x08` and `sub+0x10` of the announcer embedded at `clone+0xA8`, the links of an intrusive list,
so a null pair means the announcer is not in the element's announce list. `0x51e790` links and
`0x51e810` unlinks. Both clones of a station in a session that works arrive linked and nothing is
allocated; where a party clone arrives unlinked, the allocation happens and the completion that
follows is refused.

`0x91` on clone type 2 is the negative acknowledgement. `0x520d30` handles it and `0x520ce0` handles
the `0xa2`; the two are the same function over the same three preconditions, the clone's `+0xB0` and
`+0xB8` non-null and `+0x10C` equal to the value the record carries, and both unlink the announcer.
Only the `0xa2` path then writes 1 to `+0x110`. So a `0x91` that matches cancels the announcement
where an `0xa2` that matches completes it.

A joiner in a session that works sends one take-over per clone, at the first announcement of a clone
it does not own; sending one per sequence the peer announces cancels announcements that were never
meant to change hands. Measured over one run, three `0x91`s on clone type 2 for one clone
produced three unlinks, each inside the dispatch of one of them, the first included: the peer had
already linked and allocated for both party clones on the state-4 announce path at `0x517d9c`, about
27 milliseconds before the take-over arrived, so the first `0x91` matched like the others. Sending
only one does not avoid the cancellation and leaves the peer re-announcing without limit, 1792
retransmits over 180 seconds against three.

Each clone carries one announcement clock, not one per station. Whoever announces the clone stamps
its own mesh clock on the `0xa1`, and from that moment both stations use that number for the clone:
the peer's acknowledgement carries it, and the peer's own next `0xa1` for the clone carries it too.
`+0x10C` holds it. So the value a record must carry to match is the clock of the *other* station's
most recent `0xa1` for that clone, and it changes hands every time ownership does.

A joiner's `0x91` carries that value correctly, which is why it matches and cancels. Its `0xa2` must
carry the same value and does not: it carries the joiner's own mesh clock, round-tripped through the
peer's acknowledgement, so it misses. The record that matches is the one that cancels because only
one of the two is built from the peer's announcement.

### The take-over exchange a joiner runs once per clone

A take-over is an ownership transfer. The cancellation `0x520d30` performs ends the peer's
announcement because the clone now belongs to the joiner, which announces it again under its own
clock in the same frame. The reference exchange for the two party clones, with
the host's announcement at zero:

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

The joiner takes each clone over exactly once, at the first announcement of a clone it does not own.
Every later re-announcement is answered with a single `0xa2` carrying that announcement's clock, on
clone type 2 with the joiner's own station, payload `<clock> 00 00 00 02`. Over a whole session the
reference joiner sends six `0x91`s, all at those two first announcements, and none afterwards,
while the host re-announces continuously.

A second take-over against a re-announcement therefore cancels an announcement that was never meant
to change hands, and the peer re-announces without limit: 1792 retransmits over 180 seconds against
three. The clocks in the two records are correct in both cases; what is wrong is which record is
sent.

The record that drives a completion is the `0xa2`: each completion is preceded by one, and neither
of the two `f3` sends in a stalled window is followed by a completion. A station's own
announcer completes off the loopback of its own `0xa2` within about 6 milliseconds, which is why the
first party clone always succeeds. The second needs the joiner's, and the per-tick builder unlinks an
announcer about 30 milliseconds after it is linked. The joiner of a session that works sends **no** acknowledgement in its take-over burst. Measured on
the reference capture, with the peer's announcement at zero: the burst at +5 ms carries `0x82`, the
two `0x91`s, `0x84`, `0x81` and the two `0xa1`s and nothing else, the peer's own `0xa2` pair arrives
at +37 ms, and the joiner's single acknowledgement goes at **+72 ms**, as a reply. That session
completes.

So an announcer surviving long enough to be completed is not a matter of answering within about 30
milliseconds. A peer that never re-announces never unlinks, and the reference peer allocates no
sequences at all; the ~30 millisecond unlink is a property of a session already going wrong, and
moving the acknowledgement earlier does not address it.

### What the announce's destination field decides

The command header `0x51f820` lays out its last field, at `+0x10`, as a station bitmap. An 0x81
announcing a clone for the first time carries the whole mesh there, 0x0003 in a two-station session;
the two 0xa1s that follow it on clone types 4 and 1, and the announce repeated 35 ms later, carry the
peer alone, 0x0001. Both stations of a session that works do this.

A peer that receives the announce with the mesh bitmap answers with a pair of 0xa2s, one on clone
type 4 and one on clone type 2 carrying its own station. With the peer bitmap it answers neither and
keeps sending 0xa1 on clone type 1. The 0xa2 on clone type 2 is the only message that sets a
station's bit in `clone+0xA8`, so the destination field of the announce decides whether the gate at
`0x11b080` can ever see the acknowledged set fill.

The measurement that separates a session that works from one that stalls is the retransmit count of
`0xa1` on clone type 1. The two stations of a session that works send nine each over the whole
session. A peer whose announcement is taken over at every re-announcement sends one about every
0.12 s for as long as the session is held, over a thousand in 150 seconds from the retail console
and from an emulated host alike, and its game sends nothing. The same peer, against a joiner that takes each clone
over once and answers a re-announcement with one `0xa2` carrying that announcement's clock, sends
nine ("The take-over exchange a joiner runs once per clone").

Every clone message is built through one function, `0x51e3d0`, the protocol object's ninth vtable
slot; its fourth returns 0x73. Thirteen call sites build the messages, eight with a literal type
byte: the 0xa2 on clone type 2 at `0x51cbb8`, the 0x81 at `0x51e92c`, the 0xa2 on clone type 3 at
`0x51cdd4`, the 0xc1 at `0x51c9e4`, the 0x82 at `0x51c60c` and `0x51cd5c`, the 0xe3 at `0x51ad2c`
and the 0xf3 at `0x51ef18`. The game holds three clone objects over one element, two of type 1 at
`game+0x90` and `game+0x1710` and one of type 4 at `game+0x1258`; the clone type in a message is a
message field and does not map one to one onto them.

The handlers in `main`: `0x51ab20` CloneProtocol::vfunc9, the per-element receive; `0x51c100` the
protocol's receive dispatch, whose jump table `0xf7673c` on (type - 0x11) separates the clock
messages from the command messages and whose second table `0xf76800` on (type - 0x84) reaches the
command path; `0xf769c4` indexes the structure by the high nibble and `0xf769e4` the clone type.
`0x51b010` is the reply state machine, jump table `0xf76674` on (type - 0x21), and `0x51b1d0` the
clock-driven retransmit scheduler. The serializers are `0x51f9b0` clock request, `0x51fab0` clock
reply, `0x51fbd0` participate, `0x51f820` the command header, `0x51f4c0` ClockAndCount. A message
whose count at [0xC] does not exceed the last from that station is dropped (`0x51c1e0`). Element
offsets: +0x34 station, +0x40 state, +0x50 clock, +0x7a0 send time, +0x32c result.

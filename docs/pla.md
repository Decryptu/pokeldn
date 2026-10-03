---
title: Legends Arceus
nav_order: 8
has_children: true
---

# Legends Arceus

Pokemon Legends: Arceus (2022, title id `01001f5010dfa000`) is a native Switch title with Pia
statically linked into `main`. A host built here has completed trades with a retail console.

Addresses are offsets into the decompressed `main` of update 1.1.1, as `tools/switch/nso_read.py`
lays it out (text `0x0..0x32a5690`, rodata from `0x32a6000`, data from `0x401a000`).

## The wireless layer

| | value |
|---|---|
| Pia header version | 11, the wiki's Pia 6.16 to 6.23 band (Sword 4, BDSP 9, GBA app 15/16) |
| header size | 0x1C |
| GCM tag on the wire | 8 bytes, truncated from 16 |
| LDN passphrase | Sword/Shield's, the `HGhG` spelling (the wiki's `HGHG` row is wrong) |
| Pia game key | `p1frXqxmeCZWFv0X`, as Sword/Shield and Scarlet/Violet |
| LDN local communication id | `0x01001f5010dfa000`, the title id |

The game key and passphrase sit in rodata at `0x3985308` and `0x3985319`, NUL-terminated. The LDN
setup at `0x2c1e684` takes the local communication id in `x3` (the `mov`/`movk` run at `0x264082c`)
and installs the game key at `0x2c1e880`.

The header initializer at `0x6f0744` stores the magic `0x32AB9864` at object `+8` and `0x0b` at
`+0xc`; the validator at `0x6f07d0` checks the magic, `(byte & 0x7f) == 11` and packet length minus
0x1C below 0x5a5. The packet buffer is at `+0x30` (capacity 0x5c0), the length at `+0x5f8`; the copy
assignment at `0x6f0878` fixes each field's size:

    wire  object  size  field
    0x00  +0x08   4     magic 0x32AB9864, big-endian
    0x04  +0x0c   1     0x80 (encrypted) | version (0x7F) = 11
    0x05  +0x0e   2     destination variable id
    0x07  +0x10   2     source variable id
    0x09  +0x12   2     packet id
    0x0b  +0x14   1     footer size
    0x0c  +0x15   8     AES-GCM nonce
    0x14  +0x1d   8     AES-GCM tag, truncated from the 16 the object holds
    0x1c                ciphertext, then the footer

The footer is outside the encryption. The encrypt path `0x6f09f4` subtracts the footer size,
0xFF-pads to the block size, encrypts from buffer `+0x4c`, writes the tag to `+0x1d` via the AES-GCM
entry `0x6e68d0` with tag length 8 (`mov w4, #8` at `0x6f0b24`), then ORs `0x80` into the version.

## The receive path, for a breakpoint

    0x6ff6d8   nn::pia::local::LocalInputStream::vfunc4, the socket read
    0x6f07d0   the header validator (five callers; 0x6ff6fc is the input stream's)
    0x6f0b84   the packet decrypt, through the GCM entry at 0x6e6aac; failing here is key, IV or tag
    0x6f09f4   the packet encrypt
    0x7015b4   LdnBackgroundProcessJob::WaitConnected, the step body a stalled joiner sits in
    0x70c304   LdnProtocol vfunc18, which that step requires to return 0

## The gate a joiner stops at

The predicate `0x6f63fc` reads two endpoint slots on the LdnProtocol object, `+0x98` and `+0xb8`
(0x20 bytes each: a 16-byte address at `+8`, a native u16 port at `+0x18`):

    0x6f0ee4(a)     -> set: port non-zero and address not the sixteen zero bytes at 0x3972091
    0x6f0f48(a, b)  -> equal: same port, same sixteen address bytes
    0x6f63fc(obj)   -> 0 unless both are set, then 0x6f0f48's answer

With a joiner connected both hold the console's own address and Pia port and it returns 1; the slots
are zero only between a teardown and the next join. This gate does not stall a joiner.

## What a message is routed by

The dispatch key is the packet's source variable id: a message from a station missing from the
registry is skipped before its protocol is consulted, and variable ids re-roll every session. Message
flag `0x01` means "skip the source variable id check", for a message sent before the peer knows the
sender; `bin/pla_host.py` sets it on both of its probes.

## The Net Protocol, measured

A console hosting its own network opens the exchange with `NetUpdateNetworkConnectionStatusMessage`
(protocol 0x2C, type 0x11). It matches the wiki's 6.16 to 6.39 layout, and its network id is the one
derived from the advertised SSID:

    01 11 002a          header version 1, type 0x11, payload size 0x2a
    00000002            sequence id
    eb6f                host variable id, a fresh value every session
    ac56011000020000    host constant id, ldn_constant_id of 02:00:ac:10:56:01
    000000004f264487    network id, the low four bytes being crc32(ssid[1:16])
    01                  is network open
    0002                number of stations
    00                  is migrating host
    ...                 two NetStation entries

The NetStation is 21 bytes at this band, where 6.39 has 22:

    +0x00  1   host migration state
    +0x01  1   host migration ranking
    +0x02  1   one byte where 6.39 has two, disconnection candidate and kicking
    +0x03  18  station address: 16 bytes of address, then a big-endian u16 port

Both entries carry port 12345, ranking 0 for the console and 1 for the joiner.

A console hosting a trade sent no Session (0x98) message and left the join request unanswered in
every captured session where the request was addressed to its variable id (see below); it asked the
joined station to take the host role instead:

| joiner behaviour | console |
|---|---|
| answers 0x11 with the 0x12 ack | 0x11 again with a fresh sequence id and `is migrating host` 1, then `01 40 00 00` (a bare `NetStartHostMigrationMessage`) about twice a second |
| sends the join request, never answers 0x11 | the same 0x11 every 0.5 s, then `is migrating host` set, then `01 40 00 00`, then the network dropped (measured: 8.6 to 10.1, 13.5 to 14.1 and 16.8 to 17.5 s after association) |
| answers with `NetUpdateNetworkHostMessage` | keeps repeating 0x40 |

A searching console asked its joined station to take the host role in every captured session where
the join request was dropped (table above). Seated with the request to destination 0, an emulated
console hosting its search either ran the game (a trade completed) or, with the request held 4.5 s
after its first 0x11, sent Session type 7 naming the joiner its successor 0.02 s after the station
list, in 4 of 4 seats ([Joining a console's network](#joining-a-consoles-network)). The new host
completes the migration by creating a network on the same code: the console drops its own network
(3 to 6 s after asking, measured), joins the new one and trades as joiner. `bin/pla_join.py` leaves
the seat on the first 0x40 and runs `bin/pla_host.py` on the same code and channel (`--take-host`,
on by default).

Each Net message has a named header class with a serializer. `NetUpdateNetworkHostMessageHeader`
(`0x6fe03c`): u64 at wire +4, u64 at +0xc, u16 at +0x14, size 0x16, big-endian. The 0x11 header
(`0x6fd9dc`) maps object +0x0c, +0x10, +0x18, +0x20, +0x28, +0x2a to wire +4, +8, +0xa, +0x12,
+0x1a, +0x1b. `nn::pia::session::ClusterPacketWriter` (0x732264 to 0x7336e8) writes Session messages
inline.

A console hosting a search hands the host role away by leaving. `Session::LeaveAsync` starts
`LeaveSessionJob`, whose DisconnectNetwork step (`0x72c9dc`) calls the network facade's slot 15; on
the network host that starts `NetDestroyNetworkJob` (`0x7069d0`) with host migration whenever
`NetProtocol+0x248` is set, and the constructor `0x6f48fc` sets it to 1 (`0x6f4a14`), its only
writer. The job sends Net 0x11 with a new sequence id and `is migrating host` 1 (`0x6f6af0`), waits
up to 4000 ms for every 0x12 (`0x706b34`), then sends `NetStartHostMigrationMessage` (`0x6f7674`)
every 300 ms until it is the only station or a deadline passes: 4000 ms after a fully acknowledged
0x11, 2000 ms after one that timed out (`0x706df0`, `0x706e98`). Then it destroys the LDN network,
and the station still on it inherits the host role. Over fourteen seats of `bin/pla_join.py` the
first migrating 0x11 came 8.3 to 10.3 s after the seat, repeated for 4.0 s, then the 0x40 for 2.0 s.

The console creates the mesh as a full mesh host (`CreateSessionJob`, no wait). A joining console
sends its Session join request to header destination 0, from its own variable id. The host's
`ClusterPacketReader` gate `0x744644` (called through vfunc `0x98`, `0x731edc`, at `0x743ec0`)
looks up a unicast packet's source variable id among its stations (`0x744718`, manager vfunc
`0x48`) and drops the packet when none matches (`0x7447a8`); a packet to destination 0 or 1 with no
footer, or from source variable id 0, skips the lookup. A join request addressed to the host's
variable id from a joiner not yet registered is therefore dropped after its decrypt, before the
Session dispatcher. Sent to destination 0, it draws the join response and the type-5 station list.
On an emulated console hosting a search, a joiner seated that way that did not send its data
exchange record saw the console leave with migration about 10 s later and return to its search with
no error shown.

## The packet crypto

| | |
|---|---|
| session key | `AES-128-ECB(game key)` over one block of the network SSID |
| network id | CRC-32 of the SSID with its first byte dropped, `ssid[1:16]` |
| GCM IV | `u32be(network id XOR source IP)` then the header's eight nonce bytes |
| header nonce | a per-packet counter, big-endian |
| tag | the first 8 bytes of the GCM tag, in the header |

`0x70d61c` derives the session key: it repeats a seed shorter than sixteen bytes (`0x10 / len` at
`0x70d66c`) and encrypts one ECB block under the game key at `LdnProtocol+0x238`. Crypto mode 0 at
`LdnProtocol+0x234` leaves the key all zeroes.

`nn::pia::local::LocalOutputStream::vfunc3` (`0x711710`) builds the IV: `0x6ed380` writes the
big-endian XOR at `IV[0]`, then the header's eight nonce bytes go to `IV[4]`. The sender increments
the nonce per packet and writes it through `0x6ed360`. The GCM crypto setting is `{mode +0, IV
pointer +8, IV length +0x10, key pointer +0x18, key length +0x20}`: mode 1, IV 12, key 16.

`pokeldn/ldn/crypto.py` runs the same derivation for the whole 6.16 to 6.42 band.

## The protocols above the packet

Pia 6.16 to 6.30 keeps the 5.29 to 5.45 ids below the session layer and replaces the station and
mesh protocols with one Session Protocol. The ids changed again at 6.32:

| protocol | 5.29-5.45 | 6.16-6.30 | 6.32-6.40 |
|---|---|---|---|
| Net | absent | 0x2C | 1 |
| RTT | 0x58 | 0x58 | 3 |
| Unreliable | 0x68 | 0x68 | 5 |
| Clone, atomic to clock | 0x74-0x77 | 0x74-0x77 | 6-9 |
| Reliable | 0x7C | 0x7C | 10 |
| Broadcast reliable | 0x80 | 0x80 | 11 |
| Session | 0x94 | 0x98 | 13 |
| Monitoring data | 0xA4 | 0xA4 | 15 |
| Station, mesh, sync clock, local | 0x14, 0x18, 0x1C, 0x24 | absent | absent |

`pia_connect.py` (Net, Session, RTT at 6.32) fits this band with the ids renumbered;
`station_protocol.py` and `mesh_protocol.py` implement protocols absent here.

The console's join request lists its protocol versions:

    Net 0x2c v0   RTT 0x58 v3   Unreliable 0x68 v1   Clone 0x74 v0   Clock 0x77 v0
    Reliable 0x7c v2   BroadcastReliable 0x80 v3   0x81 v3   Session 0x98 v0   Monitoring 0xa4 v0

### The Session join request

A 115-byte Session type-0 message from `ClusterPacketWriter`: the type byte, a protocol count, the
ten `(id, version)` pairs above, then:

    +22  4   random, fresh on every repeat; Scarlet seeds it from the system tick
             (`docs/sv.md`, The Session join request)
    +26  8   source constant id, ldn_constant_id of the console
    +34  2   zero
    +36  2   source variable id, the joiner's own, fresh per session
    +38  1   NAT mapping
    +39  1   private-IPv6 flag
    +40  32  identification token, all zero on a codeless join
    +72  1   address kind, 0 for IPv4
    +73  4   source station address, IPv4
    +77  2   source station port, 12345
    +79  8   destination constant id, the host's
    +87  2   zero
    +89  2   destination variable id, the host's, `00c6`
    +91  1   player count, 1
    +92  1   a flag, 1
    +93  22  one player record: id `00..01 00..00` (two big-endian u64, 1 and 0), a big-endian u32
             name length of 1, a kind byte of 1, the name, a single space

A location id on the wire is 12 bytes: big-endian u64 constant id, two zero bytes, big-endian u16
variable id. Message flags are `0x01` on every repeat. `pokeldn.ldn.pia6.build_session_join`
reproduces the 115 bytes (`tests/test_pla_session_v11.py`).

### The Session join reply

The joiner parses the ack at `0x737534` and the join response at `0x7379c0`, dispatched from the
receive loop `0x7353a0` through the type table at `main+0x3973f19`. Each compares four ids and drops
the message silently on a mismatch: a host echoes the request's destination ids as its own and its
source ids as the console's.

The ack is Session type 1, 25 bytes: the type byte, the host location id, the console location id.
It sets `JoinMeshJob+0x69` and extends the join deadline `job+0x80` by 8000 ms; it completes nothing.

The join response is Session type 2, 43 bytes:

    +0x00  1   02
    +0x01  1   protocol id 0x98, read only when status is 3
    +0x02  1   Session version, read only when status is 3
    +0x03  1   status, 1 is the accept path
    +0x04  8   unread on the accept path
    +0x0c  12  host location id, four-field compare
    +0x18  12  console location id, four-field compare
    +0x24  1   route byte A, stored to the self station +0x90
    +0x25  1   route byte B, stored to +0x91
    +0x26  1   station index, sets bitmap bit [+0x788][index]
    +0x27  2   join order, big-endian u16, stored to +0xf8
    +0x29  2   sequence id, big-endian u16, stored to +0xde

The assignment fields are stored unvalidated (the console's writer `0x736cec` puts route `00 01`,
index 1, join order 1 for a first joiner). Status 1 sets `JoinMeshJob+0x68` and stops the request
repeating (about sixteen times a window). The completion flag `JoinMeshJob+0x7c` is set by the type-5
update `0x738740` once one whose sequence reaches `+0x29` is applied; the joiner answers with a
13-byte Session type 6: type byte, console constant id, two zero bytes, sequence.

### The type-5 station-list update

`0x7404a8` reassembles the update before `0x73897c` reads it; one fragment carries it all. The
seven-byte fragment header is the type byte, big-endian u16 sequence, fragment count, fragment index
and big-endian u16 offset. The buffer is seeded with type and sequence, so the payload starts at the
host constant id and the offset is 3. The reassembled body:

    +0x00  1   05, the reassembly byte
    +0x01  2   sequence id, big-endian u16
    +0x03  8   host constant id, big-endian u64
    +0x0b  4   host variable id, a [0000, u16] big-endian u32
    +0x0f  1   station count, at most 0x18
    +0x10  n   IPv6 bitmap, (count + 31) / 32 * 4 bytes, little-endian u32 words, bit i set for an
               IPv6 station
       ...     station entries

Each station entry, read by `0x739050`, in its IPv4 form:

    +0x00  8   constant id, big-endian u64
    +0x08  4   variable id, a [0000, u16] big-endian u32, the low half passed to the admit
    +0x0c  4   IPv4 address
    +0x10  2   port, big-endian u16
    +0x12  1   route byte A
    +0x13  1   route byte B
    +0x14  1   station index
    +0x15  2   join order, big-endian u16
    +0x17  1   NAT mapping
    +0x18  1   private-IPv6 flag
    +0x19  32  identification token
    +0x39  1   player count
    +0x3a  1   participant count
    +0x3b  ..  player records, each a 16-byte id, a big-endian u32 name length, an encoding byte, and
               the name

An IPv6 station carries an 18-byte address in place of the six bytes. The host is route `00 00`,
index 0, join order 0; the first joiner `00 01`, 1, 1. The player record is the join request's.
`0x738bc0` updates or creates each station by constant id, then sets `JoinMeshJob+0x7c` and sends the
type 6. A joined console then runs RTT, Clone Clock and the Stream Broadcast Reliable stream.

## Sustaining the mesh

A joined console leaves when the game's Matching step times out, 10.2 s after its join request,
unless the 0x81 data exchange completes first ([The game's reader and the pre-handler
phase](#the-games-reader-and-the-pre-handler-phase)). RTT (0x58) is 11 bytes: kind, eight-byte timestamp,
two-byte target; a kind-1 echo with target 0 is accepted.

Stream Broadcast Reliable (0x81) carries the `pokeldn/ldn/reliable5.py` sliding window: the
9-or-13-byte header, then application data or, with the application-data flag clear, a bulk ack of
`2 + 21 * count` bytes. The ack's leading type byte has only bit 0 read; each 21-byte entry is a
station byte, a big-endian u16 acknowledgement id, a big-endian u16 and a 16-byte mask. The consumer
(`BroadcastReliableSlidingWindow` vf13 `0x742730`) reads the entry at its own station index and
requires its station byte to equal the sender's index: a host acking a joiner at index 1 sends at
least two entries with every station byte 0. The id and mask follow [Acknowledgement](#acknowledgement).

The consumer stores each entry's second halfword at `[window + 0x528 + 2 * station]`
(`0x742828..0x742830`), sets `[window+0x4b8]` on type bit 0, and applies the id through the 0x7c
window's `0x74f0ec` (`0x742880`). The send path vf11 `0x742304` drops from its destination bitmap
every station whose halfword is `0xffff` or at or above the window base, or whose slot is empty
(`0x74238c..0x74242c`), and hands it to the ack sender `0x74ea00`: nothing unless `[window+0x4b8]`
is set; an empty bitmap clears it and stamps `[window+0x4c0]`; otherwise an AckMessage, sequence
`0xffff`, length `2 + 21 * count` (`0x74eb64..0x74eb94`), one entry per occupied station
(`0x74eba0..0x74ec2c`, serialised by `0x74ec80`, `0x743160`). The halfword only gates
acknowledgements, never retransmission. A console's 0x81 application message carried sequence 1 in
every captured join (30), so a host acknowledgement names `ack_id 2`; a host still acknowledges one
past the highest sequence received.

The console opens its stream with an INITIALIZED data message (flags `0x0f`, seq 1) and a second
one; its ack, about once a second, carries a host-stream id that climbs while the host is silent. Host data
with the destination bitmap bit of the console's station index (bit 1, count 2) is applied; the
wrong bit is dropped at the sender-station check.

### The silent-station check

The Session start `0x729d3c` copies the startup setting's `+0x28c` into `SessionProtocol+0xd8`
(`0x72a098`) with no lower bound (Z-A's has a 4000 ms floor), and passes `+0x290` to the send-silence
limit (`0x746fe4`: negative fails with 0x10407, 0 becomes 1000 ms). Every update `0x73564c` lists each
station in state 2 whose last packet (`ClusterStation+0x88`) is older than `[SessionProtocol+0xd8]`
ms, on the host and on a joiner alike. Once the first entry is 3000 ms old (`0x735364`), `0x7359ac`
acts on the list: the host hands each station to `KickoutManageJob` (`0x73cad4`); a joiner whose list
names the host treats the host as gone (`0x735b28`). The setting's `+0x28c` reads 10000 ms
(`w9 = 0x2710` at `0x72a09c` on an emulated console hosting a search), as in Z-A. A silent host on
the box screen drew the partner-left message about 13 s in: 10000 ms and the 3000 ms grace.

## The game's reader and the pre-handler phase

The game polls its reader at `main+0x2ca4f30` (`0x741494`) (365 calls in one measured window): two
loops, 0x7C and 0x80, share one handler table. Host data on 0x81 never reaches it. A message's first eight bytes are a two-u32 handler key; the
matched handler receives the rest, and an unmatched key is discarded.

At the trade search screen the handler table is empty (`ldr x8, [x19+0xd0]; cbz x8` after the read),
so every message is drained unread. `0x2ca5264` registers handlers at flow step 0x1e, never reached
in a session that times out; the handler-array pointer is nulled on leaving the menu. The reader
loops ticked about 2.5 times a second while idle, measured. The game's nine Pia call sites resolve only 0x68,
0x7C and 0x80 (three read loops, four send paths); the 0x77 clock traffic is Pia's own.

The ten-second leave is the failure branch of the game's matching sequence, above the Pia mesh join;
the trade scene is its success branch. The trade flow is `0x13d5bfc`, step at `[flow+0xa4]`,
jump table `0x397c118` for steps 0x15 to 0x22. Step 0x17 calls `0x26bdcac`, which builds the sequence
at `[manager+0x70]`; step 0x18 polls it through vtable slot 9 (`0x12b3290`), true when the
outstanding-child counter `[request+0x70]` is zero. The flow reads no network, session or mesh field.
Step 0x1e registers the handlers (`0x13d5f94 -> 0x26d8c2c -> 0x2bcb8c8 -> 0x2ca5264`). The sequence's
steps, by the name strings `0x26bdcac` pairs with their functors:

    LoginRelayServer     looked up before the sequence is built; a missing one returns false
    Matching             the first child, the one a timed-out session waits on
    DataExchangeStart
    OnCancelDataExchange
    OnSuccess            the trade scene
    OnFailure            event 8, flow step 0x23 (table `0x397c134`), the leave
    OnCancel
    Cleanup

Step 0x18's second gate is `0x13de870`, `[obj+0x7c] == 1` on the persistent network-menu object,
set by the case-0 update `0x13de888` when the current page (`[obj+0x88]`; ViewTop `[obj+0x90]`
`0x13de950`, ViewAlert `[obj+0x98]` `0x13de9d8`, ViewInMatching `[obj+0xa0]` `0x13dea28`, built by
`0x13de3cc` from the `netm` layouts) reports result 1 in its `+0x5bc`. Only player input writes it: 1
from InputDecide and InputBack (`0x13dc7b4`, `0x13dc7ec`, `0x13dd3ec`, installed at `0x13dc0a4`,
`0x13dc1a0`, `0x13dc9a0`), 2 and 3 for `button_00` and `button_01` (`0x13ddcb4`), which set
`[obj+0x7c] = 2` and `[obj+0x84]`. The first gate, the child counter, reads 0 at `0x13d6130`.

The Matching child's start `0x26c5288` stores the data-exchange object at `[matching+0x118]` and
starts a stopwatch at `[matching+0x120]` on the OS tick (`0x26c539c`). Its update `0x26c6988`
completes once at least two stations' records have arrived and every occupied slot has one
(`0x26c6b70`, `0x26c6c04`); otherwise it compares the elapsed seconds with the literal 10.0
(`fmov d1, #10.0` at `0x26c6a94`, measured 10.2 s after the join request) and fails the request with
`net_contents::p2p::ErrorLeaveAnyone` (vtable `0x416c628`, built by `0x26c6d30`). The failure runs
`0x13d654c -> 0x13d6384 -> 0x2c43d78 -> 0x2ca0a10 -> Session::LeaveAsync (0x72a6dc)`, then the
Error 7 dialog. `0x26d4ae8` is in the result callback `0x26d4aa0`, which tests the error against
`gflnet::request::Error::Timeout`, then `ErrorLeaveAnyone` (`0x26d4e04`), then
`gflnet::npln::NplnResult`; every error passes it. The only `Error::Timeout` producer is the watcher
`0x2bdb754`, armed by `0x2bda8cc` in two WaitMember steps: 25000 ms (`0x2bda24c`) and
`3000 + rand % 1000` ms (`0x2c491b8`). The completion callback is `[request+0x90] -> 0x26d69e8 -> 0x26d6a88`.

The Matching child waits for a two-round data exchange on Stream Broadcast Reliable (0x81), ports 0
and 1, after the mesh join: each station opens the stream with a type-0x0f message, acknowledges with the 44-byte
`0000002c ffff` message under flags 0xa0 ([Joining a console's network](#joining-a-consoles-network))
and sends one 74-byte type-0x1f content record carrying a 64-byte payload beginning `484b6264`. Matching completes on the
peer's second-round record (17 ms after it, measured), enqueuing `OnSuccess` (`0x26d5f64`); a host
that only acknowledges the stream gets the timeout. A joining console opens its stream unprompted and
sends its content record after the host's (86 ms after it, measured); a hosting console sends its
record first, on the joiner's stream open. The trade box (a 399-byte type-7 record) crosses later on
0x7c.

A message ends where its payload ends; this band does not align messages to four bytes (5.27-5.45
does), and only the packet pads ([Reading and writing a packet](#reading-and-writing-a-packet)). A
host answering the console's stream open bundles two messages in one packet: the record on port 0,
then its own stream open on port 1 under a header naming size, protocol and port and inheriting the
message flags. `bin/pla_host.py` sends that bundle once per join; lost on the air, the console shows
Error 7 at the 10.2 s timeout.

| protocols | header destination | footer |
|---|---|---|
| Session, Clone Clock, Reliable | the peer's variable id | none |
| RTT, Stream Broadcast Reliable | mesh destination 0x0001 | the recipient's variable id, plaintext |

A 0x81 message addressed to the peer's variable id in the header never reaches the game. The 64-byte
content payload is identical in both directions of a same-save pair except for the sender's station
index; which bytes are per-player is unknown.

## The game's reliable channel

After the data exchange the trade flow reaches `0x13d5cac`, which tests `[net+0xb8] > 1` on the
game's network object. The object advances on what the game reads on 0x7c: state 0 to 1 through
`0x26d9170`, 1 to 2 on `[net+0x78]`, set by the receive handler `0x26da310` on selector 1 (jump table
index 1, `0x26da3a4`).

The dispatcher `0x2ca4a88` matches a message's eight-byte key against each channel's `+0x6c` and
hands over the body. Two channels exist, both registered through `0x2bcb8c8`: key `00 00 00 00 00 00
00 00` for the trade box (`0x26d8c2c`), `01 00 00 00 00 00 00 00` for the phase protocol
(`0x26d7aa0`).

Port 0 and port 1 are two Reliable instances, registered in the protocol sequence at `0x2bba180` as
`0x7c000000` and `0x7c000001` (stream broadcast: `0x80000000`, `0x80000001`). Handles go in a table
at `0x4308a80` indexed by port (`0x4308a84` is 0x7c port 1). `0x2ca4a88` reads port 0 of 0x68, 0x7c
and 0x80; port 1 of 0x7c is read through the table by the channel table below.

Both ports open with a `reliable5` stream (no destination bitmap, to the peer's variable id,
sequence 1, message-start, message-end and initialized flags); each station acknowledges its peer's
message with one entry and sends the same message back on the same port:

    port 0    key eight zero bytes      body 0100        the host opens it
    port 1    b9 01 01 b9 02 b9 02 00 00 01              the joiner announces the zero key open

### Acknowledgement

`ReliableSlidingWindow` (vtable `0xc5b4d98`) builds its acknowledgement in vf12 `0x74ee1c`: the
receive window's `+0x50` as the id, one bit per entry held past it in a sixteen-byte mask
(`0x74ef18..0x74efb8`), the mask empty while `[window+0x54]` is set. vf13 `0x74efbc` applies one: it
parses the AckMessage (`0x742da0`), drops it unless the payload is `2 + 21 * count` bytes and the
entry's stream byte equals the window's `+0x36`, and calls `0x74f0ec(window, station, ack_id, mask)`
at `0x74f09c`. A send entry is 0x5d0 bytes, sequence at `+0x24`, per-station pending bitmap at `+0x2c`:

| entry sequence | the acknowledging station's pending bit |
|---|---|
| below `ack_id` | cleared (`0x74f274`) |
| equal to `ack_id` | kept |
| above `ack_id` | cleared when mask bit `seq - ack_id - 1` is set, for offsets up to 0x7f (`0x74f280..0x74f2a8`) |

| `ack_id` | effect |
|---|---|
| 0 | nothing (`0x74f0fc`) |
| below the window base | sets `[window+0x4b8]`, returns (`0x74f17c`, `0x74f2d0`) |
| `base + count` (count `[window+0x32]`), one past the last sent | releases everything |
| beyond `base + count` | passed to `[vt+0x30]` with `0x20000000` (`0x74f18c..0x74f1c0`), vf6 `0x74f2e8`, a bare `ret` in both window classes: ignored |
| `0xffff` | applies the whole window (`0x74f104..0x74f11c`) |

The comparison is the 32-bit difference of two 16-bit ids: after 65536 messages on one stream an id
past the window reads as below it.

The id is cumulative: acknowledging n+2 releases n whether or not it arrived. The console
acknowledges one past the contiguous run, held entries in the mask: four little-endian words (memcpy
at `0x742f00`, read per word by `0x74f2a0`), bit `seq - ack_id - 1` being bit n of the 128-bit
little-endian integer (`pokeldn.ldn.reliable5.build_mask`). A retail console acknowledges host 0x7c
data within tens of milliseconds (17 to 67 ms measured).

The receiver moves its window base on every message's lowest-pending field, acknowledgements
included, before reading the flags (`0x74c250` stores it at `[x0+0x20]`; the base `+0x18` walks empty
slots to the first occupied one, `0x74c2f0..0x74c2f8`; flag dispatch `0x74c3ac`); a lower value moves
nothing (`0x74c25c`). A lowest pending declared past an unacknowledged message makes its resend land
below the base and be dropped. A retail console's acknowledgements declare less than their id (ack 8,
lowest pending 6).

`bin/pla_host.py` and `pokeldn.pla.joiner` use `pokeldn.ldn.reliable5` (`SendWindow`,
`ReceiveWindow`): keep each 0x7c message until acknowledged, resend after 0.4 s under the same
sequence id and a new nonce, declare at most their own lowest unacknowledged sequence as lowest
pending (a hosting console's port-0 numbering has run one ahead of the joiner's in captures, and
declaring more walks its base past the joiner's unsent phase 6), acknowledge one past the contiguous run with the mask,
and deliver in order once. The joiner's 0x81 messages resend every 1 s. A console's first 0x7c message on a
port carries sequence 1 (66 of 66 recorded ports).

The console resends 0x7c and 0x81 data alike through `0x74c9c8` (ticks: 0x81 `0x7419ec`, 0x7c
`0x74a27c`/`0x74a2f8`): every entry up to 127 past the base with a non-zero pending bitmap `+0x2c`
and a passed deadline (`0x74cd10..0x74cd80`; 0x81 via `0x742194`, to pending stations only), then
deadline = now + 33 ms + 1.4 x the largest round-trip (`0x74d06c`, float `0x3fb33333`; 33 ms at
`0x74a784`), with no retry limit on the count `+0x14`. A pending bit clears only on an in-window
acknowledgement (`0x74f1f4..0x74f204`) or the station leaving (event 1, `0x7411cc` to `0x74b528`); a
station joining zeroes every deadline (`0x74b358`). A console resends forever to a peer that answers
only with ids past the window.

## The channel table on port 1

Port 1 of 0x7c carries the channel table: each station announces which handler keys it has open,
and a station sends on a key only after its peer has announced that key open.

The dispatcher's initialisation `0x2ca36f0` builds a 0x298-byte object (vtable `0x41997d8`), port
byte `+0x70` = 1, kept at dispatcher `+0x20148`. Every frame the poll `0x2ca82d0` receives from 0x7c
port 1 into `0x2ca9800` and runs the sender `0x2ca83dc`. Two tables of 0x18-byte entries, each an
eight-byte key at `+0x00` and a station bitmask at `+0x08`:

| table | holds |
|---|---|
| `+0xa0` | the station's own channels, with the byte at entry `+0x10` set while the channel exists and the bitmask naming the stations already told |
| `+0xd8` | the peer's channels as announced, the bitmask naming the stations that announced the key open |

The sender runs first in each poll (`0x2ca8310`) while the dirty flag `[obj+0x90]` is set
(`0x2ca83fc`), walking the own table per station bit: an existing channel with the bit clear is
announced open and the bit set; a destroyed one with the bit set (`0x2ca86c4`) is announced closed
and the bit cleared. A channel's destructor calls interface slot 1 `0x2caa12c` with its key
(`0x2ca3168..0x2ca3178`; table slot 13 `0x2caa0d4` is the same body), clearing `+0x10` and setting
the dirty flag.

The receiver `0x2ca9800` runs from the poll at `0x2ca83a8` once per pending port-1 message
(`0x2ca8398..0x2ca83d4`), resolves the sender's station index through the session's `[vt+0x38]`
(`0x2ca9854`), drops on 0xfd and aborts on 2 or more (`0x2ca9df0`). Per key:

| peer table | open | close |
|---|---|---|
| holds the key | the station's bit ORed into the mask (`0x2ca9a6c`); a repeated open changes nothing | the bit ANDed out (`0x2ca9ae4`); with neither station bit left, the entry erased by moving the tail down and `[obj+0xe0] -= 0x18` (`0x2ca9b14`) |
| lacks the key | an entry appended with the station's bit | an entry appended with a zero mask |

No arm calls into the game or writes outside the peer table. The collector `0x2ca8f58` (every poll,
`0x2ca8318`) erases zero-mask entries (`0x2ca9060..0x2ca90c8`) and empties the table when no bit is
set in `[obj+0x98]`; the station-leaving path `0x2ca90e0` (from `0x2ca4a48`) clears the station's
bit in `[obj+0x98]` and in every mask. Nothing else clears a peer entry.

Creating a channel (`0x2bcb8c8` -> `0x2ca5264` -> constructor `0x2ca3024`, each the next's only
caller) stores the table's interface (`[dispatcher+0x20148]` + 0x68, vtable `0x41998c8`) at the
channel's `+0xb8` (`0x2ca30d0`, built at `0x2ca5acc`) behind a weak reference at `+0xa8` (use count
`+0xc` tested before each call), then calls interface slot 0 `0x2caa0cc` (`sub x0,x0,#0x68; b
0x2ca9dfc`, table slot 12) with its key: `+0x10` clear is set (`0x2ca9e78`), set returns
(`0x2ca9e74`), missing is appended as `{key, 0, 1}` (`0x2ca9e90..0x2ca9ec0`); the first and third set
the dirty flag (`0x2caa034`). (`stp xzr,xzr,[x23,#0xb8]` at `0x2ca3c6c` zeroes the table's own
`+0xb8`.) The peer-table queries:

| function | slot | answers |
|---|---|---|
| `0x2ca9218` | interface 2 | the own table holds key K |
| `0x2ca92e0` | interface 3 | slot 10's test, the station given by handle and resolved through `[vt+0x38]` |
| `0x2ca93d4` | interface 4 | slot 10's test, by station index |
| `0x2ca958c` | interface 5 | `0x2ca9448` on the table object |
| `0x2ca9360` | table vtable `0x41997d8` slot 10 | the peer table holds K with station bit i |
| `0x2ca9448` | table slot 11 | the stations that announced K are every station but this one |

Every channel sender calls interface slot 3 through `+0xb8` with its key at `+0x6c` and sends only on
yes: the phase senders through `0x2ca34e0` (`0x26d7e00` in `0x26d7d8c`, `0x26d7ef8` in `0x26d7e84`),
the trade-box senders inline at `0x26d9200`, `0x26d92f0`, `0x26d950c`, `0x26d9688`, `0x26d980c`
(selector 5) and `0x26d9a1c`. The peer table gates port-0 sends too, each on its own key; this is the
wait the trade screen shows while a host is silent on port 1. Interface slots 2, 4 and 5 have no call
site through `+0xb8`.

The table pointer lives at `[dispatcher+0x20148]` (the last field; allocation `0x20150`,
`0x2bcac00`), used only in the dispatcher: init `0x2ca3d24`, destructor `0x2ca3f88` (in `0x2ca3f48`),
station join `0x2ca4774` (`0x2ca4574` from `0x2bcb2b8`: bit ORed into `[+0x98]`, dirty set), station
leave `0x2ca4a38` (`0x2ca90e0`), the frame's poll `0x2ca5020`, channel creation `0x2ca5284` (table
slot 8 `0x2ca91cc`). The other copy is each channel's `+0xb8` (interface slots 0, 1, 3). No other
peer-table reader was found: vtable `0x41997d8` is referenced only by `0x2ca3c18` and `0x2ca7f2c`,
`0x41998c8` by nothing; calls through `+0x48/+0x50/+0x58` in `0x2ca3000..0x2cab000` are only
`0x2ca92c0`, `0x2ca9340` (slot 10), `0x2ca9490` (session); outside calls into `0x2ca6000..0x2cab000`
reach only `0x2caa960..0x2caafec`; slot 9 `0x2ca9264` has no caller.

A message is the game's tagged serialisation: an unsigned integer below 0x80 is its own byte; tags
0x80, 0x81, 0x82, 0x83 prefix a little-endian 1, 2, 4, 8-byte value (`0x2661ec4`, `0x26619cc`,
`0x2661f78` write u32, u64, u16). The size table `0x397dfcc` gives 0x84 to 0x87 the same widths,
0x88 four bytes, 0x89 eight, 0xb5 to 0xbf one. 0xb9 opens a tuple, followed by the field count.

    b9 01              a tuple of one field, the list
    NN                 the number of entries
    per entry:
      b9 02            a tuple of two fields, the key and its state
      b9 02 LO HI      the key as two u32, low word first
      01 | 00          1 open, 0 closed

A console sends three during a trade:

| message | meaning | when |
|---|---|---|
| `b9 01 01 b9 02 b9 02 00 00 01` | the trade box key open | with the port-1 open, on reaching the trade step |
| `b9 01 01 b9 02 b9 02 01 00 01` | the phase key open | after the confirmation, when `0x26d7aa0` creates the phase channel |
| `b9 01 01 b9 02 b9 02 01 00 00` | the phase key closed | once the trade is written |

`pokeldn.ldn.channel_table` builds and parses these. The host answers each open with its own, once
per key, and leaves a close unanswered: a close sent back erases the console's peer entry for the
phase key (harmless within the trade, since nothing polls the peer table), and the standing entry
serves the next trade ([A second trade in one session](#a-second-trade-in-one-session)).

## The trade box

With both channels open, the game's messages cross on port 0 behind the zero key. The receive handler
`0x26da310` reads a selector and a counter, switches through the byte table at `0x397e388`, and
drops anything above 7.

    1   ready                0x26da3a4   sets [net+0x78], what step 0x20 waits on
    2   showing a Pokemon    0x26da3f0   stored at [net+0x98] by 0x26da1d8, nothing else
    3   showing no record    0x26da430   -> 0x26d93c8
    4   offering a Pokemon   0x26da3b0   stored at [net+0xb0] by 0x26da23c, phase 0xbc := 3
    5   confirmed            0x26da43c   counter check, -> 0x26da2c0
    6   withdrawn            0x26da458   state 4|5 := 3, phase 0xbc := 2, counters moved
    7                        0x26da49c   counter check, phase 0xbc := 5

The handler aborts unless its fourth argument equals `[net+0x88]`, the partner. The port-0 open body
`01 00` is the ready (selector 1, counter 0), owed once per session.

`0x26d9458` (only caller `0x10fb200` in `0x10fb198`, itself called only at `0x110a010`) sends
selector 3 with no body when its record is null (`0x26d94a0`) or its species is 0 (`0x2b5d3a4` ->
`0x2b6849c` on `[pk+0x98]`, the first halfword of the block `0x3984e57` puts first), else selector 2
with a 0x178-byte body from `0x2b65514` (`0x26d9554..0x26d9570`). The record is
`0x11207f8(ui, box, slot)` (`0x1109fa0..0x1109fac`), the slot copied into `[ui+0x1660]` by
`0x111da04` (`0x11208e4..0x1120910`, `0x111fc18..0x111fc4c`): the cursor on an empty slot sends
`03 00`. Receiving 3, `0x26d93c8` replaces `[net+0x98]` with a fresh 0xb8-byte `0x151dc70` object,
which the tick `0x26d9094` never reads.

Selector 6 takes back an offer (state 3: own selector 4 sent, `0x26d95d4` requires 2, `0x26d9718`
writes 3) or a confirmation (state 4: own selector 5, `0x26d9788` requires 3, `0x26d9838` writes 4).
Its sender `0x26d9898` refuses in states 2 and 5 (`0x26d98ac`: `cmp w8,#2; ccmp w8,#5,#4,ne`), sends
counter `[net+0xf8] + 1` (`0x26d9918`), then clears `[net+0xc0]`, sets state 2 (`0x26d9a54`), raises
`[net+0xf8]` and `[net+0xfa]` and puts a phase of 4 or 5 back to 3. The receive arm `0x26da458`
stores the counter to `[net+0xfa]`, raises `[net+0xf8]`, clears `[net+0xc0]`, sets phase 2, puts a
state of 4 or 5 back to 3, and sends nothing: an echoed 6 un-confirms the console.

Selectors 2 and 4 carry the same body: 2 when a station enters the box, 4 when the player offers.
Only 4 moves the phase. A host answering an offer with a showing leaves the console with an empty
partner hexagon and no error; `pokeldn/pla/trade_box.py` mirrors the selector.

The body is read by `0x26dac6c` (selector), `0x26662fc` (counter) and `0x26dacbc` (record); 0xbc
introduces the record, which `0x26da3b0` tests for by hand.

    0x00  1   the selector
    0x01  1   the counter, 0 on both record-carrying selectors
    0x02  1   0xbc
    0x03  1   0x81
    0x04  2   the record's length, 0x178
    0x06  376 the record

390 bytes of payload under a nine-byte header, no destination bitmap, flags 0x07 (application data,
message start, message end; no initialized bit, no zlib bit), at sequence 2.

The message depends on the save alone (identical across hosts and session keys): a capture replays.

The record is the Gen-8 entity (`pokeldn.gen8` header, LCG, block permutation and 16-bit checksum)
with 0x58-byte blocks: 0x168 stored, 0x178 in the party. `gen8.BLOCK_ORDER[(ec >> 13) & 31]` is
applied as it stands when decrypting and inverted when encrypting. The checksum cannot tell the two
apart; the names can: read directly, the nickname is at 0x60 (second block) and the trainer name at
0x110 (fourth). Read inverted, both land one block early. A captured record decrypts to a level-70
Azelf: species 482 at 0x08, experience 428750 at 0x10 (slow curve at the level at 0x168); its trainer
id at 0x0c and trainer name are the player id and name the data exchange carries.

## Confirming the trade

Trade it sends selector 5 and the counter `[net+0xf8]` on the zero key. The sender `0x26d9770`
requires `[net+0xb8] == 3` (own offer sent) and sets it to 4. The consumer `0x26da2c0` sets the phase
`[net+0xbc]` to 4 and, when `[net+0xb8]` is already 4, clears `[net+0xc8]` and allocates into it: the
second station to confirm goes on. Selectors 5 and 7 drop a counter below `[net+0xfa]` (`0x26da440`,
`0x26da4a0`).

After the confirmation the console announces the phase key open on port 1 (no initialized flag) and
sends nothing on it until the host announces it too; otherwise the trade screen waits at phase 5.

## The trade object's own state machine

`[net+0xb8]` is the state step 0x20 tests; the tick `0x26d9094` moves it:

    0     if [net+0x90] is set, 0x26d9170 -> state 1
    1     once [net+0x78] is set, one 64-bit store of 0x200000002 puts the state at 2 and the
          phase [net+0xbc] at 2 in the same instruction
    3, 4  while [net+0xc0] is set: read the stopwatch at [net+0xc8], and once [net+0xd0] is past
          1.5 seconds and the phase is 4 or 5, 0x26d9254 sends selector 7 and the state becomes 5
    5     no case. The object is finished

State 5 (offered, both confirmed) leaves the save untouched; the job below carries the trade out.

## The job that carries the trade out

The scene polls `0x26d9ea0`: `[net+0xd8]` non-null and that job's state `+0x10` in 6..10.
`0x26d9a90` builds the job in the sub-state 7 arm from `[net+0xa0]`, `[net+0xa2]`, `[net+0xa4]`,
`[net+0xa8]` and the offered record `[net+0xb0]`: 0x140 bytes, constructed at `0x26dc08c`, vtable
`0x416c8f8`, started at `0x26dc564` with eight callbacks, state 0 to 1 by `0x26dc2c8`. Its update
`0x26dc71c` switches on `state - 1` through `0x397e390` (base `0x26dc758`; 0xf and above return). The
executor `[job+0x130]` is built by `0x26db724` -> `0x26dd39c` (vtable `0x416c918`, id `[+0x70] = 3`).

| state | arm | does |
|---|---|---|
| 1 | `0x26dc774` | executor vf `+0x40` `0x26dd488` (the two records' species against eight ids `0x1e3..0x1ed`), `[job+0x1d]` from its result, then `0x26d7d8c(obj, 3)` (`0x26dc97c`); state 2 only when that send returns true |
| 2 | `0x26dc798` | `0x26d7e5c(obj, 3)`: the host's `02 03` |
| 3 | `0x26dc7b4` | executor vf `+0x50` `0x26dd910` until it returns false: the trade restriction set and saved ([The trade restriction](#the-trade-restriction)) |
| 4 | `0x26dc7e4` | send phase 6 |
| 5 | `0x26dc800` | wait for `02 06` |
| 6 | `0x26dc81c` | `0x26db9f8`: executor phase `[+0x68] = 1`, then vf `+0x58`: the trade applied, the restriction cleared |
| 7 | `0x26dc82c` | wait for executor phase 3 (`0x26dba0c`), then send `0x0b` (state 8), or state 9 with `[job+0x1d]` clear |
| 9 | `0x26dc85c` | count `[job+0x20]` down, then send `0x0b` |
| 8, 10 | `0x26dc758` | wait for `02 0b` |
| 11, 12 | `0x26dc888`, `0x26dc898` | executor phase 4, then wait for phase 5 and send `0x0e`; phase 4 runs `0x1048690` -> `0x298f2f4`, which calls `nn::fs::Commit` (`0x298f318`) |
| 13 | `0x26dc8c0` | wait for `02 0e` |
| 14 | `0x26dc8e0` | the success functor `[job+0x30]`, or with `[job+0x18]` set the failure one `[job+0xb0]`; state 0xf |

State 9's count is set once in the job init `0x26dc2c8`: a xoroshiro128+ draw of 0 to 300
(`0x26dc400`, global state `[[0x4279680]+0xd8]`) plus 2 (`0x26dc340`), 2 to 302 frames. The success
invoker `0x26db864` writes trade-object `[+0xb8] = 6`; the failure invoker `0x26db8ec` writes 7.

State 2 calls `0x26d7e5c([job+0x28], 3)`, which requires `[obj+0x70]` non-null and `[obj+0x90]` set, and returns `[obj+0x92] ==
n`. The sender `0x26d7e84` writes both, only after a successful send: it tests `0x2ca34e0([obj+0x70],
[obj+0x88])`, sends through `[obj+0x70]`'s vtable +0x40 to `[obj+0x88]`, records the phase at `+0x92`
and sets `+0x90`.

A failed gate retries on the next update (`bl 0x26d7d8c; tbz w0,#0,0x26dc908`; `0x26dc908` returns
with `[job+0x10]` unchanged): a send refused by the channel table holds the job at the sending state
(a refused `01 03` at state 1, a missing `02 03` at state 2). A job at state 1 or 2 has no timeout of
its own: the only countdown is state 9's `[job+0x20]` (`0x26dc85c`); no clock is read under
`0x26d7d8c`, `0x26d7e5c`, `0x26d7f4c`, `0x26dd488` or `0x26dc6b0`; the executor tick `0x26dba38` does
nothing at phase 0 (`0x26dba68..0x26dba80`); the only tick read, `0x265d420`
(`nn::os::GetSystemTick` at `0x265d440`), comes from state 3.

The other exit is the cancel request `0x26dc640` (`[job+0x14]`, `[job+0x18]` := 1), reached only
through `0x26d9e90` from the scene's monitor (`0x1109ef4`) and leaving mode 9 (`0x110b7ac`, after a
stopwatch at `[scene+0x278]`, `0x110b794..0x110b79c`). The scene sits in mode 5, step 9 for the job's
life (started at `0x110ad34`, step 9 set at `0x110ad3c`); the step-9 arm `0x110abb8` waits for
`0x26d9354` (`[+0xb8]` through `0x397e380`, 6 to 5, 7 to 0) to read 5. The pre-switch calls
`0x26bc6c4`, `0x10fb234` (`0x26d93b4`) and `0x1126408` are not handed the scene and cannot end the
wait. The monitor `0x1109d00` runs every update before the mode switch (`0x1109a98`), mode 5 only,
dispatching on the step through `0x3979c68` (base `0x1109d20`):

| step | arm |
|---|---|
| 0 to 5, 8 | `0x1109d4c`: an error or the partner gone |
| 6, 7 | `0x1109e48` |
| 9 | `0x1109e84` |
| 10 to 12 | nothing |
| 13 | `0x1109ec0` |

At step 9 the monitor reads `0x26d9ea0` (`0x26dc65c`). With the job in 6 to 10, an error from
`0x110977c(1)` gives mode 8; otherwise an error (`0x1109ee4`) cancels the job (`0x1109ef4`) and gives
mode 7 (`0x1109ba8`), a message then the leave. `0x110977c` reports an error with no session or no
`0x110ccf0` (`0x11097a4`, `0x1109810`), a non-zero `0x2bbb590`, or (argument bit 0) the partner gone
per `0x110994c` (session `[vt+0xb0]` false or station count `+0x28` below 2,
`0x11099fc..0x1109a04`). A held job waits until the session fails or the host leaves
([Leaving](#leaving)).

The console has nothing outstanding to resend while it waits: the host must resend any of its eleven
answers lost on the air (the port-0 open, two channel opens, the showing, the offer, selectors 5 and
7, four phases).

A cancel is taken in the states `0x26dc9a4` allows, `0x3ff7 >> state & 1`: 0 to 2 and 4 to 13. The
cancel processor `0x26dc6b0` (every frame from `0x26dc670`) sets `[executor+0x6c] = 1` via
`0x26dbe98` and the job to state 0xf, request 2. The executor tick then, at phase `[+0x68]` below 2,
calls vf `+0x48` `0x26dd5f8` and sets `[+0x6c] = 3` (`0x26dbcf8`); at phases 2 to 4 it finishes the
save first (`0x26dbd44..0x26dbd90`). The job goes to state 0xe, request 3, failure callback. vf
`+0x48` writes only with `[executor+0xb0]` set (`0x26dd610`, `0x26dd614 cbz`), stored 1 only at
`0x26ddc6c` in vf `+0x58`, state 6. A job cancelled at state 1 or 2 writes nothing and saves nothing
(executor init `0x26dd43c`: phase 0, `+0xb0` 0, save request `+0xb8` 0); an emulated save is
byte-identical after such a cancel.

## The trade restriction

The trade restriction is a u64 count of minutes in save block `0x96993D83`, field `+0x70` of the
object at `[game manager+0x2b8]` (manager through `[0x4279560]`, accessor `0x1048f94`; vtable
`0x40f2048`, constructor `0x102500c`). Its methods:

    0x102518c  clear
    0x1025194  set
    0x102519c  decrement, stopping at 0
    0x10251b0  read
    0x10251b8  non-zero

The registration `0x1024d5c` (slot `0x40f2098`) binds three fields to save blocks, found by
`0xff0ee8`'s binary search over 0x30-byte entries by u32 key (`0xff0f3c..0xff0f70`):

| field | block | type |
|---|---|---|
| `+0x68` | `0xAFA034A5` (key at `0x3978f78`) | a bool (`0xfddf30`) |
| `+0x70` | `0x96993D83` (key at `0x3978f7c`) | a u64 (`0xff0ee8`) |
| `+0x78` | `0x24E0D195` (built at `0x1024f30`), 0x2F2 bytes | `0x1024ee4` |

PKHeX's `BlankBlocks8a.cs` agrees on the sizes. In saves `0x96993D83` is type 11 and 0,
`0xAFA034A5` a false bool, `0x24E0D195` a zero flag byte then the record most recently traded in.
Every writer of the count (whole-text call index; no pointer slot holds a method):

| site | caller | value | when |
|---|---|---|---|
| `0x26dd9a0` | executor vf `+0x50` `0x26dd910`, job state 3 | 10 | after the partner's `02 03`, before either record moves |
| `0x26ddaf0` | executor vf `+0x58` `0x26ddaa0`, job state 6 | 0 | the trade is applied |
| `0x26dd704` | executor vf `+0x48` `0x26dd5f8`, the cancel | 10 | only with `[executor+0xb0]` set, which `0x26ddc6c` does at state 6 |
| `0x26bd5d0` | the ticker `0x26bd434` | minus 1 | every 60 s |

After setting 10, vf `+0x50` gets a save request from `0x12aff48`, arms it with
`0x265d420(request, [executor+8], 3)` (`0x26dd9e8`), and holds state 3 until `0x265d460` reports
done; that runs the save-data state machine `0x10457e4` (`0x265d668`; steps `0x1048354`,
`0x1048558`, `0x10485c0`, `0x1048628`, `0x1048690`, `0x10486f8`, one reaching `nn::fs::Commit` via
`0x298f2f4`). These are the only save requests in the trade code. A trade stopped before job state 3
draws no restriction; one stopped between state 3 and the save after state 6 leaves 10 in the save.

The countdown is registered by `0x277c530` in the system list at `0x42eced0` (calls at `0x277cc0c`,
`0x277fbb0`; `0x2789df4` builds it, constructor `0x26bd300`, vtable `0x416c2f0`, update `0x26bd430`
-> `0x26bd434`). Its state at `+0x58`:

    0  count non-zero -> 2                                          0x26bd4bc
    2  count zero -> 0; else snapshot the count to +0x70 and start a stopwatch at +0x60
       (nn::os::GetSystemTick, ConvertToTimeSpan, 0x26bd534..0x26bd544) -> 1
    1  count changed -> 2; elapsed / 1e9 >= 60.0 (0x26bd5b4) -> decrement (0x26bd5d0) -> 2

10 is ten minutes of the game running, on the OS tick: clock settings play no part and time with the
game closed is not counted. The ticker runs in the field: the restriction clears ten minutes of play
after it was set (a retail console left in the field after a host dropped between phases 3 and 6
reopened Link Trade within 667 s of phase 6).

`0x13d67b0` is the non-zero method's only caller (`0x13d67e8..0x13d67f0`). In Link Trade's
partner-choice menu, `0x13d55fc` and `0x13d56ac` (inside `0x13d55dc`, called by `0x13d53c0`, asserts
`[x0+0xa4] == 3`; and `0x13d5648`, called by `0x13d53dc`, `0x13d5808`) return `0x500000001` while the
count is non-zero, `0x300000001` otherwise, `0x400000001` when `0x13d65c0` is false. The menu update
`0x13d5344` switches on `[obj+0xa0]` (byte table `0x397c105`); a result `(n << 32) | 1` moves it to
state n (`0x13d5404`). The decide callback `0x13ddcb4` writes 2 for pane `button_00` and 3 for
`button_01` (FNV-1a-64 of the names, basis `0xcbf29ce484222645`), routed by state 0 to `0x13d55dc`
and `0x13d5648` (`0x13d5590..0x13d55a0`); by pane name, `button_00` is likely "Someone nearby". Each
state's `common/net` label (table `0x397c158`) goes on `pane_T_info_00` via `0x13dbe68`:

| result | state | label | text |
|---|---|---|---|
| `0x500000001` | 5 (`0x13d59a4`), then back to 0 | `matching_win_03` | cannot link trade now, the last connection was interrupted; wait a while (French: "Votre connexion a été interrompue lors de votre dernier échange...") |
| `0x300000001` | 3, then matchmaking in 6 | `matching_win_06` | the warning that an interrupted trade blocks trading for a while |
| `0x400000001` | 4 | `matching_win_02` | at least two tradeable Pokemon are needed |

## The phase protocol, and the message only a host sends

The job announces phases on key `01 00 00 00 00 00 00 00`, registered when the job is created. The
announcing object keeps three pairs, a flag and a halfword each:

    [obj+0x94] / [obj+0x96]   the phase this station has announced, written by 0x26d7d8c
    [obj+0x98] / [obj+0x9a]   the phase the peer has announced, on receiving selector 1
    [obj+0x90] / [obj+0x92]   written by 0x26d7e84, and on receiving selector 2

The two senders differ only in the selector they write; the receive handler `0x26d7f90` mirrors
them: selector 1 fills the peer pair, selector 2 the third, selector 0 aborts. The message is the
selector and the phase, a byte each while the phase is under 0x80. The state-2 arm's
`0x26d7e5c(obj, 3)` waits for the third pair to hold 3.

Selector 2 is the host's to send. `0x26d7e84` is reached only behind `[obj+0x78]`, written once at job
creation by `0x26d7aa0` from a predicate comparing the station against the session's host station. A
joiner never sends selector 2, so its job leaves state 2 only on the host's. A host that only mirrors
selector 1 leaves the trade screen waiting with both Pokemon shown and nothing outstanding on the
wire. The setup has five exits that leave `[obj+0x78]` zero: a null argument, a null cast,
`[vtable+0xd8]()` not returning 2, a station count at `+0x28` other than 2, a null station slot.

Every message a station originates on a port, mirrors included, takes the next id of its own
sequence. A mirror reusing the peer's id collides once the counts diverge and is acknowledged but
discarded.

## The completed trade

The console announces 3, 6, 0xb and 0xe in turn; the host answers each with selector 2 and the same
phase, which moves the job on:

    <-  0x7c p0  01 03      ->  01 03   the mirror     ->  02 03   the host's
    <-  0x7c p0  01 06      ->  02 06
    <-  0x7c p0  01 0b      ->  02 0b
    <-  0x7c p0  01 0e      ->  02 0e

The third pair reads 1 and 3 once the first `02 03` arrives (240 ms later, measured). After the animation the box names the
host's player as the original partner. Eight save files change: `main`, `main2`, `backup` in both
slots, both ExtraData files.

The console then sends a fresh selector 2 (whatever the cursor is on), which the host answers with a
showing, and the phase key close `b9 01 01 b9 02 b9 02 01 00 00`, which it does not answer.

Measured once with a retail Legends Arceus joining `bin/pla_host.py`, from the console's `01 0e`:
the animation started at about 2.8 s, the received Pokemon appeared at about 28.5 s (hand-pressed
marks, up to 2 s late), and the console's next port-0 message (`00 02`, the box again) came at
37.2 s, about when the player had control.

## A second trade in one session

A session carries any number of trades: after a completed trade the scene resets the trade object
and returns to the box with the session up.

After a completed trade the scene calls `0x26d8fd0(net)` at `0x110aa04` (only when `[net+0xb8]` is
6) and sets step `[scene+0xb4]` to 0xc. The reset:

    0x26d8fec  [net+0xa0], [net+0xa2] cleared           job inputs
    0x26d8ff4  [net+0xa8], [net+0xb0] released          shown and offered records
    0x26d903c  0x200000002 to [net+0xb8]                state 2, phase 2
    0x26d9044  [net+0xc0] cleared                       stopwatch flag
    0x26d9050  [net+0xd8] released through 0x26dade4    the job
    0x26d9064  32-bit zero to [net+0xf8]                both counters

`[net+0x78]` (the peer's ready) and `[net+0x88]` (the partner) are kept: the next round starts at
state 2 with no new selector 1. The scene's update `0x1109a68` (pointers at `0x3406990`,
`0x40fc090`) runs the monitor, then switches on the mode `[scene+0xb0]` through `0x3979c5e` (base
`0x1109b60`):

| mode | handler | what it is |
|---|---|---|
| 0 | `0x1109f00` | the box: cursor, showing, choosing Trade |
| 1, 2 | `0x1109b6c` | nothing |
| 3, 4 | `0x110a65c`, `0x110a694` | |
| 5 | `0x110a7f8` | the trade, by step (halfword table `0x3979c7c`, base `0x110a858`, steps 0 to 13) |
| 6 | `0x110b330` | partner gone, no error: a message, then mode 1 (`0x110b408`) |
| 7 | `0x110b468` | session error, job cancelled at step 9: a message, then mode 9 (`0x110b508`) |
| 8 | `0x110b54c` | session error at step 9, job in 6 to 10: a message, then `0x115e420(..., 1)` (`0x110b60c`) |
| 9 | `0x110b72c` | leaving: cancel the job (`0x110b7ac`), wait at least 3 s on the OS tick, finish |

After a completed trade, in mode 5:

    step 11  0x110a928  UI waits (0xc4cc88, 0x1127ab8, 0x110d8b0, 0xc6a788, 0x26bc6a4), 0x26d9eb0,
                        0x10fb2c4, 0x10fb414, 0x10fb164(..., 1) ([+0x161] = 1), 0x10fb178 (0x110a9e8),
                        0x1126408, 0x1126400, 0x26d8fd0 (0x110aa04), step 12
    step 12  0x110aae0  returns while 0x10fb170 ([+0x161]) is set, UI calls, step 13 (0x110abac)
    step 13  0x110ac80  waits for 0xc4cc88 and 0xc6a610, then 0x110acc4 b 0x110b9f0
    0x110b9f0           UI (0x1120ce0, 0x111fb5c or 0x11152b8, 0xc42438, 0xc4ba88, 0xc428b0), then
                        0x110ba44 str xzr,[x19,#0xb0]: mode 0, step 0

No callee of steps 11 to 13 reaches the session, the channel table or a send: the scene returns to
the box with the session up. Step 5's arm `0x110ac9c` shares the tail into `0x110b9f0`. `0x10fb178`
clears the box controller's valid flags `+0x164`, `+0x16c`, `+0x174` and tail-calls `0x26d93c4`,
which replaces `[net+0x98]` with a fresh `0x151dc70` object and sends nothing.

Mode 0 reads the cursor every frame (`0xc5294c` box, `0xc4bf2c` slot, `0x11207f8` record) and calls
`0x10fb198` at `0x110a010`, which sends a showing through `0x26d9458` only when the cursor tuple
differs from the one cached at `+0x168/+0x170/+0x178` or a valid flag is clear
(`0x10fb1a8..0x10fb1f0`), caching the tuple after a send (`0x10fb208..0x10fb220`); the cleared flags
cause the fresh selector 2 after a trade. Cursor moves reach the network only through `0x10fb198`.
Offering (menu result 0x19, `0x110a098`) runs `0x10fb25c`, selector 4 through `0x26d95ac`
(`0x110a24c`), and on success `0x110a260 mov w8,#5; b 0x110a148` enters mode 5 at step 0.

Every mode is entered at step 0 (`str x8,[x19,#0xb0]` at `0x1109abc`, `0x1109ac8`, `0x1109bac`,
`0x110a148`, `0x110a314`, `0x110ae14`, `0x110b408`, `0x110b508`, `0x110b9dc`, `0x110ba44`,
`0x110bd98`, `0x110c9f0`; `stp w8,wzr` with 7 at `0x11094dc`) except `0x11094a8`, mode 5 step 1 when
the box controller's `+0x160` is set (`0x10fb15c` at `0x110948c`).

The counter `[net+0xf8]` is zeroed only there and at `0x26d8c04`, raised only by a selector 6 sent
(`0x26d9a60`) or received (`0x26da468`), and serialised through `0x26d81fc` by every sender
(`0x26d91c8` selector 1, `0x26d92b8` 7, `0x26d94d4` 2 and 3, `0x26d9640` 4, `0x26d97d4` 5).

The next job is built by `0x26d9a90` from scene step 7 (`0x110ad34`, when `0x26d9354` returns 4) and
creates its phase channel with key 1 again (`bl 0x26d7aa0` at `0x26dc398`). Its phases are
immediates in `0x26dc71c`: 3 at `0x26dc978`, 6 at `0x26dc7ec`, 0xb at `0x26dc848` and `0x26dc874`,
0xe at `0x26dc8ac`. A second trade with no withdrawal repeats `05 00`, `07 00`, the phases and the
port-1 phase key open byte for byte; only the sequence ids differ, so a peer that answers each
distinct body once answers none of them.

If the host answered the console's close of the phase key, the second `01 03` waits in the gate
until the host announces the key open again: job at state 1, scene at step 9, no timeout, no
restriction.

A job held at state 1 or 2 shows `common/box` `msg_ui_box_p2ptrd_09`, "Communicating. Please stand
by..." ("Communication en cours... Veuillez patienter."), put up by the "Trade it" callback
`0x110c3d8` through the message helper (`[scene+0xc0]`, `bl 0x26bcc14` at `0x110c424`, label hash at
`0x110c408..0x110c418`), which sets step 6; the helper's close `0x26bcfc0` is called only at
`0x110a84c`, `0x110ac5c`, `0x110ace4`. `0x1128184(ui, 1)` turns on the cancel prompt (`InputCancel`,
`0x11281bc`), read only at steps 2 and 7 (`0x110ac00`, `0x110ad4c`).

## What a trade rewrites

A record traded in comes back as a showing when the cursor reaches it. A received record differs from
the one sent in these fields (23 bytes for a level-50 record sent with a level-70 party tail):

    0x006  2   the checksum
    0x092  1   the current HP, 235 sent, 192 stored
    0x0b8  26  the handling trainer's name, filled in with the receiver's own
    0x0d3  1   the handling trainer's language
    0x0d4  1   the current handler, set to 1
    0x0d8  1   the handling trainer's friendship
    0x16a  12  the six party stats, recomputed

Everything else is stored as it arrived; a met level above the level is kept. The friendship written
is the species' base friendship from the personal entry (50 for Gengar and Garchomp).

Each block start is `pokeldn.gen8`'s plus eight bytes per preceding block: nickname 0x60 (Gen 8
0x58), handling trainer name 0xb8 (0xa8), trainer name 0x110 (0xf8), party tail 0x168 (0x148). Inside
a block offsets follow the block: the first is Gen 8's except the moves (0x54 and PP 0x5c, where Gen 8
has 0x72 and 0x7a in the second block), the second Gen 8's plus 8, the third plus 0x10, the fourth
plus 0x18 with the ball moved to just after the met date.

`pokeldn/pla/trade_box.py` and `pokemon.py` reproduce a console's bytes.

## Choosing what to offer

The record a host offers is its own to compose. The game reads PKHeX's PA8, and every measured offset
agrees with it:

| offset | field | offset | field |
|---|---|---|---|
| 0x08 | species | 0x92 | current HP |
| 0x0a | held item | 0x94 | packed individual values |
| 0x0c | trainer id, 32 bits (the panel shows it modulo 1000000) | 0xa4 | growth values |
| 0x10 | experience | 0xac, 0xb0 | absolute height, weight (floats) |
| 0x14 | ability | 0xb8 | handling trainer |
| 0x16 | alpha bit | 0xee | version |
| 0x1c | personality value | 0xf2 | language |
| 0x20 | nature (Gen-3 table: 9 is Lax) | 0x110 | trainer name |
| 0x24 | form | 0x134 | met date |
| 0x26 | effort values | 0x137 | ball |
| 0x3e | alpha move | 0x138, 0x13a | egg and met locations |
| 0x50, 0x51, 0x52 | height scalar, weight scalar, scale | 0x13d | met level and trainer gender |
| 0x54, 0x5c | moves, PP | 0x159 | purchased move record |
| 0x60 | nickname | 0x15d | mastered moves bitmap |
| 0x8a | relearn moves | 0x168, 0x16a | level, six stats |

`pokeldn/pla/pokemon.py` holds the map as four tables. Across 47 captured records the alpha bit and
alpha move are set on the same three, which carry 0xff in 0x50, 0x51 and 0x52; the scale equals the
height scalar in all 47; 0x94 has the egg and nickname bits clear; every record carries version 47,
language 2, sanity 0 and affixed ribbon 0xff.

`pokemon.build` assembles a record from 376 zero bytes, writes the given fields over defaults every
captured record agrees on, and writes the checksum; unmapped fields stay zero. Against a console's
own level-68 Gengar it differs only in the fields chosen. Composed records (shiny with Gen-6 shiny
value 0, alpha, nicknamed, of species the save never held, every value from the game's tables)
trade in and display as sent. Stored, they differ from what was sent only in the
fields [What a trade rewrites](#what-a-trade-rewrites) lists; a tail carrying the stats the game
computes leaves 14 bytes changed (checksum and handler fields).

A received record whose encryption constant and personality value the save already holds is stored:
box block `0x47E1CEAB` held two with EC `0x444C4B50` and PID `0x2A694C4B` (slots 690 and 570), both
checksums good.

`bin/pla_host.py` processes each `(port, sequence id)` once, in order, and resends unacknowledged
answers. A showing comes on every cursor move, and a cancelled offer is re-offered as `04 01`.
The second trade repeats message bodies, so deduplicating by body would drop its answers.

### Mastered moves

The eight bytes at 0x15d are a bitmap over the 61 moves of the game's mastery list, in its order; a
species may master only those its personal entry permits (u64 at 0xa8). On the Pastures Change moves
screen a move draws the scroll when its mastery level (`mastery_la`, per species and form, learnset
format) is at or under the current level or its bit is set: on a level-13 Chimchar, Swift (20, index
10) drew it only with its bit set.

### The stats the game computes

`pokeldn/pla/stats.py` reproduces the stats a trade writes over the tail. Each stat is a growth term, rounded `(sqrt(base) * multiplier + level) / 2.5`, plus a base
term: `((level / 100 + 1) * base)` truncated plus the level for HP, `((level / 50 + 1) * base / 1.5)`
truncated with the nature at 110% or 90% for the rest. The multiplier is read from a table by the
growth value plus an individual-value bias (3 at 31 and above, 2 at 26, 1 at 20), the sum clamped at
10. Verified on twelve console-computed numbers at level 68, nature 14, Gengar's base stats:
273/210/199/322/345/220 for perfect individual values and growth 10, 239/136/121/322/304/133 for the
donor (individual value 22 and growth 9 also clamp to 10, so its speed is unchanged).

The absolute height and weight at 0xac and 0xb0 are the species average times
`(scalar / 255) * 0.40000004 + 0.8` per scalar, height alone for height and both multiplied for
weight, in 32-bit floats. Scalars 111 and 221 against averages 150 and 405 give 146.11766052246094
and 452.38031005859375, the floats a console's Gengar carries.

Base stats, gender ratio, ability, experience curve, average size, level-up learnset and PP come from
PKHeX's copies of the game tables: `personal_la` (0xB0 bytes an entry; 0x21 bit 6 marks a species in
the game, 264 of them), `lvlmove_la.pkl` (a 16-bit BinLinker archive of move halfwords then level
bytes), `MoveInfo8a`, `Experience`.

## The Clone Clock and Atomic protocols

This band splits the Clone family into separate protocols, unrelated to the 6.32 clone protocol:
Clone Clock 0x77 and Clone Atomic 0x74.

A Clone Clock message is 18 bytes: kind, sequence, big-endian u64 originate tick, big-endian u64
responder clock in milliseconds. Kind 0 is a request (ignored unless the receiver is master); kind 1
is the reply, which checks the sequence, computes an NTP-style offset and advances the state at
ClockProtocol `+0x5c` (0 reset, 1 requesting, 2 synchronised, 3 master, 4 parked). A joining console
parks in state 4, sends a few requests and waits. A host kind-1 reply echoing the sequence and
originate tick with the host's millisecond clock synchronises it and it stops sending.

A Clone Atomic message is 14 bytes: kind (0 announce, 1 commit, 2 ack), generation, big-endian u32
element index (below 33), big-endian u64 value. The element table is 33 slots of 0x18 bytes:
generation, state (0 empty, 1 pending, 2 awaiting-commit), u64 value, and at `+0x10` an
acknowledged-station bitmap written only by a matching-generation kind 2 from a known participant
(participant table at protocol `+0x78`; the host at station 0 reads 1 once joined). Only the trade
scene creates elements (local announce `0x6e1e48`); kinds 1 and 2 need one pending, and a host kind-0
announce draws a kind-2 echo that fills no slot.

## Reading and writing a packet

`pokeldn/ldn/pia6.py` speaks version 11; the message framing is 5.27 to 6.30's, read unchanged by
`pia5.parse_messages` (flag `0x01` marked a destination bitmap at 5.27).

The padding byte is 0xFF at every level. The message walk reads a presence byte of 0x00 as a one-byte
header inheriting every field from the previous message: zero padding makes the game parse a second
message, fail, and discard the whole packet (rejected at `0x74419c`). The console pre-fills its
encrypt buffer with 0xFF at `0x6f0af8`; `0x6e6cb0` sets the block size to 16.

`pokeldn/pla/` holds the passphrase (needed to read the advertisement), game key, local
communication id and `session_keys(ssid)`. `tests/test_pia6.py` pins the layout, the derivation
against `crypto.PiaCrypto`, both captured advertisements, and every constant read out of `main`.

## Hosting

`bin/pla_host.py` advertises the title, passphrase, scene id and link code;
`pokeldn.pla.build_advertise_data(code)` rebuilds a retail advertisement byte for byte (`app_version`
0, `security_mode` 1). The host authenticates every inbound packet with the session key from its own
SSID and prints each Pia message by protocol id.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/pla_host.py --keys PROD_KEYS \
        --code 00000000 --seconds 240

A console on the search screen alternates scanning as a station (it associates with a host found
then; its deauthentication, reason 3, ends the scan and is no rejection) and hosting under a new SSID;
measured, a cycle of about five seconds, one scanning and two to four hosting. An associated joiner stays silent until
the host sends the Net 0x2C connection request (`host_pia.build_net_probe`'s message at 6.32), every
500 ms until answered; `--no-net-probe` holds it back.

## Joining a console's network

A joiner owes a hosting console these messages, in a retail joiner's order (Net 0x50 from the
emulated host); `pokeldn.pla.joiner` sends them.

| the host sends | the joiner answers |
|---|---|
| Net 0x11 | Net 0x12 echoing the sequence id, message flags `0x11`, header destination 0; the first time, the Session join request (type 0), flags `0x01`, header destination 0 |
| Net 0x50 | Net 0x51 echoing the sequence id, header destination 0 |
| Session type 7 naming the joiner | type 8: the location id the type 7 names as target, then the host's own |
| Session type 5 | type 6: its own constant id, two zero bytes, the update's sequence |
| the first type 5 | the 0x81 stream open on port 0, `0f00000b 0001 0001 01 00000001 0000000000008000000000` |
| its 0x81 record on port 0 | the acknowledgement, its own record on port 1 (flags `0x1f`, sequence 1, bitmap `0x01`), then the key-zero open on 0x7c port 1, initialized flags |
| the 0x7c port-0 open, `0000000000000000 0100` | the same back, its own port-0 sequence 1 |
| a showing or an offer | its own, same selector and counter |
| selectors 5 and 7 | the same two bytes; after 7, the phase key open on port 1 |
| the phase key open | phases 3, 6, 11, 14 (selector 1), each after the host's answer, then the phase key closed |
| RTT kind 0 | kind 1, timestamp echoed, the requester's variable id in the last two bytes |

A retail joiner sent all 108 of its Net 0x12 to header destination 0. The reader gate drops one
addressed to the host's variable id: an emulated console then resent its migrating 0x11 every 0.5 s
for 4 s and sent its first 0x40 4.1 s after its type 7. Addressed to 0, the 0x11 went once and the
first 0x40 followed 0.10 s after the type 7 (4 of 4 seats); with no type 8 at all, 9.1 s.

The type 7 comes from `LeaveMeshWithHostMigrationJob` when the console's WaitMember (3000 +
rand%1000 ms, `0x2c491b8`) ends before the join request is accepted, as on Scarlet
([docs/sv.md](sv.md#what-decides-a-seat)); `bin/pla_join.py --join-delay 4.5` draws it. The console
resends it every second until a type 8 arrives. Its type-8 handler `0x739b08` takes only a 25-byte
message whose second location id is the console's own; `0x73f0a8` then sets the job's done flag
`+0xb0` when the first equals the target the job holds at `+0x68`:

    08 | joiner location id (12) | host location id (12)

A joiner sends its next phase once the host answers, after a few tenths of a second except across the
trade animation (several seconds).

A retail console hosting announces each phase with selector 1 before the joiner's arrives, then
answers the joiner's with selector 2, 0.02 to 0.04 s later (one retail seat). Only the selector 2 answers a phase. A
joiner that closed its phase key after sending its `01 0e`, on the console's own `01 0e` and before
its `02 0e`, never received the `02 0e`; leaving 5 s later, the console showed 2-AW7KA-0007, kept
its own Pokemon and held the ten-minute restriction ([The trade restriction](#the-trade-restriction)).
`bin/pla_join.py` closes the key on the `02 0e` and keeps the seat after a trade until the
console's player backs out, or `--hold` ends; `--hold-after-trade N` leaves N seconds after the last
queued trade. A later trade on the same seat repeats every step byte for byte, so the joiner forgets
the steps it answered once a trade completes and shows the next `--offer`. It repeats its 0x81 acknowledgement on ports 0 and 1 about once a second:

    0000002c ffff 0002 01 00000001       header: size 0x2c, lowest pending 2, bitmap 1
    00 02                                type 0 on the first, 1 on every later one; two entries
    00 0002 0001 00*16                   the host's stream: one past its sequence, then its sequence
    00 0001 0001 00*16                   its own stream

Later acknowledgements put one past the sequence in the first entry's second field too.
`tests/test_pla_joiner.py` plays a scripted host against the joiner; `tests/test_esp32.py` runs it
across two simulated boards.

## Reaching local trade on the console

    title screen, A -> Jubilife Village, the trading post -> talk to Simona (Trado in French), A
    -> "echanger des pokemon !" -> local rather than online
    -> the warning that an error temporarily restricts trading
    -> an eight-digit code
    -> "Echange en reseau ! Recherche d'un partenaire en cours..."

Both consoles enter the same eight-digit code before the search begins, as in Let's Go.

The minutes table at `0x397e1b8` (`30 30 60 60 120 120 180 180 240 240 360 360 480 480 960 960
1440 1440 2160 2160`) is the lost satchel's: `0x2686a0c` returns `max(0, table[count % 20] -
elapsed)` on the network clock (`0x265d180` -> `nn::time::StandardNetworkSystemClock::GetCurrentTime`),
called only by `0x266c740` and `0x266d580` beside the lost-bag DataStore strings (`CreateLBData`,
`ScanOtherData`, `ReturnLB`, `0x266d8dc..0x266dec8`). `0x129751c`, another network-clock caller,
compares elapsed seconds against 21600.

## The advertisement

Scanned from a console on the search screen:

| | |
|---|---|
| local communication id | `0x01001f5010dfa000` |
| LDN protocol | 1: AES-CTR advertisement, as Sword |
| scene id | 1 |
| advertisement frame version | 4 (GBA app 3, Sword 2) |
| accept policy | all |
| participants | 1 of 2 |
| SSID | 16 bytes, the session key's input |
| application data | 112 bytes |

The application data is the 0x5C system property block (`docs/ldn.md`, 6.16 to 6.41: system
communication version 21, application communication version 0, a sixteen-byte user password, player
limit enabled, one player, name size 1, encoding 1, name a single space), then 20 bytes carrying the
code in the clear:

    +0x00  16  the code as ASCII, NUL-padded
    +0x10  4   its length, little-endian

Code `0000 0000` gives `3030303030303030`, eight NULs, length 8.

### The link code in the advertisement

The user password is the same code, encrypted by Pia's password setter `0x6fc454`. With transport
encryption on (session `+0x230`) in mode 1 (`+0x234`), it fills a sixteen-byte buffer with 0xFE,
copies the NUL-padded code over it, and encrypts it in place with `0x6e68d0`: AES-128-GCM under the
key at session `+0x238` (the game key `p1frXqxmeCZWFv0X`, set through `0x6fc8a4`), no additional
data, tag discarded, and a four-byte IV taken from the key, `key[1] key[8] key[7] key[2]`
(`0x6fc4e4` to `0x6fc4fc`), here `1emf`. One GCM block is an XOR with a fixed keystream:

    password = KEYSTREAM XOR (the code's ASCII, NUL-padded to 16)
    KEYSTREAM = AES-128-GCM(key = p1frXqxmeCZWFv0X, iv = 1emf).encrypt(sixteen zero bytes)
              = e5ab19ed742b6d40885998bf968aa166

The keystream does not change with SSID, channel, code or game restart. `pokeldn.pla` has
`link_code_keystream`, `user_password`, `link_code`, and `parse_advertise_data` (checks the stated
code against the decoded password). The setter is Pia's, so every title of the band encrypts this way
([the wireless layer](ldn.md)).

## Retail

A retail console runs the same chain as an emulated one, with or without a link code, in both roles. A French save writes handler language 3 where an English one writes 2.
`--fresh-pid` re-sends a record the save already holds under a new PID and encryption constant.

On a Linux card whose monitor interface hands up decrypted frames still carrying the CCMP header and
MIC (TP-Link Archer T3U), `config/host.toml` needs `skip_encryption` and `accept_decrypted_ccmp`.

A console whose host restarted under it showed error 2318-0006 on its next search, before the trade
warning screen, with no restriction; leaving the trade menu and searching again recovered it. The host re-reads its offer file between offers; a flag change needs a restart.

## Leaving

A console quitting the trade runs `nn::pia::session::LeaveMeshJob`: it sends the Session type-3
leave request, waits 500 ms for the host's type-4 leave response, and sends again, four sends at
most, then leaves the network answered or not. The steps are SendLeaveRequest `0x73b898` (writer
`0x737ee8`, type byte 3 at `0x737f40`, call at `0x73b990`, deadline 0x1f4 ms at `0x73b9a8`),
WaitLeaveResponse `0x73bab8` (retry counter `[job+0x6c]`, given up past 3 at `0x73bbf0`) and
CompleteProcess `0x73ba54`.

    03 | u32 random | location id (12) | address kind | IPv4 (4) | port big-endian (2)
    04 | u32 random | location id (12)                          the response, 17 bytes

The location id is `pia_connect._location_id`'s (station constant, zero halfword, big-endian variable
id) and the address the station's own. The random word differs on every send, retransmissions
included. The address kind at `+0x11` is 0 in every captured leave; the handler reads 18 bytes of
address and port after a 1 and 6 after anything else (`0x7380f0`), and takes a request of 24 or 36
bytes (`0x738024`).

The type-3 handler `0x738000` (dispatch table `0x3973f19`, base `0x735434`) acts only when the
session's constant id at `+0x50` (`0x7473ec`) equals the station's own at `+0x40` (`0x747388`). It
finds the leaver by its location id, answers `04`, a fresh random word and the request's bytes 5 to
16 to the request's address (`0x7381c0..0x738248`, sent through `0x735fb0`), then removes the
station (`0x735b90`). The type-4 handler `0x738280` sets the job's done flag `[job+0x69]` only on a
17-byte message whose constant id and variable id are the leaver's own and only while the job runs
(`0x6e5f0c`); a host answering no leave holds every quitting console for the full four sends.

| host | first leave to deauthentication |
|---|---|
| `bin/pla_host.py` before the type-4 response, eight retail departures, started directly or by `bin/pla_join.py` taking the host role | 2.02 to 2.07 s, four requests 0.49 to 0.55 s apart |
| `bin/pla_host.py` answering with the type 4, two retail departures | 0.046 and 0.066 s, one request |

The screen time of a departure, marked with the board's BOOT button by the player (two retail
departures, host answering with the type 4):

| interval | measured |
|---|---|
| player confirms the quit to the first type 3 | the type 3 precedes the mark by 0.07 and 0.15 s, within reaction time |
| first type 3 to deauthentication | 0.046 and 0.066 s |
| player confirms the quit to the field back on screen | 3.70 s |

The wire is done within a tenth of a second of the confirmation; the rest of the delay before the
field returns is spent on the console after the station has left the network.

No timer inside Pia precedes the first type 3 ([pia.md](pia.md), Leaving a session). The only
caller of `Session::LeaveAsync` is the game's leave request, update `0x2ca0a10` (vtable `0x4198ef8`,
state `[req+0x88]`, jump table `0x3985448`): its first update calls `LeaveAsync` (`0x2ca0ac0`)
unless a Session job is already running (`0x72a280`), and its next updates wait for the job's result
(`0x72a294`).

From the console's last game message on 0x7C to its first type 3, nine host departures measured
1.91, 2.00, 3.02, 3.26, 4.07, 12.0, 15.3, 23.7 and 83.4 s, the player's input included. In each, the
console sent nothing in that window except RTT, Net answers, its periodic 0x81 records and acks of
the host's trade box. No fixed delay precedes the leave on the wire, and none is owed a reply.

`bin/pla_host.py` answers every type-3 request with the type-4 response. The scripted console in
`tests/test_pla_host_loss.py` runs the job's timing, and the host's answer goes through `0x738280`
under unicorn.

A received leave changed nothing on the console's screen in the two cases below; the console acted
on the network vanishing or on its partner going silent. With the console on the box screen and
nothing offered:

| host | console |
|---|---|
| network down, with or without a leave | "code d'erreur 2318-0006" within a second |
| network up and silent, with or without a leave (`--leave-sends 0`) | "Your trade partner chose not to continue trading" ("L'autre joueur a choisi d'annuler l'échange"), then Communicating, then `DisconnectedByUser`, no error code (measured: the message about 13 s in, about 3 s of Communicating after A) |

`--leave-after SECONDS` makes `bin/pla_host.py` send the leave with its own ids to each joined
station and end the run; `--stay-after-leave` keeps the network up, silent, and keeps the run going
after a console leaves following a trade. Its shape is pinned
against the four captured console leaves.

## Unresolved

- Whether a seated hosting slot ends on the 10.0 s Matching deadline or on a WaitMember timer.
- What the console does in the 3.6 s between leaving the network and showing the field.

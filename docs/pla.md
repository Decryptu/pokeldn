---
title: Legends Arceus
nav_order: 8
has_children: true
---

# Legends Arceus

Pokemon Legends: Arceus (2022, title id `01001f5010dfa000`) is a native Switch title with Pia
statically linked into `main`. The packet layer is read end to end, header and crypto; nothing
above it has been, and no packet from a console has been captured.

Addresses below are offsets into the decompressed `main` of update 1.1.1, as
`tools/switch/nso_read.py` lays it out (text `0x0..0x32a5690`, rodata from `0x32a6000`, data from
`0x401a000`).

## The wireless layer

| | value |
|---|---|
| Pia header version | 11, the wiki's Pia 6.16 to 6.23 band; a fourth band next to Sword's 4, BDSP's 9 and the GBA app's 15/16 |
| header size | 0x1C |
| GCM tag on the wire | 8 bytes, truncated from 16 |
| LDN passphrase | byte-identical to Sword/Shield's (the `HGhG` spelling; the wiki's Legends Arceus row has `HGHG` and does not match the binary) |
| Pia game key | `p1frXqxmeCZWFv0X`, the same ASCII literal as Sword/Shield and Scarlet/Violet |
| LDN local communication id | `0x01001f5010dfa000`, the title id |

The game key and the passphrase sit together in rodata at `0x3985308` and `0x3985319`, each
NUL-terminated. The LDN setup at `0x2c1e684` takes the local communication id in `x3`, built by the
`mov`/`movk` run at `0x264082c`, and installs the game key at `0x2c1e880`; one function does both.

The header initializer at `0x6f0744` stores the magic `0x32AB9864` at `+8` of its object and the
byte `0x0b` at `+0xc`; the validator at `0x6f07d0` checks the magic and `(byte & 0x7f) == 11`, then
requires the packet length minus 0x1C to be below 0x5a5. The object keeps the packet buffer at
`+0x30` with a capacity of 0x5c0 and the length at `+0x5f8`, and the copy assignment at `0x6f0878`
walks the header fields one by one, which is what fixes each field's size:

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

The footer is outside the encryption in this band. The encrypt path at `0x6f09f4` reads the footer
size off the header, subtracts it from the packet length, encrypts from buffer `+0x4c` (`0x30` plus
the 0x1C header) and writes the tag to object `+0x1d`, calling the AES-GCM entry point at
`0x6e68d0` with a tag length of 8 (`mov w4, #8` at `0x6f0b24`). The payload is 0xFF-padded to the
block size first, and `0x80` is ORed into the version byte once the packet is sealed.

## The receive path, for a breakpoint

    0x6ff6d8   nn::pia::local::LocalInputStream::vfunc4, the socket read
    0x6f07d0   the header validator: magic, (version & 0x7f) == 11, length - 0x1C < 0x5a5
    0x6f0b84   the packet decrypt; it charges through the GCM entry at 0x6e6aac
    0x6f09f4   the packet encrypt, the same shape in the other direction
    0x7015b4   LdnBackgroundProcessJob::WaitConnected, the step body a stalled joiner sits in
    0x70c304   LdnProtocol vfunc18, which that step calls and requires to return 0

The validator is called from five sites, `0x6ff6fc` being the one on the input stream. A packet that
reaches `0x6f0b84` and fails has a key, an IV or a tag problem; one that never reaches it was
dropped over its header or before the stream read it at all.

## The gate a joiner stops at

A joiner that has associated but sends nothing is held by the predicate at `0x6f63fc`, which reads
two endpoint slots on the LdnProtocol object, `+0x98` and `+0xb8`. An endpoint is 0x20 bytes: a
16-byte address at `+8` and a big-endian u16 port at `+0x18`.

    0x6f0ee4(a)     -> the endpoint is set: the port is non-zero AND the address is not the
                       sixteen zero bytes at 0x3972091
    0x6f0f48(a, b)  -> the two endpoints are EQUAL: same port, same sixteen address bytes
    0x6f63fc(obj)   -> 0 unless both are set, then whatever 0x6f0f48 says about them

So the gate asks whether two views of an endpoint agree, rather than whether two different peers are
known. The port is big-endian on the wire and native in the object. Read live with a joiner
connected, both slots hold the console's own address and Pia port and the predicate returns 1, so
this gate passes and is not where a stalled joiner stops. The slots are zero only between a
teardown and the next join.

## What a message is routed by

The dispatch key is the packet's SOURCE VARIABLE ID, not the protocol id. The parser copies it from
the header into the message's lookup field and walks the station registry for it; a station the peer
has never heard of makes the message unroutable, and it is skipped with its protocol never
consulted. A variable id is assigned per session and re-rolls on every one, so a host that invents a
fixed id can never match one.

Message flag `0x01` is what a message sent before the peer knows the sender carries: "skip the
source variable id check". `bin/pla_host.py` sets it on both of its probes.

## The Net Protocol, measured

A console hosting its own network opens the exchange. Joining one, `bin/pla_join.py` receives its
`NetUpdateNetworkConnectionStatusMessage` (protocol 0x2C, type 0x11) and the message decodes
against the wiki's 6.16 to 6.39 layout field for field, with the network id equal to the one derived
from the SSID the same console advertised:

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

Answering with the 0x12 ack advances it: the console re-sends 0x11 with a fresh sequence id and
`is migrating host` set to 1, and then repeats `01 40 00 00`, a bare
`NetStartHostMigrationMessage`, roughly twice a second for as long as the session lasts.

Answering that does not advance it further. A `NetUpdateNetworkHostMessage` built from the console's
own serializer, 26 of them, leaves it repeating 0x40, and sending its two u64 fields in the other
order changes nothing, so the field order is not what it rejects. Host migration at the LDN level means the new
host creates the network, which a Pia message alone cannot do, so the message may not be what
completes it.

The binary names every Net message and gives each a header class with its own serializer, so any
layout at this band is readable without a trace. `NetUpdateNetworkHostMessageHeader::serialize` is
`0x6fe03c`: a big-endian u64 at wire +4, another at +0xc, a big-endian u16 at +0x14, size 0x16. The
0x11 header at `0x6fd9dc` maps object +0x0c to wire +4 (sequence id), +0x10 to +8 (variable id),
+0x18 to +0xa (constant id), +0x20 to +0x12 (network id), +0x28 to +0x1a (is network open) and
+0x2a to +0x1b (station count). The session protocol's messages have no such classes; they are
written inline by `nn::pia::session::ClusterPacketWriter`, 0x732264 to 0x7336e8.

## The packet crypto

| | |
|---|---|
| session key | `AES-128-ECB(game key)` over one block of the network SSID |
| network id | CRC-32 of the SSID with its first byte dropped, `ssid[1:16]` |
| GCM IV | `u32be(network id XOR source IP)` then the header's eight nonce bytes |
| header nonce | a per-packet counter, big-endian |
| tag | the first 8 bytes of the GCM tag, in the header |

`0x70d61c` derives the session key: it takes a seed buffer and its length, repeats the seed if it is
shorter than sixteen bytes (`0x10 / len` at `0x70d66c`), and encrypts one ECB block under the
sixteen-byte game key at `LdnProtocol+0x238`. The crypto mode at `LdnProtocol+0x234` being zero
leaves the key all zeroes instead.

`nn::pia::local::LocalOutputStream::vfunc3` (`0x711710`) builds the IV: `0x6ed380` writes the
big-endian XOR at `IV[0]`, then eight bytes are copied from the packet header's nonce field to
`IV[4]`. The nonce itself is a counter the sender increments per packet and writes big-endian
through `0x6ed360`. The crypto setting handed to the GCM call is `{mode at +0, IV pointer at +8, IV
length at +0x10, key pointer at +0x18, key length at +0x20}`, with mode 1 for GCM, an IV length of
12 and a key length of 16.

This is the same derivation `pokeldn/ldn/crypto.py` already runs for the GBA app at Pia 6.32, which
is the whole 6.16 to 6.42 band.

## The protocols above the packet

Pia 6.16 to 6.30 keeps the protocol ids 5.29 to 5.45 used for everything below the session layer,
and replaces the station and mesh protocols with one Session Protocol. The ids changed again at
6.32, which is why the GBA app's numbers do not carry over:

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

So `pia_connect.py`, which speaks Net, Session and RTT at 6.32, is the right shape for this band
with the ids renumbered; `station_protocol.py` and `mesh_protocol.py` are not, because the
protocols they implement do not exist here.

The console states its per-protocol versions in the join request it sends once hosting delivers the
Net 0x11 to it every station window. Its list, ten protocols:

    Net 0x2c v0   RTT 0x58 v3   Unreliable 0x68 v1   Clone 0x74 v0   Clock 0x77 v0
    Reliable 0x7c v2   BroadcastReliable 0x80 v3   0x81 v3   Session 0x98 v0   Monitoring 0xa4 v0

### The Session join request

The console sends a 115-byte Session type-0 join request, written by `ClusterPacketWriter`. Header is
the type byte and a protocol count, then the ten `(id, version)` pairs above. Past the list, both
constant ids decode against `ldn_constant_id`, which anchors the body:

    +22  2   application version, 0x93b5
    +24  2   nonce, echoed by the response (width past two bytes unconfirmed)
    +26  8   source constant id, ldn_constant_id of the console
    +34  2   zero
    +36  2   source variable id, fresh per session
    +38  32  identification token, all zero on a codeless join
    +70  3   zero
    +73  4   source station address, IPv4
    +77  2   source station port, 12345
    +79  8   destination constant id, the host's
    +87  2   destination variable id, zero for the host
    +89  26  trailer, `00 c6 01 01 00..01 00..01 01 20`, unread

A location id on the wire is 12 bytes: a big-endian u64 constant id, two zero bytes, and a big-endian
u16 variable id. The request's `0000` at +87 is the destination location id's two zero bytes; the
host variable id is the `00c6` at +89, and the trailer starts at +91.

### The Session join reply

The joiner parses the ack at `0x737534` and the join response at `0x7379c0`, both dispatched from the
receive loop `0x7353a0` through the type table at `main+0x3973f19`. Each compares four ids and drops
the message silently on any mismatch. A host echoes the ids the request stated: the host constant and
variable ids from its destination fields, the console's from its source fields.

The ack is Session type 1, 25 bytes: the type byte, then the host location id and the console location
id. It sets `JoinMeshJob+0x69` and extends the join deadline `job+0x80` by 8000 ms. It carries no
random and completes nothing on its own.

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

The random is neither echoed nor read on the accept path. The assignment fields are stored without
validation; the console's own writer `0x736cec` puts route `00 01`, index 1 and join order 1 for a
first joiner. Status 1 sets `JoinMeshJob+0x68`. Answering the request once makes the console stop
repeating it, where an unanswered request repeats about sixteen times a window.

The response only marks the join accepted. `JoinMeshJob+0x7c`, the completion flag, is set by the
type-5 station-list update `0x738740`, and only once an update whose sequence reaches the response's
`+0x29` value has been applied, at which point the joiner answers with a Session type 6: the type
byte, the console constant id, two zero bytes, and the sequence, 13 bytes.

### The type-5 station-list update

The update is reassembled by `0x7404a8` from fragments before `0x73897c` reads it. A single fragment
carries the whole update. The seven-byte fragment header is the type byte, a big-endian u16 sequence,
a fragment count, a fragment index, and a big-endian u16 offset. The reassembler seeds its buffer with
the header's first three bytes (type and sequence) and copies the fragment payload at the offset, so
the payload begins at the host constant id and the offset is 3. The reassembled body:

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

An IPv6 station carries an 18-byte address in place of the six bytes, shifting the rest by 12. The
host is route `00 00`, index 0, join order 0; the first joiner is route `00 01`, index 1, join order
1. The player record matches the one the console emits in its join request tail: id `00..01`, length
1, encoding 1, name a single space. `0x738bc0` then updates a station that already exists by constant
id and creates one that does not, and once the applied sequence reaches the response's, sets
`JoinMeshJob+0x7c` and sends the type 6. On this update a joining console leaves `JoinMeshJob` and
runs the mesh: it answers with the type 6, then sends RTT, Clone Clock and the Stream Broadcast
Reliable stream, and holds the session until a peer that never answers those times it out.

## Sustaining the mesh

A joined console runs three protocols the host must answer or the game abandons the session about ten
seconds after the join. RTT (0x58) is an 11-byte message at this band, a kind byte then an eight-byte
timestamp and a two-byte target, and a kind-1 response that echoes the timestamp with target 0 is
accepted. The Clone Clock (0x77) ticks on its own.

The Stream Broadcast Reliable protocol (0x81) carries the sliding window `pokeldn/ldn/reliable5.py`
reads: the 9-or-13-byte header, then application data or, with the application-data flag clear, a bulk
ack of `2 + 21 * count` bytes. The ack's leading byte is a type whose only read bit is bit 0, and each
21-byte entry is a station byte, a big-endian u16 acknowledgement id, a big-endian u16, and a 16-byte
mask. The consumer `0x742740` reads the entry at the receiver's own station index and requires that
entry's station byte to equal the sender's index, so a host acking a joiner at index 1 sends at least
two entries and sets every station byte to 0, the host's index. The acknowledgement id is one past the
highest sequence received. `0x74f0ec` applies the mask.

Answering RTT and acking the reliable stream stops the console's retransmissions but does not hold the
session: the game leaves about ten seconds after the join unless the host itself sends reliable data.
The console opens its own stream with an INITIALIZED data message (flags `0x0f`, seq 1) and a second
data message, and its once-a-second ack carries a host-stream acknowledgement id that climbs while the
host stays silent. Host reliable data with the destination bitmap set for the console's own station
index (bit 1, count 2) is accepted and applied into the console's receive window; a host stream sent to
the wrong bit is dropped after the sender-station check.

## The game's reader and the pre-handler phase

Above the Pia reliable window, the game polls its own reader at `main+0x2ca4f30` (`0x741494`), 365 times
a window. Two loops share one handler table: one reads protocol 0x7C (Reliable), the other 0x80
(BroadcastReliable). Host reliable data sent on 0x80 reaches this reader and returns the host's payload;
the same data on 0x81 (StreamBroadcastReliable) never reaches it, so 0x80 is the channel the game reads
host data on. A message's first eight bytes are a two-u32 handler key; the matched handler receives the
payload past the key with length reduced by eight, and a key that matches nothing is discarded.

At the trade search screen the handler table is empty: the instruction after the reader takes a message
is `ldr x8, [x19+0xd0]; cbz x8`, and with no handler registered every message on either channel is
drained and dropped before its key is read. The game registers its handlers through `0x2ca5264`, which
never runs across a full join and leave, and the handler-array pointer is nulled on leaving the menu.
The reader loops tick about 2.5 times a second, the rate of a background manager rather than an active
scene, so the object polling for host data is an idle manager and the trade scene's own manager is
never constructed.

The game's code resolves exactly three protocols across its nine Pia call sites: 0x68 (Unreliable),
0x7C (Reliable) and 0x80 (BroadcastReliable), three read loops and four send paths, and none for the
Clone protocols 0x74 to 0x77. The console's constant 0x77 clock traffic is Pia's own mesh housekeeping
below the game. The game's two session-state queries both pass, so it is satisfied with the session.

The ten-second leave is the failure branch of the game's own matching sequence, one level above the
Pia mesh join, and the trade scene is its success branch. The trade flow is `0x13d5bfc`, its step at
`[flow+0xa4]`, jump table `0x397c118` for steps 0x15 to 0x22. Step 0x17 calls `0x26bdcac`, which builds
the sequence and stores it at `[manager+0x70]`; step 0x18 polls it through vtable slot 9 (`0x12b3290`),
which returns true when the outstanding-child counter `[request+0x70]` is zero. The counter goes to 1
when the sequence starts and stays there for the whole wait; the flow reads no network, session or
mesh field. Step 0x1e, downstream, is where `0x13d5f94 -> 0x26d8c2c -> 0x2bcb8c8 -> 0x2ca5264` registers
the handlers. The sequence's steps, by the name strings `0x26bdcac` pairs with their functors:

    LoginRelayServer     looked up before the sequence is built; a missing one returns false
    Matching             the first child, the one that never completes
    DataExchangeStart
    OnCancelDataExchange
    OnSuccess            the trade scene
    OnFailure            event 8, flow step 0x23 (table `0x397c134`), the leave
    OnCancel
    Cleanup

Step 0x18 has two gates. The first is the sequence's outstanding-child counter, which reads 0 at the
step's own call site `0x13d6130`. The second is `0x13de870`: `[obj+0x7c] == 1`, where `obj` is the
network-menu object, persistent across sessions, reading 0 for the whole wait. `[obj+0x7c]` is set to
1 by the case-0 update `0x13de888` when the current page (`[obj+0x88]`, a page's `+0x5b0`) reports
result 1: `0x13de950` for ViewTop at `[obj+0x90]`, `0x13de9d8` for ViewAlert at `[obj+0x98]`,
`0x13dea28` for ViewInMatching at `[obj+0xa0]`; the three pages are built by `0x13de3cc` from the
`netm` layouts. A page's result is its `+0x5bc`: 1 written by its InputDecide and InputBack handlers
(`0x13dc7b4`, `0x13dc7ec`, `0x13dd3ec`, installed at `0x13dc0a4`, `0x13dc1a0`, `0x13dc9a0`), 2 for
`button_00` and 3 for `button_01` (`0x13ddcb4`, by button-name hash). The result is written by player
input and by nothing on the network. Result 2 or 3 sets `[obj+0x7c] = 2` and `[obj+0x84]` to the
button.

The timeout is thrown as `gflnet::request::Error::Timeout` at `0x26d4ae8`, 10.2 s after the join
request, and runs `0x13d654c -> 0x13d6384 -> 0x2c43d78 -> 0x2ca0a10 -> Session::LeaveAsync (0x72a6dc)`,
then the Error 7 dialog. The sequence's completion callback is `[request+0x90] -> 0x26d69e8 ->
0x26d6a88`, which receives a result object. What the Matching child waits for is unknown.

Between two Ryujinx instances of the game a full trade runs, and its wire shows what the child waits
for. After the mesh join both stations run a two-round data exchange on the Stream Broadcast Reliable
protocol (0x81), on port 0 and port 1: each opens the stream with a type-0x0f message, sends a
44-byte state record (`0000002c ffff` then a station index and per-station counters, flags 0xa0),
and sends one type-0x1f content record of 74 bytes carrying a 64-byte payload that begins `484b6264`.
The joiner's Matching step completes 17 ms after it receives the peer's second-round 0x81 record, and
`OnSuccess` (`0x26d5f64`) is enqueued on the executor at that instant. The trade box, a 399-byte type-7
record, crosses later on the Reliable protocol (0x7c) once the scene is open, not before it.

A host built here answers the console's 0x81 stream with a reliable ack and never originates on it: no
0x0f open, no 44-byte state record, no 0x1f content. The data exchange therefore never completes from
the console's side, the Matching child never fires, and the sequence times out.

A joining console does not wait to be spoken to first. Against a silent host it opens its own stream,
sends its record and retransmits it about once a second for the whole twelve seconds, so the ordering
of the reference pair is whichever station was quicker and a host may answer the offer already
standing.

A message ends where its payload ends. The 5.27-5.45 band aligns a message to four bytes; this one
does not, and a reference host bundles two messages in the packet that answers the console's stream
open: the record on port 0, then its own stream open on port 1 under a header that names the size,
the protocol and the port and inherits the message flags. Only the packet pads, to a multiple of
sixteen and with 0xFF, where a zero byte would be read as a message header. A parser that aligns
walks past the second message and reads the packet as carrying one.

The protocols split two ways in how a packet is addressed. The session, clone clock and reliable
protocols carry the peer's variable id in the packet header with no footer. RTT and Stream Broadcast
Reliable carry the mesh destination 0x0001 in the header and name the recipient's variable id in the
plaintext footer, and both reference stations address them that way. A 0x81 message addressed to the
peer's variable id is transmitted and never reaches the game: the console's own count of received
datagrams does not move. Driving the 0x81 data
exchange as the reference host does is what remains. The 64-byte content payload is byte-identical in
both directions of the same-save pair except for the sender's station index, so whether any of it is
per-player is not yet separable.

## The game's reliable channel

Once the data exchange completes, the trade flow leaves the step that waits on it and reaches the
step that ticks the game's own network object, `0x13d5cac`, which tests `[net+0xb8] > 1`. The object
advances on what the game reads on protocol 0x7c rather than on anything the transport does: state 0
to 1 through `0x26d9170`, and 1 to 2 on `[net+0x78]`, which the receive handler `0x26da310` sets in
its case 0.

A message on this protocol is an eight-byte handler key and a body. The dispatcher `0x2ca4a88`
compares the key against each registered channel's own eight bytes at `+0x6c` and hands the body to
that channel's receiver with the key stripped. Two channels are registered in the whole game, both
through `0x2bcb8c8`: key `00 00 00 00 00 00 00 00` for the trade box, created by `0x26d8c2c`, and key
`01 00 00 00 00 00 00 00` for the phase protocol, created by `0x26d7aa0`.

Port 0 and port 1 are two Reliable protocol instances, registered one after the other in the game's
protocol sequence at `0x2bba180` as `0x7c000000` and `0x7c000001` (the stream broadcast protocol
gets the same pair, `0x80000000` and `0x80000001`). The registration stores each protocol's handle
in a table at `0x4308a80`, indexed by port: `0x4308a80` is 0x7c port 0, `0x4308a84` port 1. The
handler dispatcher `0x2ca4a88` reads port 0 of 0x68, 0x7c and 0x80 directly; port 1 of 0x7c is
read through the table by one object, the channel table below.

Two ports open, each a `reliable5` stream with no destination bitmap, addressed to the peer's
variable id the way the session and clock messages are, at sequence 1 under the message-start,
message-end and initialized flags:

    port 0    key eight zero bytes      body 0100        the host opens it
    port 1    b9 01 01 b9 02 b9 02 00 00 01              the joiner announces the zero key open

Each station answers its peer's channel message with a one-entry acknowledgement and with the same
message back on the same port.

## The channel table on port 1

Port 1 of protocol 0x7c carries no game message. It carries the channel table: each station tells
its peer which handler keys it has open, and a station sends on a key only after its peer has
announced that key open. A host that never announces a key never receives a message on it.

The dispatcher's initialisation `0x2ca36f0` builds one object of 0x298 bytes (vtable `0x41997d8`)
with its port byte at `+0x70` set to 1, and keeps it at dispatcher `+0x20148`. Every frame the
dispatcher calls its poll `0x2ca82d0`, which receives from 0x7c port 1 into `0x2ca9800` and then
runs the sender `0x2ca83dc`. The object keeps two tables of 0x18-byte entries, each an eight-byte
key at `+0x00` and a station bitmask at `+0x08`:

| table | holds |
|---|---|
| `+0xa0` | the station's own channels, with the byte at entry `+0x10` set while the channel exists and the bitmask naming the stations already told |
| `+0xd8` | the peer's channels as announced, the bitmask naming the stations that announced the key open |

The sender walks the own table once per station bit. An existing channel whose bit for that station
is clear gets the bit set and is announced open; a destroyed channel whose bit is still set gets the
bit cleared and is announced closed. Nothing is sent when nothing changed. The receiver takes the
sender's station index from the packet, requires it below 2, and on an open sets that station's bit
in the peer table, adding the entry if the key is new; on a close it clears the bit and erases the
entry once no bits remain.

Creating a channel (`0x2bcb8c8` -> `0x2ca5264`) gives it a reference to the table object's
interface at `+0x68`. Every channel sender asks that interface (`0x2ca92e0`, then `0x2ca9360`)
whether the peer table holds the channel's key with the destination station's bit set, and sends
only on yes; the selector-5 sender does so at `0x26d980c` through the channel's `+0xb8`. That is
the wait the trade screen shows while a host is silent on port 1.

A message is the game's tagged serialisation. An unsigned integer below 0x80 is its own byte; above
it a tag names the width, little-endian: 0x80 and one byte, 0x81 and two, 0x82 and four, 0x83 and
eight (`0x2661ec4`, `0x26619cc`, `0x2661f78` write a u32, a u64 and a u16 through the same rule).
The size table at `0x397dfcc` gives 0x84 to 0x87 the same four widths, 0x88 four bytes, 0x89
eight, and 0xb5 to 0xbf one byte. 0xb9 opens a tuple and the integer after it is the field count.

    b9 01              a tuple of one field, the list
    NN                 the number of entries
    per entry:
      b9 02            a tuple of two fields, the key and its state
      b9 02 LO HI      the key as two u32, low word first
      01 | 00          1 open, 0 closed

The three messages a console sends during a trade are the two channels it creates and the one it
destroys:

| message | meaning | when |
|---|---|---|
| `b9 01 01 b9 02 b9 02 00 00 01` | the trade box key open | with the port-1 open, on reaching the trade step |
| `b9 01 01 b9 02 b9 02 01 00 01` | the phase key open | after the confirmation, when `0x26d7aa0` creates the phase channel |
| `b9 01 01 b9 02 b9 02 01 00 00` | the phase key closed | once the trade is written |

`pokeldn.pla.channel_table` builds and parses these. The host answers each key a console announces
open with its own announcement of that key open, once per key, and reads a close without
answering. A close announced back would clear the console's bit for the host's phase key; the
trade of 2026-09-18 completed with the close unanswered, so that is what the host keeps doing.

## The trade box

With both channels open the trade screen is up and the game's own messages cross on port 0 behind
the eight-zero-byte handler key. The receive handler is `0x26da310`. It reads a selector and a
counter, switches on the selector through the byte table at `0x397e388`, and drops anything above 7.

    1   the station is ready       0x26da3a4   sets [net+0x78], which is what step 0x20 waits on
    2   the Pokemon it is SHOWING  0x26da3f0   stored at [net+0x98] by 0x26da1d8, nothing else
    3                              0x26da430   -> 0x26d93c8
    4   the Pokemon it is OFFERING 0x26da3b0   stored at [net+0xb0] by 0x26da23c, phase 0xbc := 3
    5   the trade is confirmed     0x26da43c   behind a counter check -> 0x26da2c0
    6   the offer is made          0x26da458   phase 0xbc := 2, bumps the counter at [net+0xf8]
    7                              0x26da49c   behind the same counter check, phase 0xbc := 5

Before the switch the handler compares its fourth argument against `[net+0x88]` and aborts on a
mismatch, so a message from a station the game is not in a trade with never reaches a case.

**SELECTORS 2 AND 4 ARE THE SAME MESSAGE AND DIFFERENT EVENTS.** A station entering the box sends 2
on its own; it sends 4 when the player offers the Pokemon up. The two land in different slots, and
only 4 moves the phase. An answer therefore has to carry the selector it is answering: a host that
answers an offer with a showing fills the wrong slot, and the console sits on the trade screen with
an empty partner hexagon and no error, because from its side the partner has shown a Pokemon and
never offered one. `pokeldn/pla/trade_box.py` mirrors the selector for that reason.

The body is the game's own tagged encoding, read by `0x26dac6c` for the selector, `0x26662fc` for
the counter and `0x26dacbc` for the record. A byte under 0x80 is itself, 0x80 introduces a byte,
0x81 introduces a halfword, and 0xbc introduces the record, which `0x26da3b0` tests for by hand
before deserialising.

    0x00  1   the selector
    0x01  1   the counter, 0 on both record-carrying selectors
    0x02  1   0xbc
    0x03  1   0x81
    0x04  2   the record's length, 0x178
    0x06  376 the record

The message is 390 bytes of payload under a nine-byte header with no destination bitmap, flags 0x07
- application data, message start, message end, and neither the initialized bit the opens carry nor
the zlib bit the data exchange carries - at sequence 2, the opens having taken sequence 1.

A console sent the record-carrying message byte for byte identically in two sessions, on two
machines, minutes apart, against two different hosts and two different session keys. Nothing in it
is derived from the session, the peer or the clock: it is a function of the save, which is what
makes a captured one replayable.

The record is the Gen-8 entity with wider blocks. The header, the LCG, the block permutation and the
16-bit checksum are `pokeldn.gen8`'s field for field, and a block is 0x58 bytes rather than 0x50, so
a stored record is 0x168 and a party record 0x178. `gen8.BLOCK_ORDER[(ec >> 13) & 31]` is applied as
it stands when decrypting and inverted when encrypting. The checksum cannot tell those two apart,
because permuting whole blocks leaves a sum of 16-bit words alone; what tells them apart is where
the names land. Read directly, the nickname is the second block's first field at 0x60 and the
trainer name the fourth's at 0x110, which is the Gen-8 layout with the wider block. Read inverted,
both strings still decode, one block earlier, against a record that carries neither.

The captured record decrypts to a level-70 Azelf: species 482 at 0x08, the nickname at 0x60, the
trainer name at 0x110, experience 428750 at 0x10, which is the slow curve at the level the party
tail carries at 0x168. Its trainer id at 0x0c is the same four bytes the data exchange record
carries as the player id, and its trainer name is the name the data exchange carries, so the two
messages describe one player.

## Confirming the trade

Choosing Trade it sends selector 5 and a counter, two bytes behind the same zero key, at the next
sequence on the same channel. Its sender is `0x26d9770`, gated on `[net+0xb8] == 3`, which is the
state the station reached by sending its own offer; after the send it sets `[net+0xb8]` to 4. Its
consumer `0x26da2c0` sets the phase `[net+0xbc]` to 4 and, when `[net+0xb8]` is already 4, takes the
branch that clears `[net+0xc8]` and allocates into it.

So the confirmation is a rendezvous between a station's own send and its peer's: the station that
confirms second finds the state already 4 and goes on. A host that acknowledges the console's
confirmation and sends none of its own leaves the console at state 4 with the phase never reaching
4, which is the trade screen waiting.

Past the confirmation the console announces the phase key open on port 1,
`b9 01 01 b9 02 b9 02 01 00 01`, without the initialized flag, and sends nothing on that key until
the host has announced it open too (the channel table, above). A host that answers the port-1 open
and never this leaves the trade screen waiting with the phase already at 5 and nothing else on the
wire.

The counter is the halfword the handler reads before the switch, and selectors 5 and 7 check it
against `[net+0xfa]` and drop a message carrying less. `0x26d9770` sends `[net+0xf8]` as it stands,
where the selector-6 sender at `0x26d98ac` sends it plus one.

## The trade object's own state machine

`[net+0xb8]` is the state the trade flow's step 0x20 tests, and `0x26d9094` is the tick that moves
it. Read alongside the handler's cases it accounts for the whole exchange.

    0     if [net+0x90] is set, 0x26d9170 -> state 1
    1     once [net+0x78] is set, one 64-bit store of 0x200000002 puts the state at 2 and the
          phase [net+0xbc] at 2 in the same instruction
    3, 4  while [net+0xc0] is set: read the stopwatch at [net+0xc8], and once [net+0xd0] is past
          1.5 seconds and the phase is 4 or 5, 0x26d9254 sends selector 7 and the state becomes 5
    5     no case. The object is finished

So a station that has offered, confirmed and seen its peer's confirmation ends at state 5 with the
phase at 5 and the stopwatch allocated, and its tick does nothing further. Reaching that state is
not the trade being carried out: with both stations there, both Pokemon on screen and the whole
message chain answered, the save is untouched and the screen still reads Communicating. Whatever
executes the trade is above this object.

## The job that carries the trade out

Reaching state 5 is not the trade. The scene above the trade object polls `0x26d9ea0`, which is
`[net+0xd8]` non-null and that job's state at `+0x10` in 6..10, and the job's success callback
`0x26db864` is what writes 6 to `[net+0xb8]`. `0x26d9a90` builds the job from the sub-state 7 arm,
out of `[net+0xa0]`, `[net+0xa2]`, `[net+0xa4]`, `[net+0xa8]` and the offered record at `[net+0xb0]`.
It is 0x140 bytes, constructed at `0x26dc08c` with its vtable at `0x416c8f8`, started at `0x26dc564`
with eight callbacks, and its state at `+0x10` starts at 0 and is set to 1 by `0x26dc2c8`.

`0x26dc71c` is its update: a fourteen-state switch on `state - 1` through the table at `0x397e390`.
The arm for state 2 is

    0x26dc798   x0 = [job+0x28]; 0x26d7e5c(x0, 3); on true the state becomes 3, otherwise it stays

and `0x26d7e5c(obj, n)` is not a wait on the peer. It reads `[obj+0x70]`, which has to be non-null,
`[obj+0x90]`, which has to be set, and returns `[obj+0x92] == n`. Those two fields are written by
`0x26d7e84`, the sender, and only after a send succeeds: it tests `0x2ca34e0([obj+0x70],
[obj+0x88])`, sends through `[obj+0x70]`'s vtable at +0x40 addressed to `[obj+0x88]`, and then
records the phase at `+0x92` and sets `+0x90`.

## The phase protocol, and the message only a host sends

The job announces phases on a handler key of its own, `01 00 00 00 00 00 00 00`, which the game
registers on the fly when the job is created. The object it announces through keeps three pairs of
fields, a flag and a halfword each:

    [obj+0x94] / [obj+0x96]   the phase this station has announced, written by 0x26d7d8c
    [obj+0x98] / [obj+0x9a]   the phase the peer has announced, on receiving selector 1
    [obj+0x90] / [obj+0x92]   written by 0x26d7e84, and on receiving selector 2

The two senders are the same eight instructions apart from the selector they write, and the receive
handler at `0x26d7f90` is their mirror image: selector 1 fills the peer pair, selector 2 fills the
third, and selector 0 aborts. The message is the selector and the phase, a byte each while the phase
is under 0x80.

The job's state 2 arm asks `0x26d7e5c(obj, 3)`, which is the third pair holding 3, so a station
leaves state 2 only once its peer has announced selector 2 with that phase.

**SELECTOR 2 IS THE HOST'S TO SEND.** `0x26d7e84` is reached only behind `[obj+0x78]`, written once
at job creation by `0x26d7aa0` from a predicate that ignores its argument and compares the station
against the session's host station. On a joiner it is zero and is never revisited, so a joiner never
sends selector 2 and its own job cannot leave state 2 by itself. The host owes the message. A host
that mirrors the joiner's selector 1 and sends nothing else fills the peer pair and leaves the third
empty, which is a trade screen waiting with both Pokemon shown, every message acknowledged and
nothing outstanding on the wire.

A station's sliding window on a port is its own, so every message a station originates there takes
the next id in its own sequence, mirrors included. Numbering a mirror with the id the peer used
looks right while the two streams are in lockstep and collides as soon as one station sends two
messages where the other sent one: the second arrives under an id already delivered, and the window
discards it without dispatching it. That is one message lost in silence, acknowledged on the wire,
with the receiving handler never entered.

The setup that writes that flag has five exits before the store, all of which leave it at the
constructor's zero: a null argument, a null cast, `[vtable+0xd8]()` not returning 2, a station list
whose count at `+0x28` is not 2, and either station slot coming out null. Against a two-station
session with the ids the console itself sent, none of them is taken.

## The completed trade

With the host answering each phase, the job walks out on its own. The console announces 3, 6, 0xb
and 0xe in turn, the host answers each with selector 2 and the same phase, and each answer fills the
third pair and moves the job on:

    <-  0x7c p0  01 03      ->  01 03   the mirror     ->  02 03   the host's
    <-  0x7c p0  01 06      ->  02 06
    <-  0x7c p0  01 0b      ->  02 0b
    <-  0x7c p0  01 0e      ->  02 0e

240 ms after the first `02 03` is dispatched the third pair reads 1 and 3, and that was the whole
stall. The animation plays, the console says to take good care of the Pokemon, and the box comes
back with the panel reading the host's player name as the original partner. Eight files in the save
differ from the pre-run backup: `main`, `main2` and `backup` in both slots, and both ExtraData
files. It had been byte-identical through every earlier run.

The console then sends a fresh selector 2 on the trade key, showing whatever the box cursor is on
now, which the host answers with its own showing, and the port-1 announcement that the phase key
is closed, `b9 01 01 b9 02 b9 02 01 00 00`. The host does not answer that one, and the trade
completes regardless: a retail console sent both after the trade of 2026-09-18 with the record
already in its save and the player back on the field.

## What a trade rewrites

A console shows the box cursor's Pokemon on the trade key every time the cursor moves, so the record
a host traded in comes back over the wire out of the console's own box, and the two can be compared
byte for byte. A level-50 record sent with a level-70 party tail came back with 23 bytes changed and
no others:

    0x006  2   the checksum
    0x092  1   the current HP, 235 sent, 192 stored
    0x0b8  26  the handling trainer's name, filled in with the receiver's own
    0x0d3  1   the handling trainer's language
    0x0d4  1   the current handler, set to 1
    0x0d8  1   the handling trainer's friendship
    0x16a  12  the six party stats, recomputed

So the receiving game fills in its own handler fields and rebuilds the current HP and the stats from
the level and the experience, and it does not trust the tail it was sent. Everything else is stored
as it arrived, which is what makes a record the host's to write.

A console walked across its box on that screen is a library of records the game itself considers
legal, and 46 of them place the moves: four halfwords at 0x54 with four bytes of remaining PP at
0x5c, both inside the first block, where Gen 8 keeps them in the second at 0x72 and 0x7a. Every pair
of records of one species carries the same four move ids and the same PP across different levels,
encryption constants and personality values, a lower-level Chimchar differs from a higher one in the
fourth move alone, and the Gen-8 offsets read zero in all 46. The three bytes at 0x50, 0x51 and 0x52
are the height scalar, the weight
scalar and the scale, which is why the first and the third are always equal.

That comparison is also how the field map was found. The block starts are `pokeldn.gen8`'s plus
eight bytes per block before them - the nickname at 0x60 for its 0x58, the handling trainer's name at
0xb8 for its 0xa8, the trainer's name at 0x110 for its 0xf8, the party tail at 0x168 for its 0x148 -
and the three handler fields inside the third block keep their Gen-8 positions plus 0x10. Inside a block the offsets follow their block: the first block is Gen 8's
field for field apart from the moves, the second is Gen 8's plus 8, the third plus 0x10, the fourth
plus 0x18 with the ball moved to just after the met date.

The captured pair exchanges selector 2 and stops: both stations show a Pokemon within 42 ms of one
another, both acknowledge, and the rest of the capture is RTT. Nobody offered anything up, so
nothing past the showing is recorded anywhere.

`pokeldn/pla/trade_box.py` builds the message and `pokeldn/pla/pokemon.py` the record; both
reproduce the console's own bytes on both selectors.

## Choosing what to offer

The record a host offers is its own to compose. A level-100 Arceus under the host's trainer name,
with the personality value chosen so that the Gen-6 shiny value came out 0, was traded in and the
console drew it as sent: species Arceus, level 100, nature Lax, experience 1250000, the four moves
105, 326, 449, 63 on the summary, the sparkle on the summary, on the box panel and on the model,
and the same eight save files rewritten as on the two trades before it.

Two of those readings check the map by arithmetic rather than by eye. The panel's ID No. read
201745, which is the whole 32-bit id at 0x0c modulo a million, so the halfword at 0x0e is the high
half of one trainer id and not a field of its own. The nature byte read 9 and the panel read Lax,
which is the Gen-3 nature table.

THE FIELD MAP. What the game reads out of a record is PKHeX's PA8, and every offset measured here
agrees with it: the species at 0x08, the held item at 0x0a, the id at 0x0c, the experience at 0x10,
the ability at 0x14, the personality value at 0x1c, the nature at 0x20, the form at 0x24, the effort
values at 0x26, the moves at 0x54 with their PP at 0x5c, the nickname at 0x60, the relearn moves at
0x8a, the current HP at 0x92, the packed individual values at 0x94, the growth values at 0xa4, the
absolute height and weight as floats at 0xac and 0xb0, the handling trainer at 0xb8, the version at
0xee, the language at 0xf2, the trainer name at 0x110, the met date at 0x134, the ball at 0x137, the
egg and met locations at 0x138 and 0x13a, the met level and the trainer gender sharing 0x13d, the
level at 0x168 and the six stats at 0x16a. `pokeldn/pla/pokemon.py` holds it as four tables.

Three of its fields are confirmed by the 47 captured records rather than by the source the map came
from. The alpha bit at 0x16 and the alpha move at 0x3e are set on the same three records and on no
others, and those three are the ones carrying 0xff in all of 0x50, 0x51 and 0x52. The scale at 0x52
equals the height scalar at 0x50 in all 47, which is the pattern that had looked like an unread
triple. The packed individual values at 0x94 carry the egg and nickname bits clear in every record,
with six values in range. Every record carries version 47 and language 2, the sanity halfword 0 and
the affixed ribbon 0xff.

ANSWERING EVERY MESSAGE. A console in the box screen sends a showing on every cursor move, and a
player who cancels an offer sends the mirrored selector with its round byte advanced and then offers
again. A host that answers one message per selector per station leaves all of those unanswered: a
run where twelve Pokemon were shown before the offer had one showing answered, eleven cursor moves
stale by the time the offer arrived, and the second offer, `04 01`, drew nothing at all. The three
trades that completed each had a single showing before the offer, which is why it took a long box
session to surface. The host answers each distinct (selector, round, record) once, which answers
every new message and drops a retransmission.

A record built from zeros with the field map here reproduces a console's own record byte for byte
apart from the fields chosen: against the console's own level-68 Gengar, the only differences were
the effort values at 0x26, the individual values at 0x94, the growth values at 0xa4 and the
purchased move record at 0x159, all four of them deliberate.

Such a record was traded in and stored. A shiny level-68 Gengar assembled from 376 zero bytes,
nicknamed, with perfect individual values and every growth value 10, went into a console's save on
the first attempt: the partner summary drew the species, the nickname, the sparkle, the four moves
with their PP, nature Naive for the byte 14, experience 322272, and all six effort badges reading
10, which is what draws 0xa4. The dispatch chain was the one the console's own records take, 04, 05,
07 and then the phase messages, with nothing retried.

The console showed the stored record back out of its box afterwards, and it differs from what was
sent in the handler fields, the current HP and the stats alone. The individual values, the growth
values, the empty effort values, the moves, the PP, the size, the ball, the met data and the empty
purchased move record are all stored exactly as they arrived, which is the record layer answered:
what a host composes is what the save keeps. The stats the game computed from those values are
273/210/199/322/345/220 for the 239/136/121/322/304/133 tail it was sent, five of the six raised and
the speed returned equal to what was sent.

ANYTHING THE GAME HAS CAN BE COMPOSED. An alpha, shiny, nicknamed Garchomp at level 100 of a
species the save had never held went in on the first attempt, built from 376 zero bytes with every
value out of the game's own tables: the four latest level-up moves with their PP, the experience for
the level on the species' curve, its first ability, its gender ratio, the average height and weight
against the alpha's 0xff scalars, and the six stats from the model above. The console drew the
nickname on the hexagon, the red alpha marker and the shiny sparkle beside it in the name bar, the
height and weight, Adamant, the effort badges at 10, and the six stats exactly as sent.

That record came back out of the box with 14 bytes changed: the checksum, the handling trainer's
name, language, handler flag and friendship. The stats were not touched, because the tail it was
sent is what the game itself computes, which is the stat model confirmed a second way.

The handling trainer's friendship a trade writes is the species' own base friendship from the
personal entry, 50 for both Gengar and Garchomp.

MASTERED MOVES. The eight bytes at 0x15d are a bitmap over the 61 moves the game's mastery list
holds, in that list's order, and a species may master only those its personal entry permits, a u64
at 0xa8. Of Garchomp's 21 permitted moves two are in the record above, Earth Power and Outrage,
while Dragon Claw and Double-Edge are not in the list at all and can never carry the flag.

The game reads that bitmap, and a record built here sets it. The marker is the scroll on the
Pastures screen's Change moves, and a move draws it when its mastery level is at or under the
current level OR its bit is set, which is why three level-100 records drew it on every move and said
nothing. The test was a console's own level-13 Chimchar rebuilt with one bit changed: Tackle, whose
mastery level is 10, drew the scroll on both; Ember, 15 and not in the mastery list at all, drew
nothing on both; Swift, 20 and flagged at index 10, drew nothing on the console's own record and the
scroll on ours. The mastery levels are `mastery_la`, one entry per species and form in the
learnsets' own format.

WHAT THE GAME DOES NOT CHECK. A record sent at level 50 carrying a met level of 70 was stored and
shown back out of the console's own box with the met level it was sent, so the receiving game does
not compare the two.

THE STATS THE GAME COMPUTES. A trade discards the six halfwords in the party tail and writes its
own, and `pokeldn/pla/stats.py` reproduces them: each stat is a growth term, the rounded
`(sqrt(base) * multiplier + level) / 2.5`, plus a base term, `((level / 100 + 1) * base)` truncated
and the level added for HP and `((level / 50 + 1) * base / 1.5)` truncated with the nature at 110%
or 90% for the rest. The multiplier is read from a table by the growth value plus a bias from the
individual value, 3 at 31 and above, 2 at 26 and 1 at 20, with the sum clamped at 10.

The model is verified on twelve numbers a console computed: 273/210/199/322/345/220 for a built
record with perfect individual values and every growth value 10, and 239/136/121/322/304/133 for the
console's own record the values came from. Both at level 68 with nature 14 and Gengar's base stats.
The clamp is also why a record sent with perfect values came back with the speed it was sent: the
donor's individual value 22 and growth value 9 reach 10 as surely as 31 and 10 do, so the growth
term is identical.

The absolute height and weight at 0xac and 0xb0 are the species average times a factor from the
scalars, `(scalar / 255) * 0.40000004 + 0.8` per scalar, height alone for the height and both
multiplied for the weight, computed in 32-bit floats. For a console's own Gengar, scalars 111 and
221 against the averages 150 and 405, it gives 146.11766052246094 and 452.38031005859375, the floats
the record carries.

A species' base stats, gender ratio, ability, experience curve, average height and weight and
level-up learnset, and each move's PP, are all in the game's own tables, and PKHeX carries copies:
`personal_la` at 0xB0 bytes an entry, `lvlmove_la.pkl` as a 16-bit BinLinker archive of move
halfwords followed by level bytes, the PP in `MoveInfo8a`, the curves in `Experience`. The personal
entry says whether a species is in the game at all, 0x21 bit 6, which answers what can be built
without guessing at it: 264 species. `scratchpad/pla_tables.py` reads them and
`scratchpad/pla_make_from_tables.py` composes a record for any of them.

BUILDING ONE. `pokemon.build` assembles a record from 376 zero bytes, writes the fields it is given
over defaults that every captured record agrees on, and writes its own checksum. A field the map
does not cover stays zero, so a record the game accepts from `build` is a record the map covers well
enough. `scratchpad/pla_make_record.py` composes one that way.

## The Clone Clock and Atomic protocols

The band splits the Clone protocol family into separate protocols, each with its own message format
unrelated to the 6.32 clone protocol. The Clone Clock is 0x77 and the Clone Atomic is 0x74.

A Clone Clock message is 18 bytes: a kind byte, a sequence byte, a big-endian u64 originate tick, and a
big-endian u64 responder clock in milliseconds. Kind 0 is a request, whose handler bails unless the
receiver is the master, and kind 1 is the reply that does the work: it checks the sequence, computes an
NTP-style offset, and advances the protocol's state machine. The state at ClockProtocol `+0x5c` runs 0
reset, 1 requesting, 2 synchronised, 3 master, 4 parked. A joining console parks its clock in state 4,
its per-frame tick returning immediately while the state reads 4, and sends a few requests then waits.
A host reply of kind 1, echoing the request's sequence and originate tick and carrying the host's own
millisecond clock, synchronises it: the sequence field increments, the offset field fills with a
computed value, the state leaves 4, and the console stops sending its clock.

A Clone Atomic message is 14 bytes: a kind byte (0 announce, 1 commit, 2 ack), a generation byte, a
big-endian u32 element index rejected unless below 33, and a big-endian u64 value. The element table is
33 slots of 0x18 bytes, each a generation, a state (0 empty, 1 pending, 2 awaiting-commit), a u64
value, and at slot `+0x10` an acknowledged-station bitmap written only by kind 2, after the generation
matches and the sender resolves to a known participant. A participant table indexed by station sits at
the protocol `+0x78`, and the host at station 0 reads 1 there once joined. No inbound kind creates an
element: all three handlers index an existing slot, and kinds 1 and 2 require one already pending.
Elements are created only locally, by the trade scene. A host kind-0 announce draws a kind-2 reply that
echoes the announced value but fills no slot, so the acknowledged bitmap the trade scene's readiness
gate reads cannot be filled from outside; the console populates its own table only once the trade scene
constructs and calls the local announce at `0x6e1e48`.

## Reading and writing a packet

`pokeldn/ldn/pia6.py` speaks version 11: the 0x1C header, the plaintext footer, the session key,
the network id and the IV. The message framing above it is 5.27 to 6.30's, so
`pia5.parse_messages` reads it unchanged. Message flag `0x01` means "skip the source variable id
check" in this band, where at 5.27 it said the destination was a bitmap.

The padding byte is 0xFF at every level, and 0x00 is not a spelling of it. The message walk reads a
presence byte of 0x00 as a legal one-byte header that inherits every field from the message before
it, so a message aligned to four bytes with zeroes makes the game parse a second message out of the
padding, fail, and discard the whole packet with the good message in it. Traced on the game: 31 of
31 packets accepted the first message, then rejected at `0x74419c` over the six bytes after it. The
console pads the same way `pia6` now does, pre-filling its encrypt buffer with 0xFF at `0x6f0af8`
and copying the messages over the front, and `0x6e6cb0` is what makes the block size 16.

`pokeldn/pla/` holds what is true of this title alone: the passphrase, the game key, the local
communication id, and `session_keys(ssid)`, which turns a scanned network's SSID into the session
key and the network id. A scan needs the passphrase to read the advertisement at all.

`tests/test_pia6.py` pins the layout, the derivation against `crypto.PiaCrypto`, the game package
against the band module, both captured advertisements, and every constant read back out of `main`
word by word.

## Hosting

`bin/pla_host.py` advertises Arceus's title, passphrase, scene id and link code, and a console
waiting on its search screen joins. `pokeldn.pla.build_advertise_data(code)` rebuilds either
captured advertisement byte for byte, which is what makes the console recognise the network. The
host authenticates every inbound packet with the session key derived from its own SSID and prints
each Pia message by protocol id.

    sudo ./.venv/bin/python bin/pla_host.py --code 00000000 --seconds 240

A console waiting on the search screen alternates on a five-second cycle: it opens a station and
scans for one second, tears the station down, hosts its own network for two to four seconds,
destroys it, and repeats. Both halves are visible from outside. The network it advertises carries a
new SSID every cycle, and a host it finds during the one-second scan is associated with inside that
window.

A retail console associated with `bin/pla_host.py`'s network 21 times in one four-minute run, once
per cycle, each association ended by the console with a deauthentication, reason 3. That
deauthentication is the end of its own scan phase rather than a rejection.

The copy of the game in Ryujinx, joining the same host over ldn_mitm, gets further and shows what
the silence is. It completes the LDN join, is listed in the host's own SyncNetwork as an accepted
node, binds its Pia socket on port 12345, polls `GetNetworkInfo` every frame for exactly five
seconds, sends no datagram at all, and disconnects itself. Eleven joins ran the same way.

A joiner that sends nothing is waiting to be spoken to. At 6.32 the host opens the exchange with a
Net Protocol connection request and the joiner only ever answers one, which is what
`host_pia.build_net_probe` sends for the GBA app. `bin/pla_host.py` now sends the same message at
this band, protocol 0x2C, repeating every 500 ms until the station answers; `--no-net-probe` holds
it back to measure the silence again.

The console advertises `app_version` 0 and `security_mode` 1, which is what the host sends, so the
advertisement is not what it rejects.


## Reaching local trade on the console

    title screen, A -> Jubilife Village, the trading post -> talk to Simona (Trado in French), A
    -> "echanger des pokemon !" -> local rather than online
    -> the warning that an error temporarily restricts trading
    -> an eight-digit code
    -> "Echange en reseau ! Recherche d'un partenaire en cours..."

The eight-digit code is entered before the search begins, so the session is gated on a link code
the way Let's Go's is. Both consoles enter the same one, and the search screen is where the
advertisement is.

## The advertisement

A console waiting on the search screen creates the network and advertises it. Scanned values:

| | |
|---|---|
| local communication id | `0x01001f5010dfa000`, the title id the binary builds |
| LDN protocol | 1, so the advertisement is AES-CTR, as Sword's is |
| scene id | 1 |
| advertisement frame version | 4, where the GBA app is 3 and Sword 2 |
| accept policy | all |
| participants | 1 of 2 |
| SSID | 16 bytes, and the session key is derived from it |
| application data | 112 bytes |

The application data is the band's 0x5C system property block followed by 20 bytes of the game's
own. The block reads the way `docs/ldn.md` lays it out for 6.16 to 6.41: size 0x5c, system
communication version 21, application communication version 0, a sixteen-byte user password, the
player limit enabled, one player, a name size of 1 with encoding 1, and a name field holding a
single space.

The game's 20 bytes carry the eight-digit code the player typed:

    +0x00  16  the code as ASCII, NUL-padded
    +0x10  4   its length, little-endian

A code of `0000 0000` gives `3030303030303030` followed by eight NULs and a length of 8. The code
is in the clear, so a scan reads it off the air before anything is joined.

### The link code in the advertisement

The sixteen-byte user password in the system property block is the same code, encrypted. The game
hands the code to Pia's password setter `0x6fc454` as the sixteen-byte NUL-padded buffer. With
transport encryption on (session object `+0x230`) in mode 1 (`+0x234`), the setter fills a
sixteen-byte buffer with 0xFE, copies the password over it, and encrypts it in place with
`0x6e68d0`: AES-128-GCM, the sixteen-byte key at session `+0x238`, a four-byte IV, no
additional data, the tag discarded. The IV is four bytes of the key itself, `key[1] key[8]
key[7] key[2]` (`0x6fc4e4` to `0x6fc4fc`). The key at `+0x238` is the game key
`p1frXqxmeCZWFv0X`, set through `0x6fc8a4` with the mode word beside it; the derivation
reproduces both captured passwords with it, and its IV is `1emf`.

One block of GCM is one XOR with a fixed keystream, so the field is the code XORed into a
constant, and a code shorter than sixteen bytes leaves the keystream showing in the tail:

    password = KEYSTREAM XOR (the code's ASCII, NUL-padded to 16)
    KEYSTREAM = AES-128-GCM(key = p1frXqxmeCZWFv0X, iv = 1emf).encrypt(sixteen zero bytes)
              = e5ab19ed742b6d40885998bf968aa166

Five sessions with five different SSIDs, both channels, the codes `0000 0000` and `1234 5678`, and
a full close and reopen of the game give the same keystream byte for byte. The console recreates
its network under a new SSID while the search screen stays up, and the password field does not
follow the SSID. `pokeldn.pla.link_code_keystream` computes the constant from the game key,
`pokeldn.pla.user_password` and `pokeldn.pla.link_code` are the two directions, and
`pokeldn.pla.parse_advertise_data` reads a whole advertisement, checking the code the game states
against the code its password decodes to. The password setter is Pia's, so the same encryption
covers every title of the band ([the wireless layer](ldn.md)).

## Retail

The same host drives a retail console over the air. On 2026-09-18 a record this project built went
into a retail Legends Arceus save: a shiny level-13 Chimchar with perfect individual values and
Swift's mastery bit set, assembled from 376 zero bytes, traded from a French cartridge's own box
screen for a level-59 Ptiravi.

Nothing above the packet layer changed. The retail console associated to the host's AP on channel 6,
completed the Pia session, took the data exchange record, opened the game channel, showed its own
Pokemon, and ran the trade through the same selectors and the same phase chain as an emulated one:
0400, 0500, 0700, then phases 3, 6, 11 and 14 from the host. What the save stored differs from what
was sent in nine byte runs: the checksum, the handling trainer's name, its language, the handler
flag and its friendship. The stats were untouched, because the tail sent is what the game computes.
The handler language it wrote is 3 for a French save where an English one wrote 2.

WHAT THE RADIO NEEDS. The host over the air is `bin/pla_host.py` without `--ip-host`, as root, with
an AP-capable phy. Two flags that do not exist over IP decide whether it reads anything at all: this
machine's TP-Link Archer T3U hands its monitor interface already-decrypted frames that still carry
the CCMP header and MIC, so `skip_encryption` and `accept_decrypted_ccmp` both have to be true. They
come from `config/host.toml` and the host prints them at startup. The advertisement needs nothing:
`pla.build_advertise_data` is byte-identical to the beacon a retail console publishes for the same
link code.

A HOST RESTART COSTS THE CONSOLE ITS SESSION. Bringing the host up without the trade box and
restarting it to enable one left the console joined to an AP that had gone, and its next search
ended in error 2318-0006, a communication error raised before the trade warning screen and so
before anything a failed trade would penalise. The console recovers by leaving the trade menu
entirely and searching again. The host re-reads its offer file between offers, so the record can be
changed without a restart; what cannot be changed that way is a flag.

## Leaving

A console quitting the trade sends the Session type-3 leave request, four times in a burst about
150 ms apart, and closes its ldn_mitm station without waiting for anything:

    03 | u32 random | location id (12) | reason byte | IPv4 (4) | port big-endian (2)

The location id is `pia_connect._location_id`'s, the eight-byte station constant then a zero
halfword then the variable id big-endian, and the address is the station's own. The random word
differs on every send, retransmissions of one leave included, so nothing reads it back, and the
reason byte is 0 on all four captured. The band's type table pairs a leave with no reply: what a
host owes is the type-7 left-station sync to the OTHER stations, and a session of two has none to
tell, which is why a host that answers nothing costs a leaving console nothing.

A console sent one takes it, and the message turns out to be decoration. From a box screen with
nothing offered, about twelve and a half seconds after the host stops the game draws "Your trade
partner chose not to continue trading", and A dismisses it through some three seconds of
Communicating into `DisconnectedByUser`, its station closed and the player back on the field, with no
error code. The control settles what draws it: a host that stops at the same mark and sends no leave
at all, `--leave-sends 0`, produces the same dialog in the same words after 12.7 s against the
leave's 12.5, and the same exit. The two runs differ by four datagrams and by nothing the console
does. So what the game acts on is its own keepalive timeout, it neither shortens nor changes it for a
leave, and a host that simply goes away is as clean as one that announces itself.

The host's own leave is that message with the host's ids and address, `--leave-after SECONDS`.
`bin/pla_host.py` sends it to each station that has joined and ends the run, or with
`--stay-after-leave` keeps the network up and answers that station nothing more. It has no capture
behind it, because no reference session in hand ever ends: the pair capture stops mid-session and
every emulated run so far was quit by the console. What is pinned is the shape, against the
console's four, and that a scripted console reads the host's own leave and finds the host's
location id in it.

A retail console reads it no more than the emulated one does. Four runs over the air, the console on
the box screen with nothing offered, timed by the capture on the host side and the clock on the
console side:

    leave, then the network down          "code d'erreur 2318-0006" within a second
    no leave, network down                the same, within a second
    leave, network up, host silent        "L'autre joueur a choisi d'annuler l'échange" 13 s later
    no leave, network up, host silent     the same words, 13 s later

The console keeps sending to the silent host for those thirteen seconds and stops with the dialog.
What it acts on is the network vanishing, at once, or its own keepalive timeout; the four leaves
change neither the words nor the delay.

## Unresolved

- What a console does with a close announced back on port 1. The host reads the console's close of
  the phase key and answers nothing, and the trade completes; a host announcing its own phase key
  closed is unmeasured.

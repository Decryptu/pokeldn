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

The ten-second leave is therefore not a rejection of any message and not a wait for a handler message:
the trade scene never starts. The leave is a timer whose 10000 ms and 1000 ms constants are written by
the constructor `0x2bcc43c` into an object of the same vtable family as the one that runs `LeaveAsync`.
The missing condition is whatever constructs the trade scene, above the session and the transport.

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

The sixteen-byte user password in the system property block carries the same code, XORed into one
constant:

    password = LINK_CODE_MASK XOR (the code's ASCII, NUL-padded to 16)
    LINK_CODE_MASK = e5ab19ed742b6d40885998bf968aa166

Five sessions with five different SSIDs, both channels, the codes `0000 0000` and `1234 5678`, and
a full close and reopen of the game give the same mask byte for byte. The console recreates its
network under a new SSID while the search screen stays up, and the password field does not follow
the SSID. The mask is not a literal anywhere in `main`, so what produces it
is unread. `pokeldn.pla.user_password` and `pokeldn.pla.link_code` are the two directions, and
`pokeldn.pla.parse_advertise_data` reads a whole advertisement, checking the code the game states
against the code its password decodes to.

## Unresolved

- What produces `LINK_CODE_MASK`. It survives a game restart, so it is not per-boot, and it is not
  a literal in `main`. Whether it is per-title or per-console cannot be separated here: one console
  runs this game.
- Everything above the packet header: the station handshake and the game's own message layer.

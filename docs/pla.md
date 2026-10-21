---
title: Legends Arceus
nav_order: 8
has_children: true
---

# Legends Arceus

Pokemon Legends: Arceus (title id `01001f5010dfa000`) is a native Switch title with Pia 6.16-6.23
statically linked into `main`. Addresses are offsets into the decompressed `main` of update 1.1.1 as
`tools/switch/nso_read.py` lays it out (text `0x0..0x32a5690`, rodata from `0x32a6000`, data from
`0x401a000`).

## The wireless layer

| | value |
|---|---|
| Pia header version | 11 (Sword 4, BDSP 9, GBA app 15/16) |
| header size | 0x1C |
| GCM tag on the wire | 8 bytes, truncated from 16 |
| LDN passphrase | Sword/Shield's, the `HGhG` spelling (the wiki's `HGHG` row is wrong); rodata `0x3985319` |
| Pia game key | `p1frXqxmeCZWFv0X`, as Sword/Shield and Scarlet/Violet; rodata `0x3985308` |
| LDN local communication id | `0x01001f5010dfa000`, the title id |

The LDN setup `0x2c1e684` takes the local communication id in `x3` (built at `0x264082c`) and installs
the game key at `0x2c1e880`. The header initializer `0x6f0744` stores the magic at object `+8` and
`0x0b` at `+0xc`; the validator `0x6f07d0` checks the magic, `(byte & 0x7f) == 11` and length minus
0x1C below 0x5a5. The packet buffer is at `+0x30` (capacity 0x5c0), the length at `+0x5f8`; field
sizes come from the copy assignment `0x6f0878`:

    wire  object  size  field
    0x00  +0x08   4     magic 0x32AB9864, big-endian
    0x04  +0x0c   1     0x80 (encrypted) | version (0x7F) = 11
    0x05  +0x0e   2     destination variable id
    0x07  +0x10   2     source variable id
    0x09  +0x12   2     packet id
    0x0b  +0x14   1     footer size
    0x0c  +0x15   8     AES-GCM nonce
    0x14  +0x1d   8     AES-GCM tag, truncated from the 16 the object holds
    0x1c                ciphertext, then the plaintext footer

The encrypt path `0x6f09f4` subtracts the footer, 0xFF-pads to the block size, encrypts from buffer
`+0x4c`, writes the tag through the GCM entry `0x6e68d0` with tag length 8 (`0x6f0b24`), then ORs
`0x80` into the version.

Breakpoints: socket read `0x6ff6d8`, validator `0x6f07d0`, decrypt `0x6f0b84` (failing here is key,
IV or tag), `LdnBackgroundProcessJob::WaitConnected` `0x7015b4`.

The dispatch key is the packet's source variable id: a message from a station missing from the
registry is skipped, and variable ids re-roll every session. Message flag `0x01` skips the source
variable id check; `bin/pla_host.py` sets it on both probes.

## The packet crypto

| | |
|---|---|
| session key | `AES-128-ECB(game key)` over one block of the network SSID |
| network id | CRC-32 of `ssid[1:16]` |
| GCM IV | `u32be(network id XOR source IP)` then the header's eight nonce bytes |
| header nonce | a per-packet big-endian counter |
| tag | the first 8 bytes of the GCM tag |

`0x70d61c` derives the session key; `LocalOutputStream::vfunc3` (`0x711710`) builds the IV.
`pokeldn/ldn/crypto.py` covers 6.16 to 6.42.

## The protocols above the packet

Pia 6.16 to 6.30 keeps the 5.29 to 5.45 ids below the session layer and replaces the station and mesh
protocols with one Session Protocol:

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

`pia_connect.py` fits this band with the ids renumbered. The console's join request lists:

    Net 0x2c v0   RTT 0x58 v3   Unreliable 0x68 v1   Clone 0x74 v0   Clock 0x77 v0
    Reliable 0x7c v2   BroadcastReliable 0x80 v3   0x81 v3   Session 0x98 v0   Monitoring 0xa4 v0

A message ends where its payload ends; this band does not align messages to four bytes (5.27-5.45
does). The padding byte is 0xFF at every level: the message walk reads a presence byte of 0x00 as a
one-byte header inheriting the previous message's fields, so zero padding makes the packet fail
(`0x74419c`). The console pre-fills its encrypt buffer with 0xFF at `0x6f0af8`; `0x6e6cb0` sets the
block size to 16. `pokeldn/ldn/pia6.py` speaks version 11 and `pia5.parse_messages` reads the framing.
`tests/test_pia6.py` pins the layout, the key derivation, both captured advertisements and every
constant read out of `main`.

| protocols | header destination | footer |
|---|---|---|
| Session, Clone Clock, Reliable | the peer's variable id | none |
| RTT, Stream Broadcast Reliable | mesh destination 0x0001 | the recipient's variable id, plaintext |

A 0x81 message addressed to the peer's variable id in the header never reaches the game.

### The Net Protocol

A console hosting its own network opens with `NetUpdateNetworkConnectionStatusMessage` (0x2C type
0x11), the wiki's 6.16 to 6.39 layout:

    01 11 002a          header version 1, type 0x11, payload size 0x2a
    00000002            sequence id
    eb6f                host variable id, fresh every session
    ac56011000020000    host constant id, ldn_constant_id of 02:00:ac:10:56:01
    000000004f264487    network id, the low four bytes crc32(ssid[1:16])
    01                  is network open
    0002                number of stations
    00                  is migrating host
    ...                 NetStation entries, 21 bytes each (6.39 has 22)

    NetStation  +0x00 1 migration state   +0x01 1 migration ranking
                +0x02 1 one byte where 6.39 has two (disconnection candidate, kicking)
                +0x03 18 16-byte address then big-endian u16 port (12345)


### The Session join request

A 115-byte Session type 0: the type byte, a protocol count, the ten `(id, version)` pairs, then:

    +22  4   random, fresh on every repeat (docs/sv.md, The Session join request)
    +26  8   source constant id
    +34  2   zero
    +36  2   source variable id, fresh per session
    +38  1   NAT mapping
    +39  1   private-IPv6 flag
    +40  32  identification token, zero on a codeless join
    +72  1   address kind, 0 for IPv4
    +73  4   source IPv4 address
    +77  2   source port, 12345
    +79  8   destination constant id
    +87  2   zero
    +89  2   destination variable id
    +91  1   player count, 1
    +92  1   a flag, 1
    +93  22  one player record: id (two big-endian u64, 1 and 0), big-endian u32 name length 1,
             kind byte 1, the name, a single space

A location id is 12 bytes: big-endian u64 constant id, two zero bytes, big-endian u16 variable id.
Message flags are `0x01`. `pokeldn.ldn.pia6.build_session_join` reproduces it
(`tests/test_pla_session_v11.py`).

The host's `ClusterPacketReader` gate `0x744644` (vfunc `0x98`, called at `0x743ec0`) looks up a
unicast packet's source variable id among its stations (`0x744718`) and drops it when none matches
(`0x7447a8`); a packet to destination 0 or 1 with no footer, or from source variable id 0, skips the
lookup. A join request must go to header destination 0; addressed to the host's variable id it is
dropped after decrypt.

### The Session join reply

The joiner parses the ack at `0x737534` and the join response at `0x7379c0`, dispatched from
`0x7353a0` through the type table `0x3973f19`. Each drops a message whose four ids do not match: the
host's ids are the request's destination ids, the console's its source ids.

The ack is type 1, 25 bytes: type, host location id, console location id. It sets `JoinMeshJob+0x69`
and extends the deadline `+0x80` by 8000 ms. The join response is type 2, 43 bytes:

    +0x00  1   02
    +0x01  2   protocol id 0x98 and Session version, read only when status is 3
    +0x03  1   status, 1 accepts
    +0x04  8   unread on accept
    +0x0c  12  host location id
    +0x18  12  console location id
    +0x24  2   route bytes, to self station +0x90, +0x91
    +0x26  1   station index
    +0x27  2   join order, big-endian
    +0x29  2   sequence id, big-endian

The assignment fields are not validated (a first joiner gets route `00 01`, index 1, order 1).
Status 1 stops the repeats. The join completes when a type-5 update reaching `+0x29`'s sequence is
applied; the joiner answers with a 13-byte type 6: type, own constant id, two zero bytes, sequence.

### The type-5 station-list update

`0x7404a8` reassembles it before `0x73897c` reads it. The fragment header is 7 bytes: type,
big-endian u16 sequence, count, index, big-endian u16 offset (3 for the single fragment). The body:

    +0x00  1   05
    +0x01  2   sequence id
    +0x03  8   host constant id
    +0x0b  4   host variable id as [0000, u16]
    +0x0f  1   station count, at most 0x18
    +0x10  n   IPv6 bitmap, (count + 31) / 32 * 4 bytes, little-endian words
       ...     station entries (0x739050), IPv4 form:
    +0x00  8   constant id         +0x15  2   join order
    +0x08  4   [0000, u16] var id  +0x17  1   NAT mapping
    +0x0c  4   IPv4 address        +0x18  1   private-IPv6 flag
    +0x10  2   port                +0x19  32  identification token
    +0x12  1   route byte A        +0x39  1   player count
    +0x13  1   route byte B        +0x3a  1   participant count
    +0x14  1   station index       +0x3b  ..  player records (16-byte id, u32 name length,
                                              encoding byte, name)

An IPv6 station carries 18 address bytes in place of six. The host is route `00 00`, index 0, order 0.
`0x738bc0` updates or creates each station by constant id. A joined console then runs RTT, Clone
Clock and the Stream Broadcast Reliable stream.

### Host migration

A console hosting a trade answers no join request addressed to its variable id and asks the joined
station to take the host role:

| joiner | console |
|---|---|
| answers 0x11 with 0x12 | 0x11 again, `is migrating host` 1, then `01 40 00 00` (`NetStartHostMigrationMessage`) about twice a second |
| sends the join request, never answers 0x11 | 0x11 every 0.5 s, then migrating, then 0x40, then the network drops |
| answers with `NetUpdateNetworkHostMessage` | keeps repeating 0x40 |

A hosting console leaving always migrates (`NetProtocol+0x248`, set to 1 by its constructor):
`NetDestroyNetworkJob` (`0x7069d0`) sends a migrating 0x11, waits up to 4000 ms for every 0x12, sends
0x40 every 300 ms for 4000 ms (2000 ms after an unacknowledged 0x11), then destroys the network.
`LeaveMeshWithHostMigrationJob` (`0x73eee4`) first polls up to 8000 ms for a next host; a station with
route bytes at 0xfd never qualifies.

The type 7 naming a successor comes when the console's WaitMember ends before the join is accepted,
as on Scarlet ([docs/sv.md](sv.md#what-decides-a-seat)); `bin/pla_join.py --join-delay 4.5` draws
it. The console resends it every second until a type 8. The type-8 handler `0x739b08` takes only a
25-byte message whose second location id is the console's; `0x73f0a8` sets the job's done flag `+0xb0`
when the first equals the target at `+0x68`:

    08 | joiner location id (12) | host location id (12)

The new host completes the migration by creating a network on the same code; the console joins it
and trades as joiner. `bin/pla_join.py` leaves the seat on the first 0x40 and runs `bin/pla_host.py`
on the same code and channel, or over IP with `--ip-join` (`--take-host`, on by default).

## The silent-station check

Every Session update (`0x73564c`) lists each station silent for longer than `SessionProtocol+0xd8`,
10000 ms (from the startup setting `+0x28c`, no lower bound; Z-A has a 4000 ms floor). After a further
3000 ms the host kicks each (`KickoutManageJob`) and a joiner treats a listed host as gone. A silent
host on the box screen draws the partner-left message about 13 s in.

## The game's reader and the pre-handler phase

The game polls its reader at `main+0x2ca4f30` (`0x741494`): loops over 0x7C and 0x80 sharing one
handler table. A message's first eight bytes are a two-u32 handler key; the matched handler receives
the rest, an unmatched key is discarded. Host data on 0x81 never reaches it. The game's nine Pia call
sites resolve only 0x68, 0x7C and 0x80; 0x77 clock traffic is Pia's own.

At the search screen the table is empty and every message is drained unread; handlers are
registered at flow step 0x1e (`0x2ca5264`).

The trade flow is `0x13d5bfc` (step `[flow+0xa4]`, table `0x397c118`). Step 0x17 builds the matching
sequence (`0x26bdcac`); step 0x18 polls it and the network menu's page result (`0x13de870`). The
sequence's steps:

    LoginRelayServer     looked up before the sequence is built; missing returns false
    Matching             from TradeMatchmakingConfig (0x26be354)
    DataExchangeStart    the two-round data exchange, 10.0 s deadline (0x26be3f0)
    OnCancelDataExchange
    OnSuccess            the trade scene (0x26d5f64)
    OnFailure            event 8, flow step 0x23 (table 0x397c134), the leave
    OnCancel
    Cleanup

DataExchangeStart (`0x26c5288`) starts on an established session and completes once at least two
stations' records have arrived; past 10.0 s (`0x26c6a94`) it fails with
`net_contents::p2p::ErrorLeaveAnyone` (vtable `0x416c628`, `0x26c6d30`). The failure runs `0x13d654c ->
0x13d6384 -> 0x2c43d78 -> 0x2ca0a10 -> Session::LeaveAsync (0x72a6dc)`, then the Error 7 dialog; the
host leaves with migration.

`Error::Timeout`'s only producer is the watcher `0x2bdb754`, armed in two WaitMember steps of the
matchmaking: 25000 ms (`0x2bda24c`) and `3000 + rand % 1000` ms (`0x2c491b8`, target the matchmaking
record's `+0x22` halfword, 2 under code 00000000). WaitMember completes when the member count
(`[Session+0xe0]`, the Pia Session member list) reaches its target; nothing extends the timer. The
list holds the local station and one entry per accepted Session join (on a joiner, each type-5
station); LDN association or Net 0x11 alone is not counted. A search with no member re-hosts on that
timer, a new network with a new session id every 2.4 to 4.3 s, so a joiner has the remainder of one
network's timer to be counted.

### The data exchange

DataExchangeStart waits for a two-round exchange on Stream Broadcast Reliable (0x81), ports 0 and 1:
each station opens the stream with a type-0x0f message, acknowledges with the 44-byte `0000002c ffff`
message under flags 0xa0 and sends one 74-byte type-0x1f record carrying a 64-byte payload beginning
`484b6264`. The step completes on the peer's second-round record. A joining console opens its stream
unprompted and sends its record after the host's; a hosting console sends first, on the joiner's
open. A host answering the console's open bundles the record on port 0 and its own open on port 1 in
one packet; `bin/pla_host.py` sends it once per join, and lost on the air it ends in Error 7.

The 64-byte payload is zlib (4 KB window, level 5) of a 139-byte record (`pokeldn.pla.data_exchange`),
one chunk under Pia's StreamData header ([Protocol 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)):

    +0x00  1   StreamData kind, 1: first chunk
    +0x01  1   transfer id, 0
    +0x02  1   percent delivered, 0x64
    +0x03  4   zero
    +0x07  4   big-endian u32 0x80
    +0x0b  128 the MyStatus block (PKHeX MyStatus8a): trainer id pair +0x1b, version +0x1f (47),
               gender +0x20, language +0x22, UTF-16LE name +0x2b

The game hands Pia the block alone (`0x753554` at `0x26bfd28`). A gift made for the receiving player
reads the console's trainer (`data_exchange.read_trainer`, [Made for the receiving
player](gift_simulated.md#made-for-the-receiving-player)).

Block +0x3c is the player's look, column + 4 x row of the intro's 4x2 `grid_player` (setter
`0x1023f94`), columns 2 and 3 female; it must agree with the gender at +0x15.
`data_exchange.build_record` sends 5 male, 7 female, by `--gender`. Block +0x50 is 1, written by the
initializer `0x10230e4`.

## Sustaining the mesh

RTT (0x58) is 11 bytes: kind, eight-byte timestamp, two-byte target; a kind-1 echo with target 0 is
accepted.

Stream Broadcast Reliable (0x81) carries the `pokeldn/ldn/reliable5.py` window: the 9-or-13-byte
header, then data or, with the data flag clear, a bulk ack of `2 + 21 * count` bytes (type byte, bit 0
read; entries of station byte, u16 ack id, u16, 16-byte mask). The consumer (vf13 `0x742730`) reads
the entry at its own station index and requires its station byte to equal the sender's index: a host
acking a joiner at index 1 sends two entries with station byte 0. The id applies through `0x74f0ec`.
A console's 0x81 message carries sequence 1, so a host acknowledges `ack_id 2`.

The console opens its stream with an INITIALIZED message (flags `0x0f`, seq 1); host data needs the
destination bitmap bit of the console's station index (bit 1, count 2).

## The game's reliable channel

After the exchange the flow reaches `0x13d5cac`, which tests `[net+0xb8] > 1`: state 0 to 1 through
`0x26d9170`, 1 to 2 on `[net+0x78]`, set by the receive handler `0x26da310` on selector 1
(`0x26da3a4`).

The dispatcher `0x2ca4a88` matches a message's key against each channel's `+0x6c`. Two channels
exist: key `00 00 00 00 00 00 00 00` for the trade box (`0x26d8c2c`), `01 00 00 00 00 00 00 00` for
the phase protocol (`0x26d7aa0`). Ports 0 and 1 of 0x7c are two Reliable instances; port 1 is the
channel table.

Both ports open with a `reliable5` stream (no bitmap, to the peer's variable id, sequence 1,
start, end and initialized flags); each side acknowledges and sends the same back:

    port 0    key eight zero bytes      body 0100        the host opens it
    port 1    b9 01 01 b9 02 b9 02 00 00 01              the joiner announces the zero key open

### Acknowledgement

`ReliableSlidingWindow` (vtable `0xc5b4d98`) builds its ack in vf12 `0x74ee1c`: id the receive
window's `+0x50`, one bit per held entry past it in a 16-byte mask (`0x74ef18..0x74efb8`), empty while
`[window+0x54]` is set. vf13 `0x74efbc` parses it (`0x742da0`), requires `2 + 21 * count` bytes and
the entry's stream byte equal to `+0x36`, and calls `0x74f0ec(window, station, ack_id, mask)`. A send
entry is 0x5d0 bytes, sequence `+0x24`, per-station pending bitmap `+0x2c`:

| entry sequence | pending bit |
|---|---|
| below `ack_id` | cleared (`0x74f274`) |
| equal | kept |
| above | cleared when mask bit `seq - ack_id - 1` is set, offsets up to 0x7f (`0x74f280..0x74f2a8`) |

| `ack_id` | effect |
|---|---|
| 0 | nothing (`0x74f0fc`) |
| below the base | sets `[window+0x4b8]` (`0x74f17c`, `0x74f2d0`) |
| `base + count` (`[window+0x32]`) | releases everything |
| beyond | vf6 `0x74f2e8`, a bare `ret`: ignored |
| `0xffff` | applies the whole window (`0x74f104`) |

The id is cumulative; the mask is bit n of a 128-bit little-endian integer
(`pokeldn.ldn.reliable5.build_mask`).

The receiver moves its window base on every message's lowest-pending field, acks included
(`0x74c250`). Never declare a lowest pending past an unacknowledged message: its resend lands below
the base and is dropped.

`bin/pla_host.py` and `pokeldn.pla.joiner` use `reliable5` (`SendWindow`, `ReceiveWindow`): keep
each 0x7c message until acknowledged, resend after 0.4 s with the same sequence and a new nonce,
declare at most their own lowest unacknowledged sequence, acknowledge one past the contiguous run,
deliver in order once. The joiner's 0x81 messages resend every 1 s. A console's first 0x7c message on
a port carries sequence 1 (66 of 66).

The console resends 0x7c and 0x81 alike (`0x74c9c8`) every 33 ms + 1.4 x the largest round-trip
(`0x74d06c`) with no retry limit, until an in-window ack or the station leaving.

## The channel table on port 1

Port 1 of 0x7c carries the channel table: each station announces the handler keys it has open, and a
station sends on a key only after its peer announced it open.

The table object (`0x2ca36f0`, vtable `0x41997d8`) keeps its own channels (`+0xa0`) and the peer's
announced ones (`+0xd8`), each entry an eight-byte key and a station mask; the frame poll `0x2ca82d0`
sends and receives.

The sender announces an existing channel as open and a destroyed one as closed. The receiver
(`0x2ca9800`) ORs the sender's bit into the peer entry on open and clears it on close, appending an
entry for an unknown key; the collector erases zero-mask entries, and a leaving station's bit is
cleared everywhere (`0x2ca90e0`). A channel created (`0x2bcb8c8 -> 0x2ca5264 -> 0x2ca3024`) keeps the
table's interface at `+0xb8`. Every channel sender asks interface slot 3 (`0x2ca92e0`, through
`0x2ca9360`) whether the peer announced its key and sends only on yes: a host silent on port 1 leaves
the trade screen waiting.

A message is the game's tagged serialisation: an integer below 0x80 is its own byte; 0x80 to 0x83
prefix a little-endian 1, 2, 4, 8-byte value (writers `0x2661ec4`, `0x26619cc`, `0x2661f78`). The
size table `0x397dfcc` gives 0x84 to 0x87 the same widths, 0x88 four bytes, 0x89 eight, 0xb5 to 0xbf
one. 0xb9 opens a tuple, followed by the field count.

    b9 01  NN  { b9 02  b9 02 LO HI  01|00 }    list of NN (key as two u32, open 1 / closed 0)

| message | meaning | when |
|---|---|---|
| `b9 01 01 b9 02 b9 02 00 00 01` | trade box key open | with the port-1 open, at the trade step |
| `b9 01 01 b9 02 b9 02 01 00 01` | phase key open | after the confirmation, when `0x26d7aa0` creates it |
| `b9 01 01 b9 02 b9 02 01 00 00` | phase key closed | once the trade is written |

`pokeldn.ldn.channel_table` builds and parses these. The host answers each open once per key and
leaves a close unanswered, so its standing entry serves the next trade.

## The trade box

On port 0 behind the zero key, the handler `0x26da310` reads a selector and a counter, switches
through `0x397e388`, drops anything above 7, and aborts unless its fourth argument equals
`[net+0x88]`, the partner.

    1   ready                0x26da3a4   sets [net+0x78]; the port-0 open body 01 00, once a session
    2   showing a Pokemon    0x26da3f0   stored at [net+0x98] by 0x26da1d8
    3   showing no record    0x26da430   -> 0x26d93c8
    4   offering a Pokemon   0x26da3b0   stored at [net+0xb0] by 0x26da23c, phase 0xbc := 3
    5   confirmed            0x26da43c   counter check, -> 0x26da2c0
    6   withdrawn            0x26da458   state 4|5 := 3, phase 0xbc := 2, counters moved
    7                        0x26da49c   counter check, phase 0xbc := 5

`0x26d9458` sends selector 2 with the record under the cursor (0x178 bytes from `0x2b65514`), or
selector 3 with no body for an empty slot (`03 00`). Selectors 2 and 4
carry the same body; only 4 moves the phase. A host must answer an offer with an offer: answered with
a showing, the console shows an empty partner hexagon.

Selector 6 takes back an offer or a confirmation (sender `0x26d9898`, counter `[net+0xf8] + 1`). The
receive arm returns the state to 3 and sends nothing: an echoed 6 un-confirms the console.

The body (`0x26dac6c`, `0x26662fc`, `0x26dacbc`):

    0x00  1   selector
    0x01  1   counter, 0 on both record-carrying selectors
    0x02  1   0xbc
    0x03  1   0x81
    0x04  2   record length, 0x178
    0x06  376 the record

390 bytes under a nine-byte header, flags 0x07, sequence 2. It depends on the save alone, so a capture
replays.

The record is the Gen-8 entity (`pokeldn.gen8` header, LCG, block permutation, 16-bit checksum) with
0x58-byte blocks: 0x168 stored, 0x178 in the party. `gen8.BLOCK_ORDER[(ec >> 13) & 31]` is applied
as it stands when decrypting and inverted when encrypting; the checksum cannot tell the two apart, the
names can (nickname at 0x60, trainer name at 0x110). The trainer id at 0x0c and the trainer name are
the ones the data exchange carries.

## Confirming the trade

Trade it sends selector 5 and `[net+0xf8]`. The sender `0x26d9770` requires state 3 and sets 4. The
consumer `0x26da2c0` sets phase 4 and, when the state is already 4, allocates `[net+0xc8]`: the second
station to confirm goes on. Selectors 5 and 7 drop a counter below `[net+0xfa]` (`0x26da440`,
`0x26da4a0`). The console then announces the phase key open on port 1 and waits at phase 5 until the
host announces it too.

The tick `0x26d9094` moves `[net+0xb8]`:

    0     if [net+0x90] is set, 0x26d9170 -> 1
    1     once [net+0x78] is set, one store of 0x200000002: state 2, phase [net+0xbc] 2
    3, 4  while [net+0xc0]: past 1.5 s on [net+0xc8] with phase 4 or 5, 0x26d9254 sends
          selector 7, state 5
    5     finished; the save is untouched until the job below

## The job that carries the trade out

The job (`0x26d9a90`, vtable `0x416c8f8`, update `0x26dc71c`, executor `[job+0x130]`) carries the
offered record `[net+0xb0]`.

| state | does |
|---|---|
| 1 | send phase 3 (`0x26d7d8c`); state 2 only when the send succeeds |
| 2 | wait for the host's `02 03` (`0x26d7e5c`) |
| 3 | the trade restriction set and saved (vf `+0x50` `0x26dd910`) |
| 4, 5 | send phase 6, wait for `02 06` |
| 6 | the trade applied, the restriction cleared (vf `+0x58`) |
| 7 to 10 | send `0x0b` (after a random 2 to 302 frames in state 9), wait for `02 0b` |
| 11, 12 | commit the save (`nn::fs::Commit`), send `0x0e` |
| 13 | wait for `02 0e` |
| 14 | success (`[net+0xb8] = 6`) or failure (7) |

A failed send gate retries the next update; a job held at state 1 or 2 has no timeout and shows
`msg_ui_box_p2ptrd_09`, "Communicating. Please stand by...". It ends only by the cancel request
`0x26dc640`, from the scene monitor `0x1109d00` on a session error or the partner gone (station count
below 2), or from mode 9. The console has nothing outstanding while it waits: the host resends any of
its eleven answers lost on the air (port-0 open, two channel opens, showing, offer, selectors 5 and 7,
four phases).

Cancel is taken in states `0x3ff7 >> state & 1` (0 to 2, 4 to 13). Cancelled at phases 2 to 4 the
executor finishes the save first; vf `+0x48` `0x26dd5f8` writes only with `[executor+0xb0]` set, done
at state 6. A job cancelled at state 1 or 2 writes nothing.

## The trade restriction

The restriction is a u64 count of minutes in save block `0x96993D83`, field `+0x70` of the object at
`[game manager+0x2b8]` (vtable `0x40f2048`). Block `0x24E0D195` (field `+0x78`, 0x2F2 bytes) holds a
flag byte, then the record most recently traded in.

The byte at `+0x78` marks a received record not yet placed: set at job state 6 (`0x10251c8`, record
at `+0x79`, an evolved form at `+0x1f1`), cleared by `0x26dcc74`, which places the record, registers
it in the dex and saves.

| site | caller | value | when |
|---|---|---|---|
| `0x26dd9a0` | vf `+0x50`, job state 3 | 10 | after the partner's `02 03`, before either record moves |
| `0x26ddaf0` | vf `+0x58`, job state 6 | 0 | the trade is applied |
| `0x26dd704` | vf `+0x48`, the cancel | 10 | only with `[executor+0xb0]` set |
| `0x26bd5d0` | ticker `0x26bd434` | minus 1 | every 60 s |

State 3 saves after setting 10. A trade stopped before state 3 draws no restriction; one stopped
between state 3 and the save after state 6 leaves 10 in the save.

The ticker (`0x26bd434`) decrements once per 60.0 s of the OS tick (`0x26bd5b4`): ten minutes of
the game running clear it. Clock settings play no part, and time with the game closed is not counted.

While the count is non-zero, Link Trade's partner menu (`0x13d55fc`, `0x13d56ac`) shows
`common/net` `matching_win_03` (the last connection was interrupted) instead of the warning
`matching_win_06`.

## The phase protocol

The job announces phases on key `01 00 00 00 00 00 00 00`, registered when the job is created. The
announcing object keeps three flag/halfword pairs:

    [obj+0x94] / [obj+0x96]   own announced phase, written by 0x26d7d8c (selector 1)
    [obj+0x98] / [obj+0x9a]   the peer's, on receiving selector 1
    [obj+0x90] / [obj+0x92]   written by 0x26d7e84 (selector 2), and on receiving selector 2

The receive handler `0x26d7f90` mirrors the senders; selector 0 aborts. The message is the selector
and the phase. `0x26d7e5c(obj, n)` returns `[obj+0x92] == n` with `+0x90` set.

Selector 2 is the host's to send: `0x26d7e84` is reached only behind `[obj+0x78]`, set at job creation
by `0x26d7aa0` when the station is the session's host. A joiner's job leaves state 2 only on the
host's selector 2; a host that only mirrors selector 1 leaves the trade screen waiting.

Every message a station originates on a port, mirrors included, takes its own next sequence id; a
mirror reusing the peer's id is acknowledged but discarded once the counts diverge.

## The completed trade

The console announces 3, 6, 0xb and 0xe; the host answers each with selector 2 and the same phase:

    <-  0x7c p0  01 03      ->  01 03   the mirror     ->  02 03   the host's
    <-  0x7c p0  01 06      ->  02 06
    <-  0x7c p0  01 0b      ->  02 0b
    <-  0x7c p0  01 0e      ->  02 0e

After the animation the box names the host's player as the original partner. Eight save files
change: `main`, `main2`, `backup` in both slots, both ExtraData files. The console then sends a fresh
selector 2, which the host answers with a showing, and the phase key close, left unanswered.

## A second trade in one session

After a completed trade the scene resets the trade object (`0x26d8fd0`, at `0x110aa04`): job inputs
and records released, the job freed, state and phase 2, counters `[net+0xf8]` zeroed. `[net+0x78]`
and `[net+0x88]` are kept: the next round starts at state 2 with no new selector 1.
The scene (update `0x1109a68`, mode `[scene+0xb0]`: 0 box, 5 trade, 6 partner gone, 7 and 8 session
error, 9 leaving) returns to mode 0 with the session up. `0x10fb178` clears the box controller's valid
flags, so the box sends a fresh showing; otherwise it sends one only when the cursor moves.

The next job creates its phase channel with key 1 again and uses the same phases. A second trade
repeats `05 00`, `07 00`, the phases and the phase key open byte for byte; only sequence ids differ, so
a peer deduplicating by body answers none of them. A host that answered the console's close leaves the
second `01 03` held in the gate: job at state 1, no timeout, no restriction.

## What a trade rewrites

A received record differs from the one sent in these fields (23 bytes for a level-50 record sent with
a level-70 party tail):

    0x006  2   checksum
    0x092  1   current HP
    0x0b8  26  handling trainer's name, the receiver's own
    0x0d3  1   handling trainer's language (3 French, 2 English)
    0x0d4  1   current handler, 1
    0x0d8  1   handling trainer's friendship, the species' base friendship
    0x16a  12  the six party stats, recomputed

A met level above the level is kept. Block starts are `pokeldn.gen8`'s plus eight bytes per preceding
block: nickname 0x60, handling trainer name 0xb8, trainer name 0x110, party tail 0x168. The first
block is Gen 8's except the moves (0x54, PP 0x5c), the second plus 8, the third plus 0x10, the fourth
plus 0x18 with the ball after the met date. `pokeldn/pla/trade_box.py` and `pokemon.py` reproduce a
console's bytes.

## Choosing what to offer

The game reads PKHeX's PA8:

| offset | field | offset | field |
|---|---|---|---|
| 0x08 | species | 0x92 | current HP |
| 0x0a | held item | 0x94 | packed individual values |
| 0x0c | trainer id, 32 bits (shown modulo 1000000) | 0xa4 | growth values |
| 0x10 | experience | 0xac, 0xb0 | absolute height, weight (floats) |
| 0x14 | ability | 0xb8 | handling trainer |
| 0x16 | alpha bit | 0xee | version |
| 0x1c | personality value | 0xf2 | language |
| 0x20 | nature (9 is Lax) | 0x110 | trainer name |
| 0x24 | form | 0x134 | met date |
| 0x26 | effort values | 0x137 | ball |
| 0x3e | alpha move | 0x138, 0x13a | egg and met locations |
| 0x50, 0x51, 0x52 | height scalar, weight scalar, scale | 0x13d | met level and trainer gender |
| 0x54, 0x5c | moves, PP | 0x159 | purchased move record |
| 0x60 | nickname | 0x15d | mastered moves bitmap |
| 0x8a | relearn moves | 0x168, 0x16a | level, six stats |

Across 47 captured records alphas carry 0xff in 0x50 to 0x52, the scale equals the height scalar,
0x94 has the egg and nickname bits clear, and every record carries version 47, language 2, sanity 0
and affixed ribbon 0xff. `pokemon.build` writes the given fields over those defaults on 376 zero
bytes and the checksum. Composed records (shiny, alpha, nicknamed, species the save never held) trade
in and display as sent. A record whose encryption constant and PID the save already holds is stored
(box block `0x47E1CEAB`); `--fresh-pid` re-rolls both.

`bin/pla_host.py` processes each `(port, sequence id)` once, in order, and resends unacknowledged
answers; a cancelled offer is re-offered as `04 01`. It re-reads its offer file between offers.

### Mastered moves

The eight bytes at 0x15d are a bitmap over the game's 61-move mastery list; a species may master only
those its personal entry permits (u64 at 0xa8). The Change moves screen allows a move whose mastery
level (`mastery_la`) is at or under the level or whose bit is set.

### The stats the game computes

`pokeldn/pla/stats.py` reproduces them. Each stat is a growth term, rounded `(sqrt(base) * multiplier
+ level) / 2.5`, plus a base term: `((level / 100 + 1) * base)` truncated plus the level for HP,
`((level / 50 + 1) * base / 1.5)` truncated with the nature at 110% or 90% for the rest. The
multiplier is read by growth value plus an individual-value bias (3 at 31 and above, 2 at 26, 1 at
20), clamped at 10. Verified on twelve console numbers at level 68, nature 14, Gengar:
273/210/199/322/345/220 (IVs 31, growth 10) and 239/136/121/322/304/133.

Height and weight at 0xac and 0xb0 are the species average times `(scalar / 255) * 0.40000004 + 0.8`
per scalar, both scalars for weight, in 32-bit floats (scalars 111, 221, averages 150, 405 give
146.11766052246094 and 452.38031005859375). Tables come from PKHeX: `personal_la` (0xB0 bytes an
entry; 0x21 bit 6 marks the 264 species in the game), `lvlmove_la.pkl`, `MoveInfo8a`, `Experience`.

## The Clone Clock and Atomic protocols

A Clone Clock (0x77) message is 18 bytes: kind, sequence, big-endian u64 originate tick, big-endian
u64 responder clock in ms. Kind 0 is a request (ignored unless master); kind 1 the reply, advancing
ClockProtocol `+0x5c` (0 reset, 1 requesting, 2 synchronised, 3 master, 4 parked). A joining console
parks in 4 and sends requests; a kind-1 reply echoing sequence and tick with the host's clock
synchronises it.

A Clone Atomic (0x74) message is 14 bytes: kind (0 announce, 1 commit, 2 ack), generation,
big-endian u32 element index (below 33), big-endian u64 value. Only the trade scene creates elements;
a host kind-0 announce draws a kind-2 echo that fills no slot.

## Hosting

`bin/pla_host.py` advertises the title, passphrase, scene id and link code;
`pokeldn.pla.build_advertise_data(code)` rebuilds a retail advertisement byte for byte (`app_version`
0, `security_mode` 1).

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/pla_host.py --keys PROD_KEYS \
        --code 00000000 --seconds 240

A console on the search screen alternates scanning as a station and hosting under a new SSID, a
cycle of about five seconds. An associated joiner stays silent until the host sends the Net 0x2C
connection request every 500 ms (`--no-net-probe` holds it back).

## Joining a console's network

`pokeldn.pla.joiner` answers a hosting console:

| the host sends | the joiner answers |
|---|---|
| Net 0x11 | Net 0x12 echoing the sequence, flags `0x11`, header destination 0; the first time, the Session join request, flags `0x01`, destination 0 |
| Net 0x50 | Net 0x51 echoing the sequence, destination 0 |
| Session type 7 naming the joiner | type 8 |
| Session type 5 | type 6 |
| the first type 5 | the 0x81 stream open on port 0, `0f00000b 0001 0001 01 00000001 0000000000008000000000` |
| its 0x81 record on port 0 | the ack, its own record on port 1 (flags `0x1f`, sequence 1, bitmap `0x01`), then the key-zero open on 0x7c port 1 |
| the 0x7c port-0 open `0000000000000000 0100` | the same back, sequence 1 |
| a showing or an offer | its own, same selector and counter |
| selectors 5 and 7 | the same; after 7, the phase key open |
| the phase key open | phases 3, 6, 11, 14 (selector 1), each after the host's answer, then the key closed |
| RTT kind 0 | kind 1, timestamp echoed, the requester's variable id last |

A retail joiner sends its 0x12 to destination 0 (108 of 108); addressed to the host's variable id
the reader gate drops it. A retail console hosting answers each phase with selector 2, 0.02 to 0.04 s
after the joiner's. Never close the phase key on the console's own `01 0e`: the `02 0e` never comes,
the console shows 2-AW7KA-0007 on leaving and holds the restriction. `bin/pla_join.py` closes it on the
`02 0e`, keeps the seat until the player backs out or `--hold` ends (`--hold-after-trade N` leaves N
seconds after the last queued trade), and forgets answered steps after each trade. It repeats its 0x81
acknowledgement on ports 0 and 1 about once a second:

    0000002c ffff 0002 01 00000001       header: size 0x2c, lowest pending 2, bitmap 1
    00 02                                type 0 the first time, then 1; two entries
    00 0002 0001 00*16                   the host's stream
    00 0001 0001 00*16                   its own stream

`tests/test_pla_joiner.py` plays a scripted host; `tests/test_esp32.py` runs it across two simulated
boards.

## Reaching local trade on the console

    title screen, A -> Jubilife Village, the trading post -> talk to Simona (Trado in French), A
    -> "echanger des pokemon !" -> local -> the restriction warning -> an eight-digit code
    -> "Echange en reseau ! Recherche d'un partenaire en cours..."

The minutes table at `0x397e1b8` (`30 30 60 60 ... 2160 2160`) is the lost satchel's (`0x2686a0c`, on
the network clock), unrelated to trading.

## The advertisement

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
communication version 21, application version 0, a 16-byte user password, player limit on, one player,
name a single space), then the code in the clear: 16 bytes ASCII NUL-padded, then its length as a
little-endian u32 (`0000 0000` gives `3030303030303030`, eight NULs, 8).

### The link code in the advertisement

The user password is the code encrypted by Pia's setter `0x6fc454`: with encryption on (session
`+0x230`) in mode 1 (`+0x234`), it fills 16 bytes with 0xFE, copies the NUL-padded code over it, and
encrypts in place with `0x6e68d0`: AES-128-GCM under the game key (session `+0x238`, set through
`0x6fc8a4`), no additional data, tag discarded, IV `key[1] key[8] key[7] key[2]` (`0x6fc4e4..0x6fc4fc`),
here `1emf`:

    password  = KEYSTREAM XOR (the code's ASCII, NUL-padded to 16)
    KEYSTREAM = AES-128-GCM(key = p1frXqxmeCZWFv0X, iv = 1emf).encrypt(16 zero bytes)
              = e5ab19ed742b6d40885998bf968aa166

The keystream is fixed. `pokeldn.pla` has `link_code_keystream`, `user_password`, `link_code` and
`parse_advertise_data`. The setter is Pia's, so every title of the band encrypts this way
([the wireless layer](ldn.md)).

A console whose host restarted under it shows error 2318-0006 on its next search; leaving the trade
menu and searching again clears it.

## Leaving

A console quitting runs `nn::pia::session::LeaveMeshJob`: it sends the Session type-3 leave request,
waits 500 ms for the type-4 response, four sends at most, then leaves the network. Steps:
SendLeaveRequest `0x73b898` (writer `0x737ee8`, deadline at `0x73b9a8`), WaitLeaveResponse `0x73bab8`
(counter `[job+0x6c]`, gives up past 3 at `0x73bbf0`), CompleteProcess `0x73ba54`.

    03 | u32 random | location id (12) | address kind | IPv4 (4) | port big-endian (2)
    04 | u32 random | location id (12)                          the response, 17 bytes

The random word differs on every send. The type-3 handler `0x738000` answers `04`, a fresh random
word and the request's bytes 5 to 16, then removes the station; the type-4 handler `0x738280` accepts
only the leaver's own ids.

Unanswered, a console leaves after four requests (about 2 s); answered, after one.
`bin/pla_host.py` answers every type 3 (`tests/test_pla_host_loss.py`, the answer run through
`0x738280` under unicorn).

The quit, the partner-gone message and a session error enter scene mode 9 (`0x110b72c`): it places a
pending received record, starts the leave (`0x26be890`), cancels the job, and waits at least 3.0 s
(`0x110b7d8`) for the leave and the job, so the field is back about 3.7 s after the quit whether or not
the host answers. The only caller of `Session::LeaveAsync` is the game's leave request `0x2ca0a10`;
no Pia timer precedes the first type 3 ([pia.md](pia.md), Leaving a session).

A received leave changes nothing on screen. With the console on the box screen:

| host | console |
|---|---|
| network down | "code d'erreur 2318-0006" within a second |
| network up and silent (`--leave-sends 0`) | "Your trade partner chose not to continue trading" about 13 s in, then Communicating, then `DisconnectedByUser`, no error code |

`--leave-after SECONDS` sends the leave to each joined station and ends the run;
`--stay-after-leave` keeps the network up, silent.

## Unresolved

- What fills the 0.4 s between the scene's destructor and the field on screen.
- Which flows of the box code call `0x26dcc74` (`0xc17ce0`, `0xc17e8c`).

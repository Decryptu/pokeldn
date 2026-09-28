---
title: Scarlet and Violet
nav_order: 9
has_children: false
---

# Scarlet and Violet

Pokemon Scarlet (`0100a3d008c5c000`) and Violet (`01008f6008c5e000`) are native Switch titles with
Pia statically linked into `main`. A trade is complete on a retail console: `bin/sv_host.py` puts up
a network the console joins from its offline Link Trade search, and the console draws the host's
offer, offers its own, confirms and commits.
A retail Violet trades in both roles the same way: it joins a host advertising Scarlet's local
communication id, and its own search network advertises Scarlet's id too (`0x0100a3d008c5c000`,
application version 21, scene 4), not Violet's `0x01008f6008c5e000`.

Addresses are offsets into the decompressed `main` of update 4.0.0, as `tools/switch/nso_read.py`
lays it out: text `0x0..0x343fc90`, rodata from `0x3440000`, data from `0x4383000`.

## The wireless layer

| | value |
|---|---|
| Pia header version | 11, the same band as Legends Arceus; `pokeldn.ldn.pia6` speaks it |
| header size | 0x1C, GCM tag 8 bytes |
| LDN passphrase | `W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL`, data `0x44dfd0a` |
| Pia game key | `p1frXqxmeCZWFv0X`, data `0x44dfcfe`, immediately in front of the passphrase |
| LDN local communication id | the cartridge's own title id |

The passphrase and the game key are byte-identical to Sword/Shield's and Legends Arceus's, and to
the NintendoClients wiki's Scarlet/Violet rows. The header initializer at `0x697134` stores the
magic `0x32AB9864` at `+8` of its object and the byte `0x0b` at `+0xc`, states the header size 0x1c
at `+0x5f8`, and the parser at `0x696f10` copies the wire fields out one at a time in the version-11
order. Neither title id appears as a constant in the image; the NACP lists both as local
communication ids and each cartridge advertises its own.

## What a searching console advertises

The Link Trade search alternates: a few seconds hosting its own network, then a scan, on a cycle of
about five seconds, hopping between channels 1, 6 and 11. Each host phase has a new SSID.

    local_communication_id  the cartridge's title id
    ldn protocol            1            advertisement version 4
    scene_id                4            app_version 21
    security_mode           1            accept_policy ALL
    participants            1/2
    application_data        132 bytes

The application data is the 0x5C Pia system property block and 40 game bytes:

| field | value |
|---|---|
| system communication version | 0x15 |
| application communication version | 0x15 |
| user password | sixteen zero bytes with no link code |
| player limit enabled | 1, number of players 1, then 2 once a station is seated |
| player name | one byte, a space, UTF-8 |
| the 40 game bytes | zero, or `fb149700` at game `+0x21` |

The console alternates between those two shapes of game bytes, a few seconds each, and a second
console has been seen associating on the `fb149700` one. `pokeldn.sv.build_advertise_data`
reproduces both the 1-player and the 2-player beacon byte for byte.

## The protocols the game runs

A retail pair, read from the moment the second console associated, shows four protocols in a
passive capture: Net `0x2C`, RTT `0x58`, BroadcastReliable `0x80` and StreamBroadcastReliable
`0x81`. Every one of those datagrams goes to the link-local broadcast address of the session's own
`/24`, never to the peer's address, and each carries the recipient's variable id in the plaintext
footer. The station registers ten protocols; the six the capture never shows are addressed to one
station and are invisible to a capture of two Switch 2 consoles (The Session protocol is there and
is never in a capture, below).

The game's own setup, `0x17ff030`, creates its protocols in this order: Reliable `0x7C` on port 0,
BroadcastReliable `0x80` on port 0, Unreliable `0x68`, Reliable and BroadcastReliable on port 1,
then on port 2, `[0x44dfcd0]` StreamBroadcastReliable `0x81` ports (eight on the wire), Clone
Clock `0x77` and Clone Atomic `0x74`. Pia's transport adds Net `0x2C`, RTT `0x58`, Session `0x98`
and MonitoringData `0xA4`; NatTraversalResult `0xA0` is created only when the network factory
says NAT traversal is on (`0x6d3138`), which a local network does not. The versions each class
states (`scratchpad/sv_protocols.py`):

| id | protocol | version |
|---|---|---|
| `0x2C` | Net | 0 |
| `0x58` | RTT | 3 |
| `0x68` | Unreliable | 1 |
| `0x74` | Clone Atomic | 0 |
| `0x77` | Clone Clock | 0 |
| `0x7C` | Reliable | 2 |
| `0x80` | BroadcastReliable | 3 |
| `0x81` | StreamBroadcastReliable | 3 |
| `0x98` | Session | 0 |
| `0xA4` | MonitoringData | 0 |

A retail Legends Arceus lists the same ten with the same versions in its join request.

    +0.00   the joiner associates
    +0.06   the host broadcasts Net 0x11, the station list, and 0.12 s later Net 0x50
    +0.14   the host acknowledges all eleven streams and opens two of them
    +0.89   the joiner sends an RTT request, then acknowledges all eleven and opens its two
    +0.97   the host sends its first records on 0x81 port 0
    +1.26   the joiner sends its first records on 0x81 port 1

### Net 0x11, the station list

The layout is Legends Arceus's, with four station slots of 21 bytes:

    01 11 0054          version 1, type 0x11, payload size 0x54
    00000002            sequence id
    9141                host variable id, fresh every session
    eb9b2220f1480000    host constant id, the LDN MAC reordered
    0000000097392e8a    network id, the low four bytes crc32(ssid[1:16])
    01                  is network open
    0004                station slots
    00                  is migrating host
    ...                 four stations: migration state, ranking, one byte, then 16 address bytes
                        and a big-endian u16 port. Both present stations carry port 12345, ranking
                        0 for the host and 1 for the joiner; the empty slots carry ranking 0xff

`01 40 00 00` is a bare NetStartHostMigration. A retail host sends it when the session moves to the
other console at the end; a console that a host built here joins sends it about eight seconds after
the association and then repeats it.

**The four slots are the gate on the whole host direction.** The count is Pia's, not the game's, and
a host that writes the game's own participant limit of two writes a message the joining game reads
and never answers: it binds its Pia socket, receives the datagram ten times over five seconds, sends
nothing, and calls Disconnect at exactly 5.00 s, which Ryujinx reports as DisconnectedByUser. Over
49 such joins the hold was 4.98 to 5.01 s, so it is a fixed timer rather than a race. With four
slots the same game answers the opening with Net 0x12 and sends its Session join request. The
message flags carry 0x31 on a retail host's opening against this host's 0x01, and that difference
alone changes nothing.

A retail console did this against `bin/sv_host.py` over the radio: it associated, sat about five
seconds, left, and answered Net 0x11 with ICMP port 12345 unreachable.

### The eleven streams

    0x80  BroadcastReliable         ports 0, 1, 2
    0x81  StreamBroadcastReliable   ports 0 to 7

Both stations acknowledge all eleven about once a second whether or not anything came on them. The
acknowledgement is `pokeldn.ldn.reliable5`'s bulk ack with four entries, every entry's station byte
zero, entry *k* acknowledging station *k*'s stream with one past the highest sequence received, a
destination-bit count of 3 and the peer's station bit in the bitmap.

A station opens two streams with an INITIALIZED data message carrying eleven bytes, and then sends
its records on the port that is its own station index, which is the convention
`pokeldn.pla.data_exchange` reads for Legends Arceus.

| station | opens | sends records on |
|---|---|---|
| host, index 0 | 0x81 ports 1 and 5 | 0x81 port 0 |
| joiner, index 1 | 0x81 ports 0 and 4 | 0x81 port 1 |

The open payload is `0000000000f38800000000` on ports 0 and 1, and `00 <port> 00 00 0ff0 0800000000`
on ports 4 and 5: a StreamData kind 0, a receive posted with its capacity, 0xF388 for transfer id 0
and 0xFF008 for ids 4 and 5. Of 124 kind-0 messages in 47 Scarlet captures, 62 carry 0xF388 and 62
carry 0xFF008. The 0xFF008 transfer is posted by both sides and never sent in a trade. `pokeldn.sv.streams` builds all of it and `tests/test_sv.py` pins every message
to the bytes a retail station sent.

### The Pia message flags

The flags byte of the message header is not the establishing flag the Arceus host uses. Both retail
stations send:

| message | flags |
|---|---|
| RTT, stream opens, a record's first transmission | 0x00 |
| a record sent again | 0x40 |
| the bulk acknowledgements | 0xA0 |
| the host's Net 0x11 and 0x50 | 0x31 |
| NetStartHostMigration | 0x11 |

The message destination field is zero on every message either station sends. Flag 0x40 is the
`ReliableSlidingWindow` send loop `0x6f0638` passing `w4 = 1` to the window's send vfunc: `w4 = 0`
for a slot whose send count `[slot+0x14]` is zero (`0x6f0908`), 1 for a resend (`0x6f0a9c`) and an
early send (`0x6f0c38`); `0x6e7250` stores it as byte 0 of the option block it hands the packet
writer.

### RTT

Eleven bytes: a kind byte, an eight-byte clock and a two-byte target. A request is kind 0 with
target 0; the answer is kind 1 with the same clock and the target set to the requester's variable
id. A retail station answers within 20 ms.

RttProtocol (vtable `0x43e5a28`) keeps a 0x40-byte record per station at `[proto+0x60] + index*0x40`:
the sample count at `+0`, the ring head at `+4`, the capacity 9 at `+0x10` with the ring inline
behind it, and a median cached at `+0x3c` for the count stored at `+0x38`. An answer's sample is the
clock now less the echoed clock (`0x6f34b4`), and a sample of zero or less is discarded
(`0x6f34e0`), so an answer inside the same clock unit as its request counts for nothing. Requests
go at the interval `[0x46d1528]` until every station's ring is full, then at `[0x46d1520]`, 500,
written at init (`0x6f2fcc`) and again by the game (`0x1e7c2bc`). A station event 0 or 1 clears
that station's record (vfunc11 `0x6f3bd8`), so a new seat starts with no sample.

GetRtt (`0x6f4498`, and `0x6f44bc` with a count *n*) returns -1 with no sample, otherwise the
median of the last min(count, *n*) samples, with no minimum count; the minimum `0x6f44e4`, maximum
`0x6f4508` and sample count `0x6f452c` sit beside it. Two callers read them, and nothing else calls
or points at them: the SessionTransportAnalyzer's monitoring copy (`0x6f9ab0`..`0x6f9ad4`) and the
retransmit deadline of `ReliableSlidingWindow`, `0x6f0d14`, called from its send loop at `0x6f073c`:

    deadline = now + [window+0x80] + 1.4 * (max over the destinations of GetRtt(count))

With no sample for any destination `0x6f0d14` returns the window's unscheduled marker
`[window+0x5c]`. A message is sent once when queued (`0x6f1bbc`..`0x6f1bd4` set its time to now),
then parked at the marker and skipped at `0x6f0a18` on every pass until a sample exists, when it is
re-armed to the deadline (`0x6f09f4`..`0x6f0a08`). A reliable window with no RTT sample never
retransmits.

`[window+0x80]` is 33 ms. The `ReliableSlidingWindow` constructor `0x6eeea8` (callers `0x6e69f8`,
`0x1800038`) stores `ticks_per_second * 33 / 1000` there (`0x6eef34`..`0x6eef74`: `x8 + (x8 << 5)`,
then the division by 1000); run under unicorn it leaves 633,600 ticks, 33.0 ms at 19.2 MHz. The same
constructor sets the unscheduled marker `[+0x5c]` to 0, the base sequence `[+0x30]` to 1, the own
index `[+0x10]` to 0xfd, compression `[+0xa4]` to 1 and the early-send limits `[+0x88]` and
`[+0x89]` to 0. The only later writer is `0x6f1fc8` in vfunc17 `0x6f1f98`, reached from
`ReliableProtocol::vfunc17` (`0x6eebbc`) and `BroadcastReliableProtocol::vfunc17` (`0x6e6818`); no
caller of either was found. The send loop runs once per 16.7 ms frame, so a resend leaves on the
first frame at or after `33 + int(1.4 * RTT)` ms: 83 ms at an RTT of 34 ms, 550 ms at 358 ms, the
intervals measured below.

### The records

A record is one reliable message with the ZLIB flag, and its payload is a zlib stream with a 4 KB
window, so it begins `484b`. Every record measured decompresses to 1395 bytes, `[window+0x70]`: one
chunk of a 0x81 transfer under Pia's eleven-byte StreamData header
([Protocol 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)):

    +0x00  1   StreamData kind: 1 the first chunk of the block, 2 a later chunk
    +0x01  1   transfer id, 0
    +0x02  1   percent of the block delivered after this chunk
    +0x03  4   zero, the capacity field of a kind 0
    +0x07  4   big-endian u32 0x00000568, the 1384 bytes that follow

The block a station sends on its own port is 0xF388 (62,344) bytes: 45 chunks of 1384 bytes and
one of 64, ids 1 to 46. The percent byte of chunk *k* is `floor(k * 1384 * 100 / 62344)`: 2, 4, 6,
8, 0x0b, ..., 0x37 at chunk 25, 0x52 at 37, 0x64 at 46.

The first chunk carries the player the game shows as the partner:

    +0x0b  5   unread
    +0x13  26  the player name, UTF-16 little-endian, NUL-padded
    +0x2d  22  the account identifier, ASCII, `u-` and twenty characters
    +0x53  1   5

Chunks 2 to 24 are high-entropy and carry no readable string; chunks 25 to 46 are zero in the sets
read. A station sends its whole set at once, in first-send order 1 to 46: the first packet carries
ids 1, 25, 26 to 36 and 46, the second 2, 37 and 38 to 45, then 3 to 24 one per packet (41 of 48
retail sets, as host and as joiner). The zero chunks compress to one size, so 26 to 36 and 38 to 45
travel behind a presence byte of 0x00, every header field inherited
([Message framing](pia.md#message-framing)). Of 52 retail sets, 46 went out within 0.19 s, and 22 of
the 25 that arrived whole within 0.164 to 0.190 s. `pokeldn.sv.streams.decompress` reads them and
`scratchpad/pia6_air_decode.py` writes each one out.

### The retail acknowledgement, and a flood of retransmits

A retail station acknowledges a peer's record stream with the end of the contiguous run and a mask
of what arrived early: ack id one past the run, field 0x50 equal to it, and mask bit *b* of byte *k*
the id `ack_id + 1 + 8k + b`. A Scarlet host holding a joiner's ids 1 to 4 and 7 to 38 sent
`0005 0005 feffffff01`. Ids below the peer's own `lowest_pending` count as held: once the joiner's
bulk ack declared 47, the same host acked 47 with an empty mask. `pokeldn.sv.streams.ack_position`
builds this, and `tests/test_sv.py` pins it to two of the host's acks. `bin/sv_join.py` sends it;
`--ack-highest` sends one past the highest id seen instead.

A host resends every record of its set not yet acknowledged, on the retransmit deadline of RTT
above, with message flag 0x40. A round carries the outstanding records in one packet, the lowest
first, with the host's `lowest_pending` equal to that id, and shrinks as acknowledgements arrive: 20,
19, 18 and so on after a burst whose zero chunks went unacknowledged. A message walk that stops at a
presence byte of 0x00 reads only the first record of each round, acknowledges one record per round,
and takes 19 rounds to finish the set. Against such a walk, an acknowledgement declaring one past
the highest id read (`--ack-highest`, 38 after the first two packets) moves the host's
`lowest_pending` from 1 to 38 at once.

Unacknowledged, a host retransmits every record of its set, each on its own deadline, at HT MCS3:
435 to 494 records a second at the peak of the long floods, about 3% of the air and the whole
150 KB/s of a board's line to its host.

The interval between rounds is `[window+0x80] + 1.4 x RTT`, rounded up to the send loop's frame
(RTT above). Against the host's RTT estimate (the joiner's answer delay plus the joiner's own RTT to
the host), per seat:

| answer delay | estimated RTT | round interval, seat medians |
|---|---|---|
| 0.000 s | 0.013 to 0.017 s | 0.065 to 0.069 s |
| 0.000 s | 0.033 to 0.038 s | 0.078 to 0.116 s |
| 0.000 s | 0.053 to 0.059 s | 0.115 to 0.221 s |
| 0.318 to 0.328 s | 0.354 to 0.363 s | 0.532 to 0.555 s |

The retransmit interval of one record converges on the round interval as the host's RTT ring fills:
one seat resent at 0.19 to 0.20 s with 4 to 5 RTT answers held, 0.10 s with 8 to 18 and 0.082 s
with 20, and its later rounds came 0.089 s apart. With answers 0.3 s late the host's set stood
acknowledged 9.06 to 12.10 s after it was sent, and those seats were announced 10.23 to 13.66 s in.
Nothing on the console holds a queued record back: the window's constructor `0x6eeea8`, send buffer
`0x6e6e94`, enqueue `0x6f1994` and send loop `0x6f0638`, run under unicorn with only the clock, the
deadline and the window's send vfuncs intercepted, send 46 records of the measured sizes in one pass
with `w4 = 0` and nothing more before the deadline.

Every seat that flooded this way was one whose board could not send while its line was full
([the serial ceiling](hardware_esp32.md#the-serial-ceiling)): the joiner's acks waited up to
seconds, the host kept `lowest_pending` at 1 for 3.2 to 12.4 s, and the flood kept the line full. With
that fixed, a seat holding 26 moved to 27 at 1.9 s and repeated records for one second. The form of
the ack alone decided nothing: a seat with the retail form still flooded 6 s.

`bin/sv_join.py` acks a new record at once and a repeat at most once per 50 ms per stream
(`--repeat-ack-gap`): in a one-second burst of 91 repeats read it sent 38 packets, against about 150
with an ack per repeat. The host's `lowest_pending` moved at the same point either way. It sends
one ack per stream per packet, after every message in the packet is read: a round of 14 records
draws one ack whose mask covers all 14.

With the board fixed, the host's own processing sets the pace. Its radio acknowledged every one of
the joiner's frames within 7 ms of it entering the board's driver, and the joiner acked each host
record within 1 ms of reading it, yet the host's `lowest_pending` left 1 between 0.73 and 0.81 s
after its set on every seat with prompt answers, calm or flooding, and its ack masks for the
joiner's records advance in steps about 0.19 s apart. The host sends its set about 0.1 s after the
joiner's stream open and record set, so `--open-delay` and `--record-delay` place it.

Whether the set floods depends on the RTT answers the host holds when it sends it:

| RTT answers before the set | answer delay | seats | records resent before `lowest_pending` left 1 | `lowest_pending` left 1 after |
|---|---|---|---|---|
| 0 or 1 | 0 | 3 | none in two, 138 in one | 0.78 to 0.81 s |
| 3 to 6 | 0 | 4 | 122 to 137, each id every 0.18 to 0.20 s | 0.73 to 0.80 s |
| 0 | 0.3 s | 4 | none | 0.91 to 1.01 s |
| 1 to 7 | 0.3 s | 9 | none | 0.50 to 0.58 s |

In every one of these seats the rounds that followed resent 158 to 272 records, the ones a walk
stopping at presence 0x00 had left unacknowledged.

The retransmit interval follows the measured RTT through the deadline in RTT above: a few prompt
answers bring it under the host's own 0.8 s ack latency. `--rtt-delay 0.3` answers each RTT request 0.3 s late; the host announces the
station and the trade completes: twelve seats of twelve were announced, two of them the next seat
after the console's post-trade host migration (`--leave-on-migration 3`, the player searching
again), each traded. `bin/sv_join.py --announce-timeout SECONDS` leaves a seat not announced within
that time and scans again.

With no RTT sample the 0x81 streams never retransmit
([Protocol 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)). In four seats
whose joiner answered no RTT request, no id was sent twice, the joiner's own set was acknowledged to
47, and the host answered 43 to 47 of the joiner's RTT requests. Each host sent its whole set in the
first burst; the joiner, stopping its walk at presence 0x00, read none of 26 to 36 and 38 to 46, and
a record lost on the air stayed lost:

| seat | host ids lost on the air | host `lowest_pending` | seat ended |
|---|---|---|---|
| 0 | 11 | 11 from 1.51 s | 22.72 s |
| 1 | none | 26 from 2.86 s | 22.68 s |
| 2 | 19 | 19 from 2.86 s | 20.49 s |
| 3 | 18, 23 | 18 from 1.46 s | 20.02 s |

The lowest record left unacknowledged held the host's `lowest_pending` at its id for the rest of the
seat and was never resent. In seat 1 that record was 26, which had arrived in the first packet
behind a presence byte of 0x00.

### What a passive capture misses

Both consoles pack several MSDUs into one frame. Read as a single MSDU, the payload begins six
bytes of destination and six of source before the SNAP header, so the IP header lands at the wrong
offset and the addresses read as fragments of a MAC. Unpacking the A-MSDU subframes multiplied the
readable traffic of one capture from 313 Pia packets to 3667. Any decoder pointed at these two
consoles has to do it; `scratchpad/pia6_air_decode.py` does.

## The link code

A Link Code rides the advertisement twice; the scene id stays 4. The user password is the code,
NUL-padded to sixteen bytes, XORed with `e5ab19ed742b6d40885998bf968aa166`, the mask Legends Arceus
uses under the same game key ([docs/pla.md](pla.md)). The game bytes carry the code in clear at
+0x00 and its length as a u32 at +0x24. `pokeldn.sv.build_advertise_data(code=...)` reproduces a
retail console searching with 12345678 byte for byte.

| run | result |
|---|---|
| the console searching with 12345678, hosting; `bin/sv_join.py` advertising no code joins | traded |
| `bin/sv_host.py --code 12345678`, the console searching with 12345678 | joined, traded |
| `bin/sv_host.py` with no code, the console searching with 12345678 | never joined |

A searching console joins only a host advertising its code; a console hosting under a code takes a
joiner that carries none. `bin/sv_join.py --code` joins only a console searching with that code.

## Where the code is

Offsets into the decompressed `main` of 4.0.0. The RTTI names come out of the binary's own
type_info records with `tools/switch/rtti_names.py`, which finds 208 `nn::pia` classes.

| address | what |
|---|---|
| `0x697134` | the Pia header initializer: the magic, the version byte 0x0b, header size 0x1c |
| `0x696f10` | the header parser, field by field, which fixes each field's width |
| `0x697034` | the payload bound: a length above 0x5a3 returns null |
| `0x3c0c8c0`, `0x44dfcfe` | the passphrase and the game key, rodata and data |
| `0x6b43a8` | `LdnConnectionStatus::vfunc20`, which reads `nn::ldn::GetNetworkInfo` and turns the participant list into station addresses |
| `0x6b45e0`..`0x6b4754` | its loop over the eight participant slots: a slot is 0x40 bytes with its address at `+0x108` and a present byte at `+0x113`, matched against the station array at object `+0x30` with its count at `+0x38` |
| `0x6b3090` | `LdnProtocol::vfunc104`, another `GetNetworkInfo` reader |
| `0x046ca878` | the GOT slot for `nn::ldn::GetNetworkInfo`; six call sites reach it |
| `0x17ff030` | the game's protocol registration: it creates each protocol in turn and stores the handle it gets back |
| `0x475ea68`, `0x475ea6c`, `0x475ea70` | the handles of Reliable 0x7C on ports 0, 1 and 2 |
| `0x475ea74`, `0x475ea78`, `0x475ea7c` | the handles of BroadcastReliable 0x80 on ports 0, 1 and 2 |
| `0xe45e9c` | the one send on 0x80 port 2: it loads the port-2 handle, resolves the protocol through `0xe21488`, and hands the composed buffer to `0x107e060` |
| `0xe2246c` | the 0x5a0-byte application send under it, into `BroadcastReliableProtocol::vfunc12` at `0x6e6344` |
| `0xe44cf0` | the drain that walks eight queues on its object and calls one composer per queue |
| `0xe457cc`, `0xe45740`, `0xe460bc`, `0xe454ec`, `0xe46148`, `0xe461d4`, `0xe46260` | the composers, which write the message type byte 6, 7, 8, 9, 0x0A, 0x0B and 0x0C respectively and then call `0xe45e9c` |
| `0xe45e1c`, `0xe46034` | the type-7 and type-8 field serializers, each writing the `0xb9` field marker the announcement's body carries |
| `0x46d6ca0`, `0x46d6ca8` | the singleton the drain hangs off, set up at `0xe44ac0` |
| `0x1e685a4` | the receiver of the trade channel's port-0 messages: the kind as a tagged integer, the step, then kinds 0 to 5 through the table at `0x3c5bb82`; kind 1 the identity (`0x1e6864c`, parsed into the object at `+0xae0`), kind 2 the offer (`0x1e686cc`: the 344-byte blob parsed by `0x1db949c`, wrapped by `0xeee8fc` and `0xe13ad8`, stored at `+0xb8` by `0x1e684fc`, state `+0xc4` set to 3), kind 3 the confirmation (`0x1e68768`, the step against `+0xe2`), kind 4 the cancel (`0x1e68678`), kind 5 the commit (`0x1e68780`, state `+0xc0` masked to 4) |

## The Session protocol is there and is never in a capture

The binary carries `nn::pia::session::SessionProtocol`, whose id vfunc at `0x6d9f3c` returns
**0x98**, next to `JoinMeshJob`, `CreateMeshJob`, `LeaveMeshJob`, `JoinSessionJob` and
`SessionPacketReader`/`Writer`. The mesh join a joiner runs exists in Scarlet exactly as it does
in Legends Arceus, and the reason no capture shows it is that it is addressed to one station: a
Session message carries the peer's variable id in the packet header and no footer, so it goes out
unicast, and the two consoles' unicast is 802.11ax. Everything a passive capture does show, Net,
RTT and the eleven streams, is mesh-addressed and therefore broadcast.

A joiner's variable id is its own: it states it in the join request's source location id, and the
host names it 0.14 s after the association because the unicast request has arrived by then.

### The Session join request

The joiner's writer is `0x6d5464` to `0x6d58b0` (a SessionProtocol method), the host's parser
`0x6d5aa4`. The layout is the one a retail Legends Arceus sends (`docs/pla.md`, The Session join
request; `tests/test_pla_session_v11.py` holds the 115 bytes) and
`pokeldn.ldn.pia6.build_session_join` reproduces those bytes from their fields:

    +0    1    type 0
    +1    1    protocol count, ten
    +2    2n   (id, version) pairs, walked from the protocol manager's list
    +22   4    random, xorshift128 seeded from the system tick (`0x6c70a8`, `0x6c7184`)
    +26   12   source location id: u64 constant id, two zero bytes, u16 variable id, big-endian
    +38   1    NAT mapping, two bits
    +39   1    private-IPv6 flag
    +40   32   identification token
    +72   1    address kind, 0 for IPv4 (1 puts an 18-byte IPv6 address in place of the six bytes)
    +73   4    source IPv4 address
    +77   2    source port, big-endian
    +79   12   destination location id, the host's
    +91   1    player count
    +92   1    a flag the job sets to 1
    +93   ..   player records: a 16-byte id (`1` then `0` as two big-endian u64), a big-endian u32
               name length, a kind byte (1), the name

A retail joiner's one player is named a single space, which is also the name in its advertisement.
The packet header carries destination variable id 0 and the joiner's own id as source, and the
message flags are `0x01`, skip the source check, on every repeat.

What the host checks, in order, before it creates a station:

1. The protocol count equals its own. A different count draws nothing.
2. Every listed id's version equals the host's version of it (`0x6ed1b8`). A mismatch draws a
   join response with status 3 carrying the offending id and the host's version.
3. The destination location id equals the host's own constant and variable id. A mismatch is
   dropped silently.
4. The source constant id is not the host's, and the source address is not the host's own.
5. A station already known by that constant id draws a status-1 response again; a closed session
   draws status 5; a host-side listener can refuse with status 4.

The join response (type 2, 43 bytes, `0x6d6390`) is the Arceus layout: type, protocol id, version,
status, a big-endian u32 the accept path fills, a four-byte random, the host location id, the
joiner's, route bytes A and B, the station index, the join order and the sequence id the station
update must reach. The joiner answers the type-5 station update with a type 6 of 13 bytes
(`0x6d80a4`): the type, its own constant id, two zero bytes and the applied sequence.
`pokeldn.ldn.pia_connect` parses the response and the update and builds the type 6.

## The seat, and the identity flood above it

Joining a searching console's network with the Session join request in the layout above seats the
station: a retail Scarlet host accepts it in 16 ms, sends a 41-byte join response (status 1, no
route bytes) and a route-less station update, and streams its own player identity on 0x81 port 0.
The trade does not complete: the host floods that identity about 350 times a second, each record up
to seventy retransmits, and never acknowledges the joiner's records or acks, where a retail host
sends its identity once (a passive pair, 15 records, one send each).

Ruled out as the cause: opening timing (the joiner's eleven-stream ack burst reaches the host before
its first record and it still floods), the joiner's own identity record on port 1 (sent fifty times,
never acknowledged), and the host-migration handshake. The host sends a Session type 7 on some seats,
about 22 ms after the accept, `LeaveMeshWithHostMigrationJob` handing the host role to the joiner and
repeating once a second until a type 8 answers it; the migration is intermittent and answering it is
untested. The joiner's bulk ack is byte-identical in structure to a retail joiner's and reaches
ack_id 47, one past the host's highest, and the host ignores it.

Airtime is not the cause. The same flood runs against an emulated Scarlet 4.0.0 over a LAN, where
nothing is lost and the guest's own send log shows every datagram: 44 of its 46 records on 0x81
port 0, each retransmitted 676 times in 59 seconds, every record declaring its window still at
lowest_pending 1. Sequence ids 5 and 6 are never sent at all, by either station of a pair that
traded either, so the gap is how the game numbers its records and not a fault.

### The flag that makes the host count an acknowledgement

A plain bulk acknowledgement under message flags 0xA0 never reached the emulated host's window.
Its receive function resolves the sending station, checks the length and compares a byte of the
message against the station's own before applying anything, but a message whose flags carry bit 5,
the ZLIB flag (`[msg+0x29]`, `0x6efc80`), branches earlier into `0x6e9984`, which inflates the payload
(`0x69804c`, zlib inflate at `0x2801d0`). Any failure there returns 0x2C03 (`0x6efd5c`), and a plain
payload fails the inflate. Measured on the emulated console: 600 of 600 plain acknowledgements under
0xA0 dropped at that instruction; the station resolve never ran.

The retail 0xA0 acknowledgements do carry zlib message bodies. Across three retail Scarlet/Violet
joiner captures, all 1,774 acknowledgements on 0x80 and 0x81 inflated to 99 bytes. One 38-byte
body starts `484b62606008` and reproduces exactly with the 4 KB window, level-5 sync-flush framing
used for records. `bin/sv_join.py` compresses the body when it sets bit 5.

Under message flags 0x00 the same acknowledgement, the same 99 bytes with the same four entries
and destination bitmap, takes the other path and the exchange completes. The host answered a
sweep's fifth shape by sending each of its 44 records exactly once and stopping: 115 to 257
records a second under 0xA0 in the four shapes before it, 6.3 a second during it, and none at all
in the 26 seconds after, while its periodic bulk acks continued. That is what a retail host does
with a retail joiner.

Both retail stations flag their own bulk acknowledgements 0xA0 and address them to the LDN
broadcast of their own /24. `bin/sv_join.py --ack-flags`, `--ack-entries`, `--ack-dest-bits` and `--ack-sweep` are the handles.

### The first record on a stream carries INITIALIZED

A station's own records go on 0x81 port 1 for a joiner and port 0 for a host, each station opening
the two ports it receives on: the joiner opens 0 and 4, the host opens 1 and 5. The first record a
station sends on its stream carries INITIALIZED with the usual START, END and ZLIB, flags 0x1F, and
every record after it 0x17. A first record sent as 0x17 is never acknowledged: the host's bulk ack
for that station holds at 1 for as long as the record is repeated, 198 sends in one seat. Sent as
0x1F the same record is acknowledged within 90 ms.

Replayed from a pair's own log, the identity a joiner sends is byte-identical to what that pair's
joiner sent, in the reliable header, the message flags and the record body alike, for all 44
records; the packet header differs only in the source variable id and the nonce. Both an emulated
and a retail host acknowledge the set to id 47 with the mask `feffffffff01` and their entry's
`field_0x50` following, so nothing above the seat separates this project's station from a station
that went on to trade.

With both fixes an emulated host completes the whole exchange in both directions: it sends its 44
records once each, acknowledges the joiner's, and issues a type-5 station update listing both
stations with their player blocks. It then keeps searching. What a pair does after the exchange is
what the trade needs, and it is unicast, so only two consoles or two emulator instances can show it.

## Hosting for a console

A host that answers the layers below the game brings a Scarlet to the same place a pair's joiner
reaches: seated in the mesh, its channel table sent, its two streams open and its whole 44-record
identity delivered once each. What it takes, beyond the four station slots in Net 0x11:

| the host sends | what it must be |
|---|---|
| the Session join response | the 41-byte form: no route bytes, station index 1, join order 1, sequence id 0, and four random bytes at +8. Arceus's 43-byte form, with the route bytes, is retransmitted against rather than accepted |
| the Session type-1 join ack | nothing. A Scarlet host never sends one, and a console sent one leaves within two seconds |
| the Session type-5 station list | about a second and a half after the response, never in the same breath. Sequence id 1 where the response sent 0 |
| each station in that list | 79 bytes: the location id, the address and port, the station index, a big-endian u16 join order, a NAT byte, an IPv6 flag, the 32-byte token, the counts and the player records. No route bytes, which is what makes Arceus's station 81 |
| the player name in it | one space. A console advertises a single 0x20 and a longer name changes the message's length |
| every Session reply's message flags | 0x00 |
| the acknowledgement on Reliable 0x7C | the one-entry form with no destination bitmap, not the four-entry bulk form of 0x80 and 0x81. Unacknowledged, the console retransmits its channel table for the whole session, a thousand times in ninety seconds |
| every data message on Reliable 0x7C | a nine-byte header with destination_bits 0 and no bitmap. A station acknowledges the bitmap form, so the sliding window takes it |
| Net 0x11 | once. A real host never repeats it; a request every 500 ms is a fresh connection request at a station already seated |
| Net 0x50, the update property | 0.2 s after the 0x11, retransmitted every 500 ms until the station's 0x51. It carries the forty game advertise bytes at +0x82. A host that never sends one is never sent a 0x51 |
| the Session station list, again | twice in all: one in the same breath as the join response under sequence id 0, the second about two seconds later under the next id |
| RTT | a request every 410 ms of the host's own, not only an answer. The message is eleven bytes in this band: a kind byte, a big-endian u64 timestamp and a big-endian u16 target. A response echoes the timestamp and names the REQUESTER where the request carried zero |
| the whole opening | inside the first 0.3 s. A real host sends the join response, both station lists, the channel table, both stream opens, the clock answer, Net 0x50 and all 44 records before a third of a second has passed |

The forty game advertise bytes are not a constant. Two sessions of one emulated host carried
`648cf4` and `8170f0` at +0x21 of that block, the rest zero, so the value is per session and a
replayed one is stale.

With all of it, the NetworkInfo a host here advertises is byte for byte the one a live emulated
Scarlet host advertises apart from the session id, given `--channel 6`, `--player-name RyuPlayer`
and `--host-player-id 00000000000000010000000000000000`, and its Session station list matches apart
from the variable ids.

With those the console holds one join for as long as the host stays up, against the sixteen to
fifty-seven joins a session that fails somewhere above the seat produces, and it answers RTT, the
clone clock and every stream.

### The sender's own lowest pending is what closes the gap at 5 and 6

Both stations of a pair skip sequence ids 5 and 6 on their record stream, and each one's peer still
acknowledges the set to 47 with an empty mask. What tells the peer those two will never arrive is
not on the records: every one of them declares `lowest_pending` 1, destination bits 3, bitmap `[2]`
and stream id 0. It is on the sender's next **bulk acknowledgement on the same stream**, whose own
`lowest_pending` field steps from 1 to **47** once the set is out, one past the highest id sent. A
station that reads that knows nothing below 47 is outstanding from its peer and releases the gap.

A host that leaves the field at 1 is answered with `ack_id` 5 and the mask `feffffffff01`, which is
every record the station holds, for the rest of the session. Renumbering the set 1 to 44 also gets
it acknowledged, at the cost of every record after the fourth carrying an id its sender never used.
`bin/sv_host.py --record-set` sends the ids as they are and sets the field, and the station then
acknowledges the whole gapped set to 47 with an empty mask, which is what a pair's joiner answers.

Either way the station **opens Reliable 0x7C port 2** with `03b90200bc09000000000000000000`, the
fifteen bytes a pair's joiner opens it with. That is the game's own channel.

A record set is also not sent in ascending order. A pair's host sends 1, 2, 3, 46, 4, 7, 8, 19, 9,
15, 10, 16 and so on, with the last id fourth; the order is in the `order` file
`scratchpad/sv_extract_records.py` writes beside the records.

## The game's own protocol, from a pair

Two emulated Scarlet 4.0.0 instances completed a trade, and each instance's log holds every
datagram it sent, unicast included. The two logs are keyed on the session id from the host's
NetworkInfo at +0x10; each instance's clock starts at its own launch, so they are aligned on a
datagram both recorded (`scratchpad/sv_pair_timeline.py`).

The trade runs on Reliable 0x7C, not on the broadcast streams. Those carry the identity exchange
and nothing else.

### Port 2: the announcement, the join and the answer

Port 2 of Reliable 0x7C (one station) and of BroadcastReliable 0x80 (every station) carries the
game's own session messages. One dispatcher reads both, `0x1954aec`, called from the receiver
`0x1954978` that polls the two port-2 handles (`0x475ea70`, `0x475ea7c`): the first byte is the
message type, 1 to 0xD, through the table at `0x3c68988`. Three of them open a trade:

| time | station | wire | type | bytes |
|---|---|---|---|---|
| 0.00 | host | 0x80 port 2, zlib | 7 | 167 inflated: `07b901b905b906010200bc09`, nine zero bytes, `bc8080`, 128 zero bytes, `000000b90183`, the host's station id, `00` |
| 0.09 | joiner | 0x7C port 2 | 3 | `03b90200bc09` and nine zero bytes |
| 0.15 | host | 0x80 port 2 | 9 | `09b9030000b90183` and the joiner's station id |

The encoding is the tagged one of the channel table (`pokeldn.pla.channel_table`) with one more
tag, `0xbc`, a byte string: the tag, the length as an integer, the bytes. The type 7 is a tuple of
one tuple of five (writer `0xe464fc`):

    b9 06 ...   the type-1 body as a tuple of six: kind, capacity, a zero byte, the name as a
                nine-byte string, the data as a 128-byte string, the data length
    key         body +0x8e, the relay's counter +0x1c4 before it steps
    index       body +0x8f, the relay's counter +0x1c0 masked to seven bits, before it steps
    b9 01 ...   a tuple of one u64, the station id of the type 1's sender
    0           body +0x98

The type 9 is a tuple of three: the slot key the join named, a result byte, and a tuple of one u64.

A type 7 is a relayed type 1. The type-1 handler `0x18ceb70` copies the 0x8e-byte body, stamps the
key and the index and steps both counters, appends the sender's station id and queues the element
for the type-7 composer (queue `+0x200`, stride 0xa8), with no condition anywhere in it. A station
sends a port-2 message to one station through `0x18d5a58`; when the target is its own station id it
dispatches the message to itself through `0x1954aec` instead of the wire, which is how a host
announcing alone relays its own type 1.

The type-1 body (`0x18ab760`):

    +0x00  kind
    +0x01  the slot's capacity: 2 for kinds 1 to 3, 4 for kinds 4 to 8 and 12, 0 for kinds 9 to 11
    +0x02  zero
    +0x03  a name of up to eight characters, NUL-terminated in nine bytes
    +0x0c  up to 128 bytes of data
    +0x8c  the data length

A trade's type 1 is kind 1, capacity 2, an empty name and no data. A slot keeps the body at slot
`+0xd0` (constructor `0x18b73a0`), so its key `0x12fcabc` (slot `+0x15e`) is body `+0x8e`. Every
relayed type 1, the console's own or a peer's, steps the key; `0x12fbef0` zeroes both counters and
no other writer of them is known. A join naming key 0, as `03b90200bc09` does, matches only the
first announcement since the relay's counters were last zeroed.

The type-3 handler `0x1981e94` compares the join's first field with the slot key (`0x1981ed4`) and
queues the type 9 (`+0x270`) when the join is accepted. Otherwise it queues a type 0x0D, `0d b9 01`
and a code, on `+0x350`:

| code | refused because |
|---|---|
| 1 | no slot has the join's key (`0x1981ffc`), or `0x279c8fc` refuses |
| 2 | the slot is full: `0x18f80c8` against the capacity `0x1e64914` reads, or `0x279c9a0` returns 0xfd |
| 3 | the FNV-1a 64 hash of the join's name differs from the slot's (`0x1e648a0`) |
| 4 | the slot is closed (`0x1e64924`, slot `+0x160`, cleared when the slot is created) |

`0db90101` is code 1, the answer to a join that names no slot the console holds. The port-2 poller
`0x1954978` reads the handle `[0x475ea70]` on 0x7C (`0x19549e4`) and `[0x475ea7c]` on 0x80
(`0x1954a54`) and hands both to the dispatcher `0x1954aec`, which switches on the first byte through
the table at `0x3c68988`. Type 0x0D goes to `0x1954f3c`, which requires `0xb9`, decodes a
one-element tuple with `0x279c0e8` and calls the receiver `0x279c1ac` (`0x1954f78`):

    0x279c1b8  ldr  x8, [x0, #0xb8]     the pending request
    0x279c1bc  cbz  x8, ret             none: nothing happens
    0x279c1d0  strb w9, [x8, #0x43]     result = the code
    0x279c1d8  strb #1, [x8, #0x42]     done
    0x279c1dc  bl   0xc8e6c4            wakes the request's waiter at +0x48

No sender reaches it, and it reads neither the request type `+0x40` nor the done byte `+0x42`
before writing. A 0x0D from a joiner takes the path its type 3 takes and completes whatever request
the console holds, with the code it carries. The type-9 receiver `0x18b65c8` selects
an object by the slot byte, applies the message, and compares the u64 with the station's own id
at `[[0x46d0a08]] + 0xb8`; any other id is dropped.

A station id is the Pia constant id read as a big-endian u64. The 127.0.0.2 instance of the pair
carries `7f00020000020000`, which is `ldn_constant_id` of the MAC `02:00:7f:00:00:02`, and both
of its messages above carry that value because both stations of that pair were that instance's
clones. Against a retail console the type 9 must carry the console's own constant id, the one in
the source location id of its Session join request. `pokeldn.sv.port2` builds all three from the
ids, `bin/sv_host.py --announce` sends the type 7 after the seat and answers the console's type 3
with a type 9 carrying its id; `tests/test_sv.py` pins the three messages to the pair's bytes.

### The trade job that sends the announcement

The Link Trade flow creates the job at `0x1e2ea54`: the config named `BoxTrade` (`0x3aefac8`) goes
to the job factory `0x1e2f3d4` with mode 4 and need 2. Two script bindings reach `0x1e2ea54`:
`0x1e2e9bc` (GOT `0x46d6608`, stored by `0x1b9c8c4` into the static `0x4717068`), which tail-calls
it, and `0x1e2ec84` (GOT `0x46d6610`, `bl` at `0x1e2ee40`). The job (constructor `0x1e3bd10`, vtable
`0x44568a8`, Update `0x1e51a04`) keeps its result at `+0x40`, its state at `+0xb8`, the session
handle at `+0xc0`, the mode and the need as u16 at `+0xc8` and `+0xca`, the slot object at
`+0xd0` and the request handle at `+0xf8`.

| state | address | what it does |
|---|---|---|
| 1 | `0x1e51a84` | ends with result 3 if the Pia station count `[[0x46d0a08]]+0xe0` is below need, and with result 1 if `0x18ab520` rejects the mode (0, 5, above 8). Otherwise waits, with no timeout, until the slot object counts `need` finished identity blocks (`0x1e52004`, over `[[job+0xd0]+0x10] - 0x28`), then goes to 2 on the master (`0x1639910`: own id `+0xb8` equal to the master id `+0xc0`) and to 4 on a client |
| 2, master | `0x1e51b2c` | the kind `0x18ab550(mode)` (modes 1 to 8 give 2, 3, 4, 1, 0, 5, 5, 8), then the request `0x18ab658`; a null handle ends the job with result 8 |
| 3, master | `0x1e51ca8` | waits on the request with no timeout; result 0 goes to state 6, anything else ends the job through `0x1e5086c` |
| 4, 5, client | `0x1e51b8c`, `0x1e51c74` | the same wait bounded by 15 s |

| result | meaning |
|---|---|
| 1 | success, or the mode rejected |
| 2 | the session in state 3 |
| 3 | fewer stations than need |
| 4 | a client's 15 s timeout |
| 8 | no session, or the request refused |

The request `0x18ab658` builds the type-1 body and sends it through `0x18ab83c`, which returns a
null handle while the relay's pending request `[relay+0xb8]` exists with its done byte `+0x42`
still 0 (`0x18ab860`, `0x18ab8e8`), and also when the send fails. Otherwise it clears `+0xb8`
(`0x18ab894`), stores a new request object there (`0x18ab8a8`; `0x18abec0`: `+0x40` the request
type, 0 for the announcement, `+0x42` done, `+0x43` result) and sends the type 1 to the master id
(`0x18d58b8`), which on the master is itself; a failed send clears `+0xb8` again (`0x18ab900`).

`0x18ab658` has four callers: `0x1e51b68`, the BoxTrade job's state 2; `0x18ab34c`, the same state-2
sequence in a sibling job class (vtable `0x4456490`); `0xa188f0` (vtable `0x4452e68`); and
`0x1d99568` (vtable `0x44536d8`). A type-0 request can come from any of those features. `+0xb8` is
written only by the four request creators; `0x18ab83c` and `0x2799b10` refuse while a request is
pending and not done:

| creator | request type | store | sole caller |
|---|---|---|---|
| `0x18ab83c` | 0, the announcement | `0x18ab8a8` | `0x18ab6bc`, in `0x18ab658` |
| `0x2799b10` | 2, a client's join | `0x2799bd8` (guard `0x2799b2c`..`0x2799b40`) | `0x1e635fc` |
| `0x2799c44` | | `0x2799cfc` | `0x1e639ec` |
| `0x2799d6c` | | `0x2799e30` | `0x1e63c88` |

The last three callers each sit in a function whose sole caller is in `0x1d98xxx` (`0x1d986d8`,
`0x1d98990`, `0x1d98c20`).

The relay queues the type 7 on `+0x200`. The drain `0xe44cf0` walks its eight queues in order,
`+0x1c8`, `+0x200`, `+0x238`, `+0x270`, `+0x2a8`, `+0x2e0`, `+0x318`, `+0x350`; a composer that
returns false leaves its element queued and ends the whole drain for that frame, so a stuck type 7
also holds the type 9 and the type 0x0D behind it. The type-7 composer `0xe45740` dispatches locally
alone when the station count is 1. Otherwise it asks `BroadcastReliableProtocol::vfunc20`
(`0x6e6638`) whether 0x80 port 2 can send, sends with `0x107e060`, and dispatches the same type 7
locally only when both succeed. vfunc20 refuses with 0x2c27 when no entry of the window's
destination list `[window+0x40]` is set (`0x6efb98`), with 0x4c0d when the window has no room for
the fragments (`0x6f1ef8`), and with 0x10408 when there is no session or window. Pia fills the
destination list itself on the station-join event
([Who a window sends to](pia.md#who-a-window-sends-to-pia-6)), so on the master a joiner is a
destination from the moment its join event is handled.

The type-7 receiver `0x18b566c` creates and applies the slot, and when the pending request is type
0 and the type 7's station id (body `+0x90`) is the console's own, it completes the request, done
with result 0. A master whose job reaches state 2 therefore stays in state 3 until its own type 7
has left on the wire. Nothing between the relay and the wire reads RTT, a timer or a sample count.

The identity on 0x81 is one block per station, one port per station index (handles
`0x475ea48 + 4*index`), moved by the stream send API `0xe22188` and receive API `0xe22458`. Three
objects of one layout call them, each with its own block size:

| object: Update, vtable | send | receive | block |
|---|---|---|---|
| `0xe21104`, slot 13 of `0x4455ec0` | `0xe21a44`, `bl` at `0xe21dc4`, `w2 = 0xf388` at `0xe21db8` | `0xe2150c`, `0xe2170c`, `w3 = 0xf388` at `0xe21708` | 0xF388 = 62,344 |
| | `0xa62c5c`, `w2 = 0xff008` | `0xa64ddc`, `w3 = 0xff008` | 0xFF008 = 1,044,488 |
| `0x1e5f87c`, slot 13 of `0x4458698` | `0x1e617a8`, `0x1e61980`, `w2 = 0x97e08` | `0x1e61a74`, `0x1e61c0c`, `w3 = 0x97e08` | 0x97E08 = 622,088 |

Only the 0xF388 block goes on the wire in a trade: every capacity a Scarlet posted is 0xF388 or
0xFF008 (The eleven streams), and a station's set is 0xF388 bytes (The records). The 0x97E08-byte
object never transfers in a trade. The object at the job's `+0xd0` is therefore of the 0xF388
class; which instance it is was not traced (the factory builds it through `0x1e34b6c` ->
`0x1e35e88`).

`0x1e52004` counts, over four slots at `+0xd0 + 0x30*k`, those holding a peer pointer with the byte
`+0xd8` set. The console's own slot gets `+0xd8` in `0xe21154` (`memcpy(slot, [+0x90], 0xf388)` at
`0xe21248`, then `+0xd8 = 1` at `0xe21258`); `0xe21154` is called from `0xa536e0`, `0xd6dc88`,
`0xe21128` and `0x195160c`. A peer's slot gets it in `0xe212b8` (called from `0xa536f0`, `0xd6dc98`,
`0xe21138`) only when the send to that peer has started (`+0xda`), the receive from it has started
(`+0xd9`), the console's own 0x81 stream is in state 3 (`0xe2144c`) and the peer's is in state 6
(`0xe21404`); state 7 clears a flag. The stream states are Pia's
([Protocol 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)): own state 3
is every chunk of the console's set acknowledged, peer state 6 every chunk of the peer's received.
The 0x97E08 class has the same pair, `0x1e60284` and `0x1e615e8`.

On the wire the announcement follows the end of the console's own transfer. In 37 of 40 announced
seats the type 7 on 0x80 port 2 came 0.020 to 0.106 s after the console's last send of its own set
on 0x81 port 0. The other three came 0.545, 0.864 and 3.902 s after it; in each, the announcement
preceded the next periodic console header that showed the set acknowledged.

The relay is an object of 0x388 bytes (vtable `0x44e56f8`), the singleton `[0x46da9c0]` =
`0x4739430`, created by `0x165a200` from `0x1659b70` only when none exists (`0x1659b18`). Its
station-event handler is `0x12fbb90`, reached through the thunk `0x2b71650`:

| event | effect |
|---|---|
| 0, a station joined, on the master | `0x12fbf8c` sends the current slots to it unless it is the master |
| 1, the console's own id | a pending request not yet done is completed with result 5 (`0x501` at `+0x42`), then `0x12fbef0` |
| 1, the master's id | `0x12fbef0` |
| 1, any station, on the master | then `0x12fcebc` drops the queued elements that station relayed |

`0x12fbef0` removes every slot through `0x12fc644`, which completes a pending type-1 request whose
key matches, empties seven queues (every one but `+0x1c8`) and zeroes `+0x1c0` and `+0x1c4`. It
leaves the pending request at `+0xb8`. A pending type-0 request, the announcement's, is completed
only by the type-7 receiver, the type-0x0D receiver and the own-leave event. The other types have
their own: the type-9 receiver `0x18b6710` completes type 2, the type-0xA receiver `0x1945404` type
3, the type-0xB receiver `0x279be18` type 4.

The relay lives until the application exits. Three functions write its holder `0x4739430` (GOT
`0x46da9c0`, guard `0x4739440` through GOT `0x46da9b8`):

| function | what it does |
|---|---|
| `0x165a2b4` | the assignment, called only by the creator `0x165a200` (`bl` at `0x165a230`) |
| `0x279d610` | the reset (`str xzr` at `0x279d62c`), then the destructor and a free; called only from `0x279d5d0` in `0x279d5ac` and `0x2b71684` in `0x2b71660`, the relay's own destroy slots, which have no direct callers |
| `0xa15f74` | the holder's static destructor (`str xzr` at `0xa15f90`), registered through `__cxa_atexit` by every guarded initialisation of the holder |

The relay's vtable group (relocations at `0x44e56f8`):

| entry | slot | function |
|---|---|---|
| `0x44e56f8` | 0 | `0x279a7b0`, destructor |
| `0x44e5700` | 1 | `0x2b7164c`, `b 0x279a7b0` |
| `0x44e5710` | 3 | `0x279d5ac`, destroy the singleton |
| `0x44e5718` | 4 | `0x12fbb90`, the station-event handler |
| `0x44e5730`, `0x44e5738` | interface at `+0x20`, slots 0 and 1 | `0x2b7165c` (`ret`), `0x2b71660` (destroy the singleton) |
| `0x44e5750` | interface at `+0x28` | `0x2b71650`, the listener thunk to `0x12fbb90` |

The base constructor `0x165b0c8` (`bl` at `0x165a9b8` in the constructor `0x165a998`) installs a
second vtable `0x44e5768` with the same slot 3 and `+0x20` slot 1 (`0x44e5780`, `0x44e57a0`), and
sets `[holder+8] = 1`.

The creator registers the `+0x20` interface with `0xf0ba9c` (`bl` at `0x165a244`), which appends it
to a finalizer list of up to 0x400 entries at `0x4763a18`, count at `0x4765a18`. Of the 55 code
references to the list, 53 are registrations and two are its walkers: `0x27aff48` calls slot 0 of
every entry and `0x27b0054` slot 1, both in reverse order, the second then zeroing the count
(`0x27b00ac`). Both are called only from `0x20e9c78` (`0x20e9cec`, `0x20e9d00`), slot 5 of vtable
`0x44e6be0`, reached from `0x20e9bdc` (slot 5 of `0x44a89a0`) and `0x92d648` (slot 5 of
`0x443ffd0`), which ends in `b 0x343e6c0`, `nn::account::CloseUser`: the application's finalize.
Leaving the Link Trade search or the Poke Portal does not destroy the relay; a generic virtual call
on its slot 3 cannot be excluded statically. A request pending at `+0xb8` survives every seat,
search and menu until one of its completers runs.

### Opening the channel

| time | station | port | bytes | |
|---|---|---|---|---|
| 0.29 | host | 1 | 31, INITIALIZED | `b90104b902b9027b0001b902b902320101b902b902320201b902b902320301` |
| 1.84 | joiner | 1 | 31, INITIALIZED | the same 31 bytes |
| 2.43 | joiner | 2 | 15, INITIALIZED | `03b90200bc09000000000000000000` |
| 9.00 | host | 1 | 11 | `b90101b902b90280800001`, and the joiner sends the same back |

Port 1 is the channel table, the Arceus mechanism: a station announces the handler keys it opens
and sends on a key only once its peer has announced it. A joiner's table is byte for byte the
host's. Until the joiner announces its own, the host opens no channel and stays on its search
screen however complete the identity exchange is.

The host's open of key 0x80 comes first, and a joiner that reaches its trade screen before it has
seen the host's open never sends its first game message: its screen draws, and A on a Pokemon
gives no menu. A retail console opens its own key 0x80 at 9.15 s after the seat. A host that opens
at 11.0 s gets a trade screen with no menu; a host that opens at 6.0 s gets the console's first
game message within a second of the console's own open, and the menu.

The reliable header on 0x7C carries no destination bitmap: nine bytes, the sequence and the lowest
pending both the message's own sequence. An open is flags 0x0F and a later update on the same port
0x07.

### The trade

Everything above the channel is on port 0. A message is a four-byte header and a body.

| time | station | body | |
|---|---|---|---|
| 9.15 | joiner | `80000100` + 238 bytes, zlib, two fragments | the first game message, START then END |
| 9.31 | host | the same | |
| 58.2 | host | `80000200` + 348 bytes | the offered Pokemon |
| 67.6 | joiner | `80000200` + 348 bytes | |
| | either | `8000040100` | the player backed out of the wait; the station leaves the network after it (retail) |
| 112.7 | host | `80000300` | |
| 116.0 | joiner | `80000300` | |
| 117.5 | joiner | `80000500` | |
| 117.5 | host | `80000500` | |
| 117.6 | both | port 1, `b90101b902b90280800101` | a table update opening the next key |
| 117.7 | both | `80010103`, `80010203` | |
| 117.8 | both | `80010106`, `80010206` | |
| 118.2 | both | `8001010b`, `8001020b` | |
| 118.9 | both | `8001010e`, `8001020e` | |
| 119.2 | both | port 1, `b90101b902b90280800100` | the table update that closes it |

Against a host here the retail console's offer arrives as the pair's, and the host's offer sent
in answer, byte for byte the pair host's message, is acknowledged and not taken: the console
stays on "waiting for a response". Its acknowledgement after that offer reads ack 6, field 6,
where the pair's joiner answered the same bytes with ack 4, field 3. The pair's host offered
first; a host here has only offered second.

A station sends its own identity **four** times, the two fragments and then the same two again
under the next two sequence ids, flags `0x1b`, `0x15`, `0x13`, `0x15`. A pair's host sends two
because its peer is its own clone. A host here must send four, and only after the station has
announced its key 0x80 on port 1. Sent before that announcement nothing on port 0 is dispatched at
all; sent as two, the station acknowledges them, answers the next message with `ack_id` 5 and
`lowest_pending` 5 where a pair's joiner answers 4 and 3, and the game never sees that message.
With four, the identity is dispatched as kind 1, the offer that follows is parsed, stored and drawn
on the station's screen, and the station offers, confirms and commits in answer
(`bin/sv_host.py --send-on-open`, `--offer-after-open`).

The `lowest_pending` field of a host's acknowledgements on 0x7C carries the host's own next
sequence, as it does on 0x81 (The sender's own lowest pending is what closes the gap at 5 and 6).
Carrying one past the station's last sequence instead leaves the station's receive window waiting
for that number, and the host's next message, which is below it, is acknowledged and discarded at
`0x6f03cc` without reaching the game (`docs/pia.md`, "What the receiver discards in silence"). The
two numberings run level up to the commit, where the station commits first: its `80000500` is its
seventh message on the stream, the host acknowledges it as eight, and the host's own `80000500`,
also a seventh, arrives at a window whose base is already eight. With the field set to the host's
own next sequence the commit is dispatched, the station opens key 0x0180, the four exchange steps
run in both directions, the station closes the key and the trade completes: the Pokemon the host
offered is in the station's box and the one it offered is gone.

The `8001` messages run in pairs, a 01 and a 02 under the same fourth byte, which steps 03, 06, 0B,
0E. The trade applies over those four steps and both screens return to the trade menu.

On a retail trade against `bin/sv_host.py` the host's messages on the trade stream number 5 for the
offer, 6 for the confirmation, 7 for the commit and 8 to 15 for the exchange steps; the console's
are 5, 6, 7 and 8 to 11, and its key-0x180 open and close are its port-1 messages 3 and 4. Its
acknowledgement of the host's offer reads `ack_id` 6 and `lowest_pending` 5.

Both instances ran from one save copied twice, and the game traded a Pokemon between two identical
trainers without complaint.

### A confirmation sent before the station's own offer

A station confirms a trade only after its own record is on the wire. A host that sends `80000300`
while its `80000200` is still queued crashes the game: the console's screen goes black and the
system error dialog comes up, with the offer and the confirmation both acknowledged at the
transport. The crash follows the confirmation, not the record, which the receiver stores without
checking it.

`bin/sv_host.py --offer-after-open` and `bin/sv_join.py --offer-after-open` hang the offer on the
peer's key-0x80 announcement, and the stage answers the peer's own offer with a confirmation under
its own delay. The two delays are gaps between messages rather than positions on a clock, so an
offer hung eight seconds out and a confirmation answering a peer that offered after three go out
in the wrong order. Both launchers queue a trade message no earlier than one already queued for
the same station and port, which holds the order the stage produced.

### Two trades in one seat

A seat carries more than one trade. Key 0x0080 is announced open once and stays open; key 0x0180
opens and closes once per trade, and the second trade is the same cycle again on the same stream,
the sequence numbers running on: the host's offer at 16, its confirmation at 17, its commit at 18
and the exchange steps at 19 to 26, against 5 to 15 for the first.

Both screens return to the trade menu when the exchange key closes, and the console offers again
there with no new association, no Session exchange and no identity. `TradeStage` and
`JoinerTradeStage` take a list of records and start the cycle again at the next one, and
`--trade-offer` is repeatable on both launchers.

### The first game message, and what it carries

The first message a station sends on 0x7C port 0 is `80 00 01 00` and 2557 bytes. It goes out as
two reliable fragments, START then END, 238 compressed bytes between them for a pair's host and 195
for a retail console. Each fragment is a zlib stream of its own, header `484b`, and the message is
the two inflations concatenated: neither fragment alone is the record.

The body is the game's tagged serialisation, the encoding `pokeldn.pla.channel_table` reads for the
channel table. It is a tuple of two fields: a `0xbc` blob of 2550 bytes, and the byte `0x04`.

    b9 02          a tuple of two fields
    bc 81 f6 09    a blob, 0x9f6 = 2550 bytes
    ...            2550 bytes
    04

The blob is 850 little-endian three-byte values. Most are 1; the others are bitmasks, among them
`0x0fffff`, `0x0002ff`, `0x00003f` and 0. It is a station's own state rather than a table both
carry: 38 of the 850 entries differ between a retail console's message and an emulated pair host's,
and where the pair host carries `0x0fffff` at entry 36 the console carries `0x040000`. Seven
entries are zero in both. What the index counts is unknown.

`scratchpad/sv_identity_open.txt` replays a pair host's four fragments, which is what the retail
trade ran with. `scratchpad/sv_identity_template.bin` is the first fragment's inflation alone, 1395
bytes, and is half a record.

### The record a trade message carries

The 348-byte body of a `80 00 02 00` message is four bytes and a Pokemon. The four are the constant
`bc 81 58 01`, the same on a retail console's offer and on an emulated pair host's. The 344 behind
them are one Gen-9 party record, the structure PKHeX calls PK9, under the crypto Gen 8 already uses
(`pokeldn/gen8.py`): four 0x50-byte blocks from 0x08 permuted by `(EC >> 13) & 31`, an LCG
`seed = seed * 0x41C64E6D + 0x6073` over the 16-bit words, and a 16-bit checksum of the decrypted
body up to 0x148. The party tail at 0x148 is outside the permutation and the checksum, and re-seeds
the LCG from the same encryption constant.

    0x000  u32  encryption constant, in the clear
    0x004  u16  sanity, 0 on every record measured
    0x006  u16  checksum, in the clear
    0x008       four 0x50-byte blocks, encrypted and permuted        -> 0x148
    0x148       level, a pad byte and the six stats, encrypted       -> 0x158

The field map is PK9's [`PKHeX.Core/PKM/PK9.cs`], and `pokeldn/sv/pokemon.py` reads and writes it.

| offset | field | | offset | field |
|---|---|---|---|---|
| 0x08 | species, the internal index | | 0x8A | current HP |
| 0x0A | held item | | 0x8C | six 5-bit IVs, then the egg and nicknamed bits |
| 0x0C | trainer id, secret id | | 0x90 | status condition |
| 0x10 | experience | | 0x94 | tera type, original and override |
| 0x14 | ability, then its number in bits 0-2 of 0x16 | | 0xA8 | handler name, 26 bytes |
| 0x18 | markings | | 0xC2 | handler gender, language, current handler at 0xC4 |
| 0x1C | personality value | | 0xC6 | handler id, friendship, memory |
| 0x20 | nature, stat nature | | 0xCE | version, battle version |
| 0x22 | fateful in bit 0, gender in bits 1-2 | | 0xD0 | form argument |
| 0x24 | form | | 0xD4 | affixed ribbon, language at 0xD5 |
| 0x26 | six EVs, hp atk def spe spa spd | | 0xF8 | original trainer name, 26 bytes |
| 0x2C | six contest values | | 0x112 | trainer friendship and memory |
| 0x32 | pokerus | | 0x119 | egg date, met date at 0x11C, obedience level at 0x11F |
| 0x34 | the ribbon and mark flags | | 0x120 | egg location, met location |
| 0x48 | height scalar, weight scalar, scale | | 0x124 | ball |
| 0x4B | the DLC move-record flags | | 0x125 | met level in bits 0-6, trainer gender in bit 7 |
| 0x58 | nickname, 26 bytes of UTF-16LE | | 0x126 | hyper training flags |
| 0x72 | four moves, their PP at 0x7A, PP ups at 0x7E | | 0x127 | the HOME tracker |
| 0x82 | four relearn moves | | 0x12F | the base-game move-record flags |

The map leaves nothing unread. A record rebuilt from 344 zero bytes and the fields `read` reports
of a console's own comes out that record byte for byte, checksum included
(`tests/test_sv_pokemon.py`).

The species field is the game's internal index, which parts from the National Dex at 917
[`PKHeX.Core/PKM/Util/Conversion/SpeciesConverter.cs:92`]. Under that number the two agree.

A retail Scarlet's own offer reads as species 50 at level 3, nickname `Taupiqueur`, trainer
`Gurvan`, handler `Pauline`, Poke Ball, tera type 4, met on 2025-08-05 at location 64, language 3,
version 50, moves 10 and 28, experience 27, which is level 3 on the Medium Fast curve, stats
14/9/5/10/7/8 and a current HP equal to the first of them. The emulated pair's offer reads as
species 906 at level 1, nickname `Sprigatito`, trainer `Mattia`, no handler, language 4. A wrong
block order survives the checksum, so what pins the order is a record reading as a Pokemon.

`bin/sv_host.py` prints what it offers and what the console offers, and `--offer-out FILE` writes
the console's own message where a later read can take it. `--trade-offer` accepts a bare 344-byte
record, plain or encrypted, as well as the 348-byte body and the 352-byte message.

### A record composed here

**A record built from 344 zero bytes is in a retail Scarlet save.** `pokemon.build` composed a
shiny Imposter Ditto with no nickname, the host offered it, and the console keeps it. Every field
the summary shows is the one composed, read off the screen: species 132 drawn as Métamorph, no
nickname, original trainer POKELDN, id 993401, level 1, Transform as its only move, French as the
record's language, the Normal Tera type, the ability Imposter, the Hardy nature, met at level 1 on
2025-09-22 at location 64 drawn as Caverne de la Crique, no ribbons, male, and the shiny sparkle.
The stats read 12 and 6 6 6 6 6, which the game computed; the record carried zero.

The trainer id the summary shows is `(TID16 | SID16 << 16) % 1000000`: 12345 and 54321 draw as
993401, and 8131 and 64817 draw as 855043. The characteristic line is drawn from the encryption
constant and the individual values, so both are read.

A retail Scarlet also keeps a record edited from one of its own. The host offered the pair host's Sprigatito
with its nickname, its nicknamed flag, its personality value and its six individual values
rewritten by `bin/sv_host.py --offer-set`, and the console drew it, offered in answer, confirmed,
committed, ran the four exchange steps and kept it: a shiny called POKELDN with perfect individual
values. The station's own messages are the same as against a replayed record, message for message,
and it left with a Session leave request rather than a timeout.

Nothing in the composed record is checked before the trade screen draws it. The offer's checksum
covers the decrypted body and the host writes it, so a rewritten field costs nothing beyond
re-sealing (`pokeldn/sv/pokemon.py`).

The level is derived from the experience, not read from the level byte. A record built with the
byte at 0x148 set to 100 and the experience at zero arrives on the console as a level 1 Pokemon
with no experience. The same record with 1,000,000 experience arrives as level 100 with that
experience, so composing a record at a chosen level means writing the experience its species'
growth rate asks for, and the level follows.

The six growth curves are in `PKHeX.Core/PKM/Util/Experience.cs`. Their level-100 requirements
are 1,000,000, 600,000, 1,640,000, 1,059,860, 800,000 and 1,250,000. The game's own species table
says which curve a species uses: `personal_sv`, one 0x50-byte entry per species and form, with the
base stats at 0x00, the gender ratio at 0x0C, the growth curve at 0x0F and the three abilities at
0x12, laid out by `PersonalInfo9SV.cs`. `scratchpad/sv_tables.py` reads it.

The table and the console agree. Species 132 is curve 0, whose level 100 is 1,000,000, which is the
experience the console drew as level 100; its abilities read 7, 7 and 150, and 150 is the one the
summary showed as Imposter.

The stats the game computes are the series' own arithmetic over the base stats in that table:

    HP    = (2 * base + IV + EV/4) * level / 100 + level + 10
    other = ((2 * base + IV + EV/4) * level / 100 + 5) * nature

A Ditto with perfect individual values, no effort values and a neutral nature comes to 12 and
6 6 6 6 6 at level 1 and 237 and 132 132 132 132 132 at level 100, and the console showed both for
records whose own stat fields were zero.

The receiving game recomputes the party stats. A record sent with a maximum HP of 99 and a current
HP of 99 at level 1, against a species whose own value is 12, arrives on the console reading 12.
Everything else the record carries is kept as sent: the nickname and its flag, the personality
value and its shininess, the individual values, the trainer names, the level and the experience.

### What a joiner sends, in order

Everything a pair's joiner puts on the wire before the game's first message, measured from its own
log:

| time | message |
|---|---|
| 0.17 | Net 0x12, echoing the sequence of the host's 0x11 |
| 0.04 | the Session join request |
| 0.38 | Net 0x51, echoing the sequence of the host's 0x50 |
| 1.63 | the Session type 6, acknowledging the station update |
| 1.82 | Clone Clock 0x77, eighteen zero bytes; the host answers with a one, sixteen bytes and a trailing byte |
| 1.68 | the eleven bulk acknowledgements and the stream opens on 0x81 ports 0 and 4 |
| 1.68 | the channel table on 0x7C port 1 |
| 2.03 | its own 44 records on 0x81 port 1 |
| 2.43 | the open on 0x7C port 2 |

A host that receives all of it answers Net once rather than repeating: against a console that is
sent the 0x12 and the 0x51, Net traffic falls from 212 messages a seat to 2.

### The joiner's side of the trade

A joiner's whole 0x7C script, from the pair's own log, with the sequence each message carries on
its port. Port 1 is the channel table, port 2 the game's join, port 0 the game itself.

| port | sequence | message |
|---|---|---|
| 1 | 1 | the channel table, the same four keys the host announces, INITIALIZED |
| 2 | 1 | the type-3 join, `03b90200bc09` and nine zero bytes |
| 0 | 1 to 4 | the identity: the two zlib fragments, then the same two again |
| 1 | 2 | `b90101b902b90280800001`, key 0x80 open, after the fourth fragment |
| 0 | 5 | the offered Pokemon |
| 0 | 6 | the confirmation |
| 0 | 7 | the commit, which the joiner sends first and the host answers |
| 1 | 3 | `b90101b902b90280800101`, key 0x0180 open, after the host's own |
| 0 | 8 to 11 | one echo of each step the host opens, 03, 06, 0B and 0E |
| 1 | 4 | `b90101b902b90280800100`, the close |

The identity goes 0.15 s after the host's key-0x80 open and the key-0x80 open 0.21 s after it, so
the four fragments precede it. The joiner echoes a step's `8001 01 SS` and sends nothing for the
`8001 02 SS` that closes it.

The rules a host owes its station hold in the other direction, since they are the receiver's.
The `lowest_pending` field of a joiner's acknowledgements on 0x7C is the joiner's own next sequence
on that port, and the field on the bulk acknowledgement of its own 0x81 stream is one past the
highest record id it sent: left at 1, a host acknowledges record 5 and waits for the rest of the
set for the whole session, which is what a station's own next acknowledgement declares instead
(The sender's own lowest pending is what closes the gap at 5 and 6). A joiner declaring a number
drawn from the host's numbering walks the host's receive base past its own later messages, which
then arrive below it and are acknowledged and discarded at `0x6f03cc` without reaching the game
(`docs/pia.md`, "What the receiver discards in silence").

`pokeldn.sv.trade.JoinerTradeStage` is that side as a state machine and `bin/sv_join.py
--trade-offer` runs it, with `--send-on-open` for the identity fragments the key-0x80 open gates.
`tests/test_sv.py` drives the stage with the host's half of the pair's message list and pins what
it answers to the joiner's half.

### What a trade rewrites, measured on a record that came back

A record composed here was traded onto a console, kept in its save, and offered back in a later
trade. The two wire records differ in 27 of their 344 bytes and in seven fields, and every one of
them is a handler field or a derived value:

| field | as sent | as it came back |
|---|---|---|
| `current_handler` | 0 | 1 |
| `ht_name` | empty | the console player's name |
| `ht_language` | 0 | 3 |
| `ht_friendship` | 0 | 50 |
| `nickname` | empty | the species name in the console's language |
| `current_hp` | 0 | 237 |
| `stats` | zero | the six the game computes |

Everything else is stored as sent: the encryption constant, the personality value, the trainer
identity, the moves and their PP, the individual, effort and growth values, the ball, the met
data, the experience and the level byte, the size scalars and the tera type. An empty name slot
comes back as the species name, which is the same rule the Sword Mystery Gift record follows
(`docs/swsh_gift.md`).

### Joining a searching console: a trade, and what decides the seat

**A trade is complete in the joiner direction on a retail Scarlet (2026-09-22).** The console
hosts from its Link Trade search, `bin/sv_join.py` joins it, and the console reaches its trade
screen, offers, takes the joiner's offer, confirms, commits, runs the four exchange steps and
keeps the record the joiner composed. The joiner's side of the exchange is
`pokeldn.sv.trade.JoinerTradeStage` and its numbering is a pair joiner's: port 0 messages 5 to 11
and port 1 messages 2 to 4.

What the run takes, beyond the opening below: the station update taken as the seat, the type-3
join sent in answer to the console's own announcement, the four identity messages on 0x7C port 0
after the console opens key 0x80, and the `lowest_pending` rules of the host direction applied to
the joiner's own acknowledgements.

#### What decides a seat

A seat on a searching console's own network ends one of two ways, measured on a retail Scarlet
with the joiner's whole opening delivered.

Some seats end in host migration. About eight seconds in the console sends Session type 7, start
host migration, naming the joiner's variable id as the target, and from then on it sends
`01400000`, a bare NetStartHostMigration, about twice a second and nothing else. It answers
nothing after that: not the joiner's identity records, not its channel table, not its
acknowledgements. Host migration at the LDN level means the new host creates the network, which no
Pia message does; Legends Arceus completes the same migration when the joiner hosts a network on the same code (`docs/pla.md`).

The other seats run the game. In order, what the console sends:

| | |
|---|---|
| the seat | a type-5 station update naming the joiner's variable id and the player id its request stated, then the 41-byte join response |
| its opening | the bulk acknowledgements on all eleven streams, an 11-byte record on 0x81 port 1 and another on port 5 |
| its identity | 46 records on 0x81 port 0, the same shape a host here sends, and it acknowledges the joiner's own 44 to 47 |
| its channel table | on 0x7C port 1, the four keys `0x007b`, `0x0132`, `0x0232` and `0x0332` |
| `0db90101` | on 0x7C port 2, a type 0x0D with code 1, only in answer to a type-3 join sent before the announcement (one seat, 0.03 s after the join); the console's normal sequence has none |
| the announcement | on 0x80 port 2, zlib, 167 bytes inflated: a type 7 carrying kind 1, capacity 2 and the console's own station id, which is its constant id read big-endian |

The announcement is the message no emulated instance ever composed and the one the host direction
waits on a station to answer. A joiner answers it with the type-3 join on 0x7C port 2, as a pair's
joiner does 0.09 s after its host's own type 7 (`bin/sv_join.py`, `--port2-now` for the join sent
with the channel table instead).

The station update seats a joiner on its own: it carries the joiner's variable id before any join
response does, and a joiner that waits for the response sends nothing for the whole session.

## Unresolved

- Why two seats that completed both 0x81 transfers were never announced. Of the eight
  unannounced seats since the identity fixes (three more ended when the association dropped before
  the console sent a record), six ended with the console's own transfer unfinished: the four
  `--no-rtt` seats, and two seats the joiner left at 20 s while the console was still resending
  records the joiner's walk had dropped, whose sibling seats were announced at 13.26 and 17.81 s. In
  the other two, RTT answered at once, the console's set stood acknowledged at 7.65 and 7.88 s and
  the joiner's at 7.65 and 4.56 s, and the console sent nothing on 0x80 port 2 or 0x7C port 2 in 200
  and 24 s, presence-0x00 messages included. Its 0x80 port-2 bulk
  acks carried the destination bitmap `[2]` and a payload byte-identical to an announced seat's.
  The acknowledgement composer `0x6f2138` builds that bitmap from the registered-station pointers
  at `[window+0x40]`: it skips null entries at `0x6f2324`..`0x6f232c` and sets a station's bit at
  `0x6f22f8`..`0x6f230c` only after its acknowledgement-state checks, which may also consult the
  caller's mask at `0x6f2360`..`0x6f2370`. The bitmap therefore confirms a registered destination,
  but does not show that the trade job reached its announcement state. One followed a seat that ended
  in host migration 0.5 s in, the other a failed association (LDN reason `0xc9`). A migration before
  the seat does not decide it: of the seats that followed a migrated seat, two of three with prompt
  answers and three of three with answers 0.3 s late were announced. The candidates are no trade
  job running in the seat, the job in state 1 on a slot whose `+0xd9`/`+0xda` were never set for
  this peer, a request refused because an earlier one is still pending (result 8), and a type 7
  held in state 3 by vfunc20. On the patched Ryujinx with the GDB stub, on a seat not announced 3 s
  after the console's own set is acknowledged: whether the job Update `0x1e51a04` is hit at all, and
  its state `+0xb8` and result `+0x40`; at `0x1e51ae8`, the finished-slot count `x0` and the slot
  object's vtable `[x21]` (`0x4455ec0` or a sibling of the 0xF388 class confirms the attribution
  above); at `0xe45fb0`, the vfunc20 result `w8`; at `0x18ab8e8`, the pending request's type
  `[x8+0x40]` and done byte `[x8+0x42]`.
- Which path creates a type-2 request, and whether a stale one holds later seats. A client's type-2
  join request (`0x2799b10`) uses the same `+0xb8` and the same refusal; if its master leaves, the
  event runs `0x12fbef0` alone, the job ends at 15 s and nothing clears `+0xb8`, and the relay
  outlives every seat, so every later request on that console would be refused. The creator's sole
  caller `0x1e635fc` is reached only from `0x1d986d8` in `0x1d98698`, which has six callers:
  `0x1d96c38`, `0x1d9973c`, `0x1e50eec`, `0x1e51c40`, `0x1e638ac` and `0x1e63904`. The BoxTrade
  job's, `0x1e51c40`, is in its state 4 (jump table `0x3c5baf0`, handler `0x1e51b8c`, which gives
  up 15 s after entering it); `0x1e51b04`..`0x1e51b18` set state 2 when `0x1639910` says the
  console is the master and 4 otherwise, so that job builds a type-2 request only as a client.
  Whether the other five run in a Link Trade is unknown. The check: a `bin/sv_host.py`
  session in which the console joins as a client and the host stops before its type 9, then
  `bin/sv_join.py` without restarting the game, and once more after a restart.
- Whether a seat whose joiner answers no RTT request, reads every message and loses none of the
  host's records is announced. The four seats measured each lost a record on the air or ran with a
  walk that stopped at presence 0x00 (The retail acknowledgement, and a flood of retransmits).

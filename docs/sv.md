---
title: Scarlet and Violet
nav_order: 9
has_children: false
---

# Scarlet and Violet

Pokemon Scarlet (`0100a3d008c5c000`) and Violet (`01008f6008c5e000`) are native Switch titles with
Pia linked into `main`. Both trade with a retail console in both roles: `bin/sv_host.py` hosts for
the console's offline Link Trade search, `bin/sv_join.py` joins the console's network.
A retail Violet joins a host advertising Scarlet's local communication id, and its own search
network advertises Scarlet's id too (`0x0100a3d008c5c000`, application version 21, scene 4).

Addresses are offsets into the decompressed `main` of update 4.0.0 (`tools/switch/nso_read.py`):
text `0x0..0x343fc90`, rodata from `0x3440000`, data from `0x4383000`.

## The wireless layer

| | value |
|---|---|
| Pia header version | 11, the Legends Arceus band; `pokeldn.ldn.pia6` speaks it |
| header size | 0x1C, GCM tag 8 bytes |
| LDN passphrase | `W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL`, data `0x44dfd0a` |
| Pia game key | `p1frXqxmeCZWFv0X`, data `0x44dfcfe`, immediately before the passphrase |
| LDN local communication id | Scarlet's `0x0100a3d008c5c000` on both versions (neither id is a constant in the image; the NACP lists both) |

Passphrase and game key equal Sword/Shield's and Legends Arceus's.

## What a searching console advertises

The Link Trade search alternates hosting (new SSID each time) and scanning, hopping between
channels 1, 6 and 11; a host phase measures about five seconds.

    local_communication_id  0x0100a3d008c5c000, Scarlet's, on both versions
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
| the 40 game bytes | zero, or a nonzero value at game `+0x21` (`fb149700` seen), alternating every few seconds; a second console associates on either |

`pokeldn.sv.build_advertise_data` reproduces both beacons byte for byte.

## The protocols the game runs

A passive capture of a retail pair shows Net, RTT, 0x80 and 0x81, all to the broadcast address of
the session's `/24` with the recipient's variable id in the plaintext footer; the other six are
unicast, 802.11ax between two Switch 2 consoles, and never captured.

The game's setup `0x17ff030` creates, in order: Reliable `0x7C` and BroadcastReliable `0x80` on
port 0, Unreliable `0x68`, Reliable and BroadcastReliable on ports 1 and 2, `[0x44dfcd0]`
StreamBroadcastReliable `0x81` ports (eight on the wire), Clone Clock `0x77` and Clone Atomic
`0x74`. Pia adds Net, RTT, Session `0x98` and MonitoringData `0xA4`; NatTraversalResult `0xA0` only
when the network factory enables NAT traversal (`0x6d3138`), which a local network does not.

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

A retail Legends Arceus lists the same ten versions in its join request. A retail pair's opening,
times from one capture:

    +0.00   the joiner associates
    +0.06   host: Net 0x11 (station list), 0.12 s later Net 0x50
    +0.14   host: acks all eleven streams, opens two
    +0.89   joiner: RTT request, acks all eleven, opens two
    +0.97   host: first records on 0x81 port 0
    +1.26   joiner: first records on 0x81 port 1

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
    ...                 four stations: migration state, ranking (host 0, joiner 1, empty 0xff),
                        one byte, 16 address bytes, big-endian u16 port (12345)

`01 40 00 00` is a bare NetStartHostMigration, sent by a host handing its role over. A retail
Scarlet hosting from its search repeats it on a seat it hands to its joiner
([What decides a seat](#what-decides-a-seat)).

A host must write four station slots (Pia's count, not the game's limit of two). With two, the
joining game sends nothing and disconnects 5 s after association (4.98 to 5.01 s over 49 joins), a retail
console answering Net 0x11 with ICMP port 12345 unreachable; with four it answers Net 0x12 and sends
its Session join request. Opening flags 0x31 (retail) or 0x01 make no difference.

### The eleven streams

    0x80  BroadcastReliable         ports 0, 1, 2
    0x81  StreamBroadcastReliable   ports 0 to 7

Both stations ack all eleven about once a second with `pokeldn.ldn.reliable5`'s bulk ack: four
entries, station byte zero, entry *k* one past the highest sequence of station *k*, destination-bit
count 3, the peer's bit in the bitmap. A station opens two streams with an eleven-byte INITIALIZED
message and sends records on the port of its station index (as `pokeldn.pla.data_exchange`).

| station | opens | sends records on |
|---|---|---|
| host, index 0 | 0x81 ports 1 and 5 | 0x81 port 0 |
| joiner, index 1 | 0x81 ports 0 and 4 | 0x81 port 1 |

The open payload is `0000000000f38800000000` on ports 0 and 1, `00 <port> 00 00 0ff0 0800000000` on
4 and 5: a StreamData kind 0 posting a receive of 0xF388 (transfer 0) or 0xFF008 (4 and 5). The 0xFF008 transfer is never sent in a trade.
`pokeldn.sv.streams` builds all of it; `tests/test_sv.py` pins it to retail bytes.

### The Pia message flags

Both retail stations send (the Arceus host's establishing flag is not used):

| message | flags |
|---|---|
| RTT, stream opens, a record's first transmission | 0x00 |
| a record sent again | 0x40 |
| the bulk acknowledgements | 0xA0 |
| the host's Net 0x11 and 0x50 | 0x31 |
| NetStartHostMigration | 0x11 |

The message destination field is always zero. Flag 0x40 is `w4 = 1` from the `ReliableSlidingWindow`
send loop `0x6f0638` (0 when the send count `[slot+0x14]` is zero, `0x6f0908`; 1 for a resend
`0x6f0a9c` or early send `0x6f0c38`), stored by `0x6e7250` as byte 0 of the packet writer's option
block.

### RTT

Eleven bytes: kind, big-endian u64 clock, big-endian u16 target. A request is kind 0, target 0; the
answer kind 1 with the same clock and the requester's variable id, within 20 ms on retail.

RttProtocol (vtable `0x43e5a28`) keeps a 0x40-byte record per station at `[proto+0x60] + index*0x40`:
sample count `+0`, ring head `+4`, capacity 9 at `+0x10` with the ring inline behind it, a median
cached at `+0x3c` for the count at `+0x38`. A sample is clock now less the echoed clock (`0x6f34b4`);
a sample of zero or less is discarded (`0x6f34e0`). Requests go at interval `[0x46d1528]` until every
ring is full, then at `[0x46d1520]` = 500 (written at `0x6f2fcc` and by the game at `0x1e7c2bc`).
Station event 0 or 1 clears that station's record (vfunc11 `0x6f3bd8`): a new seat has no sample.

GetRtt (`0x6f4498`; `0x6f44bc` with a count *n*) returns -1 with no sample, otherwise the median of
the last min(count, *n*) samples; min `0x6f44e4`, max `0x6f4508` and sample count `0x6f452c` sit
beside it. The only callers are the SessionTransportAnalyzer's monitoring copy
(`0x6f9ab0`..`0x6f9ad4`) and the `ReliableSlidingWindow` retransmit deadline `0x6f0d14`, called from
the send loop at `0x6f073c`:

    deadline = now + [window+0x80] + 1.4 * (max over the destinations of GetRtt(count))

With no sample, `0x6f0d14` returns the unscheduled marker `[window+0x5c]`: a message is sent once
when queued (`0x6f1bbc`..`0x6f1bd4`) and skipped at `0x6f0a18` until a sample re-arms it
(`0x6f09f4`..`0x6f0a08`). A window with no RTT sample never retransmits.

The constructor `0x6eeea8` (callers `0x6e69f8`, `0x1800038`) sets `[window+0x80]` to
`ticks_per_second * 33 / 1000` (`0x6eef34`..`0x6eef74`; 633,600 ticks, 33.0 ms at 19.2 MHz), marker
`[+0x5c]` 0, base sequence `[+0x30]` 1, own index `[+0x10]` 0xfd, compression `[+0xa4]` 1,
early-send limits `[+0x88]`, `[+0x89]` 0. The only later writer is `0x6f1fc8` in vfunc17 `0x6f1f98`
(from `ReliableProtocol::vfunc17` `0x6eebbc` and `BroadcastReliableProtocol::vfunc17` `0x6e6818`, no
known caller). The send loop runs once per 16.7 ms frame, so a resend leaves on the first frame at
or after `33 + int(1.4 * RTT)` ms: 83 ms at an RTT of 34 ms, 550 ms at 358 ms.

### The records

A record is one reliable message with the ZLIB flag, a zlib stream with a 4 KB window (`484b`),
inflating to 1395 bytes, `[window+0x70]`: one chunk of a 0x81 transfer under Pia's StreamData header
([Protocol 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)):

    +0x00  1   StreamData kind: 1 the first chunk of the block, 2 a later chunk
    +0x01  1   transfer id, 0
    +0x02  1   percent of the block delivered after this chunk
    +0x03  4   zero, the capacity field of a kind 0
    +0x07  4   big-endian u32 0x00000568, the 1384 bytes that follow

A station's block is 0xF388 (62,344) bytes: 45 chunks of 1384 and one of 64, ids 1 to 46, percent
byte `floor(k * 1384 * 100 / 62344)` (2, 4, 6, 8, 0x0b, ..., 0x37 at 25, 0x52 at 37, 0x64 at 46). The
first chunk carries the partner shown on screen:

    +0x0b  5   unread
    +0x13  26  the player name, UTF-16 little-endian, NUL-padded
    +0x2d  22  the account identifier, ASCII, `u-` and twenty characters
    +0x53  1   5

Chunks 2 to 24 are high-entropy; 25 to 46 are zero. A station sends its whole set at once, usually
ids 1, 25, 26 to 36 and 46 in the first packet, 2, 37 and 38 to 45 in the second, then 3 to 24 one
per packet (41 of 48 retail sets). The identical zero chunks travel behind a presence byte of 0x00,
every header field inherited ([Message framing](pia.md#message-framing)). A set usually leaves
within 0.2 s (46 of 52 retail sets within 0.19 s). `pokeldn.sv.streams.decompress` reads them.

`pokeldn.sv.reference` ships a station's 44 records and its two identity fragments on 0x7C port 0,
recorded from an emulated Scarlet whose player is `Player`, account identifier unset. `bin/sv_host.py`
and `bin/sv_join.py` send them unless given `--record-set`, `--send-on-open` or `--no-identity`.

### The retail acknowledgement, and a flood of retransmits

A retail station acks a peer's record stream with ack id one past the contiguous run, field 0x50
equal to it, and a mask where bit *b* of byte *k* is id `ack_id + 1 + 8k + b`: a host holding ids 1
to 4 and 7 to 38 sent `0005 0005 feffffff01`. Ids below the peer's own `lowest_pending` count as
held. `pokeldn.sv.streams.ack_position` builds this (pinned in `tests/test_sv.py`); `bin/sv_join.py
--ack-highest` sends one past the highest id seen instead.

A host resends every unacknowledged record on the RTT deadline with flag 0x40, one round per packet,
lowest id first, shrinking as acks arrive. A message walk that stops at a presence byte of 0x00 reads
only each round's first record and takes 19 rounds; `--ack-highest` moves `lowest_pending` from 1 to
38 at once. Unacknowledged, a host resends every pending record each round; at a small RTT that is
several hundred records a second (435 to 494 measured at HT MCS3, about 3% of the air), enough to
fill the 150 KB/s of a board's serial line
([the serial ceiling](hardware_esp32.md#the-serial-ceiling)). Round interval, `[window+0x80] +
1.4 x RTT` rounded up to the frame, against the joiner's answer delay:

| answer delay | estimated RTT | round interval, seat medians |
|---|---|---|
| 0.000 s | 0.013 to 0.017 s | 0.065 to 0.069 s |
| 0.000 s | 0.033 to 0.038 s | 0.078 to 0.116 s |
| 0.000 s | 0.053 to 0.059 s | 0.115 to 0.221 s |
| 0.318 to 0.328 s | 0.354 to 0.363 s | 0.532 to 0.555 s |

A record's interval converges on it as the RTT ring fills (0.19 s with 4 to 5 answers, 0.10 s with
8 to 18, 0.082 s with 20). Constructor `0x6eeea8`, send buffer `0x6e6e94`, enqueue `0x6f1994` and
send loop `0x6f0638` under unicorn send 46 records in one pass and nothing more before the deadline.
A host's own processing sets the pace: its `lowest_pending` leaves 1 about 0.5 to 1.0 s after the
set whatever the ack delay (0.73 to 0.81 s with every frame acked within 7 ms), its ack masks
advancing in steps of about 0.19 s. It sends its set about 0.1 s after the joiner's stream open and
record set (`--open-delay`, `--record-delay`). RTT answers it holds before then bring the round
interval below that latency, and it resends records the joiner already holds; answering RTT 0.3 s
late avoids it. Measured on retail seats:

| RTT answers before the set | answer delay | seats | records resent before `lowest_pending` left 1 | left 1 after |
|---|---|---|---|---|
| 0 or 1 | 0 | 3 | none in two, 138 in one | 0.78 to 0.81 s |
| 3 to 6 | 0 | 4 | 122 to 137, each id every 0.18 to 0.20 s | 0.73 to 0.80 s |
| 0 | 0.3 s | 4 | none | 0.91 to 1.01 s |
| 1 to 7 | 0.3 s | 9 | none | 0.50 to 0.58 s |

`--rtt-delay 0.3` answers RTT requests 0.3 s late, which keeps the round interval above the host's
ack latency. `--leave-on-migration N` ends a seat N seconds after the console sends Session type 7,
and `--announce-timeout SECONDS` leaves an unannounced seat; both scan again. `bin/sv_join.py` acks
a new record at once, a repeat at most once per 50 ms per stream (`--repeat-ack-gap`), one ack per
stream per packet.

With no RTT sample the 0x81 streams never retransmit
([Protocol 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)): a record lost
on the air stays pending, the host's `lowest_pending` stops at its id, and the peer is never
announced.

RTT samples enable retransmission; the announcement job has no RTT gate. A loss-free emulated
Scarlet 4.0.0 host announces and completes a trade with no RTT requests or answers. A missing identity record holds the BoxTrade job in state 1 (`+0xb8`); the finished-slot
count at `0x1e51ae8` remains 1 against a required 2 until retransmission completes the set.

### What a passive capture misses

Both consoles pack several MSDUs into one A-MSDU frame. A passive capture must unpack the subframes
or it loses most Pia packets (one capture: 313 readable without, 3667 with).

## The link code

A Link Code rides the advertisement twice; the scene id stays 4. The user password is the code,
NUL-padded to sixteen bytes, XORed with `e5ab19ed742b6d40885998bf968aa166`, the Legends Arceus mask
under the same game key ([docs/pla.md](pla.md)). The game bytes carry the code in clear at +0x00 and
its length as a u32 at +0x24. `pokeldn.sv.build_advertise_data(code=...)` reproduces a retail
console searching with 12345678 byte for byte.

A searching console joins only a host advertising its code (`bin/sv_host.py --code`). A retail
console hosting under a code accepted a joiner advertising none. `bin/sv_join.py --code` joins only
a console searching with that code.

## Where the code is

RTTI names come from the binary's type_info records (`tools/switch/rtti_names.py`, 208 `nn::pia`
classes).

| address | what |
|---|---|
| `0x697134` | the Pia header initializer: magic `0x32AB9864` at `+8`, version `0x0b` at `+0xc`, header size 0x1c at `+0x5f8` |
| `0x696f10` | the header parser, fields in version-11 order |
| `0x697034` | the payload bound: a length above 0x5a3 returns null |
| `0x3c0c8c0`, `0x44dfcfe` | the passphrase (rodata) and the game key (data) |
| `0x6b43a8` | `LdnConnectionStatus::vfunc20`: `GetNetworkInfo` participants to station addresses |
| `0x6b45e0`..`0x6b4754` | its loop over eight 0x40-byte participant slots (address `+0x108`, present byte `+0x113`) against the station array at object `+0x30`, count `+0x38` |
| `0x6b3090` | `LdnProtocol::vfunc104`, another `GetNetworkInfo` reader |
| `0x046ca878` | the GOT slot for `nn::ldn::GetNetworkInfo`, six call sites |
| `0x475ea68`, `0x475ea6c`, `0x475ea70` | Reliable 0x7C handles, ports 0, 1, 2 |
| `0x475ea74`, `0x475ea78`, `0x475ea7c` | BroadcastReliable 0x80 handles, ports 0, 1, 2 |
| `0xe45e9c` | the one send on 0x80 port 2: resolves the protocol through `0xe21488`, hands the buffer to `0x107e060` |
| `0xe2246c` | the 0x5a0-byte application send under it, into `BroadcastReliableProtocol::vfunc12` `0x6e6344` |
| `0xe457cc`, `0xe45740`, `0xe460bc`, `0xe454ec`, `0xe46148`, `0xe461d4`, `0xe46260` | the composers of message types 6, 7, 8, 9, 0x0A, 0x0B, 0x0C, each calling `0xe45e9c` |
| `0xe45e1c`, `0xe46034` | the type-7 and type-8 field serializers (`0xb9` marker) |
| `0x46d6ca0`, `0x46d6ca8` | the drain `0xe44cf0`'s singleton, set up at `0xe44ac0` |
| `0x1e685a4` | the trade channel's port-0 receiver: kind (tagged integer), step, then kinds 0 to 5 via table `0x3c5bb82`; 1 identity (`0x1e6864c`, parsed into `+0xae0`), 2 offer (`0x1e686cc`: 344-byte blob parsed by `0x1db949c`, wrapped by `0xeee8fc` and `0xe13ad8`, stored at `+0xb8` by `0x1e684fc`, state `+0xc4` = 3), 3 confirmation (`0x1e68768`, step against `+0xe2`), 4 cancel (`0x1e68678`), 5 commit (`0x1e68780`, state `+0xc0` masked to 4) |

## The Session protocol is there and is never in a capture

`nn::pia::session::SessionProtocol` (id vfunc `0x6d9f3c` returns 0x98) sits next to `JoinMeshJob`,
`CreateMeshJob`, `LeaveMeshJob`, `JoinSessionJob` and `SessionPacketReader`/`Writer`; the mesh join
is Legends Arceus's. A Session message carries the peer's variable id in the packet header and no
footer, so it goes unicast. A joiner states its variable id in the join request's source location
id; the host names it 0.14 s after association.

### The Session join request

Writer `0x6d5464`..`0x6d58b0`, host parser `0x6d5aa4`. The layout is retail Legends Arceus's
(`docs/pla.md`, The Session join request; 115 bytes in `tests/test_pla_session_v11.py`), built by
`pokeldn.ldn.pia6.build_session_join`:

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

A retail joiner's one player is named a single space. The packet header carries destination variable
id 0 and the joiner's id as source; message flags `0x01` (skip the source check) on every repeat.
The host checks, in order:

1. The protocol count equals its own; otherwise nothing is sent.
2. Every version equals the host's (`0x6ed1b8`); else status 3 with the id and the host's version.
3. The destination location id is the host's constant and variable id; else dropped.
4. The source constant id and address are not the host's.
5. A known constant id draws status 1 again; a closed session status 5; a host-side listener can
   refuse with status 4.

The join response (type 2, 43 bytes, `0x6d6390`) is the Arceus layout: type, protocol id, version,
status, a big-endian u32, four random bytes, both location ids, route bytes A and B, station index,
join order, the sequence id the station update must reach. The joiner answers the type-5 update with
a 13-byte type 6 (`0x6d80a4`): type, constant id, two zero bytes, applied sequence
(`pokeldn.ldn.pia_connect`).

## The seat, and the identity flood above it

The join request above seats the station: a retail Scarlet host accepts in 16 ms, sends a 41-byte
join response (status 1, no route bytes) and a route-less station update, and streams its identity
on 0x81 port 0, once per record. A host that does not accept the joiner's acks resends every record
until the seat ends ([The flag that makes the host count an
acknowledgement](#the-flag-that-makes-the-host-count-an-acknowledgement)): about 350 records a second
on retail, up to seventy retransmits each, and 676 retransmits per record in 59 s against an emulated
Scarlet on a lossless LAN. A host may also send Session type 7 (`LeaveMeshWithHostMigrationJob`),
handing the host role to the joiner, once a second until a type 8 answers
([What decides a seat](#what-decides-a-seat)).

### The flag that makes the host count an acknowledgement

A message with flag bit 5, ZLIB (`[msg+0x29]`, `0x6efc80`), is inflated in `0x6e9984` (`0x69804c`,
zlib inflate `0x2801d0`) before the station resolve; a failure returns 0x2C03 (`0x6efd5c`). A plain
bulk ack under flags 0xA0 fails there (600 of 600 on the emulated console). Retail 0xA0 acks carry
zlib bodies: all 1,774 in three retail joiner captures inflate to 99 bytes; a 38-byte body starting
`484b62606008` reproduces with the records' 4 KB window, level-5 sync-flush framing. Under flags 0x00 the same 99 bytes take the other path: the host sent each record once
(6.3 a second, then none, against 115 to 257 a second under plain 0xA0). Both retail stations flag
bulk acks 0xA0 and send them to the LDN broadcast of their /24; `bin/sv_join.py` compresses the
body when it sets bit 5 (`--ack-flags`, `--ack-entries`, `--ack-dest-bits`, `--ack-sweep`).

### The first record on a stream carries INITIALIZED

A station's first record carries INITIALIZED with START, END and ZLIB, flags 0x1F; later records
0x17. A first record sent as 0x17 is never acknowledged (198 sends); as 0x1F it is acknowledged
within 90 ms. Built with zlib bulk acks and INITIALIZED on the first record, a joiner's identity is byte-identical to a pair joiner's in all 44
records apart from the source variable id and nonce, and emulated and retail hosts acknowledge it to
47 (mask `feffffffff01`, `field_0x50` following), send their records once, and issue a type-5
station update listing both stations with their player blocks.

## Hosting for a console

Besides four station slots in Net 0x11, a host must send:

| the host sends | what it must be |
|---|---|
| the Session join response | 41 bytes: no route bytes, station index 1, join order 1, sequence id 0, four random bytes at +8 (Arceus's 43-byte form is retransmitted against) |
| the Session type-1 join ack | nothing; a retail console sent one left within two seconds |
| the Session type-5 station list | twice: with the join response under sequence id 0, then under the next id (a retail host: 1.5 to 2 s later) |
| each station in that list | 79 bytes: location id, address and port, station index, big-endian u16 join order, NAT byte, IPv6 flag, 32-byte token, counts, player records. No route bytes (Arceus's is 81) |
| the player name in it | one space (0x20) |
| every Session reply's message flags | 0x00 |
| the ack on Reliable 0x7C | the one-entry form, no destination bitmap; unacknowledged, the console resends the channel table without end (a thousand times in ninety seconds measured) |
| every data message on Reliable 0x7C | a nine-byte header, destination_bits 0, no bitmap |
| Net 0x11 | once; a repeat is a fresh connection request at a seated station |
| Net 0x50, the update property | 0.2 s after the 0x11, every 500 ms until the station's 0x51, with the forty game advertise bytes at +0x82 |
| RTT | its own requests besides answers (a pair's host: every 410 ms) |
| the opening | join response, the first station list, channel table, both stream opens, clock answer, Net 0x50 and all 44 records right after the seat (a retail host: within 0.3 s); the key-0x80 open before the console's trade screen draws ([Opening the channel](#opening-the-channel)) |

The forty game advertise bytes change per session: zero, or a nonzero value at +0x21 (`648cf4`,
`8170f0` and `fb149700` seen), the rest zero. With `--channel 6`, `--player-name RyuPlayer` and `--host-player-id
00000000000000010000000000000000` the NetworkInfo matches a live emulated Scarlet host's apart from
the session id. With these settings the console's first join holds; a session that fails above the
seat draws repeated joins (sixteen to fifty-seven measured).

### The sender's own lowest pending is what closes the gap at 5 and 6

A station's ids 5 and 6 are never sent (44 records on the wire), and the rest go out of order (a
pair's host: 1, 2, 3, 46, 4, 7, 8, 19, 9, 15, 10, 16...). Every record declares
`lowest_pending` 1, destination bits 3, bitmap `[2]`, stream id 0. The gap is closed by the sender's
next bulk ack on the same stream, whose `lowest_pending` steps from 1 to 47; the peer then acks the
set to 47 with an empty mask. Left at 1, the peer answers `ack_id` 5, mask `feffffffff01`, all
session. Ids 1 to 44 with no gap are accepted too; no retail sender uses them.

A sender may advance `lowest_pending` only past acknowledged records. Advancing directly to 47
after the initial burst can hide a lost identity chunk: the peer acknowledges 47 while the
StreamData block remains incomplete and the station is never announced.

Both SV launchers keep a `reliable5.SendWindow` for the identity set. The corresponding bulk-ack
entry releases records below its `ack_id` and records named by its selective mask. Every 250 ms,
unacknowledged records are resent with their original sequence ids and Pia message flag `0x40`.
The outgoing data and bulk-ack headers declare the lowest record still pending, or 47 when the
set is fully acknowledged. This preserves intentional gaps 5 and 6 while retaining actual losses.

Loss of the first INITIALIZED record leaves all 44 records unacknowledged, requiring the whole
set to be retried. A missing middle record is retried on its own.

## The game's own protocol, from a pair

Measured from two emulated Scarlet 4.0.0 instances that traded, each logging every datagram it sent.
The trade runs on Reliable 0x7C; the broadcast streams carry only the identity exchange.

### Port 2: the announcement, the join and the answer

Port 2 of Reliable 0x7C (one station) and BroadcastReliable 0x80 (every station) carries the game's
session messages. The poller `0x1954978` reads `[0x475ea70]` (`0x19549e4`) and `[0x475ea7c]`
(`0x1954a54`) into the dispatcher `0x1954aec`: first byte, type 1 to 0xD, table `0x3c68988`. Three
types open a trade:

| time | station | wire | type | bytes |
|---|---|---|---|---|
| 0.00 | host | 0x80 port 2, zlib | 7 | 167 inflated: `07b901b905b906010200bc09`, nine zero bytes, `bc8080`, 128 zero bytes, `000000b90183`, the host's station id, `00` |
| 0.09 | joiner | 0x7C port 2 | 3 | `03b90200bc09` and nine zero bytes |
| 0.15 | host | 0x80 port 2 | 9 | `09b9030000b90183` and the joiner's station id |

The encoding is the channel table's (`pokeldn.ldn.channel_table`) plus tag `0xbc`, a byte string:
tag, length as an integer, bytes. The type 7 is a tuple of one tuple of five (writer `0xe464fc`):

    b9 06 ...   the type-1 body as a tuple of six: kind, capacity, a zero byte, the name as a
                nine-byte string, the data as a 128-byte string, the data length
    key         body +0x8e, the relay's counter +0x1c4 before it steps
    index       body +0x8f, the relay's counter +0x1c0 masked to seven bits, before it steps
    b9 01 ...   a tuple of one u64, the station id of the type 1's sender
    0           body +0x98

The type 9 is a tuple of the join's slot key, a result byte and a tuple of one u64.

A type 7 is a relayed type 1: the type-1 handler `0x18ceb70` unconditionally copies the 0x8e-byte
body, stamps key and index, steps both counters, appends the sender's station id and queues it for
the type-7 composer (queue `+0x200`, stride 0xa8). `0x18d5a58` sends a port-2 message to one station,
dispatching through `0x1954aec` when the target is itself, so a host relays its own type 1.

The type-1 body (`0x18ab760`):

    +0x00  kind
    +0x01  the slot's capacity: 2 for kinds 1 to 3, 4 for kinds 4 to 8 and 12, 0 for kinds 9 to 11
    +0x02  zero
    +0x03  a name of up to eight characters, NUL-terminated in nine bytes
    +0x0c  up to 128 bytes of data
    +0x8c  the data length

A trade's type 1 is kind 1, capacity 2, empty name, no data. A slot keeps the body at slot `+0xd0`
(constructor `0x18b73a0`), so its key `0x12fcabc` (slot `+0x15e`) is body `+0x8e`. Every relayed
type 1, own or a peer's, steps the key; only `0x12fbef0` zeroes the counters. A join naming key 0,
as `03b90200bc09` does, matches only the first announcement since the counters were zeroed.

The type-3 handler `0x1981e94` compares the join's first field with the slot key (`0x1981ed4`) and
queues the type 9 (`+0x270`) on acceptance, otherwise a type 0x0D, `0d b9 01` and a code, on
`+0x350`:

| code | refused because |
|---|---|
| 1 | no slot has the join's key (`0x1981ffc`), or `0x279c8fc` refuses |
| 2 | the slot is full: `0x18f80c8` against the capacity `0x1e64914` reads, or `0x279c9a0` returns 0xfd |
| 3 | the FNV-1a 64 hash of the join's name differs from the slot's (`0x1e648a0`) |
| 4 | the slot is closed (`0x1e64924`, slot `+0x160`, cleared when the slot is created) |

Type 0x0D goes to `0x1954f3c`, which requires `0xb9`, decodes a one-element tuple (`0x279c0e8`) and
calls the receiver `0x279c1ac` (`0x1954f78`):

    0x279c1b8  ldr  x8, [x0, #0xb8]     the pending request
    0x279c1bc  cbz  x8, ret             none: nothing happens
    0x279c1d0  strb w9, [x8, #0x43]     result = the code
    0x279c1d8  strb #1, [x8, #0x42]     done
    0x279c1dc  bl   0xc8e6c4            wakes the request's waiter at +0x48

It checks neither the request type `+0x40` nor the done byte, so a 0x0D from a joiner completes
whatever request the console holds with its code. The type-9 receiver `0x18b65c8` selects an object
by the slot byte, applies the message, and drops it unless the u64 is the station's own id
`[[0x46d0a08]] + 0xb8`.

A station id is the Pia constant id as a big-endian u64 (`7f00020000020000` for MAC
`02:00:7f:00:00:02`); against a retail console the type 9 carries the constant id from its Session
join request. `pokeldn.sv.port2` builds the three (pinned in `tests/test_sv.py`); `bin/sv_host.py
--announce` sends the type 7 after the seat and answers the type 3 with a type 9.

### The trade job that sends the announcement

Link Trade creates the job at `0x1e2ea54`: config `BoxTrade` (`0x3aefac8`), factory `0x1e2f3d4`,
mode 4, need 2. Two script bindings reach it: `0x1e2e9bc` (GOT
`0x46d6608`, stored by `0x1b9c8c4` into `0x4717068`, tail call) and `0x1e2ec84` (GOT `0x46d6610`,
`bl` at `0x1e2ee40`). The job (constructor `0x1e3bd10`, vtable `0x44568a8`, Update `0x1e51a04`):
result `+0x40`, state `+0xb8`, session handle `+0xc0`, mode and need as u16 at `+0xc8` and `+0xca`,
slot object `+0xd0`, request handle `+0xf8`.

| state | address | what it does |
|---|---|---|
| 1 | `0x1e51a84` | result 3 if the station count `[[0x46d0a08]]+0xe0` is below need, result 1 if `0x18ab520` rejects the mode (0, 5, above 8); else waits, no timeout, for `need` finished identity blocks (`0x1e52004` over `[[job+0xd0]+0x10] - 0x28`), then state 2 on the master (`0x1639910`: own id `+0xb8` equals master id `+0xc0`), 4 on a client |
| 2, master | `0x1e51b2c` | kind `0x18ab550(mode)` (modes 1 to 8 give 2, 3, 4, 1, 0, 5, 5, 8), then request `0x18ab658`; null ends with result 8 |
| 3, master | `0x1e51ca8` | waits on the request, no timeout; result 0 goes to state 6, else the job ends via `0x1e5086c` |
| 4, 5, client | `0x1e51b8c`, `0x1e51c74` | the same wait, 15 s limit |

| result | meaning |
|---|---|
| 1 | success, or the mode rejected |
| 2 | the session in state 3 |
| 3 | fewer stations than need |
| 4 | a client's 15 s timeout |
| 8 | no session, or the request refused |

The request `0x18ab658` builds the type-1 body and sends it through `0x18ab83c`, which returns null
while the relay's pending request `[relay+0xb8]` has done byte `+0x42` still 0 (`0x18ab860`,
`0x18ab8e8`) or the send fails. Otherwise it clears `+0xb8` (`0x18ab894`), stores a new request
(`0x18ab8a8`; `0x18abec0`: `+0x40` type, 0 for the announcement, `+0x42` done, `+0x43` result) and
sends the type 1 to the master id (`0x18d58b8`), itself on the master; a failed send clears `+0xb8`
(`0x18ab900`).

`0x18ab658` has four callers: `0x1e51b68` (BoxTrade state 2), `0x18ab34c` (the same in a sibling job,
vtable `0x4456490`), `0xa188f0` (vtable `0x4452e68`) and `0x1d99568` (vtable `0x44536d8`). Only the
four request creators write `+0xb8`; `0x18ab83c` and `0x2799b10` refuse while a request is pending:

| creator | request type | store | sole caller |
|---|---|---|---|
| `0x18ab83c` | 0, the announcement | `0x18ab8a8` | `0x18ab6bc`, in `0x18ab658` |
| `0x2799b10` | 2, a client's join | `0x2799bd8` (guard `0x2799b2c`..`0x2799b40`) | `0x1e635fc` |
| `0x2799c44` | | `0x2799cfc` | `0x1e639ec` |
| `0x2799d6c` | | `0x2799e30` | `0x1e63c88` |

The last three callers each sit in a function whose sole caller is in `0x1d98xxx` (`0x1d986d8`,
`0x1d98990`, `0x1d98c20`).

In a Link Trade, the type-2 creator is reached from BoxTrade state 4 at `0x1e51c40`, through
`0x1d986d8` and `0x1e635fc`. It runs only on the client after the master's slot is present
(`0x1d999f4`, `0x18c7a40`), retains the request at job `+0xf8`, and enters state 5. The other
callers of `0x1d98698` belong to other job classes.

The drain `0xe44cf0` walks queues `+0x1c8`, `+0x200`, `+0x238`, `+0x270`, `+0x2a8`, `+0x2e0`,
`+0x318`, `+0x350` in order; a composer returning false ends the drain for the frame, so a stuck
type 7 holds the type 9 and 0x0D behind it. The
type-7 composer `0xe45740` dispatches locally alone when the station count is 1; otherwise it asks
`BroadcastReliableProtocol::vfunc20` (`0x6e6638`) whether 0x80 port 2 can send, sends with
`0x107e060`, and dispatches locally only when both succeed. vfunc20 refuses with 0x2c27 when no
entry of the destination list `[window+0x40]` is set (`0x6efb98`), 0x4c0d when the window lacks room
for the fragments (`0x6f1ef8`), 0x10408 with no session or window. Pia fills the destination list on
the station-join event ([Who a window sends to](pia.md#who-a-window-sends-to-pia-6)).

The type-7 receiver `0x18b566c` creates and applies the slot and, for a pending type-0 request and
the console's own station id (body `+0x90`), completes it with result 0: a master stays in state 3
until its own type 7 has left on the wire. Nothing between relay and wire reads RTT or a timer.

The 0x81 identity is one block per station on the port of its index (handles `0x475ea48 + 4*index`),
moved by the stream send API `0xe22188` and receive API `0xe22458` for three objects of one layout:

| object: Update, vtable | send | receive | block |
|---|---|---|---|
| `0xe21104`, slot 13 of `0x4455ec0` | `0xe21a44`, `bl` at `0xe21dc4`, `w2 = 0xf388` at `0xe21db8` | `0xe2150c`, `0xe2170c`, `w3 = 0xf388` at `0xe21708` | 0xF388 = 62,344 |
| | `0xa62c5c`, `w2 = 0xff008` | `0xa64ddc`, `w3 = 0xff008` | 0xFF008 = 1,044,488 |
| `0x1e5f87c`, slot 13 of `0x4458698` | `0x1e617a8`, `0x1e61980`, `w2 = 0x97e08` | `0x1e61a74`, `0x1e61c0c`, `w3 = 0x97e08` | 0x97E08 = 622,088 |

Only the 0xF388 block goes on the wire in a trade, so the job's `+0xd0` object is of that class
(instance untraced; built through `0x1e34b6c` -> `0x1e35e88`).

`0x1e52004` counts slots at `+0xd0 + 0x30*k` (four) holding a peer pointer with byte `+0xd8` set. The console's own slot gets it in `0xe21154` (`memcpy(slot, [+0x90], 0xf388)` at
`0xe21248`, `+0xd8 = 1` at `0xe21258`; called from `0xa536e0`, `0xd6dc88`, `0xe21128`, `0x195160c`).
A peer's slot gets it in `0xe212b8` (called from `0xa536f0`, `0xd6dc98`, `0xe21138`) only when the
send to the peer (`+0xda`) and the receive from it (`+0xd9`) have started, the own 0x81 stream is in
state 3 (`0xe2144c`, every own chunk acknowledged) and the peer's in state 6 (`0xe21404`, every peer
chunk received); state 7 clears a flag
([Protocol 0x81](pia.md#protocol-0x81-the-stream-broadcast-reliable-transfer-pia-6)). The 0x97E08
class has the same pair, `0x1e60284` and `0x1e615e8`.

On the wire the type 7 follows the console's last record of its own set, usually within 0.11 s
(0.020 to 0.106 s in 37 of 40 announced seats; 0.545, 0.864 and 3.902 s in the others).

The relay is a 0x388-byte object (vtable `0x44e56f8`), singleton `[0x46da9c0]` = `0x4739430`,
created by `0x165a200` from `0x1659b70` only when none exists (`0x1659b18`). Its station-event
handler is `0x12fbb90`, via the thunk `0x2b71650`:

| event | effect |
|---|---|
| 0, a station joined, on the master | `0x12fbf8c` sends it the current slots unless it is the master |
| 1, own id | a pending request not done completes with result 5 (`0x501` at `+0x42`), then `0x12fbef0` |
| 1, the master's id | `0x12fbef0` |
| 1, any station, on the master | then `0x12fcebc` drops the elements it relayed |

`0x12fbef0` removes every slot through `0x12fc644` (completing a pending type-1 request whose key
matches), empties seven queues (all but `+0x1c8`) and zeroes `+0x1c0` and `+0x1c4`; it leaves the
request at `+0xb8`. A type-0 request is completed only by the type-7 receiver, the type-0x0D
receiver and the own-leave event; type 2 by the type-9 receiver `0x18b6710`, type 3 by the type-0xA
receiver `0x1945404`, type 4 by the type-0xB receiver `0x279be18`.

The own-leave path at `0x12fbc3c..0x12fbc4c` completes a client's pending type-2 request with
result 5 (`+0x40..+0x43 = 02 00 01 05`). The next creator can replace that completed request
without restarting the game, including after a disconnect before type-9 acceptance.

The relay lives until the application exits, so a request pending at `+0xb8` survives every seat,
search and menu until a completer runs. Its holder `0x4739430` (GOT `0x46da9c0`, guard `0x4739440`
via GOT `0x46da9b8`) is written only by the assignment `0x165a2b4` (from the creator, `bl` at
`0x165a230`), the reset `0x279d610` (`str xzr` at `0x279d62c`, then destructor and free), reached only
from the relay's own destroy slots `0x279d5ac` (slot 3) and `0x2b71660` (`+0x20` interface slot 1),
which have no direct callers, and the static destructor `0xa15f74` (`__cxa_atexit`). A generic
virtual call on slot 3 cannot be excluded statically. Vtable `0x44e56f8`: slot 0 `0x279a7b0`
(destructor), 1 `0x2b7164c`, 3 `0x279d5ac`, 4 `0x12fbb90`; interface `+0x20` slots `0x2b7165c`
(`ret`) and `0x2b71660`; interface `+0x28` the listener thunk `0x2b71650`. The base constructor
`0x165b0c8` (from `0x165a998`) installs a second vtable `0x44e5768` with the same destroy slots and
sets `[holder+8] = 1`.

The creator registers the `+0x20` interface with `0xf0ba9c` (`bl` at `0x165a244`) in a finalizer list
(up to 0x400 entries at `0x4763a18`, count `0x4765a18`), walked in reverse only by `0x27aff48` (slot
0) and `0x27b0054` (slot 1, then zeroes the count), both called only from `0x20e9c78`, slot 5 of
vtable `0x44e6be0`, on the path from `0x92d648` (slot 5 of `0x443ffd0`) that ends in
`nn::account::CloseUser`: the application's finalize.

### Opening the channel

| time | station | port | bytes | |
|---|---|---|---|---|
| 0.29 | host | 1 | 31, INITIALIZED | `b90104b902b9027b0001b902b902320101b902b902320201b902b902320301` |
| 1.84 | joiner | 1 | 31, INITIALIZED | the same 31 bytes |
| 2.43 | joiner | 2 | 15, INITIALIZED | `03b90200bc09000000000000000000` |
| 9.00 | host | 1 | 11 | `b90101b902b90280800001`, and the joiner sends the same back |

Port 1 is the channel table (the Arceus mechanism): a station sends on a key only once its peer has
announced it. A joiner's table is byte for byte the host's; until it arrives the host stays on its
search screen. The host's key-0x80 open must come first: a joiner whose trade screen draws before it
never sends its first game message and A on a Pokemon gives no menu. The 0x7C reliable
header is nine bytes, no bitmap, sequence and lowest pending both the message's own; an open is
flags 0x0F, a later update 0x07.

The channel must open before the trade screen draws. A later open leaves an emulated Scarlet
4.0.0 trade box without a selection cursor; the required delay depends on the peer. Against one
retail console, which opened its own key 0x80 9.15 s after the seat, a host's open at 6.0 s drew the
menu and one at 11.0 s did not.

### The trade

Port 0 carries the game: a four-byte header and a body.

| time | station | body | |
|---|---|---|---|
| 9.15 | joiner | `80000100`, two zlib fragments | the first game message |
| 9.31 | host | the same | |
| 58.2 | host | `80000200` + 348 bytes | the offered Pokemon |
| 67.6 | joiner | `80000200` + 348 bytes | |
| | either | `8000040100` | the cancel (receiver `0x1e68678`): the player backed out of the wait |
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

A host sends its first game message four times over (the two fragments, then again under the next
two ids, flags `0x1b`, `0x15`, `0x13`, `0x15`), only after the station announces key 0x80. Sent
before, nothing on port 0 is dispatched; sent as two (as a pair's host does to its clone), the
station answers `ack_id` 5, `lowest_pending` 5 (a pair's joiner: 4 and 3), the game never sees the
next message, and the console stays on "waiting for a response" (`--send-on-open`).

The `lowest_pending` field of a host's acks on 0x7C carries its own next sequence, as on 0x81. One
past the station's last sequence instead makes the station wait for that number and discard the
host's next, lower message at `0x6f03cc`
([What the receiver discards in silence](pia.md#what-the-receiver-discards-in-silence)); the
numberings diverge at the commit, where the station commits first. The `8001` steps run in pairs, 01
and 02 under a fourth byte stepping 03, 06, 0B, 0E; the trade applies over them and both screens
return to the trade menu.

Against `bin/sv_host.py` the host's trade-stream messages number 5 (offer), 6 (confirmation), 7
(commit), 8 to 15 (steps); the console's 5, 6, 7 and 8 to 11, its key-0x180 open and close its port-1
messages 3 and 4; its ack of the host's offer reads `ack_id` 6, `lowest_pending` 5. Two identical trainers can trade.

### A confirmation sent before the station's own offer

Never send the confirmation `80000300` while the offer `80000200` is still queued: a retail console
sent them in that order crashed (black screen, system error), the record itself stored unchecked. `--offer-after-open` on both launchers hangs
the offer on the peer's key-0x80 announcement, and neither queues a trade message ahead of one
already queued for the same station and port.

### Several trades in one seat

Key 0x0080 stays open; key 0x0180 opens and closes per trade. A second trade repeats the cycle with
sequences running on (host offer 16, confirmation 17, commit 18, steps 19 to 26) and no new
association, Session exchange or identity; a retail console joined to `bin/sv_host.py` traded twice
on one seat this way. `TradeStage` and `JoinerTradeStage` take a list of records, one per trade;
`--trade-offer` is repeatable.

### The first game message, and what it carries

`80 00 01 00` and 2557 bytes, in two reliable fragments, START then END (238 compressed bytes from a
pair's host, 195 from a retail console), each its own zlib stream (`484b`); the message is the two
inflations concatenated:

    b9 02          a tuple of two fields
    bc 81 f6 09    a blob, 0x9f6 = 2550 bytes
    ...            2550 bytes
    04

The blob is 850 little-endian three-byte values, mostly 1, the rest bitmasks (`0x0fffff`,
`0x0002ff`, `0x00003f`, 0), per-station: the values differ between stations (38 entries between a retail console and a pair
host; entry 36: `0x040000` against `0x0fffff`). What the index counts is unknown. A pair host's four
fragments, replayed, are accepted by a retail console.

### The record a trade message carries

The 348-byte body of a `80 00 02 00` message is the constant `bc 81 58 01` and a 344-byte Gen-9
party record (PKHeX's PK9) under the Gen 8 crypto (`pokeldn/gen8.py`): four 0x50-byte blocks from
0x08 permuted by `(EC >> 13) & 31`, an LCG `seed = seed * 0x41C64E6D + 0x6073` over the 16-bit
words, and a 16-bit checksum of the decrypted body up to 0x148. The party tail at 0x148 is outside
the permutation and checksum and re-seeds the LCG from the encryption constant.

    0x000  u32  encryption constant, in the clear
    0x004  u16  sanity, 0 on every record measured
    0x006  u16  checksum, in the clear
    0x008       four 0x50-byte blocks, encrypted and permuted        -> 0x148
    0x148       level, a pad byte and the six stats, encrypted       -> 0x158

The field map is PK9's [`PKHeX.Core/PKM/PK9.cs`]; `pokeldn/gen9.py` reads and writes it.

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

A record rebuilt from 344 zero bytes and the fields `read` reports comes out byte for byte
(`tests/test_sv_pokemon.py`). Species is the internal index, which parts from the National Dex at
917 [`PKHeX.Core/PKM/Util/Conversion/SpeciesConverter.cs:92`]. A wrong block order survives the
checksum; a record reading as a coherent Pokemon pins it. `bin/sv_host.py` prints both offers,
`--offer-out FILE` writes the console's, and `--trade-offer` takes a 344-byte record (plain or
encrypted), the 348-byte body or the 352-byte message.

### A record composed here

A record composed from zero bytes by `pokemon.build` (a shiny Imposter Ditto) trades into a retail
Scarlet save with every summary field as composed, as does one edited with `bin/sv_host.py
--offer-set` (nickname, nicknamed flag, personality value, IVs). The trade screen draws a composed
record with no legality check; the host writes the checksum. The summary's trainer id is
`(TID16 | SID16 << 16) % 1000000` (12345 and 54321 draw as 993401, 8131 and 64817 as 855043); the
characteristic line comes from the encryption constant and the IVs.

The level follows the experience: byte 0x148 at 100 with zero experience arrives as level 1,
1,000,000 experience as level 100. The six growth curves (`PKHeX.Core/PKM/Util/Experience.cs`) need
1,000,000, 600,000, 1,640,000, 1,059,860, 800,000 and 1,250,000 at level 100. The species table
`personal_sv` (0x50 bytes per species and form, `PersonalInfo9SV.cs`) holds base stats at 0x00,
gender ratio 0x0C, growth curve 0x0F, three abilities 0x12 (species 132: curve 0, abilities 7, 7,
150). The receiving game recomputes the party stats:

    HP    = (2 * base + IV + EV/4) * level / 100 + level + 10
    other = ((2 * base + IV + EV/4) * level / 100 + 5) * nature

A Ditto with perfect IVs, no EVs, neutral nature shows 12 and 6 x5 at level 1, 237 and 132 x5 at
level 100, from zero stat fields; HP 99/99 sent at level 1 arrives as 12.

### What a joiner sends, in order

A pair's joiner before the game's first message, times from one capture:

| time | message |
|---|---|
| 0.04 | the Session join request |
| 0.17 | Net 0x12, echoing the sequence of the host's 0x11 |
| 0.38 | Net 0x51, echoing the sequence of the host's 0x50 |
| 1.63 | the Session type 6, acknowledging the station update |
| 1.68 | the eleven bulk acknowledgements and the stream opens on 0x81 ports 0 and 4 |
| 1.68 | the channel table on 0x7C port 1 |
| 1.82 | Clone Clock 0x77, eighteen zero bytes; the host answers 1, sixteen bytes, a trailing byte |
| 2.03 | its own 44 records on 0x81 port 1 |
| 2.43 | the open on 0x7C port 2 |

Unanswered, a console repeats Net 0x11 and 0x50; the 0x12 and the 0x51 stop them (212 Net messages
in a seat without, 2 with).

### The joiner's side of the trade

A pair joiner's whole 0x7C script, with each message's sequence on its port:

| port | sequence | message |
|---|---|---|
| 1 | 1 | the channel table, the host's four keys, INITIALIZED |
| 2 | 1 | the type-3 join, `03b90200bc09` and nine zero bytes |
| 0 | 1 to 4 | the first game message, twice over |
| 1 | 2 | `b90101b902b90280800001`, key 0x80 open, after the fourth fragment |
| 0 | 5 | the offered Pokemon |
| 0 | 6 | the confirmation |
| 0 | 7 | the commit, sent first |
| 1 | 3 | `b90101b902b90280800101`, key 0x0180 open, after the host's own |
| 0 | 8 to 11 | an echo of each step's `8001 01 SS` (03, 06, 0B, 0E); nothing for `8001 02 SS` |
| 1 | 4 | `b90101b902b90280800100`, the close |

The identity goes 0.15 s after the host's key-0x80 open, the joiner's own open 0.21 s after that.

The `lowest_pending` rules bind the joiner too: its own next sequence on 0x7C, one past its highest
record id on its 0x81 bulk ack. A number from the host's numbering walks the host's receive base
past the joiner's later messages, which are discarded at `0x6f03cc`.

`pokeldn.sv.trade.JoinerTradeStage` is this side as a state machine, run by `bin/sv_join.py
--trade-offer` (`--send-on-open` for the identity fragments gated on the key-0x80 open).
`tests/test_sv.py` drives it with the host's half of the pair's messages and pins the joiner's half.

### What a trade rewrites, measured on a record that came back

A composed record traded onto a console and offered back differs in 27 bytes, seven fields:

| field | as sent | as it came back |
|---|---|---|
| `current_handler` | 0 | 1 |
| `ht_name` | empty | the console player's name |
| `ht_language` | 0 | the receiving console's language (3, French) |
| `ht_friendship` | 0 | 50 |
| `nickname` | empty | the species name in the console's language |
| `current_hp` | 0 | the computed maximum HP (237, a level-100 Ditto) |
| `stats` | zero | the six the game computes |

Everything else is kept as sent. An empty name comes back as the species name, as in the Sword
Mystery Gift record (`docs/swsh_gift.md`).

### Joining a searching console: a trade, and what decides the seat

`bin/sv_join.py` trades with a retail Scarlet hosting from its Link Trade search, numbering as a
pair joiner. It takes the station update as the seat, answers the console's announcement with the
type-3 join, sends the four identity messages after the console opens key 0x80, and applies the
`lowest_pending` rules above.

#### What decides a seat

With the joiner's whole opening delivered, a retail console hosting from its search either hands
the host role to the joiner or runs the game. Handing it over, it sends Session type 7 naming the
joiner (`LeaveMeshWithHostMigrationJob`), then only NetStartHostMigration `01400000`, about twice a
second; taking the host role needs the new host to create an LDN network. The handover has been
measured anywhere from 22 ms after the accept to about eight seconds after the seat, and after a
completed trade (three seats measured); what decides it is unresolved. Running the game, the
console sends, in order:

| | |
|---|---|
| the seat | a type-5 station update naming the joiner's variable id and the player id its request stated, then the 41-byte join response |
| its opening | the bulk acknowledgements on all eleven streams, an 11-byte record on 0x81 port 1 and another on port 5 |
| its identity | 46 records on 0x81 port 0, and it acknowledges the joiner's 44 to 47 |
| its channel table | on 0x7C port 1, keys `0x007b`, `0x0132`, `0x0232`, `0x0332` |
| `0db90101` | on 0x7C port 2, code 1, only in answer to a type-3 join sent before the announcement |
| the announcement | on 0x80 port 2, zlib, 167 bytes inflated: a type 7 with kind 1, capacity 2 and the console's station id |

A joiner answers the announcement with the type-3 join (`--port2-now` sends it with the channel
table instead). A retail console seated a joiner with the station update alone, before any join
response; a joiner that waits for the join response sends nothing all session.

## Unresolved

- Whether an unannounced seat whose identity set reached acknowledgement 47 lost an outgoing chunk
  on the air. A sender that advanced its own `lowest_pending` to 47 before the acknowledgement hides
  it: a bulk ack does not show StreamData completion. Dropping one outgoing chunk reproduces the
  symptom in the emulator.
- What makes a console hosting from its search hand the host role to its joiner on one seat and run
  the game on another. A player id above the host's own drew no type 7 on one seat; a lower one drew
  it 22 to 28 ms after the accept on two, and another seat with a lower id did not migrate.
- Whether a console hosting from its search runs a second trade in the same seat. After each trade
  measured in the joiner direction it handed the host role over and the joiner left
  (`--leave-on-migration`); a console joined to `bin/sv_host.py` traded twice in one seat.
- What answering the console's type 7 with a type 8 (`bin/sv_join.py --answer-migration`) leads to;
  no seat that migrated has been answered.
- Whether the game checks a joiner's Link Code when it hosts under one: a retail console hosting
  under a code accepted a joiner advertising none.
- Why a console joined to `bin/sv_host.py` can acknowledge the host's announcement and never send its
  port-2 join (one board run of two).
- Whether a master-only leave event, without the client's own leave event, can hold a type-2
  request across the client's 15 s timeout. The master-only branch drains the relay's queues
  through `0x12fbef0` while preserving `+0xb8`.

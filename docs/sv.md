---
title: Scarlet and Violet
nav_order: 9
has_children: false
---

# Scarlet and Violet

Pokemon Scarlet (`0100a3d008c5c000`) and Violet (`01008f6008c5e000`) are native Switch titles with
Pia statically linked into `main`. The wireless layer and the mesh below the game are read, and the
mesh join the host waits for is read out of the binary; the game's own records are readable but
not yet spoken to.

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
on ports 4 and 5. `pokeldn.sv.streams` builds all of it and `tests/test_sv.py` pins every message
to the bytes a retail station sent.

### The Pia message flags

The flags byte of the message header is not the establishing flag the Arceus host uses. Both retail
stations send:

| message | flags |
|---|---|
| RTT, stream opens, records | 0x00 |
| the bulk acknowledgements | 0xA0 |
| the host's Net 0x11 and 0x50 | 0x31 |
| NetStartHostMigration | 0x11 |

The message destination field is zero on every message either station sends.

### RTT

Eleven bytes: a kind byte, an eight-byte clock and a two-byte target. A request is kind 0 with
target 0; the answer is kind 1 with the same clock and the target set to the requester's variable
id. A retail station answers within 20 ms.

### The records

A record is one reliable message with the ZLIB flag, and its payload is a zlib stream with a 4 KB
window, so it begins `484b`. Every record measured decompresses to 1395 bytes and opens the same
way:

    +0x00  1   kind: 1 the station's identity, 2 a body record
    +0x01  1   zero
    +0x02  1   an index that rises by two per record within a station's burst
    +0x03  6   zero
    +0x09  2   0x0568, the 1384 bytes that follow

A kind-1 record carries the player the game shows as the partner:

    +0x0b  5   unread
    +0x13  26  the player name, UTF-16 little-endian, NUL-padded
    +0x2d  22  the account identifier, ASCII, `u-` and twenty characters
    +0x53  1   5

The kind-2 records are high-entropy for their whole length and carry no readable string. A station
sends one kind-1 record and then a run of kind-2 records in the same tenth of a second: the host
fifteen and the joiner seven in the session measured. `pokeldn.sv.streams.decompress` reads them and
`scratchpad/pia6_air_decode.py` writes each one out.

### What a passive capture misses

Both consoles pack several MSDUs into one frame. Read as a single MSDU, the payload begins six
bytes of destination and six of source before the SNAP header, so the IP header lands at the wrong
offset and the addresses read as fragments of a MAC. Unpacking the A-MSDU subframes multiplied the
readable traffic of one capture from 313 Pia packets to 3667. Any decoder pointed at these two
consoles has to do it; `scratchpad/pia6_air_decode.py` does.

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

A bulk acknowledgement under message flags 0xA0 never reaches the host's window. Its receive
function resolves the sending station, checks the length and compares a byte of the message
against the station's own before applying anything, but a message whose flags carry bit 5 branches
earlier into a second deserialiser and is dropped there with result 0x2C03. Measured on the
emulated console: 600 of 600 acknowledgements under 0xA0, every one dropped at that instruction,
the station resolve never reached.

Under message flags 0x00 the same acknowledgement, the same 99 bytes with the same four entries
and destination bitmap, takes the other path and the exchange completes. The host answered a
sweep's fifth shape by sending each of its 44 records exactly once and stopping: 115 to 257
records a second under 0xA0 in the four shapes before it, 6.3 a second during it, and none at all
in the 26 seconds after, while its periodic bulk acks continued. That is what a retail host does
with a retail joiner.

Both retail stations flag their own bulk acknowledgements 0xA0 and address them to the LDN
broadcast of their own /24. What separates that from a joiner's 0xA0 being dropped is unmeasured.
`bin/sv_join.py --ack-flags`, `--ack-entries`, `--ack-dest-bits` and `--ack-sweep` are the handles.

### The first record on a stream carries INITIALIZED

A station's own records go on 0x81 port 1 for a joiner and port 0 for a host, each station opening
the two ports it receives on: the joiner opens 0 and 4, the host opens 1 and 5. The first record a
station sends on its stream carries INITIALIZED with the usual START, END and ZLIB, flags 0x1F, and
every record after it 0x17. A first record sent as 0x17 is never acknowledged: the host's bulk ack
for that station holds at 1 for as long as the record is repeated, 198 sends in one seat. Sent as
0x1F the same record is acknowledged within 90 ms.

With both fixes an emulated host completes the whole exchange in both directions: it sends its 44
records once each, acknowledges the joiner's, and issues a type-5 station update listing both
stations with their player blocks. It then keeps searching. What a pair does after the exchange is
what the trade needs, and it is unicast, so only two consoles or two emulator instances can show it.

## The game's own protocol, from a pair

Two emulated Scarlet 4.0.0 instances completed a trade, and each instance's log holds every
datagram it sent, unicast included. The two logs are keyed on the session id from the host's
NetworkInfo at +0x10; each instance's clock starts at its own launch, so they are aligned on a
datagram both recorded (`scratchpad/sv_pair_timeline.py`).

The trade runs on Reliable 0x7C, not on the broadcast streams. Those carry the identity exchange
and nothing else.

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

The `8001` messages run in pairs, a 01 and a 02 under the same fourth byte, which steps 03, 06, 0B,
0E. The trade applies over those four steps and both screens return to the trade menu.

Both instances ran from one save copied twice, and the game traded a Pokemon between two identical
trainers without complaint.

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

## Unresolved

What the two record kinds hold. The 238-byte zlib message under `80000100` and the 348 bytes under
`80000200` are the identity and the offered Pokemon; neither field map is read. A Gen-9 box
structure is 344 bytes, four short of that body.

What makes the host open the game. An emulated console answers every layer above, Net, the clock,
the session, the streams, the identity in both directions and the channel table, and still does not
open the game's channel: it announces nothing on 0x80 port 2, where a pair's host announces its
handler keys in two messages, and never sends the port-1 table update that precedes the first game
message. Instead it answers the joiner's port-2 open with a four-byte open of its own,
`0db90101`, which a pair's host never sends. Its screen stays on the search. Replaying a real
joiner's whole 44-record identity in place of the host's mirrored back changes none of it
(`scratchpad/sv_extract_records.py` pulls a set out of a station's log).

A retail console answers all of it exactly as the emulated one does, byte for byte. In a 179-second
seat it sent 16 records, 19 sends in all and never more than two of any one, against 350 a second
with up to seventy retransmits each before the acknowledgement flag was corrected. It answers the
clone clock, sends its channel table, and opens its own 0x7C port 2 with the same `0db90101`. The
emulated console is a faithful stand-in for this game at every layer measured so far, including
where it stops: the retail screen stays on "Searching for a trade partner" through the seat, as the
emulated one does.

Why a retail station's own 0xA0 acknowledgements are accepted between two consoles, when one sent
here is dropped in the deserialiser, is unknown. The retail pair broadcasts them and this project
unicasts them over the LAN.

A host built here is also joined by a searching console, which then never opens its Pia socket: it
answers the host's first Net 0x11 with ICMP port 12345 unreachable and leaves about five seconds
later. That was measured before the join-request layout was known and before `bin/sv_host.py` could
answer one.

Both consoles are Switch 2 and their unicast is 802.11ax, which neither the project's adapter nor a
MacBook's Broadcom sniffer demodulates. Of a 74-second session the pair sent 388 and 387 readable
data frames and 9 and 2 unicast ones, so anything sent to one station alone is invisible.

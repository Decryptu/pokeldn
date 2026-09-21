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
lowest_pending 1. Sequence ids 5 and 6 are never sent at all, so the hole is in the host's own
window rather than in the path.

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

## Unresolved

The trade above the identity exchange. The exchange itself completes against an emulated console
under message flags 0x00; what the host does next, and whether it opens the game's own channel on
0x7c once the joiner's identity is in, is the next measurement. The same flags on a retail console
is untested: every retail seat so far sent 0xA0.

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

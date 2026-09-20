---
title: Scarlet and Violet
nav_order: 9
has_children: false
---

# Scarlet and Violet

Pokemon Scarlet (`0100a3d008c5c000`) and Violet (`01008f6008c5e000`) are native Switch titles with
Pia statically linked into `main`. The wireless layer and the mesh below the game are read; the
game's own records are readable but not yet spoken to.

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

A retail pair, read from the moment the second console associated, runs four protocols and no
others: Net `0x2C`, RTT `0x58`, BroadcastReliable `0x80` and StreamBroadcastReliable `0x81`. There
is no Session protocol `0x98` in any capture, no Clone protocol and no Reliable `0x7C`. Every
datagram goes to the link-local broadcast address of the session's own `/24`, never to the peer's
address, and each carries the recipient's variable id in the plaintext footer.

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
`SessionPacketReader`/`Writer`. So the mesh join a joiner runs exists in Scarlet exactly as it does
in Legends Arceus, and the reason no capture shows it is that it is addressed to one station: a
Session message carries the peer's variable id in the packet header and no footer, so it goes out
unicast, and the two consoles' unicast is 802.11ax. Everything a passive capture does show, Net,
RTT and the eleven streams, is mesh-addressed and therefore broadcast.

This also dates the host's assignment of the joiner's variable id: it names the id 0.14 s after the
association, which is after a unicast join would have arrived and long before the joiner's first
broadcast at 0.89 s.

## Unresolved

A host built here is joined by a searching console, which then never opens its Pia socket: it
answers the host's first Net 0x11 with ICMP port 12345 unreachable, and leaves about five seconds
later. Matching a retail beacon field for field does not change it, including the station platform
byte and the player count in the Pia block.

Joining the network the console puts up reaches its Pia: it sends Net 0x11 and repeats it, and about
eight seconds later announces host migration. It sends nothing on RTT or on any of the eleven
streams, so it never treats the station as seated. The host's own acknowledgements name the joiner's
variable id 0.14 s after the association, and the joiner then adopts that id as its own: the host
assigns it. Everything the joiner sent before it was assigned one is in the capture and is three
gratuitous ARPs and an IPv6 multicast listener report, so the host assigns the id from the LDN
participant list alone, with no Pia input. Against a station this project brings, the host stops
after its Net 0x11, repeats it, and about eight seconds later announces host migration: it never
creates the station. Seven things have been matched to a retail station without changing it: the
advertisement field for field, the station platform byte, the Pia block's player count, the eleven
acknowledgements and the two stream opens, the LDN broadcast address, the message flags each kind
of message carries, and a Nintendo MAC on the adapter. What the host is waiting for is a Session
message it never receives, and the layout Legends Arceus uses for that message draws no answer.

Both consoles are Switch 2 and their unicast is 802.11ax, which neither the project's adapter nor a
MacBook's Broadcom sniffer demodulates. Of a 74-second session the pair sent 388 and 387 readable
data frames and 9 and 2 unicast ones, so anything sent to one station alone is invisible.

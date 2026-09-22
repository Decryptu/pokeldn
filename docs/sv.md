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

This is what a retail console did against a host of this project's over the radio in sv05 and sv06,
where it associated, sat about five seconds, left, and answered Net 0x11 with ICMP port 12345
unreachable.

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
one tuple of five: a tuple of six (1, 2, 0, the nine-byte string, the 128-byte string, 0), 0, 0, a
tuple of one u64, and 0. The type 9 is a tuple of three: the slot byte the join named, a result
byte, and a tuple of one u64.

A type 7 is a relayed type 1. The type-1 handler `0x18ceb70` copies the 0x8e-byte body, steps two
counters on the receiver (`+0x1c4`, and `+0x1c0` masked to seven bits), appends the sender's
station id and queues the element for the type-7 composer (queue `+0x200`, stride 0xa8). A
station sends a port-2 message to one station through `0x18d5a58`; when the target is its own
station id it dispatches the message to itself through `0x1954aec` instead of the wire, which is
how a host announcing alone relays its own type 1.

The type-3 handler `0x1981e94` queues the type 9 (`+0x270`) when the join is accepted and an
element carrying a code 1 to 4 (`+0x350`) when it is not. The type-9 receiver `0x18b65c8` selects
an object by the slot byte, applies the message, and compares the u64 with the station's own id
at `[[0x46d0a08]] + 0xb8`; any other id is dropped.

A station id is the Pia constant id read as a big-endian u64. The 127.0.0.2 instance of the pair
carries `7f00020000020000`, which is `ldn_constant_id` of the MAC `02:00:7f:00:00:02`, and both
of its messages above carry that value because both stations of that pair were that instance's
clones. Against a retail console the type 9 must carry the console's own constant id, the one in
the source location id of its Session join request. `pokeldn.sv.port2` builds all three from the
ids, `bin/sv_host.py --announce` sends the type 7 after the seat and answers the console's type 3
with a type 9 carrying its id; `tests/test_sv.py` pins the three messages to the pair's bytes.

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
Pia message does, and the same wall closed the joiner direction on Legends Arceus (`docs/pla.md`).

The other seats run the game. In order, what the console sends:

| | |
|---|---|
| the seat | a type-5 station update naming the joiner's variable id and the player id its request stated, then the 41-byte join response |
| its opening | the bulk acknowledgements on all eleven streams, an 11-byte record on 0x81 port 1 and another on port 5 |
| its identity | 46 records on 0x81 port 0, the same shape a host here sends, and it acknowledges the joiner's own 44 to 47 |
| its channel table | on 0x7C port 1, the four keys `0x007b`, `0x0132`, `0x0232` and `0x0332` |
| `0db90101` | on 0x7C port 2 |
| the announcement | on 0x80 port 2, zlib, 167 bytes inflated: a type 7 carrying slot 1, kind 2, state 0 and the console's own station id, which is its constant id read big-endian |

The announcement is the message no emulated instance ever composed and the one the host direction
waits on a station to answer. A joiner answers it with the type-3 join on 0x7C port 2, as a pair's
joiner does 0.09 s after its host's own type 7 (`bin/sv_join.py`, `--port2-now` for the join sent
with the channel table instead).

The station update seats a joiner on its own: it carries the joiner's variable id before any join
response does, and a joiner that waits for the response sends nothing for the whole session.

## Unresolved

**A trade is complete on a retail Scarlet (2026-09-22).** The console joins a network
`bin/sv_host.py` puts up, takes the host's identity as four messages, draws the host's offer with
its four-item menu, offers its own 348-byte record, confirms, commits, opens key 0x0180, runs the
four exchange steps in both directions and closes the key, and the Pokemon the host composed is on
the console. Its acknowledgement of the host's offer reads `ack_id` 6 and `lowest_pending` 5, the
numbers a console answers a console with, where the seat before the correction read 6 and 6.

The host's messages on the trade stream number 5 for the offer, 6 for the confirmation, 7 for the
commit and 8 to 15 for the exchange steps, the console's 5, 6, 7 and 8 to 11, and the console's own
key-0x180 open and close are its port-1 messages 3 and 4.

An emulated Scarlet trades end to end against a host built here: it draws the host's offer, offers
in answer, confirms, commits, opens key 0x0180, runs the four exchange steps and keeps the Pokemon
the host sent. Both corrections, four identity messages and the host's own next sequence in the `lowest_pending`
field of its 0x7C acknowledgements, carry to retail unchanged.

The paragraphs below record what was measured before that, on the emulator. Every layer a live
emulated Scarlet host puts on the wire is now matched: the NetworkInfo byte for byte apart from the
session id, Net 0x11 and 0x50, both station lists, the join response, RTT in both directions, the
clone clock, the channel table, the two stream opens, the two announcements on 0x80 port 2, the
whole 44-record identity with its gap accepted, and the port-1 channel update, each in the order and
at the times a live host sends them. The station answers all of it, acknowledges the identity to 47
with an empty mask and opens Reliable 0x7C port 2, and does not open the game's channel.

The transport is not what stops it. With the receive function at `0x6efc2c` instrumented, the
port-1 channel update from a host here walks exactly the path the same update from a real host walks
in the same guest: the flag load, the length check, the station resolve, the byte gate, the window
write and the flag at `0x6f0040`, message for message and site for site. What differs is above Pia,
in the game's own trade flow, which reaches the step that opens the channel against a real host and
not against this one. The seat lasts 23 seconds against this host where it lasted 19 before the
identity was accepted.

What the two record kinds hold. The message under `80000100` is a tuple of an 850-entry mask array
and a byte, read in "The first game message, and what it carries"; what the array indexes is
unknown. The 348 bytes under `80000200` are four constant bytes and a Gen-9 party
record, read field by field in "The record a trade message carries".

What makes the host open the game. An emulated console answers every layer above, Net, the clock,
the session, the streams, the identity in both directions and the channel table, and still does not
open the game's channel: it announces nothing on 0x80 port 2, where a pair's host announces its
handler keys in two messages, and never sends the port-1 table update that precedes the first game
message. Instead it answers the joiner's port-2 open with a four-byte open of its own,
`0db90101`, which a pair's host never sends. Its screen stays on the search. Replaying a real
joiner's whole 44-record identity in place of the host's mirrored back changes none of it
(`scratchpad/sv_extract_records.py` pulls a set out of a station's log).

The send the console withholds has one path in the binary, and it is the game's rather than Pia's.
`0xe45e9c` is the only code that sends on 0x80 port 2: it loads the port-2 handle from `0x475ea7c`,
resolves the protocol and calls `0x107e060`. Seven composers call it, each writing one message type
byte, 6 through 0x0C, and the announcement a pair's host sends at 2.33 s is the type its composer
`0xe45740` writes. They run from one drain, `0xe44cf0`, which walks eight queues on the singleton at
`0x46d6ca0` and composes whatever each holds. So the console withholding the announcement means the
game never put it in that queue. What fills it is the type-1 handler, a relay (Port 2 above):
a station that announces nothing never relayed a type 1, its own or a peer's.

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

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

The per-protocol version numbers in a join request's protocol list are unread. The console states
its own when it sends a join request, which is what hosting gets first.

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

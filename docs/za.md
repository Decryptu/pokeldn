---
title: Legends Z-A
nav_order: 10
has_children: false
---

# Legends Z-A

Pokemon Legends: Z-A (title id `0100f43008c44000`) is a native Switch title with Pia statically
linked into `main`. Its packet header is version 16, the header this project already writes for the
GBA application, so the transport below the game is the one `pokeldn.ldn.crypto` speaks.

## The dump

Three files on the share: the base application (`v0`, 4.3 GB), the update
(`0100f43008c44800`, `v393216`, 2.1 GB) and the Mega Dimension DLC (`0100f43008c45002`).

The update's Program NCA is `4a70b3ff963bfe412681185cea68bf55` at container offset `0x2085d0`,
section key `b9de1a0334576634f8fdafdd703f7f9a`, with the exeFS in section 0 and a BKTR RomFS in
section 1. The exeFS holds four files and no `subsdk0`:

| file | size |
|---|---|
| `main` | 33,970,422 |
| `main.npdm` | 1,700 |
| `rtld` | 8,550 |
| `sdk` | 6,247,676 |

Decompressed, `main` lays out as text `0..0x3163f70`, rodata from `0x3164000`, data from
`0x3bc2000`. Addresses below are offsets into that image.

The Control NCA is `3e7ba1cd223145fa4f299a8f4cafd4cb` at container offset `0xbd0`, section key
`a8cb59338ce785237048d52452eb6adf`, RomFS data at NCA `+0x14c00` with section counter
`0000000000000005`. Its `control.nacp` gives display version 2.0.2 and eight local communication
ids at `+0x30b0`, all `0100f43008c44000`. Scarlet and Violet list two ids and Z-A lists one.

## The wireless layer

| value | |
|---|---|
| LDN passphrase | `BM7cXkadR9ugiXdHiurkiyhrQwcR3rMgCM5BF47dranKXWAGpGEA9z3ncXRnPjCX` |
| Pia game key | `p3bwdaSsywFXUkDu` |

The passphrase is at rodata `0x33391fc` and again at data `0x3eeda1f`; the game key is at data
`0x3eeda0e`, immediately before that second copy. Neither string matches Sword's, Arceus's or
Scarlet's, and both are the rows the [NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Game-Keys)
publishes for this title.

## The packet header

Header version 16, which the wiki's table puts in the Pia 6.39 to 7.2 band. The layout is
`pokeldn.ldn.crypto.PiaHeader`: 29 bytes, magic `32AB9864`, the version byte carrying `0x80` when
the packet is encrypted, a padding-and-flags byte, two-byte destination and source variable ids, a
two-byte packet id, a footer size, an eight-byte nonce and eight bytes of the AES-GCM tag.

    0x24fadbc   the header initializer: stores the magic at object +0x08 and 0x10 at +0x0c,
                memsets the nonce at +0x15 for 8 bytes and the tag field at +0x1d for 16
    0x24faefc   the validator: magic, `(version & 0x7f) == 0x10`, and `(length - 0x1d) >> 6`
                below 0x71
    0x24fb1e0   the receive path, which branches on bit 7 of the version byte
    0x24fb4b0   the send path, which writes 0x10 back to +0x0c when it seals nothing
    0x24fb46c   the padding-size setter: it ORs its argument into bits 4..7 of object +0x0d,
                which is the wire's padding-and-flags byte at 0x05

The object keeps its fields eight bytes above their wire offsets for the nonce and the tag, the
same relation Legends Arceus's version-11 header has in `pokeldn.ldn.pia6`.

## The advertisement

A console on the local search screen hosts a network of its own and advertises 112 bytes: the
0x5C Pia system property block and 20 game bytes. Measured on two sessions with different link
codes, everything below held.

| field | value |
|---|---|
| local communication id | `0100f43008c44000` |
| LDN protocol | 1 |
| advertisement version | 4 |
| scene id | 1 |
| application version | 6 |
| security mode | 1 |
| accept policy | ALL |
| participants | 1/2 |
| system communication version | 22 |
| application communication version | 6 |
| player name | one byte, a space, UTF-8 |

The SSID and the channel are per session; the console put both sessions on channel 6.

The game's twenty bytes are the link code in ASCII, NUL-padded to sixteen, then its length as a
little-endian `u32`. That is Legends Arceus's layout, and so is the password field: the code
NUL-padded to sixteen bytes, XORed into the first block of AES-128-GCM under the game key with a
four-byte IV read out of the key itself (`docs/pla.md`, The link code in the advertisement). With
Z-A's own game key that derivation gives

    1068a742ac3a8787ab6066a161f5d5e1

which is the mask both sessions used. `pokeldn.za.build_advertise_data(code)` reproduces each
advertisement byte for byte from the code alone, and `tests/test_za.py` pins both.

## The seat

A console searching for a partner accepts a station into the network it hosts, and speaks Pia to it
from the first moment. Seated at 0.02 s it sent its first datagram, 109 bytes, and its packets
authenticate under `AES_ECB(game_key, ssid)` with the network id as `CRC32(ssid[1:16])`: 32 of 32
datagrams decrypted, which settles the band's session key derivation for this title.

What it sends unprompted, from its own variable id to destination 0:

| | |
|---|---|
| protocol 1 | Net, the only protocol it uses before it is answered |
| `01 11 ...`, 118 bytes | the connection status, sequence ids 2 and 3, twice a second |
| `01 40 00 00` | start host migration, once the connection status goes unanswered |

The connection status is the layout `pokeldn.ldn.pia_connect.parse_net_conn_request` reads: four
station slots, two filled, both on port 12345, the host at `169.254.x.1` and the joiner at
`169.254.x.2`. The console gave up after 14.4 s and sent nothing further, though it left the
station seated for the whole 90 s hold.

## A reference pair

Two emulated instances reach the trade's selection screen over LDN, and a capture of both ends of
one session carries 768 packets with full payloads. What it settles about the opening:

- the host transmits first, 109 bytes, 48 ms after the joiner's association; the joiner answers
  47 ms later with 45 bytes and follows with 125;
- the header nonce is a per-station counter. Each station starts from a random 64-bit base and
  increments by one on every packet it sends;
- the joiner's first packet carries source variable id 0, destination 0, packet id 0 and no
  footer, and is uncompressed; its second carries its own source id and is zstd-compressed;
- the host names the joiner's variable id from that second packet: its next packet is addressed to
  it and carries the two-byte recipient footer.

A host that says nothing after admitting a station is answered with about eight seconds of silence
and then a clean disconnection, which is the same timer a retail console runs.

## The session, on a retail console

A station that sends the Session join a reference joiner sends is admitted. The console answers in
30 ms and the session runs:

| from the seat | what the console sends |
|---|---|
| 0.02 s | Net connection status, 118 bytes |
| 0.05 s | Session join response, type 2, 37 bytes, addressed to the joiner's own variable id |
| 0.06 s | Reliable, protocol 10, 106 bytes, and two Broadcast Reliable messages on protocol 11 |
| 0.08 s | Net update property, type 0x50, 150 bytes |
| from 0.5 s | RTT requests, about three a second |
| 1.12 s, repeating | Session update session, type 5, 185 bytes |

What the join owes, over the Net acknowledgement: ten protocols
(`1:0 3:5 5:1 6:0 9:1 10:3 11:4 12:4 13:7 15:0`), application communication version 6, an
identification token of `0x06` and zeroes, and a PlayerInfo name of one space. A join declaring
the GBA application's six protocols and version 0x58 is dropped without an answer, and the console
then waits about 8.7 s and hands the host role away.

The session held 27 s with the game's own messages unanswered, after which the console re-sent its
connection status and moved to host migration, and its screen reported that no partner was found.

## The game's own exchange

Above Pia the game runs on Reliable (protocol 10) and Broadcast Reliable (protocol 11), in the
sub-header `pokeldn.ldn.reliable` already parses: flags, size, sequence, window base, recipient
count. A complete trade between two stations is twenty distinct application payloads, each
re-sent until acknowledged. In order of first appearance, with the two-byte message id they open
with:

| id | bytes | what it carries |
|---|---|---|
| `1400` | 106 | the station's identity, with the player name in UTF-16 |
| `1403` | 9 | a short follow-up to the identity |
| `0100` | 1211 | the record the selection screen is drawn from |
| `0101` | 354 | the offer: a nine-byte header, a 344-byte Pokemon record, one trailing byte |
| `0102` | 5 | a step message |
| `0104` | 5 | a step message |
| `0200` | 5 | the confirmation steps, whose last byte counts: 3, 6, 0x0b, 0x0e |

Both stations send the same set; the host's and the joiner's differ only in the station id inside.

### What a joiner owes on those streams

Measured against a reference pair and confirmed by an emulated host's acknowledgements:

- protocol 10 is addressed to the host's variable id, protocol 11 to the mesh id 0x0001, and both
  carry the host's variable id in the two-byte recipient footer;
- every game packet is zstd-compressed;
- a pure acknowledgement carries no sequence of its own: it rides the stream's base, 0xfff0. One
  that advances is read as data with a hole behind it;
- an acknowledgement on protocol 11 is 74 bytes: the sending station's four bytes, a stream byte, a
  count of four, then four entries of a next-expected halfword and a sixteen-byte mask, the last
  entry cut short. Entry 1 is the joiner's stream;
- the identity goes out under the INIT flag, the selection record about half a second later and
  then about four times a second under a fresh sequence, the same 1211 bytes each time;
- every frame on protocol 11 carries three in the sub-header's recipient count, where protocol 10
  carries zero;
- a pure acknowledgement rides message flags 0x40 on both protocols, where application data
  carries no message flags at all.

With all of that, a station's packets are the reference joiner's in size, flags, addressing,
sequence and framing, and an emulated host acknowledges every one: its bulk acknowledgement
advances past the identity and each selection record, and its broadcast acknowledgement counts the
joiner's frames in entry 1. It answers with its own identity on both protocols and does not send
its selection record, so something it reads outside these packets still decides whether a station
becomes a trade partner.

A station's LDN NodeInfo publishes a local communication version at +0x2E of the 0x40-byte
structure. Both stations of a reference pair publish 6 there, the title's application version. A
station that publishes 6 is admitted exactly as one that publishes 0 is, and the host's game
behaves the same either way, so the field is not what gates a trade partner.

A host that has not made a trade partner of its station kicks it. From about 18 to 25 s its RTT
stops and it repeats a Session type 13 twice a second: the type, its own constant id big-endian,
and a one. A reference session carries no type 13 at all.

The message is composed at `0x2551320` of main 2.0.2, inside the function at `0x25512b4`: it
writes 0x0d, then the eight-byte constant id from its station object, declares a length of ten and
a one, and hands the buffer to the Session protocol's sender. Its only two callers, `0x255bad4`
and `0x255bd70`, are both inside `nn::pia::session::KickoutManageJob`, whose `vfunc6` is at
`0x255bda0`. So type 13 is a kick request and the trailing byte is its reason.

The kick is a liveness timeout. The path, read off main 2.0.2 and confirmed with breakpoints on an
emulated host: `0x2547700` walks the stations in state 2 and asks for reason 1 on any whose
last-heard time at +0xb8 is older than the session's timeout, through `0x2547dd0`, which records
the station and reason in a map at session+0x1048. `0x2548b60` drains that map into
`0x255b4a0`, which takes a slot in `KickoutManageJob`'s 24-entry table and sends the first type 13;
the job's update at `0x255bc10` resends it every 501 ms while the station stays present. Last-heard
is refreshed by `0x2567280` for every station whose bit (its byte at +0x30) is set in a mask that
`0x2566740` builds from the received-data map, keyed by the packet header's source id.

So a station is heard only through packets whose header source is its own variable id. The session
address 0x0001 is a destination: the host broadcasts RTT and session traffic to it, and a joiner
that sends from 0x0001 is heard by no one. With every packet sourced from its own id, the station
stays seated for the whole 45 s hold and no type 13 is sent.

On protocol 11 the reliable sub-header's length counts the payload after the four-byte station
prefix, so every frame carries four bytes more than it declares: the opening is `00000001` and
message `1402 b900`, the identity is the prefix and the whole 106-byte protocol-10 identity, the
nine-byte message is `1403b9018269fb308f`, and an acknowledgement is the prefix and four complete
18-byte station entries. A frame cut at its declared length is dropped by the host, which then
resends its own opening about ten times a second; a frame whose last four bytes are wrong is
acknowledged but leaves the host's game on its search screen.

Pia packet ids run on two counters: one for every packet addressed to the host, whatever the
destination field (0 or the host's variable id), and one for the session address 0x0001. The host
drops a packet whose id is below the highest it has seen from that sender, so a joiner that keeps
a separate counter for destination 0 has every Net 0x51 dropped until that counter catches up. The
host then repeats its Net 0x50 for about ten seconds and its Session update sequence 1 comes late.

With both right, a host that accepts the Session update sequence 1 at about 1.2 s sends its own
1211-byte selection record at 1.25 s and moves to its trade box screen.

The trade on protocol 10, as a joiner runs it against a host: each side sends one 354-byte `0101`
about 2.5 s after the selection records, a preview that no player chose, marked 1. A player's
pick is the `0101` marked 0 (see Hosting). The joiner answers the host's pick with its own and
confirms with `0102b90100`; the host confirms with the same, then both send `0104b90100` and the
joiner sends four `0200b901XX` steps, 03 and 06 at once and 0b and 0e about 14 s later, while the
host sends `0000000202` on protocol 11. `bin/za_join.py --trade-offer` runs that side.

A record edited and re-encrypted with `pokeldn.za.pokemon.build_offer` is taken as sent. The
reference Noibat with the nickname "PKLDN" at 0x58 and Scarlet's nicknamed bit (0x8F bit 7) set
was drawn on the host's trade screen as PKLDN, traded, and kept that name, its shininess and its
level 44 through the host's save. Scarlet's nicknamed bit and its individual values at 0x8C read
correctly on Z-A records.

The species at 0x08 is national. The same record with 95 written there traded as a shiny level-44
Onix named PKLDN; the host's summary showed 98 HP, 58 Attack, 159 Defense, 45 Special Attack,
58 Special Defense and 80 Speed, which is Onix's spread, so the receiving game recomputes the stats
from the species. The moves were kept as sent (Hurricane, Screech, Super Fang, Air Slash, from
Scarlet's move offsets), and so were the nature (Quirky), the ball and the empty held item. The
summary screen shows no ability.

The moves at Scarlet's offsets (0x72, four little-endian halfwords) are taken as sent: the Onix
given 446, 328, 103 and 784 arrived with Stealth Rock, Sand Tomb, Screech and Breaking Swipe. The
reference Onix a player offered carries that set.

The level comes from the experience at 0x10. The Onix with experience 1,000,000 and the party
level byte left at 44 was drawn at level 100 on the trade screen and stored at level 100. Its
original 85,184 is 44 cubed, the medium-fast curve.

A record composed from 344 zero bytes by `pokeldn.sv.pokemon.build`, with nothing copied from a
console's record, trades and is kept. Composed as a shiny female Glaceon, experience 125,000,
nickname and trainer name PKLDN, trainer id 12345 and secret id 54321, Timid, version 52,
language 3, met location 202 on 2025-10-16, ball 4, scale 128 and moves 247, 573, 423 and 58, with
the stats and current HP left at zero. The host's summary showed PKLDN, shiny, female, level 50,
Shadow Ball, Freeze-Dry, Ice Fang and Ice Beam, Timid, origin France, trainer id 993401 (the
six-digit form of 54321 << 16 | 12345), first met 10/16/2025 in Wild Zone 18, size class M, and
140 HP, 72 Attack, 130 Defense, 150 Special Attack, 115 Special Defense and 93 Speed: the game
computes the stats and the current HP itself. Met location 202 is Wild Zone 18.

The Net layer is answered in full as well: the host's connection status 0x11 with a 0x12, and its
update property 0x50 with a 0x51, both of which a reference joiner sends.

The Session layer owes one more thing. A type-5 update session is answered with fifteen bytes: the
type, the answering station's LDN constant id, the update's sequence as a big-endian u32 and
0x0001. The GBA application's answer names its raw MAC and carries no sequence, and a Z-A host
answers that by repeating its update every two seconds indefinitely.

## The offered Pokemon

The offer's record is the generation 8 and 9 entity: four 0x50-byte blocks shuffled by the
encryption constant, 0x148 bytes stored and 0x158 with the party tail, the checksum over the
stored body. `pokeldn.sv.pokemon.decrypt` validates it unchanged and
`pokeldn.sv.pokemon.read` reads its fields: the sample offer is a shiny Noibat at level 44 with
perfect individual values, ball 22, ability 151 and moves 542, 103, 403 and 162.

The layout is Scarlet's, measured on nine records out of three reference sessions and on the
trades below:

| offset | field |
|---|---|
| 0x008 | species, national: 714 Noibat, 716 Xerneas, 95 Onix |
| 0x010 | experience; the game derives the level from it |
| 0x058 | nickname, UTF-16LE, thirteen code units |
| 0x072 | four moves |
| 0x0a8 | the handler's name, "Player" only on a record whose current handler is set |
| 0x0f8 | the original trainer's name, "XS" on all nine |
| 0x148 | level, in the party tail |

Every record reads version 52, language 10, met locations 200 to 212, met dates in October 2025,
trainer id 5071 and secret id 14217. The size scalars and the Tera types read zero.

## A trade with a retail console

A retail Legends Z-A on its Link Trade search, code 00000000, traded with `bin/za_join.py` and kept
a Pokemon composed from zero bytes: the shiny Glaceon PKLDN of the section above,
`scratchpad/za_offer_glaceon_built.bin`. Nothing changed from the emulated run. The console's
selection record came 1.16 s after the seat, the previews at 3.74 s, the player's offer at 55 s,
the console's `0102` at 88 s and `0104` at 89.6 s, and the joiner's four `0200` steps at 89.7 s and
104 s. After the trade the console returns to its trade menu on the same seat and offers again.

Most associations are refused with LDN status 1: 59 and 35 refusals before the two seats that
formed, on one MAC. A seat that forms late in the console's host phase is handed over rather than
run: the console's first datagram comes 1.4 s after the association instead of within 0.1 s, it
sends no Session update sequence 1, and it repeats Session type 9 once a second (start host
migration in the wiki's numbering; Z-A's kick request is 13 where the wiki lists 12, so the
numbering is unconfirmed) until it restarts its Net at 6.5 s. Scarlet's search screen runs the same race.

## Hosting

A searching console also scans, and joins a network that carries the title's advertisement and its
link code. `bin/za_host.py` hosts one; `pokeldn.za.host` is the host's side, read off an emulated
pair's trade and pinned byte for byte against it.

| from the seat | what the host sends |
|---|---|
| 0 s, every 0.46 s until answered | Net connection status 0x11: sequence 2, four slots, host and joiner on 12345 |
| on the Session join | join response (type 2, 37 bytes) to the joiner's id, update session (type 5, sequence 0) to 0x0001 |
| with it | the identity on protocol 10 under INIT; the identity and `1403b9018269fb308f` bundled on protocol 11, prefix `00000002` |
| with it | Net update property 0x50, repeated every 0.5 s until 0x51 |
| from 0.2 s | RTT requests to 0x0001 about three a second, and a response to each of the joiner's |
| 1.15 s after update 0 is acknowledged | update session sequence 1 |
| once update 1 is acknowledged | the 1211-byte selection record twice, 60 ms apart |
| 2.7 s later | the preview `0101` |

Four details differ from the GBA application's host:

- the host's station entry in the update session carries the identification token `0x06`, as the
  joiner's does;
- the update's sequence is written twice, at +1 and at +21;
- the property update carries `02` in the byte after the scene id, where the GBA application
  writes `01`;
- a broadcast acknowledgement from the host reports the joiner's stream in entry 1 and the idle
  base 0xfff0 in the other three.

The trade: the joiner's pick is its second `0101`. The host answers with its own, then `0102b90100`
after the joiner's `0102` and `0104b90100` 1.5 s later; each of the joiner's four `0200b901XX`
steps is answered on protocol 11 with `0201b901XX` under the host's prefix.

An offer's last byte marks what it is: 1 on the preview a station sends unasked, 0 on a player's
pick. A pick sent with 1 is acknowledged and drawn as nothing, and the partner waits on
"Communicating" with an empty slot. With 0 the partner shows the record, asks to confirm and
completes the trade.

A retail Legends Z-A on its Link Trade search, code 00000000, joined `bin/za_host.py` over the ESP32
board 0.6 s after the host came up, traded a Klefki for a composed shiny Glaceon and kept it. The
console sends a preview `0101`, marked 1, each time its cursor moves on the trade box: five before
its pick in that session. Its pick is the one marked 0, so a host keys on that byte and not on a
count. An emulated Legends Z-A trades with the same host over ldn_mitm.

## Mystery Gift

Mystery Gift in version 2.0.2 offers three entries: Get via Internet, Get with Code/Password and
Check Mystery Gifts. It has no local-wireless path, so a gift cannot be served over LDN.

## Unresolved

- What the property update's `02` byte means.
- The Net 0x51 handler at `0x2504150` matches the packet's source address against its stations'
  addresses; which of its earlier checks drops a packet whose id is below the sender's highest is
  inferred from one breakpoint hit and the id counts, not traced.
- The ability: Scarlet's ability field reads plausible values on Z-A records, and the summary screen
  shows none.

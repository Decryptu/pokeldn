---
title: Legends Z-A
nav_order: 10
has_children: false
---

# Legends Z-A

Pokemon Legends: Z-A (title id `0100f43008c44000`) is a native Switch title with Pia statically
linked into `main`. Its packet header is version 16, the header `pokeldn.ldn.crypto` already writes
for the GBA application, so the transport below the game is the one that module speaks.

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

### The trade commands

The trade session setup `0xca2928` subscribes five command types, named by their ctti strings, on
the session's command channel (session+0xc8). The two-byte id is `0x100 | index`, the type's
position in the channel's list at +0x60 (`0x96129c`, a `strcmp` walk), in subscription order. Each
payload is a `b9` struct whose first member is a u16 round.

| id | command | handler | payload as the handler reads it | what the handler does |
|---|---|---|---|---|
| `0100` | CommandReady | `0x2dc4c7c` | round, 1200 bytes | copies the 1200 bytes to session+0x604, sets session+0xf0 |
| `0101` | CommandSelectPokemon | `0xb2a44c` | round, 344-byte record, one byte | loads the record (The offered Pokemon); bit 0 of the byte clear makes it a pick |
| `0102` | CommandConfirmTrade | `0xc8dda0` | round | ignored when session+0x152 is above the round; else partner state +0x134 = 4 |
| `0103` | CommandCancelTrade | `0x2dc51ac` | round, u32 reason | +0xab4 = reason with 1 and 2 swapped, else 0; +0x152 = round; +0x150 += 1; then `0x2dc41f8` |
| `0104` | CommandFinalAgreement | `0x2dc52b4` | round | ignored when +0x152 is above the round or own state +0x130 is not 4 or 5; else partner state 5 |

The cancel sender `0x964a60` sends nothing while own state +0x130 is 2 or 5. Otherwise it sends
round +0x150 + 1, then sets +0x130 = 2, advances +0x150 and +0x152, and drops the partner's state
from 3..5 back to 2 (3 when the reason is 0). A ConfirmTrade or FinalAgreement still carrying the
round before a cancel is ignored after it; one carrying a round above +0x152 is accepted, since the
handlers reject only a round strictly below it. SelectPokemon reads no round.

The session object is 0xab8 bytes, allocated by `0xca2658` (its one caller `0xca20f4` stores it at
owner+0x130) and built by `0xca2704`: vtable `0x3e3a6e8`, then `0xca2794` copies a configuration
into +0x40 (a u16, 0x201, whose low byte `0xca28c8` passes to `0xca2928` as the channel argument)
and two 0x40-byte callables into +0x48 and +0x88, and a memset zeroes +0x150..+0xab7. Both rounds
therefore start at 0, and a session's first `0102` and `0104` are `b90100`. `0x964568`, which runs
only when own state +0x130 is 6 and whose one caller is `0x9601dc` in the live trade path
`0x95f8f4`, clears the own offer (+0x120) and the partner's PokemonParam (+0x128), sets both states
+0x130 and +0x134 to 2 (calling `0x964fa0(obj+0x128)` first when +0x134 was 3 or more), clears
+0x118, +0x11a and +0xd0, and zeroes +0x150 and +0x152 with one 32-bit store. A console that
completes a trade starts the next one on the same seat at round 0, and an answer that stays at
round 1 after it is still accepted. A retail Z-A that cancelled once in its first trade confirms the
second on the same seat with `0102b90100`; `pokeldn.za.host` resets its round to 0 with each trade.

Own state 5 is written by the session update `0x95f600` (`0x95f680`) when own state is 3 or 4, byte
+0x148 is set, the timer at +0x138 reads at least 1.5 s, the partner state is 4 or 5 and `0x963710` is
true. Own state 6 is written by `0xdfda8c` (`0xdfda9c`, `0xdfdaa0`), the only immediate store of 6 to
+0x130 in the text: a delegate invoke, referenced only from `0x964e78` (`0x964ea0`), which fills a
0x40-byte delegate with it (managers `0x2dc4b78`, `0x2dc4b7c`, `0x2dc4b88`). Own state 7 is written by
`0x2dc4b94`, installed by `0x964f0c` (the only reference, `0x964f20`); the one other immediate store of
7 to +0x130, `0xf721b8` in `0xf72138`, is on an object nothing ties to the trade session. `0x9610a4`
(one caller, `0x95fdbc`) runs when own state is 5 or more and the worker at +0xd0 is absent or its
byte +9 is 0 or 0x10. It calls the callable at session+0x48 with (+0x118, +0x120, +0x128), builds the
exchange worker (`0x966af0`, 0xb0 bytes) into +0xd0 and hands it both delegates (`0x9649e0` at
`0x96116c`, `0x964a20` at `0x96117c`), which `0x9655a4` stores at worker+0x20 (state 6, `0x965f54`)
and +0x60 (state 7, `0x4177c8`). `0xc8ad1c`, the one function referenced by the `adr` at `0xca2578`,
builds the trade object (`0xc8ad94`, constructor `0xc8ae70`, vtable `0x3d8a0d0`: +0x68 `0xdd07cc`,
+0x78 `0x2a67168`, +0x80 `0xcbc68c`); that it is the callable at session+0x48 was not traced to the
store.

The worker's start `0x965660` stores the host test `0x9157d0` at +0x14, clears +0x15, stores
`0x34f2b0(rng, 0x12c) + 2` at +0x18 (a draw of 0..300, so 2..302), zeroes +0xc and +0x10 and sets +9
to 1. Its update `0x960c20` (one caller, `0x95f750`) switches on +9 through the table `0x33a360d`.
`0x962ac0(peer, step)` stores `0x100 | step` at peer+0x48 and sends it; a wait compares the partner's
step at +0x70, valid when +0x71 is set.

| +9 | handler | what it does | next |
|---|---|---|---|
| 1 | `0x960d20` | trade object vfunc +0x68; result 1: +0x15 = (+0x14 != 0), result 0: +0x15 = 1 (`0x960e50`, `0x960e90`), else +0x15 = 0; send step 3 | 2 |
| 2 | `0x960cc0` | wait for the partner's 3 | 3 |
| 3 | `0x960d64` | trade object vfunc +0x78; false: state 4, send step 6 | 5 |
| 5 | `0x960ce0` | wait for the partner's 6 | 6 |
| 6 | `0x960da0` | `0x9628e8`: trade object +0x40 = 1, then vfunc +0x80 (`0xcbc68c`, the handler update in What the trade writes into a received record) | 7 |
| 7 | `0x960c84` | wait for trade object +0x40 == 3; +0x15 set: send 0xb | 8, else 9 |
| 9 | `0x960c40` | count +0x18 down once per update, then send 0xb | 10 |
| 8, 10 | `0x960ca0` | wait for the partner's 0xb | 11 |
| 11 | `0x960db0` | trade object +0x40 = 4 (`0x961098`) | 12 |
| 12 | `0x960dc0` | wait for trade object +0x40 == 5 (`0x9626e4`), send 0xe | 13 |
| 13 | `0x960d00` | wait for the partner's 0xe | 14 |
| 14 | `0x960de8` | +0x10 == 0: the state-6 delegate (`0x963810`); else the state-7 delegate (`0x9a0b00`); then `0x9637b8` | 0x10 |

Own state 6 is the exchange completed with no error at worker+0x10, after both stations have passed
steps 3, 6, 0x0b and 0x0e, the `0200b901XX` steps below. A station whose +0x15 is clear waits the
random 2..302 updates before its 0x0b. What `0xdd07cc` returns and how the stored halfword maps onto the `b901XX` bytes were not traced.

An emulated Z-A choosing Cancel on the trade prompt sends `0103b9020100`, round 1 and reason 0, and
redraws the prompt with the host's earlier offer once its player picks again; the host need not
resend it. Its next confirmation is `0102b90101` and `0104b90101`. A host that answers under round 0
is ignored and the console waits on "Communicating" with no timeout; one answering under round 1
completes the trade. `pokeldn.za.host` takes the round from the console's own `0102`, `0103` and
`0104`.

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
the station and reason in a map at session+0x1048. The timeout is 10 s:

    0x2547700   called from SessionProtocol vfunc 10 (0x2547170); returns at once when +0x1b0 is 0
                and runs only while the local station's byte +0x48 is 2; kicks when
                now > last_heard + ticks_per_ms * (s32)[+0x1b0]
    0x24f5f08   ticks per millisecond: GetSystemTickFrequency() / 1000, computed once
    0x25504c8   writes +0x1b0 on the object at session+0x18, and the same value at +0x338 of the
                object 0x24f11f0 returns
    0x253d9d4   in the session start 0x253d4f0: passes max([setting+0x28c], 4000) to 0x25504c8,
                and [setting+0x290] to 0x257d12c just before
    0x199eb48   the game's setting constructors store (+0x28c, +0x290) = (10000, 1000) as one
                u64; the same at 0x199edf0, 0x199f07c, 0x199f2f8, 0x19a0494, 0x19a0a4c

A station whose own variable id sources no packet for more than 10 s is kicked, whatever screen its
player is on. The scan also kicks with reason 1 a station whose byte in the one-shot table
`[0x3ee51d8][station id]` is set (`0x255c990` reads and clears it). `0x2548b60` drains that map into
`0x255b4a0`, which takes a slot in `KickoutManageJob`'s 24-entry table and sends the first type 13;
the job's update at `0x255bc10` resends it every 501 ms while the station stays present. Last-heard
is refreshed by `0x2567280` for every station whose bit (its byte at +0x30) is set in a mask that
`0x2566740` builds from the received-data map, keyed by the packet header's source id.

The object at session+0x18 is the session's `SessionProtocol`, so the kick scan and `0x25504c8` act
on one object. The Session's initialisation `0x253c880` (one caller, `0x253c66c`; it loads the
`nn::pia::session::Session` vtable through GOT `0x3ee5400`) calls `0x253f284(framework+0xc8, 0,
0xfd)` at `0x253cacc`, which allocates 0xd8e8 bytes, constructs them with `0x25450ec` (vtable
`0x3c8db18`, `nn::pia::session::SessionProtocol`, through GOT `0x3ee5428`), makes a handle of
protocol type 0xd and registers the object. The session keeps the handle at +0x12/+0x14
(`0x253cae0`), looks it up with `0x256b4b0` and stores the result at +0x18 (`0x253cb8c`); its other
stores to +0x18 (`0x253c8c8`, `0x253d084`) write zero. The same function stores framework+0xb8 at
session+0x30 (`0x253caf8`, `0x253cb00`). The session start passes the timeout on with `0x253d9cc
ldr x0,[x20,#0x18]; bl 0x25504c8`.

The setting's +0x290 is a send-silence limit in milliseconds. `0x253d9b8` passes it to `0x257d12c`,
which takes the object at framework+0xf8 and calls `0x256a238` on its member at +0x750: a negative
value fails with 0x10407, 0 becomes 1000, and the value is stored at member+8 and at +0x28c of the
object `0x24f11f0` returns. What stores framework+0xf8 was not traced; the +0x750 member belongs to
the `PacketWriter` methods, and the only derived `PacketWriter` is `SessionPacketWriter` (vtable
`0x3c8da30`, installed by `0x2543e08`), whose vfunc 7 `0x2544004` is `b 0x25688d0`. That vfunc 7
calls `0x256a2d0` with the send's station mask and the current time (`0x2568924`). For each station
in state 2 other than the local one, with id at most 0x17 and byte +0xa0 clear (`0x25770d8`), it
stamps station+0xb0 with the time when the station is in the mask, and otherwise sets the station's
bit in an output mask when +0xb0 is older than the limit, which includes a station never sent to
(+0xb0 = 0). It records the largest gap in ms at `[0x24f3560()]+0x98`. When the output mask is not
empty (`0x2568928`), vfunc 7 builds an extra packet (`0x256da8c`, `0x256a89c`) and sends it to those
stations through vfunc +0x68. The game's settings store (+0x28c, +0x290) = (10000, 1000) as one u64
(`0x199eb58`, `0x199ee04`, `0x199f08c`), as does Pia's default (`0x251a4c8`). The code's rule is
therefore that a seated station whose byte +0xa0 is clear is sent a packet whenever nothing has gone
to it for more than a second. No capture has been checked against that rule.

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

Pia packet ids run on two counters per sender: one for the session address 0x0001 and one for
every other destination (0 and the host's variable id share it). The check runs before any protocol
sees the packet, in `nn::pia::session::SessionPacketReader::vfunc11` at `0x2566920`: a packet from
an unknown source address or from no station is accepted; otherwise the destination selects a
controller, station+0x78 for 0x0001 and station+0x50 for the rest, and `0x2576ad0` checks the
packet id (wire 0x0a) and the big-endian nonce (wire 0x0d) against it:

    id == 0                                         accept, nothing recorded
    last id == 0                                    last id = id - 1
    last nonce == 0 and nonce != 0                  last nonce = nonce - 1
    (s16)(id - last id) < 1                         reject
    nonce != 0 and (s64)(nonce - last nonce) < 1    reject
    otherwise                                       last id = id, last nonce = nonce if non-zero

A rejected packet goes to `0x25655d8` and is dropped. An id equal to the last accepted one is
dropped, and the 16-bit wrap makes an id 0x8000 or more ahead count as behind. A joiner that keeps a
separate counter for destination 0 has every Net 0x51 dropped until that counter passes the
host-id counter. The host then repeats its Net 0x50 for about ten seconds and its Session update
sequence 1 comes late. The Net 0x51 handler itself (`0x2504100`) reads no packet header field: it
deserializes the message (`0x250f930`), checks its length and the type byte 0x51 (`0x2504150`),
matches the source address against its stations (`0x250c60c`, `0x24fba00`) and passes the station
and the acknowledged sequence id at message +4 to `0x250daa8`.

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

The species at 0x08 is national below 917 and, from 917, the generation 9 internal index Scarlet
uses (`pokeldn.sv.pokemon.internal_index` and `national` convert). The same record with 95 written there traded as a shiny level-44
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

Measured on nine records out of three reference sessions, every record reads version 52, language
10, met locations 200 to 212, met dates in October 2025, trainer id 5071 and secret id 14217; the
species include 714 Noibat, 716 Xerneas and 95 Onix. The handler's name reads "Player" only on a
record whose current handler is set, and the original trainer's name reads "XS" on all nine. The
height and weight scalars read zero.

### The record in memory

In main 2.0.2 a record sits behind an accessor object, which every field accessor takes in `x0`:

| offset | what |
|---|---|
| +0x08 | pointer to the 0x10-byte party tail, null for a stored record |
| +0x10 | pointer to the 0x148-byte core |
| +0x18 | 1 while the core is encrypted |
| +0x19 | fast mode: 1 keeps the core decrypted between accessor calls |
| +0x1c | an `nn::os::LightEventType`, signalled on release when a waiter is counted |
| +0x1e | spin-lock owner byte, 0x5f when free |
| +0x1f | waiter count |

    0xe5d810             16-bit word sum over the 0x140 bytes at core+8; the checksum at core+6
    0xe5d8c0, 0xe5d940   the crypt: seed = seed * 0x41c64e6d + 0x6073, XOR with seed >> 16, seeded
                         by the encryption constant at core+0 over core+8..+0x147, then re-seeded
                         with it over the party tail
    0x3303ab0            block order, 32 rows of four bytes indexed by (EC >> 13) & 31, byte k for
                         block k; rows 0..23 are PKHeX's BlockPosition order, rows 24..31 repeat
                         rows 0..7; blocks are 0x50 bytes

The table has 141 code references, all inside `0xe48000..0xe5d000`, the accessor range. An accessor
locks, decrypts when +0x18 is set, recomputes the checksum and ORs 4 into the halfword at core+4 on a
mismatch. Bit 2 of core+4 is the Bad Egg bit: a getter that finds it set reads the field from a
default record at `0x3f7eda0` in .bss (block A at `0x3f7eda8`) instead of the core; 23 getters of
block A carry that branch, the species getter `0xe49940` among them (`tbnz w9,#2,0xe49a98`). The
default record's one initializer, `0xe5cdb4` (one caller, `0xe629b4`), zeroes the 0x10 bytes at
`0x3f7ed98` and the four blocks at `0x3f7eda8`, `0x3f7edf8`, `0x3f7ee48` and `0x3f7ee98`, then writes 1
to the halfword at `0x3f7ed98`+2, `[0x3f0784()+0x378]` to the language (record 0xd5) and 4 to the ball
(record 0x124). Unless fast mode is on, the accessor then rewrites the checksum and re-encrypts. `0xe485f0` tests bit 2 without decrypting;
core+4 lies outside the encrypted range. The serializers `0xe47a20` (0x158 bytes) and `0xe47c60`
(0x148) write the encrypted, shuffled form.

### The fields main 2.0.2 reads and writes

Offsets in the decrypted, unshuffled record, with each field's getter and setter. A name the code
does not show is PKHeX's (`PKM/PA9.cs`).

| offset | size | getter | setter | field |
|---|---|---|---|---|
| 0x00 | 4 | every accessor | `0xe514d0` | encryption constant |
| 0x04 | 2 | `0xe485f0` | `0xe51698` | flags; bit 2 Bad Egg |
| 0x06 | 2 | load path | `0xe48250` | checksum |
| 0x08 | 2 | `0xe49940` | `0xe52aa0` | species: national below 917, generation 9 internal index from 917 |
| 0x0a | 2 | `0xe49b40` | `0xe52cc0` | held item |
| 0x0c | 4 | `0xe49d50` | `0xe52ee0` | trainer id and secret id as one u32 |
| 0x10 | 4 | `0xe49f60` | `0xe53100` | experience; level = `0xe5ce70(species, form, exp)` |
| 0x14 | 2 | `0xe4a3c0` | `0xe535b0` | ability |
| 0x16 | 2 | `0xe4d7c0` bit 1, `0xe4d9d0` bit 2 | `0xe56ad0..0xe57130` | ability slot: bit 2 hidden, bit 1 second |
| 0x18 | 2 | `0xe4a5d0` | `0xe537d0` | markings |
| 0x1c | 4 | `0xe4dbe0` | `0xe57350` | PID |
| 0x20 | 1 | `0xe4d3a0` | `0xe56690` | nature |
| 0x21 | 1 | `0xe4d5b0` | `0xe568b0` | stat nature, the one the stat routine reads |
| 0x22 | 1 | `0xe4cd70` bit 0, `0xe4cf80` bits 1-2 | `0xe56030`, `0xe56250` | fateful encounter, gender |
| 0x23 | 1 | `0xe5bcf0` | `0xe5bf00` | IsAlpha in PKHeX (below) |
| 0x24 | 2 | `0xe4d190` | `0xe56470` | form |
| 0x26..0x2b | 6 | `0xe4aa30..0xe4b480` | `0xe53c10..0xe546b0` | EVs |
| 0x48, 0x49 | 2 | none | `0xe5a7e0`, `0xe5aa00` | height and weight scalars, written only |
| 0x4a | 1 | `0xe512c0` | `0xe5ac20` | scale |
| 0x4b | 1 | `0xe5c120` | `0xe5c330` | level bonus, LevelBoost in PKHeX (below) |
| 0x58..0x71 | 26 | `0xe4ddf0` | `0xe57570` | nickname, 13 UTF-16 units |
| 0x72..0x79 | 8 | `0xe4b690(i)` | `0xe548d0(i)` | four moves |
| 0x7a..0x7d | 4 | `0xe4b8b0(i)` | `0xe54b10(i)` | PP |
| 0x7e..0x81 | 4 | `0xe4bad0(i)` | `0xe54d50(i)` | PP ups |
| 0x8a | 2 | `0xe48820` | `0xe51ec0` | current HP |
| 0x8c | 4 | `0xe4bcf0..0xe4cb60` | `0xe54f90..0xe55e10` | six 5-bit IVs from bit 0, egg bit 30, nicknamed bit 31 |
| 0x90 | 4 | `0xe48600` | `0xe516c0` | status condition |
| 0x94..0x9f | 12 | `0xe5cb00(i)` | `0xe5c550(i)` | per-move flags 264..359 |
| 0xa8..0xc1 | 26 | `0xe50840`, `0xe50a70` | `0xe5a190` | handler's name |
| 0xc2 | 1 | `0xe50ca0` | `0xe5a3a0` | handler's gender |
| 0xc3 | 1 | `0xe50eb0` | `0xe5a5c0` | handler's language |
| 0xc4 | 1 | `0xe4f780`, as `!= 0` | `0xe58a70` | current handler |
| 0xc6 | 2 | `0xe4f990` | none | handler's id ("unused?" in PKHeX) |
| 0xc8 | 1 | `0xe4fdb0` | `0xe58eb0` | handler's friendship; `0xe4a170` returns it when 0xc4 is 1, else 0x112 |
| 0xc9..0xcd | 5 | none | `0xe59910`, `0xe59b30`, `0xe59f70`, `0xe59d50` (u16 at 0xcc) | handler's memory, written only |
| 0xce | 1 | `0xe4e2a0` | `0xe57780` | version |
| 0xd0 | 4 | `0xe5b280` | `0xe5b060` | form argument |
| 0xd4 | 1 | none | `0xe5ae40` | affixed ribbon, written only |
| 0xd5 | 1 | `0xe4a7e0` | `0xe539f0` | language |
| 0xd6..0xf6 | 33 | `0xe5cb00(i)` | `0xe5c550(i)` | per-move flags 0..263 |
| 0xf8..0x111 | 26 | `0xe4e4b0` | `0xe579a0` | original trainer's name |
| 0x112 | 1 | `0xe4fba0` | `0xe58c90` | original trainer's friendship |
| 0x113..0x118 | 6 | `0xe590d0`, `0xe592e0`, `0xe594f0`, `0xe59700` | `0xe4ffc0`, `0xe501e0`, `0xe50400`, `0xe50620` | original trainer's memory: 0x113, 0x114, u16 at 0x116, 0x118 |
| 0x11c..0x11e | 3 | `0xe4e910`, `0xe4eb20`, `0xe4ed30` | `0xe57bb0..0xe57ff0` | met date |
| 0x11f | 1 | `0xe5bae0` | `0xe5b8c0` | obedience level |
| 0x122 | 2 | `0xe4ef40` | `0xe58210` | met location |
| 0x124 | 1 | `0xe4f150` | `0xe58430` | ball |
| 0x125 | 1 | `0xe4f360` bits 0-6, `0xe4f570` bit 7 | `0xe58650`, `0xe58860` | met level, original trainer's gender |
| 0x126 | 1 | `0xe5b6b0` | `0xe5b490` | hyper training bits |
| 0x148 | 1 | `0xe49760` | `0xe518f0` | level, party tail |
| 0x14a..0x155 | 12 | `0xe48a40` and five more | `0xe51ae0..0xe528b0` | max HP and the five stats |
| 0x156 | 2 | `0xe48c20` | `0xe51cd0` | signed max-HP offset |

No function in the accessor range touches these bytes:

    0x1a..0x1b  0x2c..0x47  0x4c..0x57  0x82..0x89  0xa0..0xa7  0xc5  0xcf  0xf7
    0x115  0x119..0x11b  0x120..0x121  0x127..0x147

In Scarlet's layout, which PA9.cs keeps, they hold the contest stats, Pokerus, ribbons and marks
(0x2c..0x47), the relearn moves (0x82), the battle version (0xcf), the egg date and location, the
HOME tracker (0x127) and the TM record (0x12f). PA9.cs maps 0x4b..0x57 as a DLC TM record in code
while its comment calls 0x4c..0x57 unused; main reads 0x4b only as the level bonus and never reads
0x4c..0x57. All of these bytes are zero on every console-made record read.

Byte 0x4b is added to the level for the stats: the stat level is `level + [0x4b]`, capped at 200
(`0x10f558`). The halfword at 0x156, which PA9.cs does not map, is a signed max-HP offset:
`0xe4163c` uses `max(1, maxhp + (s16)[0x156])`, and the load path never writes it, so a composed
value persists. Both are zero on every console-made record.

Byte 0x23 reaches the model descriptor built at `0x106a48` as `[0x23] != 0` (`0x106ba0`), at +0x13,
next to egg-or-bad at +0x12 and the scale mapped to `(scale / 255) * 2 - 1`. Its only setter is
called from `0xe3f140`. It is 1 on exactly the two console-made records whose scale is 255, a
Roserade (407) and a Glaceon (471), and 0 on the others.

The per-move flag array is PA9.cs's plus move record: 360 bits, bit k in 0xd6 + k/8 for k below
264 and in 0x94 + (k - 264)/8 above. A move's index is its position in the 340 u16 move ids at
rodata `0x3303fb0`, found by the linear search `0xe669e0`, which returns -1 for a move not in the
list; every caller then skips the flag. `0x631834` sets a flag, `0x673448` clears one, `0xe438e4`
clears the array, `0xe43068` reads one. Scarlet's Tera types at 0x94/0x95 do not exist in this
layout: those bytes are flags 264..279. An Onix with moves 446, 328, 103 and 784 flags 33 38 88 91
103 106 157 174 225 231 328 444 446 457 784. Every move traded so far (58, 103, 162, 247, 328, 403,
423, 446, 542, 573, 784) is in the list.

The flag unlocks a move that the learnset's level rule does not. `0xe343a0(species, form, move)` reads field 25 of the
personal entry (vtable +0x36, through `0xe3cb88` and `0xe36850`), a vector of four-byte entries
{u16 move, u8 level, u8 unlock level}, and returns the unlock level of the matching move, or 0. The
learn level is 1..100, 253 or 254. In the 2.0.2 table the unlock level is 10 for all 4,803 level-1
entries, the learn level plus 3 for 14,717 entries at levels 3..100 (nine exceptions: 99 gives 100
six times and 102 once, 33 gives 37 twice), 10 on 266 of 274 level-254 entries of present species
(19, 20 or 22 on the rest) and 10 on only 48 of 192 level-253 entries (39, 15, 12, 33, 38 and others
on the rest). The PokemonParam wrapper with vtable `0x3e28e58` (321 slots, each a thunk to the
PokemonParam at +0x50) uses it three ways:

| slot | function | what it does |
|---|---|---|
| 135 | `0x6a30b0` | lists the moves whose unlock level is non-zero and equal to its level argument |
| 145 | `0x631834` | sets a move's flag, skipping a move `0xe669e0` does not find |
| 150 | `0x699308` | true when the unlock level is non-zero and the level (`0xe49760`, or `0xe5ce70` from the experience on a stored record) is at least it; otherwise the flag |

`0xe669e0` has four callers: `0x631848` (slot 145, set), `0x67345c` (clear), `0x6993c8` (slot 150)
and `0xe4307c` (read). The bit writer `0xe5c550` is entered only by `b` from `0x631864` (set) and
`0x673478` (clear), and slot 145 (`0x63182c`, +0x488 of both wrapper vtables) is called at four
sites, so a console sets a flag in two ways. `0x52fff0`, `0x824eb0` and `0x28eec70` each call slot
135 and set the flag of every move it lists for the level passed. `0x6568c4`, in the construction
routine `0x656060` (five callers), runs only when wrapper slot +0x8b8 (`0xdf5488`, `0x106ba0`, the
getter of byte 0x23) is true: it looks a move up by species (slot +0x1b0) and form (slot +0x1b8) in
`0x657ae0` (a map from GOT `0x3eca658` = `0x6137848`, through `0x511f90`), checks it with `0x41ea50`,
writes it into move slot 0 through slot +0x110 (`0x6568a4`) and sets its flag. The two console-made
records with byte 0x23 = 1 carry that move: Roserade 605 and Glaceon 247, each in slot 0 and flagged
(move indices 227 and 112). Xerneas's 583 (index 214), held another way, is unflagged. A record
received or loaded brings its flags whole. The map's source file was not found. A record whose
flags are all zero still has every learnset move at or below its level unlocked. Nothing on the
receive path reads the array.

The summary screen `0x8d0610` (one caller, `0x8cc5a8`) formats `"%s%s"` (`0x31c6db3`) with
"/plus_on" (`0x3247096`) and with "/plus_off" (`0x31d992e`) for each move and hashes both with
FNV-1a. Unless bit 0 of the word at [x29-8] is set (`0x8d1a08`), it calls slot 150 (`0x8d1a18`,
`0x699300` in both wrapper vtables) with the move id, the result of wrapper slot +0x100, the
four-moves getter (`0x8d163c`). When slot 150 returns true (`0x8d1c3c`), "/plus_on" is looked up
with `0xf510` and passed to `0x168f70`, then "/plus_off" to `0xf510` and `0x14248`; when it returns
false, or the bit is set, the two names swap. The bit is the return of `0x393b8(x21, frame-0xf0)`,
stored at `0x8d1438`.

The six species of console-made records, against the table:

| record | level | flags against {unlock level <= level} | extra flags | unflagged |
|---|---|---|---|---|
| Noibat 714 | 44 | equal | | held 542 (unlock level 47) |
| Swablu 333 | 44 | equal | | held 297 (unlock level 47) |
| Xerneas 716 | 100 | equal | | held 583 (not in its learnset) |
| Onix 95 | 72 | 350 missing (level 254) | | |
| Roserade 407 | 63 | 866 missing (level 254) | 605, in neither learnset: the byte-0x23 move in slot 0 | |
| Glaceon 471 | 63 | equal | 247, in neither learnset: the byte-0x23 move in slot 0 | |

Glaceon also carries Eevee's level-up moves 36, 38, 129, 204 and 273, which are 254 entries in its
own learnset, and Roserade carries 40, a 253 entry of Roselia (315).

The ability is Scarlet's u16 at 0x14 with the slot bits at 0x16. GetAbility `0xe43bec`, reached
only through the thunk `0x288d894` (vtable slot `0x3d1a918`, a wrapper holding the PokemonParam at
+0x48), returns the stored value when it is below 299 (0x12b) and otherwise the personal table's
ability for the slot, `0xe5d368(species, form, bit 2 ? 2 : bit 1)`. The only other readers of 0x14
are the type getters `0x99c84` and `0xa4354`: species 493 with ability 121 and species 773 with
ability 225 take their type from the held item (`0xe5d528`, `0xe5d5a0`). The creation routines
`0xe3eb34` and `0xbb8f04` write it from `0xe5d368`. Every console-made record stores an ability
below 299 (5, 30, 38, 81, 151, 187).

The thunk is slot 42 of the vtable whose address point is `0x3d1a7c8` (GOT `0x3ec5b48`, constructor
`0x2890cb8`, which allocates the PokemonParam at +0x48); slots 43, 45, 48 and 49 thunk to
`0xe43f84`, IsEgg `0x18e4c` and the type getters `0xa4354` and `0x99c84`. From the 321 slots of the
`0x3e28e58` wrapper, a call walk four levels deep reaches the ability getter `0xe4a3c0` only
through slots 48 and 49, the type getters, and never reaches `0xe43bec`.

Over the whole image, the relocated slots whose function reaches `0xe43bec` or `0xe4a3c0` within two
calls are nine: `0x3d1a918` (slot 42 of `0x3d1a7c8`), `0x3d1a948`/`0x3d1a950` (its slots 48 and
49), `0x3e28fd8`/`0x3e28fe0` and `0x3e2a5b8`/`0x3e2a5c0` (slots 48 and 49 of the two PokemonParam
wrappers) and GOT `0x3ec4f60`/`0x3ec4f68`, the type getters. The raw getter's direct callers are
`0x99cac`, `0xa437c` and `0xe43c04`, and `0xe43bec` is entered only by `b` from `0x288d894`. Slot 42
of the `0x3d1a7c8` class is the one way to a stored ability outside the type getters. That class is
an engine component: slot 13 (`0x288db10`) returns the type id `0xfb63b93a`, slot 14 returns 0x158,
and the factory `0x2890d80` builds it through `0x2890a6c` and `0x2890c10` (0x50 bytes) with the
constructor `0x2890cb8`, which stores four vtable pointers from `0x3d1a7b8` (+0x10, +0x240, +0x290,
+0x2e8). Its primary vtable runs 68 code slots.

The message archive name "tokusei" (`0x31e3d5f`) has four code references:

| reference | in | what it is |
|---|---|---|
| `0x2d630b8` | `0x2d6307c`, one caller `0x2d5257c` in `0x2d52468` | the battle ability window |
| `0x2923560` | `0x2923544` | a message-archive loader, beside "wazaname" |
| `0x83cd08` | `0x83c55c` | a field name in a Pokemon creation spec reader, beside "tokuseiIndex" |
| `0x849120` | `0x848934` | a field name in an encounter table reader |

`0x2d52468` (one caller, `0x116bd4`) loads "btl_std" (`0x3e256b8`) and "BTL_STRID_STD_TokWin"
(`0x3e25af0`) and builds a "TOKUSEI_" label from the record at `0x3e25b08` (its string relocation at
`0x3e25b10`; the string `0x32ca5cf` has no code reference) and `0x886240(value, 3)`. The value is
slot 42 of the object at its argument's +8 (`0x2d524f4`, `ldr x8,[x8,#0x150]`); the same object goes
to `0x9062c0` (`0x2d52558`), which calls its slot 284 (+0x8e0, `0x906304`). Slot 284 lies beyond the
component's vtable; in the PokemonParam wrappers it is IsEmpty (`0x13770`). The image holds seven
321-slot vtables of that wrapper interface (`0x3e28e58`, `0x3e29950`, `0x3e2a438`, `0x3e2af50`,
`0x3e2ba38`, `0x3e2c520`, `0x3e2d360`), and slot 42 is `mov w0,wzr; ret` in every one (`0x2d6fd88`,
`0x2d71464`, `0x2d72714`, `0x2d753e0`). The name "statusname" (`0x329488c`) is loaded by the next
function, `0x2d63130` (`0x2d63190`, one caller `0x2b2fe6c`). No path found reads the stored ability
into any screen.

### What loading a received record checks

A partner's `0101` reaches `0xb2a44c`, the handler registered for CommandSelectPokemon
(`0xca33d8`, called from `0xca2928`). Its deserializer `0xb4e248` requires tag 0xb9 with three
members (`0xb4e33c`), reads the first into a u16 (`0xa91178`), requires the second to be tag 0xbc of
exactly 0x158 bytes (`0xb4e4b8`) and keeps the third at struct+0x15a. On any error the handler is not
called (`0xb4e1c8`). The handler allocates a PokemonParam (`0x82713c`) and loads the 344 bytes with
`0x270994`:

1. `0xe47e94` copies 0x148 bytes into the core and 16 into the party tail, decrypts both and
   compares the checksum at core+6 with the word sum; a mismatch sets the Bad Egg bit. It also clears
   fast mode, so every load ends by rewriting the checksum and re-encrypting: a record received with
   a bad checksum is kept with a corrected checksum and the Bad Egg bit set.
2. `0xe3f18c`: for a non-zero species, `0x2901a4(species, form)` looks the pair up in the personal
   table (`0xe366b0`, a map keyed `species * 10000 + form`) and reads the byte of the entry's
   FlatBuffers field index 1 (vtable +6, `0xe3bbfc`), 0 when the field is absent. Zero sets the Bad
   Egg bit (`0xe51698(acc, 1)`). A key missing from the map falls back to the entry at map+0x80, the
   species-0 entry, which has no field 1.
3. `0xe41750(pp, 1)` writes the level from the experience into the party tail and recomputes max HP
   and the five stats from species, form, stat level, IVs, hyper training bits, EVs and the stat
   nature. In this step current HP stays 0 when it was 0 and otherwise rises by the max-HP gain.
4. `0xe42584` counts the non-zero moves from slot 0 and clamps the PP of that many slots to the
   move's maximum with its PP ups (`0xe6646c`); an egg or a Bad Egg (`0xe4c950`, `0xe485f0`) is
   skipped unless `[0x3f0784()+0x380]` is set or `0xe483b4` is true.
5. `0xb2a4a4` calls the callable at session+0x88 with the new PokemonParam and ignores its result,
   moves the PokemonParam into session+0x128, and sets the partner state +0x134 to 3 (a pick) when
   bit 0 of the third member is clear. The callable is always `0xad2c68`, the name check below:
   `0xca20a4` builds the session's configuration with it (`0xca2520`, `0xca25d8`), and nothing else
   references it.

No step reads the moves against a learnset, the ball, the met data, the trainer ids, the ability or
the party tail's level; the tail and the stats are overwritten. On this path a composed record fails
in two ways, a wrong checksum and a personal-table flag of zero, and both make a Bad Egg rather than
a refusal. A name the check rejects is rewritten, never refused.

### The name check on a received Pokemon

`0xad2c68` returns at once for an empty record (IsEmpty `0x13778`) and otherwise runs `0x89f250`,
which opens an `nn::ngc::ProfanityFilter` into the global `0x612d3d0` with a 0x20000-byte work
buffer (`0x912e10`), checks three names with `0x9138d4(str, len, language)` and finalizes the filter
(`0x912d80`). `0x89f250` has one other caller, `0x89de34`.

| name | language passed | on failure |
|---|---|---|
| nickname, 0x58 | the record's, 0xd5 | `0x8a0370`: the species name in that language (`0xe33ca0`) is written as the nickname and the nicknamed bit (0x8c bit 31) cleared |
| original trainer's, 0xf8 | the record's, 0xd5 | replaced by `0x3d8a248[language]` and written back with `0xe579a0` |
| handler's, 0xa8 | the handler's, 0xc3 | replaced by `0x3d8a248[language]` and written back with `0xe5a190` |

A language of 12 or more indexes the table as 0. `0x8a0370` writes nothing for an egg or a Bad Egg
(`0xe4c950`, `0xe485f0`) when the byte at `[0x3f0784()]+0x380` and accessor+0x1a are both 0. The
replacement table `0x3d8a248` holds twelve UTF-16 strings:

| index | string |
|---|---|
| 0, 1, 6 | `ゼット.` |
| 2 | `Z` |
| 3 | `Zed` |
| 4, 7, 11 | `Zeta` |
| 5 | `Zett` |
| 8 | `제트.` |
| 9, 10 | `Z.` |

`0x9138d4` fails a name when:

- its length is 0 or its first unit is 0;
- it is 7 units or longer and any unit is in 0x3041..0x3090, 0x30a1..0x30fa, 0x4e00..0x9fcc or
  0xac00..0xd7a3 (the lanes at `0x3308840` and `0x33087b8`);
- the language is 1..5, 7 or 11 and any unit before the first 0 is in 0x4e00..0x9fa0 other than
  0x4edd;
- L, the value `0x444330` returns, is 0, 6 or above 11, whatever the name;
- the filter's vfunc +0x28, called by `0x913ad0` as `(&result, pattern, &str, 1)` with pattern
  `0x339f650[L - 1]` = 0x13, 0x12, 0x36, 0x92, 0x52, 0, 0x11a, 0x412, 0x8813, 0x8813, 0x11a,
  leaves a non-zero result.

A string that the length scan `0x913a80` (which skips 0x10-tagged runs) measures as 0 passes without
the filter, and a filter call that returns an error passes too (`0x913b08`). A composed record with
an empty handler name and handler language 0 has that name replaced by `ゼット.` on receipt, and an
empty original trainer's name becomes the string of the record's language; a completed trade then
overwrites the handler's name (What the trade writes into a received record). The traded nickname
and trainer name PKLDN and the names of the reference records pass.

L is byte +0x14 of the singleton at `0x6131800` (GOT `0x3ec7800`): `0x444330` reads it through
`0x410a20` once the word at +0x80 marks the object constructed. It is the game's text language,
numbered as the record's language byte, and indexes the message directory table `0x3e278b8` (stride
0x18, `0x940dd8`): 0 "jpn", 1 "jpn", 2 "English", 3 "French", 4 "Italian", 5 "German", 6 "jpn",
7 "Spanish", 8 "Korean", 9 "Simp_Chinese", 10 "Trad_Chinese", 11 "Latam", 12 "item". The message
loader `0x410a30` uses L when its own language argument is 0 (`0x410a68`, `0x410a70`).

The constructor `0xaa1340` (callers `0xaa1320`, `0x118ad60`, `0x1b29070`) stores 0 at +0x14 and, at
+0x10, the index `0x17d6368` makes of `nn::oe::GetDesiredLanguage()` (PLT `0x3161b10`): ja 0, en-US 1,
fr 2, de 3, it 4, es 5, zh-Hans 6, ko 7, nl 8, pt 9, ru 10, zh-Hant 11, en-GB 12, fr-CA 13, es-419 14,
anything else 15. `0x741760` maps that index through the 15 bytes at `0x330f728`, `1 2 3 5 4 7 9 8 2
2 2 10 2 3 11`, and gives 2 above 14. The one writer of +0x14 is the setter `0x17d62ec`, called at
`0x2c204ac` in the language-select view `0x2c2047c` (a byte from the view's table `[x0+0x50]`, indexed
by the menu position) and by `b` from the wrapper `0x741740`, which has four callers:

| call | in | value |
|---|---|---|
| `0x741710` | `0x7416b4`, from the boot sequence at `0x73bdb0` | the desired language through `0x741760` |
| `0x118adac` | `0x118ad10` (slot `0x3be5460`) | the same |
| `0xbb9d30` | `0xbb9ccc` | the player's trainer record +0x47, the language `0x882104` copies (`0x505c30`, `0x23c398`) |
| `0x16734c0` | `0x1673170` (slot `0x3c01cc0`), at `0x1673198` and `0x16731dc` | `0x8a8a10(x, 1, 0)`, which checks its argument against -1001000 and a type byte 3: a script binding that stores any integer |

The boot table gives 1..5 and 7..11. The name check's pattern `0x339f650[L - 1]` is a set of
`nn::ngc` pattern lists, so the receiving console's language picks the word lists, whatever the
record's language:

| L | pattern | lists |
|---|---|---|
| 1 Japanese | 0x13 | Japanese, American and British English |
| 2 English | 0x12 | American and British English |
| 3 French | 0x36 | American and British English, Canadian French, French |
| 4 Italian | 0x92 | American and British English, Italian |
| 5 German | 0x52 | American and British English, German |
| 6 | 0 | none; the check has already failed the name |
| 7 Spanish, 11 Latin American Spanish | 0x11a | American and British English, Latin American Spanish, Spanish |
| 8 Korean | 0x412 | American and British English, Korean |
| 9, 10 Chinese | 0x8813 | Japanese, American and British English, Chinese, Taiwanese |

### What the trade writes into a received record

Step 6 of the exchange calls the trade object's vfunc +0x80, `0xcbc68c`, which calls `0xcbc7fc`.
Unless `0xcbc9e8` returns null (`0xcbc854`, which skips the whole update), `0xcbc7fc` takes the
player's trainer record (`0x505c30` on the singleton from GOT `0x3ec28d8`) and fills a struct with
`0x882104`: the u32 at +0x40 (trainer id and secret id), the gender at +0x45, the language at +0x47
and 13 units of name from +0x50. It wraps the partner's PokemonParam (trade object +0x78) with
`0x825358` and calls wrapper slot 167 (`0xcbc888`, +0x538; `0xcebfe0` in both wrapper vtables),
which thunks to `0xcebfe8`:

- when the original trainer's gender (`0xe4f570`, 0x125 bit 7), the u32 at 0x0c (`0xe49d50`) and the
  original trainer's name (`0xe510c0`) all match the struct, it sets the current handler 0xc4 to 0
  (`0xe58a70`), calls `0xe3f900` and returns 1;
- otherwise it sets 0xc4 to 1, writes the struct's name (`0xe5a190`), gender to 0xc2 (`0xe5a3a0`)
  and language to 0xc3 (`0xe5a5c0`), writes 0 to the handler's memory 0xc9, 0xca, 0xcb and the
  halfword 0xcc (`0xe59910`, `0xe59b30`, `0xe59f70`, `0xe59d50`), writes `0xe340ac(species, form)` to
  the handler's friendship 0xc8 (`0xe58eb0`), calls `0xe3f900` and returns 0.

So a received Pokemon the player did not originate carries the receiving player as its handler, and
a handler name the name check replaced does not survive. When the receiving player is the original
trainer, only 0xc4 changes. Each of these setters, on a record still marked encrypted (accessor
+0x18), sums the 0x140 bytes from core+8 (`0xe5d810`) and sets bit 2 of core+4 when the sum differs
from the checksum at core+6 (`0xe58b60..0xe58b80`); on a record with bit 2 set it writes into a sink
at `0x3f7ef98` instead of the record (`0xe58bcc`).

### The personal table

`0xe380c0` loads `personal_array.bin` from the directory `0x7961b0` configures as "avalon/data"
(`[[0x3f7f038]]`); `waza_array.bin`, `tokusei_array.bin` and `growTable.bin` load the same way. The
RomFS keeps it in the pack archive:

| | |
|---|---|
| `/arc/data.trpfd` | 9,877,520 bytes: 238,546 file hashes, 13,181 packs |
| `/arc/data.trpfs` | 4,753,821,072 bytes, magic `ONEPACK` |
| name hash | FNV-1a 64 with offset basis `0xcbf29ce484222645` (`0xe38438`) |
| `avalon/data/personal_array.bin` | hash `0x68ab38e2cf1281ed`, file index 97074 |
| its pack | 169, `arc/avalondatatokusei_array.bin.trpak`, at trpfs `+0x4bc1840`, 131,488 bytes, 4 files |
| its entry | compression type 3, 110,132 bytes, 384,260 decompressed by `OodleLZ_Decompress` `0x1a9c9e0` |

The file is a FlatBuffers vector of 1445 tables with 1445 distinct keys. Field 0 is a struct opening
with the species and form halfwords, which the map builder `0xe36170` keys as `species * 10000 +
form`, keeping the key-0 entry at map+0x80. Species keys run 0..1010 with every value present, and
434 entries have a form above 0. Keys from 917 are the generation 9 internal index. Field 1 is 1 on
594 (species, form) pairs over 364 species and absent on the other 851 entries.

A received record whose (species at 0x08, form at 0x24) pair has field 1 clear or no entry loads as
a Bad Egg. Converted to national numbers, the 594 pairs equal PKHeX's `personal_za` presence list
species for species and form for form up to 1010. PKHeX also lists 1011..1016 (14 pairs), which have
no entry in the 2.0.2 table and so arrive as Bad Eggs. The Mega Dimension DLC ships no personal
table: its one PublicData NCA (101,376 bytes) holds a 692-byte RomFS. Every species traded so far
(95, 333, 407, 471, 707, 714, 716) is present in form 0.

`0x13778` (IsEmpty: false for a Bad Egg, else species == 0) and `0x18e4c` (IsEgg: mode 0 egg and not
bad, 1 bad, 2 either) gate `0x962388`, which boxes a Pokemon (`0x961964`) only when it is neither
empty nor egg-or-bad. The live trade path `0x95f8f4` boxes the partner's pick through `0x961964`
(`0x960000`) after `0x962e70` finds a free slot (`0x95ffec`), with no direct call to either test.
It reaches `0x962388` only through `0x95ffc0`, when the flow object's byte +0x35 is 0, and
`0x961c9c`, which calls it on the object at +0x90; `0x962388`'s other callers are `0x261178` and
`0x55a554`. In its state 0 it loads a stored 0x158-byte record with `0x270994` and tests it
(`0x962538`, `0x962548`) only when the stack byte at sp+0x2e0 is clear. Inside `0x961964` the egg
and Bad Egg tests appear only as a skip: `0x962be0` builds the `0x3e28e58` wrapper (0x68 bytes,
constructor `0x962ccc`), which reaches the PP clamp `0xe42584`, and that returns early for an egg
or a Bad Egg. For a Bad Egg pick the name check runs, and its nickname fix writes nothing while both its gate
bytes are 0.

On the exchange that follows a pick (`0x9610a4`, the worker `0x960c20`, `0xc8ad1c`, `0xcbc68c`,
`0xcbc7fc`, the store `0xcbcbec`), only `0xcbc7fc` reaches an egg or Bad Egg test (`0x13778`,
`0x18e4c`, `0xe485f0`, `0xe4c950`) within three direct calls, through `0xcbca60` and `0x8270d0`. The
tests there skip work rather than refuse: the PP clamp `0xe42584` guards its body at entry, and
`0xc34b5c` (wrapper slot +0x8f0) skips the stat recomputation `0xe41750`, both for an egg or a Bad
Egg unless `[0x3f0784()+0x380]` is set or `0xe483b4` is true. The constructor `0xe3e570` (vtable from
GOT `0x3ec2660`) has no such test. The handler update writes a Bad Egg's handler fields into its
sink. No refusal of a Bad Egg was found on that path; the virtual calls it makes were not all
followed.

## A trade with a retail console

A retail Legends Z-A on its Link Trade search, code 00000000, traded with `bin/za_join.py` and kept
a Pokemon composed from zero bytes: the shiny Glaceon PKLDN of the section above,
`scratchpad/za_offer_glaceon_built.bin`. Nothing changed from the emulated run. The console's
selection record came 1.16 s after the seat, the previews at 3.74 s, the player's offer at 55 s,
the console's `0102` at 88 s and `0104` at 89.6 s, and the joiner's four `0200` steps at 89.7 s and
104 s. After the trade the console returns to its trade menu on the same seat and offers again.

A record the save already holds trades again under a new encryption constant and PID with the
same `hi ^ lo` (the shiny state): the Glaceon above, re-sent as EC `172f7a2b` PID `bd5f5957`
(`--fresh-pid`), completed its trade 24 s after the seat.

Through a Linux Wi-Fi card most associations were refused with LDN status 1: 59 and 35 refusals
before the two seats that formed, on one MAC. Through the ESP32 board the first association seated. A seat that forms late in the console's host phase is handed over rather than
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
  writes `01`; a retail Z-A host writes it through CloseParticipation (The property update);
- a broadcast acknowledgement from the host reports the joiner's stream in entry 1 and the idle
  base 0xfff0 in the other three.

### The property update

The Net update property (type 0x50) is built by `0x2502960`, which increments the sequence at
NetProtocol+0x160, through `0x250f5d0`, and serialized big-endian by `0x250e414`. Offsets from the
start of the Net message, 0x26 bytes in all:

| wire | size | field |
|---|---|---|
| 0x04 | 4 | sequence id, NetProtocol+0x160 |
| 0x08 | 8 | network id, session property +0x90 |
| 0x10 | 2 | participant count (`0x25050dc`) |
| 0x12 | 2 | station slots, NetProtocol+0x1216 |
| 0x14 | 8 | session property value (`vfunc +0x10`); the LDN property keeps the scene id, NetworkInfo +0x0a, at +0x98 |
| 0x1c | 1 | accept state (`0x2505ec0`) |
| 0x1d | 1 | session property `vfunc +0x80`, bit 0 |
| 0x1e | 4 | system property size (`0x24fe4dc`) |
| 0x22 | 4 | game data size (`vfunc +0x50`) |

`0x2505ec0` returns the byte at NetProtocol+0x340 once the host address (+0x1280) and the station's
own address (+0x1260) are both set, or when +0x12d0 is non-zero, and 0 otherwise. The byte is
written:

| writer | value |
|---|---|
| the network create and auto-connect jobs (`0x2511b94`, `0x2511658`) and a third job site `0x2515714` | 1 when the session property's byte +0xa6 is set, 2 when clear |
| `0x2515434`, from the job's byte +0xc0 (stored by `0x2515220`) | 1 through `0x250758c` (from `NetFacade` vfunc 17), 2 through `0x2507828` (from vfunc 19) |
| host migration `0x250b060` | re-runs the 1 path when the byte is 1, the 2 path otherwise |
| the setter `0x2500a9c` | 1 from its callers `0x25fdc90` and `0x25fe1ec` |
| a station receiving a 0x50 (`0x25035bc`) | the message's byte; `0x2502e70` then sets its own +0xa6 to `byte != 2` |

The LDN session property sets +0xa6 to `stationAcceptPolicy == 0` (NetworkInfo +0x62, `0x25234b8`).
`LdnProtocol` vfunc 23 (`0x251f18c`) calls `nn::ldn::SetStationAcceptPolicy(0)`, accept all; vfunc
24 (`0x251f110`) sets policy 1; vfunc 21 (`0x251f208`) adds accept filter entries, sets policy 3 and
keeps +0xa6 across the network info refresh (`0x251f808`). So 1 means the property's accept flag is
set and the network accepts all stations; 2 means it is clear. A 2 on the wire comes only from the
job, facade and host-migration paths or a received 0x50.

The facade entries are shared: `0x25183bc` is index 19 of `NetFacade`, `LocalFacade`, `LanFacade`,
`WanFacade` and `NplndFacade` (slots `0x3c8a290`, `0x3c8b7a0`, `0x3c8c5f8`, `0x3c8f818`,
`0x3c90d68`), and starts asynchronous operation 0xa through `0x2507828`; index 17 (`0x251826c`)
starts operation 9 through `0x250758c`. Neither has a direct caller. Both reach `0x2515220`, which
keeps the value at the `NetNetworkStateJob`'s byte +0xc0 for `0x2515434` to write into
NetProtocol+0x340 (below). Host migration calls `0x250758c` and `0x2507828` directly (`0x250b098`,
`0x250b0f8`); `0x2507828`'s only other caller is `0x25183f4`, in facade index 19.

`nn::pia::session::OpenCloseParticipationJob` makes the facade calls. Its start `0x255c118` stores
the object it is given (the session's +0x30) at job+0xc8 and picks its step from its boolean
argument: "OpenCloseParticipationJob::OpenParticipation", step `0x255c264`, calls index 17 of that
object (`0x255c34c`); "OpenCloseParticipationJob::CloseParticipation", step `0x255c404`, calls index
19 (`0x255c484`). The chain above it has one caller at each level:

    0x255c118   <- 0x254703c in 0x2546fe8
    0x2546fe8   <- 0x253e870 in 0x253e7bc, argument 0: close. 0x253e7bc returns 0x10408 while the
                   session's state object (+0xd0) reads 1 or its byte +0x528 is 0
    0x253e7bc   <- 0x253e780 in 0x253e744
    0x253e744   <- 0x1a25454, game code

`0x1a25454` is slot 13 of a game task (vtable address point `0x3c17cc0`, constructor `0x1a25390`,
0x58 bytes from `0x1a22ca0`). It reads the Pia session singleton `[[0x3edc128]]`, returns when
`0x253da70` finds the state object reading 1, and calls `0x253e744` only when the session's
(u64, u16) at +0xe0/+0xe8 is non-zero and equal to the one at +0xf0/+0xf8. `0x9157d0` makes the same
comparison and is the game's host test (`0x965660` stores it at +0x14, `0x965864` at +0xb8), so the
game closes participation only while it is the session host.

The task builder `0x1a228f0` takes a name hashed with FNV-1a 64 under the basis
`0xcbf29ce484222645`. All four of its callers pass "CloseSession" (`0x32f8d4a`, length 12, hash
`0x0dd344f64c81e84d`):

| call | in | what that is |
|---|---|---|
| `0x19a7614` | `0x19a7590` | index 19 of the local session driver (address point `0x3c16dc8`, GOT `0x3edd130`), whose other slots name "InitializeLdn", "StartupSession", "CreateSession" (14), "BrowseSession" (15, 17), "JoinSession" (16), "LeaveSession", "CleanupSession", "TerminateLdn" (18) and "UpdateSessionSetting" (20) |
| `0x1a2ab94` | `0x1a2ab10` | index 19 of a second driver (slot `0x3c17fa8`) with no Ldn names; its slot 13 names "JoinRandomSession", "WaitMember" and "CloseSession", slot 14 "RandomMatchingCancel" |
| `0x19d7ac8` | the callable `0x19d7a70` (`adr` at `0x19d6de4`) | the CloseSession step of the local driver's random-matching sequence (below) |
| `0x1a35768` | the callable `0x1a35710` (`adr` at `0x1a34a84`) | the same step in the second driver's code |

The network manager forwards to its driver's index 19 at `0x199dec4` (the driver at +0x38, slot
+0x98). Its one caller, `0x2a49c38` in the request constructor `0x2a49bc4`, is reached through
`0x2a49630`, `0x2a48ea0` and the entry `0x2a49218`, which returns an empty request while the
network system flag `[0x6133ec0]` is clear. `0x2a49218` has three callers: `0x915734` in
`0x915630`, `0x2cb5254` in `0x2cb5238` (called at `0x911f48` right after the host test at
`0x911f14`), both in the net battle flow, and `0xae0fac` in `0xae0eb8`, reached only when the host
test `0x915770` passes; `0xae0afc` calls `0xae0eb8` when its owner's byte +0x121 is set, then sets
+0x122. The local driver's slot 13 (`0x19a1310`, slot `0x3c16e30`) interns, in address order,
"RandomMatchingSeq", "RetryBody", "CloseSession" (`0x19a208c`, the same hash), "StoreSessionInfo" and
"RandomMatchingCancel". It calls the sequence `0x19a1470` (`0x19a1388`), whose CloseSession step
builds a delegate with invoke `0x19d6890` and managers `0x19d8440`, `0x19d72c0`, `0x19d84e0` (`adr` at
`0x19a2180`, `0x19a2190`, `0x19a21b8`, `0x19a21c4`, each the only reference to its target), stores a
flag byte in its capture (`0x19a2178 and w8,w26,#1`) and hands it to `0x990678`. The invoke copies the
flag into the capture of the delegate it installs with `0x19d7a70` (`0x19d6b38..0x19d6b4c`,
`0x19d6d20..0x19d6d2c`, `adr` at `0x19d6de4`). `0x19d7a70` reads it at +8 (`0x19d7a84`): set, it calls
`0x1a228f0` with "CloseSession" (`0x19d7ac8`); clear, it names "NoNeedToClose" (`0x31c713c`, length
0xd) and builds no task. `0x1a35710` is the same test (`0x1a35724`), "CloseSession" at `0x1a35738` and
"NoNeedToClose" at `0x1a357b0`.

The flag is bit 0 of slot 13's fourth argument and nothing else: `0x19a1374 and w3,w24,#1`, then
`0x19a1498 mov w27,w3`, `0x19a1a00 mov w28,w27` and `0x19a1f94`/`0x19a2044 mov w26,w28` are its only
definitions over the whole of `0x19a1470..0x19a3788`. The `mov w27,#1` at `0x19a1c30`, on the path
that names "RetryBody", feeds only the tests at `0x19a1cf0`, `0x19a1d1c` and `0x19a1f58`. The network
manager forwards only its driver's slots 14 and 19 (`0x199dea8`, `0x199dec4`); no thunk in
`0x1980000..0x19a1000` reaches slot 13.

Within Pia, `0x255c484` is the only virtual call to facade index 19. Fourteen loads through offset
0x98 feed a branch in `0x24e0000..0x2600000`: twelve through a vtable, on session properties
(`0x24fe354`, `0x24fe36c`, `0x24fe5e0`, `0x24fe5f8` on the property itself; `0x250144c` on
NetProtocol+0x200), the LDN and LAN protocols from their background jobs (`0x2522704`, `0x252b650`),
`pead::ExpHeap` (`0x252dfb0`), the two reliable protocols on themselves (`0x2563268`, `0x256f4d8`),
`ThreadStreamManager` (`0x257de84`) and the facade at job+0xc8 (`0x255c484`); `0x253f100` through a
function pointer its object holds (stored at `0x253f0f0`); and `0x25b554c` from the stack. Outside
Pia, the sequence load +0x30, load the vtable, load +0x98, branch occurs once, at `0x1b49684` in
`0x1b48fd0`, on an object unrelated to the session. The 20 functions that load the Pia session
singleton (GOT `0x3edc128`) make no virtual call through 0x98.

`0x2515220` has two callers: `0x250758c` (operation 9) passes 1 (`0x25076bc`, `0x25076c4`) and
`0x2507828` (operation 0xa) passes 2 (`0x2507958`, `0x2507960`); the job is `[NetProtocol+0x248]`.
When `[[job+0xe0]+0x344]` is 1 it calls `0x2513c0c`, and when that returns 0 it stores the value at
the job's +0xc0 (`0x25152c0`); otherwise it fails with 0x10408 and stores nothing. `0x2513c0c` (one
caller, `0x251525c`) runs `0x2512b60(x0, x1, 8)` and, when that returns 0, stores the value at
`LdnBackgroundProcessJob`+0x9b (`0x2513c6c`) and schedules the member at vtable offset 0x128
(`0x2513c88`, the only `mov #0x128` in `0x24e0000..0x2600000`), vfunc 37. `0x2513c0c` is the only
writer of that byte; the other `strb` to +0x9b in Pia, `0x24f0df4` inside `0x24f0c30`, is the Pia
settings' language index, 0xff when `nn::oe::GetDesiredLanguage()` matches no entry.

`LdnBackgroundProcessJob` vfunc 37 (`0x2513ccc`, shared with the Lan and Nplnd jobs) calls index 23
of the LDN protocol when its byte +0x9b is 1 and index 24 otherwise (`0x2513cf8`, the call at
`0x2513d1c`). `nn::ldn::SetStationAcceptPolicy` (PLT `0x3163b60`, GOT `0x3ee9ab0`) has three callers,
all in `LdnProtocol` (vtable address point `0x3c8aef8`):

| call | in | policy |
|---|---|---|
| `0x251f19c` | index 23, `0x251f18c` | 0, accept all |
| `0x251f120` | index 24, `0x251f110` | 1, reject |
| `0x251f474` | index 21, `0x251f208`, after `AddAcceptFilterEntry` (`0x3163b70`) | 3, whitelist |

Of the virtual calls through offset 0xc0 in `0x24e0000..0x2600000`, `0x2513d1c` is the only one on
the LDN protocol; game code outside Pia was not scanned for one. Within Pia, policy 1 therefore
follows only from +0x9b holding 2, which only operation 0xa writes. `0x2515434` then copies the job's
+0xc0 into the accept state (`0x2500a9c`) and builds the Net 0x50 at once (`0x2502960`).

A retail console on its Link Trade search shows the transition. The joiner board records its
advertisements while seated; decrypted (LDN protocol 1, AES-CTR, every one of 725, 703, 664 and 673
advertisements read), four seated sessions give, in seconds from the seat as the host timestamps
them:

| policy 0, 2 of 2 nodes | Pia player count 2 first advertised | policy 1 first advertised | the Net 0x50 |
|---|---|---|---|
| -0.001 | 0.590 | 0.613 | 0.638 |
| 0.000 | 0.563 | 0.583 | 0.606 |
| -0.002 | 0.065 | 0.067 | 0.094 |
| -0.001 | 0.553 | 0.573 | 0.575 |

The only application-data byte that changes is the system property's number of players (advertise
data +0x16, `e1 01 01 00` to `e1 01 02 00`). The policy changed between the advertisement before the
one first showing 1 and that one, so 2 to 48 ms before the Net 0x50. Each session carries exactly one
Net 0x50, 150 bytes, sequence id 1, accept-state byte `02`, and the policy stays 1 to the end of each
trace, 68 to 74 s after the seat. No host migration was running: the console's first Net 0x40 came
65.7 to 71.4 s after the seat. The `02` a retail Z-A host writes is therefore CloseParticipation's,
operation 0xa through facade index 19, which the retail bytes show ran; which of the four task
builders above started it they do not show. Every advertisement from the seat on reads 2 of 2
participants, so the policy change refuses no station the network's capacity did not already
refuse.

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
count. A retail console searching with the code 1234 5678 joined `bin/za_host.py --code 12345678`
and traded the same way, and `bin/za_join.py --code 12345678` joined a console searching on that
code and traded. An emulated Legends Z-A trades with the same host over ldn_mitm.

## Mystery Gift

Mystery Gift in version 2.0.2 offers three entries: Get via Internet, Get with Code/Password and
Check Mystery Gifts. It has no local-wireless path, so a gift cannot be served over LDN.

## Unresolved

- Which of the four builders of the "CloseSession" task (`0x19a7590`, `0x1a2ab10`, `0x19d7a70`,
  `0x1a35710`) a Link Trade search runs, and with which fourth argument slot 13 (`0x19a1310`) enters
  the random-matching sequence. Breakpoints on an emulated host at `0x1a228f0` (caller in x30) and
  `0x19a1310` (w3) name both.
- Whether game code reaches facade index 19 other than through session+0x30, through
  framework+0xb8 or a facade getter. A scan of the loads of framework+0xb8, or a breakpoint on
  `0x25183bc` with x30 on an emulated host, settles it.
- Whether the `0x3d1a7c8` component's slot 42 is ever called, and what the battle ability window
  shows. Breakpoints on `0x288d894` (caller in x30), `0x2d52468` (the vtable of the object at x1+8)
  and `0x2d6fd88`, on an emulated console opening a summary and then in a battle where an ability
  announces itself, answer it: a hit on `0x2d52468` with a 321-slot wrapper vtable means the window
  draws ability 0 whatever the record holds.
- Whether the generic lookups `0xd8a04` (`0xd8dd4`) and `0x15dc1c` (`0x15dd34`) compare the
  component's type id `0xfb63b93a`, and what they hand the component to. Reading both functions
  settles it.
- What `0x393b8` computes, the value `0x8d1438` stores as the summary screen's bypass bit. Reading it,
  or a breakpoint on `0x8d1438` while paging through a summary, settles it.
- Whether a shipped script calls the binding `0x1673170` that stores any integer into L, and what the
  language-select view's table `[x0+0x50]` holds. A breakpoint on `0x16734c0` over a play session, and
  the table read at `0x2c204ac`, settle both.
- What writes the exchange worker's error word +0x10, which selects own state 7. A watchpoint on
  worker+0x10 during an emulated trade, with one trade cancelled after the steps start, names the
  writer.
- What the extra packet `0x25688d0` sends to a station it has been silent to for a second carries,
  and which stations have byte +0xa0 set. Reading `0x256da8c` and `0x256a89c`, and a capture of a
  seated station the console has nothing else to send to, settle it.
- What a console draws for a Bad Egg pick and whether it offers Confirm. An emulated host joined by
  `bin/za_join.py` offering a record whose checksum at +6 is off by one (without `--fresh-pid`,
  which stops on such a record), with breakpoints on `0xe51698` (x1 = 1), `0xcbc7fc` and `0xcbcbec`, shows it;
  the capture's `0102`, `0104` and `0201b901XX` answers say whether the console confirmed.

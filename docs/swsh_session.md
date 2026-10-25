---
title: The cartridge and the session
parent: Sword and Shield
nav_order: 1
---

# The cartridge, its keys, and taking a seat

`main` statically links all of Pia (252 `nn::pia` classes, 2036 virtual methods) and imports
`nn::ldn`. Above Pia the game uses protocol buffers: `main` carries a `FileDescriptorProto` for each
of 78 P2P message sets (`gflnet.p2p.framework.pb`, `.block.pb`, `.sync.pb`, one package per content:
trade, battle, camp, raid).

## The LDN passphrase

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL

64 bytes, raw (two copies, `0x203ff04` and `0x203ff45`); equal to the NintendoClients wiki's
Scarlet/Violet row, one character off Legends: Arceus (`HGhG` here, `HGHG` there). The setter call
is at `0x006c3ec8` with length `0x40`. `nn::pia::local::LdnCreateNetworkJob` holds the passphrase at
+0xC4, its length at +0x104 and the local communication id at +0xB8; it copies the passphrase to
`SecurityConfig+4` just before `nn::ldn::CreateNetwork` (`0x017972bc`). `LdnBackgroundProcessJob`
requires a length of 16..64.

## The Pia game key

    p1frXqxmeCZWFv0X

Sixteen ASCII bytes at `0x01c3dc87`, used unchanged by three call sites (the wiki's Sword/Shield
row); the create/join call is `0x183fd10` from `0x006ca914..0x006ca93c`.

## Reading the cartridge

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program
    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca 87e41bc8 --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0x1900fc0 --rodata 0x1901000:0x24da168

`main` is text 0..0x1900fc0, rodata to 0x24da168, data to 0x2635f38. Method:
[Reverse-engineering a Switch title](switch_re.md).

`/bin/message/<Language>/common/*.dat` use the Gen 6/7/8 message container: line *n*'s key starts at
`0x7C89 + n * 0x2983` and rotates left 3 per character (every line ends in `0x0000`). The `.tbl` is
an `AHTB` index, entry *i* is line *i*.

## Pia 4

The Pia header carries version 4, a shape distinct from both bands on [The Pia layer](pia.md); below
it, 5.27's LDN family (same key, IV, framing plus one field). `pokeldn/ldn/pia4.py` implements it.
`pokeldn.swsh.session_keys` is BDSP's derivation with no version substitution:

    session key   = ldn_session_key(GAME_KEY, application_data[12:16] little-endian)
    IV            = crc32(application_data[0:4] || the sender's MAC)[0:3] || source id || nonce
    tag           = sixteen bytes, checked in full

484 of 484 retail packets authenticated, source id 0 on each. A second path, `0x0179bff0` ->
`0x01774f40`, seeds AES-GCM over the session's two 64-bit values; a local trade needs only the
advertisement.

## Taking a seat

    POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_join.py --keys PROD_KEYS --scan-only

scans a hosting screen and writes each advertisement to `scratchpad/swsh_net_facts.json`.

| screen | local communication id | version | scene | app version |
|---|---|---|---|---|
| Link Trade | `0x0100ABF008968000` (Sword's) | 4 | 60001 | 7 |
| Mystery Gift local wireless | same | 4 | 65535 | |

Shield uses Sword's id; its `control.nacp` lists `LocalCommunicationId[0] = 0x0100ABF008968000`,
`[1..7] = 0x01008DB008C2C000`.

The 384 bytes of application data:

    0x00  4  network id, random per session
    0x04  4  CRC32 of the Link Code's ASCII digits, LE; 0 with no code (12345678 -> 0x9AE0DAAF)
    0x08  1  system communication version, 5
    0x09  1  header size, 0x18
    0x0A  2  padding
    0x0C  4  session param, random per session
    0x10  8  zero
    0x18  2  CRC16 over 0x1A..0x180 (`0x0065dcb0`, `pokeldn.swsh.beacon.crc16`)
    0x1A  2  network version word, 12 bits, 0x0D70 (`0x006c17c0` from `0x02068848`)
    0x1C  1  bit 0 from `0x006b5c10`; set is refused
    0x1D  1  payload type, 0 for station info
    0x1E  1  page byte, 1 and 2 in turn every third publish (`0x0111aac0`)
    0x1F 266 the player profile, as in the trade snapshot at 0xAEC
             ([the protocol page](swsh_protocol.md#the-player-profile)); zero to the end

`Connect failed with status code 1` is a refused association; the next attempt on the same search
can associate. A searching Sword advertises two networks under one comm id: its Y-Comm beacon at
scene 65535 and, past the second message, its matching network at scene 60001. A station on the
beacon reached the trade box in 0 of 16 joins; `bin/swsh_connect.py` joins scene 60001 only and
rescans until it appears. After association the console broadcasts Pia to `169.254.x.255:12345`
(about ten packets a second). What ends a console's advertisement after a joined station leaves is
unread.

## How a searching Sword finds a partner

On the Y-Comm screen every console hosts a beacon network at scene 65535 and browses about once a
second (`0x006c3630`: hosts `0x006c3840`, browses `0x006c3770` with criteria from `0x006c4550`,
`0x0183fac0`, on comm id and network type only). Records passing the CRC and version gate
(`0x006c1be0`) reach the nearby-player registry (`0x0110f270`), which drops its own (device id at
advertise 0x1F and account uid at 0x2F, `0x0111b160`) and any without a network id and scene pair
(`0x0110f2d4`). Nothing here joins.

Link Trade, then the plain trade, shows two messages, each waiting for A. After the second,
`0x00fba940` calls `SetMode(comm, 2)` (`0x01096d10`); `0x01095f10` walks states 0, 5, 3, 4, 6, and
state 6 calls `StartRandomMatching` (`0x010fcff0`) with scene 60001 (`0x01096730`). A console left
on the first message never calls `SetMode(comm, 2)` and never matches.

The matching layer joins a network (`0x006c9e70`, `0x006cb8e0`, join `0x006ca1c0`) with:

    scene 60001, equal to its own
    node count 1, below its maximum of 2; network type 2; node count maximum 8 or less
    advertise 0x04 zero: a search without a link code refuses a password
    advertise 0x00, a u32, greater than the searcher's own
    advertise 0x00 not among ids whose join failed this search (0x80 entries)

A Link Code changes only 0x04. `bin/swsh_connect.py` (no code) joins a coded console and trades;
`bin/swsh_host.py --code 12345678` is joined by a coded search, and never without the code. The
larger id hosts, so two searching consoles pair one way only; a host advertises an id near
0xFFFFFFFF.

## What the console says first

Pia Local Protocol 0x24, as in BDSP (`pokeldn.ldn.local_protocol`): version 1, type 0x11, 0x30 fixed
bytes, eight nine-byte seats, the host-migration byte. `allow_participating` is true, so the console
tables the joiner before it speaks Pia: station 0 is the console at `169.254.14.1:12345`, station 1
the seat at `169.254.14.2:12345`.

The host repeats an update session until each station acks it (0x21). Only an ack carrying its
sequence id stops the rebroadcast (within 13 ms). Header byte 0x05 and the IV's source id are 0.

## The Pia session object

`[[0x02616a30]]` (also `[0x02630f40]`), where the trade code reads station ids, is Pia's session
object: 0x270 bytes, no vtable, allocated once by `0x0183ddb0` from `0x006a8644`. On LDN the network
factory is `LdnNetworkFactory`, whose slot 73 (`0x01791080`) builds a 0x7220-byte
`LdnMatchmakeSession`.

| field | written by | value |
|---|---|---|
| `+0xf0` | `0x018418a0` (`0x01841918`) | this console's own station id |
| `+0xf8` | `0x018418a0` (`0x01841990`) | the station id at the mesh's host index (`[[0x0262f7b0]]+0xab`); skipped when `[obj+0xd4] == 4` |
| `+0xf8` | `MeshEventListener` slot 2 (`0x01843580`), event 1 | the backend's slot 30, on a departing host |
| `+0xf8` | event 2 | the id from `0x017d6080` (mode 2), or the backend's slot 30 (mode 4 only) |
| `+0xf8`, `+0x100` | event 3 | zero, when `[obj+0xd4] != 3` |

`0x018418a0` runs on create (`0x018394d8`) and join (`0x0183d9b0`). Mode `+0xd4` is 2 for ordinary
LDN create and join; it is 3 or 4 only in `LanMatchJointSessionJob` and `NexMatchJointSessionJob`
(`0x01839cc0`, `0x0183a040`), 4 when `w8 - 6 < 3` (`0x0183a2b8`).

Event 1's slot-30 store requires the departing id to equal `+0xf8` and differ from `+0x100`,
`0x01840b90(obj)` true (the local mesh controller's `+0x281` and `+0x234`, both set at creation),
`+0xd8 == 1`, `[mesh+0x64] == 0`, and a mapping from `0x0184a4b0` whose word is non-zero and differs
from the word at `obj+0x180+4*[obj+0x162]`. Event 2 reaches a host-id store only when
`[obj+0xd8] - 2` is at least 6 and `0x01841350` and `0x01769ec0([obj+0x38])` are false.

`LdnMatchmakeSession` slot 30 (`0x017a23d0`) returns `0xff` when `[this+0x18]` is null, otherwise
`0x017672d0` of the 16-byte address at `[[this+0x18]+0x18]+0x2c0+8`: 0 when all zero, its first four
bytes when the last twelve are zero, error `0x10c07` otherwise. Slot 28 (`0x017a23b0`) is the call
`0x018407f0` makes.

`0x018407f0` is true when `+0xf0` is non-zero, equals `+0xf8`, and the backend's slot 28 agrees: on
the console hosting Pia's mesh. A console hosting a trade climbs the confirmation ladder on
commands; one that joined pokeldn's host follows the shared value
([the pump](swsh_trade.md#the-pump)).

## Reaching the game layer

Every layer below the game works both ways ([The Pia layer](pia.md)): Local Protocol 0x24, station
handshake 0x14, mesh join 0x18, RTT 0x58, reliable windows 0x7C and 0x80.

The joiner's 0x14 connection response must be the 840-byte form a Sword sends
(`host4.build_host_response`: account id at 0x11, player name at 0x88, the tail at 0xB1, a token at
0xBC); `bin/swsh_connect.py --respond` sends it. An emulated Shield 1.3.2 host sends no game message
after a 56-byte response. A retail Sword completes trades after 17-byte responses
([The Pia layer](pia.md#what-a-connection-response-must-satisfy-to-be-read)).

Left alone, the console repeats `61 00 00 00 0a 00`, a ping (about four a second); 0x80 asks for ack
id 1 once a second, 0x7C stays silent. `bin/swsh_connect.py --send-data HEX --send-protocol 0x7c`
sends application data (`reliable4.build_data_message`; five silent receive checks:
[version 4](pia.md#version-4)). Pass signal: the 0x80 ack id moves off 1, or 0x7C acks at all.

## The ping handshake

A payload is a four-byte little-endian message id and a protobuf body. A handshake carries these
five messages (`gflnet.p2p.sync.ping.pb`, `gflnet.p2p.block.pb`):

    0x7C  61000000 0a00      97 SyncPingDataHolder, field 1 ping {}
    0x7C  61000000 1200      97, field 2 pingReply {}
    0x7C  61000000 1a00      97, field 3 pingSynced {}
    0x7C  60ea0000 0a00      60000 BlockDataHolder, field 1 result {}  (Result { bool isBlocking })
    0x80  60ea0000 12020801  60000, field 2 imReady { isReady: true }

Answering walks the game in five steps:

    1  answer the ping continuously   --send-data 610000000a00 --send-mirror --send-count N
    2  ack every reliable window      0x7C, 0x18 port 1, 0x80; one unacked window kills the mesh
    3  answer `result{}` on 0x7C      the mirror is per protocol
    4  answer imReady on 0x80         --send2-data 60ea000012020801
    5  the console sends its party on 0x84

- A single ping answer draws one `pingReply` and the game returns to pinging.
- A `pingReply` sent before the console asks for one stops its heartbeat.
- `imReady` sent on 0x7C draws no 0x84; it goes on 0x80.
- A late-acked message is resent and can arrive after its successor. Only a sequence above the
  newest replaces the current message.

`bin/swsh_connect.py --sync-answers` answers `trade.SYNC_ANSWERS` where it has a rule, echoes per
protocol elsewhere, and prints each unruled payload.

## Leaving

A Sword leaving a trade session sends box command 3 and, about 0.77 s later, starts the Pia leave
for its role. Each step waits for a reply and falls through on a timeout when none comes.

A joined Sword leaving a host:

| step | the Sword sends | the host owes | unanswered |
|---|---|---|---|
| mesh leave | LEAVE_REQUEST `04 <own index>`, 0x18 port 1, reliable, once | LEAVE_RESPONSE `08 <host index>` | 5.0 s |
| station disconnection | `03` on 0x14, every 0.5 s | `04` | 8 requests, 3.6 s |
| LDN | leaves the network | | |

With neither answered, a Sword leaves the LDN network 9.0 to 9.1 s after LEAVE_REQUEST; with both
answered, 0.14 s after it. The version-4 host handler `0x017c19a0` sends `08` and its own index
through `0x017c2450` (two unreliable copies) and drops the station; the 0x14 handler `0x017c6110`
answers `04` to the sender. `pokeldn/ldn/host4.py` answers both.

A hosting Sword leaving its client (it is the LDN access point):

| step | the Sword sends | the client owes | unanswered |
|---|---|---|---|
| mesh migration | MIGRATION_START `44 00 01` ([host migration](swsh_trade.md#host-migration)) | MIGRATION_FINISH and an UPDATE_MESH naming itself host | 5.0 s |
| local session | its update session (0x24 type 0x11, host-migration byte 1, new sequence id), about every 0.11 s | the 0x21 ack for that sequence id | 10.0 s |
| destroy network | START_HOST_MIGRATION `01 13 00..` (16 bytes), every 0.33 s | leave the LDN network | 10.0 s |

With MIGRATION_FINISH, UPDATE_MESH as host, the ack and the leave, the retail Sword's last packet
comes 0.17 s after MIGRATION_START; answering nothing leaves it sending for 25.0 s.

- `LocalDestroyNetworkJob::WaitUntilAllClientsDisconnection` (`0x017acd70`) destroys the network when
  only the host remains or after `0x2710` ms, re-sending START_HOST_MIGRATION every `0x12d` ms
  (`0x017acbd0`, `0x017a8bb0`).
- An ack (handler `0x017a9250`, local type 0x21) clears the sender's bit only when its sequence id
  equals the message's (`0x017aed10`). What bounds the 10.0 s local-session step is unread.
- START_HOST_MIGRATION carries no sequence (`0x017abc60` writes 0 at 0xC) and nothing acks it.

`bin/swsh_connect.py --answer-migration --update-mesh --leave-with-host` (in `--preset trade`) does
all three answers.

## LAN mode

Options, then L, R and the Left Stick pressed together, turns Sword's LAN mode on; the game shows
"Mode réseau local activé" and warns that only Max Raid Battles are guaranteed. Pia then runs over the
console's IP network ([LAN mode](pia.md#lan-mode)) and Y-Comm's Link Trade search works over it.

| measured on an emulated Shield 1.3.2 | value |
|---|---|
| the session a Link Trade search hosts | game mode 60001, maximum 2, versions 7 and 7, no application data, no attributes |
| its browse when the search starts | five requests, game mode 0, flags 0x2, maximum participants 4..4, result size 1 |
| a hosting Sword leaving its joiner | MULTI_MIGRATION_START (0x49) on mesh port 1, then silence 5.2 s later |

A Link Trade search's own session does not match the browse it sends when it starts.
`bin/swsh_connect.py --lan auto` (the app's Trade (LAN mode)) browses every local /24 with
`--preset trade`'s flags and completed a trade with a retail Sword on a Switch 2 over Wi-Fi and with
the emulated console; it takes the console's silence as its departure (`--lan-quiet`, default 3 s),
which ended the retail run 3.1 s after the player backed out. `bin/swsh_host.py --lan` hosts a session that
our joiner trades with; the emulated Shield took its replies for a 2- or 4-player session of game
mode 60001 or 0 and sent nothing to its station port.

## Operational notes

- Never pass `--verbose` live; use `--capture FILE`.
- The console's channel changes between sessions (1 and 6 seen); the scan keeps the busiest
  ([channels](ldn.md#channels)).
- `0x2D0` (allocations at `0x006a970c`, `0x006a9740`) is the session singleton's size
  (`0x006b4410`, global `main+0x02616758`), a 720-byte struct unrelated to a Wonder Card.

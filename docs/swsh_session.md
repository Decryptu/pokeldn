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
Scarlet/Violet row, one character off Legends: Arceus (`HGhG` here, `HGHG` there).

    0x006c3eb4  adrp x1, #0x203f000 ; add x1, x1, #0xf04    the literal
    0x006c3ec0  add  x0, sp, #0x10                          the LdnCreateSessionSetting
    0x006c3ec4  mov  w2, #0x40                              64, not a NUL-terminated length
    0x006c3ec8  bl   #0x1790450                             its passphrase setter

`nn::pia::local::LdnCreateNetworkJob` holds the passphrase at +0xC4, its length at +0x104, the
`NetworkConfig` intent at +0xB8 (local communication id) and +0xC0; it copies the passphrase to
`SecurityConfig+4` (`0x01797280..0x01797284`) just before `nn::ldn::CreateNetwork` (`0x017972bc`).
`LdnBackgroundProcessJob` requires a length of 16..64.

## The Pia game key

    p1frXqxmeCZWFv0X

Sixteen ASCII bytes at `0x01c3dc87`, used unchanged by three call sites (the wiki's Sword/Shield row):

    0x006ca914  mov  w8, #1 ; str w8, [sp, #0x18]     crypto enabled
    0x006ca91c  adrp x8, #0x1c3d000 ; add x8, x8, #0xc87
    0x006ca924  ldp  x9, x8, [x8]                     the 16 bytes
    0x006ca938  stur x9, [sp, #0x1c]                  -> the setting's key field
    0x006ca93c  bl   #0x183fd10                       create/join

## Reading the cartridge

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program
    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca 87e41bc8 --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0x1900fc0 --rodata 0x1901000:0x24da168

`xci_read.py` reads the XCI in place; `main` is text 0..0x1900fc0, rodata to 0x24da168, data to
0x2635f38. Method: [Reverse-engineering a Switch title](switch_re.md).

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

484 of 484 retail packets authenticated, source id 0 on each. Session param and network id change
per session. A second path, `0x0179bff0` -> `0x01774f40`, seeds AES-GCM over the session's two
64-bit values; a local trade needs only the advertisement.

## Taking a seat

    POKELDN_RADIO=esp32:auto ./.venv/bin/python bin/swsh_join.py --keys PROD_KEYS --scan-only

scans a hosting screen and writes each advertisement to `scratchpad/swsh_net_facts.json`;
`--pw-mode raw` is the default.

| screen | local communication id | version | scene | app version |
|---|---|---|---|---|
| Link Trade | `0x0100ABF008968000` (Sword's) | 4 | 60001 | 7 |
| Mystery Gift local wireless | same | 4 | 65535 | |

Shield uses Sword's id: it builds `0x0100ABF008968000` with `mov`/`movk` at `0x011083e0..0x011083f0`
into `sp+0x88` (`0x01108404`; its path to the LDN intent is untraced), and its `control.nacp`
lists `LocalCommunicationId[0] = 0x0100ABF008968000`, `[1..7] = 0x01008DB008C2C000`.

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
    0x1F 266 the player profile, as in the trade snapshot at 0xAEC but sampled at another moment
             ([the protocol page](swsh_protocol.md#the-player-profile)); zero to the end

`Connect failed with status code 1` is a refused association; the next attempt on the same search
can associate. A searching Sword advertises two networks under one comm id: its Y-Comm beacon at
scene 65535 and, past the second message, its matching network at scene 60001. A station on the
beacon reached the trade box in 0 of 16 joins (mesh join refused with reason 1, or the advertisement
changed under it); `bin/swsh_connect.py` joins scene 60001 only and rescans until it appears. Over the
ESP32 board, 6 of 8 joins on scene 60001 reached the trade box; the other two failed to associate. After pokeldn's station left a
console-hosted session, the console's advertisement was gone within a minute; what ends it is
unread. After association the console broadcasts Pia to `169.254.x.255:12345` (about ten packets a
second measured); the screen shows nothing. On a
Linux card, status 1 with no auth frame is cfg80211 missing the BSS; `iw dev IFACE scan` primes it
(`--dwell 2.5`).

## How a searching Sword finds a partner

On the Y-Comm screen every console hosts a beacon network at scene 65535 and browses about once a
second (`0x006c3630`: hosts `0x006c3840`, browses `0x006c3770` with criteria from `0x006c4550`,
`0x0183fac0`, on comm id and network type only). Records passing the CRC and version gate
(`0x006c1be0`) reach the nearby-player registry (`0x0110f270`), which drops its own (device id at
advertise 0x1F and account uid at 0x2F, `0x0111b160`) and any without a network id and scene pair
(`0x0110f2d4`). Nothing here joins.

Link Trade, then the plain trade, shows two messages, each waiting for A. After the second ("you can
cancel the search..."), `0x00fba940` calls `SetMode(comm, 2)` (`0x01096d10`); `0x01095f10` walks
states 0, 5, 3, 4, 6 within a second, and state 6 calls `StartRandomMatching` (`0x010fcff0`) with
scene 60001 (`0x01096730`). The overworld shows "Recherche...". A console left on the first message
never calls `SetMode(comm, 2)` and never matches.

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
tables the joiner before it speaks Pia.

    a9fe0e01 3039 ... 00      169.254.14.1:12345   station 0, the console, ranking 0
    a9fe0e02 3039 ... 01      169.254.14.2:12345   station 1, the seat, ranking 1

The host repeats an update session until each station acks it (0x21). An ack carrying its sequence
id stops the rebroadcast (within 13 ms measured); an ack with another sequence id does not
(`bin/swsh_connect.py --seq-delta`). Header byte 0x05 and the IV's source id are 0, as in the
console's own (`--station-sweep` walks others).

## The Pia session object

`[[0x02616a30]]` (also `[0x02630f40]`), where the trade code reads station ids, is Pia's session
object: 0x270 bytes, no vtable, allocated once by `0x0183ddb0` (`0x0183dfd4`) from `0x006a8644`.
Backends come from the network factory (`[x20+0x60]`, `0x006a8600`): `+0x178` slot `0x240/8`,
`+0x188` slot `0x290/8`, `+0x168` slot `0x248/8` (`0x0183e074`), `+0x170` slot `0x248/8` when slot
`0x1b8/8` is true; byte `+0x162` selects. On LDN the factory is `LdnNetworkFactory`, whose slot 73
(`0x01791080`) builds a 0x7220-byte `LdnMatchmakeSession` (vtable from GOT `0x0262fbd0`).

| field | written by | value |
|---|---|---|
| `+0xf0` | `0x018418a0` (`0x01841918`) | this console's own station id |
| `+0xf8` | `0x018418a0` (`0x01841990`) | the id of the station at the mesh's host index, the byte `[[0x0262f7b0]]+0xab` (`0x017bbfe0`); skipped when `[obj+0xd4] == 4` |

`0x018418a0` runs after `0x018410e0` on create (`0x018394d8`) and join (`0x0183d9b0`). The mesh host
index `+0xab` (own index `+0xac`) is written by creation (`0x017b092c`, equal to `+0xac`), the join
response (`0x017b4e4c`), resets to `0xfe` (`0x017bb820`) and to `0xfd` with `+0xac` (`0x017b99a0`),
and host migration: `0x017ca454` (from `LanProcessHostMigrationJob`,
`LocalProcessHostMigrationJobNew`, Nex) and `0x017caf48`.

`MeshEventListener` slot 2, `0x01843580` (switch on `[x1]`, table `0x02083fe8`), also writes `+0xf8`:

| event | store |
|---|---|
| 1 | the backend's slot 30 (`0x01844bc4`), then `0x018412a0(obj, 2, id)` on a change |
| 2 | the id `0x017d6080` returns (`0x01844a74`); the backend's slot 30 (`0x01844edc`); `0x01844f60` |
| 3 | zero, with `+0x100` (`0x0184415c`, `stp xzr,xzr`), when `[obj+0xd4] != 3` |

The stores to `+0xd4` in `0x01837000..0x01850000`:

| value | site |
|---|---|
| 0 | `0x018399c8` |
| 1 | `0x01837c1c`, `0x018396ac`, `0x0183dbbc` |
| 2 | `0x01837a8c`, `0x01839474`, `0x0183cda8`, `0x0183d94c` |
| 3 | `0x01839f7c`, in `0x01839cc0`, whose callers are `0x0177d8a0`, `0x0180afe0` and `0x0180bd0c` |
| 4, else 2 | `0x0183a2cc`, in `0x0183a040`: 4 when `w8 - 6 < 3` (`0x0183a2b8..0x0183a2c8`); callers `0x0177e8a8` and `0x01818b68` |

The callers of `0x01839cc0` belong to `LanMatchJointSessionJob` (`0x0177d8a0`) and
`NexMatchJointSessionJob` (`0x0180afe0`, `0x0180bd0c`). The callers of `0x0183a040` belong to
the same two jobs (`0x0177e8a8`, `0x01818b68`). Ordinary LDN create and join set mode `+0xd4` to 2.

Event 2 reaches either host-id store only when `0x01841350` and `0x01769ec0([obj+0x38])` are
false and the unsigned value `[obj+0xd8] - 2` is at least 6 (`0x01843980..0x018439a4`). Mode 2
selects the new station's constant id from `0x017d6080`; mode 4 selects the joint-session branch
containing the slot-30 store. The event-2 slot-30 store therefore requires joint-session mode 4.

Event 1's slot-30 store requires the departing station's id to match `+0xf8` and differ from `+0x100`,
`0x01840b90(obj)` to be true, state `+0xd8 == 1`, and `[mesh+0x64] == 0`
(`0x01844614..0x01844638`, `0x01844654..0x01844664`). `0x0184a4b0` must find a mapping whose
output word is non-zero and differs from the word at `obj+0x180+4*[obj+0x162]`.
If the mesh controller's byte `+0x84` is set, its byte `+0xc0` must also be set
(`0x01844b54..0x01844b9c`). The new slot-30 value must differ
from `+0xf8` before it is stored. On LDN, `0x01840b90` tests the local mesh controller's
`+0x281` and `+0x234` through virtual slots `+0xb0` and `+0xa8`. Successful local-controller
construction sets both bytes to 1 (`0x017a06ac`, `0x0183c228`); the remaining event-1 gates
still apply. Backend type alone does not exclude this branch.

`LdnMatchmakeSession`'s slot 30 (`0x017a23d0`) returns `0xff` when `[this+0x18]` is null, otherwise
`0x017672d0` of the 16-byte address at `[[this+0x18]+0x18]+0x2c0+8`: 0 when all zero, its first four
bytes when the last twelve are zero, error `0x10c07` otherwise. Slot 28 (`0x017a23b0`) is the virtual
call `0x018407f0` makes.

`0x018407f0` is true when `+0xf0` is non-zero, equals `+0xf8`, and the backend's slot 28 agrees:
with the create and join values, on the console hosting Pia's mesh. A console hosting a trade climbs
the confirmation ladder on commands; one that joined pokeldn's host follows the shared value
([the pump](swsh_trade.md#the-pump)).

## Reaching the game layer

Every layer below the game works both ways ([The Pia layer](pia.md)): Local Protocol 0x24, station
handshake 0x14, mesh join 0x18, RTT 0x58, reliable windows 0x7C and 0x80.

Left alone, the console repeats `61 00 00 00 0a 00`, a ping (about four a second); 0x80
asks for ack id 1 once a second, 0x7C stays silent. `bin/swsh_connect.py --send-data HEX
--send-protocol 0x7c` sends application data (`reliable4.build_data_message`, byte-exact with the
console's own; five silent receive checks: [version 4](pia.md#version-4)). Pass signal: the 0x80 ack
id moves off 1; 0x7C acks at all.

## The ping handshake

A payload is a four-byte little-endian message id and a protobuf body. A whole handshake carries
these five and no others (the right column counts each in one captured handshake):

    0x7C  61000000 0a00      97 SyncPingDataHolder, field 1 ping {}           x20
    0x7C  61000000 1200      97, field 2 pingReply {}                          x2
    0x7C  61000000 1a00      97, field 3 pingSynced {}                         x3
    0x7C  60ea0000 0a00      60000 BlockDataHolder, field 1 result {}          x2
                             (Result { bool isBlocking })
    0x80  60ea0000 12020801  60000, field 2 imReady { isReady: true }          x2

(`gflnet.p2p.sync.ping.pb`, `gflnet.p2p.block.pb`.) Answering walks the game in five steps:

    1  answer the ping continuously   --send-data 610000000a00 --send-mirror --send-count N
    2  ack every reliable window      0x7C, 0x18 port 1, 0x80; one unacked window kills the mesh
    3  answer `result{}` on 0x7C      the mirror is per protocol
    4  answer imReady on 0x80         --send2-data 60ea000012020801
    5  the console sends its party on 0x84

- The ping must be answered continuously: a single answer draws one `pingReply` and the game returns
  to pinging.
- A `pingReply` sent before the console asks for one stops its heartbeat.
- `imReady` sent on 0x7C in answer to `result{}` draws no 0x84: the answer goes on 0x80.
- A late-acked message is resent and can arrive after its successor (`pingReply` at sequence 9 after
  `pingSynced` at 10). Only a sequence above the newest replaces the current message; answering the
  resend loops on `pingReply` and `imReady` never comes.

`bin/swsh_connect.py --sync-answers` answers `trade.SYNC_ANSWERS` where it has a rule, echoes per
protocol elsewhere, and prints each unruled payload (after the answer it caused; read the ownerId).

## Leaving

A Sword leaving a trade session sends box command 3 and, about 0.77 s later, starts the Pia leave
for its role. Each step waits for a reply and falls through on a timeout when none comes.

A joined Sword leaving a host:

| step | the Sword sends | the host owes | unanswered |
|---|---|---|---|
| mesh leave | LEAVE_REQUEST `04 <own index>`, 0x18 port 1, reliable, once | LEAVE_RESPONSE `08 <host index>` | 5.0 s |
| station disconnection | `03` on 0x14, every 0.5 s | `04` | 8 requests, 3.6 s |
| LDN | leaves the network | | |

Eleven host captures (retail Sword and emulated Shield, the host answering neither) measure 9.0 to
9.1 s from LEAVE_REQUEST to the LDN leave.
With `08 00` twice and `04` answered, a retail Sword sent one `03` 0.04 s after LEAVE_REQUEST and
left the network 0.14 s after it.

- The version-4 host handler `0x017c19a0` (mesh type 4, table `0x02081564`) sends `08` and its own
  index through `0x017c2450`, two unreliable copies (`0x01851200` with the no-bundle flag 0, then
  1), and drops the station from the mesh. The leaver's handler `0x017c0d44` takes it only when
  [1] is the mesh host's index.
- The 0x14 handler `0x017c6110` (type 3, table `0x02081804`) answers the one byte `04` to the
  sender and marks it gone; the type-4 handler `0x017c5fcc` clears the leaver's wait.

`pokeldn/ldn/host4.py` answers both.

A hosting Sword leaving its client (it is the LDN access point):

| step | the Sword sends | the client owes | unanswered |
|---|---|---|---|
| mesh migration | MIGRATION_START `44 00 01` ([host migration](swsh_trade.md#host-migration)) | MIGRATION_FINISH and an UPDATE_MESH naming itself host, from the named station | 5.0 s |
| local session | its update session (0x24 type 0x11) with the host-migration byte 1 and a new sequence id, about every 0.11 s | the 0x21 ack for that sequence id | 10.0 s |
| destroy network | START_HOST_MIGRATION `01 13 00..` (16 bytes), every 0.33 s | leave the LDN network | 10.0 s |

Measured on a retail Sword, from MIGRATION_START to its last packet:

| the client answered | mesh step ends | last packet |
|---|---|---|
| nothing (5 captures) | 5.0 s | 25.0 s |
| MIGRATION_FINISH and UPDATE_MESH as host, repeated | 0.1 s | 20.1 s |
| MIGRATION_FINISH (acked), the ack, the leave | 5.0 s | 5.07 s |
| MIGRATION_FINISH, UPDATE_MESH as host, the ack, the leave | 0.07 s | 0.17 s |

With the finish alone acked, the console went on acknowledging the client's data for 4.8 s; with
the UPDATE_MESH it went quiet 0.07 s after the start.

- `LocalDestroyNetworkJob::WaitUntilAllClientsDisconnection` (`0x017acd70`) counts the network's
  connected nodes (`0x017a9b20`, eight slots) and destroys it when only the host remains or after
  `0x2710` ms, re-sending START_HOST_MIGRATION every `0x12d` ms (`0x017acbd0`, `0x017a8bb0`).
- The update session is re-sent by `LocalResendMessageJob`; an ack (handler `0x017a9250`, local
  type 0x21) clears the sender's bit only when its sequence id equals the message's
  (`0x017aed10`). What bounds the 10.0 s local-session step in the binary is unread.
- START_HOST_MIGRATION carries no sequence (its serializer `0x017abc60` writes 0 at 0xC) and has no
  resend job: nothing acks it.

`bin/swsh_connect.py --answer-migration --update-mesh --leave-with-host` (in `--preset trade`) sends
the finish and an UPDATE_MESH as host, acks the host-migration update session and leaves the
network on START_HOST_MIGRATION.

## Operational notes

- Never pass `--verbose` live; use `--capture FILE`.
- The console's channel changes between sessions (1 and 6 seen); the scan keeps the busiest
  ([channels](ldn.md#channels)).
- Linux card: a hard-killed run leaves the `ldnclient` vif (later attempts look like refusals); an
  interface left up holds the channel (`Errno 16 Device or resource busy`).
- `0x2D0` (allocations at `0x006a970c`, `0x006a9740`) is the session singleton's size
  (`0x006b4410`, global `main+0x02616758`), not a 720-byte Wonder Card.

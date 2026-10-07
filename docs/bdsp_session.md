---
title: Joining and the Pia layer
parent: Brilliant Diamond and Shining Pearl
nav_order: 1
---

# Joining a BDSP session, and what is under the encryption

## The advertisement

    local_communication_id  0100000011d90000
    scene_id                4352 (0x1100) Union Room; 5120 (0x1400) Union Room entered with a
                            password; 12608 (0x3140) Grand Underground
    version                 4
    channel                 a 2.4 GHz channel, band 2, chosen per session (6 in the capture)
    accept_policy           ALL
    participants            1/8
    application_data        17 bytes

The comm id is Brilliant Diamond's title id, shared by Shining Pearl (`010018e011d92000`). The
advertisement decrypts with `prod.keys` alone (`tools/ldn/ldn_scan.py`). The 17 bytes of application
data are Pia's LDN advertisement header ([The wireless layer](ldn.md)), 16 bytes, then one byte of
application data; the CRC32 field is 0 in a room opened with no password.

A room entered with a password carries the CRC32 of the password's ASCII digits there, little-endian
(00000000 -> `0xC0088D03`), and scene id 5120. `bin/bdsp_connect.py` joins such a room unchanged;
`bin/bdsp_host.py --password 00000000` advertises both, and a console entering with that password
joins and trades. The console checks at three stages (1.3.0 `main`):

| stage | code | check |
|---|---|---|
| scan | `NetworkHelper.CreateUnionGameMode` `0x224e630`; `nn::ldn::Scan` `0x16be184` | the scene id is the game mode (0x1100 plain, 0x1200 group, 0x1400 password) and a scan filter (flag 0x25: comm id, network type, scene id); another scene never reaches the game |
| browse | `LdnMatchmakeSession` `0x16c1abc`; `GameState_BrowseSessionAfter_LocalRandom2` `0x273f804` | a room is password-protected when the u32 at +0x04 is non-zero; a console with a password skips an unprotected room and one without skips a protected room |
| connect | `LocalMatchJoinSessionJob` `0x16c36c8`; the check `0x16b8890` | the joiner computes `crc32` of its typed password (`0x1719204`); +0x08 must be 8, and a CRC other than the advertised u32 at +0x04 fails with 0x6c51 before `nn::ldn::Connect` |

The host writes that header in `LdnProtocol` `0x16b6a14`: network id, the password's CRC32, the byte
8, the session parameter. No message carries the joiner's CRC to the host: a console typing the
wrong password sends the host nothing and opens a room of its own. A password longer than eight
characters keeps eight for Pia and moves the rest into application data behind `INL1`
(`IlcaNetSession.SettingSet` `0x2735f14`).

## The passphrase

    WirelessStrongCryptoKey2021

Used raw: 27 bytes, neither padded nor hashed (LDN accepts 16 to 64 bytes with an explicit length).
The game hands it to `nn::ldn::CreateNetwork` in an `nn::ldn::SecurityConfig`; it never reaches Pia's
crypto.

## Taking a seat

`bin/bdsp_join.py` scans, associates and reports the participant table:

    participant 0: ip=169.254.54.1  mac=48f1eb209b22                 <- the console
    participant 1: ip=169.254.54.2  mac=58d8122149a2  name=b'POKELDN' <- the client

The console assigns the IP. The Union Room's eight seats are the LDN `max_participants`. An LDN seat
sits below the game: nothing appears on screen, and it is not a seat in the Pia session.

`Connect failed with status code 1` is a failed association; from the ESP32 board about one attempt
in two fails, so retry before diagnosing. A console in the room can stop advertising with no change
on screen. Re-entering the room opens a new network (new channel, SSID and
session parameter), which the key derivation handles live. A receiver on the LDN interface must
filter its own source IP: broadcasts loop back.

Unauthenticated Pia is dropped silently, with no error and no loss of the seat.

## What is on the wire

Before a station acknowledges it, a hosting console broadcasts its update session to
`169.254.x.255:12345` every 100 ms, addressed to `dst_var = 0`; every datagram of the capture is 176
bytes:

    32ab9864 89 00000000 11bac90d 0000 00 f5a83bd383ce712d 59baa5cbc320cb56 <144 bytes>
    magic    v  dst=0    src      pid  f  nonce (a counter) tag              ciphertext

Version byte `0x89` is encrypted, version 9: Pia 5.27-5.45; the reliable protocol's version 3 narrows
it to 5.31-5.43. The header, message framing and transport protocols are on
[The Pia layer](pia.md). `pokeldn/ldn/pia5.py` round-trips 674 captured packets byte-identically.

## The key hierarchy

    cryptoKeyDataSeed  9918bd0fdcfa65779918bd0fdcfa6577    from global-metadata.dat
    game key           9900bd0cdcfa65639918bd0fc7fa6577    = seed derived with version 199
    session param      0x36dee059                          advertisement +0x0c, little-endian
    session key        7b182cb087eeabd228a2efd91a8be147    = AES-ECB(game key) over 16 SEAD bytes
    network id         b4c85cf8                            advertisement +0x00, little-endian
    source MAC         48:f1:eb:20:9b:22
    crc32(netid||MAC)  0xda291352
    IV (first packet)  da29130df5a83bd383ce712d

All 674 packets of the reference capture authenticate, and re-encrypting each plaintext reproduces
the console's ciphertext and tag byte for byte.

### Where the seed lives

`INL1.IlcaNetSessionSetting`'s constructor sets the defaults:

    IlcaNetSessionSetting..ctor
      byte[16] cryptoKeyDataSeed  <- RuntimeHelpers.InitializeArray(array, fieldHandle)
      string   wirelessCryptoKey  <- the "WirelessStrongCryptoKey2021" literal
      ulong    localCommunicationId = 0x0100000011d90000

The field handle resolves to `<PrivateImplementationDetails>.33F804682DF9E210AABDC4D939CBCD380EC7517F`,
the SHA-1 of the sixteen bytes. The blob lives in `global-metadata.dat`'s field-default-value
section, in neither the executables nor the RomFS; the method is on
[Reverse-engineering a Switch title](switch_re.md).

### The published key is the seed, derived

    seed (metadata)   9918bd0f dcfa6577 9918bd0f dcfa6577
    published key     9900bd0c dcfa6563 9918bd0f c7fa6577
                        ^^   ^^         ^^         ^^        bytes 1, 3, 7, 12

The game overwrites bytes 1, 3, 7 and 12 from the local communication version, 199 for 1.3.0 (the
advertisement's `app_version`); `ldn_game_key(seed, 199)` reproduces the published key.

### The session key

From `nn::pia::local::LocalProtocol`:

    seed  = a u32 session value held at LocalProtocol+0x5b0
    state = for i in 1..4:  prev = ((prev ^ (prev >> 30)) * 0x6C078965 + i)
    rnd   = four consecutive xorshift128 draws (shifts 11, 8, 19) -> 16 bytes, little-endian
    key   = AES-128-ECB(game key at LocalProtocol+0x5bc).encrypt(rnd)

The generator is SEAD's RNG; `pokeldn/ldn/sead.py` implements it.

### The GCM nonce

The IV is built by the stream object, one per network family:

    nn::pia::local::LdnOutputStream::vfunc3     0x16b39c4      the LDN sender
    nn::pia::local::LocalOutputStream::vfunc3   0x16bca80
    nn::pia::lan::LanOutputStream::vfunc3       0x16a0f80
    nn::pia::nex::NexOutputStream::vfunc3       0x16eca0c

Each takes `(this, buf, buflen, packet)`; the sender calls it at `PacketWriter+0x948`, the receiver
at `PacketReader+0xc8`.

    IV[0..3]  = u32be( crc32(ten bytes) )
    IV[3]     = overwritten with (packet.source_variable_id & 0xFF)
    IV[4..11] = the eight-byte header nonce, copied from packet+0x1b

The CRC at `0x1719204` is ordinary CRC32 (`0xEDB88320`) over the network id (little-endian, from
advertisement +0x00 via the network object's +0x450) and the source MAC from a station record. The
source MAC cannot be recovered from the packet being decrypted.

## The Local Protocol, decoded

Every packet of the reference capture carries the same message:

    presence 0x7f  flags 0x11  size 121  protocol 36  port 0  destination 0

It is the Local Protocol's `0x11` update session, rebroadcast every 100 ms until every station
acknowledges it:

    local message header  version 1, type 0x11, size 73
    sequence id           4
    network id            8b4a3b22        random, not the advertisement's network id
    host variable id      11bac90d        the same value as the packet header's source variable id
    host constant id      0000 48f1 2022 9beb
    allow participating   1
    node 0                169.254.54.1:12345          the console
    node 1                169.254.54.2:12345   01     the client
    nodes 2-7             empty, marked 0xff
    host migration state  0

Eight nine-byte node slots, the room's eight seats, then one byte. The host constant id, read
little-endian, unpacks by the LDN rule (`mac[2] << 56 | mac[4] << 48 | mac[5] << 40 | mac[3] << 32 |
mac[1] << 24 | mac[0] << 16`) to the scanned MAC `48:f1:eb:20:9b:22`. The Pia message header is
big-endian, the Local Protocol's fields little-endian, a local address inside them big-endian again.
The presence byte 0x7F sets three bits that name no field in Pia 5.27-6.30.

### The ack

The 20-byte ack is on [The Pia layer](pia.md#the-local-protocol-0x24). The framing that works is
the host's own: a broadcast with packet `dst_var` 0 and message destination 0; the unicast framings
are untested. The first ack stops the updates: in the capture, 42 updates went 100 ms apart and the
ack came 34 ms after the last. The console then sent nothing while the station sent nothing more.

## Joining the mesh

The three handshakes and the ack rule are on [The Pia layer](pia.md#joining-a-mesh). BDSP's
addresses:

| what | where |
|---|---|
| station protocol receive dispatcher | `0x0154e848`, table `0x3e6b38f` |
| connection request deserializer | `0x0154ebd0` |
| result mapping from internal errors | `0x0154f5e8` |
| protocol version lookup by id | `0x0159b850`, returns 0 for an unregistered id |
| read a mesh message's ack id | `0x01542db8` (`size - 4`, big-endian) |
| send the ack (8 bytes, on 0x14) | `0x01550324`, `mov w3, #8` |
| join REQUEST handler, host side | `0x0154b790`, `0x0154b868` |
| join RESPONSE handler | `0x0154b984`, `0x0154b9a4` |

`0x01550324` belongs to the MeshStationProtocol at `session + 0xa0`. The join response handler is the
pointer `JoinMeshJob` stores at `MeshProtocol + 0x128` (`0x0154e5c4`) after sending the join request.

The console registers nine protocols ([measured](#measurement-methods)):

    0x14 Station v2   0x18 Mesh v3      0x1c SyncClock v0
    0x24 Local v0     0x58 RTT v3       0x68 Unreliable v1
    0x7c Reliable v3  0x94 Session v1   0xa4 MonitoringData v0

The four at version 0 cannot be told from unregistered by a version probe.

The join response for a two-station mesh:

    stations 2, host index 0, joiner index 1, max_active 8, update counter 0
    station 0   the console
    station 1   the client: its own station location and ids, read back

Within a second the console sends RTT (0x58) and reliable (0x7c) traffic. Result 7 means the
variable id is already one of its stations.

### The Session Protocol (0x94)

`nn::pia::session::SessionProtocol` (1.3.0 `main`, vtable `0x4b5da50`) carries the joint-session
feature and is inert on LDN. Pia's session start-up builds it [`0x157c66c`] unless a settings byte
(+0x38 behind GOT `0x4c4b850`) is set, stores it at session+0xC8 and gives it one
`transport::ReliableSlidingWindow` per other station [`0x1581938`]. Every handler of its dispatcher
[`0x15820b8`, jump table `0x3e6b986`] returns when the joint-session job (session+0x70) is null, and
on LDN it always is: `LdnNetworkFactory`'s slot 61 [`0x16b30ac`] returns null, and the only other
stores are nulls (`0x157c618`, `0x157d0e8`). Lan and Nex factories build `LanMatchJointSessionJob` and
`NexMatchJointSessionJob`.

Its windows are the game stream's `ReliableSlidingWindow` [constructor `0x159dab4`] with two-slot
rings, protocol 0x94, port 1 (`0x159de54(window, 2, 2, 0x94000001)`); receive is slot 10
[`0x1581c98`]. Nothing before the window reads session+0x70, so a valid reliable 0x94 message (first
one flagged `is initialized`, sequence below base plus two) is acknowledged, then dropped by its
handler. No 0x94 has been captured or sent.

## Hosting

A console entering the Union Room joins any room with a free seat before opening its own
(`matchingMode` `IlcaNetSessionInitMode.Random`, `localRandomMatchmakeHostWaitTime` 25,
`localRandomMatchmakeTimeUp` 270). `bin/bdsp_host.py` hosts one, and a console entering the Union
Room joins it; `pokeldn/bdsp/host.py` holds the host side. A retail room's advertisement:

    LDN protocol         1 (AES-CTR advertisement)
    frame version        4
    security mode        1
    scene_id             4352 (0x1100)
    app_version          199
    accept policy        ALL, 1/8
    application_data     17 bytes, the Pia header with a fresh network id and session
                         parameter, then one zero byte

What a host sends, each rebuilt byte for byte from a retail host's (`tests/test_bdsp_host.py`):

| step | message | framing |
|---|---|---|
| a station associates | Local Protocol update session, every 100 ms until acknowledged, the joiner as node 1 with ranking 1 | broadcast, `dst_var` 0 |
| its connection request | an accepted connection response, 949 bytes: the request layout with type 2, the host's nine protocols, its station location, the advertised network id, one PlayerInfo, zero-filled, the ack id last | `dst_var` 0, flags 0x01 |
| its mesh join request | the station ack of the request's ack id, then the join response (two stations, `max_active` 8, the joiner's own location bytes in its entry) | `dst_var` 0 |
| the join response acknowledged | `NetJoinData` on the reliable window, sequence 1, flags 0x0F | `dst_var` the joiner's |
| from then on | update mesh (556 bytes) every second, RTT requests, `NetCharacterStateData{0, 0}` on 0x68 | `dst_var` 1, destination 0xFFFFFFFF |

The host's station location has no public address and zero NAT fields, 36 bytes; the joiner's has
both, 40. The host's station entry has index and join order 0, the joiner's 1.

The joiner sends Sync Clock (0x1C) requests about once a second from the acknowledged join response;
the host answers with the request's tick and the mesh clock in milliseconds. A joiner whose Sync
Clock requests go unanswered deauthenticates and re-associates repeatedly while the screen shows
"communication en cours". Departures came about ten seconds after the first request; the timeout is unread. Answered, it sends `NetJoinData` and requests 0x04 and 0x23, as a retail
host does, and from there the room is symmetric: the approach, the greeting and
[the trade](bdsp_trade.md) run unchanged with the console as joiner.

## Leaving

A console leaving the room runs Pia's mesh leave as a joiner and its host-migration leave as a host.
Both open on the mesh protocol's reliable window, 0x18 port 1, under the reliable header with
sequence 1, and both wait on an answer sent unreliably on port 0. A retail Pia sends each answer
twice, the second in a packet of its own. The mesh dispatcher is `0x0154ac94` (jump table
`0x3e6b25a`, types 0x40 to 0x4A behind `0x3e6b35c`).

| the console | sends | is owed | handler that ends its wait |
|---|---|---|---|
| joiner, `LeaveMeshJob` | `04 <own index>`, the leave request | `08 <host index>` from the host | `0x0154baf8`, clears job+0x7c |
| joiner, then | station disconnection request, `03` on 0x14 | `04` | |
| host, `LeaveWithHostMigrationJob` | `44 <host index> <new host index>`, one to each station | `48 <station index>` from every station | `0x0154b068`, clears job+0x6e[index] |

The host's leave request handler `0x0154b9e0` refuses a size other than 2, index 0xFD and its own
index, answers through `0x0154c860` (`08` and the host's own station index) and drops the station.
`LeaveMeshJob::WaitLeaveResponse` `0x0155fd2c` moves on when the response clears its flag or its
deadline passes. `LeaveWithHostMigrationJob::WaitMigrationResponse` `0x015607bc` waits while any
present station's flag is set; a station that left clears its own.

Measured with nothing answered:

| the console | first message | then | gone |
|---|---|---|---|
| joiner leaving a hosted room (4 captures) | leave request every 0.125 s for 4.9 to 5.0 s | disconnection request every 0.5 s, from 3.6 s (one capture ran to the end) | deauthentication 9.0 s after the first request, in that capture |
| host leaving its room with one station joined (4 captures) | migration start every 0.125 s for 4.9 s | update session, sequence +1, migration state 1, every 0.11 s for 10 s; then Local Protocol 0x13 (start host migration) every 0.3 s for 10 s | its network closes 25.3 s after the first migration start |

Answered (`08 00` twice and `04`), a retail joiner leaving sent one disconnection request 0.06 s
after its leave request and deauthenticated 0.15 s after it.
Answered (`48 01`, the update-session ack, the leave on 0x13), a retail host leaving its room sent
0x13 0.11 and 0.45 s after its migration start (2 runs) and closed it.

The 0x13 phase is `LocalDestroyNetworkJob::WaitUntilAllClientsDisconnection` `0x016b95b8`. It sends
0x13 again whenever 301 ms have passed since the last send (`job+0x68`) and ends on the first of: the
request's cancel byte set (to `WaitForCancel` `0x016b9330`); the count of present stations from
`0x016b014c` equal to 1 (`0x016b9614`); more than 10000 ms since the previous state,
`WaitUntilAllClientsReceiveUpdateSessionMessage` `0x016b936c`, stored `job+0x70` (`0x016b9644`). The
last two go to `StartDestroyNetwork` `0x016b950c`, which closes the network. A station that leaves
ends the phase on the next update; a station that stays holds it for the full 10 s. The previous
state leaves when `[[protocol+0x4f0]+0x5c]` is set (`0x016b0888`) or after 10001 ms.

`pokeldn.bdsp.session.answer_departure` builds both answers; `bin/bdsp_host.py` answers a leaving
joiner and its disconnection request, and `bin/bdsp_connect.py` answers a migration start, acks every
later update session and leaves the network on 0x13 (`--no-leave-on-host-migration` stays).

Leaving the trade box sends no departure message: the box's close callback `TradeSelectPokeModel$$CheckComplete`
[1.3.0 main 0x1c26810] sends `NetDataCurrentFlowCancelData{0}` (0x25, `SendCancel` 0x1c26bf0) and
`UnionTradeManager$$Cancel` [0x1c33780] sends `NetCharacterStateData{0}`, both in one packet, with
no wait on the partner.

## Measurement methods

- The console answers a connection request only when the protocol count matches its own; sweeping
  the count gives 9. An unregistered protocol expects version 0, so a version of 1 against it fails,
  and bisection reads any protocol's version.
- The signal must be a reply; silence is as often a lost packet. A reliable window acknowledges
  data it accepts, so send data and sweep only the sequence id.

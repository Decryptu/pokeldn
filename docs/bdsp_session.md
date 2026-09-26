---
title: Joining and the Pia layer
parent: Brilliant Diamond and Shining Pearl
nav_order: 1
---

# Joining a BDSP session, and what is under the encryption

## The advertisement

    local_communication_id  0100000011d90000
    scene_id                4352  (0x1100) in the Union Room; 5120 (0x1400) in the Union Room
                            entered with a password; 12608 (0x3140) in the Grand Underground
    version                 4
    channel                 6, band 2 (2.4 GHz)
    accept_policy           ALL
    participants            1/8
    application_data        17 bytes

The comm id is Brilliant Diamond's title id; the console was running Shining Pearl
(`010018e011d92000`). Paired versions advertise one shared `local_communication_id`, so it does not
identify which version is hosting.

The advertisement decrypts with `prod.keys` alone. `tools/ldn/ldn_scan.py` sees the session before
anything about the game is known.

The 17 bytes of application data parse against Pia's LDN advertisement layout
([The wireless layer](ldn.md)), with the CRC32 field reading 0 (the room was opened with no password)
and the header size reading 16 against a 17-byte blob, so one byte is application data.

A room entered with a password carries the CRC32 of the password's ASCII digits there, little-endian
(00000000 -> `0xC0088D03`), and scene id 5120 in place of 4352. `bin/bdsp_connect.py` joins such a
room and trades with no change; `bin/bdsp_host.py --password 00000000` advertises both and a console
entering with that password joins it and trades.

A console entering with a password checks both fields, at three stages (1.3.0 `main`):

| stage | code | check |
|---|---|---|
| scan | `NetworkHelper.CreateUnionGameMode` `0x224e630`; `nn::ldn::Scan` `0x16be184` | the scene id is the game mode (0x1100 plain, 0x1200 group, 0x1400 password) and a scan filter (flag 0x25: comm id, network type, scene id); another scene never reaches the game |
| browse | `LdnMatchmakeSession` `0x16c1abc`; `GameState_BrowseSessionAfter_LocalRandom2` `0x273f804` | a room is password-protected when the u32 at +0x04 is non-zero; a console with a password skips an unprotected room and one without skips a protected room |
| connect | `LocalMatchJoinSessionJob` `0x16c36c8`; the check `0x16b8890` | the joiner computes `crc32` of its typed password (`0x1719204`); +0x08 must be 8, and a CRC other than the advertised u32 at +0x04 fails with 0x6c51 before `nn::ldn::Connect` |

The host writes that header in `LdnProtocol` `0x16b6a14`: network id, the password's CRC32, the
byte 8, the session parameter. No message carries the joiner's CRC to the host. A password longer
than eight characters keeps eight for Pia and moves the rest into application data behind `INL1`
(`IlcaNetSession.SettingSet` `0x2735f14`).

A retail console typing 00000000 against `bin/bdsp_host.py --password 11111111` (scene 5120, the
wrong CRC) sent no frame to the host and opened an empty room of its own; the same console typing
11111111 joined and traded. The CRC value decides the join.

## The passphrase

    WirelessStrongCryptoKey2021

Used raw: 27 bytes, neither padded nor hashed. The LDN layer accepts any passphrase from 16 to 64
bytes and stores the byte string with an explicit length.

The game hands it to `nn::ldn::CreateNetwork` inside an `nn::ldn::SecurityConfig`; it never reaches
Pia's crypto.

## Taking a seat

`bin/bdsp_join.py` scans, associates and reports the participant table:

    participant 0: ip=169.254.54.1  mac=48f1eb209b22                 <- the console
    participant 1: ip=169.254.54.2  mac=58d8122149a2  name=b'PkCamp'  <- the client

The console assigns the IP and holds the seat for as long as it is held. The Union Room's eight seats
are the LDN `max_participants`, so the participant count is the room's population.

Nothing appears on the console's screen. LDN association is below the game; a seat in the LDN
session is not a seat in the Pia session.

LDN association succeeds roughly one attempt in two; `Connect failed with status code 1` with no
`authenticate` line in dmesg is the baseline. Retry before diagnosing. The console can stop
advertising while the player stays in the Union Room: the screen does not change and scans across
all three channels find nothing. Leaving and re-entering the room brings it back on a new channel,
SSID and session parameter; the key derivation handles all three live.

A receiver on the LDN interface must filter its own source IP: broadcasts loop back on the tap.

Unauthenticated Pia is discarded before it reaches anything that replies. Holding the seat and
sending unencrypted Pia datagrams (header-only, header aimed at the console's variable id, header
plus payload, to the host and to the broadcast address) drew nothing: over 70 seconds the console
sent 630 packets, every one 176 bytes, every one addressed to `dst_var = 0`, none to the sender. It
did not answer, did not error and did not drop the seat.

## What is on the wire

A hosting console broadcasts to `169.254.x.255:12345` at about nine datagrams a second, every one
176 bytes, every one addressed to `dst_var = 0`:

    32ab9864 89 00000000 11bac90d 0000 00 f5a83bd383ce712d 59baa5cbc320cb56 <144 bytes>
    magic    v  dst=0    src      pid  f  nonce (a counter) tag              ciphertext

Version byte `0x89` is encrypted, version 9: Pia 5.27-5.45. The header layout, message framing and
transport protocols are on [The Pia layer](pia.md). `pokeldn/ldn/pia5.py` round-trips 674 captured
packets byte-identically.

The reliable protocol's version 3 pins Pia to 5.31-5.43, narrower than the mesh protocol's version 3
(5.30-5.45).

## The key hierarchy

    cryptoKeyDataSeed  9918bd0fdcfa65779918bd0fdcfa6577    from global-metadata.dat
    game key           9900bd0cdcfa65639918bd0fc7fa6577    = seed derived with version 199
    session param      0x36dee059                          advertisement +0x0c, little-endian
    session key        7b182cb087eeabd228a2efd91a8be147    = AES-ECB(game key) over 16 SEAD bytes
    network id         b4c85cf8                            advertisement +0x00, little-endian
    source MAC         48:f1:eb:20:9b:22
    crc32(netid||MAC)  0xda291352
    IV (first packet)  da29130df5a83bd383ce712d

All 674 packets of one capture authenticate on that. Re-encrypting each captured plaintext with the
derived key and IV reproduces the console's own ciphertext and tag, byte for byte, for all 674.

### Where the seed lives

`cryptoKeyDataSeed` is `9918bd0f dcfa6577` twice.

`INL1.IlcaNetSessionSetting` is a plain `[Serializable]` class; its defaults come from its
constructor:

    IlcaNetSessionSetting..ctor
      byte[16] cryptoKeyDataSeed  <- RuntimeHelpers.InitializeArray(array, fieldHandle)
      string   wirelessCryptoKey  <- the "WirelessStrongCryptoKey2021" literal
      ulong    localCommunicationId = 0x0100000011d90000

The field handle resolves to
`<PrivateImplementationDetails>.33F804682DF9E210AABDC4D939CBCD380EC7517F`; a C# compiler names
those fields after the SHA-1 of their initial data, and SHA-1 of the sixteen bytes above is that
name. The `localCommunicationId` in the same constructor is BDSP's.

An `InitializeArray` blob lives in `global-metadata.dat`'s field-default-value section; neither a
scan of the executables nor a scan of the 4.2 GB RomFS finds it. The method is on
[Reverse-engineering a Switch title](switch_re.md).

### The published key is the seed, derived

    seed (metadata)   9918bd0f dcfa6577 9918bd0f dcfa6577
    published key     9900bd0c dcfa6563 9918bd0f c7fa6577
                        ^^   ^^         ^^         ^^        bytes 1, 3, 7, 12

The game overwrites those four bytes from the local communication version, 199 for 1.3.0 (the
`app_version: 199` the advertisement carries). `ldn_game_key(seed, 199)` reproduces the published
row byte for byte. A published key and a measured seed differ in exactly those four positions.

### The session key

Read out of `nn::pia::local::LocalProtocol`, the LDN implementation:

    seed  = a u32 session value held at LocalProtocol+0x5b0
    state = for i in 1..4:  prev = ((prev ^ (prev >> 30)) * 0x6C078965 + i)
    rnd   = four consecutive xorshift128 draws (shifts 11, 8, 19) -> 16 bytes, little-endian
    key   = AES-128-ECB(game key at LocalProtocol+0x5bc).encrypt(rnd)

The generator is SEAD's, Nintendo's standard-library RNG. `pokeldn/ldn/sead.py` implements it and
matches the wiki's SEAD RNG: the same init multiplier, the same 11/8/19 shifts, the same state
rotation. A failed derivation is a wrong key or a wrong nonce.

### The GCM nonce

The IV is built by the stream object, one per network family (its RTTI name says nothing about
crypto):

    nn::pia::local::LdnOutputStream::vfunc3     0x16b39c4      the LDN sender
    nn::pia::local::LocalOutputStream::vfunc3   0x16bca80
    nn::pia::lan::LanOutputStream::vfunc3       0x16a0f80
    nn::pia::nex::NexOutputStream::vfunc3       0x16eca0c

Each opens with `cmp w2, #0xb; b.hi` (the buffer must hold twelve bytes) and takes
`(this, buf, buflen, packet)`. The sender calls it on the object at `PacketWriter+0x948` just before
encrypting; the receiver memsets twelve zero bytes and calls the same slot on `PacketReader+0xc8`.

    IV[0..3]  = u32be( crc32(ten bytes) )
    IV[3]     = overwritten with (packet.source_variable_id & 0xFF)
    IV[4..11] = the eight-byte header nonce, copied from packet+0x1b

Only three bytes of the CRC reach the IV. The hash at `0x1719204` is ordinary CRC32 (its
table-building fallback spells out `0xEDB88320`). The ten bytes are the network id (little-endian)
followed by the source MAC address: a u32 from the network object at +0x450, which the joiner copies
out of advertisement +0x00, followed by six bytes of a station record.

The source MAC cannot be recovered from the packet being decrypted.

## The Local Protocol, decoded

Every one of the 674 packets carries exactly one message, and all of them are the same:

    presence 0x7f  flags 0x11  size 121  protocol 36  port 0  destination 0

Protocol 36 is the Local Protocol and the message is its `0x11` update session, rebroadcast every
100 ms until every station acknowledges it:

    local message header  version 1, type 0x11, size 73
    sequence id           4
    network id            8b4a3b22        random, and NOT the advertisement's network id
    host variable id      11bac90d        the same value as the packet header's source variable id
    host constant id      0000 48f1 2022 9beb
    allow participating   1
    node 0                169.254.54.1:12345          the console
    node 1                169.254.54.2:12345   01     us
    nodes 2-7             empty, marked 0xff
    host migration state  0

Eight nine-byte node slots then one byte: the Union Room's eight seats. The sequence id never moves
across 674 messages; the host repeats an unacknowledged update.

The captured host constant id, read as the little-endian field it is, unpacks by the wiki's LDN rule
(`mac[2] << 56 | mac[4] << 48 | mac[5] << 40 | mac[3] << 32 | mac[1] << 24 | mac[0] << 16`) to
`48:f1:eb:20:9b:22`, the MAC the scan recorded.

The byte order changes three times inside one message: the Pia message header is big-endian, the
Local Protocol's own fields are little-endian, and a local address inside them is big-endian again.

### The ack

The 20-byte ack, its framing, and how the console attributes it are documented on
[The Pia layer](pia.md#the-local-protocol-0x24). The framing that works is a broadcast to the
network broadcast address with packet `dst_var` 0 and message destination 0, the host's own framing.
The three unicast framings have not been tested.

Measured: 42 update sessions about 100 ms apart, the last at t=5.969, the first ack at t=6.003, and
zero packets from the console for the remaining 78 seconds. Nothing appeared on the console's screen.
That run was a fresh session (a different SSID, network id, session parameter, host variable id and
sequence id from the capture the derivation was read against) with every key built live from the
advertisement; all 42 packets authenticated.

The message presence byte is 0x7F. Only bits 1/2/4/8 name a field in Pia 5.27-6.30 and the console's
message carries exactly those four fields; it sets three more bits that name nothing.

## Joining the mesh

The three handshakes and the ack rule are on [The Pia layer](pia.md#joining-a-mesh). BDSP-specific
addresses and results:

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

`0x01550324` is a method of the object at `session + 0xa0`, and that object is the
MeshStationProtocol: its field `0x120` holds the `0x2710` its constructor writes at `0x0154e614`,
where `MeshProtocol`'s constructor zeroes the same offset. The join response handler is identified by
the pointer it reads at `MeshProtocol + 0x128`, which `JoinMeshJob` stores through `0x0154e5c4`
immediately after sending the join request at `0x0155cb8c`.

The console's protocol count is 9, measured by sweeping the count against a console that answers
only on a match: a connection response at N=9 and at no other N. Its nine protocols, read off its
own acceptance:

    0x14 Station v2   0x18 Mesh v3      0x1c SyncClock v0
    0x24 Local v0     0x58 RTT v3       0x68 Unreliable v1
    0x7c Reliable v3  0x94 Session v1   0xa4 MonitoringData v0

Five of the nine answer a version probe; the other four are registered at version 0, which the probe
cannot tell from unregistered (both expect 0). The wiki gives the Local Protocol version 0 for
5.19-5.45.

The join response for a two-station mesh:

    stations 2, host index 0, our index 1, max_active 8, update counter 0
    station 0   the console
    station 1   us - our own station location read back, with the ids we sent

`max_active` 8 is the Union Room's eight seats. Within a second of the join the console begins
sending RTT (0x58) and reliable (0x7c) traffic.

Use a fresh `--src-var` every run. Result 7 means "this variable id is already one of my stations";
re-using the previous run's id minutes later is refused, and changing one digit is accepted. Leaving
and re-entering the room also clears them.

## Hosting

A console entering the Union Room looks for a room before it opens one of its own. The session
setting's `matchingMode` defaults to `IlcaNetSessionInitMode.Random`, with
`localRandomMatchmakeHostWaitTime` 25 and `localRandomMatchmakeTimeUp` 270 in the same constructor.
A console that finds a room with a free seat joins it, whoever hosts it. `bin/bdsp_host.py` hosts
one and a retail Shining Pearl walks into it; `pokeldn/bdsp/host.py` holds the host side.

The advertisement a retail room carries, read off the console's own:

    LDN protocol         1 (AES-CTR advertisement)
    frame version        4
    security mode        1
    scene_id             4352 (0x1100)
    app_version          199
    accept policy        ALL, 1/8
    application_data     17 bytes, the Pia header above with a fresh network id and session
                         parameter, then one zero byte

What a host sends, in order, each one rebuilt byte for byte from a retail host's own
(`tests/test_bdsp_host.py`):

| step | message | framing |
|---|---|---|
| a station associates | Local Protocol update session, every 100 ms until acknowledged, the joiner as node 1 with ranking 1 | broadcast, `dst_var` 0 |
| its connection request | an accepted connection response, 949 bytes: the request layout with type 2, the host's nine protocols, its station location, the advertised network id, one PlayerInfo, zero-filled, the ack id last | `dst_var` 0, flags 0x01 |
| its mesh join request | the station ack of the request's ack id, then the join response (two stations, `max_active` 8, the joiner's own location bytes in its entry) | `dst_var` 0 |
| the join response acknowledged | `NetJoinData` on the reliable window, sequence 1, flags 0x0F | `dst_var` the joiner's |
| from then on | update mesh (556 bytes) every second, RTT requests, `NetCharacterStateData{0, 0}` on 0x68 | `dst_var` 1, destination 0xFFFFFFFF |

The host's station location has no public address and zero NAT fields, 36 bytes; the joiner's has
both and is 40. A host station entry carries index 0 and join order 0, the joiner index 1 and join
order 1.

A joiner sends Sync Clock (0x1C) requests to the host about once a second from the moment the join
response is acknowledged, and answering is the host's job: the reply is the request's tick and the
mesh clock in milliseconds. A joiner whose requests go unanswered deauthenticates about ten
seconds after its first one and re-associates, over and over, with its screen on "communication en
cours". Answered, it sends `NetJoinData`, requests 0x04 and 0x23, and the player sees the host's
character.

A retail joiner's first reliable messages are its `NetJoinData` and a request for 0x23, the same
two a retail host sends. From there the room is symmetric: the approach, the greeting and the trade
on [The Union Room trade](bdsp_trade.md) run unchanged with the console as the joiner.

## Measurement methods

- A check that refuses is an instrument. The console compares the protocol count against its own
  and replies only on a match, so sweeping the count measures a number not otherwise visible. An
  unregistered protocol id expects version 0, so a version of 1 against it is a guaranteed verdict,
  and bisection then reads any protocol's version.
- The equality signal must be a reply. Silence is a lost packet as often as a mismatch. A
  reliable-window ack cannot be swept against silence; a window that accepts application data must
  acknowledge it, so send data and sweep only the sequence id.

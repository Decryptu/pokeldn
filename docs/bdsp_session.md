---
title: Joining and the Pia layer
parent: Brilliant Diamond and Shining Pearl
nav_order: 1
---

# Joining a BDSP session, and what is under the encryption

This page covers a Brilliant Diamond or Shining Pearl Union Room session from the LDN advertisement
to the Pia mesh: the keys, the Local Protocol, joining, hosting and leaving. Addresses are 1.3.0
`main`.

## The advertisement

    local_communication_id  0100000011d90000
    scene_id                4352 (0x1100) Union Room; 5120 (0x1400) Union Room with a password;
                            12608 (0x3140) Grand Underground
    version                 4
    accept_policy           ALL, 1/8
    application_data        17 bytes: Pia's 16-byte LDN header (ldn.md), then one byte

The comm id is Brilliant Diamond's title id, shared by Shining Pearl (`010018e011d92000`). The
advertisement decrypts with `prod.keys` alone (`tools/ldn/ldn_scan.py`).

The header's CRC32 field (+0x04) is 0 in a plain room. A password room carries the CRC32 of the
password's ASCII digits there, little-endian (00000000 -> `0xC0088D03`), and scene id 5120. A console
filters on scene id at scan, skips rooms whose protection does not match its own, and before
`nn::ldn::Connect` compares the CRC of its typed password with +0x04 (check `0x16b8890`, error
0x6c51). No message carries the joiner's CRC to the host: a wrong password sends the host nothing.
A password longer than eight characters keeps eight for Pia and moves the rest into application data
behind `INL1`. `bin/bdsp_host.py --password 00000000` hosts a password room; `bin/bdsp_connect.py`
joins one unchanged.

## The passphrase

    WirelessStrongCryptoKey2021

Used raw, 27 bytes, neither padded nor hashed (LDN accepts 16 to 64 bytes with an explicit length), as the `nn::ldn::SecurityConfig` passphrase; it never reaches Pia's crypto.

## Taking a seat

`bin/bdsp_join.py` scans, associates and reports the participant table; the console assigns the IP.
The Union Room's eight seats are the LDN `max_participants`. An LDN seat shows nothing on screen.

- `Connect failed with status code 1` is a failed association; from the ESP32 board about one
  attempt in two fails. Retry before diagnosing.
- Re-entering the room opens a new network (new channel, SSID and session parameter).
- A receiver on the LDN interface must filter its own source IP: broadcasts loop back.
- Unauthenticated Pia is dropped silently, with no loss of the seat.

### Random matching

A console alone in its own Union Room session closes it and matches again, with no change on
screen, until it has been alone long enough. `INL1.IlcaNetSession$$GameState_GameFrontBefore_LocalRandom`
[0x02740640] runs on every session update, once per rendered frame at 30 frames a second. With one
station it closes the session after `25 + (0x7F & r)` updates (0.83 to 5.07 s, `r` random per
attempt) until 270 updates alone (9.0 s) have accumulated, then keeps its network. The constants
come from the `IlcaNetSessionSetting` constructor [0x01f46fc0]. Update chain: `Sequencer$$SubscribeUpdate` call
[0x0202da38] -> `_orderableList` [0x01a8fed0] -> `Sequencer$$Update` [0x01a906d8..0x01a9071c] ->
`NetworkManager$$OnUpdate` [0x02253190] -> `IlcaNetSession$$Update` [0x02030a38]; `targetFrameRate`
30 [0x01a8ed68], and the only quality level (`Ultra`) has `vSyncCount` 2 (30 fps at 60 Hz).

## What is on the wire

Until a station acknowledges it, a hosting console broadcasts its update session to
`169.254.x.255:12345` every 100 ms, `dst_var = 0`, 176 bytes:

    32ab9864 89 00000000 11bac90d 0000 00 f5a83bd383ce712d 59baa5cbc320cb56 <144 bytes>
    magic    v  dst=0    src      pid  f  nonce (a counter) tag              ciphertext

Version 9, encrypted: Pia 5.31-5.43. The header and transport protocols are on
[The Pia layer](pia.md); `pokeldn/ldn/pia5.py` round-trips captured packets byte-identically.

## The key hierarchy

    cryptoKeyDataSeed  9918bd0fdcfa65779918bd0fdcfa6577    from global-metadata.dat
    game key           9900bd0cdcfa65639918bd0fc7fa6577    = seed derived with version 199
    session param      0x36dee059                          advertisement +0x0c, little-endian
    session key        7b182cb087eeabd228a2efd91a8be147    = AES-ECB(game key) over 16 SEAD bytes
    network id         b4c85cf8                            advertisement +0x00, little-endian
    source MAC         48:f1:eb:20:9b:22
    crc32(netid||MAC)  0xda291352
    IV (first packet)  da29130df5a83bd383ce712d

### Where the seed lives

`INL1.IlcaNetSessionSetting`'s constructor fills `cryptoKeyDataSeed` from a field-default blob in
`global-metadata.dat` (`<PrivateImplementationDetails>.33F804682DF9E210AABDC4D939CBCD380EC7517F`);
the method is on [Reverse-engineering a Switch title](switch_re.md).

### The published key is the seed, derived

The game overwrites bytes 1, 3, 7 and 12 of the seed from the local communication version, 199 for
1.3.0 (the advertisement's `app_version`); `ldn_game_key(seed, 199)` gives the game key.

### The session key

    seed  = the session parameter (LocalProtocol+0x5b0)
    state = for i in 1..4:  prev = ((prev ^ (prev >> 30)) * 0x6C078965 + i)
    rnd   = four xorshift128 draws (shifts 11, 8, 19) -> 16 bytes, little-endian
    key   = AES-128-ECB(game key).encrypt(rnd)

`pokeldn/ldn/sead.py` implements SEAD's RNG.

### The GCM nonce

Built by `nn::pia::local::LdnOutputStream::vfunc3` `0x16b39c4`:

    IV[0..3]  = u32be( crc32(network id LE || source MAC) )
    IV[3]     = overwritten with (packet.source_variable_id & 0xFF)
    IV[4..11] = the eight-byte header nonce

The CRC is ordinary CRC32. The source MAC comes from the station record; the packet does not carry it.

## The Local Protocol, decoded

The update session (Local Protocol 0x24, type 0x11), rebroadcast every 100 ms until every station
acknowledges it:

    local message header  version 1, type 0x11, size 73
    sequence id           4
    network id            8b4a3b22        random, unrelated to the advertisement's
    host variable id      11bac90d        the packet header's source variable id
    host constant id      0000 48f1 2022 9beb
    allow participating   1
    node 0..7             nine bytes each (ip, port, ranking); empty slots 0xff
    host migration state  0

The host constant id, read little-endian, unpacks by the LDN rule (`mac[2] << 56 | mac[4] << 48 |
mac[5] << 40 | mac[3] << 32 | mac[1] << 24 | mac[0] << 16`) to the host MAC. The Pia message header
is big-endian, the Local Protocol's fields little-endian, addresses inside them big-endian.

### The ack

The 20-byte ack is on [The Pia layer](pia.md#the-local-protocol-0x24), sent as a broadcast with
`dst_var` 0 and destination 0. The first ack stops the updates.

## Joining the mesh

The handshakes are on [The Pia layer](pia.md#joining-a-mesh). BDSP's addresses:

| what | where |
|---|---|
| station protocol receive dispatcher | `0x0154e848`, table `0x3e6b38f` |
| connection request deserializer | `0x0154ebd0` |
| result mapping from internal errors | `0x0154f5e8` |
| protocol version lookup by id | `0x0159b850`, 0 for an unregistered id |
| read a mesh message's ack id | `0x01542db8` (`size - 4`, big-endian) |
| send the ack (8 bytes, on 0x14) | `0x01550324`, MeshStationProtocol at `session + 0xa0` |
| join REQUEST handler, host side | `0x0154b790`, `0x0154b868` |
| join RESPONSE handler | `0x0154b984`, `0x0154b9a4`; pointer stored at `MeshProtocol + 0x128` (`0x0154e5c4`) |

The console registers nine protocols
([measured](#measurement-methods)):

    0x14 Station v2   0x18 Mesh v3      0x1c SyncClock v0
    0x24 Local v0     0x58 RTT v3       0x68 Unreliable v1
    0x7c Reliable v3  0x94 Session v1   0xa4 MonitoringData v0

The join response lists two stations, host index 0, joiner index 1, `max_active` 8. Result 7 means
the variable id is already one of its stations. The Session Protocol (0x94) is inert on LDN: its
handlers (dispatcher `0x15820b8`, jump table `0x3e6b986`) return because session+0x70 is null:
`LdnNetworkFactory` slot 61 [`0x16b30ac`] builds no joint-session job. It is built at `0x157c66c`
(skipped when +0x38 behind GOT `0x4c4b850` is set), stored at session+0xC8, with one
`ReliableSlidingWindow` per station [`0x1581938`; constructor `0x159dab4`;
`0x159de54(window, 2, 2, 0x94000001)`; receive slot 10 `0x1581c98`]. A valid reliable 0x94 is
acknowledged, then dropped.

## Hosting

A console entering the Union Room joins any room with a free seat before opening its own.
`bin/bdsp_host.py` (`pokeldn/bdsp/host.py`) hosts one with scene id 0x1100, `app_version` 199 and a
fresh network id and session parameter. What it sends, each rebuilt byte for byte from a retail
host's (`tests/test_bdsp_host.py`):

| step | message | framing |
|---|---|---|
| a station associates | update session every 100 ms until acknowledged, the joiner as node 1 | broadcast, `dst_var` 0 |
| its connection request | an accepted connection response, 949 bytes | `dst_var` 0, flags 0x01 |
| its mesh join request | the station ack, then the join response | `dst_var` 0 |
| the join response acknowledged | `NetJoinData`, reliable sequence 1 | `dst_var` the joiner's |
| from then on | update mesh every second, RTT requests, `NetCharacterStateData{0, 0}` on 0x68 | `dst_var` 1 |

The host must answer the joiner's Sync Clock (0x1C) requests with the request's tick and the mesh
clock in milliseconds. A joiner left unanswered deauthenticates after about ten seconds and
re-associates while the screen shows "communication en cours". Once answered, the room is symmetric
and [the trade](bdsp_trade.md) runs unchanged.

## Leaving

Both departures open on the mesh reliable window (0x18 port 1, sequence 1) and wait on an answer
sent unreliably on port 0, which retail Pia sends twice. Mesh dispatcher `0x0154ac94`.

| the console | sends | is owed |
|---|---|---|
| joiner | `04 <own index>`, then station disconnection `03` on 0x14 | `08 <host index>`, then `04` |
| host | `44 <host index> <new host index>` to each station | `48 <station index>` from every station |

Answered, a joiner deauthenticates within 0.2 s and a host closes its network within 0.5 s.
Unanswered, a joiner retries for about 5 s and leaves after about 9 s; a host runs its migration
for about 25 s, ending with Local Protocol 0x13 every 0.3 s for up to 10 s
(`LocalDestroyNetworkJob::WaitUntilAllClientsDisconnection` `0x016b95b8`), which a station leaving
ends at once. Its steps: resend after 301 ms (`job+0x68`); cancel byte to `WaitForCancel` `0x016b9330`;
one station left (count `0x016b014c`, test `0x016b9614`) or 10000 ms since
`WaitUntilAllClientsReceiveUpdateSessionMessage` `0x016b936c` (`job+0x70`, test `0x016b9644`) to
`StartDestroyNetwork` `0x016b950c`; the previous state ends on `[[protocol+0x4f0]+0x5c]`
(`0x016b0888`) or after 10001 ms. Leave handlers: host's leave request `0x0154b9e0` (answer via
`0x0154c860`), joiner's response `0x0154baf8`, migration response `0x0154b068`;
`WaitLeaveResponse` `0x0155fd2c`, `WaitMigrationResponse` `0x015607bc`.

`pokeldn.bdsp.session.answer_departure` builds both answers; `bin/bdsp_host.py` answers a leaving
joiner, and `bin/bdsp_connect.py` answers a migration start and leaves the network on 0x13
(`--no-leave-on-host-migration` stays). Leaving the trade box sends no departure message, only
`NetDataCurrentFlowCancelData{0}` (0x25) and `NetCharacterStateData{0}` in one packet.

## LAN mode

BDSP 1.3.0 never sets up LAN mode. Its Pia comes through Nintendo's Unity plugin, whose framework
initialisation (around `0x16886d0`) builds the Lan factory (constructor `0x169fdcc`) for its LAN
mode, which needs a registered LAN setting. `INL1.IlcaNetBase.PlatformInitialize` registers the internet setting
(`0x1e13800`) and `PlatformInitialize2` the local one (`0x1e139dc`); nothing calls
`PiaPlugin.RegisterInitializeLanSetting` (`0x227caf0`) or its native `0x227cac0`. No C# name in
`global-metadata.dat` mentions LAN.

## Measurement methods

- The console answers a connection request only when the protocol count matches its own; sweeping
  the count gives 9. An unregistered protocol expects version 0, so bisecting the version reads any
  protocol's.
- The signal must be a reply; silence is as often a lost packet. A reliable window acknowledges
  data it accepts, so send data and sweep only the sequence id.

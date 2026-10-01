---
title: The wireless layer
nav_order: 2
has_children: true
---

# The wireless layer

A Switch talks to nearby consoles over **LDN**, Nintendo's local wireless, and above it over
[Pia](pia.md), Nintendo's peer-to-peer session middleware. Both are system libraries; titles differ
in Pia version and payloads.

## The two secrets

The LDN passphrase authenticates the 802.11 association: 16-64 bytes (checked by
`nn::pia::local::LdnBackgroundProcessJob`), used verbatim; Brilliant Diamond passes an ASCII string
straight to `nn::ldn::CreateNetwork`. The 16-byte Pia game key derives the session key that
encrypts every datagram.

| title | LDN passphrase | Pia game key |
|---|---|---|
| Brilliant Diamond / Shining Pearl | `WirelessStrongCryptoKey2021` (27 bytes, raw) | derived from `cryptoKeyDataSeed`; see [BDSP](bdsp_session.md) |
| Sword / Shield | `W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL` (64 bytes, raw) | `p1frXqxmeCZWFv0X` |

Scarlet/Violet and Legends Arceus use Sword/Shield's passphrase and game key ([Scarlet and
Violet](sv.md), [Legends Arceus](pla.md)); the NintendoClients wiki's `HGHG` spelling for Arceus is
wrong.

## Discovery

Reading an advertisement needs only `prod.keys`: `tools/ldn/ldn_scan.py` shows any session's
`local_communication_id`, `scene_id`, version, channel, accept policy, participant count and
application data. A title sees only advertisements of its own LDN protocol (1: AES-CTR under
`master_key_00`; 3: AES-GCM under `master_key_12`), so a host copies the title's
(`HostTransport(protocol=...)`).

| title | protocol | advertisement format |
|---|---|---|
| the GBA app (FireRed, LeafGreen), comm id `0x01006fa0233f8000` | 3 | 3, AES-GCM |
| Sword Mystery Gift screen, comm id `0x0100abf008968000` | 1 | 2, AES-CTR |
| Legends Arceus local trade, comm id `0x01001f5010dfa000` | 1 | 4 |

A host console sends beacons at 11 Mbit/s DSSS and advertisement action frames at HT MCS 3, 20 MHz
(OFDM), Scarlet's Link Trade search and Sword's Mystery Gift screen alike; a DSSS-only receiver
misses the action frames.

## The advertisement's application data

Pia 5 layout, from Shining Pearl:

    +0x00  4  network id                     random per session
    +0x04  4  CRC32 of the user password     0 when the room has no password
    +0x08  1  system communication version
    +0x09  1  header size                    16
    +0x0a  2  padding
    +0x0c  4  session parameter              random per session; seeds the Pia session key
    +0x10     application data

A capture decrypts only with its own session's advertisement; another fails silently.

Pia 6.16 to 6.41 use a system property block and derive the session key and network id from the
SSID:

    +0x00  2  system property data size      0x5C
    +0x02  1  system communication version   21 for 6.16-6.30, 22 for 6.39-6.41
    +0x03  2  application communication version
    +0x05  16 user password
    +0x15  1  is player limit enabled
    +0x16  1  number of players
    +0x17  4  player name size
    +0x1b  1  player name encoding           1 = UTF-8, 2 = UTF-16
    +0x1c  64 player name
    +0x5c     application data

With transport encryption on, the user password is padded to sixteen bytes with 0xFE and encrypted
in place, AES-128-GCM under the game key, tag discarded, IV `key[1] key[8] key[7] key[2]`, then
copied in by the block builder (Arceus 1.1.1 `0x6fac70`; [the setter](pla.md#the-link-code-in-the-advertisement)).
One GCM block is an XOR with a keystream fixed by the key: the game key alone reads the password.

## Hosting for an emulator

An emulator in ldn_mitm mode associates over port 11452, then runs Pia over the LAN: no radio, no
`prod.keys`, no root. `pokeldn/ldn/ldn_mitm.py` joins; `ldn_mitm_host.py` hosts through
`IpHostTransport`, whose `NEEDS_RADIO = False` selects `NullBeaconInjector`.

    UDP  console -> host:11452   Scan          header only, unicast and broadcast
    UDP  host    -> console      ScanResp      NetworkInfo, 0x480
    TCP  console -> host:11452   Connect       NodeInfo, 0x40
    TCP  host    -> console      SyncNetwork   NetworkInfo with the console seated, held open

`nn::ldn::NetworkInfo`, 0x480 bytes:

    +0x000  NetworkId          IntentId 0x10 (u64 localCommunicationId, u16, u16 sceneId, u32) then SessionId 0x10
    +0x020  CommonNetworkInfo  MAC 6, Ssid 0x22 (length byte then 0x21), s16 channel, u8 linkLevel, u8 networkType, u32
    +0x050  LdnNetworkInfo     SecurityParameter 0x10, u16 securityMode, u8 acceptPolicy, ...
    +0x066                     u8 nodeCountMax, u8 nodeCount
    +0x068                     NodeInfo[8], 0x40 each: u32 IPv4 little-endian, MAC 6, u8 nodeId,
                               u8 isConnected, 0x20 name at 0x0C, u16 localCommunicationVersion at 0x2E
    +0x26A                     u16 advertiseDataSize, then 0x180 bytes of advertise data
    +0x478                     u64 authenticationId

Nodes carry real LAN addresses (Pia is not tunnelled); node 0's must be reachable, never link-local:
the console sends Pia and opens the TCP connection there. The emulator derives a node's MAC from its
address (`02:00:ac:10:56:01` for 172.16.86.1). The game's own node holds 88 at +0x2E (aligned after
the byte at 0x2C), the value its `ConnectImpl` passes, and the game keeps the NetworkInfo exactly as
sent. FireRed's scan filter compares `localCommunicationId` and `networkType` only (`sceneId`
0xFFFF, `ssidLength` 0).

The 16-byte session id is one value in three places: `NetworkId.SessionId`, the `Ssid` text in hex,
and the plaintext of the Pia session key `AES(game_key).encrypt(ssid)`, network id
`crc32(ssid[1:16])` [`pokeldn/ldn/crypto.py`:114], as the LDN library does
[vendor/LDN/ldn/__init__.py:1921, :1910]. Advertising one and encrypting with another associates,
then the console drops every datagram and times out, with no error.

## A station's broadcasts

A joined console sends broadcast and multicast straight to the BSS (no DS bits; addresses group,
console, BSSID; CCMP group key, key id 1) and unicast to-DS (pairwise key, key id 0). FireRed's first
broadcasts are an ARP for the host and IPv6 multicast. A standard access point drops frames with no
DS bits, and a host that does not answer the ARP is deauthenticated with reason 3. The Linux
host decrypts them off its monitor interface (`vendor/LDN/ldn/__init__.py` `_process_data_frame`);
the [ESP32](hardware_esp32.md) forwards them whole.

## Channels

LDN also allows 5 GHz channels 36/40/44/48, which the ESP32 cannot reach (on a Linux card: `sudo iw
dev <managed iface> scan | grep -A3 <console MAC>`); FireRed/LeafGreen scans 2.4 GHz only. A
re-hosting console may change channel; the board's scan prints it:

    POKELDN_RADIO=esp32:auto ./.venv/bin/python tools/ldn/ldn_scan.py --keys PROD_KEYS --dwell 2.5

Advertisements leak onto neighbouring channels: a board hears a host's advertisements on the
channels beside its own too, far fewer of them and at the same RSSI. Joining on a neighbour
associates, then the next advertisement on the host's own channel drops the link as an incompatible
network, so the scan reports the busiest one.

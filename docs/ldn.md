---
title: The wireless layer
nav_order: 2
has_children: true
---

# The wireless layer

**LDN** is the Switch's local wireless; [Pia](pia.md), Nintendo's peer-to-peer middleware, runs
above it.

## The two secrets

The LDN passphrase (16-64 bytes, used verbatim) authenticates the 802.11 association. The 16-byte
Pia game key derives the session key for every datagram.

| title | LDN passphrase | Pia game key |
|---|---|---|
| Brilliant Diamond / Shining Pearl | `WirelessStrongCryptoKey2021` (27 bytes) | from `cryptoKeyDataSeed` ([BDSP](bdsp_session.md)) |
| Sword / Shield, Scarlet / Violet, Legends Arceus | `W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL` (64 bytes) | `p1frXqxmeCZWFv0X` |

## Discovery

`tools/ldn/ldn_scan.py` reads any advertisement with `prod.keys` alone. A title sees only
advertisements of its own LDN protocol, so a host copies it (`HostTransport(protocol=...)`).

| title | protocol | advertisement format |
|---|---|---|
| the GBA app, comm id `0x01006fa0233f8000` | 3 (AES-GCM, `master_key_12`) | 3 |
| Sword Mystery Gift screen, `0x0100abf008968000` | 1 (AES-CTR, `master_key_00`) | 2 |
| Legends Arceus local trade, `0x01001f5010dfa000` | 1 | 4 |

Beacons go out at 11 Mbit/s DSSS, advertisement action frames at HT MCS 3 (OFDM); a DSSS-only
receiver misses the advertisements.

## The advertisement's application data

Pia 5 (Shining Pearl):

    +0x00  4  network id                     random per session
    +0x04  4  CRC32 of the user password     0 without a password
    +0x08  1  system communication version
    +0x09  1  header size                    16
    +0x0c  4  session parameter              seeds the Pia session key
    +0x10     application data

A capture decrypts only with its own session's advertisement.

Pia 6.16 to 6.41 derive the session key and network id from the SSID:

    +0x00  2  system property data size      0x5C
    +0x02  1  system communication version   21 for 6.16-6.30, 22 for 6.39-6.41
    +0x03  2  application communication version
    +0x05  16 user password                  0xFE-padded, AES-128-GCM under the game key, tag dropped
    +0x15  1  is player limit enabled
    +0x16  1  number of players
    +0x17  4  player name size
    +0x1b  1  player name encoding           1 = UTF-8, 2 = UTF-16
    +0x1c  64 player name
    +0x5c     application data

The password's IV is `key[1] key[8] key[7] key[2]` (Arceus 1.1.1 `0x6fac70`,
[the setter](pla.md#the-link-code-in-the-advertisement)); the game key alone reads it.

## Hosting for an emulator

An emulator in ldn_mitm mode associates over port 11452 and runs Pia over the LAN, with no radio
and no `prod.keys`. `pokeldn/ldn/ldn_mitm.py` joins; `ldn_mitm_host.py` hosts through
`IpHostTransport` (`NEEDS_RADIO = False`).

    UDP  console -> host:11452   Scan          header only
    UDP  host    -> console      ScanResp      NetworkInfo, 0x480
    TCP  console -> host:11452   Connect       NodeInfo, 0x40
    TCP  host    -> console      SyncNetwork   NetworkInfo with the console seated, held open

`nn::ldn::NetworkInfo`, 0x480 bytes:

    +0x000  NetworkId          IntentId 0x10 (u64 localCommunicationId, u16, u16 sceneId, u32) then SessionId 0x10
    +0x020  CommonNetworkInfo  MAC 6, Ssid 0x22 (length byte then 0x21), s16 channel, u8 linkLevel, u8 networkType, u32
    +0x050  LdnNetworkInfo     SecurityParameter 0x10, u16 securityMode, u8 acceptPolicy, ...
    +0x066                     u8 nodeCountMax, u8 nodeCount
    +0x068                     NodeInfo[8], 0x40 each: u32 IPv4 LE, MAC 6, u8 nodeId,
                               u8 isConnected, 0x20 name at 0x0C, u16 localCommunicationVersion at 0x2E
    +0x26A                     u16 advertiseDataSize, then 0x180 bytes of advertise data
    +0x478                     u64 authenticationId

Node 0's address must be a reachable LAN address: the console sends Pia there. A node's MAC derives
from its address (`02:00:ac:10:56:01` for 172.16.86.1). The game's node carries 88 at +0x2E.
FireRed's scan filter compares `localCommunicationId` and `networkType` only.

The 16-byte session id is `NetworkId.SessionId`, the hex `Ssid` text, and the plaintext of the Pia
session key `AES(game_key).encrypt(ssid)`; network id is `crc32(ssid[1:16])`
[`pokeldn/ldn/crypto.py`:114]. Trap: a mismatch associates, then the console silently drops every
datagram.

## A station's broadcasts

A joined console sends broadcast and multicast with no DS bits (CCMP group key, key id 1) and
unicast to-DS (pairwise key, key id 0). FireRed opens with an ARP for the host; a host that does not
answer it is deauthenticated with reason 3. A standard access point drops these frames; the
[ESP32](hardware_esp32.md) forwards them whole.

## Channels

LDN also allows 5 GHz channels 36-48, which the ESP32 cannot reach; FireRed/LeafGreen uses 2.4 GHz
only. A board hears a host on neighbouring channels too; joining there is dropped at the host's next
advertisement, so the scan reports the busiest channel:

    POKELDN_RADIO=esp32:auto ./.venv/bin/python tools/ldn/ldn_scan.py --keys PROD_KEYS --dwell 2.5

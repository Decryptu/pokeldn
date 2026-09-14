---
title: The wireless layer
nav_order: 2
has_children: true
---

# The wireless layer

A Nintendo Switch communicates with nearby consoles over **LDN**, Nintendo's local wireless, and
above that over Pia, Nintendo's peer-to-peer session middleware. Both belong to the console, so
an implementation carries from one title to the next. What changes per title is the Pia version and
what the game does with the payloads.

## The two secrets

| layer | secret | purpose |
|---|---|---|
| LDN | the title's LDN passphrase, 16-64 bytes | authenticates the 802.11 association |
| Pia | the title's game key, 16 bytes | derives the session key that encrypts every datagram |

In Brilliant Diamond the passphrase is an ASCII string handed straight to `nn::ldn::CreateNetwork`;
it never reaches Pia's crypto.

Known values:

| title | LDN passphrase | Pia game key |
|---|---|---|
| Brilliant Diamond / Shining Pearl | `WirelessStrongCryptoKey2021` (27 bytes, raw) | derived from `cryptoKeyDataSeed`; see [BDSP](bdsp_session.md) |
| Sword / Shield | `W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL` (64 bytes, raw) | `p1frXqxmeCZWFv0X` |

The Sword/Shield passphrase is byte-for-byte the string the NintendoClients wiki lists for
Scarlet/Violet, and differs from its Legends: Arceus row in one character (`HGhG` against `HGHG`).

## Discovery

Reading an advertisement needs only `prod.keys`. The LDN beacon payload is decrypted with console
key material, so any title's session can be seen with nothing known about the game:
`local_communication_id`, `scene_id`, version, channel, accept policy, participant count and
application data. `tools/ldn/ldn_scan.py` does this.

An advertisement is encrypted for one LDN protocol version, and a title sees only advertisements of
the protocol its own session runs. Protocol 1 is AES-CTR under `master_key_00`; protocol 3 is
AES-GCM under `master_key_12`. Which one a title uses is read off its own advertisement
(`scratchpad/air_ldn_adv.py` over an air capture); a host meant for that title advertises the same
protocol (`HostTransport(protocol=...)`).

| title | protocol | advertisement format |
|---|---|---|
| the GBA app (FireRed, LeafGreen), comm id `0x01006fa0233f8000` | 3 | 3, AES-GCM |
| Sword Mystery Gift screen, comm id `0x0100abf008968000` | 1 | 2, AES-CTR |

Association is the first step that needs a title secret. The passphrase is used verbatim, neither
padded nor hashed. `nn::pia::local::LdnBackgroundProcessJob` validates the length as 16-64 before
use.

## The advertisement's application data

Pia's LDN advertisement layout, as parsed from a Shining Pearl session:

    +0x00  4  network id                     random per session
    +0x04  4  CRC32 of the user password     0 when the room has no password
    +0x08  1  system communication version
    +0x09  1  header size                    16
    +0x0a  2  padding
    +0x0c  4  session parameter              random per session; seeds the Pia session key
    +0x10     application data

The network id and the session parameter both change per session. A key derivation tested against a
capture from a different session fails on every packet with no distinguishing symptom. Match the
advertisement and the capture before doubting the derivation.

## Hosting for an emulator

An emulator in ldn_mitm mode has no radio. The association is an exchange on port 11452 and the
game's Pia traffic then flows over the LAN on the ordinary Pia port, so a host reaches it with no
adapter, no `prod.keys` and no root.

    UDP  console -> host:11452   Scan          header only, sent to both the unicast and the broadcast address
    UDP  host    -> console      ScanResp      NetworkInfo, 0x480
    TCP  console -> host:11452   Connect       NodeInfo, 0x40
    TCP  host    -> console      SyncNetwork   NetworkInfo with the console seated, held open

`pokeldn/ldn/ldn_mitm.py` speaks it as a joiner and `pokeldn/ldn/ldn_mitm_host.py` as a host.
`IpHostTransport` carries `HostTransport`'s surface, so a host application takes it as its
`transport_factory` and nothing above the transport changes. `NEEDS_RADIO = False` on a transport
also selects `NullBeaconInjector`, because a host that answers scans emits no 802.11 beacon.

`nn::ldn::NetworkInfo`, 0x480 bytes:

    +0x000  NetworkId          IntentId 0x10 (u64 localCommunicationId, u16, u16 sceneId, u32) then SessionId 0x10
    +0x020  CommonNetworkInfo  MAC 6, Ssid 0x22 (length byte then 0x21), s16 channel, u8 linkLevel, u8 networkType, u32
    +0x050  LdnNetworkInfo     SecurityParameter 0x10, u16 securityMode, u8 acceptPolicy, ...
    +0x066                     u8 nodeCountMax, u8 nodeCount
    +0x068                     NodeInfo[8], 0x40 each: u32 IPv4 little-endian, MAC 6, u8 nodeId,
                               u8 isConnected, 0x20 name at 0x0C, u16 localCommunicationVersion at 0x2E
    +0x26A                     u16 advertiseDataSize, then 0x180 bytes of advertise data
    +0x478                     u64 authenticationId

Every participant's node carries its real LAN address, so the addresses in the NetworkInfo are LAN
addresses and Pia is not tunnelled. The address in node 0 is where the console sends its Pia
datagrams and where it opens the TCP connection, so it must be the address the host is reachable at
rather than a link-local one.

The 16-byte session id is three things at once and they cannot be allowed to disagree: the
advertised `NetworkId.SessionId`, the text `Ssid` in hexadecimal, and the plaintext of the Pia
session key, `AES(game_key).encrypt(ssid)`, whose network id is `crc32(ssid[1:16])`
[`pokeldn/ldn/crypto.py`:114]. On the radio the LDN library generates one value and uses it for all
three [vendor/LDN/ldn/__init__.py:1921, :1910]. A host that advertises one value and encrypts with
another completes the association and is then ignored: the console authenticates every datagram
against the key it derived, drops what fails, sends nothing, and closes the socket on its own
timeout. There is no error and no retry, so the symptom is silence from a peer that is demonstrably
receiving.

`localCommunicationVersion` sits at node + 0x2E, aligned after the byte at 0x2C rather than packed
against it. A NetworkInfo read back out of the running game carries the console's own 88 there, which
is the value its `ConnectImpl` passes, so the console's own node settles the offset. The emulator
synthesises a node's MAC from its address: `02:00:ac:10:56:01` for 172.16.86.1.

A whole NetworkInfo read out of the game after it joined is identical to what the host sent, field
for field, so nothing between the ScanResp and the game rewrites any of it.

A scan filter names which fields the game compares. FireRed's filters on `localCommunicationId` and
`networkType` alone, with `sceneId` 0xFFFF and `ssidLength` 0, so only those two have to match.

## Channels

LDN allows 5 GHz channels 36/40/44/48 and a host may use them; the FireRed/LeafGreen application
scans 2.4 GHz only. A console re-hosting picks a new channel. Read the frequency out of the kernel
before a run:

    sudo iw dev <managed iface> scan | grep -A3 <console MAC>

## Pages

- [The Pia layer](pia.md): packet header formats by version, message framing, the transport
  protocols, and the session-key derivations.

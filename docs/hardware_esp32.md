---
title: ESP32 radio
parent: Hardware and setup
nav_order: 4
---

# ESP32 radio

An ESP32 board on USB serial can stand in for the nl80211 adapter. The board runs
`firmware/esp32/` and carries two kinds of traffic: LDN's vendor action frames and Ethernet
frames. Advertisement crypto, LDN authentication, IP and Pia stay on the host, in the same code
that drives the Archer. `pokeldn.ldn.esp32_wlan` gives the LDN library a factory backed by the
board, so `ldn.scan`, `ldn.connect` and `ldn.create_network` run on it unchanged. The serial
port is the board's only link to the host, so the host needs no Wi-Fi driver of its own.

## Roles

| role | what the board does |
|---|---|
| idle | promiscuous on one channel; every action frame with the Nintendo LDN prefix `7f 00 22 aa` goes to the host |
| station | joins a console's network by BSSID with the host's derived CCMP key; installs the pairwise and group keys directly and opens the port without a 4-way handshake |
| access point | a hidden-SSID WPA2 network on the host's BSSID; answers a console's association, installs the same key for it, opens its port |

A console's network has no 4-way handshake: both ends derive the CCMP key from the
advertisement's server random. The firmware replaces four entries of ESP-IDF's private
`struct wpa_funcs` table (`esp_wifi_driver.h`):

- `wpa_sta_connect` installs the RSN element a Switch station sends (CCMP, PSK, capabilities
  `0x000c`) before and after the stock callback, which rebuilds it.
- `wpa_sta_rx_eapol` drops EAPOL; the station keys go in with `esp_wifi_set_sta_key_internal`
  once the association response is seen, then `esp_wifi_auth_done_internal` opens the port.
- `wpa_ap_join` adds the station to hostapd's table and sends the association response
  (`esp_send_assoc_resp`) without creating an authenticator state machine, so no EAPOL-Key
  message 1 goes out. The stock join stays selectable with the `AP_START` flag bit 0.
- On `WIFI_EVENT_AP_STACONNECTED` the pairwise key goes in with
  `esp_wifi_set_ap_key_internal(CCMP, mac, 0, key)` and the port opens with
  `esp_wifi_wpa_ptk_init_done_internal(mac)`, the call hostapd's `PTKINITDONE` state makes
  (`wpa_auth.c:2284`). The group key goes in at `WIFI_EVENT_AP_START` with index 1.

The table layout is the ESP-IDF v6.1 blob's ABI. The firmware refuses to build against another
release.

## Serial protocol

A frame is `COBS(type | payload | crc32-le(type | payload))` followed by `0x00`. The CRC is
CRC-32/ISO-HDLC (`zlib.crc32`). The board boots at 115200 baud; `BAUD` switches both ends.
Anything before a `0x00`, including the ROM's boot text, is discarded by the checksum.

| type | direction | payload |
|---|---|---|
| `0x01` HELLO | host | none; answered by INFO |
| `0x02` BAUD | host | u32 baud; RESULT at the old rate, then the switch |
| `0x03` CHANNEL | host | u8 channel; idle only |
| `0x04` STA_JOIN | host | u8 channel, 6 BSSID, 32 SSID (the LDN SSID's hex text), 16 key, 6 station MAC (zero = random) |
| `0x05` STOP | host | none; back to idle, keys cleared |
| `0x06` AP_START | host | u8 channel, 6 BSSID, 32 SSID, 16 key, u8 max stations, u8 flags |
| `0x07` AP_KICK | host | 6 MAC, u16 reason; deauthenticates |
| `0x08` ETH_TX | host | an Ethernet frame; the driver encrypts it with the station's or the group key |
| `0x09` RAW_TX | host | an 802.11 frame without FCS (`esp_wifi_80211_tx`); used for advertisements |
| `0x0B` STATUS | host | none; answered by STATUS |
| `0x81` INFO | board | u8 protocol version (1), 6 station MAC, 6 AP MAC, u8 chip revision, text |
| `0x82` RESULT | board | u8 command, i32 `esp_err_t` |
| `0x83` LOG | board | text |
| `0x84` RX_MGMT | board | u8 channel, i8 RSSI, the action frame without FCS |
| `0x85` RX_ETH | board | an Ethernet frame the driver decrypted |
| `0x86` LINK | board | u8 up, u16 reason, 6 MAC; reason `0xFFFF` no association in 15 s, `0xFFFE` keys refused |
| `0x87` STA_JOINED | board | 6 MAC, u8 AID, i8 key install result, u8 port opened |
| `0x88` STA_LEFT | board | 6 MAC, u16 reason |
| `0x89` STATUS | board | text counters |

EtherType `0x88B7` frames are LDN authentication; `esp32_wlan` turns them into the LDN
library's `CustomFrameEvent`. Every other Ethernet frame goes to an L2 port: a kernel TAP named
after the interface on Linux, so the launchers' sockets bound to it work unchanged, or a
`MemoryPort` where there is no TAP.

## Building and flashing

ESP-IDF v6.1 (tag `v6.1`, commit `fff9895c82d744c7237be8847347bdd1b07c6643`), target `esp32`:

    cd firmware/esp32
    idf.py build
    idf.py -p <port> flash

The console output is off (`CONFIG_ESP_CONSOLE_NONE`): UART0 is the host link. The image is
0x8f1b0 bytes.

## Running

`POKELDN_RADIO=esp32:<port>` in the environment puts every launcher's `ldn` calls on the board,
for example `POKELDN_RADIO=esp32:/dev/ttyUSB0`. The port is opened once per process with DTR and
RTS released, since an edge on either resets most boards.

`tests/test_esp32.py` runs the LDN library's host and station against each other on two
simulated boards (`pokeldn.ldn.esp32_sim`): scan, association, authentication, the join event and
a UDP frame from the station reaching the host's port.

## Unresolved

- No board has run this firmware yet. Every row above is read from the ESP-IDF source and
  exercised against the simulated board only.
- Whether a console accepts the ESP32 access point's beacon and association response: the
  hidden-SSID form, the rate set and the HT elements differ from `vendor/LDN`'s access point,
  whose rate set had to match the Switch's.
- Whether the console's LDN authentication frame reaches `RX_ETH` before or after the driver
  opens the port.
- Serial latency at 921600 baud against the Scarlet and Z-A seat race.
- A host with no TAP (macOS) needs a userspace IP and UDP layer on a `MemoryPort`.
- easyworld reports that a classic ESP32 must be the ESP32-WROOM-32E module and that the older
  ESP32-WROOM-32 does not trade reliably.

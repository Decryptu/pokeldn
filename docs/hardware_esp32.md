---
title: ESP32 radio
parent: Hardware and setup
nav_order: 1
---

# ESP32 radio

An ESP32 board on USB serial is the radio. It runs `firmware/esp32/` and carries LDN's vendor
action frames and Ethernet frames; advertisement crypto, LDN authentication, IP and Pia stay on the
host, except in the [portable beacon](#portable-beacon). `pokeldn.ldn.esp32_wlan` gives the LDN library a factory backed by the board, so `ldn.scan`,
`ldn.connect` and `ldn.create_network` run unchanged and the host needs no Wi-Fi driver.

## Supported boards

| chip | host connection | merged image |
|---|---|---|
| classic ESP32 (ESP32-D0WD, WROOM-32E) | UART0 through a USB serial bridge | `pokeldn-radio.bin` |
| ESP32-S3 | native USB Serial/JTAG | `pokeldn-radio-s3.bin` |
| ESP32-C3 | native USB Serial/JTAG | `pokeldn-radio-c3.bin` |
| ESP32-C6 | native USB Serial/JTAG | `pokeldn-radio-c6.bin` |
| classic ESP32, ESP32-C6 | Bluetooth LE (the iOS app), and USB as above | `pokeldn-radio-ble.bin`, `pokeldn-radio-ble-c6.bin` |

All targets use 2.4 GHz; ESP32-S2 is unsupported. An S3, C3 or C6 with separate UART and native USB
sockets must use the native socket (S3 GPIO19/20, C3 GPIO18/19); through the UART socket the firmware
never answers. When no firmware answers through a USB serial bridge, the desktop app reads the chip
from the ROM bootloader (esptool `detect_chip`) and names an S3, C3 or C6 as plugged into the wrong
socket. `303a:1001` is shared by several chips; flashing detects the chip with esptool.

| board | antenna | BOOT | user LED | CPU, task core | idle free heap | BENCH over native USB, macOS |
|---|---|---|---|---|---|---|
| XIAO ESP32C3 rev 0.4 | supplied external one, required | GPIO9 | none (charge indicator only) | 160 MHz, core 0 | 152656 | 880.1 KB/s |
| XIAO ESP32C6 rev 0.2 (C6FH4, 4 MB) | ceramic, selected by the firmware | GPIO9 | yellow, GPIO15, lit low | 160 MHz, core 0 | 255196 | 824.6 KB/s |
| XIAO ESP32S3 rev 0.2 (8 MB flash, 8 MB PSRAM) | supplied external one, required | GPIO0 | yellow, GPIO21, lit low | 240 MHz, core 1 | 212416 | 883 KB/s |

BENCH loses nothing; the host baud setting does not change USB speed. Larger S3 boards (N8R2, N16R8)
have an onboard antenna. Board guides: [XIAO ESP32C3](https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/),
[XIAO ESP32C6](https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/).

The XIAO ESP32C6 powers its RF switch while GPIO3 is low; GPIO14 low selects the ceramic antenna. The
C6 firmware drives both low before Wi-Fi starts; on the ESP32-C6-DevKitC-1 those pins reach only the
headers, so one image serves every C6 board. The C6 station is held to 11b/g/n. Its receive header
has no `sig_mode`, `mcs` or `cwb`: the firmware derives `sig_mode` from `cur_bb_format` and the HT MCS
from `he_siga1`, and its rate byte is the L-SIG rate code for an OFDM frame.

Completed trades per board are in [Trades by board](#trades-by-board).

### The USB link after a reset (C6, S3)

Opening the port resets a C6 or S3. With the ESP-IDF default `CONFIG_ESP_SYSTEM_BBPLL_RECALIB=y`,
startup stops the BBPLL that clocks USB Serial/JTAG (`recalib_bbpll()`,
`esp_system/port/soc/esp32c6/clk.c`), and the link can stay garbled until the board is unplugged
(SOF frame number frozen, `USB_SERIAL_JTAG_INT_RAW` `0000b5b2` against `0000b50a` healthy). The C6 and
S3 builds set it to `n` (allowed with a v5.2+ bootloader; every merged image carries its own): 900 of
900 C6 opens and 300 of 300 S3 opens answered. The C3 has no such option and no fault.

The C6 and S3 builds carry a USB watch (`usbwatch.c`): a SOF frame number stalled for 2 s restarts
the chip, and the next HELLO carries the USB and clock registers as LOG lines. It arms on the first
SOF frame or the first host byte read from the cable, and never restarts while a Bluetooth host is
linked: a board on a charger sees no SOF frame, and up to firmware 1.7.0 the Bluetooth host's bytes
armed it, so a C6 on a charger restarted every 2 to 3 s under the iPhone app. Built with `POKELDN_USB_BEACON=1`, either image also broadcasts those registers once a second as a
vendor action frame to `03:55:53:42:57:00` (layout in `usbwatch.c`), which `esp32_sniff.py --mac
03:55:53:42:57:00` keeps while USB is dead.

## Roles

| role | what the board does |
|---|---|
| idle | promiscuous on one channel; every action frame with the Nintendo LDN prefix `7f 00 22 aa` goes to the host |
| station | joins a console's network by BSSID with the host's derived CCMP key |
| access point | a hidden-SSID WPA2 network on the host's BSSID, keyed the same way |

A console's network has no 4-way handshake: both ends derive the CCMP key from the advertisement's
server random. The firmware replaces four entries of ESP-IDF's private `struct wpa_funcs` table
(`esp_wifi_driver.h`). The layout is the v6.1 blob's ABI; the firmware refuses to build against
another release.

| entry | replacement |
|---|---|
| `wpa_sta_connect` | installs the Switch station's RSN element (CCMP, PSK, capabilities `0x000c`) around the stock callback |
| `wpa_sta_rx_eapol` | drops EAPOL; keys go in with `esp_wifi_set_sta_key_internal` once the association response is seen, then `esp_wifi_auth_done_internal` opens the port |
| `wpa_ap_join` | adds the station and sends the association response (`esp_send_assoc_resp`) with no EAPOL-Key message 1 (`AP_START` flag bit 0 keeps the stock join); the main loop installs the pairwise key (`esp_wifi_set_ap_key_internal(CCMP, mac, 0, key)`) and opens the port (`esp_wifi_wpa_ptk_init_done_internal(mac)`), hostapd's `PTKINITDONE` order (`wpa_auth.c:2290-2332`); the group key goes in at `WIFI_EVENT_AP_START` with index 1 |

Trap: never wait for `WIFI_EVENT_AP_STACONNECTED` to install the key. Only
`esp_wifi_wpa_ptk_init_done_internal` posts it, so with no 4-way handshake it never comes and the
console's first encrypted frame is dropped.

## The access point's frames

The softAP's beacon, probe response and association response are built in the closed `libnet80211.a`
(v6.1 `ieee80211_output.o` offsets), compared with what `vendor/LDN`'s access point sends:

| field | Switch form | ESP32 softAP | settable |
|---|---|---|---|
| hidden SSID element | 32 zero bytes | length 0 (`ieee80211_beacon_construct` 0xc4) | no |
| Supported Rates | `82 84 8B 96 0C 12 18 24` | `8B 96 82 84 0C 18 30 60` | no; same twelve rates and basic bits, 9 and 18 in Extended |
| Extended Rates | `30 48 60 6C` | `6C 12 24 48` | no |
| capability, beacon | `0x0511` | `0x0431` (short preamble constant, `ieee80211_getcapinfo` 0x7b) | no |
| HT elements | none | present in 11b/g/n | removed: the firmware sets 11b/g |
| RSN capabilities | `0x000c` | hostapd's own | set: `wpa_ap_get_wpa_ie` returns the Switch's element |
| WMM | none | present in 11g | only 11b-only removes it |

A hidden softAP answers directed probes only. An association request without the configured SSID is
dropped (0x9c6). `esp_wifi_80211_tx` refuses association responses
(`ieee80211_raw_frame_sanity_check` 0xf9), and the blob's own beacons cannot be stopped.

## Serial protocol

A frame is `COBS(type | payload | crc32-le(type | payload))` then `0x00`; the CRC is CRC-32/ISO-HDLC
(`zlib.crc32`). The classic ESP32 boots at 115200 baud; `BAUD` switches both ends, and the board keeps
the rate until it resets. On S3,
`BAUD` is acknowledged without changing the USB transfer rate. Anything before a `0x00`,
the ROM's boot text included, fails the checksum and is discarded.

| type | direction | payload |
|---|---|---|
| `0x01` HELLO | host | none; answered by CREDIT 0, then INFO. The host sends a `0x00` first to end any partial frame |
| `0x02` BAUD | host | u32 baud; RESULT at the old rate, then the switch after the UART drains (up to 3 s); `open_serial` retries the first HELLO at the new rate |
| `0x03` CHANNEL | host | u8 channel; idle only |
| `0x04` STA_JOIN | host | u8 channel, 6 BSSID, 32 SSID (the LDN SSID's hex text), 16 key, 6 station MAC (zero = random); optional: u8 fixed data rate (the AP_START bits 3..5 table), u8 maximum TX power in 0.25 dBm (`esp_wifi_set_max_tx_power`, 8 to 84, the driver caps it at 61), u8 flags: 1 RTS before every frame, 2 no RTS before a retry (`esp_wifi_internal_set_rts`) |
| `0x05` STOP | host | none; back to idle, keys cleared |
| `0x06` AP_START | host | u8 channel, 6 BSSID, 32 SSID, 16 key, u8 max stations, u8 flags: 1 the stock association and 4-way handshake, 2 no QoS for the station, 4 no 40-byte copy of each station data frame, bits 3..5 a fixed data rate, `0x40` a beacon every 1000 TU, `0x80` no promiscuous receive; optional second flag byte: 1 the driver's noise-floor check off, 2 its interval 250, 4 the receive time in each 40-byte copy's head, 8 retry limits 7 and 4, `0x10` RX_CENSUS for every frame except its stations' good data frames; then an optional maximum TX power in 0.25 dBm |
| `0x07` AP_KICK | host | 6 MAC, u16 reason; deauthenticates |
| `0x08` ETH_TX | host | an Ethernet frame, encrypted by the driver with the station's or the group key. A full driver queue is retried every 1 ms for up to 100 ms; a frame to a departed station fails with `0x3015`. A station's Ethernet source must be the MAC in LINK or the frame is never acknowledged |
| `0x09` RAW_TX | host | an 802.11 frame without FCS (`esp_wifi_80211_tx`); advertisements |
| `0x0A` SNIFF | host | u8 channel, 6 MAC; every management and data frame to or from it and every action frame on the channel (an LDN advertisement keys the network a console moves to), whole, as RX_SNIFF; MAC ff:ff:ff:ff:ff:ff sends every frame on the channel as RX_CENSUS |
| `0x0B` STATUS | host | none; answered by STATUS |
| `0x0C` BENCH | host | u32 bytes, u16 message size (8 to 1600); RESULT, then BENCH messages as fast as the UART takes them |
| `0x0D` LED | host | u8 pattern, u8 peak brightness, u16 period ms (0: the pattern's default), u16 duration ms (0: until the next LED); RESULT |
| `0x0E` DISPLAY | host | a screen command ([The screen](#the-screen)); RESULT `0x105` without a screen |
| `0x0F` ALIVE | host | none, no reply; arms [the host watchdog](#the-host-watchdog); sent only to firmware 1.4.0 and later |
| `0x10` BEACON | host | u8 op: 0 WRITE u32 offset and bytes into the staging buffer, 1 COMMIT u16 length (checks and stores the staged image), 2 ERASE, 3 START, 4 QUERY (answered by BEACON); RESULT for the others. Firmware 1.8.0 and later ([Portable beacon](#portable-beacon)) |
| `0x81` INFO | board | u8 protocol version (1), 6 station MAC, 6 AP MAC, u8 chip revision, text |
| `0x82` RESULT | board | u8 command, i32 `esp_err_t` |
| `0x83` LOG | board | text |
| `0x84` RX_MGMT | board | u8 channel, i8 RSSI, a frame without FCS: an LDN action frame; while hosting also a management frame to the board's BSSID, the first 40 bytes of a data frame to it, and a station's no-DS broadcast whole |
| `0x85` RX_ETH | board | an Ethernet frame the driver decrypted |
| `0x86` LINK | board | u8 up, u16 reason, 6 MAC; reason `0xFFFF` no association in 15 s, `0xFFFE` keys refused |
| `0x87` STA_JOINED | board | 6 MAC, u8 AID, i8 key install result, u8 port opened |
| `0x88` STA_LEFT | board | 6 MAC, u16 reason |
| `0x89` STATUS | board | text counters (below); sent unasked every 2 s while hosting, polled every 5 s by a host writing a trace |
| `0x8A` BENCH | board | u32 sequence and payload bytes; the last carries sequence `0xFFFFFFFF` and the u32 microseconds the board spent |
| `0x8B` CREDIT | board | u32 host bytes read and handled since the last HELLO, counted from the byte after its delimiter; sent on HELLO, every 1024 bytes, when the line falls idle and every 100 ms while idle, ahead of any queued message |
| `0x8C` RX_SNIFF | board | u8 channel, i8 RSSI, u8 `sig_mode` (0 legacy, 1 HT), u8 legacy rate code (`wifi_phy_rate_t`), u8 HT MCS with bit 7 for 40 MHz, a frame without FCS; also every 10-byte ACK on the channel |
| `0x8D` TX_DONE | board | the driver's TX-done of one frame, station or access point: u32 board time µs, u32 µs since the ETH_TX it completes (all ones if none), u8 acked by the peer's radio, u8 interface, u16 length, the frame's first 24 bytes (its 802.11 header) |
| `0x8E` BUTTON | board | a BOOT press, debounced over 30 ms: u32 board time µs, u16 press count since boot; the host prints `BOOT button, mark N` and the trace keeps it |
| `0x8F` RX_CENSUS | board | every frame received, FCS failures and control frames included: u32 receive time µs, i8 RSSI, i8 noise floor, u8 `rx_state` (0 good), u8 packet type (0 management, 1 control, 2 data, 3 other), u8 `sig_mode`, u8 rate code, u8 MCS with bit 7 for 40 MHz, u16 `sig_len` with FCS, the frame's first 16 bytes |
| `0x90` BEACON | board | u8 an image is stored, u8 it is running, u8 fragments, u16 image length, u32 image CRC-32 (`zlib.crc32` of the whole image) |

`rx_state` 98 marks two-stream HT (MCS 8 to 15), which the single-stream ESP32 never decodes; 65 marks
a corrupted frame of any other modulation.

| STATUS counter | what it counts |
|---|---|
| `tx_acked`, `tx_unacked` | the driver's TX-done results |
| `tx_eth`, `tx_eth_failed`, `tx_eth_retried` | ETH_TX sent, failed, and calls that found the driver's queue full |
| `tx_queued_max_us`, `_total_us`, `_n`, `_pending` | ETH_TX to TX-done, over matched TX_DONEs |
| `wire_dropped`, `wire_rx_bad` | board-to-host messages dropped; host commands failing COBS or CRC |
| `uart_fifo_ovf`, `uart_buffer_full`, `uart_overflow` | 128-byte hardware FIFO and 16 KB ring overflows, and their sum |
| `uart_frame_err`, `uart_events_full` | framing, parity and break events; ticks with the UART event queue full (the counters may undercount) |
| `read_max_us`, `write_max_us`, `handler_max_us`, `handler_max_type` | the longest host-link read turn (20 ms timeout included), writer wait, and command with its type |
| `heap_min`, `queue_max`, `refused_heap`, `refused_queue` | least free heap, deepest outgoing queue, messages refused at the heap floor and on a full queue |
| `tx_eth_max_us`, `tx_eth_total_us`, `tx_eth_slow` | ETH_TX in `esp_wifi_internal_tx`, retries included: longest, sum, count over 5 ms |

EtherType `0x88B7` frames are LDN authentication; `esp32_wlan` turns them into the LDN library's
`CustomFrameEvent`. Every other Ethernet frame goes to an L2 port, chosen by `POKELDN_L2=tap|userspace`:

| port | where | the launchers' sockets |
|---|---|---|
| `userspace_ip` stack | the default, every platform | `userspace_ip.udp_socket` and `packet_socket` |
| kernel TAP named after the interface | Linux, `POKELDN_L2=tap` only | kernel sockets, `SO_BINDTODEVICE` and `AF_PACKET` unchanged |
| `MemoryPort` | tests | none |

Creating a TAP needs `CAP_NET_ADMIN`.

### The host watchdog

The host sends ALIVE every second (`esp32.ALIVE_EVERY`) to firmware 1.4.0 and later. The first ALIVE after a HELLO arms the watch; HELLO disarms it, so a host that never
sends ALIVE is never watched. Armed, a board out of idle that reads no host command for 5 s
(`HOST_SILENT_US`) runs STOP's teardown: an access point stops beaconing and its stations drop, a
station disconnects. It then discards every message for the host, uncounted, until the host sends a
command again; otherwise each queued message costs a 500 ms write, a `wire_dropped` and a
constant `flash3` on the LED. With the host killed during a FireRed trade room, the console shows
2318-0006 and a later JOIN search lists no host.

## Portable beacon

From firmware 1.8.0 the board stores one LDN advertisement cycle in NVS and sends it with no host.
With an image stored and no host command in the 3 s after power-up, it starts the image's access
point, replays up to four screen commands, and sends one advertisement every `interval_ms` (100),
moving to the next fragment every `dwell_ms` (500). HELLO, CHANNEL, SNIFF, STA_JOIN, STOP and
AP_START end it; a host the watchdog judges gone leaves it running. `pokeldn.ldn.portable` builds the image from the
network `ldn.create_network` would create; `bin/swsh_gift_host.py --save-to-board` stores a Sword and
Shield Mystery Gift ([Sword and Shield Mystery Gift](swsh_gift.md)).

The board builds each frame as the host does (`firmware/esp32/main/advert.c`, PSA SHA-256, AES-CTR
and AES-GCM): the stored header, the fragment's payload, and a nonce that starts at a random value
at each start and rises by one per fragment, as `set_application_data` raises it on the host.
`tests/test_esp32_beacon.py` compiles `advert.c` and compares its frames with the LDN library's,
byte for byte, for protocols 1 and 3.

| offset | size | field (little-endian) |
|---|---|---|
| 0 | 4 | `PKSA` |
| 4 | 1 | layout, 1 |
| 5 | 1 | kind, 1 (an advertisement cycle) |
| 6 | 2 | image length, CRC included |
| 8 | 1 | channel |
| 9 | 6 | BSSID |
| 15 | 32 | SSID, as AP_START takes it |
| 47 | 16 | data key |
| 63 | 1 | max stations |
| 64 | 16 | advertise key |
| 80 | 40 | advertisement header: network id, version, format, u16 BE size, u32 BE nonce |
| 120 | 2 | `interval_ms`, 20 to 1000 |
| 122 | 2 | `dwell_ms`, at least `interval_ms` |
| 124 | 1 | fragments, 1 to 8 |
| 125 | 1 | screen commands, 0 to 4 |
| 126 | 2 | zero |
| 128 | | per fragment u16 length and the advertisement's plaintext; per screen command u16 length and a DISPLAY payload |
| end | 4 | `zlib.crc32` of everything before it |

The image holds the advertise and data keys derived for its one network, never `prod.keys`. An image
is at most 12288 bytes. From firmware 1.9.1 the stored image is read from NVS before the board answers
its first command; 1.9.0 answered a BEACON QUERY sent right after a port open with "none stored". A board left on a computer's USB with no app open starts the beacon as on a
charger.

### A host image

From firmware 1.9.0 an image of kind 2 makes the board answer each console's join itself and play
the session `bin/frlg_mg_host.py` plays, so a FireRed or LeafGreen receives a Mystery Gift from the
board alone. `bin/frlg_mg_host.py --save-to-board` (the app's Keep it on the board) stores one;
`pokeldn.frlg.gift.portable` builds it by constructing the host application the launcher would run
and keeping what that host computes before a console joins. A Wonder Card, Wonder News, a Stamp
Rally stamp, a visiting trainer and a Mystery Event script fit in 2 to 4 KB; a buffer script and a
save backup or restore read their answer on the computer and are refused.

Kind 2 has no fragments (byte 124 is 0) and an AES-GCM header only. After the screen commands come
records to the CRC, each u8 tag, u16 length and bytes (`firmware/esp32/main/gift.h`):

| tag | record | written by |
|---|---|---|
| 1 | LDN: the advertisement plaintext up to and with the host's 48-byte station entry, the authentication header's network id (little-endian), the 16-byte key the authentication key is decrypted from, the 32-byte challenge key, u64 challenge, u64 device id, version, platform | `pokeldn.ldn.portable.ldn_record` |
| 2 | Pia: the session key `AES(game key, SSID)`, u32 network id, the host's IPv4 address, player id and name | `portable.pia_record` |
| 16, 17 | the application data before and after the console's LinkPlayer block | `pokeldn.frlg.gift.portable` |
| 18 | the host's 200-byte LinkPlayer block and the RFU parent id | |
| 19 | `MysteryGiftTiming`'s eight fields, flags (1 native nonces, 2 join response first, 4 trust Pia), u32 protocol tick µs | |
| 20 | game family (0 FireRed/LeafGreen, 1 Emerald), the expected console (0 any) | |
| 21 | the server script compiled to bytecode: every `SVR_LOAD_*` becomes a slot | |
| 22 | a payload: u8 ident, u16 size (0 is the 1024-byte buffer), bytes; one per distinct message | |
| 23 | a cartridge served: game code (four zeros serve any), card flag id, icon, stamp fields, a payload per slot | |

The authentication key is `AES-ECB-decrypt(K, SHA-256(client random)[:16])`, where `K` is the third
step of `KeyDerivation._derive_key` for source `f1e7018419a84f711da714c2cf919c9c`, a key derived
for LDN protocol 3. Every screen command but the last plays at start; the last is the delivered
scene, played after a session that delivered, then the start ones again.

The engine is pure C and ports one Python module per layer, line for line:

| file | ports |
|---|---|
| `gift_ldn.c` | `ldn.APNetwork`'s authentication and challenge reply, the advertisement as a station sits down, `userspace_ip`'s ARP and IPv4/UDP, `host_app.py`'s run loop |
| `gift_pia.c` | `crypto.PiaCrypto`, `reliable.parse_messages`, `pia_connect`'s Net, Session and RTT codecs, `host_pia.HostPeerProtocol` |
| `gift_link.c` | `reliable.HostReliableSession`, `ni.py`, `rfu_leader.RFULeader`, `host_session.HostSession` |
| `gift_mg.c` | `host_mystery_gift.HostMysteryGiftEngine`, `block.BlockSender` and `RecvBlock`, `mg_link`, the server script |
| `gift_zstd.c` | zstd 1.5.6's decoder (`vendor/zstd`) |

The beacon task runs it: the driver's frames and associations reach it through a queue, it runs its
timers at the deadline it returns, and it rebuilds the advertisement every `interval_ms` with the
nonce raised once per change. A station's broadcasts (its ARP for the host first) come with no DS
bits under the group key, which the access point drops: the engine takes them whole from the
promiscuous callback and decrypts them itself, AES-CCM with an 8-byte MIC over the LDN library's
nonce and AAD, QoS or not ([A station's broadcasts](ldn.md#a-stations-broadcasts)). A retail
ESP32-S3 hands them on already decrypted under the installed group key, Protected bit, CCMP header
and MIC kept (a FireRed ARP is 76 bytes); from firmware 1.9.1 a body that starts with the SNAP header
after the CCMP header is taken as plaintext, as the host's `accept_decrypted_ccmp` does. Firmware
1.9.0 dropped them, and the console left with a communication error after authenticating. A console compresses most of its datagrams (1056 of 1363 in one
Wonder Card session); the decoder context is 38,464 bytes with a 1 KB literal buffer. Datagrams the
host compresses go out as zstd frames of one raw block. The engine's state is about 41 KB, taken
from the heap with the decoder's at start.

The board seats one console at a time and refuses another's authentication with status 1. A
console whose game code no cartridge record names, or whose game data the script refuses, is
disconnected with nothing sent past the game-data request. A seated console silent for 60 s, or
one still seated 30 s after the RFU close, is disconnected. When the console leaves, after a 2 s
settle once it confirmed the close, the board serves the next one on the same network and keys.

`tests/test_esp32_gift.py` compiles the engine and zstd and runs it on a simulated board against
`bin/frlg_mg_client.py` in the console's place, which resolves the host with an ARP and opens its
Reliable stream at its own Session type 6 as a retail FireRed does; its broadcasts reach the board
encrypted by the LDN library with no DS bits. A Wonder Card, the card already held, a refused replacement, a
stamp and Wonder News each end with the messages `MysteryGiftServer` sends for that console, byte
for byte; a second console is served after the first; a cartridge the image does not serve is
refused. A XIAO ESP32S3 on firmware 1.9.1, powered with no host, delivered a Wonder Card to a retail
French FireRed and served it again to the console that held it.

## The serial ceiling

The classic ESP32 UART at 921600 baud carries 92.16 KB/s board to host; Pia payloads are ciphertext
and do not compress. A hosting board also sends a 48-byte RX_MGMT copy of each station data frame
unless AP flag 4 is set (`POKELDN_ESP32_AP_FLAGS=4`); each nearby LDN network adds about ten
advertisements a second.

The outgoing queue holds 384 messages and refuses one below 64 KB of free heap; under a console at
the line's rate the heap floor refuses RX_ETH before the queue fills.

### Baud rate

`POKELDN_ESP32_BAUD` sets the rate `open_serial` switches to, 921600 by default; the USB bridge sets
the limit. On the ELEGOO board's CP2102 on macOS, 1500000 carries 149.1 KB/s with no loss, and
2000000 and 3000000 never answer HELLO. `tools/ldn/esp32_bench.py --port PORT --bauds LIST` streams
BENCH at each rate.

### Host-to-board command loss and CREDIT

Under a console's flood the board can lose host commands before the handler. The firmware's
countermeasures, each measured against its absence:

| cause | the firmware |
|---|---|
| UART interrupt on core 0 with the Wi-Fi task | driver installed from the reader task, core 1 |
| a blocked ETH_TX lets the 16 KB ring and 128-byte FIFO overflow | CREDIT flow control |
| FIFO drained at 120 bytes, 53 µs from full at 1500000 | threshold 32 (`uart_set_rx_full_threshold`), 640 µs |
| `uart_read_bytes` (IDF 6.1 `uart.c:1738`) waits its timeout per ring item | wait for one byte, then take `uart_get_buffered_data_len` |
| `uart_write_bytes` busy-loops on a full TX ring, starving the reader | the writer sleeps until the frame fits (`uart_get_tx_buffer_free_size`) |
| `UART_DATA` events fill the 64-entry queue that carries overflow events | a task above the reader drains it every tick; `uart_events_full` |

Once the board has sent a CREDIT, the host's writer thread keeps under 8 KB written and unreported
(`esp32.FLOW_WINDOW`); a launcher's trio loop only queues, and ETH_TX and RAW_TX past 512 queued
frames are dropped (`Radio.tx_dropped`). A count repeated unchanged for 0.3 s while the window is shut
means bytes were lost, and the host reopens the window (`Radio.flow_resyncs`). Never resync on
silence alone: a busy reader holds up to 0.7 s, and a resync then puts 16 KB in flight against a
16 KB ring. The board credits every 1024 bytes (`wire.c` `CREDIT_STEP`), so the host counts a CREDIT
against bytes written plus the frame on the line. A board without CREDIT is written to unthrottled.
The board logs a command over 50 ms (`slow command`) and a reader turn over 100 ms (`reader held`).

A HELLO restarts both counts, so the host holds it until nothing is in flight and keeps the window
shut until the board's CREDIT 0 (`tests/test_esp32.py::test_a_hello_mid_session_does_not_open_the_window`).
`tools/ldn/esp32_cmd_loss.py TRACE` reconciles a trace: ETH_TX written against `tx_eth +
tx_eth_failed`, bytes written since HELLO against the last CREDIT.

### Transmit timing

ETH_TX spends about 0.1 ms in the driver and waits about 1 ms median for TX-done. Under a flood
TX_DONE reaches the host up to 0.6 s late. Traps: a sniffer board's own line backs up in a burst, so
time delivery by the peer's acknowledgements; an access point flood is broadcast at 1 Mbit/s and
fills the air past about 90 frames a second.

## Holds and receive misses

With the board as access point in a FireRed trade, a frame usually completes in about 1 ms; now and
then one frame the console has not acknowledged holds 100 to 260 ms while the frames behind it
complete in a burst, and the board hears neither the console's data nor its ACKs. The channel decides
the holds: on a channel shared with a busy access point most trades held, on channel 11 none did.
`config/host.local.toml` takes a `[host] channel`; the console joins a host on 1, 6 or 11. The 240 MHz
CPU and a pinned rate (AP flag bits 3..5: 1, 11, 6, 12, 24, 36, 54 Mbit/s for 1 to 7) do not remove
holds. `tools/ldn/esp32_hold.py CAPTURE TRACE` splits each wait into stages,
`tools/ldn/esp32_hold_air.py` lists what a sniffer saw, and `tools/ldn/esp32_rx_copies.py` matches the
console's retries to the board's receive misses.

### Receive misses on two boards

As an access point the board misses 1 to 22% of a station's OFDM first copies; DSSS at 1 Mbit/s is
almost never missed. `tools/ldn/esp32_pair_bench.py AP STA --flood 0 --burst N --send R` counts them.
Misses concentrate on a frame that follows the board's own transmission, such as data 60 µs after its
6 Mbit/s CTS. Lower on a quiet channel (0.8 to 2.3% on 3 to 9), with RTS before every station frame
(STA_JOIN flag 1), and at full station power.

No change from the beacon interval, promiscuous receive, the noise-floor check, receive buffers,
CPU clock, IRAM optimisation, access point power or ESP-IDF v5.5.5 against v6.1. Most misses leave no
trace at the access point, not even an FCS failure.

A station sends every retry behind an RTS (`lmacConfMib` +42, threshold at +22;
`esp_wifi_internal_get_rts`/`_set_rts`). `lmacRetryTxFrame` resends up to `lmacConfMib` limits (short
+21, long +20, 32 by default; `esp_wifi_internal_set_retry_counter`). The ACK and CTS rate table is at `0x3ff73400`..`0x3ff7341c`.

## The userspace stack

`pokeldn.ldn.userspace_ip` carries IPv4, UDP and ARP inside the host process. A stack is registered
under the interface name (`ldnclient` for joiners, `ldn-tap` for an access point);
`userspace_ip.lookup(name)` returns None for a kernel interface, which is how every launcher picks its
path. Addresses and neighbours come from the LDN library's `add_address` and `add_neighbor` and from
received frames; a unicast destination with no neighbour sends an ARP request and drops the datagram;
`.255` goes to broadcast. Datagrams over 1472 bytes are fragmented, fragments reassembled (5 s).
`udp_socket(port)` and `packet_socket()` stand in for a bound UDP socket and an `AF_PACKET` socket,
each backed by a socket pair with one byte per queued datagram, so `select` and
`trio.lowlevel.wait_readable` work on every platform.

Trap: the board's frames reach the stack through trio tasks in the launcher's own trio loop. Never
block in `select` inside that loop; wait with `trio.lowlevel.wait_readable` under
`trio.move_on_after`.

## The board's LED and buttons

The LED is GPIO2 on classic ESP32, GPIO21 inverted on S3, GPIO15 inverted on C6; the C3 firmware
leaves LED pins alone. BOOT is GPIO0 on classic ESP32 and S3, GPIO9 on C3 and C6; each press sends
BUTTON (`0x8E`), flashes the LED and wakes the screen. On the ELEGOO ESP-32 Type-C board (CP2102,
ESP32-D0WD-V3, unbranded PCB-antenna module) the red LED is the power rail and the blue one GPIO2.
GPIO2 and GPIO0 are strapping pins; the firmware drives GPIO2 only after boot.

The LED runs LEDC PWM (13 bits, 5 kHz) every 10 ms with gamma 2.2 and 150 ms crossfades.

| pattern | id | default period | shape |
|---|---|---|---|
| auto | 0 | | the mode's look, below |
| off, on | 1, 2 | | |
| breathe | 3 | 3000 ms | raised cosine |
| blink | 4 | 1000 ms | on for half the period |
| flash3 | 5 | 1000 ms | three flashes in the first 60 % of the period |
| ramp-up, ramp-down, pulse | 6, 7, 8 | 1000, 1000, 1200 ms | once |

The automatic look: one pulse at boot, a dim 4 s breathe idle, a 250 ms blink while joining, a
brighter 1.5 s breathe hosting with no station, dim on when linked, off while sniffing.

Every frame flickers the LED on top. A failed join, a refused key, a dropped board-to-host message or
a lost host command plays flash3 for 1.5 s. A completed trade or Mystery Gift ramps up to full
(`pokeldn.ldn.show_done`). `tools/ldn/esp32_led.py --port PORT PATTERN` sets a look; `--demo` shows
each.

## The screen

An SSD1306 128x64 OLED on I2C is optional (SSD1315 and SSD1309 modules also work). The firmware
probes 0x3C, then 0x3D, and with a screen draws a frame every 50 ms at 400 kHz.

| target | SDA | SCL | board pins |
|---|---|---|---|
| ESP32 | GPIO21 | GPIO22 | DevKit V1 D21, D22 |
| ESP32-S3 | GPIO8 | GPIO9 | |
| ESP32-C3 | GPIO6 | GPIO7 | XIAO D4, D5 |
| ESP32-C3 | GPIO5 | GPIO6 | the 0.42-inch OLED board's own 72x40 screen, probed second |
| ESP32-C6 | GPIO22 | GPIO23 | XIAO D4, D5 |

The common four-pin module carries its own regulator and pull-ups; its address resistor selects 0x3C
(silkscreen 0x78) or 0x3D (0x7A). The firmware sets segment remap (`A1`), reversed COM scan (`C8`)
and alternative COM pins (`DA 12`). The ESP32-C3 0.42-inch OLED board's 72x40 panel shows columns
30..101 and rows 24..63 of the frame; a screen on those pins gets compact scenes (one 12-character
line, half-size sprites), rendered offline by `tools/ldn/screen_preview.py --panel 72x40`.

Without host commands the screen shows the radio's state: idle, joining or hosting, and linked, with
the frames counted in each direction. It is at full brightness while the radio is active or an
animation plays and for 60 s after the last DISPLAY, HELLO or BOOT press; then it dims to contrast 1
with pre-charge `22` (`81 01 D9 22`), and after 600 s turns off (`AE`). Lower pre-charge flickers.
The idle scene shifts 2 pixels every 60 s against burn-in. `tests/test_esp32_screen.py` holds the
timings.

DISPLAY (`0x0E`) carries one op:

| op | layout |
|---|---|
| `0` SHOW | u8 show, u16 hold s (0: until the next show), title, NUL, line, NUL; each text at most 21 ASCII characters |
| `1` SPRITE | u8 slot (0 ours, 1 theirs, 2 gift), u8 width <= 64, u8 height <= 64, rows of `(width + 7) / 8` bytes, MSB first; width 0 empties the slot |
| `2` LOBBY | u8 stars (0..7, 0: none), u8 joined, u8 seats (1..3, at least joined), title, NUL, name, NUL, Link Code, NUL; starts the lobby show |
| `3` JOINED | u8 joined, at most the lobby's seats; refused without a lobby show |

| show | id | drawn |
|---|---|---|
| auto | 0 | the radio's state |
| trade | 1 | slot 0 with "offering" and the line |
| traded | 2 | slot 0 leaves in its ball (2.1 s), packets cross until the hold, a ball arrives and opens (1.6 s), then slot 1 "received" for 10 s |
| gift | 3 | a Wonder Card holding slot 2 |
| gifted | 4 | the card leaves, then "delivered!" |
| arrived | 5 | a traded show still waiting brings its ball in now |
| lobby | LOBBY | slot 0, title, name, stars, "joined/seats" and the code |

A show waits for a playing traded or gifted show; shows end when the radio returns to idle.

`pokeldn.app.screen` is the launchers' side: `offer`, `received`, `arrived`, `gift`, `delivered`,
`lobby` and `joined` return at once and run in order on one thread. Hosted raids put up a lobby. Every
launcher calls `received` at the trade's last step with a hold of the time below less 2.5 s, so the
ball opens with the console's:

| title | from | received Pokemon on the console | first message after the animation |
|---|---|---|---|
| FireRed/LeafGreen | START_TRADE | 22.7 s | READY_FINISH_TRADE ([FireRed link](frlg_link.md)) |
| Let's Go | step `0e` | 15.3 s | the type 4 payload ([Let's Go session](lgpe_session.md#the-trade-animation)) |
| Sword/Shield | the last syncCommand 40 | 15.0 s | none ([Sword trade](swsh_trade.md#the-trade-animation)) |
| BD/SP | `tradeState` 5 | 18.6 s | none ([BDSP trade](bdsp_trade.md#the-completed-trade)) |
| Legends Arceus | `01 0e` | 28.5 s | the box message `00 02` ([Legends Arceus](pla.md#the-completed-trade)) |
| Scarlet/Violet | `8001010e` | 19.8 s | none ([Scarlet and Violet](sv.md#the-trade)) |
| Legends Z-A | the fourth step | 26.2 s | the next `01 01` preview ([Legends Z-A](za.md#a-trade-with-a-retail-console)) |

Times were marked by hand (up to 2 s late). The launcher calls `arrived` at the message after the
animation. Sprites are PokeAPI's FireRed/LeafGreen ones up to
species 386 and the default after, cropped, scaled to at most 64 (40 on a card) and thresholded to
one bit with the inner lines kept dark. `tools/ldn/esp32_screen.py --port PORT` plays a trade and a
gift on a board; `tools/ldn/screen_preview.py OUT.gif` renders a scripted session offline.

### The E32R40T board

The E32R40T (sold as the 4.0-inch ESP32-32E display) is a classic ESP32 with a 480x320 ST7796S panel
on SPI. Its firmware is a separate build, `POKELDN_DISPLAY=E32R40T` in the environment of `idf.py`
(the default is `OLED`); the release images are OLED builds.

| signal | GPIO |
|---|---|
| CS, DC, SCK, MOSI | 15, 2, 14, 13 |
| backlight, lit while high | 27 |
| RGB LED, lit while low: red, green, blue | 22, 16, 17 |

The panel shows the 128x64 frame at 3x (384x192), black on white, at 40 MHz SPI. GPIO2 is the
panel's DC, so the board's LED is the blue one on GPIO17. The backlight goes off when the OLED would.

## Building and flashing

The firmware version (`firmware/esp32/version.txt`, `major.minor.patch`, shared by all targets) is
reported in INFO as `version=...`; an unversioned build shows `version unknown` and works when its
serial protocol matches. The protocol number is separate and changes only with the wire contract.

ESP-IDF v6.1 (tag `v6.1`, commit `fff9895c82d744c7237be8847347bdd1b07c6643`) builds all four targets.
Install its tools with `install.sh esp32,esp32s3,esp32c3,esp32c6`, then activate the IDF environment.

    cd firmware/esp32
    idf.py set-target esp32   # esp32s3, esp32c3 or esp32c6 for those chips
    idf.py build
    idf.py -p <port> flash

Console output is off; on classic ESP32 the firmware assigns UART0's GPIO1 and GPIO3 itself
(`uart_set_pin`). The desktop app detects the chip with esptool and validates the merged image's
bootloader at the chip's flash offset (ESP32 `0x1000`, others `0x0`) before writing: esptool 5.4.0's
`write_flash` can skip its chip check when an image starts with padding. Never choose firmware from a
USB bridge ID.
[Desktop builds](gui.md) covers packaging all four images.

### Bluetooth

A build with `POKELDN_BLE=1` also carries the host link over Bluetooth LE, for the iOS app, which
cannot open a USB serial device; the board then needs USB only for power.

    POKELDN_BLE=1 idf.py -B ../../scratchpad/esp/build-ble \
        -D SDKCONFIG=../../scratchpad/esp/build-ble/sdkconfig \
        -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.ble" build

The board advertises only its name, `POKELDN-RADIO`; the iOS app scans with no service filter. The
service is `7a1e0101-5d2c-4c3e-9f4b-504f4b454c44`: the host writes the COBS stream to `...0102`
(write without response) and the board notifies on `...0103`. While a central is subscribed to
`...0103` the wire runs there and the cable falls silent. Framing, CRC and CREDIT are unchanged. HELLO
text ends in `link=ble`, which the Board page shows as the Bluetooth wireless firmware.
`POKELDN_RADIO=esp32:ble` (or `esp32:ble:NAME`) opens it from any launcher (`pokeldn/ldn/esp32_ble.py`,
bleak).

The BLE build takes the BLE-only controller, 10 static Wi-Fi RX buffers and a 10 KB receive buffer,
and releases Classic Bluetooth memory: the dual-mode controller leaves free heap under the wire's
64 KB floor. Over BLE the board sends no TX_DONE and gathers queued frames into one notification. It
asks for a 15 ms interval (again once the central subscribes; `ble_itvl_us` in STATUS), the 2M PHY, a
247-byte MTU and data length extension; at 30 ms a FireRed room crawls.

The classic ESP32 (Bluetooth 4.2, no 2M PHY) benches 28.1 KB/s and completes a FireRed host trade
but is too slow for a FireRed joiner (2318-0013). The XIAO ESP32C6 benches 33.6 KB/s and completes a
FireRed joiner trade. Every radio build takes ESP-IDF's single-app-large table (a 1500 KB factory
app at 0x10000; nvs at 0x9000 and phy_init at 0xf000 as before); the C6 BLE image (0xfd000 bytes)
leaves 488 KB of it.

On macOS, bleak aborts (SIGABRT) in a process whose responsible app has no Bluetooth grant; a script
started with `open -n -a Terminal FILE.command` runs under Terminal's.

### The USB host link

The S3, C3 and C6 use the same COBS, CRC and CREDIT protocol over USB Serial/JTAG with 16 KB rings.
The writer retries a refused `usb_serial_jtag_write_bytes` every 20 ms and counts a dropped message
after 500 ms. The receive interrupt drops a 64-byte packet on a full RX ring and counts nothing
(`usb_serial_jtag.c:144`); CREDIT keeps the ring from filling. UART counters stay zero on this path,
and `POKELDN_ESP32_BAUD` changes only the classic ESP32's rate. On USB targets the reader runs at
priority 21, above the writer (20): below it, the writer starves the reader under a full-rate stream.

The host sets a 1 s write timeout; a failed or short write ends the session as a board loss. After
HELLO, 1 s without a valid frame queues a STATUS probe, and 3 s of silence ends the session with a USB
error asking the user to replug the board.

A two-hour host-to-board soak with no console (one baud value; native USB ignores it):

```sh
./.venv/bin/python tools/ldn/esp32_bench.py --port COM5 --bauds 921600 \
    --soak 7200 --size 1400 --rate 460000
```

It prints frames, bytes, credits and STATUS every 5 s and exits nonzero on a USB failure or a frame
count mismatch. It reproduces neither the console's acknowledgements nor its Wi-Fi load.

## Running

`POKELDN_RADIO=esp32:<port>` puts every launcher's `ldn` calls on the board. `esp32:auto` takes the
only USB serial port present and refuses to choose between several, since opening a port can reset
its board. The port is opened once per process with DTR and RTS released; a CP2102 board on macOS
resets on open regardless. A board that
does not reset keeps the previous `BAUD`, so the host tries HELLO at 115200, `POKELDN_ESP32_BAUD`,
921600 and 1500000 in turn before switching to the requested rate.
On Windows a COM port opens exclusively (`PermissionError(13, 'Access is denied.')`), so the launcher
closes a silent board's port before retrying, and a board unplugged mid-run ends it with `[esp32] The
board disconnected from USB`. With a CP2102, RTS asserted alone holds EN low and the board stays
silent. A board in ROM download mode never answers HELLO.

On the board the launchers skip every nl80211 step (`--phy auto` resolves to `esp32`), need no root
and inject no beacons; a joiner's `--mac` becomes the board station's address. A console hosting on
5 GHz cannot be reached.

`POKELDN_ESP32_TRACE=FILE` appends every serial message, one line each: Unix time, `>` (host) or `<`
(board), type and payload in hex.

`tools/ldn/esp32_first_contact.py` checks a new board (`--flash` writes the build, then HELLO,
STATUS, an idle scan counting LDN action frames per channel, and with `--keys` a decrypting scan);
`tools/ldn/esp32_sniff.py` runs a second board as a sniffer; `tests/test_esp32.py` runs the LDN
host and station on two simulated boards (`pokeldn.ldn.esp32_sim`). A CH9102 or CH343 bridge
enumerates as CDC ACM (`/dev/ttyACM0`, `/dev/cu.usbmodem*`).

### A board that decodes no OFDM

A console's advertisements are HT MCS 3 ([Discovery](ldn.md#discovery)), so a board that cannot
demodulate OFDM hears no advertisements: `esp32_first_contact.py` counts 0 LDN action frames on every
channel, while association and ping still work at DSSS. `tools/ldn/esp32_census.py` next to a busy
access point tells it apart: a working board lists `OFDM` and `HT` good frames, a deaf one only
`DSSS`, with OFDM frames failing at `rx_state` 65. One generic ESP32-WROOM-32 DevKit (ESP32-D0WD-V3
rev 3.1, CP2102) is deaf; a WROOM-32E board with the same chip works
([issue 1](https://github.com/Decryptu/pokeldn/issues/1)).

## Trades by board

The ELEGOO board (ESP32-D0WD-V3 rev 3.1, CP2102, 921600 baud) trades with retail Switch 2 consoles
in every title, as station and access point, and delivers FireRed and Sword Mystery Gifts. The XIAO
ESP32C3, ESP32C6 (ceramic antenna) and ESP32S3 complete FireRed trades in both roles and Sword host
trades, the C6 also Scarlet host trades; an ESP32-S3 on Windows completes a FireRed joiner trade
([PR 2](https://github.com/Decryptu/pokeldn/pull/2)). The [Android app](../examples/android/README.md)
hosts FireRed through a XIAO ESP32C6 at 51.1 parent slots a second once its Python threads are pinned
to one performance core.

A FireRed console joining the board's access point accepts its zero-length hidden SSID, rate order,
capability `0x0431` and WMM element, and sends one association request: listen interval 10, the SSID
as 32 hex characters, rates `02 04 0b 16 0c 12 18 24` and `30 48 60 6c`, power capability `00 14`, RSN
capabilities `0x0000`, a WMM information element, vendor element `00 22 aa 10 01 02`. Its first
broadcasts need the firmware's forwarding ([A station's broadcasts](ldn.md#a-stations-broadcasts)).

### Joining

`STA_JOIN` makes one association attempt: a fast scan on the channel and BSSID, then open
authentication and association; `LINK` comes up 0.23 to 0.34 s later. A retail Sword's network can
fail an attempt (`LINK` down, reason `0xc9` or `0x2`) while its advertisements are still heard, and a
new attempt then associates, so the host sends `STA_JOIN` up to three times
(`pokeldn.ldn.esp32_wlan.JOIN_ATTEMPTS`). Why an attempt misses is unknown.

## Unresolved

- The softAP negotiates WMM, which a Switch host does not; trades complete with and without it
  (`POKELDN_ESP32_AP_FLAGS=2`, `AP_FLAG_NO_QOS`, clears the station's QoS flag).
- What in the access point's receive path misses a station's OFDM first copies is unknown
  ([Receive misses on two boards](#receive-misses-on-two-boards)).
- Whether an ESP32-WROOM-32E module misses fewer frames than the ELEGOO board's unbranded module is
  unmeasured. A user report says the older ESP32-WROOM-32 does not trade reliably; one WROOM-32 DevKit
  decoded no OFDM ([A board that decodes no OFDM](#a-board-that-decodes-no-ofdm)).
- A Scarlet console joined to the board's access point can acknowledge the announcement and send no
  port 2 join ([Scarlet and Violet](sv.md#unresolved)).

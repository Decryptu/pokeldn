---
title: ESP32 radio
parent: Hardware and setup
nav_order: 1
---

# ESP32 radio

An ESP32 board on USB serial is the radio. It runs `firmware/esp32/` and carries LDN's vendor
action frames and Ethernet frames; advertisement crypto, LDN authentication, IP and Pia stay on the
host. `pokeldn.ldn.esp32_wlan` gives the LDN library a factory backed by the board, so `ldn.scan`,
`ldn.connect` and `ldn.create_network` run unchanged and the host needs no Wi-Fi driver.

## Supported boards

| chip | host connection | merged image |
|---|---|---|
| classic ESP32 (ESP32-D0WD, WROOM-32E) | UART0 through a USB serial bridge | `pokeldn-radio.bin` |
| ESP32-S3 | native USB Serial/JTAG | `pokeldn-radio-s3.bin` |
| ESP32-C3 | native USB Serial/JTAG | `pokeldn-radio-c3.bin` |
| ESP32-C6 | native USB Serial/JTAG | `pokeldn-radio-c6.bin` |

All targets use 2.4 GHz. ESP32-S2 is unsupported. The Seeed Studio XIAO ESP32C3 and XIAO
ESP32S3 have no onboard antenna and need their supplied external one attached; larger S3 boards
such as the N8R2 and N16R8 carry an onboard antenna. An S3, C3 or C6 board with separate UART
and native USB sockets needs the native socket for radio communication. USB Serial/JTAG uses
GPIO19 (D-) and GPIO20 (D+), as described in
[Espressif's USB guide](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-guides/usb-serial-jtag-console.html).
On C3, native USB uses GPIO18 (D-) and GPIO19 (D+), as described in
[Espressif's C3 USB guide](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/api-guides/usb-serial-jtag-console.html).
The USB identifier `303a:1001` is shared by several chips; flashing detects the chip with esptool.
Flashing an S3 through its UART socket (a WCH CH343 bridge on a DevKitC) succeeds, and the firmware
then never answers on that socket. When no firmware answers through a USB serial bridge, the desktop
app reads the chip type from the ROM bootloader (esptool `detect_chip`, then a hard reset) and names
an S3, C3 or C6 found there as plugged into the wrong socket.

The Seeed Studio XIAO ESP32C3 uses its USB-C socket for native USB Serial/JTAG.
Attach its supplied external antenna before radio use. BOOT is GPIO9, and the onboard LED
is a charging indicator ([Seeed's board guide](https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/)).
The C3 build runs at 160 MHz. Wire and button tasks run on core 0; the dual-core targets keep
these tasks on core 1.

A XIAO ESP32C3 revision 0.4 over native USB on macOS carries a 2,000,000-byte BENCH transfer as
1429 messages with none missing and no bad checksum, at 880.1 KB/s with the host baud setting at
115200 and 878.3 KB/s at 1500000: the host baud setting does not change USB speed. Its idle free
heap at start is 152656 bytes.

The Seeed Studio XIAO ESP32C6 (ESP32-C6FH4, 4 MB embedded flash) uses its USB-C socket for native
USB Serial/JTAG. Its RF switch is powered while GPIO3 is low, and GPIO14 selects the ceramic antenna
(low) or the U.FL socket (high) ([Seeed's board guide](https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/));
the C6 firmware drives both low before Wi-Fi starts, so the board radiates from its ceramic antenna.
The image is the same for every C6 board and needs no antenna attached. On the ESP32-C6-DevKitC-1,
GPIO3 and GPIO15 reach only the pin headers, GPIO14 is not broken out, and the addressable RGB LED
is on GPIO8 ([Espressif's user guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c6/esp32-c6-devkitc-1/user_guide.html)),
so the XIAO pin settings leave that board's radio and parts untouched.
BOOT is GPIO9; the yellow user LED on GPIO15 (lit while low) shows the LED looks; the red LED is the
charge indicator. The build runs at 160 MHz with the wire and button tasks on core 0, as on the C3.

The C6 is a Wi-Fi 6 chip. Its station is held to 11b/g/n so its association request carries no HE
elements, as on every other target. Its receive header (`esp_wifi_he_types.h`) has no `sig_mode`,
`mcs` or `cwb`; the firmware derives RX_SNIFF and RX_CENSUS `sig_mode` from `cur_bb_format` and the
HT MCS byte from the HT-SIG in `he_siga1`. Its rate byte is the L-SIG rate code for an OFDM frame,
not a `wifi_phy_rate_t`. The ESP-IDF v6.1 C6 Wi-Fi libraries export every private symbol the
firmware uses, with the same `lmacConfMib` offsets as the C3.

A XIAO ESP32C6 revision 0.2 over native USB on macOS carries a 2,000,000-byte BENCH transfer as
1429 messages with none missing and no bad checksum, at 824.6 KB/s, and takes 5000 of 5000 uplink
commands with none lost. Its idle free heap at start is 255196 bytes. A FireRed joiner session on
its ceramic antenna counted 5155 of 5155 host ETH_TX commands on the board, with no bad wire frame
and no USB resync.

The Seeed Studio XIAO ESP32S3 (ESP32-S3 revision 0.2, 8 MB flash, 8 MB PSRAM) uses its USB-C
socket for native USB Serial/JTAG and needs its supplied external antenna. BOOT is GPIO0; the yellow
user LED on GPIO21 (lit while low) shows the LED looks. Over native USB on macOS it carries a
2,000,000-byte BENCH transfer as 1429 messages with none missing and no bad checksum, at 883 KB/s,
and takes 5000 of 5000 uplink commands with none lost. Its idle free heap at start is 212416 bytes.

The classic ESP32 measurements below use the ELEGOO ESP32-D0WD-V3 board unless another board is
named. Completed trades per board are in [Trades by board](#trades-by-board).

### The USB link after a reset (C6, S3)

Opening the port resets a C6 or S3 through USB Serial/JTAG (reset reason 11, a core reset). With
`CONFIG_ESP_SYSTEM_BBPLL_RECALIB=y`, the ESP-IDF default on both chips, the application's startup
runs `recalib_bbpll()` (`esp_system/port/soc/esp32c6/clk.c`, the same on S3): on any reset other
than a CPU reset it calls `rtc_clk_cpu_freq_set_xtal()`, which stops the BBPLL with no check for its
USB consumer, then restarts it. USB Serial/JTAG takes its 48 MHz clock from that PLL while the host
is talking to it. On a XIAO ESP32C6 the link then sometimes came up garbled and stayed so until the
board was unplugged: the firmware kept running, the SOF frame number never moved after that boot,
`USB_SERIAL_JTAG_INT_RAW` held PID, CRC5 and bit-stuffing errors (`0000b5b2` against `0000b50a`
healthy) with the reply stuck in the IN FIFO, the clock-enable, pad and PCR registers matched a
healthy board, GET_CONFIGURATION over EP0 failed, and esptool's USB reset got no answer.

| C6 image | port opens (reset and boot) | link dead until unplugged |
|---|---|---|
| recalibration on | 113 | 1, at open 113 |
| recalibration off | 900 | 0 |

The C6 and S3 builds set `CONFIG_ESP_SYSTEM_BBPLL_RECALIB=n`; its Kconfig help allows that for a
bootloader built with ESP-IDF v5.2 or later, and every merged image carries its own v6.1
bootloader. A XIAO ESP32S3 with recalibration off answered 300 of 300 opens. The C3 has no such option and showed no fault.
With recalibration off, 4 of 600 opens on a C6 found no answer once and a working link on the next
open, after macOS re-enumerated the device ("Device not configured").

The C6 build also carries a USB watch (`usbwatch.c`): it samples the SOF frame
number every 5 ms and, once frames have counted or the host has sent a byte, restarts the chip
after a 2 s stall and reports the USB and clock registers from before and after it as LOG lines on
the next HELLO. Built with `POKELDN_USB_BEACON=1` in the environment of `idf.py`, the C6 image also
sends those registers, the SOF changes it has seen and the host bytes it has read once a second, as
a vendor action frame (category 127, OUI `02:55:53`) to the group address `03:55:53:42:57:00`; a
sniffing board keeps them with `esp32_sniff.py --mac 03:55:53:42:57:00` while the USB link is dead.
The frame body after the 4-byte vendor header is u32 little-endian: uptime ms, SOF changes, host
bytes, `wire_dropped`, stall count, then the sixteen registers listed in `usbwatch.c`.

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

- `wpa_sta_connect` installs the RSN element a Switch station sends (CCMP, PSK, capabilities
  `0x000c`) before and after the stock callback, which rebuilds it.
- `wpa_sta_rx_eapol` drops EAPOL; the station keys go in with `esp_wifi_set_sta_key_internal` once
  the association response is seen, then `esp_wifi_auth_done_internal` opens the port.
- `wpa_ap_join` adds the station to hostapd's table and sends the association response
  (`esp_send_assoc_resp`) with no authenticator state machine, so no EAPOL-Key message 1 goes out
  (`AP_START` flag bit 0 keeps the stock join). It queues the station's MAC; the main loop installs
  the pairwise key (`esp_wifi_set_ap_key_internal(CCMP, mac, 0, key)`) and opens the port
  (`esp_wifi_wpa_ptk_init_done_internal(mac)`), hostapd's `PTKINITDONE` order
  (`wpa_auth.c:2290-2332`). The group key goes in at `WIFI_EVENT_AP_START` with index 1.
- `esp_wifi_wpa_ptk_init_done_internal` is the only poster of `WIFI_EVENT_AP_STACONNECTED` (event 14,
  `ieee80211_supplicant.o`) for a WPA2 station. Never wait for that event to install the key: with
  no 4-way handshake it never comes and the console's first encrypted frame is dropped.

## The access point's frames

The softAP's beacon, probe response and association response are built in the closed
`libnet80211.a`. Read from the v6.1 blob (`ieee80211_output.o` offsets), against what `vendor/LDN`'s
access point sends a Switch:

| field | Switch form | ESP32 softAP | settable |
|---|---|---|---|
| hidden SSID element | 32 zero bytes | length 0 (`ieee80211_beacon_construct` 0xc4) | no |
| Supported Rates | `82 84 8B 96 0C 12 18 24` | `8B 96 82 84 0C 18 30 60` | no; same twelve rates and basic bits, 9 and 18 in Extended |
| Extended Rates | `30 48 60 6C` | `6C 12 24 48` | no |
| capability, beacon | `0x0511` | `0x0431` (short preamble constant, `ieee80211_getcapinfo` 0x7b) | no |
| HT elements | none | present in 11b/g/n | removed: the firmware sets 11b/g |
| RSN capabilities | `0x000c` | hostapd's own | set: `wpa_ap_get_wpa_ie` returns the Switch's element |
| WMM | none | present in 11g | only 11b-only removes it |

A hidden softAP answers directed probes only, with the real SSID in the probe response. An
association request without the configured SSID is dropped (0x9c6). `esp_wifi_80211_tx` accepts
beacons and refuses association responses (`ieee80211_raw_frame_sanity_check` 0xf9); the blob's own
beacons cannot be stopped.

## Serial protocol

A frame is `COBS(type | payload | crc32-le(type | payload))` then `0x00`; the CRC is CRC-32/ISO-HDLC
(`zlib.crc32`). The classic ESP32 boots at 115200 baud; `BAUD` switches both ends. On S3,
`BAUD` is acknowledged without changing the USB transfer rate. Anything before a `0x00`,
the ROM's boot text included, fails the checksum and is discarded.

| type | direction | payload |
|---|---|---|
| `0x01` HELLO | host | none; answered by CREDIT 0, then INFO |
| `0x02` BAUD | host | u32 baud; RESULT at the old rate, then the switch, which waits up to 3 s for the UART to drain (at 115200 the ring holds over a second of RX_MGMT). The first HELLO at 1500000 is sometimes lost (about one open of four measured); `open_serial` retries it |
| `0x03` CHANNEL | host | u8 channel; idle only |
| `0x04` STA_JOIN | host | u8 channel, 6 BSSID, 32 SSID (the LDN SSID's hex text), 16 key, 6 station MAC (zero = random); optional: u8 fixed data rate (the AP_START bits 3..5 table), u8 maximum TX power in 0.25 dBm (`esp_wifi_set_max_tx_power`, 8 to 84, the driver caps it at 61), u8 flags: 1 RTS before every frame, 2 no RTS before a retry (`esp_wifi_internal_set_rts`) |
| `0x05` STOP | host | none; back to idle, keys cleared |
| `0x06` AP_START | host | u8 channel, 6 BSSID, 32 SSID, 16 key, u8 max stations, u8 flags: 1 the stock association and 4-way handshake, 2 no QoS for the station, 4 no 40-byte copy of each station data frame, bits 3..5 a fixed data rate, `0x40` a beacon every 1000 TU, `0x80` no promiscuous receive; optional second flag byte: 1 the driver's noise-floor check off, 2 its interval 250, 4 the receive time in each 40-byte copy's head, 8 retry limits 7 and 4, `0x10` RX_CENSUS for every frame except its stations' good data frames; then an optional maximum TX power in 0.25 dBm |
| `0x07` AP_KICK | host | 6 MAC, u16 reason; deauthenticates |
| `0x08` ETH_TX | host | an Ethernet frame, encrypted by the driver with the station's or the group key. A full driver queue (`ESP_ERR_NO_MEM`) is retried every 1 ms for up to 100 ms; a frame to a departed station fails at once with `0x3015` (`ESP_ERR_WIFI_NOT_ASSOC`). A station sends the Ethernet source as its 802.11 transmitter address: a source other than the MAC in LINK is never acknowledged (49 of 49) |
| `0x09` RAW_TX | host | an 802.11 frame without FCS (`esp_wifi_80211_tx`); advertisements |
| `0x0A` SNIFF | host | u8 channel, 6 MAC; every management and data frame to or from it, whole, as RX_SNIFF; MAC ff:ff:ff:ff:ff:ff sends every frame on the channel as RX_CENSUS |
| `0x0B` STATUS | host | none; answered by STATUS |
| `0x0C` BENCH | host | u32 bytes, u16 message size (8 to 1600); RESULT, then BENCH messages as fast as the UART takes them |
| `0x0D` LED | host | u8 pattern, u8 peak brightness, u16 period ms (0: the pattern's default), u16 duration ms (0: until the next LED); RESULT. Older firmware answers `0x106` |
| `0x0E` DISPLAY | host | a screen command ([The screen](#the-screen)); RESULT `0x105` (`ESP_ERR_NOT_FOUND`) without a screen, `0x106` from older firmware |
| `0x0F` ALIVE | host | none, no reply; arms [the host watchdog](#the-host-watchdog). Firmware before 1.4.0 answers `0x106`, so the host sends it only to 1.4.0 and later |
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

`rx_state` 98 marks two-stream HT (MCS 8 to 15), which the single-stream ESP32 never decodes (79 of
79 in one census); 65 marks a corrupted frame of any other modulation (1397 of 5605).

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

Creating a TAP needs `CAP_NET_ADMIN`. The desktop app runs as the user, so on Linux a TAP default
fails before the board joins anything.

### The host watchdog

From firmware 1.4.0 the host sends ALIVE every second (`esp32.ALIVE_EVERY`), chosen from INFO's
`version=` text. The first ALIVE after a HELLO arms the watch; HELLO disarms it, so a host that never
sends ALIVE is never watched. Armed, a board out of idle that reads no host command for 5 s
(`HOST_SILENT_US`) runs STOP's teardown: an access point stops beaconing and its stations drop, a
station disconnects. It then discards every message for the host, uncounted, until the host sends a
command again: a host gone from a USB board otherwise turns each queued or overheard message into a
500 ms write and a `wire_dropped`, and the LED's alarm into a constant `flash3`.

On a XIAO ESP32C6 with a retail FireRed in the trade room of `frlg_trade_host.py` and the host
killed with SIGKILL, the console showed 2318-0006, a later JOIN search listed no host, and the LED
returned to its idle look. Without the discard the LED stayed on `flash3`.

## The serial ceiling

On the classic ESP32 UART at 921600 baud, 8N1, the board-to-host line carries 92.16 KB/s.
A message costs its payload plus a
type byte, a four-byte CRC, the COBS overhead (one byte per 254 and the delimiter) and, for RX_MGMT,
two bytes of channel and RSSI. Pia payloads are AES-GCM ciphertext and do not compress.

| traffic | what it costs the line |
|---|---|
| a station's data frame, hosting | the frame as RX_ETH, and 48 bytes for the 40-byte RX_MGMT copy unless AP flag 4 is set (`POKELDN_ESP32_AP_FLAGS=4`) |
| a station's data frame, joined | the frame as RX_ETH only; station mode passes management frames alone |
| an LDN advertisement nearby | the whole action frame, about ten a second per network |

The outgoing queue holds 384 messages and refuses one below 64 KB of free heap; a 128-entry queue
overflows in a Scarlet host's opening burst (337 messages dropped where measured). A console at the
line's rate holds the heap at that floor (`heap_min` 63976, `queue_max` 95, `refused_heap` 219): the
heap refuses RX_ETH before the queue fills.

### Baud rate

`POKELDN_ESP32_BAUD` sets the rate `open_serial` switches to, 921600 by default. The ESP32 UART runs
to 5 Mbaud; the USB bridge sets the limit. `tools/ldn/esp32_bench.py --port PORT --bauds
921600,1500000,2000000,3000000` streams BENCH at each rate. The ELEGOO board's bridge ("CP2102 USB to UART Bridge Controller", idProduct 60000, bcdDevice 0x100)
on macOS:

| baud | measured | messages | lost | bad checksums |
|---|---|---|---|---|
| 921600 | 91.7 KB/s | 1429 of 1400 bytes | 0 | 0 |
| 1000000 | 99.4 KB/s | 1429 of 1400 bytes | 0 | 0 |
| 1500000 | 149.1 KB/s | 4286 of 1400 bytes | 0 | 0 |
| 1500000 | 140.2 KB/s | 20000 of 100 bytes | 0 | 0 |
| 2000000, 3000000 | the board never answers HELLO at the new rate | | | |

A Legends Z-A seat at 921600 with CREDIT had no refused association, its first message at 1.68 s
(1.7 s at 1500000) and 695 of 695 ETH_TX counted.

### Host-to-board command loss and CREDIT

Under a console's flood, host commands can be lost before the handler: a Scarlet seat that handed
the board 660 ETH_TX in 7.5 s had 92 counted (`tx_eth + tx_eth_failed`), with no CCMP packet number
spent on the rest and `tx_eth_retried` 0. Each cause, measured without its countermeasure, and what
the firmware does:

| cause | measured without the countermeasure | the firmware |
|---|---|---|
| UART interrupt on core 0 with the Wi-Fi task | the seat above | driver installed from the reader task, core 1 |
| an ETH_TX waiting on a full Wi-Fi queue in the reader task; the 16 KB ring fills, the FIFO overflows | `esp32_bench.py --uplink 5000` (5000 broadcast ETH_TX to an empty network) at 1500000: 369 to 429 lost, `uart_fifo_ovf` 305, `wire_rx_bad` 169; none at 921600 | CREDIT: 0 of 5000 lost at either rate |
| FIFO drained at 120 bytes (`UART_FULL_THRESH_DEFAULT`), 53 µs from full at 1500000 | a Scarlet seat with CREDIT: about 210 of 1901 lost, `uart_fifo_ovf` 235 | threshold 32 (`uart_set_rx_full_threshold`), 640 µs: 10 of 1691, `uart_fifo_ovf` 0 |
| `uart_read_bytes` (IDF 6.1 `uart.c:1738`) waits its timeout again per ring item until it has `length` | a 21-byte command every 15 ms read 461 ms late (`--trickle 5`); a Scarlet seat `read_max_us` 311644 | wait for one byte, then take `uart_get_buffered_data_len`: 20.3 ms |
| `uart_write_bytes` busy-loops on a full TX ring (`uart.c:1662`); the writer (priority 20) shares core 1 with the reader (19) | a Scarlet flood held ETH_TX up to 707 ms; `esp32_pair_bench.py AP STA --flood 0 --send 20 --bench`: `read_max_us` 7982767, 74 sends refused | the writer sleeps until the frame fits (`uart_get_tx_buffer_free_size`): 30382 µs, none refused ([Scarlet and Violet](sv.md#the-retail-acknowledgement-and-a-flood-of-retransmits)) |
| every 32 bytes post a `UART_DATA` event into the 64-entry queue that carries overflow events (`uart.c:1369`, `1543`), full in 14 ms at 1500000 | an overflow during a long command could go uncounted | a task above the reader drains it every tick; `uart_events_full` |

With the window ignored (`--uplink 5000 --no-flow`) each `uart_fifo_ovf` loses 136.5 bytes, about one
FIFO, and `uart_events_full` stays 0: a full ring stops `UART_DATA` events.

CREDIT: once the board has sent one, the host keeps under 8 KB written and unreported
(`esp32.FLOW_WINDOW`) from a writer thread, so a launcher's trio loop only queues, and drops ETH_TX
and RAW_TX past 512 queued frames (`Radio.tx_dropped`). If no CREDIT moves while the window is shut, a
count repeated unchanged for 0.3 s means bytes were lost on the line and the host reopens the window
(`Radio.flow_resyncs`); a board sending no count is busy and gets 5 s. Never resync on silence alone:
a busy reader holds up to 0.7 s, and a resync then puts 16 KB in flight against a 16 KB ring. Written-off
bytes stay written off; a CREDIT past what the loss allows shrinks it. A CREDIT jumps the
outgoing queue (at most one queued) yet arrives about 0.5 s late behind a Scarlet seat's 150 KB/s of
RX_ETH. A board without CREDIT never opens the window and the host writes unthrottled. The board logs a
command over 50 ms (`slow command`) and a reader turn over 100 ms (`reader held`).

With the idle count and the CREDIT ahead of the queue, the board counted every ETH_TX the host handed
it: 520315 of 520315 over 228 board sessions (classic ESP32 up to firmware 1.2.0, C3, C6 1.0.0), every
overflow and wire counter 0, every repeated idle count equal to the bytes written. Six of those
sessions had the host writing over 500 ETH_TX a second while the board-to-host line ran at 148 to
152 KB/s.

Firmware before the idle count lost a few host commands with no overflow counted: 6 of 2333 at
921600 with no CREDIT and 10 of 1691 at 1500000 with the CREDIT at the back of the queue, each with
`wire_rx_bad` 1 and `tx_eth_retried` 0. The loss fell in the host's first burst with the
board-to-host line at its ceiling (91.4 KB in one second at 921600). That firmware's writer spun on
a full TX ring above the reader, and only the reader drained the UART event queue, so an overflow
during a starved read went uncounted. One `wire_rx_bad` for several lost commands fits one
contiguous lost span. Which buffer dropped the bytes is unmeasured: those traces carry no CREDIT.

A HELLO restarts both counts, so the host holds it until nothing is in flight and keeps the window
shut across it until the board's CREDIT 0. A host that wrote unthrottled after a mid-session HELLO
(a scan sends one, `EspFactory.create_monitor`) overran a simulated 16 KB ring held for 0.5 s by
76423 bytes; `tests/test_esp32.py::test_a_hello_mid_session_does_not_open_the_window` pins it.
`tools/ldn/esp32_cmd_loss.py TRACE` reconciles a trace: ETH_TX written against `tx_eth +
tx_eth_failed`, bytes written since HELLO against the last CREDIT.

### Transmit timing

On one calm Scarlet seat ETH_TX spent 0.12 ms on average and 1.57 ms at most in the driver, and the
console held all 44 of the joiner's records 0.35 s after they were sent.

TX_DONE separates the board from the peer. On a flooding Scarlet seat a frame waited 1.0 ms median
and 6.8 ms at most from ETH_TX to TX-done, and the console's radio acknowledged 1267 of 1267. The
TX_DONEs reached the host 15 ms after their board time while calm and 446 ms (590 ms at most) in the
worst second: the board-to-host line backs up under a flood. Board time minus the smallest arrival
offset gives a message's lag on the line.

The two-board bench (`tools/ldn/esp32_pair_bench.py`, 200-byte station frames) delivers every
station frame: 187 of 187 at 20 a second (1.6 ms average ETH_TX to TX-done, 10.7 ms at most), and 1227
of 1227 under 100 1200-byte broadcasts a second from the access point, about 96% of the air (26.8 ms
average, 218 ms at most).

Measuring traps: a sniffer board's line backs up in a burst like any board's, so a frame it reports
may reach the host a second after it was on the air; run it at 1500000 and time delivery by the
peer's acknowledgements. Its counts of another board's frames undercount while its own line is
saturated. BENCH fills its payload once; an RNG fill held it under the line's rate. A flood the
board sends as an access point is broadcast at 1 Mbit/s and fills the air past about 90 frames a
second.

## Holds and receive misses

### The FireRed hold

Five FireRed trades with the board as the access point, one row per trade; the console
acknowledged every frame. Wait is ETH_TX to TX-done; retries are the share of data frames the sniffer
saw with the retry bit.

| channel | frames | wait median | wait p99 | wait max | holds over 100 ms | retries AP / console |
|---|---|---|---|---|---|---|
| 1 | 7489 | 1.24 ms | 116 ms | 261 ms | 5 | 13.3% / 12.8% |
| 6 | 13670 | 0.85 ms | 18 ms | 108 ms | 1 | 10.5% / 7.7% |
| 11 | 7069 | 0.86 ms | 9 ms | 46 ms | 0 | 15.0% / 5.7% |
| 1 | 7332 | 1.03 ms | 25 ms | 88 ms | 0 | 20.6% / 9.4% |
| 1, 24 Mbit/s pinned | 6892 | 0.73 ms | 69 ms | 185 ms | 5 | 2.8% / 14.3% |

Host to board adds 0.12 to 0.47 ms median (socket to ETH_TX written) and 3.1 to 3.4 ms (ETH_TX to the
board). Every wait over 100 ms is head-of-line: one frame the console has not acknowledged holds 108
to 261 ms, the frames behind it complete in a burst (up to 10 within 5 ms), and the access point's
action frames keep going. The sniffer sees one to three copies of the head frame, at 54 or 48 Mbit/s,
with the console's frames between them, all with the power-management bit clear: the console stays
awake on the channel. The channel decides a hold (The channel), the retry share does not.

| sender | first tries at 54 Mbit/s | retries |
|---|---|---|
| board (access point) | 91 to 100% | 54 Mbit/s for 77 to 92%, then 48, rarely 6 or 36 |
| console | 92 to 99% | 48, 36, 24, 18, down to 1 Mbit/s |

Bits 3 to 5 of the access point's flag byte pin its data rate (`esp_wifi_internal_set_fix_rate`; 0
is rate control). `POKELDN_ESP32_AP_FLAGS=0x28` pins 24 Mbit/s: the retry share fell to 2.8% and the
holds stayed.

| bits 3..5 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| rate, Mbit/s | 1 | 11 | 6 | 12 | 24 | 36 | 54 |

What makes the board wait about 100 ms between copies is unknown. `tools/ldn/esp32_hold.py CAPTURE
TRACE` splits each wait into stages, pairing TX-dones by length (they complete out of order);
`tools/ldn/esp32_hold_air.py` lists what the sniffer saw during each hold.

### The CPU clock

The firmware runs the CPU at 240 MHz (`CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240`; IDF's default is 160).
Six FireRed trades on channel 1, one row per trade; missed is the share of the console's first
copies the board did not hear:

| CPU | RX buffers | frames | p90 | p99 | p99.9 | over 5 ms | over 40 ms | over 80 ms | holds | missed | console retries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 160 MHz | 16 | 6744 | 4.7 ms | 30.4 ms | 91.7 ms | 605 | 41 | 10 | 1 | | 8.8% |
| 160 MHz | 25 | 6999 | 4.6 ms | 34.4 ms | 106.5 ms | 615 | 57 | 19 | 1 | 6.8% | 13.0% |
| 240 MHz | 25 | 7425 | 3.1 ms | 13.5 ms | 34.3 ms | 322 | 5 | 0 | 0 | 5.2% | 12.4% |
| 240 MHz | 25 | 7235 | 3.0 ms | 15.7 ms | 66.3 ms | 242 | 16 | 3 | 0 | 4.9% | 11.9% |
| 160 MHz | 25 | 8349 | 4.3 ms | 27.5 ms | 82.3 ms | 666 | 41 | 9 | 0 | 5.3% | 10.2% |
| 240 MHz | 25 | 7021 | 5.0 ms | 31.7 ms | 109.6 ms | 708 | 57 | 16 | 1 | 8.5% | 18.9% |

The spread between runs of one setting is as large as the clock's difference.

### The channel

Long waits follow the channel's occupancy. Where these trades were measured, channel 1 also carried
the console's home access point and held the long waits:

| channel | trades | wait p99 | wait max | trades with a hold over 100 ms | board missed, console first copies |
|---|---|---|---|---|---|
| 1 | 9 | 13.5 to 116 ms | 65 to 261 ms | 5 | 4.9 to 8.5% |
| 6 | 1 | 18 ms | 108 ms | 1 | |
| 11 | 4 | 9 to 11.2 ms | 19 to 46 ms | 0 | 3.3%, 5.5%, 6.0% |

On channel 11 the board misses as many first copies with the same p90 wait (4.5 ms); only the tail
differs (8 and 9 frames over 20 ms against 42 to 137): the receive misses do not make the holds. `config/host.local.toml` takes a `[host] channel`; the console joins a host on 1, 6 or 11.

### The board is the deaf side

A sniffing board keeps every ACK as a 10-byte RX_SNIFF; an ACK names only its receiver, so
`tools/ldn/esp32_hold_air.py` pairs it with the data copy just before it; a copy acknowledged and
sent again means its sender missed the ACK. One FireRed trade on channel 1 (6744 frames):

| sender | first copies | no ACK after it | acknowledged and sent again |
|---|---|---|---|
| board | 6514 | 490 (7.5%) | 56 |
| console | 4517 | 428 (9.5%) | 2 |

In that trade the board missed far more ACKs than the console (56 against 2). During a hold the
board hears neither the console's data nor its ACKs: its copies of the held frame go out about 40 ms
apart, and 42 to 66% of the console's frames to it carry the retry bit (11 to 14% over the session),
while the sniffer hears both sides at -19 to -21 dBm.

The console's retries are the board's receive misses. Matched by sequence number against the sniffer
(`tools/ldn/esp32_rx_copies.py HOST_TRACE SNIFF_TRACE --ap BSSID --sta MAC`), a frame the console sent
more than once reached the board's RX_MGMT header copies as one copy with the retry bit in 1008 of
1027; such a copy with no earlier one of its sequence number marks a miss from the board's trace
alone. The board missed 4.5 to 12.1% of the console's first copies at 54 and 48 Mbit/s, at -20 dBm. A
missed first copy follows another console frame 37 to 52% of the time, a heard one 28 to 32%; RSSI,
rate and length do not differ.

### Receive misses on two boards

`tools/ldn/esp32_pair_bench.py AP STA --flood 0 --burst N --send R` has the station board send
200-byte frames and counts, from the access point's header copies, the frames whose first copy it
missed. Either board misses as an access point on an otherwise idle air, hearing the station at -43
to -48 dBm: 5.5 to 22.2% at 20 to 100 frames a second, and identical 30 s runs range from 6.1 to
43.7%. The station's longest wait for an ack is 89 to 100 ms on channel 1, 8 to 22 ms on channel 11.
With the receive time in the header copies (second AP_START flag byte bit 2, `rx_ctrl.timestamp`, u32
µs after the RSSI), misses fold flat at 102.4, 51.2, 25.6 and 1024 ms and at 50 and 100 Hz.

| variable | first copies missed |
|---|---|
| station rate (STA_JOIN rate byte, `--sta-rate N`), channel 11 | 54 Mbit/s OFDM 2.3 to 4.0%, 6 Mbit/s OFDM 1.9 to 5.4%, 1 Mbit/s DSSS 0.04 to 0.2% |
| station power (`--sta-power`, 0.25 dBm), 54 Mbit/s | 78 (default, 19.5 dBm) 1.5 to 3.1%, 28: 4.5 to 12.9%, 12: 15.3 to 20.8%; the access point reads -33 to -35 dBm from 17 to 61 alike |
| channel, 54 Mbit/s | 1: 3.7 to 9.7%, 3: 0.8%, 5 to 9: 0.8 to 2.3%, 11: 2.1 to 5.7%; 13 refused (`0x102`) |
| ESP-IDF driver, channel 3 | v5.5.5 5.0%, v6.1 4.1% |
| STA_JOIN flag 1, RTS before every frame | 2.1 to 2.3% against 4.6 to 4.8%; flag 2, no RTS before a retry, 3.7 to 4.9% |

No change from: a beacon every 1000 TU (AP `0x40`); promiscuous receive off (AP `0x80`); the
noise-floor check off (second byte bit 0, clears `g_pm+21` so libpp's `pm_noise_check` returns early)
or its `NoiseTimerInterval` (`pp.o` `.data`, u16 100) at 250 (bit 1); 25 static receive buffers
(`CONFIG_ESP_WIFI_STATIC_RX_BUFFER_NUM`) against 16; 240 MHz; `CONFIG_ESP_WIFI_EXTRA_IRAM_OPT=y`; the
access point's power at 19.5, 10 or 3.5 dBm; the Switch asleep with Bluetooth off. The misses follow
the modulation and the channel, not the signal margin: 6 Mbit/s misses as often as 54, DSSS almost
never. The two drivers share `libphy.a` and `hal_mac_rx.o` byte for byte, the same register writes,
receive interrupt, buffer recycling and transmit-done code; v6.1 adds `wifi_assert` on the per-frame
paths and passes `wpa_ap_join` one struct where v5.5.5 passes nine arguments.

Channels 1 and 11 were busy 8.7 to 13% with 44 to 107 neighbour frames a second, channels 3 to 9 0.3
to 1.7%, noise floor -96 dBm on all (`tools/ldn/esp32_census.py`). The access point's own census
(second flag byte `0x10`) finds a neighbour frame in the 3 ms before a miss 13.1% of the time, 11.0%
before a heard copy; a probe request in the 2 or 5 ms before a miss 0.0 or 1.1% against 0.0 or 0.1%. 85 to 91% of misses leave no trace at the access point, not even an FCS failure.

The board misses most often a frame that follows its own transmission. A FireRed console sends every
data frame behind RTS/CTS although the board's beacon carries ERP byte 0; the data follows the
board's 6 Mbit/s CTS by 60 µs (44 µs plus SIFS), and 329 of 4034 were missed in one trade. On the
bench, bursts of 4 at 54 Mbit/s: the first frame 0.5 to 3.0%, the second 2.4 to 4.6%, the third 4.7 to
8.7% (usually the most), the fourth 2.6 to 7.6%.

An ESP32 station sends every retry behind an RTS 128 µs before the data (`lmacConfMib` +42, retries
before RTS, 0; RTS threshold 2346 at +22); `esp_wifi_internal_get_rts` and `_set_rts` access both
through a packed `{u16 threshold, u8 retries before RTS, u8 long, u8 short}`. The ACK and CTS rate table is at `0x3ff73400`..`0x3ff7341c`. Of 8527 RTS the access
point heard in 90 s, 311 (3.6%) were answered and the data after the CTS missed; the count above
leaves those out. The driver retries in software: `lmacRetryTxFrame` (libpp `lmac.o`) resends through
`lmacTxFrame` up to `lmacConfMib` limits (short +21, long +20, 32 by default), set by
`esp_wifi_internal_set_retry_counter(short, long)`. At 100 unicast frames a second from the access
point (`--flood 100 --unicast`) frames waited at most 24 ms; two boards do not reproduce a 100 ms hold.

The station board's slow sends (over 3 ms, `--done-out`) bunch into two twentieths of a 102.4 ms cycle
(29 to 43% against 2 to 12%) whatever the beacon interval (`tools/ldn/esp32_bench_fold.py FILE
PERIOD_US`).
`tools/ldn/esp32_bench_drift.py` measures both boards' clocks against the host (1.9 ppm apart over
600 s) and scans the fold period.

## The userspace stack

`pokeldn.ldn.userspace_ip` carries IPv4, UDP and ARP inside the host process for an interface with no
kernel behind it. A stack is registered under the caller's interface name (`ldnclient` for the
joiners, `ldn-tap` for an access point) while the port exists; `userspace_ip.lookup(name)` returns
None for a kernel interface, which is how every launcher picks its path.

- Addresses and neighbours come from the LDN library's `add_address` and `add_neighbor`; a source
  address on any received frame is learned as a neighbour.
- A destination ending in `.255` or equal to the broadcast address goes to `ff:ff:ff:ff:ff:ff`. A
  unicast destination with no neighbour entry sends an ARP request and drops the datagram. ARP
  requests for the stack's own address are answered.
- Datagrams over 1472 bytes are fragmented; incoming fragments are reassembled (5 s timeout). UDP
  checksums are computed.
- `udp_socket(port)` stands in for a UDP socket bound to the interface, `packet_socket()` for an
  `AF_PACKET` socket delivering whole IPv4 Ethernet frames. Each uses a socket pair with one byte
  per queued datagram, so `select` and `trio.lowlevel.wait_readable` work on macOS, Linux and Windows.
  TCP socket pairs disable Nagle buffering so readiness bytes reach the reader promptly.
- The board's frames reach the stack through trio tasks in the launcher's own trio loop. A blocking
  `select` inside that loop starves them and each datagram waits out the full timeout; wait with
  `trio.lowlevel.wait_readable` under `trio.move_on_after`. A Scarlet joiner blocking in
  `select(0.05)` handles one message per 50 ms, and the console re-sends its records meanwhile (50
  to 70 s measured).

## The board's LED and buttons

LED patterns drive GPIO2 on classic ESP32 boards, GPIO21, inverted, on the S3 (the XIAO ESP32S3's
yellow user LED, `LED_BUILTIN` in arduino-esp32's XIAO_ESP32S3 variant) and GPIO15, inverted, on the
C6 (the XIAO ESP32C6's yellow LED). The C3 firmware leaves LED pins alone. BOOT trace markers use GPIO0 on classic
ESP32 and S3, and GPIO9 on C3 and C6.

The ELEGOO ESP-32 Type-C board (CP2102, ESP32-D0WD-V3) carries an unbranded module with a PCB antenna
and no Espressif module name:

| part | wired to | controllable |
|---|---|---|
| red LED | the 3.3 V rail | no, lit whenever the board has power |
| blue LED | GPIO2, lit when high | yes |
| EN button | the chip's reset | no |
| BOOT button | GPIO0 | yes: each press sends BUTTON (`0x8E`), flashes the LED and wakes the screen |

GPIO2 and GPIO0 are strapping pins (low or floating at reset for download mode); the firmware drives
GPIO2 only after boot. From the ROM bootloader the LED lights by writing GPIO2's IO_MUX
(`0x3FF49040`, `MCU_SEL` 2), its output select (`0x3FF44538` = `0x100`), `GPIO_ENABLE_W1TS` and
`GPIO_OUT_W1TS` (bit 2).

The firmware drives the blue LED with LEDC PWM (13 bits, 5 kHz) from a priority-1 task on core 1
every 10 ms. The duty is the level to the power 2.2; a
change of look crossfades over 150 ms.

| pattern | id | default period | shape |
|---|---|---|---|
| auto | 0 | | the mode's look, below |
| off, on | 1, 2 | | |
| breathe | 3 | 3000 ms | raised cosine |
| blink | 4 | 1000 ms | on for half the period, 80 ms eased edges |
| flash3 | 5 | 1000 ms | three flashes in the first 60 % of the period |
| ramp-up, ramp-down | 6, 7 | 1000 ms | once, cubic ease-in-out, then held |
| pulse | 8 | 1200 ms | a quick swell, a slow cubic fall |

| mode | automatic look |
|---|---|
| boot | one pulse, 900 ms |
| idle | breathe, dim, 4 s |
| joining a console | fast blink, 250 ms |
| hosting, no station | breathe, brighter, 1.5 s |
| joined, or hosting a station | on, dim |
| sniffing | off |

Every frame received or completed flickers the LED on top.
A failed join (LINK `0xFFFF`, `0xFFFE`), a refused key, a dropped board-to-host message or a lost host
command plays flash3 for 1.5 s. A completed trade or Mystery Gift delivery ramps up to full over
800 ms, held until 3 s (`pokeldn.ldn.show_done`); the Sword gift host, a beacon with no read-back, has
no such moment. `tools/ldn/esp32_led.py --port PORT PATTERN` sets a look; `--demo` shows each.

## The screen

An SSD1306 128x64 one-bit OLED on I2C is optional. At boot the firmware probes 0x3C, then 0x3D;
when neither answers it frees the pins and starts nothing. With a screen, a priority-1 task on the
last core draws a frame every 50 ms and sends it at 400 kHz (1031 bytes, about 23 ms).

| target | SDA | SCL | board pins |
|---|---|---|---|
| ESP32 | GPIO21 | GPIO22 | DevKit V1 D21, D22 |
| ESP32-S3 | GPIO8 | GPIO9 | |
| ESP32-C3 | GPIO6 | GPIO7 | XIAO D4, D5 |
| ESP32-C6 | GPIO22 | GPIO23 | XIAO D4, D5 |

VCC goes to 3V3 and GND to GND. The common four-pin module (GND, VCC, SCL, SDA) carries its own
3.3 V regulator and 4.7 k pull-ups on SCL and SDA; its address resistor selects 0x3C (silkscreen
0x78) or 0x3D (0x7A). Its panel maps segment 127 to column 1 and COM0 to row 63, so the firmware sets
segment remap (`A1`), reversed COM scan (`C8`) and alternative COM pins (`DA 12`).

Without host commands the screen shows the radio's state: idle, joining or hosting (rings around a
Poke Ball), and linked, where a cable between a console and a Poke Ball carries one digit per frame
the radio counted in each direction, at most one per 70 ms, with the totals below.

OLED pixels age with the time they are lit, so the screen limits how long a still image stays on.
It is at full brightness while the radio is joining, joined, hosting or sniffing, while a traded or
gifted animation plays, and for 60 s after the last of these, a DISPLAY command, a HELLO or a BOOT
press. After that it dims to contrast 1 with a 2+2-clock pre-charge (`81 01 D9 22`), and after 600 s
it turns off (`AE`); the panel keeps its RAM. The next of those events lights it on the following frame, which is sent before the
`AF`. The idle scene moves 2 pixels every 60 s around a 2x2 square. `scene_draw` returns the
brightness; `tests/test_esp32_screen.py` holds the timings.

Contrast, pre-charge and VCOMH settings on the four-pin 0.96-inch module, judged by eye from INIT's
`81 CF D9 F1 DB 40`:

| setting | seen |
|---|---|
| contrast `80` | no change |
| contrast `40`, `20` | each a step dimmer |
| contrast `10` down to `01` | no further change, readable |
| contrast `00` | black |
| contrast `01`, pre-charge `22` | dimmer again, readable, steady |
| contrast `01`, pre-charge `11` | flickers; with VCOMH `20` or `00`, unreadable |
| contrast `01`, VCOMH `00` | looked normal, steady |

DISPLAY (`0x0E`) carries one op:

| op | layout |
|---|---|
| `0` SHOW | u8 show, u16 hold s (0: until the next show), title, NUL, line, NUL; each text at most 21 ASCII characters |
| `1` SPRITE | u8 slot (0 ours, 1 theirs, 2 gift), u8 width <= 64, u8 height <= 64, rows of `(width + 7) / 8` bytes, MSB first; width 0 empties the slot |

| show | id | drawn |
|---|---|---|
| auto | 0 | the radio's state |
| trade | 1 | slot 0 on the right half, "offering" and the line on the left, the cable below |
| traded | 2 | slot 0 flashes and returns to its ball, the ball leaves (2.1 s), packets cross until the hold (at least 3.1 s), a ball arrives and opens (1.6 s), then slot 1 with "received" and the line for 10 s: the board's side, as "offering" is |
| gift | 3 | a Wonder Card holding slot 2 (a gift box when empty), the line beside it |
| gifted | 4 | the card leaves to the right, then "delivered!" |
| arrived | 5 | no scene: a traded show still waiting brings its ball in now |

A trade or gift show sent before a traded or gifted show has ended waits for it to end. A trade or gift
show ends when the radio returns to idle after being active; one sent before the radio starts stays.
HELLO resets the screen to the radio's state with empty slots.

`pokeldn.app.screen` is the launchers' side: `offer`, `received`, `arrived`, `gift` and `delivered`
return at once and run in order on one thread. Every launcher calls `received` at the trade's last
step, before the console's trade animation, with a hold of the title's measured time from that step
to the received Pokemon appearing on the console, less 2.5 s so the ball opens with the console's:

| title | from | received Pokemon on the console | first message after the animation |
|---|---|---|---|
| FireRed/LeafGreen | START_TRADE | 22.7 s | READY_FINISH_TRADE ([FireRed link](frlg_link.md)) |
| Let's Go | step `0e` | 15.3 s | the type 4 payload ([Let's Go session](lgpe_session.md#the-trade-animation)) |
| Sword/Shield | the last syncCommand 40 | 15.0 s | none ([Sword trade](swsh_trade.md#the-trade-animation)) |
| BD/SP | `tradeState` 5 | 18.6 s | none ([BDSP trade](bdsp_trade.md#the-completed-trade)) |
| Legends Arceus | `01 0e` | 28.5 s | the box message `00 02` ([Legends Arceus](pla.md#the-completed-trade)) |
| Scarlet/Violet | `8001010e` | 19.8 s | none ([Scarlet and Violet](sv.md#the-trade)) |
| Legends Z-A | the fourth step | 26.2 s | the next `01 01` preview ([Legends Z-A](za.md#a-trade-with-a-retail-console)) |

Each time was marked by hand in one session and may be up to 2 s late. Where the console sends a message after its
animation, the launcher calls `arrived` there. A record goes through the PKHeX helper for its national species
and name; the sprite is PokeAPI's FireRed/LeafGreen one (64x64) up to species 386 and the default one
after, through the app's sprite cache and its download setting. A sprite becomes one bit per pixel:

1. Cropped to its visible pixels; larger than 64 (40 on a card) it is scaled down by area, each
   output pixel taking the darker third of its box.
2. Lit where its luminance exceeds a cutoff: the luminance at the darkest eighth of its visible pixels
   plus 6, clamped to 20..60, so the outline is dark and a dark Pokemon's body stays lit.
3. Dark where a lit pixel is more than 40 below and under 0.72 of its brightest four-neighbour: the
   inner lines.

`tools/ldn/esp32_screen.py --port PORT` plays a trade and a gift on a board, no radio traffic.
`tools/ldn/screen_preview.py OUT.gif` builds `scene.c` and `screen.c` for the host and renders a
scripted session offline.

## Building and flashing

Firmware releases use `major.minor.patch` in `firmware/esp32/version.txt`, shared by ESP32, S3, C3
and C6. Increment patch for fixes, minor for compatible features and major for incompatible changes
before building a release. ESP-IDF embeds the version in the application descriptor; INFO reports
it as `version=...`, and Boards displays it once its check of the board returns. Unversioned builds show `version unknown`
and remain usable when their serial protocol matches. The serial protocol and desktop app versions
are independent; increment the protocol number when its wire contract changes.

ESP-IDF v6.1 (tag `v6.1`, commit `fff9895c82d744c7237be8847347bdd1b07c6643`) builds all four targets.
Install its tools with `install.sh esp32,esp32s3,esp32c3,esp32c6`, then activate the IDF environment.

    cd firmware/esp32
    idf.py set-target esp32   # esp32s3, esp32c3 or esp32c6 for those chips
    idf.py build
    idf.py -p <port> flash

Console output is off (`CONFIG_ESP_CONSOLE_NONE`, `CONFIG_ESP_CONSOLE_SECONDARY_NONE`). On classic
ESP32, UART0 is the host link, so the firmware assigns GPIO1 and GPIO3 itself (`uart_set_pin`).
On S3, the firmware installs the USB Serial/JTAG driver on core 1; C3 and C6 install it on core 0.

The desktop app detects the chip with esptool on the same connection used for flashing.
It validates the merged image's bootloader at the chip's flash offset (ESP32: `0x1000`,
S3, C3 and C6: `0x0`) before writing, including custom images. esptool 5.4.0's `write_flash` can skip its
chip check when a merged image starts with padding. Never choose firmware from a USB bridge ID.
[Desktop builds](gui.md) covers packaging all four images.

### The USB host link

The S3, C3 and C6 use the same COBS, CRC and CREDIT protocol over USB Serial/JTAG. Both driver rings are
16 KB. IDF v6.1's `usb_serial_jtag_write_bytes` enqueues a whole frame or returns zero after its
timeout; the writer retries with 20 ms waits and counts a dropped message after 500 ms without
progress. `write_max_us` includes this wait. The reader takes available bytes with a 20 ms
timeout. UART overflow and framing counters stay zero on this path; they do not measure USB loss.
The receive interrupt drops a 64-byte packet when the 16 KB RX ring is full and counts nothing
(`usb_serial_jtag.c:144` ignores `xRingbufferSendFromISR`'s result). The CREDIT window keeps the ring
from filling; a loss there shows only as bytes written past the board's last CREDIT.
`POKELDN_ESP32_BAUD` is accepted on all targets and only changes the classic ESP32's line rate.

USB drains faster than the writer encodes, so under a full-rate board-to-host stream the writer
never sleeps. On USB targets the reader runs at priority 21, above the writer (20); the UART build
keeps it at 19, where the line rate makes the writer sleep. On a XIAO ESP32S3, a 14-byte ETH_TX
every 15 ms during an 884 KB/s BENCH (`esp32_bench.py --trickle 300 --flood`):

| reader priority | `read_max_us` | ETH_TX counted |
|---|---|---|
| 19, below the writer | 53951079 | 785 of 3055, the rest dropped at the host's 512-frame queue |
| 21, above the writer | 20493 | 3052 of 3052 |

BENCH stays at 884 KB/s; 5000 uplink ETH_TX take 15.4 s against 13.5 s, none lost. A FireRed joiner
trade on the raised priority counted 5629 of 5629 ETH_TX.

## Running

`POKELDN_RADIO=esp32:<port>` puts every launcher's `ldn` calls on the board. `esp32:auto` takes the
only USB serial port present (`/dev/cu.usbserial-*`, `/dev/cu.SLAB_USBtoUART*`,
`/dev/cu.wchusbserial*`, `/dev/cu.usbmodem*`, `/dev/ttyUSB*`, `/dev/ttyACM*`; USB COM ports on Windows)
and refuses to choose between several, since opening a port can reset its board. The port is opened once
per process with DTR and RTS released; a CP2102 board on macOS resets on open regardless, so the host
retries HELLO for 5 s before switching to 921600. Windows opens a COM port exclusively: a second open
while any handle is held, in this process or another, fails with `PermissionError(13, 'Access is
denied.')`, so a board that never answers HELLO closes its port before the launcher retries. A USB
device removed under an open port fails the next read the same way (`GetOverlappedResult failed` or `ClearCommError failed`)
and every write after it; the launcher then ends the run with `[esp32] The board disconnected from
USB` instead of writing on.

On Windows 11 with the Silicon Labs driver 11.6.0.420, a classic ESP32 on a CP2102 measured:

| lines before `open()` | opens | reset banner | ROM download mode | what followed |
|---|---|---|---|---|
| DTR and RTS released (the host's open) | 40 | 0 | 0 | the running firmware's CREDIT frames; HELLO answered in 0.06 s, 30 of 30 |
| pyserial's default, both asserted | 20 | 20, `rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)` | 0 | the firmware's INFO at boot, about 0.3 s after the open |
| DTR released, RTS asserted | 20 | 0 | 0 | no byte while the port is open: RTS holds EN low on the two-transistor auto-reset circuit |

A board held in ROM download mode never answers HELLO, and the app's check reports no pokeldn
firmware. Another process holding the port fails the open at once; the app reports the port busy.

On the board the launchers skip every nl80211 step: `--phy auto` resolves to `esp32`, no vif is
deleted, no `iw`, `ip`, `nmcli` or `sysctl` runs, and a joiner's `--mac` becomes the board station's
address. No root is needed on macOS. A scan skips 5 GHz channels (36 and up): the board is 2.4 GHz
only, so a console hosting on 5 GHz cannot be reached. The FRLG hosts inject no beacons; the board's
access point beacons itself.

`POKELDN_ESP32_TRACE=FILE` appends every serial message, one line each: Unix time, `>` (host) or `<`
(board), type and payload in hex.

| tool | what it does |
|---|---|
| `tools/ldn/esp32_first_contact.py` | first run against a new board: `--flash` writes the build with esptool, then HELLO, STATUS, an idle scan counting LDN action frames per channel and source, and with `--keys` the LDN library's scan, decrypting each network |
| `tools/ldn/esp32_sniff.py` | a second board as a sniffer (SNIFF) |
| `tests/test_esp32.py` | the LDN library's host and station on two simulated boards (`pokeldn.ldn.esp32_sim`), from scan to fragmented UDP through two userspace stacks |

A CH9102 or CH343 USB bridge enumerates as CDC ACM: `/dev/ttyACM0` on Linux, `/dev/cu.usbmodem*` on
macOS.

### A board that decodes no OFDM

A console's advertisements are HT MCS 3 ([Discovery](ldn.md#discovery)), so a board that cannot
demodulate OFDM hears its DSSS beacons and none of its advertisements: `esp32_first_contact.py`
counts 0 LDN action frames on every channel. Two checks separate it from a firmware or host fault:

| check | a working board | a board that decodes no OFDM |
|---|---|---|
| `tools/ldn/esp32_census.py` next to a console or a busy access point | `OFDM` and `HT` among the good frames | good frames all `DSSS`; the OFDM frames fail with `rx_state` 65 |
| joined to an access point as a station, the rate of the unicast frames the access point sends it | HT MCS 5 to 7 (HT40 access point) | about 97% at DSSS 5.5 Mbit/s, never above OFDM 6 or HT MCS 1 |

A station association and a ping succeed on such a board: the access point's rate adaptation falls
back to DSSS. A generic ESP32-WROOM-32 DevKit (ESP32-D0WD-V3 revision 3.1, CP2102) fails both checks
with firmware other than pokeldn's; a WROOM-32E board with the same chip passes both, hears Sword's
gift network and delivers a Mystery Gift ([issue 1](https://github.com/Decryptu/pokeldn/issues/1)).

## Trades by board

The ELEGOO board (ESP32-D0WD-V3 revision 3.1 on its unbranded module, CP2102, macOS, 921600 baud)
trades with retail Switch 2 consoles:

| role | title | result |
|---|---|---|
| station | FireRed | trade; 38 to 42 'T' slots a second each way |
| access point | FireRed, LeafGreen | trade and Wonder Cards; the console's association below |
| station | Scarlet | trade, more than one in a seat; below |
| access point | Scarlet | trade: the console's type-3 join answered with the type 9 accept, key `0x80` opened, offer sent 11.4 s after the join |
| station, access point | Legends Z-A | trade in both roles |
| station, access point | Let's Go | trade in both roles |
| access point | Legends Arceus | trade through the four host phases (3, 6, 11, 14) |
| station | Sword | trade; late-ack resends arrive out of order ([Sword session](swsh_session.md)) |
| access point | Sword | trade and Mystery Gift |
| station | Brilliant Diamond | Union Room trade to the save. A client that stops without leaving stays a station in the room; the console refuses the same variable id (result 7) until the player re-enters the room or a fresh id is used ([The Pia layer](pia.md#the-version-9-connection-request)) |
| access point | Brilliant Diamond | a Shining Pearl entered the hosted room and traded to the save ([Hosting](bdsp_session.md#hosting)) |

Other boards, with their trades:

| board | role | title | result |
|---|---|---|---|
| XIAO ESP32C3 | station | FireRed | trade, valid PK3 checksums; zero lost ETH_TX, bad wire frames and USB resyncs |
| XIAO ESP32C3 | access point | Sword | trade through the packaged macOS app, legal PK8 |
| XIAO ESP32C6 (ceramic antenna) | station | FireRed | trade, clean console departure |
| XIAO ESP32C6 (ceramic antenna) | access point | Sword, Scarlet | trade, valid PK8 records, clean console departure |
| XIAO ESP32S3 (macOS) | station | FireRed | trade, mutual cancel, clean link close; 5099 of 5099 ETH_TX, no bad wire frame, no USB resync |
| XIAO ESP32S3 (macOS) | access point | FireRed, Sword | trade, 344-byte PK8, clean console departure; zero lost ETH_TX; the board answers HELLO afterwards |
| ESP32-S3 (Windows, reported in [PR 2](https://github.com/Decryptu/pokeldn/pull/2)) | station | FireRed | trade |

A FireRed console joining the board's access point lists the network (it accepts the zero-length
hidden SSID, the rate order, capability `0x0431` and the WMM element), authenticates open and sends
one association request 24 ms after the authentication: capability `0x0431`, listen interval 10,
the SSID as 32 hex characters, rates `02 04 0b 16 0c 12 18 24` and `30 48 60 6c`, power capability `00 14`,
RSN capabilities `0x0000`, a WMM information element, vendor element `00 22 aa 10 01 02`. Its LDN
authentication request reaches `RX_ETH` 40 ms after `STA_JOINED`. Its first broadcasts need the
firmware's forwarding ([A station's broadcasts](ldn.md#a-stations-broadcasts)).

Scarlet as joiner: the board seated on its first association attempt, 0.35 s from `STA_JOIN` to
`LINK`; the session join was answered at 0.93 s and the announcement came 5.8 to 7.7 s after the
seat. The console's first
burst of 46 records (about 50 KB) saturates board-to-host at 92 KB/s.

### Joining

`STA_JOIN` makes one association attempt: a fast scan on the given channel and BSSID, then open
authentication and association. A retail Sword's matching network failed the attempt in 2 of 10
board joins, `LINK` down with reason `0xc9` (no access point found, 2.4 s after `STA_JOIN`) or
`0x2` (authentication expired, 1.3 s after), while the board went on hearing its advertisements on
that channel; a new `STA_JOIN` on the same search associated. A successful join reports `LINK` up
0.23 to 0.34 s after `STA_JOIN`. The host sends `STA_JOIN` up to three times
(`pokeldn.ldn.esp32_wlan.JOIN_ATTEMPTS`) within the join timeout. Why the console's network
misses a given attempt is unknown.

## Unresolved

- The softAP negotiates WMM, which a Switch host does not; trades complete with and without it.
  `POKELDN_ESP32_AP_FLAGS=2` (`AP_FLAG_NO_QOS`) clears the station's QoS flag after association: the
  board then sends plain data while the console keeps sending QoS data. Z-A, Legends Arceus, Let's
  Go and LeafGreen trades complete with it. Two sniffed Z-A trades retried 11.9% of the board's
  frames and 11.5% of the console's without QoS data, and 1.3% of each with it; nothing attributes
  the difference to the setting.
- ESP32-S3 throughput, and S3 trades in the host role or with titles other than FireRed, are
  unmeasured on a local board.
- A Scarlet console joined to the board's access point once acknowledged the announcement and sent
  no port 2 join; the gates that can hold it are in [the Scarlet page](sv.md#unresolved).
- What in the access point's receive path misses 1 to 22% of a station's OFDM first copies, and ACKs
  during a FireRed hold, is unknown; the settings ruled out are in
  [Receive misses on two boards](#receive-misses-on-two-boards).
- Whether an Espressif ESP32-WROOM-32E module misses fewer frames as an access point than the ELEGOO
  board's unbranded module is unmeasured. easyworld reports that a classic ESP32 must be the
  ESP32-WROOM-32E and that the older ESP32-WROOM-32 does not trade reliably; one WROOM-32 DevKit
  decoded no OFDM at all ([A board that decodes no OFDM](#a-board-that-decodes-no-ofdm)). Whether
  that is the module or that one board is unknown. Espressif's ESP32-DevKitC-32E carries the
  WROOM-32E module; its shield reads ESP32-WROOM-32E with the Espressif logo.

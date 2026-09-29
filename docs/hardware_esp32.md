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
(`zlib.crc32`). The board boots at 115200 baud; `BAUD` switches both ends. Anything before a `0x00`,
the ROM's boot text included, fails the checksum and is discarded.

| type | direction | payload |
|---|---|---|
| `0x01` HELLO | host | none; answered by CREDIT 0, then INFO |
| `0x02` BAUD | host | u32 baud; RESULT at the old rate, then the switch, which waits up to 3 s for the UART to drain (at 115200 the ring holds over a second of RX_MGMT). The first HELLO at 1500000 is lost in about one open of four; `open_serial` retries it |
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
| `read_max_us`, `write_max_us`, `handler_max_us`, `handler_max_type` | the longest `uart_read_bytes` (20 ms timeout included), `uart_write_bytes`, and command with its type |
| `heap_min`, `queue_max`, `refused_heap`, `refused_queue` | least free heap, deepest outgoing queue, messages refused at the heap floor and on a full queue |
| `tx_eth_max_us`, `tx_eth_total_us`, `tx_eth_slow` | ETH_TX in `esp_wifi_internal_tx`, retries included: longest, sum, count over 5 ms |

EtherType `0x88B7` frames are LDN authentication; `esp32_wlan` turns them into the LDN library's
`CustomFrameEvent`. Every other Ethernet frame goes to an L2 port, chosen by platform or by
`POKELDN_L2=tap|userspace`:

| port | where | the launchers' sockets |
|---|---|---|
| kernel TAP named after the interface | Linux | kernel sockets, `SO_BINDTODEVICE` and `AF_PACKET` unchanged |
| `userspace_ip` stack | every other host (macOS) | `userspace_ip.udp_socket` and `packet_socket` |
| `MemoryPort` | tests | none |

## The serial ceiling

At 921600 baud, 8N1, the board-to-host line carries 92.16 KB/s. A message costs its payload plus a
type byte, a four-byte CRC, the COBS overhead (one byte per 254 and the delimiter) and, for RX_MGMT,
two bytes of channel and RSSI. Pia payloads are AES-GCM ciphertext and do not compress.

| traffic | what it costs the line |
|---|---|
| a station's data frame, hosting | the frame as RX_ETH, and 48 bytes for the 40-byte RX_MGMT copy unless AP flag 4 is set (`POKELDN_ESP32_AP_FLAGS=4`) |
| a station's data frame, joined | the frame as RX_ETH only; station mode passes management frames alone |
| an LDN advertisement nearby | the whole action frame, about ten a second per network |

The outgoing queue holds 384 messages and refuses one below 64 KB of free heap (a 128-entry queue
dropped 337 in a Scarlet host's opening burst). A console at the line's rate holds the heap at that
floor (`heap_min` 63976, `queue_max` 95, `refused_heap` 219): the heap, not the queue, refuses RX_ETH.

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

A Legends Z-A seat at 921600 with CREDIT seated with no refused association, first message at 1.68 s
(1.7 s at 1500000), 695 of 695 ETH_TX, and traded: the default rate wins Z-A's seat race.

### Host-to-board command loss and CREDIT

Under a console's flood, host commands can be lost before the handler: one Scarlet seat handed the board 660 ETH_TX in 7.5 s and the board counted 92 (`tx_eth +
tx_eth_failed`), with no CCMP packet number spent on the rest and `tx_eth_retried` 0. Causes and
fixes:

| cause | measured | fix |
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

Since the idle count and the CREDIT ahead of the queue, 26 seats (Scarlet both roles, Sword host)
handed the board 35514 ETH_TX and it counted 35514, every overflow counter 0.
`tools/ldn/esp32_cmd_loss.py TRACE` reconciles a trace: ETH_TX written against `tx_eth +
tx_eth_failed`, bytes written since HELLO against the last CREDIT. Earlier losses of a few commands
with no overflow counted (6 of 2333, 10 of 1691, 1 of 836) fell in the host's first burst after the
link came up; the cause is unmeasured.

### Transmit timing

On a calm Scarlet seat ETH_TX spent 0.12 ms average and 1.57 ms at most in the driver; the console
held all 44 of the joiner's records 0.35 s after sending.

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

Five FireRed trades hosted as an access point; the console acknowledged every frame. Wait is ETH_TX
to TX-done; retries are the share of data frames the sniffer saw with the retry bit.

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
Six FireRed trades on channel 1, in order; missed is the share of the console's first copies the
board did not hear:

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

The long waits belong to channel 1 in this room, which also carries the console's home access point:

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

Only the board misses ACKs. During a hold the
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

### Two boards reproduce the misses

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
  `AF_PACKET` socket delivering whole IPv4 Ethernet frames. Each has a real file descriptor (a pipe,
  one byte per queued datagram), so `select` and `trio.lowlevel.wait_readable` work.
- The board's frames reach the stack through trio tasks in the launcher's own trio loop. A blocking
  `select` inside that loop starves them and each datagram waits out the full timeout; wait with
  `trio.lowlevel.wait_readable` under `trio.move_on_after`. A Scarlet joiner blocking in
  `select(0.05)` handled one message per 50 ms and the console re-sent its records for 50 to 70 s.

## The board's LED and buttons

The ELEGOO ESP-32 Type-C board (CP2102, ESP32-D0WD-V3) carries an unbranded module with a PCB antenna
and no Espressif module name:

| part | wired to | controllable |
|---|---|---|
| red LED | the 3.3 V rail | no, lit whenever the board has power |
| blue LED | GPIO2, lit when high | yes |
| EN button | the chip's reset | no |
| BOOT button | GPIO0 | yes: each press sends BUTTON (`0x8E`) and flashes the LED |

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

## Building and flashing

ESP-IDF v6.1 (tag `v6.1`, commit `fff9895c82d744c7237be8847347bdd1b07c6643`), target `esp32`;
`install.sh esp32` is enough, and Linux and macOS (Apple silicon) build the same image size.

    cd firmware/esp32
    idf.py build
    idf.py -p <port> flash

The image is 0x90650 bytes. The console output is off (`CONFIG_ESP_CONSOLE_NONE`): UART0 is the host
link, left unrouted, so the firmware assigns GPIO1 and GPIO3 itself (`uart_set_pin`) or the board
boots and never answers.

## Running

`POKELDN_RADIO=esp32:<port>` puts every launcher's `ldn` calls on the board. `esp32:auto` takes the
only USB serial port present (`/dev/cu.usbserial-*`, `/dev/cu.SLAB_USBtoUART*`, `/dev/ttyUSB*`) and
refuses to choose between several, since opening a port resets its board. The port is opened once
per process with DTR and RTS released; a CP2102 board on macOS resets on open regardless, so the host
retries HELLO for 5 s before switching to 921600.

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

## Measured on a board

The ELEGOO board (ESP32-D0WD-V3 revision 3.1 on its unbranded module, CP2102, macOS, 921600 baud)
has traded with retail Switch 2 consoles:

| role | title | result |
|---|---|---|
| station | FireRed | joined 2.5 s after the scan, Pia at 3.3 s, GBA link at 3.4 s; 38 to 42 'T' slots a second each way, as on the rtw88 adapter |
| access point | FireRed, LeafGreen | trade and Wonder Cards; the console's association below |
| station | Scarlet | four trades in three runs, below |
| access point | Scarlet | the console's type-3 join answered with the type 9 accept, key `0x80` opened, offer sent 11.4 s after the join. In one of two runs the console acknowledged the announcement and never sent its port 2 join; re-entering the search cleared it |
| station | Legends Z-A | seated on the first scan: selection record (`0100`) at 1.75 s, offer at 11.9 s, close (`0104`, `0200`) at 15 s |
| station, access point | Let's Go | trade in both roles |
| access point | Legends Arceus | trade through the four host phases (3, 6, 11, 14) |
| station | Sword | channel 6 by the busiest-channel scan, the first association held, confirmation ladder done 34 s after the seat; late-ack resends arrive out of order ([Sword session](swsh_session.md)) |
| access point | Sword | two Mystery Gifts |
| station | Brilliant Diamond | Union Room trade to `NetDataReturnSelectData` and the save. A killed client leaves its station in the room; the same MAC is never answered until the player leaves and re-enters |
| access point | Brilliant Diamond | a Shining Pearl entered the hosted room, handshake done 0.46 s after association, trade to the save ([Hosting](bdsp_session.md#hosting)) |

A FireRed console joining the board's access point lists the network (it accepts the zero-length
hidden SSID, the rate order, capability `0x0431` and the WMM element), authenticates open and sends
one association request 24 ms later, not retried: capability `0x0431`, listen interval 10, the SSID
as 32 hex characters, rates `02 04 0b 16 0c 12 18 24` and `30 48 60 6c`, power capability `00 14`,
RSN capabilities `0x0000`, a WMM information element, vendor element `00 22 aa 10 01 02`. Its LDN
authentication request reaches `RX_ETH` 40 ms after `STA_JOINED`. Its first broadcasts need the
firmware's forwarding ([A station's broadcasts](ldn.md#a-stations-broadcasts)).

Scarlet as joiner: the first association attempt seats, 0.35 s from `STA_JOIN` to `LINK` (the rtw88
adapter needs 30 to 60 refused attempts); the session join is answered at 0.93 s and the announcement
comes 5.8 to 7.7 s after the seat. The console's first burst of 46 records (about 50 KB) saturates
board-to-host at 92 KB/s.

## Unresolved

- The softAP negotiates WMM, which a Switch host does not; trades complete with and without it.
  `POKELDN_ESP32_AP_FLAGS=2` (`AP_FLAG_NO_QOS`) clears the station's QoS flag after association: the
  board then sends plain data (446 frames on a Z-A trade) while the console keeps sending QoS data.
  Z-A, Legends Arceus, Let's Go and LeafGreen trades completed with it. Two sniffed Z-A trades
  without and with QoS data retried 11.9% then 1.3% of the board's frames and 11.5% then 1.3% of the
  console's: the retry rate follows the air, and nothing attributes a difference to the setting.
- What in the access point's receive path misses 1 to 22% of a station's OFDM first copies, and ACKs
  during a FireRed hold, is unknown; the settings ruled out are in
  [Two boards reproduce the misses](#two-boards-reproduce-the-misses).
- Whether an Espressif ESP32-WROOM-32E module misses fewer frames as an access point than the ELEGOO
  board's unbranded module is unmeasured. easyworld reports that a classic ESP32 must be the
  ESP32-WROOM-32E and that the older ESP32-WROOM-32 does not trade reliably. Espressif's ESP32-DevKitC-32E carries that module; its shield reads ESP32-WROOM-32E with the Espressif logo.

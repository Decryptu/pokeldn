---
title: ESP32 radio
parent: Hardware and setup
nav_order: 1
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
- `wpa_ap_join` also queues the station's MAC. The main loop then installs the pairwise key with
  `esp_wifi_set_ap_key_internal(CCMP, mac, 0, key)` and opens the port with
  `esp_wifi_wpa_ptk_init_done_internal(mac)`, the order hostapd's `PTKINITDONE` state uses
  (`wpa_auth.c:2290-2332`). The group key goes in at `WIFI_EVENT_AP_START` with index 1.
- `esp_wifi_wpa_ptk_init_done_internal` is what posts `WIFI_EVENT_AP_STACONNECTED` (event 14,
  `ieee80211_supplicant.o`); the blob posts no other connect event for a WPA2 station. Never
  wait for that event to install the key: with no 4-way handshake it never comes, and the
  console's first encrypted frame is dropped.

The table layout is the ESP-IDF v6.1 blob's ABI. The firmware refuses to build against another
release.

## The access point's frames

The softAP's beacon, probe response and association response are built inside the closed
`libnet80211.a`. Read statically from the v6.1 blob (`ieee80211_output.o` offsets), against what
`vendor/LDN`'s access point sends a Switch:

| field | Switch form | ESP32 softAP | settable |
|---|---|---|---|
| hidden SSID element | 32 zero bytes | length 0 (`ieee80211_beacon_construct` 0xc4) | no |
| Supported Rates | `82 84 8B 96 0C 12 18 24` | `8B 96 82 84 0C 18 30 60` | no; same twelve rates and basic bits, 9 and 18 in Extended |
| Extended Rates | `30 48 60 6C` | `6C 12 24 48` | no |
| capability, beacon | `0x0511` | `0x0431` (short preamble constant, `ieee80211_getcapinfo` 0x7b) | no |
| HT elements | none | present in 11b/g/n | removed: the firmware sets 11b/g |
| RSN capabilities | `0x000c` | hostapd's own | set: `wpa_ap_get_wpa_ie` returns the Switch's element |
| WMM | none | present in 11g | only 11b-only removes it |

A hidden softAP answers directed probes only and puts the real SSID in the probe response. The
association request must carry the configured SSID or it is dropped (0x9c6).
`esp_wifi_80211_tx` accepts beacon frames and refuses association responses
(`ieee80211_raw_frame_sanity_check` 0xf9), and the blob's own beacons cannot be stopped.

## Serial protocol

A frame is `COBS(type | payload | crc32-le(type | payload))` followed by `0x00`. The CRC is
CRC-32/ISO-HDLC (`zlib.crc32`). The board boots at 115200 baud; `BAUD` switches both ends.
Anything before a `0x00`, including the ROM's boot text, is discarded by the checksum.

| type | direction | payload |
|---|---|---|
| `0x01` HELLO | host | none; answered by CREDIT 0, then INFO |
| `0x02` BAUD | host | u32 baud; RESULT at the old rate, then the switch. The switch is a queue entry behind the RESULT and waits up to 3 s for the UART to drain: at 115200 the ring can hold more than a second of RX_MGMT from a console advertising nearby, and a 100 ms wait switched with the RESULT still in it. The host's first HELLO at the new rate is lost in about one open of four at 1500000, so `open_serial` retries it |
| `0x03` CHANNEL | host | u8 channel; idle only |
| `0x04` STA_JOIN | host | u8 channel, 6 BSSID, 32 SSID (the LDN SSID's hex text), 16 key, 6 station MAC (zero = random); optional: u8 a fixed data rate (the AP_START bits 3..5 table), then u8 a maximum TX power in 0.25 dBm (`esp_wifi_set_max_tx_power`, 8 to 84; the driver caps it at 61), then u8 flags: 1 RTS before every frame, 2 no RTS before a retry (`esp_wifi_internal_set_rts`) |
| `0x05` STOP | host | none; back to idle, keys cleared |
| `0x06` AP_START | host | u8 channel, 6 BSSID, 32 SSID, 16 key, u8 max stations, u8 flags: 1 the stock association and 4-way handshake, 2 no QoS for the station, 4 no 40-byte copy of each station data frame, bits 3..5 a fixed data rate, `0x40` a beacon every 1000 TU, `0x80` no promiscuous receive; an optional second flag byte: 1 the driver's noise-floor check off, 2 its interval 250, 4 the receive time in each 40-byte data copy's head, 8 retry limits 7 and 4, `0x10` a RX_CENSUS for every frame but its stations' good data frames to it; then an optional maximum TX power in 0.25 dBm |
| `0x07` AP_KICK | host | 6 MAC, u16 reason; deauthenticates |
| `0x08` ETH_TX | host | an Ethernet frame; the driver encrypts it with the station's or the group key. A full driver queue (`ESP_ERR_NO_MEM`) is retried every 1 ms for up to 100 ms before the frame counts as failed; a frame to a station that has left fails at once with `0x3015` (`ESP_ERR_WIFI_NOT_ASSOC`). A station sends the frame's Ethernet source as its 802.11 transmitter address: a source other than the MAC in LINK is never acknowledged (49 of 49 unacked, none seen by the access point) |
| `0x09` RAW_TX | host | an 802.11 frame without FCS (`esp_wifi_80211_tx`); used for advertisements |
| `0x0A` SNIFF | host | u8 channel, 6 MAC; every management and data frame to or from it, whole, as RX_SNIFF; the MAC ff:ff:ff:ff:ff:ff sends every frame on the channel as RX_CENSUS instead |
| `0x0B` STATUS | host | none; answered by STATUS |
| `0x0C` BENCH | host | u32 bytes, u16 message size (8 to 1600); RESULT, then BENCH messages as fast as the UART takes them |
| `0x0D` LED | host | u8 pattern, u8 peak brightness, u16 period ms (0: the pattern's default), u16 duration ms (0: until the next LED); RESULT. A board flashed before it answers `0x106` |
| `0x81` INFO | board | u8 protocol version (1), 6 station MAC, 6 AP MAC, u8 chip revision, text |
| `0x82` RESULT | board | u8 command, i32 `esp_err_t` |
| `0x83` LOG | board | text |
| `0x84` RX_MGMT | board | u8 channel, i8 RSSI, a frame without FCS: an LDN action frame; while hosting also a management frame to our BSSID, the first 40 bytes of a data frame to it, and a station's no-DS broadcast whole |
| `0x85` RX_ETH | board | an Ethernet frame the driver decrypted |
| `0x86` LINK | board | u8 up, u16 reason, 6 MAC; reason `0xFFFF` no association in 15 s, `0xFFFE` keys refused |
| `0x87` STA_JOINED | board | 6 MAC, u8 AID, i8 key install result, u8 port opened |
| `0x88` STA_LEFT | board | 6 MAC, u16 reason |
| `0x89` STATUS | board | text counters, including the driver's TX-done `tx_acked` and `tx_unacked`, `tx_eth_retried` (ETH_TX calls that found the driver's queue full) and `wire_dropped` (board-to-host messages dropped: 384 queued, or free heap under 64 KB), `wire_rx_bad` (host commands that failed COBS or their CRC), `uart_fifo_ovf` and `uart_buffer_full` (UART hardware FIFO and driver ring overflows) and their sum `uart_overflow`, `uart_frame_err` (framing, parity and break events), `uart_events_full` (ticks that found the UART event queue full, when the counters before it may undercount); sent unasked every 2 s while hosting, and polled every 5 s by a host that writes a trace |
| `0x8A` BENCH | board | u32 sequence and random bytes; the last carries sequence `0xFFFFFFFF` and the u32 microseconds the board spent |
| `0x8C` RX_SNIFF | board | u8 channel, i8 RSSI, u8 `sig_mode` (0 legacy, 1 HT), u8 legacy rate code (`wifi_phy_rate_t`), u8 HT MCS with bit 7 set for 40 MHz, a frame without FCS; in sniff mode also every 10-byte ACK on the channel |
| `0x8D` TX_DONE | board | the driver's TX-done of one frame, as a station or an access point: u32 board time in µs, u32 µs since the ETH_TX it completes (all ones for a frame that is not one), u8 acked by the peer's radio, u8 interface, u16 length, then the frame's first 24 bytes (its 802.11 header). STATUS sums the matched ones in `tx_queued_max_us`, `tx_queued_total_us`, `tx_queued_n` and `tx_queued_pending` |
| `0x8E` BUTTON | board | a press of the BOOT button, debounced over 30 ms: u32 board time in µs, u16 press count since boot. The host prints `BOOT button, mark N` and the trace keeps it, so the player marks a moment on the screen |
| `0x8F` RX_CENSUS | board | SNIFF with MAC ff:ff:ff:ff:ff:ff, or AP_START's `0x10`: every frame received, FCS failures and control frames included: u32 receive time in µs, i8 RSSI, i8 noise floor, u8 `rx_state` (0 good), u8 packet type (0 management, 1 control, 2 data, 3 other), u8 `sig_mode`, u8 rate code, u8 MCS with bit 7 for 40 MHz, u16 `sig_len` with FCS, the frame's first 16 bytes |
| `0x8B` CREDIT | board | u32 host bytes read and handled since the last HELLO, counting from the byte after its delimiter; sent on HELLO, every 1024 bytes, when the line falls idle and every 100 ms while it stays idle, ahead of any queued message |

EtherType `0x88B7` frames are LDN authentication; `esp32_wlan` turns them into the LDN
library's `CustomFrameEvent`. Every other Ethernet frame goes to an L2 port:

| port | where | what the launchers' sockets are |
|---|---|---|
| kernel TAP named after the interface | Linux | kernel sockets, `SO_BINDTODEVICE` and `AF_PACKET` unchanged |
| `userspace_ip` stack | every other host (macOS) | `userspace_ip.udp_socket` and `packet_socket` |
| `MemoryPort` | tests | none |

`POKELDN_L2=tap` or `POKELDN_L2=userspace` overrides the platform's choice.

## The serial ceiling

At 921600 baud, 8N1, the board-to-host line carries 92.16 KB/s. A message costs its payload
plus a type byte, a four-byte CRC, the COBS overhead (one byte per 254 and the delimiter) and,
for RX_MGMT, two bytes of channel and RSSI. Pia payloads are AES-GCM ciphertext and do not
compress.

| traffic | what it costs the line |
|---|---|
| a station's data frame, hosting | the frame as RX_ETH, and 48 bytes for the 40-byte RX_MGMT copy unless AP flag 4 is set (`POKELDN_ESP32_AP_FLAGS=4`) |
| a station's data frame, joined | the frame as RX_ETH only; the sniffer passes management frames alone in station mode |
| an LDN advertisement nearby | the whole action frame, about ten a second per network |

A Scarlet host's opening burst, as the board's station, took free heap from 171 KB to 96 KB with
128 messages queued and dropped 337 more. The queue now holds 384 and drops only below 64 KB of
free heap.

The same burst costs the other direction too. In the first 7.5 s of a seat the joiner handed the
board 660 ETH_TX commands and the board counted 92 (`tx_eth` plus `tx_eth_failed`); from then on
the two counts moved together, 500 apart, for the rest of the run. A second board sniffing the air
saw no CCMP packet number spent on the missing frames, and the driver never reported a full queue
(`tx_eth_retried` 0). The commands were lost between the host and the command handler, only while
the console flooded the board's receive path, in both a seat that traded and one that did not. The
UART driver was installed from the main task, so its interrupt shared core 0 with the Wi-Fi task;
it is now installed from the reader task on core 1, and STATUS counts `wire_rx_bad` and
`uart_overflow`.

The loss is in the board's UART receive path. With the UART on core 1 at 1500000 baud, a Scarlet
seat loses about 150 ETH_TX commands in its first 11 s, with 34 `uart_overflow` events and 9
`wire_rx_bad` frames, and none after. `uart_overflow` is the sum of `uart_fifo_ovf` (`UART_FIFO_OVF`,
the 128-byte hardware FIFO, 0.85 ms at this rate) and `uart_buffer_full` (`UART_BUFFER_FULL`, the
driver's 16 KB ring). At 921600 baud the same seat lost 6 of 2333 ETH_TX commands, all between 11
and 16 s, with one `wire_rx_bad` frame, `uart_fifo_ovf` 0 and `uart_buffer_full` 0, and traded.

The board handles each command on the task that reads the UART, and an ETH_TX that finds the Wi-Fi
driver's queue full waits there for it to drain. While it waits, the 16 KB ring fills at line rate;
once it is full the driver stops draining the 128-byte FIFO, which overflows, and the bytes lost
cut frames. `tools/ldn/esp32_bench.py --uplink 5000` reproduces it with no console: the board hosts
an empty network, the host writes 5000 broadcast ETH_TX of 100 to 300 bytes in bursts of 11, and
broadcasts leave at the lowest rate. At 1500000 baud the board lost 369 to 429, with
`tx_eth_retried` 4059, `uart_buffer_full` 294, `uart_fifo_ovf` 305 and `wire_rx_bad` 169. At 921600
the line is slower than the air and nothing was lost.

CREDIT closes it. Once the board has sent one, the host keeps under 8 KB written and not yet
reported (`esp32.FLOW_WINDOW`), from a writer thread, so a launcher's trio loop only queues. The
host drops ETH_TX and RAW_TX past 512 queued frames (`Radio.tx_dropped`), and if no CREDIT moves
while the window is shut, the host tells a lossy line from a busy board by what the board sends. An
idle reader repeats its count every 100 ms: a count repeated unchanged for 0.3 s means the rest was
lost on the line, and the host reopens the window (`Radio.flow_resyncs`). A board that sends no
count at all is busy and gets 5 s. Never resync on silence alone: a busy reader holds up to 0.7 s,
and a resync then puts 16 KB in flight against a 16 KB ring. The board logs a command that takes
over 50 ms (`slow command`) and a reader turn over 100 ms (`reader held`). A LOG line is refused at
the heap floor like any message, so STATUS also carries maxima since boot:

| field | what it is |
|---|---|
| `read_max_us` | the longest `uart_read_bytes` call, its 20 ms timeout included |
| `handler_max_us`, `handler_max_type` | the longest command and its type |
| `write_max_us` | the longest `uart_write_bytes` call |
| `heap_min`, `queue_max` | the least free heap and the deepest outgoing queue a send saw |
| `refused_heap`, `refused_queue` | messages refused at the heap floor, and on a full queue |
| `tx_eth_max_us`, `tx_eth_total_us`, `tx_eth_slow` | ETH_TX's own time in `esp_wifi_internal_tx`, retries included: the longest, the sum, and the count over 5 ms |

`uart_read_bytes` (ESP-IDF 6.1, `uart.c:1738`) waits its whole timeout again for every ring item
until it has `length` bytes. With `length` 512, a host writing a 21-byte command every 15 ms was
read 461 ms late (`tools/ldn/esp32_bench.py --port PORT --bauds 1500000 --trickle 5`), and every
command in that read waited with it. A Scarlet seat measured `read_max_us` 311644. The reader now
waits for one byte, then takes what `uart_get_buffered_data_len` reports with no timeout:
`read_max_us` is 20.3 ms on the same trickle, and 20.5 ms with BENCH filling the other direction at
150 KB/s.

A console's traffic at the line's rate holds free heap at the 64 KB floor (`heap_min` 63976,
`queue_max` 95, `refused_heap` 219): the heap floor, not the queue's 384 entries, is what refuses
RX_ETH.

`uart_write_bytes` busy-loops while the driver's TX ring is full (IDF 6.1 `uart.c:1662`, `free_size`
0 retried without blocking), and the writer task (priority 20) shares core 1 with the reader (19).
Whenever the board-to-host line is full the writer spins and the reader, and the command it is
handling, wait. A Scarlet seat's flood held ETH_TX up to 707 ms inside `esp_wifi_internal_tx`, and the
host handed the board 3 to 29 ETH_TX a second against the ~150 the joiner produced, with the air 3%
busy. `tools/ldn/esp32_pair_bench.py AP STA --flood 0 --send 20 --bench` reproduces it with two
boards: with the spin, `read_max_us` 7982767, one host resync and 74 sends refused; with the writer
sleeping until the frame fits (`uart_get_tx_buffer_free_size`), `read_max_us` 30382, none of either.
The next Scarlet seat that flooded stopped after one second instead of four to thirteen
([Scarlet and Violet](sv.md#the-retail-acknowledgement-and-a-flood-of-retransmits)).

On a calm Scarlet seat ETH_TX spent 0.12 ms on average in the driver and at most 1.57 ms, and the
console held all 44 of the joiner's records 0.35 s after they were sent.

TX_DONE separates the board from the peer. On a flooding Scarlet seat a frame waited 1.0 ms median
and 6.8 ms at most between ETH_TX and its TX-done, and the console's radio acknowledged 1267 of 1267.
The same seat's TX_DONE messages reached the host 15 ms after their board time while calm and 446 ms
(590 ms at most) in the flood's worst second: the board-to-host line backs up under the console's
flood, and a host reading arrival times reads that lag. Board time minus the smallest arrival offset
gives a message's lag on the line.

The two-board bench (`tools/ldn/esp32_pair_bench.py`, 1200-byte broadcasts from the access point,
200-byte frames from the station) delivers every station frame. Calm, 20 a second: 187 of 187
acknowledged, 1.6 ms average from ETH_TX to TX-done, 10.7 ms at most. Under a flood of 100 a second,
which at 1 Mbit/s takes about 96% of the air: 1227 of 1227, 26.8 ms average, 218 ms at most, and the
station received 794 of the flood.

### The FireRed hold

Five FireRed trades hosted as an access point, the same line with the channel changed, the last with
the access point's rate pinned at 24 Mbit/s; the console acknowledged every frame in all five. Wait is ETH_TX to TX-done; retries are the share of data
frames the sniffer saw with the retry bit, from the access point and from the console.

| channel | frames | wait median | wait p99 | wait max | holds over 100 ms | retries AP / console |
|---|---|---|---|---|---|---|
| 1 | 7489 | 1.24 ms | 116 ms | 261 ms | 5 | 13.3% / 12.8% |
| 6 | 13670 | 0.85 ms | 18 ms | 108 ms | 1 | 10.5% / 7.7% |
| 11 | 7069 | 0.86 ms | 9 ms | 46 ms | 0 | 15.0% / 5.7% |
| 1 | 7332 | 1.03 ms | 25 ms | 88 ms | 0 | 20.6% / 9.4% |
| 1, 24 Mbit/s pinned | 6892 | 0.73 ms | 69 ms | 185 ms | 5 | 2.8% / 14.3% |

Host to board adds 0.12 to 0.47 ms median (socket to ETH_TX written) and 3.1 to 3.4 ms (ETH_TX to
the board). Every wait over 100 ms is head-of-line: one frame the console has not acknowledged
holds for 108 to 261 ms, the frames queued behind it then complete in a burst (up to 10 within
5 ms), and the access point's own action frames keep going meanwhile. The sniffer saw one to three
copies of such a head frame, retries at 54 or 48 Mbit/s. The retry share does not decide it; the
channel does (below, The channel). A foreign station associating for 4 s every
20 to 25 s coincided with none of the 81 frames over 100 ms.

The console stays awake and on the channel through a hold. Through each of the five holds on
channel 1, the sniffer shows the console's data frames to the board between the head frame's
copies, all with the power-management bit clear; the one hold on channel 6 shows a single copy. In four trades the console never set that bit
toward the board. It set it only toward its infrastructure access point, which shares channel 1,
and sent that access point nothing while the session ran. The board's copies of a held frame are
spread across the hold with the console's frames between them, not sent back to back. The two sides
also pick rates differently:

| sender | first tries at 54 Mbit/s | retries |
|---|---|---|
| board (access point) | 91 to 100% | 54 Mbit/s for 77 to 92%, then 48, rarely 6 or 36 |
| console | 92 to 99% | 48, 36, 24, 18, down to 1 Mbit/s |

What makes the board wait about 100 ms between copies of a frame is unknown. Bits 3 to 5 of the
access point's flag byte pin its data rate (`esp_wifi_internal_set_fix_rate`); 0 leaves rate control
on:

| bits 3..5 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| rate, Mbit/s | 1 | 11 | 6 | 12 | 24 | 36 | 54 |

`POKELDN_ESP32_AP_FLAGS=0x28` pins 24 Mbit/s. Pinned, the board's retry share fell to 2.8% and the
holds stayed: five of 102 to 185 ms. The rate the board picks does not decide a hold.

### The CPU clock

The firmware runs the CPU at 240 MHz (`CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240`; IDF's default is 160).
Six FireRed trades on channel 1, rate control on, in this order; wait is ETH_TX to TX-done, missed is
the share of the console's first copies the board did not hear, retries the console's on the sniffer:

| CPU | RX buffers | frames | p90 | p99 | p99.9 | over 5 ms | over 40 ms | over 80 ms | holds | missed | console retries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 160 MHz | 16 | 6744 | 4.7 ms | 30.4 ms | 91.7 ms | 605 | 41 | 10 | 1 | | 8.8% |
| 160 MHz | 25 | 6999 | 4.6 ms | 34.4 ms | 106.5 ms | 615 | 57 | 19 | 1 | 6.8% | 13.0% |
| 240 MHz | 25 | 7425 | 3.1 ms | 13.5 ms | 34.3 ms | 322 | 5 | 0 | 0 | 5.2% | 12.4% |
| 240 MHz | 25 | 7235 | 3.0 ms | 15.7 ms | 66.3 ms | 242 | 16 | 3 | 0 | 4.9% | 11.9% |
| 160 MHz | 25 | 8349 | 4.3 ms | 27.5 ms | 82.3 ms | 666 | 41 | 9 | 0 | 5.3% | 10.2% |
| 240 MHz | 25 | 7021 | 5.0 ms | 31.7 ms | 109.6 ms | 708 | 57 | 16 | 1 | 8.5% | 18.9% |

The two shortest waits measured on channel 1 were at 240 MHz, and the third 240 MHz trade matched the
160 MHz ones. The clock does not decide the wait on its own; the spread between runs of one setting is
as large as the difference. `tools/ldn/esp32_hold.py CAPTURE TRACE` prints the wait on its `board
queue -> TX-done` line.

### The channel

The long waits belong to channel 1 in this room, which also carries the console's home access point.
Every FireRed trade on channel 11 had its p99 wait under 12 ms and no frame over 50 ms; channel 1
ranged from 13.5 to 116 ms:

| channel | trades | wait p99 | wait max | trades with a hold over 100 ms | board missed, console first copies |
|---|---|---|---|---|---|
| 1 | 9 | 13.5 to 116 ms | 65 to 261 ms | 5 | 4.9 to 8.5% |
| 6 | 1 | 18 ms | 108 ms | 1 | |
| 11 | 3 | 9 to 11.2 ms | 26 to 46 ms | 0 | 5.5%, 6.0% |

On channel 11 the board misses as large a share of the console's first copies as on channel 1, and
its p90 wait is the same (4.5 ms); only the tail differs (over 20 ms: 8 and 9 frames, against 42 to
137 in the six channel-1 trades counted). The receive misses do not make the holds. `config/host.local.toml` takes a
`[host] channel`; the console joins a host on 1, 6 or 11.

### The board is the deaf side

A sniffing board keeps every ACK on its channel as a 10-byte RX_SNIFF frame (the promiscuous control
filter, ACK only). An ACK names only its receiver, so `tools/ldn/esp32_hold_air.py` reads one as the
answer to the data copy just before it and counts copies acknowledged on the air and sent again
anyway: such a copy means its sender missed the ACK. One FireRed trade on channel 1 (rate control
on, 6744 frames, one hold over 100 ms):

| sender | first copies | no ACK on the air after it | copies acknowledged and sent again |
|---|---|---|---|
| board | 6514 | 490 (7.5%) | 56 |
| console | 4517 | 428 (9.5%) | 2 |

Each receiver leaves a similar share of first copies unacknowledged; only the board misses ACKs. In
the 119 ms hold the board's first copy went unacknowledged, the console acknowledged the second, and
the board sent a third, which was acknowledged; the console meanwhile sent one frame five times
before the board acknowledged it. In a 61 ms wait the console acknowledged the first copy and the
board sent it again. The board's copies of a held frame are about 40 ms apart in sniffer order.
During a hold the board hears neither the console's data frames nor its ACKs.

Between the first and last copy of a held frame, the console's data frames to the board carry the
retry bit on 8 of 19 (42%, rate control on) and 19 of 29 (66%, pinned), against 11% and 14% over the
whole session; one console frame went out six times at six rates. The sniffer receives both sides at
-19 to -21 dBm throughout.

The console's retries toward the board are the board's receive misses. The board's promiscuous
receive path copies the 802.11 header of every frame the console sends it (RX_MGMT, 40 bytes);
matched by sequence number against the sniffer (`tools/ldn/esp32_rx_copies.py HOST_TRACE SNIFF_TRACE
--ap BSSID --sta MAC`), a frame the console sent more than once reached the board as one copy
carrying the retry bit in 1008 of 1027 over three trades: the board never heard the first copy the
sniffer heard. The board missed 5.7 to 8.5% of the console's first copies at 54 Mbit/s and 4.5 to
12.1% at 48 Mbit/s, while its own RSSI for the console was -20 to -21 dBm. In sniffer order a missed
first copy follows another console frame 46 to 52% of the time (two trades) and 37% (a third),
against 28 to 32% for a first copy the board heard. A board copy that carries the retry bit, with no
earlier copy of its sequence number, marks a miss from the board's trace alone. The console's first copies that
no ACK followed and those that one did are alike: 414 of 428 against 3995 of 4089 at 54 Mbit/s,
sniffer RSSI median -17 against -16 dBm, length median 203 bytes both.

### Two boards reproduce the misses

`tools/ldn/esp32_pair_bench.py AP STA --flood 0 --burst N --send R` has the station board send
200-byte frames and counts, from the access point's own header copies, the frames whose first copy
it missed:

| access point | channel | station sends | first copies missed | station's longest wait for an ack |
|---|---|---|---|---|
| board 2 | 1 | 50 pairs a second | 11.1% | 89 ms |
| board 1 | 1 | 50 pairs a second | 14.2% | 100 ms |
| board 2 | 11 | 50 pairs a second | 22.2% | 17 ms |
| board 2 | 11 | 100 single frames a second | 5.5% | 22 ms |
| board 2 | 11 | 20 single frames a second | 7.5% | 8 ms |

Either board misses as an access point, on either channel, on an otherwise idle air; a frame sent
right after another is missed about twice as often. The access point hears the station at -43 to
-48 dBm. Identical runs (channel 11, 20 single frames a second, 30 s) missed 6.1, 9.3, 9.8, 11.3,
16.9, 17.9, 43.6 and 43.7%.

The misses are spread evenly in time. With the second AP_START flag byte's bit 2 the header copies
carry the access point's receive time (`rx_ctrl.timestamp`, u32 us, after the RSSI); folded on that
clock, 595 misses among 10511 frames over 60 s fall at 4 to 9% of frames in every twentieth of
102.4, 51.2, 25.6 and 1024 ms.

Ruled out as the cause, each by a bench with one flag changed:

| flag | change | first copies missed |
|---|---|---|
| AP `0x40` | a beacon every 1000 TU (a sniffing board counted 9 in 10 s) | 43.6%, 10.0% |
| AP `0x80` | promiscuous receive off; the station's acks took as long (6.8%, 9.0% of frames over 3 ms, against 6.1%, 13.6%) | not countable |
| second byte bit 0 | `pm_noise_check_disable`: clears `g_pm+21`, after which libpp's `pm_noise_check` returns before measuring | 7.5, 13.2, 8.1% against 7.0, 5.9, 7.9% |
| second byte bit 1 | libpp's `NoiseTimerInterval` (`pp.o` `.data`, u16 100) set to 250 | 6.6% against 5.5% |

Static receive buffers raised from 16 to 25 (`CONFIG_ESP_WIFI_STATIC_RX_BUFFER_NUM`, the ESP32's
maximum) on the access point: 50 pairs a second on channel 1 missed 9.6, 8.2, 9.0% against 10.7,
11.6, 11.8%; 20 single frames a second on channel 11 missed 3.4, 2.7, 5.2% against 3.0, 2.5, 3.8%.
A FireRed trade on channel 1 with 25 buffers had one hold of 105 ms, and the board missed 316 of 4637
of the console's first copies (6.8%), the range it missed with 16.
With the CPU at 240 MHz (`CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240`, was 160) on top of 25 buffers, the
same benches missed 4.6, 5.4, 5.2% (pairs, channel 1) and 5.5, 6.1, 6.4% (single frames, channel 11).

The misses depend on the modulation, not the signal margin. With the station's rate pinned (STA_JOIN's
rate byte, `esp32_pair_bench.py --sta-rate N`), 50 single frames a second for 60 s on channel 11,
about 2520 frames a run, board 2 the access point:

| station rate | first copies missed | ETH_TX to TX-done, median |
|---|---|---|
| 54 Mbit/s OFDM | 2.3, 4.0, 2.4, 2.9% | 707 us |
| 6 Mbit/s OFDM | 3.7, 5.4, 3.1, 3.1% | 956 us |
| 1 Mbit/s DSSS | 1, 2, 1 and 1 frames (0.04 to 0.08%) | 2960 us |

With the boards' roles swapped the same runs missed 3.1, 2.6% (54), 4.3, 1.9% (6) and 0.2, 0.2% (1).
6 Mbit/s needs far less signal than 54 and misses as many; DSSS, spread over 11 chips a bit, almost
never misses. The Switch asleep, its controllers' Bluetooth off, changed nothing (the third and
fourth runs above).

Less transmit power means more misses (STA_JOIN's power byte, `--sta-power`, 54 Mbit/s, two passes of
60 s): the driver's default 78 (19.5 dBm, read back) 1.5, 3.1%; 60: 1.9, 3.7%; 40: 2.3, 5.2%; 28: 4.5,
12.9%; 20: 3.5, 4.0%; 12: 20.8, 15.3%; 8 (read back 3): 16.2, 14.3%. The access point reports the
station at -33 to -35 dBm from 17 up to 61 alike: its RSSI does not follow the station's power this
close. Receiver overload is not the cause.

The misses depend on the channel. 54 Mbit/s, 50 frames a second, 60 s, two passes:

| channel | 1 | 3 | 5 | 7 | 9 | 11 |
|---|---|---|---|---|---|---|
| first copies missed | 9.7, 3.7% | 0.8, 0.8% | 1.6, 1.9% | 2.3, 2.1% | 0.8, 1.8% | 2.1, 5.7% |

Folded on the access point's receive clock at 19900 to 20100 us and 9950 to 10050 us in 30 s windows,
the misses show no 50 Hz or 100 Hz rhythm. The two boards are the only USB devices on the host, each at
12 Mbit/s. AP_START refuses channel 13 (`0x102`).

The channels with the most misses carry the most neighbouring traffic (`tools/ldn/esp32_census.py`,
every frame a board receives on a channel, FCS failures included, 30 s per channel, two passes): channels
1 and 11 were busy 8.7 to 13% of the time with 44 to 107 good frames a second at -65 to -92 dBm,
channels 3, 5, 6, 7 and 9 were busy 0.3 to 1.7%, and the noise floor read -96 dBm on all of them. The
access point's own census (AP_START second flag byte `0x10`) shows no link to those frames: over 175
misses on channel 1, a neighbour frame was on the air in the 300 us, 1 ms and 3 ms before a miss 1.7,
4.6 and 13.1% of the time, against 1.5, 4.3 and 11.0% before a copy it heard. 85 to 91% of the misses
leave no trace at the access point, not even a frame failing its FCS; 6 to 13% arrive as a strong frame
failing it. An ESP32 station sends every retry behind an RTS, 128 us before the data frame.

The board misses most often the frame that follows its own transmission. A FireRed console sends
every data frame to the board behind RTS/CTS, although the board's beacon carries ERP byte 0 and no
HT operation element: the board answers the RTS with a CTS at 6 Mbit/s and the data follows it 60 us
later on a third board's clock, the CTS's 44 us plus SIFS. Over one trade on channel 1 the board
acknowledged 3705 of 4034 such data frames; the 329 it missed followed its CTS by the same 60 us.
On the bench, by a frame's place in its station's burst (bursts 40 ms apart, 54 Mbit/s, grouped by
receive time and ranked by sequence number, since a missed frame is only timed at its retry):

| channel | burst | 1st | 2nd | 3rd | 4th |
|---|---|---|---|---|---|
| 3 | 2 | 2.3% | 5.0% | | |
| 1 | 2 | 4.9% | 7.5% | | |
| 3 | 4 | 3.0% | 3.1% | 5.9% | 4.6% |

A frame after 40 ms of quiet is missed at a rate set by the channel; one that follows the access
point's own ACKs is missed 1.5 to 2 times as often.

The access point's own transmit power does not set it (AP_START's power byte, channel 3, bursts of
4, 120 s, two passes; the driver read the power back):

| access point power | 1st | 2nd | 3rd | 4th |
|---|---|---|---|---|
| 19.5 dBm (default) | 1.4, 1.0% | 3.6, 3.1% | 6.5, 5.8% | 3.3, 2.7% |
| 10 dBm | 0.7, 0.5% | 4.5, 3.2% | 6.5, 4.7% | 4.1, 3.6% |
| 3.5 dBm | 0.6, 0.6% | 3.1, 2.4% | 6.1, 7.0% | 3.0, 2.6% |

The third frame of a burst is the most missed in all six runs and in the run above.

The Wi-Fi driver of ESP-IDF v5.5.5 misses more than v6.1's. The same firmware built on v5.5.5 (its
`wpa_ap_join` takes nine arguments where v6.1 passes one struct; the esp32 `libphy.a` is
byte-identical in both, `libpp`'s `hal_mac_rx.o` too), both boards, channel 3, bursts of 4, 120 s,
two passes each, v6.1 run after v5.5.5:

| driver | 1st | 2nd | 3rd | 4th | all |
|---|---|---|---|---|---|
| v5.5.5 | 1.0, 1.1% | 3.2, 2.8% | 8.5, 8.7% | 7.3, 7.6% | 5.0, 5.0% |
| v6.1 | 1.0, 1.4% | 4.6, 4.6% | 6.9, 6.4% | 4.0, 4.1% | 4.1, 4.1% |

The two drivers write the same MAC and PHY registers for a station and an access point and share the
receive interrupt, buffer recycling and transmit-done code; v6.1 adds `wifi_assert` calls on the
per-frame paths. The gap between them is timing or spread. With `CONFIG_ESP_WIFI_EXTRA_IRAM_OPT=y` on
v6.1 the same bench missed 4.6 and 5.1% (0.9, 1.3 / 5.4, 7.2 / 5.4, 5.3 / 6.7, 6.6% by position): no
gain, and the most missed position moved.

An ESP32 station sends every retry behind RTS (`lmacConfMib` byte 42, retries before RTS, 0), with
its RTS threshold at 2346 (`lmacConfMib` +22); `esp_wifi_internal_get_rts` and
`esp_wifi_internal_set_rts` read and write both through a packed `{u16 threshold, u8 retries before
RTS, u8 long, u8 short}`.

With the station's RTS threshold at 0 (STA_JOIN flag 1), every data frame reaches the access point
SIFS after its CTS, as a FireRed console's does. On channel 3, bursts of 4, 120 s, alternated:

| station | missed | 1st | 2nd | 3rd | 4th |
|---|---|---|---|---|---|
| defaults | 4.6, 4.8% | 0.9, 2.0% | 3.4, 4.1% | 6.6, 5.6% | 7.5, 7.6% |
| RTS before every frame | 2.3, 2.1% | 0.8, 1.0% | 2.8, 2.7% | 3.6, 3.3% | 2.1, 1.5% |
| no RTS before a retry | 3.7, 4.9% | 0.8, 1.1% | 3.1, 6.3% | 5.2, 5.0% | 5.6, 7.3% |

The count leaves out a missed RTS, which the station sends again before the data. With the access
point's census on, over 90 s it heard 8527 of the station's RTS and 8216 data copies: 311 RTS
(3.6%) were answered and the data after the CTS was missed; the RTS gaps after a data frame bunch at
175 to 300 us, with a second group at 375 to 600 us, the timing of an RTS sent again. RTS before
every frame moves part of the misses onto the RTS; no gain overall is shown.

The driver retries in software: `lmacRetryTxFrame` (libpp `lmac.o`) sends each copy again through
`lmacTxFrame`, up to limits kept in `lmacConfMib` (short at +21, long at +20, both 32 by default);
`esp_wifi_internal_set_retry_counter(short, long)` sets them. With the access point sending 100
unicast 1200-byte frames a second to the station board (`--flood 100 --unicast`, 40 s), its frames
waited at most 18.6 and 23.9 ms from ETH_TX to TX-done with the limits at 32, and 23.4 ms and one
over 50 ms with 7 and 4 (second byte bit 3), which also left one frame unacknowledged in each run.
Two boards do not reproduce a 100 ms hold in that direction.

The one foreign access point beaconing on channel 11 during the bench (-79 dBm) beacons every 110 TU
(TSF gaps 112638 us). What the access point's radio is doing when it misses a frame is unknown.

The station board's sends slow down on a 102.4 ms (100 TU) cycle, a separate effect of the station
side. Frames that took over 3 ms from ETH_TX to TX-done (`--done-out`), folded by send time on the
station's clock (`tools/ldn/esp32_bench_fold.py FILE PERIOD_US`), bunch into two twentieths of
102.4 ms (29 to 43% against 2 to 12% elsewhere) with the beacon at 100 TU or 1000 TU, with the noise
check off or at 250, and fold flat at 250, 1000 and 1024 ms; the access point's misses do not follow
it. The measure includes a frame's wait behind the one before it, so a sender's own rhythm shows in a
fold: the FireRed trades' TX-dones fold unevenly at 25.6 ms. `tools/ldn/esp32_bench_drift.py`
measures both boards' clocks against the host (1.9 ppm apart over 600 s) and scans the fold period.

`tools/ldn/esp32_hold_air.py` lists what the sniffer saw during each hold. TX-dones complete out of
order and the board's receive times can swap two frames written 0.1 ms apart; `tools/ldn/esp32_hold.py
CAPTURE TRACE` pairs them by length and splits these stages.

Three traps in measuring this. A sniffer board's line backs up in a burst like any board's, so a
frame it reports reached the host up to a second after it was on the air; run it at 1500000
(`POKELDN_ESP32_BAUD`) and time delivery by the peer's acknowledgements, not by the sniffer. BENCH
filled each payload from the RNG, which held it under the line's rate so its queue never backed up;
it now fills once. And a flood the board sends as an access point is broadcast, which goes out at
1 Mbit/s and fills the air past about 90 frames a second.

The bytes a resync writes off stay written off: the board's count never includes them, so each later
CREDIT is read as that count plus the loss, and a CREDIT past what the loss allows shrinks it.
With CREDIT the same flood lost 0 of 5000 at 921600 and at 1500000, both counters 0. A board on
firmware without CREDIT never opens the window and the host writes unthrottled, as before.

A CREDIT jumps the board's outgoing queue and carries the count current when the writer reaches it;
at most one is queued. A Scarlet seat's opening fills the board-to-host line at 1500000 (150 KB/s of
RX_ETH); a CREDIT queued behind that traffic arrives about 0.5 s late.

A console seat loses commands the other way. A Scarlet seat at 1500000 with CREDIT lost about 210
of 1901 ETH_TX, all in its first 13 s, with `uart_fifo_ovf` 235, `uart_buffer_full` 5 and
`tx_eth_retried` 0: the hardware FIFO overflowing with the ring nearly empty. The driver drains the
FIFO when it holds 120 bytes (`UART_FULL_THRESH_DEFAULT`), 8 bytes short of full: 53 us at 1500000
and 87 us at 921600 before a late interrupt loses data. The firmware now sets the threshold to 32
(`uart_set_rx_full_threshold`), 640 us at 1500000; the next Scarlet seat at 1500000 lost 10 of
1691, with `uart_fifo_ovf` 0 and one `wire_rx_bad` frame, all in its first 11 s. The board alone does not reproduce the seat's
overflow: both directions flooded at once lost 2 of 3000 once and 0 in three more runs on the same
firmware.

Since the idle count and the CREDIT ahead of the queue, 26 seats (Scarlet as joiner and host, Sword
as host) handed the board 35514 ETH_TX and it counted 35514, every overflow counter 0.
`tools/ldn/esp32_cmd_loss.py TRACE` reconciles a trace: the ETH_TX written before each STATUS
request against the board's `tx_eth + tx_eth_failed`, and the bytes written since the HELLO against
the last CREDIT. The earlier seats that lost a few commands with no overflow counted (6 of 2333 at
921600, 10 of 1691 at 1500000, one of 836 on a Sword seat) lost them in the host's first burst after
the link came up, 112 and 306 ETH_TX in one second; their traces carry no byte count, and what lost
them is unmeasured.

The UART interrupt posts a `UART_DATA` event for every 32 bytes it moves into the ring, into the
same 64-entry queue as the overflow events (IDF 6.1 `uart.c:1369`, `1543`); at 1500000 the queue
fills in 14 ms and the interrupt drops what does not fit. The reader drained it once per turn, so an
overflow during a command held over 14 ms could go uncounted. A task above the reader on core 1
now drains it every tick, and STATUS carries `uart_frame_err` (framing, parity and break events) and
`uart_events_full` (ticks that found the queue full). An overrun with the window ignored
(`tools/ldn/esp32_bench.py --uplink 5000 --no-flow` at 1500000) loses 136.5 bytes per
`uart_fifo_ovf` on both the old reader and the new task, about one 128-byte FIFO each, and
`uart_events_full` stays 0: with the ring full the interrupt stops posting `UART_DATA`, so an
overrun never floods the queue.

`POKELDN_ESP32_BAUD` sets the rate `open_serial` switches to, 921600 by default. The ESP32 UART
runs to 5 Mbaud; the USB bridge sets the limit. `tools/ldn/esp32_bench.py --port PORT --bauds
921600,1500000,2000000,3000000` measures it with the board alone: BENCH streams random payloads,
and the tool prints the rate, the messages lost and the frames that failed their checksum at each
rate.

The ELEGOO board's bridge reports itself as "CP2102 USB to UART Bridge Controller" (idProduct
60000, bcdDevice 0x100) on macOS:

| baud | measured | messages | lost | bad checksums |
|---|---|---|---|---|
| 921600 | 91.7 KB/s | 1429 of 1400 bytes | 0 | 0 |
| 1000000 | 99.4 KB/s | 1429 of 1400 bytes | 0 | 0 |
| 1500000 | 149.1 KB/s | 4286 of 1400 bytes | 0 | 0 |
| 1500000 | 140.2 KB/s | 20000 of 100 bytes | 0 | 0 |
| 2000000, 3000000 | the board never answers HELLO at the new rate | | | |

`POKELDN_ESP32_BAUD=1500000` gives the board-to-host line 1.6 times the 921600 budget. A retail Legends
Z-A seat at 921600 with CREDIT flow control seated with no refused association, the host's first
message at 1.68 s (1.7 s at 1500000), 695 of 695 ETH_TX and a completed trade: the default rate
wins Z-A's seat race.

## The userspace stack

`pokeldn.ldn.userspace_ip` carries IPv4, UDP and ARP inside the host process for an interface
with no kernel behind it. A stack is registered under the interface name the caller passes
(`ldnclient` for the joiners, `ldn-tap` for an access point) while the port exists; `userspace_ip.lookup(name)` returns None
for a kernel interface, which is how every launcher picks its path.

- Addresses and neighbours come from the LDN library's `add_address` and `add_neighbor` calls.
  A source address seen on any received frame is learned as a neighbour.
- A destination ending in `.255` or equal to the broadcast address goes to `ff:ff:ff:ff:ff:ff`.
  A unicast destination with no neighbour entry sends an ARP request and drops the datagram.
- ARP requests for the stack's own address are answered.
- Outgoing datagrams larger than 1472 bytes are fragmented; incoming fragments are reassembled
  (five-second timeout). UDP checksums are computed.
- `udp_socket(port)` stands in for a UDP socket bound to the interface, `packet_socket()` for an
  `AF_PACKET` socket and delivers whole IPv4 Ethernet frames. Both have a real file descriptor
  (a pipe with one byte per queued datagram), so `select` and `trio.lowlevel.wait_readable` work.
- The board's frames reach the stack through trio tasks in the launcher's own trio loop. A
  launcher that waits for its socket with a blocking `select` inside that loop starves them: each
  datagram then waits out the full timeout. Wait with `trio.lowlevel.wait_readable` under
  `trio.move_on_after`. A Scarlet joiner blocking in `select(0.05)` handled one message per 50 ms
  and the console re-sent its records for 50 to 70 s.

## The board's LED and buttons

The ELEGOO ESP-32 Type-C board (CP2102, ESP32-D0WD-V3) carries an unbranded module: its shield reads
"ESP-32 / WIFI+BT SoC Inside / ISM2.4G 802.11/b/g/n" with FCC and CE marks, over a PCB antenna, with
no Espressif module name. The board carries two LEDs and two buttons:

| part | wired to | controllable |
|---|---|---|
| red LED | the 3.3 V rail | no, lit whenever the board has power |
| blue LED | GPIO2, lit when the pin is high | yes |
| EN button | the chip's reset | no |
| BOOT button | GPIO0 | yes: each press sends BUTTON (`0x8E`) and flashes the LED |

GPIO2 and GPIO0 are strapping pins: both must be low or floating at reset for the ROM to enter
download mode, so the firmware drives GPIO2 only after boot. The blue LED was found from the ROM
bootloader with no firmware change, by writing GPIO2's IO_MUX register (`0x3FF49040`, `MCU_SEL` 2),
its output select (`0x3FF44538` = `0x100`), `GPIO_ENABLE_W1TS` and `GPIO_OUT_W1TS` (bit 2); the
next reset returns the pin to its default.

The firmware drives the blue LED with LEDC PWM (13 bits, 5 kHz) from a priority-1 task on core 1
that recomputes it every 10 ms. Brightness is perceptual: the duty is the level to the power 2.2.
A change of look crossfades over 150 ms. The task reads counters the radio already keeps and adds
no work to the frame paths.

| pattern | id | default period | shape |
|---|---|---|---|
| auto | 0 | | the radio's own look, below |
| off, on | 1, 2 | | |
| breathe | 3 | 3000 ms | raised cosine |
| blink | 4 | 1000 ms | on for half the period, 80 ms eased edges |
| flash3 | 5 | 1000 ms | three flashes in the first 60 % of the period |
| ramp-up, ramp-down | 6, 7 | 1000 ms | once, cubic ease-in-out, then held |
| pulse | 8 | 1200 ms | a quick swell, a slow cubic fall |

The automatic look follows the board's mode:

| mode | look |
|---|---|
| boot | one pulse, 900 ms |
| idle | breathe, dim, 4 s |
| joining a console | fast blink, 250 ms |
| hosting, no station | breathe, brighter, 1.5 s |
| joined, or hosting a station | on, dim |
| sniffing | off |

On top of it every frame received or completed flickers the LED, retriggered once the previous
flicker has faded, so a flood shows as a shimmer. A failed join (LINK reasons `0xFFFF`, `0xFFFE`),
a refused key, a dropped board-to-host message or a lost host command plays flash3 for 1.5 s.
A launcher on the board marks a completed trade or Mystery Gift delivery with ramp-up to full
brightness over 800 ms, held until 3 s (`pokeldn.ldn.show_done`); the Sword gift host, a beacon
with no read-back, has no such moment.
`tools/ldn/esp32_led.py --port PORT PATTERN` sets a look; `--demo` shows each.

## Building and flashing

ESP-IDF v6.1 (tag `v6.1`, commit `fff9895c82d744c7237be8847347bdd1b07c6643`), target `esp32`.
Installing only the `esp32` target is enough (`install.sh esp32`); the same tree builds on
Linux and on macOS (Apple silicon) to the same image size.

    cd firmware/esp32
    idf.py build
    idf.py -p <port> flash

The console output is off (`CONFIG_ESP_CONSOLE_NONE`): UART0 is the host link. The image is
0x90650 bytes.

The release build runs with `CONFIG_ESP_CONSOLE_NONE`, which leaves UART0 unrouted: the
firmware assigns GPIO1 and GPIO3 itself (`uart_set_pin`), or the board boots and never answers.

## Running

`POKELDN_RADIO=esp32:<port>` in the environment puts every launcher's `ldn` calls on the board,
for example `POKELDN_RADIO=esp32:/dev/ttyUSB0`. `esp32:auto` takes the only USB serial port present
(`/dev/cu.usbserial-*`, `/dev/cu.SLAB_USBtoUART*`, `/dev/ttyUSB*`) and refuses to choose between
several, since opening a port resets its board.
The port is opened once per process with DTR and RTS released, since an edge on either resets
most boards. A CP2102 board on macOS resets on open regardless, so the host retries HELLO for
five seconds before switching to 921600. Under it the launchers skip every nl80211 step: `--phy auto` resolves to `esp32`,
no vif is deleted, no `iw`, `ip`, `nmcli` or `sysctl` runs, and a joiner's `--mac` becomes the
board station's address. A scan's 5 GHz channels (36 and up) are skipped, since the board is
2.4 GHz only; a console hosting on 5 GHz cannot be reached. The FRLG hosts inject no beacons of their own, since the board's
access point beacons itself. No root is needed on macOS.

`POKELDN_ESP32_TRACE=FILE` appends every serial message in both directions to FILE, one line
each: Unix time, `>` (host) or `<` (board), the type in hex, the payload in hex.

`tools/ldn/esp32_first_contact.py` is the first thing to run against a new board: `--flash`
writes the build with esptool, then HELLO, STATUS, an idle scan that counts LDN action frames
per channel and source, and with `--keys` the LDN library's own scan on the board, which
decrypts and lists each network.

`tests/test_esp32.py` runs the LDN library's host and station against each other on two
simulated boards (`pokeldn.ldn.esp32_sim`): scan, association, authentication, the join event, a
UDP frame from the station reaching the host's port, UDP both ways through two userspace stacks
including a fragmented datagram, `HostTransport` on a userspace stack, and the first-contact tool
decoding a simulated host.

## Measured on a board

An ELEGOO ESP32 board (ESP32-D0WD-V3 revision 3.1, CP2102 bridge, macOS, 921600 baud) has
completed a FireRed trade as the joiner against a retail Switch 2 hosting:

| stage | measurement |
|---|---|
| advertisements | 19 LDN action frames in 2 s on channel 11 from the console's BSSID, decoded to comm id `0x01006fa0233f8000`, 1 of 6 players |
| LDN join | scan to association in 1.9 s, joined at 2.5 s |
| Pia | connection established at 3.3 s, the GBA link accepted at 3.4 s |
| FRLG link loop | 38 to 42 'T' slots per second each way, the rate the rtw88 adapter reaches |
| trade | the console's Pokemon received intact (species 244, OT id `0xE5BBDF65`); cancel-to-leave, room exit and link close all completed |

These measurements are on the ELEGOO board's unbranded module (ESP32-D0WD-V3 chip), not an Espressif
WROOM module.

As an access point it has hosted a completed FireRed trade, a retail Switch 2 joining:

| stage | measurement |
|---|---|
| discovery | the console lists the network, so it accepts the zero-length hidden SSID, the rate order, capability `0x0431` and the WMM element |
| association | open authentication, then one association request 24 ms later, not retried |
| association request | capability `0x0431`, listen interval 10, the SSID as 32 hex characters, rates `02 04 0b 16 0c 12 18 24` and `30 48 60 6c`, power capability `00 14`, RSN capabilities `0x0000`, a WMM information element and the vendor element `00 22 aa 10 01 02` |
| LDN authentication | the console's request reaches `RX_ETH` 40 ms after `STA_JOINED`; the host answers it |
| the console's broadcasts | no DS bits, group key, first an ARP request for the host ([A station's broadcasts](ldn.md#a-stations-broadcasts)); the driver drops them, the firmware forwards them whole and the LDN library decrypts them |
| link | Pia session join, RTT, RFU handshake, trade room, party exchange |
| trade | the console's Pokemon received (species 113); both cancelled, left the room and closed the link |

Without the broadcast forwarding every host frame reaches the console and decrypts (a second
board sniffing verified each MIC), yet the console's ARP goes unanswered, it transmits nothing
more, deauthenticates with reason 3 after 7.3 s and shows "l'autre dresseur est indisponible".

As a station it has completed a Scarlet trade as the joiner, a retail Switch 2 hosting Link Trade:

| stage | measurement |
|---|---|
| seat | the first association attempt, 0.35 s from `STA_JOIN` to `LINK`; the rtw88 adapter needs 30 to 60 refused attempts against the same host phase |
| Pia | the session join answered at 0.93 s after the seat, the station update names the board's station |
| announcement | 7.7 s and 5.8 s after the seat once the joiner waits in trio (1.7 s on the rtw88 adapter); 52 s and 72 s while it blocked in `select`, the console re-sending its `0x81` port 0 records 1 to 24 and session update 1 |
| trade | the joiner's offer taken, the console's record received, then host migration to the joiner as on the adapter; four trades in three runs |
| serial | the console's first burst of 46 records (about 50 KB) saturates board-to-host at 92 KB/s; 337 messages dropped in the first 5 s of one seat, none after |

As an access point it has hosted a completed Scarlet trade, the console joining from its Link
Trade search: join request, the console's type-3 join answered with the type 9 accept, key `0x80`
opened and the host's offer sent 11.4 s after the join. In one of two runs the console
acknowledged the announcement and never sent its port 2 join; re-entering the search cleared it.

As a station it has completed a Legends Z-A trade as the joiner: seated on the first scan, the
console's selection record (`0100`) at 1.75 s, the offer at 11.9 s and the close (`0104`, `0200`)
at 15 s.

As an access point it has delivered Wonder Cards to FireRed and LeafGreen and two Sword Mystery Gifts.

As an access point it has hosted a completed Let's Go trade: the console joined the mesh, both
commits went through, its kind 4 record came back and it left cleanly, with no failed transmit
and no serial drop.

As a station it has completed a Let's Go trade as the joiner.

As an access point it has hosted a completed Legends Arceus trade through the four host
phases (3, 6, 11, 14).

As a station it has completed a Sword trade as the client: the busiest-channel scan picked
channel 6, the first association held, the party snapshots crossed and the confirmation ladder
finished 34 s after the seat. The console's late-ack resends reach the client out of order on the
board ([Sword session](swsh_session.md)).

As a station it has completed a Brilliant Diamond Union Room trade: accepted into the mesh on the
first request, the character walked in, the trade ran to `NetDataReturnSelectData` and the console
saved. A killed client leaves its station in the Union Room; the next seat with the same MAC is
never answered until the player leaves and re-enters the room.

As an access point it has hosted a Brilliant Diamond Union Room that a retail Shining Pearl
entered: the handshake finished 0.46 s after the association, and a trade ran to
`NetDataReturnSelectData` and the console's save ([Hosting](bdsp_session.md#hosting)).

`tools/ldn/esp32_sniff.py` makes a second board an air sniffer: `SNIFF` (`0x0A`, u8 channel and
6 MAC) forwards every management and data frame to or from that MAC, whole, as `RX_MGMT`.

## Unresolved

- The softAP negotiates WMM, which a Switch host does not; a trade completes with it and without
  it. `AP_FLAG_NO_QOS` (`POKELDN_ESP32_AP_FLAGS=2`) clears the station's QoS flag after
  association: on a retail Legends Z-A trade the board sent 446 plain data frames and no QoS data,
  while the console kept sending QoS data (113 frames), since the association still negotiated
  WMM. Retail Legends Arceus, Let's Go and LeafGreen trades also completed with it. Two Legends
  Z-A host trades on one console, channel and link code, sniffed, one without QoS data and one
  with: 11.9% then 1.3% of the board's frames retried, and 11.5% then 1.3% of the console's, whose
  frames are QoS data in both. The retry rate follows the air at the time in both directions; no
  measurement attributes a difference to the setting.
- A sniffer board's counts of another board's frames undercount while the sniffer's own serial
  link is saturated; they are not evidence of loss on the air.
- The access point board misses 1 to 22% of a station's OFDM first copies at -20 to -48 dBm, evenly in
  time, and misses ACKs during a FireRed hold; DSSS frames almost never; the share varies by channel
  (channel 3 lowest, channel 1 highest here) and is highest for a frame that follows the board's own
  CTS or ACK by SIFS; what in the board's receive path causes it is unknown. Ruled out: the beacon interval,
  promiscuous receive, the driver's noise-floor check, the board unit, the CPU clock (160 or
  240 MHz), the static receive buffer count (16 or 25), receiver overload, the signal margin, the
  Switch's Bluetooth, a 50 or 100 Hz source.
- Whether an Espressif ESP32-WROOM-32E module misses fewer frames as an access point than the
  unbranded module on the ELEGOO board is unmeasured.
- easyworld reports that a classic ESP32 must be the ESP32-WROOM-32E module and that the older
  ESP32-WROOM-32 does not trade reliably.

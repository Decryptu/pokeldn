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
| `0x04` STA_JOIN | host | u8 channel, 6 BSSID, 32 SSID (the LDN SSID's hex text), 16 key, 6 station MAC (zero = random) |
| `0x05` STOP | host | none; back to idle, keys cleared |
| `0x06` AP_START | host | u8 channel, 6 BSSID, 32 SSID, 16 key, u8 max stations, u8 flags: 1 the stock association and 4-way handshake, 2 no QoS for the station, 4 no 40-byte copy of each station data frame |
| `0x07` AP_KICK | host | 6 MAC, u16 reason; deauthenticates |
| `0x08` ETH_TX | host | an Ethernet frame; the driver encrypts it with the station's or the group key. A full driver queue (`ESP_ERR_NO_MEM`) is retried every 1 ms for up to 100 ms before the frame counts as failed; a frame to a station that has left fails at once with `0x3015` (`ESP_ERR_WIFI_NOT_ASSOC`) |
| `0x09` RAW_TX | host | an 802.11 frame without FCS (`esp_wifi_80211_tx`); used for advertisements |
| `0x0A` SNIFF | host | u8 channel, 6 MAC; every management and data frame to or from it, whole, as RX_SNIFF |
| `0x0B` STATUS | host | none; answered by STATUS |
| `0x0C` BENCH | host | u32 bytes, u16 message size (8 to 1600); RESULT, then BENCH messages as fast as the UART takes them |
| `0x81` INFO | board | u8 protocol version (1), 6 station MAC, 6 AP MAC, u8 chip revision, text |
| `0x82` RESULT | board | u8 command, i32 `esp_err_t` |
| `0x83` LOG | board | text |
| `0x84` RX_MGMT | board | u8 channel, i8 RSSI, a frame without FCS: an LDN action frame; while hosting also a management frame to our BSSID, the first 40 bytes of a data frame to it, and a station's no-DS broadcast whole |
| `0x85` RX_ETH | board | an Ethernet frame the driver decrypted |
| `0x86` LINK | board | u8 up, u16 reason, 6 MAC; reason `0xFFFF` no association in 15 s, `0xFFFE` keys refused |
| `0x87` STA_JOINED | board | 6 MAC, u8 AID, i8 key install result, u8 port opened |
| `0x88` STA_LEFT | board | 6 MAC, u16 reason |
| `0x89` STATUS | board | text counters, including the driver's TX-done `tx_acked` and `tx_unacked`, `tx_eth_retried` (ETH_TX calls that found the driver's queue full) and `wire_dropped` (board-to-host messages dropped: 384 queued, or free heap under 64 KB), `wire_rx_bad` (host commands that failed COBS or their CRC), `uart_fifo_ovf` and `uart_buffer_full` (UART hardware FIFO and driver ring overflows) and their sum `uart_overflow`; sent unasked every 2 s while hosting, and polled every 5 s by a host that writes a trace |
| `0x8A` BENCH | board | u32 sequence and random bytes; the last carries sequence `0xFFFFFFFF` and the u32 microseconds the board spent |
| `0x8C` RX_SNIFF | board | u8 channel, i8 RSSI, u8 `sig_mode` (0 legacy, 1 HT), u8 legacy rate code (`wifi_phy_rate_t`), u8 HT MCS with bit 7 set for 40 MHz, a frame without FCS |
| `0x8D` TX_DONE | board | the driver's TX-done of one frame, as a station or an access point: u32 board time in µs, u32 µs since the ETH_TX it completes (all ones for a frame that is not one), u8 acked by the peer's radio, u8 interface, u16 length, then the frame's first 24 bytes (its 802.11 header). STATUS sums the matched ones in `tx_queued_max_us`, `tx_queued_total_us`, `tx_queued_n` and `tx_queued_pending` |
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

`POKELDN_ESP32_BAUD=1500000` gives the board-to-host line 1.6 times the 921600 budget.

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

The ESP32-WROOM-32E module is built on the ESP32-D0WD-V3.

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

As an access point it has delivered a FireRed Wonder Card and a Sword Mystery Gift.

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

- The softAP negotiates WMM, which a Switch host does not; a trade completes with it.
  `AP_FLAG_NO_QOS` (`POKELDN_ESP32_AP_FLAGS=2`) clears the station's QoS flag after association.
- What loses the last few commands at the start of a seat, with neither overflow counter moving.
  The overflow events travel a 64-entry queue the reader drains only between commands, so a
  reader held in `sta_join` can miss them. A trace records every CREDIT (`< 8b`) and each host
  resync (`! 8b`); bytes the board never read show there.
- A sniffer board's counts of another board's frames undercount while the sniffer's own serial
  link is saturated; they are not evidence of loss on the air.
- Serial latency at 921600 baud against the Z-A seat race.
- easyworld reports that a classic ESP32 must be the ESP32-WROOM-32E module and that the older
  ESP32-WROOM-32 does not trade reliably.

# Scarlet/Violet retail raid guest reverse engineering

This note preserves the protocol evidence used to make an ESP32-backed PokéLDN
station join a retail Scarlet/Violet Tera Raid. It consolidates the former
runtime procedure and legacy capture notes. User-facing operation is documented
in [`../../sv_raid_guest.md`](../../sv_raid_guest.md).

## Confirmed result and boundary

The synthetic guest can join the local network, establish Pia, appear as
POKELDN, announce a selected party Pokémon, become ready, acknowledge Start Raid
Battle, and let the retail host enter battle. It intentionally disconnects at
the stable `0x80349301` battle transition; a complete guest battle runtime was
not implemented.

The final path does not replay a donor's network or Session identity. It uses:

- a fresh local-unicast Wi-Fi MAC;
- the Pia constant ID derived from that MAC;
- anonymous/local player ID `00000000000000010000000000000000`;
- POKELDN in the Pia and application identity names;
- the standard 44-record Scarlet/Violet application identity already used by
  trades; and
- generated raid-lobby, selected-Pokémon, Ready, and Start messages.

Live validation covered a generated identity in lobby 4216 and the shared
application identity in lobby 2417. In both cases the retail game displayed
POKELDN and reached the expected battle transition.

## Derived protocol sequence

The successful capture series established this ordering. Timings are validated
working values, not proven lower bounds.

| Stage | Guest action and evidence |
| --- | --- |
| LDN seat | Join the discovered scene-7 network with a fresh local-unicast MAC. |
| Net setup | Respond to Net connection status with `0x12`; outer flags `0x11`. |
| Pia Session | Send the anonymous player ID and configured name. Delay acknowledgment of the first Session update until the retail retry. |
| Clone clock | Send 18 bytes with byte 9 equal to 1 and every other byte zero. |
| Streams | Send the bulk acknowledgments and open guest streams on `0x81` ports 0 and 4. |
| Channels | Send the four-key base table, join port 2 at +0.24 seconds, then send the separate `0x8033`/`0x8034` key update at +0.79 seconds. |
| Identity | Send the shared SV application records on `0x81:1`, starting about 0.44 seconds after the accepted Session update. |
| Lobby | Send generated `0x80332d01` and `0x80332e01` messages. Identity alone does not make the guest visible. |
| Ready | After the configured lobby delay, send a type-`0x2d` message with state `0x01`. |
| Start | On host state `0x0c`, send guest state `0x0d` once. This permits battle entry. |
| Handoff | Maintain Pia, RTT, and reliable streams until host message `0x80349301`, then disconnect. |

Several early timing details were changed together, so their individual
necessity was not isolated. Lobby presence, Ready, and Start were established
with controlled UI actions and sequential tests.

## Application state messages

The observed `0x80332d01` plaintext is 42 bytes:

- bytes 4–7 are a little-endian application counter;
- bytes 34–37 are a little-endian state;
- Ready uses state `0x01`;
- the host's Start request uses state `0x0c`; and
- the guest's Start acknowledgment uses state `0x0d`.

The application counter advances independently of reliable sequence numbering.
Retransmissions retain their original counter. An earlier experiment incorrectly
treated state `0x0d` as Ready: the host acknowledged it but did not mark the
guest ready. Replying with `0x0d` only after the host sent `0x0c` enabled
battle entry.

The `0x80332e01` message carries an 18-byte application header followed by the
encrypted 344-byte party PK9. `pokeldn.sv.raid.JoinerRaidStage` now generates
the complete message around the selected Pokémon rather than replaying it.

## Session identity and address mapping

The source capture used guest MAC `48:f1:eb:c7:b3:51`, constant ID
`ebb351c7f1480000`, and player ID
`100096e8aa857fe0be9fe53f544feab2`. These values are evidence only and are no
longer replayed.

For the observed Pia representation, the inverse mapping is:

`mac = [constant[5], constant[4], constant[0], constant[3], constant[1], constant[2]]`

The serialized station-ID byte order must not be mistaken for the actual Wi-Fi
MAC. The earlier `48:f1:c7:51:b3:eb` interpretation was incorrect.

## Passive capture pitfalls

The ESP32 sniffer filters on receiver or transmitter MAC. Filtering on the host
omits guest broadcasts because their receiver is the broadcast address and
their transmitter is the guest. A larger frame limit does not correct that
omission. Likewise, `ff:ff:ff:ff:ff:ff` selects header-only census mode in the
capture firmware; it is not a full-payload wildcard.

With one board, the reliable method was:

1. Locate the host advertisement and channel using the host MAC.
2. Restart capture on that channel with the guest MAC before the guest joins,
   appending to the same trace.
3. Separate Join, Ready, and Start actions so packet semantics can be assigned
   from controlled transitions.
4. Decode with `tools/ldn/esp32_trace_decode.py`, using the advertisement from
   the same SSID to derive the session keys.

Guest filtering captures guest broadcasts and host-to-guest unicast but omits
host broadcasts, so it is not a complete simultaneous two-way capture. Traces
from unrelated lobbies must not be combined: the decoder selects a decodable
advertisement, and the wrong SSID produces misleading results.

The capture board used firmware 1.4.0 built with ESP-IDF v6.1. Its
`WIRE_MAX_PAYLOAD` was raised from 1600 to 2400, and the sniff limit was set to
`WIRE_MAX_PAYLOAD - 5` to account for the PHY header.

## Bootstrap acquisition

The guest workflow originally existed to acquire a complete retail
`0x80332f01` bootstrap. The successful retry20 capture contained the message
across reliable sequences 14–15: a 1,395-byte uncompressed fragment followed by
a compressed fragment inflating to 246 bytes, for 1,641 serialized bytes.

Later Ghidra work established that `0x0AA0` is the plaintext record size inside
the application's raw LZ4 block, not the compressed application length. After
LZ4 decoding, `RaidPoint_10_01_07` begins at raw offset `0x6B8`.

Older captures also contain `0x32016e00`, `0x32017300`, and `0x80349301`
before battle commands. The first two were not required to acquire the
RaidPoint bootstrap. The last became the validated handoff marker used by the
product joiner.

The RaidPoint layout and generator findings continue in
[`SV_RAIDPOINT_REVERSE_ENGINEERING.md`](SV_RAIDPOINT_REVERSE_ENGINEERING.md).

# ESP32 joining a retail Tera Raid: working capture procedure

Recorded 2026-10-05, on branch `sv-raid-seed-generation`.

This is the reverse direction from our main ESP32-host project: a retail Switch
hosts and the ESP32 joins as a synthetic guest. It is useful for acquiring the
host's raid bootstrap without needing a fully functional guest battle runtime.

## Confirmed result and limit

The ESP32 can join the local network, establish Pia, exchange identities, appear
as POKELDN, mark itself ready, acknowledge Start Raid Battle, and cause the retail
host to enter battle and transmit the complete RaidPoint bootstrap.

The latest run stalls before move selection. This is not a complete playable
guest, and we have not implemented the remaining battle synchronization. No
victory, catch, or reward-screen behavior is established for this guest mode.

The workflow was recaptured on 2026-10-07. Lobby 5352 supplied the complete
46-record identity, initial lobby records and controlled Ready transition;
lobby 6071 supplied the Start acknowledgment and successful battle entry. The
minimal runtime material is tracked as `pokeldn/sv/data/raid_guest.json`.

## Launch procedure

Run from `/home/ismail/Documents/GitHub/pokeldn/bin`, with the project `.venv` and
the ESP32 connected at `/dev/ttyACM0`. Only one process may own the radio.
Stop a previous fake host, fake guest, or passive sniffer before launching.
The retail guest Switch must be disconnected: this experiment reuses its MAC
and recorded player identity.

Open a local/offline raid lobby on the retail host, then run:

```bash
POKELDN_RADIO=esp32:/dev/ttyACM0 ./.venv/bin/python sv_join.py \
  --keys /home/ismail/Downloads/switchkeys.io-v22.5.0/prod.keys \
  --scene-id 7 --raid-guest-replay \
  --raid-guest-ready-delay 2 \
  --seconds 900 --hold 240 --max-seats 1 \
  --capture tera_raid_guest_next_test.jsonl
```

Choose a fresh output filename for each run. These durations mean up to 900
seconds scanning and 240 seconds holding the joined session, not an unlimited
capture. Serial-device access must be permitted by the environment. The
identity and lobby fixture is bundled automatically; `--record-trace` and
`--raid-lobby-trace` are now experimental overrides rather than prerequisites.

The script scans channels 1, 6, and 11 and discovers a scene-7 network; this
command does **not** take or validate the four-digit link code. The code is an
operator reference in our tests, not a target selector. Check the discovered
host and SSID in the log, especially if more than one raid is nearby.

Wait for POKELDN to appear and show ready on the retail host screen. Then choose
Start Raid Battle. Network `SEATED` and reliable ACKs alone do not establish
that the game accepted a trainer or a state transition. The screen is a separate
validation step.

## Working protocol sequence

The implementation is in `sv_join.py`. Its replay preset supplies the following
sequence. Timings are the working experimental configuration, not proven
minimum delays or universal protocol requirements.

| Stage | Guest action / evidence |
| --- | --- |
| LDN seat | Join the discovered retail scene-7 network using the captured guest MAC. |
| Net setup | Respond to Net connection status with 0x12; outer flags 0x11. |
| Pia Session | Send the captured player identity in the Session join request. Hold the first Session update, then ACK a repeated update at least one second later; the observed retail repeat was about two seconds later. |
| Clone clock | Send 18 bytes with byte 9 equal to 1; all other bytes zero. |
| Stream opening | Send the eleven bulk ACKs and guest stream opens on 0x81 ports 0 and 4. These are needed in raid mode too. |
| Game channels | Send the four-key base table on 0x7c:1, port-2 join at +0.24 s, and the separate 0x8033/0x8034 key update at +0.79 s relative to the base table. Channel ACK delay is 0.25 s. |
| Identity | Send all 46 captured records on 0x81:1, starting about 0.44 s after the accepted Session update. Patch record 1's trainer name to POKELDN. Retransmit unacknowledged records. |
| Lobby presence | Send the two captured 0x80:0 application records below after identity transmission and channel setup. Identity alone did not make the guest visible. |
| Ready | Two seconds after lobby replay, send another type-0x2d message with state 0x01. |
| Start acknowledgment | On a received host type-0x2d state 0x0c, send guest state 0x0d once. This enabled retail battle entry. |
| Bootstrap | Keep Pia/RTT/reliable maintenance running and capture the host's application fragments. |

We changed several early timing and identity details together. Their individual
necessity has not been isolated. The later presence, Ready, and Start experiments
have stronger direct evidence from sequential tests and controlled UI actions.

### Guest identity and address mapping

- Actual guest Wi-Fi MAC: `48:f1:eb:c7:b3:51`.
- Its Pia constant ID: `ebb351c7f1480000`.
- Captured player ID: `100096e8aa857fe0be9fe53f544feab2`.
- Tested host MAC: `a4:38:cc:eb:6d:5a`.

The inverse constant-ID mapping is
`mac = [constant[5], constant[4], constant[0], constant[3], constant[1], constant[2]]`.
Do not confuse the game's serialized station-id byte order with the actual
Wi-Fi MAC. The previous `48:f1:c7:51:b3:eb` setting was incorrect.

### Application records and state transitions

The first two guest messages on 0x80:0 are:

| Reliable seq | Application prefix | Reliable flags | Payload |
| --- | --- | --- | --- |
| 1 | 80332d01 after inflation | 0x1f | 35 compressed bytes, 42 plaintext bytes; initial state 0x18 |
| 2 | 80332e01 | 0x07 | 362 uncompressed bytes of captured data |
| 3 | 80332d01 after inflation | 0x17 | Ready state 0x01 |
| 4 | 80332d01 after inflation | 0x17 | Start acknowledgment state 0x0d, triggered by host state 0x0c |

Offsets are relative to the decompressed application payload, not the Pia or
reliable headers: bytes 4–7 carry the little-endian application counter;
bytes 34–37 carry the little-endian state in the observed 42-byte 0x2d layout.
The counter advances after the preceding application message. It is independent
of reliable sequence numbering. Retransmissions keep their original counters.

The controlled Ready capture is `tera_raid_retail_ready_6534_ch11.trace` and its
decoded JSONL: guest seq 1 has state 0x18, seq 2 supplies the captured 0x2e data,
then the user's explicit guest Ready press produces seq 3 with state 0x01.
Only the application counter and state byte differ from the initial 0x2d message.

Earlier we mistook an older state-0x0d message for Ready. The host acknowledged
receipt but did not mark the guest ready. In retry19, pressing Start on the host
produced state 0x0c and stalled. In retry20, replying 0x0d permitted battle entry.
These observations establish the behavior tested here; broader state-machine
semantics and other state values remain undecoded.

The 0x2e payload and identity are still capture-backed. This is not arbitrary
guest-Pokémon generation. Unknown session-dependent fields are retained, and
success with this recorded identity does not establish portability to all raids.

## Passive capture pitfalls and correct workflow

The firmware sniffer matches only the receiver or transmitter MAC. Filtering on
the host omits guest broadcasts, because those frames' receiver is broadcast and
their transmitter is the guest. Increasing the frame limit does not fix this.
The earlier nine-message guest opening was an incomplete view, not proof that
identity records or stream opens were absent.

Also, `--mac ff:ff:ff:ff:ff:ff` enables header-only census mode in this firmware;
it is **not** a wildcard that saves all full payloads.

With one board, use this sequence:

1. Open the host lobby. Passively locate its channel and capture its advertisement
   using the host MAC. Do not assume channel 1: the controlled Ready run used 11.
2. Stop that sniffer and restart on the same channel with the guest MAC, appending
   to the same trace file. The trace writer appends. Keep the same lobby/SSID.
3. Join the retail guest only after the guest-MAC capture is active.
4. Separate UI actions with user signals: joined, Ready, Start. This avoids
   assigning a semantic meaning to a packet just because it occurred near battle.
5. Decode with `../tools/ldn/esp32_trace_decode.py`, using the host advertisement
   to derive that session's keys.

Guest filtering captures guest broadcasts and host-to-guest unicast, but omits
host broadcasts. It is not a complete simultaneous two-way broadcast capture.
Do not combine unrelated lobbies: the decoder chooses the first decodable
advertisement, so a trace spanning multiple SSIDs needs explicit separation.

The board used firmware 1.4.0 built with ESP-IDF v6.1, with WIRE_MAX_PAYLOAD
increased from 1600 to 2400 and the sniff-frame limit set to WIRE_MAX_PAYLOAD - 5
to allow for the PHY header. The firmware edits are in `wire.h` and `radio.c`.

## Bootstrap validation and next work

Use `sv_reward_wire.py CAPTURE.jsonl` to locate the 80332f01 message by content,
not a fixed reliable sequence number. The extractor verifies contiguous
START-to-END fragments and excludes following application messages.

Retry20 contains this message in seq 14–15: 1,395 uncompressed bytes followed by
a compressed fragment inflating to 246 bytes, total 1,641 serialized bytes.
`RaidPoint_10_01_07` is at offset 0x57e and the reward marker at 0x5cb. This is a
complete transmitted bootstrap despite the subsequent stall. The header field
0x0aa0 is not the serialized byte count; its interpretation is unresolved.

Older retail-guest captures contain further messages with prefixes 32016e00,
32017300, and 80349301 before battle commands. Their triggering conditions and
session-specific fields must be established before adding responses. They are
not needed just to acquire the RaidPoint bootstrap. Main reward analysis can
continue independently; see `REWARD_SERIALIZATION_40CE99D3_ANALYSIS.md`.

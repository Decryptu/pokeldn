---
title: Join a retail Scarlet/Violet Tera Raid
parent: Scarlet and Violet
nav_order: 3
---
# Join a retail Tera Raid

The **Tera Raid (Join)** tool makes the ESP32 join a raid hosted by a retail
Scarlet or Violet console. POKELDN appears in the lobby, becomes ready, and
acknowledges the host starting the battle. At the stable battle transition it
disconnects, leaving its selected Pokemon in the raid as an AI-controlled bot.
It does not select moves, finish the battle, catch the Pokemon, or receive
rewards.

## Run it

1. Connect a board with current pokeldn firmware and configure `prod.keys` in
   Settings.
2. On the retail host, open a local/offline Tera Raid, choose **Challenge as a
   group**, and remain on the participant-waiting screen.
3. Choose the legal **Raid Pokemon** POKELDN should bring. The Pokemon builder
   provides the same species, form, moves, ability, item, stats, and Tera-type
   controls used by trades. It is required because the lobby record is generated
   from this Pokémon rather than copied from a capture.
4. Start **Tera Raid (Join)** in pokeldn.
5. Confirm POKELDN appears and becomes ready, then choose **Start Raid Battle**
   on the host.
6. After the battle begins, confirm POKELDN has disconnected and its Pokemon
   remains in the party as a bot.

The tool scans channels 1, 6, and 11 for scene 7. Scarlet/Violet's four-digit
raid code is not available as a radio-level selector, so do not run it near a
different local raid lobby that it could join instead.

## Command line

The tracked fixture is selected automatically; capture paths are not required:

```bash
POKELDN_RADIO=esp32:/dev/ttyACM0 ./.venv/bin/python bin/sv_join.py \
  --scene-id 7 --raid-guest --raid-guest-ready-delay 2 \
  --raid-pokemon path/to/raid-bot.pk9 \
  --seconds 900 --hold 240 --max-seats 1
```

`--raid-guest` generates a fresh local-unicast MAC and uses Pia's validated
anonymous/local player ID. The GUI fixes the LDN node, Session player, and game
identity names to `POKELDN`. `pokeldn.sv.raid.JoinerRaidStage` constructs
the initial state, selected-Pokémon announcement, Ready transition, and Start
acknowledgment. The 46-record game identity and established Session/channel
timing remain shared transport fixtures. `--record-trace` and
`--raid-lobby-trace` remain available only for explicit protocol experiments.

`--raid-pokemon` accepts a party `.pk9`. The shared PKHeX service validates it
and refreshes its party stats, then the joiner generates the complete
`0x80332e01` message around its encrypted 344-byte body. Application counters,
envelopes, compression, reliable flags, Ready, and Start ACK are generated as
well.

## Limitations

- The 46-record game identity remains capture-backed and validated against game
  version 4.0.0, matching the identity layer used by trades. The raid lobby
  application sequence itself is generated.
- `SEATED` in the log proves only the network join. The retail host screen must
  show POKELDN to validate lobby presence.

The capture and protocol notes used to derive the compact fixture are retained
in `bin/ESP32_RETAIL_RAID_GUEST.md`.

---
title: Scarlet/Violet Tera Raid hosting
parent: Scarlet and Violet
nav_order: 2
---
# Scarlet/Violet Tera Raid hosting

The Tera Raid (Host) tool lets a retail Scarlet or Violet console join a raid
hosted through the ESP32. The raid Pokemon and the reward list are configured
separately. POKELDN's own Pokemon can also be selected with the same legal
Pokemon builder used by trades.

## Configure the raid

Choose **POKELDN's Pokemon** to control the fake host's battler. PKHeX builds
and validates its complete party record, including its moves, ability, held
item, stats, current HP, and Tera type. This is required because the fully
generated bootstrap needs a coherent host participant record.

Enter an eight-digit hexadecimal Raid Pokemon seed. It determines the boss
species, form, Tera type, stats, ability and moves. The default `000F34C3`
produces the Pawniard used while validating the host.

Choose the game version, region, story progress, and standard or black-crystal
table. The seed field immediately previews the generated species, star level,
battle level, Tera type, IVs and calculated stats in that context. **Find a
raid** treats the host context as a quick template, but each game, region,
progress, and content dimension can be broadened to **Any**. It scans a chosen
32-bit seed interval and filters by species name or Pokédex ID, star level,
Tera type, shininess, nature, gender, ability ID, and exact or inclusive IV
ranges. Results can be ranked by estimated physical bulk, special bulk,
overall bulk, offense, or total stats. Pick **Use** to copy both the seed and
the result's complete context back into the host form.

When no species is selected, the result list keeps only the best candidate for
each species instead of filling the list with duplicate species. When a
species is selected, multiple seeds remain visible so their IVs and Tera types
can be compared. **Results to show** controls the list size from 1 through 100.

Crystal type defaults to **Standard or black**, so opening the browser does not
silently restrict results to the host form's previously selected crystal type.

Search runs in the background, reports progress, and can be cancelled. To
keep broad searches responsive, one run may cover at most one million
seed/context combinations.

Difficulty rankings are estimates, not a complete battle simulation: moves,
abilities, type matchups and the Pokemon brought by the player can change which
encounter is easiest in practice.

The seed's normal rewards are used when the reward list is empty. To override
them, add between one and sixteen rewards. Search for each item by name and
enter a quantity from 1 through 999. Rows remain separate and appear in the
selected order, including duplicate items.

## Join from the console

1. Choose the Pokemon POKELDN should bring. It remains as an AI-controlled bot
   after the fake host disconnects.
2. Choose a raid Pokemon from its seed and displayed stats. Pick one your team
   can defeat.
3. Optionally replace the seed rewards with an exact custom list.
4. Plug in a board with current pokeldn firmware, add your `prod.keys` in
   Settings, and start the Tera Raid (Host) session.
5. On the console, open the Poké Portal and join an offline Tera Raid Battle.
6. Enter the Link Code `4970`.
7. A communication warning may appear while entering the raid. This is
   expected; dismiss it and continue.
8. Defeat the raid Pokemon to receive the configured rewards. Catching the
   Pokemon is optional.

The host automatically generates application sequences 1 through 20, including
the `0xAA0` RaidPoint bootstrap, and advances the loading transitions from the
client's observed state. Reward-profile files, donor captures and replay timing
switches are not exposed in the app.

## Current scope

The encounter, boss PK9, RaidPoint, and default rewards are generated from the
selected seed using the bundled retail encounter tables. An optional custom
reward list replaces the seed rewards with consecutive neutral reward rows;
the unused reward region is zeroed before compression. No captured RaidPoint
plaintext is retained. POKELDN's selected Pokemon is written into both its
`0x80332e01` lobby announcement and player slot 0 of the final `0x80332f01`
bootstrap, and the joining console's lobby Pokemon is installed in slot 1.

Generated RaidPoints include the encounter-specific retail action/shield
profile for all bundled standard one- through five-star and black six-star
encounters in Paldea, Kitakami, and Blueberry. Poké Portal News event raids
remain unsupported because their active BCAT enemy and reward tables are
separate context not determined by the seed.

The generated path no longer loads `tera_raid_retail_victory_full.jsonl`.
`pokeldn.sv.raid.RaidStage` constructs the lobby descriptor, host Pokémon,
countdown/state records, bootstrap fragments, loading transitions, and the
sequence-20 battle handoff. Pia identity and Session/Net/channel maintenance
remain the shared transport layer, matching the separation used by generated
trades.

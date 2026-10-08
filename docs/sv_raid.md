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
item, stats, current HP, and Tera type. Leaving this empty retains the captured
replay behavior.

Enter an eight-digit hexadecimal Raid Pokemon seed. It determines the boss
species, form, Tera type, stats, ability and moves. The default `000F34C3`
produces the Pawniard used while validating the host.

The seed field immediately previews the generated species, star level, battle
level, Tera type, IVs and calculated stats. **Find a raid** scans a chosen
32-bit seed interval and ranks encounters by estimated physical bulk, special
bulk, overall bulk, offense or total stats. Its star filter can restrict the
results to one through four stars, and its shininess filter can find only shiny
encounters. Pick **Use** on a result to copy that seed back into the host form.

Difficulty rankings are estimates, not a complete battle simulation: moves,
abilities, type matchups and the Pokemon brought by the player can change which
encounter is easiest in practice. Search currently uses the same validated
Violet, Paldea, 4-star story-progress, standard-raid context as the host.

Add between one and sixteen rewards. Search for each item by name and enter a
quantity from 1 through 999. Rows remain separate and appear in the selected
order, including duplicate items.

## Join from the console

1. Choose the Pokemon POKELDN should bring. It remains as an AI-controlled bot
   after the fake host disconnects.
2. Choose a raid Pokemon from its seed and displayed stats. Pick one your team
   can defeat.
3. Add the rewards you want to receive after the battle.
4. Plug in a board with current pokeldn firmware, add your `prod.keys` in
   Settings, and start the Tera Raid (Host) session.
5. On the console, open the Poké Portal and join an offline Tera Raid Battle.
6. Enter the Link Code `4970`.
7. A communication warning may appear while entering the raid. This is
   expected; dismiss it and continue.
8. Defeat the raid Pokemon to receive the configured rewards. Catching the
   Pokemon is optional.

The host automatically uses client-gated startup and the validated battle
handoff. Reward-profile files, donor captures and replay timing switches are
not exposed in the app.

## Current scope

The encounter is generated from the selected seed using the validated 4-star
Paldea context. Rewards use the Violet 4.0.0 Avalugg bootstrap layout, but the
boss shown and caught comes from the independently selected Raid Pokemon seed.
Item IDs and quantities are encoded into the plaintext raid bootstrap before
it is compressed and transmitted. POKELDN's selected Pokemon is written into
both its `0x80332e01` lobby announcement and player slot 0 of the final
`0x80332f01` bootstrap; guest slots, the boss slot, and RaidPoint rewards are
left unchanged.

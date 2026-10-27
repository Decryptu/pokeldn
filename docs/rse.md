---
title: Ruby, Sapphire and Emerald
nav_order: 11
has_children: true
nav_exclude: true
search_exclude: true
---

# Ruby, Sapphire and Emerald

Ruby, Sapphire and Emerald have no Switch release; pokeldn carries support prepared from
[pret/pokeemerald](https://github.com/pret/pokeemerald) and [pret/pokeruby](https://github.com/pret/pokeruby)
for a release in the same GBA application as FireRed and LeafGreen. Every address is the GBA English
build's. The app shows the title only from a source checkout ([Unreleased titles](gui.md#unreleased-titles)).

An Emerald built for that application runs in place of a FireRed cartridge and links with pokeldn's
hosts ([The Switch build](rse_switch_build.md)). That build is the instrument for these pages until a
release exists.

| page | subject |
|---|---|
| [Trade and the Union Room](rse_link.md) | joining a host, the link trade, the Union Room |
| [Mystery Gift](rse_gift.md) | the protocol differences, the gifts, the menu gate |
| [The Switch build](rse_switch_build.md) | Emerald for the FireRed application: the port, building, running, test saves |

The GBA application already holds a play-report table for all five Gen III game codes, `AXV?`,
`AXP?` and `BPE?` among them ([Code on the console](frlg_rom.md)), and all twelve FireRed and
LeafGreen titles share the first local communication id `0x01006fa0233f8000`
([The ROM map](frlg_rom_map.md)).

## What each game can do over the link

| | Ruby / Sapphire | Emerald |
|---|---|---|
| Wireless Adapter (RFU) code | none: SIO multi-player cable only | FireRed's `link_rfu_2.c` |
| link trade | cable | Direct Corner and Union Room, as FireRed |
| Mystery Gift (Wonder Cards, Wonder News) | none | FireRed's protocol and structs |
| Mystery Event | e-Reader over cable, enabled by "MYSTERY EVENT IS EXCITING" | none from the title menu |

The launchers speak the Wireless Adapter protocol, so they reach Emerald only. Above the link, the
RS cable protocol shares the `LinkPlayer` record, block sizes 200, 200, 100, 220 and 40, the link
command words and the trade blocks [pokeruby link.c, trade.c]. RS writes an 11-byte name over the
bytes FireRed and Emerald read as progress flags, so both zero those flags for an RS partner.

## Identifiers

| field | Ruby | Sapphire | Emerald |
|---|---|---|---|
| game code | `AXV` + language | `AXP` + language | `BPE` + language |
| header title | `POKEMON RUBY` | `POKEMON SAPP` | `POKEMON EMER` |
| `gGameVersion` | 2 | 1 | 3 |
| `LinkPlayer.version` | `0x4002` | `0x4001` | `0x4003` |

The language letter is `E`, `F`, `D`, `I`, `S` or `J` [include/constants/global.h:8-12].

## The save

The flash layout, signature `0x08012025` and checksum are FireRed's [save.c]. SaveBlock1 is `0x3D88`
bytes, SaveBlock2 `0xF2C`; the sectors checksum `0xF2C`, `0xF80` three times, `0xF08`, `0xF80` eight
times and `0x7D0` bytes by id. Party count `0x234`, party `0x238`, money `0x490` (XORed with SaveBlock2
`+0xAC`), flags `0x1270`, vars `0x139C`, game stats `0x159C`, Mystery Gift `0x322C`. SaveBlock2 has no
`filler_B20`.

| field | offset | |
|---|---|---|
| SaveBlock1 `continueGameWarp` | `0x0C` | `WarpData`: s8 group, s8 map, s8 warp id, pad, s16 x, s16 y |
| SaveBlock2 `specialSaveWarpFlags` | `0x09` | bit 0 `CONTINUE_GAME_WARP`: CONTINUE warps to `continueGameWarp` [overworld.c:1739] |

CONTINUE without `CONTINUE_GAME_WARP` restores SaveBlock1's map view and object events with `pos` and
`location`; a save edit that moves only `pos` and `location` loads the old map with the player
invisible.

## Emerald link features pokeldn lacks

Record Mixing, the Berry Blender, contests, the Battle Tower link multi battle, Berry Crush, Pokemon
Jump and Dodrio Berry Picking (link groups 12 to 21, activities 14 and 23 to 29).

## Unresolved

- Whether a Switch release exists, and its title ids, game codes and software version.
- Whether it keeps the FireRed application's communication id, scene id and advertisement packing.
- How a Switch release carries Ruby and Sapphire's cable link.
- Every ROM and RAM address of a Switch Emerald.

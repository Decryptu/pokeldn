---
title: Ruby, Sapphire and Emerald
nav_order: 11
nav_exclude: true
search_exclude: true
---

# Ruby, Sapphire and Emerald

Ruby, Sapphire and Emerald have no Switch release; pokeldn carries support prepared from
[pret/pokeemerald](https://github.com/pret/pokeemerald) and [pret/pokeruby](https://github.com/pret/pokeruby)
for a release in the same GBA application as FireRed and LeafGreen. Nothing here is measured on a
console, and every address is the GBA English build's. The app shows the title only from a source
checkout ([Unreleased titles](gui.md#unreleased-titles)).

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

## Joining a host

The advertisement record and `RfuGameData` are FireRed's [include/link_rfu.h:80-113]. Emerald lists a
host whose version is not 3 as "not ready" unless the player is Champion and the host advertises
`canLinkNationally` [union_room.c:1266-1283; trade.c:2514-2521]. `--version emerald` (or `ruby`,
`sapphire`) advertises that version and sets `canLinkNationally`, `hasNationalDex` and `gameClear`
from the profile (bits 16, 17 and 24 of the word at `[16:20]`; `RfuGameData` bits 7, 8, 9). FireRed
and LeafGreen keep those bits clear.

## Trade

The wire is FireRed's (trainer card Wonder Card id at `0x60`), with two differences:

- Without the National Dex, Emerald refuses an egg or a non-Hoenn species and sends
  `READY_CANCEL_TRADE` after an A press [trade.c:1585-1589]; `LinkPlayer.progressFlags & 0xF` reports
  the dex. `pokeldn.rse.constants` holds the 202-entry Hoenn dex and the host logs refused offers.
- GBA Emerald runs five post-trade standby rounds; Switch FireRed runs six, the last followed by
  `svc_FinishSave`. `--save-rounds N` sets the count (default 6).

With version 3 Emerald draws the host's trainer card with frontier symbols at `0x3A` and Battle
Points at `0x3C`. Its receive queue holds 32 slots (FireRed 20), and it accepts serial `0x0000`
beside `0x0002` and `0x7F7D`.

## Mystery Gift

The transport, scripts, 332-byte `WonderCard`, 444-byte `WonderNews` and `MysteryGiftSave` (`0x36C`)
are FireRed's. GameData `+0x0C` and `+0x10` carry 4 and `0x200` for a card, 5 and `0x201` for news,
where FireRed sends 1 and its version code [mystery_gift.c:346-363]; Emerald's check wants bit 2 and
`0x380` for a card [mystery_gift.c:390]. The host applies the rule of the game the console's game
code names. Emerald's field opcodes differ only at `0xC7..0xCC`, `0xD0`, `0xD3..0xD5` and run to
`0xE3`.

| | FireRed / LeafGreen | Emerald |
|---|---|---|
| card flagId 1000 (`sReceivedGiftFlags[0]`) | `0x2A7` | `0x13A` |
| `FLAG_MYSTERY_GIFT_DONE` | `0x3D8` | `0x1E4` |
| the gift cursor vars | `0x40B6..0x40BC` | `0x40DE..0x40E4` |
| last item | 374 | 376 (`ITEM_OLD_SEA_MAP`) |
| `StartLegendaryBattle` / `GetMysteryGiftCardStat` | 312 / 390 | 314 / 392 |
| `special` index check | bounded by `gSpecialsEnd` [scrcmd.c:101] | none: 527 specials [scrcmd.c:119] |
| RamScript in SaveBlock1 | `0x361C` | `0x3728` |

`gift_composer` takes a `GameRules` table; `pokeldn.rse.constants.EMERALD_RULES` compiles under
Emerald's numbers. The host refuses a console of another game before sending. Emerald's Wonder News
has no reward.

### Gifts

`pokeldn.rse.gifts` rebuilds pokeemerald's four official gift scripts op for op with pokeldn's text
(`tests/test_rse.py` compares the bytecode). The Mystery Gift man on Pokemon Center 2F runs the saved
script.

| preset | card flagId | what it does |
|---|---|---|
| Aurora Ticket | 1000 | the ticket and `FLAG_ENABLE_SHIP_BIRTH_ISLAND` |
| Mystic Ticket | 1001 | the ticket and `FLAG_ENABLE_SHIP_NAVEL_ROCK` |
| Old Sea Map | 1002 | the map and `FLAG_ENABLE_SHIP_FARAWAY_ISLAND` |
| Altering Cave rumor | 1003 | the next of the cave's nine wild tables |
| Eon Ticket | 1007 | the game's own handout [cable_club.inc:33]: the ticket and `FLAG_ENABLE_SHIP_SOUTHERN_ISLAND` |
| Master Ball, Rare Candy x5, Surfing Pichu egg | 1004..1006 | composed under `EMERALD_RULES` |

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --version emerald \
        --gift-file old-sea-map.pokegift --keys "$HOME/Documents/Switch/23.0.0 keys/prod.keys"

An Emerald gift file has one variant, `emerald` ([Mystery Gift files](gifts.md)). Native code, save
backup and the FireRed presets are refused for Emerald.

## The save

The flash layout, signature `0x08012025` and checksum are FireRed's [save.c]. SaveBlock1 is `0x3D88`
bytes, SaveBlock2 `0xF2C`. Party count `0x234`, party `0x238`, money `0x490` (XORed with SaveBlock2
`+0xAC`), flags `0x1270`, vars `0x139C`, game stats `0x159C`, Mystery Gift `0x322C`. SaveBlock2 has no
`filler_B20`.

## Emerald link features pokeldn lacks

Record Mixing, the Berry Blender, contests, the Battle Tower link multi battle, Berry Crush, Pokemon
Jump and Dodrio Berry Picking (link groups 12 to 21, activities 14 and 23 to 29).

## Unresolved

- Whether a Switch release exists, and its title ids, game codes and software version.
- Whether it keeps the FireRed application's communication id, scene id and advertisement packing.
- How a Switch release carries Ruby and Sapphire's cable link.
- The post-trade standby count of a Switch Emerald.
- Every ROM and RAM address of a Switch Emerald.
- The Japanese Emerald Mystery Gift activities and card sizes.
- Whether the Switch keeps Emerald's Mystery Gift menu gate (`FLAG_SYS_MYSTERY_GIFT_ENABLE`, set by
  "LINK TOGETHER WITH ALL" [easy_chat.c:693]).

---
title: Ruby, Sapphire and Emerald
nav_order: 11
nav_exclude: true
search_exclude: true
---

<a id="ruby-sapphire-and-emerald"></a>
# Ruby, Sapphire and Emerald

Ruby, Sapphire and Emerald have no Switch release. pokeldn carries support prepared from
[pret/pokeemerald](https://github.com/pret/pokeemerald) and
[pret/pokeruby](https://github.com/pret/pokeruby) for the case where Nintendo ships them in the same
GBA application as FireRed and LeafGreen. Nothing on this page is measured on a console. Every
address and number is the GBA English build's; the FireRed Switch build is a new revision
(`0x0A`) whose code moved, so an Emerald Switch build would differ the same way.

The app shows the title only when it runs from a source checkout
([Unreleased titles](gui.md#unreleased-titles)); this page is left out of the site's navigation.

<a id="why-the-gba-application-is-expected-to-run-them"></a>
## Why the GBA application is expected to run them

The FireRed and LeafGreen application already holds a play-report table for each of the five
Gen III game codes, `AXV?` Ruby, `AXP?` Sapphire and `BPE?` Emerald among them
([Code on the console](frlg_rom.md)). All twelve FireRed and LeafGreen titles list the same first
local communication id, `0x01006fa0233f8000` ([The ROM map](frlg_rom_map.md)); the launchers' scan
joins the only network present when no id is given.

<a id="what-each-game-can-do-over-the-link"></a>
## What each game can do over the link

| | Ruby / Sapphire | Emerald |
|---|---|---|
| Wireless Adapter (RFU) code | none: `pokeruby` has the SIO multi-player cable only | the same `link_rfu_2.c` as FireRed |
| link trade | cable | Direct Corner and Union Room, as FireRed |
| Mystery Gift (Wonder Cards, Wonder News) | none | the same protocol and structs as FireRed |
| Mystery Event | e-Reader over cable, enabled by "MYSTERY EVENT IS EXCITING" | none from the title menu |

pokeldn's launchers speak the Wireless Adapter protocol, so Emerald is the game they can reach.
How a Switch release would carry Ruby and Sapphire's cable link is unknown.

The RS cable protocol shares with FireRed and Emerald what pokeldn's trade engine uses above the
link: the `LinkPlayer` record with its GameFreak magics, block sizes 200, 200, 100, 220 and 40, the
link command words, and a trade's three 200-byte party blocks, 220-byte mail block and 40-byte
ribbon block [pokeruby link.c, trade.c]. RS writes an 11-byte name into `LinkPlayer`, over the bytes
FireRed and Emerald read as progress flags, so both zero those flags for an RS partner.

<a id="identifiers"></a>
## Identifiers

| field | Ruby | Sapphire | Emerald |
|---|---|---|---|
| game code | `AXV` + language | `AXP` + language | `BPE` + language |
| header title | `POKEMON RUBY` | `POKEMON SAPP` | `POKEMON EMER` |
| `gGameVersion` | 2 | 1 | 3 |
| `LinkPlayer.version` | `0x4002` | `0x4001` | `0x4003` |

The language letter is `E`, `F`, `D`, `I`, `S` or `J`, as on the FireRed cartridges. The version and
language numbers are the same in all three decomps [include/constants/global.h:8-12].

<a id="joining-a-host"></a>
## Joining a host

The advertisement record and the `RfuGameData` layout are FireRed's [include/link_rfu.h:80-113].
When the player searches for a trade, Emerald lists a host whose advertised version is not 3 as
"not ready" unless the player is Champion and the host advertises `canLinkNationally`
[union_room.c:1266-1283]; the trading board applies the same rule [trade.c:2514-2521].

A launcher run with `--version emerald` (or `ruby`, `sapphire`) advertises that version and sets
`canLinkNationally`, `hasNationalDex` and `gameClear` from its profile, in the advertisement record
(bits 16, 17 and 24 of the word at `[16:20]`) and in the NI game data (`RfuGameData` bits 7, 8, 9).
FireRed and LeafGreen keep the bytes retail consoles accepted, with those bits clear.

<a id="trade"></a>
## Trade

The wire is FireRed's: link commands, block exchange order and sizes, the trainer card
(Wonder Card id at `0x60`). Two rules differ.

- Without the National Dex, Emerald refuses the partner's egg or a species outside the Hoenn
  Pokedex, then waits for an A press before sending `READY_CANCEL_TRADE` [trade.c:1585-1589]. The
  console reports its National Dex in `LinkPlayer.progressFlags & 0xF`. `pokeldn.rse.constants`
  holds the 202-entry Hoenn dex; the host logs which offers such a console refuses.
- GBA Emerald runs five post-trade standby rounds (`trade.c` states 1, 41, 5, 8 and the trade menu's
  init); Switch FireRed runs six, its state 43 round followed by `svc_FinishSave`. `--save-rounds N`
  sets the count the host waits for (default 6). A Switch Emerald that saves through the same
  syscall would carry the sixth round; the count is unknown until a console is measured.

With version 3 an Emerald console draws our trainer card with frontier symbols at `0x3A` and Battle
Points at `0x3C`; with 4 or 5 it draws a FireRed card. Emerald's receive queue holds 32 slots against
FireRed's 20, and it accepts the serial `0x0000` beside `0x0002` and `0x7F7D`.

<a id="mystery-gift"></a>
## Mystery Gift

The link transport, the server and client scripts, the 332-byte `WonderCard`, the 444-byte
`WonderNews` and `MysteryGiftSave` (`0x36C`) are FireRed's, field for field. Three things differ.

The game data at `+0x0C` and `+0x10` carries gift-type bits in Emerald, 4 and `0x200` for a card,
5 and `0x201` for news, where FireRed sends 1 and its version code [mystery_gift.c:346-363]. Emerald's
check wants bit 2 and `0x380` for a card and nothing for news [mystery_gift.c:390]. The host runs
the rule of the game the console's game code names; the console's version is read from its game
code.

Flags, vars and specials a gift script names sit at other numbers. The field-script opcodes pokeldn
emits are the same; only `0xC7..0xCC`, `0xD0` and `0xD3..0xD5` differ, and Emerald runs to `0xE3`.

| | FireRed / LeafGreen | Emerald |
|---|---|---|
| card flagId 1000 (`sReceivedGiftFlags[0]`) | `0x2A7` | `0x13A` |
| `FLAG_MYSTERY_GIFT_DONE` | `0x3D8` | `0x1E4` |
| the gift cursor vars | `0x40B6..0x40BC` | `0x40DE..0x40E4` |
| last item | 374 | 376 (`ITEM_OLD_SEA_MAP`) |
| `StartLegendaryBattle` / `GetMysteryGiftCardStat` | 312 / 390 | 314 / 392 |
| `special` index check | bounded by `gSpecialsEnd` [scrcmd.c:101] | none: 527 specials [scrcmd.c:119] |
| RamScript in SaveBlock1 | `0x361C` | `0x3728` |

`pokeldn.frlg.gift.gift_composer` takes a `GameRules` table; `pokeldn.rse.constants.EMERALD_RULES`
compiles a gift under Emerald's numbers. A payload carries its game, and the host refuses a console
of another game before anything is sent.

Wonder News in Emerald has no reward: nothing increments its step counter and no script reads its
berry.

<a id="gifts"></a>
### Gifts

The four official gift scripts pokeemerald ships (`data/scripts/gift_aurora_ticket.inc`,
`gift_mystic_ticket.inc`, `gift_old_sea_map.inc`, `gift_altering_cave.inc`) are rebuilt op for op in
`pokeldn.rse.gifts` with pokeldn's own text; `tests/test_rse.py` assembles the decomp's sources and
compares the bytecode. The Mystery Gift man on 2F of a Pokemon Center runs the saved script
(`trywondercardscript`, `CableClub_EventScript_MysteryGiftMan`).

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

An Emerald gift file has one variant, `emerald` ([Mystery Gift files](gifts.md)). Native code,
save backup and the FireRed presets name FireRed addresses and are refused for Emerald.

<a id="the-save"></a>
## The save

The flash layout, sector signature `0x08012025` and checksum are FireRed's [save.c]. SaveBlock1 is
`0x3D88` bytes and SaveBlock2 `0xF2C`. Party count `0x234`, party `0x238`, money `0x490` (XORed with
SaveBlock2 `+0xAC`), flags `0x1270`, vars `0x139C`, game stats `0x159C`, Mystery Gift `0x322C`.
SaveBlock2 has no `filler_B20`; the kept native payload would need another home.

<a id="emerald-link-features-pokeldn-lacks"></a>
## Emerald link features pokeldn lacks

Record Mixing (the Record Corner), the Berry Blender, contests, the Battle Tower link multi battle,
Berry Crush, Pokemon Jump and Dodrio Berry Picking run over the Wireless Adapter in Emerald (link
groups 12 to 21, activities 14 and 23 to 29). FireRed carries the last three as well.

<a id="unresolved"></a>
## Unresolved

- Whether a Switch release exists, and its title ids, game codes and software version.
- Whether it keeps the communication id, scene id and advertisement packing of the FireRed application.
- How a Switch release carries Ruby and Sapphire's cable link.
- The post-trade standby count of a Switch Emerald.
- Every ROM and RAM address of a Switch Emerald; the native-code payloads need them.
- The Japanese Emerald Mystery Gift activities and card sizes.
- Whether the Switch keeps Emerald's in-game gate on the Mystery Gift menu (`FLAG_SYS_MYSTERY_GIFT_ENABLE`,
  set by "LINK TOGETHER WITH ALL" [easy_chat.c:693]).

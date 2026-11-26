---
title: Emerald Mystery Gift
parent: Ruby, Sapphire and Emerald
nav_order: 2
nav_exclude: true
search_exclude: true
---

# Emerald Mystery Gift

Emerald's Mystery Gift is FireRed's ([Mystery Gift](frlg_gift.md)) with Emerald's numbers. The launcher
is `bin/frlg_mg_host.py --version emerald`.

## The menu gate

The title menu lists MYSTERY GIFT once `FLAG_SYS_MYSTERY_GIFT_ENABLE` (`0x8DB`) is set. The questionnaire
on the Poke Mart counter sets it for LINK TOGETHER WITH ALL once the player holds the Pokedex
[questionnaire.inc:30-37; easy_chat.c:693]. The path is then Mystery Gift, Wonder Cards, Friend.

## The protocol

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

On an emulated console [the Switch build](rse_switch_build.md) lists POKELDN on the Friend search, identifies
itself as Emerald holding no card, takes the Old Sea Map card and closes LDN normally; the Pokemon
Center 2F delivery man then hands over the OLD SEA MAP from the saved script.

## Gifts

`pokeldn.rse.gifts` rebuilds pokeemerald's four official gift scripts op for op with pokeldn's text
(`tests/test_rse.py` compares the bytecode). The Mystery Gift man on Pokemon Center 2F runs the saved
script.

| preset | card flagId | what it does |
|---|---|---|
| Aurora Ticket | 1000 | the ticket and `FLAG_ENABLE_SHIP_BIRTH_ISLAND` |
| Mystic Ticket | 1001 | the ticket and `FLAG_ENABLE_SHIP_NAVEL_ROCK` |
| Old Sea Map | 1002 | the map and `FLAG_ENABLE_SHIP_FARAWAY_ISLAND` |
| Eon Ticket | 1007 | the game's own handout [cable_club.inc:33]: the ticket and `FLAG_ENABLE_SHIP_SOUTHERN_ISLAND` |
| Altering Cave rumor | 1003 | the next of the cave's nine wild tables |

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --version emerald \
        --gift-file old-sea-map.pokegift --keys "$HOME/Documents/Switch/23.0.0 keys/prod.keys"

The other presets are the Wonder Cards and event Pokemon FireRed offers
([FireRed's gifts](frlg_gift.md#cards-every-gba-title-shares)), compiled under `EMERALD_RULES`:
`wonder_card_events.gba_cards(EMERALD_RULES)` swaps in Emerald's card-stat special (392),
`EnableNationalPokedex` (499) and `FLAG_SYS_NATIONAL_DEX` (`0x896`).

The three tickets' received flags are `sReceivedGiftFlags[0..2]` [mystery_gift.c:229] and the Eon
handout reads flagId 1007's. A composed card clears its receipt flag on the first talk and sets it at
the end, so `pokeldn.rse.gifts.composed` refuses flagIds 1000, 1001, 1002 and 1007.

## Event Pokemon

`--gift event-pokemon --event-pokemon NAME` sends FireRed's event card
([Event Pokemon](frlg_gift.md#event-pokemon)) under Emerald's numbers. Emerald's Mystery Event VM
(`CLI_RUN_MEVENT_SCRIPT`) runs the same `givepokemon`, with offsets relative to the receive buffer, so
one `emerald` variant serves every Emerald cartridge.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --version emerald \
        --gift event-pokemon --event-pokemon "WISHMKR Jirachi" --keys "$HOME/Documents/Switch/23.0.0 keys/prod.keys"

A compiled preset becomes a file with `pokeldn.gifts.save(PATH, pokeldn.rse.gift_builder.compile(PRESET[key].state))`;
an event preset exports with `--export-gift PATH`. An Emerald gift file has one variant, `emerald`
([Mystery Gift files](gifts.md)), holding `card`, `ram_script` and an optional `mevent`. Native code,
save backup, Wonder News, the questionnaire and FireRed's other presets are refused for Emerald.

## Unresolved

- The Japanese Emerald Mystery Gift activities and card sizes.
- Whether a Switch release keeps the menu gate.

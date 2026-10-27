---
title: Trade and the Union Room
parent: Ruby, Sapphire and Emerald
nav_order: 1
nav_exclude: true
search_exclude: true
---

# Emerald trade and the Union Room

Emerald's wireless link is FireRed's ([The link](frlg_link.md)); this page lists where Emerald
differs. The launchers are `bin/frlg_trade_host.py` and `bin/frlg_trade_join.py` with
`--version emerald`. Measurements are against [the Switch build](rse_switch_build.md) on an emulated console.

## Joining a host

The advertisement record and `RfuGameData` are FireRed's [include/link_rfu.h:80-113]. Emerald lists a
host whose version is not 3 as "not ready" unless the player is Champion and the host advertises
`canLinkNationally` [union_room.c:1266-1283; trade.c:2514-2521]. `--version emerald` (or `ruby`,
`sapphire`) advertises that version and sets `canLinkNationally`, `hasNationalDex` and `gameClear`
from the profile (bits 16, 17 and 24 of the word at `[16:20]`; `RfuGameData` bits 7, 8, 9). FireRed
and LeafGreen keep those bits clear.

Every Pokemon Center 2F attendant answers "undergoing adjustments" until `FLAG_SYS_POKEDEX_GET`
(`0x861`) is set [cable_club.inc:803, 885, 901, 1152].

## Trade

The wire is FireRed's (trainer card Wonder Card id at `0x60`), with two differences:

- Without the National Dex, Emerald refuses an egg or a non-Hoenn species from its partner
  [trade.c:1584-1589]: the trade screen shows "The other TRAINER's POKeMON can't be traded now" and the
  console sends `READY_CANCEL_TRADE` after an A press. `LinkPlayer.progressFlags & 0xF` reports the
  dex. `pokeldn.rse.constants.HOENN_DEX` holds the 202 entries and the host logs refused offers.
- Emerald runs five post-trade standby rounds [trade.c:4686-4797]; Switch FireRed runs six, the last
  followed by `svc_FinishSave`. The Switch build keeps five: the console sends `READY_EXIT_STANDBY` 5 to
  9 and waits on "communication standby" for a host that expects a sixth. `--version emerald` makes
  the host run five; `--save-rounds N` overrides.

With version 3 Emerald draws the host's trainer card with frontier symbols at `0x3A` and Battle
Points at `0x3C`. Its receive queue holds 32 slots (FireRed 20), and it accepts serial `0x0000`
beside `0x0002` and `0x7F7D`.

On an emulated console the Switch build completes a Direct Corner trade with the host: LinkPlayer, trainer cards,
the seat route, party, mail and ribbon blocks, the swap, five standby rounds, `READY_CLOSE_LINK`, the
RFU disconnect frame and the Pia leave, then a save written to the emulator's storage.

## The Union Room

The room, the activity menu and the trading board run as on FireRed ([The Union Room](frlg_link.md#the-union-room)).
`--union-room --union-room-keepalive 120` spawns POKELDN's avatar and the console connects when its
player talks to it. Talking to POKELDN shows GREETINGS, BATTLE, CHAT and EXIT; Emerald offers no trade
from that menu.

| activity | flags | measured on an emulated console |
|---|---|---|
| GREETINGS | `--union-room` | both trainer cards, the standby barrier, back to the room |
| EXIT | `--union-room` | `READY_CLOSE_LINK` and a normal disconnect |
| trading board | `--union-room --board-type TYPE` | the console picks POKELDN's listing, the Pokemon and mail blocks cross, the trade and the save complete, the link closes |
| CHAT | `--union-room-chat` | not run |
| BATTLE | `--union-room-battle` | not run |

The host serves a board trade the console starts from POKELDN's listing; it does not request one from
the console's own listing. `--board-type` names the type the host asks for in return, and the console
offers only a Pokemon of that type.

With `--union-room-keepalive 600` the console sat on "Communicating with POKELDN..." after both trainer
card blocks crossed and never showed the menu; 120 reached it.

## Unresolved

- The post-trade standby count of a Switch Emerald release.
- Union Room chat and battle against Emerald.

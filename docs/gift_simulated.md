---
title: Simulated Mystery Gifts
---
# Simulated Mystery Gifts

A simulated Mystery Gift brings an official gift Pokemon to a game that takes no Mystery Gift card
over local wireless: the game's trade host offers a fresh legal copy, as a trainer who received the
gift, and the console's player trades a Pokemon back, which goes to Received. A gift that names its
receiver is made for the console's own save ([Made for the receiving player](#made-for-the-receiving-player)).

| game | tool | the host it is | offer flag |
|---|---|---|---|
| Let's Go | `lgpe-gift-host` | Trade (Host), `bin/lgpe_host.py` | `--offer` |
| Brilliant Diamond/Shining Pearl | `bdsp-gift-host` | Trade (Host), `bin/bdsp_host.py` | `--offer` |
| Legends Arceus | `pla-gift-host` | Trade (Host), `bin/pla_host.py` | `--trade-box-record` |
| Scarlet/Violet | `sv-gift-host` | Trade (Host), `bin/sv_host.py` ([Hosting for a console](sv.md#hosting-for-a-console)) | `--trade-offer` |
| Legends Z-A | `za-gift-host` | Trade (Host), `bin/za_host.py` | `--trade-offer` |

Each tool is its game's Trade (Host) with up to six event Pokemon in trade order
(`catalog.simulated_gift`); the host keeps the session between trades.

## The gifts

PKHeX.Core embeds every distribution its legality check knows, one table per game; nothing is
downloaded. The PKHeX service's `gift_events` lists a table's Pokemon cards (eggs and item cards left
out), newest first by `EncounterServerDate.GetDistributionWindow`, undated cards last. PKHeX.Core
26.8.26 holds:

| game | table | gift Pokemon | opened | HOME's | Your OT |
|---|---|---:|---|---|---:|
| Let's Go | `MGDB_G7GG` | 15 | undated, but for HOME's Meltan (11 Feb 2025) | Meltan (9028) | 3 |
| Brilliant Diamond/Shining Pearl | `MGDB_G8B` | 9 | 18 May 2022 to 27 Jan 2025, 5 undated | Turtwig, Chimchar, Piplup (9015 to 9017), Manaphy (9026) | 3 |
| Legends Arceus | `MGDB_G8A` | 11 | 27 Jan 2022 to 27 Jan 2025 | Rowlet, Cyndaquil, Oshawott (9018 to 9020), Enamorus (9027) | 3 |
| Scarlet/Violet | `MGDB_G9` | 106 | 17 Nov 2022 to 5 Jun 2026 | Sprigatito, Fuecoco, Quaxly (9021 to 9023), Meloetta (9024), Garchomp (9035) | 29 |
| Legends Z-A | `MGDB_G9A` | 8 | 14 Oct 2025 to 26 Apr 2026 | Chikorita, Tepig, Totodile (9031 to 9033), Volcanion (9034) | 5 |

A gift's key is `card-species-form`, plus the Tera type on Scarlet/Violet (`0503-964-0-10` is
Gavin's Palafin). Scarlet/Violet's card 1521 holds eighteen Mew, one per Tera type.

The tool lists each gift as the Settings trainer would receive it (PKHeX's `ConvertToPKM`): the card's
OT and language where the card fixes them, otherwise Your OT, with level, Tera type, shininess, held
item and opening day ([Mystery Gift - Simulated](gui.md#mystery-gift---simulated)). A Your OT card
that never reached saves in the Settings trainer's language is listed as illegal.

### Saves a card reached

A Your OT copy names the receiving save as its OT, so it must be a save the card reached.
`gift_event` replies `refused` with the reason, empty when allowed (`services/pkhex/Program.cs`):

- Language: the copy is in the save's language. Where the card fixes another, PKHeX's
  `CanHaveLanguage` decides (`InTrainerLanguage`).
- Version: under `"only_version"`, a card refuses a version it never reached (`ReachedVersion`).
  HOME's cards (9000 on) reached either version; another card that fixes its origin reached that
  version alone; otherwise `RestrictVersion` (Let's Go's `IRestrictVersion`) decides.

A card with its own trainer is never refused: its copy is a traded Pokemon. At PKHeX.Core 26.8.26 the
only refused Your OT cards are Let's Go's Meltan and Melmetal (1501, 1502), legal in Simplified
Chinese alone (`WB7.IsMainlandChinaGift`).

### HOME's gifts

PKHeX's HOME cards rebuild what HOME hands out:

| OT | gallery | cards | made for the receiving player |
|---|---|---|---|
| HOME | "Simulated HOME" | Let's Go's Meltan (9028), Manaphy (9026), Enamorus (9027), Meloetta (9024), Volcanion (9034) | no: goes as made |
| the receiving trainer's | "Simulated (Trainer)" | Turtwig, Chimchar, Piplup (9015 to 9017); Rowlet, Cyndaquil, Oshawott (9018 to 9020) | yes |
| the receiving trainer's, with a handler | "Simulated (Trainer)" | Sprigatito, Fuecoco, Quaxly (9021 to 9023); Chikorita, Tepig, Totodile (9031 to 9033) | no: goes with the trainer from Settings |
| PJCS26, in Japanese | "Simulated PJCS26" | Scarlet/Violet's Garchomp (9035) | no: goes as made |

Outside Let's Go, a HOME gift carries a HOME tracker, set by
[The HOME tracker setting](gui.md#the-home-tracker-setting): none under `empty` (PKHeX's only
complaint, accepted), a made one under `made` (Pokemon HOME refuses it). Each reply names it
(`home_tracker`); the list outlines such gifts in amber, and the host inherits the setting
(`POKELDN_HOME_TRACKER`).

Two HOME gifts need fixes in `services/pkhex/Program.cs`:

- Let's Go's Meltan (9028) keeps HOME's height and weight (`WB7.IsHeightWeightFixed`, `ResetSizes`).
- Legends Z-A's Chikorita, Tepig and Totodile (9031 to 9033) get HOME's IVs, three perfect and 20 in
  the rest (`WA9.HomeBaseIV`, `SetHomeIVs`).

## The copy a trade offers

`gift_event` makes a fresh copy for the Settings trainer on each of the game's versions until one is
legal. A copy illegal as made gets the handler POKELDN. Moves are never refitted, and a rejected PID
is re-rolled up to eight times per version. The host checks the copy again as an offer; New PID each
run gives a new PID and encryption constant where the card rolls them. Every gift passes under
either HOME tracker setting (`tests/test_pokemon_service.py`).

The console receives:

- the card's own trainer and language where the card fixes them;
- otherwise the console's own save as trainer
  ([Made for the receiving player](#made-for-the-receiving-player)), or with that off the Settings
  trainer;
- with the card's or the Settings trainer, the console's player as handler.

## Made for the receiving player

`--for-receiver` (on by default in the app) makes a Your OT gift during the trade for the console's
own save. A gift with its own trainer goes as made. A gift legal only with a handler (`handled`:
HOME's Sprigatito, Fuecoco, Quaxly, Chikorita, Tepig, Totodile) goes with the Settings trainer, since
a save receiving its own OT clears the handler and PKHeX then refuses it
([What a trade rewrites](sv.md#what-a-trade-rewrites)). The app passes each offer as `--gift-event KEY`
(`command._args`).

At launch the host asks `gift_event` for the card under the probe trainer `receiver_gift.PROBE`,
which tells whether the card names its receiver (`your_ot`) and starts the service. The five hosts
share `pokeldn.receiver_gift`, whose `ReceiverGift` stands where an online partner would
([In a launcher](online.md#in-a-launcher)).

### Whose save it is

The offered Pokemon names the save when the save caught it: original trainer (handler 0), one of the
game's versions, not an egg. It gives OT name, 16-bit TID and SID, gender, language and version
(`receiver_gift.own_trainer`), read on a worker thread (`Service.owner`; Scarlet/Violet in Python,
`receiver_gift.sv_owner`).

| game | Your OT cards | the console's offer | versions |
|---|---|---|---|
| Let's Go | Meltan (1501), Melmetal (1502), both for Simplified Chinese saves alone; Mew (2001) | kind 2 + 2r in trade r, an encrypted 232-byte PB7 | 42 Pikachu, 43 Eevee |
| Brilliant Diamond/Shining Pearl | HOME's Turtwig, Chimchar, Piplup (9015 to 9017) | 0x13, an encrypted 328-byte PB8 | 48 Brilliant Diamond, 49 Shining Pearl |
| Legends Arceus | HOME's Rowlet, Cyndaquil, Oshawott (9018 to 9020) | selector 4, an encrypted 376-byte PA8 | 47 |
| Scarlet/Violet | 9 cards, Mew (1521) and Pikachu (1501) among them | the 348-byte body of `80 00 02 00` ([The record a trade message carries](sv.md#the-record-a-trade-message-carries)) | 50 Scarlet, 51 Violet |
| Legends Z-A | Charizard (1607), Ralts (1601) | the 354-byte pick | 52 |

Otherwise the console's session names the save before any Pokemon (`receiver_gift.hear`):

| game | the console's message | what it names |
|---|---|---|
| Let's Go | kind 1, the save's MyStatus block ([Kind 1](lgpe_session.md#the-games-messages-on-the-reliable-protocol), `pb7.first_trainer`) | id pair, version, gender, language, name |
| Brilliant Diamond/Shining Pearl | 0x24 `TradeTranerData`, as the trade opens ([The Pokemon](bdsp_trade.md#the-pokemon), `room.traner_trainer`) | id pair, version, language, name |
| Legends Arceus | its 0x81 data exchange record, the save's MyStatus block ([The game's reader](pla.md#the-games-reader-and-the-pre-handler-phase), `data_exchange.read_trainer`) | id pair, version, gender, language, name |
| Scarlet/Violet | record 1 of its identity block, on the 0x81 port of its station index ([The records](sv.md#the-records), `sv_host.identity_chunk`, `reference.identity_trainer`) | id pair, version, gender, language, name |
| Legends Z-A | the 1400 identity ([The game's own exchange](za.md#the-games-own-exchange), `reference.identity_trainer`) | id pair, gender, language, name |

Brilliant Diamond/Shining Pearl's session never names the gender
([The model](bdsp_protocol.md#the-model)); the offered Pokemon does, as original trainer or as the
handler the game writes on every received Pokemon
([What the console does to a received Pokemon](bdsp_trade.md#what-the-console-does-to-a-received-pokemon)).
A field the session lacks comes from the offered Pokemon when its original trainer (handler 0) or
handler (handler 1) matches the session's name and id pair; otherwise from Settings. The log names
each such field (`[gift] the console's Pokemon ... cannot name the save`). Legends Arceus and Legends
Z-A have one version. A caught Pokemon offered in a later trade outranks the session, and the copy is
made again.

`gift_event` makes the card on the save's version alone (`"only_version"`) and refuses a card no such
save received ([Saves a card reached](#saves-a-card-reached)). HOME's Turtwig, Chimchar and Piplup are
Brilliant Diamond's.

### The trade

The trade runs as an online one ([Online](online.md)):

1. The console offers first.
2. If neither the Pokemon nor the session names the save, the gift goes under the Settings trainer;
   the host logs why and raises a pop-up ([Pop-ups](gui.md#pop-ups)) once per reason.
3. `gift_event` makes the card for the save, then on a worker thread the copy passes the host's offer
   check (`pokemon.prepare_offer`, under the HOME tracker setting) and its loader.
4. The copy goes up after the console's offer and stays until the trade ends.
5. The host confirms after the console does.

| game | loader | what it checks |
|---|---|---|
| Let's Go | `lgpe_host.boxed` | an encrypted 232-byte box structure whose checksum and sanity word hold |
| Brilliant Diamond/Shining Pearl | `bdsp.pokemon.build_from` | the encrypted PB8 |
| Legends Arceus | the trade box's `box_offer` | its edits, then PKHeX's check of the encrypted record (`pokemon.validate`) |
| Scarlet/Violet | `trade.load_offer` | the 348-byte body a trade message carries |
| Legends Z-A | `za_host.gift_offer` | a 354-byte offer that decrypts; a gift is never sent as a Bad Egg |

A copy PKHeX cannot make or that fails a check goes as the app made it; the log
(`[gift] could not be made ...`) and a pop-up name the save and the stage (`receiver_gift.maker`):

| where | the reason reads |
|---|---|
| the card | the save cannot have received the card: card 1502 gave it in Simplified Chinese alone, never to a save in English |
| PKHeX | PKHeX made an illegal ... from card ...: its check's findings |
| the offer check | the copy fails the host's offer check: ... |
| the loader | the host cannot send the copy: ... |

Scarlet/Violet, Legends Arceus and Legends Z-A keep one `ReceiverGift` per console; Let's Go and
Brilliant Diamond/Shining Pearl host one console. A later trade in the same seat is made as soon as
the one before completes; the last gift serves every later trade.

On retail consoles of all five games the gift arrives with the save's own trainer, whether the
console offered a caught or a traded Pokemon. A gift traded back to the console arrives with handler
0, as the save's own catch ([What a trade rewrites](sv.md#what-a-trade-rewrites)).

## Other games

FireRed and LeafGreen receive event Pokemon through their own Mystery Gift
([Event Pokemon](frlg_gift.md#event-pokemon)). Sword and Shield take real cards over local wireless
([Official event cards](swsh_gift.md#official-event-cards)).

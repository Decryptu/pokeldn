---
title: Simulated Mystery Gifts
---
<a id="simulated-mystery-gifts"></a>
# Simulated Mystery Gifts

Let's Go Pikachu/Eevee, Brilliant Diamond/Shining Pearl, Legends Arceus, Scarlet/Violet and Legends
Z-A take no Mystery Gift card over local wireless. Each has a Mystery Gift - Simulated tool that
brings a console an official gift Pokemon another way: the game's trade host offers a fresh legal
copy, as a trainer who received the gift and trades it on. The console's player offers a Pokemon in
return, which goes to Received like any trade's. A gift that names its receiver is made for the
console's own save ([Made for the receiving player](#made-for-the-receiving-player)).

| game | tool | the host it is | offer flag |
|---|---|---|---|
| Let's Go | `lgpe-gift-host` | Trade (Host), `bin/lgpe_host.py` | `--offer` |
| Brilliant Diamond/Shining Pearl | `bdsp-gift-host` | Trade (Host), `bin/bdsp_host.py` | `--offer` |
| Legends Arceus | `pla-gift-host` | Trade (Host), `bin/pla_host.py` | `--trade-box-record` |
| Scarlet/Violet | `sv-gift-host` | Trade (Host), `bin/sv_host.py` ([Hosting for a console](sv.md#hosting-for-a-console)) | `--trade-offer` |
| Legends Z-A | `za-gift-host` | Trade (Host), `bin/za_host.py` | `--trade-offer` |

Each tool is its game's Trade (Host) with up to six event Pokemon in trade order: the same entry point,
fixed arguments and host code (Brilliant Diamond/Shining Pearl's room password), plus Made for the
receiving player. It sits after the game's trades (`catalog.simulated_gift`). The player offers a
Pokemon back for each gift and leaves after the last trade. The host keeps the session between trades.

<a id="the-gifts"></a>
## The gifts

PKHeX.Core embeds every distribution its legality check knows, one table per game, read from the
package's own resources: nothing is downloaded. The PKHeX service's `gift_events` lists a table's
Pokemon cards, eggs and item cards left out, newest first by the day the distribution opened
(`EncounterServerDate.GetDistributionWindow`); a card PKHeX holds no day for lists after the dated
ones. PKHeX.Core 26.8.26 holds:

| game | table | gift Pokemon | opened | HOME's | Your OT |
|---|---|---:|---|---|---:|
| Let's Go | `MGDB_G7GG` | 15 | undated, but for HOME's Meltan (11 Feb 2025) | Meltan (9028) | 3 |
| Brilliant Diamond/Shining Pearl | `MGDB_G8B` | 9 | 18 May 2022 to 27 Jan 2025, 5 undated | Turtwig, Chimchar, Piplup (9015 to 9017), Manaphy (9026) | 3 |
| Legends Arceus | `MGDB_G8A` | 11 | 27 Jan 2022 to 27 Jan 2025 | Rowlet, Cyndaquil, Oshawott (9018 to 9020), Enamorus (9027) | 3 |
| Scarlet/Violet | `MGDB_G9` | 106 | 17 Nov 2022 to 5 Jun 2026 | Sprigatito, Fuecoco, Quaxly (9021 to 9023), Meloetta (9024), Garchomp (9035) | 29 |
| Legends Z-A | `MGDB_G9A` | 8 | 14 Oct 2025 to 26 Apr 2026 | Chikorita, Tepig, Totodile (9031 to 9033), Volcanion (9034) | 5 |

Each gift has a key, `card-species-form`, with the Tera type after it on Scarlet/Violet
(`0503-964-0-10` is Gavin's Palafin). Scarlet/Violet's card 1521 holds eighteen Mew, one per Tera
type: its 106 gifts come from 77 cards, and the 29 that give the receiver's own trainer from 12. Two
records under one key differ only in what the Pokemon does not carry, such as the card's revision.

The tool's card lists the gifts ([Mystery Gift - Simulated](gui.md#mystery-gift---simulated)), each as
the trainer in Settings would receive it (PKHeX's `ConvertToPKM` with that trainer): the card's own OT
and language where the card fixes them, otherwise Your OT. A tile also shows the level, Tera type,
shininess (may be or always), held item and the day the distribution opened; a hover shows the moves.
The search matches any word of these, the ball, the moves and the card number.

A card reached saves in some languages and versions only, and a copy for a save it never reached is
refused ([Saves a card reached](#saves-a-card-reached)). A Your OT card that never reached saves in
the Settings trainer's language is listed as illegal, its tile saying why, and picking it says so
and changes nothing.

<a id="saves-a-card-reached"></a>
### Saves a card reached

A Your OT copy names the receiving save as its OT, so it must be a save the card reached.
`gift_event` replies with `refused`: why no save like the trainer's received the card, empty when
one did (`services/pkhex/Program.cs`).

- Language: a Your OT copy is in the receiving save's language. Where the card fixes another,
  the copy in the save's language goes through PKHeX's check, which knows the languages each card
  was given in (`CanHaveLanguage`): legal, it is the copy; illegal, the card is refused
  (`InTrainerLanguage`).
- Version: made for one save's version (`"only_version"`, below), a Your OT card refuses a
  version it never reached (`ReachedVersion`). HOME's cards (9000 on) reached either version's saves,
  whatever origin they fix. Any other card that fixes its origin reached that version alone;
  otherwise the card's own restriction says (`RestrictVersion`, Let's Go's `IRestrictVersion`). A
  Your OT card PKHeX makes legal only on another of the game's versions is refused the same way.

A card with its own trainer is never refused: its copy is a traded Pokemon, which any save may hold
in the card's language and from the version it reached. Scarlet/Violet's card 1540 gave Violet a
Koraidon and Scarlet a Miraidon, and either trades to either version.

A reason reads "card 1502 gave it in Simplified Chinese alone, never to a save in English". At
PKHeX.Core 26.8.26, the only Your OT cards of the five games that some save cannot receive are Let's
Go's Meltan and Melmetal (1501, 1502): a mainland China distribution, legal in Simplified Chinese
alone (`WB7.IsMainlandChinaGift`). Every other Your OT card takes every language and version.

<a id="homes-gifts"></a>
### HOME's gifts

HOME delivers Pokemon, not cards: PKHeX's HOME cards rebuild what it hands out. The EventsGallery
names each "Simulated" and the trainer it gives:

| OT | gallery | cards | made for the receiving player |
|---|---|---|---|
| HOME | "Simulated HOME" | Let's Go's Meltan (9028), Manaphy (9026), Enamorus (9027), Meloetta (9024), Volcanion (9034) | no: goes as made |
| the receiving trainer's | "Simulated (Trainer)" | Turtwig, Chimchar, Piplup (9015 to 9017); Rowlet, Cyndaquil, Oshawott (9018 to 9020) | yes |
| the receiving trainer's, with a handler | "Simulated (Trainer)" | Sprigatito, Fuecoco, Quaxly (9021 to 9023); Chikorita, Tepig, Totodile (9031 to 9033) | no: goes with the trainer from Settings |
| PJCS26, in Japanese | "Simulated PJCS26" | Scarlet/Violet's Garchomp (9035) | no: goes as made |

A gift HOME gave carries the tracker HOME sets as it delivers it. Let's Go has no HOME tracker, so its
Meltan needs none. On the other games, a copy of one gets the tracker the HOME tracker setting gives
it ([The HOME tracker setting](gui.md#the-home-tracker-setting)): none under `empty`, which PKHeX
flags and the app accepts as the only problem, and a made one under `made`, which Pokemon HOME
refuses. Each reply says which (`home_tracker`). No other gift needs a tracker.

- The list outlines each such gift in amber with the setting's warning, which the search finds.
- The chosen copy shows Legal, with the same warning.
- The trade's host checks its offer under the same setting, which it inherits from the app
  (`POKELDN_HOME_TRACKER`).

Two of HOME's gifts need more than PKHeX's `ConvertToPKM` gives (`services/pkhex/Program.cs`):

- Let's Go's Meltan (card 9028) keeps the height and weight HOME gave it
  (`WB7.IsHeightWeightFixed`), which PKHeX's check expects in place of the computed ones
  [MiscVerifierPB7]. The service computes every other Let's Go Pokemon's as the console does, and
  restores this card's (`ResetSizes`).
- Legends Z-A's Chikorita, Tepig and Totodile (cards 9031 to 9033) are Alphas with three perfect
  IVs and 20 in the rest (`WA9.HomeBaseIV`). PKHeX.Core 26.8.26 makes them with one perfect IV and
  five at 0, which its own check refuses, so the service sets HOME's spread (`SetHomeIVs`).

<a id="the-copy-a-trade-offers"></a>
## The copy a trade offers

Picking a gift runs `gift_event`: a fresh copy for the trainer in Settings, made on each of the game's
versions in turn until one gives a legal copy, as a card given to one version alone needs. A copy illegal as made gets a
handler (POKELDN), as the receiving save sets one on a card that arrives already handled. The card's
moves are never refitted. A PID roll its own check rejects is rolled again, up to eight times on each
version.

The copy is kept with the built Pokemon and offered like one, under the trainer it was made with until
the trade makes it again for the console's save (below). The host checks it again as it prepares the
offer. With New PID each run on, the copy gets a new PID and encryption constant where the card rolls
them, and a fixed PID stays ("kept its own PID"). Every gift of the five games passes that check
under either HOME tracker setting (`tests/test_pokemon_service.py`).

The console receives a traded event Pokemon:

- the card's own trainer and language, where the card fixes them (Gavin's Palafin keeps OT Gavin and
  English);
- otherwise, the trainer a gift to the receiver names: the console's own save's
  ([Made for the receiving player](#made-for-the-receiving-player)), or, with that switch off, the
  app's trainer from Settings;
- with the card's trainer, or the app's, the console's player becomes its handler.

<a id="made-for-the-receiving-player"></a>
## Made for the receiving player

Made for the receiving player (`--for-receiver`, on by default in the app) makes the gift during the
trade for the console's own save, so the Pokemon is the player's as if their save had received the
card. It applies to a gift that names its receiver (Your OT in the list); one with its own trainer
goes as made. The app holds the switch off while every queued gift goes as made. A gift legal only
with a handler also goes as made: a save that receives a Pokemon whose OT is its own clears the handler
([What a trade rewrites](sv.md#what-a-trade-rewrites)), and PKHeX then refuses HOME's Sprigatito,
Fuecoco, Quaxly, Chikorita, Tepig and Totodile ("Current handler cannot be the OT"). `gift_event`
marks such a card `handled`, and it goes with the trainer from Settings, whose copy the console's
player handles
([Mystery Gift - Simulated](gui.md#mystery-gift---simulated)). The app passes each offer's card as
`--gift-event KEY` (`command._args`).

At launch, the host asks `gift_event` for the card under a trainer no card names
(`receiver_gift.PROBE`): the copy carries that trainer only where the card names its receiver
(`your_ot`). This also starts the service before the console arrives. The five hosts share
`pokeldn.receiver_gift`, whose `ReceiverGift` takes the place of the online partner a host already
trades with ([In a launcher](online.md#in-a-launcher)).

<a id="whose-save-it-is"></a>
### Whose save it is

The trainer comes from the Pokemon the console offers, when its save caught it: still with its
original trainer (handler 0), from one of the game's versions, and not an egg. That record gives the
OT name, the 16-bit TID and SID, the OT gender, the language and the version
(`receiver_gift.own_trainer`). The service reads it from the offer on a worker thread, never on the
host's loop (`Service.owner`); Scarlet/Violet's is read in Python (`receiver_gift.sv_owner`).

| game | Your OT cards | the console's offer | versions |
|---|---|---|---|
| Let's Go | Meltan (1501), Melmetal (1502), both for Simplified Chinese saves alone; Mew (2001) | kind 2 + 2r in trade r, an encrypted 232-byte PB7 | 42 Pikachu, 43 Eevee |
| Brilliant Diamond/Shining Pearl | HOME's Turtwig, Chimchar, Piplup (9015 to 9017) | 0x13, an encrypted 328-byte PB8 | 48 Brilliant Diamond, 49 Shining Pearl |
| Legends Arceus | HOME's Rowlet, Cyndaquil, Oshawott (9018 to 9020) | selector 4, an encrypted 376-byte PA8 | 47 |
| Scarlet/Violet | 9 cards, Mew (1521) and Pikachu (1501) among them | the 348-byte body of `80 00 02 00` ([The record a trade message carries](sv.md#the-record-a-trade-message-carries)) | 50 Scarlet, 51 Violet |
| Legends Z-A | Charizard (1607), Ralts (1601) | the 354-byte pick | 52 |

When the offer names no one, the console's own session data does. Each game sends its save's trainer
before any Pokemon, and the host passes it on (`receiver_gift.hear`):

| game | the console's message | what it names |
|---|---|---|
| Let's Go | kind 1, the save's MyStatus block ([Kind 1](lgpe_session.md#the-games-messages-on-the-reliable-protocol), `pb7.first_trainer`) | id pair, version, gender, language, name |
| Brilliant Diamond/Shining Pearl | 0x24 `TradeTranerData`, as the trade opens ([The Pokemon](bdsp_trade.md#the-pokemon), `room.traner_trainer`) | id pair, version, language, name |
| Legends Arceus | its 0x81 data exchange record, the save's MyStatus block ([The game's reader](pla.md#the-games-reader-and-the-pre-handler-phase), `data_exchange.read_trainer`) | id pair, version, gender, language, name |
| Scarlet/Violet | record 1 of its identity block, on the 0x81 port of its station index ([The records](sv.md#the-records), `sv_host.identity_chunk`, `reference.identity_trainer`) | id pair, version, gender, language, name |
| Legends Z-A | the 1400 identity ([The game's own exchange](za.md#the-games-own-exchange), `reference.identity_trainer`) | id pair, gender, language, name |

Brilliant Diamond/Shining Pearl's session never names the gender: the Union Room answers no request
for the 0x05 trainer card that carries it, and the join's avatar follows the save's sex only once the
player has used the Union Room's optional appearance counter; until then the save gets a random
avatar of either sex when it first connects ([The model](bdsp_protocol.md#the-model)). The offered
Pokemon names it instead: as its original trainer when the save caught or bred it, and as its handler
when the save received it from another trainer. The game writes the save's name, gender and language
as the handler on every such receipt, eggs included
([What the console does to a received Pokemon](bdsp_trade.md#what-the-console-does-to-a-received-pokemon)).

A field the session lacks comes from the offered Pokemon when it is this save's:

- from its original trainer, while it is still with that trainer (handler 0) and that trainer's name
  and id pair are the session's, as on an egg the save bred;
- from its handler, once it came from another trainer (handler 1) and its handler name is the
  session's.

Otherwise it comes from the trainer from Settings. Legends Arceus and Legends Z-A have one version,
which the session need not name. The log names each field taken elsewhere: `[gift] the console's
Pokemon ... cannot name the save: it is an egg; the session does (gender from the Pokemon's original
trainer)`. A Pokemon the save caught still outranks the session: offered in a later trade, it
names the save, and a copy made for the session's trainer is made again.

`gift_event` makes the card for the save on its version alone (`"only_version"`), and refuses a card
no save like it received ([Saves a card reached](#saves-a-card-reached)): Let's Go's Meltan and
Melmetal (1501, 1502) for any save not in Simplified Chinese. HOME's Turtwig, Chimchar and Piplup
are Brilliant Diamond's, whatever the save.

<a id="the-trade"></a>
### The trade

The trade runs as an online one does ([Online](online.md)):

1. The console offers first. Nothing goes up before it does.
2. A Pokemon that names no one, such as one received in a trade, leaves the save to the session. A
   Pokemon the save caught, offered in a later trade, still names it in the session's place. With
   neither, the gift goes as the app made it, under the trainer from Settings: the host logs why
   (`[gift] the console's Pokemon ... cannot name the save`) and asks the app for a pop-up
   ([Pop-ups](gui.md#pop-ups)), once for each reason, and the next trade asks again.
3. Once the save is known, `gift_event` makes the card for it. On a worker thread, the copy then
   takes the checks the host's own offers took at launch: the offer check with the host's New PID
   each run and edits (`pokemon.prepare_offer`, with PKHeX's legality check under the HOME tracker
   setting), then the host's own loader.
4. The copy goes up once the console has offered in that trade, and stays up until the trade ends. A
   cancel from the host is unmeasured.
5. The host confirms after the console does.

| game | loader | what it checks |
|---|---|---|
| Let's Go | `lgpe_host.boxed` | an encrypted 232-byte box structure whose checksum and sanity word hold, as a `--next-offer` needs |
| Brilliant Diamond/Shining Pearl | `bdsp.pokemon.build_from` | the encrypted PB8 |
| Legends Arceus | the trade box's `box_offer` | its edits, then PKHeX's check of the encrypted record (`pokemon.validate`) |
| Scarlet/Violet | `trade.load_offer` | the 348-byte body a trade message carries |
| Legends Z-A | `za_host.gift_offer` | a 354-byte offer that decrypts; a `--trade-offer` that does not goes as a Bad Egg, a gift never |

A card PKHeX cannot make for the save, or a copy that fails a check, goes as the app made it too; the
log (`[gift] could not be made ...`) and a pop-up say why. The pop-up names the save, its ID and its
version, and where the copy stopped (`receiver_gift.maker`):

| where | the reason reads |
|---|---|
| the card | the save cannot have received the card: card 1502 gave it in Simplified Chinese alone, never to a save in English |
| PKHeX | PKHeX made an illegal ... from card ...: its check's findings |
| the offer check | the copy fails the host's offer check: ... |
| the loader | the host cannot send the copy: ... |

Scarlet/Violet, Legends Arceus and Legends Z-A give each console its own `ReceiverGift`, so one
console's save never names another's gift; Let's Go and Brilliant Diamond/Shining Pearl host one
console. A later trade in the same seat is made as soon as the trade before it completes, for the save
already known. The last gift serves every later trade, made afresh, as a host's last offer does.

On retail consoles of all five games, the gift came with the save's own trainer whether the console
offered a Pokemon the save caught or one it received in a trade, which left the save to the session;
on Scarlet/Violet, one received in an online trade too. On a retail Violet, a Pokemon that had been to
Pokemon HOME and back named the save, and a Pokemon from a Surprise Trade named no one. The gift traded
back came with handler 0 and no handler name, as the save's own catch does
([What a trade rewrites](sv.md#what-a-trade-rewrites)): it names the save in turn.

<a id="other-games"></a>
## Other games

FireRed and LeafGreen receive event Pokemon through their own Mystery Gift:
[Event Pokemon](frlg_gift.md#event-pokemon) sends a fresh Gen 3 distribution through the Mystery
Event `givepokemon`. Sword and Shield take real cards over local wireless
([Official event cards](swsh_gift.md#official-event-cards)).

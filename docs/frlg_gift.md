---
title: Mystery Gift
parent: FireRed and LeafGreen
nav_order: 2
---

# Mystery Gift

The Mystery Gift menu needs no Pokemon Center. A console on the Wonder Cards screen accepts a Wonder
Card, a delivery script, Wonder News, a visiting Battle Tower trainer, and a Pokemon straight into the
party. The Mystery Event VM and native ARM code are on [Code on the console](frlg_rom.md).

## The session

The console's client boots with `{CLI_RECV, MG_LINKID_CLIENT_SCRIPT}, {CLI_COPY_RECV}`
[mystery_gift_scripts.c:15] and executes whatever `MysteryGiftClientCmd` array it receives
[mystery_gift_client.c:87]. It understands the whole opcode set, so a host can drive flows beyond
FireRed's two ROM server scripts.

    console joins  ->  SEND_PLAYER_IDS  ->  LinkPlayer block exchange  ->  one standby barrier
                                                                              |
      server -> CLIENT_SCRIPT (sClientScript_SendGameData, 32 B)
      client -> GAME_DATA     (MysteryGiftLinkGameData, 96 B)   -- validated, card flag compared
      server -> CLIENT_SCRIPT (sClientScript_SaveCard, 48 B)
      server -> CARD          (struct WonderCard, 332 B)
      server -> RAM_SCRIPT    (1024 B: the delivery bytecode, zero-padded)
      client -> READY_END     (1024 B)
                                                                              |
                                              close-link handshake  ->  disconnect

The host issues one LinkPlayer block request, waits for the console's valid block, sends its own,
then waits for the standby barrier.

### Two framing rules that are easy to get wrong

Size 0 means 1024: `MysteryGiftLink_InitSend` [mystery_gift_link.c:55] expands it to
`MG_LINK_BUFFER_SIZE`, and `SVR_COPY_SAVED_RAM_SCRIPT` never sets `ramScriptSize`
[mystery_gift_server.c:275], so the RAM script and `CLI_SEND_READY_END` are full 1024-byte messages.
The CRC covers the padded buffer.

Block pacing has no acknowledgement. `SEND_BLOCK_INIT` is ignored unless the receiver's slot is
`RECV_STATE_READY` [link_rfu_2.c:1146], restored only by the console's `MGL_ResetReceived`. The
parent's own `MGL_HasReceived` flag is set at once [link_rfu_2.c:1044]; the four-VBlank countdown
[link_rfu_2.c:1220] applies only to child blocks. `MysteryGiftTiming.inter_block_gap_frames` is 36:
the console model takes up to 13 frames per block with nothing dropped, 16 before the transfer dies. A
dropped block leaves the console waiting forever. Stalls while the console sends follow
[the mirror rule](frlg_link.md#row-one-of-the-parents-table-is-the-consoles-own-command-mirrored-back).

### Modules

Under `pokeldn/frlg/gift/` unless stated:

| file | role |
|---|---|
| `mg_link.py` | framing: 6-byte `{ident, crc, size}` header block + ≤252-byte chunks |
| `mg_script.py` | client-script assembler, the decomp's canned scripts, `MysteryGiftLinkGameData` reader |
| `mg_server.py` | server-script interpreter (`SVR_*`) |
| `host_mystery_gift.py` | leader engine: `tick()` → parent gSendCmd, `feed_child_slot()` ← child row |
| `host_mg_app.py` | application hooks over the host runtime |
| `wonder_card.py` | byte-exact Celebi and legendary-beast card/RAM-script builders |
| `stamp_rally.py` | Stamp Rally card, stamps, activation wrappers, delivery script |
| `gift_composer.py` | action definitions, cursor-state validation, RAM-script compiler |
| `gift_registry.py` | the catalog |
| `gift_to_bin.py` | `.bin` exporter for external Gen-3 Mystery Gift tools |
| `pokeldn/frlg/save/save_inject.py` | save injection with card, RAM-script and sector checksums |
| `bin/frlg_mg_host.py` | the CLI |

## Running it

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --phy auto \
               --keys PROD_KEYS --gift beast-cutscene --flag-id 1005
    (them) join the host when it appears; YES on the replace-card prompt if one shows

Radio setup: [The ESP32 radio](hardware_esp32.md). `bin/frlg_mg_host.py` serves one console per run
and stops once it has left LDN ([Host implementation](frlg_host.md), Shutdown and cleanup); a second
console needs a new run. `tests/test_mystery_gift_flow.py` models the block-receive gate, `MGL_Receive` and one client command
per frame; `tests/test_mystery_gift_end_to_end.py` adds an impaired Reliable/RFU path.

## What the link can carry

Three of the 22 client instructions [include/mystery_gift_client.h:18] execute something:

| instruction | what the console does |
|---|---|
| `CLI_SAVE_RAM_SCRIPT` (17) | stores a field script; it runs on the next NPC interaction |
| `CLI_RUN_MEVENT_SCRIPT` (15) | runs a Mystery Event bytecode script, a second VM with its own 17-opcode table |
| `CLI_RUN_BUFFER_SCRIPT` (21) | `func = (void *)gDecompressionBuffer; func(&param, gSaveBlock2Ptr, gSaveBlock1Ptr)`; up to 1024 bytes of ARM executed with both save-block pointers |

## The one RAM script slot

A console holds a Wonder Card or a bound RAM script, never both. `ValidateSavedWonderCard` checks the
card CRC, `ValidateWonderCard`, then `ValidateRamScript` [mystery_gift.c:186], which requires
`magic == RAM_SCRIPT_MAGIC`, map group and number `MAP_UNDEFINED`, and `objectId == 0xFF`
[script.c:538]. The field runs a RAM script through `GetRamScript(gSpecialVar_LastTalked, script)`
[field_control_avatar.c:458], which requires the coordinates of the object talked to.
`CLI_SAVE_RAM_SCRIPT` calls `InitRamScript_NoObjectEvent` (MAP_UNDEFINED, 0xFF [script.c:578]); the
Mystery Event VM's `initramscript` writes real coordinates. With a bound script the card stays in the
save with a good CRC, but the menu hides it and `MysteryGift_LoadLinkGameData` reports `flagId` 0
[mystery_gift.c:349] (`HAS_NO_CARD`).

The next Wonder Card rebinds the slot (`magic` stays 51, coordinates 0xFF) and the card comes back; a
buffer script sends no card and leaves the slot alone. An ordinary card delivered over a bound script
rewrites the card at +0x32E0 and the RAM script at +0x361C, both in one save sector, and nothing in
SaveBlock2; measured, 564 of the 15872 bytes of SaveBlock1 differed.

The slot's checksum (`ramScript.checksum`, SaveBlock1 + 0x361C) is `CalcCRC16WithTable` over
`sizeof(RamScriptData)`, which is 1000 bytes: the 999 declared bytes and one padding byte that
`InitRamScript` zeroes first [script.c:500]. `CalculateRamScriptChecksum` passes `250 << 2`
(`0x0806D43C` BPRE, `0x0806D5A0` BPRF). Every game-written slot read back carries the 1000-byte CRC. A
slot whose CRC covers only 999 bytes is wiped by `GetRamScript` the first time its object is talked to
[script.c:526].

## The gift catalogue

`--gift NAME`; `--help` lists flag ids (1000..1019). Only the held card matters: the same id means
"already has this card" (`MysteryGift_CompareCardFlags`).

| gift | what it does |
|---|---|
| `beast-cutscene-share` | the repeatable legendary-beast cutscene; the default demo card |
| `celebi` | the composed level-50 Celebi card |
| `porygon-tm-gift` | a Porygon card, a Clefairy scene, TM29 Psychic then TM46 Thief |
| `solrock-stamp` / `lunatone-stamp` | the two halves of one Stamp Rally card |
| `altering-cave` | the official Altering Cave event, ported |
| `wish-egg`, `pokepark-egg`, `pc-japan-egg` | the official distribution eggs; see Distribution eggs |
| `event-pokemon` | a Gen 3 distribution Pokemon, straight into the party; see Event Pokemon |
| `starter-egg` | an egg of one of the nine first partners, drawn by `random` |
| `rare-berries` | an Enigma, a Lansat and a Starf Berry, one stage each |
| `national-dex` | `EnableNationalPokedex` (special 367) unless `IsNationalPokedexEnabled` (403) answers 1 |
| `nature-mint`, `pc-anywhere` and 42 more | the GB-Link Team cards; see GB-Link Team cards |
| `battle-count-card` | the official Battle Count Card |
| `visiting-trainer` | a Battle Tower trainer as ident 26 (FireRed only) |
| `mystery-event-probe` | `givenationaldex; setstatus 42; checksum`, the VM's own self-test |
| `mystery-event-celebi` | `givepokemon`: a Lv30 Celebi holding mail, straight into the party |
| `mystery-event-npc` | `initramscript`: binds a field script to the Pallet Town fat man |
| `rng-seed-reader`, `rng-rate-probe`, `rng-shiny-hunt`, `rng-mon-hunt`, `rng-mon-hunt-both`, `rng-mon-hunt-log` | see [the RNG](frlg_rng.md) |

A console already holding the card takes a Mystery Event gift alone, with no prompt.

### The legendary beast

A deliveryman cutscene gives the Lansat and Liechi Berries, then a Master Ball, then starts a wild
level-65 legendary beast battle chosen by the save's starter:

| starter | beast |
|---|---|
| Bulbasaur | Suicune |
| Squirtle | Entei |
| Charmander | Raikou |

The saved script stays, so the event repeats.

### Porygon TM gift

A Porygon-icon card, a Clefairy sprite three tiles to the player's right facing west, TM29 Psychic
then TM46 Thief, with separate delivery checkpoints so retrying Thief cannot duplicate Psychic.
Default flag id 1007; the viewer shows `7` top right (`flag_id % 100`).

### The Stamp Rally

Two events share one `SUN AND MOON RALLY` card (Claydol icon, two stamp slots, displayed number `6`,
flag id 1006), received in either order.

| state | meaning |
|---|---|
| `VAR_MYSTERY_GIFT_1` | Celebi completion cursor |
| `VAR_MYSTERY_GIFT_2 = 0/1/2` | Solrock absent / active / received |
| `VAR_MYSTERY_GIFT_3 = 0/1/2` | Lunatone absent / active / received |
| `FLAG_MYSTERY_GIFT_DONE` | rally completion |
| card receipt flag | synchronized when Celebi succeeds |

Each stamp earns a level-30 Solrock or Lunatone; both earn a level-50 Celebi, all by plain `givemon`.
Party or PC counts; if both are full nothing advances. Two pending stamps deliver all three at once.

```text
matching =
    saved flag ID == distribution flag ID
    and max stamps == 2
    and metadata icon species == CLAYDOL

if no card:                install shared card + delivery script + selected stamp, run activation
else if not matching:      offer the toss prompt; on accept, install as above
else if stamp species or ID already exists:   HAS_STAMP, no activation
else if neither slot empty:                   NO_ROOM_STAMPS, no activation
else:                      save the stamp, run activation, STAMP_RECEIVED
```

The activation is a Mystery Event wrapper (`runscript` plus an embedded field script). Stamps are
live-host-only. `IsStampInMetadata` [mystery_gift.c:272] rejects a stamp whose id or species
collides (maximum 7). `CLI_SAVE_STAMP` writes only `cardMetadata.stampData` [mystery_gift.c:307],
avoiding the card wipe of `CLI_SAVE_CARD`.

### Altering Cave

The official script [data/mystery_event_msg.s:325]: `addvar VAR_ALTERING_CAVE_WILD_SET, 1`, a wrap
at 10 [:328], a message; it ends in `end`, so each talk advances one set. The reader clamps 9 and
above to table 0 [wild_encounter.c:192]. The var (0x4024) is at SaveBlock1 + 0x1048:

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x1048 --dump-size 2

Three talks set it to 3, and GROTTE METAMO (Six Island) then draws from table 3
`sSixIslandAlteringCave_4_FireRed` [src/data/wild_encounters.json] (a level-16 Houndour on retail
FireRed).

| var | species | | var | species |
|---|---|---|---|---|
| 0 | Zubat | | 5 | Aipom |
| 1 | Mareep | | 6 | Shuckle |
| 2 | Pineco | | 7 | Stantler |
| 3 | Houndour | | 8 | Smeargle |
| 4 | Teddiursa | | | |

### Distribution eggs

Three Japanese distributions, ported from the bytes GB-Link-Switch-LDN carries (`web/js/gift/official.js`).
Each card holds every egg of its distribution and the console picks one with `random` [scrcmd.c:455];
the egg gets the distribution's four moves, the fateful-encounter bit and met location 0xFF, as the
original scripts set them. A full party refuses before the draw and the card stays open.

| card | eggs |
|---|---|
| `wish-egg` (Pokemon Center New York) | Chansey, Drowzee, Exeggcute, Farfetch'd, Kangaskhan, Lickitung; each knows Wish |
| `pokepark-egg` (PokePark Market Fantasia) | Cacnea, Corphish, Corsola, Igglybuff, Minun, Pichu, Plusle, Psyduck, Skitty, Spinda, Spoink, Surskit, Taillow, Whismur, Wynaut |
| `pc-japan-egg` (Pokemon Center Japan) | Bellsprout (Teeter Dance), Meowth (Petal Dance), Oddish (Leech Seed), Poliwag (Sweet Kiss) |

On the French FireRed ROM under mGBA, each card bound to the mother gave its egg with the listed moves,
`modernFatefulEncounter` 1 and met location 0xFF; four delays drew Whismur, Minun, Corphish and
Psyduck from the PokePark card.
On a retail French FireRed the PokePark card was received and saved, and the delivery man gave an egg
whose summary read "Drôle d'ŒUF de POKéMON obtenu dans un bel endroit.", the line the summary screen
picks for met location 0xFF or the fateful-encounter bit [pokemon_summary_screen.c:2799].

### Event Pokemon

`--gift event-pokemon --event-pokemon NAME` sends a fresh copy of a Gen 3 distribution: PKHeX.Core
makes it from its own event table (`EncounterGift3`, the non-egg, non-Japanese entries) by that
event's PID/IV method, with its trainer name, trainer id, level, moves, held item, ribbons and
fateful-encounter bit, and its legality check must pass. The record goes into the party through the
Mystery Event `givepokemon` the moment the card is saved, as `mystery-event-celebi` does; a full party
answers status 3 and gets nothing, and the card can be received again. Without `--event-pokemon`
the card sends a stored WISHMKR Jirachi.
On a retail French FireRed a WISHMKR Jirachi made this way arrived in the party with trainer WISHMKR,
id 20043, after `givepokemon` answered status 2.

`NAME` is the trainer name, a space and the species: `WISHMKR Jirachi`, `CHANNEL Jirachi`,
`Aura Mew`, `MYSTRY Mew`, `DOEL Deoxys`, `SPACE C Deoxys`, `ROCKS Metang`, `10 ANIV Pikachu` and every
other `10 ANIV` species, the European `10ANNIV`, `10JAHRE`, `10ANNI` and `10ANIV` releases. Where an
event was released in several languages, the one matching `--language` is sent.

### GB-Link Team cards

The GB-Link Team's custom Wonder Cards (GB-Link-Switch-LDN `cards/`, GPL-3.0) are a Wonder Card plus a
delivery-man RAM script that carries THUMB code, called through `callnative`. Their ARM sources are in
`vendor/gblink-cards/`; `scripts/gen_team_cards.py` assembles them for the four cartridges into
`pokeldn/frlg/data/team_cards.json`, and `pokeldn/frlg/gift/team_cards.py` registers each card under its
id without `custom-` (`--gift nature-mint`). With their unmodified sources and their RAM addresses the
generator reproduces their own `BPRE 1.10` payloads byte for byte, all 44 of them.

`starter-egg`, `rare-berries` and `national-dex` are their three cards that need no native code,
rebuilt with the composer: on the French FireRed ROM under mGBA the berries landed in the Berries pocket
(items 173, 174, 175), the starter card gave a Chikorita egg, and the National Pokedex card set
`FLAG_SYS_NATIONAL_DEX` (0x840) again after it was cleared in RAM. Their event Pokemon come from PKHeX
(see Event Pokemon) except the four PKHeX's table leaves out; their follower, Master Ball, speed-up and
encounter hooks are covered by this project's own.

| group | cards |
|---|---|
| change a Pokemon | `nature-mint`, `ability-capsule`, `poke-ball-changer`, `pokemon-gender`, `nickname`, `stat-judge`, `hidden-power`, `hidden-power-type`, `ev-training`, `friendship`, `pp-max`, `max-conditions`, `pokerus`, `unown-letters`, `trade-evolution`, `espeon-umbreon`, `move-tutor` |
| per-frame hooks | `speed-2`, `speed-3`, `speed-4`, `speed-0-75`, `speed-0-5`, `fast-text`, `travel-anywhere`, `pc-anywhere`, `hm-moves`, `reusable-tms`, `physical-special-split`, `exp-share`, `shiny-hunting`, `roamer` |
| other | `no-encounters`, `legendary-respawn`, `instant-eggs`, `gift-box`, `pocket-casino`, `gift-ribbons`, `trainer-ids`, `gender-swap`, `rival-name` |
| event Pokemon | `box-eggs`, `colosseum-pikachu`, `ageto-celebi`, `mattle-ho-oh` |

What differs from their build:

- French cartridges. The 167 addresses the sources take are found on `BPRF`/`BPGF` from the English
  symbol tables: a function by unique byte windows of its body, RAM and pointer-bearing data by the
  literal pools of mapped functions, a field-script label by its script's start with pointers masked.
  `vendor/gblink-cards/symbols.json` holds all four; `tests/test_team_cards.py` checks 25 of them
  against `builds.py` on every cartridge. Each script checks the header's game letter, language letter
  and revision, so a payload sent to another cartridge only says the gift does not work.
- The relocated script (996 bytes) and the menu list (80 bytes) go to `0x0203F768` and `0x0203FB50`,
  newlib's malloc state, instead of `0x0203FC00`, where this project's resident hooks run; see
  [Where a payload can live](frlg_rom.md#where-a-payload-can-live).
- The hook cards' installers point `gIntrTable[4]` at `VBlankIntr` before their copy, chain to it
  rather than to the handler they find, and store it at `0x0203FBFC`, where this project's resident
  installs look. A hook card replaces a running game boost and the reverse; neither chains to a stale
  copy. Their state is at `0x0203FF60`, their copy ends below it.
- Their ids above 1019 have no `sReceivedGiftFlags` bit; the registry sends 1000 + the card's id
  number mod 20 for those.
- Two texts are four and six characters shorter (`hm-moves`, `physical-special-split`) to fit 995
  bytes after the installer change.

Every card was run bound to Mom under mGBA on all four cartridges, its dialogue answered with A. On the
French FireRed the native code drew French menus (stat, Poke Ball and type names from the ROM), changed
the party (nature `HARDI`, gender, Hidden Power to `COMBAT` 70, maximum EVs), opened the move relearner
and the slot machine, and `trainer-ids` read TID 50425 and SID 50923 off the save; R after
`pc-anywhere` opened the boxes. The other three cartridges drew the same screens, pixel for pixel on
French LeafGreen. A LeafGreen payload on a FireRed answered "This gift doesn't work with this version
of the game." With a resident hook running, `nature-mint` left `0x0203FC00..0x02040000` untouched and
`pc-anywhere` took over `gIntrTable[4]` with `0x0800071D` kept at `0x0203FBFC`.

`colosseum-pikachu` and `ageto-celebi` carry their Japanese trainer names, which a European cartridge
draws as dots; PKHeX reports all four event Pokemon legal.

### The Battle Count Card

`MysteryEventScript_BattleCard` [data/mystery_event_msg.s:162] reads `GET_CARD_BATTLES_WON` through
`GetMysteryGiftCardStat` (special 390) and gives a POTION at exactly three. The port replaces the
official `FLAG_MYSTERY_GIFT_DONE` gate with its own prize var, so it stays repeatable.

The partner arms the counters: `Task_ExchangeCards` arms `MysteryGift_TryEnableStatsByFlagId` only if
the u16 after the 96-byte trainer card in the `BLOCK_REQ_SIZE_100` buffer equals the held card's flag
id [union_room.c:1777], on entry to the trade centre or colosseum (`frlg_trade_host.py
--card-flag-id N`).

| what increments | where | the rule |
|---|---|---|
| `numTrades` | a completed trade [trade_scene.c:2609] | a trainer id the card has not counted |
| `battlesWon` / `battlesLost` | the end of a cable club battle [cable_club.c:792] | the same, 5 ids remembered per stat |

`IncrementCardStatForNewTrainer` [mystery_gift.c:630] counts each trainer id once. The Union Room
battle returns through `CB2_ReturnToField` and counts nothing; only
[the colosseum](frlg_link.md#the-cable-club-colosseum) does. The counters sit at SaveBlock1 + 0x3434
(`buffer_script.SAV1_CARD_METADATA`), read with no CRC check [mystery_gift.c:490]:

    0x3434: 0000 0000 0000 2300     battlesWon 0, lost 0, trades 0, icon 35 (CARD_TYPE_GIFT)
    0x3434: 0000 0000 0100 2300     trades 1                       (CARD_TYPE_LINK_STAT)

A `CARD_TYPE_GIFT` card stays at zero even when armed. The wireless club's trade centre goes through
`union_room.c`'s `Task_StartActivity`, the only builder that writes the flag id at offset 96.

### The visiting trainer

`CLI_RECV_EREADER_TRAINER` (18, ident `MG_LINKID_EREADER_TRAINER` = 26) copies the buffer into
`gSaveBlock2Ptr->battleTower.ereaderTrainer` and calls `ValidateEReaderTrainer`
[mystery_gift_client.c:233]. The struct is 188 bytes [global.h:286]:

    0x00 u8  unk0                  0x10 u16 greeting[6]            0x34 BattleTowerPokemon party[3]
    0x01 u8  trainerClass          0x1C u16 farewellPlayerLost[6]  0xB8 u32 checksum
    0x02 u16 winStreak             0x28 u16 farewellPlayerWon[6]
    0x04 u8  name[8]
    0x0C u8  trainerId[4]

Validation: the first 46 words not all zero, the trailing u32 their sum [battle_tower.c:1354, :1384];
a failure is cleared silently. `SevenIsland_House_Room1` gates only on it: the old woman offers a 3v3
in Room2, built by `CreateBattleTowerMon` from the struct [battle_tower.c:928], healed after,
repeatable. The level rule and banlist (`ShouldBattleEReaderTrainer` [:232]) are never called here.

`CreateBattleTowerMon` sets species, item, four moves (PP from the move table), level, ppBonuses,
EVs, IVs, abilityNum, otId, personality, nickname, friendship. The phrases are six Easy Chat words;
`farewellPlayerWon` is said when the player wins. FRLG shows five of the eight name bytes
[`CopyEReaderTrainerName5`, battle_tower.c:1343]. `CLI_MSG_TRAINER_RECEIVED` (12) [strings.c:1296]
counts as success, so the console saves.

`--gift visiting-trainer` sends card, RAM script and trainer in one session: no card → all three; the
same card → the trainer alone, no toss prompt; another card → the toss prompt, then all three.

## Wonder News

The Mystery Gift menu is {Wonder Cards, Wonder News} x {Wireless Communication, Friend}.
`struct WonderNews` [global.h:646] is 444 bytes and carries no identity:

| offset | size | field | notes |
|---|---|---|---|
| 0x000 | 2 | `id` | the only thing `ValidateWonderNews` checks: it must not be 0 [mystery_gift.c:113] |
| 0x002 | 1 | `sendType` | `SEND_TYPE_DISALLOWED` hides the console's own "Send" option [mystery_gift.c:120] |
| 0x003 | 1 | `bgType` | not validated; `WonderNews_Init` clamps `>= NUM_WONDER_BGS` to 0 [mystery_gift_show_news.c:110] |
| 0x004 | 40 | `titleText` | centred in a 224 px window |
| 0x02C | 400 | `bodyText[10][40]` | eight lines are on screen; a non-empty line past index 7 arms the scroll indicator [:346] |

News has no `flagId`, metadata, RAM script or receipt flag, and never consults
`sReceivedGiftFlags`. `IsWonderNewsSameAsSaved` [mystery_gift.c:140] compares all 444 bytes, so one
changed byte makes old news new (`--news-id N`). Against the Wonder Card host:

- The News accept list holds one activity [`sAcceptedActivityIds_WonderNews`,
  src/data/union_room.h:406]: `build_wonder_news_app_data` advertises 22, not 21. The `hasNews` bit
  matters only on the Wireless path [union_room.c:3777].
- The console answers with `MG_LINKID_RESPONSE` (ident 19) [mystery_gift_client.c:210]: `FALSE` =
  saved, `TRUE` = already held. `sServerScript_SendNews` [mystery_gift_scripts.c:126] ends in
  `SVR_MSG_HAS_NEWS` on `TRUE` and otherwise runs `sClientScript_NewsReceived`, which saves and sets
  the reward. `SCRIPT_SEND_WONDER_NEWS` drops its leading `SVR_COPY_SAVED_NEWS`.
- No card check, toss prompt or RAM script: news and cards never displace each other.

News from a Friend rolls a berry between `ITEM_RAZZ_BERRY` and `ITEM_NOMEL_BERRY`
[mystery_gift_menu.c:1367, wonder_news.c:21], given by the man in `CeruleanCity_House4`: up to five,
then 500 steps [`MAX_REWARD`]. The four-berry reward needs `WONDER_NEWS_RECV_WIRELESS`, a closed path.

`--news` (`--news berry`, `--news-id N`); the player picks Wonder News, "input one?", Friend (a
console holding news shows it: A, then Receive). One session (about 18 s):

    ident 16  sClientScript_SendGameData
    ident 17  MysteryGiftLinkGameData
    ident 16  sClientScript_SaveNews
    ident 23  MG_LINKID_NEWS - 444 bytes in three blocks
    ident 19  MG_LINKID_RESPONSE - FALSE: the console saved it
    ident 16  sClientScript_NewsReceived
    ident 20  READY_END                              -> SVR_MSG_NEWS_SENT

## The questionnaire as a password gate

`SVR_CHECK_QUESTIONNAIRE` compares the four Poke Mart questionnaire words in order
[`MysteryGift_DoesQuestionnaireMatch`, mystery_gift.c:422] into `param` for `SVR_GOTO_IF_EQ`; no ROM
server script uses it. `mg_server.gate_on_questionnaire(script)` splices it after the game-data
prefix:

    MysteryGiftServer(card, ram_script, questionnaire=phrase, denied_message="Say the words.")
    bin/frlg_mg_host.py --gift ... --questionnaire species:55,FEELINGS/60,move:177,why

A word may be an English name, `species:N`, `move:N`, `GROUP/INDEX`, or a raw id. A wrong phrase gets
the host's 64-byte message through `CLIENT_SCRIPT_DYNAMIC_ERROR` and `SVR_MSG_NOTHING_SENT`; nothing
is sent or tossed. Test the refusal first: a passing gate looks like an unwired one.

French word ids are read off a console: every session ships the four words in
`MysteryGiftLinkGameData` [mystery_gift.c:361] and the host logs them.

    questionnaire: POKEMON/55  done [FEELINGS/60]  MOVE_1/177  why [MISC/37]

for AKWAKWAK FURAX AEROBLAST POURQUOI: `EC_GROUP_POKEMON` indexes by species (Golduck, 55),
`EC_GROUP_MOVE_1` by move id (Aeroblast, 177), and the English table is right about MISC/37 and wrong
about FEELINGS/60. See [the French Easy Chat vocabulary](frlg_rom_map.md#the-french-easy-chat-vocabulary).

## What the console volunteers about itself

Every session's `MysteryGiftLinkGameData` carries the Easy Chat profile and the card stats
(`CARD_STAT_BATTLES_WON` / `_LOST` / `_NUM_TRADES` / `_NUM_STAMPS`) [mystery_gift.c:361].
`--game-data-log PATH` (`pokeldn/frlg/gift/game_data_log.py`) appends each session to a JSONL ledger
and prints what moved since that console's last one; `tools/frlg/game_data_read.py PATH` reads it. A
counter is evidence only as a difference on the same card flag id. The ledger names every word id
the French Easy Chat table lacks.

## Authoring gifts

`pokeldn.frlg.gift.gift_composer` builds cards and deliveryman scripts from immutable `WonderGift`
definitions:

```python
MEWTWO_GIFT = WonderGift(
    slug="mewtwo-encounter",
    card=WonderCardSpec(icon_species=150, title="MYSTERIOUS ENCOUNTER",
                        body=("Visit the deliveryman.",), default_flag_id=1008),
    intro_message="A powerful presence is waiting!",
    event=GiftSpec(shareable="once"),          # or StampRallySpec(...)
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(Message("Take this."), GiveItem(1)),  # Master Ball
        DeliveryStage(ShowSprite(0, RelativeToPlayer(dx=1)), BattleLegendary(150, level=70)),
    )),
    completed_message="That mysterious encounter is over.",
)
```

`GiftSpec` holds repeatable and shareable; `StampRallySpec` rally slots and completion hooks. A
`DeliveryPlan` has three sequences: `WonderGift.delivery` uses `delivery`; `StampSlot.delivery` and
`StampRallySpec.completion` use `pre_stages` and `post_stages`; anything else is rejected.

The compiler shows `intro_message`, resumes the stages from `VAR_MYSTERY_GIFT_1`, and on success sets
`FLAG_MYSTERY_GIFT_DONE` and the card receipt flag. A later visit shows `completed_message`;
`GiftSpec(repeatable=True)` resets the cursor instead.

### Stages and conditions

Each `DeliveryStage` is one checkpoint: a failed reward re-offers that stage and skips the successful
ones before it. Never put two fallible rewards (`GiveItem`, `GivePokemon`, `GiveEgg`) in one stage.
`GiveEgg` takes the same `moves=(...)` as `GivePokemon`; a move-bearing egg needs a party slot, so a
full party retries later instead of sending it to the PC. A move of 0 after the first empties that
slot. `GiveRandomEgg(eggs)` takes `(species, moves)` pairs and gives one picked by `random`: a jump
table, so fifteen eggs with four moves each fit one RAM script (944 bytes).

`condition=` (`VarEquals`, `FlagSet`, `Not`, `AllOf`, `AnyOf`) skips a stage's actions when false but
still advances the cursor, for mutually exclusive branches. `RequireSpecialResult(...)` calls a field
special into `VAR_RESULT`, compares it, and on failure shows its message without advancing.

```python
DeliveryStage(ShowSprite(142, RelativeToPlayer(dx=1)),
              condition=VarEquals(0x4031, 0))  # VAR_STARTER_MON == Bulbasaur
DeliveryStage(BattleLegendary(243, level=65),
              condition=Not(AnyOf((VarEquals(0x4031, 0), VarEquals(0x4031, 1)))))
DeliveryStage(RequireSpecialResult(SPECIAL_HAS_ALL_KANTO_MONS, 1, "Finish the KANTO POKEDEX first."),
              GivePokemon(251, level=50))
```

### Writing the player's save

`SetVar(variable, value)` emits `setvar` (0x16) and `AddVar(variable, value)` emits `addvar` (0x17),
both restricted to a saved var (0x4000..0x40FF) or a special var (0x8000..0x8011).

### Battles

`BattleLegendary` emits `setwildbattle`, `special StartLegendaryBattle`, then `end` without
`waitstate`, so nothing resumes a RAM-script pointer after the battle moves SaveBlock memory ([a RAM
script may not come back from a battle](frlg_rng.md#a-ram-script-may-not-come-back-from-a-battle)).
`BattlePokemon` emits the ordinary `dowildbattle`. Either must be the last action of its stage.
Battles are prohibited in a stamp-slot path, including a rally's shared middle; conditional battle
stages are allowed as terminal alternatives.

### Sharing

`GiftSpec.shareable` maps to the Wonder Card `sendType` bits:

| value | behaviour |
|---|---|
| `"never"` | cannot be shared onward |
| `"once"` | can be shared once; the receiving game flips the card to not shareable |
| `"always"` | can continue to be shared after receipt |

### Event mons that look like event mons

`GivePokemon(..., fateful_encounter=True)` (and `GiveEgg`) emits the official Surf Pichu pair:
`setmonmodernfatefulencounter` (`0xCD`) and `setmonmetlocation` (`0xD2`, `METLOC_FATEFUL_ENCOUNTER` =
0xFF) [data/mystery_event_msg.s:71]. It is opt-in, so older cards are byte-identical.

`ScrCmd_setmonmodernfatefulencounter` does not bounds-check its index [scrcmd.c:2239] (`setmonmove`
clamps [script_pokemon_util.c:144]), so the composer's `LAST_PARTY_MON_INDEX` of 7 must not reach it.
The index is the party count before the give (`specialvar ... CalculatePlayerPartyCount`); a full
party jumps to the failure label, so a mon sent to the PC is never marked.

The summary screen's fateful-encounter line comes from the met location alone
[pokemon_summary_screen.c:2665, ORed at :2799]. `modernFatefulEncounter` is bit 31 of the
ribbon word at Misc+0x08 [include/pokemon.h:40-82]; `mon.decode_mon` reads it from a party dump.

### `initramscript` in the composer

`gift_composer.build_bound_script(actions)` compiles composer actions into the field script
`initramscript` binds; `build_mevent_npc_script(actions=...)` takes them directly. Same bytecode,
interpreter and `ramScript` slot, so items, mons, sprites and battles all work. There is no stage
cursor or receipt flag: the script ends in `end` and reruns whole, so a once-only effect needs its own
`SetVar` or condition.

### Registration and validation

```python
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
GIFT_REGISTRY.register_definition(MEWTWO_GIFT)
```

Registration validates and compiles the default flag id; a runtime `--flag-id` compiles again.
Validation covers card text and flags, plan structure, action ranges, cursor bounds, unique stamps,
battle placement, virtual pointers and the 995-byte RAM-script limit, naming the section:

```text
example-rally.event.slots[1].delivery.post_stages[0].actions[1]: battles are not allowed in stamp-slot delivery plans
```

## Static tools

```bash
./.venv/bin/python -m pokeldn.frlg.gift.gift_to_bin --gift beast-cutscene --flag-id 1005 --out-dir exported-gift
./.venv/bin/python -m pokeldn.frlg.save.save_inject game.sav --gift beast-cutscene --flag-id 1005
```

`gift_to_bin` writes a 336-byte Wonder Card and a 1004-byte RAM script as
`pokemon-gen3-mysterygift-tool` expects. `save_inject` writes both into the active save slot,
rebuilds the card CRC, RAM-script CRC and sector checksum, and saves `<save>.gift.sav` (`--in-place`
overwrites). `--make-artifact` writes a deterministic `.ram.lst` under `artifacts/` (bytes, decoded
instructions, checksums, targets, stage summary).

## Closed paths

### Wireless Communication (JoySpot)

Blocked at the RFU serial-number gate. Both paths reach the same gift conversation:

| | Friend | Wireless Communication |
|---|---|---|
| listener | `Task_ListenForCompatiblePartners` [union_room.c:3757] | `Task_ListenForWonderDistributor` [union_room.c:3799] |
| accepts RFU serial | `IsRfuSerialNumberValid` → `{0x0002, 0x7F7D}` | `== 0x7F7D` only [link_rfu_3.c:920] |
| selection | the player picks from a list | auto-connects, no button press |
| reachable from a Switch | yes | no |

`Task_CardOrNewsOverWireless` [union_room.c:2415] scans, waits 120 frames, then gates candidate 0:

1. `Rfu_GetWonderDistributorPlayerData` [link_rfu_3.c:917] keeps the candidate only if
   `partner[idx].serialNo == RFU_SERIAL_WONDER_DISTRIBUTOR (0x7F7D)`, else zeroes it.
2. `groupScheduledAnim == UNION_ROOM_SPAWN_IN && !startedActivity`.
3. `HasWonderCardOrNewsByLinkGroup`: the advertised `hasCard` bit; failing it plays SE_BOO.
4. `CreateTask_RfuReconnectWithParent(...)`.

A wrong serial fails gate 1 silently (no SE_BOO). The Switch bridge reports `0x0002`
(`RFU_SERIAL_GAME`): Friend (`sAcceptedSerialNos` [link_rfu_2.c:240]) lists every candidate and
Wireless ignores every one. The advertisement has no serial field; a native one is zero outside four
fields:

```
50 10 | c1 cc bf bf c8 ff 00 00 | 65 ac | 00 00 00 00 | 84 15 | 00 00 00 00 00 00
TID   | uname                   | parent| UNEXPLAINED | search| UNEXPLAINED
```

`svc_47` [sloopsvc.c:34] takes `{u8 HostRfuGameData[0x10]; u8 HostRfuUsername[8]}`, 24 bytes with no
serial, while the bridge writes the candidate list through `svc_45_rfu_link_status()`.

Advertisements that drew no 802.11 authentication from the Wireless path (21 tried): the scene id
(0, 21, 0x7F7D), LDN and Pia app versions, `0x7F7D` in both byte orders at offsets 12, 13, 14, 18,
19, 20, 22, the activity (0, 4, 21), `hasCard`, and the search word's bit 7. Held constant: `local_communication_id =
0x01006fa0233f8000`, LDN version 4, channel 1, `max_participants = 2`, Pia `sysCommVer = 22`, scene
22287.

`0x1584 & 0x7F = 4 = ACTIVITY_TRADE` in the native capture, and activity 21 at that offset gave a
Friend listing and a join, so the search word at `record[16:18]` is
`activity:7 | bit7 | version:3 | language:3 | hasCard?:1 | startedActivity:1` (version 5 = LeafGreen,
language 2 = English in that capture).

Untested: `local_communication_id` (a change hides the host, indistinguishable from the gate), a
scene brute force, multi-variable combinations. It reopens on bridge evidence assigning
`partner[].serialNo` from anything advertisable, or a capture of an advertisement a Switch treats as a
wonder distributor. The block costs the zero-button path and the four-berry Wonder News reward.

### The e-Reader itself

Trainer Tower sets and `CEReaderTool_SaveTrainerTower`: `ereader_screen.c` opens
`gLinkType = LINKTYPE_EREADER_FRLG` over the GBA serial link, not the wireless adapter.

### The Aurora and Mystic Tickets

A ticket card does nothing on the Switch release. The distribution scripts are in `data/mystery_event_msg.s:200`, but the Switch release grants both
tickets and both `FLAG_RECEIVED_*` flags on the first Hall of Fame entry
[post_battle_event_funcs.c:52, `#if REVISION >= 0xA`], so on a completed save the script is a no-op.
The gallery's `FL - Item AuroraTicket` script tests `FLAG_RECEIVED_AURORA_TICKET` first; on a retail
French FireRed past its Hall of Fame the delivery man said only "Merci d'utiliser le système CADEAU
MYST." and gave nothing. That card's `iconSpecies` is `0xFFFF`: any value but `SPECIES_NONE` draws an
icon, and a species past `SPECIES_UNOWN_B - 1` draws `SPECIES_NONE`'s question mark
[mystery_gift_show_card.c:466, pokemon_icon.c:1102].
The Old Sea Map is Emerald-only [mystery_gift.c:30].

## Traps

- `charmap.encode` drops unknown characters, newline included. The line break is 0xFE; `mg_server`'s
  encoder splits on `\n`, joins on 0xFE, and refuses a third line or a line wider than the ROM's
  longest string in that window ("A WONDER CARD has been received", 31 characters [strings.c:1291]).
  Window 1 is 28 tiles by 4 [mystery_gift_menu.c:97,524].
- A new payload goes into `DUMP_SCRIPTS` and `DECODED_SCRIPTS` in `buffer_script.py` and the
  launcher's `--dump-file` line, or the offline harness passes while the hardware path is untested.

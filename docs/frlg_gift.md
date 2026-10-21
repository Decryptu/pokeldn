---
title: Mystery Gift
parent: FireRed and LeafGreen
nav_order: 2
---

# Mystery Gift

FireRed/LeafGreen Mystery Gift over Friend accepts a Wonder Card, a delivery script, Wonder News, a
visiting Battle Tower trainer, and a Pokemon straight into the party, with no Pokemon Center. The
Mystery Event VM and native ARM code are on [Code on the console](frlg_rom.md).

## The session

The console's client boots with `{CLI_RECV, MG_LINKID_CLIENT_SCRIPT}, {CLI_COPY_RECV}`
[mystery_gift_scripts.c:15] and executes any `MysteryGiftClientCmd` array it receives
[mystery_gift_client.c:87].

    console joins  ->  SEND_PLAYER_IDS  ->  LinkPlayer block exchange  ->  one standby barrier
      server -> CLIENT_SCRIPT (sClientScript_SendGameData, 32 B)
      client -> GAME_DATA     (MysteryGiftLinkGameData, 96 B)   -- validated, card flag compared
      server -> CLIENT_SCRIPT (sClientScript_SaveCard, 48 B)
      server -> CARD          (struct WonderCard, 332 B)
      server -> RAM_SCRIPT    (1024 B: the delivery bytecode, zero-padded)
      client -> READY_END     (1024 B)
    close-link handshake  ->  disconnect

### Framing rules

- Size 0 means 1024 [mystery_gift_link.c:55]; `SVR_COPY_SAVED_RAM_SCRIPT` never sets
  `ramScriptSize` [mystery_gift_server.c:275], so the RAM script and READY_END are full 1024-byte
  messages. The CRC covers the padded buffer.
- Block pacing has no acknowledgement: `SEND_BLOCK_INIT` is ignored unless the receiver's slot is
  `RECV_STATE_READY` [link_rfu_2.c:1146]. `MysteryGiftTiming.inter_block_gap_frames` is 36; a dropped
  block leaves the console waiting forever.
- Stalls while the console sends follow
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
| `pokeldn/frlg/save/save_inject.py` | save gift writing with card, RAM-script and sector checksums |
| `bin/frlg_mg_host.py` | the CLI |

## Running it

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --phy auto \
               --keys PROD_KEYS --gift beast-cutscene --flag-id 1005
    (them) join the host when it appears; YES on the replace-card prompt if one shows

Radio setup: [The ESP32 radio](hardware_esp32.md). One console per run; the host stops once it has
left LDN ([Host implementation](frlg_host.md)). `tests/test_mystery_gift_flow.py` and
`tests/test_mystery_gift_end_to_end.py` model the console's receive path.

## What the link can carry

Three of the 22 client instructions [include/mystery_gift_client.h:18] execute something:

| instruction | what the console does |
|---|---|
| `CLI_SAVE_RAM_SCRIPT` (17) | stores a field script; it runs on the next NPC interaction |
| `CLI_RUN_MEVENT_SCRIPT` (15) | runs a Mystery Event bytecode script (17-opcode VM) |
| `CLI_RUN_BUFFER_SCRIPT` (21) | `func = (void *)gDecompressionBuffer; func(&param, gSaveBlock2Ptr, gSaveBlock1Ptr)`; up to 1024 bytes of ARM |

## The one RAM script slot

A console holds a Wonder Card or a bound RAM script, never both. `ValidateSavedWonderCard` ends in
`ValidateRamScript` [mystery_gift.c:186], which requires `RAM_SCRIPT_MAGIC`, map `MAP_UNDEFINED` and
`objectId == 0xFF` [script.c:538]; the field runs one only at the coordinates of the object talked to
[field_control_avatar.c:458]. `CLI_SAVE_RAM_SCRIPT` writes MAP_UNDEFINED/0xFF [script.c:578]; the
Mystery Event VM's `initramscript` writes real coordinates. With a bound script the card stays in the
save but the menu hides it and GameData reports `flagId` 0 [mystery_gift.c:349].

The next Wonder Card rebinds the slot and the card comes back; a buffer script leaves the slot
alone. A card rewrites SaveBlock1 +0x32E0 (card) and +0x361C (RAM script), one sector, nothing in
SaveBlock2.

`ramScript.checksum` is `CalcCRC16WithTable` over 1000 bytes, the 999 declared and one zeroed
padding byte [script.c:500] (`CalculateRamScriptChecksum` `0x0806D43C` BPRE, `0x0806D5A0` BPRF). A
slot whose CRC covers 999 bytes is wiped the first time its object is talked to [script.c:526].

## The gift catalogue

`--gift NAME`; `--help` lists flag ids (1000..1019). Only the held card matters: the same id means
"already has this card" (`MysteryGift_CompareCardFlags`). A console already holding the card takes
a Mystery Event gift alone, with no prompt.

| gift | what it does |
|---|---|
| `beast-cutscene-share` | the repeatable legendary-beast cutscene; the default demo card |
| `celebi` | the composed level-50 Celebi card |
| `porygon-tm-gift` | a Porygon card, a Clefairy scene, TM29 Psychic then TM46 Thief |
| `solrock-stamp` / `lunatone-stamp` | the two halves of one Stamp Rally card |
| `altering-cave` | the official Altering Cave event, ported |
| `wish-egg`, `pokepark-egg`, `pc-japan-egg` | the official distribution eggs |
| `event-pokemon` | a Gen 3 distribution Pokemon, straight into the party |
| `starter-egg` | an egg of one of the nine first partners, drawn by `random` |
| `rare-berries` | an Enigma, a Lansat and a Starf Berry, one stage each |
| `national-dex` | `EnableNationalPokedex` (special 367) unless `IsNationalPokedexEnabled` (403) answers 1 |
| `nature-mint`, `pc-anywhere` and 42 more | the GB-Link Team cards |
| `battle-count-card` | the official Battle Count Card |
| `visiting-trainer` | a Battle Tower trainer as ident 26 (FireRed only) |
| `mystery-event-probe` | `givenationaldex; setstatus 42; checksum`, the VM's self-test |
| `mystery-event-celebi` | `givepokemon`: a Lv30 Celebi holding mail, straight into the party |
| `mystery-event-npc` | `initramscript`: binds a field script to the Pallet Town fat man |
| `rng-seed-reader`, `rng-rate-probe`, `rng-shiny-hunt`, `rng-mon-hunt`, `rng-mon-hunt-both`, `rng-mon-hunt-log` | see [the RNG](frlg_rng.md) |

### The legendary beast

A deliveryman gives the Lansat and Liechi Berries and a Master Ball, then starts a repeatable
level-65 battle: Suicune for a Bulbasaur save, Entei for Squirtle, Raikou for Charmander.

### Porygon TM gift

A Porygon-icon card and a Clefairy sprite three tiles right of the player give TM29 then TM46 at
separate checkpoints. Default flag id 1007; the viewer shows `flag_id % 100`.

### The Stamp Rally

Two events share one `SUN AND MOON RALLY` card (Claydol icon, two stamp slots, flag id 1006), in
either order. Each stamp gives a level-30 Solrock or Lunatone; both give a level-50 Celebi.

| state | meaning |
|---|---|
| `VAR_MYSTERY_GIFT_1` | Celebi completion cursor |
| `VAR_MYSTERY_GIFT_2 = 0/1/2` | Solrock absent / active / received |
| `VAR_MYSTERY_GIFT_3 = 0/1/2` | Lunatone absent / active / received |
| `FLAG_MYSTERY_GIFT_DONE` | rally completion |

```text
matching = saved flag ID == distribution flag ID and max stamps == 2 and icon species == CLAYDOL
if no card:                install shared card + delivery script + selected stamp, run activation
else if not matching:      offer the toss prompt; on accept, install as above
else if stamp species or ID already exists:   HAS_STAMP
else if neither slot empty:                   NO_ROOM_STAMPS
else:                      save the stamp, run activation, STAMP_RECEIVED
```

The activation is a Mystery Event wrapper. `IsStampInMetadata` [mystery_gift.c:272] rejects a
colliding stamp; `CLI_SAVE_STAMP` writes only `cardMetadata.stampData` [mystery_gift.c:307].

### Altering Cave

The official script [data/mystery_event_msg.s:325] adds 1 to `VAR_ALTERING_CAVE_WILD_SET` (0x4024,
SaveBlock1 + 0x1048), wrapping at 10; values 9 and above read table 0 [wild_encounter.c:192].

| var | species | | var | species |
|---|---|---|---|---|
| 0 | Zubat | | 5 | Aipom |
| 1 | Mareep | | 6 | Shuckle |
| 2 | Pineco | | 7 | Stantler |
| 3 | Houndour | | 8 | Smeargle |
| 4 | Teddiursa | | | |

### Distribution eggs

Three Japanese distributions, from GB-Link-Switch-LDN's `web/js/gift/official.js`. The card picks one
egg with `random` [scrcmd.c:455]; it gets the distribution's moves, the fateful-encounter bit and met
location 0xFF. A full party refuses before the draw.

| card | eggs |
|---|---|
| `wish-egg` (Pokemon Center New York) | Chansey, Drowzee, Exeggcute, Farfetch'd, Kangaskhan, Lickitung; each knows Wish |
| `pokepark-egg` (PokePark Market Fantasia) | Cacnea, Corphish, Corsola, Igglybuff, Minun, Pichu, Plusle, Psyduck, Skitty, Spinda, Spoink, Surskit, Taillow, Whismur, Wynaut |
| `pc-japan-egg` (Pokemon Center Japan) | Bellsprout (Teeter Dance), Meowth (Petal Dance), Oddish (Leech Seed), Poliwag (Sweet Kiss) |

### Event Pokemon

`--gift event-pokemon --event-pokemon NAME` sends a Gen 3 distribution made by PKHeX.Core from
`EncounterGift3` (non-egg, non-Japanese) by its PID/IV method, legality-checked, through the Mystery
Event `givepokemon` when the card is saved. A full party answers status 3 and the card can be received
again. The default is the WISHMKR Jirachi.

`NAME` is trainer name and species: `WISHMKR Jirachi`, `CHANNEL Jirachi`, `Aura Mew`, `MYSTRY Mew`,
`DOEL Deoxys`, `SPACE C Deoxys`, `ROCKS Metang`, every `10 ANIV` species, and the European
`10ANNIV`, `10JAHRE`, `10ANNI` and `10ANIV` releases; `--language` picks among languages.

The card is build-independent; `tests/test_frlg_english_cartridges.py` runs it through each
cartridge's `RunMysteryEventScript`.

### GB-Link Team cards

The GB-Link Team's custom cards (GB-Link-Switch-LDN `cards/`, GPL-3.0) are a Wonder Card plus a RAM
script that calls THUMB code through `callnative`. Sources are in `vendor/gblink-cards/`;
`scripts/gen_team_cards.py` builds `pokeldn/frlg/data/team_cards.json`, reproducing all 44 of their
`BPRE 1.10` payloads byte for byte, and `team_cards.py` registers each id without `custom-`.
`starter-egg`, `rare-berries` (items 173-175) and `national-dex` (`FLAG_SYS_NATIONAL_DEX` 0x840) are
rebuilt with the composer.

| group | cards |
|---|---|
| change a Pokemon | `nature-mint`, `ability-capsule`, `poke-ball-changer`, `pokemon-gender`, `nickname`, `stat-judge`, `hidden-power`, `hidden-power-type`, `ev-training`, `friendship`, `pp-max`, `max-conditions`, `pokerus`, `unown-letters`, `trade-evolution`, `espeon-umbreon`, `move-tutor` |
| per-frame hooks | `speed-2`, `speed-3`, `speed-4`, `speed-0-75`, `speed-0-5`, `fast-text`, `travel-anywhere`, `pc-anywhere`, `hm-moves`, `reusable-tms`, `physical-special-split`, `exp-share`, `shiny-hunting`, `roamer` |
| other | `no-encounters`, `legendary-respawn`, `instant-eggs`, `gift-box`, `pocket-casino`, `gift-ribbons`, `trainer-ids`, `gender-swap`, `rival-name` |
| event Pokemon | `box-eggs`, `colosseum-pikachu`, `ageto-celebi`, `mattle-ho-oh` |

Differences from their build:

- All twelve revision `0x0A` cartridges: `vendor/gblink-cards/symbols.json` holds the 167 addresses
  per ROM, `tests/test_team_cards.py` checks them, and each script checks the header's game,
  language and revision ([The cartridge maps](frlg_rom_map.md#the-international-revision-0x0a-cartridges)).
- The relocated script (996 bytes) and menu list (80 bytes) live at `0x0203F768` and `0x0203FB50`,
  below the resident hooks at `0x0203FC00` ([Where a payload can live](frlg_rom.md#where-a-payload-can-live)).
- Hook installers chain to `VBlankIntr`, stored at `0x0203FBFC`, so a hook card and a game boost
  replace each other. Their state is at `0x0203FF60`.
- Ids above 1019 have no `sReceivedGiftFlags` bit; the registry sends 1000 + id mod 20.
- `hm-moves` and `physical-special-split` texts are shortened to fit 995 bytes.

Every card runs bound to Mom under mGBA on all twelve cartridges. On the other game's cartridge a
payload answers "This gift doesn't work with this version of the game." ("Wrong game." in Japanese).
`colosseum-pikachu` and `ageto-celebi` carry Japanese trainer names, drawn as dots on a European
cartridge.

### The Battle Count Card

`MysteryEventScript_BattleCard` [data/mystery_event_msg.s:162] gives a POTION at exactly three
`GET_CARD_BATTLES_WON` (special 390); the port gates on its own var, so it repeats. The counters advance
only if the u16 after the 96-byte trainer card equals the held card's flag id
[union_room.c:1777] (`frlg_trade_host.py --card-flag-id N`).

| what increments | where | the rule |
|---|---|---|
| `numTrades` | a completed trade [trade_scene.c:2609] | a trainer id the card has not counted |
| `battlesWon` / `battlesLost` | a cable club battle [cable_club.c:792] | the same, 5 ids per stat |

Union Room battles count nothing; only [the colosseum](frlg_link.md#the-cable-club-colosseum) does.
The counters sit at SaveBlock1 + 0x3434 with no CRC [mystery_gift.c:490]:

    0x3434: 0000 0000 0100 2300     trades 1, icon 35 (CARD_TYPE_LINK_STAT)

A `CARD_TYPE_GIFT` card stays at zero even when the special runs.

### The visiting trainer

`CLI_RECV_EREADER_TRAINER` (18, ident 26) copies the buffer into
`gSaveBlock2Ptr->battleTower.ereaderTrainer` [mystery_gift_client.c:233]. The struct is 188 bytes
[global.h:286]:

    0x00 u8  unk0                  0x10 u16 greeting[6]            0x34 BattleTowerPokemon party[3]
    0x01 u8  trainerClass          0x1C u16 farewellPlayerLost[6]  0xB8 u32 checksum
    0x02 u16 winStreak             0x28 u16 farewellPlayerWon[6]
    0x04 u8  name[8]
    0x0C u8  trainerId[4]

Valid when the first 46 words are not all zero and the u32 is their sum [battle_tower.c:1354,
:1384]. The old woman in `SevenIsland_House_Room1` then offers a repeatable 3v3 built by
`CreateBattleTowerMon` [battle_tower.c:928]; no level rule or banlist applies. FRLG shows five name
bytes [battle_tower.c:1343]. `--gift visiting-trainer` sends card, RAM script and trainer together;
with the same card held, the trainer alone.

## Wonder News

`struct WonderNews` [global.h:646] is 444 bytes:

| offset | size | field | notes |
|---|---|---|---|
| 0x000 | 2 | `id` | must not be 0, the only check [mystery_gift.c:113] |
| 0x002 | 1 | `sendType` | `SEND_TYPE_DISALLOWED` hides "Send" [mystery_gift.c:120] |
| 0x003 | 1 | `bgType` | `>= NUM_WONDER_BGS` reads 0 [mystery_gift_show_news.c:110] |
| 0x004 | 40 | `titleText` | centred in a 224 px window |
| 0x02C | 400 | `bodyText[10][40]` | eight lines on screen; a line past index 7 turns on the scroll indicator [:346] |

`IsWonderNewsSameAsSaved` compares all 444 bytes [mystery_gift.c:140] (`--news-id N` makes news
new). News and cards never displace each other.

- `build_wonder_news_app_data` advertises activity 22 [src/data/union_room.h:406].
- The console answers `MG_LINKID_RESPONSE` (ident 19): `FALSE` saved, `TRUE` already held
  [mystery_gift_client.c:210; mystery_gift_scripts.c:126].
- News from a Friend rolls a berry between `ITEM_RAZZ_BERRY` and `ITEM_NOMEL_BERRY`, given by the man
  in `CeruleanCity_House4`, up to five, then 500 steps [mystery_gift_menu.c:1367, wonder_news.c:21].
  The four-berry reward needs the closed Wireless path.

`--news` (`--news berry`, `--news-id N`). Message order (about 18 s):

    ident 16  sClientScript_SendGameData
    ident 17  MysteryGiftLinkGameData
    ident 16  sClientScript_SaveNews
    ident 23  MG_LINKID_NEWS - 444 bytes in three blocks
    ident 19  MG_LINKID_RESPONSE - FALSE: the console saved it
    ident 16  sClientScript_NewsReceived
    ident 20  READY_END                              -> SVR_MSG_NEWS_SENT

## The questionnaire as a password gate

`SVR_CHECK_QUESTIONNAIRE` compares the four Poke Mart questionnaire words
[mystery_gift.c:422]; `mg_server.gate_on_questionnaire(script)` splices it after the game-data prefix:

    bin/frlg_mg_host.py --gift ... --questionnaire species:55,FEELINGS/60,move:177,why

A word is an English name, `species:N`, `move:N`, `GROUP/INDEX` or a raw id. A wrong phrase gets the
host's 64-byte message (`CLIENT_SCRIPT_DYNAMIC_ERROR`) and nothing is sent. Every session logs the
console's four words from GameData [mystery_gift.c:361]:

    questionnaire: POKEMON/55  done [FEELINGS/60]  MOVE_1/177  why [MISC/37]

`EC_GROUP_POKEMON` indexes by species, `EC_GROUP_MOVE_1` by move id; see
[the French Easy Chat vocabulary](frlg_rom_map.md#the-french-easy-chat-vocabulary).

## What the console volunteers about itself

GameData carries the Easy Chat profile and the card stats [mystery_gift.c:361]. `--game-data-log
PATH` (`game_data_log.py`) appends each session to a JSONL ledger and prints what moved since that
console's last one; `tools/frlg/game_data_read.py PATH` reads it. A counter is evidence only as a
difference on the same card flag id.

## Save backup and restore

A Wonder Cards, Friend session copies the console's whole 128 KiB save chip to the host, or writes a
`.sav` onto it and makes the game load and save it; no card is sent. `asm/save-backup.s` and
`asm/save-restore.s` are ported from the GB-Link Team's `cards/savebackup.s` and
`cards/saverestore.s` (GPL-3.0); the host is `pokeldn.frlg.gift.save_transfer` (`--save-backup FILE`,
`--save-restore FILE`), and the app's Your save tab ([Your saves](gui.md#your-saves)). Both run on
all twelve cartridges ([Save backup and restore](frlg_rom_map.md#save-backup-and-restore)).

### The token coding

A byte `n < 0x80` is followed by `n + 1` literal bytes; `n >= 0x80` by one byte repeated
`n - 0x80 + 3` times (runs of 3 to 130, literals up to 128).

### Backup

The client script repeats `CLI_LOAD_TOSS_RESPONSE, CLI_RUN_BUFFER_SCRIPT, CLI_SEND_LOADED` up to 32
times per script. Each pass sends up to 1 KiB of tokens for at most 8 KiB of the chip, never across
the 64 KiB bank edge; the chip offset is `client->param = 0x5A << 24 | offset`
[mystery_gift_client.c:276], and a `param` without `0x5A` starts at `first`.

| payload word | offset | value |
|---|---|---|
| `first` | `0x004` | the chip offset the first pass starts at |
| `send_queue` | `0x008` | `&gRfu.sendQueue.count` |

A pass stages `0x800` bytes a frame into `gDecompressionBuffer + 0x800`, compresses into `+ 0x400`,
and sets `link.sendBuffer` (`param + 0x3C`) and `link.sendSize` (`param + 0x34`). It waits while
`gRfu.sendQueue.count` is not zero. The session ends on `CLI_MSG_BUFFER_FAILURE` with a message, so
the console does not save [mystery_gift_menu.c:1379]. A cut-short backup resumes by game code and
trainer id.

### Restore

1. The first message is the 620-byte image; `install` copies it to `gDecompressionBuffer + 0x400`
   and answers with the 12-byte footers (id, checksum, signature, counter at `+0xFF4`) of the 28 slot
   sectors.
2. The host finds the newest whole slot as `GetSaveValidStatus` would and writes the file's copy into
   the other slot with counter `newest + 1`, then sectors 28 to 31 as the file has them.
3. It erases the target slot's id-0 sector first and writes the new id 0 last, so the chip's own
   copy loads until the new one is whole.
4. Later messages start `b RESIDENT + 4` (`0xEA0000FF`), then an op. `OP_DATA` (1) carries sector,
   write flag, u16 offset, u16 token length and tokens into a 4 KiB buffer; the sector's last
   message writes it with `swi 0x48` and verifies it, setting a fail-mask bit on mismatch.
5. `OP_FINISH` (2) calls `LoadGameSave(SAVE_NORMAL)` if nothing failed [save.c:803]. On
   `SAVE_STATUS_OK` the session ends on `CLI_MSG_BUFFER_SUCCESS` and the console saves the loaded
   game; otherwise on `CLI_MSG_BUFFER_FAILURE` and the old save stays.

| payload word | offset | value |
|---|---|---|
| `b install` | `0x000` | the first message's entry |
| `b entry` | `0x004` | every later message's entry, at `gDecompressionBuffer + 0x404` |
| `load_game_save` | `0x008` | `LoadGameSave \| 1` |

The host refuses a save whose loaded copy is not whole or of the other layout: Japanese SaveBlock1
is 40 bytes shorter, read from the language byte (`+0x12`) of the trainer's own Pokemon.

`tests/test_save_transfer.py` covers backup, resume, restore and an interrupted restore against the
scripted console. On retail, backup works on French and English FireRed, and restore on English
FireRed, a French save included. The console's next save differs from the file in sectors 1 to 7,
which carry the encryption key `LoadGameSave` re-rolls.

## Authoring gifts

`pokeldn.frlg.gift.gift_composer` builds cards and delivery scripts from `WonderGift` definitions:

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

`WonderGift.delivery` uses `delivery`; `StampSlot.delivery` and `StampRallySpec.completion` use
`pre_stages` and `post_stages`. The compiler resumes stages from `VAR_MYSTERY_GIFT_1` and on success
sets `FLAG_MYSTERY_GIFT_DONE` and the receipt flag; `GiftSpec(repeatable=True)` resets the cursor.

### Stages and conditions

Each `DeliveryStage` is one checkpoint; never put two fallible rewards (`GiveItem`, `GivePokemon`,
`GiveEgg`) in one stage. A move-bearing `GiveEgg` needs a party slot. `GiveRandomEgg(eggs)` picks one
through a jump table (fifteen four-move eggs fit in 944 bytes). `condition=` (`VarEquals`, `FlagSet`,
`Not`, `AllOf`, `AnyOf`) skips a stage but advances the cursor; `RequireSpecialResult(...)` stops on
failure without advancing.

```python
DeliveryStage(ShowSprite(142, RelativeToPlayer(dx=1)),
              condition=VarEquals(0x4031, 0))  # VAR_STARTER_MON == Bulbasaur
DeliveryStage(RequireSpecialResult(SPECIAL_HAS_ALL_KANTO_MONS, 1, "Finish the KANTO POKEDEX first."),
              GivePokemon(251, level=50))
```

`SetVar` (`setvar` 0x16) and `AddVar` (`addvar` 0x17) accept saved vars 0x4000..0x40FF and special vars
0x8000..0x8011.

### Battles

`BattleLegendary` emits `setwildbattle`, `special StartLegendaryBattle`, `end` with no `waitstate`
([a RAM script may not come back from a battle](frlg_rng.md#a-ram-script-may-not-come-back-from-a-battle));
`BattlePokemon` emits `dowildbattle`. Either ends its stage. Battles are refused in a stamp-slot
path except as conditional terminal alternatives.

### Sharing

`GiftSpec.shareable` sets the card's `sendType`: `"never"`, `"once"` (the receiver's copy becomes
unshareable) or `"always"`.

### Fateful-encounter marking

`GivePokemon(..., fateful_encounter=True)` (and `GiveEgg`) emits `setmonmodernfatefulencounter`
(`0xCD`) and `setmonmetlocation` (`0xD2`, 0xFF) [data/mystery_event_msg.s:71]. The first command does
not bounds-check its index [scrcmd.c:2239]; the index is the party count before the give, and a full
party jumps to the failure label. The summary line comes from the met location alone
[pokemon_summary_screen.c:2665, 2799]; `modernFatefulEncounter` is bit 31 of Misc+0x08
[include/pokemon.h:40-82].

### `initramscript` in the composer

`gift_composer.build_bound_script(actions)` and `build_mevent_npc_script(actions=...)` compile actions
into the field script `initramscript` binds. It has no stage cursor and reruns whole, so a once-only
effect needs its own `SetVar` or condition.

### Registration and validation

```python
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
GIFT_REGISTRY.register_definition(MEWTWO_GIFT)
```

Registration validates and compiles: card text and flags, plan structure, action ranges, cursor
bounds, unique stamps, battle placement, pointers and the 995-byte RAM-script limit, with errors
naming the path (`example-rally.event.slots[1].delivery.post_stages[0].actions[1]: ...`).

## Static tools

```bash
./.venv/bin/python -m pokeldn.frlg.gift.gift_to_bin --gift beast-cutscene --flag-id 1005 --out-dir exported-gift
./.venv/bin/python -m pokeldn.frlg.save.save_inject game.sav --gift beast-cutscene --flag-id 1005
```

`gift_to_bin` writes a 336-byte Wonder Card and a 1004-byte RAM script for
`pokemon-gen3-mysterygift-tool`. `save_inject` writes both into the active slot, fixes the card,
RAM-script and sector checksums, and saves `<save>.gift.sav` (`--in-place` overwrites;
`--make-artifact` writes a `.ram.lst` listing under `artifacts/`).

## Closed paths

### Wireless Communication (JoySpot)

The Wireless path is blocked at the RFU serial-number gate:

| | Friend | Wireless Communication |
|---|---|---|
| listener | `Task_ListenForCompatiblePartners` [union_room.c:3757] | `Task_ListenForWonderDistributor` [union_room.c:3799] |
| accepts RFU serial | `{0x0002, 0x7F7D}` | `== 0x7F7D` only [link_rfu_3.c:920] |
| selection | the player picks from a list | auto-connects |
| reachable from a Switch | yes | no |

`Task_CardOrNewsOverWireless` [union_room.c:2415] keeps candidate 0 only if its `serialNo` is
`0x7F7D`, then checks the spawn state, the `hasCard` bit (SE_BOO on failure) and reconnects. The
Switch bridge reports `0x0002`, and the advertisement has no serial field; `svc_47` [sloopsvc.c:34]
takes 24 bytes with no serial. A native advertisement:

```
50 10 | c1 cc bf bf c8 ff 00 00 | 65 ac | 00 00 00 00 | 84 15 | 00 00 00 00 00 00
TID   | uname                   | parent| unexplained | search| unexplained
```

The search word at `record[16:18]` is
`activity:7 | bit7 | version:3 | language:3 | hasCard?:1 | startedActivity:1`.

No tried advertisement variant (scene id, app versions, `0x7F7D` at every free offset, activity,
`hasCard`, bit 7) drew an authentication from the Wireless path. Untested: `local_communication_id`,
a scene brute force, combinations.

### The e-Reader itself

Trainer Tower e-Reader sets use `LINKTYPE_EREADER_FRLG` over the GBA serial link (`ereader_screen.c`),
not the wireless adapter.

### The Aurora and Mystic Tickets

The Switch release grants both tickets and their `FLAG_RECEIVED_*` flags on the first Hall of Fame
entry [post_battle_event_funcs.c:52, `REVISION >= 0xA`], so a ticket card gives nothing after it. A
card's `iconSpecies` other than `SPECIES_NONE` draws an icon; past `SPECIES_UNOWN_B - 1` it draws the
question mark [mystery_gift_show_card.c:466, pokemon_icon.c:1102]. The Old Sea Map is Emerald-only
[mystery_gift.c:30].

## Traps

- `charmap.encode` drops unknown characters, newline included. The line break is 0xFE; `mg_server`
  refuses a third line or one wider than 31 characters [strings.c:1291] (window 28 tiles by 4,
  [mystery_gift_menu.c:97,524]).
- A new payload goes into `DUMP_SCRIPTS` and `DECODED_SCRIPTS` in `buffer_script.py` and the
  launcher's `--dump-file` line.

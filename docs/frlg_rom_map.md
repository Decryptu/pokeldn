---
title: The ROM map
parent: FireRed and LeafGreen
nav_order: 4
---

# The ROM map

This page maps the FireRed/LeafGreen cartridge ROMs: images, function tables, script readers, the
species table, the French Easy Chat vocabulary and the twelve international builds. Addresses are
French FireRed (BPRF, version 0x0A) unless a table says otherwise; LeafGreen's are on
[LeafGreen](frlg_leafgreen.md). `pokeldn/frlg/rom/rom_map.py` records how each address was obtained
and `tests/test_rom_map.py` checks it against console dumps.

## The cartridge image

The Switch release carries the GBA ROM as the only file in its RomFS.

| title id | RomFS file | size | sha1 |
|---|---|---|---|
| 01004B3023412000 | `/FireRed_f.gba` | 16777216 | `07566b82dbd2a91321698f730f6400ae4c56ddf1` |
| 010087C02342E000 | `/LeafGreen_f.gba` | 16777216 | `9f774956dfbad7f69ddb91fb91d2c26e54408f75` |
| 0100554023408000 | `/FireRed_e.gba` | 16777216 | `baa452d0b24629dd7782cfc07a8984085dde1311` |
| 010034D02340E000 | `/LeafGreen_e.gba` | 16777216 | `62b9fc77549dbc67032eb6cbd0ea6ad3b825690f` |

The header at 0xA0 reads `POKEMON FIRE` `BPRF` and `POKEMON LEAF` `BPGF`, version 0x0A, checksum
valid. The French FireRed 1.0.1 update leaves the guest ROM unchanged apart from the wrapper's three
load-time patches ([frlg_rom.md](frlg_rom.md), The breakpoint hooks); `0x09000000..0x0A000000` reads
open bus (each halfword its own address halved). The English pair (`BPRE`, `BPGE`) is byte-identical
to `pret/pokefirered`'s `pokefirered_switch.gba` and `pokeleafgreen_switch.gba`.

`scratchpad/base_romfs.py` reads the Program NCA's single CTR RomFS section:

    ./.venv/bin/python scratchpad/base_romfs.py "$NSP" --list
    ./.venv/bin/python scratchpad/base_romfs.py "$NSP" --extract /FireRed_f.gba --out scratchpad/FireRed_f.gba

## EWRAM is at the same addresses in both builds

The English ELF's EWRAM symbols are the French cartridge's (`gDecompressionBuffer` 0x0201C000,
`gPlayerParty` 0x02024280, `gPlayerPartyCount` 0x02024025). IWRAM differs. No symbol claims
0x0203FBAC (highest symbol end) to 0x02040000 (`scratchpad/ram_survey.py`).

## The English cartridges

`pokeldn/frlg/rom/builds.py` holds one table per cartridge (`BPRF`, `BPGF`, `BPRE`, `BPGE`, `BPRS`,
`BPGS`, `BPRD`, `BPGD`, `BPRI`, `BPGI`, `BPRJ`, `BPGJ`): IWRAM globals, the ROM functions payloads,
hooks, stubs and `call-chain` use, and the data pointers gifts carry. The host picks a table from the
game code in `MysteryGiftLinkGameData` [mystery_gift.c:369] before anything address-dependent is
sent; a console with no table, or one excluded by `--console-build CODE` or `--version`, is refused
with nothing sent.

English addresses come from the ELFs, each checked against the retail image.

| region | French to English |
|---|---|
| EWRAM | unchanged |
| IWRAM 0x03000000..0x03001B6F | unchanged |
| IWRAM 0x03002370..0x0300602F English, from `gMain` (0x030022D0 French, 0x03002380 English) | +0xB0 |
| IWRAM 0x03006090..0x03007583 English, `gSoundInfo` (0x03005F80 French) to `gFlash` | +0x110 |
| IWRAM 0x03007590 and up: the stack, the interrupt vector | unchanged |
| ROM | no single offset; every function is looked up |

English values: `gRngValue` 0x030042D0, `gSaveBlock1Ptr` 0x030042D8, `gSaveBlock2Ptr` 0x030042DC,
`gIntrTable[4]` 0x030027E0, `gLastWrittenSector` 0x03004650, `gSaveCounter` 0x03004660. English
LeafGreen's RAM is English FireRed's; of a resident hook's addresses only `m4aSoundMain` moves
(0x081E07C4 against 0x081E07E8). `tests/test_frlg_english_cartridges.py` runs the payloads through
each image's `Client_RunBufferScript` (skipped without `scratchpad/frlg_en/`).

## The BIOS wrappers

`libagbsyscall.s` links as THUMB `svc N ; bx lr` pairs in the decomp's order, 0x24 lower on LeafGreen:

| wrapper | svc | FireRed | LeafGreen |
|---|---|---|---|
| `ArcTan2` | 0x0A | 0x081E21D4 | 0x081E21B0 |
| `BgAffineSet` | 0x0E | 0x081E21D8 | 0x081E21B4 |
| `CpuFastSet` | 0x0C | 0x081E21DC | 0x081E21B8 |
| `CpuSet` | 0x0B | 0x081E21E0 | 0x081E21BC |
| `Div` | 0x06 | 0x081E21E4 | 0x081E21C0 |
| `LZ77UnCompVram` | 0x12 | 0x081E21E8 | 0x081E21C4 |
| `LZ77UnCompWram` | 0x11 | 0x081E21EC | 0x081E21C8 |

The game's LZ77 streams are VRAM-safe and match `gbagfx` output. LZ77 does not shrink payload code;
it helps only data over 1024 bytes.

## The first anchor

`anchors` returns `0x08148C75`, the return address in `Client_RunBufferScript`
[mystery_gift_client.c:274]. Its literal pool:

    0x08148C88 -> 0x0201C000   gDecompressionBuffer
    0x08148C8C -> 0x0300422C   &gSaveBlock2Ptr
    0x08148C90 -> 0x03004228   &gSaveBlock1Ptr

`MysteryGiftClient_CallFunc` at 0x08148C94 indexes `sClientFuncs` (0x0845DBD0, eight entries) by
`client->funcId`. Every other address is reached from literal pools, `bl` targets and pointer tables,
each landing on a known prologue (`scratchpad/rom_read.py`).

## The four function tables

    gScriptCmdTable              0x08163650   214 entries   the field script commands
    gSpecialVars                 0x081639A8    21 entries
    gSpecials                    0x081639FC   444 entries   gSpecialsEnd 0x081640EC
    gStdScripts                  0x081640EC    10 entries
    gMysteryEventScriptCmdTable  0x081DE144    17 entries

`script_data` runs from 0x08163650 to 0x081DE188, where `lib_text` (`libgcnmultiboot`) starts
[ld_script_rev10.ld:318-330].

- `gSpecialVars`: twelve words each 2 above the last (`gSpecialVar_0x8000` = 0x020370B4, an
  `EWRAM_DATA` global) [event_data.c:16].
- `gScriptCmdTable`: 214 THUMB pointers; entries 0 and 213 are both `ScrCmd_nop`.
  `pokeldn/frlg/rom/scrcmd_names.py` names every entry (`scrcmd_names.handler("additem")`).

      0x23 callnative   0x0806D854      0x44 additem      0x0806DED0
      0x25 special      0x0806D7EC      0x79 givemon      0x0806F834
      0x29 setflag      0x0806E0EC      0x90 addmoney     0x0806F998

- `gSpecials`: 444 entries from `ScrCmd_special`'s literal pool [scrcmd.c:101], called through
  0x081E2224; 171 are `NullFieldSpecial`. `rom_map.SPECIAL_ADDRESSES` holds them and
  `rom_map.special_function("HealPlayerParty")` resolves one.
- `gStdScripts`: ten words into 0x081A76xx..0x081AB5xx.
- `gMysteryEventScriptCmdTable`: found through `sMysteryEventScriptContext` (0x0203AA38), whose
  table pair sits at +0x5C/+0x60 [mystery_event_script.c:27,52]
  (`table-scan --table-delta 0x44 --table-runlen 2` over EWRAM, after a Mystery Event gift in the same
  boot).

| # | command | handler | | # | command | handler |
|---|---|---|---|---|---|---|
| 0 | `nop` | 0x080DE451 | | 9 | `givenationaldex` | 0x080DE61D |
| 1 | `checkcompat` | 0x080DE401 | | 10 | `addrareword` | 0x080DE641 |
| 2 | `end` | 0x080DE3F5 | | 11 | `setrecordmixinggift` | 0x080DE66D |
| 3 | `setmsg` | 0x080DE465 | | 12 | `givepokemon` | 0x080DE681 |
| 4 | `setstatus` | 0x080DE455 | | 13 | `addtrainer` | 0x080DE78D |
| 5 | `runscript` | 0x080DE49D | | 14 | `enableresetrtc` | 0x080DE7D5 |
| 6 | `initramscript` | 0x080DE5B5 | | 15 | `checksum` | 0x080DE7E9 |
| 7 | `setenigmaberry` | 0x080DE4B9 | | 16 | `crc` | 0x080DE831 |
| 8 | `giveribbon` | 0x080DE581 | | | | |

## From a table entry to the function behind it

A handler's `bl` targets in address order are the decomp's calls in source order
[scrcmd.c:463-590]:

    ScriptReadHalfword   0x0806D1E8      AddBagItem           0x0809DA70
    VarGet               0x08071DDC      RemoveBagItem        0x0809DBC4
    GetVarPointer        0x08071CC8      CheckBagHasSpace     0x0809D9EC
    FlagSet              0x08071EF4      CheckBagHasItem      0x0809D92C
    FlagClear            0x08071F1C      AddPCItem            0x0809DDB4
    FlagGet              0x08071F44      IncrementGameStat    0x080587A4

`gSpecialVar_Result` is 0x020370CC; `Random` is 0x080486B0. `scratchpad/handler_workers.py` prints a
handler's `bl` targets; `tools/frlg/rom_functions.py --table specials|field|mystery-event|callable`
does it across a table and plans the next `--dump-address` windows.

The ROM is agbcc-built and ends a THUMB function `pop {r4,r5,r6}; pop {r1}; bx r1` (BC70 BC02 4708),
never `pop {..., pc}`. `pokeldn/frlg/rom/thumb.py` matches `bx Rn` and treats a return as the end
of a block only when a prologue follows.

### Naming 300 workers offline

`scripts/gen_worker_names.py` zips every dumped body against the decomp and writes
`pokeldn/frlg/rom/worker_names.py`, under four checks:

| check | what it rules out |
|---|---|
| length | inlining, `__umodsi3`, a macro read as a call |
| anchor | a misaligned body: every measured address must land back on its own name |
| agreement | a target named differently by two callers |
| link order | a name in the wrong place in the ROM (longest ascending chain kept) |

A gap between anchors holding one unnamed target and one source call is forced. Reading the source:

- `firered_switch` is `GAME_REVISION=10 MODERN=0` [Makefile:227]: the `#if REVISION >= 0xA` blocks
  are live.
- `VarGet(ScriptReadHalfword(ctx))` is `bl ScriptReadHalfword` then `bl VarGet`.
- `ScriptReadByte` is a macro and emits no `bl` [include/script.h:24].
- `NDEBUG` holds: no assert calls.

| `rom_map` name | the decomp | bodies agreeing |
|---|---|---|
| `GET_MON_DATA` | `GetMonData3` | 15 |
| `SCRIPT_CONTEXT_SET_NATIVE` | `SetupNativeScript` | 11 |
| `SET_RESPAWN` | `SetLastHealLocationWarp` | 1 |
| `SCRIPT_MOVEMENT_START` | `ScriptMovement_StartObjectMovementScript` | 2 |
| `CHANGE_AMOUNT_MONEY_BOX` | `ChangeAmountInMoneyBox` | 2 |
| `ME_CHECK_COMPATIBILITY` / `ME_SET_INCOMPATIBLE` | `CheckCompatibility` / `SetIncompatible` | 1 / 3 |

`GetMonData2` aliases `GetMonData3` [pokemon.c:2970]. `0x0806D0EC` is `StopScript(ctx)` [script.c:76];
`ScriptContext_Stop(void)` [:360] is 0x0806D418.

### Two mixed-image hazards

- Never read two cartridges' dumps as one image: LeafGreen keeps this code −0x2C away, and a mixed
  image misnames calls. `script_read.every_dump` takes one cartridge.
- Read every dump at once: `scrcmd.Memory` merges overlapping dumps
  (`tools/frlg/script_read.py --with-every-dump`).

### What is measured

Every body behind every table is read: 213 field commands, 17 Mystery Event opcodes, 27 callable
functions, 272 specials. `NullFieldSpecial` is `bx lr` at 0x080CE8DC; `GetLeadMonIndex` is
0x080CE818; `DoDiveWarp` 0x08081CC8, `DoFallWarp` 0x08081DA0.

The Mystery Event VM's workers:

| worker | address | called by |
|---|---|---|
| `StringExpandPlaceholders` | 0x0800CADC | the last call of every handler that leaves a message |
| `RunScriptImmediately` | 0x0806D438 | `runscript` |
| `InitRamScript` | 0x0806D5F0 | `initramscript` |
| `GiveGiftRibbonToParty` | 0x080A43B0 | `giveribbon` |
| `EnableRareWord` | 0x080C1658 | `addrareword` |
| `CheckCompatibility` | 0x080DE300 | `checkcompat` |
| `SetIncompatible` | 0x080DE330 | `checkcompat`'s else |
| `memcpy` | 0x081E44F4 | `addtrainer` |
| `CalcCRC16` | 0x080489A0 | `crc` |
| `StringCopyN` | 0x0800C8CC | `setenigmaberry`, `givepokemon` |
| `StringCompare`, `SetEnigmaBerry` | 0x0800C938, 0x080A01B0 | `setenigmaberry` |
| `VarSet` | 0x08071DF8 | `setenigmaberry`; no ScrCmd calls it |
| `SpeciesToNationalPokedexNum` | 0x08046994 | `givepokemon` |
| `GetSetPokedexFlag` | 0x0808C860 | `givepokemon` |
| `ItemIsMail`, `GiveMailToMon2`, `CompactPartySlots` | 0x0809BB18, 0x0809B964, 0x080971FC | `givepokemon` |

The call veneers are four bytes each from `_call_via_r0` at 0x081E2224 (r4 0x081E2234, r6 0x081E223C).

## Save backup and restore

`LoadGameSave` [save.c:803] and `gRfu.sendQueue.count` [link_rfu_2.c:3131] on every cartridge.
`LoadGameSave` opens `70 b5 00 06` and pools `gDecompressionBuffer`; the queue count is read by the
leaf `ldr r0, =gRfu; ldr r1, =0x8D2; adds r0, r0, r1; ldrb r0, [r0]; bx lr`.

| cartridge | `LoadGameSave` | `gRfu` | `gRfu.sendQueue.count` |
|---|---|---|---|
| `BPRE` | `0x080DDBF4` | `0x03005590` | `0x03005E62` |
| `BPGE` | `0x080DDBC8` | `0x03005590` | `0x03005E62` |
| `BPRF` | `0x080DDFD4` | `0x030054E0` | `0x03005DB2` |
| `BPGF` | `0x080DDFA8` | `0x030054E0` | `0x03005DB2` |
| `BPRD`, `BPRI` | `0x080DDF14` | `0x030054E0` | `0x03005DB2` |
| `BPGD`, `BPGI` | `0x080DDEE8` | `0x030054E0` | `0x03005DB2` |
| `BPRS` | `0x080DDFFC` | `0x030054E0` | `0x03005DB2` |
| `BPGS` | `0x080DDFD0` | `0x030054E0` | `0x03005DB2` |
| `BPRJ` | `0x080DED68` | `0x03005520` | `0x03005DF2` |
| `BPGJ` | `0x080DED3C` | `0x03005520` | `0x03005DF2` |

`sSaveSlotLayout` agrees on all twelve except sector id 4: 3816 bytes on the Latin cartridges, 3776
on the Japanese ones.

# Reading the console's scripts

`scripts/gen_scrcmd_args.py` generates operand widths from the decomp's macros into
`pokeldn/frlg/rom/scrcmd_args.py`; `memory-dump` plus `scrcmd.disassemble` then reads any script:

    0x081A7624  6A  lock
    0x081A7625  5A  faceplayer
    0x081A7626  67  message 0x00000000
    0x081A762B  66  waitmessage
    0x081A762C  6D  waitbuttonpress
    0x081A762D  6C  release
    0x081A762E  03  return

This is `Std_MsgboxNPC`. A walk from each `gStdScripts` entry ends on a terminator at the byte
before the next.

## The conditional macros

| command | width | structure |
|---|---|---|
| `applymovement` | 7 bytes | `.ifb \map` branch |
| `waitmovement`, `removeobject`, `addobject` | 3 bytes | `.ifb \map` branch |
| `applymovementat`, `waitmovementat`, `removeobjectat`, `addobjectat` | 9, 5, 5, 5 bytes | alternate branch |
| `warp` and the eight other warps | 8 bytes | `formatwarp` sub-macro |
| the ten `buffer*` commands | 4 bytes | `stringvar` sub-macro |
| `showobjectat`, `hideobjectat`, `resetobjectsubpriority` | 5 bytes | `map` sub-macro |
| `trainerbattle` | 6 + 4..16 bytes | type-dependent branch |

A macro is a command macro only when every route starts with its own opcode byte and reaches no other
command macro (`giveitem` is two instructions). `trainerbattle` is `scrcmd_args.VARIABLE`; an unknown
type makes `scrcmd.shape` answer `None`. `goto` is a terminator alongside `end` and `return`. The
266-byte trainer-battle region 0x081A7699..0x081A77A3 is a fixture in
`tests/test_script_cmd_table.py`.

## Naming the operands

`tools/frlg/script_read.py DUMP.bin --base ADDR`:

    0x081A76A8  4F  applymovement 0x800F (VAR_LAST_TALKED), 0x081A77B0
    0x081A76B2  26  specialvar 0x800D (VAR_RESULT), 0x0036 (Script_HasTrainerBeenFought)
    0x081A76BC  06  goto_if 0x05 (!=), 0x081A76CD
    0x081A76C2  25  special 0x0038 (PlayTrainerEncounterMusic)

- An operand of 0x4000 or more is a variable reference in any command [event_data.c:214,235].
  `pokeldn/frlg/rom/symbol_names.py` has the 274 var and 1470 flag names.
- `scrcmd_args.PARAMS` names each operand, which picks the table (`special` u16 into `gSpecials`,
  `callstd` u8 into `gStdScripts`).
- Conditions are <, =, >, <=, >=, != [scrcmd.c:65].

## Following a script to what it reaches

`scrcmd.follow` chases every `goto`, `call`, `goto_if` and `call_if` and collects unheld addresses;
data pointers are reported, not followed. `scrcmd.dump_plan` turns the misses into
`--dump-address` lines. `charmap.decode` is for names, `charmap.decode_message` for dialogue. A
command running past the dump's end is reported as a short dump.

# The species table

`gSpeciesInfo` = 0x0824CDFC, stride 28 (the decomp's 26 plus two `00 00` padding bytes). Its data
matches the English decomp. Traps when parsing the decomp: `[SPECIES_NONE] = {0},` on one line,
`PERCENT_FEMALE(x)`, the `noFlip` bitfield, and hex `#define`s.

## Finding `CreateMon` from it

`pokemon.o`'s first `&gSpeciesInfo` pool belongs to `CreateMon` [pokemon.c:1755]:

| symbol | address | how |
|---|---|---|
| `CreateMon` | `0x08041150` | the disassembly (`f0b5 4746 80b4 87b0`) |
| `ZeroMonData` | `0x08041090` | its first call |
| `CreateBoxMon` | `0x080411C0` | its call between ZeroMonData and SetMonData |
| `SetMonData` | `0x08043A78` | called with 56 (`MON_DATA_LEVEL`), then 64 (`MON_DATA_MAIL`) with 255 |
| `CalculateMonStats` | `0x08041B78` | its last call |

## The Spanish FireRed cartridge

Spanish FireRed base v0 (`0100EB702342C000`) contains `FireRed_s.gba`, game code `BPRS`, revision 0x0A.
`builds.BPRS` and `vendor/gblink-cards/symbols.json` (language id 7) carry its addresses.

| symbol | Spanish FireRed |
|---|---|
| `gRngValue`, `gSaveBlock1Ptr`, `gSaveBlock2Ptr` | 0x03004220, 0x03004228, 0x0300422C |
| `gMain`, `gIntrTable[4]`, `gSoundInfo` | 0x030022D0, 0x03002730, 0x03005F80 |
| `VBlankIntr`, `Client_RunBufferScript` | 0x0800071C, 0x08148CD0 |
| `CreateMon`, `GetMonData3`, `Random` | 0x08041164, 0x080432F8, 0x080486C4 |
| `CB1_Overworld`, `CB2_Overworld`, `RunTextPrinters` | 0x08059E5C, 0x08059EDC, 0x08002D50 |
| `m4aSoundMain`, `ReadFlash` | 0x081E089C, 0x081E224C |
| `MapGridGetElevationAt`, `MapGridGetCollisionAt` | 0x0805C658, 0x0805C6D8 |
| Cut, Rock Smash, Strength message return pointers | 0x081C1909, 0x081C19FD, 0x081C1AE6 |
| `GetMoney`, `SpeciesToNationalPokedexNum` (table) | 0x080A376C, 0x080469A8 (0x0824B9DE) |

The badge checks point to message scripts at 0x081C1901, 0x081C19F5 and 0x081C1ADE;
`EventScript_CurrentTooFast` starts at `0x081AA346` (`lockall`). Translated text moves each resume
script. `tests/test_frlg_english_cartridges.py`, `tests/test_noclip.py` and `tests/test_follower.py`
use `scratchpad/frlg_es/FireRed_s.gba` when present.

# The French Easy Chat vocabulary

All 1006 language-dependent Easy Chat words are read out of the console's ROM into
`pokeldn/frlg/text/easychat_french_words.py`; `easychat_french.french(id)` answers from it.

## The slot problem

An Easy Chat id is `(group << 9) | index`. `pokeldn/frlg/text/easychat_words.py` names what the
English ROM keeps in each slot; the French ROM keeps other words (`EC_WORD_ENJOY` renders STRESSE,
`EC_WORD_DONE` FURAX, `SPEECH/12` LES). Mail, the trainer card quote, the visiting trainer,
`--denied-message` and the questionnaire gate depend on the French table.

## Finding the table

`sEasyChatGroups[]` is 22 entries of `{ const void *wordData; u16 numWords; u16 numEnabledWords; }`
[src/data/easy_chat/easy_chat_groups.h:26], at 0x083E3700. Its counts equal the English build's, so an
id is the same slot in both languages. Word arrays and text span 0x083DE2C8..0x083E3700.
`tests/test_easychat_french.py` requires render and ROM evidence to agree. `TRAINER/11` is DRESSEUR;
DRESSEURS is not in the table.

## What the table says

- `EC_GROUP_STATUS` (109 Abilities) is nearly a direct translation (`stench` PUANTEUR, `thick_fat`
  ISOGRAISSE, `air_lock` AIR LOCK).
- `EC_GROUP_FEELINGS` is re-binned: slot 13 (`disappoints`) is RAVI, 44 (`eat`) HUMILIE, 51
  (`drink`) HONTEUX.
- `EC_GROUP_SPEECH`: LES and L' take the slots English spends on `case` and `miss`.

807 slots (`EC_GROUP_POKEMON`, `POKEMON_2`, `MOVE_1`, `MOVE_2`) print from `gSpeciesNames` /
`gMoveNames` [easy_chat.c:155], localized by the console; `easychat.species_word(55)`,
`easychat.move_word(177)` and `easychat.is_language_safe` handle them.

## Using it

```python
from pokeldn.frlg.text import easychat, easychat_french
easychat_french.french(easychat.WORDS["enjoy"])     # 'STRESSE'
easychat_french.render(ids)                          # the line as the console will print it
easychat_french.check(ids, strict=True)              # raises on anything unread or out of range
```

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS \
        --buffer-script string-gather --gather-address 0x083DF5C0 --gather-count 42 \
        --gather-stride 12 --dump-file DUMP.bin --version firered    # one group per run
    ./.venv/bin/python scratchpad/ec_words.py --group 4 DUMP.bin

LeafGreen's Easy Chat region is FireRed's at −0x1C4 with identical vocabulary.

## The international revision 0x0A cartridges

The host has address tables for both versions in English, French, German, Italian, Spanish and
Japanese. Functions are paired with the English ELF by unique instruction windows with relative calls
and pointer literals masked; RAM globals come from literal pools; field-move scripts are paired as
command sequences. `SpeciesToNationalPokedexNum` is paired through its neighbours, which share its
instruction sequence.

| cartridge | ROM file | SHA-256 |
|---|---|---|
| `BPRD` | `FireRed_d.gba` | `04f43a43f7cf9109561cd1744d108f50202c931ce31b30abaa6f18950824d20d` |
| `BPRE` | `FireRed_e.gba` | `d32c8df8702293716ad8de68755fe5903161f4829a0a2e486bfa7e74a0b62e94` |
| `BPRF` | `FireRed_f.gba` | `9edf7a3137536b0ccf024a732025da9a0ea1330eb9fd13b2ffed19f5e008c147` |
| `BPRI` | `FireRed_i.gba` | `cf7fa25cf57fbf12f24709efdd1d1aa8056efb4e9b6520ac7d068d3de13ff135` |
| `BPRJ` | `FireRed_j.gba` | `e2cdfb0415ef09e887e9d27b925ff02a713a92f004843490cf6b88b68db6cd01` |
| `BPRS` | `FireRed_s.gba` | `d4dee5aeb5313e073d6067bee37278b0204886958467633978bb746bbe3d5b76` |
| `BPGD` | `LeafGreen_d.gba` | `eb0e340b5efb3ccb7bab104183d2050fa834261dd816c5ad8221e4e98c04342b` |
| `BPGE` | `LeafGreen_e.gba` | `993a8a5695a4f7e4dfe8ceec55beb43e020e82b492854d457d4aa3f864d20f08` |
| `BPGF` | `LeafGreen_f.gba` | `751346c16c0cf3a3ec601d6c2d3c482b54609c5d00ca74f2f668d75b31b8efde` |
| `BPGI` | `LeafGreen_i.gba` | `b99b9c58c83a61b5bd8a1a69b6f21ce0cfab8d1f6065b53b81a323801c9b2895` |
| `BPGJ` | `LeafGreen_j.gba` | `a2aa939a23a36610902be51169042efac78f2f6db6a433e06443a2ee09d4f19e` |
| `BPGS` | `LeafGreen_s.gba` | `a943ecfd6560115b184dc244daed71ba328a67334f343eb35b39932c3ce7c731` |

| symbol | German FireRed | German LeafGreen | Italian FireRed | Italian LeafGreen | Spanish LeafGreen |
|---|---|---|---|---|---|
| `gmain` | `0x030022D0` | `0x030022D0` | `0x030022D0` | `0x030022D0` | `0x030022D0` |
| `sb1ptr` | `0x03004228` | `0x03004228` | `0x03004228` | `0x03004228` | `0x03004228` |
| `sb2ptr` | `0x0300422C` | `0x0300422C` | `0x0300422C` | `0x0300422C` | `0x0300422C` |
| `rng` | `0x03004220` | `0x03004220` | `0x03004220` | `0x03004220` | `0x03004220` |
| `vblank_intr` | `0x08000730` | `0x08000730` | `0x08000730` | `0x08000730` | `0x0800071C` |
| `create_mon` | `0x08041178` | `0x08041178` | `0x08041164` | `0x08041164` | `0x08041164` |
| `client_run_buffer_script` | `0x08148BA4` | `0x08148B80` | `0x08148BE4` | `0x08148BC0` | `0x08148CAC` |
| `save_slot_layout` | `0x083FCEC0` | `0x083FCCFC` | `0x083F464C` | `0x083F4488` | `0x083F7674` |

The ROM-backed tests run each cartridge's `Client_RunBufferScript`, `CreateMon`, `GetVarPointer`,
`VBlankIntr`, saved-hook loader and collision functions under Unicorn, and every card under mGBA.

### Japanese layout

Japanese FireRed and LeafGreen use a different EWRAM layout:

| symbol | Japanese |
|---|---|
| party, party count | `0x020241E0`, `0x02023F85` |
| player avatar, object events | `0x02036FA8`, `0x02036D68` |
| palette fade, wild-encounter disable byte | `0x020379E8`, `0x02038624` |
| `gSpecialVar_0x8000` | `0x02036FE8` |
| `gMain`, `gIntrTable[4]` | `0x030022E0`, `0x03002740` |
| `gRngValue`, `gSaveBlock1Ptr`, `gSaveBlock2Ptr` | `0x03004230`, `0x03004238`, `0x0300423C` |

`RunTextPrinters` (`0x08002D38`) reads its array at `0x02020030` with a `0x20` stride (`0x24`
internationally).

SaveBlock1 is `0x3D40` bytes (`0x3D68` internationally); sector id 4 covers `0xEC0` bytes (`0xEE8`).
`RamScript` keeps checksum `0x361C`, magic `0x3620`, body `0x3624`.

Wonder Cards are 164 bytes and Wonder News 224. `SaveWonderCard` is `0x081481F4` (`BPRJ`) /
`0x081481CC` (`BPGJ`), validation `0x08148250` / `0x08148228`. Card CRC at SaveBlock1 `+0x3204`, data
at `+0x3208`, news at `+0x3124`. `BufferCardText` (`0x08149934`) reads title bytes 10..27, subtitle
28..40, four 20-byte body lines at 41..120 and two 20-byte footers at 121..160. The native `.wc3`
layout is in [Gift files](gifts.md#native-formats).

The Wonder Cards and Wonder News accept lists hold activities 6 and 7 (`BPRJ` `0x08410EC4`,
`0x08410EC8`; `BPGJ` `0x08410E4C`, `0x08410E50`) where every other cartridge holds 21 and 22
[src/data/union_room.h:405-406]. The accepted RFU serials are `{0x0002, 0x7F7F}` (`BPRJ`
`0x083FC378`). All twelve titles list `0x01006fa0233f8000` as their first local communication id.

Japanese names use the kana table and a five-character trainer-name limit; Latin accents share
byte values with kana, so built-in gift prose drops accents and wraps at 26 characters, two lines a
page. `CreateMon` names species 25 ピカチュウ. The Japanese Team cards use their source's Japanese
struct sizes; two prompts are shortened.

### Retail verification

| cartridge | verified on retail hardware | source |
|---|---|---|
| Italian LeafGreen (`BPGI`, revision `0x0A`) | All 41 `Build` fields match console memory; follower installation; Master Ball card and item delivery | [Contributor verification](https://github.com/Decryptu/pokeldn/issues/13) |

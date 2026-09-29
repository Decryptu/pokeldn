---
title: The ROM map
parent: FireRed and LeafGreen
nav_order: 4
---

# The ROM map

Every address here was read off the console's own cartridge through the Mystery Gift link
(`memory-dump`, `memory-scan`, `table-scan`, `call-chain`, on [Code on the console](frlg_rom.md)).
`pokeldn/frlg/rom/rom_map.py` records how each was obtained; `tests/test_rom_map.py` checks it against
the dumps. The cartridge image, read later, confirms them.

Addresses are French FireRed, cartridge BPRF, software version 0x0A. LeafGreen's are on
[LeafGreen](frlg_leafgreen.md).

## The cartridge image

The Switch release carries the GBA ROM as the only file in its RomFS.

| title id | RomFS file | size | sha1 |
|---|---|---|---|
| 01004B3023412000 | `/FireRed_f.gba` | 16777216 | `07566b82dbd2a91321698f730f6400ae4c56ddf1` |
| 010087C02342E000 | `/LeafGreen_f.gba` | 16777216 | `9f774956dfbad7f69ddb91fb91d2c26e54408f75` |
| 0100554023408000 | `/FireRed_e.gba` | 16777216 | `baa452d0b24629dd7782cfc07a8984085dde1311` |
| 010034D02340E000 | `/LeafGreen_e.gba` | 16777216 | `62b9fc77549dbc67032eb6cbd0ea6ad3b825690f` |

The header at 0xA0 reads `POKEMON FIRE` `BPRF` and `POKEMON LEAF` `BPGF`, version 0x0A.

The French FireRed 1.0.1 update leaves the cartridge unchanged. Its guest ROM, read on a retail console
through `rom-checksum` and a byte read of the one differing stretch, equals `FireRed_f.gba` across
`0x08000000..0x09000000` apart from the wrapper's three load-time patches ([frlg_rom.md](frlg_rom.md),
The breakpoint hooks); `0x09000000..0x0A000000` reads the open bus (each halfword its own address
halved) on both.

The English pair (`BPRE`, `BPGE`, version 0x0A, base v0 packages) is byte-identical to
`pokefirered_switch.gba` and `pokeleafgreen_switch.gba` as `pret/pokefirered` pins them: the decomp is
an exact map of the English release.

The Program NCA has one CTR RomFS section and no update, so `bktr_read.py` refuses it;
`scratchpad/base_romfs.py` reads it:

    ./.venv/bin/python scratchpad/base_romfs.py "$NSP" --list
    ./.venv/bin/python scratchpad/base_romfs.py "$NSP" --extract /FireRed_f.gba --out scratchpad/FireRed_f.gba

`rom_map.CREATE_MON` is 0x08041150 and the image reads `f0b5 4746 80b4 87b0` there, the prologue the
`create-mon` payload was written against. A body nobody has dumped is readable offline.

## EWRAM is at the same addresses in both builds

The English build's EWRAM symbols are the French cartridge's EWRAM addresses. Three measured
independently agree with `pokefirered_switch.elf`:

    gDecompressionBuffer  0x0201C000
    gPlayerParty          0x02024280
    gPlayerPartyCount     0x02024025

IWRAM does not transfer: `gSaveBlock1Ptr` is 0x030042D8 in the English build and 0x03004228 on the
cartridge.

Every sized EWRAM symbol in the ELF, subtracted from the region, leaves one span no symbol claims, in
every game state (`nm -S pokefirered_switch.elf`, `scratchpad/ram_survey.py`):

    highest symbol end   0x0203FBAC
    EWRAM end            0x02040000

## The English cartridges

The Mystery Gift host sends English FireRed (`BPRE`) and English LeafGreen (`BPGE`) code built on their
own addresses. `pokeldn/frlg/rom/builds.py` holds one table per cartridge (`BPRF`, `BPGF`, `BPRE`,
`BPGE`): the IWRAM globals, the ROM functions a payload, hook or field stub calls, the functions
`call-chain` names, and the ROM data pointers a gift carries.

The host picks the table from the game code in the console's `MysteryGiftLinkGameData`
[mystery_gift.c:369], which arrives before anything address-dependent is sent. A payload whose bytes
differ between builds is built for each; a console with no table, or one the run excludes
(`--console-build CODE`, or `--version` against the other version), is refused with nothing sent. A
build-independent payload goes to any console.

English addresses come from `pokefirered_switch.elf` and `pokeleafgreen_switch.elf`, each checked
against the retail image: a function by its bytes, an IWRAM global by the literal pools that use it,
paired with the same pool on the French cartridge.

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
(0x081E07C4 against 0x081E07E8).

`tests/test_frlg_english_cartridges.py` runs the English payloads on both retail images through each
cartridge's own `Client_RunBufferScript`; it skips when `scratchpad/frlg_en/` holds no image.

An emulated English FireRed (USA v0, `0100554023408000`) reports `BPRE`, takes and shows a Wonder Card,
and runs an English `call-chain`: `SpeciesToNationalPokedexNum` at `0x08046A41` returned 252 for species
277, `VarGet` at `0x08071CD5` returned. The game saves after both.

## The BIOS wrappers

`libagbsyscall.s` links as one block of THUMB `svc N ; bx lr` pairs in the decomp's order
[src/libagbsyscall.s], identical on both cartridges and 0x24 lower on LeafGreen:

| wrapper | svc | FireRed | LeafGreen |
|---|---|---|---|
| `ArcTan2` | 0x0A | 0x081E21D4 | 0x081E21B0 |
| `BgAffineSet` | 0x0E | 0x081E21D8 | 0x081E21B4 |
| `CpuFastSet` | 0x0C | 0x081E21DC | 0x081E21B8 |
| `CpuSet` | 0x0B | 0x081E21E0 | 0x081E21BC |
| `Div` | 0x06 | 0x081E21E4 | 0x081E21C0 |
| `LZ77UnCompVram` | 0x12 | 0x081E21E8 | 0x081E21C4 |
| `LZ77UnCompWram` | 0x11 | 0x081E21EC | 0x081E21C8 |

The game's LZ77 streams are VRAM-safe (no copy distance of 1): Bulbasaur's front sprite at 0x08D2FBD4
(676 bytes) and palette at 0x08D2FE78 (40 bytes) on FireRed are byte for byte what `gbagfx` writes from
the decomp's sources. LZ77 does not shrink payload code (the resident hooks come out as large or
larger); it helps only data over 1024 bytes.

## The first anchor

`anchors` returns the address after `Client_RunBufferScript`'s call, `0x08148C75`. Everything else grew
from there: dump a caller, disassemble it, read its literal pool and `bl` targets, dump any pointer table
it names, check every entry lands on a known prologue (`scratchpad/rom_read.py`).

A dump at 0x08148A00 disassembles as `Client_RunBufferScript` [mystery_gift_client.c:274], `cmp r0,#1`
at 0x08148C74. Its literal pool:

    0x08148C88 -> 0x0201C000   gDecompressionBuffer
    0x08148C8C -> 0x0300422C   &gSaveBlock2Ptr
    0x08148C90 -> 0x03004228   &gSaveBlock1Ptr

`MysteryGiftClient_CallFunc` follows at 0x08148C94 and copies eight words from 0x0845DBD0 (sClientFuncs)
indexed by `client->funcId` at `[r0,#8]`. All eight land on a `push {r4, lr}`; entry 7 is 0x08148C61,
the function `anchors` measured.

The cartridge header, dumped at 0x08000000, confirms the `REVISION >= 0xA` branches run:

    entry      b 0x08000204
    title      POKEMON FIRE          [0xA0]
    game code  BPRF                  [0xAC]  BPR = FireRed, F = French
    version    0x0a                  [0xBC]
    header checksum 0x5d, recomputed 0x5d -> VALID

## The four function tables

    gScriptCmdTable              0x08163650   214 entries   the field script commands
    gSpecialVars                 0x081639A8    21 entries
    gSpecials                    0x081639FC   444 entries   gSpecialsEnd 0x081640EC
    gStdScripts                  0x081640EC    10 entries
    gMysteryEventScriptCmdTable  0x081DE144    17 entries

`script_data` runs from 0x08163650 to 0x081DE188, where `lib_text` starts.

### `gSpecialVars`, found by shape

Its first twelve words each sit exactly 2 above the one before: `gSpecialVar_0x8000` through `0x800B`
are twelve consecutive `u16`s [event_data.c:16]. `table-scan` returns the run's start and first value
in one run: `gSpecialVars` = 0x081639A8, `gSpecialVar_0x8000` = 0x020370B4, the only such run in
2.75 MB. The range came from link order: `script_data` follows every `.text` object
[ld_script_rev10.ld:318] and `.rodata` starts below `gSpeciesInfo`. `gSpecialVar_0x8000` is
`EWRAM_DATA`, a link-time global safe to name as a constant.

### `gScriptCmdTable`, derived rather than searched

`script_data` opens with `gScriptCmdTable` (214 four-byte entries) and puts `gSpecialVars` right after it
[ld_script_rev10.ld:318], so it starts at 0x08163650 and one 856-byte dump reads it. All 214 words are
THUMB pointers into a 10488-byte span; the only two sharing an address are 0 and 213, the two
`ScrCmd_nop`s, with `ScrCmd_nop1` distinct at 1. A read one entry off cannot produce that.

    0x23 callnative   0x0806D854      0x44 additem      0x0806DED0
    0x25 special      0x0806D7EC      0x79 givemon      0x0806F834
    0x29 setflag      0x0806E0EC      0x90 addmoney     0x0806F998

`pokeldn/frlg/rom/scrcmd_names.py` names every entry by opcode; `scrcmd_names.handler("additem")`
answers offline.

### `gSpecials` and `gStdScripts`

`ScrCmd_special` indexes `gSpecials` with a u16, bounds-checks against `gSpecialsEnd` and calls through
a veneer [scrcmd.c:101]. Its literal pool gives `gSpecials` = 0x081639FC and `gSpecialsEnd` =
0x081640EC: 0x6F0 = 444 × 4, the 444 entries of `data/specials.inc`, starting at `gSpecialVars + 21 * 4`.
The call goes through 0x081E2224, four bytes below `_call_via_r1`. The dump gives 444 THUMB pointers,
the 171 `NullFieldSpecial` indices one address across two dumps. `rom_map.SPECIAL_ADDRESSES` holds them;
`rom_map.special_function("HealPlayerParty")` resolves one by name.

`gStdScripts` follows `gSpecials` in `data/event_scripts.s` under an `.align 2` already satisfied, at
0x081640EC: ten words into 0x081A76xx..0x081AB5xx, the five msgbox scripts within forty bytes of each
other.

### `gMysteryEventScriptCmdTable`, via a live struct

The table's 17 entries are unrelated addresses, but its address is kept in a struct:

```c
static void InitMysteryEventScript(struct ScriptContext *ctx, u8 *script)
{
    InitScriptContext(ctx, gMysteryEventScriptCmdTable, gMysteryEventScriptCmdTableEnd);
```

[mystery_event_script.c:52]. `struct ScriptContext` keeps the pair at +0x5C and +0x60
[include/script.h], 68 apart, and the context is `EWRAM_DATA static struct ScriptContext
sMysteryEventScriptContext` [mystery_event_script.c:27]. `table-scan --table-delta 0x44 --table-runlen 2`
over EWRAM finds it; the scan must follow a Mystery Event gift in the same boot, since the context is
zero until a script runs.

All 256 KB of EWRAM in 86 calls gave one hit, at 0x0203AA94 holding 0x081DE144:
`sMysteryEventScriptContext` = 0x0203AA38, the table = 0x081DE144. The 17 entries are odd, distinct,
inside `.text`, span 1084 bytes, and follow the order of `mystery_event.OPCODE_NAMES`, which was written
from the console's behaviour:

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

`data/mystery_event_script_cmd_table.o(script_data)` is the last member of `script_data`
[ld_script_rev10.ld:318-330]; 0x081DE188 reads `0x4C41B510`, `push {r4, lr}`, the prologue of
`libgcnmultiboot`, first in `lib_text`.

## From a table entry to the function behind it

A handler takes a `struct ScriptContext *` and reads its arguments from the script. Its `bl` targets in
address order are the decomp's calls in source order (`VarGet(ScriptReadHalfword(ctx))` per argument,
then one call [scrcmd.c:463-590]), so one dump names the workers by position:

    ScriptReadHalfword   0x0806D1E8      AddBagItem           0x0809DA70
    VarGet               0x08071DDC      RemoveBagItem        0x0809DBC4
    GetVarPointer        0x08071CC8      CheckBagHasSpace     0x0809D9EC
    FlagSet              0x08071EF4      CheckBagHasItem      0x0809D92C
    FlagClear            0x08071F1C      AddPCItem            0x0809DDB4
    FlagGet              0x08071F44      IncrementGameStat    0x080587A4

`ScrCmd_additem` matches the decomp instruction for instruction (the `(u8)quantity` cast is
`lsls r1, #24; lsrs r1, #24`) and stores through 0x020370CC, `gSpecialVar_Result`. `ScrCmd_random`'s
third call is 0x080486B0, `Random`, found independently from its own literal pool.

`scratchpad/handler_workers.py` prints each handler's `bl` targets in order, naming known ones.
`tools/frlg/rom_functions.py --table specials|field|mystery-event|callable` does it across a table,
bounding each body by the next entry and its own epilogue, and prints the next run's plan: unheld
entries clustered into ranked `--dump-address` windows.

The ROM is agbcc-built and ends a THUMB function `pop {r4,r5,r6}; pop {r1}; bx r1` (BC70 BC02 4708),
never `pop {..., pc}`. A reader looking only for 0xBDxx walks into the next function (one 4-call handler
came back with 25 `bl` targets). `pokeldn/frlg/rom/thumb.py` also matches `bx Rn` and treats a return as
a boundary only when a prologue follows.

### Naming 300 workers offline

`scripts/gen_worker_names.py` zips every dumped body against the decomp, all four tables at once, and
writes `pokeldn/frlg/rom/worker_names.py`. Four checks:

| check | what it rules out | what it cost |
|---|---|---|
| length | inlining, `__umodsi3`, a macro read as a call | 22 bodies dropped |
| anchor | a misaligned body: every measured address must land back on its own name | 1 body dropped |
| agreement | a target named differently by two callers | 0 |
| link order | a name in the wrong place in the ROM | 1 address dropped |

Across the 164 aligned bodies the anchor check lands on 68 distinct measured names, 557 times, each on its
own address. agbcc emits a translation unit in definition order and `ld_script_rev10.ld:53` lists the
objects in layout order, so names and anchors form one ascending sequence; the check keeps the longest
ascending chain, not the first break.

A gap between two anchors holding exactly one unnamed target and one source call is forced and relaxes
the length rule. An open gap (before the first anchor, after the last) names nothing.

Reading the source:

- `firered_switch` is `GAME_VERSION=FIRERED GAME_REVISION=10 MODERN=0` [Makefile:227]: the 203
  `#if REVISION >= 0xA` blocks are live, their `#else` is not.
- Evaluation is post-order: `VarGet(ScriptReadHalfword(ctx))` is `bl ScriptReadHalfword` then `bl VarGet`.
- A macro is not a call: `#define ScriptReadByte(ctx) (*(ctx->scriptPtr++))` [include/script.h:24] put a
  phantom `bl` in 151 bodies; removing it took the names from 136 to 180.
- `NDEBUG` holds: `ScrCmd_special` makes two calls on the cartridge, and the assert would add a third.

Names coined here that the decomp already has, confirmed by every body reaching the address
(`rom_map.DECOMP_NAMES` is the join):

| this project | the decomp | bodies agreeing |
|---|---|---|
| `GET_MON_DATA` | `GetMonData3` | 15 |
| `SCRIPT_CONTEXT_SET_NATIVE` | `SetupNativeScript` | 11 |
| `SET_RESPAWN` | `SetLastHealLocationWarp` | 1 |
| `SCRIPT_MOVEMENT_START` | `ScriptMovement_StartObjectMovementScript` | 2 |
| `CHANGE_AMOUNT_MONEY_BOX` | `ChangeAmountInMoneyBox` | 2 |
| `ME_CHECK_COMPATIBILITY` / `ME_SET_INCOMPATIBLE` | `CheckCompatibility` / `SetIncompatible` | 1 / 3 |

`GetMonData` is a macro dispatching on argument count [include/pokemon.h:343]; `GetMonData2` is
`__attribute__((alias("GetMonData3")))` [pokemon.c:2970]: one address, three names.

A worker reached by exactly as many commands as the decomp says call it is a measurement: `Compare` came
back with the eight `compare_*` commands, `StringCopy` with the seven `buffer*` ones plus the two specials
that build a name from `gText_BigGuy`. `0x0806D0EC` is `StopScript(ctx)` [script.c:76], `ScrCmd_end`'s
call; `ScriptContext_Stop(void)` [:360] is 0x0806D418, called by twelve handlers and the whole of
`ScrCmd_waitstate` besides `return TRUE`.

### Two mixed-image hazards

- Never read two cartridges' dumps as one image. LeafGreen keeps this code −0x2C away, so a LeafGreen
  dump placed at its FireRed `--dump-address` answers wrongly: a mixed image made `gSpecials[54]`
  (`Script_HasTrainerBeenFought`, `FlagGet(GetTrainerAFlag())`) call `FlagSet`, which is
  `SetBattledTrainerFlag2` at +0x2C. `script_read.every_dump` takes one cartridge (FireRed by default),
  from the run's `--expect-console`, falling back to the tag.
- Read every dump at once. `scrcmd.Memory` merges overlapping and adjacent dumps so a block straddling
  two runs still walks (`tools/frlg/script_read.py --with-every-dump`); one dump at a time proposes runs
  for bytes already held.

### What is measured

Every body behind every table is off the cartridge: 213 field commands, 17 Mystery Event opcodes, 27
callable functions, 272 specials.

- `NullFieldSpecial` is `bx lr`, two bytes, at 0x080CE8DC.
- The special vars are in id order, two bytes each: `ShakeScreen` [310] loads 0x020370BC, BE, C0, C2,
  and the decomp's reads `gSpecialVar_0x8004..0x8007`; `GetPlayerXY` [143] writes the first two,
  `GetPartyMonSpecies` [327] reads the first.
- `GetLeadMonIndex` at 0x080CE818 is not in the table; four lead-mon specials call it.
- A one-load special names a global: `GetBattleOutcome` [180] is `ldr; ldrb; bx lr`, its pool word is
  `gBattleOutcome`. The same gave `gStringVar1`, `gStringVar4` (`ShowFieldMessageStringVar4` [141]).
- The tables cross-check: specials name 0x08081CC8 `DoDiveWarp` and 0x08081DA0 `DoFallWarp`, as the
  warp workers do; `CalculatePlayerPartyCount` is special 131 and `ScrCmd_getpartysize`'s one call;
  `GetPlayerFacingDirection` is special 287 and `ScrCmd_faceplayer`'s first.

The Mystery Event VM's workers:

| worker | address | called by |
|---|---|---|
| `StringExpandPlaceholders` | 0x0800CADC | the last call of every handler that leaves a message |
| `RunScriptImmediately` | 0x0806D438 | `runscript`, after `ScriptReadWord`, nothing else |
| `InitRamScript` | 0x0806D5F0 | `initramscript` |
| `GiveGiftRibbonToParty` | 0x080A43B0 | `giveribbon`, first of two |
| `EnableRareWord` | 0x080C1658 | `addrareword`, first of two |
| `CheckCompatibility` | 0x080DE300 | `checkcompat`, before the branch |
| `SetIncompatible` | 0x080DE330 | `checkcompat`'s else; the only call either dead opcode makes |
| `memcpy` | 0x081E44F4 | `addtrainer`, second call |
| `CalcCRC16` | 0x080489A0 | `crc`, its only worker |
| `StringCopyN` | 0x0800C8CC | `setenigmaberry` and `givepokemon`, twice each |
| `StringCompare`, `SetEnigmaBerry` | 0x0800C938, 0x080A01B0 | `setenigmaberry` |
| `VarSet` | 0x08071DF8 | `setenigmaberry`, last call |
| `SpeciesToNationalPokedexNum` | 0x08046994 | `givepokemon` |
| `GetSetPokedexFlag` | 0x0808C860 | `givepokemon`, twice: SEEN then CAUGHT |
| `ItemIsMail`, `GiveMailToMon2`, `CompactPartySlots` | 0x0809BB18, 0x0809B964, 0x080971FC | `givepokemon` |

`memcpy` (libgcc, in `lib_text`) at 0x081E44F4 sits above 0x081DE188, agreeing with the boundary.

`VarSet` is reachable only from here: no ScrCmd body calls it (`setvar` stores through
`GetVarPointer`'s result, hence `call-chain`'s `prev`). `event_data.c` declares `GetVarPointer`,
`VarGet`, `VarSet` in that order, at 0x08071CC8 < 0x08071DDC < 0x08071DF8; the 0x1C between the last
two is `VarGet`'s body.

The call veneers are `bx rN` plus alignment, four bytes each: r0 0x081E2224, r1 0x081E2228 and r3
0x081E2230 measured, so 0x081E2234 is `_call_via_r4` and 0x081E223C `_call_via_r6` (the link-order check
rejected a `game_clear.c` name for 0x081E2234).

# Reading the console's scripts as scripts

With `gScriptCmdTable` measured and operand widths generated from the decomp's macros
(`scripts/gen_scrcmd_args.py` → `pokeldn/frlg/rom/scrcmd_args.py`: each `.macro` emits its opcode as a
`.byte`, then a `.byte`/`.2byte`/`.4byte` per argument), `memory-dump` plus `scrcmd.disassemble` reads
any script in the cartridge:

    0x081A7624  6A  lock
    0x081A7625  5A  faceplayer
    0x081A7626  67  message 0x00000000
    0x081A762B  66  waitmessage
    0x081A762C  6D  waitbuttonpress
    0x081A762D  6C  release
    0x081A762E  03  return

This is `Std_MsgboxNPC` [data/scripts/std_msgbox.inc]. The proof is where each script stops: a walk from
each `gStdScripts` entry must end on a terminator at the byte before the next; a width wrong by one
anywhere desynchronises it.

## The conditional macros

Eleven macros have conditional bodies. The generator walks each branch and raises on an unknown
sub-macro.

| command | width | structure |
|---|---|---|
| `applymovement` | 7 bytes | `.ifb \map` branch |
| `waitmovement`, `removeobject`, `addobject` | 3 bytes | `.ifb \map` branch |
| `applymovementat`, `waitmovementat`, `removeobjectat`, `addobjectat` | 9, 5, 5, 5 bytes | alternate branch |
| `warp` and the eight other warps | 8 bytes | `formatwarp` sub-macro |
| the ten `buffer*` commands | 4 bytes | `stringvar` sub-macro |
| `showobjectat`, `hideobjectat`, `resetobjectsubpriority` | 5 bytes | `map` sub-macro |
| `trainerbattle` | 6 + 4..16 bytes | type-dependent branch |

`warp` is `.byte 0x39` then `formatwarp`: one instruction, callee inlined. `giveitem` is `loadword` then
`callstd`: two instructions, never inlined. A macro is a command macro only when every route through it
starts with its own literal opcode byte and reaches no other command macro.

`trainerbattle` has a head of type, trainer and localId, then one to four pointers chosen by the type. It
is `scrcmd_args.VARIABLE`; a type outside the decomp's ten makes `scrcmd.shape` answer `None`.

0x081A7699..0x081A77A3 is `data/scripts/trainer_battle.inc`. Before the conditional macros:

    0x081A76A8  4F  applymovement 0x800F, 0x081A77B0, 0x51, 0x0000, 0x36800D26
    0x081A76B6  00  nop
    0x081A76B7  21  compare_var_to_value 0x800D, 0x0000

After:

    0x081A76A8  4F  applymovement 0x800F, 0x081A77B0     @ VAR_LAST_TALKED, Movement_RevealTrainer
    0x081A76AF  51  waitmovement 0x0000
    0x081A76B2  26  specialvar 0x800D, 0x0036            @ VAR_RESULT, Script_HasTrainerBeenFought

which is `EventScript_TryDoNormalTrainerBattle` [data/scripts/trainer_battle.inc:8]. The region is
labels end to end and gives seven boundary tests; `goto` is a terminator alongside `end` and `return`,
since `EventScript_NoTrainerBattle` sits on the byte behind one [:17]. The five standard scripts use only
seven fixed-width commands, too few to prove the table; all 266 bytes of the trainer-battle region are a
fixture in `tests/test_script_cmd_table.py`.

## Naming the operands

`tools/frlg/script_read.py DUMP.bin --base ADDR`:

    0x081A76A8  4F  applymovement 0x800F (VAR_LAST_TALKED), 0x081A77B0
    0x081A76B2  26  specialvar 0x800D (VAR_RESULT), 0x0036 (Script_HasTrainerBeenFought)
    0x081A76BC  06  goto_if 0x05 (!=), 0x081A76CD
    0x081A76C2  25  special 0x0038 (PlayTrainerEncounterMusic)

- An operand of 0x4000 or more is a variable reference in any command: `VarGet` returns the number
  unchanged below `VARS_START` and reads the variable at or above it [event_data.c:235,
  `GetVarPointer`:214]. `additem 0x8004` gives the item id held in `VAR_0x8004`.
  `pokeldn/frlg/rom/symbol_names.py` has the 274 var and 1470 flag names, evaluated from
  `include/constants/vars.h` and `flags.h`.
- The table an index reaches comes from the macro parameter name: `scrcmd_args.PARAMS` names each
  operand (`special`'s is `function`, `setflag`'s is `flag`). `function` is shared: `ScrCmd_special`
  reads a u16 into `gSpecials`, `ScrCmd_callstd` a u8 into `gStdScripts`.
- `goto_if 0x05` is `!=`: `sScriptConditionTable`'s rows are <, =, >, <=, >=, != [scrcmd.c:65].

The Altering Cave counter moves at SaveBlock1 + 0x1048; `GetVarPointer` is `vars[idx - VARS_START]`, so
that is var 0x4024, `VAR_ALTERING_CAVE_WILD_SET`. `tests/test_script_symbols.py` holds the names to it.

## Following a script to what it reaches

`scrcmd.follow` chases every `goto`, `call`, `goto_if` and `call_if` from a set of entry points and
collects every address reached that the dump does not hold. A data pointer (`text`, `movements`, a
multichoice list) is reported, never followed. `scrcmd.dump_plan` turns the misses into
`--dump-address` lines, biggest catch first.

`charmap.decode` is for a name (fixed width, no control codes, unknown bytes as `.`); dialogue needs
`charmap.decode_message`. `scrcmd.data_pointers` and `scrcmd.read_string` decode what the dumps hold. All
ten standard scripts are read off the console, code and text.

A known command whose operands run past the dump's end means the dump is short, and the reader says so.

# The species table

`gSpeciesInfo` = 0x0824CDFC, stride 28.

A needle of `friendship`, `growthRate` and `eggGroups` at the decomp's 26-byte stride (widest member
`u16`) matched nothing in 16 MB. The data itself matches the English decomp: `CalculateMonStats`
[pokemon.c:2095] recomputed from five party mons' base stats, level, IVs, EVs and nature reproduced 30 of
30 stored stats.

Mew, Celebi and Jirachi have all six base stats at 100, so `0x64646464` sits at entry offsets 0 and 2,
one of them word-aligned whatever the stride:

    scan: 3 match(es) for 0x64646464 in 0x08000000..0x08400000
       0x0824DE80   0x0824E970   0x0824FAB8

The gaps, 2800 and 4424, are 100 and 158 entries of 28 bytes. A dump from 60 bytes before the base read
34 of 34 entries (884 bytes) identical to the decomp; the two extra bytes are `00 00` padding on every
entry.

Traps in modelling the decomp: `[SPECIES_NONE] = {0},` is a one-line block a multi-line regex swallows,
`genderRatio` is the macro `PERCENT_FEMALE(x)`, `noFlip` is a bitfield not always set, and hex
`#define`s escape a decimal-only regex.

## Finding `CreateMon` from it

Scanning for `0x0824CDFC` finds every literal pool holding `&gSpeciesInfo`: 31 hits in
`0x08028000..0x08048800`, below `Random` at 0x080486B0. Five sit exactly `0x14` apart, one function with
several pools, so the count is no evidence; object boundaries are. The largest gap (37 KB) is not the
`pokemon.o` boundary: the hit above it is `battle_ai_switch_items.c:88`. The next gap, 15.6 KB, is
`src/battle_controller_link_opponent.o`, which never references `gSpeciesInfo`.

The first hit of `pokemon.o`'s block is `CreateMon` [pokemon.c:1755], instruction for instruction:

| symbol | address | how |
|---|---|---|
| `CreateMon` | `0x08041150` | the disassembly |
| `ZeroMonData` | `0x08041090` | its first call |
| `CreateBoxMon` | `0x080411C0` | its call between ZeroMonData and SetMonData |
| `SetMonData` | `0x08043A78` | called with 56 (`MON_DATA_LEVEL`), then 64 (`MON_DATA_MAIL`) with 255 (`MAIL_NONE`) |
| `CalculateMonStats` | `0x08041B78` | its last call |

# The French Easy Chat vocabulary

All 1006 language-dependent Easy Chat words are read out of the console's ROM.
`pokeldn/frlg/text/easychat_french_words.py` is the table; `easychat_french.french(id)` answers from it.

## The problem

An Easy Chat id is `(group << 9) | index`, a slot. `pokeldn/frlg/text/easychat_words.py` comes from the
English decomp and names what the English ROM keeps there; each localized ROM has its own
`gEasyChatGroup_*` tables. Mail, the trainer card quote, the visiting trainer's lines,
`--denied-message` and the questionnaire gate all depend on the French one. Rendered on the console,
`EC_WORD_ENJOY` printed STRESSE, `EC_WORD_DONE` FURAX, `SPEECH/12` LES.

## Finding the table

`sEasyChatGroups[]` is 22 entries of
`struct EasyChatGroup { const void *wordData; u16 numWords; u16 numEnabledWords; }`
[src/data/easy_chat/easy_chat_groups.h:26], 8 bytes each. Groups 8, 9 and 10 (Endings, Feelings,
Conditions) hold 69 words, 69 enabled, so `0x00450045` appears three times 8 bytes apart.
`--buffer-script memory-scan --scan-word 0x00450045` over 0x08000000..0x08480000 returned exactly those
three hits. The range: `src/easy_chat.o(.rodata)` is object #99 in `ld_script.ld`, below
`src/mystery_gift_client.o(.rodata)` (#182, `sClientFuncs` known). The table is at 0x083E3700.

All 22 entries have counts identical to the English build's, so an id is the same slot in both languages.
The word arrays and their text span 0x083DE2C8..0x083E3700, 21560 bytes, each group's strings between
its array and the next. `string-gather` reads one group per run; entries 42 and 60 are STRESSE and FURAX,
as rendered. `tests/test_easychat_french.py` requires render and ROM evidence to agree.

`TRAINER/11` is DRESSEUR, singular; DRESSEURS is not in the table.

## What the table says

Divergence from the English table depends on the group:

- `EC_GROUP_STATUS` (109 Ability names) is nearly exact: `stench`→PUANTEUR, `thick_fat`→ISOGRAISSE,
  `rain_dish`→CUVETTE, `drizzle`→CRACHIN, `arena_trap`→PIEGE, `rock_head`→TETE DE ROC, `air_lock`→AIR
  LOCK.
- `EC_GROUP_FEELINGS` is almost entirely re-binned: English mixes in verbs (meet, play, eat, drink, see,
  hear, got, goes, go home), French holds only emotional states. Slot 13 (`disappoints`) is RAVI, 44
  (`eat`) HUMILIE, 51 (`drink`) HONTEUX.
- `EC_GROUP_SPEECH`: `but`→MAIS, `however`→CEPENDANT, `how`→COMMENT, `the`→LE line up, and LES and L'
  took the slots English spends on `case` and `miss`.

Proper-noun groups barely moved; ordinary vocabulary moved a lot. An id alone does not tell.

807 slots need no reading: `EC_GROUP_POKEMON`, `POKEMON_2`, `MOVE_1` and `MOVE_2` print from
`gSpeciesNames` / `gMoveNames` [easy_chat.c:155], localized by the console. `easychat.species_word(55)`
and `easychat.move_word(177)` build them; `easychat.is_language_safe` recognises them.

## Using it

```python
from pokeldn.frlg.text import easychat, easychat_french
easychat_french.french(easychat.WORDS["enjoy"])     # 'STRESSE', not 'enjoy'
easychat_french.render(ids)                          # the line as the console will print it
easychat_french.check(ids, strict=True)              # raises on anything unread
```

`check` catches an id that is not a word, such as an index past the end of its group.

    ./scratchpad/run_mg_board.sh <tag> --buffer-script string-gather --gather-address 0x083DF5C0 \
        --gather-count 42 --gather-stride 12 --version firered    # one group per run
    ./.venv/bin/python scratchpad/ec_words.py --group 4 --tag <tag> scratchpad/<tag>_dump.bin
    ./.venv/bin/python scratchpad/ec_words.py --report

`scratchpad/ec_locate.py` finds the table in a scan answer and checks a dump against the decomp's counts;
`scratchpad/ec_words.py` holds the 22 word-array addresses.

LeafGreen's whole Easy Chat region is FireRed's shifted by −0x1C4, with identical vocabulary: 22 entries,
every count equal, and one group's `string-gather` returned 26/26 words in the same slots.
`easychat_french` answers for both consoles.

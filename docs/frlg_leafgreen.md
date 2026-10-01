---
title: LeafGreen
parent: FireRed and LeafGreen
nav_order: 6
---

# LeafGreen, and the two cartridges' offset map

The rest of this section was read off French FireRed (BPRF, version 0x0A). French LeafGreen is
BPGF, 0x0A (`POKEMON LEAF` in its header). Every payload works there unchanged; ROM addresses do not.
The measurements run inside the Mystery Gift menu, so the console never leaves its save point.

## The measured addresses

| symbol | LeafGreen | FireRed |
|---|---|---|
| `gDecompressionBuffer` | 0x0201C000 | same |
| Mystery Gift call site | 0x08148C50 | 0x08148C74 |
| `Random` | 0x080486B0 | same |
| `SeedRng` | 0x080486D0 | same |
| `gRngValue` | 0x03004220 | same |
| `gPlayerParty` | 0x02024280 | same |
| `gPlayerPartyCount` | 0x02024025 | same |
| `gEnemyParty` | 0x02024028 | same |
| `gSpeciesInfo` | 0x0824CDD8 | 0x0824CDFC |
| `CreateMon` | 0x08041150 | same |
| `sEasyChatGroups` | 0x083E353C | 0x083E3700 |
| `gSpecialVar_0x8000` | 0x020370B4 | same |
| `gSpecialVars` | 0x08163984 | 0x081639A8 |
| `gSaveBlock1Ptr` | 0x03004228 | same |
| `gSaveBlock2Ptr` | 0x0300422C | same |

`rom_map.LEAFGREEN` holds these with their evidence; `rom_map.leafgreen(symbol)` raises for a symbol
not in the table instead of falling back to FireRed.

Every IWRAM and EWRAM address measured is identical (link-time globals of the same code); every ROM
address above 0x080486C8 differs. Fifteen symbols confirm it; measure every new one rather than
predicting it.

## The delta is a property of a region

The offset from a FireRed address to its LeafGreen twin is piecewise constant, in at least eight
segments, and not monotonic (the four low segments each diverge four bytes less than the one below):

    +0x0   -0x2C   -0x28   -0x24   -0x20   -0x1C4   -0x124C   -0x1240   -0x12D8

`rom_map.leafgreen_guess(firered_address)` answers inside a measured segment and refuses the gaps. It
aims a dump; it says nothing about content. `pokeldn/frlg/rom/leafgreen_twins.py` holds 738 pairs,
each read off its own cartridge (about 200 are named functions); `leafgreen_twins.leafgreen(address)`
answers exactly where it has a pair and falls back to `leafgreen_guess`.

### The boundaries

    step             span                          what is in it
    0     -> -0x2c   644 B, 0x0807CF68..0x0807D1EC  title_screen.o
    -0x2c -> -0x28    62 B, 0x080DE2E4..0x080DE322  mystery_event_script.o
    -0x28 -> -0x24    90 B, 0x081480CE..0x08148128  mystery_gift.o
    -0x24 -> -0x20    31 B, 0x08251D8E..0x08251DAD  pokemon.o rodata
    -0x20 -> -0x1c4 1209 B, 0x083B7B47..0x083B8000  title_screen.o rodata
    -0x1c4 -> -0x124c  30 KB, 0x0843AFFF..0x08442800  graphics
    -0x124c -> -0x1240 17 KB, 0x08442BFF..0x08447000  graphics
    -0x1240 -> -0x12d8 63 KB, 0x0844F3FF..0x0845F000  graphics

A boundary is the version-divergent region itself, where no delta applies. The span is the last
window matching the old delta to the first matching the new one. `rom_map.LEAFGREEN_DELTA_BOUNDARIES`
holds them; a test asserts the boundary and segment tables agree. Above 0x0843C800 the cartridges
hold different bytes (version-specific graphics), so the delta there is undefined by content.

## The methods, in order of cost

### Paired constants

`RAND_MULT` scanned on both cartridges gave eleven hits each, pairing in order across 1.3 MB.

### A pointer as the needle

Every reference to an address measured on both consoles is a paired point. Scanning each cartridge
for its own `gSpeciesInfo` gave 56 literal-pool references each, ascending, pairing one to one:

| delta | FireRed span | paired hits |
|---|---|---|
| 0 | 0x080001BC .. 0x0805359C | 42 |
| −0x2C | 0x080CBFB0 .. 0x080CE36C | 2 |
| −0x28 | 0x080EBA14 .. 0x0813E8CC | 9 |
| −0x24 | 0x0815A3F4 .. 0x0815A630 | 3 |

No hit lies above 0x0815A630.

### Making a needle where there is no symbol

Above 0x083E3700 nothing has a name. Dump 1 KB off one console; a word occurring exactly once in it
with four distinct bytes fingerprints a place, and scanning the other console for it gives that
place's address there. Two runs a point, anywhere in the ROM:

| FireRed | LeafGreen | needle | delta |
|---|---|---|---|
| 0x086003E0 | 0x085FF108 | 0xE1926F4D | −0x12D8 |
| 0x086803FC | 0x0867F124 | 0xC35D61AE | −0x12D8 |

Each scan returned one match in a 2 MB window. Two agreeing points do not constrain the range
between them; a control must. The script-layer scans:

| needle | taken from | found on LeafGreen at | delta |
|---|---|---|---|
| 0x49050B80 | inside `ScrCmd_special` | 0x0806D7F4 | 0 |
| 0x4831D940 | the top of the handler block | 0x080701C0 | 0 |
| 0x49040A00 | inside the flag/var workers | 0x08071E1C | 0 |
| 0x47708008 | above `FlagGet` | 0x08071FC4 | 0 |
| 0x18210094 | inside `AddBagItem` | 0x0809DA80, FireRed 0x0809DAAC | −0x2C |

Delta 0 is also what a scan of the wrong console answers, so the last row, from above the boundary,
must come back shifted.

### Literal pools, which are free pointer tables

A function keeps the addresses it touches in a pool after its body, so a 1 KB code window is a few
dozen pointers. Placing the window on both cartridges is free where the code's segment delta is
known. m4a code lies in `lib_text` (the −0x24 segment) and its pools point at sound data at the top
of the ROM. Two 1 KB dumps gave 24 pool words each, 13 identical (RAM addresses and constants), and
all five cartridge pointers moved alike:

| FireRed | LeafGreen | delta |
|---|---|---|
| 0x0847DCF8 | 0x0847CA20 | −0x12D8 |
| 0x0847DDAC | 0x0847CAD4 | −0x12D8 |
| 0x0847DF10 | 0x0847CC38 | −0x12D8 |
| 0x0849758C (`gMPlayTable`) | 0x084962B4 | −0x12D8 |
| 0x084975BC (`gSongTable`) | 0x084962E4 | −0x12D8 |

`gMPlayTable` and `gSongTable` are 0x30 apart on both: four twelve-byte `struct MusicPlayer`, as
`sound/music_player_table.inc` holds.

Two 16-block pool pairs gave 550 and 288 paired sites and found the −0x20 segment, which spans more
than a megabyte between −0x24 and −0x1C4. Pair by code offset, never by index: pools of 552 and 550
words paired in order invent deltas (−0x53BADA0) after the first mismatch.

A `bl` is relative, so the same instruction on both cartridges resolves to targets differing by the
delta at the target; a 16 KB handler window holds 834. `tools/frlg/cartridge_pair.py` reads pools and
`bl`s out of every window held on both cartridges: 1592 points, every site paired (734 of 734, 834 of
834), four distinct deltas per window, no outliers.

### Dumping both cartridges at the same address

At a common address with delta d, the LeafGreen block
holds the FireRed block shifted by d; for |d| under a kilobyte, cross-correlation reads d directly.
`memory-dump-scatter` sends the same 27 addresses to both consoles. Inside a block, testing which
delta still matches window by window places a step to the byte: the boundaries of the five code
steps total 2036 bytes, and all 272 specials have a LeafGreen address.

A wide gap may hide several steps: the 421 KB from −0x1C4 to −0x12D8 holds three. Graphics
resembles itself, so each reading is scored against the alternatives: at 0x08442800 −0x124C scores
436/436, −0x1240 6.9%, −0x12D8 2.7%; at 0x08457000 74.7% against 57.3% is recorded as no verdict.

## Reading a LeafGreen dump against FireRed's tables

Every table here was read off FireRed. `tools/frlg/rom_functions.py --console leafgreen` moves the
entries, bodies and names through the measured twins and drops an entry that falls inside a
boundary: 184 of the 213 field bodies and 33 of the 252 placeable specials come back, with the same
three unnamed call targets as FireRed.

The script layer is identical on both cartridges below 0x0807AF04
(`rom_map.SHARED_WITH_LEAFGREEN_THROUGH`): the `gScriptCmdTable` handler block (0x0806D7C0..0x080700B8),
the script engine (`ScriptContext_Stop`, `ScriptJump`, `ScriptCall`, `ScriptReturn`, the native-pointer
setter `callnative` uses), `GetVarPointer`, `VarGet`, `FlagSet`, `FlagClear`, `FlagGet`, and the
`_call_via_r0` veneer.

## The overworld, and a shiny Mewtwo

Every literal in [the seek stubs](frlg_rng.md) is a link-time IWRAM word shared with FireRed
(`gRngValue`, `gSaveBlock1Ptr`, `gSaveBlock2Ptr`), so the stubs run unported. A RAM script needs a map
object to bind to: `initramscript` takes a map group, map number and object id, and `GetRamScript`
runs the script instead of the object's own [field_control_avatar.c:458]. Cerulean Cave B1F is group
1 map 74 [data/maps/map_groups.json]; Mewtwo is object 3 [data/maps/CeruleanCave_B1F/map.json].
`rng-mon-hunt-both` bound there with `setwildbattle` species 150, level 70, replaces Mewtwo's script
and starts an aimed Mewtwo battle at once (verified shiny on retail LeafGreen).

- The stray-draw search works on LeafGreen; the stub reads `TID ^ SID` off `gSaveBlock2Ptr` at run
  time [asm/field/mon-seek-both.s:73].
- The binding survives a power cycle, although `gSaveBlock1Ptr` is re-rolled on every load.
- A buffer script sends no card and leaves the RAM script slot alone. A Wonder Card session takes it
  back: an ordinary card rebinds the slot through `InitRamScript_NoObjectEvent`, and Mewtwo's own
  script returns.

While bound, the console reports holding no Wonder Card; the card stays intact
([the one RAM script slot](frlg_gift.md#the-one-ram-script-slot)).

## A dumped region must not move

A `memory-dump` of 0x03004220 (`gRngValue`, two turns per frame) dies mid-transmission with *erreur
de connexion*: the CRC and the send happen on different frames. A dump of a region that changes
between frames fails its CRC; a ROM region of the same size does not. Mechanism and guard:
[Code on the console](frlg_rom.md#repointing-the-consoles-outgoing-message).

Starting 4 bytes higher reads the save-block pointers. Both move together, by one shared 4-aligned
offset inside the 0..124 range `SetSaveBlocksPointers` rolls [load_save.c:75].

## The English build as an instrument

`pret/pokefirered` builds both cartridges at REVISION 10, the Switch release's revision:

    make firered_switch     -> pokefirered_switch.gba    baa452d0b24629dd7782cfc07a8984085dde1311
    make leafgreen_switch   -> pokeleafgreen_switch.gba  62b9fc77549dbc67032eb6cbd0ea6ad3b825690f

Both match the decomp's sha1 when built with binutils and `pret/agbcc` (about two minutes); a build
that does not match is unusable. The ROM is never committed.

It is the English release: at the same address a French console and the English build agree on 3.7%
of bytes, since French strings differ in length. It serves as a second cartridge pair from the same
source and link order, with every symbol known.

### The offset: French address to English address

Piecewise constant, stepping only where an object changes size between languages; code runs are tens
of kilobytes long, one 1.3 MB. Two independent readings agree everywhere both apply:

- The tables: `gSpecials[i]`, `gScriptCmdTable[i]` and `gMysteryEventScriptCmdTable[i]` are the same
  function on both builds, giving 675 points from existing dumps.
- The dumps: a 16-byte window occurring exactly once in the English ROM places equal French bytes; a
  kilobyte of code votes hundreds of times, and a step inside a block shows as two runs.

      ./.venv/bin/python tools/frlg/english_build.py --offsets

### The control

The English ELF (which carries static functions, unlike the link map) names a French address through
the offset. Against `worker_names`, every name measured off the console's own bodies: 232 agree, 0
disagree. `GetBoxMonData2` is `__attribute__((alias("GetBoxMonData3")))` [pokemon.c:3332]; the reader
keeps every name an address carries.

    ./.venv/bin/python tools/frlg/english_build.py --check

A name from here is a deduction. `rom_map.CALLABLE` means called on hardware with an effect;
`worker_names` means the console's own body called it in source order. `pokeldn/frlg/rom/english_names.py`
holds 7573 French function addresses named this way (`scripts/gen_english_names.py`), with the offset
runs. `rom_functions` reads them last, marked `[english]`, so a deduction never overrules a body the
console named; `gen_worker_names` passes `with_english=False`.

Of 177 unnamed call targets, 158 fall inside a measured offset run and are named. The rest fall
between runs and go to `english_names.BRACKETED`: named with one of the two neighbouring offsets, only
when it lands exactly on a function start and the other does not (`[english?]`). Two are left. Three
targets reached from a dozen bodies each read as `__divsi3`, `__modsi3` and `__umodsi3`, agbcc's
division helpers.

### The English pair's own delta map

The two English ROMs compared give the same six deltas the French cartridges measured, in order:

    +0x0   -0x2c   -0x28   -0x24   -0x20   -0x1c4

Each step lies inside a version-divergent object (`title_screen.o`, `mystery_event_script.o`,
`mystery_gift.o`, `pokemon.o`), where no symbol is common to both builds; byte comparison brackets
each to 79..1606 bytes. Carried across by the offset map, all five predicted French boundaries fall
inside the brackets measured on hardware.

    ./.venv/bin/python tools/frlg/english_build.py --boundaries

### Traps

- A `.gcc2_compiled.` symbol shadows the first function of its file; skip names beginning `.` or `$`.
- Padding matches every delta. Require 16 distinct byte values in a window before a match counts, or
  0xFF filler reads as agreement.
- The offset (French to English, one cartridge) is not the delta (FireRed to LeafGreen):
  `french delta = offsetFR - offsetLG + english delta`.
- Regenerate `english_names.py` with `scripts/gen_english_names.py` after any new dump.

## What did not work

`gSongTable` (347 `{header, ms, me}` entries) packs 122 song headers inside 9 KB, so it measures one
place, not many.

FireRed's ROM data ends between 0x086ABE68 (the last song header) and 0x08800000: 0x08800000 reads
all `0xFF`, 0x08E00000 all `0x00`, 0x08680000 is high-entropy data.

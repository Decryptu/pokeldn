---
title: LeafGreen
parent: FireRed and LeafGreen
nav_order: 6
---

# LeafGreen, and the two cartridges' offset map

French LeafGreen (BPGF, version 0x0A, `POKEMON LEAF`) runs French FireRed's code at a
piecewise-constant ROM offset. Every payload works on it unchanged; ROM addresses do not.

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
not in the table. Every IWRAM and EWRAM address is identical; every ROM address above 0x080486C8
differs. Measure a new ROM symbol; never predict it.

## The delta by region

The FireRed-to-LeafGreen offset is piecewise constant and not monotonic:

    +0x0   -0x2C   -0x28   -0x24   -0x20   -0x1C4   -0x124C   -0x1240   -0x12D8

`rom_map.leafgreen_guess(firered_address)` answers inside a measured segment and refuses the gaps.
`pokeldn/frlg/rom/leafgreen_twins.py` holds 738 measured pairs (about 200 named functions);
`leafgreen_twins.leafgreen(address)` answers exactly where it has a pair and falls back to the guess.

### The divergent spans

    step             span                          what is in it
    0     -> -0x2c   644 B, 0x0807CF68..0x0807D1EC  title_screen.o
    -0x2c -> -0x28    62 B, 0x080DE2E4..0x080DE322  mystery_event_script.o
    -0x28 -> -0x24    90 B, 0x081480CE..0x08148128  mystery_gift.o
    -0x24 -> -0x20    31 B, 0x08251D8E..0x08251DAD  pokemon.o rodata
    -0x20 -> -0x1c4 1209 B, 0x083B7B47..0x083B8000  title_screen.o rodata
    -0x1c4 -> -0x124c  30 KB, 0x0843AFFF..0x08442800  graphics
    -0x124c -> -0x1240 17 KB, 0x08442BFF..0x08447000  graphics
    -0x1240 -> -0x12d8 63 KB, 0x0844F3FF..0x0845F000  graphics

Each span is version-divergent; no single delta applies inside it. `rom_map.LEAFGREEN_DELTA_BOUNDARIES`
holds them, and a test checks them against the segment table. Above 0x0843C800 the cartridges hold
different graphics. `gMPlayTable` is 0x0849758C on FireRed and 0x084962B4 on LeafGreen, with
`gSongTable` 0x30 above it on both.

## Pairing the cartridges

`tools/frlg/cartridge_pair.py` reads literal pools and `bl` targets out of every window held on both
cartridges and pairs them (1592 points, every site paired). `memory-dump-scatter` sends the same
addresses to both consoles; cross-correlation of two blocks reads the delta, and testing which delta
matches window by window places a step to the byte. A unique four-distinct-byte word from one
console's dump, scanned on the other, gives a point anywhere in the ROM.

Traps:

- Pair pools by code offset, never by index: index pairing invents deltas after the first mismatch.
- Delta 0 is also what a scan of the wrong console answers; include a control point above a
  step edge, which must come back shifted.
- Graphics resembles itself: score each candidate delta against the others and record a close score
  as no verdict.

## Reading a LeafGreen dump against FireRed's tables

`tools/frlg/rom_functions.py --console leafgreen` moves entries, bodies and names through the
twins and drops entries inside a divergent span. The script layer is identical below 0x0807AF04
(`rom_map.SHARED_WITH_LEAFGREEN_THROUGH`): the `gScriptCmdTable` handler block
(0x0806D7C0..0x080700B8), the script engine, `GetVarPointer`, `VarGet`, `FlagSet`, `FlagClear`,
`FlagGet` and `_call_via_r0`.

## The overworld, and a shiny Mewtwo

[The seek stubs](frlg_rng.md) run unported. `initramscript` binds a RAM script to a map object,
which `GetRamScript` runs instead of the object's own [field_control_avatar.c:458]. Cerulean Cave B1F
is group 1 map 74; Mewtwo is object 3 [data/maps/CeruleanCave_B1F/map.json]. `rng-mon-hunt-both`
bound there with `setwildbattle` species 150, level 70 starts an aimed Mewtwo battle (a shiny Mewtwo
on retail LeafGreen).

- The binding survives a power cycle.
- A Wonder Card session rebinds the slot through `InitRamScript_NoObjectEvent` and Mewtwo's own
  script returns; a buffer script leaves it alone.
- While bound, the console reports no Wonder Card
  ([the one RAM script slot](frlg_gift.md#the-one-ram-script-slot)).

## A dumped region must not move

A `memory-dump` of a region that changes between frames, such as `gRngValue`, fails its CRC and ends
in *erreur de connexion*, because the CRC and the send happen on different frames
([Code on the console](frlg_rom.md#repointing-the-consoles-outgoing-message)). The two save-block
pointers above it move together by one 4-aligned offset in 0..124 [load_save.c:75].

## The English build

`pret/pokefirered` builds both cartridges at REVISION 10 with binutils and `pret/agbcc`:

    make firered_switch     -> pokefirered_switch.gba    baa452d0b24629dd7782cfc07a8984085dde1311
    make leafgreen_switch   -> pokeleafgreen_switch.gba  62b9fc77549dbc67032eb6cbd0ea6ad3b825690f

A build that does not match those sha1s is unusable; the ROM is never committed. It is the English
release, a second cartridge pair with every symbol known.

### The offset: French address to English address

The French-to-English offset is piecewise constant, stepping where an object changes size between
languages. `gSpecials`, `gScriptCmdTable` and `gMysteryEventScriptCmdTable` entries (675 points) and
unique 16-byte windows agree everywhere both apply.

    ./.venv/bin/python tools/frlg/english_build.py --offsets

### The control

Named through the offset, the English ELF agrees with all 232 names in `worker_names` and disagrees
with none.

    ./.venv/bin/python tools/frlg/english_build.py --check

`pokeldn/frlg/rom/english_names.py` (`scripts/gen_english_names.py`) holds 7573 French function
addresses named this way, read last by `rom_functions` and marked `[english]`, so a name inferred from
the English build never overrules a body the console named (`gen_worker_names` passes
`with_english=False`). Targets between offset runs go to `english_names.BRACKETED` (`[english?]`)
when exactly one neighbouring offset lands on a function start. `__divsi3`, `__modsi3` and
`__umodsi3` are agbcc's division helpers.

### The English pair's own delta map

The two English ROMs give the same six deltas in the same order, each step inside a
version-divergent object:

    +0x0   -0x2c   -0x28   -0x24   -0x20   -0x1c4

All five predicted French step positions fall inside the brackets measured on hardware.

    ./.venv/bin/python tools/frlg/english_build.py --boundaries

### Traps

- A `.gcc2_compiled.` symbol shadows the first function of its file; skip names beginning `.` or `$`.
- Padding matches every delta. Require 16 distinct byte values in a window before a match counts.
- The offset (French to English, one cartridge) is not the delta (FireRed to LeafGreen):
  `french delta = offsetFR - offsetLG + english delta`.
- Regenerate `english_names.py` after any new dump.

## Unusable references

`gSongTable` packs 122 song headers inside 9 KB, so it fixes one place only. FireRed's ROM data ends
between 0x086ABE68 and 0x08800000; 0x08800000 reads all `0xFF`, 0x08E00000 all `0x00`.

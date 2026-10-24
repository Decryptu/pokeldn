---
title: The random number generator
parent: FireRed and LeafGreen
nav_order: 5
---

# gRngValue: reading it, predicting it, and aiming it

FireRed's `gRngValue` can be read, predicted from a Pokemon, and aimed by a field stub so the next
scripted encounter is shiny with a chosen nature and IVs. Addresses are French FireRed (BPRF, 0x0A).

## The generator

```c
u16 Random(void) { gRngValue = 1103515245 * gRngValue + 24691; return gRngValue >> 16; }
void SeedRng(u16 seed) { gRngValue = seed; }
```

[src/random.c, include/random.h:18]

| symbol | address |
|---|---|
| `gRngValue` | `0x03004220` |
| `Random` | `0x080486B0` |
| `SeedRng` | `0x080486D0` |
| `gSpecialVar_0x8000` | `0x020370B4` |

`pokeldn/frlg/rom/lcg.py` is the arithmetic; `distance(a, b)` is exact by baby-step/giant-step. The
map permutes all 2<sup>32</sup> states, so a distance is evidence only when small (odds N /
2<sup>32</sup>). `gRngValue` and `gSpecialVar_0x8000` never move; save blocks move on every battle
and load [load_save.c:75].

## The rate: exactly 2 turns per frame

The state advances exactly 2 turns per frame: `--gift rng-rate-probe` (read, `delay` N frames
[scrcmd.c:651], read) measures `2N + 2` turns, the +2 being one frame around the `delay`. The state n
frames after a reading is `advance(S, 2n)`. One turn is about 8 ms.

## Where the seed comes from, and why it cannot be carried

`SeedRngAndSetTrainerId` [main.c:264] seeds from timer 1 (`REG_TM1CNT_L`) at the title screen's START
press [title_screen.c:735], 65536 values; the read has sub-frame jitter, so timing START cannot choose
a seed. Backing out of Mystery Gift returns to the title screen [mystery_gift_menu.c:463], so a seed
set during a link never reaches the overworld.

| `SeedRng` call site | when |
|---|---|
| `SeedRngAndSetTrainerId` [title_screen.c:735] | the title screen |
| `LinkTestScreen` [link.c:318] | unused debug screen |
| `Debug_RfuIdle` [link_rfu_2.c:2670] | unused debug screen |
| `RfuMain1` [link_rfu_2.c:2116] | Switch-only, gated on `svc_4b() & SVC4B_RESEED_RNG`, seeds from the host's advertised `playerTrainerId` |

No measured state descends from the `RfuMain1` reseed; when its bit is set is unknown.

## Reading a Pokemon back into the state that made it

A wild Pokemon is four draws: personality low, personality high, HP/ATK/DEF, SPE/SPATK/SPDEF
[wild_encounter.c:233]. The IVs add 30 bits of check, so `lcg.recover_wild_state` finds exactly one
state. A stray draw can sit before or between the IV draws; its source is unknown, so both gaps are
searched:

| method | gap before IVs | gap between IVs |
|---|---|---|
| 1 | 0 | 0 |
| 2 | 1 | 0 |
| 4 | 0 | 1 |

Check a mon's PID and IVs against its six summary stats before any RNG claim.

## The scripted battle

```
setptr b0..b3 -> 0x03004220      gRngValue = seed          (opcode 0x11)
setwildbattle <species> <level>  CreateMon rolls PID, PID, IV, IV   (0xB6)
dowildbattle                     the battle starts          (0xB7)
```

`setwildbattle` calls `CreateMon(..., 32, 0, 0, OT_ID_PLAYER_ID, 0)` [script_pokemon_util.c:128]:
plain four-draw Method 1, no grass or encounter roll. Both commands return FALSE, so the writes and
the generation run in one frame; nothing that yields may sit between them (a test asserts it). The
RAM script is bound by `initramscript` and ends in `end` (0x02), not `endram`, so it re-triggers. A
predicted shiny Lv50 Ditto matched PID, nature and IVs exactly.

Reading the live state and generating a mon, the four draws start at the state read; the mon costs
4 turns (`Random32()` 2, IVs 2 [pokemon.c:1796,1836,1845]) and one overworld frame adds 2.

## The seed-reading NPC

`--gift rng-seed-reader`, flag id 1015, a bound RAM script:

```
copybyte gSpecialVar_0x8000+0, 0x03004220      (opcode 0x15)
copybyte gSpecialVar_0x8000+1, 0x03004221
copybyte gSpecialVar_0x8001+0, 0x03004222
copybyte gSpecialVar_0x8001+1, 0x03004223
buffernumberstring 0, VAR_0x8000               (0x83)
msgbox                                          the NPC prints the value
```

`rng_script.seed_from_printed(low, high)` reassembles the word, and
`rng_script.check_two_readings` scores two readings.

- All six commands return FALSE and run in one frame, so the read cannot tear.
- The text pointer is relative: `setvaddress` (0xB8) and `vmessage` (0xBD) [scrcmd.c:171] make the
  operand an offset into the script body, which moves with the save block.
- `buffernumberstring` prints a `u16` [scrcmd.c:1678]: two vars, two lines.

Bind to the player's mother (group 4, map 0, object 1, `MOVEMENT_TYPE_FACE_LEFT`, never hidden). The
Pallet Town object events wander off.

## How precisely a human can press A

A player aiming 30 s ahead lands within a standard deviation of 4.5 frames after a constant offset,
so a press hits one chosen frame about 9% of the time; a shiny frame comes every ~8192 frames.
`pokeldn/frlg/rom/rng_countdown.py` is the countdown; `--aimed-at STATE` measures a miss in frames.
This is the route when the RAM script slot holds a Wonder Card.

At a script's button wait the hook can press instead, on the exact frame and without writing
`gRngValue`: [`shiny-press`](frlg_rom.md#shiny-shiny-press-ivs-noencounter), the app's Shiny legendary.

## The stub that does the search

`--gift rng-shiny-hunt`, `pokeldn/frlg/rom/native_script.py`, `asm/field/`. All four stubs work on
retail:

| stub | gift |
|---|---|
| `shiny-seek.s` | `rng-shiny-hunt` |
| `mon-seek.s` | `rng-mon-hunt` |
| `mon-seek-far.s` | `rng-mon-hunt-far` |
| `mon-seek-both.s` | `rng-mon-hunt-both` |

```c
bool8 ScrCmd_setptr(struct ScriptContext * ctx)          // 0x11
{ u8 value = ScriptReadByte(ctx); *(u8 *)ScriptReadWord(ctx) = value; }
bool8 ScrCmd_callnative(struct ScriptContext * ctx)      // 0x23
{ void (*func)(void) = ((void (*)(void))ScriptReadWord(ctx)); func(); return FALSE; }
```

[scrcmd.c:300, :120]. `setptr` stages code into EWRAM and `callnative` runs it in the overworld,
which `CLI_RUN_BUFFER_SCRIPT` cannot reach (`notblisy/RUBYSAPPHIREDLC` does the same on
Ruby/Sapphire). `CreateScriptedWildMon` has no fixed personality and `OT_ID_PLAYER_ID` draws nothing,
so shininess is the first two draws after the state the stub leaves.

The stub reads `playerTrainerId` at `gSaveBlock2Ptr + 0x0A` and writes only `gRngValue`. The search is
bounded; on exhaustion the encounter is ordinary. Every stub runs under unicorn before staging
(`tests/test_native_script.py`).

### A RAM script may not come back from a battle

`CB2_InitBattle` and `InitOverworldBgs` call `MoveSaveBlocks_ResetHeap` [battle_main.c:614,
overworld.c:1337], moving `gSaveBlock1` by a multiple of 4 in 0..124 [load_save.c:75], while the
engine keeps its pointer into `ramScript.data.script` [script.c:514]. Nothing after `dowildbattle` is
reachable: the resume lands on a stray battle, zero fill, or a command that freezes the overworld.

The battle starts from outside the save block [`rng_script.battle_and_exit`]:

    setvar 0x8000, 0x02B7      ->  0x020370B4: B7 02  =  dowildbattle ; end
    goto   0x020370B4

Nothing writes `gSpecialVar_0x8000` in battle, and `end` returns control [script.c:335]. No RAM script
may rely on a save-block address across a battle or map load.

## Choosing the nature and the IVs

`--gift rng-mon-hunt`, `asm/field/mon-seek.s`, flag id 1019, tests shininess, nature
(`personality % 25` [pokemon.c:5020]) and IV floors (draws 3 and 4 [pokemon.c:1836]):

    --hunt-nature adamant,jolly   --hunt-iv speed=31 --hunt-iv attack=20   --hunt-cap N

| asked for | 1 state in | typical freeze | worst at the cap |
|---|---|---|---|
| shiny | 8,192 | 0.02 s | 0.10 s |
| shiny + one nature | 204,800 | 0.55 s | 2.5 s |
| shiny + nature + one IV >= 20 | 546,133 | 1.5 s | 6.7 s |
| shiny + two IVs = 31 | 8,388,608 | 22 s | refused |

`native_script.search_cost` computes this; the host refuses a worst case above
`--hunt-freeze-frames` (default 900). The player sees a still frame with music. `mon-seek.s` is 160
bytes of a 163-byte staging budget.

## The payload in the script body

`setptr` costs six script bytes per code byte. The engine runs the 995-byte RAM script body in place
and never reads past the last command [script.c:514], so bytes after it are storage at one byte each.
`&gSaveBlock1Ptr` (0x03004228) gives the body's address for the frame; `asm/field/ram-jump.s` (36
bytes) is the only part staged:

    setptr x36    the trampoline, into gDecompressionBuffer        216 bytes
    callnative    -> trampoline -> payload -> back                   5
    setwildbattle / setvar / goto                                   16
    pad to a multiple of four                                        3
    payload                                                        755

The trampoline tail-branches (`bx r0`), so the payload's `pop {r4-r7, pc}` returns to
`ScrCmd_callnative`'s caller. It returns early unless `ramScript.data.magic` is 51 [script.c:12].

### Alignment to four bytes

THUMB `ldr rN, [pc, #imm]` uses `Align(PC, 4)`. The body is word-aligned: the save-block offset is
`& 0x7C` [load_save.c:75] and `RAMSCRIPT_BODY_OFFSET` is 0x3624. `native_script.emulate_body_script`
walks the real script bytes to catch a misalignment.

### Proving the size rather than the jump

`asm/field/mon-seek-far.s` is followed by non-zero filler to byte 995; the stub searches only if the
filler sums correctly. `InitRamScript` zero-fills the rest [script.c:495], so a short delivery leaves
`gRngValue` alone. `--gift rng-mon-hunt-far` carries 196 bytes of stub and 559 of filler.

## Searching so the stray draw cannot move the answer

`asm/field/mon-seek-both.s` (232 bytes, `--gift rng-mon-hunt-both`, flag id 1001) tests the floors at
two placements. With d3, d4, d5 the draws after the personality:

| method | first triple (HP/ATK/DEF) | second triple (SPE/SPATK/SPDEF) |
|---|---|---|
| 1 (clean) | d3 | d4 |
| 2 | d4 | d5 |
| 4 | d3 | d5 |

Requiring both words `d3 | d4<<15` and `d4 | d5<<15` covers all three methods. Shiny + Jolly +
SPEED >= 20 becomes 1 in 1,456,000, about 4 s typical; the cap is 95%.

## Where a hunt writes its report

`asm/field/mon-seek-log.s` (288 bytes, `--gift rng-mon-hunt-log`, flag id 1002) writes
`{marker, start, found, iterations, cap}` to `gSaveBlock1Ptr + 0x348C`, `u8 unused_348C[400]`
[include/global.h], which no code writes. It survives the battle and reaches flash on save; an
exhausted search writes `found` 0.

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x348C --dump-size 32

`native_script.decode_hunt_log` reads it. A logged search of 603,745 iterations matched
`lcg.distance(start, found)` exactly and took 2-3 s, 3.7-5.6 cycles per instruction against the
model's `CYCLES_PER_INSTRUCTION_FROM_EWRAM` of 3.

## LeafGreen

The stubs run unported: every literal is a link-time IWRAM word or a constant, and `TID ^ SID` is read
at run time. See [LeafGreen](frlg_leafgreen.md).

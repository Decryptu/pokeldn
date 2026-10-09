---
title: The random number generator
parent: FireRed and LeafGreen
nav_order: 5
---

# gRngValue: reading it, predicting it, and aiming it

Everything here was measured on French FireRed, BPRF software version 0x0A.

## The generator

```c
u16 Random(void) { gRngValue = 1103515245 * gRngValue + 24691; return gRngValue >> 16; }
void SeedRng(u16 seed) { gRngValue = seed; }
```

[src/random.c, include/random.h:18]

| symbol | address | how it was obtained |
|---|---|---|
| `gRngValue` | `0x03004220` | `Random`'s literal pool |
| `Random` | `0x080486B0` | scanning 4 MB for `RAND_MULT` = 0x41C64E6D |
| `SeedRng` | `0x080486D0` | its pool names `gRngValue` a second time |
| `gSpecialVars` | `0x081639A8` | the only twelve-word run rising by 2 in 2.75 MB |
| `gSpecialVar_0x8000` | `0x020370B4` | that run's first entry |

No ARM or THUMB instruction encodes `RAND_MULT`, so it sits in `Random`'s pool next to `&gRngValue`.
The scan returned eleven hits; `ld_script.ld` puts `src/random.o` at #86 and the next user of the
constant, `src/title_screen.o`, at #123, so the lowest hit is random.o's. The dump matches `Random`
instruction for instruction [random.c:9-13], and `SeedRng` follows with the same pool word.

`Random` returns the top half of the state: a personality (two draws) leaves 2<sup>16</sup>
candidate states. `pokeldn/frlg/rom/lcg.py` is the arithmetic; `distance(a, b)` is exact at any range
by baby-step/giant-step (2<sup>17</sup> operations). The map permutes all 2<sup>32</sup> states, so a
distance always exists and is evidence only when small (odds N / 2<sup>32</sup>).

`gRngValue` and `gSpecialVar_0x8000` are link-time globals and never move. A save-block address
moves: `SetSaveBlocksPointers` re-rolls a 4-aligned offset on every battle and load [load_save.c:75].

## The rate: exactly 2 turns per frame

`ScrCmd_delay` resumes after exactly N frames [scrcmd.c:651]. `--gift rng-rate-probe` reads
`gRngValue`, delays N frames and reads it again; `rng_script.measure_rate` divides `lcg.distance` by N.

| frames (exact) | turns (exact) | 2N + 2 |
|---|---|---|
| 600 | 1,202 | 1202 |
| 3000 | 6,002 | 6002 |

The +2 is one extra frame around the `delay`; a 2.003333-per-frame model fits N=600 but predicts 6010
at N=3000. `rng-trace` sampling `gRngValue` once a frame at the Mystery Gift link menu gave gaps of
exactly 2, 95 of 95. The state n frames after a reading is `advance(S, 2n)`.

The probe measures a locked player during `delay` (`lock=False` measures unlocked); turn counts in
ordinary overworld play are even. A count comes from two readings (`distance`) or the resulting
Pokemon (`recover_wild_state`); one turn is about 8 ms, so hand-timed seconds do not determine it.

## Where the seed comes from, and why it cannot be carried

```c
void SeedRngAndSetTrainerId(void) { u16 val = REG_TM1CNT_L; SeedRng(val); gTrainerId = val; }
```

[main.c:264], called from `Task_TitleScreenMain` after the fade, just before
`SetMainCallback2(CB2_InitMainMenu)` [title_screen.c:735]. `StartTimer1` runs at `CB2_InitTitleScreen`
[:351]: the seed is a free-running timer sampled at the START press, 65536 possible values.

A seed set during a link does not survive: backing out of Mystery Gift runs
`MainCB_FreeAllBuffersAndReturnToInitTitleScreen` → `CB2_InitTitleScreen` [mystery_gift_menu.c:463],
and START reseeds. No route from the Mystery Gift menu to the overworld avoids it. A seed of `0xC0DE`
set there is not an ancestor of the next encounter's state (measured 1,898,278,119 turns apart).

| `SeedRng` call site | when |
|---|---|
| `SeedRngAndSetTrainerId` [title_screen.c:735] | the title screen |
| `LinkTestScreen` [link.c:318] | unused debug screen |
| `Debug_RfuIdle` [link_rfu_2.c:2670] | unused debug screen |
| `RfuMain1` [link_rfu_2.c:2116] | Switch-only, gated on a Sloop syscall |

```c
if ((svc_4b() & SVC4B_RESEED_RNG) != 0)
    SeedRng(ReadU16(&GetHostRfuGameData()->compatibility.playerTrainerId));
```

[link_rfu_2.c:2114, `#if REVISION >= 0xA`]. `RfuMain1` runs every frame while RFU is up, so a set
bit would pin the state near the advertised `playerTrainerId`. No measured state descends from it:
a state sampled at the Mystery Gift menu was 1.37 billion turns from the console's
`playerTrainerId`, and one sampled at an encounter after Union Room play 2.10 billion turns.
When the bit is set is unknown.

Timing START cannot choose a seed. Timer 1 runs at F/1 and a frame is 280,896 cycles, so frame-aligned
reads would all be multiples of `gcd(280896 mod 65536, 65536) = 64`. Recovered seeds `0xB8C0`,
`0x3742`, `0x8E94`, `0x1376` are 0, 2, 20, 54 mod 64: the read has sub-frame jitter.

## Reading a Pokemon back into the state that made it

`GenerateWildMon` calls `CreateMonWithNature(..., USE_RANDOM_IVS, Random() % NUM_NATURES)`
[wild_encounter.c:233], rolling the personality until it matches the nature, then the IVs. A wild
Pokemon is four draws: personality low, personality high, HP/ATK/DEF, SPEED/SPATK/SPDEF. The two IV
draws add 30 bits of check and exactly one state survives (`lcg.recover_wild_state`). `Random32()`,
`(Random() | (Random() << 16))`, draws the low half first at both call sites.

Both gaps must be searched; the layout varies between mons. Observed on retail:

| method | gap before IVs | gap between IVs | observed on |
|---|---|---|---|
| 1 | 0 | 0 | scripted Ditto, scripted Magikarp (2) |
| 2 | 1 | 0 | wild Weedle, scripted Magikarp |
| 4 | 0 | 1 | wild Caterpie, Weedle, Mankey; scripted Magikarp |

A search over one gap reports "no state builds this mon" for the others. The stray draw is in no
line of `CreateBoxMon`; its source is unknown. On a scripted encounter it is intermittent. A stub
asking for shiny + Jolly + SPEED >= 20 produced a shiny Jolly Magikarp with SPEED 10; exactly one
state in 2<sup>32</sup> has that PID on its next two draws:

    state 0x429D2189
      draws 3,4 -> 15/0/12/25/7/14      what the stub tested: SPEED 25, passes
      draws 4,5 -> 25/7/14/10/10/30     the mon that appeared

A mon's PID and IVs are checked against the six stats on its summary screen before any RNG claim.

## The scripted battle

```
setptr b0..b3 -> 0x03004220      gRngValue = seed          (opcode 0x11)
setwildbattle <species> <level>  CreateMon rolls PID, PID, IV, IV   (0xB6)
dowildbattle                     the battle starts          (0xB7)
```

`ScrCmd_setptr` writes an immediate byte to an absolute address [scrcmd.c:300]. `setwildbattle` calls
`CreateScriptedWildMon` → `CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0)`
[script_pokemon_util.c:128]: random IVs, no fixed personality, no nature loop, plain four-draw Method 1.
Both commands return FALSE and the field engine runs commands until one returns TRUE, so the four
`setptr`s and the generation run in one frame. Nothing that yields may sit between them (a `playse`
breaks it); a test asserts none does.

Delivered as a RAM script bound to a map object by `initramscript`, ending in `end` (0x02) instead of
`endram` (0x0d) so the binding survives and re-triggers. `setwildbattle` needs no grass and no
encounter roll. Predicted offline before the console saw the seed, a shiny Lv50 Ditto in Pallet Town:

```
PREDICTED   PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
ACTUAL      PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
```

### A mon predicted from a seed nobody set

A script that writes nothing reads the live state, prints it, generates a mon, and prints it again:

```
BEFORE  0x9A4F5DAA        (read off the console)
AFTER   0x8EEB8648
```

Predicted from `BEFORE` alone, the mon dumped from `gPlayerParty` matched on all seven fields: PID
0x0BF87DD1, nature 13 Jolly, not shiny, IVs 25/10/28/9/19/3. The four draws start at the state read,
offset zero.

`distance(BEFORE, AFTER)` is 6 where `CreateBoxMon` spends 4: 2 for `Random32()`, none for the OT
because the player is the OT [pokemon.c:1796], 2 for the IVs [:1836,1845]. The extra 2 (one frame of
overworld consumption) land after the generation.

## The seed-reading NPC

`--gift rng-seed-reader`, flag id 1015. Six commands, installed once as a RAM script by `initramscript`
and ending in `end` so the binding survives:

```
copybyte gSpecialVar_0x8000+0, 0x03004220      (opcode 0x15, byte at any address to any address)
copybyte gSpecialVar_0x8000+1, 0x03004221
copybyte gSpecialVar_0x8001+0, 0x03004222
copybyte gSpecialVar_0x8001+1, 0x03004223
buffernumberstring 0, VAR_0x8000               (0x83)
msgbox                                          the NPC prints the value
```

It alters nothing; `rng_script.seed_from_printed(low, high)` reassembles the word.

- The read is atomic. The RNG never idles, so byte copies spread over frames would tear into a value
  the console never held. `copybyte` and `buffernumberstring` return FALSE, so all six run in one
  frame; a test asserts nothing that yields sits between them.
- The text pointer is relative. The RAM script lives in `gSaveBlock1Ptr->ramScript`, whose base is
  re-rolled on every battle and load. `setvaddress` (0xB8) sets
  `sAddressOffset = addr2 - (ctx->scriptPtr - 1)` [scrcmd.c:171] and `vmessage` (0xBD) subtracts it,
  so the operand is an offset into the script's own body.
- `buffernumberstring` prints a `u16` [scrcmd.c:1678], so the seed takes two vars and two lines.

Two readings about twenty seconds apart gave:

```
reading 1   RNG HI 4685   RNG LO 26687   -> 0x124D683F
reading 2   RNG HI 54871  RNG LO 55616   -> 0xD657D940
distance    2,595 turns
```

Unrelated words sit about 2<sup>31</sup> apart; 2,595 is odds 1 in 1,655,093
(`rng_script.check_two_readings`).

Bind to the player's mother (group 4, map 0, object 1): `MOVEMENT_TYPE_FACE_LEFT`, flag 0 so never
hidden, a step from the player. Both Pallet Town object events are `MOVEMENT_TYPE_WANDER_AROUND`
[data/maps/PalletTown/map.json] and walk off mid-countdown.

## How precisely a human can press A

Four presses by one player against a target 30.00 s ahead, read off the seed-printing NPC:

| trial | frames elapsed | error vs 1791.8 |
|---|---|---|
| 1 | 1801 | +9.2 |
| 2 | 1807 | +15.2 |
| 3 | 1800 | +8.2 |
| 4 | 1796 | +4.2 |

Mean +9.2 frames (a fixed offset that cancels), standard deviation 4.5, range 11. All four turn
counts are even.

A shiny frame arrives every ~8192 frames (~137 s); at a 4.5-frame spread a press hits one chosen
frame about 9% of the time, so a hand-aimed shiny costs about 25 minutes against about 23 hours of
random encounters. A miss is measured exactly. `pokeldn/frlg/rom/rng_countdown.py` is
the countdown; `--aimed-at STATE` turns a miss into a signed frame count. This remains the route when
the RAM script slot holds a Wonder Card.

## The stub that does the search

`--gift rng-shiny-hunt`, `pokeldn/frlg/rom/native_script.py`, `asm/field/shiny-seek.s`. Each stub on
this page is verified on retail hardware:

| stub | gift | verified on retail |
|---|---|---|
| `shiny-seek.s` | `rng-shiny-hunt` | a shiny Ditto from the mother, from two different states |
| `mon-seek.s` | `rng-mon-hunt` | shiny, Jolly, Speed IV >= 20 on a level 5 Magikarp |
| `mon-seek-far.s` | `rng-mon-hunt-far` | a shiny Jolly Magikarp, so the 559 filler bytes arrived |
| `mon-seek-both.s` | `rng-mon-hunt-both` | shiny, Jolly, SPEED 22; a shiny Mewtwo on LeafGreen |

```c
bool8 ScrCmd_setptr(struct ScriptContext * ctx)          // 0x11
{ u8 value = ScriptReadByte(ctx); *(u8 *)ScriptReadWord(ctx) = value; }
bool8 ScrCmd_callnative(struct ScriptContext * ctx)      // 0x23
{ void (*func)(void) = ((void (*)(void))ScriptReadWord(ctx)); func(); return FALSE; }
```

[scrcmd.c:300, :120]

`setptr` writes one byte anywhere and `callnative` runs it, so a RAM script stages code into EWRAM and
runs it in the overworld, where `CLI_RUN_BUFFER_SCRIPT` cannot reach. `notblisy/RUBYSAPPHIREDLC` does
the same on Ruby/Sapphire (`writebytetoaddr` + `callasm`, an LCG loop until the PID is shiny).

`hasFixedPersonality` is 0 in `CreateScriptedWildMon`, so the personality is `Random32()` and
`OT_ID_PLAYER_ID` draws nothing: shininess is the first two draws after the state. `setptr`,
`callnative` and `setwildbattle` return FALSE, so the state the stub leaves in `gRngValue` is the one
`CreateScriptedWildMon` consumes.

The stub reads `playerTrainerId` at `gSaveBlock2Ptr + 0x0A` (a pointer at a fixed IWRAM address), so
the same bytes serve FireRed and LeafGreen. It writes one word, `gRngValue`. The search is bounded; on
exhaustion `gRngValue` is untouched and the encounter is ordinary. Every stub runs under unicorn
before staging (`tests/test_native_script.py`) and its answer is checked against `rng_countdown`.

### A RAM script may not come back from a battle

`CB2_InitBattle` and `InitOverworldBgs` call `MoveSaveBlocks_ResetHeap` [battle_main.c:614,
overworld.c:1337], re-rolling `gSaveBlock1` by a multiple of 4 in 0..124 [`SAVEBLOCK_MOVE_RANGE` 128,
load_save.c:75]. The engine keeps its pointer into `gSaveBlock1Ptr->ramScript.data.script`
[`GetRamScript`, script.c:514] across the battle, so it resumes where the script no longer is and
nothing after `dowildbattle` is reachable.

Symptoms: a stray second battle (landing on 0xB6/0xB7); a clean exit (landing in zero fill, `nop`);
a frozen overworld with no A, B or START (a resume point at byte 972 of 995 landing inside a six-byte
`setptr` record and decoding a command that waits forever). `releaseall` + `end` does not fix it.

The fix starts the battle from outside the save block, in ten bytes [`rng_script.battle_and_exit`]:

    setvar 0x8000, 0x02B7      ->  0x020370B4: B7 02  =  dowildbattle ; end
    goto   0x020370B4

`gSpecialVar_0x8000` does not move and nothing in battle or overworld code writes it.
`ScriptContext_RunScript` calls `UnlockPlayerFieldControls()` when a script stops [script.c:335], so
the `end` returns control. No RAM script may rely on a save-block address across a battle or map load.

## Choosing the nature and the IVs

`--gift rng-mon-hunt`, `asm/field/mon-seek.s`, flag id 1019. All four draws are tested: the
personality gives shininess and the nature (`personality % 25` [pokemon.c:5020]); draws 3 and 4 are
the IVs [pokemon.c:1836, HP/ATK/DEF then SPE/SPATK/SPDEF].

    --hunt-nature adamant,jolly   --hunt-iv speed=31 --hunt-iv attack=20   --hunt-cap N

A caught Magikarp reads back PID 0x01503B8A, shiny value 4, Jolly, IVs 6/2/25/28/12/7;
`lcg.recover_wild_state` gives state 0x7041F74F and `rng_countdown` reproduces every field.

Shininess is tested in the fifteen-instruction hot loop; the division by 25 and the IV comparisons run
for 1 state in 8192, so a criterion multiplies the iterations needed without slowing one:

| asked for | 1 state in | typical freeze | worst at the cap |
|---|---|---|---|
| shiny | 8,192 | 0.02 s | 0.10 s |
| shiny + one nature | 204,800 | 0.55 s | 2.5 s |
| shiny + nature + one IV >= 20 | 546,133 | 1.5 s | 6.7 s |
| shiny + two IVs = 31 | 8,388,608 | 22 s | refused |

`native_script.search_cost` computes this; the host refuses anything whose worst case exceeds
`--hunt-freeze-frames` (default 900, about 15 s). The player sees a still frame with music while it
searches.

`mon-seek.s` is 160 bytes of a 163-byte staging budget: the shiny value is its own inverse so `pidLo`
returns in two instructions, the divisor is its own loop counter, the IV floors carry a terminator bit
at 30, and both fields shift to bits 27..31 so a five-bit comparison is unsigned.

## The payload in the script body

`setptr` spends six script bytes per code byte (opcode, immediate, 4-byte address): about 162 bytes
of code in a 995-byte RAM script body. The engine runs the body in place and never reads past the last
command:

```c
const u8 *GetRamScript(u8 objectId, const u8 *script)
{ ... return scriptData->script; }
```

[script.c:514], out of `gSaveBlock1Ptr->ramScript.data.script`, so bytes appended after the last
command are delivered storage at one script byte each. The save-block offset is fixed for the frame
the script runs in, and `&gSaveBlock1Ptr` (0x03004228) holds it, so a run-time read aims exactly.
`asm/field/ram-jump.s` (36 bytes) is the only part staged:

| | staged | body |
|---|---|---|
| cost per payload byte | 6 script bytes | 1 script byte |
| room in a 995-byte body | 162 bytes of code | 755 bytes |

    setptr x36    the trampoline, into gDecompressionBuffer        216 bytes
    callnative    -> trampoline -> payload -> back                   5
    setwildbattle / setvar / goto                                   16
    pad to a multiple of four                                        3
    payload                                                        755

The trampoline tail-branches (`bx r0`, `lr` untouched), so the payload's `pop {r4-r7, pc}` returns to
`ScrCmd_callnative`'s caller. It first checks `ramScript.data.magic` is `RAM_SCRIPT_MAGIC` = 51
[script.c:12]; on a wrong offset it returns and the encounter is ordinary.

### Alignment to four bytes

THUMB `ldr rN, [pc, #imm]` and `adr` use `Align(PC, 4)`. Two bytes off, the branch lands and the code
runs but every pool word is read two bytes late. Four-byte alignment holds: `offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)`
[load_save.c:75] is `& 0x7C`, `gSaveBlock1` is word-aligned, and `RAMSCRIPT_BODY_OFFSET` (0x3624) keeps
it so. `native_script.emulate_body_script` catches a misalignment by walking the real script bytes
(the 36 `setptr`s, the `callnative`, the trampoline's `gSaveBlock1Ptr` read, the branch into the body).

### Proving the size rather than the jump

A shiny result confirms the jump but not the delivered size. `asm/field/mon-seek-far.s` is followed by non-zero filler to
byte 995; the stub sums it and searches only on a match. `InitRamScript` zero-fills the rest
[`ClearRamScript`, script.c:495], so a short delivery leaves `gRngValue` alone. `--gift
rng-mon-hunt-far` carries 196 bytes of stub and 559 of filler.

## Searching so the stray draw cannot move the answer

`asm/field/mon-seek-both.s` (232 bytes, `--gift rng-mon-hunt-both`, flag id 1001) tests the floors at
two placements covering all three methods. With d3, d4, d5 the draws after the personality:

| method | first triple (HP/ATK/DEF) | second triple (SPE/SPATK/SPDEF) |
|---|---|---|
| 1 (clean) | d3 | d4 |
| 2 | d4 | d5 |
| 4 | d3 | d5 |

Word A is `d3 | d4<<15`, word B `d4 | d5<<15`. Requiring both puts the first triple's floors on d3 and
d4 and the second's on d4 and d5, so Method 4 passes without its own word.

Only the IV term is squared: shiny + Jolly + SPEED >= 20 goes from 1 in 546,000 to 1 in 1,456,000,
about 4 s typical. The cap is 95%, since a miss costs one A press while 99% costs 18 s on an unlucky
run.

State 0xFCB5674F gave shiny, Jolly, SPEED 22 by Method 1 on retail, and every method passes:

| method | IVs | floors |
|---|---|---|
| 1 (clean) | 4/1/10/22/14/21 | ok, what the console made |
| 2 | 22/14/21/25/1/18 | ok |
| 4 | 4/1/10/25/1/18 | ok |

State 0x4FB97B07 predicts the PID exactly, with the IVs from Method 4 (SPEED 21, floor 20):

      Method 1 (clean)  25/10/30/20/ 9/25
      Method 2 (stray)  20/ 9/25/21/ 3/ 1
      Method 4          25/10/30/21/ 3/ 1   <- the mon that appeared

## Where a hunt writes its report

`asm/field/mon-seek-log.s` (288 bytes, `--gift rng-mon-hunt-log`, flag id 1002) writes
`{marker, start, found, iterations, cap}` to `gSaveBlock1Ptr + 0x348C`, `u8 unused_348C[400]`
[include/global.h]. No code writes `unused_348C`, and it reads zero on a retail save. The block is outside `ramScript`, so
`CalculateRamScriptChecksum` is untouched and the binding survives; each talk overwrites the log. It
survives the battle (`MoveSaveBlocks_ResetHeap` copies the blocks) and reaches flash on save.

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x348C --dump-size 32

`native_script.decode_hunt_log` reads it. An exhausted search writes `found` 0 with the marker.

| | |
|---|---|
| iterations | 603,745 |
| `lcg.distance(start, found)` | 603,745, difference 0 |
| instructions (15 each) | 9,056,175 |
| model at 3 cycles/instruction | 1.62 s |
| observed by the player | 2-3 s |
| implied | 3.7-5.6 cycles/instruction |

`CYCLES_PER_INSTRUCTION_FROM_EWRAM` is 3. The observed time is a stopwatch reading and search times
are exponentially distributed; an underestimate only makes the freeze ceiling refuse sooner.

## LeafGreen

The stubs run unported: every literal is a link-time IWRAM word or a constant identical on LeafGreen,
and `TID ^ SID` is read at run time. A binding on Mewtwo aims Mewtwo's encounter; see
[LeafGreen](frlg_leafgreen.md).

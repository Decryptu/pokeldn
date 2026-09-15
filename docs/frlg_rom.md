---
title: Code on the console
parent: FireRed and LeafGreen
nav_order: 3
---

# Running code on the console

The Mystery Gift client runs code sent to it through two interpreters.

`CLI_RUN_MEVENT_SCRIPT` (opcode 15) hands the bytes to the game's 17-opcode Mystery Event VM.
`CLI_RUN_BUFFER_SCRIPT` (opcode 21) hands them to the **CPU**: 1024 bytes copied into
`gDecompressionBuffer` and called as `func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr)`
[mystery_gift_client.c:276]. There is no glitch, no prepared save and nothing for the player to set
up; the console sits on its own Mystery Gift menu the whole time.

Addresses on this page were measured on French FireRed, cartridge BPRF, software version 0x0A.
LeafGreen's are on [LeafGreen](frlg_leafgreen.md); the tables and how they were found are on
[The ROM map](frlg_rom_map.md).

# The Mystery Event VM

A separate interpreter [src/mystery_event_script.c] with its own 17-command table
[data/mystery_event_script_cmd_table.s], distinct from the ordinary field-script VM that a Wonder
Card's delivery script compiles to.

## The command table

| # | command | operands after the opcode byte | returns | effect |
|---|---|---|---|---|
| 0 | `nop` |  | FALSE | nothing |
| 1 | `checkcompat` | u32 base, u16, u32, u16, u32 | **TRUE** | the compatibility gate |
| 2 | `end` |  | **TRUE** | `StopScript` |
| 3 | `setmsg` | u8 selector, ptr | FALSE | `StringExpandPlaceholders(gStringVar4, str)` when the selector is `0xFF` or equals the status |
| 4 | `setstatus` | u8 | FALSE | `ctx->data[2] = value` |
| 5 | `runscript` | ptr | FALSE | `RunScriptImmediately` on a field script |
| 6 | `initramscript` | u8 group, u8 map, u8 object, ptr, ptr | FALSE | `InitRamScript` bound to any map and object |
| 7 | `setenigmaberry` | ptr | FALSE | writes `gSaveBlock1Ptr->enigmaBerry` |
| 8 | `giveribbon` | u8 index, u8 ribbonId | FALSE | a gift ribbon onto every non-egg party mon |
| 9 | `givenationaldex` |  | FALSE | `EnableNationalPokedex()` |
| 10 | `addrareword` | u8 | FALSE | `EnableRareWord` (an Easy Chat trendy saying) |
| 11 | `setrecordmixinggift` |  | **TRUE** | dead: `SetIncompatible` |
| 12 | `givepokemon` | ptr | FALSE | a whole `struct Pokemon` plus attached Mail into the party |
| 13 | `addtrainer` | ptr | FALSE | a 188-byte `BattleTowerEReaderTrainer` |
| 14 | `enableresetrtc` |  | **TRUE** | dead: `SetIncompatible` |
| 15 | `checksum` | u32, ptr, ptr | **TRUE** | status 1 if `CalcByteArraySum` over the range does not match |
| 16 | `crc` | u32, ptr, ptr | **TRUE** | the same with `CalcCRC16` |

`pokeldn/frlg/rom/mystery_event.py` assembles all of them; `MysteryEventScript.blob()` holds the data
and the assembler resolves the pointers.

Every opcode has been run on retail hardware.

## `checkcompat` is optional, and skipping it removes two unknowns

`checkcompat` looks mandatory, it is the first command of every official script and it gates the
language and version masks, whose `LANGUAGE_MASK` is the English decomp's value. It can be skipped,
because of the loop structure:

```c
bool32 RunMysteryEventScriptCommand(struct ScriptContext *ctx)
{
    if (RunScriptCommand(ctx) && ctx->data[3])   // data[3] is set only by checkcompat
        return TRUE;
    return FALSE;
}
...
while (MEventScript_Run(&ret));
```

`RunScriptCommand` [script.c:107] already loops *inside one call*, executing commands until one
returns TRUE, and only six commands return TRUE. So a script with no `checkcompat` runs every command
up to the first TRUE-returning one in a single pass, and the outer `while` then stops because
`data[3]` is 0. That first TRUE-returning command is the end of the script, and `end` is the ordinary
way to write it.

Two consequences:

- `checkcompat` never runs, so its masks never matter. The French `LANGUAGE_MASK` question is
  removed rather than answered.
- Pointer operands become plain offsets. Every pointer is relocated as
  `operand - ctx->data[1] + ctx->data[0]`. `data[1]` is set only by `checkcompat`, so it stays 0, and
  `data[0]` is the address of the script itself, the console's 1024-byte `client->recvBuffer`. An
  operand of N means "N bytes from the start of what was sent", with no virtual base to guess.

`checkcompat` exists only to let execution *resume* after itself. It is the one command the assembler
allows code after.

## The return channel

`MEventScript_Run` writes the script's status into `client->param`
[mystery_event_script.c:75], and `CLI_LOAD_TOSS_RESPONSE`, named for the replace-card prompt but not
specific to it, loads exactly `client->param` into `MG_LINKID_RESPONSE`
[mystery_gift_client.c:204]:

    CLI_RECV MG_LINKID_RAM_SCRIPT
    CLI_RUN_MEVENT_SCRIPT
    CLI_LOAD_TOSS_RESPONSE
    CLI_SEND_LOADED

Those four commands are a return channel from the console carrying a u32 of the sender's choosing.
`setstatus` sets it to anything; the stock statuses report outcomes nothing else on this link shows:

| status | meaning |
|---|---|
| 0 | no command set one |
| 1 | `setenigmaberry` could not validate the berry, or a `checksum`/`crc` mismatch |
| 2 | success, every opcode that did its job sets this |
| 3 | `SetIncompatible`, or `givepokemon` found a full party |

`CLI_COPY_RECV_IF` and `CLI_COPY_RECV_IF_N` branch the *client script* on `client->param`
[mystery_gift_client.c:170], so a status can steer what the console does next without another round
trip. Not yet used.

The Mystery Gift menu prints its own result text from the client script's `CLI_RETURN` value
[`GetClientResultMessage`, mystery_gift_menu.c:884], not from `gStringVar4`, so `setmsg` is invisible
on this path. Only a success message reaches `MG_STATE_SAVE_LOAD_GIFT` [:1379], and without that save
everything the event wrote is lost at the next reset, which is why `CLIENT_SCRIPT_MEVENT_DONE`
returns `CLI_MSG_CARD_RECEIVED` even on the branch where no card was sent.
`CLI_MSG_BUFFER_SUCCESS` (13) is the other success exit and prints `data->clientMsg`, the 64 bytes
pushed by `CLI_COPY_MSG`.

### The probe script

`--gift mystery-event-probe` is deliberately incapable of losing the player anything:
`givenationaldex` is a strict upgrade and a no-op on a save that already has the National Dex, and
`checksum` only reads.

    givenationaldex; setstatus 42; checksum 1026, 16, 31

and the returned status is self-diagnosing:

| status | what it proves |
|---|---|
| 42 | the chain ran to the end and pointer operands are offsets into the sent buffer |
| 1 | the chain ran, but the relocated pointers did not land on the probe bytes |
| 2 | `givenationaldex` ran and nothing after it did |
| 0 | the VM was entered but no command executed |
| nothing | the client script shape is wrong, not the VM |

`checksum` goes last precisely because it is terminal: it reports on the relocation without disturbing
the status the commands before it left. The console answers 42.

## `givepokemon`

`pokeldn/frlg/save/mevent_pokemon.py` builds the payload, a 100-byte encrypted party mon followed by
the 34-byte `struct Mail` the console reads at `pointer + sizeof(struct Pokemon)`.
`--gift mystery-event-celebi` ships one.

Three things it does that the field-script `givemon` cannot:

- Mail. Nothing else on the gift link can attach any. `ItemIsMail` gates it, so the mon's held item
  must be one of the twelve mail items [mail_data.c:167], and `GiveMailToMon2` then copies the whole
  struct into `gSaveBlock1Ptr->mail` verbatim [:100], words, sender name, trainer id, species and item.
- It writes the Pokedex itself, `FLAG_SET_SEEN` and `FLAG_SET_CAUGHT` on the national number,
  before the player sees the mon.
- It lands at the Mystery Gift menu, not at the delivery man. The mon is in the party the moment
  the menu closes, with no Pokemon Center visit.

The status is the outcome: 2 for success, 3 for a full party, in which case nothing is written. Do not
put a `setstatus` after `givepokemon`.

Traps the builder enforces:

- the mon's `mail` byte must be `MAIL_NONE` (0xFF) going in; a zero there is mail slot 0, which the
  console reads as real mail the player never received;
- `personality == otId` makes the encryption key 0, and a mon then validates both shuffled and
  unshuffled, so an unshuffled one could ship;
- the party tail must be derived, not zeroed, a zero tail reads back as level 0;
- the mon's held item and the mail's `itemId` must agree, because `GiveMailToMon2` sets the held item
  *from the mail*.

## `initramscript`

`initramscript 3, 0, 2` binds a field script to a named map object, group 3, map 0, object 2 is the
fat man in the south of Pallet Town. After a reboot he says the script's lines, with `{PLAYER}`
expanded.

It works because it puts the script on the *other* dispatch path. `CLI_SAVE_RAM_SCRIPT` calls
`InitRamScript_NoObjectEvent`: MAP_UNDEFINED, object 0xFF [script.c:578]. Those never satisfy
`GetRamScript`'s map and object checks [:514]; they exist for `GetSavedRamScriptIfValid` [:554], the
delivery man's own script command, which also requires a valid Wonder Card. Real coordinates land on
`GetRamScript(gSpecialVar_LastTalked, script)` in the field [field_control_avatar.c:458], which runs
the given script instead of the object's own and never consults the card. `gSpecialVar_LastTalked`
is the object's *local* id, assigned in `map.json` order from 1.

It costs the Wonder Card, see [the one RAM script slot](frlg_gift.md#the-one-ram-script-slot).
While a bound script is installed, every session logs "holding no Wonder Card"; the next ordinary card
takes the slot back and the object gets its own script again.

`GetRamScript` replaces the object's script outright, so binding to a plot object suppresses that
object's own encounter script entirely. Binding to Mewtwo's object in Cerulean Cave B1F replaced
Mewtwo's script with a scripted encounter of this project's own.

## Traps

- `setenigmaberry` cannot set the item effect. `struct ReceivedEnigmaBerry` [berry.c:944] is 1322
  bytes: the 28-byte `Berry2` at offset 0, then `u8 unk_001C[0x4FA]`, then `itemEffect[18]`,
  `holdEffect` and `holdEffectParam` at offset 0x516, 1302 bytes into a buffer that is only 1024. The
  name, flavours, size, firmness and growth data all land; the tail is read from whatever follows
  `recvBuffer` on the console's heap. `build_enigma_berry_blob` lays the struct out and the simulator
  reports the overrun as a `read_past_buffer` effect.
- The two ROM description pointers in `struct Berry2` must be read off the cartridge and sent back
  unchanged: they live in the save forever and the Berry Pouch dereferences them to print the
  description, so an invented pointer renders garbage on every future look at the berry.
- `giveribbon` index 7..10, `GiveGiftRibbonToParty` [pokemon_size_record.c:193] accepts
  `index < 11`, but `sGiftRibbonsMonDataIds` has seven entries copied into a `u8[8]`; 7..10
  `SetMonData` a field id read from uninitialised stack. The assembler refuses anything above 6.
- FRLG has no ribbon UI, so `giveribbon` is invisible on this console; the effect only shows up
  after a transfer.
- A script with no terminal command runs on, decoding the rest of the zero-filled 1024-byte buffer
  as opcodes. `assemble()` refuses a script that does not end in one, and so does the server.
- `setrecordmixinggift` and `enableresetrtc` are dead. Both call `SetIncompatible` and stop the
  chain [mystery_event_script.c:227, :291]. The composer rejects them. Read off the console, each makes
  exactly one call and it is `SetIncompatible`.
- `addrareword` and `setenigmaberry` are invisible in game and have to be read back from the save.
  `addrareword` sets a bit in `gSaveBlock1Ptr->additionalPhrases` (SaveBlock1 + 0x2F10) that makes one
  more word *selectable* in the Easy Chat editor; `setenigmaberry` writes
  `gSaveBlock1Ptr->enigmaBerry` (+0x30EC), whose record defines what the Enigma Berry *is* while the
  player still has no such item. `VAR_ENIGMA_BERRY_AVAILABLE`, which the opcode sets, is read nowhere
  else in FRLG.

## How it is wired

- `pokeldn/frlg/rom/mystery_event.py`, opcodes, the assembler, a disassembler (`describe`), and
  `run()`, a simulator of the console's execution used by the offline client.
- `pokeldn/frlg/gift/mg_script.py`, `CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT` (no card held: card,
  delivery script, then the event), `CLIENT_SCRIPT_RUN_MEVENT` (the console already holds this card:
  the event alone, nothing tossed) and `CLIENT_SCRIPT_MEVENT_DONE`, the shared success tail.
- `pokeldn/frlg/gift/mg_server.py`, `SCRIPT_SEND_MYSTERY_EVENT`, with `SVR_LOAD_MEVENT` and
  `SVR_READ_MEVENT_STATUS`; the status lands in `server.mevent_status` and in the host log.
- `pokeldn/frlg/gift/gift_composer.py`, `WonderGift.mevent` takes assembled bytes and validates them.

# Native ARM code

```c
case CLI_RUN_BUFFER_SCRIPT:
    memcpy(gDecompressionBuffer, client->recvBuffer, MG_LINK_BUFFER_SIZE);
    client->funcId = FUNC_RUN_BUFFER;
    ...
static u32 Client_RunBufferScript(struct MysteryGiftClient * client)
{
    u32 (*func)(u32 *, struct SaveBlock2 *, struct SaveBlock1 *) = (void *)gDecompressionBuffer;
    if (func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr) == 1)
```

[mystery_gift_client.c:237,276]. Five facts follow, and every payload rests on them:

- 1024 bytes, copied whole (`MG_LINK_BUFFER_SIZE`) whatever was actually sent, so a payload runs
  with the tail of the previous receive behind it and must be self-contained.
- Three arguments: `r0 = &client->param`, `r1 = gSaveBlock2Ptr`, `r2 = gSaveBlock1Ptr`. Both save
  blocks, by pointer, readable and writable.
- A return channel. `client->param` is what `CLI_LOAD_TOSS_RESPONSE` ships back as
  `MG_LINKID_RESPONSE` [:204].
- Called once per frame until it returns 1. A payload that returns anything else is re-entered
  next frame; one that never returns 1 hangs the Mystery Gift menu with no way out. The `memcpy` that
  loads the payload runs once, at the `CLI_RUN_BUFFER_SCRIPT` command [:239], not per call, so a
  payload can keep state across frames and resume.
- ARM state, not THUMB. The caller reaches it with a `bx` through a function pointer, which takes
  the state from bit 0 of a word-aligned address.

`gDecompressionBuffer` is at **0x0201C000**, measured by the `anchors` payload. Payloads are position
independent either way.

## The build

- `asm/*.s`, one ARM source per payload, assembled by `scripts/gen_buffer_scripts.py` into
  `pokeldn/frlg/rom/buffer_payloads.py`. The machine code is committed so a live host needs no GBA
  toolchain; `tests/test_buffer_script.py` re-assembles and compares whenever `arm-none-eabi-as` is
  installed.
- `pokeldn/frlg/rom/buffer_script.py`, the payload registry, the validation, and `emulate()`, which
  runs a payload under unicorn on the GBA memory map with the console's three arguments. A payload
  that faults, or never returns 1, is caught there and never reaches the air.
  `emulate_repeating` calls a payload until it returns 1, the way the console does.
- `pokeldn/frlg/gift/mg_script.py`, `CLIENT_SCRIPT_RUN_BUFFER` (recv, run, load the return channel,
  send it, recv the next script) and `CLIENT_SCRIPT_BUFFER_SUCCESS`.
- `pokeldn/frlg/gift/mg_server.py`, `SCRIPT_RUN_BUFFER_SCRIPT`. No card, no toss prompt, no branch on
  what the console holds: a buffer script is not a gift, so a console carrying any card takes the same
  path and keeps it.
- Both simulated consoles execute the payload for real: `pokeldn/frlg/gift/mg_client.py` and
  `ConsoleClientModel` in `tests/test_mystery_gift_flow.py`, written from the decomp independently and
  modelling the once-per-frame re-entry.

Offline first, every time:

    ./.venv/bin/python -m pytest tests/test_buffer_script.py -q
    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script -v

On hardware there is no replace-card prompt and no card: a console holding any Wonder Card keeps it.

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  ./scratchpad/run_mg_fast.sh bsNN --buffer-script --version firered
    (them) join the host when it appears

Never SIGTERM the Mystery Gift host until the dump file exists. The host writes
`scratchpad/<tag>_dump.bin` when the session closes, several seconds *after* the
`Buffer script dump: N bytes` line prints:

    until ls scratchpad/<tag>_dump.bin >/dev/null 2>&1; do sleep 2; done

## Where a payload can live

A buffer script is 1024 bytes at `gDecompressionBuffer`, re-copied from `client->recvBuffer` on every
frame, so nothing it writes inside its own image survives the next frame and nothing at all survives
the session. Code that is to outlive the Mystery Gift menu has to be copied somewhere the game does
not use.

    0x0203FC00 .. 0x02040000    1024 bytes, above every symbol the game links

The top of EWRAM is unclaimed: the highest sized EWRAM symbol in the build ends at 0x0203FBAC and the
region ends at 0x02040000 ([EWRAM is at the same addresses in both builds](frlg_rom_map.md)). Dumps
of a console's EWRAM on the Mystery Gift menu, in the overworld, and after a battle and a map reload
read zero across the whole span in all three states.

A soft reset clears it twice, and on the Switch release it boots the game twice. `DoSoftReset` calls
`SoftReset(RESET_ALL & ~RESET_SIO_REGS)` [main.c:488], and `SoftReset` is `svc 0x1` then `svc 0`
[libagbsyscall.s:69]: a `RegisterRamReset` with those flags before the console reboots, then the BIOS
reset. `AgbMain` then calls `RegisterRamReset(RESET_ALL)` itself [main.c:134]. `RESET_ALL` is 0xFF
and bit 0 is `RESET_EWRAM` [include/gba/syscall.h:4,12], so the whole 256 KB goes each time.

Sampled at 328000 readings a second, `gIntrTable` is cleared and rebuilt **twice**, and both rebuilds
are the complete template, all fourteen words including `0x08000805` at entry 0 and the eight
`IntrDummy`s. `INTR_VECTOR` at 0x03007FFC is written twice with it. So `InitIntrHandlers` runs twice,
and therefore `AgbMain` does. Between the two, entries 1, 2 and 7 take their wireless values, so the
first boot reaches the point where the link comes up before the second clear arrives. The intervals
are 33.3 ms from the first clear to the first rebuild, 133.6 ms until the second clear, and 33.6 ms
to the second rebuild. The decomp accounts for two `RegisterRamReset` calls and for one `AgbMain`;
the second `AgbMain` is the wrapper restarting the emulated console.
What reads non-zero afterwards is what the boot path rebuilt: the heap, the GPU and font state, and
the save reloaded out of flash. The rebuild does not reach above 0x0203B0E8, which is why the top of
EWRAM reads clear rather than spared. A staged payload therefore lives until the console is reset and
no longer; measured, a marker at 0x0203FC00 survived the gift session closing, the title screen, a
full reload from it, walking, the START menu, the party and bag screens, the save menu, a save, a map
change, a wild battle fought to the end and a PC box, and was gone after A+B+START+SELECT.

`gHeap` carries no size in the symbol table, so a naive subtraction reports its 114688 bytes as
unclaimed. Named from the decomp instead, the top span is not merely the largest unclaimed region in
EWRAM, it is the **only** one: everything else the link map leaves over is three and eight-byte
alignment holes. `scratchpad/ewram_symbol.py ADDR LEN` answers the question for one address.

Large quiet spans lower down are not free. 0x0202B280, 0x020185C4 and 0x0203B0E9 are each tens of
kilobytes that read zero in all three of those states, and each is inside a symbol: the battle and box
buffers, the run-up to `gDecompressionBuffer`, and allocator bookkeeping. A buffer that happens to be
empty is not spare memory, and no number of sampled states can tell the two apart. The link map can.

That is not a theoretical caution. Twelve bytes written to 0x0202B280 to test whether a soft reset
clears EWRAM landed inside `gPokemonStorage` at +0x1F70, which is box 4 slot 10, across that stored
Pokemon's markings, checksum and the first bytes of its encrypted substructs. Destroying the checksum
is what makes a BAD EGG. The session saved immediately afterwards so it reached flash, and nothing
read it for eight tasks, because nothing reads a box slot until a person opens the box. A second
address in the same run, 0x02012304, was inside `gHeap` and did no harm only because that block
happened to be free. Both had been chosen for reading zero in three RAM dumps, which is the exact
mistake this section describes.

## The per-frame hook

`gIntrTable` is at **0x03002720** on the French cartridge and entry 4, the V-blank handler, holds
`VBlankIntr` at 0x0800071D. The table is a plain array of fourteen function pointers, written once
by `InitIntrHandlers` from `gIntrTableTemplate` [main.c:339], and the BIOS reaches it through
`IntrMain`, whose address the hardware vector at 0x03007FFC carries. Replacing entry 4 gives code a
call every frame in every game state, which nothing else on this console does: `gMain.vblankCallback`
and `gMain.callback2` are rewritten whenever a menu or a battle starts.

It was located in a console's own IWRAM rather than predicted. `IntrMain_Buffer` reads 0x03002760 at
0x03007FFC against the English build's 0x03002810, and `gSaveBlock1Ptr` is 0x03004228 against
0x030042D8: both say the cartridge's IWRAM sits 0xB0 below the English build's. At 0x030027D0 minus
0xB0 the fourteen words are the table, and four of the five real handlers name themselves, each a
constant 0x18 below its English address:

| entry | cartridge | English | |
|---|---|---|---|
| 0 VCount | 0x08000805 | 0x0800081C | `VCountIntr` |
| 1 Serial | 0x03004B34 | | replaced with an IWRAM handler while the link is up |
| 2 Timer3 | 0x08005AE1 | | `Timer3Intr`, a different ROM segment and a different delta |
| 3 HBlank | 0x080007D5 | 0x080007EC | `HBlankIntr` |
| 4 VBlank | 0x0800071D | 0x08000734 | `VBlankIntr` |
| 5, 6, 8-13 | 0x08000885 | 0x0800089C | `IntrDummy`, eight times |
| 7 | 0x081E0D35 | | the RFU library's timer handler, `sTimerIntrFunc = gIntrTable + 0x7` [main.c:85] |

Entries 1 and 7 being the two that differ from the template is what the decomp says happens while
wireless is running, so the two slots that break the pattern confirm the identification rather than
weakening it. The table reads identically on the Mystery Gift menu, in the overworld, and after a
battle and a map reload.

IWRAM addresses do not transfer between the two builds the way EWRAM addresses do, so the 0xB0 is a
measured offset at these addresses and not a map.

`InitIntrHandlers` re-runs on a soft reset and writes the table back from `gIntrTableTemplate`, so a
hook in it is undone by the same event that clears EWRAM and by nothing else. Entries 1 and 2 read
their template values again afterwards, where a session with the link up had replaced them.

### Code that outlives the session

A twenty-byte stub written into the staging area and installed in entry 4 runs every frame, in every
game state, after the Mystery Gift session has closed. `asm/resident/vblank-hook.s`:

```arm
    ldr     r0, .Lcounter
    ldr     r1, [r0]
    add     r1, #1
    str     r1, [r0]
    ldr     r0, .Loriginal
    bx      r0                      @ tail branch: lr still points at intr_return
```

`IntrMain` enters a handler in SYS mode with `lr` pointing at `intr_return` and lets it clobber
r0-r3 [crt0.s, `jump_intr`], so the stub preserves nothing and leaves `lr` alone: the handler it
replaced returns to `IntrMain` through its own `bx lr` as if nothing were in the way. Both literals
are patched before it is sent, so the code is position independent.

Installing it costs no new payload. A `call-chain` writes the five words and then entry 4, in that
order so the table never points at an incomplete stub, and every write reads itself back:

    read32  [0x03002730]                gIntrTable[4], 0x0800071D
    write32 [0x0203FC00] = 0x68014802   the stub
    write32 [0x0203FC04] = 0x60013101
    write32 [0x0203FC08] = 0x47004801
    write32 [0x0203FC0C] = 0x0203FC40   the counter's address
    write32 [0x0203FC10] = 0x0800071D   the handler being replaced
    write32 [0x03002730] = 0x0203FC01   the hook, THUMB bit set
    read32  [0x0203FC40]                the counter

Measured over 19995 frames and 329 samples: 59.0 to 63.3 counts a second on the Mystery Gift menu,
the title screen, the overworld, a party menu and a wild battle, with no stall, no revert and no
deviation, the spread being the sampler's. It survives a full in-game restart, title screen to save
load to overworld, without missing a frame. A soft reset ends it, because that clears EWRAM and
re-runs `InitIntrHandlers`. An IWRAM sample taken at the reset read `gIntrTable[4]` as zero and read
it as 0x0800071D again ten seconds later, which is the clear caught between `RegisterRamReset` and
`InitIntrHandlers` writing the table back.

A gift session cannot reach a console that is already carrying a payload. Mystery Gift is reachable
only from the menu a boot arrives at, and the boot clears EWRAM on the way, so installing a payload
always destroys whatever was there first. Nothing the gift link can send changes that; the way to
have a payload present without a human having just run a session is to put its installer in the
save.

`gIntrTable[1]` and `[2]` are replaced when wireless starts and are not restored when it ends: they
hold their wireless values in the overworld long after a session closed, and return to the template's
only at a reset. Entry 4 is never written by any of it.

### Re-arming it after a reset

`--gift resident-hook` sends a Wonder Card whose Mystery Event script `initramscript`s a field script
onto the player's mother, and that field script installs the hook. The binding lives in the save and
survives a power cycle ([the one RAM script slot](frlg_gift.md#the-one-ram-script-slot)), so the
player talks to her once after any boot and the hook is back, with no link and no host.

`asm/field/install-vblank-hook.s`, 68 bytes, staged with `setptr` at six script bytes each and run
with `callnative`: 418 bytes of the 995 a RAM script body holds.

    read  gIntrTable[4]
    if it already names the stub: return, writing nothing
    write the five words of the V-blank stub to the staging area
    write the handler just read into the stub's fifth word
    zero the counter
    write the staging area, Thumb bit set, into gIntrTable[4], last

The tail target is read from the table rather than patched in by the host, so the hook chains
whatever handler is there. The comparison at the top is a guard and not an optimisation: installing
twice would make the stub tail-branch to itself, which spins forever inside an interrupt handler and
freezes the overworld with no menu to back out of. The player can talk to their mother as often as
they like.

While the script is bound the console reports holding no Wonder Card, and the object's own dialogue
is replaced rather than extended. The next ordinary card takes the slot back.

Measured on an emulator: the card installed, the player talked to their mother, and the stub and
`gIntrTable[4] = 0x0203FC01` appeared in the same 50 ms sample with the counter at 1, so the hook
arms within about a frame of the conversation. A soft reset removed both. The script block at
`SaveBlock1 + 0x32E0` came back byte for byte at the re-rolled pointer, and talking to her again
brought the hook back with the host down and the console holding no LDN socket. Ten samples over 78
seconds saw nothing write the staging area before the script fired, which bounds the claim to what
was sampled rather than proving the span untouched.

What the save carries is the binding, not the payload. The script rebuilds the code on every arming,
so the code can never be larger than a script body holds: 162 bytes staged, or about 755 appended
after the last command and reached with a trampoline. Past that a payload has to live somewhere else
in the save and be copied in by a loader; `filler_B20` is 1024 bytes and is the only unused region
already proven to reach flash and come back.

### A payload larger than a script body

What the save keeps is a script, so the script's body bounds the code. A loader removes that bound by
putting the code somewhere else in the save and copying it in.

`asm/field/save-loader.s`, 64 bytes, is the whole of what the RAM script stages whatever the payload
weighs: it reads `gSaveBlock2Ptr` fresh, adds 0xB20, copies N words to the staging area, compares the
first word against a magic and branches into it. It uses only r0-r3 and never pushes, so the branch is
a tail branch and the payload's return goes straight back to `ScrCmd_callnative`'s caller. The magic
is the guard: a save that was never written, or a region a later card reached, is not branched into.

The blob is 936 bytes, which is what one `save-write` carries (`MAX_SAVE_WRITE_BYTES`, the 1024-byte
receive buffer less the payload that writes it):

    +0x000  magic 0x444C4B50
    +0x004  installer
    +0x054  the V-blank hook
    +0x068  filler
    +0x3A4  checksum over the filler

The installer sums the filler and installs nothing unless the sum matches. The blob travels through a
save write, flash, a slot rotation and a copy loop, and a short arrival would run perfectly well and
be wrong, so the checksum is what separates "the branch landed" from "all of it arrived".

The hook's tail target in the save's copy is the measured `VBlankIntr` rather than zero, and that is
a correctness requirement rather than a convenience. The loader copies the blob on top of whatever is
at the destination, which may be a hook that is installed and being called every frame, so a V-blank
landing between the copy and the install would branch to whatever the copy just wrote there. On a
second visit to the bound object it is not a race at all: the table already names the hook, the
installer takes its already-installed path and patches nothing, and the copy has already overwritten
the working tail target. The installer still writes the handler it reads, so the hook still chains
rather than assumes; the constant is what makes the window and the second visit safe.

Measured, with the zero left in deliberately: the second visit re-zeroed the word, `gIntrTable[4]`
never changed, the staged blob came back byte-identical to the save, and the console went to a black
screen 205 frames after the conversation ended. The counter recorded its own last frame, because the
hook increments before it branches. It is the
same argument a RAM script body makes about its own filler
([proving the size](frlg_rng.md#proving-the-size-rather-than-the-jump)).

The resulting RAM script is 394 bytes of 995 and does not grow with the payload. `filler_B20` holds
1024 bytes, and the other unused regions in the save add about 700 more. A blob larger than one
`save-write` is not a different mechanism, only more sessions: `save_write_chunks` splits it and the
region persists between them. At the full 1024 the blob ends at the top of EWRAM, so the frame
counter moves below it, into the 84 bytes between the highest symbol and the staging area.

Measured on an emulator, 936 bytes through the whole path: the blob arrived in EWRAM identical to
what was written into the save except the hook's fifth word, filler included; `gIntrTable[4]` read
the hook's address inside the blob; the counter ran at 60.0 a second. Across three soft resets and
four installs the staged blob hashed the same every time and the save blob was unchanged before each,
so the save survives the cycles and the loader reproduces the same bytes.

### Calling the wrapper

The GBA code the Switch release runs reaches its emulator through syscalls the decomp calls Sloop:
23 of them between `swi 0x40` and `swi 0x62`, with gaps at 0x46, 0x4E, 0x52 and 0x58 to 0x60
[src/sloopsvc.c]. A resident payload can issue any of them, because it is arbitrary THUMB in EWRAM,
and the blob carries a two-halfword thunk, `swi N ; bx lr`, assembled into it by the builder with the
number patched in. Markers go down before the call, since a syscall that does not return leaves
nothing else to read:

    +0x00  0xB0B00001   the probe was reached
    +0x04  the syscall number
    +0x08  0xB0B00002   it returned, and zero until it does
    +0x0C  r0, r1, r2, r3 as the syscall left them

`swi 0x54`, `svc_CommsAllowedByParentalControls` [sloopsvc.c:182], returned a non-zero u32 on an
emulated console with no parental controls, which is what it should. `swi 0x46`, one of the four
numbers the decomp leaves out, returned r0 = 0 and did not hang, so an unhandled number is inert and
the gaps can be swept without risking the overworld.

The wrapper's dispatcher is at `main + 0x057014` and its jump table at `main + 0x17D7F6`, found by
arming every candidate function in `main` on an emulator and looking for the one that carried a
syscall number the game never issues. It admits `N` in **0x40..0x62** and sends everything else to
the same place as its default:

    cmp   w2, #0x2b ; b.lo default       below 0x2B, the BIOS syscalls
    sub   w9, w19, #0x40 ; cmp w9, #0x22 ; b.hi default
    ldrh  w12, [table, w9, lsl #1]       a u16 word-offset from 0x05706C
    br    base + offset * 4

Thirty-five entries, twenty-three distinct handlers. Every number `sloopsvc.c` names has one of its
own. **0x52 has a handler the decomp does not have**, at 0x05728C. Called from the overworld with
`0xC0DE0052` in r0 and distinct markers in r1 to r3, it **writes r0 and nothing else, and writes
zero**: not an error code, not a pointer, not a handle. r1 to r3 came back bit for bit as passed,
which rules out a multi-register answer. The console did not freeze and both save slots were
byte-identical afterwards. Its handler reads the guest CPU state, shifts a word right by 21, indexes
a structure and calls through a vtable, so it does something rather than nothing, and what that
something writes is not known: a diff of the payload's own kilobyte cannot see a write anywhere else
in memory. The eleven that share the default
are 0x46, 0x4E and 0x58 through 0x60, which are exactly the decomp's gaps, so the gaps are gaps in
the table rather than in what the game happens to call. 0x48 and 0x56 share one handler, as
`WriteSector` and `ReplaceSector` should; 0x40 and 0x41 share one that branches on the number itself.

The default handler is `cmp w19, #0x2a ; cset w0, hi` and returns. That `w0` is the wrapper's own
"did I handle this" boolean, not the guest's r0, so an unimplemented number leaves the guest's
registers untouched rather than returning zero. A probe that passes zero in and reads zero out has
measured nothing, which is what the first reading of `swi 0x46` did.

Reading the table also settles that a blind sweep of 0x40..0x62 is not a measurement but a hazard:
0x48 and 0x56 take a sector number and a pointer, 0x4C finishes a save, 0x55 hands over a SaveBlock2
pointer, and 0x43, 0x57, 0x61 and 0x62 all take arguments. Sweeping them with a marker in r0 asks the
wrapper to write flash from a garbage address.

Because the shared ones are inert, the probe sweeps a range rather than taking one number per deployment. The
thunk is two halfwords in EWRAM and this CPU has no instruction cache, so the payload rewrites its
own `swi` before each call, records `r0` per number after the seven header words, and writes the
number it is about to attempt first, so a number that does hang still names itself. The whole
0x40..0x62 range is 35 results in 140 bytes and fits in one blob. It was chosen first because its
answer is predictable, so a wrong mechanism reads differently from a wrong answer. A sampler caught
the call in flight, between the pre-call markers and the return, with the result slots still holding
the filler pattern, and the whole crossing cost the guest nothing at a 25 ms stall threshold.

**Two sweeps, and they are different experiments.** Stepping the number asks what each syscall does.
Stepping `r0` with the number pinned asks what one syscall's argument selects, which is the only way
to read 0x52's index. The payload has a step for each, `p_probe_num_step` and `p_probe_a0_step`, and
pinning the number needs the first to be zero. It was a hardcoded increment for one deployment, so a
run configured as ten selectors of `swi 0x52` was ten consecutive syscalls carrying ten different
arguments, and the differences between its rows measured the number rather than the selector. The
marker at `+0x04` records the number of the pass in flight and read `0x54` while the first row was
being called, which is what exposed it.

That run measured four numbers before it stopped, each with an unrelated marker in `r0`:

| number | r0 in | r0 out |
| --- | --- | --- |
| `swi 0x52` | `0xA5A00052` | `0` |
| `swi 0x53` | `0xA5C00052` | `1` |
| `swi 0x54` | `0xA5E00052` | `1` |
| `swi 0x55` | `0xA6000052` | `0xA6000052`, unchanged |
| `swi 0x56` | `0xA6200052` | the wrapper faulted |

0x52 writing zero and 0x54 answering non-zero repeat earlier readings. 0x55 leaving `r0` as passed is
the default handler's signature, since the boolean it sets is the wrapper's own and never reaches the
guest.

**0x56 is `ReplaceSector`, and it takes a sector number and a pointer.** Reached with `0xA6200052` in
`r0` it dereferenced a near-null base and the emulator aborted:

    Invalid memory access at virtual address 0x0000000000000FF8
    PC  = main+0x573F8     LR = main+0x573EC
    x19 = 0x56                  the syscall number
    x22 = 0xA6200052            the guest's r0
    x13 = 0x0203FFC2            the guest's PC, the halfword after the thunk's `swi`
    x03 = 0x655DB09BE8          0x2D0 above the object 0x52's index 45 resolves to

The fault address is `+0xFF8` from something near zero rather than an offset into the table, so it is
inside a callee of the dispatcher and not the dispatch itself. Both save slots verified intact
afterwards, 14 sectors each and no checksum failure, so the call faulted before it wrote flash.

This is the hazard named two paragraphs above, and the sweep walked into it because the number moved
when only the argument was meant to. A sweep of numbers is safe only over the range that has been
read out of the jump table and found to take no pointer; the rest take one, and a marker word is a
garbage address. With the number pinned the range no longer exists and the question does not arise.

The log labels `0x0855D3F8` as `gba-app:0x573f8`, which re-derives the `main` base as **0x08506000**
from the emulator's own symbolisation.

With the number pinned and `r0` stepped by `1 << 21`, all ten selectors from index 45 to index 54
returned and none hung, so the abort belonged to the number and no index in that range is hostile.
**Every one of them returned `r0` = 0**, index 45 included, whose slot 9 disassembles to two
instructions returning `r0 & 0x00FFFFFF`. The wrapper therefore does not hand slot 9's return back to
the guest.

Repeating the walk with distinct markers in `r1` to `r3` closed the rest. All ten indices returned
`r0` = 0 and `r1` to `r3` exactly as passed, `A5B00001 A5C00002 A5D00003`, one distinct result across
the ten. **Across indices 45 to 54, `swi 0x52` is indistinguishable from inside the guest**: the four
registers are everything a guest is handed and none of them varies with the selector. This does not
show the ten reach the same object. It shows that if they reach different ones, the difference does
not cross the boundary, which index 45 already demonstrated is possible: its slot 9 computes a
selector-dependent value and the guest still reads zero.

`swi 0x52`'s handler is at `main + 0x05728C` and its shape accounts for every measurement:

    ldp   w1, w22, [x20, #0x48]     guest r0 into w1, guest r1 into w22
    lsr   x9, x1, #0x15             r0 >> 21
    ldr   x8, [x21, #0xe0]!         the region table
    and   x9, x9, #0x7f8            bits 3..10, so x9 is a BYTE OFFSET, not an index
    add   x8, x8, x9
    ldr   x0, [x8, #0x50]           the object for this selector
    ldr   x8, [x0]                  its vtable
    ldr   x8, [x8, #0x48]           slot 9
    blr   x8
    mov   x0, x20 ; mov w1, wzr ; mov w2, wzr ; b 0x0855D584

**The call's return value is discarded.** `x0` is overwritten with the guest state pointer and the
write-back at `main + 0x057584` is handed `w1` = `wzr`, so the guest's `r0` is set to a hardcoded
zero whatever slot 9 computed. The guest reading zero from every selector is what this code does by
construction, not a failure to propagate.

`swi 0x55` at `main + 0x057304` indexes **the same table with the same shift** and calls the same
slot 9, then branches to `main + 0x057588`, the exit that never calls the write-back at all. That is
why 0x55 returns the guest's `r0` unchanged. Two syscalls reach the selector table and neither hands
anything back.

Reading the object and the resolved target therefore has to happen at the call. The instruction is
`blr x8` at **`main + 0x0572AC`**, virtual address `0x0855D2AC`, where `x0` holds the object for this
selector, `x8` holds slot 9's resolved target and `w1` holds the guest `r0` that chose them. Stopping
one instruction after it reads the return value before `mov x0, x20` overwrites it.

`0x7f8` masks and scales in one instruction, so the entry is

    entry = (r0 >> 24) & 0xFF        and the byte offset is entry * 8

not `(r0 >> 21) & 0xFF`. Reading it as an index times eight makes every entry number eight times too
large and turns eight neighbouring arguments into what look like eight different entries.

**`r0` is a GBA address and the table is the memory bus.** Bits 24 to 31 of a GBA address are exactly
what selects a region, and each entry's slot 9 is that region's address-folding function:

| entry | region | slot 9 |
| --- | --- | --- |
| 0x02 | EWRAM, 256 KB | `and w0, w1, #0x3ffff` |
| 0x03 | IWRAM, 32 KB | `and w0, w1, #0x7fff` |
| 0x05 | palette, 1 KB | `and w0, w1, #0x3ff` |
| 0x06 | VRAM, 96 KB | `and w8, w1, #0x1ffff`, then `0x18000..0x1FFFF` folded down by `0x8000` |
| 0x07 | OAM, 1 KB | `and w0, w1, #0x3ff` |
| 0x08 to 0x0C | ROM, three waitstate mirrors | `ldr w8, [x0, #0x34] ; and w0, w8, w1`, the cartridge's own size mask |
| 0x0E | SRAM | its object is allocated well away from the others |
| everything else | unmapped | `and w0, w1, #0xffffff` |

The VRAM fold is the hardware's mirror rule exactly: `0x18000` reads `0x10000` and `0x1FFFF` reads
`0x17FFF`. The three ROM entries share one vtable and carry three separate objects, which is the
three waitstate mirrors. The ROM mask is a field rather than a constant because it is the cartridge's
size.

So `swi 0x52` resolves a GBA address to its region handler and calls slot 9, the fold. The 256 entry
points are the 256 top bytes of the GBA address space, not 256 unrelated services.

Measured across all 256 entries, the table is the GBA's own top-byte map and nothing else:

| entry | region | object |
| --- | --- | --- |
| 0x00 | BIOS | its own, folding with `0xFFFFFF` |
| 0x01 | unmapped | the default |
| 0x02, 0x03 | EWRAM, IWRAM | their own |
| 0x04 | I/O | its own |
| 0x05, 0x06, 0x07 | palette, VRAM, OAM | their own |
| 0x08 and 0x09 | ROM waitstate 0 | one object over both entries |
| 0x0A and 0x0B | ROM waitstate 1 | one object over both entries |
| 0x0C | ROM waitstate 2 | its own, same vtable as the other two |
| 0x0D | the top of waitstate 2, where EEPROM sits | its own, with the default vtable |
| 0x0E | SRAM | allocated away from every other region object |
| 0x0F | the SRAM mirror | its own |
| 0x10 to 0xFF | unmapped | the default |

Entries 0 to 15 give 14 distinct objects across 11 distinct vtables.

The vtable is the bus interface. Taking EWRAM's, `main + 0x1C21A0`, with `x0` the region object, `x1`
the cycle counter, `x2` the address and `x3` the value:

| slot | what it is |
| --- | --- |
| 2 | store two words into the object at `+0x24` and `+0x2C` |
| 3, 4, 5 | read 16, 32 and 8 bits |
| 6, 7, 8 | write 16, 32 and 8 bits |
| 9 | fold the address into the region |
| 10, 11 | return null, and a no-op |

Each accessor charges the cycle counter first, three for a halfword or byte and six for a word, then
indexes the region's host backing pointer at `+0x10`. The size is at `+0x20` and the ROM size mask at
`+0x34`.

Seven syscalls reach the table: 0x45, 0x47, 0x48 with 0x56, 0x4D, 0x52, 0x55 and 0x62. Every one of
them calls slot 9 and nothing else. The read and write accessors are not reachable by syscall number;
they belong to the emulator's own CPU core. `swi 0x62` is four instructions, incrementing a counter.

A handler must be bounded by its own control flow, not by the next handler's start. Several carry an
out-of-line continuation placed after the last entry in the table, so bounding by the next start
attributes that continuation to whichever handler happens to precede it.

### The flash sector path

`swi 0x48` and `swi 0x56` share a handler at `main + 0x057084`, with a continuation at
`main + 0x057364`. It takes guest `r0` as a 4 KB sector number and guest `r1` as the source address:

    source      = r1, resolved through the region table and folded
    destination = 0x0E000000 + r0 * 0x1000, resolved the same way

Each side is rejected, and its pointer replaced with null, on any of three conditions: the region's
backing pointer at `+0x10` is null, the folded offset is at or past the region's size at `+0x20`, or
fewer than `0x1000` bytes remain after it. Both sides are resolved before either is used, then
`0x1000` bytes are copied.

**`swi 0x56` then stores `0xFF` at destination `+0xFF8` with no null check**:

    cmp   w19, #0x56
    b.ne  exit
    mov   w8, #0xff
    strb  w8, [x21, #0xff8]

`+0xFF8` is the sector signature [pokeldn/frlg/save/save_inject.py], so that store turns the
signature `0x08012025` into `0x080120FF` and invalidates the sector it has just written. That is what
distinguishes `swi 0x56` from `swi 0x48`, and it matches the decomp's names: `ReplaceSector` writes a
sector and then voids its signature, `WriteSector` writes and leaves it.

A rejected destination leaves `x21` null, so the store faults at `0x0000000000000FF8`. That is the
abort seen when `swi 0x56` was reached with an argument in an unmapped region: the destination was
correctly rejected, the copy returned, and the unconditional store went to a null pointer. `swi 0x48`
takes the same path without the store.

Both ends of `swi 0x48` are measured on the emulated console rather than read off the handler:

| call | result |
| --- | --- |
| `r0` a sector past the flash size, `r1` an unmapped region | nothing written, flash byte-identical, no fault, no freeze |
| `r0 = 30`, `r1 = 0x08000000` (the ROM header) | sector 30 became the cartridge's first 4 KB, 4096 of 4096 bytes, neighbours untouched |
| `r0 = 30`, `r1` an EWRAM buffer the payload filled | sector 30 became those bytes; the buffer read back unchanged afterwards |

**It modifies no guest register and reports nothing.** `r0` and `r1` come back as they went in, and
`r2`, `r3` sentinels are untouched, so there is no accept/reject status: a rejected call is
distinguishable from an accepted one only by whether flash changed. A probe that passes a sector
number in `r0` and reads `r0` back has measured nothing, because the value returned is the value
passed.

The write does not reach the host's save file on its own. The emulator commits its 128 KiB flash
image when the game itself saves, and that save rewrites the game's own band and commits the whole
image, carrying a foreign sector along with it. A syscall write followed by a hard kill leaves the
file unchanged. A write issued from inside a Mystery Gift session is durable by the time the link
closes, because receiving a card saves; one issued from the resident V-blank hook during ordinary
play waits for whatever saves next. Every vtable carries a null typeinfo pointer, so the
image is built without RTTI and none of the classes has a name to recover.

Read that way, entries 165 and 166 give one object `0x655DB09918`, one vtable `main + 0x1C1FB0` and one
slot 9 `main + 0x01F7D8`, the unmapped-region default, whose whole body is

    and   w0, w1, #0xffffff
    ret

and whose returns are `r0_in & 0x00FFFFFF` at every index, including the one where the selector bits
mask out to `0x00000052`. Its neighbours in the vtable are the same kind of stub: `mov x0, xzr ; ret`
at slot 10, a bare `ret` at slot 11, a two-store setter at slot 2. The vtable carries a null typeinfo
pointer at `-0x08`, so the image is built without RTTI and the class has no name to recover.

For a survey of the whole table, the breakpoint belongs at `ldr x8, [x0]`, **`main + 0x0572A4`**,
where `x0` is already the object and nothing has been dereferenced yet. An entry holding a null or
unmapped object faults at that instruction, so a stop placed on it reads the object of an index that
would otherwise take the emulator down before reporting anything.

The store is proven rather than assumed, and the non-zero filler is what proves it. The result table
holds `offset & 0xFF` filler in the save, so a table that still reads filler is a store that did not
run and a table that reads anything else is a store that did. After the walk all 160 bytes differed
from the filler, so forty words were written and ten identical rows are a measurement rather than an
absence of one.


## Repointing the console's outgoing message

`r0` is `&client->param`, so the whole of `struct MysteryGiftClient`
[include/mystery_gift_client.h:71] sits at fixed offsets from it:

| field | from `r0` |
| --- | --- |
| `client->sendBuffer` | 0x10 |
| `client->link.sendSize` | 0x34 |
| `client->link.sendBuffer` | 0x3C |

`MysteryGiftLink_InitSend` stores the pointer it is given [mystery_gift_link.c:59], and the CRC is
taken later, at send time, over `link->sendBuffer` for `link->sendSize` bytes [:166]. So a payload
running between the InitSend and the send can point the console's own outgoing message at any address,
and the console reads that region out and CRCs it. The client script order is the whole trick:

    CLI_RECV -> CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

Swapping the middle two makes the payload patch fields the InitSend is about to overwrite.

A repointed region must not move between the CRC frame and the send frame.

```c
case 0:  header.crc = CalcCRC16WithTable(link->sendBuffer, link->sendSize);   // one frame
case 1:  SendBlock(0, link->sendBuffer + blocksize, ...);                     // the next
case 2:  if (CalcCRC16WithTable(...) != link->sendCRC) LinkRfu_FatalError();  // the one after
```

[mystery_gift_link.c:155]. Aiming a dump at `gRngValue` (0x03004220), which advances two turns every
frame, kills the link mid-transmission with *erreur de connexion*, the same run repeated unchanged
fails identically with a different CRC pair, which is the signature of a region that moves rather than
one that is corrupted. `buffer_script.build_memory_dump` refuses any range overlapping it and says what
to do instead: dump around it, or use `rng-trace`, which returns it through the 4-byte channel. It is
the only address named because it is the only one *guaranteed* to move; anything else volatile has to
be found the same way.

## The payloads

### `trainer-id-probe`

24 bytes, reads only, and chosen so one run decides everything because the answer is already known by
another route: the console put its own `playerTrainerId` into the `MysteryGiftLinkGameData` it sent
seconds earlier [mystery_gift.c:337].

```arm
    ldrh    r3, [r1, #0x0A]         @ SaveBlock2.playerTrainerId[0..1]
    ldrh    ip, [r1, #0x0C]         @ SaveBlock2.playerTrainerId[2..3]
    orr     r3, r3, ip, lsl #16
    str     r3, [r0]                @ *param
    mov     r0, #1
    bx      lr
```

- The two agree: the payload ran, in ARM state, with the arguments the decomp promises, against the
  real `gSaveBlock2Ptr`, and returned 1.
- A different value: it ran, but the arguments or the offsets are not what they were thought to be.
- No `Buffer script status:` line at all: the client script shape is wrong, or the console never
  reached the call.

A 7-character player name's terminator overwrites `playerTrainerId[0]` on the way into the game data
[mystery_gift.c:364], so with a name that long the host compares the top three bytes and says so. The
save read is unaffected.

### `save-dump` and `memory-dump`

`memory-dump` takes an absolute address. `save-dump` needs none: the console hands the payload
`gSaveBlock2Ptr` in r1 and `gSaveBlock1Ptr` in r2, so it reads either save block at any offset on any
console and any build. Up to 1024 bytes a run, `MGL_Receive` rejects more [mystery_gift_link.c:102].

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-dump --dump-block sav2 \
        --dump-size 256 --version firered
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script memory-dump --dump-address 0x0201C000 \
        --version firered

What this reaches that nothing else does: `SaveBlock1.playerParty` at 0x0038, `money` at 0x0290 XORed
with `SaveBlock2.encryptionKey` at 0xF20, the bag, flags and vars, and through `memory-dump`, IWRAM
where `gRngValue` lives. None of it is reachable by any Mystery Event opcode or link message.

### `memory-dump-multi` and `memory-dump-scatter`

`MG_LINK_BUFFER_SIZE` caps a message, not a session. The client executes a *script* of commands out
of its 1024-byte receive buffer [mystery_gift_client.c:140], and the three that produce a dump,

    CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

can appear in it as many times as it has room for. At 8 bytes a command and three fixed commands
around the loop, that is 41 passes; `mg_script.MAX_DUMP_BLOCKS` holds it at 32, because a session that
dies halfway loses every block in it. 16 KB takes about 57 seconds, blocks arriving about 2.5 s apart.

The payload cannot remember anything. `CLI_RUN_BUFFER_SCRIPT` memcpys `recvBuffer` over
`gDecompressionBuffer` on every pass [:238], so the image is restored each time and a cursor kept
inside it would never advance. What survives is what the payload is handed a *pointer* to:
`client->param`. So the block index lives there, and each pass sends `base + index * 1024` and hands
the next index on. It self-initialises off a magic in the high half, if `param` does not carry
`0x5A5A0000`, this is pass zero.

`memory-dump-scatter` is the same payload with the cursor indexing a table of bases carried in the
payload instead of being multiplied by 1024:

    adr     r3, .Ltable
    ldr     r3, [r3, r1, lsl #2]    @ this block's own base
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer

`adr` is PC-relative, which is what lets the table be read from wherever `gDecompressionBuffer` is.
Every slot of the 32-entry table is filled, the unused ones with the last address, so a pass the client
script never promised re-sends a block already held rather than pointing the console's outgoing message
at 0.

That matters because a plan does not ask for one long region. For 166 unread function bodies spread
over a megabyte:

| one join, 16 KB off the wire | bodies it catches |
|---|---|
| `memory-dump-multi`, sixteen consecutive blocks at the best base | 22 |
| `memory-dump-scatter`, the sixteen densest kilobytes | 83 |
| `memory-dump-scatter`, 32 blocks | 119 of 166 |

The readability guard is per block, not over the span. multi's blocks are one region; scatter's are
unrelated regions and each is checked.

A scattered session's blocks arrive end to end in one file, so the launcher line carries
`--dump-scatter A,B,C` and `script_read.dumps` splits the file and places each block at its own base,
tagging them `<run>[0]`, `<run>[1]`, …

`--dump-blocks 1` returns `CLIENT_SCRIPT_DUMP_MEMORY` itself, byte for byte, so the single-block path is
untouched.

### `anchors`

Asks the CPU for the addresses nothing else can supply. It writes eleven words into
`client->sendBuffer` and widens `link->sendSize` to 44; it repoints nothing, because
`CLI_LOAD_TOSS_RESPONSE` has already aimed `link->sendBuffer` at `client->sendBuffer`
[`MysteryGiftClient_InitSendWord`, mystery_gift_client.c:91].

| word | what | measured |
| --- | --- | --- |
| 0 | `sub ip, pc, #8`: where the console put the code | 0x0201C000 |
| 1 | `lr`: the ROM address after the call [mystery_gift_client.c:276], bit 0 set because the caller is THUMB | 0x08148C75 |
| 2 | `sp` | 0x03007DB8 |
| 3 | `r0` = `&client->param`, so where `AllocZeroed` put the client in `gHeap` | 0x020020D4 |
| 4-5 | gSaveBlock2Ptr, gSaveBlock1Ptr | 0x02024598, 0x0202553C |
| 6-9 | the four AllocZeroed buffers: send, recv, script, msg | 0x02006510 .. 0x02007140 |
| 10 | `link->sendBuffer` as InitSend left it; must equal word 6 | 0x02006510 |

Word 1 is the point: an absolute ROM address of a code site nameable in the decomp, so anything whose
distance from that call site is known becomes reachable. Word 10 equalling word 6 confirms every struct
offset computed from r0 against the console. The four buffers are 0x410 apart, 1024 bytes plus a
16-byte block header, so `gHeap`'s allocator behaves as `malloc.c` describes.
`buffer_script.describe_anchors` prints all eleven with every consistency check it can make.

### `save-write`

Copies its payload tail into the block and then points `link->sendBuffer` at the destination, so
what comes back over the air is what is now in the console's save rather than a copy of what was asked
for. One run writes and proves the write. The session ends in `CLI_MSG_BUFFER_SUCCESS`, which sends the
console to `MG_STATE_SAVE_LOAD_GIFT`, so the write reaches flash.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-write --dump-block sav2 \
        --dump-offset 0xB20 --write-text "some text" --version firered

The guard is the important part. `build_save_write` refuses by default any span that is not inside a
region the game never reads: `filler_90[8]` at 0x090 and `filler_B20[0x400]` at 0xB20 in
`struct SaveBlock2` [global.h:345,357], neither referenced anywhere in `src/`. A write ending four bytes
past `filler_B20` lands in `encryptionKey`, which money is XORed with, so getting this wrong scrambles a
game rather than failing a run. `--write-unsafe` is the deliberate override.

A write survives a reload from the title screen, so `SaveBlock2` really comes back from flash.

Where it lands in the file is not fixed. A sector's physical slot is
`((gLastWrittenSector + sectorId) % 14) + 14 * (gSaveCounter % 2)` [save.c:174], so the counter's
parity picks one half of the 28 sectors and `gLastWrittenSector`, which advances by one and wraps at
14 after every full save [:147], rotates within it. Sector 0 was observed at physical 6, 21, 15, 2,
17 and 4 across six consecutive saves. Find it by parsing the footers of the slot with the highest
counter and taking the sector whose id is 0; a fixed file offset reads a previous generation and
fails without a symptom. `gLastWrittenSector` is reset independently of `gSaveCounter` by
`Save_ResetSaveCounters` [:104], so computing the rotation from the counter is not safe either.

The write is surgical. Measured across one `save-write` session: zero differing bytes in SaveBlock1,
196 in SaveBlock2, and every one of them inside the 256-byte span that was asked for. Bytes written
into `filler_B20` also survive what else the link does to the save: sixteen written there in one
session were still intact ten save generations later, through a Mystery Event delivery, a Wonder Card
delivery, several soft resets and the play in between, and 256 bytes written there were unchanged
after a minute of ordinary play in which 1456 bytes of SaveBlock1 moved. That bounds ordinary play
rather than endurance.

### `memory-scan`

Takes a 32-bit needle and a range. Each call scans its budget of 32-byte blocks, writes the cursor back
into its own image and returns 0; the call that reaches the end repoints `link->sendBuffer` at its
result block and returns 1. The image opens with a branch over its own parameter block, so every offset
is fixed by construction:

| offset | |
|---|---|
| 0x000 | `b .Lcode` |
| 0x004 | cursor: the start address, advanced by the payload |
| 0x008 | end |
| 0x00C | needle |
| 0x010 | blocks per call |
| 0x014 | max_calls, the watchdog |
| 0x018 | result: matches found, final cursor, calls used, matches stored |
| 0x028 | result: 64 × (address, value) |
| 0x228 | the code |

The budget is the design. The console is holding an RFU link open while this runs, so a call that
overruns its frame costs frames the link needs. The inner loop is an `ldmia` of eight words and eight
chained `cmpne`s, about 14 ARM instructions per eight words; the default 512 blocks is 7703 instructions
a call, measured under unicorn. Out of EWRAM (a 16-bit bus, ~6 cycles an ARM fetch) that is roughly
60000 of a frame's 280896 cycles. The whole 16 MB cartridge is 1024 calls, about 17 seconds, one run.
`--scan-blocks` is the dial. In practice the host's status lines read ~60 child frames a second
throughout.

The watchdog is not optional. `max_calls` is patched in beside the range and defaults to what the
range needs plus two; a watchdog stop still answers, with a cursor short of the end saying where to
resume.

The answer is a fixed 528 bytes however many matches there are, so the host's length check
(`len(dump) == buffer_dump_size`) stays the proof that the payload repointed the send. `found` counts
every match; `hits` holds the first 64.

`memory-scan` reads with `ldmia`, so it only ever sees word-aligned matches. A needle at an entry
offset that is never word-aligned for the real stride returns zero and looks like a missing table.

### `table-scan`

Finds a table by its *shape* rather than by a constant it contains. `gSpecialVars` is 21 words holding
the addresses of the special script variables [data/event_scripts.s:51], and every one of those
addresses is the unknown, but `gSpecialVar_0x8000` through `0x800B` are twelve `u16`s declared
consecutively [event_data.c:16] and `gSpecialVars` lists them in var-id order, so its first twelve words
each sit exactly 2 above the one before.

`table-scan` finds every maximal run of `runlen` words where each is exactly `delta` above its
predecessor, and answers with where the run starts and what value it starts with, which for
`gSpecialVars` *is* `&gSpecialVar_0x8000`, so locating and reading are one run.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script table-scan --table-delta 2 \
        --table-runlen 12 --table-start 0x08140000 --table-end 0x08400000 --version firered

The run is exactly twelve. `gSpecialVars` continues past entry 11, but entry 12 is
`gSpecialVar_Facing`, declared after `Result` and `LastTalked`, so it is +6 from entry 11 and the
ascending run stops. Asking for 13 finds nothing against the real table, which is the check that the
fingerprint matches the shape rather than merely "some pointers".

A shape test is ~7 ARM instructions a word where a value test is ~1.75, so
`TABLE_SCAN_DEFAULT_BLOCKS` is 192 blocks of 16 bytes, the same per-call load as `memory-scan`'s 512
blocks of 32.

Run state is the new mechanic. A value search is memoryless; a run has to be carried across the
`ldmia` boundary *and* the frame boundary, because the table may straddle either. `run`, `runstart` and
`expect` live in the image at 0x22C..0x234 beside the cursor and are saved on the way out of every
yield.

One edge: `expect` starts at 0, so if the first word of the range happens to be 0 it is credited to a
run whose `runstart` was never written and reads back as 0. `read_table_scan` discards any hit outside
the range that was asked for.

The same shape finds a live `struct ScriptContext` in EWRAM. `InitScriptContext` stores a command
table and its end as adjacent words at +0x5C and +0x60 [include/script.h], so a 17-entry table makes
them exactly 68 apart: `--table-delta 0x44 --table-runlen 2` over EWRAM answers with the context's
address and, as its value, the table's. The context is zero until a script has run, and 0 and 0 are not
68 apart, so the scan has to follow a Mystery Event gift in the same boot. The control costs
nothing: `--table-delta 0x358` (856 = 214 entries) finds the field script context instead, whose
`cmdTable` is `gScriptCmdTable`, an address already measured.

### `rng-trace`

Samples a word once a frame and, between the two reads of each sample, calls a ROM function.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script rng-trace --trace-address 0x03004220 \
        --trace-call 0x080486B1 --trace-samples 96 --version firered

The call is `mov lr, pc; bx r2`, pc reads as that instruction + 8, which is the instruction after the
`bx`, with bit 0 clear so the callee returns to ARM state. With `--trace-call 0` it is a plain per-frame
sampler; it is a general "call this and watch what it changes" harness rather than an RNG tool. See
[the RNG](frlg_rng.md) for what it settled.

### `string-gather`

Dereferences a table of pointers. Given the address of the first pointer, a stride and a count, it
copies each string pointed at, bytes up to and including the 0xFF terminator, into one contiguous
answer, and reports where a following run should resume.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script string-gather \
        --gather-address 0x083E0D54 --gather-count 69 --gather-stride 12 --version firered

`--gather-stride` is 12 for `struct EasyChatWordInfo`, whose `text` is at offset 0; a plain array of
`const u8 *` is 4. The answer is a fixed 776 bytes, four header words then up to 760 bytes of strings.

It never truncates. A string that does not fit ends the run before it, and `next` names the entry to
resume from; a half-copied word would be indistinguishable from a French word that really is that short.
`--gather-maxlen` bounds the walk (64 by default), because a pointer that is not a string would
otherwise be copied until it happened to meet an 0xFF.

### `create-mon`

```c
void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
               u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
```

Four arguments in `r0..r3` and four on the stack. `asm/create-mon.s` is written against the console's
own prologue rather than against a calling convention taken on trust:

    08041150  push {r4,r5,r6,r7,lr}    ; sp -= 20
    08041152  mov  r7, r8
    08041154  push {r7}                ; sp -= 4
    08041156  sub  sp, #28             ; sp -= 28, so entry sp is now sp + 52
    0804115c  ldr  r4, [sp, #52]       -> entry sp +  0   hasFixedPersonality  (masked to u8)
    0804115e  ldr  r7, [sp, #56]       -> entry sp +  4   fixedPersonality     (NOT masked: u32)
    08041160  ldr  r5, [sp, #60]       -> entry sp +  8   otIdType             (masked to u8)
    08041184  ldr  r0, [sp, #64]       -> entry sp + 12   fixedOtId            (u32)

so the four go at `sp+0..sp+12` in whole words at the moment of the call. The callee does not pop them,
so the payload takes the 16 bytes back itself, and returning at all is the proof that it did, because a
payload that forgot would pop a garbage `lr`.

The destination is the payload's own image. `CreateMon` writes 100 bytes wherever it is pointed, and
the only interesting address on the console is the player's live save, so the mon is built inside the
1024 bytes the payload was copied into, with 32 bytes of guard between it and the first instruction, and
read back from there. `--create-mon-destination ADDR` copies the finished 100 bytes onward afterwards
and needs `--write-unsafe`.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon \
        --create-mon-species 151 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADE0000 --version firered

`--create-mon-call` defaults to `CreateMon | 1` from `rom_map.py`; `--create-mon-call 0` calls nothing
and answers the zeroed buffer, which checks the send path with the ROM left out. The answer is a fixed
116 bytes, four header words then the 100-byte `struct Pokemon`, and `*param` comes back as the mon's
personality.

The answer verifies itself. The 48-byte substruct region is encrypted with `personality ^ otId` and
checksummed, so a valid checksum means those two words are the ones the ROM used. `check_create_mon`
then checks species, level and the IVs out of the decrypted substructs, and
`scratchpad/verify_create_mon.py` predicts the thirteen fields the ROM *derives*: exp from
`gExperienceTables[growthRate][level]`, friendship and the ability slot from `gSpeciesInfo`, the initial
moveset and its PP from the level-up learnset, and all six stats from `CalculateMonStats`.

The nickname is deliberately not predicted. `CreateBoxMon` fills it from `gSpeciesNames`
[pokemon.c:1810], the French table on this cartridge, so whatever comes back is a *reading* of it.

Three fields the payload cannot predict are measurements of the console:

| field | value | what it says |
| --- | --- | --- |
| `language` | 3 | `gGameLanguage` is LANGUAGE_FRENCH [global.h:22] |
| `metGame` | 4 | `gGameVersion` is VERSION_FIRE_RED [global.h:11] |
| `metLocation` | 91 | `GetCurrentRegionMapSectionId()` [overworld.c:1265], where the player was standing |

`buffer_script.shiny_personality(tid, sid)` gives a `fixedPersonality` that makes the mon shiny for a
console whose secret ID has been read out of its save.

Offline, two THUMB stubs stand in for `CreateMon` at whatever address the payload was built to call:
`CREATE_MON_ARG_MODEL` writes `r0..r3` and the four stack arguments into the destination as eight words,
so the answer names each one; `create_mon_copy_model(source)` copies 100 bytes a caller prepared, so a
mon built in Python travels the whole path.

#### `--create-mon-append`

It writes `gPlayerParty`, not the save block's party.

```c
void SavePlayerParty(void)
{
    gSaveBlock1Ptr->playerPartyCount = gPlayerPartyCount;
    for (i = 0; i < PARTY_SIZE; i++)
        gSaveBlock1Ptr->playerParty[i] = gPlayerParty[i];
}
```

Appending into the save block reports success, and the mon is gone: the console saves seconds later and
copies the live array back over it [load_save.c:160,196]. A successful-looking answer from a payload
is not confirmation that anything happened.

The slot is always the first free one. It writes at `slot == playerPartyCount` and then raises the
count, which is what the game does when a mon is caught. An occupied slot is never touched, so the write
cannot destroy a Pokemon however wrong everything else is, structural rather than a check that could be
got past. A full party writes nothing and says so. The answer grew a fifth word past the mon for this
(`countBefore | slot << 8 | status << 16`, status 0 not asked / 1 appended / 2 party full / 3 dry run).

Two refusals are built in: an append together with an absolute `--create-mon-destination` is two answers
to the same question, and an append with `--create-mon-call 0` would put a hundred zero bytes in the
party.

    # dry run first: the same code with the two stores left out
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append-dry-run \
        --create-mon-species 59 --create-mon-level 30 --version firered
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append \
        --write-unsafe --create-mon-species 59 --create-mon-level 30 --version firered

The dry run reports the party count and the address it *would* write, and reads that slot's current 100
bytes back in place of the mon it built, so the answer says what a real run would overwrite. It is the
only thing that catches a `playerPartyCount` disagreeing with what is actually in the party.

An empty party slot is not a hundred zero bytes. `ZeroMonData` zeroes everything and then ends
`arg = MAIL_NONE; SetMonData(mon, MON_DATA_MAIL, &arg)` [pokemon.c:1737], and `mail` is at offset 0x55,
so an empty slot carries `0xFF` there. `buffer_script.EMPTY_PARTY_SLOT` is that shape and
`is_empty_party_slot` is the check.

Where an address may be hardcoded, and where it may not:

| | moves? | so |
| --- | --- | --- |
| `gSaveBlock1Ptr` | yes, a random 4-aligned offset re-rolled on every battle and load [`SetSaveBlocksPointers`, load_save.c:75] | take it from `r1`/`r2` every call |
| `gPlayerParty` | no, a link-time EWRAM global | an address is legitimate |

Measured: `gSaveBlock1Ptr` was 0x0202559C and then 0x02025550 six minutes apart with no reboot, 76
bytes, inside the 0..124 the mask allows.

`gPlayerParty` = 0x02024280 and `gPlayerPartyCount` = 0x02024025 were found by finding a Pokemon
rather than by looking where predicted: `scratchpad/find_party.py` walks every 4-aligned window of a
dump and reports the ones that decode as a `struct Pokemon` with a valid checksum. Exactly one did, and
the species, level, nickname and OT in it were things only the player's console knew.

### `call`

The general form: an address, up to eight argument words, the `r0` that comes back, and one address
read either side of the call.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script call \
        --call-address 0x080486D1 --call-arg 0xC0DE --call-watch 0x03004220 --version firered

    0x000  b .Lcode
    0x004  function    THUMB pointer (bit 0 set), or 0 to call nothing
    0x008  argc        how many of the eight words below are meant
    0x00C  args[0..7]  r0, r1, r2, r3, then [sp+0], [sp+4], [sp+8], [sp+12]
    0x02C  watch       a word to read before and after the call, or 0
    0x030  result      calls used, function, argc, r0, *watch before, *watch after

`asm/call.s` pushes the sixteen bytes for every call whatever `argc` says, because the callee never pops
them and a function taking fewer simply does not read them.

`SeedRng` returns nothing:
`void SeedRng(u16 seed) { gRngValue = seed; }` [random.c:15], so a return value would prove only that
*something* ran. Reading `gRngValue` immediately before and after is the only thing that says the call
did what it was called for. The payload writes nothing itself; what the callee writes is the whole risk,
so an address that has not been read as code first has no business here.

The console's own `SeedRng` bytes are the offline fixture: `tests/test_buffer_script.py` executes them
under unicorn through the payload. The eight-argument path is checked with powers of two as the
arguments, so the returned sum names exactly which slots arrived.

### `flash-write`

Composes a 4 KB sector in EWRAM on the console and writes it into save flash with
[`swi 0x48`](#the-flash-sector-path), with none of the game's save code in the way. The scratch is
`gDecompressionBuffer + 0x400`, inside the 0x4000 buffer at 0x0201C000 and a full 0x400 above the
payload's own image, so the fill cannot overwrite the code doing the filling.

    --flash-sector N            the sector, 0..31; 0..27 are the save bands and need --write-unsafe
    --flash-fill-base WORD      word[i] = base + i * step, the data pattern
    --flash-footer              compose a well-formed sector instead of a raw pattern
    --flash-id N                the sector id at +0xFF4
    --flash-derive              read the save globals and place it where that id actually lives
    --flash-position N          aim at band position N and derive the id from it instead
    --flash-counter-bias N      added to gSaveCounter for the footer

With `--flash-footer` the payload zeroes from the end of the pattern to `+0xFF4` the way the game
zeroes its buffer, computes the game's own checksum, and lays down id, checksum, signature and
counter. The status word carries the physical sector in its high half and the checksum in its low
half, so one word says both where the write went and whether the console's arithmetic agreed with
the host's.

`--flash-derive` reads `gLastWrittenSector` and `gSaveCounter` and computes the position at write
time. Nothing about placement may be decided when the payload is built: both variables advance on
every save, and a gift session saves at the end, so a position computed an hour earlier addresses a
sector the id no longer occupies.

### `call-chain`

Up to sixteen steps in order in a single frame, one answer word per step. Every question about the
console's game state is *read it, change it, read it back*, and the expensive thing is the run rather
than the call.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script call-chain \
        --chain-step call:FlagGet,0x828 \
        --chain-step call:FlagSet,0x828 \
        --chain-step call:FlagGet,0x828 --version firered

A step is 24 bytes, an op word, a target, and four argument words, and the ops are `call`,
`read32`/`read16`/`read8` and `write32`/`write16`/`write8`. `--chain-step` takes them as
`OP:TARGET[,ARG]...`, where a call's target may be one of the functions this project has measured
(`rom_map.CALLABLE`) rather than an address. A name the decomp knows is not enough: the decomp's
addresses are a different build's.

`prev` exists for one shape. A step can take its target or its first argument from the previous
step's result:

    --chain-step call:GetVarPointer,0x4024      prev = the address the GAME computed
    --chain-step read16+keep:prev               the value before, prev untouched
    --chain-step write16:prev,7                 the store, read back by the payload itself
    --chain-step read16:prev                    the value after

There is no `VarSet` among the ScrCmd workers: `ScrCmd_setvar` writes through `GetVarPointer`'s return
[scrcmd.c:472], so setting a var the game's own way is a call followed by an indirect store. (The
Mystery Event VM does reach a real `VarSet`; see [The ROM map](frlg_rom_map.md).) Two rules keep the
sequence honest, and both live in the payload rather than the builder:

- a write never becomes `prev`, so a pointer survives the store made through it;
- a read does, unless the step carries `+keep`, which is exactly what a read *before* the write
  needs.

Every write reads itself back, and that read is what lands in the answer. A write whose value does
not come back is a refused write or a target that is not what it was thought to be, and there is no
other way to tell those apart from here.

    0x000  b .Lcode
    0x004  count       how many steps are meant, 0..16
    0x010  steps[16]   {op, target, a0, a1, a2, a3}, 24 bytes each
    0x190  result      calls, count, steps executed, the op word that stopped it
    0x1A0  values[16]  one word per step, in order

A chain cannot fail silently: an opcode the payload does not have stops the run and is named in the
answer beside everything that did run, and the step count is capped in the ARM as well as in the
builder.

What the builder refuses, all offline: an empty chain, more than sixteen steps, a call to an ARM
pointer or to an address outside the cartridge, a call whose target comes from `prev` (an address
computed on the console cannot be checked from here, and a wrong one hangs the menu), an unaligned or
unreachable read, more than four arguments, and any write at all without `--write-unsafe`. Unlike
`save-write` there is no scratch region to be safe in: a chain writes wherever the game keeps the thing
being changed, and the console commits its save to flash afterwards.

Measured examples:

    call GetVarPointer(0x4024)   -> 0x020265B4
    read16 [prev] keep           -> 0
    write16 [prev] = 3           -> 3        the store, read back by the payload
    read16 [prev]                -> 3
    call VarGet(0x4024)          -> 3        the game's own reader, same frame

and, in a later session with a third `gSaveBlock1Ptr` base, the var behind that pointer still read 3,
which is why a var write goes through `GetVarPointer` rather than a computed address.

Money is encrypted, `*moneyPtr ^ gSaveBlock2Ptr->encryptionKey` [money.c:14], and one chain reads both
sides with an address the host cannot know and an offset added on the console:

    read32 [0x03004228]              -> 0x02025554     gSaveBlock1Ptr
    read32 [prev + 0x290] keep       -> 0x93E78EEE     the ciphertext, before
    call GetMoney(prev + 0x290) keep -> 0x00034103     213251, the plaintext
    call AddMoney(prev + 0x290, 1234) keep
    call GetMoney(prev + 0x290) keep -> 0x000345D5     214485, exactly +1234
    read32 [prev + 0x290]            -> 0x93E78A38     the ciphertext, after

Both XOR pairs give **0x93E4CFED**, which reads back directly out of SaveBlock2 + 0xF20.
`rom_map.SAV1_MONEY`, `SAV2_ENCRYPTION_KEY` and `CALLABLE` hold all of it.

A special reads its operands out of the special vars, so calling one is write, call, read: setting
`gSpecialVar_Result` to `GET_CARD_BATTLES_WON` and calling special 390 answered 3, with the raw word at
`SaveBlock1 + 0x3434` reading 3 in the same frame.

None of the warp or message workers may be called from a buffer script: they run inside the Mystery
Gift menu, where there is no overworld. They belong to a [field stub](frlg_rng.md#the-payload-in-the-script-body).

## Writing a sector the game will load

Four things have to be right at once, and each is a separate claim. They were established one at a
time, on the emulator, with the target outside the save bands until the arithmetic was settled.

### The checksum covers the id's chunk, not the data area

`CalculateChecksum(data, size)` sums `size` bytes as little-endian u32 words and folds
`(sum >> 16) + sum` to u16 [decomp:src/save.c]. `size` is the id's own chunk, from `sSaveSlotLayout`,
the const table at `0x083F58C4` in the French cartridge: 14 entries of {u16 offset, u16 size}.

| id | size | id | size |
| --- | --- | --- | --- |
| 0 | 3876 | 4 | 3816 |
| 1-3 | 3968 | 5-12 | 3968 |
| 13 | 2000 | | |

Summing the full 3968 instead gives the same answer for every sector the game wrote, because the
buffer is zeroed and only `size` bytes are copied, so the difference cannot be seen in any save on
disk. It appears the moment a sector is composed with data past its chunk: the loader sums the chunk,
reads a checksum taken over more than that, and rejects the sector. Two exact fits pin the table
against a real save, where the last non-zero data byte is the last byte of the chunk: id 0 size 3876
with byte 3875 last, id 13 size 2000 with byte 1999 last.

A composed sector therefore fills only its own chunk and leaves the rest zero, which restores the
equivalence and makes it structurally what the game would have written. When the id is only decided
on the console the fill stops at 2000, the smallest chunk any id carries: past that the bytes are
zero under every id, so **one checksum is valid whichever id lands there**.

### Where an id lives, and which sector carries the slot's counter

A save slot is 14 sectors and the game alternates between two of them, rotating which sector holds
which id [decomp:src/save.c:174]:

    physical = ((gLastWrittenSector + id) % 14) + 14 * (gSaveCounter % 2)

The index is `gLastWrittenSector`, not the counter. They advance together from zero and so coincide
in ordinary play, which lets a counter-based formula reproduce every sector of a real save and still
name the wrong variable; they separate as soon as a write is marked damaged, because the game then
restores `gLastWrittenSector` from `gLastKnownGoodSector` and the counter separately [save.c:159].
`gLastKnownGoodSector` and `gLastSaveCounter` are assigned from the live pair before they advance, so
they describe the previous generation exactly and the inactive band never has to be inferred.

`GetSaveValidStatus` decides which slot loads. It reads all 14 sectors of each, and counts a sector
when its signature is `0x08012025` and its stored checksum equals the checksum over
`locations[id].size` bytes, where the id comes from the sector's own footer. Two consequences decide
any injection:

- a slot is OK only when all 14 ids are present and valid; the counters within a slot are never
  required to agree,
- `slotNsaveCounter` is assigned on **every** valid sector in physical order, so it ends up holding
  the counter of the last valid sector, not a consensus and not a maximum.

So raising one sector's counter changes the slot's counter only if that sector is the last valid one
in its band. This was confirmed on the running game before it was relied on: thirteen sectors at 129
and one at 131, placed at the end of the band, and the slot reported 131 and was adopted over a
complete counter-130 band.

The save globals, measured live in IWRAM on the French build:

| address | symbol | width |
| --- | --- | --- |
| `0x030045A0` | `gLastWrittenSector` | u16 |
| `0x030045A4` | `gLastSaveCounter` | u32 |
| `0x030045A8` | `gLastKnownGoodSector` | u16 |
| `0x030045AC` | `gDamagedSaveSectors` | u32 |
| `0x030045B0` | `gSaveCounter` | u32 |

After a load, `gLastWrittenSector` describes the rotation of the slot actually adopted, so a value
carried over from before the load is wrong.

### The band the session's own save will not write

A full save assigns the previous pair, advances `gLastWrittenSector` and `gSaveCounter`, and then
writes the band the **incremented** counter selects [save.c:144-153]. Since every gift session saves
at the end, a sector written into the inactive band during a session is overwritten from RAM seconds
later by that session's own save. The band to write is the one the counter currently selects: the
save does not touch it, and our band and the session's are opposite by construction.

To be adopted afterwards, a sector must sit at band position 13 and carry `gSaveCounter + 2`: the
session's save leaves its own band at `gSaveCounter + 1`, so ours lands exactly one above it. The id
that belongs at position 13 is `(13 - gLastWrittenSector) % 14`, derived on the console like the
rest.

### A RAM snapshot is not a save

The save routine serializes at save time, so `gSaveBlock2Ptr`'s live contents are not what it would
write. Two fields prove it, and both were found by breaking something a player can see:

- **The encryption key is re-rolled on LOAD.** `LoadGameSave` restores the three blocks from flash
  and then makes a new key, applies it to every encrypted field in RAM, and stores it in SaveBlock2
  [decomp:src/load_save.c:126-128]. So the key in RAM is never the key the flash it came from is
  encrypted under. A SaveBlock2 composed from RAM and placed beside an untouched SaveBlock1 makes the
  next load decrypt with the wrong key: money read 3345243765 instead of 998927, and the RAM value
  was predicted to the byte from `raw ^ flash_key ^ ram_key`. The encrypted set spans both blocks
  [ApplyNewEncryptionKeyToAllEncryptedData]: Trainer Tower times, game stats, bag quantities, berry
  powder in SaveBlock2, money and coins.
- **The saved map view is filled only at save time.** 420 bytes at SaveBlock2 `+0x898`, 210 u16
  metatile ids with `0x03FF` as the blank marker. In a sector the game wrote it is fully populated;
  in live RAM it is zero. A composed sector hands the loader 210 zero metatiles and the overworld
  draws as a blank grid with the player and NPCs on it.

Every checksum passes and `gDamagedSaveSectors` stays 0 in both cases: the loader cannot see either.
Neither is a list to patch. A normal save writes all fourteen sectors from RAM at once, so key and
ciphertext always move together; any partial write has to reproduce that invariant or recreate this
in a new place.

### Reading flash: a 64 KiB window over a 128 KiB chip

`swi 0x48` addresses the chip linearly. The CPU does not. A guest load sees a 64 KiB aperture at
`0x0E000000`, and a 1 Mbit part reaches it as two banks, so

    sector N is bank N / 16 at 0x0E000000 + (N % 16) * 0x1000

An address above the aperture **aliases rather than faulting**. Reading `0x0E01E000` meaning sector
30 lands on `0x0E00E000` and returns sector 14 of whichever bank is selected, which on a typical save
is zeros: a wrong answer wearing the failure's clothes. Bank and window are computed from the sector,
never written by hand.

Selecting the bank is the game's own four stores [decomp:src/agb_flash.c SwitchFlashBank,
`0x081E0C74`, seven instructions with no loop and no `REG_WAITCNT`]:

    strb 0xAA -> 0x0E005555 ; strb 0x55 -> 0x0E002AAA ; strb 0xB0 -> 0x0E005555 ; strb bank -> 0x0E000000

Inlining them keeps a payload free of ROM calls entirely, so nothing executes off the stack,
`REG_WAITCNT` is never modified and no ROM function runs while the RFU link is live. Reads are
byte-wide: the flash bus is 8 bits and a wider load does not return more flash bytes.

**The console's outgoing message cannot be pointed at flash.** `memory-dump` repoints
`client->link.sendBuffer` and lets the console send the region; aimed at flash it sends something
else. Asked for `0x0E01BC00` at 1024 bytes and `0x0E01E000` at 252, the console returned identical
content belonging to neither sector. The content does not depend on the address requested, so it is
not aliasing, not banking and not size. Unexplained. A payload that wants flash copies it into EWRAM
and points the send at the copy.

### Changing one field of a real save

Composing a sector is bounded by what the save routine serializes. Reading one is not: the sector
already on the chip was written by a real save, so its key, its map view and everything nobody has
thought of are already right and already consistent with the band around it. `flash-patch` reads,
changes what it means to, and writes back, which makes a field nobody enumerated impossible to get
wrong.

An edit is two sectors, because the id being edited is rarely the one that carries the slot's
counter:

    A   the target id's sector: patch the field, recompute the checksum over the id's own chunk,
        set the counter to gSaveCounter + 2
    B   the sector at band position 13: set its counter to gSaveCounter + 2 and nothing else, not
        even the checksum, because +0xFFC is outside the summed data area

The bias of 2 is a property of the ordering rather than of any particular state. A full save
increments the counter and then writes the band the incremented value selects [decomp:src/save.c:144-153],
so the band we write (`C % 2`) and the band the session's own save writes (`(C+1) % 2`) are opposite
by construction, and ours lands exactly one counter above. The band is then a mixture — twelve
sectors at the old counter and two at the new — which the loader takes because all fourteen ids are
present and valid and the last valid sector carries the higher counter.

Measured end to end: a player name changed to POKELDN through a Wonder Card link, physical 4
differing by ten bytes and physical 13 by one, money still 998927, the overworld normal, both key
copies and all 420 bytes of the map view carried verbatim, and 0 bad checksums across all 28 sectors.

### The chain, end to end

Established with no step assumed, each one measured on the emulated console:

1. code arrives over a Wonder Card link and runs as a buffer script,
2. it composes 4 KB in EWRAM, deriving id, position and counter from the game's live globals,
3. `swi 0x48` writes it into a real flash sector, bypassing the save code entirely,
4. the game's own next save commits the whole 128 KiB image to the host file, carrying it along,
5. on the next load the game adopts our band over its own, `gDamagedSaveSectors` clean and nothing
   flagged or repaired,
6. the bytes are the live save data: the delivered pattern reads back in the running game's EWRAM,
   500 consecutive words at each of two sites.

The delivered pattern differed from the one used to pre-test the loader, which is what makes step 6
a measurement: the pre-test pattern appears at zero sites afterwards, so nothing being read is left
over. Had both used the same bytes, a success and a no-op would have differed only in the four bytes
of the counter field.

# Reading the save

A Mystery Gift session reads the console's live save and prints what the game never shows: the secret
ID, and every party Pokemon's PID, IVs and nature. One run, the console never leaves its Mystery
Gift menu, nothing is written and no Wonder Card changes hands.

## Trainer ID and secret ID

SaveBlock2 offset 0 holds the player name, gender, the 32-bit trainer id and the play time
[global.h:327]. The low half is the TID printed on the trainer card; the high half is the secret ID,
which appears nowhere in the game and travels in no link message.

    sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py \
        --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin

    ./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2

    dump.bin: 64 bytes from sav2 + 0x0
      playerName    'PLAYER'
      gender        boy
      trainerId     0xE5BBDF65  TID 57189  SID 58811
      playTime      148h 12m 30s

The TID is the check: it must match the number on the console's own trainer card. A dump that disagrees
is a bad read, whatever else it says.

## The party

SaveBlock1 0x34 is `playerPartyCount`, then `playerParty[6]` at 0x38, 100 bytes each [global.h:772]. Six
slots is 604 bytes, inside the 1024-byte per-run limit.

    sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py \
        --buffer-script save-dump --dump-block sav1 --dump-offset 0x34 \
        --dump-size 608 --dump-file party.bin

    ./.venv/bin/python tools/frlg/dump_read.py party.bin --block sav1 --offset 0x34 \
        --tid 57189 --sid 58811

    party.bin: 608 bytes from sav1 + 0x34
      playerPartyCount 5
      slot 1: ARCANINE  Lv72 nick='ARCANIN' OT='PLAYER' PID=0x30353ACA Lonely  IVs=[18,17,20,31,2,10] checksum ok
      slot 2: LUGIA     Lv77 nick='LUGIA'   OT='PLAYER' PID=0x91F854FF Relaxed IVs=[21,9,11,31,28,21] checksum ok

IVs read HP, ATK, DEF, SPE, SPA, SPD. Pass `--tid`/`--sid` to fill in the shiny column; without them it
is left blank rather than guessed. Every stored mon carries a checksum over its substructs, so
`checksum ok` on every slot means the dump is a real party rather than a stale buffer.

Party mons are stored exactly as a `.pk3`/`.ek3` stores them, which is why `pokeldn.frlg.save.mon`
decodes them unchanged: the 48 bytes at offset 0x20 are XORed with `PID ^ OTID`, and the four substructs
inside are ordered by `PID % 24`.

## Two things that will bite

The party the game plays with is not the party in the save block. `SavePlayerParty` copies
`gPlayerParty` into `gSaveBlock1Ptr->playerParty` when the console saves [load_save.c:160], so SaveBlock1
holds the party as of the last save. For the live one, dump `gPlayerParty` by address, 0x02024280 on
both measured cartridges, with `gPlayerPartyCount` at 0x02024025:

    --buffer-script memory-dump --dump-address 0x02024280 --dump-size 600

Save block addresses move. `SetSaveBlocksPointers` re-rolls them by a multiple of 4 in 0..124 on
every battle and every load [load_save.c:75]. Never carry an absolute save address from one run to the
next; `save-dump` takes the pointers fresh every call.

## What else the same payload reaches

Money at SaveBlock1 0x0290, XORed with `SaveBlock2.encryptionKey` at 0xF20; the bag; and the flags and
vars. `memory-dump` takes an absolute address instead of a save block and so reaches IWRAM, including
`gRngValue`, see [the random number generator](frlg_rng.md).

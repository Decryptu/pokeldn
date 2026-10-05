---
title: Code on the console
parent: FireRed and LeafGreen
nav_order: 3
---

# Running code on the console

The Mystery Gift client runs code sent to it through two interpreters: `CLI_RUN_MEVENT_SCRIPT`
(opcode 15) hands the bytes to the Mystery Event VM, `CLI_RUN_BUFFER_SCRIPT` (opcode 21) to the CPU.
Neither needs a glitch, a prepared save or any setup; the console stays on its Mystery Gift menu.

Addresses on this page are French FireRed, cartridge BPRF, software version 0x0A. LeafGreen's are on
[LeafGreen](frlg_leafgreen.md); the tables are on [The ROM map](frlg_rom_map.md).

# The Mystery Event VM

A separate interpreter [src/mystery_event_script.c] with its own 17-command table
[data/mystery_event_script_cmd_table.s], distinct from the field-script VM a Wonder Card's delivery
script compiles to. `pokeldn/frlg/rom/mystery_event.py` assembles every command
(`MysteryEventScript.blob()` holds the data, the assembler resolves pointers). Every opcode is
verified on retail hardware.

## The command table

| # | command | operands after the opcode byte | returns | effect |
|---|---|---|---|---|
| 0 | `nop` |  | FALSE | nothing |
| 1 | `checkcompat` | u32 base, u16, u32, u16, u32 | TRUE | the compatibility gate |
| 2 | `end` |  | TRUE | `StopScript` |
| 3 | `setmsg` | u8 selector, ptr | FALSE | `StringExpandPlaceholders(gStringVar4, str)` when the selector is `0xFF` or equals the status |
| 4 | `setstatus` | u8 | FALSE | `ctx->data[2] = value` |
| 5 | `runscript` | ptr | FALSE | `RunScriptImmediately` on a field script |
| 6 | `initramscript` | u8 group, u8 map, u8 object, ptr, ptr | FALSE | `InitRamScript` bound to any map and object |
| 7 | `setenigmaberry` | ptr | FALSE | writes `gSaveBlock1Ptr->enigmaBerry` |
| 8 | `giveribbon` | u8 index, u8 ribbonId | FALSE | a gift ribbon onto every non-egg party mon |
| 9 | `givenationaldex` |  | FALSE | `EnableNationalPokedex()` |
| 10 | `addrareword` | u8 | FALSE | `EnableRareWord` (an Easy Chat trendy saying) |
| 11 | `setrecordmixinggift` |  | TRUE | dead: `SetIncompatible` |
| 12 | `givepokemon` | ptr | FALSE | a whole `struct Pokemon` plus attached Mail into the party |
| 13 | `addtrainer` | ptr | FALSE | a 188-byte `BattleTowerEReaderTrainer` |
| 14 | `enableresetrtc` |  | TRUE | dead: `SetIncompatible` |
| 15 | `checksum` | u32, ptr, ptr | TRUE | status 1 if `CalcByteArraySum` over the range does not match |
| 16 | `crc` | u32, ptr, ptr | TRUE | the same with `CalcCRC16` |

## `checkcompat` is optional

`checkcompat` opens every official script and gates the language and version masks (the decomp's
`LANGUAGE_MASK` is English). A script can skip it:

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

`RunScriptCommand` [script.c:107] loops inside one call until a command returns TRUE. Without
`checkcompat`, `data[3]` stays 0: the script runs to its first TRUE-returning command (normally
`end`) and the outer `while` stops. The masks never matter, and pointers relocate as
`operand - ctx->data[1] + ctx->data[0]` with `data[1]` 0 (set only by `checkcompat`) and `data[0]` the
console's 1024-byte `client->recvBuffer`: an operand of N is N bytes into what was sent. `checkcompat`
is the one command the assembler allows code after.

## The return channel

`MEventScript_Run` writes the status into `client->param` [mystery_event_script.c:75];
`CLI_LOAD_TOSS_RESPONSE` loads it into `MG_LINKID_RESPONSE` [mystery_gift_client.c:204]. These four
client commands return a u32 the script chooses:

    CLI_RECV MG_LINKID_RAM_SCRIPT
    CLI_RUN_MEVENT_SCRIPT
    CLI_LOAD_TOSS_RESPONSE
    CLI_SEND_LOADED

`setstatus` sets any value. The stock statuses:

| status | meaning |
|---|---|
| 0 | no command set one |
| 1 | `setenigmaberry` could not validate the berry, or a `checksum`/`crc` mismatch |
| 2 | success; every opcode that did its job sets this |
| 3 | `SetIncompatible`, or `givepokemon` found a full party |

`CLI_COPY_RECV_IF` and `CLI_COPY_RECV_IF_N` can branch the client script on it
[mystery_gift_client.c:170] (unused).

The menu prints its result from `CLI_RETURN` [`GetClientResultMessage`, mystery_gift_menu.c:884], so
`setmsg` is invisible here. Only a success message reaches `MG_STATE_SAVE_LOAD_GIFT` [:1379], without
which the event's writes are lost at reset; `CLIENT_SCRIPT_MEVENT_DONE` therefore returns
`CLI_MSG_CARD_RECEIVED` even with no card. `CLI_MSG_BUFFER_SUCCESS` (13), the other success exit,
prints the 64 bytes `CLI_COPY_MSG` pushed.

### The probe script

`--gift mystery-event-probe` is harmless: `givenationaldex` is a no-op once the National Dex is on,
and `checksum` only reads.

    givenationaldex; setstatus 42; checksum 1026, 16, 31

| status | what it proves |
|---|---|
| 42 | the chain ran to the end and pointer operands are offsets into the sent buffer |
| 1 | the chain ran, but the relocated pointers did not land on the probe bytes |
| 2 | `givenationaldex` ran and nothing after it did |
| 0 | the VM was entered but no command executed |
| nothing | the client script shape is wrong, not the VM |

`checksum` is terminal and keeps the earlier status on a match. A retail FireRed answers 42.

## `givepokemon`

`pokeldn/frlg/save/mevent_pokemon.py` builds the payload: a 100-byte encrypted party mon, then the
34-byte `struct Mail` the console reads at `pointer + sizeof(struct Pokemon)`.
`--gift mystery-event-celebi` ships one. Unlike the field-script `givemon`, it:

- attaches mail. `ItemIsMail` gates it, so the held item must be one of the twelve mail items
  [mail_data.c:167]; `GiveMailToMon2` copies the whole struct (words, sender name, trainer id,
  species, item) into `gSaveBlock1Ptr->mail` [:100];
- sets `FLAG_SET_SEEN` and `FLAG_SET_CAUGHT` on the national number;
- lands at the Mystery Gift menu: the mon is in the party when the menu closes.

Status 2 is success, 3 a full party with nothing written. Never put a `setstatus` after it.

Traps the builder enforces:

- the mon's `mail` byte must be `MAIL_NONE` (0xFF); 0 is mail slot 0, read as real mail;
- `personality == otId` makes the encryption key 0, so the mon validates shuffled or unshuffled and an
  unshuffled one could ship;
- the party tail is derived; a zero tail reads back as level 0;
- the held item and the mail's `itemId` must agree: `GiveMailToMon2` sets the held item from the mail.

## `initramscript`

`initramscript 3, 0, 2` binds a field script to group 3, map 0, object 2, the fat man in south Pallet
Town. After a reboot he says the script's lines, with `{PLAYER}` expanded.

`CLI_SAVE_RAM_SCRIPT` uses `InitRamScript_NoObjectEvent` (MAP_UNDEFINED, object 0xFF) [script.c:578],
which only the delivery man's `GetSavedRamScriptIfValid` [:554] reads, and only with a valid Wonder
Card. Real coordinates reach `GetRamScript(gSpecialVar_LastTalked, script)` [:514,
field_control_avatar.c:458], which runs the script in place of the object's own and ignores the card.
`gSpecialVar_LastTalked` is the object's local id, in `map.json` order from 1.

It costs the Wonder Card ([the one RAM script slot](frlg_gift.md#the-one-ram-script-slot)); sessions
log "holding no Wonder Card" until the next ordinary card takes the slot back. The object loses its
own script while bound: bound to a static encounter's object, the script replaces the encounter.

## Traps

- `setenigmaberry` cannot set the item effect. `struct ReceivedEnigmaBerry` [berry.c:944] is 1322
  bytes: `Berry2` (28 bytes), `u8 unk_001C[0x4FA]`, then `itemEffect[18]`, `holdEffect` and
  `holdEffectParam` at 0x516, past the 1024-byte buffer; the tail is whatever follows `recvBuffer` on
  the heap (`build_enigma_berry_blob`; the simulator reports `read_past_buffer`).
- The two ROM description pointers in `struct Berry2` must be read off the cartridge and sent back
  unchanged: the Berry Pouch dereferences them from the save forever.
- `giveribbon` index 7..10: `GiveGiftRibbonToParty` [pokemon_size_record.c:193] accepts `index < 11`,
  but `sGiftRibbonsMonDataIds` has seven entries copied into a `u8[8]`, so 7..10 `SetMonData` a field
  id from uninitialised stack. The assembler refuses anything above 6. FRLG has no ribbon UI; a ribbon
  shows only after a transfer.
- A script with no terminal command decodes the rest of the zero-filled buffer as opcodes. `assemble()`
  and the server refuse one.
- `setrecordmixinggift` and `enableresetrtc` each make one call, `SetIncompatible`, and stop the chain
  [mystery_event_script.c:227, :291]. The composer rejects them.
- `addrareword` and `setenigmaberry` are invisible in game; read them back from the save:
  `additionalPhrases` (SaveBlock1 + 0x2F10, one more Easy Chat word) and `enigmaBerry` (+0x30EC). The
  `VAR_ENIGMA_BERRY_AVAILABLE` it sets is read nowhere else in FRLG.

## How it is wired

- `pokeldn/frlg/rom/mystery_event.py`: opcodes, assembler, disassembler (`describe`), and `run()`,
  the simulator the offline client uses.
- `pokeldn/frlg/gift/mg_script.py`: `CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT` (no card held: card, delivery
  script, event), `CLIENT_SCRIPT_RUN_MEVENT` (card already held: the event alone, nothing tossed),
  `CLIENT_SCRIPT_MEVENT_DONE` (the shared success tail).
- `pokeldn/frlg/gift/mg_server.py`: `SCRIPT_SEND_MYSTERY_EVENT` with `SVR_LOAD_MEVENT` and
  `SVR_READ_MEVENT_STATUS`; the status lands in `server.mevent_status` and the host log.
- `pokeldn/frlg/gift/gift_composer.py`: `WonderGift.mevent` validates assembled bytes.

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

[mystery_gift_client.c:237,276]. Every payload rests on five facts:

- 1024 bytes (`MG_LINK_BUFFER_SIZE`) are copied whatever was sent, so a payload runs with the tail of
  the previous receive behind it and must be self-contained.
- `r0 = &client->param`, `r1 = gSaveBlock2Ptr`, `r2 = gSaveBlock1Ptr`: both save blocks, readable and
  writable.
- `client->param` is what `CLI_LOAD_TOSS_RESPONSE` ships back as `MG_LINKID_RESPONSE` [:204].
- It is called once per frame until it returns 1; a payload that never does hangs the Mystery Gift
  menu with no way out. The `memcpy` runs once, at `CLI_RUN_BUFFER_SCRIPT` [:239], so a payload can
  keep state across frames.
- ARM state: the caller reaches it with a `bx` to a word-aligned address.

`gDecompressionBuffer` is at 0x0201C000 (measured by `anchors`). Payloads are position independent.

## The build

The app's Mystery Gift builder assembles ARM source with the same toolchain
(`pokeldn/frlg/rom/custom_code.py`), or takes a raw `.bin`, and runs it on the simulated console
before it is sent. `.pokegift` files carry compiled ARM bytes, cartridge targets and response
settings. [Mystery Gift files](gifts.md#console-code) documents packaging and sharing.

- `asm/*.s`, one ARM source per payload, assembled by `scripts/gen_buffer_scripts.py` into the
  committed `pokeldn/frlg/rom/buffer_payloads.py`; `tests/test_buffer_script.py` re-assembles and
  compares when `arm-none-eabi-as` is installed.
- `pokeldn/frlg/rom/buffer_script.py`: registry, validation, and `emulate()` / `emulate_repeating`,
  which run a payload under unicorn on the GBA memory map with the console's three arguments; one that
  faults or never returns 1 never reaches the air.
- `pokeldn/frlg/gift/mg_script.py`: `CLIENT_SCRIPT_RUN_BUFFER` (recv, run, load the return channel,
  send, recv the next script) and `CLIENT_SCRIPT_BUFFER_SUCCESS`.
- `pokeldn/frlg/gift/mg_server.py`: `SCRIPT_RUN_BUFFER_SCRIPT`. No card and no toss prompt; a held
  Wonder Card is kept.
- Both simulated consoles, written from the decomp independently, execute the payload with per-frame
  re-entry: `pokeldn/frlg/gift/mg_client.py` and `ConsoleClientModel` in
  `tests/test_mystery_gift_flow.py`.

Offline first, every time:

    ./.venv/bin/python -m pytest tests/test_buffer_script.py -q
    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script -v

On hardware the console waits on Mystery Gift -> Wonder Cards -> Friend and joins the host. In the
run lines below, `HOST` stands for
`POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS --dump-file DUMP.bin`,
and `IP_HOST` for `./.venv/bin/python -u bin/frlg_mg_host.py --over-ip --dump-file DUMP.bin`, which
serves an emulated console over the LAN with no radio and no keys. Never SIGTERM the host before
`DUMP.bin` exists; it is written seconds after `Buffer script dump: N bytes`:

    until ls DUMP.bin >/dev/null 2>&1; do sleep 2; done

## Where a payload can live

A buffer script is re-copied every frame, so nothing it writes into its own image survives. Code that
outlives the menu goes where the game never writes:

    0x0203FC00 .. 0x02040000    1024 bytes, above every symbol the game links

The highest sized EWRAM symbol ends at 0x0203FBAC ([EWRAM is at the same addresses in both
builds](frlg_rom_map.md)). Named from the decomp (`gHeap`'s 114688 bytes carry no size in the symbol
table), this is the only unclaimed EWRAM span; the rest are three- and eight-byte alignment holes.

    0x0203F768 .. 0x0203FBAC    1092 bytes, newlib's malloc state

`__malloc_av_` and the malloc counters after it are reached only from newlib's stdio, which only
`AGBPrintf`, unused in a release build, calls (pokefirered_switch.elf: the only `bl` to `_malloc_r`,
`_calloc_r` and `_free_r` are inside libc). A 0xA5 fill there survived menus, walking and a whole wild
battle on the French FireRed under mGBA. The GB-Link Team cards keep their relocated script there
([frlg_gift.md](frlg_gift.md#gb-link-team-cards)).
`scratchpad/ewram_symbol.py ADDR LEN` checks an address.

Never pick an address because it reads zero. 0x0202B280, 0x020185C4 and 0x0203B0E9 read tens of
kilobytes of zeros and are the battle and box buffers, the run-up to `gDecompressionBuffer`, and
allocator bookkeeping; 0x02012304 is in `gHeap`. 0x0202B280 lies inside `gPokemonStorage`: a write
there can land on a boxed Pokemon's checksum, and the save then keeps a Bad Egg.

A soft reset clears EWRAM twice: `DoSoftReset` calls `SoftReset(RESET_ALL & ~RESET_SIO_REGS)`
[main.c:488] (`svc 0x1` then `svc 0` [libagbsyscall.s:69]), then `AgbMain` calls
`RegisterRamReset(RESET_ALL)` [main.c:134]; bit 0 of 0xFF is `RESET_EWRAM` [include/gba/syscall.h:4,12].
The Switch wrapper also restarts the emulated console, so `AgbMain` runs twice: `gIntrTable` and
`INTR_VECTOR` (0x03007FFC) are cleared and rebuilt twice per boot, entries 1, 2 and 7 taking wireless
values in between (sampled at 328000 a second: 33.3 ms, then 133.6 ms to the second clear, 33.6 ms to
its rebuild). The boot rebuilds nothing above 0x0203B0E8. Nothing between two boots writes
0x0203FC00..0x02040000: a marker there persists across the title screen, a reload, menus, a save, a
map change, a battle and a PC box, and a soft reset (A+B+START+SELECT) clears it.

## The per-frame hook

`gIntrTable` is at 0x03002720 on the French cartridge; entry 4, the V-blank handler, holds `VBlankIntr`
(0x0800071D). It is fourteen function pointers written once by `InitIntrHandlers` from
`gIntrTableTemplate` [main.c:339], reached by the BIOS through `IntrMain`, whose address the vector at
0x03007FFC holds. Replacing entry 4 gives code a call every frame in every game state;
`gMain.vblankCallback` and `gMain.callback2` are rewritten whenever a menu or battle starts.

Located in a console's IWRAM: `IntrMain_Buffer` is 0x03002760 (English 0x03002810) and
`gSaveBlock1Ptr` is 0x03004228 (English 0x030042D8), so the cartridge's IWRAM sits 0xB0 below the
English build's at these addresses. IWRAM does not transfer between builds the way EWRAM does.

| entry | cartridge | English | |
|---|---|---|---|
| 0 VCount | 0x08000805 | 0x0800081C | `VCountIntr` |
| 1 Serial | 0x03004B34 | | an IWRAM handler while the link is up |
| 2 Timer3 | 0x08005AE1 | | `Timer3Intr`, a different ROM segment and delta |
| 3 HBlank | 0x080007D5 | 0x080007EC | `HBlankIntr` |
| 4 VBlank | 0x0800071D | 0x08000734 | `VBlankIntr` |
| 5, 6, 8-13 | 0x08000885 | 0x0800089C | `IntrDummy`, eight times |
| 7 | 0x081E0D35 | | the RFU timer handler, `sTimerIntrFunc = gIntrTable + 0x7` [main.c:85] |

Entries 1 and 7 differ from the template as the decomp predicts while wireless runs; entries 1 and 2
keep their wireless values after a session until a reset. The game writes entry 4 only in
`InitIntrHandlers`, which re-runs only on a soft reset.

### Code that outlives the session

A twenty-byte stub in the staging area, installed in entry 4, runs every frame in every game state
after the session has closed. `asm/resident/vblank-hook.s`:

```arm
    ldr     r0, .Lcounter
    ldr     r1, [r0]
    add     r1, #1
    str     r1, [r0]
    ldr     r0, .Loriginal
    bx      r0                      @ tail branch: lr still points at intr_return
```

`IntrMain` enters a handler in SYS mode with `lr` at `intr_return` and lets it clobber r0-r3 [crt0.s,
`jump_intr`], so the replaced handler returns through its own `bx lr`. Both literals are patched
before sending.

A `call-chain` installs it: the five words first, entry 4 last, every write read back.

    read32  [0x03002730]                gIntrTable[4], 0x0800071D
    write32 [0x0203FC00] = 0x68014802   the stub
    write32 [0x0203FC04] = 0x60013101
    write32 [0x0203FC08] = 0x47004801
    write32 [0x0203FC0C] = 0x0203FC40   the counter's address
    write32 [0x0203FC10] = 0x0800071D   the handler being replaced
    write32 [0x03002730] = 0x0203FC01   the hook, THUMB bit set
    read32  [0x0203FC40]                the counter

The hook runs once per frame in every game state: over 19995 frames it counted 59.0 to 63.3 calls
a second on the menu, title screen, overworld, party menu, a wild battle and across an in-game
restart. A soft reset ends it: `InitIntrHandlers` rewrites entry 4 [main.c:339] (`gIntrTable[4]`
reads zero, then 0x0800071D). Mystery Gift is reachable only after a boot, which clears EWRAM, so a payload that
must be present without a fresh session needs its installer in the save.

### Re-arming it after a reset

`--gift resident-hook` sends a Wonder Card whose Mystery Event script `initramscript`s a field script
onto the player's mother. The binding lives in the save and survives a power cycle ([the one RAM
script slot](frlg_gift.md#the-one-ram-script-slot)); talking to her after any boot installs the hook,
with no link and no host.

`asm/field/install-vblank-hook.s`, 68 bytes, staged with `setptr` at six script bytes each and run
with `callnative`: 418 of the 995 bytes a RAM script body holds.

    read  gIntrTable[4]
    if it already names the stub: return, writing nothing
    write the five words of the V-blank stub to the staging area
    write the handler just read into the stub's fifth word
    zero the counter
    write the staging area, Thumb bit set, into gIntrTable[4], last

The tail target comes from the table, so the hook chains whatever handler is there. The guard at the
top is required: installing twice makes the stub tail-branch to itself, which spins inside an
interrupt handler and freezes the overworld.

The script block at `SaveBlock1 + 0x32E0` survives a soft reset at the re-rolled pointer (verified on
an emulator).

The script rebuilds the code on every arming, so the code is bounded by a script body: 162 bytes
staged, or about 755 appended after the last command and reached with a trampoline.

### A payload larger than a script body

`asm/field/save-loader.s`, 64 bytes, is all the RAM script stages whatever the payload weighs: it reads
`gSaveBlock2Ptr` fresh, adds 0xB20, copies N words to the staging area, checks the first word against a
magic (a never-written save, or a region a later card reached) and branches in. It uses only r0-r3 and
never pushes, so the payload returns straight to `ScrCmd_callnative`'s caller.

The blob is 936 bytes, one `save-write` (`MAX_SAVE_WRITE_BYTES`, the 1024-byte receive buffer less
the writer):

    +0x000  magic 0x444C4B50
    +0x004  installer
    +0x054  the V-blank hook
    +0x068  filler
    +0x3A4  checksum over the filler

The installer installs nothing unless the filler sums right
([proving the size](frlg_rng.md#proving-the-size-rather-than-the-jump)).

The hook's tail target in the save's copy must be the measured `VBlankIntr`, never zero: the loader
copies over a hook that may be live, and on a second visit the installer finds the hook installed and
patches nothing. A zero there crashes the console to a black screen after the second conversation.

The RAM script is 394 of 995 bytes whatever the payload. `filler_B20` holds 1024 bytes, the save's
other unused regions about 700. A larger blob is written in pieces of 936 bytes, one payload each, in
one session ([`save-write`](#save-write)). At the full
1024 the blob reaches the top of EWRAM and the counter moves into the 84 bytes below the staging area.
The staged copy equals the save except the hook's fifth word, and every arming stages the same bytes
(verified on an emulator, where the counter ran at 60.0 a second).

### Calling the wrapper

The GBA code reaches the Switch emulator through Sloop syscalls: 23 between
`swi 0x40` and `swi 0x62`, with gaps at 0x46, 0x4E, 0x52 and 0x58 to 0x60 [src/sloopsvc.c]. A
resident payload can issue any of them: the builder assembles a thunk `swi N ; bx lr` into the blob
with the number patched in. Markers go down before the call, since a syscall that does not return
leaves nothing else to read:

    +0x00  0xB0B00001   the probe was reached
    +0x04  the syscall number
    +0x08  0xB0B00002   it returned, and zero until it does
    +0x0C  r0, r1, r2, r3 as the syscall left them

`swi 0x54`, `svc_CommsAllowedByParentalControls` [sloopsvc.c:182], returns non-zero on a console
with no parental controls.

#### The dispatcher: the Sloop syscall boundary

The dispatcher is at `main + 0x057014`, its jump table at `main + 0x17D7F6`. It admits
`N` in 0x40..0x62:

    cmp   w2, #0x2b ; b.lo default       below 0x2B, the BIOS syscalls
    sub   w9, w19, #0x40 ; cmp w9, #0x22 ; b.hi default
    ldrh  w12, [table, w9, lsl #1]       a u16 word-offset from 0x05706C
    br    base + offset * 4

Thirty-five entries, twenty-three distinct handlers. Every number `sloopsvc.c` names has its own.
0x46, 0x4E and 0x58 to 0x60 share the default, exactly the decomp's gaps. 0x48 and 0x56 share one
handler (`WriteSector`, `ReplaceSector`); 0x40 and 0x41 share one that branches on the number.

The default is `cmp w19, #0x2a ; cset w0, hi ; ret`. That `w0` is the wrapper's own "handled"
boolean, not the guest's r0, so an unimplemented number is inert (no hang) and leaves every guest
register untouched. A probe that passes zero and reads zero has measured nothing.

Never sweep 0x40..0x62 blind: 0x48 and 0x56 take a sector number and a pointer, 0x4C finishes a save,
0x55 hands over a SaveBlock2 pointer, and 0x43, 0x57, 0x61 and 0x62 take arguments. A marker in r0
becomes a garbage flash source.

The probe rewrites its own `swi` before each call (no instruction cache), writes the number first so a
hang names itself, and records `r0` per number after the seven header words (35 results, 140 bytes).
`p_probe_num_step` steps the number; `p_probe_a0_step` steps `r0` with the number step at zero.

| number | r0 in | r0 out |
| --- | --- | --- |
| `swi 0x52` | `0xA5A00052` | `0` |
| `swi 0x53` | `0xA5C00052` | `1` |
| `swi 0x54` | `0xA5E00052` | `1` |
| `swi 0x55` | `0xA6000052` | `0xA6000052`, unchanged |
| `swi 0x56` | `0xA6200052` | the wrapper faulted |

`swi 0x56` (`ReplaceSector`) with a destination the region table rejects (a marker in r0) faults the
emulator at `0xFF8` (`main+0x573F8`), and the save is untouched:

    Invalid memory access at virtual address 0x0000000000000FF8
    PC  = main+0x573F8     LR = main+0x573EC
    x19 = 0x56                  the syscall number
    x22 = 0xA6200052            the guest's r0
    x13 = 0x0203FFC2            the guest's PC, the halfword after the thunk's `swi`
    x03 = 0x655DB09BE8          0x2D0 above the object 0x52's index 45 resolves to

The log labels `0x0855D3F8` as
`gba-app:0x573f8`, which puts the `main` base at 0x08506000.

#### `swi 0x52` and `swi 0x55`: the memory bus

0x52 has a handler the decomp lacks, at `main + 0x05728C`:

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

The return value is discarded: the write-back at `main + 0x057584` is handed `w1 = wzr`, so the guest
reads r0 = 0 always and r1 to r3 unchanged. `swi 0x52` returns r0 = 0 and leaves r1 to r3 and the
save unchanged, from the overworld, across selectors 45 to 54 (`r0` stepped by `1 << 21`). `swi 0x55` at
`main + 0x057304` indexes the same table with the same shift, calls slot 9 and exits through
`main + 0x057588`, which skips the write-back; that is why it returns r0 unchanged.

To read the object and target, stop at `blr x8`, `main + 0x0572AC` (virtual `0x0855D2AC`): `x0` is the
object, `x8` slot 9's target, `w1` the guest r0. One instruction later the return value is still in
`x0`. For a survey of all 256 entries stop at `ldr x8, [x0]`, `main + 0x0572A4`, before anything is
dereferenced: a null or unmapped object faults there.

`0x7f8` masks and scales in one instruction:

    entry = (r0 >> 24) & 0xFF        and the byte offset is entry * 8

Reading it as `(r0 >> 21) & 0xFF` makes every entry eight times too large. `r0` is a GBA address and
the table is the memory bus: the top byte selects the region and slot 9 is its address fold.

| entry | region | object | slot 9 |
| --- | --- | --- | --- |
| 0x00 | BIOS | its own | `and w0, w1, #0xffffff` |
| 0x01 | unmapped | the default | `and w0, w1, #0xffffff` |
| 0x02 | EWRAM, 256 KB | its own | `and w0, w1, #0x3ffff` |
| 0x03 | IWRAM, 32 KB | its own | `and w0, w1, #0x7fff` |
| 0x04 | I/O | its own | |
| 0x05 | palette, 1 KB | its own | `and w0, w1, #0x3ff` |
| 0x06 | VRAM, 96 KB | its own | `and w8, w1, #0x1ffff`, then `0x18000..0x1FFFF` folded down by `0x8000` |
| 0x07 | OAM, 1 KB | its own | `and w0, w1, #0x3ff` |
| 0x08, 0x09 | ROM waitstate 0 | one object over both | `ldr w8, [x0, #0x34] ; and w0, w8, w1`, the cartridge's size mask |
| 0x0A, 0x0B | ROM waitstate 1 | one object over both | same vtable |
| 0x0C | ROM waitstate 2 | its own | same vtable |
| 0x0D | top of waitstate 2, where EEPROM sits | its own | the default vtable |
| 0x0E | SRAM | allocated away from every other region object | |
| 0x0F | the SRAM mirror | its own | |
| 0x10 to 0xFF | unmapped | the default | `and w0, w1, #0xffffff` |

Entries 0 to 15 give 14 objects and 11 vtables. The VRAM fold is the hardware mirror (`0x18000`
reads `0x10000`, `0x1FFFF` reads `0x17FFF`). The default object is `0x655DB09918`, vtable
`main + 0x1C1FB0`, slot 9 `main + 0x01F7D8`; its slot 10 is `mov x0, xzr ; ret`, 11 a bare `ret`,
2 a two-store setter. Every vtable has a null typeinfo pointer at `-0x08`: no RTTI, no class names.

EWRAM's vtable, `main + 0x1C21A0` (`x0` the region object, `x1` the cycle counter, `x2` the address,
`x3` the value):

| slot | what it is |
| --- | --- |
| 2 | store two words into the object at `+0x24` and `+0x2C` |
| 3, 4, 5 | read 16, 32 and 8 bits |
| 6, 7, 8 | write 16, 32 and 8 bits |
| 9 | fold the address into the region |
| 10, 11 | return null, and a no-op |

Accessors charge the cycle counter first (three for a halfword or byte, six for a word), then index
the host backing pointer at `+0x10`. Size is at `+0x20`, the ROM size mask at `+0x34`.

Seven syscalls reach the table (0x45, 0x47, 0x48 with 0x56, 0x4D, 0x52, 0x55, 0x62), and each calls
only slot 9; the read and write accessors belong to the emulator's CPU core. `swi 0x62` is four
instructions incrementing a counter.

Bound a handler by its own control flow: several carry an out-of-line continuation after the last
table entry, which bounding by the next handler's start misattributes.

### The flash sector path

`swi 0x48` and `swi 0x56` share a handler at `main + 0x057084`, continuation at `main + 0x057364`.
Guest `r0` is a 4 KB sector number, guest `r1` the source:

    source      = r1, resolved through the region table and folded
    destination = 0x0E000000 + r0 * 0x1000, resolved the same way

Each side is rejected (pointer set to null) if the region's backing pointer at `+0x10` is null, the
folded offset is at or past the size at `+0x20`, or fewer than `0x1000` bytes remain. Both sides
resolve before `0x1000` bytes are copied. `swi 0x56` then stores `0xFF` at destination `+0xFF8` with
no null check:

    cmp   w19, #0x56
    b.ne  exit
    mov   w8, #0xff
    strb  w8, [x21, #0xff8]

`+0xFF8` is the sector signature [pokeldn/frlg/save/save_inject.py]: `0x08012025` becomes `0x080120FF`
and the sector is void. `ReplaceSector` writes and voids, `WriteSector` writes. A rejected destination
leaves `x21` null, so `swi 0x56` faults at `0xFF8`, the abort above.

Measured with `swi 0x48` on the emulated console:

| call | result |
| --- | --- |
| `r0` a sector past the flash size, `r1` an unmapped region | nothing written, flash byte-identical, no fault, no freeze |
| `r0 = 30`, `r1 = 0x08000000` (the ROM header) | sector 30 became the cartridge's first 4 KB, 4096 of 4096 bytes, neighbours untouched |
| `r0 = 30`, `r1` an EWRAM buffer the payload filled | sector 30 became those bytes; the buffer read back unchanged |

It modifies no guest register and returns no status: only a flash read tells an accepted call from a
rejected one.

The emulator commits its 128 KiB flash image only when the game saves, carrying a foreign sector
along. A syscall write followed by a hard kill leaves the host file unchanged. A write from inside a
Mystery Gift session is durable once the session ends in a success message, which saves
[mystery_gift_menu.c:1379]; after any other result, and from the resident hook, it waits for the next
save.

### The breakpoint hooks

The wrapper's GBA CPU object has 256 hook slots at `cpu + 0x170`, one per `bkpt` immediate. The ARM
decode tests `(insn & 0xFFF000FF) == 0xE1200070`, the THUMB decode `(insn & 0xFF00) == 0xBE00` at
`main + 0x01FCE4`; the THUMB handler at `main + 0x01EFC0` calls vtable slot 2 of the hook in slot
`imm8` (hook, `&insn`, the `bkpt`'s address, the CPU) through `main + 0x01F820`. A hook returning 1
has the core execute the instruction it stored in `insn`; 0, or an empty slot, makes the `bkpt` a
no-op. `main + 0x022A2C` registers a hook and refuses a filled slot. Two slots are filled:

| slot | owner | hook | what it does |
| --- | --- | --- | --- |
| `bkpt #0x52` | the Sloop component, vtable `main + 0x1C3878` | `main + 0x05499C` -> `main + 0x056368` -> `main + 0x03E850` | the librfu patches below |
| `bkpt #0xFF` | the application object, vtable `main + 0x1B4078` | `main + 0x001140` | posts event `0x82EF0054` with argument 1, which quits the application |

At load the wrapper writes three patches into the guest's ROM copy, the only ten bytes over
`0x08000000..0x09000000` that differ from the cartridge, on v0 and 1.0.1 alike (block checksum and a
read through the Mystery Gift client, retail and emulated):

| address | cartridge | guest |
| --- | --- | --- |
| `0x081E1696` | THUMB `mov ip, r1` (`468c`) | `bkpt #0x52` (`be52`) |
| `0x081E187C` | ARM `ldr r3, [pc, #0x50]` (`e59f3050`) | `bkpt #0x52` (`e1200572`) |
| `0x081E1F90` | ARM `mov lr, r0, lsr #14` (`e1a0e720`) | `b 0x081E1FB8` (`ea000008`) |

`bkpt #0x52` is keyed by address: its hook holds two records `{u32 pc, u32 original insn, ..., u32
hits at +0x0C}` at `+0x120` and `+0x148`, and `main + 0x0546C0` matches the address and returns the
original instruction. At the `Sio32IDMain` patch (`0x081E1696`) it resolves guest `r0`
(`&gRfuSIO32Id`) and stores `0x8001` at `+0x0A`, the adapter id `AgbRFU_checkID` waits for
[librfu_sio32id.c]. A `bkpt #0x52` at any other address re-keys the second record (the `0x081E187C`
patch) to itself for the rest of the session.

#### The record resolver (`main + 0x03E850`)

The hook `main + 0x05499C` writes the `bkpt` itself into `insn`, then calls the virtual function at
`[[x0 - 0x60] + 0x98]` with `x0 - 0x60` as `this` (disassembly, `main + 0x549c4`-`0x549cc`); for the
Sloop component that resolves to `main + 0x056368`, which derives the record holder `[component +
0x40] -> [+0xA8] + 0x68` and tail-calls the resolver `main + 0x03E850` with it, `&insn`, the
`bkpt`'s address and the CPU (`0x3e850` has exactly one caller in the image, `0x56378`). The guest
`r0`'s top byte selects a region only later, inside the resolver's Sio32ID emulation below. The
resolver:

- matches record 1 (holder `+0x120`) through `main + 0x0546C0`: a match increments the hit count at
  `+0x0C` and copies the original at `+0x4` into `insn`, which the core then executes;
- on a record-1 match continues into the Sio32ID emulation: guest `r0` is folded through the
  region table, the folded offset is bounds-checked only against `offset < region size`
  (`+0x20`), and with the flag byte at holder `+0x108` set, `strh` stores `0x8001` at
  `backing + offset + 0xA` and `main + 0x2209C` writes the byte at `backing + offset + 1` into
  guest `r1` (`str w2, [regfile + 4 + 0x48]`). The `+0xA` is not covered by the bounds check, so
  an offset in the last `0xA` bytes of a region writes past the region's backing allocation, up
  to 11 bytes past its end; with the flag set and an out-of-range offset the backing pointer is
  null and the wrapper faults reading address `0x1`. With the flag clear the resolver returns
  without the write. Holder `+0x108` is `[+0xA8] + 0x170` (holder is `[+0xA8] + 0x68`), the same
  byte as the adapter power switch below: three live reads through `main + 0x03E850` during the
  console's own Mystery Gift search found it `0x1` every time, so `swi 0x40` alone arms the write path.
- on a record-1 mismatch re-keys record 2 (holder `+0x148`): `record2.pc := the bkpt address`,
  then matches it, so the core executes record 2's original, which is never updated: the stale
  `0x081E187C` original `e59f3050` (`ldr r3, [pc, #0x50]`), at any address the guest executes a
  `bkpt #0x52` from, in whatever CPU mode the guest is in. On the console's own Mystery Gift
  search, every dispatch re-keys through this path: record 2's hit count (holder `+0x154`)
  advanced about 20 per 0.33 s across three live reads, record 1's did not move, so the STWI
  driver's own `bkpt #0x52` at `0x081E187C`'s runtime IWRAM copy, not the `Sio32IDMain` ROM site,
  is what the search screen runs once a frame.
- on a record-2 match with the `+0x108` flag set, falls into `main + 0x03E954`: it folds the
  address stored at holder `+0x170`, reads a word at the folded address, and uses the word's top
  byte as a region selector and the word itself as the address to fold again, bounds-checked,
  decrementing a counter at holder `+0x42B8 + 0x7C`.

The guest controls the whole trigger: a payload that branches to `0x081E1696` (the patched site,
THUMB) with a chosen `r0` makes the wrapper write `0x8001` at `fold(r0) + 0xA` and set `r1` to the
byte at `fold(r0) + 1`; a payload that executes a `bkpt #0x52` anywhere else executes the stale
`e59f3050` there. Both are guest-relative; the `+0xA` write is the one path that leaves the
guest's regions: it can write `0x8001` two constant bytes up to 11 bytes past any region's
backing allocation, including the 16 MB ROM copy's.

#### What follows the ROM buffer: the Sloop component

The ROM objects' mask (`+0x34`) is `0x1ffffff` while the cartridge occupies `0x1000000` bytes, so
folds `0xFFFFF6..0xFFFFFF` pass the bounds check and put the write on the ten bytes immediately
behind the ROM buffer. The object there is the Sloop component
([The breakpoint hooks](#the-breakpoint-hooks)): its first word is the vtable pointer
`main + 0x1C3878`, `+8` `0x000004bf`, `+0xC` `0x0A828400`, `+0x18` and `+0x20` `main + 0x16EB83`,
`+0x28` a `0x655db` heap pointer, `+0x60` and `+0x88` further vtables (`main + 0x1C3948`,
`main + 0x1C3978`), `+0xE0` the CPU-bus object.

At the patched site the cartridge's own code parks its own `r0` (`ldr r0, [pc, #0x10]` loads
`0x0300744A`, its own `&gRfuSIO32Id`, IWRAM), so the game's own dispatches always fold to the
game's own struct: the wrapper's `0x8001` store is the adapter id reaching
`gRfuSIO32Id.lastId` (`RFU_ID = 0x8001` [librfu.h]), the value `AgbRFU_checkID` waits for. A
payload that branches to `0x081E1696` directly skips that load and parks its own `r0`, which is
what moves the store instead.

Instrumented on the strh itself (`main + 0x3E928`) and its continuation: with a direct branch
and `r0 = 0x08FFFFF6`, the store's `x8` is `backing + 0xFFFFF6` (`0x66209f9ff6`, the tail's
`ff` padding behind it), and the pre/post dumps read `0x66209fa000` as `78 98 6c 08 ...` before
the store and `01 80 6c 08 ...` after it: two stores about 90 ms apart (the payload's trigger,
then a second dispatch through the same site with the parked `r0`).

A write over the component's first two bytes plants the vtable pointer `0x086C8001`, and the
dispatcher `main + 0x1F820` then reads hook slot 19 (offset `+0x98`) from it: the eight bytes at
`main + 0x1C2099` are `f7 01 00 00 00 00 00 00`, so the wrapper's next virtual call executes at
guest PC `0x1F7`, an unmapped address no guest path otherwise reaches. On the emulator this
aborts the process (`Unhandled guest exception InstructionAbortLowerEl`); the same trigger with
the fold inside a region ends the session in the local fold's write only, no such dispatch. The
cartridge's own code at the site rules out the other candidate: `mov ip, r1` stores `ip` as a
value (`mov r0, ip; strh r0, [r4]`), it is never branched through.

The hook acts only while the byte at `[component + 0x40] -> [+0xA8] + 0x170` is set: the virtual
adapter's power switch. `swi 0x40` sets it, `swi 0x41` clears it (handler `main + 0x05706C` stores
`number == 0x40`; "unreferenced flag setters" in [sloopsvc.c:23]). `swi 0x41` from the Mystery Gift
menu stops the RFU frames: the game raises its link error and leaves LDN. The adapter stays off across
a soft reset, so the next wireless menu reports "L'adaptateur sans fil GBA n'est pas connecté". The
byte survives a soft reset; relaunching, or
`swi 0x40`, restores it. It is read per frame: `swi 0x41` then `swi 0x40` in one payload is harmless.

#### The dispatch chain and the plant's consumers

The image's relocations matter for reading the vtables: an NSO's vtable slots are unrelocated
addends in the file, the loader adds the image base. With the base applied (`main` at
`0x8506000`), the chain from a guest `bkpt #0x52` is:

- both decode paths (THUMB `main + 0x1EFE0`, ARM `main + 0x1B7B8`) call the dispatcher
  `main + 0x1F820` as `(CPU, bkpt address, immediate, &insn)`;
- the dispatcher takes hook = `[CPU + (imm & 0xff) * 8 + 0x170]` — for `bkpt #0x52` that is
  `component + 0x60`, a sub-object of the component (the component is the GBA CPU object: `+0x84`
  current pc, `+0x170` hook table, `+0x960` a second bus table, `+0xE0` the bus object) — reads
  the hook's own vtable (`main + 0x1C3948`) slot `+0x10`, and calls it as
  `f(hook, &insn, bkpt address, CPU)`. Slot `+0x10` is `main + 0x5499C` directly;
- `main + 0x5499C` writes `0xE1200572` into `insn`, then loads `[component]` and tail-calls the
  virtual at `[that pointer + 0x98]` with `(component, &insn, bkpt address, CPU)`: slot `+0x98`
  of `main + 0x1C3878` is `main + 0x56368`, which derives the record holder and reaches the
  resolver `main + 0x03E850`.

So a plant over the component's first ten bytes is consumed at slot `+0x98`, not `+0x10`; the
`+0x10` read happens on the hook sub-object, which the seam write cannot reach. The resolver's
write target itself is `buffer_data + fold + 0xA`, where the fold comes from the selected
region object's vtable slot `+0x48`: the ROM class's fold is `and w0, w1, [this + 0x34]`
(`main + 0x33B00`, the mask fold), the EWRAM class folds `r0 & 0x3ffff` (`main + 0x34B7C`) and
the IO class folds `r0 & 0xffffff` (`main + 0x1F7D8`), all bounds-checked afterwards against the
object's size at `+0x20`.

The bus dispatch for a guest memory access computes
`region = [bus + ((addr >> 21) & 0x7F8) + 0x50]` with `bus = [component + 0xE0]`, then calls the
region's vtable at slot `+0x18` (read 16), `+0x20` (read 32), `+0x28` (read 8), `+0x30`, `+0x38`
and `+0x40` (the three stores), `+0x48` and `+0x68` (special paths), the region object in `x0`.
210 call sites. The bus table is indexed by the address's top byte (16 entries), and window 4,
the GBA IO registers, maps to a 0x400-byte region object that sits immediately behind its own
backing allocation (bus `+0x14C0` is the backing, bus `+0x18C0` the object, the key-interrupt
sub-object embedded at object `+0x88`).

#### What a seam plant does: the measured hijacks

With `fold = size - 0xB` (in range) the write pair is `(size-1, size)`: the region's last byte
gets `0x01` and the first byte of the neighbouring allocation gets `0x80`. With
`fold = size - 0xA` the pair is `(size, size+1)`: `0x01 0x80` onto the neighbour's first two
bytes. One Mystery Gift session buys one chosen fold; the payload's branch into the patched site
does not return, and the body loops afterwards with the same parked `r0`, re-writing the same
pair.

Measured live on the emulated console:

| plant | consumed at | outcome |
| --- | --- | --- |
| component byte pair `01 80` (`0x086C8001`) | slot `+0x98` read at `main + 0x1C2099`, unaligned, unrelocated: `0x1f7` | the wrapper branches to an unmapped PC; the whole process dies (`InstructionAbortLowerEl`) |
| component byte 0 `0x80` (`0x086C9880`) | `main + 0x5492C`, the same method without the `-0x60` | it re-reads `[x0] + 0x98` on the still-planted component and recurses into itself; the thread stack exhausts and the process dies with a data abort (`InvalidMemoryRegionException`) |
| IO object byte 0 `0x80` (`0x086C8480`) | the bus's store slots `+0x38`/`+0x40`, whose planted targets are raw `0xffffffffffffe5e0` and `0` | the first IO store after the plant aborts the process within ~30 ms; the load targets (`main + 0x30EAC`, `main + 0x31114`, `main + 0x36D54`) never run |
| name-hash block byte 0 (`0x80`) | the block is an SDK binder/surface descriptor object (`android.gui.IGraphicBufferProducer` and friends are static strings in the SDK image), not a dispatched object | no guest-visible or emulator-visible reaction; the game runs to its own clean exit |

The plant that would survive and keep dispatching (`0x086C8080`, bytes `80 80`: every
`bkpt #0x52` then runs a pure counter getter, `main + 0x1F7F0`, and becomes a no-op) needs two
writes with no dispatch in between, and one session buys one write; both single-write states on
the way kill the process. Held via the debugger instead, the planted pointer stayed in place for
five minutes with the game running and the process alive: no restore mechanism rewrites a
wrapper object's header, so guest-reachable corruption of the wrapper's objects is durable.

#### The remaining syscalls

Handler addresses are `main + 0x05706C + entry * 4` from the jump table at `main + 0x17D7F6`. The last
column is what one issue from the Mystery Gift client with `sloop-svc` showed.

| swi | handler, callee | what it does | observed when issued once |
| --- | --- | --- | --- |
| 0x42 | mode switch `main + 0x0588A0` | `rfu_REQ_startSearchChild` [sloopsvc.c:49]; sets the network manager to mode 2 | ends the session with the link error; no access point opens |
| 0x43 | `main + 0x0570EC` -> `main + 0x058AD0` | `rfu_REQ_startConnectParent`, 16-bit PID in `r0` [sloopsvc.c:91]; the same mode switch | the buffer script answered, then "Erreur de connexion" at close |
| 0x44 | `main + 0x057100` -> `main + 0x058B0C` | `rfu_REQ_stopMode`, no arguments [sloopsvc.c:102] | after 0x43, no visible change |
| 0x45 | `main + 0x057110` -> `main + 0x058900` | `rfu_REQ_startSearchParent`, `rfu_STC_readParentCandidateList` with `&gRfuLinkStatus` [sloopsvc.c:67-75]; copies the wrapper's scan result through the region table into `struct RfuLinkStatus`, `findParentCount` [include/librfu.h] at offset 8 first | 220 zeroed bytes stayed zero (no parent search in a gift session) |
| 0x47 | `main + 0x05715C` -> `main + 0x058680` | `rfu_REQ_configGameData`, `r0` points to `struct RfuGameData` (16 bytes) and the username (8, `RFU_USER_NAME_LENGTH`) [sloopsvc.c:34-46; include/link_rfu.h:103-115,232]; copies all 24 to `component + 0x6050D8` and `activity` (bits 16-22 of the second 64-bit word) to `component + 0x605360` if changed | `activity` 0x30 landed byte for byte at both |
| 0x4B | `main + 0x0572C4` | no argument; bit 1 makes `RfuMain1` reseed the RNG from `gHostRfuGameData->compatibility.playerTrainerId`, bit 0 clear makes `SpawnGroupLeaderAndMembers` exit early for a leader [sloopsvc.c:132-145] | 0 |
| 0x4D | `main + 0x0571FC` | the bad-word filter, below | |
| 0x4F | `main + 0x057248` -> `main + 0x058B54` | builds `{u16 tag 0x4757; u32 value = r0}` on its stack; the tagged-property dispatcher `main + 0x4EBD0` and setter `main + 0x058BB4` store the value unvalidated at `component + 0x6052A0` | writing 3 and `0x7FFFFFFF`, each followed by 0x49 and 0x4A, changed nothing observable |
| 0x50 | getter `main + 0x058BA4` | reads the same 4-byte count back | |
| 0x51 | `main + 0x057270` -> `main + 0x0511BC` | reads `component + 0x3404` into an out-parameter and clears it; the out-parameter is always the dispatcher's own stack slot | |
| 0x61 | `main + 0x057340` -> `main + 0x058B2C` | `svc_SetActivity`; writes `r0` to `component + 0x605360` only for 0x41 to 0x48, the Union Room activity codes | 0x45: a breakpoint on the callee's `ret` (`main + 0x058B50`) read `w1` and the field as 0x45; normal close |

Answer-only syscalls issued with a pointer in `r0` return 0 (0x49, 0x4A, 0x4B, 0x51, 0x53) or 1
(0x50, 0x54), with `r1` to `r3` as passed.

`component + 0x6052A0` is 16 bytes: a 4-byte count, 4 unused, an 8-byte pointer into `main`. Freshly
launched: count 1, pointer `main + 0x1E8D20`, an array of pointers with two nulls after the one
populated slot. The dispatcher's mismatch path (`main + 0x50618`) checks a second tag, `0x59`, with a
third argument (`x2`) no known syscall supplies; what it reaches is unknown.

The tagged-property dispatcher `main + 0x4EBD0` walks a listener list on the component: entries of
`0xd0` at `component + 0x10`, the count at `+0x688`, the enabled byte at `+0x690`; for each entry
whose first word is 2 it calls the component vtable slot `+0x50` with the 8 bytes at `entry - 8`
and the tagged entry. The setter `main + 0x058BB4` is the `0x4757` listener; the `0x59` listener at
`main + 0x50618` writes its value at `component + 0x3324 + index * 4` with the index bounded 0..7 by
`main + 0x4DB0C`. The count the `0x4757` listener stores at `component + 0x6052A0` has no reader
but the getter `main + 0x058BA4` (`swi 0x50`): every other code site that forms the offset
`0x6052A0` or `0x6052A8` in the image writes it or the pointer beside it at init. The value the
`0x4F` caller supplies is inert.

The console's own Mystery Gift search issues `swi 0x47` before any buffer script, advertising
`activity` 0x15 (`ACTIVITY_WONDER_CARD` [include/constants/union_room.h:46]); a payload's call
overwrites it. A breakpoint at `main + 0x0586B4` reads `component + 0x605360` through `x8 + 0x280`.
The game-data object (vtable `main + 0x1C3B30`) is a sibling of the CPU/bus object `bkpt #0x52`'s hook
table resolves (vtable `main + 0x1C3878`, region table, syscalls 0x45, 0x48, 0x52, 0x55, 0x62); the
live addresses differ by `0x100000000`.

The per-candidate layout 0x45 writes is unsettled: the copy loop's byte count does not match
`sizeof(struct RfuTgtData)`; read it live before depending on it.

`component + 0x2770` (through `[component + 0xD0]`) is read by `swi 0x53` (a boolean) and by
`main + 0x0511CC` and `main + 0x0511F4`, which no syscall reaches. `main + 0x0511F4` compares it with
10 and, at or past it, atomically loads a flag at `component + 0x2790`; a set flag enters
`main + 0x057250`'s continuation, which tests a third argument for null. Its caller is unidentified.

The full audit, done statically and closed:

| swi | handler | what it does |
| --- | --- | --- |
| 0x40, 0x41 | `main + 0x05706C` | the adapter switch |
| 0x42 | `main + 0x0570DC` -> `main + 0x0588A0` | `rfu_REQ_startSearchChild` |
| 0x43 | `main + 0x0570EC` -> `main + 0x058AD0` | `rfu_REQ_startConnectParent`, `r0` = the PID |
| 0x44 | `main + 0x057100` -> `main + 0x058B0C` | `rfu_REQ_stopMode` |
| 0x45 | `main + 0x057110` | folds `r0` through the region table, copies up to 0x1000 bytes into the guest |
| 0x46 | jump-table entry `0x147` | the dispatcher's exit: a no-op |
| 0x47 | `main + 0x05715C` | `rfu_REQ_configGameData`, 24 bytes |
| 0x48, 0x56 | `main + 0x057084` | the flash-sector copy: sector = guest `r0`, source = `fold(guest r1)` through the same region table, bounds-checked, up to 4 KB |
| 0x49 | `main + 0x0571A8` -> `main + 0x0588D0` | a call on the `component + 0xD0` object, no guest argument |
| 0x4A | `main + 0x0571B8` -> `main + 0x058AB8` | the same shape, no guest argument |
| 0x4B | `main + 0x0572C4` | the RNG/leader flag |
| 0x4C | `main + 0x0571CC` | two internal calls (`main + 0x05D930` on `[component + 0xE8] + 0xA0`, then `main + 0x049D28` on a global), no guest data |
| 0x4D | `main + 0x0571FC` | the bad-word filter: reads up to 256 bytes at `fold(r0)` |
| 0x4E | jump-table entry `0x147` | a no-op |
| 0x4F, 0x50 | `main + 0x057248` | the `0x4757` tagged-property set/get |
| 0x51 | `main + 0x057270` | reads `component + 0x3404` |
| 0x52 | `main + 0x05728C` | loads `[bus vtable + (r1 >> 24) * 8 + 0x50]` (the index unbounded 0..255), folds, and discards the result: guest `r1` reads back 0 |
| 0x53 | `main + 0x0572D4` | `component + 0x2770` == 0 |
| 0x54 | `main + 0x0572EC` | `svc_CommsAllowedByParentalControls` |
| 0x55 | `main + 0x057304` | stores `r0` at `component + 0xE1BC`, reads one folded byte back |
| 0x57 | `main + 0x057330` | `MonsSelect` into the report at `component + 0x140` |
| 0x58 to 0x60 | jump-table entry `0x147` | no-ops |
| 0x61 | `main + 0x057340` | `svc_SetActivity` |
| 0x62 | `main + 0x057354` | the `CommsError` counter |

The answers come back through `main + 0x2209C`: guest `r0` = 1 when the number is above 0x2A,
guest `r1` = the handler's answer word. No handler returns a wrapper pointer to the guest (0x52's
is discarded), so the guest never learns a wrapper address through a syscall. The `0x59`
tagged-property listener (`main + 0x050618`), which would write a guest-chosen 32-bit value at
`component + 0x3324 + index * 4`, has no supplier: no syscall builds a `0x59` entry or the third
argument its index reads from `[x2]`, and the twelve calls of the tagged-property dispatcher all
build their entries from wrapper-internal fields. It is unreachable from the guest.

The `bkpt #0x52` component also owns the dispatcher (slot 21 of its vtable) and 2324 species names,
six languages each, hashed with djb2 (`main + 0x056540`, strings at `main + 0x1C4470`). The
dispatcher's frame, shared by every handler, is `0x40` bytes of saved registers plus `0x310`.

`bkpt #0xFF` from a payload closes the game: the wrapper files the session's play report, finalizes
LDN, stops audio, files a report built from the save, commits the save and exits. No answer reaches
the host. The reports as Ryujinx's `prepo` prints them:

| room | fields |
| --- | --- |
| `network`, one per link session | `Flavor` 66, `Trainer` (the 32-bit trainer id), `Zone` (the link activity, 21 `ACTIVITY_WONDER_CARD` for Mystery Gift), `Duration`, `Players`, `Slot`, `Rtt` |
| `game`, at exit | `Flavor`, `TimeStamp`, `Trainer`, `Gender`, `Duration`, `Badges` (a bitmask), `TotalBadges`, `HallOfFame`, `TotalHallOfFame`, `CompleteRegionalPokedex`, `RegionalPokedexCnt`, `RegionalPokedexCap`, `CompleteNationalPokedex`, `NationalPokedexCnt`, `NationalPokedexCap`, `Distributed`, `LinkExchange`, `LinkBattle`, `MonsNo1..5` and `MonsNoNLevel`, `Money`, `CommsError` |

### What the play reports are built from

The game report is parsed from the flash image. `main + 0x05A280` finds the newest slot by the sector
footers (signature `0x08012025`), copies its 14 sectors (0xE000 bytes) to `component + 0x140 + 0x70`,
and `main + 0x05A370` walks it with a per-game description table: badge flag bits, Hall of Fame and
Pokedex flags, money XORed with the save's key. `swi 0x57` fills `MonsSelect` (the starter, through
the internal-to-national table at `main + 0x17DA8C`); the printed JSON carries a fixed subset of the
table and omits `MonsSelect`. `swi 0x62` increments `component + 0xE1B0`, which becomes `CommsError`:
each call adds one to `CommsError` in the next report Ryujinx's `ServicePrepo ProcessPlayReport`
prints to the host log. The one reader of the SaveBlock2 pointer `swi 0x55` stores
at `component + 0xE1BC` is `main + 0x0577D8`, which tests `optionsButtonMode == 2` (L=A). The store
site is the handler itself, `main + 0x057308`: the dispatcher sets `x8 = component + 0xE1B0` at
`main + 0x057058`, and the handler stores the raw guest `r0` at `[x8 + 0xC]`. The reader folds the
stored word through the region table, bounds-checks it and reads one byte, `+0x13` into the
folded region: both are guest-relative and bounds-checked.

`main + 0x059CE4` picks the table from the game code; the application carries all five:

| game code | table | `Flavor` base |
| --- | --- | --- |
| `AXV?` | Ruby | 0x10 |
| `AXP?` | Sapphire | 0x20 |
| `BPE?` | Emerald | 0x30 |
| `BPR?` | FireRed | 0x40 |
| `BPG?` | LeafGreen | 0x50 |

`Flavor` adds the language's index in `JEFIDS`, so French FireRed reports `0x42` (66).

The table addresses the 14 sectors in id order, 0x1000 each: byte offset `o` is SaveBlock1 offset
`((o >> 12) - 1) * 0xF80 + (o & 0xFFF)`. A flag is a `(bit, byte)` pair; a bit above 7 means absent.
Decoded against the three decomps:

| field | Ruby / Sapphire | Emerald | FireRed / LeafGreen |
| --- | --- | --- | --- |
| badges, 8 flags from | byte `0x23A0` bit 7, `FLAG_BADGE01_GET` 0x807 | `0x23FC` bit 7, 0x867 | `0x2064` bit 0, 0x820 |
| `HallOfFame` | `0x23A0` bit 4, `FLAG_SYS_GAME_CLEAR` 0x804 | `0x23FC` bit 4, 0x864 | `0x2065` bit 4, 0x82C |
| `Money` | `0x1490` (SaveBlock1 + 0x490), no key | `0x1490`, XOR `0x00AC` (SaveBlock2 `encryptionKey`) | `0x1290` (+0x290), XOR `0x0F20` |
| party count, party | `0x1234`, `0x1238` | `0x1234`, `0x1238` | `0x1034`, `0x1038` |
| `TotalHallOfFame` | `0x25E8`, `GAME_STAT_ENTERED_HOF` | `0x2644` | `0x22A8` |
| `LinkExchange` | `0x2614`, `GAME_STAT_POKEMON_TRADES` | `0x2670` | `0x22D4` |
| `LinkBattle`, the sum of | `0x261C..0x2624`, link wins, losses, draws | `0x2678..0x2680` | `0x22DC..0x22E4` |
| regional Pokedex size | 202 | 202 | 151 |

Game stats are XORed with the money key where the game has one.

`Distributed` is four bits, each the flag that opens a ferry to a ticket-only island:

| bit | flag | Ruby / Sapphire | Emerald | FireRed / LeafGreen |
| --- | --- | --- | --- | --- |
| 0 | Navel Rock (Mystic Ticket) | absent | `0x240C` bit 0, `FLAG_ENABLE_SHIP_NAVEL_ROCK` 0x8E0 | `0x2069` bit 2, 0x84A |
| 1 | Birth Island (Aurora Ticket) | absent | absent | `0x2069` bit 3, 0x84B |
| 2 | Southern Island (Eon Ticket) | `0x23AA` bit 3, `FLAG_SYS_HAS_EON_TICKET` 0x853 | `0x2406` bit 3, `FLAG_ENABLE_SHIP_SOUTHERN_ISLAND` 0x8B3 | absent |
| 3 | Faraway Island (Old Sea Map) | absent | `0x240A` bit 6, `FLAG_ENABLE_SHIP_FARAWAY_ISLAND` 0x8D6 | absent |

In FireRed and LeafGreen both flags are set by the tickets' Mystery Event scripts
[mystery_event_msg.s:222,281] and by the Switch release's Hall of Fame grant
[post_battle_event_funcs.c:58]; a save carried over with its Hall of Fame already entered reports 0.

### Where the boundary stands

Every guest-reachable path into the wrapper is now audited. The guest can: run ARM code, call all
23 Sloop syscalls with chosen operands, write the adapter switch and the activity, compose flash
sectors from `fold(guest r1)`, store guest-chosen words at `component + 0xE1BC` and
`component + 0x6052A0` (both with guest-relative readers or none), and fire the resolver's
`0x8001` seam writes up to 11 bytes past any region's backing. What the guest cannot do: learn a
wrapper address (no handler returns one), call a wrapper function with a guest-chosen target
(the only plantable vtable pointers resolve to an abort, a self-recursion, or an inert counter
getter), or reach any wrapper state the region folds do not cover. The wrapper's own objects
accept durable corruption from guest code and nothing in the image restores them, so the
corruption is lasting, but every dispatched consumer of a corrupted object kills the process.
Escalation past the wrapper, from the guest, through this surface, is closed.

### The bad-word filter

`swi 0x4D`, handler `main + 0x0571FC`, resolves `r0` as a GBA address, requires 256 bytes behind it,
converts the ASCII string to UTF-16 and runs the platform's profanity check, rewriting the string in
place. `r1` non-zero selects a second mode the game never uses (`r1` = 1 masked the same way). The game
calls it through `svc_BadWordCheck`, converting the name to ASCII and back [sloopsvc.c:211]. The naming
screen saves the typed name only when it answers 0 [naming_screen.c:686].

| string sent | `r0` | string after |
| --- | --- | --- |
| `hello world` | 0 | `hello world` |
| `hello fuck` | 1 | `hello ` then four `0xA1` bytes |
| `POKELDN` | 0 | unchanged |
| `ASSASSIN` | 0 | unchanged |
| `NINTENDO` | 0 | unchanged |

## Repointing the console's outgoing message

`r0` is `&client->param`, so `struct MysteryGiftClient` [include/mystery_gift_client.h:71] sits at
fixed offsets from it:

| field | from `r0` |
| --- | --- |
| `client->sendBuffer` | 0x10 |
| `client->link.sendSize` | 0x34 |
| `client->link.sendBuffer` | 0x3C |

`MysteryGiftLink_InitSend` stores the pointer it is given [mystery_gift_link.c:59]; the CRC is taken at
send time over `link->sendBuffer` for `link->sendSize` bytes [:166]. A payload that runs between
InitSend and the send points the console's outgoing message at any address:

    CLI_RECV -> CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

In the other order InitSend overwrites the payload's patch.

Never dump a region that moves between the CRC frame and the send frame:

```c
case 0:  header.crc = CalcCRC16WithTable(link->sendBuffer, link->sendSize);   // one frame
case 1:  SendBlock(0, link->sendBuffer + blocksize, ...);                     // the next
case 2:  if (CalcCRC16WithTable(...) != link->sendCRC) LinkRfu_FatalError();  // the one after
```

[mystery_gift_link.c:155]. `gRngValue` (0x03004220) advances two steps a frame; a dump over it fails
the body CRC and the console reports "erreur de connexion". `buffer_script.build_memory_dump`
refuses any range overlapping it; dump around it, or use `rng-trace`, which returns it through the
4-byte channel. Any other volatile region has to be found the same way.

## The payloads

### `trainer-id-probe`

24 bytes, read only. The console already sent its `playerTrainerId` in the
`MysteryGiftLinkGameData` seconds earlier [mystery_gift.c:337], so the answer is known.

```arm
    ldrh    r3, [r1, #0x0A]         @ SaveBlock2.playerTrainerId[0..1]
    ldrh    ip, [r1, #0x0C]         @ SaveBlock2.playerTrainerId[2..3]
    orr     r3, r3, ip, lsl #16
    str     r3, [r0]                @ *param
    mov     r0, #1
    bx      lr
```

A match means it ran in ARM state with the decomp's arguments against the real `gSaveBlock2Ptr` and
returned 1; a different value means the arguments or offsets are wrong; no `Buffer script status:`
line means the client script shape is wrong or the call was never reached. A 7-character player name's
terminator overwrites `playerTrainerId[0]` in the game data [mystery_gift.c:364]; the host then
compares the top three bytes.

### `save-dump` and `memory-dump`

`memory-dump` takes an absolute address. `save-dump` reads either save block at any offset through r1
and r2, on any build. Up to 1024 bytes a run; `MGL_Receive` rejects more [mystery_gift_link.c:102].

    HOST --buffer-script save-dump --dump-block sav2 --dump-size 256 --version firered
    HOST --buffer-script memory-dump --dump-address 0x0201C000 --version firered

They reach `SaveBlock1.playerParty` at 0x0038, `money` at 0x0290 XORed with
`SaveBlock2.encryptionKey` at 0xF20, the bag, flags and vars, and IWRAM (`gRngValue`).

### `memory-dump-multi` and `memory-dump-scatter`

`MG_LINK_BUFFER_SIZE` caps a message, not a session. The client runs a script of commands from its
1024-byte receive buffer [mystery_gift_client.c:140], and the dump triple

    CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

repeats as often as it fits: 41 passes at 8 bytes a command with three fixed commands around the loop.
`mg_script.MAX_DUMP_BLOCKS` holds it at 32, since a session that dies loses every block. A 16 KB dump
took about 57 s on the ESP32 radio, blocks about 2.5 s apart.

`CLI_RUN_BUFFER_SCRIPT` re-copies the image every pass [:238], so the cursor lives in `client->param`:
each pass sends `base + index * 1024` and hands the next index on. A `param` without `0x5A5A0000` in the
high half is pass zero.

`memory-dump-scatter` indexes a table of bases instead:

    adr     r3, .Ltable
    ldr     r3, [r3, r1, lsl #2]    @ this block's own base
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer

`adr` is PC-relative. All 32 slots are filled, unused ones with the last address, so an extra pass
re-sends a held block instead of pointing the message at 0. Scattered blocks catch about four times
as many short function bodies per join as consecutive ones; for one set of 166 unread function bodies
over a megabyte:

| one join, 16 KB off the wire | bodies it catches |
|---|---|
| `memory-dump-multi`, sixteen consecutive blocks at the best base | 22 |
| `memory-dump-scatter`, the sixteen densest kilobytes | 83 |
| `memory-dump-scatter`, 32 blocks | 119 of 166 |

The readability guard checks each scatter block. The blocks arrive end to end in one file;
`--dump-scatter A,B,C` lets `script_read.dumps` place each at its base, tagged `<run>[0]`, `<run>[1]`,
... `--dump-blocks 1` returns `CLIENT_SCRIPT_DUMP_MEMORY` byte for byte.

### `anchors`

Writes eleven words into `client->sendBuffer` and widens `link->sendSize` to 44; no repoint is needed,
since `CLI_LOAD_TOSS_RESPONSE` already aimed `link->sendBuffer` there
[`MysteryGiftClient_InitSendWord`, mystery_gift_client.c:91].

| word | what | one boot |
| --- | --- | --- |
| 0 | `sub ip, pc, #8`: where the console put the code | 0x0201C000 |
| 1 | `lr`: the ROM address after the call [mystery_gift_client.c:276], bit 0 set because the caller is THUMB | 0x08148C75 |
| 2 | `sp` | 0x03007DB8 |
| 3 | `r0` = `&client->param`, so where `AllocZeroed` put the client in `gHeap` | 0x020020D4 |
| 4-5 | gSaveBlock2Ptr, gSaveBlock1Ptr | 0x02024598, 0x0202553C |
| 6-9 | the four AllocZeroed buffers: send, recv, script, msg | 0x02006510 .. 0x02007140 |
| 10 | `link->sendBuffer` as InitSend left it; must equal word 6 | 0x02006510 |

Words 4-5 change on every battle and load [load_save.c:75]; words 3 and 6-9 depend on heap state.
Word 1 anchors a decomp call site; word 10 equal to word 6 confirms the struct offsets. The buffers are 0x410 apart (1024 bytes plus a 16-byte block header), as `malloc.c`
describes. `buffer_script.describe_anchors` prints all eleven with its consistency checks.

### `save-write`

Copies its payload tail into the block, then points `link->sendBuffer` at the destination, so the
answer is what the save now holds. The session ends in `CLI_MSG_BUFFER_SUCCESS`, which reaches
`MG_STATE_SAVE_LOAD_GIFT` and commits the write to flash; it survives a reload from the title screen.

    HOST --buffer-script save-write --dump-block sav2 --dump-offset 0xB20 \
        --write-text "some text" --version firered

One payload carries 936 bytes. Longer data is written in pieces of 936, each its own payload, all
run in turn in the session; the client receives and runs them as its command list says
[mystery_gift_client.c:145, 236]. The answer is what the save holds under the last piece.

`build_save_write` refuses any span outside `filler_90[8]` at 0x090 and `filler_B20[0x400]` at 0xB20 in
`struct SaveBlock2` [global.h:345,357], which nothing in `src/` references. Four bytes past
`filler_B20` is `encryptionKey`, which money is XORed with. `--write-unsafe` overrides. Where the
block lands in flash rotates ([where an id lives](#where-an-id-lives-and-which-sector-carries-the-slots-counter)).

A `save-write` changes only the span it names: a 256-byte write changed 196 bytes of SaveBlock2, all
inside the span, and none of SaveBlock1. Nothing in the game writes `filler_B20`: a write there
persists across saves (ten generations measured), Mystery Events, Wonder Cards, soft resets and play
(256 bytes unchanged over a minute of play in which 1456 bytes of SaveBlock1 moved).

### `memory-scan`

Takes a 32-bit needle and a range. Each call scans its budget of 32-byte blocks, writes the cursor back
into its image and returns 0; the call reaching the end repoints `link->sendBuffer` at the result and
returns 1. The image opens with a branch over its parameters:

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

The budget protects the RFU link, which needs its frames. The inner loop is an `ldmia` of eight words
and eight chained `cmpne`s, about 14 instructions per eight words; the default 512 blocks is 7703
instructions a call under unicorn, roughly 60000 of a frame's 280896 cycles from EWRAM (16-bit bus,
~6 cycles an ARM fetch). The 16 MB cartridge is 1024 calls, about 17 s. `--scan-blocks` sets it; the
host reads ~60 child frames a second throughout.

`max_calls` defaults to what the range needs plus two; a watchdog stop answers with a short cursor
saying where to resume. The answer is always 528 bytes, so `len(dump) == buffer_dump_size` proves the
repoint. `found` counts every match, `hits` holds the first 64. `ldmia` sees only word-aligned
matches: a needle never word-aligned for the real stride returns zero.

### `table-scan`

Finds a table by shape: every maximal run of `runlen` words each exactly `delta` above its
predecessor, answered with the run's start and first value. `gSpecialVars`
[data/event_scripts.s:51] lists `gSpecialVar_0x8000` through `0x800B`, twelve consecutive `u16`s
[event_data.c:16], so its first twelve words step by 2 and the first value is `&gSpecialVar_0x8000`.

    HOST --buffer-script table-scan --table-delta 2 --table-runlen 12 \
        --table-start 0x08140000 --table-end 0x08400000 --version firered

Entry 12 is `gSpecialVar_Facing`, declared after `Result` and `LastTalked`, +6 from entry 11, so the run
is exactly twelve and a 13 finds nothing.

A shape test is ~7 instructions a word against ~1.75 for a value, so `TABLE_SCAN_DEFAULT_BLOCKS` is 192
blocks of 16 bytes, the same load as `memory-scan`'s 512 of 32. `run`, `runstart` and `expect` live at
0x22C..0x234 beside the cursor and are saved at every yield, since a run straddles `ldmia` and frame
boundaries. `expect` starts at 0, so a zero first word is credited to a run with an unwritten
`runstart`; `read_table_scan` discards hits outside the range.

The same shape finds a live `struct ScriptContext`: `InitScriptContext` stores a command table and its
end at +0x5C and +0x60 [include/script.h], 68 apart for a 17-entry table, so `--table-delta 0x44
--table-runlen 2` over EWRAM answers with the context's address and the table's. The context is zero
until a script has run, so the scan must follow a Mystery Event gift in the same boot.
`--table-delta 0x358` (214 entries) finds the field script context, whose `cmdTable` is the known
`gScriptCmdTable`.

### `rom-checksum`

Sums a range in up to 128 blocks, one sum per block, so the host names the blocks of the cartridge
that differ from its ROM image; a second run over one block with smaller blocks narrows it. The frame
loop, budget, watchdog and repointed send are `memory-scan`'s. Each block sums its words in ascending
order from 0:

    acc = w + ror(acc, 31)          one `add r0, rN, r0, ror #31` per word, mod 2^32

`rom_checksum_reference` computes the same from a ROM file. An XOR would cancel (a repeated word sums
to 0; equal changes 32 words apart cancel). A block past the end of the reference is named by its sum:
zero-filled, 0xFF-filled, open bus (each halfword its own address halved), a mirror, or CONTENT.

| offset | |
|---|---|
| 0x000 | `b .Lcode` |
| 0x004 | cursor: the start address, advanced by the payload |
| 0x008 | end |
| 0x00C | start |
| 0x010 | 32-byte chunks per call |
| 0x014 | max_calls, the watchdog |
| 0x018 | shift: log2 of the block size, 5 to 25 |
| 0x01C | the running sum of the block in progress, carried across calls |
| 0x020 | result: final cursor, calls used, sums stored, the shift echoed |
| 0x030 | result: 128 × u32 block sums |
| 0x230 | the code |

The answer is 528 bytes from 0x020. The builder refuses a start not aligned to the block, a range not
a whole number of blocks, more than 128 blocks, and a block that is not a power of two from 32 bytes.
13 instructions per eight words; 512 chunks is 6688 instructions a call. The default
0x08000000..0x09000000 in 128 KiB blocks is 1024 calls, about 17 s.

    HOST --buffer-script rom-checksum --version firered
    HOST --buffer-script rom-checksum --sum-start 0x08120000 --sum-end 0x08140000 \
        --sum-block 0x400 --version firered

The host logs each block's range, both sums and `SAME` or `DIFF`, then
`rom-checksum: N of M blocks differ from <image>`. The image is `config.REFERENCE_ROMS[game code]`, or
`--sum-reference` for every build. Blocks past the image are listed and not counted.

### `rng-trace`

Samples a word once a frame and calls a ROM function between the two reads of each sample
(`--trace-call 0` makes it a plain sampler).

    HOST --buffer-script rng-trace --trace-address 0x03004220 --trace-call 0x080486B1 \
        --trace-samples 96 --version firered

The call is `mov lr, pc; bx r2`: pc reads as the instruction after the `bx`, bit 0 clear, so the
callee returns to ARM state. On retail FireRed every sample of a `Random` trace follows the LCG (96
of 96 in the trace measured). Results are on [the RNG](frlg_rng.md).

### `string-gather`

Given the address of the first pointer, a stride and a count, copies each string pointed at, up to
and including the 0xFF terminator, into one answer, and reports where the next run resumes.

    HOST --buffer-script string-gather --gather-address 0x083E0D54 --gather-count 69 \
        --gather-stride 12 --version firered

`--gather-stride` is 12 for `struct EasyChatWordInfo` (`text` at 0), 4 for a `const u8 *` array. The
answer is 776 bytes: four header words, up to 760 bytes of strings. It never truncates: a string that
does not fit ends the run and `next` names it. `--gather-maxlen` (default 64) bounds a pointer that is
not a string.

### `create-mon`

```c
void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
               u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
```

Four arguments in `r0..r3`, four on the stack. `asm/create-mon.s` follows the console's own prologue:

    08041150  push {r4,r5,r6,r7,lr}    ; sp -= 20
    08041152  mov  r7, r8
    08041154  push {r7}                ; sp -= 4
    08041156  sub  sp, #28             ; sp -= 28, so entry sp is now sp + 52
    0804115c  ldr  r4, [sp, #52]       -> entry sp +  0   hasFixedPersonality  (masked to u8)
    0804115e  ldr  r7, [sp, #56]       -> entry sp +  4   fixedPersonality     (NOT masked: u32)
    08041160  ldr  r5, [sp, #60]       -> entry sp +  8   otIdType             (masked to u8)
    08041184  ldr  r0, [sp, #64]       -> entry sp + 12   fixedOtId            (u32)

The four go at `sp+0..sp+12` as whole words and the payload pops them itself. The mon is built inside
the payload's image, 32 bytes of guard before the code; `--create-mon-destination ADDR` copies it
onward and needs `--write-unsafe`.

    HOST --buffer-script create-mon \
        --create-mon-species 151 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADE0000 --version firered

`--create-mon-call` defaults to `CreateMon | 1` from `rom_map.py`; `0` calls nothing and answers the
zeroed buffer. The answer is 116 bytes (four header words, the 100-byte `struct Pokemon`), and
`*param` is the personality.

The substructs are encrypted with `personality ^ otId` and checksummed, so a valid checksum proves the
two words. `check_create_mon` checks species, level and IVs; `scratchpad/verify_create_mon.py`
predicts the thirteen derived fields: exp from `gExperienceTables[growthRate][level]`, friendship and
ability slot from `gSpeciesInfo`, moves and PP from the learnset, six stats from `CalculateMonStats`.
The nickname comes from `gSpeciesNames` [pokemon.c:1810], the cartridge's French table, and is read,
never predicted. Three fields measure the console:

| field | value | what it says |
| --- | --- | --- |
| `language` | 3 | `gGameLanguage` is LANGUAGE_FRENCH [global.h:22] |
| `metGame` | 4 | `gGameVersion` is VERSION_FIRE_RED [global.h:11] |
| `metLocation` | 91 | `GetCurrentRegionMapSectionId()` [overworld.c:1265], where the player was standing |

`buffer_script.shiny_personality(tid, sid)` gives a shiny `fixedPersonality`. Offline stubs for
`CreateMon`: `CREATE_MON_ARG_MODEL` writes the eight arguments into the destination,
`create_mon_copy_model(source)` copies 100 prepared bytes.

#### `--create-mon-append`

It writes `gPlayerParty`, not the save block's party:

```c
void SavePlayerParty(void)
{
    gSaveBlock1Ptr->playerPartyCount = gPlayerPartyCount;
    for (i = 0; i < PARTY_SIZE; i++)
        gSaveBlock1Ptr->playerParty[i] = gPlayerParty[i];
}
```

An append into the save block reports success and is lost at the next save [load_save.c:160,196]. It
writes at `slot == playerPartyCount` and raises the count, as a catch does; an occupied slot is
never touched and a full party writes nothing. A fifth answer word reports
`countBefore | slot << 8 | status << 16` (0 not asked, 1 appended, 2 party full, 3 dry run). An append
with an absolute `--create-mon-destination`, or with `--create-mon-call 0`, is refused.

    # dry run first: the same code with the two stores left out
    HOST --buffer-script create-mon --create-mon-append-dry-run \
        --create-mon-species 59 --create-mon-level 30 --version firered
    HOST --buffer-script create-mon --create-mon-append \
        --write-unsafe --create-mon-species 59 --create-mon-level 30 --version firered

The dry run reports the count, the target address and that slot's current 100 bytes, which catches a
`playerPartyCount` that disagrees with the party. An empty slot is not all zeros: `ZeroMonData` ends
with `SetMonData(mon, MON_DATA_MAIL, &MAIL_NONE)` [pokemon.c:1737], so offset 0x55 is `0xFF`
(`buffer_script.EMPTY_PARTY_SLOT`, `is_empty_party_slot`).

| | moves? | so |
| --- | --- | --- |
| `gSaveBlock1Ptr` | yes, a random 4-aligned offset re-rolled on every battle and load [`SetSaveBlocksPointers`, load_save.c:75] | take it from `r1`/`r2` every call |
| `gPlayerParty` | no, a link-time EWRAM global | an address is legitimate |

`gPlayerParty` is 0x02024280 and `gPlayerPartyCount` 0x02024025: the one 4-aligned window of an
EWRAM dump that decodes as checksummed `struct Pokemon`s.

### `call`

An address, up to eight argument words, the returned `r0`, and one address read either side of the
call.

    HOST --buffer-script call \
        --call-address 0x080486D1 --call-arg 0xC0DE --call-watch 0x03004220 --version firered

    0x000  b .Lcode
    0x004  function    THUMB pointer (bit 0 set), or 0 to call nothing
    0x008  argc        how many of the eight words below are meant
    0x00C  args[0..7]  r0, r1, r2, r3, then [sp+0], [sp+4], [sp+8], [sp+12]
    0x02C  watch       a word to read before and after the call, or 0
    0x030  result      calls used, function, argc, r0, *watch before, *watch after

`asm/call.s` always pushes the sixteen stack bytes; the callee never pops them. `SeedRng` returns
nothing (`gRngValue = seed` [random.c:15]), so the watch word is the evidence. Only call an address
already read as code. `tests/test_buffer_script.py` runs the console's own `SeedRng` bytes through the
payload under unicorn, and the eight-argument path with powers of two.

### `flash-write`

Composes a 4 KB sector in EWRAM and writes it to flash with [`swi 0x48`](#the-flash-sector-path),
bypassing the game's save code. The scratch is `gDecompressionBuffer + 0x400`, 0x400 above the
payload's own image.

    --flash-sector N            the sector, 0..31; 0..27 are the save bands and need --write-unsafe
    --flash-fill-base WORD      word[i] = base + i * step, the data pattern
    --flash-footer              compose a well-formed sector instead of a raw pattern
    --flash-id N                the sector id at +0xFF4
    --flash-derive              read the save globals and place it where that id actually lives
    --flash-position N          aim at band position N and derive the id from it instead
    --flash-counter-bias N      added to gSaveCounter for the footer

`--flash-footer` zeroes from the pattern's end to `+0xFF4` as the game does, computes the game's
checksum and lays down id, checksum, signature and counter. The status word is the physical sector
(high half) and the checksum (low half). `--flash-derive` reads `gLastWrittenSector` and
`gSaveCounter` at write time: both advance on every save, and a gift session that ends in a success
message saves [mystery_gift_menu.c:1379].

### `sloop-svc`

Up to eight Sloop syscalls in one session with host-chosen operands, answered through a result block.

    IP_HOST --buffer-script sloop-svc --svc-number 0x4d --svc-text "hello fuck" \
        --svc-data-in r0 --version firered

    0x000  b .Lcode
    0x004  flags       bit 0: r0 = &copy, bit 1: r1 = &copy
    0x008  r0..r3
    0x018  scratch     gDecompressionBuffer + 0x400
    0x01C  length      of the data, at most 256
    0x020  thunk       swi N ; bx lr (THUMB), or bkpt N ; bx lr with --svc-bkpt
    0x024  count       1..8
    0x028  numbers     eight bytes, one per call
    0x030  data

Before each call the payload copies the data afresh and writes the number into the thunk's low byte.
The result block: marker `0x53565331`, the count, marker `0x53565332`, the length, eight 20-byte
records (thunk word, `r0..r3` after), and the data as the last call left it. Value-only numbers (0x46,
0x49..0x4B, 0x4D, 0x4E, 0x50..0x54, 0x58..0x60) go as they are; 0x48, 0x56, 0x4C and 0x55 are refused;
the rest, and `--svc-bkpt`, need `--write-unsafe`; `--svc-bkpt` refuses `#0x52`.

### `install-resident`

Copies a resident THUMB hook to `0x0203FC00` and installs it in `gIntrTable[4]` in one session. It runs
every frame, through CONTINUER and the overworld, until a soft reset.

    IP_HOST --buffer-script install-resident --resident turbo \
        --resident-param extra=4 --resident-param field=1 --resident-param battle=1 \
        --resident-param overlay=0x03004220 --resident-param hold=0x100 \
        --resident-param budget=228 --write-unsafe --version firered

    0x000  b .Lcode
    0x004  dest          0x0203FC00
    0x008  length        of the hook, whole words
    0x00C  table         &gIntrTable[4], 0x03002730
    0x010  entry_off     the hook's entry inside it
    0x014  original_off  its p_original word
    0x018  blob_off      where the hook starts in this image, after the installer's code

The THUMB installer is 148 bytes, leaving 876 for a hook whose data (`p_frames`, `p_ring`, `p_state`)
must not overlap its code or pass `0x02040000`. REG_IME is cleared around the copy and table write. The first install keeps the replaced handler at `0x0203FBFC`; later installs
chain to that word and refuse with `0xBAD0BAD0` when it is empty. The answer is the handler found:
`0x0800071D` on a clean install. One hook is resident at a time; all share the 1 KB at `0x0203FC00`.

#### `turbo`

`asm/resident/turbo.s` runs `VBlankIntr`, then in an idle frame the overworld's callbacks `field` more
times, the battle's `battle` more times, and `RunTextPrinters` (`0x08002D51`) `extra` more times. A
pass runs only while `callback1`/`callback2` are exactly `CB1_Overworld` (`0x08059E49`) /
`CB2_Overworld` (`0x08059EC9`) or `BattleMainCB1` (`0x08015B6D`, stored by the battle init at
`0x08013FDE`) / `BattleMainCB2` (`0x08014889`), rechecked between the two calls. `newKeys` and
`newAndRepeatedKeys` are cleared first so a press is handled once.

No pass runs while `gPaletteFade.active` (`0x02037AB4`) is set: a hardware fade ends when
`UpdatePaletteFade` sets the one-bit `hardwareFadeFinishing` and the next V-blank sees it
[palette.c:701, 743]; a second update in one frame wraps the bit to 0, and `CompleteWhenChoseItem`
then waits forever after the bag closes in battle. Two more gates:

- `gMain.intrCheck` (`0x030022EC`) bit 0 clear, read before `VBlankIntr`: the main loop is parked in
  `WaitForVBlank` [main.c:462]. Set is a lag frame, left alone.
- No active printer in `sTextPrinters` (`0x02020034`, 32 of 0x24 bytes) at its origin (`currentX ==
  x`, `currentY == y`): a field message adds its printer before its box is drawn [field_message_box.c:44],
  and a pass before the box is drawn prints into a window the box then clears.

Measured on an emulator: 60 frames a second, 97% idle, text at five glyphs a frame; `field=1` doubles
the overworld, `battle=1` a battle and its menus.

`hold=MASK` runs the callback passes only while `gMain.heldKeys` (`gMain + 0x2C`) holds every button
in the mask; text extras run regardless. With `hold=0x100` (R) the hook stores 1 every frame into
`gHelpSystemToggleWithRButtonDisabled` (`0x0203F171`, the literal at `0x0813F6FC` in
`RunHelpSystemCallback`, `0x0813F65C`), so R does not open the Help System [help_system_util.c:50]; L
still does.

`budget=LINES` bounds passes by time. The Switch emulator advances `REG_VCOUNT` (0 to 227, V-blank
from 160) while a frame's code runs; a pass starts only if the lines since V-blank plus twice the last
pass's cost fit in `LINES`. The last cost is at counter `+0x0C`, held-back passes counted at `+0x10`;
each held-back pass shrinks the kept cost by an eighth.

Measured on an emulator:

| setting, R held | extra passes a frame | note |
|---|---|---|
| `field=2 battle=2` | 1.70 to 1.90 of 2 | about 2.9x, no visible lag |
| `field=3 battle=3` | at most 2.38 of 3 | about a quarter of frames lag; visible stutter |
| `field=3 battle=3 budget=228` | up to 2.48 | smooth; a pass costs 36 to 42 lines walking, 100 to 108 in battle |

`overlay=ADDRESS` draws the word at `ADDRESS` as eight hex digits in the overworld's top-right corner
(`0x03004220` is `gRngValue`). The entries go into `gMain.oamBuffer[120..127]` (`0x030026C8`), the two
colours into OBJ palette 15 of `gPlttBufferFaded` (`0x020375F4`) and `gPlttBufferUnfaded`
(`0x020371F4`), before `VBlankIntr`'s `LoadOam` and `TransferPlttBuffer` (after it, the top rows lag
a frame). A 128-byte 1bpp font (sixteen 3x5 digits, pixels 2
to 4 of rows 1 to 5, `asm/resident/overlay.inc`) is expanded into OBJ tiles 1008 to 1023 when two
sentinel words differ. The overlay overwrites whatever the game keeps in palette 15 and those tiles.

`ring=ADDRESS` (140 bytes; `0x0203FF74` ends at the top of EWRAM) keeps `gRngValue` as `VBlankIntr`
finds it, one word a frame for 32 frames, and freezes when `watch` (`gEnemyParty[0]`'s personality,
`0x02024028`) changes. A grass encounter's personality follows from every kept seed. Measured while
walking in grass on an emulator: two `Random` calls a frame, and from the previous frame's seed the
nature roll is the fifth call (`VBlankIntr`'s [main.c:412], the frame's own, slot, level, nature).

#### `shiny`, `ivs`, `noencounter`

`shiny` (`asm/resident/shiny.s`) counts down to the next shiny wild roll. `VBlankIntr` calls `Random`
once a frame [main.c:412]; a wild Pokemon rolls `Random() % 25` for its nature, then draws
`Random() | Random() << 16` until the nature matches [wild_encounter.c:233, pokemon.c:1864];
`method=1` takes the first pair (a scripted `CreateMon`). Shiny is `TID ^ SID ^ high ^ low < 8`, TID
and SID from `gSaveBlock2Ptr` (`0x0300422C`) `+0x0A`. The hook follows `gRngValue` frame to frame (up
to 64 steps, else it restarts), searches `search` candidates per idle frame, and shows the target's
nature and `target - current - offset` in decimal (`offset=4`, the grass case), or `FF` and the search
distance. While `slow` (R) is held it waits `slow_frames` more V-blanks a frame: `IntrMain` leaves
VCount enabled in a handler [crt0.s], so `m4aSoundVSync` runs, and the hook calls `m4aSoundMain`
(`0x081DF53D`, `gPcmDmaCounter` `0x03002F68` from `gSoundInfo` `0x03005F80`) per waited V-blank and
clears it in `REG_IF`. State is 36 bytes at `0x0203FF80`.

`ivs` (`asm/resident/ivs.s`) shows the lead's IVs on two rows (`OVERLAY_TWO_ROWS`, the second in
`gMain.oamBuffer[112..117]` at y 10): HP, Attack, Defense, Speed, then Sp. Atk, Sp. Def and
`personality % 25`. `GetMonData(mon, MON_DATA_IVS)` (66, `0x080432E5`) returns six five-bit IVs, HP
lowest [pokemon.c:3250]; `GetBoxMonData` decrypts in place and re-encrypts [pokemon.c:2992, 3327], so
the call is made only in an idle overworld frame.

`noencounter` (`asm/resident/noencounter.s`) stores 1 every frame into `sWildEncountersDisabled`
(`0x020386D8`), which `StandardWildEncounter` (`0x08086528`) tests first [wild_encounter.c:360];
`DisableWildEncounters` (`0x08085FAC`) is its only other writer. Grass, water and roamer encounters
stop; fishing and Sweet Scent take their own paths.

#### `noclip`

`noclip` (`asm/resident/noclip.s`, 304 bytes) lets the player walk through walls while every button
in `hold` (default `0x100`, R) is held. On each idle overworld frame (`gMain.intrCheck` bit 0 clear,
`callback2` `CB2_Overworld`) it rewrites the four blocks around the player's `currentCoords` in the
map grid, `VMap.map` (`gBackupMapData`, `0x02031DF8`), to collision 0 and elevation 15, keeping the
metatile id. `VMap` is `{s32 Xsize, s32 Ysize, u16 *map}` at `0x03004260` (French) or `0x03004310`
(English), the literal in `MapGridGetCollisionAt`. A block is `metatile | collision << 10 |
elevation << 12` [global.fieldmap.h:7]; `GetCollisionAtCoords` blocks on a collision bit, then on
`IsElevationMismatchAt`, which passes elevation 15, and `ObjectEventUpdateElevation` leaves the
player's own elevation unchanged on a 15 tile [event_object_movement.c:4830, 8346, 8400].

The next idle frame puts each block back, only while `gMapHeader.mapLayout` (`0x02036DF8`) is the
layout it changed and the block still has its metatile id with elevation 15 and collision 0: a warp
or a metatile the game rewrote keeps the new block. A block equal to `MAPGRID_UNDEFINED` (`0x3FF`)
stays, or the player would leave the map. Object events still block (`DoesObjectCollideWithObjectAt`),
ledges still jump, and a wandering object event beside the player can step onto an opened block. Held
R would open the Help System, so the hook stores 1 every frame into `0x0203F171` (see `turbo`).
State is 24 bytes at `0x0203FF80`: the layout, a count and four `{u16 index, u16 block}`.

`tests/test_noclip.py` installs it through each cartridge's own client and reads the result with the
cartridge's own `MapGridGetCollisionAt` and `MapGridGetElevationAt`.
Measured on mGBA with the French cartridge in Pallet Town: walking south, the player stops at the
fence without R and passes six tiles through it with R held; an object event still stops it.

#### `follower`

`asm/resident/follower.s` walks the lead Pokemon one tile behind the player as a real object event,
moved by the game's own movement actions, so the game draws its steps, runs, ledge jumps (arc, shadow,
landing dust), door fades and sprite priority. The design follows GB-Link's `cards/follow.s`
(GPL-3.0). It is 984 bytes, past one `install-resident` session, so it is installed from the save
([A resident hook kept in the save](#a-resident-hook-kept-in-the-save)).

On each idle overworld frame (`gMain.intrCheck` bit 0 clear, `callback2` `CB2_Overworld`), after
`VBlankIntr`:

| step | what the hook does |
| --- | --- |
| find it | the active object event of local id `0xF0`, a local id no map uses; none after a map load |
| spawn | `SpawnSpecialObjectEventParameterized(gfx, MOVEMENT_TYPE_NONE, 0xF0, x, y, elevation)` on the player's tile, hidden until the player's first step |
| every frame | its current elevation set to 14, which no tile has: the player walks back through it and nothing talks to it [event_object_movement.c:4899]; `fixedPriority` set while the field is locked, so a load keeps that elevation |
| a player step | the tile the player left becomes its target; one tile away it gets the player's own action family (a run becomes `WALK_FAST`), off line it is moved straight there with `MoveObjectEventToMapCoords` |
| a ledge | the player's `JUMP_2` moves its coordinates twice: the first takes the follower to the edge, the second leaves it there; on the player's next step it does `JUMP_2` itself, two tiles; two tiles in a line with no ledge pending, it closes up with `WALK_FASTER` (0x35), one tile at a time |
| a menu | `sLockFieldControls` (`0x0300109C`) set with `sGlobalScriptContextStatus` (`0x03000FA8`) at `CONTEXT_SHUTDOWN`: `RemoveObjectEvent`, so a save never holds it; it is spawned again after |
| bike, surf, dive | hidden on the player's tile |
| a new lead | removed and spawned again |
| a bump | the player bumping into it on an elevation-0 tile puts it on the player's tile |

| lead | object |
| --- | --- |
| one of the 42 species with an overworld sprite (`OBJ_EVENT_GFX_SNORLAX` 109 to `DEOXYS_N`; Deoxys in its version's forme, the builder's `deoxys=`) | its own graphics id |
| any other species, an egg, Unown by letter | Snorlax's 32x32 frame (109, `sAnimTable_Standard`); its sprite's `images` points at nine `SpriteFrameImage` at `0x0203FBB4` (standing 0..2: icon frame 0, walking 3..8: frame 1, 0x200 bytes each, from `GetMonIconPtr`) on OBJ palette 15 |

The icon's palette goes to `gPlttBufferUnfaded` OBJ palette 15 (`0x020375D4`) each idle frame, and to
`gPlttBufferFaded` (`0x020379D4`) only when the blend `y` (`gPaletteFade + 4`, bits 6..10) is 0. A door
fade-out runs `BeginNormalPaletteFade` to `y` 16 and then clears `active` with the screen still black
[field_weather.c:740, palette.c]; measured on mGBA walking into a door, `active` stays set 21 frames,
then `y` 16 with `active` clear for four frames before `callback2` leaves the overworld.

A in the field while the tile in front of the player is the follower's and the field is not locked
(the game's own A, a script or a menu take the frame first): `gSelectedObjectEvent` is set to it and
`ScriptContext_SetupScript` runs, with the species written in (none for `SPECIES_EGG`, 412, which has
no cry):

    6A                lock
    A1 SPEC 0000      playmoncry SPECIES, CRY_MODE_NORMAL
    5A                faceplayer
    4F F000 PTR       applymovement 0xF0: 66 FE (MOVEMENT_ACTION_EMOTE_SMILE, step_end)
    51 0000           waitmovement 0
    C5                waitmoncry
    7F 00 0000        bufferpartymonnick STR_VAR_1, 0
    67 PTR            message: "{STR_VAR_1} saute\nde joie !" (French), "{STR_VAR_1} jumps\nfor joy!" (English)
    66 6D 6C 02       waitmessage, waitbuttonpress, release, end

State, 17 bytes at `0x0203FFDC` (`state=`): `+0` its object event or `0xFF`, `+1` a step pending, `+2`
showing an icon, `+3` the movement family, `+4` the player's coordinates last seen, `+8` its target,
`+12` the lead's species, `+14` the species it was spawned for, `+16` a ledge pending. The icon's frame
table is 72 bytes at `0x0203FBB4` (`images=`), below the handler the installer keeps at `0x0203FBFC`.

| cartridge | `SpawnSpecialObjectEventParameterized` | `ObjectEventSetHeldMovement` | `ObjectEventClearHeldMovement` | `MoveObjectEventToMapCoords` | `RemoveObjectEvent` | `ScriptContext_SetupScript` | `gSelectedObjectEvent` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BPRF, BPGF | `0x08062130` | `0x080675A4` | `0x08067634` | `0x08063024` | `0x08061DB4` | `0x0806D3D4` | `0x03004294` |
| BPRE, BPGE | `0x08061FD4` | `0x08067448` | `0x080674D8` | `0x08062EC8` | `0x08061C58` | `0x0806D270` | `0x03004344` |

| cartridge | `gMonIconPaletteIndices` | `gMonIconPalettes` | `GetMonIconPtr` |
| --- | --- | --- | --- |
| BPRF | `0x083CBEE8` | `0x083CB7A8` | `0x0809AA74` |
| BPGF | `0x083CBD24` | `0x083CB5E4` | `0x0809AA48` |
| BPRE | `0x083D197C` | `0x083D123C` | `0x0809A7B8` |
| BPGE | `0x083D17B8` | `0x083D1078` | `0x0809A78C` |

English values are `pokefirered_switch.elf`'s; the French ones are the same bytes found in each image.
`tests/test_follower.py` runs the hook as `install-kept` installs it on each image, with the object
functions stood in for: the spawn, a walk, the icon frames and palette, the ledge wait and the single
jump, the talk script, the removal under a menu.

`AddSpritesToOamBuffer` fills unused OAM entries with `gDummyOamData` only up to `gOamLimit`
[sprite.c:487], which `ResetSpriteData` sets to 64 [sprite.c:297] and which reads 64 in the overworld
(`0x02021B44`): an entry above 64 written by a hook stays on screen until a screen resets its sprites.

#### Verified

| hook | retail French FireRed, ESP32 radio (each install answers `0x0800071D`) | emulator |
| --- | --- | --- |
| `turbo` `extra=4 field=3 battle=3 hold=0x100 budget=228` | holding R fast-forwards | |
| `overlay` | eight digits drawn, changing every frame | drawn during the recap after CONTINUER |
| `shiny` | counts down in grass; R slows it | the followed seed matches `gRngValue`; the Python model agrees on the shiny |
| `ivs` | the lead's IV word and `personality % 25` match a `save-dump` of `SaveBlock1 + 0x34` | matches `gPlayerParty` (`0x02024280`) |
| `noencounter` | no wild encounter while walking in grass | none; encounters return after a soft reset |
| `turbo-lite+noclip+noencounter`, `turbo-lite.field=2 battle=2 hold=0x2`, `noclip.hold=0x100` | one session answered `0x0800071D`; B held fast-forwards, R held walks through walls, no grass encounters, both buttons at once walk fast through walls | |
| `follower` | walks a tile behind, waits at a ledge's edge and jumps it after the player steps off the landing tile, with the game's shadow and dust; running and running over a ledge without flicker; A facing it: cry, smile, line; the start menu and doors; one session writes it to the save and installs it | the same on mGBA with Chansey's sprite and Blastoise's icon |

Unresolved: on the emulator the overlay drew during the recap after CONTINUER but not in interactive
play, while `field` still sped the game.

Every hook runs on LeafGreen with one address changed: `m4aSoundMain` is `0x081DF518` (the `bl` in its
`VBlankIntr` at `0x08000772`); every other constant maps identically through FireRed's own references.
`follower` also reads ROM tables and functions that move, listed in its section.
The builders take `version=`, the host `--version leafgreen`. Verified on an emulated LeafGreen:
turbo and `shiny`, music intact.

### Several hooks at once

Every hook calls the handler it replaced as a function (`bl` to a `bx r3` on `p_original`) and
returns through its own pushed `lr`, so a hook's `p_original` may name another hook. `--resident
turbo-lite+noclip+noencounter` lays the hooks out back to back from `0x0203FC00`, writes each one's
`p_original` as the next one's entry (Thumb bit set), and hands the installers one blob whose entry
is the first hook's and whose `p_original` is the last one's. `install-resident`, `install-kept` and
MOM's loader are unchanged. A setting names its hook: `--resident-param turbo-lite.hold=2`.

| rule | why |
|---|---|
| order turbo, noclip, shiny, ivs, noencounter | turbo's callback passes run after the other hooks have finished with the frame |
| each hook's data is placed in `0x0203FBB4..0x0203FBFC`, then above the code | the defaults overlap: `shiny`, `ivs` and `noclip` all keep state at `0x0203FF80` |
| at most one of `shiny`, `ivs` and turbo's `overlay` | each draws in `gMain.oamBuffer[120..127]` and OBJ palette 15 |
| `follower` runs alone | 984 bytes: with any other hook it passes the 1004 the save holds |
| the code fits `0x0203FC00..0x02040000` | 1024 bytes; past 876 the set goes through the save, past 1004 nowhere |

`turbo-lite` (`asm/resident/turbo-lite.s`) is `turbo.s` assembled with `TURBO_LITE` set: the same
passes, gates, hold and budget with no overlay and no RNG history, 356 bytes against 696. Every turbo
frame test runs on it (`tests/test_turbo_lite.py`); a frame through a chain runs each hook and
`VBlankIntr` once (`tests/test_resident_chain.py`).

### `install-kept`

`asm/install-kept.s`, 192 bytes, installs the hook kept in `filler_B20` as `install-resident`
installs its own: it reads `gSaveBlock2Ptr` (the block moves on every load), checks the magic, a length
that leaves the checksum inside `filler_B20`, and the sum, then clears REG_IME, keeps the game's
handler at `0x0203FBFC`, copies the hook, writes its `p_original` and points `gIntrTable[4]` at it.
The answer is the handler found in the table, or `0xBAD0BAD0` when nothing was installed. The ARM
entry at +0 is the buffer script's; MOM's RAM script runs the THUMB entry at +8, which points the
answer at a word in the image. The last two words are patched per cartridge: `&gSaveBlock2Ptr` and
`&gIntrTable[4]`.

    IP_HOST --buffer-script install-kept --version firered

### A resident hook kept in the save

Any resident hook can live in `filler_B20` and be installed again by talking to MOM after a boot, with
no link and no host. Two gift sessions set it up:

    IP_HOST --buffer-script save-write --resident follower --version firered
    IP_HOST --gift resident-save --version firered

The first writes this blob at `SaveBlock2 + 0xB20` and installs the hook from it in the same session:

    +0x00  magic     0x32524B50, "PKR2"
    +0x04  length    the hook's bytes, whole words
    +0x08  dest      0x0203FC00
    +0x0C  entry     u16 offset of the hook's entry
    +0x0E  original  u16 offset of its p_original word
    +0x10  the hook
    +len   checksum  the sum of every word before it

A blob past one `save-write` (936 bytes) is written by two. The session runs every write and then
[`install-kept`](#install-kept), each a payload of its own: the client receives and runs buffer scripts
in turn as its command list says [mystery_gift_client.c:145, 236], and only the last answer travels
back.

    client  RECV RUN  RECV RUN  RECV RUN LOAD_TOSS_RESPONSE SEND_LOADED  RECV COPY_RECV
    host    script    write 1   write 2  install-kept   <- the handler found

The session ends in `CLI_MSG_BUFFER_SUCCESS`, which saves, so `filler_B20` reaches flash.

The second binds a RAM script to MOM that stages the 36-byte [ram-jump trampoline](#a-payload-larger-than-a-script-body)
and branches into `install-kept`'s THUMB entry, carried in the script body at one byte each (428
bytes of 995). Talking to MOM installs the hook; a second visit chains to the kept handler, and a soft
reset removes the hook until MOM is talked to again.

| hook | blob | `save-write` payloads |
| --- | --- | --- |
| `noencounter` | 48 | 1 |
| `ivs` | 520 | 1 |
| `turbo-lite` | 376 | 1 |
| `turbo` | 716 | 1 |
| `shiny` | 888 | 1 |
| `follower` | 1004 | 2 |

`tests/test_resident_save.py` runs the whole session between the host and the emulated client, and
MOM's body script on a booted console: a flipped byte, a missing second write, a length past
`filler_B20` install nothing. A retail FireRed installs the follower from its `PKR2` blob.

A new Wonder Card undoes the binding: `SaveWonderCard` calls `ClearSavedWonderCardAndRelated`, which
calls `ClearRamScript` [mystery_gift.c:172, 160]. `filler_B20` stays as written.

### `call-chain`

Up to sixteen steps in order in one frame, one answer word per step.

    HOST --buffer-script call-chain \
        --chain-step call:FlagGet,0x828 \
        --chain-step call:FlagSet,0x828 \
        --chain-step call:FlagGet,0x828 --version firered

A step is 24 bytes (op, target, four arguments), written `OP:TARGET[,ARG]...` with ops `call`,
`read32/16/8`, `write32/16/8`. A call target may be a `rom_map.CALLABLE` name (never a decomp address).

A step can take its target or first argument from the previous result, `prev`:

    --chain-step call:GetVarPointer,0x4024      prev = the address the GAME computed
    --chain-step read16+keep:prev               the value before, prev untouched
    --chain-step write16:prev,7                 the store, read back by the payload itself
    --chain-step read16:prev                    the value after

`ScrCmd_setvar` writes through `GetVarPointer`'s return [scrcmd.c:472]; no ScrCmd worker is a `VarSet`
([The ROM map](frlg_rom_map.md)). A write never becomes `prev`; a read does unless it carries `+keep`.
Every write reads itself back into the answer.

    0x000  b .Lcode
    0x004  count       how many steps are meant, 0..16
    0x010  steps[16]   {op, target, a0, a1, a2, a3}, 24 bytes each
    0x190  result      calls, count, steps executed, the op word that stopped it
    0x1A0  values[16]  one word per step, in order

An unknown opcode stops the run and is named in the answer; the ARM caps the step count too. The
builder refuses an empty chain, more than sixteen steps, a call to an ARM pointer or outside the
cartridge, a call target from `prev` (a wrong one hangs the menu), an unaligned or unreachable read,
more than four arguments, and any write without `--write-unsafe` (the console commits its save
afterwards).

    call GetVarPointer(0x4024)   -> 0x020265B4
    read16 [prev] keep           -> 0
    write16 [prev] = 3           -> 3        the store, read back by the payload
    read16 [prev]                -> 3
    call VarGet(0x4024)          -> 3        the game's own reader, same frame

The variable still reads 3 after `gSaveBlock1Ptr` changes base. Money is `*moneyPtr ^
gSaveBlock2Ptr->encryptionKey` [money.c:14]:

    read32 [0x03004228]              -> 0x02025554     gSaveBlock1Ptr
    read32 [prev + 0x290] keep       -> 0x5A5A198C     the ciphertext, before
    call GetMoney(prev + 0x290) keep -> 0x00000BB8     3000, the plaintext
    call AddMoney(prev + 0x290, 1234) keep
    call GetMoney(prev + 0x290) keep -> 0x0000108A     4234, exactly +1234
    read32 [prev + 0x290]            -> 0x5A5A02BE     the ciphertext, after

(Illustrative values.) Both XOR pairs give the key, here 0x5A5A1234, the word at SaveBlock2 + 0xF20
(`rom_map.SAV1_MONEY`, `SAV2_ENCRYPTION_KEY`). A special reads its operands from the special vars:
with `gSpecialVar_Result` set to `GET_CARD_BATTLES_WON`, special 390 answers the card's `battlesWon`,
the value `SaveBlock1 + 0x3434` holds in the same frame.

Never call a warp or message worker from a buffer script: the Mystery Gift menu has no overworld. They
belong to a [field stub](frlg_rng.md#the-payload-in-the-script-body).

## Writing a sector the game will load

Everything below was measured on the emulator.

### The checksum covers the id's chunk

`CalculateChecksum(data, size)` sums `size` bytes as little-endian u32 words and folds
`(sum >> 16) + sum` to u16 [decomp:src/save.c]. `size` is the id's own chunk from `sSaveSlotLayout`,
14 entries of {u16 offset, u16 size} at `0x083F58C4` on the French cartridge:

| id | size | id | size |
| --- | --- | --- | --- |
| 0 | 3876 | 4 | 3816 |
| 1-3 | 3968 | 5-12 | 3968 |
| 13 | 2000 | | |

`HandleWriteSector` zeroes the whole sector buffer before copying the chunk [save.c:181-183], so a
game-written sector is zero past its chunk and summing all 3968 bytes gives the same checksum; a
composed sector with data past its chunk is rejected. Fill only the chunk. When the id is decided on the console, fill at most 2000
bytes, the smallest chunk: one checksum is then valid for any id.

### Where an id lives, and which sector carries the slot's counter

A slot is 14 sectors; the game alternates between two slots and rotates ids [decomp:src/save.c:174]:

    physical = ((gLastWrittenSector + id) % 14) + 14 * (gSaveCounter % 2)

`gLastWrittenSector` advances by one per full save, wrapping at 14 [:147]. It coincides with the
counter in ordinary play but separates when a write is marked damaged: the game restores it from
`gLastKnownGoodSector` [save.c:159], and `Save_ResetSaveCounters` [:104] resets it independently.
`gLastKnownGoodSector` and `gLastSaveCounter` take the live pair before it advances, so they describe
the previous generation exactly. Find a sector by parsing footers, never by a fixed file offset.

`GetSaveValidStatus` counts a sector when its signature is `0x08012025` and its checksum over
`locations[id].size` matches, the id taken from its own footer:

- a slot is OK only when all 14 ids are present and valid; counters within a slot need not agree;
- `slotNsaveCounter` is assigned on every valid sector in physical order, so it holds the last valid
  sector's counter.

So a complete band whose last sector carries a higher counter wins over a band whose sectors all
carry a lower one (thirteen at 129 and one at 131 beat fourteen at 130).

| address | symbol | width |
| --- | --- | --- |
| `0x030045A0` | `gLastWrittenSector` | u16 |
| `0x030045A4` | `gLastSaveCounter` | u32 |
| `0x030045A8` | `gLastKnownGoodSector` | u16 |
| `0x030045AC` | `gDamagedSaveSectors` | u32 |
| `0x030045B0` | `gSaveCounter` | u32 |

IWRAM, French build. After a load `gLastWrittenSector` describes the adopted slot.

### The band the session's own save will not write

A full save assigns the previous pair, advances `gLastWrittenSector` and `gSaveCounter`, then writes
the band the incremented counter selects [save.c:144-153]. A gift session that ends in a success
message saves [mystery_gift_menu.c:1379]; one that ends in any other result returns to the menu
without saving. When the session will end in success, write the band `gSaveCounter % 2` selects now:
the session's save writes the other one. To be adopted,
a sector sits at band position 13 with counter `gSaveCounter + 2`, one above the session's
`gSaveCounter + 1`. The id at position 13 is `(13 - gLastWrittenSector) % 14`, derived on the console.

### Composing a sector from a RAM snapshot

The save routine serializes at save time, so SaveBlock2's live contents differ from what it would
write. Every checksum passes and `gDamagedSaveSectors` stays 0 in both cases below:

- The encryption key is re-rolled on load. `LoadGameSave` restores the blocks, makes a new key,
  applies it to every encrypted field in RAM and stores it in SaveBlock2
  [decomp:src/load_save.c:126-128]. A SaveBlock2 composed from RAM beside an untouched SaveBlock1 reads
  money as `raw ^ flash_key ^ ram_key`. The encrypted set
  [ApplyNewEncryptionKeyToAllEncryptedData]: Trainer Tower times, game stats, bag quantities and berry
  powder in SaveBlock2, money and coins.
- The saved map view, 420 bytes at SaveBlock2 `+0x898` (210 u16 metatile ids, `0x03FF` blank), is
  filled only at save time and is zero in RAM; a composed sector draws the overworld as a blank grid.

A normal save writes all fourteen sectors at once, so key and ciphertext move together; a partial
write must preserve that.

### Reading flash: a 64 KiB window over a 128 KiB chip

`swi 0x48` addresses the chip linearly. A guest load sees a 64 KiB aperture at `0x0E000000`, and a
1 Mbit part reaches it as two banks:

    sector N is bank N / 16 at 0x0E000000 + (N % 16) * 0x1000

An address above the aperture aliases: `0x0E01E000` (sector 30) reads `0x0E00E000`, sector 14 of the
selected bank, usually zeros. Compute bank and window from the sector. Selecting the bank is the game's
own four stores [decomp:src/agb_flash.c SwitchFlashBank, `0x081E0C74`, seven instructions, no loop,
no `REG_WAITCNT`], inlined so a payload makes no ROM call:

    strb 0xAA -> 0x0E005555 ; strb 0x55 -> 0x0E002AAA ; strb 0xB0 -> 0x0E005555 ; strb bank -> 0x0E000000

Reads are byte-wide; the flash bus is 8 bits.

`ReadFlash`'s one lasting effect, `REG_WAITCNT`'s SRAM field set to
3 (`WAITCNT_SRAM_8` [decomp:src/agb_flash.c:149]), is already in place after boot: `AgbMain` clears it
[main.c:143], the boot save load calls `ReadFlash` [intro.c:1006], and every flash routine writes 3
(`gFlash->wait[0]` [agb_flash_mx.c:28, agb_flash_le.c:28]).

Never point the outgoing message at flash. The header and body read the window at different widths:

| step | code | load | what it read |
|---|---|---|---|
| header CRC | `CalcCRC16WithTable` [mystery_gift_link.c:166] | `ldrb` | flash: `0xDEC2` is the CRC of physical `0x1BC00..0x1BFFF`, `0x5907` of `0x1E000..0x1E0FB` (bank 1 selected) |
| body | `Rfu_InitBlockSend` copies each chunk of 252 bytes or fewer into `gBlockSendBuffer` [link_rfu_2.c:1357] with `memcpy` `0x081E44F4` | `ldm`, one word, when source and destination are word-aligned and 16 bytes or more remain | other bytes: runs of the byte pairs `01 cb`, `10 3a` and `04 3a`, identical for `0x0E01BC00` and `0x0E01E000` |

The body CRC fails, the host discards it, and the gift menu hangs with the RFU link up. Where the
body bytes come from is unknown. `build_memory_dump` and its two siblings
refuse any span touching `0x0E000000..0x0FFFFFFF`. `flash-read` copies the sector into EWRAM with
`ldrb` and sends the copy, which returns the sector exactly.

### Changing one field of a real save

`flash-patch` reads a sector a real save wrote, changes one field and writes it back, so the key and
map view stay consistent. An edit is two sectors:

    A   the target id's sector: patch the field, recompute the checksum over the id's own chunk,
        set the counter to gSaveCounter + 2
    B   the sector at band position 13: set its counter to gSaveCounter + 2 and nothing else, not
        even the checksum, because +0xFFC is outside the summed data area

The loader takes the band (twelve sectors at the old counter, two at the new) because all fourteen ids
are valid and the last valid sector carries the higher counter. A `flash-patch` of the player name
changes only sector A's field and checksum and sector B's counter; the load adopts the band with no
bad checksum, money and overworld unchanged, and the key copies and map view are those the game
wrote.

### The chain, end to end

Measured on the emulated console: a buffer script composes a sector from the live globals, `swi 0x48`
writes it, the game's next save commits the image, and the next load adopts the band with
`gDamagedSaveSectors` clean. The delivered pattern (distinct from the loader's pre-test pattern, which
appears nowhere) reads back in EWRAM, 500 consecutive words at each of two sites.

# Reading the save

A Mystery Gift session reads the live save: the secret ID, and every party Pokemon's PID, IVs and
nature. Nothing is written and no card changes hands. The host's log decodes a `save-dump` of
SaveBlock2 from offset 0 (name, gender, TID, SID, play time) or of SaveBlock1 covering 0x38 (each
party Pokemon's nature, IVs and EVs) through `pokeldn.frlg.save.readout`, and a `trainer-id-probe`
answer as TID and SID.

## Trainer ID and secret ID

SaveBlock2 offset 0 holds the player name, gender, the 32-bit trainer id and the play time
[global.h:327]. The low half is the TID on the trainer card; the high half is the secret ID, shown
nowhere and sent in no link message.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS \
        --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin

    ./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2

    dump.bin: 64 bytes from sav2 + 0x0
      playerName    'PLAYER'
      gender        boy
      trainerId     0x12345678  TID 22136  SID 4660
      playTime      12h 34m 56s

A TID that disagrees with the trainer card means a bad read.

## The party

SaveBlock1 0x34 is `playerPartyCount`, then `playerParty[6]` at 0x38, 100 bytes each [global.h:772]:
604 bytes for six.

    POKELDN_RADIO=esp32:auto ./.venv/bin/python -u bin/frlg_mg_host.py --live --keys PROD_KEYS \
        --buffer-script save-dump --dump-block sav1 --dump-offset 0x34 \
        --dump-size 608 --dump-file party.bin

    ./.venv/bin/python tools/frlg/dump_read.py party.bin --block sav1 --offset 0x34

    party.bin: 608 bytes from sav1 + 0x34
      playerPartyCount 5
      slot 1: PIKACHU   Lv25 nick='PIKACHU' OT='PLAYER' PID=0x00000019 Hardy   IVs=[10,20,30,15,5,25] checksum ok
      slot 2: ...

(Illustrative values.)

IVs read HP, ATK, DEF, SPE, SPA, SPD. The shiny column compares each mon's PID with its own OTID. `checksum ok` on every slot
means a real party. Party mons are stored as a `.pk3`/`.ek3` stores them (`pokeldn.frlg.save.mon`): the
48 bytes at 0x20 XORed with `PID ^ OTID`, the four substructs ordered by `PID % 24`.

SaveBlock1 holds the party as of the last save (`SavePlayerParty` [load_save.c:160], see
`--create-mon-append`). For the live party dump `gPlayerParty`, 0x02024280 on both measured cartridges:

    --buffer-script memory-dump --dump-address 0x02024280 --dump-size 600

Never carry an absolute save-block address between runs; `save-dump` takes the pointers fresh.
IWRAM and `gRngValue` are on [the random number generator](frlg_rng.md).

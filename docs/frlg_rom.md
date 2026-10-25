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

### The self-test script

`--gift mystery-event-probe` is harmless: `givenationaldex` is a no-op once the National Dex is on,
and `checksum` only reads.

    givenationaldex; setstatus 42; checksum 1026, 16, 31

| status | what it means |
|---|---|
| 42 | the chain ran to the end and pointer operands are offsets into the sent buffer |
| 1 | the chain ran, but the relocated pointers did not land on the test bytes |
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

`IntrMain` enters a handler in SYS mode with `lr` at `intr_return` and lets it overwrite r0-r3 [crt0.s,
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

### Installing it again after a reset

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

The tail target comes from the table, so the hook chains whatever handler is there. The check at the
top is required: installing twice makes the stub tail-branch to itself, which spins inside an
interrupt handler and freezes the overworld.

The script block at `SaveBlock1 + 0x32E0` survives a soft reset at the re-rolled pointer (verified on
an emulator).

The script rebuilds the code on every install, so the code is bounded by a script body: 162 bytes
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
The staged copy equals the save except the hook's fifth word, and every install stages the same bytes
(verified on an emulator, where the counter ran at 60.0 a second).

### Calling the wrapper

The GBA code reaches the Switch emulator through Sloop syscalls: 23 between
`swi 0x40` and `swi 0x62`, with gaps at 0x46, 0x4E, 0x52 and 0x58 to 0x60 [src/sloopsvc.c]. A
resident payload can issue any of them: the builder assembles a thunk `swi N ; bx lr` into the blob
with the number patched in. Markers go down before the call, since a syscall that does not return
leaves nothing else to read:

    +0x00  0xB0B00001   the call was reached
    +0x04  the syscall number
    +0x08  0xB0B00002   it returned, and zero until it does
    +0x0C  r0, r1, r2, r3 as the syscall left them

The lower numbers run the embedded BIOS: `main` carries the 16,384-byte GBA BIOS image at file
offset `0x177BAC`, its vector table at `+0` and the string `Coded by Kawasedo` at `+0x2D34`.
`swi 0x00..0x2A` executes as guest ARM code in the emulated CPU. The dispatcher at `main+0x57014`
takes `0x40..0x62` and leaves the numbers below 0x2B to that image.

`swi 0x54`, `svc_CommsAllowedByParentalControls` [sloopsvc.c:182], returns non-zero on a console
with no parental controls.

#### The dispatcher and its jump table

The dispatcher is at `main + 0x057014`, its jump table at `main + 0x17D7F6`. It admits
`N` in 0x40..0x62:

    cmp   w2, #0x2b ; b.lo default       below 0x2B, the BIOS syscalls
    sub   w9, w19, #0x40 ; cmp w9, #0x22 ; b.hi default
    ldrh  w12, [table, w9, lsl #1]       a u16 word-offset from 0x05706C
    br    base + offset * 4

Thirty-five entries, twenty-three distinct handlers. Every number `sloopsvc.c` names has its own.
0x46, 0x4E and 0x58 to 0x60 share the default, exactly the decomp's gaps. 0x48 and 0x56 share one
handler (`WriteSector`, `ReplaceSector`); 0x40 and 0x41 share one that branches on the number.
The dispatcher's `x0` is the CPU object, `w2` the number, and `x3` the register context its
handlers read: the guest's `r0` at `+0x48` and `r1` at `+0x4C` (the `0x52` handler's
`ldp w1, w22, [x20, #0x48]` after `mov x20, x3`).

The default is `cmp w19, #0x2a ; cset w0, hi ; ret`. That `w0` is the wrapper's own "handled"
boolean, not the guest's r0, so an unimplemented number is inert (no hang) and leaves every guest
register untouched. A test that passes zero and reads zero has measured nothing.

Never step 0x40..0x62 with an unchosen r0: 0x48 and 0x56 take a sector number and a pointer, 0x4C finishes a save,
0x55 hands over a SaveBlock2 pointer, and 0x43, 0x57, 0x61 and 0x62 take arguments. A marker in r0
becomes a garbage flash source.

The payload rewrites its own `swi` before each call (no instruction cache), writes the number first so a
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

The destination address is formed in 32-bit arithmetic [main + 0x05737C]:
`0x0E000000 + ((r0 & 0xFFFFF) << 12)`, and the region entry is that address's top byte
[main + 0x057384]: `0x0E + ((r0 & 0xFFFFF) >> 12)` mod 256, so `r0` selects the region. A
destination in EWRAM, IWRAM or the cartridge buffer passes both bounds checks (`fold < size`,
`size - fold >= 0x1000`); with `r0 = 0xFA000 + n` the destination folds into the ROM copy's
4 KB at `n * 0x1000` (`n` 0..0xFFF), from any source region.

A ROM destination is a live write into the cartridge buffer, measured on the patched Ryubing
build of the emulated console over the IP host (no retail console touched): with
`r0 = 0xFA3FF` (`dest` 0x083FF000, `n` = 0x3FF, region entry 0x08) and an EWRAM source
(`r1` 0x0201C400, fold 0x1C400, mask 0x3ffff), both gates pass and the copy lands: the cartridge
buffer's bytes at 0x3FF000 became the source's own 0x1000 bytes exactly (200 words of a chosen
pattern at 0x3FF000..0x3FF31F, then the source's own tail bytes at 0x3FF320+ carried along, e.g.
word 200 = 0x11111000 in both places). A guest load at 0x083FF000 then reads the pattern through
the folded ROM window. The host session held: the payload returned 1, `client->param` carried the
pattern's own first word, the console printed the success message and closed the link cleanly.

Code copied the same way executes. With the source's word 0 a two-instruction THUMB routine
(`0x47706001`: `str r1,[r0]; bx lr`) and words 1..199 the pattern, after the copy the payload read
the fold back (`0x47706001`, the routine) and branched to `0x083FF001` with a nonce in `r1` and the
address of its own result word in `r0`: the console's answer carried the nonce, so the wrapper's
instruction fetch reads the same live backing the syscall wrote, and the copied bytes run as code
through the normal fetch path. The session closed with the success message and the game saved.

The write persists through a soft reset. After A+B+START+SELECT the same 4 KB at fold 0x3FF000
read back byte-identical (0 of 4096 bytes changed) through the debugger while the EWRAM source
scratch was cleared. A second session opened after the reset read 0x083FF000 (`0x47706001`) and
branched to 0x083FF001 with a fresh nonce; the resident routine returned that nonce. A full
application relaunch restored the bytes from the emulator's ROM file: the fresh process held the
file's original bytes at the fold. The write's lifetime is the emulator process lifetime.

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
| `r0 = 0xFA3FF` (dest 0x083FF000), `r1` an EWRAM buffer | the copy lands in the cartridge buffer: its bytes at fold 0x3FF000 became the source's 4 KB byte for byte; a guest read at 0x083FF000 returns the pattern; the session ended cleanly |
| the same copy, the source's word 0 a THUMB routine, then a branch to `0x083FF001` with a nonce in `r1` | the copied routine returned the nonce; the console showed success, saved and closed cleanly |
| after a soft reset, a debugger read of the same fold | the 4 KB matched byte-for-byte (0 of 4096 bytes differed), while the EWRAM source scratch was cleared |
| after the reset, a second session that reads the routine then branches to `0x083FF001` | the resident routine returned a fresh nonce and remained callable across resets in one process |
| after a full application relaunch, a debugger read of the same fold | the original ROM-file bytes were restored at the fold; the write's lifetime is the process lifetime |

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

The third patch removes a wait loop. The function at `0x081E1F74` polls `REG_SIOCNT`
(`0x04000128`) bit 2 against the caller's `r0` (`r0` masked to u16, `lr = r0 >> 14`), and
returns early when the byte at `[*(0x03000030) + 0x10]` is 1, clearing it and answering 1. In
emulation the poll never matches, so the wrapper replaces the body with `mov r0, #0; return`:
the wait answers 0 at once.

`bkpt #0x52` is keyed by address: its hook holds two records `{u32 pc, u32 original insn, ..., u32
hits at +0x0C}` at `+0x120` and `+0x148`, and `main + 0x0546C0` matches the address and returns the
original instruction. At the `Sio32IDMain` patch (`0x081E1696`) it resolves guest `r0`
(`&gRfuSIO32Id`) and stores `0x8001` at `+0x0A`, the adapter id `AgbRFU_checkID` waits for
[librfu_sio32id.c]. A `bkpt #0x52` at any other address re-points the second record (the `0x081E187C`
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
  console's own Mystery Gift search found it `0x1` every time, so `swi 0x40` alone turns the write path on.
- on a record-1 mismatch re-points record 2 (holder `+0x148`): `record2.pc := the bkpt address`,
  then matches it, so the core executes record 2's original, which is never updated: the stale
  `0x081E187C` original `e59f3050` (`ldr r3, [pc, #0x50]`), at any address the guest executes a
  `bkpt #0x52` from, in whatever CPU mode the guest is in. On the console's own Mystery Gift
  search, every dispatch re-points through this path: record 2's hit count (holder `+0x154`)
  advanced about 20 per 0.33 s across three live reads, record 1's did not move, so the STWI
  driver's own `bkpt #0x52` at `0x081E187C`'s runtime IWRAM copy, not the `Sio32IDMain` ROM site,
  is what the search screen runs once a frame.
- on a record-2 match with the `+0x108` flag set, falls into `main + 0x03E954`: it folds the
  address stored at holder `+0x170`, reads a word at the folded address, and uses the word's top
  byte as a region selector and the word itself as the address to fold again, bounds-checked,
  decrementing a counter at holder `+0x42B8 + 0x7C`.
- on a record-2 match with the `+0x108` flag clear, falls into `main + 0x03E960`: it folds the
  address stored at holder `+0x170`, reads a word there, and tests its bits 15 to 26 against
  `0x600`. On a match it folds the word's low 24 bits through the same region table,
  bounds-checked, and decrements the counter at holder `+0x42B8 + 0x7C`; on a mismatch,
  nothing.

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

The neighbour changes between boots: one boot's ROM neighbour is an object whose first word is
the vtable `main + 0x1C36D8` and whose `+0x60` is the vtable `main + 0x1C3790`. The constructor
`main + 0x547CC` writes exactly that pair, reading the static pointer at `main + 0x86D67E8`
(addend `main + 0x1C36C8` [main_relocs.json]). That class's fields are written by its own
constructor and its own code; no store from a guest session reaches them.

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

A write over the component's first two bytes replaces the vtable pointer with `0x086C8001`, and the
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

#### The chain from a bkpt to the resolver

An NSO's vtable slots hold unrelocated addends in the file; the loader adds the image base
(`main` at `0x8506000`). With that base applied, a guest `bkpt #0x52` runs this chain:

- both decode paths (THUMB `main + 0x1EFE0`, ARM `main + 0x1B7B8`) call the dispatcher
  `main + 0x1F820` as `(CPU, bkpt address, immediate, &insn)`;
- the dispatcher takes hook = `[CPU + (imm & 0xff) * 8 + 0x170]`; for `bkpt #0x52` that is
  `component + 0x60`, a sub-object of the component (the component is the GBA CPU object: `+0x84`
  current pc, `+0x170` hook table, `+0x960` a second bus table, `+0xE0` the bus object). It reads
  the hook's own vtable (`main + 0x1C3948`) slot `+0x10`, and calls it as
  `f(hook, &insn, bkpt address, CPU)`. Slot `+0x10` is `main + 0x5499C` directly;
- `main + 0x5499C` writes `0xE1200572` into `insn`, then loads `[component]` and tail-calls the
  virtual at `[that pointer + 0x98]` with `(component, &insn, bkpt address, CPU)`: slot `+0x98`
  of `main + 0x1C3878` is `main + 0x56368`, which derives the record holder and reaches the
  resolver `main + 0x03E850`.

A store over the component's first ten bytes is therefore consumed at slot `+0x98`; the
`+0x10` read happens on the hook sub-object, outside those ten bytes. The resolver's write
target is `buffer_data + fold + 0xA`, the fold being the selected region's slot 9
([`swi 0x52` and `swi 0x55`: the memory bus](#swi-0x52-and-swi-0x55-the-memory-bus)).

#### What a write across a region's edge does

With `fold = size - 0xB` (in range) the write pair is `(size-1, size)`: the region's last byte
gets `0x01` and the first byte of the neighbouring allocation gets `0x80`. With
`fold = size - 0xA` the pair is `(size, size+1)`: `0x01 0x80` onto the neighbour's first two
bytes. One Mystery Gift session allows one chosen fold per visit.

The body behind the site returns through a five-word frame: its epilogue at `0x081E177C` is
`movs r0,#0 ; pop {r4,r5,r6,r7} ; pop {r1} ; bx r1`. A payload that branches to the site skips
the function's prologue and must push that frame itself, with `lr` at a continuation; the body
then returns to the payload, which can run more code and finish the session normally. A payload
that pushes any other frame unwinds through its caller's stack instead, and the measured runs
re-entered the site with the same parked `r0`.

Window 4, the GBA IO registers, maps to a 0x400-byte region object that sits immediately behind
its own backing allocation: the backing is at bus `+0x14C0`, the object at bus `+0x18C0`, and
the key-interrupt sub-object is embedded at object `+0x88`. The write therefore lands on the
object the bus dispatches every IO access through. The image's CPU core has 210 call sites in
the accessor shape ([`swi 0x52` and `swi 0x55`: the memory bus](#swi-0x52-and-swi-0x55-the-memory-bus)).

On the emulated console:

| write | read at | outcome |
| --- | --- | --- |
| component byte pair `01 80` (`0x086C8001`) | the slot `+0x98` read at `main + 0x1C2099`, unrelocated, `0x1f7` ([above](#what-follows-the-rom-buffer-the-sloop-component)) | |
| component byte 0 `0x80` (`0x086C9880`) | `main + 0x5492C`, the same method without the `-0x60` | it re-reads `[x0] + 0x98` on the still-rewritten component and recurses into itself; the thread stack exhausts and the process dies with a data abort (`InvalidMemoryRegionException`) |
| IO object byte 0 `0x80` (`0x086C8480`) | the bus's store slots `+0x38`/`+0x40`, whose replaced targets are raw `0xffffffffffffe5e0` and `0` | the first IO store after the write aborts the process within ~30 ms; the load targets (`main + 0x30EAC`, `main + 0x31114`, `main + 0x36D54`) never run |
| name-hash block byte 0 (`0x80`) | the block is an SDK binder/surface descriptor object (`android.gui.IGraphicBufferProducer` and friends are static strings in the SDK image), not a dispatched object | no reaction; the game runs to its own clean exit |

The write `0x086C8080` (bytes `80 80`: every `bkpt #0x52` then runs the pure counter getter
`main + 0x1F7F0`, so each bkpt becomes a no-op) needs two writes with no dispatch in between;
one session allows one write, and both single-write states on the way kill the process. Written
through the debugger instead, that pointer stayed in place for five minutes with the game
running and the process alive. No code site in the image writes a wrapper object's header after
init.

#### Every placement a single write can make

A single write leaves one of two byte patterns on the neighbour: `80` on its first byte (the region's
own last byte takes the `01`), or `01 80` on bytes `k` and `k+1`, `k` in 0..9. The neighbour's
first eight bytes are its vtable pointer, so the pointer the consumer then reads resolves against
the file image and its relocations. Four placements read live main memory:

| object | bytes written | rewritten pointer | consumer |
| --- | --- | --- | --- |
| the component (vtable `main + 0x1C3878`) | `80` at +0 | `0x086C9880` | the `bkpt #0x52` chain's `[P + 0x98]` = `main + 0x1C3918` = `main + 0x5492C` |
| the component | `01 80` at +0..1 | `0x086C8001` | `[P + 0x98]` = `main + 0x1C2099` = raw `0x1F7` |
| the IO object (vtable `main + 0x1C2408`) | `80` at +0 | `0x086C8480` | the bus accessor slots, below |
| the IO object | `01 80` at +0..1 | `0x086C8001` | the bus accessor slots: `0x1F7`, zero, raw addends |

The other placements resolve outside the image. `01 80` at +1 gives `0x08800178` (component) and
`0x08800108` (IO object), inside main's bss. A zero-filled bss model predicts a null
call there; the file image alone does not establish the contents during a live session. `01 80`
at +2 through +7 moves byte 2 or byte 3, so the consumer's read itself faults. At +8 and +9 the
pair lands on the field at `+8` (the component's `0x000004BF` becomes `0x00008001` at +8 and
`0x008001BF` at +9) and the vtable pointer stays in place, so the dispatch is the object's own.

Two site visits can compose their pairs on the IO object when no `0x04` access occurs
between them; the payload's instruction fetches from ROM or EWRAM do not themselves access
that object. Repeating a placement is idempotent, and writes at +8 or +9 leave the vtable
pointer unchanged. Distinct placements confined to bytes 0 and 1 can still leave one of the
in-image pointers above; compositions that change higher pointer bytes need separate analysis.
On the component, the next `bkpt #0x52` consumes the current write. The STWI driver produces
about 60 such calls a second while the link is up, but that rate alone does not establish that
a call intervenes between every pair of payload visits.

The IO object's rewritten block, by bus slot. The access class comes from the caller's result mask
(`and #0xffff` at `main + 0x18378` for a 16-bit load, the word rotate at `main + 0xBDB8` for a
32-bit load, `and #0xff` at `main + 0xD914` for an 8-bit load).

| bus slot | access | rewritten target | with the IO object as `this` |
| --- | --- | --- | --- |
| `+0x18` | 16-bit load | `main + 0x30EAC` | the key handler's default case: `w2` is the full `0x04xxxxxx` address, above every register id the handler switches on, so it stores `w3 & 0xffff` at `[x1]`; the call site at `main + 0x18330` passes `x1 = CPU + 0x20` and `w3 = 1`, and the guest's load returns the handler's leftover `w0` |
| `+0x20` | 32-bit load | `main + 0x31114` | calls `main + 0x3580C` with `(x1 from the site, IO + 0x20)`, then tail-calls `main + 0x22404` with `x0 = [[IO + 8] + 0x90]` |
| `+0x28` | 8-bit load | `main + 0x36D54` | a 0x76000-byte object's teardown family: `[x0 + 0x76C70]`, `+0x76C30`, `+0x76C00`, `[x0 + 0x4E68]` |
| `+0x30` | store | `main + 0x36E40` | `x0 -= 0x1A10`, then `main + 0x3664C`, the same teardown family on the rebased pointer |
| `+0x38` | store | raw `0xFFFFFFFFFFFFE5E0` | the call faults |
| `+0x40` | store | `0` | null call |
| `+0x48` | | `main + 0x36E4C` | the teardown family at `+0x76C60`, `+0x76C20`, `+0x76BF0`, `[x0 + 0x4E58]` |
| `+0x68` | | `main + 0x310A8` | `x0 -= 0x10`, then `main + 0x30EAC` |

None of the placements above reaches a dispatch target that guest memory supplies: the four
in-main placements read main's own data, and the IO object's block calls main's own handlers with
the bus's arguments.

On retail (a Switch Lite, English FireRed, the payloads delivered over LDN by a XIAO ESP32S3
radio), the component write and the in-range write are told apart by the link teardown, not by the
screen. Every run returned to HOME with "The software was closed because an error occurred" about
two seconds after the script, so the message is generic; the graceful Pia leave
(`Session type 3`) is not:

- with the fold one past the cartridge buffer (component, `r0 = 0x08FFFFF6`), the console left LDN
  with no `Session type 3` (tags `pl01`, `pl04`) - the abrupt abort the emulator's dispatch shows,
  now on hardware;
- with the fold in range (`r0 = 0x08FFFFF0`, tag `pl03`, write at buffer `+0xFFFFFA`) and with the
  EWRAM end-overrun that lands on VRAM (`r0 = 0x0203FFF6`, tag `pl02`), the console sent
  `Session type 3` and left gracefully; ordinary card sessions (`scratchpad/re1_host.log`,
  `rt02`..`rt04`) do the same.

So the record-resolver store reaches a live wrapper object on retail when the fold crosses the ROM
buffer's end, and the app aborts there; the same store kept in guest-visible memory does not. A
payload that pushes the body's frame returns from the site on retail as well.

The dispatch after the write is the app's next `bkpt #0x52`. The game produces them from two
places: the STWI driver's IWRAM copy, about 60 a second while the link is up (a live read of its
hit count), and its own calls into `Sio32IDMain` at the site (12 hits in a live read of record 1).
With the vtable's low byte at `0x80` that
dispatch reaches `main + 0x5492C`, which re-reads `[component] + 0x98` on the rewritten pointer and
recurses until the thread stack leaves its region; the console returns to HOME with no
`Session type 3`. A payload that puts the cartridge's own instruction back over the IWRAM copy's
`bkpt #0x52` and reverts the cartridge copy's two load-time patches (the 4 KB block that holds
both sites, through `swi 0x48`) removes both sources: the console then shows the game's own
communication error, leaves LDN with `Session type 3`, files its network report and runs on. The
written pointer is inert in that state, not repaired: no code site restores the vtable. The reverted
cartridge copy is process-lifetime state as well: the wireless menu then reports the adapter as
not connected, and a full relaunch re-applies the wrapper's load-time patches.

#### The candidate copy as a vtable write

`swi 0x45` composes its stores through the candidate list rather than one placement. With one
candidate in the list (`owner + 0x2770 == 0xB`, count 1) and `r0 = 0x08FFFFD7`, the candidate's
8-byte display name lands at `component + 0` and the `bkpt #0x52` hook object at `+0x60` stays
outside the write. That name is slot bytes `+0x10..+0x17` ([The wrapper's own scan
pipeline](#the-wrappers-own-scan-pipeline)), so the component's vtable pointer comes from the
peer's advertisement record.

The next `bkpt #0x52` reads `[component]` and calls `[component + 0x98]`. A host that advertises
the display name as a native address therefore chooses the call target. Measured on the emulated
French FireRed, with the advertised name `08 01 df 1f 66 00 00 00` (`0x661FDF0108`, inside the
ROM copy), a 4 KB block of `0xDEADBEEF` written through `swi 0x48` to fold `0xFA3F6`
(`ROM + 0x3F6000`), one candidate, and the payload's `bkpt #0x52`:

```
Unhandled guest exception PcAlignmentFault at ELR 0xDEADBEEFDEADBEEF (ESR 0x8A000000)
```

`ESR 0x8A000000` carries exception class `0x22`, a PC alignment fault, and `ELR` holds the eight
bytes at `[P + 0x98]` for `P` equal to the advertised name. The branch target was guest data.

### Coverage

The guest paths mapped on this page include a store past a region's backing: the resolver's `0x8001` strh at `fold + 0xA`; a rewritten pointer's readers
take their targets from `main`'s own data at static addresses ([Every placement a single write
can make](#every-placement-a-single-write-can-make)). The four placements that read live
memory and what every other placement leaves are listed there; the component's consumer during a
session after the low-byte `80` write is `main + 0x5492C`, from the `bkpt #0x52` hook chain.
The single-write survey finds no call target supplied by guest bytes; it does not cover
every sequence of writes. Removing the chain's two guest sources stopped the observed dispatch. The syscalls' stores into the component and their readers are in
[The remaining syscalls](#the-remaining-syscalls); the
`main + 0x1C36C8` class's fields are written by its own constructor and its own code ([What
follows the ROM buffer](#what-follows-the-rom-buffer-the-sloop-component)). The third load-time
patch replaces a wait loop. The bad-word filter's two buffers are length-bounded inside the
dispatcher's own frame ([The bad-word filter](#the-bad-word-filter)); the flash-sector path's
bounds are in [The flash sector path](#the-flash-sector-path).

The Pia side has both ends decoded: the guest's `RfuGameData` and username are re-packed into the
advertisement record and base85-encoded ([The advertisement
record](#the-advertisement-record)); the peer's `NetworkInfo` bytes reach the candidate list
verbatim ([The wrapper's own scan pipeline](#the-wrappers-own-scan-pipeline)); the peer's session
messages pass the per-type bounds before a handler reads them ([The Pia session-message
dispatcher](#the-pia-session-message-dispatcher)). The following [wire-parsing section](#the-pia-librarys-own-wire-parsing)
traces the statically linked `PiaCommon-6_42_1` path from the UDP socket to the session queue;
that trace maps the path, not every length check and message handler in it.

#### The remaining syscalls

Handler addresses are `main + 0x05706C + entry * 4` from the jump table at `main + 0x17D7F6`. The last
column is what one issue from the Mystery Gift client with `sloop-svc` showed.

| swi | handler, callee | what it does | observed when issued once |
| --- | --- | --- | --- |
| 0x40, 0x41 | `main + 0x05706C` | the adapter power switch: stores `r0 == 0x40` at `[component + 0x40] -> [+0xA8] + 0x170` | swi 0x41 from the Mystery Gift menu raises the link error and leaves LDN ([above](#what-follows-the-rom-buffer-the-sloop-component)) |
| 0x42 | mode switch `main + 0x0588A0` | `rfu_REQ_startSearchChild` [sloopsvc.c:49]; sets the network manager to mode 2 | ends the session with the link error; no access point opens |
| 0x43 | `main + 0x0570EC` -> `main + 0x058AD0` | `rfu_REQ_startConnectParent`, 16-bit PID in `r0` [sloopsvc.c:91]; the same mode switch | the buffer script answered, then "Erreur de connexion" at close |
| 0x44 | `main + 0x057100` -> `main + 0x058B0C` | `rfu_REQ_stopMode`, no arguments [sloopsvc.c:102] | after 0x43, no visible change |
| 0x45 | `main + 0x057110` -> `main + 0x058900` | `rfu_REQ_startSearchParent`, `rfu_STC_readParentCandidateList` with `&gRfuLinkStatus` [sloopsvc.c:67-75]; copies the wrapper's scan result through the region table into `struct RfuLinkStatus`, `findParentCount` [include/librfu.h] at offset 8 first | 220 zeroed bytes stayed zero (no parent search in a gift session) |
| 0x46 | jump-table entry `0x147` | falls through to the dispatcher's exit: the syscall does nothing | |
| 0x47 | `main + 0x05715C` -> `main + 0x058680` | `rfu_REQ_configGameData`, `r0` points to `struct RfuGameData` (16 bytes) and the username (8, `RFU_USER_NAME_LENGTH`) [sloopsvc.c:34-46; include/link_rfu.h:103-115,232]; copies all 24 to `component + 0x6050D8` and `activity` (bits 16-22 of the second 64-bit word) to `component + 0x605360` if changed | `activity` 0x30 landed byte for byte at both |
| 0x48, 0x56 | `main + 0x057084` | the flash-sector copy: the destination sector is guest `r0`, the source is `fold(guest r1)` through the same region table and bounds-checked against the region's size, up to 4 KB | [The flash sector path](#the-flash-sector-path) |
| 0x49 | `main + 0x0571A8` -> `main + 0x0588D0` | calls `main + 0x0588D0` on the `component + 0xD0` object; takes no guest argument | returns 0 |
| 0x4A | `main + 0x0571B8` -> `main + 0x058AB8` | the same shape on `component + 0xD0` | returns 0 |
| 0x4B | `main + 0x0572C4` | no argument; bit 1 makes `RfuMain1` reseed the RNG from `gHostRfuGameData->compatibility.playerTrainerId`, bit 0 clear makes `SpawnGroupLeaderAndMembers` exit early for a leader [sloopsvc.c:132-145] | 0 |
| 0x4C | `main + 0x0571CC` | calls `main + 0x05D930` on `[component + 0xE8] + 0xA0`, and when it answers 0 calls `main + 0x049D28` on a global pointer; no guest data reaches either | returns 0 |
| 0x4D | `main + 0x0571FC` | the bad-word filter: resolves `r0` and reads up to 256 bytes at `fold(r0)`, [below](#the-bad-word-filter) | |
| 0x4E | jump-table entry `0x147` | falls through to the dispatcher's exit: the syscall does nothing | |
| 0x4F | `main + 0x057248` -> `main + 0x058B54` | builds `{u16 tag 0x4757; u32 value = r0}` on its stack; the tagged-property dispatcher `main + 0x4EBD0` and setter `main + 0x058BB4` store the value unvalidated at `component + 0x6052A0` | writing 3 and `0x7FFFFFFF`, each followed by 0x49 and 0x4A, changed nothing observable |
| 0x50 | getter `main + 0x058BA4` | reads the same 4-byte count back | |
| 0x51 | `main + 0x057270` -> `main + 0x0511BC` | reads `component + 0x3404` into an out-parameter and clears it; the out-parameter is always the dispatcher's own stack slot | |
| 0x52 | `main + 0x05728C` | folds guest `r0` through the bus object's region table (`[component + 0xE0] + 0x50`) and calls the region's `+0x48` fold. A non-zero guest `r1` also runs the pointer resolver `main + 0x562CC`: it reads `[[bus] + 0x50 + (r1 >> 24) * 8]` with the index unbounded 0..255, calls the value's `+0x48` as a virtual, then returns `backing + offset` when `offset < size`. The handler is the resolver's only caller, discards its result and returns `r0 = 0`, so guest `r1` reads back 0. The 256 entries read live are main's own method pointers, negative values and zeros, none an object with a `+0x48` method | |
| 0x53 | `main + 0x0572D4` | answers `component + 0x2770 == 0` (through `[component + 0xD0]`) | |
| 0x54 | `main + 0x0572EC` | `svc_CommsAllowedByParentalControls` [sloopsvc.c:182] | returns 1 |
| 0x55 | `main + 0x057304` | stores `r0` at `component + 0xE1BC`, folds the stored word through the region table and reads one byte back ([What the play reports are built from](#what-the-play-reports-are-built-from)) | |
| 0x57 | `main + 0x057330` | `MonsSelect` into the report copy at `component + 0x140` | |
| 0x58 to 0x60 | jump-table entry `0x147` | falls through to the dispatcher's exit: the syscall does nothing | |
| 0x61 | `main + 0x057340` -> `main + 0x058B2C` | `svc_SetActivity`; writes `r0` to `component + 0x605360` only for 0x41 to 0x48, the Union Room activity codes | 0x45: a breakpoint on the callee's `ret` (`main + 0x058B50`) read `w1` and the field as 0x45; normal close |
| 0x62 | `main + 0x057354` | adds 1 to `component + 0xE1B0`, the next report's `CommsError` | |

Answers come back through `main + 0x2209C`: guest `r0` = 1 when the number is above 0x2A, guest
`r1` = the handler's answer word. No handler's answer carries a wrapper address.

`component + 0x6052A0` is 16 bytes: a 4-byte count, 4 unused, an 8-byte pointer into `main`. Freshly
launched: count 1, pointer `main + 0x1E8D20`, an array of pointers with two nulls after the one
populated slot.

The tagged-property dispatcher `main + 0x4EBD0` walks a listener list on the component: entries of
`0xd0` at `component + 0x10`, the count at `+0x688`, the enabled byte at `+0x690`; for each entry
whose first word is 2 it calls the component vtable slot `+0x50` with the 8 bytes at `entry - 8`
and the tagged entry. The setter `main + 0x058BB4` is the `0x4757` listener. The `0x59` listener
at `main + 0x50618` writes the value at `[tagged entry + 4]` to `component + 0x3324 + index * 4`,
the index read from `[x2]` and bounded 0..7 by `main + 0x4DB0C`. No syscall builds a `0x59`
entry or supplies that third argument, and the twelve calls of the dispatcher build their
entries from wrapper-internal fields. The count the `0x4757` listener stores at
`component + 0x6052A0` has no reader but the getter `main + 0x058BA4` (`swi 0x50`): every other
code site that forms the offset `0x6052A0` or `0x6052A8` in the image writes it or the pointer
beside it at init. The value the `0x4F` caller supplies is inert.

The console's own Mystery Gift search issues `swi 0x47` before any buffer script, advertising
`activity` 0x15 (`ACTIVITY_WONDER_CARD` [include/constants/union_room.h:46]); a payload's call
overwrites it. A breakpoint at `main + 0x0586B4` reads `component + 0x605360` through `x8 + 0x280`.
The game-data object (vtable `main + 0x1C3B30`) is a sibling of the CPU/bus object `bkpt #0x52`'s hook
table resolves (vtable `main + 0x1C3878`, region table, syscalls 0x45, 0x48, 0x52, 0x55, 0x62); the
live addresses differ by `0x100000000`.

The per-candidate layout 0x45 writes is unsettled: the copy loop's byte count does not match
`sizeof(struct RfuTgtData)`; read it live before depending on it.

`component + 0x6050D8`, the 24 bytes `swi 0x47` copies ([main + 0x058694], a pre-indexed
store from the guest's `r0` buffer), is read back by the same handler, which re-packs it into the
advertisement record. `component + 0x605360`'s readers are the activity diff
`main + 0x058698` (through `component + 0x6050E0`) and `svc_SetActivity`'s setter
`main + 0x058B40`; both compare or store the activity code.

#### The advertisement record

The `swi 0x47` handler assembles the 24-byte RFU record the advertisement carries from the guest's
own `RfuGameData` (16) and `gHostRfuUsername` (8) [include/link_rfu.h:103-115, src/sloopsvc.c:34-46]:

| record | source |
| --- | --- |
| `[0:2]` | `RfuGameData[2:4]`, the trainer id (`compatibility.playerTrainerId`) |
| `[2:10]` | the username |
| `[10:12]` | the wrapper's RFU session id, `main + 0x3F2E0([component + 0x6050D0])` |
| `[12:16]` | `RfuGameData[4:8]`, `partnerInfo` |
| `[16:20]` | the search word, packed from `RfuGameData[0:2]` and `[8:12]` |
| `[22:24]` | `RfuGameData[8:10]`, `tradeSpecies` |

The search word's bits, from the two source words: 0-6 the activity (`RfuGameData` bits 16-22),
7 the gender (bit 24), 8-10 the version (`RfuGameData[0:2]` bits 10-12), 11-14 the language (bits
0-3), 15 `startedActivity` (bit 23), 16 `canLinkNationally` (bit 7), 17 `hasNationalDex` (bit 8),
18-23 the `tradeType` (bits 10-15), 24 `gameClear` (bit 9), 25-31 the `tradeLevel` (bits 25-31).
`hasNews` and `hasCard` (bits 4 and 5) are not copied. The two bytes at `[20:22]` are left as the
frame held them.

The encoder `main + 0x2A90` writes five characters per 4-byte group, low digit first, over an
alphabet of `0x23` upward with `0x5C` skipped, and refuses when the output would pass the capacity
it is given. The handler calls it with a capacity of `0x20` for the 24 bytes, so the 30 characters
fit, and stores the text at `component + 0x6C0` with its `strlen` at `component + 0x700`
(`main + 0x15FAE0` and `main + 0x15FB20`, the `strlen`/`memcpy` PLT stubs).

The captured app data the host's beacon clones (`pokeldn/frlg/link/host_beacon.py`) is 122 bytes:
`0x5C` of Pia system header and 30 characters reading back as trainer id `0x1050`, the name
`GREEN`, RFU session id `0xac65` and search word `0x1584` (activity 4, version 5, language 2, bit 7
set).

The record text goes into an advertise-data builder the handler builds for the occasion (class
vtable `main + 0x1CB8C8`, constructor `main + 0x87514`): a `0x180`-byte Pia advertise area at
`+0x1C`, the used size at `+0x18` starting at the `0x5C` header, the app data pointer
`main + 0xA2C70` = `+0x78`, the app data size `main + 0xA2C90` = used minus `0x5C`, clamped to
`0x124` (slot `+0x28`, `main + 0x875AC`; the header offset `0x5C` is slot `+0x30`,
`main + 0x875A4`). `main + 0xA3480` appends the 30 characters at the app data offset through the
buffer object it holds at `+8` (its capacity is the buffer's vtable slot `+0x28`, its used size at
the buffer's `+0x18`, and the append sets bit 1 of the buffer's `+8`); its only caller is the
handler (`main + 0x58838`). The
handler then delivers the builder at `main + 0x58854`: `x0 = [component + 0x3528]`,
`main + 0xB1304`. That method calls a method on `[session + 0xD0]`, passes it on as an argument,
zeroes the u32 at `+0xD8` and calls
`main + 0xD4DD0(x0 = [session + 0x70], x1 = [session + 0xD0], x2 = [session + 0x30], x3 = the
builder)`. The delivery takes `X = [session + 0x30]` and calls `X`'s vtable slot `+0xA8` as
`(X, [session + 0x70] + 0x90, builder)`, after gating on `X`'s slots `+0xD8` (must return true)
and `+0xE8` (must return false). The session's `+0x30` is set by `main + 0xAF760` from
`[[session + 8] + 0xB8]`, the session owner's `+0xB8`.

`X` has the facade classes' shape: `nn::pia::local::LocalFacade` (vtable `main + 0x1CB548`) and
`nn::pia::net::NetFacade` (`main + 0x1CBE60`) share the implementation, and their slots are
`+0xA8` = `main + 0x8D4AC`, `+0xD8` = `main + 0x8D84C` (true when the facade's `+0x28` is set and
its `+0x30` non-null), `+0xE8` = `main + 0x8D920` (true when `[[facade + 0x30] + 0x12D8]` is
non-zero). The facade's `main + 0x8D4AC` validates through `main + 0x8C6FC`, locks the manager
(`[facade + 0x30] + 0x2B8` through `main + 0x94B78`, so the facade holds the manager at `+0x30`),
takes the value at the builder's `+8` (`main + 0xA3710`) and hands it to the manager's
`main + 0x99C3C`, then records the transport at `[facade + 0x48]` and state 8 at `[facade + 0x40]`.
The manager passes the buffer on to the job's receive half (below), and the job's publish half
reaches `nn::ldn::SetAdvertiseData` through the manager's blob builder.

The object the component keeps at `[component + 0x3528]` is a `nn::pia::session::Session`: the
class whose methods fill `main + 0xAF4E0` through `0xB23xx` (primary vtable `main + 0x1CE300`, a
second at `main + 0x1CE330`, constructor `main + 0xAF4E0`, which initializes fields from
`+0x10` onward and treats `+0xD8` as a u32). Its methods set `+0x30` (`main + 0xAF760`),
`+0x70` (set by
`main + 0xAF9F0`; live it holds the `UpdateSessionPropertyJob` singleton, whose `+0x10` u16 the
setter maintains) and `+0xD0` (`main + 0xAFA94`), and clear them at `main + 0xAFB44`; the delivery
caller reads `+0x150`,
`+0x528`, `+0x70`, `+0x30`, `+0xD0` and `+0xD8`, all Session fields. The component picks it at
`main + 0x528F8` from the object it embeds at `+0x34A0` (its first word) or from the global at
relocated slot `main + 0x1D1AB0` (which points outside the image, to `0x41FB1C8`), and opens it
with `main + 0xB14E0`, which stores the callback `main + 0x52BB4` at `+0x88` and the component at
`+0x90`. The Session's constructor has no caller in the image and its vtable-pointer slot is
loaded only by that constructor and the destructor, so the instance arrives from outside this
module. The live shape (emulated French FireRed, Mystery Gift session; the same `main`
binary): the layer is a set of bss singletons: `Session` at `main + 0x1029950`,
`SessionProtocol` at `main + 0x1032000`, the owner at `main + 0x9E1798`, the `LocalFacade` at
`main + 0x9E15B8`, and three session-job singletons at `main + 0x103FBB0`, `+0x103FCE8` and
`+0x1040180` (`LeaveMeshWithHostMigrationJob`, `ProcessHostMigrationJob`, `KickoutManageJob`).
During a live session `[component + 0x3528]` is exactly that `Session`, where component =
`[session + 0x90]`, the object the syscall dispatcher receives (its RFU shadow at `+0x6050D8`
holds the last record: activity `0x15`, the username bytes). `[session + 8]` (the owner; also
`[protocol + 8]` for every protocol and `[reader + 0x60]`) has no vtable: `+0xB8` holds the
facade, `+0xC8` the protocol manager. `[session + 0x30]` = the `LocalFacade`
(typeinfo-verified). The session jobs' `+0x80` is `[SessionProtocol + 0x130]` = the Session and
their `+0x88` is the SessionProtocol (their constructor `main + 0xCB0D0`: `stp x9, x19,
[x20, #0x80]`, `x9 = [x19 + 0x130]`).

The advertise machinery belongs to a different object, the
`nn::pia::local::LdnBackgroundProcessJob` (class vtable `main + 0x1CAC48`, `0xA60` bytes, factory
`main + 0x7EED8` = the manager's vtable slot `+0x278`, constructor `main + 0x83A88`), which
derives from `nn::pia::net::NetBackgroundProcessJob` (vtable `main + 0x1CB928`) and embeds a
`nn::pia::common::StepSequenceJob::Step` at `+0xD8` (vtable `main + 0x1C9770`) and a
`nn::pia::local::LocalConnectNetworkSetting` at `+0x320` (vtable `main + 0x1CA2D0`). Its base
constructor `main + 0x875BC` stores the network manager at `+0xA8` and builds the sub-objects; its
constructor builds the advertise-data builder at `+0x8C0` (`main + 0x87514`). The job's method
`main + 0x84260` (vtable slot `+0x60`) is the receive half: it locks the manager (`+0x2B8`),
touches the holder (`main + 0x87374` on `[manager + 0x200] + 0xA8` and `[manager + 0x2D8]`),
validates the incoming buffer through `main + 0x8885C` (the buffer's size `main + 0xA2C90` within
the manager's slot `+0x100` limit, the buffer's `+0x8` bit 1 set, `[manager + 0x12D8]` zero, the
`main + 0x879C0` check with `w2 = 8`, a timestamp at `[job + 0xA0]`), copies the buffer's
`0x180`-byte advertise area (`+0x1C`) into the job's builder at `+0x8C0` (`main + 0x87578`) and
sets the job's next step to slot `0x130`. It is reached through the job's vtable: the manager's
`main + 0x99C3C` hands the buffer to the object it keeps at `+0x250` (a
`StepSequenceJob::Step`-derived delegate, constructor `main + 0xA2824`, `0x98` bytes, a `0x38`-byte
helper at `+0x88`, the manager at `+0x90`), whose `main + 0xA28E4` calls the job's slot `+0x60` as
`(job, helper, buffer)`. The publish half is the job's `+0x130` (`main + 0x84360`), which passes
the job's builder `+0x8C0` to the manager's slot `+0xD0` at `main + 0x8445C`. Eight sites in the
steps of Pia's own session jobs
(`main + 0xCB0CC`-`0xCC738`; `nn::pia::session::LeaveMeshWithHostMigrationJob`, vtable
`main + 0x1CEB70`, `nn::pia::session::ProcessHostMigrationJob`, `main + 0x1CEBA0`,
`nn::pia::session::KickoutManageJob`, and the classes at construction slots
`main + 0x1D26F8`-`0x1D2728`) each gated by the job's state byte at `+0x90` read the holder at
`+0x80` (which is `[SessionProtocol + 0x130]`, the `Session`; live-verified) and call
`[holder + 0x30]`'s vtable slot `+0x130`; `[holder + 0x30]` is the `LocalFacade` (live typeinfo),
whose `+0x130` entry is `main + 0x8E0B4`.

The chain is gated on the wrapper's network state, and it is the leader-side path. The `swi 0x47`
body delivers only when the session is non-null, the byte at `component + 0x690` is set,
`component + 0x2770` is at least 10 and the session predicate `main + 0xB06BC` answers false
(`main + 0x5879C`-`0x587DC`). The byte at `+0x690` is the listener list's enabled flag: it is set at
`main + 0x53A58` only while `[component + 0x6A0] == [component + 0x6A4]` (the wrapper's scan and
join pair), and cleared by the tagged-property dispatcher's walk (`main + 0x4EBB0`, mode `-2`) and
by the teardown that writes `-1` into both. The delivery's own gates then compare two Pia address
structs in the manager: `X`'s slot `+0xD8` tails into `main + 0x95C90`, which requires both
`[manager + 0x1268]` and `[manager + 0x1288]` to pass `main + 0x74BE0` (a valid address) and to
compare equal in `main + 0x74C18` (the u16 at `+0x18`, then 0x10 bytes at `+8`); slot `+0xE8`
requires `[manager + 0x12D8]` to be zero. Those two structs hold the wrapper's local address
(`127.0.0.1` on the emulator) and the peer's (the host's IP), so the chain runs only while the
console is the leader of the network it is on. A joining console's record stays in the shadow; its
game data still reaches the parent through the session.

Confirmed live on the emulator in one frame, all eight hops, with a `swi 0x47` carrying version 5,
language 2, trainer id `0x1234`, activity `0x45` and the username `PKLDNTST`: the handler's shadow
took the 24 bytes; with the gate byte and the address pair poked equal, the session's
`main + 0xB1304` ran, the facade's `main + 0x8D4AC` took the stack builder (its app data carried the
30-character record text ``Z8J4;Vk.+>`.uN;#####<P?>######``), the manager's `main + 0x99C3C` and
its `+0x250` delegate's `main + 0xA28E4` passed it on, the job's `+0x60` validated it and copied the
`0x180`-byte area into the job's builder at `+0x8C0` (`main + 0x87578`), the job's `+0x130` ran from
the state machine, and the manager's blob builder `main + 0x80C3C` received the job's builder with
the same record text. The job itself runs as a state machine: its `+0x38`/`+0x40` hold
the current step (a vtable slot with a one-bit virtual flag, or a direct function) and the base
method `main + 0x6EAA0` ("ExecuteCore", the job's slot `+0x20`) dispatches it; the steps seen are
the vtable slots `0xB8`, `0xC8`, `0xD8`, `0xE8`, `0xF8`, `0x108`, `0x118`, `0x138`, `0x148` and
direct functions such as `main + 0x891F0`.

The manager class (`nn::pia::local::LdnProtocol`; vtable `main + 0x1CA5B0`, pointer formed at
`main + 0x7E244` from the relocated slot `main + 0x1D1E98`) keeps its own `NetworkInfo` at
`[manager + 0x2D8] + 0xB8`: the
advertise size is `NetworkInfo + 0x26A` (`+0x322`), the blob `NetworkInfo + 0x26C` (`+0x324`),
`NetworkInfo + 0x282` at `+0x33A`. Its method `main + 0x80C3C` (the only consumer of a builder's
app data; `main + 0xA2C70` has this one caller) zeroes `+0x380` (`NetworkInfo + 0x2C8`), copies
the app data there, sets the size to the app data plus `0x5C` at `+0x322`, writes the `0x5C`-byte
Pia system header at `+0x324` with the holder's own method (its vtable slot `+0x68`), and calls
`nn::ldn::SetAdvertiseData(holder + 0x324, size)` (PLT `main + 0x160A90`, GOT `0x1d3800`). Two
more manager methods advertise a second object's data (`main + 0x7F990`, `0x81140`: `[object +
0x18]`, the size its vtable slot `+0x38` plus `main + 0x8AC20`), and `main + 0x80EBC` rebuilds the
holder from `[manager + 0x128]` before advertising it.

`component + 0x2770` (through `[component + 0xD0]`) is read by `swi 0x53` (a boolean) and by
`main + 0x0511CC` and `main + 0x0511F4`, which no syscall reaches. `main + 0x0511F4` compares it with
10 and, at or past it, atomically loads a flag at `component + 0x2790`; a set flag enters
`main + 0x057250`'s continuation, which tests a third argument for null. Its caller is unidentified.

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
Pokedex flags, money XORed with the save's key. Every offset and bit index comes from the static
table; the one count the copied save supplies, `playerPartyCount` (a byte), bounds the party walk at
`main + 0x05AAE0`, and 255 entries of 0x64 bytes stay inside the 0xE000 copy. `swi 0x57` fills
`MonsSelect` (the starter, through
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

The path [main + 0x0571FC -> main + 0x057458]: the handler folds `r0`, requires `0x100` bytes
behind the fold, and copies the string into a `0x100`-byte stack buffer at frame `-0x100` (the
copy at `main + 0x85645F0` is bounded by its `w1 = 0x100` argument). The conversion to UTF-16
runs from that buffer into a `0x200`-byte buffer at `sp + 0x10` ([main + 0x855F100], `w2 =
0x200`), the profanity check runs through a global pointer [main + 0x574AC, callee `main +
0x86664C0`], and the masked string is copied back to the guest fold. Both buffers end inside
the dispatcher's own `0x310`-byte frame (`sp + 0x210` and `sp + 0x310`); the copy reaches
neither the saved registers nor past the frame. The replacement byte is the constant `0xA1`.

### The wrapper's own scan pipeline

The wrapper scans networks with `nn::ldn::Scan` through its own PLT (`main + 0x160B70`;
`ScanPrivate` at `main + 0x160B60`), from the manager object `x23` at the call sites
`main + 0x80944`/`0x8095C` with `w2 = 0x18` networks, into an inline array at
`manager + 0x14C0`, 24 entries x `0x480` (zero-filled once at init, `main + 0x7E290`).
The emulator's own ldn service casts the wire `ScanResponse` body into `NetworkInfo` without
a length check, so the other seat's field values reach the wrapper verbatim.

A consume loop (`main + 0x80A20..0x80B9C`) walks the array: it zeroes a `0x480`-byte record at
`sp + 0x128` (`main + 0x874A0`), converts the entry into it (`main + 0x87374`: one memcpy of
the whole `0x480` to `record + 0xB8`, then bit-precise field reads: source `+0xA`, `+0x11`
(a 15-byte integer parse, `main + 0xA9830`, hex/oct/dec/bin with `b`/`x` prefixes,
bound-checked at every advance), `+0x26A` (the advertise data size), `+0x281`/`+0x282`,
`+0x11A..0x11F`; stores to record `+0x90`, `+0xA0`, `+0xA2`, `+0xA4`, `+0xA6`, `+0xB0`), then
passes the record through a filter virtual and an accept virtual (`main + 0x80A88..0x80A94`).

The accepted networks land in the parent-candidate list: 16 slots x `0x1A` bytes at
`owner + 0x6050F2`, the write index at `owner + 0x605294` capped at 15 (`cmp w8, #0xf; b.le`
[main + 0x58C3C]); the array ends at `+0x605292`, tight against the index. The fill is the
owner class's (vtable `main + 0x1C3B30`) slot `+0xA0`, `main + 0x58BF8`, called per
scan-result station by `main + 0x536A4`; the station's name length comes from the station's
own virtual [slot `+0x50`], and `sub w8, w0, #1; cmp w8, #0x3f; b.hi` [main + 0x5364C] drops
`x6 > 0x40` before the call. Inside the fill, a `0x41`-byte stack buffer at `sp + 7` receives
`memcpy(sp + 7, x5, x6)` with the tail-zeroing memset skipped when `x6 > 0x40` [main +
0x58C68]: for `x6 > 0x40` the copy reaches the frame's saved `x29`/`x30` (buffer offsets
`0x59`/`0x61`). The one caller decoded clamps first, so the length through it is at most
`0x40`; of the image's eight sites loading a class's slot `+0xA0`, `main + 0x536A4` is the
one confirmed to dispatch on this class.

Measured on the emulated console, one host advertising: count 1, slot 0 = the host's
advertisement byte for byte: the 16-byte game data (activity `0x15`), the 8-byte display
name, the parent id u16 (`0x59f1`).

In `main` the list is written only through the fill family (`main + 0x58BB4`, `0x58BE4`,
`0x58BF8`), all virtual; every other component-anchored access in the image is a read. The
owner class's vtable pointer `main + 0x1C3B30` is formed in `main` by loading the relocated slot
`main + 0x1D1B38` (value `main + 0x1C3B20`) and adding `0x10`: `main + 0x58558` stores it while it
zeroes the candidate list at `component + 0x6050F0`, and `main + 0x58FD8`/`0x59054` in the two
component initializers. The same idiom forms the manager class's pointer (slot `main + 0x1D1E98`;
`main + 0x7E244`, `0x7E4D0`) and the session class's (slot `main + 0x1D2770`; `main + 0xB7D24`,
`0xB7E78`).

### The Pia session-message dispatcher

The wrapper's native Pia session receive is a type switch at `main + 0xB9FC0`. A chain of nodes is
walked: `[node + 0x10]` is the message body and its first byte is the type, while the node's own
three leading bytes are the protocol address used as the queue key. A node is dispatched
when the manager object's `[x0 + 0xA0]` is non-zero and the type is at most `0x11`, and the switch
is `adr x8, main + 0xB9FD0` (`main + 0xB9FCC`), `ldrb w9, [main + 0x180FC9 + type]` (`main +
0xB9FC4`; `adr x27, main + 0x180FC9` at `main + 0xB9EFC`), `add x8, x8, w9, lsl #2`, `br x8`. The
byte table at `main + 0x180FC9` has one entry per type; the eighteen case blocks sit at
`main + 0xB9FD0 + index * 4`, each ending in an unconditional `b main + 0xB9F80` and each calling
its handler (`main + 0xBCB60`, `main + 0xBE438`, `main + 0xBE8BC`, ...).

Each handler bounds its read against the message before touching it: the type-1 handler
`main + 0xBE438` opens `cmp w2, #0x15; b.ne` (only a `0x15`-byte message reaches the copy), and the
per-type tests the audit decoded are type 2 `>= 4`, type 3 `== 0x16 or 0x22`, type 4 `== 0xf`,
type 6 `>= 0xf`, type 9 `== 0x1e or 0x2a`, type 10 and 12 `== 0x15`, type 11 `>= 0xe`, type 13
`== 0xa`, type 14 `>= 0x4d`, type 17 `>= 0xd`. The variable-length reader `main + 0xC0D90` derives
its byte count from the bit count, compares it against the declared length, and refuses on short.
No handler in this set was found to copy a message-controlled length into a fixed buffer.

The types are the Pia session protocol's own message types; the host's session layer
(`pokeldn/ldn/pia_connect.py`) numbers them 0 join request, 1 join ack, 2 join response, 3 leave
request, 4 leave response, 5 update, 6 update ack, 7 start host migration, 8 migration ack. The
type-1 handler `main + 0xBE438` reads a 21-byte message as `[0]` type, `[1:9]` and `[9:0xB]` the
source station's constant id and variable id, `[0xB:0x13]` and `[0x13:0x15]` the destination's, and
refuses unless the destination pair matches the transport's own ([transport + 0x1B8], `+0x1C0`),
then looks the source station up and calls `main + 0xC9B4C` on it. The type-2 handler
`main + 0xBE8BC` accepts 4 bytes or more, gates on the manager's state byte (`+0x30 == 0xFD`),
and switches on message byte 3 over 3 to 0x10.

The receive path's owner is the session class (`nn::pia::session::SessionProtocol`; vtable base
`main + 0x1CE8E0`; its vtable pointer is
formed at `main + 0xB7D24`/`0xB7E78` from the relocated slot `main + 0x1D2770`, its constructor is
`main + 0xB7E70`). The pump is that class's vtable slot `+0x50`, `main + 0xB9CA0`, which calls the
walker `main + 0xB9DB0`; the chain hangs off the object at `[protocol + 0xF8]` (the session packet
reader, attached by the protocol manager) at its `+0x70` table (`main + 0xD6D68` returns that
address). Message objects are constructed by `main + 0xD4430` (its
vtable pointer comes from the relocated slot `main + 0x1D27B0`). The Pia library itself is
statically linked in `main` (the image carries `SDK MW+Nintendo+PiaCommon-6_42_1-Release` and the
session job names).

### The Pia library's own wire parsing

`main` links the whole Pia 6.42.1 stack (the image carries the `SDK MW+Nintendo+...` release
strings for `PiaCommon`, `PiaLocal`, `PiaNet`, `PiaSession`, `PiaTransport` and `Pia_ZStandard`,
plus the mangled class names). The classes described above by their vtables only are:

| earlier wording | class (mangled name at the vtable's typeinfo) | vtable |
| --- | --- | --- |
| the network manager | `nn::pia::local::LdnProtocol` | `main + 0x1CA5B0` |
| the session object (builder at `+0x8C0`) | `nn::pia::local::LdnBackgroundProcessJob` | `main + 0x1CAC48` |
| the session class (the receive path) | `nn::pia::session::SessionProtocol` | `main + 0x1CE8E0` |
| the packet object | `nn::pia::common::Packet::Header` | `main + 0x1CA100` |
| the local receive stream | `nn::pia::local::LocalInputStream` | `main + 0x1CA540` |
| the net receive stream | `nn::pia::net::NetInputStream` | `main + 0x1CC1D0` |

The transport classes' vtables are `PacketReader` `main + 0x1CF1A8` (a second at `main + 0x1CE7E8`),
`PacketWriter` `main + 0x1CF258`, `ProtocolManager` `main + 0x1CF3A0`, `ProtocolMessageReader`
`main + 0x1CF458`, `ProtocolMessageWriter` `main + 0x1CF490`, `ReliableProtocol` `main + 0x1CF4C8`,
`Station` `main + 0x1CF8C8`, `StationManager` `main + 0x1CF938`, `ReceiveThreadStream`
`main + 0x1CFB20`, `SendThreadStream` `main + 0x1CFB68`; the session classes' are `Session`
`main + 0x1CE300`, `SessionPacketReader` `main + 0x1CE748`, `SessionPacketWriter`
`main + 0x1CE7F8`, `SessionStation` `main + 0x1CED20`; the local classes' are `LocalProtocol`
`main + 0x1CA9B0`, `LocalService` `main + 0x1CB460`, `LocalFacade` `main + 0x1CB548`.

**The packet.** The packet object is `0x1D18` bytes: the parsed header at `+8` through `+0x24`, the
datagram buffer at `+0x30` (capacity `0x1C5C`, the bound in the append helpers `main + 0x75664`
and `main + 0x75694`, the second of which records a footer size at `+0x14`), the received size at
`+0x1C90` (the local receive path stores it at `main + 0x7DE40`, after a `0x5AC`-byte
receive and a check against that limit). Its parse (`main + 0x752D4`, vtable slot
`+0x18`; the entry `main + 0x752C8` supplies the object's own buffer and the constant `0x1C5C`)
requires more than `0x1C` bytes and reads the `0x1D`-byte header:

| at | size | meaning | lands at |
| --- | --- | --- | --- |
| 0x00 | 4 | magic `0x32AB9864`, big-endian | `+0x08` |
| 0x04 | 1 | version in bits 0-6, encrypted flag `0x80` | `+0x0C` |
| 0x05 | 1 | one byte, kept as sent | `+0x0D` |
| 0x06 | 2 | destination variable id, big-endian | `+0x0E` |
| 0x08 | 2 | source variable id, big-endian | `+0x10` |
| 0x0A | 2 | packet id, big-endian | `+0x12` |
| 0x0C | 1 | footer size | `+0x14` |
| 0x0D | 8 | nonce, as sent | `+0x15` |
| 0x15 | 8 | GCM tag, as sent | `+0x1D` |

The version this app speaks is `0x10` (16): the validity check `main + 0x75610` demands the magic,
`([+0xC] & 0x7F) == 0x10` and `size - 0x1D < 0x1C40`. The payload pointer is `+0x4D` (the buffer
past the header, `main + 0x75474`); `main + 0x75458` returns `buffer + t`, where
`t = (n + 0x1D)` in 32-bit arithmetic, or null when `(t >> 2) > 0x716`. This capacity
check allows `t` through `0x1C5B`; the message walker separately checks against the received
size minus the header and footer (`main + 0xDE278`).

**The socket and the receive stream.** The socket is a small holder (constructor `main + 0x6D93C`:
fd `-1` at `+0`, a count at `+4`, the family at `+8`, the protocol at `+0xC`); `main + 0x6D95C`
opens it (`nn::socket::Socket`, PLT `main + 0x160940`), `main + 0x6DBF4` closes it
(`main + 0x160950`), `main + 0x6DCD0` binds it (`main + 0x160960`), and `main + 0x6DE6C`,
`0x6DF44`, `0x6E00C`, `0x6E0F0` set options (`main + 0x160970`). The datagram calls are
`main + 0x6E1D0` (`nn::socket::RecvFrom`, PLT `main + 0x160980`, flags `0x80`, the source address
converted back by `main + 0x6E9D0`) and `main + 0x6E538` (`nn::socket::SendTo`,
`main + 0x160990`). The local receive stream (variable id at `+0x88`, a lock at `+0x68`, the
socket holder pointer at `+0x18`) runs the pump `main + 0x7DD10` (vtable slot `+0x10`): it receives
into a packet's buffer and parses the header into it (`main + 0x7DDEC`; `main + 0x6E1C8` is the
thunk); the packet filter `main + 0x91280` (slot `+0x20`) first requires a valid packet.
When the version is at least 7, the footer is non-empty and the destination variable id is
at most 1, the footer must contain at least two bytes, and the stream's own id (`+0x88`) must
be non-zero and appear among its big-endian u16 recipient ids (`footer_size >> 1` entries). Separately, when
`([+0xC] & 0x7E) >= 6` and the destination is 2 or more, it must equal the stream's own `+0x88`.

The filter forms the recipient pointer as `packet + (size - footer) + 0x30`, after `sub w8, w8, w9`
at `main + 0x912EC`; the message walker `main + 0xD6460` and the parser `main + 0xDE278` form the
walk bound as `size - footer - 0x1d` (`main + 0xD651C`, `main + 0xDE298`). Neither subtract is
gated on the footer size fitting the datagram. The footer size byte is datagram offset 12, in the
plaintext header, so a peer sets it freely. A footer size above the datagram size does not fault
the filter: six 31-byte datagrams with footer `0x40` reached the socket and the session ran on
(measured on the emulator).

**The threads.** The transport's receive and send loops are `nn::os` threads named "Pia
ReceiveThreadStream" (started at `main + 0xE9020`, the name via `adr` at `main + 0xE9034`) and "Pia
SendThreadStream" (`main + 0xEA758`), created through `main + 0xF6010` (`nn::os::CreateThread`,
PLT `main + 0x15FDF0`, and `StartThread`, `main + 0x15FE00`).

**From the wire to the session handlers.** A received session message is parsed by the session
packet reader and left in a per-address table that the session protocol walks each update.

`nn::pia::session::SessionPacketReader` (vtable `main + 0x1CE748`) inherits
`nn::pia::transport::PacketReader` (vtable `main + 0x1CF1A8`). The reader's `+0x30` method
(`main + 0xD5DE0`) processes received packets and calls `main + 0xD6460(reader, packet)`
to walk their messages. The walker starts at datagram offset `0x1D` and stops before
`packet_size - footer_size` (`main + 0xDE278`, `0xD6510`-`0xD6538`); the footer follows
the payload. It parses each message with `main + 0x74EA8` and takes the protocol address
used as the queue key through the reader's `+0x78` virtual (`main + 0xD6D0C`: the u16 at message
`+0x2C` with the byte at `+0x2E` as its high part) and calls
`main + 0xD6944(table, address, message)`.

The table is embedded at `reader + 0x70`: a u32 bucket count at `+0`, a pointer to the
bucket array at `+8` (0x18 bytes per bucket, the chain head at `+0`, the tail at `+8`)
and an optional hash callback at `+0x40`. `main + 0xD6944` loads the array pointer before
adding `index * 0x18`; the buckets are not inline in the table. The bucket
index is `callback(address) % count`, or `(address[0] + address[1] + address[2]) % count` when no
callback is set. `main + 0xD71F0(bucket, address, message)` takes a node, copies the message into
it (the three address bytes at `+0`, the body pointer at `+0x10`, the id at `+0x18`, more fields
at `+0x20` through `+0x30` and the rest through `main + 0x74C54`) and appends it to the bucket's
doubly-linked list (next at `+0x78`, previous at `+0x80`).

The protocol side: `nn::pia::session::SessionProtocol`'s `+0x50` virtual (`main + 0xB9CA0`) runs
`main + 0xB9DB0` every update. It reads `[protocol + 0xF8]` (the reader, attached as below), takes
the reader's table at `+0x70`, computes the bucket for the protocol's own three-byte address (the
u16 at `+0x120` with the byte at `+0x122`, read by the `+0x18` virtual `main + 0x828E4`; that pair
is a `nn::pia::transport::Protocol` field, set by `main + 0xDA614`), walks the chain and dispatches
each node by the first byte of the body at `[node + 0x10]` through the jump table to the handlers
(`main + 0xBCB60`, `main + 0xBE438`, `main + 0xBE8BC`, `main + 0xBF2D4`, and so on), passing
`(protocol, node, id)`.

The attach: the protocol manager (embedded at `+0xC8` of its owner, its protocol table at `+0x18`)
walks its table and sets every protocol's `+0xF0` and `+0xF8` from its owner's `+0xF8` and
`+0x100` (the setters `main + 0xDA8C8` and `main + 0xDA8D0`, the broadcast `main + 0xDB740`, called
with the pair at `main + 0xEC0E4`; it refuses either argument when zero). The `+0xF8` object is the
reader, which is why the walker's table is the reader's `+0x70`.

Live, the manager sits at `[session + 8] + 0xC8` (the owner above), and its table at
`[manager + 0x18]` has a u32 bucket count at `+0` and a bucket-array pointer at `+8`.
Each bucket is `0x18` bytes: `+0` is a node, the
node's `+8` is the protocol and the node's `+0x30` chains the next node. In the emulated session
the table had count `19` and exactly six protocols, one per kind, keyed by the protocol's address
(u16; the byte at `+0x122` is zero, and each protocol's `+0x108` holds the network's Pia var,
`0x8fa2`/`0x0766`): `0xfd01` `nn::pia::local::LdnProtocol`, `0xfd03`
`nn::pia::transport::RttProtocol`, `0xfd05` `nn::pia::transport::UnreliableProtocol`, `0xfd0a`
`nn::pia::transport::ReliableProtocol`, `0xfd0d` `nn::pia::session::SessionProtocol`, `0xfd0f`
`nn::pia::transport::MonitoringDataProtocol`. The protocols are one per kind, not per station:
the `SessionProtocol`'s pump traced the single instance 8 times out of 8, and reader-table nodes
were filed under the protocol address (`0xfd0a`, message id `0x60`). An instance is created and
registered by `main + 0xB1F60` (allocate `0xD8E8` bytes via `main + 0xDB114`, constructor
`main + 0xB7D0C`, insert into the manager's map keyed by the address pair); the Session's
constructor calls it once and stores the returned address at `+0x12`/`+0x14`.

The `nn::pia::transport::Protocol` base (vtable `main + 0x1CF308`, constructor `main + 0xDA548`,
vtable pointer from the relocated slot `main + 0x1D2808`) carries the three-byte address at
`+0x120`/`+0x122`, locks at `+0xC8`, the attached pair at `+0xF0`/`+0xF8`, two configured
8-byte-plus-u16 values at `+0x100`/`+0x108` and `+0x110`/`+0x118`, a state byte at `+0x123` and a
flag at `+0xD8`.

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

The readability check covers each scatter block. The blocks arrive end to end in one file;
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
ends. `expect` starts at 0, so a zero first word is credited to a run with an unwritten
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
the payload's image, 32 bytes of padding before the code; `--create-mon-destination ADDR` copies it
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
instead of going through the game's save code. The scratch is `gDecompressionBuffer + 0x400`, 0x400 above the
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

#### `shiny`, `shiny-press`, `ivs`, `noencounter`

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

`shiny-press` (`asm/resident/shiny-press.s`, 872 bytes) is the same source assembled with
`SHINY_PRESS`: no slow motion, `method=1`, and A pressed by the hook. On an idle frame whose countdown
is 0, while `callback1`/`callback2` are `CB1_Overworld`/`CB2_Overworld` and `sGlobalScriptContext`
(`0x03000FB0` on all twelve cartridges, the first literal of `ScriptContext_SetupScript`) has mode 2
and `nativePtr` `WaitForAorBPress` (the literal of `ScrCmd_waitbuttonpress`, `gScriptCmdTable[0x6D]`;
`0x0806F159` French), or runs no script (mode 0) while B is held, it stores a shim, found by `adr`,
in `callback1`. `ReadKeys` runs first in the next main-loop pass [main.c:81]; the shim puts
`CB1_Overworld` back, ORs A into `gMain.newKeys` and calls it. A waiting script returns at once [scrcmd.c:1313]; with no script, A talks to what the
player faces. Held B is no new press at a wait and does nothing standing still.

| Pokemon | the press that creates it | `offset` |
|---|---|---|
| Mewtwo | its `waitbuttonpress`; `setwildbattle` follows [CeruleanCave_B1F/scripts.inc:37] | 1 |
| Articuno, Zapdos, Moltres | the talk: `lock`, `faceplayer`, `setwildbattle`, then the wait | 2 |

`offset` counts calls from the hook's seed at the press frame to the one before the personality,
measured in mGBA on French FireRed (A held for one frame, three presses each, `tests/test_shiny.py`)
and run end to end with the app's payload while the player holds B: offsets 0 to 8 at Zapdos give
one shiny, at 2. With the table's offsets the app's payload gave all four shiny on seven cartridges:
French, English, Spanish and German FireRed, French, English and Italian LeafGreen. Japanese is
untried. A target whose countdown is odd when the game advances two calls a frame is skipped; the
next one is held.

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

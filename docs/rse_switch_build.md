---
title: The Switch build
parent: Ruby, Sapphire and Emerald
nav_order: 3
nav_exclude: true
search_exclude: true
app_exclude: true
---

# Emerald for the Switch FireRed application

The Switch build is pret/pokeemerald with pokefirered's `REVISION >= 0xA` changes ported, linked so
the FireRed/LeafGreen application's load-time patches land on Emerald's wireless driver. It runs in
place of a FireRed cartridge: on an emulated console it saves, receives Mystery Gift, trades and uses the Union
Room against pokeldn's hosts. `tools/rse/pokeemerald_switch.patch` is the port against pret commit
`731ad5bf`; `tools/rse/emerald_switch_build.py` applies and builds it.

## What the application requires of a cartridge

The English Switch FireRed ROM is pret/pokefirered's `make compare_firered_switch`
([The ROM map](frlg_rom_map.md#the-cartridge-image)); the port is the difference between that build and
REVISION 1, applied to Emerald's copies of the same files.

- **Syscalls.** The application serves `swi 0x40..0x62` (the Sloop calls,
  [Code on the console](frlg_rom.md)). `src/sloopsvc.c` is pokefirered's, unchanged: the wireless
  adapter calls (`0x42..0x53`), `WriteSector` (`0x48`), `ReplaceSector` (`0x56`), `FinishSave`
  (`0x4C`), parental controls (`0x54`), the bad-word filter (`0x4D`), `SetSaveBlock2` (`0x55`),
  `SetStarter` (`0x57`), `SetActivity` (`0x61`) and `IncrementLinkError` (`0x62`).
- **The save.** The application writes its flash image to storage only on `svc_FinishSave`. The
  build writes sectors through `svc_WriteSector`/`svc_ReplaceSector` and calls `svc_FinishSave` where
  pokefirered does: the end of `HandleSavingData`, the special save sectors, the last link-save sector.
- **The driver at fixed addresses.** At load the application patches three instructions at the
  cartridge's own `Sio32IDMain + 0x12E`, `IntrSIO32 + 8` and `IntrSIO32 + 0x71C`
  ([The breakpoint hooks](frlg_rom.md#the-breakpoint-hooks)). `ld_script_switch.ld` places
  `librfu_sio32id.o` and `librfu_intr.o` (`+0x30C`) in a `sloop_rfu` section at the cartridge's
  address; the code bytes are FireRed's apart from literal pointers and `bl` offsets.

| cartridge | `librfu_sio32id.o` | | cartridge | `librfu_sio32id.o` |
|---|---|---|---|---|
| BPRE | `0x081E2814` | | BPGE | `0x081E27F0` |
| BPRF | `0x081E1568` | | BPGF | `0x081E1544` |
| BPRD | `0x081E702C` | | BPGD | `0x081E7008` |
| BPRI | `0x081E0200` | | BPGI | `0x081E01DC` |
| BPRS | `0x081E28C8` | | BPGS | `0x081E28A4` |
| BPRJ | `0x081C66EC` | | BPGJ | `0x081C66C8` |

The Japanese addresses fall inside Emerald's `.text`; those two cartridges are not built.

## What the patch changes

Each change sits under `#if REVISION >= 0xA`, so `make compare` still matches pret's ROM.

| area | files |
|---|---|
| build | `Makefile` (`REVISION`, `SWITCH_CART`, the address table, `make emerald_switch`), `ld_script_switch.ld`, `sym_common.txt` |
| syscalls | `include/sloopsvc.h`, `src/sloopsvc.c` |
| adapter library and link manager | `librfu.h` (version 1028), `librfu_rfu.c`, `AgbRfu_LinkManager.{c,h}`: the svc calls, the longer periods, link recovery off |
| link layer | `link_rfu_2.c` (the rev10 timeouts, reseed, reload and soft reset on `svc_51`), `link_rfu_3.c` (ASCII tables), `link.c` (error screen, `HandleLinkConnection`) |
| Union Room | `union_room.c` (leader and join-group state machines, activity reporting, parental controls), `union_room_chat.c` and `naming_screen.c` (bad-word filter), `union_room_player_avatar.c`, `union_room_battle.c` |
| save | `save.c`, `load_save.c`, `main.c` (`svc_SetSaveBlock2`, black backdrop, no adapter wait on soft reset) |
| clock | `rtc.c` (a software clock when no GPIO port is attached, [The real-time clock](#the-real-time-clock)) |
| guards | `cable_club.c`, `trade.c`, `field_screen_effect.c`, `menu.c`, `task.c`, `wireless_communication_status_screen.c`, `mystery_gift_menu.c`, `battle_setup.c` (`svc_SetStarter`) |

Left out: pokefirered's intro colours, status-screen counts, link test removals, Hall of Fame tickets,
the berry fix, poison flash speed, multichoice default and `NDEBUG`. The trade keeps Emerald's five
post-trade standby rounds ([Trade](rse_link.md#trade)).

## Building

Needs pret/agbcc, arm-none-eabi binutils and a C preprocessor.

    ./.venv/bin/python tools/rse/emerald_switch_build.py --tree ~/pokeemerald_switch --agbcc ~/agbcc \
        --cart BPRE --cpp /opt/homebrew/bin/cpp-16 --compare

`--tree` is cloned when absent and checked out at the base commit. `--agbcc` runs agbcc's `install.sh`
into the tree. `--compare` also builds REVISION 0 and runs pret's sha1 check. The tool refuses a ROM
whose map places `librfu_sio32id.o` anywhere but the cartridge's address. Homebrew ships no
`arm-none-eabi-cpp`; `--cpp` names another.

From a fresh clone the BPRE build is sha1 `a6b7e67c3cab1225dba709503ad0ef974b9ae9d5` and the
REVISION 0 build passes `pokeemerald.gba: OK`.

## Running it

The application loads the ROM from its RomFS at every launch ([The ROM map](frlg_rom_map.md)), so a
LayeredFS file over that path replaces the cartridge until it is removed. `tools/rse/rom_mod.py`
installs one in an emulator's mod folder or on an Atmosphere SD card:

    ./.venv/bin/python tools/rse/rom_mod.py install pokeemerald_switch_BPRE.gba --title 0100554023408000 --data FOLDER
    ./.venv/bin/python tools/rse/rom_mod.py install pokeemerald_switch_BPRE.gba --title 0100554023408000 --sd /Volumes/SWITCH
    ./.venv/bin/python tools/rse/rom_mod.py remove --title 0100554023408000 --data FOLDER

The ROM must match the title's cartridge: BPRE for English FireRed (`0100554023408000`), BPRF for French
FireRed (`01004B3023412000`). The game keeps the title's save file name (`FireRed_e.sav`); both games
share it ([The FireRed copy](#the-firered-copy)).

On an emulated console (English FireRed, BPRE build) Emerald boots at 60 FPS, shows no dead-battery
message, saves, and loads the save after a relaunch. With the emulator's LDN pointed at the Mac the
hosts' `--over-ip` serves it ([Trade and the Union Room](rse_link.md), [Mystery Gift](rse_gift.md)).

## Test saves

The link features sit behind story flags. `tools/rse/emerald_save.py` edits the slot the game loads
and redoes the checksums ([The save](rse.md#the-save)):

    ./.venv/bin/python tools/rse/emerald_save.py FireRed_e.sav --link-ready --copy-party-mon 0

| flag | opens |
|---|---|
| `FLAG_SYS_POKEDEX_GET` `0x861` | the Pokemon Center 2F attendants |
| `FLAG_SYS_MYSTERY_GIFT_ENABLE` `0x8DB` | MYSTERY GIFT on the title menu |

`--link-ready` sets both and a continue warp to Oldale Town Pokemon Center 2F (map group 2, map 3,
x 5, y 4). `--copy-party-mon N` appends a copy of party slot N with a new PID, so a one-Pokemon save
can trade. The Pokedex flag shows the POKeDEX menu with no seen or caught entries.

Emerald loads a whole save from retail Emerald as it stands in the FireRed save file: on an emulated
console a 128 KB save with `FLAG_SYS_MYSTERY_GIFT_ENABLE` set showed its trainer, the MYSTERY GIFT
entry and its menu, and CONTINUE loaded the field. The software clock raised no battery message.

## Delivery without Atmosphere

A console running Atmosphere takes the ROM as a LayeredFS file ([Running it](#running-it)). A stock
console reads only the title's signed RomFS, so the ROM has to be written into the running ROM copy
from inside the game, each launch, through the same Mystery Gift native-code path the save transfer
uses ([Save backup and restore](frlg_gift.md#save-backup-and-restore)).

Three mechanisms are already measured and carry the design:

- `swi 0x48` with `r0 = 0xFA000 + n` (n in 0..0xFFF) writes 4 KB from a guest source into the ROM copy
  at `0x08000000 + n * 0x1000`, covering all 16 MB ([The flash sector path](frlg_rom.md#the-flash-sector-path)).
- Code written that way runs: a routine copied to `0x083FF000` executed when branched to
  [frlg_rom.md](frlg_rom.md#the-flash-sector-path).
- The save transfer streams compressed data across many Mystery Gift messages into a resident EWRAM
  block, inflates `0x800` bytes at a time and writes each sector, at about 1 KB of tokens per message
  ([Save backup and restore](frlg_gift.md#save-backup-and-restore)).

The ROM transfer is that pipeline with the write target changed from a flash sector (0..13) to a ROM
fold (`0xFA000 + n`) and a boot at the end instead of a save. The stream is redone at every launch
because the ROM copy is reloaded from RomFS at each application launch.

### The ROM transfer

`bin/frlg_mg_host.py --rom-transfer ROM` runs it (`pokeldn.frlg.gift.rom_transfer`,
`asm/rom-transfer.s`; `--rom-no-boot` stops after the check). A session:

1. installs the payload, which stops the m4a engine (`gSoundInfo.ident` and `SOUNDCNT_X` zeroed):
   the music otherwise reads song and wave data from the ROM being replaced;
2. hashes all 4096 blocks of the ROM copy (`h = rotl(h, 1) + word`, 32 blocks per frame; an XOR there hashed a 0x00 block and a 0xFF block alike, so a block of zeros over a block of 0xFF was never written);
3. writes every block whose hash differs from the image, 62 messages per acknowledgement, each block
   read back through the ROM window; a run of blocks of one byte goes as one fill message of up to
   eight blocks;
4. hashes all blocks again and compares;
5. sends the boot op: with `IME` and the four DMA channels off, the staged blocks move into place,
   the blocks past the image become `0xFF`, then `swi 0x00`.

The hash pass makes a cut session resumable within one application launch: the next session writes
only the blocks still different.

Measured on emulated English FireRed over the IP host: an image of FireRed with its three title
screen palettes recoloured (blocks `0xEAB`, `0xEAD`, `0xEAE`) wrote those 3 blocks in place, staged
151 live blocks at `0xEB1`, passed the check, and after the boot op the console restarted through the
intro to the recoloured title screen.

The whole Emerald build for BPRE has streamed and booted on emulated English FireRed: 3073 blocks in
place and 157 live blocks staged at `0xE3D`, 3,691,122 bytes of LZMA in 4268 messages (`--block-repeat
1 --inter-block-gap-frames 8`, messages cut at 10 frames of decoding), the check pass whole, the boot
op sent at 3 h 12 min, then Emerald's intro and its title screen in the FireRed application. Past
the title Emerald printed "The internal battery has run dry. The game can be played." and "However,
clock-based events will no longer occur.", then, on a build older than [The FireRed
copy](#the-firered-copy), a main menu offering CONTINUE on FireRed's save file (player name and play
time read back, 0 badges). Emerald loaded at launch through LayeredFS showed
no battery message ([The real-time clock](#the-real-time-clock)).

A stream ends when the console loses the first data block of a message. The console takes a block
only once it has read the one before [link_rfu_2.c:1146], and the header of the next
message lands while it still decodes the last one. On an emulated console, 2240 blocks in, the
console's frames to the host came 0.07 to 0.12 s apart four times in 0.6 s with the host still
sending. The client's receive buffer then held blocks 1 to 4 of the message at offsets 0 to 756 and
the next message's header at 1008. The CRC failed, `LinkRfu_FatalError` ran, and
`sLinkErrorBuffer` read `0x90000000` ([The emulator can close the link on its
own](frlg_link.md#the-emulator-can-close-the-link-on-its-own)). The disconnect frame followed 0.3 s
after that header. The host now counts its gaps in console frames received and leaves 24 frames
(`HEADER_GAP_FRAMES`) after a header that follows a busy message. With both, 3645 of 3645 blocks
went through in 3 h 13 min with no stop, the check pass was whole, and Emerald booted through its
intro to its title and main menu with no battery message, showing CONTINUE on the save (POKELDN,
137:40, 0 badges). Whether one of the two alone is enough is unmeasured.

The host encodes in a child process of the app (`pokeldn.frlg.gift.rom_transfer`, `--module`), since
a packaged app has no `multiprocessing`, and in a thread on a phone. With `--rom-base none` the host has
no cartridge and the stream is LZMA that names no block of the console's copy: 6,349,961 bytes for the
BPRE build against 3,350,357 from the cartridge in the same encoder and 11,842,749 uncompressed.

The decoder's own load is ruled out: the whole BPRE stream under unicorn
(`tools/rse/rom_stream_cost.py`) peaks at 102,765 instructions a call and no message outlasts its
quiet frames.

An Emerald save goes in before the stream, in the same application launch, with
`--save-restore-emerald FILE`. It writes the file's newest Emerald copy beside the running game's own
copy with the next counter, plus the four sectors past the slots (19 sectors, 7 to 9 minutes on an
emulated console), reads each one back, and stops. FireRed's load is skipped: its checksums fail on
Emerald's chunks and its save would overwrite the copy. A FILE from a console holding both games gives
its Emerald copy, whichever counter is higher.

The application holds the flash in memory and an emulated console's save file did not change after
the write, after leaving Mystery Gift, or when the emulator closed. A relaunch before the game saves
loses the written copy, so the stream follows in the same launch. Over GDB the flash held the file's
copy at counter 195 and FireRed's at 194; that image as the save file, with Emerald loaded at launch,
showed the file's trainer and the MYSTERY GIFT entry, and CONTINUE loaded the field.

A full stream after a save write has run on an emulated console with the build that keeps
[The FireRed copy](#the-firered-copy): 3645 of 3645 blocks in 3 h 14 min. Emerald booted, loaded the
written save and saved in game at counter 201, FireRed's copy stayed at counter 194, and a relaunch
of FireRed showed CONTINUE and MYSTERY GIFT.

An emulated stream needs the emulator's logging off. With Info logging and the log file on, the
emulator's process stopped for up to 1.03 s at a time, the host held frames (39 times in one stream)
and four of five streams ended in a link error between 1472 and about 3200 blocks. With both off, one stream
had 2 stalls over 0.15 s, the longest 0.17 s, 2 holds and no error. About 1980 stops of the process
for 0.26 to 0.56 s, forced with `tools/rse/stream_stall.py` from block 960 to block 2816, caused about
4000 holds and no error.

The same order runs on a retail Switch Lite with English FireRed over a XIAO ESP32S3 on firmware
1.9.3: the save backup, `--save-restore-emerald` (19 sectors in 390 s), then the stream with
`--block-repeat 1 --inter-block-gap-frames 8`, which wrote 3645 of 3645 blocks in 3 h 18 min with no
drop. Emerald booted, loaded the Emerald save and saved in game. The console's auto-sleep ends a stream
about 10 minutes after the last button press with error 2318-0314, with no RFU disconnect frame; the
game survived that, returned to its title and kept the blocks and the written save, FireRed printing
that the save file is corrupted before it loaded its own copy, and the next session resumed the stream.

### The FireRed copy

Both games use the same 32 sectors, the same footer and the same two 14-sector slots. Their chunks
differ at two ids:

| id | Emerald | FireRed, LeafGreen |
|---|---|---|
| 0 | `0xF2C` | `0xF24` |
| 4 | `0xF08` | `0xEE8` |

A FireRed sector's tail is zero, so a FireRed copy passes Emerald's checksums. An Emerald copy fails
FireRed's at id 4: `ResetWaldaWallpaper` fills `waldaPhrase.colors` at `0x3D70`, past FireRed's
SaveBlock1. A slot with one failing id is `SAVE_STATUS_ERROR`; a stock FireRed then prints "The save
file is corrupted." and "The previous save file will be loaded." and loads the other slot. With both
slots failing it prints "The save file has been deleted...", offers NEW GAME only and leaves the file
unchanged until a new game saves ([main_menu.c:232]). From there no Mystery Gift reaches the console.

Unpatched, Emerald alternates slots by `gSaveCounter % 2`, so its first save after
`--save-restore-emerald` lands on FireRed's slot. The build keeps that slot instead
(`sFireRedSlot` in `save.c`, `REVISION >= 0xA`):

- `GetSaveValidStatus` also checks each sector against FireRed's chunks. A slot passing all 14 counts
  as `SAVE_STATUS_EMPTY`, so Emerald never loads a FireRed copy; of two, the higher counter is the one
  kept.
- `gSaveCounter` skips that slot's parity at each increment, and starts on the other parity when no
  Emerald copy exists. Emerald's copy stays in one slot; `svc_FinishSave` writes the flash image
  whole, so a second Emerald copy adds no safety on this application.

Measured on an emulated console with English FireRed:

| chip before | what ran | chip after | next launch |
|---|---|---|---|
| Emerald in both slots | stock FireRed | unchanged | "The save file has been deleted...", NEW GAME only |
| FireRed 194, Emerald 195 | two saves in Emerald | FireRed 194 byte for byte, Emerald 199 | FireRed: both messages, then CONTINUE and MYSTERY GIFT; Emerald: CONTINUE on its save |
| FireRed 194 and 193 | Emerald, NEW GAME, one save | FireRed 194 byte for byte, Emerald 3 | Emerald: CONTINUE on the new game |

With no Emerald copy the menu offers NEW GAME and OPTION. A save in FireRed goes to the slot beside its
loaded copy and replaces Emerald's. `--save-restore-emerald` reads `gSaveCounter` from the running
game to find FireRed's slot: an Emerald copy can hold the chip's highest counter
(`asm/save-restore.s`, `sav.sectors_to_write`).

### Returning to FireRed

A relaunch of the application reloads FireRed from RomFS, but the save file may still hold Emerald's
sectors. FireRed then prints "The save file is corrupted." / "The previous save file will be loaded."
and takes the other slot when it is whole; when neither slot is whole it offers NEW GAME only, and
no Mystery Gift session can reach the console.

If the console is still running Emerald, `tools/rse/emerald_save_restore.py` runs a save restore from
Emerald's Mystery Gift. It builds `asm/save-restore.s` with a FinishSave stub: `swi 0x4C` commits the
whole 128 KiB flash image to `save:/`, and the stub returns 0 instead of `SAVE_STATUS_OK`, so the
Mystery Gift menu ends on a failure and the running game does not save over the restored image. The
payload reads Emerald's `gSaveCounter` (0x03006320 in the BPRE and BPRF builds), and the host
advertises as Emerald. Measured on the emulated French FireRed: a VBlank hook wrote sector 30 with
`0x5A` through `swi 0x48`, then called `swi 0x4C`; the save file changed and sector 30 read `0x5A`,
while the same write without `0x4C` stayed in the in-memory flash image. On the retail English
FireRed Lite running the Emerald BPRE build, the Emerald build's Mystery Gift -> Wonder Cards ->
Friend screen went black: the console associated with the host's Wi-Fi but never sent its LinkPlayer
block, so the retail FinishSave path is unverified.

The console is now back on FireRed with a fresh save. The old save is
`scratchpad/lite/lite_backup.sav` (GURVAN, TID 57189, SID 58811, 156h30m). Once Mystery Gift is
unlocked on FireRed, the ordinary restore writes, loads and saves it:

    bin/frlg_mg_host.py --save-restore scratchpad/lite/lite_backup.sav --live ...

### The ROM image

The ROM copy carries the application's three librfu patches ([The breakpoint
hooks](frlg_rom.md#the-breakpoint-hooks)), which the cartridge file lacks. The image is written with
the same patches applied at the cartridge's `librfu_sio32id.o` (`builds.SIO32ID`, offsets `+0x12E`,
`+0x314`, `+0xA28`; the cartridge bytes there checked on all twelve cartridges). An image whose bytes
there are not the cartridge's instructions is refused: the patches would land on other code.

### The LZMA stream

With `--rom-base` naming the console's own cartridge ROM, the blocks go as LZMA (lc 0, lp 0, pb 2,
`pokeldn.frlg.gift.rom_lzma`) instead of run and literal tokens. The dictionary is the console's
copy itself: a virtual position below 16 MB is the copy's byte, past it the stream's output. Every
block from 0 to the highest still to write is emitted, in an order the host writes to ROM blocks
`0xFFD` and `0xFFE` first: a pass with no availability limit records which copy blocks each block
copies from, and a block goes before any copy block it takes 8 bytes or more from (a topological
sort, highest block first). A match names a copy byte only while that block still holds what the
survey showed: not yet overwritten by the stream, a live block, or an untouched one. A match stops before a block it may not read, and a
literal after a match is coded against the byte the console holds there.

The decoder (`asm/rom-lzma.c`, 1768 bytes of Thumb built by clang) runs from ROM block `0xFFF`,
which the host writes first and the boot's fill clears with the order table. Its state, 6.9 KB with 5.2 KB of
probabilities, sits at `gDecompressionBuffer + 0x2000`. It decodes about a thousand bytes a frame
(at most 102,765 instructions a call under unicorn) and returns 0 until a message is consumed, so the
client calls it again the next frame. A finished block is written with `swi 0x48` and read back.
The host encodes in a worker process while one-block surveys keep the link busy.

The console drops a link block that arrives while it is still running the last message. The encoder
records the decoder's cost per stream byte (a symbol 6 units, a copied byte 1, 900 units a frame, which keeps every call of the ten Latin streams under 100,000 instructions);
a symbol decodes once the decoder holds its 20-byte lookahead, 25 bytes past the encoder's count, so
its work falls on the message that brings those. Each data message carries the frames of decoding it
causes plus 6 frames; the next message's header block may arrive during the decoding, its second
block only after. A few bytes of
stream for a long run of `0xFF` can decode for over a hundred frames.

| coding of Emerald for BPRE | bytes |
|---|---|
| runs and literals | 11,667,649 |
| runs and literals plus a copy token from any ROM byte still held (offline) | 9,081,120 |
| LZMA against the console's copy, descending order (57 chunks, encoded in 26 s) | 3,691,122 |
| the same in the reference order (offline) | 3,206,459 |
| LZMA with no availability limit, greedy (offline bound) | 3,027,095 |

### The live blocks

The session runs FireRed's own link and Mystery Gift code from the copy it overwrites. Those blocks
are written last: their new bytes go to staging blocks past both images (`0xEB1` to `0xFFF` on BPRE,
335 blocks) and the boot op moves them.

The set for English FireRed (BPRE) is 157 blocks, `pokeldn/frlg/data/rom_live_blocks.json`: the
functions an emulated session executes (216 million host-side samples of the GBA `pc` over a
transfer fall in 327 functions and 53 blocks), their direct callees, and the data their literal
pools name. With every other block of the copy filled with `0xFF`, an emulated English FireRed
session ran its writes and its check pass and printed its end message. Closing further over data
pointers reaches nearly the whole ROM (3380 blocks at two levels).

The other nine Latin cartridges carry BPRE's set by code matching (`tools/rse/live_blocks.py`): every
cartridge holds FireRed's code apart from `bl` offsets and pool pointers, so 32-byte windows of BPRE's
live blocks, with those words masked, are found in the cartridge, and each block moves by the shift its
windows land with. A window counts only when a neighbour lands with the same shift. Every function
address of the build table that the matched windows hold lands where the table puts it (29 of 29 on
each cartridge), and the method run on BPRE gives back its 157 blocks.

| cartridge | live blocks | | cartridge | live blocks |
|---|---|---|---|---|
| BPRE | 157 (measured) | | BPGE | 197 |
| BPRF | 212 | | BPGF | 212 |
| BPRD | 210 | | BPGD | 210 |
| BPRI | 209 | | BPGI | 209 |
| BPRS | 211 | | BPGS | 211 |

The decoder's live table (`asm/rom-lzma.c` `live[336]`) holds one entry per staging block; its state
ends below `0x02020000`, the end of `gDecompressionBuffer`. The Japanese cartridges are refused.

### Rates

Emulated English FireRed over the IP host: a full hash pass takes 120 s (0.6 s per 32-block answer);
a 1 KB data message takes 6.3 s (160 B/s); 2077 blocks as fill messages took 400 s. A 252-byte link
block costs about 80 frames at the default pacing: 21 fragments sent twice (`block_repeat`) and a
36-frame gap (`inter_block_gap_frames`), against one fragment per frame on the link.

Emerald (BPRE) is 14,929,764 bytes before its `0xFF` tail, 3645 sectors of 4 KB, and every one differs
from the FireRed Switch image's sector at the same offset, so no sector can be skipped. A message
carries 1012 token bytes (the 1 KiB link buffer less a 12-byte header):

| coding | stream | messages | decoder |
|---|---|---|---|
| the save transfer's runs and literals | 11,667,649 bytes | 14,566 | on the GBA side, tested |
| a copy/literal format with no entropy coding, matched against the whole FireRed image and Emerald's own output, byte-aligned tokens | 8,470,154 bytes | 8370 | none written |
| LZMA2, 64 KB window | 6,169,577 bytes | 6097 | none written |
| LZMA2, unbounded window | 5,747,728 bytes | 5680 | none written |
| LZMA2 with the FireRed image as its dictionary | 2,561,046 bytes | 2531 | none written |

DEFLATE's 32 KiB window cannot see across the two ROMs' 15 MB of shared library and engine code, so a
FireRed dictionary under `zlib` barely helps (6,991,630 bytes, against 6,975,681 with no dictionary at
all): the dictionary win is specific to a window the size of the ROM. A decoder's complexity does not
have to grow with that window: a copy token can name any 32-bit source address at no extra cost, so an
unbounded-window matcher needs the same dispatch-and-memcpy decoder as the save transfer's existing
one, just with a third token type. Measured against a hash-chain matcher (6 candidates, 5-byte key)
over the FireRed image and Emerald's own output, that format still trails LZMA2 by about 3.3 MB: most
of LZMA2's win past window size is its range coder packing short matches and literals into fractions of
a byte, which a byte-aligned format cannot do. Reaching the LZMA2 numbers needs a real entropy coder on
the GBA side, not just a bigger window. `tools/rse/emerald_switch_build.py` already carries a working
agbcc / arm-none-eabi toolchain for this exact target, so that decoder is better adapted from an
existing small LZMA or LZMA2 reference decoder in C and cross-compiled with it than hand-assembled from
nothing; none exists yet.

A retail restore over the board moved about 150 token bytes a second plus about 3.5 s a sector: 19
sectors took 107 s for 6182 token bytes and 249 s for 27,421, a 2-point fit, unconfirmed by a third run.
At that rate the stream is about 22 hours in the save transfer's coding, 16 hours under the
no-entropy-coding format, 11 hours under LZMA2 and 5 hours with the FireRed dictionary; 3645 sectors at
3.5 s add 3.5 hours on top of any of them if each sector keeps the restore's one-ack-per-sector round
trip. The restore now sends up to 62 data messages per acknowledgement
([Restore](frlg_gift.md#restore)), and the ROM transfer uses the same batches. The longest session measured so far lasted 269 s.

The boot writes the GBA SoftReset flag and runs `swi 0x00`: the BIOS jumps to the ROM reset vector at
`0x08000000` with RAM cleared, so Emerald's own `AgbMain` initialises from the bytes just written. A
BIOS SoftReset is in-core and is not an application launch, so a write to the ROM copy outlives it. The
rom-reset-probe payload (`asm/rom-reset-probe.s`) wrote `word[i] = 0x454D4552 + i` to ROM copy block
0xF00 (0x08F00000, in FireRed's `0xFF` tail), ran `swi 0x00`, and after the reboot a second Mystery
Gift session dumped 0x08F00000: all 16 words read back unchanged (English FireRed, emulated console, over the IP
host). The RomFS reload happens at an application launch, not a soft reset, so the written ROM survives
the boot into the new game.

### The real-time clock

The application emulates a cartridge GPIO port and an S-3511 clock, and attaches them only when the
ROM it loaded at launch is not FireRed or LeafGreen. The attach hook (`main + 0x056DD8`, slot `+0x40`
of the Sloop component's vtable `main + 0x1C3878`) reads the third letter of the game code from the
component's header copy: `G` or `R` skips the port, anything else builds it.

| what | where |
|---|---|
| header copy: `0xAC` to component `+0x55`, `0xBC` to `+0x5D` | `main + 0x05593C` to `main + 0x055950` |
| third letter test, `0x47` and `0x52` | `main + 0x056DF4` |
| port region installed over region `0x08` only, ROM pointer, size and mask copied from the plain object | `main + 0x056E20` to `main + 0x056E64` |
| region vtable | `main + 0x1C3978` |
| read 16 bits: `0xC8` enable, `0xC6` direction, `0xC4` data, served only while the enable is 1 | `main + 0x05610C` |
| write 16 bits: the same three offsets | `main + 0x05620C` |
| the clock's serial protocol: bit 0 clock, bit 1 data, bit 2 chip select, command prefix `0x60` | `main + 0x0351CC` |
| date source: `nn::time` calendar, BCD into the clock's registers | `main + 0x05EB90`, `main + 0x034CA8` |

A BIOS soft reset runs in the guest, so no host code looks at the new header. Emerald built with game
code `BPEE` and loaded at launch gets the port; streamed into a `BPRE` session it does not. Its GPIO
stores are then ordinary cartridge stores and its reads return ROM bytes, so `SiiRtcProbe` succeeds on
whatever those bytes give and `RtcCheckInfo` flags the date (`month == 0` is `RTC_ERR_INVALID_MONTH`
[rtc.c:174]), which `RTC_ERR_FLAG_MASK` turns into the dead-battery message [main_menu.c:717]. The
reads have not been observed under a debugger. Emerald loaded at launch with only its header's game
code changed to `BPRE` shows the dead-battery message on an emulated console, with no stream involved.

The date reaches the clock device only: `main + 0x05EB90` has five callers, four inside the device and
one in its setup (`main + 0x054A9C`). No syscall between `0x40` and `0x62` calls it, so a streamed ROM
has no way to read the console's time.

The build keeps a software clock for that case (`src/rtc.c`, under `REVISION >= 0xA`). `RtcInit` reads
`0x080000C8` after enabling it: a port reads back 1, a plain ROM reads its own 0. With no port, the raw
date is 1 January 2001 plus the save's play time, so it lives in the save with no new field and goes
back with an older save. A game day is 24 hours of play. The clock stops where play time stops, at
999:59:59, on 11 February 2001. With the port attached, the build reads the application's clock
as before.

| Emerald on an emulated console, loaded at launch | main menu |
|---|---|
| game code `BPEE`, no software clock | no message |
| game code `BPRE`, no software clock | dead-battery message |
| game code `BPRE`, software clock | no message |

Under unicorn, `RtcGetRawInfo` from the built ROM returned the expected date at seven play times and
`RtcCheckInfo` returned 0 at each. A stream of this build has not run.

## Unresolved

- A retail console has run only the build before [The FireRed copy](#the-firered-copy). On it FireRed's
  copy does not survive an Emerald save.
- The retail Emerald build's Mystery Gift -> Wonder Cards -> Friend screen goes black before the
  LinkPlayer block ([Returning to FireRed](#returning-to-firered)); the FinishSave restore has not
  run on retail.
- The live blocks of the error path. After a link error 2816 blocks into an emulated stream, A on
  the error screen gave a black screen: the way back to the title runs from overwritten blocks, so a
  cut stream restarts from a relaunch.
- What turns a logging stall into a link error. Forced stops of the same length caused none.
- A console session on a cartridge other than BPRE; their live blocks are carried by code matching.
- A build for the Japanese cartridges.

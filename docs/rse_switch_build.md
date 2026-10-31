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

From a fresh clone the BPRE build is sha1 `4e0a7e203e761cbb861ec65e98b31d6657083865` and the
REVISION 0 build passes `pokeemerald.gba: OK`.

## Running it

The application loads the ROM from its RomFS at every launch ([The ROM map](frlg_rom_map.md)), so a
LayeredFS file over that path replaces the cartridge until it is removed. `tools/rse/rom_mod.py`
installs one in an emulator's mod folder or on an Atmosphere SD card:

    ./.venv/bin/python tools/rse/rom_mod.py install pokeemerald_switch_BPRE.gba --title 0100554023408000
    ./.venv/bin/python tools/rse/rom_mod.py install pokeemerald_switch_BPRE.gba --title 0100554023408000 --sd /Volumes/SWITCH
    ./.venv/bin/python tools/rse/rom_mod.py remove --title 0100554023408000

The ROM must match the title's cartridge: BPRE for English FireRed (`0100554023408000`), BPRF for French
FireRed (`01004B3023412000`). The game keeps the title's save file name (`FireRed_e.sav`); an Emerald
save and a FireRed save cannot share it, so back the FireRed save up first.

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
2. hashes all 4096 blocks of the ROM copy (`h = rotl(h, 1) ^ word`, 32 blocks per frame);
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

The ROM copy carries the application's three librfu patches ([The breakpoint
hooks](frlg_rom.md#the-breakpoint-hooks)), which the cartridge file lacks. The image is written with
the same patches applied at the cartridge's `librfu_sio32id.o` (`builds.SIO32ID`, offsets `+0x12E`,
`+0x314`, `+0xA28`; the cartridge bytes there checked on all twelve cartridges). An image whose bytes
there are not the cartridge's instructions is refused: the patches would land on other code.

### The live blocks

The session runs FireRed's own link and Mystery Gift code from the copy it overwrites. Those blocks
are written last: their new bytes go to staging blocks past both images (`0xEB1` to `0xFFF` on BPRE,
335 blocks) and the boot op moves them.

The set for English FireRed (BPRE) is 157 blocks, `pokeldn/frlg/data/rom_live_blocks.json`: the
functions an emulated session executes (216 million host-side samples of the GBA `pc` over a
transfer fall in 327 functions and 53 blocks), their direct callees, and the data their literal
pools name. With every other block of the copy filled with `0xFF`, an emulated English FireRed
session ran its writes and its check pass and printed its end message. Closing further over data
pointers reaches nearly the whole ROM (3380 blocks at two levels). The other eleven cartridges have
no measured set and are refused.

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

## Unresolved

- Whether the application emulates the GPIO real-time clock Emerald reads. Emerald's main menu showed
  no dead-battery message on an emulated console.
- Whether a retail console runs the build: the emulated-console measurements are the only ones.
- The whole Emerald stream and the boot into it. The boot op has moved FireRed's own live blocks and
  restarted the game; Emerald has not been streamed.
- The live blocks of the error path: a session cut short returns to the menu through code outside
  the measured set.
- The live blocks of the eleven other cartridges.
- Whether a session lasting hours stays up.
- What FireRed does with the save file after Emerald has saved into it.
- A build for the Japanese cartridges.

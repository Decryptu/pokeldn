@ CLI_RUN_BUFFER_SCRIPT payload: write a 4 KB pattern into the ROM copy through the swi 0x48 fold,
@ then GBA-soft-reset, to settle whether a write to the ROM copy survives a soft reset
@ [docs/rse_switch_build.md, Delivery without Atmosphere].
@
@ THE QUESTION. The application reloads the ROM copy from the title's RomFS at every application
@ launch, so an Emerald streamed into the copy only lasts the launch it is written in. A full boot
@ needs a GBA SoftReset (swi 0x00) to re-enter the ROM reset vector with RAM cleared. A BIOS SoftReset
@ is in-core, not an application launch, so whether it keeps the written copy or reloads it is the one
@ unmeasured link. This writes a recognisable pattern to one fold, soft-resets, and a second Mystery
@ Gift session dumps the address: the pattern surviving means the delivery stands.
@
@ THE FOLD. swi 0x48 copies 0x1000 bytes from r1 into flash sector r0; with r0 = 0xFA000 + n the
@ destination folds into the ROM copy at 0x08000000 + n * 0x1000, from any guest source
@ [docs/frlg_rom.md, The flash sector path]. The source is a scratch in gDecompressionBuffer, filled
@ here so the bytes are ours: word[i] = fillbase + i over `words` words.
@
@ THE RESET. The BIOS SoftReset flag at 0x03007FFA selects the return target: 0 -> 0x08000000 (the ROM
@ reset vector), else 0x02000000 [GBATEK, BIOS Functions]. It is zeroed before swi 0x00 so control
@ returns to the ROM, which is FireRed except for the one written fold. swi 0x00 does not return.
@
@ Both swis go through a THUMB thunk in this image, the tested boundary [asm/flash-write.s].
@
@ Image, offsets from _start, patched by buffer_script.build_rom_reset_probe:
@   0x000  b .Lcode
@   0x004  sector      r0 for swi 0x48: 0xFA000 + n
@   0x008  source      r1 for swi 0x48: the EWRAM scratch base
@   0x00C  fillbase    word[0] of the pattern
@   0x010  words       pattern words, 1..0x400
@   0x014  reset_flag  &0x03007FFA, the byte zeroed before the reset
@   0x018  thunk48     swi 0x48 ; bx lr (THUMB)
@   0x01C  thunk00     swi 0x00 ; bx lr (THUMB), never returns

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lsector:   .word 0                 @ 0x004
.Lsource:   .word 0                 @ 0x008
.Lfillbase: .word 0                 @ 0x00C
.Lwords:    .word 0                 @ 0x010
.Lresetfl:  .word 0x03007FFA        @ 0x014
.Lthunk48:  .word 0x4770DF48        @ 0x018  swi 0x48 ; bx lr (THUMB)
.Lthunk00:  .word 0x4770DF00        @ 0x01C  swi 0x00 ; bx lr (THUMB)

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start

    @ Fill the scratch: word[i] = fillbase + i, i in 0..words-1.
    ldr     r5, [r4, #0x08]         @ source
    ldr     r6, [r4, #0x10]         @ words
    ldr     r0, [r4, #0x0C]         @ running value = fillbase
    mov     r2, #0                  @ index
.Lfill:
    cmp     r2, r6
    bhs     .Lfilled
    str     r0, [r5, r2, lsl #2]
    add     r0, r0, #1
    add     r2, r2, #1
    b       .Lfill
.Lfilled:

    @ swi 0x48 (r0 = sector, r1 = source) through the THUMB thunk.
    ldr     r0, [r4, #0x04]
    mov     r1, r5
    add     r7, r4, #0x18
    orr     r7, r7, #1              @ THUMB bit
    mov     lr, pc
    bx      r7

    @ Zero the SoftReset flag so the reset returns to 0x08000000, then swi 0x00.
    ldr     r0, [r4, #0x14]
    mov     r1, #0
    strb    r1, [r0]
    add     r7, r4, #0x1C
    orr     r7, r7, #1
    mov     lr, pc
    bx      r7                      @ swi 0x00: does not return

.Lcodeoff:
    .word   .Lcode - _start

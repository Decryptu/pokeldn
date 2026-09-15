@ CLI_RUN_BUFFER_SCRIPT payload: copy save flash into EWRAM with the CPU, then send the COPY.
@
@ Why the copy, rather than pointing the send at flash directly: pointing `client->link.sendBuffer`
@ at the flash region does not send flash. Measured twice, at two different addresses and two
@ different lengths, and the content that came back was identical both times and belonged to neither
@ sector [NOTES: the console's outgoing message cannot be pointed at flash]. So the send reads EWRAM
@ here, which is what memory-dump has carried dozens of times, and the only new thing is where the
@ bytes came from.
@
@ THE WINDOW IS 64 KiB AND THE CHIP IS 128 KiB. 0x0E000000..0x0E00FFFF is the whole aperture; a
@ 1 Mbit flash reaches it as two banks. Sector N lives at flash offset N * 0x1000, so it is bank
@ N / 16 at window address 0x0E000000 + (N % 16) * 0x1000. An address above the window does not
@ fault, it aliases: a read of 0x0E01E000 meaning sector 30 lands on 0x0E00E000 and returns sector
@ 14 of whichever bank is selected. On this save that is zeros, so the naive mistake returns a
@ plausible-looking wrong answer of exactly the shape a failed read has.
@
@ The bank select is the game's own, inlined rather than called [decomp:src/agb_flash.c
@ SwitchFlashBank, 0x081E0C74, seven instructions with no loop and no REG_WAITCNT]:
@
@     strb 0xAA -> 0x0E005555 ; strb 0x55 -> 0x0E002AAA ; strb 0xB0 -> 0x0E005555 ; strb bank -> 0x0E000000
@
@ Inlining it keeps this payload free of ROM calls entirely: no function whose side effects have to
@ be reasoned about, nothing executed off the stack, and REG_WAITCNT untouched.
@
@ READS ARE BYTE-WIDE. The SRAM/flash bus is 8 bits; a halfword or word load does not return two or
@ four flash bytes. `ldrb` is the only width that answers.
@
@ Image, offsets from _start, patched by buffer_script.build_flash_read:
@   0x000  b .Lcode
@   0x004  bank        the bank to select, 0 or 1
@   0x008  window      the window address to read from, 0x0E000000..0x0E00FFFF
@   0x00C  length      how many bytes to copy and send
@   0x010  scratch     the EWRAM buffer the copy lands in, and what the send is pointed at
@   0x014  cmd5555     0x0E005555
@   0x018  cmd2AAA     0x0E002AAA
@   0x01C  cmdbank     0x0E000000

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lbank:     .word 0                 @ 0x004
.Lwindow:   .word 0                 @ 0x008
.Llength:   .word 0                 @ 0x00C
.Lscratch:  .word 0                 @ 0x010
.Lcmd5555:  .word 0x0E005555        @ 0x014
.Lcmd2AAA:  .word 0x0E002AAA        @ 0x018
.Lcmdbank:  .word 0x0E000000        @ 0x01C

.Lcode:
    sub     ip, pc, #8
    push    {r0, r4, r5, r6, r7, lr}
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start

    @ Select the bank, the way the game does.
    ldr     r1, [r4, #0x14]
    mov     r2, #0xAA
    strb    r2, [r1]
    ldr     r3, [r4, #0x18]
    mov     r2, #0x55
    strb    r2, [r3]
    mov     r2, #0xB0
    strb    r2, [r1]
    ldr     r1, [r4, #0x1C]
    ldr     r2, [r4, #0x04]
    strb    r2, [r1]                @ bank

    @ Byte-copy the window into the scratch. ldrb is the only width the flash bus answers.
    ldr     r5, [r4, #0x08]         @ source, inside the window
    ldr     r6, [r4, #0x10]         @ destination in EWRAM
    ldr     r7, [r4, #0x0C]         @ length
    mov     r2, #0
.Lcopy:
    cmp     r2, r7
    bhs     .Lcopied
    ldrb    r3, [r5, r2]
    strb    r3, [r6, r2]
    add     r2, r2, #1
    b       .Lcopy
.Lcopied:

    @ Point the console's outgoing message at the COPY, never at flash.
    ldr     r3, [sp]                @ &client->param
    str     r6, [r3, #0x3C]         @ client->link.sendBuffer
    strh    r7, [r3, #0x34]         @ client->link.sendSize

    mov     r0, #1
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start

@ CLI_RUN_BUFFER_SCRIPT payloads: write a whole save over the chip, then load it [docs/frlg_gift.md,
@ Save backup and restore]. Ported from the GB-Link Team's cards/saverestore.s
@ (GB-Link/GB-Link-Switch-LDN, GPL-3.0). Sectors go through swi 0x48 [docs/frlg_rom.md, The flash
@ sector path] from a THUMB thunk in this image; LoadGameSave is a header word the host patches.
@
@ The first message is this whole image: `install` copies it to RESIDENT, past the 1 KiB the client
@ overwrites each time, and points the outgoing message at the footers (id, checksum, signature,
@ counter: 12 bytes at +0xFF4) of the chip's 28 save sectors, for the pass's CLI_SEND_LOADED.
@ Every later message starts with a branch to RESIDENT + 4, then holds:
@   +4  op: OP_DATA or OP_FINISH
@   OP_DATA:  +5 sector, +6 flags (bit 0: write it now), +8 u16 offset in the sector, +10 u16 token
@             bytes, +12 tokens filling STAGING from that offset (the coding of save-backup.s).
@             A write hands STAGING to swi 0x48 and reads the sector back through the window: a
@             sector that differs, or tokens that overflow STAGING, set its bit in the fail mask
@             (bit 31 for the tokens). The outgoing message is pointed at STATUS.
@   OP_FINISH: with no sector failed, LoadGameSave(SAVE_NORMAL) loads the save just written; STATUS
@             is the fail mask and the load result (0xFF when not loaded).
@
@ link.sendSize is at param + 0x34 and link.sendBuffer at param + 0x3C (struct MysteryGiftClient).
@
@ Image, offsets from _start:
@   0x000  b install
@   0x004  b entry           where a data message's branch lands, at RESIDENT + 4
@   0x008  load_game_save    LoadGameSave | 1 (builds.Build.load_game_save)

    .arm
    .text
    .global _start
    .equ DECOMPRESSION_BUFFER, 0x0201C000
    .equ MESSAGE, DECOMPRESSION_BUFFER
    .equ RESIDENT, DECOMPRESSION_BUFFER + 0x400
    .equ STAGING, DECOMPRESSION_BUFFER + 0x800
    .equ STATUS, DECOMPRESSION_BUFFER + 0x1800
    .equ FOOTERS, DECOMPRESSION_BUFFER + 0x1810
    .equ SAVE_SECTORS, 28
    .equ FOOTER, 0xFF4
    .equ SECTOR, 0x1000
    .equ OP_DATA, 1
    .equ OP_FINISH, 2
    .equ LINK_SEND_SIZE, 0x34
    .equ LINK_SEND_BUFFER, 0x3C

_start:
    b       install
    b       entry
load_game_save:
    .word   0

install:
    adr     r1, _start
    ldr     r2, resident
    ldr     r3, size
1:  ldr     ip, [r1], #4
    str     ip, [r2], #4
    subs    r3, r3, #4
    bne     1b
    ldr     r2, status
    mov     r3, #0
    str     r3, [r2]
    mov     r3, #0xFF
    str     r3, [r2, #4]

    push    {r4-r6, lr}
    mov     r6, r0
    ldr     r4, footers
    str     r4, [r6, #LINK_SEND_BUFFER]
    mov     r1, #SAVE_SECTORS * 12
    strh    r1, [r6, #LINK_SEND_SIZE]
    mov     r5, #0                          @ the sector
6:  mov     r2, r5, lsr #4
    bl      bank
    mov     r3, #0x0E000000
    and     r1, r5, #15
    add     r3, r3, r1, lsl #12
    add     r3, r3, #FOOTER & 0xF00
    add     r3, r3, #FOOTER & 0xFF
    mov     r2, #12
7:  ldrb    r0, [r3], #1
    strb    r0, [r4], #1
    subs    r2, r2, #1
    bne     7b
    add     r5, r5, #1
    cmp     r5, #SAVE_SECTORS
    blo     6b
    mov     r2, #0
    bl      bank
    mov     r0, #1
    pop     {r4-r6, lr}
    bx      lr

@ r0 param on entry. r4 tokens, r5 their end, r6 STAGING cursor, r7 its end.
entry:
    push    {r4-r10, lr}
    mov     r10, r0
    ldr     r8, message
    ldrb    r1, [r8, #4]
    cmp     r1, #OP_FINISH
    beq     finish
    cmp     r1, #OP_DATA
    bne     out

    ldr     r6, staging
    add     r7, r6, #SECTOR
    ldrh    r1, [r8, #8]
    add     r6, r6, r1
    add     r4, r8, #12
    ldrh    r1, [r8, #10]
    add     r5, r4, r1
token:
    cmp     r4, r5
    bhs     written
    ldrb    r1, [r4], #1
    cmp     r1, #0x80
    blo     2f
    sub     r2, r1, #0x80 - 3               @ a run
    ldrb    r1, [r4], #1
    add     r3, r6, r2
    cmp     r3, r7
    bhi     overflow
3:  strb    r1, [r6], #1
    subs    r2, r2, #1
    bne     3b
    b       token
2:  add     r2, r1, #1                      @ bytes as they are
    add     r3, r6, r2
    cmp     r3, r7
    bhi     overflow
4:  ldrb    r1, [r4], #1
    strb    r1, [r6], #1
    subs    r2, r2, #1
    bne     4b
    b       token

overflow:
    mov     r1, #0x80000000
    b       failed

written:
    ldrb    r1, [r8, #6]
    tst     r1, #1
    beq     out
    ldrb    r9, [r8, #5]                    @ the sector
    mov     r0, r9
    ldr     r1, staging
    adr     r3, write_sector + 1
    bl      call
    @ Read it back.
    mov     r2, r9, lsr #4
    bl      bank
    mov     r3, #0x0E000000
    and     r1, r9, #15
    add     r3, r3, r1, lsl #12
    ldr     r6, staging
    mov     r2, #SECTOR
    mov     r4, #0
5:  ldrb    r0, [r3], #1
    ldrb    r1, [r6], #1
    eor     r0, r0, r1
    orr     r4, r4, r0
    subs    r2, r2, #1
    bne     5b
    mov     r2, #0
    bl      bank                            @ bank 0 again, as the game leaves it
    cmp     r4, #0
    beq     report_status
    mov     r1, #1
    mov     r1, r1, lsl r9
failed:
    ldr     r2, status
    ldr     r3, [r2]
    orr     r3, r3, r1
    str     r3, [r2]
report_status:
    ldr     r4, status
    b       report

finish:
    ldr     r4, status
    ldr     r1, [r4]
    cmp     r1, #0
    bne     report
    mov     r0, #0                          @ SAVE_NORMAL
    ldr     r3, load_game_save
    bl      call
    str     r0, [r4, #4]
report:
    str     r4, [r10, #LINK_SEND_BUFFER]
    mov     r1, #8
    strh    r1, [r10, #LINK_SEND_SIZE]

out:
    mov     r0, #1
    pop     {r4-r10, lr}
    bx      lr

@ Calls the game's Thumb routine at r3 with r0, r1. A Thumb routine may return
@ with pop {pc}, which stays in Thumb, so it returns to the Thumb half of this
@ call, which bx's back.
call:
    adr     ip, thumb_call + 1
    bx      ip
    .thumb
    .align  1
thumb_call:
    push    {lr}
    bl      1f
    pop     {r3}
    bx      r3
1:  bx      r3
    .arm
    .align  2

@ swi 0x48: r0 the sector, r1 the 4 KiB source; it returns no register.
    .thumb
    .align  1
write_sector:
    swi     0x48
    bx      lr
    .arm
    .align  2

@ Selects bank r2. Uses r0, r1 and ip.
bank:
    ldr     r0, command_5555
    ldr     ip, command_2aaa
    mov     r1, #0xAA
    strb    r1, [r0]
    mov     r1, #0x55
    strb    r1, [ip]
    mov     r1, #0xB0
    strb    r1, [r0]
    mov     r0, #0x0E000000
    strb    r2, [r0]
    bx      lr

resident:
    .word   RESIDENT
size:
    .word   end - _start
message:
    .word   MESSAGE
staging:
    .word   STAGING
status:
    .word   STATUS
footers:
    .word   FOOTERS
command_5555:
    .word   0x0E005555
command_2aaa:
    .word   0x0E002AAA
end:

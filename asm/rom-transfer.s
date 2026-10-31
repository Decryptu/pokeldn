@ CLI_RUN_BUFFER_SCRIPT payloads: write a ROM image into the running ROM copy, then boot it
@ [docs/rse_switch_build.md, Delivery without Atmosphere]. The data path is asm/save-restore.s with
@ the write target the ROM fold (swi 0x48, r0 = 0xFA000 + n) and the read-back the ROM window.
@
@ The first message is this whole image: `install` copies it to RESIDENT, stops the sound engine
@ (its song and wave data are ROM the stream overwrites) and answers STATUS.
@ Every later message starts with a branch to RESIDENT + 4, then holds:
@   +4  op
@   OP_DATA (1):   +5 flags (bit 0: write it now), +6 u16 sector n, +8 u16 offset in it, +10 u16
@                  token bytes, +12 tokens filling STAGING (the coding of asm/save-backup.s). A
@                  write goes to 0x08000000 + n * 0x1000 and is read back. Answers STATUS.
@   OP_SURVEY (3): +6 u16 first sector, +8 u16 count, +10 u16 sectors per run, +12 u32 tag. Each
@                  run hashes the next sectors from where the last run with that tag stopped and
@                  answers one word per sector: h = rotl(h, 1) ^ word over the sector's words.
@   OP_FILL (5):   +5 the byte, +6 u16 first sector, +8 u16 count: each sector written with the
@                  byte and read back. Answers STATUS.
@   OP_LZ_START (6), OP_LZ_DATA (7): handed to the LZMA decoder (asm/rom-lzma.c), which the host
@                  writes to ROM block 0xFFF first; its return value goes back to the client, so a
@                  message it has not finished is called again next frame. Answers STATUS.
@   OP_BOOT (4):   +6 u16 count, +8 u16 first staged sector, +10 u16 first fill sector, +12 u16
@                  fill count, +16 u16 sector[count]. With interrupts and DMA off, staged sector
@                  first + i goes to sector[i], the fill sectors become 0xFF, then SoftReset into
@                  0x08000000. It does not return.
@
@ Image: 0x000 b install, 0x004 b entry (RESIDENT + 4), 0x008 &gSoundInfo (0: leave the sound).
@
@ STATUS: +0 sectors that read back wrong, +4 the first of them (0xFFFFFFFF: none), +8 token runs
@ that overflowed STAGING. link.sendSize is at param + 0x34, link.sendBuffer at param + 0x3C.

    .arm
    .text
    .global _start
    .equ DECOMPRESSION_BUFFER, 0x0201C000
    .equ MESSAGE, DECOMPRESSION_BUFFER
    .equ RESIDENT, DECOMPRESSION_BUFFER + 0x400
    .equ STAGING, DECOMPRESSION_BUFFER + 0x800
    .equ STATUS, DECOMPRESSION_BUFFER + 0x1800
    .equ HASHES, DECOMPRESSION_BUFFER + 0x1C00
    .equ STATUS_SIZE, 12
    .equ SURVEY_TAG, 0x10
    .equ SURVEY_AT, 0x14
    .equ SURVEY_LEFT, 0x18
    .equ SECTOR, 0x1000
    .equ ROM, 0x08000000
    .equ OP_DATA, 1
    .equ OP_SURVEY, 3
    .equ OP_BOOT, 4
    .equ OP_FILL, 5
    .equ OP_LZ_START, 6
    .equ OP_LZ_DATA, 7
    .equ REG_SOUNDCNT_X, 0x84
    .equ LINK_SEND_SIZE, 0x34
    .equ LINK_SEND_BUFFER, 0x3C

_start:
    b       install
    b       entry
sound_info:
    .word   0

install:
    push    {r4, lr}
    mov     r4, r0
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
    mvn     r1, #0
    str     r1, [r2, #4]
    str     r3, [r2, #8]
    str     r3, [r2, #SURVEY_TAG]           @ the host never uses tag 0
    ldr     r1, sound_info
    cmp     r1, #0
    strne   r3, [r1]                        @ gSoundInfo.ident: SoundMain returns at once [m4a]
    movne   r1, #0x04000000
    strneh  r3, [r1, #REG_SOUNDCNT_X]       @ master sound off; m4aSoundInit turns it back on
    str     r2, [r4, #LINK_SEND_BUFFER]
    mov     r1, #STATUS_SIZE
    strh    r1, [r4, #LINK_SEND_SIZE]
    mov     r0, #1
    pop     {r4, lr}
    bx      lr

@ r0 param on entry. r4 tokens, r5 their end, r6 STAGING cursor, r7 its end.
entry:
    push    {r4-r11, lr}
    mov     r10, r0
    ldr     r8, message
    ldrb    r1, [r8, #4]
    cmp     r1, #OP_DATA
    beq     data
    cmp     r1, #OP_SURVEY
    beq     survey
    cmp     r1, #OP_BOOT
    beq     boot
    cmp     r1, #OP_FILL
    beq     fill
    cmp     r1, #OP_LZ_START
    beq     lz
    cmp     r1, #OP_LZ_DATA
    beq     lz
    b       out

data:
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
    ldr     r2, status
    ldr     r3, [r2, #8]
    add     r3, r3, #1
    str     r3, [r2, #8]
    b       report_status

written:
    ldrb    r1, [r8, #5]
    tst     r1, #1
    beq     out
    ldrh    r9, [r8, #6]                    @ the sector
    bl      put
    b       report_status

lz:
    mov     r0, r8
    ldr     r3, lz_entry
    bl      call
    mov     r5, r0
    ldr     r4, status
    str     r4, [r10, #LINK_SEND_BUFFER]
    mov     r1, #STATUS_SIZE
    strh    r1, [r10, #LINK_SEND_SIZE]
    mov     r0, r5
    pop     {r4-r11, lr}
    bx      lr

fill:
    ldrb    r0, [r8, #5]
    orr     r0, r0, r0, lsl #8
    orr     r0, r0, r0, lsl #16
    ldr     r4, staging
    mov     r2, #SECTOR
1:  str     r0, [r4], #4
    subs    r2, r2, #4
    bne     1b
    ldrh    r9, [r8, #6]
    ldrh    r11, [r8, #8]
2:  subs    r11, r11, #1
    bmi     report_status
    bl      put
    add     r9, r9, #1
    b       2b

@ Writes STAGING to sector r9 and reads it back through the ROM window; a mismatch counts in STATUS.
@ Uses r0-r4 and r6.
put:
    push    {lr}
    ldr     r0, fold
    add     r0, r0, r9
    ldr     r1, staging
    adr     r3, write_sector
    orr     r3, r3, #1                      @ Thumb
    bl      call
    mov     r3, #ROM
    add     r3, r3, r9, lsl #12
    ldr     r6, staging
    mov     r2, #SECTOR
    mov     r4, #0
5:  ldr     r0, [r3], #4
    ldr     r1, [r6], #4
    eor     r0, r0, r1
    orr     r4, r4, r0
    subs    r2, r2, #4
    bne     5b
    cmp     r4, #0
    beq     6f
    ldr     r2, status
    ldr     r3, [r2]
    add     r3, r3, #1
    str     r3, [r2]
    ldr     r3, [r2, #4]
    cmn     r3, #1
    streq   r9, [r2, #4]
6:  pop     {lr}
    bx      lr

report_status:
    ldr     r4, status
    mov     r1, #STATUS_SIZE
report:                                     @ r4 the buffer, r1 its size
    str     r4, [r10, #LINK_SEND_BUFFER]
    strh    r1, [r10, #LINK_SEND_SIZE]
out:
    mov     r0, #1
    pop     {r4-r11, lr}
    bx      lr

survey:
    ldr     r2, status
    ldr     r1, [r8, #12]                   @ the tag
    ldr     r3, [r2, #SURVEY_TAG]
    cmp     r1, r3
    beq     1f
    str     r1, [r2, #SURVEY_TAG]           @ a new survey starts at its first sector
    ldrh    r3, [r8, #6]
    str     r3, [r2, #SURVEY_AT]
    ldrh    r3, [r8, #8]
    str     r3, [r2, #SURVEY_LEFT]
1:  ldrh    r5, [r8, #10]
    ldr     r3, [r2, #SURVEY_LEFT]
    cmp     r5, r3
    movhi   r5, r3                          @ the sectors this run
    sub     r3, r3, r5
    str     r3, [r2, #SURVEY_LEFT]
    ldr     r6, [r2, #SURVEY_AT]
    add     r3, r6, r5
    str     r3, [r2, #SURVEY_AT]
    ldr     r4, hashes
    mov     r7, r4
    mov     r11, r5
2:  subs    r11, r11, #1
    bmi     4f
    mov     r3, #ROM
    add     r3, r3, r6, lsl #12
    add     r6, r6, #1
    mov     r0, #0
    mov     r2, #SECTOR
3:  ldmia   r3!, {r1, r9}
    eor     r0, r1, r0, ror #31
    eor     r0, r9, r0, ror #31
    subs    r2, r2, #8
    bne     3b
    str     r0, [r7], #4
    b       2b
4:  mov     r1, r5, lsl #2
    b       report

boot:
    mov     r0, #0x04000000
    mov     r2, #0
    add     r1, r0, #0x200
    strh    r2, [r1, #8]                    @ REG_IME
    strh    r2, [r0, #0xBA]                 @ DMA0CNT_H .. DMA3CNT_H
    strh    r2, [r0, #0xC6]
    strh    r2, [r0, #0xD2]
    strh    r2, [r0, #0xDE]
    ldrh    r5, [r8, #6]
    ldrh    r6, [r8, #8]
    add     r7, r8, #16
1:  subs    r5, r5, #1
    bmi     2f
    ldrh    r9, [r7], #2
    ldr     r0, fold
    add     r0, r0, r9
    mov     r1, #ROM
    add     r1, r1, r6, lsl #12
    add     r6, r6, #1
    adr     r3, write_sector
    orr     r3, r3, #1                      @ Thumb
    bl      call
    b       1b
2:  ldr     r4, staging
    mvn     r0, #0
    mov     r2, #SECTOR
3:  str     r0, [r4], #4
    subs    r2, r2, #4
    bne     3b
    ldrh    r5, [r8, #12]
    ldrh    r6, [r8, #10]
4:  subs    r5, r5, #1
    bmi     5f
    ldr     r0, fold
    add     r0, r0, r6
    add     r6, r6, #1
    ldr     r1, staging
    adr     r3, write_sector
    orr     r3, r3, #1                      @ Thumb
    bl      call
    b       4b
5:  ldr     r0, reset_flag                  @ 0: SoftReset returns to 0x08000000 [GBATEK]
    mov     r1, #0
    strb    r1, [r0]
    adr     r3, soft_reset
    orr     r3, r3, #1                      @ Thumb
    bl      call
    b       .

@ Calls the Thumb routine at r3 with r0, r1 [asm/save-restore.s].
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

    .thumb
    .align  1
write_sector:
    swi     0x48
    bx      lr
soft_reset:
    swi     0x00
    bx      lr
    .arm
    .align  2

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
hashes:
    .word   HASHES
fold:
    .word   0xFA000
reset_flag:
    .word   0x03007FFA
lz_entry:
    .word   0x08FFF001                      @ the decoder in ROM block 0xFFF, Thumb
end:

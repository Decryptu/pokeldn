@ CLI_RUN_BUFFER_SCRIPT payload: send the whole 128 KiB save chip, compressed, one message per pass of
@     CLI_LOAD_TOSS_RESPONSE, CLI_RUN_BUFFER_SCRIPT, CLI_SEND_LOADED
@ [docs/frlg_gift.md, Save backup and restore]. Ported from the GB-Link Team's cards/savebackup.s
@ (GB-Link/GB-Link-Switch-LDN, GPL-3.0); the build addresses are header words the host patches.
@
@ Client_RunBufferScript calls it as u32 (*)(u32 *param, SaveBlock2 *, SaveBlock1 *) until it returns
@ 1, re-copying the image every pass [decomp:src/mystery_gift_client.c:238,276]. The chip offset read
@ so far lives in *param as MAGIC << 24 | offset; a param without MAGIC is the first pass, which starts
@ at `first`, so a backup cut short goes on where it stopped.
@
@ A message holds up to 1 KiB of tokens for at most READ_LIMIT chip bytes and never crosses a bank:
@ n < 0x80 is followed by n + 1 literal bytes; n >= 0x80 by one byte repeated n - 0x80 + 3 times. Past
@ the end a pass leaves CLI_LOAD_TOSS_RESPONSE's 4-byte word armed, which the host ignores.
@
@ The chip is a 64 KiB window at 0x0E000000, two banks, read a byte at a time [docs/frlg_rom.md,
@ Reading flash]. A pass first stages its stretch into STAGE, STEP bytes a frame (returning 0), with
@ the count in STATE: 8 KiB read in one frame stalls the game past what its link survives.
@
@ Each lost fragment is queued again on top of every frame's send, and gRfu.sendQueue (40 commands)
@ drains only while nothing is sent; a pass waits for it to empty, or a lossy link overflows it.
@
@ link.sendSize is at param + 0x34 and link.sendBuffer at param + 0x3C (struct MysteryGiftClient).
@
@ Image, offsets from _start, patched by pokeldn.frlg.gift.save_transfer:
@   0x000  b code
@   0x004  first       the chip offset the first pass starts at
@   0x008  send_queue  &gRfu.sendQueue.count (builds.Build.rfu_send_queue)

    .arm
    .text
    .global _start
    .equ DECOMPRESSION_BUFFER, 0x0201C000
    .equ SCRATCH, DECOMPRESSION_BUFFER + 0x400
    .equ STAGE, DECOMPRESSION_BUFFER + 0x800
    .equ STATE, DECOMPRESSION_BUFFER + 0x2800
    .equ MESSAGE, 0x400
    .equ CHIP, 0x20000
    .equ READ_LIMIT, 0x2000
    .equ STEP, 0x800
    .equ MAGIC, 0x5A
    .equ LINK_SEND_SIZE, 0x34
    .equ LINK_SEND_BUFFER, 0x3C

@ r0 param, r1 offset, r5 stretch length; then r4 read cursor in STAGE, r5 its
@ end, r6 write cursor, r7 write end, r8 such that offset = r4 + r8.
_start:
    b       code
first:
    .word   0
send_queue:
    .word   0

code:
    ldr     r2, send_queue
    ldrb    r2, [r2]
    cmp     r2, #0
    movne   r0, #0
    bxne    lr
    push    {r4-r10, lr}
    ldr     r9, state
    ldr     r1, [r0]
    mov     r2, r1, lsr #24
    cmp     r2, #MAGIC
    ldrne   r1, first                       @ the first pass: nothing staged
    movne   r3, #0
    strne   r3, [r9]
    bic     r1, r1, #0xFF000000
    cmp     r1, #CHIP
    bhs     finished

    mov     r3, r1, lsr #16
    add     r3, r3, #1
    mov     r3, r3, lsl #16                 @ the bank's end
    sub     r5, r3, r1
    cmp     r5, #READ_LIMIT
    movhi   r5, #READ_LIMIT
    ldr     r10, [r9]                       @ staged so far
    cmp     r10, r5
    bhs     staged
    sub     r6, r5, r10
    cmp     r6, #STEP
    movhi   r6, #STEP
    mov     r2, r1, lsr #16
    bl      bank
    mov     r3, #0x0E000000
    mov     ip, r1, lsl #16
    add     r3, r3, ip, lsr #16
    add     r3, r3, r10                     @ the next byte to stage, in the window
    ldr     ip, stage
    add     ip, ip, r10
    add     r10, r10, r6
    str     r10, [r9]
1:  ldrb    r7, [r3], #1
    strb    r7, [ip], #1
    subs    r6, r6, #1
    bne     1b
    mov     r2, #0
    bl      bank                            @ bank 0 again, as the game leaves it
    orr     r1, r1, #MAGIC << 24
    str     r1, [r0]                        @ the next call is this pass's too
    mov     r0, #0                          @ again next frame
    pop     {r4-r10, lr}
    bx      lr

staged:
    mov     r3, #0
    str     r3, [r9]                        @ the next pass stages anew
    ldr     r6, scratch
    str     r6, [r0, #LINK_SEND_BUFFER]
    add     r7, r6, #MESSAGE
    ldr     r4, stage
    add     r5, r4, r5
    sub     r8, r1, r4

token:
    cmp     r4, r5
    bhs     read
    @ A run of the byte at r4: r2 its length, at most 130.
    ldrb    r9, [r4]
    mov     r2, #1
1:  add     r3, r4, r2
    cmp     r3, r5
    bhs     2f
    ldrb    r10, [r3]
    cmp     r10, r9
    bne     2f
    add     r2, r2, #1
    cmp     r2, #130
    blo     1b
2:  cmp     r2, #3
    blo     literal
    add     r3, r6, #2
    cmp     r3, r7
    bhi     read
    sub     r3, r2, #3
    orr     r3, r3, #0x80
    strb    r3, [r6], #1
    strb    r9, [r6], #1
    add     r4, r4, r2
    b       token

@ Bytes as they are, up to the next run of three, at most 128, and as many as
@ the message has room for after the count.
literal:
    sub     r3, r7, r6
    subs    r3, r3, #1
    bls     read                            @ no room for a byte after the count
    cmp     r3, #128
    movhi   r3, #128
    mov     r2, #0                          @ r2 bytes taken
    add     r10, r6, #1
3:  add     ip, r4, r2
    cmp     ip, r5
    bhs     5f
    cmp     r2, #0
    beq     4f
    @ Stop where a run of three starts.
    add     lr, ip, #2
    cmp     lr, r5
    bhs     4f
    ldrb    r9, [ip]
    ldrb    lr, [ip, #1]
    cmp     lr, r9
    ldreqb  lr, [ip, #2]
    cmpeq   lr, r9
    beq     5f
4:  ldrb    r9, [ip]
    strb    r9, [r10], #1
    add     r2, r2, #1
    cmp     r2, r3
    blo     3b
5:  sub     r3, r2, #1
    strb    r3, [r6]
    mov     r6, r10
    add     r4, r4, r2
    b       token

read:
    add     r1, r4, r8                      @ where the next pass starts
    ldr     r3, scratch
    sub     r3, r6, r3
    strh    r3, [r0, #LINK_SEND_SIZE]
finished:
    orr     r1, r1, #MAGIC << 24
    str     r1, [r0]
    mov     r0, #1
    pop     {r4-r10, lr}
    bx      lr

@ Selects bank r2. Uses r3 and ip.
bank:
    str     lr, [sp, #-4]!
    ldr     r3, command_5555
    ldr     ip, command_2aaa
    mov     lr, #0xAA
    strb    lr, [r3]
    mov     lr, #0x55
    strb    lr, [ip]
    mov     lr, #0xB0
    strb    lr, [r3]
    mov     r3, #0x0E000000
    strb    r2, [r3]
    ldr     pc, [sp], #4

scratch:
    .word   SCRATCH
stage:
    .word   STAGE
state:
    .word   STATE
command_5555:
    .word   0x0E005555
command_2aaa:
    .word   0x0E002AAA

@ CLI_RUN_BUFFER_SCRIPT payload: CHECKSUM the console's memory in blocks, so the host can say
@ which blocks of the cartridge differ from a ROM image it holds.
@
@ The frame mechanics are memory-scan's and are not re-derived here (asm/memory-scan.s): the
@ payload returns 0 to be called again next frame with its own image intact
@ [decomp:src/mystery_gift_client.c:276-280], `budget` bounds one call, `max_calls` is the
@ watchdog, and the answer goes out by repointing link->sendBuffer/sendSize
@ [mystery_gift_link.c:59,166].
@
@ The checksum of one block, over its words w in ascending address order:
@     acc = 0;  for each w: acc = w + ror(acc, 31)   (mod 2^32)
@ which is one `add` per word. An XOR here cancels: a one-value fill and two equal changes 32 words
@ apart sum to 0. At each block boundary the sum is stored and acc starts again at 0.
@
@ The image, all offsets from _start, and every one of them a constant this file and
@ buffer_script.py both name:
@
@   0x000  b .Lcode
@   0x004  cursor      where the next call resumes; the caller patches the start address
@   0x008  end         one past the last address to read
@   0x00C  start       the first address; a block's index is (address - start) >> shift
@   0x010  budget      32-byte chunks per call
@   0x014  max_calls   watchdog: finish and answer once this many calls have run
@   0x018  shift       log2 of the block size in bytes, 5 or more
@   0x01C  acc         the running sum of the block in progress, carried across calls
@   0x020  RESULT      the cursor as we finished: == end means every block was summed
@   0x024  RESULT      calls used
@   0x028  RESULT      sums stored below
@   0x02C  RESULT      the shift, echoed so the answer names its own block size
@   0x030  RESULT      128 x u32 block sums
@   0x230  the code
@
@ The send is FIXED at 0x210 bytes from 0x020, so the host's length check stays the proof that
@ the payload repointed it. start and end are block-aligned (the builder refuses anything else),
@ so a boundary is `cursor & (block - 1) == 0` after a chunk.
@
@ Reads only. Writes nothing outside our own image and the two link fields.
@ Position independent. lr is pushed on entry, so the loop holds the block mask in it.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lcursor:
    .word   0                       @ 0x004
.Lend:
    .word   0                       @ 0x008
.Lstart:
    .word   0                       @ 0x00C
.Lbudget:
    .word   0                       @ 0x010
.Lmaxcalls:
    .word   0                       @ 0x014
.Lshift:
    .word   0                       @ 0x018
.Lacc:
    .word   0                       @ 0x01C
.Lresult:
    .word   0                       @ 0x020 final cursor
    .word   0                       @ 0x024 calls used
    .word   0                       @ 0x028 sums stored
    .word   0                       @ 0x02C shift echoed
.Lsums:
    .space  512                     @ 0x030 128 x u32

.Lcode:
    sub     ip, pc, #8              @ pc reads as this instruction + 8, so ip = .Lcode
    push    {r0, r4-r11, lr}        @ r0 = &client->param, kept at [sp]
    ldr     r1, .Lcodeoff
    sub     r1, ip, r1              @ r1 = _start: our base, whatever we were copied to

    ldr     r2, [r1, #0x24]
    add     r2, r2, #1
    str     r2, [r1, #0x24]         @ this call counted before anything can go wrong
    ldr     r3, [r1, #0x14]
    ldr     r10, [r1, #0x04]        @ cursor
    ldr     r11, [r1, #0x08]        @ end
    ldr     r0, [r1, #0x1C]         @ acc, as the last call left it
    cmp     r2, r3
    bhi     .Lfinish                @ the watchdog, not the range: answer with what we have

    ldr     r2, [r1, #0x18]
    mov     lr, #1
    mov     lr, lr, lsl r2
    sub     lr, lr, #1              @ lr = block size - 1
    ldr     r12, [r1, #0x10]
    add     r12, r10, r12, lsl #5   @ r12 = where this call's budget runs out
    cmp     r12, r11
    movhi   r12, r11                @ or the end of the range, whichever is first
    b       .Lnext

.Lloop:
    ldmia   r10!, {r2-r9}           @ eight words, one sequential burst
    add     r0, r2, r0, ror #31
    add     r0, r3, r0, ror #31
    add     r0, r4, r0, ror #31
    add     r0, r5, r0, ror #31
    add     r0, r6, r0, ror #31
    add     r0, r7, r0, ror #31
    add     r0, r8, r0, ror #31
    add     r0, r9, r0, ror #31
    tst     r10, lr
    beq     .Lboundary              @ a block just ended
.Lnext:
    cmp     r10, r12
    blo     .Lloop
    cmp     r10, r11
    bhs     .Lfinish                @ summed to the end: the answer is complete

    str     r10, [r1, #0x04]        @ resume here next frame
    str     r0, [r1, #0x1C]         @ with the block in progress
    mov     r0, #0                  @ NOT 1: call me again [mystery_gift_client.c:277]
    pop     {r2, r4-r11, lr}
    bx      lr

@ The block [r10 - block, r10) is complete. r2-r9 are free; r0, r1, r10-r12 and lr must survive.
.Lboundary:
    ldr     r2, [r1, #0x0C]
    sub     r2, r10, r2
    ldr     r3, [r1, #0x18]
    mov     r2, r2, lsr r3
    sub     r2, r2, #1              @ the block's index
    cmp     r2, #128
    addlo   r3, r1, #0x30
    strlo   r0, [r3, r2, lsl #2]
    ldrlo   r3, [r1, #0x28]
    addlo   r3, r3, #1
    strlo   r3, [r1, #0x28]         @ counted only when there was room for it
    mov     r0, #0                  @ the next block starts from nothing
    b       .Lnext

.Lfinish:
    str     r10, [r1, #0x04]
    str     r0, [r1, #0x1C]
    str     r10, [r1, #0x20]        @ how far the sums actually got
    ldr     r2, [r1, #0x18]
    str     r2, [r1, #0x2C]
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r1, #0x20
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #0x210
    strh    r2, [r3, #0x34]         @ client->link.sendSize = header + 128 sums, always
    ldr     r2, [r1, #0x28]
    str     r2, [r3, #0x00]         @ *param = sums stored, for the 4-byte channel too
    mov     r0, #1                  @ done
    pop     {r2, r4-r11, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start

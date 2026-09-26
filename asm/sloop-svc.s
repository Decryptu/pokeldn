@ CLI_RUN_BUFFER_SCRIPT payload: issue up to eight Sloop syscalls and send back what each left.
@
@ The Switch release's emulator answers `swi 0x40..0x62` itself [decomp:src/sloopsvc.c]. For each
@ number in the list this payload copies up to 256 bytes of data into EWRAM, loads r0..r3
@ (optionally pointing r0 or r1 at that copy), rewrites the low byte of its THUMB thunk and calls
@ it, then repoints the console's outgoing message at a result block [docs/frlg_rom.md, Calling
@ the wrapper]. No instruction cache on this CPU, so the rewritten thunk is what runs.
@
@ Image, offsets from _start, patched by buffer_script.build_sloop_svc:
@   0x000  b .Lcode
@   0x004  flags       bit 0: r0 = &copy, bit 1: r1 = &copy
@   0x008  r0 .. r3    0x008, 0x00C, 0x010, 0x014
@   0x018  scratch     the EWRAM result block, and what the send is pointed at
@   0x01C  length      bytes of data to copy, at most 256; a zero byte is stored after them
@   0x020  thunk       swi N ; bx lr, THUMB, or bkpt N ; bx lr; the low byte is rewritten per call
@   0x024  count       how many numbers, 1..8
@   0x028  numbers     eight bytes
@   0x030  data        256 bytes
@
@ Result block at scratch:
@   +0x00  0x53565331  reached, written before the first call
@   +0x04  count
@   +0x08  0x53565332  returned, zero until every call has
@   +0x0C  length
@   +0x10  per call, 20 bytes: the thunk word, then r0, r1, r2, r3 as the syscall left them
@   +0xB0  the data after the last call, length + 1 bytes

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lflags:    .word 0                 @ 0x004
.Lr0:       .word 0                 @ 0x008
.Lr1:       .word 0                 @ 0x00C
.Lr2:       .word 0                 @ 0x010
.Lr3:       .word 0                 @ 0x014
.Lscratch:  .word 0                 @ 0x018
.Llength:   .word 0                 @ 0x01C
.Lthunk:    .word 0x4770DF00        @ 0x020  swi 0x00 ; bx lr (THUMB)
.Lcount:    .word 0                 @ 0x024
.Lnumbers:  .space 8                @ 0x028
.Ldata:     .space 256              @ 0x030

.Lcode:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r7, r0                  @ &client->param
    adr     r4, _start
    ldr     r5, [r4, #0x18]         @ the result block

    ldr     r0, .Lreached
    str     r0, [r5, #0x00]
    ldr     r0, [r4, #0x24]
    str     r0, [r5, #0x04]
    mov     r0, #0
    str     r0, [r5, #0x08]
    ldr     r0, [r4, #0x1C]
    str     r0, [r5, #0x0C]
    mov     r8, #0                  @ the call index

.Lnext:
    ldr     r0, [r4, #0x24]
    cmp     r8, r0
    bhs     .Ldone

    @ Fresh data for every call, terminated.
    ldr     r6, [r4, #0x1C]
    add     r1, r4, #0x30
    add     r3, r5, #0xB0
    mov     r2, #0
.Lcopy:
    cmp     r2, r6
    bhs     .Lcopied
    ldrb    r0, [r1, r2]
    strb    r0, [r3, r2]
    add     r2, r2, #1
    b       .Lcopy
.Lcopied:
    mov     r0, #0
    strb    r0, [r3, r2]

    @ This call's number into the thunk.
    add     r0, r4, #0x28
    ldrb    r0, [r0, r8]
    strb    r0, [r4, #0x20]

    @ r0..r3, then the pointer substitutions the flags ask for.
    ldr     ip, [r4, #0x04]
    ldr     r0, [r4, #0x08]
    ldr     r1, [r4, #0x0C]
    ldr     r2, [r4, #0x10]
    tst     ip, #1
    movne   r0, r3
    tst     ip, #2
    movne   r1, r3
    ldr     r3, [r4, #0x14]

    add     ip, r4, #0x20
    orr     ip, ip, #1              @ THUMB
    mov     lr, pc                  @ ARM return, two instructions on
    bx      ip

    @ Record the thunk word and the four registers at +0x10 + 20 * index.
    add     r6, r8, r8, lsl #2      @ 5 * index
    add     r6, r5, r6, lsl #2      @ + 20 * index
    add     r6, r6, #0x10
    ldr     ip, [r4, #0x20]
    str     ip, [r6], #4
    stmia   r6, {r0, r1, r2, r3}
    add     r8, r8, #1
    b       .Lnext

.Ldone:
    ldr     r0, .Lreturned
    str     r0, [r5, #0x08]

    @ Send the block: header, eight records and the data with its terminator.
    str     r5, [r7, #0x3C]         @ client->link.sendBuffer
    ldr     r0, [r5, #0x0C]
    add     r0, r0, #0xB1
    strh    r0, [r7, #0x34]         @ client->link.sendSize

    mov     r0, #1                  @ done
    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

.Lreached:  .word 0x53565331
.Lreturned: .word 0x53565332

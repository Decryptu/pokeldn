@ Install the resident hook kept in the save: check the blob at gSaveBlock2Ptr + 0xB20 (filler_B20)
@ and install it as install-resident does. One image, two callers: the ARM entry at +0 is a
@ CLI_RUN_BUFFER_SCRIPT payload (r0 = &client->param), and MOM's RAM script stages it from +8 and
@ calls the THUMB entry there. docs/frlg_rom.md, A resident hook kept in the save.
@
@ The blob: +0 magic "PKR2", +4 length (hook bytes, whole words), +8 dest, +12 entry offset,
@ +14 p_original offset, +16 the hook, then the sum of every word before it. The sum is checked in
@ place, before anything is written: gSaveBlock2Ptr moves on every load, so it is read each call.
@ Patched by buffer_script.build_install_kept: the image's last two words.

    .arm
    .text
    .global _start
_start:
    add     r3, pc, #(.Lbody - _start - 8 + 1)
    bx      r3

    .thumb
.Lmom:                              @ +8: MOM's entry; the answer goes in .Lscratch
    adr     r0, .Lscratch
.Lbody:                             @ +0x0A: the buffer script's, r0 = &client->param
    push    {r4, r5, r6, r7, lr}
    mov     r7, r0                  @ where the answer goes
    ldr     r1, .Lrefused
    str     r1, [r7]                @ until something is installed
    ldr     r4, .Lsav2ptr
    ldr     r4, [r4]
    mov     r1, #0xB2
    lsl     r1, r1, #4
    add     r4, r1                  @ filler_B20
    ldr     r0, [r4]
    ldr     r1, .Lmagic
    cmp     r0, r1
    bne     .Lout                   @ no kept hook
    ldr     r5, [r4, #4]
    add     r5, #16                 @ the bytes summed
    mov     r1, #0xFF
    lsl     r1, r1, #2
    cmp     r5, r1
    bhi     .Lout                   @ the checksum would lie past filler_B20
    mov     r2, #0
    mov     r3, #0
.Lsum:
    ldr     r0, [r4, r3]
    add     r2, r0
    add     r3, #4
    cmp     r3, r5
    blo     .Lsum
    ldr     r0, [r4, r5]
    cmp     r0, r2
    bne     .Lout                   @ not all of it arrived: install nothing

    bl      .Lime_address
    ldrh    r6, [r3]                @ REG_IME, kept
    mov     r0, #0
    strh    r0, [r3]                @ no V-blank runs a half-written hook

    ldr     r0, .Ltable
    ldr     r1, [r0]                @ what handles V-blank now
    str     r1, [r7]                @ the answer: the handler found
    ldr     r5, [r4, #8]            @ dest
    sub     r2, r5, #4              @ the word the game's handler is kept in
    sub     r3, r1, r5
    lsr     r3, r3, #10
    bne     .Lgame
    ldr     r1, [r2]                @ a resident hook already: the game's handler it kept
    b       .Lkept
.Lgame:
    str     r1, [r2]                @ the game's own handler: keep it for the next install
.Lkept:
    cmp     r1, #0
    beq     .Lrefuse                @ a hook with no kept handler: chaining it would jump to 0
    ldrh    r2, [r4, #12]
    add     r2, r5
    add     r2, #1                  @ the entry, THUMB bit set
    push    {r2}
    ldrh    r2, [r4, #14]
    push    {r2}
    ldr     r0, [r4, #4]
    add     r4, #16                 @ the hook
.Lcopy:
    sub     r0, #4
    bmi     .Lcopied
    ldr     r2, [r4, r0]
    str     r2, [r5, r0]
    b       .Lcopy
.Lcopied:
    pop     {r0}
    str     r1, [r5, r0]            @ p_original
    pop     {r2}
    ldr     r0, .Ltable
    str     r2, [r0]                @ gIntrTable[4], last
.Lime:
    bl      .Lime_address
    strh    r6, [r3]                @ REG_IME back
.Lout:
    mov     r0, #1                  @ done
    pop     {r4, r5, r6, r7}
    pop     {r3}
    bx      r3

.Lrefuse:
    ldr     r0, .Lrefused
    str     r0, [r7]
    b       .Lime

.Lime_address:                      @ r3 = REG_IME, 0x04000208
    mov     r3, #0x82
    lsl     r3, r3, #2
    mov     r2, #4
    lsl     r2, r2, #24
    add     r3, r2
    bx      lr

    .align 2
.Lscratch:  .word 0
.Lmagic:    .word 0x32524B50        @ "PKR2"
.Lrefused:  .word 0xBAD0BAD0
.Lsav2ptr:  .word 0                 @ end - 8: &gSaveBlock2Ptr
.Ltable:    .word 0                 @ end - 4: &gIntrTable[4]

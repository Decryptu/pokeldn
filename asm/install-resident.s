@ CLI_RUN_BUFFER_SCRIPT payload: install a resident V-blank hook carried in this image.
@
@ Copies `length` bytes of THUMB code to `dest` (the free top of EWRAM, docs/frlg_rom.md "Where a
@ payload can live"), stores the handler it replaces into the blob's p_original, and points
@ gIntrTable[4] at the blob's entry. The hook then runs every frame until a soft reset.
@
@ IDEMPOTENT. The game's handler is kept in the word just below `dest` on the first install. If the
@ table already points into the resident area, the handler is taken from that word, whatever layout
@ the hook already there had; otherwise a reinstall would chain the new hook to itself, or to a stale
@ offset of the old one, and spin or jump to garbage inside the interrupt.
@ IME is cleared around the copy and the table write, so no V-blank runs a half-written hook.
@ The body is THUMB, half the size of ARM, so a hook has that much more of the 1024-byte buffer.
@
@ Image, offsets from _start, patched by buffer_script.build_install_resident:
@   0x000  b .Lcode
@   0x004  dest          where the blob goes, word aligned
@   0x008  length        bytes, a multiple of 4
@   0x00C  table         &gIntrTable[4]
@   0x010  entry_off     the hook's entry inside the blob
@   0x014  original_off  the blob's p_original word
@   0x018  blob_off      where the blob starts in this image: the builder appends it after the code

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Ldest:     .word 0                 @ 0x004
.Llength:   .word 0                 @ 0x008
.Ltable:    .word 0                 @ 0x00C
.Lentry:    .word 0                 @ 0x010
.Lorigoff:  .word 0                 @ 0x014
.Lblobof:   .word 0                 @ 0x018

.Lcode:
    add     r3, pc, #1              @ pc reads .Lcode + 8: .Lthumb, THUMB bit set
    bx      r3

    .thumb
.Lthumb:
    push    {r4, r5, r6, r7, lr}
    mov     r7, r0                  @ &client->param
.Lhere:
    mov     r4, pc                  @ .Lhere + 4
    sub     r4, #.Lhere + 4 - _start
    ldr     r5, [r4, #0x04]         @ dest

    bl      .Lime_address
    ldrh    r6, [r3]                @ REG_IME, kept
    mov     r0, #0
    strh    r0, [r3]                @ no interrupts while the hook is half written

    ldr     r0, [r4, #0x0C]
    ldr     r1, [r0]                @ what handles V-blank now
    str     r1, [r7]                @ the answer: the handler found in the table
    sub     r2, r5, #4              @ the word the game's handler is kept in
    sub     r3, r1, r5              @ how far into the resident area the table points
    lsr     r3, r3, #10
    bne     .Lgame
    ldr     r1, [r2]                @ a resident hook already: the game's handler it kept
    b       .Lkept
.Lgame:
    str     r1, [r2]                @ the game's own handler: keep it for the next install
.Lkept:
    cmp     r1, #0
    beq     .Lrefuse                @ a hook with no kept handler: chaining it would jump to 0

    ldr     r0, [r4, #0x08]         @ length, a multiple of 4
    ldr     r3, [r4, #0x18]
    add     r3, r4                  @ the blob
.Lcopy:
    sub     r0, #4
    bmi     .Lcopied
    ldr     r2, [r3, r0]
    str     r2, [r5, r0]
    b       .Lcopy
.Lcopied:
    ldr     r0, [r4, #0x14]
    str     r1, [r5, r0]            @ p_original
    ldr     r2, [r4, #0x10]
    add     r2, r5
    add     r2, #1                  @ our entry, THUMB bit set
    ldr     r0, [r4, #0x0C]
    str     r2, [r0]                @ gIntrTable[4], last

.Lime:
    bl      .Lime_address
    strh    r6, [r3]                @ REG_IME back
    mov     r0, #1                  @ done
    pop     {r4, r5, r6, r7}
    pop     {r3}
    bx      r3                      @ to the ARM caller

.Lrefuse:
    ldr     r0, .Lrefused
    str     r0, [r7]                @ the answer says nothing was written
    b       .Lime

.Lime_address:                      @ r3 = REG_IME, 0x04000208
    mov     r3, #0x82
    lsl     r3, r3, #2
    mov     r2, #4
    lsl     r2, r2, #24
    add     r3, r2
    bx      lr

    .align 2
.Lrefused:
    .word   0xBAD0BAD0

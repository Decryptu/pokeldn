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
    push    {r4, r5, r6, r7, lr}
    mov     r7, r0                  @ &client->param
    adr     r4, _start
    ldr     r5, [r4, #0x04]         @ dest

    mov     r3, #0x04000000
    add     r3, r3, #0x200          @ REG_IE
    ldrh    r6, [r3, #0x08]         @ REG_IME, kept
    mov     r0, #0
    strh    r0, [r3, #0x08]         @ no interrupts while the hook is half written

    ldr     r0, [r4, #0x0C]
    ldr     r1, [r0]                @ what handles V-blank now
    str     r1, [r7]                @ the answer: the handler found in the table
    ldr     r2, [r4, #0x10]
    add     r2, r5, r2
    add     r2, r2, #1              @ our entry, THUMB bit set
    sub     r3, r1, r5              @ how far into the resident area the table points
    cmp     r3, #0x400
    ldrlo   r1, [r5, #-4]           @ a resident hook already: the game's handler it kept
    strhs   r1, [r5, #-4]           @ the game's own handler: keep it for the next install
    cmp     r1, #0
    beq     .Lrefuse                @ a hook with no kept handler: chaining it would jump to 0

    ldr     r0, [r4, #0x08]         @ length
    ldr     lr, [r4, #0x18]
    add     lr, r4, lr              @ the blob
    mov     ip, #0
.Lcopy:
    cmp     ip, r0
    bhs     .Lcopied
    ldr     r3, [lr, ip]
    str     r3, [r5, ip]
    add     ip, ip, #4
    b       .Lcopy
.Lcopied:
    ldr     ip, [r4, #0x14]
    str     r1, [r5, ip]            @ p_original
    ldr     r0, [r4, #0x0C]
    str     r2, [r0]                @ gIntrTable[4], last

.Lime:
    mov     r3, #0x04000000
    add     r3, r3, #0x200
    strh    r6, [r3, #0x08]         @ REG_IME back

    mov     r0, #1                  @ done
    pop     {r4, r5, r6, r7, lr}
    bx      lr

.Lrefuse:
    ldr     r0, .Lrefused
    str     r0, [r7]                @ the answer says nothing was written
    b       .Lime
.Lrefused:
    .word   0xBAD0BAD0

@ FIELD STUB: copy a payload out of the save into EWRAM and run it.
@
@ A RAM script stages this with `setptr` and reaches it with `callnative`, so it runs in the
@ overworld when the player talks to the object the script is bound to. It is the whole of what the
@ script has to carry: about fifty bytes whatever the payload's size, where staging the payload
@ itself would cost six script bytes per byte and cap it at 162.
@
@ THE SOURCE ADDRESS IS READ, NOT PATCHED. `gSaveBlock2Ptr` is a pointer at a fixed IWRAM address and
@ the block it points at is re-rolled by a multiple of four on every battle and every load
@ [decomp:src/load_save.c:75], so an address taken from one session is wrong in the next. This
@ dereferences the pointer every time it runs.
@
@ THE MAGIC IS THE GUARD. If the save has never been written, or a later card reached further than
@ measured, the copied bytes are not a payload and branching into them runs whatever is there. The
@ first word of the blob is a constant the builder chose; a mismatch returns without branching, and
@ the player gets an ordinary conversation instead of a frozen overworld.
@
@ NOTHING IS SAVED OR RESTORED. `callnative` calls this as `void (*)(void)`, so r0-r3 are free and
@ r4-r7 are not touched. Thumb's `pop` cannot restore `lr`, and not pushing it is what lets the
@ branch into the payload be a tail branch: the payload's own return goes straight back to
@ `ScrCmd_callnative`'s caller.

    .thumb
    .align 2
    .global _start
    .global p_sav2ptr, p_offset, p_dest, p_words, p_magic
_start:
    ldr     r0, p_sav2ptr
    ldr     r0, [r0]                @ gSaveBlock2Ptr, read fresh
    ldr     r1, p_offset
    add     r0, r0, r1              @ the payload in the save
    ldr     r1, p_dest              @ the destination, advanced by the loop
    ldr     r2, p_words
.Lcopy:
    cmp     r2, #0
    beq     .Lcopied
    ldr     r3, [r0]
    str     r3, [r1]
    add     r0, #4
    add     r1, #4
    sub     r2, #1
    b       .Lcopy
.Lcopied:
    ldr     r0, p_dest
    ldr     r1, [r0]                @ the first word of what arrived
    ldr     r2, p_magic
    cmp     r1, r2
    bne     .Ldone                  @ not a payload: run nothing
    add     r0, #5                  @ the entry follows the magic, and Thumb wants bit 0
    bx      r0                      @ tail branch: lr still points at the caller
.Ldone:
    bx      lr

    .align 2
p_sav2ptr: .word 0x0300422C         @ &gSaveBlock2Ptr [rom_map.GSAVEBLOCK2PTR]
p_offset:  .word 0x00000B20         @ patched: filler_B20 inside SaveBlock2
p_dest:    .word 0x0203FC00         @ patched: the staging area
p_words:   .word 0x000000F0         @ patched: how many words to copy
p_magic:   .word 0x444C4B50         @ patched: the blob's first word

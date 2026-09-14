@ FIELD STUB: install the resident V-blank hook, carrying the hook with it.
@
@ A RAM script stages this into EWRAM one byte at a time and reaches it with `callnative`, so it runs
@ in the overworld when the player talks to the object the script is bound to. `save-loader.s` is the
@ other way to install the same hook, and the better one for anything large: it copies a payload out
@ of the save and the script does not grow with it. This one carries the hook in the script itself,
@ which is simpler when the hook is all there is.
@
@ THE HOOK IS DATA APPENDED AFTER THIS CODE, not three words written out by hand. An earlier version
@ wrote word 0, 1 and 2 and patched the rest, and when the hook grew from five words to fifteen the
@ installer was silently writing a third of it. The count comes from the builder and the words come
@ from the same symbol table the hook is assembled from, so the two cannot go out of step.
@
@ IDEMPOTENT. Installing twice would point the hook's tail branch at the hook, which spins forever
@ inside an interrupt handler and freezes the console with no menu to back out of. The table is read
@ first and this returns having written nothing if it already names the hook.
@
@ ORDER. The table entry is written last, so it never names a half-written hook.

    .thumb
    .align 2
    .global _start
_start:
    push    {r4, r5, r6, lr}
    ldr     r0, p_table_entry       @ &gIntrTable[4]
    ldr     r1, [r0]                @ whatever handles V-blank now
    ldr     r2, p_hook_ptr          @ our hook, Thumb bit set
    cmp     r1, r2
    beq     .Ldone                  @ already installed
    ldr     r3, p_resident          @ where the hook goes
    adr     r4, .Lwords             @ and where it comes from, PC-relative
    ldr     r5, p_words
.Lcopy:
    ldr     r6, [r4]
    str     r6, [r3]
    add     r4, #4
    add     r3, #4
    sub     r5, #1
    bne     .Lcopy
    ldr     r3, p_original_at
    str     r1, [r3]                @ the handler the hook tail-branches to
    ldr     r4, p_counter
    mov     r5, #0
    str     r5, [r4]                @ the counter starts at zero
    str     r2, [r0]                @ install, last
.Ldone:
    pop     {r4, r5, r6, pc}

    .align 2
    .global p_table_entry, p_hook_ptr, p_resident, p_counter, p_original_at, p_words
p_table_entry:  .word 0x03002730    @ gIntrTable[4] [docs/frlg_rom.md, The per-frame hook]
p_hook_ptr:     .word 0x0203FC01    @ patched: where the hook will live, Thumb bit set
p_resident:     .word 0x0203FC00    @ patched: the same, Thumb bit clear
p_counter:      .word 0x0203FC40    @ patched: the frame counter
p_original_at:  .word 0x0203FC10    @ patched: where the hook keeps its tail target
p_words:        .word 5             @ patched: how many words the hook is

    .align 2
    .global _words
.Lwords:
_words:
    .word   0                       @ the builder appends the hook here

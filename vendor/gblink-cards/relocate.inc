@ The game moves SaveBlock1, and the RAM script in it, whenever it returns to
@ the overworld from a menu or scene. `relocate` copies the RAM script to
@ RELOCATED and moves the script context to the same place in the copy; the
@ script then re-anchors its relative addresses with `setvaddress`.
@
@ Parameters (--defsym): SB1_PTR (&gSaveBlock1Ptr), SCRIPT_IN_SB1 (the RAM
@ script's offset in SaveBlock1) and RELOCATED.

    .equ RAM_SCRIPT_WORDS, 249          @ 995 bytes, rounded up

relocate:                               @ r3 = the script context
    ldr r0, relocate_sb1_ptr
    ldr r0, [r0]
    ldr r1, relocate_script
    adds r0, r0, r1
    ldr r1, relocate_to
    ldr r2, [r3, #8]                    @ scriptPtr
    subs r2, r2, r0
    adds r2, r2, r1
    str r2, [r3, #8]
    movs r2, #RAM_SCRIPT_WORDS
    lsls r2, r2, #2
1:  subs r2, #4
    ldr r3, [r0, r2]
    str r3, [r1, r2]
    bne 1b
    bx lr

    .align 2
relocate_sb1_ptr: .word SB1_PTR
relocate_script:  .word SCRIPT_IN_SB1
relocate_to:      .word RELOCATED

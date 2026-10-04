@ How a card's script calls its code. The script loads these 16 bytes into
@ the script context's data registers with `loadword`, then calls a routine
@ with `callnative` to them and a u16 after the address: the routine's
@ distance from the address's third byte, Thumb bit set.
@
@ ScrCmd_callnative leaves ScriptReadWord's registers: r2 = the address's
@ third byte, r3 = the script context. Routines get r3 too and return to the
@ script engine; the script carries on after the u16.

    .syntax unified
    .thumb
    .text
    ldrb r0, [r2, #3]
    lsls r0, r0, #8
    ldrb r1, [r2, #2]
    adds r0, r0, r1
    adds r0, r0, r2
    adds r2, #4
    str r2, [r3, #8]                    @ scriptPtr
    bx r0

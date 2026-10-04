@ Max Conditions. `max_conditions` raises the COOL, BEAUTY, CUTE, SMART and
@ TOUGH conditions and the sheen of the Pokémon in gSpecialVar_0x8004 to 255,
@ as far as POKéBLOCKS take them. A FEEBAS evolves at its next level when its
@ Beauty is above 170.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SET_MON_DATA and those of
@ relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
    .equ MAX_CONDITION, 255
    .equ CONDITIONS, 6

max_conditions:
    push {r5, lr}
    sub sp, #4
    movs r0, #MAX_CONDITION
    str r0, [sp]
    movs r5, #0
1:  bl chosen_mon
    adr r1, fields
    ldrb r1, [r1, r5]
    mov r2, sp
    ldr r3, p_set_mon_data
    bl call_r3
    adds r5, #1
    cmp r5, #CONDITIONS
    bne 1b
    add sp, #4
    pop {r5, pc}

call_r3:
    bx r3

    .align 2
p_set_mon_data: .word SET_MON_DATA
fields:         .byte 22, 23, 24, 33, 47, 48   @ MON_DATA_COOL, BEAUTY, CUTE, SMART, TOUGH, SHEEN
    .align 2

    .include "mons.inc"
    .include "relocate.inc"

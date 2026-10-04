@ Friendship Checker. `check` puts the friendship of the Pokémon in
@ gSpecialVar_0x8004 in VAR_0x8005. `max_menu` offers to raise it to 255 for
@ that Pokémon or for the whole party, and `befriend` does: for the Pokémon
@ (VAR_RESULT 0) or for every party Pokémon that isn't an Egg (VAR_RESULT
@ 1), whose friendship byte holds its egg cycles.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ GET_MON_DATA, SET_MON_DATA and those of menu.inc and relocate.inc; data.inc
@ holds the menu's items.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
    .set MENU_LISTS, 1
    .equ MON_DATA_FRIENDSHIP, 32
    .equ MAX_FRIENDSHIP, 255
    .equ MENU_WIDTH, 11                 @ tiles, for THIS POKéMON

check:
    push {lr}
    bl chosen_mon
    movs r1, #MON_DATA_FRIENDSHIP
    ldr r3, p_get_mon_data
    bl call_r3
    ldr r1, p_var_8004
    strh r0, [r1, #2]                   @ VAR_0x8005
    pop {pc}

max_menu:
    adr r0, max_items
    movs r1, #3
    movs r2, #MENU_WIDTH
    b list_menu

befriend:
    push {r4, r5, lr}
    sub sp, #4
    movs r0, #MAX_FRIENDSHIP
    str r0, [sp]
    ldr r0, p_var_result
    ldrh r0, [r0]
    cmp r0, #0
    bne 1f
    bl chosen_mon
    bl befriend_mon
    b 9f
1:  ldr r4, p_party
    movs r5, #PARTY_SIZE
2:  ldrb r0, [r4, #MON_FLAGS]
    lsls r0, r0, #29
    lsrs r0, r0, #29
    cmp r0, #A_POKEMON
    bne 3f
    movs r0, r4
    bl befriend_mon
3:  adds r4, #MON_SIZE
    subs r5, #1
    bne 2b
9:  add sp, #4
    pop {r4, r5, pc}

@ SetMonData(r0, MON_DATA_FRIENDSHIP, the 255 in befriend's frame).
befriend_mon:
    movs r1, #MON_DATA_FRIENDSHIP
    mov r2, sp
    ldr r3, p_set_mon_data
call_r3:
    bx r3

    .align 2
p_var_8004:     .word SPECIAL_VAR_8004
p_var_result:   .word SPECIAL_VAR_RESULT
p_party:        .word PARTY
p_get_mon_data: .word GET_MON_DATA
p_set_mon_data: .word SET_MON_DATA

    .include "data.inc"
    .include "menu.inc"
    .include "mons.inc"
    .include "relocate.inc"

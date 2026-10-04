@ EV Training, for the Pokémon in gSpecialVar_0x8004. `reset_evs` sets its six
@ EVs to 0. `ev_menu` offers the six stats (gStatNamesTable 0-5) in the
@ multichoice box. `max_ev` raises the EV of stat VAR_RESULT to 252, or as far
@ as the 510 total allows, never lowering it; its value goes to VAR_0x8005 and
@ the stat's name to gStringVar2. `recalculate` recalculates its stats.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ STRING_VAR_2, STAT_NAMES, GET_MON_DATA, SET_MON_DATA, CALCULATE_STATS,
@ STRING_COPY and those of menu.inc and relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
    .equ STAT_MENU_WIDTH, 8             @ tiles, for SP. ATK and DEFENSE
    .equ MON_DATA_HP_EV, 26
    .equ STAT_COUNT, 6
    .equ TRAINED_EV, 252
    .equ MAX_TOTAL_EVS, 510

reset_evs:
    push {r4, r5, lr}
    sub sp, #4
    bl chosen_mon
    movs r4, r0
    movs r0, #0
    str r0, [sp]
    movs r5, #MON_DATA_HP_EV
1:  movs r0, r4
    movs r1, r5
    mov r2, sp
    ldr r3, p_set_mon_data
    bl call_r3
    adds r5, #1
    cmp r5, #MON_DATA_HP_EV + STAT_COUNT
    bne 1b
    add sp, #4
    pop {r4, r5, pc}

ev_menu:
    ldr r0, p_stat_names
    movs r1, #STAT_COUNT
    movs r2, #STAT_MENU_WIDTH
    b menu

max_ev:
    push {r4, r5, r6, r7, lr}
    sub sp, #4
    bl chosen_mon
    movs r4, r0
    ldr r0, p_var_result
    ldrh r7, [r0]                       @ the stat
    movs r5, #0                         @ the total of the others
    movs r6, #0
1:  cmp r6, r7
    beq 2f
    movs r0, r4
    movs r1, #MON_DATA_HP_EV
    adds r1, r1, r6
    ldr r3, p_get_mon_data
    bl call_r3
    adds r5, r5, r0
2:  adds r6, #1
    cmp r6, #STAT_COUNT
    bne 1b
    ldr r6, p_max_total
    subs r6, r6, r5                     @ room left
    bpl 3f
    movs r6, #0
3:  cmp r6, #TRAINED_EV
    bls 4f
    movs r6, #TRAINED_EV
4:  movs r0, r4
    movs r1, #MON_DATA_HP_EV
    adds r1, r1, r7
    ldr r3, p_get_mon_data
    bl call_r3
    cmp r6, r0
    bcs 5f
    movs r6, r0                         @ already higher
5:  str r6, [sp]
    movs r0, r4
    movs r1, #MON_DATA_HP_EV
    adds r1, r1, r7
    mov r2, sp
    ldr r3, p_set_mon_data
    bl call_r3
    ldr r0, p_var_8004
    strh r6, [r0, #2]                   @ VAR_0x8005
    lsls r7, r7, #2
    ldr r1, p_stat_names
    ldr r1, [r1, r7]
    ldr r0, p_string_var_2
    ldr r3, p_string_copy
    bl call_r3
    add sp, #4
    pop {r4, r5, r6, r7, pc}

recalculate:
    push {lr}
    bl chosen_mon
    ldr r3, p_calculate_stats
    bl call_r3
    pop {pc}

call_r3:
    bx r3

    .align 2
p_var_8004:        .word SPECIAL_VAR_8004
p_var_result:      .word SPECIAL_VAR_RESULT
p_stat_names:      .word STAT_NAMES
p_get_mon_data:    .word GET_MON_DATA
p_set_mon_data:    .word SET_MON_DATA
p_calculate_stats: .word CALCULATE_STATS
p_string_var_2:    .word STRING_VAR_2
p_string_copy:     .word STRING_COPY
p_max_total:       .word MAX_TOTAL_EVS

    .include "menu.inc"
    .include "mons.inc"
    .include "relocate.inc"

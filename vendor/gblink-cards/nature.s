@ Nature Mint. `stat_menu` offers ATTACK to SP. DEF (gStatNamesTable 1-5) in
@ the multichoice box. `change_nature` gives the Pokémon in gSpecialVar_0x8004
@ the nature that raises stat VAR_0x8005 and lowers stat VAR_RESULT (both 0-4,
@ from the menu; natures go 5 to a raised stat in that order), keeping its
@ gender, ability and shininess (repersonalize: its IVs come with the new
@ personality, and its stats are recalculated), and puts the nature's name
@ in gStringVar2. VAR_RESULT = 1, or 0 when no personality turned up.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ STRING_VAR_2, STAT_NAMES, NATURE_NAMES, STRING_COPY and
@ those of menu.inc, personality.inc and relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_ORDER, 1
    .set REP_KEEP_ORDER, 1              @ the low byte stays
    .set MONS_CHOSEN, 1
    .equ STAT_MENU_WIDTH, 8             @ tiles, for SP. ATK and DEFENSE

stat_menu:
    ldr r0, p_stat_names
    adds r0, #4                         @ from ATTACK
    movs r1, #5
    movs r2, #STAT_MENU_WIDTH
    b menu

change_nature:
    push {r4, r5, lr}
    ldr r0, p_var_8004
    ldrh r5, [r0, #2]                   @ VAR_0x8005
    movs r1, #5
    muls r5, r1
    ldr r0, p_var_result
    ldrh r0, [r0]
    adds r5, r5, r0                     @ the nature
    bl chosen_mon
    movs r4, r0
    ldrb r1, [r4, #MON_PERSONALITY]     @ the same low byte
    movs r2, r5
    bl repersonalize
    ldr r1, p_var_result
    strh r0, [r1]
    cmp r0, #0
    beq 9f
    ldr r1, p_nature_names
    lsls r5, r5, #2
    ldr r1, [r1, r5]
    ldr r0, p_string_var_2
    ldr r3, p_string_copy
    bl call_r3
9:  pop {r4, r5, pc}

call_r3:
    bx r3

    .align 2
p_stat_names:      .word STAT_NAMES
p_var_8004:        .word SPECIAL_VAR_8004
p_var_result:      .word SPECIAL_VAR_RESULT
p_nature_names:    .word NATURE_NAMES
p_string_var_2:    .word STRING_VAR_2
p_string_copy:     .word STRING_COPY

    .include "menu.inc"
    .include "personality.inc"
    .include "mons.inc"
    .include "relocate.inc"

@ Hidden Power, for the Pokémon in gSpecialVar_0x8004. Two cards share this:
@
@ With PICK 0 (Hidden Power & IVs), `hidden_power` works out its Hidden Power
@ from its IVs the way the game does: its type's name goes to gStringVar2 and
@ its power to VAR_0x8005. `max_ivs` sets every IV to 31, with a personality
@ that goes with them.
@
@ With PICK 1 (Hidden Power Type), `kind_menu` asks physical or special and
@ `type_menu` offers the eight types of kind VAR_0x8006; `set_type` gives the
@ Pokémon type VAR_RESULT of them at power 70 and puts its name in
@ gStringVar2. Each IV becomes 30 or 31, its lowest bit that IV's bit of
@ 4 × the type's number + 3: HP and Attack stay 31 and floor(bits × 15 / 63),
@ the game's formula, gives the type.
@
@ Both recalculate its stats.
@
@ Parameters (--defsym): PICK, PARTY, SPECIAL_VAR_8004, SET_MON_DATA,
@ CALCULATE_STATS, STRING_VAR_2, TYPE_NAMES, STRING_COPY, JAPANESE (1 on the
@ Japanese games), relocate.inc's, and
@ with PICK 0 GET_MON_DATA, with PICK 1 SPECIAL_VAR_RESULT and menu.inc's;
@ data.inc holds the kinds' names.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
.if PICK == 0
    .set MONS_ORDER, 1
    .set PERSONALITY_SET_ONLY, 1
.endif
    .equ MON_DATA_HP_IV, 39
    .equ STAT_COUNT, 6
    .equ TYPE_FIGHTING, 1
    .equ TYPE_MYSTERY, 9                @ ???, which Hidden Power skips
.if JAPANESE
    .equ TYPE_NAME_SIZE, 5
.else
    .equ TYPE_NAME_SIZE, 7
.endif
    .equ KIND_TYPES, 8
    .equ KIND_WIDTH, 8                  @ tiles, for PHYSICAL
    .equ TYPE_WIDTH, 7                  @ for FLYING

.if PICK == 0
hidden_power:
    push {r4, r5, r6, r7, lr}
    bl chosen_mon
    movs r4, r0
    movs r5, #0                         @ the type bits
    movs r6, #0                         @ the power bits
    movs r7, #0                         @ the stat
1:  movs r0, r4
    movs r1, #MON_DATA_HP_IV
    adds r1, r1, r7
    ldr r3, p_get_mon_data
    bl call_r3
    lsrs r1, r0, #1
    movs r2, #1
    ands r0, r2
    ands r1, r2
    lsls r0, r7
    lsls r1, r7
    orrs r5, r0
    orrs r6, r1
    adds r7, #1
    cmp r7, #STAT_COUNT
    bne 1b
    movs r0, #40
    muls r0, r6
    movs r1, #63
    svc #6                              @ Div
    adds r0, #30
    ldr r1, p_var_8004
    strh r0, [r1, #2]                   @ VAR_0x8005: the power
    movs r0, #15
    muls r0, r5
    movs r1, #63
    svc #6
    adds r0, #TYPE_FIGHTING
    cmp r0, #TYPE_MYSTERY
    bcc 2f
    adds r0, #1
2:  bl type_name
    pop {r4, r5, r6, r7, pc}

@ Only six frames of the random number generator give six 31s (Method 1), all
@ with these two personalities but for bit 31: PKHeX wants the PID one of them,
@ so the Pokémon takes the one with its ability bit (both MODEST). A shiny one
@ keeps its personality.
max_ivs:
    push {r4, lr}
    bl chosen_mon
    movs r4, r0
    ldr r1, [r4, #MON_PERSONALITY]
    ldr r0, [r4, #MON_OT_ID]
    eors r0, r1
    lsrs r2, r0, #16
    eors r0, r2
    lsls r0, r0, #16
    lsrs r0, r0, #16                    @ its shiny value
    cmp r0, #8
    bcc 2f
    lsrs r1, r1, #1                     @ carry: the ability bit
    ldr r1, p_all31_odd
    bcs 1f
    ldr r1, p_all31_even
1:  movs r0, r4
    bl set_personality
2:  movs r0, #0xFF                      @ every bit set: 31 each
    bl set_ivs
    pop {r4, pc}
.else
    .set MENU_LISTS, 1

kind_menu:
    adr r0, kind_items
    movs r1, #2
    movs r2, #KIND_WIDTH
    b list_menu

type_menu:
    push {lr}
    sub sp, #KIND_TYPES * 4
    bl first_type
    movs r1, #TYPE_NAME_SIZE
    muls r0, r1
    ldr r1, p_type_names
    adds r0, r0, r1
    movs r1, #0
1:  mov r2, sp
    str r0, [r2, r1]
    adds r0, #TYPE_NAME_SIZE
    adds r1, #4
    cmp r1, #KIND_TYPES * 4
    bne 1b
    mov r0, sp
    movs r1, #KIND_TYPES
    movs r2, #TYPE_WIDTH
    bl menu
    add sp, #KIND_TYPES * 4
    pop {pc}

@ r0 = the first type of kind VAR_0x8006: FIGHTING, or FIRE after ???.
first_type:
    ldr r0, p_var_8004
    ldrh r0, [r0, #4]
    movs r1, #KIND_TYPES + 1
    muls r0, r1
    adds r0, #TYPE_FIGHTING
    bx lr

set_type:
    push {r4, lr}
    bl first_type
    ldr r1, p_var_result
    ldrh r4, [r1]
    adds r0, r0, r4
    bl type_name
    ldr r0, p_var_8004
    ldrh r0, [r0, #4]
    lsls r0, r0, #3
    adds r0, r0, r4                     @ the type's number, 0 to 15
    lsls r0, r0, #2
    adds r0, #3
    bl set_ivs
    pop {r4, pc}
.endif

@ Each IV to 30 plus its bit of r0, from HP; then the stats.
set_ivs:
    push {r4, r5, r6, lr}
    sub sp, #4
    movs r6, r0
    bl chosen_mon
    movs r4, r0
    movs r5, #MON_DATA_HP_IV
1:  movs r0, #1
    ands r0, r6
    lsrs r6, r6, #1
    adds r0, #30
    str r0, [sp]
    movs r0, r4
    movs r1, r5
    mov r2, sp
    ldr r3, p_set_mon_data
    bl call_r3
    adds r5, #1
    cmp r5, #MON_DATA_HP_IV + STAT_COUNT
    bne 1b
    movs r0, r4
    ldr r3, p_calculate_stats
    bl call_r3
    add sp, #4
    pop {r4, r5, r6, pc}

@ The name of type r0 to gStringVar2.
type_name:
    movs r1, #TYPE_NAME_SIZE
    muls r1, r0
    ldr r0, p_type_names
    adds r1, r1, r0
    ldr r0, p_string_var_2
    ldr r3, p_string_copy
call_r3:
    bx r3

    .align 2
p_var_8004:        .word SPECIAL_VAR_8004
p_set_mon_data:    .word SET_MON_DATA
p_calculate_stats: .word CALCULATE_STATS
p_type_names:      .word TYPE_NAMES
p_string_var_2:    .word STRING_VAR_2
p_string_copy:     .word STRING_COPY
.if PICK == 0
p_get_mon_data:    .word GET_MON_DATA
p_all31_odd:       .word 0x685011A9
p_all31_even:      .word 0xF9426F72
    .include "personality.inc"
.else
p_var_result:      .word SPECIAL_VAR_RESULT

    .include "data.inc"
    .include "menu.inc"
.endif
    .include "mons.inc"
    .include "relocate.inc"

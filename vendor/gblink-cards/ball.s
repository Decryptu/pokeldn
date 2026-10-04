@ Poké Ball Changer. `ball_menu` offers page VAR_0x8006 of the POKé BALLS
@ named in `balls`, by the game's own item names: the first page ends with
@ MORE, which leads to the second. `set_ball` takes item VAR_RESULT of that
@ page: MORE sets VAR_0x8006 to 1 and VAR_RESULT to 1; a ball goes to the
@ Pokémon in gSpecialVar_0x8004, its name to gStringVar2, and VAR_RESULT
@ to 0.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ SET_MON_DATA, ITEMS, STRING_VAR_2, STRING_COPY, JAPANESE (1 on the Japanese
@ games) and those of menu.inc and relocate.inc; data.inc holds MORE.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
    .equ MON_DATA_POKEBALL, 38
.if JAPANESE
    .equ ITEM_SIZE, 0x28                @ struct Item, its name first
.else
    .equ ITEM_SIZE, 0x2C
.endif
    .equ FIRST_PAGE, 7                  @ balls before MORE
    .equ SECOND_PAGE, 4
    .equ MENU_WIDTH, 13                 @ tiles, for PREMIER BALL

ball_menu:
    push {r4, r5, lr}
    sub sp, #32
    ldr r0, p_var_8004
    ldrh r0, [r0, #4]                   @ VAR_0x8006: the page
    adr r4, balls
    movs r5, #FIRST_PAGE
    cmp r0, #0
    beq 1f
    adds r4, #FIRST_PAGE
    movs r5, #SECOND_PAGE
1:  movs r3, #0
2:  ldrb r0, [r4, r3]
    bl item_name
    lsls r1, r3, #2
    add r1, sp
    str r0, [r1]
    adds r3, #1
    cmp r3, r5
    bne 2b
    cmp r5, #FIRST_PAGE
    bne 3f
    adr r0, more_items
    lsls r1, r3, #2
    add r1, sp
    str r0, [r1]
    adds r5, #1
3:  mov r0, sp
    movs r1, r5
    movs r2, #MENU_WIDTH
    bl menu
    add sp, #32
    pop {r4, r5, pc}

set_ball:
    push {r4, lr}
    sub sp, #4
    ldr r3, p_var_8004
    ldrh r0, [r3, #4]                   @ the page
    ldr r1, p_var_result
    ldrh r1, [r1]                       @ the item
    cmp r0, #0
    bne 1f
    cmp r1, #FIRST_PAGE
    bne 2f
    movs r0, #1                         @ MORE
    strh r0, [r3, #4]
    b 9f
1:  adds r1, #FIRST_PAGE
2:  adr r0, balls
    ldrb r4, [r0, r1]
    str r4, [sp]
    bl chosen_mon
    movs r1, #MON_DATA_POKEBALL
    mov r2, sp
    ldr r3, p_set_mon_data
    bl call_r3
    movs r0, r4
    bl item_name
    movs r1, r0
    ldr r0, p_string_var_2
    ldr r3, p_string_copy
    bl call_r3
    movs r0, #0
9:  ldr r1, p_var_result
    strh r0, [r1]
    add sp, #4
    pop {r4, pc}

@ r0 = the name of item r0.
item_name:
    movs r1, #ITEM_SIZE
    muls r0, r1
    ldr r1, p_items
    adds r0, r0, r1
    bx lr

call_r3:
    bx r3

    .align 2
p_var_8004:     .word SPECIAL_VAR_8004
p_var_result:   .word SPECIAL_VAR_RESULT
p_set_mon_data: .word SET_MON_DATA
p_items:        .word ITEMS
p_string_var_2: .word STRING_VAR_2
p_string_copy:  .word STRING_COPY
@ POKé, GREAT, ULTRA, MASTER, NET, DIVE and NEST BALL, then REPEAT, TIMER,
@ LUXURY and PREMIER BALL: every ball but the SAFARI BALL.
balls:
    .byte 4, 3, 2, 1, 6, 7, 8, 9, 10, 11, 12
    .align 2

    .include "data.inc"
    .include "menu.inc"
    .include "mons.inc"
    .include "relocate.inc"

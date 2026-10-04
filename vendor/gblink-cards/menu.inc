@ `menu` shows the game's multichoice box at the top right, r2 tiles wide,
@ with r1 items (up to 8) named by the string pointers at r0, and leaves the
@ choice to the game's input task: after `waitstate` the script finds the
@ item's index in VAR_RESULT, or 127 for B. The box is built the way
@ DrawMultichoiceMenu (Emerald) and DrawVerticalMultichoiceMenu
@ (FireRed/LeafGreen) build theirs, with the item list at MENU_LIST. The
@ Japanese games' fonts are fixed-width, and the box is as wide as their own
@ make it for the longest item; r2 goes unused there.
@
@ Parameters (--defsym): EMERALD (1 on Emerald), JAPANESE (1 on the Japanese
@ games), SPECIAL_VAR_RESULT, MENU_LIST (room for 8 MenuActions),
@ CREATE_WINDOW_FROM_RECT, WINDOW_BORDER, PRINT_MENU_ITEMS (PrintMenuTable,
@ Japanese Emerald's PrintMenuActionTextsWithSpacing /
@ MultichoiceList_PrintItems), INIT_MENU_CURSOR (InitMenuInUpperLeftCornerNormal,
@ Japanese Emerald's InitMenuNormal / Menu_InitCursor), MULTICHOICE_TASK
@ (InitMultichoiceCheckWrap / CreateMCMenuInputHandlerTask) and
@ SCHEDULE_BG_COPY.
@
@ With MENU_LISTS set, `list_menu` is `menu` for r1 names that follow one
@ another from r0, each word-aligned (as data.inc lays them out).

    .equ MENU_RIGHT, 28                 @ the box ends at this column
    .equ MENU_ID, 2                     @ a multichoice id with no extras
    .equ FONT_NORMAL_FRLG, 2
    .equ FONT_NORMAL_EMERALD, 1
.if JAPANESE
    .equ TEXT_LEFT_FRLG, 11             @ past the cursor
.else
    .equ TEXT_LEFT_FRLG, 8
.endif

menu:
    push {r4, r5, r6, r7, lr}
    sub sp, #20
    movs r5, r1                         @ how many
    movs r7, r2                         @ the width
    ldr r6, menu_list
    movs r3, #0
1:  ldmia r0!, {r1}
    movs r2, #0
    stmia r6!, {r1, r2}                 @ MenuAction: text, func
    adds r3, #1
    cmp r3, r5
    bne 1b
.if JAPANESE
    ldr r0, menu_list
    movs r1, r5
    bl menu_width
    movs r7, r0
.endif
    ldr r6, menu_list
    movs r0, #MENU_RIGHT
    subs r0, r0, r7
    movs r1, #0                         @ the top row
    movs r2, r7
.if EMERALD
    lsls r3, r5, #1                     @ two rows an item
.else
    adr r3, menu_heights
    subs r4, r5, #1
    ldrb r3, [r3, r4]
.endif
    ldr r4, menu_create_window
    bl menu_call
    movs r7, r0                         @ the window
    movs r1, #0
    ldr r4, menu_border
    bl menu_call
.if EMERALD
.if JAPANESE
    movs r1, #16                        @ PrintMenuActionTextsWithSpacing(window,
    str r1, [sp, #0]                    @ font, 8, 2, 16, count, list, 0, 0)
    str r5, [sp, #4]
    str r6, [sp, #8]
    movs r1, #0
    str r1, [sp, #12]
    str r1, [sp, #16]
    movs r0, r7
    movs r1, #FONT_NORMAL_EMERALD
    movs r2, #8
    movs r3, #2
    ldr r4, menu_print
    bl menu_call
    movs r1, #16                        @ InitMenuNormal(window, font, 0, 2, 16,
    str r1, [sp, #0]                    @ count, 0)
    str r5, [sp, #4]
    movs r1, #0
    str r1, [sp, #8]
    movs r0, r7
    movs r1, #FONT_NORMAL_EMERALD
    movs r2, #0
    movs r3, #2
    ldr r4, menu_cursor
    bl menu_call
.else
    movs r0, r7
    movs r1, r5
    movs r2, r6
    ldr r4, menu_print
    bl menu_call
    movs r0, r7
    movs r1, r5
    movs r2, #0
    ldr r4, menu_cursor
    bl menu_call
.endif
    movs r0, #0
    ldr r4, menu_copy
    bl menu_call
.else
    movs r1, #14                        @ MultichoiceList_PrintItems(window, font,
    str r1, [sp, #0]                    @ TEXT_LEFT_FRLG, 2, 14, count, list, 0, 2)
    str r5, [sp, #4]
    str r6, [sp, #8]
    movs r1, #0
    str r1, [sp, #12]
    movs r1, #2
    str r1, [sp, #16]
    movs r0, r7
    movs r2, #TEXT_LEFT_FRLG
    movs r3, #2
    ldr r4, menu_print
    bl menu_call
    movs r1, #14                        @ Menu_InitCursor(window, font, 0, 2, 14,
    str r1, [sp, #0]                    @ count, 0)
    str r5, [sp, #4]
    movs r1, #0
    str r1, [sp, #8]
    movs r0, r7
    movs r1, #FONT_NORMAL_FRLG
    movs r2, #0
    movs r3, #2
    ldr r4, menu_cursor
    bl menu_call
.endif
    movs r0, #0                         @ B cancels
    movs r1, r5
    movs r2, r7
    movs r3, #MENU_ID
    ldr r4, menu_task
    bl menu_call
.if EMERALD == 0
    movs r0, #0
    ldr r4, menu_copy
    bl menu_call
.endif
    ldr r0, menu_result
    movs r1, #0xFF
    strh r1, [r0]
    add sp, #20
    pop {r4, r5, r6, r7, pc}

menu_call:
    bx r4

.if JAPANESE
@ The width in tiles of a box for the r1 MenuActions at r0: Emerald's is a
@ tile a character and one for the cursor, FireRed/LeafGreen's 11 pixels a
@ character and 11 for the cursor.
menu_width:
    push {r4, r5}
    movs r2, #0                         @ the longest name
1:  ldr r3, [r0]
    adds r0, #8
    movs r4, #0
2:  ldrb r5, [r3, r4]
    cmp r5, #0xFF
    beq 3f
    adds r4, #1
    b 2b
3:  cmp r4, r2
    bls 4f
    movs r2, r4
4:  subs r1, #1
    bne 1b
    adds r0, r2, #1
.if EMERALD == 0
    movs r1, #11
    muls r0, r1
    adds r0, #7
    lsrs r0, r0, #3
.endif
    pop {r4, r5}
    bx lr
.endif

.ifdef MENU_LISTS
list_menu:
    push {r4, lr}
    sub sp, #32
    movs r3, #0
1:  lsls r4, r3, #2
    add r4, sp
    str r0, [r4]
2:  ldrb r4, [r0]                       @ past the name's EOS, to the next word
    adds r0, #1
    cmp r4, #0xFF
    bne 2b
    adds r0, #3
    lsrs r0, r0, #2
    lsls r0, r0, #2
    adds r3, #1
    cmp r3, r1
    bne 1b
    mov r0, sp
    bl menu
    add sp, #32
    pop {r4, pc}
.endif

    .align 2
menu_list:          .word MENU_LIST
menu_result:        .word SPECIAL_VAR_RESULT
menu_create_window: .word CREATE_WINDOW_FROM_RECT
menu_border:        .word WINDOW_BORDER
menu_print:         .word PRINT_MENU_ITEMS
menu_cursor:        .word INIT_MENU_CURSOR
menu_task:          .word MULTICHOICE_TASK
menu_copy:          .word SCHEDULE_BG_COPY
.if EMERALD == 0
menu_heights:       .byte 2, 4, 6, 7, 9, 11, 13, 14   @ GetMCWindowHeight for 1-8 items
.endif
    .align 2

@ Unown Letter Changer. `type_letter` opens the naming screen for the UNOWN
@ in gSpecialVar_0x8004, with gStringVar2 for the text, and returns to the
@ script. `change_letter` takes what was typed, spaces aside: one character
@ (A to Z in either case, ! or ?) gives the UNOWN a personality of that
@ letter that keeps its nature and whether it is shiny, and the letter goes
@ to gStringVar2. VAR_RESULT = 1 when it changed, 0 when nothing was typed, or
@ 2 when it was not one of those characters alone.
@
@ The letter of personality p is ((p >> 24 & 3) << 6 | (p >> 16 & 3) << 4 |
@ (p >> 8 & 3) << 2 | p & 3) % 28. The tries take the low half from Random(),
@ and the high half too, or for a shiny UNOWN the low half ^ its old high ^
@ low ^ 0 to 7, which keeps it shiny and still reaches every letter with
@ every nature; 65536 tries only bound the search.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ STRING_VAR_2, RANDOM, DO_NAMING_SCREEN, CB2_RETURN_TO_SCRIPT
@ (CB2_ReturnToFieldContinueScriptPlayMapMusic) and those of personality.inc
@ and relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
    .set MONS_ORDER, 1
    .set PERSONALITY_SET_ONLY, 1
    .equ NAMING_SCREEN_NICKNAME, 3
    .equ MON_GENDERLESS, 0xFF
    .equ CHAR_A, 0xBB                   @ then B to Z, then a to z
    .equ CHAR_EXCLAMATION, 0xAB
    .equ CHAR_QUESTION, 0xAC
    .equ EOS, 0xFF
    .equ LETTERS, 28
    .equ NO_LETTER, 0
    .equ CHANGED, 1
    .equ NOT_ONE_LETTER, 2
    .equ CHAR_SPACE, 0x00
    .equ TARGET, 0                      @ change_letter's frame
    .equ SHINY_X, 4                     @ the old high ^ low if shiny, else -1
    .equ ID_X, 8                        @ trainer id ^ secret id
    .equ TRIES, 12
    .equ FRAME, 16

type_letter:
    push {r4, lr}
    sub sp, #8
    bl chosen_mon
    ldr r0, [r0, #MON_PERSONALITY]
    str r0, [sp]
    ldr r0, p_return
    str r0, [sp, #4]
    ldr r1, p_string_var_2
    movs r0, #EOS
    strb r0, [r1]                       @ an empty text to start with
    movs r0, #NAMING_SCREEN_NICKNAME
    movs r2, #SPECIES_UNOWN
    movs r3, #MON_GENDERLESS
    ldr r4, p_do_naming_screen
    bl call_r4
    add sp, #8
    pop {r4, pc}

change_letter:
    push {r4, r5, r6, r7, lr}
    sub sp, #FRAME
    ldr r1, p_string_var_2
    movs r2, #0                         @ characters typed, spaces aside
    movs r3, r1
10: ldrb r4, [r3]
    adds r3, #1
    cmp r4, #EOS
    beq 11f
    cmp r4, #CHAR_SPACE
    beq 10b
    movs r0, r4
    adds r2, #1
    b 10b
11: cmp r2, #1
    beq 12f
    movs r0, #NO_LETTER                 @ nothing typed
    bcc 9f
    movs r0, #NOT_ONE_LETTER
    b 9f
12: movs r2, r0
    subs r2, #CHAR_A
    cmp r2, #26
    bcc 13f                             @ A to Z
    subs r2, #26
    cmp r2, #26
    bcc 13f                             @ a to z
    movs r2, #26
    cmp r0, #CHAR_EXCLAMATION
    beq 13f
    movs r2, #27
    cmp r0, #CHAR_QUESTION
    beq 13f
    movs r0, #NOT_ONE_LETTER
    b 9f
13: str r2, [sp, #TARGET]
    movs r0, #CHAR_A
    cmp r2, #26
    bcc 14f
    movs r0, #CHAR_EXCLAMATION - 26
14: adds r0, r0, r2
    strb r0, [r1]                       @ the letter, as a capital
    movs r0, #EOS
    strb r0, [r1, #1]
    bl chosen_mon
    movs r4, r0
    ldr r6, [r4, #MON_PERSONALITY]
    movs r0, r6
    movs r1, #25
    bl umod
    movs r5, r0                         @ the nature
    ldr r0, [r4, #MON_OT_ID]
    lsrs r1, r0, #16
    eors r0, r1
    lsls r0, r0, #16
    lsrs r0, r0, #16
    str r0, [sp, #ID_X]
    lsrs r1, r6, #16
    eors r1, r6
    lsls r1, r1, #16
    lsrs r1, r1, #16
    eors r0, r1
    cmp r0, #8
    bcc 3f                              @ shiny
    movs r1, #0
    mvns r1, r1
3:  str r1, [sp, #SHINY_X]
    movs r0, #0
    str r0, [sp, #TRIES]
4:  ldr r3, p_random
    bl call_r3
    movs r7, r0                         @ the low half
    ldr r3, p_random
    bl call_r3
    ldr r1, [sp, #SHINY_X]
    adds r2, r1, #1
    beq 5f
    lsls r0, r0, #29
    lsrs r0, r0, #29
    eors r0, r1
    eors r0, r7                         @ the high half, as shiny as before
    b 6f
5:  movs r1, r0
    eors r1, r7
    ldr r2, [sp, #ID_X]
    eors r1, r2
    cmp r1, #8
    bcc 7f                              @ it would be shiny
6:  lsls r0, r0, #16
    orrs r7, r0                         @ the personality to try
    movs r0, r7
    movs r1, #25
    bl umod
    cmp r0, r5
    bne 7f
    bl letter_of
    ldr r1, [sp, #TARGET]
    cmp r0, r1
    beq 8f
7:  ldr r0, [sp, #TRIES]
    adds r0, #1
    str r0, [sp, #TRIES]
    lsrs r0, r0, #16
    beq 4b
    movs r0, #NO_LETTER
    b 9f
8:  movs r0, r4
    movs r1, r7
    bl set_personality
    movs r0, #CHANGED
9:  ldr r1, p_var_result
    strh r0, [r1]
    add sp, #FRAME
    pop {r4, r5, r6, r7, pc}

@ r0 = the letter of personality r7.
letter_of:
    movs r0, #0
    movs r1, #24
1:  lsls r0, r0, #2
    movs r2, r7
    lsrs r2, r1
    movs r3, #3
    ands r2, r3
    orrs r0, r2
    subs r1, #8
    bpl 1b
    movs r1, #LETTERS
    b umod

call_r3:
    bx r3

call_r4:
    bx r4

    .align 2
p_var_result:       .word SPECIAL_VAR_RESULT
p_string_var_2:     .word STRING_VAR_2
p_random:           .word RANDOM
p_do_naming_screen: .word DO_NAMING_SCREEN
p_return:           .word CB2_RETURN_TO_SCRIPT

    .include "personality.inc"
    .include "mons.inc"
    .include "relocate.inc"

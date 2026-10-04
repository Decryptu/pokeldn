@ IV/EV Stat Judge: writes the text about the chosen party Pokémon (slot in
@ gSpecialVar_0x8004) to TEXT_BUFFER.
@
@ The text is `template` from data.inc with placeholders: FD 00 nickname,
@ FD 01 nature, FD 10+n value n, FD 30 / FD 31 `stat_lines` for the IVs / EVs.
@ The values are the six IVs, the six EVs (HP, Attack, Defense, Speed, Sp. Atk,
@ Sp. Def) and the EV total; inside `stat_lines`, FD 10+n is stat n of that set.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, TEXT_BUFFER, GET_MON_DATA,
@ GET_NATURE, NATURE_NAMES (&gNatureNamePointers) and those of relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ MON_SIZE, 100
    .equ MON_DATA_NICKNAME, 2
    .equ MON_DATA_HP_EV, 26
    .equ MON_DATA_HP_IV, 39
    .equ STAT_COUNT, 6
    .equ PLACEHOLDER, 0xFD
    .equ EOS, 0xFF
    .equ CHAR_0, 0xA1
    .equ VALUE, 0x10
    .equ STAT_LINES_IVS, 0x30
    .equ RETURN_TO, 28                  @ stack frame: 13 values, then the template
    .equ FRAME, 32                      @ position to return to after stat_lines

judge:
    push {r4, r5, r6, r7, lr}
    sub sp, #FRAME
    ldr r0, p_var_8004
    ldrh r0, [r0]
    movs r1, #MON_SIZE
    muls r0, r1
    ldr r4, p_party
    adds r4, r4, r0                     @ the Pokémon

    movs r5, #0                         @ the value
    movs r7, #0                         @ the EV total
1:  movs r1, #MON_DATA_HP_IV
    cmp r5, #STAT_COUNT
    bcc 2f
    movs r1, #MON_DATA_HP_EV - STAT_COUNT
2:  adds r1, r1, r5
    movs r0, r4
    ldr r3, p_get_mon_data
    bl call_r3
    lsls r1, r5, #1
    mov r2, sp
    strh r0, [r2, r1]
    cmp r5, #STAT_COUNT
    bcc 3f
    adds r7, r7, r0
3:  adds r5, #1
    cmp r5, #STAT_COUNT * 2
    bne 1b
    mov r2, sp
    strh r7, [r2, #STAT_COUNT * 4]

    movs r0, #0
    str r0, [sp, #RETURN_TO]
    adr r5, template
    ldr r6, p_text_buffer
    movs r7, #0                         @ byte offset of value 0 (12 in the EV lines)
4:  ldrb r0, [r5]
    adds r5, #1
    cmp r0, #PLACEHOLDER
    beq 6f
    cmp r0, #EOS
    bne 5f
    ldr r1, [sp, #RETURN_TO]
    cmp r1, #0
    beq 5f                              @ end of the text
    movs r5, r1                         @ end of stat_lines: back to the template
    movs r7, #0
    str r7, [sp, #RETURN_TO]
    b 4b
5:  strb r0, [r6]
    adds r6, #1
    cmp r0, #EOS
    bne 4b
    add sp, #FRAME
    pop {r4, r5, r6, r7}
    pop {r0}
    bx r0

6:  ldrb r0, [r5]
    adds r5, #1
    cmp r0, #STAT_LINES_IVS
    bcs 10f
    cmp r0, #VALUE
    bcs 9f
    cmp r0, #0
    bne 8f
    movs r0, r4                         @ the nickname, EGG for an Egg
    movs r1, #MON_DATA_NICKNAME
    movs r2, r6
    ldr r3, p_get_mon_data
    bl call_r3
7:  ldrb r0, [r6]
    cmp r0, #EOS
    beq 4b
    adds r6, #1
    b 7b
8:  movs r0, r4                         @ the nature
    ldr r3, p_get_nature
    bl call_r3
    lsls r0, r0, #2
    ldr r1, p_nature_names
    ldr r1, [r1, r0]
    bl put_string
    b 4b
9:  subs r0, #VALUE
    lsls r0, r0, #1
    adds r0, r0, r7
    mov r1, sp
    ldrh r0, [r1, r0]
    bl put_number
    b 4b
10: subs r0, #STAT_LINES_IVS            @ 0 for the IVs, 1 for the EVs
    movs r7, #STAT_COUNT * 2
    muls r7, r0
    str r5, [sp, #RETURN_TO]
    adr r5, stat_lines
    b 4b

@ Copies the string at r1 to r6, without its terminator.
put_string:
    ldrb r0, [r1]
    cmp r0, #EOS
    beq 1f
    strb r0, [r6]
    adds r1, #1
    adds r6, #1
    b put_string
1:  bx lr

@ Writes r0 in decimal at r6, without leading zeros.
put_number:
    push {r4, r5, lr}
    movs r4, #0                         @ set once a digit is written
    adr r5, powers_of_ten
1:  ldrh r1, [r5]
    adds r5, #2
    cmp r1, #1
    beq 4f
    movs r2, #0
2:  cmp r0, r1
    bcc 3f
    subs r0, r0, r1
    adds r2, #1
    b 2b
3:  orrs r4, r2
    beq 1b
    adds r2, #CHAR_0
    strb r2, [r6]
    adds r6, #1
    b 1b
4:  adds r0, #CHAR_0
    strb r0, [r6]
    adds r6, #1
    pop {r4, r5}
    pop {r0}
    bx r0

call_r3:
    bx r3

    .align 2
p_party:        .word PARTY
p_var_8004:     .word SPECIAL_VAR_8004
p_text_buffer:  .word TEXT_BUFFER
p_get_mon_data: .word GET_MON_DATA
p_get_nature:   .word GET_NATURE
p_nature_names: .word NATURE_NAMES
powers_of_ten:  .hword 1000, 100, 10, 1

    .include "data.inc"
    .include "relocate.inc"

@ Nickname Change: routines for the party Pokémon in gSpecialVar_0x8004.
@ `nicknamed` sets VAR_RESULT to 1 when its nickname differs from its species
@ name; `unname` sets the nickname back to the species name. Renaming itself
@ uses the game's ChangePokemonNickname special. The game knows its species
@ names only in its own language: a Pokémon from another language's game
@ counts as having none to take back.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ TEXT_BUFFER (scratch), GET_MON_DATA, SET_MON_DATA, GET_SPECIES_NAME,
@ GAME_LANGUAGE (the game's language number) and those of relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ MON_DATA_NICKNAME, 2
    .equ MON_DATA_LANGUAGE, 3
    .equ MON_DATA_SPECIES, 11
    .equ NICKNAME_AT, 0x20              @ in TEXT_BUFFER, after the species name
    .equ EOS, 0xFF

nicknamed:
    push {r4, lr}
    bl species_name
    movs r0, r4
    movs r1, #MON_DATA_LANGUAGE
    ldr r3, p_get_mon_data
    bl call_r3
    cmp r0, #GAME_LANGUAGE
    beq 4f
    movs r0, #0
    b 3f
4:  movs r0, r4
    movs r1, #MON_DATA_NICKNAME
    ldr r2, p_text_buffer
    adds r2, #NICKNAME_AT
    ldr r3, p_get_mon_data
    bl call_r3
    ldr r0, p_text_buffer
    movs r1, r0
    adds r1, #NICKNAME_AT
1:  ldrb r2, [r0]
    ldrb r3, [r1]
    cmp r2, r3
    bne 2f
    adds r0, #1
    adds r1, #1
    cmp r2, #EOS
    bne 1b
    movs r0, #0
    b 3f
2:  movs r0, #1
3:  ldr r1, p_var_result
    strh r0, [r1]
    pop {r4}
    pop {r0}
    bx r0

unname:
    push {r4, lr}
    bl species_name
    movs r0, r4
    movs r1, #MON_DATA_NICKNAME
    ldr r2, p_text_buffer
    ldr r3, p_set_mon_data
    bl call_r3
    pop {r4}
    pop {r0}
    bx r0

@ r4 = the chosen Pokémon; its species name goes to TEXT_BUFFER.
species_name:
    push {lr}
    ldr r0, p_var_8004
    ldrh r0, [r0]
    movs r1, #MON_SIZE
    muls r0, r1
    ldr r4, p_party
    adds r4, r4, r0
    movs r0, r4
    movs r1, #MON_DATA_SPECIES
    ldr r3, p_get_mon_data
    bl call_r3
    movs r1, r0
    ldr r0, p_text_buffer
    ldr r3, p_get_species_name
    bl call_r3
    pop {r0}
    bx r0

call_r3:
    bx r3

    .align 2
p_party:            .word PARTY
p_var_8004:         .word SPECIAL_VAR_8004
p_var_result:       .word SPECIAL_VAR_RESULT
p_text_buffer:      .word TEXT_BUFFER
p_get_mon_data:     .word GET_MON_DATA
p_set_mon_data:     .word SET_MON_DATA
p_get_species_name: .word GET_SPECIES_NAME

    .include "mons.inc"
    .include "relocate.inc"

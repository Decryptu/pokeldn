@ Pokémon Gender Change. `switch_gender` gives the Pokémon in
@ gSpecialVar_0x8004 the other gender: a personality whose low byte is on the
@ other side of its species' gender ratio (female below it) with the same
@ ability bit, and the same nature and shininess. VAR_RESULT = 1 when it is
@ now male, 2 when female, 0 when its species has one gender or none.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ SPECIES_INFO, GET_MON_DATA and those of personality.inc and relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_ORDER, 1
    .set MONS_CHOSEN, 1
    .equ SPECIES_INFO_SIZE, 0x1C
    .equ GENDER_RATIO, 0x10
    .equ MON_MALE, 0
    .equ MON_FEMALE, 254

switch_gender:
    push {r4, r5, r6, lr}
    bl chosen_mon
    movs r4, r0
    movs r1, #MON_DATA_SPECIES
    ldr r3, p_get_mon_data
    bl call_r3
    movs r1, #SPECIES_INFO_SIZE
    muls r0, r1
    ldr r1, p_species_info
    adds r0, r0, r1
    ldrb r2, [r0, #GENDER_RATIO]
    movs r6, #0
    cmp r2, #MON_MALE
    beq 9f
    cmp r2, #MON_FEMALE
    bcs 9f                              @ one gender or none
    ldrb r5, [r4, #MON_PERSONALITY]
    movs r1, r2
    eors r1, r5
    movs r0, #1
    ands r1, r0                         @ 1 if the ratio's bit 0 is not the byte's
    movs r6, #1
    cmp r5, r2
    bcc 1f
    subs r2, #2                         @ male now: just below the ratio
    movs r6, #2
1:  adds r5, r2, r1                     @ else the ratio itself or one above
    ldr r0, [r4, #MON_PERSONALITY]
    movs r1, #25
    bl umod
    movs r2, r0
    movs r1, r5
    movs r0, r4
    bl repersonalize
    cmp r0, #0
    bne 9f
    movs r6, #0
9:  ldr r1, p_var_result
    strh r6, [r1]
    pop {r4, r5, r6, pc}

call_r3:
    bx r3

    .align 2
p_var_result:   .word SPECIAL_VAR_RESULT
p_get_mon_data: .word GET_MON_DATA
p_species_info: .word SPECIES_INFO

    .include "personality.inc"
    .include "mons.inc"
    .include "relocate.inc"

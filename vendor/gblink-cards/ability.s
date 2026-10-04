@ Ability Capsule. `switch_ability` gives the Pokémon in gSpecialVar_0x8004 its
@ species' other ability: a personality with the other ability bit and the
@ same nature, gender and shininess, and abilityNum to match. The low byte
@ decides the gender against the species' gender ratio (female below it), so
@ where flipping bit 0 would cross the ratio the byte moves one step the other
@ way instead. VAR_RESULT = 1 with the ability's name in gStringVar2, or 0 when
@ the species has one ability.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ STRING_VAR_2, SPECIES_INFO, ABILITY_NAMES, GET_MON_DATA, SET_MON_DATA,
@ STRING_COPY, JAPANESE (1 on the Japanese games) and those of personality.inc
@ and relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_ORDER, 1
    .set MONS_CHOSEN, 1
    .equ SPECIES_INFO_SIZE, 0x1C
    .equ GENDER_RATIO, 0x10
    .equ ABILITIES, 0x16
.if JAPANESE
    .equ ABILITY_NAME_SIZE, 8
.else
    .equ ABILITY_NAME_SIZE, 13
.endif
    .equ MON_DATA_ABILITY_NUM, 46
    .equ MON_MALE, 0
    .equ MON_FEMALE, 254

switch_ability:
    push {r4, r5, r6, r7, lr}
    sub sp, #4
    bl chosen_mon
    movs r4, r0
    movs r1, #MON_DATA_SPECIES
    ldr r3, p_get_mon_data
    bl call_r3
    movs r1, #SPECIES_INFO_SIZE
    muls r0, r1
    ldr r1, p_species_info
    adds r6, r0, r1                     @ its species info
    movs r0, #0
    ldrb r1, [r6, #ABILITIES + 1]
    cmp r1, #0
    beq 9f                              @ one ability
    ldrb r5, [r4, #MON_PERSONALITY]     @ the low byte
    movs r7, #1
    eors r7, r5                         @ with the other ability bit
    ldrb r2, [r6, #GENDER_RATIO]
    cmp r2, #MON_MALE
    beq 2f
    cmp r2, #MON_FEMALE
    bcs 2f                              @ one gender or none: any byte will do
    cmp r5, r2
    sbcs r0, r0                         @ -1 if female
    cmp r7, r2
    sbcs r1, r1
    cmp r0, r1
    beq 2f
    subs r7, r5, #1                     @ it would cross: step away from the ratio
    lsrs r0, r5, #1
    bcc 2f
    adds r7, r5, #1
2:  ldr r0, [r4, #MON_PERSONALITY]
    movs r1, #25
    bl umod
    movs r2, r0                         @ the same nature
    movs r1, r7
    movs r0, r4
    bl repersonalize
    cmp r0, #0
    beq 9f
    movs r0, #1
    ands r7, r0
    str r7, [sp]
    movs r0, r4
    movs r1, #MON_DATA_ABILITY_NUM
    mov r2, sp
    ldr r3, p_set_mon_data
    bl call_r3
    adds r6, #ABILITIES
    ldrb r1, [r6, r7]
    movs r0, #ABILITY_NAME_SIZE
    muls r1, r0
    ldr r0, p_ability_names
    adds r1, r1, r0
    ldr r0, p_string_var_2
    ldr r3, p_string_copy
    bl call_r3
    movs r0, #1
9:  ldr r1, p_var_result
    strh r0, [r1]
    add sp, #4
    pop {r4, r5, r6, r7, pc}

call_r3:
    bx r3

    .align 2
p_var_result:    .word SPECIAL_VAR_RESULT
p_get_mon_data:  .word GET_MON_DATA
p_set_mon_data:  .word SET_MON_DATA
p_species_info:  .word SPECIES_INFO
p_ability_names: .word ABILITY_NAMES
p_string_var_2:  .word STRING_VAR_2
p_string_copy:   .word STRING_COPY

    .include "personality.inc"
    .include "mons.inc"
    .include "relocate.inc"

@ Instant Eggs. The script hatches one Egg at a time with the game's EggHatch
@ special, which reads the party slot from gSpecialVar_0x8004, or has the Day
@ Care's Egg ready at once.
@
@ `prepare` counts the party's Eggs into VAR_RESULT and resets the search.
@ `next_egg` finds the next Egg after gSpecialVar_0x8004, stores its slot there
@ and sets VAR_RESULT to 1, or to 0 when there are no more.
@
@ `daycare_egg` has the game's TriggerPendingDaycareEgg make the Day Care's
@ Egg ready now when its two Pokémon can have one (GetDaycareCompatibilityScore
@ above 0). VAR_RESULT = 1 when it did, else 0.
@
@ Parameters (--defsym): PARTY (&gPlayerParty), SPECIAL_VAR_8004
@ (&gSpecialVar_0x8004), SPECIAL_VAR_RESULT (&gSpecialVar_Result), SB1_PTR,
@ DAYCARE (its offset in SaveBlock1), DAYCARE_COMPATIBILITY,
@ TRIGGER_DAYCARE_EGG and those of relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

prepare:
    ldr r0, p_var_8004
    movs r1, #0
    subs r1, #1
    strh r1, [r0]                       @ 0xFFFF: start before slot 0
    ldr r0, p_party
    movs r1, #0                         @ Eggs found
    movs r2, #PARTY_SIZE
1:  ldrb r3, [r0, #MON_FLAGS]
    lsls r3, r3, #29
    lsrs r3, r3, #29
    cmp r3, #AN_EGG
    bne 2f
    adds r1, #1
2:  adds r0, #MON_SIZE
    subs r2, #1
    bne 1b
    ldr r0, p_var_result
    strh r1, [r0]
    bx lr

next_egg:
    ldr r3, p_var_8004
    ldrh r2, [r3]
    adds r2, #1
    lsls r2, r2, #16
    lsrs r2, r2, #16                    @ the slot after the last Egg
    movs r1, #MON_SIZE
    muls r1, r2
    ldr r0, p_party
    adds r0, r0, r1
1:  cmp r2, #PARTY_SIZE
    bcs 3f
    ldrb r1, [r0, #MON_FLAGS]
    lsls r1, r1, #29
    lsrs r1, r1, #29
    cmp r1, #AN_EGG
    beq 2f
    adds r0, #MON_SIZE
    adds r2, #1
    b 1b
2:  strh r2, [r3]
    movs r0, #1
    b 4f
3:  movs r0, #0
4:  ldr r1, p_var_result
    strh r0, [r1]
    bx lr

daycare_egg:
    push {lr}
    ldr r0, p_sb1_ptr
    ldr r0, [r0]
    ldr r1, p_daycare
    adds r0, r0, r1
    ldr r3, p_compatibility
    bl call_r3
    cmp r0, #0
    beq 1f
    ldr r3, p_trigger_egg
    bl call_r3
    movs r0, #1
1:  ldr r1, p_var_result
    strh r0, [r1]
    pop {pc}

call_r3:
    bx r3

    .align 2
p_party:         .word PARTY
p_var_8004:      .word SPECIAL_VAR_8004
p_var_result:    .word SPECIAL_VAR_RESULT
p_sb1_ptr:       .word SB1_PTR
p_daycare:       .word DAYCARE
p_compatibility: .word DAYCARE_COMPATIBILITY
p_trigger_egg:   .word TRIGGER_DAYCARE_EGG

    .include "mons.inc"
    .include "relocate.inc"

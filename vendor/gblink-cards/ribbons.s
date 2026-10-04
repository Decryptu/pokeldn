@ Gift Ribbons. `give_ribbons` gives every party Pokémon that is not an Egg the
@ seven gift ribbons (Marine to World), and names each ribbon that has no
@ caption yet in SaveBlock1's giftRibbons, which the summary screen reads its
@ caption from; a caption from a real event stays.
@
@ Parameters (--defsym): SB1_PTR, PARTY, GIFT_RIBBONS (its offset in
@ SaveBlock1), SET_MON_DATA.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ GIFT_RIBBON_COUNT, 7
    .equ MON_DATA_MARINE_RIBBON, 72

give_ribbons:
    push {r4, r5, r6, lr}
    sub sp, #4
    ldr r4, p_sb1_ptr
    ldr r4, [r4]
    ldr r0, p_gift_ribbons
    adds r4, r4, r0
    adr r5, captions
    movs r6, #0
1:  ldrb r0, [r4, r6]
    cmp r0, #0
    bne 2f
    ldrb r0, [r5, r6]
    strb r0, [r4, r6]
2:  adds r6, #1
    cmp r6, #GIFT_RIBBON_COUNT
    bne 1b
    movs r0, #1
    str r0, [sp]
    ldr r4, p_party
    movs r5, #PARTY_SIZE
3:  ldrb r0, [r4, #MON_FLAGS]
    lsls r0, r0, #29
    lsrs r0, r0, #29
    cmp r0, #A_POKEMON
    bne 5f
    movs r6, #MON_DATA_MARINE_RIBBON
4:  movs r0, r4
    movs r1, r6
    mov r2, sp
    ldr r3, p_set_mon_data
    bl call_r3
    adds r6, #1
    cmp r6, #MON_DATA_MARINE_RIBBON + GIFT_RIBBON_COUNT
    bne 4b
5:  adds r4, #MON_SIZE
    subs r5, #1
    bne 3b
    add sp, #4
    pop {r4, r5, r6, pc}

call_r3:
    bx r3

    .align 2
p_sb1_ptr:      .word SB1_PTR
p_gift_ribbons: .word GIFT_RIBBONS
p_party:        .word PARTY
p_set_mon_data: .word SET_MON_DATA
@ gGiftRibbonDescriptionPointers entries (from 1): Summer Holidays, Evergreen,
@ Special Holiday, Lots of Friends, Hard Worker, Full of Energy, and "A
@ commemorative RIBBON for a loved POKéMON."
captions:       .byte 55, 58, 59, 61, 60, 62, 63
    .align 2

    .include "mons.inc"

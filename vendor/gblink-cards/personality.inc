@ `repersonalize` gives the Pokémon at r0 a new personality whose low byte (its
@ gender and ability bit) is r1 and whose nature is r2, with the IVs that go
@ with it, and re-encrypts, reorders and recalculates it to match; r0 = 1, or 0
@ if no such personality turned up. PKHeX wants a wild Pokémon's PID and IVs
@ to be one frame of the random number generator (Method 1: the PID's low
@ half, its high half, then two words of IVs), so the search walks the
@ generator: for each second byte, every first number whose high half is that
@ low half, the second number then giving the high half. A shiny Pokémon only
@ takes high halves that keep it shiny, and an Unown only those, and second
@ bytes, that keep its letter.
@
@ With REP_KEEP_ORDER set (a card that keeps the low byte's low 3 bits), the
@ PID also keeps its remainder by 24, the order of the secure data, which then
@ only needs XORing with the change of key; then MONS_ORDER's table can go.
@ With PERSONALITY_SET_ONLY set, the include holds `set_personality` instead,
@ which gives the Pokémon at r0 personality r1 the same way, IVs as they were.
@
@ Parameters (--defsym): GET_MON_DATA, SET_MON_DATA, CALCULATE_STATS. Needs
@ mons.inc with MONS_ORDER.

    .equ REP_NATURE, 48                 @ frame: 48 bytes of reordered data, then
    .equ REP_LOW, 52
    .equ REP_TRAINER, 56                @ the trainer id's halves XORed, or -1 if not shiny
    .equ REP_CANDIDATE, 60
    .equ REP_IVS, 64
    .equ REP_OLD, 68
    .equ REP_LETTER, 76                 @ the PID bits an Unown's letter is made of
    .equ REP_ORDER, 80                  @ the old personality % 24
    .equ REP_FRAME, 84
    .equ LCG_MUL, 0x41C64E6D
    .equ LCG_ADD, 0x6073
    .equ MON_DATA_HP_IV, 39             @ then ATTACK, DEFENSE, SPEED, SP. ATK, SP. DEF
    .equ SPECIES_UNOWN, 201
    .equ MON_DATA_SPECIES, 11

.ifdef PERSONALITY_SET_ONLY
set_personality:
    push {r4, r5, r6, r7, lr}
    sub sp, #REP_FRAME
    movs r5, r0
    movs r7, r1
    ldr r6, [r5, #MON_PERSONALITY]
.else
repersonalize:
    push {r4, r5, r6, r7, lr}
    sub sp, #REP_FRAME
    movs r5, r0
    str r1, [sp, #REP_LOW]
    str r2, [sp, #REP_NATURE]
    ldr r6, [r5, #MON_PERSONALITY]
    str r6, [sp, #REP_OLD]
.ifdef REP_KEEP_ORDER
    movs r0, r6
    movs r1, #24
    bl umod
    str r0, [sp, #REP_ORDER]
.endif
    ldrh r0, [r5, #MON_OT_ID]
    ldrh r1, [r5, #MON_OT_ID + 2]
    eors r0, r1
    lsrs r1, r6, #16
    eors r1, r0
    lsls r2, r6, #16
    lsrs r2, r2, #16
    eors r1, r2                         @ its shiny value
    cmp r1, #8
    bcc 1f
    movs r0, #0
    mvns r0, r0
1:  str r0, [sp, #REP_TRAINER]
    movs r0, r5
    movs r1, #MON_DATA_SPECIES
    ldr r3, rep_get_mon_data
    bl rep_call
    ldr r7, [sp, #REP_LOW]              @ the low half, second byte 0
    movs r2, #0
    cmp r0, #SPECIES_UNOWN
    bne 2f
    ldr r2, rep_letter
2:  str r2, [sp, #REP_LETTER]
3:  lsls r6, r7, #16                    @ the first number
    ldr r1, rep_lcg_mul
    movs r4, r6
    muls r4, r1
    ldr r2, rep_lcg_add
    adds r4, r2                         @ the second
@ The next first number is 1 more, so the next second is the multiplier more.
4:  adds r6, #1
    ldr r1, rep_lcg_mul
    adds r4, r1
    lsrs r0, r6, #16
    cmp r0, r7
    bne 6f                              @ all of this low half's tried
    lsrs r0, r4, #16                    @ the high half
    ldr r2, [sp, #REP_TRAINER]
    adds r3, r2, #1
    beq 5f
    eors r2, r0
    eors r2, r7
    cmp r2, #8
    bcs 4b                              @ not shiny
5:  lsls r0, r0, #16
    orrs r0, r7                         @ the PID
    ldr r2, [sp, #REP_OLD]
    eors r2, r0
    ldr r3, [sp, #REP_LETTER]
    tst r2, r3
    bne 4b                              @ another letter
    str r0, [sp, #REP_CANDIDATE]
    movs r1, #25
    bl umod
    ldr r1, [sp, #REP_NATURE]
    cmp r0, r1
    bne 4b
.ifdef REP_KEEP_ORDER
    ldr r0, [sp, #REP_CANDIDATE]
    movs r1, #24
    bl umod
    ldr r1, [sp, #REP_ORDER]
    cmp r0, r1
    bne 4b                              @ its data would need reordering
.endif
    ldr r1, rep_lcg_mul
    ldr r2, rep_lcg_add
    movs r0, r4
    muls r0, r1
    adds r0, r2
    movs r3, r0
    muls r3, r1
    adds r3, r2
    lsls r0, r0, #1
    lsrs r0, r0, #17                    @ HP, ATTACK, DEFENSE
    lsls r3, r3, #1
    lsrs r3, r3, #17
    lsls r3, r3, #15                    @ SPEED, SP. ATK, SP. DEF
    orrs r0, r3
    str r0, [sp, #REP_IVS]
    ldr r7, [sp, #REP_CANDIDATE]
    ldr r6, [sp, #REP_OLD]
    b 7f
6:  adds r7, #255
    adds r7, #1                         @ the next second byte
    lsrs r0, r7, #16
    beq 3b
    movs r0, #0
    b 9f
7:
.endif
.ifdef REP_KEEP_ORDER
    movs r1, r6
    eors r1, r7                         @ the key changes by old ^ new personality
    movs r0, r5
    adds r0, #MON_SECURE
    movs r2, #44
1:  ldr r3, [r0, r2]
    eors r3, r1
    str r3, [r0, r2]
    subs r2, #4
    bpl 1b
.else
    movs r0, r6
    bl rep_order
    str r0, [sp, #REP_NATURE]           @ from here: the old order
    movs r0, r7
    bl rep_order
    str r0, [sp, #REP_LOW]              @ and the new one
    movs r4, #0                         @ 2 × the substructure number
3:  ldr r0, [sp, #REP_NATURE]
    lsrs r0, r4
    movs r3, #3
    ands r0, r3
    movs r2, #SUBSTRUCT_SIZE
    muls r0, r2
    adds r0, #MON_SECURE
    adds r0, r5, r0                     @ from its old place
    ldr r1, [sp, #REP_LOW]
    lsrs r1, r4
    ands r1, r3
    muls r1, r2
    add r1, sp                          @ to its new place in the frame
    movs r2, #3
4:  ldr r3, [r0]
    eors r3, r6                         @ the key changes by old ^ new personality
    eors r3, r7
    str r3, [r1]
    adds r0, #4
    adds r1, #4
    subs r2, #1
    bne 4b
    adds r4, #2
    cmp r4, #8
    bne 3b
    mov r1, sp
    movs r0, r5
    adds r0, #MON_SECURE
    movs r2, #44
5:  ldr r3, [r1, r2]
    str r3, [r0, r2]
    subs r2, #4
    bpl 5b
.endif
    str r7, [r5, #MON_PERSONALITY]
.ifndef PERSONALITY_SET_ONLY
    movs r4, #0                         @ IV number r4, 5 bits each
3:  ldr r0, [sp, #REP_IVS]
    lsrs r1, r0, #5
    str r1, [sp, #REP_IVS]
    movs r1, #31
    ands r0, r1
    str r0, [sp, #REP_CANDIDATE]
    movs r0, r5
    movs r1, #MON_DATA_HP_IV
    adds r1, r4
    add r2, sp, #REP_CANDIDATE
    ldr r3, rep_set_mon_data
    bl rep_call
    adds r4, #1
    cmp r4, #6
    bne 3b
    movs r0, r5
    ldr r3, rep_calc_stats
    bl rep_call
.endif
    movs r0, #1
9:  add sp, #REP_FRAME
    pop {r4, r5, r6, r7, pc}

.ifndef REP_KEEP_ORDER
@ r0 = the substructure order for personality r0.
rep_order:
    push {lr}
    movs r1, #24
    bl umod
    adr r1, substruct_order
    ldrb r0, [r1, r0]
    pop {pc}
.endif

.ifndef PERSONALITY_SET_ONLY
rep_call:
    bx r3

    .align 2
rep_get_mon_data: .word GET_MON_DATA
rep_calc_stats:   .word CALCULATE_STATS
rep_set_mon_data: .word SET_MON_DATA
rep_lcg_mul:      .word LCG_MUL
rep_lcg_add:      .word LCG_ADD
rep_letter:       .word 0x03030300         @ the low 2 bits of the bytes the low one doesn't fix
.endif

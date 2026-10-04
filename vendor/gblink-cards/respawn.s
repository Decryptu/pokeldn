@ Legendary Respawn. `respawn` brings back the legendary Pokémon the player
@ beat without catching. Each flag in `legendaries` that is set is cleared
@ unless the Pokémon's national number is marked caught in the Pokédex (0
@ where only a win sets the flag and a catch sets another); the Pokémon's map
@ shows it again once its flag is clear. A roamer that stopped roaming (beaten,
@ or lost to Roar in the first releases) and was never caught roams again at
@ full HP. VAR_RESULT = how many came back.
@
@ Parameters (--defsym): SB1_PTR, SB2_PTR, ENEMY_PARTY, SPECIAL_VAR_RESULT,
@ FLAG_GET, FLAG_CLEAR, SPECIES_TO_NATIONAL, CREATE_MON_IVS_PERSONALITY,
@ ROAMER_MOVE (RoamerMoveToOtherLocationSet) and EMERALD.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ DEX_OWNED, 0x28                @ in SaveBlock2
    .equ ROAMER_IVS, 0
    .equ ROAMER_PERSONALITY, 4
    .equ ROAMER_SPECIES, 8
    .equ ROAMER_HP, 0x0A
    .equ ROAMER_LEVEL, 0x0C
    .equ ROAMER_STATUS, 0x0D
    .equ ROAMER_ACTIVE, 0x13
    .equ MON_MAX_HP, 0x58
.if EMERALD
    .equ ROAMER, 0x31DC                 @ in SaveBlock1
.else
    .equ ROAMER, 0x30D0
.endif

respawn:
    push {r4, r5, r6, r7, lr}
    sub sp, #4
    movs r7, #0                         @ how many came back
    adr r4, legendaries
1:  ldrh r0, [r4]
    cmp r0, #0
    beq 4f
    ldr r3, p_flag_get
    bl call_r3
    cmp r0, #0
    beq 3f
    ldrh r0, [r4, #2]
    bl caught
    cmp r0, #0
    bne 3f
    ldrh r0, [r4]
    ldr r3, p_flag_clear
    bl call_r3
    adds r7, #1
3:  adds r4, #4
    b 1b
4:  ldr r5, p_sb1_ptr
    ldr r5, [r5]
    ldr r0, p_roamer
    adds r5, r5, r0
    ldrh r0, [r5, #ROAMER_SPECIES]
    cmp r0, #0
    beq 9f                              @ nothing has roamed yet
    ldrb r1, [r5, #ROAMER_ACTIVE]
    cmp r1, #0
    bne 9f
    ldr r3, p_species_to_national
    bl call_r3
    bl caught
    cmp r0, #0
    bne 9f
    ldr r0, [r5, #ROAMER_PERSONALITY]
    str r0, [sp]
    ldr r0, p_enemy_party               @ to learn its max HP
    ldrh r1, [r5, #ROAMER_SPECIES]
    ldrb r2, [r5, #ROAMER_LEVEL]
    ldr r3, [r5, #ROAMER_IVS]
    ldr r6, p_create_mon
    bl call_r6
    ldr r0, p_enemy_party
    adds r0, #MON_MAX_HP
    ldrh r0, [r0]
    strh r0, [r5, #ROAMER_HP]
    movs r0, #0
    strb r0, [r5, #ROAMER_STATUS]
    movs r0, #1
    strb r0, [r5, #ROAMER_ACTIVE]
    ldr r3, p_roamer_move
    bl call_r3
    adds r7, #1
9:  ldr r0, p_var_result
    strh r7, [r0]
    add sp, #4
    pop {r4, r5, r6, r7, pc}

@ r0 = 1 if national number r0 is marked caught in the Pokédex, else 0.
caught:
    cmp r0, #0
    beq 1f
    subs r0, #1
    lsrs r1, r0, #3
    ldr r2, p_sb2_ptr
    ldr r2, [r2]
    adds r2, #DEX_OWNED
    ldrb r1, [r2, r1]
    movs r2, #7
    ands r0, r2
    lsrs r1, r0
    movs r0, #1
    ands r0, r1
1:  bx lr

call_r3:
    bx r3

call_r6:
    bx r6

    .align 2
p_flag_get:            .word FLAG_GET
p_flag_clear:          .word FLAG_CLEAR
p_sb1_ptr:             .word SB1_PTR
p_sb2_ptr:             .word SB2_PTR
p_roamer:              .word ROAMER
p_species_to_national: .word SPECIES_TO_NATIONAL
p_enemy_party:         .word ENEMY_PARTY
p_create_mon:          .word CREATE_MON_IVS_PERSONALITY
p_roamer_move:         .word ROAMER_MOVE
p_var_result:          .word SPECIAL_VAR_RESULT

@ The flag each legendary's map checks, and its national number.
legendaries:
.if EMERALD
    .hword 0x1BB, 377                   @ FLAG_DEFEATED_REGIROCK
    .hword 0x1BC, 378                   @ FLAG_DEFEATED_REGICE
    .hword 0x1BD, 379                   @ FLAG_DEFEATED_REGISTEEL
    .hword 0x1BE, 382                   @ FLAG_DEFEATED_KYOGRE
    .hword 0x1BF, 383                   @ FLAG_DEFEATED_GROUDON
    .hword 0x1C0, 384                   @ FLAG_DEFEATED_RAYQUAZA
    .hword 0x1C8, 0                     @ FLAG_DEFEATED_LATIAS_OR_LATIOS
    .hword 0x1C7, 0                     @ FLAG_DEFEATED_MEW
    .hword 0x1DD, 0                     @ FLAG_DEFEATED_LUGIA
    .hword 0x1DC, 0                     @ FLAG_DEFEATED_HO_OH
    .hword 0x1AC, 0                     @ FLAG_DEFEATED_DEOXYS
.else
    .hword 0x2BE, 144                   @ FLAG_FOUGHT_ARTICUNO
    .hword 0x2BF, 145                   @ FLAG_FOUGHT_ZAPDOS
    .hword 0x2BD, 146                   @ FLAG_FOUGHT_MOLTRES
    .hword 0x2BC, 150                   @ FLAG_FOUGHT_MEWTWO
    .hword 0x2F5, 0                     @ FLAG_LUGIA_FLEW_AWAY
    .hword 0x2F6, 0                     @ FLAG_HO_OH_FLEW_AWAY
    .hword 0x2F7, 0                     @ FLAG_DEOXYS_FLEW_AWAY
.endif
    .hword 0
    .align 2

@ Shiny Hunting: a V-blank hook that keeps a chain of one species of wild
@ Pokémon and makes that species shiny more often the longer the chain is.
@
@ Catching a wild Pokémon adds 2 to the chain and making it faint adds 1; one
@ of another species starts a new chain at that. Running away leaves the chain
@ as it is, and a wild Pokémon that flees ends it. In a plain wild battle
@ (no battle type but IS_MASTER, and no script running when the Pokémon turned up: the
@ scripts of legendaries and the like take one that fled for one caught) the
@ wild Pokémon flees on 1 turn in 20 unless it is asleep: once every choice
@ of the turn is made, the hook turns its action into a run before
@ SetActionsAndBattlersTurnOrder orders them, and the game's own
@ HandleAction_Run lets it go, or keeps it when it can't escape.
@
@ A wild Pokémon is a new gEnemyParty[0] that turns up while CB2_Overworld
@ runs, or CB2_OverworldBasic, which the game switches to when a battle's
@ transition starts (often before the hook's first chance), and carries the
@ player's trainer id, as every Pokémon the player can catch does; a
@ trainer's does not; the last battle's, still there when the hook starts,
@ counts as met. gBattleOutcome still holds the last battle's then, so the
@ hook clears it and reads its battle's once the game sets it. The
@ Pokémon turns shiny when its shiny value (the personality's halves XOR the
@ trainer id's) is below 32 × (chain + 2), where the game's own rule is below
@ 8, its chain counting only for the chain's species and up to ODDS_CHAIN:
@ 1 in 1024 without a chain, 1 in 64 from 30 on. It then gets a PID and IVs
@ from a shiny frame of the random number generator, which belong together
@ as in a wild Pokémon the game made shiny itself: what PKHeX checks.
@
@ R pressed in the field, with the controls free and no script running,
@ runs `r_script` with the chain in VAR_0x8005 and its species in
@ VAR_0x8006 (its lockall waits for the player to stop); not in a link room
@ (their field has another callback1), nor while FireRed/LeafGreen play back
@ "Previously on your quest", where R no longer opens the Help menu either
@ (L still does).
@
@ `install` copies `resident`..`resident_end` to RESIDENT like the other hooks
@ (only one card's hook can run between resets) and points the V-blank
@ interrupt at the copy. It stays on until the game is reset. The hook only acts while the game waits for V-blank, so it
@ never meets a Pokémon or a battle the game is halfway through changing.
@
@ Parameters (--defsym): INTR_VBLANK, MAIN, CB1_OVERWORLD, CB2_OVERWORLD,
@ ENEMY_PARTY, SB2_PTR, BATTLE_OUTCOME, BATTLE_MAIN_FUNC, SET_TURN_ORDER,
@ BATTLE_TYPE, CHOSEN_ACTIONS, RANDOM, GET_MON_DATA, SET_MON_DATA,
@ CALCULATE_STATS, SPECIAL_VAR_8004,
@ CONTROLS_LOCKED, SCRIPT_STATUS, SETUP_SCRIPT, HIDE_MAP_NAME,
@ HELP_R_DISABLE and QUEST_LOG_STATE (0 if none), EMERALD and STATE.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ PENDING, 1                     @ u8 while a wild battle's outcome is awaited:
    .equ WAITING, 1                     @   a scripted battle's (a script made the Pokémon),
    .equ MAY_FLEE, 2                    @   else one the Pokémon may flee from
    .equ CHAIN, 4                       @ u16
    .equ SPECIES, 6                     @ u16, the chain's species
    .equ MET, 8                         @ u16, the wild Pokémon's species
    .equ LAST_PID, 12                   @ the last wild Pokémon's personality
    .equ KEPT, 16                       @ the V-blank handler the hook calls
    .equ ODDS_CHAIN, 30                 @ the chain the odds stop improving at
    .equ MAIN_CALLBACK1, 0
    .equ MAIN_CALLBACK2, 4
    .equ MAIN_INTR_CHECK, 0x1C
    .equ MAIN_NEW_KEYS, 0x2E
    .equ BUTTON_R_BIT, 8
    .equ OVERWORLD_BASIC, 12            @ CB2_OverworldBasic is 12 bytes before CB2_Overworld
    .equ PLAYER_ID, 10                  @ in SaveBlock2
    .equ MON_PERSONALITY, 0x00
    .equ MON_OT_ID, 0x04
    .equ MON_STATUS, 0x50               @ the battle keeps it up to date
    .equ STATUS1_SLEEP_BITS, 29         @ the low 3 bits: turns left asleep
    .equ MON_DATA_SPECIES, 11
    .equ SPECIES_UNOWN, 201
    .equ SPECIES_RAIKOU, 243            @ then ENTEI, SUICUNE: FireRed and LeafGreen's roamers
    .equ SPECIES_LATIAS, 407            @ then LATIOS: Emerald's
    .equ MON_DATA_HP_IV, 39             @ then ATTACK, DEFENSE, SPEED, SP. ATK, SP. DEF
    .equ BATTLE_TYPE_IS_MASTER, 4       @ a plain wild battle's only battle type bit
    .equ B_ACTION_RUN, 3
    .equ B_OUTCOME_WON, 1
    .equ B_OUTCOME_MON_FLED, 6
    .equ B_OUTCOME_CAUGHT, 7
    .equ FLEE_CHANCE, 0xCC0             @ of a Random() of 65536: 1 in 20
    .equ CONTEXT_SHUTDOWN, 2
    .equ QL_STATE_PLAYBACK, 2           @ and 3, its last scene
    .equ VAR_0x8005, 0x8005
    .equ VAR_0x8006, 0x8006
    .equ NPC_TEXT_COLOR_NEUTRAL, 3

@ The copy runs with interrupts on: a hook already at RESIDENT is this one,
@ whose bytes it writes again.
install:
    push {r4, r5, lr}
    ldr r0, p_intr_vblank               @ pokeldn: the game's own handler while the copy
    ldr r1, p_vblank_intr               @ overwrites whatever hook runs at RESIDENT
    str r1, [r0]
    ldr r5, p_resident
    adr r4, resident
    ldr r0, p_resident_size
1:  subs r0, #4
    ldr r1, [r4, r0]
    str r1, [r5, r0]
    bne 1b
    ldr r4, p_state
    str r0, [r4, #ENABLED]              @ and PENDING
    str r0, [r4, #CHAIN]                @ and SPECIES
    movs r0, #1
    strb r0, [r4, #ENABLED]
    ldr r0, p_intr_vblank
    ldr r1, p_vblank_intr               @ pokeldn: chain to the game's handler, never a hook,
    str r1, [r4, #KEPT]
    subs r3, r5, #4                     @ and keep it at RESIDENT - 4, where pokeldn's
    str r1, [r3]                        @ resident installs look for it [docs/frlg_rom.md]
    adds r1, r5, #1
    str r1, [r0]
3:  pop {r4, r5, pc}

    .align 2
p_resident:      .word RESIDENT
p_resident_size: .word resident_end - resident
p_state:         .word STATE
p_intr_vblank:   .word INTR_VBLANK
p_vblank_intr:   .word VBLANK_INTR

@ ---- copied to RESIDENT
    .align 2
resident:
    push {r4, r5, r6, r7, lr}
    ldr r4, r_state
    ldrb r0, [r4, #ENABLED]
    cmp r0, #0
    beq 9f
    ldr r7, r_main
    ldrh r0, [r7, #MAIN_INTR_CHECK]
    lsls r0, r0, #31
    bne 9f                              @ the game is mid-frame
.if EMERALD == 0
    ldr r0, r_help_r_disable
    movs r1, #1
    strb r1, [r0]
.endif
    bl battle
    bl field_r
    bl encounter
9:  ldr r3, [r4, #KEPT]
    bl call_r3
    pop {r4, r5, r6, r7}
    pop {r0}
    bx r0

call_r3:
    bx r3

@ The wild battle's outcome once it is set, else this turn's flee chance;
@ r4 = STATE. gBattleMainFunc is SetActionsAndBattlersTurnOrder for one
@ V-blank a turn: the one between the frame the last choice was made in and
@ the frame that orders the turn.
battle:
    push {lr}
    ldrb r0, [r4, #PENDING]
    cmp r0, #0
    beq 9f
    ldr r1, r_outcome
    ldrb r2, [r1]
    cmp r2, #0
    bne outcome
    cmp r0, #MAY_FLEE
    bne 9f
    ldr r1, r_main_func
    ldr r1, [r1]
    ldr r2, r_set_turn_order
    cmp r1, r2
    bne 9f
    ldr r1, r_battle_type
    ldr r1, [r1]
    cmp r1, #BATTLE_TYPE_IS_MASTER
    bne 9f                              @ not a plain wild battle
    ldr r1, r_enemy
    adds r1, #MON_STATUS
    ldrb r1, [r1]
    lsls r1, r1, #STATUS1_SLEEP_BITS
    bne 9f                              @ asleep
    ldr r3, r_random
    bl call_r3
    movs r1, #FLEE_CHANCE >> 4
    lsls r1, r1, #4
    cmp r0, r1
    bcs 9f
    ldr r1, r_chosen_actions
    movs r0, #B_ACTION_RUN
    strb r0, [r1, #1]                   @ the wild Pokémon's
    b 9f
outcome:
    movs r1, #0
    strb r1, [r4, #PENDING]
    cmp r2, #B_OUTCOME_MON_FLED
    beq 5f                              @ the chain ends
    movs r0, #1
    cmp r2, #B_OUTCOME_WON
    beq 2f
    movs r0, #2
    cmp r2, #B_OUTCOME_CAUGHT
    bne 9f
2:  ldrh r2, [r4, #MET]
    ldrh r3, [r4, #SPECIES]
    cmp r2, r3
    beq 3f
    strh r2, [r4, #SPECIES]             @ a new chain
    b 4f
3:  ldrh r1, [r4, #CHAIN]
4:  adds r1, r1, r0
5:  strh r1, [r4, #CHAIN]
9:  pop {pc}

@ R pressed in the field runs r_script; r7 = gMain.
field_r:
    push {lr}
    ldrh r0, [r7, #MAIN_NEW_KEYS]
    lsrs r0, r0, #BUTTON_R_BIT + 1
    bcc 9f                              @ R not just pressed
    ldr r0, [r7, #MAIN_CALLBACK1]
    ldr r1, r_cb1_overworld
    cmp r0, r1
    bne 9f
    ldr r0, r_controls_locked
    ldrb r0, [r0]
    cmp r0, #0
    bne 9f
    ldr r0, r_script_status
    ldrb r0, [r0]
    cmp r0, #CONTEXT_SHUTDOWN
    bne 9f
.if EMERALD == 0
    ldr r0, r_quest_log_state
    ldrb r0, [r0]
    cmp r0, #QL_STATE_PLAYBACK
    bcs 9f
.endif
    ldr r0, r_var_8004
    ldrh r1, [r4, #CHAIN]
    strh r1, [r0, #2]
    ldrh r1, [r4, #SPECIES]
    strh r1, [r0, #4]
    ldr r0, r_r_script
    ldr r3, r_setup_script
    bl call_r3
9:  pop {pc}

@ A new gEnemyParty[0]; r4 = STATE, r7 = gMain.
encounter:
    push {lr}
    ldr r5, r_enemy
    ldr r6, [r5, #MON_PERSONALITY]
    ldr r0, [r4, #LAST_PID]
    cmp r0, r6
    beq 9f
    str r6, [r4, #LAST_PID]
    ldr r0, [r7, #MAIN_CALLBACK2]
    ldr r1, r_cb2_overworld
    cmp r0, r1
    beq 1f
    adds r0, #OVERWORLD_BASIC
    cmp r0, r1
    bne 8f
1:  ldr r0, r_sb2_ptr
    ldr r0, [r0]
    ldrh r1, [r0, #PLAYER_ID + 2]
    lsls r1, r1, #16
    ldrh r0, [r0, #PLAYER_ID]
    orrs r0, r1
    ldr r1, [r5, #MON_OT_ID]
    cmp r0, r1
    bne 8f                              @ a trainer's Pokémon, or none
    movs r0, r5
    movs r1, #MON_DATA_SPECIES
    ldr r3, r_get_mon_data
    bl call_r3
    strh r0, [r4, #MET]
    ldr r1, r_outcome
    movs r2, #0
    strb r2, [r1]
    ldr r1, r_script_status
    ldrb r1, [r1]
    movs r2, #WAITING
    cmp r1, #CONTEXT_SHUTDOWN
    bne 3f
    movs r2, #MAY_FLEE
3:  strb r2, [r4, #PENDING]
@ Never a roaming legendary, nor Unown: PKHeX expects the roamers' IVs of the
@ game's bug and an Unown letter of the chamber it lives in.
.if EMERALD
    movs r1, r0
    subs r1, #255
    subs r1, #SPECIES_LATIAS - 255
    cmp r1, #1
.else
    cmp r0, #SPECIES_UNOWN
    beq 9f
    movs r1, r0
    subs r1, #SPECIES_RAIKOU
    cmp r1, #2
.endif
    bls 9f
    ldrh r1, [r4, #SPECIES]
    movs r2, #0
    cmp r0, r1
    bne 2f
    ldrh r2, [r4, #CHAIN]
    cmp r2, #ODDS_CHAIN
    bls 2f
    movs r2, #ODDS_CHAIN
2:  adds r2, #2
    lsls r2, r2, #5                     @ 32 × (chain + 2)
    ldr r0, [r5, #MON_OT_ID]
    eors r0, r6
    lsrs r1, r0, #16
    eors r0, r1
    lsls r0, r0, #16
    lsrs r0, r0, #16                    @ the shiny value
    cmp r0, r2
    bcs 9f
    bl make_shiny
    str r6, [r4, #LAST_PID]
    b 9f
8:  movs r0, #0
    strb r0, [r4, #PENDING]             @ no wild battle to wait for
9:  pop {pc}

    .equ LCG_MUL, 0x41C64E6D            @ the games' random number generator
    .equ LCG_ADD, 0x6073
    .equ MON_SECURE, 0x20               @ 48 bytes XORed with personality ^ trainer id
    .equ OLD_PID, 0                     @ make_shiny's frame
    .equ HIGH_MOD3, 4
    .equ IVS, 8
    .equ IV, 0                          @ each IV in turn, once OLD_PID is done with

@ Gives the Pokémon at r5 (personality r6) a shiny PID and IVs from one frame
@ of the random number generator, as the game makes a wild Pokémon (Method 1:
@ the PID's low half, its high half, then two words of IVs). The low half
@ stays (gender, ability; 1 time in 32 it moves on by 24) and the high half
@ keeps its remainder by 3, so the PID keeps its remainder by 24, the order
@ of the secure data, which only needs XORing with the change of key. Re-creating the Pokémon instead
@ (CreateMon) holds the game up for some 9 frames. r6 = the new personality.
make_shiny:
    push {r4, r7, lr}
    sub sp, #16
    str r6, [sp, #OLD_PID]
    lsrs r6, r6, #16
    bl mod3
    str r6, [sp, #HIGH_MOD3]
    ldrh r3, [r5, #MON_OT_ID]
    ldrh r1, [r5, #MON_OT_ID + 2]
    eors r3, r1
    movs r7, r3                         @ the trainer id's halves XORed
    ldr r0, [sp, #OLD_PID]
    lsls r0, r0, #16                    @ its high half: the PID's low half
    ldr r1, r_lcg_mul
    ldr r2, r_lcg_add
    movs r4, r0
    muls r4, r1
    adds r4, r2                         @ the next random number
1:  lsrs r3, r0, #16
    eors r3, r7                         @ the high halves shiny with this low half
@ Each next try adds 1 to the first number, so a multiplier to the second.
2:  adds r0, #1
    adds r4, r1
    lsrs r6, r4, #16
    eors r6, r3
    cmp r6, #8
    bcs 2b
    lsrs r6, r0, #16
    eors r6, r7
    cmp r6, r3
    bne 5f                              @ the low half moved on meanwhile
    lsrs r6, r4, #16
    bl mod3
    ldr r2, [sp, #HIGH_MOD3]
    cmp r6, r2
    bne 2b
    lsrs r6, r0, #16
    lsrs r7, r4, #16
    lsls r7, r7, #16
    orrs r6, r7                         @ the shiny PID
    ldr r2, r_lcg_add
    movs r0, r4
    muls r0, r1
    adds r0, r2
    movs r4, r0
    muls r4, r1
    adds r4, r2
    lsls r0, r0, #1
    lsrs r0, r0, #17                    @ HP, ATTACK, DEFENSE
    lsls r4, r4, #1
    lsrs r4, r4, #17
    lsls r4, r4, #15                    @ SPEED, SP. ATK, SP. DEF
    orrs r0, r4
    str r0, [sp, #IVS]
    ldr r1, [sp, #OLD_PID]
    eors r1, r6                         @ the change of key
    movs r0, r5
    adds r0, #MON_SECURE
    movs r2, #44
3:  ldr r3, [r0, r2]
    eors r3, r1
    str r3, [r0, r2]
    subs r2, #4
    bpl 3b
    str r6, [r5, #MON_PERSONALITY]
    movs r7, #0
4:  ldr r0, [sp, #IVS]
    lsrs r1, r0, #5
    str r1, [sp, #IVS]                  @ the next IV, 5 bits on
    movs r1, #31
    ands r0, r1
    str r0, [sp, #IV]
    movs r1, #MON_DATA_HP_IV
    adds r1, r7
    add r2, sp, #IV
    movs r0, r5
    ldr r4, r_set_mon_data
    bl call_r4
    adds r7, #1
    cmp r7, #6
    bne 4b
    movs r0, r5
    ldr r4, r_calc_stats
    bl call_r4
    add sp, #16
    pop {r4, r7, pc}

@ None of this low half's 65536 tries fitted: on to the low half 24 past it,
@ which keeps the remainder by 24 and bit 0 (the ability).
5:  movs r6, #23
    lsls r6, r6, #16
    adds r0, r6
    muls r6, r1
    adds r4, r6
    b 1b

@ r6 = r6 % 3, for r6 below 65536; uses r2.
mod3:
    ldr r2, r_third
    muls r2, r6
    lsrs r2, r2, #17                    @ r6 / 3
    subs r6, r2
    subs r6, r2
    subs r6, r2
    bx lr

call_r4:
    bx r4

    .align 2
r_state:            .word STATE
r_main:             .word MAIN
r_enemy:            .word ENEMY_PARTY
r_sb2_ptr:          .word SB2_PTR
r_outcome:          .word BATTLE_OUTCOME
r_main_func:        .word BATTLE_MAIN_FUNC
r_set_turn_order:   .word SET_TURN_ORDER
r_battle_type:      .word BATTLE_TYPE
r_chosen_actions:   .word CHOSEN_ACTIONS
r_random:           .word RANDOM
r_get_mon_data:     .word GET_MON_DATA
r_set_mon_data:     .word SET_MON_DATA
r_third:            .word 0xAAAB              @ 2^17 / 3, rounded up
r_calc_stats:       .word CALCULATE_STATS
r_lcg_mul:          .word LCG_MUL
r_lcg_add:          .word LCG_ADD
.if EMERALD == 0
r_help_r_disable:   .word HELP_R_DISABLE
r_quest_log_state:  .word QUEST_LOG_STATE
.endif
r_cb1_overworld:    .word CB1_OVERWORLD
r_cb2_overworld:    .word CB2_OVERWORLD
r_controls_locked:  .word CONTROLS_LOCKED
r_script_status:    .word SCRIPT_STATUS
r_setup_script:     .word SETUP_SCRIPT
r_var_8004:         .word SPECIAL_VAR_8004
r_r_script:         .word RESIDENT + (r_script - resident)

@ a label's address in RESIDENT
    .macro at label
    .4byte RESIDENT + (\label - resident)
    .endm

r_script:
    .byte 0x23                          @ callnative: the map name banner away
    .4byte HIDE_MAP_NAME
    .byte 0x69                          @ lockall
.if EMERALD == 0
    .byte 0xC7, NPC_TEXT_COLOR_NEUTRAL  @ textcolor
.endif
    .byte 0x7D, 0                       @ bufferspeciesname STR_VAR_1, VAR_0x8006
    .2byte VAR_0x8006
    .byte 0x83, 1                       @ buffernumberstring STR_VAR_2, VAR_0x8005
    .2byte VAR_0x8005
    .byte 0x67                          @ message
    at chain_text
    .byte 0x66                          @ waitmessage
    .byte 0x6D                          @ waitbuttonpress
    .byte 0x68                          @ closemessage
    .byte 0x6B                          @ releaseall
    .byte 0x02                          @ end
    .include "data.inc"
resident_end:

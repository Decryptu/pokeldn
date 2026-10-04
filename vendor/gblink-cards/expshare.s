@ Exp. Share for the whole party. `install` starts a V-blank hook that shares
@ a battle's EXP. the way later games do: each party Pokémon that battled the
@ fainted Pokémon gets all of its EXP., not a share of it, and every other
@ one that isn't an Egg and hasn't fainted gets half. The battle engine runs
@ one script command a frame, and between frames the hook looks at the next
@ one; for getexp it changes what the command works with:
@ - before the step that works out the EXP., the hook does that step itself:
@   EXP keeps what the fainted Pokémon gives (yield × level / 7, as the game
@   has it), a held EXP. SHARE's own share becomes 0 (the whole party gets
@   EXP. anyway), and the Pokémon to give it to start from the first.
@ - before the step for each party Pokémon, its value: EXP for one that
@   battled, half of it for another, which is then marked as having battled
@   so that the step gives it.
@ The step then adds its own boosts (a trainer's Pokémon, a traded Pokémon,
@ a LUCKY EGG) and the EVs, levels up and learns moves as it does for the
@ EXP. SHARE. In Emerald's battles beside a partner, the partner's Pokémon
@ (party slots 4 to 6) get nothing they didn't battle for. The hook is copied
@ to RESIDENT like the others, so it lasts until the game is reset;
@ clearing ENABLED turns it off.
@
@ Parameters (--defsym): INTR_VBLANK, MAIN, BATTLE_CB1, EXEC_FLAGS
@ (gBattleControllerExecFlags), SCRIPT_INSTR (gBattlescriptCurrInstr),
@ BATTLE_STRUCT, BATTLE_SCRIPTING, BATTLE_MONS, BATTLER_FAINTED, SENT_POKES
@ (gSentPokesToOpponent), EXP_SHARE_EXP, SPECIES_INFO, PARTY, BATTLE_TYPE,
@ EMERALD and STATE.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ EXP, 2                         @ u16
    .equ KEPT, 4                        @ the V-blank handler the hook calls
    .equ MAIN_INTR_CHECK, 0x1C
    .equ GETEXP, 0x23
    .equ GETEXP_STATE, 0x1C             @ in gBattleScripting
    .equ WORK_OUT, 1                    @ getexp's steps
    .equ GIVE, 2
    .equ EXP_GETTER_MON, 0x10           @ in gBattleStruct
    .equ EXP_VALUE, 0x50
    .equ SENT_IN_POKES, 0x53
    .equ BATTLE_MON_SIZE, 0x58          @ struct BattlePokemon
    .equ BATTLE_MON_LEVEL, 0x2A
    .equ SPECIES_INFO_SIZE, 28
    .equ EXP_YIELD, 9
    .equ MON_SIZE, 100
    .equ MON_FLAGS, 0x13                @ isBadEgg, hasSpecies, isEgg
    .equ A_POKEMON, 2
    .equ MON_HP, 0x56
    .equ PARTNER_SLOTS, 3               @ from party slot 4
    .equ BATTLE_TYPE_INGAME_PARTNER_BIT, 22

@ Only this card's hook can run until a reset, so a hook already running is
@ rewritten with the same bytes.
install:
    push {r4, r5, lr}
    ldr r0, p_intr_vblank               @ pokeldn: the game's own handler while the copy
    ldr r1, p_vblank_intr               @ overwrites whatever hook runs at RESIDENT
    str r1, [r0]
    ldr r5, p_resident
    adr r4, resident
    movs r0, #(resident_end - resident) / 4
    lsls r0, r0, #2
1:  subs r0, #4
    ldr r1, [r4, r0]
    str r1, [r5, r0]
    bne 1b
    ldr r4, p_state
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
p_state:         .word STATE
p_intr_vblank:   .word INTR_VBLANK
p_vblank_intr:   .word VBLANK_INTR

@ ---- copied to RESIDENT
    .align 2
resident:
    push {r4, r5, r6, r7, lr}
    ldr r4, r_state
    ldr r0, r_main
    ldrh r1, [r0, #MAIN_INTR_CHECK]
    lsls r1, r1, #31
    bne 9f                              @ the game is mid-frame
    ldrb r1, [r4, #ENABLED]
    cmp r1, #0
    beq 9f
    ldr r0, [r0]                        @ gMain.callback1
    ldr r1, r_battle_cb1
    cmp r0, r1
    bne 9f
    ldr r0, r_exec_flags
    ldr r0, [r0]
    cmp r0, #0
    bne 9f                              @ the next command waits
    ldr r0, r_script_instr
    ldr r0, [r0]
    lsrs r1, r0, #25
    cmp r1, #4
    bne 9f                              @ no script in ROM
    ldrb r0, [r0]
    cmp r0, #GETEXP
    bne 9f
    ldr r5, r_battle_struct
    ldr r5, [r5]
    ldr r7, r_scripting
    ldrb r0, [r7, #GETEXP_STATE]
    cmp r0, #GIVE
    beq give
    cmp r0, #WORK_OUT
    bne 9f
    ldr r0, r_fainted                   @ the EXP. the fainted Pokémon gives
    ldrb r0, [r0]
    movs r1, #BATTLE_MON_SIZE
    muls r0, r1
    ldr r1, r_battle_mons
    adds r0, r0, r1
    ldrh r1, [r0]                       @ its species
    movs r2, #BATTLE_MON_LEVEL
    ldrb r6, [r0, r2]
    movs r0, #SPECIES_INFO_SIZE
    muls r0, r1
    ldr r1, r_species_info
    adds r0, r0, r1
    ldrb r0, [r0, #EXP_YIELD]
    muls r0, r6
    movs r1, #7
    svc #6                              @ Div: r0 = / 7
    strh r0, [r4, #EXP]
    movs r0, #0
    ldr r1, r_exp_share_exp
    strh r0, [r1]
    strb r0, [r5, #EXP_GETTER_MON]
    bl sent_in
    movs r1, #SENT_IN_POKES
    strb r0, [r5, r1]
    movs r0, #GIVE
    strb r0, [r7, #GETEXP_STATE]
give:
    ldrb r6, [r5, #EXP_GETTER_MON]
    ldrh r1, [r4, #EXP]
    bl sent_in
    lsrs r0, r6
    lsls r0, r0, #31
    bmi 3f                              @ it battled: all of it
.if EMERALD
    cmp r6, #PARTNER_SLOTS
    bcc 1f
    ldr r0, r_battle_type
    ldr r0, [r0]
    lsls r0, r0, #31 - BATTLE_TYPE_INGAME_PARTNER_BIT
    bmi 9f
1:
.endif
    movs r0, #MON_SIZE
    muls r0, r6
    ldr r2, r_party
    adds r0, r0, r2
    ldrb r2, [r0, #MON_FLAGS]
    lsls r2, r2, #29
    lsrs r2, r2, #29
    cmp r2, #A_POKEMON
    bne 9f                              @ an Egg, or no Pokémon
    movs r2, #MON_HP
    ldrh r2, [r0, r2]
    cmp r2, #0
    beq 9f
    movs r3, #SENT_IN_POKES
    ldrb r2, [r5, r3]
    movs r0, #1
    orrs r2, r0
    strb r2, [r5, r3]                   @ counts as having battled
    lsrs r1, r1, #1                     @ half
3:  cmp r1, #0
    bne 4f
    movs r1, #1                         @ never less than 1, as the game has it
4:  movs r2, #EXP_VALUE
    strh r1, [r5, r2]
9:  ldr r3, [r4, #KEPT]
    pop {r4, r5, r6, r7}
    pop {r0}
    mov lr, r0
    bx r3                               @ which returns for the hook

@ r0 = the party Pokémon that battled the fainted one, a bit each.
sent_in:
    ldr r0, r_fainted
    ldrb r0, [r0]
    lsls r0, r0, #30
    lsrs r0, r0, #31                    @ its side's left or right
    ldr r2, r_sent_pokes
    ldrb r0, [r2, r0]
    bx lr

    .align 2
r_state:         .word STATE
r_main:          .word MAIN
r_battle_cb1:    .word BATTLE_CB1
r_exec_flags:    .word EXEC_FLAGS
r_script_instr:  .word SCRIPT_INSTR
r_battle_struct: .word BATTLE_STRUCT
r_scripting:     .word BATTLE_SCRIPTING
r_fainted:       .word BATTLER_FAINTED
r_battle_mons:   .word BATTLE_MONS
r_species_info:  .word SPECIES_INFO
r_exp_share_exp: .word EXP_SHARE_EXP
r_sent_pokes:    .word SENT_POKES
r_party:         .word PARTY
.if EMERALD
r_battle_type:   .word BATTLE_TYPE
.endif
    .align 2
resident_end:

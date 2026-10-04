@ Physical/Special Split. `install` starts a V-blank hook that makes each
@ damaging move physical or special by the move itself, as from Diamond and
@ Pearl on, instead of by its type (`kinds`). The battle engine runs one
@ script command a frame, and between frames the hook looks at the next one;
@ when the move's kind is not its type's, it changes what that command reads
@ for the one frame, and the next frame puts it back:
@ - damagecalc, trysetfutureattack for DOOM DESIRE and stockpiletobasedamage
@   for SPIT UP: CalculateBaseDamage takes the type's branch, so the stats
@   that branch reads hold the other ones, with their stat stages, and
@   REFLECT and LIGHT SCREEN change places.
@   ATTACK's own boosts follow the move: a physical move taking the special
@   branch gets CHOICE BAND, HUGE POWER, PURE POWER, HUSTLE, GUTS and a burn's
@   halving in advance; a special move taking the physical branch loses them
@   (every ability but SWARM, which boosts by type, is hidden).
@ - datahpupdate: the damage taken is recorded by the type's kind, which
@   COUNTER and MIRROR COAT read (gProtectStructs); the Pokémon's two records
@   change places around it, so the new damage lands in the move's kind's.
@   gSpecialStatuses keeps its records: a FIRE move thaws by them.
@ In a link battle only one GBA runs the battle engine, and its hook decides
@ for both. The hook is copied to RESIDENT like the others, so it lasts until
@ the game is reset; clearing ENABLED turns it off.
@
@ Parameters (--defsym): INTR_VBLANK, MAIN, BATTLE_CB1, EXEC_FLAGS
@ (gBattleControllerExecFlags), SCRIPT_INSTR (gBattlescriptCurrInstr),
@ CURRENT_MOVE, BATTLE_MOVES, BATTLE_STRUCT, BATTLE_MONS, BATTLER_ATTACKER,
@ BATTLER_TARGET, BATTLER_POSITIONS, SIDE_STATUSES, PROTECT_STRUCTS and STATE.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ PENDING, 1                     @ u8: what the last frame changed
    .equ VICTIM, 2                      @ u8: RECORDS: whose records
    .equ KEPT_TARGET, 4                 @ STATS: its struct BattlePokemon up to its item
    .equ TARGET_SIZE, 0x30
    .equ KEPT, KEPT_TARGET + TARGET_SIZE        @ the V-blank handler the hook calls
    .equ KEPT_ATTACKER, KEPT + 4        @ STATS: the attacker's up to its status
    .equ ATTACKER_SIZE, 0x50
    .equ STATS, 1
    .equ RECORDS, 2
    .equ MAIN_INTR_CHECK, 0x1C
    .equ DAMAGECALC, 0x05
    .equ DATAHPUPDATE, 0x0C
    .equ STOCKPILETOBASEDAMAGE, 0x86
    .equ TRYSETFUTUREATTACK, 0xC3
    .equ BS_ATTACKER, 1                 @ datahpupdate's battler: 0 is the target
    .equ MOVE_SIZE, 12
    .equ MOVE_TYPE, 2
    .equ DYNAMIC_TYPE, 0x13             @ in gBattleStruct
    .equ IGNORE_PHYSICALITY_BIT, 6      @ datahpupdate then takes the move's type
    .equ TYPE_MYSTERY, 9                @ types below it are physical, above special
    .equ MON_SIZE, 0x58                 @ struct BattlePokemon
    .equ MON_ATTACK, 0x02
    .equ MON_DEFENSE, 0x04
    .equ MON_SP_ATTACK, 0x08
    .equ MON_SP_DEFENSE, 0x0A
    .equ STAGE_ATTACK, 0x19             @ statStages[STAT_ATK]
    .equ STAGE_DEFENSE, 0x1A
    .equ STAGE_SP_ATTACK, 0x1C
    .equ STAGE_SP_DEFENSE, 0x1D
    .equ MON_ABILITY, 0x20
    .equ MON_ITEM, 0x2E
    .equ MON_STATUS, 0x4C
    .equ STATUS_BURN_BIT, 4
    .equ PROTECT_SIZE, 16
    .equ PHYSICAL_DAMAGE, 4             @ then specialDmg, physicalBattlerId, specialBattlerId
    .equ ITEM_CHOICE_BAND, 186
    .equ ABILITY_HUGE_POWER, 37
    .equ ABILITY_HUSTLE, 55
    .equ ABILITY_SWARM, 68
    .equ ABILITY_GUTS, 62
    .equ ABILITY_PURE_POWER, 74

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
    ldr r6, r_main
    ldrh r0, [r6, #MAIN_INTR_CHECK]
    lsls r0, r0, #31
    bne 9f                              @ the game is mid-frame
    ldrb r1, [r4, #PENDING]
    cmp r1, #0
    beq 1f
    bl undo
1:  ldrb r0, [r4, #ENABLED]
    cmp r0, #0
    beq 9f
    ldr r0, [r6]                        @ gMain.callback1
    ldr r1, r_battle_cb1
    cmp r0, r1
    bne 9f
    ldr r0, r_exec_flags
    ldr r0, [r0]
    cmp r0, #0
    bne 9f                              @ the next command waits
    ldr r0, r_script_instr
    ldr r7, [r0]
    lsrs r0, r7, #25
    cmp r0, #4
    bne 9f                              @ no script in ROM: the other GBA of a link battle
    ldr r0, r_current_move
    ldrh r0, [r0]
    adr r1, kinds
    lsrs r2, r0, #3
    ldrb r1, [r1, r2]
    movs r2, #7
    ands r2, r0
    lsrs r1, r2
    movs r5, #1
    ands r5, r1                         @ 1 for a physical move
    movs r1, #MOVE_SIZE
    muls r1, r0
    ldr r0, r_battle_moves
    adds r0, r0, r1
    ldrb r6, [r0, #MOVE_TYPE]
    ldr r0, r_battle_struct
    ldr r0, [r0]
    ldrb r1, [r0, #DYNAMIC_TYPE]
    ldrb r2, [r7]                       @ the command
    cmp r1, #0
    beq 3f
    cmp r2, #DATAHPUPDATE
    bne 2f
    lsls r3, r1, #31 - IGNORE_PHYSICALITY_BIT
    bmi 3f
2:  movs r6, #0x3F
    ands r6, r1                         @ HIDDEN POWER's or WEATHER BALL's type
3:  subs r6, #TYPE_MYSTERY
    lsrs r6, r6, #31                    @ 1 for a physical type
    cmp r6, r5
    beq 9f                              @ the type's kind is the move's
    cmp r2, #DAMAGECALC
    beq stats
    cmp r2, #TRYSETFUTUREATTACK
    beq stats
    cmp r2, #STOCKPILETOBASEDAMAGE
    beq stats
    cmp r2, #DATAHPUPDATE
    bne 9f
    ldrb r1, [r7, #1]                   @ the records
    ldr r0, r_target
    cmp r1, #BS_ATTACKER
    bhi 9f
    bne 6f
    ldr r0, r_attacker
6:  ldrb r0, [r0]
    strb r0, [r4, #VICTIM]
    bl swap_records
    movs r1, #RECORDS
8:  strb r1, [r4, #PENDING]
9:  ldr r3, [r4, #KEPT]
    pop {r4, r5, r6, r7}
    pop {r0}
    mov lr, r0
    bx r3                               @ which returns for the hook

stats:
    ldr r0, r_attacker
    bl mon_of
    movs r6, r0                         @ the attacker
    movs r1, r4
    adds r1, #KEPT_ATTACKER
    bl copy_attacker
    ldr r0, r_target
    bl mon_of
    movs r7, r0                         @ the target
    adds r1, r4, #KEPT_TARGET
    bl copy_target
    bl swap_screens
    cmp r5, #0
    beq 7f
    ldrh r0, [r6, #MON_ATTACK]          @ physical, in the special branch
    ldrh r1, [r6, #MON_ITEM]
    cmp r1, #ITEM_CHOICE_BAND
    bne 1f
    lsrs r1, r0, #1
    adds r0, r0, r1
1:  movs r1, #MON_ABILITY
    ldrb r1, [r6, r1]
    cmp r1, #ABILITY_HUGE_POWER
    beq 2f
    cmp r1, #ABILITY_PURE_POWER
    bne 3f
2:  lsls r0, r0, #1
3:  cmp r1, #ABILITY_HUSTLE
    bne 4f
    lsrs r2, r0, #1
    adds r0, r0, r2
4:  ldr r2, [r6, #MON_STATUS]
    cmp r1, #ABILITY_GUTS
    bne 5f
    cmp r2, #0
    beq 6f
    lsrs r2, r0, #1
    adds r0, r0, r2
    b 6f
5:  lsls r2, r2, #31 - STATUS_BURN_BIT
    bpl 6f
    lsrs r0, r0, #1
6:  strh r0, [r6, #MON_SP_ATTACK]
    ldrb r0, [r6, #STAGE_ATTACK]
    strb r0, [r6, #STAGE_SP_ATTACK]
    ldrh r0, [r7, #MON_DEFENSE]
    strh r0, [r7, #MON_SP_DEFENSE]
    ldrb r0, [r7, #STAGE_DEFENSE]
    strb r0, [r7, #STAGE_SP_DEFENSE]
    b 2f
7:  ldrh r0, [r6, #MON_SP_ATTACK]       @ special, in the physical branch
    strh r0, [r6, #MON_ATTACK]
    ldrb r0, [r6, #STAGE_SP_ATTACK]
    strb r0, [r6, #STAGE_ATTACK]
    ldrh r0, [r7, #MON_SP_DEFENSE]
    strh r0, [r7, #MON_DEFENSE]
    ldrb r0, [r7, #STAGE_SP_DEFENSE]
    strb r0, [r7, #STAGE_DEFENSE]
    movs r0, #0
    ldrh r1, [r6, #MON_ITEM]
    cmp r1, #ITEM_CHOICE_BAND
    bne 1f
    strh r0, [r6, #MON_ITEM]
1:  movs r2, #MON_ABILITY
    ldrb r1, [r6, r2]
    cmp r1, #ABILITY_SWARM
    beq 4f
    strb r0, [r6, r2]
4:  ldr r1, [r6, #MON_STATUS]
    movs r2, #1 << STATUS_BURN_BIT
    bics r1, r2
    str r1, [r6, #MON_STATUS]
2:  movs r1, #STATS
    b 8b

@ Puts back what the last frame's command saw changed (r1: STATS or RECORDS).
undo:
    push {lr}
    movs r0, #0
    strb r0, [r4, #PENDING]
    cmp r1, #RECORDS
    beq 2f
    bl swap_screens
    ldr r0, r_target
    bl mon_of
    movs r1, r0
    adds r0, r4, #KEPT_TARGET
    bl copy_target
    ldr r0, r_attacker
    bl mon_of
    movs r1, r0
    movs r0, r4
    adds r0, #KEPT_ATTACKER
    bl copy_attacker
    pop {pc}
2:  ldrb r0, [r4, #VICTIM]
    bl swap_records
    pop {pc}

@ r0 = gBattleMons[*r0].
mon_of:
    ldrb r0, [r0]
    movs r1, #MON_SIZE
    muls r0, r1
    ldr r1, r_battle_mons
    adds r0, r0, r1
    bx lr

@ Copies the attacker at r0, up to its status, or the target, up to its item,
@ to r1.
copy_attacker:
    movs r2, #ATTACKER_SIZE
    b 1f
copy_target:
    movs r2, #TARGET_SIZE
1:  subs r2, #4
    ldr r3, [r0, r2]
    str r3, [r1, r2]
    bne 1b
    bx lr

@ REFLECT and LIGHT SCREEN change places on the target's side.
swap_screens:
    ldr r0, r_target
    ldrb r0, [r0]
    ldr r1, r_positions
    ldrb r0, [r1, r0]
    lsls r0, r0, #31
    lsrs r0, r0, #30                    @ its side, × 2
    ldr r1, r_side_statuses
    adds r0, r0, r1
    ldrh r1, [r0]
    lsrs r2, r1, #1
    eors r2, r1
    lsls r2, r2, #31
    lsrs r2, r2, #31                    @ 1 when only one is up
    lsls r3, r2, #1
    orrs r2, r3
    eors r1, r2
    strh r1, [r0]
    bx lr

@ Battler r0's physical and special damage records change places.
swap_records:
    movs r1, #PROTECT_SIZE
    muls r1, r0
    ldr r0, r_protect_structs
    adds r1, r1, r0
    ldr r2, [r1, #PHYSICAL_DAMAGE]
    ldr r3, [r1, #PHYSICAL_DAMAGE + 4]
    str r3, [r1, #PHYSICAL_DAMAGE]
    str r2, [r1, #PHYSICAL_DAMAGE + 4]
    ldrb r2, [r1, #PHYSICAL_DAMAGE + 8]
    ldrb r3, [r1, #PHYSICAL_DAMAGE + 9]
    strb r3, [r1, #PHYSICAL_DAMAGE + 8]
    strb r2, [r1, #PHYSICAL_DAMAGE + 9]
    bx lr

    .align 2
r_state:           .word STATE
r_main:            .word MAIN
r_battle_cb1:      .word BATTLE_CB1
r_exec_flags:      .word EXEC_FLAGS
r_script_instr:    .word SCRIPT_INSTR
r_current_move:    .word CURRENT_MOVE
r_battle_moves:    .word BATTLE_MOVES
r_battle_struct:   .word BATTLE_STRUCT
r_battle_mons:     .word BATTLE_MONS
r_attacker:        .word BATTLER_ATTACKER
r_target:          .word BATTLER_TARGET
r_positions:       .word BATTLER_POSITIONS
r_side_statuses:   .word SIDE_STATUSES
r_protect_structs: .word PROTECT_STRUCTS
@ Each move's kind in Diamond and Pearl, a bit a move from move 0: 1 for
@ physical. A status move has its type's.
kinds:
    .byte 0xff, 0xdf, 0xfe, 0xff, 0xff, 0xff, 0x05, 0x00, 0x7f, 0x2c, 0x02, 0x1f
    .byte 0xcc, 0xbf, 0xf0, 0xa7, 0x9d, 0xfb, 0xd5, 0xef, 0xfd, 0x9f, 0xd9, 0x8f
    .byte 0xee, 0xfb, 0xff, 0xff, 0xfd, 0x57, 0x34, 0x5a, 0x81, 0x4f, 0xd6, 0x8f
    .byte 0x7d, 0xfe, 0x66, 0xb0, 0xa2, 0xf9, 0xdb, 0x51, 0x00
    .align 2
resident_end:

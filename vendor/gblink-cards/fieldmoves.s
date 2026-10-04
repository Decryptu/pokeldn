@ HM Moves Without HMs. `install` starts a V-blank hook that lets the party
@ use CUT, ROCK SMASH, STRENGTH, WATERFALL, SURF, Emerald's DIVE and FLASH
@ with the badge each needs, whether or not a Pokémon knows the move. The
@ first party Pokémon that isn't an Egg is the one shown using it.
@ - The game's scripts for a tree, a rock, a boulder, a waterfall and a dive
@   spot check for a Pokémon that knows the move and otherwise say it can't
@   be used, with a message box that returns to CANT. While that message
@   is up, the hook takes the script on to RESUME, where it goes on when a
@   Pokémon knows the move, with that Pokémon's slot in VAR_RESULT, through
@   `go_on`, which first closes the message. With the badge, and for
@   WATERFALL surfing north, which is what the game checks.
@ - The game only offers SURF when a Pokémon knows it; A facing water that
@   can be surfed, with the badge, starts the SURF script past that check,
@   also through `go_on`, which puts away the banner with a new map's name
@   as the field does when it starts a script itself.
@   On FireRed/LeafGreen, A facing a current too fast says so first, as the
@   game does when a Pokémon knows SURF.
@ - In a dark cave, with the badge, the hook lights it as FLASH does.
@ SURF and FLASH wait for the field to be idle at two V-blanks in a row, so
@ an A that closed a message doesn't start SURF. Nothing happens while
@ FireRed/LeafGreen play back "Previously on your quest". The hook is
@ copied to RESIDENT like the others, so it lasts until the game is reset;
@ clearing ENABLED turns it off.
@
@ Parameters (--defsym): INTR_VBLANK, MAIN, SCRIPT_CONTEXT, SCRIPT_STATUS,
@ CONTROLS_LOCKED, PLAYER_AVATAR, MAP_HEADER, PARTY, SPECIAL_VAR_RESULT,
@ CB2_OVERWORLD, FLAG_GET, SETUP_SCRIPT, HIDE_MAP_NAME, FACING_SURFABLE_WATER,
@ SURFING_NORTH, USE_FLASH, the CANT and RESUME addresses of each move,
@ SURF_RESUME, EMERALD and STATE; on FireRed/LeafGreen QUEST_LOG_STATE,
@ FRONT_OF_PLAYER, METATILE_BEHAVIOR_AT, IS_FAST_WATER and CURRENT_TOO_FAST.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ WAS_IDLE, 1                    @ u8: the field was idle at the last V-blank
    .equ KEPT, 4                        @ the V-blank handler the hook calls
    .equ MAIN_CALLBACK2, 4
    .equ MAIN_INTR_CHECK, 0x1C
    .equ MAIN_NEW_KEYS, 0x2E
    .equ CTX_STACK_DEPTH, 0             @ struct ScriptContext
    .equ CTX_MODE, 1
    .equ CTX_SCRIPT_PTR, 8
    .equ CTX_STACK, 0x0C
    .equ SCRIPT_MODE_BYTECODE, 1
    .equ CONTEXT_SHUTDOWN, 2
    .equ TILE_TRANSITION_STATE, 3       @ in gPlayerAvatar: 0 while standing still
    .equ MAP_CAVE, 0x15                 @ in gMapHeader: 1 for a dark cave
    .equ PARTY_SIZE, 6
    .equ MON_SIZE, 100
    .equ MON_FLAGS, 0x13                @ isBadEgg, hasSpecies, isEgg
    .equ A_POKEMON, 2
    .equ NONE, 0xFF
    .equ QL_STATE_PLAYBACK, 2           @ and 3, its last scene
    .equ MOVE_ENTRY, 12                 @ CANT, RESUME, u16 badge, u8 north
.if EMERALD
    .equ BADGE_CUT, 0x867
    .equ BADGE_FLASH, 0x868
    .equ BADGE_ROCK_SMASH, 0x869
    .equ BADGE_STRENGTH, 0x86A
    .equ BADGE_SURF, 0x86B
    .equ BADGE_DIVE, 0x86D
    .equ BADGE_WATERFALL, 0x86E
    .equ FLAG_FLASH_ON, 0x888           @ FLAG_SYS_USE_FLASH
.else
    .equ BADGE_FLASH, 0x820
    .equ BADGE_CUT, 0x821
    .equ BADGE_STRENGTH, 0x823
    .equ BADGE_SURF, 0x824
    .equ BADGE_ROCK_SMASH, 0x825
    .equ BADGE_WATERFALL, 0x826
    .equ FLAG_FLASH_ON, 0x806           @ FLAG_SYS_FLASH_ACTIVE
.endif

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
    ldr r7, r_main
    ldrh r0, [r7, #MAIN_INTR_CHECK]
    lsls r0, r0, #31
    bne 9f                              @ the game is mid-frame
    movs r6, #0                         @ idle now
    ldrb r0, [r4, #ENABLED]
    cmp r0, #0
    beq 8f
    ldr r0, [r7, #MAIN_CALLBACK2]
    ldr r1, r_cb2_overworld
    cmp r0, r1
    bne 8f
.if EMERALD == 0
    ldr r0, r_quest_log_state
    ldrb r0, [r0]
    cmp r0, #QL_STATE_PLAYBACK
    bcs 8f
.endif
    bl cant_message
    bl idle
    movs r6, r0
    ldrb r1, [r4, #WAS_IDLE]
    ands r0, r1
    beq 8f
    bl surf
    cmp r0, #0
    bne 8f
    bl flash
8:  strb r6, [r4, #WAS_IDLE]
9:  ldr r3, [r4, #KEPT]
    pop {r4, r5, r6, r7}
    pop {r0}
    mov lr, r0
    bx r3                               @ which returns for the hook

@ A "can't use the move" message box: on to where the script goes on.
cant_message:
    push {r5, r6, lr}
    ldr r5, r_context
    ldrb r0, [r5, #CTX_STACK_DEPTH]
    cmp r0, #1
    bne 8f
    ldr r0, [r5, #CTX_STACK]            @ where the message box returns to
    adr r6, moves
    movs r3, #(moves_end - moves) / MOVE_ENTRY
1:  ldr r1, [r6]
    cmp r0, r1
    beq 2f
    adds r6, #MOVE_ENTRY
    subs r3, #1
    bne 1b
    b 8f
2:  ldrh r0, [r6, #8]
    bl flag_get
    cmp r0, #0
    beq 8f
    ldrb r0, [r6, #10]
    cmp r0, #0
    beq 3f
    ldr r3, r_surfing_north
    bl call_r3
    cmp r0, #0
    beq 8f
3:  bl lead_slot
    cmp r0, #NONE
    beq 8f
    ldr r1, r_var_result
    strh r0, [r1]
    ldr r0, [r6, #4]                    @ where the script goes on, for go_on
    adr r1, go_on
    strh r0, [r1, #8]
    lsrs r0, r0, #16
    strh r0, [r1, #10]
    str r1, [r5, #CTX_SCRIPT_PTR]
    movs r0, #0
    strb r0, [r5, #CTX_STACK_DEPTH]
    movs r0, #SCRIPT_MODE_BYTECODE
    strb r0, [r5, #CTX_MODE]
8:  pop {r5, r6, pc}

@ r0 = 1 when the player stands still with the controls free and no script
@ running, else 0.
idle:
    movs r0, #0
    ldr r1, r_controls_locked
    ldrb r1, [r1]
    cmp r1, #0
    bne 1f
    ldr r1, r_script_status
    ldrb r1, [r1]
    cmp r1, #CONTEXT_SHUTDOWN
    bne 1f
    ldr r1, r_player_avatar
    ldrb r1, [r1, #TILE_TRANSITION_STATE]
    cmp r1, #0
    bne 1f
    movs r0, #1
1:  bx lr

@ A just pressed facing water that can be surfed: the SURF script. r0 = 1
@ when a script started.
surf:
    push {r5, lr}
    ldrh r0, [r7, #MAIN_NEW_KEYS]
    lsrs r0, r0, #1
    bcc 8f                              @ A not just pressed
.if EMERALD == 0
    sub sp, #4                          @ a current first, as the game checks
    mov r0, sp
    adds r1, r0, #2
    ldr r3, r_front_of_player
    bl call_r3
    mov r2, sp
    ldrh r0, [r2, #0]
    ldrh r1, [r2, #2]
    add sp, #4
    ldr r3, r_behavior_at
    bl call_r3
    ldr r3, r_is_fast_water
    bl call_r3
    ldr r5, r_current_too_fast
    cmp r0, #0
    bne 2f
.endif
    ldr r0, r_badge_surf
    bl flag_get
    cmp r0, #0
    beq 8f
    ldr r3, r_facing_water
    bl call_r3
    cmp r0, #0
    beq 8f
    ldr r5, r_surf_resume
    bl lead_slot
    cmp r0, #NONE
    beq 8f
    ldr r1, r_var_result
    strh r0, [r1]
2:  adr r0, go_on
    strh r5, [r0, #8]
    lsrs r1, r5, #16
    strh r1, [r0, #10]
    ldr r3, r_setup_script
    bl call_r3
    movs r0, #1
    pop {r5, pc}
8:  movs r0, #0
    pop {r5, pc}

@ In a dark cave not yet lit: FLASH.
flash:
    push {lr}
    ldr r0, r_map_header
    ldrb r0, [r0, #MAP_CAVE]
    cmp r0, #1
    bne 8f
    ldr r0, r_flag_flash_on
    bl flag_get
    cmp r0, #0
    bne 8f
    ldr r0, r_badge_flash
    bl flag_get
    cmp r0, #0
    beq 8f
    ldr r3, r_use_flash                 @ its sound, the flag, then its script
    bl call_r3
8:  pop {pc}

@ r0 = the first party slot with a Pokémon that isn't an Egg, else NONE.
lead_slot:
    ldr r1, r_party
    movs r0, #0
1:  ldrb r2, [r1, #MON_FLAGS]
    lsls r2, r2, #29
    lsrs r2, r2, #29
    cmp r2, #A_POKEMON
    beq 2f
    adds r1, #MON_SIZE
    adds r0, #1
    cmp r0, #PARTY_SIZE
    bne 1b
    movs r0, #NONE
2:  bx lr

flag_get:
    ldr r3, r_flag_get
call_r3:
    bx r3

    .align 2
r_state:            .word STATE
r_main:             .word MAIN
r_cb2_overworld:    .word CB2_OVERWORLD
.if EMERALD == 0
r_quest_log_state:  .word QUEST_LOG_STATE
r_front_of_player:  .word FRONT_OF_PLAYER
r_behavior_at:      .word METATILE_BEHAVIOR_AT
r_is_fast_water:    .word IS_FAST_WATER
r_current_too_fast: .word CURRENT_TOO_FAST
.endif
r_context:          .word SCRIPT_CONTEXT
r_script_status:    .word SCRIPT_STATUS
r_controls_locked:  .word CONTROLS_LOCKED
r_player_avatar:    .word PLAYER_AVATAR
r_map_header:       .word MAP_HEADER
r_party:            .word PARTY
r_var_result:       .word SPECIAL_VAR_RESULT
r_flag_get:         .word FLAG_GET
r_setup_script:     .word SETUP_SCRIPT
r_facing_water:     .word FACING_SURFABLE_WATER
r_surfing_north:    .word SURFING_NORTH
r_use_flash:        .word USE_FLASH
r_surf_resume:      .word SURF_RESUME
r_badge_surf:       .word BADGE_SURF
r_badge_flash:      .word BADGE_FLASH
r_flag_flash_on:    .word FLAG_FLASH_ON
@ callnative HIDE_MAP_NAME, closemessage, then goto RESUME or the SURF
@ script (written in at go_on + 8 by cant_message and surf)
    .align 2
go_on:
    .byte 0x23
    .4byte HIDE_MAP_NAME
    .byte 0x68, 0x00, 0x05              @ the nop aligns goto's target
    .hword 0, 0
    .align 2
moves:
    .word CUT_CANT, CUT_RESUME
    .hword BADGE_CUT
    .byte 0, 0
    .word SMASH_CANT, SMASH_RESUME
    .hword BADGE_ROCK_SMASH
    .byte 0, 0
    .word STRENGTH_CANT, STRENGTH_RESUME
    .hword BADGE_STRENGTH
    .byte 0, 0
    .word WATERFALL_CANT, WATERFALL_RESUME
    .hword BADGE_WATERFALL
    .byte 1, 0
.if EMERALD
    .word DIVE_CANT, DIVE_RESUME
    .hword BADGE_DIVE
    .byte 0, 0
    .word SURFACE_CANT, SURFACE_RESUME
    .hword BADGE_DIVE
    .byte 0, 0
.endif
moves_end:
resident_end:

@ PC Anywhere. `install` starts a V-blank hook: R pressed in the field,
@ while the player stands still with the controls free and no script
@ running, runs `pc_script`, which opens the POKéMON STORAGE SYSTEM as a PC
@ in a POKéMON CENTER does, its menu first, and gives the field back after
@ SEE YA!. Not in the Union Room, nor in a link room (their field has
@ another callback1), nor on Emerald in the Battle Frontier, whose
@ challenges keep the player's own party aside; not while FireRed/LeafGreen
@ play back "Previously on your quest", where R no longer opens the Help
@ menu either (L still does). The hook is copied to RESIDENT like the
@ others, so it lasts until the game is reset; `uninstall` turns it off and
@ gives R back to the Help menu.
@
@ Parameters (--defsym): INTR_VBLANK, MAIN, PLAYER_AVATAR, CONTROLS_LOCKED
@ (sLockFieldControls), SCRIPT_STATUS (sGlobalScriptContextStatus),
@ HELP_R_DISABLE and QUEST_LOG_STATE (0 if none), MAP_HEADER, CB1_OVERWORLD,
@ CB2_OVERWORLD, IN_UNION_ROOM, SETUP_SCRIPT, HIDE_MAP_NAME, PC_SPECIAL,
@ EMERALD and STATE.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ KEPT, 4                        @ the V-blank handler the hook calls
    .equ MAIN_CALLBACK1, 0
    .equ MAIN_CALLBACK2, 4
    .equ MAIN_INTR_CHECK, 0x1C
    .equ MAIN_NEW_KEYS, 0x2E
    .equ BUTTON_R_BIT, 8
    .equ TILE_TRANSITION_STATE, 3       @ in gPlayerAvatar: 0 while standing still
    .equ CONTEXT_SHUTDOWN, 2
    .equ MAP_SECTION, 0x14              @ in gMapHeader
    .equ MAPSEC_BATTLE_FRONTIER, 0x3A
    .equ QL_STATE_PLAYBACK, 2           @ and 3, its last scene
    .equ SE_PC_LOGIN, 2
    .equ IME, 0x04000208

install:
    push {r4, r5, r6, lr}
    ldr r0, p_intr_vblank               @ pokeldn: the game's own handler while the copy
    ldr r1, p_vblank_intr               @ overwrites whatever hook runs at RESIDENT
    str r1, [r0]
    ldr r3, p_ime
    ldrh r6, [r3]
    movs r0, #0
    strh r0, [r3]                       @ no interrupts while the hook changes
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
3:  ldr r3, p_ime
    strh r6, [r3]
    pop {r4, r5, r6, pc}

uninstall:
    ldr r0, p_state
    movs r1, #0
    strb r1, [r0, #ENABLED]
.if EMERALD == 0
    ldr r0, p_help_r_disable
    strb r1, [r0]
.endif
    bx lr

    .align 2
.if EMERALD == 0
p_help_r_disable: .word HELP_R_DISABLE
.endif
p_ime:            .word IME
p_resident:       .word RESIDENT
p_state:          .word STATE
p_intr_vblank:    .word INTR_VBLANK
p_vblank_intr:   .word VBLANK_INTR

@ ---- copied to RESIDENT
    .align 2
resident:
    push {r4, r7, lr}
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
    ldrh r0, [r7, #MAIN_NEW_KEYS]
    lsrs r0, r0, #BUTTON_R_BIT + 1
    bcc 9f                              @ R not just pressed
    ldr r0, [r7, #MAIN_CALLBACK1]
    ldr r1, r_cb1_overworld
    cmp r0, r1
    bne 9f
    ldr r0, [r7, #MAIN_CALLBACK2]
    ldr r1, r_cb2_overworld
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
    ldr r0, r_player_avatar
    ldrb r0, [r0, #TILE_TRANSITION_STATE]
    cmp r0, #0
    bne 9f
.if EMERALD
    ldr r0, r_map_header
    ldrb r0, [r0, #MAP_SECTION]
    cmp r0, #MAPSEC_BATTLE_FRONTIER
    beq 9f
.else
    ldr r0, r_quest_log_state
    ldrb r0, [r0]
    cmp r0, #QL_STATE_PLAYBACK
    bcs 9f
.endif
    ldr r3, r_in_union_room
    bl r_call_r3
    cmp r0, #0
    bne 9f
    ldr r0, r_pc_script
    ldr r3, r_setup_script
    bl r_call_r3
9:  ldr r3, [r4, #KEPT]
    bl r_call_r3
    pop {r4, r7}
    pop {r0}
    bx r0

r_call_r3:
    bx r3

    .align 2
r_state:           .word STATE
r_main:            .word MAIN
.if EMERALD
r_map_header:      .word MAP_HEADER
.else
r_help_r_disable:  .word HELP_R_DISABLE
r_quest_log_state: .word QUEST_LOG_STATE
.endif
r_cb1_overworld:   .word CB1_OVERWORLD
r_cb2_overworld:   .word CB2_OVERWORLD
r_controls_locked: .word CONTROLS_LOCKED
r_script_status:   .word SCRIPT_STATUS
r_player_avatar:   .word PLAYER_AVATAR
r_in_union_room:   .word IN_UNION_ROOM
r_setup_script:    .word SETUP_SCRIPT
r_pc_script:       .word RESIDENT + (pc_script - resident)
pc_script:
    .byte 0x23                          @ callnative: the map name banner away
    .4byte HIDE_MAP_NAME
    .byte 0x69                          @ lockall
    .byte 0x2F, SE_PC_LOGIN, 0          @ playse
    .byte 0x25, PC_SPECIAL & 0xFF, PC_SPECIAL >> 8   @ special ShowPokemonStorageSystemPC
    .byte 0x27                          @ waitstate
    .byte 0x6B                          @ releaseall
    .byte 0x02                          @ end
    .align 2
resident_end:

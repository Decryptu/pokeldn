@ Travel Anywhere. `install` starts a V-blank hook: R pressed in the field,
@ while the player stands still with the controls free on a map where FLY
@ works, opens the FLY map without a Pokémon that knows FLY. Choosing a place
@ flies there as FLY does; B goes back to the field instead of to the party
@ menu. The Pokémon shown flying is the first in the party that knows FLY,
@ else the first that isn't an Egg; with neither, R does nothing. On
@ FireRed/LeafGreen R no longer opens the Help menu (L still does). In the
@ field the hook also marks the map as one for running and cycling, which the
@ game checks when the player runs or gets on the BIKE. The hook is copied to
@ RESIDENT like the others, so it lasts until the game is reset; `uninstall`
@ turns it off and gives R back to the Help menu.
@
@ The field is left the way the START and party menus leave it for the FLY
@ map: the map name box hidden, objects frozen, a fade to black, the rain's
@ sound stopped, the overworld's windows freed, scanline effects stopped and
@ the tasks reset.
@
@ Parameters (--defsym): INTR_VBLANK, MAIN, PARTY, PLAYER_AVATAR, MAP_HEADER,
@ CONTROLS_LOCKED (sLockFieldControls), HELP_R_DISABLE (0 if none), TASKS,
@ PARTY_MENU, PALETTE_FADE, FIELD_CALLBACK, CB2_OVERWORLD, CB2_OPEN_FLY_MAP,
@ CB2_RETURN_TO_PARTY_FROM_FLY, CB2_RETURN_TO_FIELD, MAP_ALLOWS_FLY,
@ GET_MON_DATA, HIDE_MAP_NAME, FREEZE_OBJECT_EVENTS, STOP_PLAYER_AVATAR,
@ FADE_SCREEN, RAIN_SOUND_STOP, CLEANUP_OVERWORLD, SCANLINE_EFFECT_STOP,
@ RESET_TASKS, CREATE_TASK, EMERALD and STATE.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ FLYING, 1                      @ u8: the FLY map is open from R
    .equ FLYER, 2                       @ u8: the party slot shown flying
    .equ KEPT, 4                        @ the V-blank handler the hook calls
    .equ MAIN_CALLBACK2, 4
    .equ MAIN_INTR_CHECK, 0x1C
    .equ MAIN_NEW_KEYS, 0x2E
    .equ MAIN_STATE, 0x438
    .equ BUTTON_R_BIT, 8
    .equ TILE_TRANSITION_STATE, 3       @ in gPlayerAvatar: 0 while standing still
    .equ MAP_TYPE, 0x17                 @ in gMapHeader
.if EMERALD
    .equ MAP_FLAGS, 0x1A                @ allowCycling bit 0, allowRunning bit 2
    .equ RUN_AND_BIKE, 5
.else
    .equ MAP_BIKING, 0x18               @ bikingAllowed
    .equ MAP_FLAGS, 0x19                @ allowRunning bit 1
    .equ RUN_AND_BIKE, 2
.endif
    .equ PARTY_MENU_SLOT, 9             @ gPartyMenu.slotId, which FLY shows
    .equ FADE_ACTIVE, 6                 @ gPaletteFade: bit 15 of this halfword
    .equ TASK_SIZE, 0x28
    .equ TASK_DATA, 8
    .equ TASK_PRIORITY, 80
    .equ FADE_TO_BLACK, 1
    .equ PARTY_SIZE, 6
    .equ MON_SIZE, 100
    .equ MON_DATA_SPECIES, 11
    .equ MON_DATA_MOVE1, 13
    .equ MON_DATA_IS_EGG, 45
    .equ MOVE_FLY, 19
    .equ NONE, 0xFF
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
    ldr r0, p_resident_size
1:  subs r0, #4
    ldr r1, [r4, r0]
    str r1, [r5, r0]
    bne 1b
    ldr r4, p_state
    strb r0, [r4, #FLYING]
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
    ldr r0, p_help_r_disable
    cmp r0, #0
    beq 1f
    strb r1, [r0]
1:  bx lr

    .align 2
p_help_r_disable: .word HELP_R_DISABLE
p_ime:           .word IME
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
    ldr r0, r_help_r_disable
    cmp r0, #0
    beq 1f
    movs r1, #1
    strb r1, [r0]
1:  ldr r0, [r7, #MAIN_CALLBACK2]
    ldr r1, r_return_to_party
    cmp r0, r1
    bne 2f
    ldrb r1, [r4, #FLYING]
    cmp r1, #0
    beq 9f
    movs r1, #0                         @ B on the FLY map: to the field instead
    strb r1, [r4, #FLYING]
    ldr r2, r_field_callback
    str r1, [r2]
    ldr r2, r_main_state
    strb r1, [r2]
    ldr r1, r_return_to_field
    str r1, [r7, #MAIN_CALLBACK2]
    b 9f
2:  ldr r1, r_cb2_overworld
    cmp r0, r1
    bne 9f
    ldr r1, r_map_header
    ldrb r0, [r1, #MAP_FLAGS]
    movs r2, #RUN_AND_BIKE
    orrs r0, r2
    strb r0, [r1, #MAP_FLAGS]
.if EMERALD == 0
    movs r0, #1
    strb r0, [r1, #MAP_BIKING]
.endif
    movs r0, #0
    strb r0, [r4, #FLYING]
    ldrh r0, [r7, #MAIN_NEW_KEYS]
    lsrs r0, r0, #BUTTON_R_BIT + 1
    bcc 9f                              @ R not just pressed
    ldr r5, r_controls_locked
    ldrb r0, [r5]
    cmp r0, #0
    bne 9f
    ldr r0, r_player_avatar
    ldrb r0, [r0, #TILE_TRANSITION_STATE]
    cmp r0, #0
    bne 9f
    ldr r0, r_map_header
    ldrb r0, [r0, #MAP_TYPE]
    ldr r3, r_map_allows_fly
    bl r_call_r3
    cmp r0, #0
    beq 9f
    bl pick_flyer
    cmp r0, #NONE
    beq 9f
    strb r0, [r4, #FLYER]
    movs r0, #1
    strb r0, [r5]                       @ LockPlayerFieldControls
    ldr r0, r_fly_task
    movs r1, #TASK_PRIORITY
    ldr r3, r_create_task
    bl r_call_r3
9:  ldr r3, [r4, #KEPT]
    bl r_call_r3
    pop {r4, r5, r6, r7}
    pop {r0}
    bx r0

@ The task R starts: hides the map name, freezes the field and fades to black,
@ then opens the FLY map.
fly_task:
    push {r4, lr}
    movs r1, #TASK_SIZE
    muls r1, r0
    ldr r4, r_tasks
    adds r4, r4, r1
    ldrh r0, [r4, #TASK_DATA]
    cmp r0, #0
    bne 1f
    ldr r3, r_hide_map_name
    bl r_call_r3
    ldr r3, r_freeze_object_events
    bl r_call_r3
    ldr r3, r_stop_player_avatar
    bl r_call_r3
    movs r0, #FADE_TO_BLACK
    movs r1, #0
    ldr r3, r_fade_screen
    bl r_call_r3
    movs r0, #1
    strh r0, [r4, #TASK_DATA]
    pop {r4, pc}
1:  ldr r0, r_palette_fade
    ldrh r0, [r0, #FADE_ACTIVE]
    lsls r0, r0, #16
    bmi 9f                              @ still fading
    ldr r0, r_state
    ldrb r1, [r0, #FLYER]
    ldr r2, r_party_menu
    strb r1, [r2, #PARTY_MENU_SLOT]
    movs r1, #1
    strb r1, [r0, #FLYING]
    ldr r3, r_rain_sound_stop
    bl r_call_r3
    ldr r3, r_cleanup_overworld
    bl r_call_r3
    ldr r3, r_scanline_effect_stop
    bl r_call_r3
    ldr r3, r_reset_tasks               @ this task too
    bl r_call_r3
    ldr r0, r_main_state
    movs r1, #0
    strb r1, [r0]
    ldr r0, r_main
    ldr r1, r_open_fly_map
    str r1, [r0, #MAIN_CALLBACK2]
9:  pop {r4, pc}

@ r0 = the party slot of the first Pokémon that knows FLY, else of the first
@ that isn't an Egg, else NONE.
pick_flyer:
    push {r4, r5, r6, r7, lr}
    movs r6, #NONE
    movs r4, #0
1:  movs r0, #MON_SIZE
    muls r0, r4
    ldr r5, r_party
    adds r5, r5, r0
    movs r0, r5
    movs r1, #MON_DATA_SPECIES
    bl get_mon_data
    cmp r0, #0
    beq 4f
    movs r0, r5
    movs r1, #MON_DATA_IS_EGG
    bl get_mon_data
    cmp r0, #0
    bne 4f
    cmp r6, #NONE
    bne 2f
    movs r6, r4
2:  movs r7, #MON_DATA_MOVE1
3:  movs r0, r5
    movs r1, r7
    bl get_mon_data
    cmp r0, #MOVE_FLY
    beq 5f
    adds r7, #1
    cmp r7, #MON_DATA_MOVE1 + 4
    bne 3b
4:  adds r4, #1
    cmp r4, #PARTY_SIZE
    bne 1b
    movs r0, r6
    pop {r4, r5, r6, r7, pc}
5:  movs r0, r4
    pop {r4, r5, r6, r7, pc}

get_mon_data:
    movs r2, #0
    ldr r3, r_get_mon_data
r_call_r3:
    bx r3

    .align 2
r_state:                .word STATE
r_main:                 .word MAIN
r_main_state:           .word MAIN + MAIN_STATE
r_help_r_disable:       .word HELP_R_DISABLE
r_return_to_party:      .word CB2_RETURN_TO_PARTY_FROM_FLY
r_field_callback:       .word FIELD_CALLBACK
r_return_to_field:      .word CB2_RETURN_TO_FIELD
r_cb2_overworld:        .word CB2_OVERWORLD
r_controls_locked:      .word CONTROLS_LOCKED
r_player_avatar:        .word PLAYER_AVATAR
r_map_header:           .word MAP_HEADER
r_map_allows_fly:       .word MAP_ALLOWS_FLY
r_fly_task:             .word RESIDENT + (fly_task - resident) + 1
r_create_task:          .word CREATE_TASK
r_tasks:                .word TASKS
r_hide_map_name:        .word HIDE_MAP_NAME
r_freeze_object_events: .word FREEZE_OBJECT_EVENTS
r_stop_player_avatar:   .word STOP_PLAYER_AVATAR
r_fade_screen:          .word FADE_SCREEN
r_palette_fade:         .word PALETTE_FADE
r_rain_sound_stop:      .word RAIN_SOUND_STOP
r_party_menu:           .word PARTY_MENU
r_cleanup_overworld:    .word CLEANUP_OVERWORLD
r_scanline_effect_stop: .word SCANLINE_EFFECT_STOP
r_reset_tasks:          .word RESET_TASKS
r_open_fly_map:         .word CB2_OPEN_FLY_MAP
r_party:                .word PARTY
r_get_mon_data:         .word GET_MON_DATA
resident_end:

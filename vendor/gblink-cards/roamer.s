@ Roaming Pokémon. `roamer_info` puts the roamer's species name in gStringVar1
@ and the name of the map it is on in gStringVar2; VAR_RESULT = 1, or 0 when
@ none is roaming.
@
@ `install` starts a V-blank hook that, while STATE's first byte is 1 and the
@ roamer roams, moves it to the player's map whenever that map is one of the
@ routes it roams (the first column of sRoamerLocations). The game's own rule
@ then has it turn up in 1 of 4 wild encounters there. It is copied to
@ RESIDENT like the other hooks, so it lasts until the game is reset.
@
@ Parameters (--defsym): SB1_PTR, SPECIAL_VAR_RESULT, STRING_VAR_1,
@ STRING_VAR_2, ROAMER_LOCATION (sRoamerLocation), ROAMER_LOCATIONS
@ (sRoamerLocations), GET_SPECIES_NAME, GET_MAP_HEADER, GET_MAP_NAME,
@ INTR_VBLANK, STATE and EMERALD.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ KEPT, 4                        @ the V-blank handler the hook calls
    .equ LOCATION_GROUP, 4              @ in SaveBlock1: the player's map
    .equ LOCATION_NUM, 5
    .equ ROAMER_SPECIES, 8
    .equ ROAMER_ACTIVE, 0x13
    .equ MAP_SECTION, 0x14              @ in a MapHeader
    .equ NO_MAP, 0xFF                   @ ends sRoamerLocations
    .equ IME, 0x04000208
.if EMERALD
    .equ ROAMER, 0x31DC                 @ in SaveBlock1
    .equ ROAMER_GROUP, 0
    .equ ROAMER_ROW, 6
.else
    .equ ROAMER, 0x30D0
    .equ ROAMER_GROUP, 3
    .equ ROAMER_ROW, 7
.endif

roamer_info:
    push {r4, lr}
    ldr r4, p_sb1_ptr
    ldr r4, [r4]
    ldr r0, p_roamer
    adds r4, r4, r0
    ldrb r0, [r4, #ROAMER_ACTIVE]
    ldr r1, p_var_result
    strh r0, [r1]
    cmp r0, #0
    beq 9f
    ldrh r1, [r4, #ROAMER_SPECIES]
    ldr r0, p_string_var_1
    ldr r3, p_get_species_name
    bl call_r3
    ldr r2, p_roamer_location
    ldrb r0, [r2]
    ldrb r1, [r2, #1]
    ldr r3, p_get_map_header
    bl call_r3
    ldrb r1, [r0, #MAP_SECTION]
    ldr r0, p_string_var_2
    movs r2, #0                         @ no padding
    ldr r3, p_get_map_name
    bl call_r3
9:  pop {r4, pc}

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

call_r3:
    bx r3

    .align 2
p_sb1_ptr:          .word SB1_PTR
p_roamer:           .word ROAMER
p_var_result:       .word SPECIAL_VAR_RESULT
p_string_var_1:     .word STRING_VAR_1
p_string_var_2:     .word STRING_VAR_2
p_get_species_name: .word GET_SPECIES_NAME
p_roamer_location:  .word ROAMER_LOCATION
p_get_map_header:   .word GET_MAP_HEADER
p_get_map_name:     .word GET_MAP_NAME
p_ime:              .word IME
p_resident:         .word RESIDENT
p_resident_size:    .word resident_end - resident
p_state:            .word STATE
p_intr_vblank:      .word INTR_VBLANK
p_vblank_intr:   .word VBLANK_INTR

@ ---- copied to RESIDENT
    .align 2
resident:
    push {r4, lr}
    ldr r4, r_state
    ldrb r0, [r4, #ENABLED]
    cmp r0, #0
    beq 9f
    ldr r0, r_sb1_ptr
    ldr r0, [r0]
    ldr r1, r_roamer_active
    ldrb r1, [r0, r1]
    cmp r1, #0
    beq 9f
    ldrb r1, [r0, #LOCATION_GROUP]
    cmp r1, #ROAMER_GROUP
    bne 9f
    ldrb r2, [r0, #LOCATION_NUM]
    ldr r3, r_locations
1:  ldrb r0, [r3]
    cmp r0, r2
    beq 2f
    adds r3, #ROAMER_ROW
    cmp r0, #NO_MAP
    bne 1b
    b 9f
2:  ldr r0, r_roamer_location
    strb r1, [r0]
    strb r2, [r0, #1]
9:  ldr r3, [r4, #KEPT]
    bl r_call_r3
    pop {r4}
    pop {r0}
    bx r0

r_call_r3:
    bx r3

    .align 2
r_state:           .word STATE
r_sb1_ptr:         .word SB1_PTR
r_roamer_active:   .word ROAMER + ROAMER_ACTIVE
r_locations:       .word ROAMER_LOCATIONS
r_roamer_location: .word ROAMER_LOCATION
resident_end:

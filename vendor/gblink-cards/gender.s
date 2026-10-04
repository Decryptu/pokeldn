@ Gender Swap and trainer rename.
@
@ `swap` flips the gender in SaveBlock2 (offset 8) and gPlayerAvatar (offset
@ 7) and redraws the player: GetPlayerAvatarGraphicsIdByStateIdAndGender,
@ ObjectEventSetGraphicsId, then ObjectEventTurn to restart the facing
@ animation. `rename` opens the game's naming screen for the player, and
@ `update_ot` gives the new name to every Pokémon with the player's trainer id
@ in the party, the PC boxes and the Day Care, so they still count as the
@ player's own.
@
@ Parameters (--defsym): SB2_PTR, SB1_PTR, PLAYER_AVATAR, OBJECT_EVENTS, PARTY,
@ STORAGE_PTR (&gPokemonStoragePtr), DAYCARE (its offset in SaveBlock1),
@ AVATAR_GRAPHICS_ID, SET_GRAPHICS_ID, OBJECT_EVENT_TURN, DO_NAMING_SCREEN,
@ RETURN_TO_FIELD (CB2_ReturnToFieldContinueScript) and those of relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ STATE_NORMAL, 0
    .equ OBJECT_EVENT_SIZE, 0x24
    .equ PLAYER_GENDER, 8
    .equ PLAYER_ID, 10
    .equ PLAYER_NAME_LENGTH, 7
    .equ NAMING_SCREEN_PLAYER, 0
    .equ DAYCARE_MON_SIZE, 0x8C
    .equ BOX_COUNT_4, 14 * 30 / 4

swap:
    push {r4, r5, lr}
    ldr r0, p_sb2_ptr
    ldr r0, [r0]
    ldrb r1, [r0, #PLAYER_GENDER]
    movs r2, #1
    eors r1, r2
    strb r1, [r0, #PLAYER_GENDER]
    ldr r4, p_player_avatar
    strb r1, [r4, #7]
    ldrb r5, [r4, #5]                   @ the player's object event
    movs r0, #OBJECT_EVENT_SIZE
    muls r5, r0
    ldr r0, p_object_events
    adds r5, r5, r0
    movs r0, #STATE_NORMAL              @ r1: the new gender
    ldr r3, p_avatar_graphics_id
    bl call_r3
    movs r1, r0
    movs r0, r5
    ldr r3, p_set_graphics_id
    bl call_r3
    ldrb r1, [r5, #0x18]                @ facingDirection, the low nibble
    lsls r1, r1, #28
    lsrs r1, r1, #28
    movs r0, r5
    ldr r3, p_object_event_turn
    bl call_r3
    pop {r4, r5}
    pop {r0}
    bx r0

@ DoNamingScreen(NAMING_SCREEN_PLAYER, playerName, playerGender, 0, 0,
@ CB2_ReturnToFieldContinueScript).
rename:
    push {r4, lr}
    sub sp, #8
    ldr r3, p_return_to_field
    str r3, [sp, #4]
    movs r0, #0
    str r0, [sp]
    ldr r1, p_sb2_ptr
    ldr r1, [r1]
    ldrb r2, [r1, #PLAYER_GENDER]
    movs r3, #0
    movs r0, #NAMING_SCREEN_PLAYER
    ldr r4, p_naming_screen
    bl call_r4
    add sp, #8
    pop {r4, pc}

update_ot:
    push {r4, r5, r6, r7, lr}
    ldr r7, p_sb2_ptr
    ldr r7, [r7]                        @ the name, at the start of SaveBlock2
    movs r0, #PLAYER_ID + 3
1:  lsls r5, r5, #8                     @ the trainer id, as a Pokémon stores it
    ldrb r1, [r7, r0]
    orrs r5, r1
    subs r0, #1
    cmp r0, #PLAYER_ID
    bge 1b
    ldr r4, p_party
    movs r6, #PARTY_SIZE
    movs r2, #MON_SIZE
    bl fix_range
    ldr r4, p_storage_ptr
    ldr r4, [r4]
    adds r4, #4                         @ PokemonStorage.boxes
    movs r6, #BOX_COUNT_4
    lsls r6, r6, #2
    movs r2, #BOX_MON_SIZE
    bl fix_range
    ldr r4, p_sb1_ptr
    ldr r4, [r4]
    ldr r0, p_daycare
    adds r4, r4, r0
    movs r6, #2
    movs r2, #DAYCARE_MON_SIZE
    bl fix_range
    pop {r4, r5, r6, r7}
    pop {r0}
    bx r0

@ For r6 Pokémon from r4, r2 bytes apart: those with trainer id r5 get the
@ name at r7 as their OT name, copied the way the game does.
fix_range:
1:  subs r6, #1
    bmi 4f
    ldrb r1, [r4, #MON_FLAGS]
    lsls r1, r1, #30                    @ hasSpecies
    bpl 3f
    ldr r1, [r4, #MON_OT_ID]
    cmp r1, r5
    bne 3f
    movs r1, r4
    adds r1, #MON_OT_NAME
    movs r0, #PLAYER_NAME_LENGTH
2:  subs r0, #1
    ldrb r3, [r7, r0]
    strb r3, [r1, r0]
    bne 2b
3:  adds r4, r4, r2
    b 1b
4:  bx lr

call_r3:
    bx r3

call_r4:
    bx r4

    .align 2
p_sb2_ptr:            .word SB2_PTR
p_sb1_ptr:            .word SB1_PTR
p_player_avatar:      .word PLAYER_AVATAR
p_object_events:      .word OBJECT_EVENTS
p_party:              .word PARTY
p_storage_ptr:        .word STORAGE_PTR
p_daycare:            .word DAYCARE
p_avatar_graphics_id: .word AVATAR_GRAPHICS_ID
p_set_graphics_id:    .word SET_GRAPHICS_ID
p_object_event_turn:  .word OBJECT_EVENT_TURN
p_naming_screen:      .word DO_NAMING_SCREEN
p_return_to_field:    .word RETURN_TO_FIELD

    .include "mons.inc"
    .include "relocate.inc"

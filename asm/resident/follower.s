@ A resident V-blank hook that walks the lead Pokemon one tile behind the player as a real object
@ event, moved by the game's own movement actions, so the game draws its steps, runs, ledge jumps
@ (arc, shadow, dust), fades and priority. After GB-Link's cards/follow.s (GPL-3.0,
@ github.com/GB-Link/GB-Link-Switch-LDN). docs/frlg_rom.md, `follower`, has the model and the state.
@
@ Local id FOLLOW_ID, elevation NO_ELEVATION: no tile has it, so the player walks back through it
@ and nothing talks to it. A species without an overworld sprite shows its party icon: the object
@ wears Snorlax's 32x32 frame and its sprite's images point at the table at p_images, on OBJ palette 15.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00
    .equ OBJECT, 0                      @ state: u8, the follower's object event or NONE
    .equ PENDING, 1                     @ u8, 1 while a step waits to be taken
    .equ ICON, 2                        @ u8, 1 when it shows the lead's icon
    .equ FAMILY, 3                      @ u8, the player's movement action, facing down
    .equ PLAYER_XY, 4                   @ s16 x 2, the player's coordinates last seen
    .equ TARGET_XY, 8                   @ s16 x 2, the tile the follower goes to
    .equ SPECIES, 12                    @ u16, the lead's
    .equ SHOWN, 14                      @ u16, the species the follower was spawned for
    .equ LEDGE, 16                      @ u8, 1 from the player's ledge jump to the follower's
    .equ NONE, 0xFF
    .equ FOLLOW_ID, 0xF0                @ a local id no map uses
    .equ NO_ELEVATION, 14
    .equ OBJ_SIZE, 0x24                 @ struct ObjectEvent
    .equ OBJ_FLAGS, 0                   @ bit 0 active, 6 heldMovementActive, 7 finished
    .equ OBJ_FLAGS_1, 1                 @ bit 5 invisible
    .equ OBJ_FLAGS_3, 3                 @ bit 2 fixedPriority
    .equ OBJ_SPRITE, 4
    .equ OBJ_LOCAL_ID, 8
    .equ OBJ_ELEVATION, 0x0B            @ current in the low 4 bits, previous in the high
    .equ OBJ_CURRENT, 0x10
    .equ OBJ_PREVIOUS, 0x14
    .equ OBJ_DIRECTION, 0x18            @ facing low, movement high
    .equ OBJ_ACTION, 0x1C
    .equ INVISIBLE_BIT, 5
    .equ SPRITE_SIZE, 0x44
    .equ WALK_NORMAL, 0x10              @ MOVEMENT_ACTION_WALK_NORMAL_DOWN
    .equ JUMP_2, 0x14                   @ MOVEMENT_ACTION_JUMP_2_DOWN
    .equ WALK_FAST, 0x1D                @ MOVEMENT_ACTION_WALK_FAST_DOWN
    .equ WALK_FASTER, 0x35              @ MOVEMENT_ACTION_WALK_FASTER_DOWN
    .equ PLAYER_RUN, 0x3D               @ MOVEMENT_ACTION_PLAYER_RUN_DOWN
    .equ WALK_IN_PLACE_SLOW, 0x21       @ MOVEMENT_ACTION_WALK_IN_PLACE_SLOW_DOWN, a bump
    .equ GFX_SNORLAX, 109               @ OBJ_EVENT_GFX_SNORLAX, 32x32 on sAnimTable_Standard

    .global follower_hook
follower_hook:
    push    {r4, r5, r6, r7, lr}
    ldr     r4, p_state
    ldr     r0, p_gmain
    ldrh    r1, [r0, #0x1C]             @ intrCheck bit 0 clear: the main loop is parked
    ldr     r0, [r0, #4]
    ldr     r2, p_cb2_overworld
    eors    r0, r2
    lsls    r1, r1, #31
    orrs    r0, r1
    push    {r0}                        @ 0: an idle overworld frame
    ldr     r3, p_original
    bl      call_r3                     @ the game's VBlankIntr first: its transfers keep their time
    pop     {r0}
    cmp     r0, #0
    bne     9f
    bl      follow
    bl      talk
9:  pop     {r4, r5, r6, r7}
    pop     {r0}
    bx      r0

call_r3:
    bx      r3
call_r7:
    bx      r7

@ r4 = state. r5 = the player's object event, r6 = the follower's.
follow:
    push    {lr}
    ldr     r0, p_avatar
    ldrb    r0, [r0, #5]
    movs    r1, #OBJ_SIZE
    muls    r0, r1
    ldr     r5, p_objects
    adds    r5, r5, r0
    bl      lead_graphics               @ r0: its graphics id, 0 for none
@ r7 = 1 while a menu is up (the field locked, no script running), the start menu's SAVE among
@ them: no follower then, so none is ever saved.
    ldr     r7, p_controls_locked
    ldrb    r7, [r7]
    cmp     r7, #0
    beq     15f
    ldr     r7, p_script_status
    ldrb    r7, [r7]
    lsrs    r7, r7, #1                  @ CONTEXT_SHUTDOWN 2; running 0, waiting 1
15:
@ The follower is the active object event of local id FOLLOW_ID: none on a new map.
    ldr     r6, p_objects
    movs    r1, #0
12: ldrb    r2, [r6, #OBJ_FLAGS]
    lsls    r2, r2, #31
    beq     13f
    ldrb    r2, [r6, #OBJ_LOCAL_ID]
    cmp     r2, #FOLLOW_ID
    beq     14f
13: adds    r6, #OBJ_SIZE
    adds    r1, #1
    cmp     r1, #16
    bne     12b
    b       1f
14: strb    r1, [r4, #OBJECT]
    ldrh    r1, [r4, #SHOWN]
    ldrh    r2, [r4, #SPECIES]
    cmp     r1, r2
    bne     16f
    cmp     r7, #0
    beq     4f                          @ still ours, still the lead
16: push    {r0}
    movs    r0, r6
    ldr     r3, p_remove_object
    bl      call_r3
    pop     {r0}
1:  movs    r1, #NONE
    strb    r1, [r4, #OBJECT]
    cmp     r0, #0
    beq     17f                         @ an empty party
    cmp     r7, #0
    beq     3f
17: b       9f
@ A new follower on the player's tile, hidden until the first step.
3:  sub     sp, #8
    ldrb    r1, [r5, #OBJ_ELEVATION]
    lsls    r1, r1, #28
    lsrs    r1, r1, #28
    str     r1, [sp, #4]                @ elevation
    ldrh    r1, [r5, #OBJ_CURRENT + 2]
    str     r1, [sp]                    @ y
    ldrh    r3, [r5, #OBJ_CURRENT]      @ x
    movs    r1, #0                      @ MOVEMENT_TYPE_NONE
    movs    r2, #FOLLOW_ID
    ldr     r7, p_spawn_object
    bl      call_r7
    add     sp, #8
    cmp     r0, #16
    bcc     18f
    b       9f                          @ no free object event
18: strb    r0, [r4, #OBJECT]
    movs    r1, #OBJ_SIZE
    muls    r0, r1
    ldr     r6, p_objects
    adds    r6, r6, r0
    ldrh    r0, [r4, #SPECIES]
    strh    r0, [r4, #SHOWN]
    bl      icon_frames
    bl      hide
    ldr     r0, [r5, #OBJ_CURRENT]
    str     r0, [r4, #PLAYER_XY]
    movs    r0, #0
    strb    r0, [r4, #PENDING]
4:  bl      icon_sprite
    ldrb    r0, [r6, #OBJ_ELEVATION]    @ nothing collides with it
    lsrs    r0, r0, #4
    lsls    r0, r0, #4
    adds    r0, #NO_ELEVATION
    strb    r0, [r6, #OBJ_ELEVATION]
@ A save made by a script keeps it, and a load resets each object's elevation from its tile
@ unless its priority is fixed: fixed while the field is locked.
    ldr     r0, p_controls_locked
    ldrb    r0, [r0]
    lsls    r0, r0, #2
    strb    r0, [r6, #OBJ_FLAGS_3]
    ldr     r0, p_avatar
    ldrb    r0, [r0]
    movs    r1, #0x1E                   @ either bike, surfing, underwater
    tst     r0, r1
    beq     5f
@ Riding or surfing: hidden on the player's tile.
    bl      hide
    ldr     r1, [r5, #OBJ_CURRENT]
    str     r1, [r4, #PLAYER_XY]
    ldr     r0, [r6, #OBJ_CURRENT]
    cmp     r0, r1
    beq     9f
    movs    r0, #0
    strb    r0, [r4, #PENDING]
    ldrh    r1, [r5, #OBJ_CURRENT]
    ldrh    r2, [r5, #OBJ_CURRENT + 2]
    b       move_to
5:  ldr     r0, [r5, #OBJ_CURRENT]
    ldr     r1, [r4, #PLAYER_XY]
    cmp     r0, r1
    beq     6f
@ The player has begun a step: the follower goes where it was.
    str     r0, [r4, #PLAYER_XY]
    ldrb    r0, [r5, #OBJ_DIRECTION]
    lsrs    r0, r0, #4
    ldrb    r1, [r5, #OBJ_ACTION]
    adds    r1, #1
    subs    r1, r1, r0                  @ its action's down
    cmp     r1, #JUMP_2
    bne     7f
@ A ledge moves the player's coordinates twice, onto the ledge and past it: the first takes the
@ follower to the edge, the second leaves it there, and it jumps after the player's next step.
    ldrb    r0, [r4, #LEDGE]
    cmp     r0, #0
    bne     6f                          @ the second tile
    movs    r0, #1
    strb    r0, [r4, #LEDGE]
    movs    r1, #WALK_NORMAL
7:  cmp     r1, #PLAYER_RUN
    bne     11f
    movs    r1, #WALK_FAST              @ a Pokemon's sprite has no running frames
11: strb    r1, [r4, #FAMILY]
    ldr     r0, [r5, #OBJ_PREVIOUS]
    str     r0, [r4, #TARGET_XY]
    movs    r0, #1
    strb    r0, [r4, #PENDING]
6:  ldrb    r0, [r4, #PENDING]
    cmp     r0, #0
    beq     9f
    ldrb    r0, [r6, #OBJ_FLAGS]
    lsrs    r1, r0, #7                  @ finished
    bne     8f
    lsls    r0, r0, #25
    bmi     9f                          @ still moving
8:  movs    r0, r6
    ldr     r3, p_clear_held_movement
    bl      call_r3
    movs    r0, #0
    strb    r0, [r4, #PENDING]
    ldrh    r1, [r4, #TARGET_XY]
    ldrh    r2, [r4, #TARGET_XY + 2]
    ldrh    r0, [r6, #OBJ_CURRENT]
    subs    r0, r1, r0                  @ dx (map coordinates are never negative)
    ldrh    r3, [r6, #OBJ_CURRENT + 2]
    subs    r3, r2, r3                  @ dy
    ldrb    r7, [r4, #FAMILY]
    movs    r1, #3                      @ right
    cmp     r0, #1
    beq     3f
    cmp     r0, #2
    beq     2f
    movs    r1, #2                      @ left
    adds    r0, #1
    beq     3f
    adds    r0, #1
    beq     2f
    cmp     r0, #2
    bne     1f                          @ off in x too: straight there
    movs    r1, #0                      @ down
    cmp     r3, #1
    beq     3f
    cmp     r3, #2
    beq     2f
    movs    r1, #1                      @ up
    adds    r3, #1
    beq     3f
    adds    r3, #1
    beq     2f
    cmp     r3, #2
    beq     4f                          @ already there: just seen
1:  movs    r0, #0
    strb    r0, [r4, #LEDGE]
    ldrh    r1, [r4, #TARGET_XY]
    ldrh    r2, [r4, #TARGET_XY + 2]
    b       move_to
@ Two in a line: down the ledge the player jumped; anywhere else it fell behind (its own jump
@ took two of the player's steps), and it closes up one tile at a time, faster than a run.
2:  ldrb    r0, [r4, #LEDGE]
    cmp     r0, #0
    beq     5f
    movs    r7, #JUMP_2
    movs    r0, #0
    strb    r0, [r4, #LEDGE]
    b       3f
5:  movs    r7, #WALK_FASTER
    movs    r0, #1
    strb    r0, [r4, #PENDING]          @ the same target, one tile nearer
3:  adds    r1, r7, r1                  @ two in a line: down a ledge; one: a step
    movs    r0, r6
    ldr     r3, p_set_held_movement
    bl      call_r3
4:  ldrb    r0, [r6, #OBJ_FLAGS_1]      @ seen from the first step on
    movs    r1, #1 << INVISIBLE_BIT
    bics    r0, r1
    strb    r0, [r6, #OBJ_FLAGS_1]
9:  pop     {pc}

@ The follower at (r1, r2), where its next steps start from; returns from follow.
move_to:
    movs    r0, r6
    ldr     r3, p_move_object_to
    bl      call_r3
    pop     {pc}

hide:
    ldrb    r0, [r6, #OBJ_FLAGS_1]
    movs    r1, #1 << INVISIBLE_BIT
    orrs    r0, r1
    strb    r0, [r6, #OBJ_FLAGS_1]
    bx      lr

@ The icon's two frames for Snorlax's nine: standing frames 0..2 show frame 0, walking 3..8 frame 1,
@ as the party menu alternates them. GetMonIconPtr picks Unown's letter.
icon_frames:
    push    {lr}
    ldrb    r0, [r4, #ICON]
    cmp     r0, #0
    beq     2f
    ldrh    r0, [r4, #SPECIES]
    ldr     r1, p_party
    ldr     r1, [r1]                    @ personality
    movs    r2, #0
    ldr     r3, p_get_mon_icon
    bl      call_r3
    ldr     r1, p_images
    movs    r2, #0
    movs    r7, #1
    lsls    r7, r7, #9                  @ 0x200 bytes a frame
1:  cmp     r2, #3
    bne     3f
    adds    r0, r0, r7                  @ frame 1 from the first walking frame on
3:  lsls    r3, r2, #3
    str     r0, [r1, r3]
    adds    r3, #4
    str     r7, [r1, r3]
    adds    r2, #1
    cmp     r2, #9
    bne     1b
2:  pop     {pc}

@ Each idle frame on an icon: its sprite reads icon_images on palette 15, and the palette goes to
@ gPlttBufferUnfaded, and to gPlttBufferFaded only at blend y 0, so a fade darkens it with the map
@ and a finished fade-out (y 16, `active` clear) stays black [palette.c].
icon_sprite:
    push    {lr}
    ldrb    r0, [r4, #ICON]
    cmp     r0, #0
    beq     1f
    ldrb    r1, [r6, #OBJ_SPRITE]
    movs    r0, #SPRITE_SIZE
    muls    r1, r0
    ldr     r0, p_sprites
    adds    r1, r1, r0
    ldr     r0, p_images
    str     r0, [r1, #0x0C]             @ images
    ldrb    r0, [r1, #5]
    movs    r2, #0xF0
    orrs    r0, r2
    strb    r0, [r1, #5]                @ oam.paletteNum 15
    ldrh    r0, [r4, #SPECIES]
    ldr     r1, p_icon_pal_indices
    ldrb    r0, [r1, r0]
    lsls    r0, r0, #5
    ldr     r1, p_icon_palettes
    adds    r0, r0, r1
    push    {r0}
    ldr     r2, p_pal_unfaded
    bl      copy32
    pop     {r0}
    ldr     r2, p_palette_fade
    ldrh    r1, [r2, #4]                @ delayCounter:6 y:5 targetY:5
    lsls    r1, r1, #21
    lsrs    r1, r1, #27
    bne     1f
    ldr     r2, p_pal_faded
    bl      copy32
1:  pop     {pc}

@ 32 bytes from r0 to r2.
copy32:
    movs    r1, #8
1:  ldmia   r0!, {r3}
    stmia   r2!, {r3}
    subs    r1, #1
    bne     1b
    bx      lr

@ In the field, facing the follower: A runs talk_script; pushing into it (the player bumps where
@ elevation 0 lets anything collide) puts it on the player's tile, so the way is free. r4 = state,
@ r5 and r6 as follow left them.
talk:
    push    {lr}
    ldr     r0, p_controls_locked
    ldrb    r0, [r0]
    cmp     r0, #0
    bne     9f                          @ a menu, or a script the A started
    ldrb    r1, [r4, #OBJECT]
    cmp     r1, #NONE
    beq     9f
@ The tile in front of the player: facing 1 south, 2 north, 3 west, 4 east.
    ldrb    r2, [r5, #OBJ_DIRECTION]
    lsls    r2, r2, #28
    lsrs    r2, r2, #27                 @ twice the facing
    cmp     r2, #4
    bhi     1f
    movs    r0, #3
    subs    r0, r0, r2
    lsls    r0, r0, #16                 @ y + 1 or y - 1
    b       2f
1:  subs    r0, r2, #7                  @ x - 1 or x + 1
2:  ldr     r2, [r5, #OBJ_CURRENT]
    adds    r0, r0, r2
    ldr     r2, [r6, #OBJ_CURRENT]
    cmp     r0, r2
    bne     9f
    ldr     r0, p_gmain
    ldrh    r0, [r0, #0x2E]             @ gMain.newKeys
    lsrs    r0, r0, #1
    bcs     3f
    ldrb    r0, [r5, #OBJ_ACTION]
    subs    r0, #WALK_IN_PLACE_SLOW
    cmp     r0, #3
    bhi     9f
    bl      hide
    ldrh    r1, [r5, #OBJ_CURRENT]
    ldrh    r2, [r5, #OBJ_CURRENT + 2]
    b       move_to
3:  ldrh    r0, [r4, #SPECIES]
    movs    r2, #206
    lsls    r2, r2, #1
    cmp     r0, r2
    beq     9f                          @ SPECIES_EGG (412): no cry, no line
    ldr     r0, p_selected_object       @ lock and faceplayer act on it
    strb    r1, [r0]
    movs    r0, r6
    ldr     r3, p_clear_held_movement
    bl      call_r3
    adr     r0, talk_script
    ldrh    r1, [r4, #SPECIES]
    strh    r1, [r0, #2]
    ldr     r3, p_setup_script
    bl      call_r3
9:  pop     {pc}

@ r0 = the lead's graphics id: its own overworld sprite where the cartridge has one, else
@ Snorlax's frame with ICON set; 0 for an empty party.
lead_graphics:
    push    {lr}
    ldr     r0, p_party
    movs    r1, #65                     @ MON_DATA_SPECIES_OR_EGG: an egg shows the egg icon
    movs    r2, #0
    ldr     r3, p_get_mon_data
    bl      call_r3
    strh    r0, [r4, #SPECIES]
    movs    r2, #0
    strb    r2, [r4, #ICON]
    cmp     r0, #0
    beq     3f
    movs    r1, #205
    lsls    r1, r1, #1
    cmp     r0, r1
    bne     1f
    movs    r0, #252                    @ Deoxys: an unused species number stands for it
1:  adr     r1, species
2:  ldrb    r3, [r1, r2]
    cmp     r3, r0
    beq     4f
    adds    r2, #1
    cmp     r2, #42
    bne     2b
    movs    r2, #1
    strb    r2, [r4, #ICON]
    movs    r2, #0                      @ Snorlax's frame
4:  movs    r0, r2
    adds    r0, #GFX_SNORLAX
3:  pop     {pc}

    .align 2
@ playmoncry's species at +2 is written in when A is pressed. lock and faceplayer act on
@ gSelectedObjectEvent, set to the follower first.
talk_script:
    .byte   0x6A                        @ lock
    .byte   0xA1                        @ playmoncry SPECIES, CRY_MODE_NORMAL
    .2byte  0, 0
    .byte   0x5A                        @ faceplayer
    .byte   0x4F                        @ applymovement FOLLOW_ID, smile
    .2byte  FOLLOW_ID
    .4byte  RESIDENT + (smile - follower_hook)
    .byte   0x51                        @ waitmovement 0
    .2byte  0
    .byte   0xC5                        @ waitmoncry
    .byte   0x7F, 0                     @ bufferpartymonnick STR_VAR_1, 0
    .2byte  0
    .byte   0x67                        @ message
    .4byte  RESIDENT + (p_text - follower_hook)
    .byte   0x66, 0x6D, 0x6C, 0x02      @ waitmessage, waitbuttonpress, release, end
smile:
    .byte   0x66, 0xFE                  @ MOVEMENT_ACTION_EMOTE_SMILE, step_end
    .global p_text
p_text:
    .space  20                          @ the builder's line, in the cartridge's language

@ The species for OBJ_EVENT_GFX_SNORLAX (109) onwards, one byte each [include/constants/event_objects.h:115].
@ 253 never matches; 252, unused, stands for Deoxys (410): the builder puts it on the version's form,
@ Attack on FireRed, Defense on LeafGreen (p_deoxys, the three bytes and the padding after them).
    .align 2
species:
    .byte   143, 21, 104, 62, 35, 18, 39, 16, 113, 138, 115, 25, 54, 29, 32, 33, 52, 86, 100, 79
    .byte   80, 66, 40, 84, 22, 67, 131, 145, 146, 144, 150, 151, 244, 245, 243, 249, 250, 251, 140
    .global p_deoxys
p_deoxys:
    .byte   253, 253, 252               @ Deoxys Defense, Attack, Normal

    .align 2
    .global p_original, p_gmain, p_cb2_overworld, p_get_mon_data, p_state, p_get_mon_icon
    .global p_icon_pal_indices, p_icon_palettes, p_controls_locked, p_setup_script
    .global p_script_status, p_selected_object, p_spawn_object, p_set_held_movement
    .global p_clear_held_movement, p_move_object_to, p_remove_object, p_images
p_original:             .word 0x0800071D    @ patched by the installer: the handler it replaced
p_gmain:                .word 0x030022D0    @ gMain (French FireRed)
p_cb2_overworld:        .word 0x08059EC9    @ CB2_Overworld, THUMB (French FireRed)
p_get_mon_data:         .word 0x080432E5    @ GetMonData, THUMB (French FireRed)
p_get_mon_icon:         .word 0x0809AA75    @ GetMonIconPtr, THUMB (French FireRed)
p_icon_pal_indices:     .word 0x083CBEE8    @ gMonIconPaletteIndices (French FireRed)
p_icon_palettes:        .word 0x083CB7A8    @ gMonIconPalettes (French FireRed)
p_controls_locked:      .word 0x0300109C    @ sLockFieldControls
p_script_status:        .word 0x03000FA8    @ sGlobalScriptContextStatus
p_selected_object:      .word 0x03004294    @ gSelectedObjectEvent (French FireRed)
p_setup_script:         .word 0x0806D3D5    @ ScriptContext_SetupScript, THUMB (French FireRed)
p_spawn_object:         .word 0x08062131    @ SpawnSpecialObjectEventParameterized (French FireRed)
p_set_held_movement:    .word 0x080675A5    @ ObjectEventSetHeldMovement (French FireRed)
p_clear_held_movement:  .word 0x08067635    @ ObjectEventClearHeldMovement (French FireRed)
p_move_object_to:       .word 0x08063025    @ MoveObjectEventToMapCoords (French FireRed)
p_remove_object:        .word 0x08061DB5    @ RemoveObjectEvent (French FireRed)
p_state:                .word 0x0203FFDC    @ 16 bytes of state, near the top of EWRAM
p_images:               .word 0x0203FBB4    @ nine SpriteFrameImage the icon's sprite reads, below the
                                            @ handler the installer keeps at 0x0203FBFC
p_party:                .word 0x02024280    @ gPlayerParty; EWRAM is the same on all four cartridges
p_avatar:               .word 0x02037074    @ gPlayerAvatar
p_objects:              .word 0x02036E34    @ gObjectEvents
p_sprites:              .word 0x0202063C    @ gSprites
p_palette_fade:         .word 0x02037AB4    @ gPaletteFade
p_pal_unfaded:          .word 0x020375D4    @ gPlttBufferUnfaded, OBJ palette 15
p_pal_faded:            .word 0x020379D4    @ gPlttBufferFaded, OBJ palette 15

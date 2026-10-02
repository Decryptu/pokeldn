@ A resident V-blank hook that draws the lead Pokemon walking one tile behind the player: the
@ cartridge's own overworld sprite where it has one (OBJ_EVENT_GFX_SNORLAX..DEOXYS_N, 9 frames on
@ sAnimTable_Standard [src/data/object_events/object_event_anims.h:1022]), else its party icon. One OAM
@ entry, not an object event: an object on the tile the player left blocks the step back
@ [src/event_object_movement.c:4899]. docs/frlg_rom.md, install-resident, `follower`.
@ State at p_state, its layout and the step model: that page.

    .thumb
    .align 2
    .global follower_hook
follower_hook:
    push    {r4, r5, r6, r7, lr}
    ldr     r7, p_state
    ldr     r0, p_gmain
    ldrh    r0, [r0, #0x1C]         @ gMain.intrCheck
    push    {r0}                    @ bit 0 clear: the main loop is idle
    bl      .Ldraw
    ldr     r3, p_original
    bl      .Lcall                  @ the game's VBlankIntr
    pop     {r0}
    lsr     r0, r0, #1
    bcs     .Lout                   @ a lag frame: the main loop may be inside the party
    ldr     r0, p_party
    mov     r1, #65                 @ MON_DATA_SPECIES_OR_EGG: an egg does not follow
    mov     r2, #0
    ldr     r3, p_get_mon_data
    bl      .Lcall
    strh    r0, [r7, #24]
.Lout:
    pop     {r4, r5, r6, r7}
    pop     {r0}
    bx      r0

.Lcall:
    bx      r3

@ Clobbers r0..r6.
.Ldraw:
    push    {lr}
    ldr     r0, p_gmain
    ldr     r0, [r0, #4]
    ldr     r1, p_cb2_overworld
    cmp     r0, r1
    bne     .Lskip                  @ a battle, a menu screen, a map load: drawn again on return
    ldr     r0, p_palette_fade
    ldrh    r0, [r0, #6]            @ blendColor:15, active:1
    lsr     r0, r0, #15
    bne     .Lskip                  @ a door or a warp is fading
    ldr     r4, p_avatar
    ldrb    r0, [r4]                @ gPlayerAvatar.flags
    mov     r1, #0x1E               @ either bike, surfing, underwater
    tst     r0, r1
    beq     .Lon_foot
.Lhide:
    b       .Lreset
.Lskip:
    b       .Ldone
.Lon_foot:
    ldrb    r0, [r4, #5]            @ objectEventId
    mov     r1, #0x24
    mul     r0, r1
    ldr     r4, p_objects
    add     r4, r0                  @ r4: the player's object event
    ldrb    r0, [r4, #4]            @ spriteId
    mov     r1, #0x44
    mul     r0, r1
    ldr     r5, p_sprites
    add     r5, r0                  @ r5: the player's sprite
    ldrh    r0, [r5, #4]
    strh    r0, [r7, #28]

    @ previousCoords jumping more than two tiles in a frame: a warp, or a map connection moving every
    @ object by the offset between the two maps. The follower starts over and walks in from behind
    @ on the next step; the sprites stay put, so the anchor moves the other way. State as the install
    @ found it is caught here too.
    mov     r6, #0                  @ axis byte offset: 0 = x, 2 = y
.Lshift_axis:
    add     r1, r4, r6
    ldrh    r0, [r1, #0x14]         @ previousCoords on this axis
    add     r1, r7, r6
    ldrh    r2, [r1, #16]           @ its value last frame
    sub     r0, r0, r2
    lsl     r0, r0, #16
    asr     r0, r0, #16
    add     r2, r0, #2
    cmp     r2, #4
    bls     .Lshift_next
    ldrh    r2, [r1, #12]
    lsl     r0, r0, #4
    sub     r2, r2, r0
    strh    r2, [r1, #12]
    mov     r0, #0
    strb    r0, [r7, #20]
.Lshift_next:
    add     r6, #2
    cmp     r6, #4
    bne     .Lshift_axis
    ldr     r0, [r4, #0x14]         @ previousCoords as one word
    str     r0, [r7, #16]

    ldr     r0, [r4, #0x10]         @ currentCoords
    ldr     r1, [r4, #0x14]
    mov     r6, #0                  @ progress, in pixels
    cmp     r0, r1
    bne     .Lmoving
    @ At rest: anchor = sprite - 16 * tile, and the follower has arrived.
    mov     r3, #0
.Lanchor_axis:
    add     r1, r5, r3
    ldrh    r0, [r1, #0x20]         @ sprite x or y
    add     r1, r4, r3
    ldrh    r1, [r1, #0x10]
    lsl     r1, r1, #4
    sub     r0, r0, r1
    add     r1, r7, r3
    strh    r0, [r1, #12]
    add     r3, #2
    cmp     r3, #4
    bne     .Lanchor_axis
    ldr     r0, [r7, #4]
    str     r0, [r7, #0]
    b       .Lstepped

.Lmoving:
    ldr     r2, [r7, #8]
    cmp     r0, r2
    beq     .Lprogress
    @ A new step: the follower walks from its tile to the one the player is leaving, the way the
    @ player walked the step before.
    ldrb    r2, [r4, #0x18]
    lsr     r2, r2, #4
    sub     r2, #1                  @ movementDirection: 1 S, 2 N, 3 W, 4 E
    ldrb    r0, [r7, #20]
    cmp     r0, #0
    bne     .Lplaced
    mov     r0, #1
    strb    r0, [r7, #20]
    strb    r0, [r7, #22]           @ the parity, set up: its first step shows walking frame 1
    strb    r2, [r7, #23]
    lsl     r3, r1, #1              @ the first step: walk in from one step behind the tile the
    ldr     r0, [r4, #0x10]         @ player leaves, 2 * previous - current on both halves
    sub     r3, r3, r0
    str     r3, [r7, #4]
.Lplaced:
    ldrb    r0, [r7, #23]
    strb    r0, [r7, #21]
    strb    r2, [r7, #23]
    ldr     r0, [r7, #4]
    str     r0, [r7, #0]            @ source: where it stands
    str     r1, [r7, #4]            @ target: the player's previous tile
    ldrb    r0, [r7, #22]
    mov     r2, #1
    eor     r0, r2
    strb    r0, [r7, #22]
.Lprogress:
    @ |sprite - (anchor + 16 * previousCoords)| over both axes; a ledge's two tiles clamp at one.
    mov     r3, #0
.Lprog_axis:
    add     r1, r5, r3
    ldrh    r0, [r1, #0x20]         @ sprite x or y
    add     r1, r7, r3
    ldrh    r2, [r1, #12]           @ anchor
    sub     r0, r0, r2
    add     r1, r4, r3
    ldrh    r2, [r1, #0x14]         @ previousCoords
    lsl     r2, r2, #4
    sub     r0, r0, r2
    lsl     r0, r0, #16
    asr     r0, r0, #16
    bpl     .Lprog_abs
    neg     r0, r0
.Lprog_abs:
    add     r6, r0
    add     r3, #2
    cmp     r3, #4
    bne     .Lprog_axis
    cmp     r6, #16
    bls     .Lstepped
    mov     r6, #16
.Lstepped:
    ldr     r0, [r4, #0x10]
    str     r0, [r7, #8]
    ldrb    r0, [r7, #20]
    cmp     r0, #0
    beq     .Lskip2
    ldrh    r0, [r5, #0x3E]
    lsr     r0, r0, #3              @ the player's sprite invisible: a cutscene hides it
    bcs     .Lskip2

    @ The lead's own overworld sprite where the cartridge has one, else its party menu icon.
    ldrh    r0, [r7, #24]
    mov     r1, #205
    lsl     r1, r1, #1
    cmp     r0, r1
    bne     .Lnot_deoxys
    mov     r0, #252                @ Deoxys: an unused species number stands for it in the table
.Lnot_deoxys:
    adr     r1, .Lspecies
    mov     r2, #0
.Lfind:
    ldrb    r3, [r1, r2]
    cmp     r3, r0
    beq     .Lfound
    add     r2, #1
    cmp     r2, #42
    bne     .Lfind

    @ The icon: GetMonIconPtr picks Unown's letter; frames 0 and 1 alternate every 16 V-blanks, as
    @ in the party menu; its palette is gMonIconPalettes[gMonIconPaletteIndices[species]].
    ldrh    r4, [r7, #24]
    cmp     r4, #0
    beq     .Lskip2                 @ an empty party
    ldr     r0, p_icon_pal_indices
    ldrb    r0, [r0, r4]
    lsl     r0, r0, #5
    ldr     r1, p_icon_palettes
    add     r0, r1
    push    {r0}
    mov     r0, r4
    ldr     r1, p_party
    ldr     r1, [r1]                @ personality
    mov     r2, #0
    ldr     r3, p_get_mon_icon
    bl      .Lcall
    ldr     r1, p_gmain
    ldr     r1, [r1, #0x24]         @ vblankCounter2
    lsl     r1, r1, #27
    lsr     r1, r1, #31
    lsl     r1, r1, #9
    add     r0, r1                  @ frame 1 is 0x200 bytes on
    mov     r1, #1
    lsl     r1, r1, #9
    mov     r5, #32
    b       .Lsprite

.Lfound:
    add     r2, #109                @ OBJ_EVENT_GFX_SNORLAX + the index
    lsl     r2, r2, #2
    ldr     r1, p_gfx_info
    ldr     r4, [r1, r2]            @ r4: its ObjectEventGraphicsInfo
    @ The palette: Pokemon use tags 0x1103..0x1106, entries 0..3 of sObjectEventSpritePalettes.
    ldrh    r0, [r4, #2]
    lsl     r0, r0, #29
    lsr     r0, r0, #26             @ (tag & 7) * 8: 24..48
    ldr     r1, p_obj_palettes
    sub     r1, #24
    ldr     r0, [r1, r0]
    push    {r0}
    @ The frame: standing 0 S, 1 N, 2 W/E; walking 3/4 S, 5/6 N, 7/8 W/E for the first half of a step.
    ldrb    r2, [r7, #21]
    cmp     r2, #2
    blo     .Lstand
    mov     r2, #2
.Lstand:
    sub     r0, r6, #1
    cmp     r0, #7
    bhs     .Lframe                 @ still, or the second half of a step
    ldr     r0, [r7]
    ldr     r1, [r7, #4]
    cmp     r0, r1
    beq     .Lframe                 @ the follower itself is not moving
    lsl     r2, r2, #1
    add     r2, #3
    ldrb    r0, [r7, #22]
    add     r2, r0
.Lframe:
    lsl     r2, r2, #3
    ldr     r0, [r4, #0x1C]         @ images
    add     r0, r2
    ldrh    r1, [r0, #4]            @ size in bytes: 0x80 or 0x200
    ldr     r0, [r0]                @ the frame's 4bpp tiles
    ldrh    r5, [r4, #8]            @ width; the sprites are square

.Lsprite:                           @ r0 tiles, r1 their size, r5 the width, the palette pushed
    ldr     r2, p_tiles
    bl      .Lcopy
    @ Only gPlttBufferFaded: the game's own colours for palette 15 stay in gPlttBufferUnfaded.
    pop     {r0}
    ldr     r2, p_pal_faded
    mov     r1, #32
    bl      .Lcopy

    @ The position, in the player's sprite frame: anchor + 16 * source + progress * (target - source).
    mov     r3, #2
.Lpos_axis:
    add     r1, r7, r3
    ldrh    r0, [r1, #12]           @ anchor
    ldrh    r2, [r1, #0]            @ source
    lsl     r4, r2, #4
    add     r0, r4
    ldrh    r4, [r1, #4]            @ target
    sub     r4, r4, r2
    mul     r4, r6
    add     r0, r4
    ldr     r1, p_coord_offset
    ldrh    r1, [r1, r3]            @ gSpriteCoordOffsetX / Y
    add     r0, r1
    lsr     r1, r5, #1
    sub     r0, r0, r1              @ x: the left edge
    cmp     r3, #0
    beq     .Lpos_x
    sub     r0, r0, r1
    add     r0, #16                 @ y: the top, the bottom on the tile's
    lsl     r0, r0, #24
    lsr     r0, r0, #24
    push    {r0}
    sub     r3, #2
    b       .Lpos_axis
.Lskip2:
    b       .Ldone
.Lpos_x:
    lsl     r0, r0, #23
    lsr     r0, r0, #23
    lsr     r5, r5, #5              @ 16 -> 0, 32 -> 1
    add     r5, #1                  @ OAM size 1 (16x16) or 2 (32x32)
    lsl     r5, r5, #14
    orr     r0, r5
    ldrb    r2, [r7, #21]
    cmp     r2, #3
    bne     .Lnoflip
    mov     r2, #1
    lsl     r2, r2, #12
    orr     r0, r2                  @ facing east: the west frames flipped
.Lnoflip:
    ldrh    r2, [r7, #28]           @ the player's attr2: its priority against the background
    ldr     r3, .Lprio_mask
    and     r2, r3
    ldr     r3, .Lattr2
    orr     r2, r3
    ldr     r3, p_oam
    pop     {r1}
    strh    r1, [r3]                @ attr0: y, square, 4bpp
    strh    r0, [r3, #2]            @ attr1: x, size, flip
    strh    r2, [r3, #4]            @ attr2: tile 1008, palette 15, the player's priority
    b       .Ldone
.Lreset:
    mov     r0, #0
    strb    r0, [r7, #20]
.Ldone:
    pop     {r0}
    bx      r0

@ Copy r1 bytes (a multiple of 8) from r0 to r2, two words at a time: VRAM takes no byte stores.
.Lcopy:
    push    {r4}
.Lcopy_loop:
    ldmia   r0!, {r3, r4}
    stmia   r2!, {r3, r4}
    sub     r1, #8
    bne     .Lcopy_loop
    pop     {r4}
    bx      lr

    .align 2
.Lprio_mask:
    .word   0x0C00
.Lattr2:
    .word   0xF3F0                  @ palette 15, tile 1008

@ The species for OBJ_EVENT_GFX_SNORLAX (109) onwards, one byte each [include/constants/event_objects.h:115].
@ 253 never matches; 252, unused, stands for Deoxys (410): the builder puts it on the version's form,
@ Attack on FireRed, Defense on LeafGreen (p_deoxys, the three bytes and the padding after them).
.Lspecies:
    .byte   143                     @ Snorlax
    .byte   21                      @ Spearow
    .byte   104                     @ Cubone
    .byte   62                      @ Poliwrath
    .byte   35                      @ Clefairy
    .byte   18                      @ Pidgeot
    .byte   39                      @ Jigglypuff
    .byte   16                      @ Pidgey
    .byte   113                     @ Chansey
    .byte   138                     @ Omanyte
    .byte   115                     @ Kangaskhan
    .byte   25                      @ Pikachu
    .byte   54                      @ Psyduck
    .byte   29                      @ Nidoran F
    .byte   32                      @ Nidoran M
    .byte   33                      @ Nidorino
    .byte   52                      @ Meowth
    .byte   86                      @ Seel
    .byte   100                     @ Voltorb
    .byte   79                      @ Slowpoke
    .byte   80                      @ Slowbro
    .byte   66                      @ Machop
    .byte   40                      @ Wigglytuff
    .byte   84                      @ Doduo
    .byte   22                      @ Fearow
    .byte   67                      @ Machoke
    .byte   131                     @ Lapras
    .byte   145                     @ Zapdos
    .byte   146                     @ Moltres
    .byte   144                     @ Articuno
    .byte   150                     @ Mewtwo
    .byte   151                     @ Mew
    .byte   244                     @ Entei
    .byte   245                     @ Suicune
    .byte   243                     @ Raikou
    .byte   249                     @ Lugia
    .byte   250                     @ Ho-Oh
    .byte   251                     @ Celebi
    .byte   140                     @ Kabuto
    .global p_deoxys
p_deoxys:
    .byte   253, 253, 252           @ Deoxys Defense, Attack, Normal

    .align 2
    .global p_original, p_gmain, p_cb2_overworld, p_get_mon_data, p_gfx_info
    .global p_obj_palettes, p_state, p_oam, p_get_mon_icon, p_icon_pal_indices, p_icon_palettes
p_original:
    .word   0x0800071D              @ patched by the installer: the handler this one replaced
p_gmain:
    .word   0x030022D0              @ gMain (French FireRed)
p_cb2_overworld:
    .word   0x08059EC9              @ CB2_Overworld, THUMB (French FireRed)
p_get_mon_data:
    .word   0x080432E5              @ GetMonData, THUMB (French FireRed)
p_gfx_info:
    .word   0x083983C8              @ gObjectEventGraphicsInfoPointers (French FireRed)
p_obj_palettes:
    .word   0x0839D770              @ sObjectEventSpritePalettes (French FireRed)
p_get_mon_icon:
    .word   0x0809AA75              @ GetMonIconPtr, THUMB (French FireRed)
p_icon_pal_indices:
    .word   0x083CBEE8              @ gMonIconPaletteIndices (French FireRed)
p_icon_palettes:
    .word   0x083CB7A8              @ gMonIconPalettes (French FireRed)
p_oam:
    .word   0x03002700              @ gMain.oamBuffer[127] (French FireRed)
p_state:
    .word   0x0203FFC0              @ 30 bytes of state, past the hook
p_party:
    .word   0x02024280              @ gPlayerParty; EWRAM is the same on all four cartridges
p_palette_fade:
    .word   0x02037AB4              @ gPaletteFade
p_avatar:
    .word   0x02037074              @ gPlayerAvatar
p_objects:
    .word   0x02036E34              @ gObjectEvents
p_sprites:
    .word   0x0202063C              @ gSprites
p_coord_offset:
    .word   0x02021BC8              @ gSpriteCoordOffsetX, then Y
p_pal_faded:
    .word   0x020379D4              @ gPlttBufferFaded, OBJ palette 15
p_tiles:
    .word   0x06017E00              @ OBJ tile 1008

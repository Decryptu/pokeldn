@ A resident V-blank hook that lets the player walk through walls while R is held: on each idle
@ overworld frame it gives the four tiles around the player collision 0 and elevation 15 in the map
@ grid (VMap.map, gBackupMapData), and puts back what it changed the next frame. docs/frlg_rom.md,
@ `noclip`. Elevation 15 passes IsElevationMismatchAt and leaves the player's own elevation alone
@ [event_object_movement.c:8346, 8400]; MAPGRID_UNDEFINED tiles stay, or the player leaves the map.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ LAYOUT, 0                      @ state: gMapHeader.mapLayout when the tiles were changed
    .equ COUNT, 4                       @ u32, entries in use
    .equ ENTRIES, 8                     @ 4 x {u16 grid index, u16 original block}
    .equ OBJ_SIZE, 0x24                 @ struct ObjectEvent
    .equ OBJ_CURRENT, 0x10              @ s16 x, s16 y
    .equ VMAP_XSIZE, 0
    .equ VMAP_YSIZE, 4
    .equ VMAP_MAP, 8
    .equ FREE, 0x3C                     @ block >> 10 of a changed tile: elevation 15, collision 0

    .global noclip_hook
noclip_hook:
    push    {r4, r5, r6, r7, lr}
    ldr     r0, p_gmain
    ldrh    r1, [r0, #0x1C]             @ intrCheck bit 0 clear: the main loop is parked
    ldr     r0, [r0, #4]
    ldr     r2, p_cb2_overworld
    eors    r0, r2
    lsls    r1, r1, #31
    orrs    r0, r1
    push    {r0}                        @ 0: an idle overworld frame
    ldr     r3, p_original
    bl      call_r3                     @ the game's VBlankIntr first
    pop     {r0}
    cmp     r0, #0
    bne     9f
    bl      walls
9:  pop     {r4, r5, r6, r7}
    pop     {r0}
    bx      r0

call_r3:
    bx      r3

@ r4 = state, r5 = VMap, r6 = the grid.
walls:
    push    {lr}
    ldr     r0, p_help                  @ R does not open the Help System [help_system_util.c:50]
    movs    r1, #1
    strb    r1, [r0]
    ldr     r4, p_state
    ldr     r5, p_vmap
    ldr     r6, [r5, #VMAP_MAP]
@ Put back last frame's tiles, on the same layout and only where the block is still ours.
    ldr     r0, p_map_header
    ldr     r0, [r0]
    ldr     r1, [r4, #LAYOUT]
    ldr     r2, [r4, #COUNT]
    movs    r3, #0
    str     r3, [r4, #COUNT]
    cmp     r0, r1
    bne     3f
    movs    r7, r4
    adds    r7, #ENTRIES
1:  cmp     r2, #0
    beq     3f
    ldrh    r0, [r7]
    lsls    r0, r0, #1
    ldrh    r1, [r7, #2]
    ldrh    r3, [r6, r0]
    eors    r3, r1
    lsls    r3, r3, #22                 @ the same metatile
    bne     2f
    ldrh    r3, [r6, r0]
    lsrs    r3, r3, #10
    cmp     r3, #FREE
    bne     2f
    strh    r1, [r6, r0]
2:  adds    r7, #4
    subs    r2, #1
    b       1b
3:  ldr     r0, p_gmain
    ldrh    r0, [r0, #0x2C]             @ heldKeys
    ldr     r1, p_hold
    ands    r0, r1
    cmp     r0, r1
    bne     8f
    ldr     r0, p_map_header
    ldr     r0, [r0]
    str     r0, [r4, #LAYOUT]
    ldr     r0, p_avatar
    ldrb    r0, [r0, #5]                @ objectEventId
    movs    r1, #OBJ_SIZE
    muls    r0, r1
    ldr     r7, p_objects
    adds    r7, r7, r0
    movs    r2, #OBJ_CURRENT
    ldrsh   r0, [r7, r2]
    adds    r2, #2
    ldrsh   r1, [r7, r2]
    movs    r7, r0                      @ r7 = x; y goes on the stack
    push    {r1}
    subs    r0, r7, #1
    bl      free_tile
    adds    r0, r7, #1
    ldr     r1, [sp]
    bl      free_tile
    ldr     r1, [sp]
    subs    r1, #1
    movs    r0, r7
    bl      free_tile
    ldr     r1, [sp]
    adds    r1, #1
    movs    r0, r7
    bl      free_tile
    add     sp, #4
8:  pop     {r0}
    bx      r0

@ r0 = x, r1 = y, inside the grid: the block becomes elevation 15, collision 0, and is recorded.
free_tile:
    cmp     r0, #0
    blt     9f
    ldr     r2, [r5, #VMAP_XSIZE]
    cmp     r0, r2
    bge     9f
    cmp     r1, #0
    blt     9f
    ldr     r3, [r5, #VMAP_YSIZE]
    cmp     r1, r3
    bge     9f
    muls    r2, r1
    adds    r2, r2, r0                  @ the grid index
    lsls    r3, r2, #1
    ldrh    r0, [r6, r3]                @ the original block
    lsls    r1, r0, #22
    lsrs    r1, r1, #22
    adds    r1, #1
    lsrs    r1, r1, #10
    bne     9f                          @ MAPGRID_UNDEFINED, 0x3FF
    lsls    r1, r0, #22
    lsrs    r1, r1, #22
    push    {r2}
    movs    r2, #0xF
    lsls    r2, r2, #12
    orrs    r1, r2
    pop     {r2}
    strh    r1, [r6, r3]
    ldr     r1, [r4, #COUNT]
    lsls    r3, r1, #2
    adds    r3, r3, r4
    strh    r2, [r3, #ENTRIES]
    strh    r0, [r3, #ENTRIES + 2]
    adds    r1, #1
    str     r1, [r4, #COUNT]
9:  bx      lr

    .align 2
    .global p_original, p_gmain, p_cb2_overworld, p_vmap, p_hold, p_help, p_state
p_original:             .word 0x0800071D    @ patched by the installer: the handler it replaced
p_gmain:                .word 0x030022D0    @ gMain (French FireRed)
p_cb2_overworld:        .word 0x08059EC9    @ CB2_Overworld, THUMB (French FireRed)
p_vmap:                 .word 0x03004260    @ VMap (French; 0x03004310 English)
p_hold:                 .word 0x00000100    @ every button in it held: R
p_help:                 .word 0x0203F171    @ gHelpSystemToggleWithRButtonDisabled
p_state:                .word 0x0203FF80    @ 24 bytes
p_map_header:           .word 0x02036DF8    @ gMapHeader; EWRAM is the same on all four cartridges
p_avatar:               .word 0x02037074    @ gPlayerAvatar
p_objects:              .word 0x02036E34    @ gObjectEvents

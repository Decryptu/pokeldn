@ The overlay shared by the resident hooks: the word at p_overlay as eight hex digits in the top-right
@ corner of the overworld. The including hook defines p_overlay, p_gmain, p_cb2_overworld,
@ p_overlay_tiles, p_overlay_pal and p_overlay_oam [docs/frlg_rom.md, install-resident].

@ The overlay. Both halves return at once unless p_overlay is set and callback2 is CB2_Overworld.
.Loverlay_on:                       @ -> Z set when the overlay should not draw
    ldr     r0, p_overlay
    cmp     r0, #0
    beq     .Lov_on_done
    ldr     r1, p_gmain
    ldr     r1, [r1, #4]
    ldr     r2, p_cb2_overworld
    cmp     r1, r2
    bne     .Lov_off                @ the overworld only: battle sprites fill OBJ VRAM
    cmp     r0, #0                  @ Z clear: draw
    bx      lr
.Lov_off:
    mov     r0, #0
    cmp     r0, #0                  @ Z set
.Lov_on_done:
    bx      lr

.Loverlay_oam:
    push    {r4, r5, r6, r7, lr}      @ the same frame as .Loverlay_tiles: both leave by .Lov_done
    bl      .Loverlay_on
    beq     .Lov_done
    ldr     r0, p_overlay_pal
    ldr     r1, .Lwhite
    mov     r2, #0
    strh    r1, [r0]                @ gPlttBufferFaded, OBJ palette 15 colour 1
    strh    r2, [r0, #2]            @ colour 2, black
    ldr     r3, .Lunfaded
    sub     r0, r0, r3
    strh    r1, [r0]                @ gPlttBufferUnfaded, so a fade settles on the same colours
    strh    r2, [r0, #2]
    ldr     r0, p_overlay
    ldr     r0, [r0]                @ the word shown
    ldr     r5, p_overlay_oam       @ gMain.oamBuffer[120]
    mov     r4, #0
.Ldigit:
    lsr     r1, r0, #28             @ the top nibble
    ldr     r2, .Lattr2
    add     r2, r1                  @ tile 1008 + nibble, palette 15
    mov     r3, #2
    strh    r3, [r5]                @ attr0: y 2, 8x8, 4bpp
    lsl     r3, r4, #3
    add     r3, #174
    strh    r3, [r5, #2]            @ attr1: x 174 + 8 * digit
    strh    r2, [r5, #4]            @ attr2
    lsl     r0, r0, #4
    add     r5, #8
    add     r4, #1
    cmp     r4, #8
    bne     .Ldigit
    b       .Lov_done

.Loverlay_tiles:
    push    {r4, r5, r6, r7, lr}
    bl      .Loverlay_on
    beq     .Lov_done
    ldr     r5, p_overlay_tiles     @ already there, as far as two words can tell: skip the upload.
    ldr     r0, [r5, #4]            @ '0' row 1 and 'F' row 5, as expanded below.
    ldr     r1, .Lsentinel0
    cmp     r0, r1
    bne     .Lupload
    ldr     r2, .Lsentinel_off
    ldr     r0, [r5, r2]
    ldr     r1, .LsentinelF
    cmp     r0, r1
    beq     .Lov_done
.Lupload:                           @ 3x5 glyphs at pixels 2..4 of rows 1..5, the rest background
    adr     r4, .Lfont
    mov     r7, #16
.Lglyph:
    ldrh    r6, [r4]                @ row 0 in bits 0..2, bit 0 the leftmost pixel
    add     r4, #2
    mov     r3, #8
.Lrow:
    ldr     r1, .Lblank
    cmp     r3, #8
    beq     .Lstore                 @ row 0
    cmp     r3, #3
    blo     .Lstore                 @ rows 6 and 7
    mov     r0, #1
    and     r0, r6
    lsl     r0, r0, #8
    sub     r1, r1, r0              @ pixel 2: colour 2 -> 1
    mov     r0, #2
    and     r0, r6
    lsl     r0, r0, #11
    sub     r1, r1, r0              @ pixel 3
    mov     r0, #4
    and     r0, r6
    lsl     r0, r0, #14
    sub     r1, r1, r0              @ pixel 4
    lsr     r6, r6, #3
.Lstore:
    str     r1, [r5]                @ one 4bpp row; VRAM takes no byte stores
    add     r5, #4
    sub     r3, #1
    bne     .Lrow
    sub     r7, #1
    bne     .Lglyph
.Lov_done:
    pop     {r4, r5, r6, r7}
    pop     {r0}
    bx      r0

    .align 2
.Lwhite:
    .word   0x7FFF
.Lattr2:
    .word   0xF3F0                  @ palette 15, priority 0, tile 1008
.Lunfaded:
    .word   0x400                   @ gPlttBufferUnfaded is 0x400 below gPlttBufferFaded
.Lblank:
    .word   0x22222222              @ a row of background, colour 2
.Lsentinel0:
    .word   0x22211122              @ '0' row 1: pixels 2..4 in colour 1
.Lsentinel_off:
    .word   15 * 32 + 5 * 4         @ 'F' row 5
.LsentinelF:
    .word   0x22222122              @ 'F' row 5: pixel 2 in colour 1
.Lfont:                             @ 16 hex digits, 3x5, three bits a row from the top
    .hword  0x7B6F                  @ 0: ### #.# #.# #.# ###
    .hword  0x749A                  @ 1: .#. ##. .#. .#. ###
    .hword  0x73E7                  @ 2: ### ..# ### #.. ###
    .hword  0x79E7                  @ 3: ### ..# ### ..# ###
    .hword  0x49ED                  @ 4: #.# #.# ### ..# ..#
    .hword  0x79CF                  @ 5: ### #.. ### ..# ###
    .hword  0x7BCF                  @ 6: ### #.. ### #.# ###
    .hword  0x4927                  @ 7: ### ..# ..# ..# ..#
    .hword  0x7BEF                  @ 8: ### #.# ### #.# ###
    .hword  0x79EF                  @ 9: ### #.# ### ..# ###
    .hword  0x5BEF                  @ A: ### #.# ### #.# #.#
    .hword  0x3AEB                  @ B: ##. #.# ##. #.# ##.
    .hword  0x724F                  @ C: ### #.. #.. #.. ###
    .hword  0x3B6B                  @ D: ##. #.# #.# #.# ##.
    .hword  0x73CF                  @ E: ### #.. ### #.. ###
    .hword  0x13CF                  @ F: ### #.. ### #.. #..
    .align 2

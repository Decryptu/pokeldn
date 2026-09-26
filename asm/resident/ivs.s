@ A resident V-blank hook that shows the lead Pokemon's six IVs and its nature over the overworld:
@ HP, Attack, Defense, Speed on the first row, Sp. Atk, Sp. Def and the nature on the second, two
@ decimal digits each.
@
@ GetMonData(mon, MON_DATA_IVS) returns the six IVs packed five bits apiece, HP lowest
@ [src/pokemon.c:3250]. GetBoxMonData decrypts the Pokemon in place and encrypts it again
@ [src/pokemon.c:2992, 3327], so the call is made only in a frame where the main loop is parked in
@ WaitForVBlank (gMain.intrCheck bit 0 clear, read before VBlankIntr) and only in the overworld.
@ The nature is personality % 25 [src/pokemon.c, GetNatureFromPersonality]; 0x10000 % 25 is 11.
@
@ State at p_words: +0 the first row, +4 the second, +8 frames the IVs were read.

    .thumb
    .align 2
    .set    OVERLAY_TWO_ROWS, 1
    .global ivs_hook
ivs_hook:
    push    {r4, r5, r6, r7, lr}
    ldr     r0, p_intr_check
    ldrh    r4, [r0]                @ bit 0 clear: the main loop is idle
    bl      .Loverlay_oam
    ldr     r3, p_original
    bl      .Lcall                  @ the game's VBlankIntr
    bl      .Loverlay_tiles
    mov     r0, #1
    tst     r4, r0
    bne     .Lout                   @ a lag frame: the main loop may be inside the party
    ldr     r0, p_gmain
    ldr     r0, [r0, #4]
    ldr     r1, p_cb2_overworld
    cmp     r0, r1
    bne     .Lout
    ldr     r0, p_mon
    mov     r1, #66                 @ MON_DATA_IVS
    mov     r2, #0
    ldr     r3, p_get_mon_data
    bl      .Lcall
    mov     r4, r0                  @ the six IVs
    ldr     r5, p_words
    mov     r7, #0
    mov     r6, #6
.Liv:
    mov     r0, #31
    and     r0, r4
    lsr     r4, r4, #5
    bl      .Lbcd2
    lsl     r7, r7, #8
    orr     r7, r0
    sub     r6, #1
    cmp     r6, #2
    bne     .Liv_next
    str     r7, [r5]                @ HP, Attack, Defense, Speed
    mov     r7, #0
.Liv_next:
    cmp     r6, #0
    bne     .Liv
    ldr     r0, p_mon
    ldrh    r1, [r0]                @ personality, low half
    ldrh    r0, [r0, #2]            @ high half
    mov     r2, #11
    mul     r0, r2
    add     r0, r1
    bl      .Lmod25
    bl      .Lbcd2
    lsl     r7, r7, #8
    orr     r7, r0
    lsl     r7, r7, #8
    str     r7, [r5, #4]            @ Sp. Atk, Sp. Def, nature
    ldr     r0, [r5, #8]
    add     r0, #1
    str     r0, [r5, #8]
.Lout:
    pop     {r4, r5, r6, r7}
    pop     {r0}
    bx      r0

@ r0 (below 100) -> two BCD digits. Clobbers r1.
.Lbcd2:
    mov     r1, #0
.Lbcd2_loop:
    cmp     r0, #10
    blo     .Lbcd2_done
    sub     r0, #10
    add     r1, #1
    b       .Lbcd2_loop
.Lbcd2_done:
    lsl     r1, r1, #4
    orr     r0, r1
    bx      lr

@ r0 = r0 % 25 for r0 below 819200. Clobbers r2, r3.
.Lmod25:
    ldr     r3, .Lrecip25
    mul     r3, r0
    lsr     r3, r3, #17             @ at most 6 under the quotient
    mov     r2, #25
    mul     r3, r2
    sub     r0, r0, r3
.Lmod_loop:
    cmp     r0, #25
    blo     .Lmod_done
    sub     r0, #25
    b       .Lmod_loop
.Lmod_done:
    bx      lr

    .include "overlay.inc"

.Lcall:
    bx      r3

    .align 2
.Lrecip25:
    .word   5242                    @ 2^17 / 25, rounded down

    .align 2
    .global p_original, p_intr_check, p_gmain, p_cb2_overworld, p_mon, p_get_mon_data, p_words
    .global p_overlay, p_overlay2, p_overlay_tiles, p_overlay_pal, p_overlay_oam
p_original:
    .word   0x0800071D              @ patched by the installer: the handler this one replaced
p_intr_check:
    .word   0x030022EC              @ &gMain.intrCheck (French FireRed)
p_gmain:
    .word   0x030022D0              @ gMain (French FireRed)
p_cb2_overworld:
    .word   0x08059EC9              @ CB2_Overworld, THUMB
p_mon:
    .word   0x02024280              @ patched: gPlayerParty[0] (French FireRed)
p_get_mon_data:
    .word   0x080432E5              @ GetMonData, THUMB (French FireRed)
p_words:
    .word   0x0203FF80              @ patched: 12 bytes of state
p_overlay:
    .word   0x0203FF80              @ patched: the first row, p_words
p_overlay2:
    .word   0x0203FF84              @ patched: the second row, p_words + 4
p_overlay_tiles:
    .word   0x06017E00              @ OBJ tile 1008
p_overlay_pal:
    .word   0x020379D6              @ gPlttBufferFaded (0x020375F4) + OBJ palette 15 colour 1
p_overlay_oam:
    .word   0x030026C8              @ gMain.oamBuffer[120] (gMain + 0x38 + 120 * 8)

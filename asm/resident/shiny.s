@ A resident V-blank hook for shiny hunting: a countdown to the next shiny wild Pokemon, drawn over the
@ overworld, and slow motion while R is held so the player can act on the right frame.
@
@ THE MODEL. VBlankIntr calls Random once a frame [src/main.c:412]. A wild Pokemon rolls its nature
@ with Random() % 25, then draws personality = Random() | Random() << 16 until the nature matches
@ [src/wild_encounter.c:233, src/pokemon.c:1864]; p_method 1 takes the first pair as it is (a scripted
@ CreateMon). It is shiny when TID ^ SID ^ high ^ low < 8.
@
@ THE COUNT. The hook follows gRngValue from frame to frame (at most 64 steps, else it starts over)
@ and gives it an index. A search cursor walks ahead of it, p_search candidates per idle frame; the
@ first candidate whose next call rolls a shiny is the target. The overlay shows the target's nature
@ as two decimal digits and target - current - p_offset as six, or FF and how far the search has
@ looked. p_offset 4 is a grass encounter: from the seed read one frame before the encounter frame,
@ the nature roll is call 5.
@
@ SLOW MOTION. While every button in p_slow is held, the hook waits out p_slow_frames more V-blanks
@ after the game's VBlankIntr. VCount stays enabled inside a handler [src/crt0.s, jump_intr], so
@ m4aSoundVSync still runs at line 150; the hook calls m4aSoundMain once per V-blank it waits, the way
@ VBlankIntr does, and clears the V-blank it waited out in REG_IF so it is not taken again at once.
@ p_help is stored 1 every frame: gHelpSystemToggleWithRButtonDisabled, so R does not open Help.
@
@ Calibrating p_offset for another kind of encounter is the turbo hook's ring (ring=, and
@ scratchpad/emu/rng_ring_read.py): this hook has no room for it.
@
@ State at p_state: +0 seed followed, +4 its index, +8 search seed, +12 its index, +16 target index,
@ +20 target nature + 1 (0 none), +24 the word shown, +28 frames, +32 candidates tried.

    .thumb
    .align 2
    .global shiny_hook
shiny_hook:
    push    {r4, r5, r6, r7, lr}
    ldr     r0, p_intr_check
    ldrh    r0, [r0]
    push    {r0}                    @ bit 0 clear: the main loop is idle
    ldr     r7, p_state
    ldr     r1, [r7, #28]
    add     r1, #1
    str     r1, [r7, #28]
    ldr     r0, p_help
    cmp     r0, #0
    beq     .Lhelp_done
    mov     r1, #1
    strb    r1, [r0]
.Lhelp_done:
    bl      .Loverlay_oam
    ldr     r3, p_original
    bl      .Lcall                  @ the game's VBlankIntr
    bl      .Loverlay_tiles
    ldr     r7, p_state
    bl      .Ltrack
    bl      .Ltarget
    pop     {r0}
    mov     r1, #1
    tst     r0, r1
    bne     .Lsearched              @ a lag frame: no search
    bl      .Lsearch
.Lsearched:
    bl      .Lshow
    bl      .Lslow
    pop     {r4, r5, r6, r7}
    pop     {r0}
    bx      r0

@ Follow gRngValue: step the kept seed until it matches, or start over.
.Ltrack:
    push    {lr}
    ldr     r0, p_rng
    ldr     r0, [r0]
    ldr     r1, [r7]
    ldr     r2, [r7, #4]
    mov     r4, #64
.Ltr_loop:
    cmp     r1, r0
    beq     .Ltr_found
    bl      .Ladv
    add     r2, #1
    sub     r4, #1
    bne     .Ltr_loop
    str     r0, [r7]                @ lost it (a battle, a reseed): count from here
    mov     r2, #0
    str     r2, [r7, #4]
    str     r0, [r7, #8]
    str     r2, [r7, #12]
    str     r2, [r7, #20]
    b       .Ltr_done
.Ltr_found:
    str     r1, [r7]
    str     r2, [r7, #4]
.Ltr_done:
    pop     {r0}
    bx      r0

@ Drop a target already passed; keep the search cursor at or ahead of the seed followed.
.Ltarget:
    push    {lr}
    ldr     r0, [r7, #20]
    cmp     r0, #0
    beq     .Ltg_cursor
    ldr     r0, [r7, #16]
    ldr     r1, [r7, #4]
    sub     r0, r0, r1
    ldr     r1, p_offset
    cmp     r0, r1
    bge     .Ltg_done               @ still ahead
    mov     r0, #0
    str     r0, [r7, #20]
    ldr     r1, [r7, #8]
    bl      .Ladv
    str     r1, [r7, #8]
    ldr     r0, [r7, #12]
    add     r0, #1
    str     r0, [r7, #12]
.Ltg_cursor:
    ldr     r0, [r7, #12]
    ldr     r1, [r7, #4]
    cmp     r0, r1
    bge     .Ltg_done
    str     r1, [r7, #12]
    ldr     r0, [r7]
    str     r0, [r7, #8]
.Ltg_done:
    pop     {r0}
    bx      r0

@ Try p_search candidates. r4 nature, r5 TID ^ SID, r6 candidates left.
.Lsearch:
    push    {lr}
    ldr     r0, [r7, #20]
    cmp     r0, #0
    bne     .Lse_done               @ a target is held
    ldr     r0, p_sb2ptr
    ldr     r0, [r0]
    ldrh    r5, [r0, #0x0A]         @ TID
    ldrh    r1, [r0, #0x0C]         @ SID
    eor     r5, r1
    ldr     r6, p_search
.Lse_cand:
    ldr     r1, [r7, #8]
    ldr     r0, p_method
    cmp     r0, #0
    bne     .Lse_pair_once
    bl      .Ladv
    lsr     r0, r1, #16
    bl      .Lmod25
    mov     r4, r0                  @ the nature rolled
.Lse_pair:
    bl      .Lpair
    cmp     r0, r4
    bne     .Lse_pair
    b       .Lse_check
.Lse_pair_once:
    bl      .Lpair
    mov     r4, r0
.Lse_check:
    ldr     r0, [r7, #32]
    add     r0, #1
    str     r0, [r7, #32]
    eor     r2, r5
    cmp     r2, #8
    bhs     .Lse_next
    add     r4, #1
    str     r4, [r7, #20]           @ a shiny: nature + 1
    ldr     r0, [r7, #12]
    str     r0, [r7, #16]
    b       .Lse_done
.Lse_next:
    ldr     r1, [r7, #8]
    bl      .Ladv
    str     r1, [r7, #8]
    ldr     r0, [r7, #12]
    add     r0, #1
    str     r0, [r7, #12]
    sub     r6, #1
    bne     .Lse_cand
.Lse_done:
    pop     {r0}
    bx      r0

@ One personality from r1: r1 advanced twice, r0 = personality % 25, r2 = high ^ low.
.Lpair:
    push    {lr}
    bl      .Ladv
    lsr     r2, r1, #16             @ low
    bl      .Ladv
    lsr     r0, r1, #16             @ high
    mov     r3, #11
    mul     r3, r0                  @ 0x10000 % 25 == 11
    add     r3, r2
    eor     r2, r0
    push    {r2}
    mov     r0, r3
    bl      .Lmod25
    pop     {r2}
    pop     {r3}
    bx      r3

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

@ r1 = the next seed. Clobbers r3.
.Ladv:
    ldr     r3, .Lmult
    mul     r1, r3
    ldr     r3, .Linc
    add     r1, r3
    bx      lr

@ The word shown: nature and countdown, or FF and how far the search has looked, in BCD.
.Lshow:
    push    {lr}
    mov     r2, #0
    ldr     r0, [r7, #20]
    cmp     r0, #0
    beq     .Lsh_search
    sub     r0, #1
    adr     r3, .Lpow10 + 16
    mov     r6, #2
    bl      .Lbcd
    ldr     r0, [r7, #16]
    ldr     r1, [r7, #4]
    sub     r0, r0, r1
    ldr     r1, p_offset
    sub     r0, r0, r1
    bpl     .Lsh_count
    mov     r0, #0                  @ found inside the offset after a restart: dropped next frame
    b       .Lsh_count
.Lsh_search:
    mov     r2, #0xFF
    ldr     r0, [r7, #12]
    ldr     r1, [r7, #4]
    sub     r0, r0, r1
.Lsh_count:
    adr     r3, .Lpow10
    mov     r6, #6
    bl      .Lbcd
    str     r2, [r7, #24]
    pop     {r0}
    bx      r0

@ Append r6 decimal digits of r0 to r2, from the power of ten at r3. Clobbers r0, r1, r3, r4, r6.
.Lbcd:
    ldr     r1, [r3]
    mov     r4, #0
.Lbcd_sub:
    cmp     r0, r1
    blo     .Lbcd_digit
    sub     r0, r0, r1
    add     r4, #1
    b       .Lbcd_sub
.Lbcd_digit:
    lsl     r2, r2, #4
    orr     r2, r4
    add     r3, #4
    sub     r6, #1
    bne     .Lbcd
    bx      lr

@ Slow motion: wait out p_slow_frames more V-blanks, mixing the sound for each.
.Lslow:
    push    {lr}
    ldr     r1, p_slow
    cmp     r1, #0
    beq     .Lsl_done
    ldr     r0, p_gmain
    ldrh    r0, [r0, #0x2C]         @ heldKeys
    and     r0, r1
    cmp     r0, r1
    bne     .Lsl_done
    ldr     r4, p_slow_frames
    ldr     r5, p_vcount
.Lsl_frame:
    cmp     r4, #0
    beq     .Lsl_ack
.Lsl_leave:
    ldrh    r0, [r5]
    cmp     r0, #160
    bhs     .Lsl_leave              @ out of this V-blank
.Lsl_enter:
    ldrh    r0, [r5]
    cmp     r0, #160
    blo     .Lsl_enter              @ into the next
    ldr     r0, p_sound_info
    ldrb    r0, [r0, #4]            @ gSoundInfo.pcmDmaCounter
    ldr     r1, p_pcm_counter
    strb    r0, [r1]
    ldr     r3, p_sound_main
    bl      .Lcall
    sub     r4, #1
    b       .Lsl_frame
.Lsl_ack:
    ldr     r0, p_reg_if
    mov     r1, #1
    strh    r1, [r0]                @ the V-blank waited out is not taken again
.Lsl_done:
    pop     {r0}
    bx      r0

    .include "overlay.inc"

.Lcall:
    bx      r3

    .align 2
.Lmult:
    .word   0x41C64E6D
.Linc:
    .word   0x00006073
.Lrecip25:
    .word   5242                    @ 2^17 / 25, rounded down
.Lpow10:
    .word   100000, 10000, 1000, 100, 10, 1

    .align 2
    .global p_original, p_intr_check, p_gmain, p_cb2_overworld, p_state, p_rng, p_sb2ptr
    .global p_method, p_offset, p_search, p_slow, p_slow_frames, p_help, p_vcount
    .global p_sound_main, p_pcm_counter, p_sound_info, p_reg_if
    .global p_overlay, p_overlay_tiles, p_overlay_pal, p_overlay_oam
p_original:
    .word   0x0800071D              @ patched by the installer: the handler this one replaced
p_intr_check:
    .word   0x030022EC              @ &gMain.intrCheck (French FireRed)
p_gmain:
    .word   0x030022D0              @ gMain (French FireRed)
p_cb2_overworld:
    .word   0x08059EC9              @ CB2_Overworld, THUMB
p_state:
    .word   0x0203FF80              @ patched: 36 bytes of state
p_rng:
    .word   0x03004220              @ gRngValue
p_sb2ptr:
    .word   0x0300422C              @ gSaveBlock2Ptr; TID at +0x0A, SID at +0x0C
p_method:
    .word   0                       @ patched: 0 a wild nature roll, 1 a scripted CreateMon
p_offset:
    .word   4                       @ patched: calls from the shown seed to the one before the roll
p_search:
    .word   16                      @ patched: candidates tried per idle frame
p_slow:
    .word   0x100                   @ patched: buttons held for slow motion (R), 0 for none
p_slow_frames:
    .word   3                       @ patched: V-blanks waited out per game frame
p_help:
    .word   0x0203F171              @ patched: gHelpSystemToggleWithRButtonDisabled, 0 for none
p_vcount:
    .word   0x04000006              @ REG_VCOUNT
p_sound_main:
    .word   0x081DF53D              @ m4aSoundMain, THUMB (VBlankIntr's call at 0x08000772)
p_pcm_counter:
    .word   0x03002F68              @ gPcmDmaCounter (VBlankIntr's literal)
p_sound_info:
    .word   0x03005F80              @ gSoundInfo (VBlankIntr's literal)
p_reg_if:
    .word   0x04000202              @ REG_IF
p_overlay:
    .word   0x0203FF98              @ patched: the word shown, p_state + 24
p_overlay_tiles:
    .word   0x06017E00              @ OBJ tile 1008
p_overlay_pal:
    .word   0x020379D6              @ gPlttBufferFaded (0x020375F4) + OBJ palette 15 colour 1
p_overlay_oam:
    .word   0x030026C8              @ gMain.oamBuffer[120] (gMain + 0x38 + 120 * 8)

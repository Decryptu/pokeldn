@ A resident V-blank hook that speeds the game up. After the game's own VBlankIntr, in a frame
@ where the main loop is idle, it runs the overworld's two callbacks p_field more times, the
@ battle's two callbacks p_battle more times, and RunTextPrinters p_extra more times: the field and
@ battles at 1 + N speed and a printer at the fast option drawing 1 + p_extra glyphs a frame
@ [decomp:src/text.c:629 RenderText, src/text_printer.c:115].
@
@ A CALLBACK PASS runs only while gMain.callback1 and callback2 are exactly the pair it is for
@ (CB1_Overworld and CB2_Overworld, or BattleMainCB1 and BattleMainCB2), checked again between the two
@ calls, so a warp or a battle CB1 starts is not followed by the old CB2. newKeys and
@ newAndRepeatedKeys are cleared first, so a press the frame already handled is not handled twice;
@ heldKeys stays, so walking continues [src/overworld.c:1449, src/battle_main.c:1447].
@
@ A LINE BUDGET, when p_budget is non-zero: a pass starts only if the scanlines since V-blank plus twice
@ the last pass's cost (this pass, then the game's own frame) fit in p_budget; 228 is one whole frame.
@ Fixed passes past what a frame holds make lag frames: three a frame lagged one frame in four. A
@ held-back frame shrinks the kept cost by an eighth: one 101-line pass kept as it was stopped every pass.
@
@ HELD TO FAST-FORWARD, when p_hold is a button mask: a callback pass runs only while gMain.heldKeys
@ holds every button in it; the text extras run either way. p_help names a byte stored 1 every frame:
@ gHelpSystemToggleWithRButtonDisabled, so holding R does not open the Help System
@ [src/help_system_util.c:50].
@
@ NO CALLBACK PASS DURING A PALETTE FADE. A hardware fade ends only when UpdatePaletteFade sets the
@ one-bit hardwareFadeFinishing and the next V-blank's TransferPlttBuffer sees it [src/palette.c:701,
@ 743]. A second UpdatePaletteFade in the same frame increments that bit back to 0, every frame, and
@ the fade never ends: closing the battle bag left CompleteWhenChoseItem waiting for it forever. So a
@ pass is skipped while gPaletteFade.active is set.
@
@ ONLY WHEN THE MAIN LOOP IS IDLE. WaitForVBlank clears INTR_FLAG_VBLANK in gMain.intrCheck and spins
@ until VBlankIntr sets it again [src/main.c:462]. Read before VBlankIntr runs, a clear bit means the
@ main loop is parked in that spin, so the extra work cannot interleave with its own; a set bit is a
@ lag frame and the frame runs as the game wrote it.
@
@ ONLY PRINTERS THE GAME HAS STARTED. A field message adds its printer before its box is drawn and
@ runs it only once the box task reaches its print state [src/field_message_box.c:44]; printing
@ earlier draws glyphs the box then erases (the speaker's name, the start of the line). A printer
@ still at its origin (currentX == x and currentY == y) has not been run by the game, so any such
@ active printer skips the extra text calls for that frame.
@
@ THE OVERLAY, when p_overlay names an address, shows the word there as eight hex digits in the
@ top-right corner, in the overworld only. The entries go into gMain.oamBuffer[120..127] and the two
@ colours into gPlttBufferFaded and gPlttBufferUnfaded BEFORE VBlankIntr, whose LoadOam and
@ TransferPlttBuffer copy them at the start of V-blank with the game's own. Written to OAM after
@ VBlankIntr instead, they landed once the screen had started drawing and the top rows of the digits
@ showed the previous frame. The digits are the 1bpp font below expanded into OBJ tiles 1008..1023
@ after VBlankIntr, drawn with OBJ palette 15: whatever the game keeps there is overwritten.
@
@ IntrMain enters in SYS mode with lr = intr_return [crt0.s]; lr is pushed and returned through.

    .thumb
    .align 2
    .global turbo_hook
turbo_hook:
    push    {r4, r5, lr}
    ldr     r0, p_intr_check
    ldrh    r4, [r0]                @ bit 0 clear: the main loop is waiting for V-blank
    ldr     r0, p_frames
    ldr     r1, [r0]
    add     r1, #1
    str     r1, [r0]
    ldr     r0, p_help
    cmp     r0, #0
    beq     .Lhelp_done
    mov     r1, #1
    strb    r1, [r0]                @ R stays off the Help System
.Lhelp_done:
.ifndef TURBO_LITE
    bl      .Lring
    bl      .Loverlay_oam           @ into the game's buffers, before it copies them
.endif
    ldr     r3, p_original
    bl      .Lcall                  @ the game's VBlankIntr, unchanged
.ifndef TURBO_LITE
    bl      .Loverlay_tiles
.endif
    mov     r0, #1
    tst     r4, r0
    bne     .Lout                   @ a lag frame: leave the game alone

    ldr     r4, p_field
    adr     r5, p_cb1_overworld
    bl      .Lpasses
    ldr     r4, p_battle
    adr     r5, p_cb1_battle
    bl      .Lpasses

    ldr     r0, p_printers          @ sTextPrinters, 32 of 0x24 bytes
    mov     r1, #32
.Lscan:
    ldrb    r2, [r0, #0x1B]         @ active
    cmp     r2, #0
    beq     .Lnext
    ldrb    r2, [r0, #6]            @ x
    ldrb    r3, [r0, #8]            @ currentX
    cmp     r2, r3
    bne     .Lnext
    ldrb    r2, [r0, #7]            @ y
    ldrb    r3, [r0, #9]            @ currentY
    cmp     r2, r3
    beq     .Lout                   @ not started by the game yet: leave every printer alone
.Lnext:
    add     r0, #0x24
    sub     r1, #1
    bne     .Lscan
    ldr     r0, p_frames
    ldr     r1, [r0, #4]
    add     r1, #1
    str     r1, [r0, #4]            @ frames that ran the extra printers
    ldr     r4, p_extra
.Lloop:
    cmp     r4, #0
    beq     .Lout
    ldr     r3, p_run_text
    bl      .Lcall
    sub     r4, #1
    b       .Lloop
.Lout:
    pop     {r4, r5}
    pop     {r0}
    bx      r0

@ r4 passes, r5 = &{cb1, cb2}. None unless p_hold is 0 or all held. Each pass: both callbacks still
@ the pair, presses cleared, CB1, the pair checked again, CB2.
.Lpasses:
    push    {lr}
    ldr     r1, p_hold
    cmp     r1, #0
    beq     .Lpass
    ldr     r0, p_gmain
    ldrh    r0, [r0, #0x2C]         @ heldKeys
    and     r0, r1
    cmp     r0, r1
    bne     .Lpassed                @ the fast-forward buttons are not all held
.Lpass:
    cmp     r4, #0
    beq     .Lpassed
    ldr     r0, p_gmain
    ldr     r1, [r0, #4]            @ callback2
    ldr     r2, [r5, #4]
    cmp     r1, r2
    bne     .Lpassed
    ldr     r1, [r0]                @ callback1
    ldr     r2, [r5]
    cmp     r1, r2
    bne     .Lpassed
    ldr     r1, p_palette_fade
    ldrh    r1, [r1, #6]            @ blendColor:15, active:1
    lsr     r1, r1, #15
    bne     .Lpassed                @ a fade is running: leave it to the game's own pace
    bl      .Lline
    ldr     r1, p_budget
    cmp     r1, #0
    beq     .Lgo
    ldr     r2, p_frames
    ldr     r2, [r2, #12]           @ the last pass's cost in lines
    lsl     r3, r2, #1
    add     r3, r0
    cmp     r3, r1
    bls     .Lgo
    ldr     r0, p_frames            @ no room for this pass and the game's own frame after it
    ldr     r1, [r0, #16]
    add     r1, #1
    str     r1, [r0, #16]           @ passes the budget held back
    lsr     r1, r2, #3
    add     r1, #1
    sub     r2, r2, r1
    bpl     .Ldecayed
    mov     r2, #0
.Ldecayed:
    str     r2, [r0, #12]           @ the cost shrinks by an eighth, so one slow pass cannot latch
    b       .Lpassed
.Lgo:
    push    {r0}                    @ the line this pass starts on
    ldr     r0, p_gmain
    mov     r1, #0
    strh    r1, [r0, #0x2E]         @ newKeys: already handled this frame
    strh    r1, [r0, #0x30]         @ newAndRepeatedKeys
    ldr     r3, [r5]
    bl      .Lcall                  @ CB1
    ldr     r0, p_gmain
    ldr     r1, [r0, #4]
    ldr     r3, [r5, #4]
    cmp     r1, r3
    bne     .Lpass_left             @ CB1 left this state (a warp, a battle, its end): stop here
    bl      .Lcall                  @ CB2
    bl      .Lline
    pop     {r1}
    sub     r0, r0, r1
    bpl     .Lcost
    add     r0, #228
.Lcost:
    ldr     r2, p_frames
    str     r0, [r2, #12]           @ this pass's cost in lines
    ldr     r1, [r2, #8]
    add     r1, #1
    str     r1, [r2, #8]            @ extra callback passes run
    sub     r4, #1
    b       .Lpass
.Lpass_left:
    add     sp, #4
.Lpassed:
    pop     {r0}
    bx      r0

.ifndef TURBO_LITE
    .include "overlay.inc"
.endif

.Lcall:
    bx      r3

.ifndef TURBO_LITE
@ The RNG history, when p_ring names one: {state, watched at arming, frames, seeds[32]}. Each frame
@ keeps gRngValue as VBlankIntr finds it, until the word at p_watch changes; state 2 is frozen.
.Lring:
    ldr     r0, p_ring
    cmp     r0, #0
    beq     .Lring_done
    ldr     r1, p_watch
    ldr     r1, [r1]
    ldr     r2, [r0]
    cmp     r2, #0
    bne     .Lring_armed
    str     r1, [r0, #4]            @ the value that counts as unchanged
    mov     r2, #1
    str     r2, [r0]
.Lring_armed:
    cmp     r2, #1
    bne     .Lring_done             @ frozen
    ldr     r3, [r0, #8]
    add     r2, r3, #1
    str     r2, [r0, #8]
    lsl     r3, r3, #27
    lsr     r3, r3, #25             @ (frame & 31) * 4
    add     r3, r0
    ldr     r2, p_rng
    ldr     r2, [r2]
    str     r2, [r3, #12]
    ldr     r2, [r0, #4]
    cmp     r1, r2
    beq     .Lring_done
    mov     r2, #2
    str     r2, [r0]                @ the watched word changed: keep this history
.Lring_done:
    bx      lr
.endif

@ -> r0 = scanlines since V-blank began: REG_VCOUNT runs 0..227 and V-blank starts at 160.
.Lline:
    ldr     r0, p_vcount
    ldrh    r0, [r0]
    sub     r0, #160
    bpl     .Lline_done
    add     r0, #228
.Lline_done:
    bx      lr

    .align 2
    .global p_original, p_intr_check, p_run_text, p_extra, p_frames, p_printers
    .global p_field, p_battle, p_gmain, p_cb1_overworld, p_cb2_overworld, p_cb1_battle, p_cb2_battle
    .global p_palette_fade, p_hold, p_help, p_budget, p_vcount
.ifndef TURBO_LITE
    .global p_overlay, p_overlay_tiles, p_overlay_pal, p_overlay_oam, p_ring, p_watch, p_rng
.endif
p_original:
    .word   0x0800071D              @ patched by the installer: the handler this one replaced
p_intr_check:
    .word   0x030022EC              @ &gMain.intrCheck (gMain 0x030022D0 + 0x1C, French FireRed)
p_run_text:
    .word   0x08002D51              @ RunTextPrinters, THUMB (French FireRed)
p_extra:
    .word   4                       @ patched: extra RunTextPrinters calls per idle frame
p_frames:
    .word   0x0203FF60              @ patched: counters: frames, text-extra frames, passes, last pass cost, held back
p_printers:
    .word   0x02020034              @ sTextPrinters (French FireRed, RunTextPrinters' literal)
p_field:
    .word   0                       @ patched: extra overworld passes per idle frame
p_battle:
    .word   0                       @ patched: extra battle passes per idle frame
p_gmain:
    .word   0x030022D0              @ gMain (French FireRed)
p_cb1_overworld:
    .word   0x08059E49              @ CB1_Overworld, THUMB (CB1_Overworld's own literal)
p_cb2_overworld:
    .word   0x08059EC9              @ CB2_Overworld, THUMB
p_cb1_battle:
    .word   0x08015B6D              @ BattleMainCB1, THUMB (the battle init's store at 0x08013FDE)
p_cb2_battle:
    .word   0x08014889              @ BattleMainCB2, THUMB
p_palette_fade:
    .word   0x02037AB4              @ gPaletteFade (French FireRed, CB2_Overworld's literal)
.ifndef TURBO_LITE
p_overlay:
    .word   0                       @ patched: the address whose word is shown, 0 for no overlay
p_overlay_tiles:
    .word   0x06017E00              @ OBJ tile 1008
p_overlay_pal:
    .word   0x020379D6              @ gPlttBufferFaded (0x020375F4) + OBJ palette 15 colour 1
p_overlay_oam:
    .word   0x030026C8              @ gMain.oamBuffer[120] (gMain + 0x38 + 120 * 8)
.endif
p_hold:
    .word   0                       @ patched: buttons held to run the passes (R 0x100), 0 for always
p_help:
    .word   0                       @ patched: byte kept 1 every frame, 0 for none
p_budget:
    .word   0                       @ patched: scanlines a frame's passes and the game may use, 0 for off
p_vcount:
    .word   0x04000006              @ REG_VCOUNT
.ifndef TURBO_LITE
p_ring:
    .word   0                       @ patched: the RNG history, 140 bytes (0x0203FF74 ends at EWRAM's top), 0 for none
p_watch:
    .word   0x02024028              @ patched: gEnemyParty[0].personality (French FireRed)
p_rng:
    .word   0x03004220              @ gRngValue
.endif

@ A read-only FireRed/LeafGreen RNG assistant.
@
@ The hook follows gRngValue after the game's VBlankIntr and exposes the tracked seed/index on the
@ existing hexadecimal overlay.  It never stores to gRngValue or to any Pokemon/save field.  When
@ p_auto_a is enabled and the tracked index reaches p_trigger_index while the normal overworld
@ callback pair is active, the VBlank hook records the hit and replaces callback1 with the small
@ input shim below.  ReadKeys runs before that callback on the next main-loop pass, so the shim can
@ OR A into newKeys/newAndRepeatedKeys without an extra callback pass or a VBlank-time key that
@ ReadKeys would immediately overwrite.
@
@ State at p_state (64 bytes):
@   +0x00 current_seed             +0x04 current_index
@   +0x08 predicted_generation_seed +0x0C predicted_generation_index
@   +0x10 trigger_seed              +0x14 trigger_index
@   +0x18 hit_seed                  +0x1C hit_index
@   +0x20 hit_frame                 +0x24 frame_counter
@   +0x28 target_pid                +0x2C target_nature
@   +0x30 candidates_tested         +0x34 flags
@   +0x38 mode                      +0x3C display_bottom
@
@ Flags are intentionally simple and stable for host-side inspection:
@   bit 0 initialized, bit 1 pending A, bit 2 fired, bit 3 hit locked,
@   bit 4 armed, bit 5 target found (reserved), bit 6 trigger missed.

    .thumb
    .align 2
    .set    FLAG_INITIALIZED, 1
    .set    FLAG_PENDING_A,   2
    .set    FLAG_FIRED,       4
    .set    FLAG_HIT_LOCKED,  8
    .set    FLAG_ARMED,       16
    .set    FLAG_TARGET_FOUND,32
    .set    FLAG_MISSED,      64
    .set    OVERLAY_TWO_ROWS, 1

    .global rng_assist_hook, rng_assist_input_shim
rng_assist_hook:
    push    {r4, r5, r6, r7, lr}
    ldr     r6, p_intr_check
    ldrh    r6, [r6]                @ capture before the game's VBlankIntr
    ldr     r7, p_state
    ldr     r0, [r7, #0x24]
    add     r0, #1
    str     r0, [r7, #0x24]       @ frame_counter

    bl      .Loverlay_oam         @ OAM must be ready before the game's VBlankIntr
    ldr     r3, p_original
    bl      .Lcall                 @ leave the game's interrupt handler unchanged
    bl      .Loverlay_tiles

    ldr     r7, p_state
    bl      .Ltrack
    bl      .Lmaybe_arm
    bl      .Lshow
    pop     {r4, r5, r6, r7}
    pop     {r0}
    bx      r0

@ Follow the live LCG state.  A reseed or an unexpectedly large jump restarts the index at zero.
.Ltrack:
    push    {r4, r5, lr}
    ldr     r0, p_rng
    ldr     r0, [r0]               @ read-only: gRngValue
    ldr     r1, [r7]
    ldr     r2, [r7, #4]
    ldr     r3, [r7, #0x34]
    mov     r4, #FLAG_INITIALIZED
    tst     r3, r4
    bne     .Ltrack_find

    str     r0, [r7]
    mov     r1, #0
    str     r1, [r7, #4]
    str     r1, [r7, #8]
    str     r1, [r7, #0x0C]
    str     r1, [r7, #0x10]        @ no trigger seed until the trigger is reached
    str     r1, [r7, #0x18]        @ no hit seed
    str     r1, [r7, #0x1C]
    str     r1, [r7, #0x20]
    str     r1, [r7, #0x30]
    ldr     r1, p_trigger_index
    str     r1, [r7, #0x14]
    ldr     r1, p_target_pid
    str     r1, [r7, #0x28]
    ldr     r1, p_target_nature
    str     r1, [r7, #0x2C]
    ldr     r1, p_mode
    str     r1, [r7, #0x38]
    mov     r1, #FLAG_INITIALIZED
    str     r1, [r7, #0x34]
    b       .Ltrack_done

.Ltrack_find:
    mov     r4, #64
.Ltrack_loop:
    cmp     r1, r0
    beq     .Ltrack_found
    bl      .Lstep
    add     r2, #1
    sub     r4, #1
    bne     .Ltrack_loop

    @ The game reseeded or consumed more than the bounded search window.
    str     r0, [r7]
    mov     r1, #0
    str     r1, [r7, #4]
    str     r1, [r7, #8]
    str     r1, [r7, #0x0C]
    str     r1, [r7, #0x10]
    str     r1, [r7, #0x18]
    str     r1, [r7, #0x1C]
    str     r1, [r7, #0x20]
    str     r1, [r7, #0x30]
    mov     r1, #FLAG_INITIALIZED
    str     r1, [r7, #0x34]
    b       .Ltrack_done

.Ltrack_found:
    str     r1, [r7]
    str     r2, [r7, #4]
.Ltrack_done:
    pop     {r4, r5}
    pop     {r0}
    bx      r0

@ Reserve A only on the exact calibrated index.  A late frame is marked as missed and never presses.
.Lmaybe_arm:
    push    {r4, r5, r6, lr}
    ldr     r0, p_auto_a
    cmp     r0, #0
    beq     .Larm_done
    ldr     r0, [r7, #0x34]
    mov     r1, #(FLAG_PENDING_A | FLAG_FIRED | FLAG_HIT_LOCKED | FLAG_ARMED)
    tst     r0, r1
    bne     .Larm_done
    ldr     r1, [r7, #4]
    ldr     r2, [r7, #0x14]
    cmp     r1, r2
    beq     .Larm_at_trigger
    blo     .Larm_done
    mov     r1, #FLAG_MISSED
    orr     r0, r1
    str     r0, [r7, #0x34]
    b       .Larm_done

.Larm_at_trigger:
    mov     r1, #1
    tst     r6, r1
    bne     .Larm_done              @ a lag/non-idle frame cannot safely own ReadKeys
    ldr     r4, p_gmain
    ldr     r1, [r4]
    ldr     r2, p_cb1_overworld
    cmp     r1, r2
    bne     .Larm_done
    ldr     r1, [r4, #4]
    ldr     r2, p_cb2_overworld
    cmp     r1, r2
    bne     .Larm_done

    @ A calibrated offset above 255 would make the VBlank hook unbounded.  Reject it in the
    @ resident image as well as in the host builder, even if a stale or hand-written payload is run.
    ldr     r5, p_offset
    cmp     r5, #255
    bhi     .Larm_invalid_offset

    ldr     r1, [r7]
    str     r1, [r7, #0x10]        @ trigger_seed
    str     r1, [r7, #0x18]        @ hit_seed
    ldr     r1, [r7, #4]
    str     r1, [r7, #0x1C]        @ hit_index
    str     r1, [r7, #0x0C]        @ predicted_generation_index, before offset
    ldr     r1, [r7, #0x24]
    str     r1, [r7, #0x20]        @ hit_frame
    ldr     r1, [r7]
    str     r1, [r7, #8]            @ predicted_generation_seed, before offset

    @ Convert the calibrated offset from advances into a predicted state.  The bounded parameter
    @ keeps interrupt latency deterministic; host-side validation rejects values above 255.
    ldr     r1, [r7, #0x0C]
    add     r1, r5
    str     r1, [r7, #0x0C]
    ldr     r1, [r7, #8]
.Lpredict_loop:
    cmp     r5, #0
    beq     .Lpredict_done
    bl      .Lstep
    sub     r5, #1
    b       .Lpredict_loop
.Lpredict_done:
    str     r1, [r7, #8]

    mov     r1, #(FLAG_INITIALIZED | FLAG_PENDING_A | FLAG_ARMED)
    ldr     r0, [r7, #0x34]
    orr     r0, r1
    str     r0, [r7, #0x34]

    @ The installer patches p_input_shim to this image's address.  Do not use a long-range ADR here:
    @ the shared overlay can move this symbol outside ARMv4T's short ADR range.
    ldr     r0, p_gmain
    ldr     r1, p_input_shim
    add     r1, #1
    str     r1, [r0]                @ callback1 = shim; callback2 remains untouched
.Larm_done:
    pop     {r4, r5, r6}
    pop     {r0}
    bx      r0

.Larm_invalid_offset:
    ldr     r0, [r7, #0x34]
    mov     r1, #FLAG_MISSED
    orr     r0, r1
    str     r0, [r7, #0x34]
    b       .Larm_done

@ Inject one A after ReadKeys and run the original overworld callback exactly once.
rng_assist_input_shim:
    push    {r4, r5, lr}
    ldr     r4, p_state
    ldr     r5, p_gmain

    @ The game may have replaced callback1 while this shim was pending.  In that case it owns
    @ the callback again; never call an old overworld callback from the shim.
    ldr     r1, [r5]
    ldr     r2, p_input_shim
    add     r2, #1
    cmp     r1, r2
    bne     .Lshim_abandon
    ldr     r1, [r5, #4]
    ldr     r2, p_cb2_overworld
    cmp     r1, r2
    bne     .Lshim_abort

    ldr     r0, [r4, #0x34]
    mov     r1, #FLAG_PENDING_A
    tst     r0, r1
    beq     .Lshim_restore

    @ The shim is a one-main-loop-pass handoff.  If VBlank has advanced twice before it runs,
    @ abandon it instead of pressing A in a later scene or against a new RNG epoch.
    ldr     r1, [r4, #0x24]
    ldr     r2, [r4, #0x20]
    sub     r1, r2
    cmp     r1, #1
    bhi     .Lshim_abort

    ldrh    r1, [r5, #0x2E]
    mov     r2, #1                 @ A
    orr     r1, r2
    strh    r1, [r5, #0x2E]
    ldrh    r1, [r5, #0x30]
    orr     r1, r2
    strh    r1, [r5, #0x30]

    mov     r1, #FLAG_PENDING_A
    bic     r0, r1
    mov     r1, #(FLAG_FIRED | FLAG_HIT_LOCKED)
    orr     r0, r1
    str     r0, [r4, #0x34]

.Lshim_restore:
    ldr     r1, p_cb1_overworld
    str     r1, [r5]
    ldr     r3, p_cb1_overworld
    bl      .Lcall                 @ ARMv4T has no BLX <register>
    b       .Lshim_return

.Lshim_abort:
    @ A scene change or a reseed invalidates the one-shot.  Restore the known callback without
    @ invoking it in the wrong scene; the next frame can resume normal game dispatch.
    ldr     r0, [r4, #0x34]
    mov     r1, #FLAG_PENDING_A
    bic     r0, r1
    mov     r1, #FLAG_MISSED
    orr     r0, r1
    str     r0, [r4, #0x34]
    ldr     r1, p_cb1_overworld
    str     r1, [r5]

.Lshim_abandon:
    @ callback1 no longer belongs to us, so leave the game's replacement in place.  Clear the
    @ pending request to prevent a stale A from being delivered if the callback is reused later.
    ldr     r0, [r4, #0x34]
    mov     r1, #FLAG_PENDING_A
    bic     r0, r1
    mov     r1, #FLAG_MISSED
    orr     r0, r1
    str     r0, [r4, #0x34]

.Lshim_return:
    pop     {r4, r5}
    pop     {r0}
    bx      r0

@ Display current index until a hit, then freeze the hit frame.  The top row is current_seed via
@ p_overlay; the second row points at display_bottom via p_overlay2.
.Lshow:
    ldr     r0, [r7, #0x34]
    mov     r1, #FLAG_HIT_LOCKED
    tst     r0, r1
    beq     .Lshow_current
    ldr     r0, [r7, #0x20]
    str     r0, [r7, #0x3C]
    bx      lr
.Lshow_current:
    ldr     r0, [r7, #4]
    str     r0, [r7, #0x3C]
    bx      lr

@ r1 = next LCG state.  No caller-visible memory is changed.
.Lstep:
    ldr     r3, .Lmult
    mul     r1, r3
    ldr     r3, .Linc
    add     r1, r3
    bx      lr

    .include "overlay.inc"

.Lcall:
    bx      r3

    .align 2
.Lmult:
    .word   0x41C64E6D
.Linc:
    .word   0x00006073

    .align 2
    .global p_original, p_intr_check, p_state, p_rng, p_gmain, p_cb1_overworld, p_cb2_overworld, p_input_shim
    .global p_auto_a, p_trigger_index, p_offset, p_target_pid, p_target_nature, p_mode
    .global p_overlay, p_overlay2, p_overlay_tiles, p_overlay_pal, p_overlay_oam
p_original:
    .word   0x0800071D              @ patched by the installer: the handler this one replaced
p_intr_check:
    .word   0x030022EC              @ patched: &gMain.intrCheck, sampled before VBlankIntr
p_state:
    .word   0x0203FF80              @ patched: 64 bytes of volatile state
p_rng:
    .word   0x03004220              @ patched: gRngValue
p_gmain:
    .word   0x030022D0              @ patched: gMain
p_cb1_overworld:
    .word   0x08059E49              @ patched: CB1_Overworld, THUMB
p_cb2_overworld:
    .word   0x08059EC9              @ patched: CB2_Overworld, THUMB
p_input_shim:
    .word   0                       @ patched: this image's rng_assist_input_shim, THUMB added above
p_auto_a:
    .word   0                       @ patched: 0 off, non-zero enables the one-shot shim
p_trigger_index:
    .word   0                       @ patched: exact tracked RNG-advance index to arm at
p_offset:
    .word   0                       @ patched: calibrated RNG advances to predicted generation
p_target_pid:
    .word   0                       @ patched/reserved for a future search planner
p_target_nature:
    .word   0                       @ patched/reserved; 0..24 when used by a future planner
p_mode:
    .word   0                       @ patched: host-visible mode value
p_overlay:
    .word   0x0203FF80              @ current_seed
p_overlay2:
    .word   0x0203FFBC              @ display_bottom (state + 0x3C)
p_overlay_tiles:
    .word   0x06017E00              @ OBJ tile 1008
p_overlay_pal:
    .word   0x020379D6              @ gPlttBufferFaded + OBJ palette 15 colour 1
p_overlay_oam:
    .word   0x030026C8              @ gMain.oamBuffer[120]

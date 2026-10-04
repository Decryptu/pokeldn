@ Speed hook: a V-blank handler that, while it is on, runs the overworld and
@ battle callbacks and the text printers extra times per frame, or skips a
@ frame every SLOW_PERIOD frames. With TOGGLE, pressing R switches it on and
@ off, read from the key register at each V-blank so a long frame can't count
@ one press twice; without, only the text printers run extra, all the time.
@
@ `install` copies `resident`..`resident_end` to RESIDENT and points the
@ V-blank interrupt at the copy, keeping the original handler on reinstall.
@
@ Parameters (--defsym): INTR_VBLANK (&gIntrTable[4]), VBLANK_INTR, INTR_CHECK,
@ RUN_TEXT_PRINTERS, TEXT_PRINTERS, MAIN, CB1_OVERWORLD, CB2_OVERWORLD,
@ BATTLE_CB1, BATTLE_CB2, PALETTE_FADE, HELP_R_DISABLE (0 if none), TEXT_EXTRA,
@ OW_EXTRA, BATTLE_EXTRA (extra runs per frame), SLOW_PERIOD (0 for none),
@ TOGGLE and JAPANESE (1 on the Japanese games).

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ STATE, 0x0203FF60              @ frame counters and the swapped callbacks
    .equ SWITCH, STATE + 32             @ then TOGGLE's
    .equ ON, 0                          @ u8: switched on
    .equ R_DOWN, 1                      @ u8: R was down at the last V-blank
    .equ KEYINPUT, 0x04000130           @ a bit is clear while its button is down
    .equ LINE_BUDGET, 228
.if JAPANESE
    .equ TEXT_PRINTER_SIZE, 32          @ struct TextPrinter
.else
    .equ TEXT_PRINTER_SIZE, 36
.endif

install:
    push {r4, r5, r6, lr}
    bl ime_address
    ldrh r6, [r3]
    movs r0, #0
    strh r0, [r3]                       @ no interrupts while the hook changes
    ldr r5, p_resident
    adr r4, resident
    ldr r0, p_resident_size
1:  subs r0, #4
    bmi 2f
    ldr r1, [r4, r0]
    str r1, [r5, r0]
    b 1b
2:  ldr r0, p_intr_vblank
    ldr r1, [r0]
    subs r2, r5, #4                     @ where the replaced handler is kept
    subs r3, r1, r5
    lsrs r3, r3, #10
    bne 5f
    ldr r1, [r2]                        @ already installed: keep the original handler
    b 6f
5:  str r1, [r2]
6:  cmp r1, #0
    beq 7f
    ldr r3, p_orig_vblank               @ in the copy
    str r1, [r3]
    adds r1, r5, #1
    str r1, [r0]
7:  bl ime_address
    strh r6, [r3]
    pop {r4, r5, r6, pc}

ime_address:
    movs r3, #0x82
    lsls r3, r3, #2
    movs r2, #4
    lsls r2, r2, #24
    adds r3, r3, r2
    bx lr

    .align 2
p_resident:      .word RESIDENT
p_resident_size: .word resident_end - resident
p_intr_vblank:   .word INTR_VBLANK
p_orig_vblank:   .word RESIDENT + (orig_vblank - resident)

resident:
    push {r4, r5, lr}
    ldr r0, p_intr_check
    ldrh r4, [r0]                       @ bit 0 set: the game is lagging
    ldr r0, p_state
    ldr r1, [r0]
    adds r1, #1
    str r1, [r0]
    ldr r0, p_help_r_disable
    cmp r0, #0
    beq 1f
    movs r1, #1
    strb r1, [r0]                       @ keep R from opening the help system
1:
.if TOGGLE
    bl toggle
.endif
    bl swap_callbacks
    ldr r3, orig_vblank
    bl call_r3
    movs r0, #1
    tst r4, r0
    bne exit                            @ lagging: no extra runs
    ldr r4, p_ow_extra
    adr r5, ow_pair
    bl extra_frames
    ldr r4, p_battle_extra
    adr r5, battle_pair
    bl extra_frames
.if TOGGLE
    ldr r0, p_switch
    ldrb r0, [r0, #ON]
    cmp r0, #0
    beq exit
.endif
    ldr r0, p_text_printers
    movs r1, #32
2:  ldrb r2, [r0, #27]                  @ active
    cmp r2, #0
    beq 3f
    ldrb r2, [r0, #6]
    ldrb r3, [r0, #8]
    cmp r2, r3
    bne 3f
    ldrb r2, [r0, #7]
    ldrb r3, [r0, #9]
    cmp r2, r3
    beq exit                            @ a printer that has not started yet
3:  adds r0, #TEXT_PRINTER_SIZE
    subs r1, #1
    bne 2b
    ldr r0, p_state
    ldr r1, [r0, #4]
    adds r1, #1
    str r1, [r0, #4]
    ldr r4, p_text_extra
4:  cmp r4, #0
    beq exit
    ldr r3, p_run_text_printers
    bl call_r3
    subs r4, #1
    b 4b
exit:
    pop {r4, r5}
    pop {r0}
    bx r0

@ Runs the callback pair at r5 up to r4 more times while it is on, the game
@ is in those callbacks, no fade is running and the last run fit before V-blank.
extra_frames:
    push {lr}
    ldr r0, p_switch
    ldrb r0, [r0, #ON]
    cmp r0, #0
    beq 9f
1:  cmp r4, #0
    beq 9f
    ldr r0, p_main
    ldr r1, [r0, #4]
    ldr r2, [r5, #4]
    cmp r1, r2
    bne 9f
    ldr r1, [r0, #0]
    ldr r2, [r5, #0]
    cmp r1, r2
    bne 9f
    ldr r1, p_palette_fade
    ldrh r1, [r1, #6]
    lsrs r1, r1, #15
    bne 9f
    bl lines_since_vblank
    ldr r1, p_line_budget
    cmp r1, #0
    beq 2f
    ldr r2, p_state
    ldr r2, [r2, #12]                   @ lines the last extra run took
    lsls r3, r2, #1
    adds r3, r3, r0
    cmp r3, r1
    bls 2f
    ldr r0, p_state
    ldr r1, [r0, #16]
    adds r1, #1
    str r1, [r0, #16]
    lsrs r1, r2, #3
    adds r1, #1
    subs r2, r2, r1
    bpl 5f
    movs r2, #0
5:  str r2, [r0, #12]
    b 9f
2:  push {r0}
    ldr r0, p_main
    movs r1, #0
    strh r1, [r0, #46]                  @ newKeys
    strh r1, [r0, #48]                  @ newAndRepeatedKeys
    ldr r3, [r5, #0]
    bl call_r3
    ldr r0, p_main
    ldr r1, [r0, #4]
    ldr r3, [r5, #4]
    cmp r1, r3
    bne 8f
    bl call_r3
    bl lines_since_vblank
    pop {r1}
    subs r0, r0, r1
    bpl 6f
    adds r0, #228
6:  ldr r2, p_state
    str r0, [r2, #12]
    ldr r1, [r2, #8]
    adds r1, #1
    str r1, [r2, #8]
    subs r4, #1
    b 1b
8:  add sp, #4
9:  pop {r0}
    bx r0

call_r3:
    bx r3

.if TOGGLE
@ R going down switches the speed on or off.
toggle:
    ldr r2, p_switch
    ldr r0, p_keyinput
    ldrh r0, [r0]
    mvns r0, r0
    lsls r0, r0, #23
    lsrs r0, r0, #31                    @ 1 while R is down
    ldrb r1, [r2, #R_DOWN]
    strb r0, [r2, #R_DOWN]
    bics r0, r1                         @ 1 only as it goes down
    ldrb r1, [r2, #ON]
    eors r1, r0
    strb r1, [r2, #ON]
    bx lr
.endif

@ Slow down: every SLOW_PERIOD-th frame while it is on, both callbacks are
@ replaced with `noop` for one frame.
swap_callbacks:
    push {r4, lr}
    ldr r0, p_state
    ldr r1, [r0, #20]
    cmp r1, #0
    beq 1f
    ldr r2, p_main
    str r1, [r2, #0]
    ldr r1, [r0, #24]
    str r1, [r2, #4]
    movs r1, #0
    str r1, [r0, #20]
    str r1, [r0, #24]
1:  ldr r1, p_slow_period
    cmp r1, #0
    beq 9f
    ldr r0, p_switch
    ldrb r2, [r0, #ON]
    cmp r2, #0
    beq 9f
    ldr r0, p_state
    ldr r2, [r0, #28]
    adds r2, #1
    cmp r2, r1
    bcc 3f
    movs r2, #0
3:  str r2, [r0, #28]
    cmp r2, #0
    bne 9f
    ldr r3, p_main
    ldr r4, [r3, #0]
    ldr r2, p_cb1_overworld
    cmp r4, r2
    bne 4f
    ldr r4, [r3, #4]
    ldr r2, p_cb2_overworld
    cmp r4, r2
    beq 5f
4:  ldr r4, [r3, #0]
    ldr r2, p_battle_cb1
    cmp r4, r2
    bne 9f
    ldr r4, [r3, #4]
    ldr r2, p_battle_cb2
    cmp r4, r2
    bne 9f
5:  ldr r2, p_palette_fade
    ldrh r2, [r2, #6]
    lsrs r2, r2, #15
    bne 9f
    ldr r0, p_state
    ldr r4, [r3, #0]
    str r4, [r0, #20]
    ldr r4, [r3, #4]
    str r4, [r0, #24]
    ldr r4, p_noop
    str r4, [r3, #0]
    str r4, [r3, #4]
9:  pop {r4}
    pop {r0}
    bx r0
noop:
    bx lr

lines_since_vblank:
    ldr r0, p_vcount
    ldrh r0, [r0]
    subs r0, #160
    bpl 1f
    adds r0, #228
1:  bx lr

    .align 2
orig_vblank:          .word VBLANK_INTR
p_run_text_printers:  .word RUN_TEXT_PRINTERS
ow_pair:
p_cb1_overworld:      .word CB1_OVERWORLD
p_cb2_overworld:      .word CB2_OVERWORLD
battle_pair:
p_battle_cb1:         .word BATTLE_CB1
p_battle_cb2:         .word BATTLE_CB2
p_intr_check:         .word INTR_CHECK
p_text_extra:         .word TEXT_EXTRA
p_state:              .word STATE
p_text_printers:      .word TEXT_PRINTERS
p_ow_extra:           .word OW_EXTRA
p_battle_extra:       .word BATTLE_EXTRA
p_main:               .word MAIN
p_palette_fade:       .word PALETTE_FADE
p_switch:             .word SWITCH
.if TOGGLE
p_keyinput:           .word KEYINPUT
.endif
p_help_r_disable:     .word HELP_R_DISABLE
p_line_budget:        .word LINE_BUDGET
p_vcount:             .word 0x04000006
p_slow_period:        .word SLOW_PERIOD
p_noop:               .word RESIDENT + (noop - resident) + 1
resident_end:

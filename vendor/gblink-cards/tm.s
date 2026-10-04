@ Reusable TMs. `install` starts a V-blank hook that keeps a TM from being
@ used up by teaching a move, once per lesson, when gSpecialVar_ItemId is a
@ TM. Where the game takes the TM:
@ - Task_LearnedMove, which hands its task on to
@   Task_DoLearnedMoveFanfareAfterText: while a task is at that step of the
@   party menu and the move came from a TM or HM (gPartyMenu.data[1] is 0),
@   the TM goes back in the bag.
@ - FireRed/LeafGreen, after the animation of the TM being used plays out
@   (sCancelDisabled): CB2_UseItem, or CB2_UseTMHMAfterForgettingMove when a
@   move was replaced, takes it and leaves the party menu. While one of them
@   is about to run, one TM goes in the bag first. A skipped animation goes
@   back to the party menu and Task_LearnedMove instead.
@ HMs were never used up, and selling or giving a TM still does. `uninstall`
@ turns it off. The hook is copied to RESIDENT like the others, so it lasts
@ until the game is reset.
@
@ Parameters (--defsym): INTR_VBLANK, MAIN, TASKS, PARTY_MENU, ITEM_ID
@ (gSpecialVar_ItemId), CB2_UPDATE_PARTY_MENU, LEARNED_MOVE_STEP
@ (Task_DoLearnedMoveFanfareAfterText), ADD_BAG_ITEM, STATE, EMERALD and on
@ FireRed/LeafGreen CB2_USE_ITEM, CB2_USE_TM_AFTER_FORGETTING and
@ ITEM_ANIM_PLAYED (sCancelDisabled).

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RESIDENT, 0x0203FC00           @ unused RAM in both games
    .equ ENABLED, 0                     @ STATE: u8
    .equ GIVEN, 1                       @ u8: this lesson's TM is back
    .equ KEPT, 4                        @ the V-blank handler the hook calls
    .equ MAIN_CALLBACK2, 4
    .equ MAIN_INTR_CHECK, 0x1C
    .equ NUM_TASKS, 16
    .equ TASK_SIZE, 0x28
    .equ TASK_ACTIVE, 4
    .equ LEARN_METHOD, 16               @ gPartyMenu.data[1]: 0 for a TM or HM
    .equ ITEM_TM01, 289
    .equ NUM_TMS, 50
    .equ IME, 0x04000208

install:
    push {r4, r5, r6, lr}
    ldr r0, p_intr_vblank               @ pokeldn: the game's own handler while the copy
    ldr r1, p_vblank_intr               @ overwrites whatever hook runs at RESIDENT
    str r1, [r0]
    ldr r3, p_ime
    ldrh r6, [r3]
    movs r0, #0
    strh r0, [r3]                       @ no interrupts while the hook changes
    ldr r5, p_resident
    adr r4, resident
    ldr r0, p_resident_size
1:  subs r0, #4
    ldr r1, [r4, r0]
    str r1, [r5, r0]
    bne 1b
    ldr r4, p_state
    strb r0, [r4, #GIVEN]
    movs r0, #1
    strb r0, [r4, #ENABLED]
    ldr r0, p_intr_vblank
    ldr r1, p_vblank_intr               @ pokeldn: chain to the game's handler, never a hook,
    str r1, [r4, #KEPT]
    subs r3, r5, #4                     @ and keep it at RESIDENT - 4, where pokeldn's
    str r1, [r3]                        @ resident installs look for it [docs/frlg_rom.md]
    adds r1, r5, #1
    str r1, [r0]
3:  ldr r3, p_ime
    strh r6, [r3]
    pop {r4, r5, r6, pc}

uninstall:
    ldr r0, p_state
    movs r1, #0
    strb r1, [r0, #ENABLED]
    bx lr

    .align 2
p_ime:           .word IME
p_resident:      .word RESIDENT
p_resident_size: .word resident_end - resident
p_state:         .word STATE
p_intr_vblank:   .word INTR_VBLANK
p_vblank_intr:   .word VBLANK_INTR

@ ---- copied to RESIDENT
    .align 2
resident:
    push {r4, r5, r6, r7, lr}
    ldr r4, r_state
    ldrb r0, [r4, #ENABLED]
    cmp r0, #0
    beq 9f
    ldr r7, r_main
    ldrh r0, [r7, #MAIN_INTR_CHECK]
    lsls r0, r0, #31
    bne 9f                              @ the game is mid-frame
    ldr r0, [r7, #MAIN_CALLBACK2]
    ldr r1, r_party_menu_cb2
    cmp r0, r1
    beq 1f
.if EMERALD == 0
    ldr r1, r_use_item
    cmp r0, r1
    beq 4f
    ldr r1, r_use_after_forgetting
    cmp r0, r1
    beq 4f
.endif
    b 8f
1:  ldr r5, r_tasks
    movs r6, #NUM_TASKS
    ldr r1, r_learned_move_step
2:  ldr r0, [r5]
    cmp r0, r1
    bne 3f
    ldrb r0, [r5, #TASK_ACTIVE]
    cmp r0, #0
    bne 5f
3:  adds r5, #TASK_SIZE
    subs r6, #1
    bne 2b
8:  movs r0, #0                         @ no lesson ending: ready for the next
    strb r0, [r4, #GIVEN]
    b 9f
.if EMERALD == 0
4:  ldr r0, r_item_anim_played
    ldr r0, [r0]
    cmp r0, #0
    beq 9f                              @ skipped: the party menu takes the TM
    b 6f
.endif
5:  ldr r0, r_party_menu
    ldrh r0, [r0, #LEARN_METHOD]
    cmp r0, #0
    bne 9f
6:  ldrb r0, [r4, #GIVEN]
    cmp r0, #0
    bne 9f
    ldr r0, r_item_id
    ldrh r0, [r0]
    ldr r1, r_first_tm
    subs r1, r0, r1
    cmp r1, #NUM_TMS
    bcs 9f                              @ not a TM
    movs r1, #1
    strb r1, [r4, #GIVEN]
    ldr r3, r_add_bag_item
    bl r_call_r3
9:  ldr r3, [r4, #KEPT]
    bl r_call_r3
    pop {r4, r5, r6, r7}
    pop {r0}
    bx r0

r_call_r3:
    bx r3

    .align 2
r_state:             .word STATE
r_main:              .word MAIN
r_party_menu_cb2:    .word CB2_UPDATE_PARTY_MENU
r_tasks:             .word TASKS
r_learned_move_step: .word LEARNED_MOVE_STEP
r_party_menu:        .word PARTY_MENU
r_item_id:           .word ITEM_ID
r_first_tm:          .word ITEM_TM01
r_add_bag_item:      .word ADD_BAG_ITEM
.if EMERALD == 0
r_use_item:             .word CB2_USE_ITEM
r_use_after_forgetting: .word CB2_USE_TM_AFTER_FORGETTING
r_item_anim_played:     .word ITEM_ANIM_PLAYED
.endif
resident_end:

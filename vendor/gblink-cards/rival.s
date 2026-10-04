@ Rename Your Rival (FireRed/LeafGreen). `rename_rival` opens the game's naming
@ screen for the rival: DoNamingScreen(NAMING_SCREEN_RIVAL, rivalName, 0, 0,
@ 0, CB2_ReturnToFieldContinueScript).
@
@ Parameters (--defsym): SB1_PTR, DO_NAMING_SCREEN, RETURN_TO_FIELD and those
@ of relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ RIVAL_NAME, 0x3A4C             @ in SaveBlock1
    .equ NAMING_SCREEN_RIVAL, 4

rename_rival:
    push {r4, lr}
    sub sp, #8
    ldr r3, p_return_to_field
    str r3, [sp, #4]
    movs r0, #0
    str r0, [sp]
    ldr r1, p_sb1_ptr
    ldr r1, [r1]
    ldr r2, p_rival_name
    adds r1, r1, r2
    movs r2, #0
    movs r3, #0
    movs r0, #NAMING_SCREEN_RIVAL
    ldr r4, p_naming_screen
    bl call_r4
    add sp, #8
    pop {r4, pc}

call_r4:
    bx r4

    .align 2
p_sb1_ptr:         .word SB1_PTR
p_rival_name:      .word RIVAL_NAME
p_naming_screen:   .word DO_NAMING_SCREEN
p_return_to_field: .word RETURN_TO_FIELD

    .include "relocate.inc"

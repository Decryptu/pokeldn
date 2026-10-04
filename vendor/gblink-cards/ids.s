@ Trainer ID reveal. `buffer_ids` writes the player's trainer id to gStringVar1
@ and secret id to gStringVar2, five digits each, from SaveBlock2.
@
@ Parameters (--defsym): SB2_PTR, STRING_VAR_1, STRING_VAR_2, INT_TO_STRING.

    .syntax unified
    .thumb
    .text
    .align 2

    .equ PLAYER_ID, 10                  @ in SaveBlock2: trainer id, then secret id
    .equ LEADING_ZEROS, 2
    .equ ID_DIGITS, 5

buffer_ids:
    push {r4, r5, lr}
    ldr r4, p_sb2_ptr
    ldr r4, [r4]
    ldr r5, p_int_to_string
    ldrh r1, [r4, #PLAYER_ID]
    ldr r0, p_string_var_1
    movs r2, #LEADING_ZEROS
    movs r3, #ID_DIGITS
    bl call_r5
    ldrh r1, [r4, #PLAYER_ID + 2]
    ldr r0, p_string_var_2
    movs r2, #LEADING_ZEROS
    movs r3, #ID_DIGITS
    bl call_r5
    pop {r4, r5, pc}

call_r5:
    bx r5

    .align 2
p_sb2_ptr:       .word SB2_PTR
p_string_var_1:  .word STRING_VAR_1
p_string_var_2:  .word STRING_VAR_2
p_int_to_string: .word INT_TO_STRING

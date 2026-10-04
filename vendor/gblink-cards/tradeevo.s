@ Trade Evolution. `trade_evolve` asks the game's GetEvolutionTargetSpecies,
@ in trade mode, what the Pokémon in gSpecialVar_0x8004 becomes when traded;
@ for an evolution that needs a held item it takes the item, as a trade
@ does. If there is one, the game's evolution scene starts (it cannot be
@ stopped, as after a trade) and returns to the script through
@ CB2_ReturnToFieldContinueScript. VAR_RESULT = 1 when it started, else 0.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ GET_EVOLUTION_TARGET, BEGIN_EVOLUTION_SCENE, CB2_AFTER_EVOLUTION,
@ RETURN_TO_FIELD and those of relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
    .equ EVO_MODE_TRADE, 1

trade_evolve:
    push {r4, r5, lr}
    bl chosen_mon
    movs r4, r0
    movs r1, #EVO_MODE_TRADE
    movs r2, #0
    ldr r3, p_evolution_target
    bl call_r3
    movs r5, r0
    beq 9f
    ldr r0, p_after_evolution
    ldr r1, p_return_to_field
    str r1, [r0]
    ldr r3, p_var_8004
    ldrb r3, [r3]                       @ the party slot
    movs r2, #0                         @ it cannot be stopped
    movs r1, r5
    movs r0, r4
    ldr r4, p_evolution_scene
    bl call_r4
    movs r5, #1
9:  ldr r0, p_var_result
    strh r5, [r0]
    pop {r4, r5, pc}

call_r3:
    bx r3

call_r4:
    bx r4

    .align 2
p_var_8004:         .word SPECIAL_VAR_8004
p_var_result:       .word SPECIAL_VAR_RESULT
p_evolution_target: .word GET_EVOLUTION_TARGET
p_evolution_scene:  .word BEGIN_EVOLUTION_SCENE
p_after_evolution:  .word CB2_AFTER_EVOLUTION
p_return_to_field:  .word RETURN_TO_FIELD

    .include "mons.inc"
    .include "relocate.inc"

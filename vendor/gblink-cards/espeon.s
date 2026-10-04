@ Espeon & Umbreon. `check` looks at the Pokémon in gSpecialVar_0x8004 and
@ puts its friendship in VAR_0x8005; VAR_RESULT = 0 for an EEVEE at 220 or
@ more, 1 for another species, 2 for an EEVEE that isn't friendly enough.
@ `form_menu` offers ESPEON and UMBREON, and `evolve` starts the game's
@ evolution scene into form VAR_RESULT of them, which B can stop as in a
@ friendship evolution. The scene returns to the script through
@ CB2_ReturnToFieldContinueScript.
@
@ Parameters (--defsym): PARTY, SPECIAL_VAR_8004, SPECIAL_VAR_RESULT,
@ GET_MON_DATA, BEGIN_EVOLUTION_SCENE, CB2_AFTER_EVOLUTION, RETURN_TO_FIELD
@ and those of menu.inc and relocate.inc; data.inc holds the forms' names.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MONS_CHOSEN, 1
    .set MENU_LISTS, 1
    .equ MON_DATA_SPECIES, 11
    .equ MON_DATA_FRIENDSHIP, 32
    .equ SPECIES_EEVEE, 133
    .equ SPECIES_ESPEON, 196            @ UMBREON follows it
    .equ FRIENDSHIP_TO_EVOLVE, 220
    .equ FORM_WIDTH, 8                  @ tiles, for UMBREON

check:
    push {r4, r5, lr}
    bl chosen_mon
    movs r4, r0
    movs r1, #MON_DATA_FRIENDSHIP
    bl get_mon_data
    ldr r1, p_var_8004
    strh r0, [r1, #2]                   @ VAR_0x8005
    movs r5, #2
    cmp r0, #FRIENDSHIP_TO_EVOLVE
    bcc 1f
    movs r5, #0
1:  movs r0, r4
    movs r1, #MON_DATA_SPECIES
    bl get_mon_data
    cmp r0, #SPECIES_EEVEE
    beq 2f
    movs r5, #1
2:  ldr r0, p_var_result
    strh r5, [r0]
    pop {r4, r5, pc}

form_menu:
    adr r0, form_items
    movs r1, #2
    movs r2, #FORM_WIDTH
    b list_menu

evolve:
    push {r4, lr}
    ldr r0, p_after_evolution
    ldr r1, p_return_to_field
    str r1, [r0]
    bl chosen_mon
    ldr r1, p_var_result
    ldrh r1, [r1]
    adds r1, #SPECIES_ESPEON
    movs r2, #1                         @ B can stop it
    ldr r3, p_var_8004
    ldrb r3, [r3]                       @ the party slot
    ldr r4, p_evolution_scene
    bl call_r4
    pop {r4, pc}

get_mon_data:
    movs r2, #0
    ldr r3, p_get_mon_data
    bx r3

call_r4:
    bx r4

    .align 2
p_var_8004:        .word SPECIAL_VAR_8004
p_var_result:      .word SPECIAL_VAR_RESULT
p_get_mon_data:    .word GET_MON_DATA
p_evolution_scene: .word BEGIN_EVOLUTION_SCENE
p_after_evolution: .word CB2_AFTER_EVOLUTION
p_return_to_field: .word RETURN_TO_FIELD

    .include "data.inc"
    .include "menu.inc"
    .include "mons.inc"
    .include "relocate.inc"

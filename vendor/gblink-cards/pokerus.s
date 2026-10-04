@ Gives every party Pokémon Pokérus (strain 1, two days left), a value the
@ game's RandomlyGivePartyPokerus can also produce. It is the first byte of the
@ misc substructure.
@
@ Parameters (--defsym): PARTY (&gPlayerParty).

    .syntax unified
    .thumb
    .text
    .align 2

    .equ POKERUS, 0x12
    .set MONS_SET_BYTE, 1

infect:
    push {r4, r5, lr}
    ldr r4, p_party
    movs r5, #PARTY_SIZE
1:  ldrb r0, [r4, #MON_FLAGS]
    movs r1, #3
    ands r0, r1
    cmp r0, #2                          @ a species, not a bad egg
    bne 2f
    movs r0, r4
    movs r1, #MISC
    movs r2, #MISC_POKERUS
    movs r3, #POKERUS
    bl set_mon_byte
2:  adds r4, #MON_SIZE
    subs r5, #1
    bne 1b
    pop {r4, r5}
    pop {r0}
    bx r0

    .align 2
p_party: .word PARTY

    .include "mons.inc"

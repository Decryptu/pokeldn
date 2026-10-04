@ Party Pokémon: 100 bytes each; the first 80 are a BoxPokemon whose 48 secure
@ bytes are four 12-byte substructures (growth, attacks, EVs, misc), XORed with
@ personality ^ otId and ordered by personality % 24. The checksum is the sum of
@ the decrypted secure halfwords.
@
@ Set MONS_SET_BYTE before including to get `set_mon_byte`, MONS_ORDER for
@ `umod` and `substruct_order` alone, and MONS_CHOSEN for `chosen_mon`.

    .equ MON_SIZE, 100
    .equ PARTY_SIZE, 6
    .equ MON_PERSONALITY, 0x00
    .equ MON_OT_ID, 0x04
    .equ MON_NICKNAME, 0x08
    .equ MON_LANGUAGE, 0x12
    .equ MON_FLAGS, 0x13                @ isBadEgg bit 0, hasSpecies bit 1, isEgg bit 2
    .equ MON_OT_NAME, 0x14              @ 7 characters
    .equ BOX_MON_SIZE, 80
    .equ MON_CHECKSUM, 0x1C
    .equ MON_SECURE, 0x20
    .equ SUBSTRUCT_SIZE, 12
    .equ GROWTH, 0                      @ substructure numbers for `substruct`
    .equ ATTACKS, 1
    .equ EVS, 2
    .equ MISC, 3
    .equ GROWTH_FRIENDSHIP, 9           @ egg cycles left, for an Egg
    .equ MISC_POKERUS, 0
    .equ MISC_IVS, 4
    .equ A_POKEMON, 2                   @ MON_FLAGS & 7: a species, not an Egg, not bad
    .equ AN_EGG, 6                      @ MON_FLAGS & 7: a species and an Egg, not bad

.ifdef MONS_SET_BYTE
    .set MONS_ORDER, 1
.endif

.ifdef MONS_CHOSEN
@ r0 = the party Pokémon in gSpecialVar_0x8004. Needs PARTY and
@ SPECIAL_VAR_8004.
chosen_mon:
    ldr r0, mons_var_8004
    ldrh r0, [r0]
    movs r1, #MON_SIZE
    muls r0, r1
    ldr r1, mons_party
    adds r0, r0, r1
    bx lr

    .align 2
mons_var_8004: .word SPECIAL_VAR_8004
mons_party:    .word PARTY
.endif

.ifdef MONS_ORDER
@ r0 = r0 % r1, for r1 below 32.
umod:
    lsls r1, r1, #27
    lsrs r2, r1, #27
1:  cmp r0, r1
    bcc 2f
    subs r0, r0, r1
2:  cmp r1, r2
    beq 3f
    lsrs r1, r1, #1
    b 1b
3:  bx lr
.endif

.ifdef MONS_SET_BYTE
@ r0 = the address of substructure r1 (GROWTH .. MISC) of the Pokémon at r0.
substruct:
    push {r4, r5, lr}
    movs r4, r0
    lsls r5, r1, #1                     @ its bit position in substruct_order
    ldr r0, [r4, #MON_PERSONALITY]
    movs r1, #24
    bl umod
    adr r1, substruct_order
    ldrb r0, [r1, r0]
    lsrs r0, r5
    movs r1, #3
    ands r0, r1
    movs r1, #SUBSTRUCT_SIZE
    muls r0, r1
    adds r0, #MON_SECURE
    adds r0, r4, r0
    pop {r4, r5}
    pop {r1}
    bx r1

@ r0 = the encryption key (personality ^ otId) of the Pokémon at r0.
key_of:
    ldr r1, [r0, #MON_PERSONALITY]
    ldr r0, [r0, #MON_OT_ID]
    eors r0, r1
    bx lr

@ Sets the byte at offset r2 of substructure r1 of the Pokémon at r0 to r3 and
@ updates the checksum.
set_mon_byte:
    push {r4, r5, r6, r7, lr}
    movs r7, r0                         @ the Pokémon
    push {r2, r3}
    bl substruct
    movs r4, r0
    movs r0, r7
    bl key_of
    movs r5, r0                         @ the key
    pop {r2, r3}
    lsrs r1, r2, #2
    lsls r1, r1, #2
    adds r4, r4, r1                     @ the word holding the byte
    movs r1, #3
    ands r1, r2
    lsls r1, r1, #3                     @ the byte's shift in it
    ldr r6, [r4]
    eors r6, r5
    movs r2, r6
    lsrs r2, r1
    lsls r2, r2, #24
    lsrs r2, r2, #24                    @ the old byte
    movs r0, #0xFF
    lsls r0, r1
    bics r6, r0
    movs r0, r3
    lsls r0, r1
    orrs r6, r0
    eors r6, r5
    str r6, [r4]
    subs r3, r3, r2                     @ change in the byte
    movs r0, #8
    ands r1, r0                         @ an odd byte is the high half of a halfword
    lsls r3, r1
    ldrh r0, [r7, #MON_CHECKSUM]
    adds r0, r0, r3
    strh r0, [r7, #MON_CHECKSUM]
    pop {r4, r5, r6, r7}
    pop {r0}
    bx r0
.endif

.ifndef REP_KEEP_ORDER
.ifdef MONS_ORDER
@ Substructure positions by personality % 24, two bits each with growth lowest
@ (GetSubstruct's SUBSTRUCT_CASE).
    .align 2
substruct_order:
    .byte 0xE4, 0xB4, 0xD8, 0x9C, 0x78, 0x6C, 0xE1, 0xB1, 0xD2, 0x93, 0x72, 0x63
    .byte 0xC9, 0x8D, 0xC6, 0x87, 0x4E, 0x4B, 0x39, 0x2D, 0x36, 0x27, 0x1E, 0x1B
    .align 2
.endif
.endif

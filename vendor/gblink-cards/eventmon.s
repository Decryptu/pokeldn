@ Event Pokémon. `give_mon` makes a copy of an English Gen 3 distribution the
@ way PKHeX's EncounterGift3 describes it, from the card's settings below: the
@ distribution's trainer id, level, flags and OT name, and its Pokémon
@ (species, then four moves; VAR_0x8004 picks one where there are several).
@
@ The origin seed is 16 bits of Random(), or for MYSTRY Mew one of the 86 seeds
@ its Mew came from, 1 to 4 Mew along. The GBA LCG then gives the high half of
@ the PID and its low half (+8 and rounded down to a multiple of 8 where it
@ would be shiny and the event never gave shinies), two calls of IVs, and one
@ call for the held item (WISHMKR's Salac or Ganlon Berry) or the OT's gender
@ (bit 7 inverted, or (r / 3) & 1).
@
@ Pokémon Box's Eggs take a 32-bit seed and the same calls, with no
@ anti-shiny step. The Pokémon Channel JIRACHI and the COLOSSEUM gifts come
@ from the GameCube's LCG and a 32-bit seed: for CHANNEL, the menu and accept
@ calls PKHeX's ChannelJirachi skips, then the secret id, the PID (bit 31
@ flipped as the game does), one call each for the held item (Ganlon or Salac
@ Berry), the game (Sapphire or Ruby) and the OT's gender, and the six IVs
@ from the top five bits of a call each; for the COLOSSEUM, two calls of IVs,
@ the ability's call and the PID, from the next seed along while that PID
@ would be shiny.
@
@ CreateMon makes the Pokémon, which then gets the event's OT, IVs, moves and
@ met data (a fateful encounter, in Ruby unless the event says otherwise, at
@ its level, in a POKé BALL), and the fateful-encounter flag and National
@ Ribbon where the event had them. An Egg is the player's until it hatches,
@ as the game's own Eggs are: in Japanese, named タマゴ, with its species' egg
@ cycles, met at level 0 in this game. It goes to the next party slot
@ (gPlayerPartyCount, which the script counts with getpartysize first), else
@ to the PC by the routine GiveMonToPlayer uses, which (unlike
@ GiveMonToPlayer) keeps the OT. Given, it counts as seen and caught, but an
@ Egg only once it hatches. VAR_RESULT = MON_GIVEN_TO_PARTY, MON_GIVEN_TO_PC
@ or MON_CANT_GIVE.
@
@ On cards with several Pokémon, `offer` puts the species of Pokémon
@ VAR_0x8004 in VAR_0x8006, with VAR_RESULT 1, or 0 past the last.
@
@ The Japanese games name every Pokémon in Japanese: there a distribution
@ that was not Japanese gives an English Pokémon with its English name.
@
@ Parameters (--defsym): EVENT (below), PARTY, PARTY_COUNT, ENEMY_PARTY,
@ SPECIAL_VAR_8004, SPECIAL_VAR_RESULT, RANDOM, CREATE_MON, SET_MON_DATA,
@ SET_MON_MOVE_SLOT, CALCULATE_STATS, SEND_MON_TO_PC, SPECIES_TO_NATIONAL,
@ GET_SET_POKEDEX_FLAG, SPECIES_INFO and JAPANESE (1 on the Japanese games).

    .syntax unified
    .thumb
    .text
    .align 2

    .equ EVENT_WISHMKR_JIRACHI, 1
    .equ EVENT_10_ANIV_CELEBI, 2
    .equ EVENT_10_ANIV_KANTO, 3
    .equ EVENT_10_ANIV_LEGENDS, 4
    .equ EVENT_10_ANIV_JOHTO_HOENN, 5
    .equ EVENT_DOEL_DEOXYS, 6
    .equ EVENT_SPACE_C_DEOXYS, 7
    .equ EVENT_AURA_MEW, 8
    .equ EVENT_MYSTRY_MEW, 9
    .equ EVENT_ROCKS_METANG, 10
    .equ EVENT_CHANNEL_JIRACHI, 11
    .equ EVENT_BOX_EGGS, 12
    .equ EVENT_COLOSSEUM_PIKACHU, 13
    .equ EVENT_AGETO_CELEBI, 14
    .equ EVENT_MATTLE_HO_OH, 15

    .equ F_ANTI_SHINY, 1
    .equ F_FATEFUL, 2
    .equ F_NATIONAL_RIBBON, 4
    .equ F_GENDER_BIT7, 8               @ OT gender: bit 7 of the call, inverted,
    .equ F_GENDER_DIV3, 16              @ or (call / 3) & 1; else male
    .equ F_WISHMKR_ITEM, 32
    .equ F_MYSTRY_SEEDS, 64
    .equ F_SEED_32, 128                 @ a 32-bit seed
    .equ F_CHANNEL, 256                 @ the GameCube LCG: Pokémon Channel's calls
    .equ F_CXD, 512                     @ or COLOSSEUM's, never shiny
    .equ F_EGG, 1024
    .equ F_JAPANESE, 2048               @ Japanese, named jp_name
    .equ F_OT_FEMALE, 4096
    .equ F_MET_LEVEL_0, 8192
    .equ F_ENGLISH, 16384               @ English: an English-only distribution

@ ---- the distributions (PKHeX EncountersWC3): trainer id (secret id 0),
@ level, flags and how many Pokémon; the OT names and the Pokémon are below
.if EVENT == EVENT_WISHMKR_JIRACHI
    .equ TID, 20043
    .equ LEVEL, 5
    .equ FLAGS, F_WISHMKR_ITEM | F_ENGLISH
    .equ MONS, 1
.endif
.if EVENT == EVENT_10_ANIV_CELEBI       @ Journey Across America
    .equ TID, 10
    .equ LEVEL, 70
    .equ FLAGS, F_ANTI_SHINY | F_GENDER_BIT7 | F_ENGLISH
    .equ MONS, 1
.endif
.if EVENT >= EVENT_10_ANIV_KANTO && EVENT <= EVENT_10_ANIV_JOHTO_HOENN
    .equ TID, 6808                      @ Party of the Decade
    .equ LEVEL, 70
    .equ FLAGS, F_ANTI_SHINY | F_GENDER_BIT7 | F_ENGLISH
.endif
.if EVENT == EVENT_10_ANIV_KANTO || EVENT == EVENT_10_ANIV_JOHTO_HOENN
    .equ MONS, 6
.endif
.if EVENT == EVENT_10_ANIV_LEGENDS
    .equ MONS, 8
.endif
.if JAPANESE == 0
.if EVENT == EVENT_10_ANIV_KANTO
    .equ EN_NAMES, 6
.endif
.if EVENT == EVENT_10_ANIV_LEGENDS
    .equ EN_NAMES, 3
.endif
.if EVENT == EVENT_10_ANIV_JOHTO_HOENN
    .equ EN_NAMES, 5
.endif
.endif
.if EVENT == EVENT_DOEL_DEOXYS
    .equ TID, 28606
.endif
.if EVENT == EVENT_SPACE_C_DEOXYS
    .equ TID, 10
.endif
.if EVENT == EVENT_DOEL_DEOXYS || EVENT == EVENT_SPACE_C_DEOXYS
    .equ LEVEL, 70
    .equ FLAGS, F_ANTI_SHINY | F_GENDER_BIT7 | F_FATEFUL | F_ENGLISH
    .equ MONS, 1
.endif
.if EVENT == EVENT_AURA_MEW
    .equ TID, 20078
    .equ LEVEL, 10
    .equ FLAGS, F_ANTI_SHINY | F_GENDER_BIT7 | F_FATEFUL
    .equ MONS, 1
.endif
.if EVENT == EVENT_MYSTRY_MEW
    .equ TID, 6930
    .equ LEVEL, 10
    .equ FLAGS, F_ANTI_SHINY | F_GENDER_DIV3 | F_FATEFUL | F_MYSTRY_SEEDS | F_ENGLISH
    .equ MONS, 1
.endif
.if EVENT == EVENT_ROCKS_METANG
    .equ TID, 2005
    .equ LEVEL, 30
    .equ FLAGS, F_ANTI_SHINY | F_NATIONAL_RIBBON | F_ENGLISH
    .equ MONS, 1
.endif
.if EVENT == EVENT_CHANNEL_JIRACHI      @ the secret id comes from the calls
    .equ TID, 40122
    .equ LEVEL, 5
    .equ FLAGS, F_SEED_32 | F_CHANNEL | F_MET_LEVEL_0
    .equ MONS, 1
.endif
.if EVENT == EVENT_BOX_EGGS             @ an Egg's trainer id is the player's
    .equ TID, 0
    .equ LEVEL, 5
    .equ FLAGS, F_SEED_32 | F_EGG | F_JAPANESE | F_OT_FEMALE | F_MET_LEVEL_0
    .equ MONS, 4
    .equ OT_ID_TYPE, OT_ID_PLAYER_ID
.endif
.if EVENT == EVENT_COLOSSEUM_PIKACHU || EVENT == EVENT_AGETO_CELEBI
    .equ TID, 31121
    .equ LEVEL, 10
.endif
.if EVENT == EVENT_COLOSSEUM_PIKACHU
    .equ FLAGS, F_SEED_32 | F_CXD | F_JAPANESE
    .equ MONS, 1
.endif
.if EVENT == EVENT_AGETO_CELEBI
    .equ FLAGS, F_SEED_32 | F_CXD | F_JAPANESE | F_OT_FEMALE
    .equ MONS, 1
.endif
.if EVENT == EVENT_MATTLE_HO_OH
    .equ TID, 10048
    .equ LEVEL, 70
    .equ FLAGS, F_SEED_32 | F_CXD | F_ENGLISH
    .equ MONS, 1
    .equ MET_GAME, VERSION_SAPPHIRE
.endif

    .equ ENTRY_SIZE, 10                 @ u16 species, u16 moves[4]
    .equ PARTY_SIZE, 6
    .equ MON_SIZE, 100
    .equ OT_ID_PRESET, 1
    .equ OT_ID_PLAYER_ID, 0
    .equ MON_DATA_NICKNAME, 2
    .equ MON_DATA_LANGUAGE, 3
    .equ MON_DATA_OT_NAME, 7
    .equ MON_DATA_HELD_ITEM, 12
    .equ MON_DATA_FRIENDSHIP, 32
    .equ MON_DATA_MET_LOCATION, 35
    .equ MON_DATA_MET_LEVEL, 36
    .equ MON_DATA_MET_GAME, 37
    .equ MON_DATA_HP_IV, 39
    .equ MON_DATA_IS_EGG, 45
    .equ MON_DATA_OT_GENDER, 49
    .equ MON_DATA_NATIONAL_RIBBON, 76
    .equ MON_DATA_FATEFUL, 80           @ MON_DATA_MODERN_FATEFUL_ENCOUNTER
    .equ METLOC_FATEFUL_ENCOUNTER, 0xFF
    .equ VERSION_SAPPHIRE, 1
    .equ VERSION_RUBY, 2
    .equ LANGUAGE_JAPANESE, 1
    .equ LANGUAGE_ENGLISH, 2
    .equ SPECIES_INFO_SIZE, 28
    .equ EGG_CYCLES, 17                 @ in gSpeciesInfo
    .equ MON_GIVEN_TO_PARTY, 0
    .equ MON_CANT_GIVE, 2
    .equ FLAG_SET_SEEN, 2
    .equ FLAG_SET_CAUGHT, 3
    .equ ITEM_GANLON_BERRY, 169
    .equ ITEM_SALAC_BERRY, 170
    .equ MYSTRY_SEED_COUNT, 86
    .equ MYSTRY_RELEASED_SEED, 0x6065   @ its only valid Mew is the 2nd along
    .equ FRAME, 24                      @ CreateMon's four stack arguments, then:
    .equ IVS, 16                        @ the IVs, packed as the game keeps them
    .equ VALUE, 20                      @ a value for SetMonData
.ifndef MET_GAME
    .equ MET_GAME, VERSION_RUBY
.endif
.ifndef OT_ID_TYPE
    .equ OT_ID_TYPE, OT_ID_PRESET
.endif
.if (FLAGS & F_ENGLISH) || (JAPANESE && (FLAGS & F_JAPANESE) == 0)
    .equ ENGLISH, 1
.else
    .equ ENGLISH, 0
.endif
.if JAPANESE && ENGLISH                 @ every name in English
    .equ EN_NAMES, MONS
.endif
.ifndef EN_NAMES                        @ the first Pokémon whose name some language spells
    .equ EN_NAMES, 0                    @ another way, in en_names
.endif

give_mon:
    push {r4, r5, r6, r7, lr}
    sub sp, #FRAME
    adr r4, mons
.if MONS > 1
    ldr r0, p_var_8004
    ldrh r0, [r0]
    movs r1, #ENTRY_SIZE
    muls r0, r1
    adds r4, r4, r0                     @ the Pokémon
.endif
    ldr r3, p_random
    bl call_r3
    lsls r6, r0, #16
    lsrs r6, r6, #16                    @ the origin seed
.if FLAGS & F_SEED_32
    ldr r3, p_random
    bl call_r3
    lsls r0, r0, #16
    orrs r6, r0
.endif
.if FLAGS & F_MYSTRY_SEEDS
    movs r0, r6
    movs r1, #MYSTRY_SEED_COUNT
    svc #6                              @ Div: r1 = r0 % 86
    lsls r1, r1, #1
    adr r0, mystry_seeds
    ldrh r0, [r0, r1]
    lsls r2, r6, #30
    lsrs r2, r2, #30
    adds r2, #1                         @ Mew 1 to 4 along
    ldr r1, p_released_seed
    cmp r0, r1
    bne 1f
    movs r2, #2
1:  movs r1, #5
    muls r2, r1
    movs r6, r0
2:  bl rand16
    subs r2, #1
    bne 2b
.endif
.if FLAGS & F_CHANNEL
    movs r5, #0                         @ JIRACHI's menu: calls until the tops
1:  bl rand16                           @ of the seed have been 1, 2 and 3
    lsrs r0, r6, #30
    movs r1, #1
    lsls r1, r0
    orrs r5, r1
    cmp r5, #14
    bcc 1b
    bl rand16                           @ accepting it: four calls, a 25%
    bl rand16                           @ call, and then one call if it passed,
    bl rand16                           @ else a 33% call and one call if that
    bl rand16                           @ passed, else two
    bl rand16
    movs r1, #1
    lsls r1, r1, #14
    cmp r0, r1
    bls 2f
    bl rand16
    ldr r1, p_third
    cmp r0, r1
    bls 2f
    bl rand16
2:  bl rand16
    bl rand16
    movs r5, r0                         @ the secret id
    bl rand16
    lsls r7, r0, #16
    bl rand16
    orrs r7, r0                         @ the PID
    movs r1, #1                         @ bit 31 flips unless (low half < 8)
    cmp r0, #8                          @ is high half ^ secret id ^ trainer id
    bcc 3f
    movs r1, #0
3:  lsrs r0, r7, #16
    eors r0, r5
    ldr r2, p_tid
    eors r0, r2
    cmp r0, r1
    beq 4f
    movs r0, #1
    lsls r0, r0, #31
    eors r7, r0
4:  lsls r5, r5, #16                    @ the secret id, then the top bits of
    bl rand16                           @ the calls for the item (bit 0), the
    lsrs r0, r0, #15                    @ game (bit 1) and the OT's gender
    orrs r5, r0                         @ (bit 2)
    bl rand16
    lsrs r0, r0, #15
    lsls r0, r0, #1
    orrs r5, r0
    bl rand16
    lsrs r0, r0, #15
    lsls r0, r0, #2
    orrs r5, r0
    movs r2, #0
    movs r3, #0
5:  bl rand16                           @ each IV, the top five bits of a call
    lsrs r0, r0, #11
    lsls r0, r3
    orrs r2, r0
    adds r3, #5
    cmp r3, #30
    bne 5b
    str r2, [sp, #IVS]
    str r7, [sp, #4]                    @ CreateMon(mon, species, level, 0, TRUE,
    movs r0, #1                         @ pid, OT_ID_PRESET, trainer id)
    str r0, [sp, #0]
    movs r0, #OT_ID_PRESET
    str r0, [sp, #8]
    lsrs r0, r5, #16
    lsls r0, r0, #16
    ldr r1, p_tid
    orrs r0, r1
    str r0, [sp, #12]
.elseif FLAGS & F_CXD
    movs r5, r6                         @ the first seed
1:  movs r6, r5
    bl rand16
    lsls r7, r0, #17
    lsrs r7, r7, #17
    bl rand16
    lsls r0, r0, #17
    lsrs r0, r0, #2
    orrs r7, r0
    str r7, [sp, #IVS]
    bl rand16                           @ the ability's call
    bl rand16
    lsls r7, r0, #16
    bl rand16
    orrs r7, r0                         @ the PID
    lsrs r0, r7, #16
    eors r0, r7
    ldr r1, p_tid
    eors r0, r1
    lsls r0, r0, #16
    lsrs r0, r0, #19
    bne 2f                              @ not shiny
    movs r6, r5
    bl rand16
    movs r5, r6                         @ else from the next seed along
    b 1b
2:  str r7, [sp, #4]                    @ CreateMon(mon, species, level, 0, TRUE,
    movs r0, #1                         @ pid, OT_ID_PRESET, trainer id)
    str r0, [sp, #0]
    movs r0, #OT_ID_PRESET
    str r0, [sp, #8]
    ldr r0, p_tid
    str r0, [sp, #12]
.else
    bl rand16
    lsls r7, r0, #16
    bl rand16
    orrs r7, r0                         @ the PID
.if FLAGS & F_ANTI_SHINY
    lsrs r0, r7, #16
    eors r0, r7
    ldr r1, p_tid
    eors r0, r1
    lsls r0, r0, #16
    lsrs r0, r0, #19
    bne 3f                              @ not shiny
    adds r7, #8
    lsrs r7, r7, #3
    lsls r7, r7, #3
3:
.endif
    str r7, [sp, #4]                    @ CreateMon(mon, species, level, 0, TRUE,
    movs r0, #1                         @ pid, OT_ID_PRESET, trainer id)
    str r0, [sp, #0]
    movs r0, #OT_ID_TYPE
    str r0, [sp, #8]
    ldr r0, p_tid
    str r0, [sp, #12]
    bl rand16
    lsls r7, r0, #17
    lsrs r7, r7, #17
    bl rand16
    lsls r0, r0, #17
    lsrs r0, r0, #2
    orrs r0, r7
    str r0, [sp, #IVS]
.if FLAGS & (F_WISHMKR_ITEM | F_GENDER_BIT7 | F_GENDER_DIV3)
    bl rand16
    movs r6, r0                         @ the call for the item or the OT's gender
.endif
.endif
    ldr r0, p_mon
    ldrh r1, [r4]
    movs r2, #LEVEL
    movs r3, #0
    ldr r7, p_create_mon
    bl call_r7
    adr r2, ot_name
    movs r1, #MON_DATA_OT_NAME
    bl set_data
.if FLAGS & F_GENDER_BIT7
    mvns r0, r6
    lsrs r0, r0, #7                     @ bit 7, inverted; the field keeps bit 0
.elseif FLAGS & F_GENDER_DIV3
    movs r0, r6
    movs r1, #3
    svc #6                              @ Div: r0 = call / 3
.elseif FLAGS & F_CHANNEL
    lsrs r0, r5, #2
.elseif FLAGS & F_OT_FEMALE
    movs r0, #1
.else
    movs r0, #0                         @ male
.endif
    movs r1, #MON_DATA_OT_GENDER
    bl set_value
    movs r0, #METLOC_FATEFUL_ENCOUNTER
    movs r1, #MON_DATA_MET_LOCATION
    bl set_value
.if FLAGS & F_CHANNEL
    lsrs r0, r5, #1
    movs r1, #1
    ands r0, r1
    adds r0, #VERSION_SAPPHIRE          @ Sapphire, or Ruby
.else
    movs r0, #MET_GAME
.endif
.if (FLAGS & F_EGG) == 0                @ an Egg's is this game
    movs r1, #MON_DATA_MET_GAME
    bl set_value
.endif
.if FLAGS & F_WISHMKR_ITEM
    movs r0, r6
    movs r1, #3
    svc #6                              @ Div: r0 = call / 3
    movs r1, #1
    ands r1, r0
    movs r0, #ITEM_SALAC_BERRY
    subs r0, r0, r1                     @ Salac, or Ganlon when (call / 3) & 1
    movs r1, #MON_DATA_HELD_ITEM
    bl set_value
.endif
.if FLAGS & F_CHANNEL
    movs r0, #1
    ands r0, r5
    adds r0, #ITEM_GANLON_BERRY         @ Ganlon, or Salac
    movs r1, #MON_DATA_HELD_ITEM
    bl set_value
.endif
.if FLAGS & F_MET_LEVEL_0
    movs r0, #0
    movs r1, #MON_DATA_MET_LEVEL
    bl set_value
.endif
.if FLAGS & F_JAPANESE
    movs r0, #LANGUAGE_JAPANESE
    movs r1, #MON_DATA_LANGUAGE
    bl set_value
    adr r2, jp_name
    movs r1, #MON_DATA_NICKNAME
    bl set_data
.endif
.if ENGLISH                             @ in every language's game, as PKHeX knows these;
    movs r0, #LANGUAGE_ENGLISH          @ the name the game gave is the English one
    movs r1, #MON_DATA_LANGUAGE         @ unless en_names has it
    bl set_value
.if EN_NAMES
    adr r0, mons
    subs r2, r4, r0                     @ the entry's offset: a name is as long as an entry
    cmp r2, #EN_NAMES * ENTRY_SIZE
    bcs 1f
    adr r0, en_names
    adds r2, r0, r2
    movs r1, #MON_DATA_NICKNAME
    bl set_data
1:
.endif
.endif
.if FLAGS & F_EGG
    ldrh r0, [r4]
    movs r1, #SPECIES_INFO_SIZE
    muls r0, r1
    ldr r1, p_species_info
    adds r0, r0, r1
    ldrb r0, [r0, #EGG_CYCLES]
    movs r1, #MON_DATA_FRIENDSHIP
    bl set_value
    movs r0, #1
    movs r1, #MON_DATA_IS_EGG
    bl set_value
.endif
.if FLAGS & F_FATEFUL
    movs r0, #1
    movs r1, #MON_DATA_FATEFUL
    bl set_value
.endif
.if FLAGS & F_NATIONAL_RIBBON
    movs r0, #1
    movs r1, #MON_DATA_NATIONAL_RIBBON
    bl set_value
.endif
    ldr r6, [sp, #IVS]
    movs r7, #MON_DATA_HP_IV
4:  movs r0, #31                        @ each IV, five bits apiece from HP
    ands r0, r6
    lsrs r6, r6, #5
    movs r1, r7
    bl set_value
    adds r7, #1
    cmp r7, #MON_DATA_HP_IV + 6
    bne 4b
    movs r6, #0
5:  lsls r1, r6, #1                     @ each move
    adds r1, r4, r1
    ldrh r1, [r1, #2]
    movs r2, r6
    ldr r0, p_mon
    ldr r7, p_set_move_slot
    bl call_r7
    adds r6, #1
    cmp r6, #4
    bne 5b
    ldr r0, p_mon
    ldr r7, p_calculate_stats
    bl call_r7
    ldr r6, p_party_count
    ldrb r7, [r6]
    ldr r0, p_mon
    cmp r7, #PARTY_SIZE
    bcc 6f
    ldr r3, p_send_to_pc
    bl call_r3
    b 8f
6:  movs r1, #MON_SIZE                  @ into the next party slot
    muls r1, r7
    ldr r2, p_party
    adds r1, r1, r2
    movs r2, #MON_SIZE - 4
7:  ldr r3, [r0, r2]
    str r3, [r1, r2]
    subs r2, #4
    bpl 7b
    adds r7, #1
    strb r7, [r6]
    movs r0, #MON_GIVEN_TO_PARTY
8:  ldr r1, p_var_result
    strh r0, [r1]
    cmp r0, #MON_CANT_GIVE
    beq 9f
.if (FLAGS & F_EGG) == 0
    ldrh r0, [r4]
    ldr r3, p_species_to_national
    bl call_r3
    movs r6, r0
    movs r1, #FLAG_SET_SEEN
    ldr r7, p_pokedex_flag
    bl call_r7
    movs r0, r6
    movs r1, #FLAG_SET_CAUGHT
    bl call_r7
.endif
9:  add sp, #FRAME
    pop {r4, r5, r6, r7, pc}

@ r0 = the next 16 bits of the GBA LCG, whose state is r6.
rand16:
    ldr r0, p_lcg_mul
    muls r0, r6
    ldr r1, p_lcg_add
    adds r6, r0, r1
    lsrs r0, r6, #16
    bx lr

@ SetMonData on the Pokémon being made: field r1, the value r0, or data at r2.
set_value:
    str r0, [sp, #VALUE]                @ in give_mon's frame
    add r2, sp, #VALUE
set_data:
    ldr r0, p_mon
    ldr r3, p_set_mon_data
call_r3:
    bx r3

call_r7:
    bx r7

.if MONS > 1
offer:
    ldr r0, p_var_8004
    ldrh r1, [r0]
    movs r2, #0
    cmp r1, #MONS
    bcs 1f                              @ past the last
    movs r2, #ENTRY_SIZE
    muls r1, r2
    adr r2, mons
    ldrh r1, [r2, r1]
    strh r1, [r0, #4]                   @ VAR_0x8006
    movs r2, #1
1:  ldr r0, p_var_result
    strh r2, [r0]
    bx lr
.endif

    .align 2
p_var_result:          .word SPECIAL_VAR_RESULT
p_random:              .word RANDOM
.if FLAGS & (F_CHANNEL | F_CXD)
p_lcg_mul:             .word 0x000343FD
p_lcg_add:             .word 0x00269EC3
.else
p_lcg_mul:             .word 0x41C64E6D
p_lcg_add:             .word 0x00006073
.endif
.if FLAGS & F_CHANNEL
p_third:               .word 0x547A
.endif
.if FLAGS & F_EGG
p_species_info:        .word SPECIES_INFO
.endif
p_tid:                 .word TID
p_mon:                 .word ENEMY_PARTY
p_create_mon:          .word CREATE_MON
p_set_mon_data:        .word SET_MON_DATA
p_set_move_slot:       .word SET_MON_MOVE_SLOT
p_calculate_stats:     .word CALCULATE_STATS
p_party:               .word PARTY
p_party_count:         .word PARTY_COUNT
p_send_to_pc:          .word SEND_MON_TO_PC
p_species_to_national: .word SPECIES_TO_NATIONAL
p_pokedex_flag:        .word GET_SET_POKEDEX_FLAG
.if MONS > 1
p_var_8004:            .word SPECIAL_VAR_8004
.endif
.if FLAGS & F_MYSTRY_SEEDS
p_released_seed:       .word MYSTRY_RELEASED_SEED
.endif

@ ---- the OT name (7 characters, EOS), then the Pokémon: species and moves.
@ COLOSSEUM's Japanese gifts end their names with zeros after the terminator,
@ as the GameCube writes them.
ot_name:
.if EVENT == EVENT_WISHMKR_JIRACHI
    .byte 0xD1, 0xC3, 0xCD, 0xC2, 0xC7, 0xC5, 0xCC, 0xFF           @ WISHMKR
mons:
    .hword 409, 273, 93, 156, 0         @ JIRACHI: WISH, CONFUSION, REST
.endif
.if EVENT >= EVENT_10_ANIV_CELEBI && EVENT <= EVENT_10_ANIV_JOHTO_HOENN
    .byte 0xA2, 0xA1, 0x00, 0xBB, 0xC8, 0xC3, 0xD0, 0xFF           @ 10 ANIV
mons:
.endif
.if EVENT == EVENT_10_ANIV_CELEBI
    .hword 251, 246, 248, 226, 195      @ CELEBI: ANCIENTPOWER, FUTURE SIGHT, BATON PASS, PERISH SONG
.endif
.if EVENT == EVENT_10_ANIV_KANTO
    .hword 1, 230, 74, 76, 235          @ BULBASAUR: SWEET SCENT, GROWTH, SOLARBEAM, SYNTHESIS
    .hword 6, 17, 163, 82, 83           @ CHARIZARD: WING ATTACK, SLASH, DRAGON RAGE, FIRE SPIN
    .hword 9, 182, 240, 130, 56         @ BLASTOISE: PROTECT, RAIN DANCE, SKULL BASH, HYDRO PUMP
    .hword 25, 85, 87, 113, 19          @ PIKACHU: THUNDERBOLT, THUNDER, LIGHT SCREEN, FLY
    .hword 65, 248, 347, 94, 271        @ ALAKAZAM: FUTURE SIGHT, CALM MIND, PSYCHIC, TRICK
    .hword 149, 97, 219, 17, 200        @ DRAGONITE: AGILITY, SAFEGUARD, WING ATTACK, OUTRAGE
    .align 2
en_names:
    .byte 0xBC, 0xCF, 0xC6, 0xBC, 0xBB, 0xCD, 0xBB, 0xCF, 0xCC, 0xFF   @ BULBASAUR
    .byte 0xBD, 0xC2, 0xBB, 0xCC, 0xC3, 0xD4, 0xBB, 0xCC, 0xBE, 0xFF   @ CHARIZARD
    .byte 0xBC, 0xC6, 0xBB, 0xCD, 0xCE, 0xC9, 0xC3, 0xCD, 0xBF, 0xFF   @ BLASTOISE
    .byte 0xCA, 0xC3, 0xC5, 0xBB, 0xBD, 0xC2, 0xCF, 0xFF, 0xFF, 0xFF   @ PIKACHU
    .byte 0xBB, 0xC6, 0xBB, 0xC5, 0xBB, 0xD4, 0xBB, 0xC7, 0xFF, 0xFF   @ ALAKAZAM
    .byte 0xBE, 0xCC, 0xBB, 0xC1, 0xC9, 0xC8, 0xC3, 0xCE, 0xBF, 0xFF   @ DRAGONITE
.endif
.if EVENT == EVENT_10_ANIV_LEGENDS
    .hword 144, 97, 170, 58, 115        @ ARTICUNO: AGILITY, MIND READER, ICE BEAM, REFLECT
    .hword 145, 97, 197, 65, 268        @ ZAPDOS: AGILITY, DETECT, DRILL PECK, CHARGE
    .hword 146, 97, 203, 53, 219        @ MOLTRES: AGILITY, ENDURE, FLAMETHROWER, SAFEGUARD
    .hword 243, 98, 209, 115, 242       @ RAIKOU: QUICK ATTACK, SPARK, REFLECT, CRUNCH
    .hword 244, 83, 23, 53, 207         @ ENTEI: FIRE SPIN, STOMP, FLAMETHROWER, SWAGGER
    .hword 245, 16, 62, 54, 243         @ SUICUNE: GUST, AURORA BEAM, MIST, MIRROR COAT
    .hword 407, 296, 94, 105, 204       @ LATIAS: MIST BALL, PSYCHIC, RECOVER, CHARM
    .hword 408, 295, 94, 105, 349       @ LATIOS: LUSTER PURGE, PSYCHIC, RECOVER, DRAGON DANCE
    .align 2
en_names:
    .byte 0xBB, 0xCC, 0xCE, 0xC3, 0xBD, 0xCF, 0xC8, 0xC9, 0xFF, 0xFF   @ ARTICUNO
    .byte 0xD4, 0xBB, 0xCA, 0xBE, 0xC9, 0xCD, 0xFF, 0xFF, 0xFF, 0xFF   @ ZAPDOS
    .byte 0xC7, 0xC9, 0xC6, 0xCE, 0xCC, 0xBF, 0xCD, 0xFF, 0xFF, 0xFF   @ MOLTRES
.if JAPANESE
    .byte 0xCC, 0xBB, 0xC3, 0xC5, 0xC9, 0xCF, 0xFF, 0xFF, 0xFF, 0xFF   @ RAIKOU
    .byte 0xBF, 0xC8, 0xCE, 0xBF, 0xC3, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF   @ ENTEI
    .byte 0xCD, 0xCF, 0xC3, 0xBD, 0xCF, 0xC8, 0xBF, 0xFF, 0xFF, 0xFF   @ SUICUNE
    .byte 0xC6, 0xBB, 0xCE, 0xC3, 0xBB, 0xCD, 0xFF, 0xFF, 0xFF, 0xFF   @ LATIAS
    .byte 0xC6, 0xBB, 0xCE, 0xC3, 0xC9, 0xCD, 0xFF, 0xFF, 0xFF, 0xFF   @ LATIOS
.endif
.endif
.if EVENT == EVENT_10_ANIV_JOHTO_HOENN
    .hword 157, 98, 172, 129, 53        @ TYPHLOSION: QUICK ATTACK, FLAME WHEEL, SWIFT, FLAMETHROWER
    .hword 196, 60, 244, 94, 234        @ ESPEON: PSYBEAM, PSYCH UP, PSYCHIC, MORNING SUN
    .hword 197, 185, 212, 103, 236      @ UMBREON: FAINT ATTACK, MEAN LOOK, SCREECH, MOONLIGHT
    .hword 248, 37, 184, 242, 89        @ TYRANITAR: THRASH, SCARY FACE, CRUNCH, EARTHQUAKE
    .hword 282, 299, 163, 119, 327      @ BLAZIKEN: BLAZE KICK, SLASH, MIRROR MOVE, SKY UPPERCUT
    .hword 376, 104, 163, 248, 195      @ ABSOL: DOUBLE TEAM, SLASH, FUTURE SIGHT, PERISH SONG
    .align 2
en_names:
    .byte 0xCE, 0xD3, 0xCA, 0xC2, 0xC6, 0xC9, 0xCD, 0xC3, 0xC9, 0xC8   @ TYPHLOSION
    .byte 0xBF, 0xCD, 0xCA, 0xBF, 0xC9, 0xC8, 0xFF, 0xFF, 0xFF, 0xFF   @ ESPEON
    .byte 0xCF, 0xC7, 0xBC, 0xCC, 0xBF, 0xC9, 0xC8, 0xFF, 0xFF, 0xFF   @ UMBREON
    .byte 0xCE, 0xD3, 0xCC, 0xBB, 0xC8, 0xC3, 0xCE, 0xBB, 0xCC, 0xFF   @ TYRANITAR
    .byte 0xBC, 0xC6, 0xBB, 0xD4, 0xC3, 0xC5, 0xBF, 0xC8, 0xFF, 0xFF   @ BLAZIKEN
.if JAPANESE
    .byte 0xBB, 0xBC, 0xCD, 0xC9, 0xC6, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF   @ ABSOL
.endif
.endif
.if EVENT == EVENT_DOEL_DEOXYS
    .byte 0xBE, 0xC9, 0xBF, 0xC6, 0xFF, 0xFF, 0xFF, 0xFF           @ DOEL
.endif
.if EVENT == EVENT_SPACE_C_DEOXYS
    .byte 0xCD, 0xCA, 0xBB, 0xBD, 0xBF, 0x00, 0xBD, 0xFF           @ SPACE C
.endif
.if EVENT == EVENT_DOEL_DEOXYS || EVENT == EVENT_SPACE_C_DEOXYS
mons:
    .hword 410, 322, 105, 354, 63       @ DEOXYS: COSMIC POWER, RECOVER, PSYCHO BOOST, HYPER BEAM
.endif
.if EVENT == EVENT_AURA_MEW
    .byte 0xBB, 0xE9, 0xE6, 0xD5, 0xFF, 0xFF, 0xFF, 0xFF           @ Aura
.endif
.if EVENT == EVENT_MYSTRY_MEW
    .byte 0xC7, 0xD3, 0xCD, 0xCE, 0xCC, 0xD3, 0xFF, 0xFF           @ MYSTRY
.endif
.if EVENT == EVENT_AURA_MEW || EVENT == EVENT_MYSTRY_MEW
mons:
    .hword 151, 1, 144, 0, 0            @ MEW: POUND, TRANSFORM
.endif
.if EVENT == EVENT_MYSTRY_MEW
    .align 2
mystry_seeds:
    .hword 0x0652, 0x0932, 0x0C13, 0x0D43, 0x0EEE, 0x1263, 0x13C9, 0x1614, 0x1C09, 0x1EA5
    .hword 0x20BF, 0x2389, 0x2939, 0x302D, 0x306E, 0x34F3, 0x45F3, 0x46CE, 0x4A0D, 0x4B63
    .hword 0x4C79, 0x508E, 0x50AB, 0x5240, 0x5327, 0x56BA, 0x56CC, 0x5841, 0x5A60, 0x5BC1
    .hword 0x5E2B, 0x5EF3, 0x6065, 0x643F, 0x6457, 0x67A3, 0x6944, 0x6E06, 0x6E62, 0x7667
    .hword 0x77EF, 0x78D2, 0x8655, 0x8A92, 0x8B48, 0x93D0, 0x941D, 0x95A0, 0x967D, 0x9690
    .hword 0x9C37, 0x9C40, 0x9D9C, 0x9DE4, 0x9E86, 0xA153, 0xA443, 0xA8AC, 0xAC08, 0xAFFB
    .hword 0xB1F2, 0xB831, 0xBE96, 0xC2D4, 0xC385, 0xC6CE, 0xC92C, 0xC953, 0xC962, 0xCC43
    .hword 0xCD47, 0xCD96, 0xD1E4, 0xDFED, 0xE62C, 0xE6CC, 0xE90A, 0xE95D, 0xE991, 0xEBB2
    .hword 0xEE7F, 0xEE9F, 0xEFC8, 0xF0E4, 0xFE4E, 0xFE9D
.endif
.if EVENT == EVENT_ROCKS_METANG
    .byte 0xCC, 0xC9, 0xBD, 0xC5, 0xCD, 0xFF, 0xFF, 0xFF           @ ROCKS
mons:
    .hword 399, 36, 93, 232, 287        @ METANG: TAKE DOWN, CONFUSION, METAL CLAW, REFRESH
.endif
.if EVENT == EVENT_CHANNEL_JIRACHI
    .byte 0xBD, 0xC2, 0xBB, 0xC8, 0xC8, 0xBF, 0xC6, 0xFF           @ CHANNEL
mons:
    .hword 409, 273, 93, 156, 0         @ JIRACHI: WISH, CONFUSION, REST
.endif
.if EVENT == EVENT_BOX_EGGS
    .byte 0xBB, 0xD4, 0xCF, 0xCD, 0xBB, 0xFF, 0xFF, 0xFF           @ ＡＺＵＳＡ, until it hatches
mons:
    .hword 358, 64, 45, 206, 0          @ SWABLU: PECK, GROWL, FALSE SWIPE
    .hword 288, 33, 45, 39, 245         @ ZIGZAGOON: TACKLE, GROWL, TAIL WHIP, EXTREMESPEED
    .hword 315, 45, 33, 39, 6           @ SKITTY: GROWL, TACKLE, TAIL WHIP, PAY DAY
    .hword 172, 84, 204, 57, 0          @ PICHU: THUNDERSHOCK, CHARM, SURF
    .align 2
jp_name:
    .byte 0x60, 0x6F, 0x8B, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF   @ タマゴ
.endif
.if EVENT == EVENT_COLOSSEUM_PIKACHU
    .byte 0x5A, 0x7B, 0x5C, 0x51, 0x71, 0xFF, 0x00, 0x00           @ コロシアム
mons:
    .hword 25, 84, 45, 39, 86           @ PIKACHU: THUNDERSHOCK, GROWL, TAIL WHIP, THUNDER WAVE
    .align 2
jp_name:
    .byte 0x9C, 0x56, 0x61, 0x85, 0x53, 0xFF, 0x00, 0x00, 0x00, 0x00   @ ピカチュウ
.endif
.if EVENT == EVENT_AGETO_CELEBI
    .byte 0x51, 0x8A, 0x64, 0xFF, 0x00, 0x00, 0x00, 0x00           @ アゲト
mons:
    .hword 251, 93, 105, 215, 219       @ CELEBI: CONFUSION, RECOVER, HEAL BELL, SAFEGUARD
    .align 2
jp_name:
    .byte 0x5E, 0x7A, 0x97, 0x80, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00   @ セレビィ
.endif
.if EVENT == EVENT_MATTLE_HO_OH
    .byte 0xC7, 0xBB, 0xCE, 0xCE, 0xC6, 0xBF, 0xFF, 0xFF           @ MATTLE
mons:
    .hword 250, 105, 126, 241, 129      @ HO-OH: RECOVER, FIRE BLAST, SUNNY DAY, SWIFT
.endif
.if JAPANESE && ENGLISH && MONS == 1    @ the one Pokémon's English name
    .align 2
en_names:
.if EVENT == EVENT_WISHMKR_JIRACHI || EVENT == EVENT_CHANNEL_JIRACHI
    .byte 0xC4, 0xC3, 0xCC, 0xBB, 0xBD, 0xC2, 0xC3, 0xFF, 0xFF, 0xFF   @ JIRACHI
.endif
.if EVENT == EVENT_10_ANIV_CELEBI
    .byte 0xBD, 0xBF, 0xC6, 0xBF, 0xBC, 0xC3, 0xFF, 0xFF, 0xFF, 0xFF   @ CELEBI
.endif
.if EVENT == EVENT_DOEL_DEOXYS || EVENT == EVENT_SPACE_C_DEOXYS
    .byte 0xBE, 0xBF, 0xC9, 0xD2, 0xD3, 0xCD, 0xFF, 0xFF, 0xFF, 0xFF   @ DEOXYS
.endif
.if EVENT == EVENT_AURA_MEW || EVENT == EVENT_MYSTRY_MEW
    .byte 0xC7, 0xBF, 0xD1, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF   @ MEW
.endif
.if EVENT == EVENT_ROCKS_METANG
    .byte 0xC7, 0xBF, 0xCE, 0xBB, 0xC8, 0xC1, 0xFF, 0xFF, 0xFF, 0xFF   @ METANG
.endif
.if EVENT == EVENT_MATTLE_HO_OH
    .byte 0xC2, 0xC9, 0xAE, 0xC9, 0xC2, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF   @ HO-OH
.endif
.endif
    .align 2

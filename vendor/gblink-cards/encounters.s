@ No Wild Encounters & Repel. `choice_menu` offers which wild Pokémon stay
@ away: all of them, the weaker ones, or none; the script does the rest.
@
@ Parameters (--defsym): those of menu.inc; data.inc holds the choices.

    .syntax unified
    .thumb
    .text
    .align 2

    .set MENU_LISTS, 1
    .equ MENU_WIDTH, 10                 @ tiles, for WEAKER ONES

choice_menu:
    adr r0, choice_items
    movs r1, #3
    movs r2, #MENU_WIDTH
    b list_menu

    .align 2
    .include "data.inc"
    .include "menu.inc"

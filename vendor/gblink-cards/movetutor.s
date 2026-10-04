@ Move Relearner & Deleter: the game's own specials do the work; the script
@ only needs to move itself, since their menus return to the field.
@
@ Parameters (--defsym): those of relocate.inc.

    .syntax unified
    .thumb
    .text
    .align 2

    .include "relocate.inc"

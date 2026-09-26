@ A resident V-blank hook that stops wild encounters while it is installed: it stores 1 every frame
@ into sWildEncountersDisabled, which StandardWildEncounter tests first and returns FALSE on
@ [src/wild_encounter.c:360; French FireRed 0x08086528, the flag its literal at 0x080865B0]. That
@ is every grass, water and roamer encounter a step can start; fishing and Sweet Scent take their own
@ paths and still work. A soft reset removes the hook, and the game's own writes take over again.

    .thumb
    .align 2
    .global noencounter_hook
noencounter_hook:
    push    {lr}
    ldr     r0, p_flag
    mov     r1, #1
    strb    r1, [r0]
    ldr     r3, p_original
    bl      .Lcall                  @ the game's VBlankIntr
    pop     {r0}
    bx      r0

.Lcall:
    bx      r3

    .align 2
    .global p_original, p_flag
p_original:
    .word   0x0800071D              @ patched by the installer: the handler this one replaced
p_flag:
    .word   0x020386D8              @ sWildEncountersDisabled (French FireRed)

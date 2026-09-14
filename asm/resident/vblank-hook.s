@ A resident V-blank hook: counts frames, optionally issues a Sloop syscall for a bounded burst of
@ frames, and tail-branches to the handler it replaced.
@
@ gIntrTable entry 4 holds VBlankIntr [docs/frlg_rom.md, The per-frame hook]. IntrMain enters a
@ handler in SYS mode with lr = intr_return and the handler free to clobber r0-r3 [crt0.s:jump_intr],
@ so this preserves nothing except lr, which the tail branch needs.
@
@ WHY THE BURST. A syscall issued once is invisible to anyone watching the wrapper from outside: the
@ handler runs for a few microseconds inside one frame and is gone. Repeating it makes the number a
@ recurring signature that a host-side breakpoint sweep can catch and read registers from. It is
@ bounded rather than permanent because a syscall on every V-blank forever is a change to how the
@ console runs, and the measurement only needs a few seconds of it.
@
@ CALLING A REGISTER IN THUMB. `bl` takes a label, so the call goes through a local `bx` stub, which
@ is what sets lr for the thunk's own `bx lr`. That destroys the lr this handler was entered with, so
@ it is saved to a word in the blob first and put back afterwards.

    .thumb
    .align 2
    .global vblank_hook
vblank_hook:
    ldr     r0, p_counter
    ldr     r1, [r0]
    add     r1, #1
    str     r1, [r0]

    ldr     r2, p_burst
    cmp     r1, r2
    bhi     .Ldone                  @ past the burst, or burst is 0: nothing but the count
    ldr     r0, p_lrsave
    mov     r2, lr
    str     r2, [r0]                @ the return into IntrMain, kept across the call
    ldr     r3, p_thunk
    bl      .Lcall
    ldr     r0, p_lrsave
    ldr     r2, [r0]
    mov     lr, r2

.Ldone:
    ldr     r0, p_original
    bx      r0                      @ tail branch: lr points at intr_return again

.Lcall:
    bx      r3

    .align 2
    .global p_counter, p_original, p_burst, p_thunk, p_lrsave
p_counter:
    .word   0x0203FC40              @ patched: the frame counter
p_original:
    .word   0x0800071D              @ patched: the handler this one replaced, THUMB
p_burst:
    .word   0                       @ patched: fire on frames 1..N, 0 for never
p_thunk:
    .word   0x0203FF40              @ patched: `swi N ; bx lr`, THUMB
p_lrsave:
    .word   0x0203FF3C              @ patched: one word of scratch

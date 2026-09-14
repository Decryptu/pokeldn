@ RESIDENT PAYLOAD: the thing that lives in the save and is copied into EWRAM by a loader.
@
@ The ceiling this exists to remove. What a RAM script keeps in the save is a SCRIPT, and the script
@ rebuilds its code every time it runs, so the code can never be larger than a script body carries:
@ 162 bytes staged at six script bytes each, or about 755 appended after the last command. A payload
@ parked in `filler_B20` is bounded by save space instead, and measured on an emulator nothing
@ touches that region: not the `save-write` that puts it there, not ordinary play, not a later Wonder
@ Card, and sixteen bytes left there survived ten save generations with nobody protecting them
@ [docs/frlg_rom.md, Reading the save].
@
@ SHAPE. The host builds the blob; this source is its head.
@
@     +0x000  magic           the loader checks this before it branches
@     +0x004  entry           where the loader branches, Thumb
@     ...     installer
@     ...     the V-blank hook, copied here from asm/resident/vblank-hook.s by the builder
@     ...     filler, whatever the host puts there
@     size-4  checksum        the sum of the filler as words
@
@ WHY THE CHECKSUM. A branch that lands proves the jump and says nothing about the size. The blob
@ travels through `save-write`, flash, a save slot rotation and a copy loop, and a short or truncated
@ arrival would run perfectly well and be wrong. This sums the filler and refuses to install unless
@ the sum matches, which is the same argument `asm/field/mon-seek-far.s` makes about a RAM script
@ body [docs/frlg_rng.md, Proving the size rather than the jump].
@
@ IDEMPOTENT. Installing twice would point the hook's tail branch at the hook, which spins forever
@ inside an interrupt handler and freezes the console with no menu. The table is read first and the
@ installer returns having written nothing if it already names the hook.

    .thumb
    .align 2
    .global _start, p_magic, p_hook, p_table_entry, p_counter
    .global p_filler_start, p_filler_end, p_checksum_at
_start:
p_magic:
    .word   0x444C4B50              @ "PKLD" little-endian; patched by the builder

entry:
    push    {r4, r5, r6, r7, lr}

    @ the filler must sum to what the builder recorded, or nothing here is trustworthy
    ldr     r0, p_filler_start
    ldr     r1, p_filler_end
    mov     r2, #0
.Lsum:
    cmp     r0, r1
    bhs     .Lsummed
    ldr     r3, [r0]
    add     r2, r2, r3
    add     r0, #4
    b       .Lsum
.Lsummed:
    ldr     r0, p_checksum_at
    ldr     r3, [r0]
    cmp     r2, r3
    bne     .Ldone                  @ short, truncated or corrupted: install nothing

    ldr     r0, p_table_entry       @ &gIntrTable[4]
    ldr     r1, [r0]                @ whatever handles V-blank now
    ldr     r2, p_hook              @ our hook, Thumb bit set
    cmp     r1, r2
    beq     .Ldone                  @ already installed

    ldr     r3, p_hook_original_at  @ where the hook keeps its tail target
    str     r1, [r3]                @ the handler it tail-branches to
    ldr     r4, p_counter
    mov     r5, #0
    str     r5, [r4]                @ the counter starts at zero
    str     r2, [r0]                @ install, last

.Ldone:
    @ A one-shot probe of the Sloop syscall boundary, run after the hook is in and skipped when
    @ p_probe_enable is zero. The markers go down BEFORE the call, because a syscall that does not
    @ return freezes the overworld and the only thing left to read is what was written first.
    ldr     r0, p_probe_count
    cmp     r0, #0
    beq     .Lout
    ldr     r6, p_probe_out
    ldr     r0, p_probe_mark1
    str     r0, [r6, #0]            @ reached the probe
    mov     r0, #0
    str     r0, [r6, #8]            @ cleared, so a stale "returned" is not read as this run's
    ldr     r4, p_probe_first       @ the syscall number being attempted
    mov     r5, #0                  @ how many have been done
.Lsweep:
    str     r4, [r6, #4]            @ written BEFORE the call, so a hang names itself
    @ Patch the thunk's own `swi N`. EWRAM, no instruction cache on this CPU, so the next call
    @ through it uses the number just written.
    ldr     r7, p_probe_thunk
    mov     r0, r7
    sub     r0, #1                  @ the thunk's address, Thumb bit cleared
    ldr     r1, p_probe_swi_base
    add     r1, r1, r4              @ 0xDF00 | N
    strh    r1, [r0]
    @ r0 = a0 + step * index, so one deployment can walk the selector `swi 0x52` takes from r0
    @ rather than needing two save-writes per value. step 0 leaves every pass identical.
    ldr     r0, p_probe_a0
    ldr     r1, p_probe_a0_step
    mov     r2, r5
    mul     r2, r1
    add     r0, r0, r2
    ldr     r1, p_probe_a1
    ldr     r2, p_probe_a2
    ldr     r3, p_probe_a3
    bl      .Lcall
    @ Four words per number, after the seven header words. r0..r3 are the results, so the address is
    @ built in r7, which the top of the loop reloads anyway.
    @
    @ p_probe_store 0 skips the store entirely. The result region holds ten passes and no more, which
    @ caps a sweep at ten whenever the answer is read out of guest memory. It is not always read from
    @ there: a breakpoint on the wrapper's side reads the object and the call target directly, and
    @ then the guest only has to ISSUE the calls. With the store off a sweep can walk all 256
    @ selectors in one deployment.
    ldr     r7, p_probe_store
    cmp     r7, #0
    beq     .Lnostore
    lsl     r7, r5, #4
    add     r7, r7, r6
    str     r0, [r7, #28]
    str     r1, [r7, #32]
    str     r2, [r7, #36]
    str     r3, [r7, #40]
.Lnostore:
    @ The number steps by p_probe_num_step, which is 1 for a sweep of syscall numbers and 0 for a
    @ sweep of one syscall's selector in r0. It was a hardcoded `add r4, #1`, so a run that stepped
    @ r0 stepped the number underneath it and every row of the table was a different syscall. Four
    @ rows read as four selectors of `swi 0x52` were 0x52, 0x53, 0x54 and 0x55.
    ldr     r0, p_probe_num_step
    add     r4, r4, r0
    add     r5, #1
    ldr     r0, p_probe_count
    cmp     r5, r0
    blo     .Lsweep
    ldr     r0, p_probe_mark2
    str     r0, [r6, #8]            @ every number in the range returned
.Lout:
    pop     {r4, r5, r6, r7, pc}

.Lcall:
    bx      r7                      @ the thunk: swi N ; bx lr, patched above

    .align 2
    .global p_hook_original_at
p_hook:         .word 0x0203FC20    @ patched: the hook inside this blob, Thumb bit set
p_hook_original_at: .word 0x0203FC30 @ patched from the hook's own symbol table, never computed here
p_table_entry:  .word 0x03002730    @ gIntrTable[4]
p_counter:      .word 0x0203FFC0    @ patched: the frame counter
p_filler_start: .word 0x0203FC40    @ patched
p_filler_end:   .word 0x0203FFBC    @ patched
p_checksum_at:  .word 0x0203FFBC    @ patched
    .global p_probe_enable, p_probe_out, p_probe_thunk
    .global p_probe_mark1, p_probe_mark2, p_probe_a0, p_probe_a1, p_probe_a2, p_probe_a3
    .global p_probe_first, p_probe_count, p_probe_swi_base, p_probe_num_step, p_probe_store
p_probe_first:  .word 0x40          @ patched: the first syscall number of the sweep
p_probe_count:  .word 0             @ patched: how many, or 0 to run no probe
p_probe_num_step: .word 1           @ patched: added to the syscall number once per pass, 0 to pin it
p_probe_store:  .word 1             @ patched: 0 skips the result store, so a sweep is not capped at ten
p_probe_swi_base: .word 0x0000DF00  @ the Thumb `swi` opcode, the number goes in the low byte
p_probe_out:    .word 0x0203FE00    @ patched: seven words of answer, inside the blob's filler
p_probe_thunk:  .word 0x0203FE80    @ patched: the thunk, Thumb bit set
p_probe_mark1:  .word 0xB0B00001
p_probe_mark2:  .word 0xB0B00002
    .global p_probe_a0_step
p_probe_a0_step: .word 0            @ patched: added to r0 once per pass
p_probe_a0:     .word 0             @ patched
p_probe_a1:     .word 0             @ patched
p_probe_a2:     .word 0             @ patched
p_probe_a3:     .word 0             @ patched

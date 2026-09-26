@ The head of a resident hook carried in the save: the loader bound to an NPC copies filler_B20 to a
@ staging area and tail-branches here, and this runs the install-resident image that follows, which
@ copies the hook to 0x0203FC00 and installs it [docs/frlg_rom.md, A resident hook kept in the save].
@
@     +0x00  magic     "PKRS"; the older save payload's loader wants "PKLD" and runs nothing here
@     +0x04  entry     THUMB, reached as staging + 5 with lr at ScrCmd_callnative's caller
@     p_length         bytes summed, from +0 up to the checksum
@     p_answer         where the installer writes the handler it found, or 0xBAD0BAD0
@     p_image          the install-resident image: ARM entry, THUMB body, then the hook
@     +length          checksum: the sum of every word before it
@
@ The checksum is what says the whole blob arrived through save-write, flash, a slot rotation and the
@ loader's copy; a short arrival would branch perfectly well. Nothing is installed unless it matches.

    .thumb
    .align 2
    .global _start, p_magic, p_length, p_answer, p_image
_start:
p_magic:
    .word   0x53524B50              @ "PKRS" little-endian

entry:
    push    {r4, lr}
    sub     r4, r0, #5              @ the loader branched to staging + 5
    ldr     r1, p_length
    mov     r2, #0
    mov     r3, #0
.Lsum:
    ldr     r0, [r4, r3]
    add     r2, r2, r0
    add     r3, #4
    cmp     r3, r1
    blo     .Lsum
    ldr     r0, [r4, r1]            @ the checksum
    cmp     r0, r2
    bne     .Lout                   @ not all of it arrived: install nothing
    mov     r0, r4
    add     r0, #(p_answer - _start)
    mov     r3, r4
    add     r3, #(p_image - _start)
    bl      .Lbx                    @ into the installer's ARM entry; it returns with bx
.Lout:
    pop     {r4}
    pop     {r0}
    bx      r0

.Lbx:
    bx      r3

    .align 2
p_length:
    .word   0                       @ patched by the builder
p_answer:
    .word   0
p_image:

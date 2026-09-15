@ CLI_RUN_BUFFER_SCRIPT payload: read a save sector out of flash, change one field, write it back.
@
@ The difference from flash-write, and the reason this exists: a sector COMPOSED from live RAM is not
@ what the game's save routine writes. The routine serializes at save time, so a RAM snapshot is
@ missing whatever it would have serialized, and two such fields have already been found by breaking
@ something visible - the encryption key, re-rolled on load [decomp:src/load_save.c:126], and the
@ 420-byte saved map view at SaveBlock2 +0x898, which is zero in RAM. There is no reason to believe
@ those are the last two.
@
@ So nothing is reconstructed here. The sector already on flash was written by a real save; this
@ reads it, changes the bytes it means to change, and writes it back. Every other byte is the byte
@ the save routine put there, and an unenumerated field cannot be wrong because it is never rebuilt.
@
@ Two sectors, both read-modify-written:
@   A  the target id's sector: patch `patch_len` bytes at `patch_off`, recompute the checksum over
@      the id's own chunk, set the counter.
@   B  the sector at band position 13: set the counter ONLY. That position is the one whose counter
@      GetSaveValidStatus reports for the whole slot [docs/frlg_rom.md]. +0xFFC is outside the summed
@      data area, so no checksum work is needed and the sector stays valid.
@
@ Neither write brings a key in from RAM, so the key and the ciphertext beside it are never separated.
@
@ ReadFlash(u16 sectorNum, u32 offset, void *dest, u32 size) at 0x081E0EEC switches bank itself
@ [decomp:src/agb_flash.c]. It also sets REG_WAITCNT's SRAM wait states to 8 cycles and never
@ restores them; that is the one piece of shared hardware state this touches while the RFU link is
@ live, and it is the first thing to suspect if the link misbehaves.
@
@ THE STATUS WORD SEPARATES THE TWO NEW MECHANISMS. A run that fails must say whether the read or the
@ write was at fault, so the witness is a LIVE value rather than a constant: the counter sector B
@ already held. A payload that read nothing could not invent it.
@
@   both signatures 0x08012025 seen   ->  physA << 24 | physB << 16 | (sector B's old counter & 0xFFFF)
@   either signature missing          ->  0xBAD00000 | physA << 8 | physB
@
@ Image, offsets from _start, patched by buffer_script.build_flash_patch:
@   0x000  b .Lcode
@   0x004  readflash   THUMB pointer to ReadFlash
@   0x008  scratch     a 4 KB EWRAM buffer, above this payload's own image
@   0x00C  lws_addr    &gLastWrittenSector (u16)
@   0x010  sc_addr     &gSaveCounter (u32)
@   0x014  target_id   the save id to patch
@   0x018  patch_off   byte offset of the field inside the sector data
@   0x01C  patch_len   how many bytes
@   0x020  chunk       the id's chunk size, what the checksum covers
@   0x024  bias        added to gSaveCounter for both counters
@   0x028  signature   0x08012025, what a real sector must carry
@   0x02C  RESULT      physA
@   0x030  RESULT      physB
@   0x034  RESULT      sector B's counter as read, before we changed it
@   0x038  RESULT      0 if both signatures were seen, else 1
@   0x03C  patch       up to 16 bytes of replacement field
@   0x04C  thunk       swi 0x48 ; bx lr, THUMB

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lreadflash: .word 0             @ 0x004
.Lscratch:   .word 0             @ 0x008
.Llws:       .word 0             @ 0x00C
.Lsc:        .word 0             @ 0x010
.Lid:        .word 0             @ 0x014
.Lpatchoff:  .word 0             @ 0x018
.Lpatchlen:  .word 0             @ 0x01C
.Lchunk:     .word 0             @ 0x020
.Lbias:      .word 0             @ 0x024
.Lsig:       .word 0             @ 0x028
.LphysA:     .word 0             @ 0x02C RESULT
.LphysB:     .word 0             @ 0x030 RESULT
.LoldB:      .word 0             @ 0x034 RESULT
.Lbadsig:    .word 0             @ 0x038 RESULT
.Lpatch:     .space 16           @ 0x03C
.Lthunk:     .word 0x4770DF48    @ 0x04C swi 0x48 ; bx lr

.Lcode:
    sub     ip, pc, #8
    push    {r0, r4, r5, r6, r7, lr}    @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4                  @ r4 = _start

    @ physA = ((lws + id) % 14) + 14 * (sc & 1);  physB = 13 + 14 * (sc & 1)
    ldr     r0, [r4, #0x0C]
    ldrh    r5, [r0]                    @ gLastWrittenSector
    ldr     r0, [r4, #0x10]
    ldr     r6, [r0]                    @ gSaveCounter
    ldr     r1, [r4, #0x14]
    add     r0, r5, r1
    cmp     r0, #14
    subhs   r0, r0, #14
    tst     r6, #1
    addne   r0, r0, #14
    str     r0, [r4, #0x2C]             @ physA
    mov     r1, #13
    tst     r6, #1
    addne   r1, r1, #14
    str     r1, [r4, #0x30]             @ physB

    @ --- A: read, patch, re-checksum, set counter, write ------------------------------------------
    ldr     r0, [r4, #0x2C]
    bl      .Lread                      @ r7 = scratch
    ldr     r0, [r4, #0x18]             @ patch_off
    add     r0, r7, r0
    add     r1, r4, #0x3C               @ the replacement bytes
    ldr     r2, [r4, #0x1C]             @ patch_len
.Lpatchloop:
    cmp     r2, #0
    beq     .Lpatched
    ldrb    r3, [r1], #1
    strb    r3, [r0], #1
    sub     r2, r2, #1
    b       .Lpatchloop
.Lpatched:
    @ CalculateChecksum over the id's own chunk, stored at +0xFF6.
    ldr     r3, [r4, #0x20]             @ chunk
    mov     r0, #0
    mov     r2, #0
.Lsum:
    cmp     r2, r3
    bhs     .Lsummed
    ldr     r1, [r7, r2]
    add     r0, r0, r1
    add     r2, r2, #4
    b       .Lsum
.Lsummed:
    mov     r1, r0, lsr #16
    add     r0, r0, r1
    ldr     r2, .Lfooter
    add     r2, r7, r2                  @ &scratch[0xFF4]
    strh    r0, [r2, #0x02]             @ checksum
    ldr     r0, [r4, #0x24]
    add     r0, r6, r0                  @ gSaveCounter + bias
    str     r0, [r2, #0x08]             @ counter at +0xFFC
    ldr     r0, [r4, #0x2C]
    bl      .Lwrite

    @ --- B: read, set counter only, write ---------------------------------------------------------
    ldr     r0, [r4, #0x30]
    bl      .Lread
    ldr     r2, .Lfooter
    add     r2, r7, r2
    ldr     r0, [r2, #0x08]
    str     r0, [r4, #0x34]             @ the counter it already held: the witness
    ldr     r0, [r4, #0x24]
    add     r0, r6, r0
    str     r0, [r2, #0x08]             @ only these four bytes change; the checksum still stands
    ldr     r0, [r4, #0x30]
    bl      .Lwrite

    @ --- the status word --------------------------------------------------------------------------
    ldr     r0, [r4, #0x38]
    cmp     r0, #0
    beq     .Lgood
    ldr     r0, .Lbadmark
    ldr     r1, [r4, #0x2C]
    orr     r0, r0, r1, lsl #8
    ldr     r1, [r4, #0x30]
    orr     r0, r0, r1
    b       .Lreport
.Lgood:
    ldr     r0, [r4, #0x2C]
    mov     r0, r0, lsl #24
    ldr     r1, [r4, #0x30]
    orr     r0, r0, r1, lsl #16
    ldr     r1, [r4, #0x34]
    mov     r1, r1, lsl #16
    orr     r0, r0, r1, lsr #16
.Lreport:
    ldr     r3, [sp]
    str     r0, [r3, #0x00]
    mov     r0, #1
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

@ ReadFlash(sector, 0, scratch, 0x1000), then check the signature. Leaves scratch in r7.
.Lread:
    push    {r0, lr}
    ldr     r7, [r4, #0x08]             @ scratch
    mov     r1, #0
    mov     r2, r7
    mov     r3, #0x1000
    ldr     ip, [r4, #0x04]             @ ReadFlash, THUMB
    mov     lr, pc
    bx      ip
    ldr     r1, .Lfooter
    add     r1, r7, r1
    ldr     r0, [r1, #0x04]             @ +0xFF8, the signature
    ldr     r1, [r4, #0x28]
    cmp     r0, r1
    movne   r0, #1
    strne   r0, [r4, #0x38]             @ a missing signature is remembered, not fatal
    pop     {r0, lr}
    bx      lr

@ swi 0x48 with r0 = sector, r1 = scratch, through the THUMB thunk in our own image.
.Lwrite:
    push    {lr}
    mov     r1, r7
    add     ip, r4, #0x4C
    orr     ip, ip, #1
    mov     lr, pc
    bx      ip
    pop     {lr}
    bx      lr

.Lcodeoff:  .word .Lcode - _start
.Lfooter:   .word 0xFF4
.Lbadmark:  .word 0xBAD00000

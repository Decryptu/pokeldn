@ CLI_RUN_BUFFER_SCRIPT payload: read a save sector out of flash, change one field, write it back.
@
@ Why read rather than compose: a sector built from a live save block is not what the game's save
@ routine writes. The routine serializes at save time, so a RAM snapshot is missing whatever it
@ would have serialized, and two such fields were found by breaking something visible - the
@ encryption key, re-rolled on load [decomp:src/load_save.c:126], and the 420-byte saved map view at
@ SaveBlock2 +0x898, which is zero in RAM. Nothing here is reconstructed: every byte this does not
@ deliberately change is the byte a real save put there, so a field nobody has thought of cannot be
@ wrong.
@
@ TWO SHAPES ONTO ONE CHIP, and this payload uses both.
@   reading  the CPU sees a 64 KiB window at 0x0E000000. A 128 KiB flash reaches it as two banks, so
@            sector N is bank N / 16 at 0x0E000000 + (N % 16) * 0x1000, and an address above the
@            window ALIASES rather than faulting.
@   writing  swi 0x48 takes a linear sector number 0..31 and handles the whole 128 KiB itself
@            [docs/frlg_rom.md, the flash sector path].
@ Both are measured. Mixing them up reads one sector and writes another.
@
@ The bank select is the game's own four stores [decomp:src/agb_flash.c SwitchFlashBank, 0x081E0C74,
@ seven instructions, no loop and no REG_WAITCNT], inlined rather than called so that this payload
@ makes no ROM call at all: nothing executed off the stack, REG_WAITCNT untouched, and no ROM
@ function running while the link is live.
@
@ Reads are byte-wide. The flash bus is 8 bits and a wider load does not return more flash bytes.
@
@ Two sectors, both read-modify-written:
@   A  the target id's sector: patch `patch_len` bytes at `patch_off`, recompute the checksum over
@      the id's own chunk, set the counter.
@   B  the sector at band position 13: set the counter ONLY. That position is the one whose counter
@      GetSaveValidStatus reports for the whole slot. +0xFFC is outside the summed data area, so the
@      sector stays valid with no checksum work.
@
@ Neither write brings a key in from RAM, so the key and the ciphertext beside it are never separated.
@
@ THE STATUS WORD SEPARATES THE MECHANISMS. The witness is a LIVE value, sector B's existing counter,
@ which a payload that read nothing could not invent; a constant could be produced without reading.
@
@   both signatures seen  ->  physA << 24 | physB << 16 | (sector B's OLD counter & 0xFFFF)
@   a signature missing   ->  0xBAD00000 | physA << 8 | physB
@
@ Image, offsets from _start, patched by buffer_script.build_flash_patch:
@   0x000  b .Lcode
@   0x004  scratch     a 4 KB EWRAM buffer, above this payload's own image
@   0x008  lws_addr    &gLastWrittenSector (u16)
@   0x00C  sc_addr     &gSaveCounter (u32)
@   0x010  target_id   the save id to patch
@   0x014  patch_off   byte offset of the field inside the sector data
@   0x018  patch_len   how many bytes
@   0x01C  chunk       the id's chunk size, what the checksum covers
@   0x020  bias        added to gSaveCounter for both counters
@   0x024  signature   0x08012025, what a real sector must carry
@   0x028  RESULT      physA
@   0x02C  RESULT      physB
@   0x030  RESULT      sector B's counter as read, before we changed it
@   0x034  RESULT      0 if both signatures were seen, else 1
@   0x038  patch       up to 16 bytes of replacement field
@   0x048  thunk       swi 0x48 ; bx lr, THUMB

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lscratch:   .word 0             @ 0x004
.Llws:       .word 0             @ 0x008
.Lsc:        .word 0             @ 0x00C
.Lid:        .word 0             @ 0x010
.Lpatchoff:  .word 0             @ 0x014
.Lpatchlen:  .word 0             @ 0x018
.Lchunk:     .word 0             @ 0x01C
.Lbias:      .word 0             @ 0x020
.Lsig:       .word 0             @ 0x024
.LphysA:     .word 0             @ 0x028 RESULT
.LphysB:     .word 0             @ 0x02C RESULT
.LoldB:      .word 0             @ 0x030 RESULT
.Lbadsig:    .word 0             @ 0x034 RESULT
.Lpatch:     .space 16           @ 0x038
.Lthunk:     .word 0x4770DF48    @ 0x048 swi 0x48 ; bx lr

.Lcode:
    sub     ip, pc, #8
    push    {r0, r4, r5, r6, r7, lr}    @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4                  @ r4 = _start

    @ physA = ((lws + id) % 14) + 14 * (sc & 1);  physB = 13 + 14 * (sc & 1)
    ldr     r0, [r4, #0x08]
    ldrh    r5, [r0]                    @ gLastWrittenSector
    ldr     r0, [r4, #0x0C]
    ldr     r6, [r0]                    @ gSaveCounter
    ldr     r1, [r4, #0x10]
    add     r0, r5, r1
    cmp     r0, #14
    subhs   r0, r0, #14
    tst     r6, #1
    addne   r0, r0, #14
    str     r0, [r4, #0x28]             @ physA
    mov     r1, #13
    tst     r6, #1
    addne   r1, r1, #14
    str     r1, [r4, #0x2C]             @ physB

    @ --- A: read, patch, re-checksum, set counter, write ------------------------------------------
    ldr     r0, [r4, #0x28]
    bl      .Lread                      @ r7 = scratch, holding the sector
    ldr     r0, [r4, #0x14]             @ patch_off
    add     r0, r7, r0
    add     r1, r4, #0x38               @ the replacement bytes
    ldr     r2, [r4, #0x18]             @ patch_len
.Lpatchloop:
    cmp     r2, #0
    beq     .Lpatched
    ldrb    r3, [r1], #1
    strb    r3, [r0], #1
    sub     r2, r2, #1
    b       .Lpatchloop
.Lpatched:
    @ CalculateChecksum over the id's own chunk, stored at +0xFF6.
    ldr     r3, [r4, #0x1C]             @ chunk
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
    ldr     r0, [r4, #0x20]
    add     r0, r6, r0                  @ gSaveCounter + bias
    str     r0, [r2, #0x08]             @ counter at +0xFFC
    ldr     r0, [r4, #0x28]
    bl      .Lwrite

    @ --- B: read, set counter only, write ---------------------------------------------------------
    ldr     r0, [r4, #0x2C]
    bl      .Lread
    ldr     r2, .Lfooter
    add     r2, r7, r2
    ldr     r0, [r2, #0x08]
    str     r0, [r4, #0x30]             @ the counter it already held: the witness
    ldr     r0, [r4, #0x20]
    add     r0, r6, r0
    str     r0, [r2, #0x08]             @ only these four bytes change; the checksum still stands
    ldr     r0, [r4, #0x2C]
    bl      .Lwrite

    @ --- the status word --------------------------------------------------------------------------
    ldr     r0, [r4, #0x34]
    cmp     r0, #0
    beq     .Lgood
    ldr     r0, .Lbadmark
    ldr     r1, [r4, #0x28]
    orr     r0, r0, r1, lsl #8
    ldr     r1, [r4, #0x2C]
    orr     r0, r0, r1
    b       .Lreport
.Lgood:
    ldr     r0, [r4, #0x28]
    mov     r0, r0, lsl #24
    ldr     r1, [r4, #0x2C]
    orr     r0, r0, r1, lsl #16
    ldr     r1, [r4, #0x30]
    mov     r1, r1, lsl #16
    orr     r0, r0, r1, lsr #16
.Lreport:
    ldr     r3, [sp]
    str     r0, [r3, #0x00]
    mov     r0, #1
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

@ Select the bank the sector in r0 lives in, byte-copy its 4 KB out of the window into the scratch,
@ and note a missing signature. Leaves the scratch in r7 for the caller.
.Lread:
    push    {r0, r1, r2, r3, r5, lr}
    ldr     r7, [r4, #0x04]             @ scratch, kept for the caller
    mov     r5, r0                      @ the physical sector
    ldr     r0, .Lcmd5555
    mov     r1, #0xAA
    strb    r1, [r0]
    ldr     r2, .Lcmd2AAA
    mov     r1, #0x55
    strb    r1, [r2]
    mov     r1, #0xB0
    strb    r1, [r0]
    ldr     r2, .Lwindow
    mov     r1, r5, lsr #4              @ bank = sector / 16
    strb    r1, [r2]
    and     r1, r5, #15
    add     r0, r2, r1, lsl #12         @ window = base + (sector % 16) * 0x1000
    ldr     r2, .Lsectorsize
    mov     r1, #0
.Lrcopy:
    cmp     r1, r2
    bhs     .Lrdone
    ldrb    r3, [r0, r1]                @ byte-wide: the flash bus is 8 bits
    strb    r3, [r7, r1]
    add     r1, r1, #1
    b       .Lrcopy
.Lrdone:
    ldr     r1, .Lfooter
    add     r1, r7, r1
    ldr     r0, [r1, #0x04]             @ +0xFF8, the signature
    ldr     r1, [r4, #0x24]
    cmp     r0, r1
    movne   r0, #1
    strne   r0, [r4, #0x34]             @ remembered, not fatal
    pop     {r0, r1, r2, r3, r5, lr}
    bx      lr

@ swi 0x48 with r0 = the LINEAR sector number and r1 = the scratch.
.Lwrite:
    push    {lr}
    mov     r1, r7
    add     ip, r4, #0x48
    orr     ip, ip, #1
    mov     lr, pc
    bx      ip
    pop     {lr}
    bx      lr

.Lcodeoff:     .word .Lcode - _start
.Lfooter:      .word 0xFF4
.Lcmd5555:     .word 0x0E005555
.Lcmd2AAA:     .word 0x0E002AAA
.Lwindow:      .word 0x0E000000
.Lsectorsize:  .word 0x1000
.Lbadmark:     .word 0xBAD00000

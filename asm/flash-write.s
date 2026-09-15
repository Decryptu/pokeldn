@ CLI_RUN_BUFFER_SCRIPT payload: compose a sector in EWRAM and write it straight to flash with
@ swi 0x48, the Sloop raw sector write [docs/frlg_rom.md, the Sloop syscall boundary].
@
@ swi 0x48 copies 0x1000 bytes from r1 into flash sector r0 (dest 0x0E000000 + r0*0x1000), bypassing
@ the game's save code, and returns no register. The source is filled here, on the console, so the
@ bytes are ours: word[i] = fillbase + i*fillstep over `words` words, into a scratch inside
@ gDecompressionBuffer (0x4000 at 0x0201C000), above this payload's own image.
@
@ With `footer` set it composes a WELL-FORMED save sector instead of a raw pattern: the data area is
@ filled, everything from there to the footer is zeroed the way the game zeroes its buffer, the
@ checksum is computed here over the whole 3968-byte data area, and id, checksum, signature and
@ counter are laid down at +0xFF4, +0xFF6, +0xFF8, +0xFFC [decomp:include/save.h struct SaveSector].
@
@ The checksum is the game's own [decomp:src/save.c CalculateChecksum]: sum the data as u32 words,
@ then (sum >> 16) + sum, truncated to u16. Summing the full 3968 is always right because the buffer
@ is zero past the data and zeros add nothing, so one constant serves every sector id.
@
@ It is reported back in *param so the arithmetic is checked over the link before anything is dumped:
@ the host computes the same checksum and asks for it with --expect.
@
@ Client_RunBufferScript calls us as u32 (*)(u32 *param, SaveBlock2*, SaveBlock1*) once a frame until
@ we return 1 [decomp:src/mystery_gift_client.c:276]. r0 = &client->param on entry. The swi goes
@ through a THUMB thunk in our own image, the path asm/resident/save-payload.s uses, because the
@ tested boundary is a THUMB `swi`.
@
@ Image, offsets from _start, patched by buffer_script.build_flash_write:
@   0x000  b .Lcode
@   0x004  sector      r0 for the swi: the 4 KB flash sector index
@   0x008  source      r1 for the swi: the EWRAM scratch base
@   0x00C  fillbase    word[0] of the data pattern
@   0x010  fillstep    added to the value each word
@   0x014  words       how many words of pattern, at least 1
@   0x018  footer      0 = write the pattern raw; else compose a valid sector footer
@   0x01C  id          the sector id, at +0xFF4
@   0x020  counter     the save counter, at +0xFFC (replaced when deriving)
@   0x024  signature   0x08012025, at +0xFF8
@   0x028  derive_lws  &gLastWrittenSector (u16), or 0 to use the literal sector
@   0x02C  derive_sc   &gSaveCounter (u32)
@   0x030  bias        added to gSaveCounter for the footer: 0 stays in its own band
@   0x034  RESULT      the syscall's r0 return, echoed
@   0x038  RESULT      source[words-1] after the write
@   0x03C  RESULT      the checksum this payload computed
@   0x040  RESULT      the physical sector actually written
@   0x044  RESULT      the sector id actually written
@   0x048  position    0..13 to derive the id FROM the position instead, or -1 to use the literal id
@   0x04C  thunk       swi N ; bx lr, THUMB; N patched into the low byte
@
@ DERIVING THE ID FROM THE POSITION. GetSaveValidStatus assigns the slot's counter on every valid
@ sector in physical order, so after the loop it holds the LAST valid sector's counter, not a
@ consensus [decomp:src/save.c]. A sector that is meant to change which slot the loader picks must
@ therefore sit at position 13 of its band, and the id that belongs there is (position - lws) % 14.
@ That is the inverse of the usual derivation and the reason for `position`.
@
@ DERIVING THE POSITION ON THE CONSOLE. The save rotates: a sector id lands at
@ (gLastWrittenSector + id) % 14 + 14 * (gSaveCounter % 2) [decomp:src/save.c:174]. Both variables
@ advance on every save, and a gift session saves at the end, so a position computed when the payload
@ was built is stale by the time it runs. Reading them here makes the write address the sector the id
@ actually occupies. The chosen sector is reported back, so a null result can be told from a
@ mis-aimed one.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lsector:   .word 0                 @ 0x004
.Lsource:   .word 0                 @ 0x008
.Lfillbase: .word 0                 @ 0x00C
.Lfillstep: .word 0                 @ 0x010
.Lwords:    .word 0                 @ 0x014
.Lfooter:   .word 0                 @ 0x018
.Lid:       .word 0                 @ 0x01C
.Lcounter:  .word 0                 @ 0x020
.Lsig:      .word 0                 @ 0x024
.Ldlws:     .word 0                 @ 0x028
.Ldsc:      .word 0                 @ 0x02C
.Lbias:     .word 0                 @ 0x030
.Lret:      .word 0                 @ 0x034  RESULT: syscall r0
.Lreadback: .word 0                 @ 0x038  RESULT: source[words-1]
.Lcksum:    .word 0                 @ 0x03C  RESULT: the checksum computed here
.Lphys:     .word 0                 @ 0x040  RESULT: the physical sector written
.Lidout:    .word 0                 @ 0x044  RESULT: the id written
.Lpos:      .word 0xFFFFFFFF        @ 0x048  band position to aim at, or -1 for "use the literal id"
.Lthunk:    .word 0x4770DF00        @ 0x04C  swi 0x00 ; bx lr (THUMB); builder ors in the number

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    push    {r0, r4, r5, r6, r7, lr}    @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start; r4-r7 survive the call

    @ The data pattern: word[i] = fillbase + i*fillstep, i in 0..words-1.
    ldr     r5, [r4, #0x08]         @ source base
    ldr     r6, [r4, #0x14]         @ words
    ldr     r0, [r4, #0x0C]         @ running value = fillbase
    ldr     r1, [r4, #0x10]         @ fillstep
    mov     r2, #0                  @ index
.Lfill:
    cmp     r2, r6
    bhs     .Lfilled
    str     r0, [r5, r2, lsl #2]
    add     r0, r0, r1
    add     r2, r2, #1
    b       .Lfill
.Lfilled:

    @ Where does this go? Either the literal sector, or derived from the game's own save globals.
    ldr     r7, [r4, #0x28]         @ &gLastWrittenSector, 0 = use the literal
    cmp     r7, #0
    beq     .Lliteral
    ldrh    r0, [r7]                @ gLastWrittenSector
    ldr     r2, [r4, #0x48]         @ position, or -1
    cmp     r2, #0
    blt     .Lbyid
    @ id = (position - lws) % 14, and the position is where it goes.
    sub     r1, r2, r0
    cmp     r1, #0
    addlt   r1, r1, #14             @ % 14 over a difference of two 0..13 values
    str     r1, [r4, #0x1C]         @ the id the footer will carry
    mov     r0, r2                  @ the position itself
    b       .Lband
.Lbyid:
    ldr     r1, [r4, #0x1C]         @ id
    add     r0, r0, r1
    cmp     r0, #14
    subhs   r0, r0, #14             @ % 14; both operands are 0..13 so one subtract is enough
.Lband:
    ldr     r7, [r4, #0x2C]         @ &gSaveCounter
    ldr     r1, [r7]                @ gSaveCounter
    tst     r1, #1
    addne   r0, r0, #14             @ + 14 * (counter % 2): the band it is the active half of
    str     r0, [r4, #0x04]         @ the sector the swi will use
    ldr     r2, [r4, #0x30]         @ bias
    add     r1, r1, r2
    str     r1, [r4, #0x20]         @ the counter the footer will carry
    b       .Lplaced
.Lliteral:
    ldr     r0, [r4, #0x04]
.Lplaced:
    str     r0, [r4, #0x40]         @ RESULT: where it actually went
    ldr     r1, [r4, #0x1C]
    str     r1, [r4, #0x44]         @ RESULT: the id it used, literal or derived

    ldr     r0, [r4, #0x18]         @ footer?
    cmp     r0, #0
    beq     .Lwrite

    @ Zero from where the pattern stopped up to the footer, as the game zeroes its whole buffer
    @ before filling it [decomp:src/save.c:182].
    ldr     r3, .Lfooter_off        @ 0xFF4
    mov     r0, #0
    mov     r2, r6, lsl #2          @ byte offset the pattern reached
.Lzero:
    cmp     r2, r3
    bhs     .Lzeroed
    str     r0, [r5, r2]
    add     r2, r2, #4
    b       .Lzero
.Lzeroed:

    @ CalculateChecksum over the whole data area: sum as u32 words, then (sum >> 16) + sum.
    ldr     r3, .Ldata_bytes        @ 0xF80
    mov     r0, #0                  @ running sum
    mov     r2, #0                  @ byte offset
.Lsum:
    cmp     r2, r3
    bhs     .Lsummed
    ldr     r1, [r5, r2]
    add     r0, r0, r1
    add     r2, r2, #4
    b       .Lsum
.Lsummed:
    mov     r1, r0, lsr #16
    add     r0, r0, r1
    mov     r0, r0, lsl #16
    mov     r0, r0, lsr #16         @ truncated to u16
    str     r0, [r4, #0x3C]         @ RESULT: the checksum, reported in *param below

    @ The footer: id +0xFF4, checksum +0xFF6, signature +0xFF8, counter +0xFFC.
    ldr     r3, .Lfooter_off
    add     r3, r5, r3              @ &source[0xFF4]
    ldr     r1, [r4, #0x1C]
    strh    r1, [r3, #0x00]         @ id
    strh    r0, [r3, #0x02]         @ checksum
    ldr     r1, [r4, #0x24]
    str     r1, [r3, #0x04]         @ signature
    ldr     r1, [r4, #0x20]
    str     r1, [r3, #0x08]         @ counter

.Lwrite:
    @ swi N with r0 = sector, r1 = source, through our THUMB thunk.
    ldr     r0, [r4, #0x04]         @ sector
    mov     r1, r5                  @ source
    add     r7, r4, #0x4C           @ the thunk word
    orr     r7, r7, #1              @ THUMB bit
    mov     lr, pc                  @ ARM return, bit 0 clear
    bx      r7
    str     r0, [r4, #0x34]         @ the syscall's r0 return

    @ source[words-1] read back: the fill reached the end and the write left it intact.
    sub     r2, r6, #1
    ldr     r0, [r5, r2, lsl #2]
    str     r0, [r4, #0x38]

    @ *param: the checksum when we composed a sector, else the read-back. The checksum is the
    @ claim under test, so it is what the host checks over the link.
    ldr     r1, [r4, #0x18]
    cmp     r1, #0
    beq     .Lreport
    ldr     r0, [r4, #0x3C]         @ the checksum, low half
    ldr     r1, [r4, #0x40]
    orr     r0, r0, r1, lsl #16     @ the physical sector, high half
.Lreport:
    ldr     r3, [sp]                @ &client->param
    str     r0, [r3, #0x00]

    mov     r0, #1                  @ done, one frame
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
.Lfooter_off:
    .word   0xFF4                   @ where the footer starts inside the sector
.Ldata_bytes:
    .word   0xF80                   @ SECTOR_DATA_SIZE, what the checksum covers

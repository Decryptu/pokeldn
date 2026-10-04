@ turbo without the overlay and the RNG history: the same passes, gates and budget in fewer bytes,
@ so it chains with other hooks inside the resident area [docs/frlg_rom.md, Several hooks at once].
    .set    TURBO_LITE, 1
    .include "turbo.s"

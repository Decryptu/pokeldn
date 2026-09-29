"""Inside the console: its own code and data, every address read off the hardware.

`rom_map` holds measured addresses; `thumb` and `decomp_source` read a dump as code; `scrcmd*`,
`*_names` name the function tables; native code is `buffer_script` and `native_script`; the RNG
is `lcg`, `rng_script` and `rng_countdown`. `docs/frlg_rom.md`, `docs/frlg_rng.md`.
"""

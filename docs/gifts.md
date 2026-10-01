---
title: Mystery Gift files
---
# Mystery Gift files

A `.pokegift` file stores a complete Mystery Gift distribution for FireRed/LeafGreen or
Sword/Shield, or an FRLG ARM console payload, with its target game and native records.

## Desktop app

Games, Mystery Gift has the same Gift file control for both supported games. Browse opens a
`.pokegift` file and shows its name, game and cartridge variants. Sword/Shield also opens `.wc8`
files. Selecting a file hides the built-in gift fields and sends the file's data. Clearing the
path restores those fields. Existing Sword/Shield settings containing a `.wc8` path still work.

FRLG, Console code has a Payload file control and Save payload file button. They import a shared
ARM payload or export the selected built-in action, including its response settings. Imported
code files belong on Console code; cards and news belong on Mystery Gift.

Save gift file writes the selected built-in gift or imported file as `.pokegift`. It needs no board
or Switch keys. FRLG exports include every supported cartridge variant that the selected options
can build. The console's game code chooses the variant during the gift handshake; a cartridge
absent from the file is refused before gift data is sent.

The app does not modify gift files on import. Files remain at the chosen paths.

## Command line

Both gift launchers accept `--gift-file FILE`. Sword/Shield retains `--record` as an alias.
`--export-gift FILE` saves the chosen gift and exits before using the radio.

```bash
./.venv/bin/python bin/frlg_mg_host.py --gift celebi --export-gift celebi.pokegift
./.venv/bin/python bin/frlg_mg_host.py --news berry --export-gift news.pokegift
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 --export-gift pikachu.pokegift
./.venv/bin/python -m pokeldn.gifts inspect celebi.pokegift
```

An FRLG gift file defines the card flag ID, scripts, questionnaire and refusal message together.
Payload overrides such as `--flag-id`, `--questionnaire` and `--hunt-*` are refused with it.
Radio, trainer identity and cartridge-selection options remain session settings.

### Console code

Export a built-in payload with its configured bytes and response settings:

```bash
./.venv/bin/python bin/frlg_mg_host.py --buffer-script save-dump --dump-size 64 \
  --export-gift save-dump.pokegift
```

Authors can package their own raw ARM code with an explicit cartridge target:

```bash
arm-none-eabi-as -march=armv4t -mcpu=arm7tdmi -o payload.o payload.s
arm-none-eabi-objcopy -O binary -j .text payload.o payload.bin
./.venv/bin/python -m pokeldn.gifts import --game frlg --code payload.bin \
  --build BPRF --name "Custom payload" --expect 66 -o custom.pokegift
```

A minimal `payload.s` writes 66 into the response parameter and completes in one call:

```asm
.syntax unified
.arm
.text
.global _start
_start:
    mov r3, #66
    str r3, [r0]
    mov r0, #1
    bx lr
```

The code must be position independent ARMv4T, word aligned, and at most 1024 bytes. The console
passes `r0 = &param`, `r1 = gSaveBlock2Ptr` and `r2 = gSaveBlock1Ptr`; it calls the payload once per
frame until it returns 1. See [Console code](frlg_rom.md) for the execution contract. Without
`--expect`, any returned parameter is accepted. A payload that repoints the response to a byte
buffer uses `--dump-size N` when packaged.

Share the `.pokegift` file. The recipient imports it on FRLG, Console code, or launches with
`--gift-file custom.pokegift`. `--dump-file PATH` chooses where the host writes a returned dump.
Cartridge variants are enforced before code is sent. Packaging verifies structure and size;
authors must execute new payloads offline with `buffer_script.emulate_repeating` before a live
run. A file hash does not prove that native code returns or leaves the save intact.

### Native formats

The converter imports Sword/Shield WC8 records and paired FRLG files used by
`pokemon-gen3-mysterygift-tool`. FRLG import requires the cartridge code the script targets:
`BPRF`, `BPGF`, `BPRE` or `BPGE`. It cannot infer a script's target from its bytes.

```bash
./.venv/bin/python -m pokeldn.gifts import --game swsh --record event.wc8 -o event.pokegift
./.venv/bin/python -m pokeldn.gifts import --game frlg --card WonderCard.bin \
  --script Script.bin --build BPRF --name "Event gift" -o event.pokegift
./.venv/bin/python -m pokeldn.gifts export celebi.pokegift --build BPRF --out-dir native-gift
```

The FRLG pair contains a 336-byte card and a 1004-byte RAM-script structure. Import verifies both
CRCs and the script's unbound Mystery Gift header. The native pair cannot carry stamps, visiting
trainers, Mystery Event scripts, questionnaire gates or Wonder News. Export to that pair refuses
a distribution with those extras. `.pokegift` preserves them together.

## Version 2

The file is UTF-8 JSON with five required fields:

| Field | Value |
| --- | --- |
| `format` | `pokeldn.gift` |
| `version` | integer `2` |
| `game` | `frlg` or `swsh` |
| `name` | non-empty display name, up to 180 characters |
| `variants` | object mapping target codes to native data and options |

Each variant has `data` and `options` objects. A component in `data` has `hex`, the native bytes
encoded as hexadecimal, and `sha256`, their lowercase SHA-256 digest. JSON field order has no
meaning. Export sorts fields for deterministic files.

| Game | Variant keys | Data components | Options |
| --- | --- | --- | --- |
| FRLG gifts | supported cartridge codes | `card`, `ram_script`, `stamp`, `activation_script`, `install_activation_script`, `trainer`, `news`, `mevent` | `questionnaire`, `denied_message` |
| FRLG console code | supported cartridge codes | `buffer_code` | response settings below |
| Sword/Shield | `swsh` | `wc8` | none |

FRLG card variants carry the same flag ID and gift type. Wonder News and console code each travel
alone. Captures, keys, filesystem paths and session timing are outside this format.

An FRLG console-code variant has exactly one `buffer_code` component. Its optional response
settings are `buffer_expect` (a 32-bit unsigned integer or `trainer-id`), `buffer_dump_size`,
`buffer_dump_blocks`, `buffer_dump_address`, `buffer_dump_addresses` and `buffer_decode`.
Dump sizes are 1 to 1024 bytes per block, with at most 32 blocks; a scatter dump names one address
per block. Decoder names come from the existing response decoders. Dump output paths and local
ROM comparison paths remain on the host and are excluded from shared files.

Readers also accept version-1 files containing cards, news or WC8. Exports use version 2, which
adds console code and integer response settings. Version-1 readers reject version-2 files.

Readers reject unknown versions, fields and target codes, duplicate JSON fields, invalid hashes,
files larger than 256 KiB, invalid native sizes and invalid component combinations. FRLG validation
also checks card fields, trainer checksums and Mystery Event termination. Sword/Shield delivery
continues to require the shared PKHeX gift validation before opening the radio.

Hashes detect damaged bytes. They do not authenticate a distributor or prove that an imported
FRLG script is safe to execute. Native script import preserves instructions and requires an
explicit cartridge target.

## Implementation

`pokeldn.gifts` owns the envelope, validation dispatch, reader, writer and converter. Game-specific
codecs live in `pokeldn.frlg.gift.file` and `pokeldn.swsh.gift_file`. The shared app adapter calls
the launchers' own builders; the GUI uses one picker and export control for both games.

The FRLG file adapter builds the existing `MysteryGiftDistribution`, including its cartridge
selection and refusal path. The Sword/Shield adapter supplies the existing WC8 advertisement
builder. The wireless protocols and payload layouts are unchanged.

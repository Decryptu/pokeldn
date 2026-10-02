---
title: Mystery Gift files
---
# Mystery Gift files

A `.pokegift` file stores a complete Mystery Gift distribution for FireRed/LeafGreen or
Sword/Shield, or an FRLG ARM console payload, with its target game and native records.

## Desktop app

Games, Mystery Gift is one tool per game with three ways to choose the gift. The same builder serves
FireRed/LeafGreen and Sword/Shield; each game's module supplies its presets and its form
(`pokeldn/frlg/gift/builder.py`, `pokeldn/swsh/gift_builder.py`, bound in `pokeldn/app/gift_builder.py`).

| mode | what it sends |
|---|---|
| Use a preset | a built-in gift; FRLG Wonder Cards, Wonder News and console code go to the launcher as flags |
| Build your own | the form, compiled to `session/gifts/<tool>.pokegift` at Start and passed as `--gift-file` |
| Open a file | a shared `.pokegift`, or a `.wc8` on Sword/Shield |

Customize copies a preset into the form. A FRLG card preset offers it only when the form expresses
every step: unconditional stages of Pokemon, item, egg, wild battle and message steps, no event
script and no visiting trainer. Every Sword/Shield preset is a form state.

The FRLG form builds a Wonder Card, Wonder News or console code.

| part | contents |
|---|---|
| card | title, subtitle, four text lines, icon species, card id 1000 to 1019, received again, shareable |
| who hands it over | the delivery man in any Pokemon Center, Mom in the player's house, or the man in south Pallet Town |
| steps | Pokemon (species, level, held item, four moves), item and quantity, egg, wild battle, message |
| news | title, up to ten lines, news id |
| console code | ARM source or a prebuilt `.bin`, the cartridge it is built for, expected answer, bytes sent back |

Each step is its own delivery stage, so a full party or bag stops at that step and the player
retries only what is left. A person other than the delivery man holds the steps through an
`initramscript` binding; the card is not shown while it is bound. A bound script carries no
receipt flag: that person gives the steps every time until another gift replaces the binding. Species use the cartridge's
internal numbering (`pokeldn/frlg/save/species_names.py`). Card and news compile for all four
cartridges; console code compiles for all four or for the one chosen.

Console code is assembled with `arm-none-eabi-as` when it is on the PATH; without it, the form takes a
prebuilt `.bin`. Check offline runs the code once on the simulated console
(`pokeldn/frlg/rom/custom_code.py`) and shows the answer and the bytes. The same check runs before
Start and before a file is saved: code that faults, or never returns 1, is refused.

The Sword/Shield form builds a Pokemon, an egg, up to six bag items, or Battle Points, with a card
id. Each kind writes the bytes of a record a retail Sword listed and redeemed
([Sword and Shield Mystery Gift](swsh_gift.md#a-card-delivered-to-a-retail-console)); the
Pikachu preset is byte for byte the launcher's own default record.

Before you send lists what the console gets, when it runs, and the cartridges the gift serves. Save
gift file writes the selected gift as `.pokegift` with no board and no Switch keys. FRLG presets go
through the launcher's own builder, so the file holds every cartridge variant they build. The
console's game code chooses the variant during the gift handshake; a cartridge absent from the file
is refused before gift data is sent. A preset's card id is on the Advanced tab (`--flag-id`, 1000 to
1019).

The app does not modify gift files on import. Files remain at the chosen paths.

Opened files have been delivered to retail consoles: a French FireRed received a Celebi card file,
and a console code file that answered with the value it was built for; a Sword received a
Pikachu card file. Console code built in the form answered with the save's trainer id.

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

Share the `.pokegift` file. The recipient opens it on FRLG, Mystery Gift, or launches with
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

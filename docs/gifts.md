---
title: Mystery Gift files
---
# Mystery Gift files

A `.pokegift` file stores a complete Mystery Gift distribution for FireRed/LeafGreen or
Sword/Shield, or an FRLG ARM console payload, with its target game and native records.

## Desktop app

One builder serves both games (`pokeldn/app/gift_builder.py`; forms in
`pokeldn/frlg/gift/builder.py`, `pokeldn/swsh/gift_builder.py`).

| mode | what it sends |
|---|---|
| Use a preset | a built-in gift; FRLG Wonder Cards, Wonder News and console code go to the launcher as flags |
| Official events | a real Sword/Shield event card ([Official event cards](swsh_gift.md#official-event-cards)), compiled like a built gift |
| Build your own | the form, compiled to `session/gifts/<tool>.pokegift` at Start and passed as `--gift-file` |
| Open a file | a shared `.pokegift`, or a `.wc8` on Sword/Shield |

The FRLG Game boosts are resident hooks ([`install-resident`](frlg_rom.md#install-resident)), run
as one chain ([Several hooks at once](frlg_rom.md#several-hooks-at-once)) within 1024 bytes; settings
become `--resident-param` flags.

| boost | settings | parameters |
|---|---|---|
| Speed up the game (`turbo-lite`) | speed x1 to x4; overworld, battles or both; always on or while R, B or Select is held; faster text | `field` and `battle` = speed - 1, `budget=228` from x3, `hold`, `extra=4` |
| Walk through walls | R, B or Select | `hold` |
| Shiny countdown | the slow-down button; x2, x4 or x8 slower | `slow`, `slow_frames` 1, 3 or 7 |
| Shiny Mewtwo (`shiny-press`) | none | |
| No wild encounters, Lead's IVs on screen, Pokemon follower | none | |

L is not offered: only R's Help System toggle has a flag the hooks hold off. Save boosts for later
writes the set into `filler_B20` (`save-write --resident`) and installs it; a set over 876 bytes, and
the follower, always go through the save. Mom restores your boosts makes talking to Mom install the
saved set after any boot. Sending boosts again replaces the running set.

Read the save offers Trainer ID (TID) and Secret ID (SID), trainer details and play time, and the
last saved party's natures, IVs and EVs, leaving the save intact
([Reading the save](frlg_rom.md#reading-the-save)).

`.wc3` and `.wc8` files are read as binary even when they start with `{`. Customize copies a preset
into the form when the form can express it: every Sword/Shield preset, and FRLG cards made only of
unconditional form steps.

The FRLG form builds a Wonder Card, Wonder News or console code.

| part | contents |
|---|---|
| card | title, subtitle, four text lines, icon species, card id 1000 to 1019, received again, shareable |
| who hands it over | the delivery man in any Pokemon Center, Mom in the player's house, or the man in south Pallet Town |
| steps | Pokemon (species, level, held item, four moves), item and quantity, egg, wild battle, message |
| news | title, up to ten lines, news id |
| console code | ARM source or a prebuilt `.bin`, the cartridge it is built for, expected answer, bytes sent back |

Each step is its own delivery stage: a full party or bag stops there and a retry gives what is left.
Another person holds the steps through an `initramscript` binding, which hides the card and gives the
steps every time until replaced. Species use internal numbering
(`pokeldn/frlg/save/species_names.py`).

Console code needs `arm-none-eabi-as` (PATH, Homebrew or Arm's Windows folder), or a prebuilt `.bin`:

| system | command |
|---|---|
| macOS | `brew install arm-none-eabi-binutils` |
| Fedora | `sudo dnf install arm-none-eabi-binutils-cs` |
| Debian, Ubuntu and derivatives | `sudo apt install binutils-arm-none-eabi` |
| Windows | `winget install Arm.ArmGnuToolchain` |

Check offline runs the code on the simulated console (`pokeldn/frlg/rom/custom_code.py`), as do
Start and save, refusing code that faults or never returns 1.

The Sword/Shield form builds a Pokemon (Gigantamax optional), an egg, up to six items, outfits
([Clothing](swsh_gift.md#clothing), six pieces per gender), Battle Points or money, laid out as a
[record a retail Sword redeemed](swsh_gift.md#a-card-delivered-to-a-retail-console).

Save gift file writes a `.pokegift` with every cartridge variant, needing no board or keys. The
console's game code picks the variant; a cartridge absent from the file is refused before sending.

## Command line

Both gift launchers accept `--gift-file FILE`; on Sword/Shield `--record` is an alias.
`--export-gift FILE` saves the chosen gift and exits before using the radio.

```bash
./.venv/bin/python bin/frlg_mg_host.py --gift celebi --export-gift celebi.pokegift
./.venv/bin/python bin/frlg_mg_host.py --news berry --export-gift news.pokegift
./.venv/bin/python bin/swsh_gift_host.py --species 25 --level 25 --export-gift pikachu.pokegift
./.venv/bin/python -m pokeldn.gifts inspect celebi.pokegift
```

An FRLG gift file defines the card flag ID, scripts, questionnaire and refusal message together.
Payload overrides such as `--flag-id`, `--questionnaire` and `--hunt-*` are refused with it;
radio, trainer and cartridge-selection options still apply.

### Console code

A built-in payload exports with its response settings:

```bash
./.venv/bin/python bin/frlg_mg_host.py --buffer-script save-dump --dump-size 64 \
  --export-gift save-dump.pokegift
```

Raw ARM code is packaged with an explicit cartridge target:

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

The code is position-independent ARMv4T, word aligned, at most 1024 bytes, called once per frame
with `r0 = &param`, `r1 = gSaveBlock2Ptr`, `r2 = gSaveBlock1Ptr` until it returns 1
([Console code](frlg_rom.md)). Without `--expect` any answer is accepted; a byte-buffer response
needs `--dump-size N`.

The recipient opens the file in the FRLG Mystery Gift tool or passes `--gift-file`; `--dump-file
PATH` chooses where a returned dump goes. Packaging checks structure and size only: run a new
payload offline with `buffer_script.emulate_repeating` before a live run.

### Native formats

The converter imports WC8, FRLG `.wc3` and the card/script pairs of
`pokemon-gen3-mysterygift-tool`; `.wc3` and `.wc8` also open directly.

An FRLG script with no absolute address (only `vgoto`/`vmessage` relative to `setvaddress`
[scrcmd.c:171], items through `callstd`) serves every cartridge of its layout. One with `goto`,
`call`, `message`, `callnative` or another absolute pointer needs `--build`, and is refused when
opened directly.

```bash
./.venv/bin/python -m pokeldn.gifts import --game swsh --record event.wc8 -o event.pokegift
./.venv/bin/python -m pokeldn.gifts import --game frlg --wc3 "FL - Item AuroraTicket (FRE).wc3" -o aurora.pokegift
./.venv/bin/python -m pokeldn.gifts import --game frlg --card WonderCard.bin \
  --script Script.bin --name "Event gift" -o event.pokegift
./.venv/bin/python -m pokeldn.gifts export celebi.pokegift --build BPRF --out-dir native-gift
./.venv/bin/python -m pokeldn.gifts export celebi.pokegift --wc3 --build BPRJ --out-dir native-gift
./.venv/bin/python bin/frlg_mg_host.py --gift celebi --console-build BPRJ --export-gift celebi.wc3
```

Saving to a `.wc3` or `.wc8` path writes the native file. A `.wc3` holds one cartridge; differing
variants need `--build`. Its metadata is zero except the icon, which repeats the card's. Every
accepted international gallery file round-trips with identical card, script and icon bytes.

An international `.wc3` is 1420 bytes (`0x58C`):

| offset | size | content |
| --- | --- | --- |
| `0x000` | 336 | CRC16 of the card, 2 pad bytes, the 332-byte `struct WonderCard` |
| `0x150` | 80 | save-side card metadata; not read |
| `0x1A0` | 1004 | CRC16, 2 pad bytes, `struct RamScriptData` (magic 51, map group, map number, object id, 995-byte script), 1 pad byte |

The gallery files' script CRC covers 1000 bytes; the game's covers 999 [script.c:488]; import accepts
either. `--icon N` (Card icon in the app) sets `iconSpecies` (card offset 2), 0 to 411; 0 draws none
[mystery_gift_show_card.c:466].

Japanese `.wc3` files are 1252 bytes (`0x4E4`): the card structure is 164 bytes, its CRC wrapper
is 168 bytes, metadata starts at `0x0A8`, and the 1004-byte RAM-script structure starts at `0x0F8`.
Japanese files serve `BPRJ` and `BPGJ`, international ones the ten Latin cartridges. Flag ids outside
1000 to 1019 are refused [mystery_gift.c:241].

A native pair (card plus 1004-byte script) cannot carry stamps, visiting trainers, Mystery Event
scripts, questionnaire gates or Wonder News; export refuses them. Import checks both CRCs.

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
encoded as hexadecimal, and `sha256`, their lowercase SHA-256 digest. Export sorts fields.

| Game | Variant keys | Data components | Options |
| --- | --- | --- | --- |
| FRLG gifts | supported cartridge codes | `card`, `ram_script`, `stamp`, `activation_script`, `install_activation_script`, `trainer`, `news`, `mevent` | `questionnaire`, `denied_message` |
| FRLG console code | supported cartridge codes | `buffer_code`, `buffer_lead_1`.. | response settings below |
| Sword/Shield | `swsh` | `wc8` | none |

FRLG card variants share flag ID and gift type; news and console code travel alone. A console-code
variant has one `buffer_code` and up to eight `buffer_lead_N` run before it, numbered with no gap.
Response settings: `buffer_expect` (u32 or `trainer-id`), `buffer_dump_size` (1 to 1024),
`buffer_dump_blocks` (at most 32), `buffer_dump_address`, `buffer_dump_addresses` (one per block),
`buffer_decode`.

Readers accept version-1 files (cards, news, WC8); exports are version 2, which adds console code.
Version-1 readers reject version-2 files.

Readers reject unknown versions, fields and codes, duplicate fields, bad hashes, files over 256 KiB,
bad native sizes and bad combinations; FRLG also checks card fields, trainer checksums and Mystery
Event termination. Hashes detect damage only; they authenticate nobody.

## Implementation

`pokeldn.gifts` owns the envelope, validation dispatch, reader, writer and converter. Game-specific
codecs live in `pokeldn.frlg.gift.file` and `pokeldn.swsh.gift_file`. The FRLG adapter builds a
`MysteryGiftDistribution`, with its cartridge selection and refusal path; the Sword/Shield adapter
feeds the WC8 advertisement builder.

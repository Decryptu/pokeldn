---
title: Mystery Gift files
---
# Mystery Gift files

A `.pokegift` file stores a complete Mystery Gift distribution for FireRed/LeafGreen or
Sword/Shield, or an FRLG ARM console payload, with its target game and native records.

## Desktop app

Games, Mystery Gift is one tool per game with three ways to choose the gift, four on Sword/Shield.
One builder serves both games; each game's module supplies its presets and its form
(`pokeldn/frlg/gift/builder.py`, `pokeldn/swsh/gift_builder.py`, bound in `pokeldn/app/gift_builder.py`).

| mode | what it sends |
|---|---|
| Use a preset | a built-in gift; FRLG Wonder Cards, Wonder News and console code go to the launcher as flags |
| Official events | a real Sword/Shield event card ([Official event cards](swsh_gift.md#official-event-cards)), compiled like a built gift |
| Build your own | the form, compiled to `session/gifts/<tool>.pokegift` at Start and passed as `--gift-file` |
| Open a file | a shared `.pokegift`, or a `.wc8` on Sword/Shield |

The FRLG Game boosts are the resident hooks ([`install-resident`](frlg_rom.md#install-resident)).
Several can be ticked at once; they run as one chain ([Several hooks at once](frlg_rom.md#several-hooks-at-once)).
Each carries settings that become the launcher's `--resident-param` flags, and the panel shows the
bytes the ticked set takes of the 1024 the console has.

| boost | settings | parameters |
|---|---|---|
| Speed up the game (`turbo-lite`) | speed x1 to x4; overworld, battles or both; always on or while R, B or Select is held; faster text | `field` and `battle` = speed - 1, `budget=228` from x3, `hold`, `extra=4` |
| Walk through walls | R, B or Select | `hold` |
| Shiny countdown | the slow-down button; x2, x4 or x8 slower | `slow`, `slow_frames` 1, 3 or 7 |
| No wild encounters, Lead's IVs on screen, Pokemon follower | none | |

L is not offered: only R's Help System toggle has a flag the hooks hold off. Save boosts for later
sends `save-write --resident` in place of `install-resident`: the set goes into `filler_B20` and is
installed in the same session. A set past one `install-resident` session (876 bytes), and the
follower, always go through the save. Mom restores your boosts binds Mom's loader, and talking to Mom
after any boot installs whatever set the save holds. Sending boosts again replaces the set running.
The app shows the restore steps beside the save option and in Before you send, including for sets
that must be saved. Preset names and descriptions wrap so their instructions remain visible.
`tests/test_gift_builder.py` sends every combination of boosts, and every setting of each, through the
launcher for all four cartridges.

Read the save offers Trainer ID (TID) and Secret ID (SID), trainer details and play time, and the
last saved party's natures, IVs and EVs. Results appear in the Session log; the two dump presets
also write the read data into Received. The group explains the normally hidden SID, IVs as six
individual values from 0 to 31, and EVs as training points. These reads preserve the save and
Wonder Card ([Reading the save](frlg_rom.md#reading-the-save)).

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

Console code is assembled with `arm-none-eabi-as` when it is on the PATH, in Homebrew's folders or
under Arm's Windows install folder; without it, the form takes a prebuilt `.bin` and shows the
command that installs the assembler on this system:

| system | command |
|---|---|
| macOS | `brew install arm-none-eabi-binutils` |
| Fedora | `sudo dnf install arm-none-eabi-binutils-cs` |
| Debian, Ubuntu and derivatives | `sudo apt install binutils-arm-none-eabi` |
| Windows | `winget install Arm.ArmGnuToolchain` |

Another Linux distribution gets Arm's download page. The Fedora 44 and Ubuntu 24.04 packages
assemble the default template to `01 00 a0 e3 1e ff 2f e1`. Check offline runs the code once on the simulated console
(`pokeldn/frlg/rom/custom_code.py`) and shows the answer and the bytes. The same check runs before
Start and before a file is saved: code that faults, or never returns 1, is refused.

The Sword/Shield form builds a Pokemon (optionally able to Gigantamax), an egg, up to six bag items,
official outfits, Battle Points or money, with a card id. The Pokemon, egg, item, clothing and Battle
Points kinds write the bytes of a record a retail Sword listed and redeemed
([Sword and Shield Mystery Gift](swsh_gift.md#a-card-delivered-to-a-retail-console)); the
Pikachu preset is byte for byte the launcher's own default record. Clothing comes from the pairs of
the official outfit cards ([Clothing](swsh_gift.md#clothing)), at most six pieces for each player
gender. PKHeX refuses a Gigantamax flag on a species without a Gigantamax form.

Before you send lists what the console gets, when it runs, and the cartridges the gift serves. Save
gift file writes the selected gift as `.pokegift` with no board and no Switch keys. FRLG presets go
through the launcher's own builder, so the file holds every cartridge variant they build. The
console's game code chooses the variant during the gift handshake; a cartridge absent from the file
is refused before gift data is sent. A preset's card id is on the Advanced tab (`--flag-id`, 1000 to
1019).

The app does not modify gift files on import. Files remain at the chosen paths.

Delivered from an opened file on retail consoles: a Celebi card and a console code file on a French
FireRed, a Pikachu card on a Sword. Console code built in the form answered with the save's trainer id.

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

The converter imports Sword/Shield WC8 records, FRLG `.wc3` files and paired FRLG files used by
`pokemon-gen3-mysterygift-tool`. A `.wc3` or `.wc8` also opens directly, in the app's Open a file and
in `--gift-file`.

An FRLG script whose reachable code holds no absolute address serves all four cartridges (`BPRF`,
`BPGF`, `BPRE`, `BPGE`): its jumps and text are `vgoto`/`vmessage` operands relative to its own
`setvaddress` [scrcmd.c:171], and items come through `callstd`. A script with a `goto`, `call`,
`message`, `callnative` or other absolute pointer belongs to one cartridge and needs `--build`; a
`.wc3` of that kind is refused when opened directly.

```bash
./.venv/bin/python -m pokeldn.gifts import --game swsh --record event.wc8 -o event.pokegift
./.venv/bin/python -m pokeldn.gifts import --game frlg --wc3 "FL - Item AuroraTicket (FRE).wc3" -o aurora.pokegift
./.venv/bin/python -m pokeldn.gifts import --game frlg --card WonderCard.bin \
  --script Script.bin --name "Event gift" -o event.pokegift
./.venv/bin/python -m pokeldn.gifts export celebi.pokegift --build BPRF --out-dir native-gift
./.venv/bin/python -m pokeldn.gifts export celebi.pokegift --wc3 --out-dir native-gift
./.venv/bin/python bin/frlg_mg_host.py --gift celebi --export-gift celebi.wc3
```

Saving to a path ending in `.wc3` or `.wc8` writes that native file instead of a `.pokegift`: in
`--export-gift`, in Save gift file and in `pokeldn.gifts.save`. A `.wc3` holds one cartridge's card
and script; without `--build` every variant of the gift must carry the same bytes, as a relative
script's do. The `.wc3` metadata block is written as zero except its icon, which repeats the card's.
Every international gallery file the game accepts comes back with the same card, script and icon
bytes after an import and an export.

A `.wc3` is 1420 bytes (`0x58C`):

| offset | size | content |
| --- | --- | --- |
| `0x000` | 336 | CRC16 of the card, 2 pad bytes, the 332-byte `struct WonderCard` |
| `0x150` | 80 | save-side card metadata; not read |
| `0x1A0` | 1004 | CRC16, 2 pad bytes, `struct RamScriptData` (magic 51, map group, map number, object id, 995-byte script), 1 pad byte |

The script CRC in the files covers 1000 bytes, pad byte included, in all 54 international files of
Project Pokemon's EventsGallery; the game's own covers 999 [script.c:488]. Import accepts either.
`--icon N` on import, or Card icon under Open a file in the app, sets the card's `iconSpecies`
(offset 2 of the card) to an internal species id from 0 to 411; 0 draws no icon
[mystery_gift_show_card.c:466].

Japanese `.wc3` files are 1252 bytes (`0x4E4`) and are refused: the Switch cartridges are French and
English. Every international gallery script is relative and serves all four cartridges. The gallery's
debug cards with flag ids 4 to 8 are refused: the delivery man hands a gift only for flag ids 1000 to
1019 [mystery_gift.c:241]. The Aurora and Mystic Tickets are no-ops on a save past its first Hall of
Fame ([The Aurora and Mystic Tickets](frlg_gift.md#the-aurora-and-mystic-tickets)).

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
| FRLG console code | supported cartridge codes | `buffer_code`, `buffer_lead_1`.. | response settings below |
| Sword/Shield | `swsh` | `wc8` | none |

FRLG card variants carry the same flag ID and gift type. Wonder News and console code each travel
alone. Captures, keys, filesystem paths and session timing are outside this format.

An FRLG console-code variant has exactly one `buffer_code` component, and up to eight payloads run
before it in the same session as `buffer_lead_1`, `buffer_lead_2` and on, numbered with no gap (a
resident hook kept in the save writes `filler_B20` with them, then installs it). Its optional response
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

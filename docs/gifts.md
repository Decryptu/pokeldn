---
title: Mystery Gift files
---
# Mystery Gift files

A `.pokegift` file stores a complete Mystery Gift distribution for FireRed/LeafGreen or
Sword/Shield, with its target game and native records.

## Desktop app

Games, Mystery Gift has the same Gift file control for both supported games. Browse opens a
`.pokegift` file and shows its name, game and cartridge variants. Sword/Shield also opens `.wc8`
files. Selecting a file hides the built-in gift fields and sends the file's data. Clearing the
path restores those fields. Existing Sword/Shield settings containing a `.wc8` path still work.

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

## Version 1

The file is UTF-8 JSON with five required fields:

| Field | Value |
| --- | --- |
| `format` | `pokeldn.gift` |
| `version` | integer `1` |
| `game` | `frlg` or `swsh` |
| `name` | non-empty display name, up to 180 characters |
| `variants` | object mapping target codes to native data and options |

Each variant has `data` and `options` objects. A component in `data` has `hex`, the native bytes
encoded as hexadecimal, and `sha256`, their lowercase SHA-256 digest. JSON field order has no
meaning. Export sorts fields for deterministic files.

| Game | Variant keys | Data components | Options |
| --- | --- | --- | --- |
| FRLG | supported cartridge codes | `card`, `ram_script`, `stamp`, `activation_script`, `install_activation_script`, `trainer`, `news`, `mevent` | `questionnaire`, `denied_message` |
| Sword/Shield | `swsh` | `wc8` | none |

FRLG card variants carry the same flag ID and gift type. Wonder News travels alone. Native buffer
code, captures, keys, filesystem paths and session timing are outside this format.

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

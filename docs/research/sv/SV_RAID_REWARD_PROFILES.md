# Scarlet/Violet raid reward profiles

> Historical donor-era research. Production hosting now generates the complete
> raid opening and rewards. Donor artifacts remain only as research evidence.

## Historical product surface

The first custom-reward implementation used a versioned JSON file and command
line tools. That interface has been removed; the current GUI and CLI pass
ordered reward rows directly to the generated RaidPoint builder.

The original profile backend was intentionally donor-specific. The archived
corpus retains `fixtures/sv_raid_reward_donor.bin` alongside its packet capture:

- game: Pokémon Violet 4.0.0;
- donor seed: `C72E1D7F`;
- donor RaidPoint: `RaidPoint_13_1_1`;
- bootstrap message: application type `0x012F`;
- profile format: `pokeldn.sv.raid-rewards.v1`;
- template ID: `violet-4.0.0-c72e1d7f-avalugg`.

The retired parser rejected unknown formats, templates, fields, and donor
bytes.

## Profile format

```json
{
  "format": "pokeldn.sv.raid-rewards.v1",
  "template": "violet-4.0.0-c72e1d7f-avalugg",
  "mode": "exact",
  "name": "Quick Ball x500",
  "rewards": [
    {
      "item_id": 15,
      "quantity": 500
    }
  ]
}
```

Rules:

- `format`, `template`, `mode`, and `rewards` are required;
- `name` is optional;
- `mode` must be `exact`;
- `rewards` must contain 1 through 16 entries in display order;
- every entry must contain exactly `item_id` and `quantity`;
- `item_id` is an integer from 1 through `0xFFFFFFFF` and must represent a
  valid Scarlet/Violet item;
- `quantity` is an integer from 1 through 999;
- duplicate item IDs are allowed and remain separate rows.

## Commands

The commands below describe the historical donor experiment. Their helper
scripts were removed when production switched to direct generated RaidPoint
rows; they are retained here as an experiment log, not runnable instructions.

Create a profile (historical):

```bash
./.venv/bin/python tools/sv/research/sv_raid_rewards.py create \
  --name "Quick Ball x500" \
  --reward 15:500 \
  --output quick500.json
```

Repeat `--reward ITEM_ID:QUANTITY` to create an ordered multi-row list.
Command-line integers accept Python notation such as decimal `15` or
hexadecimal `0x0f`. JSON output is normalized to decimal integers.

Validate and normalize a profile:

```bash
./.venv/bin/python tools/sv/research/sv_raid_rewards.py validate quick500.json
```

Inspect all known reward slots in the donor capture:

```bash
./.venv/bin/python tools/sv/research/sv_raid_rewards.py inspect \
  --trace tera_raid_retail_seed_C72E1D7F_max_quantity_avalugg_run1.jsonl
```

Offline-encode an application and its decoded `0xAA0`-byte object:

```bash
./.venv/bin/python tools/sv/research/sv_raid_rewards.py encode quick500.json \
  --trace tera_raid_retail_seed_C72E1D7F_max_quantity_avalugg_run1.jsonl \
  --application-out quick500.application.bin \
  --raw-out quick500.raw.bin
```

Host the profile with an independently selected fight/catch seed:

```bash
tools/sv/research/sv_raid_reward_host.sh 000F34C3 quick500.json
```

The current host wrapper uses link code `4970`, the connected ESP32 at
`/dev/ttyACM0`, client-gated replay, and the proven sequence-20 handoff.
Client gating is automatic for every raid replay and is not a command-line
option.

The direct host integration point is:

```text
--raid-reward-profile PROFILE.json
```

Profile mode automatically selects the known-good victory replay, its
`BD13FB43` source seed, the bundled 4-star Paldea encounter context, the
validated donor bootstrap, and the proven sequence-20 handoff. The wrapper
supplies the radio and retail-session settings.

## Exact-list encoding behavior

The encoder performs these operations:

1. Reassemble decoded reliable sequences 11 and 12.
2. Validate the `80 33` application prefix, message type `0x012F`, compressed
   flag 2, declared raw size `0xAA0`, and RaidPoint identifier.
3. Raw-LZ4-decompress the application payload.
4. Require byte-exact original values in all 19 linked reward records and both
   independent bonus records.
5. Clear all 21 known reward records to `{0, 0, 0, 0}`.
6. Write profile entries sequentially into the 16 guest-visible offsets as
   `{source=0, item_id, quantity, reserved=0}`.
7. LZ4-compress the complete `0xAA0` plaintext object.
8. Preserve the captured 16-byte application header except for its raw-size
   field, which remains `0xAA0`.
9. Split the application at the proven 1,395-byte sequence-11 boundary and
   restore each fragment's outer zlib encoding according to its Pia flags.

All bytes outside the 21 known reward records remain unchanged in exact mode.

## Retail validation

Demonstrated on retail hardware:

- all 19 linked item records remapped to Ultra Ball with native quantities:
  42 Ultra Balls awarded;
- all 19 linked item records remapped to Exp. Candy XL with native quantities:
  42 Exp. Candy XL awarded;
- first visible record changed to Quick Ball x500 while the other 19 linked
  records were cleared: Quick Ball x500 was awarded;
- that first single-entry run also awarded Nugget x1, identifying independent
  bonus slot `0x8C8` as active.

The product exact-list encoder additionally clears bonus slots `0x8B8`
(Big Pearl) and `0x8C8` (Nugget). This correction is structurally verified by
decode-after-encode tests; a second retail run of the bonus-cleared profile is
the remaining confirmation for a literally one-row result screen.

## Python API

`sv_raid_bootstrap_codec.py` exposes:

- `parse_reward_profile(mapping)`;
- `load_reward_profile(path)`;
- `decode_application(application)`;
- `encode_application(template, raw)`;
- `inspect_avalugg_rewards(raw)`;
- `encode_reward_profile_application(template, profile)`;
- `patch_avalugg_reward_profile(events, profile)`.

The lower-level functions accept and return bytes; they do not access the GUI,
radio, or filesystem except for the explicitly named profile loader.

## Limitations

- Version 1 supports only the validated Avalugg donor layout.
- A coherent donor bootstrap is still required; this does not generate the
  whole RaidPoint from a reward seed.
- One-entry custom identity and quantity are retail-proven. Multi-entry exact
  profiles are encoded and tested structurally but have not all been exercised
  on retail hardware.
- Valid item IDs are the caller's responsibility; the encoder validates the
  integer range, not the game's item database.
- Inventory caps and game-specific handling of unusually large quantities may
  affect what is retained after the reward screen.
- The GUI is intentionally unchanged.

For the full binary layout, Ghidra call chain, offsets, and compression layers,
see `SV_RAID_BOOTSTRAP_ENCODER.md`.

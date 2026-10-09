# Scarlet/Violet raid reverse-engineering archive

This directory keeps the durable notes and methods behind pokeldn's generated
Tera Raid host. Runtime code remains in `bin/`; obsolete donor captures are
preserved under `docs/research/sv/fixtures/` and are not packaged. Raw
local captures remain in the application's session capture directory.

## Research map

- [`SV_RAIDPOINT_REVERSE_ENGINEERING.md`](SV_RAIDPOINT_REVERSE_ENGINEERING.md):
  RaidPoint layout, retail encounter assets, Ghidra findings, and validation log.
- [`SV_PIA_IDENTITY_REVERSE_ENGINEERING.md`](SV_PIA_IDENTITY_REVERSE_ENGINEERING.md):
  donor-free Pia player identity and locally administered MAC findings.
- [`SV_RAID_BOOTSTRAP_ENCODER.md`](SV_RAID_BOOTSTRAP_ENCODER.md): the `0x012F`
  bootstrap encoding and structural evidence.
- [`SV_RAID_REWARD_PROFILES.md`](SV_RAID_REWARD_PROFILES.md): reward profile
  format and the earlier donor-backed workflow.
- [`TODO.md`](TODO.md): completed milestones and remaining retail-validation work.
- [`fixtures/`](fixtures/): retired victory/reward donor artifacts retained only
  for byte-level regression and historical comparison.
- [`SV_RAID_GUEST_REVERSE_ENGINEERING.md`](SV_RAID_GUEST_REVERSE_ENGINEERING.md):
  retail guest state transitions, timing evidence, capture method, and bootstrap
  acquisition findings.

Reusable Ghidra scripts live in [`../../../tools/sv/ghidra`](../../../tools/sv/ghidra).
Donor-era command-line analysis tools live in
[`../../../tools/sv/research`](../../../tools/sv/research). Neither research
fixtures nor research tools are included in desktop runtime bundles.
The generated retail encounter/action catalog is reproducible through
[`../../../tools/sv/import_raid_data.py`](../../../tools/sv/import_raid_data.py).

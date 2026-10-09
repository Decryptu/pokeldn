# TODO

## Restore the ESP32 retail raid-guest workflow

- [x] Capture one new successful session in which the ESP32 joins a retail
  Scarlet/Violet Tera Raid as a guest, appears in the lobby, becomes ready,
  and lets the host begin the raid.
- [x] Use the captures to identify the lobby records, Ready and Start states,
  channel-table split, timing, and valid Session identity shape.
- [x] Add offline tests for the application types, channel-table split,
  generated lobby messages, and Ready/Start transitions.
- [x] Document the durable protocol and capture findings in
  `SV_RAID_GUEST_REVERSE_ENGINEERING.md`.
- [x] Reuse the legal SV Pokemon builder for a custom raid guest Pokemon,
  replacing only the party PK9 inside the captured lobby announcement.
- [x] Disconnect after the stable battle-transition message so the selected
  Pokemon remains in the raid as an AI-controlled bot.

The implementation itself remains in `sv_join.py`, including retail Session
and Net behavior, delayed channel acknowledgements, the base/raid channel-table
split, port-2 join, identity delivery, generated lobby messages, and ready-state handling.
The replacement retail captures were recorded on 2026-10-07. The small
`pokeldn/sv/data/raid_guest.json` fixture now retains only lobby regression
evidence; raw traces remain local diagnostics and are no longer runtime
dependencies. Host and guest both reuse the standard Scarlet/Violet application
identity, and their Session player IDs and MAC addresses are generated.

- [x] Replace the default captured guest lobby records with
  `pokeldn.sv.raid.JoinerRaidStage`. The selected PK9, initial state, Ready, and
  Start ACK are now generated; the GUI requires a selected Pokémon. The old
  lobby fixture remains only as regression evidence and for the explicit
  `--raid-lobby-trace` experiment path.

## Generate the SV raid bootstrap without a raid donor

Detailed reverse-engineering state is in
`SV_RAIDPOINT_REVERSE_ENGINEERING.md`.

- [x] Identify the `0x012F` serializer and prove the fixed `0xAA0` plaintext
  layout: four participant PK9s, one boss PK9, and a `0x3E8` RaidPoint.
- [x] Prove that the serializer copies an already-populated RaidPoint rather
  than generating it.
- [x] Compare complete two-star standard, four-star standard, and five-star
  event RaidPoints.
- [x] Map the identity, difficulty, level, HP multiplier, reward rows, and
  repeated encounter-summary fields.
- [x] Confirm that encounter selection, boss PK9 generation, and ordered reward
  rolls are deterministic from seed plus version/map/progress/content context.
- [x] Recover or retail-validate the standard shield/action block for every
  supported star level.
- [ ] Determine whether a synthetic `RaidPoint_*` name is accepted.
- [ ] Determine the live meaning or accepted canonical value of the opaque
  application-header fields at `0x04` and `0x0E`.
- [x] Implement a zero-initialized `0x3E8` RaidPoint constructor for the
  retail-table-backed standard one- through five-star and black six-star profiles.
- [x] Implement a donor-free `0xAA0` constructor using supplied player PK9s,
  canonical empty slots, and the generated boss PK9.
- [x] Implement a donor-free `0x012F` envelope/LZ4 constructor and an
  experimental replay replacement path exposed by
  `sv_raid_host.py --generated-bootstrap`.
- [ ] Retail-test one generated ordinary raid through the normal sequence-20
  handoff. The first corrected run reached the battle protocol but mistakenly
  replayed through sequence 76; the game never became playable and then left.
- [x] Gate the early raid stream/channel/identity opening on the console's
  Session type-6 station-list ACK. The failed run received that ACK 261 ms
  after the old fixed timers had already sent the whole identity.
- [x] Retail-retest the ACK-gated lobby transition and confirm receipt of the
  console's `0x7C` port-2 type-3 raid join before validating sequences 11/12.
- [x] Capture the joining console's `0x80332e` party PK9 and late-bind it into
  bootstrap participant slot 1 before sequence 11.
- [x] Replace all-zero missing participants with retail's exact static level-1
  species-zero `Egg` placeholder.
- [x] Retail-retest the corrected participant array. The patched run reached
  and acknowledged sequences 11/12 and returned `load_6e`, `load_73`, and
  `battle_93` without reproducing the immediate game crash. It did not prove a
  playable battle because the host incorrectly continued past the normal
  sequence-20 handoff.
- [x] Apply the proven sequence-20 handoff and five-second host shutdown to
  generated-bootstrap mode as well as reward-profile mode.
- [x] Replace the generated mode's capture-timed sequences 1-20 with a pure
  `pokeldn.sv.raid.RaidStage`, including generated lobby metadata/Pokémon,
  bootstrap fragmentation, loading transitions, and battle handoff records.
- [ ] Retail-test the fully generated sequence-1..20 path. Offline regression
  tests reproduce every plaintext application message from the successful
  opening, but the two opaque tokens in battle handoff messages 15/16 still use
  their retail-validated canonical values pending identification in Ghidra.
- [ ] Keep event raids gated on explicit BCAT enemy/action/reward table input.
- [ ] Separately remove the capture dependency from later battle runtime state;
  generating RaidPoint alone does not generate the whole battle simulation.

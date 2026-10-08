# TODO

## Restore the ESP32 retail raid-guest workflow

- [ ] Capture one new successful session in which the ESP32 joins a retail
  Scarlet/Violet Tera Raid as a guest, appears in the lobby, becomes ready,
  and lets the host begin the raid.
- [ ] From that capture, extract and retain only the minimal reproducible
  fixtures required by `sv_join.py`:
  - the complete guest identity stream on `0x81` port 1;
  - the guest lobby application records on `0x80` port 0, sequences 1 and 2;
  - the Session join identity needed to verify the player ID and station MAC.
- [ ] Add offline tests that load the compact fixtures and verify their
  sequence continuity, application types, channel-table split, and ready-state
  transition.
- [ ] Recreate `ESP32_RETAIL_RAID_GUEST.md` with the known-good command,
  required console steps, expected log milestones, timings, and failure modes.
- [ ] Mark the compact fixtures as required reference assets so future capture
  cleanup does not delete them.

The implementation itself remains in `sv_join.py`, including retail Session
and Net behavior, delayed channel acknowledgements, the base/raid channel-table
split, port-2 join, identity replay, lobby replay, and ready-state handling.
The deleted full-frame capture was untracked, so it cannot be restored through
Git and must be replaced by a new capture or another backup.

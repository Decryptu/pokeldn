# Tera raid battle-runtime checkpoint

This checkpoint preserves the current experimental battle-host implementation before seed-profile
generation is developed further.

## Working transport path

`sv_host.py --raid --raid-replay-trace ... --raid-replay-interactive` hosts a captured local Tera
Raid lobby over the ESP32. A retail guest can discover it, join it, enter the lobby, and (with an
unmodified matching replay) reach battle command selection.

## Seed substitution work

`pokeldn.sv.raid_seed.patch_boss()` first audits and then atomically replaces the capture-backed
boss representations:

1. The complete 344-byte encrypted PK9.
2. The compact lobby descriptor: species, star count, Tera type, and encounter identifier.
3. The structured boss action slots in the opening 20,626-byte runtime state and its 250-byte
   summary.

The replacement PK9 is built from a blank record plus known raid-common values, rather than being
edited in place from Growlithe. This prevents unknown source-record bytes carrying into a target.

## Known limitation

The large runtime state has a variable battle-command/effect payload. A substituted Pawniard can
enter battle but disconnects before move selection. Generating a valid seed profile is useful and
is intentionally an independent layer; it does not by itself generate the matching runtime battle
commands.

## Sequence-20 handoff result

The generated Pawniard no longer needs the replay-backed battle-command phase to be playable. A
repeatable handoff sends the generated lobby/boss stream only through host reliable sequence 20,
keeps Pia/RTT/reliable maintenance alive for 30 seconds, and then shuts down the host transport.
The retail guest reports a communication error but proceeds into local move selection, can finish
the battle, and can catch Pawniard.

The boundary is meaningful: stopping after sequence 18 or 20 leaves the client connected, while
sending the unchanged Growlithe sequences 21-22 leads to a Session type-3 leave roughly 70-80 ms
after sequence 22. Sequence 21 is an opcode-0x11 synchronization table and sequence 22 is an
opcode-0x02 participant-state record. The client sends a burst of 0x80:0 application records just
before leaving; transport ACK/RTT traffic remains healthy.

Rewards are still the captured Growlithe rewards, even though the encountered and caught Pokémon
is Pawniard. This establishes that reward context is separate from the patched lobby species,
encounter identifier, and encrypted boss PK9, and is already available to the client by sequence
20. The source seed itself does not occur as a plaintext 32-bit value in sequences 1-20. The
compact raid descriptor still has unmapped fields, notably its varying u16 at offset +4.

## Sequence 12 finding

In the Growlithe source, reliable sequence 11 starts the large `0x80332f01` raid-state message and
contains most of the encrypted boss PK9. Sequence 12 ends that message. Its first 11 decoded bytes
are exactly the tail of the 344-byte boss PK9; the remaining 164 bytes begin with the ASCII object
identifier `RaidPoint_12_1_11` and an opaque serialized raid-point state block.

The Pawniard substitution changes exactly sequence-12 offsets 0 through 10. Offsets 11 through 174
remain byte-for-byte Growlithe data. Equivalent retail messages differ by raid: Mareep carries
`RaidPoint_09_02_05`, Tinkatink carries `RaidPoint_11_1_1`, and Forretress carries
`RaidPoint_10_01_07`; their decoded continuation lengths are respectively 183, 190, and 299 bytes
before removing the 11-byte PK9 tail. The known seeds are not present as plaintext. This block is
therefore a credible source of stale raid/reward context, but its raid-point identity means the
differences may also describe the crystal's world location. It remains a candidate pending a
controlled substitution test.

### Partial Forretress sequence-12 substitution

Capture `tera_raid_seed_000F34C3_seq12_forretress_11_178_handoff20_ch1_4970.jsonl`
preserves the Pawniard PK9 tail at decoded sequence-12 offsets 0..10 and replaces offsets 11..178
inclusive with the Forretress continuation. Because the Growlithe continuation is 175 bytes and
the Forretress continuation is 299 bytes, this creates a 179-byte hybrid that ends at Forretress
offset 178 rather than carrying the complete Forretress record.

The client completed the normal application exchange through its battle-action message, ACKed all
host sequences 1..20, and sent no Session type-3 leave. After the scripted handoff it reached the
reward screen, but displayed `You defeated Egg!`, did not offer a catch, and showed corrupt-looking
rewards. This proves that the post-PK9 portion of sequence 12 supplies semantic defeated-boss and
reward/catch state. It also shows that a partial byte-range splice is structurally invalid. The
next controlled test should replace the complete decoded Forretress continuation from offset 11
through its end, without truncating it.

### Complete Forretress sequence-12 suffix

Capture `tera_raid_seed_000F34C3_seq12_forretress_full_suffix_handoff20_ch1_4970.jsonl`
contains the follow-up test: Pawniard PK9 tail at offsets 0..10 followed by the complete Forretress
sequence-12 suffix, producing the expected 299 decoded bytes. The client again reached the result
screen but offered no catch, displayed `You defeated Egg!`, and listed four entries of
`Master Ball x0`. Thus truncation was not the cause. Sequence 12 is part of a larger internally
coupled raid-state structure; transplanting its suffix without the corresponding preceding state
causes the game to read default species/item id 0 and quantity 0.

### Coherent Forretress sequences 11-12 with a generated Pawniard PK9

Capture `tera_raid_seed_000F34C3_seq11_12_forretress_template_pawniard_pk9_handoff20_ch1_4970.jsonl`
copies the complete decoded Forretress application records at replay sequences 11 and 12, then
replaces only the encrypted boss PK9 spanning sequence 11 offset `0x426` through the first 11
decoded bytes of sequence 12 with the generated Pawniard PK9 for seed `000F34C3`.

This combination completed successfully through the sequence-20 scripted handoff and displayed
Forretress reward data. The trace contains one clean join, every replay sequence 1..20 exactly
once, no Session type-3 leave, and no stale replay events from an earlier attempt. This is the
strongest localization result so far: the raid outcome/reward/catch context is encoded in the
internally coupled sequence-11/12 `0x80332f01` state, while the encrypted boss PK9 within that
state can be substituted independently to present and battle a different generated boss.

It also explains both earlier results: preserving the Growlithe sequence-11/12 context yielded
Growlithe rewards, while transplanting only the Forretress sequence-12 suffix broke its internal
references and produced Egg/Master Ball x0 defaults. Arbitrary reward generation therefore needs
the sequence-11/12 state decoded or generated as one coherent unit; byte-splicing sequence 12 in
isolation is not sufficient.

The successful attempt also validates the identity-handshake timing change from a configured
record delay of 137 ms to 100 ms. The first host identity record was emitted 120.8 ms after join,
the client identity burst began at 273.2 ms, and the port-2 raid join arrived at 1.148 s.

This capture also exposed a host retry bug: after an application-layer leave and rejoin using the
same link-local IP, unsent raid events from the first attempt remained scheduled and interleaved
with the fresh replay. `sv_host.py` now clears the raid reliable window, pending replay/Net/session
events, handoff timer, and per-attempt diagnostic state whenever a new Session join request arrives.

## Pre-raid record burst result

The large burst immediately after Pia stream setup is station identity/state, not raid bootstrap
data. It consists of 46 zlib records on protocol `0x81`, port 0: 45 records inflate to 1,395 bytes
and the final record inflates to 75 bytes. The complete inflated stream is 62,850 bytes.

The extracted record payloads from `tera_raid_retail_victory_full`,
`tera_raid_retail_battle_full`, and `tera_raid_retail_pair_4040` are byte-for-byte identical for
every one of the 46 record ids (inflated aggregate SHA-256
`b2c4e54156b0f8a62c91fbb413a297b17da7568966252bab62c2fbe5c66c4893`). Their transmission order
varies, while their contents do not. None of the known Growlithe, Mareep, Pawniard, Tinkatink, or
Forretress raid seeds occurs in either byte order. This excludes the record burst as the source of
the captured Growlithe encounter or reward context.

## Evidence captures

- `tera_raid_retail_victory_full.jsonl`: 2-star Growlithe, seed `BD13FB43`.
- `tera_raid_retail_battle_full.jsonl`: 2-star Mareep.
- `tera_raid_fake_host_seed_000F34C3_action_ch1_4970.jsonl`: generated Pawniard seed substitution
  through the identified runtime action fields.
- `tera_raid_fake_host_seed_000F34C3_handoff20_pawniard_catch_growlithe_rewards_ch1_4970.jsonl`:
  Pawniard is playable and catchable after a sequence-20 host handoff; rewards remain Growlithe's.
- `tera_raid_seed_000F34C3_stop_after_18_ch1_4970.jsonl` and
  `tera_raid_seed_000F34C3_stop_after_20_ch1_4970.jsonl`: stable connected holds with maintenance
  traffic continuing after the selected replay boundary.
- `tera_raid_seed_000F34C3_stop_after_22_ch1_4970.jsonl` and
  `tera_raid_seed_000F34C3_delay_23_5s_ch1_4970.jsonl`: Session leave occurs after sequence 22 and
  before sequence 23, excluding sequence 23 as the direct trigger.
- `tera_raid_retail_controlled_tinkatink_first_moves.jsonl`: despite the provisional filename, this
  is a Forretress raid. It uses the same Giratina host and Gallade guest as the Growlithe reference,
  with Giratina selecting Aura Sphere (move 396) in both captures. Host reliable sequences 1-137
  are complete with no gaps.

## Controlled differential result

The comparable opening host-action states are Growlithe sequence 33 and Forretress sequence 59.
Their 20,626-byte records have the same envelope and fixed layout. The queued boss move changes at
record offset `0x43` (`172` to `371`). The variable payload starts at `0x26f`; its declared length
changes from `0x293` to `0x377`, while large later blocks remain byte-identical but move because the
Forretress stream inserts additional commands.

The corresponding 250-byte records are Growlithe sequence 48 and Forretress sequence 74. Their
host and boss action fields remain at offsets `0x3b` and `0x4b`. Other differing values are runtime
effect/RNG state and are not a second boss profile.

The variable payload is therefore a serialized command stream, not a fixed boss structure. It does
not contain the boss species, EC, ability, nature, Tera type, or stats as direct integers. Arbitrary
raid hosting now requires either constructing this command stream or replacing the replay-backed
battle phase with a live authoritative battle-state implementation.

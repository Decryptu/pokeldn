# Scarlet/Violet RaidPoint reverse-engineering notes

## Objective and current conclusion

The objective is to construct the complete Scarlet/Violet `0x012F` raid
bootstrap from generated state instead of copying and patching a donor raid.

The bootstrap itself can now be built without a raid donor. Ghidra establishes a
fixed plaintext layout and leads from the RaidPoint consumer to the retail raid
enemy assets. The decoded assets supply the exact encounter-specific HP,
shield, extra-action, and double-action values for all 700 bundled encounters:
standard one- through five-star and black six-star raids across Paldea,
Kitakami, and Blueberry. Retail captures independently validate the resulting
two- and four-star serialization.

"Seed only" needs one qualification. A 32-bit seed does not identify a unique
raid by itself. Retail resolution also depends on:

- Scarlet or Violet;
- map: Paldea, Kitakami, or Blueberry;
- story progress, which controls the star distribution;
- standard, black, or event content and the active event tables.

Those values are game state rather than donor data. Given that context, the
existing catalog code deterministically generates the encounter, boss PK9,
Tera type, and reward rolls. A host player PK9 is also independent input, not a
property of the raid seed. The map-specific `RaidPoint_*` name is likewise an
instance identity rather than a seed result; a synthetic deterministic name may
work, but this has not been tested on retail.

This work therefore separates three goals:

1. donor-free `0x3E8` RaidPoint construction;
2. donor-free `0xAA0` bootstrap construction from player PK9s plus RaidPoint;
3. a completely generated battle stream.

The first two are the scope of this investigation. The third still contains
large runtime battle-state messages and is not solved by generating RaidPoint.

## Ghidra project and scripts

The analyzed executable is Violet 4.0.0 `main`, loaded at image base
`0x7100000000`. The saved project is:

```text
/home/ismail/violet_raidpoint.gpr
/home/ismail/violet_raidpoint.rep/
```

The original project had a stale lock, so headless analysis was performed on a
copy at `/tmp/violet-ghidra-work`. Do not treat that temporary copy as the
authoritative project.

Reusable scripts are in `tools/sv/ghidra/`:

| Script | Purpose |
| --- | --- |
| `DumpRaidFunctions.java` | Decompile the initially identified raid functions. |
| `DumpPointers.java` | Find initialized pointers to target functions or data; tolerates uninitialized BSS. |
| `FindScalarFunctions.java` | Find functions using a scalar value. |
| `FindMultiScalarFunctions.java` | Rank functions containing several target scalar values. |
| `FindAsciiRefs.java` | Find references to an exact ASCII string. |
| `FindStringsContaining.java` | Scan initialized memory for strings containing supplied terms. |
| `FindCallsWithNearbyScalar.java` | Find calls accompanied by a nearby scalar. |
| `FindPointerValues.java` | Find initialized occurrences of pointer values. |
| `FindHexBytes.java` | Search initialized memory for exact byte patterns. |
| `DumpInstructions.java` | Print instructions for an address range. |
| `CreateFunctions.java` | Disassemble/create functions at specified entry points. |

The working headless invocation was:

```bash
rm -f /tmp/violet-ghidra-work/violet_raidpoint.lock \
  /tmp/violet-ghidra-work/violet_raidpoint.lock~
XDG_CONFIG_HOME=/tmp/ghidra-config GHIDRA_HEADLESS_MAXMEM=4G \
  /home/ismail/Downloads/ghidra_12.1.4_PUBLIC/support/analyzeHeadless \
  /tmp/violet-ghidra-work violet_raidpoint \
  -process main -noanalysis \
  -scriptPath /home/ismail/Documents/GitHub/pokeldn/tools/sv/ghidra \
  -postScript SCRIPT.java ARGS...
```

## Proven native layout

### Message class and serializer

All addresses are Violet 4.0.0 addresses.

| Address | Proven role |
| --- | --- |
| `FUN_71018BB5F8` | Constructs the large message object and assigns type `0x012F`. |
| `FUN_71018BB4FC` | Allocates the `0x460`-byte message object and calls its constructor. |
| `FUN_7100E327FC` | Serializes the message object to a fixed `0xAA0` plaintext record. |
| `FUN_7100E329B4` | Serializes each referenced PK9 subobject to `0x158` bytes. |
| `FUN_7101E62FE4` | Inverse/copy-back path for the same layout. |
| `FUN_7101592B7C` | Builds the serializer header and selects compression. |
| `FUN_7101592DAC` | Allocates the compression buffer and invokes LZ4. |
| `FUN_7101592E50` | Computes the standard LZ4 compression bound. |
| `FUN_7101592E80` | LZ4 wrapper. |
| `FUN_710071D940` | LZ4 fast-compression core. |

`FUN_7100E327FC` reads five object references at object offsets `+0x440`,
`+0x448`, `+0x450`, `+0x458`, and `+0x50`. It writes their fixed PK9
representations at raw offsets `0x000`, `0x158`, `0x2B0`, `0x408`, and
`0x560`. It then copies four qwords from object `+0x58..+0x77`, followed by
`0x3C8` bytes from object `+0x78`.

The resulting layout is:

```c
struct RaidBootstrapRaw {
    uint8_t player[4][0x158]; // 0x000..0x55F
    uint8_t boss[0x158];      // 0x560..0x6B7
    uint8_t raidpoint[0x3E8]; // 0x6B8..0xA9F
}; // 0xAA0 bytes
```

The five subobjects are not five raid bosses. Retail decoding identifies them
as the four participant party PK9s followed by the boss PK9. In the Avalugg
capture they are Mew, Gallade, two species-zero placeholders, and Avalugg.

### RaidPoint is copied as an opaque value

`FUN_7101BAE670` calls `FUN_7101BAE760`. The latter obtains a value through
`FUN_7101BAFF98`, copies `0x3C8` bytes to its stack, then passes them through
`FUN_7101BB0018` into message object offset `+0x78`.

This proves that the `0x012F` serializer does not calculate the RaidPoint. It
copies an already-populated `0x3E8` higher-level object. The generator must
therefore reproduce that object's semantic fields; further inspection of the
serializer cannot reveal how its shield/action values were chosen.

The native registration table contains a pointer to `FUN_7101BAE670` at
`0x7104432350`, alternating with obfuscated function names. Neighboring entry
points at `0x7101BAE7D0` and `0x7101BAE940` were disassembled with
`CreateFunctions.java`; both operate on the enclosing object's PK9 references
near `+0x440`.

### Seed-driven native generation

The xoroshiro constant `0x82A2B175229D6A5B` occurs in the game's raid
generators. Relevant functions include:

| Address | Observed role |
| --- | --- |
| `FUN_7100E29340` | Initializes the raid xoroshiro state. |
| `FUN_7100E29404` | Selects `raidEnemyInfo` from difficulty/table data. |
| `FUN_7100DEF2B8` | Generates the complete `0x148` stored portion of a boss PK9. |
| `FUN_7101EAB5E4` | Parses `raidEnemyInfo`. |
| `FUN_7102935B68` | Selects `raidEnemyInfo` by difficulty. |
| `FUN_7100A55EE0` | Reads encounter properties including species, form, sex, difficulty, gem type, distribution flag, table ID, version, and field ID. |

This independently corroborates `pokeldn.sv.raid_generation` and
`pokeldn.sv.raid_catalog`: boss generation is seed-driven, but encounter
selection also consumes explicit version/map/progress/content context.

Strings useful for future Ghidra work include `raidEnemyInfo`, `bossPokePara`,
`raid_table_id`, `gemType`, `RaidGemForceLottery`, and the BCAT raid-table
paths. Broad searches for constants such as `9999`, `500`, or `1200` are noisy
because those numbers also occur as unrelated offsets and limits. Three small
functions at `0x71020F16E4`, `0x71020F17FC`, and `0x71020F1928` clamp values at
9999, but no evidence yet ties them to RaidPoint.

An exact initialized-memory search for the captured four-star parameter
sequences and the likely HP-multiplier table also returned no hits. Together
with the opaque setter path, this indicates that these values are populated
from runtime game assets or script data rather than a literal table in `main`.
The executable contains the command string `Wild::RaidAction`, but its nearby
references are battle/script registration machinery and have not exposed the
difficulty profiles.

Further decompilation confirmed the asset boundary. `FUN_7100E29404` constructs
an asset key with `snprintf("%sdifficulty_%02d", prefix, difficulty)`, looks it
up in a runtime collection, and passes the selected record to
`FUN_7101EAB5E4`, which searches its `values` array for `raidEnemyInfo`. The
three observed prefixes are the empty string, `su1_`, and `su2_`, establishing
explicit records named `difficulty_01` through `difficulty_06` plus their two
map-prefixed variants. `FUN_7102935B68` independently enumerates all three
prefixes and difficulties 1 through 6 using the same asset schema.

`FUN_7101BAFF98`, previously considered a possible RaidPoint source, is only a
nullable reflected-field getter: it returns the pointer stored at object offset
`+8`, or a zero-initialized `0x3C8` singleton. It does not calculate any raid
parameters. These results mean Ghidra can recover the lookup names, parser, and
data flow, but the six difficulty records themselves must be extracted from the
game's runtime/RomFS asset bundle or observed after loading; they are not
literal constants in `main`.

Following that boundary into the update RomFS identified the eighteen standard
enemy tables:

```text
world/data/raid/raid_enemy_01..06/raid_enemy_XX_array.bin
world/data/raid/su1_raid_enemy_01..06/su1_raid_enemy_XX_array.bin
world/data/raid/su2_raid_enemy_01..06/su2_raid_enemy_XX_array.bin
```

Their paired `.bfbs` files are self-describing FlatBuffer schemas. The `bin`
and `bfbs` files live in
`arc/worlddataraidraid_gem_item_reward_boostdata.bin.trpak`; after Oodle
decompression, `flatc` decodes every record and its `bossDesc`. The counts are
454 Paldea, 133 Kitakami, and 113 Blueberry records, exactly matching the 700
encounters already bundled in `raid_base.json`. Record `no` is the existing
encounter `identifier`, so the join is exact rather than species-based.

## Application envelope

The application begins with `80 33`, followed by a 16-byte `0x012F` header and
a raw LZ4 block at offset `0x12`:

| Offset | Size | Meaning |
| ---: | ---: | --- |
| `0x00` | 2 | Application prefix `80 33`. |
| `0x02` | 2 | Message type `0x012F`. |
| `0x04` | 2 | Opaque message/session value; differs between captures. |
| `0x06` | 4 | Compression value 2. |
| `0x0A` | 4 | Uncompressed size `0xAA0`. |
| `0x0E` | 4 | Opaque header bytes; preserve or deliberately choose and validate. |
| `0x12` | variable | Raw LZ4 block. |

Observed first 18 bytes:

```text
Growlithe: 80 33 2f 01 0f 01 02 00 00 00 a0 0a 00 00 00 00 00 00
Forretress:80 33 2f 01 8b 01 02 00 00 00 a0 0a 00 00 00 00 00 00
Avalugg:   80 33 2f 01 13 00 02 00 00 00 a0 0a 00 00 00 00 28 3a
```

The old assumption that the final four bytes were always zero was false. Their
semantics remain unknown. `sv_raid_bootstrap_codec.encode_application`
correctly preserves all 18 bytes from its template today. A donor-free builder
must expose the opaque/session fields or choose a standard zero form and prove
it on retail.

## Comparative retail corpus

Three complete bootstraps are currently useful:

| Seed | Content | Boss | Stars/level/Tera | RaidPoint |
| --- | --- | --- | --- | --- |
| `BD13FB43` | standard | Growlithe | 2 / 20 / 11 | `RaidPoint_12_1_11` |
| `FDAE7B7D` | standard | Forretress | 4 / 45 / 1 | `RaidPoint_10_01_07` |
| `C72E1D7F` | event | Avalugg | 5 / 75 / 0 | `RaidPoint_13_1_1` |

The Growlithe bootstrap is in `fixtures/tera_raid_retail_victory_full.jsonl`. The
Forretress capture was recovered read-only from commit `da14d92` as
`bin/tera_raid_retail_controlled_tinkatink_first_moves.jsonl`. The Avalugg
bootstrap is the compact `fixtures/sv_raid_reward_donor.bin` fixture.

The Avalugg seed demonstrates why content is mandatory context: resolving
`C72E1D7F` through the bundled normal table selects a different ordinary raid.
Only the event table identifies Avalugg.

## RaidPoint `0x3E8` layout

Offsets in this section are relative to raw `+0x6B8`, the beginning of the
RaidPoint.

### Identity and scalar header

| Relative offset | Size | Evidence-backed meaning |
| ---: | ---: | --- |
| `0x000` | up to 24 | Inline zero-padded ASCII `RaidPoint_*` identifier. |
| `0x018` | 1 | `0x40` in all three captures; likely inline-string metadata/capacity. |
| `0x020` | 4 | Stars/difficulty. |
| `0x024` | 4 | Zero in all samples; unknown. |
| `0x028` | 4 | One in all samples; unknown flag/count. |
| `0x02C` | 4 | Boss level. |
| `0x030..0x04B` | 28 | Mostly zero in standard captures; contains capture-specific/event data. |
| `0x04C` | 4 | Boss HP multiplier in percent-like units. |
| `0x050..0x0DF` | 144 | Raid action/shield parameter block. |
| `0x0E0..` | 16-byte rows | Fixed and lottery reward definitions, then optional bonus rows. |
| `0x3B8` | 4 | Stars/difficulty repeated. |
| `0x3BC` | 4 | Species. |
| `0x3C0` | 4 | Form. |
| `0x3C4` | 4 | Gender (`0` male, `1` female in the samples). |
| `0x3C8` | 4 | Level repeated. |
| `0x3CC` | 4 | Zero in all samples; unknown. |
| `0x3D0` | 4 | Tera type. |
| `0x3D4..0x3DF` | 12 | Mixed semantic/padding bytes; includes apparent stale stack data. |
| `0x3E0` | 4 | 2 for both standard captures, 4 for the event capture; likely category/content. |
| `0x3E4..0x3E7` | 4 | Unknown/padding. |

The bytes at `0x3D4..0x3DF` must not be treated as a stable identifier. The
Forretress capture contains the ASCII-like little-endian words `Effe` and
`Para`, strong evidence that at least part of this tail is uninitialized copied
storage. A generator should zero unknown padding rather than reproduce those
bytes.

The decoded tables establish HP multipliers of 500, 500, 800, 1200, 2000, and
2500 for stars one through six. Every table row supplies its own complete
`bossDesc`; higher-star action schedules are encounter-specific rather than a
single profile per star.

### Action/shield parameter samples

Values below are little-endian `u32`s grouped four per line. Unknown values are
recorded without assigning names.

Two-star Growlithe:

```text
020: 2, 0, 1, 20
030..040: zero except 04C = 500
050..0DF: all zero
```

Four-star Forretress:

```text
020: 4, 0, 1, 45
030: 0xFFFFFC00, 0, 0, 0
040: 0, 0, 0, 1200
050: 60, 40, 9999, 30
060: 0, 334, 20, 80
070: 40, 3, 1, 90
080: 106, 2, 2, 60
090: 0, 3, 1, 40
0A0: 106, 0, 0, 0
0B0..0DF: zero
```

The resolved encounter has extra moves `[106, 0, 106, 0, 0, 0]`; both 106
values occur in the action block. The remaining values are therefore a mixture
of star-level shield defaults and encounter extra-action records.

The retail schema and the capture together resolve the complete word layout:

```text
04C: hpCoef
050: powerChargeTrigerHp, powerChargeTrigerTime,
     powerChargeLimitTime, powerChargeCancelDamage
060: powerChargePenaltyTime, powerChargePenaltyAction,
     powerChargeDamageRate, powerChargeGemDamageRate
070: powerChargeChangeGemDamageRate
074..0D3: six records of (action, timing, value, move)
0D4: doubleActionTrigerHp, doubleActionTrigerTime, doubleActionRate
```

The RaidPoint action enum is `NONE=0`, `BOSS_STATUS_RESET=1`,
`PLAYER_STATUS_RESET=2`, `WAZA=3`, `GEM_COUNT=4`; timing is `NONE=0`,
`TIME=1`, `HP=2`. This ordering explains the captured Forretress words exactly.

Five-star event Avalugg:

```text
020: 5, 0, 1, 75
030: 0x3C135700, 0, 0, 0
040: 0, 0, 0, 2000
050: 65, 30, 9999, 35
060: 0, 0, 20, 75
070: 35, 3, 1, 85
080: 883, 2, 2, 75
090: 0, 1, 2, 50
0A0: 0, 3, 2, 45
0B0: 883, 3, 2, 30
0C0: 334, 0, 0, 0
0D0: zero
```

The event block is not a safe template for ordinary five-star raids.

## Reward representation

Reward records begin at RaidPoint relative offset `0x0E0`, raw offset `0x798`:

```c
struct RewardRecord {
    uint32_t marker;
    uint32_t item;
    uint32_t quantity;
    uint32_t reserved;
}; // 16 bytes
```

The current catalog generator reproduces the ordered fixed and lottery
item/quantity rows from the seed. It does not generate Raid Power/source-4
bonus rows. Those bonuses are player/meal context, not seed-only raid state,
and can be omitted or zeroed by a neutral constructor.

### Two-star Growlithe

```text
0E0: (0, 1125, 3, 0)
0F0: (0, 1961, 2, 0)
100: (0, 566,  1, 0)
110: (0, 1961, 1, 0)  hidden/subject-2 fixed row
120: (2, 88,   1, 0)
130: (0, 1961, 1, 0)
140: (0, 155,  1, 0)
150: (0, 566,  1, 0)
160: (0, 88,   1, 0)
170: (0, 88,   1, 0)  additional definition/duplicate
180: (4, 88,   1, 0)  source-4 bonus
190: (4, 151,  2, 0)  source-4 bonus
1A0: (4, 0,    0, 0)  empty source-4 slot
```

The generated list matches the item/quantity ordering through `0x160`.

### Four-star Forretress

```text
0E0: (0, 1126, 2, 0)
0F0: (0, 1127, 1, 0)
100: (0, 1983, 4, 0)
110: (0, 567,  2, 0)
120: (0, 1983, 2, 0)
130: (2, 1868, 1, 0)
140: (0, 1868, 2, 0)
150: (1, 1126, 1, 0)
160: (0, 157,  1, 0)
170: (0, 1126, 1, 0)
180: (0, 171,  3, 0)
190: (0, 171,  3, 0)
1A0: (0, 1126, 1, 0)
1B0: (0, 89,   1, 0)
1C0: (0, 1983, 2, 0)
1D0: (0, 89,   1, 0)  additional definition/duplicate
1E0: (4, 163,  1, 0)  source-4 bonus
1F0: (4, 89,   1, 0)  source-4 bonus
200: (4, 1868, 5, 0)  source-4 bonus
210: (5, 0,    0, 0)  observed metadata/end row
```

The generated list's 15 item/quantity pairs match `0x0E0..0x1C0` exactly.

### Marker interpretation and safe construction

Markers 0, 1, and 2 all occur among guest-visible rewards, while marker 4 is
associated with independent bonus slots. Their complete enum meanings remain
unknown. Retail tests already prove that an exact custom list made of marker-0
rows works when linked hidden records and bonus rows are cleared. This supports
a conservative donor-free representation using ordered marker-0 rows and zero
unused storage, but a seed-faithful encoder should retain known subject/source
marker rules after they are fully mapped.

Marker 5 is also not proven to be a generic terminator. It follows the
definition/bonus area in the four-star Forretress and five-star Avalugg, but is
absent from the valid two-star Growlithe RaidPoint. The current four-star
constructor reproduces its observed placement after one reserved definition
slot and three zeroed bonus slots; the one- and two-star profiles omit it.

## Seed-derived versus external fields

| Field | Source |
| --- | --- |
| Encounter species/form/level/moves/extra moves | Seed + version/map/progress/content tables. |
| Stars | Seed + progress, or fixed by content type. |
| Tera type | Seed + encounter rule. |
| Boss EC/PID/IVs/ability/gender/nature/size/stats | Seed + encounter/personal data. |
| Fixed and lottery rewards | Seed + encounter reward tables. |
| Shield/action defaults | Star/content tables; exact standard mapping not yet recovered. |
| Event actions/rewards | Active BCAT event tables, not inferable from the seed alone. |
| `RaidPoint_*` string | Map/instance identity, not observed as seed-derived. |
| Four participant PK9s | Lobby/player choices. |
| Raid Power bonus rows | Player/meal context. |
| Application header opaque values | Session/message context; exact semantics unknown. |
| Later battle runtime state | Separate battle simulation/session state. |

## Implemented donor-free builder

`sv_raid_bootstrap_codec.py` now exposes:

- `build_raid_boss_pk9(profile)`;
- `build_raid_point(raid, point_name=...)`;
- `build_seed_bootstrap_raw(seed, ..., players=...)`;
- `build_application(raw, message_value=..., header_tail=...)`;
- `replace_bootstrap_raw(events, raw)`.

The API is explicit about the context boundary above rather than accepting a
misleading bare seed as the complete game state.

Suggested inputs:

```python
build_raid_bootstrap(
    seed,
    version="violet",
    map_name="paldea",
    progress="4star",
    content="standard",
    point_name="RaidPoint_POKELDN_0",
    players=(host_pk9,),
    message_value=0,
    header_tail=b"\0\0\0\0",
)
```

Construction:

1. Resolve the encounter and rewards with
   `pokeldn.sv.raid_generation.generate_seed_raid`.
2. Build the boss party PK9 from `RAID_BOSS_COMMON` plus the generated profile,
   then encrypt it with `pokeldn.gen9.encrypt`.
3. Serialize supplied participant party PK9s and fill unused slots with a
   deliberately canonical species-zero placeholder. Do not copy placeholder
   bytes from a retail donor; captured placeholders contain unrelated default
   values and stale data.
4. Build a zero-initialized `0x3E8` RaidPoint and write only understood fields.
5. Populate all 37 words from the selected encounter's retail-table-backed
   `boss_desc` profile: HP coefficient, shield settings, six extra actions, and
   double-action settings.
6. Write ordered fixed/lottery reward rows; omit neutral player-specific bonus
   rows.
7. Fill the repeated encounter summary at `0x3B8` and zero unknown padding.
8. Concatenate four player PK9s, the boss PK9, and RaidPoint to `0xAA0` bytes.
9. LZ4-compress the plaintext and prepend an explicit 18-byte header, or retain
   only a live replay's opaque envelope fields when replacing sequences 11/12.
10. Split the application across reliable fragments according to the live
    sender's packet budget; there is no semantic requirement that the split be
    the historical sequence-11 boundary.

Generate a two-star ordinary bootstrap and standalone application:

```bash
./.venv/bin/python sv_raid_profile.py BD13FB43 \
  --point-name RaidPoint_12_1_11 \
  --bootstrap /tmp/growlithe-bootstrap.bin \
  --application /tmp/growlithe-012f.bin
```

Supply `--player-pk9 FILE` up to four times to populate participant slots. The
standalone form defaults the opaque header fields to zero. The experimental
host integration instead preserves only the source replay's 18-byte envelope:

```bash
./.venv/bin/python sv_raid_host.py \
  --raid-seed BD13FB43 \
  --raid-player-pokemon HOST.pk9 \
  --generated-bootstrap \
  --keys ~/.switch/prod.keys
```

This removes the raid donor from the complete decoded bootstrap. It does not
remove the source replay dependency from later runtime battle-state messages.
The wrapper selects the existing client-gated replay automatically. This path
is ready for a controlled retail test, not yet a product default.

## Required validation before claiming retail donor-free support

### 2026-10-08 first retail attempt

The generated two-star Growlithe host was launched with seed `BD13FB43` and a
complete generated `0xAA0` bootstrap. The console discovered and associated
with the AP, but displayed “Unable to communicate” and deauthenticated before
the host transmitted replay sequences 11/12.

A controlled donor-backed run using the previously validated Avalugg reward
bootstrap reproduced the same failure. It progressed through Net and Session,
sent identity and channel setup, and received the console's acknowledgements,
but the console never sent the expected `0x7C` port-2 type-3 raid join before
deauthenticating. Consequently this attempt did not exercise or reject the
generated RaidPoint. The current blocker is the earlier lobby/session transition
and must be cleared before retail validation of this encoder.

Comparison with the earlier successful emulator-host capture identified a
host-side race. In the successful run the console's Session type-6 ACK arrived
at +100 ms, just before channel setup; in the failure it arrived at +361 ms,
after the fixed +100 ms channel timer and all 46 identity records had already
run. `sv_host.py` now waits for a matching type-6 ACK before releasing the raid
stream bootstrap and channel setup, then starts identity 20 ms later. A fresh
Session join also clears any stale opening queues. Retail confirmation of this
fix remains pending.

### 2026-10-08 generated-bootstrap battle-load result

The ACK-gated retry cleared the earlier lobby failure. Retail sent the port-2
join, acknowledged generated bootstrap sequences 11/12, and returned both
`load_6e` and `load_73`. The game then crashed after host sequence 14 during
battle initialization.

The capture exposed a participant-array defect independent of RaidPoint. A
successful emulator-host bootstrap contains the joining console's exact
344-byte `0x80332e` lobby PK9 in participant slot 1. The crashed generated
bootstrap left that slot empty. Its missing-player records were also incorrect:
retail consistently uses a static level-1 species-zero record with nickname
`Egg`, Tera sentinel 19, current HP 11, and stats 11/5/5/5/5/5, not an
all-zero level-0 party record.

The host now captures and validates the guest lobby PK9, patches pending
sequences 11/12 before transmission, and withholds sequence 11 if the guest
record has not arrived. Generated empty slots reproduce the retail placeholder
byte-for-byte. This established the participant array as the leading cause to
test in the next retail run.

### 2026-10-08 corrected-participant retail result

The corrected retry succeeded past the previous immediate crash boundary. For
seed `BD13FB43`, retail acknowledged generated sequences 11/12 and returned
`load_6e`, `load_73`, and `battle_93`. There were 397 authenticated datagrams
and zero authentication failures.

The host mistakenly continued the capture-backed stream through replay
sequence 76 instead of performing the normal sequence-20 handoff. The game
never reached playable battle and eventually left the session. Consequently,
this run validates transport and parsing of the generated bootstrap, plus the
participant-array crash fix, but not a playable generated raid. Generated
bootstrap mode now uses the same proven sequence-20 cutoff and five-second host
shutdown as reward-profile mode; that corrected path still requires a retail
test.

### 2026-10-09 shiny-Ralts startup-gate result

A GUI-hosted shiny Ralts run acknowledged generated bootstrap sequences 11/12
but emitted `load_73` without first emitting `load_6e`. The client subsequently
sent `battle_93`, demonstrating that it had advanced while the host remained
deadlocked withholding sequence 13. Because sequence 20 was never reached, the
handoff shutdown was never scheduled and the host had to be stopped manually.

Sequence 13 now accepts either `load_6e` or `load_73` as the retail transition
marker. The later `load_73` and `battle_93` gates remain in place, so this only
removes the invalid assumption that every successful bootstrap emits both load
markers in order.

- Unit-test the generated Growlithe and Forretress boss PK9s against their
  captured decrypted fields.
- Compare every understood RaidPoint scalar with both standard captures.
- Compare generated reward item/quantity order with both standard captures.
- [x] Prove the canonical species-zero participant record passes bootstrap
  loading without the previous immediate crash.
- Prove a synthetic `RaidPoint_*` identifier produces a playable battle.
- Prove the zero-form opaque application header produces a playable battle.
- Retail-test generated one-, three-, five-, and black six-star RaidPoints;
  their parameter blocks are now recovered, but captures remain useful as
  end-to-end validation.
- Test a generated ordinary RaidPoint on retail before integrating it into the
  host's default path.
- Keep event raids explicitly unsupported until their BCAT enemy, action, and
  reward tables are supplied as context.

## Current implementation boundary

Implemented and covered by offline tests:

- seed-to-standard-encounter selection;
- seed-to-boss-PK9 profile generation;
- seed-to-ordered-reward generation;
- `0x012F` LZ4 decode/re-encode;
- standalone donor-free `0x012F` envelope construction;
- zero-initialized RaidPoint construction for all 700 bundled standard
  one- through five-star and black six-star encounter profiles;
- neutral generated reward rows, plus the four-star marker-5 metadata row;
- complete `0xAA0` construction from supplied/canonical participant PK9s, the
  generated boss, and generated RaidPoint;
- complete bootstrap replacement in replay sequences 11/12 while retaining
  only the opaque live envelope;
- host-player PK9 replacement;
- exact custom marker-0 reward lists in a generated RaidPoint, with all
  remaining reward storage zeroed;
- guarded donor-backed exact reward replacement.

For seed `BD13FB43`, the newly generated boss PK9 matches the captured retail
Growlithe PK9 byte-for-byte. The generated standalone application decodes back
to the exact generated `0xAA0` plaintext.

Not yet implemented or retail-validated:

- retail end-to-end validation of generated one-, three-, five-, and black
  six-star RaidPoints;
- event-table input;
- replacement of the later capture-backed battle runtime stream.

The current host and GUI can generate and substitute a complete bootstrap for
supported standard seeds. Omitting a custom list uses seed-derived rewards;
supplying one writes the requested ordered rewards directly into the generated
RaidPoint without loading `sv_raid_reward_donor.bin`. Retail has parsed a
generated bootstrap through `battle_93` for the two-star seed `BD13FB43`.
A playable battle through the corrected sequence-20 handoff, and the generated
exact-list variant specifically, still require retail confirmation. Removing
the bootstrap donor and removing the later battle replay are separate
milestones.

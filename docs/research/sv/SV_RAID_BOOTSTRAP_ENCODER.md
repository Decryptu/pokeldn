# Pokémon Scarlet/Violet Tera Raid Bootstrap Encoder

> Historical donor-era analysis. Production now uses the fully generated
> RaidPoint and sequence-1..20 path. These artifacts remain for regression and
> reverse-engineering evidence only.

## Status

This document describes the validated encoder for the large Scarlet/Violet
Tera Raid bootstrap application message used by game version 4.0.0.

For the continuing work to construct this message without a captured raid
template, including the full `0x3E8` RaidPoint layout, three-capture comparison,
Ghidra call chain, and the exact remaining unknowns, see
`SV_RAIDPOINT_REVERSE_ENGINEERING.md`.

The important result is that raid rewards are **not** encoded as a proprietary
reference bitstream. The message contains a fixed `0xAA0`-byte plaintext
structure compressed as a raw LZ4 block. Reward items and quantities are
ordinary little-endian 32-bit fields inside that plaintext structure.

The retired guarded editor updated 19 linked reward records from the captured
Violet Avalugg seed `C72E1D7F`: 16 guest-visible rows and three
hidden/conditional counterparts. Production `sv_raid_bootstrap_codec.py` no
longer contains that editor; it writes generated reward rows directly. The
historical JSON/CLI experiment is documented in `SV_RAID_REWARD_PROFILES.md`.

## Evidence and validation corpus

The production fixture extracted from the primary retail capture is:

```text
fixtures/sv_raid_reward_donor.bin
```

Properties of that capture:

- Violet 4.0.0;
- reward seed `C72E1D7F`;
- species Avalugg after importing the save into Violet;
- RaidPoint identifier `RaidPoint_13_1_1`;
- application message type `0x012F`;
- reliable application fragments 11 and 12;
- complete compressed application size 1,707 bytes;
- decoded plaintext size exactly `0xAA0` (2,720) bytes;
- 16 displayed reward rows totaling 42 items.

The decoder was checked by decompressing the captured application message and
locating `RaidPoint_13_1_1` at plaintext offset `0x6B8`. This is exactly the
offset independently recovered from the serializer in Ghidra.

The encoder was checked offline by:

1. decoding the captured application to `0xAA0` bytes;
2. recompressing it with liblz4;
3. decoding the new application again;
4. requiring byte-for-byte equality with the original `0xAA0` plaintext;
5. changing all 19 linked item and quantity fields;
6. decoding the changed application and confirming every new field value.

The new plaintext path was then validated on a retail console twice, using
client-gated replay timing:

- all linked item fields set to item 2 produced exactly 42 Ultra Balls;
- all linked item fields set to item 1128 produced exactly 42 Exp. Candy XL.

The respective changed application sizes were 1,700 and 1,702 bytes. The
original is 1,707 bytes. A different compressed size is expected and valid.

## Protocol layers

There are two independent compression layers. They must not be confused.

```text
Pia reliable packet
└── optional reliable-fragment zlib              FLAG_ZLIB
    └── complete application message             fragments 11 + 12
        ├── two-byte application prefix          80 33
        ├── 16-byte 0x012F serializer header
        └── raw LZ4 block
            └── fixed 0xAA0-byte raid plaintext
                └── RaidPoint and reward records
```

The existing `pokeldn.sv.streams` functions handle the outer per-fragment
zlib layer. `sv_raid_bootstrap_codec.py` handles the inner application LZ4
layer.

## Complete application envelope

The known Avalugg application starts with the following 18-byte envelope. The
last two bytes shown (`28 3a`) are part of the opaque header, not LZ4 data:

```text
80 33 2f 01 13 00 02 00 00 00 a0 0a 00 00 00 00 28 3a
```

The raw LZ4 block begins immediately after those bytes, at application offset
`0x12`. The first two bytes are an outer application prefix; the following 16
bytes are emitted by the serializer found in Ghidra.

| Application offset | Size | Captured value | Meaning |
| ---: | ---: | --- | --- |
| `0x00` | 2 | `80 33` | Outer Scarlet/Violet application prefix |
| `0x02` | 2 | `2f 01` | Message type `0x012F` |
| `0x04` | 2 | `13 00` | Opaque message/session value; differs between captures |
| `0x06` | 4 | `02 00 00 00` | Serializer flags; bit/value 2 means compressed |
| `0x0A` | 4 | `a0 0a 00 00` | Uncompressed size, `0xAA0` |
| `0x0E` | 4 | `00 00 28 3a` | Opaque, preserved from template; standard captures use four zero bytes |
| `0x12` | variable | — | Raw LZ4 block through end of application message |

Only the uncompressed-size field is regenerated. All other unknown envelope
fields are preserved from the validated retail template. In particular, do not
assume raw offset `0x0E` is uniformly zero: it differs between the standard and
event captures currently available.

The compressed byte count is not stored in this header. It is determined by
the enclosing reliable message length.

## Ghidra call chain

All addresses below are from the analyzed Violet 4.0.0 `main` image.

### Message object and factory

| Address | Role |
| --- | --- |
| `FUN_71018BB5F8` | Constructor for the large message object; stores type `0x012F` |
| `FUN_71018BB4FC` | Object factory; allocates `0x460` bytes and calls the constructor |
| `PTR_DAT_71046D69B8` | Pointer to the `0x012F` class vtable group |
| `FUN_71018D9FE8` | Constructor for neighboring type `0x012E` |
| `FUN_71019508B4` | `0x012E` factory; useful comparison, allocates only `0x58` bytes |

The size difference was the first strong confirmation that `0x012F` is the
large raid bootstrap rather than an unrelated scalar constant.

### Plaintext construction

The class-specific virtual method `FUN_7100E327FC` constructs a contiguous
`0xAA0`-byte record. It converts five referenced subobjects to fixed `0x158`
byte representations, copies four eight-byte fields, and copies a `0x3C8`
byte tail.

Equivalent layout:

```c
struct RaidBootstrapRaw {
    uint8_t subobject[5][0x158]; // 0x000..0x6B7
    uint64_t raidpoint_head[4];  // 0x6B8..0x6D7
    uint8_t raidpoint_tail[0x3C8]; // 0x6D8..0xA9F
}; // sizeof == 0xAA0
```

The four nominal `uint64_t` fields and the following tail form one contiguous
RaidPoint value in the capture. `RaidPoint_13_1_1` begins at raw offset
`0x6B8` and crosses that boundary naturally.

The five referenced subobjects are serialized through `FUN_7100E329B4`.
The inverse/copy-back virtual method is `FUN_7101E62FE4`.

### Application serialization and LZ4

`FUN_7100E327FC` passes the `0xAA0` record to `FUN_7101592B7C`.

When compression is enabled:

| Address | Role |
| --- | --- |
| `FUN_7101592B7C` | Builds the 16-byte message header and chooses compression |
| `FUN_7101592DAC` | Allocates the compression buffer and invokes the compressor |
| `FUN_7101592E50` | Computes compression bound |
| `FUN_7101592E80` | Wrapper around the six-argument fast compressor |
| `FUN_710071D940` | LZ4 fast compression core |

`FUN_7101592E50` computes:

```text
input_size + floor(input_size / 255) + 16
```

This is `LZ4_compressBound`. The compression wrapper uses a 16 KiB state
buffer and acceleration 1, matching an LZ4 fast/extState call. Standard
`LZ4_compress_default` produces a semantically equivalent raw block accepted
by the same LZ4 decoder; byte-identical compressed output is not required.

## Plaintext RaidPoint and reward area

For the `C72E1D7F` Avalugg donor:

| Raw range | Meaning |
| --- | --- |
| `0x000..0x6B7` | Five fixed `0x158`-byte subobjects |
| `0x6B8..0x6C7` | ASCII `RaidPoint_13_1_1` |
| `0x6C8..0x797` | RaidPoint metadata and encounter/reward state |
| `0x798..` | Fixed-width reward-related records |
| `0xA9F` | End of fixed plaintext record |

The displayed reward records used by the guarded editor have this observed
layout:

```c
struct RewardRecord {
    uint32_t condition_or_source;
    uint32_t item_id;
    uint32_t quantity;
    uint32_t reserved;
}; // 16 bytes
```

All integers are little-endian. The first field is not fully decoded. Values
0, 1, and 2 occur among rewards that appeared on the guest's result screen,
so it must be preserved. The final field is zero in every validated row.

### Validated guest-visible reward records

| Raw offset | First field | Original item | Original quantity |
| ---: | ---: | ---: | ---: |
| `0x798` | 0 | 1127, Exp. Candy L | 1 |
| `0x7A8` | 0 | 1128, Exp. Candy XL | 1 |
| `0x7B8` | 0 | 2064, Bergmite Ice | 5 |
| `0x7C8` | 0 | 567, Resist Feather | 3 |
| `0x7D8` | 0 | 2064, Bergmite Ice | 3 |
| `0x7E8` | 2 | 1862, Normal Tera Shard | 2 |
| `0x808` | 1 | 2064, Bergmite Ice | 2 |
| `0x818` | 0 | 171, Qualot Berry | 3 |
| `0x828` | 0 | 171, Qualot Berry | 3 |
| `0x838` | 0 | 171, Qualot Berry | 3 |
| `0x848` | 0 | 1235, Bold Mint | 1 |
| `0x858` | 0 | 171, Qualot Berry | 3 |
| `0x868` | 0 | 171, Qualot Berry | 3 |
| `0x878` | 0 | 171, Qualot Berry | 3 |
| `0x888` | 0 | 171, Qualot Berry | 3 |
| `0x898` | 0 | 171, Qualot Berry | 3 |

Their original quantities total 42, matching the retail result screen.

Three additional records are linked to definitions used by the visible list.
The earlier compressed-stream Ultra Ball edit changed them along with the
visible records; omitting them in the first plaintext implementation caused
the client to ACK transport traffic but never send its next application
message.

| Raw offset | First field | Original item | Original quantity |
| ---: | ---: | ---: | ---: |
| `0x7F8` | 0 | 1862, Normal Tera Shard | 2 |
| `0x8A8` | 0 | 567, Resist Feather | 2 |
| `0x8D8` | 4 | 1862, Normal Tera Shard | 10 |

The guarded all-item encoder therefore edits these three rows together with
the 16 visible rows. Source-4 records at `0x8B8` (item 89, Big Pearl) and
`0x8C8` (item 92, Nugget) are independent bonus slots. In the first retail
single-entry test, clearing only the 19 linked rows produced the requested
Quick Ball x500 plus Nugget x1, proving that `0x8C8` can be active. Exact-list
mode now clears both independent bonus slots as well.

## Decoder algorithm

Pseudocode for a complete already-reassembled application message:

```python
assert application[0:2] == bytes.fromhex("8033")
assert u16le(application, 0x02) == 0x012F
assert u32le(application, 0x06) == 2

raw_size = u32le(application, 0x0A)
assert raw_size == 0xAA0

compressed = application[0x12:]
raw = LZ4_decompress_safe(compressed, output_capacity=raw_size)
assert len(raw) == raw_size
```

Before reaching this algorithm, each reliable fragment must be decoded with
`pokeldn.sv.streams.decompress` if its Pia reliable flags contain
`FLAG_ZLIB`. The decoded sequence-11 and sequence-12 bytes are concatenated.

## Encoder algorithm

```python
raw = decode_application(template_application)

for offset in validated_linked_reward_offsets:
    assert original RewardRecord matches the donor specification
    write_u32le(raw, offset + 4, requested_item_id)
    write_u32le(raw, offset + 8, requested_quantity)

compressed = LZ4_compress_default(raw)

header = bytearray(template_application[:0x12])
write_u32le(header, 0x0A, len(raw))
changed_application = bytes(header) + compressed
```

The application is then split at the original decoded sequence-11 length,
which is 1,395 bytes for the proven template:

```python
seq11_plain = changed_application[:1395]
seq12_plain = changed_application[1395:]
```

Sequence 11 retains its original reliable flags. Sequence 12 retains its
original reliable flags. Each fragment is outer-zlib-compressed again when
its flags contain `FLAG_ZLIB`.

For the retail-validated native-quantity tests:

```text
original application:       1707 bytes
Ultra Ball application:     1700 bytes
Exp. Candy XL application:  1702 bytes
sequence 11:                1395 bytes, unchanged boundary
original sequence 12:       312 bytes
Ultra Ball sequence 12:     305 bytes
Exp. Candy XL sequence 12:  307 bytes
```

## Current CLI

The supported interface is a versioned JSON profile:

```text
format:   pokeldn.sv.raid-rewards.v1
template: violet-4.0.0-c72e1d7f-avalugg
mode:     exact
rewards:  1..16 ordered {item_id, quantity} entries
```

The following commands record the historical donor-profile workflow. Its helper
scripts no longer ship; production writes exact rows directly into the generated
RaidPoint.

Create and host a profile (historical):

```bash
./.venv/bin/python tools/sv/research/sv_raid_rewards.py create \
  --reward 15:500 --output quick500.json
tools/sv/research/sv_raid_reward_host.sh 000F34C3 quick500.json
```

The direct host option is `--raid-reward-profile PROFILE.json`. The obsolete
compressed-stream and plaintext experiment switches have been removed.

Historical retail runs remapped all linked rows to Ultra Ball and Exp. Candy
XL while retaining native quantities. The retail-validated results are:

- Pawniard remains the fight/catch Pokémon from fight seed `000F34C3`;
- the reward identity remains backed by the coherent Avalugg RaidPoint donor;
- 42 Ultra Balls;
- 42 Exp. Candy XL.

The custom quantity test changed one visible row to Quick Ball x500 and
cleared the other linked rows. Retail awarded Quick Ball x500. It also awarded
Nugget x1, which identified `0x8C8` as an independent active bonus slot. Exact
profile mode now clears both independent bonus slots before writing the list.

Raid replay is always client-gated. Ungated startup can race ahead of the
client's application messages and leave the console communicating, so it is
no longer exposed as a selectable mode.

## Safety and coherence checks

The implementation refuses to encode unless all of these are true:

- application prefix is `80 33`;
- message type is `0x012F`;
- serializer compression flags equal 2;
- declared plaintext size is `0xAA0`;
- LZ4 decompression produces exactly `0xAA0` bytes;
- RaidPoint identifier at raw offset `0x6B8` is `RaidPoint_13_1_1`;
- every one of the 19 linked original records matches its expected first field,
  item ID, quantity, and zero reserved field;
- both independent bonus records at `0x8B8` and `0x8C8` match their expected
  source, item, quantity, and reserved fields;
- the plaintext remains exactly `0xAA0` bytes after editing;
- the recompressed message remains long enough to use both reliable fragments.

These guards prevent accidentally applying donor-specific offsets to another
RaidPoint layout or to an already-mutated/corrupt application stream.

## What is now possible

For the validated Avalugg donor, the encoder can independently set:

- an ordered exact list of 1 through 16 visible `{item_id, quantity}` entries;
- arbitrary per-row identities and quantities from 1 through 999;
- a one-entry Quick Ball x500 list, as demonstrated on retail hardware;
- all linked records at once for native-quantity control profiles;
- item IDs outside the old one-byte compressed-literal range.

Because editing occurs before LZ4, changes are no longer constrained by
compressed token widths, page/remainder forms, apparent references, or keeping
the compressed message the same length.

## Current limitations and next work

The following are not yet claimed:

- generation of an entire RaidPoint from only a seed without a coherent donor;
- decoded meanings for the first record field or the conditional records;
- portability of the same raw offsets to every RaidPoint/template;
- retail validation of every possible multi-row combination;
- item-database validation or guarantees beyond the game's inventory limits;
- a retail rerun of the corrected exact-list mode after clearing the newly
  identified Big Pearl and Nugget bonus slots.

The natural extensions are:

1. map the remaining conditional/host-only record selectors;
2. compare decompressed RaidPoints from other seeds to identify stable fields;
3. replace the donor-specific layout with a typed RaidPoint parser;
4. generate the complete raw RaidPoint structure directly from raid metadata
   and seed-derived rewards.

## Why earlier mutation experiments behaved strangely

The previously studied 125-byte region at compressed application offsets
`0x606..0x683` lies inside the LZ4 block. It is not the native reward object.
Apparent item literals and repeated references were consequences of LZ4
literal runs and back-references.

This explains the historical results:

- some same-width item substitutions happened to leave a valid LZ4 stream;
- changing individual amount bits altered match lengths, offsets, or literals;
- some mutations decompressed to corrupt RaidPoint data and displayed Egg or
  No item entries;
- other mutations made the LZ4 stream invalid and were rejected before the
  client sent its next application-level handshake;
- copying a locally coherent-looking compressed region failed because LZ4
  references depend on earlier decompressed bytes.

Those experiments were still valuable: they proved the reward-bearing region,
provided high-value donor captures, and established reliable battle/reward
handoff behavior. They should now be treated as historical controls rather
than the production encoding method.

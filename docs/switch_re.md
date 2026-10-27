---
title: Reverse-engineering a Switch title
nav_order: 3
---

# Reverse-engineering a Switch title

This page covers reading a retail Switch game's code in place, for Unity/IL2CPP (BDSP) and native
C++ (Sword / Shield) titles.

## Order of work

1. Search published sources for a constant, including the NintendoClients wiki's per-game pages:

       gh search code "<a constant, a field name, a class name>" --limit 20
       gh api repos/kinnay/NintendoClientsWiki/contents/<Page>.md --jq .content | base64 -d

2. Look for existing decompilations (`TeamLumi/opendpr` for BDSP) and clients sharing the game key.
3. Name everything in one build's executable and metadata.
4. Verify in the binary.
5. Search a key space last: one wrong input gives a confident negative.

## Getting the executable out

### From an NSP

An NSP is a PFS0 of NCAs. The title key is in `<rights id>.tik`: encrypted key at `+0x180`, rights id
at `+0x2A0`; its last byte *n* selects `titlekek_{n-1}`. A sparse file (`dd` the needed ranges into a
`truncate`d file) passes hactool's bounds checks.

### From an XCI

`tools/switch/xci_read.py` walks HFS0/PFS0, decrypts NCA headers and prints each section's offset,
counter and key; a cartridge NCA's body key is key area slot 2 under
`key_area_key_application_<max(crypto_type, crypto_type2) - 1>`.

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program
    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca <id> --exefs 0 --extract main

Traps: `fs_type` is at +0x2 and the hash type at +0x3 (hactool swaps the names); the section counter
is used reversed.

### From a RomFS

Sections are AES-128-CTR (counter: section CTR and `offset >> 4` big-endian), so any range decrypts
alone. `tools/switch/romfs_read.py` walks and extracts, refusing a header whose size field is not
`0x50`. Trap: hactool aborts on a `prod.keys` line of 34 hex digits and segfaults on `--listromfs`
over a sparse file.

## Naming everything first

- IL2CPP: `global-metadata.dat` plus the same build's executable give Il2CppDumper every C# method.
- C++ RTTI: `tools/switch/rtti_names.py` names `nn::pia` classes from relocations (279 in BDSP, 252 in
  Sword/Shield). `LocalProtocol` versus `LanProtocol` separates LDN from LAN key derivation.

## A constant only in the metadata

A `byte[]` default of a `[Serializable]` C# class lives only in `global-metadata.dat`, as
`Field$<PrivateImplementationDetails>.<SHA-1>`, reached through `InitializeArray` in the constructor.
BDSP's game key seed is stored this way.

## Check which version you dumped

BDSP's base defines 24 network messages, 1.3.0 defines 65:

| struct | base | 1.3.0 ([the protocol page](bdsp_protocol.md#framing)) |
|---|---|---|
| `PosData` | `Vector3 pos, short rotY`, 16 bytes | `ushort posX, ushort posZ, short rotY`, 6 bytes |
| `JoinData` | two fields fewer, aligned | `byte, byte, byte, short, Vector3`, 17 bytes unaligned |

A base-dump layout decodes a 1.3.0 capture into plausible nonsense. `strings global-metadata.dat | grep NetPlayerNameData` finds 1.3.0 only.
Constants survive an update; structures do not.

## Reading a game update's RomFS

An update's RomFS is a BKTR section over the base's; `tools/switch/bktr_read.py` composes its
relocation and subsection tables:

    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp \
        --extract /Data/Managed/Metadata/global-metadata.dat

Trap: an XCI's update partition holds system titles' Program NCAs; pick the base by the update's title.

## Finding callers

Scan for `bl` and the tail call `b`: BDSP's `ANetData<SelectData>$$SendReliableData` has only `b`
callers. A method with no branch to it may be a delegate registered through ADRP/ADD
(`arm64_xref.py`).

Traps: `arm64_xref.function_start` can cross `udf` padding into the previous function; bounding a function by "N bytes after entry" can run past its `ret`; `mov w0,
#0x80` is an ORR-immediate, invisible to a byte sweep.

## Calling into nnSdk

An nnSdk call goes through a GOT slot named by a JUMP_SLOT relocation (`tools/switch/nso_imports.py`).

## Trainer names

Every Switch title's trainer record carries a language id beside the player name (PKHeX's LanguageID:
1 Japanese, 2 English, 3 French, 4 Italian, 5 German, 7 Spanish, 8 Korean, 9 and 10 Chinese), and
the game draws the name in that language's font. A retail Japanese Scarlet drew the kana name キリコ
in narrow half-width glyphs while the record said English (2), next to the same name at full width
from a Japanese save. `pokeldn.trainer_language.for_name` picks the id a written name needs: kana
Japanese, hangul Korean, Chinese characters Japanese unless the record is already Chinese; a Latin
name keeps the recorded id. Each title's identity writer applies it:

| title | where the language sits |
|---|---|
| Scarlet / Violet | record 1 `+0x11` |
| Legends Z-A | the 1400 identity value's third integer, one byte before the name |
| Sword / Shield | MyStatus `+0xA7`, TrainerCard `+0x1B`, the profile's language bits |
| Brilliant Diamond / Shining Pearl | PlayerInfo and `TradeTranerData` language bytes |
| Let's Go | the first message's MyStatus `+0x35` |
| Legends Arceus | the data exchange record `+0x22` |

## The tools

All offline, over `pokeldn.switch`:

    tools/switch/nso_read.py     an NSO's segments decompressed at their memory offsets
    tools/switch/nso_relocs.py   RELA and RELR relocations (modern titles use RELR)
    tools/switch/arm64_xref.py   ADRP cross-references, BL call graph, function starts
    tools/switch/arm64_dis.py    capstone disassembly

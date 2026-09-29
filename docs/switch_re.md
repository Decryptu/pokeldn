---
title: Reverse-engineering a Switch title
nav_order: 3
---

# Reverse-engineering a Switch title

Reading a retail Switch game's code without unpacking it: BDSP (Unity/IL2CPP, 7.3 GB of NSPs, 3.5
GB free) and Sword / Shield (native C++, a 13.3 GB XCI on a network share).

## Order of work

1. Search published sources for a constant in hand. Code search reaches inside the
   NintendoClients wiki, including per-game pages its summary tables do not link:

       gh search code "<a constant, a field name, a class name>" --limit 20
       gh api repos/kinnay/NintendoClientsWiki/contents --jq '.[].name'
       gh api repos/kinnay/NintendoClientsWiki/contents/<Page>.md --jq .content | base64 -d

   Summary tables give derived values; the per-game, Pia-version and application-data pages give
   the rule.
2. Look for the game's code already dumped: a C# recreation (`TeamLumi/opendpr` for BDSP) reads
   faster than IL2CPP output; a game key finds third-party clients (Sword/Shield's: four LAN-mode
   clients).
3. Get executable and metadata of one build; name everything first.
4. Read the binary to verify transcriptions and find the unwritten (BDSP's `cryptoKeyDataSeed` and
   its version rule).
5. Only then search a key space: one input pinned wrong gives a confident negative.

Decrypting a Pia LDN title takes its passphrase, `cryptoKeyDataSeed`, local communication version,
the advertisement and each sender's MAC ([The Pia layer](pia.md)).

## Getting the executable out

### From an NSP

An NSP is a PFS0 archive of NCAs; the executable sits near the end of a multi-GB NCA.

1. Parse the PFS0 header directly: hactool's `--listfiles` offsets are relative to the data base.
2. Decrypt the title key from `<rights id>.tik` (the rights id is the NSP's filename): encrypted key
   at `+0x180`, rights id at `+0x2A0`, absolute. Its last byte is the key generation *n*, which uses
   `titlekek_{n-1}`. hactool takes the encrypted key on `--titlekey`; `xci_read.py` reads the
   ticket itself.
3. Build a sparse file: `dd` the NCA's head, `truncate -s` to its real size, `dd ... seek_bytes
   conv=notrunc` the needed ranges. 109 MB on disk stands in for 2.7 GB and passes hactool's bounds
   checks (`du -h` shows the real size, `ls -l` does not).

### From an XCI

`tools/switch/xci_read.py` walks HFS0 partitions (or an NSP's PFS0), decrypts NCA headers in place
(AES-128-XTS under `header_key`, big-endian sector tweak) and prints title id, content type, key
generation and each section's offset, counter and key:

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program

A cartridge NCA has a zero rights id and no ticket: the body key is key area slot 2 under
`key_area_key_application_<max(crypto_type, crypto_type2) - 1>`. An update's exefs is section 0 of
its Program NCA, an ordinary CTR PartitionFS:

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca <id> --exefs 0 --extract main

Traps: the FS header's `fs_type` is at +0x2 and the hash type at +0x3 (hactool's struct swaps the
names); the 8-byte section counter is used reversed.

### From a RomFS

NCA sections are AES-128-CTR under the title key (counter: the section's CTR value and `offset >> 4`
big-endian), so any range decrypts alone. `tools/switch/romfs_read.py` walks, greps and extracts
from a 4.2 GB RomFS off the container, raising unless the header's size field reads `0x50`, where a
wrong key, offset or counter shows first. hactool aborts on a `prod.keys` line of 34 hex digits and
segfaults on `--listromfs` over a sparse file missing the tables.

## Naming everything first

A retail Unity title has two independent naming layers:

- IL2CPP metadata, the C# surface: `global-metadata.dat` (romfs `Data/Managed/Metadata`) and the
  executable of the same build give Il2CppDumper every class and method RVA.
- C++ RTTI, the native surface: `type_info` name pointers and vtable `type_info` pointers are
  ordinary relocations. `tools/switch/rtti_names.py` finds 279 `nn::pia` classes and 2269 virtual
  methods in BDSP, 252 and 2036 in Sword/Shield.

The owning class (`LocalProtocol` or `LanProtocol`) tells the LDN session-key derivation from the
near-identical LAN one. A vtable with holes is a multiple-inheritance group: the holes are the next
sub-object's offset-to-top and typeinfo.

## A constant only in the metadata

A constant `byte[]` default of a plain `[Serializable]` C# class (not a `ScriptableObject`) is
written by its constructor with `RuntimeHelpers.InitializeArray` over a static field of
`<PrivateImplementationDetails>`, whose bytes live only in `global-metadata.dat`'s
field-default-value table. The constructor's ADRP/LDR pair names a metadata-usage slot resolving to
`Field$<PrivateImplementationDetails>.<HEX>`, the SHA-1 of the data; read the value by field name
and verify by hashing. BDSP's 16-byte game key seed came out this way. Native C++ constants are in
rodata, found by cross-reference.

## Check which version you dumped

Base game and update are separate NSPs. BDSP's base defines 24 network message classes, 1.3.0
defines 65; `PosData` went from `Vector3 pos, short rotY` to `ushort posX, ushort posZ, short rotY`
(16 bytes to 6) and `JoinData` gained two fields and lost its alignment, so a base-dump layout
decodes a capture into plausible nonsense. Checks:

- `strings global-metadata.dat | grep` for a class only one version has: BDSP's base has
  `NetDataTradeStandbyData` (deleted by the update) and lacks `NetPlayerNameData` (added; 1.3.0's
  metadata is 12,496,504 bytes).
- Divide a captured length by the struct size: a 72-byte list of points is 12 of 6, never 16-byte
  ones.

Constants survive (BDSP's base-metadata key seed decrypts 674 of 674 packets from an updated
console); re-read anything structural a capture has not confirmed.

## Reading a game update's RomFS

An update's RomFS is a BKTR section patching the base game's. Two tables at its end, under the
section's ordinary CTR, in 0x4000-byte buckets keyed by offset (hactool `bktr.c`), decide every byte:
the relocation table maps a virtual range to the update's section or the base RomFS (`is_patch`);
the subsection table gives each physical range of the update a counter value replacing bytes 4..8
of the section counter. `tools/switch/bktr_read.py` composes both into one seekable section:

    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp \
        --extract /Data/Managed/Metadata/global-metadata.dat

## Finding callers

Scan the image words for `bl` (`100101` plus a signed 26-bit word offset) and the tail call `b`
(`000101`), which a one-line C# forwarder compiles to: BDSP's
`ANetData<SelectData>$$SendReliableData` and `ANetData<TransitionData>$$SendReliableData` have no
`bl` callers and nine `b` ones, in the Union Room's context menus. A method with no branch to it may be
a delegate registered as an `Action` through an ADRP/ADD pair (`arm64_xref.py`), as with
`TradeStateModel`'s `WriteSaveData`, `FirstSave` and `SendTradeState`.

Traps: `arm64_xref.function_start` walks back through `udf` padding and can credit a store to the
preceding function (check the prologue); bounding a function by "N bytes after its entry" runs past
its `ret` into the next body; `mov w0, #0x80` is an ORR-immediate on ARM64, invisible to a byte
pattern sweep, so decode constants with a disassembler.

## Calling into nnSdk

A call into nnSdk goes through a GOT slot filled by a JUMP_SLOT relocation naming the symbol:
cross-reference the slot (`tools/switch/nso_imports.py`), then count callers of its one PLT stub.

## The tools

Besides `xci_read.py`, `romfs_read.py`, `bktr_read.py` and `rtti_names.py` above, all offline:

    tools/switch/nso_read.py     an NSO's three segments decompressed (pure-Python LZ4) at their
                                 memory offsets: a file offset is an address
    tools/switch/nso_relocs.py   MOD0 -> dynamic -> relative relocations, RELA and RELR. Vtable slots
                                 fill at load time, so "who points here" is a relocation question;
                                 modern titles use RELR, where a RELA-only reader finds nothing
    tools/switch/arm64_xref.py   ADRP(+ADD|+LDR) cross-references, BL call graph, function starts
    tools/switch/arm64_dis.py    capstone window disassembly

---
title: The sync framework
parent: Sword and Shield
nav_order: 2
---

# Messages, contents and routing

The publish/subscribe framework above Pia. A message is a u16 LE id, a discriminator byte, a zero
byte, and a protobuf body.

## Where a message id comes from

Low ids come from a table of 838 24-byte records at `0x01BBFFA0`, `{u64 handler slot, u32 0x402,
u32 id, u64 0}`, ids 1..880. High ids are base plus offset.

## Contents and holders

Each content registers three holders (registrars `0x010ccd90` content 30, `0x010da7d0` 40,
`0x010d5150` 50), adding a base to its offset `ldrh [content+0x372]` and passing each to
`0x006daeb0(manager, &holder, flag)`:

| id | holder | flag |
|---|---|---|
| 10000 + offset | `0x010dd910` | 1 |
| 20000 + offset | `0x010d85f0` | 0 |
| 30000 + offset | `0x010d0980` | 0 |

The 40000 family is minted a layer lower (`ldrb w20,[x0,#0x28]`, `add w24,w20,#-0x63c0`,
`strh w24,[x20,#0x160]`): 40030 / 40040 / 40050.

A holder without a listener drops silently (`0x010d81d0`). Nothing reaches the 20000-base holder of
content 40 or 50: 20040 and 20050 are inert.

### The 30000 holder

The 30000+offset holder (`0x010d0980`, vtable GOT `0x02618620` = `0x02528100`, no RTTI) carries
`gflnet.p2p.framework.pb.SequenceDataHolder`:

    SequenceDataHolder    oneof message {
                            1 CancelAccepted        cancelAccepted
                            2 RequestCancel         requestCancel
                            3 RequestCancelAll      requestCancelAll
                            4 RequestForcedProceed  requestForcedProceed }
    CancelAccepted        { 1 int32 currentSeqNo; 2 bool  isForced    }
    RequestCancel         { 1 int32 currentSeqNo }
    RequestCancelAll      { 1 int32 currentSeqNo }
    RequestForcedProceed  { 1 int32 currentSeqNo; 2 int32 targetSeqNo }

Parser `0x006a7580`; the receive (slot 8 `0x008b9590`) calls listener slot (case - 1) of
`[holder+0x168]`. Shield 1.3.2 builds only CancelAccepted (`0x006a3db0`, called from the send
wrapper `0x008b7420` and two reply jobs in each of ten sync contents). Retail trades never carry
cases 2 to 4; a console still acts on them ([content 40](swsh_trade.md#the-cancel-and-proceed-messages)).
Content 40's instance, 30040, port 0:

    RequestForcedProceed{c, c+1}   58750000 2204 08<c> 10<c+1>     c=0: 58750000 2204 0800 1001

### The three trade contents

`0x010c9280` builds the session: content 30 (the box exchange) at `+0x120`, content 40
(SyncSaveDataHolder) at `+0x148`, content 50 (PokemonTradeDataHolder) at `+0x2b0`; own Pokemon
`+0x68`, theirs `+0x70`; trade state (1..10) `+0x140`, error code `+0x144`; `+0x418` sends command
3 on the first frame and `+0x419` is the role bit that suppresses it. Content 50 initialises in
state 1, content 40 in state 6.

## The routing path

    0x006a9a20   the sync pump, from the trade session update
    0x006db3b0   the poll: per registered entry, drain both streams of its kind (byte +8)
    0x006a8490   stream A: mesh port [pia+0xd0+kind*4], Pia protocol 0x7C
    0x006a84f0   stream B: mesh port [pia+0xd8+kind*4], Pia protocol 0x80
    0x006db9c0   drain: slot 0x78 fills (sender*, length) and the buffer at manager+0xf0
    0x006db620   dispatch: match the entry, call the holder's slot 8
    0x010d81d0   content 50's 10000-base holder: parse, call the listener's slot 0
    0x010d5e40   the listener: sender to station index, memcpy 0x158, invoke

### The application header

A payload is `struct.pack("<HBB", id, discriminator, 0)` then the body, built by `0x006db840` and
parsed by `0x006db620`. The discriminator is a generation counter (`[content+0x370]`, +1 mod 255,
`0x008b6670`) pushed into `[manager+0x480f0]`; a forced CancelAccepted steps it on content 40
(`0x006db470`) and registrars zero it (`0x010d53a0`). A trade with no forced CancelAccepted carries zero throughout.

### Reading the registrations live

    manager = read_u64(read_u64(main + 0x02616750))     0x006a9a70, the poll's caller
    count   = read_u64(manager + 0xD8)                  0x006db3dc
    array   = read_u64(manager + 0xD0)                  0x006db3e0
    entry i = array + i * 0x10                          0x006db3e4
    id      = holder's vtable slot 7, called at 0x006db740 (`ldr x8, [x8, #0x38]`)

Slot 7 returns `[holder+0x160]`. The list is empty on an idle screen; a seated link trade adds two
entries; Mystery Gift adds none.

### Dispatch gates, ports and senders

An entry is 16 bytes: holder, kind at +8, flag at +9 (1 only for 10000+offset):

    id == holder->slot7()
    entry[8] == the drain's kind
    entry[9] ? header[2] == [manager+0x480f0] : no check

Kind is the mesh port: 0 for content holders (20030, 10050, pings), 1 for the 40000 family
(`0x006daf40(manager, &holder, 1, 0)`). The sender is a transport pointer resolved by `0x006b5850`
(`mesh->GetStationIndex`, 0xfd on failure); loopback passes `[[0x2616a30]]+0xf0`. `Data.ownerId`
plays no part on 10050.

## The `Data` envelope

`gflnet.p2p.sync.pb`, `data.proto`:

    1  uint32  syncId        the content offset       30 / 40 / 50
    2  uint32  elementId     the base                 10000 / 20000
    3  uint64  ownerId       the sender
    4  uint64  clock
    5  bytes   body          four bytes in a pair; a 344-byte PK8 in a 40050

The 40000 holder's listener is `element+0x18`; its slot 0, `0x006d59f0`, routes:

    [Data+0x14] == [listener+0x10]        syncId, the element's offset
    walk [listener+0x28] .. [+0x30]       sub-elements, 0x90 bytes each
      [Data+0x18] == [sub+0x62]           elementId, u16
      [Data+0x20] == [sub+0x68]           ownerId, u64
    sub->vtable at 0x48 (sub, body, len, [Data+0x28])     body and clock
    otherwise: ret                        dropped silently

### Sub-element kinds

| kind | constructor | vtable | `+0x88` at birth | slot 9, receive: size check, store to `+0x88` |
|---|---|---|---|---|
| 32-bit | `0x006d5c00` | `0x2512bc8` | 0 | `0x006d5f20`: 4 bytes |
| pair (the phase) | `0x006d6160` | `0x2512c90` | `0xfc18fc18` | `0x006d6490`: 4 bytes |
| 16-bit | `0x006d66d0` | `0x2512d58` | 0 | `0x006d69f0`: 2 bytes |

A receive then sets `[sub+0x78] = clock` and `strh 0x0100 -> [sub+0x60]` (ready byte `+0x61`); slot
7, the hashed value, returns the clock. The constructor takes the element `x0` (`+0x80`), elementId
`w1` (`+0x62`), ownerId `x2` (`+0x68`), flag `w3` (`+0x70`).

The sync element (`0x006d3f80`) is built once per sync content (content 30 at `0x010ce604`, 50 at
`0x010d6904`, 40 at `0x010dc264`). Vtables from `0x2512b28`:

| offset | vtable | role |
|---|---|---|
| `+0x00` | `0x2512b38` | primary, 6 slots; 2, 3, 4 are the three constructors with w3 = 1 |
| `+0x08` | `0x2512b78` | interface A: the 32-bit kind |
| `+0x10` | `0x2512b90` | interface B: the pair, the 16-bit kind |
| `+0x18` | `0x2512bb0` | the router listener, slot 0 = `0x006d59f0` |

The mint `0x006d44e0` builds four channels: `+0xd0` holds per station a 32-bit sub-element,
elementId 10000 (the quorum hash); `+0xf0` holds at `+0x38` a 16-bit sub-element, elementId 20000,
owner 0 (the [shared value](swsh_trade.md#the-phase-is-the-elements-field)) and per station a pair,
elementId 20000; `+0x110` is the list the quorum hash walks.

### The quorum hash

The four bytes on elementId 10000, built by `0x006d7b40` at `element+0xa8`:

    h = 0
    for sub in subs:
        if (!sub[+0x61]) { h = 0; break }        any station not ready -> zero
        h = crc32(le32(h + sub->slot7()))        slot 7 is the clock

Non-zero means every station is ready. `0x0065de30` is `zlib.crc32`; `0x0065df04` (poly `0x8005`) is
a CRC-16. The walked list `element+0x110` is `0x006d48b0`'s copy of `+0x40` keeping entries with
`+0x68` zero.

The chain covers the sender's elementId 0 and 1 (no owner), then its own elementId 20000. A hosting
Sword's non-zero hashes match, e.g. content 50:

    elementId 0, no owner      clock 2304   the host's own Pokemon (344 bytes)
    elementId 1, no owner      clock 2313   the partner's Pokemon, sent back
    elementId 20000, host      clock 2278   then 2338 after its pair moved
    crc32 chain                8ffa0f2e     then b3615e90

A joiner that echoes the host's hash completes a trade against a hosting Sword.

## The party payload on protocol 0x84

`ReliableBroadcastProtocol` carries the 3456-byte trade snapshot in three fragments until acked;
the third is zlib (Pia flag 0x10): 1404 + 1404 + 157 raw, the last inflating to 648.
`trade_payload.py` refuses any other total. Layout (as in `kwsch/PokePiaSWSH`,
`lincoln-lm/swsh-lan-client`):

    0x000  six PK8 records, party form, 0x158 each          -> 0x810
    0x810  u32   party count
    0x814  MyStatus, 272 bytes      TID/SID at 0xA0, trainer name at 0xB0
    0x924  TrainerCard, 456 bytes   trainer name at 0x00, save start date at 0x170
    0xAEC  the player profile, 266 bytes                     -> 0xBF6
    0xBF6  392 bytes, the Battle Stadium block; zero for Link Trade
    0xD7E  2 bytes of padding                                -> 0xD80 = 3456

MyStatus and TrainerCard are PKHeX save blocks (`Saves/Substructures/Gen8/SWSH/`). The builder is
`0x0110c180`, the receiver `0x0110cff0`. Link Trade (`0x010967f0`) and password matching
(`0x00bd80f4`) pass no Battle Stadium block; Battle Stadium (`0x00b2d7d0`) passes one.

### The Battle Stadium block

0x180 bytes of data, a u64 length; the reader `0x00b2d9fc` requires length 0x118. Producer
`0x00b2eb60`. From 0xBF6:

    0x000  u32    CRC-16 (0x8005) of the 0x22fc-byte regulation core (0x008ff9e0;
                  regulation_preset_core_%d.bin)
    0x004  0x100  the team's signature: +0x36 of the 0x136-byte team descriptor at match+0x98
    0x104  4      zero
    0x108  u64    the manager's optional (value +0x1ab8, flag +0x1ab0), zero unless match type 3
    0x110  u8     the manager's byte +0x191c when 0x00adb920 yields an object and 0x00b1ce10(0) == 2
    0x111  u32, u16, u8   team descriptor +0, +4, +6
    0x118  0x68   zero
    0x180  u64    length, 0x118

The receiver `0x00b2e590` compares the partner's CRC with its own (`0x00b2e760`); the result is 9
when both hold, else 10.

The team descriptor sits at match+0x98 of an optional at match+0x70, written only by `0x00ad9cf0`
from the Battle Stadium matching update `0x00ad5750`. The team download job (`0x014f7fd0`) fills it:
`+0x00..+0x2f` six u64 from the result holder `+0x38`, `+0x30..+0x35` six bytes from `+0x68`,
`+0x36..+0x135` from `+0x6e`, then overwritten by the `v1/validate` signature. The holder takes the
0x158-byte entry of the team list (`0x0150320c`) whose key matches the selected key:

| key | entry |
|---|---|
| (1, team) | a save battle team: six u64 `box \| slot << 32`, from `save+0x525 + team*12 + i*2`; name at `save+0x4a0 + team*0x16` |
| (2, i) | a stored record: bytes 0x26..0x15b of a 0x87f-byte record (`0x01430670`) |

The signature is RSA-2048, PKCS#1 v1.5, SHA-256, checked by `0x011aedf0(team, v, sig)`, the only
caller of `nn::crypto::detail::BigNum::ModExp` (PLT `0x018fff50`). The signed message is the
stored 0x148-byte PK8s of the team, the key version `v` as BE u16, then `00 01`. The console holds
only the public key; the image names `https://v3-lp1.vp.n.srv.nintendo.net/v1/public_key` and
`.../v1/validate`, so a Nintendo server presumably signs. Link Trade never reaches the check.

`v1/validate` (`0x011a2a70`) sends a NUL-terminated string (the `v1/public_key` body), the key
version as BE u16, the console's version `0x2D` (Shield) as BE u16, `00 01`, a BE count and the
0x148-byte records. The reply parser `0x011a2870`: byte 0 a status (2: stale key, fetch again),
bytes 5-6 a BE count n clamped to 6, n BE u32, and on status 0 a 0x100-byte signature.

The match type is slot 8 of vtables `0x2538238`, `0x2538358`, `0x2538478`: 1 casual, 2 ranked, 3
online competition. They are built by `0x00adcfb0(obj, mode)` from `StateBtlSpotTop` (`0x00b23080`).
Block `+0x108` is written by `0x00adc8b0` from `StateBtlSpotCompTop` with the u64 at 0x33C0 of save
block `0x88F6D6AE` (0x33D0 bytes; the preceding key `0xEEE5A3F8` is PKHeX's `KOfficialCompetition`).

### The player profile

266 bytes at 0xAEC, also the beacon's record at 0x1F ([session](swsh_session.md#taking-a-seat)).
`0x01111970` copies it from the singleton `[0x2610958]` (+0x310 to +0x564); `0x01125080` packs all
groups or none; bit-packed groups are LSB first. `trade_payload.read_tail` decodes it.

    0x00  16  nn::oe::GetPseudoDeviceId
    0x10  16  nn::account::GetUserId, the account Uid
    0x20   8  nn::account::GetNetworkServiceAccountId, or zero
    0x28  24  trainer name, UTF-16, from MyStatus+0xB0; stale bytes after the terminator
    0x40  25  appearance, bit-packed:
                bit 0      MyStatus+0xA5 (gender) != 0
                bit 1      set by 0x0111cfec; 0 in every capture
                bits 2-5   MyStatus+0xA7, the language (3, French)
                bits 6-7   zero
                8 bits     MyStatus+0xCC
                17 x 10    the model 0x0111dd60 unpacks from the MyStatus bitfield at +0x00
                2, 2, 10   the last three of that unpacking
    0x59  55  position samples, bit-packed:
                2, 2 bits  `a` and `b`, below
                8 bits     generation: random at ring reset (0x00eb98a8), +1 per re-seed
                8 bits     player object byte +0x136 (7 in every capture)
                3 x 17     at 0x5C, 0x6D, 0x7E, newest first: 5-bit counter (+1 per push);
                           3-bit state (+0x1c8, below); x, y, z floats; yaw in radians.
                           0x00ebf590 pushes at most once a second from the field object's
                           +0x60 (position) and +0x50 (rotation)
                8 bits     at 0x8F: player object byte +0x140 (1 in every capture)
    0x90  37  activity, bit-packed: an 8-bit kind (13 in trade), an optional 28-byte part,
              a 24-byte field, a u16 at 0xB2, a bool; only kind and u16 non-zero. The u16 is the
              location, the line of `script/place_name.dat`, PKHeX's met-location id
              (170 Challenge Beach)
    0xB5  37  two more groups, zero in every capture
    0xDA  32  sixteen u16 records (`0x010f5060`): Record8 indexes 6, 32, 0, 33, 17, 27, 34, 24,
              12, 3, 10, 35, 38, 7, 36, 37, each clamped to 0xFFFF (PKHeX `RecordList_8`)
    0xFA   8  an optional u64, zero in every capture
    0x102  8  zero

A receiver (0x00dd5e24) stores the position at +0xB0 and the yaw, as a quaternion, at +0xA0.

The sample state (`+0x1c8` of `[[0x261bd18]]`, set by `0x00ebf570`) is 0 until the field sets it; the
push returns at once while it is 0. States 1 and 2 are field motions, 3 and 4 the Pokemon Camp visit
and session screens, 6 Max Raid Battle matching (`0x01466d30`). `a` is 1, 2 or 3 for the areas
`wr0101`, `wr0201` (the Isle of Armor, captures at location 170) and `wr0301`, else 0, from an
FNV-1a 64 area key; `b` comes from vtable `0x259add8` slots 8 and 11.

The activity record at 0x90 is `0x49` bytes, set up by `0x0111b660(rec, kind)`; Link Trade sets
communication mode 2 (`SetMode` `0x01096d10`,
[session](swsh_session.md#how-a-searching-sword-finds-a-partner)), which maps to kind 13 through the
table at `0x2066c40`.

The trainer name appears four times (MyStatus, trainer card, party records, profile);
`pokeldn/swsh/trade_payload.rewrite` moves all four, and the trade screen names that trainer. An empty
party slot is a zero record, sent either as zero bytes or encrypted under encryption constant 0; both
decrypt to zeros, and the count at 0x810 agrees. Encryption constant 0 alone does not mark a slot empty:
HOME gave its gifts before HOME 3.0.0 the card's zero constant (the Zeraora gift, WC8 9011)
[PKHeX `WC8.cs`]. `pokeldn.gen8.is_empty` tests the decrypted record.

## The PK8

Shared with BDSP in `pokeldn/gen8.py` (PKHeX `PK8` and `PB8` are both `G8PKM`). Sword sends the
0x158 party form (`pokeldn/swsh/pokemon.py`), BDSP the 0x148 stored form.

    0x00  u32  encryption constant, in the clear. Seeds the cipher and the block order
    0x06  u16  checksum, in the clear, over the decrypted body only
    0x08       four 80-byte blocks, LCG-encrypted and permuted by (EC >> 13) & 31
    0x148      the party stats, LCG-encrypted with the stream restarted, never permuted

Traps:

- The party stats restart the LCG (`PokeCrypto.Decrypt8` seeds `CryptArray` twice from the EC); a
  continued stream gives plausible garbage such as level 110.
- `BLOCK_ORDER[sv]` names the block that becomes block *i*: apply it, never invert it. 16 of 32 `sv`
  values are self-inverse and the checksum ignores order. PKHeX's `BlockPosition` entries 24-31
  duplicate 0-7.

Checks of a decoded party: nicknames match species; levels match experience; hyper-training 0x126
matches the IV word 0x8C; MyStatus's trainer ids match every PK8's.

## The trade message

`net_contents.trade.common.pokemon_trade.protocol_buffers`:

    Pokemon                  { 1 bytes   serializePokemonParam }
    PokemonTradeDataHolder   { 1 Pokemon pokemon }

An offer carries a 344-byte PK8 on 10050 (`trade.py` `pokemon_offer`). The parse `0x010d81d0` builds
a 0x28-byte message, calls `ParseFromArray` (`0x0070c180`); `MergePartialFromCodedStream`
(`0x010d9ee0`) accepts tag 0x0a only. The listener reads `[Pokemon+0x18]` as a libc++
`std::string`, copying 0x158.

### The receive handler's two silent drops

`0x010d5e40`:

    w0 = 0x006b5850(senderPointer)                            0xfd on failure
    if (w0 == 0xfd) { [content+0x1a4] = 1; return; }          silent
    memcpy(stack, body, 0x158)
    subscriber = [content + 0x30 + index*8]
    if (subscriber == null || its refcount is 0) return       silent
    ... invoke it, then content 50's send 0x010d6000

Content 50's init fills only `+0x30` and `+0x38`, so a station index above 1 returns; content 40's
`0x010dbc90` gates the same at `+0x38`/`+0x40`. The console answers a 10050 at once with its own; no
10050 back means the offer never reached `0x010d5e40`. Content 30's slot (`0x010ce080`) rejects
only its own id: an ownerless offer passes the box phase and fails content 50.

### Content 40's message

`net_contents.trade.common.sync_save.protocol_buffers`:

    SyncSaveDataHolder { 1 SyncCommand syncCommand }
    SyncCommand        { 1 int32       data       }

Parse `0x010ddb20`; `0x010df6d0` accepts tag 0x0a only, the submessage parser `0x010debc0` tag 0x08
only. `trade.sync_command` builds it.

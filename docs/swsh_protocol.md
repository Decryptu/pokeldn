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
u32 id, u64 0}`, ids 1..880 (97, the ping holder, 110, 120, 130 among them). High ids are base plus
offset; 20030 or 40040 never occur as constants, 60000 is base + 0 (a MOVZ at 41 sites).

## Contents and holders

Each content registers three holders (registrars `0x010ccd90` content 30, `0x010da7d0` 40,
`0x010d5150` 50), adding a base to its offset `ldrh [content+0x372]` and passing each to
`0x006daeb0(manager, &holder, flag)`:

    mov w9, #0x2710    id = 10000 + offset   holder 0x010dd910   flag 1
    mov w9, #0x4e20    id = 20000 + offset   holder 0x010d85f0   flag 0
    mov w9, #0x7530    id = 30000 + offset   holder 0x010d0980   flag 0

The 40000 family is minted a layer lower, 40000 as a MOVN:

    ldrb w20, [x0, #0x28]          the content offset, 30 / 40 / 50
    mov  w9, #-0x63c0              w9 = 0xffff9c40
    add  w24, w20, w9
    strh w24, [x20, #0x160]        40030 / 40040 / 40050

A holder without a listener drops silently (`0x010d81d0`: `ldr x8,[x0,#0x168]; cbz x8, out`).
Installs: content 30 `0x010ccc94`, `0x010ccca4`, `0x010ccf7c`; content 40 `0x010da6d0`,
`0x010da9bc` (cleared `0x010dab10`); content 50 `0x010d50ac`, `0x010d533c` (cleared `0x010d5660`).
None reaches the 20000-base holder of 40 or 50: 20040 and 20050 are inert.

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

Parser `0x006a7580` (tags `0x0a`..`0x22`); RequestForcedProceed's `0x006a65c0` stores its fields
at `+0x14`, `+0x18`. The receive, slot 8 `0x008b9590`, calls listener slot (case - 1) of
`[holder+0x168]` via `0x0204c430`.

Shield 1.3.2 builds only CancelAccepted: outside the protobuf code (`0x006a3000..0x006a8400`) nothing
calls the other constructors (`0x006a4b50`, `0x006a5730`, `0x006a6330`) or their accessors.
`0x006a3db0` has 21 outside callers: the send wrapper `0x008b7420` and two reply jobs in each of ten
sync contents (`0x008b71a0`, `0x008b7700`, `0x008cfb10`, `0x008cfbe0`,
`0x00c06420`, `0x00c064f0`, `0x010763a0`, `0x01076470`, `0x010a2090`, `0x010a2160`, `0x010cf460`,
`0x010cf530`, `0x010d7760`, `0x010d7830`, `0x010dd0c0`, `0x010dd190`, `0x012a8390`, `0x012a8460`,
`0x012bec80`, `0x012bed50`). Retail trades never carry cases 2 to 4; a console still acts on them
([content 40](swsh_trade.md#the-cancel-and-proceed-messages)). Content 40's instance, 30040, port 0:

    RequestForcedProceed{c, c+1}   58750000 2204 08<c> 10<c+1>     c=0: 58750000 2204 0800 1001

### The three trade contents

`0x010c9280` builds the session:

    +0x120   content 30, the box exchange       ctor 0x010cca10, registers offset 30 at 0x010ce4f0
    +0x148   content 40, SyncSaveDataHolder     ctor 0x010da3f0
    +0x2b0   content 50, PokemonTradeDataHolder ctor 0x010d4d40
    +0x60    an event source, listeners in a vector at its own +0x60
    +0x68    own Pokemon        +0x70  theirs
    +0x90    a delegate to +0xb0: thunk 0x010cc250 -> box callback 0x010ca800(session, code, payload)
    +0x140   the trade state, 1..10            +0x144  the error code
    +0x418   send command 3 on the first frame  +0x419  the role bit that suppresses it

A content's init registers its holders and mints its 40000 id: content 50 in trade state 1
(`0x010d4d90`), content 40 in state 6 (`0x010da470`), after the exchange (state 3) and the state-4
decision `0x01109320`.

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

A payload is `struct.pack("<HBB", id, discriminator, 0)` then the body, built at `manager+0x240f0`
by `0x006db840` (`strh w3`, the discriminator from `manager+0x480f0`, `strb wzr`) and parsed by
`0x006db620`. The discriminator is a generation counter, `[content+0x370] = (+1) mod 255`
(`0x008b6670`), pushed into `[manager+0x480f0]`; a forced CancelAccepted steps it on content 40
(`0x006db470`, `0x010dcea4..0x010dcec8`); registrars zero it (`0x010d53a0`). The 107 payloads of
one trade with no forced CancelAccepted all carried zero.

### Reading the registrations live

    manager = read_u64(read_u64(main + 0x02616750))     0x006a9a70, the poll's caller
    count   = read_u64(manager + 0xD8)                  0x006db3dc
    array   = read_u64(manager + 0xD0)                  0x006db3e0
    entry i = array + i * 0x10                          0x006db3e4
    id      = holder's vtable slot 7, called at 0x006db740 (`ldr x8, [x8, #0x38]`)

Slot 7 returns `[holder+0x160]` here; elsewhere decode its `ldrh`. Empty on an idle screen; a seated
link trade adds two entries (seen within two seconds of the seat); Mystery Gift adds none.

### Dispatch gates, ports and senders

An entry is 16 bytes: holder, kind at +8 (`w2`), flag at +9 (`w3`, 1 only for 10000+offset):

    id == holder->slot7()
    entry[8] == the drain's kind
    entry[9] ? header[2] == [manager+0x480f0] : no check

Kind is the mesh port: 0 for content holders (20030, 10050, pings), 1 for the 40000 family
(`0x006daf40(manager, &holder, 1, 0)`). The sender is a transport pointer (`[sp+0x28]` in
`0x006db9c0`) passed down to `0x010d5e40` and resolved by `0x006b5850` (`mesh->GetStationIndex`,
0xfd on failure); loopback passes `[[0x2616a30]]+0xf0`. `Data.ownerId` plays no part on 10050.

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
| 32-bit | `0x006d5c00` | `0x2512bc8` | 0 (`0x006d5ce0`) | `0x006d5f20`: 4, `ldr w8` / `str w8` |
| pair (the phase) | `0x006d6160` | `0x2512c90` | `0xfc18fc18` (`0x006d6230`) | `0x006d6490`: 4, `ldr w8` / `str w8` |
| 16-bit | `0x006d66d0` | `0x2512d58` | 0 (`0x006d67b0`) | `0x006d69f0`: 2, `ldrh w8` / `strh w8` |

A receive then sets `[sub+0x78] = clock` and `strh 0x0100 -> [sub+0x60]` (ready byte `+0x61`); slot
7, the hashed value, returns the clock. A sub-element is 0x90 bytes; its constructor takes the
element `x0` (`+0x80`), elementId `w1` (`+0x62`), ownerId `x2` (`+0x68`), flag `w3` (`+0x70`),
returning through `x8`.

The sync element (`0x006d3f80`) is built once per sync content: `0x008b5c60`, `0x008cecb0`,
`0x00c05690`, `0x01075610`, `0x010a1230`, `0x010ce604` (30), `0x010d6904` (50), `0x010dc264` (40),
`0x012a7530`, `0x012bdef0`. Vtables from `0x2512b28`:

    element+0x00  0x2512b38   primary, 6 slots; 2, 3, 4 are the three constructors with w3 = 1
    element+0x08  0x2512b78   interface A: the 32-bit kind (thunk 0x006d5ab0)
    element+0x10  0x2512b90   interface B: the pair (0x006d5ac0), the 16-bit kind (0x006d5ad0)
    element+0x18  0x2512bb0   the router listener, slot 0 = 0x006d59f0

The mint `0x006d44e0` builds four channels, adding every station in `[element+0x70..+0x78]`:

| field | built by | size | holds |
|---|---|---|---|
| `+0xb0` | `0x006cd890` | 0x130 | |
| `+0xd0` | `0x006d9ca0`, A | 0x38 | per station a 32-bit sub-element, elementId 10000 (`0x006d9d90`): the quorum hash |
| `+0xf0` | `0x006d29b0`, B | 0x40 | at `+0x38` a 16-bit sub-element, elementId 20000, owner 0: the [shared value](swsh_trade.md#the-phase-is-the-elements-field); per station a pair, elementId 20000 (`0x006d2aa0`), in 16-byte `{stationId, sub}` entries |
| `+0x110` | `0x006d7980` | 0x30 | the list the quorum hash walks |

### The quorum hash

The four bytes on elementId 10000, built by `0x006d7b40` at `element+0xa8`:

    h = 0
    for sub in subs:
        if (!sub[+0x61]) { h = 0; break }        any station not ready -> zero
        h = crc32(le32(h + sub->slot7()))        slot 7 is the clock

Non-zero means every station is ready. `0x0065de30` is `zlib.crc32` (checked under unicorn);
`0x0065df04` (poly `0x8005`) is a CRC-16. The walked list `element+0x110` is `0x006d48b0`'s
copy of `+0x40` keeping entries with `+0x68` zero; its length in a trade is unread.

The chain covers the sender's elementId 0 and 1 (no owner), then its own elementId 20000. Every
non-zero hash a hosting Sword sent matches, e.g. content 50:

    elementId 0, no owner      clock 2304   the host's own Pokemon (344 bytes)
    elementId 1, no owner      clock 2313   the partner's Pokemon, sent back
    elementId 20000, host      clock 2278   then 2338 after its pair moved
    crc32 chain                8ffa0f2e     then b3615e90

A clock can change before its message is sent. A joiner that echoes the host's hash completes a
trade against a hosting Sword.

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

MyStatus and TrainerCard are PKHeX save blocks (`Saves/Substructures/Gen8/SWSH/`).

The builder `0x0110c180`: `0x00784f90` (party), `0x01424f10` (MyStatus), a 0x1C8 memcpy (trainer
card), `0x01124fa0` (profile), a 0x188 memcpy of an optional block or a memset. Of `0x010fcff0`'s
callers, Link Trade (`0x010967f0`) and password matching (`0x00bd80f4`,
`ChikaMatchingStateSession`) pass no block; Battle Stadium (`0x00b2d7d0`, `StateBtlSpot*Battle`,
Casual, Rank, Comp) passes one. The receiver `0x0110cff0` copies both regions per station.

### The Battle Stadium block

0x180 bytes of data, a u64 length. Producer `0x00b2eb60` fills an optional (flag `+0`, data
`+8`); the snapshot copies 0x188 from its holder's `+0x60` (`0x0110c378`); the reader `0x00b2d9fc`
requires length 0x118. From 0xBF6:

    0x000  u32    CRC-16 (0x8005) of the 0x22fc-byte regulation core   0x008ff9e0:
                  0x0065dd70([reg+0x180]+0x60, 0x22fc); regulation_preset_core_%d.bin (0x008feb34)
    0x004  0x100  the team's signature: +0x36 of the 0x136-byte team descriptor at match+0x98
                  (0x00b2ef24)
    0x104  4      zero
    0x108  u64    the manager's optional (value +0x1ab8, flag +0x1ab0, 0x00adc8d0), zero unless
                  match type 3                                         0x00b2f100
    0x110  u8     the manager's byte +0x191c (0x00adbbe0) when 0x00adb920 yields an object and
                  0x00b1ce10(0) == 2                                   0x00b2efc4
    0x111  u32, u16, u8   team descriptor +0, +4, +6
    0x118  0x68   zero
    0x180  u64    length, 0x118

The receiver `0x00b2e590` compares the partner's CRC with its own (`0x00b2e760`); with `0x008fc470`
the result is 9 when both hold, else 10 (`cinc` `0x00b2e778`). `0x010719f0`, `0x01071a98`,
`0x01071c00` compare it and a CRC over 0x640 bytes at `+0x188` (`0x008ffa10`). The descriptor is
copied whole at 18 sites, four in `StateDownloadTeamMenu` (`0x013e660c` to `0x013e7c58`).

match+0x70 is an optional (flag `+0x70`, value from `+0x78`: a u64 key, a pointer, a u64, a pointer,
then the descriptor at `+0x98`). Its only writer is `0x00ad9cf0` (memcpy in `0x00adeaf0`): the Battle
Stadium matching update `0x00ad5750` fills it at `0x00ad6a2c` from `[state+0xb8]+0x20`, and
`0x00ad6a68` and `0x00b1ea88` clear it. That request object is filled by the team download job
(`0x014f7fd0`..`0x014f809c`, done flag `+0x18`) from its result holder at `[job+0x88]`: descriptor
`+0x00..+0x2f` six u64 from `+0x38`, `+0x30..+0x35` six bytes from `+0x68`, `+0x36..+0x135` from
`+0x6e`, then overwritten by the `v1/validate` signature (`0x014f8094`). The holder takes whole the
0x158-byte entry of the team list whose key matches the list's selected key (`0x01503f10`, copied
at `0x014fa804`). The list `0x0150320c` holds two kinds of entry:

| key | entry |
|---|---|
| (1, team) | a save battle team: six u64 `box \| slot << 32`, one per member, from `save+0x525 + team*12 + i*2` (`0x0140a5c0`, `0x0140a5f0`); name at `save+0x4a0 + team*0x16` |
| (2, i) | a stored record: bytes 0x26..0x15b of a 0x87f-byte record `0x01430670` loads |

The signature is RSA-2048, PKCS#1 v1.5, SHA-256, checked by `0x011aedf0(team, v, sig)` (callers
`0x00b2f19c`, `0x00b2f1e0`, `0x00b2f2e0`, `0x0109eb68`), the only caller of
`nn::crypto::detail::BigNum::ModExp` (PLT `0x018fff50`, GOT `0x0260fb38`):

    0x011aee90  count 0x148-byte stored PK8s        bl 0x7664c0, add w26,#0x148
    0x011aeeac  v as BE u16, then 00 01             rev w8,w22; lsr #16; strh 0x100
    0x011aef98  Sha256Impl::Initialize
    0x011aefa8  BigNum::Set(modulus, .., 0x100), Set(exponent, ..)
    0x011aeffc  Sha256Impl::Update(message)
    0x011af01c  BigNum::ModExp(out, sig, exponent, 0x100, ..)
    0x011af06c  cmp x8,#0xca: the 00 01 FF..FF 00 padding
    0x011af090  memcmp(.., Sha256Generator::Asn1ObjectIdentifier, 0x13)
    0x011af128  Sha256Impl::GetHash, memcmp(.., 0x20)

The console holds only the public key; the image carries
`https://v3-lp1.vp.n.srv.nintendo.net/v1/public_key` (`0x01bd7d41`) and `.../v1/validate`
(`0x01c11a93`), so a Nintendo server presumably signs. Link Trade never reaches the check.

`v1/validate` (`0x011a2a70`) sends a NUL-terminated string (all of `v1/public_key`'s body), the key
version as BE u16 (key holder `+0x68`, set from the `v1/public_key` reply by `0x0144fb90`), the
console's version `0x007d4270() = 0x2D` (Shield) as BE u16, `00 01`, a BE count and 0x148-byte
records (`0x007664c0`). The signed message holds the same records, version and `00 01`; there `v` is
the partner's MyStatus byte `0xA4` (`obj+0x104`, `0x01424bf0`, default `0x2D` at `0x014245f0`, PKHeX
`MyStatus8.Game`). The reply parser `0x011a2870`: byte 0 a status (2: stale key, fetch again;
`R+0x70` = status == 1), bytes 5-6 a BE count n clamped to 6, n BE u32 into `R+0x74`, on status 0
0x100 bytes into `R+0x8c` (`0x011a29e4`). Of five callers only `0x014f8c00` keeps them (to
`obj+0x183`); `0x014f808c` writes them at `+0x36` of a descriptor-shaped 0x136-byte run.

The match type is slot 8 (`+0x40`) of vtables `0x2538238`, `0x2538358`, `0x2538478`: 1 casual
(`0x00adda60`), 2 ranked (`0x00adde60`), 3 online competition (`0x00ade340`). `0x00adcfb0(obj,
mode)` builds them, reached only via `0x00b1cdd0` from six sites in `StateBtlSpotTop`
(`0x00b23080`), which moves to `StateBtlSpotCasualMatchEntrance`, `StateBtlSpotRankMatchEntrance` or
`StateBtlSpotCompTop`. `+0x108` is written by `0x00adc8b0` (`str x1,[x0,#0x1ab8]`, flag `+0x1ab0 =
1`) from `0x00b41b7c` in `StateBtlSpotCompTop`, with the u64 at 0x33C0 of save block `0x88F6D6AE`
(0x33D0 bytes, key at `0x02072fac`, read by `0x01444ac0`; the preceding key `0xEEE5A3F8` is PKHeX's
`KOfficialCompetition`).

### The player profile

266 bytes at 0xAEC, also the beacon's record at 0x1F ([session](swsh_session.md#taking-a-seat)).
`0x01111970` copies it from the singleton `[0x2610958]` (+0x310 to +0x564, mutex +0x580);
`0x01125080` packs all groups or none, so the layout is fixed; bit-packed groups are LSB first.
`trade_payload.read_tail` decodes it.

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
                2, 2 bits  `a` (sample object +0x47) and `b` (+0x1c9), below
                8 bits     generation: random at ring reset (0x00eb98a8), +1 per re-seed
                8 bits     player object byte +0x136 (7 in every capture)
                3 x 17     at 0x5C, 0x6D, 0x7E, newest first: 5-bit counter (0x01123be0, +1 per
                           push); 3-bit state (+0x1c8, below); x, y, z floats; yaw in radians
                           (Euler component 1, 0x006101c0). 0x00ebf590 pushes at most once a second
                           from the field object's +0x60 (position) and +0x50 (rotation);
                           0x00b4f140 and 0x00b54450 re-push the current sample three times.
                8 bits     at 0x8F: player object byte +0x140 (1 in every capture)
    0x90  37  activity, bit-packed: an 8-bit kind (below; 13 in trade), an optional 28-byte part,
              a 24-byte field, a u16 at 0xB2, a bool; only kind and u16 non-zero. The u16 is the
              location, the line of `script/place_name.dat` (0x00f27d70), PKHeX's met-location
              id (170 Challenge Beach); setter 0x0111bc60, readers 0x0111b8c8, 0x0111b8f4.
    0xB5  37  two more groups (56 and 16 source bytes), zero in every capture
    0xDA  32  sixteen u16 records, `0x010f5060`: Record8 indexes 6, 32, 0, 33, 17, 27, 34, 24,
              12, 3, 10, 35, 38, 7, 36, 37, each clamped to 0xFFFF (PKHeX `RecordList_8`:
              total_capture, evolution, egg_hatching, net_battle, trade, license_trade, cooking,
              campin, pretty, capture_raid, rotomu_circuit, poke_job_return, bike_dash, dress_up,
              get_rare_item, whistle)
    0xFA   8  an optional u64, zero in every capture
    0x102  8  zero

A receiver (0x00dd5e24) stores the position at +0xB0 and the yaw, as a quaternion, at +0xA0
(0x00992cd0); 0x011a68a4 samples only in states 1, 2, 3, 6.

The sample state is `+0x1c8` of `[[0x261bd18]]`, set only by `0x00ebf570`, zeroed by the reset
`0x00eb97b0` (sole caller `0x00dd2e00`, `0x00eb986c`); the push returns at once while it is 0
(`0x00ebf5a8`):

| state | set by |
|---|---|
| 0 | `0x00dfd1d4`, vtable `0x2561ec8` slot 9 |
| 1 | field player slots 13 (`0x00d98f28`), 30 (`0x00d9d2a8`), 76 (`0x00da0188`); `0x00d97730` motion 0 |
| 2 | `0x00d97730` motion 1 or 2; slot 7 (`0x00d97644`, motion 1 when `[+0x5b8]` becomes 1 or 2 in motion 2); slot 75 (`0x00d9fcc4`) |
| 3 | vtable `0x253e358` slot 15 (`0x00b4f028`, class of `StateCreateSession`); vtable `0x25614c0` slot 8 (`0x00dedf80`) when `[[obj+0x98]+0x58]` is set |
| 4 | vtable `0x253e8d0` slot 16 (`0x00b54338`, class of `StateConnect`); the `0x25614c0` slot when clear |
| 5 | nothing |
| 6 | `0x00da09a0` (`0x00da0a04`) from `0x00cebe00`, `0x00cebea4`, `0x01466d90` in the native `CallRaidBattleMatchingEvent_` (`0x01466d30`, table `0x25aac68`) |

`0x00d97730(player, motion)` stores the motion via `player->vtable[0x190]` under key `[0x261e8a0]`,
also read by the native `IsPlayerRideBicycleType` (`0x0148b960` -> `0x00da0210`); the Lua enum at
`0x00e57940` names motions `NORMAL`, `BICYCLE_GROUND`, `BICYCLE_WATER` (`1 | 2<<32` at
`0x00e5793c`). The `0x25614c0` slot also starts an activity record of kind 11 (`0x0111b660`), hands
it to `[0x26108d8]` (`0x00fa13c0`) and pushes a sample. The `0x25614c0` object is the Pokemon Camp
visit: the natives `PokeCampToVisit` (request `0x0100`, state 3) and `NpcPokeCampToVisit` (`0x0000`,
state 4) build it, as do the network-side requests `0x0101` (state 3) and `0x0001` (state 4), and the
image carries the multiplayer camp's `contents.pokecamp.pb.KwSyncData`. State 6 is Max Raid Battle
matching.

`a` and `b` pack into bits 0-1 and 2-3 (`0x01123710`; `0x01123760` reads `b` 3 as 0). The reset
`0x00eb97b0` in mode 0 sets `a` from the area key `[[[0x2617c48]]+0x180]` (`0x00eb97d0..0x00eb9848`):

| key | area | `a` |
|---|---|---|
| `0x5742865396e549d0` | `wr0101` | 1 |
| `0x5ea5c3539ab81c81` | `wr0201`, the Isle of Armor (captures at location 170) | 2 |
| `0x674edc539f9f74a6` | `wr0301` | 3 |
| other | | 0 |

The keys are FNV-1a 64 (basis `0xcbf29ce484222645`, `0x01369700..0x01369724`) of `a_wr0101`,
`a_wr0201`, `a_wr0301` (inverted over the last two characters, all reach `0xb8123d750dc24af8`). They
are also the array `0x02061f98` (looped at `0x00ecd418`), map to the nest-hole emitter names at
`0x01c25bbb`, `0x01be5bad`, `0x01c2d3a5` (`0x00ec51b4..0x00ec5218`), and `0x00de19c0` copies
`a_wr0101` (`0x01c0ae67`) on the first; the romfs has `a_wr0201.bnk` and `a_wr0301.bnk` sound banks.
`b` is set by `0x00ebf580` from vtable `0x259add8` slot 8 (`0x0110e850(...) < 4`, `0x012dfaec`) and
slot 11 (2, `0x012dfca8`), each followed by a push.

The activity record at 0x90 is `0x49` bytes, set up by `0x0111b660(rec, kind)` (kind at `+0`,
zeroes at `+4`, `+0x24..+0x3e`, `+0x40`, `+0x48`). Kinds by call site: 9 `0x0102437c`; 11
`0x00dedf3c`, `0x0126e37c`; 12 `0x01272120`; 18 `0x01027d38`; 19, 21, 23, 25 `0x01027d2c`
(`0x13 + 2n`); 27 `0x00de7a0c`; 28 `0x00de727c`; 29 `0x01026290`; 30 `0x0109659c`; 31 `0x015d595c`;
255 `0x01027fac`, `0x010962b8`, `0x01097990`, `0x01097bc4`; and `0x010961b0` by the communication
mode `[obj+0x70]` through the table at `0x2066c40`:

    mode   0    1  2   3   4   5   6
    kind   255  1  13  14  15  16  30

`SetMode` (`0x01096d10`, `str w1,[x0,#0x70]`) is called with 2 by Link Trade
([session](swsh_session.md#how-a-searching-sword-finds-a-partner)), and with 0, 1, 6.

The trainer name appears four times (MyStatus, trainer card, party records, profile);
`pokeldn/swsh/trade_payload.rewrite` moves all four, and the trade screen names that trainer. Empty
party slots are zero; the count at 0x810 agrees.

## The PK8

Shared with BDSP in `pokeldn/gen8.py` (PKHeX `PK8` and `PB8` are both `G8PKM`). Sword sends the
0x158 party form (`pokeldn/swsh/pokemon.py`), BDSP the 0x148 stored form.

    0x00  u32  encryption constant, in the clear. Seeds the cipher and the block order
    0x06  u16  checksum, in the clear, over the decrypted body only
    0x08       four 80-byte blocks, LCG-encrypted and permuted by (EC >> 13) & 31
    0x148      the party stats, LCG-encrypted with the stream restarted, never permuted

Two silent misreads:

- The party stats restart the LCG (`PokeCrypto.Decrypt8` seeds `CryptArray` twice from the EC); a
  continued stream gives plausible garbage such as level 110.
- `BLOCK_ORDER[sv]` names the block that becomes block *i*: apply it, never invert it. 16 of 32 `sv`
  values are self-inverse and the checksum ignores order, so the wrong direction often reads fine.
  PKHeX's `BlockPosition` entries 24-31 duplicate 0-7.

Checks of a decoded party: nicknames match species; levels (unshuffled tail) match experience;
hyper-training 0x126 matches the IV word 0x8C; MyStatus's trainer ids match every PK8's.

## The trade message

`net_contents.trade.common.pokemon_trade.protocol_buffers`:

    Pokemon                  { 1 bytes   serializePokemonParam }
    PokemonTradeDataHolder   { 1 Pokemon pokemon }

An offer carries a 344-byte PK8 on 10050 (`trade.py` `pokemon_offer`). The parse `0x010d81d0` builds
a 0x28-byte message (`0x010d9c90`), calls `ParseFromArray` (`0x0070c180`) and passes `[msg+0x18]`;
`MergePartialFromCodedStream` (`0x010d9ee0`) accepts tag 0x0a only. The listener reads
`[Pokemon+0x18]` as a libc++ `std::string` (byte 0 bit 0 selects the heap pointer at +0x10), copying
0x158.

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
10050 back means the offer never reached `0x010d5e40`. Content 30's slot (`0x010ce080`) only rejects
its own id (`[[0x2616a30]]+0xf0`): an ownerless offer passes the box phase and fails content 50.

### Content 40's message

`net_contents.trade.common.sync_save.protocol_buffers`:

    SyncSaveDataHolder { 1 SyncCommand syncCommand }
    SyncCommand        { 1 int32       data       }

Parse `0x010ddb20` (twin of `0x010d81d0`); `0x010df6d0` accepts tag 0x0a only, the submessage
parser `0x010debc0` tag 0x08 only. `trade.sync_command` builds it.

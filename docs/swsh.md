---
title: Sword and Shield
nav_order: 6
has_children: true
---

# Sword and Shield

Pokemon Sword and Shield run C++ game code with protocol-buffer messages, over a generic
publish/subscribe framework, directly on Pia.

Static readings are from a Shield 1.3.2 EUR image (`01008db008c2c000`, update NCA, SDK 7.7.0.0);
measurements are against a French Sword 1.3.2. The two share their network code; a difference is
marked where it exists.

A retail Sword has traded with pokeldn in both roles ([Hosting a trade](swsh_trade.md#hosting-a-trade)).

| page | contents |
|---|---|
| [The cartridge and the session](swsh_session.md) | keys, the image, Pia 4, association to the first application data |
| [The sync framework](swsh_protocol.md) | message ids, contents, holders, routing, the party payload |
| [Trading](swsh_trade.md) | the trade screen, the box state machine, the confirmation ladder |
| [Mystery Gift](swsh_gift.md) | the Mystery Gift menu's local-wireless branch |

## Sources

Ids, offsets and addresses come from Shield's `main` or the air unless a section names a client.
`SYNC_ANSWERS` in `pokeldn/swsh/trade.py` is `andyjusa/nxldn-lab`'s reading of a console-to-console
capture (messages 97 and 60000 match pokeldn's byte for byte). Four clients speak the LAN mode,
`kwsch/PokePiaSWSH`, `lincoln-lm/swsh-lan-client`, `andyjusa/nxldn-lab`, `Slashcash/PSD`, from the
Pia station handshake up; none covers LDN or host migration.

## The field scripts

`bin/script/amx/*.amx` (953 in 1.3.2) are Pawn 3.x with 64-bit cells: magic `0xF1E1`, version 10,
flags `0x1C` (compact code, sleep, no checks). Compact encoding: 7 bits per byte, high group first,
sign in bit 6 of the first byte. Non-branch one-parameter opcodes are also packed as
`(param << 32) | op`, numbered from 162 in 3.x order (`LOAD.pri` 162, `LOAD.S.pri` 164, `PUSH.C`
188, `PUSH.S` 190, `STACK` 191, `ADD.C` 197, `ZERO.S` 200, `EQ.C.pri` 201, `INC.S` 204, `HALT` 210,
`PUSH.ADR` 212); `halt 0` at offset 0 pins it.

A native is twelve bytes, `u64 0` and a `u32` name hash, resolved by `amx_Register` (`0x0066d970`):

    h = 0; for each byte c: h = (h * 0x83) ^ c        (32-bit)

Binding tables are `(name, function)` pairs in `.data`, one per module (getters such as
`0x014aea00`): 777 names, 512 of the 513 hashes used. Items: `ItemAdd` (`0x014acea0`), `ItemSub`
(`0x014acf40`), `ItemGetNum`, `ItemAddCheck`, `ItemGetCategory`, `GetPocketNumberFromItemNumber_`.
Variables: `WorkGet`/`WorkSet` (hashed 64-bit keys), `TempWorkGet`/`TempWorkSet` (indices the UI
fills before the script resumes). A call is `PUSH` per argument, right to left, then
`SYSREQ.N native, bytes`.

## Unresolved

- [Player profile](swsh_protocol.md#the-player-profile): which role sample states 3 and 4 stand for
  in a Pokemon Camp session (`StateCreateSession`, `StateConnect`). `a_wr0301` as the Crown Tundra wild area is read from the numbering; one beacon
  taken there settles it.
- [Battle Stadium](swsh_protocol.md#the-battle-stadium-block): the writer of `match+0x98`. The team
  descriptor's `+0` to `+7` is one u64 copied from `[job+0x88]+0x38` of the rental-team response
  (`0x014f7fd0`); the `v1/validate` reply is copied over its signature at `0x014f8094`.
- Sword against Shield: binary readings are Shield's, the console is Sword; the
  [session constants](swsh_session.md#taking-a-seat) hold across the pair. Sword testing bit 0 of a
  card's version mask is inferred from Shield's code, where the test is `1 << (v == 0x2D)` and eleven
  of the 31 call sites of `0x007d4270` compare against both `0x2C` and `0x2D`, and from PKHeX
  `RestrictVersion` (1 Sword, 2 Shield, 3 both); two retail Sword snapshots carry `0x2C` at MyStatus
  `+0xA4`. Sword's own `0x007d4270` and its communication id literal are unread.
- [Mystery Gift](swsh_gift.md#what-the-menu-refuses): whether a retail console takes a kind-1 gift
  whose species is absent from the game as an emulated Shield does, as a bad egg named "Egg"; and
  what such an egg does on hatching or in a trade.

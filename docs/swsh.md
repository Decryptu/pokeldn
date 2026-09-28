---
title: Sword and Shield
nav_order: 6
has_children: true
---

# Sword and Shield

In Pokemon Sword and Shield, Pia is the game's own transport and the game's code sits directly on
it, written in C++ with protocol-buffer messages above a generic publish/subscribe framework.

The static reading is taken from a Shield 1.3.2 EUR cartridge image (`01008db008c2c000`, update
NCA, SDK 7.7.0.0). Hardware measurements are against a French Sword 1.3.2. The two builds share
their network code; where a finding differs between the pair it is marked.

A retail Sword has completed a trade with pokeldn: it accepted a Pokemon, gave one of its own, wrote
its save and returned the player to the overworld. pokeldn has also hosted a trade that a retail Sword
joined and saved, over the ESP32 board ([Hosting a trade](swsh_trade.md#hosting-a-trade)).

## Pages

| page | contents |
|---|---|
| [The cartridge and the session](swsh_session.md) | what the title is built from, the LDN passphrase and Pia game key, reading the image, Pia 4, and the association through to the first application data |
| [The sync framework](swsh_protocol.md) | message ids, contents and holders, the routing path from the radio to a handler, and the party payload |
| [Trading](swsh_trade.md) | the trade screen, the box state machine, and the confirmation ladder |
| [Mystery Gift](swsh_gift.md) | the local-wireless branch of the Mystery Gift menu |

## What is measured and what is borrowed

Every message id, structure offset and address on these pages is read out of Shield's `main` or
measured on the air, except where a section names an external client.

`pokeldn/swsh/trade.py` carries `SYNC_ANSWERS`, a table of what to answer for sync holders not
exercised here. It is `andyjusa/nxldn-lab`'s reading of a console-to-console capture. Its ids for
messages 97 and 60000 agree with pokeldn's own capture byte for byte.

Four published clients read this game's LAN mode and were found by searching its Pia game key:
`kwsch/PokePiaSWSH`, `lincoln-lm/swsh-lan-client`, `andyjusa/nxldn-lab` and `Slashcash/PSD`. They
share the payload layouts from the Pia station handshake upward; the LDN link layer below is not
covered by any of them, and none of them handles Pia host migration.

## The field scripts

The field events are Pawn scripts, `bin/script/amx/*.amx` in the RomFS (953 files in 1.3.2, the
two expansions included), one per event or NPC group. The format is Pawn 3.x with 64-bit cells:
magic `0xF1E1`, file version 10, flags `0x1C` (compact code, sleep, no checks). The code segment is
stored in Pawn's compact encoding, 7 bits per byte, most significant group first, sign in bit 6 of
the first byte. On top of the 3.x opcode set the compiler packs every one-parameter opcode that is
not a branch into one cell, `(param << 32) | op`, numbered from 162 in the 3.x order (`LOAD.pri`
162, `LOAD.S.pri` 164, `PUSH.C` 188, `PUSH.S` 190, `STACK` 191, `ADD.C` 197, `ZERO.S` 200,
`EQ.C.pri` 201, `INC.S` 204, `HALT` 210, `PUSH.ADR` 212); `halt 0` at code offset 0 pins the table.

Natives carry no names. A native entry is twelve bytes, `u64 address = 0` and a `u32` hash, and the
game's `amx_Register` (`0x0066d970`) resolves it by hashing each name in its binding tables with

    h = 0; for each byte c: h = (h * 0x83) ^ c        (32-bit)

The binding tables are `(const char *name, function)` pairs in `.data`, one table per module,
reached through getters such as `0x014aea00`; 777 names, 512 of the 513 hashes the scripts use.
The item natives are `ItemAdd` (`0x014acea0`), `ItemSub` (`0x014acf40`), `ItemGetNum`,
`ItemAddCheck`, `ItemGetCategory`, `GetPocketNumberFromItemNumber_`; script variables come through
`WorkGet`/`WorkSet` (hashed 64-bit keys) and `TempWorkGet`/`TempWorkSet` (small indices the game's
own UI writes into before the script resumes). A native call is `PUSH` per argument, right to left,
then `SYSREQ.N native, bytes`.

## Unresolved

- Inside the player profile ([the protocol page](swsh_protocol.md#the-player-profile)): which
  feature the class of vtable `0x25614c0` serves (it starts activity record kind 11, `0x00dedf3c`, and
  sets sample state 3 or 4); sample states 3, 4 and 6 are named only by the code that sets them
  (`StateCreateSession`, `StateConnect`, `CallRaidBattleMatchingEvent_`). That `a_wr0301` is the
  Crown Tundra's wild area is read from the numbering; one beacon taken there settles it.
- What writes the Battle Stadium team descriptor's `+0`, `+4` and `+6`
  ([the protocol page](swsh_protocol.md#the-battle-stadium-block)). A save holding a registered,
  validated team shows it: dump its blocks and look for the 0x100-byte signature.
- Whether the `v1/validate` reply's 0x100 bytes reach the team descriptor at `match+0x98`: the copy
  `0x014f808c` writes them into a descriptor-shaped run at `[x19+0xb0]+0x76`, and the path from there
  is untraced ([the protocol page](swsh_protocol.md#the-battle-stadium-block)). What the reply's status
  1 and its up to six u32 mean is unknown.
- Whether mesh events 1 and 2 store `LdnMatchmakeSession`'s slot 30, a 32-bit value or `0xff`, into
  the Pia session's `+0xf8` in an LDN session ([the session page](swsh_session.md#the-pia-session-object)).
  `+0xd4` is 3 or 4 only through `0x01839cc0` and `0x0183a040`; whether their callers are the
  joint-session jobs alone, and which `+0xd4` each event branch needs, is unchecked. A breakpoint on
  `0x01844bc4`, `0x01844edc`, `0x0184415c` and `0x018407f0` through a hosted ladder with a host
  migration settles it.
- Where content 40's tick (`0x010dae70`, from `0x010c5f40` and `0x010c9c34`) runs against the two
  message drains of a frame, one before and one after the game update `0x00f1cc60`
  ([the trade page](swsh_trade.md#the-command)). A backtrace at `0x010dae70` during a ladder on an
  emulated console settles it.
- What a console does with a partner's `RequestForcedProceed{c, c+1}`
  ([the trade page](swsh_trade.md#the-cancel-and-proceed-messages)). By the handler it writes `c+1`
  as the shared value, skipping pump states 8 to 10 but not state 3 of the next rung. No retail
  console sends the message, and none has been sent to one. A joiner that keeps rung 0's
  `syncCommand` and sends `RequestForcedProceed{c, c+1}` on 30040 in place of each later one settles
  it: accepted if the shared value moves with no `syncCommand` in that rung.
- That a partner card differing from a filed one only in the u64 at 0x1A8 brings the League Card
  question back follows from `0x013fbc40` and is unmeasured. A hosted trade whose card differs from
  one the Sword holds only in 0x1A8 settles it.
- Sword against Shield. Everything read off the binary is Shield's; the console is Sword. The
  passphrase, the game key, the Pia version and the local communication id hold across the pair
  ([the session page](swsh_session.md#taking-a-seat)). Mystery Gift's state names are Shield-only
  readings. That a Sword tests bit 0 of a card's version mask follows from Shield's code with Sword's
  version 44 (`0x2C`) in place of `0x007d4270`'s `0x2D`, and from PKHeX's `RestrictVersion` (1
  Sword, 2 Shield, 3 both); no Sword instruction has been read.
- Mystery Gift redemption ([the gift page](swsh_gift.md#what-the-menu-refuses)): whether the kind-1
  builder `0x010b6110` or the placement `0x010159d0` checks legality (illegal moves were accepted on
  a retail console).

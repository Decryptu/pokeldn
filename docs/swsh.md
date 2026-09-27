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

- Inside the player profile ([the protocol page](swsh_protocol.md#the-player-profile)): the sample
  states 3, 4 and 6 are named only by the code that sets them (`StateCreateSession`, `StateConnect`,
  `CallRaidBattleMatchingEvent_`); what the Battle Stadium team descriptor's `+0`, `+4` and `+6` and
  match type 3 are. That the 0x100 bytes at 0xBF6+4 are an RSA-2048 signature over the stored-form
  party is inferred from the `ModExp` call and its 0x148 stride. That `wr0201` and `wr0301` are the
  Isle of Armor's and the Crown Tundra's wild areas is read from the numbering and from every capture
  on Challenge Beach carrying 2; the strings the three area keys hash are unrecovered.
- What the Pia session's `+0xf8` holds after mesh events 1 and 2
  ([the session page](swsh_session.md#the-pia-session-object)). They store `LdnMatchmakeSession`'s
  slot 30, a 32-bit value or `0xff`, which cannot equal a 64-bit LDN station id, so either those
  paths do not run in an LDN session or `0x018407f0` turns false after one; event 3 zeroes `+0xf8`.
  A breakpoint on `0x01844bc4`, `0x01844edc`, `0x0184415c` and `0x018407f0` through a hosted ladder
  separates them.
- The order of the network update's message drain (`0x006a9a20`, called from `0x00ef4a9c`,
  `0x01109250`, `0x01109308`) against content 40's tick (`0x010dae70`, from `0x010c5f40` and
  `0x010c9c34`) inside one frame is unread ([the trade page](swsh_trade.md#the-pump)). By the pump's
  order, a command reaching the master between its state-10 write of the shared value and the commit
  that follows the adoption is cleared by that commit. That the writing station reads its own shared
  value back only once its message returns through the loopback sender is inferred.
- What spends the first `syncCommand` a joiner sends. The registrar sets the committed phase to 0
  before any pump runs, so a tail commit of phase 0 does not.
- What a console does with a partner's `RequestForcedProceed{c, c+1}`
  ([the trade page](swsh_trade.md#the-cancel-and-proceed-messages)). By the handler it writes `c+1`
  as the shared value; on the master the adoption and the commit would then send its next command
  with no `syncCommand` received, and a target other than the announced phase would be committed
  through slot 7 with no command. No retail console sends the message, and none has been sent to one.
- The five stars a retail Sword drew on a received League Card. The card carried 4 at 0x177 and
  zero at 0x1B6 and 0x1B7, which the front's formula draws as four
  ([the trade page](swsh_trade.md#the-league-card)); which view the player read, or whether the card
  sent differed, is unmeasured, and setting 0x177, 0x1B6 and 0x1B7 one per run separates them. The
  flags behind 0x177's grade 4 and behind 0x1B3, 0x1B6 and 0x1B7 are unnamed; none of the four
  hashes is FNV-1a 64 of a printable string in rodata. That grade 4 marks the Champion title is
  inferred from its outranking eight badges.
- That a partner card differing from a filed one only in the u64 at 0x1A8 brings the League Card
  question back follows from `0x013fbc40` and is unmeasured.
- Sword against Shield. Everything read off the binary is Shield's; the console is Sword. The
  passphrase, the game key and the Pia version hold across the pair. The local communication id does
  not: `0x0100ABF008968000` is Sword's. Mystery Gift's state names are Shield-only readings. That a
  Sword tests bit 0 of a card's version mask follows from Shield's code with Sword's version 44
  (`0x2C`) in place of `0x007d4270`'s `0x2D`, and from PKHeX's `RestrictVersion` (1 Sword, 2 Shield,
  3 both); no Sword instruction has been read.
- Mystery Gift redemption ([the gift page](swsh_gift.md)): what the console shows, and whether the
  card counts as received, when a kind-1 Pokemon finds no room (`0x010159d0` returns `{0, 1}` and its
  caller stores it untested); whether anything reads the last-receipt table at album `+0x15c0`
  (accesses at those offsets elsewhere in `0x00fe0000..0x01460000` were not tied to the album). The
  keep path `0x00ff14c0` and redemption have not been read in full for legality checks; illegal moves
  were accepted on a retail console.

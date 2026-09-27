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
  `CallRaidBattleMatchingEvent_`); what the three 64-bit keys behind the first sample bits name; what
  the Battle Stadium team descriptor's `+0`, `+4` and `+6` and match type 3 are. That the 0x100 bytes
  at 0xBF6+4 are an RSA-2048 signature over the stored-form party is inferred from the `ModExp` call
  and its 0x148 stride.
- Which station `+0xf8` of the station object names. `0x018407f0` treats the station whose own id
  equals it as the one that writes the shared value, and content 40 addresses its pending body to it.
  It is stored from slot `0xf0/8` of the network backend (`0x01844ebc`, `0x01844b3c`, the latter
  followed by `0x018412a0(obj, 2, id)` on a change), which reads as the session host re-read on host
  migration; whether the backend returns Pia's host or an election of its own is unread.
- The measured two rungs per command fit the path command, flag, pump states 8 to 10, the shared
  value, adoption into the phase, then the next command
  ([the trade page](swsh_trade.md#the-pump)). Two links are inferred: that the commit follows the
  adoption, and that the delegate's slot 0 is `0x010dbf40`. The order of a commit and a command
  arriving in the same frame is unread, and so is which message reaches content 40's interface at
  `content+0x68` (`0x010dc920`, `0x010dcaa0`). That the writing station reads its own shared value
  back only once its message returns through the loopback sender is inferred.
- Which card fields set the five stars a Sword draws on a received League Card; `dex_complete` does
  not. The card carried 0x31 = 1, 400 owned, 7 shiny, 380 caught.
- Whether fields other than the trainer id also take part in the League Card match
  ([the trade page](swsh_trade.md#the-league-card)); a new name or Pokédex count does not.
- Sword against Shield. Everything read off the binary is Shield's; the console is Sword. The
  passphrase, the game key and the Pia version hold across the pair. The local communication id does
  not: `0x0100ABF008968000` is Sword's. Mystery Gift's state names are Shield-only readings, and so is
  `0x007d4270` returning `0x2D`: which bit of a card's version mask a Sword tests is unread.
- Mystery Gift redemption ([the gift page](swsh_gift.md)): whether a kind-1 card is refused with the
  party and boxes full (`0x010159d0` calls `0x013b4900` and `0x013af4a0`; no error return was found in
  the part read); what the kind-5 counter at `status+0x64` is; what the kind-1 builder's IV count at
  `[sp+0x110]` and its `0xFFFF` IVs become; what the second per-id table (`0x01449560`) records. The
  keep path `0x00ff14c0` and redemption have not been read in full for legality checks; illegal moves
  were accepted on a retail console.

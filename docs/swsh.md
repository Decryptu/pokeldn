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
its save and returned the player to the overworld.

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

- The two unnamed Pia header fields, the byte at 0x05 and the halfword at 0x06. Written by
  `0x017beb74`/`0x017beb78`; both were zero in every packet captured.
- Inside the player profile ([the protocol page](swsh_protocol.md#the-player-profile)): what the
  four floats of a sample measure, the u16 before the samples, the u16 in the activity group (170
  in every trade capture, 188 in the one trade-screen beacon read), and which session kind fills the 392-byte
  block at 0xBF6 that Link Trade leaves zero.
- Where a materialised Wonder Card is kept. The importer builds a `0x3A8` card object and the album
  re-encodes it, since neither the 720-byte record nor any string in it appears in the save.
- How a partner's command reaches a sub-element's body word. The receive handler `0x010dbc90` does
  not write it. That an arriving command lets the shared value move is inferred from a per-station
  flag and from every run so far.
- The elementId-10000 hash inputs. The formula is read (a CRC-32 quorum over the sub-elements'
  clocks); an inversion search over every clock in the observed window finds no two-station
  solution, so either the channel's list holds more than two stations or the hashed clock is not the
  envelope clock.
- Sword against Shield. Everything read off the binary is Shield's; the console is Sword. The
  passphrase, the game key and the Pia version hold across the pair. The local communication id does
  not: `0x0100ABF008968000` is Sword's. Mystery Gift's state names are Shield-only readings.
- A third sub-element kind takes two-byte bodies (`0x006d69f0`, `cmp x2,#2`). Which element field
  carries it is unknown; the confirmation element's update touches only `+0xd0`, `+0xf0` and `+0x110`
  and all three are accounted for.

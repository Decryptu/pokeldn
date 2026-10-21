---
title: FireRed and LeafGreen
nav_order: 4
has_children: true
---

# FireRed and LeafGreen

The Switch release of FireRed and LeafGreen is the original GBA ROM in an emulator, with two link
layers stacked:

| layer | whose | documented in |
|---|---|---|
| LDN and Pia | the emulator's, shared with every Switch title | [The wireless layer](ldn.md) |
| the GBA link: RFU frames, seats, block sends | the ROM's | these pages |

[pret/pokefirered](https://github.com/pret/pokefirered) at `REVISION >= 0xA` is authoritative for
the game-level protocol. The French cartridges report software version `0x0A` and game codes `BPRF`
(FireRed) and `BPGF` (LeafGreen). The host carries ROM and RAM addresses for the English, German,
Italian, Spanish and Japanese pairs as well, twelve cartridges in total, and Mystery Gift picks one
from the game code once the player chooses pokeldn in the Friend list. Coverage is under
[Retail verification](frlg_rom_map.md#retail-verification) and
[The cartridge maps](frlg_rom_map.md#the-international-revision-0x0a-cartridges).

A console that leaves about three seconds after associating, once the Pia session has finalized,
received an association response without 6, 9 and 12 Mbit/s ([frlg_link.md](frlg_link.md), The
advertised rate set). A missing Pia type 2 Join Response gives the same symptom.

## What works

On retail hardware, on both cartridges, the host serves Mystery Gift in both directions, trade as
host and joiner, the Union Room with full link battles, Wonder News, the cable-club colosseum and a
visiting Battle Tower trainer.

Through the gift link's two interpreters the console runs code sent to it: memory read and written,
the ROM mapped into named functions per build, its functions called with eight arguments, and a
host-chosen Pokemon built by its own `CreateMon` into the party. The RNG is predicted end to end; an
aimed shiny encounter costs one A press per attempt.

The interface between the guest and the wrapper is mapped on [Code on the console](frlg_rom.md#coverage),
and the wrapper's scan pipeline to its first stage on
[The wrapper's own scan pipeline](frlg_rom.md#the-wrappers-own-scan-pipeline).

## Pages

| page | contents |
|---|---|
| [The link protocol](frlg_link.md) | the RFU link layer, the seat barrier, the Union Room, chat, link battles, the cable-club colosseum |
| [Mystery Gift](frlg_gift.md) | the gift session, authoring gifts, Wonder News, the visiting trainer, the blocked Wireless Communication path |
| [Code on the console](frlg_rom.md) | the Mystery Event VM, native ARM payloads, the live save |
| [The ROM map](frlg_rom_map.md) | address sources, the four function tables, the species table, the French Easy Chat vocabulary |
| [The random number generator](frlg_rng.md) | reading and predicting `gRngValue`, the field stubs that aim an encounter |
| [LeafGreen](frlg_leafgreen.md) | the offset map to FireRed, the English build as an instrument |
| [Host implementation](frlg_host.md) | the components of the trade and Mystery Gift hosts |

## Rules

- LeafGreen runs the same code at a piecewise-constant offset ([LeafGreen](frlg_leafgreen.md)).
  Never predict an address across an unbracketed span.
- The decomp's link order is evidence; its addresses need measuring on the cartridge.
  `pokeldn/frlg/rom/rom_map.py` records how each address was obtained.
- A payload runs offline under unicorn (`buffer_script.emulate`, `emulate_repeating`, both simulated
  consoles) before it is sent. One that faults or never returns 1 hangs the Mystery Gift menu; a
  field stub that loops forever freezes the overworld.

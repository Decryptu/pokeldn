---
title: FireRed and LeafGreen
nav_order: 4
has_children: true
---

# FireRed and LeafGreen

The Switch release of FireRed and LeafGreen is the original GBA ROM running inside an emulator, so
two link layers are stacked:

| layer | whose | documented in |
|---|---|---|
| LDN and Pia | the emulator's, shared with every other Switch title | [The wireless layer](ldn.md) |
| the GBA link: RFU frames, seats, block sends | the ROM's | these pages |

[pret/pokefirered](https://github.com/pret/pokefirered) is authoritative for the whole game-level
protocol at `REVISION >= 0xA`. Cartridge header, read off both consoles: software version `0x0A`,
game code `BPRF` (FireRed, French) and `BPGF` (LeafGreen, French).

A console that leaves about three seconds after associating, once the Pia session has finalized,
was given an association response without 6, 9 and 12 Mbit/s ([frlg_link.md](frlg_link.md), The
advertised rate set); a missing Pia type 2 Join Response gives the same symptom.

## What works

On retail hardware, on both cartridges, the host serves every activity the console offers: Mystery
Gift in both directions, trade as host and as joiner, the whole Union Room including full link
battles, Wonder News, the cable-club colosseum, and a visiting Battle Tower trainer.

Through the gift link's two interpreters the console also runs code sent to it: its memory read and
written, its ROM mapped into named functions for the build it runs, its own functions called with
eight arguments, and a Pokemon chosen by the host built by its own `CreateMon` and left in the
player's party. The RNG is closed end to end; an aimed shiny encounter costs one A press per
attempt.

The guest-to-wrapper boundary is decoded ([Code on the
console](frlg_rom.md#where-the-boundary-stands)): the guest's one store past a region's backing
is byte-precise and constant-valued, a planted pointer's consumers read their targets from
`main`'s own data at static addresses, and the syscalls' stores into the component are read
back as counts and GBA addresses, every address bounds-checked. The wrapper's own scan
pipeline is decoded to its first stage ([The wrapper's own scan
pipeline](frlg_rom.md#the-wrappers-own-scan-pipeline)): the scan results, the consume loop
and the parent-candidate list are all fixed-shape and bounded, and the one length-taking
path (a station name, at most `0x40`) is clamped at its caller.

## Pages

| page | contents |
|---|---|
| [The link protocol](frlg_link.md) | the RFU link layer, the seat barrier, the Union Room, chat, link battles, and the cable-club colosseum |
| [Mystery Gift](frlg_gift.md) | the gift session, authoring gifts, Wonder News, the visiting trainer, and the blocked Wireless Communication path |
| [Code on the console](frlg_rom.md) | the Mystery Event VM, native ARM payloads, and reading and writing the live save |
| [The ROM map](frlg_rom_map.md) | how addresses were measured, the four function tables, the species table, and the French Easy Chat vocabulary |
| [The random number generator](frlg_rng.md) | reading and predicting `gRngValue`, and the field stubs that aim an encounter |
| [LeafGreen](frlg_leafgreen.md) | what the second cartridge shares, the measured offset map, and the English build as an instrument |
| [Host implementation](frlg_host.md) | the component boundaries of the trade and Mystery Gift hosts |

## The two cartridges

LeafGreen runs the same code at a piecewise-constant offset; the measured pairs and the boundaries
are on [LeafGreen](frlg_leafgreen.md). Never predict an address across an unbracketed boundary.

## Rules that hold across all of it

- The decomp's link order is evidence; its addresses need measuring on the cartridge.
  `pokeldn/frlg/rom/rom_map.py` records how each address was obtained.
- A payload runs offline under unicorn (`buffer_script.emulate`, `emulate_repeating`, both simulated
  consoles) before it is sent. One that faults or never returns 1 hangs the Mystery Gift menu with
  no way out; a field stub that loops forever freezes the overworld.

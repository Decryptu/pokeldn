# Vendored GB-Link Team cards

The ARM sources of the GB-Link Team's custom Wonder Cards for the Switch's FireRed and LeafGreen.
`scripts/gen_team_cards.py` assembles them into `pokeldn/frlg/data/team_cards.json`
([docs/frlg_gift.md](../../docs/frlg_gift.md#gb-link-team-cards)).

## Upstream

- Project: <https://github.com/GB-Link/GB-Link-Switch-LDN>, directory `cards/`, itself from
  gblink-wondercards (`tools/native-cards`)
- Upstream revision: `c1a3a97f3ab5c60e87307089d6b7db10e3fd5993`
- License: GPL-3.0 (the repository is AGPL-3.0); the license text is in `LICENSE`.

`build.mjs` is not vendored, nor the sources of the cards pokeldn makes its own way (`berries.s`, `starter.s`, `follow.s`): `scripts/gen_team_cards.py` is its port, the same script commands, cards
and texts. `kept/` holds the six Wonder Cards `build.mjs` keeps whole from its payload file (the five
speed cards and the Pocket Casino), cut from those payloads.

## Local changes

- `symbols.json` replaces `roms.mjs`: its English entries, plus the same symbols found on the French
  cartridges `BPRF` and `BPGF`.
- `shiny.s`, `roamer.s`, `fly.s`, `tm.s`, `split.s`, `pc.s`, `fieldmoves.s`, `expshare.s`:
  `install` points `gIntrTable[4]` at `VBlankIntr` before its copy, chains to `VBlankIntr` instead of
  the handler it finds, and stores it at `RESIDENT - 4` (lines marked `pokeldn:`).

Keep this file current whenever the vendored copy is rebased or modified.

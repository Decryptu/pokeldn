---
title: Home
nav_order: 1
---

# pokeldn

pokeldn is a Linux implementation of Nintendo Switch local wireless (LDN) that speaks to Pokemon
games running on retail Switch hardware. These pages document the protocols involved, with the
decompilation citations, disassembly addresses and hardware measurements behind each finding.

Installation, the command-line reference and the code layout are in the
[repository README](https://github.com/Decryptu/pokeldn#readme).

## Targets

Four games, all on retail hardware, all over the same LDN and Pia layers:

| | FireRed / LeafGreen | Let's Go Pikachu / Eevee | Sword / Shield | Brilliant Diamond / Shining Pearl |
|---|---|---|---|---|
| Trade | yes, as host and as joiner | yes, as host and as joiner | yes, joining the console's Link Trade | yes, joining the console's Union Room |
| Mystery Gift | yes, distribute and receive | the game has none over local wireless | yes, distribute a Wonder Card | the game has none over local wireless |
| Link battle | yes, Union Room and colosseum | not tried | not tried | as far as the lobby |
| Code on the console, save read and write | yes, over a Mystery Gift session | no | no | no |

FireRed and LeafGreen run as the original GBA ROM inside an emulator on the Switch, so the ROM's
own GBA link protocol is stacked on the console's LDN and Pia. The three other games put their
own code directly on Pia: Unity/IL2CPP in Brilliant Diamond and Shining Pearl, C++ with protocol
buffers over `gflnet3` in Sword and Shield and in Let's Go.

## Sections

| section | contents |
|---|---|
| [The wireless layer](ldn.md) | LDN and Pia: advertisements, association, packet formats by version, session-key derivation. Game-independent. |
| [Reverse-engineering a Switch title](switch_re.md) | Reading a retail game's own code: NCA/RomFS extraction in place, IL2CPP metadata, C++ RTTI. General method. |
| [FireRed and LeafGreen](frlg.md) | The GBA link, Mystery Gift, code execution on the console, the RNG, the two cartridges. |
| [Brilliant Diamond and Shining Pearl](bdsp.md) | Pia 5.27-5.45, the Union Room, and the trade flow. |
| [Sword and Shield](swsh.md) | Pia 4, the sync framework, trading, and the Mystery Gift local branch. |
| [Let's Go Pikachu and Eevee](lgpe.md) | Pia 3, the link code, and the trade flow. |
| [Hardware and setup](hardware.md) | Adapters, Raspberry Pi deployment, Switch keys. |

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.

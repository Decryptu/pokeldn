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

Seven games, all on retail hardware, all over the same LDN and Pia layers:

| | FRLG | LGPE | SwSh | BDSP | PLA | SV | PLZA |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Trade | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mystery Gift | ✓ | ∅ | ✓ | ∅ | ∅ | ∅ | ✗ |
| Link battle | ✓ | ✗ | ✗ | ✗ | ∅ | ✗ | ✗ |
| Code on the console, save read and write | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

✓ works on a retail console · ✗ not done · ∅ the game has no such feature over local wireless
FRLG FireRed/LeafGreen · LGPE Let's Go Pikachu/Eevee · SwSh Sword/Shield · BDSP Brilliant Diamond/Shining Pearl · PLA Legends Arceus · SV Scarlet/Violet · PLZA Legends Z-A

FireRed and LeafGreen run as the original GBA ROM inside an emulator on the Switch, so the ROM's
own GBA link protocol is stacked on the console's LDN and Pia. The six other games put their own
code directly on Pia: Unity/IL2CPP in Brilliant Diamond and Shining Pearl, C++ with protocol
buffers over `gflnet3` in Sword and Shield and in Let's Go, and C++ with Pia statically linked in
Legends Arceus, in Scarlet and Violet and in Legends Z-A.

## Sections

| section | contents |
|---|---|
| [The wireless layer](ldn.md) | LDN and Pia: advertisements, association, packet formats by version, session-key derivation. Game-independent. |
| [Reverse-engineering a Switch title](switch_re.md) | Reading a retail game's own code: NCA/RomFS extraction in place, IL2CPP metadata, C++ RTTI. General method. |
| [FireRed and LeafGreen](frlg.md) | The GBA link, Mystery Gift, code execution on the console, the RNG, the two cartridges. |
| [Brilliant Diamond and Shining Pearl](bdsp.md) | Pia 5.27-5.45, the Union Room, and the trade flow. |
| [Sword and Shield](swsh.md) | Pia 4, the sync framework, trading, and the Mystery Gift local branch. |
| [Let's Go Pikachu and Eevee](lgpe.md) | Pia 3, the link code, and the trade flow. |
| [Legends Arceus](pla.md) | Pia header version 11, the trade flow, and the record a host composes. |
| [Scarlet and Violet](sv.md) | Pia header version 11, the reliable streams, and the trade a host runs. |
| [Legends Z-A](za.md) | Pia header version 16, the game's twenty trade messages, and the trade a joiner runs. |
| [Hardware and setup](hardware.md) | Adapters, the ESP32 radio, Raspberry Pi deployment, Switch keys. |

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.

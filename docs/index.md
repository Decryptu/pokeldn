---
title: Home
nav_order: 1
---

# pokeldn

pokeldn is an implementation of Nintendo Switch local wireless (LDN) that speaks to Pokemon games
running on retail Switch hardware, through an ESP32 board as its radio: on USB serial from a computer
or an Android phone, or over Bluetooth from an iPhone. These pages document the protocols involved,
with decompilation citations, disassembly addresses and hardware measurements.

Start with [app setup](gui.md) or [command-line usage](usage.md).
[Code organization](architecture.md) covers the shared modules and tests.

## Targets

Seven games, all on retail hardware, all over the same LDN and Pia layers:

| | FRLG | LGPE | SwSh | BDSP | PLA | SV | PLZA |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Trade | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mystery Gift | ✓ | ∅ | ✓ | ∅ | ∅ | ∅ | ∅ |
| Event Pokemon | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
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
| [Sword and Shield](swsh.md) | Pia 4, the sync framework, trading, Max Raid Battles in both roles, Dynamax Adventures, and the Mystery Gift local branch. |
| [Let's Go Pikachu and Eevee](lgpe.md) | Pia 3, the link code, and the trade flow. |
| [Legends Arceus](pla.md) | Pia header version 11, the trade flow, and the record a host composes. |
| [Scarlet and Violet](sv.md) | Pia header version 11, the reliable streams, the trade a host runs, Tera Raids in both roles, and the Union Circle as a guest. |
| [Legends Z-A](za.md) | Pia header version 16, the game's twenty trade messages, and the trade in both roles. |
| [Simulated Mystery Gifts](gift_simulated.md) | Official gift Pokemon traded by the host to the five titles with no local Mystery Gift, made for the receiving save. |
| [Command-line usage](usage.md) | Source setup and commands for each game. |
| [Desktop app](gui.md) | Setup, Bank, controller, updates and builds; the same app on Android and iOS. |
| [Code organization](architecture.md) | Shared modules, Pokémon preparation and verification. |
| [Hardware and setup](hardware.md) | The ESP32 radio, Switch keys, and legacy Linux Wi-Fi cards. |
| [Code signing policy](code_signing.md) | What the Windows release signs, the team roles, and the privacy policy. |

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.

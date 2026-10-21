---
title: Home
nav_order: 1
---

# pokeldn

pokeldn is an implementation of Nintendo Switch local wireless (LDN) that speaks to Pokemon games
on retail Switch hardware through an ESP32 board as its radio, on USB serial from a computer or an
Android phone or over Bluetooth from an iPhone. These pages document the protocols with decompilation
citations, disassembly addresses and hardware measurements.

Start with [app setup](gui.md) or [command-line usage](usage.md).

## Targets

Seven games share the same LDN and Pia layers:

| | FRLG | LGPE | SwSh | BDSP | PLA | SV | PLZA |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Trade | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mystery Gift | ✓ | ∅ | ✓ | ∅ | ∅ | ∅ | ∅ |
| Event Pokemon | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Link battle | ✓ | ✗ | ✗ | ✗ | ∅ | ✗ | ✗ |
| Code on the console, save read and write | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

✓ works on a retail console · ✗ not done · ∅ the game has no such feature over local wireless
FRLG FireRed/LeafGreen · LGPE Let's Go Pikachu/Eevee · SwSh Sword/Shield · BDSP Brilliant Diamond/Shining Pearl · PLA Legends Arceus · SV Scarlet/Violet · PLZA Legends Z-A

FireRed and LeafGreen run as the GBA ROM inside the Switch's emulator, so the ROM's GBA link protocol
sits on LDN and Pia. The six other games put their own code directly on Pia: Unity/IL2CPP in BDSP, C++ with protocol buffers over `gflnet3` in SwSh
and LGPE, and C++ with Pia statically linked in PLA, SV and PLZA.

## Sections

| section | contents |
|---|---|
| [The wireless layer](ldn.md) | LDN and Pia: advertisements, association, packet formats by version, session-key derivation. |
| [Reverse-engineering a Switch title](switch_re.md) | Reading a retail game's own code: NCA/RomFS extraction in place, IL2CPP metadata, C++ RTTI. |
| [FireRed and LeafGreen](frlg.md) | GBA link, Mystery Gift, code execution, RNG, cartridges. |
| [Brilliant Diamond and Shining Pearl](bdsp.md) | Pia 5.27-5.45, the Union Room, and the trade flow. |
| [Sword and Shield](swsh.md) | Pia 4, sync framework, trade, Max Raids, Dynamax Adventures, Mystery Gift. |
| [Let's Go Pikachu and Eevee](lgpe.md) | Pia 3, the link code, and the trade flow. |
| [Legends Arceus](pla.md) | Pia header version 11, trade flow, composed record. |
| [Scarlet and Violet](sv.md) | Pia header version 11, reliable streams, trade, Tera Raids, Union Circle. |
| [Legends Z-A](za.md) | Pia header version 16 and the twenty trade messages. |
| [Simulated Mystery Gifts](gift_simulated.md) | Official gift Pokemon traded by the host to titles with no local Mystery Gift. |
| [Command-line usage](usage.md) | Source setup and commands for each game. |
| [Desktop app](gui.md) | Setup, Bank, controller, builds; Android and iOS. |
| [Code organization](architecture.md) | Shared modules, Pokémon preparation and verification. |
| [Hardware and setup](hardware.md) | The ESP32 radio, Switch keys, and legacy Linux Wi-Fi cards. |
| [Code signing policy](code_signing.md) | What the Windows release signs, the team roles, and the privacy policy. |

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.

# pokeldn 0.2.2

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- Evolved Pokemon build legally far more often. An evolved species takes the ability of its own
  species, a trade evolution (Alakazam, Politoed, Scizor and similar) receives a second handling
  trainer, and evolutions that count something (Sirfetch'd, Runerigus, Annihilape, Gholdengo) start
  from that count. Plain builds that failed fall from 48 to 7 in Brilliant Diamond and Shining Pearl,
  from 7 to 0 in Let's Go and from 4 to 0 in Legends Arceus.
- A build no longer fails at random. A wild encounter's level and personality are rolled at random, and
  about one build in ten of a chosen level was refused; each encounter now gets several rolls.
- A level below the lowest one a game offers says so, for example "Mewtwo cannot be lower than level
  100 in this game".

## Downloads

| Computer | File |
|---|---|
| macOS, Apple silicon | `pokeldn-macos-arm64.zip` |
| Windows, x64 | `pokeldn-windows-x64.exe` |
| Linux, x64 | `pokeldn-linux-x64.tar.gz` |

Each app includes PKHeX.Core and firmware for classic ESP32, ESP32-S3 and ESP32-C3. Python, .NET
and ESP-IDF are bundled or unnecessary for running the app. Supply your own `prod.keys`.
The separate `pokeldn-radio*.bin` files are merged firmware images for manual flashing at address
`0x0`; the app selects the right image for the connected chip. `SHA256SUMS` covers all six downloads.

## First run

1. Extract the macOS or Linux archive, or launch the Windows executable. On macOS, the app is
   unsigned; use right-click, Open for the first launch.
2. Choose `prod.keys` when prompted.
3. Connect one supported board with a USB data cable. S3 and C3 boards use native USB Serial/JTAG;
   attach the external antenna on a Seeed Studio XIAO ESP32C3.
4. On Board, select the port, press Flash, then Identify.
5. On Games, choose a game and a tool, build an offer or select a Pokemon file, and follow the
   console instructions before starting.

Received Pokemon are saved in `Documents/pokeldn/Received`, with a configurable folder in Settings.

## Supported features

- Trades in both directions: FireRed/LeafGreen, Let's Go Pikachu/Eevee, Sword/Shield, Brilliant
  Diamond/Shining Pearl, Legends Arceus, Scarlet/Violet and Legends Z-A.
- Mystery Gift: FireRed/LeafGreen and Sword/Shield.
- Legal Pokemon preparation with PKHeX.Core, board detection and flashing, and session recordings.

## Platform notes

macOS requires Apple silicon. Linux requires GTK 3, libsecret and access
to the serial port; on distributions using the `dialout` group, run `sudo usermod -aG dialout "$USER"`
and log out and back in. ESP32-S2 and ESP32-C6 are unsupported.

[Setup and protocol documentation](https://decryptu.github.io/pokeldn/) contains the per-game
requirements. Attach the latest session recording from Settings to an
[issue](https://github.com/Decryptu/pokeldn/issues) when reporting a problem.

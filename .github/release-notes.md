# pokeldn 0.10.0

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- FireRed and LeafGreen support English, French, German, Italian, Spanish and Japanese,
  including the 44 GB-Link Team cards and game boosts on all twelve cartridges.
- Game language is detected after choosing pokeldn in the Mystery Gift Friend list. The Basic
  screen explains this directly below Version.
- Japanese cartridges use their own RAM addresses, text layout and save checksums. Japanese
  Wonder Cards, Wonder News and native `.wc3` files use their compact formats; kana names decode
  correctly. Built-in gift dialogue uses Roman text.
- Native `.wc3` export asks which version and language to save when cartridge variants differ.
  A `.pokegift` keeps every supported cartridge together.
- The Spanish FireRed HM card now starts at the correct field-move script entry.

All twelve cartridge tables were checked against their extracted ROMs. The newly added German,
Italian, Spanish LeafGreen and Japanese cartridges passed offline emulation checks; their Switch
wireless delivery remains unverified on retail hardware.

Everything from 0.9.1 is included: the 171 official Sword/Shield event cards, native `.wc3` and `.wc8`
gift files, the official FireRed/LeafGreen distribution eggs and event Pokemon, the GB-Link Team's
custom cards, Sword/Shield outfits, money and Gigantamax Pokemon, and the clearer Game boosts,
Mom restore and save-readout instructions.

The firmware is unchanged (1.4.0); a board flashed by 0.7.0 or later needs no reflash.

pokeldn is an unofficial fan project, not affiliated with Nintendo or The Pokemon Company. It is not
meant for commercial or promotional use; see the License section of the README.

## Downloads

| Computer | File |
|---|---|
| macOS, Apple silicon | `pokeldn-macos-arm64.zip` |
| Windows, x64 | `pokeldn-windows-x64.exe` |
| Linux, x64 | `pokeldn-linux-x64.tar.gz` |

Each app includes PKHeX.Core and firmware for classic ESP32, ESP32-S3, ESP32-C3 and ESP32-C6. Python, .NET
and ESP-IDF are bundled or unnecessary for running the app. Supply your own `prod.keys`.
The separate `pokeldn-radio*.bin` files are merged firmware images for manual flashing at address
`0x0`; the app selects the right image for the connected chip. `SHA256SUMS` covers all seven downloads.

## First run

1. Extract the macOS or Linux archive, or launch the Windows executable.
   - macOS: the app is unsigned, so the first launch is blocked. Open it once and close the warning,
     then open System Settings, Privacy & Security, scroll down to Security and press Open Anyway next
     to pokeldn, then confirm with your password. Later launches open normally.
   - Windows: if SmartScreen stops the app, choose More info, then Run anyway.
2. Choose `prod.keys` when prompted.
3. Connect one supported board with a USB data cable. S3, C3 and C6 boards use native USB Serial/JTAG.
   A board that ships an external antenna, such as the Seeed Studio XIAO ESP32C3 or XIAO ESP32S3,
   needs it attached; larger S3 boards such as the N8R2 and N16R8 have an onboard antenna.
4. On Board, press Flash. The app checks the board on its own and shows Board ready.
5. On Games, choose a game and a tool, build an offer or select a Pokemon file, and follow the
   console instructions before starting.

Received Pokemon are saved in `Documents/pokeldn/Received`, with a configurable folder in Settings.

## Supported features

- Trades in both directions: FireRed/LeafGreen, Let's Go Pikachu/Eevee, Sword/Shield, Brilliant
  Diamond/Shining Pearl, Legends Arceus, Scarlet/Violet and Legends Z-A.
- Mystery Gift: FireRed/LeafGreen and Sword/Shield.
- Legal Pokemon preparation with PKHeX.Core, board detection and flashing, and session recordings.

## Platform notes

macOS requires Apple silicon and macOS 12 or later. Linux requires GTK 3, libsecret and access
to the serial port; on distributions using the `dialout` group, run `sudo usermod -aG dialout "$USER"`
and log out and back in. ESP32-S2 is unsupported.

[Setup and protocol documentation](https://decryptu.github.io/pokeldn/) contains the per-game
requirements. Attach the latest session recording from Settings to an
[issue](https://github.com/Decryptu/pokeldn/issues) when reporting a problem.

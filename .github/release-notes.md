# pokeldn 0.6.2

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- Linux: sessions over the radio board no longer need root. In 0.6.1 and earlier the Linux app
  created a kernel network interface for the board, which an ordinary user may not do, so a session
  stopped right after it started even though flashing worked. The app now uses its own network stack
  on Linux, as it already did on macOS and Windows.
- Files can be dragged from the desktop onto the app. A Pokemon file or a Showdown team (`.txt`)
  dropped on a trade fills it, and extra files go to the following trades. Files dropped on Add a
  trade queue one trade each. A gift file dropped on the Gift card opens it, a `.bin` dropped on
  Flash the firmware becomes the custom image, and every file field takes the file it asks for.
- Add a trade is a small card centered under the Pokemon to offer.

The firmware is unchanged (1.2.0); a board flashed by 0.6.1 needs no reflash.

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

# pokeldn 0.13.0

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- A smaller download: the macOS app goes from 51 MB to 41 MB; the Windows and Linux apps drop the
  same unused parts.
- Legends Z-A hosting: when the host closes on its own (a timed close, the time limit or Stop) while
  the console sits on its trade box, the console now shows "Your trading partner chose to quit
  trading" and returns to Link Play, instead of Error 6.
- Scarlet/Violet hosting: if a console takes a seat but never opens the trade, the session log names
  the step it is waiting on, to attach to an issue.

Firmware 1.5.0: ESP32-S3, C3 and C6 boards keep reading the app's commands under heavy traffic
(an S3 could stop listening for up to a minute), and the XIAO ESP32S3's yellow LED shows the
board's state. Reflash S3, C3 and C6 boards from the Board page; a classic ESP32 on 1.4.0 needs no
reflash.

pokeldn is an unofficial fan project, not affiliated with Nintendo or The Pokemon Company. It is not
meant for commercial or promotional use; see the License section of the README.

## Downloads

| Computer | File |
|---|---|
| macOS, Apple silicon | `pokeldn-macos-arm64.zip` |
| Windows, x64 | `pokeldn-windows-x64.zip` |
| Linux, x64 | `pokeldn-linux-x64.tar.gz` |

Each app includes PKHeX.Core and firmware for classic ESP32, ESP32-S3, ESP32-C3 and ESP32-C6. Python, .NET
and ESP-IDF are bundled or unnecessary for running the app. Supply your own `prod.keys`.
The separate `pokeldn-radio*.bin` files are merged firmware images for manual flashing at address
`0x0`; the app selects the right image for the connected chip. `SHA256SUMS` covers all seven downloads.

## First run

1. Extract the archive for your computer. On Windows, run `pokeldn.exe` inside the extracted `pokeldn` folder.
   - macOS: the app is unsigned, so the first launch is blocked. Open it once and close the warning,
     then open System Settings, Privacy & Security, scroll down to Security and press Open Anyway next
     to pokeldn, then confirm with your password. Later launches open normally.
   - Windows: if SmartScreen stops the app, choose More info, then Run anyway.
2. Choose `prod.keys` when prompted.
3. Connect one supported board with a USB data cable. S3, C3 and C6 boards use native USB Serial/JTAG.
   On Windows, a classic ESP32 needs its USB chip's driver first (CP210x or CH340); the Board page
   links both, says how to install them and names the one missing.
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

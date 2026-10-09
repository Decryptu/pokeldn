# pokeldn 0.18.2

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- FireRed/LeafGreen Mystery Gift: a value left on the tool's All options tab for `--gift` or
  `--buffer-script` no longer stops a run. It overrode the Gift card's choice, so an Event Pokemon,
  a card, a Game boost or a save backup was refused before anything was sent. The Gift card now
  owns those options; they are gone from All options and an old saved value is ignored.
- From 0.18.1: on macOS the Board and Control pages find the controller board over Bluetooth again.
- From 0.18.0: a redesigned Board page shows each board's firmware and version and installs
  Wireless or Controller on any board; controller button presses are no longer dropped.

The radio firmware is unchanged at 1.6.1; wireless boards need no update. The controller firmware is
1.2.0; the Board page offers the update.

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
The separate `pokeldn-radio*.bin` (wireless) and `pokeldn-pad*.bin` (controller) files are merged
firmware images for manual flashing at address `0x0`; the app selects the right image for the
connected chip. `pokeldn-pad.bin`, the classic ESP32 controller over Bluetooth, is untested on a
console. `SHA256SUMS` covers all nine downloads.

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
4. On Board, choose Install beside Wireless. The app checks the board on its own and shows Up to date.
5. On Games, choose a game and a tool, build an offer or select a Pokemon file, and follow the
   console instructions before starting.

Received Pokemon are saved in `Documents/pokeldn/Received`, with a configurable folder in Settings.

## Supported features

- Trades in both directions: FireRed/LeafGreen, Let's Go Pikachu/Eevee, Sword/Shield, Brilliant
  Diamond/Shining Pearl, Legends Arceus, Scarlet/Violet and Legends Z-A.
- Mystery Gift: FireRed/LeafGreen and Sword/Shield.
- Tera Raids in both roles: Scarlet/Violet.
- Legal Pokemon preparation with PKHeX.Core, board detection and flashing, and session recordings.
- An ESP32-S3 as a wired Switch controller, with macros.

## Platform notes

macOS requires Apple silicon and macOS 12 or later. Linux requires GTK 3, libsecret and access
to the serial port; on distributions using the `dialout` group, run `sudo usermod -aG dialout "$USER"`
and log out and back in. ESP32-S2 is unsupported.

[Setup and protocol documentation](https://decryptu.github.io/pokeldn/) contains the per-game
requirements. Attach the latest session recording from Settings to an
[issue](https://github.com/Decryptu/pokeldn/issues) when reporting a problem.

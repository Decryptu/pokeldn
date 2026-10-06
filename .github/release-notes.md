# pokeldn 0.11.1

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- 0.11.1: on macOS the app shows one Dock icon again. 0.11.0 showed a second one that kept
  bouncing.
- FireRed and LeafGreen saves: the Mystery Gift tool's Your save tab backs up the console's whole
  save into the app's library over Mystery Gift, then restores, renames, imports, exports and edits
  saves (trainer and party, with PKHeX). A backup takes about four minutes on a retail French
  FireRed and leaves the console's save unchanged. Restore is checked offline only and is untried
  on retail hardware; back the console up first.
- The app opens about four times faster: on an Apple silicon Mac the window appears in 0.5 s
  instead of 2.5 s, and each trade or gift session starts in under 0.1 s instead of 1.5 s.
- Smaller downloads: the macOS app is 51 MB instead of 121 MB. Unused display components, the
  unused parts of PKHeX's runtime and of the emulator used by Check offline are left out.
- The Windows download is now a zip: extract it and run `pokeldn.exe` inside the `pokeldn` folder,
  keeping the `_internal` folder beside it.
- The app removes the display files its earlier versions left in `~/.flet/client`.
- Sword/Shield gift item pickers list only items a card can carry.
- Preset and official-card tiles line up in even rows.
- A rare `.pk3` that also reads as encrypted data is now opened correctly.

Everything from 0.10.0 is included: FireRed and LeafGreen in English, French, German, Italian,
Spanish and Japanese, the 44 GB-Link Team cards and game boosts on all twelve cartridges, the
171 official Sword/Shield event cards and native `.wc3` and `.wc8` gift files.

The firmware is unchanged (1.4.0); a board flashed by 0.7.0 or later needs no reflash.

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

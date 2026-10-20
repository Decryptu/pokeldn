# pokeldn 0.33.1

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

A maintenance release: no new features, and trades, gifts and raids behave as in 0.33.0.

- Unused code and duplicated helpers removed; the app and its launchers share one copy of the
  record encryption, session keys and link codes of Sword/Shield, Scarlet/Violet, Legends Arceus
  and Legends Z-A.
- Command line: every launcher reads the keys path set in `config/host.local.toml`, and
  `frlg_mg_client.py` reports a mistyped `--password` or `--connect-id` instead of crashing.

The radio firmware stays at 1.7.0 and the controller firmware at 1.3.0; no board update is needed.

pokeldn is an unofficial fan project, not affiliated with Nintendo or The Pokemon Company. It is not
meant for commercial or promotional use; see the License section of the README.

## Downloads

| Computer | File |
|---|---|
| macOS, Apple silicon | `pokeldn-macos-arm64.zip` |
| Windows, x64 | `pokeldn-windows-x64.zip` |
| Linux, x64 | `pokeldn-linux-x64.tar.gz` |
| Android, arm64 | `pokeldn-android-arm64.apk` |
| iPhone and iPad (AltStore, SideStore) | `pokeldn-ios.ipa` |

Each app includes PKHeX.Core and firmware for classic ESP32, ESP32-S3, ESP32-C3 and ESP32-C6. Python, .NET
and ESP-IDF are bundled or unnecessary for running the app. Supply your own `prod.keys`.
The separate `pokeldn-radio*.bin` (wireless; `-ble` for Bluetooth wireless) and `pokeldn-pad*.bin` (controller) files are merged
firmware images for manual flashing at address `0x0`; the app selects the right image for the
connected chip. `SHA256SUMS` covers all thirteen downloads.

Code signing policy: free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org); [what is signed, team roles and privacy](https://decryptu.github.io/pokeldn/code_signing.html).

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
- Tera Raids in both roles and the Union Circle as a guest: Scarlet/Violet.
- Max Raid and Dynamax Adventure hosting: Sword/Shield.
- Legal Pokemon preparation with PKHeX.Core, board detection and flashing, and session recordings.
- An ESP32-S3 as a wired Switch controller or a classic ESP32 as a Bluetooth one, with macros.
- Online trade over public relays, and a GTS for banked Pokemon.

## Platform notes

macOS requires Apple silicon and macOS 12 or later. Linux requires GTK 3, libsecret and access
to the serial port; on distributions using the `dialout` group, run `sudo usermod -aG dialout "$USER"`
and log out and back in. ESP32-S2 is unsupported.

[Setup and protocol documentation](https://decryptu.github.io/pokeldn/) contains the per-game
requirements. Attach the latest session recording from Settings to an
[issue](https://github.com/Decryptu/pokeldn/issues) when reporting a problem.

# pokeldn 0.4.0

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- A new look: a glass toolbar and panels, and Pokemon sprites in the Session panel, on the
  Mystery Gift card and in the Received list.
- Each queued Pokemon gets a check mark when its trade completes.
- A session ends on its own once the console has left after a trade, in every game and both roles;
  Stop is only needed to cut a session short. Start on another tool stops the running session first.
- Let's Go: the link code is three slots; each opens the console's ten Pokemon, as on the Switch.
- Let's Go host: a lost message near the end of a trade no longer leaves the console on its
  confirmation screen.
- Brilliant Diamond/Shining Pearl: pokeldn's character appears ready to trade with no walk, and
  hosting, it comes over the moment the trade emote goes up.
- Legends Arceus: only the Pokemon traded is saved, not every Pokemon the console's cursor passed over.
- Sword/Shield: a Pokemon that exists only as an event keeps its own PID, so hosting with it no longer
  fails; a built Pokemon comes from a wild, static or egg encounter when the species has one. The
  Mystery Gift card id moved to Advanced: a console takes a card built here again under the same id.

The firmware is unchanged; a board flashed by 0.3.x needs no new flash.

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

1. Extract the macOS or Linux archive, or launch the Windows executable.
   - macOS: the app is unsigned, so the first launch is blocked. Open it once and close the warning,
     then open System Settings, Privacy & Security, scroll down to Security and press Open Anyway next
     to pokeldn, then confirm with your password. Later launches open normally.
   - Windows: if SmartScreen stops the app, choose More info, then Run anyway.
2. Choose `prod.keys` when prompted.
3. Connect one supported board with a USB data cable. S3 and C3 boards use native USB Serial/JTAG.
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

macOS requires Apple silicon. Linux requires GTK 3, libsecret and access
to the serial port; on distributions using the `dialout` group, run `sudo usermod -aG dialout "$USER"`
and log out and back in. ESP32-S2 and ESP32-C6 are unsupported.

[Setup and protocol documentation](https://decryptu.github.io/pokeldn/) contains the per-game
requirements. Attach the latest session recording from Settings to an
[issue](https://github.com/Decryptu/pokeldn/issues) when reporting a problem.

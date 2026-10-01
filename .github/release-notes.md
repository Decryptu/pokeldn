# pokeldn 0.3.0

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- Several trades in one session. Add a trade, under the Pokemon to offer, queues up to six; each
  completed trade offers the next one, on every trade tool.
- More options when building a Pokemon: nature, ability, gender, held item, ball, IVs and EVs (AVs in
  Let's Go, effort levels in Legends Arceus). The lists hold only what the species can legally have.
- Female-only species (Vespiquen, Froslass, Wormadam), event gifts and Pokemon that need TM or TR
  records build legally far more often.
- The console leaves cleanly. In every game and in both roles, the app answers the console's goodbye,
  so a player backing out of the trade gets no communication error.
- The Board page checks the board on its own and says what is wrong in plain words: no firmware,
  port in use, or an ESP32-S3 or C3 plugged into its COM/UART socket instead of the one marked USB.
- Before you start, in the Session panel, lists what Start still needs (Switch keys, board, a built
  Pokemon) with a button to fix each.
- Every setting has a short explanation. Settings rarely changed moved to Advanced, and Settings puts
  your setup first.
- The app tells you when a newer release is out.
- Running from source, the Board page downloads the released firmware; no ESP-IDF needed.

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

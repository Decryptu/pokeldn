# pokeldn 0.5.0

This desktop app trades with seven Pokemon game families on a Switch or Switch 2
through an ESP32 radio connected by USB. Nothing is installed on the console.

## What is new

- ESP32-C6 boards are supported, the Seeed Studio XIAO ESP32C6 included: the app flashes and checks
  them, and the board uses its ceramic antenna. FireRed, Sword and Scarlet trades are verified on it.
  The C6 and S3 keep their USB link through restarts.
- One Mystery Gift builder for FireRed and Sword/Shield: start from a preset, build a gift in a form,
  or open a file. FireRed builds Wonder Cards (who hands it over, and Pokemon, item, egg, battle and
  message steps), Wonder News and console code; Sword builds Pokemon, eggs, items, Battle Points and
  clothing cards.
- Gift files: save any gift as a `.pokegift` file and open it later or share it; FireRed and Sword
  files share one format, and native card files convert both ways.
- Import paste: a Showdown, Smogon or PKHeX set fills the build form (species, form, nature,
  ability, item, moves, IVs, EVs); a pasted team fills the trade queue in order.
- Settings, Storage, Clear local files: frees old session records and unused prepared Pokemon,
  keeping your queues, received Pokemon, keys and firmware.
- Sword/Shield: joining finds the console's trade search and no longer stops at its Y-Comm
  beacon; a Battle Points card is listed as Battle Points.
- Scarlet/Violet: when a searching console hands over the host role, pokeldn takes it and the trade
  goes on.
- Let's Go: queued trades no longer stall when one message is lost, and leaving mid-vote no longer
  locks the console out of trading.
- Brilliant Diamond/Shining Pearl: joining waits for the console's Union Room instead of giving up.
- A board that misses one association with the console's network tries again on its own.

The firmware changed: flash the board again from Board after updating.

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

macOS requires Apple silicon. Linux requires GTK 3, libsecret and access
to the serial port; on distributions using the `dialout` group, run `sudo usermod -aG dialout "$USER"`
and log out and back in. ESP32-S2 is unsupported.

[Setup and protocol documentation](https://decryptu.github.io/pokeldn/) contains the per-game
requirements. Attach the latest session recording from Settings to an
[issue](https://github.com/Decryptu/pokeldn/issues) when reporting a problem.

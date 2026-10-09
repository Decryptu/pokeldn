---
title: Controller board
parent: Hardware and setup
nav_order: 5
---

# Controller board

The controller board is an ESP32-S3 that a Switch takes as a wired controller on its USB-C port,
or a classic ESP32 that pairs with it as a Pro Controller over Bluetooth Classic. The host presses
the console's buttons and loads macros the board plays on its own clock. Firmware `firmware/pad`, host side `pokeldn.pad`, app page [The controller](gui.md#the-controller),
command line `tools/switch/pad.py`.

## Which boards

| chip | controller | why |
|---|---|---|
| ESP32-S3 | wired, over USB | its USB-OTG block can be any USB device |
| classic ESP32 | wireless Pro Controller, Bluetooth Classic; the host on its USB-to-serial port | no USB device of its own; it has Bluetooth Classic, the Pro Controller's transport |
| ESP32-C3, ESP32-C6 | none | USB Serial/JTAG is fixed-function, and their Bluetooth is LE only |

## The USB side

The board enumerates as a HORI Pokken controller, `0f0d:0092`, one HID interface with an
interrupt IN and an interrupt OUT endpoint. A Switch accepts this ID as a plain HID gamepad with
no Pro Controller handshake. A retail Switch Lite on firmware 23.0.1 enumerated it from the HOME
menu and moved its cursor on the board's reports, with no setting changed.

The input report is 8 bytes, sent every millisecond the host is ready for one:

| offset | size | field |
|---|---|---|
| 0 | 2 | buttons, little-endian |
| 2 | 1 | hat: 0 up, then clockwise to 7 up-left; 8 centre |
| 3 | 4 | LX, LY, RX, RY; 128 centre, 0 left or up |
| 7 | 1 | vendor byte; the firmware puts its Bluetooth state there |

| bit | button | bit | button |
|---|---|---|---|
| 0x0001 | Y | 0x0100 | Minus |
| 0x0002 | B | 0x0200 | Plus |
| 0x0004 | A | 0x0400 | left stick click |
| 0x0008 | X | 0x0800 | right stick click |
| 0x0010 | L | 0x1000 | HOME |
| 0x0020 | R | 0x2000 | Capture |
| 0x0040 | ZL | | |
| 0x0080 | ZR | | |

Vendor byte: 1 synced, 2 advertising, 3 connected; `0x80 | step` when that step failed.

## Cabling

A USB-C to USB-C cable from the board to the console. The console is the power source and the USB
host; the board draws its power from it. The XIAO ESP32S3's LED (GPIO21) lights while the host has
configured the device.

A Switch Lite connected to a Mac over a C-to-C cable is the power source and enumerates nothing.
Through a USB-A port at the Mac, with "Copy to a Computer via USB Connection" open, it enumerates as
`057e:201d`, one MTP interface, a read-only "Album" storage and ten read-only operations
(`0x1001`-`0x100a`).

## The Bluetooth side

The board advertises as `POKELDN-PAD` with one service, `7a1e0001-5d2c-4c3e-9f4b-504f4b454c44`:

| characteristic | access | content |
|---|---|---|
| `...0002` | write, write without response | the 8-byte input report, sent as is; ignored while a macro plays |
| `...0003` | read | status, below |
| `...0004` | write | a command, below |

Status, little-endian: mounted u8, report writes u32, playing u8, loops done u32, entry index u16,
entry count u16, the firmware version as text, then NUL, the reset reason u8 (`esp_reset_reason`),
the stage the previous boot reached u8 and boots since power-on u16. Firmware before 1.0.0 sends the
first five bytes only.

| command | body | effect |
|---|---|---|
| `0x10` load | count u16, loop start u16, loops u32 | stops a macro and sizes the program; loops 0 plays until stopped |
| `0x11` data | first entry u16, then entries | each entry is a report and a hold u16 in ms, 10 bytes |
| `0x12` play | | starts the program |
| `0x13` stop | | stops it and releases every button |
| `0xB0` download | | restarts the chip into the ROM loader |

The program holds 8192 entries. Entries before the loop start play once; the rest repeat. The player
waits with `vTaskDelayUntil` on the 1 kHz tick, so holds add up without drift: on the Mac's USB side
a 10-loop macro played every loop in exactly its 500 ms.

Through bleak on macOS a write without response is lost when CoreBluetooth's queue is full, and
bleak never reads `canSendWriteWithoutResponse`: 300 neutral reports sent back to back reached the
board's write counter 67 times; at 20 ms or wider spacing, 40 of 40. `pokeldn.pad.link` waits for
that flag before each report write, and writes with a response where the flag does not exist or
stays false for a second.

| report write | per report, back to back | reached the board |
|---|---|---|
| without response, unpaced | 0.1 ms | 67 of 300 |
| with response | 60 ms, flat over the first 25 s of a connection | 300 of 300 |
| without response, paced by the flag | 2.4 ms | 200 of 200 |

Firmware 1.2.0 asks for a 15 to 30 ms connection interval on connect; with responses the write
still took 63 ms, and whether macOS granted the request is unknown.

A disconnect returns the report to neutral, so a host that vanishes leaves no button held; a playing
macro keeps going.

## The serial side

The classic ESP32 stays on the computer's USB: UART0 at 921600 baud carries frames both ways
(`firmware/pad/main/uart_link.c`, `pokeldn/pad/serial_link.py`), and console output is off.

    A5 5A | length u16 (type and payload) | type u8 | payload | sum of type and payload mod 256

| type | direction | payload |
|---|---|---|
| `0x01` | to the board | the 8-byte report; answered by `0x81` |
| `0x02` | to the board | none; answered by `0x82` with the status record |
| `0x03` | to the board | a command, as on the control characteristic; answered by `0x81` |
| `0x81` | to the host | result i8: 0, -1 bad length, -2 refused |
| `0x82` | to the host | the status record; mounted means the Switch set the player lights |

The host opens the port with DTR and RTS low. The service tries each USB serial port that is not
an S3's native USB before it scans for Bluetooth LE.

## The Bluetooth Classic side

`firmware/pad/main/bt_esp32.c` registers a Bluedroid HID device: the 170-byte Pro Controller report
descriptor, service "Wireless Gamepad", provider "Nintendo", subclass 0x08, class of device
0x002508, name "Pro Controller", SSP with no input and no output, modem sleep off. It answers the
0x01 subcommands by ID: 0x02 device info (firmware 4.00, type 0x03, its Bluetooth address), 0x10 SPI
reads, 0x03 report mode, 0x04 trigger times, 0x21 MCU configuration, a plain ACK for the rest; 0x30
(player lights) marks the controller as taken. It streams 0x30 every 15 ms once the Switch asks for
full reports, 100 ms before, and holds the stream while a reply waits.

`pro_report.c` maps the shared report onto the Pro Controller's bytes (dekuNukem
`bluetooth_hid_notes.md`): sticks 0x800 at rest, 0x700 either way, matching the factory calibration
it returns at 0x603D; blank flash (0xFF) for the serial number and user calibration.
`tests/test_pad_pro.py` compiles it on the host and checks every button bit and the calibration.

## Macros

A macro is a JSON file with the extension `.pokemacro` (`pokeldn.pad.macro`):

```json
{
  "format": "pokeldn-macro", "version": 1,
  "name": "Soft reset", "description": "", "author": "", "game": "",
  "press_ms": 100, "gap_ms": 150,
  "setup": [{"press": "HOME"}, {"wait": 1000}],
  "loop": [
    {"press": ["A", "B"], "ms": 500, "after": 2000, "note": "skip the intro"},
    {"repeat": 3, "steps": [{"press": "A"}]},
    {"press": [], "left": [0, 1], "ms": 300},
    {"wait": 5000}
  ],
  "loops": 0
}
```

| field | meaning |
|---|---|
| `press_ms`, `gap_ms` | how long a step holds its input, and the pause after it, when the step does not say |
| `setup` | steps run once |
| `loop` | steps repeated `loops` times; 0 repeats until stopped |
| a press step | `press`: a button name or a list held together (`A B X Y L R ZL ZR PLUS MINUS LSTICK RSTICK HOME CAPTURE UP DOWN LEFT RIGHT UPLEFT UPRIGHT DOWNLEFT DOWNRIGHT`); `left` and `right`: stick `[x, y]` from -1 to 1, up positive; `ms` hold; `after` pause; `note` |
| a wait step | `wait`: ms with every button released |
| a repeat step | `repeat`: 1 to 10000 times over `steps`, nested up to 8 deep |

The compiler expands repeats, joins neighbouring entries that hold the same report and splits holds
over 65535 ms. A macro that expands past 8192 entries is refused. `after: 0` between two equal presses
holds them as one. A file whose `version` is newer than the reader's is refused.

## The host side

`pokeldn.pad.service` holds the Bluetooth link and takes one JSON request per line on
`127.0.0.1:47800`: `status`, `connect`, `send`, `tap`, `play`, `stop`, `download`, `scan`,
`disconnect`. The app starts it as its own child; `tools/switch/pad.py` starts it in its own process
when none is running.

    ./.venv/bin/python tools/switch/pad.py A
    ./.venv/bin/python tools/switch/pad.py HOME wait:1 'RIGHT*3' A
    ./.venv/bin/python tools/switch/pad.py hold:B:2 stick:L:-1:0:0.5
    ./.venv/bin/python tools/switch/pad.py --play soft_reset.pokemacro
    ./.venv/bin/python tools/switch/pad.py --stop --status

macOS aborts a process that opens Bluetooth when its responsible app declares no
`NSBluetoothAlwaysUsageDescription`, which happens under a terminal embedded in another app.
`pad.py --make-app PATH` writes a small app that runs the service; `open` it once and allow
Bluetooth, and later `pad.py` calls and a source checkout's app use it.

## Flashing again

The pad owns the USB port, so esptool cannot reset it into the loader. The download command, the
Board page's installs and `pad.py --download` do it over Bluetooth; holding BOOT while
plugging the board in does it without firmware.

- `RTC_CNTL_USB_CONF` survives a reset. Left on USB-OTG, the loader came up as the OTG CDC device
  `303a:0009` and esptool reached it about half the time. The firmware stops NimBLE and TinyUSB,
  gives the PHY back to USB Serial/JTAG and sets `RTC_CNTL_FORCE_DOWNLOAD_BOOT` before the reset;
  the loader is then `303a:1001` every time.
- `esp_restart()` with Bluetooth and USB up once hung: enumerated, LED lit, no reports.
- On macOS the first open of the fresh loader port reads nothing, and esptool keeps the port locked
  for its process; `gui/board.py` waits 8 s before connecting without a reset when it flashes the
  controller firmware, and falls back to a reset for a board still running the radio.
- After a flash from a forced loader, a reset over USB stays in the loader; the watchdog reset boots
  the image (`--after watchdog-reset`).

Both directions, radio to controller and controller to radio, flashed through
`python -m gui.board --kind pad|radio`. `--from-loader` flashes a board the download command already
put in the loader: it waits, connects without a reset and boots the image with the watchdog, as for
the controller firmware.

Trap: the USB loop's delay is zero ticks at FreeRTOS's default 100 Hz and starves NimBLE; the
firmware builds at 1000 Hz.

## Build

    . scratchpad/esp/env.sh
    cd firmware/pad && idf.py -B BUILD_DIR -D SDKCONFIG=SDKCONFIG_PATH build

TinyUSB comes from the component manager (`espressif/esp_tinyusb` 2.4.0). The release builds
`pokeldn-pad-s3.bin` beside the radio images.

## Unresolved

- Whether a retail Switch pairs with the classic ESP32 firmware; it is built and tested offline
  only. The sources and their reported pitfalls are in nxbt, joycontrol and friendmaker.

- Whether a Switch 2 takes the HORI ID the same way; only a Switch Lite was measured.

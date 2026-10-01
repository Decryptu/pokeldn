import os
import struct
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports

from pokeldn.app.paths import ROOT
from pokeldn.ldn import esp32

# USB-to-serial bridges found on ESP32 boards, by USB vendor and product id.
BRIDGES = {
    (0x10C4, 0xEA60): "Silicon Labs CP210x",
    (0x1A86, 0x7523): "WCH CH340",
    (0x1A86, 0x55D3): "WCH CH343",
    (0x1A86, 0x55D4): "WCH CH9102",
    (0x0403, 0x6001): "FTDI FT232R",
    (0x0403, 0x6010): "FTDI FT2232",
    (0x0403, 0x6015): "FTDI FT231X",
    (0x303A, 0x1001): "Espressif USB (S3, C3, C6)",
}
NATIVE_USB = (0x303A, 0x1001)

DRIVERS = {
    "Silicon Labs CP210x": "https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers",
    "WCH CH340": "https://www.wch-ic.com/downloads/CH341SER_EXE.html",
}

FIRMWARE = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio.bin")   # written by the release build
FIRMWARE_S3 = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio-s3.bin")
FIRMWARE_C3 = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio-c3.bin")


def bundled_firmware(chip: str) -> str:
    """Select by the chip esptool detected; native USB IDs are shared by S3, C3 and C6."""
    return {"ESP32": FIRMWARE, "ESP32-S3": FIRMWARE_S3, "ESP32-C3": FIRMWARE_C3}[chip]


@dataclass(frozen=True)
class Port:
    device: str
    bridge: str
    serial_number: str
    native: bool = False   # the chip's own USB, not a USB-to-serial bridge


def wrong_port(port: Port, chip: str) -> bool:
    """S3 and C3 firmware talks over native USB only; flashing through a UART bridge still works."""
    return chip in ("ESP32-S3", "ESP32-C3") and not port.native


@dataclass(frozen=True)
class Identity:
    sta_mac: str
    ap_mac: str
    chip_revision: int
    firmware: str
    protocol: int
    firmware_version: str = ""

    @property
    def current(self) -> bool:
        return self.protocol == esp32.PROTOCOL_VERSION


def ports() -> list[Port]:
    found = []
    for info in list_ports.comports():
        if info.vid is None:
            continue
        # macOS lists each USB serial device twice; /dev/cu.* is the one to open.
        if info.device.startswith("/dev/tty.") and os.path.exists(info.device.replace("/tty.", "/cu.")):
            continue
        bridge = BRIDGES.get((info.vid, info.pid), f"USB serial {info.vid:04x}:{info.pid:04x}")
        found.append(Port(info.device, bridge, info.serial_number or "", (info.vid, info.pid) == NATIVE_USB))
    return sorted(found, key=lambda p: p.device)


def identify(port: str, blink: bool = True) -> Identity:
    """HELLO, then blink GPIO2 on classic boards to identify them (docs/hardware_esp32.md).
    Raises esp32.RadioError when no pokeldn firmware answers. Opening the port can reset it."""
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 115200, 0.02
    s.dtr = s.rts = False   # most boards reset on a DTR/RTS edge
    s.open()
    radio = esp32.Radio(s)
    try:
        # Radio.hello() refuses another protocol version; parse it here to report it instead.
        for attempt in range(5):   # a HELLO sent while the board boots is lost
            try:
                info = esp32.Info.parse(radio.request(esp32.CMD_HELLO, b"", esp32.MSG_INFO, timeout=1.0))
                break
            except esp32.RadioError:
                if attempt == 4:
                    raise
        if blink and info.version == esp32.PROTOCOL_VERSION:
            time.sleep(1.0)   # the boot pulse
            radio.led("blink", 255, 300, 5000)
        return Identity(bytes(info.sta_mac).hex(":"), bytes(info.ap_mac).hex(":"), info.chip_revision,
                        info.text, info.version, info.firmware_version)
    finally:
        radio.close()


def flash(port: str, firmware: str = "") -> None:
    """Detect, validate and flash on one connection (docs/hardware_esp32.md, Building and flashing)."""
    import esptool
    from esptool.bin_image import LoadFirmwareImage

    with esptool.detect_chip(port) as chip:
        if chip.CHIP_NAME not in ("ESP32", "ESP32-S3", "ESP32-C3"):
            raise esptool.FatalError(f"{chip.CHIP_NAME} is not supported. Use an ESP32, ESP32-S3 or ESP32-C3.")
        path = firmware or bundled_firmware(chip.CHIP_NAME)
        if not os.path.isfile(path):
            raise esptool.FatalError(f"Missing firmware for {chip.CHIP_NAME}: {path}")
        # esptool skips its image check on a merged ESP32 image's 0x1000 padding.
        # Validate the bootloader at the detected chip's offset before any erase or write.
        # docs/hardware_esp32.md, Building and flashing.
        with open(path, "rb") as source:
            source.seek(chip.BOOTLOADER_FLASH_OFFSET)
            data = source.read()
        if len(data) < 24 or data[0] != 0xE9 or int.from_bytes(data[12:14], "little") != chip.IMAGE_CHIP_ID:
            raise esptool.FatalError(f"Merged firmware does not match {chip.CHIP_NAME}: {path}")
        try:
            image = LoadFirmwareImage(chip.CHIP_NAME, data)
        except (struct.error, RuntimeError, TypeError) as error:
            raise esptool.FatalError(f"Invalid merged firmware: {path}") from error
        image.verify()
        if image.checksum != image.calculate_checksum() or (
                image.append_digest and image.stored_digest != image.calc_digest):
            raise esptool.FatalError(f"Firmware checksum does not match: {path}")
        print(f"[app] Firmware for {chip.CHIP_NAME}: {path}", flush=True)
        esptool.main(["--baud", "460800", "--after", "hard-reset", "write-flash",
                      "0x0", os.path.abspath(path)], esp=chip)


def main() -> int:
    import argparse
    import esptool

    parser = argparse.ArgumentParser(description="Flash pokeldn firmware for the connected chip.")
    parser.add_argument("--port", required=True)
    parser.add_argument("--firmware", default="", help="custom merged image; default: bundled firmware")
    args = parser.parse_args()
    try:
        flash(args.port, args.firmware)
    except (esptool.FatalError, OSError, ValueError) as error:
        print(f"[app] {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

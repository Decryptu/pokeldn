import os
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

DRIVERS = {
    "Silicon Labs CP210x": "https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers",
    "WCH CH340": "https://www.wch-ic.com/downloads/CH341SER_EXE.html",
}

FIRMWARE = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio.bin")   # written by the release build
FIRMWARE_S3 = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio-s3.bin")   # ditto, this fork only


def bundled_firmware(p: "Port | None") -> str:
    """The release build's own image for this port's chip family, if the release included one."""
    path = FIRMWARE_S3 if p and p.bridge.startswith("Espressif") else FIRMWARE
    return path if os.path.exists(path) else ""


@dataclass(frozen=True)
class Port:
    device: str
    bridge: str
    serial_number: str

    @property
    def supported(self) -> bool:
        # Upstream pokeldn only ships classic-ESP32 firmware, so it rejects the native-USB
        # Espressif bridge (S3/C3/C6) outright. This fork has an ESP32-S3 build (USB Serial/JTAG
        # transport added in firmware/esp32/main/wire.c), so let it through here; esptool's own
        # chip-vs-image check at flash time is what actually catches a C3/C6 board with no
        # compatible firmware, not this property.
        return True


@dataclass(frozen=True)
class Identity:
    sta_mac: str
    ap_mac: str
    chip_revision: int
    firmware: str
    protocol: int

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
        found.append(Port(info.device, bridge, info.serial_number or ""))
    return sorted(found, key=lambda p: p.device)


def identify(port: str, blink: bool = True) -> Identity:
    """HELLO, then five seconds of fast blinking so the user can see which board answered.
    Raises esp32.RadioError when no pokeldn firmware answers. Opening the port resets the board."""
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
                        info.text, info.version)
    finally:
        radio.close()


def flash_args(port: str, firmware: str) -> list[str]:
    """esptool's arguments for a merged image (bootloader, partition table, app) written at 0.
    --chip auto lets esptool detect the connected chip itself (classic ESP32 or ESP32-S3) rather
    than forcing esp32 and refusing an S3 outright; it still refuses if the image's own chip-id
    header doesn't match what's connected, so a C3/C6 board with no compatible image is still safe."""
    return ["--chip", "auto", "-p", port, "-b", "460800", "--before", "default-reset",
            "--after", "hard-reset", "write-flash", "0x0", os.path.abspath(firmware)]

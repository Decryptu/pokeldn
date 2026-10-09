import asyncio
import os
import re
import struct
import subprocess
import sys
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
# An S3 running the controller firmware is a HID controller with no serial port (firmware/pad/main/usb_s3.c).
PAD_USB = (0x0F0D, 0x0092)

DRIVERS = {
    "Silicon Labs CP210x": "https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers",
    "WCH CH340": "https://www.wch-ic.com/downloads/CH341SER_EXE.html",
}
DRIVER_STEPS = {   # Windows, docs/gui.md USB drivers
    "Silicon Labs CP210x": "Download the CP210x Universal Windows Driver zip, extract it, right-click "
                           "silabser.inf and choose Install, then unplug and replug the board.",
    "WCH CH340": "Download CH341SER.EXE, run it and press Install, then unplug and replug the board.",
}

FIRMWARE = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio.bin")   # written by the release build
FIRMWARE_S3 = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio-s3.bin")
FIRMWARE_C3 = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio-c3.bin")
FIRMWARE_C6 = os.path.join(ROOT, "gui", "firmware", "pokeldn-radio-c6.bin")
# The controller firmware (firmware/pad), docs/hardware_pad.md: an S3 over USB, a classic ESP32 over
# Bluetooth Classic. C3 and C6 cannot be a Switch controller.
FIRMWARE_PAD = os.path.join(ROOT, "gui", "firmware", "pokeldn-pad-s3.bin")
FIRMWARE_PAD_ESP32 = os.path.join(ROOT, "gui", "firmware", "pokeldn-pad.bin")




@dataclass(frozen=True)
class Firmware:
    """One firmware a board can run; the Board page lists them in this order."""
    kind: str
    name: str
    summary: str
    icon: str
    chips: tuple[str, ...]
    role: str     # what the board is while it runs this, after "the board stops working as"


FIRMWARES = (
    Firmware("radio", "Wireless", "The board is the radio for trades, Mystery Gift and every tool on the Games "
             "page.", "globe", ("ESP32", "ESP32-S3", "ESP32-C3", "ESP32-C6"), "the radio for trades"),
    Firmware("pad", "Controller", "The board is a controller for the Switch: this computer presses its buttons "
             "and plays macros from the Control page.", "joystick", ("ESP32-S3", "ESP32"),
             "a controller for the Switch"),
)
FIRMWARE_BY_KIND = {f.kind: f for f in FIRMWARES}
CHIP_NAMES = {"esp32": "ESP32", "esp32s3": "ESP32-S3", "esp32c3": "ESP32-C3", "esp32c6": "ESP32-C6"}


def image_for(kind: str, chip: str) -> str:
    if kind == "pad":
        return FIRMWARE_PAD if chip == "ESP32-S3" else FIRMWARE_PAD_ESP32
    return bundled_firmware(chip)


APP_DESC_MAGIC = 0xABCD5432   # esp_app_desc_t: magic, secure version, two reserved words, version[32]


def image_info(path: str) -> tuple[str, str]:
    """The project name and version an ESP-IDF image carries in its app descriptor, ("", "") if none."""
    try:
        with open(path, "rb") as f:
            data = f.read(IMAGE_BYTES)
    except OSError:
        return "", ""
    at = data.find(struct.pack("<I", APP_DESC_MAGIC))
    if at < 0:
        return "", ""
    version, project = data[at + 16:at + 48], data[at + 48:at + 80]
    return (project.split(b"\0")[0].decode(errors="replace"), version.split(b"\0")[0].decode(errors="replace"))


def image_version(path: str) -> str:
    return image_info(path)[1]


PROJECTS = {"pokeldn_radio": "radio", "pokeldn_pad": "pad"}   # firmware/*/CMakeLists.txt project()


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) if n.isdigit() else 0 for n in re.split(r"[.\-]", version)) if version else ()


def update_for(installed: str, kind: str, chip: str) -> str:
    """The included version when it is newer than the installed one, else ""."""
    if kind not in FIRMWARE_BY_KIND or chip not in FIRMWARE_BY_KIND[kind].chips:
        return ""
    included = image_version(image_for(kind, chip))
    return included if installed and version_key(included) > version_key(installed) else ""


RELEASES = os.environ.get("POKELDN_RELEASES_URL", "https://api.github.com/repos/Decryptu/pokeldn/releases")
IMAGE_BYTES = 4 * 1024 * 1024   # a merged image fills at most the 4 MB flash


def bundled_firmware(chip: str) -> str:
    """Select by the chip esptool detected; native USB IDs are shared by S3, C3 and C6."""
    return {"ESP32": FIRMWARE, "ESP32-S3": FIRMWARE_S3, "ESP32-C3": FIRMWARE_C3, "ESP32-C6": FIRMWARE_C6}[chip]


@dataclass(frozen=True)
class Port:
    device: str
    bridge: str
    serial_number: str
    native: bool = False   # the chip's own USB, not a USB-to-serial bridge


def wrong_port(port: Port, chip: str) -> bool:
    """S3, C3 and C6 firmware talks over native USB only; flashing through a UART bridge still works."""
    return chip in ("ESP32-S3", "ESP32-C3", "ESP32-C6") and not port.native


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

    @property
    def chip(self) -> str:
        """From the HELLO text, `pokeldn-radio esp32c3 version=1.0.0 idf=v6.1`."""
        words = self.firmware.split()
        return CHIP_NAMES.get(words[1], "") if len(words) > 1 else ""


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


def bridges_without_port(sysfs: str = "/sys/bus/usb/devices") -> list[str]:
    """Linux: the known bridges on USB that no driver gave a tty. Ubuntu 22.04's brltty claims every
    CH340 and its node never appears (docs/gui.md, Linux serial ports)."""
    import glob
    found = []
    for device in sorted(glob.glob(os.path.join(sysfs, "*"))):
        try:
            with open(os.path.join(device, "idVendor")) as v, open(os.path.join(device, "idProduct")) as p:
                ids = (int(v.read(), 16), int(p.read(), 16))
        except (OSError, ValueError):
            continue
        if ids in BRIDGES and not glob.glob(os.path.join(device, "*:*", "tty*")):
            found.append(BRIDGES[ids])
    return found


# Present devices with a Device Manager problem; a bridge with no driver has code 28 and no COM port.
PROBLEM_DEVICES = ("Get-CimInstance Win32_PnPEntity -Filter 'ConfigManagerErrorCode <> 0' "
                   "| ForEach-Object { $_.PNPDeviceID }")
USB_ID = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.I)


def bridges_without_driver(run=subprocess.run) -> list[str]:
    """Windows: the known bridges plugged in with no working driver, so with no COM port."""
    try:
        out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PROBLEM_DEVICES],
                  capture_output=True, text=True, timeout=20,
                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for vid, pid in USB_ID.findall(out or ""):
        name = BRIDGES.get((int(vid, 16), int(pid, 16)))
        if name and name not in found:
            found.append(name)
    return found


def controllers(platform: str = "", run=subprocess.run,
                sysfs: str = "/sys/bus/usb/devices") -> int:
    """How many S3 controller boards are on this computer's USB. They have no serial port, so ports()
    never lists them. A retail HORI Pokken controller carries the same ids."""
    platform = platform or sys.platform
    try:
        if platform == "darwin":
            out = run(["ioreg", "-p", "IOUSB", "-l", "-w0"], capture_output=True, text=True, timeout=10).stdout
            return sum(1 for block in (out or "").split("+-o ")
                       if re.search(rf'"idVendor" = {PAD_USB[0]}\b', block)
                       and re.search(rf'"idProduct" = {PAD_USB[1]}\b', block))
        if platform == "win32":
            out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                       "Get-CimInstance Win32_PnPEntity -Filter \"PNPDeviceID LIKE 'USB%'\" "
                       "| ForEach-Object { $_.PNPDeviceID }"],
                      capture_output=True, text=True, timeout=20,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return sum(1 for line in (out or "").splitlines()
                       if (m := USB_ID.search(line)) and "&MI_" not in line.upper()
                       and (int(m[1], 16), int(m[2], 16)) == PAD_USB)
    except (OSError, subprocess.SubprocessError):
        return 0
    import glob
    found = 0
    for device in glob.glob(os.path.join(sysfs, "*")):
        try:
            with open(os.path.join(device, "idVendor")) as v, open(os.path.join(device, "idProduct")) as p:
                found += (int(v.read(), 16), int(p.read(), 16)) == PAD_USB
        except (OSError, ValueError):
            continue
    return found


@dataclass(frozen=True)
class PadIdentity:
    """A classic ESP32 answering with the controller firmware on its serial port."""
    version: str


def identify_pad(port: str, seconds: float = 3.0) -> PadIdentity:
    """The controller firmware's status frame [pokeldn.pad.serial_link]. Opening the port for the radio
    check may have reset the board, so this asks until it has booted."""
    from pokeldn.pad.serial_link import SerialPad, SerialError
    pad = SerialPad(port)
    try:
        end = time.monotonic() + seconds
        while True:
            try:
                return PadIdentity(asyncio.run(pad.status()).version)
            except SerialError:
                if time.monotonic() > end:
                    raise
    finally:
        pad.serial.close()


def identify(port: str, blink: bool = True) -> Identity:
    """HELLO, then blink GPIO2 on classic boards to identify them (docs/hardware_esp32.md).
    Raises esp32.RadioError when no pokeldn firmware answers. Opening the port can reset it."""
    # Another protocol version is reported, not refused.
    radio = esp32.Radio.open_serial(port, fast_baud=0, check_protocol=False)
    info = radio.info
    try:
        if blink and info.version == esp32.PROTOCOL_VERSION:
            time.sleep(1.0)   # the boot pulse
            radio.led("blink", 255, 300, 5000)
        return Identity(bytes(info.sta_mac).hex(":"), bytes(info.ap_mac).hex(":"), info.chip_revision,
                        info.text, info.version, info.firmware_version)
    finally:
        radio.close()


def detect_chip(port: str) -> str:
    """The chip's name from its ROM bootloader, then a reset back into the firmware. Works with no
    firmware and through an S3's UART socket, where the radio firmware never answers."""
    import esptool

    with esptool.detect_chip(port, connect_attempts=2) as chip:
        name = chip.CHIP_NAME
        chip.hard_reset()
    return name


def _get(url: str, limit: int) -> bytes:
    import urllib.request
    from pokeldn.app.sprites import _context
    request = urllib.request.Request(url, headers={"User-Agent": "pokeldn-desktop"})
    with urllib.request.urlopen(request, timeout=30, context=_context()) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise OSError(f"{url} is larger than {limit} bytes")
    return data


def download_firmware(say=print, folder: str = os.path.dirname(FIRMWARE)) -> str:
    """A source checkout has no firmware image: fetch every image the newest published release carries
    (a release predating a chip lacks its image), check each against its SHA256SUMS, and write them
    only when all match. Returns the release tag."""
    import hashlib
    import json

    releases = json.loads(_get(RELEASES, 1_000_000))
    known = [os.path.basename(f) for f in (FIRMWARE, FIRMWARE_S3, FIRMWARE_C3, FIRMWARE_C6, FIRMWARE_PAD,
                                           FIRMWARE_PAD_ESP32)]
    for release in releases:
        files = {a.get("name"): a.get("browser_download_url") for a in release.get("assets") or []}
        if release.get("draft") or not all(n in files for n in (known[0], "SHA256SUMS")):
            continue
        names = [n for n in known if n in files]
        sums = {name.lstrip("*"): digest.lower() for digest, name in
                (line.split() for line in _get(files["SHA256SUMS"], 100_000).decode().splitlines()
                 if len(line.split()) == 2)}
        images = {}
        for name in names:
            say(f"[app] Downloading {name} from {release.get('tag_name')}.")
            images[name] = _get(files[name], IMAGE_BYTES)
            if hashlib.sha256(images[name]).hexdigest() != sums.get(name):
                raise OSError(f"{name} does not match the release's SHA256SUMS; nothing was written")
        os.makedirs(folder, exist_ok=True)
        for name, data in images.items():
            path = os.path.join(folder, name)
            with open(path + ".part", "wb") as out:
                out.write(data)
            os.replace(path + ".part", path)
        return str(release.get("tag_name"))
    raise OSError("No published release carries the firmware images")


LOADER_SETTLE = 8.0   # seconds; see _connect


def _native(port: str) -> bool:
    return any(p.device == port and p.native for p in ports())


def _connect(port: str, kind: str, from_loader: bool = False):
    """A controller board reaches the flasher already in the ROM loader (the Board page's Make it wireless again, or BOOT); a reset
    on connect would leave it. On macOS a USB Serial/JTAG port younger than about 8 s fails its first
    read and stays locked for the process; the node's times do not say its age, so every such flash waits
    (docs/hardware_pad.md)."""
    import esptool
    if (kind == "pad" or from_loader) and _native(port):
        print(f"[app] Waiting {LOADER_SETTLE:.0f} s for the board's port to settle.", flush=True)
        time.sleep(LOADER_SETTLE)
        try:
            return esptool.detect_chip(port, connect_mode="no-reset", connect_attempts=1)
        except (esptool.FatalError, serial.SerialException, OSError):
            time.sleep(1)    # a board still running other firmware: reset it into the loader
    return esptool.detect_chip(port)


def flash(port: str, firmware: str = "", kind: str = "radio", from_loader: bool = False) -> None:
    """Detect, validate and flash on one connection (docs/hardware_esp32.md, Building and flashing).
    `kind` "pad" writes the controller firmware, which needs an S3's USB device. `from_loader`: the
    controller firmware just restarted the board into the ROM loader (its download command)."""
    import esptool
    from esptool.bin_image import LoadFirmwareImage

    with _connect(port, kind, from_loader) as chip:
        if chip.CHIP_NAME not in ("ESP32", "ESP32-S3", "ESP32-C3", "ESP32-C6"):
            raise esptool.FatalError(f"{chip.CHIP_NAME} is not supported. Use an ESP32, ESP32-S3, ESP32-C3 or ESP32-C6.")
        if kind == "pad" and chip.CHIP_NAME not in ("ESP32-S3", "ESP32"):
            raise esptool.FatalError(f"The controller firmware needs an ESP32-S3 (its USB acts as a controller) or a "
                                     f"classic ESP32 (Bluetooth Classic); an {chip.CHIP_NAME} can be neither.")
        pad_image = FIRMWARE_PAD if chip.CHIP_NAME == "ESP32-S3" else FIRMWARE_PAD_ESP32
        path = firmware or (pad_image if kind == "pad" else bundled_firmware(chip.CHIP_NAME))
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
        # The pad owns the USB port once it runs: a reset over USB from the ROM loader it was put
        # in by `pad.py --download` leaves the chip in the loader; the watchdog boots the image.
        after = "watchdog-reset" if (kind == "pad" or from_loader) and chip.CHIP_NAME == "ESP32-S3" else "hard-reset"
        esptool.main(["--baud", "460800", "--after", after, "write-flash",
                      "0x0", os.path.abspath(path)], esp=chip)


def main() -> int:
    import argparse
    import esptool

    parser = argparse.ArgumentParser(description="Flash pokeldn firmware for the connected chip.")
    parser.add_argument("--port", required=True)
    parser.add_argument("--firmware", default="", help="custom merged image; default: bundled firmware")
    parser.add_argument("--kind", choices=("radio", "pad"), default="radio",
                        help="radio: wireless trades; pad: the S3 as a Switch controller")
    parser.add_argument("--from-loader", action="store_true",
                        help="the controller firmware already restarted the board into its ROM loader")
    args = parser.parse_args()
    try:
        flash(args.port, args.firmware, args.kind, args.from_loader)
    except (esptool.FatalError, OSError, ValueError) as error:
        print(f"[app] {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

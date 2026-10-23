"""A plain-text report of this computer's USB serial ports and one board, for a player to send when a
board does not work (docs/gui.md, A board report). Every probe is caught: a report always comes back."""
import os
import platform
import sys
import time
import traceback

import serial
from serial.tools import list_ports

import pokeldn
from gui import board
from pokeldn.ldn import esp32

PORT_FIELDS = ("device", "name", "description", "manufacturer", "product", "vid", "pid", "serial_number",
               "location", "interface", "hwid")
BOOT_READ_S = 2.0


def _failure(error: BaseException) -> str:
    detail = type(error).__name__ + ": " + str(error)
    for name in ("errno", "winerror"):
        if getattr(error, name, None) is not None:
            detail += f" ({name} {getattr(error, name)})"
    return detail


def _section(title: str, lines) -> list[str]:
    return ["", f"== {title}", *lines]


def system() -> list[str]:
    import esptool
    return [f"pokeldn {pokeldn.__version__}" + (" (packaged)" if getattr(sys, "frozen", False) else " (source)"),
            f"system {platform.platform()} {platform.machine()}",
            f"python {platform.python_version()}, pyserial {serial.__version__}, esptool {esptool.__version__}",
            f"POKELDN_RADIO={os.environ.get('POKELDN_RADIO', '')}"]


def serial_ports() -> list[str]:
    lines = []
    for info in sorted(list_ports.comports(), key=lambda i: i.device):
        fields = {name: getattr(info, name, None) for name in PORT_FIELDS}
        for name in ("vid", "pid"):
            if fields[name] is not None:
                fields[name] = f"{fields[name]:04x}"
        known = board.BRIDGES.get((info.vid, info.pid), "not a known ESP32 bridge") if info.vid is not None else "no USB ids"
        lines.append(f"{info.device}: {known}")
        lines += [f"    {name}: {value}" for name, value in fields.items() if value not in (None, "")]
    return lines or ["none"]


def missing_drivers() -> list[str]:
    lines = []
    try:
        if sys.platform == "win32":
            lines.append(f"bridges with no driver: {', '.join(board.bridges_without_driver()) or 'none'}")
        elif sys.platform.startswith("linux"):
            lines.append(f"bridges with no tty: {', '.join(board.bridges_without_port()) or 'none'}")
        lines.append(f"controller boards on USB (no serial port): {board.controllers()}")
    except Exception as error:
        lines.append(f"failed: {_failure(error)}")
    return lines


def boot_bytes(device: str) -> list[str]:
    """What the port carries in the first seconds after opening it, which resets most boards."""
    try:
        with serial.Serial(device, 115200, timeout=0.1) as port:
            data, end = b"", time.monotonic() + BOOT_READ_S
            while time.monotonic() < end and len(data) < 4096:
                data += port.read(512)
    except Exception as error:
        return [f"open failed: {_failure(error)}"]
    text = "".join(c if c.isprintable() or c in "\r\n" else "." for c in data.decode("latin-1"))
    return [f"opened at 115200, {len(data)} bytes in {BOOT_READ_S:.0f} s",
            *(f"    {line}" for line in text.splitlines()[:20] if line.strip()),
            f"    hex: {data[:128].hex(' ')}" if data else "    nothing"]


def firmware(device: str) -> list[str]:
    try:
        radio = esp32.Radio.open_serial(device, fast_baud=0, check_protocol=False)
    except Exception as error:
        return [f"no pokeldn firmware answered: {_failure(error)}"]
    try:
        info = radio.info
        lines = [f"HELLO: {info.text}", f"protocol {info.version}, station MAC {bytes(info.sta_mac).hex(':')}, "
                                        f"chip revision {info.chip_revision}"]
        try:
            lines.append(f"STATUS: {radio.status()}")
        except Exception as error:
            lines.append(f"STATUS failed: {_failure(error)}")
        return lines
    finally:
        radio.close()


def chip(device: str) -> list[str]:
    """The ROM bootloader's answer through esptool, which resets the board into it and back."""
    import esptool
    try:
        with esptool.detect_chip(device, connect_attempts=2) as found:
            lines = [f"chip {found.CHIP_NAME}"]
            for label, read in (("description", "get_chip_description"), ("features", "get_chip_features"),
                                ("crystal MHz", "get_crystal_freq"), ("MAC", "read_mac"),
                                ("USB-Serial/JTAG", "uses_usb_jtag_serial")):
                try:
                    value = getattr(found, read)()
                    lines.append(f"{label}: {':'.join(f'{b:02x}' for b in value) if read == 'read_mac' else value}")
                except Exception as error:
                    lines.append(f"{label}: {_failure(error)}")
            found.hard_reset()
            return lines
    except Exception as error:
        return [f"the bootloader did not answer: {_failure(error)}"]


def report(device: str = "", *, probe: bool = True, identity=None, activity: str = "") -> str:
    """The report; `probe` opens `device` (the board may restart), otherwise only what the system lists."""
    out = ["pokeldn board report, " + time.strftime("%Y-%m-%d %H:%M:%S %z")]
    for title, make in (("This computer", system), ("USB serial ports", serial_ports),
                        ("Drivers", missing_drivers)):
        try:
            out += _section(title, make())
        except Exception:
            out += _section(title, traceback.format_exc().splitlines())
    if device:
        out += _section(f"The board on {device}", [f"the app's check: {identity!r}"])
        if probe:
            out += _section("Opening the port", boot_bytes(device))
            out += _section("pokeldn firmware", firmware(device))
            out += _section("ESP32 bootloader", chip(device))
        else:
            out.append("the port was in use, so it was not opened")
    if activity:
        out += _section("Activity", activity.splitlines()[-80:])
    return "\n".join(out) + "\n"

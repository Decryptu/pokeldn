"""Chip detection and merged-image checks before the first flash write."""
from pathlib import Path
from queue import Empty, Queue
from types import SimpleNamespace

import esptool
import pytest

from gui import board
from pokeldn.ldn import esp32


# ESP-IDF image format: one four-byte RAM segment, checksum 0xeb, no SHA digest.
# Chip IDs and bootloader offsets: esptool's ESP32, ESP32-S3, ESP32-C3 and ESP32-C6 ROM definitions.
BOOTLOADERS = {
    "ESP32": bytes.fromhex(
        "e9 01 00 20 00000040 ff000000 0000 00 0000 ffff 00000000 00 "
        "0000fb3f 04000000 01020304 0000000000000000000000 eb"),
    "ESP32-S3": bytes.fromhex(
        "e9 01 00 20 00000040 ff000000 0900 00 0000 ffff 00000000 00 "
        "0000c93f 04000000 01020304 0000000000000000000000 eb"),
    "ESP32-C3": bytes.fromhex(
        "e9 01 00 20 00000040 ff000000 0500 00 0000 ffff 00000000 00 "
        "0000c83f 04000000 01020304 0000000000000000000000 eb"),
    "ESP32-C6": bytes.fromhex(
        "e9 01 00 20 00000040 ff000000 0d00 00 0000 ffff 00000000 00 "
        "00008040 04000000 01020304 0000000000000000000000 eb"),
}


@pytest.mark.parametrize("protocol,text,release,compatible", [
    (1, b"pokeldn-radio esp32c3 version=1.0.0 idf=v6.1", "1.0.0", True),
    (1, b"pokeldn-radio esp32 version=0.9.9 idf=v6.1", "0.9.9", True),
    (1, b"pokeldn-radio esp32s3 idf=v6.1", "", True),
    (2, b"pokeldn-radio esp32 version=2.0.0 idf=v6.1", "2.0.0", False),
])
def test_identify_preserves_release_and_protocol_across_serial(monkeypatch, protocol, text, release, compatible):
    class SerialReply:
        def __init__(self):
            self.inbox = Queue()
            self.closed = False

        def open(self):
            pass

        def write(self, frame):
            [(command, payload)] = esp32.FrameReader().feed(frame)
            assert command == 0x01 and payload == b""
            # INFO's fixed header: protocol, STA MAC, AP MAC, chip revision.
            header = bytes([protocol]) + bytes.fromhex("021122334455 0266778899aa 03")
            self.inbox.put(esp32.encode_frame(0x81, header + text))
            return len(frame)

        def read(self, n):
            try:
                return self.inbox.get(timeout=0.02)
            except Empty:
                return b""

        def close(self):
            self.closed = True

    serial = SerialReply()
    monkeypatch.setattr(board.serial, "Serial", lambda: serial)
    ident = board.identify("COM4", blink=False)
    assert ident.sta_mac == "02:11:22:33:44:55"
    assert ident.ap_mac == "02:66:77:88:99:aa"
    assert ident.chip_revision == 3
    assert ident.firmware == text.decode()
    assert ident.firmware_version == release
    assert ident.protocol == protocol and ident.current is compatible
    assert serial.closed


class Chip:
    def __init__(self, name):
        self.CHIP_NAME = name
        self.BOOTLOADER_FLASH_OFFSET = 0x1000 if name == "ESP32" else 0
        self.IMAGE_CHIP_ID = {"ESP32": 0, "ESP32-S3": 9, "ESP32-C3": 5, "ESP32-C6": 13}.get(name, -1)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


@pytest.fixture
def flasher(monkeypatch, tmp_path):
    images = {}
    for name, header in BOOTLOADERS.items():
        path = tmp_path / f"{name}.bin"
        path.write_bytes((b"\xff" * 0x1000 if name == "ESP32" else b"") + header)
        images[name] = path
    monkeypatch.setattr(board, "FIRMWARE", str(images["ESP32"]))
    monkeypatch.setattr(board, "FIRMWARE_S3", str(images["ESP32-S3"]))
    monkeypatch.setattr(board, "FIRMWARE_C3", str(images["ESP32-C3"]))
    monkeypatch.setattr(board, "FIRMWARE_C6", str(images["ESP32-C6"]))
    writes, connections = [], []

    def detect(port):
        connections.append(port)
        return state.chip

    def write(args, esp):
        writes.append((esp.CHIP_NAME, Path(args[-1]).read_bytes()))

    state = SimpleNamespace(chip=None, images=images, writes=writes, connections=connections)
    monkeypatch.setattr(esptool, "detect_chip", detect)
    monkeypatch.setattr(esptool, "main", write)
    return state


@pytest.mark.parametrize("name", BOOTLOADERS)
def test_flash_uses_the_detected_chip_on_one_connection(flasher, name):
    flasher.chip = Chip(name)
    board.flash("COM4")
    assert flasher.connections == ["COM4"]
    assert flasher.writes == [(name, flasher.images[name].read_bytes())]
    assert flasher.chip.closed


@pytest.mark.parametrize("name", ["ESP32-S2", "ESP32-H2"])
def test_unsupported_chip_is_refused_before_writing(flasher, name):
    flasher.chip = Chip(name)
    with pytest.raises(esptool.FatalError, match="not supported"):
        board.flash("COM4")
    assert not flasher.writes and flasher.chip.closed


@pytest.mark.parametrize("name,other", [(name, other) for name in BOOTLOADERS
                                       for other in BOOTLOADERS if name != other])
def test_wrong_custom_image_is_refused_before_writing(flasher, name, other):
    flasher.chip = Chip(name)
    with pytest.raises(esptool.FatalError, match="does not match"):
        board.flash("COM4", str(flasher.images[other]))
    assert not flasher.writes and flasher.chip.closed


@pytest.mark.parametrize("name", BOOTLOADERS)
def test_missing_image_does_not_fall_back_to_another_chip(flasher, name):
    flasher.chip = Chip(name)
    flasher.images[name].unlink()
    with pytest.raises(esptool.FatalError, match=f"Missing firmware for {name}"):
        board.flash("COM4")
    assert not flasher.writes and flasher.chip.closed


@pytest.mark.parametrize("damage", ["truncate", "checksum"])
@pytest.mark.parametrize("name", BOOTLOADERS)
def test_damaged_bootloader_is_refused_before_writing(flasher, damage, name):
    flasher.chip = Chip(name)
    path = flasher.images[name]
    data = path.read_bytes()
    path.write_bytes(data[:10] if damage == "truncate" else data[:-1] + b"\x00")
    with pytest.raises(esptool.FatalError):
        board.flash("COM4")
    assert not flasher.writes and flasher.chip.closed


# ioreg -p IOUSB -l -w0 on macOS with an S3 running firmware/pad plugged in, trimmed to the ids.
IOREG = """+-o Root  <class IORegistryEntry, id 0x100000100, retain 32>
  +-o AppleT8132USBXHCI@00000000  <class AppleT8132USBXHCI, id 0x10000037f, registered, matched, active>
  | +-o POKKEN CONTROLLER@00100000  <class IOUSBHostDevice, id 0x1000265a7, registered, matched, active>
  |     {
  |       "idProduct" = 146
  |       "USB Product Name" = "POKKEN CONTROLLER"
  |       "USB Vendor Name" = "HORI CO.,LTD."
  |       "idVendor" = 3853
  |     }
  | +-o USB2.0 Hub@00200000  <class IOUSBHostDevice, id 0x100026600, registered, matched, active>
  |     {
  |       "idProduct" = 146
  |       "idVendor" = 1507
  |     }
  +-o AppleT8132USBXHCI@01000000  <class AppleT8132USBXHCI, id 0x100000383, registered, matched, active>
"""


def test_a_controller_board_is_found_on_usb_where_it_has_no_serial_port(tmp_path):
    """Each platform's listing, with a device that shares only the product id."""
    def run(out):
        return lambda *a, **k: SimpleNamespace(stdout=out)
    assert board.controllers("darwin", run(IOREG)) == 1
    windows = "USB\\VID_0F0D&PID_0092\\5&1A2B&0&3\r\nUSB\\VID_05E3&PID_0092\\6&1\r\nUSB\\ROOT_HUB30\\4&2\r\n"
    assert board.controllers("win32", run(windows)) == 1
    for name, ids in (("1-1", ("0f0d", "0092")), ("1-2", ("05e3", "0092")), ("usb1", ("1d6b", "0002"))):
        (tmp_path / name).mkdir()
        (tmp_path / name / "idVendor").write_text(ids[0] + "\n")
        (tmp_path / name / "idProduct").write_text(ids[1] + "\n")
    assert board.controllers("linux", sysfs=str(tmp_path)) == 1


def test_a_board_the_controller_firmware_put_in_the_loader_is_flashed_without_a_reset(flasher, monkeypatch):
    """A reset over USB keeps a forced loader in the loader; only the watchdog boots the radio image."""
    connects, afters = [], []

    def detect(port, **kwargs):
        connects.append(kwargs.get("connect_mode", "default-reset"))
        return Chip("ESP32-S3")

    monkeypatch.setattr(esptool, "detect_chip", detect)
    monkeypatch.setattr(esptool, "main", lambda args, esp: afters.append(args[args.index("--after") + 1]))
    monkeypatch.setattr(board, "_native", lambda port: True)
    monkeypatch.setattr(board.time, "sleep", lambda s: None)
    board.flash("/dev/cu.usbmodem1", kind="radio", from_loader=True)
    board.flash("/dev/cu.usbmodem1", kind="radio")
    assert connects == ["no-reset", "default-reset"]
    assert afters == ["watchdog-reset", "hard-reset"]


def _app_image(path, project: bytes, version: bytes):
    """A merged image's app descriptor, laid out as ESP-IDF's esp_app_desc_t: magic, secure version,
    two reserved words, version[32], project_name[32], at 0x10020."""
    import struct
    desc = struct.pack("<IIII", 0xABCD5432, 0, 0, 0) + version.ljust(32, b"\0") + project.ljust(32, b"\0")
    path.write_bytes(b"\xff" * 0x10020 + desc + b"\xff" * 64)
    return str(path)


@pytest.mark.parametrize("installed, included, offered", [
    ("1.1.0", "1.2.0", "1.2.0"),
    ("1.2.0", "1.2.0", ""),
    ("1.10.0", "1.9.0", ""),     # compared as numbers, never as text
    ("1.9.0", "1.10.0", "1.10.0"),
    ("", "1.2.0", ""),           # a version the board did not say is not out of date
])
def test_an_update_is_offered_only_for_a_newer_included_image(tmp_path, monkeypatch, installed, included, offered):
    image = _app_image(tmp_path / "pad.bin", b"pokeldn_pad", included.encode())
    monkeypatch.setattr(board, "FIRMWARE_PAD", image)
    assert board.image_info(image) == ("pokeldn_pad", included)
    assert board.update_for(installed, "pad", "ESP32-S3") == offered
    assert board.update_for(installed, "pad", "ESP32-C3") == ""    # the controller does not run on a C3

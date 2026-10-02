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
            command, payload = esp32.decode_frame(frame[:-1])
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

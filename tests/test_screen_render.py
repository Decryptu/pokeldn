"""pokeldn.app.screen_render against the firmware's own scene code (scene.c and screen.c built for
this machine): scripted sessions, byte-identical frames and power at every step."""
import ctypes
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pokeldn.app.screen_render import Scene, pixels
from pokeldn.ldn import esp32

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "firmware/esp32/main/scene.c", ROOT / "firmware/esp32/main/screen.c"]
VERSION = (ROOT / "firmware/esp32/version.txt").read_text(encoding="ascii").strip()

pytestmark = pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler")


class Radio(ctypes.Structure):
    _fields_ = [("mode", ctypes.c_uint8), ("stations", ctypes.c_uint8),
                ("rx", ctypes.c_uint32), ("tx", ctypes.c_uint32), ("presses", ctypes.c_uint32)]


@pytest.fixture
def firmware(tmp_path):
    """A fresh build per test: scene.c keeps its packets and wake clock in statics."""
    lib = tmp_path / ("libscene" + (".dylib" if sys.platform == "darwin" else ".so"))
    subprocess.run(["cc", "-O1", "-Wall", "-Werror", "-shared", "-fPIC",
                    f'-DPOKELDN_FIRMWARE_VERSION="{VERSION}"', "-o", str(lib), *map(str, SOURCES)],
                   check=True)
    lib = ctypes.CDLL(str(lib))
    lib.scene_command.restype = ctypes.c_bool
    lib.scene_draw.restype = ctypes.c_uint8
    return lib


def sprite(w, h, seed):
    rows = []
    for y in range(h):
        rows.append([((x * 7 + y * 13 + seed) % 5 < 2) or (x - w // 2) ** 2 + (y - h // 2) ** 2 < 40
                     for x in range(w)])
    return rows


def play(lib, script, *, panel=0, start=1000, step=50, until=30000):
    """script: {ms after start: [("cmd", payload, expect) | ("radio", field, value) | ("reset",)]}."""
    py = Scene(VERSION)
    lib.scene_panel(panel)
    py.panel(panel)
    radio = Radio()
    fb = ctypes.create_string_buffer(1024)
    frames = 0
    for at in range(0, until, step):
        now = start + at
        for event in script.get(at, ()):
            if event[0] == "cmd":
                c = lib.scene_command(event[1], len(event[1]), now)
                assert c == py.command(event[1], now) == event[2], (at, event)
            elif event[0] == "reset":
                lib.scene_reset()
                py.reset()
            else:
                setattr(radio, event[1], event[2])
        power = lib.scene_draw(fb, ctypes.byref(radio), now)
        frame, py_power = py.draw(radio.mode, radio.stations, radio.rx, radio.tx, radio.presses, now)
        assert (frame, py_power) == (fb.raw, power), f"frame at {at} ms differs"
        frames += 1
        radio.rx += (at // 700) % 3
        radio.tx += (at // 1100) % 2
    return frames


def radio_script():
    return {1500: [("radio", "mode", 3)], 4000: [("radio", "stations", 1)],
            9000: [("radio", "stations", 0)], 11000: [("radio", "mode", 1)],
            15000: [("radio", "mode", 2)], 20000: [("radio", "mode", 4)],
            25000: [("radio", "mode", 0)], 27000: [("radio", "presses", 1)]}


def trade_script():
    return {500: [("radio", "mode", 3)], 1000: [("radio", "stations", 1)],
            2000: [("cmd", esp32.display_sprite_payload("ours", sprite(40, 37, 1)), True),
                   ("cmd", esp32.display_show_payload("trade", 0, "Sw/Sh", "Pikachu the brave"), True)],
            6000: [("cmd", esp32.display_sprite_payload("theirs", sprite(56, 64, 2)), True),
                   ("cmd", esp32.display_show_payload("traded", 30, "Sw/Sh", "Mewtwo"), True)],
            8000: [("cmd", esp32.display_show_payload("trade", 0, "", "Queued next one"), True)],
            12000: [("cmd", esp32.display_show_payload("arrived"), True)],
            28000: [("radio", "mode", 0)]}


def gift_script():
    return {300: [("cmd", esp32.display_sprite_payload("gift", sprite(40, 40, 3)), True),
                  ("cmd", esp32.display_show_payload("gift", 0, "Mystery Gift", "Mew from the event"), True)],
            700: [("radio", "mode", 3)], 1500: [("radio", "stations", 1)],
            5000: [("cmd", esp32.display_show_payload("gifted", 6, "", "Mew"), True)],
            14000: [("cmd", esp32.display_show_payload("gift", 0, "", "Celebi"), True)],
            15000: [("reset",)],
            16000: [("cmd", esp32.display_show_payload("gifted", 3, "", "a box"), True)],
            22000: [("radio", "mode", 0)]}


def lobby_script():
    bad = [b"", b"\x09", b"\x01\x03\x08\x08", b"\x01\x00\x08\x01\xff\xff", b"\x01\x00\x41\x01" + b"\0" * 9,
           b"\x00\x06\x00\x00",
           b"\x00\x01\x00", b"\x02\x08\x00\x01a\0b\0c\0", b"\x02\x01\x02\x01a\0b\0c\0",
           b"\x02\x01\x00\x04a\0b\0c\0", b"\x03\x01"]
    return {0: [("cmd", p, False) for p in bad],
            200: [("radio", "mode", 3)],
            500: [("cmd", esp32.display_sprite_payload("ours", sprite(64, 50, 4)), True),
                  ("cmd", esp32.display_lobby_payload("Max Raid Battle", "Gigantamax Charizard",
                                                      0, 3, 5, "1234 5678"), True)],
            3000: [("cmd", esp32.display_joined_payload(1), True)],
            5000: [("cmd", esp32.display_joined_payload(4), False),
                   ("cmd", esp32.display_joined_payload(2), True)],
            8000: [("cmd", esp32.display_lobby_payload("Adventure", "", 1, 1), True)],
            10000: [("cmd", bytes((0, 1, 0, 0)) + b"x" * 40, True),
                    ("cmd", bytes((0, 3, 0, 0)) + "é~\x7f".encode("latin-1") + b"\0" + b"ab" * 30, True)],
            12000: [("cmd", esp32.display_show_payload("traded", 0, "", "Unterminated").rstrip(b"\0"), True)],
            20000: [("cmd", esp32.display_show_payload("arrived"), True)],
            26000: [("radio", "mode", 0)]}


SCRIPTS = {"radio": radio_script, "trade": trade_script, "gift": gift_script, "lobby": lobby_script}


@pytest.mark.parametrize("panel", [0, 1])
@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_frames_match_the_firmware(firmware, name, panel):
    assert play(firmware, SCRIPTS[name](), panel=panel) == 600


@pytest.mark.parametrize("panel", [0, 1])
def test_idle_dims_and_turns_off_like_the_firmware(firmware, panel):
    script = {0: [("radio", "mode", 3)], 2000: [("radio", "mode", 0)],
              700000: [("radio", "presses", 1)], 800000: [("cmd", b"\x09", False)]}
    play(firmware, script, panel=panel, step=1000, until=1500000)


def test_the_clock_wraps_like_the_firmware(firmware):
    play(firmware, trade_script(), start=0xFFFFFFFF - 7000)


def test_pixels_reads_the_page_order():
    frame = bytearray(1024)
    frame[5 + 128 * 2] = 1 << 3
    rows = pixels(bytes(frame))
    assert len(rows) == 64 and len(rows[0]) == 128
    assert [(x, y) for y, row in enumerate(rows) for x, on in enumerate(row) if on] == [(5, 19)]

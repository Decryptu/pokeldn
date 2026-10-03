#!/usr/bin/env python3
"""Renders the board's screen offline: compiles firmware/esp32/main/scene.c and screen.c for this
machine, plays a scripted session through them and writes an animated GIF (needs a C compiler and
Pillow). docs/hardware_esp32.md, The screen.

    ./.venv/bin/python tools/ldn/screen_preview.py OUT.gif [--offer 25] [--receive 150] [--gift 151]
"""
import argparse
import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pokeldn.ldn import esp32  # noqa: E402

SOURCES = [ROOT / "firmware/esp32/main/scene.c", ROOT / "firmware/esp32/main/screen.c"]
MODES = {"idle": 0, "joining": 1, "joined": 2, "hosting": 3, "sniffing": 4}


class Radio(ctypes.Structure):
    _fields_ = [("mode", ctypes.c_uint8), ("stations", ctypes.c_uint8),
                ("rx", ctypes.c_uint32), ("tx", ctypes.c_uint32), ("presses", ctypes.c_uint32)]


class Scene:
    """The firmware's scene code, built as a shared library and driven frame by frame."""

    def __init__(self, build_dir: str | None = None):
        folder = Path(build_dir or tempfile.mkdtemp(prefix="pokeldn-screen-"))
        lib = folder / ("libscene" + (".dylib" if sys.platform == "darwin" else ".so"))
        subprocess.run([os.environ.get("CC", "cc"), "-O1", "-Wall", "-Werror", "-shared", "-fPIC",
                        "-o", str(lib), *map(str, SOURCES)], check=True)
        self.lib = ctypes.CDLL(str(lib))
        self.lib.scene_command.restype = ctypes.c_bool
        self.lib.scene_draw.restype = ctypes.c_uint8
        self.lib.scene_reset()
        self.radio = Radio()
        self.now = 1000

    def command(self, payload: bytes) -> bool:
        return self.lib.scene_command(payload, len(payload), self.now)

    def frame(self) -> bytes:
        fb = ctypes.create_string_buffer(1024)
        self.power = self.lib.scene_draw(fb, ctypes.byref(self.radio), self.now)
        return fb.raw

    def advance(self, ms: int) -> None:
        self.now += ms


def pixel(fb: bytes, x: int, y: int) -> bool:
    return bool(fb[x + 128 * (y >> 3)] >> (y & 7) & 1)


def image(fb: bytes, scale: int = 4):
    from PIL import Image
    img = Image.new("RGB", (128 * scale, 64 * scale), (6, 8, 14))
    lit = Image.new("RGB", (scale - 1, scale - 1), (90, 180, 255))
    for y in range(64):
        for x in range(128):
            if pixel(fb, x, y):
                img.paste(lit, (x * scale, y * scale))
    return img


def session(scene: Scene, offer: int, receive: int, gift: int, frame_ms: int = 50):
    """A host session: idle, waiting, a console seats, a trade, then a Mystery Gift."""
    from pokeldn.app.screen import sprite_bits
    frames = []

    def play(ms, rx_rate=0, tx_rate=0):
        for _ in range(ms // frame_ms):
            scene.radio.rx += rx_rate
            scene.radio.tx += tx_rate
            frames.append(scene.frame())
            scene.advance(frame_ms)

    play(1500)
    scene.radio.mode = MODES["hosting"]
    play(2000)
    scene.radio.stations = 1
    play(1500, 2, 2)
    scene.command(esp32.display_sprite_payload("ours", sprite_bits(offer) or []))
    scene.command(esp32.display_show_payload("trade", 0, "Sw/Sh", "Pikachu"))
    play(3000, 2, 1)
    scene.command(esp32.display_sprite_payload("theirs", sprite_bits(receive) or []))
    scene.command(esp32.display_show_payload("traded", 30, "Sw/Sh", "Mewtwo"))   # a 30 s wait
    play(6000, 1, 1)
    scene.command(esp32.display_show_payload("arrived"))                        # cut short
    play(8000, 1, 1)
    scene.command(esp32.display_sprite_payload("gift", sprite_bits(gift, 40) or []))
    scene.command(esp32.display_show_payload("gift", 0, "Mystery Gift", "Mew from the event"))
    play(3000, 0, 2)
    scene.command(esp32.display_show_payload("gifted", 6, "", "Mew"))
    play(6500)
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out")
    parser.add_argument("--offer", type=int, default=25)
    parser.add_argument("--receive", type=int, default=150)
    parser.add_argument("--gift", type=int, default=151)
    args = parser.parse_args()
    frames = [image(fb) for fb in session(Scene(), args.offer, args.receive, args.gift)]
    frames[0].save(args.out, save_all=True, append_images=frames[1:], duration=50, loop=0)
    print(f"{len(frames)} frames -> {args.out}")


if __name__ == "__main__":
    main()

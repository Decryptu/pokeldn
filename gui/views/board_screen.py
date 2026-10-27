"""The board's screen drawn in the Session panel: a run's `[screen]` lines (pokeldn.ldn.esp32_wlan) replayed
through pokeldn.app.screen_render, the firmware's scenes in Python. docs/gui.md, The board's screen."""
import struct
import threading
import time
import zlib

import flet as ft

from gui import theme as t
from pokeldn.app import screen_render
from pokeldn.ldn.esp32_wlan import MIRROR_PREFIX

WIDTH, HEIGHT = 128, 64
SCALE = 2
FRAME_S = 0.05            # display.c FRAME_MS
ON, DIM, OFF = 0, 1, 2    # scene.h enum scene_power
LIT = bytes.fromhex(t.BLUE[1:])
DARK = bytes.fromhex("0B0B0D")


def png(rows: list[list[bool]]) -> bytes:
    """An 8-bit palette PNG, one index per pixel."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\0" + bytes(int(p) for p in row) for row in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 3, 0, 0, 0))
            + chunk(b"PLTE", DARK + LIT) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class BoardScreen:
    def __init__(self, app):
        self.app = app
        self.scene = screen_render.Scene()
        self.radio = (0, 0, 0, 0, 0)      # mode, stations, rx, tx, presses
        self.lock = threading.Lock()
        self.shown = None
        self.running = False
        self.image = ft.Image(src=t.image_src(png([[False] * WIDTH] * HEIGHT)), width=WIDTH * SCALE,
                              height=HEIGHT * SCALE, fit=ft.BoxFit.FILL, filter_quality=ft.FilterQuality.NONE,
                              anti_alias=False, gapless_playback=True)
        self.control = ft.Container(self.image, bgcolor="#0B0B0D", border_radius=10, padding=10,
                                    border=ft.Border.all(1, t.BORDER), alignment=ft.Alignment.CENTER,
                                    visible=False)

    @staticmethod
    def _now() -> int:
        return int(time.monotonic() * 1000)

    def take(self, line: str) -> bool:
        """True for a `[screen]` line, which it applies."""
        if not line.startswith(MIRROR_PREFIX):
            return False
        kind, _, rest = line[len(MIRROR_PREFIX):].partition(" ")
        with self.lock:
            if kind == "reset":
                self.scene.reset()
            elif kind == "cmd":
                try:
                    self.scene.command(bytes.fromhex(rest), self._now())
                except ValueError:
                    pass
            elif kind == "radio":
                try:
                    self.radio = tuple(int(v) for v in rest.split())[:5]
                except ValueError:
                    pass
        return True

    def show(self, on: bool) -> None:
        self.control.visible = on
        if on and not self.running:
            self.running = True
            threading.Thread(target=self._loop, name="board-screen", daemon=True).start()
        elif not on:
            self.running = False

    def _loop(self) -> None:
        while self.running:
            with self.lock:
                frame, power = self.scene.draw(*self.radio, self._now())
            shown = (frame, power)
            if shown != self.shown:
                self.shown = shown
                rows = screen_render.pixels(frame) if power != OFF else [[False] * WIDTH] * HEIGHT
                data = png(rows)
                opacity = 0.45 if power == DIM else 1.0

                def draw(data=data, opacity=opacity):
                    self.image.src = t.image_src(data)
                    self.image.opacity = opacity
                    if self.control.page:
                        self.image.update()
                self.app.ui(draw)
            time.sleep(FRAME_S)

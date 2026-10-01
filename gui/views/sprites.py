import threading

import flet as ft

from gui import theme as t
from gui.views.widgets import PixelActivity
from pokeldn.app.sprites import CACHE, bounds

SIZE = 96   # the sprites are 96x96 pixels: shown at 1:1, or at a whole multiple, never in between
ICON = 48   # pixelarticons are drawn on a 24 px grid: 48 is a whole multiple
MINI = 46   # a small tile: the Pokemon cropped from its canvas at 1:1, or at 1:2 when wider than the tile
EDGE = 1    # the frame's border sits outside the sprite: a 96 px frame would squeeze it to 94
OVERHANG = 4   # a sprite this much wider than its tile stays 1:1, trimmed; halved, Eevee (47) fell to 23


class Sprite:
    """One Pokemon's pixel-art sprite. Shows a placeholder when there is none, offline or never downloaded."""

    def __init__(self, app, species: int = 0, shiny: bool = False, size: int = SIZE):
        self.app, self.size = app, size
        self.token = 0
        self.frame = ft.Container(width=size + 2 * EDGE, height=size + 2 * EDGE, alignment=ft.Alignment.CENTER,
                                  bgcolor=t.BG, border=ft.Border.all(EDGE, t.DIVIDER), border_radius=12 if size >= SIZE else 10,
                                  clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
        self.control = self.frame
        self.show(species, shiny, update=False)

    def show(self, species: int, shiny: bool = False, update: bool = True) -> None:
        """Cached sprites appear at once; the rest load on a worker thread, and a stale answer is dropped."""
        self.token += 1
        token = self.token
        CACHE.online = bool(self.app.settings.sprites)
        if not species:
            self._set(self._placeholder(), update)
            return
        data = CACHE.cached(species, shiny)
        if data:
            self._set(self._image(data), update)
            return
        shown = CACHE.cached(species) if shiny else None    # the plain sprite stands in while the shiny loads
        if shown:
            self._set(self._image(shown), update)
        if CACHE.known_missing(species, shiny) and (not shiny or CACHE.known_missing(species)):
            if not shown:
                self._set(self._placeholder("No sprite for this species."), update)
            return
        if not shown:
            self._set(PixelActivity("Loading sprite"), update)
        threading.Thread(target=self._load, args=(token, species, shiny, bool(shown)), daemon=True).start()

    def _load(self, token: int, species: int, shiny: bool, shown: bool) -> None:
        data = CACHE.get(species, shiny) or (CACHE.get(species) if shiny and not shown else None)

        def done():
            if token != self.token:
                return
            if data:
                self._set(self._image(data))
            elif not shown:
                self._set(self._placeholder(self._why()))
        self.app.ui(done)

    def _why(self) -> str:
        if not self.app.settings.sprites:
            return "Sprite downloads are off in Settings."
        return "Sprite not available. It downloads once when the app is online."

    def _image(self, data: bytes) -> ft.Control:
        if self.size >= SIZE:
            return ft.Image(src=data, width=self.size, height=self.size, fit=ft.BoxFit.CONTAIN,
                            filter_quality=ft.FilterQuality.NONE, anti_alias=False, gapless_playback=True,
                            error_content=self._placeholder())
        x0, y0, x1, y1 = bounds(data) or (0, 0, SIZE, SIZE)
        scale = 1 if max(x1 - x0, y1 - y0) <= self.size + OVERHANG else 0.5
        # At 1:2 the canvas lands on whole pixels, so each tile pixel averages one 2x2 block.
        image = ft.Image(src=data, width=SIZE * scale, height=SIZE * scale, fit=ft.BoxFit.FILL,
                         left=round(self.size / 2 - (x0 + x1) / 2 * scale),
                         top=round(self.size / 2 - (y0 + y1) / 2 * scale),
                         filter_quality=ft.FilterQuality.NONE if scale == 1 else ft.FilterQuality.MEDIUM,
                         anti_alias=False, gapless_playback=True, error_content=self._placeholder())
        return ft.Stack([image], width=self.size, height=self.size, clip_behavior=ft.ClipBehavior.HARD_EDGE)

    def _placeholder(self, tip: str = "") -> ft.Control:
        return ft.Container(t.pixel_icon("circle-question", size=ICON if self.size >= SIZE else 24,
                                         color=t.FAINT),
                            alignment=ft.Alignment.CENTER, width=self.size, height=self.size,
                            tooltip=tip or None)

    def _set(self, content: ft.Control, update: bool = True) -> None:
        self.frame.content = content
        if update:
            try:
                self.frame.update()
            except RuntimeError:    # the picker was closed, or is not on the page yet
                pass

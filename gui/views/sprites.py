import threading

import flet as ft

from gui import theme as t
from gui.views.widgets import PixelActivity
from pokeldn.app.sprites import CACHE

SIZE = 96   # the sprites are 96x96 pixels: shown at 1:1, or at a whole multiple, never in between
ICON = 48   # pixelarticons are drawn on a 24 px grid: 48 is a whole multiple


class Sprite:
    """One Pokemon's pixel-art sprite. Shows a placeholder when there is none, offline or never downloaded."""

    def __init__(self, app, species: int = 0, shiny: bool = False, size: int = SIZE):
        self.app, self.size = app, size
        self.token = 0
        self.frame = ft.Container(width=size, height=size, alignment=ft.Alignment.CENTER, bgcolor=t.BG,
                                  border=ft.Border.all(1, t.BORDER), border_radius=10)
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
        return ft.Image(src=data, width=self.size, height=self.size, fit=ft.BoxFit.CONTAIN,
                        filter_quality=ft.FilterQuality.NONE, anti_alias=False, gapless_playback=True,
                        error_content=self._placeholder())

    def _placeholder(self, tip: str = "") -> ft.Control:
        return ft.Container(t.pixel_icon("circle-question", size=ICON, color=t.FAINT),
                            alignment=ft.Alignment.CENTER, width=self.size, height=self.size,
                            tooltip=tip or None)

    def _set(self, content: ft.Control, update: bool = True) -> None:
        self.frame.content = content
        if update:
            try:
                self.frame.update()
            except RuntimeError:    # the picker was closed, or is not on the page yet
                pass

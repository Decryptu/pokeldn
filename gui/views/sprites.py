from concurrent.futures import ThreadPoolExecutor

import flet as ft

from gui import theme as t
from gui.views.widgets import PixelActivity
from pokeldn.app.sprites import CACHE, bounds
from pokeldn.app.sprite_forms import sprite_key
from pokeldn.app.i18n import t as tr

SIZE = 96   # the sprites are 96x96 pixels: shown at 1:1, or at a whole multiple, never in between
ICON = 48   # pixelarticons are drawn on a 24 px grid: 48 is a whole multiple
MINI = 46   # a small tile: every Pokemon's visible pixels scaled to fill it, less PAD on each side
EDGE = 1    # the frame's border sits outside the sprite: a 96 px frame would squeeze it to 94
PAD = 3     # sprites run from 28 px (Togepi) to 96: a fixed scale left half of them twice the size of the rest
WORKERS = ThreadPoolExecutor(4, thread_name_prefix="sprite")


class Sprite:
    """One Pokemon's pixel-art sprite. Shows a placeholder when there is none, offline or never downloaded."""

    def __init__(self, app, species: int = 0, shiny: bool = False, size: int = SIZE, form: int = 0):
        self.app, self.size = app, size
        self.token = 0
        self.frame = ft.Container(width=size + 2 * EDGE, height=size + 2 * EDGE, alignment=ft.Alignment.CENTER,
                                  bgcolor=t.BG, border=ft.Border.all(EDGE, t.DIVIDER), border_radius=12 if size >= SIZE else 10,
                                  clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
        self.control = self.frame
        self.show(species, shiny, update=False, form=form)

    def show(self, species: int, shiny: bool = False, update: bool = True, form: int = 0) -> None:
        """Cached sprites appear at once; the rest load on a worker thread, and a stale answer is dropped."""
        self.token += 1
        token = self.token
        CACHE.online = bool(self.app.settings.sprites)
        species = sprite_key(species, form)
        if not species:
            self._set(self._placeholder(tr('sprites.no_sprite_for_this_form_0f3039', 'No sprite for this form.') if form else ""), update)
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
                self._set(self._placeholder(tr('sprites.no_sprite_for_this_species_2c7400', 'No sprite for this species.')), update)
            return
        if not CACHE.online:
            if not shown:
                self._set(self._placeholder(self._why()), update)
            return
        if not shown:
            self._set(PixelActivity(tr('sprites.loading_sprite_642b3d', 'Loading sprite')), update)
        WORKERS.submit(self._load, token, species, shiny, bool(shown))

    def _load(self, token: int, species: int | str, shiny: bool, shown: bool) -> None:
        if token != self.token:
            return
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
            return tr('sprites.sprite_downloads_are_off_in_settings_bd65ba', 'Sprite downloads are off in Settings.')
        return tr('sprites.sprite_not_available_it_downloads_once_when_the_app_is__aee73c', 'Sprite not available. It downloads once when the app is online.')

    def _image(self, data: bytes) -> ft.Control:
        if self.size >= SIZE:
            return ft.Image(src=t.image_src(data), width=self.size, height=self.size, fit=ft.BoxFit.CONTAIN,
                            filter_quality=ft.FilterQuality.NONE, anti_alias=False, gapless_playback=True,
                            error_content=self._placeholder())
        x0, y0, x1, y1 = bounds(data) or (0, 0, SIZE, SIZE)
        scale = (self.size - 2 * PAD) / max(x1 - x0, y1 - y0)
        image = ft.Image(src=t.image_src(data), width=SIZE * scale, height=SIZE * scale, fit=ft.BoxFit.FILL,
                         left=round(self.size / 2 - (x0 + x1) / 2 * scale),
                         top=round(self.size / 2 - (y0 + y1) / 2 * scale),
                         filter_quality=ft.FilterQuality.MEDIUM,
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

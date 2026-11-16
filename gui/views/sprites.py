from concurrent.futures import ThreadPoolExecutor

import flet as ft

from gui import theme as t
from gui.views.widgets import skeleton_tiles
from pokeldn.app.sprites import CACHE, ITEMS, RIBBON_SETS, RIBBONS, size as png_size
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

    def show(self, species: int, shiny: bool = False, update: bool = True, form: int = 0,
             sweet: int | None = None) -> None:
        """A sprite already in memory appears at once. Any other is read from disk, or downloaded, on a worker
        thread behind a skeleton: reading, hashing and checking a PNG on the UI thread, once per tile, stalled the
        window (docs/gui.md, Performance). A stale answer is dropped."""
        self.token += 1
        token = self.token
        CACHE.online = bool(self.app.settings.sprites)
        species = sprite_key(species, form, sweet=sweet)
        if not species:
            self._set(self._placeholder(tr('sprites.no_sprite_for_this_form_0f3039', 'No sprite for this form.') if form else ""), update)
            return
        data = CACHE.held(species, shiny)
        if data:
            self._set(self._image(data, species, shiny), update)
            return
        if not CACHE.online and not CACHE.on_disk(species, shiny) and not (shiny and CACHE.on_disk(species)):
            self._set(self._placeholder(self._why()), update)    # nothing to read and nothing to download
            return
        shown = CACHE.held(species) if shiny else None    # the plain sprite stands in while the shiny loads
        # An empty frame while the disk is read (milliseconds); a skeleton every tile flashed for that long read
        # as flicker. The skeleton shows only before a download (_load).
        self._set(self._image(shown, species, False) if shown else None, update)
        WORKERS.submit(self._load, token, species, shiny, bool(shown))

    def _load(self, token: int, species: int | str, shiny: bool, shown: bool) -> None:
        if token != self.token:
            return
        data = CACHE.cached(species, shiny)
        if data is None and not shown and CACHE.online and not CACHE.known_missing(species, shiny):
            self.app.ui(lambda: token == self.token and self._set(
                skeleton_tiles(1, self.size, tr('sprites.loading_sprite_642b3d', 'Loading sprite'))))
        data = data or CACHE.get(species, shiny)
        plain = not data and shiny and not shown
        if plain:
            data = CACHE.get(species)
        missing = not data and CACHE.known_missing(species, shiny) and (not shiny or CACHE.known_missing(species))

        def done():
            if token != self.token:
                return
            if data:
                self._set(self._image(data, species, shiny and not plain))
            elif not shown:
                self._set(self._placeholder(tr('sprites.no_sprite_for_this_species_2c7400', 'No sprite for this species.')
                                            if missing else self._why()))
        self.app.ui(done)

    def _why(self) -> str:
        if not self.app.settings.sprites:
            return tr('sprites.sprite_downloads_are_off_in_settings_bd65ba', 'Sprite downloads are off in Settings.')
        return tr('sprites.sprite_not_available_it_downloads_once_when_the_app_is__aee73c', 'Sprite not available. It downloads once when the app is online.')

    def _image(self, data: bytes, species: int | str, shiny: bool) -> ft.Control:
        if self.size >= SIZE:
            return ft.Image(src=t.image_src(data), width=self.size, height=self.size, fit=ft.BoxFit.CONTAIN,
                            filter_quality=ft.FilterQuality.NONE, anti_alias=False, gapless_playback=True,
                            error_content=self._placeholder())
        x0, y0, x1, y1 = CACHE.crop(species, shiny, data) or (0, 0, SIZE, SIZE)
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


class SpritePool:
    """A view's sprites kept from one render to the next. A new ft.Image resends its PNG and the client decodes
    it again, so a list rebuilt on every click blinks; a kept Sprite sends nothing. sweep() at each render."""

    def __init__(self, app):
        self.app = app
        self.kept: dict[tuple, Sprite] = {}
        self.used: dict[tuple, Sprite] = {}

    def get(self, slot, species: int, shiny: bool = False, size: int = SIZE, form: int = 0) -> ft.Control:
        key = (slot, species, bool(shiny), size, form)
        while key in self.used:     # a control has one parent: a repeated slot gets its own sprite
            key = (*key, 0)
        sprite = self.kept.pop(key, None) or Sprite(self.app, species, shiny, size=size, form=form)
        self.used[key] = sprite
        return sprite.control

    def sweep(self) -> None:
        self.kept, self.used = self.used, {}


class Icon:
    """An item, ball or ribbon icon by the helper's "icon" name, cropped to its visible pixels and scaled
    to fill `size`; an empty slot while it loads, offline or when PokeAPI has none."""

    def __init__(self, app, name: str | None, ribbon: bool | str = False, size: int = 24, fetch: bool = True):
        """`fetch` False shows only a cached image: a list's rows, which the cache's prefetch fills in. `ribbon` names
        the helper's "icon_set", or True for generation IX."""
        self.app, self.size = app, size
        self.cache = RIBBON_SETS.get(ribbon, RIBBONS) if ribbon else ITEMS
        self.token = 0
        self.control = ft.Container(width=size, height=size, alignment=ft.Alignment.CENTER)
        self.show(name, update=False, fetch=fetch)

    def show(self, name: str | None, update: bool = True, fetch: bool = True) -> None:
        self.token += 1
        token = self.token
        self.cache.online = bool(self.app.settings.sprites)
        data = self.cache.held(name) if name else None     # memory only: disk is a worker's job (Sprite.show)
        self._set(data, name, update)
        if data or not fetch or not name or (not self.cache.online and not self.cache.on_disk(name)):
            return

        def load():
            if token != self.token:
                return
            found = self.cache.get(name)
            self.app.ui(lambda: token == self.token and found and self._set(found, name))
        WORKERS.submit(load)

    def _set(self, data: bytes | None, name: str | None, update: bool = True) -> None:
        if data is None:
            self.control.content = None
        else:
            width, height = png_size(data) or (self.size, self.size)
            x0, y0, x1, y1 = self.cache.crop(name, False, data) or (0, 0, width, height)
            scale = self.size / max(x1 - x0, y1 - y0)
            self.control.content = ft.Stack([ft.Image(
                src=t.image_src(data), width=width * scale, height=height * scale, fit=ft.BoxFit.FILL,
                left=round(self.size / 2 - (x0 + x1) / 2 * scale), top=round(self.size / 2 - (y0 + y1) / 2 * scale),
                filter_quality=ft.FilterQuality.NONE if scale >= 1 else ft.FilterQuality.MEDIUM,
                anti_alias=False, gapless_playback=True)],
                width=self.size, height=self.size, clip_behavior=ft.ClipBehavior.HARD_EDGE)
        if update:
            try:
                self.control.update()
            except RuntimeError:    # the picker was closed, or is not on the page yet
                pass

import os

import flet as ft

from gui import theme as t
from pokeldn import __version__
from pokeldn.app.paths import SESSION
from pokeldn.app.sprites import CACHE
from pokeldn.app.settings import LANGUAGES
from gui.views.widgets import PathField, open_folder

LINKS = (("Documentation", "https://decryptu.github.io/pokeldn/"),
         ("GitHub", "https://github.com/Decryptu/pokeldn"),
         ("Discord", "https://discord.gg/PyvaVYnpXC"))


def keys_found(path: str) -> bool:
    return os.path.isfile(os.path.expanduser(path))


class SettingsView:
    def __init__(self, app):
        self.app = app
        self.keys_state = ft.Container()
        self.sprite_state = t.text("", 12, t.MUTED)
        self.column = ft.Column(spacing=t.GAP, width=760)
        self.control = ft.ListView([ft.Row([self.column], alignment=ft.MainAxisAlignment.CENTER)],
                                   padding=ft.Padding(4, 8, 4, 24), expand=True)
        self.render()

    def save(self, name: str, value) -> None:
        setattr(self.app.settings, name, value)
        self.app.settings.save()

    def render(self) -> None:
        s = self.app.settings
        home = lambda: os.path.expanduser("~")   # noqa: E731
        keys = PathField(self.app.picker, home, s.keys, "file", ("keys",), self._keys)
        received = PathField(self.app.picker, home, s.received, "dir", on_change=lambda v: self.save("received", v))
        self._keys(s.keys, update=False)
        speed = t.dropdown([("921600", "921600 (default)"), ("1500000", "1500000 (faster, needs a good cable)")],
                           str(s.baud), on_select=lambda e: self.save("baud", int(e.control.value)))

        def number(name, label):
            def store(e):
                try:
                    value = int(e.control.value)
                except ValueError:
                    return
                if 0 <= value <= 65535:
                    self.save(name, value)
            return ft.Column([t.text(label, 11, t.MUTED),
                              t.field(value=str(getattr(s, name)), mono=True, on_change=store)],
                             spacing=4, expand=True)

        trainer = ft.Row([
            ft.Column([t.text("Name", 11, t.MUTED),
                       t.field(value=s.ot, on_change=lambda e: self.save("ot", e.control.value[:12]))],
                      spacing=4, expand=2),
            number("tid", "Trainer ID"),
            number("sid", "Secret ID"),
            ft.Column([t.text("Language", 11, t.MUTED),
                       t.dropdown(list(LANGUAGES), str(s.language),
                                  on_select=lambda e: self.save("language", int(e.control.value)))],
                      spacing=4, expand=2),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)

        def switch(name, label, help_):
            return t.card(label, None, help_,
                          trailing=t.switch(getattr(s, name), lambda e: self.save(name, e.control.value)))

        def link(label, url):
            return t.link_button(label, lambda e: self.app.page.run_task(self.app.open_url, url))

        self.column.controls = [
            t.notch(ft.Row([t.pixel_icon("gear", color=t.RED),
                            t.text("Settings", 13, weight=ft.FontWeight.W_600)], spacing=8, tight=True)),
            t.card("Switch keys", ft.Column([keys.control, self.keys_state], spacing=8),
                   "prod.keys from your own console. It decrypts the local wireless advertisements and never "
                   "leaves this computer."),
            t.card("Your trainer", trainer,
                   "The original trainer of every Pokemon the app builds. The IDs were drawn at random on first "
                   "launch."),
            t.card("Received Pokemon", ft.Row([ft.Container(received.control, expand=True),
                                               t.icon_button("external-link",
                                                             lambda e: open_folder(os.path.expanduser(s.received)),
                                                             "Open it")]),
                   "Where the Pokemon a console sends you are saved."),
            t.card("Serial speed", speed, "How fast the computer talks to the board after connecting."),
            t.card("Pokemon sprites", ft.Row([t.button("Clear the cache", self._clear_sprites, "refresh",
                                                        filled=False), self.sprite_state], spacing=10),
                   "Pixel-art sprites come from PokeAPI and are saved on this computer after the first download, "
                   "so they keep showing offline. The app works without them.",
                   trailing=t.switch(s.sprites, lambda e: self.save("sprites", e.control.value))),
            switch("capture", "Record every session",
                   "Keeps each session's datagrams. Small, and what a bug report needs."),
            switch("board_trace", "Record the board's serial traffic",
                   "Adds the board's counters and every serial message. For radio problems only."),
            t.card("Session records", ft.Row([t.button("Open the folder", lambda e: open_folder(str(SESSION / "captures")),
                                                       "folder", filled=False)]),
                   "Attach the latest file to a bug report."),
            t.card(f"About pokeldn {__version__}", ft.Row([link(label, url) for label, url in LINKS], spacing=4),
                   "pokeldn is AGPLv3. Pokemon are checked with PKHeX.Core (GPLv3)."),
        ]

    def _clear_sprites(self, e) -> None:
        self.sprite_state.value = f"{CACHE.clear()} files removed"
        self.sprite_state.update()

    def _keys(self, value: str, update: bool = True) -> None:
        self.save("keys", value)
        ok = keys_found(value)
        self.keys_state.content = ft.Row([
            t.pixel_icon("checkbox-on" if ok else "warning-diamond",
                    color=t.GREEN if ok else t.RED),
            t.text("Found" if ok else "No file at this path", 12, t.GREEN if ok else t.RED)], spacing=6)
        if update:
            self.keys_state.update()

import os

import flet as ft

from gui import theme as t
from gui.app import keys_found
from pokeldn import __version__
from pokeldn.app.paths import SESSION
from pokeldn.app.sprites import CACHE
from pokeldn.app.settings import LANGUAGES
from gui.views.widgets import PathField, open_folder

LINKS = (("Documentation", "https://decryptu.github.io/pokeldn/"),
         ("GitHub", "https://github.com/Decryptu/pokeldn"),
         ("Discord", "https://discord.gg/PyvaVYnpXC"))


class SettingsView:
    def __init__(self, app):
        self.app = app
        self.keys_state = ft.Container()
        self.sprite_state = t.text("", 12, t.MUTED)
        self.update_state = t.text("", 12, t.MUTED)
        self.shown = self.asked = False
        app.update_listeners.append(self._update_shown)
        self._update_text()
        self.show_advanced = False
        self.column = ft.Column(spacing=t.GAP, width=760)
        self.scroll = ft.ListView([ft.Row([self.column], alignment=ft.MainAxisAlignment.CENTER)],
                                  padding=ft.Padding(4, 8, 4, 24), expand=True)
        self.control = t.fade(self.scroll)
        self.render()

    def enter(self, **_) -> None:
        self.shown = True

    def leave(self) -> None:
        self.shown = False

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

        def section(label):
            return ft.Container(t.text(label, 12, t.MUTED, weight=ft.FontWeight.W_600),
                                padding=ft.Padding(4, 8, 0, 0))

        advanced = [
            t.card("Serial speed", speed, "How fast the computer talks to the board. Keep the default unless a "
                                          "guide says otherwise."),
            switch("board_trace", "Record the board's serial traffic",
                   "Adds the board's counters and every serial message to the session record. Only for radio "
                   "problems someone asked you to report."),
            t.card("Pokemon sprites", ft.Row([t.button("Clear the cache", self._clear_sprites, "refresh",
                                                        filled=False), self.sprite_state], spacing=10),
                   "Pixel-art sprites come from PokeAPI and are kept on this computer after the first download. "
                   "The app works without them.",
                   trailing=t.switch(s.sprites, lambda e: self.save("sprites", e.control.value))),
        ]
        self.column.controls = [
            t.notch(ft.Row([t.pixel_icon("gear", color=t.RED),
                            t.text("Settings", 13, weight=ft.FontWeight.W_600)], spacing=8, tight=True)),
            section("Your setup"),
            t.card("Switch keys", ft.Column([keys.control, self.keys_state], spacing=8),
                   "prod.keys dumped from your own console. Needed to talk to the games; it never leaves this "
                   "computer."),
            t.card("Your trainer", trainer,
                   "The original trainer of every Pokemon the app builds for you. Put your own name and IDs to "
                   "make them yours; the IDs were drawn at random on first launch."),
            t.card("Received Pokemon", ft.Row([ft.Container(received.control, expand=True),
                                               t.icon_button("external-link",
                                                             lambda e: open_folder(os.path.expanduser(s.received)),
                                                             "Open it")]),
                   "Where the Pokemon a console sends you are saved."),
            section("Bug reports"),
            t.card("Record every session", ft.Row([t.button("Open the records", lambda e: open_folder(
                str(SESSION / "captures")), "folder", filled=False)]),
                   "Keeps a small record of each session. When something fails, attach the latest file to your "
                   "report.",
                   trailing=t.switch(s.capture, lambda e: self.save("capture", e.control.value))),
            ft.Row([t.link_button("Hide advanced settings" if self.show_advanced else "Show advanced settings",
                                  self._toggle_advanced)]),
            *(advanced if self.show_advanced else []),
            t.card("Updates", ft.Row([t.button("Check now", self._check_update, "refresh", filled=False),
                                      self.update_state], spacing=10),
                   "Asks GitHub for a newer pokeldn when the app starts. Nothing about you or your games is "
                   "sent.",
                   trailing=t.switch(s.check_updates, lambda e: self.save("check_updates", e.control.value))),
            t.card(f"About pokeldn {__version__}", ft.Row([link(label, url) for label, url in LINKS], spacing=4),
                   "pokeldn is AGPLv3. Pokemon are checked with PKHeX.Core (GPLv3)."),
        ]

    def _toggle_advanced(self, e) -> None:
        self.show_advanced = not self.show_advanced
        self.render()
        self.control.update()

    def _check_update(self, e) -> None:
        self.asked = True
        self.app.check_update()
        self._update_text()
        self.update_state.update()

    def _update_text(self) -> None:
        release, state = self.app.update, self.app.update_state
        self.update_state.value = {
            "checking": "Checking...",
            "current": f"You have the latest version ({__version__}).",
            "offline": "GitHub did not answer. Check your connection.",
            "available": f"pokeldn {release.version} is available." if release else "",
        }.get(state, "")
        self.update_state.color = t.GREEN if state == "available" else t.MUTED

    def _update_shown(self) -> None:
        self._update_text()
        if self.shown:
            self.update_state.update()
            if self.asked and self.app.update:
                self.app.navigate("update")
        self.asked = False

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

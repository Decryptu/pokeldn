import os

import flet as ft

from gui import theme as t
from gui.views.widgets import PathField, open_folder

LINKS = (("Documentation", "https://decryptu.github.io/pokeldn/"),
         ("GitHub", "https://github.com/Decryptu/pokeldn"),
         ("Discord", "https://discord.gg/PyvaVYnpXC"))


class SettingsView:
    def __init__(self, app):
        self.app = app
        self.keys_state = ft.Container()
        self.column = ft.Column(spacing=12, width=760)
        self.control = t.panel(ft.ListView([ft.Row([self.column], alignment=ft.MainAxisAlignment.CENTER)],
                                           padding=24, expand=True), expand=True)
        self.render()

    def save(self, name: str, value) -> None:
        setattr(self.app.settings, name, value)
        self.app.settings.save()

    def render(self) -> None:
        s = self.app.settings
        home = lambda: str(os.path.expanduser("~"))   # noqa: E731
        keys = PathField(self.app.picker, home, s.keys, "file", ("keys",), self._keys)
        work = PathField(self.app.picker, home, s.work_dir, "dir", on_change=lambda v: self.save("work_dir", v))
        self._keys(s.keys, update=False)
        speed = t.dropdown([("921600", "921600 (default)"), ("1500000", "1500000 (faster, needs a good cable)")],
                           str(s.baud), on_select=lambda e: self.save("baud", int(e.control.value)))

        def switch(name, label, help_):
            return t.card(label, None, help_,
                          trailing=t.switch(getattr(s, name), lambda e: self.save(name, e.control.value)))

        def link(label, url):
            return ft.TextButton(label, on_click=lambda e: self.app.page.run_task(self.app.open_url, url),
                                 style=ft.ButtonStyle(color=t.BLUE))

        self.column.controls = [
            t.text("Settings", 22, weight=ft.FontWeight.W_700),
            t.card("Switch keys", ft.Column([keys.control, self.keys_state], spacing=8),
                   "prod.keys from your own console. It decrypts the local wireless advertisements; it never "
                   "leaves this computer."),
            t.card("Work folder", ft.Row([ft.Container(work.control, expand=True),
                                          t.icon_button(ft.Icons.OPEN_IN_NEW_ROUNDED,
                                                        lambda e: open_folder(os.path.expanduser(s.work_dir)),
                                                        "Open it")]),
                   "Sessions run here. Received Pokemon go to received/, session records to captures/, and "
                   "relative paths in a tool point inside it."),
            t.card("Serial speed", speed, "How fast the computer talks to the board after connecting."),
            switch("capture", "Record every session",
                   "Writes each session's datagrams to captures/. Small, and what a bug report needs."),
            switch("board_trace", "Record the board's serial traffic",
                   "Adds the board's counters and every serial message. For radio problems only."),
            t.card("About", ft.Row([link(label, url) for label, url in LINKS], spacing=4),
                   "pokeldn is AGPLv3. It talks to retail games through their own local wireless protocols."),
        ]

    def _keys(self, value: str, update: bool = True) -> None:
        self.save("keys", value)
        ok = os.path.isfile(os.path.expanduser(value))
        self.keys_state.content = ft.Row([
            ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED if ok else ft.Icons.ERROR_OUTLINE_ROUNDED, size=15,
                    color=t.GREEN if ok else t.AMBER),
            t.text("Found" if ok else "No file at this path", 12, t.GREEN if ok else t.AMBER)], spacing=6)
        if update:
            self.keys_state.update()

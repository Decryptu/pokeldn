import copy
import os
import threading

import flet as ft

from gui import theme as t
from gui.app import keys_found
from pokeldn import __version__
from pokeldn.app.paths import SESSION
from pokeldn.app.sprites import CACHE
from pokeldn.app.settings import LANGUAGES, switch_ids_valid
from pokeldn.app import storage
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
        self.storage_state = t.text("Checking local files...", 12, t.MUTED)
        self.storage_result = t.text("", 12, t.MUTED, visible=False)
        self.storage_inventory = storage.Inventory()
        self.storage_work = False
        self.clear_button = t.button("Clear local files", self._clear_local, "folder", filled=False,
                                     disabled=True)
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
        self._storage_refresh()

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

        def number(name, label, valid, size):
            def store(e):
                try:
                    value = int(e.control.value)
                except ValueError:
                    return
                if valid(value):
                    self.save(name, value)
            return ft.Column([t.text(label, 11, t.MUTED),
                              t.field(value=str(getattr(s, name)), mono=True, digits=True, limit=size,
                                      on_change=store)],
                             spacing=4, expand=True)

        gba = lambda v: 0 <= v <= 65535   # noqa: E731
        trainer = ft.Column([
            ft.Row([
                ft.Column([t.text("Name", 11, t.MUTED),
                           t.field(value=s.ot, limit=12, on_change=lambda e: self.save("ot", e.control.value[:12]))],
                          spacing=4, expand=True),
                ft.Column([t.text("Language", 11, t.MUTED),
                           t.dropdown(list(LANGUAGES), str(s.language),
                                      on_select=lambda e: self.save("language", int(e.control.value)))],
                          spacing=4, expand=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row([
                number("tid", "ID, FireRed and LeafGreen", gba, 5),
                number("sid", "Secret ID", gba, 5),
                number("switch_tid", "ID, Switch games", lambda v: switch_ids_valid(v, s.switch_sid), 6),
                number("switch_sid", "Secret ID", lambda v: switch_ids_valid(s.switch_tid, v), 4),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),
        ], spacing=10)

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
            ft.Container(ft.Row([t.pixel_icon("gear", size=24, color=t.RED),
                                 t.text("Settings", 22, weight=ft.FontWeight.W_600)], spacing=10),
                         padding=ft.Padding(4, 12, 0, 0)),
            section("Your setup"),
            t.card("Switch keys", ft.Column([keys.control, self.keys_state], spacing=8),
                   "prod.keys dumped from your own console. Needed to talk to the games; it never leaves this "
                   "computer."),
            t.card("Your trainer", trainer,
                   "The original trainer of every Pokemon the app builds for you. Put your own name and IDs to "
                   "make them yours: FireRed and LeafGreen show a five-digit ID, the Switch games a six-digit "
                   "one. The IDs were drawn at random on first launch."),
            t.card("Received Pokemon", ft.Row([ft.Container(received.control, expand=True),
                                               t.icon_button("external-link",
                                                             lambda e: open_folder(os.path.expanduser(s.received)),
                                                             "Open it")]),
                   "Where the Pokemon a console sends you are saved."),
            section("Storage"),
            t.card("Local files", ft.Column([
                self.storage_state,
                ft.Row([self.clear_button], spacing=10),
                self.storage_result,
            ], spacing=8),
                   "Free space used by session records, logs, temporary offers and unused built Pokemon. "
                   "Your received Pokemon, selected offers, keys, firmware and settings are kept."),
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

    def _storage_refresh(self, inventory=None) -> None:
        if self.storage_work:
            return
        self.storage_work = True
        self.clear_button.disabled = True
        self.storage_state.value = "Clearing local files..." if inventory is not None else "Checking local files..."
        if self.shown:
            self.app.ui(self.control.update)
        settings = copy.deepcopy(self.app.settings)

        def work():
            try:
                result = storage.clear(inventory, settings) if inventory is not None else None
                found = storage.scan(settings)
                self.app.ui(lambda: self._storage_done(found, result))
            except OSError as error:
                self.app.ui(lambda message=str(error): self._storage_done(storage.Inventory(errors=1),
                                                                          error=message))
            finally:
                if inventory is not None:
                    self.app.storage_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _storage_done(self, inventory, result=None, error="") -> None:
        self.storage_work = False
        self.storage_inventory = inventory
        count = len(inventory.files)
        self.clear_button.disabled = not count
        self.storage_state.value = (f"{storage.size_text(inventory.size)} can be freed · {count} files"
                                    if count else "No local files to clear.")
        if inventory.errors:
            self.storage_state.value += " Some folders could not be read."
        if result is not None:
            self.storage_result.value = f"Freed {storage.size_text(result.size)} · {result.files} files removed."
            if result.errors:
                self.storage_result.value += f" {result.errors} files could not be removed; try again."
            if result.skipped:
                self.storage_result.value += " Files in use or changed since the check were kept."
        if error:
            self.storage_result.value = f"Could not clear local files: {error}"
        self.storage_result.visible = bool(self.storage_result.value)
        if self.shown:
            self.control.update()

    def _clear_local(self, e) -> None:
        if self.storage_work:
            return
        if self.app.busy:
            self.storage_result.value = "Finish the current run or board check before clearing local files."
            self.storage_result.visible = True
            self.storage_result.update()
            return
        inventory = self.storage_inventory
        if not inventory.files:
            self._storage_refresh()
            return

        def close(e):
            self.app.page.pop_dialog()

        def clear(e):
            close(e)
            if self.app.busy or self.storage_work:
                self.storage_result.value = "Finish the current run or board check before clearing local files."
                self.storage_result.visible = True
                self.storage_result.update()
                return
            self.app.storage_busy = True
            self._storage_refresh(inventory)

        self.app.page.show_dialog(t.dialog(
            title=t.text("Clear local files?", 17, weight=ft.FontWeight.W_600),
            content=ft.Container(t.text(
                f"Remove {len(inventory.files)} files and free about {storage.size_text(inventory.size)}. "
                "This deletes saved session records, logs, temporary offers and unused built Pokemon. "
                "Save any records needed for a bug report first. Your received Pokemon, selected offers, "
                "keys, firmware and settings are kept.", 13, t.MUTED), width=460),
            actions=[t.secondary_button("Cancel", close), t.button("Clear files", clear)],
        ))

    def _keys(self, value: str, update: bool = True) -> None:
        self.save("keys", value)
        ok = keys_found(value)
        self.keys_state.content = ft.Row([
            t.pixel_icon("checkbox-on" if ok else "warning-diamond",
                    color=t.GREEN if ok else t.RED),
            t.text("Found" if ok else "No file at this path", 12, t.GREEN if ok else t.RED)], spacing=6)
        if update:
            self.keys_state.update()

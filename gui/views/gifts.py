"""Shared Mystery Gift file picker and export button."""

import asyncio
import os

import flet as ft

from gui import theme as t
from gui.views.widgets import PathField
from pokeldn import gifts, pokemon
from pokeldn.app import command, gift_files


class GiftPicker:
    def __init__(self, games, field):
        self.games, self.field = games, field
        value = command.value_of(field, games.values) or ""
        self.path = PathField(games.app.picker, lambda: os.path.expanduser("~"), value,
                              "file", field.exts, self._changed, single_line=True)
        self.path.control.controls.append(t.icon_button("close", self._clear, "Use built-in options"))
        self.detail = t.text("", 12, t.MUTED)
        self.save_button = t.secondary_button("Save payload file" if games.tool.key == "frlg-code"
                                              else "Save gift file", self._save, "download")
        self.control = ft.Column([self.path.control, self.detail, self.save_button], spacing=10)
        self._describe(value)

    def _describe(self, path):
        try:
            self.detail.value = gift_files.read(self.games.tool, path).summary if path else ""
            self.detail.color = t.MUTED
        except (OSError, ValueError) as exc:
            self.detail.value, self.detail.color = str(exc), t.RED

    def _changed(self, path):
        self._describe(path)
        rebuild = bool(command.value_of(self.field, self.games.values)) != bool(path)
        self.games.set_value(self.field, path, rebuild=rebuild)
        if not rebuild:
            self.control.update()

    def _clear(self, e):
        self.path.field.value = ""
        self._changed("")

    async def _save(self, e):
        self.save_button.disabled = True
        self.detail.value = "Preparing gift file…"
        self.detail.color = t.MUTED
        self.control.update()
        # Capture the selected tool and settings before the user can switch views.
        tool = self.games.tool
        values, extra = dict(self.games.values), dict(self.games.extra)
        try:
            gift = await asyncio.to_thread(gift_files.build, tool, values, extra, self.games.app.settings)
            path = await self.games.app.picker.save_file(
                dialog_title="Save Mystery Gift", file_name=f"{tool.key}.pokegift",
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=[gifts.EXTENSION])
            if path:
                if not path.lower().endswith(".pokegift"):
                    path += ".pokegift"
                gifts.save(path, gift)
                self.detail.value = f"Saved {path}"
            else:
                self._describe(command.value_of(self.field, values))
        except (OSError, ValueError, pokemon.BuilderError) as exc:
            self.detail.value, self.detail.color = str(exc), t.RED
        finally:
            self.save_button.disabled = False
            if self.games.tool is tool:
                self.control.update()

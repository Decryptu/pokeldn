"""A plugin's library on the Games page, under its tools: the files the player keeps there, added by a button or
a drop, renamed and deleted by the app [pokeldn.app.library, docs/plugins.md, A library]."""
import os
import threading

import flet as ft

from gui import drop, theme as t
from gui.views.panels import image
from gui.views.widgets import open_folder
from gui.localization import date_time, error_message
from pokeldn import plugins
from pokeldn.app import library, panels
from pokeldn.app.i18n import t as tr
from pokeldn.app.plugin_store import size_text


NOTE_STATES = {"ok": ("check", t.GREEN), "bad": ("warning-diamond", t.RED), "checking": ("clock", t.AMBER)}


class LibraryCard:
    def __init__(self, app, plugin: plugins.Plugin):
        self.app, self.plugin = app, plugin
        self.folder = plugins.library_path(plugin.library)
        self.listing = ft.Column(spacing=6)
        self.note = t.text("", 12, t.MUTED, visible=False)
        self.sort = panels.sort(plugin)
        self.order = ft.Row(spacing=0, tight=True)

    def control(self) -> ft.Control:
        tools = ft.Row([
            t.icon_button("plus", lambda e: self.app.page.run_task(self._pick), tr('library.add_a_file', 'Add a file')),
            t.icon_button("folder", lambda e: open_folder(str(self.folder)), tr('library.open_the_folder', 'Open the folder')),
            t.icon_button("refresh", lambda e: self.refresh(), tr('library.refresh', 'Refresh'))], spacing=0)
        self.refresh(update=False)
        self._render_order()
        where = tr('library.kept_in', 'Kept in {value0}. Removing {value1} leaves these files.',
                   value0=library.shown(self.folder), value1=self.plugin.name)
        return drop.target(t.card(tr('library.library', 'Library'), ft.Column([self.order, self.listing, self.note], spacing=8),
                                  where, trailing=tools), self._add)

    def _render_order(self) -> None:
        field, descending = self.sort.removesuffix("-desc"), self.sort.endswith("-desc")
        names = (("name", tr('library.name', 'Name')), ("date", tr('library.date', 'Date')),
                 ("size", tr('library.size', 'Size')))
        self.order.controls = [t.text(tr('library.sort_by', 'Sort by'), 12, t.FAINT), ft.Container(width=8)] + [
            ft.Container(t.text(label, 12, t.TEXT if key == field else t.MUTED, weight=ft.FontWeight.W_600),
                         padding=ft.Padding(10, 4, 10, 4), border_radius=999,
                         bgcolor=ft.Colors.with_opacity(0.14, "#FFFFFF") if key == field else None,
                         on_click=lambda e, k=key: self._order(k + ("-desc" if descending else "")))
            for key, label in names] + [
            t.icon_button("arrow-down" if descending else "arrow-up",
                          lambda e: self._order(field if descending else field + "-desc"),
                          tr('library.descending', 'Descending') if descending else tr('library.ascending', 'Ascending'))]

    def _order(self, sort: str) -> None:
        self.sort = sort
        try:
            panels.set_sort(self.plugin.id, sort)
        except OSError as error:
            self._say(error.strerror or str(error), t.RED)
        self._render_order()
        self.order.update()
        self.refresh()

    def refresh(self, update: bool = True) -> None:
        found = library.entries(self.folder, self.sort)
        self.notes = panels.load(self.plugin.id)["notes"]
        empty = tr('library.empty', 'Nothing here yet. Add a file') + (
            tr('library.drop_it_here', ' or drop it here.') if drop.AVAILABLE else ".")
        self.listing.controls = [self._row(e) for e in found] or [t.text(empty, 12, t.FAINT)]
        if update:
            self.listing.update()

    def _row(self, entry: library.Entry) -> ft.Control:
        def item(label, icon, action, color=t.MUTED):
            return ft.PopupMenuItem(ft.Row([t.pixel_icon(icon, color=color), t.text(label, 13)], spacing=10),
                                    on_click=action, height=40)
        menu = ft.PopupMenuButton(
            content=ft.Container(t.pixel_icon("more-vertical", color=t.MUTED), width=32, height=32,
                                 alignment=ft.Alignment.CENTER),
            tooltip=tr('library.more', 'More'), bgcolor=t.PANEL, menu_position=ft.PopupMenuPosition.UNDER, items=[
                item(tr('library.rename', 'Rename'), "label", lambda e, x=entry: self._rename(x)),
                item(tr('library.delete', 'Delete'), "trash", lambda e, x=entry: self._delete(x), t.RED)])
        when = date_time(entry.modified)
        note = self.notes.get(entry.name)
        lines = [t.text(entry.name, 13, weight=ft.FontWeight.W_600, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS, tooltip=entry.name),
                 t.text(f"{size_text(entry.size)} · {when}", 12, t.MUTED)]
        state = None
        if note:
            icon, color = NOTE_STATES[note["state"]]
            state = t.pixel_icon(icon, color=color, tooltip=note["text"] or None)
            if note["text"]:
                lines.append(t.text(note["text"], 12, color, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
        art = image(panels.image(self.plugin, note and note.get("image")), 36) or t.pixel_icon("file", color=t.MUTED)
        return ft.Container(ft.Row([
            art,
            ft.Column(lines, spacing=1, expand=True),
            *([state] if state else []),
            menu,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(10, 6, 4, 6), border_radius=10, border=ft.Border.all(1, t.BORDER))

    async def _pick(self) -> None:
        files = await self.app.picker.pick_files(allow_multiple=True)
        self._add([f.path for f in files or () if f.path])

    def _add(self, paths: list[str]) -> None:
        """Copies off the UI loop: a library file can be several gigabytes."""
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        self._say(tr('library.copying', 'Copying {value0} into the library...', value0=", ".join(map(os.path.basename, paths))),
                  t.BLUE)

        def work():
            errors = []
            for path in paths:
                try:
                    library.add(self.folder, path)
                except OSError as error:
                    errors.append(f"{os.path.basename(path)}: {error.strerror or error}")

            def done():
                self._say(" ".join(errors) if errors else tr('library.added', 'Added.'), t.RED if errors else t.MUTED)
                self.refresh()
            self.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

    def _rename(self, entry: library.Entry) -> None:
        box = t.field(value=entry.name, autofocus=True, width=360)
        error = t.text("", 12, t.RED, visible=False)

        def done(e):
            try:
                library.rename(self.folder, entry, box.value or "")
            except (OSError, ValueError) as problem:
                error.value, error.visible = error_message(problem), True
                error.update()
                return
            self.app.page.pop_dialog()
            self.refresh()

        box.on_submit = done
        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('library.rename_the_file', 'Rename the file'), 18),
            content=ft.Column([box, error], spacing=8, tight=True),
            actions=[t.secondary_button(tr('library.cancel', 'Cancel'), lambda e: self.app.page.pop_dialog()),
                     t.button(tr('library.rename', 'Rename'), done)]))

    def _delete(self, entry: library.Entry) -> None:
        def done(e):
            self.app.page.pop_dialog()
            try:
                library.delete(self.folder, entry)
            except (OSError, ValueError) as problem:
                self._say(error_message(problem), t.RED)
            self.refresh()

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('library.delete_this_file', 'Delete this file?'), 18),
            content=t.text(tr('library.is_deleted', '{value0} ({value1}) is deleted from this computer.',
                              value0=entry.name, value1=size_text(entry.size)), 13, t.MUTED, width=380),
            actions=[t.secondary_button(tr('library.cancel', 'Cancel'), lambda e: self.app.page.pop_dialog()),
                     t.button(tr('library.delete', 'Delete'), done, "trash", color=t.RED)]))

    def _say(self, text: str, color: str) -> None:
        self.note.value, self.note.color, self.note.visible = text, color, bool(text)
        self.note.update()

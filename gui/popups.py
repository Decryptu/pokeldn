"""The programs' pop-ups as dialogs over whatever page the app shows (pokeldn.app.popups, docs/gui.md, Pop-ups)."""

import flet as ft

from gui import theme as t
from gui.localization import translate

TONES = {"info": ("circle-info", t.BLUE), "warning": ("warning-diamond", t.AMBER),
         "error": ("warning-diamond", t.RED)}


class Dialogs:
    """The manager's view. An app dialog's `page.pop_dialog()` closes that dialog, the top one of the app's own,
    never a pop-up that opened above it since."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.shown: dict = {}     # entry -> its dialog, while it shows
        # Not a Flet property: object.__setattr__ keeps it out of the page's changes sent to the client.
        object.__setattr__(page, "pop_dialog", self.pop_app_dialog)

    def show(self, entry) -> None:
        dialog = t.dialog(modal=False)
        dialog.on_dismiss = lambda e: self._escaped(dialog)
        self._fill(dialog, entry)
        self.page.show_dialog(dialog)

    def _escaped(self, dialog) -> None:
        # Flet reports every close; one the manager made has left `shown` already.
        entry = next((e for e, d in self.shown.items() if d is dialog), None)
        if entry is not None:
            entry.escaped()

    def refresh(self, old, entry) -> None:
        dialog = self.shown.pop(old)
        self._fill(dialog, entry)
        dialog.update()

    def hide(self, entry) -> None:
        dialog = self.shown.pop(entry, None)
        # One Esc closed has left the page's dialogs already.
        if dialog is not None and dialog.open and dialog in self.page._dialogs.controls:
            dialog.open = False
            dialog.update()

    def pop_app_dialog(self):
        """Flet's Page.pop_dialog, past the pop-ups."""
        mine = set(map(id, self.shown.values()))
        dialog = next((d for d in reversed(self.page._dialogs.controls) if d.open and id(d) not in mine), None)
        if dialog is not None:
            dialog.open = False
            dialog.update()
        return dialog

    def _fill(self, dialog: ft.AlertDialog, entry) -> None:
        self.shown[entry] = dialog
        icon, color = TONES[entry.tone]
        header = [t.text(translate(entry.title), 17, weight=ft.FontWeight.W_600)]
        if entry.source:
            header.insert(0, t.text(translate(entry.source), 12, t.FAINT))
        dialog.semantics_label = translate(entry.title)
        dialog.title = ft.Row([t.pixel_icon(icon, color=color),
                               ft.Column(header, spacing=2, tight=True, expand=True)], spacing=10)
        def press(answer):
            return lambda e: entry.press(answer)
        body = [t.text(translate(entry.text), 13, t.MUTED, selectable=True)] if entry.text else []
        # A choice's options weigh the same: one unfilled button each, full width, in the program's order.
        body += [t.secondary_button(translate(option), press(str(i))) for i, option in enumerate(entry.options)]
        if len(body) > 1:
            body = [ft.Column(body, spacing=8, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)]
        dialog.content = ft.Container(body[0], width=460) if body else None
        # Esc and a click outside answer Dismiss; a button for it would sit beside disagree.
        dialog.actions = ([t.button(translate(entry.label), press("ack"))] if entry.kind == "ack" else
                          [t.secondary_button(translate(entry.disagree), press("disagree")),
                           t.button(translate(entry.agree), press("agree"))] if entry.kind == "confirm" else [])

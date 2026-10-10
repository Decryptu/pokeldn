"""The Tera Raid host's Raid event card: the app's copy of the EventsGallery's raid events
(pokeldn.app.events_gallery), downloaded, checked and updated; the event the raid comes from,
searchable by its name or its bosses'; and the override for a boss a save catches once."""

import threading
import time

import flet as ft

from gui import theme as t
from gui.views.widgets import Check, PixelActivity
from pokeldn.app import events_gallery as gallery
from pokeldn.sv import raid_event

NONE = "-"
NO_EVENT = "No event, a standard raid · type an event or a Pokemon to search"
ORDER = "#raid-event-order"       # "newest" (the default) or "oldest", kept with the tool's values
FOLDED = "#raid-event-folded"     # the chosen event while the card is folded, set aside until unfolded
CATCH = "--raid-catch-normal"


def day(date: str) -> str:
    when = gallery.date_of(date)
    return when.strftime("%d %b %Y").lstrip("0") if when else "an unknown date"


class RaidEventPicker:
    """`view` is the GamesView: it keeps the card open across redraws, holds the values and
    narrows the raid card to the chosen event."""

    def __init__(self, view, field):
        self.view, self.app, self.field = view, view.app, field
        self.stop = threading.Event()
        self.events = None          # the gallery's index, once listed
        self.chevron = t.pixel_icon("chevron-down" if view.raid_event_open else "chevron-right", color=t.FAINT)
        key = view.values.get(field.key) or ""
        folded = "" if key else view.values.get(FOLDED) or ""
        # An event the gallery lacks (never downloaded, or updated without it) stays chosen, for the
        # gallery to come back; the run refuses it (pokeldn.app.command.code_error).
        missing = bool(key) and not gallery.holds(key)
        if missing:
            summary, tip = (f"Missing: {gallery.title(key)}",
                            "Not in the event gallery: download or update it, or choose another event")
        elif key:
            summary, tip = gallery.title(key), "Fold to set the event aside and host a standard raid"
        elif folded:
            summary, tip = f"Off: {gallery.title(folded)}", "Unfold to raid the event again"
        else:
            summary, tip = "None, a standard raid", "Show or hide the event raids"
        self.summary = t.text(summary, 12, t.RED if missing else t.BLUE if key else t.MUTED, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS)
        header = ft.Container(ft.Row([
            self.chevron, t.text(field.label, 13, weight=ft.FontWeight.W_600),
            ft.Container(self.summary, expand=True, alignment=ft.Alignment.CENTER_RIGHT),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), on_click=self._toggle, tooltip=tip)
        self.busy = ft.Container(PixelActivity("Working"), visible=False)
        self.status = t.text("", 12, t.MUTED, expand=True)
        self.actions = ft.Row([], spacing=8, tight=True)
        self.bar = ft.ProgressBar(value=None, color=t.BLUE, bgcolor=t.FIELD, height=4, border_radius=2,
                                  visible=False)
        self.dropdown = t.dropdown([], None, on_select=self._picked, enable_filter=True, editable=True,
                                   menu_height=360, hint_text="Looking for the event gallery...", disabled=True)
        self.order = t.icon_button(self._order_icon(), self._turn, self._order_tip())
        self.catch = ft.Column([], spacing=4, visible=False)
        self.body = ft.Column([
            t.text(field.help, 12, t.MUTED),
            ft.Row([self.busy, self.status, self.actions], spacing=8,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.bar,
            ft.Row([self.dropdown, self.order], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.catch,
        ], spacing=10, visible=view.raid_event_open)
        self.control = t.surface(ft.Container(ft.Column([header, self.body], spacing=10, tight=True), padding=16))
        self._show_catch()
        if view.raid_event_open:
            self._refresh(update=False)

    # Opening

    def _toggle(self, _e) -> None:
        self.view.show_raid_event(not self.view.raid_event_open)

    def _working(self, text: str, bar: bool = False) -> None:
        self.status.value, self.status.color = text, t.MUTED
        self.busy.visible, self.bar.visible, self.bar.value = True, bar, None
        self.actions.controls = []

    def _background(self, work, then) -> None:
        """Runs work() on a thread, then then(result, error) on the page, error "" or why it failed."""
        def run():
            try:
                result, error = work(), ""
            except Exception as exc:
                result, error = None, str(exc)
            self.app.ui(lambda: then(result, error))
        threading.Thread(target=run, daemon=True).start()

    def _refresh(self, update: bool = True) -> None:
        """Looks for the gallery, then lists its events."""
        self._working("Looking for the event gallery...")
        if update:
            self.control.update()
        self._background(gallery.state, self._show_state)

    def _show_state(self, found, error: str) -> None:
        self.busy.visible = self.bar.visible = False
        if error:
            self._failed(error, self._refresh)
            return
        if not found.present:
            self.status.value = "The event gallery is not downloaded yet."
            self.actions.controls = [t.button("Download", self._download, "download")]
            self.dropdown.hint_text, self.dropdown.disabled = "Download the event gallery first", True
            self.dropdown.options, self.dropdown.value = [], None
            self.control.update()
            return
        self.status.value = f"Event gallery of {day(found.date)}"
        self.actions.controls = [t.secondary_button("Check for updates", self._check, "refresh")]
        self.control.update()
        self._background(gallery.index, self._fill)

    # The events

    def _fill(self, events, error: str) -> None:
        if error:
            self.dropdown.hint_text = f"The events could not be read: {error}"
            self.dropdown.update()
            return
        self.events = events
        newest = self.view.values.get(ORDER, "newest") != "oldest"
        options = [ft.DropdownOption(key=NONE, text="No event, a standard raid")]
        for entry in (reversed(events) if newest else events):
            species = ", ".join(entry.species)
            options.append(ft.DropdownOption(key=entry.key, text=f"{entry.title} · {species}", content=ft.Column([
                t.text(entry.title, 13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                t.text(species, 11, t.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=0, tight=True)))
        key = self.view.values.get(self.field.key) or ""
        known = {e.key for e in events}
        self.dropdown.options = options
        # No event leaves the field empty under its hint, so a search is typed straight in.
        self.dropdown.value = key if key in known else None
        self.dropdown.hint_text = NO_EVENT
        self.dropdown.disabled = False
        if key and key not in known:
            self.status.value, self.status.color = "The chosen event is not in this gallery.", t.RED
        self.control.update()

    def _picked(self, e) -> None:
        key = "" if e.control.value in (None, NONE) else e.control.value
        if key == (self.view.values.get(self.field.key) or ""):
            if e.control.value == NONE:         # back to the empty field under its hint
                self.dropdown.value = None
                self.dropdown.update()
            return
        self.view.values.pop(CATCH, None)       # another event: the catch-once override starts unchecked
        self.view.set_value(self.field, key, rebuild=True)

    def _order_icon(self) -> str:
        return "arrow-up" if self.view.values.get(ORDER) == "oldest" else "arrow-down"

    def _order_tip(self) -> str:
        return ("Oldest first; show the newest first" if self.view.values.get(ORDER) == "oldest"
                else "Newest first; show the oldest first")

    def _turn(self, _e) -> None:
        self.view.values[ORDER] = "newest" if self.view.values.get(ORDER) == "oldest" else "oldest"
        self.app.settings.save()
        self.order.icon.src = f"icons/{self._order_icon()}.svg"
        self.order.tooltip = self._order_tip()
        if self.events is not None:
            self._fill(self.events, "")
        self.order.update()

    def _show_catch(self) -> None:
        """The override under the event, for an event whose bosses a save catches once."""
        event = self.view.raid_event()
        names = raid_event.catch_once(event) if event is not None else []
        self.catch.visible = bool(names)
        if not names:
            return
        field = next(f for f in self.view.tool.fields if f.key == CATCH)
        box = Check("Let it be caught again", value=bool(self.view.values.get(CATCH)), size=13,
                    on_change=lambda on: self.view.set_value(field, on, rebuild=True))
        who = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
        self.catch.controls = [box.control, t.text(
            f"A save can catch {who} only once. Checked, a save that already caught it can catch it "
            "again, and the Pokemon caught is as legal as the first.", 12, t.MUTED)]

    # Download, check, update

    def _download(self, _e) -> None:
        self._run(lambda progress: gallery.download(progress=progress, cancelled=self.stop.is_set),
                  "Downloading the event gallery...")

    def _update(self, _e) -> None:
        self._run(lambda progress: gallery.download(progress=progress, cancelled=self.stop.is_set),
                  "Updating the event gallery...")

    def _run(self, job, text: str) -> None:
        self.stop.clear()
        self._working(text, bar=True)
        self.actions.controls = [t.secondary_button("Cancel", lambda _e: self.stop.set())]
        self.control.update()
        shown = [0.0]

        def progress(what: str, done: int, total: int) -> None:
            now = time.monotonic()
            if now - shown[0] < 0.2 and done != total:
                return
            shown[0] = now
            mb = 1 << 20

            def show():
                self.status.value = (f"{what} {done / mb:.0f} of {total / mb:.0f} MB" if total else
                                     f"{what} {done / mb:.0f} MB" if done else what)
                self.bar.value = done / total if total else None
                self.status.update()
                self.bar.update()
            self.app.ui(show)

        def work():
            try:
                job(progress)
                error = ""
            except Exception as exc:
                error = "Cancelled." if self.stop.is_set() else (str(exc) or type(exc).__name__)

            def done():
                if error:
                    self._failed(error, self._refresh)
                else:
                    self.view.gallery_changed()
            self.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

    def _check(self, _e) -> None:
        self._working("Checking for updates...")
        self.control.update()
        self._background(gallery.check, self._checked)

    def _checked(self, found, error: str) -> None:
        self.busy.visible = False
        if error:
            self._failed(error, lambda: self._check(None))
            return
        if found.available:
            self.status.value = f"An update of {day(found.date)} is available."
            self.actions.controls = [t.button("Update", self._update, "download")]
        else:
            self.status.value = f"Up to date: the newest raid event change is of {day(found.date)}."
            self.actions.controls = [t.secondary_button("Check again", self._check, "refresh")]
        self.control.update()

    def _failed(self, error: str, retry) -> None:
        self.busy.visible = self.bar.visible = False
        self.status.value, self.status.color = f"{error[:1].upper()}{error[1:]}", t.RED
        self.actions.controls = [t.secondary_button("Try again", lambda _e: retry())]
        self.control.update()

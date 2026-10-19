"""The Tera Raid host's Raid event card: the app's copy of the EventsGallery's raid events
(pokeldn.app.events_gallery), downloaded, checked and updated; the event the raid comes from,
searchable by its name or its bosses'; and the override for a boss a save catches once."""
from pokeldn.app.i18n import t as tr

import threading
import time

import flet as ft

from gui import theme as t
from gui.views.widgets import Check, PixelActivity
from gui.localization import error_message, translate
from pokeldn.app import events_gallery as gallery
from pokeldn.sv import raid_event

NONE = "-"
NO_EVENT = tr('raid_event.no_event_a_standard_raid_type_an_event_or_a_pokemon_to__22d3fd', 'No event, a standard raid · type an event or a Pokemon to search')
ORDER = "#raid-event-order"       # "newest" (the default) or "oldest", kept with the tool's values
FOLDED = "#raid-event-folded"     # the chosen event while the card is folded, set aside until unfolded
CATCH = "--raid-catch-normal"


def day(date: str) -> str:
    when = gallery.date_of(date)
    return when.strftime(tr('raid_event.d_b_y_ede2cc', '%d %b %Y')).lstrip("0") if when else tr('raid_event.an_unknown_date_df0e68', 'an unknown date')


class RaidEventPicker:
    """`view` is the GamesView: it keeps the card open across redraws, holds the values and
    narrows the raid card to the chosen event."""

    def __init__(self, view, field):
        self.view, self.app, self.field = view, view.app, field
        self.game = getattr(getattr(view, "game", None), "key", "sv")
        self.stop = threading.Event()
        self.events = None          # the gallery's index, once listed
        self.chevron = t.pixel_icon("chevron-down" if view.raid_event_open else "chevron-right", color=t.FAINT)
        key = view.values.get(field.key) or ""
        folded = "" if key else view.values.get(FOLDED) or ""
        # An event the gallery lacks (never downloaded, or updated without it) stays chosen, for the
        # gallery to come back; the run refuses it (pokeldn.app.command.code_error).
        missing = bool(key) and not gallery.holds(key, game=self.game)
        if missing:
            summary, tip = (tr('raid_event.missing_0d71ec', 'Missing: {value0}', value0=translate(gallery.title(key, game=self.game))),
                            tr('raid_event.not_in_the_event_gallery_download_or_update_it_or_choos_8b8767', 'Not in the event gallery: download or update it, or choose another event'))
        elif key:
            summary, tip = translate(gallery.title(key, game=self.game)), tr('raid_event.fold_to_set_the_event_aside_and_host_a_standard_raid_c8854c', 'Fold to set the event aside and host a standard raid')
        elif folded:
            summary, tip = tr('raid_event.off_d2834c', 'Off: {value0}', value0=translate(gallery.title(folded, game=self.game))), tr('raid_event.unfold_to_raid_the_event_again_2db3e3', 'Unfold to raid the event again')
        else:
            summary, tip = tr('raid_event.none_a_standard_raid_23a8c4', 'None, a standard raid'), tr('raid_event.show_or_hide_the_event_raids_19f0b5', 'Show or hide the event raids')
        self.summary = t.text(summary, 12, t.RED if missing else t.BLUE if key else t.MUTED, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS)
        header = ft.Container(ft.Row([
            self.chevron, t.text(field.label, 13, weight=ft.FontWeight.W_600),
            ft.Container(self.summary, expand=True, alignment=ft.Alignment.CENTER_RIGHT),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), on_click=self._toggle, tooltip=tip)
        self.busy = ft.Container(PixelActivity(tr('raid_event.working_a92f04', 'Working')), visible=False)
        self.status = t.text("", 12, t.MUTED, expand=True)
        self.actions = ft.Row([], spacing=8, tight=True)
        self.bar = ft.ProgressBar(value=None, color=t.BLUE, bgcolor=t.FIELD, height=4, border_radius=2,
                                  visible=False)
        self.dropdown = t.dropdown([], None, on_select=self._picked, enable_filter=True, editable=True,
                                   menu_height=360, hint_text=tr('raid_event.looking_for_the_event_gallery_d438b4', 'Looking for the event gallery...'), disabled=True)
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
        self._working(tr('raid_event.looking_for_the_event_gallery_d438b4', 'Looking for the event gallery...'))
        if update:
            self.control.update()
        self._background(lambda: gallery.state(game=self.game), self._show_state)

    def _show_state(self, found, error: str) -> None:
        self.busy.visible = self.bar.visible = False
        if error:
            self._failed(error, self._refresh)
            return
        if not found.present:
            self.status.value = tr('raid_event.the_event_gallery_is_not_downloaded_yet_2acdb1', 'The event gallery is not downloaded yet.')
            self.actions.controls = [t.button(tr('raid_event.download_d6eafe', 'Download'), self._download, "download")]
            self.dropdown.hint_text, self.dropdown.disabled = tr('raid_event.download_the_event_gallery_first_573c61', 'Download the event gallery first'), True
            self.dropdown.options, self.dropdown.value = [], None
            self.control.update()
            return
        self.status.value = tr('raid_event.event_gallery_of_7d0c46', 'Event gallery of {value0}', value0=day(found.date))
        self.actions.controls = [t.secondary_button(tr('raid_event.check_for_updates_f26f32', 'Check for updates'), self._check, "refresh")]
        self.control.update()
        self._background(lambda: gallery.index(game=self.game), self._fill)

    # The events

    def _fill(self, events, error: str) -> None:
        if error:
            self.dropdown.hint_text = tr('raid_event.the_events_could_not_be_read_523a5c', 'The events could not be read: {value0}', value0=error_message(error))
            self.dropdown.update()
            return
        self.events = events
        newest = self.view.values.get(ORDER, "newest") != "oldest"
        options = [ft.DropdownOption(key=NONE, text=tr('raid_event.no_event_a_standard_raid_562e51', 'No event, a standard raid'))]
        for entry in (reversed(events) if newest else events):
            species = tr("presentation.list_separator", ", ").join(translate(name) for name in entry.species)
            title = translate(entry.title)
            options.append(ft.DropdownOption(key=entry.key, text=tr('raid_event._75414c', '{value0} · {value1}', value0=title, value1=species), content=ft.Column([
                t.text(title, 13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
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
            self.status.value, self.status.color = tr('raid_event.the_chosen_event_is_not_in_this_gallery_eb29c7', 'The chosen event is not in this gallery.'), t.RED
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
        return (tr('raid_event.oldest_first_show_the_newest_first_20ac51', 'Oldest first; show the newest first') if self.view.values.get(ORDER) == "oldest"
                else tr('raid_event.newest_first_show_the_oldest_first_2cb69f', 'Newest first; show the oldest first'))

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
        event = self.view.raid_event() if self.game == "sv" else None
        names = [translate(name) for name in raid_event.catch_once(event)] if event is not None else []
        self.catch.visible = bool(names)
        if not names:
            return
        field = next(f for f in self.view.tool.fields if f.key == CATCH)
        box = Check(tr('raid_event.let_it_be_caught_again_15aa86', 'Let it be caught again'), value=bool(self.view.values.get(CATCH)), size=13,
                    on_change=lambda on: self.view.set_value(field, on, rebuild=True))
        who = (tr('raid_event.names_and', '{value0} and {value1}', value0=", ".join(names[:-1]), value1=names[-1])
               if len(names) > 1 else "".join(names))
        self.catch.controls = [box.control, t.text(
            tr('raid_event.a_save_can_catch_only_once_checked_a_save_that_already__1b48ec', 'A save can catch {value0} only once. Checked, a save that already caught it can catch it again, and the Pokemon caught is as legal as the first.', value0=who), 12, t.MUTED)]

    # Download, check, update

    def _download(self, _e) -> None:
        self._run(lambda progress: gallery.download(progress=progress, cancelled=self.stop.is_set, game=self.game),
                  tr('raid_event.downloading_the_event_gallery_17c46e', 'Downloading the event gallery...'))

    def _update(self, _e) -> None:
        self._run(lambda progress: gallery.download(progress=progress, cancelled=self.stop.is_set, game=self.game),
                  tr('raid_event.updating_the_event_gallery_575a75', 'Updating the event gallery...'))

    def _run(self, job, text: str) -> None:
        self.stop.clear()
        self._working(text, bar=True)
        self.actions.controls = [t.secondary_button(tr('raid_event.cancel_19766e', 'Cancel'), lambda _e: self.stop.set())]
        self.control.update()
        shown = [0.0]

        def progress(what: str, done: int, total: int) -> None:
            now = time.monotonic()
            if now - shown[0] < 0.2 and done != total:
                return
            shown[0] = now
            mb = 1 << 20

            def show():
                self.status.value = (tr('raid_event.of_mb_b97c07', '{value0} {value1:.0f} of {value2:.0f} MB', value0=translate(what), value1=done / mb, value2=total / mb) if total else
                                     tr('raid_event.mb_ad7a1d', '{value0} {value1:.0f} MB', value0=translate(what), value1=done / mb) if done else translate(what))
                self.bar.value = done / total if total else None
                self.status.update()
                self.bar.update()
            self.app.ui(show)

        def work():
            try:
                job(progress)
                error = ""
            except Exception as exc:
                error = tr('raid_event.cancelled_4b5ea0', 'Cancelled.') if self.stop.is_set() else (str(exc) or type(exc).__name__)

            def done():
                if error:
                    self._failed(error, self._refresh)
                else:
                    self.view.gallery_changed()
            self.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

    def _check(self, _e) -> None:
        self._working(tr('raid_event.checking_for_updates_8bcaee', 'Checking for updates...'))
        self.control.update()
        self._background(lambda: gallery.check(game=self.game), self._checked)

    def _checked(self, found, error: str) -> None:
        self.busy.visible = False
        if error:
            self._failed(error, lambda: self._check(None))
            return
        if found.available:
            self.status.value = tr('raid_event.an_update_of_is_available_365d4a', 'An update of {value0} is available.', value0=day(found.date))
            self.actions.controls = [t.button(tr('raid_event.update_c1c100', 'Update'), self._update, "download")]
        else:
            self.status.value = tr('raid_event.up_to_date_the_newest_raid_event_change_is_of_1ada15', 'Up to date: the newest raid event change is of {value0}.', value0=day(found.date))
            self.actions.controls = [t.secondary_button(tr('raid_event.check_again_fb7099', 'Check again'), self._check, "refresh")]
        self.control.update()

    def _failed(self, error: str, retry) -> None:
        self.busy.visible = self.bar.visible = False
        message = error_message(error)
        self.status.value, self.status.color = f"{message[:1].upper()}{message[1:]}", t.RED
        self.actions.controls = [t.secondary_button(tr('raid_event.try_again_d8b839', 'Try again'), lambda _e: retry())]
        self.control.update()

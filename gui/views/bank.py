from pokeldn.app import i18n
"""The bank: every Pokemon a trade brought in, and the way to trade one into another game
[pokeldn.app.bank, docs/gui.md, The bank]."""
from pokeldn.app.i18n import ref as _ref
from pokeldn.app.i18n import text as tr, ref
import os
import threading

import flet as ft

from gui import drop, theme as t
from gui.views.games import tool_role
from gui.views.sprites import MINI, SIZE, Sprite
from gui.views.widgets import open_folder
from gui.localization import SERVICE, date_time, display_summary, summary_lines, summary_text, translate
from pokeldn import pokemon
from pokeldn.app import bank
from pokeldn.app.settings import GEN3
from pokeldn.app.catalog import GAMES

NAMES = {game.key: game.name for game in GAMES}
ALL = "all"


def trade_tools(game_key: str) -> list:
    """(tool, its offer field) for each trade tool of a game."""
    game = next(g for g in GAMES if g.key == game_key)
    return [(tool, field) for tool in game.tools if not tool.unavailable
            for field in tool.fields if field.kind == "pokemon" and field.queue > 1]


def game_icon(key: str, size: int = 20) -> ft.Control:
    return ft.Image(src=f"games/{key}.png", width=size, height=size, fit=ft.BoxFit.CONTAIN,
                    filter_quality=ft.FilterQuality.NONE, semantics_label=NAMES.get(key, key))


class BankView:
    def __init__(self, app):
        self.app = app
        self.visible = False
        self.shown = ALL                  # the game whose Pokemon the grid shows
        self.items: list[bank.Entry] = []
        self.selected: str = ""           # an Entry.id
        self.target: str = ""             # the game chosen to send the selected Pokemon to
        self.routes: dict[str, dict] = {}   # Entry.id -> pokemon.Service.destinations
        self.working = False
        self.boxes = ft.ListView(spacing=2, padding=ft.Padding(8, 8, 8, 8), expand=True)
        self.grid = ft.Row(spacing=8, run_spacing=8, wrap=True)
        self.heading = t.text("", 12, t.MUTED)
        self.detail = ft.Column(spacing=24, scroll=ft.ScrollMode.AUTO, expand=True)
        self.note = t.text("", 12, t.MUTED)
        self.panes = t.Panes(
            (tr('core.bank.pane_boxes'), "archive", t.panel(ft.Column([
                t.panel_header(tr('core.bank.bank_676c47'),
                               t.icon_button("plus", self._pick, tr('core.bank.import_a_pokemon_file_or_a_game_save_da7f8c')),
                               t.icon_button("folder", lambda e: open_folder(str(self._folder())),
                                             tr('core.bank.open_the_bank_folder_438a67')),
                               t.icon_button("refresh", lambda e: self.refresh(), tr('core.bank.refresh_0e9161'))),
                t.fade(self.boxes),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH)),
            (tr('core.bank.pane_box'), "package", drop.target(ft.Container(t.fade(ft.ListView(
                [ft.Container(self.heading, padding=ft.Padding(4, 14, 4, 0)), self.grid],
                spacing=12, padding=ft.Padding(0, 0, 0, 24), expand=True)), expand=True, border_radius=16),
                self._import, expand=True)),
            (tr('core.bank.pane_pokemon'), "user", t.panel(ft.Column([
                t.panel_header(tr('core.bank.pokemon_224642')),
                ft.Container(ft.Column([self.detail, self.note], spacing=8, expand=True),
                             padding=ft.Padding(18, 8, 18, 18), expand=True),
            ], spacing=0, expand=True), width=t.SESSION_WIDTH)))
        self.control = self.panes.control
        self.panes.show(1, update=False)   # a phone opens on the box itself

    def enter(self, **_) -> None:
        self.visible = True
        self.routes.clear()     # the HOME tracker setting may have changed what a move gives
        self.refresh(update=False)
        if entry := self._entry():
            threading.Thread(target=self._find_routes, args=(entry,), daemon=True).start()

    def leave(self) -> None:
        self.visible = False

    @staticmethod
    def _folder():
        folder = bank.library()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    # The listing

    def refresh(self, update: bool = True) -> None:
        bank.prune(self.app.settings)
        self.items = bank.entries()
        if self.selected not in {e.id for e in self.items}:
            self.selected, self.target = "", ""
        self.render_boxes()
        self.render_grid()
        self.render_detail()
        if update:
            self.control.update()

    def render_boxes(self) -> None:
        counts = {key: sum(e.game == key for e in self.items) for key in NAMES}
        rows = [self._box(ALL, tr('core.bank.all_pokemon_fe268d'), len(self.items), t.pixel_icon("package", color=t.MUTED))]
        rows += [self._box(key, NAMES[key], counts[key], game_icon(key, 28)) for key in NAMES if counts[key]]
        self.boxes.controls = rows

    def _box(self, key: str, label: str, count: int, icon: ft.Control) -> ft.Control:
        active = key == self.shown
        return ft.Container(ft.Row([
            ft.Container(icon, width=32, alignment=ft.Alignment.CENTER),
            t.text(label, 13, t.TEXT if active else t.SOFT, weight=ft.FontWeight.W_600, expand=True),
            t.text(str(count), 12, t.MUTED),
        ], spacing=10), padding=ft.Padding(8, 8, 10, 8), border_radius=12,
            bgcolor=t.SELECTED if active else None, on_click=lambda e, k=key: self._show(k))

    def _show(self, key: str) -> None:
        self.shown = key
        self.render_boxes()
        self.render_grid()
        self.control.update()

    def render_grid(self) -> None:
        shown = [e for e in self.items if self.shown in (ALL, e.game)]
        where = tr('core.bank.in_the_bank_f69744') if self.shown == ALL else tr('core.bank.from_7f2df4', value0=NAMES[self.shown])
        self.heading.value = (tr('core.bank.pokemon_3a4d02', value0=len(shown), value1=where) if shown else
                              tr('core.bank.the_bank_is_empty_every_pokemon_a_trade_brings_in_lands_e05ff4')
                              + (tr('core.bank.drop_a_pokemon_file_or_a_game_save_here_to_import_what__7adc95')
                                 if drop.AVAILABLE else ""))
        self.grid.controls = [self._tile(e) for e in shown]

    def _tile(self, entry: bank.Entry) -> ft.Control:
        sprite = Sprite(self.app, entry.species_id, entry.shiny, size=MINI)
        active = entry.id == self.selected
        queued = bool(bank.queued(self.app.settings, entry.id))
        return ft.Container(ft.Stack([
            sprite.control,
            ft.Container(game_icon(entry.game, 16), right=0, bottom=0),
            ft.Container(t.pixel_icon("arrows-horizontal", size=12, color=t.BLUE), left=2, top=2,
                         visible=queued),
        ]), padding=4, border_radius=14, tooltip=display_summary(entry),
            border=ft.Border.all(2, t.BLUE if active else ft.Colors.TRANSPARENT),
            on_click=lambda e, i=entry.id: self.select(i))

    # The selected Pokemon

    def select(self, entry_id: str) -> None:
        self.selected, self.target = entry_id, ""
        self.note.value = ""
        self.render_grid()
        self.render_detail()
        self.control.update()
        entry = self._entry()
        if entry and entry.id not in self.routes:
            threading.Thread(target=self._find_routes, args=(entry,), daemon=True).start()

    def _entry(self) -> bank.Entry | None:
        return next((e for e in self.items if e.id == self.selected), None)

    def _find_routes(self, entry: bank.Entry) -> None:
        trainer = self.app.settings.trainer(entry.game)
        try:
            routes = bank.destinations(entry, trainer, service=SERVICE)
        except (OSError, pokemon.BuilderError) as error:
            routes = {key: {"ok": key == entry.game, "reason": str(error)} for key in NAMES}

        def done():
            self.routes[entry.id] = routes
            if self.visible and self.selected == entry.id:
                self.render_detail()
                self.detail.update()
        self.app.ui(done)

    def render_detail(self) -> None:
        entry = self._entry()
        if entry is None:
            self.detail.controls = [t.text(tr('core.bank.pick_a_pokemon_to_see_where_it_can_go_3b278b'), 13, t.MUTED)]
            return
        head, rest = summary_lines(display_summary(entry))
        about = ft.Column([
            t.text(head, 15, weight=ft.FontWeight.W_600),
            t.text(rest, 12, t.MUTED),
            ft.Row([game_icon(entry.game), t.text(tr('core.bank.in_bb2233', value0=NAMES[entry.game]), 12, t.SOFT)], spacing=6),
            t.text(tr('core.bank.banked_faf7b7', value0=date_time(entry.created)), 12, t.FAINT),
            t.badge(tr('core.bank.legal_4787ea'), t.GREEN, "checkbox-on") if entry.legal else
            t.badge(tr('core.bank.pkhex_finds_it_not_legal_58cc49'), t.AMBER, "warning-diamond"),
            *([t.badge(translate(warning), t.AMBER, "warning-diamond")]
              if (warning := pokemon.HOME_TRACKER_WARNINGS.get(entry.home_tracker)) else []),
        ], spacing=4, expand=True)
        controls = [ft.Row([Sprite(self.app, entry.species_id, entry.shiny, size=SIZE).control, about],
                           spacing=14, vertical_alignment=ft.CrossAxisAlignment.START)]
        queued = bank.queued(self.app.settings, entry.id)
        if queued:
            tools = {tool.key: tr('core.bank._54ef3b', value0=NAMES[g.key], value1=tool.name) for g in GAMES for tool in g.tools}
            controls.append(t.section(tr('core.bank.waiting_to_trade_4a46c7'), ft.Column([
                t.text(tr('core.bank.queued_in_it_leaves_the_bank_when_that_trade_completes_e6f058', value0=', '.join((tools.get(k, k) for k in queued))), 12, t.MUTED),
                ft.Row([t.secondary_button(tr('core.bank.open_the_trade_fdac5d'), lambda e: self._open(queued[0]), "play"),
                        t.secondary_button(tr('core.bank.take_it_out_5a1e31'), lambda e: self._dequeue(entry), "close")],
                       spacing=8, wrap=True),
            ], spacing=10)))
        else:
            controls.append(t.section(tr('core.bank.send_it_to_a_game_da82fb'), self._routes(entry)))
        controls.append(ft.Row([
            *([] if queued else [t.secondary_button(tr('core.bank.edit_464c4f'), lambda e: self._edit(entry), "edit")]),
            t.secondary_button(tr('core.bank.export_366489'), lambda e: self.app.page.run_task(self._export, entry), "upload"),
            t.secondary_button(tr('core.bank.remove_c3812f'), lambda e: self._remove(entry), "trash"),
        ], spacing=8, wrap=True))
        self.detail.controls = controls

    def _routes(self, entry: bank.Entry) -> ft.Control:
        routes = self.routes.get(entry.id)
        if routes is None:
            return t.badge(tr('core.bank.pkhex_is_checking_each_game_8c9f63'), t.BLUE, "refresh")
        rows = []
        for key in NAMES:
            route = routes.get(key, {"ok": False, "reason": ""})
            ok, chosen = route["ok"], key == self.target
            lines = translate(route["reason"]).split("\n")
            warning = pokemon.HOME_TRACKER_WARNINGS.get(route.get("home_tracker", "")) if ok else None
            why = lines[0] + (tr('core.bank.more_86f3b0', value0=len(lines) - 1) if len(lines) > 1 else "") if not ok else (
                tr('core.bank.its_own_game_6e5aee') if key == entry.game else translate(warning) if warning else tr('core.bank.moves_as_home_would_move_it_5731e1'))
            rows.append(ft.Container(ft.Row([
                game_icon(key, 24),
                ft.Column([t.text(NAMES[key], 13, t.TEXT if ok else t.FAINT, weight=ft.FontWeight.W_600),
                           t.text(why, 11, t.AMBER if warning else t.MUTED if ok else t.FAINT, max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS)], spacing=0, expand=True),
                t.pixel_icon("chevron-right", color=t.BLUE) if chosen else ft.Container(),
            ], spacing=10), padding=ft.Padding(8, 6, 8, 6), border_radius=10,
                bgcolor=t.SELECTED if chosen else None, tooltip=None if ok else route["reason"],
                on_click=(lambda e, k=key: self._choose(k)) if ok else None))
        body = [ft.Column(rows, spacing=2)]
        if self.target:
            buttons = [t.button(tool.name, lambda e, x=tool, f=field: self._send(entry, x, f),
                                "arrows-horizontal", filled=n == 0, disabled=self.working,
                                tooltip=tool_role(tool))
                       for n, (tool, field) in enumerate(trade_tools(self.target))]
            body.append(t.text(tr('core.bank.queue_it_for_a_trade_a3f68e', value0=NAMES[self.target]), 12, t.MUTED))
            body.append(ft.Row(buttons, spacing=8, wrap=True))
        return ft.Column(body, spacing=10)

    def _choose(self, key: str) -> None:
        self.target = key
        self.render_detail()
        self.detail.update()

    def _send(self, entry: bank.Entry, tool, field) -> None:
        self.working = True
        self._say(tr('core.bank.moving_it_to_38b799', value0=NAMES[self.target]), t.BLUE)
        self.render_detail()
        self.detail.update()
        game = self.target

        def work():
            try:
                item = bank.offer(entry, game, self.app.settings.trainer(game))
                problem = bank.enqueue(self.app.settings, tool, field, item)
            except (OSError, pokemon.BuilderError) as error:
                problem = str(error)

            def done():
                self.working = False
                if problem:
                    self._say(problem, t.RED)
                    self.render_detail()
                    self.detail.update()
                    return
                self.app.navigate("games", game=game, tool=tool.key)
            self.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

    def _open(self, tool_key: str) -> None:
        game = next(g for g in GAMES for tool in g.tools if tool.key == tool_key)
        self.app.navigate("games", game=game.key, tool=tool_key)

    def _dequeue(self, entry: bank.Entry) -> None:
        bank.dequeue(self.app.settings, entry.id)
        self.render_grid()
        self.render_detail()
        self.control.update()

    def _edit(self, entry: bank.Entry) -> None:
        self._say(tr('core.bank.reading_it_dda821'), t.BLUE)

        def work():
            try:
                info = SERVICE.check_bytes(entry.game, bank.data(entry))
                moves = SERVICE.names(entry.game, "moves")
                items = SERVICE.names(entry.game, "items")
                problem = ""
            except (OSError, pokemon.BuilderError) as error:
                info, moves, items, problem = {}, [], [], str(error)

            def done():
                self._say(problem, t.RED)
                if not problem:
                    EditDialog(self, entry, info, moves, items).show()
            self.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

    def edited(self, entry: bank.Entry) -> None:
        self.routes.pop(entry.id, None)
        self.refresh()
        self.select(entry.id)
        self._say(tr('core.bank.saved_pkhex_checks_again_where_it_can_go_e19eb7'), t.MUTED)

    async def _export(self, entry: bank.Entry) -> None:
        extension = os.path.splitext(entry.path)[1][1:]
        path = await self.app.picker.save_file(dialog_title=tr('core.bank.export_pokemon_0cfbf8'), file_name=os.path.basename(entry.path),
                                               file_type=ft.FilePickerFileType.CUSTOM,
                                               allowed_extensions=[extension])
        if not path:
            return
        path += "" if path.lower().endswith(f".{extension}") else f".{extension}"
        try:
            with open(path, "wb") as out:
                out.write(bank.data(entry))
            self._say(tr('core.bank.exported_to_58eb1e', value0=path), t.MUTED)
        except OSError as error:
            self._say(str(error), t.RED)

    def _remove(self, entry: bank.Entry) -> None:
        def done(e):
            bank.dequeue(self.app.settings, entry.id)
            bank.remove(entry.id)
            self.app.page.pop_dialog()
            self.refresh()

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('core.bank.remove_this_pokemon_81b928'), 18),
            content=t.text(tr('core.bank.is_deleted_from_the_bank_on_this_computer_export_it_fir_c61b92', value0=entry.summary.split(' · ')[0]), 13, t.MUTED, width=380),
            actions=[t.button(tr('core.bank.cancel_19766e'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('core.bank.remove_c3812f'), done, color=t.RED)]))

    # Importing

    async def _pick(self, e) -> None:
        files = await self.app.picker.pick_files(dialog_title=tr('core.bank.import_pokemon_eed048'), allow_multiple=True)
        self._import([file.path for file in files or () if file.path])

    def _import(self, paths: list[str]) -> None:
        """Bank what each file holds, off the page's thread; the files are only read [bank.import_file]."""
        if self.working or not paths:
            return
        self.working = True
        trainers = {key: self.app.settings.trainer(key) for key in NAMES}

        def work():
            done, failed = [], []
            for n, path in enumerate(paths, 1):
                self.app.ui(lambda n=n, path=path: self._say(
                    tr('core.bank.reading_f1029d', value0=os.path.basename(path)) + (tr('core.bank.of_91ec22', value0=n, value1=len(paths)) if len(paths) > 1 else "")
                    + "...", t.BLUE))
                try:
                    done.append(bank.import_file(path, trainers))
                except (OSError, pokemon.BuilderError) as error:
                    failed.append(tr('core.bank._6a7768', value0=os.path.basename(path), value1=error))

            def finish():
                self.working = False
                self._say("", t.MUTED)
                self.refresh()
                ImportDialog(self.app, done, failed).show()
            self.app.ui(finish)
        threading.Thread(target=work, daemon=True).start()

    def _say(self, text: str, color: str) -> None:
        self.note.value, self.note.color = text, color
        try:
            self.note.update()
        except RuntimeError:
            pass


class ImportDialog:
    """One row per Pokemon found, grouped by file: its sprite, where it was, and whether it was banked."""

    STATES = {"banked": (ref('core.bank.banked_c89116'), "check", t.GREEN), "already": (ref('core.bank.already_in_the_bank_0dd815'), "copy", t.MUTED),
              'refused': (ref('core.bank.not_imported_a37f7e'), "warning-diamond", t.AMBER)}

    def __init__(self, app, done: list[bank.Imported], failed: list[str]):
        self.app = app
        counts = {state: sum(r.count(state) for r in done) for state in self.STATES}
        summary = [t.chip(tr('core.bank._54ef3b', value0=counts[s], value1=label.lower()), icon, color)
                   for s, (label, icon, color) in self.STATES.items() if counts[s] and s != "banked"]
        if failed:
            summary.append(t.chip(tr('core.bank.file_unreadable_0fd8f4', value0=len(failed), value1='s' if len(failed) > 1 else ''), "close", t.RED))
        groups: list[ft.Control] = [self._file(result) for result in done]
        groups += [self._unreadable(line) for line in failed]
        self.dialog = t.dialog(
            title=t.text(tr('core.bank.pokemon_banked_b85a56', value0=counts['banked']) if counts["banked"] else tr('core.bank.nothing_new_to_bank_566ae1'), 18),
            content=ft.Column([
                *([ft.Row(summary, spacing=6, wrap=True, run_spacing=6)] if summary else []),
                ft.Column(groups, spacing=18, scroll=ft.ScrollMode.AUTO, tight=True,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                          height=None if sum(len(r.pokemon) for r in done) + len(failed) < 6 else 440),
                t.text(tr('core.bank.pkhex_checks_every_pokemon_your_files_are_not_changed_da3f29'), 12, t.FAINT),
            ], spacing=16, tight=True, width=520),
            actions=[t.button(tr('core.bank.close_7d9eb7'), lambda e: app.page.pop_dialog())])

    def show(self) -> None:
        self.app.page.show_dialog(self.dialog)

    def _file(self, result: bank.Imported) -> ft.Control:
        head = ft.Row([t.pixel_icon("save" if result.save else "file", size=18, color=t.MUTED),
                       t.text(result.name, 13, weight=ft.FontWeight.W_600, expand=True,
                              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                       t.text(result.save.replace(", ", " · "), 12, t.FAINT)],
                      spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        rows = [self._pokemon(p) for p in result.pokemon] or [
            ft.Container(t.text(tr('core.bank.no_pokemon_in_this_file_bf95cd'), 12, t.MUTED), padding=12)]
        return ft.Column([head, ft.Container(ft.Column(rows, spacing=2), bgcolor=t.CARD, border_radius=14,
                                             padding=ft.Padding(6, 6, 12, 6))], spacing=8, tight=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def _pokemon(self, found: bank.ImportedPokemon) -> ft.Control:
        label, icon, color = self.STATES[found.state]
        about = [t.text(translate(found.species) or tr('core.bank.unknown_pokemon_40e13e'), 13, t.TEXT if found.state != _ref('core.gui.views.bank.refused_83c874d3') else t.SOFT,
                        weight=ft.FontWeight.W_600)]
        if found.where:
            about.append(t.text(translate(found.where), 11, t.FAINT))
        if found.detail:
            detail = i18n.join(((translate(part) for part in found.detail.split(" · "))), " · ")
            about.append(t.text(detail, 11, t.AMBER if found.state == _ref('core.gui.views.bank.refused_83c874d3') else t.MUTED,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, tooltip=detail))
        status = [ft.Container(game_icon(found.game, 18), tooltip=tr('core.bank.kept_as_a_pokemon_8c187f', value0=NAMES[found.game]))
                  ] if found.game and found.state != _ref('core.gui.views.bank.refused_83c874d3') else []
        status.append(t.chip(label, icon, color))
        return ft.Container(ft.Row([
            ft.Container(Sprite(self.app, found.species_id, found.shiny, size=MINI).control,
                         opacity=0.45 if found.state == _ref('core.gui.views.bank.refused_83c874d3') else 1),
            ft.Column(about, spacing=1, expand=True, tight=True),
            ft.Row(status, spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=ft.Padding(0, 4, 0, 4))

    @staticmethod
    def _unreadable(line: str) -> ft.Control:
        name, _, why = line.partition(": ")
        return ft.Column([
            ft.Row([t.pixel_icon("file", size=18, color=t.MUTED), t.text(name, 13, weight=ft.FontWeight.W_600)],
                   spacing=8),
            ft.Container(t.badge(why, t.RED, "close"), bgcolor=t.CARD, border_radius=14, padding=14),
        ], spacing=8, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


NONE = "-"


class EditDialog:
    """What a player could change in the game itself: nickname, level (only up), moves and held item. PKHeX
    checks the result, and a legal Pokemon is never saved illegal [pokeldn.app.bank.edit]."""

    def __init__(self, view: BankView, entry: bank.Entry, info: dict, moves: list[dict], items: list[dict]):
        self.view, self.entry, self.info = view, entry, info
        self.nickname = t.field(value=info["nickname"], hint=info["species"], expand=True,
                                limit=10 if entry.game in GEN3 else 12)
        self.level = t.field(value=str(info["level"]), mono=True, width=90, digits=True, limit=3)
        move_options = [(NONE, tr('core.bank.none_dc937b'))] + [(str(n["id"]), n["name"]) for n in moves]
        known = (list(info["move_ids"]) + [0] * 4)[:4]
        self.moves = [t.dropdown(move_options, str(m) if m else NONE, enable_filter=True, editable=True,
                                 menu_height=320) for m in known]
        self.item = t.dropdown([(NONE, tr('core.bank.nothing_67e1bc'))] + [(str(n["id"]), n["name"]) for n in items],
                               str(info["held_item_id"]) if info["held_item_id"] else NONE,
                               enable_filter=True, editable=True, menu_height=320)
        self.message = t.text("", 12, t.MUTED)
        self.save = t.button(tr('core.bank.save_1509f5'), self._save, "save")
        self.dialog = t.dialog(
            title=t.text(tr('core.bank.edit_44b87f', value0=info['species']), 18),
            content=ft.Column([
                ft.Row([t.labeled_control(tr('core.bank.nickname_d720f6'), self.nickname, expand=True),
                        t.labeled_control(tr('core.bank.level_170930'), self.level)], spacing=10),
                t.labeled_control(tr('core.bank.moves_26c84a'), ft.Column([ft.Row(self.moves[:2], spacing=6),
                                                      ft.Row(self.moves[2:], spacing=6)], spacing=6)),
                t.labeled_control(tr('core.bank.held_item_6af4a4'), self.item),
                t.text(tr('core.bank.only_what_the_game_itself_lets_a_player_change_pkhex_ch_363411'), 12, t.FAINT),
                self.message,
            ], spacing=14, tight=True, width=420),
            actions=[t.button(tr('core.bank.cancel_19766e'), lambda e: view.app.page.pop_dialog(), filled=False), self.save])

    def show(self) -> None:
        self.view.app.page.show_dialog(self.dialog)

    def _changes(self) -> dict | str:
        info, fields = self.info, {}
        nickname = self.nickname.value.strip()
        if nickname != info["nickname"]:
            fields["nickname"] = nickname
        level = self.level.value.strip()
        if not level.isdigit() or not info["level"] <= int(level) <= 100:
            return tr('core.bank.the_level_goes_from_to_100_f53f78', value0=info['level'])
        if int(level) != info["level"]:
            fields["level"] = int(level)
        moves = [int(box.value) for box in self.moves if box.value and box.value != NONE]
        if not moves:
            return tr('core.bank.it_needs_at_least_one_move_7a18ff')
        if len(set(moves)) < len(moves):
            return tr('core.bank.a_move_appears_twice_d477e7')
        if moves != list(info["move_ids"]):
            fields["moves"] = moves
        item = 0 if self.item.value in (None, NONE) else int(self.item.value)
        if item != info["held_item_id"]:
            fields["held_item"] = item
        return fields

    def _say(self, text: str, color: str) -> None:
        self.message.value, self.message.color = text, color
        self.dialog.update()

    def _save(self, e) -> None:
        fields = self._changes()
        if isinstance(fields, str):
            self._say(fields, t.RED)
            return
        if not fields:
            self.view.app.page.pop_dialog()
            return
        self.save.disabled = True
        self._say(tr('core.bank.pkhex_is_checking_it_e51442'), t.BLUE)

        def work():
            try:
                bank.edit(self.entry, fields)
                problem = ""
            except (OSError, pokemon.BuilderError) as error:
                problem = str(error)

            def done():
                if problem:
                    self.save.disabled = False
                    self._say(tr('core.bank.not_saved_0c5892', value0=problem), t.RED)
                    return
                self.view.app.page.pop_dialog()
                self.view.edited(self.entry)
            self.view.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

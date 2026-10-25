"""The bank: every Pokemon a trade brought in, and the way to trade one into another game
[pokeldn.app.bank, docs/gui.md, The bank]."""
from pokeldn.app.i18n import t as tr
import os
import shutil
import threading

import flet as ft

from gui import drop, theme as t
from gui.views.games import tool_role
from gui.views.sprites import MINI, SIZE, Sprite
from gui.views.widgets import open_folder
from gui.localization import SERVICE, date_time, summary_lines, summary_text, translate
from pokeldn import pokemon
from pokeldn.app import bank
from pokeldn.app.settings import GEN3
from pokeldn.app.catalog import GAMES

NAMES = {game.key: game.name for game in GAMES}
ALL = "all"
DEX = "dex"   # the Pokedex: every species a bank game holds, and whether the bank has one
STATS = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
SORTS = {"newest": lambda e: (-e.created, e.id), "oldest": lambda e: (e.created, e.id),
         "dex": lambda e: (e.species_id, -e.created), "name": lambda e: (e.summary.split(" · ")[0].casefold(), -e.created)}


def trade_tools(game_key: str) -> list:
    """(tool, its offer field) for each trade tool of a game."""
    game = next(g for g in GAMES if g.key == game_key)
    return [(tool, field) for tool in game.tools if not tool.unavailable
            for field in tool.fields if field.kind == "pokemon" and field.queue > 1]


def game_icon(key: str, size: int = 20) -> ft.Control:
    return ft.Image(src=f"games/{key}.png", width=size, height=size, fit=ft.BoxFit.CONTAIN,
                    filter_quality=ft.FilterQuality.NONE, semantics_label=NAMES.get(key, key))


class Tile:
    """One banked Pokemon in the grid, built once and repainted in place: a click redraws one tile, not the box."""

    def __init__(self, view, entry: bank.Entry, queued: bool):
        self.entry, self.queued = entry, queued
        self.check = ft.Container(left=2, top=2, bgcolor=t.BG, border_radius=4, visible=False)
        self.control = ft.Container(ft.Stack([
            Sprite(view.app, entry.species_id, entry.shiny, size=MINI).control,
            ft.Container(game_icon(entry.game, 16), right=0, bottom=0),
            ft.Container(t.pixel_icon("arrows-horizontal", size=12, color=t.BLUE), right=2, top=2, visible=queued),
            self.check,
        ]), padding=4, border_radius=14, tooltip=summary_text(entry.summary),
            on_click=lambda e: view.click(entry.id), on_long_press=lambda e: view.pick(entry.id))

    def paint(self, active: bool, picking: bool, picked: bool) -> None:
        self.control.border = ft.Border.all(2, t.BLUE if active or picked else ft.Colors.TRANSPARENT)
        self.control.bgcolor = t.SELECTED if picked else None
        self.check.visible = picking
        self.check.content = t.pixel_icon("checkbox-on" if picked else "checkbox", size=18,
                                          color=t.BLUE if picked else t.MUTED)


class BankView:
    def __init__(self, app):
        self.app = app
        self.visible = False
        self.shown = ALL                  # the game whose Pokemon the grid shows
        self.items: list[bank.Entry] = []
        self.selected: str = ""           # an Entry.id
        self.target: str = ""             # the game chosen to send the selected Pokemon to
        self.routes: dict[str, dict] = {}   # Entry.id -> pokemon.Service.destinations
        self.battle: dict[str, dict] = {}   # Entry.id -> the helper's "battle": IVs, effort, stats, Showdown set
        self.working = False
        self.tiles: dict[str, Tile] = {}
        self.picking = False              # several Pokemon are being chosen for one action
        self.picked: set[str] = set()
        self.query, self.sort, self.only = "", "newest", "any"
        self.dex_names: dict[int, str] = {}   # species id -> name, every species one of the bank's games holds
        self.dex_only = "all"
        self.queued: set[str] = set()       # bank.queued_ids, read once per render
        self.boxes = ft.ListView(spacing=2, padding=ft.Padding(8, 8, 8, 8), expand=True)
        # A lazy grid: only the tiles on screen are laid out and their sprites decoded.
        self.grid = ft.GridView(max_extent=64, spacing=6, run_spacing=6, padding=ft.Padding(0, 0, 0, 24), expand=True)
        self.dex = ft.GridView(max_extent=64, spacing=6, run_spacing=6, padding=ft.Padding(0, 0, 0, 24), expand=True)
        self.heading = t.text("", 12, t.MUTED)
        self.search = t.field(hint=tr('bank.search_by_name', 'Search'), on_change=self._search, expand=True)
        self.pick_button = t.secondary_button(tr('bank.select_several', 'Select'), lambda e: self._picking(not self.picking),
                                              "checkbox")
        self.actions = ft.Row(spacing=8, run_spacing=8, wrap=True, visible=False)
        self.detail = ft.Column(spacing=24, scroll=ft.ScrollMode.AUTO, expand=True)
        self.note = t.text("", 12, t.MUTED)
        self.panes = t.Panes(
            (tr('bank.pane_boxes', 'Boxes'), "archive", t.panel(ft.Column([
                t.panel_header(tr('bank.bank_676c47', 'Bank'),
                               t.icon_button("plus", self._pick, tr('bank.import_a_file', 'Import a Pokemon file, a game save or a PKSM bank')),
                               t.icon_button("folder", lambda e: open_folder(str(self._folder())),
                                             tr('bank.open_the_bank_folder_438a67', 'Open the bank folder')),
                               t.icon_button("refresh", lambda e: self.refresh(), tr('bank.refresh_0e9161', 'Refresh'))),
                t.fade(self.boxes),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH)),
            (tr('bank.pane_box', 'Box'), "package", drop.target(ft.Container(ft.Column([
                ft.Row([self.search], spacing=8),
                box_tools := ft.Row([
                    t.dropdown([("newest", tr('bank.sort_newest', 'Newest first')),
                                ("oldest", tr('bank.sort_oldest', 'Oldest first')),
                                ("dex", tr('bank.sort_dex', 'Pokedex number')),
                                ("name", tr('bank.sort_name', 'Name'))], self.sort,
                               on_select=lambda e: self._sorted(e.control.value)),
                    t.dropdown([("any", tr('bank.only_any', 'Every Pokemon')),
                                ("shiny", tr('bank.only_shiny', 'Shiny')),
                                ("queued", tr('bank.only_queued', 'Waiting to trade')),
                                ("illegal", tr('bank.only_illegal', 'Not legal'))], self.only,
                               on_select=lambda e: self._only(e.control.value)),
                    self.pick_button], spacing=8),
                dex_tools := ft.Row([
                    t.dropdown([("all", tr('bank.dex_all', 'Every species')),
                                ("have", tr('bank.dex_have', 'In the bank')),
                                ("missing", tr('bank.dex_missing', 'Missing')),
                                ("shiny", tr('bank.dex_no_shiny', 'No shiny yet'))], self.dex_only,
                               on_select=lambda e: self._dex_only(e.control.value)),
                ], spacing=8, visible=False),
                self.actions,
                ft.Container(self.heading, padding=ft.Padding(4, 0, 4, 0)),
                grid_box := t.fade(self.grid),
                dex_box := t.fade(self.dex),
            ], spacing=10, expand=True), padding=ft.Padding(0, 14, 0, 0), expand=True, border_radius=16),
                self._import, expand=True)),
            (tr('bank.pane_pokemon', 'Pokemon'), "user", t.panel(ft.Column([
                t.panel_header(tr('bank.pokemon_224642', 'Pokemon')),
                ft.Container(ft.Column([self.detail, self.note], spacing=8, expand=True),
                             padding=ft.Padding(18, 8, 18, 18), expand=True),
            ], spacing=0, expand=True), width=t.SESSION_WIDTH)))
        self.box_tools, self.dex_tools = box_tools, dex_tools
        self.grid_box, self.dex_box = grid_box, dex_box   # the grids' fades: a hidden grid's fade would still fill
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
        self.items = bank.entries()
        held = {e.id for e in self.items}
        bank.prune(self.app.settings, held)
        if self.selected not in held:
            self.selected, self.target = "", ""
        self.picked &= held
        self.tiles = {key: tile for key, tile in self.tiles.items() if key in held}
        self.render_boxes()
        self.render_grid()
        self.render_detail()
        if update:
            self.control.update()

    def render_boxes(self) -> None:
        counts = {key: sum(e.game == key for e in self.items) for key in NAMES}
        rows = [self._box(ALL, tr('bank.all_pokemon_fe268d', 'All Pokemon'), len(self.items), t.pixel_icon("package", color=t.MUTED))]
        held = len({e.species_id for e in self.items})
        rows.append(self._box(DEX, tr('bank.pokedex', 'Pokedex'),
                              f"{held} / {len(self.dex_names)}" if self.dex_names else held,
                              t.pixel_icon("book-open", color=t.MUTED)))
        rows += [self._box(key, NAMES[key], counts[key], game_icon(key, 28)) for key in NAMES if counts[key]]
        self.boxes.controls = rows

    def _box(self, key: str, label: str, count: int | str, icon: ft.Control) -> ft.Control:
        active = key == self.shown
        return ft.Container(ft.Row([
            ft.Container(icon, width=32, alignment=ft.Alignment.CENTER),
            t.text(label, 13, t.TEXT if active else t.SOFT, weight=ft.FontWeight.W_600, expand=True),
            t.text(str(count), 12, t.MUTED),
        ], spacing=10), padding=ft.Padding(8, 8, 10, 8), border_radius=12,
            bgcolor=t.SELECTED if active else None, on_click=lambda e, k=key: self._show(k))

    def _show(self, key: str) -> None:
        self.shown = key
        if key == DEX and self.picking:
            self._picking(False)
        self.render_boxes()
        self.render_grid()
        self.control.update()
        if key == DEX and not self.dex_names:
            threading.Thread(target=self._load_dex, daemon=True).start()

    def _only(self, key: str) -> None:
        self.only = key
        self.render_grid()
        self.control.update()

    def _search(self, e) -> None:
        self.query = e.control.value.strip().casefold()
        self.render_grid()
        self.control.update()

    def _sorted(self, key: str) -> None:
        self.sort = key
        self.render_grid()
        self.control.update()

    def _matches(self, entry: bank.Entry) -> bool:
        if self.only == "shiny" and not entry.shiny or self.only == "illegal" and entry.legal:
            return False
        if self.only == "queued" and entry.id not in self.queued:
            return False
        return (self.shown in (ALL, entry.game)
                and (not self.query or self.query in summary_text(entry.summary).casefold()))

    def _shown(self) -> list[bank.Entry]:
        return [e for e in self.items if self._matches(e)]

    def render_grid(self) -> None:
        """Every tile stays in the grid and a filter only hides some: a hidden tile costs nothing on screen,
        and showing it again sends no sprite."""
        dex = self.shown == DEX
        self.queued = bank.queued_ids(self.app.settings)
        self.grid_box.visible, self.dex_box.visible = not dex, dex
        self.box_tools.visible, self.dex_tools.visible = not dex, dex
        if dex:
            self.render_dex()
            self.render_actions()
            return
        shown = self._shown()
        where = tr('bank.in_the_bank_f69744', 'in the bank') if self.shown == ALL else tr('bank.from_7f2df4', 'from {value0}', value0=NAMES[self.shown])
        self.heading.value = (tr('bank.pokemon_3a4d02', '{value0} Pokemon {value1}', value0=len(shown), value1=where) if shown else
                              tr('bank.nothing_matches', 'No Pokemon matches this search.') if (self.query or self.only != "any") and self.items else
                              tr('bank.the_bank_is_empty_every_pokemon_a_trade_brings_in_lands_e05ff4', 'The bank is empty. Every Pokemon a trade brings in lands here, from any game.')
                              + (tr('bank.drop_a_file_here', ' Drop a Pokemon file, a game save or a PKSM bank here to import what it holds.')
                                 if drop.AVAILABLE else ""))
        self.grid.controls = [self._tile(e, e.id in self.queued) for e in sorted(self.items, key=SORTS[self.sort])]
        self.render_actions()

    # The Pokedex

    def _load_dex(self) -> None:
        names: dict[int, str] = {}
        try:
            for key in NAMES:
                names.update({s["id"]: s["name"] for s in SERVICE.species(key)})
        except (OSError, pokemon.BuilderError) as error:
            self.app.ui(lambda: self._say(str(error), t.RED))
            return

        def done():
            self.dex_names = names
            if self.visible:
                self.render_boxes()
                self.render_grid()
                self.control.update()
        self.app.ui(done)

    def render_dex(self) -> None:
        """One cell per species: its sprite while the bank holds one, its number while it does not."""
        held: dict[int, list[bank.Entry]] = {}
        for entry in self.items:
            held.setdefault(entry.species_id, []).append(entry)
        shiny = {s for s, entries in held.items() if any(e.shiny for e in entries)}
        if not self.dex_names:
            self.heading.value = tr('bank.dex_loading', 'Reading the species of every game...')
            self.dex.controls = []
            return
        keep = {"all": lambda s: True, "have": lambda s: s in held, "missing": lambda s: s not in held,
                "shiny": lambda s: s not in shiny}[self.dex_only]
        self.heading.value = tr('bank.dex_heading', '{held} of {total} species in the bank, {shiny} of them shiny',
                                held=len(held.keys() & self.dex_names.keys()), total=len(self.dex_names),
                                shiny=len(shiny & self.dex_names.keys()))
        self.dex.controls = [self._dex_cell(s, name, held.get(s, []), s in shiny)
                             for s, name in sorted(self.dex_names.items())
                             if keep(s) and (not self.query or self.query in name.casefold())]

    def _dex_cell(self, species: int, name: str, entries: list[bank.Entry], shiny: bool) -> ft.Control:
        number = t.text(f"{species:04d}", 10, t.FAINT if entries else t.MUTED)
        if not entries:
            return ft.Container(ft.Column([number, t.text(name, 9, t.FAINT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                                          spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                          alignment=ft.MainAxisAlignment.CENTER),
                                padding=4, tooltip=name)
        tip = tr('bank.dex_cell_tip', '{name}: {count} in the bank', name=name, count=len(entries))
        return ft.Container(ft.Stack([
            Sprite(self.app, species, shiny, size=MINI).control,
            ft.Container(t.pixel_icon("sparkles", size=12, color=t.AMBER), right=2, top=2, visible=shiny),
            ft.Container(t.text(str(len(entries)), 10, t.SOFT, weight=ft.FontWeight.W_600), right=4, bottom=2,
                         visible=len(entries) > 1),
        ]), padding=4, border_radius=14, tooltip=tip, on_click=lambda e: self._find(name))

    def _dex_only(self, key: str) -> None:
        self.dex_only = key
        self.render_grid()
        self.control.update()

    def _find(self, name: str) -> None:
        """A held species opens the box searched for it."""
        self.query = name.casefold()
        self.search.value = name
        self._show(ALL)

    def _tile(self, entry: bank.Entry, queued: bool) -> ft.Control:
        tile = self.tiles.get(entry.id)
        if tile is None or tile.entry != entry or tile.queued != queued:
            tile = self.tiles[entry.id] = Tile(self, entry, queued)
        self._paint(entry.id)
        tile.control.visible = self._matches(entry)
        return tile.control

    def _paint(self, entry_id: str, update: bool = False) -> None:
        if tile := self.tiles.get(entry_id):
            tile.paint(entry_id == self.selected and not self.picking, self.picking, entry_id in self.picked)
            if update and tile.control.page:
                tile.control.update()

    # Several at once

    def click(self, entry_id: str) -> None:
        if not self.picking:
            self.select(entry_id)
            return
        self.picked ^= {entry_id}
        self._paint(entry_id, update=True)
        self.render_actions()
        self.actions.update()

    def pick(self, entry_id: str) -> None:
        """A long press starts choosing several, with that one chosen."""
        if not self.picking:
            self._picking(True)
        if entry_id not in self.picked:
            self.click(entry_id)

    def _picking(self, on: bool) -> None:
        self.picking = on
        self.picked.clear()
        for key in self.tiles:
            self._paint(key)
        self.render_actions()
        self.control.update()

    def _pick_all(self, on: bool) -> None:
        self.picked = {e.id for e in self._shown()} if on else set()
        for key in self.tiles:
            self._paint(key)
        self.render_actions()
        self.control.update()

    def render_actions(self) -> None:
        self.pick_button.content = tr('bank.done_selecting', 'Done') if self.picking else tr('bank.select_several', 'Select')
        self.actions.visible = self.picking
        if not self.picking:
            return
        count = len(self.picked)
        queued = bank.queued_ids(self.app.settings) & self.picked
        everything = count and count == len(self._shown())
        self.actions.controls = [
            ft.Container(t.text(tr('bank.picked_count', '{count} selected', count=count) if count else
                                tr('bank.pick_some', 'Click Pokemon to select them.'), 13, t.SOFT),
                         height=t.CONTROL_HEIGHT, alignment=ft.Alignment.CENTER_LEFT),
            t.secondary_button(tr('bank.select_none', 'Select none') if everything else tr('bank.select_all', 'Select all'),
                               lambda e: self._pick_all(not everything), "checkbox-on"),
            t.secondary_button(tr('bank.export_366489', 'Export'), lambda e: self.app.page.run_task(self._export_picked),
                               "upload", disabled=not count),
            *([t.secondary_button(tr('bank.take_them_out', 'Take out of trades'), lambda e: self._dequeue_picked(),
                                  "close")] if queued else []),
            t.button(tr('bank.remove_c3812f', 'Remove'), lambda e: self._remove_picked(), "trash", color=t.RED,
                     disabled=not count),
        ]

    async def _export_picked(self) -> None:
        folder = await self.app.picker.get_directory_path(dialog_title=tr('bank.export_pokemon_0cfbf8', 'Export Pokemon'))
        if not folder:
            return
        chosen = [e for e in self.items if e.id in self.picked]
        try:
            for entry in chosen:
                name, extension = os.path.splitext(os.path.basename(entry.path))
                path, n = os.path.join(folder, name + extension), 1
                while os.path.exists(path):
                    n += 1
                    path = os.path.join(folder, f"{name} ({n}){extension}")
                shutil.copyfile(entry.path, path)
            self._say(tr('bank.exported_many', '{count} Pokemon exported to {folder}', count=len(chosen), folder=folder), t.MUTED)
        except OSError as error:
            self._say(str(error), t.RED)

    def _dequeue_picked(self) -> None:
        bank.dequeue(self.app.settings, *self.picked)
        self.render_grid()
        self.render_detail()
        self.control.update()

    def _remove_picked(self) -> None:
        chosen = [e for e in self.items if e.id in self.picked]
        if not chosen:
            return

        def done(e):
            bank.dequeue(self.app.settings, *(entry.id for entry in chosen))
            for entry in chosen:
                bank.remove(entry.id)
            self.app.page.pop_dialog()
            self.picking = False
            self.picked.clear()
            self.refresh()
            self._say(tr('bank.removed_many', '{count} Pokemon removed.', count=len(chosen)), t.MUTED)

        names = ", ".join(e.summary.split(" · ")[0] for e in chosen[:6]) + (", ..." if len(chosen) > 6 else "")
        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('bank.remove_many_title', 'Remove {count} Pokemon?', count=len(chosen)), 18),
            content=t.text(tr('bank.remove_many_detail', '{names} are deleted from the bank on this computer. Export them first to keep files.',
                              names=names), 13, t.MUTED, width=380),
            actions=[t.button(tr('bank.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('bank.remove_c3812f', 'Remove'), done, color=t.RED)]))

    # The selected Pokemon

    def select(self, entry_id: str) -> None:
        previous = self.selected
        self.selected, self.target = entry_id, ""
        self.note.value = ""
        self._paint(previous, update=True)
        self._paint(entry_id, update=True)
        self.render_detail()
        self.detail.update()
        self.note.update()
        self.panes.show(2)
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
        try:
            battle = SERVICE.check_bytes(entry.game, bank.data(entry))["battle"]
        except (OSError, pokemon.BuilderError):
            battle = {}

        def done():
            self.routes[entry.id] = routes
            self.battle[entry.id] = battle
            if self.visible and self.selected == entry.id:
                self.render_detail()
                self.detail.update()
        self.app.ui(done)

    def render_detail(self) -> None:
        entry = self._entry()
        if entry is None:
            self.detail.controls = [t.text(tr('bank.pick_a_pokemon_to_see_where_it_can_go_3b278b', 'Pick a Pokemon to see where it can go.'), 13, t.MUTED)]
            return
        head, rest = summary_lines(entry.summary)
        about = ft.Column([
            t.text(head, 15, weight=ft.FontWeight.W_600),
            t.text(rest, 12, t.MUTED),
            ft.Row([game_icon(entry.game), t.text(tr('bank.in_bb2233', 'In {value0}', value0=NAMES[entry.game]), 12, t.SOFT)], spacing=6),
            t.text(tr('bank.banked_faf7b7', 'Banked {value0}', value0=date_time(entry.created)), 12, t.FAINT),
            t.badge(tr('bank.legal_4787ea', 'Legal'), t.GREEN, "checkbox-on") if entry.legal else
            t.badge(tr('bank.pkhex_finds_it_not_legal_58cc49', 'PKHeX finds it not legal'), t.AMBER, "warning-diamond"),
            *([t.badge(translate(warning), t.AMBER, "warning-diamond")]
              if (warning := pokemon.HOME_TRACKER_WARNINGS.get(entry.home_tracker)) else []),
        ], spacing=4, expand=True)
        controls = [ft.Row([Sprite(self.app, entry.species_id, entry.shiny, size=SIZE).control, about],
                           spacing=14, vertical_alignment=ft.CrossAxisAlignment.START)]
        queued = bank.queued(self.app.settings, entry.id)
        if queued:
            tools = {tool.key: tr('bank._54ef3b', '{value0} {value1}', value0=NAMES[g.key], value1=tool.name) for g in GAMES for tool in g.tools}
            controls.append(t.section(tr('bank.waiting_to_trade_4a46c7', 'Waiting to trade'), ft.Column([
                t.text(tr('bank.queued_in_it_leaves_the_bank_when_that_trade_completes_e6f058', 'Queued in {value0}. It leaves the bank when that trade completes.', value0=', '.join((tools.get(k, k) for k in queued))), 12, t.MUTED),
                ft.Row([t.secondary_button(tr('bank.open_the_trade_fdac5d', 'Open the trade'), lambda e: self._open(queued[0]), "play"),
                        t.secondary_button(tr('bank.take_it_out_5a1e31', 'Take it out'), lambda e: self._dequeue(entry), "close")],
                       spacing=8, wrap=True),
            ], spacing=10)))
        else:
            controls.append(t.section(tr('bank.send_it_to_a_game_da82fb', 'Send it to a game'), self._routes(entry)))
        if battle := self.battle.get(entry.id):
            controls.append(t.section(tr('bank.battle_set', 'Battle set'), self._battle(battle)))
        controls.append(ft.Row([
            *([] if queued else [t.secondary_button(tr('bank.edit_464c4f', 'Edit'), lambda e: self._edit(entry), "edit")]),
            t.secondary_button(tr('bank.export_366489', 'Export'), lambda e: self.app.page.run_task(self._export, entry), "upload"),
            t.secondary_button(tr('bank.remove_c3812f', 'Remove'), lambda e: self._remove(entry), "trash"),
        ], spacing=8, wrap=True))
        self.detail.controls = controls

    def _battle(self, battle: dict) -> ft.Control:
        effort = {"evs": tr('bank.evs', 'EVs'), "avs": tr('bank.avs', 'AVs'), "gvs": tr('bank.gvs', 'GVs')}
        columns = [("", STATS), (tr('bank.ivs', 'IVs'), battle["ivs"]),
                   (effort[battle["effort_kind"]], battle["effort"]), (tr('bank.stat', 'Stat'), battle["stats"])]
        table = ft.Row([ft.Column([t.text(head, 11, t.MUTED, weight=ft.FontWeight.W_600),
                                   *(t.text(str(v), 12, t.SOFT if n == 0 else t.TEXT) for v in values)],
                                  spacing=4, width=56 if n == 0 else 44,
                                  horizontal_alignment=ft.CrossAxisAlignment.START if n == 0 else ft.CrossAxisAlignment.END)
                        for n, (head, values) in enumerate(columns)], spacing=12)
        return ft.Column([table, t.secondary_button(
            tr('bank.copy_as_showdown_set', 'Copy as a Showdown set'),
            lambda e: self.app.page.run_task(self.app.copy, battle["showdown"]), "copy")], spacing=12)

    def _routes(self, entry: bank.Entry) -> ft.Control:
        routes = self.routes.get(entry.id)
        if routes is None:
            return t.badge(tr('bank.pkhex_is_checking_each_game_8c9f63', 'PKHeX is checking each game...'), t.BLUE, "refresh")
        rows = []
        for key in NAMES:
            route = routes.get(key, {"ok": False, "reason": ""})
            ok, chosen = route["ok"], key == self.target
            lines = translate(route["reason"]).split("\n")
            warning = pokemon.HOME_TRACKER_WARNINGS.get(route.get("home_tracker", "")) if ok else None
            why = lines[0] + (tr('bank.more_86f3b0', ' (+{value0} more)', value0=len(lines) - 1) if len(lines) > 1 else "") if not ok else (
                tr('bank.its_own_game_6e5aee', 'Its own game') if key == entry.game else translate(warning) if warning else tr('bank.moves_as_home_would_move_it_5731e1', 'Moves as HOME would move it'))
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
            body.append(t.text(tr('bank.queue_it_for_a_trade_a3f68e', 'Queue it for a {value0} trade:', value0=NAMES[self.target]), 12, t.MUTED))
            body.append(ft.Row(buttons, spacing=8, wrap=True))
        return ft.Column(body, spacing=10)

    def _choose(self, key: str) -> None:
        self.target = key
        self.render_detail()
        self.detail.update()

    def _send(self, entry: bank.Entry, tool, field) -> None:
        self.working = True
        self._say(tr('bank.moving_it_to_38b799', 'Moving it to {value0}...', value0=NAMES[self.target]), t.BLUE)
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
        self._say(tr('bank.reading_it_dda821', 'Reading it...'), t.BLUE)

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
        self._say(tr('bank.saved_pkhex_checks_again_where_it_can_go_e19eb7', 'Saved. PKHeX checks again where it can go.'), t.MUTED)

    async def _export(self, entry: bank.Entry) -> None:
        extension = os.path.splitext(entry.path)[1][1:]
        path = await self.app.picker.save_file(dialog_title=tr('bank.export_pokemon_0cfbf8', 'Export Pokemon'), file_name=os.path.basename(entry.path),
                                               file_type=ft.FilePickerFileType.CUSTOM,
                                               allowed_extensions=[extension])
        if not path:
            return
        path += "" if path.lower().endswith(f".{extension}") else f".{extension}"
        try:
            with open(path, "wb") as out:
                out.write(bank.data(entry))
            self._say(tr('bank.exported_to_58eb1e', 'Exported to {value0}', value0=path), t.MUTED)
        except OSError as error:
            self._say(str(error), t.RED)

    def _remove(self, entry: bank.Entry) -> None:
        def done(e):
            bank.dequeue(self.app.settings, entry.id)
            bank.remove(entry.id)
            self.app.page.pop_dialog()
            self.refresh()

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('bank.remove_this_pokemon_81b928', 'Remove this Pokemon?'), 18),
            content=t.text(tr('bank.is_deleted_from_the_bank_on_this_computer_export_it_fir_c61b92', '{value0} is deleted from the bank on this computer. Export it first to keep a file.', value0=entry.summary.split(' · ')[0]), 13, t.MUTED, width=380),
            actions=[t.button(tr('bank.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('bank.remove_c3812f', 'Remove'), done, color=t.RED)]))

    # Importing

    async def _pick(self, e) -> None:
        files = await self.app.picker.pick_files(dialog_title=tr('bank.import_pokemon_eed048', 'Import Pokemon'), allow_multiple=True)
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
                    tr('bank.reading_f1029d', 'Reading {value0}', value0=os.path.basename(path)) + (tr('bank.of_91ec22', ' ({value0} of {value1})', value0=n, value1=len(paths)) if len(paths) > 1 else "")
                    + "...", t.BLUE))
                try:
                    done.append(bank.import_file(path, trainers))
                except (OSError, pokemon.BuilderError) as error:
                    failed.append(tr('bank._6a7768', '{value0}: {value1}', value0=os.path.basename(path), value1=error))

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

    STATES = {"banked": (tr('bank.banked_c89116', 'Banked'), "check", t.GREEN), "already": (tr('bank.already_in_the_bank_0dd815', 'Already in the bank'), "copy", t.MUTED),
              "refused": (tr('bank.not_imported_a37f7e', 'Not imported'), "warning-diamond", t.AMBER)}

    def __init__(self, app, done: list[bank.Imported], failed: list[str]):
        self.app = app
        counts = {state: sum(r.count(state) for r in done) for state in self.STATES}
        summary = [t.chip(tr('bank._54ef3b', '{value0} {value1}', value0=counts[s], value1=label.lower()), icon, color)
                   for s, (label, icon, color) in self.STATES.items() if counts[s] and s != "banked"]
        if failed:
            summary.append(t.chip(tr('bank.file_unreadable_0fd8f4', '{value0} file{value1} unreadable', value0=len(failed), value1='s' if len(failed) > 1 else ''), "close", t.RED))
        groups: list[ft.Control] = [self._file(result) for result in done]
        groups += [self._unreadable(line) for line in failed]
        self.dialog = t.dialog(
            title=t.text(tr('bank.pokemon_banked_b85a56', '{value0} Pokemon banked', value0=counts['banked']) if counts["banked"] else tr('bank.nothing_new_to_bank_566ae1', 'Nothing new to bank'), 18),
            content=ft.Column([
                *([ft.Row(summary, spacing=6, wrap=True, run_spacing=6)] if summary else []),
                ft.Column(groups, spacing=18, scroll=ft.ScrollMode.AUTO, tight=True,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                          height=None if sum(len(r.pokemon) for r in done) + len(failed) < 6 else 440),
                t.text(tr('bank.pkhex_checks_every_pokemon_your_files_are_not_changed_da3f29', 'PKHeX checks every Pokemon. Your files are not changed.'), 12, t.FAINT),
            ], spacing=16, tight=True, width=520),
            actions=[t.button(tr('bank.close_7d9eb7', 'Close'), lambda e: app.page.pop_dialog())])

    def show(self) -> None:
        self.app.page.show_dialog(self.dialog)

    def _file(self, result: bank.Imported) -> ft.Control:
        head = ft.Row([t.pixel_icon("save" if result.save else "file", size=18, color=t.MUTED),
                       t.text(result.name, 13, weight=ft.FontWeight.W_600, expand=True,
                              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                       t.text(result.save.replace(", ", " · "), 12, t.FAINT)],
                      spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        rows = [self._pokemon(p) for p in result.pokemon] or [
            ft.Container(t.text(tr('bank.no_pokemon_in_this_file_bf95cd', 'No Pokemon in this file.'), 12, t.MUTED), padding=12)]
        return ft.Column([head, ft.Container(ft.Column(rows, spacing=2), bgcolor=t.CARD, border_radius=14,
                                             padding=ft.Padding(6, 6, 12, 6))], spacing=8, tight=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def _pokemon(self, found: bank.ImportedPokemon) -> ft.Control:
        label, icon, color = self.STATES[found.state]
        about = [t.text(translate(found.species) or tr('bank.unknown_pokemon_40e13e', 'Unknown Pokemon'), 13, t.TEXT if found.state != "refused" else t.SOFT,
                        weight=ft.FontWeight.W_600)]
        if found.where:
            about.append(t.text(translate(found.where), 11, t.FAINT))
        if found.detail:
            detail = " · ".join(translate(part) for part in found.detail.split(" · "))
            about.append(t.text(detail, 11, t.AMBER if found.state == "refused" else t.MUTED,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, tooltip=detail))
        status = [ft.Container(game_icon(found.game, 18), tooltip=tr('bank.kept_as_a_pokemon_8c187f', 'Kept as a {value0} Pokemon', value0=NAMES[found.game]))
                  ] if found.game and found.state != "refused" else []
        status.append(t.chip(label, icon, color))
        return ft.Container(ft.Row([
            ft.Container(Sprite(self.app, found.species_id, found.shiny, size=MINI).control,
                         opacity=0.45 if found.state == "refused" else 1),
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
        move_options = [(NONE, tr('bank.none_dc937b', 'None'))] + [(str(n["id"]), n["name"]) for n in moves]
        known = (list(info["move_ids"]) + [0] * 4)[:4]
        self.moves = [t.dropdown(move_options, str(m) if m else NONE, enable_filter=True, editable=True,
                                 menu_height=320) for m in known]
        self.item = t.dropdown([(NONE, tr('bank.nothing_67e1bc', 'Nothing'))] + [(str(n["id"]), n["name"]) for n in items],
                               str(info["held_item_id"]) if info["held_item_id"] else NONE,
                               enable_filter=True, editable=True, menu_height=320)
        self.message = t.text("", 12, t.MUTED)
        self.save = t.button(tr('bank.save_1509f5', 'Save'), self._save, "save")
        self.dialog = t.dialog(
            title=t.text(tr('bank.edit_44b87f', 'Edit {value0}', value0=info['species']), 18),
            content=ft.Column([
                ft.Row([t.labeled_control(tr('bank.nickname_d720f6', 'Nickname'), self.nickname, expand=True),
                        t.labeled_control(tr('bank.level_170930', 'Level'), self.level)], spacing=10),
                t.labeled_control(tr('bank.moves_26c84a', 'Moves'), ft.Column([ft.Row(self.moves[:2], spacing=6),
                                                      ft.Row(self.moves[2:], spacing=6)], spacing=6)),
                t.labeled_control(tr('bank.held_item_6af4a4', 'Held item'), self.item),
                t.text(tr('bank.only_what_the_game_itself_lets_a_player_change_pkhex_ch_363411', 'Only what the game itself lets a player change. PKHeX checks every edit; one that would make it not legal is refused.'), 12, t.FAINT),
                self.message,
            ], spacing=14, tight=True, width=420),
            actions=[t.button(tr('bank.cancel_19766e', 'Cancel'), lambda e: view.app.page.pop_dialog(), filled=False), self.save])

    def show(self) -> None:
        self.view.app.page.show_dialog(self.dialog)

    def _changes(self) -> dict | str:
        info, fields = self.info, {}
        nickname = self.nickname.value.strip()
        if nickname != info["nickname"]:
            fields["nickname"] = nickname
        level = self.level.value.strip()
        if not level.isdigit() or not info["level"] <= int(level) <= 100:
            return tr('bank.the_level_goes_from_to_100_f53f78', 'The level goes from {value0} to 100.', value0=info['level'])
        if int(level) != info["level"]:
            fields["level"] = int(level)
        moves = [int(box.value) for box in self.moves if box.value and box.value != NONE]
        if not moves:
            return tr('bank.it_needs_at_least_one_move_7a18ff', 'It needs at least one move.')
        if len(set(moves)) < len(moves):
            return tr('bank.a_move_appears_twice_d477e7', 'A move appears twice.')
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
        self._say(tr('bank.pkhex_is_checking_it_e51442', 'PKHeX is checking it...'), t.BLUE)

        def work():
            try:
                bank.edit(self.entry, fields)
                problem = ""
            except (OSError, pokemon.BuilderError) as error:
                problem = str(error)

            def done():
                if problem:
                    self.save.disabled = False
                    self._say(tr('bank.not_saved_0c5892', 'Not saved: {value0}', value0=problem), t.RED)
                    return
                self.view.app.page.pop_dialog()
                self.view.edited(self.entry)
            self.view.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

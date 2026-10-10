"""The bank: every Pokemon a trade brought in, and the way to trade one into another game
[pokeldn.app.bank, docs/gui.md, The bank]."""
import os
import threading

import flet as ft

from gui import theme as t
from gui.views.games import tool_role
from gui.views.sprites import MINI, SIZE, Sprite
from gui.views.widgets import open_folder
from pokeldn import pokemon
from pokeldn.app import bank
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
        self.control = ft.Row([
            t.panel(ft.Column([
                t.panel_header("Bank",
                               t.icon_button("folder", lambda e: open_folder(str(self._folder())),
                                             "Open the bank folder"),
                               t.icon_button("refresh", lambda e: self.refresh(), "Refresh")),
                t.fade(self.boxes),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH),
            t.fade(ft.ListView([ft.Container(self.heading, padding=ft.Padding(4, 14, 4, 0)), self.grid],
                               spacing=12, padding=ft.Padding(0, 0, 0, 24), expand=True)),
            t.panel(ft.Column([
                t.panel_header("Pokemon"),
                ft.Container(ft.Column([self.detail, self.note], spacing=8, expand=True),
                             padding=ft.Padding(18, 8, 18, 18), expand=True),
            ], spacing=0, expand=True), width=t.SESSION_WIDTH),
        ], spacing=t.GAP, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    def enter(self, **_) -> None:
        self.visible = True
        self.refresh(update=False)

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
        rows = [self._box(ALL, "All Pokemon", len(self.items), t.pixel_icon("package", color=t.MUTED))]
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
        where = "in the bank" if self.shown == ALL else f"from {NAMES[self.shown]}"
        self.heading.value = (f"{len(shown)} Pokemon {where}" if shown else
                              "The bank is empty. Every Pokemon a trade brings in lands here, from any game.")
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
        ]), padding=4, border_radius=14, tooltip=entry.summary,
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
            routes = pokemon.SERVICE.destinations(entry.game, bank.data(entry), entry.tracker, trainer)
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
            self.detail.controls = [t.text("Pick a Pokemon to see where it can go.", 13, t.MUTED)]
            return
        parts = entry.summary.split(" · ")
        head = 3 if len(parts) > 2 and parts[2] == "shiny" else 2
        about = ft.Column([
            t.text(" · ".join(parts[:head]), 15, weight=ft.FontWeight.W_600),
            t.text(" · ".join(parts[head:]), 12, t.MUTED),
            ft.Row([game_icon(entry.game), t.text(f"In {NAMES[entry.game]}", 12, t.SOFT)], spacing=6),
            t.text(f"Banked {entry.when}", 12, t.FAINT),
            t.badge("Legal", t.GREEN, "checkbox-on") if entry.legal else
            t.badge("PKHeX finds it not legal", t.AMBER, "warning-diamond"),
        ], spacing=4, expand=True)
        controls = [ft.Row([Sprite(self.app, entry.species_id, entry.shiny, size=SIZE).control, about],
                           spacing=14, vertical_alignment=ft.CrossAxisAlignment.START)]
        queued = bank.queued(self.app.settings, entry.id)
        if queued:
            tools = {tool.key: f"{NAMES[g.key]} {tool.name}" for g in GAMES for tool in g.tools}
            controls.append(t.section("Waiting to trade", ft.Column([
                t.text(f"Queued in {', '.join(tools.get(k, k) for k in queued)}. It leaves the bank when "
                       "that trade completes.", 12, t.MUTED),
                ft.Row([t.secondary_button("Open the trade", lambda e: self._open(queued[0]), "play"),
                        t.secondary_button("Take it out", lambda e: self._dequeue(entry), "close")],
                       spacing=8, wrap=True),
            ], spacing=10)))
        else:
            controls.append(t.section("Send it to a game", self._routes(entry)))
        controls.append(ft.Row([
            *([] if queued else [t.secondary_button("Edit", lambda e: self._edit(entry), "edit")]),
            t.secondary_button("Export", lambda e: self.app.page.run_task(self._export, entry), "upload"),
            t.secondary_button("Remove", lambda e: self._remove(entry), "trash"),
        ], spacing=8, wrap=True))
        self.detail.controls = controls

    def _routes(self, entry: bank.Entry) -> ft.Control:
        routes = self.routes.get(entry.id)
        if routes is None:
            return t.badge("PKHeX is checking each game...", t.BLUE, "refresh")
        rows = []
        for key in NAMES:
            route = routes.get(key, {"ok": False, "reason": ""})
            ok, chosen = route["ok"], key == self.target
            lines = route["reason"].split("\n")
            why = lines[0] + (f" (+{len(lines) - 1} more)" if len(lines) > 1 else "") if not ok else (
                "Its own game" if key == entry.game else "Moves as HOME would move it")
            rows.append(ft.Container(ft.Row([
                game_icon(key, 24),
                ft.Column([t.text(NAMES[key], 13, t.TEXT if ok else t.FAINT, weight=ft.FontWeight.W_600),
                           t.text(why, 11, t.MUTED if ok else t.FAINT, max_lines=1,
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
            body.append(t.text(f"Queue it for a {NAMES[self.target]} trade:", 12, t.MUTED))
            body.append(ft.Row(buttons, spacing=8, wrap=True))
        return ft.Column(body, spacing=10)

    def _choose(self, key: str) -> None:
        self.target = key
        self.render_detail()
        self.detail.update()

    def _send(self, entry: bank.Entry, tool, field) -> None:
        self.working = True
        self._say(f"Moving it to {NAMES[self.target]}...", t.BLUE)
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
        self._say("Reading it...", t.BLUE)

        def work():
            try:
                info = pokemon.SERVICE.check_bytes(entry.game, bank.data(entry))
                moves = pokemon.SERVICE.names(entry.game, "moves")
                items = pokemon.SERVICE.names(entry.game, "items")
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
        self._say("Saved. PKHeX checks again where it can go.", t.MUTED)

    async def _export(self, entry: bank.Entry) -> None:
        extension = os.path.splitext(entry.path)[1][1:]
        path = await self.app.picker.save_file(dialog_title="Export Pokemon", file_name=os.path.basename(entry.path),
                                               file_type=ft.FilePickerFileType.CUSTOM,
                                               allowed_extensions=[extension])
        if not path:
            return
        path += "" if path.lower().endswith(f".{extension}") else f".{extension}"
        try:
            with open(path, "wb") as out:
                out.write(bank.data(entry))
            self._say(f"Exported to {path}", t.MUTED)
        except OSError as error:
            self._say(str(error), t.RED)

    def _remove(self, entry: bank.Entry) -> None:
        def done(e):
            bank.dequeue(self.app.settings, entry.id)
            bank.remove(entry.id)
            self.app.page.pop_dialog()
            self.refresh()

        self.app.page.show_dialog(t.dialog(
            title=t.text("Remove this Pokemon?", 18),
            content=t.text(f"{entry.summary.split(' · ')[0]} is deleted from the bank on this computer. "
                           "Export it first to keep a file.", 13, t.MUTED, width=380),
            actions=[t.button("Cancel", lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button("Remove", done, color=t.RED)]))

    def _say(self, text: str, color: str) -> None:
        self.note.value, self.note.color = text, color
        try:
            self.note.update()
        except RuntimeError:
            pass


NONE = "-"


class EditDialog:
    """What a player could change in the game itself: nickname, level (only up), moves and held item. PKHeX
    checks the result, and a legal Pokemon is never saved illegal [pokeldn.app.bank.edit]."""

    def __init__(self, view: BankView, entry: bank.Entry, info: dict, moves: list[dict], items: list[dict]):
        self.view, self.entry, self.info = view, entry, info
        self.nickname = t.field(value=info["nickname"], hint=info["species"], expand=True,
                                limit=10 if entry.game == "frlg" else 12)
        self.level = t.field(value=str(info["level"]), mono=True, width=90, digits=True, limit=3)
        move_options = [(NONE, "None")] + [(str(n["id"]), n["name"]) for n in moves]
        known = (list(info["move_ids"]) + [0] * 4)[:4]
        self.moves = [t.dropdown(move_options, str(m) if m else NONE, enable_filter=True, editable=True,
                                 menu_height=320) for m in known]
        self.item = t.dropdown([(NONE, "Nothing")] + [(str(n["id"]), n["name"]) for n in items],
                               str(info["held_item_id"]) if info["held_item_id"] else NONE,
                               enable_filter=True, editable=True, menu_height=320)
        self.message = t.text("", 12, t.MUTED)
        self.save = t.button("Save", self._save, "save")
        self.dialog = t.dialog(
            title=t.text(f"Edit {info['species']}", 18),
            content=ft.Column([
                ft.Row([t.labeled_control("Nickname", self.nickname, expand=True),
                        t.labeled_control("Level", self.level)], spacing=10),
                t.labeled_control("Moves", ft.Column([ft.Row(self.moves[:2], spacing=6),
                                                      ft.Row(self.moves[2:], spacing=6)], spacing=6)),
                t.labeled_control("Held item", self.item),
                t.text("Only what the game itself lets a player change. PKHeX checks every edit; one that "
                       "would make it not legal is refused.", 12, t.FAINT),
                self.message,
            ], spacing=14, tight=True, width=420),
            actions=[t.button("Cancel", lambda e: view.app.page.pop_dialog(), filled=False), self.save])

    def show(self) -> None:
        self.view.app.page.show_dialog(self.dialog)

    def _changes(self) -> dict | str:
        info, fields = self.info, {}
        nickname = self.nickname.value.strip()
        if nickname != info["nickname"]:
            fields["nickname"] = nickname
        level = self.level.value.strip()
        if not level.isdigit() or not info["level"] <= int(level) <= 100:
            return f"The level goes from {info['level']} to 100."
        if int(level) != info["level"]:
            fields["level"] = int(level)
        moves = [int(box.value) for box in self.moves if box.value and box.value != NONE]
        if not moves:
            return "It needs at least one move."
        if len(set(moves)) < len(moves):
            return "A move appears twice."
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
        self._say("PKHeX is checking it...", t.BLUE)

        def work():
            try:
                bank.edit(self.entry, fields)
                problem = ""
            except (OSError, pokemon.BuilderError) as error:
                problem = str(error)

            def done():
                if problem:
                    self.save.disabled = False
                    self._say(f"Not saved: {problem}", t.RED)
                    return
                self.view.app.page.pop_dialog()
                self.view.edited(self.entry)
            self.view.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

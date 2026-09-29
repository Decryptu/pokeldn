import os
import shlex
import threading
import time

import flet as ft

from pokeldn.app import command, runner
from gui import theme as t
from pokeldn.app.catalog import GAMES, Field, Game, Tool
from pokeldn.app.introspect import flags_of
from pokeldn.app.paths import SESSION
from gui.views.pokemon import NAME_LISTS, NamePicker, PokemonPicker
from gui.views.widgets import Log, PathField, open_folder

TOOL_ICONS = {"Trade": ft.Icons.SWAP_HORIZ_ROUNDED, "Mystery Gift": ft.Icons.CARD_GIFTCARD_OUTLINED,
              "Console code": ft.Icons.MEMORY_OUTLINED}
EMPTY = "-"   # a dropdown option cannot carry an empty key


def tool_icon(tool: Tool):
    return TOOL_ICONS.get(tool.name.split(" (")[0], ft.Icons.SWAP_HORIZ_ROUNDED)


class GamesView:
    def __init__(self, app):
        self.app = app
        self.game: Game = GAMES[0]
        self.tool: Tool = self.game.tools[0]
        self.tab = "basic"
        self.search = ""
        self.tree = ft.ListView(spacing=2, padding=ft.Padding(8, 8, 8, 8), expand=True)
        self.title = t.text("", 13, weight=ft.FontWeight.W_600)
        self.summary = t.text("", 12, t.MUTED)
        self.body = ft.ListView(spacing=12, padding=ft.Padding(4, 8, 4, 24), expand=True)
        self.tabs = ft.Container()
        self.session = SessionPanel(app, self)
        center = ft.Column([
            t.notch(self.title, self.tabs,
                    t.icon_button(ft.Icons.MENU_BOOK_OUTLINED, self._open_doc, "Read the docs for this game")),
            ft.Container(self.summary, alignment=ft.Alignment.CENTER, padding=ft.Padding(0, 10, 0, 2)),
            self.body,
        ], spacing=0, expand=True)
        self.control = ft.Row([
            t.panel(ft.Column([t.panel_header("Games"), self.tree], spacing=0, expand=True), width=270),
            center,
            self.session.control,
        ], spacing=14, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.select(self.game, self.tool, update=False)

    def enter(self, **_) -> None:
        self.session.refresh(update=False)

    # State

    def stored(self) -> dict:
        return self.app.settings.tool_values.setdefault(self.tool.key, {"values": {}, "extra": {}})

    @property
    def values(self) -> dict:
        return self.stored()["values"]

    @property
    def extra(self) -> dict:
        return self.stored()["extra"]

    def set_value(self, field: Field, value, rebuild: bool = False) -> None:
        self.values[field.key] = value
        self.app.settings.save()
        if rebuild:
            self.render_body()
            self.body.update()
        self.session.refresh()

    # Rendering

    def select(self, game: Game, tool: Tool, update: bool = True) -> None:
        if tool is not self.tool:
            self.tab, self.search = "basic", ""
        self.game, self.tool = game, tool
        self.title.value = f"{tool.name} · {game.name}"
        self.summary.value = tool.summary
        self.tabs.content = t.segmented([("basic", "Basic", ft.Icons.TUNE_ROUNDED),
                                          ("all", "All options", ft.Icons.LIST_ROUNDED)], self.tab, self._tab)
        self.render_tree()
        self.render_body()
        self.session.show(tool)
        if update:
            self.control.update()

    def render_tree(self) -> None:
        rows = []
        for game in GAMES:
            open_ = game is self.game
            rows.append(ft.Container(ft.Row([
                ft.Container(t.text(game.short, 10, t.BLUE if open_ else t.MUTED, weight=ft.FontWeight.W_700),
                             width=40, height=26, border_radius=7, alignment=ft.Alignment.CENTER,
                             bgcolor=ft.Colors.with_opacity(0.14, t.BLUE) if open_ else t.FIELD),
                t.text(game.name, 13, t.TEXT if open_ else "#C5C7CD", weight=ft.FontWeight.W_600, expand=True),
            ], spacing=10), padding=ft.Padding(8, 7, 8, 7), border_radius=9,
                on_click=lambda e, g=game: self.select(g, g.tools[0])))
            if open_:
                for tool in game.tools:
                    active = tool is self.tool
                    rows.append(ft.Container(ft.Row([
                        ft.Icon(tool_icon(tool), size=16, color=t.BLUE if active else t.FAINT),
                        t.text(tool.name, 13, t.TEXT if active else (t.FAINT if tool.unavailable else t.MUTED),
                               expand=True),
                        t.pill("Soon", t.FAINT) if tool.unavailable else ft.Container(),
                    ], spacing=10), padding=ft.Padding(24, 7, 8, 7), border_radius=9,
                        bgcolor=t.HOVER if active else None,
                        on_click=lambda e, g=game, x=tool: self.select(g, x)))
                rows.append(ft.Container(height=6))
        self.tree.controls = rows

    def render_body(self) -> None:
        if self.tool.unavailable:
            self.tabs.visible = False
            self.body.controls = [t.card("Not available yet", None, self.tool.unavailable)]
            return
        self.tabs.visible = True
        self.body.controls = self.basic_cards() if self.tab == "basic" else self.all_rows()

    def _tab(self, key: str) -> None:
        self.tab = key
        self.render_body()
        self.body.update()

    def _open_doc(self, e) -> None:
        self.app.navigate("docs", doc=self.tool.doc or self.game.doc)

    # Basic tab

    def basic_cards(self) -> list[ft.Control]:
        cards, groups = [], {}
        for field in self.tool.fields:
            if not command.applies(field, self.tool, self.values):
                continue
            if field.group:
                if field.group not in groups:
                    groups[field.group] = []
                    cards.append(("group", field.group))
                groups[field.group].append(field)
            else:
                cards.append(("field", field))
        out = []
        for kind, item in cards:
            if kind == "field" and item.kind == "switch":
                out.append(t.card(item.label, None, item.help, trailing=self.input(item)))
            elif kind == "field":
                out.append(t.card(item.label, self.input(item), item.help))
            else:
                fields = groups[item]
                per_row = 2 if len(fields) > 3 else len(fields)
                rows = [ft.Row([
                    ft.Column([t.text(f.label, 11, t.MUTED), self.input(f, grouped=True)], spacing=4, expand=True)
                    for f in fields[i:i + per_row]], spacing=10) for i in range(0, len(fields), per_row)]
                out.append(t.card(item, ft.Column(rows, spacing=10),
                                  tip=" ".join(f.help for f in fields if f.help)))
        if not self.tool.fields:
            out.append(t.text("Nothing to fill in.", 13, t.MUTED))
        return out

    def input(self, field: Field, grouped: bool = False) -> ft.Control:
        value = command.value_of(field, self.values)
        if field.kind == "switch":
            return t.switch(bool(value), lambda e: self.set_value(field, e.control.value, rebuild=True))
        if field.kind == "choice":
            return t.dropdown([(k or EMPTY, label) for k, label in field.choices], value or EMPTY,
                              on_select=lambda e: self.set_value(
                                  field, "" if e.control.value == EMPTY else e.control.value, rebuild=True))
        if field.kind in NAME_LISTS:
            return NamePicker(self.app, self.game.key, field.kind, value,
                              lambda v: self.set_value(field, v), optional=not field.default).control
        if field.kind == "pokemon":
            return PokemonPicker(self.app, self.game.key, value or {}, lambda v: self.set_value(field, v),
                                 version=str(self.values.get("--version", ""))).control
        if field.kind == "file":
            return PathField(self.app.picker, lambda: os.path.expanduser("~"), value or "", "file", field.exts,
                             lambda v: self.set_value(field, v)).control
        def changed(e):
            if field.limits:
                e.control.error = command.limit_error(field, e.control.value) or None
                e.control.update()
            self.set_value(field, e.control.value)

        box = t.field(value=str(value), mono=field.kind == "number", error_max_lines=2,
                      width=180 if field.kind == "number" and not grouped else None,
                      error=command.limit_error(field, value) or None, on_change=changed,
                      expand=field.kind != "number" or grouped)
        return box if grouped or field.kind == "number" else ft.Row([box])

    # All tab

    def all_rows(self) -> list[ft.Control]:
        search = t.field(value=self.search, hint="Search every option", autofocus=False,
                         prefix_icon=ft.Icons.SEARCH, on_change=self._search)
        note = ("Every option the entry point accepts, from its own help. Values set here are added after the "
                "Basic fields and override them.")
        self.flag_list = ft.Column(spacing=8)
        self._fill_flags()
        return [t.card("Every option", ft.Column([search, self.flag_list], spacing=10,
                                                 horizontal_alignment=ft.CrossAxisAlignment.STRETCH), note)]

    def _search(self, e) -> None:
        self.search = e.control.value
        self._fill_flags()
        self.flag_list.update()

    def _fill_flags(self) -> None:
        try:
            flags = flags_of(self.tool.script)
        except Exception as error:
            self.flag_list.controls = [t.text(f"Could not read the options: {error}", 12, t.RED)]
            return
        query = self.search.lower().strip()
        rows = []
        for flag in flags:
            if query and query not in flag.option.lower() and query not in flag.help.lower():
                continue
            rows.append(self.flag_row(flag))
        empty = "No option matches." if flags else "This tool takes no options beyond its Basic fields."
        self.flag_list.controls = rows[:200] or [t.text(empty, 12, t.MUTED)]

    def flag_row(self, flag) -> ft.Control:
        value = self.extra.get(flag.option)

        def store(v):
            if v in (None, "", False):
                self.extra.pop(flag.option, None)
            else:
                self.extra[flag.option] = v
            self.app.settings.save()
            self.session.refresh()

        if flag.kind == "switch":
            control = t.switch(bool(value), lambda e: store(e.control.value))
        elif flag.kind == "choice":
            control = ft.Container(t.dropdown([(EMPTY, "default")] + [(c, c) for c in flag.choices],
                                              value or EMPTY,
                                              on_select=lambda e: store("" if e.control.value == EMPTY else e.control.value)),
                                   width=220)
        else:
            default = "" if flag.default in (None, [], "") else str(flag.default)
            control = ft.Container(t.field(value=value or "", hint=default, mono=True,
                                           on_change=lambda e: store(e.control.value)), width=220)
        lines = [" ".join(line.split()) for line in flag.help.splitlines()]
        help_ = t.text("\n".join(l for l in lines if l) or "No description.", 11.5, t.MUTED, max_lines=4,
                       overflow=ft.TextOverflow.ELLIPSIS)

        def toggle(e):
            help_.max_lines = None if help_.max_lines else 4
            help_.update()

        return ft.Container(ft.Row([
            ft.Column([t.text(flag.option, 12.5, t.BLUE if value else t.TEXT, font_family=t.MONO),
                       ft.Container(help_, on_click=toggle, tooltip="Show all" if len(lines) > 4 else None)],
                      spacing=3, expand=True),
            control,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            bgcolor=t.FIELD, border_radius=10, padding=12)


class SessionPanel:
    def __init__(self, app, games: GamesView):
        self.app, self.games = app, games
        self.tool: Tool | None = None
        self.stopping = False
        self.status = ft.Container()
        self.board_line = ft.Container()
        self.steps = ft.Container()
        self.action = ft.Container()
        self.command_text = ft.Text("", size=11, color=t.MUTED, font_family=t.MONO, selectable=True)
        self.command_box = ft.Container(self.command_text, bgcolor=t.BG, border_radius=8, padding=10,
                                        visible=False)
        self.log = Log(app.page, "The session's output appears here.")
        tools = ft.Row([
            t.icon_button(ft.Icons.CODE_ROUNDED, self._toggle_command, "Show the command"),
            t.icon_button(ft.Icons.CONTENT_COPY_ROUNDED, self._copy_log, "Copy the log"),
            t.icon_button(ft.Icons.FOLDER_OUTLINED, self._open_received, "Open the Received folder"),
        ], spacing=0)
        self.control = t.panel(ft.Column([
            t.panel_header("Session", self.status),
            ft.Container(ft.Column([
                self.board_line, self.steps, self.action,
                ft.Row([t.text("Output", 12, t.MUTED, weight=ft.FontWeight.W_600, expand=True), tools]),
                self.command_box,
            ], spacing=10), padding=ft.Padding(14, 12, 14, 0)),
            ft.Container(self.log.control, padding=ft.Padding(14, 0, 14, 14), expand=True),
        ], spacing=0, expand=True), width=380)
        self.set_status("Ready", t.MUTED)

    def set_status(self, label: str, color: str) -> None:
        self.status.content = t.pill(label, color)

    def show(self, tool: Tool) -> None:
        if tool is not self.tool and not (self.app.process and self.app.process.running):
            self.log.clear()
            self.set_status("Ready", t.MUTED)
        self.tool = tool
        self.steps.content = t.card("On the console", t.numbered(list(tool.steps)))
        self.refresh(update=False)

    def refresh(self, update: bool = True) -> None:
        tool, s = self.tool, self.app.settings
        running = self.app.process and self.app.process.running
        port = self.app.radio_port()
        self.board_line.content = ft.Row([
            ft.Icon(ft.Icons.MEMORY_ROUNDED, size=16, color=t.GREEN if port else t.RED),
            t.text(f"Radio on {port}" if port else "No board selected", 12,
                   t.TEXT if port else t.RED, expand=True),
            ft.TextButton("Board", on_click=lambda e: self.app.navigate("board"),
                          style=ft.ButtonStyle(color=t.BLUE)),
        ], spacing=8)
        if running:
            action = t.button("Stop", self._stop, ft.Icons.STOP_ROUNDED, t.RED, expand=True)
        else:
            action = t.button("Start", self._start, ft.Icons.PLAY_ARROW_ROUNDED, expand=True,
                              disabled=self.app.busy or bool(tool.unavailable))
        self.action.content = ft.Row([action])
        try:
            self.command_text.value = shlex.join([tool.script, *command.build(
                tool, self.games.values, self.games.extra, s, stamp="STAMP")])
        except OSError as error:
            self.command_text.value = f"{error}"
        if update:
            self.control.update()

    def _toggle_command(self, e) -> None:
        self.command_box.visible = not self.command_box.visible
        self.command_box.update()

    async def _copy_log(self, e) -> None:
        await self.app.copy(self.log.text())

    def _open_received(self, e) -> None:
        open_folder(os.path.expanduser(self.app.settings.received))

    def _start(self, e) -> None:
        tool, s = self.tool, self.app.settings
        if self.app.busy:
            return
        port = self.app.radio_port()
        problems = [p for p in (
            "" if port else "No board found. Plug it in, or pick one on the Board page.",
            "" if os.path.isfile(os.path.expanduser(s.keys)) else "Choose your prod.keys in Settings.",
            command.missing_offer(tool, self.games.values), *command.problems(tool, self.games.values)) if p]
        self.log.clear()
        if problems:
            for p in problems:
                self.log.add(f"[app] {p}")
            self.set_status("Not started", t.RED)
            self.refresh()
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        args = command.build(tool, self.games.values, self.games.extra, s, stamp)
        for folder in (SESSION / "captures", os.path.expanduser(s.received)):
            os.makedirs(folder, exist_ok=True)
        trace = f"captures/{tool.key}-{stamp}_esp32.trace" if s.board_trace else None
        self.log.add(f"[app] {tool.name} · {self.games.game.name} · radio {port}")
        self.stopping = False
        self.app.process_label = tool.name
        self.app.process = runner.Process(["--run", tool.script, *args], str(SESSION),
                                          runner.base_env(s, port, trace), self.log.add, self._exited)
        threading.Thread(target=self._tick, daemon=True).start()
        self.refresh()

    def _tick(self) -> None:
        process = self.app.process
        while process.running:
            elapsed = int(time.monotonic() - process.started)
            self.app.ui(lambda e=elapsed: (self.set_status(f"Running {e // 60:02d}:{e % 60:02d}", t.BLUE),
                                           self.status.update()))
            time.sleep(1)

    def _stop(self, e) -> None:
        self.stopping = True
        self.log.add("[app] Stopping: the entry point leaves the network and closes the board.")
        self.app.process.stop()

    def _exited(self, code: int) -> None:
        def done():
            if self.stopping:
                self.set_status("Stopped", t.MUTED)
            elif code == 0:
                self.set_status("Finished", t.GREEN)
            else:
                self.set_status(f"Failed ({code})", t.RED)
            self.log.add(f"[app] Exited with code {code}.")
            self.refresh()
        self.app.ui(done)

import os
import shlex
import threading
import time

import flet as ft

from gui import board
from gui.app import keys_found
from pokeldn import pokemon as builder
from pokeldn.app import command, received, runner
from gui import theme as t
from pokeldn.app.catalog import GAMES, Field, Game, Tool
from pokeldn.app.introspect import flags_of
from pokeldn.app.paths import SESSION
from gui.views.pokemon import NAME_LISTS, NamePicker, OfferQueue, PokemonPicker
from gui.views.sprites import MINI, Sprite
from gui.views.widgets import CodeBlock, Log, PathField, open_folder

TOOL_ICONS = {"Trade": "arrows-horizontal", "Mystery Gift": "gift",
              "Console code": "cpu"}
EMPTY = "-"   # a dropdown option cannot carry an empty key
ADVANCED_NOTE = ("The tested defaults work for most players. Change these only when a guide or a bug report "
                 "asks you to. A value set here overrides the Basic tab.")


def tool_icon(tool: Tool):
    return TOOL_ICONS.get(tool.name.split(" (")[0], "arrows-horizontal")


def tool_role(tool: Tool) -> str:
    """Who looks for whom, said from the console's side."""
    if tool.key.endswith("-host"):
        return "Your console joins pokeldn"
    if tool.key.endswith("-join"):
        return "pokeldn joins your console"
    return ""


class GamesView:
    def __init__(self, app):
        self.app = app
        self.game: Game = GAMES[0]
        self.tool: Tool = self.game.tools[0]
        self.tab = "basic"
        self.search = ""
        self.sprites: dict[str, Sprite] = {}   # a species field's key -> the sprite on its card
        self.visible = False
        self.tree = ft.ListView(spacing=2, padding=ft.Padding(8, 8, 8, 8), expand=True)
        self.summary = t.text("", 12, t.MUTED, text_align=ft.TextAlign.CENTER)
        self.cards = ft.Column(spacing=t.GAP)
        # The cards start below the toolbar and scroll under its glass.
        self.body = ft.ListView([ft.Container(self.summary, alignment=ft.Alignment.CENTER,
                                              padding=ft.Padding(12, 0, 12, 4)), self.cards],
                                spacing=t.GAP, padding=ft.Padding(0, 62, 0, 24), expand=True)
        self.tabs = ft.Container()
        self.session = SessionPanel(app, self)
        center = ft.Stack([
            t.fade(self.body, 48),
            ft.Container(t.notch(self.tabs,
                                 t.icon_button("book-open", self._open_doc, "Read the docs for this game")),
                         top=0, left=0, right=0),
        ], expand=True)
        self.control = ft.Row([
            t.panel(ft.Column([t.panel_header("Games"), t.fade(self.tree)], spacing=0, expand=True), width=t.SIDEBAR_WIDTH),
            center,
            self.session.control,
        ], spacing=t.GAP, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.select(self.game, self.tool, update=False)

    def enter(self, **_) -> None:
        self.visible = True
        self.session.refresh(update=False)
        self.app.check_if_unknown()

    def leave(self) -> None:
        self.visible = False

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
            self.cards.update()
        self.session.refresh()

    # Rendering

    def select(self, game: Game, tool: Tool, update: bool = True) -> None:
        if tool is not self.tool:
            self.tab, self.search = "basic", ""
        self.game, self.tool = game, tool
        self.summary.value = tool.summary
        self.tabs.content = t.segmented([("basic", "Basic", "sliders-horizontal"),
                                          ("all", "Advanced", "bulletlist")], self.tab, self._tab)
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
                ft.Container(ft.Image(src=f"games/{game.key}.png", width=36, height=36,
                                      fit=ft.BoxFit.CONTAIN, filter_quality=ft.FilterQuality.NONE,
                                      semantics_label=game.name),
                             width=40, height=36, alignment=ft.Alignment.CENTER),
                t.text(game.name, 13, t.TEXT if open_ else t.SOFT, weight=ft.FontWeight.W_600, expand=True),
            ], spacing=10), padding=ft.Padding(8, 6, 8, 6), border_radius=12,
                on_click=lambda e, g=game: self.select(g, g.tools[0])))
            if open_:
                for tool in game.tools:
                    active = tool is self.tool
                    name = t.text(tool.name, 13, t.TEXT if active else (t.FAINT if tool.unavailable else t.MUTED))
                    role = tool_role(tool)
                    rows.append(ft.Container(ft.Row([
                        t.pixel_icon(tool_icon(tool), color=t.BLUE if active else t.FAINT),
                        ft.Column([name, t.text(role, 11, t.FAINT)], spacing=0, expand=True) if role else
                        ft.Container(name, expand=True),
                        t.badge("Soon", t.FAINT) if tool.unavailable else ft.Container(),
                    ], spacing=10), padding=ft.Padding(24, 7, 8, 7), border_radius=12, tooltip=tool.summary,
                        bgcolor=t.SELECTED if active else None,
                        on_click=lambda e, g=game, x=tool: self.select(g, x)))
                rows.append(ft.Container(height=6))
        self.tree.controls = rows

    def render_body(self) -> None:
        if self.tool.unavailable:
            self.tabs.visible = False
            self.cards.controls = [t.card("Not available yet", None, self.tool.unavailable)]
            return
        self.tabs.visible = True
        self.cards.controls = self.basic_cards() if self.tab == "basic" else self.all_rows()

    def _tab(self, key: str) -> None:
        self.tab = key
        self.render_body()
        self.cards.update()

    def _open_doc(self, e) -> None:
        self.app.navigate("docs", doc=self.tool.doc or self.game.doc)

    # Basic tab

    def basic_cards(self) -> list[ft.Control]:
        cards, groups = [], {}
        for field in self.tool.fields:
            if field.hidden or not command.applies(field, self.tool, self.values):
                continue
            if field.group:
                if field.group not in groups:
                    groups[field.group] = []
                    cards.append(("group", field.group))
                groups[field.group].append(field)
            else:
                cards.append(("field", field))
        out = []
        self.sprites = {}
        for kind, item in cards:
            if kind == "field" and item.kind == "switch":
                out.append(t.card(item.label, None, item.help, trailing=self.input(item)))
            elif kind == "field":
                out.append(t.card(item.label, self.input(item), self.description(item),
                                  trailing=self.species_sprite([item])))
            else:
                fields = groups[item]
                per_row = 2 if len(fields) > 3 else len(fields)
                sprite = self.species_sprite(fields)
                rows = [ft.Row([
                    t.labeled_control(f.label, self.input(f, grouped=True), expand=True)
                    for f in fields[i:i + per_row]], spacing=10) for i in range(0, len(fields), per_row)]
                out.append(t.card(item, ft.Column(rows, spacing=10),
                                  " ".join(f.help for f in fields if f.help), trailing=sprite))
        if not self.tool.fields:
            out.append(t.text("Nothing to fill in.", 13, t.MUTED))
        return out

    def shiny(self) -> bool:
        return any(bool(command.value_of(f, self.values)) for f in self.tool.fields
                   if f.shiny and command.applies(f, self.tool, self.values))

    def species_sprite(self, fields: list[Field]) -> ft.Control | None:
        field = next((f for f in fields if f.kind == "species"), None)
        if field is None:
            return None
        value = str(command.value_of(field, self.values) or "")
        sprite = Sprite(self.app, int(value) if value.isdigit() else 0, self.shiny(), size=MINI)
        self.sprites[field.key] = sprite
        return sprite.control

    def description(self, field: Field) -> str:
        selected = command.value_of(field, self.values)
        detail = dict(field.choice_help).get(selected, "") if field.kind == "choice" else ""
        return " ".join(part for part in (field.help, detail) if part)

    def input(self, field: Field, grouped: bool = False) -> ft.Control:
        value = command.value_of(field, self.values)
        if field.kind == "switch":
            return t.switch(bool(value), lambda e: self.set_value(field, e.control.value, rebuild=True))
        if field.kind == "choice":
            return t.dropdown([(k or EMPTY, label) for k, label in field.choices], value or EMPTY,
                              on_select=lambda e: self.set_value(
                                  field, "" if e.control.value == EMPTY else e.control.value, rebuild=True))
        if field.kind in NAME_LISTS:
            def picked(v):
                self.set_value(field, v)
                if field.key in self.sprites:
                    self.sprites[field.key].show(int(v) if str(v).isdigit() else 0, self.shiny())
            return NamePicker(self.app, self.game.key, field.kind, value, picked,
                              optional=not field.default).control
        if field.kind == "pokemon" and field.queue > 1:
            return OfferQueue(self.app, self.game.key, value, field.queue, lambda v: self.set_value(field, v),
                              version=str(self.values.get("--version", ""))).control
        if field.kind == "pokemon":
            first = command.offers(value)
            return PokemonPicker(self.app, self.game.key, first[0] if first else {},
                                 lambda v: self.set_value(field, v),
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
        search = t.field(value=self.search, hint="Search the options", autofocus=False,
                         prefix_icon=ft.Container(t.pixel_icon("search", color=t.FAINT),
                                                  width=40, alignment=ft.Alignment.CENTER),
                         on_change=self._search)
        self.flag_list = ft.Column(spacing=0)
        self._fill_flags()
        return [t.card("Advanced options", ft.Column([search, self.flag_list], spacing=10,
                                                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                       ADVANCED_NOTE)]

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
        hidden = {f.key: f for f in self.tool.fields if f.hidden}
        rows = []
        # The settings kept off the Basic tab come first.
        for flag in sorted(flags, key=lambda f: f.option not in hidden):
            field = hidden.get(flag.option)
            text = " ".join((flag.option, flag.help, field.label, field.help) if field else (flag.option, flag.help))
            if query and query not in text.lower():
                continue
            rows.append(self.flag_row(flag))
        empty = "No option matches." if flags else "This tool takes no options beyond its Basic fields."
        self.flag_list.controls = rows[:200] or [t.text(empty, 12, t.MUTED)]

    def flag_row(self, flag) -> ft.Control:
        # A field kept off the Basic tab is set here, on its own value, default included.
        bound = next((f for f in self.tool.fields if f.hidden and f.key == flag.option), None)
        value = command.value_of(bound, self.values) if bound else self.extra.get(flag.option)

        def store(v):
            if bound:
                self.set_value(bound, v if v not in (None, "") else bound.default)
                return
            if v in (None, "", False):
                self.extra.pop(flag.option, None)
            else:
                self.extra[flag.option] = v
            self.app.settings.save()
            self.session.refresh()
            if flag.kind == "choice":
                self._fill_flags()
                self.flag_list.update()

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
        detail = ""
        for field in self.tool.fields:
            if field.flag == flag.option and field.choice_help:
                detail = dict(field.choice_help).get(value or flag.default, "")
                break
        lines = ([bound.help] if bound and bound.help else
                 [" ".join(line.split()) for line in flag.help.splitlines()])
        if detail:
            lines.append(detail)
        help_ = t.text("\n".join(l for l in lines if l) or "No description.", 12, t.MUTED, max_lines=4,
                       overflow=ft.TextOverflow.ELLIPSIS)

        def toggle(e):
            help_.max_lines = None if help_.max_lines else 4
            help_.update()

        return ft.Container(ft.Row([
            ft.Column([ft.Row([t.text(bound.label, 13, weight=ft.FontWeight.W_600),
                               t.text(flag.option, 12, t.BLUE if value != bound.default else t.MUTED,
                                      font_family=t.MONO)], spacing=8) if bound else
                       t.text(flag.option, 13, t.BLUE if value else t.TEXT, font_family=t.MONO),
                       ft.Container(help_, on_click=toggle, tooltip="Show all" if len(lines) > 4 else None)],
                      spacing=3, expand=True),
            control,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            border=ft.Border(top=ft.BorderSide(1, t.DIVIDER)), padding=ft.Padding(0, 12, 0, 12))


def pokemon_row(app, species: int, shiny: bool, summary: str, tip: str = "") -> ft.Control:
    """A small sprite, then pokeldn.pokemon.summary on two lines: species, level and shininess, then the rest."""
    parts = summary.split(" · ")
    head = 3 if len(parts) > 2 and parts[2] == "shiny" else 2
    lines = [t.text(" · ".join(parts[:head]), 13, weight=ft.FontWeight.W_600, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS)]
    if parts[head:]:
        lines.append(t.text(" · ".join(parts[head:]), 12, t.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
    return ft.Container(ft.Row([Sprite(app, species, shiny, size=MINI).control,
                                ft.Column(lines, spacing=0, expand=True)],
                               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        tooltip=tip or None)


class SessionPanel:
    def __init__(self, app, games: GamesView):
        self.app, self.games = app, games
        self.tool: Tool | None = None
        self.stopping = False
        self.pulsing = False
        self.status_dot = ft.Container(width=10, height=10, border_radius=5, bgcolor=t.MUTED,
                                       animate_opacity=ft.Animation(800, ft.AnimationCurve.EASE_IN_OUT),
                                       on_animation_end=self._pulse)
        self.status_label = ft.Semantics(content=self.status_dot, label="Idle")
        self.status = ft.Container(self.status_label, width=24, height=24,
                                   alignment=ft.Alignment.CENTER, tooltip="Idle")
        self.board_line = ft.Container()   # the checklist before Start, or one line once all is set
        self.offering = ft.Container(visible=False)
        self.offered = None                # what the offering card shows, to rebuild it only on a change
        self.traded = 0                    # the run's completed trades, from its `[done] trade N` lines
        self.running_tool: Tool | None = None
        self.restart = False               # Start on another tool: stop this run, then start that one
        self.received = ft.Container(visible=False)
        self.run = None                    # (process, stamp, game) of the last run started
        self.seen: dict[str, tuple] = {}   # a received file -> (size, mtime, what PKHeX read, or None)
        self.steps = ft.Container()
        self.action = ft.Container()
        command_block = CodeBlock(app)
        self.command_text = command_block.text
        self.command_box = command_block.control
        self.command_box.visible = False
        self.log = Log(app.page, "The session's output appears here.")
        tools = ft.Row([
            t.icon_button("code", self._toggle_command, "Show the command"),
            t.icon_button("copy", self._copy_log, "Copy the log"),
            t.icon_button("folder", self._open_received, "Open the Received folder"),
        ], spacing=0)
        self.control = t.panel(ft.Column([
            t.panel_header("Session", self.status),
            # The checklist and the steps scroll; Start stays in view below them.
            ft.Container(t.fade(ft.Column([self.board_line, self.offering, self.received, self.steps], spacing=24,
                                          scroll=ft.ScrollMode.AUTO)),
                         padding=ft.Padding(18, 8, 18, 0), expand=3),
            ft.Container(ft.Column([
                self.action,
                ft.Row([t.text("Output", 12, t.MUTED, weight=ft.FontWeight.W_600, expand=True), tools]),
                self.command_box,
            ], spacing=12), padding=ft.Padding(18, 14, 18, 8)),
            ft.Container(self.log.control, padding=ft.Padding(12, 0, 12, 12), expand=2),
        ], spacing=0, expand=True), width=t.SESSION_WIDTH)
        self.set_status("Ready", t.MUTED)
        app.board_listeners.append(lambda: self.refresh() if games.visible else None)

    def set_status(self, label: str, color: str) -> None:
        description = "Idle" if label == "Ready" else label
        running = label.startswith("Running")
        self.status_dot.bgcolor = color
        self.status.tooltip = description
        self.status_label.label = description
        if running and not self.pulsing:
            self.status_dot.opacity = 0.35
        elif not running:
            self.status_dot.opacity = 1
        self.pulsing = running

    def _pulse(self, e) -> None:
        if self.pulsing:
            self.status_dot.opacity = 1 if self.status_dot.opacity < 1 else 0.35
            self.status_dot.update()

    def show(self, tool: Tool) -> None:
        if tool is not self.tool and not (self.app.process and self.app.process.running):
            self.log.clear()
            self.set_status("Ready", t.MUTED)
            self.seen, self.received.content, self.received.visible = {}, None, False
            self.traded = 0
        self.tool = tool
        self.steps.content = t.section("On the console", t.step_list(list(tool.steps)))
        self.refresh(update=False)

    def checklist(self) -> list[tuple[str, str, str, str]]:
        """(state, what, how to fix it, the page that fixes it) for each thing Start needs.
        state is ok, wait, warn (Start still allowed) or block."""
        status = self.app.board_status()
        board_state = ("ok" if status.ready else "wait" if status.state == "checking" else
                       "block" if status.state in ("missing", "choose") else "warn")
        items = [
            ("ok", "Switch keys added", "", "") if keys_found(self.app.settings.keys) else
            ("block", "Add your Switch keys", "Choose prod.keys in Settings.", "settings"),
            (board_state, status.title, "" if status.ready else status.detail, "board"),
        ]
        if missing := command.missing_offer(self.tool, self.games.values):
            hint = " Pick a species, then press Build." if missing.startswith("Build") else ""
            items.append(("block", "Pokemon to offer", missing + hint, ""))
        items += [("block", "Check the options", problem, "") for problem in
                  command.problems(self.tool, self.games.values)]
        return items

    def render_checklist(self, items) -> ft.Control:
        if all(state == "ok" for state, *_ in items):
            return ft.Row([t.pixel_icon("checkbox-on", color=t.GREEN),
                           t.text("Ready to start", 13, t.TEXT, expand=True),
                           t.secondary_button("Board", lambda e: self.app.navigate("board"), "cpu")], spacing=8)
        looks = {"ok": ("checkbox-on", t.GREEN), "wait": ("refresh", t.BLUE),
                 "warn": ("warning-diamond", t.AMBER), "block": ("warning-diamond", t.RED)}
        labels = {"settings": "Settings", "board": "Board"}
        rows = []
        for state, what, how, page in items:
            icon, color = looks[state]
            rows.append(ft.Row([
                ft.Container(t.pixel_icon(icon, color=color), padding=ft.Padding(0, 1, 0, 0)),
                ft.Column([t.text(what, 13, weight=ft.FontWeight.W_600)] +
                          ([t.text(how, 12, t.MUTED)] if how else []), spacing=1, expand=True),
                t.secondary_button(labels[page], lambda e, k=page: self.app.navigate(k))
                if page and state != "ok" else ft.Container(),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START))
        return t.section("Before you start", ft.Column(rows, spacing=10))

    def refresh(self, update: bool = True) -> None:
        tool, s = self.tool, self.app.settings
        running = bool(self.app.process and self.app.process.running)
        session = running and self.run is not None and self.run[0] is self.app.process
        here = session and self.running_tool is tool
        items = self.checklist()
        self.board_line.content = None if here else self.render_checklist(items)
        blocked = any(state == "block" for state, *_ in items)
        if here:
            action = t.button("Stop", self._stop, "stop", t.RED, expand=True)
        elif session:
            action = t.button(f"Stop {self.running_tool.name} and start", self._start, "play", expand=True,
                              disabled=self.restart or blocked or bool(tool.unavailable))
        else:
            action = t.button("Start", self._start, "play", expand=True,
                              disabled=self.app.busy or blocked or bool(tool.unavailable))
        self.action.content = ft.Row([action])
        self.render_offering()
        try:
            self.command_text.value = shlex.join([tool.script, *command.build(
                tool, self.games.values, self.games.extra, s, stamp="STAMP")])
        except OSError as error:
            self.command_text.value = f"{error}"
        if update:
            self.control.update()

    def render_offering(self) -> None:
        entries = [entry for field in self.tool.fields
                   if field.kind == "pokemon" and command.applies(field, self.tool, self.games.values)
                   for entry in command.offers(command.value_of(field, self.games.values))[:field.queue]
                   if entry.get("file")]
        shown = [(int(e.get("species") or 0), bool(e.get("shiny")), e.get("summary", "")) for e in entries]
        if (shown, self.traded) == self.offered:
            return
        self.offered = (shown, self.traded)
        self.offering.visible = bool(shown)
        done = t.text(f"{self.traded} traded", 12, t.GREEN) if self.traded else None
        if not shown:
            self.offering.content = None
        elif len(shown) == 1:
            species, shiny, summary = shown[0]
            self.offering.content = t.section("Offering", pokemon_row(self.app, species, shiny, summary),
                                              trailing=done)
        else:
            tiles = []
            for n, (species, shiny, summary) in enumerate(shown, start=1):
                sprite = Sprite(self.app, species, shiny, size=MINI)
                traded = n <= self.traded
                sprite.frame.tooltip = f"Trade {n}{' (done)' if traded else ''}: {summary}"
                tiles.append(ft.Stack([sprite.control, ft.Container(
                    t.pixel_icon("checkbox-on", color=t.GREEN), right=0, bottom=0, visible=traded)]))
            progress = (f"{min(self.traded, len(shown))} of {len(shown)} traded" if self.traded
                        else f"{len(shown)} trades, in order")
            self.offering.content = t.section("Offering", ft.Row(tiles, spacing=6, run_spacing=6, wrap=True),
                                              trailing=t.text(progress, 12, t.GREEN if self.traded else t.MUTED))

    def scan_received(self, run: tuple) -> None:
        """Read each Pokemon file the run has saved so far; a file still growing is read again."""
        process, stamp, game = run
        changed = False
        for path in received.session_files(self.app.settings.received, stamp):
            try:
                size, mtime = os.path.getsize(path), os.path.getmtime(path)
            except OSError:
                continue
            if path in self.seen and self.seen[path][:2] == (size, mtime):
                continue
            try:
                info = builder.SERVICE.check(game, path)
            except Exception:
                info = None
            if self.run is not run:
                return
            self.seen[path] = (size, mtime, info)
            changed = True
        if changed:
            self.app.ui(lambda: self.render_received(process))

    def render_received(self, process) -> None:
        if self.run is None or self.run[0] is not process:
            return
        rows = []
        for path, (_, _, info) in list(self.seen.items()):
            name = os.path.basename(path)
            if info is None:
                rows.append(pokemon_row(self.app, 0, False, f"Not read by PKHeX · {name}", path))
            else:
                rows.append(pokemon_row(self.app, int(info.get("species_id") or 0), bool(info.get("shiny")),
                                        builder.summary(info), path))
        self.received.visible = True
        self.received.content = t.section("Received", ft.Column(rows, spacing=8),
                                       trailing=t.icon_button("folder", self._open_received,
                                                              "Open the Received folder"))
        self.received.update()

    def _toggle_command(self, e) -> None:
        self.command_box.visible = not self.command_box.visible
        self.command_box.update()

    async def _copy_log(self, e) -> None:
        await self.app.copy(self.log.text())

    def _open_received(self, e) -> None:
        open_folder(os.path.expanduser(self.app.settings.received))

    def _start(self, e) -> None:
        tool, s = self.tool, self.app.settings
        process = self.app.process
        if (process and process.running and self.run is not None and self.run[0] is process
                and self.running_tool is not tool):
            # one board, one session: the running one leaves the network first
            self.restart = True
            self._stop(e)
            self.refresh()
            return
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
        self.seen, self.received.content, self.received.visible = {}, None, False
        self.traded = 0
        self.stopping = False
        self.app.process_label = tool.name
        self.running_tool = tool
        self.app.process = runner.Process(["--run", tool.script, *args], str(SESSION),
                                          runner.base_env(s, port, trace), self._line, self._exited)
        self.run = (self.app.process, stamp, self.games.game.key)
        threading.Thread(target=self._tick, daemon=True).start()
        self.refresh()

    def _line(self, line: str) -> None:
        self.log.add(line)
        n = received.trades_done(line)
        if n is not None and n > self.traded:
            def mark():
                self.traded = n
                self.render_offering()
                self.offering.update()
            self.app.ui(mark)

    def _tick(self) -> None:
        run = self.run
        process = run[0]
        while process.running:
            elapsed = int(time.monotonic() - process.started)
            self.app.ui(lambda e=elapsed: (self.set_status(f"Running {e // 60:02d}:{e % 60:02d}", t.BLUE),
                                           self.status.update())
                        if self.app.process is process and process.running else None)
            self.scan_received(run)
            time.sleep(1)
        self.scan_received(run)   # a launcher may write its last file as it closes

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
            if self.restart:
                self.restart = False
                self._start(None)
                return
            self.refresh()
        self.app.ui(done)

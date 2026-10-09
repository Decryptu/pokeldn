"""The controller: a Switch's buttons pressed from this computer through the controller board, and
the macros the board plays on its own clock [pokeldn.pad, docs/gui.md, The controller]."""
import copy
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import flet as ft

from gui import theme as t
from gui.views import widgets
from gui.views.widgets import open_folder
from pokeldn.app import macros
from pokeldn.app.paths import SESSION
from pokeldn.app.runner import Process
from pokeldn.pad import macro as m
from pokeldn.pad import service

# Keyboard keys (Flet key names) to controller keys, used while "Keyboard" is on.
KEYBOARD = {
    "Arrow Up": "UP", "Arrow Down": "DOWN", "Arrow Left": "LEFT", "Arrow Right": "RIGHT",
    "X": "A", "Z": "B", "S": "X", "A": "Y", "Q": "L", "W": "R", "1": "ZL", "2": "ZR",
    "Enter": "PLUS", "Backspace": "MINUS", "H": "HOME", "C": "CAPTURE",
}
HINT = {v: k.replace("Arrow ", "") for k, v in KEYBOARD.items()}
STICK_DIRECTIONS = [("", "Centre", (0.0, 0.0)), ("UP", "Up", (0.0, 1.0)), ("UPRIGHT", "Up-right", (0.71, 0.71)),
                    ("RIGHT", "Right", (1.0, 0.0)), ("DOWNRIGHT", "Down-right", (0.71, -0.71)),
                    ("DOWN", "Down", (0.0, -1.0)), ("DOWNLEFT", "Down-left", (-0.71, -0.71)),
                    ("LEFT", "Left", (-1.0, 0.0)), ("UPLEFT", "Up-left", (-0.71, 0.71))]
BLUETOOTH_REFUSED = ("macOS refused Bluetooth to this program. The packaged app asks for it; from a source "
                     "checkout, allow Bluetooth for the terminal in System Settings, Privacy & Security.")


def describe(step: dict, macro: m.Macro) -> str:
    if "wait" in step:
        return f"Wait {step['wait']} ms"
    if "repeat" in step:
        return f"Repeat {step['repeat']} times"
    keys = step.get("press", [])
    keys = [keys] if isinstance(keys, str) else list(keys)
    for side in ("left", "right"):
        if side in step:
            keys.append(f"{side} stick {direction_of(step[side])[1].lower()}")
    return f"{' + '.join(keys) or 'Nothing'}  ·  {step.get('ms', macro.press_ms)} ms, then {step.get('after', macro.gap_ms)} ms"


def direction_of(xy) -> tuple[str, str, tuple]:
    best = min(STICK_DIRECTIONS, key=lambda d: (d[2][0] - xy[0]) ** 2 + (d[2][1] - xy[1]) ** 2)
    return best


class ControllerView:
    def __init__(self, app):
        self.app = app
        self.visible = False
        self.client: service.Client | None = None
        self.child: Process | None = None
        self.connecting = False
        self.state = "Not connected"
        self.board: dict = {}
        self.error = ""
        self.sender = ThreadPoolExecutor(max_workers=1)
        self.held: set[str] = set()
        self.keyboard = False
        self.recording = False
        self.last_up = 0.0
        self.pressed_at = 0.0
        self.items: list[macros.Entry] = []
        self.path = None                    # the open macro's file
        self.macro: m.Macro | None = None
        self.target = "loop"                # where recorded steps go
        self.note = t.text("", 12, t.MUTED)
        self.list = ft.ListView(spacing=2, padding=ft.Padding(8, 8, 8, 8), expand=True)
        self.status = ft.Column(spacing=6, tight=True)
        self.pad = ft.Column(spacing=18, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)
        self.editor = ft.ListView(spacing=14, padding=ft.Padding(18, 8, 18, 18), expand=True)
        self.footer = ft.Column(spacing=8, tight=True)
        self.control = ft.Row([
            t.panel(ft.Column([
                t.panel_header("Macros",
                               t.icon_button("plus", lambda e: self.new(), "New macro"),
                               t.icon_button("upload", self._import, "Import a .pokemacro file"),
                               t.icon_button("folder", lambda e: open_folder(str(macros.library())),
                                             "Open the macros folder")),
                t.fade(self.list),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH),
            t.fade(ft.ListView([self.status, self.pad], spacing=t.GAP, padding=ft.Padding(0, 0, 0, 24),
                               expand=True)),
            t.panel(ft.Column([
                t.panel_header("Macro"),
                self.editor,
                ft.Container(self.footer, padding=ft.Padding(18, 0, 18, 18)),
            ], spacing=0, expand=True), width=t.SESSION_WIDTH),
        ], spacing=t.GAP, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.render_all()

    def enter(self, **_) -> None:
        self.visible = True
        widgets.KEY_TARGET[0] = self
        self.refresh_list()
        self.render_all()
        threading.Thread(target=self._poll, daemon=True).start()

    def leave(self) -> None:
        self.visible = False
        widgets.KEY_TARGET[0] = None
        self._release_all()

    # The link

    def connect(self, e=None) -> None:
        if self.connecting:
            return
        self.connecting, self.error, self.state = True, "", "Looking for the board..."
        self.render_status()
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self) -> None:
        try:
            if not service.running():
                env = dict(os.environ)
                os.makedirs(SESSION, exist_ok=True)
                self.child = Process(["--module", "pokeldn.pad.service"], str(SESSION), env,
                                     lambda line: None, self._child_exit)
                for _ in range(100):
                    if service.running() or not self.child.running:
                        break
                    time.sleep(0.1)
            if self.client is None:
                self.client = service.Client()
            self.client.call("connect")
            reply = self.client.call("status")
            self.board = {**reply.get("status", {}), "link": reply.get("link", "")}
            self.state = "Connected"
        except (OSError, service.ServiceError) as error:
            self._drop()
            self.state = "Not connected"
            self.error = self.error or str(error)
        self.connecting = False
        self.app.ui(self.render_status)

    def _child_exit(self, code: int) -> None:
        self._drop()
        self.state = "Not connected"
        if code and sys.platform == "darwin" and code in (-6, 134):
            self.error = BLUETOOTH_REFUSED
        self.app.ui(self.render_status)

    def _drop(self) -> None:
        if self.client is not None:
            self.client.close()
        self.client = None

    def disconnect(self, e=None) -> None:
        if self.client is not None:
            try:
                self.client.call("disconnect")
            except (OSError, service.ServiceError):
                pass
        self._drop()
        self.board, self.state = {}, "Not connected"
        self.render_status()

    def _flashing_mode(self, e) -> None:
        def work():
            if self._call("download") is not None:
                self._drop()
                self.board, self.state = {}, "Not connected"
                self._say("The board restarted in flashing mode. Open the Board page and press Flash.")
                self.app.ui(self.render_status)
        threading.Thread(target=work, daemon=True).start()

    def _call(self, op: str, **fields) -> dict | None:
        if self.client is None:
            return None
        try:
            return self.client.call(op, **fields)
        except (OSError, service.ServiceError) as error:
            self.error = str(error)
            self.app.ui(self.render_status)
            return None

    def _send_later(self, op: str, **fields) -> None:
        self.sender.submit(self._call, op, **fields)

    def _poll(self) -> None:
        while self.visible:
            if self.client is not None and not self.connecting:
                reply = self._call("status")
                if reply is not None:
                    board = ({**reply.get("status", {}), "link": reply.get("link", "")}
                             if reply.get("connected") else {})
                    if board != self.board:
                        if self.board.get("playing") and not board.get("playing"):
                            self.note.value = ""
                        self.board = board
                        self.app.ui(self.render_status)
            time.sleep(1)

    # Pressing

    def _report(self) -> bytes:
        keys = [k for k in self.held if k in m.KEYS]
        left = next((d[2] for d in STICK_DIRECTIONS if f"LS_{d[0]}" in self.held), (0.0, 0.0))
        right = next((d[2] for d in STICK_DIRECTIONS if f"RS_{d[0]}" in self.held), (0.0, 0.0))
        return m.state(keys, left, right)

    def down(self, key: str) -> None:
        self.held.add(key)
        self.pressed_at = time.monotonic()
        self._send_later("send", report=self._report().hex())

    def up(self, key: str) -> None:
        if key not in self.held:
            return
        self._record(key, time.monotonic())
        self.held.discard(key)
        self._send_later("send", report=self._report().hex())

    def _release_all(self) -> None:
        if self.held:
            self.held.clear()
            self._send_later("send", report=m.NEUTRAL.hex())

    def key(self, e) -> None:
        """A keyboard key, from page_key while this page is shown and "Keyboard" is on."""
        if not self.keyboard or self.client is None or e.ctrl or e.meta or e.alt:
            return
        name = KEYBOARD.get(e.key)
        if name:
            now = time.monotonic()
            self.pressed_at = now
            press = self.macro.press_ms if self.macro else 100
            self._send_later("tap", report=m.state([name]).hex(), ms=press)
            self._record(name, now + press / 1000)

    def _record(self, key: str, released: float) -> None:
        if not (self.recording and self.macro):
            return
        step = {"press": [key]} if key in m.KEYS else {"left" if key.startswith("LS_") else "right":
                                                           list(direction_of_key(key))}
        step["ms"] = max(1, round((released - self.pressed_at) * 1000))
        steps = getattr(self.macro, self.target)
        if steps and self.last_up and "wait" not in steps[-1] and "repeat" not in steps[-1]:
            steps[-1]["after"] = max(0, round((self.pressed_at - self.last_up) * 1000))
        self.last_up = released
        steps.append(step)
        self.save()
        self.app.ui(self.render_editor)

    # The macro library

    def refresh_list(self) -> None:
        self.items = macros.entries()
        if self.path and not os.path.exists(self.path):
            self.path, self.macro = None, None
        rows = [self._row(entry) for entry in self.items]
        self.list.controls = rows or [ft.Container(t.text(
            "No macros yet. Make one with +, or import a .pokemacro someone shared.", 12, t.MUTED),
            padding=10)]

    def _row(self, entry: macros.Entry) -> ft.Control:
        active = self.path is not None and entry.path == self.path
        return ft.Container(ft.Row([
            t.pixel_icon("warning-diamond" if entry.error else "repeat", color=t.AMBER if entry.error else t.MUTED),
            t.text(entry.name, 13, t.TEXT if active else t.SOFT, weight=ft.FontWeight.W_600, expand=True,
                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=10), padding=ft.Padding(10, 8, 10, 8), border_radius=12,
            tooltip=entry.error or None, bgcolor=t.SELECTED if active else None,
            on_click=lambda e, p=entry.path: self.open(p))

    def open(self, path) -> None:
        try:
            self.macro, self.path = macros.load(path), path
            self._say("")
        except (OSError, m.MacroError) as error:
            self._say(f"This file does not load: {error}", t.RED)
            return
        self.recording = False
        self.refresh_list()
        self.render_all()
        self.control.update()

    def new(self) -> None:
        macro = m.Macro(name="New macro", loops=1)
        self.path = macros.save(macro)
        self.macro = macro
        self.refresh_list()
        self.render_all()
        self.control.update()

    def save(self) -> None:
        if self.macro is not None:
            self.path = macros.save(self.macro, self.path)

    async def _import(self, e) -> None:
        files = await self.app.picker.pick_files(allowed_extensions=[m.EXTENSION[1:]],
                                                 file_type=ft.FilePickerFileType.CUSTOM, allow_multiple=True)
        last = None
        for f in files or []:
            if f.path:
                try:
                    last = macros.import_file(f.path)
                except (OSError, UnicodeDecodeError, m.MacroError) as error:
                    self._say(f"{os.path.basename(f.path)}: {error}", t.RED)
        if last:
            self.open(last)

    async def _export(self, e) -> None:
        if self.macro is None:
            return
        path = await self.app.picker.save_file(dialog_title="Export macro",
                                               file_name=f"{self.macro.name}{m.EXTENSION}",
                                               file_type=ft.FilePickerFileType.CUSTOM,
                                               allowed_extensions=[m.EXTENSION[1:]])
        if not path:
            return
        path += "" if path.lower().endswith(m.EXTENSION) else m.EXTENSION
        try:
            with open(path, "w", encoding="utf-8") as out:
                out.write(self.macro.dumps())
            self._say(f"Exported to {path}")
        except OSError as error:
            self._say(str(error), t.RED)

    def _delete(self) -> None:
        def done(e):
            macros.remove(self.path)
            self.path, self.macro = None, None
            self.app.page.pop_dialog()
            self.refresh_list()
            self.render_all()
            self.control.update()

        self.app.page.show_dialog(t.dialog(
            title=t.text("Delete this macro?", 18),
            content=t.text(f"{self.macro.name} is deleted from this computer. Export it first to keep a file.",
                           13, t.MUTED, width=380),
            actions=[t.button("Cancel", lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button("Delete", done, color=t.RED)]))

    # Playing

    def play(self, e=None) -> None:
        if self.macro is None:
            return
        try:
            m.compile_macro(self.macro)
        except m.MacroError as error:
            self._say(str(error), t.RED)
            return
        self.recording = False

        def run():
            reply = self._call("play", macro=self.macro.dumps())
            if reply:
                self._say("Playing on the board. It keeps going if this computer sleeps.")
                self.board = {**self.board, "playing": True}
                self.app.ui(self.render_all_update)
        threading.Thread(target=run, daemon=True).start()

    def stop(self, e=None) -> None:
        self._send_later("stop")

    def render_all_update(self) -> None:
        self.render_all()
        self.control.update()

    # Rendering

    def render_all(self) -> None:
        self.render_status(update=False)
        self.render_pad()
        self.render_editor(update=False)

    def render_status(self, update: bool = True) -> None:
        connected = self.client is not None and self.state == "Connected"
        board = self.board or {}
        facts = []
        if connected:
            link = board.get("link", "")
            facts.append(t.chip(f"Board connected on {link.split(' ')[1]}" if link.startswith("serial ")
                                else "Board connected over Bluetooth", "check", t.GREEN))
            serial_link = board.get("link", "").startswith("serial ")
            facts.append(t.chip(("Paired with the Switch" if serial_link else "Switch plugged in") if board.get("mounted")
                                else "Not paired: open Change Grip/Order on the Switch" if serial_link
                                else "No Switch on its USB port",
                                "usb", t.GREEN if board.get("mounted") else t.AMBER))
            if board.get("version"):
                facts.append(t.chip(f"Firmware {board['version']}", "cpu"))
        action = (ft.Row([
            t.icon_button("download", self._flashing_mode,
                          "Flashing mode: the board restarts as a USB serial port, so the Board page can flash it. "
                          "Plug it into this computer first."),
            t.button("Disconnect", self.disconnect, "close", filled=False)], spacing=4, tight=True) if connected else
                  t.button("Looking..." if self.connecting else "Connect", self.connect, "zap",
                           disabled=self.connecting))
        body = [ft.Row([ft.Row(facts or [t.text(self.state, 13, t.MUTED)], spacing=6, wrap=True, expand=True),
                        action], vertical_alignment=ft.CrossAxisAlignment.CENTER)]
        if self.error:
            body.append(t.text(self.error, 12, t.RED))
        if not connected:
            body.append(t.text("Flash the controller firmware from the Board page. An ESP32-S3 plugs into the "
                               "Switch's USB-C port and this computer reaches it over Bluetooth; a classic ESP32 "
                               "stays plugged into this computer and pairs with the Switch as a Pro Controller.",
                               12, t.MUTED))
        if board.get("playing"):
            body.append(ft.Row([
                t.badge(f"Macro running: loop {board.get('loops_done', 0) + 1}, "
                        f"step {board.get('index', 0) + 1} of {board.get('count', 0)}", t.BLUE, "play"),
                t.button("Stop", self.stop, "stop", color=t.RED)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
        self.status.controls = [t.card("Controller board", ft.Column(body, spacing=10, tight=True))]
        self.render_footer()
        if update:
            try:
                self.status.update()
                self.footer.update()
            except RuntimeError:
                pass

    def _button(self, key: str, label: str, width=44, height=44, round_=True, icon: str = "") -> ft.Control:
        hint = HINT.get(key, "")
        face = ft.Container(
            ft.Column([t.pixel_icon(icon, color=t.SOFT) if icon else t.text(label, 13, t.TEXT, weight=ft.FontWeight.W_600),
                       *([t.text(hint, 9, t.FAINT)] if hint and self.keyboard else [])],
                      spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                      alignment=ft.MainAxisAlignment.CENTER),
            width=width, height=height, alignment=ft.Alignment.CENTER,
            border_radius=width / 2 if round_ else 10, bgcolor=t.FIELD,
            border=ft.Border.all(1, t.EDGE))
        return ft.GestureDetector(face, mouse_cursor=ft.MouseCursor.CLICK,
                                  on_tap_down=lambda e, k=key: self.down(k),
                                  on_tap_up=lambda e, k=key: self.up(k))

    def _arrow(self, key: str, icon: str, rotate: float = 0) -> ft.Control:
        face = ft.Container(t.pixel_icon(icon, color=t.SOFT), width=40, height=40, alignment=ft.Alignment.CENTER,
                            border_radius=10, bgcolor=t.FIELD, border=ft.Border.all(1, t.EDGE),
                            rotate=ft.Rotate(rotate) if rotate else None)
        return ft.GestureDetector(face, mouse_cursor=ft.MouseCursor.CLICK,
                                  on_tap_down=lambda e, k=key: self.down(k),
                                  on_tap_up=lambda e, k=key: self.up(k))

    def _cross(self, prefix: str, centre: ft.Control | None) -> ft.Control:
        gap = ft.Container(width=40, height=40)
        k = (lambda d: f"{prefix}{d}") if prefix else (lambda d: d)
        return ft.Column([
            ft.Row([gap, self._arrow(k("UP"), "arrow-up"), gap], spacing=4, tight=True),
            ft.Row([self._arrow(k("LEFT"), "arrow-left"), centre or gap, self._arrow(k("RIGHT"), "arrow-right")],
                   spacing=4, tight=True),
            ft.Row([gap, self._arrow(k("DOWN"), "arrow-down"), gap], spacing=4, tight=True),
        ], spacing=4, tight=True)

    def render_pad(self) -> None:
        b = self._button
        shoulders = ft.Row([
            ft.Row([b("ZL", "ZL", 64, 34, False), b("L", "L", 64, 34, False)], spacing=6),
            ft.Row([b("MINUS", "-", 34, 34), b("PLUS", "+", 34, 34)], spacing=60),
            ft.Row([b("R", "R", 64, 34, False), b("ZR", "ZR", 64, 34, False)], spacing=6),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=560)
        face = ft.Column([
            ft.Row([b("X", "X")], alignment=ft.MainAxisAlignment.CENTER, width=140),
            ft.Row([b("Y", "Y"), b("A", "A")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=140),
            ft.Row([b("B", "B")], alignment=ft.MainAxisAlignment.CENTER, width=140),
        ], spacing=0, tight=True)
        middle = ft.Row([
            ft.Column([t.text("Left stick", 11, t.MUTED), self._cross("LS_", b("LSTICK", "L3", 40, 40))],
                      spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            face,
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=560,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        lower = ft.Row([
            ft.Column([t.text("D-pad", 11, t.MUTED), self._cross("", None)], spacing=6,
                      horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            ft.Row([b("CAPTURE", "Capture", 40, 40, False, "camera"), b("HOME", "HOME", 40, 40, True, "home")],
                   spacing=24),
            ft.Column([t.text("Right stick", 11, t.MUTED), self._cross("RS_", b("RSTICK", "R3", 40, 40))],
                      spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=560,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        options = ft.Row([
            ft.Row([t.switch(self.keyboard, self._keyboard), t.text("Keyboard", 13, t.SOFT)], spacing=6, tight=True,
                   tooltip="Arrows for the D-pad, X A, Z B, S X, A Y, Q L, W R, 1 ZL, 2 ZR, Enter +, "
                           "Backspace -, H HOME, C Capture"),
            ft.Row([t.switch(self.recording, self._recording), t.text("Record into the macro", 13, t.SOFT)],
                   spacing=6, tight=True,
                   tooltip="Each press, its length and the pause before the next one become steps"),
        ], spacing=24)
        self.pad.controls = [t.card("Controller", ft.Column([
            ft.Container(ft.Column([shoulders, middle, lower], spacing=22, tight=True,
                                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                         padding=ft.Padding(0, 8, 0, 8), alignment=ft.Alignment.CENTER),
            options,
        ], spacing=16, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            "Hold a button to hold it on the console.")]

    def _keyboard(self, e) -> None:
        self.keyboard = e.control.value
        self.render_pad()
        self.pad.update()

    def _recording(self, e) -> None:
        if e.control.value and self.macro is None:
            self.new()
        self.recording = e.control.value
        self.last_up = 0.0
        self.render_pad()
        self.pad.update()

    # The editor

    def render_editor(self, update: bool = True) -> None:
        mac = self.macro
        if mac is None:
            self.editor.controls = [t.text("Pick a macro on the left, or make a new one with +.", 13, t.MUTED)]
        else:
            self.editor.controls = [
                self._text_field("Name", mac.name, lambda v: setattr(mac, "name", v or "Macro")),
                self._text_field("Description", mac.description, lambda v: setattr(mac, "description", v),
                                 multiline=True),
                ft.Row([self._number("Press (ms)", mac.press_ms, lambda v: setattr(mac, "press_ms", max(1, v)),
                                     "How long a step holds its buttons unless it says otherwise"),
                        self._number("Pause after (ms)", mac.gap_ms, lambda v: setattr(mac, "gap_ms", v),
                                     "The pause after each step unless it says otherwise")], spacing=10),
                self._number("Repeat the loop (0 = until stopped)", mac.loops,
                             lambda v: setattr(mac, "loops", min(v, 1_000_000))),
                self._section("Run once", "setup", mac.setup),
                self._section("Loop", "loop", mac.loop),
            ]
        self.render_footer()
        if update:
            try:
                self.editor.update()
                self.footer.update()
            except RuntimeError:
                pass

    def render_footer(self) -> None:
        self.footer.controls = [self._summary(), self._actions(), self.note] if self.macro else [self.note]

    def _text_field(self, label, value, setter, multiline=False) -> ft.Control:
        def changed(e):
            setter(e.control.value)
            self.save()
            if label == "Name":
                self.refresh_list()
                self.list.update()
        return t.labeled_control(label, t.field(value=value, multiline=multiline, min_lines=2 if multiline else None,
                                                on_blur=changed, on_submit=changed))

    def _number(self, label, value, setter, tip: str = "") -> ft.Control:
        def changed(e):
            setter(int(e.control.value or 0))
            self.save()
            self.render_footer()
            self.footer.update()
        return t.labeled_control(label, t.field(value=str(value), digits=True, limit=7, on_blur=changed,
                                                on_submit=changed, tooltip=tip or None), expand=True)

    def _section(self, title: str, target: str, steps: list) -> ft.Control:
        rec = t.chip("Recording here", "circle-info", t.RED) if self.recording and self.target == target else \
            ft.Container(t.text("Record here", 11, t.FAINT), on_click=lambda e: self._target(target),
                         visible=self.recording)
        return t.section(title, ft.Column([
            *self._steps(steps, 0),
            self._adders(steps),
        ], spacing=4, tight=True), rec)

    def _target(self, target: str) -> None:
        self.target, self.last_up = target, 0.0
        self.render_editor()

    def _steps(self, steps: list, depth: int) -> list[ft.Control]:
        rows = []
        for i, step in enumerate(steps):
            icon = "clock" if "wait" in step else "repeat" if "repeat" in step else "gamepad"
            label = describe(step, self.macro)
            if step.get("note"):
                label += f"  ·  {step['note']}"
            rows.append(ft.Container(ft.Row([
                t.pixel_icon(icon, size=12, color=t.MUTED),
                t.text(label, 12, t.SOFT, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                t.icon_button("arrow-up", lambda e, s=steps, n=i: self._move(s, n, -1), "Move up",
                              disabled=i == 0),
                t.icon_button("edit", lambda e, s=steps, n=i: self._edit(s, n), "Edit"),
                t.icon_button("trash", lambda e, s=steps, n=i: self._remove_step(s, n), "Remove"),
            ], spacing=4), padding=ft.Padding(8 + 14 * depth, 2, 0, 2), border_radius=8, bgcolor=t.CARD))
            if "repeat" in step:
                inner = step.setdefault("steps", [])
                rows += self._steps(inner, depth + 1)
                rows.append(ft.Container(self._adders(inner), padding=ft.Padding(8 + 14 * (depth + 1), 0, 0, 0)))
        return rows

    def _adders(self, steps: list) -> ft.Control:
        def add(kind):
            step = {"press": ["A"]} if kind == "press" else {"wait": 1000} if kind == "wait" else \
                {"repeat": 2, "steps": [{"press": ["A"]}]}
            steps.append(step)
            self.save()
            self.render_editor()
            if kind != "repeat":
                self._edit(steps, len(steps) - 1)
        return ft.Row([t.link_button("+ Press", lambda e: add("press")),
                       t.link_button("+ Wait", lambda e: add("wait")),
                       t.link_button("+ Repeat", lambda e: add("repeat"))], spacing=0)

    def _move(self, steps, n, delta) -> None:
        steps[n + delta], steps[n] = steps[n], steps[n + delta]
        self.save()
        self.render_editor()

    def _remove_step(self, steps, n) -> None:
        del steps[n]
        self.save()
        self.render_editor()

    def _edit(self, steps: list, n: int) -> None:
        step = copy.deepcopy(steps[n])
        page = self.app.page
        controls: list[ft.Control] = []

        if "wait" in step:
            wait = t.field(value=str(step["wait"]), digits=True, limit=7)
            controls.append(t.labeled_control("Wait (ms)", wait))

            def collect():
                return {"wait": int(wait.value or 0), **({"note": note.value} if note.value else {})}
        elif "repeat" in step:
            count = t.field(value=str(step["repeat"]), digits=True, limit=5)
            controls.append(t.labeled_control("Times", count))

            def collect():
                return {"repeat": max(1, int(count.value or 1)), "steps": step.get("steps", []),
                        **({"note": note.value} if note.value else {})}
        else:
            keys = step.get("press", [])
            chosen = set([keys] if isinstance(keys, str) else keys)
            chips = ft.Row(wrap=True, spacing=6, run_spacing=6, width=420)

            def render_chips():
                chips.controls = [ft.Container(
                    t.text(k, 12, t.TEXT if k in chosen else t.MUTED, weight=ft.FontWeight.W_600),
                    padding=ft.Padding(10, 4, 10, 4), border_radius=999,
                    bgcolor=t.SELECTED if k in chosen else ft.Colors.with_opacity(0.06, "#FFFFFF"),
                    on_click=lambda e, k=k: toggle(k)) for k in m.KEYS]

            def toggle(k):
                chosen.symmetric_difference_update({k})
                render_chips()
                chips.update()

            render_chips()
            sticks = {}
            for side, label in (("left", "Left stick"), ("right", "Right stick")):
                current = direction_of(step[side])[0] if side in step else ""
                sticks[side] = t.dropdown([(d[0] or "CENTRE", d[1]) for d in STICK_DIRECTIONS],
                                          current or "CENTRE")
                controls_side = t.labeled_control(label, sticks[side], expand=True)
                sticks[side + "_row"] = controls_side
            hold = t.field(value=str(step.get("ms", "")), digits=True, limit=7,
                           hint=f"{self.macro.press_ms}, the macro's")
            after = t.field(value=str(step.get("after", "")), digits=True, limit=7,
                            hint=f"{self.macro.gap_ms}, the macro's")
            controls += [t.text("Buttons held together", 11, t.MUTED), chips,
                         ft.Row([sticks["left_row"], sticks["right_row"]], spacing=10, width=420),
                         ft.Row([t.labeled_control("Hold (ms)", hold, expand=True),
                                 t.labeled_control("Pause after (ms)", after, expand=True)], spacing=10, width=420)]

            def collect():
                out = {"press": sorted(chosen, key=m.KEYS.index)}
                for side in ("left", "right"):
                    d = next(d for d in STICK_DIRECTIONS if (d[0] or "CENTRE") == sticks[side].value)
                    if d[0]:
                        same = side in step and direction_of(step[side])[0] == d[0]
                        out[side] = step[side] if same else list(d[2])
                if hold.value:
                    out["ms"] = max(1, int(hold.value))
                if after.value:
                    out["after"] = int(after.value)
                if step.get("note") or note.value:
                    out["note"] = note.value
                return {k: v for k, v in out.items() if k != "note" or v}

        note = t.field(value=step.get("note", ""), hint="What this step is for")
        controls.append(t.labeled_control("Note (optional)", note))

        def done(e):
            new = collect()
            try:
                m.check_steps([new])
            except m.MacroError as error:
                error_text.value = str(error)
                error_text.update()
                return
            steps[n] = new
            self.save()
            page.pop_dialog()
            self.render_editor()

        error_text = t.text("", 12, t.RED)
        page.show_dialog(t.dialog(
            title=t.text("Edit step", 18),
            content=ft.Column([*controls, error_text], spacing=10, tight=True, width=420),
            actions=[t.button("Cancel", lambda e: page.pop_dialog(), filled=False), t.button("Save", done)]))

    def _summary(self) -> ft.Control:
        try:
            p = m.compile_macro(self.macro)
        except m.MacroError as error:
            return t.text(str(error), 12, t.AMBER)
        loops = "until stopped" if p.loops == 0 else f"x{p.loops}"
        return t.text(f"{len(p.entries)} of {m.MAX_ENTRIES} board steps  ·  run once {p.setup_ms / 1000:g} s  ·  "
                      f"loop {p.loop_ms / 1000:g} s {loops}", 12, t.MUTED)

    def _actions(self) -> ft.Control:
        connected = self.client is not None
        playing = bool(self.board.get("playing"))
        main = (t.button("Stop", self.stop, "stop", color=t.RED) if playing else
                t.button("Play on the board", self.play, "play", disabled=not connected,
                         tooltip=None if connected else "Connect the board first"))
        return ft.Row([main, ft.Row([
            t.icon_button("download", self._export, "Export as a .pokemacro file to share"),
            t.icon_button("trash", lambda e: self._delete(), "Delete this macro"),
        ], spacing=2)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    def _say(self, text: str, color: str = t.MUTED) -> None:
        self.note.value, self.note.color = text, color
        try:
            self.note.update()
        except RuntimeError:
            pass


def direction_of_key(key: str) -> tuple:
    name = key[3:]
    return next(d[2] for d in STICK_DIRECTIONS if d[0] == name)

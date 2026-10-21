"""The controller: a Switch's buttons pressed from this computer through the controller board, and
the macros the board plays on its own clock [pokeldn.pad, docs/gui.md, The controller]."""
from pokeldn.app.i18n import t as tr
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
from gui.localization import error_message
from pokeldn.app import macros
from pokeldn.app.paths import SESSION
from pokeldn.app.runner import Process
from pokeldn.pad import macro as m
from pokeldn.pad import service

# Keyboard keys (Flet key names) to controller keys, used while "Keyboard" is on.
KEYBOARD = {
    "Arrow Up": 'UP', "Arrow Down": 'DOWN', "Arrow Left": 'LEFT', "Arrow Right": 'RIGHT',
    "X": "A", "Z": "B", "S": "X", "A": "Y", "Q": "L", "W": "R", "1": 'ZL', "2": 'ZR',
    "Enter": 'PLUS', "Backspace": 'MINUS', "H": 'HOME', "C": 'CAPTURE',
}
HINT = {v: k.replace("Arrow ", "") for k, v in KEYBOARD.items()}
STICK_DIRECTIONS = [("", tr('controller.centre_45c193', 'Centre'), (0.0, 0.0)), ('UP', tr('controller.up_55490a', 'Up'), (0.0, 1.0)), ('UPRIGHT', tr('controller.up_right_3e0f6f', 'Up-right'), (0.71, 0.71)),
                    ('RIGHT', tr('controller.right_883361', 'Right'), (1.0, 0.0)), ('DOWNRIGHT', tr('controller.down_right_2ba044', 'Down-right'), (0.71, -0.71)),
                    ('DOWN', tr('controller.down_b86d11', 'Down'), (0.0, -1.0)), ('DOWNLEFT', tr('controller.down_left_92b2bc', 'Down-left'), (-0.71, -0.71)),
                    ('LEFT', tr('controller.left_58eb90', 'Left'), (-1.0, 0.0)), ('UPLEFT', tr('controller.up_left_0e99ce', 'Up-left'), (-0.71, 0.71))]
BLUETOOTH_REFUSED = (tr('controller.macos_refused_bluetooth_to_this_program_the_packaged_ap_130da9', 'macOS refused Bluetooth to this program. The packaged app asks for it; from a source checkout, allow Bluetooth for the terminal in System Settings, Privacy & Security.'))


def start_service(on_exit=lambda code: None, popups=None) -> Process | None:
    """The child that holds the Bluetooth link, started unless one with this code already answers; None
    if it did. A service outlives an app that crashed, so one running other code is told to quit. Its pop-ups
    show through `popups`, the app's (pokeldn.app.popups)."""
    if service.running():
        client = service.Client()
        try:
            if client.call("status").get("code") == service.CODE:
                return None
            client.call("quit")
        except service.ServiceError as error:
            raise service.ServiceError(tr('controller.an_older_controller_service_holds_the_bluetooth_link_qu_aa8033', 'an older controller service holds the Bluetooth link; quit every pokeldn window and open the app again')) from error
        finally:
            client.close()
        for _ in range(50):
            if not service.running():
                break
            time.sleep(0.1)
    os.makedirs(SESSION, exist_ok=True)
    # POKELDN_MANAGED_RUN: the child stops when the app's end of its stdin closes (pokeldn.app.runner).
    child = Process(["--module", "pokeldn.pad.service"], str(SESSION),
                    dict(os.environ, POKELDN_MANAGED_RUN="1"), lambda line: None, on_exit, bluetooth=True,
                    popups=popups, label=tr('controller.controller_service_c608fb', 'Controller service'))
    for _ in range(100):
        if service.running() or not child.running:
            break
        time.sleep(0.1)
    return child


def describe(step: dict, macro: m.Macro) -> str:
    if "wait" in step:
        return tr('controller.wait_ms_48e659', 'Wait {value0} ms', value0=step['wait'])
    if "repeat" in step:
        return tr('controller.repeat_times_d20988', 'Repeat {value0} times', value0=step['repeat'])
    keys = step.get("press", [])
    keys = [keys] if isinstance(keys, str) else list(keys)
    for side in ("left", "right"):
        if side in step:
            keys.append(tr('controller.stick_e120fb', '{value0} stick {value1}', value0=tr('controller.stick_side_left', 'Left') if side == 'left' else tr('controller.stick_side_right', 'Right'), value1=direction_of(step[side])[1].lower()))
    return tr('controller.ms_then_ms_a88cbd', '{value0}  ·  {value1} ms, then {value2} ms', value0=' + '.join(keys) or tr('controller.nothing_67e1bc', 'Nothing'), value1=step.get('ms', macro.press_ms), value2=step.get('after', macro.gap_ms))


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
        self.state = tr('controller.not_connected_0303e1', 'Not connected')
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
        self.panes = t.Panes(
            (tr('controller.pane_macros', 'Macros'), "bulletlist", t.panel(ft.Column([
                t.panel_header(tr('controller.macros_866dcd', 'Macros'),
                               t.icon_button("plus", lambda e: self.new(), tr('controller.new_macro_b9a983', 'New macro')),
                               t.icon_button("upload", self._import, tr('controller.import_a_pokemacro_file_13a934', 'Import a .pokemacro file')),
                               t.icon_button("folder", lambda e: open_folder(str(macros.library())),
                                             tr('controller.open_the_macros_folder_10afa1', 'Open the macros folder'))),
                t.fade(self.list),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH)),
            (tr('controller.pane_controller', 'Controller'), "joystick", t.fade(ft.ListView([self.status, self.pad], spacing=t.GAP, padding=ft.Padding(0, 0, 0, 24),
                               expand=True))),
            (tr('controller.pane_macro', 'Macro'), "code", t.panel(ft.Column([
                t.panel_header(tr('controller.macro_cdf16e', 'Macro')),
                self.editor,
                ft.Container(self.footer, padding=ft.Padding(18, 0, 18, 18)),
            ], spacing=0, expand=True), width=t.SESSION_WIDTH)))
        self.control = self.panes.control
        self.render_all()
        app.board_listeners.append(lambda: self.visible and self.render_status())

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
        self.connecting, self.error, self.state = True, "", tr('controller.looking_for_the_board_fff30a', 'Looking for the board...')
        self.render_status()
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self) -> None:
        try:
            for attempt in range(3):   # a service from a closed app may still hold the port while it exits
                try:
                    self.child = start_service(self._child_exit, self.app.popups) or self.child
                    if self.client is None:
                        self.client = service.Client()
                    break
                except ConnectionRefusedError:
                    if attempt == 2:
                        raise
                    time.sleep(1)
            self.client.call("connect")
            reply = self.client.call("status")
            self.board = {**reply.get("status", {}), "link": reply.get("link", "")}
            self.state = tr('controller.connected_229655', 'Connected')
        except (OSError, service.ServiceError) as error:
            self._drop()
            self.state = tr('controller.not_connected_0303e1', 'Not connected')
            self.error = self.error or error_message(error)
        self.connecting = False
        self.app.ui(self.render_status)

    def _child_exit(self, code: int) -> None:
        self._drop()
        self.state = tr('controller.not_connected_0303e1', 'Not connected')
        if code and sys.platform == "darwin" and code in (-6, 134):
            self.error = BLUETOOTH_REFUSED
        self.app.ui(self.render_status)

    def _reconnect(self) -> None:
        """The link dropped (the board lost power moving to the Switch, or went out of range): the
        service finds it again when it advertises."""
        if self.state == tr("controller.connected_229655", "Connected"):
            self.board, self.state, self.error = {}, tr('controller.board_lost_looking_for_it_again_8278e1', 'Board lost: looking for it again...'), ""
            self.app.ui(self.render_status)
        try:
            self.client.call("connect")
        except (OSError, service.ServiceError):
            self.state = tr('controller.board_lost_looking_for_it_again_is_it_plugged_into_the__43e2fa', 'Board lost: looking for it again. Is it plugged into the Switch or a USB power source?')
            self.app.ui(self.render_status)
            return
        self.state, self.error = tr('controller.connected_229655', 'Connected'), ""
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
        self.board, self.state = {}, tr('controller.not_connected_0303e1', 'Not connected')
        self.render_status()

    def _call(self, op: str, **fields) -> dict | None:
        if self.client is None:
            return None
        try:
            return self.client.call(op, **fields)
        except (OSError, service.ServiceError) as error:
            self.error = error_message(error)
            self.app.ui(self.render_status)
            return None

    def _send_later(self, op: str, **fields) -> None:
        self.sender.submit(self._call, op, **fields)

    def _poll(self) -> None:
        while self.visible:
            if self.client is not None and not self.connecting:
                reply = self._call("status")
                if reply is not None and not reply.get("connected"):
                    self._reconnect()
                elif reply is not None:
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
            tr('controller.no_macros_yet_make_one_with_or_import_a_pokemacro_someo_aeace1', 'No macros yet. Make one with +, or import a .pokemacro someone shared.'), 12, t.MUTED),
            padding=10)]

    def _row(self, entry: macros.Entry) -> ft.Control:
        active = self.path is not None and entry.path == self.path
        return ft.Container(ft.Row([
            t.pixel_icon("warning-diamond" if entry.error else "repeat", color=t.AMBER if entry.error else t.MUTED),
            t.text(entry.name, 13, t.TEXT if active else t.SOFT, weight=ft.FontWeight.W_600, expand=True,
                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=10), padding=ft.Padding(10, 8, 10, 8), border_radius=12,
            tooltip=error_message(entry.error) or None, bgcolor=t.SELECTED if active else None,
            on_click=lambda e, p=entry.path: self.open(p))

    def open(self, path) -> None:
        try:
            self.macro, self.path = macros.load(path), path
            self._say("")
        except (OSError, m.MacroError) as error:
            self._say(tr('controller.this_file_does_not_load_1d6a84', 'This file does not load: {value0}', value0=error_message(error)), t.RED)
            return
        self.recording = False
        self.refresh_list()
        self.render_all()
        self.control.update()

    def new(self) -> None:
        macro = m.Macro(name=tr('controller.new_macro_b9a983', 'New macro'), loops=1)
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
                    self._say(tr('controller._6a7768', '{value0}: {value1}', value0=os.path.basename(f.path), value1=error_message(error)), t.RED)
        if last:
            self.open(last)

    async def _export(self, e) -> None:
        if self.macro is None:
            return
        path = await self.app.picker.save_file(dialog_title=tr('controller.export_macro_d0363d', 'Export macro'),
                                               file_name=f"{self.macro.name}{m.EXTENSION}",
                                               file_type=ft.FilePickerFileType.CUSTOM,
                                               allowed_extensions=[m.EXTENSION[1:]])
        if not path:
            return
        path += "" if path.lower().endswith(m.EXTENSION) else m.EXTENSION
        try:
            with open(path, "w", encoding="utf-8") as out:
                out.write(self.macro.dumps())
            self._say(tr('controller.exported_to_58eb1e', 'Exported to {value0}', value0=path))
        except OSError as error:
            self._say(error_message(error), t.RED)

    def _delete(self) -> None:
        def done(e):
            macros.remove(self.path)
            self.path, self.macro = None, None
            self.app.page.pop_dialog()
            self.refresh_list()
            self.render_all()
            self.control.update()

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('controller.delete_this_macro_647eaf', 'Delete this macro?'), 18),
            content=t.text(tr('controller.is_deleted_from_this_computer_export_it_first_to_keep_a_d54293', '{value0} is deleted from this computer. Export it first to keep a file.', value0=self.macro.name),
                           13, t.MUTED, width=380),
            actions=[t.button(tr('controller.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('controller.delete_e2d0a5', 'Delete'), done, color=t.RED)]))

    # Playing

    def play(self, e=None) -> None:
        if self.macro is None:
            return
        try:
            m.compile_macro(self.macro)
        except m.MacroError as error:
            self._say(error_message(error), t.RED)
            return
        self.recording = False

        def run():
            reply = self._call("play", macro=self.macro.dumps())
            if reply:
                self._say(tr('controller.playing_on_the_board_it_keeps_going_if_this_computer_sl_33fc14', 'Playing on the board. It keeps going if this computer sleeps.'))
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
        connected = self.client is not None and self.state == tr("controller.connected_229655", "Connected")
        lost = self.client is not None and not connected and not self.connecting
        board = self.board or {}
        facts = []
        if connected:
            link = board.get("link", "")
            facts.append(t.chip(tr('controller.board_connected_on_c9d52b', 'Board connected on {value0}', value0=link.split(' ')[1]) if link.startswith("serial ")
                                else tr('controller.board_connected_over_bluetooth_dbda11', 'Board connected over Bluetooth'), "check", t.GREEN))
            facts.append(self.where(board))
        action = (t.button(tr('controller.disconnect_acfc5b', 'Disconnect'), self.disconnect, "close", filled=False) if connected else
                  t.button(tr('controller.stop_looking_86f929', 'Stop looking'), self.disconnect, "close", filled=False) if lost else
                  t.button(tr('controller.looking_c1c971', 'Looking...') if self.connecting else tr('controller.connect_1a2303', 'Connect'), self.connect, "zap",
                           disabled=self.connecting))
        body = [ft.Row([ft.Row(facts or [t.text(self.state, 13, t.MUTED)], spacing=6, wrap=True, expand=True),
                        action], vertical_alignment=ft.CrossAxisAlignment.CENTER)]
        if self.error:
            body.append(t.text(self.error, 12, t.RED))
        if not connected and not lost:
            body += self.guidance()
        if board.get("playing"):
            body.append(ft.Row([
                t.badge(tr('controller.macro_running_loop_step_of_ad7131', 'Macro running: loop {value0}, step {value1} of {value2}', value0=board.get('loops_done', 0) + 1, value1=board.get('index', 0) + 1, value2=board.get('count', 0)), t.BLUE, "play"),
                t.button(tr('controller.stop_cae7d5', 'Stop'), self.stop, "stop", color=t.RED)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
        self.status.controls = [t.card(tr('controller.controller_board_2f732b', 'Controller board'), ft.Column(body, spacing=10, tight=True))]
        self.render_footer()
        if update:
            try:
                self.status.update()
                self.footer.update()
            except RuntimeError:
                pass

    def where(self, board: dict) -> ft.Control:
        """Where the board is plugged in. `mounted` says only that some USB host configured it: this
        computer does too, so being on this computer's USB bus is asked first."""
        if board.get("link", "").startswith("serial "):   # a classic board pairs over Bluetooth Classic
            return (t.chip(tr('controller.paired_with_the_switch_81e9d4', 'Paired with the Switch'), "check", t.GREEN) if board.get("mounted") else
                    t.chip(tr('controller.not_paired_on_the_switch_open_controllers_change_grip_o_c8139e', 'Not paired: on the Switch, open Controllers, Change Grip/Order'), "usb", t.AMBER))
        if self.app.controllers:
            return t.chip(tr('controller.plugged_into_this_computer_plug_it_into_the_switch_to_p_4ea75e', 'Plugged into this computer: plug it into the Switch to play'), "usb", t.AMBER)
        if board.get("mounted"):
            return t.chip(tr('controller.plugged_into_the_switch_fb8cf5', 'Plugged into the Switch'), "check", t.GREEN)
        return t.chip(tr('controller.not_plugged_into_the_switch_de9b47', 'Not plugged into the Switch'), "usb", t.AMBER)

    def guidance(self) -> list[ft.Control]:
        """What is plugged in and the next step, while no board is connected."""
        from gui import board
        to_board = t.secondary_button(tr('controller.open_the_board_page_2664cd', 'Open the Board page'), lambda e: self.app.navigate("board"), "cpu")
        if self.app.controllers:
            return [t.text(tr('controller.a_controller_board_is_plugged_into_this_computer_press__656ca1', "A controller board is plugged into this computer. Press Connect to reach it over Bluetooth. To play, plug it into the Switch's USB-C port; it reconnects on its own."),
                           12, t.MUTED)]
        radios = [d for d, ident in self.app.identities.items() if isinstance(ident, board.Identity)]
        if radios:
            return [t.text(tr('controller.the_board_plugged_in_runs_the_wireless_firmware_for_tra_383729', 'The board plugged in runs the wireless firmware, for trades. To use it as a controller, install the Controller firmware on the Board page.'),
                           12, t.MUTED), ft.Row([to_board])]
        return [t.text(tr('controller.no_controller_board_found_an_esp32_s3_with_the_controll_86ae6e', "No controller board found. An ESP32-S3 with the controller firmware plugs into the Switch's USB-C port and this computer reaches it over Bluetooth; a classic ESP32 stays plugged into this computer and pairs with the Switch as a Pro Controller. Install it on the Board page."), 12, t.MUTED), ft.Row([to_board])]

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
            ft.Row([gap, self._arrow(k('UP'), "arrow-up"), gap], spacing=4, tight=True),
            ft.Row([self._arrow(k('LEFT'), "arrow-left"), centre or gap, self._arrow(k('RIGHT'), "arrow-right")],
                   spacing=4, tight=True),
            ft.Row([gap, self._arrow(k('DOWN'), "arrow-down"), gap], spacing=4, tight=True),
        ], spacing=4, tight=True)

    def render_pad(self) -> None:
        b = self._button
        shoulders = ft.Row([
            ft.Row([b('ZL', 'ZL', 64, 34, False), b("L", "L", 64, 34, False)], spacing=6),
            ft.Row([b('MINUS', "-", 34, 34), b('PLUS', "+", 34, 34)], spacing=60),
            ft.Row([b("R", "R", 64, 34, False), b('ZR', 'ZR', 64, 34, False)], spacing=6),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=560)
        face = ft.Column([
            ft.Row([b("X", "X")], alignment=ft.MainAxisAlignment.CENTER, width=140),
            ft.Row([b("Y", "Y"), b("A", "A")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=140),
            ft.Row([b("B", "B")], alignment=ft.MainAxisAlignment.CENTER, width=140),
        ], spacing=0, tight=True)
        middle = ft.Row([
            ft.Column([t.text(tr('controller.left_stick_674e59', 'Left stick'), 11, t.MUTED), self._cross("LS_", b('LSTICK', "L3", 40, 40))],
                      spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            face,
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=560,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        lower = ft.Row([
            ft.Column([t.text(tr('controller.d_pad_126a91', 'D-pad'), 11, t.MUTED), self._cross("", None)], spacing=6,
                      horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            ft.Row([b('CAPTURE', tr('controller.capture_1900b4', 'Capture'), 40, 40, False, "camera"), b('HOME', 'HOME', 40, 40, True, "home")],
                   spacing=24),
            ft.Column([t.text(tr('controller.right_stick_20fcdb', 'Right stick'), 11, t.MUTED), self._cross("RS_", b('RSTICK', "R3", 40, 40))],
                      spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=560,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        options = ft.Row([
            ft.Row([t.switch(self.keyboard, self._keyboard), t.text(tr('controller.keyboard_231681', 'Keyboard'), 13, t.SOFT)], spacing=6, tight=True,
                   tooltip=tr('controller.arrows_for_the_d_pad_x_a_z_b_s_x_a_y_q_l_w_r_1_zl_2_zr__c8b3b3', 'Arrows for the D-pad, X A, Z B, S X, A Y, Q L, W R, 1 ZL, 2 ZR, Enter +, Backspace -, H HOME, C Capture')),
            ft.Row([t.switch(self.recording, self._recording), t.text(tr('controller.record_into_the_macro_0c10a9', 'Record into the macro'), 13, t.SOFT)],
                   spacing=6, tight=True,
                   tooltip=tr('controller.each_press_its_length_and_the_pause_before_the_next_one_100b06', 'Each press, its length and the pause before the next one become steps')),
        ], spacing=24)
        self.pad.controls = [t.card(tr('controller.controller_31df66', 'Controller'), ft.Column([
            ft.Container(ft.Column([shoulders, middle, lower], spacing=22, tight=True,
                                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                         padding=ft.Padding(0, 8, 0, 8), alignment=ft.Alignment.CENTER),
            options,
        ], spacing=16, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            tr('controller.hold_a_button_to_hold_it_on_the_console_501072', 'Hold a button to hold it on the console.'))]

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
            self.editor.controls = [t.text(tr('controller.pick_a_macro_on_the_left_or_make_a_new_one_with_3cf0ac', 'Pick a macro on the left, or make a new one with +.'), 13, t.MUTED)]
        else:
            self.editor.controls = [
                self._text_field(tr('controller.name_dcd1d5', 'Name'), mac.name,
                                 lambda v: setattr(mac, "name", v or tr('controller.macro_cdf16e', 'Macro')), rename=True),
                self._text_field(tr('controller.description_526e00', 'Description'), mac.description, lambda v: setattr(mac, "description", v),
                                 multiline=True),
                ft.Row([self._number(tr('controller.press_ms_1f75f4', 'Press (ms)'), mac.press_ms, lambda v: setattr(mac, "press_ms", max(1, v)),
                                     tr('controller.how_long_a_step_holds_its_buttons_unless_it_says_otherw_f1c099', 'How long a step holds its buttons unless it says otherwise')),
                        self._number(tr('controller.pause_after_ms_212f61', 'Pause after (ms)'), mac.gap_ms, lambda v: setattr(mac, "gap_ms", v),
                                     tr('controller.the_pause_after_each_step_unless_it_says_otherwise_c03c51', 'The pause after each step unless it says otherwise'))], spacing=10),
                self._number(tr('controller.repeat_the_loop_0_until_stopped_0676a3', 'Repeat the loop (0 = until stopped)'), mac.loops,
                             lambda v: setattr(mac, "loops", min(v, 1_000_000))),
                self._section(tr('controller.run_once_5f041f', 'Run once'), "setup", mac.setup),
                self._section(tr('controller.loop_f2f6a0', 'Loop'), "loop", mac.loop),
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

    def _text_field(self, label, value, setter, multiline=False, *, rename=False) -> ft.Control:
        def changed(e):
            setter(e.control.value)
            self.save()
            if rename:
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
        rec = t.chip(tr('controller.recording_here_cce87d', 'Recording here'), "circle-info", t.RED) if self.recording and self.target == target else \
            ft.Container(t.text(tr('controller.record_here_ea3c50', 'Record here'), 11, t.FAINT), on_click=lambda e: self._target(target),
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
                label += tr('controller._fc0bd4', '  ·  {value0}', value0=step['note'])
            rows.append(ft.Container(ft.Row([
                t.pixel_icon(icon, size=12, color=t.MUTED),
                t.text(label, 12, t.SOFT, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                t.icon_button("arrow-up", lambda e, s=steps, n=i: self._move(s, n, -1), tr('controller.move_up_c66feb', 'Move up'),
                              disabled=i == 0),
                t.icon_button("edit", lambda e, s=steps, n=i: self._edit(s, n), tr('controller.edit_464c4f', 'Edit')),
                t.icon_button("trash", lambda e, s=steps, n=i: self._remove_step(s, n), tr('controller.remove_c3812f', 'Remove')),
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
        return ft.Row([t.link_button(tr('controller.press_2e0708', '+ Press'), lambda e: add("press")),
                       t.link_button(tr('controller.wait_1d24d7', '+ Wait'), lambda e: add("wait")),
                       t.link_button(tr('controller.repeat_402130', '+ Repeat'), lambda e: add("repeat"))], spacing=0)

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
            controls.append(t.labeled_control(tr('controller.wait_ms_a9c19b', 'Wait (ms)'), wait))

            def collect():
                return {"wait": int(wait.value or 0), **({"note": note.value} if note.value else {})}
        elif "repeat" in step:
            count = t.field(value=str(step["repeat"]), digits=True, limit=5)
            controls.append(t.labeled_control(tr('controller.times_0c0fd3', 'Times'), count))

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
            for side, label in (("left", tr('controller.left_stick_674e59', 'Left stick')), ("right", tr('controller.right_stick_20fcdb', 'Right stick'))):
                current = direction_of(step[side])[0] if side in step else ""
                sticks[side] = t.dropdown([(d[0] or 'CENTRE', d[1]) for d in STICK_DIRECTIONS],
                                          current or 'CENTRE')
                controls_side = t.labeled_control(label, sticks[side], expand=True)
                sticks[side + "_row"] = controls_side
            hold = t.field(value=str(step.get("ms", "")), digits=True, limit=7,
                           hint=tr('controller.the_macro_s_f555b8', "{value0}, the macro's", value0=self.macro.press_ms))
            after = t.field(value=str(step.get("after", "")), digits=True, limit=7,
                            hint=tr('controller.the_macro_s_f555b8', "{value0}, the macro's", value0=self.macro.gap_ms))
            controls += [t.text(tr('controller.buttons_held_together_37a294', 'Buttons held together'), 11, t.MUTED), chips,
                         ft.Row([sticks["left_row"], sticks["right_row"]], spacing=10, width=420),
                         ft.Row([t.labeled_control(tr('controller.hold_ms_16f67e', 'Hold (ms)'), hold, expand=True),
                                 t.labeled_control(tr('controller.pause_after_ms_212f61', 'Pause after (ms)'), after, expand=True)], spacing=10, width=420)]

            def collect():
                out = {"press": sorted(chosen, key=m.KEYS.index)}
                for side in ("left", "right"):
                    d = next(d for d in STICK_DIRECTIONS if (d[0] or 'CENTRE') == sticks[side].value)
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

        note = t.field(value=step.get("note", ""), hint=tr('controller.what_this_step_is_for_0d1709', 'What this step is for'))
        controls.append(t.labeled_control(tr('controller.note_optional_f9b73e', 'Note (optional)'), note))

        def done(e):
            new = collect()
            try:
                m.check_steps([new])
            except m.MacroError as error:
                error_text.value = error_message(error)
                error_text.update()
                return
            steps[n] = new
            self.save()
            page.pop_dialog()
            self.render_editor()

        error_text = t.text("", 12, t.RED)
        page.show_dialog(t.dialog(
            title=t.text(tr('controller.edit_step_c5279a', 'Edit step'), 18),
            content=ft.Column([*controls, error_text], spacing=10, tight=True, width=420),
            actions=[t.button(tr('controller.cancel_19766e', 'Cancel'), lambda e: page.pop_dialog(), filled=False), t.button(tr('controller.save_1509f5', 'Save'), done)]))

    def _summary(self) -> ft.Control:
        try:
            p = m.compile_macro(self.macro)
        except m.MacroError as error:
            return t.text(error_message(error), 12, t.AMBER)
        loops = tr('controller.until_stopped_ca2053', 'until stopped') if p.loops == 0 else f"x{p.loops}"
        return t.text(tr('controller.of_board_steps_run_once_s_loop_s_3d534d', '{value0} of {value1} board steps  ·  run once {value2:g} s  ·  loop {value3:g} s {value4}', value0=len(p.entries), value1=m.MAX_ENTRIES, value2=p.setup_ms / 1000, value3=p.loop_ms / 1000, value4=loops), 12, t.MUTED)

    def _actions(self) -> ft.Control:
        connected = self.client is not None
        playing = bool(self.board.get("playing"))
        main = (t.button(tr('controller.stop_cae7d5', 'Stop'), self.stop, "stop", color=t.RED) if playing else
                t.button(tr('controller.play_on_the_board_56ea82', 'Play on the board'), self.play, "play", disabled=not connected,
                         tooltip=None if connected else tr('controller.connect_the_board_first_feea04', 'Connect the board first')))
        return ft.Row([main, ft.Row([
            t.icon_button("download", self._export, tr('controller.export_as_a_pokemacro_file_to_share_c4b552', 'Export as a .pokemacro file to share')),
            t.icon_button("trash", lambda e: self._delete(), tr('controller.delete_this_macro_ef52c4', 'Delete this macro')),
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

"""Every board plugged into this computer: what it runs, whether that is current, and the firmware it
can run instead [docs/gui.md, Boards and firmware]."""
import os
import re
import sys
import threading
import time
from dataclasses import dataclass

import flet as ft

from gui import board
from gui.app import NO_FIRMWARE, PORT_BUSY, PORT_DENIED
from pokeldn.pad import service
from pokeldn.app import runner
from pokeldn.app.paths import SESSION
from gui import drop, theme as t
from gui.views.widgets import CodeBlock, Log, PixelActivity

PERCENT = re.compile(r"(\d{1,3}(?:\.\d)?)\s?%")
CHIP = re.compile(r"Firmware for (ESP32(?:-S3|-C3|-C6)?):")

# An S3 running the controller firmware has no serial port; the list shows it under this key.
CONTROLLER = "usb-controller"

PROBLEMS = ("wrong-port", "busy", "denied", "old")


@dataclass
class Facts:
    """What the page knows about one board."""
    key: str
    kind: str = ""          # radio, pad, or "" for no pokeldn firmware
    version: str = ""
    chip: str = ""
    state: str = "checking"   # checking, ready, none, old, wrong-port, busy, denied, unknown
    detail: str = ""
    port: board.Port | None = None
    mac: str = ""

    @property
    def firmware(self) -> board.Firmware | None:
        return board.FIRMWARE_BY_KIND.get(self.kind)

    @property
    def update(self) -> str:
        return board.update_for(self.version, self.kind, self.chip) if self.state == "ready" else ""


class BoardView:
    def __init__(self, app):
        self.app = app
        self.ports: list[board.Port] = []
        self.selected: str = ""
        self.visible = False
        self.downloading = False
        self.installing = ""        # the firmware being written, from the press until the board answers
        self.flash_kind = "radio"
        self.pad_child = None
        self.pad: dict | None = None    # the S3 controller's status over Bluetooth
        self.pad_error = ""
        self.pad_checking = False
        self.list = ft.ListView(spacing=4, padding=8, expand=True)
        self.detail = ft.Column(spacing=t.GAP)
        self.log = Log(app.page, "Checks and installs show their output here.")
        self.progress = ft.ProgressBar(value=None, color=t.BLUE, bgcolor=t.FIELD, height=4, border_radius=2)
        self.progress_text = t.text("", 12, t.MUTED)
        self.control = ft.Row([
            t.panel(ft.Column([
                t.panel_header("Boards", t.icon_button("refresh", lambda e: self.scan(), "Look again")),
                t.fade(self.list),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH),
            t.fade(ft.ListView([self.detail], padding=ft.Padding(0, 0, 0, 24), expand=True)),
            t.panel(ft.Column([t.panel_header("Activity"),
                               ft.Container(self.log.control, padding=16, expand=True)],
                              spacing=0, expand=True), width=t.SESSION_WIDTH),
        ], spacing=t.GAP, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        app.board_listeners.append(self._checked)

    # The boards present, polled while the page is open so a board shows up when it is plugged in

    def enter(self, select: str = "", **_) -> None:
        self.selected = select or self.selected
        self.scan(update=False)
        if not self.visible:
            self.visible = True
            threading.Thread(target=self._poll, daemon=True).start()

    def leave(self) -> None:
        self.visible = False

    def _poll(self) -> None:
        while self.visible:
            time.sleep(2)
            present = board.ports()
            if sys.platform == "win32":
                hidden = [] if present else board.bridges_without_driver()
                if hidden != self.app.hidden_bridges:
                    self.app.hidden_bridges = hidden
                    self.app.ui(self.scan)
                    continue
            if self.visible and [p.device for p in present] != [p.device for p in self.ports]:
                self.app.ui(self.scan)

    def keys(self) -> list[str]:
        return [p.device for p in self.ports] + [CONTROLLER] * bool(self.app.controllers)

    def scan(self, update: bool = True) -> None:
        self.ports = board.ports()
        if not self.app.controllers:
            self.pad, self.pad_error = None, ""
        keys = self.keys()
        if self.selected not in keys:
            self.selected = self.app.radio_port(self.ports) or (keys[0] if keys else "")
        self._check_selected()
        self.render()
        if update:
            self.control.update()

    def _check_selected(self) -> None:
        if self.installing or self.app.busy:
            return
        if self.selected == CONTROLLER:
            if self.pad is None and not self.pad_error and not self.pad_checking:
                self._check_pad()
        elif self.selected and self.selected not in self.app.identities:
            self.log.add(f"[app] Checking {self.selected}; the board may restart.")
            self.app.check_board(self.selected, log=self.log.add)

    def _checked(self) -> None:
        if self.visible:
            self.scan()

    def port(self) -> board.Port | None:
        return next((p for p in self.ports if p.device == self.selected), None)

    # What each board is

    def facts(self, key: str) -> Facts:
        if key == CONTROLLER:
            f = Facts(key, "pad", chip="ESP32-S3")
            if self.pad is not None:
                f.version, f.state = self.pad.get("version", ""), "ready"
            elif self.pad_error:
                f.state, f.detail = "unknown", self.pad_error
            return f
        port = next((p for p in self.ports if p.device == key), None)
        f = Facts(key, port=port, chip=self.app.chips.get(key, ""))
        ident = self.app.identities.get(key)
        if isinstance(ident, board.Identity):
            f.kind, f.version, f.mac = "radio", ident.firmware_version, ident.sta_mac
            f.chip = ident.chip or f.chip
            f.state = "ready" if ident.current else "old"
        elif isinstance(ident, board.PadIdentity):
            f.kind, f.version, f.chip, f.state = "pad", ident.version, "ESP32", "ready"
        elif ident in (PORT_BUSY, PORT_DENIED, NO_FIRMWARE):
            status = self.app.board_status(self.ports, key)
            f.state = {"busy": "busy", "denied": "denied", "wrong-port": "wrong-port"}.get(status.state, "none")
            f.detail = status.detail
        return f

    def name_of(self, f: Facts) -> str:
        if f.mac and (name := self.app.settings.board_names.get(f.mac)):
            return name
        return f"{f.chip} board" if f.chip else "ESP32 board"

    def line(self, f: Facts) -> str:
        """The firmware and its version, as the list and the header say it."""
        if f.state == "checking":
            return "Checking..."
        if f.state in ("busy", "denied", "wrong-port"):
            return "Needs attention"
        if f.firmware is None:
            return "No pokeldn firmware"
        return f"{f.firmware.name} {f.version}".strip()

    # The page

    def render(self) -> None:
        keys = self.keys()
        session_port = self.app.radio_port(self.ports)
        rows = []
        for key in keys:
            f = self.facts(key)
            active = key == self.selected
            dot = (t.BLUE if f.update else t.GREEN if f.state == "ready" else
                   t.FAINT if f.state in ("checking", "unknown") else t.RED)
            rows.append(ft.Container(ft.Row([
                t.pixel_icon(f.firmware.icon if f.firmware else "cpu", color=t.BLUE if active else t.FAINT),
                ft.Column([
                    t.text(self.name_of(f), 13, t.TEXT if active else t.SOFT, weight=ft.FontWeight.W_600),
                    t.text(self.line(f), 11, t.MUTED),
                ], spacing=1, expand=True),
                t.badge("In use", t.BLUE, "checkbox-on") if len(self.ports) > 1 and key == session_port else
                ft.Container(width=8, height=8, border_radius=4, bgcolor=dot),
            ], spacing=10), padding=ft.Padding(10, 8, 10, 8), border_radius=12,
                bgcolor=t.SELECTED if active else None, on_click=lambda e, k=key: self._select(k)))
        if not rows:
            rows.append(ft.Container(ft.Column([
                t.pixel_icon("usb", color=t.FAINT),
                t.text("No board found", 13, t.MUTED, weight=ft.FontWeight.W_600),
                t.text("Plug it into this computer with a data cable. It shows up here on its own.", 12,
                       t.FAINT, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6), padding=24))
        self.list.controls = rows
        if self.selected:
            f = self.facts(self.selected)
            cards = [self.header(f), self.firmware_card(f), self.about_card(f)]
            if f.state in PROBLEMS or f.state == "none":
                cards.append(self.help_card())
        else:
            cards = [self.empty_card(), self.help_card()]
        self.detail.controls = cards

    def _select(self, key: str) -> None:
        if not self.installing:
            self.progress_text.value = ""
        self.selected = key
        self._check_selected()
        self.render()
        self.control.update()

    def empty_card(self) -> ft.Control:
        status = self.app.board_status(self.ports)
        return t.surface(ft.Container(ft.Row([
            t.pixel_icon("usb", size=48, color=t.FAINT),
            ft.Column([t.text(status.title, 17, weight=ft.FontWeight.W_600),
                       t.text(status.detail, 13, t.MUTED)], spacing=2, expand=True),
        ], spacing=14), padding=ft.Padding(18, 16, 18, 18)))

    def header(self, f: Facts) -> ft.Control:
        """Name, firmware and version, one status line and the one action that status calls for."""
        subtitle = " · ".join(x for x in (self.line(f) if f.firmware else "", f.chip,
                                          "USB" if f.key == CONTROLLER or f.port else "") if x)
        busy = self.app.busy or bool(self.installing)
        action: list[ft.Control] = []
        if self.installing:
            icon, color, title, detail = None, t.BLUE, f"Installing {board.FIRMWARE_BY_KIND[self.installing].name} firmware", \
                "Keep the board plugged in. About a minute."
        elif f.state == "checking":
            icon, color, title, detail = None, t.BLUE, "Checking the board", (
                "Asking the board over Bluetooth for its firmware version." if f.key == CONTROLLER
                else "Asking the board for its firmware.")
        elif f.state == "unknown":
            icon, color, title, detail = "circle-info", t.AMBER, "Version unknown", f.detail
            action.append(t.secondary_button("Check again", lambda e: self._check_pad(), "refresh",
                                             disabled=busy or self.pad_checking))
        elif f.state == "none":
            radio = board.FIRMWARE_BY_KIND["radio"]
            icon, color, title, detail = "warning-diamond", t.AMBER, "No pokeldn firmware", (
                "Install a firmware below. The Wireless firmware is the one every Games tool needs.")
            action.append(t.button(f"Install {radio.name}", lambda e: self.confirm(radio), "download",
                                   disabled=busy))
        elif f.state == "old":
            icon, color, title, detail = "warning-diamond", t.AMBER, "Update required", (
                "This firmware speaks an older protocol than this app. Update it to use the board.")
            action.append(t.button("Update", lambda e: self.install(f.kind), "download", disabled=busy))
        elif f.state in PROBLEMS:
            status = self.app.board_status(self.ports, f.key)
            icon, color, title, detail = "warning-diamond", t.RED, status.title, status.detail
            action.append(t.secondary_button("Check again", self._identify, "refresh", disabled=busy))
        elif f.update:
            icon, color, title, detail = "download", t.BLUE, f"Update available: {f.update}", (
                f"{f.firmware.name} firmware {f.update} is included with this app. This board runs {f.version}.")
            action.append(t.button("Update", lambda e: self.install(f.kind), "download", disabled=busy))
        else:
            icon, color, title, detail = "checkbox-on", t.GREEN, "Up to date", (
                f"{f.firmware.name} firmware {f.version} is the newest this app includes." if f.version else
                f"{f.firmware.name} firmware.")
        if not self.installing and f.state == "ready":
            if f.kind == "radio":
                several = len(self.ports) > 1
                if several and f.key != self.app.radio_port(self.ports):
                    action.append(t.secondary_button("Use for trades", self._use, "check"))
                action.append(t.button("Go to Games", lambda e: self.app.navigate("games"), "gamepad",
                                       filled=not f.update))
            elif f.kind == "pad":
                action.append(t.button("Open Control", lambda e: self.app.navigate("controller"), "joystick",
                                       filled=not f.update))
        lead = (PixelActivity("Working") if icon is None else t.pixel_icon(icon, size=18, color=color))
        status_row = ft.Row([
            ft.Container(lead, width=20, height=20, alignment=ft.Alignment.CENTER),
            ft.Column([t.text(title, 14, weight=ft.FontWeight.W_600),
                       *([t.text(detail, 12, t.MUTED)] if detail else [])], spacing=2, expand=True),
            *action,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        body = [
            ft.Row([
                t.pixel_icon(f.firmware.icon if f.firmware else "cpu", size=48, color=t.BLUE),
                ft.Column([t.text(self.name_of(f), 20, weight=ft.FontWeight.W_600),
                           t.text(subtitle or "pokeldn board", 13, t.MUTED)], spacing=2, expand=True),
            ], spacing=14),
            ft.Divider(height=1, color=ft.Colors.with_opacity(0.08, "#FFFFFF")),
            status_row,
        ]
        if self.installing or self.progress_text.value:
            body.append(ft.Column([self.progress, self.progress_text], spacing=6))
        return t.surface(ft.Container(ft.Column(body, spacing=14, tight=True), padding=ft.Padding(20, 18, 20, 18)))

    def firmware_card(self, f: Facts) -> ft.Control:
        busy = self.app.busy or bool(self.installing) or f.state in ("checking", "busy", "denied")
        rows = []
        for fw in board.FIRMWARES:
            installed = fw.kind == f.kind and f.state in ("ready", "old")
            fits = not f.chip or f.chip in fw.chips
            if installed:
                trailing = t.chip(f"Installed · {f.version}" if f.version else "Installed", "check", t.GREEN)
            elif not fits:
                trailing = t.text(f"Not available on {f.chip}", 12, t.FAINT)
            else:
                trailing = t.secondary_button("Install", lambda e, w=fw: self.confirm(w), "download",
                                              disabled=busy or not self.available(fw))
            rows.append(ft.Container(ft.Row([
                t.pixel_icon(fw.icon, size=24, color=t.BLUE if installed else t.MUTED),
                ft.Column([t.text(fw.name, 14, weight=ft.FontWeight.W_600),
                           t.text(fw.summary, 12, t.MUTED)], spacing=2, expand=True),
                trailing,
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding(12, 10, 12, 10), border_radius=12,
                bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF") if installed else None))
        footer = [t.link_button("Install from a file...", self._choose_file)]
        if not all(self.available(fw) for fw in board.FIRMWARES):
            footer.insert(0, t.secondary_button("Downloading..." if self.downloading else "Download the firmware",
                                                self._download, "download", disabled=self.downloading))
            rows.append(t.text("This copy of the app has no firmware images (a copy run from source). Download "
                               "the released ones; no ESP-IDF needed.", 12, t.AMBER))
        rows.append(ft.Row(footer, spacing=8))
        return drop.target(t.card("Firmware", ft.Column(rows, spacing=4),
                                  "A board runs one firmware at a time. Switching takes about a minute, and you "
                                  "can switch back whenever you like."), self._dropped)

    def about_card(self, f: Facts) -> ft.Control:
        def info(label, value):
            return ft.Row([t.text(label, 12, t.MUTED, width=110),
                           value if isinstance(value, ft.Control) else t.text(value, 13)],
                          vertical_alignment=ft.CrossAxisAlignment.CENTER)

        rows = [info("Chip", f.chip or "Unknown"),
                info("Firmware", f"{f.firmware.name} {f.version}".strip() if f.firmware else "None")]
        if f.key == CONTROLLER:
            rows.append(info("Connection", "USB to this computer, as a controller; Bluetooth to this app"))
        elif f.port:
            rows += [info("Connection", f"USB serial, {f.port.bridge}"),
                     info("Port", t.text(f.port.device, 13, font_family=t.MONO))]
        if f.mac:
            rows.append(info("Wi-Fi MAC", t.text(f.mac, 13, font_family=t.MONO)))
            name = t.field(value=self.app.settings.board_names.get(f.mac, ""), hint="Living room, spare...",
                           width=220, on_submit=lambda e: self._rename(e.control, f.mac))
            rows.append(info("Name", ft.Row([name, t.icon_button("check", lambda e: self._rename(name, f.mac),
                                                                 "Save the name")], spacing=4)))
            rows.append(ft.Row([t.secondary_button("Blink the LED", self._blink, "lightbulb",
                                                   disabled=self.app.busy)]))
        return t.card("About this board", ft.Column(rows, spacing=10))

    def _rename(self, field, mac: str) -> None:
        names = self.app.settings.board_names
        if field.value.strip():
            names[mac] = field.value.strip()
        else:
            names.pop(mac, None)
        self.app.settings.save()
        self.render()
        self.control.update()

    def _use(self, e) -> None:
        self.app.settings.radio_port = self.selected
        self.app.settings.save()
        self.log.add(f"[app] Trades now use {self.selected}.")
        self.render()
        self.control.update()

    def _identify(self, e, blink: bool = False) -> None:
        if self.app.busy:
            return
        self.app.identities.pop(self.selected, None)
        self.log.add(f"[app] Checking {self.selected}; the board may restart.")
        self.app.check_board(self.selected, blink=blink, log=self.log.add)
        self.render()
        self.control.update()

    def _blink(self, e) -> None:
        self._identify(e, blink=True)

    # The controller's version, over Bluetooth: it has no serial port

    def _check_pad(self) -> None:
        self.pad_checking, self.pad_error = True, ""
        threading.Thread(target=self._check_pad_work, daemon=True).start()
        if self.visible:
            self.render()
            self.control.update()

    def _check_pad_work(self) -> None:
        from gui.views.controller import BLUETOOTH_REFUSED, start_service
        refused = []
        try:
            # Kept: the child stops when its Process object, and with it the stdin pipe, goes.
            self.pad_child = start_service(lambda code: refused.append(
                sys.platform == "darwin" and code in (-6, 134))) or self.pad_child
            client = service.Client()
            try:
                client.call("connect")
                self.pad = client.call("status").get("status", {})
            finally:
                client.close()
        except (OSError, service.ServiceError) as error:
            self.pad = None
            self.pad_error = (BLUETOOTH_REFUSED if any(refused) else
                              f"The board did not answer over Bluetooth ({error}). Is Bluetooth on?")
        self.pad_checking = False
        self.app.ui(self._checked)

    # Installing

    def available(self, fw: board.Firmware) -> bool:
        return any(os.path.isfile(board.image_for(fw.kind, chip)) for chip in fw.chips)

    def confirm(self, fw: board.Firmware, image: str = "") -> None:
        f = self.facts(self.selected)
        lines = [fw.summary]
        if f.firmware and f.firmware.kind != fw.kind and f.state == "ready":
            lines.append(f"It replaces the {f.firmware.name} firmware: the board stops working as "
                         f"{f.firmware.role} until you install {f.firmware.name} again.")
        lines.append("Keep the board plugged into this computer. It takes about a minute.")
        if image:
            lines.append(f"From the file {os.path.basename(image)}.")

        def go(e):
            self.app.page.pop_dialog()
            self.install(fw.kind, image)

        self.app.page.show_dialog(t.dialog(
            title=t.text(f"Install {fw.name} firmware?", 17, weight=ft.FontWeight.W_600),
            content=ft.Column([t.text(line, 13, t.MUTED) for line in lines], tight=True, spacing=8, width=420),
            actions=[t.secondary_button("Cancel", lambda e: self.app.page.pop_dialog()),
                     t.button("Install", go, "download")]))

    def install(self, kind: str, image: str = "") -> None:
        if self.app.busy or self.installing:
            return
        self.installing = kind
        self.progress.value = None
        self.progress_text.value, self.progress_text.color = "Starting...", t.MUTED
        self.log.clear()
        if self.selected == CONTROLLER:
            self.log.add("[app] Asking the board over Bluetooth to restart for installing.")
            self.progress_text.value = "Asking the board to restart for installing..."
            threading.Thread(target=self._loader_work, args=(image,), daemon=True).start()
        else:   # a serial port: esptool resets the chip into its loader
            self._flash(kind, image)
        self.render()
        self.control.update()

    def _loader_work(self, image: str) -> None:
        from gui.views.controller import BLUETOOTH_REFUSED, start_service
        before = {p.device for p in board.ports()}
        refused = []
        try:
            self.pad_child = start_service(lambda code: refused.append(
                sys.platform == "darwin" and code in (-6, 134))) or self.pad_child
            client = service.Client()
            try:
                client.call("connect")
                client.call("download")
            finally:
                client.close()
        except (OSError, service.ServiceError) as error:
            self._failed(BLUETOOTH_REFUSED if any(refused) else f"The board did not answer over Bluetooth "
                                                                 f"({error}).")
            return
        self.app.ui(lambda: setattr(self.progress_text, "value", "Waiting for the board to restart...")
                    or self.progress_text.update())
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            fresh = [p for p in board.ports() if p.native and p.device not in before]
            if fresh:
                self.app.ui(lambda: self._from_loader(fresh[0].device, image))
                return
            time.sleep(0.5)
        self._failed("The board did not come back for installing.")

    def _from_loader(self, device: str, image: str) -> None:
        self.selected = device
        self.ports = board.ports()
        self.log.add(f"[app] The board restarted for installing on {device}.")
        self._flash(self.installing, image, from_loader=True)

    def _flash(self, kind: str, image: str = "", from_loader: bool = False) -> None:
        self.flash_kind = kind
        args = ["--module", "gui.board", "--port", self.selected, "--kind", kind]
        if from_loader:
            args.append("--from-loader")
        if image:
            args += ["--firmware", image]
        self.log.add(f"[app] Installing {board.FIRMWARE_BY_KIND[kind].name} firmware on {self.selected}.")
        self.progress_text.value = "Connecting..."
        env = dict(os.environ, NO_COLOR="1", PYTHONUNBUFFERED="1")
        env.pop("POKELDN_RADIO", None)
        self.app.process_label = "flash"
        self.app.process = runner.Process(args, str(SESSION), env, self._flash_line, self._flashed)

    def _flash_line(self, line: str) -> None:
        self.log.add(line)
        if chip := CHIP.search(line):
            self.app.chips[self.selected] = chip[1]
        found = PERCENT.findall(line)
        if found and "Writing" in line:
            value = min(float(found[-1]), 100.0) / 100

            def show():
                self.progress.value = value
                self.progress_text.value = f"Writing {value:.0%}"
                self.progress.update()
                self.progress_text.update()
            self.app.ui(show)

    def _flashed(self, code: int) -> None:
        device, kind = self.selected, self.flash_kind

        def done():
            self.installing = ""
            self.app.identities.pop(device, None)
            if code:
                self._failed("The install did not finish.")
                return
            self.progress.value = 1
            self.progress_text.color = t.GREEN
            self.progress_text.value = (
                "Installed. Plug the board into the Switch's USB-C port and open Control." if kind == "pad"
                else "Installed. Checking the board...")
            self.pad, self.pad_error = None, ""
            self.render()
            self.control.update()
            # A native-USB board comes back under a new port name, or as a controller with none.
            threading.Timer(3.0, lambda: self.app.ui(self._after_install)).start()
        self.app.ui(done)

    def _after_install(self) -> None:
        self.selected = "" if self.selected not in [p.device for p in board.ports()] else self.selected
        self.scan()

    def _failed(self, why: str) -> None:
        def show():
            self.installing = ""
            self.log.add(f"[app] {why}")
            self.progress.value = 0
            self.progress_text.color = t.RED
            self.progress_text.value = (
                f"{why} Unplug the board, hold its BOOT button while plugging it back in, let go, then choose "
                "Install again on the board that appears. On a board with two USB ports, use the one marked USB.")
            self.render()
            self.control.update()
        self.app.ui(show)

    def _dropped(self, paths: list[str]) -> None:
        """A firmware image dropped on the Firmware card installs it, after the same confirmation."""
        path = next((p for p in paths if drop.suffix(p) == "bin"), "")
        if path and not self.app.busy:
            self._confirm_file(path)

    async def _choose_file(self, e) -> None:
        files = await self.app.picker.pick_files(allowed_extensions=["bin"],
                                                 file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            self._confirm_file(files[0].path)

    def _confirm_file(self, path: str) -> None:
        project, version = board.image_info(path)
        kind = board.PROJECTS.get(project)
        if kind is None:
            self.log.add(f"[app] {os.path.basename(path)} is not a pokeldn firmware image.")
            return
        self.confirm(board.FIRMWARE_BY_KIND[kind], path)

    def _download(self, e) -> None:
        self.downloading = True
        self.render()
        self.control.update()

        def work():
            try:
                tag = board.download_firmware(self.log.add)
                self.log.add(f"[app] Firmware from {tag} is ready.")
            except Exception as error:
                self.log.add(f"[app] Could not download the firmware: {error}")
            finally:
                self.downloading = False
                self.app.ui(lambda: (self.render(), self.control.update()))

        threading.Thread(target=work, daemon=True).start()

    def help_card(self) -> ft.Control:
        def link(label, url):
            return t.secondary_button(label, lambda e: self.app.page.run_task(self.app.open_url, url),
                                      "external-link")

        lines = [t.text("Try another cable or USB port. Many cables only charge.", 13)]
        if sys.platform == "win32":
            lines += [
                t.text("Windows needs the driver for the board's USB chip, printed on the chip next to the "
                       "USB socket (CP2102 or CH340):", 13),
                ft.Row([link("CP210x driver", board.DRIVERS["Silicon Labs CP210x"]),
                        link("CH340 driver", board.DRIVERS["WCH CH340"])], spacing=6, wrap=True),
                t.text(f"CP210x: {board.DRIVER_STEPS['Silicon Labs CP210x']}", 13, t.MUTED),
                t.text(f"CH340: {board.DRIVER_STEPS['WCH CH340']}", 13, t.MUTED)]
        elif sys.platform.startswith("linux"):
            lines += [
                t.text("Allow serial ports, then log out and back in:", 13),
                CodeBlock(self.app, "sudo usermod -aG dialout $USER").control,
                t.text("Arch and its derivatives name the group uucp instead of dialout.", 13, t.MUTED)]
        lines += [
            t.text("Use a classic ESP32 (ESP32-D0WD, WROOM-32E), or an ESP32-S3, C3 or C6 through its native USB "
                   "port, the one marked USB. S2 boards are not supported.", 13, t.MUTED),
            t.text("An install stuck on Connecting: hold the board's BOOT button until writing starts.", 13,
                   t.MUTED),
            t.text("A controller board is listed only while it is plugged into this computer.", 13, t.MUTED)]
        return t.card("Board not listed, or not answering?", ft.Column(lines, spacing=8))

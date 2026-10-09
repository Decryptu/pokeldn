import os
import re
import sys
import threading
import time

import flet as ft

from gui import board
from gui.app import BoardStatus
from pokeldn.app import runner
from pokeldn.app.paths import SESSION
from gui import drop, theme as t
from gui.views.widgets import CodeBlock, Log, PixelActivity

PERCENT = re.compile(r"(\d{1,3}(?:\.\d)?)\s?%")
CHIP = re.compile(r"Firmware for (ESP32(?:-S3|-C3|-C6)?):")

FLASH_STEPS = [
    "ESP32-S3, C3 or C6 with two USB ports: plug into the one marked USB, not COM or UART.",
    "Press Flash. The app picks the firmware for your chip and checks the board afterwards.",
    "Stuck on 'Connecting'? Hold the board's BOOT button until writing starts, then let go.",
]

STATE_LOOK = {   # state -> icon, color
    "ready": ("checkbox-on", t.GREEN),
    "checking": ("refresh", t.BLUE),
    "missing": ("usb", t.MUTED),
    "choose": ("cpu", t.BLUE),
}


class BoardView:
    def __init__(self, app):
        self.app = app
        self.ports: list[board.Port] = []
        self.selected: str = ""
        self.visible = False
        self.downloading = False
        self.list = ft.ListView(spacing=4, padding=8, expand=True)
        self.detail = ft.Column(spacing=t.GAP)
        self.log = Log(app.page, "Checks and flashing show their output here.")
        self.progress = ft.ProgressBar(value=0, color=t.BLUE, bgcolor=t.FIELD, height=4, border_radius=0, visible=False)
        self.progress_text = t.text("", 12, t.MUTED)
        self.control = ft.Row([
            t.panel(ft.Column([
                t.panel_header("Boards", t.icon_button("refresh", lambda e: self.scan(), "Scan again")),
                t.fade(self.list),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH),
            t.fade(ft.ListView([self.detail], padding=ft.Padding(0, 0, 0, 24), expand=True)),
            t.panel(ft.Column([t.panel_header("Activity"),
                               ft.Container(self.log.control, padding=16, expand=True)],
                              spacing=0, expand=True), width=t.SESSION_WIDTH),
        ], spacing=t.GAP, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        app.board_listeners.append(self._checked)

    # Port list, polled while the page is open so a board shows up when it is plugged in

    def enter(self, **_) -> None:
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

    def scan(self, update: bool = True) -> None:
        self.ports = board.ports()
        devices = [p.device for p in self.ports]
        if self.selected not in devices:
            self.selected = self.app.radio_port(self.ports) or (devices[0] if devices else "")
        self._check_selected()
        self.render()
        if update:
            self.control.update()

    def _check_selected(self) -> None:
        if self.selected and self.selected not in self.app.identities and not self.app.busy:
            self.log.add(f"[app] Checking {self.selected}; the board may restart.")
            self.app.check_board(self.selected, log=self.log.add)

    def _checked(self) -> None:
        if self.visible:
            self.render()
            self.control.update()

    def port(self) -> board.Port | None:
        return next((p for p in self.ports if p.device == self.selected), None)

    def name_of(self, device: str) -> str:
        ident = self.app.identities.get(device)
        if isinstance(ident, board.Identity):
            return self.app.settings.board_names.get(ident.sta_mac, "")
        return ""

    def status(self) -> BoardStatus:
        if self.app.board_busy and self.selected not in self.app.identities:
            return BoardStatus("checking", "Checking the board", "Asking the board for its firmware.", self.selected)
        return self.app.board_status(self.ports, self.selected)

    def render(self) -> None:
        rows = []
        several = len(self.ports) > 1
        session_port = self.app.radio_port(self.ports)
        for p in self.ports:
            active = p.device == self.selected
            state = self.app.board_status(self.ports, p.device)
            dot = t.GREEN if state.ready else t.RED if state.state in ("flash", "wrong-port", "busy", "denied") else t.FAINT
            rows.append(ft.Container(ft.Row([
                t.pixel_icon("cpu", color=t.BLUE if active else t.FAINT),
                ft.Column([
                    t.text(self.name_of(p.device) or os.path.basename(p.device), 13,
                           t.TEXT if active else t.SOFT, weight=ft.FontWeight.W_600),
                    t.text(state.title, 11, t.MUTED),
                ], spacing=1, expand=True),
                t.badge("In use", t.BLUE, "checkbox-on") if several and p.device == session_port else
                ft.Container(width=8, height=8, border_radius=4, bgcolor=dot),
            ], spacing=10), padding=ft.Padding(10, 8, 10, 8), border_radius=12,
                bgcolor=t.SELECTED if active else None,
                on_click=lambda e, d=p.device: self._select(d)))
        if not rows:
            rows.append(ft.Container(ft.Column([
                t.pixel_icon("usb", color=t.FAINT),
                t.text("No board found", 13, t.MUTED, weight=ft.FontWeight.W_600),
                t.text("Plug it in with a data cable. It shows up here on its own.", 12, t.FAINT,
                       text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6), padding=24))
        self.list.controls = rows
        cards = [self.status_card()]
        if self.port():
            cards += [self.flash_card(), self.details_card()]
        cards.append(self.help_card())
        self.detail.controls = cards

    def _select(self, device: str) -> None:
        self.selected = device
        self._check_selected()
        self.render()
        self.control.update()

    # The selected board, in one line

    def status_card(self) -> ft.Control:
        status = self.status()
        icon, color = STATE_LOOK.get(status.state, ("warning-diamond", t.RED))
        lead = PixelActivity("Checking") if status.state == "checking" else t.pixel_icon(icon, size=24, color=color)
        actions: list[ft.Control] = []
        several = len(self.ports) > 1
        if self.port() and several and self.selected != self.app.radio_port(self.ports):
            actions.append(t.button("Use this board", self._use, "check"))
        if status.ready:
            actions.append(t.button("Go to Games", lambda e: self.app.navigate("games"), "gamepad",
                                    filled=not actions))
        if status.state in ("flash", "wrong-port", "busy", "denied"):
            actions.append(t.secondary_button("Check again", self._identify, "refresh", disabled=self.app.busy))
        detail = status.detail
        if status.ready and several:
            detail += (" Sessions use this board." if self.selected == self.app.radio_port(self.ports)
                       else " Sessions use another board; press Use this board to switch.")
        return t.surface(ft.Container(ft.Column([
            ft.Row([
                ft.Container(lead, width=24, height=24, alignment=ft.Alignment.CENTER),
                ft.Column([t.text(status.title, 17, weight=ft.FontWeight.W_600),
                           t.text(detail, 13, t.MUTED)], spacing=2, expand=True),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            *([ft.Row(actions, spacing=8)] if actions else []),
        ], spacing=14, tight=True), padding=ft.Padding(18, 16, 18, 18)))

    def details_card(self) -> ft.Control:
        p = self.port()
        ident = self.app.identities.get(p.device)
        if isinstance(ident, board.Identity):
            firmware = f"pokeldn v{ident.firmware_version}" if ident.firmware_version else "pokeldn"
            mac = ident.sta_mac
        else:
            firmware, mac = ident or "not checked yet", "unknown"

        def info(label, value):
            return ft.Row([t.text(label, 12, t.MUTED, width=110),
                           value if isinstance(value, ft.Control) else t.text(value, 13, font_family=t.MONO)])

        name = t.field(value=self.name_of(p.device), hint="Living room, spare...", width=220,
                       disabled=not isinstance(ident, board.Identity), on_submit=self._rename)
        body = ft.Column([
            info("Port", p.device),
            info("USB chip", p.bridge),
            info("Firmware", firmware),
            info("Wi-Fi MAC", mac),
            info("Nickname", ft.Row([name, t.icon_button("check", lambda e: self._rename(e, name),
                                                         "Save the nickname")], spacing=4,
                                               vertical_alignment=ft.CrossAxisAlignment.CENTER)),
            ft.Row([t.secondary_button("Blink the LED", self._blink, "lightbulb",
                                       disabled=self.app.busy or not isinstance(ident, board.Identity))]),
        ], spacing=10)
        return t.card("Details", body, "Blink the LED shows which board this is: a classic ESP32's blue LED "
                                       "blinks for five seconds. A nickname helps when several are plugged in.")

    def _rename(self, e, field=None) -> None:
        field = field or e.control
        ident = self.app.identities.get(self.selected)
        if isinstance(ident, board.Identity):
            names = self.app.settings.board_names
            if field.value.strip():
                names[ident.sta_mac] = field.value.strip()
            else:
                names.pop(ident.sta_mac, None)
            self.app.settings.save()
            self.render()
            self.control.update()

    def _use(self, e) -> None:
        self.app.settings.radio_port = self.selected
        self.app.settings.save()
        self.log.add(f"[app] Sessions now use {self.selected}.")
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

    # Flashing

    def firmware(self) -> str:
        chosen = self.app.settings.firmware
        if chosen and os.path.exists(chosen):
            return chosen
        return ""

    def flash_button(self) -> ft.Control:
        image = self.firmware()
        available = image or any(os.path.isfile(f) for f in (board.FIRMWARE, board.FIRMWARE_S3, board.FIRMWARE_C3, board.FIRMWARE_C6))
        flashing = bool(self.app.process and self.app.process.running and self.app.process_label == "flash")
        return t.button("Flashing..." if flashing else "Flash", self._flash, "zap", filled=not self.status().ready,
                        disabled=self.app.busy or not available or not self.port())

    def flash_card(self) -> ft.Control:
        image = self.firmware()
        available = image or any(os.path.isfile(f) for f in (board.FIRMWARE, board.FIRMWARE_S3, board.FIRMWARE_C3, board.FIRMWARE_C6))
        source = ft.Row([
            t.pixel_icon("package", color=t.MUTED),
            t.text(f"Custom image: {image}" if image else
                   "Firmware included with the app: ESP32, ESP32-S3, ESP32-C3 or ESP32-C6, picked for your chip." if available
                   else "No firmware image here yet (a copy run from source). Download the released one; "
                        "no ESP-IDF needed.",
                   12, t.MUTED if available else t.RED, expand=True),
            *([t.secondary_button("Included firmware", self._clear_file, "refresh")] if image else
              [t.icon_button("file", self._choose_file, "Use a firmware file of your own"
                                                         + (", or drop a .bin on this card" if drop.AVAILABLE else ""))] + ([] if available else [
                  t.button("Downloading..." if self.downloading else "Download the firmware", self._download,
                           "download", disabled=self.downloading)])),
        ], spacing=6)
        return drop.target(t.card("Flash the firmware", ft.Column([
            t.step_list(FLASH_STEPS),
            source,
            ft.Column([self.progress, self.progress_text], spacing=6, visible=self.progress.visible),
            ft.Row([self.flash_button()]),
        ], spacing=14), "Needed once per board, and again after an app update that says so. "
                        "Takes about thirty seconds."), self._dropped)

    def _dropped(self, paths: list[str]) -> None:
        """A firmware image dropped on the card becomes the custom image."""
        path = next((p for p in paths if drop.suffix(p) == "bin"), "")
        if path and not self.app.busy:
            self._set_firmware(path)

    def _download(self, e) -> None:
        self.downloading = True
        self.render()
        self.control.update()

        def work():
            try:
                tag = board.download_firmware(self.log.add)
                self.log.add(f"[app] Firmware from {tag} is ready. Press Flash.")
            except Exception as error:
                self.log.add(f"[app] Could not download the firmware: {error}")
            finally:
                self.downloading = False
                self.app.ui(lambda: (self.render(), self.control.update()))

        threading.Thread(target=work, daemon=True).start()

    async def _choose_file(self, e) -> None:
        files = await self.app.picker.pick_files(allowed_extensions=["bin"],
                                                 file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            self._set_firmware(files[0].path)

    def _clear_file(self, e) -> None:
        self._set_firmware("")

    def _set_firmware(self, path: str) -> None:
        self.app.settings.firmware = path
        self.app.settings.save()
        self.render()
        self.control.update()

    def _flash(self, e) -> None:
        if self.app.busy:
            return
        args = ["--module", "gui.board", "--port", self.selected]
        if image := self.firmware():
            args += ["--firmware", image]
        self.log.clear()
        self.log.add(f"[app] Flashing {self.selected}.")
        self.progress.visible, self.progress.value = True, None
        self.progress_text.value = "Connecting..."
        self.progress_text.color = t.MUTED
        env = dict(os.environ, NO_COLOR="1", PYTHONUNBUFFERED="1")
        env.pop("POKELDN_RADIO", None)
        self.app.process_label = "flash"
        self.app.process = runner.Process(args, str(SESSION), env, self._flash_line,
                                          self._flashed)
        self.render()
        self.control.update()

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
        device = self.selected

        def done():
            self.progress.value = 1 if code == 0 else 0
            self.progress_text.value = ("Done. Checking the board..." if code == 0 else
                                        "Flashing failed. Hold the BOOT button and press Flash again; the "
                                        "Activity log has the details.")
            self.progress_text.color = t.GREEN if code == 0 else t.RED
            self.app.identities.pop(device, None)
            self.render()
            self.control.update()
            if code == 0:
                threading.Timer(2.0, lambda: self.app.ui(self._after_flash)).start()
        self.app.ui(done)

    def _after_flash(self) -> None:
        self.scan(update=False)   # a native-USB board can come back under a new port name
        self.render()
        self.control.update()

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
        lines.append(t.text("Use a classic ESP32 (ESP32-D0WD, WROOM-32E), or an ESP32-S3, C3 or C6 through its "
                            "native USB port. S2 boards are not supported.", 13, t.MUTED))
        return t.card("Board not listed?", ft.Column(lines, spacing=8))

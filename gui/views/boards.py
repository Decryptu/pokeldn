import os
import re
import threading
import time

import flet as ft
import serial

from gui import board
from pokeldn.app import runner
from pokeldn.app.paths import SESSION
from gui import theme as t
from gui.views.widgets import CodeBlock, Log

PERCENT = re.compile(r"(\d{1,3}(?:\.\d)?)\s?%")

FLASH_STEPS = [
    "Use a USB data cable. A charge-only cable powers the board but no port appears.",
    "Select the board on the left.",
    "Press Flash. If it stays on 'Connecting', hold the BOOT button until writing starts.",
    "When it is done the blue LED pulses once, then breathes slowly.",
]


class BoardView:
    def __init__(self, app):
        self.app = app
        self.ports: list[board.Port] = []
        self.selected: str = ""
        self.identities: dict[str, board.Identity | str] = {}   # device -> identity or error
        self.visible = False
        self.list = ft.ListView(spacing=4, padding=8, expand=True)
        self.detail = ft.Column(spacing=12)
        self.log = Log(app.page, "Identify and flash output appears here.")
        self.progress = ft.ProgressBar(value=0, color=t.BLUE, bgcolor=t.FIELD, border_radius=4, visible=False)
        self.progress_text = t.text("", 12, t.MUTED)
        self.control = ft.Row([
            t.panel(ft.Column([
                t.panel_header("Boards", t.icon_button("refresh", lambda e: self.scan(), "Scan again")),
                self.list,
            ], spacing=0, expand=True), width=270),
            ft.ListView([self.detail], padding=ft.Padding(4, 0, 4, 24), expand=True),
            t.panel(ft.Column([t.panel_header("Activity"),
                               ft.Container(self.log.control, padding=14, expand=True)],
                              spacing=0, expand=True), width=380),
        ], spacing=14, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

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
            if self.visible and [p.device for p in board.ports()] != [p.device for p in self.ports]:
                self.app.ui(self.scan)

    def scan(self, update: bool = True) -> None:
        self.ports = board.ports()
        devices = [p.device for p in self.ports]
        if self.selected not in devices:
            self.selected = self.app.radio_port() or (devices[0] if devices else "")
        self.render()
        if update:
            self.control.update()

    def port(self) -> board.Port | None:
        return next((p for p in self.ports if p.device == self.selected), None)

    def name_of(self, device: str) -> str:
        ident = self.identities.get(device)
        if isinstance(ident, board.Identity):
            return self.app.settings.board_names.get(ident.sta_mac, "")
        return ""

    def render(self) -> None:
        rows = []
        for p in self.ports:
            active = p.device == self.selected
            radio = p.device == self.app.settings.radio_port
            rows.append(ft.Container(ft.Row([
                t.pixel_icon("cpu", color=t.BLUE if active else t.FAINT),
                ft.Column([
                    t.text(self.name_of(p.device) or os.path.basename(p.device), 13,
                           t.TEXT if active else "#C5C7CD", weight=ft.FontWeight.W_600),
                    t.text(p.bridge, 11, t.MUTED),
                ], spacing=1, expand=True),
                t.pill("Radio", t.RED) if radio else ft.Container(),
            ], spacing=10), padding=ft.Padding(10, 8, 10, 8), border_radius=9,
                bgcolor=t.HOVER if active else None,
                on_click=lambda e, d=p.device: self._select(d)))
        if not rows:
            rows.append(ft.Container(ft.Column([
                t.pixel_icon("usb", color=t.FAINT),
                t.text("No board found", 13, t.MUTED, weight=ft.FontWeight.W_600),
                t.text("Plug it in with a data cable. It shows up here on its own.", 12, t.FAINT,
                       text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6), padding=24))
        self.list.controls = rows
        self.detail.controls = [self.board_card(), self.flash_card(), self.help_card()]

    def _select(self, device: str) -> None:
        self.selected = device
        self.render()
        self.control.update()

    # The selected board

    def board_card(self) -> ft.Control:
        p = self.port()
        if not p:
            return t.card("No board selected", None, "Plug a board in; it is listed on the left.")
        ident = self.identities.get(p.device)
        if isinstance(ident, board.Identity):
            firmware = (t.pill("pokeldn firmware", t.GREEN) if ident.current else
                        t.pill(f"Old firmware (protocol {ident.protocol}), flash it", t.RED))
            mac = ident.sta_mac
        elif isinstance(ident, str):
            firmware, mac = t.pill(ident, t.RED), "unknown"
        else:
            firmware, mac = t.pill("Not checked yet", t.MUTED), "press Identify"

        def info(label, value):
            return ft.Row([t.text(label, 12, t.MUTED, width=110),
                           value if isinstance(value, ft.Control) else t.text(value, 12.5, font_family=t.MONO)])

        is_radio = p.device == self.app.settings.radio_port
        name = t.field(value=self.name_of(p.device), hint="Radio, Sniffer...", width=220,
                       disabled=not isinstance(ident, board.Identity), on_submit=self._rename)
        body = ft.Column([
            info("Port", p.device),
            info("USB chip", p.bridge),
            info("Wi-Fi MAC", mac),
            info("Firmware", firmware),
            info("Name", ft.Row([name, t.icon_button("check", lambda e: self._rename(e, name),
                                                     "Save the name")], spacing=4)),
            ft.Container(height=2),
            ft.Row([
                t.button("Identify", self._identify, "lightbulb",
                         disabled=self.app.busy or not p.supported),
                t.button("This is my radio" if not is_radio else "Radio board", self._use,
                         "checkbox" if not is_radio else "checkbox-on",
                         filled=False, disabled=is_radio),
            ], spacing=8),
        ], spacing=10)
        note = ("Identify restarts the board, reads its firmware and MAC, and blinks its blue LED for five "
                "seconds so you can tell the boards apart.")
        if not p.supported:
            note = "This is an ESP32-S3, C3 or C6. pokeldn runs on the classic ESP32 only."
        return t.card(self.name_of(p.device) or "ESP32 board", body, note)

    def _rename(self, e, field=None) -> None:
        field = field or e.control
        ident = self.identities.get(self.selected)
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
        self.log.add(f"[app] {self.selected} is the radio for every session.")
        self.render()
        self.control.update()

    def _identify(self, e) -> None:
        device = self.selected
        if self.app.busy:
            return
        self.app.board_busy = True
        self.log.add(f"[app] Opening {device}; the board restarts.")
        self.render()
        self.control.update()

        def work():
            try:
                ident = board.identify(device)
                self.identities[device] = ident
                self.log.add(f"[app] {ident.firmware}, protocol {ident.protocol}, chip revision "
                             f"{ident.chip_revision}, MAC {ident.sta_mac}")
                if ident.current:
                    self.log.add("[app] The board's blue LED blinks for five seconds.")
                else:
                    self.log.add("[app] This firmware is older than the app. Flash the board.")
            except serial.SerialException as error:
                self.identities[device] = "Port busy or not allowed"
                self.log.add(f"[app] Could not open {device}: {error}")
            except Exception as error:
                self.identities[device] = "No pokeldn firmware"
                self.log.add(f"[app] No pokeldn firmware answered ({error}). Flash the board below.")
            finally:
                self.app.board_busy = False
                self.app.ui(lambda: (self.render(), self.control.update()))

        threading.Thread(target=work, daemon=True).start()

    # Flashing

    def firmware(self) -> str:
        chosen = self.app.settings.firmware
        if chosen and os.path.exists(chosen):
            return chosen
        return board.FIRMWARE if os.path.exists(board.FIRMWARE) else ""

    def flash_card(self) -> ft.Control:
        image = self.firmware()
        p = self.port()
        source = ft.Row([
            t.pixel_icon("package", color=t.MUTED),
            t.text(("pokeldn firmware, included with the app" if image == board.FIRMWARE else image) if image else
                   "This copy of the app has no firmware image.", 12, t.MUTED if image else t.RED, expand=True),
            t.secondary_button("Use another file", self._choose_file, "file"),
        ], spacing=6)
        flashing = bool(self.app.process and self.app.process.running and self.app.process_label == "flash")
        return t.card("Flash the firmware", ft.Column([
            t.step_list(FLASH_STEPS),
            source,
            ft.Column([self.progress, self.progress_text], spacing=6),
            t.button("Flashing..." if flashing else "Flash", self._flash, "zap",
                     disabled=self.app.busy or not image or not p or not p.supported),
        ], spacing=14), "Writes pokeldn's radio firmware to the selected board. Takes about thirty seconds.")

    async def _choose_file(self, e) -> None:
        files = await self.app.picker.pick_files(allowed_extensions=["bin"],
                                                 file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            self._set_firmware(files[0].path)

    def _set_firmware(self, path: str) -> None:
        self.app.settings.firmware = path
        self.app.settings.save()
        self.render()
        self.control.update()

    def _flash(self, e) -> None:
        if self.app.busy:
            return
        args = board.flash_args(self.selected, self.firmware())
        self.log.clear()
        self.log.add(f"[app] Flashing {self.selected}.")
        self.progress.visible, self.progress.value = True, None
        self.progress_text.value = "Connecting..."
        env = dict(os.environ, NO_COLOR="1", PYTHONUNBUFFERED="1")
        env.pop("POKELDN_RADIO", None)
        self.app.process_label = "flash"
        self.app.process = runner.Process(["--module", "esptool", *args], str(SESSION), env, self._flash_line,
                                          self._flashed)
        self.render()
        self.control.update()

    def _flash_line(self, line: str) -> None:
        self.log.add(line)
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
        def done():
            self.progress.value = 1 if code == 0 else 0
            self.progress_text.value = ("Done. The board restarted with the new firmware." if code == 0 else
                                        "Flashing failed. Read the activity log; holding BOOT often helps.")
            self.progress_text.color = t.GREEN if code == 0 else t.RED
            self.identities.pop(self.selected, None)
            self.render()
            self.control.update()
        self.app.ui(done)

    def help_card(self) -> ft.Control:
        def link(label, url):
            return t.link_button(label, lambda e: self.app.page.run_task(self.app.open_url, url))

        return t.card("Board not listed?", ft.Column([
            t.text("Try another cable or USB port. Many cables only charge.", 12.5),
            ft.Row([t.text("Windows and macOS need the driver for the board's USB chip:", 12.5),
                    link("CP210x", board.DRIVERS["Silicon Labs CP210x"]),
                    link("CH340", board.DRIVERS["WCH CH340"])], spacing=6, wrap=True),
            t.text("Linux: allow serial ports, then log out and back in:", 12.5),
            CodeBlock(self.app, "sudo usermod -aG dialout $USER").control,
            t.text("pokeldn needs a classic ESP32 (ESP32-D0WD, WROOM-32E). S3, C3 and C6 boards are not "
                   "supported.", 12.5, t.MUTED),
        ], spacing=8))

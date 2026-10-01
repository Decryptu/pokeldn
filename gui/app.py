import os
import threading
from dataclasses import dataclass

import flet as ft
import serial

from gui import board
from pokeldn.app import settings, update
from pokeldn.app.paths import SESSION
from gui.views.widgets import on_ui

NO_FIRMWARE = "No pokeldn firmware"
PORT_BUSY = "Port busy or not allowed"


@dataclass(frozen=True)
class BoardStatus:
    state: str     # missing, choose, checking, ready, flash, wrong-port, busy
    title: str
    detail: str
    port: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "ready"


class App:
    """State shared by the pages: settings, the one child process a board allows, and services."""

    storage_busy = False

    def __init__(self, page: ft.Page):
        self.page = page
        SESSION.mkdir(parents=True, exist_ok=True)
        self.settings = settings.load()
        self.picker = ft.FilePicker()
        self.clipboard = ft.Clipboard()
        self.launcher = ft.UrlLauncher()
        self.process = None        # the running session or flash
        self.process_label = ""
        self.board_busy = False    # a check holds the port
        self.navigate = None       # set by the shell: navigate(page_key, **kwargs)
        self.identities: dict[str, board.Identity | str] = {}   # device -> identity, or why none answered
        self.chips: dict[str, str] = {}                         # device -> chip the last flash detected
        self.board_listeners: list = []                         # called on the UI loop after a check
        self.update: update.Release | None = None               # a newer release GitHub offered
        self.update_state = ""                                  # checking, current, available, offline
        self.update_listeners: list = []                        # called on the UI loop after a check

    def ui(self, fn) -> None:
        on_ui(self.page, fn)

    @property
    def busy(self) -> bool:
        return self.storage_busy or self.board_busy or bool(self.process and self.process.running)

    def radio_port(self, present: list[board.Port] | None = None) -> str:
        """The chosen board if it is plugged in, else the only board present."""
        devices = [p.device for p in (board.ports() if present is None else present)]
        if self.settings.radio_port in devices:
            return self.settings.radio_port
        return devices[0] if len(devices) == 1 else ""

    def board_status(self, present: list[board.Port] | None = None, device: str = "") -> BoardStatus:
        """One line a player can act on: is the board plugged in, does pokeldn's firmware answer.
        Without a device, the board sessions use."""
        present = board.ports() if present is None else present
        for device in set(self.identities) - {p.device for p in present}:
            self.identities.pop(device)   # unplugged: check again when it returns
        if not present:
            return BoardStatus("missing", "No board plugged in",
                               "Plug the ESP32 in with a USB data cable. Charge-only cables show nothing.")
        port = device or self.radio_port(present)
        if not port:
            return BoardStatus("choose", "Several boards plugged in",
                               "Open the Board page and pick the one to use.")
        found = next((p for p in present if p.device == port), None)
        if found is None:
            return BoardStatus("missing", "Board unplugged", "Plug it back in.", port)
        ident = self.identities.get(port)
        if isinstance(ident, board.Identity):
            if ident.current:
                version = f" v{ident.firmware_version}" if ident.firmware_version else ""
                return BoardStatus("ready", "Board ready", f"pokeldn firmware{version} answered.", port)
            return BoardStatus("flash", "Firmware out of date",
                               "Flash the board to update it.", port)
        if ident == PORT_BUSY:
            return BoardStatus("busy", "Board port busy",
                               "Another program holds the port. Close it, or unplug and replug the board.",
                               port)
        if ident == NO_FIRMWARE:
            if board.wrong_port(found, self.chips.get(port, "")):
                return BoardStatus("wrong-port", "Use the board's other USB port",
                                   f"The {self.chips[port]} firmware talks over the native USB port. Move the "
                                   "cable to the port marked USB (not COM or UART).", port)
            return BoardStatus("flash", "No pokeldn firmware on the board",
                               "Flash the board. If you just flashed it, press its RESET (RST) button.",
                               port)
        return BoardStatus("checking", "Checking the board", "Asking the board for its firmware.", port)

    def check_board(self, device: str, blink: bool = False, log=None) -> None:
        """Ask the board's firmware for its identity in the background; opening the port can restart it."""
        if self.busy or not device:
            return
        self.board_busy = True
        say = log or (lambda line: None)

        def work():
            try:
                ident = board.identify(device, blink=blink)
                self.identities[device] = ident
                say(f"[app] {ident.firmware}, protocol {ident.protocol}, chip revision "
                    f"{ident.chip_revision}, MAC {ident.sta_mac}")
                if not ident.current:
                    say("[app] This firmware uses a different radio protocol. Flash the board.")
            except serial.SerialException as error:
                self.identities[device] = PORT_BUSY
                say(f"[app] Could not open {device}: {error}")
            except Exception as error:
                self.identities[device] = NO_FIRMWARE
                say(f"[app] No pokeldn firmware answered on {device} ({error}).")
                self._probe_chip(device, say)
            finally:
                self.board_busy = False
                self.ui(lambda: [listener() for listener in list(self.board_listeners)])

        threading.Thread(target=work, daemon=True).start()

    def _probe_chip(self, device: str, say) -> None:
        """Through a USB-to-serial bridge, the ROM bootloader still names the chip: an S3 or C3 there
        is on its UART socket, where the radio firmware never answers."""
        port = next((p for p in board.ports() if p.device == device), None)
        if port is None or port.native:
            return
        try:
            self.chips[device] = board.detect_chip(device)
            say(f"[app] The chip on {device} is an {self.chips[device]}.")
        except Exception as error:
            say(f"[app] Could not read the chip type on {device} ({error}).")

    def check_if_unknown(self, present: list[board.Port] | None = None) -> None:
        port = self.radio_port(present)
        if port and port not in self.identities and not self.busy:
            self.check_board(port)

    def check_update(self) -> None:
        """Ask GitHub for a newer release in the background; listeners run when it answers."""
        if self.update_state == "checking":
            return
        self.update_state = "checking"

        def work():
            try:
                found, state = update.check(), "current"
            except OSError:
                found, state = None, "offline"
            self.ui(lambda: self._update_done(found, state))

        threading.Thread(target=work, daemon=True).start()

    def _update_done(self, found, state: str) -> None:
        if state != "offline":   # a failed check keeps a release an earlier one found
            self.update = found
        self.update_state = "available" if self.update else state
        for listener in list(self.update_listeners):
            listener()

    async def open_url(self, url: str) -> None:
        await self.launcher.launch_url(url)

    async def copy(self, value: str) -> None:
        await self.clipboard.set(value)
        self.page.show_dialog(ft.SnackBar(ft.Text("Copied"), duration=1500))


def keys_found(path: str) -> bool:
    return os.path.isfile(os.path.expanduser(path))

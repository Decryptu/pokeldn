import errno
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import flet as ft
import serial

from gui import board, theme
from gui.popups import Dialogs
from pokeldn import plugins, pokemon, popup
from pokeldn.app import android, ios, popups, settings, update
from pokeldn.app.paths import SESSION
from gui.views.widgets import on_ui
from pokeldn.app.i18n import t as tr

NO_FIRMWARE = 'No pokeldn firmware'
PORT_BUSY = 'Port busy or not allowed'
PORT_DENIED = 'Port not allowed'


@dataclass(frozen=True)
class BoardStatus:
    state: str     # missing, choose, checking, ready, flash, wrong-port, busy, denied, controller
    title: str
    detail: str
    port: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "ready"


class App:
    """State shared by the pages: settings, the one child process a board allows, and services."""

    storage_busy = False
    controllers = 0    # S3 controller boards on USB, polled

    def __init__(self, page: ft.Page):
        self.page = page
        page.fonts = {**(getattr(page, "fonts", None) or {}), **theme.FONT_ASSETS}
        SESSION.mkdir(parents=True, exist_ok=True)
        self.settings = settings.load()
        pokemon.SERVICE.home_tracker = self.settings.home_tracker
        self.plugin_stopped = plugins.turn_off_the_one_that_stopped(self.settings)   # and watches this start
        self.picker = ft.FilePicker()
        if android.active():   # the web view's picker gives no paths
            self.picker = android.Picker()
        if ios.active():
            self.picker = ios.Picker()
        self.clipboard = ft.Clipboard()
        self.launcher = ft.UrlLauncher()
        self.process = None        # the running session or flash
        self.process_label = ""
        self.board_busy = False    # a check holds the port
        self.navigate = None       # set by the shell: navigate(page_key, **kwargs)
        self.identities: dict[str, board.Identity | str] = {}   # device -> identity, or why none answered
        self.chips: dict[str, str] = {}                         # device -> chip the last flash detected
        self.board_listeners: list = []                         # called on the UI loop after a check
        self.hidden_bridges: list[str] = []                     # Windows: bridges with no driver, polled
        self.update: update.Release | None = None               # a newer release GitHub offered
        self.update_state = ""                                  # checking, current, available, offline
        self.update_listeners: list = []                        # called on the UI loop after a check
        self.plugin_updates: dict = {}                          # plugin id -> plugin_updates.Available
        self.plugin_sources: list = []                          # plugin_sources.Source, as last read
        self.plugin_update_listeners: list = []                 # called on the UI loop after a check
        self.gts = None                                         # gui.views.gts.service, once used
        # Pop-ups (docs/gui.md, Pop-ups): a run's come through runner.Process; the app's own through
        # pokeldn.popup, their callbacks on a worker so none stalls the UI.
        self.popups = popups.Manager(Dialogs(page), call=self.ui)
        answers = ThreadPoolExecutor(1, thread_name_prefix="popup")
        popup.attach(self.popups.program("", lambda reply: answers.submit(popup.answered, reply)).take)
        threading.Thread(target=self._watch_controllers, daemon=True).start()

    def ui(self, fn) -> None:
        on_ui(self.page, fn)

    def _watch_controllers(self) -> None:
        """A controller board has no serial port, so the port list never shows it; USB does."""
        import time
        while True:
            found = board.controllers()
            if found != self.controllers:
                self.controllers = found
                self.ui(lambda: [listener() for listener in list(self.board_listeners)])
            time.sleep(6 if sys.platform == "win32" else 2)

    @property
    def busy(self) -> bool:
        return self.storage_busy or self.board_busy or bool(self.process and self.process.running)

    def plugin_radio(self):
        """The selected external radio, or None for the board."""
        if not self.settings.radio:
            return None
        from pokeldn.ldn import radios
        return radios.radio(self.settings.radio)

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
        if not present and android.active():
            return self.android_status()
        if not present and ios.active():
            off = ios.radio_state() == "off"
            return BoardStatus("missing", tr('app.ios_no_radio', 'Bluetooth is off') if off else
                               tr('app.ios_looking_for_radio', 'Looking for the Bluetooth radio'),
                               tr('app.ios_radio_steps', 'Power a board running the Bluetooth radio firmware near the phone, and allow pokeldn to use Bluetooth in Settings.'))
        if not present:
            hidden = board.bridges_without_port() if sys.platform.startswith("linux") else []
            if hidden:
                fix = (tr('app.ubuntu_22_04_s_braille_service_takes_ch340_boards_sudo__4f946d', "Ubuntu 22.04's braille service takes CH340 boards: sudo apt remove brltty, then unplug and replug the board.") if "WCH CH340" in hidden else
                       tr('app.unplug_and_replug_it_the_kernel_log_sudo_dmesg_says_why_c4306e', 'Unplug and replug it; the kernel log (sudo dmesg) says why.'))
                return BoardStatus("missing", tr('app.board_found_without_a_serial_port_c0cd13', 'Board found without a serial port'),
                                   tr('app.linux_gave_the_no_serial_port_5329c0', 'Linux gave the {value0} no serial port. {value1}', value0=hidden[0], value1=fix))
            if sys.platform == "win32" and self.hidden_bridges:
                name = self.hidden_bridges[0]
                steps = board.DRIVER_STEPS.get(name, tr('app.install_its_driver_the_board_page_links_it_c226a3', 'Install its driver; the Board page links it.'))
                return BoardStatus("missing", tr('app.board_found_without_a_driver_aea8c6', 'Board found without a driver'),
                                   tr('app.windows_has_no_driver_for_the_so_it_has_no_com_port_10597e', 'Windows has no driver for the {value0}, so it has no COM port. {value1}', value0=name, value1=steps))
            if self.controllers:
                return BoardStatus("controller", tr('app.your_board_runs_the_controller_firmware_fec986', 'Your board runs the Controller firmware'),
                                   tr('app.trades_need_the_wireless_firmware_install_it_from_the_b_c0721b', 'Trades need the Wireless firmware: install it from the Board page.'))
            return BoardStatus("missing", tr('app.no_board_plugged_in_0ea8e5', 'No board plugged in'),
                               tr('app.plug_the_esp32_in_with_a_usb_data_cable_charge_only_cab_baeb1f', 'Plug the ESP32 in with a USB data cable. Charge-only cables show nothing.'))
        port = device or self.radio_port(present)
        if not port:
            return BoardStatus("choose", tr('app.several_boards_plugged_in_997786', 'Several boards plugged in'),
                               tr('app.open_the_board_page_and_pick_the_one_to_use_1dae63', 'Open the Board page and pick the one to use.'))
        found = next((p for p in present if p.device == port), None)
        if found is None:
            return BoardStatus("missing", tr('app.board_unplugged_3ffbbb', 'Board unplugged'), tr('app.plug_it_back_in_b782dc', 'Plug it back in.'), port)
        ident = self.identities.get(port)
        if isinstance(ident, board.Identity):
            if ident.current:
                version = f" v{ident.firmware_version}" if ident.firmware_version else ""
                return BoardStatus("ready", tr('app.board_ready_222cfc', 'Board ready'), tr('app.pokeldn_firmware_answered_9123fd', 'pokeldn firmware{value0} answered.', value0=version), port)
            return BoardStatus("flash", tr('app.firmware_out_of_date_bcafad', 'Firmware out of date'),
                               tr('app.update_it_on_the_board_page_2ca281', 'Update it on the Board page.'), port)
        if isinstance(ident, board.PadIdentity):
            return BoardStatus("controller", tr('app.your_board_runs_the_controller_firmware_fec986', 'Your board runs the Controller firmware'),
                               tr('app.trades_need_the_wireless_firmware_install_it_from_the_b_c0721b', 'Trades need the Wireless firmware: install it from the Board page.'), port)
        if ident == PORT_DENIED:
            group = "uucp" if os.path.exists("/etc/arch-release") else "dialout"
            fix = (tr('app.add_yourself_to_the_group_sudo_usermod_ag_user_then_log_b0f6cb', 'Add yourself to the {value0} group (sudo usermod -aG {value1} $USER), then log out and back in.', value0=group, value1=group) if sys.platform.startswith("linux") else tr('app.unplug_and_replug_the_board_5e9230', 'Unplug and replug the board.'))
            return BoardStatus("denied", tr('app.no_permission_to_open_the_board_87f9dc', 'No permission to open the board'), fix, port)
        if ident == PORT_BUSY:
            return BoardStatus("busy", tr('app.board_port_busy_68939c', 'Board port busy'),
                               tr('app.another_program_holds_the_port_close_it_or_unplug_and_r_6addae', 'Another program holds the port. Close it, or unplug and replug the board.'),
                               port)
        if ident == NO_FIRMWARE:
            if board.wrong_port(found, self.chips.get(port, "")):
                return BoardStatus("wrong-port", tr('app.use_the_board_s_other_usb_port_f8c42f', "Use the board's other USB port"),
                                   tr('app.the_firmware_talks_over_the_native_usb_port_move_the_ca_a14e6b', 'The {value0} firmware talks over the native USB port. Move the cable to the port marked USB (not COM or UART).', value0=self.chips[port]), port)
            return BoardStatus("flash", tr('app.no_pokeldn_firmware_on_the_board_bf42d9', 'No pokeldn firmware on the board'),
                               tr('app.install_the_wireless_firmware_on_the_board_page_if_you__f58486', "Install the Wireless firmware on the Board page. If you just installed it, press the board's RESET (RST) button."),
                               port)
        return BoardStatus("checking", tr('app.checking_the_board_f7ce4a', 'Checking the board'), tr('app.asking_the_board_for_its_firmware_21d622', 'Asking the board for its firmware.'), port)

    def android_status(self) -> BoardStatus:
        """The phone's USB state before any firmware answers (docs/gui.md, Android setup requirements)."""
        state = android.usb_state()
        titles = {"missing": tr('app.no_board_plugged_in_0ea8e5', 'No board plugged in'),
                  "bridge": tr('app.android_bridge_board', 'This board needs a computer'),
                  "permission": tr('app.android_allow_usb', 'Allow USB access'),
                  "denied": tr('app.android_usb_refused', 'USB access was refused')}
        return BoardStatus("denied" if state in ("permission", "denied") else "missing", titles.get(state, ""),
                           android.usb_guidance(state))

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
                say(f'[app] {ident.firmware}, protocol {ident.protocol}, chip revision {ident.chip_revision}, MAC {ident.sta_mac}')
                if not ident.current:
                    say('[app] This firmware uses a different radio protocol. Update it on the Board page.')
            except serial.SerialException as error:
                # pyserial keeps the open's errno: EACCES is a missing group on Linux, not a busy port.
                self.identities[device] = PORT_DENIED if error.errno == errno.EACCES else PORT_BUSY
                say(f'[app] Could not open {device}: {error}')
            except Exception as error:
                try:
                    self.identities[device] = board.identify_pad(device)
                    say(f'[app] {device} runs the controller firmware.')
                except Exception:
                    self.identities[device] = NO_FIRMWARE
                    say(f'[app] No pokeldn firmware answered on {device} ({error}).')
                    self._probe_chip(device, say)
            finally:
                self.board_busy = False
                self.ui(lambda: [listener() for listener in list(self.board_listeners)])

        threading.Thread(target=work, daemon=True).start()

    def _probe_chip(self, device: str, say) -> None:
        """Through a USB-to-serial bridge, the ROM bootloader still names the chip: an S3, C3 or C6 there
        is on its UART socket, where the radio firmware never answers."""
        port = next((p for p in board.ports() if p.device == device), None)
        if port is None or port.native:
            return
        try:
            self.chips[device] = board.detect_chip(device)
            say(f'[app] The chip on {device} is an {self.chips[device]}.')
        except Exception as error:
            say(f'[app] Could not read the chip type on {device} ({error}).')

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

    def check_plugin_updates(self) -> None:
        """Read every followed source and each installed plugin's update address, in the background."""
        def work():
            from pokeldn.app import plugin_sources, plugin_updates
            listings = [plugin_sources.fetch(url) for url in plugin_sources.followed()]
            found = plugin_updates.check(plugins.discover(), listings)

            def done():
                self.plugin_sources = listings
                self._plugin_updates_done(found)
            self.ui(done)

        threading.Thread(target=work, daemon=True).start()

    def _plugin_updates_done(self, found: dict) -> None:
        self.plugin_updates = found
        for listener in list(self.plugin_update_listeners):
            listener()

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
        self.page.show_dialog(ft.SnackBar(ft.Text(tr('app.copied_8d525e', 'Copied')), duration=1500))


def keys_found(path: str) -> bool:
    return os.path.isfile(os.path.expanduser(path))

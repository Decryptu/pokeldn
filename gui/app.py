from pokeldn.app.i18n import ref as _ref
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
from pokeldn.app.i18n import text as tr, ref

NO_FIRMWARE = _ref('core.gui.app.no_pokeldn_firmware_091f1ae1')
PORT_BUSY = _ref('core.gui.app.port_busy_or_not_allowed_0c197ba6')
PORT_DENIED = _ref('core.gui.app.port_not_allowed_bbd7016b')


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
            return BoardStatus("missing", tr('core.app.ios_no_radio') if off else
                               tr('core.app.ios_looking_for_radio'),
                               tr('core.app.ios_radio_steps'))
        if not present:
            hidden = board.bridges_without_port() if sys.platform.startswith("linux") else []
            if hidden:
                fix = (tr('core.app.ubuntu_22_04_s_braille_service_takes_ch340_boards_sudo__4f946d') if "WCH CH340" in hidden else
                       tr('core.app.unplug_and_replug_it_the_kernel_log_sudo_dmesg_says_why_c4306e'))
                return BoardStatus("missing", tr('core.app.board_found_without_a_serial_port_c0cd13'),
                                   tr('core.app.linux_gave_the_no_serial_port_5329c0', value0=hidden[0], value1=fix))
            if sys.platform == "win32" and self.hidden_bridges:
                name = self.hidden_bridges[0]
                steps = board.DRIVER_STEPS.get(name, tr('core.app.install_its_driver_the_board_page_links_it_c226a3'))
                return BoardStatus("missing", tr('core.app.board_found_without_a_driver_aea8c6'),
                                   tr('core.app.windows_has_no_driver_for_the_so_it_has_no_com_port_10597e', value0=name, value1=steps))
            if self.controllers:
                return BoardStatus("controller", tr('core.app.your_board_runs_the_controller_firmware_fec986'),
                                   tr('core.app.trades_need_the_wireless_firmware_install_it_from_the_b_c0721b'))
            return BoardStatus("missing", tr('core.app.no_board_plugged_in_0ea8e5'),
                               tr('core.app.plug_the_esp32_in_with_a_usb_data_cable_charge_only_cab_baeb1f'))
        port = device or self.radio_port(present)
        if not port:
            return BoardStatus("choose", tr('core.app.several_boards_plugged_in_997786'),
                               tr('core.app.open_the_board_page_and_pick_the_one_to_use_1dae63'))
        found = next((p for p in present if p.device == port), None)
        if found is None:
            return BoardStatus("missing", tr('core.app.board_unplugged_3ffbbb'), tr('core.app.plug_it_back_in_b782dc'), port)
        ident = self.identities.get(port)
        if isinstance(ident, board.Identity):
            if ident.current:
                version = f" v{ident.firmware_version}" if ident.firmware_version else ""
                return BoardStatus("ready", tr('core.app.board_ready_222cfc'), tr('core.app.pokeldn_firmware_answered_9123fd', value0=version), port)
            return BoardStatus("flash", tr('core.app.firmware_out_of_date_bcafad'),
                               tr('core.app.update_it_on_the_board_page_2ca281'), port)
        if isinstance(ident, board.PadIdentity):
            return BoardStatus("controller", tr('core.app.your_board_runs_the_controller_firmware_fec986'),
                               tr('core.app.trades_need_the_wireless_firmware_install_it_from_the_b_c0721b'), port)
        if ident == PORT_DENIED:
            group = "uucp" if os.path.exists("/etc/arch-release") else "dialout"
            fix = (tr('core.app.add_yourself_to_the_group_sudo_usermod_ag_user_then_log_b0f6cb', value0=group, value1=group) if sys.platform.startswith("linux") else tr('core.app.unplug_and_replug_the_board_5e9230'))
            return BoardStatus("denied", tr('core.app.no_permission_to_open_the_board_87f9dc'), fix, port)
        if ident == PORT_BUSY:
            return BoardStatus("busy", tr('core.app.board_port_busy_68939c'),
                               tr('core.app.another_program_holds_the_port_close_it_or_unplug_and_r_6addae'),
                               port)
        if ident == NO_FIRMWARE:
            if board.wrong_port(found, self.chips.get(port, "")):
                return BoardStatus("wrong-port", tr('core.app.use_the_board_s_other_usb_port_f8c42f'),
                                   tr('core.app.the_firmware_talks_over_the_native_usb_port_move_the_ca_a14e6b', value0=self.chips[port]), port)
            return BoardStatus("flash", tr('core.app.no_pokeldn_firmware_on_the_board_bf42d9'),
                               tr('core.app.install_the_wireless_firmware_on_the_board_page_if_you__f58486'),
                               port)
        return BoardStatus("checking", tr('core.app.checking_the_board_f7ce4a'), tr('core.app.asking_the_board_for_its_firmware_21d622'), port)

    def android_status(self) -> BoardStatus:
        """The phone's USB state before any firmware answers (docs/gui.md, Android setup requirements)."""
        state = android.usb_state()
        titles = {"missing": tr('core.app.no_board_plugged_in_0ea8e5'),
                  "bridge": tr('core.app.android_bridge_board'),
                  "permission": tr('core.app.android_allow_usb'),
                  "denied": tr('core.app.android_usb_refused')}
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
        self.page.show_dialog(ft.SnackBar(ft.Text(tr('core.app.copied_8d525e')), duration=1500))


def keys_found(path: str) -> bool:
    return os.path.isfile(os.path.expanduser(path))

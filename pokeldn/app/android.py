"""The app on Android (examples/android): the radio board's USB link as a serial port, so the Board page,
the launchers and esptool reach it unchanged, and the Android calls that stand in for a desktop's
folders. Everything here needs Chaquopy's `java` module; nothing imports it off Android."""
import os
import sys
import time

import serial
from serial.serialutil import PortNotOpenError, SerialBase, SerialException, Timeout

PORT = "android://board"


def active() -> bool:
    return os.environ.get("POKELDN_PLATFORM") == "android"


def bridge():
    from java import jclass
    return jclass("org.pokeldn.usbprobe.Bridge")


class Serial(SerialBase):
    """pyserial's interface over UsbStream.java; serial.Serial and serial_for_url("android://board") are this."""

    def open(self):
        if self.is_open:
            raise SerialException("Port is already open.")
        if self._port != PORT:
            raise SerialException(f"Only {PORT} exists on this phone, not {self._port!r}.")
        # A reset into the ROM loader re-enumerates native USB (esptool reopens the port): wait for it.
        deadline = time.monotonic() + 10
        while True:
            try:
                self._usb = bridge().open()
                break
            except Exception as error:
                if time.monotonic() > deadline:
                    raise SerialException(str(error)) from error
                time.sleep(0.25)
        self.is_open = True
        self._reconfigure_port()
        self._update_dtr_state()

    def close(self):
        if self.is_open:
            self.is_open = False
            self._usb.close()

    def from_url(self, url):
        return url

    def _reconfigure_port(self):
        if self.is_open:
            self._usb.setBaud(int(self._baudrate))

    def _update_dtr_state(self):
        if self.is_open:
            self._usb.setLines(bool(self._dtr_state), bool(self._rts_state))

    _update_rts_state = _update_dtr_state

    def _update_break_state(self):
        pass

    @property
    def in_waiting(self):
        if not self.is_open:
            raise PortNotOpenError()
        return int(self._usb.available())

    @property
    def out_waiting(self):
        return 0

    def read(self, size=1):
        if not self.is_open:
            raise PortNotOpenError()
        data = bytearray()
        timeout = Timeout(self._timeout)
        while len(data) < size:
            chunk = bytes(self._usb.read(size - len(data)))   # waits up to 20 ms for a USB transfer
            data += chunk
            if self._usb.isClosed() and not chunk:
                raise SerialException("The board's USB link closed.")
            if timeout.expired():
                break
        return bytes(data)

    def write(self, data):
        if not self.is_open:
            raise PortNotOpenError()
        data = bytes(data)
        self._usb.write(data)
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        if self.is_open:
            while self._usb.available():
                self._usb.read(65536)

    def reset_output_buffer(self):
        pass

    @property
    def cts(self):
        return True

    @property
    def dsr(self):
        return True

    @property
    def ri(self):
        return False

    @property
    def cd(self):
        return True


class _Port:
    """A ListPortInfo for the board, the fields gui.board and esp32_wlan read."""

    def __init__(self):
        self.device = PORT
        self.vid, self.pid = int(bridge().deviceVendorId()), int(bridge().deviceProductId())
        self.serial_number = self.description = self.product = bridge().deviceName()
        self.manufacturer = "Espressif" if (self.vid, self.pid) == (0x303A, 0x1001) else "Silicon Labs"
        self.hwid, self.location, self.interface = f"USB VID:PID={self.vid:04X}:{self.pid:04X}", "", ""

    def __getitem__(self, index):
        return (self.device, self.description, self.hwid)[index]


def comports(include_links=False):
    return [_Port()] if bridge().usbState() == "ready" else []


def install() -> None:
    """Before anything imports serial.tools.list_ports: pyserial has no port list for 'android'."""
    import types
    posix = types.ModuleType("serial.tools.list_ports_posix")
    posix.comports = comports
    sys.modules["serial.tools.list_ports_posix"] = posix
    serial.Serial = Serial
    protocol = types.ModuleType("pokeldn_android_serial.protocol_android")
    protocol.Serial = Serial
    sys.modules["pokeldn_android_serial"] = types.ModuleType("pokeldn_android_serial")
    sys.modules["pokeldn_android_serial.protocol_android"] = protocol
    serial.protocol_handler_packages.append("pokeldn_android_serial")


def usb_state() -> str:
    """missing, bridge, permission, denied or ready (Bridge.usbState)."""
    return str(bridge().usbState())


def usb_guidance(state: str) -> str:
    return str(bridge().guidance(state))


def ask_permission() -> None:
    bridge().askPermission()


def open_settings() -> None:
    bridge().openSettings()


def keep_awake(on: bool) -> None:
    bridge().keepAwake(on)


def changes() -> int:
    return int(bridge().changes())


def save_as(path: str, name: str = "", kind: str = "") -> None:
    bridge().saveAs(path, name or os.path.basename(path), kind)


def share(path: str, kind: str = "") -> None:
    bridge().share(path, kind)


class PickedFile:
    def __init__(self, path: str):
        self.path, self.name, self.size = path, os.path.basename(path), os.path.getsize(path)


class Picker:
    """flet.FilePicker's three calls on Android's own pickers: in a web view Flet's picker returns no paths."""

    async def pick_files(self, allow_multiple: bool = False, allowed_extensions=None, **_):
        import asyncio
        paths = await asyncio.to_thread(lambda: list(bridge().pickFiles(bool(allow_multiple))))
        files = [PickedFile(str(p)) for p in paths]
        if allowed_extensions:
            wanted = {e.lower().lstrip(".") for e in allowed_extensions}
            files = [f for f in files if f.name.rsplit(".", 1)[-1].lower() in wanted] or files
        return files

    async def save_file(self, file_name: str = "", **_):
        """The place is chosen first; the caller then writes the returned path, which is copied there once it stops changing."""
        import asyncio
        import tempfile
        import threading
        uri = await asyncio.to_thread(lambda: str(bridge().createDocument(file_name or "file")))
        if not uri:
            return None
        outbox = os.path.join(os.environ.get("HOME", tempfile.gettempdir()), "outbox")
        os.makedirs(outbox, exist_ok=True)
        path = os.path.join(tempfile.mkdtemp(dir=outbox), file_name or "file")
        threading.Thread(target=_deliver, args=(path, uri), daemon=True).start()
        return path

    async def get_directory_path(self, initial_directory: str = "", **_):
        return initial_directory or None


def _deliver(path: str, uri: str, settle: float = 1.0, limit: float = 600.0) -> None:
    """Copies `path` to the chosen document once its size has held for `settle` seconds."""
    deadline, seen, since = time.monotonic() + limit, None, time.monotonic()
    while time.monotonic() < deadline:
        try:
            now = os.stat(path).st_size, os.stat(path).st_mtime
        except OSError:
            now = None
        if now != seen:
            seen, since = now, time.monotonic()
        elif now is not None and time.monotonic() - since >= settle:
            bridge().copyToDocument(path, uri)
            return
        time.sleep(0.2)


def save_folder(path: str) -> None:
    """Zips `path` into the outbox and asks where to save the archive."""
    import shutil
    import tempfile
    outbox = os.path.join(os.environ.get("HOME", tempfile.gettempdir()), "outbox")
    os.makedirs(outbox, exist_ok=True)
    name = os.path.basename(os.path.normpath(path)) or "pokeldn"
    archive = shutil.make_archive(os.path.join(tempfile.mkdtemp(dir=outbox), name), "zip", path)
    save_as(archive, name + ".zip", "application/zip")

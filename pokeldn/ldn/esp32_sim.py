"""A simulated ESP32 radio: the firmware's message set (`firmware/esp32/main/radio.c`) over an
in-process stream, and an `Air` several boards share. It carries action frames, association and
CCMP-keyed Ethernet between boards, and nothing of LDN above that.
"""

import queue
import random
import struct
import threading
import time

from pokeldn.ldn import esp32

IDLE, STA, AP = "idle", "sta", "ap"


class _HostStream:
    """The host end of the simulated USB serial port."""

    def __init__(self, board: "SimulatedBoard"):
        self._board = board
        self._inbox: queue.Queue[bytes] = queue.Queue()

    def read(self, n: int) -> bytes:
        try:
            data = self._take(self._inbox.get(timeout=0.02))
        except queue.Empty:
            return b""
        while len(data) < n:
            try:
                data += self._take(self._inbox.get_nowait())
            except queue.Empty:
                break
        return data

    def _take(self, sent: tuple[int | None, bytes]) -> bytes:
        return sent[1]

    def write(self, data: bytes) -> None:
        self._board._from_host(data)

    def close(self) -> None:
        pass


class UartPort(_HostStream):
    """pyserial's `Serial` on a classic board's UART: the board keeps its line rate across opens
    (wire.c sets it at boot and on BAUD), and bytes sent at another rate arrive as noise."""

    def __init__(self, board: "SimulatedBoard"):
        super().__init__(board)
        board.stream = self
        if board.line_rate is None:
            board.line_rate = 115200
        self.baudrate = 115200
        self.dtr = self.rts = True   # pyserial asserts both on open unless told otherwise
        self._credit_at = 0.0

    def open(self) -> None:
        pass

    def flush(self) -> None:
        pass

    def read(self, n: int) -> bytes:
        data = super().read(n)
        if not data and time.monotonic() - self._credit_at > 0.1:
            self._credit_at = time.monotonic()
            # Idle, the firmware repeats its CREDIT every 100 ms (wire.c reader): the one after a
            # BAUD leaves at the new rate, before the host has switched.
            self._board._emit(esp32.MSG_CREDIT, struct.pack("<I", getattr(self._board, "_consumed", 0)))
        return data

    def _take(self, sent: tuple[int | None, bytes]) -> bytes:
        rate, data = sent
        return data if rate == self.baudrate else b"\x55" * len(data)

    def write(self, data: bytes) -> None:
        # Noise with no 0x00 leaves a partial frame in the board's decoder.
        self._board._from_host(data if self.baudrate == self._board.line_rate else b"\xff" * len(data))


class Air:
    def __init__(self):
        self.boards: list["SimulatedBoard"] = []
        self.lock = threading.RLock()

    def attach(self, board: "SimulatedBoard") -> None:
        with self.lock:
            self.boards.append(board)

    def access_point(self, bssid: bytes, channel: int, ssid: bytes):
        with self.lock:
            for board in self.boards:
                if board.mode == AP and board.bssid == bssid and board.channel == channel \
                        and board.ssid == ssid:
                    return board
        return None


class SimulatedBoard:
    def __init__(self, air: Air, mac: bytes | None = None):
        self.air = air
        self.sta_mac = mac or bytes([0x24, 0x6F, 0x28] + random.sample(range(256), 3))
        self.ap_mac = self.sta_mac[:5] + bytes([(self.sta_mac[5] + 1) & 0xFF])
        self.mode = IDLE
        self.refuse_joins = 0        # STA_JOINs answered as a retail join failure, 0xc9
        self.channel = 1
        self.bssid = b""
        self.ssid = b""
        self.key = b""
        self.stations: dict[bytes, "SimulatedBoard"] = {}   # AP: mac -> station board
        self.ap: "SimulatedBoard | None" = None              # STA: the joined access point
        self.stream = _HostStream(self)
        self.line_rate: int | None = None   # a classic board's UART rate; None for native USB
        self._reader = esp32.FrameReader()
        self.sent_raw: list[bytes] = []
        self.led_looks: list[bytes] = []
        self.displays: list[bytes] = []
        self.version = ""                 # the firmware version HELLO reports, "" for none
        self.host_silent_after = 5.0      # the firmware's HOST_SILENT_US
        self._host_seen = 0.0
        self._watched = False
        air.attach(self)

    def host_stream(self) -> _HostStream:
        return self.stream

    def _emit(self, msg_type: int, payload: bytes = b"") -> None:
        self.stream._inbox.put((self.line_rate, esp32.encode_frame(msg_type, payload)))

    def _result(self, command: int, code: int = 0) -> None:
        self._emit(esp32.MSG_RESULT, bytes([command]) + struct.pack("<i", code))

    def _from_host(self, data: bytes) -> None:
        # The firmware's CREDIT: host bytes read since the last HELLO, counted up to each frame's
        # delimiter so a HELLO's reset excludes its own bytes.
        for b in data:
            self._consumed = getattr(self, "_consumed", 0) + 1
            for msg_type, payload in self._reader.feed(bytes([b])):
                with self.air.lock:
                    if msg_type == esp32.CMD_HELLO:
                        self._consumed = 0
                        self._emit(esp32.MSG_CREDIT, struct.pack("<I", 0))
                    self._command(msg_type, payload)
        self._emit(esp32.MSG_CREDIT, struct.pack("<I", self._consumed))

    def _command(self, t: int, p: bytes) -> None:
        self._host_seen = time.monotonic()
        if t == esp32.CMD_HELLO:
            self._watched = False
            text = "pokeldn-radio simulated" + (f" version={self.version}" if self.version else "")
            self._emit(esp32.MSG_INFO, bytes([esp32.PROTOCOL_VERSION]) + self.sta_mac + self.ap_mac
                       + b"\x03" + text.encode())
        elif t == esp32.CMD_ALIVE and self.version:
            if not self._watched:
                self._watched = True
                threading.Thread(target=self._watch_host, daemon=True).start()
        elif t == esp32.CMD_BAUD:
            self._result(t)   # at the old rate
            if self.line_rate is not None:
                self.line_rate = struct.unpack("<I", p)[0]
        elif t == esp32.CMD_CHANNEL:
            if self.mode != IDLE:
                self._result(t, 0x103)
            else:
                self.channel = p[0]
                self._result(t)
        elif t == esp32.CMD_STA_JOIN:
            self._go_idle()
            self.channel, self.bssid, self.ssid, self.key = p[0], p[1:7], p[7:39], p[39:55]
            mac = p[55:61]
            if mac != bytes(6):
                self.sta_mac = mac
            self._result(t)
            ap = self.air.access_point(self.bssid, self.channel, self.ssid)
            if ap is not None and self.refuse_joins:
                self.refuse_joins -= 1
                self._emit(esp32.MSG_LINK, b"\x00" + struct.pack("<H", 0xC9) + self.sta_mac)
                return
            if ap is None:
                self._emit(esp32.MSG_LINK, b"\x00" + struct.pack("<H", esp32.LINK_TIMEOUT) + self.sta_mac)
                return
            self.mode, self.ap = STA, ap
            aid = len(ap.stations) + 1
            ap.stations[self.sta_mac] = self
            ap._emit(esp32.MSG_STA_JOINED, self.sta_mac + bytes([aid, 0, 1]))
            self._emit(esp32.MSG_LINK, b"\x01" + struct.pack("<H", 0) + self.sta_mac)
        elif t == esp32.CMD_STOP:
            self._go_idle()
            self._result(t)
        elif t == esp32.CMD_AP_START:
            self._go_idle()
            self.channel, self.bssid, self.ssid, self.key = p[0], p[1:7], p[7:39], p[39:55]
            self.mode = AP
            self._result(t)
            self._emit(esp32.MSG_LINK, b"\x01" + struct.pack("<H", 0) + self.bssid)
        elif t == esp32.CMD_AP_KICK:
            station = self.stations.get(p[:6])
            if station is None:
                self._result(t, 0x102)
                return
            reason = struct.unpack_from("<H", p, 6)[0]
            self._drop_station(p[:6], reason)
            self._result(t)
        elif t == esp32.CMD_ETH_TX:
            self._ethernet_tx(p)
        elif t == esp32.CMD_RAW_TX:
            self._raw_tx(p)
        elif t == esp32.CMD_STATUS:
            self._emit(esp32.MSG_STATUS, f"mode={self.mode} simulated".encode())
        elif t == esp32.CMD_LED:
            self.led_looks.append(p)
            self._result(t, 0 if len(p) == 6 and p[0] < len(esp32.LED_PATTERNS) else 0x102)
        elif t == esp32.CMD_DISPLAY:
            self.displays.append(p)
            self._result(t)
        elif t == esp32.CMD_BENCH:
            total, size = struct.unpack("<IH", p)
            self._result(t)
            for seq in range(-(-total // size)):
                self._emit(esp32.MSG_BENCH, struct.pack("<I", seq) + random.randbytes(size - 4))
            self._emit(esp32.MSG_BENCH, struct.pack("<II", 0xFFFFFFFF, 0))
        else:
            self._result(t, 0x106)

    def _watch_host(self) -> None:
        """The firmware's host watchdog: a host silent past host_silent_after leaves the network."""
        while self._watched:
            time.sleep(0.02)
            with self.air.lock:
                if self._watched and self.mode != IDLE and time.monotonic() - self._host_seen > self.host_silent_after:
                    self._watched = False
                    self._go_idle()
                    self._emit(esp32.MSG_LOG, b"host silent: left the network")

    def _go_idle(self) -> None:
        if self.mode == STA and self.ap is not None:
            self.ap.stations.pop(self.sta_mac, None)
            self.ap._emit(esp32.MSG_STA_LEFT, self.sta_mac + struct.pack("<H", 8))
        elif self.mode == AP:
            for mac in list(self.stations):
                self._drop_station(mac, 3)
        self.mode, self.ap = IDLE, None
        self.key = b""

    def _drop_station(self, mac: bytes, reason: int) -> None:
        station = self.stations.pop(mac)
        self._emit(esp32.MSG_STA_LEFT, mac + struct.pack("<H", reason))
        if station.mode == STA and station.ap is self:
            station.mode, station.ap = IDLE, None
            station._emit(esp32.MSG_LINK, b"\x00" + struct.pack("<H", reason) + station.sta_mac)

    def _ethernet_tx(self, frame: bytes) -> None:
        if len(frame) < 14:
            return
        target = frame[0:6]
        if self.mode == STA and self.ap is not None and self.ap.key == self.key:
            if target in (self.bssid, b"\xff" * 6):
                self.ap._emit(esp32.MSG_RX_ETH, frame)
        elif self.mode == AP:
            for mac, station in self.stations.items():
                if target in (mac, b"\xff" * 6) and station.key == self.key:
                    station._emit(esp32.MSG_RX_ETH, frame)

    def _raw_tx(self, frame: bytes) -> None:
        self.sent_raw.append(frame)
        if len(frame) < 28 or frame[0] & 0xFC != 0xD0 or frame[24:28] != b"\x7f\x00\x22\xaa":
            return
        for board in self.air.boards:
            if board is not self and board.channel == self.channel:
                board._emit(esp32.MSG_RX_MGMT, bytes([self.channel, (-40) & 0xFF]) + frame)

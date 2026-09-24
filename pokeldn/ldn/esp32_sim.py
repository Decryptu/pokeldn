"""A simulated ESP32 radio: the firmware's message set (`firmware/esp32/main/radio.c`) over an
in-process byte stream, and an `Air` several boards share. It carries what the firmware's
driver would carry: action frames to every board on the channel, a station's association to the
access point with the same BSSID, SSID and channel, and Ethernet frames between them when both
hold the same CCMP key. It knows nothing of LDN above that.
"""

import queue
import random
import struct
import threading

from pokeldn.ldn import esp32

IDLE, STA, AP = "idle", "sta", "ap"


class _HostStream:
    """The host end of the simulated USB serial port."""

    def __init__(self, board: "SimulatedBoard"):
        self._board = board
        self._inbox: queue.Queue[bytes] = queue.Queue()

    def read(self, n: int) -> bytes:
        try:
            data = self._inbox.get(timeout=0.02)
        except queue.Empty:
            return b""
        while len(data) < n:
            try:
                data += self._inbox.get_nowait()
            except queue.Empty:
                break
        return data

    def write(self, data: bytes) -> None:
        self._board._from_host(data)

    def close(self) -> None:
        pass


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
        self.channel = 1
        self.bssid = b""
        self.ssid = b""
        self.key = b""
        self.stations: dict[bytes, "SimulatedBoard"] = {}   # AP: mac -> station board
        self.ap: "SimulatedBoard | None" = None              # STA: the joined access point
        self.stream = _HostStream(self)
        self._reader = esp32.FrameReader()
        self.sent_raw: list[bytes] = []
        air.attach(self)

    # ---- host link ----

    def host_stream(self) -> _HostStream:
        return self.stream

    def _emit(self, msg_type: int, payload: bytes = b"") -> None:
        self.stream._inbox.put(esp32.encode_frame(msg_type, payload))

    def _result(self, command: int, code: int = 0) -> None:
        self._emit(esp32.MSG_RESULT, bytes([command]) + struct.pack("<i", code))

    def _from_host(self, data: bytes) -> None:
        for msg_type, payload in self._reader.feed(data):
            with self.air.lock:
                self._command(msg_type, payload)

    # ---- the firmware's commands ----

    def _command(self, t: int, p: bytes) -> None:
        if t == esp32.CMD_HELLO:
            self._emit(esp32.MSG_INFO, bytes([esp32.PROTOCOL_VERSION]) + self.sta_mac + self.ap_mac
                       + b"\x03" + b"pokeldn-radio simulated")
        elif t == esp32.CMD_BAUD:
            self._result(t)
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
        elif t == esp32.CMD_BENCH:
            total, size = struct.unpack("<IH", p)
            self._result(t)
            for seq in range(-(-total // size)):
                self._emit(esp32.MSG_BENCH, struct.pack("<I", seq) + random.randbytes(size - 4))
            self._emit(esp32.MSG_BENCH, struct.pack("<II", 0xFFFFFFFF, 0))
        else:
            self._result(t, 0x106)

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

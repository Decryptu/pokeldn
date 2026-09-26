"""The host side of the ESP32 radio (`firmware/esp32/`): its serial framing, its message set, and a
link object that owns the port.

A frame on the wire is COBS(type | payload | crc32-le(type | payload)) followed by 0x00. The board
carries Ethernet frames and LDN vendor action frames; everything above them runs here. The message
set is the one `firmware/esp32/main/radio.c` implements, documented in `docs/hardware_esp32.md`.
"""

import collections
import os
import struct
import threading
import time
import zlib
from dataclasses import dataclass

PROTOCOL_VERSION = 1

CMD_HELLO = 0x01
CMD_BAUD = 0x02
CMD_CHANNEL = 0x03
CMD_STA_JOIN = 0x04
CMD_STOP = 0x05
CMD_AP_START = 0x06
CMD_AP_KICK = 0x07
CMD_ETH_TX = 0x08
CMD_RAW_TX = 0x09
CMD_SNIFF = 0x0A
CMD_STATUS = 0x0B
CMD_BENCH = 0x0C
CMD_LED = 0x0D      # u8 pattern, u8 peak, u16 period ms, u16 duration ms: the board's blue LED

# The LED's patterns (firmware/esp32/main/led.h); "auto" hands the LED back to the radio's state.
LED_PATTERNS = ("auto", "off", "on", "breathe", "blink", "flash3", "ramp-up", "ramp-down", "pulse")


def led_payload(pattern: str, peak: int = 255, period_ms: int = 0, duration_ms: int = 0) -> bytes:
    return struct.pack("<BBHH", LED_PATTERNS.index(pattern), peak, period_ms, duration_ms)

MSG_INFO = 0x81
MSG_RESULT = 0x82
MSG_LOG = 0x83
MSG_RX_MGMT = 0x84
MSG_RX_ETH = 0x85
MSG_LINK = 0x86
MSG_STA_JOINED = 0x87
MSG_STA_LEFT = 0x88
MSG_STATUS = 0x89
MSG_BENCH = 0x8A
MSG_RX_SNIFF = 0x8C   # u8 channel, i8 RSSI, u8 sig mode, u8 rate code, u8 MCS | 40 MHz << 7, frame
MSG_CREDIT = 0x8B   # u32: host bytes the board has read and handled since the last HELLO
MSG_BUTTON = 0x8E   # u32 board us, u16 press count: the BOOT button, a marker for the trace
MSG_TX_DONE = 0x8D  # u32 board us, u32 us since its ETH_TX (all ones: not one), u8 acked, u8 if, u16 len, 24 frame bytes

# The board handles a command on the task that reads the UART, so an ETH_TX waiting on a full Wi-Fi
# queue stops the reading; past 16 KB its RX ring overflows and commands are lost. Once the board
# reports CREDIT the host keeps under FLOW_WINDOW bytes in flight. docs/hardware_esp32.md.
FLOW_WINDOW = 8192
# The window stays shut: a board repeating one count past FLOW_STALL is idle and the rest was lost on
# the line; a silent one is busy (a Scarlet seat held its reader 0.7 s) and gets FLOW_BLIND.
FLOW_STALL = 0.3
FLOW_BLIND = 5.0
QUEUE_LIMIT = 512       # frames waiting on the host; ETH_TX and RAW_TX beyond it are dropped here

AP_FLAG_STOCK_JOIN = 1      # let the stock hostapd answer the association and start its 4-way handshake
AP_FLAG_NO_QOS = 2          # clear the station node's QoS flag: non-QoS data frames to it
AP_FLAG_NO_DATA_TRACE = 4   # skip the 40-byte copy of each station data frame (serial bandwidth)

LINK_TIMEOUT = 0xFFFF       # MSG_LINK reason: no association within 15 s
LINK_KEY_FAILED = 0xFFFE    # MSG_LINK reason: the driver refused the CCMP keys


def cobs_encode(data: bytes) -> bytes:
    out = bytearray([0])
    code_at, code = 0, 1
    for b in data:
        if b == 0:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
            continue
        out.append(b)
        code += 1
        if code == 255:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
    out[code_at] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        block = data[i + 1:i + code]
        if code == 0 or len(block) != code - 1:
            raise ValueError("bad COBS block")
        out += block
        i += code
        if code != 255 and i < len(data):
            out.append(0)
    return bytes(out)


def encode_frame(msg_type: int, payload: bytes = b"") -> bytes:
    body = bytes([msg_type]) + payload
    return cobs_encode(body + struct.pack("<I", zlib.crc32(body))) + b"\x00"


def decode_frame(encoded: bytes) -> tuple[int, bytes]:
    """`encoded` excludes the 0x00 delimiter. Raises ValueError on a bad block or checksum."""
    body = cobs_decode(encoded)
    if len(body) < 5:
        raise ValueError("frame too short")
    if struct.unpack("<I", body[-4:])[0] != zlib.crc32(body[:-4]):
        raise ValueError("bad frame checksum")
    return body[0], body[1:-4]


class FrameReader:
    """Accumulates bytes and yields whole frames; noise and boot text before a 0x00 are dropped."""

    def __init__(self):
        self._buffer = bytearray()
        self.rejected = 0

    def feed(self, data: bytes):
        for b in data:
            if b:
                self._buffer.append(b)
                continue
            if self._buffer:
                try:
                    yield decode_frame(bytes(self._buffer))
                except ValueError:
                    self.rejected += 1
                self._buffer.clear()


def mac_bytes(mac) -> bytes:
    if isinstance(mac, (bytes, bytearray)):
        return bytes(mac)
    if hasattr(mac, "encode") and not isinstance(mac, str):
        return mac.encode()
    return bytes.fromhex(str(mac).replace(":", ""))


def sta_join_payload(channel: int, bssid, ssid: str, key: bytes, mac=bytes(6)) -> bytes:
    ssid_bytes = ssid.encode("ascii")
    if len(ssid_bytes) != 32 or len(key) != 16:
        raise ValueError("an LDN SSID is 32 hex characters and the key 16 bytes")
    return bytes([channel]) + mac_bytes(bssid) + ssid_bytes + key + mac_bytes(mac)


def ap_start_payload(channel: int, bssid, ssid: str, key: bytes, max_stations: int = 7,
                     flags: int = 0) -> bytes:
    ssid_bytes = ssid.encode("ascii")
    if len(ssid_bytes) != 32 or len(key) != 16:
        raise ValueError("an LDN SSID is 32 hex characters and the key 16 bytes")
    return bytes([channel]) + mac_bytes(bssid) + ssid_bytes + key + bytes([max_stations, flags])


@dataclass
class Info:
    version: int
    sta_mac: bytes
    ap_mac: bytes
    chip_revision: int
    text: str

    @classmethod
    def parse(cls, payload: bytes) -> "Info":
        return cls(payload[0], payload[1:7], payload[7:13], payload[13], payload[14:].decode(errors="replace"))


@dataclass
class Link:
    up: bool
    reason: int
    mac: bytes

    @classmethod
    def parse(cls, payload: bytes) -> "Link":
        return cls(bool(payload[0]), struct.unpack_from("<H", payload, 1)[0], payload[3:9])


@dataclass
class StationJoined:
    mac: bytes
    aid: int
    key_result: int
    port_opened: bool

    @classmethod
    def parse(cls, payload: bytes) -> "StationJoined":
        return cls(payload[0:6], payload[6], struct.unpack("b", payload[7:8])[0], bool(payload[8]))


@dataclass
class StationLeft:
    mac: bytes
    reason: int

    @classmethod
    def parse(cls, payload: bytes) -> "StationLeft":
        return cls(payload[0:6], struct.unpack_from("<H", payload, 6)[0])


@dataclass
class ManagementFrame:
    channel: int
    rssi: int
    frame: bytes      # the 802.11 frame without its FCS

    @classmethod
    def parse(cls, payload: bytes) -> "ManagementFrame":
        return cls(payload[0], struct.unpack("b", payload[1:2])[0], payload[2:])


class RadioError(Exception):
    pass


class Radio:
    """Owns one byte stream to a board. `stream` needs `read(n)` returning within a short timeout
    and `write(data)`; a pyserial port and `esp32_sim.SimulatedBoard.host_stream()` both qualify.

    Events go to every subscriber callback from the reader thread; `request` waits for the
    reply a command produces."""

    def __init__(self, stream, log=None):
        self._stream = stream
        self._log = log
        self._write_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._reader = FrameReader()
        self._subscribers: list = []
        self._subscribers_lock = threading.Lock()
        self._replies: dict[int, list] = {}
        self._reply_cv = threading.Condition()
        self._closed = False
        self._out: collections.deque = collections.deque()
        self._out_cv = threading.Condition()
        self._written = self._credited = 0
        self._credit_seen = 0.0     # monotonic time of the last CREDIT, moved or not
        self._lost = 0      # bytes a resync wrote off; the board's count stays behind by them
        self._flow = False
        self.tx_dropped = self.flow_resyncs = 0
        # POKELDN_ESP32_TRACE=FILE records every message both ways: time, direction, type, hex.
        trace = os.environ.get("POKELDN_ESP32_TRACE")
        self._trace = open(trace, "a", buffering=1) if trace else None
        self._thread = threading.Thread(target=self._read_loop, name="esp32-radio", daemon=True)
        self._thread.start()
        self._writer = threading.Thread(target=self._write_loop, name="esp32-writer", daemon=True)
        self._writer.start()

    @classmethod
    def open_serial(cls, port: str, baud: int = 115200, fast_baud: int | None = None, log=None):
        """`fast_baud` defaults to POKELDN_ESP32_BAUD, else 921600, the rate every run so far used."""
        import serial
        if fast_baud is None:
            fast_baud = int(os.environ.get("POKELDN_ESP32_BAUD", "921600"))
        s = serial.Serial()
        s.port = port
        s.baudrate = baud
        s.timeout = 0.02
        # Most ESP32 boards reset on a DTR/RTS edge; keep both released so opening does not.
        s.dtr = False
        s.rts = False
        s.open()
        radio = cls(s, log=log)
        # Opening the port still resets some boards (a CP2102 on macOS); a HELLO sent during the
        # boot is lost, so retry past it.
        for attempt in range(5):
            try:
                radio.request(CMD_HELLO, b"", MSG_INFO, timeout=1.0)
                break
            except RadioError:
                if attempt == 4:
                    raise
        radio.hello()
        if fast_baud and fast_baud != baud:
            radio.request(CMD_BAUD, struct.pack("<I", fast_baud), MSG_RESULT)
            radio.drain()
            s.flush()
            s.baudrate = fast_baud
            # A HELLO that reaches the board while it is still switching is lost (one open in four
            # at 1500000), so retry it as the first one is.
            for attempt in range(5):
                try:
                    radio.request(CMD_HELLO, b"", MSG_INFO, timeout=0.5)
                    break
                except RadioError:
                    if attempt == 4:
                        raise
            radio.hello()
        if radio._trace:
            # The board's counters (tx_eth_failed, wire_dropped) land in the trace every 5 s.
            threading.Thread(target=radio._poll_status, name="esp32-status", daemon=True).start()
        return radio

    def _poll_status(self) -> None:
        while not self._closed:
            time.sleep(5)
            try:
                self.send(CMD_STATUS)
            except Exception:
                return

    def close(self) -> None:
        self._closed = True
        with self._out_cv:
            self._out_cv.notify_all()
        self._writer.join(timeout=1)
        self._thread.join(timeout=1)
        close = getattr(self._stream, "close", None)
        if close:
            close()

    # ---- plumbing ----

    def subscribe(self, callback) -> None:
        with self._subscribers_lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        with self._subscribers_lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def send(self, msg_type: int, payload: bytes = b"") -> None:
        """Queues one command; the writer thread sends it in order. Never blocks the caller."""
        frame = encode_frame(msg_type, payload)
        with self._out_cv:
            if len(self._out) >= QUEUE_LIMIT and msg_type in (CMD_ETH_TX, CMD_RAW_TX):
                self.tx_dropped += 1
                return
            self._out.append((msg_type, payload, frame))
            self._out_cv.notify_all()

    def drain(self, timeout: float = 5.0) -> bool:
        """Waits until every queued command has been written to the port."""
        deadline = time.monotonic() + timeout
        with self._out_cv:
            while self._out or self._writing:
                left = deadline - time.monotonic()
                if left <= 0 or self._closed:
                    return False
                self._out_cv.wait(left)
        return True

    _writing = False

    def _write_loop(self) -> None:
        while True:
            with self._out_cv:
                while not self._out and not self._closed:
                    self._out_cv.wait()
                if self._closed:
                    return
                msg_type, payload, frame = self._out.popleft()
                self._writing = True
                last, since = self._credited, time.monotonic()
                while (self._flow and not self._closed
                       and self._written - self._credited + len(frame) > FLOW_WINDOW):
                    quiet = time.monotonic() - since
                    if self._credited != last:
                        last, since = self._credited, time.monotonic()
                    elif ((quiet > FLOW_STALL and self._credit_seen > since + FLOW_STALL * 2 / 3)
                          or quiet > FLOW_BLIND):
                        # Bytes the board never counted (lost on the line) would hold the window
                        # shut for good.
                        self.flow_resyncs += 1
                        self._record("!", MSG_CREDIT, struct.pack("<II", self._written, self._credited))
                        self._lost += self._written - self._credited
                        self._credited = self._written
                        break
                    self._out_cv.wait(0.05)
            self._record(">", msg_type, payload)
            try:
                with self._write_lock:
                    self._stream.write(frame)
            except Exception as e:
                if self._log:
                    self._log(f"[esp32] write failed: {e}")
            with self._out_cv:
                self._written += len(frame)
                if msg_type == CMD_HELLO:
                    # The board restarts its count after a HELLO's delimiter; so does the host.
                    self._written = self._credited = self._lost = 0
                    self._flow = False
                self._writing = False
                self._out_cv.notify_all()

    def request(self, msg_type: int, payload: bytes, reply_type: int, timeout: float = 3.0) -> bytes:
        """Sends a command and returns the payload of the next `reply_type` message. A MSG_RESULT
        reply is checked: it must name this command and carry code 0."""
        with self._request_lock:
            return self._request(msg_type, payload, reply_type, timeout)

    def _request(self, msg_type: int, payload: bytes, reply_type: int, timeout: float) -> bytes:
        with self._reply_cv:
            self._replies[reply_type] = []
        self.send(msg_type, payload)
        with self._reply_cv:
            while True:
                pending = self._replies.get(reply_type, [])
                while pending:
                    reply = pending.pop(0)
                    if reply_type != MSG_RESULT:
                        del self._replies[reply_type]
                        return reply
                    if reply[0] != msg_type:
                        continue
                    del self._replies[reply_type]
                    code = struct.unpack_from("<i", reply, 1)[0]
                    if code:
                        raise RadioError(f"command 0x{msg_type:02x} failed: {code:#x}")
                    return reply
                if not self._reply_cv.wait(timeout):
                    self._replies.pop(reply_type, None)
                    raise RadioError(f"no reply 0x{reply_type:02x} to command 0x{msg_type:02x}")

    def _read_loop(self) -> None:
        while not self._closed:
            try:
                data = self._stream.read(4096)
            except Exception as e:
                if self._log:
                    self._log(f"[esp32] read failed: {e}")
                return
            if not data:
                continue
            for msg_type, payload in self._reader.feed(data):
                self._dispatch(msg_type, payload)

    def _record(self, direction: str, msg_type: int, payload: bytes) -> None:
        if self._trace:
            self._trace.write(f"{time.time():.6f} {direction} {msg_type:02x} {payload.hex()}\n")

    def _dispatch(self, msg_type: int, payload: bytes) -> None:
        if msg_type == MSG_CREDIT and len(payload) == 4:
            credit = struct.unpack("<I", payload)[0]
            self._record("<", msg_type, payload)
            with self._out_cv:
                self._credit_seen = time.monotonic()
                # More than was written since the HELLO is a count from before it. A count past
                # what the written-off bytes allow means a resync wrote off bytes the board had.
                if credit <= self._written:
                    self._lost = min(self._lost, self._written - credit)
                    self._credited = max(self._credited, credit + self._lost)
                    self._flow = True
                    self._out_cv.notify_all()
            return
        self._record("<", msg_type, payload)
        if msg_type == MSG_LOG and self._log:
            self._log(f"[esp32] {payload.decode(errors='replace')}")
        if msg_type == MSG_BUTTON and len(payload) == 6 and self._log:
            self._log(f"[esp32] BOOT button, mark {struct.unpack_from('<H', payload, 4)[0]}")
        with self._reply_cv:
            if msg_type in self._replies:
                self._replies[msg_type].append(payload)
                self._reply_cv.notify_all()
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(msg_type, payload)

    # ---- commands ----

    def hello(self) -> Info:
        info = Info.parse(self.request(CMD_HELLO, b"", MSG_INFO))
        if info.version != PROTOCOL_VERSION:
            raise RadioError(f"board speaks protocol {info.version}, host speaks {PROTOCOL_VERSION}")
        return info

    def set_channel(self, channel: int) -> None:
        self.request(CMD_CHANNEL, bytes([channel]), MSG_RESULT)

    def sta_join(self, channel: int, bssid, ssid: str, key: bytes, mac=bytes(6)) -> None:
        self.request(CMD_STA_JOIN, sta_join_payload(channel, bssid, ssid, key, mac), MSG_RESULT)

    def ap_start(self, channel: int, bssid, ssid: str, key: bytes, max_stations: int = 7,
                 flags: int = 0) -> None:
        self.request(CMD_AP_START, ap_start_payload(channel, bssid, ssid, key, max_stations, flags),
                     MSG_RESULT, timeout=5.0)

    def stop(self) -> None:
        self.request(CMD_STOP, b"", MSG_RESULT, timeout=5.0)

    def kick(self, mac, reason: int = 1) -> None:
        self.request(CMD_AP_KICK, mac_bytes(mac) + struct.pack("<H", reason), MSG_RESULT)

    def send_ethernet(self, frame: bytes) -> None:
        self.send(CMD_ETH_TX, frame)

    def send_raw(self, frame: bytes) -> None:
        self.send(CMD_RAW_TX, frame)

    def sniff(self, channel: int, mac) -> None:
        """Every management and data frame to or from `mac` on `channel`, whole, as RX_MGMT."""
        self.request(CMD_SNIFF, bytes([channel]) + mac_bytes(mac), MSG_RESULT, timeout=5.0)

    def bench(self, total: int, size: int = 1400, timeout: float = 60.0) -> dict:
        """Asks the board for `total` bytes in `size`-byte messages as fast as the link carries
        them. -> {bytes, messages, missing, rejected, seconds, board_seconds, rate}."""
        got, done = [], threading.Event()
        state = {"first": None, "last": None, "board_us": None}
        rejected = self._reader.rejected

        def on_message(msg_type, payload):
            if msg_type != MSG_BENCH:
                return
            now = time.monotonic()
            seq = struct.unpack_from("<I", payload)[0]
            if seq == 0xFFFFFFFF:
                state["board_us"] = struct.unpack_from("<I", payload, 4)[0]
                done.set()
                return
            state["first"] = state["first"] or now
            state["last"] = now
            got.append((seq, len(payload)))

        self.subscribe(on_message)
        try:
            self.request(CMD_BENCH, struct.pack("<IH", total, size), MSG_RESULT)
            done.wait(timeout)
        finally:
            self.unsubscribe(on_message)
        received = sum(n for _, n in got)
        expected = -(-total // size)
        seconds = (state["last"] - state["first"]) if len(got) > 1 else 0.0
        return {"bytes": received, "messages": len(got),
                "missing": expected - len({seq for seq, _ in got}),
                "rejected": self._reader.rejected - rejected, "seconds": seconds,
                "board_seconds": (state["board_us"] or 0) / 1e6,
                "rate": received / seconds if seconds else 0.0}

    def led(self, pattern: str, peak: int = 255, period_ms: int = 0, duration_ms: int = 0) -> None:
        """Shows `pattern` for duration_ms (0: until the next call); a period of 0 is the pattern's
        default. A board flashed before the LED command answers RadioError 0x106."""
        self.request(CMD_LED, led_payload(pattern, peak, period_ms, duration_ms), MSG_RESULT)

    def status(self) -> str:
        return self.request(CMD_STATUS, b"", MSG_STATUS).decode(errors="replace")

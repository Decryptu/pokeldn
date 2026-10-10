"""The serial link to a controller board on its USB-to-serial port: the classic ESP32, which reaches
the Switch over Bluetooth Classic [docs/hardware_pad.md, The serial side].

Frames both ways: A5 5A, length u16 (type and payload), type u8, payload, sum of type and payload
mod 256. Host to board: 0x01 report, 0x02 status, 0x03 command. Board to host: 0x81 result (i8),
0x82 status record.
"""
import asyncio
import struct
import threading
import time

from pokeldn.pad.link import DOWNLOAD, PLAY, STOP, Status, parse_status, program_writes
from pokeldn.pad.macro import NEUTRAL, Program

MAGIC = b"\xa5\x5a"
REPORT, STATUS, COMMAND = 0x01, 0x02, 0x03
RESULT, STATUS_REPLY = 0x81, 0x82
BAUD = 921600
BOOT_WAIT = 3.0   # seconds a board reset by the port opening may take to answer


def frame(kind: int, payload: bytes = b"") -> bytes:
    body = bytes([kind]) + payload
    return MAGIC + struct.pack("<H", len(body)) + body + bytes([sum(body) & 0xFF])


class Reader:
    """Frames out of a byte stream that may carry the ROM's boot text or a broken frame."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self.buf += data
        out = []
        while True:
            start = self.buf.find(MAGIC)
            if start < 0:
                del self.buf[:-1]
                return out
            del self.buf[:start]
            if len(self.buf) < 4:
                return out
            (length,) = struct.unpack_from("<H", self.buf, 2)
            if not 1 <= length <= 600:
                del self.buf[:2]
                continue
            if len(self.buf) < 4 + length + 1:
                return out
            body, check = bytes(self.buf[4:4 + length]), self.buf[4 + length]
            if sum(body) & 0xFF != check:
                del self.buf[:2]
                continue
            del self.buf[:4 + length + 1]
            out.append((body[0], body[1:]))


class SerialError(ConnectionError):
    pass


class SerialPad:
    """The same coroutines as link.Pad, over a serial port."""

    def __init__(self, port: str):
        import serial
        s = serial.Serial()
        s.port, s.baudrate, s.timeout = port, BAUD, 0.05
        s.dtr = s.rts = False   # most boards reset on a DTR/RTS edge
        s.open()
        self.port = port
        self.serial = s
        self.reader = Reader()
        self.lock = threading.Lock()

    @classmethod
    async def connect(cls, port: str):
        pad = await asyncio.to_thread(cls, port)
        # Opening the port resets a CP2102 board; a request sent during its boot is lost.
        end = time.monotonic() + BOOT_WAIT
        while True:
            try:
                await pad.status()
                return pad
            except SerialError:
                if time.monotonic() < end:
                    continue
                await pad.close()
                raise
            except Exception:
                await pad.close()
                raise

    @property
    def connected(self) -> bool:
        return self.serial.is_open

    def _ask(self, kind: int, payload: bytes, want: int, timeout: float = 1.0) -> bytes:
        with self.lock:
            self.serial.reset_input_buffer()
            self.reader.buf.clear()
            self.serial.write(frame(kind, payload))
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                for got, body in self.reader.feed(self.serial.read(256)):
                    if got == want:
                        return body
        raise SerialError(f"no answer from the controller board on {self.port}")

    def _call(self, kind: int, payload: bytes) -> None:
        body = self._ask(kind, payload, RESULT)
        (rc,) = struct.unpack("<b", body[:1])
        if rc:
            raise SerialError(f"the board refused the request ({rc})")

    async def send(self, report: bytes):
        await asyncio.to_thread(self._call, REPORT, report)

    async def status(self) -> Status:
        return parse_status(await asyncio.to_thread(self._ask, STATUS, b"", STATUS_REPLY))

    async def load(self, program: Program, progress=None):
        writes = program_writes(program)
        for n, w in enumerate(writes, 1):
            await asyncio.to_thread(self._call, COMMAND, w)
            if progress:
                progress(n, len(writes))

    async def play(self):
        await asyncio.to_thread(self._call, COMMAND, bytes([PLAY]))

    async def stop(self):
        await asyncio.to_thread(self._call, COMMAND, bytes([STOP]))

    async def download(self):
        await asyncio.to_thread(self._call, COMMAND, bytes([DOWNLOAD]))

    async def close(self):
        if self.serial.is_open:
            try:
                await self.send(NEUTRAL)
            except Exception:
                pass
            self.serial.close()


def candidates() -> list[str]:
    """USB serial ports that may hold a classic board."""
    from serial.tools import list_ports
    return sorted(p.device for p in list_ports.comports()
                  if p.vid is not None and (p.vid, p.pid) != (0x303A, 0x1001))

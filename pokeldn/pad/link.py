"""The Bluetooth LE link to the controller board [docs/hardware_pad.md, The Bluetooth side]."""
import asyncio
import struct
from dataclasses import dataclass

from pokeldn.pad.macro import NEUTRAL, Program, encode_entry

NAME = "POKELDN-PAD"
REPORT = "7a1e0002-5d2c-4c3e-9f4b-504f4b454c44"
STATUS = "7a1e0003-5d2c-4c3e-9f4b-504f4b454c44"
CONTROL = "7a1e0004-5d2c-4c3e-9f4b-504f4b454c44"
LOAD, DATA, PLAY, STOP, DOWNLOAD = 0x10, 0x11, 0x12, 0x13, 0xB0
CHUNK = 18      # entries per DATA write: 3 + 18 * 10 bytes fits a 185-byte ATT MTU


@dataclass(frozen=True)
class Status:
    mounted: bool           # the console has configured the board's USB device
    writes: int
    playing: bool = False
    loops_done: int = 0
    index: int = 0
    count: int = 0
    version: str = ""
    reset_reason: int = -1      # esp_reset_reason() of this boot
    stage_before: int = -1      # how far the previous boot got (firmware/pad/main/pad.c)
    boots: int = 0              # boots since power-on


def parse_status(raw: bytes) -> Status:
    mounted, writes = struct.unpack_from("<BI", raw)
    if len(raw) < 14:
        return Status(bool(mounted), writes)
    playing, done, index, count = struct.unpack_from("<BIHH", raw, 5)
    version, _, extra = raw[14:].partition(b"\0")
    reason, stage, boots = struct.unpack("<BBH", extra) if len(extra) == 4 else (-1, -1, 0)
    return Status(bool(mounted), writes, bool(playing), done, index, count,
                  version.decode(errors="replace"), reason, stage, boots)


def program_writes(program: Program) -> list[bytes]:
    """The CONTROL writes that load a program: LOAD, then DATA chunks."""
    out = [struct.pack("<BHHI", LOAD, len(program.entries), program.loop_start, program.loops)]
    for first in range(0, len(program.entries), CHUNK):
        body = b"".join(encode_entry(r, ms) for r, ms in program.entries[first:first + CHUNK])
        out.append(struct.pack("<BH", DATA, first) + body)
    return out


async def find(timeout=10.0):
    from bleak import BleakScanner
    return await BleakScanner.find_device_by_name(NAME, timeout=timeout)


class Pad:
    """One connection to a board. Every method is a coroutine on the caller's event loop."""

    def __init__(self, device):
        from bleak import BleakClient
        self.client = BleakClient(device)

    @classmethod
    async def connect(cls, timeout=10.0):
        device = await find(timeout)
        if device is None:
            raise ConnectionError(f"no {NAME} found: is the board powered and running the controller firmware?")
        pad = cls(device)
        await pad.client.connect()
        return pad

    @property
    def connected(self) -> bool:
        return self.client.is_connected

    async def send(self, report: bytes):
        # CoreBluetooth drops a write without response its queue cannot take, and bleak never asks
        # canSendWriteWithoutResponse; elsewhere, or if the queue stays full, a response paces it
        # (docs/hardware_pad.md, The Bluetooth side).
        peripheral = getattr(getattr(self.client, "_backend", None), "_peripheral", None)
        if peripheral is not None and hasattr(peripheral, "canSendWriteWithoutResponse"):
            for _ in range(500):
                if peripheral.canSendWriteWithoutResponse():
                    await self.client.write_gatt_char(REPORT, report, response=False)
                    return
                await asyncio.sleep(0.002)
        await self.client.write_gatt_char(REPORT, report, response=True)

    async def status(self) -> Status:
        return parse_status(bytes(await self.client.read_gatt_char(STATUS)))

    async def load(self, program: Program, progress=None):
        writes = program_writes(program)
        for n, w in enumerate(writes, 1):
            await self.client.write_gatt_char(CONTROL, w, response=True)
            if progress:
                progress(n, len(writes))

    async def play(self):
        await self.client.write_gatt_char(CONTROL, bytes([PLAY]), response=True)

    async def stop(self):
        await self.client.write_gatt_char(CONTROL, bytes([STOP]), response=True)

    async def download(self):
        await self.client.write_gatt_char(CONTROL, bytes([DOWNLOAD]), response=True)

    async def close(self):
        if self.client.is_connected:
            try:
                await self.send(NEUTRAL)
            finally:
                await self.client.disconnect()

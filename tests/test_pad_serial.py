import asyncio
import os
import struct
import threading
from types import SimpleNamespace

import pytest

from pokeldn.pad import macro
from pokeldn.pad.serial_link import Reader, SerialPad, frame

pytestmark = pytest.mark.skipif(os.name == "nt", reason="a pty stands in for the board's port")

# Frames written out by hand from docs/hardware_pad.md, The serial side.
STATUS_REQUEST = bytes.fromhex("a55a01000202")
ACK = bytes.fromhex("a55a0200810081")


def test_frames_match_the_documented_bytes():
    assert frame(0x02) == STATUS_REQUEST
    assert frame(0x81, b"\x00") == ACK


def test_reader_skips_boot_text_and_broken_frames_and_joins_split_ones():
    boot = b"ets Jun  8 2016 00:22:57\r\nrst:0x1 (POWERON_RESET),boot:0x13\r\n"
    broken = bytes.fromhex("a55a0200810082")          # bad sum
    stream = boot + broken + ACK + frame(0x82, b"\x01\x02")
    r = Reader()
    got = []
    for i in range(0, len(stream), 5):               # arrives in pieces
        got += r.feed(stream[i:i + 5])
    assert got == [(0x81, b"\x00"), (0x82, b"\x01\x02")]


class FakeBoard(threading.Thread):
    """The board side of the documented protocol on a pty, recording what it was sent."""

    def __init__(self, fd):
        super().__init__(daemon=True)
        self.fd, self.reports, self.commands, self.running = fd, [], [], True

    def run(self):
        r = Reader()
        os.write(self.fd, b"rst:0x1 (POWERON_RESET)\r\n")
        while self.running:
            try:
                data = os.read(self.fd, 256)
            except OSError:
                return
            for kind, body in r.feed(data):
                if kind == 0x01:
                    self.reports.append(body)
                    os.write(self.fd, frame(0x81, b"\x00"))
                elif kind == 0x03:
                    self.commands.append(body)
                    os.write(self.fd, frame(0x81, b"\x00"))
                elif kind == 0x02:
                    record = bytes([1]) + struct.pack("<IBIHH", len(self.reports), 0, 0, 0, 0) + b"1.1.0"
                    os.write(self.fd, frame(0x82, record))


def test_a_macro_loads_and_presses_over_a_serial_port(monkeypatch):
    import tty
    from pokeldn.pad import serial_link
    monkeypatch.setattr(serial_link, "BAUD", 115200)    # a pty takes no IOSSIOSPEED rate
    board_fd, host_fd = os.openpty()
    tty.setraw(board_fd)
    tty.setraw(host_fd)
    board = FakeBoard(board_fd)
    board.start()
    program = macro.compile_macro(macro.loads(
        '{"format": "pokeldn-macro", "version": 1, "loop": [{"repeat": 30, "steps": [{"press": "A"}]}], "loops": 0}'))

    async def run():
        pad = await SerialPad.connect(os.ttyname(host_fd))
        assert (await pad.status()).version == "1.1.0"
        await pad.send(macro.state(["B"]))
        await pad.load(program)
        await pad.play()
        status = await pad.status()
        await pad.close()
        return status

    status = asyncio.run(run())
    board.running = False
    assert status.mounted and status.writes == 1
    assert board.reports[0] == macro.state(["B"]) and board.reports[-1] == macro.NEUTRAL
    load, *data, play = board.commands
    assert struct.unpack("<BHHI", load) == (0x10, len(program.entries), 0, 0)
    assert b"".join(d[3:] for d in data) == b"".join(r + struct.pack("<H", ms) for r, ms in program.entries)
    assert play == b"\x12"


def test_a_report_waits_while_corebluetooth_cannot_take_a_write_without_response():
    """A write CoreBluetooth cannot queue is dropped with no error: 67 of 300 reached the board."""
    from pokeldn.pad import link

    class Peripheral:
        free = 0

        def canSendWriteWithoutResponse(self):
            Peripheral.free += 1
            return Peripheral.free > 3

    writes = []

    class Client:
        _backend = SimpleNamespace(_peripheral=Peripheral())

        async def write_gatt_char(self, uuid, data, response):
            writes.append((Peripheral.free, response))

    pad = link.Pad.__new__(link.Pad)
    pad.client = Client()
    asyncio.run(pad.send(macro.NEUTRAL))
    assert writes == [(4, False)]
    Client._backend = SimpleNamespace(_peripheral=None)     # another platform: the response paces it
    asyncio.run(pad.send(macro.NEUTRAL))
    assert writes[-1][1] is True


def test_the_service_exits_when_the_app_closes_its_stdin():
    """asyncio.run never left on runner's interrupt: a closed app's service kept the port."""
    import socket
    import subprocess
    import sys
    import time
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    entry = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pokeldn", "app", "entry.py")
    child = subprocess.Popen([sys.executable, "-u", entry, "--module", "pokeldn.pad.service", "--port", str(port)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=dict(os.environ, POKELDN_MANAGED_RUN="1"))
    try:
        assert b"listening" in child.stdout.readline()
        child.stdin.close()
        child.wait(timeout=10)
    finally:
        child.kill()
        child.stdout.close()

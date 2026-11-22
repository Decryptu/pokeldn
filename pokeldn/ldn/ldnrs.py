"""Windows ldnd protocol 7 and its Ethernet bridge. See docs/hardware_adapters.md.
Wire contract: unlimitedcoder2/ldnrs, tag 0.0.3, docs/daemon-protocol.md.
"""
import contextlib
import math
import os
import socket
import struct
import sys
from types import SimpleNamespace

import trio
from ldn import DisconnectEvent, JoinEvent, LeaveEvent, wlan

from pokeldn.ldn import userspace_ip

HEADER = struct.Struct("<BBII")
MAX_BODY = 256 * 1024
DEFAULT_PIPE = r"\\.\pipe\ldnd"
JOIN_SECONDS = 70


def number(fmt, value):
    return struct.pack("<" + fmt, value)


def blob(value):
    return number("I", len(value)) + value


def text(value):
    return blob(value.encode("utf-8"))


def optional(value, encode):
    return b"\0" if value is None else b"\1" + encode(value)


class DaemonError(RuntimeError):
    def __init__(self, sub, status, message):
        self.status = status
        super().__init__(f"ldnrs request {sub:#x} failed ({status}): {message or 'no detail'}")


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, count):
        if count < 0 or self.offset + count > len(self.data):
            raise ValueError("Truncated ldnd message")
        start = self.offset
        self.offset += count
        return self.data[start:self.offset]

    def num(self, fmt):
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))[0]

    def blob(self):
        return self.take(self.num("I"))

    def text(self):
        return self.blob().decode("utf-8")

    def option(self, read):
        flag = self.num("B")
        if flag not in (0, 1):
            raise ValueError("Invalid ldnd optional field")
        return read() if flag else None

    def end(self):
        if self.offset != len(self.data):
            raise ValueError("Unexpected bytes in ldnd message; protocol 7 required")


def participant(r):
    return SimpleNamespace(ip_address=socket.inet_ntoa(r.take(4)),
                           mac_address=wlan.MACAddress(r.take(6)), connected=bool(r.num("B")),
                           name=r.blob(), app_version=r.num("H"), platform=r.num("B"))


def network_info(r):
    start = r.offset
    info = SimpleNamespace(protocol=r.num("B"), address=wlan.MACAddress(r.take(6)),
                           band=r.num("B"), channel=r.num("B"), local_communication_id=r.num("Q"),
                           scene_id=r.num("H"), ssid=r.take(16), version=r.num("B"),
                           server_random=r.take(16), security_mode=r.num("H"), app_version=r.num("H"),
                           accept_policy=r.num("B"), max_participants=r.num("B"),
                           num_participants=r.num("B"))
    count = r.num("I")
    if count > 8:
        raise ValueError("ldnd returned more than eight participants")
    info.participants = [participant(r) for _ in range(count)]
    info.application_data, info.challenge, info.nonce = r.blob(), r.num("Q"), r.take(4)
    info.raw = r.data[start:r.offset]
    return info


def daemon_running(path: str = DEFAULT_PIPE) -> bool:
    """Whether the ldnrs daemon's pipe exists; False off Windows."""
    return sys.platform == "win32" and os.path.exists(path)


class Pipe:
    @classmethod
    async def open(cls, path):
        if sys.platform != "win32":
            raise RuntimeError("The ldnrs USB Wi-Fi backend requires Windows")
        if not path.startswith("\\\\.\\pipe\\"):
            raise ValueError("ldnrs requires a local Windows named pipe")
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(path, 0xC0000000, 0, None, 3, 0x40000000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.get_last_error(),
                          "Cannot connect to ldnrs. Start its daemon after completing the adapter wizard.")
        result = cls()
        result.handle, result.kernel = handle, kernel
        try:
            trio.lowlevel.register_with_iocp(handle)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
        return result

    async def send_all(self, data):
        view = memoryview(data)
        while view:
            count = await trio.lowlevel.write_overlapped(self.handle, view)
            if not count:
                raise EOFError("ldnrs pipe closed while writing")
            view = view[count:]

    async def receive_some(self, count):
        data = bytearray(count)
        size = await trio.lowlevel.readinto_overlapped(self.handle, data)
        return bytes(data[:size])

    async def aclose(self):
        self.kernel.CloseHandle(self.handle)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()


class Connection:
    def __init__(self, stream, nursery):
        self.stream, self.nursery = stream, nursery
        self.sequence, self.pending = 0, {}
        self.out, self._out = trio.open_memory_channel(4096)
        self.events, self._events = trio.open_memory_channel(math.inf)
        self.network = None
        self.early_events, self.early_data = [], []

    async def exact(self, count):
        data = bytearray()
        while len(data) < count:
            chunk = await self.stream.receive_some(count - len(data))
            if not chunk:
                raise EOFError("ldnrs daemon disconnected")
            data.extend(chunk)
        return bytes(data)

    async def writer(self):
        async for frame in self._out:
            await self.stream.send_all(frame)

    async def reader(self):
        while True:
            op, sub, request, length = HEADER.unpack(await self.exact(HEADER.size))
            if length > MAX_BODY:
                raise ValueError("ldnd frame exceeds 256 KiB")
            body = await self.exact(length)
            if op == 0x80:
                waiter = self.pending.get(request)
                if waiter is None:
                    raise ValueError("ldnd replied to an unknown request")
                waiter[1].append(body)
                waiter[0].set()
            elif op == 0x82:
                r = Reader(body)
                handle = r.num("I")
                if self.network is not None and handle == self.network.channel:
                    await self.network.port.write(r.take(len(body) - r.offset))
                elif len(self.early_data) < 256:
                    self.early_data.append(body)
                else:
                    raise ValueError("ldnd sent too many frames before opening its raw channel")
            elif op == 0x81:
                self.event(Reader(body))
            else:
                raise ValueError(f"Unexpected ldnd opcode {op:#x}")

    def event(self, r):
        kind = r.num("B")
        if self.network is None and kind in (3, 4, 5):
            if len(self.early_events) >= 256:
                raise ValueError("ldnd sent too many events before opening its network")
            self.early_events.append(r.data)
            return
        if kind in (3, 4):
            handle, index, p = r.num("I"), r.num("B"), participant(r)
            if self.network is not None and handle == self.network.handle:
                parts = self.network.info().participants
                if index >= len(parts):
                    raise ValueError("Invalid ldnd participant index")
                parts[index] = p
                if kind == 3:
                    self.network.port.stack.add_neighbor(p.ip_address, p.mac_address)
                else:
                    parts[index].connected = False
                event = (JoinEvent if kind == 3 else LeaveEvent)(index, p)
                self.events.send_nowait(event)
        elif kind == 5:
            handle, reason = r.num("I"), r.num("B")
            if self.network is not None and handle == self.network.handle:
                self.events.send_nowait(DisconnectEvent(reason))
        elif kind == 8:
            handle, status, message = r.num("I"), r.num("B"), r.text()
            raise ConnectionError(f"ldnrs channel {handle} failed ({status}): {message}")
        elif kind == 10:
            state, message = r.num("B"), r.option(r.text)
            if state in (3, 4):
                raise ConnectionError(message or "ldnrs USB adapter disconnected")

    async def request(self, sub, body=b"", *, op=0x10):
        self.sequence += 1
        sequence = self.sequence
        event, result = trio.Event(), []
        self.pending[sequence] = event, result
        try:
            await self.send(op, sub, sequence, body)
            await event.wait()
            r = Reader(result[0])
            status, message = r.num("B"), r.option(r.text)
            if status:
                raise DaemonError(sub, status, message)
            return r
        finally:
            self.pending.pop(sequence, None)

    async def send(self, op, sub, request, body):
        if len(body) > MAX_BODY:
            raise ValueError("ldnd request exceeds 256 KiB")
        await self.out.send(HEADER.pack(op, sub, request, len(body)) + body)

    def later(self, sub, body):
        self.nursery.start_soon(self.request, sub, body)


@contextlib.asynccontextmanager
async def connection(keys):
    spec = os.environ.get("POKELDN_RADIO", "").partition(":")[2]
    stream = await Pipe.open(spec or DEFAULT_PIPE)
    async with stream:
        async with trio.open_nursery() as nursery:
            conn = Connection(stream, nursery)
            nursery.start_soon(conn.reader)
            nursery.start_soon(conn.writer)
            try:
                with trio.fail_after(10):
                    hello = await conn.request(0, number("I", 7) + b"\0" + text("pokeldn") + text("1"), op=1)
                    version = hello.num("I")
                    hello.text()
                    hello.num("B")
                    hello.num("B")
                    ready = hello.num("B")
                    hello.end()
                    if version != 7:
                        raise RuntimeError(f"ldnrs protocol {version} is unsupported; protocol 7 required")
                    if not ready:
                        raise RuntimeError("ldnrs adapter is not ready. Complete its adapter wizard first.")
                    if keys:
                        key_text = "\n".join(f"{name} = {value.hex()}" for name, value in keys.items())
                        await conn.request(0x60, text(key_text))
                yield conn
            finally:
                nursery.cancel_scope.cancel()


async def scan(keys=None, *, channels=None, dwell_time=None, protocols=None, **unused):
    async with connection(keys) as conn:
        body = (blob(bytes(channels or [])) + optional(None if dwell_time is None else int(dwell_time * 1000),
                                                     lambda n: number("I", n))
                + blob(bytes(protocols or [])) + b"\0")
        with trio.fail_after(30):
            r = await conn.request(0x20, body)
        networks = [network_info(r) for _ in range(r.num("I"))]
        r.end()
        return networks


class Network:
    def __init__(self, conn, reply):
        self.conn, self.handle = conn, reply.num("I")
        reply.option(lambda: reply.num("B"))
        self._info = reply.option(lambda: network_info(reply))
        self.index = reply.option(lambda: reply.num("B"))
        reply.end()
        if not self.handle or self._info is None or self.index is None:
            raise ValueError("ldnd returned an incomplete network")
        self.channel, self.port = None, None

    def info(self):
        return self._info

    def participant(self):
        return self._info.participants[self.index]

    def broadcast_address(self):
        return self.participant().ip_address.rsplit(".", 1)[0] + ".255"

    async def next_event(self):
        return await self.conn._events.receive()

    def set_application_data(self, data):
        self.conn.later(0x40, number("I", self.handle) + blob(bytes(data)))

    def set_accept_policy(self, policy):
        self.conn.later(0x41, number("I", self.handle) + number("B", policy))

    async def kick(self, index):
        await self.conn.request(0x43, number("I", self.handle) + number("B", index))

    async def transmit(self):
        while True:
            frame = await self.port.read()
            await self.conn.send(0x82, 0, 0, number("I", self.channel) + frame)


@contextlib.asynccontextmanager
async def _network(param, sub, body, ifname):
    async with connection(param.keys) as conn:
        with trio.fail_after(JOIN_SECONDS + 10):
            net = Network(conn, await conn.request(sub, body))
        async with userspace_ip.userspace_port(ifname, net.participant().mac_address) as port:
            net.port = port
            await port.add_address(net.participant().ip_address, net.broadcast_address())
            for p in net.info().participants:
                if p.connected:
                    await port.add_neighbor(p.ip_address, p.mac_address)
            conn.network = net
            for event in conn.early_events:
                conn.event(Reader(event))
            conn.early_events.clear()
            r = await conn.request(0x51, number("I", net.handle))
            net.channel = r.num("I")
            r.end()
            if not net.channel:
                raise ValueError("ldnd returned an invalid raw channel")
            for data in conn.early_data:
                r = Reader(data)
                if r.num("I") == net.channel:
                    await port.write(r.take(len(data) - r.offset))
            conn.early_data.clear()
            conn.nursery.start_soon(net.transmit)
            try:
                yield net
            finally:
                with trio.CancelScope(shield=True), trio.move_on_after(3):
                    for operation, handle in ((0x52, net.channel), (0x32, net.handle)):
                        try:
                            await conn.request(operation, number("I", handle))
                        except DaemonError as error:
                            if error.status != 3:  # a remotely closed handle is already released
                                raise


def connect(param):
    if param.network is None:
        raise ValueError("An ldnrs scan result is required")
    body = (param.network.raw + blob(param.password) + blob(param.name) + number("H", param.app_version)
            + number("B", param.platform) + number("B", param.enable_challenge) + number("Q", param.device_id)
            + optional(param.client_random, bytes) + number("B", param.dev)
            + b"\1" + number("I", JOIN_SECONDS * 1000))
    return _network(param, 0x30, body, param.ifname)


def create_network(param):
    body = (number("Q", param.local_communication_id) + number("H", param.scene_id)
            + optional(param.max_participants, lambda n: number("B", n)) + blob(param.application_data)
            + optional(param.accept_policy, lambda n: number("B", n)) + number("I", len(param.accept_filter))
            + b"".join(bytes(a) for a in param.accept_filter)
            + optional(param.security_mode, lambda n: number("H", n)) + optional(param.ssid, bytes)
            + blob(param.name) + number("H", param.app_version) + number("B", param.platform)
            + optional(param.channel, lambda n: number("B", n)) + optional(param.server_random, bytes)
            + blob(param.password) + optional(param.version, lambda n: number("B", n))
            + number("B", param.enable_challenge) + number("Q", param.device_id)
            + optional(param.protocol, lambda n: number("B", n)) + number("B", param.dev))
    return _network(param, 0x31, body, param.ifname_tap)

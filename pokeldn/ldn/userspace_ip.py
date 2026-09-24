"""IPv4, UDP and ARP in the host process, for a radio whose L2 port has no kernel interface behind
it (the ESP32 board on macOS). The launchers' sockets bound to an interface name become the
objects here: `udp_socket` stands in for a UDP socket and `packet_socket` for an AF_PACKET one.
Both have a real file descriptor, so `select` and `trio.lowlevel.wait_readable` work on them.

A stack is registered under its interface name when the radio's port is created, and removed
with it. `lookup(name)` answers None when the interface is a kernel one.
"""

import collections
import contextlib
import errno
import math
import os
import socket
import struct
import threading
import time

import trio

ETH_P_IP = 0x0800
ETH_P_ARP = 0x0806
PROTO_UDP = 17
BROADCAST_MAC = b"\xff" * 6
MTU = 1500
_REASSEMBLY_TIMEOUT = 5.0

_stacks: dict[str, "Stack"] = {}
_stacks_lock = threading.Lock()


def lookup(name: str) -> "Stack | None":
    with _stacks_lock:
        return _stacks.get(name)


def any_stack() -> "Stack | None":
    """The only registered stack, for callers that do not know the interface name."""
    with _stacks_lock:
        return next(iter(_stacks.values())) if len(_stacks) == 1 else None


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _mac(value) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return bytes.fromhex(value.replace(":", ""))
    return bytes.fromhex(str(value).replace(":", ""))


def build_udp(src_ip: str, dst_ip: str, src_port: int, dst_port: int, payload: bytes,
              ident: int = 0) -> list[bytes]:
    """-> the IPv4 packets carrying one datagram, fragmented at the MTU."""
    src, dst = socket.inet_aton(src_ip), socket.inet_aton(dst_ip)
    udp_len = 8 + len(payload)
    pseudo = src + dst + struct.pack("!BBH", 0, PROTO_UDP, udp_len)
    udp = struct.pack("!HHHH", src_port, dst_port, udp_len, 0) + payload
    udp_sum = checksum(pseudo + udp) or 0xFFFF
    udp = udp[:6] + struct.pack("!H", udp_sum) + udp[8:]
    step = (MTU - 20) & ~7
    packets = []
    for offset in range(0, len(udp), step):
        chunk = udp[offset:offset + step]
        more = offset + step < len(udp)
        flags = (0x2000 if more else 0) | (offset // 8)
        header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(chunk), ident & 0xFFFF, flags,
                             64, PROTO_UDP, 0, src, dst)
        header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
        packets.append(header + chunk)
    return packets


class _Readable:
    """A queue with a pipe beside it: one byte per queued item, so the read end is selectable."""

    def __init__(self):
        self._queue = collections.deque()
        # The pipe byte and the queued item change together under this lock: the radio's thread
        # pushes while the reader pops, and a byte seen before its item made popleft raise.
        self._lock = threading.Lock()
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)
        os.set_blocking(self._w, False)
        self._timeout = None
        self.closed = False
        self.dropped = 0

    def fileno(self) -> int:
        return self._r

    def _push(self, item) -> None:
        with self._lock:
            if self.closed:
                return
            self._queue.append(item)
            try:
                os.write(self._w, b"\x00")
            except BlockingIOError:
                self._queue.pop()
                self.dropped += 1

    def _pop(self):
        while True:
            with self._lock:
                try:
                    os.read(self._r, 1)
                    return self._queue.popleft()
                except BlockingIOError:
                    pass
            if self._timeout == 0:
                raise BlockingIOError(errno.EAGAIN, "no datagram queued")
            import select
            ready = select.select([self._r], [], [], self._timeout)[0]
            if not ready:
                raise socket.timeout("timed out")

    def setblocking(self, flag: bool) -> None:
        self._timeout = None if flag else 0

    def settimeout(self, value) -> None:
        self._timeout = value

    def gettimeout(self):
        return self._timeout

    def setsockopt(self, *args) -> None:
        pass

    def getsockopt(self, level, option, *args):
        return 8 * 1024 * 1024 if option == socket.SO_RCVBUF else 0

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._detach()
        for fd in (self._r, self._w):
            with contextlib.suppress(OSError):
                os.close(fd)

    def _detach(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class UdpSocket(_Readable):
    def __init__(self, stack: "Stack", port: int):
        super().__init__()
        self.stack = stack
        self.port = port

    def _detach(self) -> None:
        self.stack._unbind(self)

    def bind(self, address) -> None:
        pass

    def getsockname(self):
        return (self.stack.ip or "0.0.0.0", self.port)

    def recvfrom(self, bufsize: int = 65535):
        payload, source = self._pop()
        return payload[:bufsize], source

    def recv(self, bufsize: int = 65535) -> bytes:
        return self.recvfrom(bufsize)[0]

    def sendto(self, data: bytes, address) -> int:
        self.stack.send_udp(bytes(data), address[0], address[1], self.port)
        return len(data)


class PacketSocket(_Readable):
    """Every IPv4 Ethernet frame the radio delivers, whole, as AF_PACKET gives them."""

    def __init__(self, stack: "Stack"):
        super().__init__()
        self.stack = stack

    def _detach(self) -> None:
        self.stack._unbind(self)

    def bind(self, address) -> None:
        pass

    def recv(self, bufsize: int = 65535) -> bytes:
        return self._pop()[:bufsize]


class Stack:
    """One interface's addresses, neighbours and sockets. `deliver` takes a frame from the radio;
    `transmit(frame)` is how a frame leaves."""

    def __init__(self, name: str, mac, transmit):
        self.name = name
        self.mac = _mac(mac)
        self.ip: str | None = None
        self.broadcast: str | None = None
        self.neighbors: dict[str, bytes] = {}
        self.learned: dict[str, bytes] = {}
        self._transmit = transmit
        self._lock = threading.Lock()
        self._udp: dict[int, list[UdpSocket]] = {}
        self._packet: list[PacketSocket] = []
        self._fragments: dict[tuple, tuple[float, dict[int, bytes], int | None]] = {}
        self._ident = 0
        self.counters = collections.Counter()

    # addresses
    def set_address(self, local: str, broadcast: str) -> None:
        self.ip, self.broadcast = local, broadcast

    def add_neighbor(self, ip: str, mac) -> None:
        self.neighbors[ip] = _mac(mac)

    def remove_neighbor(self, ip: str) -> None:
        self.neighbors.pop(ip, None)

    # sockets
    def udp_socket(self, port: int, receive: bool = True) -> UdpSocket:
        """`receive=False` makes a send-only socket that queues nothing."""
        sock = UdpSocket(self, port)
        if receive:
            with self._lock:
                self._udp.setdefault(port, []).append(sock)
        return sock

    def packet_socket(self) -> PacketSocket:
        sock = PacketSocket(self)
        with self._lock:
            self._packet.append(sock)
        return sock

    def _unbind(self, sock) -> None:
        with self._lock:
            if isinstance(sock, PacketSocket):
                with contextlib.suppress(ValueError):
                    self._packet.remove(sock)
            else:
                with contextlib.suppress(ValueError):
                    self._udp.get(sock.port, []).remove(sock)

    # out
    def _resolve(self, ip: str) -> bytes | None:
        if ip == "255.255.255.255" or ip == self.broadcast or ip.endswith(".255"):
            return BROADCAST_MAC
        return self.neighbors.get(ip) or self.learned.get(ip)

    def send_udp(self, payload: bytes, dst_ip: str, dst_port: int, src_port: int) -> None:
        if self.ip is None:
            raise OSError("the interface has no address yet")
        target = self._resolve(dst_ip)
        if target is None:
            self.counters["unresolved"] += 1
            self._send_arp(1, BROADCAST_MAC, b"\x00" * 6, dst_ip)
            return
        with self._lock:
            self._ident = (self._ident + 1) & 0xFFFF
            ident = self._ident
        for packet in build_udp(self.ip, dst_ip, src_port, dst_port, payload, ident):
            self._transmit(target + self.mac + struct.pack("!H", ETH_P_IP) + packet)
        self.counters["udp_out"] += 1

    def _send_arp(self, op: int, eth_target: bytes, hw_target: bytes, ip_target: str) -> None:
        if self.ip is None:
            return
        arp = struct.pack("!HHBBH6s4s6s4s", 1, ETH_P_IP, 6, 4, op, self.mac,
                          socket.inet_aton(self.ip), hw_target, socket.inet_aton(ip_target))
        self._transmit(eth_target + self.mac + struct.pack("!H", ETH_P_ARP) + arp)

    # in
    def deliver(self, frame: bytes) -> None:
        if len(frame) < 14:
            return
        target, protocol = frame[:6], struct.unpack_from("!H", frame, 12)[0]
        if target not in (self.mac, BROADCAST_MAC) and not target[0] & 1:
            self.counters["not_ours"] += 1
            return
        if protocol == ETH_P_ARP:
            self._on_arp(frame[14:])
        elif protocol == ETH_P_IP:
            self._on_ip(frame)

    def _on_arp(self, arp: bytes) -> None:
        if len(arp) < 28:
            return
        op, sender_mac, sender_ip, _, target_ip = struct.unpack_from("!6xH6s4s6s4s", arp)
        sender = socket.inet_ntoa(sender_ip)
        if sender != "0.0.0.0":
            self.learned[sender] = sender_mac
        if op == 1 and self.ip is not None and socket.inet_ntoa(target_ip) == self.ip:
            self._send_arp(2, sender_mac, sender_mac, sender)
            self.counters["arp_replies"] += 1

    def _on_ip(self, frame: bytes) -> None:
        ip = frame[14:]
        if len(ip) < 20 or ip[0] >> 4 != 4:
            return
        ihl = (ip[0] & 0x0F) * 4
        total = struct.unpack_from("!H", ip, 2)[0]
        ip = ip[:total]
        src = socket.inet_ntoa(ip[12:16])
        if src != "0.0.0.0" and frame[6:12] != self.mac:
            self.learned.setdefault(src, frame[6:12])
        with self._lock:
            packet_sockets = list(self._packet)
        flags = struct.unpack_from("!H", ip, 6)[0]
        if flags & 0x3FFF:
            ip = self._reassemble(ip, ihl, flags)
            if ip is None:
                return
            ihl = 20
            frame = frame[:14] + ip
        for sock in packet_sockets:
            sock._push(frame)
        if ip[9] != PROTO_UDP or len(ip) < ihl + 8:
            return
        dst = socket.inet_ntoa(ip[16:20])
        if self.ip is not None and dst not in (self.ip, self.broadcast, "255.255.255.255") \
                and not dst.endswith(".255"):
            return
        src_port, dst_port, udp_len = struct.unpack_from("!HHH", ip, ihl)
        payload = ip[ihl + 8:ihl + max(udp_len, 8)]
        with self._lock:
            sockets = list(self._udp.get(dst_port, ()))
        for sock in sockets:
            sock._push((payload, (src, src_port)))
        self.counters["udp_in"] += 1

    def _reassemble(self, ip: bytes, ihl: int, flags: int) -> bytes | None:
        key = (ip[12:16], ip[16:20], ip[4:6], ip[9])
        now = time.monotonic()
        for stale in [k for k, v in self._fragments.items() if now - v[0] > _REASSEMBLY_TIMEOUT]:
            del self._fragments[stale]
        started, parts, end = self._fragments.get(key, (now, {}, None))
        offset = (flags & 0x1FFF) * 8
        parts[offset] = ip[ihl:]
        if not flags & 0x2000:
            end = offset + len(ip) - ihl
        self._fragments[key] = (started, parts, end)
        if end is None:
            return None
        data, cursor = bytearray(), 0
        for off in sorted(parts):
            if off != cursor:
                return None
            data += parts[off]
            cursor += len(parts[off])
        if cursor != end:
            return None
        del self._fragments[key]
        header = bytearray(ip[:20])
        header[0] = 0x45
        struct.pack_into("!HH", header, 2, 20 + len(data), 0)
        return bytes(header) + bytes(data)


class UserspacePort:
    """The `esp32_wlan` L2 port backed by a `Stack`: frames from the radio go into the stack,
    frames the stack sends come out of `read()`."""

    def __init__(self, name: str, address):
        self._name = name
        self._address = address
        self._token = trio.lowlevel.current_trio_token()
        self._out_send, self._out_recv = trio.open_memory_channel(math.inf)
        self.stack = Stack(name, _mac(address), self._queue_out)

    def _queue_out(self, frame: bytes) -> None:
        try:
            self._token.run_sync_soon(self._out_send.send_nowait, frame)
        except (trio.RunFinishedError, trio.ClosedResourceError):
            pass

    def name(self) -> str:
        return self._name

    def index(self) -> int:
        return 0

    def address(self):
        return self._address

    async def up(self) -> None:
        pass

    def disable_ipv6(self) -> None:
        pass

    async def update_link(self, address) -> None:
        self._address = address
        self.stack.mac = _mac(address)

    async def add_address(self, local: str, broadcast: str, prefix: int = 24) -> None:
        self.stack.set_address(local, broadcast)

    async def add_neighbor(self, ipaddr: str, macaddr) -> None:
        self.stack.add_neighbor(ipaddr, macaddr)

    async def remove_neighbor(self, ipaddr: str, macaddr) -> None:
        self.stack.remove_neighbor(ipaddr)

    async def write(self, frame: bytes) -> None:
        self.stack.deliver(frame)

    async def read(self) -> bytes:
        return await self._out_recv.receive()


@contextlib.asynccontextmanager
async def userspace_port(name: str, address):
    port = UserspacePort(name, address)
    with _stacks_lock:
        _stacks[name] = port.stack
    try:
        yield port
    finally:
        with _stacks_lock:
            if _stacks.get(name) is port.stack:
                del _stacks[name]


def udp_socket(ifname: str, port: int) -> UdpSocket | None:
    """A userspace UDP socket on `ifname` if a stack owns it, else None."""
    stack = lookup(ifname)
    return None if stack is None else stack.udp_socket(port)


def packet_socket(ifname: str) -> PacketSocket | None:
    stack = lookup(ifname)
    return None if stack is None else stack.packet_socket()

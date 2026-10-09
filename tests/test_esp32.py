"""The ESP32 radio's host side: its framing, and the unchanged LDN library running on it, host and
station, across two simulated boards."""

import contextlib
import contextvars
import os
import struct
import threading
import time

import pytest
import trio

import ldn
from ldn import wlan

from pokeldn.ldn import esp32, esp32_sim, esp32_wlan


def test_cobs_round_trip():
    for n in (0, 1, 253, 254, 255, 256, 509, 1600):
        for data in (bytes(n), os.urandom(n), b"\x01" * n):
            encoded = esp32.cobs_encode(data)
            assert 0 not in encoded
            assert esp32.cobs_decode(encoded) == data


def test_reader_resynchronises_after_boot_text():
    frame = esp32.encode_frame(esp32.MSG_RX_ETH, b"\x00abc\x00")
    reader = esp32.FrameReader()
    corrupt = bytearray(frame)
    corrupt[2] ^= 0x40
    frames = list(reader.feed(b"ets Jun  8 2016 rst:0x1\r\n\x00" + bytes(corrupt) + frame))
    assert frames == [(esp32.MSG_RX_ETH, b"\x00abc\x00")]
    assert reader.rejected == 2


class _RingBoard:
    """The firmware's receive side as measured: a 16 KB ring, a CREDIT per 1024 bytes; 1500000 baud
    lost 429 of 5000 ETH_TX."""

    RING, RATE = 16384, 2_000_000   # bytes, bytes per second the handler takes

    def __init__(self, losses=(), holds=()):
        import threading
        self.losses = sorted(losses)    # (at byte N received, lose the next M bytes)
        self.holds = sorted(holds)      # (at byte N read, the reader stops for S seconds)
        self.credit_at = 0.0
        self.overflowed = 0
        self.received = self.losing = self.lost = 0
        self.ring = bytearray()
        self.lock = threading.Lock()
        self.inbox = []
        self.reader = esp32.FrameReader()
        self.frames = self.consumed = self.credited = 0
        self.closed = False
        self.thread = threading.Thread(target=self._handle, daemon=True)
        self.thread.start()

    def write(self, data):
        with self.lock:
            self.received += len(data)
            if self.losses and self.received >= self.losses[0][0]:
                self.losing += self.losses.pop(0)[1]
            if self.losing > 0:
                self.losing -= len(data)
                self.lost += len(data)
                return
            room = max(0, self.RING - len(self.ring))
            self.overflowed += max(0, len(data) - room)
            self.ring += data[:room]

    def read(self, n):
        time.sleep(0.001)
        with self.lock:
            out, self.inbox = b"".join(self.inbox), []
        return out

    def close(self):
        self.closed = True

    def _handle(self):
        while not self.closed:
            time.sleep(0.002)
            if self.holds and self.consumed >= self.holds[0][0]:
                time.sleep(self.holds.pop(0)[1])
            with self.lock:
                take, self.ring = bytes(self.ring[:int(self.RATE * 0.002)]), self.ring[int(self.RATE * 0.002):]
            for b in take:
                self.consumed += 1
                for msg_type, _ in self.reader.feed(bytes([b])):
                    if msg_type == esp32.CMD_HELLO:
                        self.consumed = 0
                        with self.lock:
                            self.inbox.append(esp32.encode_frame(esp32.MSG_CREDIT, bytes(4)))
                    elif msg_type == esp32.CMD_ETH_TX:
                        self.frames += 1
                    elif msg_type == esp32.CMD_STATUS:
                        with self.lock:
                            self.inbox.append(esp32.encode_frame(
                                esp32.MSG_STATUS, f"mode=3 tx_eth={self.frames} tx_eth_failed=0".encode()))
            if take or time.monotonic() - self.credit_at > 0.1:    # idle, it repeats its count
                self.credit_at = time.monotonic()
                with self.lock:
                    self.inbox.append(esp32.encode_frame(esp32.MSG_CREDIT,
                                                         struct.pack("<I", self.consumed)))


def test_a_flood_of_eth_tx_never_overflows_the_boards_ring():
    """2000 ETH_TX at once, as a Scarlet seat opens, all reach the handler under the CREDIT window."""
    board = _RingBoard()
    radio = esp32.Radio(board)
    try:
        radio.send(esp32.CMD_HELLO)
        time.sleep(0.1)
        frame = b"\xff" * 6 + bytes(6) + b"\x08\x00" + bytes(range(200))
        for i in range(2000):
            radio.send_ethernet(frame)
            if i % 200 == 199:                      # a caller that keeps within the host's queue
                radio.drain(30)
        radio.drain(30)
        deadline = time.monotonic() + 5
        while board.frames < 2000 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        radio.close()
        board.close()
    assert board.frames == 2000
    assert (radio.tx_dropped, radio.flow_resyncs) == (0, 0)


def test_bytes_lost_on_the_line_close_the_window_once_each():
    """9 KB lost in three pieces shuts the window once; one resync writes it off."""
    board = _RingBoard(losses=[(100_000, 3000), (200_000, 3000), (300_000, 3000)])
    radio = esp32.Radio(board)
    try:
        radio.send(esp32.CMD_HELLO)
        time.sleep(0.1)
        frame = b"\xff" * 6 + bytes(6) + b"\x08\x00" + bytes(range(200))
        for i in range(2000):
            radio.send_ethernet(frame)
            if i % 200 == 199:
                assert radio.drain(10)
        assert radio.drain(10)
        while board.ring:
            time.sleep(0.01)
    finally:
        radio.close()
        board.close()
    assert (radio.flow_resyncs, radio.tx_dropped) == (1, 0)
    assert board.frames >= 2000 - 3 * (3000 // len(frame) + 2)


def test_a_trace_reconciles_the_commands_and_bytes_the_line_lost(tmp_path, monkeypatch):
    """tools/ldn/esp32_cmd_loss.py names the commands and bytes the board never read."""
    import esp32_cmd_loss
    trace = tmp_path / "loss_esp32.trace"
    monkeypatch.setenv("POKELDN_ESP32_TRACE", str(trace))
    board = _RingBoard(losses=[(50_000, 3000)])
    radio = esp32.Radio(board)
    try:
        radio.send(esp32.CMD_HELLO)
        time.sleep(0.1)
        frame = b"\xff" * 6 + bytes(6) + b"\x08\x00" + bytes(range(200))
        for i in range(600):
            radio.send_ethernet(frame)
            if i == 299:
                radio.send(esp32.CMD_STATUS)    # one STATUS mid-flood, the reply counts in order
            if i % 200 == 199:
                assert radio.drain(10)
        radio.send(esp32.CMD_STATUS)
        assert radio.drain(10)
        deadline = time.monotonic() + 5
        while (board.ring or radio._credited + 3000 > radio._written) and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
    finally:
        radio.close()
        board.close()
    rows, resyncs, _, written, credit = esp32_cmd_loss.read(str(trace), False)
    lost = [sent - counted for _, sent, counted, _ in rows]
    assert 600 - board.frames > 0
    assert lost == [lost[0], 600 - board.frames] and 0 < lost[0] <= lost[1]
    assert (resyncs, written - credit) == (0, board.lost)


def test_a_reader_held_silent_is_waited_for_not_overrun():
    """A reader silent for 1.2 s with the window full is waited for, not resynced."""
    board = _RingBoard(holds=[(60_000, 1.2)])
    radio = esp32.Radio(board)
    try:
        radio.send(esp32.CMD_HELLO)
        time.sleep(0.1)
        frame = b"\xff" * 6 + bytes(6) + b"\x08\x00" + bytes(range(200))
        for i in range(600):
            radio.send_ethernet(frame)
            if i % 200 == 199:
                assert radio.drain(10)
        assert radio.drain(10)
        while board.ring:
            time.sleep(0.01)
    finally:
        radio.close()
        board.close()
    assert (board.overflowed, radio.flow_resyncs, board.frames) == (0, 0, 600)


def test_a_hello_mid_session_does_not_open_the_window():
    """A HELLO sent with ETH_TX queued behind it, to a reader held as it arrives, overran the 16 KB
    ring by 76423 bytes when the host dropped flow control until the board's CREDIT 0."""
    frame = b"\xff" * 6 + bytes(6) + b"\x08\x00" + bytes(range(200))
    length = len(esp32.encode_frame(esp32.CMD_ETH_TX, frame))
    board = _RingBoard(holds=[(400 * length - 50, 0.5)])
    radio = esp32.Radio(board)
    try:
        radio.send(esp32.CMD_HELLO)
        time.sleep(0.1)
        for i in range(400):
            radio.send_ethernet(frame)
            if i % 200 == 199:
                assert radio.drain(30)
        radio.send(esp32.CMD_HELLO)
        for _ in range(400):
            radio.send_ethernet(frame)
        assert radio.drain(30)
        deadline = time.monotonic() + 10
        while board.ring and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.3)
    finally:
        radio.close()
        board.close()
    assert (board.overflowed, board.frames) == (0, 800)


def test_radio_commands_against_the_simulated_board():
    board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    radio = esp32.Radio(board.host_stream())
    try:
        info = radio.hello()
        assert info.version == esp32.PROTOCOL_VERSION and info.sta_mac == board.sta_mac
        radio.set_channel(11)
        assert board.channel == 11
        with pytest.raises(esp32.RadioError):
            radio.kick(b"\x02" * 6)
    finally:
        radio.close()


KEYS = {name: os.urandom(16) for name in (
    "aes_kek_generation_source", "aes_key_generation_source", "master_key_00", "master_key_12")}

_radio = contextvars.ContextVar("radio")


@contextlib.contextmanager
def _two_boards(refuse_joins=0):
    air = esp32_sim.Air()
    host_board, station_board = esp32_sim.SimulatedBoard(air), esp32_sim.SimulatedBoard(air)
    station_board.refuse_joins = refuse_joins
    radios = esp32.Radio(host_board.host_stream()), esp32.Radio(station_board.host_stream())
    ports = {}

    @contextlib.asynccontextmanager
    async def port_factory(name, address):
        port = esp32_wlan.MemoryPort(name, address)
        ports[name] = port
        yield port

    @contextlib.asynccontextmanager
    async def factory():
        esp = esp32_wlan.EspFactory(_radio.get(), port_factory=port_factory, join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    wlan.set_factory(factory)
    try:
        yield radios, ports, host_board
    finally:
        wlan.set_factory(None)
        for radio in radios:
            radio.close()


@pytest.mark.parametrize("console_scene, found", [(2321, 11), (2341, None)])
def test_the_lets_go_host_finds_the_channel_a_console_searches_on(console_scene, found):
    """`--channel auto` for code 2321 finds a console on channel 11; another code is not found."""
    import lgpe_host
    from pokeldn.lgpe import COMM_ID_PIKACHU

    async def main():
        with _two_boards() as ((console_radio, host_radio), ports, console_board):
            up = trio.Event()
            result = []

            async def console():
                _radio.set(console_radio)
                param = ldn.CreateNetworkParam(
                    keys=KEYS, channel=11, local_communication_id=COMM_ID_PIKACHU,
                    scene_id=console_scene, name=b"POKELDN", app_version=0)
                async with ldn.create_network(param):
                    up.set()
                    while not result:
                        await trio.sleep(0.05)

            async def host():
                _radio.set(host_radio)
                await up.wait()
                result.append(await lgpe_host.find_console_channel(KEYS, None, 2321, seconds=2))

            with trio.fail_after(20):
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(console)
                    nursery.start_soon(host)
            assert result == [found]

    trio.run(main)


def _udp_frame(target: bytes, source: bytes, payload: bytes) -> bytes:
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 28 + len(payload), 0, 0, 64, 17, 0,
                     bytes([169, 254, 1, 2]), bytes([169, 254, 1, 1]))
    return target + source + b"\x08\x00" + ip + struct.pack(">HHHH", 12345, 12345, 8 + len(payload), 0) + payload


# A retail Sword's network refused a board's join with 0xc9 or 0x2 while still advertising; the
# next STA_JOIN was taken (docs/hardware_esp32.md, Joining).
@pytest.mark.parametrize("refused", [0, 2])
def test_ldn_host_and_station_run_on_simulated_boards(refused):
    async def main():
        with _two_boards(refused) as ((host_radio, station_radio), ports, host_board):
            host_up = trio.Event()
            joined = []
            received = []

            async def host():
                _radio.set(host_radio)
                param = ldn.CreateNetworkParam(
                    keys=KEYS, channel=6, local_communication_id=0x0100ABCD00000000,
                    name=b"POKELDN", app_version=1, application_data=b"esp32 test")
                async with ldn.create_network(param) as network:
                    host_up.set()
                    event = await network.next_event()
                    joined.append(event)
                    received.append(await ports["ldn-tap"].received())
                    await trio.sleep(0.3)

            async def station():
                _radio.set(station_radio)
                await host_up.wait()
                networks = await ldn.scan(KEYS, channels=[6], dwell_time=0.5)
                assert len(networks) == 1
                network = networks[0]
                assert network.application_data == b"esp32 test"
                param = ldn.ConnectNetworkParam(network=network, keys=KEYS, name=b"Board", app_version=1)
                async with ldn.connect(param) as sta:
                    port = ports["ldn"]
                    assert port.addresses == [(sta.participant().ip_address, sta.broadcast_address())]
                    host_mac = esp32.mac_bytes(network.address)
                    port.transmit(_udp_frame(host_mac, esp32.mac_bytes(sta.participant().mac_address),
                                             b"pia"))
                    with trio.fail_after(5):
                        while not received:
                            await trio.sleep(0.05)

            with trio.fail_after(20):
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(host)
                    nursery.start_soon(station)

            assert isinstance(joined[0], ldn.JoinEvent) and joined[0].participant.name == b"Board"
            assert received[0].endswith(b"pia")
            assert any(f[24:28] == b"\x7f\x00\x22\xaa" for f in host_board.sent_raw)

    trio.run(main)


def test_userspace_stack_carries_udp_both_ways_on_simulated_boards():
    """The macOS path: no TAP, the launchers' sockets are `userspace_ip` sockets on each port."""
    from pokeldn.ldn import userspace_ip

    air = esp32_sim.Air()
    boards = esp32_sim.SimulatedBoard(air), esp32_sim.SimulatedBoard(air)
    radios = tuple(esp32.Radio(b.host_stream()) for b in boards)

    @contextlib.asynccontextmanager
    async def factory():
        esp = esp32_wlan.EspFactory(_radio.get(), port_factory=userspace_ip.userspace_port,
                                    join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    got = {}

    async def main():
        host_up, done = trio.Event(), trio.Event()

        async def host():
            _radio.set(radios[0])
            param = ldn.CreateNetworkParam(
                keys=KEYS, channel=6, local_communication_id=0x0100ABCD00000000,
                name=b"POKELDN", app_version=1, application_data=b"esp32 test")
            async with ldn.create_network(param) as network:
                sock = userspace_ip.udp_socket("ldn-tap", 12345)
                raw = userspace_ip.packet_socket("ldn-tap")
                host_up.set()
                await network.next_event()
                await trio.lowlevel.wait_readable(sock)
                sock.setblocking(False)
                data, source = sock.recvfrom(4096)
                got["host"] = (data, source)
                got["raw"] = raw.recv(65535)
                sock.sendto(b"pong" * 600, source)
                await done.wait()
                sock.close()
                raw.close()

        async def station():
            _radio.set(radios[1])
            await host_up.wait()
            network = (await ldn.scan(KEYS, channels=[6], dwell_time=0.5))[0]
            param = ldn.ConnectNetworkParam(network=network, keys=KEYS, name=b"Board", app_version=1)
            async with ldn.connect(param) as sta:
                sock = userspace_ip.udp_socket("ldn", 12345)
                host_ip = sta.info().participants[0].ip_address
                sock.sendto(b"ping", (host_ip, 12345))
                with trio.fail_after(5):
                    await trio.lowlevel.wait_readable(sock)
                got["station"] = sock.recvfrom(4096)
                got["station_ip"] = sta.participant().ip_address
                done.set()
                sock.close()

        with trio.fail_after(20):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(host)
                nursery.start_soon(station)

    wlan.set_factory(factory)
    try:
        trio.run(main)
    finally:
        wlan.set_factory(None)
        for radio in radios:
            radio.close()

    data, (src_ip, src_port) = got["host"]
    assert data == b"ping" and src_ip == got["station_ip"] and src_port == 12345
    assert got["raw"][12:14] == b"\x08\x00" and got["raw"].endswith(b"ping")
    reply, (reply_ip, _) = got["station"]
    assert reply == b"pong" * 600 and reply_ip.endswith(".1")
    assert userspace_ip.lookup("ldn") is None and userspace_ip.lookup("ldn-tap") is None


def test_userspace_stack_answers_arp_and_reassembles():
    from pokeldn.ldn import userspace_ip

    sent = []
    stack = userspace_ip.Stack("x", b"\x02\x00\x00\x00\x00\x01", sent.append)
    stack.set_address("169.254.9.2", "169.254.9.255")
    peer = b"\x02\x00\x00\x00\x00\x02"
    arp = struct.pack("!HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 1, peer, bytes([169, 254, 9, 1]),
                      bytes(6), bytes([169, 254, 9, 2]))
    stack.deliver(b"\xff" * 6 + peer + b"\x08\x06" + arp)
    assert sent[-1][:6] == peer and sent[-1][14 + 7] == 2
    with stack.udp_socket(12345) as sock:
        sock.setblocking(False)
        for packet in userspace_ip.build_udp("169.254.9.1", "169.254.9.2", 12345, 12345, bytes(range(256)) * 12, 7):
            stack.deliver(stack.mac + peer + b"\x08\x00" + packet)
        assert sock.recvfrom(65535) == (bytes(range(256)) * 12, ("169.254.9.1", 12345))
        with pytest.raises(BlockingIOError):
            sock.recvfrom(65535)


def test_host_transport_uses_the_userspace_stack_that_owns_its_interface():
    from pokeldn.ldn import transport, userspace_ip

    sent = []
    stack = userspace_ip.Stack("ldn-tap", b"\x02\x00\x00\x00\x00\x01", sent.append)
    stack.set_address("169.254.9.1", "169.254.9.255")
    userspace_ip._stacks["ldn-tap"] = stack
    try:
        host = object.__new__(transport.HostTransport)
        host.iface, host.our_ip, host.broadcast = "ldn-tap", "169.254.9.1", "169.254.9.255"
        host.tracer, host.log, host._rx_seen = None, lambda *a: None, 0
        host._setup_sockets()
        console = b"\x02\x00\x00\x00\x00\x02"
        for packet in userspace_ip.build_udp("169.254.9.2", "169.254.9.1", 12345, 12345, b"pia-in"):
            stack.deliver(stack.mac + console + b"\x08\x00" + packet)
        assert host.wait_readable(0.2) is True
        assert host.recv() == [(b"pia-in", "169.254.9.2")]
        assert stack.neighbors["169.254.9.2"] == console
        host.send(b"pia-out", "169.254.9.2")
        assert sent[-1][:6] == console and sent[-1].endswith(b"pia-out")
        host.send(b"bcast", "169.254.9.255")
        assert sent[-1][:6] == b"\xff" * 6
    finally:
        host._tx.close()
        host._rx.close()
        userspace_ip._stacks.pop("ldn-tap", None)


def test_first_contact_sees_and_decodes_a_simulated_host():
    import threading

    import esp32_first_contact

    air = esp32_sim.Air()
    host_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    probe_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    up, done = threading.Event(), threading.Event()

    @contextlib.asynccontextmanager
    async def host_factory():
        esp = esp32_wlan.EspFactory(host_radio, port_factory=esp32_wlan.memory_port)
        try:
            yield esp
        finally:
            esp.router.close()

    def host():
        async def run():
            param = ldn.CreateNetworkParam(
                keys=KEYS, channel=6, local_communication_id=0x0100ABCD00000000,
                name=b"POKELDN", app_version=1, application_data=b"first contact")
            async with ldn.create_network(param):
                up.set()
                await trio.to_thread.run_sync(done.wait)
        trio.run(run)

    wlan.set_factory(host_factory)
    thread = threading.Thread(target=host, daemon=True)
    thread.start()
    try:
        assert up.wait(10)
        lines = []
        result = esp32_first_contact.first_contact(probe_radio, (1, 6), 0.4, KEYS, lines.append)
    finally:
        done.set()
        thread.join(5)
        wlan.set_factory(None)
        host_radio.close()
        probe_radio.close()
    assert sum(result["seen"][6].values()) > 0 and not result["seen"][1]
    assert [n.application_data for n in result["networks"]] == [b"first contact"]
    assert lines[0].startswith("[hello] protocol 1")


def test_station_broadcast_with_no_ds_bits_reaches_the_ldn_data_path():
    """A console's no-DS-bit group-key broadcasts reach the LDN library still protected
    (docs/hardware_esp32.md)."""
    key = os.urandom(16)
    bssid, station = wlan.MACAddress("1a:ff:86:ca:35:1f"), wlan.MACAddress("48:f1:eb:20:9b:22")
    arp = wlan.SNAPHeader()
    arp.protocol, arp.payload = 0x0806, os.urandom(28)

    def frame(tods, target):
        data = wlan.DataFrame()
        data.target, data.source, data.bssid, data.tods = target, station, bssid, tods
        data.payload = arp.encode()
        data.encrypt(key, 61647690794114, 0 if tods else 1)
        return data.encode()

    class StubRadio:
        def subscribe(self, callback):
            self.callback = callback

    async def main():
        radio = StubRadio()
        router = esp32_wlan._Router(radio)
        monitor = esp32_wlan.EspMonitor(type("Factory", (), {"router": router})(), bssid)
        head = bytes([1, 0xC8])
        radio.callback(esp32.MSG_RX_MGMT, head + frame(True, bssid)[:40])   # a trace header only
        radio.callback(esp32.MSG_RX_MGMT, head + frame(False, wlan.MACAddress("ff:ff:ff:ff:ff:ff")))
        with trio.fail_after(1):
            received = await monitor.recv_frame()
        assert received.protected and received.keyid == 1 and not received.tods
        assert received.source == station
        received.decrypt(key)
        assert received.payload == arp.encode()
        assert router.mgmt.statistics().current_buffer_used == 0

    trio.run(main)


@pytest.mark.parametrize("tcp", [False, True])
def test_userspace_socket_readiness_tracks_queued_datagrams(monkeypatch, tcp):
    import select
    import socket
    from pokeldn.ldn.userspace_ip import _Readable

    def tcp_pair():
        # Windows' socketpair is a loopback TCP pair; 3.13.15's own fallback fails on macOS
        with socket.create_server(("127.0.0.1", 0)) as server:
            client = socket.create_connection(server.getsockname())
            return server.accept()[0], client

    if tcp:
        monkeypatch.setattr(socket, "socketpair", tcp_pair)
    with _Readable() as queue:
        if tcp:
            assert queue._w.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
        queue.setblocking(False)
        assert select.select([queue], [], [], 0)[0] == []
        queue._push(b"first")
        queue._push(b"second")
        assert select.select([queue], [], [], 0.2)[0] == [queue]
        assert queue._pop() == b"first"
        assert select.select([queue], [], [], 0.2)[0] == [queue]
        assert queue._pop() == b"second"
        assert select.select([queue], [], [], 0)[0] == []
        with pytest.raises(BlockingIOError):
            queue._pop()
        queue.settimeout(0.001)
        with pytest.raises(socket.timeout):
            queue._pop()
    queue.close()
    queue._push(b"closed")
    assert queue.fileno() == -1


def test_userspace_socket_queue_survives_a_concurrent_reader():
    """A pipe byte seen before its item once raised IndexError; the console showed 2318-0006."""
    import threading
    from pokeldn.ldn import userspace_ip
    queue = userspace_ip._Readable()
    queue.setblocking(False)
    count, got = 20000, []

    def produce():
        for i in range(count):
            while True:
                before = queue.dropped
                queue._push(i)
                if queue.dropped == before:
                    break

    thread = threading.Thread(target=produce)
    thread.start()
    while len(got) < count:
        try:
            got.append(queue._pop())
        except BlockingIOError:
            pass
    thread.join()
    queue.close()
    assert got == list(range(count))


def test_the_arceus_joiner_seats_across_simulated_boards():
    """bin/pla_join.py scans, associates and reaches the console's Net request, join and station list."""
    import argparse

    import pla_join
    from pokeldn import pla
    from pokeldn.ldn import pia6, pia_connect, userspace_ip
    from pokeldn.pla import data_exchange, trade_box

    air = esp32_sim.Air()
    boards = esp32_sim.SimulatedBoard(air), esp32_sim.SimulatedBoard(air)
    radios = tuple(esp32.Radio(b.host_stream()) for b in boards)

    @contextlib.asynccontextmanager
    async def factory():
        esp = esp32_wlan.EspFactory(_radio.get(), port_factory=userspace_ip.userspace_port,
                                    join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    args = pla_join.build_parser().parse_args(["--hold", "4", "--connect-timeout", "10"])
    exchange = data_exchange.build_record(player_id=bytes.fromhex(args.player_id),
                                          name=args.player_name)
    offer = trade_box.build_our_record(**data_exchange.read_record(exchange))
    got = {}

    async def main():
        host_up = trio.Event()

        async def console():
            _radio.set(radios[0])
            param = ldn.CreateNetworkParam(
                keys=KEYS, channel=6, local_communication_id=pla.COMM_ID, name=b"console",
                app_version=0, application_data=pla.build_advertise_data("00000000"),
                password=pla.PASSPHRASE, protocol=pla.LDN_PROTOCOL)
            async with ldn.create_network(param) as network:
                keys = pla.session_keys(network.info().ssid)
                sock = userspace_ip.udp_socket("ldn-tap", pla.PIA_PORT)
                sock.setblocking(False)
                host_ip = str(network.participant().ip_address)
                host_mac = esp32.mac_bytes(network.participant().mac_address)
                host_cid = pia_connect.ldn_constant_id(host_mac)
                host_up.set()
                event = await network.next_event()
                station = str(event.participant.ip_address)

                def send(body, protocol, dst_var, flags=0x01):
                    msg = pia6.build_message(body, protocol=protocol, message_flags=flags)
                    sock.sendto(pia6.build_packet(keys.session_key, keys.network_id, host_ip,
                                                  msg, dst_var=dst_var, src_var=0x2FEE,
                                                  nonce8=os.urandom(8)), (station, pla.PIA_PORT))

                with trio.move_on_after(8):
                    while "stream" not in got:
                        send(pia_connect.build_net_conn_request(
                            2, 0x2FEE, host_mac, keys.network_id, [host_ip, station],
                            max_stations=2, station_size=21), 0x2C, 0, flags=0x31)
                        with trio.move_on_after(0.3):
                            await trio.lowlevel.wait_readable(sock)
                        while True:
                            try:
                                data, (src, _) = sock.recvfrom(4096)
                            except BlockingIOError:
                                break
                            _, plain, _ = pia6.parse_packet(keys.session_key, src,
                                                            keys.network_id, data)
                            for m in pia6.parse_messages(plain):
                                if m.protocol == 0x98 and m.payload[0] == 0:
                                    j = pia_connect.parse_session_join_v11(m.payload)
                                    got["join"] = j
                                    ids = (host_cid, 0x2FEE, j["source_constant_id"],
                                           j["source_var"])
                                    send(pia_connect.build_session_join_response_v11(*ids),
                                         0x98, j["source_var"])
                                    send(bytes([5, 0, 1]) + host_cid, 0x98, j["source_var"])
                                elif m.protocol == 0x98 and m.payload[0] == 6:
                                    got["seated"] = m.payload
                                elif m.protocol == 0x81:
                                    got["stream"] = m.payload
                sock.close()

        async def joiner():
            _radio.set(radios[1])
            await host_up.wait()
            nets = await ldn.scan(KEYS, channels=[6], dwell_time=0.5)
            target = pla_join.pick(args, nets, lambda **row: None)
            got["picked"] = target is not None
            got["session"] = await pla_join.seat(args, KEYS, target, None, offer, exchange,
                                                 lambda **row: None)

        with trio.fail_after(30):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(console)
                nursery.start_soon(joiner)

    wlan.set_factory(factory)
    try:
        trio.run(main)
    finally:
        wlan.set_factory(None)
        for radio in radios:
            radio.close()

    assert got["picked"]
    assert got["join"]["destination_var"] == 0x2FEE
    assert got["seated"][0] == 6 and got["seated"][-2:] == b"\x00\x01"
    assert got["stream"] == bytes.fromhex("0f00000b0001000101000000010000000000008000000000")
    assert got["session"].seated


def test_the_arceus_joiner_takes_the_host_role_a_console_hands_it(tmp_path, monkeypatch):
    """A NetStartHostMigration answer makes the joiner hand its caller the channel to host on."""
    import threading

    import pla_join
    from pokeldn import pla
    from pokeldn.ldn import pia6, pia_connect, userspace_ip
    from pokeldn.pla import data_exchange, trade_box

    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))
    air = esp32_sim.Air()
    console_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    join_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    console_thread = {}

    @contextlib.asynccontextmanager
    async def factory():
        mine = threading.current_thread() is console_thread.get("t")
        esp = esp32_wlan.EspFactory(console_radio if mine else join_radio,
                                    port_factory=userspace_ip.userspace_port, join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    got = {"asked": 0}
    stop = threading.Event()

    async def console():
        param = ldn.CreateNetworkParam(
            keys=KEYS, channel=6, local_communication_id=pla.COMM_ID, name=b"console",
            app_version=0, application_data=pla.build_advertise_data("00000000"),
            password=pla.PASSPHRASE, protocol=pla.LDN_PROTOCOL)
        async with ldn.create_network(param) as network:
            keys = pla.session_keys(network.info().ssid)
            sock = userspace_ip.udp_socket("ldn-tap", pla.PIA_PORT)
            sock.setblocking(False)
            host_ip = str(network.participant().ip_address)
            host_mac = esp32.mac_bytes(network.participant().mac_address)
            event = await network.next_event()
            station = str(event.participant.ip_address)
            answered = False

            def send(body):
                msg = pia6.build_message(body, protocol=0x2C, message_flags=0x31)
                sock.sendto(pia6.build_packet(keys.session_key, keys.network_id, host_ip, msg,
                                              dst_var=0, src_var=0x2FEE, nonce8=os.urandom(8)),
                            (station, pla.PIA_PORT))

            while not stop.is_set():
                if answered:
                    send(bytes.fromhex("01400000"))
                    got["asked"] += 1
                else:
                    send(pia_connect.build_net_conn_request(
                        2, 0x2FEE, host_mac, keys.network_id, [host_ip, station],
                        max_stations=2, station_size=21))
                with trio.move_on_after(0.3):
                    await trio.lowlevel.wait_readable(sock)
                while True:
                    try:
                        sock.recvfrom(4096)
                        answered = True
                    except BlockingIOError:
                        break
            sock.close()

    console_thread["t"] = threading.Thread(target=lambda: trio.run(console), daemon=True)
    args = pla_join.build_parser().parse_args(
        ["--keys", str(keys_file), "--channels", "6", "--dwell", "0.5", "--seconds", "25",
         "--connect-timeout", "10"])
    exchange = data_exchange.build_record(player_id=bytes.fromhex(args.player_id),
                                          name=args.player_name)
    offer = trade_box.build_our_record(**data_exchange.read_record(exchange))
    wlan.set_factory(factory)
    try:
        console_thread["t"].start()
        time.sleep(1)
        result = pla_join.main_radio(args, offer, exchange, lambda **row: None)
    finally:
        stop.set()
        console_thread["t"].join(10)
        wlan.set_factory(None)
        console_radio.close()
        join_radio.close()
    assert got["asked"] >= 1
    assert result["take_host"] == 6 and 0 < result["remaining"] < 25
    argv = pla_join.host_argv(args, result["take_host"], result["remaining"])
    assert argv[argv.index("--channel") + 1] == "6" and argv[argv.index("--code") + 1] == "00000000"


def test_the_sword_gift_walks_its_fragments_on_a_simulated_board(tmp_path, monkeypatch):
    """A protocol-1 advertisement whose data changes while up, reassembled by a scan on a second board."""
    import threading
    import types

    import swsh_gift_host
    from pokeldn.ldn import userspace_ip
    from pokeldn.swsh import COMM_ID, beacon

    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))
    args = swsh_gift_host.build_parser().parse_args(
        ["--species", "25", "--level", "25", "--nickname", "POKELDN", "--ot", "POKELDN",
         "--channel", "6"])
    record = swsh_gift_host.build_record(args)
    fragments = beacon.build_message(record)
    assert len(fragments) == 3

    air = esp32_sim.Air()
    host_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    probe_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())

    @contextlib.asynccontextmanager
    async def host_factory():
        esp = esp32_wlan.EspFactory(host_radio, port_factory=userspace_ip.userspace_port)
        try:
            yield esp
        finally:
            esp.router.close()

    wlan.set_factory(host_factory)
    machine = types.SimpleNamespace(skip_encryption=False, accept_decrypted_ccmp=False)
    host = swsh_gift_host.make_host(args, fragments, str(keys_file), "esp32", machine)
    stop = threading.Event()
    walker = None
    try:
        host.start(timeout=10, attempts=1)
        walker = threading.Thread(target=swsh_gift_host.walk,
                                  args=(host, fragments, 0.2, time.time() + 30, stop),
                                  daemon=True)
        walker.start()
        esp32_wlan.use(radio=probe_radio)
        seen = {}
        deadline = time.time() + 20
        while len(seen) < 3 and time.time() < deadline:
            # A 0.3 s scan locks to the 0.6 s walk and samples fragments 0 and 1 only; 0.27 s drifts.
            for net in trio.run(lambda: ldn.scan(KEYS, channels=[6], dwell_time=0.27)):
                assert net.local_communication_id == COMM_ID and net.max_participants == 8
                seen[bytes(net.application_data)] = True
    finally:
        stop.set()
        if walker is not None:
            walker.join(5)
        host.stop()
        wlan.set_factory(None)
        host_radio.close()
        probe_radio.close()
    assert sorted(seen) == sorted(fragments)
    assert beacon.reassemble(list(seen)) == record


def test_the_firered_gift_host_comes_up_and_advertises_on_a_simulated_board(tmp_path, monkeypatch):
    """bin/frlg_mg_host.py's Wonder Card network, read back by a scan on a second board."""
    import threading

    import frlg_mg_host
    from pokeldn.ldn import transport, userspace_ip

    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))
    air = esp32_sim.Air()
    host_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    probe_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())

    @contextlib.asynccontextmanager
    async def host_factory():
        esp = esp32_wlan.EspFactory(host_radio, port_factory=userspace_ip.userspace_port)
        try:
            yield esp
        finally:
            esp.router.close()

    wlan.set_factory(host_factory)
    result = {}
    host = threading.Thread(target=lambda: result.setdefault("code", frlg_mg_host.main(
        ["--live", "--keys", str(keys_file), "--channel", "6", "--idle-timeout", "6"])),
        daemon=True)
    networks = []
    try:
        host.start()
        time.sleep(3)
        esp32_wlan.use(radio=probe_radio)
        deadline = time.time() + 10
        while not networks and time.time() < deadline:
            networks = [n for n in trio.run(lambda: ldn.scan(KEYS, channels=[6], dwell_time=0.4))
                        if n.local_communication_id == transport.HostTransport.LOCAL_COMMUNICATION_ID]
        host.join(15)
    finally:
        wlan.set_factory(None)
        host_radio.close()
        probe_radio.close()
    assert networks and networks[0].application_data
    assert result.get("code") == 124           # idle timeout: nothing joined, as expected


def test_the_lets_go_joiner_reaches_the_game_on_simulated_boards(tmp_path, monkeypatch):
    """bin/lgpe_join.py against bin/lgpe_host.py: association through the kind-1 identity both ways,
    each under its own trainer's name."""
    import threading

    import lgpe_host
    import lgpe_join
    from pokeldn.ldn import userspace_ip
    from pokeldn.lgpe import pb7

    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))
    identity = pb7.build_message(pb7.FIRST_MESSAGE, pb7.set_trainer_id(bytes(360), 41234, 12345))
    (tmp_path / "identity.bin").write_bytes(identity)
    air = esp32_sim.Air()
    host_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    join_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    threads = {}

    @contextlib.asynccontextmanager
    async def factory():
        radio = join_radio if threading.current_thread() is threads.get("join") else host_radio
        esp = esp32_wlan.EspFactory(radio, port_factory=userspace_ip.userspace_port,
                                    join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    result = {}
    threads["host"] = threading.Thread(target=lambda: result.setdefault("host", lgpe_host.main(
        ["--keys", str(keys_file), "--channel", "6", "--seconds", "14", "--grace", "0",
         "--first", "echo", "--trainer-name", "HOSTER", "--capture", str(tmp_path / "host.jsonl")])),
        daemon=True)
    threads["join"] = threading.Thread(target=lambda: result.setdefault("join", lgpe_join.main(
        ["--keys", str(keys_file), "--channels", "6", "--dwell", "0.5", "--connect",
         "--connect-seconds", "10", "--facts", str(tmp_path / "facts.json"),
         "--capture", str(tmp_path / "join.jsonl"),
         "--reliable-payload", str(tmp_path / "identity.bin"), "--trainer-name", "JOINER",
         "--ack-peer-clock", "--ack-re-announce"])), daemon=True)
    wlan.set_factory(factory)
    try:
        threads["host"].start()
        time.sleep(2)
        threads["join"].start()
        threads["join"].join(40)
        threads["host"].join(40)
    finally:
        wlan.set_factory(None)
        host_radio.close()
        join_radio.close()
    assert result == {"host": 0, "join": 0}

    def named(name):
        return pb7.build_message(pb7.FIRST_MESSAGE, pb7.set_trainer_name(identity[pb7.HEADER_SIZE:], name))
    assert (tmp_path / "host.jsonl.payload1.bin").read_bytes() == named("JOINER")
    assert (tmp_path / "join.jsonl.payload1.bin").read_bytes() == named("HOSTER")


def test_the_lets_go_joiner_trades_its_queue_on_one_seat_on_simulated_boards(tmp_path, monkeypatch):
    """bin/lgpe_join.py with two --offer against bin/lgpe_host.py --lead, which plays a console host:
    trade 2 offers on kind 4 and commits on kind 5 on clones 6 and 7, and each side writes what it
    received in order."""
    import struct
    import threading

    import lgpe_host
    import lgpe_join
    from pokeldn import pokemon
    from pokeldn.ldn import userspace_ip
    from pokeldn.lgpe import pb7

    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    monkeypatch.setattr(pokemon, "prepare_file", lambda game, path, fresh=False: path)
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))

    def record(name, species, ec):
        plain = bytearray(pb7.BOX_SIZE)
        struct.pack_into("<IH", plain, 0, ec, 0)
        struct.pack_into("<H", plain, 8, species)
        (tmp_path / name).write_bytes(pb7.encrypt(bytes(plain)))
        return str(tmp_path / name)

    host_offers = [record("pikachu.pb7", 25, 0x11111111), record("onix.pb7", 95, 0x22222222)]
    join_offers = [record("eevee.pb7", 133, 0x33333333), record("bulbasaur.pb7", 1, 0x44444444)]
    air = esp32_sim.Air()
    host_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    join_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    threads = {}

    @contextlib.asynccontextmanager
    async def factory():
        radio = join_radio if threading.current_thread() is threads.get("join") else host_radio
        esp = esp32_wlan.EspFactory(radio, port_factory=userspace_ip.userspace_port,
                                    join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    result = {}
    threads["host"] = threading.Thread(target=lambda: result.setdefault("host", lgpe_host.main(
        ["--keys", str(keys_file), "--channel", "6", "--seconds", "30", "--grace", "0",
         "--first", "echo", "--lead", "1", "--result-after", "2",
         "--offer", host_offers[0], "--next-offer", host_offers[1],
         "--received", str(tmp_path / "host_got.pb7"),
         "--capture", str(tmp_path / "host.jsonl")])), daemon=True)
    threads["join"] = threading.Thread(target=lambda: result.setdefault("join", lgpe_join.main(
        ["--keys", str(keys_file), "--channels", "6", "--dwell", "0.5", "--connect",
         "--connect-seconds", "26", "--grace", "0", "--facts", str(tmp_path / "facts.json"),
         "--capture", str(tmp_path / "join.jsonl"), "--ack-peer-clock", "--ack-re-announce",
         "--offer", join_offers[0], "--offer", join_offers[1],
         "--received", str(tmp_path / "join_got.pb7")])), daemon=True)
    wlan.set_factory(factory)
    try:
        threads["host"].start()
        time.sleep(2)
        threads["join"].start()
        threads["join"].join(60)
        threads["host"].join(60)
    finally:
        wlan.set_factory(None)
        host_radio.close()
        join_radio.close()

    def species(name):
        return int.from_bytes(pb7.decrypt((tmp_path / name).read_bytes()[:pb7.BOX_SIZE])[8:10], "little")

    def sent(capture):
        """(kind, step) of each game message the other side received, from its payload files."""
        out = []
        for path in sorted(tmp_path.glob(f"{capture}.payload*.bin"),
                           key=lambda p: int(p.name.rsplit("payload", 1)[1][:-4])):
            m = pb7.parse_message(path.read_bytes())
            out.append((m["kind"], m["step"]))
        return out

    assert result == {"host": 0, "join": 0}
    assert [species("join_got.pb7"), species("join_got-2.pb7")] == [25, 95]
    assert [species("host_got.pb7"), species("host_got-2.pb7")] == [133, 1]
    # The joiner's answers, as the host read them: identity, offer, commits 1 and 2, then trade 2 on
    # kinds 4 and 5. After the last queued trade it sends no kind 6.
    assert sent("host.jsonl") == [(1, 1), (2, 2), (3, 3), (3, 4), (4, 5), (4, 6), (5, 7), (5, 8)]
    assert sent("join.jsonl")[-1] == (6, 9)


def test_the_bench_counts_every_message_from_a_simulated_board():
    radio = esp32.Radio(esp32_sim.SimulatedBoard(esp32_sim.Air()).host_stream())
    try:
        r = radio.bench(100_000, 1400, timeout=10)
    finally:
        radio.close()
    assert r["messages"] == 72 and r["missing"] == 0 and r["rejected"] == 0
    assert r["bytes"] == 72 * 1400


def test_the_fast_rate_comes_from_the_environment(monkeypatch):
    """POKELDN_ESP32_BAUD picks the rate open_serial switches to; the default is 921600."""
    import serial

    rates = []

    class Port:
        def __init__(self):
            self.board = esp32_sim.SimulatedBoard(esp32_sim.Air()).host_stream()
            self._baud = 115200

        baudrate = property(lambda self: self._baud,
                            lambda self, v: (setattr(self, "_baud", v), rates.append(v)))

        def open(self):
            pass

        def read(self, n):
            return self.board.read(n)

        def write(self, data):
            self.board.write(data)

        def flush(self):
            pass

        def close(self):
            self.board.close()

    monkeypatch.setattr(serial, "Serial", Port)
    monkeypatch.setenv("POKELDN_ESP32_BAUD", "2000000")
    esp32.Radio.open_serial("sim").close()
    monkeypatch.delenv("POKELDN_ESP32_BAUD")
    esp32.Radio.open_serial("sim").close()
    assert rates[-1] == 921600 and 2000000 in rates


def test_a_board_that_leaves_usb_mid_run_stops_the_run_once_and_stops_writing():
    """Windows fails the read of a removed USB device with PermissionError 13 and every write after
    it; a run kept writing to the dead port until the player pressed Stop."""
    board = esp32_sim.SimulatedBoard(esp32_sim.Air()).host_stream()
    gone = threading.Event()
    writes_after = []

    class Port:
        def read(self, n):
            if gone.is_set():
                raise PermissionError(13, "Access is denied.", None, 5)
            return board.read(n)

        def write(self, data):
            if gone.is_set():
                writes_after.append(data)
                raise PermissionError(13, "Access is denied.", None, 5)
            board.write(data)

        def close(self):
            board.close()

    lost = []
    radio = esp32.Radio(Port(), on_lost=lost.append)
    try:
        radio.hello()
        gone.set()
        deadline = time.monotonic() + 2
        while not lost and time.monotonic() < deadline:
            time.sleep(0.01)
        start = time.monotonic()
        with pytest.raises(esp32.RadioError, match="left USB"):
            radio.request(esp32.CMD_HELLO, b"", esp32.MSG_INFO, timeout=3.0)
        assert time.monotonic() - start < 0.5
        for _ in range(50):
            radio.send(esp32.CMD_STATUS)
        time.sleep(0.2)
        assert len(lost) == 1 and isinstance(lost[0], PermissionError)
        assert writes_after == []
    finally:
        radio.close()


def test_a_board_that_never_answers_releases_its_port(monkeypatch):
    """Windows opens a COM port exclusively: a failed open that kept its handle refused every retry
    with PermissionError 13, hiding the first attempt's cause."""
    import serial
    held = []

    class Port:
        def open(self):
            if held:
                raise serial.SerialException("could not open port: PermissionError(13, 'Access is denied.')")
            held.append(self)

        def read(self, n):
            time.sleep(0.01)
            return b""                                   # a board in its ROM bootloader

        def write(self, data):
            pass

        def flush(self):
            pass

        def close(self):
            held.remove(self)

    def silent(self, *args, **kwargs):
        raise esp32.RadioError("no answer to HELLO")

    monkeypatch.setattr(serial, "Serial", Port)
    monkeypatch.setattr(esp32.Radio, "request", silent)
    for _ in range(2):
        with pytest.raises(esp32.RadioError):
            esp32.Radio.open_serial("COM7")
    assert not held


@pytest.mark.parametrize("version", ["1.4.0", ""])
def test_a_board_whose_host_dies_leaves_the_network_and_an_older_board_is_never_fed(monkeypatch, version):
    """A host killed mid-seat stops sending ALIVE; the board leaves and the console's AP sees the
    station go. Firmware that names no version answers ALIVE as unknown, so it is never sent."""
    import serial
    air = esp32_sim.Air()
    ap_board, station_board = esp32_sim.SimulatedBoard(air), esp32_sim.SimulatedBoard(air)
    station_board.version, station_board.host_silent_after = version, 0.3
    commands = []
    command = station_board._command
    station_board._command = lambda t, p: (commands.append(t), command(t, p))

    class Port:
        def __init__(self):
            self.board, self.baudrate = station_board.host_stream(), 115200

        def open(self):
            pass

        def read(self, n):
            return self.board.read(n)

        def write(self, data):
            self.board.write(data)

        def flush(self):
            pass

        def close(self):
            self.board.close()

    monkeypatch.setattr(serial, "Serial", Port)
    monkeypatch.setattr(esp32, "ALIVE_EVERY", 0.05)
    ap = esp32.Radio(ap_board.host_stream())
    station = esp32.Radio.open_serial("sim", fast_baud=115200)
    try:
        ap.ap_start(6, b"\x02" * 6, "0" * 32, bytes(16))
        station.sta_join(6, b"\x02" * 6, "0" * 32, bytes(16))
        time.sleep(0.6)                                  # twice the silence the board allows
        assert ap_board.stations                             # fed, still seated
        station._closed = True                            # the process is gone: nothing more is sent
        deadline = time.monotonic() + 2
        while ap_board.stations and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (not ap_board.stations) == bool(version)
        assert (esp32.CMD_ALIVE in commands) == bool(version)
    finally:
        station._closed = False
        station.close()
        ap.close()


def test_auto_port_takes_the_one_serial_port_and_refuses_to_guess():
    from pokeldn.ldn import esp32_wlan
    assert esp32_wlan.auto_port(["/dev/cu.usbserial-7"]) == "/dev/cu.usbserial-7"
    for ports in ([], ["/dev/cu.usbserial-1", "/dev/cu.usbserial-2"]):
        try:
            esp32_wlan.auto_port(ports)
        except RuntimeError:
            continue
        raise AssertionError(f"chose a port out of {ports}")


def test_windows_auto_port_enumerates_usb_without_opening_it(monkeypatch):
    from types import SimpleNamespace
    from serial.tools import list_ports
    monkeypatch.setattr(esp32_wlan.sys, "platform", "win32")
    found = [SimpleNamespace(device="COM1", vid=None),
             SimpleNamespace(device="COM4", vid=0x303A)]
    monkeypatch.setattr(list_ports, "comports", lambda: found)
    assert esp32_wlan.auto_port() == "COM4"
    found.append(SimpleNamespace(device="COM5", vid=0x10C4))
    with pytest.raises(RuntimeError, match="exactly one"):
        esp32_wlan.auto_port()


def test_sword_host_and_joiner_trade_on_simulated_boards(tmp_path, monkeypatch):
    """bin/swsh_connect.py against bin/swsh_host.py: two trades on one session, each side offering
    its queued records in order and saving the other's. The host plays a console's player: it accepts
    first and offers again from the box after the first trade (--lead)."""
    import threading

    import swsh_connect
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn import gen8, pokemon as pokemon_service
    from pokeldn.ldn import userspace_ip
    from pokeldn.swsh import pokemon

    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    monkeypatch.setattr(pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(pokemon_service, "prepare", lambda game, raw, **kw: gen8.decrypt(raw))
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))
    party = a_payload(count=4)
    (tmp_path / "snapshot.bin").write_bytes(party)
    for slot in range(4):
        (tmp_path / f"offer{slot}.pk8").write_bytes(party[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY])
    air = esp32_sim.Air()
    host_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    join_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    threads = {}

    @contextlib.asynccontextmanager
    async def factory():
        radio = join_radio if threading.current_thread() is threads.get("join") else host_radio
        esp = esp32_wlan.EspFactory(radio, port_factory=userspace_ip.userspace_port, join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    result = {}
    threads["host"] = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--keys", str(keys_file), "--channel", "6", "--seconds", "50", "--accept-first",
         "--lead", "3",
         "--snapshot", str(tmp_path / "snapshot.bin"), "--received", str(tmp_path / "host.pk8"),
         "--offer-file", str(tmp_path / "offer0.pk8"), "--offer-file", str(tmp_path / "offer1.pk8")])),
        daemon=True)
    threads["join"] = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        ["--keys", str(keys_file), "--preset", "trade", "--channels", "6", "--dwell", "0.5",
         "--hold", "35", "--save-offered", str(tmp_path / "join.pk8"),
         "--offer-file", str(tmp_path / "offer2.pk8"), "--offer-file", str(tmp_path / "offer3.pk8")])),
        daemon=True)
    wlan.set_factory(factory)
    try:
        threads["join"].start()          # before the host: the joiner rescans until it appears
        time.sleep(1.5)
        threads["host"].start()
        threads["join"].join(120)
        threads["host"].join(120)
    finally:
        wlan.set_factory(None)
        host_radio.close()
        join_radio.close()
    assert result == {"host": 0, "join": 0}

    def species(name):
        return pokemon.read(pokemon.encrypt(gen8.load((tmp_path / name).read_bytes())))["species"]
    assert [species(n) for n in ("join.pk8", "join-2.pk8")] == [94, 95]
    assert [species(n) for n in ("host.pk8", "host-2.pk8")] == [96, 97]


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_the_board_needs_no_privilege_on_any_platform(monkeypatch, platform):
    """A kernel TAP needs CAP_NET_ADMIN, which the desktop app never has; it is opt-in on Linux."""
    from pokeldn.ldn import userspace_ip
    monkeypatch.delenv("POKELDN_L2", raising=False)
    monkeypatch.setattr(esp32_wlan.sys, "platform", platform)
    assert esp32_wlan.default_port_factory() is userspace_ip.userspace_port
    monkeypatch.setenv("POKELDN_L2", "tap")
    assert esp32_wlan.default_port_factory() is esp32_wlan.kernel_tap

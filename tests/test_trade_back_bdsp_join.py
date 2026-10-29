"""The Brilliant Diamond / Shining Pearl joiner (bin/bdsp_connect.py) against a scripted console on a
loopback socket, over the whole receive and send path, Pia encryption included: trade back over two
trades, and the departure --hold-after-trade sends after the queue."""
import contextlib
import socket
import struct
import time
import types

import trio

import bdsp_connect
from pokeldn.bdsp import COMM_ID, host, pokemon, room
from pokeldn.ldn import mesh_protocol as mp, reliable5 as rl, station_protocol as stp
from pokeldn.ldn.pia5 import PiaHeader5, ciphertext, decrypt_payload, gcm_iv, ldn_nonce_crc, parse_messages

HOST_MAC, OUR_MAC = bytes.fromhex("021111111111"), bytes.fromhex("022222222222")
KEYS = types.SimpleNamespace(session_key=bytes(range(16)), network_id_le=bytes.fromhex("b4c85cf8"))
CONSOLE_VAR, OUR_VAR = 0x11223344, 0x2B7F4C11


def a_pb8(ec, species, nickname):
    plain = bytearray(bytes(range(256)) * 2)[:pokemon.SIZE_STORED]
    struct.pack_into("<I", plain, 0x00, ec)
    struct.pack_into("<H", plain, 0x04, 0)
    struct.pack_into("<H", plain, pokemon.OFF_SPECIES, species)
    plain[pokemon.OFF_NICKNAME:pokemon.OFF_NICKNAME + pokemon.NAME_LENGTH] = \
        nickname.encode("utf-16-le").ljust(pokemon.NAME_LENGTH, b"\x00")
    return pokemon.encrypt(bytes(plain))


class Loopback:
    """The joiner's socket: every send goes to the console's socket, whatever the address."""

    def __init__(self, console_addr):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.console_addr = console_addr

    def fileno(self):
        return self.sock.fileno()

    def recvfrom(self, n):
        return self.sock.recvfrom(n)

    def sendto(self, data, _addr):
        self.sock.sendto(data, self.console_addr)


class ScriptedConsole:
    """A console that sends a TRADE_POKE, waits for ours, then reports SEND_READYOK and its character
    state, once per trade. Its reliable id is shared with the joiner's: a joiner message under an id
    below the console's last send is acknowledged and dropped (docs/bdsp_protocol.md), as a retail
    Shining Pearl dropped a returned Pokemon sent under 27 after its own 27 and 28."""

    def __init__(self):
        self.sock = None
        self.joiner = None
        self.seq = 1
        self.nonce = 0

    def packet(self, payload, protocol=rl.PROTOCOL, port=rl.PORT):
        self.nonce += 1
        return bdsp_connect.wrap(KEYS, HOST_MAC, CONSOLE_VAR, OUR_VAR, self.nonce.to_bytes(8, "big"),
                                 payload, protocol, port=port)

    def messages(self, data):
        h = PiaHeader5.parse(data)
        iv = gcm_iv(ldn_nonce_crc(KEYS.network_id_le, OUR_MAC), h.src_var, h.nonce8)
        return parse_messages(decrypt_payload(KEYS.session_key, iv, ciphertext(data, h.footer_size), h.tag))

    async def send_data(self, message):
        frame = rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START | rl.FLAG_MESSAGE_END
                                | rl.FLAG_IS_INITIALIZED, self.seq, len(message),
                                lowest_pending=self.seq) + message
        self.seq += 1
        await self.sock.sendto(self.packet(frame), self.joiner)

    async def ack(self, ack_id):
        await self.sock.sendto(self.packet(rl.build_ack_message(ack_id)), self.joiner)

    async def their_poke(self):
        """-> the PB8 of the next NetTradePokeData the joiner sends, after acking it."""
        while True:
            data, _ = await self.sock.recvfrom(4096)
            for m in self.messages(data):
                if m.protocol != rl.PROTOCOL:
                    continue
                d = rl.parse(m.payload)
                if not d["flags"] & rl.FLAG_APPLICATION_DATA:
                    continue
                await self.ack(d["sequence_id"] + 1)
                if d["sequence_id"] < self.seq - 1:
                    continue
                g = room.parse(d["payload"])
                if g["data_id"] == room.TRADE_POKE:
                    return d["payload"][room.HEADER_SIZE:]

    async def trade(self, ours):
        await self.send_data(room.build_trade_poke(ours))
        got = await self.their_poke()
        await self.send_data(room.build_trade_ready_ok(room.TRADE_STATE_SEND_READYOK, is_trade_ok=1))
        await self.send_data(room.build_state(18))
        return got


def _run_joiner(monkeypatch, args, console, script):
    net = types.SimpleNamespace(local_communication_id=COMM_ID, ssid=b"room", channel=1, app_version=1)
    participant = lambda ip, mac: types.SimpleNamespace(ip_address=ip, mac_address=mac, connected=True)
    info = types.SimpleNamespace(participants=[participant("169.254.54.1", HOST_MAC),
                                               participant("169.254.54.2", OUR_MAC)])

    @contextlib.asynccontextmanager
    async def connect(_param):
        yield types.SimpleNamespace(info=lambda: info)

    async def scan(*_a, **_k):
        return [net]

    monkeypatch.setattr(bdsp_connect, "cleanup", lambda: None)
    monkeypatch.setattr(bdsp_connect, "resolve_keys", lambda k: k)
    monkeypatch.setattr(bdsp_connect, "session_keys", lambda n: KEYS)
    monkeypatch.setattr(bdsp_connect.ldn, "load_keys", lambda k: None)
    monkeypatch.setattr(bdsp_connect.ldn, "scan", scan)
    monkeypatch.setattr(bdsp_connect.ldn, "connect", connect)
    monkeypatch.setattr(bdsp_connect.ldn, "ConnectNetworkParam", types.SimpleNamespace)
    joiner = {}

    def make_socket(_ifname):
        joiner["sock"] = Loopback(console.sock.getsockname())
        console.joiner = joiner["sock"].sock.getsockname()
        return joiner["sock"]

    monkeypatch.setattr(bdsp_connect, "make_socket", make_socket)

    async def run():
        console.sock = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
        with console.sock:
            await console.sock.bind(("127.0.0.1", 0))
            async with trio.open_nursery() as nursery:
                nursery.start_soon(bdsp_connect.main_async, args)
                with trio.fail_after(10):
                    while console.joiner is None:
                        await trio.sleep(0.01)
                    await script(nursery)

    try:
        trio.run(run)
    finally:
        joiner["sock"].sock.close()


# A retail Shining Pearl leaving a room, decrypted: the mesh leave request `04 01` under the reliable
# header (sequence 1), as tests/test_bdsp_host.py has it.
RETAIL_LEAVE_REQUEST = bytes.fromhex("0f00000200010001000401")


def test_the_bdsp_joiner_leaves_as_a_retail_station_does_soon_after_its_queued_trade(monkeypatch, tmp_path):
    """--hold-after-trade: once the only queued offer has traded, the joiner sends a retail station's
    leave request and station disconnection, each until the host answers, and ends well before --hold."""
    template = tmp_path / "queued.pb8"
    template.write_bytes(a_pb8(0x0000E000, 41, "Nosferapti"))
    args = bdsp_connect.build_parser().parse_args([
        "--phy", "none", "--scans", "1", "--listen-first", "0", "--hold", "20",
        "--trade-reply", "--complete-trade", "--security-repeat", "100",
        "--trade-template", str(template), "--src-var", hex(OUR_VAR), "--hold-after-trade", "0.2"])
    monkeypatch.setattr(bdsp_connect, "TRADE_SETTLE", 0.3)
    console = ScriptedConsole()
    heard, timeline = [], {}   # the joiner's run must end on its own once both are answered

    async def script(nursery):
        loc = lambda ip, mac, var: host.host_location(ip, stp.ldn_constant_id(mac), var,
                                                      stp.ldn_service_variable_id(mac))
        join = host.build_join_response([(loc("169.254.54.1", HOST_MAC, CONSOLE_VAR), 0, 0),
                                         (loc("169.254.54.2", OUR_MAC, OUR_VAR), 1, 1)], 1, 5)
        await console.sock.sendto(console.packet(join, mp.PROTOCOL, mp.PORT_UNRELIABLE), console.joiner)
        await console.ack(1)
        await console.trade(a_pb8(0xCDBEB642, 25, "Pikachu"))
        timeline["traded"] = time.monotonic()
        while (stp.PROTOCOL, bytes([stp.DISCONNECTION_REQUEST])) not in heard:
            data, _ = await console.sock.recvfrom(4096)
            for m in console.messages(data):
                if (m.protocol, m.port) == (mp.PROTOCOL, mp.PORT_RELIABLE) and m.payload[:1] == b"\x0f":
                    heard.append((m.protocol, m.payload))
                    answer = console.packet(bytes([mp.LEAVE_RESPONSE, 0]), mp.PROTOCOL, mp.PORT_UNRELIABLE)
                    await console.sock.sendto(answer, console.joiner)
                elif m.protocol == stp.PROTOCOL and m.payload == bytes([stp.DISCONNECTION_REQUEST]):
                    heard.append((m.protocol, m.payload))
                    answer = console.packet(bytes([stp.DISCONNECTION_RESPONSE]), stp.PROTOCOL, 0)
                    await console.sock.sendto(answer, console.joiner)

    _run_joiner(monkeypatch, args, console, script)
    assert heard[0] == (mp.PROTOCOL, RETAIL_LEAVE_REQUEST)
    assert heard[-1] == (stp.PROTOCOL, bytes([stp.DISCONNECTION_REQUEST]))
    assert time.monotonic() - timeline["traded"] < 4.0


def test_the_bdsp_joiner_offers_back_the_console_pokemon_byte_for_byte(monkeypatch, tmp_path):
    queued = a_pb8(0x0000E000, 41, "Nosferapti")
    console_first, console_second = a_pb8(0xCDBEB642, 25, "Pikachu"), a_pb8(0x12345678, 63, "Abra")
    template = tmp_path / "queued.pb8"
    template.write_bytes(queued)
    args = bdsp_connect.build_parser().parse_args([
        "--phy", "none", "--scans", "1", "--listen-first", "0", "--hold", "20",
        "--trade-reply", "--complete-trade", "--security-repeat", "100", "--trade-back",
        "--trade-template", str(template), "--trade-save-poke", str(tmp_path / "received.pb8"),
        "--src-var", hex(OUR_VAR)])
    console = ScriptedConsole()
    offered = []

    async def script(nursery):
        await console.ack(1)           # the joiner's first reliable message takes id 1
        offered.append(await console.trade(console_first))
        await trio.sleep(0.2)
        offered.append(await console.trade(console_second))
        nursery.cancel_scope.cancel()

    _run_joiner(monkeypatch, args, console, script)
    assert offered[0] == queued
    assert offered[1] == console_first

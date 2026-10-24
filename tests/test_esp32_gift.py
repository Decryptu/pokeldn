"""The board hosting a FireRed/LeafGreen Mystery Gift alone (firmware/esp32/main/gift_*.c, compiled
here with vendor/zstd) on a simulated board, against bin/frlg_mg_client.py in the console's place on
another: LDN authentication, Pia, Reliable, the RFU leader and the server script, end to end."""
import collections
import contextlib
import ctypes
import hashlib
import hmac
import os
import queue
import shutil
import subprocess
import threading
import time

import pytest
from Crypto.Cipher import AES

from test_esp32_beacon import Crypto, Image, CALLBACKS

ROOT = os.path.join(os.path.dirname(__file__), "..")
MAIN = os.path.join(ROOT, "firmware", "esp32", "main")
ZSTD = os.path.join(ROOT, "vendor", "zstd", "lib")
ENGINE = ("advert.c", "gift_ldn.c", "gift_pia.c", "gift_link.c", "gift_mg.c", "gift_zstd.c")
ZSTD_SOURCES = ("common/debug.c", "common/entropy_common.c", "common/error_private.c",
                "common/fse_decompress.c", "common/xxhash.c", "common/zstd_common.c",
                "decompress/huf_decompress.c", "decompress/zstd_ddict.c",
                "decompress/zstd_decompress.c", "decompress/zstd_decompress_block.c")
ZSTD_DEFINES = ("-DZSTD_DISABLE_ASM=1", "-DZSTD_MULTITHREAD=0", "-DZSTD_DECODER_INTERNAL_BUFFER=1024")

P = ctypes.c_void_p
N = ctypes.c_size_t
SHA = ctypes.CFUNCTYPE(ctypes.c_int, P, N, P)
HMAC = ctypes.CFUNCTYPE(ctypes.c_int, P, N, P, N, P)
BLOCK = ctypes.CFUNCTYPE(ctypes.c_int, P, P, P)
GCM = ctypes.CFUNCTYPE(ctypes.c_int, P, P, P, N, P, P, N, P, N)
RANDOM = ctypes.CFUNCTYPE(ctypes.c_uint32, P)
SEND = ctypes.CFUNCTYPE(None, P, P, N)
KICK = ctypes.CFUNCTYPE(None, P, P)
EVENT = ctypes.CFUNCTYPE(None, P, ctypes.c_int, ctypes.c_int)

EVENT_JOINED, EVENT_LINKED, EVENT_RESULT, EVENT_LEFT, EVENT_REFUSED = range(1, 6)


class Platform(ctypes.Structure):
    _fields_ = [("sha256", SHA), ("hmac_sha256", HMAC), ("aes_decrypt_block", BLOCK),
                ("aes_encrypt_block", BLOCK), ("gcm_seal", GCM), ("gcm_open", GCM), ("random", RANDOM), ("send", SEND),
                ("kick", KICK), ("event", EVENT), ("context", P)]


def _read(address, n):
    return ctypes.string_at(address, n) if n else b""


def _sha(data, n, out):
    ctypes.memmove(out, hashlib.sha256(_read(data, n)).digest(), 32)
    return 0


def _hmac(key, key_n, data, n, out):
    ctypes.memmove(out, hmac.digest(_read(key, key_n), _read(data, n), "sha256"), 32)
    return 0


def _block(key, src, dst):
    ctypes.memmove(dst, AES.new(_read(key, 16), AES.MODE_ECB).decrypt(_read(src, 16)), 16)
    return 0


def _encrypt_block(key, src, dst):
    ctypes.memmove(dst, AES.new(_read(key, 16), AES.MODE_ECB).encrypt(_read(src, 16)), 16)
    return 0


def _seal(key, iv, aad, aad_n, src, dst, n, tag, tag_n):
    cipher = AES.new(_read(key, 16), AES.MODE_GCM, nonce=_read(iv, 12), mac_len=tag_n)
    cipher.update(_read(aad, aad_n))
    out, mac = cipher.encrypt_and_digest(_read(src, n))
    ctypes.memmove(dst, out, n)
    ctypes.memmove(tag, mac, tag_n)
    return 0


def _open(key, iv, aad, aad_n, src, dst, n, tag, tag_n):
    cipher = AES.new(_read(key, 16), AES.MODE_GCM, nonce=_read(iv, 12), mac_len=tag_n)
    cipher.update(_read(aad, aad_n))
    try:
        out = cipher.decrypt_and_verify(_read(src, n), _read(tag, tag_n))
    except ValueError:
        return 1
    ctypes.memmove(dst, out, n)
    return 0


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("gift")
    objects = []
    for source in ZSTD_SOURCES:
        obj = out / (source.replace("/", "_") + ".o")
        subprocess.run([cc, "-c", "-fPIC", "-O2", *ZSTD_DEFINES, "-I", ZSTD,
                        "-I", os.path.join(ZSTD, "common"), "-o", str(obj),
                        os.path.join(ZSTD, source)], check=True)
        objects.append(str(obj))
    lib = out / "gift.so"
    subprocess.run([cc, "-shared", "-fPIC", "-O1", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", MAIN, "-I", ZSTD, "-o", str(lib),
                    *(os.path.join(MAIN, s) for s in ENGINE), *objects], check=True)
    so = ctypes.CDLL(str(lib))
    so.advert_parse.argtypes = (ctypes.c_char_p, N, ctypes.POINTER(Image))
    so.advert_frame_plain.argtypes = (ctypes.POINTER(Image), ctypes.c_char_p, N, ctypes.c_uint32,
                                      ctypes.POINTER(Crypto), ctypes.c_char_p)
    so.advert_frame_plain.restype = N
    so.gift_image_size.restype = N
    so.gift_host_size.restype = N
    so.gift_parse.argtypes = (ctypes.POINTER(Image), P)
    so.gift_host_start.argtypes = (P, P, ctypes.POINTER(Platform), ctypes.c_uint64)
    so.gift_host_start.restype = P
    so.gift_host_rx.argtypes = (P, ctypes.c_char_p, N, ctypes.c_uint64)
    so.gift_host_rx_80211.argtypes = (P, ctypes.c_char_p, N, ctypes.c_uint64)
    so.gift_host_station.argtypes = (P, ctypes.c_char_p, ctypes.c_bool, ctypes.c_uint64)
    so.gift_host_poll.argtypes = (P, ctypes.c_uint64)
    so.gift_host_poll.restype = ctypes.c_uint64
    so.gift_host_advert.argtypes = (P, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32))
    so.gift_host_advert.restype = N
    return so


def _now_us():
    return time.monotonic_ns() // 1000


class FirmwareBoard:
    """A simulated board running radio.c's portable beacon: the image's access point, its
    advertisement every 100 ms, and every station frame and association handed to the gift host, on
    one task as the firmware does. A station's broadcast arrives as the air carries it: no DS bits,
    CCMP under the group key (docs/ldn.md), QoS on every other one."""

    def __init__(self, so, air, image: bytes):
        from pokeldn.ldn import esp32, esp32_sim
        self.so, self.esp32 = so, esp32
        self.keep = ctypes.create_string_buffer(image, len(image))
        self.advert = Image()
        assert so.advert_parse(self.keep, len(image), ctypes.byref(self.advert)) == 0
        self.gift = ctypes.create_string_buffer(so.gift_image_size())
        self.refused = so.gift_parse(ctypes.byref(self.advert), self.gift)
        self.events = []
        self._inbox = queue.Queue()
        self._stop = threading.Event()
        board = esp32_sim.SimulatedBoard(air)
        board._emit = self._from_air
        board.channel, board.bssid, board.ssid, board.key = image[8], image[9:15], image[15:47], image[47:63]
        board.mode, board.beacon_on = esp32_sim.AP, True
        self.board = board
        self.platform = Platform(SHA(_sha), HMAC(_hmac), BLOCK(_block), BLOCK(_encrypt_block),
                                 GCM(_seal), GCM(_open),
                                 RANDOM(lambda _: int.from_bytes(os.urandom(4), "little")),
                                 SEND(self._send), KICK(self._kick), EVENT(self._event), None)
        self.memory = ctypes.create_string_buffer(so.gift_host_size())
        self._thread = threading.Thread(target=self._run, daemon=True)
        if self.refused == 0:
            self._thread.start()

    def _from_air(self, msg_type, payload=b""):
        esp32 = self.esp32
        if msg_type == esp32.MSG_RX_ETH and payload[:6] == b"\xff" * 6:
            self._inbox.put(("air", self._on_air(bytes(payload))))
        elif msg_type in (esp32.MSG_RX_ETH, esp32.MSG_STA_JOINED, esp32.MSG_STA_LEFT):
            self._inbox.put((msg_type, bytes(payload)))

    def _on_air(self, ethernet):
        from ldn import wlan
        self.broadcasts = getattr(self, "broadcasts", 0) + 1
        frame = wlan.DataFrame()
        frame.target, frame.source = wlan.MACAddress(ethernet[0:6]), wlan.MACAddress(ethernet[6:12])
        frame.bssid = wlan.MACAddress(self.board.bssid)
        frame.qos, frame.tid = bool(self.broadcasts & 1), 0
        snap = wlan.SNAPHeader()
        snap.protocol = int.from_bytes(ethernet[12:14], "big")
        snap.payload = ethernet[14:]
        frame.payload = snap.encode()
        frame.encrypt(self.board.key, self.broadcasts, 1)
        raw = frame.encode()
        if frame.qos:
            # DataFrame.encode writes no QoS header; its encrypt took the TID into nonce and AAD.
            raw = bytes([raw[0] | 0x80]) + raw[1:24] + bytes([frame.tid, 0]) + raw[24:]
        return raw

    def _send(self, _, frame, n):
        with self.board.air.lock:
            self.board._ethernet_tx(_read(frame, n))

    def _kick(self, _, mac):
        mac = _read(mac, 6)
        with self.board.air.lock:
            if mac in self.board.stations:
                self.board._drop_station(mac, 3)

    def _event(self, _, event, value):
        self.events.append((event, value))

    def _run(self):
        so, esp32 = self.so, self.esp32
        host = so.gift_host_start(self.memory, self.gift, ctypes.byref(self.platform), _now_us())
        nonce = int.from_bytes(os.urandom(4), "big")
        plain = ctypes.create_string_buffer(1024)
        frame = ctypes.create_string_buffer(24 + 12 + 40 + 32 + 0x500)
        version = ctypes.c_uint32()
        deadline = next_advert = 0
        while not self._stop.is_set():
            wait = max(0, min(deadline, next_advert) - _now_us()) / 1e6
            try:
                msg_type, payload = self._inbox.get(timeout=min(wait, 0.05))
            except queue.Empty:
                pass
            else:
                if msg_type == "air":
                    so.gift_host_rx_80211(host, payload, len(payload), _now_us())
                elif msg_type == esp32.MSG_RX_ETH:
                    so.gift_host_rx(host, payload, len(payload), _now_us())
                else:
                    so.gift_host_station(host, payload[:6], msg_type == esp32.MSG_STA_JOINED, _now_us())
                deadline = 0
            now = _now_us()
            if now >= deadline:
                deadline = so.gift_host_poll(host, now)
            if now >= next_advert:
                n = so.gift_host_advert(host, plain, ctypes.byref(version))
                n = so.advert_frame_plain(ctypes.byref(self.advert), plain, n,
                                          (nonce + version.value) & 0xFFFFFFFF,
                                          ctypes.byref(CALLBACKS), frame)
                with self.board.air.lock:
                    self.board._raw_tx(frame.raw[:n])
                next_advert = now + 100_000

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(5)


# A retail FireRed's RTT request to the host (fb11): type 0, its system time, the host's var 0x00C6.
RETAIL_RTT_REQUEST = bytes.fromhex("0000002abe351015d6000000000004d447000000c6")


class _ArpOnly(dict):
    """A neighbour table filled by ARP replies alone."""

    def setdefault(self, key, default=None):
        return self.get(key, default)


@contextlib.contextmanager
def console_on_air(monkeypatch):
    """bin/frlg_mg_client.py's radio is a simulated board. As a console, it opens its Reliable
    stream at its own Session type 6 (`fb11`: 20 ms after it, before any RTT), and it resolves the
    host with an ARP, a broadcast (docs/ldn.md, A station's broadcasts)."""
    from ldn import wlan
    from pokeldn.ldn import esp32, esp32_sim, esp32_wlan, pia_connect, userspace_ip
    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    init = userspace_ip.Stack.__init__

    def console_stack(self, *args, **kwargs):
        init(self, *args, **kwargs)
        self.learned = _ArpOnly()
    monkeypatch.setattr(userspace_ip.Stack, "__init__", console_stack)
    monkeypatch.setattr(userspace_ip.Stack, "add_neighbor", lambda self, ip, mac: None)
    on_message = pia_connect.ConnectionManager.on_message

    seen = collections.Counter()

    def console_on_message(self, proto, payload, tick=None):
        if proto == pia_connect.PROTO_RTT and payload[:1] in (b"\x00", b"\x01"):
            seen["host rtt probe" if payload[0] == 0 else "host rtt answer"] += 1
        on_message(self, proto, payload, tick)
        if self.state == pia_connect.ST_FINALIZE and any(
                m["proto"] == pia_connect.PROTO_SESSION and m["payload"][:1] == b"\x06"
                for m in self._outbox):
            self.state = pia_connect.ST_CONNECTED
            # and probes the host's round trip with its own requests (fb11, 0.3 s after its type 6)
            self._last_host_rtt = RETAIL_RTT_REQUEST
    monkeypatch.setattr(pia_connect.ConnectionManager, "on_message", console_on_message)
    air = esp32_sim.Air()
    air.seen = seen
    radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())

    @contextlib.asynccontextmanager
    async def factory():
        esp = esp32_wlan.EspFactory(radio, port_factory=userspace_ip.userspace_port, join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()
    wlan.set_factory(factory)
    try:
        yield air
    finally:
        wlan.set_factory(None)
        radio.close()


def _image(argv, keys):
    import frlg_mg_host
    from pokeldn.frlg import config as configmod
    from pokeldn.frlg.gift import portable
    parser = frlg_mg_host.build_parser()
    args = parser.parse_args(["--live", "--no-local-config", *argv])
    config = frlg_mg_host.build_run_config(parser, args)
    plan = configmod.plan_builds(config.payload, config.console_build, config.console_version)
    return portable.build(config, plan, keys), config, plan


def _keys_file(tmp_path):
    from test_esp32 import KEYS
    path = tmp_path / "prod.keys"
    if not path.exists():
        path.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))
    return KEYS, str(path)


def _run_console(tmp_path, prefix, argv=(), board=None, left=1):
    """The client on this thread; it notices no LDN kick, so a board that ended the session ends it
    too, 3 s later, as an interrupt."""
    import _thread
    import frlg_mg_client
    _, keys_path = _keys_file(tmp_path)
    done = threading.Event()

    def watchdog():
        while not done.is_set():
            if board is not None and sum(e == EVENT_LEFT for e, _ in board.events) >= left:
                if not done.wait(3):
                    _thread.interrupt_main()
                return
            done.wait(0.1)
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        return frlg_mg_client.main(["--live", "--keys", keys_path, "--out", str(tmp_path / prefix),
                                    *argv])
    finally:
        done.set()


def _messages(tmp_path, prefix):
    import json
    with open(tmp_path / f"{prefix}_messages.jsonl") as f:
        return [json.loads(line) for line in f]


def _python_server(config, plan, messages):
    """What bin/frlg_mg_host.py's own server sends, given what this console sent: (ident, bytes as
    the console receives them) per message, and its result."""
    from pokeldn.frlg.gift import portable
    server = portable.application(config, plan).session.activity.server
    sent, said = [], iter(m for m in messages if m["dir"] == "out")
    while True:
        action = server.run()
        if action[0] == "send":
            ident, payload, size = action[1:]
            sent.append((ident, bytes(payload).ljust(size or 1024, b"\0")))
            server.on_sent()
        elif action[0] == "recv":
            m = next(said)
            server.on_received(m["ident"], bytes.fromhex(m["payload_hex"]))
        else:
            return sent, server.result


def _wait_left(board, count=1, seconds=15):
    deadline = time.monotonic() + seconds
    while sum(e == EVENT_LEFT for e, _ in board.events) < count and time.monotonic() < deadline:
        time.sleep(0.1)


@pytest.mark.parametrize("gift, console, result", [
    (["--gift", "celebi"], [], 2),                                    # SVR_MSG_CARD_SENT
    (["--gift", "celebi"], ["--holding-card", "1003"], 5),            # SVR_MSG_HAS_CARD
    (["--gift", "celebi"], ["--holding-card", "1009", "--keep-card"], 9),   # SVR_MSG_CLIENT_CANCELED
    (["--gift", "solrock-stamp"], [], 4),                             # SVR_MSG_STAMP_SENT
    (["--news"], [], 3),                                              # SVR_MSG_NEWS_SENT
])
def test_the_board_alone_plays_the_hosts_session(engine, tmp_path, monkeypatch, gift, console, result):
    keys, _ = _keys_file(tmp_path)
    image, config, plan = _image(gift, keys)
    with console_on_air(monkeypatch) as air:
        board = FirmwareBoard(engine, air, image)
        assert board.refused == 0
        try:
            _run_console(tmp_path, "got", console, board=board)
            _wait_left(board)
        finally:
            board.stop()
    messages = _messages(tmp_path, "got")
    received = [(m["ident"], bytes.fromhex(m["payload_hex"])) for m in messages if m["dir"] == "in"]
    expected, expected_result = _python_server(config, plan, messages)
    assert expected_result == result
    assert received == expected
    assert (EVENT_RESULT, result) in board.events
    assert (EVENT_LEFT, int(result in (2, 3, 4))) in board.events
    assert board.broadcasts >= 1                       # its ARP for the host, under the group key
    assert air.seen["host rtt answer"] >= 1 and air.seen["host rtt probe"] >= 1


def test_the_board_serves_the_next_console_after_one_leaves(engine, tmp_path, monkeypatch):
    keys, _ = _keys_file(tmp_path)
    image, _, plan = _image(["--gift", "celebi"], keys)
    with console_on_air(monkeypatch) as air:
        board = FirmwareBoard(engine, air, image)
        try:
            assert _run_console(tmp_path, "first", board=board) == 0
            _wait_left(board)
            assert _run_console(tmp_path, "second", ["--version", "firered", "--language", "french"],
                                board=board, left=2) == 0
            _wait_left(board, 2)
        finally:
            board.stop()
    first, second = (tmp_path / "first_card.bin").read_bytes(), (tmp_path / "second_card.bin").read_bytes()
    assert first == plan.per_build["BPGE"].card
    assert second == plan.per_build["BPRF"].card
    assert [e for e in board.events if e[0] == EVENT_LEFT] == [(EVENT_LEFT, 1), (EVENT_LEFT, 1)]


def test_a_cartridge_the_image_does_not_serve_is_refused_with_nothing_sent(engine, tmp_path, monkeypatch):
    keys, _ = _keys_file(tmp_path)
    image, _, _ = _image(["--gift", "celebi", "--console-build", "BPRF"], keys)
    with console_on_air(monkeypatch) as air:
        board = FirmwareBoard(engine, air, image)
        try:
            assert _run_console(tmp_path, "got", board=board) == 1   # an English LeafGreen
            _wait_left(board)
        finally:
            board.stop()
    received = [m["ident"] for m in _messages(tmp_path, "got") if m["dir"] == "in"]
    assert received == [16]                                     # the game-data request alone
    assert any(e == EVENT_REFUSED for e, _ in board.events)
    assert (EVENT_LEFT, 0) in board.events


def _save_with_launcher(tmp_path, monkeypatch, version, *argv):
    import frlg_mg_host
    from ldn import wlan
    from pokeldn.ldn import esp32, esp32_sim, esp32_wlan
    _, keys_path = _keys_file(tmp_path)
    sim = esp32_sim.SimulatedBoard(esp32_sim.Air())
    sim.version = version
    radio = esp32.Radio(sim.host_stream())
    monkeypatch.setattr(esp32_wlan, "_radio", radio)
    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    try:
        code = frlg_mg_host.main(["--live", "--no-local-config", "--keys", keys_path, "--save-to-board",
                                  *argv])
    finally:
        radio.close()
        wlan.set_factory(None)
    return code, sim


def test_the_launcher_keeps_a_gift_the_board_then_hosts_alone(engine, tmp_path, monkeypatch):
    """--save-to-board through the host link into the simulated board's flash, then that image, run
    by the board's own code, to a console."""
    code, sim = _save_with_launcher(tmp_path, monkeypatch, "1.9.0", "--gift", "celebi", "--channel", "6")
    assert code == 0 and sim.beacon
    keys, _ = _keys_file(tmp_path)
    _, _, plan = _image(["--gift", "celebi"], keys)
    with console_on_air(monkeypatch) as air:
        board = FirmwareBoard(engine, air, sim.beacon)
        assert board.refused == 0
        assert board.advert.channel == 6 and board.advert.display_count == 3   # card, sprite, delivered
        try:
            assert _run_console(tmp_path, "got", board=board) == 0
            _wait_left(board)
        finally:
            board.stop()
    assert (tmp_path / "got_card.bin").read_bytes() == plan.per_build["BPGE"].card
    ram = (tmp_path / "got_ramscript.bin").read_bytes()
    assert ram == plan.per_build["BPGE"].ram_script.ljust(1024, b"\0")


@pytest.mark.parametrize("version, argv, says", [
    ("1.8.0", ["--gift", "celebi"], "1.9.0"),
    ("1.9.0", ["--buffer-script", "trainer-id-probe"], "cannot be kept on the board"),
])
def test_what_the_board_cannot_host_is_refused_before_anything_is_stored(tmp_path, monkeypatch, capsys,
                                                                         version, argv, says):
    code, sim = _save_with_launcher(tmp_path, monkeypatch, version, *argv)
    assert code == 1 and not sim.beacon
    assert says in capsys.readouterr().err


@pytest.mark.parametrize("qos", [False, True])
def test_a_consoles_group_key_arp_gets_the_boards_answer(engine, tmp_path, qos):
    """FireRed opens with an ARP for the host, sent with no DS bits under the group key; an access
    point drops it and a host that does not answer is left (docs/ldn.md, A station's broadcasts)."""
    import struct
    from pokeldn.ldn import esp32_sim
    keys, _ = _keys_file(tmp_path)
    image, _, _ = _image(["--gift", "celebi"], keys)
    board = FirmwareBoard.__new__(FirmwareBoard)
    board.so = engine
    board.keep = ctypes.create_string_buffer(image, len(image))
    board.advert = Image()
    assert engine.advert_parse(board.keep, len(image), ctypes.byref(board.advert)) == 0
    board.gift = ctypes.create_string_buffer(engine.gift_image_size())
    assert engine.gift_parse(ctypes.byref(board.advert), board.gift) == 0
    board.board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    board.board.bssid, board.board.key = image[9:15], image[47:63]
    board.broadcasts = 0 if qos else 1
    sent = []
    platform = Platform(SHA(_sha), HMAC(_hmac), BLOCK(_block), BLOCK(_encrypt_block), GCM(_seal), GCM(_open),
                        RANDOM(lambda _: 4), SEND(lambda _, f, n: sent.append(_read(f, n))), KICK(lambda *a: None),
                        EVENT(lambda *a: None), None)
    memory = ctypes.create_string_buffer(engine.gift_host_size())
    host = engine.gift_host_start(memory, board.gift, ctypes.byref(platform), _now_us())
    plain = ctypes.create_string_buffer(1024)
    engine.gift_host_advert(host, plain, ctypes.byref(ctypes.c_uint32()))
    console, host_ip = bytes.fromhex("48f1eb209b22"), plain.raw[40:44]   # the host's station entry
    arp = struct.pack("!HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 1, console, host_ip[:3] + b"\x02", bytes(6), host_ip)
    raw = board._on_air(b"\xff" * 6 + console + b"\x08\x06" + arp)
    assert (raw[0] & 0x80) == (0x80 if qos else 0)
    engine.gift_host_rx_80211(host, raw, len(raw), _now_us())
    assert len(sent) == 1
    reply = sent[0]
    assert reply[:6] == console and reply[6:12] == image[9:15] and reply[12:14] == b"\x08\x06"
    assert reply[14 + 6:14 + 8] == b"\x00\x02" and reply[14 + 14:14 + 18] == host_ip
    tampered = raw[:-1] + bytes([raw[-1] ^ 1])               # a MIC that does not match
    engine.gift_host_rx_80211(host, tampered, len(tampered), _now_us())
    assert len(sent) == 1

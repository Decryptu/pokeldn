"""The portable beacon: the board's frame builder (firmware/esp32/main/advert.c, compiled here)
against the frames the host itself sends for the same network, and a Sword/Shield gift reassembled
from them as the console reassembles it."""
import ctypes
import hashlib
import os
import shutil
import subprocess
import zlib

import pytest
from Crypto.Cipher import AES

import ldn
from ldn import wlan
from pokeldn.ldn import portable
from pokeldn.swsh import COMM_ID, PASSPHRASE, beacon, wc8

SOURCE = os.path.join(os.path.dirname(__file__), "..", "firmware", "esp32", "main", "advert.c")
KEYS = {name: hashlib.sha256(name.encode()).digest()[:16] for name in
        ("master_key_00", "master_key_12", "aes_kek_generation_source", "aes_key_generation_source")}

SHA = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)
CTR = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_size_t)
GCM = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.c_void_p)


class Image(ctypes.Structure):
    _fields_ = [("channel", ctypes.c_uint8), ("bssid", ctypes.c_uint8 * 6),
                ("ssid", ctypes.c_uint8 * 32), ("data_key", ctypes.c_uint8 * 16),
                ("max_stations", ctypes.c_uint8), ("advertise_key", ctypes.c_uint8 * 16),
                ("header", ctypes.c_uint8 * 40), ("interval_ms", ctypes.c_uint16),
                ("dwell_ms", ctypes.c_uint16), ("count", ctypes.c_uint8),
                ("display_count", ctypes.c_uint8), ("plain", ctypes.c_void_p * 8),
                ("plain_len", ctypes.c_uint16 * 8), ("display", ctypes.c_void_p * 4),
                ("display_len", ctypes.c_uint16 * 4)]


class Crypto(ctypes.Structure):
    _fields_ = [("sha256", SHA), ("aes_ctr", CTR), ("aes_gcm", GCM)]


def _read(address, n):
    return ctypes.string_at(address, n)


def _sha(data, n, out):
    ctypes.memmove(out, hashlib.sha256(_read(data, n)).digest(), 32)
    return 0


def _ctr(key, counter, src, dst, n):
    cipher = AES.new(_read(key, 16), AES.MODE_CTR, nonce=b"", initial_value=_read(counter, 16))
    ctypes.memmove(dst, cipher.encrypt(_read(src, n)), n)
    return 0


def _gcm(key, iv, aad, aad_n, src, dst, n, tag):
    cipher = AES.new(_read(key, 16), AES.MODE_GCM, nonce=_read(iv, 12))
    cipher.update(_read(aad, aad_n))
    out, mac = cipher.encrypt_and_digest(_read(src, n))
    ctypes.memmove(dst, out, n)
    ctypes.memmove(tag, mac, 16)
    return 0


CALLBACKS = Crypto(SHA(_sha), CTR(_ctr), GCM(_gcm))


@pytest.fixture(scope="module")
def board(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler")
    lib = tmp_path_factory.mktemp("advert") / "advert.so"
    subprocess.run([cc, "-shared", "-fPIC", "-O1", "-Wall", "-Werror", "-o", str(lib), SOURCE],
                   check=True)
    so = ctypes.CDLL(str(lib))
    so.advert_parse.argtypes = (ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(Image))
    so.advert_frame.argtypes = (ctypes.POINTER(Image), ctypes.c_uint, ctypes.c_uint32,
                                ctypes.POINTER(Crypto), ctypes.c_char_p)
    so.advert_frame.restype = ctypes.c_size_t
    return so


class Board:
    def __init__(self, so, image: bytes):
        self.so, self.keep = so, ctypes.create_string_buffer(image, len(image))
        self.image = Image()
        self.refused = so.advert_parse(self.keep, len(image), ctypes.byref(self.image))

    def frame(self, index, nonce):
        out = ctypes.create_string_buffer(24 + 12 + 40 + 32 + 0x500)
        n = self.so.advert_frame(ctypes.byref(self.image), index, nonce, ctypes.byref(CALLBACKS), out)
        assert n
        return out.raw[:n]


def _record():
    return wc8.pokemon_card(species=25, level=25, form=0, moves=(84, 45, 86, 98),
                            nickname="PKCAMP", ot="POKELDN", card_id=0x270F, region_mask=0xFFFF,
                            ribbons=(), ot_gender=2, gender=0)


def _network(protocol):
    return portable.network(KEYS, local_communication_id=COMM_ID, scene_id=0, app_version=4,
                            protocol=protocol, password=PASSPHRASE, name=b"POKELDN")


def _host_frames(net, derivation, fragments, count):
    """What the host sends: its first advertisement, then one per set_application_data."""
    out = []
    for i in range(count):
        if i:
            net.set_application_data(fragments[i % len(fragments)])
        else:
            net.info().application_data = fragments[0]
        action = wlan.ActionFrame()
        action.source = net.info().address
        action.action = net.info().build_advertisement(derivation).encode()
        out.append(action.encode())
    return out


@pytest.mark.parametrize("protocol", (1, 3))
def test_board_frames_are_the_hosts(board, protocol):
    fragments = beacon.build_message(_record())
    net, derivation, key = _network(protocol)
    image = portable.build(net, derivation, key, fragments)
    expected = _host_frames(net, derivation, fragments, 7)
    b = Board(board, image)
    assert b.refused == 0
    first = int.from_bytes(image[116:120], "big")
    got = [b.frame(i % len(fragments), (first + i) & 0xFFFFFFFF) for i in range(7)]
    assert got == expected


def test_console_reassembles_the_gift(board):
    """Decrypted with the advertise key a console derives and reassembled as the console does."""
    record = _record()
    fragments = beacon.build_message(record)
    net, derivation, key = _network(1)
    image = portable.build(net, derivation, key, fragments)
    b = Board(board, image)
    first = int.from_bytes(image[116:120], "big")
    datas = []
    for i in range(len(fragments)):
        action = wlan.ActionFrame()
        action.decode(b.frame(i, first + i))
        frame = ldn.AdvertisementFrame(ldn.KeyDerivation(KEYS, 1), 1)
        frame.decode(action.action)
        assert frame.network_id.local_communication_id == COMM_ID
        datas.append(frame.payload.application_data)
    assert beacon.reassemble(datas) == record


def test_board_refuses_a_damaged_image(board):
    fragments = beacon.build_message(_record())
    image = bytearray(portable.build(*_network(1), fragments))
    assert Board(board, bytes(image[:-1])).refused == 1
    image[200] ^= 1
    assert Board(board, bytes(image)).refused == 4
    image[200] ^= 1
    image[124] = 9                                     # nine fragments, CRC resealed
    image[-4:] = zlib.crc32(bytes(image[:-4])).to_bytes(4, "little")
    assert Board(board, bytes(image)).refused == 5


def _launcher(tmp_path, monkeypatch, version, *extra):
    import swsh_gift_host
    from pokeldn.ldn import esp32, esp32_sim, esp32_wlan
    keys = tmp_path / "prod.keys"
    keys.write_text("".join(f"{name} = {value.hex()}\n" for name, value in KEYS.items()))
    board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    board.version = version
    radio = esp32.Radio(board.host_stream())
    monkeypatch.setattr(esp32_wlan, "_radio", radio)
    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    try:
        code = swsh_gift_host.main(["--species", "151", "--level", "10", "--nickname", "MEW",
                                    "--keys", str(keys), *extra])
    finally:
        radio.close()
        wlan.set_factory(None)     # esp32_wlan.use routes every later LDN call in this process
    return code, board


def test_the_launcher_saves_a_gift_the_board_sends_alone(board, tmp_path, monkeypatch):
    """--save-to-board through the host link to the simulated board's flash; the stored image,
    run by the board's own builder, carries the same record --dump writes."""
    fixed = wc8.pack_date()           # each run dates the record when it sends; keep one date
    monkeypatch.setattr(wc8, "pack_date", lambda t=None: fixed)
    code, _ = _launcher(tmp_path, monkeypatch, "1.8.0", "--dump", str(tmp_path / "card.wc8"))
    assert code == 0
    code, sim = _launcher(tmp_path, monkeypatch, "1.8.0", "--save-to-board", "--channel", "11")
    assert code == 0 and sim.beacon
    b = Board(board, sim.beacon)
    assert b.refused == 0 and b.image.channel == 11
    first = int.from_bytes(sim.beacon[116:120], "big")
    datas = []
    for i in range(b.image.count):
        action = wlan.ActionFrame()
        action.decode(b.frame(i, first + 40 + i))
        frame = ldn.AdvertisementFrame(ldn.KeyDerivation(KEYS, 1), 1)
        frame.decode(action.action)
        datas.append(frame.payload.application_data)
    assert beacon.reassemble(datas) == (tmp_path / "card.wc8").read_bytes()
    assert b.image.display_count == 2                 # the gift's sprite and its card


def test_firmware_without_the_beacon_is_told_to_update(tmp_path, monkeypatch, capsys):
    code, sim = _launcher(tmp_path, monkeypatch, "1.7.1", "--save-to-board")
    assert code == 1 and not sim.beacon
    assert "1.8.0" in capsys.readouterr().err

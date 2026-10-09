"""The classic ESP32's Pro Controller encoding (firmware/pad/main/pro_report.c), compiled and run on the
host, against the bit layout in dekuNukem's bluetooth_hid_notes.md and spi_flash_notes.md."""
import ctypes
import shutil
import subprocess
from pathlib import Path

import pytest

from pokeldn.pad import macro

SOURCE = Path(__file__).resolve().parents[1] / "firmware" / "pad" / "main" / "pro_report.c"


@pytest.fixture(scope="module")
def pro(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler")
    lib = tmp_path_factory.mktemp("pro") / "pro.so"
    subprocess.run([cc, "-shared", "-fPIC", "-O1", "-o", str(lib), str(SOURCE)], check=True)
    so = ctypes.CDLL(str(lib))
    so.pro_spi_byte.restype = ctypes.c_uint8

    def state(report: bytes, timer: int = 7) -> bytes:
        out = ctypes.create_string_buffer(12)
        so.pro_state(ctypes.c_char_p(report), ctypes.c_uint8(timer), out)
        return out.raw

    def spi(address: int, length: int) -> bytes:
        return bytes(so.pro_spi_byte(ctypes.c_uint32(address + i)) for i in range(length))
    return state, spi


@pytest.mark.parametrize("keys, byte, bits", [
    (["Y"], 2, 0x01), (["X"], 2, 0x02), (["B"], 2, 0x04), (["A"], 2, 0x08), (["R"], 2, 0x40), (["ZR"], 2, 0x80),
    (["MINUS"], 3, 0x01), (["PLUS"], 3, 0x02), (["RSTICK"], 3, 0x04), (["LSTICK"], 3, 0x08),
    (["HOME"], 3, 0x10), (["CAPTURE"], 3, 0x20),
    (["DOWN"], 4, 0x01), (["UP"], 4, 0x02), (["RIGHT"], 4, 0x04), (["LEFT"], 4, 0x08),
    (["L"], 4, 0x40), (["ZL"], 4, 0x80), (["UPRIGHT"], 4, 0x06), (["DOWNLEFT"], 4, 0x09),
])
def test_each_button_lands_on_its_documented_bit(pro, keys, byte, bits):
    state, _ = pro
    out = state(macro.state(keys))
    assert out[byte] == bits
    assert all(out[b] == 0 for b in (2, 3, 4) if b != byte)


def test_rest_and_full_tilt_pack_as_twelve_bit_pairs(pro):
    state, _ = pro
    rest = state(macro.NEUTRAL, timer=0x41)
    assert rest[:2] == bytes([0x41, 0x8E]) and rest[11] == 0x80
    assert rest[5:8] == rest[8:11] == bytes.fromhex("000880")     # x = y = 0x800

    def unpack(p):
        return p[0] | (p[1] & 0x0F) << 8, p[1] >> 4 | p[2] << 4
    assert unpack(state(macro.state(left=(-1, 0)))[5:8]) == (0x800 - 0x700, 0x800)
    assert unpack(state(macro.state(left=(0, 1)))[5:8]) == (0x800, 0x800 + 0x700)     # HID 0 is up
    # HID 255 is 127 steps of 128 to the right and down
    assert unpack(state(macro.state(right=(1, -1)))[8:11]) == (0x800 + 0x6F2, 0x800 - 0x6F2)


def test_calibration_matches_the_report_centre_and_range(pro):
    _, spi = pro
    left, right = spi(0x603D, 9), spi(0x6046, 9)

    def twelve(c):
        return [c[0] | (c[1] & 0xF) << 8, c[1] >> 4 | c[2] << 4,
                c[3] | (c[4] & 0xF) << 8, c[4] >> 4 | c[5] << 4,
                c[6] | (c[7] & 0xF) << 8, c[7] >> 4 | c[8] << 4]
    # left: max above, centre, min below; right: centre, min below, max above
    assert twelve(left) == [0x700, 0x700, 0x800, 0x800, 0x700, 0x700]
    assert twelve(right) == [0x800, 0x800, 0x700, 0x700, 0x700, 0x700]
    assert spi(0x6000, 16) == b"\xff" * 16            # no serial number
    assert spi(0x8010, 24) == b"\xff" * 24            # no user calibration
    assert spi(0x6098, 18) == spi(0x6086, 18)

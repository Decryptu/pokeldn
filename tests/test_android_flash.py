import json
import subprocess
import sys

# A fresh interpreter: install() rewrites serial and esp_pylib for the whole process.
SCRIPT = r'''
import json, sys, types
class Bridge:
    deviceVendorId = staticmethod(lambda: VID)
    deviceProductId = staticmethod(lambda: PID)
    deviceName = staticmethod(lambda: "board")
    usbState = staticmethod(lambda: "ready")
sys.modules["java"] = types.SimpleNamespace(jclass=lambda name: Bridge)
from pokeldn.app import android
android.install()
lines = []
class Usb:
    def setLines(self, dtr, rts): lines.append((dtr, rts))
    def close(self): pass
port = android.Serial.__new__(android.Serial)
android.SerialBase.__init__(port)
port._usb, port.is_open, port._port, port.name = Usb(), True, android.PORT, android.PORT
from esptool.loader import ESPLoader
loader = ESPLoader.__new__(ESPLoader)
loader._port, loader.cache, loader.CHIP_NAME = port, {"usb_vid": None, "usb_pid": None}, "ESP32"
strategy = loader._construct_reset_strategy_sequence("default-reset")[0]
strategy()
print(json.dumps([type(strategy).__name__, lines]))
'''


def _first_reset(vid: int, pid: int):
    run = subprocess.run([sys.executable, "-c", f"VID, PID = {vid}, {pid}\n" + SCRIPT],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    name, lines = json.loads(run.stdout)
    return name, [tuple(pair) for pair in lines]


def test_android_board_resets_into_the_loader():
    """esptool's first reset on android://board reaches the USB lines. It once lacked the port's ids
    (a native USB chip got the classic reset) and then wrote a CP210x's lines through fileno()."""
    name, lines = _first_reset(0x303A, 0x1001)
    assert name == "USBJTAGSerialReset" and lines[-1] == (False, False)
    name, lines = _first_reset(0x10C4, 0xEA60)
    # (DTR, RTS) asserted: EN held low with IO0 high, then EN released with IO0 low, the ROM loader.
    entry = lines.index((False, True))
    assert name == "UnixTightReset" and lines[entry + 1] == (True, False)

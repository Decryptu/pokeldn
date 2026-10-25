import subprocess
import sys

# A fresh interpreter: install() rewrites serial and esp_pylib for the whole process.
SCRIPT = r'''
import sys, types
class Bridge:
    deviceVendorId = staticmethod(lambda: VID)
    deviceProductId = staticmethod(lambda: PID)
    deviceName = staticmethod(lambda: "board")
    usbState = staticmethod(lambda: "ready")
sys.modules["java"] = types.SimpleNamespace(jclass=lambda name: Bridge)
from pokeldn.app import android
android.install()
from esptool.loader import ESPLoader
from esptool.reset import USBJTAGSerialReset
loader = ESPLoader.__new__(ESPLoader)
loader._port = types.SimpleNamespace(port=android.PORT, name=android.PORT)
loader.cache = {"usb_vid": None, "usb_pid": None}
loader.CHIP_NAME = "ESP32-S3"
sequence = loader._construct_reset_strategy_sequence("default-reset")
print(all(isinstance(step, USBJTAGSerialReset) for step in sequence))
'''


def _usb_reset(vid: int, pid: int) -> str:
    return subprocess.run([sys.executable, "-c", f"VID, PID = {vid}, {pid}\n" + SCRIPT],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_android_native_usb_board_flashes_through_the_usb_jtag_reset():
    """esptool resets android://board as the bridge's ids say; it refused a URL port's ids and gave
    an S3, C3 or C6 the classic reset, which never reaches the loader."""
    assert _usb_reset(0x303A, 0x1001) == "True"
    assert _usb_reset(0x10C4, 0xEA60) == "False"

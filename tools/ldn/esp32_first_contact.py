#!/usr/bin/env python3
"""First contact with an ESP32 radio board: optionally flash it, then HELLO, STATUS, and an idle
scan that counts the LDN advertisements arriving per channel and, given prod.keys, decodes them
with the LDN library running on the board. docs/hardware_esp32.md.

    ./.venv/bin/python tools/ldn/esp32_first_contact.py --flash
    ./.venv/bin/python tools/ldn/esp32_first_contact.py --port PORT --keys ~/prod.keys
"""
import argparse
import collections
import glob
import os
import subprocess
import sys
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "vendor", "LDN"))

from pokeldn.ldn import esp32  # noqa: E402

BUILD_DIR = os.path.join(PROJECT_ROOT, "scratchpad", "esp", "build-radio")
PORT_PATTERNS = ("/dev/cu.usbserial-*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*",
                 "/dev/ttyUSB*", "/dev/ttyACM*")


def find_port() -> str | None:
    ports = sorted(p for pattern in PORT_PATTERNS for p in glob.glob(pattern))
    return ports[0] if len(ports) == 1 else None


def flash(port: str, build_dir: str = BUILD_DIR, log=print) -> None:
    """esptool from the ESP-IDF Python env, with the build's own flash_args."""
    envs = sorted(glob.glob(os.path.join(PROJECT_ROOT, "scratchpad", "esp", "idf-tools",
                                         "python_env", "*", "bin", "python")))
    python = envs[-1] if envs else sys.executable
    cmd = [python, "-m", "esptool", "--chip", "esp32", "-p", port, "-b", "460800",
           "--before", "default-reset", "--after", "hard-reset", "write-flash", "@flash_args"]
    log("[flash] " + " ".join(cmd))
    subprocess.run(cmd, cwd=build_dir, check=True)


def idle_scan(radio: esp32.Radio, channels, dwell: float, log=print) -> dict:
    """-> {channel: Counter(source MAC -> advertisement count)}; the board stays idle."""
    seen = {c: collections.Counter() for c in channels}
    current = [None]
    lock = threading.Lock()

    def on_frame(msg_type, payload):
        if msg_type != esp32.MSG_RX_MGMT:
            return
        mgmt = esp32.ManagementFrame.parse(payload)
        with lock:
            if current[0] is not None:
                seen[current[0]][mgmt.frame[10:16].hex(":")] += 1

    radio.subscribe(on_frame)
    try:
        for channel in channels:
            radio.set_channel(channel)
            with lock:
                current[0] = channel
            time.sleep(dwell)
            with lock:
                current[0] = None
            total = sum(seen[channel].values())
            log(f"[scan] channel {channel:2d}: {total} LDN action frame(s) from "
                f"{len(seen[channel])} source(s) {dict(seen[channel]) or ''}")
    finally:
        radio.unsubscribe(on_frame)
    return seen


def decode_networks(radio: esp32.Radio, keys: dict, channels, dwell: float, log=print) -> list:
    """The LDN library's own scan, on the board: the advertisements decrypted and parsed."""
    import trio
    import ldn
    from pokeldn.ldn import esp32_wlan

    esp32_wlan.use(radio=radio)
    networks = trio.run(lambda: ldn.scan(keys, channels=list(channels), dwell_time=dwell))
    for net in networks:
        log(f"[ldn] comm_id={net.local_communication_id:#018x} scene={net.scene_id} "
            f"channel={net.channel} bssid={net.address} "
            f"players={net.num_participants}/{net.max_participants} "
            f"app_data={len(net.application_data)}B")
    return networks


def first_contact(radio: esp32.Radio, channels=(1, 6, 11), dwell: float = 2.0, keys=None,
                  log=print) -> dict:
    info = radio.hello()
    log(f"[hello] protocol {info.version}, sta {bytes(info.sta_mac).hex(':')}, "
        f"ap {bytes(info.ap_mac).hex(':')}, chip rev {info.chip_revision}, {info.text}")
    if info.version != esp32.PROTOCOL_VERSION:
        log(f"[hello] the host speaks protocol {esp32.PROTOCOL_VERSION}; reflash the board")
    log(f"[status] {radio.status()}")
    seen = idle_scan(radio, channels, dwell, log)
    networks = decode_networks(radio, keys, channels, dwell, log) if keys else None
    log(f"[status] {radio.status()}")
    return {"info": info, "seen": seen, "networks": networks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="serial port (default: the only USB serial port present)")
    ap.add_argument("--flash", action="store_true", help=f"flash {BUILD_DIR} first")
    ap.add_argument("--channels", default="1,6,11")
    ap.add_argument("--dwell", type=float, default=2.0, help="seconds per channel")
    ap.add_argument("--keys", help="prod.keys, to decode the advertisements with the LDN library")
    ap.add_argument("--baud", type=int, default=921600, help="the rate after HELLO (0 keeps 115200)")
    args = ap.parse_args(argv)

    port = args.port or find_port()
    if port is None:
        print("no single USB serial port found; pass --port", file=sys.stderr)
        return 2
    if args.flash:
        flash(port)
        time.sleep(1.0)
    keys = None
    if args.keys:
        import ldn
        keys = ldn.load_keys(os.path.expanduser(args.keys))
    radio = esp32.Radio.open_serial(port, fast_baud=args.baud or None, log=print)
    try:
        first_contact(radio, [int(c) for c in args.channels.split(",")], args.dwell, keys)
    finally:
        radio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

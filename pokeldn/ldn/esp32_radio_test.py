"""The Board page's radio test: what a board hears on the LDN channels, and a visible test network a
phone can look for (docs/hardware_esp32.md, The radio test)."""
import os
import struct
import threading
import time
from dataclasses import dataclass, field

from pokeldn.ldn import esp32

CHANNELS = (1, 6, 11)   # the channels a Switch hosts local play on
TEST_SSID = b"POKELDN-TEST"


@dataclass
class Channel:
    channel: int
    switches: dict = field(default_factory=dict)        # transmitter MAC -> best RSSI of its LDN advertisements
    access_points: dict = field(default_factory=dict)   # transmitter MAC -> best RSSI of its beacons
    frames: int = 0
    damaged: int = 0
    noise: list = field(default_factory=list)


SETTLE = 0.1


def hear(radio: esp32.Radio, channels=CHANNELS, dwell: float = 3.0) -> list[Channel]:
    """Per channel: `dwell` seconds idle (LDN advertisements reach the host as RX_MGMT), then
    `dwell` seconds of census (every frame's first 16 bytes, RSSI and noise floor)."""
    results, current, lock = [], None, threading.Lock()

    def received(msg_type: int, payload: bytes) -> None:
        with lock:
            if current is None:
                return
            if msg_type == esp32.MSG_RX_MGMT and len(payload) >= 2 + 16 and payload[2] == 0xD0:
                rssi = struct.unpack("b", payload[1:2])[0]
                mac = payload[2 + 10:2 + 16].hex(":")
                current.switches[mac] = max(rssi, current.switches.get(mac, -128))
            elif msg_type == esp32.MSG_RX_CENSUS and len(payload) >= 13:
                rssi, noise, state = struct.unpack("bbB", payload[4:7])
                current.frames += 1
                current.noise.append(noise)
                if state:
                    current.damaged += 1
                elif len(payload) >= 13 + 16 and payload[13] == 0x80:
                    mac = payload[13 + 10:13 + 16].hex(":")
                    current.access_points[mac] = max(rssi, current.access_points.get(mac, -128))

    radio.subscribe(received)
    try:
        for channel in channels:
            radio.stop()
            radio.set_channel(channel)
            time.sleep(SETTLE)              # a frame of the last channel can still be on its way up
            with lock:
                current = Channel(channel)
            time.sleep(dwell)
            radio.sniff(channel, "ff:ff:ff:ff:ff:ff")
            time.sleep(dwell)
            radio.stop()
            with lock:
                results.append(current)
                current = None
    finally:
        radio.unsubscribe(received)
    return results


def beacon_frame(bssid: bytes, channel: int, sequence: int = 0) -> bytes:
    """An open 11b/g network's beacon named TEST_SSID. A Mac's scan lists it only with a running
    timestamp and the TIM element; a beacon with neither is dropped."""
    header = b"\x80\x00\x00\x00" + b"\xff" * 6 + bssid + bssid + struct.pack("<H", (sequence & 0xFFF) << 4)
    body = struct.pack("<QHH", 1_000_000 + sequence * 102_400, 100, 0x0401)   # TSF, 100 TU, ESS + short slot
    elements = (bytes([0, len(TEST_SSID)]) + TEST_SSID
                + b"\x01\x08\x82\x84\x8b\x96\x0c\x12\x18\x24" + bytes([3, 1, channel])
                + b"\x05\x04\x00\x01\x00\x00" + b"\x2a\x01\x00" + b"\x32\x04\x30\x48\x60\x6c")
    return header + body + elements


def show_network(radio: esp32.Radio, seconds: float, power: int = 0, channel: int = 6,
                 stop: threading.Event | None = None) -> int:
    """Hosts a hidden access point at `power` (0.25 dBm, 0 the driver's maximum) and sends a visible
    TEST_SSID beacon from it every 100 ms until `seconds` pass or `stop` is set. -> beacons sent."""
    bssid = bytearray(os.urandom(6))
    bssid[0] = (bssid[0] & 0xFC) | 0x02
    radio.ap_start(channel, bytes(bssid), os.urandom(16).hex(), os.urandom(16), power=power)
    # Its own BSSID: a scan merges it into the hidden network's entry otherwise.
    shown = bytes(bssid[:5]) + bytes([bssid[5] ^ 0x01])
    sent, end = 0, time.monotonic() + seconds
    try:
        while time.monotonic() < end and not (stop and stop.is_set()):
            radio.send_raw(beacon_frame(shown, channel, sent))
            sent += 1
            time.sleep(0.1)
    finally:
        radio.stop()
    return sent


def summary(channels: list[Channel]) -> list[str]:
    """One line per channel, then the verdict, in a player's words."""
    lines = []
    for c in channels:
        noise = sorted(c.noise)[len(c.noise) // 2] if c.noise else None
        switches = ", ".join(f"{mac} at {rssi} dBm" for mac, rssi in sorted(c.switches.items(), key=lambda i: -i[1]))
        best_ap = max(c.access_points.values(), default=None)
        lines.append(f"channel {c.channel}: {len(c.switches)} Switch{'' if len(c.switches) == 1 else 'es'}"
                     + (f" ({switches})" if switches else "")
                     + f", {len(c.access_points)} Wi-Fi network{'' if len(c.access_points) == 1 else 's'}"
                     + (f" (strongest {best_ap} dBm)" if best_ap is not None else "")
                     + f", {c.frames} frames, {c.damaged} damaged"
                     + (f", noise {noise} dBm" if noise is not None else ""))
    heard_switch = any(c.switches for c in channels)
    heard_wifi = any(c.access_points or c.frames for c in channels)
    if heard_switch:
        lines.append("The board hears a Switch.")
    elif heard_wifi:
        lines.append("The board hears Wi-Fi but no Switch: is the console waiting in a local play menu?")
    else:
        lines.append("The board heard nothing at all: its receiver or antenna may be faulty.")
    return lines

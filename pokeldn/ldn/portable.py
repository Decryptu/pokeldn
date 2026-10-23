"""The portable beacon: an LDN advertisement cycle the board stores and sends with no host
(`firmware/esp32/main/advert.c`, docs/hardware_esp32.md, Portable beacon). The image carries the
network the host would create and the keys derived for it, never `prod.keys`.
"""
import secrets
import struct
import zlib

import ldn
from ldn import wlan

MAGIC = b"PKSA"
LAYOUT = 1
KIND_CYCLE = 1
IMAGE_MAX = 12288
FRAGMENTS_MAX = 8
DISPLAY_MAX = 4
HEADER_LEN = 40


class _Address:
    def __init__(self, mac: wlan.MACAddress):
        self._mac = mac

    def address(self) -> wlan.MACAddress:
        return self._mac


def network(keys: dict, *, local_communication_id: int, scene_id: int, app_version: int,
            protocol: int, password: bytes, name: bytes, max_participants: int = 8,
            channel: int = 6, bssid: bytes | None = None, ssid: bytes | None = None,
            server_random: bytes | None = None) -> tuple[ldn.APNetwork, ldn.KeyDerivation, bytes]:
    """The network `ldn.create_network` would build for these parameters, with its key derivation
    and its data key; `ldn.APNetwork` itself fills the advertisement."""
    param = ldn.CreateNetworkParam()
    param.keys = keys
    param.protocol = protocol
    param.local_communication_id = local_communication_id
    param.scene_id = scene_id
    param.app_version = app_version
    param.max_participants = max_participants
    param.accept_policy = ldn.ACCEPT_ALL
    param.password = password
    param.name = name
    param.channel = channel
    param.ssid = ssid or secrets.token_bytes(16)
    param.server_random = server_random or secrets.token_bytes(16)
    param.check()
    derivation = ldn.KeyDerivation(keys, protocol)
    data_key = derivation.derive_data_key(param.server_random, password)
    # A locally administered unicast address, as the board's access point takes for a run.
    mac = bytearray(bssid or secrets.token_bytes(6))
    mac[0] = (mac[0] & 0xFC) | 0x02
    net = ldn.APNetwork(_Address(wlan.MACAddress(bytes(mac))), None, None, param, derivation, data_key)
    return net, derivation, data_key


def _plain(frame: ldn.AdvertisementFrame) -> bytes:
    return frame._make_payload_encoder().encode(frame.payload)


def build(net: ldn.APNetwork, derivation: ldn.KeyDerivation, data_key: bytes,
          fragments: list[bytes], *, interval_ms: int = 100, dwell_ms: int = 500,
          display: list[bytes] = ()) -> bytes:
    """The image: the access point, the advertisement header with its first nonce, one payload per
    fragment and up to four DISPLAY commands the board replays at start."""
    if not 1 <= len(fragments) <= FRAGMENTS_MAX:
        raise ValueError(f"{len(fragments)} fragments; the board stores 1 to {FRAGMENTS_MAX}")
    if len(display) > DISPLAY_MAX:
        raise ValueError(f"{len(display)} screen commands; the board replays at most {DISPLAY_MAX}")
    if not 20 <= interval_ms <= 1000 or dwell_ms < interval_ms:
        raise ValueError("the interval is 20 to 1000 ms and no longer than the dwell")
    info = net.info()
    plains, first = [], None
    for data in fragments:
        info.application_data = bytes(data)
        frame = info.build_advertisement(derivation)
        if first is None:
            first = frame
        plains.append(_plain(frame))
    head = (first.network_id.encode(">") + bytes((first.version, first.format)) + bytes(2)
            + first.nonce)
    assert len(head) == HEADER_LEN
    ssid = info.ssid.hex().encode("ascii")
    body = bytearray()
    body += MAGIC + bytes((LAYOUT, KIND_CYCLE)) + bytes(2)
    body += bytes((info.channel,)) + bytes(info.address) + ssid + data_key
    body += bytes((info.max_participants,))
    body += derivation.derive_advertise_key(first.network_id.encode(">")) + head
    body += struct.pack("<HHBBH", interval_ms, dwell_ms, len(plains), len(display), 0)
    assert len(body) == 128
    for blob in (*plains, *display):
        body += struct.pack("<H", len(blob)) + blob
    struct.pack_into("<H", body, 6, len(body) + 4)
    body += struct.pack("<I", zlib.crc32(body))
    if len(body) > IMAGE_MAX:
        raise ValueError(f"the image is {len(body)} bytes; the board stores at most {IMAGE_MAX}")
    return bytes(body)


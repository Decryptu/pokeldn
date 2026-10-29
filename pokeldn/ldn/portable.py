"""The portable beacon: an LDN advertisement cycle the board stores and sends with no host
(`firmware/esp32/main/advert.c`, docs/hardware_esp32.md, Portable beacon). The image carries the
network the host would create and the keys derived for it, never `prod.keys`.
"""
import secrets
import struct
import zlib

from Crypto.Cipher import AES

import ldn
from ldn import wlan

MAGIC = b"PKSA"
LAYOUT = 1
KIND_CYCLE = 1
KIND_HOST = 2
IMAGE_MAX = 12288
FRAGMENTS_MAX = 8
DISPLAY_MAX = 4
HEADER_LEN = 40
# The AES-GCM advertisement's plaintext: 40 bytes before the stations, 48 a station.
V2_PREFIX = 40
V2_STATION = 48
AUTH_KEY_SOURCE = bytes.fromhex("f1e7018419a84f711da714c2cf919c9c")
RECORD_LDN = 1
RECORD_PIA = 2


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


def _head(net: ldn.APNetwork, derivation: ldn.KeyDerivation, data_key: bytes, kind: int,
          interval_ms: int, dwell_ms: int, count: int, display: list[bytes]) -> bytearray:
    """The 128 bytes every image opens with."""
    if len(display) > DISPLAY_MAX:
        raise ValueError(f"{len(display)} screen commands; the board replays at most {DISPLAY_MAX}")
    if not 20 <= interval_ms <= 1000 or dwell_ms < interval_ms:
        raise ValueError("the interval is 20 to 1000 ms and no longer than the dwell")
    info = net.info()
    first = info.build_advertisement(derivation)
    head = (first.network_id.encode(">") + bytes((first.version, first.format)) + bytes(2)
            + first.nonce)
    assert len(head) == HEADER_LEN
    body = bytearray()
    body += MAGIC + bytes((LAYOUT, kind)) + bytes(2)
    body += bytes((info.channel,)) + bytes(info.address) + info.ssid.hex().encode("ascii") + data_key
    body += bytes((info.max_participants,))
    body += derivation.derive_advertise_key(first.network_id.encode(">")) + head
    body += struct.pack("<HHBBH", interval_ms, dwell_ms, count, len(display), 0)
    assert len(body) == 128
    return body


def _close(body: bytearray) -> bytes:
    struct.pack_into("<H", body, 6, len(body) + 4)
    body += struct.pack("<I", zlib.crc32(body))
    if len(body) > IMAGE_MAX:
        raise ValueError(f"the image is {len(body)} bytes; the board stores at most {IMAGE_MAX}")
    return bytes(body)


def build(net: ldn.APNetwork, derivation: ldn.KeyDerivation, data_key: bytes,
          fragments: list[bytes], *, interval_ms: int = 100, dwell_ms: int = 500,
          display: list[bytes] = ()) -> bytes:
    """The image: the access point, the advertisement header with its first nonce, one payload per
    fragment and up to four DISPLAY commands the board replays at start."""
    if not 1 <= len(fragments) <= FRAGMENTS_MAX:
        raise ValueError(f"{len(fragments)} fragments; the board stores 1 to {FRAGMENTS_MAX}")
    info = net.info()
    plains = []
    for data in reversed(fragments):
        info.application_data = bytes(data)
        plains.insert(0, _plain(info.build_advertisement(derivation)))
    body = _head(net, derivation, data_key, KIND_CYCLE, interval_ms, dwell_ms, len(plains), display)
    for blob in (*plains, *display):
        body += struct.pack("<H", len(blob)) + blob
    return _close(body)


def _generation_key(derivation: ldn.KeyDerivation, source: bytes) -> bytes:
    """The key `KeyDerivation._derive_key` decrypts its data hash with: a key derived for this LDN
    protocol, never one of `prod.keys`'."""
    key = derivation._select_master_key()
    key = derivation._decrypt_key(derivation._key("aes_kek_generation_source"), key)
    key = derivation._decrypt_key(source, key)
    return derivation._decrypt_key(derivation._key("aes_key_generation_source"), key)


def record(tag: int, data: bytes) -> bytes:
    """One record of a host image: u8 tag, u16 length, bytes (firmware/esp32/main/gift.h)."""
    if len(data) > 0xFFFF:
        raise ValueError(f"record {tag} is {len(data)} bytes")
    return struct.pack("<BH", tag, len(data)) + bytes(data)


def ldn_record(net: ldn.APNetwork, derivation: ldn.KeyDerivation) -> bytes:
    """What the board needs to answer a join itself (firmware/esp32/main/gift.h, the LDN record):
    the advertisement plaintext up to the first station, the authentication key's generation key and
    the challenge the network advertises."""
    info = net.info()
    info.application_data = b""
    plain = _plain(info.build_advertisement(derivation))
    if len(plain) != V2_PREFIX + V2_STATION + 2:
        raise ValueError("the board builds AES-GCM advertisements only (LDN protocol 3)")
    network_id = ldn.NetworkId()
    network_id.local_communication_id = info.local_communication_id
    network_id.scene_id = info.scene_id
    network_id.ssid = info.ssid
    return record(RECORD_LDN, plain[:V2_PREFIX + V2_STATION] + network_id.encode("<")
                   + _generation_key(derivation, AUTH_KEY_SOURCE)
                   + derivation.challenge_key(net._param.dev)
                   + struct.pack("<QQBB", info.challenge, net._device_id, info.version,
                                 net._platform))


def pia_record(net: ldn.APNetwork, game_key: bytes, host_name: str,
               host_player_id: bytes) -> bytes:
    """The Pia host's session key and identity (gift.h, the Pia record)."""
    info = net.info()
    session_key = AES.new(bytes(game_key), AES.MODE_ECB).encrypt(bytes(info.ssid))
    network_id = zlib.crc32(bytes(info.ssid)[1:16]) & 0xFFFFFFFF
    name = host_name.encode()
    if len(name) > 40 or len(host_player_id) != 16:
        raise ValueError("a Pia player name is at most 40 bytes and its id 16")
    host_ip = bytes(int(x) for x in net.participant().ip_address.split("."))
    return record(RECORD_PIA, session_key + struct.pack("<I", network_id) + host_ip
                   + bytes(host_player_id) + name)


def build_host(net: ldn.APNetwork, derivation: ldn.KeyDerivation, data_key: bytes,
               records: list[bytes], *, interval_ms: int = 100, display: list[bytes] = ()) -> bytes:
    """An image whose board answers a join (KIND_HOST): the advertisement is built on the board
    from the LDN record and the stations seated, and `records` say what it plays above LDN."""
    body = _head(net, derivation, data_key, KIND_HOST, interval_ms, interval_ms, 0, display)
    for blob in display:
        body += struct.pack("<H", len(blob)) + blob
    for record in records:
        body += record
    return _close(body)

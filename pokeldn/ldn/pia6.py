"""Pia 6.16-6.30 packet header, version 11, the wire format Legends Arceus speaks.

Header, crypto and framing: docs/pla.md, The wireless layer and The packet crypto. The message
framing is `pia5`'s unaligned; flag 0x01 means "skip the source variable id check"."""
import struct

from pokeldn.ldn.crypto import PiaCrypto, ip_bytes
from pokeldn.ldn.pia5 import ALL_FIELDS_PRESENT, decrypt_payload, encrypt_payload
from pokeldn.ldn import pia5 as _pia5
from pokeldn.ldn.pia5 import build_message as _build_message5
from pokeldn.ldn.pia5 import pad_payload

MAGIC = 0x32AB9864
VERSION = 11
HEADER_SIZE = 0x1C
FOOTER_SIZE_OFF = 0x0B
NONCE_OFF, TAG_OFF, CT_OFF = 0x0C, 0x14, 0x1C
TAG_SIZE = 8
FLAG_ENCRYPTED = 0x80
MAX_PAYLOAD = 0x5A5  # 0x6f07fc: length - 0x1C must be below this
BUFFER_SIZE = 0x5C0  # 0x6f0824: the object's packet buffer

# 6.16-6.30 message flags; 0x01 marked a destination bitmap at 5.27-5.45.
MESSAGE_FLAG_SKIP_SOURCE_CHECK = 0x01
MESSAGE_FLAG_RELAY_ONE = 0x02
MESSAGE_FLAG_RELAY_MANY = 0x04
MESSAGE_FLAG_WAS_RELAYED = 0x08
MESSAGE_FLAG_NO_BUNDLING = 0x10
MESSAGE_FLAG_ZLIB = 0x20

__all__ = ["MAGIC", "VERSION", "HEADER_SIZE", "FOOTER_SIZE_OFF", "NONCE_OFF", "TAG_OFF", "CT_OFF",
           "TAG_SIZE", "FLAG_ENCRYPTED", "MAX_PAYLOAD", "BUFFER_SIZE", "PiaHeader6", "is_pia6",
           "ciphertext", "footer", "ldn_session_key", "ldn_network_id", "gcm_iv", "build_packet",
           "parse_packet", "pad_payload", "encrypt_payload", "decrypt_payload", "parse_messages",
           "build_message", "MESSAGE_FLAG_SKIP_SOURCE_CHECK", "MESSAGE_FLAG_RELAY_ONE",
           "MESSAGE_FLAG_RELAY_MANY", "MESSAGE_FLAG_WAS_RELAYED", "MESSAGE_FLAG_NO_BUNDLING",
           "MESSAGE_FLAG_ZLIB"]


class PiaHeader6:
    """The 0x1C bytes in front of a version-11 packet."""

    __slots__ = ("dst_var", "src_var", "packet_id", "footer_size", "nonce8", "tag",
                 "encrypted", "version")

    def __init__(self, dst_var=0, src_var=0, packet_id=0, footer_size=0,
                 nonce8=b"\0" * 8, tag=b"\0" * TAG_SIZE, encrypted=True, version=VERSION):
        self.dst_var, self.src_var = dst_var, src_var
        self.packet_id, self.footer_size = packet_id, footer_size
        self.nonce8, self.tag = bytes(nonce8), bytes(tag)
        self.encrypted, self.version = encrypted, version

    @classmethod
    def parse(cls, data):
        if len(data) < HEADER_SIZE:
            raise ValueError(f"short packet: {len(data)} bytes")
        magic, vb, dst, src, pid, footer_size = struct.unpack_from(">IBHHHB", data, 0)
        if magic != MAGIC:
            raise ValueError(f"not Pia: magic {magic:#010x}")
        return cls(dst, src, pid, footer_size, data[NONCE_OFF:TAG_OFF], data[TAG_OFF:CT_OFF],
                   bool(vb & FLAG_ENCRYPTED), vb & 0x7F)

    def pack(self):
        vb = (FLAG_ENCRYPTED if self.encrypted else 0) | (self.version & 0x7F)
        return (struct.pack(">IBHHHB", MAGIC, vb, self.dst_var & 0xFFFF, self.src_var & 0xFFFF,
                            self.packet_id & 0xFFFF, self.footer_size & 0xFF)
                + self.nonce8.ljust(8, b"\0")[:8] + self.tag.ljust(TAG_SIZE, b"\0")[:TAG_SIZE])

    def __repr__(self):
        return (f"PiaHeader6(v{self.version}{'E' if self.encrypted else ''} "
                f"dst={self.dst_var:#06x} src={self.src_var:#06x} pid={self.packet_id} "
                f"footer={self.footer_size} nonce={self.nonce8.hex()})")


def is_pia6(data):
    """-> True for a version-11 packet; the version byte separates it from 9, 15 and 16."""
    return (len(data) >= HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == MAGIC
            and (data[4] & 0x7F) == VERSION)


def ciphertext(data, footer_size=None):
    """The encrypted body, between the header and the footer; the tag does not cover the footer."""
    if footer_size is None:
        footer_size = data[FOOTER_SIZE_OFF] if len(data) > FOOTER_SIZE_OFF else 0
    end = len(data) - footer_size if footer_size else len(data)
    return data[CT_OFF:end]


def footer(data, footer_size=None):
    """-> the recipients' variable ids, one big-endian halfword each."""
    if footer_size is None:
        footer_size = data[FOOTER_SIZE_OFF] if len(data) > FOOTER_SIZE_OFF else 0
    if not footer_size:
        return []
    raw = data[len(data) - footer_size:]
    return [struct.unpack_from(">H", raw, i)[0] for i in range(0, len(raw) - 1, 2)]


# Pad with 0xFF only: a 0x00 is a one-byte header, and zero padding makes the console discard the
# whole packet at `0x74419c` (docs/pla.md, Reading and writing a packet).
MESSAGE_PAD = b"\xff"


def parse_messages(plaintext):
    """`pia5.parse_messages` with no alignment: this band starts the next message where the last
    ended, and a four-byte walk skips a bundled message."""
    return _pia5.parse_messages(plaintext, align=0)


def build_message(payload, protocol, port=0, message_flags=0, destination=0, inherit=False):
    """One message, ending where its payload ends: this band does not align to four.
    `inherit=True` states the size alone; `inherit="port"` states size, protocol and port, as a
    reference host bundles a second message on another port."""
    if inherit == "port":
        return (bytes([0x02 | 0x04]) + struct.pack(">H", len(payload))
                + bytes([protocol]) + int(port).to_bytes(3, "big") + bytes(payload))
    raw = _build_message5(payload, protocol, port=port, message_flags=message_flags,
                          destination=destination, inherit=bool(inherit))
    stated = _stated_length(raw)
    if stated is None or stated >= len(raw):
        return raw
    return raw[:stated]


def _stated_length(raw):
    """-> the message's length before alignment, or None if its header omits the size."""
    present, off, size = raw[0], 1, None
    for bit, width in ((0x01, 1), (0x02, 2), (0x04, 4), (0x08, 8)):
        if not present & bit:
            continue
        if bit == 0x02:
            size = int.from_bytes(raw[off:off + width], "big")
        off += width
    return None if size is None else off + size


def ldn_session_key(game_key, ssid):
    """AES-128-ECB(game_key) over one block of the SSID, repeated if short (0x70d61c)."""
    from Crypto.Cipher import AES

    game_key, ssid = bytes(game_key), bytes(ssid)
    if len(game_key) != 16:
        raise ValueError(f"a Pia game key is sixteen bytes, not {len(game_key)}")
    if not ssid:
        raise ValueError("the SSID is empty")
    block = ssid[:16] if len(ssid) >= 16 else (ssid * (16 // len(ssid) + 1))[:16]
    return AES.new(game_key, AES.MODE_ECB).encrypt(block)


def ldn_network_id(ssid):
    """-> CRC-32 over the SSID without its first byte."""
    import zlib

    return zlib.crc32(bytes(ssid)[1:16]) & 0xFFFFFFFF


def gcm_iv(network_id, src_ip, nonce8):
    """`u32be(network_id ^ source_ip)` then the header's nonce (0x711710)."""
    if len(nonce8) != 8:
        raise ValueError(f"a Pia header nonce is eight bytes, not {len(nonce8)}")
    four = (network_id ^ int.from_bytes(ip_bytes(src_ip), "big")) & 0xFFFFFFFF
    return four.to_bytes(4, "big") + bytes(nonce8)


def crypto(ssid, game_key):
    return PiaCrypto(ssid, game_key=bytes(game_key))


def parse_packet(session_key, src_ip, network_id, data):
    """-> (PiaHeader6, plaintext, footer ids); plaintext is None if the tag does not verify."""
    header = PiaHeader6.parse(data)
    ids = footer(data, header.footer_size)
    ct = ciphertext(data, header.footer_size)
    if not header.encrypted:
        return header, ct, ids
    iv = gcm_iv(network_id, src_ip, header.nonce8)
    return header, decrypt_payload(session_key, iv, ct, header.tag), ids


def build_packet(session_key, network_id, src_ip, plaintext, dst_var=0, src_var=0, packet_id=0,
                 nonce8=b"\0" * 8, footer_ids=()):
    """A whole version-11 packet: header, ciphertext, plaintext footer. Give each packet its own
    `nonce8`; `footer_ids` are the recipients' variable ids for a multi-station packet."""
    tail = b"".join(struct.pack(">H", v & 0xFFFF) for v in footer_ids)
    iv = gcm_iv(network_id, src_ip, nonce8)
    ct, tag = encrypt_payload(session_key, iv, pad_payload(plaintext))
    header = PiaHeader6(dst_var=dst_var, src_var=src_var, packet_id=packet_id,
                        footer_size=len(tail), nonce8=nonce8, tag=tag, encrypted=True)
    return header.pack() + ct + tail


# Session Protocol 0x98. The join request is a retail Arceus's (tests/test_pla_session_v11.py) and
# Scarlet's (docs/sv.md, The Session join request). Its station address is seven bytes: kind (0 for
# IPv4), IPv4, big-endian port.
SESSION_JOIN_REQUEST = 0
STATION_ADDRESS_SIZE = 18

# The protocols and versions a station at this band registers; a host compares the count and every
# version against its own first.
PROTO_NET, PROTO_RTT, PROTO_UNRELIABLE = 0x2C, 0x58, 0x68
PROTO_CLONE = (0x74, 0x75, 0x76, 0x77)
PROTO_RELIABLE, PROTO_BROADCAST_RELIABLE, PROTO_SESSION, PROTO_MONITORING = 0x7C, 0x80, 0x98, 0xA4
PROTO_STREAM_BROADCAST_RELIABLE, PROTO_CLONE_ATOMIC, PROTO_CLONE_CLOCK = 0x81, 0x74, 0x77
BAND_PROTOCOLS = [(PROTO_NET, 0), (PROTO_RTT, 3), (PROTO_UNRELIABLE, 1), (PROTO_CLONE_ATOMIC, 0),
                  (PROTO_CLONE_CLOCK, 0), (PROTO_RELIABLE, 2), (PROTO_BROADCAST_RELIABLE, 3),
                  (PROTO_STREAM_BROADCAST_RELIABLE, 3), (PROTO_SESSION, 0), (PROTO_MONITORING, 0)]

# A retail joiner's player id: 1 then 0 as two big-endian u64.
DEFAULT_PLAYER_ID = (1).to_bytes(8, "big") + bytes(8)


def station_address(ip, port=12345):
    """The Net protocol's 18-byte station address: IPv4 in 16 bytes, big-endian port."""
    return ip_bytes(ip).ljust(16, b"\x00") + int(port).to_bytes(2, "big")


def location_id(constant_id, var):
    """The constant id, two zero bytes, the variable id."""
    cid = bytes(constant_id)
    cid = cid + b"\x00\x00" if len(cid) == 6 else cid
    var = var if isinstance(var, int) else int.from_bytes(var, "big")
    return cid + b"\x00\x00" + var.to_bytes(2, "big")


def build_session_join(src_constant_id, src_var, src_ip, dst_constant_id, dst_var, player_name,
                       random4, *, src_port=12345, protocols=BAND_PROTOCOLS,
                       player_id=DEFAULT_PLAYER_ID, token=b"\x00" * 32, nat_mapping=0,
                       private_ipv6=0, players=None, player_flag=1, name_kind=1):
    """A retail-layout 0x98 join request. `players` is a list of (id, name)."""
    out = bytearray([SESSION_JOIN_REQUEST, len(protocols)])
    for pid, ver in protocols:
        out += bytes([pid & 0xFF, ver & 0xFF])
    out += bytes(random4)[:4].rjust(4, b"\x00")
    out += location_id(src_constant_id, src_var)
    out += bytes([nat_mapping & 0xFF, private_ipv6 & 0xFF])
    out += bytes(token)[:32].ljust(32, b"\x00")
    out += b"\x00" + ip_bytes(src_ip) + int(src_port).to_bytes(2, "big")
    out += location_id(dst_constant_id, dst_var)
    if players is None:
        players = [(player_id, player_name)]
    out += bytes([len(players) & 0xFF, player_flag & 0xFF])
    for pid, name in players:
        name = name.encode() if isinstance(name, str) else bytes(name)
        out += bytes(pid)[:16].ljust(16, b"\x00")
        out += len(name).to_bytes(4, "big") + bytes([name_kind]) + name
    return bytes(out)

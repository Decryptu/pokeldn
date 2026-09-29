"""Pia version 4 packet header and message framing, the wire format Sword/Shield speaks.

Session key, IV and message framing are 5.27-5.45's plus an eight-byte source constant id in the
message header (docs/pia.md, Version 4 and Message framing)."""
import struct
import zlib

from pokeldn.ldn.pia5 import gcm_iv, ldn_session_key, parse_messages as parse_messages5

MAGIC = 0x32AB9864
VERSION = 4
HEADER_SIZE = 0x20
NONCE_OFF, TAG_OFF, CT_OFF = 0x08, 0x10, 0x20
TAG_SIZE = 16  # 5.27-5.45 truncates to eight
FLAG_ENCRYPTED = 0x80
MESSAGE_HEADER_SIZE = 24

__all__ = ["MAGIC", "VERSION", "HEADER_SIZE", "TAG_SIZE", "MESSAGE_HEADER_SIZE", "PiaHeader4",
           "ciphertext", "is_pia4", "gcm_iv", "ldn_session_key", "parse_messages5",
           "ALL_FIELDS_PRESENT", "MESSAGE_FLAGS", "build_message", "parse_message_header",
           "MESSAGE_FIELDS", "MESSAGE_FLAG_ZLIB", "message_header_size", "parse_packet",
           "pad_payload", "encrypt_payload", "decrypt_payload", "build_packet"]


class PiaHeader4:
    __slots__ = ("station", "session_id", "nonce8", "tag", "encrypted", "version")

    def __init__(self, station=0, session_id=0, nonce8=b"\0" * 8, tag=b"\0" * TAG_SIZE,
                 encrypted=True, version=VERSION):
        self.station, self.session_id = station, session_id
        self.nonce8, self.tag = bytes(nonce8), bytes(tag)
        self.encrypted, self.version = encrypted, version

    @classmethod
    def parse(cls, data):
        if len(data) < HEADER_SIZE:
            raise ValueError(f"short packet: {len(data)} bytes")
        magic, vb, station, session_id = struct.unpack_from(">IBBH", data, 0)
        if magic != MAGIC:
            raise ValueError(f"not Pia: magic {magic:#010x}")
        return cls(station, session_id, data[NONCE_OFF:TAG_OFF], data[TAG_OFF:CT_OFF],
                   bool(vb & FLAG_ENCRYPTED), vb & 0x7F)

    def pack(self):
        vb = (FLAG_ENCRYPTED if self.encrypted else 0) | (self.version & 0x7F)
        return (struct.pack(">IBBH", MAGIC, vb, self.station & 0xFF, self.session_id & 0xFFFF)
                + self.nonce8.ljust(8, b"\0")[:8] + self.tag.ljust(TAG_SIZE, b"\0")[:TAG_SIZE])

    def __repr__(self):
        return (f"PiaHeader4(v{self.version}{'E' if self.encrypted else ''} "
                f"station={self.station} session={self.session_id:#06x} "
                f"nonce={self.nonce8.hex()})")


def is_pia4(data):
    """-> True for a version-4 packet; the version byte separates it from BDSP's 9."""
    return (len(data) >= HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == MAGIC
            and (data[4] & 0x7F) == VERSION)


def ciphertext(data):
    """Version 4 has no footer-size field: the body is the tail."""
    return data[CT_OFF:]


# The presence byte says which fields follow; an omitted field is inherited from the previous
# message in the packet (`0x01853050`, docs/pia.md, Message framing).
MESSAGE_FIELDS = ((0x01, 1, "flags"), (0x02, 2, "size"), (0x04, 4, "proto_port"),
                  (0x08, 8, "destination"), (0x10, 8, "source"))

# Version 4's zlib flag; 5.27-5.45 uses 0x20 (docs/pia.md, Compression).
MESSAGE_FLAG_ZLIB = 0x10


def message_header_size(present):
    return 1 + sum(width for bit, width, _ in MESSAGE_FIELDS if present & bit)


def parse_packet(plaintext):
    """Split a decrypted version-4 payload into messages, resolving inherited fields.
    The walk stops at 0xFF alone: presence 0x00 is a one-byte header inheriting every field
    (`0x01852da0`), and a reliable-window packet carries two of them after its first 0x7C."""
    out, off, prev = [], 0, None
    while off < len(plaintext):
        present = plaintext[off]
        if present == 0xFF:
            break
        if present == 0 and prev is None:
            break  # nothing to inherit; the console never sends this
        size = message_header_size(present)
        if off + size > len(plaintext):
            break
        m = {"at": off, "present": present, "header_size": size, "inherited": set()}
        p = off + 1
        for bit, width, name in MESSAGE_FIELDS:
            if present & bit:
                m[name] = int.from_bytes(plaintext[p:p + width], "big")
                p += width
            elif prev is not None:
                m[name] = prev[name]
                m["inherited"].add(name)
            else:
                m[name] = 0
                m["inherited"].add(name)
        m["protocol"], m["port"] = m["proto_port"] >> 24, m["proto_port"] & 0xFFFFFF
        end = p + m["size"]
        if end > len(plaintext):
            break
        m["header"] = plaintext[off:p]
        m["payload"] = m["raw_payload"] = plaintext[p:end]
        m["compressed"] = bool(m["flags"] & MESSAGE_FLAG_ZLIB)
        if m["compressed"]:
            try:
                m["payload"] = zlib.decompress(m["raw_payload"])
            except zlib.error as exc:
                m["compressed"], m["zlib_error"] = False, str(exc)
        out.append(m)
        prev = m
        off = end + (-end % 4)
    return out


def parse_messages(plaintext):
    """-> [(header_bytes, body)], each header as sent; `parse_packet` resolves inherited fields."""
    return [(m["header"], m["payload"]) for m in parse_packet(plaintext)]


# Mirrored from a retail Sword's own headers (`tests/test_pia4.py`). The source field is the
# sender's station constant id, big-endian here and little-endian in the Local Protocol body
# (docs/pia.md, Message framing).

ALL_FIELDS_PRESENT = 0x7F
MESSAGE_FLAGS = 0x09  # the console's own, on every message
SOURCE_OFF = 16


def build_message(payload, protocol, source, port=0, message_flags=MESSAGE_FLAGS, destination=0):
    """One version-4 message, padded to four bytes. `source` is this station's constant id
    (`station_protocol.ldn_constant_id` over its MAC) as an integer."""
    payload = bytes(payload)
    out = (bytes([ALL_FIELDS_PRESENT, message_flags & 0xFF]) + struct.pack(">H", len(payload))
           + bytes([protocol & 0xFF]) + (port & 0xFFFFFF).to_bytes(3, "big")
           + struct.pack(">Q", destination) + struct.pack(">Q", source))
    out += payload
    return out + b"\x00" * (-len(out) % 4)


def parse_message_header(header):
    """-> dict of the fields this header states; `parse_packet` resolves the omitted ones."""
    present = header[0]
    if len(header) != message_header_size(present):
        raise ValueError(f"a header with presence {present:#04x} is "
                         f"{message_header_size(present)} bytes, this is {len(header)}")
    out, off = {"present": present}, 1
    for bit, width, name in MESSAGE_FIELDS:
        if present & bit:
            out[name] = int.from_bytes(header[off:off + width], "big")
            off += width
    if "proto_port" in out:
        out["protocol"], out["port"] = out["proto_port"] >> 24, out["proto_port"] & 0xFFFFFF
    return out


def pad_payload(plaintext):
    """0xFF-pad to a multiple of sixteen as 5.27 does: a 145-byte station announcement pads to
    148 as a message and 160 as a packet, the measured ciphertext length."""
    return bytes(plaintext) + b"\xff" * (-len(plaintext) % 16)


def encrypt_payload(session_key, iv, plaintext):
    """-> (ciphertext, 16-byte tag)."""
    from Crypto.Cipher import AES

    return AES.new(bytes(session_key), AES.MODE_GCM, nonce=bytes(iv),
                   mac_len=TAG_SIZE).encrypt_and_digest(bytes(plaintext))


def decrypt_payload(session_key, iv, ct, tag):
    """-> plaintext, or None if the tag does not verify."""
    from Crypto.Cipher import AES

    try:
        return AES.new(bytes(session_key), AES.MODE_GCM, nonce=bytes(iv),
                       mac_len=TAG_SIZE).decrypt_and_verify(bytes(ct), bytes(tag))
    except ValueError:
        return None


def build_packet(session_key, iv, plaintext, station=0, session_id=0, nonce8=b"\0" * 8):
    """A whole version-4 packet. The console sends 0 as connection id (`station`) and packet id
    (`session_id`) on every packet; 0 passes every receive check (docs/pia.md, Version 4)."""
    ct, tag = encrypt_payload(session_key, iv, pad_payload(plaintext))
    return PiaHeader4(station=station, session_id=session_id, nonce8=nonce8, tag=tag,
                      encrypted=True).pack() + ct

"""Pia version 3 (Pia 5.11-5.12), the wire format Let's Go Pikachu / Eevee speaks: pia4's packet
header with version byte 3, over a fixed 22-byte message header (docs/lgpe_session.md, The message
framing). Tag, session key and IV are pia4's."""
import struct

from pokeldn.ldn import pia4
from pokeldn.ldn.pia4 import (HEADER_SIZE, MAGIC, TAG_SIZE, PiaHeader4, ciphertext, decrypt_payload,
                              encrypt_payload, gcm_iv, ldn_session_key, pad_payload)

VERSION = 3
MESSAGE_VERSION = 1
MESSAGE_HEADER_SIZE = 0x16
MESSAGE_FLAG_BITMAP = 0x01
MESSAGE_FLAG_UNBUNDLED = 0x08

__all__ = ["VERSION", "MESSAGE_VERSION", "MESSAGE_HEADER_SIZE", "MESSAGE_FLAG_BITMAP",
           "MESSAGE_FLAG_UNBUNDLED", "HEADER_SIZE", "MAGIC", "TAG_SIZE", "PiaHeader4", "ciphertext",
           "decrypt_payload", "encrypt_payload", "gcm_iv", "ldn_session_key", "pad_payload",
           "is_pia3", "parse_packet", "parse_messages", "build_message", "build_packet"]


def is_pia3(data):
    """-> True for a version-3 packet; the version byte separates it from Sword's 4 and BDSP's 9."""
    return (len(data) >= HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == MAGIC
            and (data[4] & 0x7F) == VERSION)


def parse_packet(plaintext):
    """Split a decrypted version-3 payload into message dicts; the walk stops at 0xFF padding."""
    out, off = [], 0
    while off + MESSAGE_HEADER_SIZE <= len(plaintext):
        if plaintext[off] == 0xFF:
            break
        flags, version, size, protocol, port, dest, source = struct.unpack_from(
            ">BBHBBQQ", plaintext, off)
        p = off + MESSAGE_HEADER_SIZE
        end = p + size
        if end > len(plaintext):
            break
        out.append({"at": off, "flags": flags, "version": version, "size": size,
                    "protocol": protocol, "port": port, "destination": dest, "source": source,
                    "header": plaintext[off:p], "payload": plaintext[p:end]})
        off = end + (-end % 4)
    return out


def parse_messages(plaintext):
    """-> [(header_bytes, body)]."""
    return [(m["header"], m["payload"]) for m in parse_packet(plaintext)]


def build_message(payload, protocol, source, port=0, message_flags=MESSAGE_FLAG_UNBUNDLED,
                  destination=0):
    """One version-3 message, padded to four bytes. `destination` is a station bitmap when
    `message_flags` carries MESSAGE_FLAG_BITMAP."""
    payload = bytes(payload)
    out = struct.pack(">BBHBBQQ", message_flags & 0xFF, MESSAGE_VERSION, len(payload),
                      protocol & 0xFF, port & 0xFF, destination, source) + payload
    return out + b"\x00" * (-len(out) % 4)


def build_packet(session_key, iv, plaintext, station=0, session_id=0, nonce8=b"\0" * 8):
    pkt = bytearray(pia4.build_packet(session_key, iv, plaintext, station=station,
                                      session_id=session_id, nonce8=nonce8))
    pkt[4] = (pkt[4] & 0x80) | VERSION
    return bytes(pkt)

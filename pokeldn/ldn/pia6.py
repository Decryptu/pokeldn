"""Pia 6.16-6.30 packet header, version 11: the wire format Legends Arceus speaks.

Read off Legends Arceus 1.1.1's decompressed `main`. The header object keeps its fields at +8 and
its packet buffer at +0x30, so a field's wire offset is its object offset minus 9, apart from the
magic and the version byte:

    wire  obj    size  field                        evidence in main_111.bin
    0x00  +0x08  4     magic 0x32AB9864, big-endian the initializer stores it at 0x6f0750
    0x04  +0x0c  1     0x80 (encrypted) | version   0x6f0754 writes 0x0b; 0x6f07e8 checks & 0x7f
    0x05  +0x0e  2     destination variable id
    0x07  +0x10  2     source variable id
    0x09  +0x12  2     packet id
    0x0b  +0x14  1     footer size
    0x0c  +0x15  8     AES-GCM nonce                zeroed by memset(obj+0x15, 0, 8) at 0x6f0778
    0x14  +0x1d  8     AES-GCM tag, truncated       the object holds 16; `mov w4, #8` at 0x6f0b24
    0x1c                ciphertext

The copy assignment at 0x6f0878 walks those fields one by one and stops at +0x2c, then copies
0x5c4 bytes from +0x30 and the length from +0x5f8. The validator at 0x6f07d0 requires the magic,
`(version & 0x7f) == 11`, and a packet length minus 0x1C below 0x5a5.

The footer is outside the encryption in this band. The encrypt path at 0x6f09f4 takes the footer
size off the header, subtracts it from the length, encrypts from buffer+0x4c (0x30 + 0x1C) and
writes the tag to obj+0x1d, so the footer rides after the ciphertext in plaintext. The payload is
0xFF-padded to the AES block size first (`memset(.., 0xFF, 0x5a4)` at 0x6f0af8), and the version
byte gets 0x80 ORed into it once the packet is sealed (0x6f0b48).

THE SESSION KEY AND THE IV ARE THE SAME DERIVATION `pokeldn.ldn.crypto.PiaCrypto` ALREADY RUNS for
the GBA app at 6.32, which is why this module holds a header and no second crypto stack. Both were
read off Arceus rather than assumed:

    session key   0x70d61c takes the network SSID, repeats it if it is shorter than sixteen bytes,
                  and AES-ECB-encrypts one block under the game key at LdnProtocol+0x238. The mode
                  at +0x234 being zero leaves the key all zeroes.
    GCM IV        LocalOutputStream::vfunc3 (0x711710) writes `u32be(network_id ^ source_ip)` at
                  IV[0] through 0x6ed380, then copies the header's eight nonce bytes to IV[4].
    header nonce  a per-packet counter, big-endian, written to obj+0x15 by 0x6ed360.

`docs/pla.md` carries the addresses. The message framing above the header is 5.27-6.30's, so
`pia5.parse_messages` and `pia5.build_message` read and write it unchanged; only the meaning of
message flag 0x01 moved, to "skip the source variable id check".
"""
import struct

from pokeldn.ldn.crypto import PiaCrypto, ip_bytes
from pokeldn.ldn.pia5 import ALL_FIELDS_PRESENT, decrypt_payload, encrypt_payload, parse_messages
from pokeldn.ldn.pia5 import build_message as _build_message5
from pokeldn.ldn.pia5 import pad_payload

MAGIC = 0x32AB9864
VERSION = 11
HEADER_SIZE = 0x1C
FOOTER_SIZE_OFF = 0x0B
NONCE_OFF, TAG_OFF, CT_OFF = 0x0C, 0x14, 0x1C
TAG_SIZE = 8
FLAG_ENCRYPTED = 0x80
MAX_PAYLOAD = 0x5A5               # 0x6f07fc: length - 0x1C must be below this
BUFFER_SIZE = 0x5C0               # 0x6f0824: the object's own packet buffer

# 6.16-6.30 message flags. 0x01 changed meaning from 5.27-5.45, where it said the destination was a
# bitmap; the rest are 5.27's.
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
    """-> True for a version-11 packet. The version byte separates it from 9, 15 and 16."""
    return (len(data) >= HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == MAGIC
            and (data[4] & 0x7F) == VERSION)


def ciphertext(data, footer_size=None):
    """The encrypted body: after the header and before the footer, which is not covered by the tag.

    The footer size is a header field, so nothing is guessed: pass it, or let this read it back.
    """
    if footer_size is None:
        footer_size = data[FOOTER_SIZE_OFF] if len(data) > FOOTER_SIZE_OFF else 0
    end = len(data) - footer_size if footer_size else len(data)
    return data[CT_OFF:end]


def footer(data, footer_size=None):
    """-> the recipients' variable ids, one big-endian halfword each, as the console packs them."""
    if footer_size is None:
        footer_size = data[FOOTER_SIZE_OFF] if len(data) > FOOTER_SIZE_OFF else 0
    if not footer_size:
        return []
    raw = data[len(data) - footer_size:]
    return [struct.unpack_from(">H", raw, i)[0] for i in range(0, len(raw) - 1, 2)]


# THE PADDING BYTE IS 0xFF AT EVERY LEVEL, and 0x00 is not a spelling of it. The message walk
# treats a presence byte of 0x00 as a legal one-byte header that inherits every field from the
# message before it, so a message padded to four bytes with zeroes makes the parser read a second
# message out of the padding, fail, and REJECT THE WHOLE PACKET, the good message with it. Measured
# on the game under a debugger: 31 of 31 packets discarded at `0x74419c` after the first message had
# already parsed and been accepted. The console pads the same way this does, pre-filling its encrypt
# buffer with 0xFF at `0x6f0af8` before copying the messages over the front.
MESSAGE_PAD = b"\xff"


def build_message(payload, protocol, port=0, message_flags=0, destination=0, inherit=False):
    """One message, aligned to four bytes with 0xFF rather than with zeroes.

    `pia5.build_message` writes the layout; only the alignment bytes differ. 5.27-5.45 pads with
    zeroes and BDSP's parser stops on a zero presence byte, so there it is invisible.
    """
    raw = _build_message5(payload, protocol, port=port, message_flags=message_flags,
                          destination=destination, inherit=inherit)
    stated = _stated_length(raw)
    if stated is None or stated >= len(raw):
        return raw
    return raw[:stated] + MESSAGE_PAD * (len(raw) - stated)


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
    """AES-128-ECB(game_key) over one block of the network SSID. 0x70d61c.

    An SSID of sixteen bytes or more is taken as is; a shorter one is repeated to fill the block,
    which is the `0x10 / len` loop at 0x70d66c. No console has been seen advertising a short one.
    """
    from Crypto.Cipher import AES

    game_key, ssid = bytes(game_key), bytes(ssid)
    if len(game_key) != 16:
        raise ValueError(f"a Pia game key is sixteen bytes, not {len(game_key)}")
    if not ssid:
        raise ValueError("the SSID is empty")
    block = ssid[:16] if len(ssid) >= 16 else (ssid * (16 // len(ssid) + 1))[:16]
    return AES.new(game_key, AES.MODE_ECB).encrypt(block)


def ldn_network_id(ssid):
    """-> the network id: CRC-32 over every byte of the SSID except the first."""
    import zlib

    return zlib.crc32(bytes(ssid)[1:16]) & 0xFFFFFFFF


def gcm_iv(network_id, src_ip, nonce8):
    """The twelve-byte IV: `u32be(network_id ^ source_ip)` then the header's nonce. 0x711710."""
    if len(nonce8) != 8:
        raise ValueError(f"a Pia header nonce is eight bytes, not {len(nonce8)}")
    four = (network_id ^ int.from_bytes(ip_bytes(src_ip), "big")) & 0xFFFFFFFF
    return four.to_bytes(4, "big") + bytes(nonce8)


def crypto(ssid, game_key):
    """-> a `crypto.PiaCrypto` for this network. Its key and IV are this band's, measured above."""
    return PiaCrypto(ssid, game_key=bytes(game_key))


def parse_packet(session_key, src_ip, network_id, data):
    """-> (PiaHeader6, plaintext, footer ids), or (header, None, footer) if the tag does not verify.

    The tag is the oracle. A wrong game key, SSID, network id or source address cannot pass it.
    """
    header = PiaHeader6.parse(data)
    ids = footer(data, header.footer_size)
    ct = ciphertext(data, header.footer_size)
    if not header.encrypted:
        return header, ct, ids
    iv = gcm_iv(network_id, src_ip, header.nonce8)
    return header, decrypt_payload(session_key, iv, ct, header.tag), ids


def build_packet(session_key, network_id, src_ip, plaintext, dst_var=0, src_var=0, packet_id=0,
                 nonce8=b"\0" * 8, footer_ids=()):
    """A whole version-11 packet: header, ciphertext, then the plaintext footer.

    `nonce8` is the console's per-packet counter, big-endian and eight bytes; give each packet its
    own. `footer_ids` are the recipients' variable ids when one packet goes to several stations.
    """
    tail = b"".join(struct.pack(">H", v & 0xFFFF) for v in footer_ids)
    iv = gcm_iv(network_id, src_ip, nonce8)
    ct, tag = encrypt_payload(session_key, iv, pad_payload(plaintext))
    header = PiaHeader6(dst_var=dst_var, src_var=src_var, packet_id=packet_id,
                        footer_size=len(tail), nonce8=nonce8, tag=tag, encrypted=True)
    return header.pack() + ct + tail

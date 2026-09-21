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


def parse_messages(plaintext):
    """Split a decrypted payload into messages. `pia5.parse_messages` with no alignment.

    This band starts the next message where the last one ended. Aligning to four, as 5.27-5.45 does,
    walks past a bundled message: a reference host bundles its stream open behind its data exchange
    record, and the aligned walk reads that packet as carrying the record alone.
    """
    return _pia5.parse_messages(plaintext, align=0)


def build_message(payload, protocol, port=0, message_flags=0, destination=0, inherit=False):
    """One message, ending where its payload ends.

    `pia5.build_message` writes the layout and aligns the result to four bytes; this band does not
    align, and a reference station's bundled packet starts its second message on the byte after the
    first one's payload. The packet's own 0xFF padding to a multiple of sixteen is `pad_payload`,
    and with a single message per packet the two are indistinguishable.

    `inherit=True` emits the payload size alone; `inherit="port"` emits the size, the protocol and
    the port, which is how a reference host bundles a second message that changes port.
    """
    if inherit == "port":
        # Size, protocol and port present; the message flags and destination inherit.
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


# Session Protocol at this band, protocol id 0x98. The join request is what a retail Legends Arceus
# sends (tests/test_pla_session_v11.py) and what Scarlet's own writer 0x6d5464 and parser 0x6d5aa4
# lay out (docs/sv.md, The Session join request). A station address here is a kind byte (0 for
# IPv4) then the four address bytes and the big-endian port, seven bytes; the sixteen-plus-two
# form belongs to the Net protocol's station entries, not to this message.
SESSION_JOIN_REQUEST = 0
STATION_ADDRESS_SIZE = 18

# The protocols a station at this band registers, with the version each class states
# (`scratchpad/sv_protocols.py`; a retail Arceus lists the same ten). A host compares the count
# and every version against its own before it reads anything else.
PROTO_NET, PROTO_RTT, PROTO_UNRELIABLE = 0x2C, 0x58, 0x68
PROTO_CLONE = (0x74, 0x75, 0x76, 0x77)
PROTO_RELIABLE, PROTO_BROADCAST_RELIABLE, PROTO_SESSION, PROTO_MONITORING = 0x7C, 0x80, 0x98, 0xA4
PROTO_STREAM_BROADCAST_RELIABLE, PROTO_CLONE_ATOMIC, PROTO_CLONE_CLOCK = 0x81, 0x74, 0x77
BAND_PROTOCOLS = [(PROTO_NET, 0), (PROTO_RTT, 3), (PROTO_UNRELIABLE, 1), (PROTO_CLONE_ATOMIC, 0),
                  (PROTO_CLONE_CLOCK, 0), (PROTO_RELIABLE, 2), (PROTO_BROADCAST_RELIABLE, 3),
                  (PROTO_STREAM_BROADCAST_RELIABLE, 3), (PROTO_SESSION, 0), (PROTO_MONITORING, 0)]

# The player record a retail joiner puts in its request: id 1 then 0 as two big-endian u64, and a
# name whose kind byte is 1.
DEFAULT_PLAYER_ID = (1).to_bytes(8, "big") + bytes(8)


def station_address(ip, port=12345):
    """The band's 18-byte station address: the IPv4 address in the first four of sixteen bytes,
    then the port big-endian. Read off the console's own NetStation entries."""
    return ip_bytes(ip).ljust(16, b"\x00") + int(port).to_bytes(2, "big")


def location_id(constant_id, var):
    """A location id on the wire: the eight-byte constant id, two zero bytes, the variable id."""
    cid = bytes(constant_id)
    cid = cid + b"\x00\x00" if len(cid) == 6 else cid
    var = var if isinstance(var, int) else int.from_bytes(var, "big")
    return cid + b"\x00\x00" + var.to_bytes(2, "big")


def build_session_join(src_constant_id, src_var, src_ip, dst_constant_id, dst_var, player_name,
                       random4, *, src_port=12345, protocols=BAND_PROTOCOLS,
                       player_id=DEFAULT_PLAYER_ID, token=b"\x00" * 32, nat_mapping=0,
                       private_ipv6=0, players=None, player_flag=1, name_kind=1):
    """A session join request for 0x98, the retail layout. `players` is a list of (id, name);
    without it the one player is `player_id` and `player_name`."""
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

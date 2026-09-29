"""Pia 5.27-5.45 packet header (version 9), the wire format BDSP speaks.

Header, keys and IV: docs/pia.md, Version 9 (Pia 5.27-5.45) and Session keys, and
docs/bdsp_session.md."""
import struct
import zlib

MAGIC = 0x32AB9864
VERSION = 9
HEADER_SIZE = 0x20
NONCE_OFF, TAG_OFF, CT_OFF = 0x10, 0x18, 0x20
FOOTER_SIZE_OFF = 0x0F
FLAG_ENCRYPTED = 0x80


class PiaHeader5:
    __slots__ = ("dst_var", "src_var", "packet_id", "footer_size", "nonce8", "tag",
                 "encrypted", "version")

    def __init__(self, dst_var=0, src_var=0, packet_id=0, footer_size=0,
                 nonce8=b"\0" * 8, tag=b"\0" * 8, encrypted=True, version=VERSION):
        self.dst_var, self.src_var = dst_var, src_var
        self.packet_id, self.footer_size = packet_id, footer_size
        self.nonce8, self.tag = bytes(nonce8), bytes(tag)
        self.encrypted, self.version = encrypted, version

    @classmethod
    def parse(cls, data):
        if len(data) < HEADER_SIZE:
            raise ValueError(f"short packet: {len(data)} bytes")
        magic, vb = struct.unpack_from(">IB", data, 0)
        if magic != MAGIC:
            raise ValueError(f"not Pia: magic {magic:#010x}")
        dst, src = struct.unpack_from(">I", data, 5)[0], struct.unpack_from(">I", data, 9)[0]
        pid = struct.unpack_from(">H", data, 0x0d)[0]
        return cls(dst, src, pid, data[0x0f], data[NONCE_OFF:TAG_OFF], data[TAG_OFF:CT_OFF],
                   bool(vb & FLAG_ENCRYPTED), vb & 0x7F)

    def pack(self):
        vb = (FLAG_ENCRYPTED if self.encrypted else 0) | (self.version & 0x7F)
        return (struct.pack(">IB", MAGIC, vb)
                + struct.pack(">I", self.dst_var) + struct.pack(">I", self.src_var)
                + struct.pack(">H", self.packet_id) + bytes([self.footer_size])
                + self.nonce8.ljust(8, b"\0")[:8] + self.tag.ljust(8, b"\0")[:8])

    def __repr__(self):
        return (f"PiaHeader5(v{self.version}{'E' if self.encrypted else ''} "
                f"dst={self.dst_var:#010x} src={self.src_var:#010x} "
                f"pid={self.packet_id} footer={self.footer_size} "
                f"nonce={self.nonce8.hex()})")


def ciphertext(data, footer_size=None):
    """The encrypted body minus the footer: the recipients' variable ids ride after the ciphertext,
    outside the GCM tag (docs/pia.md, The footer)."""
    if footer_size is None:
        footer_size = data[FOOTER_SIZE_OFF] if len(data) > FOOTER_SIZE_OFF else 0
    end = len(data) - footer_size if footer_size else len(data)
    return data[CT_OFF:end]


def footer(data, footer_size=None):
    """-> the recipients' variable ids, low halves."""
    if footer_size is None:
        footer_size = data[FOOTER_SIZE_OFF] if len(data) > FOOTER_SIZE_OFF else 0
    if not footer_size:
        return []
    raw = data[len(data) - footer_size:]
    return [struct.unpack_from(">H", raw, i)[0] for i in range(0, len(raw) - 1, 2)]


def is_pia5(data):
    return len(data) >= HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == MAGIC


def gcm_iv(station_crc, src_variable_id, nonce8):
    """The twelve-byte IV: three CRC bytes, the source variable id's low byte, the header nonce
    (`LdnOutputStream::vfunc3` 0x16b39c4, docs/bdsp_session.md, The GCM nonce)."""
    if len(nonce8) != 8:
        raise ValueError(f"a Pia 5.x header nonce is eight bytes, not {len(nonce8)}")
    return (struct.pack(">I", station_crc & 0xFFFFFFFF)[:3]
            + bytes([src_variable_id & 0xFF])
            + bytes(nonce8))


def password_crc(password):
    """-> advertise 0x04: CRC32 of the password's ASCII, little-endian; zero with none."""
    return struct.pack("<I", zlib.crc32(password.encode("ascii")) if password else 0)


def ldn_session_key(game_key, seed):
    """AES-128-ECB(game_key) over sixteen bytes of SEAD output (`LocalProtocol` 0x016b14e8,
    docs/bdsp_session.md, The session key). LAN's HMAC derivation does not apply to LDN."""
    from Crypto.Cipher import AES

    from pokeldn.ldn.sead import Sead

    if len(game_key) != 16:
        raise ValueError(f"a Pia game key is sixteen bytes, not {len(game_key)}")
    return AES.new(bytes(game_key), AES.MODE_ECB).encrypt(Sead(seed=seed).bytes(16))


def ldn_game_key(crypto_key_data_seed, local_communication_version):
    """The game's constant seed with bytes 1, 3, 7 and 12 replaced by the version (0x1e3f404,
    docs/pia.md, The game key). A published key is this for one version."""
    key = bytearray(crypto_key_data_seed)
    if len(key) != 16:
        raise ValueError(f"a cryptoKeyDataSeed is sixteen bytes, not {len(key)}")
    v = local_communication_version
    key[1] = (v >> 8) & 0xFF
    key[3] = (v >> 4) & 0xFF
    key[7] = (v >> 1) & 0xFF
    key[12] = v & 0xFF
    return bytes(key)


def ldn_nonce_crc(network_id_le, source_mac):
    """The CRC32 opening the GCM IV: network id (little-endian) then the source MAC."""
    if len(network_id_le) != 4 or len(source_mac) != 6:
        raise ValueError("network id is four bytes little-endian, MAC is six")
    return zlib.crc32(bytes(network_id_le) + bytes(source_mac)) & 0xFFFFFFFF


MESSAGE_FLAG_DESTINATION_BITMAP = 0x01
MESSAGE_FLAG_RELAY_ONE = 0x02
MESSAGE_FLAG_RELAY_MANY = 0x04
MESSAGE_FLAG_WAS_RELAYED = 0x08
MESSAGE_FLAG_NO_BUNDLING = 0x10
MESSAGE_FLAG_ZLIB = 0x20


class Pia5Message:
    """One message out of a decrypted Pia 5.27-5.45 packet."""

    __slots__ = ("message_flags", "protocol", "port", "destination", "payload", "compressed")

    def __init__(self, message_flags, protocol, port, destination, payload, compressed=False):
        self.message_flags, self.protocol = message_flags, protocol
        self.port, self.destination, self.payload = port, destination, payload
        self.compressed = compressed

    def __repr__(self):
        return (f"Pia5Message(proto={self.protocol} port={self.port} "
                f"flags={self.message_flags:#04x} dest={self.destination:#x} "
                f"len={len(self.payload)})")


def parse_messages(plaintext, align=4):
    """Split a decrypted payload into presence-flagged messages whose absent fields inherit
    (docs/pia.md, Message framing). 5.27-5.45 aligns each to four; `pia6` passes `align=0`."""
    out, off = [], 0
    flags = size = protocol = port = 0
    destination = 0
    while off < len(plaintext):
        present = plaintext[off]
        if present == 0xFF or (present == 0 and not out):
            break  # padding, or nothing to inherit from
        off += 1
        if present & 1:
            if off >= len(plaintext):
                break
            flags = plaintext[off]; off += 1
        if present & 2:
            if off + 2 > len(plaintext):
                break
            size = struct.unpack_from(">H", plaintext, off)[0]; off += 2
        if present & 4:
            if off + 4 > len(plaintext):
                break
            protocol = plaintext[off]
            port = int.from_bytes(plaintext[off + 1:off + 4], "big"); off += 4
        if present & 8:
            if off + 8 > len(plaintext):
                break
            destination = struct.unpack_from(">Q", plaintext, off)[0]; off += 8
        if size > len(plaintext) - off:
            break
        body = plaintext[off:off + size]
        compressed = False
        # Read raw, a zlib payload parses as a plausible header full of nonsense.
        if flags & MESSAGE_FLAG_ZLIB and body:
            try:
                body, compressed = zlib.decompress(body), True
            except zlib.error:
                pass
        out.append(Pia5Message(flags, protocol, port, destination, body, compressed))
        off += size
        if align:
            off += -off % align
    return out


def encrypt_payload(session_key, iv, plaintext):
    """-> (ciphertext, 8-byte tag): Pia keeps the first eight bytes of the GCM tag."""
    from Crypto.Cipher import AES

    ct, tag = AES.new(bytes(session_key), AES.MODE_GCM, nonce=bytes(iv),
                      mac_len=8).encrypt_and_digest(bytes(plaintext))
    return ct, tag


def decrypt_payload(session_key, iv, ciphertext, tag):
    """-> plaintext, or None if the tag does not verify."""
    from Crypto.Cipher import AES

    try:
        return AES.new(bytes(session_key), AES.MODE_GCM, nonce=bytes(iv),
                       mac_len=8).decrypt_and_verify(bytes(ciphertext), bytes(tag))
    except ValueError:
        return None


def pad_payload(plaintext):
    """0xFF-pad to a multiple of 16, as Packet::Header::vfunc3 does before encrypting."""
    return bytes(plaintext) + b"\xff" * (-len(plaintext) % 16)


ALL_FIELDS_PRESENT = 0x7F  # what the console writes; only bits 1/2/4/8 name a field


def build_message(payload, protocol, port=0, message_flags=0, destination=0, inherit=False):
    """One Pia 5.27-6.30 message, padded to four bytes. `inherit=True` states the size alone, as
    the console packs a second message; presence 0x7F copies the console's own headers."""
    payload = bytes(payload)
    if inherit:
        out = bytes([0x02]) + struct.pack(">H", len(payload))
    else:
        out = (bytes([ALL_FIELDS_PRESENT, message_flags & 0xFF]) + struct.pack(">H", len(payload))
               + bytes([protocol & 0xFF]) + (port & 0xFFFFFF).to_bytes(3, "big")
               + struct.pack(">Q", destination))
    out += payload
    return out + b"\x00" * (-len(out) % 4)

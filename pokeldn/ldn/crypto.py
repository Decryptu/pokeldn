"""Pia 6.16-6.42 AES-GCM transport crypto and zstd framing (NintendoClients wiki, Pia Protocol).

Session key AES-ECB(game key, SSID); net id CRC32(ssid[1:16]); IV u32be(net_id ^ src_ip) then the
header nonce; empty AAD; 8-byte tag. A decrypted payload may be a stock zstd frame."""

import zlib
from dataclasses import dataclass
from Crypto.Cipher import AES

try:
    import zstandard as _zstd
except ImportError:                      # pragma: no cover
    _zstd = None

# The host's Pia messages are zstd-compressed; without zstandard nothing parses.
HAVE_ZSTD = _zstd is not None

FRLG_GAME_KEY = bytes.fromhex("83ca7fab734c34633b10183526c1e85b")
PIA_MAGIC = bytes.fromhex("32ab9864")
ZSTD_MAGIC = bytes.fromhex("28b52ffd")
# The 6.32 header, 29 bytes: magic, enc, flags, dst var, src var, pktid (big-endian u16s),
# footer size [12], nonce [13:21], tag [21:29]; the recipient var-id footer is inside the payload.
HDR = 29
NONCE_OFF, TAG_OFF, CT_OFF = 13, 21, 29

STATION_HOST = 0x7620
STATION_JOINER = 0xc493


@dataclass
class PiaHeader:
    dst: int = STATION_HOST
    src: int = STATION_JOINER
    pktid: int = 0
    nonce8: bytes = b"\x00" * 8
    enc: int = 0x90
    flags: int = 0x50
    footer: int = 2

    def pack(self):
        return (PIA_MAGIC
                + bytes([self.enc, self.flags])
                + self.dst.to_bytes(2, "big")
                + self.src.to_bytes(2, "big")
                + self.pktid.to_bytes(2, "big")
                + bytes([self.footer])
                + self.nonce8)

    @classmethod
    def unpack(cls, datagram):
        return cls(
            enc=datagram[4], flags=datagram[5],
            dst=int.from_bytes(datagram[6:8], "big"),
            src=int.from_bytes(datagram[8:10], "big"),
            pktid=int.from_bytes(datagram[10:12], "big"),
            footer=datagram[12], nonce8=datagram[NONCE_OFF:TAG_OFF],
        )


def ip_bytes(ip):
    if isinstance(ip, (bytes, bytearray)):
        return bytes(ip)
    return bytes(int(x) for x in ip.split("."))


def is_pia(datagram):
    return len(datagram) >= CT_OFF and datagram[:4] == PIA_MAGIC


def decompress(plaintext):
    """-> (app_bytes, was_compressed); decoding stops at the frame end, past the 0xFF padding."""
    if plaintext[:4] != ZSTD_MAGIC or _zstd is None:
        return plaintext, False
    try:
        return _zstd.ZstdDecompressor().decompressobj().decompress(plaintext), True
    except Exception:
        return plaintext, False


def _to_window_frame(frame, wd=0x18):
    """Rewrite the zstd frame header to the Switch's window-descriptor form (28b52ffd 00 18); it
    only widens the declared window, so the frame decodes to the same bytes."""
    if frame[:4] != ZSTD_MAGIC:
        return frame
    fhd = frame[4]
    if (fhd & 0x03) or (fhd & 0x04):
        return frame
    fcs_flag = fhd >> 6
    if fhd & 0x20:
        blocks = frame[5 + ((1, 2, 4, 8)[fcs_flag]):]
    else:
        if frame[5] > wd:
            return frame
        blocks = frame[6 + ((0, 2, 4, 8)[fcs_flag]):]
    return ZSTD_MAGIC + bytes([0x00, wd]) + blocks


ZSTD_LEVEL = 4  # the only level byte-identical to the console's frames


def compress(app_bytes):
    """A zstd frame matching the console's byte for byte; the caller 0xFF-pads it."""
    if _zstd is None:
        raise RuntimeError("zstandard module not available")
    return _to_window_frame(
        _zstd.ZstdCompressor(level=ZSTD_LEVEL, write_content_size=False).compress(app_bytes))


class PiaCrypto:
    def __init__(self, ssid, game_key=FRLG_GAME_KEY):
        self.ssid = bytes(ssid)
        self.session_key = AES.new(game_key, AES.MODE_ECB).encrypt(self.ssid)
        self.net_id = zlib.crc32(self.ssid[1:16]) & 0xFFFFFFFF

    def nonce(self, src_ip, header_nonce8):
        four = (self.net_id ^ int.from_bytes(ip_bytes(src_ip), "big")) & 0xFFFFFFFF
        return four.to_bytes(4, "big") + bytes(header_nonce8)

    def decrypt(self, datagram, src_ip):
        """-> plaintext, still zstd-wrapped, or None on auth failure; `src_ip` is the sender's."""
        if not is_pia(datagram):
            return None
        nonce = self.nonce(src_ip, datagram[NONCE_OFF:TAG_OFF])
        tag = datagram[TAG_OFF:CT_OFF]
        ct = datagram[CT_OFF:]
        c = AES.new(self.session_key, AES.MODE_GCM, nonce=nonce, mac_len=len(tag))
        try:
            return c.decrypt_and_verify(ct, tag)
        except ValueError:
            return None

    def encrypt(self, plaintext, src_ip, header):
        """`header.nonce8` must be fresh per live packet; a replay copies the captured one."""
        nonce = self.nonce(src_ip, header.nonce8)
        c = AES.new(self.session_key, AES.MODE_GCM, nonce=nonce, mac_len=8)
        ct, tag = c.encrypt_and_digest(plaintext)
        return header.pack() + tag + ct

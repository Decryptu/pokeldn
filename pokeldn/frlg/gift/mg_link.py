"""MysteryGiftLink framing [decomp:src/mystery_gift_link.c]: block 0 is {u16 ident; u16 crc;
u16 size}, then <=252-byte chunks. size 0 means the whole 1024-byte buffer (RAM script, READY_END);
the CRC covers the declared size, padding included."""
from pokeldn.app.i18n import message_ref as _message

from pokeldn.frlg.gift.mystery_gift import (
    MG_LINK_BUFFER_SIZE, MG_LINK_HEADER_SIZE, MG_LINK_MAX_CHUNK, crc16,
)


class MysteryGiftLinkError(Exception):
    """A condition that makes the console call ``LinkRfu_FatalError``."""


def build_header(ident, crc, size):
    return (ident.to_bytes(2, "little")
            + crc.to_bytes(2, "little")
            + size.to_bytes(2, "little"))


def parse_header(block):
    if len(block) < MG_LINK_HEADER_SIZE:
        raise MysteryGiftLinkError(
            _message('core.pokeldn.frlg.gift.mg_link.header_block_is_value0_bytes_need_value1_c7f28019', value0=len(block), value1=MG_LINK_HEADER_SIZE))
    return (int.from_bytes(block[0:2], "little"),
            int.from_bytes(block[2:4], "little"),
            int.from_bytes(block[4:6], "little"))


def chunk_payload(buf):
    """As MGL_Send walks it: an exact multiple of 252 ends on a full chunk, no trailing block."""
    return [buf[i:i + MG_LINK_MAX_CHUNK]
            for i in range(0, len(buf), MG_LINK_MAX_CHUNK)]


def build_message(ident, payload=b"", size=None):
    """size None = exactly this payload; 0 = full buffer (padded to 1024, CRC over it)."""
    payload = bytes(payload)
    if size is None:
        size = len(payload)
    if size == 0:
        size = MG_LINK_BUFFER_SIZE
    if not 0 < size <= MG_LINK_BUFFER_SIZE:
        raise MysteryGiftLinkError(
            _message('core.pokeldn.frlg.gift.mg_link.message_size_value0_is_outside_1_value1_175e51b5', value0=size, value1=MG_LINK_BUFFER_SIZE))
    if len(payload) > size:
        raise MysteryGiftLinkError(
            _message('core.pokeldn.frlg.gift.mg_link.payload_of_value0_bytes_exceeds_the_declared_siz_e0fd4672', value0=len(payload), value1=size))
    buf = payload.ljust(size, b"\x00")
    return [build_header(ident, crc16(buf), size)] + chunk_payload(buf)


class MysteryGiftLinkReceiver:
    """Blocks arrive padded to 12-byte RFU fragments: every read is sliced to the declared size."""

    def __init__(self):
        self.expected_ident = None
        self.ident = None
        self.size = 0
        self.crc = 0
        self.buf = bytearray()
        self.blocks = 0
        self._in_header = True

    @property
    def active(self):
        return self.expected_ident is not None

    def expect(self, ident):
        self.expected_ident = ident
        self.ident = None
        self.size = 0
        self.crc = 0
        self.buf = bytearray()
        self.blocks = 0
        self._in_header = True

    def feed_block(self, block):
        block = bytes(block)
        self.blocks += 1
        if self._in_header:
            self._read_header(block)
            return None
        remaining = self.size - len(self.buf)
        take = min(remaining, MG_LINK_MAX_CHUNK)
        if len(block) < take:
            raise MysteryGiftLinkError(
                _message('core.pokeldn.frlg.gift.mg_link.payload_block_is_value0_bytes_need_value1_c68a730f', value0=len(block), value1=take))
        self.buf += block[:take]
        if len(self.buf) < self.size:
            return None
        payload = bytes(self.buf)
        if crc16(payload) != self.crc:
            raise MysteryGiftLinkError(
                _message('core.pokeldn.frlg.gift.mg_link.ident_value0_crc_mismatch_header_0x_value1_04x_c_2741a908', value0=self.ident, value1=self.crc, value2=crc16(payload)))
        self.expected_ident = None
        return payload

    def _read_header(self, block):
        ident, crc, size = parse_header(block)
        # MGL_Receive checks size before ident; keep that order.
        if size > MG_LINK_BUFFER_SIZE:
            raise MysteryGiftLinkError(
                _message('core.pokeldn.frlg.gift.mg_link.declared_size_value0_exceeds_mg_link_buffer_size_d0985972', value0=size))
        if self.expected_ident is not None and ident != self.expected_ident:
            raise MysteryGiftLinkError(
                _message('core.pokeldn.frlg.gift.mg_link.expected_ident_value0_received_value1_8c289830', value0=self.expected_ident, value1=ident))
        if size == 0:
            # Stricter than MGL_Receive: InitSend maps 0 -> 1024, so a zero is not a header.
            raise MysteryGiftLinkError(_message('core.pokeldn.frlg.gift.mg_link.received_header_declares_a_zero_size_01b47e91'))
        self.ident = ident
        self.crc = crc
        self.size = size
        self._in_header = False

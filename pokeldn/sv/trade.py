"""The trade on Reliable 0x7C port 0, as a host runs it against a joiner.

A game message is a four-byte header and a body: the handler key as a little-endian u16, a kind
byte and a step byte. Key 0x0080 is the trade channel, key 0x0180 the one the exchange itself runs
on; each is announced open on port 1 before its first message and closed after its last
(`pokeldn.pla.channel_table` for the table, `docs/sv.md` "The trade" for the order).

    80 00 02 00 + 348 bytes    the offered Pokemon, once each way, either side first
    80 00 03 00                the player confirmed, once each way, either side first
    80 00 04 01 00             the player backed out of the wait (B); the station leaves after it
    80 00 05 00                the joiner commits, the host answers in kind
    80 01 01 SS                the host starts step SS, the joiner echoes it
    80 01 02 SS                the host closes step SS; steps 03, 06, 0B, 0E

`TradeStage` is the host's side as a pure state machine: `on_message(port, payload)` returns what
to send, each entry `(delay, port, payload)`, and `tests/test_sv.py` runs it over the emulated
pair's own message list. The delays are the pair host's: its confirmation came from a player and
is sent here a second after the joiner's offer.
"""

import struct

from pokeldn.pla import channel_table

KEY_TRADE = 0x0080
KEY_EXCHANGE = 0x0180
KIND_OFFER = 2
KIND_CONFIRM = 3
KIND_CANCEL = 4
KIND_COMMIT = 5
KIND_STEP_OPEN = 1
KIND_STEP_CLOSE = 2
STEPS = (0x03, 0x06, 0x0B, 0x0E)
OFFER_SIZE = 348


def build(key, kind, step=0, body=b""):
    return struct.pack("<HBB", key, kind, step) + bytes(body)


def parse(payload):
    """-> (key, kind, step, body) of a game message, or None when it is shorter than a header."""
    if len(payload) < 4:
        return None
    key, kind, step = struct.unpack_from("<HBB", payload)
    return key, kind, step, payload[4:]


def table_update(key, opened):
    """The port-1 message announcing one key opened or closed. Scarlet keys are u16, sent as the
    two bytes of an eight-byte key with the rest absent (`b9 02 LO HI`)."""
    lo, hi = key & 0xFF, key >> 8
    state = channel_table.STATE_OPEN if opened else channel_table.STATE_CLOSED
    return (bytes([channel_table.TUPLE]) + channel_table.encode_uint(1) + channel_table.encode_uint(1)
            + bytes([channel_table.TUPLE]) + channel_table.encode_uint(2)
            + bytes([channel_table.TUPLE]) + channel_table.encode_uint(2)
            + channel_table.encode_uint(lo) + channel_table.encode_uint(hi)
            + channel_table.encode_uint(state))


class TradeStage:
    """The host's side of one trade. `offer` is the 348-byte record the host puts up."""

    def __init__(self, offer, confirm_delay=1.0):
        offer = bytes(offer)
        if len(offer) != OFFER_SIZE:
            raise ValueError(f"an offer is {OFFER_SIZE} bytes, not {len(offer)}")
        self.offer = offer
        self.confirm_delay = confirm_delay
        self.joiner_offer = None
        self.offered = False
        self.confirmed = False
        self.committed = False
        self.step_index = None
        self.done = False

    def offer_first(self):
        """-> the host's offer, for a host that puts its Pokemon up before the joiner does, as the
        pair's host did (its offer came 9 s before the joiner's)."""
        if self.offered:
            return []
        self.offered = True
        return [(0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, self.offer))]

    def on_message(self, port, payload):
        """-> [(delay, port, payload), ...] to send in answer to what the joiner sent."""
        if port != 0 or self.done:
            return []
        m = parse(payload)
        if m is None:
            return []
        key, kind, step, body = m
        if key == KEY_TRADE and kind == KIND_OFFER and len(body) == OFFER_SIZE:
            self.joiner_offer = body
            out = []
            if not self.offered:
                self.offered = True
                out.append((0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, self.offer)))
            if not self.confirmed:
                self.confirmed = True
                out.append((self.confirm_delay, 0, build(KEY_TRADE, KIND_CONFIRM)))
            return out
        if key == KEY_TRADE and kind == KIND_CONFIRM:
            return []
        if key == KEY_TRADE and kind == KIND_COMMIT and not self.committed:
            self.committed = True
            self.step_index = 0
            return [(0.0, 0, build(KEY_TRADE, KIND_COMMIT)),
                    (0.1, 1, table_update(KEY_EXCHANGE, True)),
                    (0.15, 0, build(KEY_EXCHANGE, KIND_STEP_OPEN, STEPS[0]))]
        if (key == KEY_EXCHANGE and kind == KIND_STEP_OPEN and self.step_index is not None
                and step == STEPS[self.step_index]):
            out = [(0.0, 0, build(KEY_EXCHANGE, KIND_STEP_CLOSE, step))]
            self.step_index += 1
            if self.step_index < len(STEPS):
                out.append((0.05, 0, build(KEY_EXCHANGE, KIND_STEP_OPEN, STEPS[self.step_index])))
            else:
                self.done = True
                out.append((0.2, 1, table_update(KEY_EXCHANGE, False)))
            return out
        return []

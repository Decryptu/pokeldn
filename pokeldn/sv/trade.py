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

`TradeStage` is the host's side as a pure state machine and `JoinerTradeStage` the joiner's:
`on_message(port, payload)` returns what to send, each entry `(delay, port, payload)`, and
`tests/test_sv.py` runs each of them over the emulated pair's own message list, in its own
direction. The delays are the pair's: a confirmation came from a player and is sent here a second
after the offer it answers.
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
    """The host's side of a trade. `offer` is the 348-byte record the host puts up, or a list of
    them: with a list the cycle starts again at the next record when the exchange key closes, so
    one seat carries more than one trade."""

    def __init__(self, offer, confirm_delay=1.0):
        offers = [offer] if isinstance(offer, (bytes, bytearray)) else list(offer)
        if not offers:
            raise ValueError("a host needs at least one offer")
        self.offers = []
        for one in offers:
            one = bytes(one)
            if len(one) != OFFER_SIZE:
                raise ValueError(f"an offer is {OFFER_SIZE} bytes, not {len(one)}")
            self.offers.append(one)
        self.index = 0
        self.trades = 0
        self.joiner_offers = []
        self.confirm_delay = confirm_delay
        self.done = False
        self._start()

    def _start(self):
        """Clear what belongs to one trade."""
        self.joiner_offer = None
        self.offered = False
        self.confirmed = False
        self.committed = False
        self.step_index = None

    @property
    def offer(self):
        return self.offers[self.index]

    def offer_first(self):
        """-> the host's offer, for a host that puts its Pokemon up before the joiner does, as the
        pair's host did (its offer came 9 s before the joiner's)."""
        if self.offered:
            return []
        self.offered = True
        return [(0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, self.offer))]

    def on_message(self, port, payload):
        """-> [(delay, port, payload), ...] to send in answer to what the joiner sent."""
        if self.done:
            return []
        if port == 1:
            # A station sends on a key only once its peer has announced it, so the first
            # exchange step waits for the joiner's own open of key 0x0180. A pair's host sends
            # 80010103 twenty-five milliseconds after that echo, not before it.
            if (self.committed and self.step_index is None
                    and payload == table_update(KEY_EXCHANGE, True)):
                self.step_index = 0
                return [(0.025, 0, build(KEY_EXCHANGE, KIND_STEP_OPEN, STEPS[0]))]
            return []
        if port != 0:
            return []
        m = parse(payload)
        if m is None:
            return []
        key, kind, step, body = m
        if key == KEY_TRADE and kind == KIND_OFFER and len(body) == OFFER_SIZE:
            if self.joiner_offer != body:
                self.joiner_offers.append(body)
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
            # A pair's host answers the commit 83 ms later, not in the same breath: sent at once
            # the message is acknowledged by the station's transport and never dispatched.
            return [(0.09, 0, build(KEY_TRADE, KIND_COMMIT)),
                    (0.19, 1, table_update(KEY_EXCHANGE, True))]
        if (key == KEY_EXCHANGE and kind == KIND_STEP_OPEN and self.step_index is not None
                and step == STEPS[self.step_index]):
            out = [(0.0, 0, build(KEY_EXCHANGE, KIND_STEP_CLOSE, step))]
            self.step_index += 1
            if self.step_index < len(STEPS):
                out.append((0.05, 0, build(KEY_EXCHANGE, KIND_STEP_OPEN, STEPS[self.step_index])))
            else:
                self.trades += 1
                if self.index + 1 < len(self.offers):
                    # A second trade in the same seat, at the next record.
                    self.index += 1
                    self._start()
                else:
                    self.done = True
                out.append((0.2, 1, table_update(KEY_EXCHANGE, False)))
            return out
        return []


class JoinerTradeStage:
    """The joiner's side of a trade, `TradeStage` mirrored.

    `offer` is one 348-byte record or a list of them. With a list the stage runs the cycle again
    at the next record when the exchange key closes, so one seat carries more than one trade.

    A joiner answers rather than leads: it opens key 0x0080 on port 1 once the host has announced
    it, offers when the host's offer arrives, confirms and then commits on its own, opens key
    0x0180 after the host opens it, echoes each step the host starts, and mirrors the close. The
    pair's joiner committed first and its host answered in kind, so the commit is the joiner's to
    send; `commit_delay` is how long after its own confirmation it goes.

    The delays are the pair joiner's: the key-0x80 open after the last identity fragment, the
    confirmation a second after the host's and the commit 1.5 s after that.
    """

    def __init__(self, offer, confirm_delay=1.0, commit_delay=1.5, open_delay=0.35):
        offers = [offer] if isinstance(offer, (bytes, bytearray)) else list(offer)
        if not offers:
            raise ValueError("a joiner needs at least one offer")
        self.offers = []
        for one in offers:
            one = bytes(one)
            if len(one) != OFFER_SIZE:
                raise ValueError(f"an offer is {OFFER_SIZE} bytes, not {len(one)}")
            self.offers.append(one)
        self.index = 0
        self.trades = 0
        self.host_offers = []
        self.confirm_delay = confirm_delay
        self.commit_delay = commit_delay
        self.open_delay = open_delay
        self.opened = False
        self.done = False
        self._start()

    def _start(self):
        """Clear what belongs to one trade. The key-0x80 open belongs to the seat, not to a trade."""
        self.host_offer = None
        self.offered = False
        self.confirmed = False
        self.committed = False
        self.step_index = None

    @property
    def offer(self):
        return self.offers[self.index]

    def offer_first(self):
        """-> the joiner's offer, for a run that puts its Pokemon up before the host does."""
        if self.offered:
            return []
        self.offered = True
        return [(0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, self.offer))]

    def on_message(self, port, payload):
        """-> [(delay, port, payload), ...] to send in answer to what the host sent."""
        if self.done:
            return []
        if port == 1:
            if payload == table_update(KEY_TRADE, True) and not self.opened:
                # The pair's joiner opened the key 206 ms after the host did, after all four
                # of its identity fragments on port 0 rather than between them.
                self.opened = True
                return [(self.open_delay, 1, table_update(KEY_TRADE, True))]
            if (self.committed and self.step_index is None
                    and payload == table_update(KEY_EXCHANGE, True)):
                self.step_index = 0
                return [(0.0, 1, table_update(KEY_EXCHANGE, True))]
            if (self.step_index is not None and self.step_index >= len(STEPS)
                    and payload == table_update(KEY_EXCHANGE, False)):
                self.trades += 1
                if self.index + 1 < len(self.offers):
                    # A second trade in the same seat: the cycle starts again at the next offer,
                    # with the trade key still open. What a console does after a trade closes is
                    # unmeasured.
                    self.index += 1
                    self._start()
                else:
                    self.done = True
                return [(0.0, 1, table_update(KEY_EXCHANGE, False))]
            if payload == table_update(KEY_TRADE, False) and self.opened:
                # The host closing the trade key, mirrored the way every other table update is.
                self.opened = False
                return [(self.open_delay, 1, table_update(KEY_TRADE, False))]
            return []
        if port != 0:
            return []
        m = parse(payload)
        if m is None:
            return []
        key, kind, step, body = m
        if key == KEY_TRADE and kind == KIND_OFFER and len(body) == OFFER_SIZE:
            if self.host_offer != body:
                # Every record the host puts up, in order, one entry per selection it makes. A
                # second trade in the seat starts a fresh entry even for the same record.
                self.host_offers.append(body)
            self.host_offer = body
            if self.offered:
                return []
            self.offered = True
            return [(0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, self.offer))]
        if key == KEY_TRADE and kind == KIND_CONFIRM and not self.confirmed:
            self.confirmed = True
            self.committed = True
            return [(self.confirm_delay, 0, build(KEY_TRADE, KIND_CONFIRM)),
                    (self.commit_delay, 0, build(KEY_TRADE, KIND_COMMIT))]
        if key == KEY_TRADE and kind == KIND_CANCEL:
            self.done = True
            return []
        if (key == KEY_EXCHANGE and kind == KIND_STEP_OPEN and self.step_index is not None
                and self.step_index < len(STEPS) and step == STEPS[self.step_index]):
            self.step_index += 1
            return [(0.0, 0, build(KEY_EXCHANGE, KIND_STEP_OPEN, step))]
        return []


def apply_fields(plain, settings):
    """-> the record with each `FIELD=VALUE` written into it. `shiny` alone rolls the value.

    A name field takes the text as it stands, a comma in the value makes a vector, and an integer
    may be decimal or `0x`-prefixed. The field names are `pokeldn.sv.pokemon`'s.
    """
    from pokeldn.sv import pokemon

    for setting in settings:
        if setting == "shiny":
            fields = pokemon.read(plain)
            plain = pokemon.write(plain, pid=pokemon.shiny_pid(fields["trainer_id"],
                                                               fields["secret_id"]))
            continue
        if "=" not in setting:
            raise ValueError(f"{setting!r} is not FIELD=VALUE")
        key, value = setting.split("=", 1)
        if key in pokemon.NAMES:
            plain = pokemon.write(plain, **{key: value})
        elif "," in value or key in pokemon.VECTORS or key in ("ivs", "stats"):
            plain = pokemon.write(plain, **{key: tuple(int(v, 0) for v in value.split(","))})
        else:
            plain = pokemon.write(plain, **{key: int(value, 0)})
    return plain


def load_offer(raw, settings=()):
    """-> the 348-byte body to offer, from a file's bytes in any of the forms one is kept in.

    Hex text, a 352-byte game message with its header, and a bare stored or party record, plain or
    encrypted, all read; `settings` are `apply_fields`'s.
    """
    from pokeldn.sv import pokemon

    raw = bytes(raw)
    try:
        raw = bytes.fromhex(raw.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        pass
    if len(raw) == OFFER_SIZE + 4:
        raw = raw[4:]
    if len(raw) in (pokemon.SIZE_STORED, pokemon.SIZE_PARTY):
        raw = pokemon.to_wire(pokemon.load(raw))
    if settings:
        raw = pokemon.to_wire(apply_fields(pokemon.from_wire(raw), settings))
    if len(raw) != OFFER_SIZE:
        raise ValueError(f"an offer is {OFFER_SIZE} bytes, not {len(raw)}")
    return raw

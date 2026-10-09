"""The trade on Reliable 0x7C port 0, host and joiner side, as pure state machines (docs/sv.md,
The trade). A game message is a u16 handler key, a kind byte, a step byte and a body; key 0x0080 is
the trade channel, 0x0180 the exchange. `on_message` returns [(delay, port, payload)].
"""

import struct

from pokeldn.ldn import channel_table

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

    def __init__(self, offer, confirm_delay=1.0, partner=None):
        offers = [offer] if isinstance(offer, (bytes, bytearray)) else list(offer)
        # Online (pokeldn.online): our offer is the partner's console's, and our confirm waits for
        # both consoles' (docs/online.md).
        self.partner = partner
        if not offers and partner is None:
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
        self.sent = None                  # online: the partner record the console was shown
        self.console_confirmed = False

    @property
    def offer(self):
        return self.sent if self.partner is not None else self.offers[self.index]

    def offer_first(self):
        """-> the host's offer, for a host that puts its Pokemon up before the joiner does, as the
        pair's host did (its offer came 9 s before the joiner's)."""
        if self.offered or self.partner is not None:
            return []
        self.offered = True
        return [(0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, self.offer))]

    def on_message(self, port, payload):
        """-> [(delay, port, payload), ...] to send in answer to what the joiner sent."""
        if self.done:
            return []
        if port == 1:
            # A station sends on a key only once its peer announced it: the first exchange step
            # waits for the joiner's open of key 0x0180.
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
            if self.partner is not None:
                self.console_confirmed = False
                self.partner.offer(body)
                return []
            out = []
            if not self.offered:
                self.offered = True
                out.append((0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, self.offer)))
            if not self.confirmed:
                self.confirmed = True
                out.append((self.confirm_delay, 0, build(KEY_TRADE, KIND_CONFIRM)))
            return out
        if key == KEY_TRADE and kind == KIND_CONFIRM:
            if self.partner is not None and self.joiner_offer is not None:
                self.console_confirmed = True
                self.partner.accept()
            return []
        if key == KEY_TRADE and kind == KIND_CANCEL and self.partner is not None and not self.committed:
            # 8000040100: the player backed out of the wait (docs/sv.md, The trade).
            self.partner.withdraw()
            self.joiner_offer, self.console_confirmed = None, False
            return []
        if key == KEY_TRADE and kind == KIND_COMMIT and not self.committed:
            self.committed = True
            # Sent at once, the commit answer is acknowledged by the transport and never dispatched.
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
                if self.partner is not None:
                    self.partner.done()
                    self._start()
                elif self.index + 1 < len(self.offers):
                    self.index += 1
                    self._start()
                else:
                    self.done = True
                out.append((0.2, 1, table_update(KEY_EXCHANGE, False)))
            return out
        return []


    def tick(self):
        """Online: -> [(delay, port, payload)] that the partner's progress releases. The partner's
        record goes up once it arrives and comes down when they withdraw it; our confirm goes once
        both consoles have confirmed."""
        if self.partner is None or self.committed:
            return []
        theirs = self.partner.theirs()
        out = []
        if self.offered and theirs.offer != self.sent and not self.confirmed:
            # A host-sent cancel is unmeasured on a console (docs/online.md, Unresolved).
            out.append((0.0, 0, build(KEY_TRADE, KIND_CANCEL, 1, b"\x00")))
            self.offered, self.sent = False, None
        if not self.offered and theirs.offer is not None:
            self.offered, self.sent = True, theirs.offer
            out.append((0.0, 0, build(KEY_TRADE, KIND_OFFER, 0, theirs.offer)))
        if (self.offered and not self.confirmed and self.console_confirmed and theirs.accepted
                and self.joiner_offer is not None):
            self.confirmed = True
            out.append((0.0, 0, build(KEY_TRADE, KIND_CONFIRM)))
        return out


class JoinerTradeStage:
    """The joiner's side of a trade: it answers rather than leads, and commits first, `commit_delay`
    after its own confirmation. `offer` is one 348-byte record or a list, one per trade."""

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
        """Clear what belongs to one trade; the key-0x80 open belongs to the seat."""
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
                # The pair's joiner opened the key 206 ms after the host, after all four identity
                # fragments.
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
                    self.index += 1
                    self._start()
                else:
                    self.done = True
                return [(0.0, 1, table_update(KEY_EXCHANGE, False))]
            if payload == table_update(KEY_TRADE, False) and self.opened:
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
    """-> the record with each `FIELD=VALUE` (`pokeldn.sv.pokemon` names) written; `shiny`
    alone rolls the value, a comma makes a vector."""
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


def load_offer(raw, settings=(), fresh=False):
    """-> the 348-byte body to offer from hex text, a 352-byte message or a stored or party record;
    `fresh` draws a new PID and encryption constant, shiny state kept."""
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
    if fresh:
        raw = pokemon.to_wire(pokemon.fresh_identity(pokemon.from_wire(raw)))
    if len(raw) != OFFER_SIZE:
        raise ValueError(f"an offer is {OFFER_SIZE} bytes, not {len(raw)}")
    return raw

"""Trade back: the trade after each queued one returns the Pokemon the console just sent, so one that
evolves by trade comes home evolved (docs/architecture.md, Trade back).

`Rounds` is the order a launcher offers in: queued offer 1, what the console sent for it, queued offer 2,
what the console sent for that, and so on; the last queued offer serves every later even round, as a
launcher's last offer does. A returned record is the console's bytes, unchanged: never under a new PID.

`TradeBack` takes an online partner's place (pokeldn.online.link.Partner) in a native trade host, as
`pokeldn.receiver_gift.ReceiverGift` does, with each round's record up from the round's start, as a host's
own offer is, and our confirm waiting for the console's alone.
"""

import threading


def add_arguments(ap):
    ap.add_argument("--trade-back", action="store_true",
                    help="after each trade, trade again and offer the Pokemon the console just sent, so one "
                         "that evolves by trade evolves on the console; the player offers ours back "
                         "(docs/architecture.md, Trade back)")


def check(ap, args, offer_flag, *flags):
    """--trade-back needs `offer_flag` for its first trade; with a flag that decides the offers some
    other way it is a usage error."""
    if not getattr(args, "trade_back", False):
        return
    for flag in flags:
        if getattr(args, flag.lstrip("-").replace("-", "_"), None):
            ap.error(f"--trade-back cannot be combined with {flag}")
    if not getattr(args, offer_flag.lstrip("-").replace("-", "_"), None):
        ap.error(f"--trade-back needs {offer_flag} for the first trade")


class Rounds:
    """What each trade of one seat offers, `offers` in the launcher's own send format."""

    def __init__(self, offers, log=print):
        self.offers = [bytes(o) for o in offers]
        self.log = log
        self.round = 0
        self.back = None            # what the console sent in the last queued round

    @property
    def finished(self):
        """Every queued offer went out and came back: a launcher that stops after its last queued trade
        stops here."""
        return self.round >= 2 * len(self.offers)

    @property
    def returning(self):
        return self.round % 2 == 1 and self.back is not None

    def current(self):
        """-> this round's record; None when nothing is queued and nothing is owed back."""
        if self.returning:
            return self.back
        if not self.offers:
            return None
        return self.offers[min(self.round // 2, len(self.offers) - 1)]

    def done(self, received):
        """This round's trade completed with the console sending `received` (None when unknown)."""
        if self.round % 2 == 0:
            self.back = bytes(received) if received is not None else None
            if self.back is None:
                self.log("[trade-back] the console's Pokemon was not kept: the next trade offers the queue")
                self.round += 1
        else:
            self.back = None
        self.round += 1
        if self.returning:
            self.log(f"[trade-back] trade {self.round + 1} returns the console's Pokemon")


class Offer:
    """One round's record as a host reads an online partner's: put up once set, never changed."""

    def __init__(self):
        self.offer = None
        self.accepted = True        # our confirm waits for the console's alone
        self.withdrawn = 0
        self.done = False
        self.refused = ""
        self.shared = {}


class TradeBack:
    """The stand-in partner: each round's record from `Rounds`. The console's last offer before `done` is the
    one its trade sent."""

    state = "paired"
    paired = True
    validate = None

    def __init__(self, game, offers, log=print):
        self.game = game
        self.log = log
        self.rounds = Rounds(offers, log=log)
        if not self.rounds.offers:
            raise ValueError("--trade-back needs an offer for the first trade")
        self.lock = threading.Lock()
        self.theirs_now = self._next()
        self.last = None
        log("[trade-back] each trade is followed by one returning the console's Pokemon")

    def _next(self):
        up = Offer()
        up.offer = self.rounds.current()
        return up

    def theirs(self):
        with self.lock:
            return self.theirs_now

    def offer(self, body):
        with self.lock:
            self.last = bytes(body)

    def withdraw(self):
        pass

    def accept(self):
        pass

    def unaccept(self):
        pass

    def share(self, key, data):
        pass

    def refuse(self, reason):
        self.log(f"[trade-back] refused: {reason}")

    def tick(self):
        pass

    def done(self):
        with self.lock:
            self.rounds.done(self.last)
            self.last = None
            self.theirs_now = self._next()

    def close(self, reason="closed"):
        pass

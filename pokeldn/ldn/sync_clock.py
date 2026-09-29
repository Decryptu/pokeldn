"""Pia Sync Clock Protocol 0x1C, the mesh clock the host controls (docs/lgpe_session.md, The Sync
Clock Protocol). A Let's Go host tears the clone elements down about five seconds after a mesh join
that carries no sync clock traffic."""
import struct

PROTOCOL = 0x1C
MESSAGE_SIZE = 16
TICK_HZ = 19_200_000
INTERVAL = 2.0
# `0x51a920` CloneProtocol::vfunc3 reads the synchronized clock.
__all__ = ["PROTOCOL", "MESSAGE_SIZE", "TICK_HZ", "INTERVAL", "build_request", "parse_message",
           "SyncClock"]


def build_request(tick):
    """The sender's system tick, then eight zero bytes."""
    return struct.pack(">QQ", tick & ((1 << 64) - 1), 0)


def parse_message(payload):
    """-> (tick, clock_ms), or None if not a 16-byte sync clock message; a request's clock is 0."""
    if len(payload) < MESSAGE_SIZE:
        return None
    return struct.unpack_from(">QQ", payload, 0)


class SyncClock:
    """A station's side: a request every two seconds, the median of the last ten round trips as
    the delay. `now` is monotonic seconds."""

    def __init__(self, now, interval=INTERVAL):
        self.interval = interval
        self.next_request = now
        self.pending = {}
        self.round_trips = []
        self.clock_ms = None
        self.at = None
        self.replies = 0

    def tick(self, now):
        return int(now * TICK_HZ) & ((1 << 64) - 1)

    def poll(self, now):
        """-> [payload] to send now."""
        if now < self.next_request:
            return []
        self.next_request = now + self.interval
        t = self.tick(now)
        self.pending[t] = now
        return [build_request(t)]

    def receive(self, payload, now):
        """Take the host's reply; nothing is sent in answer."""
        m = parse_message(payload)
        if m is None:
            return []
        tick, clock = m
        sent = self.pending.pop(tick, None)
        if sent is None or clock == 0:
            return []
        self.round_trips.append(now - sent)
        del self.round_trips[:-10]
        rtt = sorted(self.round_trips)[len(self.round_trips) // 2]
        self.clock_ms = clock + int(rtt * 1000 / 2)
        self.at = now
        self.replies += 1
        return []

    def now_ms(self, now):
        """-> the mesh clock in ms, or None before the first reply."""
        if self.clock_ms is None:
            return None
        return self.clock_ms + int((now - self.at) * 1000)

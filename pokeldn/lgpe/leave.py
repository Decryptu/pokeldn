"""A joiner leaving a Let's Go trade session the way a retail console does (docs/lgpe_session.md,
"A joiner leaving"): the offered clone published with 4 in its state word, argument 0 and then 3;
its clones released with a 0x83 each, repeated every 100 ms until the host's 0x84; the mesh leave
request on the mesh protocol's reliable port; then the station disconnection, either way round."""
import struct

from pokeldn.ldn import clone, reliable3
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn.station_protocol import DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE
from pokeldn.ldn import station9

__all__ = ["Leaver"]

RELEASE_ORDER = (1, 0, 2, 3)
# the console's own pause between its last release and its leave request, measured three times
LEAVE_AFTER_RELEASES = 2.45


class Leaver:
    """Drives one station's exit. `poll(now)` -> [(payload, protocol, port)] to send;
    `receive(protocol, payload)` takes what the host answers. `done` once the disconnection is
    answered or given up on."""

    def __init__(self, participant, offered_clone, step, tail, counter, station=1,
                 host_bit=1, clone_ids=RELEASE_ORDER):
        self.p = participant
        self.offered = offered_clone
        self.step, self.tail, self.counter = step, tail, counter
        self.station = station
        self.host_bit = host_bit
        self.clone_ids = list(clone_ids)
        self.t0 = None
        self.sent_state = 0
        self.released = {}          # clone id -> last send time
        self.acked = set()
        self.leave_sent = None
        self.leave_answered = False
        self.leave_next = 0.0
        self.disconnect_at = None
        self.disconnect_sent = None
        self.done = False
        self.log = []

    def _state4(self, now, arg):
        self.counter += 1
        data = (b"\x04\0\0\0" + struct.pack("<III", arg, self.counter, self.step)
                + struct.pack("<I", self.tail))
        rec = clone.build_state_record(self.offered, self.station, 3, self.p.ms(now), data)
        return clone.build_data_message(clone.STATE_DATA, 2, self.station, self.offered,
                                        self.p.frame(now), rec, flags=3)

    def _release(self, cid, now):
        ctype = 3 if cid == 0 else 4
        return self.p._command(clone.COMMAND_END, ctype, 0xFD, cid, now, dest=self.host_bit)

    def poll(self, now):
        if self.done:
            return []
        if self.t0 is None:
            self.t0 = now
        t = now - self.t0
        out = []
        if self.sent_state == 0:
            self.sent_state = 1
            out.append((self._state4(now, 0), clone.PROTOCOL, 0))
            self.log.append("state 4, argument 0")
        elif self.sent_state == 1 and t >= 1.0:
            self.sent_state = 2
            out.append((self._state4(now, 3), clone.PROTOCOL, 0))
            self.log.append("state 4, argument 3")
        elif self.sent_state == 2 and t >= 1.5:
            for cid in self.clone_ids:
                if cid in self.acked:
                    continue
                if now - self.released.get(cid, -1.0) >= 0.1:
                    self.released[cid] = now
                    out.append((self._release(cid, now), clone.PROTOCOL, 0))
            if self.leave_sent is None and (
                    all(cid in self.acked for cid in self.clone_ids) or t >= 1.5 + 3.0):
                self.leave_sent = now
                self.leave_next = now + LEAVE_AFTER_RELEASES
        if self.leave_sent is not None and not self.leave_answered and now >= self.leave_next:
            self.leave_next = now + 0.5
            msg = reliable3.build(bytes([mp.LEAVE_REQUEST, self.station]),
                                  reliable3.FIRST_SEQUENCE, reliable3.FIRST_SEQUENCE)
            out.append((msg, mp.PROTOCOL, 1))
            if not self.log or self.log[-1] != "leave request":
                self.log.append("leave request")
        if (self.leave_answered and self.disconnect_sent is None and self.disconnect_at is not None
                and now >= self.disconnect_at):
            self.disconnect_sent = now
            out.append((bytes([DISCONNECTION_REQUEST]), station9.PROTOCOL, 0))
            self.log.append("disconnection request, ours")
        if self.disconnect_sent is not None and now - self.disconnect_sent >= 4.0:
            self.done = True
            self.log.append("given up on the disconnection response")
        return out

    def receive(self, protocol, payload, now):
        """-> [(payload, protocol, port)] to answer with."""
        if protocol == clone.PROTOCOL and len(payload) > 1 and payload[1] == clone.COMMAND_END_ACK:
            c = clone.parse_command(payload)
            if c:
                self.acked.add(c["clone_id"])
        elif protocol == mp.PROTOCOL and payload and payload[0] == mp.LEAVE_RESPONSE:
            if not self.leave_answered:
                self.leave_answered = True
                # a host that closes the connection sends its disconnection request within a
                # frame; the console sent its own after five seconds
                self.disconnect_at = now + 5.0
                self.log.append("leave response")
        elif protocol == station9.PROTOCOL and payload:
            if payload[0] == DISCONNECTION_REQUEST:
                self.done = True
                self.log.append("the host's disconnection request; answered")
                return [(bytes([DISCONNECTION_RESPONSE]), station9.PROTOCOL, 0)]
            if payload[0] == DISCONNECTION_RESPONSE and self.disconnect_sent is not None:
                self.done = True
                self.log.append("disconnection response")
        return []

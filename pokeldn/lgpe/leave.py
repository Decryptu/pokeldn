"""A joiner leaving a Let's Go trade session the way a retail console does (docs/lgpe_session.md,
"A joiner leaving")."""
import struct

from pokeldn.ldn import clone, reliable3
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn.station_protocol import DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE
from pokeldn.ldn import station9

__all__ = ["Leaver", "host_departure", "unagreed_vote"]

RELEASE_ORDER = (1, 0, 2, 3)
# The console's pause between its last release and its leave request, measured three times.
LEAVE_AFTER_RELEASES = 2.45


class Leaver:
    """Drives one station's exit. `poll(now)` -> [(payload, protocol, port)] to send;
    `receive(protocol, payload)` takes what the host answers. `done` once the disconnection is
    answered or given up on."""

    def __init__(self, participant, offered_clone, step, tail, counter, station=1,
                 host_bit=1, clone_ids=RELEASE_ORDER, host_index=0):
        self.p = participant
        self.host_index = host_index
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
        rec = clone.build_state_record(self.offered, self.station, 3,
                                         self.p.record_clock(2, self.offered, now), data)
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
        if self.disconnect_sent is not None and now - self.disconnect_sent >= 2.0:
            self.done = True
            self.log.append("given up on the disconnection response")
        return out

    def receive(self, protocol, payload, now):
        """-> [(payload, protocol, port)] to answer with."""
        if protocol == clone.PROTOCOL and len(payload) > 1 and payload[1] == clone.COMMAND_END_ACK:
            c = clone.parse_command(payload)
            if c:
                self.acked.add(c["clone_id"])
        elif protocol == mp.PROTOCOL and bytes(payload) == bytes([mp.LEAVE_RESPONSE,
                                                                  self.host_index]):
            # The console's handler 0x591bf4 takes only the host's index at [1].
            if not self.leave_answered:
                self.leave_answered = True
                # A retail host migrates every 0.3 s and waits five seconds for the leaver, so the
                # disconnection request goes at once.
                self.disconnect_at = now + 0.05
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


def host_departure(protocol, payload, station_index):
    """-> (replies, leave) for a console host that leaves: the migration start's ack and `48 <own
    index>` (wait 0x58aeb0, 5 s unanswered); `leave` on START_HOST_MIGRATION, repeated until no
    station is on the network (0x5d3fd0, 10 s). docs/lgpe_session.md, A host leaving."""
    payload = bytes(payload)
    if protocol == mp.PROTOCOL and len(payload) > reliable3.HEADER_SIZE:
        r = reliable3.parse(payload)
        if r and r["size"] and mp.parse_migration_start(r["payload"]) is not None:
            return ([(reliable3.build_ack(r["sequence"] + 1), mp.PROTOCOL, 1),
                     (mp.build_migration_response(station_index), mp.PROTOCOL, 0)], False)
    if protocol == lp.PROTOCOL and len(payload) >= lp.HEADER_SIZE:
        try:
            kind, _ = lp.parse_header(payload)
        except ValueError:
            return [], False
        return [], kind == lp.START_HOST_MIGRATION
    return [], False


def unagreed_vote(participant):
    """-> the clone both stations vote on with one argument while the session host's A differs,
    else None. The host's authority (main 0x11b6c0) moves A within one tick of agreement
    (docs/lgpe_session.md, The two clone records a trade walks)."""
    p = participant
    for cid, theirs in p.shared.items():
        ours = p.our_data(cid)
        if (len(theirs) >= 20 and theirs[:4] == ours[:4] == b"\x01\0\0\0"
                and theirs[4:8] == ours[4:8] and theirs[16:20] == ours[16:20]
                and p.agreed.get(cid, bytes(4))[:4] != theirs[4:8]):
            return cid
    return None

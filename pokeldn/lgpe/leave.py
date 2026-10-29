"""A joiner leaving a Let's Go trade session the way a retail console does (docs/lgpe_session.md,
"A joiner leaving")."""
import struct

from pokeldn.ldn import clone, reliable3
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn.station_protocol import DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE
from pokeldn.ldn import station9

__all__ = ["HostLeaver", "Leaver", "host_departure", "unagreed_vote"]

RELEASE_ORDER = (1, 0, 2, 3)
# The console's pause between its last release and its leave request, measured three times.
LEAVE_AFTER_RELEASES = 2.45
# `LeaveMeshJob` deauthenticates 5.0 s after its first unanswered leave request.
LEAVE_UNANSWERED = 5.0


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
        self.leave_first = None
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
        if (self.leave_first is not None and not self.leave_answered
                and now - self.leave_first >= LEAVE_UNANSWERED):
            self.done = True
            self.log.append("given up on the leave response")
            return out
        if self.leave_sent is not None and not self.leave_answered and now >= self.leave_next:
            self.leave_next = now + 0.5
            if self.leave_first is None:
                self.leave_first = now
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


# A console host leaving (docs/lgpe_session.md, A host leaving); both messages are byte for byte the
# ones tests/test_lgpe_leave.py holds from an emulated pair and a retail host.
MIGRATION_START = reliable3.build(bytes([mp.MIGRATION_START, 0, 1]), reliable3.FIRST_SEQUENCE,
                                  reliable3.FIRST_SEQUENCE)
START_HOST_MIGRATION = bytes([1, lp.START_HOST_MIGRATION]) + bytes(14)
# The teardown's idle wait, 150 calls (0x116bc0, docs/lgpe_session.md, The wait before leaving).
IDLE_WAIT = 2.5


class HostLeaver:
    """Drives a host's exit after its state 4, argument 3: the releases, the migration start every
    45 ms for 5 s until `48 01`, then start host migration every 301 ms for 10 s until no station is
    left. `poll(now, stations)` -> [(payload, protocol, port, broadcast)]; `done` once over."""

    def __init__(self, participant, now, clone_ids=RELEASE_ORDER):
        self.p = participant
        self.t0 = now
        self.clone_ids = [c for c in clone_ids if participant is not None
                          and (c in participant.held or c == 0)]
        self.released = {}
        self.acked = set()
        self.migration_at = self.migration_next = None
        self.answered = False
        self.start_at = self.start_next = None
        self.done = False
        self.log = []

    def poll(self, now, stations):
        if self.done:
            return []
        out = []
        if self.migration_at is None:
            if now - self.t0 < 0.5:
                return out
            for cid in self.clone_ids:
                if cid not in self.acked and now - self.released.get(cid, -1.0) >= 0.1:
                    if cid not in self.released:
                        self.log.append(f"release {cid}")
                    self.released[cid] = now
                    out += [(m, clone.PROTOCOL, 0, False) for m in self.p.release(cid, now)]
            if all(c in self.acked for c in self.clone_ids) or now - self.t0 >= 0.5 + IDLE_WAIT:
                self.migration_at = self.migration_next = now
                self.log.append("migration start")
        if self.start_at is None and self.migration_at is not None:
            if self.answered or now - self.migration_at >= 5.0 or not stations:
                self.start_at = self.start_next = now
                self.log.append("start host migration" + ("" if self.answered else ", unanswered"))
                out.append((None, lp.PROTOCOL, 0, True))     # the update session, migration state 1
            elif now >= self.migration_next:
                self.migration_next = now + 0.045
                out.append((MIGRATION_START, mp.PROTOCOL, 1, False))
        if self.start_at is not None:
            if not stations or now - self.start_at >= 10.0:
                self.done = True
                self.log.append("no station left" if not stations else "given up after 10 s")
            elif now >= self.start_next:
                self.start_next = now + 0.301
                out.append((START_HOST_MIGRATION, lp.PROTOCOL, 0, True))
        return out

    def receive(self, protocol, payload):
        payload = bytes(payload)
        if protocol == clone.PROTOCOL and len(payload) > 1 and payload[1] == clone.COMMAND_END_ACK:
            c = clone.parse_command(payload)
            if c:
                self.acked.add(c["clone_id"])
        elif protocol == mp.PROTOCOL and len(payload) == 2 and payload[0] == mp.MIGRATION_RESPONSE:
            if not self.answered:
                self.log.append(f"migration response {payload[1]}")
            self.answered = True


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

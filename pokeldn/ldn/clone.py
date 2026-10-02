"""Pia Clone Protocol (protocol 0x73), the mesh's synchronized-object layer; Let's Go runs its
partner sync on it. `Participant` runs the measured exchange (docs/lgpe_session.md, "The Clone
Protocol")."""
import struct
import zlib

PROTOCOL = 0x73
VERSION = 3

CLOCK_REQUEST = 0x11
CLOCK_REPLY = 0x21
PARTICIPATE = 0x31
EXIT_ACK = 0x41
CLOCK_REPLY_SYNCED = 0x22
PARTICIPATE_ACK = 0x33
EXIT_REQUEST = 0x32
COMMAND_ANNOUNCE = 0x81
COMMAND_REQUEST = 0x82
COMMAND_END = 0x83
COMMAND_END_ACK = 0x84
CLOCK_COMMAND = 0x91
CLOCK_AND_COUNT = 0xA1
CLOCK_AND_COUNT_2 = 0xA2
CLOCK_AND_PARTICIPANT = 0xB1
CLOCK_COUNT_PARTICIPANT = 0xC1
STATE_ACK = 0xE3
STATE_DATA = 0xF3
RECORD_TAG = 0x20
# Twenty bytes with a single 1 at offset 12, the same from both stations of a real session.
SHARED_CLONE_DATA = bytes(12) + b"\x01" + bytes(7)


def shared_clone_data(state_word):
    """The 20-byte data a clone type 2 copy carries. Byte 12 is the station's state word."""
    return bytes(12) + bytes([state_word]) + bytes(7)
RECORD_EMPTY = 0x01                 # a clone that has no data yet: six bytes, no clock
RECORD_STATE = 0x03
RECORD_ACK = 0x05
TICK_HZ = 19_200_000
FRAME_HZ = 60

__all__ = ["PROTOCOL", "VERSION", "CLOCK_REQUEST", "CLOCK_REPLY", "CLOCK_REPLY_SYNCED",
           "PARTICIPATE", "PARTICIPATE_ACK", "EXIT_ACK", "parse_clock_request", "parse_clock_reply",
           "build_clock_request", "build_clock_reply", "reply_to", "build_participate",
           "build_command", "parse_command", "build_empty_record", "RECORD_EMPTY",
           "RECORD_STATE", "RECORD_ACK",
           "Participant"]


def parse_clock_request(payload):
    """-> dict of the clock request's fields, or None if it is not a type-0x11 clone message."""
    if len(payload) < 0x12 or payload[0] != VERSION or payload[1] != CLOCK_REQUEST:
        return None
    field_a, count, participant = struct.unpack_from(">HIH", payload, 2)
    clock = struct.unpack_from(">Q", payload, 0xA)[0]
    return {"version": payload[0], "type": payload[1], "field_a": field_a, "count": count,
            "participant": participant, "clock": clock}


def parse_clock_reply(payload):
    """-> dict of a clock reply's fields (type 0x21 or 0x22), or None."""
    if len(payload) < 0x16 or payload[0] != VERSION or payload[1] not in (CLOCK_REPLY,
                                                                          CLOCK_REPLY_SYNCED):
        return None
    field_a, count, participant, ms = struct.unpack_from(">HIHI", payload, 2)
    clock = struct.unpack_from(">Q", payload, 0xE)[0]
    return {"type": payload[1], "field_a": field_a, "count": count, "participant": participant,
            "ms": ms, "clock": clock}


def build_clock_request(field_a, count, participant, clock):
    """The 18-byte clock request (type 0x11), fields in the order 0x51f9b0 writes them."""
    return (bytes([VERSION, CLOCK_REQUEST]) + struct.pack(">HIH", field_a & 0xFFFF,
            count & 0xFFFFFFFF, participant & 0xFFFF) + struct.pack(">Q", clock & ((1 << 64) - 1)))


def build_clock_reply(field_a, count, participant, clock, extra=0, kind=CLOCK_REPLY):
    """The 22-byte clock reply (type 0x21, or 0x22 once participating), fields in the order
    0x51fab0 writes them: `extra` is the replier's clone clock in ms, `clock` the request's tick."""
    return (bytes([VERSION, kind]) + struct.pack(">HIH", field_a & 0xFFFF,
            count & 0xFFFFFFFF, participant & 0xFFFF) + struct.pack(">I", extra & 0xFFFFFFFF)
            + struct.pack(">Q", clock & ((1 << 64) - 1)))


def reply_to(request_payload, extra=0):
    """-> the clock reply bytes for a clock request, echoing its fields. None if not a request."""
    r = parse_clock_request(request_payload)
    if r is None:
        return None
    return build_clock_reply(r["field_a"], r["count"], r["participant"], r["clock"], extra)


def build_participate(field_a=0, value=0, participant=0, kind=PARTICIPATE):
    """The 10-byte participate message (type 0x31) or its ack (0x33), fields in the order 0x51fbd0
    writes them: version 3, type, the frame counter, the message count, the destination bitmap."""
    return (bytes([VERSION, kind]) + struct.pack(">HIH", field_a & 0xFFFF,
            value & 0xFFFFFFFF, participant & 0xFFFF))


def pack_record(record, level=5):
    """A clone record as the game deflates it: one compress, a sync flush, then the final block.
    Reproduces every captured stream byte for byte."""
    co = zlib.compressobj(level, zlib.DEFLATED, 15)
    return co.compress(record) + co.flush(zlib.Z_SYNC_FLUSH) + co.flush(zlib.Z_FINISH)


def build_empty_record(clone_id, participants=1):
    """The record a station publishes for a clone whose copy is still empty: six bytes. A host
    publishes this before the filled one."""
    return bytes([RECORD_TAG, 6]) + struct.pack(">HBB", clone_id & 0xFFFF, participants & 0xFF, 0)


def build_state_record(clone_id, station, participants, clock, data=b""):
    """The record an 0xfN carries: the clone's data with the clock it is true at."""
    body = struct.pack(">HBBHHI", clone_id & 0xFFFF, RECORD_STATE, station & 0xFF, 0,
                       participants & 0xFFFF, clock & 0xFFFFFFFF) + data
    return bytes([RECORD_TAG, len(body) + 2]) + body


def build_ack_record(clone_id, station, clock):
    """The ten-byte record an 0xeN carries: the clone and station acked, and the clock."""
    return bytes([RECORD_TAG, 10]) + struct.pack(">HBBI", clone_id & 0xFFFF, RECORD_ACK,
                                                 station & 0xFF, clock & 0xFFFFFFFF)


def parse_record(record):
    """-> dict of a clone record's fields, or None. `kind` 1 is a clone with no data yet, 3 a
    state and 5 an acknowledgement."""
    if len(record) < 6 or record[0] != RECORD_TAG or record[1] != len(record):
        return None
    clone_id, kind, station = struct.unpack_from(">HBB", record, 2)
    if kind == RECORD_EMPTY:
        return {"clone_id": clone_id, "kind": kind, "station": station, "clock": None,
                "data": b""}
    if len(record) < 8:
        return None
    if kind == RECORD_ACK:
        return {"clone_id": clone_id, "kind": kind, "station": station,
                "clock": struct.unpack_from(">I", record, 6)[0], "data": b""}
    participants, clock = struct.unpack_from(">HI", record, 8)
    return {"clone_id": clone_id, "kind": kind, "station": station,
            "participants": participants, "clock": clock, "data": record[14:]}


def build_data_message(kind, ctype, station, clone_id, frame, record, flags=None):
    """An 0xeN (13-byte header) or 0xfN (14-byte header) carrying a deflated record."""
    head = (bytes([VERSION, kind]) + struct.pack(">HBBHI", frame & 0xFFFF, ctype & 0xFF,
            station & 0xFF, 0, clone_id & 0xFFFFFFFF))
    if (kind & 0xF0) == 0xF0:
        head += struct.pack(">H", flags if flags is not None else 0)
    else:
        head += bytes([flags if flags is not None else 0])
    return head + pack_record(record)


def parse_data_message(payload):
    """-> dict of an 0xdN/0xeN/0xfN message with its record inflated, or None."""
    if len(payload) < 14 or payload[0] != VERSION or payload[1] < 0xD0:
        return None
    ctype, station = payload[4], payload[5]
    clone_id = struct.unpack_from(">I", payload, 8)[0]
    off = 14 if (payload[1] & 0xF0) == 0xF0 else 13
    try:
        record = zlib.decompress(payload[off:])
    except zlib.error:
        return None
    return {"type": payload[1], "frame": struct.unpack_from(">H", payload, 2)[0], "ctype": ctype,
            "station": station, "clone_id": clone_id, "flags": payload[12:off],
            "record": parse_record(record), "raw": record}


def build_exit_ack(frame, count, dest, stations):
    """The 14-byte exit ack (type 0x41): the answer to an exit request (0x32). `stations` is the
    sender's own station bitmap."""
    return (bytes([VERSION, EXIT_ACK]) + struct.pack(">HIHI", frame & 0xFFFF, count & 0xFFFFFFFF,
            dest & 0xFFFF, stations & 0xFFFFFFFF))


def build_command(kind, ctype, station, clone_id, count, dest, payload=b""):
    """A clone command message (types 0x81 and up), header per CloneCommandMessage::Serialize
    (0x51f820) with `payload` after the 18-byte header."""
    return (bytes([VERSION, kind]) + struct.pack(">HBBHIIH", 0, ctype & 0xFF, station & 0xFF, 0,
            clone_id & 0xFFFFFFFF, count & 0xFFFFFFFF, dest & 0xFFFF) + payload)


def parse_command(payload):
    """-> dict of a clone command message's header and payload, or None."""
    if len(payload) < 0x12 or payload[0] != VERSION or payload[1] < 0x80:
        return None
    frame, ctype, station, _, clone_id, count, dest = struct.unpack_from(">HBBHIIH", payload, 2)
    return {"type": payload[1], "frame": frame, "ctype": ctype, "station": station,
            "clone_id": clone_id, "count": count, "dest": dest, "payload": payload[0x12:]}


class Participant:
    """One side of the measured clock exchange. `now` is a monotonic clock in seconds; `dest` is
    the peer's station bitmap. Feed every 0x73 payload to `receive`, call `poll` a few times a
    second, and send what both return."""

    def __init__(self, now, dest=0x0001, own=0x0002, station=1, request_interval=0.2,
                 requests_before_participate=10):
        self.t0 = now
        self.dest = dest
        self.own = own
        self.station = station
        self.exited = False
        self.count = 0
        self.next_request = now + 0.06
        self.request_interval = request_interval
        self.answered = 0
        self.participate_after = requests_before_participate
        self.participated = False
        self.peer_participated = False
        self.peer_participated_at = None
        self.announced = False
        self.mesh_ms = None
        self.contents = {}
        self.shared = {}
        self.published = set()
        self.mirrored = {}
        self.publish_deadline = {}
        self.announce_clocks = {}
        self.taken_over = {}
        # Clones this station announced itself; the peer takes them over (docs/lgpe_session.md).
        self.owned = set()
        self.owned_answered = set()
        # Byte 12 of a clone type 2 copy's data: both stations walk it 0, 1, 2 and offer at 2.
        self.state_word = 1
        self.held = set()
        # (when, clone id) answers owed to the peer's announcement of an owned clone. Built in poll:
        # the clock it carries arrives in the 0xa1 behind the 0x81, in the same datagram.
        self.answer_owned = []
        # The trailing u32 of a clone type 2 copy's data, when driven past the peer's.
        self.tail = {}
        # The first three words of a clone type 2 copy's data, when driven past the peer's: 01 01 01
        # on selection, then 01 02 02.
        self.flags = {}
        # The first word of a clone type 4 copy when it differs from the flags' second word: the
        # peer's own argument, echoed at state word 4.
        self.arg = {}
        # A clone type 4 copy's words 1 to 5: B, then per station index the counter of the vote the
        # authority last saw withdrawn (Let's Go main 0x11b6c0).
        self.votes = {}
        self.queue = []
        self.log = []
        # clone id -> (next resend, resends): our peer-only announcement until the peer's 0x82.
        self.unrequested = {}
        # Resends and withheld frames, for the launcher to print.
        self.events = []
        self.withhold_clone0_answers = set()
        # clone id -> the session host's clone type 4 data: A, the agreed argument, first.
        self.agreed = {}

    def frame(self, now):
        return int((now - self.t0) * FRAME_HZ) & 0xFFFF

    def tick(self, now):
        return int(now * TICK_HZ)

    def element_ms(self, now):
        """Milliseconds since this station's clone session started, the clone elements' clock."""
        return int((now - self.t0) * 1000)

    def ms(self, now):
        """The clock a clone message carries: the mesh clock from the Sync Clock Protocol once
        the host has answered one, our own elapsed milliseconds before that."""
        if self.mesh_ms is not None:
            return self.mesh_ms
        return int((now - self.t0) * 1000)

    def _next_count(self):
        self.count += 1
        return self.count

    def poll(self, now):
        """-> [payload] to send now: a clock request on its interval, the participate once due."""
        out = []
        # A station stops requesting the clock once it participates: the reference host sent its
        # last at 3.343 s, participated at 3.406, and sent none in the remaining 438 s.
        if not self.participated and now >= self.next_request:
            self.next_request = now + self.request_interval
            out.append(build_clock_request(self.frame(now), self._next_count(), self.dest,
                                           self.tick(now)))
        if self.host_role:
            # A host participates 1.1 s after the joiner did.
            due = (self.peer_participated
                   and now >= self.peer_participated_at + self.participate_delay)
        else:
            due = self.answered >= self.participate_after
        if not self.participated and due:
            self.participated = True
            out.append(build_participate(self.frame(now), self._next_count(), 0x0003))
        for when, cid in list(self.answer_owned):
            if now < when:
                continue
            self.answer_owned.remove((when, cid))
            out.extend(self._owned_answer(cid, now))
        for cid, when in list(self.publish_deadline.items()):
            if now >= when:
                del self.publish_deadline[cid]
                self.queue.append((now, 2, self.station, cid, STATE_DATA, None, None))
        for item in list(self.queue):
            when, ctype, station, clone_id, kind, content, qdest = item
            if now < when:
                continue
            self.queue.remove(item)
            if kind == STATE_DATA:
                if clone_id in self.published:
                    continue
                self.published.add(clone_id)
                out.append(build_data_message(
                    STATE_DATA, ctype, station, clone_id, self.frame(now),
                    build_state_record(clone_id, station, 3, self.ms(now),
                                       self.our_data(clone_id)),
                    flags=3))
                self.held.add(clone_id)
                continue
            payload = content or b""
            if kind == COMMAND_ANNOUNCE and qdest is None and clone_id not in self.unrequested:
                self.unrequested[clone_id] = (now + self.announce_retry, 0)
                if self.withhold_announces > 0:
                    # Test only: as if this frame were lost, so the resend below carries it.
                    self.withhold_announces -= 1
                    self.events.append(f"withheld our announcement of clone {clone_id}")
                    continue
            if kind == CLOCK_AND_COUNT:
                # As late as possible: the host's announcements arrive in the same packet as the one
                # that queued this.
                payload = (self.contents.get((ctype, station, clone_id))
                           or self.contents.get((4, 0xFD, clone_id))
                           or self.contents.get((1, 0xFD, clone_id)) or b"\x01\0\0\0")
                payload = struct.pack(">I", self.ms(now)) + payload
            elif kind == CLOCK_COMMAND:
                echo = self.announce_clocks.get(clone_id) if self.echo_takeover_clock else None
                echo = echo or struct.pack(">I", self.ms(now))
                self.taken_over[clone_id] = echo
                payload = echo + payload
            elif kind == CLOCK_AND_COUNT_2 and not payload:
                # The take-over's sequence, shaped like a peer's own 0xa2.
                echo = (self.announce_clocks.get(clone_id)
                        or struct.pack(">I", self.ms(now)))
                payload = echo + struct.pack(">BBH", 0, 0, self.element_ms(now) & 0xFFFF)
            out.append(self._command(kind, ctype, station, clone_id, now, payload, qdest))
        for cid, (when, sent) in list(self.unrequested.items()):
            if now < when or sent is None:
                continue
            if sent >= self.announce_retries:
                self.unrequested[cid] = (when, None)
                continue
            self.unrequested[cid] = (now + self.announce_retry, sent + 1)
            self.events.append(f"resent our announcement of clone {cid} ({sent + 1})")
            out.append(self._command(COMMAND_ANNOUNCE, 2, self.station, cid, now))
        if (self.participated and self.peer_participated_ack and not self.announced
                and not self.host_role):
            # A joiner sends this 6 ms after the host's 0x33: an 0xa1 for type-3 clone 0, count 1.
            self.announced = True
            out.append(self._command(CLOCK_AND_COUNT, 3, 0xFD, 0, now,
                                     struct.pack(">IB", self.ms(now), 1) + b"\0\0\0"))
        return out

    peer_participated_ack = False
    # Host side: participate after the peer, answer its first clone 0 announcement with 0x91, never
    # announce clone 0 (docs/lgpe_session.md).
    host_role = False
    participate_delay = 1.1
    request_publishes_type4 = False
    # A retail pair publishes no clone data on clone types 4 and 1; the trade object stages what
    # arrives there (main 0x11b688, 0x11ba20).
    publish_type4 = False
    announce_mesh_dest = True
    echo_takeover_clock = True
    takeover_per_sequence = True
    ack_peer_clock = False
    ack_re_announcement = False
    publish_once = False
    # Set once the peer releases clone 0, as it leaves (docs/lgpe_session.md, Leaving).
    peer_released = False
    publish_delay = 0.09
    ack_in_burst = False
    ack_early = False
    publish_on_announce = False
    publish_fallback = 3.0
    announce_in_burst = True
    # Our announcement to the peer alone goes out once; one lost frame, ours or its 0x82, leaves
    # both waiting on the confirmation screen (docs/lgpe_session.md, The take-over exchange).
    announce_retry = 0.1
    announce_retries = 20
    withhold_announces = 0

    def _mirror_announce(self, c, now, takeover_only=False):
        """Take the host's clone over on three clone types, then announce our own copy of it, in
        a real joiner's order."""
        cid = c["clone_id"]
        seq = self.announce_clocks.get(cid)
        key = (cid, seq) if self.takeover_per_sequence else (cid, None)
        if now - self.mirrored.get(key, -1e9) < 1.0:
            return []
        self.mirrored[key] = now
        out = []
        at = now if self.announce_in_burst else now + 0.01
        burst = ((1, 0xFD, COMMAND_REQUEST), (4, 0xFD, CLOCK_COMMAND),
                 (2, self.station, CLOCK_COMMAND), (4, 0xFD, COMMAND_END_ACK))
        if self.ack_early:
            # The ack goes directly behind the take-overs: the burst spans datagrams, and one
            # datagram earlier counts against a ~30 ms unlink.
            burst = (burst[0], burst[1], burst[2], (2, self.station, CLOCK_AND_COUNT_2), burst[3])
        elif self.ack_in_burst:
            # The 0xa2 drives completion; sent as a reply it trails the burst by 24 ms and loses to
            # the per-tick unlink (docs/lgpe_session.md).
            burst = burst + ((2, self.station, CLOCK_AND_COUNT_2),)
        if takeover_only:
            # A re-announcement gets the take-overs alone: a repeated 0x82 makes the peer mint a new
            # sequence (0x520c30) it then fails to match (docs/lgpe_session.md).
            burst = ((4, 0xFD, CLOCK_COMMAND), (2, self.station, CLOCK_COMMAND))
        for ctype, station, kind in burst:
            self.queue.append((at, ctype, station, cid, kind, None, None))
        if takeover_only:
            return out
        # Take-over and own announcement share one frame; the announce's dest is the whole mesh, the
        # clock-and-counts only the peer (0x51f820).
        self.queue.append((at, 2, self.station, cid, COMMAND_ANNOUNCE, None,
                           (self.own | self.dest) if self.announce_mesh_dest else None))
        for ctype in (4, 1):
            self.queue.append((at, ctype, 0xFD, cid, CLOCK_AND_COUNT, None, None))
        if self.publish_on_announce:
            self.queue.append((now + self.publish_delay, 2, self.station, cid, STATE_DATA,
                               None, None))
        else:
            # A real joiner publishes its type 2 copy 0.04 s after the peer's; the deadline is an
            # unmeasured fallback.
            self.publish_deadline[cid] = now + self.publish_fallback
        return out

    def our_data(self, clone_id):
        """The 20 bytes our clone type 2 copy of `clone_id` carries: the peer's own, with our
        state word written over byte 12."""
        data = self.shared.get(clone_id, SHARED_CLONE_DATA)
        tail = self.tail.get(clone_id)
        out = (self.flags.get(clone_id) or data[:12]) + bytes([self.state_word]) + data[13:16]
        return out + (struct.pack("<I", tail) if tail is not None else data[16:20])

    def type4_data(self, clone_id):
        """The 32 bytes a clone type 4 copy carries, staged and compared by the trade object (main
        0x11b688, 0x11ba20): the type 2 state's second word at +0x00, the step at +0x18, the
        trailing word at +0x1c (docs/lgpe_session.md)."""
        flags = self.flags.get(clone_id) or self.shared.get(clone_id, SHARED_CLONE_DATA)[:12]
        arg = self.arg.get(clone_id) or (flags[4:8] if len(flags) >= 8 else bytes(4))
        return arg + self.votes.get(clone_id, bytes(0x14)) + struct.pack("<I", self.state_word) + \
            struct.pack("<I", self.tail.get(clone_id, 0))

    def advance_state(self, now, state_word):
        """-> the clone type 2 copies to resend when the state word moves: the reference pair
        republishes every held copy in one frame (docs/lgpe_session.md)."""
        self.state_word = state_word
        out = []
        for cid in sorted(self.held):
            out.append(build_data_message(
                STATE_DATA, 2, self.station, cid, self.frame(now),
                build_state_record(cid, self.station, 3, self.ms(now), self.our_data(cid)),
                flags=3))
            if self.publish_type4:
                out.append(build_data_message(
                    STATE_DATA, 4, 0xFD, cid, self.frame(now),
                    build_state_record(cid, self.station, 3, self.ms(now),
                                       self.type4_data(cid)), flags=3))
        return out

    def _answer_takeover(self, c, now):
        """Queue the answer owed to the peer's announcement of a clone we own; poll sends it."""
        self.answer_owned.append((now, c["clone_id"]))
        return []

    def _owned_answer(self, cid, now):
        """The announcer's answer to the peer's announcement of its own copy: first a2 on types 4
        and 2 and a1 on type 1 with the peer's clock; on re-announcement, an 82 on type 1 and our
        type 2 copy (docs/lgpe_session.md)."""
        peer_clock = self.announce_clocks.get(cid) or struct.pack(">I", self.ms(now))
        out = []
        if cid not in self.owned_answered:
            self.owned_answered.add(cid)
            # Each later announcement carries a fresh sequence and is owed one ack carrying it, or
            # the peer's announcer retransmits without limit.
            self.taken_over[cid] = peer_clock
            out.append(self._command(CLOCK_AND_COUNT_2, 4, 0xFD, cid, now,
                                     peer_clock + struct.pack(">BBH", 1, 0,
                                                              self.element_ms(now) & 0xFFFF)))
            out.append(self._command(CLOCK_AND_COUNT_2, 2, self.station, cid, now,
                                     peer_clock + struct.pack(">BBH", 0, 0,
                                                              self.element_ms(now) & 0xFFFF)))
            content = (self.contents.get((4, 0xFD, cid)) or self.contents.get((1, 0xFD, cid))
                       or b"\x01\x28\x08\xab")
            out.append(self._command(CLOCK_AND_COUNT, 1, 0xFD, cid, now, peer_clock + content))
            if self.publish_type4:
                out.append(build_data_message(
                    STATE_DATA, 4, 0xFD, cid, self.frame(now),
                    build_state_record(cid, self.station, self.dest, self.ms(now), bytes(32)),
                    flags=self.dest))
            return out
        out.append(self._command(COMMAND_REQUEST, 1, 0xFD, cid, now))
        self.published.add(cid)
        out.append(build_data_message(
            STATE_DATA, 2, self.station, cid, self.frame(now),
            build_state_record(cid, self.station, 3, self.ms(now), self.our_data(cid)),
            flags=3))
        return out

    def release(self, clone_id, now):
        """-> this station's release of a clone: 0x83 on type 2 under its own station to every
        station and on type 4, station 0xFD, to the peer; clone 0 on type 3 alone
        (docs/lgpe_session.md)."""
        self.held.discard(clone_id)
        self.published.discard(clone_id)
        if clone_id == 0:
            return [self._command(COMMAND_END, 3, 0xFD, 0, now, dest=self.dest)]
        return [self._command(COMMAND_END, 2, self.station, clone_id, now,
                              dest=self.own | self.dest),
                self._command(COMMAND_END, 4, 0xFD, clone_id, now, dest=self.dest)]

    def _command(self, kind, ctype, station, clone_id, now, payload=b"", dest=None):
        m = build_command(kind, ctype, station, clone_id, self._next_count(),
                          self.dest if dest is None else dest, payload)
        return m[:2] + struct.pack(">H", self.frame(now)) + m[4:]

    def receive(self, payload, now):
        """-> [payload] to send in answer to one received 0x73 payload."""
        if len(payload) < 2 or payload[0] != VERSION:
            return []
        kind = payload[1]
        self.log.append((round(now - self.t0, 3), kind, len(payload)))
        if kind == CLOCK_REQUEST:
            r = parse_clock_request(payload)
            reply_kind = CLOCK_REPLY_SYNCED if (self.participated or self.peer_participated) \
                else CLOCK_REPLY
            return [build_clock_reply(self.frame(now), self._next_count(), self.dest,
                                      r["clock"], extra=self.ms(now), kind=reply_kind)]
        if kind in (CLOCK_REPLY, CLOCK_REPLY_SYNCED):
            self.answered += 1
            return []
        if kind == PARTICIPATE:
            self.peer_participated = True
            self.peer_participated_at = now
            return [build_participate(self.frame(now), self._next_count(), self.dest,
                                      kind=PARTICIPATE_ACK)]
        if kind == PARTICIPATE_ACK:
            self.peer_participated_ack = True
            return []
        if kind == EXIT_REQUEST:
            self.exited = True
            return [build_exit_ack(self.frame(now), self._next_count(), self.dest, self.own)]
        d = parse_data_message(payload)
        if d is not None:
            r = d["record"]
            if d["type"] & 0xF0 == 0xF0 and r is not None and r["kind"] == RECORD_EMPTY:
                # The peer retries a publish while its copy is empty; answer with a
                # clock-and-participant, since an 0xe3 does not advance it.
                return [self._command(CLOCK_COUNT_PARTICIPANT, d["ctype"], d["station"],
                                      d["clone_id"], now,
                                      struct.pack(">IBBHI", self.ms(now), 1, 0,
                                                  self.element_ms(now) & 0xFFFF,
                                                  self.own | self.dest))]
            if d["type"] & 0xF0 == 0xF0 and r is not None and r["kind"] == RECORD_STATE:
                if d["ctype"] == 4 and r["station"] != self.station:
                    self.agreed[d["clone_id"]] = r["data"]
                if d["ctype"] == 2 and d["station"] != self.station and not self.peer_released:
                    # Answer the shared clone with our copy once: the peer retransmits about ten
                    # times a second, and answering each makes the pair trade publishes all session.
                    seen = self.shared.get(d["clone_id"])
                    self.shared[d["clone_id"]] = r["data"]
                    self.publish_deadline.pop(d["clone_id"], None)
                    if (not self.publish_once or d["clone_id"] not in self.published
                            or seen != r["data"]):
                        self.published.add(d["clone_id"])
                        self.held.add(d["clone_id"])
                        return [build_data_message(
                            STATE_DATA, 2, self.station, d["clone_id"], self.frame(now),
                            build_state_record(r["clone_id"], self.station, r["participants"],
                                               self.ms(now), self.our_data(d["clone_id"])),
                            flags=r["participants"])]
                # A clone type 2 copy is acked on clone type 1, station 0xFD, with the publisher's
                # station in the header byte (docs/lgpe_session.md).
                ctype, station = (1, 0xFD) if d["ctype"] == 2 else (d["ctype"], d["station"])
                return [build_data_message(STATE_ACK, ctype, station, d["clone_id"],
                                           self.frame(now),
                                           build_ack_record(r["clone_id"], r["station"],
                                                            r["clock"]),
                                           flags=r["station"])]
            return []
        c = parse_command(payload)
        if c is None:
            return []
        key = (c["ctype"], c["station"], c["clone_id"])
        if kind == CLOCK_AND_COUNT and len(c["payload"]) >= 8:
            self.contents[key] = c["payload"][4:8]
            # The peer's announcement clock is the sequence 0x520c30 allocated; 0x520ce0 completes a
            # take-over only when it carries it back.
            self.announce_clocks[c["clone_id"]] = c["payload"][:4]
        if kind == COMMAND_ANNOUNCE and c["ctype"] == 2 and c["clone_id"] in self.owned:
            return self._answer_takeover(c, now)
        if kind == COMMAND_ANNOUNCE and c["ctype"] == 2 and c["clone_id"] != 0:
            return self._mirror_announce(c, now)
        if (self.takeover_per_sequence and kind == CLOCK_AND_COUNT and c["clone_id"] != 0
                and c["station"] != self.station and len(c["payload"]) >= 4):
            # A re-announcement: 0x520c30 allocates a new sequence each time and 0x520ce0 completes
            # only on a match, so the previous take-over is stale.
            seq = c["payload"][:4]
            if self.taken_over.get(c["clone_id"]) not in (None, seq):
                self.announce_clocks[c["clone_id"]] = seq
                if self.ack_re_announcement:
                    # A joiner takes a clone over once and answers each later re-announcement with
                    # one 0xa2 carrying its clock, one per sequence (docs/lgpe_session.md).
                    self.taken_over[c["clone_id"]] = seq
                    return [self._command(CLOCK_AND_COUNT_2, 2, self.station, c["clone_id"], now,
                                          seq + b"\x00\x00\x00\x02")]
                return self._mirror_announce(c, now, takeover_only=True)
        if kind == CLOCK_AND_COUNT_2 and c["ctype"] == 2 and c["clone_id"] in self.owned:
            # The peer's ack of a clone announced here; its re-announcement follows.
            return []
        if kind == CLOCK_AND_COUNT_2 and c["ctype"] == 2 and c["station"] != self.station:
            # The host acked our copy: a real joiner announces once more 35 ms later.
            self.queue.append((now + 0.035, 2, self.station, c["clone_id"], COMMAND_ANNOUNCE,
                               None, None))
            if self.ack_re_announcement:
                # The reference joiner answers the peer's 0xa1 only; answering the 0xa2 too sends a
                # second ack with a superseded clock (docs/lgpe_session.md).
                return []
            payload = c["payload"]
            if self.ack_peer_clock:
                # The ack carries the peer's announcement clock, which 0x520ce0 compares against
                # +0x10C (docs/lgpe_session.md).
                seq = self.announce_clocks.get(c["clone_id"])
                if seq:
                    payload = seq + payload[4:]
            return [self._command(CLOCK_AND_COUNT_2, 2, self.station, c["clone_id"], now,
                                  payload)]
        if kind == CLOCK_COMMAND and c["clone_id"] in self.owned:
            # A take-over of an owned clone is answered once, off the 81 that follows it.
            return []
        if kind == CLOCK_COMMAND and c["clone_id"] != 0:
            # The peer took our clone over. Clone type 2 answers under our own station; type 4 keeps
            # 0xFD.
            station = self.station if c["ctype"] == 2 else c["station"]
            flag = 1 if c["ctype"] == 4 else 0
            # Mesh clock, flag, zero, the element's own clock (docs/lgpe_session.md).
            return [self._command(CLOCK_AND_COUNT_2, c["ctype"], station, c["clone_id"], now,
                                  struct.pack(">IBBH", self.ms(now), flag, 0,
                                              self.element_ms(now) & 0xFFFF))]
        if kind == COMMAND_END:
            # Unacked, the peer repeats the 0x83 every 100 ms and its player waits on 'interruption
            # de la connexion'. A release on type 2 is acked on type 1 (docs/lgpe_session.md).
            cid = c["clone_id"]
            if c["ctype"] == 3 and cid == 0:
                self.peer_released = True
            self.unrequested.pop(cid, None)
            self.held.discard(cid)
            self.published.discard(cid)
            self.tail.pop(cid, None)
            self.flags.pop(cid, None)
            self.arg.pop(cid, None)
            self.votes.pop(cid, None)
            return [self._command(COMMAND_END_ACK, 1 if c["ctype"] == 2 else c["ctype"],
                                  0xFD, cid, now)]
        if kind == COMMAND_REQUEST and c["ctype"] == 1:
            self.unrequested[c["clone_id"]] = (now, None)
            out = [build_data_message(STATE_ACK, 1, 0xFD, c["clone_id"], self.frame(now),
                                      build_ack_record(c["clone_id"], 0, self.ms(now)),
                                      flags=0)]
            if self.host_role and c["clone_id"] != 0 and c["clone_id"] not in self.owned:
                # The reference joiner answers the 82 with its type 2 copy in the same frame; a
                # joining console publishes nothing itself.
                self.published.add(c["clone_id"])
                out.append(build_data_message(
                    STATE_DATA, 2, self.station, c["clone_id"], self.frame(now),
                    build_state_record(c["clone_id"], self.station, 3, self.ms(now),
                                       self.our_data(c["clone_id"])),
                    flags=3))
                if self.request_publishes_type4 and self.publish_type4:
                    # The announcer of a working session publishes the type 4 copy after the
                    # take-over with the taker's bit; the peer never does, so the host does it for
                    # it.
                    out.append(build_data_message(
                        STATE_DATA, 4, 0xFD, c["clone_id"], self.frame(now),
                        build_state_record(c["clone_id"], self.station, self.dest, self.ms(now),
                                           bytes(32)),
                        flags=self.dest))
            return out
        if key == (3, 0xFD, 0):
            # The measured joiner on the type-3 clone: a2 echoes a1's clock with count 1, c1 echoes
            # b1's with its bitmap, 0x84 answers 0x83.
            if (kind in (CLOCK_AND_COUNT, CLOCK_AND_PARTICIPANT)
                    and kind in self.withhold_clone0_answers):
                # Test only: as if the answer were lost, to see whether the owner repeats its pair.
                self.withhold_clone0_answers.discard(kind)
                self.events.append(f"withheld our answer to the peer's clone 0 {kind:#04x}")
                return []
            if kind == CLOCK_AND_COUNT and len(c["payload"]) >= 8:
                if self.host_role:
                    # The reference host answers the joiner's clone 0 announcement with a 0x91
                    # echoing the clock; its own a1/b1 pair follows its participate.
                    return [self._command(CLOCK_COMMAND, 3, 0xFD, 0, now, c["payload"][:4])]
                # The clock, then the count and checksum bytes.
                return [self._command(CLOCK_AND_COUNT_2, 3, 0xFD, 0, now, c["payload"][:8])]
            if kind == CLOCK_AND_PARTICIPANT and len(c["payload"]) >= 8:
                clk, part = c["payload"][:4], c["payload"][4:8]
                return [self._command(CLOCK_COUNT_PARTICIPANT, 3, 0xFD, 0, now,
                                      clk + b"\x01\0\0\x02" + part)]
        return []

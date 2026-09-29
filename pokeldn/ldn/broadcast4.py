"""Protocol 0x84, `nn::pia::transport::ReliableBroadcastProtocol`, the version-4 bulk channel.

Kinds and ports: docs/pia.md, Protocol 0x84; the Sword snapshot: docs/swsh_protocol.md.
"""
import struct
import zlib

PROTOCOL = 0x84
# u8 kind, 3 zero, u16be own sequence (one counter across kinds on a port), u16be the peer's
# last sequence seen (0xFFFF before any). Pia's zlib flag 0x10 covers only bytes after PREFIX_SIZE.
HEADER_SIZE = 8
PREFIX_SIZE = 12                      # header + u32be fragment index, never compressed
KIND_CONTROL = 0x11
KIND_DATA = 0x12
KIND_ACK = 0x21                       # u32be base + u64be bitmask of what arrived out of order
KIND_DONE = 0x19
KIND_DONE_ACK = 0x28                  # the answer to KIND_DONE
ACK_SIZE = HEADER_SIZE + 12
CONTROL_SIZE = 20                     # header, u32be total, u16be chunk size, u16be 5, 4 zero
NO_PEER_SEQUENCE = 0xFFFF
CONTROL_UNKNOWN = 5                   # the halfword at 0x0E, 5 in every message seen
CHUNK_SIZE = 1404                     # the console's; nxldn-lab's sender picks 1244

# The console's deflate settings, from nxldn-lab's sender: 12-bit window, level 5.
COMPRESS_LAST = "last"                # deflate only the final fragment, as the console does
COMPRESS_AUTO = "auto"                # deflate whenever smaller, as nxldn-lab's sender does

_WBITS = 12
_LEVEL = 5
_MEM_LEVEL = 4


def build_header(kind, sequence, peer_sequence=NO_PEER_SEQUENCE):
    return struct.pack(">B3xHH", kind, sequence & 0xFFFF, peer_sequence & 0xFFFF)


def build_control(sequence, total, chunk_size=CHUNK_SIZE, peer_sequence=NO_PEER_SEQUENCE):
    return (build_header(KIND_CONTROL, sequence, peer_sequence)
            + struct.pack(">IHH4x", total, chunk_size, CONTROL_UNKNOWN))


def deflate(body):
    """-> (bytes, compressed?), deflated only when smaller."""
    c = zlib.compressobj(_LEVEL, zlib.DEFLATED, _WBITS, _MEM_LEVEL)
    packed = c.compress(bytes(body)) + c.flush(zlib.Z_SYNC_FLUSH) + c.flush(zlib.Z_FINISH)
    return (packed, True) if len(packed) < len(body) else (bytes(body), False)


def build_fragment(sequence, index, body, peer_sequence=NO_PEER_SEQUENCE, compress=True):
    """-> (payload, compressed?); the caller sets Pia's 0x10 flag when compressed."""
    packed, done = deflate(body) if compress else (bytes(body), False)
    return (build_header(KIND_DATA, sequence, peer_sequence)
            + struct.pack(">I", index) + packed), done


def split(payload, chunk_size=CHUNK_SIZE):
    return [bytes(payload[i:i + chunk_size]) for i in range(0, len(payload), chunk_size)]


def parse(message):
    """-> dict. A data body is left deflated: only Pia's message flag says whether to inflate."""
    if len(message) < HEADER_SIZE:
        raise ValueError(f"a 0x84 message is at least {HEADER_SIZE} bytes, got {len(message)}")
    kind = message[0]
    sequence, peer = struct.unpack_from(">HH", message, 4)
    out = {"kind": kind, "sequence": sequence, "peer_sequence": peer,
           "is_control": kind == KIND_CONTROL, "is_data": kind == KIND_DATA}
    if kind == KIND_CONTROL:
        if len(message) < CONTROL_SIZE:
            raise ValueError(f"a control message is {CONTROL_SIZE} bytes, got {len(message)}")
        total, chunk, unknown = struct.unpack_from(">IHH", message, 8)
        out.update(total=total, chunk_size=chunk, unknown=unknown)
    elif kind == KIND_DATA:
        if len(message) < PREFIX_SIZE:
            raise ValueError(f"a data message is at least {PREFIX_SIZE} bytes, got {len(message)}")
        out.update(index=struct.unpack_from(">I", message, 8)[0], body=message[PREFIX_SIZE:])
    elif kind == KIND_ACK:
        if len(message) < ACK_SIZE:
            raise ValueError(f"an ack is {ACK_SIZE} bytes, got {len(message)}")
        base, mask = struct.unpack_from(">IQ", message, 8)
        out.update(base=base, mask=mask)
    elif kind in (KIND_DONE, KIND_DONE_ACK):
        pass
    else:
        raise ValueError(f"kind {kind:#04x} is none of control ({KIND_CONTROL:#04x}), "
                         f"data ({KIND_DATA:#04x}), ack ({KIND_ACK:#04x}), done "
                         f"({KIND_DONE:#04x}) or done-ack ({KIND_DONE_ACK:#04x})")
    return out


def build_ack(sequence, base, mask=0, peer_sequence=NO_PEER_SEQUENCE):
    """`base` is the first index not yet received and `mask` bit n is index `base + 1 + n`: a
    receiver holding 0 and 2 acks base 1, mask 1."""
    return (build_header(KIND_ACK, sequence, peer_sequence)
            + struct.pack(">IQ", base, mask))


def build_done(sequence, peer_sequence=NO_PEER_SEQUENCE):
    return build_header(KIND_DONE, sequence, peer_sequence)


def build_done_ack(sequence, peer_sequence=NO_PEER_SEQUENCE):
    return build_header(KIND_DONE_ACK, sequence, peer_sequence)


def ack_fields(indexes):
    received = set(indexes)
    base = 0
    while base in received:
        base += 1
    mask = 0
    for index in received:
        if index > base:
            mask |= 1 << (index - base - 1)
    return base, mask


class Sender:
    """One port's outgoing side. One sequence counts across control and data: control at 0,
    fragment 0 at 1, fragment 2 at 5, the gaps being retransmits."""

    def __init__(self, chunk_size=CHUNK_SIZE):
        self.sequence = 0
        self.peer_sequence = NO_PEER_SEQUENCE
        self.chunk_size = chunk_size

    def _next(self):
        sequence, self.sequence = self.sequence, (self.sequence + 1) & 0xFFFF
        return sequence

    def saw(self, sequence):
        """Record the peer's sequence, which every later message echoes."""
        self.peer_sequence = sequence & 0xFFFF

    def transfer(self, payload, compress=COMPRESS_LAST):
        """-> [(payload, compressed?), ...]. The console sent fragments 0 and 1 plain at 1404 bytes
        (fragment 1 deflates to 776) and deflated only the last, so COMPRESS_LAST is the default;
        COMPRESS_AUTO is nxldn-lab's policy, `False` sends everything plain."""
        chunks = split(payload, self.chunk_size)
        out = [(build_control(self._next(), len(payload), self.chunk_size, self.peer_sequence),
                False)]
        for index, chunk in enumerate(chunks):
            if compress == COMPRESS_LAST:
                allow = index == len(chunks) - 1
            else:
                allow = bool(compress)
            out.append(build_fragment(self._next(), index, chunk, self.peer_sequence, allow))
        return out


class Receiver:
    """One port's incoming side. An unacknowledged 0x84 repeats: 15460 and 19142 messages of one
    snapshot in two sessions left unacked."""

    def __init__(self):
        self.indexes = set()
        self.total = None
        self.chunk_size = None
        self.sequence = 0
        self.peer_sequence = NO_PEER_SEQUENCE
        self.fragments = {}

    def _next(self):
        sequence, self.sequence = self.sequence, (self.sequence + 1) & 0xFFFF
        return sequence

    def feed(self, message, body=None):
        """-> the replies to one received message. `body` is the fragment already inflated when
        Pia's 0x10 flag was set."""
        got = parse(message)
        self.peer_sequence = got["sequence"]
        if got["is_control"]:
            self.total, self.chunk_size = got["total"], got["chunk_size"]
            return []
        if got["kind"] == KIND_DATA:
            self.indexes.add(got["index"])
            self.fragments[got["index"]] = body if body is not None else got["body"]
            base, mask = ack_fields(self.indexes)
            return [build_ack(self._next(), base, mask, self.peer_sequence)]
        if got["kind"] == KIND_DONE:
            return [build_done_ack(self._next(), self.peer_sequence)]
        return []

    def complete(self):
        if self.total is None or self.chunk_size is None:
            return False
        expected = -(-self.total // self.chunk_size)
        return self.indexes >= set(range(expected))

    def payload(self):
        """-> the reassembled bytes, or None until complete."""
        if not self.complete():
            return None
        return b"".join(self.fragments[i] for i in sorted(self.fragments))

"""Pia's Local Protocol (protocol 36): the host's update session and the station's ack.

Byte order is mixed: the Pia header is big-endian, these fields little-endian, a local address
big-endian again (docs/pia.md, docs/bdsp_session.md).
"""

import struct
from dataclasses import dataclass, field

PROTOCOL = 36

UPDATE_SESSION = 0x11
DESTROY_NETWORK = 0x12
START_HOST_MIGRATION = 0x13
UPDATE_SESSION_ACK = 0x21

# One send path (main.bin 0x016af22c) frames every type alike: 0x11 is bitmap destination (0x01)
# plus unbundled (0x10); the bitmap is `1 << station_index`, 0 broadcast (docs/pia.md).
MESSAGE_FLAGS = 0x11
BROADCAST = 0

HEADER_SIZE = 12
UPDATE_SESSION_FIXED = 0x30       # before the node list
NODE_SIZE = 9
NODE_COUNT = 8
RANKING_EMPTY = 255               # an unused seat, with its address zeroed


@dataclass
class LocalNode:
    ip: str
    port: int
    ranking: int                  # 0 is the oldest node; 255 means the seat is empty

    @property
    def occupied(self):
        return self.ranking != RANKING_EMPTY


@dataclass
class UpdateSession:
    sequence_id: int
    network_id: int  # random per network; differs from the advertisement's network id
    host_variable_id: int
    host_service_variable_id: int
    host_constant_id: bytes
    allow_participating: bool
    nodes: list = field(default_factory=list)
    host_migration_state: int = 0

    @property
    def occupied(self):
        return [n for n in self.nodes if n.occupied]


def parse_header(data):
    """-> (message_type, payload_size). Raises if the version byte is not 1."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a local message header is {HEADER_SIZE} bytes, got {len(data)}")
    version, message_type, size = struct.unpack_from("<BBH", data, 0)
    if version != 1:
        raise ValueError(f"local message version {version}, expected 1")
    return message_type, size


def _address(raw):
    """A 6-byte IPv4 InetAddress, big-endian, then 2 bytes of extension."""
    return ".".join(str(b) for b in raw[:4]), struct.unpack_from(">H", raw, 4)[0]


def parse_update_session(data):
    """The whole 0x11 message, header included."""
    message_type, size = parse_header(data)
    if message_type != UPDATE_SESSION:
        raise ValueError(f"message type {message_type:#04x}, expected {UPDATE_SESSION:#04x}")
    if len(data) < UPDATE_SESSION_FIXED + size:
        raise ValueError(f"truncated: {len(data)} bytes for {UPDATE_SESSION_FIXED + size}")
    seq, network_id, host_var, host_svc = struct.unpack_from("<4I", data, 0x0C)
    constant_id = data[0x20:0x28]
    allow = bool(data[0x28])
    nodes = []
    for i in range(NODE_COUNT):
        off = UPDATE_SESSION_FIXED + i * NODE_SIZE
        if off + NODE_SIZE > len(data):
            break
        ip, port = _address(data[off:off + 8])
        nodes.append(LocalNode(ip, port, data[off + 8]))
    tail = UPDATE_SESSION_FIXED + NODE_COUNT * NODE_SIZE
    state = data[tail] if tail < len(data) else 0
    return UpdateSession(seq, network_id, host_var, host_svc, constant_id, allow, nodes, state)


def build_update_session(sequence_id, network_id, host_variable_id, host_service_variable_id,
                         host_constant_id, nodes, allow_participating=True,
                         host_migration_state=0):
    """The host's 0x11 message, 121 bytes for eight seats; `nodes` is up to eight (ip, port,
    ranking). A retail Sword's own update session rebuilds from its parsed fields byte for byte."""
    nodes = list(nodes)[:NODE_COUNT]
    body = bytearray(UPDATE_SESSION_FIXED)
    size = NODE_COUNT * NODE_SIZE + 1
    struct.pack_into("<BBH", body, 0, 1, UPDATE_SESSION, size)
    struct.pack_into("<4I", body, 0x0C, sequence_id & 0xFFFFFFFF, network_id & 0xFFFFFFFF,
                     host_variable_id & 0xFFFFFFFF, host_service_variable_id & 0xFFFFFFFF)
    struct.pack_into("<Q", body, 0x20, host_constant_id & 0xFFFFFFFFFFFFFFFF)
    body[0x28] = 1 if allow_participating else 0
    for i in range(NODE_COUNT):
        if i < len(nodes):
            ip, port, ranking = nodes[i]
            body += bytes(int(p) for p in ip.split(".")) + struct.pack(">H", port)
            body += b"\0\0" + bytes([ranking & 0xFF])
        else:
            body += b"\0" * 8 + bytes([RANKING_EMPTY])
    return bytes(body) + bytes([host_migration_state & 0xFF])


def build_ack(sequence_id):
    """The 20-byte 0x21 ack (main.bin 0x016bc0f4): the payload-size halfword stays zero for an ack
    (docs/pia.md)."""
    return (struct.pack("<BBH", 1, UPDATE_SESSION_ACK, 0) + b"\0" * 6 + b"\0" * 2
            + struct.pack("<I", sequence_id) + b"\0" * 4)


def parse_ack(data):
    """-> the sequence id a 0x21 message acknowledges."""
    message_type, _size = parse_header(data)
    if message_type != UPDATE_SESSION_ACK:
        raise ValueError(f"message type {message_type:#04x}, expected {UPDATE_SESSION_ACK:#04x}")
    if len(data) < 0x14:
        raise ValueError(f"an ack is 20 bytes, got {len(data)}")
    return struct.unpack_from("<I", data, 0x0C)[0]

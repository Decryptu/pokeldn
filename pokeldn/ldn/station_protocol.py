"""Pia 5.27-5.45's Mesh Station Protocol, protocol 0x14: the connection handshake a joiner
completes to enter a mesh. Parser main.bin 0x0154ebd0, dispatcher 0x0154e848.

docs/pia.md, The Mesh Station Protocol (0x14).
"""

import struct
import zlib

# Pia 5.27-5.45 offsets. Sword/Shield's version 4 shifts every field from [3] one byte later:
# `station4.py`, docs/pia.md "The version-4 connection request".
PROTOCOL = 0x14                   # MeshStationProtocol, Pia 5.29-5.45
PORT_UNRELIABLE = 0               # unused by Pia since 5.6

CONNECTION_REQUEST = 1
CONNECTION_RESPONSE = 2
DISCONNECTION_REQUEST = 3
DISCONNECTION_RESPONSE = 4
ACK = 5
RELAY_CONNECTION_REQUEST = 6
RELAY_CONNECTION_RESPONSE = 7

PLATFORM_WII_U = 3
PLATFORM_SWITCH = 4

MIN_SIZE = 15                     # `cmp w8, #0xe; b.ls`
MAX_SIZE = 949                    # `cmp w8, #0x3b6; b.hs`

RESULT_ACCEPTED = 0
RESULT_DENIED = 1
RESULT_VERSION_TOO_LOW = 2
RESULT_VERSION_TOO_HIGH = 3

# Result mapping at main.bin 0x0154f5e8 (docs/pia.md).
RESULT_VERSIONS_MATCHED = 7

RESULT_NAMES = {
    0: "accepted",
    1: "denied",
    2: "version too low",
    3: "version too high",
    4: "refused after parsing (0xc24)",
    5: "refused before the station lookup",
    7: "parsed and versions matched, refused by the second stage (0x11c0f)",
}

STATION_LOCATION_MIN = 0x20       # `sub w10, w25, #0x20; cmp w10, #0x21; b.hs`
STATION_LOCATION_MAX = 0x40


def ldn_constant_id(mac):
    """A station's constant id in LDN mode, from its MAC (NintendoClients wiki); stable across
    sessions. A Shining Pearl host's 000048f120229beb is this rule over 48:f1:eb:20:9b:22."""
    m = bytes(mac)
    if len(m) != 6:
        raise ValueError(f"a MAC is six bytes, not {len(m)}")
    return (m[2] << 56) | (m[4] << 48) | (m[5] << 40) | (m[3] << 32) | (m[1] << 24) | (m[0] << 16)


def ldn_service_variable_id(mac):
    """A station's service variable id in LDN mode: the CRC-32 of its MAC."""
    m = bytes(mac)
    if len(m) != 6:
        raise ValueError(f"a MAC is six bytes, not {len(m)}")
    return zlib.crc32(m) & 0xFFFFFFFF


# InetAddress parser main.bin 0x0153ac10 tests `1 << size` against 0x00040044: the size counts the
# port, so 2 is a bare port, 6 IPv4, 18 IPv6.
INET_SIZES = (2, 6, 18)
INET_IPV4 = 6


def inet_address(ip, port):
    """Four address bytes then a big-endian port: size 6."""
    octets = bytes(int(p) for p in ip.split("."))
    if len(octets) != 4:
        raise ValueError(f"not an IPv4 address: {ip}")
    return octets + struct.pack(">H", port)


def station_location(ip, port, constant_id, variable_id, service_variable_id,
                     nat_flags=0x05, nat_location=1, probeinit=0, private_available=1,
                     public=True):
    """A Pia 5.11-5.45 station location, 40 bytes (36 with `public=False`), by the deserializer
    main.bin 0x015a3aac: two size bytes, the two addresses, then relay u32 + u16, constant id u64,
    variable id u32, service variable id u32, nat flags, nat location, probeinit, private flag."""
    # A station with no route off the mesh sends an empty public address, a zero port: a Let's Go
    # joiner on local wireless.
    public = inet_address(ip, port) if public else struct.pack(">H", 0)
    private = inet_address(ip, port)
    # Trap: the connection-request parser discards the location's error, so a bad size byte reads as
    # a well-formed request with variable id 0 that every probe sees refused.
    out = (bytes([len(public), len(private)]) + public + private
           + inet_address("0.0.0.0", 0)
           + struct.pack(">Q", constant_id)
           + struct.pack(">I", variable_id)
           + struct.pack(">I", service_variable_id)
           + bytes([nat_flags & 0xFF, nat_location & 0xFF,
                    probeinit & 0xFF, 1 if private_available else 0]))
    if not STATION_LOCATION_MIN <= len(out) <= STATION_LOCATION_MAX:
        raise ValueError(f"a station location must be 0x20..0x40 bytes, this is {len(out)}")
    return out


def player_info(name="", account="", language=1, principal_id=0):
    """One 195-byte PlayerInfo, 5.27-5.45 (string and encoding swapped order in 5.27)."""
    out = (bytes([1]) + name.encode("utf-8")[:80].ljust(80, b"\0")
           + bytes([1]) + account.encode("utf-8")[:40].ljust(40, b"\0")
           + bytes([language & 0xFF]) + b"\0" * 64
           + struct.pack("<Q", principal_id))
    assert len(out) == 0xC3, len(out)
    return out


def build_connection_request(target_constant_id, target_variable_id, protocols, location,
                             token=b"", network_id=0, players=1, participants=1, player_infos=(),
                             ack_id=1, platform=PLATFORM_SWITCH, result=RESULT_ACCEPTED,
                             message_type=CONNECTION_REQUEST):
    """The message the parser at 0x0154ebd0 reads. `protocols` is (id, version) pairs; the target
    ids are the host's, and a mismatch on either is dropped in silence."""
    if len(location) < STATION_LOCATION_MIN or len(location) > STATION_LOCATION_MAX:
        raise ValueError(f"station location is {len(location)} bytes, must be 0x20..0x40")
    out = bytearray()
    out += bytes([message_type & 0xFF, result & 0xFF, platform & 0xFF])
    out += struct.pack(">Q", target_constant_id)
    out += struct.pack(">I", target_variable_id)
    out += bytes([len(protocols) & 0xFF])
    for pid, version in protocols:
        out += bytes([pid & 0xFF, version & 0xFF])
    out += struct.pack(">H", len(location)) + bytes(location)
    out += bytes(token)[:32].ljust(32, b"\0")
    out += struct.pack(">I", network_id)
    out += bytes([players & 0xFF, participants & 0xFF, len(player_infos) & 0xFF])
    for info in player_infos:
        out += bytes(info)
    out += struct.pack(">I", ack_id)
    if not MIN_SIZE <= len(out) <= MAX_SIZE:
        raise ValueError(f"a connection request must be {MIN_SIZE}..{MAX_SIZE} bytes, "
                         f"this is {len(out)}")
    return bytes(out)


# Pia 5.29-5.45 protocol ids (NintendoClients wiki, "Pia Protocols"); BDSP registers nine.
KNOWN_PROTOCOL_IDS = (
    0x08,   # Keep Alive
    0x14,   # Station (MeshStationProtocol)
    0x18,   # Mesh
    0x1C,   # Sync Clock
    0x24,   # Local
    0x34,   # NAT
    0x44,   # LAN
    0x58,   # RTT
    0x65,   # Sync
    0x68,   # Unreliable
    0x73,   # Clone
    0x74,   # Clone (atomic)
    0x75,   # Clone (event)
    0x76,   # Clone (broadcast event)
    0x77,   # Clone (clock)
    0x7B,   # Voice
    0x7C,   # Reliable
    0x80,   # Broadcast Reliable
    0x81,   # Stream Broadcast Reliable
    0x94,   # Session
    0xA4,   # Monitoring Data
    0xB0,   # Reckoning 1D
    0xB4,   # Reckoning 3D
)

# An unregistered id looks up as version 0 (0x0159b850), so this pair always matches and pads a
# probe to the required count.
FILLER = (0xFF, 0)


def version_probe(protocol_id, version, count):
    """-> [(id, version)]: the candidate first, since the console reports the first entry that
    disagrees, then filler to the console's own count."""
    if count < 1:
        raise ValueError("a version probe needs at least one entry")
    return [(protocol_id, version)] + [FILLER] * (count - 1)


def read_version(result):
    """-> "higher", "lower" or "equal" for the version sent; raises on silence. A request whose
    versions all match is refused by the second stage (0x0154fcfc) with result 7, so equality is a
    reply and silence is a lost packet."""
    if result == RESULT_VERSION_TOO_LOW:
        return "higher"  # ours was too low
    if result == RESULT_VERSION_TOO_HIGH:
        return "lower"
    if result is not None and result != RESULT_VERSION_TOO_LOW:
        return "equal"  # past the version loop
    raise ValueError("silence says nothing about a version - the equality signal is a reply")


class VersionSearch:
    """Find a registered version from higher/lower/equal probes, driven by the caller: send
    `next_version()`, `feed()` the read_version answer. `found` stays None when answers contradict,
    as a lost packet makes them; `bin/bdsp_connect.py` re-probes both neighbours."""

    def __init__(self, lo=0, hi=255, first=1):
        self.lo, self.hi = lo, hi
        self.pending = max(lo, min(hi, first))
        self.found = None
        self.done = False
        self.probes = 0

    def next_version(self):
        if self.done:
            return None
        return self.pending

    def feed(self, direction):
        if self.done:
            raise ValueError("this search has already finished")
        v = self.pending
        self.probes += 1
        if direction == "equal":
            self.found, self.done = v, True
            return
        if direction == "higher":
            self.lo = v + 1
        elif direction == "lower":
            self.hi = v - 1
        else:
            raise ValueError(f"a probe answered {direction!r}, which is not a direction")
        if self.lo > self.hi:
            self.done = True                # the answers contradict each other
            return
        self.pending = (self.lo + self.hi) // 2


def build_ack(ack_id):
    """The eight-byte ack (0x0154fa2c). A connection response repeats every 500 ms until acked."""
    return bytes([ACK, 0, 0, 0]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def parse_ack(data):
    if len(data) < 8 or data[0] != ACK:
        raise ValueError(f"not an eight-byte station protocol ack: {data[:8].hex()}")
    return struct.unpack_from(">I", data, 4)[0]


def parse_station_location(loc):
    """-> dict, by the deserializer main.bin 0x015a3aac; the size bytes count the port."""
    if len(loc) < 4 or loc[0] not in INET_SIZES or loc[1] not in INET_SIZES:
        raise ValueError(f"address sizes {loc[:2].hex()} are not two of {INET_SIZES}")
    rest = 2 + loc[0] + loc[1]
    if len(loc) < rest + 0x1A:
        raise ValueError(f"a station location is {rest + 0x1A} bytes here, got {len(loc)}")

    def address(off, size):
        if size < 6:
            return None, struct.unpack_from(">H", loc, off + size - 2)[0]
        return (".".join(str(b) for b in loc[off:off + 4]),
                struct.unpack_from(">H", loc, off + 4)[0])

    public = address(2, loc[0])
    private = address(2 + loc[0], loc[1])
    return {
        "public": public, "private": private,
        "relay": (".".join(str(b) for b in loc[rest:rest + 4]),
                  struct.unpack_from(">H", loc, rest + 4)[0]),
        "constant_id": struct.unpack_from(">Q", loc, rest + 0x06)[0],
        "variable_id": struct.unpack_from(">I", loc, rest + 0x0E)[0],
        "service_variable_id": struct.unpack_from(">I", loc, rest + 0x12)[0],
        "nat_flags": loc[rest + 0x16], "nat_location": loc[rest + 0x17],
        "probeinit": loc[rest + 0x18], "private_available": loc[rest + 0x19],
    }


def parse_connection_response(data):
    """-> dict. A denial is fifteen bytes (built at 0x01550190); an acceptance carries the host's
    protocol list, station location, ids, network id, player names and ack id."""
    if len(data) < 2:
        raise ValueError(f"a connection response is at least two bytes, got {len(data)}")
    if data[0] != CONNECTION_RESPONSE:
        raise ValueError(f"message type {data[0]:#04x}, expected {CONNECTION_RESPONSE:#04x}")
    out = {"result": data[1], "result_name": RESULT_NAMES.get(data[1], "?"), "size": len(data)}
    if data[1] != RESULT_ACCEPTED:
        if len(data) >= 15:
            out["constant_id"] = struct.unpack_from(">Q", data, 3)[0]
            out["variable_id"] = struct.unpack_from(">I", data, 11)[0]
        return out

    out["platform"] = data[2]
    out["target_constant_id"] = struct.unpack_from(">Q", data, 3)[0]
    out["target_variable_id"] = struct.unpack_from(">I", data, 11)[0]
    n = data[15]
    off = 16
    out["protocols"] = [(data[off + 2 * i], data[off + 2 * i + 1]) for i in range(n)]
    off += 2 * n
    size = struct.unpack_from(">H", data, off)[0]
    off += 2
    out["location"] = parse_station_location(data[off:off + size])
    off += size
    out["token"] = data[off:off + 32]
    off += 32
    out["network_id"] = struct.unpack_from(">I", data, off)[0]
    off += 4
    out["players"], out["participants"], infos = data[off], data[off + 1], data[off + 2]
    off += 3
    names = []
    for _ in range(infos):
        info = data[off:off + 0xC3]
        off += 0xC3
        if len(info) >= 0x51:
            names.append(info[1:0x51].split(b"\0")[0].decode("utf-8", "replace"))
    out["player_names"] = names
    out["ack_id"] = struct.unpack_from(">I", data, len(data) - 4)[0]
    return out


def parse_message(data):
    """-> (message type, the rest)."""
    if not data:
        raise ValueError("empty station protocol message")
    return data[0], data[1:]

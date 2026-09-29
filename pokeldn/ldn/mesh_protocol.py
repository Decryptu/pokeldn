"""Pia's Mesh Protocol (protocol 0x18), the membership layer above the station handshake.

A mesh message is acked on the station protocol (0x14), with its eight-byte type-5 ack
(docs/pia.md, "The Mesh Protocol"; docs/bdsp_session.md, "Acking a mesh message").
"""

import struct

from pokeldn.ldn import station_protocol as stp

PROTOCOL = 0x18
PORT_UNRELIABLE = 0
PORT_RELIABLE = 1                 # update mesh travels here; the join request does not

JOIN_REQUEST = 0x01
JOIN_RESPONSE = 0x02
LEAVE_REQUEST = 0x04
LEAVE_RESPONSE = 0x08
DESTROY_MESH = 0x10
DESTROY_RESPONSE = 0x11
UPDATE_MESH = 0x20
KICKOUT_NOTICE = 0x21
DUMMY_MESSAGE = 0x22
DUMMY_ACK = 0x23
CONNECTION_FAILURE_NOTICE = 0x24
INCONSISTENT_NOTICE = 0x25
GREETING = 0x40
MIGRATION_FINISH = 0x41
GREETING_RESPONSE = 0x42
MIGRATION_START = 0x44
MIGRATION_RESPONSE = 0x48
MULTI_MIGRATION_START = 0x49
MULTI_MIGRATION_RANK_DECISION = 0x4A
CONNECTION_REPORT = 0x80
RELAY_ROUTE_DIRECTIONS = 0x81

TYPE_NAMES = {v: k for k, v in list(globals().items()) if isinstance(v, int) and k.isupper()}

STATION_INDEX_INVALID = 253       # a console that has not joined a mesh yet
STATION_INDEX_HOST = 254
STATION_INDEX_BROADCAST = 255

STATION_INFO_SIZE = 68            # 5.31-5.45: a 64-byte location, an index, a join order, a pad
LOCATION_FIELD = 64
ACK_PROTOCOL = stp.PROTOCOL  # a mesh message is acked on the station protocol

# Version 4 (Sword/Shield): the same types minus 0x22 and 0x23; 64-byte entries with the index at
# 0x3E (parser 0x017b4830). docs/pia.md, 'The Mesh Protocol'.
MESH_TYPES_V4 = frozenset([
    JOIN_REQUEST, JOIN_RESPONSE, LEAVE_REQUEST, LEAVE_RESPONSE,
    DESTROY_MESH, DESTROY_RESPONSE, UPDATE_MESH, KICKOUT_NOTICE,
    CONNECTION_FAILURE_NOTICE, INCONSISTENT_NOTICE,
    GREETING, MIGRATION_FINISH, GREETING_RESPONSE, MIGRATION_START,
    MIGRATION_RESPONSE, MULTI_MIGRATION_START, MULTI_MIGRATION_RANK_DECISION,
    CONNECTION_REPORT, RELAY_ROUTE_DIRECTIONS,
])
STATION_INFO_SIZE_V4 = 0x40
INDEX_FIELD_V4 = 0x3E

# A retail Sword's join response is 148 bytes for two stations (docs/pia.md).
JOIN_RESPONSE_TWO_STATIONS_V4 = 0x10 + 2 * STATION_INFO_SIZE_V4 + 4        # 148


def build_join_request(ack_id, station_index=STATION_INDEX_INVALID):
    """Six bytes. 253 is what a station that is not yet in a mesh calls itself."""
    return bytes([JOIN_REQUEST, station_index & 0xFF]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def read_ack_id(data):
    """The last four bytes, big-endian (main.bin 0x01542db8); 0 when shorter than four."""
    if len(data) < 4:
        return 0
    return struct.unpack_from(">I", data, len(data) - 4)[0]


def ack_for(data):
    """-> (protocol, payload) acking a join request or response, or None: `05 00 00 00 <ack id>`
    on 0x14, as 0x01550324 sends it (docs/bdsp_session.md)."""
    kind = data[0] if data else None
    if kind not in (JOIN_REQUEST, JOIN_RESPONSE) or len(data) < 4:
        return None
    return ACK_PROTOCOL, stp.build_ack(read_ack_id(data))


def parse_join_response(data, version4=False):
    """-> dict. A refusal is `02 00 ff ff <reason>`; a success carries the mesh.

    Version 4 walks `stations` entries from base 0 when unfragmented (0x017b48f4) and [6] entries
    into slot [7] when fragmented (0x017b4b6c); 5.31-5.45 reads [6] in both (docs/pia.md)."""
    if len(data) < 5 or data[0] != JOIN_RESPONSE:
        raise ValueError(f"not a mesh join response: {data[:8].hex()}")
    if data[1] == 0 and data[2] == 0xFF and data[3] == 0xFF:
        return {"refused": True, "reason": data[4]}
    if len(data) < 16:
        raise ValueError(f"a join response is at least sixteen bytes, got {len(data)}")
    out = {
        "refused": False,
        "stations": data[1],              # including the joining station
        "host_index": data[2],
        "our_index": data[3],
        "fragments": data[4],
        "fragment_index": data[5],
        "entries": data[6],
        "base_index": data[7],
        "max_active": data[8],
        "max_buffer": data[9],
        "max_total": data[10],
        "update_counter": struct.unpack_from(">I", data, 12)[0],
    }
    count, base = out["entries"], out["base_index"]
    if version4 and out["fragments"] == 1:
        count, base = out["stations"], 0
    out["entry_count"], out["entry_base"] = count, base
    out["station_info"] = _station_info(data, 16, count, version4=version4)
    out["ack_id"] = read_ack_id(data)
    return out


UPDATE_MESH_HEADER = 12
UPDATE_MESH_SIZE = UPDATE_MESH_HEADER + 8 * STATION_INFO_SIZE      # 556: always the full 8 seats
UPDATE_MESH_SIZE_V4 = UPDATE_MESH_HEADER + 8 * STATION_INFO_SIZE_V4        # 524, measured


def parse_update_mesh(data, version4=False):
    """-> dict. Always the full size, unused seats zero: walk `entries`, never the length."""
    if len(data) < UPDATE_MESH_HEADER or data[0] != UPDATE_MESH:
        raise ValueError(f"not a mesh update: {data[:12].hex()}")
    out = {
        "stations": data[1],
        "host_index": data[2],
        "update_counter": struct.unpack_from(">I", data, 4)[0],
        "fragments": data[8],
        "fragment_index": data[9],
        "entries": data[10],
        "base_index": data[11],
    }
    out["station_info"] = _station_info(data, UPDATE_MESH_HEADER, out["entries"],
                                        version4=version4)
    return out


def rewrite_update_mesh(data, host_index, update_counter=None):
    """-> the console's own update mesh with byte [2] (host index) and optionally the counter at
    [4:8] changed; the station table stays its own bytes. After a migration this host sends it."""
    if len(data) < UPDATE_MESH_HEADER or data[0] != UPDATE_MESH:
        raise ValueError(f"not a mesh update: {data[:12].hex()}")
    if not 0 <= host_index <= MAX_STATION_INDEX:
        raise ValueError(f"station index {host_index} is outside the 32-station bound")
    out = bytearray(data)
    out[2] = host_index
    if update_counter is not None:
        struct.pack_into(">I", out, 4, update_counter & 0xFFFFFFFF)
    return bytes(out)


def station_entry_v4(location, station_index):
    """One 64-byte version-4 entry: the location zero-padded to 0x3E, the index, a pad."""
    location = bytes(location)
    if len(location) > INDEX_FIELD_V4:
        raise ValueError(f"a location is at most {INDEX_FIELD_V4} bytes here, got {len(location)}")
    return location.ljust(INDEX_FIELD_V4, b"\0") + bytes([station_index & 0xFF, 0])


def build_join_response_v4(host_index, joiner_index, entries, ack_id, update_counter=0,
                           max_active=2, max_buffer=0, max_total=8):
    """A version-4 unfragmented join response; `entries` is (location, station index), host first.
    A retail Sword's two-station response rebuilds byte for byte."""
    head = bytes([JOIN_RESPONSE, len(entries), host_index, joiner_index, 1, 0, len(entries), 0,
                  max_active, max_buffer, max_total, 0]) + struct.pack(">I", update_counter)
    body = b"".join(station_entry_v4(loc, idx) for loc, idx in entries)
    return head + body + struct.pack(">I", ack_id & 0xFFFFFFFF)


def build_update_mesh_v4(host_index, entries, update_counter):
    """The host's periodic version-4 update mesh: 12 bytes of header and all eight 64-byte seats."""
    head = bytes([UPDATE_MESH, len(entries), host_index, 0]) + struct.pack(">I", update_counter)
    head += bytes([1, 0, len(entries), 0])
    body = b"".join(station_entry_v4(loc, idx) for loc, idx in entries)
    return (head + body).ljust(UPDATE_MESH_SIZE_V4, b"\0")


def _station_info(data, off, count, version4=False):
    """5.31-5.45: 68 bytes (location, index, big-endian join order, pad). Version 4: 64 bytes, the
    index at 0x3E, no join order (docs/pia.md)."""
    size = STATION_INFO_SIZE_V4 if version4 else STATION_INFO_SIZE
    index_field = INDEX_FIELD_V4 if version4 else LOCATION_FIELD
    infos = []
    for _ in range(count):
        if off + size > len(data):
            break
        blob = data[off:off + size]
        entry = {"station_index": blob[index_field]}
        if not version4:
            entry["join_order"] = struct.unpack_from(">H", blob, index_field + 1)[0]
        try:
            entry["location"] = stp.parse_station_location(blob[:index_field])
        except ValueError as exc:
            entry["location_error"] = str(exc)
        infos.append(entry)
        off += size
    return infos


def parse_message(data):
    if not data:
        raise ValueError("empty mesh protocol message")
    return data[0], TYPE_NAMES.get(data[0], f"unknown {data[0]:#04x}")


# Host migration: a retail Sword sends MIGRATION_START `44 00 01` on port 1 (the reliable port) when
# the player accepts a trade; handlers and builders in docs/pia.md, 'Host migration'. Byte 0xAB of
# the mesh is the host's index, 0xAC the station's own.
MIGRATION_START_SIZE = 3
MIGRATION_RESPONSE_SIZE = 2
MIGRATION_FINISH_SIZE = 3
MAX_STATION_INDEX = 0x1F          # the bound both migration handlers check, 32 stations


def parse_migration_start(data):
    """-> {'host_index', 'new_host_index'}, or None; never raises, since a live-run reader must
    not (see `swsh.trade._maybe_parse`)."""
    data = bytes(data)
    if len(data) != MIGRATION_START_SIZE or data[0] != MIGRATION_START:
        return None
    return {"host_index": data[1], "new_host_index": data[2]}


def build_migration_response(station_index):
    """`station_index` is the station's own index (join response `our_index`, mesh byte 0xAC)."""
    if not 0 <= station_index <= MAX_STATION_INDEX:
        raise ValueError(f"station index {station_index} is outside the 32-station bound")
    return bytes([MIGRATION_RESPONSE, station_index])


def build_migration_finish(station_index, ok=True):
    """The new host's broadcast closing a migration; responses go to it (0x017c3250 via 0x017ca1a0).
    The sender 0x017c2e90 requires `station_index` (mesh+0xAC) to equal the host index; `ok` is
    read as a bool (0x017c1014)."""
    if not 0 <= station_index <= MAX_STATION_INDEX:
        raise ValueError(f"station index {station_index} is outside the 32-station bound")
    return bytes([MIGRATION_FINISH, station_index, 1 if ok else 0])


def parse_migration_finish(data):
    """-> {'host_index', 'flag'}, or None."""
    data = bytes(data)
    if len(data) != MIGRATION_FINISH_SIZE or data[0] != MIGRATION_FINISH:
        return None
    return {"host_index": data[1], "flag": data[2]}

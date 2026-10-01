"""Pia version 4's Mesh Station Protocol, protocol 0x14: 5.27's number with a different message.

Layout, handshake and gate byte: docs/pia.md, The version-4 connection request.
"""

import struct

from pokeldn.ldn.station_protocol import (CONNECTION_REQUEST, CONNECTION_RESPONSE,
                                          DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE,
                                          RELAY_CONNECTION_REQUEST, RESULT_NAMES,
                                          STATION_LOCATION_MAX, STATION_LOCATION_MIN,
                                          inet_address, ldn_constant_id,
                                          ldn_service_variable_id, station_location)

PROTOCOL = 0x14                   # 5.27-5.45's number, a different message
PLATFORM_SWITCH = 9               # 5.27-5.45 writes 4; `mov w8, #9; strb w8, [x1,#2]`

HEADER_SIZE = 0x11                # everything before the station location
OFF_NAT_FLAGS = 1
OFF_PLATFORM = 2
OFF_HAS_VARIABLE_ID = 3
OFF_CONSTANT_ID = 4
OFF_VARIABLE_ID = 0xC
OFF_NAT_LOCATION = 0x10
OFF_LOCATION = 0x11

__all__ = ["PROTOCOL", "PLATFORM_SWITCH", "HEADER_SIZE", "OFF_NAT_FLAGS", "OFF_PLATFORM",
           "OFF_HAS_VARIABLE_ID", "OFF_CONSTANT_ID", "OFF_VARIABLE_ID", "OFF_NAT_LOCATION",
           "OFF_LOCATION", "CONNECTION_REQUEST", "CONNECTION_RESPONSE",
           "OFF_RESPONSE_GATE", "RESPONSE_GATE_MAX", "ACCEPTED_RESPONSE_SIZE",
           "ACK", "ACK_SIZE", "build_ack", "ack_id_of", "DISCONNECTION_REQUEST",
           "DISCONNECTION_RESPONSE", "build_disconnection_response",
           "RELAY_CONNECTION_REQUEST", "RESULT_NAMES", "RESPONSE_SIZE", "build_connection_request",
           "build_connection_response", "parse_connection_request", "parse_incoming_request",
           "parse_station_location", "parse_reply", "inet_address", "ldn_constant_id",
           "ldn_service_variable_id", "station_location"]


def build_connection_request(target_constant_id, target_variable_id, location,
                             nat_flags=5, nat_location=1, with_variable_id=True, relay=False,
                             platform=PLATFORM_SWITCH):
    """`location` is `station_protocol.station_location`. `with_variable_id=False` clears [3], which
    skips the variable-id comparison; the id is still written so the fields after it stay put."""
    location = bytes(location)
    if not STATION_LOCATION_MIN <= len(location) <= STATION_LOCATION_MAX:
        raise ValueError(f"a station location is 0x20..0x40 bytes, this is {len(location)}")
    out = bytearray(HEADER_SIZE)
    out[0] = RELAY_CONNECTION_REQUEST if relay else CONNECTION_REQUEST
    out[OFF_NAT_FLAGS] = nat_flags & 0xFF
    out[OFF_PLATFORM] = platform & 0xFF
    out[OFF_HAS_VARIABLE_ID] = 1 if with_variable_id else 0
    struct.pack_into(">Q", out, OFF_CONSTANT_ID, target_constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_VARIABLE_ID, target_variable_id & 0xFFFFFFFF)
    out[OFF_NAT_LOCATION] = nat_location & 0xFF
    return bytes(out) + location


def parse_connection_request(data):
    """-> dict, the inverse of the builder."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a connection request is at least {HEADER_SIZE} bytes")
    return {"type": data[0], "nat_flags": data[OFF_NAT_FLAGS], "platform": data[OFF_PLATFORM],
            "with_variable_id": data[OFF_HAS_VARIABLE_ID],
            "constant_id": struct.unpack_from(">Q", data, OFF_CONSTANT_ID)[0],
            "variable_id": struct.unpack_from(">I", data, OFF_VARIABLE_ID)[0],
            "nat_location": data[OFF_NAT_LOCATION], "location": data[OFF_LOCATION:]}


RESPONSE_SIZE = 0x11              # the allocation the sender asks for
OFF_RESPONSE_RESULT = 1
OFF_RESPONSE_CONSTANT_ID = 5
OFF_RESPONSE_VARIABLE_ID = 0xD
OFF_RESPONSE_GATE = 0x37          # result 0 is dropped when this byte is 5 or more
RESPONSE_GATE_MAX = 5
ACCEPTED_RESPONSE_SIZE = 0x38     # the shortest response whose gate byte is inside the message


def build_connection_response(result, constant_id, variable_id, min_size=None, gate=1):
    """The 17-byte answer off the sender at 0x017c6c30: [0] 2, [1] result, [2] 9, [5] constant id
    u64 BE, [0xD] variable id u32 BE. `min_size` pads so the receiver's gate at [0x37]
    (`0x017c6ff0`) is read from inside the message; `gate` is the byte written there."""
    if min_size is not None and min_size > RESPONSE_SIZE:
        out = bytearray(min_size)
        if min_size > OFF_RESPONSE_GATE:
            out[OFF_RESPONSE_GATE] = gate & 0xFF
    else:
        out = bytearray(RESPONSE_SIZE)
    out[0] = CONNECTION_RESPONSE
    out[OFF_RESPONSE_RESULT] = result & 0xFF
    out[2] = PLATFORM_SWITCH
    struct.pack_into(">Q", out, OFF_RESPONSE_CONSTANT_ID, constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_RESPONSE_VARIABLE_ID, variable_id & 0xFFFFFFFF)
    return bytes(out)


def parse_station_location(data):
    """-> dict: two size-prefixed addresses, then the fixed tail. Checked against the console's own
    request, whose location carries a size-2 address and a size-6 one."""
    s1, s2 = data[0], data[1]
    a1, a2 = data[2:2 + s1], data[2 + s1:2 + s1 + s2]
    t = 2 + s1 + s2
    return {"address_sizes": (s1, s2), "address1": a1, "address2": a2,
            "ip": ".".join(str(b) for b in a2[:4]) if len(a2) >= 6 else None,
            "port": int.from_bytes(a2[4:6], "big") if len(a2) >= 6 else None,
            "relay_address": int.from_bytes(data[t:t + 4], "big"),
            "relay_port": int.from_bytes(data[t + 4:t + 6], "big"),
            "constant_id": int.from_bytes(data[t + 6:t + 14], "big"),
            "variable_id": int.from_bytes(data[t + 14:t + 18], "big"),
            "service_variable_id": int.from_bytes(data[t + 18:t + 22], "big"),
            "nat_flags": data[t + 22], "nat_location": data[t + 23],
            "probeinit": data[t + 24], "private_available": data[t + 25],
            "size": t + 26}


def parse_incoming_request(data):
    """A request the console sent: the header, its location and a trailing u32 ack id, which
    `0x017d5750` reads as the message size minus four."""
    got = parse_connection_request(data)
    location = got["location"]
    got["station"] = parse_station_location(location)
    got["ack_id"] = int.from_bytes(location[got["station"]["size"]:], "big") or None
    return got


ACK = 5
ACK_SIZE = 8


def build_ack(ack_id):
    """`05 00 00 00` then a u32 big-endian: the acked message's own trailing counter."""
    return bytes([ACK, 0, 0, 0]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def build_disconnection_response():
    """One byte: the handler of `03`, 0x017c6110, answers `04` and marks the station gone; a leaving
    Sword repeats `03` every 0.5 s until it hears it."""
    return bytes([DISCONNECTION_RESPONSE])


def ack_id_of(data):
    """The trailing counter, the last four bytes big-endian, as `0x017d5750` reads it."""
    return int.from_bytes(data[-4:], "big") if len(data) >= 4 else 0


def parse_reply(data):
    """-> (message type, connection result or None)."""
    if not data:
        return None, None
    kind = data[0]
    result = data[1] if kind == CONNECTION_RESPONSE and len(data) > 1 else None
    return kind, result

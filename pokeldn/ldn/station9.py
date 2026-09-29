"""Pia station protocol version 9 (Pia 5.10-5.18), protocol 0x14, for Let's Go Pikachu / Eevee.

Request layout read off Let's Go Pikachu `main` 0x5b8800 (docs/lgpe_session.md, "The station
protocol, for a mesh join")."""
import struct

from pokeldn.ldn.station_protocol import (ACK, CONNECTION_REQUEST, CONNECTION_RESPONSE,
                                          RELAY_CONNECTION_REQUEST, RESULT_NAMES,
                                          STATION_LOCATION_MAX, STATION_LOCATION_MIN,
                                          inet_address, ldn_constant_id,
                                          ldn_service_variable_id, player_info, station_location)

PROTOCOL = 0x14
VERSION = 9

HEADER_SIZE = 0x11
OFF_CONNECTION_ID = 1
OFF_VERSION = 2
OFF_IS_INVERSE = 3
OFF_CONSTANT_ID = 4
OFF_VARIABLE_ID = 0xC
OFF_INVERSE_ID = 0x10
OFF_LOCATION = 0x11

PLATFORM_SWITCH = 4

# The response parser at 0x5b9270 reads [1] result, [5..C] and [0xD..10] the receiver's own ids
# big-endian, and [0x37] a gate byte dropped when >= 5 (docs/lgpe_session.md).
OFF_RESPONSE_RESULT = 1
OFF_RESPONSE_VERSION = 2
OFF_RESPONSE_PLATFORM = 3
OFF_RESPONSE_FRAGMENT = 4
OFF_RESPONSE_CONSTANT_ID = 5
OFF_RESPONSE_VARIABLE_ID = 0xD
OFF_RESPONSE_GATE = 0x37
ACCEPTED_RESPONSE_SIZE = 0x38

# The full body a Let's Go station sends: 0x348 bytes, the PlayerInfo at 0x37.
OFF_RESPONSE_NETWORK_ID = 0x31  # the advertise data's first u32, big-endian
OFF_RESPONSE_FLAGS = 0x35           # 01 01, then the PlayerInfo at 0x37
OFF_RESPONSE_PLAYER_INFO = 0x37
FULL_RESPONSE_SIZE = 0x344  # the ack id follows, so the message is 0x348
STATION_NAME = "username"           # the name field of every captured station's PlayerInfo

__all__ = ["PROTOCOL", "VERSION", "HEADER_SIZE", "PLATFORM_SWITCH", "CONNECTION_REQUEST",
           "CONNECTION_RESPONSE", "RELAY_CONNECTION_REQUEST", "ACK", "RESULT_NAMES",
           "ACCEPTED_RESPONSE_SIZE", "FULL_RESPONSE_SIZE", "build_connection_request", "parse_connection_request",
           "build_connection_response", "build_ack", "ack_id_of", "parse_reply",
           "station_location", "inet_address", "ldn_constant_id", "ldn_service_variable_id"]


def build_connection_request(target_constant_id, target_variable_id, location, ack_id=0,
                             connection_id=0, inverse_connection_id=0, is_inverse=False,
                             relay=False):
    """`is_inverse=False` clears [3], so the console skips the variable-id comparison; the id is
    written anyway."""
    location = bytes(location)
    if not STATION_LOCATION_MIN <= len(location) <= STATION_LOCATION_MAX:
        raise ValueError(f"a station location is 0x20..0x40 bytes, this is {len(location)}")
    out = bytearray(HEADER_SIZE)
    out[0] = RELAY_CONNECTION_REQUEST if relay else CONNECTION_REQUEST
    out[OFF_CONNECTION_ID] = connection_id & 0xFF
    out[OFF_VERSION] = VERSION
    out[OFF_IS_INVERSE] = 1 if is_inverse else 0
    struct.pack_into(">Q", out, OFF_CONSTANT_ID, target_constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_VARIABLE_ID, target_variable_id & 0xFFFFFFFF)
    out[OFF_INVERSE_ID] = inverse_connection_id & 0xFF
    return bytes(out) + location + struct.pack(">I", ack_id & 0xFFFFFFFF)


def parse_connection_request(data):
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a connection request is at least {HEADER_SIZE} bytes")
    return {"type": data[0], "connection_id": data[OFF_CONNECTION_ID],
            "version": data[OFF_VERSION], "is_inverse": data[OFF_IS_INVERSE],
            "constant_id": struct.unpack_from(">Q", data, OFF_CONSTANT_ID)[0],
            "variable_id": struct.unpack_from(">I", data, OFF_VARIABLE_ID)[0],
            "inverse_connection_id": data[OFF_INVERSE_ID],
            "location": data[OFF_LOCATION:-4], "ack_id": struct.unpack_from(">I", data, len(data) - 4)[0]}


def build_connection_response(target_constant_id, target_variable_id, result=0, ack_id=1,
                              gate=1, platform=PLATFORM_SWITCH, network_id=None, player_name=None,
                              station_name=STATION_NAME):
    """The target ids are the receiver's own (the host's). With `network_id` the full 0x348-byte
    body is built; without it the body stops at the gate and carries no player."""
    if network_id is not None:
        out = bytearray(FULL_RESPONSE_SIZE)
    else:
        out = bytearray(ACCEPTED_RESPONSE_SIZE)
    out[0] = CONNECTION_RESPONSE
    out[OFF_RESPONSE_RESULT] = result & 0xFF
    out[OFF_RESPONSE_VERSION] = VERSION
    out[OFF_RESPONSE_PLATFORM] = platform & 0xFF
    struct.pack_into(">Q", out, OFF_RESPONSE_CONSTANT_ID, target_constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_RESPONSE_VARIABLE_ID, target_variable_id & 0xFFFFFFFF)
    out[OFF_RESPONSE_GATE] = gate & 0xFF
    if network_id is not None:
        struct.pack_into(">I", out, OFF_RESPONSE_NETWORK_ID, network_id & 0xFFFFFFFF)
        out[OFF_RESPONSE_FLAGS] = out[OFF_RESPONSE_FLAGS + 1] = 1
        if isinstance(player_name, bytes):
            player_name = player_name.decode("utf-8", "replace")
        info = player_info(name=station_name, account=player_name or "")
        out[OFF_RESPONSE_PLAYER_INFO:OFF_RESPONSE_PLAYER_INFO + len(info)] = info
    return bytes(out) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def build_ack(ack_id):
    """`05 00 00 00` then a u32 big-endian, one layout across every 5.x version."""
    return bytes([ACK, 0, 0, 0]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def ack_id_of(data):
    """The trailing u32, read by the console as the message size minus four."""
    return struct.unpack_from(">I", data, len(data) - 4)[0] if len(data) >= 4 else 0


def parse_reply(data):
    """-> (message type, connection result or None)."""
    if not data:
        return None, None
    kind = data[0]
    result = data[1] if kind == CONNECTION_RESPONSE and len(data) > 1 else None
    return kind, result

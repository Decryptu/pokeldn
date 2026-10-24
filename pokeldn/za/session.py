"""Everything a Legends Z-A local session is keyed on, from main 2.0.2 and a retail beacon
(docs/za.md has the address or scan behind each value)."""
from pokeldn.ldn.beacon import build_pia_header, decode_pia_header
from pokeldn.ldn import pia6
from pokeldn.ldn.pia6 import LINK_CODE_IV_BYTES, SessionKeys, packet_iv  # noqa: F401

# 64 bytes used raw: rodata 0x33391fc of main 2.0.2, and data 0x3eeda1f.
PASSPHRASE = b"BM7cXkadR9ugiXdHiurkiyhrQwcR3rMgCM5BF47dranKXWAGpGEA9z3ncXRnPjCX"
assert len(PASSPHRASE) == 64

# Sixteen ASCII bytes at data 0x3eeda0e.
GAME_KEY = b"p3bwdaSsywFXUkDu"
assert len(GAME_KEY) == 16

# The title id, the NACP's eight entries and what a searching console advertises.
COMM_ID = 0x0100F43008C44000

# Header initializer 0x24fadbc, validator 0x24faefc: version 0x10, the 6.39-7.2 band's 29-byte
# header `pokeldn.ldn.crypto.PiaHeader`.
PIA_VERSION = 16
PIA_HEADER_SIZE = 0x1D
PIA_TAG_SIZE = 8
PIA_PORT = 12345
# `(length - 0x1d) >> 6` below 0x71 at 0x24faf20: a packet of 0x1c5c bytes or less.
MAX_PACKET_SIZE = 0x1D + 0x71 * 0x40 - 1


def session_keys(ssid, game_key=GAME_KEY):
    return pia6.session_keys(ssid, game_key)


# A console on the local search screen, measured on two retail sessions.
LDN_PROTOCOL = 1
ADVERTISE_VERSION = 4
SCENE_ID = 1
APP_VERSION = 6                   # the LDN application version field
MAX_PARTICIPANTS = 2
SYS_COMM_VERSION = 22             # the Pia system block's system communication version
APP_COMM_VERSION = 6              # and its application communication version
ADVERTISE_NAME = " "              # the console does not publish its own name

# Arceus's link code mask under the same game key (docs/pla.md, The link code in the advertisement).
LINK_CODE_LEN = 8


def link_code_keystream(game_key=GAME_KEY):
    return pia6.link_code_keystream(game_key)


LINK_CODE_MASK = link_code_keystream()
assert LINK_CODE_MASK == bytes.fromhex("1068a742ac3a8787ab6066a161f5d5e1")   # two retail sessions

# The game's application data, after the 0x5C system property block `ldn.beacon` codes.
GAME_DATA_SIZE = 20
CODE_OFF, CODE_LEN_OFF = 0x00, 0x10


def user_password(code):
    return pia6.link_code_password(LINK_CODE_MASK, code)


def link_code(user_password_bytes, length=LINK_CODE_LEN):
    return pia6.link_code_of(LINK_CODE_MASK, user_password_bytes, length)


def build_game_data(code):
    return pia6.link_code_game_data(code)


def build_advertise_data(code, *, name=ADVERTISE_NAME, num_players=1,
                         player_limit_enabled=True, app_comm_ver=APP_COMM_VERSION):
    """-> the 112 bytes a console waiting on this code advertises; reproduces both captures bar
    their SSID."""
    code = code.encode() if isinstance(code, str) else bytes(code)
    header = build_pia_header(sys_comm_ver=SYS_COMM_VERSION, app_comm_ver=app_comm_ver,
                              user_password=user_password(code),
                              player_limit_enabled=player_limit_enabled,
                              num_players=num_players, nickname=name, name_encoding=1)
    return header + build_game_data(code)


def parse_advertise_data(app_data):
    """-> dict: the system block's fields, the code, and the code the password field agrees on."""
    app = bytes(app_data)
    out = decode_pia_header(app)
    game = app[0x5C:0x5C + GAME_DATA_SIZE]
    if len(game) < GAME_DATA_SIZE:
        raise ValueError(f"application data is {len(app)} bytes, need at least "
                         f"{0x5C + GAME_DATA_SIZE}")
    size = int.from_bytes(game[CODE_LEN_OFF:CODE_LEN_OFF + 4], "little")
    out["code_size"] = size
    out["code"] = game[CODE_OFF:CODE_OFF + min(size, 16)].decode("ascii", "replace")
    out["password_code"] = link_code(bytes.fromhex(out["user_password"]), size)
    out["game_data"] = game
    return out


# A reference joiner's fifteen-byte type-6 answer; a host answered without the sequence repeats its
# update every two seconds (docs/za.md).
SESSION_UPDATE_ACK_TAIL = bytes([0x00, 0x01])


def session_update_sequence(payload):
    """-> the sequence a type-5 update session carries, at its second and third bytes."""
    payload = bytes(payload)
    if len(payload) < 3 or payload[0] != 5:
        raise ValueError("not a type-5 update session")
    return int.from_bytes(payload[1:3], "big")


def build_session_update_ack(constant_id, sequence):
    """-> the fifteen bytes a joiner answers a type-5 update session with."""
    constant_id = bytes(constant_id)
    if len(constant_id) == 6:
        constant_id += b"\x00\x00"
    if len(constant_id) != 8:
        raise ValueError(f"a constant id is six or eight bytes, not {len(constant_id)}")
    return (bytes([6]) + constant_id + (sequence & 0xFFFFFFFF).to_bytes(4, "big")
            + SESSION_UPDATE_ACK_TAIL)


# Leaving (docs/za.md, Leaving). A location here is a constant id and a variable id, 8 + 2 bytes.
SESSION_LEAVE_REQUEST, SESSION_LEAVE_RESPONSE = 3, 4
SESSION_START_MIGRATION, SESSION_START_MIGRATION_ACK = 9, 10


def build_leave_response(request, random4):
    """-> the fifteen-byte type 4 a host answers a type-3 leave with: the type, a random word, the
    leaver's location copied from the request (writer `0x254c740`, reader `0x25474f8`)."""
    request = bytes(request)
    if len(request) < 15 or request[0] != SESSION_LEAVE_REQUEST:
        raise ValueError("not a type-3 leave request")
    return bytes([SESSION_LEAVE_RESPONSE]) + bytes(random4)[:4].ljust(4, b"\0") + request[5:15]


def migration_target(start):
    """-> the (constant id, variable id) a type-9 start host migration names as the next host."""
    start = bytes(start)
    if len(start) < 28 or start[0] != SESSION_START_MIGRATION:
        raise ValueError("not a type-9 start host migration")
    return start[18:26], int.from_bytes(start[26:28], "big")


def build_start_migration(host_constant_id, host_var, host_ip, next_constant_id, next_var,
                          port=PIA_PORT):
    """-> the 30-byte type 9 a leaving host names the next host with: its location, address type 0,
    IPv4 and port, then the next host's location and `00 01` (`0x255a91c`; handler `0x2550684`)."""
    return (bytes([SESSION_START_MIGRATION]) + bytes(host_constant_id)
            + (host_var & 0xFFFF).to_bytes(2, "big") + b"\0"
            + bytes(int(x) for x in host_ip.split(".")) + (port & 0xFFFF).to_bytes(2, "big")
            + bytes(next_constant_id) + (next_var & 0xFFFF).to_bytes(2, "big") + b"\0\x01")


def migration_acked(ack, host_constant_id, host_var, next_constant_id, next_var):
    """-> True when a type 10 is the named next host's answer to our type 9 (reader `0x2550a64`)."""
    ack = bytes(ack)
    return (len(ack) == 21 and ack[0] == SESSION_START_MIGRATION_ACK
            and ack[1:11] == bytes(next_constant_id) + (next_var & 0xFFFF).to_bytes(2, "big")
            and ack[11:21] == bytes(host_constant_id) + (host_var & 0xFFFF).to_bytes(2, "big"))


def build_migration_ack(start):
    """-> the 21-byte type 10 the named station answers a type 9 with: its own location, then the
    sender's (reader `0x2550a64`)."""
    start = bytes(start)
    migration_target(start)
    return bytes([SESSION_START_MIGRATION_ACK]) + start[18:28] + start[1:11]


def build_leave_request(constant_id, variable_id, ip, random4, port=PIA_PORT):
    """-> the 22-byte type 3 a station leaving sends its host: the type, a random word, its location,
    address type 0, its IPv4 and port (`LeaveMeshJob` `0x2557e54`; a retail console's own leave)."""
    return (bytes([SESSION_LEAVE_REQUEST]) + bytes(random4)[:4].ljust(4, b"\0")
            + bytes(constant_id) + (variable_id & 0xFFFF).to_bytes(2, "big") + b"\0"
            + bytes(int(x) for x in ip.split(".")) + (port & 0xFFFF).to_bytes(2, "big"))

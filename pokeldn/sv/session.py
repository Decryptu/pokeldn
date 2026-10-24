"""Everything a Scarlet / Violet local session is keyed on, from main 4.0.0 and a retail beacon
(docs/sv.md has the address or scan behind each value)."""
from pokeldn.ldn.beacon import build_pia_header, decode_pia_header
from pokeldn.ldn import pia6
from pokeldn.ldn.pia6 import SessionKeys, packet_iv  # noqa: F401

# 64 bytes used raw, data 0x44dfd0a of main 4.0.0; equal to Sword's and Arceus's.
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# Sixteen ASCII bytes at data 0x44dfcfe.
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# Both retail versions advertise Scarlet's id (docs/sv.md).
COMM_ID_SCARLET = 0x0100A3D008C5C000
COMM_ID_VIOLET = 0x01008F6008C5E000

# Header initializer 0x697134 of main 4.0.0: Arceus's layout (docs/pla.md).
PIA_VERSION = 11
PIA_HEADER_SIZE = 0x1C
PIA_TAG_SIZE = 8
PIA_PORT = 12345


def session_keys(ssid, game_key=GAME_KEY):
    return pia6.session_keys(ssid, game_key)


# A searching retail Scarlet 4.0.0, offline, no link code.
LDN_PROTOCOL = 1                  # AES-CTR
ADVERTISE_VERSION = 4
SCENE_ID = 4
APP_VERSION = 21                  # the LDN application version field
MAX_PARTICIPANTS = 2
SYS_COMM_VERSION = 0x15           # the Pia system block's system communication version
APP_COMM_VERSION = 0x15           # and its application communication version
ADVERTISE_NAME = " "              # the console does not publish its own name
GAME_DATA_SIZE = 40               # the game's bytes after the 0x5c system block: zero on every scan
# Both retail consoles (Switch 2) advertise platform 1; the LDN layer's default is 0.
PLATFORM = 1


# Link Code: masked into the user password and in clear at game byte +0x00, length at +0x24
# (docs/sv.md, The link code).
LINK_CODE_MASK = bytes.fromhex("e5ab19ed742b6d40885998bf968aa166")
CODE_LEN_OFF = 0x24


def user_password(code):
    """-> the sixteen password bytes a console searching with this code advertises."""
    return bytes(m ^ c for m, c in zip(LINK_CODE_MASK, code.encode().ljust(16, b"\x00")))


def build_game_data(code):
    """-> the 40 game bytes for a code: the code, zeros, its length as a u32 at +0x24."""
    raw = code.encode()
    if len(raw) > 16:
        raise ValueError(f"a link code is at most 16 bytes, not {len(raw)}")
    return raw.ljust(CODE_LEN_OFF, b"\x00") + len(raw).to_bytes(4, "little")


def link_code(app_data):
    """-> the code a network advertises, or "" when it carries none."""
    game = bytes(app_data)[0x5C:0x5C + GAME_DATA_SIZE]
    if len(game) < GAME_DATA_SIZE:
        return ""
    size = int.from_bytes(game[CODE_LEN_OFF:CODE_LEN_OFF + 4], "little")
    return game[:min(size, 16)].decode("ascii", "replace")


def build_advertise_data(*, password=b"", num_players=1, game_data=None, code=None):
    """-> the 132 bytes a searching console advertises: the 0x5C Pia system block and 40 game bytes;
    reproduces the retail scans byte for byte."""
    if code:
        password = user_password(code)
        game_data = build_game_data(code) if game_data is None else game_data
    header = build_pia_header(sys_comm_ver=SYS_COMM_VERSION, app_comm_ver=APP_COMM_VERSION,
                              user_password=password, player_limit_enabled=True,
                              num_players=num_players, nickname=ADVERTISE_NAME, name_encoding=1)
    game = bytes(GAME_DATA_SIZE) if game_data is None else bytes(game_data)
    if len(game) != GAME_DATA_SIZE:
        raise ValueError(f"the game data is {GAME_DATA_SIZE} bytes, not {len(game)}")
    return header + game


def parse_advertise_data(app_data):
    """-> dict: the system block's fields and the 40 game bytes."""
    app = bytes(app_data)
    out = decode_pia_header(app)
    out["game_data"] = app[0x5C:0x5C + GAME_DATA_SIZE]
    return out


PROTOCOL_NAMES = {
    0x08: "keep alive", 0x2C: "net", 0x30: "turn", 0x58: "rtt", 0x65: "sync",
    0x68: "unreliable", 0x74: "clone atomic", 0x75: "clone event",
    0x76: "clone broadcast event", 0x77: "clone clock", 0x7B: "voice", 0x7C: "reliable",
    0x80: "broadcast reliable", 0x81: "stream broadcast reliable", 0x98: "session",
    0xA0: "nat traversal result", 0xA4: "monitoring data", 0xAC: "wan nat",
}
# Session type 7 is LeaveMeshWithHostMigrationJob (0x6d8de0) handing the host role over, not the
# wiki's left-station sync (docs/sv.md).
SESSION_MESSAGE_NAMES = {
    0: "join request", 1: "join request ack", 2: "join response", 3: "leave request",
    5: "update session", 6: "update session ack", 7: "start host migration",
    8: "start host migration ack",
}


def describe_message(msg):
    """One log line for a Pia message: protocol, Session type, port, flags and length."""
    name = PROTOCOL_NAMES.get(msg.protocol, "?")
    extra = ""
    if msg.protocol == 0x98 and msg.payload:
        extra = f" {SESSION_MESSAGE_NAMES.get(msg.payload[0], '?')}({msg.payload[0]})"
    return (f"proto 0x{msg.protocol:02x} {name}{extra} port={msg.port} "
            f"flags=0x{msg.message_flags:02x} len={len(msg.payload)}")

"""Everything a Legends Arceus session is keyed on, from update 1.1.1's `main` (docs/pla.md).

Passphrase and game key equal Sword's; the Pia header is version 11 (`pokeldn.ldn.pia6`) and the
session key and network id come from the SSID.
"""
from pokeldn.ldn import pia6
from pokeldn.ldn.pia6 import LINK_CODE_IV_BYTES, SessionKeys, packet_iv  # noqa: F401

# 64 bytes used raw, rodata 0x3985319, length 0x40 at 0x2c24268.
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# rodata 0x3985308; installed at 0x2c1e684, kept at LdnProtocol+0x238.
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# The title id, built at 0x264082c and passed to the LDN setup 0x2c1e684 in x3.
COMM_ID = 0x01001F5010DFA000

PIA_VERSION = 11
PIA_HEADER_SIZE = 0x1C
PIA_TAG_SIZE = 8

PIA_PORT = 12345


def session_keys(ssid, game_key=GAME_KEY):
    return pia6.session_keys(ssid, game_key)


# A waiting console's advertisement, measured on two retail sessions.
LDN_PROTOCOL = 1                  # the advertisement is AES-CTR, as Sword's is
ADVERTISE_VERSION = 4             # the advertisement frame version; the GBA app is 3, Sword 2
SCENE_ID = 1
MAX_PARTICIPANTS = 2

# The code, NUL-padded to sixteen bytes, GCM-encrypted under the game key by `0x6fc454`: one XOR
# with this fixed keystream (docs/pla.md, The link code in the advertisement).
LINK_CODE_LEN = 8          # pia6.LINK_CODE_IV_BYTES is read at `0x6fc4e4`..`0x6fc4fc`


def link_code_keystream(game_key=GAME_KEY):
    return pia6.link_code_keystream(game_key)


LINK_CODE_MASK = link_code_keystream()
assert LINK_CODE_MASK == bytes.fromhex("e5ab19ed742b6d40885998bf968aa166")   # five retail sessions

# The game's application data, after the 0x5C system property block `ldn.beacon` already codes.
GAME_DATA_SIZE = 20
CODE_OFF, CODE_LEN_OFF = 0x00, 0x10


def user_password(code):
    return pia6.link_code_password(LINK_CODE_MASK, code)


def link_code(user_password_bytes, length=LINK_CODE_LEN):
    return pia6.link_code_of(LINK_CODE_MASK, user_password_bytes, length)


def build_game_data(code):
    return pia6.link_code_game_data(code)


def parse_advertise_data(app_data):
    """-> dict: the 0x5C block's fields, the game's `code`, and the `password_code` the password
    field decodes to; the two have matched on every session measured."""
    from pokeldn.ldn.beacon import decode_pia_header

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


# What the console puts in the player name field: one byte, a space, UTF-8. The game does not
# advertise the player's name.
ADVERTISE_NAME = " "
APP_COMM_VERSION = 0
SYS_COMM_VERSION = 21


def build_advertise_data(code, *, name=ADVERTISE_NAME, num_players=1,
                         player_limit_enabled=True, app_comm_ver=APP_COMM_VERSION):
    """-> the 112 bytes a console waiting on this code advertises; reproduces both captures."""
    from pokeldn.ldn.beacon import build_pia_header

    code = code.encode() if isinstance(code, str) else bytes(code)
    header = build_pia_header(sys_comm_ver=SYS_COMM_VERSION, app_comm_ver=app_comm_ver,
                              user_password=user_password(code),
                              player_limit_enabled=player_limit_enabled,
                              num_players=num_players, nickname=name, name_encoding=1)
    return header + build_game_data(code)

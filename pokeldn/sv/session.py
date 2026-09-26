"""Everything a Scarlet / Violet local session is keyed on.

Read off the decompressed `main` of update 4.0.0 and off a retail Scarlet's own beacon on the
offline Link Trade search. `docs/sv.md` has the address or the scan behind each value.
"""
from dataclasses import dataclass

from pokeldn.ldn.beacon import build_pia_header, decode_pia_header
from pokeldn.ldn.pia6 import gcm_iv, ldn_network_id, ldn_session_key

# The LDN passphrase, 64 bytes used raw: data 0x44dfd0a of main 4.0.0 (and rodata 0x3c0c8c0),
# byte-identical to Sword's and Arceus's and to the wiki's Scarlet/Violet row.
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# The Pia game key, sixteen ASCII bytes at data 0x44dfcfe, in front of the passphrase.
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# The local communication ids: the NACP lists both. A retail Scarlet and a retail Violet both
# advertise Scarlet's (docs/sv.md). Neither is a constant in the image.
COMM_ID_SCARLET = 0x0100A3D008C5C000
COMM_ID_VIOLET = 0x01008F6008C5E000

# Header initializer 0x697134 of main 4.0.0: magic 0x32AB9864 at +8, the byte 0x0b at +0xc, header
# 0x1c, the same object layout as Arceus's (`docs/pla.md`).
PIA_VERSION = 11
PIA_HEADER_SIZE = 0x1C
PIA_TAG_SIZE = 8
PIA_PORT = 12345


@dataclass
class SessionKeys:
    session_key: bytes
    game_key: bytes
    ssid: bytes
    network_id: int

    def __repr__(self):
        return (f"SessionKeys(session={self.session_key.hex()} game={self.game_key.hex()} "
                f"ssid={self.ssid.hex()} network_id={self.network_id:#010x})")


def session_keys(ssid, game_key=GAME_KEY):
    """-> SessionKeys for a network, from its SSID alone: the band's derivation, `pia6`."""
    ssid = bytes(ssid)
    return SessionKeys(ldn_session_key(game_key, ssid), bytes(game_key), ssid,
                       ldn_network_id(ssid))


def packet_iv(keys, source_ip, nonce8):
    """The twelve-byte GCM IV for a version-11 packet. `source_ip` is the SENDER's LDN address."""
    return gcm_iv(keys.network_id, source_ip, nonce8)


# What a searching retail Scarlet 4.0.0 advertises, offline mode, no link code (sv01, sv02).
LDN_PROTOCOL = 1                  # AES-CTR advertisement, as Sword's and Arceus's
ADVERTISE_VERSION = 4
SCENE_ID = 4
APP_VERSION = 21                  # the LDN application version field
MAX_PARTICIPANTS = 2
SYS_COMM_VERSION = 0x15           # the Pia system block's system communication version
APP_COMM_VERSION = 0x15           # and its application communication version
ADVERTISE_NAME = " "              # a one-byte UTF-8 name; the console does not publish its own here
GAME_DATA_SIZE = 40               # the game's bytes after the 0x5c system block: zero on every scan
# The station platform byte in the advertisement's participant entry and in the authentication
# response. Both retail consoles are Switch 2 and advertise 1; the LDN layer's own default is 0.
PLATFORM = 1


# A Link Code rides the advertisement twice: NUL-padded into the user password under the mask
# Legends Arceus uses (the same game key), and in clear at game byte +0x00 with its length at +0x24
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
    """-> the 132 bytes a searching console advertises: the 0x5C Pia system block and 40 game bytes.

    Reproduces the three sv01 scans and the sv02 session beacon byte for byte with the defaults
    (one pass carried `fb149700` at game byte +0x20; what writes it is unknown).
    """
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

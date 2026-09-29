"""Everything a Legends Z-A local session is keyed on, from main 2.0.2 and a retail beacon
(docs/za.md has the address or scan behind each value)."""
from dataclasses import dataclass

from pokeldn.ldn.beacon import build_pia_header, decode_pia_header
from pokeldn.ldn.pia6 import gcm_iv, ldn_network_id, ldn_session_key

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
    """-> SessionKeys for a network, from its SSID alone: the band's derivation."""
    ssid = bytes(ssid)
    return SessionKeys(ldn_session_key(game_key, ssid), bytes(game_key), ssid,
                       ldn_network_id(ssid))


def packet_iv(keys, source_ip, nonce8):
    """The twelve-byte GCM IV for a packet. `source_ip` is the SENDER's LDN address."""
    return gcm_iv(keys.network_id, source_ip, nonce8)


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
LINK_CODE_IV_BYTES = (1, 8, 7, 2)
LINK_CODE_LEN = 8


def link_code_keystream(game_key=GAME_KEY):
    """-> the sixteen bytes the game XORs the code into."""
    from Crypto.Cipher import AES
    game_key = bytes(game_key)
    iv = bytes(game_key[i] for i in LINK_CODE_IV_BYTES)
    return AES.new(game_key, AES.MODE_GCM, nonce=iv).encrypt(bytes(16))


LINK_CODE_MASK = link_code_keystream()
assert LINK_CODE_MASK == bytes.fromhex("1068a742ac3a8787ab6066a161f5d5e1")   # two retail sessions

# The game's application data, after the 0x5C system property block `ldn.beacon` codes.
GAME_DATA_SIZE = 20
CODE_OFF, CODE_LEN_OFF = 0x00, 0x10


def user_password(code):
    """-> the sixteen bytes a console advertises for this code."""
    code = code.encode() if isinstance(code, str) else bytes(code)
    return bytes(m ^ c for m, c in zip(LINK_CODE_MASK, code.ljust(16, b"\x00")))


def link_code(user_password_bytes, length=LINK_CODE_LEN):
    """-> the code a console is waiting on, read back out of its advertised password field."""
    raw = bytes(m ^ p for m, p in zip(LINK_CODE_MASK, bytes(user_password_bytes)))
    return raw[:length].decode("ascii", "replace")


def build_game_data(code):
    """-> the twenty bytes after the system property block: the code, then its length."""
    code = code.encode() if isinstance(code, str) else bytes(code)
    return code.ljust(16, b"\x00")[:16] + len(code).to_bytes(4, "little")


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

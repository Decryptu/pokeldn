"""Everything a Legends Arceus session is keyed on, as far as the binary has been read.

Read off the decompressed `main` of update 1.1.1, offline, with no hardware run. `docs/pla.md` has
the address behind each value. Two things separate this title from Sword/Shield, which shares its
passphrase and its game key byte for byte:

  * the Pia header is version 11, the 6.16 to 6.30 band, and `pokeldn.ldn.pia6` speaks it.
  * the session key comes from the network's SSID rather than from a session parameter in the
    advertisement. There is no seed to read out of the application data at this band, and the
    network id is a hash of the SSID rather than a broadcast field.
"""
from dataclasses import dataclass

from pokeldn.ldn.pia6 import gcm_iv, ldn_network_id, ldn_session_key

# The LDN passphrase, 64 bytes used RAW. rodata 0x3985319, copied in four `ldp`/`stp` pairs with the
# length stored right after it as a literal 0x40 (0x2c24268). Byte-identical to Sword/Shield's.
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# The Pia game key, sixteen ASCII bytes at rodata 0x3985308, used unchanged. The LDN setup at
# 0x2c1e684 installs it; Pia keeps it at LdnProtocol+0x238 and derives the session key from it.
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# The local communication id, built by the `mov`/`movk` run at 0x264082c and passed to the LDN setup
# at 0x2c1e684 in x3. It is the title id. NOT yet seen on air.
COMM_ID = 0x01001F5010DFA000

PIA_VERSION = 11
PIA_HEADER_SIZE = 0x1C
PIA_TAG_SIZE = 8

# Every Pia station listens on the same port; this is not game-specific, and BDSP measured it.
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
    """-> SessionKeys for a network, from its SSID alone.

    `ssid` is the LDN network's SSID as scanned. Both the session key and the network id come out of
    it, so nothing here depends on what the game puts in its application data.
    """
    ssid = bytes(ssid)
    return SessionKeys(ldn_session_key(game_key, ssid), bytes(game_key), ssid,
                       ldn_network_id(ssid))


def packet_iv(keys, source_ip, nonce8):
    """The twelve-byte GCM IV for a version-11 packet: `pia6`'s construction, unchanged.

    `source_ip` is the SENDER's LDN address, dotted or four bytes.
    """
    return gcm_iv(keys.network_id, source_ip, nonce8)


# What a waiting console advertises, measured on two sessions of a retail Legends Arceus.
LDN_PROTOCOL = 1                  # the advertisement is AES-CTR, as Sword's is
ADVERTISE_VERSION = 4             # the advertisement frame version; the GBA app is 3, Sword 2
SCENE_ID = 1
MAX_PARTICIPANTS = 2

# The eight-digit code the player types is XORed into the advertisement's sixteen-byte user
# password field, and the game's own twenty bytes carry the code in the clear beside it. The mask
# is the password a code of eight NULs would give. Identical across five sessions with five SSIDs,
# two codes and a full close and reopen of the game. It is not a literal in `main`.
LINK_CODE_MASK = bytes.fromhex("e5ab19ed742b6d40885998bf968aa166")
LINK_CODE_LEN = 8

# The game's application data, after the 0x5C system property block `ldn.beacon` already codes.
GAME_DATA_SIZE = 20
CODE_OFF, CODE_LEN_OFF = 0x00, 0x10


def user_password(code):
    """-> the sixteen bytes a console advertises for this code.

    `code` is the eight digits as a string or bytes. The first eight bytes of the mask carry the
    code; the rest of the field is the mask unchanged, which is why a code shorter than the field
    leaves the tail alone.
    """
    code = code.encode() if isinstance(code, str) else bytes(code)
    return bytes(m ^ c for m, c in zip(LINK_CODE_MASK, code.ljust(16, b"\x00")))


def link_code(user_password_bytes, length=LINK_CODE_LEN):
    """-> the code a console is waiting on, read back out of its advertised password field."""
    raw = bytes(m ^ p for m, p in zip(LINK_CODE_MASK, bytes(user_password_bytes)))
    return raw[:length].decode("ascii", "replace")


def build_game_data(code):
    """-> the twenty bytes the game puts after the system property block: the code, then its length."""
    code = code.encode() if isinstance(code, str) else bytes(code)
    return code.ljust(16, b"\x00")[:16] + len(code).to_bytes(4, "little")


def parse_advertise_data(app_data):
    """-> dict: the 0x5C system property block's fields, the code, and the code the password agrees on.

    `code` is what the game states in its own twenty bytes. `password_code` is what the password
    field decodes to. They have matched on every session measured; a disagreement means the mask
    is not constant and the derivation needs another look.
    """
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
    """-> the 112 bytes a console waiting on this code advertises.

    The 0x5C system property block is `ldn.beacon`'s, which is the band's and not this game's; the
    twenty bytes after it are the game's. Reproduces both captured advertisements byte for byte.
    """
    from pokeldn.ldn.beacon import build_pia_header

    code = code.encode() if isinstance(code, str) else bytes(code)
    header = build_pia_header(sys_comm_ver=SYS_COMM_VERSION, app_comm_ver=app_comm_ver,
                              user_password=user_password(code),
                              player_limit_enabled=player_limit_enabled,
                              num_players=num_players, nickname=name, name_encoding=1)
    return header + build_game_data(code)

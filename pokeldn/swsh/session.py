"""What a Sword/Shield session is keyed on, from a Shield 1.3.2 image (docs/swsh_session.md).

The game key is a literal with no version substitution; the session seed is at application data +12.
"""

import struct
from dataclasses import dataclass

from pokeldn.ldn.pia5 import gcm_iv, ldn_nonce_crc, ldn_session_key, password_crc

# 64 bytes used raw, main.bin 0x203ff04; the length is the literal 0x40 at 0x006c3ec8.
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# main.bin 0x1c3dc87, used unchanged; Pia keeps it at LocalProtocol+0x4d4 (setter 0x17ab750).
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# Header initializer 0x17748bc stores 0x00000004_32AB9864; validators check (byte & 0x7f) == 4.
PIA_VERSION = 4

# Deserializer 0x1774730: magic, version, station byte, a big-endian halfword, an 8-byte nonce and a
# sixteen-byte GCM tag.
PIA_HEADER_SIZE = 0x20
PIA_TAG_SIZE = 16

PIA_PORT = 12345


def session_key(seed, game_key=GAME_KEY):
    """AES-128-ECB(game key) over sixteen SEAD bytes, `pia5`'s derivation [main.bin 0x17ab010]."""
    return ldn_session_key(game_key, seed)


# Sword's title id, read off its advertisement.
COMM_ID = 0x0100ABF008968000

# BDSP's offsets: the seed at 12 authenticated all 484 packets of a capture.
NETWORK_ID_OFF = 0
SESSION_PARAM_OFF = 12
PASSWORD_CRC_OFF = 4


@dataclass
class SessionKeys:
    session_key: bytes
    game_key: bytes
    network_id_le: bytes
    session_param: int

    def __repr__(self):
        return (f"SessionKeys(session={self.session_key.hex()} game={self.game_key.hex()} "
                f"network_id_le={self.network_id_le.hex()} param={self.session_param:#010x})")


def session_keys(net, game_key=GAME_KEY):
    """-> SessionKeys, from a scanned network. `net` needs `application_data`."""
    app = bytes(getattr(net, "application_data", b"") or b"")
    if len(app) < SESSION_PARAM_OFF + 4:
        raise ValueError(f"application data is {len(app)} bytes, need at least "
                         f"{SESSION_PARAM_OFF + 4}")
    param = struct.unpack_from("<I", app, SESSION_PARAM_OFF)[0]
    return SessionKeys(ldn_session_key(game_key, param), bytes(game_key),
                       app[NETWORK_ID_OFF:NETWORK_ID_OFF + 4], param)


def packet_iv(keys, source_mac, nonce8, source_id=0):
    """The twelve-byte GCM IV for a version-4 packet: `pia5`'s construction."""
    return gcm_iv(ldn_nonce_crc(keys.network_id_le, source_mac), source_id, nonce8)

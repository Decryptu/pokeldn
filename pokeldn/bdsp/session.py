"""What a BDSP session is keyed on, from the scanned advertisement (docs/bdsp_session.md)."""

import struct
from dataclasses import dataclass

from pokeldn.ldn.pia5 import ldn_game_key, ldn_session_key

# Used raw, 27 bytes, unpadded, for nn::ldn::CreateNetwork only; distinct from Pia's game key.
PASSPHRASE = b"WirelessStrongCryptoKey2021"

COMM_ID = 0x0100000011D90000
PIA_PORT = 12345

# From global-metadata.dat. The game key is this with four bytes replaced by the local communication
# version (docs/bdsp_session.md).
CRYPTO_KEY_DATA_SEED = bytes.fromhex("9918bd0fdcfa65779918bd0fdcfa6577")

# Offsets into the advertisement's application data.
NETWORK_ID_OFF = 0
SESSION_PARAM_OFF = 12


@dataclass
class SessionKeys:
    session_key: bytes
    game_key: bytes
    network_id_le: bytes          # four bytes, in the order the CRC eats them
    session_param: int

    def __repr__(self):
        return (f"SessionKeys(session={self.session_key.hex()} game={self.game_key.hex()} "
                f"network_id_le={self.network_id_le.hex()} param={self.session_param:#010x})")


def session_keys(net):
    """-> SessionKeys, from a scanned network. `net` needs `application_data` and `app_version`."""
    app = bytes(getattr(net, "application_data", b"") or b"")
    if len(app) < SESSION_PARAM_OFF + 4:
        raise ValueError(f"application data is {len(app)} bytes, need at least "
                         f"{SESSION_PARAM_OFF + 4}")
    network_id_le = app[NETWORK_ID_OFF:NETWORK_ID_OFF + 4]
    session_param = struct.unpack_from("<I", app, SESSION_PARAM_OFF)[0]
    game_key = ldn_game_key(CRYPTO_KEY_DATA_SEED, net.app_version)
    return SessionKeys(ldn_session_key(game_key, session_param), game_key,
                       network_id_le, session_param)

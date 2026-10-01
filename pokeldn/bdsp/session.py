"""What a BDSP session is keyed on, from the scanned advertisement (docs/bdsp_session.md)."""

import struct
from dataclasses import dataclass

from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn import reliable5 as rl
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


def answer_departure(payload, own_index):
    """A message on the mesh's reliable port (0x18 port 1) -> (ack, answer): the window's ack, and
    the unreliable answer a departure waits for, or None (docs/bdsp_session.md, Leaving).

    A leave request `04 <leaver>` at the host is owed `08 <host index>` [0x0154c860, 0x0154baf8];
    a migration start `44 <host> <new host>` at a station is owed `48 <own index>`
    [0x0154d66c, 0x0154b068]. A retail Pia sends either answer twice."""
    d = rl.parse(payload)
    if d["is_ack"] or d["truncated"]:
        return None, None
    # nothing of ours is on this window, so our lowest pending is its first id
    ack = rl.build_ack_message(d["sequence_id"] + 1, stream_id=d["stream_id"], field_0x50=1,
                               lowest_pending=1)
    body = bytes(d["payload"])
    if len(body) == 2 and body[0] == mp.LEAVE_REQUEST and body[1] != own_index:
        return ack, mp.build_leave_response(own_index)
    start = mp.parse_migration_start(body)
    if start is not None and start["host_index"] != own_index:
        return ack, mp.build_migration_response(own_index)
    return ack, None

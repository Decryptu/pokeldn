"""The Max Raid den lobby's messages: id 2000, `net_contents.nesthole.protocol_buffers.
NestholeAsyncDataHolder`, each field a holder of one `bytes` field (main `0x1bfde43`, `0x20677b0`).
A joining guest sends PlayerInfo, BattleReady and SelectPokemon after the snapshot (docs/swsh_raid.md)."""
import struct

from pokeldn.swsh.trade import field, message

NESTHOLE = 2000
TIME_LIMIT, PLAYER_INFO, BATTLE_READY, SELECT_POKEMON = 1, 2, 3, 4
NAME_CHARS = 13


def holder(which, data):
    return message(NESTHOLE, field(which, field(1, data)))


def player_info(name):
    """40 bytes as two emulated Shields sent them: 8 zero, u32 0x12, the UTF-16 name, then 0x03."""
    raw = name.encode("utf-16-le")
    if len(raw) > 2 * (NAME_CHARS - 1):
        raise ValueError(f"{name!r} is longer than {NAME_CHARS - 1} characters")
    body = bytes(8) + struct.pack("<I", 0x12) + raw.ljust(2 * NAME_CHARS, b"\0") + b"\0\x03"
    return holder(PLAYER_INFO, body)


def battle_ready(ready=False, started=False):
    """16 bytes, zero until ready; a retail host's ready sets byte 8 to 1, and byte 12 once it has
    sent BattleStart."""
    body = bytearray(16)
    body[8] = 1 if ready else 0
    body[12] = 1 if started else 0
    return holder(BATTLE_READY, bytes(body))


def select_pokemon(pk8):
    """8 zero bytes and the chosen Pokemon in its encrypted party form."""
    pk8 = bytes(pk8)
    if len(pk8) != 0x158:
        raise ValueError(f"{len(pk8)} bytes is not a party PK8 (0x158)")
    return holder(SELECT_POKEMON, bytes(8) + pk8)


def parse(payload):
    """-> (field number, data) for an id-2000 payload, or None."""
    if len(payload) < 4 or struct.unpack_from("<I", payload, 0)[0] != NESTHOLE:
        return None
    b = payload[4:]
    which = b[0] >> 3
    i, n, s = 1, 0, 0
    while True:
        c = b[i]; i += 1
        n |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            break
    inner = b[i:i + n]
    j, m, s = 1, 0, 0
    while True:
        c = inner[j]; j += 1
        m |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            break
    return which, inner[j:j + m]

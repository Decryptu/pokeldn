"""Pia system advertisement header (docs/ldn.md)."""

PIA_HDR = 0x5C

# Pia 6.16-6.41 system header (docs/ldn.md), values from a real FRLG beacon. The console's Pia layer
# rejects a zero-filled header.
PIA_SYS_COMM_VERSION = 22
PIA_APP_COMM_VERSION = 88
PIA_NAME_UTF8, PIA_NAME_UTF16 = 1, 2


def _encode_pia_name(nickname, encoding):
    if encoding == PIA_NAME_UTF16:
        return (nickname or "").encode("utf-16-be")
    return (nickname or "").encode("utf-8")


def build_pia_header(*, sys_comm_ver=PIA_SYS_COMM_VERSION, app_comm_ver=PIA_APP_COMM_VERSION,
                     user_password=b"", player_limit_enabled=True, num_players=1, nickname="EMU",
                     name_encoding=PIA_NAME_UTF8):
    """92-byte big-endian Pia system header; the game's application data follows at 0x5C."""
    name = _encode_pia_name(nickname, name_encoding)[:64]
    h = bytearray(PIA_HDR)
    h[0x00:0x02] = PIA_HDR.to_bytes(2, "big")
    h[0x02] = sys_comm_ver & 0xFF
    h[0x03:0x05] = (app_comm_ver & 0xFFFF).to_bytes(2, "big")
    h[0x05:0x15] = bytes(user_password)[:16].ljust(16, b"\x00")
    h[0x15] = 1 if player_limit_enabled else 0
    h[0x16] = num_players & 0xFF
    h[0x17:0x1B] = len(name).to_bytes(4, "big")
    h[0x1B] = name_encoding & 0xFF
    h[0x1C:0x1C + len(name)] = name
    return bytes(h)


def decode_pia_header(header):
    h = bytes(header)[:PIA_HDR].ljust(PIA_HDR, b"\x00")
    name_size = int.from_bytes(h[0x17:0x1B], "big")
    enc = h[0x1B]
    raw_name = h[0x1C:0x1C + min(name_size, 64)]
    try:
        name = raw_name.decode("utf-16-be" if enc == PIA_NAME_UTF16 else "utf-8", "replace")
    except Exception:
        name = raw_name.hex()
    return {
        "size": int.from_bytes(h[0x00:0x02], "big"),
        "sys_comm_ver": h[0x02],
        "app_comm_ver": int.from_bytes(h[0x03:0x05], "big"),
        "user_password": h[0x05:0x15].hex(),
        "player_limit_enabled": h[0x15],
        "num_players": h[0x16],
        "name_size": name_size,
        "name_encoding": enc,
        "nickname": name,
    }

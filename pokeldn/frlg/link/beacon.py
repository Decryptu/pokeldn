"""FRLG advertisement application data: the 0x5C Pia system header (docs/ldn.md), then a custom
base85 of the 24-byte RFU record (LE): [0:2] trainer id, [2:10] name (0xFF-padded), [10:12] RFU
session id, [12:20] partnerInfo, [20:24] game data.
"""

from pokeldn.frlg.text import charmap

PIA_HDR = 0x5C
RECORD_SIZE = 24

RFU_SERIAL_GAME = 0x0002
# Colosseum Single Battle searches with LINK_GROUP_SINGLE_BATTLE, which accepts this activity alone
# [sAcceptedActivityIds_SingleBattle, src/data/union_room.h:398].
ACTIVITY_BATTLE_SINGLE = 1
ACTIVITY_TRADE = 4
ACTIVITY_SEARCH = 12
ACTIVITY_WONDER_CARD = 21
ACTIVITY_WONDER_NEWS = 22
# Union Room search activities: docs/frlg_link.md, Getting listed.
IN_UNION_ROOM = 1 << 6
LANGUAGE_ENGLISH = 2
VERSION_FIRE_RED = 4

# The search word at record[16:18] (docs/frlg_gift.md).
SEARCH_WORD_OFFSET = 16
SEARCH_ACTIVITY_MASK = 0x007F
SEARCH_UNKNOWN_BIT7 = 0x0080
SEARCH_VERSION_MASK = 0x0700
SEARCH_VERSION_SHIFT = 8
SEARCH_LANGUAGE_MASK = 0x3800
SEARCH_LANGUAGE_SHIFT = 11
SEARCH_HAS_CARD = 0x4000
SEARCH_STARTED_ACTIVITY = 1 << 15

# Trading-board fields (docs/frlg_link.md, The trading board); bits 0-1 of byte 18 are unknown and
# kept.
TRADE_BOARD_TYPE_OFFSET = 18
TRADE_BOARD_LEVEL_OFFSET = 19
TRADE_BOARD_SPECIES_OFFSET = 22
# include/constants/pokemon.h; 9 is TYPE_MYSTERY, unused for a request.
TYPE_NAMES = {
    "normal": 0, "fighting": 1, "flying": 2, "poison": 3, "ground": 4, "rock": 5, "bug": 6,
    "ghost": 7, "steel": 8, "fire": 10, "water": 11, "grass": 12, "electric": 13, "psychic": 14,
    "ice": 15, "dragon": 16, "dark": 17,
}


def set_trade_board(record, species, level, wanted_type):
    """Register (species, level) on the trading board, asking for wanted_type in return."""
    rec = bytearray(record)
    if not 0 <= species < 1024 or not 0 <= level < 128 or not 0 <= wanted_type < 64:
        raise ValueError("trade board fields out of range")
    rec[TRADE_BOARD_SPECIES_OFFSET:TRADE_BOARD_SPECIES_OFFSET + 2] = species.to_bytes(2, "little")
    rec[TRADE_BOARD_LEVEL_OFFSET] = (rec[TRADE_BOARD_LEVEL_OFFSET] & 0x01) | ((level & 0x7F) << 1)
    rec[TRADE_BOARD_TYPE_OFFSET] = (rec[TRADE_BOARD_TYPE_OFFSET] & 0x03) | ((wanted_type & 0x3F) << 2)
    return bytes(rec)


from pokeldn.ldn.beacon import (PIA_HDR, PIA_SYS_COMM_VERSION, PIA_APP_COMM_VERSION,
                                PIA_NAME_UTF8, PIA_NAME_UTF16, build_pia_header, decode_pia_header)


def _b85_char(digit):
    """Digit 0..84 -> alphabet byte 0x23.., skipping 0x5C."""
    c = 0x23 + (digit % 85)
    return c + 1 if c >= 0x5C else c


def b85_encode(data):
    """4-byte LE groups -> 5 base85 chars each, low digit first."""
    data = bytes(data)
    if len(data) % 4:
        data = data.ljust(len(data) + (4 - len(data) % 4), b"\x00")
    out = bytearray()
    for i in range(0, len(data), 4):
        v = int.from_bytes(data[i:i + 4], "little")
        for _ in range(5):
            out.append(_b85_char(v % 85))
            v //= 85
    return bytes(out)


def encode_name(name, width=8, *, language=None):
    return charmap.encode(name or "", width=width, pad=0xFF, language=language)


def mutate_beacon(captured_app_data, *, name=None, trainer_id=None, rfu_session_id=None, language=None):
    """Clone a captured host's application data, Pia header verbatim, re-encoding only the
    overridden record fields."""
    captured = bytes(captured_app_data)
    header = captured[:PIA_HDR]
    rec = bytearray(b85_decode(captured[PIA_HDR:])[:RECORD_SIZE].ljust(RECORD_SIZE, b"\x00"))
    if trainer_id is not None:
        rec[0:2] = (trainer_id & 0xFFFF).to_bytes(2, "little")
    if name is not None:
        rec[2:10] = encode_name(name, width=8, language=language)
    if rfu_session_id is not None:
        rec[10:12] = (rfu_session_id & 0xFFFF).to_bytes(2, "little")
    return header + b85_encode(bytes(rec))

_PIA_HDR = 0x5C  # Pia 6.16-6.41 LDN system header length


def b85_decode(s):
    """Custom base85: alphabet 0x23..0x78 skipping 0x5c, low digit first, 4-byte LE groups."""
    out = bytearray()
    for i in range(0, len(s) - len(s) % 5, 5):
        v = 0
        for c in reversed(s[i:i + 5]):
            v = v * 85 + ((c - 0x23) if c < 0x5C else (c - 0x24))
        out += (v & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def decode_name(b, *, language=None):
    if language == 1:
        return charmap.decode(b, language=language).rstrip()
    out = []
    for x in b:
        if x == 0xFF:
            break
        if 0xBB <= x <= 0xD4:
            out.append(chr(ord("A") + x - 0xBB))
        elif 0xD5 <= x <= 0xEE:
            out.append(chr(ord("a") + x - 0xD5))
        elif 0xA1 <= x <= 0xAA:
            out.append(chr(ord("0") + x - 0xA1))
        else:
            out.append(" " if x == 0 else "?")
    return "".join(out).rstrip()


def diagnose(app_data, log):
    """Diagnostics only; the connect id is not taken from the beacon."""
    if not app_data:
        log("[live] beacon: NO application_data on the advertisement")
        return None
    app_data = bytes(app_data)
    log(f"[live] beacon application_data ({len(app_data)} B): {app_data.hex()}")
    if len(app_data) >= _PIA_HDR:
        gba = app_data[_PIA_HDR:]
        log(f"[live] beacon RFU payload (after the 0x5C Pia header, {len(gba)} B): {gba.hex()}")
        try:
            d = b85_decode(gba)
            if len(d) >= 24:
                log(f"[live] beacon decoded: host name={decode_name(d[2:10], language=(int.from_bytes(d[16:18], "little") >> 11) & 7)!r} "
                    f"TID=0x{int.from_bytes(d[0:2], 'little'):04x} "
                    f"RFU-session-id=0x{int.from_bytes(d[10:12], 'little'):04x} "
                    f"tradeSpecies={int.from_bytes(d[20:24], 'little') >> 16}")
                # The only pre-join view of the host's game state; logged at INFO since the verbose
                # sink is unusable live.
                word = int.from_bytes(d[16:18], "little")
                info = getattr(log, "info", log)
                info(f"host beacon game state: activity={word & 0x007F} "
                     f"started_activity={bool(word & (1 << 15))} "
                     f"has_card={bool(word & 0x4000)} word=0x{word:04x}")
        except Exception as e:
            log(f"[live] beacon decode skipped ({type(e).__name__}: {e})")
    return app_data

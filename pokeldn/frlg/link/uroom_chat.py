"""Union Room chat blocks [src/union_room_chat.c]; layout in docs/frlg_link.md."""

from pokeldn.frlg.text import charmap

BLOCK_SIZE = 0x28
NAME_FIELD = 8              # PLAYER_NAME_LENGTH + 1 [include/constants/global.h:64]
PAYLOAD_OFF = 1 + NAME_FIELD
# 2 * MESSAGE_BUFFER_NCHAR + 1: 15 entries of up to two bytes plus the terminator.
TEXT_FIELD = BLOCK_SIZE - PAYLOAD_OFF

# The console types at most 15 entries [union_room_chat.c:21,1112] and its receive path never checks
# [union_room_chat.c:1308]: entries 16+ draw off the screen (docs/frlg_link.md).
MESSAGE_NCHAR = 15
EXTRA_SYMBOL = 0xF9         # CHAR_EXTRA_SYMBOL [include/characters.h:176], two-byte entry prefix

NULL = 0
CHAT = 1
JOIN = 2
LEAVE = 3
DROP = 4
DISBAND = 5

NAMES = {NULL: "NULL", CHAT: "CHAT", JOIN: "JOIN", LEAVE: "LEAVE", DROP: "DROP", DISBAND: "DISBAND"}


def entry_count(encoded):
    """Entries, counting a 0xF9 pair as one [src/string_util.c:560]."""
    n = i = 0
    while i < len(encoded) and encoded[i] != charmap.EOS:
        i += 2 if encoded[i] == EXTRA_SYMBOL else 1
        n += 1
    return n


def check_text(text):
    """Raise unless `text` survives the Gen-3 charmap and fits the console's 15-entry chat line."""
    if not text:
        raise ValueError("a chat message must not be empty")
    encoded = charmap.encode(text)
    if entry_count(encoded) > MESSAGE_NCHAR:
        raise ValueError(f"chat message {text!r} is longer than {MESSAGE_NCHAR} characters; the "
                         "console's own keyboard stops there and its chat line does not wrap")
    if charmap.decode(charmap.encode(text, width=TEXT_FIELD)) != text:
        raise ValueError(f"chat message {text!r} has characters outside the Gen-3 charmap")
    return text


def build(cmd, name, *, multiplayer_id=0, text=""):
    """One 0x28-byte chat block, padded with EOS."""
    if cmd not in NAMES:
        raise ValueError(f"unknown chat command {cmd!r}")
    if cmd == CHAT:
        check_text(text)
    out = bytearray([charmap.EOS]) * BLOCK_SIZE
    out[0] = cmd
    out[1:1 + NAME_FIELD] = charmap.encode(name, width=NAME_FIELD)
    if cmd == CHAT:
        out[PAYLOAD_OFF:PAYLOAD_OFF + TEXT_FIELD] = charmap.encode(text, width=TEXT_FIELD)
    else:
        out[PAYLOAD_OFF] = multiplayer_id & 0xFF
    return bytes(out)


def parse(data):
    """-> {cmd, name, multiplayer_id, text}; for CHAT, multiplayer_id is the text's first byte."""
    if len(data) < BLOCK_SIZE:
        raise ValueError(f"chat block is {len(data)} bytes, expected {BLOCK_SIZE}")
    cmd = data[0]
    return {
        "cmd": cmd,
        "name": charmap.decode(data[1:1 + NAME_FIELD]),
        "multiplayer_id": data[PAYLOAD_OFF] if cmd != CHAT else None,
        "text": charmap.decode(data[PAYLOAD_OFF:BLOCK_SIZE]) if cmd == CHAT else "",
    }


def describe(msg):
    kind = NAMES.get(msg["cmd"], f"0x{msg['cmd']:02x}")
    if msg["cmd"] == CHAT:
        return f"{msg['name']}: {msg['text']}"
    return f"[{kind}] {msg['name']}"

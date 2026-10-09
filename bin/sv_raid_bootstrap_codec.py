#!/usr/bin/env python3
"""Decode, edit, and re-encode SV's LZ4-compressed 0x012f raid bootstrap."""

import ctypes
import ctypes.util
from dataclasses import dataclass
import struct

from pokeldn import gen9
from pokeldn.ldn import reliable5
from pokeldn.sv import streams
from pokeldn.sv.raid_generation import MAX_REWARD_ROWS


OUTER_PREFIX = bytes.fromhex("8033")
MESSAGE_TYPE = 0x012F
MESSAGE_HEADER_OFFSET = 2
MESSAGE_HEADER_SIZE = 16
LZ4_OFFSET = MESSAGE_HEADER_OFFSET + MESSAGE_HEADER_SIZE
RAW_SIZE_OFFSET = MESSAGE_HEADER_OFFSET + 8
EXPECTED_RAW_SIZE = 0xAA0
PARTICIPANT_COUNT = 4
RAIDPOINT_OFFSET = gen9.SIZE_PARTY * 5
RAIDPOINT_SIZE = 0x3E8
RAIDPOINT_REWARD_OFFSET = 0x0E0
RAIDPOINT_SUMMARY_OFFSET = 0x3B8
LOBBY_POKEMON_PREFIX = bytes.fromhex("80332e01")
LOBBY_POKEMON_HEADER_SIZE = 18
LOBBY_POKEMON_SIZE_OFFSET = 10

STANDARD_CONTENT_KIND = 2


@dataclass(frozen=True)
class RewardEntry:
    item_id: int
    quantity: int


def parse_reward(value):
    """Parse one CLI ITEM_ID:QUANTITY reward row."""
    try:
        item_text, quantity_text = value.split(":", 1)
        item_id, quantity = int(item_text, 0), int(quantity_text, 0)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("reward must be ITEM_ID:QUANTITY") from exc
    entry = normalize_rewards([(item_id, quantity)])[0]
    return entry.item_id, entry.quantity


def normalize_rewards(rows):
    """Validate an ordered exact reward list for a generated RaidPoint."""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("rewards must be a non-empty list")
    if len(rows) > MAX_REWARD_ROWS:
        raise ValueError(f"a RaidPoint supports at most {MAX_REWARD_ROWS} reward rows")
    rewards = []
    for index, row in enumerate(rows):
        if isinstance(row, RewardEntry):
            item_id, quantity = row.item_id, row.quantity
        elif isinstance(row, dict) and set(row) == {"item_id", "quantity"}:
            item_id, quantity = row["item_id"], row["quantity"]
        elif isinstance(row, (list, tuple)) and len(row) == 2:
            item_id, quantity = row
        else:
            raise ValueError(f"reward {index} must contain item_id and quantity")
        if isinstance(item_id, bool) or not isinstance(item_id, int) or not 1 <= item_id <= 0xFFFFFFFF:
            raise ValueError(f"reward {index} item_id must be an integer from 1 to 4294967295")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 999:
            raise ValueError(f"reward {index} quantity must be an integer from 1 to 999")
        rewards.append(RewardEntry(item_id, quantity))
    return tuple(rewards)


def _load_lz4():
    name = ctypes.util.find_library("lz4") or "liblz4.so.1"
    library = ctypes.CDLL(name)
    library.LZ4_decompress_safe.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)
    library.LZ4_decompress_safe.restype = ctypes.c_int
    library.LZ4_compressBound.argtypes = (ctypes.c_int,)
    library.LZ4_compressBound.restype = ctypes.c_int
    library.LZ4_compress_default.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int)
    library.LZ4_compress_default.restype = ctypes.c_int
    return library


_LZ4 = None


def _lz4():
    global _LZ4
    if _LZ4 is None:
        _LZ4 = _load_lz4()
    return _LZ4


def _decompress_block(block, size):
    source = ctypes.create_string_buffer(block, len(block))
    target = ctypes.create_string_buffer(size)
    decoded = _lz4().LZ4_decompress_safe(source, target, len(block), size)
    if decoded != size:
        raise ValueError(f"invalid raid bootstrap LZ4 block: decoded {decoded}, expected {size}")
    return target.raw[:decoded]


def _compress_block(raw):
    source = ctypes.create_string_buffer(raw, len(raw))
    capacity = _lz4().LZ4_compressBound(len(raw))
    target = ctypes.create_string_buffer(capacity)
    encoded = _lz4().LZ4_compress_default(source, target, len(raw), capacity)
    if encoded <= 0:
        raise ValueError("raid bootstrap LZ4 compression failed")
    return target.raw[:encoded]


def decode_application(application):
    """Return the fixed plaintext record from a complete 0x012f application message."""
    if len(application) < LZ4_OFFSET or application[:2] != OUTER_PREFIX:
        raise ValueError("not an SV broadcast application message")
    message_type = struct.unpack_from("<H", application, MESSAGE_HEADER_OFFSET)[0]
    if message_type != MESSAGE_TYPE:
        raise ValueError(f"expected message type 0x{MESSAGE_TYPE:04x}, got 0x{message_type:04x}")
    compression = struct.unpack_from("<I", application, MESSAGE_HEADER_OFFSET + 4)[0]
    if compression != 2:
        raise ValueError(f"expected compressed 0x012f message flags 2, got {compression}")
    raw_size = struct.unpack_from("<I", application, RAW_SIZE_OFFSET)[0]
    if raw_size != EXPECTED_RAW_SIZE:
        raise ValueError(f"expected 0x{EXPECTED_RAW_SIZE:x}-byte raid record, got 0x{raw_size:x}")
    return _decompress_block(application[LZ4_OFFSET:], raw_size)


def encode_application(template, raw):
    """Recompress plaintext while preserving the existing message envelope."""
    decode_application(template)  # Validate the envelope and original block first.
    if len(raw) != EXPECTED_RAW_SIZE:
        raise ValueError(f"raid record must remain 0x{EXPECTED_RAW_SIZE:x} bytes")
    header = bytearray(template[:LZ4_OFFSET])
    struct.pack_into("<I", header, RAW_SIZE_OFFSET, len(raw))
    return bytes(header) + _compress_block(raw)


def build_application(raw, *, message_value=0, header_tail=b"\0\0\0\0"):
    """Build a complete compressed 0x012F application.

    ``message_value`` is the opaque 16-bit field at application offset 4.
    ``header_tail`` is the opaque four-byte field at offset 0x0e. Ordinary
    retail captures use zero for both tail words; callers can supply live
    session values once their semantics are known.
    """
    raw = bytes(raw)
    if len(raw) != EXPECTED_RAW_SIZE:
        raise ValueError(f"raid record must be 0x{EXPECTED_RAW_SIZE:x} bytes")
    if not 0 <= message_value <= 0xFFFF:
        raise ValueError("message_value must fit in an unsigned 16-bit field")
    header_tail = bytes(header_tail)
    if len(header_tail) != 4:
        raise ValueError("header_tail must contain exactly four bytes")
    header = OUTER_PREFIX + struct.pack(
        "<HHII4s", MESSAGE_TYPE, message_value, 2, len(raw), header_tail)
    if len(header) != LZ4_OFFSET:
        raise AssertionError("0x012F application envelope has the wrong size")
    return header + _compress_block(raw)


def _raidpoint_name(value):
    try:
        encoded = value.encode("ascii")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise ValueError("RaidPoint name must be an ASCII string") from exc
    if not encoded.startswith(b"RaidPoint_"):
        raise ValueError("RaidPoint name must start with 'RaidPoint_'")
    if len(encoded) > 23:
        raise ValueError("RaidPoint name must fit in the 24-byte inline string")
    return encoded


def build_raid_point(raid, *, point_name="RaidPoint_POKELDN_0", exact_rewards=None):
    """Build the understood portion of a standard `0x3E8` RaidPoint.

    Encounter-specific boss/shield/action parameters come from the bundled
    retail raid tables. Unknown padding and player-specific Raid Power bonus rows are zeroed.
    Reward rows use the retail-tested neutral marker zero. Four-star captures
    place marker 5 after one definition slot and three bonus slots; lower-star
    captures do not establish that marker as a universal terminator.
    """
    try:
        encounter = raid["encounter"]
        profile = raid["profile"]
        metadata = raid["metadata"]
        rewards = raid["rewards"]
        stars = metadata["stars"]
    except (KeyError, TypeError) as exc:
        raise ValueError("raid must be a generate_seed_raid result") from exc
    if encounter.get("content") not in ("standard", "black"):
        raise ValueError("generated RaidPoint supports standard and black raids")
    boss_desc = encounter.get("boss_desc")
    if not isinstance(boss_desc, (list, tuple)) or len(boss_desc) != 37:
        raise ValueError("raid encounter is missing its 37-word boss_desc profile")
    if any(isinstance(value, bool) or not isinstance(value, int)
           or not 0 <= value <= 0xFFFFFFFF for value in boss_desc):
        raise ValueError("raid encounter boss_desc words must be unsigned 32-bit integers")
    hp_multiplier, *actions = boss_desc

    out = bytearray(RAIDPOINT_SIZE)
    name = _raidpoint_name(point_name)
    out[:len(name)] = name
    out[0x18] = 0x40
    struct.pack_into("<IIII", out, 0x20, stars, 0, 1, profile["level"])
    struct.pack_into("<I", out, 0x4C, hp_multiplier)
    struct.pack_into(f"<{len(actions)}I", out, 0x50, *actions)

    if exact_rewards is not None:
        exact_rewards = normalize_rewards(exact_rewards)
        rewards = tuple(
            {"item": entry.item_id, "amount": entry.quantity}
            for entry in exact_rewards)

    # A neutral generated list is deliberately independent of subject/source
    # marker aliases and of the host's meal-based Raid Power bonuses. Retail
    # accepts exact marker-0 lists and awards their requested quantities.
    # Seed-derived four-star lists retain the observed marker-5 metadata row.
    # Exact lists deliberately omit it and zero every unused row.
    trailing_rows = 5 if stars == 4 and exact_rewards is None else 0
    if len(rewards) + trailing_rows > MAX_REWARD_ROWS:
        raise ValueError(
            f"raid has {len(rewards)} rewards; RaidPoint profile supports at most "
            f"{MAX_REWARD_ROWS - trailing_rows}")
    for index, reward in enumerate(rewards):
        struct.pack_into(
            "<IIII", out, RAIDPOINT_REWARD_OFFSET + index * 16,
            0, reward["item"], reward["amount"], 0)
    if stars == 4 and exact_rewards is None:
        struct.pack_into(
            "<IIII", out, RAIDPOINT_REWARD_OFFSET + (len(rewards) + 4) * 16,
            5, 0, 0, 0)

    struct.pack_into(
        "<IIIIIII", out, RAIDPOINT_SUMMARY_OFFSET,
        stars, profile["species"], profile["form"], profile["gender"],
        profile["level"], 0, metadata["tera_type"])
    struct.pack_into("<I", out, 0x3E0, STANDARD_CONTENT_KIND)
    return bytes(out)


def _empty_party_pk9():
    """Return the exact species-zero placeholder retail uses for open raid slots."""
    # This static value is identical across retail bootstraps. It is not an
    # all-zero party record: the game gives its placeholder the nickname "Egg", level 1, neutral
    # Tera sentinel 19, and the minimum level-1 HP/stat block. An all-zero record survives the
    # wire codec but crashes later when the battle participant array is initialized.
    plain = bytearray(gen9.SIZE_PARTY)
    plain[gen9.OFF_NICKNAME:gen9.OFF_NICKNAME + 8] = (
        "Egg".encode("utf-16le") + b"\0\0")
    struct.pack_into("<H", plain, gen9.OFF_CURRENT_HP, 11)
    plain[gen9.OFF_TERA_TYPE_ORIGINAL] = 19
    plain[gen9.OFF_TERA_TYPE_OVERRIDE] = 19
    plain[gen9.OFF_LANGUAGE] = 2
    plain[gen9.OFF_LEVEL] = 1
    struct.pack_into("<6H", plain, gen9.OFF_STATS, 11, 5, 5, 5, 5, 5)
    return gen9.encrypt(bytes(plain))


def extract_lobby_pokemon(application):
    """Return the sealed party PK9 carried by a raid `0x80332e` lobby message."""
    application = bytes(application)
    declared = (struct.unpack_from("<I", application, LOBBY_POKEMON_SIZE_OFFSET)[0]
                if len(application) >= LOBBY_POKEMON_SIZE_OFFSET + 4 else None)
    if (len(application) != LOBBY_POKEMON_HEADER_SIZE + gen9.SIZE_PARTY
            or application[:4] != LOBBY_POKEMON_PREFIX
            or declared != gen9.SIZE_PARTY):
        raise ValueError("not a complete raid 0x80332e party-PK9 lobby message")
    return _party_pk9(application[LOBBY_POKEMON_HEADER_SIZE:])


def build_raid_boss_pk9(profile):
    """Build the complete encrypted party PK9 used for a generated raid boss."""
    from pokeldn.sv.raid_generation import RAID_BOSS_COMMON

    fields = dict(RAID_BOSS_COMMON)
    fields.update(profile)
    # gen9.write applies mappings in insertion order. Nickname sets the flag,
    # so apply the explicit raid-boss is_nicknamed=0 override afterward.
    is_nicknamed = fields.pop("is_nicknamed")
    fields["is_nicknamed"] = is_nicknamed
    return gen9.encrypt(gen9.write(bytes(gen9.SIZE_PARTY), **fields))


def build_seed_bootstrap_raw(seed, *, version="violet", progress="4star",
                             map_name="paldea", content="standard",
                             point_name="RaidPoint_POKELDN_0", players=(),
                             exact_rewards=None):
    """Generate a complete `0xAA0` bootstrap plaintext from seed and context.

    Up to four encrypted or plaintext party PK9s may be supplied. Missing
    participant slots become canonical species-zero records. The fifth slot is
    the complete seed-generated raid boss.
    """
    from pokeldn.sv import raid_generation

    players = tuple(players)
    if len(players) > PARTICIPANT_COUNT:
        raise ValueError(f"a raid bootstrap has at most {PARTICIPANT_COUNT} participants")
    participant_records = [_party_pk9(player) for player in players]
    participant_records.extend(
        _empty_party_pk9() for _ in range(PARTICIPANT_COUNT - len(participant_records)))
    raid = raid_generation.generate_seed_raid(
        seed, version=version, progress=progress, map_name=map_name, content=content)
    boss = build_raid_boss_pk9(raid["profile"])
    raidpoint = build_raid_point(
        raid, point_name=point_name, exact_rewards=exact_rewards)
    raw = b"".join(participant_records) + boss + raidpoint
    if len(raw) != EXPECTED_RAW_SIZE:
        raise AssertionError("generated raid bootstrap has the wrong size")
    return raw


def _bootstrap_parts(events):
    parts = {}
    for delay, sequence, flags, lowest, payload in events:
        if sequence in (11, 12):
            plain = streams.decompress(payload) if flags & reliable5.FLAG_ZLIB else bytes(payload)
            parts[sequence] = plain
    if set(parts) != {11, 12}:
        raise ValueError("raid bootstrap requires generated sequences 11 and 12")
    return parts


def _replace_bootstrap_application(events, application, changed):
    """Replace generated fragments 11/12 while preserving their outer flags."""
    parts = _bootstrap_parts(events)
    original_first_length = len(parts[11])
    if application != parts[11] + parts[12]:
        raise ValueError("bootstrap application changed while preparing replacement")
    if len(changed) < 2:
        raise ValueError("recompressed bootstrap is too short for its two reliable fragments")
    # Keep RaidStage's sequence-11 boundary when possible. A repeated or especially compressible player
    # PK9 can make the LZ4 application shorter than sequence 11 used to be; retain both reliable
    # sequence ids by moving the boundary instead of rejecting an otherwise valid bootstrap.
    first_length = min(original_first_length, len(changed) - 1)
    replacements = {11: changed[:first_length], 12: changed[first_length:]}
    output = []
    for delay, sequence, flags, lowest, payload in events:
        if sequence in replacements:
            plain = replacements[sequence]
            payload = streams.compress(plain) if flags & reliable5.FLAG_ZLIB else plain
        output.append((delay, sequence, flags, lowest, payload))
    return output, len(parts[12]), len(replacements[12])


def patch_bootstrap_participant(events, slot, raw):
    """Replace one of the four live participant PK9s in generated sequences 11/12."""
    if not 0 <= slot < PARTICIPANT_COUNT:
        raise ValueError(f"raid participant slot must be 0..{PARTICIPANT_COUNT - 1}")
    parts = _bootstrap_parts(events)
    application = parts[11] + parts[12]
    bootstrap = bytearray(decode_application(application))
    offset = slot * gen9.SIZE_PARTY
    bootstrap[offset:offset + gen9.SIZE_PARTY] = _party_pk9(raw)
    changed = encode_application(application, bytes(bootstrap))
    output, _, _ = _replace_bootstrap_application(events, application, changed)
    return output


def _party_pk9(raw):
    raw = bytes(raw)
    if len(raw) != gen9.SIZE_PARTY:
        raise ValueError(
            f"a raid player Pokemon must be a {gen9.SIZE_PARTY}-byte party PK9, "
            f"not {len(raw)} bytes")
    return gen9.encrypt(gen9.load(raw))

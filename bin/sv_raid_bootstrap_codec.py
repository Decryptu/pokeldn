#!/usr/bin/env python3
"""Decode, edit, and re-encode SV's LZ4-compressed 0x012f raid bootstrap."""

import ctypes
import ctypes.util
from dataclasses import dataclass
import json
from pathlib import Path
import struct

from pokeldn import gen9
from pokeldn.ldn import reliable5
from pokeldn.sv import streams


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
AVALUGG_RAIDPOINT_OFFSET = 0x6B8
AVALUGG_RAIDPOINT = b"RaidPoint_13_1_1"
LOBBY_POKEMON_PREFIX = bytes.fromhex("80332e01")
LOBBY_POKEMON_HEADER_SIZE = 18
LOBBY_POKEMON_SIZE_OFFSET = 10
REWARD_PROFILE_FORMAT = "pokeldn.sv.raid-rewards.v1"
REWARD_PROFILE_TEMPLATE = "violet-4.0.0-c72e1d7f-avalugg"

# Complete linked reward set from Violet seed C72E1D7F. Sixteen rows are
# visible to the guest in our capture; 0x7f8, 0x8a8, and 0x8d8 are hidden or
# conditional rows which must be changed with their visible counterparts.
# Source-4 rows 0x8b8/0x8c8 are independent bonuses and are not part of the
# definition/reference set changed by the proven compressed-stream edit.
AVALUGG_VISIBLE_REWARD_RECORDS = (
    (0x798, 0, 1127, 1),
    (0x7A8, 0, 1128, 1),
    (0x7B8, 0, 2064, 5),
    (0x7C8, 0, 567, 3),
    (0x7D8, 0, 2064, 3),
    (0x7E8, 2, 1862, 2),
    (0x808, 1, 2064, 2),
    (0x818, 0, 171, 3),
    (0x828, 0, 171, 3),
    (0x838, 0, 171, 3),
    (0x848, 0, 1235, 1),
    (0x858, 0, 171, 3),
    (0x868, 0, 171, 3),
    (0x878, 0, 171, 3),
    (0x888, 0, 171, 3),
    (0x898, 0, 171, 3),
)

AVALUGG_LINKED_HIDDEN_RECORDS = (
    (0x7F8, 0, 1862, 2),
    (0x8A8, 0, 567, 2),
    (0x8D8, 4, 1862, 10),
)

AVALUGG_REWARD_RECORDS = tuple(sorted(
    AVALUGG_VISIBLE_REWARD_RECORDS + AVALUGG_LINKED_HIDDEN_RECORDS))

# Independent source-4 bonus slots. They are not linked to the 19-record
# definition set, but must be cleared when constructing an exact custom list.
AVALUGG_BONUS_RECORDS = (
    (0x8B8, 4, 89, 1),   # Big Pearl
    (0x8C8, 4, 92, 1),   # Nugget; observed on the retail single-entry test
)

STANDARD_CONTENT_KIND = 2


@dataclass(frozen=True)
class RewardEntry:
    item_id: int
    quantity: int


@dataclass(frozen=True)
class RewardProfile:
    rewards: tuple
    name: str = ""
    format: str = REWARD_PROFILE_FORMAT
    template: str = REWARD_PROFILE_TEMPLATE
    mode: str = "exact"


def parse_reward_profile(value):
    """Validate and normalize a version-1 exact reward profile mapping."""
    if not isinstance(value, dict):
        raise ValueError("reward profile must be a JSON object")
    allowed = {"format", "template", "mode", "name", "rewards"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown reward profile field(s): {', '.join(unknown)}")
    if value.get("format") != REWARD_PROFILE_FORMAT:
        raise ValueError(f"reward profile format must be {REWARD_PROFILE_FORMAT!r}")
    if value.get("template") != REWARD_PROFILE_TEMPLATE:
        raise ValueError(f"reward profile template must be {REWARD_PROFILE_TEMPLATE!r}")
    if value.get("mode") != "exact":
        raise ValueError("reward profile mode must be 'exact'")
    name = value.get("name", "")
    if not isinstance(name, str):
        raise ValueError("reward profile name must be a string")
    rows = value.get("rewards")
    if not isinstance(rows, list) or not rows:
        raise ValueError("reward profile rewards must be a non-empty array")
    if len(rows) > len(AVALUGG_VISIBLE_REWARD_RECORDS):
        raise ValueError(
            f"reward profile supports at most {len(AVALUGG_VISIBLE_REWARD_RECORDS)} entries")
    rewards = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"item_id", "quantity"}:
            raise ValueError(
                f"reward {index} must contain exactly item_id and quantity")
        item_id, quantity = row["item_id"], row["quantity"]
        if isinstance(item_id, bool) or not isinstance(item_id, int) or not 1 <= item_id <= 0xFFFFFFFF:
            raise ValueError(f"reward {index} item_id must be an integer from 1 to 4294967295")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 999:
            raise ValueError(f"reward {index} quantity must be an integer from 1 to 999")
        rewards.append(RewardEntry(item_id, quantity))
    return RewardProfile(tuple(rewards), name=name)


def load_reward_profile(path):
    """Load a versioned reward profile from disk."""
    profile_path = Path(path)
    try:
        value = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load reward profile {profile_path}: {exc}") from exc
    return parse_reward_profile(value)


def extract_retail_bootstrap(path):
    """Extract the complete host 0x012F application from a retail JSONL capture."""
    rows = []
    try:
        with Path(path).open(encoding="utf-8") as capture:
            for line_number, line in enumerate(capture, 1):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid JSON in {path} at line {line_number}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read donor capture {path}: {exc}") from exc
    accepts = [
        row["t"] for row in rows
        if (row.get("rec") == "data" and row.get("protocol") == 0x80
            and row.get("port") == 2 and row.get("seq") == 1
            and str(row.get("src", "")).endswith(".1")
            and bytes.fromhex(row.get("payload", "00"))[:1] == b"\x09")
    ]
    if not accepts:
        raise ValueError("donor capture lacks the retail host type-9 accept")
    packets = {}
    for row in rows:
        if (row.get("rec") != "data" or row.get("protocol") != 0x80
                or row.get("port") != 0 or not str(row.get("src", "")).endswith(".1")
                or row["t"] < min(accepts)):
            continue
        flags = row.get("reliable_flags", row.get("flags", 0))
        payload = bytes.fromhex(row["payload"])
        plain = streams.decompress(payload) if flags & reliable5.FLAG_ZLIB else payload
        old = packets.setdefault(row["seq"], (flags, plain))
        if old != (flags, plain):
            raise ValueError("donor capture has conflicting reliable fragments")
    starts = [
        sequence for sequence, (flags, plain) in packets.items()
        if flags & reliable5.FLAG_MESSAGE_START and plain.startswith(OUTER_PREFIX)
        and len(plain) >= 4 and struct.unpack_from("<H", plain, 2)[0] == MESSAGE_TYPE
    ]
    if len(starts) != 1:
        raise ValueError("donor capture must contain exactly one 0x012F message start")
    parts = []
    for sequence in range(starts[0], max(packets) + 1):
        if sequence not in packets:
            raise ValueError("donor bootstrap has a reliable fragment gap")
        flags, plain = packets[sequence]
        parts.append(plain)
        if flags & reliable5.FLAG_MESSAGE_END:
            application = b"".join(parts)
            decode_application(application)
            return application
    raise ValueError("donor bootstrap lacks a reliable message end")


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
    """Recompress plaintext while preserving the captured message envelope."""
    decode_application(template)  # Validate the envelope and original block first.
    if len(raw) != EXPECTED_RAW_SIZE:
        raise ValueError(f"raid record must remain 0x{EXPECTED_RAW_SIZE:x} bytes")
    header = bytearray(template[:LZ4_OFFSET])
    struct.pack_into("<I", header, RAW_SIZE_OFFSET, len(raw))
    return bytes(header) + _compress_block(raw)


def build_application(raw, *, message_value=0, header_tail=b"\0\0\0\0"):
    """Build a complete compressed 0x012F application without a donor envelope.

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


def build_raid_point(raid, *, point_name="RaidPoint_POKELDN_0", reward_profile=None):
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
        raise ValueError("donor-free RaidPoint supports standard and black raids")
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

    if reward_profile is not None:
        if not isinstance(reward_profile, RewardProfile):
            reward_profile = parse_reward_profile(reward_profile)
        rewards = tuple(
            {"item": entry.item_id, "amount": entry.quantity}
            for entry in reward_profile.rewards)

    # A neutral generated list is deliberately independent of subject/source
    # marker aliases and of the host's meal-based Raid Power bonuses. Marker-0
    # exact lists have already been accepted by retail in the donor-backed path.
    max_rows = (RAIDPOINT_SUMMARY_OFFSET - RAIDPOINT_REWARD_OFFSET) // 16
    # Seed-derived four-star lists retain the observed marker-5 metadata row.
    # Exact lists deliberately omit it: retail accepted the donor-backed exact
    # representation with every row after the requested marker-0 entries zeroed.
    trailing_rows = 5 if stars == 4 and reward_profile is None else 0
    if len(rewards) + trailing_rows > max_rows:
        raise ValueError(
            f"raid has {len(rewards)} rewards; RaidPoint profile supports at most "
            f"{max_rows - trailing_rows}")
    for index, reward in enumerate(rewards):
        struct.pack_into(
            "<IIII", out, RAIDPOINT_REWARD_OFFSET + index * 16,
            0, reward["item"], reward["amount"], 0)
    if stars == 4 and reward_profile is None:
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
    # This static value is identical in the Growlithe and Avalugg bootstraps. It is not an
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
    # Import lazily: raid_seed imports transport helpers that also use this
    # codec in command-line workflows.
    from pokeldn.sv.raid_seed import RAID_BOSS_COMMON

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
                             reward_profile=None):
    """Generate a donor-free `0xAA0` bootstrap plaintext from seed and context.

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
        raid, point_name=point_name, reward_profile=reward_profile)
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
        raise ValueError("plaintext reward editing requires replay sequences 11 and 12")
    return parts


def _validate_avalugg_rewards(raw):
    if raw[AVALUGG_RAIDPOINT_OFFSET:
           AVALUGG_RAIDPOINT_OFFSET + len(AVALUGG_RAIDPOINT)] != AVALUGG_RAIDPOINT:
        raise ValueError("plaintext reward editing requires the C72E1D7F Avalugg RaidPoint")
    for offset, expected_source, expected_item, expected_quantity in AVALUGG_REWARD_RECORDS:
        source, item, quantity, reserved = struct.unpack_from("<IIII", raw, offset)
        observed = (source, item, quantity, reserved)
        expected = (expected_source, expected_item, expected_quantity, 0)
        if observed != expected:
            raise ValueError(
                f"unexpected reward record at raw+0x{offset:x}: {observed}, expected {expected}")
    for offset, expected_source, expected_item, expected_quantity in AVALUGG_BONUS_RECORDS:
        observed = struct.unpack_from("<IIII", raw, offset)
        expected = (expected_source, expected_item, expected_quantity, 0)
        if observed != expected:
            raise ValueError(
                f"unexpected bonus record at raw+0x{offset:x}: {observed}, expected {expected}")


def inspect_avalugg_rewards(raw):
    """Return all known donor reward slots as JSON-ready dictionaries."""
    _validate_avalugg_rewards(raw)
    visible_offsets = {record[0] for record in AVALUGG_VISIBLE_REWARD_RECORDS}
    linked_offsets = {record[0] for record in AVALUGG_REWARD_RECORDS}
    output = []
    for offset, *_ in sorted(AVALUGG_REWARD_RECORDS + AVALUGG_BONUS_RECORDS):
        source, item_id, quantity, reserved = struct.unpack_from("<IIII", raw, offset)
        output.append({
            "offset": f"0x{offset:03X}",
            "kind": ("visible" if offset in visible_offsets else
                     "linked_hidden" if offset in linked_offsets else "bonus"),
            "source": source,
            "item_id": item_id,
            "quantity": quantity,
            "reserved": reserved,
        })
    return output


def encode_reward_profile_application(template_application, profile):
    """Apply an exact v1 reward profile to a validated donor application."""
    if not isinstance(profile, RewardProfile):
        profile = parse_reward_profile(profile)
    raw = bytearray(decode_application(template_application))
    _validate_avalugg_rewards(raw)
    for offset, *_ in AVALUGG_REWARD_RECORDS + AVALUGG_BONUS_RECORDS:
        raw[offset:offset + 16] = b"\0" * 16
    for entry, record in zip(profile.rewards, AVALUGG_VISIBLE_REWARD_RECORDS):
        offset = record[0]
        struct.pack_into("<IIII", raw, offset, 0, entry.item_id, entry.quantity, 0)
    return encode_application(template_application, bytes(raw))


def _replace_bootstrap_application(events, application, changed):
    """Replace replay fragments 11/12 while preserving their outer flags."""
    parts = _bootstrap_parts(events)
    original_first_length = len(parts[11])
    if application != parts[11] + parts[12]:
        raise ValueError("bootstrap application changed while preparing replacement")
    if len(changed) < 2:
        raise ValueError("recompressed bootstrap is too short for its two reliable fragments")
    # Keep the capture's boundary when possible. A repeated or especially compressible player
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


def replace_bootstrap_raw(events, raw):
    """Replace replay sequences 11/12 with a generated `0xAA0` plaintext.

    The live replay's 18-byte application envelope is retained because its two
    opaque fields may be session/message state. No RaidPoint, reward, boss, or
    participant bytes are retained from the old compressed plaintext.
    """
    parts = _bootstrap_parts(events)
    application = parts[11] + parts[12]
    changed = encode_application(application, bytes(raw))
    output, _, _ = _replace_bootstrap_application(events, application, changed)
    return output


def patch_bootstrap_participant(events, slot, raw):
    """Replace one of the four live participant PK9s in replay sequences 11/12."""
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


def patch_host_lobby_pokemon(events, raw):
    """Replace the host's PK9 in its 0x80332e lobby announcement."""
    sealed = _party_pk9(raw)
    output = list(events)
    matches = []
    for index, (delay, sequence, flags, lowest, payload) in enumerate(output):
        plain = streams.decompress(payload) if flags & reliable5.FLAG_ZLIB else bytes(payload)
        if plain[:4] == LOBBY_POKEMON_PREFIX:
            matches.append((index, delay, sequence, flags, lowest, plain))
    if len(matches) != 1:
        raise ValueError(f"raid host replay needs one Pokemon lobby record, found {len(matches)}")
    index, delay, sequence, flags, lowest, plain = matches[0]
    declared = struct.unpack_from("<I", plain, LOBBY_POKEMON_SIZE_OFFSET)[0]
    if (len(plain) != LOBBY_POKEMON_HEADER_SIZE + gen9.SIZE_PARTY
            or declared != gen9.SIZE_PARTY):
        raise ValueError(
            f"unrecognized raid host Pokemon lobby record: {len(plain)} bytes, "
            f"declared size {declared}")
    changed = plain[:LOBBY_POKEMON_HEADER_SIZE] + sealed
    payload = streams.compress(changed) if flags & reliable5.FLAG_ZLIB else changed
    output[index] = (delay, sequence, flags, lowest, payload)
    return output


def patch_bootstrap_host_pokemon(events, raw):
    """Replace player subobject 0 in the final 0x80332f raid bootstrap."""
    sealed = _party_pk9(raw)
    parts = _bootstrap_parts(events)
    application = parts[11] + parts[12]
    record = bytearray(decode_application(application))
    record[:gen9.SIZE_PARTY] = sealed
    changed = encode_application(application, bytes(record))
    output, _, _ = _replace_bootstrap_application(events, application, changed)
    return output


def patch_host_player_pokemon(events, raw):
    """Put the same host-player PK9 in the lobby and battle bootstrap."""
    return patch_bootstrap_host_pokemon(patch_host_lobby_pokemon(events, raw), raw)


def patch_avalugg_reward_profile(events, profile):
    """Apply a productized exact-list reward profile to replay events."""
    if not isinstance(profile, RewardProfile):
        profile = load_reward_profile(profile) if isinstance(profile, (str, Path)) else parse_reward_profile(profile)
    parts = _bootstrap_parts(events)
    application = parts[11] + parts[12]
    changed = encode_reward_profile_application(application, profile)
    output, old_seq12, new_seq12 = _replace_bootstrap_application(
        events, application, changed)
    label = f" {profile.name!r}" if profile.name else ""
    print(f"[sv] REWARD PROFILE{label}: {len(profile.rewards)} exact reward(s); "
          f"bootstrap {len(application)} -> {len(changed)} bytes; "
          f"seq12 {old_seq12} -> {new_seq12} bytes")
    for index, entry in enumerate(profile.rewards):
        print(f"[sv]   reward[{index}] item={entry.item_id} quantity={entry.quantity}")
    return output

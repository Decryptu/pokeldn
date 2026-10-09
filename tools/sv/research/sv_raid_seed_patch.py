"""Small, capture-backed helpers for locating and changing a Gen-9 raid boss record.

This is deliberately separate from raid generation.  A Scarlet/Violet raid seed is recoverable
from the boss PK9's first RNG result (its encryption constant), but changing only that value does
not yet regenerate every seed-dependent property of the encounter.
"""

import struct

from pokeldn import gen9
from pokeldn.ldn import reliable5
from pokeldn.sv import streams
from pokeldn.sv.raid_generation import RAID_BOSS_COMMON


XOROSHIRO_CONST_LOW = 0x229D6A5B

# First end-to-end generated raid used to distinguish a real seed substitution from a replay.
# Field ordering follows PK9 (HP, Atk, Def, Spe, SpA, SpD), not RaidCalc's speed-last display.
GENERATED_PROFILES = {
    0x000F34C3: {
        "species": 624,                 # Pawniard
        "nickname": "Pawniard",
        "level": 20,
        "met_level": 20,
        "experience": 8000,
        "encryption_constant": 0x22AC9F1E,
        "trainer_id": 0x8D3C,          # fake trainer id 0x13608D3C
        "secret_id": 0x1360,
        "pid": 0x36DDA01D,
        "ability": 128,                # Defiant
        "ability_number": 1,
        "gender": 0,                   # male
        "nature": 20,                  # Calm
        "stat_nature": 20,
        "ivs": (31, 31, 31, 31, 31, 31),
        "height_scalar": 222,
        "weight_scalar": 64,
        "scale": 125,
        "tera_type_original": 8,       # Steel
        "tera_type_override": 19,
        "moves": (210, 232, 184, 372),
        "move_pp": (20, 35, 10, 10),
        "move_pp_ups": (0, 0, 0, 0),
        "current_hp": 54,
        "stats": (54, 40, 39, 35, 27, 29),
        "ot_friendship": 35,
    },
}

GENERATED_METADATA = {
    0x000F34C3: {"species": 624, "stars": 2, "tera_type": 8,
                 "encounter_identifier": 2037},
}

def encryption_constant(seed):
    """Return the first xoroshiro128+ output used as a Gen-9 raid PK9's EC."""
    return ((seed & 0xFFFFFFFF) + XOROSHIRO_CONST_LOW) & 0xFFFFFFFF


def seed_from_encryption_constant(ec):
    """Reverse the ordinary 32-bit raid seed -> encryption constant operation.

    PKHeX documents one colliding EC whose second possible seed must be distinguished by PID.
    It is rejected here until the caller supplies that disambiguation.
    """
    if ec == 0xF8572EBE:
        raise ValueError("raid EC 0xf8572ebe is ambiguous without checking the PID")
    return (ec - XOROSHIRO_CONST_LOW) & 0xFFFFFFFF


def _decoded_payload(flags, payload):
    if flags & reliable5.FLAG_ZLIB:
        return streams.decompress(payload)
    return bytes(payload)


def find_pk9s(events):
    """Find valid party PK9 records in replay event payloads.

    Returns ``(offset, plain)`` pairs in a virtual stream made by concatenating each event after
    applying its per-message zlib flag.  This catches records split across reliable messages, as
    the retail raid boss is in the current capture.
    """
    decoded = [_decoded_payload(flags, payload) for _, _, flags, _, payload in events]
    blob = b"".join(decoded)
    found = []
    for offset in range(len(blob) - gen9.SIZE_PARTY + 1):
        # Sanity is plaintext in the PK9 header and zero for a normal record.  This avoids doing
        # the relatively expensive decrypt/checksum attempt at every byte.
        if blob[offset + gen9.OFF_SANITY:offset + gen9.OFF_SANITY + 2] != b"\0\0":
            continue
        try:
            plain = gen9.decrypt(blob[offset:offset + gen9.SIZE_PARTY])
        except ValueError:
            continue
        species = struct.unpack_from("<H", plain, gen9.OFF_SPECIES)[0]
        if species:
            found.append((offset, plain))
    return found


def _decoded_parts(events):
    return [_decoded_payload(flags, payload) for _, _, flags, _, payload in events]


def _event_location(events, sizes, stream_offset):
    cursor = 0
    for (_, sequence, _, _, _), size in zip(events, sizes):
        if cursor <= stream_offset < cursor + size:
            return sequence, stream_offset - cursor
        cursor += size
    raise ValueError(f"stream offset {stream_offset} is outside the replay")


def _runtime_boss_actions(blob, source_move):
    """Locate the boss action slot in each known 0x7b/0x1327 runtime record.

    The initial 20,626-byte state and its following 250-byte state summary use different fixed
    prefixes, but both contain a nine-byte boss action ``01 move:u32 000000 02``.  Restricting the
    match to those two structural slots avoids treating an equal integer inside the variable battle
    log as another move field.
    """
    header = bytes.fromhex("7b001327")
    layouts = {0x5080: 67, 0x00E8: 75}  # declared body size -> move-id offset in the record
    found = []
    search = 0
    while True:
        record = blob.find(header, search)
        if record < 0:
            break
        search = record + 1
        if record + 18 > len(blob):
            continue
        body_size = struct.unpack_from("<I", blob, record + 14)[0]
        move_local = layouts.get(body_size)
        if move_local is None or record + 18 + body_size > len(blob):
            continue
        move = record + move_local
        if (blob[move - 1:move] == b"\x01"
                and blob[move + 4:move + 7] == b"\0\0\0"
                and blob[move + 7:move + 8] == b"\x02"
                and struct.unpack_from("<I", blob, move)[0] == source_move):
            found.append((move, body_size))
    return found


def audit_boss_fields(events, source_seed):
    """Identify every capture field directly tied to the selected raid boss.

    This deliberately reports semantic fields, not coincidental equal integers in the opaque battle
    log.  The two available retail battles establish three representations: the complete encrypted
    PK9, the compact lobby descriptor, and the boss action slots in runtime state records.
    """
    decoded = _decoded_parts(events)
    sizes = [len(part) for part in decoded]
    blob = b"".join(decoded)
    wanted_ec = encryption_constant(source_seed)
    matches = [(offset, plain) for offset, plain in find_pk9s(events)
               if struct.unpack_from("<I", plain, gen9.OFF_ENCRYPTION_CONSTANT)[0] == wanted_ec]
    if len(matches) != 1:
        raise ValueError(f"expected one PK9 for source seed {source_seed:08X}, found {len(matches)}")
    pk9_offset, plain = matches[0]
    source = gen9.read(plain)

    descriptor_header = bytes.fromhex("80332c01")
    descriptors = []
    search = 0
    while True:
        descriptor = blob.find(descriptor_header, search)
        if descriptor < 0:
            break
        search = descriptor + 1
        if (descriptor + 62 <= len(blob)
                and struct.unpack_from("<H", blob, descriptor + 22)[0] == source["species"]):
            descriptors.append(descriptor)
    if len(descriptors) != 1:
        raise ValueError(f"expected one lobby descriptor for species {source['species']}, "
                         f"found {len(descriptors)}")

    action_sets = [(move, _runtime_boss_actions(blob, move))
                   for move in dict.fromkeys(source["moves"]) if move]
    action_sets = [(move, found) for move, found in action_sets if found]
    actions = [entry for _, found in action_sets for entry in found]
    if not actions:
        raise ValueError(f"found no structured runtime action for source moves {source['moves']}")
    runtime_moves = {move for move, found in action_sets if found}
    if len(runtime_moves) != 1:
        raise ValueError(f"found multiple source moves in structured runtime actions: "
                         f"{sorted(runtime_moves)}")
    return {
        "source": source,
        "runtime_move": runtime_moves.pop(),
        "pk9": (pk9_offset, _event_location(events, sizes, pk9_offset)),
        "descriptor": (descriptors[0], _event_location(events, sizes, descriptors[0])),
        "runtime_actions": [
            (offset, body_size, _event_location(events, sizes, offset))
            for offset, body_size in actions
        ],
    }


def describe_audit(audit):
    """Return short user-facing lines for a boss-field audit."""
    source = audit["source"]
    pk9_sequence, pk9_local = audit["pk9"][1]
    descriptor_sequence, descriptor_local = audit["descriptor"][1]
    action_text = ", ".join(
        f"seq {sequence}+0x{local:x} (body 0x{body_size:x})"
        for _, body_size, (sequence, local) in audit["runtime_actions"])
    return [
        (f"PK9: seq {pk9_sequence}+0x{pk9_local:x}, complete 344-byte boss record "
         f"({source['nickname']}, EC {source['encryption_constant']:08X})"),
        (f"lobby: seq {descriptor_sequence}+0x{descriptor_local:x}, species/stars/Tera/"
         f"encounter identifier"),
        f"runtime boss action: {action_text}; move {audit['runtime_move']}",
    ]


def patch_boss(events, source_seed, target_seed, lobby_patch="full", *, target_profile=None,
               target_metadata=None, clear_runtime_commands=False, runtime_move_index=0,
               runtime_template_events=None, runtime_template_seed=None):
    """Replace the boss PK9 in replay events and return a new event list.

    ``source_seed`` selects the boss unambiguously from other valid PK9 records in the opening.
    A different target requires a complete generated profile; changing the EC alone would create
    an internally inconsistent encounter.
    """
    if (source_seed & 0xFFFFFFFF) == (target_seed & 0xFFFFFFFF):
        # Preserve the retail compressor's exact bytes for the validation/no-op case.
        return list(events)

    # Complete discovery happens before the first write.  This prevents a partial substitution if a
    # future capture moves or omits one of the required runtime representations.
    audit = audit_boss_fields(events, source_seed)
    decoded = _decoded_parts(events)
    sizes = [len(part) for part in decoded]
    original = b"".join(decoded)
    blob = bytearray(original)
    offset = audit["pk9"][0]
    if target_profile is None or target_metadata is None:
        try:
            profile = GENERATED_PROFILES[target_seed & 0xFFFFFFFF]
            metadata = GENERATED_METADATA[target_seed & 0xFFFFFFFF]
        except KeyError as exc:
            raise ValueError(f"no complete generated profile for target seed {target_seed:08X}") from exc
    else:
        profile = target_profile
        metadata = target_metadata
    if profile["encryption_constant"] != encryption_constant(target_seed):
        raise ValueError(f"generated profile for {target_seed:08X} has the wrong EC")
    replacement_fields = dict(RAID_BOSS_COMMON)
    replacement_fields.update(profile)
    replacement = gen9.write(bytes(gen9.SIZE_PARTY), **replacement_fields)
    replacement_encrypted = gen9.encrypt(replacement)
    mutations = [(offset, offset + gen9.SIZE_PARTY, replacement_encrypted, "complete boss PK9")]

    # The opening 0x80332c01 record is the lobby's compact raid descriptor.  Retail captures of
    # different raids establish these offsets: species u16 at +22, stars u32 at +34, and Tera
    # type u32 at +38, and encounter-table identifier u32 at +46.  It is separate from the
    # encrypted boss PK9 used when battle begins.
    descriptor = audit["descriptor"][0]
    descriptor_bytes = bytearray(original[descriptor:descriptor + 62])
    if lobby_patch in ("species", "full"):
        struct.pack_into("<H", descriptor_bytes, 22, metadata["species"])
        struct.pack_into("<I", descriptor_bytes, 46, metadata["encounter_identifier"])
    if lobby_patch == "full":
        struct.pack_into("<I", descriptor_bytes, 34, metadata["stars"])
        struct.pack_into("<I", descriptor_bytes, 38, metadata["tera_type"])
    elif lobby_patch != "none" and lobby_patch != "species":
        raise ValueError(f"unknown lobby patch mode {lobby_patch!r}")
    if lobby_patch != "none":
        mutations.append((descriptor, descriptor + 62, bytes(descriptor_bytes),
                          "complete lobby descriptor"))

    # A controlled retail capture can supply the complete opening runtime records while the base
    # replay continues to supply transport timing, lobby state, and the boss PK9.  Copy records by
    # their declared body size; the subsequent target-action mutation deliberately overlays the
    # template boss's selected move.  The controlled Forretress capture uses the same host, guest,
    # and host move as the Growlithe reference, so its remaining differences are boss-runtime data.
    if runtime_template_events is not None:
        if runtime_template_seed is None:
            raise ValueError("a runtime template trace requires its source raid seed")
        template_audit = audit_boss_fields(runtime_template_events, runtime_template_seed)
        template_blob = b"".join(_decoded_parts(runtime_template_events))
        source_by_size = {}
        template_by_size = {}
        for move_offset, body_size, _ in audit["runtime_actions"]:
            source_by_size.setdefault(body_size, []).append(move_offset)
        for move_offset, body_size, _ in template_audit["runtime_actions"]:
            template_by_size.setdefault(body_size, []).append(move_offset)
        # A longer controlled capture can contain later summaries with the same selected boss
        # move.  The opening 0x5080 action identifies our template phase; select the first 0xe8
        # summary after it, matching the base replay's one-record-per-size opening layout.
        if 0x5080 in template_by_size:
            template_by_size[0x5080] = [min(template_by_size[0x5080])]
        if 0x00E8 in template_by_size and 0x5080 in template_by_size:
            after_big = [offset for offset in template_by_size[0x00E8]
                         if offset > template_by_size[0x5080][0]]
            if after_big:
                template_by_size[0x00E8] = [min(after_big)]
        if source_by_size.keys() != template_by_size.keys() or any(
                len(source_by_size[size]) != len(template_by_size[size])
                for size in source_by_size):
            raise ValueError("runtime template does not have the same opening record layout")
        layouts = {0x5080: 67, 0x00E8: 75}
        for body_size in source_by_size:
            move_local = layouts[body_size]
            record_size = body_size + 18
            for source_move_offset, template_move_offset in zip(
                    source_by_size[body_size], template_by_size[body_size]):
                source_record = source_move_offset - move_local
                template_record = template_move_offset - move_local
                mutations.append((source_record, source_record + record_size,
                                  template_blob[template_record:template_record + record_size],
                                  "controlled runtime template record"))

    # The opening battle-state object queues the boss's selected move in an action slot encoded as
    # ``01 <move:u32> 000000 02``.  Retail Growlithe and Mareep captures put their respective
    # first encounter move at this same position.  Leaving Flame Wheel queued for Pawniard makes
    # the guest reject the battle just before command selection.
    if not 0 <= runtime_move_index < len(profile["moves"]):
        raise ValueError(f"runtime move index {runtime_move_index} is outside the target moveset")
    target_move = profile["moves"][runtime_move_index]
    for move_offset, _, _ in audit["runtime_actions"]:
        mutations.append((move_offset, move_offset + 4, struct.pack("<I", target_move),
                          "runtime boss move"))

    # Each 0x5080 battle-state snapshot contains a length-prefixed, variable command/effect log at
    # record +0x26a.  The victory capture has two such snapshots: the opening state and the state
    # after the boss is defeated.  The latter does not necessarily contain the structured source
    # move used by ``audit_boss_fields``, so discover every complete record by its header rather
    # than clearing only records that happened to match that move.  This lets a generated boss use
    # the captured fixed opening/victory states without executing Growlithe-specific commands.
    if clear_runtime_commands:
        runtime_header = bytes.fromhex("7b001327")
        record = 0
        cleared_records = 0
        while True:
            record = original.find(runtime_header, record)
            if record < 0:
                break
            next_search = record + 1
            if record + 18 > len(original):
                record = next_search
                continue
            body_size = struct.unpack_from("<I", original, record + 14)[0]
            record_end = record + 18 + body_size
            if body_size != 0x5080 or record_end > len(original):
                record = next_search
                continue
            command_length_offset = record + 0x26A
            command_length = struct.unpack_from("<I", original, command_length_offset)[0]
            command_start = command_length_offset + 4
            command_end = command_start + command_length
            if command_end > record_end:
                raise ValueError("runtime command log extends past its record")
            mutations.append((command_length_offset, command_length_offset + 4, bytes(4),
                              "empty runtime command-log length"))
            mutations.append((command_start, command_end, bytes(command_length),
                              "empty runtime command log"))
            cleared_records += 1
            record = record_end
        if not cleared_records:
            raise ValueError("found no complete 0x5080 runtime records to clear")

    # Apply the already-complete mutation plan atomically to the in-memory copy.
    for start, end, value, _ in mutations:
        if end - start != len(value):
            raise AssertionError("raid mutation changed a fixed-size representation")
        blob[start:end] = value
    modified = [(start, end) for start, end, _, _ in mutations]

    out = []
    cursor = 0
    for event, size in zip(events, sizes):
        delay, sequence, flags, lowest, old_payload = event
        part = bytes(blob[cursor:cursor + size])
        intersects = any(cursor < end and cursor + size > start for start, end in modified)
        cursor += size
        if not intersects:
            payload = old_payload
        else:
            payload = streams.compress(part) if flags & reliable5.FLAG_ZLIB else part
        out.append((delay, sequence, flags, lowest, payload))
    # Validate all three semantic representations after re-fragmenting and recompressing them.
    if lobby_patch != "none":
        target_audit = audit_boss_fields(out, target_seed)
        target_fields = target_audit["source"]
        for key, wanted in profile.items():
            if target_fields[key] != wanted:
                raise AssertionError(
                    f"patched PK9 field {key} is {target_fields[key]!r}, wanted {wanted!r}")
        if len(target_audit["runtime_actions"]) != len(audit["runtime_actions"]):
            raise AssertionError("patched replay lost a runtime boss action")
    return out


def patch_boss_encryption_constant(events, source_seed, target_seed):
    """Compatibility name for the seed patcher, now requiring a complete target profile."""
    return patch_boss(events, source_seed, target_seed)

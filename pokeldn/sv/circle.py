"""Scarlet / Violet's Union Circle, the game's team circle, as a guest sees it
(docs/sv_union_circle.md).

Belongs here: the circle's scene and game messages, and a member's side of them: its seat on the
host's field, its BBQ clears and reports, following the host's player and its own wild spawns.
"""

import math
import random
import struct
from dataclasses import dataclass

from pokeldn import gen9
from pokeldn.ldn import channel_table
from pokeldn.sv import lz4, port2, raid, streams, trade, wild

# The scene a console hosting a Union Circle advertises (a Link Trade's is 4, a Tera Raid's 7).
SCENE = 5
# The circle's Lua messages: game messages under this handler key whose kind byte is the Lua message
# id, on 0x80 port 0.
KEY_LUA = 0x0132
START = 100        # the host started the circle
MEMBER = 101       # a member's own state: where it stands and its flags
SYNC = 103         # a sync point: each station sends its id and waits for every member's
CRYSTALS = 106     # a station's Tera Raid crystals; every station waits for every other's
CRYSTAL_SLOTS = 300
NO_CRYSTAL = bytes.fromhex("ffffffff0000")      # an empty six-byte slot
FIELD = 110        # the field a station stands in, sent on every map change
STATION_FLAG = 115 # a per-station value (a raid's "loaded")
# The host's own per-station messages a member sends back as its own, so it stays where the host is.
FOLLOWED = (FIELD, STATION_FLAG)
# The most a message carries unfragmented: a retail console splits longer ones, and left our 1818-byte
# 106 unacknowledged.
FRAGMENT = 1395
# Each console's field objects, on reliable 0x7c port 0 between it and the host. A console declares
# each of its own objects (key, id u16, type u16), asks for each the other declares (key, kind 0, 0,
# id u16), and answers each ask with the object's state: the same header with the state's kind.
KEY_DECLARE = 0x001F
KEY_OBJECT = 0x001E
ASK = 0
# Our objects, in the order a retail member declares them: (type, the kind of its state). A station's
# ids step by 4 from its station index. The types differ between consoles (a host declared its second
# as type 1) but the kinds do not; nobody answers an ask for the type-10 object.
OBJECTS = ((0, 1), (2, 2), (3, 3), (10, None))
# An object's frames on the unreliable protocol 0x68: key 0x011E, kind, 0, the object's id (u16). Its
# reliable messages on 0x80 port 0 (key 0x001E: kind 5 its animation state, 9 to 12 its parameters
# and status) carry the id at the same place.
KEY_FRAME = 0x011E
OBJECT_ID_AT = 4
# Kind 4 is the transform: a rotation quaternion (x, y, z, w) at 6, the position at 22. It is a world
# position unless the object rides another, when it sits exactly at the origin of its parent.
TRANSFORM = 4
ROTATION_AT, POSITION_AT = 6, 22
# Kind 6 sets how an object hangs on others; a 40-byte one (mode 3) attaches it to the object whose
# id is at 34, as the player mounts its ride.
ATTACH = 6
PARENT_AT = 34
FOLLOW_DISTANCE = 5.0  # metres our mirrored objects keep from the host's
NEAR_ORIGIN = 10.0     # metres: a transform this close to the origin rides another object or was
                       # set down (the host's player read (0, 0, -2) as it went into Area Zero)
# In Area Zero the host's console stops sending its player's transforms but still shares the wild
# Pokemon it spawns around its player, 8 to 46 m from it in the captures. With no transform for
# HOST_STALE seconds, the host is placed at the middle of its newest ESTIMATE_SPAWNS spawns of the
# last ESTIMATE_WINDOW seconds (wild.ESTIMATE_ERROR).
HOST_STALE = 2.0
ESTIMATE_SPAWNS = 6
ESTIMATE_WINDOW = 30.0
# A retail console sends its objects' transforms about every 16 ms; we receive the host's with gaps
# (the board drops some), so ours go out on our own clock, the host shown as it stood FRAME_DELAY
# seconds ago, between the two of its frames around that moment.
FRAME_PERIOD = 1 / 60
FRAME_DELAY = 0.3
TRACK_LIFE = 1.0   # seconds after the host's last frame of an object we stop sending ours
# Seconds after which one object's own last place is too old to move on from, as when the player
# steps off its ride: it starts again from wherever we last stood.
STALE_PLACE = 0.5
# Kind 5 on key 0x001E is an object's animation: a u32 count of op bytes at 6, then the ops (01 id
# value sets a flag, 02 id f32 a number, 03 id value a small one, 04 node 01 a state, whose names
# follow the ops). The player's numbers 1 and 2 drive its move blend, 1 its speed (0 standing, 1.5
# running). Ours are the host's scaled by how fast our object moves against the host's, so it
# stands while the host runs within the leash.
ANIMATION = 5
OPS_AT = 6
OP_SIZES = {1: 3, 2: 6, 3: 3, 4: 3}
OP_NUMBER = 2
BLEND = (1, 2)
SPEED = 1
MOVING = 0.3        # m/s under which the host counts as standing: its own numbers stand
PACE_WEIGHT = 0.15  # each frame's share in the speeds we compare
PACE_LIMIT = 1.5    # the most we scale the host's numbers by
SPEED_STEP = 0.1    # the least change in our speed number we send on our own,
SPEED_PERIOD = 0.1  # at most this often
# The BBQ module's own messages: game messages under this key on 0x80 port 0, the kind byte the
# module's message type, the body in the game's tagged format. Type 1 is a player's status record,
# type 2 a player's progress on a quest, type 3 a player's clear.
KEY_BBQ = 0x0048
BBQ_STATUS, BBQ_PROGRESS, BBQ_CLEAR = 1, 2, 3
# A member's progress on one of the host's quests: the host counts it as its own and, once the quest
# is done, clears it itself, crediting the member, and its solo total goes up. The two values a
# quest's progress names (a type, a biome); -1 for none. Our count is the largest goal a Normal
# quest has, so one report finishes any.
NO_VALUE = -1
PROGRESS_COUNT = 500.0
DEMO_ENDED = 2     # the sync point id the start demo's end reaches: the overworld is up
CLEAR_DELAY = 1.0  # seconds a member waits after the start demo's end before its BP clear
CLEAR_QUEST = 29   # the quest a BP clear names: the retail clear's
NORMAL, TEAM = 0, 2     # a clear's grade (1 is Bonus)
# A wild Pokemon a console spawns and shares (docs/sv_union_circle.md, Overworld encounters): key
# 0x0026 kind 1 its 96-byte record, kind 2 its id gone; key 0x0126 kind 3 its id then its state.
# Its id is the pair (station, n) in unsigned integers only, its object id station + 4n, and its
# frames on 0x68 are an object's. A console files another's spawn as unsettled and starts no
# battle with it until a state's last element, its status, says 0: settled. To battle it, a console
# asks its owner alone, on 0x7c port 0, with kind 5 (its id, the asker's id for it) and waits until
# the owner answers with the same pair: kind 7, broadcast on 0x80 port 0, hands it over; kind 6,
# back to the asker, refuses.
KEY_SPAWN, KEY_SPAWN_STATE = 0x0026, 0x0126
SPAWNED, GONE, SPAWN_STATE, ASKED, REFUSED, HANDED = 1, 2, 3, 5, 6, 7
SETTLED = 0
RECORD_SIZE = 0x60
# The record: the object id, then from +4 the bitfields `EncountManager.UpdateNetworkSpawn` copies
# into a `pml.pokepara.InitialSpec` (the accessors at 0x90e344, bound in the Lua module c4CF1D719),
# then the position at +0x30 and a rotation at +0x40. (bit, width) in the u64 at +4:
SPECIES, ITEM, SCALE, SEX = (0, 11), (11, 12), (23, 8), (31, 1)
RARE, FORM, LEVEL, RIBBON, NATURE, TERA = (32, 1), (33, 5), (38, 7), (45, 8), (53, 5), (58, 5)
# The IVs (HP, Attack, Defense, Sp. Atk, Sp. Def, Speed) and ability slot: (offset, bit, width).
IVS = ((12, 8, 5), (12, 13, 5), (12, 18, 5), (16, 0, 5), (16, 5, 5), (12, 23, 5))
ABILITY = (16, 10, 2)
RECORD_UNSET_AT = 0x24      # an s32 a retail record holds at -1
RECORD_POSITION_AT, RECORD_ROTATION_AT = 0x30, 0x40
# Before its record the owner sends the object's frames: kind 6 hanging it on nothing, kind 7 its
# scale; then its transform and state every so often until it is gone.
UNATTACHED = bytes.fromhex("00000000000000000000003f0000003f000000000000003f0000003f")
SCALE_FRAME = 7
SPAWN_STATE_VALUE = 0.001   # the float a retail state opens with, 0.001 to 0.04
SPAWN_DELAY = 10.0          # seconds after the start demo's end before our first spawn
SPAWN_PERIOD = 1.0          # seconds between our spawns while fewer than SPAWN_COPIES are out
SPAWN_REFRESH = 2.0         # seconds between a spawn's transforms and states
SPAWN_FIRST = 0x100         # our first n, clear of our players' objects
SPAWN_COPIES = 3            # our spawns kept out at once
SPAWN_RING = (15.0, 25.0)   # metres from the host's player each comes
SPAWN_CULL = 50.0           # metres: one of ours the host has gone this far from is let go and
                            # spawned again near it
# A clear's quest sits in the third of the player's three quest slots, as the retail clear seen did.
CLEAR_SLOT = 2
# A quest row as a clear carries it: the quest's category (1 Battle, 2 Field, 3 Camera), its id, the
# row's own id, the goal, the BP, the BP to swap the quest out, 0, the grade, the difficulty (0 to 2,
# Beginner to Advanced) and the row's weight in the draw. Ours copy the retail clear's of quest 29.
CLEAR_CATEGORY = 2
# The Team (group) quests a clear can name, as the game draws them: (quest, BP, odds out of 300).
TEAM_QUESTS = ((15, 500, 33), (15, 550, 36), (15, 600, 36), (14, 500, 70), (14, 600, 35),
               (5, 500, 30), (25, 400, 30), (3, 400, 30))
# Snacksworth releases a version's 13 solo-route legendaries at every 10 of the player's solo
# clears and its 12 Team-route ones at every Team clear (docs/sv_union_circle.md, Snacksworth).
SOLO_GOAL, TEAM_GOAL = 130, 12
SNACK_SPACING = 1.0         # seconds between a Snacksworth run's clears and reports
STALL_SENDS = 20            # a Snacksworth run's sends in a row the host's totals ignore before it stops
BP_MAX = 9_999_999          # the most BP a player holds: the host clamps its total to it
# An empty quest row: as a retail clear fills its unused ones.
EMPTY_ROW = (0, 0, 0, 32767, 0, 0, 0, 0, 0, 0.0)
NO_QUEST = (0, 0.0, 0, 0)


class U64(int):
    """A value the tagged format writes at full width, as the game does a station id."""


def encode(value):
    """-> `value` in the game's tagged format: an integer from -64 to 127 as its own byte, a wider one
    behind a signed tag (0x84 to 0x86), a float behind 0x88, bytes behind 0xbc, a tuple behind 0xb9
    and its length."""
    if isinstance(value, U64):
        return port2.encode_u64(value)
    if isinstance(value, float):
        return b"\x88" + struct.pack("<f", value)
    if isinstance(value, bytes):
        return port2.encode_bytes(value)
    if isinstance(value, tuple):
        return (bytes([channel_table.TUPLE]) + channel_table.encode_uint(len(value))
                + b"".join(encode(v) for v in value))
    if -0x40 <= value < 0x80:
        return bytes([value & 0xFF])
    for tag, fmt in ((0x84, "<b"), (0x85, "<h"), (0x86, "<i")):
        try:
            return bytes([tag]) + struct.pack(fmt, value)
        except struct.error:
            continue
    raise ValueError(f"{value} does not fit a 32-bit integer")


def decode(data, pos=0):
    """-> (value, the position after it) of the value at `pos` in the game's tagged format: as
    `encode` writes it, also reading an unsigned integer (0x80 to 0x83) or a signed 64-bit one."""
    tag = data[pos]
    if tag < 0x80 or tag >= 0xC0:
        return (tag if tag < 0x80 else tag - 0x100), pos + 1
    if tag <= 0x83:
        return channel_table.decode_uint(data, pos)
    if tag == channel_table.TUPLE:
        count, pos = channel_table.decode_uint(data, pos + 1)
        values = []
        for _ in range(count):
            value, pos = decode(data, pos)
            values.append(value)
        return tuple(values), pos
    if tag == port2.BYTES:
        size, pos = channel_table.decode_uint(data, pos + 1)
        end = pos + size
    elif 0x84 <= tag <= 0x88:
        end = pos + 1 + (4 if tag == 0x88 else 1 << (tag - 0x84))
    else:
        raise ValueError(f"tag {tag:#04x} at {pos} is not one the circle's messages use")
    if end > len(data):
        raise ValueError(f"the value at {pos} runs past the end")
    if tag == port2.BYTES:
        return bytes(data[pos:end]), end
    if tag == 0x88:
        return struct.unpack_from("<f", data, pos + 1)[0], end
    return int.from_bytes(data[pos + 1:end], "little", signed=True), end


@dataclass(frozen=True)
class QuestSlot:
    """A quest slot of a BBQ status record: the quest's id (0: the slot is empty), its progress, its
    text variant (which type, biome or flavor it names; 0 for a quest without), and its row's own id
    among the rows of that quest id, which says the row's grade and difficulty."""
    quest: int
    progress: float
    variant: int
    row: int


@dataclass(frozen=True)
class BbqStatus:
    """What a player's BBQ status record (docs/sv_union_circle.md, The BBQ status record) says of
    its three quest slots, its solo total and its Team total, the two Snacksworth reads."""
    quests: tuple
    solo: int
    team: int


def status_of(record):
    """-> the BbqStatus of a decoded status record."""
    *_, solo, team = record
    return BbqStatus(tuple(QuestSlot(*slot) for slot in record[1:4]), solo, team)


def bbq_values(payload):
    """-> (type, [the values of its body]) of a BBQ message, or None for any other message."""
    payload = bytes(payload)
    if len(payload) < 3 or int.from_bytes(payload[:2], "little") != KEY_BBQ:
        return None
    values, pos = [], 3
    while pos < len(payload):
        value, pos = decode(payload, pos)
        values.append(value)
    return payload[2], values


def bbq_record(payload):
    """-> the sender's BbqStatus of a BBQ status, progress or clear message, each of which ends with
    its sender's status record, or None for any other message."""
    message = bbq_values(payload)
    if message is None or message[0] not in (BBQ_STATUS, BBQ_PROGRESS, BBQ_CLEAR) or not message[1]:
        return None
    return status_of(message[1][-1])


def progress_message(quest, sequence, *, value=NO_VALUE, count=PROGRESS_COUNT):
    """-> a member's progress of `count` on `quest` (docs/sv_union_circle.md, A member's progress
    on the host's quests), naming `value` (a type, a biome) or none, the sender's message
    `sequence`, then a status record with no quests."""
    record = (1, NO_QUEST, NO_QUEST, NO_QUEST, b"\x01", NO_QUEST, NO_QUEST, 0, 0, 0, 0)
    return (KEY_BBQ.to_bytes(2, "little") + bytes([BBQ_PROGRESS]) + encode(quest) + encode(value)
            + encode(NO_VALUE) + encode(float(count)) + encode(sequence) + encode(record))


def sync_id(payload):
    """-> the id a sync point message (103) carries."""
    return int.from_bytes(raid.payload_of(payload)[16:20], "little")


def team_clear(rng=random):
    """-> a Team clear of a quest drawn from TEAM_QUESTS by its odds: (TEAM, BP, its row)."""
    quest, bp, _ = rng.choices(TEAM_QUESTS, [odds for *_, odds in TEAM_QUESTS])[0]
    return TEAM, bp, (CLEAR_CATEGORY, quest, 0, 1, bp, 10, 0, TEAM, 0, 8.0)


def clear_message(quest, bp, station_id, sequence, *, grade=NORMAL, cleared=1, row=None):
    """-> a player's BBQ clear (docs/sv_union_circle.md, What the host does with a member's clear):
    the clear event of `quest` paying `bp`, from the station `station_id`, the sender's message
    `sequence`, then its status record: its three quest slots, the cleared one in the third, and
    `cleared` clears so far. The event carries the quest's `row` (as a clear carries one), else the
    retail clear's row of quest 29 with our quest and BP."""
    if row is None:
        row = (CLEAR_CATEGORY, quest, 0, 1, bp, 10, 0, 0, 0, 8.0)
    event = (quest, row[2], 0, CLEAR_SLOT, grade, bp, (U64(station_id),), row, 0, 0, (0,), CLEAR_SLOT,
             NO_QUEST, EMPTY_ROW, EMPTY_ROW, 0, EMPTY_ROW, 0)
    record = (1, NO_QUEST, NO_QUEST, (quest, 0.0, 0, 0), b"\x01", NO_QUEST, NO_QUEST,
              cleared, 0, cleared, 0)
    return (KEY_BBQ.to_bytes(2, "little") + bytes([BBQ_CLEAR]) + encode(event) + encode(sequence)
            + encode(record))


def lua_message_id(payload):
    """-> the Lua message id of a circle game message, or None for any other game message."""
    parsed = trade.parse(bytes(payload))
    if parsed is None or parsed[0] != KEY_LUA:
        return None
    return parsed[1]


def message(message_id, counter, payload, *, compressed=False):
    """-> a circle message: the Lua message id under the Lua's key, then the serializer header;
    `compressed` stores the payload LZ4-compressed, as a retail console does its 104 and 106."""
    if compressed:
        return raid.message(KEY_LUA, message_id, 0, counter, lz4.compress(payload),
                            compression=raid.COMPRESSION_LZ4, size=len(payload))
    return raid.message(KEY_LUA, message_id, 0, counter, payload)


def opens_objects(table):
    """-> whether a channel-table update (plain) opens the object keys a station's field uses."""
    return any(int.from_bytes(key[:4], "little") == KEY_DECLARE for key, _ in channel_table.parse(table))


def declare(object_id, object_type):
    return (KEY_DECLARE.to_bytes(2, "little") + object_id.to_bytes(2, "little")
            + object_type.to_bytes(2, "little"))


def ask(object_id):
    return KEY_OBJECT.to_bytes(2, "little") + bytes([ASK, 0]) + object_id.to_bytes(2, "little")


def object_of(payload):
    """-> the object id an object message (key 0x001E or 0x011E) names."""
    return int.from_bytes(payload[OBJECT_ID_AT:OBJECT_ID_AT + 2], "little")


def behind(transform, distance):
    """-> a transform moved `distance` metres back along its own heading (the game's forward is
    (sin yaw, cos yaw) in x and z); one at the origin, its object riding another, as it is."""
    x, y, z = struct.unpack_from("<3f", transform, POSITION_AT)
    if x == y == z == 0:
        return transform
    _, qy, _, qw = struct.unpack_from("<4f", transform, ROTATION_AT)
    yaw = 2 * math.atan2(qy, qw)
    out = bytearray(transform)
    struct.pack_into("<3f", out, POSITION_AT, x - distance * math.sin(yaw), y,
                     z - distance * math.cos(yaw))
    return bytes(out)


def leashed(transform, at, distance):
    """-> a transform at `at` turned to face its own position, while that is within `distance`
    metres (across the ground); further, pulled to `distance` metres from it on the line towards
    `at`, at its height. One at the origin as it is; one right on `at` there with its own
    rotation."""
    x, y, z = struct.unpack_from("<3f", transform, POSITION_AT)
    if x == y == z == 0:
        return transform
    dx, dz = at[0] - x, at[2] - z
    gap = math.hypot(dx, dz)
    out = bytearray(transform)
    if gap < 1e-3:
        struct.pack_into("<3f", out, POSITION_AT, *at)
        return bytes(out)
    if gap <= distance:
        ours = at
    else:
        ours = (x + dx / gap * distance, y, z + dz / gap * distance)
    yaw = math.atan2(x - ours[0], z - ours[2])
    struct.pack_into("<4f", out, ROTATION_AT, 0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2))
    struct.pack_into("<3f", out, POSITION_AT, *ours)
    return bytes(out)


def numbers(payload):
    """-> {(offset, id): value} of an animation message's number ops; None if an op is not one we
    know the size of."""
    if len(payload) < OPS_AT + 4:
        return None
    end = OPS_AT + 4 + int.from_bytes(payload[OPS_AT:OPS_AT + 4], "little")
    at, out = OPS_AT + 4, {}
    while at < end:
        size = OP_SIZES.get(payload[at])
        if size is None or at + size > min(end, len(payload)):
            return None
        if payload[at] == OP_NUMBER:
            out[(at, payload[at + 1])] = struct.unpack_from("<f", payload, at + 2)[0]
        at += size
    return out


def scaled(payload, ratio):
    """-> an animation message with its move blend numbers times `ratio`."""
    found = numbers(payload)
    if not found or ratio == 1.0:
        return payload
    out = bytearray(payload)
    for (at, number), value in found.items():
        if number in BLEND:
            struct.pack_into("<f", out, at + 2, value * ratio)
    return bytes(out)


def speed_message(ours, value):
    """-> an animation message setting only `ours`'s speed number."""
    ops = bytes([OP_NUMBER, SPEED]) + struct.pack("<f", value)
    return (KEY_OBJECT.to_bytes(2, "little") + bytes([ANIMATION, 0]) + ours.to_bytes(2, "little")
            + len(ops).to_bytes(4, "little") + ops)


def facing(yaw):
    """-> the rotation quaternion (x, y, z, w) of a heading `yaw` about the vertical."""
    return 0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2)


def spawn_record(object_id, position, *, species, level, shiny=False, form=0, item=0, scale=128,
                 sex=0, ribbon=0, nature=0, tera=0, ivs=(0,) * 6, ability=0):
    """-> a shared wild Pokemon's 96-byte record."""
    fields = 0
    for (bit, width), value in ((SPECIES, species), (ITEM, item), (SCALE, scale), (SEX, sex),
                                (RARE, int(shiny)), (FORM, form), (LEVEL, level), (RIBBON, ribbon),
                                (NATURE, nature), (TERA, tera)):
        if not 0 <= value < 1 << width:
            raise ValueError(f"{value} does not fit {width} bits")
        fields |= value << bit
    out = bytearray(RECORD_SIZE)
    out[0:2] = object_id.to_bytes(2, "little")
    out[4:12] = fields.to_bytes(8, "little")
    for (at, bit, width), value in zip(IVS + (ABILITY,), tuple(ivs) + (ability,)):
        if not 0 <= value < 1 << width:
            raise ValueError(f"{value} does not fit {width} bits")
        word = int.from_bytes(out[at:at + 4], "little") | value << bit
        out[at:at + 4] = word.to_bytes(4, "little")
    struct.pack_into("<i", out, RECORD_UNSET_AT, -1)
    struct.pack_into("<3f", out, RECORD_POSITION_AT, *position)
    struct.pack_into("<4f", out, RECORD_ROTATION_AT, *facing(0.0))
    return bytes(out)


def spawn_id(station, n):
    """-> a shared wild Pokemon's id as its messages carry it: a pair of unsigned integers, which
    the game reads with no signed tag."""
    return (bytes([channel_table.TUPLE]) + channel_table.encode_uint(2)
            + channel_table.encode_uint(station) + channel_table.encode_uint(n))


def read_spawn_id(data, pos=0):
    """-> ((station, n), next pos) of the spawn id at `pos`."""
    if data[pos:pos + 2] != bytes([channel_table.TUPLE, 2]):
        raise ValueError(f"no spawn id at {pos}")
    station, pos = channel_table.decode_uint(data, pos + 2)
    n, pos = channel_table.decode_uint(data, pos)
    return (station, n), pos


def record_fields(record):
    """-> {name: value} of a record's bitfields, its IVs and ability slot."""
    fields = int.from_bytes(record[4:12], "little")
    out = {name: (fields >> bit) & ((1 << width) - 1) for name, (bit, width) in (
        ("species", SPECIES), ("item", ITEM), ("scale", SCALE), ("sex", SEX), ("shiny", RARE),
        ("form", FORM), ("level", LEVEL), ("ribbon", RIBBON), ("nature", NATURE),
        ("tera", TERA))}
    out["ivs"] = tuple((int.from_bytes(record[at:at + 4], "little") >> bit) & ((1 << width) - 1)
                       for at, bit, width in IVS)
    at, bit, width = ABILITY
    out["ability"] = (int.from_bytes(record[at:at + 4], "little") >> bit) & ((1 << width) - 1)
    out["position"] = struct.unpack_from("<3f", record, RECORD_POSITION_AT)
    return out


def object_frame(object_id, kind, body):
    """-> one of an object's frames on 0x68."""
    return KEY_FRAME.to_bytes(2, "little") + bytes([kind, 0]) + object_id.to_bytes(2, "little") + body


def transform_frame(object_id, position, yaw):
    return object_frame(object_id, TRANSFORM, struct.pack("<4f", *facing(yaw))
                        + struct.pack("<3f", *position) + bytes(4))


class Spawner:
    """Our own wild Pokemon in the host's world: `copies` of `species` at `level` (shiny with
    `shiny`, Tera Type `tera`, and any of form, item, scale, sex, nature, ivs and ability `crafted`
    names), each otherwise its own size, nature, IVs and ability slot (never the hidden one), all
    random as the host's wild ones are. Once
    `start`ed, after SPAWN_DELAY seconds one every SPAWN_PERIOD seconds while fewer are out, at a
    random spot SPAWN_RING metres from the host's player and facing it, at its height. One goes when
    a console battles it, the host's console removes it, or the host's player goes more than
    SPAWN_CULL metres from it, and another comes in its place. While not `active` every one is let
    go and none comes. Each spawn's object frames go out before its record, then its transform and a
    settled state every SPAWN_REFRESH. `update` -> ([(label, payload)] for 0x80 port 0, the label
    None for a routine state, [frame] for 0x68)."""

    def __init__(self, species, level, shiny=False, *, tera=0, copies=SPAWN_COPIES,
                 station=streams.JOINER_INDEX, crafted=None, rng=None):
        self.species, self.level, self.shiny, self.tera = species, level, shiny, tera
        self.crafted = {k: v for k, v in (crafted or {}).items() if v is not None}
        self.copies, self.station = copies, station
        self.active = True
        self.rng = rng or random.Random()
        self.due = None
        self.next_n = SPAWN_FIRST
        self.live = []              # [n, position, yaw, next refresh], oldest first
        self.pending = []           # (time, label, record message, n) not yet sent

    def start(self, now):
        if self.due is None:
            self.due = now + SPAWN_DELAY

    def _record(self, object_id, position):
        rng = self.rng
        fields = {"scale": rng.randrange(256), "nature": rng.randrange(25),
                  "ivs": [rng.randrange(32) for _ in range(6)], "ability": rng.randrange(2),
                  **self.crafted}
        return spawn_record(object_id, position, species=self.species, level=self.level,
                            shiny=self.shiny, tera=self.tera, **fields)

    def _let_go(self, spawn, why=""):
        self.live.remove(spawn)
        n = spawn[0]
        self.pending = [p for p in self.pending if p[3] != n]
        return (f"spawn ({self.station}, {n}) gone{why}",
                KEY_SPAWN.to_bytes(2, "little") + bytes([GONE]) + spawn_id(self.station, n))

    def gone(self, station, n):
        """The host's console removed spawn (station, n): -> whether it was one of ours out."""
        live = [s for s in self.live if s[0] == n] if station == self.station else []
        for spawn in live:
            self.live.remove(spawn)
        return bool(live)

    def update(self, now, host_at):
        messages, frames = [], []
        if not self.active:
            for spawn in list(self.live):
                messages.append(self._let_go(spawn))
            return messages, frames
        if host_at is not None:
            for spawn in [s for s in self.live if math.dist(s[1], host_at) > SPAWN_CULL]:
                messages.append(self._let_go(spawn, f": the host is more than {SPAWN_CULL:g} m away"))
        if (self.due is not None and now >= self.due and host_at is not None
                and len(self.live) < self.copies):
            self.due = max(self.due + SPAWN_PERIOD, now)
            n, self.next_n = self.next_n, self.next_n + 1
            object_id = self.station + 4 * n
            angle = self.rng.uniform(0.0, 2 * math.pi)
            distance = self.rng.uniform(*SPAWN_RING)
            position = (host_at[0] + distance * math.sin(angle), host_at[1],
                        host_at[2] + distance * math.cos(angle))
            yaw = angle + math.pi                   # back towards the host
            record = self._record(object_id, position)
            frames += [object_frame(object_id, ATTACH, UNATTACHED),
                       object_frame(object_id, SCALE_FRAME, struct.pack("<f", 1.0)),
                       transform_frame(object_id, position, yaw)]
            self.pending.append((now, f"spawn ({self.station}, {n}) species {self.species} level "
                                      f"{self.level}{' shiny' if self.shiny else ''}, "
                                      f"{distance:.1f} m from the host",
                                 KEY_SPAWN.to_bytes(2, "little") + bytes([SPAWNED])
                                 + port2.encode_bytes(record), n))
            self.live.append([n, position, yaw, now + SPAWN_REFRESH])
        # A record goes out after its object's frames.
        for when, label, message, _ in [p for p in self.pending if p[0] < now]:
            messages.append((label, message))
        self.pending = [p for p in self.pending if p[0] >= now]
        for spawn in self.live:
            n, position, yaw, refresh = spawn
            if now >= refresh:
                spawn[3] = now + SPAWN_REFRESH
                frames.append(transform_frame(self.station + 4 * n, position, yaw))
                messages.append((None, KEY_SPAWN_STATE.to_bytes(2, "little") + bytes([SPAWN_STATE])
                                 + spawn_id(self.station, n)
                                 + encode((SPAWN_STATE_VALUE, 0.0, 0.0, 0, SETTLED))))
        return messages, frames

    def answer(self, body):
        """-> (label, payload) answering a console's ask for a spawn (kind 5's `body`): one of ours
        live is handed over and is no longer ours to refresh or let go; any other refused. None
        when `body` names no spawn."""
        try:
            (station, n), pos = read_spawn_id(body, 2)
            asker, _ = read_spawn_id(body, pos)
        except (ValueError, IndexError):
            return None
        live = [s for s in self.live if s[0] == n] if station == self.station else []
        if live:
            self.live.remove(live[0])
            return (f"spawn ({station}, {n}) handed over as {asker}",
                    KEY_SPAWN.to_bytes(2, "little") + bytes([HANDED]) + body)
        return (f"spawn ({station}, {n}) refused",
                KEY_SPAWN.to_bytes(2, "little") + bytes([REFUSED]) + body)


def between(track, at):
    """-> the transform `track` ([(time, transform)], oldest first) shows at `at`: the position
    interpolated between the two frames around it, the last one held past the end; None before the
    first. Across a frame at the origin (an object mounting or leaving its ride) the earlier one
    holds."""
    earlier = [n for n, (t, _) in enumerate(track) if t <= at]
    if not earlier:
        return None
    n = earlier[-1]
    (t0, a) = track[n]
    if n + 1 == len(track):
        return a
    (t1, b) = track[n + 1]
    pa = struct.unpack_from("<3f", a, POSITION_AT)
    pb = struct.unpack_from("<3f", b, POSITION_AT)
    if pa == (0, 0, 0) or pb == (0, 0, 0) or t1 <= t0:
        return a
    f = (at - t0) / (t1 - t0)
    out = bytearray(a)
    struct.pack_into("<3f", out, POSITION_AT, *(u + (v - u) * f for u, v in zip(pa, pb)))
    return bytes(out)


class Member:
    """A member's side once the host starts the circle. On 0x80 port 0: our own state for the host's
    start, every sync point the host reaches, reached back, our crystals for the host's, and the
    host's field and station value as ours, so we stand where the host does in a world without
    crystals. On 0x7c port 0, once the host opens the field's keys: our objects declared, the host's
    asked for, and each of the host's asks for ours answered with the state of the host's own object
    of that type under our id, so our player stands as the host's does. With `bp`, CLEAR_DELAY
    seconds after the start demo has ended, a Normal clear of CLEAR_QUEST paying that much, from
    `station_id`. With `snacksworth`, from the start demo's end, every SNACK_SPACING seconds: the
    Team clears the host's Team total lacks for TEAM_GOAL, each of a quest drawn from TEAM_QUESTS by
    `rng`, then progress reports finishing the quests in the host's slots, as its latest status
    record shows them, until its solo total reaches SOLO_GOAL (the host clears each quest itself,
    crediting us), then a Team clear more while its Team total still lacks any; `snacks` is how far
    the host's totals have come. With a `spawner`, our own wild Pokemon once the start demo has
    ended, around where the host stands, each handed to the console that asks to battle it; with a
    `locator` (wild.Locator), only while it has found the host's area from the wild Pokemon the
    host's console shares. `notes` tell what a user follows (a BP clear sent, our spawns out, one
    battled, the host's area found or lost), `details` the rest, in order. With `follow` (metres), our objects copy
    the host's as it moves: each of its frames and object messages comes back under our object in
    the same place in the declarations, a world transform where ours stood while the host's is
    within `follow` metres, else pulled to `follow` metres from it, always facing it (the first
    behind it). The frames go out every FRAME_PERIOD, FRAME_DELAY behind the host's, its animations
    with them, the move blend scaled to our own pace.

    `on_lua` takes the host's messages on 0x80 port 0, inflated; `on_table` each plain channel-table
    update on 0x7c port 1; `on_object` each new message on 0x7c port 0; `on_frame` each of the
    host's messages on 0x68 with the time it came. `tick` -> [(label, flags, payload)] to send on
    0x80 port 0 in order, `objects` -> the same for 0x7c port 0, `frames_due` -> ours due on 0x68,
    `frame_wait` the seconds until the next are."""

    def __init__(self, station=streams.JOINER_INDEX, station_id=0, bp=None, snacksworth=False,
                 follow=None, spawner=None, locator=None, rng=random):
        self.station_id, self.bp = station_id, bp
        self.locator = locator      # a wild.Locator our spawns wait on
        self.notes = []             # what a user follows, in order
        self.details = []           # what else changed, in order
        self.snacksworth, self.rng = snacksworth, rng
        self.host_start = None      # the host's (solo, Team) totals when we first saw them
        self.team_left = 0          # Team clears still to send for the host's first Team total
        self.snack_due = None
        self.host_bbq = None        # the host's latest BbqStatus
        self.next_slot = 0          # the host's slot our next progress report goes to
        self.unmoved = 0            # Snacksworth sends since the host's totals last rose
        self.stalled = False        # the host's totals stopped rising: the run gives up
        self.spawner = spawner
        self.host_at = None         # where the host's player (or its ride) last stood, or its estimate
        self.host_seen = None       # when the host's console last showed where its player stands
        self.wild_seen = []         # (time, position) of the host's own wild spawns, in order
        self.spawn_frames = []      # our spawns' frames due now on 0x68
        self.follow = follow
        self.tracks = {}            # our object -> [(time, the host's transform as ours)]
        self.held = []              # (time, the host's other frames as ours), in order
        self.animations = []        # (time, our object, the host's animation as ours), in order
        self.blends = {}            # our object -> the host's latest move blend {number: value}
        self.speeds_sent = {}       # our object -> (time, the speed number we last sent)
        self.paces = {}             # our object -> (time, host position, ours, host m/s, ours)
        self.ratio = 1.0            # our pace against the host's
        self.next_frame = None
        self.places = {}            # our object (None: any) -> (time, where it stands)
        self.overworld = False      # the start demo has ended
        self.clear_due = None
        self.counter = 0
        self.bbq_sequence = 0
        self.started = False
        self.host_state = None
        self.state_sent = self.crystals_sent = self.sent_any = False
        self.queue = []
        self.ours = {station + 4 * n: entry for n, entry in enumerate(OBJECTS)}
        self.declared = False
        self.host_objects = []      # the ids the host declared, in order
        self.states = {}            # kind -> the host's state of that kind
        self.asked = []             # our ids the host asked for, not yet answered
        self.object_queue = []

    def _flags(self):
        """-> a whole zlib message's flags; the first we send on the stream marks it initialized."""
        first, self.sent_any = not self.sent_any, True
        return raid.FIRST if first else raid.COMPLETE_ZLIB

    def _send(self, message_id, payload, compressed=False):
        self.counter += 1
        plain = message(message_id, self.counter, payload, compressed=compressed)
        if len(plain) > FRAGMENT:
            raise ValueError(f"circle message {message_id} is {len(plain)} bytes, more than one "
                             f"fragment's {FRAGMENT}")
        self.queue.append((f"message {message_id}", self._flags(), streams.compress(plain)))

    def _ours_for(self, host_id):
        """-> our object in the place the host's has in its declarations, or None."""
        if not self.declared or host_id not in self.host_objects:
            return None
        ours = sorted(self.ours)
        place = self.host_objects.index(host_id)
        return ours[place] if place < len(ours) else None

    def _as_ours(self, payload, ours):
        """-> one of the host's object messages under our object, naming our parent if it names one
        of the host's objects as its own."""
        out = bytearray(payload)
        out[OBJECT_ID_AT:OBJECT_ID_AT + 2] = ours.to_bytes(2, "little")
        if (int.from_bytes(payload[:2], "little") == KEY_FRAME and payload[2] == ATTACH
                and len(payload) >= PARENT_AT + 2):
            parent = self._ours_for(int.from_bytes(payload[PARENT_AT:PARENT_AT + 2], "little"))
            if parent is not None:
                out[PARENT_AT:PARENT_AT + 2] = parent.to_bytes(2, "little")
        return bytes(out)

    def on_frame(self, payload, now):
        """Keeps one of the host's frames on 0x68, come at `now`, under our object for
        `frames_due`, where the host stands; nothing else unless following one of the host's
        objects."""
        payload = bytes(payload)
        if (len(payload) < OBJECT_ID_AT + 2
                or int.from_bytes(payload[:2], "little") != KEY_FRAME):
            return
        if (payload[2] == TRANSFORM and len(payload) >= POSITION_AT + 12
                and object_of(payload) in self.host_objects):
            at = struct.unpack_from("<3f", payload, POSITION_AT)
            if math.dist(at, (0, 0, 0)) > NEAR_ORIGIN:        # not riding or set down
                self.host_at, self.host_seen = at, now
                if self.locator is not None:
                    self.locator.source = wild.GAME
                    self.locator.host_moved(at)
        if self.follow is None:
            return
        ours = self._ours_for(object_of(payload))
        if ours is None:
            return
        frame = self._as_ours(payload, ours)
        if frame[2] == TRANSFORM and len(frame) >= POSITION_AT + 12:
            self.tracks.setdefault(ours, []).append((now, frame))
        else:
            self.held.append((now, frame))

    def frame_wait(self, now):
        """-> seconds until our next frames are due, None while we have none to send."""
        if self.spawn_frames:
            return 0.0
        if not self.tracks and not self.held and not self.animations:
            return None
        return 0.0 if self.next_frame is None else max(0.0, self.next_frame - now)

    def frames_due(self, now):
        """-> our frames due on 0x68 at `now`: the host's other frames as they come due, then each
        of our objects whose host frames still come, the host's transform `FRAME_DELAY` ago placed
        by `_place`; our spawns' frames at once."""
        spawned, self.spawn_frames = self.spawn_frames, []
        if self.next_frame is not None and now < self.next_frame:
            return spawned
        if self.next_frame is None or now - self.next_frame > FRAME_PERIOD:
            self.next_frame = now
        self.next_frame += FRAME_PERIOD
        at = now - FRAME_DELAY
        out = [frame for t, frame in self.held if t <= at]
        self.held = [(t, frame) for t, frame in self.held if t > at]
        for ours, track in sorted(self.tracks.items()):
            if now - track[-1][0] > TRACK_LIFE:
                del self.tracks[ours]
                continue
            transform = between(track, at)
            # Keep only the frame in effect at `at` and those after it.
            while len(track) > 1 and track[1][0] <= at:
                track.pop(0)
            if transform is not None:
                placed = self._place(ours, transform, now)
                self._pace(ours, transform, placed, now)
                out.append(placed)
        self._animate(at, now)
        return spawned + out

    def _pace(self, ours, transform, placed, now):
        """Weighs how fast our object moves against the host's, for `_animate`."""
        host = struct.unpack_from("<3f", transform, POSITION_AT)
        mine = struct.unpack_from("<3f", placed, POSITION_AT)
        if host == (0, 0, 0):
            self.paces.pop(ours, None)
            return
        last = self.paces.get(ours)
        if last is None or now <= last[0] or now - last[0] > STALE_PLACE:
            self.paces[ours] = (now, host, mine, 0.0, 0.0)
            return
        dt = now - last[0]
        host_speed = math.dist(host, last[1]) / dt
        our_speed = math.dist(mine, last[2]) / dt
        self.paces[ours] = (now, host, mine,
                            last[3] + (host_speed - last[3]) * PACE_WEIGHT,
                            last[4] + (our_speed - last[4]) * PACE_WEIGHT)

    def _animate(self, at, now):
        """Queues the host's animations come due at `at` as ours, their move blend scaled by our
        pace against the host's; then our own speed where that drifted from what we sent."""
        if self.paces:
            host_speed, our_speed = max((p[3], p[4]) for p in self.paces.values())
            self.ratio = (1.0 if host_speed < MOVING
                          else min(PACE_LIMIT, our_speed / host_speed))
        due = [a for a in self.animations if a[0] <= at]
        self.animations = self.animations[len(due):]
        for _, ours, payload in due:
            found = numbers(payload) or {}
            blend = self.blends.setdefault(ours, {})
            for (_, number), value in found.items():
                if number in BLEND:
                    blend[number] = value
                    if number == SPEED:
                        self.speeds_sent[ours] = (now, value * self.ratio)
            self.queue.append((f"host object kind {ANIMATION} as ours {ours:#06x}", self._flags(),
                               streams.compress(scaled(payload, self.ratio))))
        for ours, blend in self.blends.items():
            if SPEED not in blend or ours not in self.speeds_sent:
                continue
            sent_at, sent = self.speeds_sent[ours]
            want = blend[SPEED] * self.ratio
            if now - sent_at >= SPEED_PERIOD and abs(want - sent) >= SPEED_STEP:
                self.speeds_sent[ours] = (now, want)
                self.queue.append((f"our speed {want:.2f} for {ours:#06x}", self._flags(),
                                   streams.compress(speed_message(ours, want))))

    def _place(self, ours, transform, now):
        """-> the host's world transform as ours: `follow` metres from the host towards where our
        object last stood, facing the host; the first time behind it."""
        if struct.unpack_from("<3f", transform, POSITION_AT) == (0, 0, 0):
            return transform
        last = self.places.get(ours)
        if last is None or now - last[0] > STALE_PLACE:
            last = self.places.get(None)
        transform = (behind(transform, self.follow) if last is None
                     else leashed(transform, last[1], self.follow))
        place = (now, struct.unpack_from("<3f", transform, POSITION_AT))
        self.places[ours] = self.places[None] = place
        return transform

    def on_lua(self, payload, now=0.0, host=True):
        """-> the Lua message id the host's message carries, come at `now`, or None for any other
        message. While following, one of the host's object messages comes back under our object,
        an animation when `frames_due` shows the host's frames of that moment. A BBQ message from
        the `host` updates its quests and totals."""
        payload = bytes(payload)
        if host and len(payload) >= 3 and int.from_bytes(payload[:2], "little") == KEY_SPAWN:
            self._on_host_spawn(payload, now)
            return None
        if len(payload) >= 3 and int.from_bytes(payload[:2], "little") == KEY_BBQ:
            if host:
                self._on_host_bbq(payload)
            return None
        if (self.follow is not None and len(payload) >= OBJECT_ID_AT + 2
                and int.from_bytes(payload[:2], "little") == KEY_OBJECT):
            ours = self._ours_for(object_of(payload))
            if ours is not None and payload[2] == ANIMATION:
                self.animations.append((now, ours, self._as_ours(payload, ours)))
            elif ours is not None:
                self.queue.append((f"host object {object_of(payload):#06x} kind {payload[2]} "
                                   f"as ours {ours:#06x}", self._flags(),
                                   streams.compress(self._as_ours(payload, ours))))
            return None
        message_id = lua_message_id(payload)
        if message_id == START:
            self.started = True
        elif message_id == MEMBER and self.host_state is None:
            self.host_state = raid.payload_of(payload)
        elif message_id == SYNC:
            self._send(SYNC, raid.payload_of(payload))
            if sync_id(payload) == DEMO_ENDED:
                self.overworld = True
        elif message_id == CRYSTALS and not self.crystals_sent:
            self.crystals_sent = True
            self._send(CRYSTALS, NO_CRYSTAL * CRYSTAL_SLOTS, compressed=True)
        elif message_id in FOLLOWED:
            self._send(message_id, raid.payload_of(payload))
        if self.started and self.host_state is not None and not self.state_sent:
            self.state_sent = True
            self._send(MEMBER, self.host_state)
        return message_id

    def _estimate(self, now):
        """While the host's console shows no transform of its player, places the host at the middle
        of its newest spawns; with none of those, where it stands is unknown."""
        if self.host_seen is not None and now - self.host_seen <= HOST_STALE:
            return
        recent = [at for t, at in self.wild_seen if now - t <= ESTIMATE_WINDOW][-ESTIMATE_SPAWNS:]
        if recent:
            at = tuple(sum(axis) / len(recent) for axis in zip(*recent))
            source = wild.SPAWNS
        elif self.host_seen is not None:
            at, source = None, wild.LOST
        else:
            return                  # not in the field yet
        changed = at != self.host_at
        self.host_at = at
        if self.locator is not None:
            self.locator.source = source
            if at is not None and changed:
                self.locator.host_moved(at)

    def _on_host_spawn(self, payload, now):
        """Keeps where a wild Pokemon the host's console spawned at `now` stands, and weighs it for
        the locator; lets go of one of ours it removed."""
        station = self.spawner.station if self.spawner is not None else None
        if payload[2] == SPAWNED and len(payload) >= 3 + RECORD_SIZE:
            record = payload[-RECORD_SIZE:]
            if int.from_bytes(record[:2], "little") % 4 == station:
                return
            fields = record_fields(record)
            self.wild_seen = [s for s in self.wild_seen if now - s[0] <= ESTIMATE_WINDOW]
            self.wild_seen.append((now, fields["position"]))
            self._estimate(now)
            if self.locator is not None:
                self.locator.host_spawn(gen9.national(fields["species"]), fields["form"],
                                        fields["level"], fields["position"])
        elif payload[2] == GONE and self.spawner is not None:
            try:
                (owner, n), _ = read_spawn_id(payload, 3)
            except (ValueError, IndexError):
                return
            if self.spawner.gone(owner, n):
                self.details.append(f"the host removed our spawn ({owner}, {n}); another comes")

    def _on_host_bbq(self, payload):
        try:
            status = bbq_record(payload)
        except (ValueError, IndexError, TypeError):
            return
        if status is not None:
            if self.host_bbq is not None and (status.solo, status.team) != (self.host_bbq.solo,
                                                                          self.host_bbq.team):
                self.unmoved = 0
            self.host_bbq = status
            if self.host_start is None:
                self.host_start = status.solo, status.team
                self.team_left = max(0, TEAM_GOAL - status.team)

    def _send_progress(self):
        """Sends a report finishing the quest in the host's next slot that holds one."""
        if not any(slot.quest for slot in self.host_bbq.quests):
            return
        slots = self.host_bbq.quests
        while not slots[self.next_slot % len(slots)].quest:
            self.next_slot += 1
        index = self.next_slot % len(slots)
        slot, self.next_slot = slots[index], index + 1
        self.bbq_sequence += 1
        value = slot.variant or NO_VALUE
        self.queue.append((f"BBQ progress on the host's quest {slot.quest} (slot {index + 1}, "
                           f"value {value})", self._flags(),
                           streams.compress(progress_message(slot.quest, self.bbq_sequence,
                                                             value=value))))

    def _send_snack(self):
        """Sends the next of a Snacksworth run's clears or reports, as the host's totals stand."""
        if self.team_left:
            self.team_left -= 1
        elif self.host_bbq.solo < SOLO_GOAL:
            self._send_progress()
            return
        self._send_clear(*team_clear(self.rng))

    @property
    def snacks(self):
        """-> (done, total): the host's Team and solo clears since we first saw its totals, of those
        it then lacked for every Snacksworth legendary; None before."""
        if self.host_start is None:
            return None
        solo, team = self.host_start
        solo_needed, team_needed = max(0, SOLO_GOAL - solo), max(0, TEAM_GOAL - team)
        done = (min(solo_needed, max(0, self.host_bbq.solo - solo))
                + min(team_needed, max(0, self.host_bbq.team - team)))
        return done, solo_needed + team_needed

    @property
    def finished(self):
        """-> whether the `bp` clear has gone out and, with `snacksworth`, the host's totals have
        reached SOLO_GOAL and TEAM_GOAL or ignored STALL_SENDS sends in a row."""
        if self.bp is not None:
            return False
        return not self.snacksworth or self.stalled or (self.host_bbq is not None
                                                        and self.host_bbq.solo >= SOLO_GOAL
                                                        and self.host_bbq.team >= TEAM_GOAL)

    def _send_clear(self, grade, bp, row=None):
        quest = row[1] if row else CLEAR_QUEST
        self.bbq_sequence += 1
        self.queue.append((f"BBQ {'Team' if grade == TEAM else 'Normal'} clear of quest {quest}, "
                           f"{bp} BP", self._flags(),
                           streams.compress(clear_message(quest, bp, self.station_id,
                                                          self.bbq_sequence, grade=grade,
                                                          cleared=self.bbq_sequence, row=row))))

    def _send_object(self, label, payload):
        if len(payload) > 8:
            self.object_queue.append((label, raid.COMPLETE_ZLIB, streams.compress(payload)))
        else:
            self.object_queue.append((label, raid.COMPLETE, payload))

    def on_table(self, table):
        if self.declared or not opens_objects(table):
            return
        self.declared = True
        for object_id, (kind, _) in self.ours.items():
            self._send_object(f"declares object {object_id:#06x}, type {kind}",
                              declare(object_id, kind))

    def on_object(self, payload):
        payload = bytes(payload)
        if len(payload) < 6:
            return
        key, object_id = int.from_bytes(payload[:2], "little"), int.from_bytes(payload[2:4], "little")
        if key == KEY_DECLARE:
            if object_id not in self.host_objects:
                self.host_objects.append(object_id)
            self._send_object(f"asks for host object {object_id:#06x}", ask(object_id))
            return
        if key == KEY_SPAWN and payload[2] == ASKED and self.spawner is not None:
            answer = self.spawner.answer(payload[3:])
            if answer is None:
                return
            label, reply = answer
            if reply[2] == HANDED:
                self.notes.append("a console battles one of our spawns; another comes")
                self.queue.append((label, self._flags(), streams.compress(reply)))
            else:
                self._send_object(label, reply)
            return
        if key != KEY_OBJECT:
            return
        object_id = int.from_bytes(payload[4:6], "little")
        if payload[2] == ASK:
            if self.ours.get(object_id, (0, None))[1] and object_id not in self.asked:
                self.asked.append(object_id)
        elif object_id in self.host_objects:
            self.states.setdefault(payload[2], payload)
        for object_id in [i for i in self.asked if self.ours[i][1] in self.states]:
            self.asked.remove(object_id)
            state = self.states[self.ours[object_id][1]]
            self._send_object(f"object {object_id:#06x} state, kind {state[2]}",
                              state[:4] + object_id.to_bytes(2, "little") + state[6:])

    def tick(self, now):
        """-> [(label, flags, payload)] due now on 0x80 port 0."""
        if self.overworld and self.bp is not None and self.clear_due is None:
            self.clear_due = now + CLEAR_DELAY
        if self.bp is not None and self.clear_due is not None and now >= self.clear_due:
            self._send_clear(NORMAL, self.bp)
            self.notes.append(f"sent a clear paying the host {self.bp} BP; it shows once the host's "
                              "player closes the BP side bar")
            self.bp = None
        if self.snacksworth and self.overworld and self.host_start is not None:
            if self.snack_due is None:
                self.snack_due = now
            if now >= self.snack_due and not self.finished:
                self._send_snack()
                self.snack_due += SNACK_SPACING
                self.unmoved += 1
                if self.unmoved >= STALL_SENDS:
                    self.stalled = True
                    bbq = self.host_bbq
                    self.notes.append(
                        f"the host's totals did not rise over {STALL_SENDS} clears and reports; "
                        f"stopping with {max(0, SOLO_GOAL - bbq.solo)} solo and "
                        f"{max(0, TEAM_GOAL - bbq.team)} Team still to go")
        self._estimate(now)
        if self.locator is not None:
            self.spawner.active = self.locator.found
            self.notes += self.locator.notes
            self.details += self.locator.details
            self.locator.notes, self.locator.details = [], []
        if self.spawner is not None and self.overworld:
            self.spawner.start(now)
            out_before = bool(self.spawner.live)
            messages, frames = self.spawner.update(now, self.host_at)
            if self.spawner.live and not out_before:
                self.notes.append("our spawns are coming out around the host's player")
            for label, payload in messages:
                self.queue.append((label, self._flags(), streams.compress(payload)))
            self.spawn_frames += frames
        out, self.queue = self.queue, []
        return out

    def objects(self):
        """-> [(label, flags, payload)] due now on 0x7c port 0."""
        out, self.object_queue = self.object_queue, []
        return out

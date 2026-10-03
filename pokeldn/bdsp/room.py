"""BDSP's own protocol above Pia: encodes and decodes the messages the Union Room is made of.

Framing: data id (1), payload length (2, big-endian), the packed little-endian struct. The ids and
structs are `pokeldn.bdsp.netdata`, generated from opendpr (docs/bdsp_protocol.md).
"""

import struct

from pokeldn.bdsp.netdata import FIELDS, NAMES, OPAQUE

HEADER_SIZE = 3

# Payloads whose C# struct is not blittable, with the layout measured on the wire and from
# `ANetData<T>$$ConvertStructToBytes`.
MEASURED = {
    0x02: "12 x PosData, 72 bytes: ushort posX, ushort posZ, short rotY",
    0x13: "one encrypted PB8 at stored size, 328 bytes, no length prefix",
    0x14: "694 bytes: RECORD 120, RANDOM_SEED 132, TvRecodeData 204, 4 x TV_STR_DATA 36, "
          "RECORD_HEAD 48, ten ints, six bytes",
    0x15: "143 bytes: byte count, is3D, template, then 20 x SealParam{short x, y, z; byte id}",
    0x22: "5 x StandbyData, 20 bytes: byte isAddPlayer, hostIndex, myIndex, langId",
    0x24: "26-byte name, u32 tranerId, byte cassetVersion, byte langId",
    0x38: "481 bytes: a 328-byte PB8, 20 x SealParam, u32 attachPokemonId, u32 attachPersonalRnd, "
          "byte index, num, is3DEditMode, isAppliedTemplate, affixSealCount",
    0x18: "616 bytes: short zoneID, posX, posY; byte direction, expansionStatus; int goodCount; "
          "30 x UgStoneStatue{int statueId, pedestalId, posX, posY, dir}; bool isEnable (4)",
    0x42: "26-byte name, byte genderid, byte languageId",
    0x54: "the same 616 bytes as 0x18",
    0x61: "8 bytes of dig-fossil ids, one per station",
}

RECODE = 0x14                     # NetDataRecodeData - the record-mixing payload
BALL_DECO = 0x15                  # NetDataAttachSealNetData - the ball-capsule payload
SEAL_SLOTS = 20
SEAL_SIZE = 7

# Marshalled sizes from the 1.3.0 Il2CppTypeDefinitionSizes table (docs/bdsp_protocol.md).
NATIVE_SIZES = {
    0x02: 72, 0x13: 328, 0x14: 694, 0x15: 143, 0x18: 616, 0x22: 20, 0x24: 32, 0x29: 8,
    0x38: 481, 0x42: 28, 0x54: 616, 0x61: 8,
}

STANDBY_LIST = 0x22               # NetDataStandbyWaitListData - answers a request for 0x22
STANDBY_SLOTS = 5                 # UnionRoomManager$$SendStandbyPlayerData allocates the array
STANDBY_SIZE = 4

JOIN = 0x01                       # NetJoinData
POS = 0x02                        # NetPosData
EMOTION = 0x03                    # NetEmotionData
STATE = 0x04                      # NetCharacterStateData
TRAINER_CARD = 0x05               # NetDataTranerCardData
REQUEST = 0x12                    # NetRequestData - "send me your <data id>"
MATCH_WAIT = 0x23                 # NetDataIsMatchWaitData
TALK = 0x06                       # NetDataTalkData; talkState CHECK (0) is a null dereference
                                  # in the receiver unless a message window is already open
TALK_RESERVE = 0x63               # NetDataTalkReserveData: "I want to talk to your character"
TALK_RESERVE_RESULT = 0x64        # NetDataTalkReserveResultData, the answer that unblocks it
PLAYER_NAME = 0x42                # NetPlayerNameData, a string

JOIN_BODY_SIZE = 17
POS_POINT_SIZE = 6
POS_POINTS = 12                   # 12 * 6 is the 0x48 captured

# A real player's walk, median over 80 NetPosData; a ninth of this renders as a stutter.
POS_PERIOD = 0.41                 # seconds; min 0.20 max 1.59
POS_STRIDE = 0.93                 # units one message spans; max 2.60
POS_SCALE = 0.05                  # PosData.pos: -posX * 0.05, posZ * 0.05
POS_UNIT = 20.0                   # the setter multiplies by 20: 10.35 / 0.05 truncates to 206,
                                  # 10.35 * 20 gives 207
# `NetCharacterStateData{NONE, 0}`, broadcast every two seconds by a console standing still.
STATE_NONE_MESSAGE = bytes.fromhex("0400020000")
KEEPALIVE = STATE_NONE_MESSAGE            # an alias, kept so an old log still reads

# The names used before opendpr's, kept so an old log still reads.
DATA_ID_NAMES = {ident: name for ident, (name, _) in NAMES.items()}


def name(data_id):
    known = NAMES.get(data_id)
    return known[0] if known else f"data id {data_id:#04x}"


def layout(data_id):
    """-> the struct format for a payload, or None when it is not blittable (`netdata.OPAQUE`)."""
    fields = FIELDS.get(data_id)
    return "<" + "".join(fmt for _, _, fmt in fields) if fields else None


def parse(data):
    """-> dict, one game message. The length is big-endian; everything inside it is not."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a game message is at least {HEADER_SIZE} bytes, got {len(data)}")
    data_id = data[0]
    length = struct.unpack_from(">H", data, 1)[0]
    body = data[HEADER_SIZE:HEADER_SIZE + length]
    out = {"data_id": data_id, "name": name(data_id), "length": length, "body": body,
           "truncated": len(body) < length,
           "opaque": data_id in OPAQUE and data_id not in MEASURED}
    fields = parse_fields(data_id, body)
    if fields is not None:
        out["fields"] = fields
    if data_id == JOIN and len(body) >= JOIN_BODY_SIZE:
        out["join"] = parse_join_body(body)
    elif data_id == POS:
        out["points"] = parse_pos_body(body)
    elif data_id == STANDBY_LIST:
        out["standby"] = parse_standby_list(body)
    elif data_id == BALL_DECO and len(body) >= 3 + SEAL_SIZE:
        out["ball_deco"] = parse_ball_deco(body)
    elif data_id == RECODE and len(body) >= NATIVE_SIZES[RECODE]:
        out["recode"] = parse_recode_head(body)
    elif data_id == SELECT_POKEMON and len(body) >= NATIVE_SIZES[SELECT_POKEMON]:
        out["select_pokemon"] = parse_select_pokemon(body)
    elif data_id == TRADE_TRANER and len(body) == TRADE_TRANER_SIZE:
        out["traner"] = parse_trade_traner(body)
    return out


def parse_fields(data_id, body):
    """-> {name: value} for any payload the generated table gives a layout, else None."""
    fmt = layout(data_id)
    if fmt is None or len(body) < struct.calcsize(fmt):
        return None
    values, out = struct.unpack_from(fmt, body), {}
    i = 0
    for field, _, sub in FIELDS[data_id]:
        count = len(struct.unpack("<" + sub, bytes(struct.calcsize("<" + sub))))
        out[field] = values[i] if count == 1 else values[i:i + count]
        i += count
    return out


def parse_standby_list(body):
    """`StanbyListData`: five StandbyData{isAddPlayer, hostIndex, myIndex, langId}, one byte each;
    an empty list is twenty zero bytes [1.3.0 main 0x01e52fa0]."""
    return [{"is_add_player": body[i], "host_index": body[i + 1], "my_index": body[i + 2],
             "lang_id": body[i + 3]}
            for i in range(0, min(len(body), STANDBY_SLOTS * STANDBY_SIZE), STANDBY_SIZE)]


def parse_ball_deco(body):
    """`BallDecoData`: count, is3DEditMode, isAppliedTemplate, then twenty SealParam."""
    seals = [dict(zip(("x", "y", "z", "seal_id"), struct.unpack_from("<hhhB", body, 3 + i * SEAL_SIZE)))
             for i in range(min(SEAL_SLOTS, (len(body) - 3) // SEAL_SIZE))]
    return {"count": body[0], "is_3d_edit": body[1], "is_template": body[2], "seals": seals}


def parse_recode_head(body):
    """The RECORD counters, names, trainer id and version of a `NetRecodeData`."""
    counters = struct.unpack_from("<30I", body, 0)
    group = body[0x78:0x98].decode("utf-16-le", "replace").split("\0")[0]
    name = body[0x98:0xd8].decode("utf-16-le", "replace").split("\0")[0]
    sex, region, seed, random, stamp, user_id = struct.unpack_from("<iiQQqI", body, 0xd8)
    return {"counters": counters, "group_name": group, "name": name, "sex": sex,
            "region_code": region, "seed": seed, "random": random, "time_stamp": stamp,
            "user_id": user_id, "language": struct.unpack_from("<i", body, 0x274)[0],
            "unique_id": struct.unpack_from("<I", body, 0x280)[0], "version": body[0x2b0]}


SELECT_POKEMON = 0x38             # NetDataBattleMatchingSelectPokemon - one per team member


def parse_select_pokemon(body):
    """`BattleMatchingPokeData`: the encrypted PB8, then the seals, then the ids and the slot."""
    attach_id, attach_rnd, index, num, is_3d, template, count = struct.unpack_from("<IIBBBBB", body, 0x1d4)
    return {"pb8": body[:328], "seals": parse_ball_deco(b"\0\0\0" + body[0x148:0x1d4])["seals"],
            "attach_pokemon_id": attach_id, "attach_personal_rnd": attach_rnd, "index": index,
            "num": num, "is_3d_edit": is_3d, "is_template": template, "seal_count": count}


def parse_join_body(body):
    """`JoinData`: avatarId, colorId, cassetVersion, InitRotY, InitPos - C#'s own field order."""
    if len(body) < JOIN_BODY_SIZE:
        raise ValueError(f"a JoinData is {JOIN_BODY_SIZE} bytes, got {len(body)}")
    x, y, z = struct.unpack_from("<fff", body, 5)
    return {"avatar_id": body[0], "color_id": body[1], "casset_version": body[2],
            "rot_y": struct.unpack_from("<h", body, 3)[0], "x": x, "y": y, "z": z}


def parse_pos_body(body):
    """-> a list of {x, z, rot_y}, already through the game's own scaling."""
    out = []
    for i in range(len(body) // POS_POINT_SIZE):
        px, pz, rot = struct.unpack_from("<HHh", body, i * POS_POINT_SIZE)
        out.append({"x": -px * POS_SCALE, "z": pz * POS_SCALE, "rot_y": rot,
                    "raw": (px, pz)})
    return out


def build(data_id, body):
    return bytes([data_id & 0xFF]) + struct.pack(">H", len(body)) + bytes(body)


def build_fields(data_id, *values):
    """Pack a payload from the generated layout. Raises on an id whose struct is not blittable."""
    fmt = layout(data_id)
    if fmt is None:
        raise ValueError(f"{name(data_id)} has no layout this table can decide "
                         f"({OPAQUE.get(data_id, 'unknown')} is not blittable)")
    return build(data_id, struct.pack(fmt, *values))


UG_JOIN = 0x16                    # NetUgJoinData - the Grand Underground's join record
ZONE = 0x17                       # NetZoneData - a station's zone and position, sent on arrival


def build_ug_join(x, y, z, zone_id, rot_y=0, avatar_id=0, color_id=0):
    """`UgJoinData`: avatarId, colorId, short zoneID, short InitRotY, Vector3 InitPos - 18 bytes,
    the fields `UgNetworkManager$$MakeJoinData` [1.3.0 main 0x01f79580] fills."""
    body = (bytes([avatar_id & 0xFF, color_id & 0xFF]) + struct.pack("<hh", int(zone_id), int(rot_y))
            + struct.pack("<fff", float(x), float(y), float(z)))
    return build(UG_JOIN, body)


def build_join(x, y, z, rot_y=0, avatar_id=8, color_id=0, casset_version=0x31):
    """"A player has joined, here." The defaults are what a real console sends."""
    body = (bytes([avatar_id & 0xFF, color_id & 0xFF, casset_version & 0xFF])
            + struct.pack("<h", int(rot_y)) + struct.pack("<fff", float(x), float(y), float(z)))
    return build(JOIN, body)


def build_pos(points):
    """`points` is [(x, z, rot_y), ...]; x negated, both scaled by 20 as `PosData.pos` does."""
    body = b"".join(struct.pack("<HHh", int(abs(x * POS_UNIT)), int(abs(z * POS_UNIT)), int(rot))
                    for x, z, rot in points)
    return build(POS, body)


def pos_span(start, end, rot_y, points=POS_POINTS):
    """-> the twelve points of one NetPosData spanning a whole stride, endpoint included; tighter
    points make the avatar creep, then jump. `start` and `end` are (x, z)."""
    if points < 1:
        raise ValueError("a NetPosData carries at least one point")
    (x0, z0), (x1, z1) = start, end
    last = max(points - 1, 1)
    return [(x0 + (x1 - x0) * i / last, z0 + (z1 - z0) * i / last, rot_y) for i in range(points)]


def build_trainer_card(fashion_id=0, body_type=0, gender_id=0, lang_id=2, trainer_rank=1,
                       trainer_id=0, money=0, zukan_count=0, play_time_hour=1, play_time_minute=0):
    """`NetDataTranerCardData`: 75 bytes from opendpr's field list; no capture holds one."""
    return build_fields(TRAINER_CARD,
                        fashion_id & 0xFF, body_type & 0xFF, gender_id & 0xFF, lang_id & 0xFF,
                        trainer_rank & 0xFF,
                        0,                                  # cardData.startTime, a long
                        trainer_id & 0xFFFFFFFF, money & 0xFFFFFFFF, zukan_count & 0xFFFFFFFF,
                        0, 0, 0, 0, 0,                      # style/beatiful/cute/clever/strong rank
                        0, 0, 0, 0,                         # the four renshou streaks
                        0,                                  # clearTime
                        0,                                  # digFossilPlayCount, a short
                        play_time_hour & 0xFFFF, play_time_minute & 0xFFFF,
                        0, 0, 0, 0)                         # tagIndex, isZukanGet, cooking, statues


def build_request(requested_id):
    """"Send me your <data id>." `RequestData.RequestDataID` is itself one of these ids."""
    return build_fields(REQUEST, requested_id & 0xFF)


TRADE_POKE_CHECK_OK = 0x46        # NetDataTradePokeCheckOkData
TRADE_READY_OK = 0x21             # NetDataTradeReadyOkData: past this the console writes its save
TRADE_TRANER = 0x24               # NetDataTradeTranerData
TRADE_POKE = 0x13                 # NetTradePokeData: a whole Pokemon, 328 bytes
RETURN_SELECT = 0x45              # NetDataReturnSelectData: back in the select window after a
                                  # trade, once a second; answering it changes nothing


def parse_trade_traner(body):
    """-> the 32-byte marshalled `TradeTranerData`: name, u32 id, version, language; the ten bytes
    past the name are heap residue, kept as `slack` (docs/bdsp_trade.md)."""
    if len(body) != TRADE_TRANER_SIZE:
        raise ValueError(f"{len(body)} bytes, expected {TRADE_TRANER_SIZE}")
    trainer_id32, casset, lang = struct.unpack_from("<IBB", body, 26)
    return {"name": body[0:TRADE_TRANER_NAME_SIZE].decode("utf-16-le").split("\x00")[0],
            "trainer_id32": trainer_id32,
            "trainer_id": trainer_id32 & 0xFFFF, "secret_id": trainer_id32 >> 16,
            "casset_version": casset, "lang_id": lang,
            "slack": bytes(body[16:26]).hex()}


TRADE_TRANER_SIZE = 32
TRADE_TRANER_NAME_SIZE = 26

# The console's own heap residue at 0x10 (docs/bdsp_trade.md).
CONSOLE_SLACK = bytes.fromhex("18a4010014a4010000 00".replace(" ", ""))


def build_trade_poke(pb8):
    """A NetTradePokeData carrying an encrypted 328-byte PB8; accepted only while the manager's
    state is 1 [`UnionTradeManager$$RecivePokeData` main.bin 0x1dd2800]."""
    if len(pb8) != 328:
        raise ValueError(f"{len(pb8)} bytes, expected a 328-byte PB8")
    return build(TRADE_POKE, pb8)


def build_trade_traner(name, trainer_id, secret_id, casset_version=0x31, lang_id=3,
                       slack=CONSOLE_SLACK):
    """The marshalled 32-byte record; the defaults are a French console's own."""
    encoded = name.encode("utf-16-le")
    if len(encoded) + 2 > TRADE_TRANER_NAME_SIZE:
        raise ValueError(f"{name!r} is too long for the {TRADE_TRANER_NAME_SIZE}-byte name field")
    if len(slack) != 10:
        raise ValueError(f"{len(slack)} bytes of slack, expected 10")
    trainer_id32 = (trainer_id & 0xFFFF) | ((secret_id & 0xFFFF) << 16)
    return build(TRADE_TRANER,
                 encoded.ljust(16, b"\x00") + bytes(slack)
                 + struct.pack("<IBB", trainer_id32, casset_version & 0xFF, lang_id & 0xFF))


# `TradeStateModel.TradeState` [dump.cs:258737].
TRADE_STATE_NONE = 0
TRADE_STATE_INIT = 1
TRADE_STATE_WAIT = 2
TRADE_STATE_SEND_POKE = 3
TRADE_STATE_WAIT_POKE = 4
TRADE_STATE_SEND_READYOK = 5
TRADE_STATE_WAIT_READYOK = 6
TRADE_STATE_START_WRITE_SAVE = 7
TRADE_STATE_WRITEING_SAVE = 8


TRADE_STATE_NAMES = {
    TRADE_STATE_NONE: "NONE", TRADE_STATE_INIT: "INIT", TRADE_STATE_WAIT: "WAIT",
    TRADE_STATE_SEND_POKE: "SEND_POKE", TRADE_STATE_WAIT_POKE: "WAIT_POKE",
    TRADE_STATE_SEND_READYOK: "SEND_READYOK", TRADE_STATE_WAIT_READYOK: "WAIT_READYOK",
    TRADE_STATE_START_WRITE_SAVE: "START_WRITE_SAVE", TRADE_STATE_WRITEING_SAVE: "WRITEING_SAVE",
    9: "END_SAVE", 10: "END", 11: "ERROR",
}


def mirror_trade_state(their_state):
    """-> the state to claim back so that the console's machine advances (docs/bdsp_trade.md).

    WAIT_POKE is answered with SEND_READYOK: echoing it deadlocks a CHILD console.
    """
    if their_state <= TRADE_STATE_INIT:
        return TRADE_STATE_WAIT
    if their_state >= TRADE_STATE_WAIT_POKE:
        return TRADE_STATE_SEND_READYOK
    return their_state


def repeats_trade_state(their_state):
    """-> whether our security state is still re-said: the answer to a console's SEND_READYOK lands
    in its WAIT_READYOK in either role, and a later repeat can land in its select window and cancel
    the next round (docs/bdsp_trade.md, The completed trade)."""
    return their_state is not None and their_state < TRADE_STATE_SEND_READYOK


def build_trade_ready_ok(trade_state=TRADE_STATE_WAIT, is_trade_ok=0):
    """The 0x21 that lets the console write its save; only `tradeState` is read
    [`TradeSelectPokeModel$$ReciveReadyOk` main.bin 0x1cd4860]. Defaults give the console's own
    `21 00 02 00 02` (docs/bdsp_trade.md)."""
    return build_fields(TRADE_READY_OK, is_trade_ok & 0xFF, trade_state & 0xFF)


def build_talk_reserve(body_byte=0):
    """The console's own `63 00 01 00`: the approach must come from us, since an emote locks the
    player in place. opendpr declares no layout for it."""
    return build(TALK_RESERVE, bytes([body_byte & 0xFF]))


def build_match_wait(is_waiting=False):
    """`isMatchWait`: only 1 starts a trade [`UnionRoomManager$$SetNetData` main.bin 0x01fd56e4];
    the console's own repeated answer is 0."""
    return build_fields(MATCH_WAIT, 1 if is_waiting else 0)


# `OpcState.OnlineState` [opendpr:Assets/Scripts/OpcState.cs]; `IsCanTalkState()` reads it
# (docs/bdsp_protocol.md).
STATE_NONE = 0
STATE_RECRUITMENT_BATTLE = 3
STATE_RECRUITMENT_TRADE = 4
STATE_RECRUITMENT_RECORD = 5
STATE_RECRUITMENT_GREETINGS = 6
STATE_RECRUITMENT_BALL_DECORATION = 7
STATE_COMMUNICATE = 8


def build_state(state=STATE_NONE, is_recruitment=0):
    """`StateData`; the default is a character standing still, the answer to a request for 0x04."""
    return build_fields(STATE, state & 0xFF, is_recruitment & 0xFF)


def build_talk_reserve_result(can_talk=1, is_recruitment=1, emoticon_state=STATE_NONE):
    """The answer to `NetDataTalkReserveData`; unanswered, the player's character freezes until
    reboot. `IsCanTalk` decides it (docs/bdsp_protocol.md)."""
    return build_fields(TALK_RESERVE_RESULT, can_talk & 0xFF, is_recruitment & 0xFF,
                        emoticon_state & 0xFF)


def build_emotion(emotion_id):
    return build_fields(EMOTION, emotion_id & 0xFF)


def answer(message, state=STATE_NONE, is_recruitment=0, match_wait=False):
    """-> the reply a NetRequestData asks for, when the requested id has a layout, else None."""
    if message.get("data_id") != REQUEST or not message.get("fields"):
        return None
    wanted = message["fields"]["RequestDataID"]
    if wanted == MATCH_WAIT:
        return build_match_wait(match_wait)
    if wanted == STATE:
        return build_state(state, is_recruitment)
    if layout(wanted) is None:
        return None
    return build(wanted, bytes(struct.calcsize(layout(wanted))))

"""Sword/Shield's application layer: a four-byte little-endian message id and a protobuf body, in
the shapes `main`'s own FileDescriptorProtos give (docs/swsh_protocol.md, docs/swsh_trade.md).
"""
import struct


WIRE_VARINT = 0
WIRE_BYTES = 2


def varint(value):
    if value < 0:
        raise ValueError("only non-negative varints appear in these messages")
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(number, payload):
    """A length-delimited field: `bytes` or a nested message."""
    return varint((number << 3) | WIRE_BYTES) + varint(len(payload)) + bytes(payload)


def field_varint(number, value):
    return varint((number << 3) | WIRE_VARINT) + varint(value)


SYNC_PING = 97                        # gflnet.p2p.sync.ping.pb.SyncPingDataHolder
BLOCK = 60000                         # gflnet.p2p.block.pb.BlockDataHolder
POKEMON_TRADE = 20030                 # the console offers its own Pokemon here

PING, PING_REPLY, PING_SYNCED = 1, 2, 3           # SyncPingDataHolder's three fields
RESULT, IM_READY = 1, 2                           # BlockDataHolder's two

# Holders of the same three-field shape; all four ids are in the low registration table.
SYNC_IDS = (SYNC_PING, 110, 120, 130)


def message(message_id, body=b""):
    """-> the four-byte little-endian id and its protobuf body, which is the whole wire format."""
    return struct.pack("<I", message_id) + bytes(body)


def parse(payload):
    """-> (message_id, body). Raises on anything too short to carry an id."""
    if len(payload) < 4:
        raise ValueError(f"{len(payload)} bytes cannot carry a message id")
    return struct.unpack_from("<I", payload, 0)[0], payload[4:]


def sync(message_id, which):
    """-> an empty one of the three sync fields, e.g. `610000000a00` for ping."""
    return message(message_id, field(which, b""))


def result():
    """`result{}` on the block holder, what the console asks for on 0x7C. Measured."""
    return message(BLOCK, field(RESULT, b""))


def im_ready(ready=True):
    """`imReady{isReady:true}`, what the console asks for on 0x80. Measured."""
    return message(BLOCK, field(IM_READY, field_varint(1, 1 if ready else 0)))


def pokemon_trade(pk8):
    """-> PokemonTradeDataHolder{pokemon{serializePokemonParam: <the encrypted PK8>}}."""
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return message(POKEMON_TRADE, field(1, field(1, pk8)))


# The trade RPC envelope `gflnet.p2p.sync.pb.Data`: syncId, elementId, ownerId, clock, body
# (docs/swsh_trade.md, The trade RPC). 20030 is 20000 + 30 assembled on the wire.
RPC_ENVELOPE_BASE = 40000             # the envelope's own id is this plus the same offset
RPC_ENVELOPE = 40030                  # offset 30, the one the console sends
RPC_PREFIX = struct.pack("<I", RPC_ENVELOPE)
RPC_OFFSET, RPC_BASE, RPC_STATION, RPC_CLOCK, RPC_BODY = 1, 2, 3, 4, 5
RPC_BASES = (10000, 20000)

# The dispatcher [main.bin 0x013b2c00] indexes an id in 40001..60000 at `id - 40001`, so 40040 and
# 40050 are legal ids in the band of 40030.
OFFER_OFFSET = 30
SELECTION_OFFSET = 50
CONFIRMATION_OFFSET = 40

# The three trade contents and their holders (docs/swsh_protocol.md, The three trade contents).
CONTENT_HOLDERS = {OFFER_OFFSET: "BoxSyncStateDataHolder",
                   SELECTION_OFFSET: "PokemonTradeDataHolder",
                   CONFIRMATION_OFFSET: "SyncSaveDataHolder"}
RPC_POKEMON_FIELD = 5

# The console's own pair bodies against bases 10000 and 20000, on 40030 and 40050 alike.
RPC_PAIR_BODIES = (b"\x00\x00\x00\x00", bytes.fromhex("000018fc"))


def build_rpc(offset, base, station_id, clock, body=b"\x00\x00\x00\x00", envelope=None):
    """-> one member of a trade RPC pair; `envelope` defaults to `40000 + offset`."""
    inner = field_varint(RPC_OFFSET, offset)
    if base is not None:                      # the console's own Pokemon-carrying 40050 has
        inner += field_varint(RPC_BASE, base)  # only fields 1, 4 and 5
    if station_id is not None:
        inner += field_varint(RPC_STATION, station_id)
    inner += field_varint(RPC_CLOCK, clock) + field(RPC_BODY, body)
    if envelope is None:
        envelope = RPC_ENVELOPE_BASE + offset
    return message(envelope, field(1, inner))


def build_rpc_pokemon(offset, base, station_id, clock, pk8):
    """-> an RPC envelope carrying a PK8 in field 5, the shape the console uses on content 50."""
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return build_rpc(offset, base, station_id, clock, pk8)


def mirror_pokemon_offer(offset, clock, pk8):
    """-> a Pokemon-carrying envelope with the console's own field set (1, 4, 5): syncId, clock,
    body; all five fields under our ownerId are acknowledged and move nothing."""
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return build_rpc(offset, None, None, clock, pk8)


def build_rpc_pair(offset, station_id, clock, bodies=RPC_PAIR_BODIES):
    """-> the two members of an RPC pair, base 10000 then base 20000, in the console's order."""
    return tuple(build_rpc(offset, base, station_id, clock, body)
                 for base, body in zip(RPC_BASES, bodies))


def parse_rpc(payload):
    """-> the five members of a trade RPC, or None if this is not one."""
    got = _maybe_parse(payload)
    # Any envelope in the band: past the offer phase the console sends 40050 pairs.
    if got is None or not (RPC_ENVELOPE_BASE < got[0] <= RPC_ENVELOPE_BASE + 1000):
        return None
    _, body = got
    outer = _read_fields(body)
    if not isinstance(outer.get(1), bytes):
        return None
    inner = _read_fields(outer[1])
    return {"envelope": got[0], "offset": inner.get(RPC_OFFSET), "base": inner.get(RPC_BASE),
            "station_id": inner.get(RPC_STATION), "clock": inner.get(RPC_CLOCK),
            "body": inner.get(RPC_BODY, b"")}


def answer_rpc(payload, station_id, clock_delta=5):
    """-> the same RPC with our station id and the clock advanced, or None if it is not one."""
    got = parse_rpc(payload)
    # The console's Pokemon rides a 40050 with no base field, and its echo of ours carries base 1:
    # answer only a complete envelope. A reader on a live run must not raise.
    if got is None or any(got[k] is None for k in ("offset", "base", "clock")):
        return None
    return build_rpc(got["offset"], got["base"], station_id, got["clock"] + clock_delta,
                     got["body"])


def _read_fields(data):
    """-> {field number: value} for a flat protobuf message. Varints and byte fields only."""
    out, i = {}, 0
    while i < len(data):
        tag, i = _varint(data, i)
        number, wire = tag >> 3, tag & 7
        if wire == WIRE_VARINT:
            out[number], i = _varint(data, i)
        elif wire == WIRE_BYTES:
            size, i = _varint(data, i)
            out[number], i = data[i:i + size], i + size
        else:
            break
    return out


def _varint(data, i):
    value = shift = 0
    while i < len(data):
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7
    raise ValueError("truncated varint")


# The ping and block answers. Ids 110, 120 and 130 are in the low table; the rows for them are
# `andyjusa/nxldn-lab`'s console-to-console capture.
SYNC_ANSWERS = {
    sync(SYNC_PING, PING):            (sync(SYNC_PING, PING_REPLY), sync(SYNC_PING, PING)),
    sync(SYNC_PING, PING_SYNCED):     (sync(SYNC_PING, PING_SYNCED), result()),
    sync(110, PING):                  (sync(110, PING),),
    sync(110, PING_REPLY):            (sync(110, PING_REPLY), sync(110, PING_SYNCED)),
    sync(120, PING):                  (sync(120, PING),),
    sync(120, PING_REPLY):            (sync(120, PING_REPLY), sync(120, PING_SYNCED)),
    sync(130, PING):                  (sync(130, PING), sync(130, PING_REPLY)),
    sync(130, PING_SYNCED):           (sync(130, PING_SYNCED),),
}


def answers_for(payload):
    """-> the payloads to send back for one received payload, or () for one without a rule."""
    return SYNC_ANSWERS.get(bytes(payload), ())


# 20030 is a BoxSyncStateDataHolder: its field 2, `boxSyncStateCommand{data}`, is the command that
# moves the box state machine (docs/swsh_trade.md, The box state machine).
BOX_SEND_POKEMON, BOX_SYNC_STATE_COMMAND = 1, 2

# A content at offset N owns 10000+N, 20000+N and 30000+N; the framework mints 40000+N. The console
# never opens a phase after the offer, so the host opens them.
CONTENT_BASE_LOW = 10000


def open_content(offset, which=PING):
    """-> `ping` on content `offset`'s 10000-base holder: `382700000a00` for offset 40."""
    return message(CONTENT_BASE_LOW + offset, field(which, b""))


def pokemon_offer(offset, pk8):
    """-> PokemonTradeDataHolder on content `offset`'s 10000-base holder: id 10050 for offset 50.
    Content 50's parser `0x010d9ee0` accepts tag 0x0a only (docs/swsh_protocol.md)."""
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return message(CONTENT_BASE_LOW + offset, field(1, field(1, pk8)))


def pokemon_offer_high(offset, pk8):
    """-> PokemonTradeDataHolder on the 20000-base holder, id 20050 for offset 50. Inert: content 50
    installs no listener on that holder, and `0x010d81d0` returns on a null one."""
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return message(RPC_BASES[1] + offset, field(1, field(1, pk8)))


SYNC_SAVE_COMMAND = 1                 # SyncSaveDataHolder's only field
SYNC_COMMAND_DATA = 1                 # SyncCommand's only field

# The four commands content 40's machine `0x010dae70` sends through `0x010db840(delegate, data,
# flag)`; each parks it idle until the partner's command (flag is `data + 1`).
SYNC_COMMANDS = {0: "0x010db308, out of state 1  -> state 2",
                 1: "0x010db0b0, out of state 3  -> state 4",
                 2: "0x010db0dc / 0x010db104, states 6 and 8 -> states 7 and 9",
                 3: "0x010db16c, out of state 12 -> state 0, and the machine is done"}

# Phase -> the state that sends the next command, via the setter `0x010dbf40`; phase 4 tears down
# (docs/swsh_trade.md, The phase-to-state map).
SYNC_LADDER = {0: 1, 1: 3, 2: 5, 3: 10, 4: 13}


def sync_announced_phase(data):
    """-> the phase the console records when it sends command `data`: `data + 1`, written to
    `content+0x86` (docs/swsh_trade.md, The pump)."""
    return data + 1


def sync_step(phase, announced):
    """-> the four-byte step body `<u16 phase><u16 announced>` a content's element publishes; the
    halves have independent publishers (docs/swsh_trade.md, The step body)."""
    return struct.pack("<HH", phase & 0xFFFF, announced & 0xFFFF)


def answer_rpc_with_phase(payload, station_id, phase, clock_delta=5):
    """-> `answer_rpc`'s reply with the step body's phase half replaced, or None when the payload is
    not a four-byte RPC."""
    got = parse_rpc(payload)
    if got is None or any(got[k] is None for k in ("offset", "base", "clock")):
        return None
    step = parse_sync_step(got["body"])
    if step is None:
        return None
    return build_rpc(got["offset"], got["base"], station_id, got["clock"] + clock_delta,
                     sync_step(phase, step[1]))


def parse_sync_step(body):
    """-> `(phase, announced)` out of a content's four-byte step body, or None if it is not four
    (docs/swsh_trade.md, The step body)."""
    if body is None or len(body) != 4:
        return None
    return struct.unpack("<HH", bytes(body))


def sync_command(offset, data):
    """-> `SyncSaveDataHolder{syncCommand{data: <int32>}}` on content `offset`'s 10000-base holder
    (docs/swsh_trade.md, The command)."""
    if data < 0:
        raise ValueError(f"{data} is not one of the commands the machine sends: {sorted(SYNC_COMMANDS)}")
    return message(CONTENT_BASE_LOW + offset,
                   field(SYNC_SAVE_COMMAND, field_varint(SYNC_COMMAND_DATA, data)))


def parse_sync_command(payload):
    """-> the command int on any content's 10000-base holder, or None."""
    got = _maybe_parse(payload)
    if got is None or got[0] not in {CONTENT_BASE_LOW + o for o in CONTENT_HOLDERS}:
        return None
    inner = _read_fields(got[1]).get(SYNC_SAVE_COMMAND)
    if not isinstance(inner, bytes):
        return None
    value = _read_fields(inner).get(SYNC_COMMAND_DATA)
    return value if isinstance(value, int) else None


SELECTION_SWEEP_NOTE = """The selection-offer shapes that remain, swept together.

Every one of these is acknowledged at the transport and moves nothing: the holder on 10050, a
five-field Data on 40050 with our ownerId, the console's own three-field Data on 40050
(byte-identical in shape and length), the holder on 20050, and the 120 pingSynced the borrowed
trace calls the confirmation's opener (the console uses 97, 110 and 130 all run and never 120).

What is left comes from the binary rather than from another project's capture. Each content's
registrar builds THREE holders - 10000+off, 20000+off and 30000+off - and the 30000 family has
never been on the air here in either direction. And the pair's two members carry elementId 10000
and 20000, so if those are the two sides' slots, our Pokemon may belong on the one we have not
used.

This is deliberately NOT one variable. The player is the scarce resource and the remaining space is
two shapes; a run that moves anything at all is worth a bisect afterwards."""


def selection_sweep(offset, pk8):
    """-> the shapes left, in order: Data on elementId 10000, then the 30000-base holder."""
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return (build_rpc(offset, RPC_BASES[0], None, 0, pk8),
            message(30000 + offset, field(1, field(1, pk8))))


def box_sync_state(command):
    """-> `BoxSyncStateDataHolder{boxSyncStateCommand{data: command}}` on the trade holder."""
    return message(POKEMON_TRADE,
                   field(BOX_SYNC_STATE_COMMAND, field_varint(1, command)))


def parse_box_command(payload):
    """-> the command int on the trade holder, or None when the payload is not one."""
    got = _maybe_parse(payload)
    if got is None or got[0] != POKEMON_TRADE:
        return None
    outer = _read_fields(got[1])
    inner = outer.get(BOX_SYNC_STATE_COMMAND)
    if not isinstance(inner, bytes):
        return None
    value = _read_fields(inner).get(1)
    return value if isinstance(value, int) else None


def trade_ready(ready=True):
    """`imReady{isReady:true}` on the trade holder, 20030: nxldn-lab's client waits for these bytes
    before sending its own Pokemon."""
    return message(POKEMON_TRADE, field(IM_READY, field_varint(1, 1 if ready else 0)))


def _maybe_parse(payload):
    """-> (id, body), or None. At the confirmation prompt the console sends a three-byte message;
    raising on it kills the run mid-trade."""
    payload = bytes(payload)
    if len(payload) < 4:
        return None
    return struct.unpack_from("<I", payload, 0)[0], payload[4:]


def offered_pokemon(payload):
    """-> the 0x158 PK8 inside a trade offer on 20030, or None when this is not one."""
    got = _maybe_parse(payload)
    if got is None or got[0] != POKEMON_TRADE:
        return None
    _, body = got
    outer = _read_fields(body)
    if not isinstance(outer.get(1), bytes):
        return None
    inner = _read_fields(outer[1])
    pk8 = inner.get(1)
    return pk8 if isinstance(pk8, bytes) and len(pk8) in (0x148, 0x158) else None


def answers_for_offer(payload, our_pk8):
    """-> our own offer, as a one-tuple, when the console has just made one."""
    if our_pk8 is None or offered_pokemon(payload) is None:
        return ()
    return (pokemon_trade(our_pk8),)


def answers_for_rpc(payload, station_id, clock_delta=5):
    """-> the reply to a trade RPC as a one-tuple, or () when the payload is not one."""
    answer = answer_rpc(payload, station_id, clock_delta)
    return (answer,) if answer is not None else ()


def next_answer(said, queue=(), station_id=None, clock_delta=5, offer_pk8=None):
    """-> (what to send now, the queue after it): the table's rule where there is one, else the
    console's own payload echoed back."""
    queue = list(queue)
    if not queue:
        queue = list(answers_for(said))
    if not queue:
        # Echoing an offer hands the console back its own Pokemon under its own trainer's name.
        queue = list(answers_for_offer(said, offer_pk8))
    if not queue and station_id is not None:
        # Mirroring an RPC sends the console its own station id back.
        queue = list(answers_for_rpc(said, station_id, clock_delta))
    if queue:
        return queue[0], queue[1:]
    return said, []


def unanswered(payloads):
    """-> the distinct payloads a run saw that nothing here answers."""
    return sorted({bytes(p) for p in payloads if not answers_for(p)})

"""A Tera Raid on 0x80 port 0, both roles, as pure state machines: the lobby, the battle bootstrap
and the start of the battle (docs/sv_raid.md). A raid message is a game message (`pokeldn.sv.trade`)
whose body is the game's serializer header and a payload. `RaidHost.actions` and
`RaidGuest.tick` return what to send; the launcher owns Pia, sequences and retransmits.
"""

import struct

from pokeldn import gen9
from pokeldn.ldn import channel_table as tables, reliable5
from pokeldn.sv import lz4, raid_encounter, streams, trade

KEY_LOBBY = 0x3380
KEY_BATTLE = 0x3480
KEY_LOAD = 0x0132
# The handler keys a raid host announces on 0x7C port 1: a Link Trade's four, then the raid's two.
CHANNEL_KEYS = (0x007B, 0x0132, 0x0232, 0x0332, KEY_LOBBY, KEY_BATTLE)
KIND_DESCRIPTOR, KIND_STATE, KIND_POKEMON, KIND_BOOTSTRAP, KIND_COUNTDOWN = 0x2C, 0x2D, 0x2E, 0x2F, 0x30
COMPRESSION_NONE, COMPRESSION_LZ4 = 0, 2
SERIALIZER_HEADER = struct.Struct("<HII4s")      # counter, compression, plain size, four unread bytes

STATE_IDLE, STATE_READY, STATE_START, STATE_STARTED = 0x18, 0x01, 0x0C, 0x0D

# What a retail host and a retail guest sent, by the prefix the game dispatches on.
CONSOLE_POKEMON = trade.build(KEY_LOBBY, KIND_POKEMON, 1)
CONSOLE_STATE = trade.build(KEY_LOBBY, KIND_STATE, 1)
CONSOLE_LOADING = trade.build(KEY_LOAD, 0x6E)
CONSOLE_LOADED = trade.build(KEY_LOAD, 0x73)
BATTLE = trade.build(KEY_BATTLE, 0x93, 1)
# The host's two loading transitions and its six battle-start messages, as a retail host sent them.
# Two opaque words in the handoff (`05050726`, `ceaf29`) are untraced (docs/sv_raid.md, Unresolved).
LOADED = bytes.fromhex("320173000400000000000800000000006f740100000001000000")
BATTLE_READY = bytes.fromhex("803493010400000000000400000000000000ed030000")
HANDOFF = tuple(bytes.fromhex(h) for h in (
    "7b0013270000010000000200000020000000010000000000000001000000000000000000000000000000050507265a000000",
    "7b00132700000300000005000000240000004600000000000000000000000000000000000000000000000500ceaf2900000000000000",
    "7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000501000000000000",
    "7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000503000000000000",
    "7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000504000000000000",
    "7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000500000000000000"))

COMPLETE = reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START | reliable5.FLAG_MESSAGE_END
COMPLETE_ZLIB = COMPLETE | reliable5.FLAG_ZLIB
FIRST = COMPLETE_ZLIB | reliable5.FLAG_IS_INITIALIZED
FRAGMENT_START = reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
FRAGMENT_END_ZLIB = reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_END | reliable5.FLAG_ZLIB
BOOTSTRAP_FRAGMENT = 1395         # where a retail host split its 0x012f message

# The battle bootstrap: four participants, the boss, the RaidPoint [0xe327fc].
PARTICIPANTS = 4
BOOTSTRAP_SIZE = 5 * gen9.SIZE_PARTY + 0x3E8
RAIDPOINT = 5 * gen9.SIZE_PARTY
POINT_SIZE = 0x3E8
POINT_NAME = "RaidPoint_POKELDN_0"
POINT_REWARDS = 0x0E4             # rows of item, quantity, 0, subject
POINT_SUMMARY = 0x3B8
REWARD_ROWS = (POINT_SUMMARY - POINT_REWARDS) // 16           # 45
SUBJECT_ALL = 0                   # the table's SubjectType: 0 everyone, 1 host, 2 guests
CONTENT_STANDARD = 2
TERA_EMPTY = raid_encounter.TERA_NONE
FIRST_COUNTER = 0x0105            # the host's lobby counters run on from here; the bootstrap 0x010f

# Seconds after the port-2 answer for messages 1 to 10, and after message 15 for 15 to 20, as a
# retail host's raid ran.
LOBBY_AT = (0.0, 0.0, 0.0, 0.726, 1.758, 2.748, 3.192, 3.757, 4.787, 5.393)
HANDOFF_AT = (0.0, 0.0, 0.101, 0.121, 0.161, 0.181)
HANDOFF_LOWEST = (None, 15, 15, 17, 18, None)
GATE_MARGIN = 0.05                # a gated message leaves this long after its milestone
RETRY = 0.5                       # the raid Net 0x50 and Session update repeat until answered
LINGER = 5.0                      # the host leaves this long after its twentieth message
STATION_LIST_RETRY = 2.0          # a retail raid host resends its Session station list this often


def channel_table():
    return tables.build([(struct.pack("<II", key & 0xFF, key >> 8), True) for key in CHANNEL_KEYS])


def message(key, kind, step, counter, payload, *, compression=COMPRESSION_NONE, size=None,
            unread=bytes(4)):
    """-> a serialized raid message: the game message header, then the serializer header."""
    payload = bytes(payload)
    return (trade.build(key, kind, step)
            + SERIALIZER_HEADER.pack(counter, compression, len(payload) if size is None else size,
                                     bytes(unread)) + payload)


def payload_of(raw):
    """-> the payload of a serialized raid message, decompressed when it says LZ4."""
    _, compression, size, _ = SERIALIZER_HEADER.unpack_from(raw, 4)
    body = raw[4 + SERIALIZER_HEADER.size:]
    return lz4.decompress(body, size) if compression == COMPRESSION_LZ4 else body


def state(counter, value, *, initial=False):
    body = (bytes.fromhex("080000000400040004000000") if initial else
            bytes.fromhex("0c000000000006000c00040006000000") + struct.pack("<II", value, 0))
    return message(KEY_LOBBY, KIND_STATE, 1, counter, body)


def state_of(raw):
    """-> the lobby state a 42-byte state message carries, or None."""
    if len(raw) != 42 or raw[:4] != CONSOLE_STATE:
        return None
    return struct.unpack_from("<I", raw, 34)[0]


def pokemon(counter, party_pk9):
    """-> the lobby message presenting a participant's 344-byte party record."""
    return message(KEY_LOBBY, KIND_POKEMON, 1, counter, gen9.encrypt(gen9.load(party_pk9)))


def pokemon_of(raw):
    """-> the plain party record a lobby Pokemon message carries, or None."""
    if raw[:4] != CONSOLE_POKEMON or len(raw) != 18 + gen9.SIZE_PARTY:
        return None
    try:
        return gen9.load(raw[18:])
    except ValueError:
        return None


def countdown(counter, value):
    body = bytes.fromhex("0c000000000006000800040006000000") + struct.pack("<I", value)
    return message(KEY_LOBBY, KIND_COUNTDOWN, 1, counter, body)


def descriptor(counter, raid):
    """-> what the lobby shows of the raid before the battle: species, form, stars, Tera, gender."""
    boss = raid.boss
    body = struct.pack("<11I", 0, gen9.internal_index(raid.species), boss["form"], 0, raid.stars,
                       raid.tera_type, boss["gender"], raid.row["identifier"], 0, 0x33, 0)
    return message(KEY_LOBBY, KIND_DESCRIPTOR, 1, counter, body)


def empty_participant():
    """-> the record a retail bootstrap holds in an empty participant slot: species 0, level 1,
    named Egg. An all-zero record crashed a console when its battle began."""
    return gen9.encrypt(gen9.write(
        bytes(gen9.SIZE_PARTY), nickname="Egg", current_hp=11, tera_type_original=TERA_EMPTY,
        tera_type_override=TERA_EMPTY, language=2, level=1, stats=(11, 5, 5, 5, 5, 5)))


def boss_record(raid):
    """-> the boss's encrypted party record."""
    return gen9.encrypt(gen9.write(bytes(gen9.SIZE_PARTY), **raid.boss))


def raid_point(raid, rewards=None, name=POINT_NAME):
    """-> the 0x3e8-byte RaidPoint: identity, stars and level, the boss's HP coefficient and its
    37-word action profile, reward rows every player receives, the summary. Unknown words stay
    zero."""
    rows = raid.rewards if rewards is None else tuple(rewards)
    if len(rows) > REWARD_ROWS:
        raise ValueError(f"a RaidPoint holds at most {REWARD_ROWS} reward rows")
    out = bytearray(POINT_SIZE)
    encoded = name.encode("ascii")
    if not encoded.startswith(b"RaidPoint_") or len(encoded) > 23:
        raise ValueError(f"a RaidPoint name is RaidPoint_ and at most 13 more characters, not {name!r}")
    out[:len(encoded)] = encoded
    out[0x18] = 0x40
    struct.pack_into("<IIII", out, 0x20, raid.stars, 0, 1, raid.boss["level"])
    struct.pack_into("<37I", out, 0x4C, *raid.row["boss_desc"])
    for index, (item, quantity) in enumerate(rows):
        struct.pack_into("<IIII", out, POINT_REWARDS + index * 16, item, quantity, 0, SUBJECT_ALL)
    struct.pack_into("<7I", out, POINT_SUMMARY, raid.stars, gen9.internal_index(raid.species),
                     raid.boss["form"], raid.boss["gender"], raid.boss["level"], 0, raid.tera_type)
    struct.pack_into("<I", out, 0x3E0, CONTENT_STANDARD)
    return bytes(out)


def bootstrap(raid, participants, rewards=None, name=POINT_NAME):
    """-> the 0xaa0 plaintext: up to four party records, empty slots, the boss, the RaidPoint."""
    if len(participants) > PARTICIPANTS:
        raise ValueError(f"a raid has at most {PARTICIPANTS} participants")
    records = [gen9.encrypt(gen9.load(p)) for p in participants]
    records += [empty_participant()] * (PARTICIPANTS - len(records))
    return b"".join(records) + boss_record(raid) + raid_point(raid, rewards, name)


def bootstrap_message(plain, counter=FIRST_COUNTER + 10):
    if len(plain) != BOOTSTRAP_SIZE:
        raise ValueError(f"a bootstrap is {BOOTSTRAP_SIZE} bytes, not {len(plain)}")
    return message(KEY_LOBBY, KIND_BOOTSTRAP, 1, counter, lz4.compress(plain),
                   compression=COMPRESSION_LZ4, size=len(plain))


class RaidHost:
    """The host's side of one console's raid: twenty messages on 0x80 port 0, each released by the
    console's previous step. `actions` -> [("app", seq, flags, lowest, payload) | ("net",) |
    ("session",)]; the launcher reports the console's messages and its Net and Session acks."""

    def __init__(self, raid, pokemon_record, rewards=None):
        self.raid = raid
        self.pokemon = gen9.load(pokemon_record)
        self.rewards = None if rewards is None else tuple(rewards)
        raid_point(raid, self.rewards)          # a list that does not fit raises before the radio
        self.guest = None
        self.seen = {}                          # milestone -> when the console reached it
        self.sent = {}                          # our sequence -> when it left
        self.accepted_at = None
        self.net_at = self.session_at = None
        self.done_at = None
        self.whole = None

    def accepted(self, now):
        """The console's port-2 join was answered: the lobby clock starts."""
        if self.accepted_at is None:
            self.accepted_at = now

    def on_message(self, payload, now):
        """A message the console sent on 0x80 port 0, inflated."""
        payload = bytes(payload)
        record = pokemon_of(payload)
        if record is not None:
            self.guest = record
            self._reach("guest_lobby", now)
        if state_of(payload) == STATE_STARTED and 10 in self.sent:
            self._reach("guest_start", now)
        if payload[:4] == CONSOLE_LOADING and 12 in self.sent:
            self._reach("loading", now)
        if payload[:4] == CONSOLE_LOADED and 12 in self.sent:
            self._reach("loaded", now)
        if payload[:4] == BATTLE and 13 in self.sent:
            self._reach("battle", now)

    def net_acked(self, now):
        if self.net_at is not None:
            self._reach("net_ack", now)

    def session_acked(self, now):
        if self.session_at is not None:
            self._reach("session_ack", now)

    def _reach(self, milestone, now):
        self.seen.setdefault(milestone, now)

    def _passed(self, *milestones, now):
        times = [self.seen[m] for m in milestones if m in self.seen]
        return bool(times) and now >= min(times) + GATE_MARGIN

    def _lobby(self):
        counters = iter(range(FIRST_COUNTER, FIRST_COUNTER + 10))
        n = lambda: next(counters)
        return [(FIRST, streams.compress(descriptor(n(), self.raid)), 1),
                (COMPLETE, state(n(), STATE_IDLE, initial=True), 1),
                (COMPLETE, pokemon(n(), self.pokemon), 1),
                (COMPLETE, countdown(n(), 0x91), None),
                (COMPLETE, countdown(n(), 0x90), None),
                (COMPLETE, countdown(n(), 0x8F), None),
                (COMPLETE_ZLIB, streams.compress(state(n(), STATE_READY)), None),
                (COMPLETE, countdown(n(), 0x8E), None),
                (COMPLETE, countdown(n(), 0x8D), None),
                (COMPLETE_ZLIB, streams.compress(state(n(), STATE_START)), None)]

    def _ready(self, seq, now):
        """-> whether message `seq` may leave now."""
        if seq - 1 not in self.sent and seq > 1:
            return False
        if seq <= 10:
            if seq in (1, 7, 10) and not self._passed("guest_lobby", now=now):
                return False
            return now >= self.accepted_at + LOBBY_AT[seq - 1]
        if seq == 11:
            return self.guest is not None and self._passed("session_ack", now=now)
        if seq == 12:
            return True
        if seq == 13:
            return self._passed("loading", "loaded", now=now)
        if seq == 14:
            return self._passed("loaded", now=now)
        if seq == 15:
            return self._passed("battle", now=now)
        return now >= self.sent[15] + HANDOFF_AT[seq - 15]

    def _message(self, seq):
        if seq <= 10:
            return self._lobby()[seq - 1]
        if seq in (11, 12):
            if self.whole is None:
                self.whole = bootstrap_message(bootstrap(self.raid, (self.pokemon, self.guest),
                                                         self.rewards))
            cut = min(BOOTSTRAP_FRAGMENT, len(self.whole) - 1)
            if seq == 11:
                return FRAGMENT_START, self.whole[:cut], None
            return FRAGMENT_END_ZLIB, streams.compress(self.whole[cut:]), 11
        if seq == 13:
            return COMPLETE, LOADED, None
        if seq == 14:
            return COMPLETE, BATTLE_READY, None
        return COMPLETE_ZLIB, streams.compress(HANDOFF[seq - 15]), HANDOFF_LOWEST[seq - 15]

    def actions(self, now):
        if self.accepted_at is None:
            return []
        out = []
        seq = len(self.sent) + 1
        while seq <= 20 and self._ready(seq, now):
            flags, payload, lowest = self._message(seq)
            out.append(("app", seq, flags, seq if lowest is None else lowest, payload))
            self.sent[seq] = now
            seq += 1
        if seq > 20 and self.done_at is None:
            self.done_at = now + LINGER
        if ("net_ack" not in self.seen and self._passed("guest_start", now=now)
                and (self.net_at is None or now >= self.net_at + RETRY)):
            self.net_at = now
            out.append(("net",))
        if ("session_ack" not in self.seen and self._passed("net_ack", now=now)
                and (self.session_at is None or now >= self.session_at + RETRY)):
            self.session_at = now
            out.append(("session",))
        return out


class RaidGuest:
    """The guest's side: its lobby state and Pokemon, Ready after `ready_delay`, and the answer to
    the host's start. `on_message` takes the host's messages on 0x80 port 0, inflated; `tick`
    -> [(flags, payload)] to send there in order."""

    def __init__(self, pokemon_record, ready_delay=2.0):
        self.pokemon = gen9.load(pokemon_record)
        self.ready_delay = ready_delay
        self.lobby_at = None
        self.counter = 0
        self.ready_sent = self.started = False
        self.start_seen = False

    def _next(self):
        self.counter += 1
        return self.counter

    def lobby(self, now):
        """-> the two messages that make the guest a lobby participant."""
        self.lobby_at = now
        return [(FIRST, streams.compress(state(self._next(), STATE_IDLE))),
                (COMPLETE, pokemon(self._next(), self.pokemon))]

    def on_message(self, payload):
        if state_of(bytes(payload)) == STATE_START:
            self.start_seen = True

    def tick(self, now):
        out = []
        if self.lobby_at is not None and not self.ready_sent and now >= self.lobby_at + self.ready_delay:
            self.ready_sent = True
            out.append((COMPLETE_ZLIB, streams.compress(state(self._next(), STATE_READY))))
        if self.ready_sent and self.start_seen and not self.started:
            self.started = True
            out.append((COMPLETE_ZLIB, streams.compress(state(self._next(), STATE_STARTED))))
        return out

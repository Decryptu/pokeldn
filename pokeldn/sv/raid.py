"""Generated Scarlet/Violet raid application flow on broadcast reliable port 0.

This is the raid counterpart to :mod:`pokeldn.sv.trade`: it constructs application
messages from encounter/player state and exposes the client-driven transitions.  It
does not own Pia Session, Net, channel setup, reliable sequence allocation, or ACKs.
"""

from dataclasses import dataclass
import struct

from pokeldn import gen9
from pokeldn.ldn import reliable5
from pokeldn.sv import streams


PREFIX_RAID = 0x3380
TYPE_DESCRIPTOR = 0x012C
TYPE_STATE = 0x012D
TYPE_POKEMON = 0x012E
TYPE_COUNTDOWN = 0x0130

FLAGS_COMPLETE = (reliable5.FLAG_APPLICATION_DATA
                  | reliable5.FLAG_MESSAGE_START
                  | reliable5.FLAG_MESSAGE_END)
FLAGS_COMPLETE_ZLIB = FLAGS_COMPLETE | reliable5.FLAG_ZLIB
FLAGS_FIRST = FLAGS_COMPLETE_ZLIB | reliable5.FLAG_IS_INITIALIZED
FLAGS_FRAGMENT_START = (reliable5.FLAG_APPLICATION_DATA
                        | reliable5.FLAG_MESSAGE_START)
FLAGS_FRAGMENT_END_ZLIB = (reliable5.FLAG_APPLICATION_DATA
                           | reliable5.FLAG_MESSAGE_END
                           | reliable5.FLAG_ZLIB)

# Retail's sequence-11 boundary. The second fragment remains present when an
# unusually compressible generated RaidPoint makes the application shorter.
BOOTSTRAP_SPLIT = 1395


@dataclass(frozen=True)
class RaidMessage:
    delay: float
    flags: int
    payload: bytes
    lowest_pending: int | None = None


def serialized(message_type, value, body, *, compression=0, tail=b"\0\0\0\0"):
    """Build the common 0x8033 application envelope used by lobby messages."""
    body = bytes(body)
    tail = bytes(tail)
    if len(tail) != 4:
        raise ValueError("a serialized application tail must be four bytes")
    return (struct.pack("<HHHII", PREFIX_RAID, message_type, value,
                        compression, len(body)) + tail + body)


def descriptor(metadata, profile, *, value=0x0105):
    """Build the compact raid description shown in the lobby."""
    body = struct.pack(
        "<11I", 0, int(metadata["species"]), int(profile.get("form", 0)), 0,
        int(metadata["stars"]), int(metadata["tera_type"]),
        int(profile.get("gender", 0)), int(metadata["encounter_identifier"]),
        0, 0x33, 0)
    return serialized(TYPE_DESCRIPTOR, value, body)


def state(value, state_value, *, initial=False):
    """Build the host lobby state record (0x012d)."""
    if initial:
        body = bytes.fromhex("080000000400040004000000")
    else:
        body = (bytes.fromhex("0c000000000006000c00040006000000")
                + struct.pack("<II", state_value, 0))
    return serialized(TYPE_STATE, value, body)


def pokemon(value, party_pk9):
    """Build the host's complete encrypted party-PK9 lobby announcement."""
    raw = bytes(party_pk9)
    if len(raw) != gen9.SIZE_PARTY:
        raise ValueError(f"a raid player Pokemon must be {gen9.SIZE_PARTY} bytes")
    sealed = gen9.encrypt(gen9.load(raw))
    return serialized(TYPE_POKEMON, value, sealed)


def countdown(value, counter):
    body = (bytes.fromhex("0c000000000006000800040006000000")
            + struct.pack("<I", counter))
    return serialized(TYPE_COUNTDOWN, value, body)


def load_transition(kind):
    """Build the two application transitions observed after the bootstrap."""
    if kind == "load":
        return bytes.fromhex("320173000400000000000800000000006f740100000001000000")
    if kind == "battle":
        return bytes.fromhex("803493010400000000000400000000000000ed030000")
    raise ValueError(f"unknown raid transition {kind!r}")


def battle_handoff():
    """Build the six generic battle-start records through the sequence-20 handoff.

    Their envelope and small state bodies are stable across the compared retail
    captures. Two opaque runtime tokens retain the retail-validated canonical
    values until their producers are identified in the game binary.
    """
    return (
        bytes.fromhex("7b0013270000010000000200000020000000010000000000000001000000000000000000000000000000050507265a000000"),
        bytes.fromhex("7b00132700000300000005000000240000004600000000000000000000000000000000000000000000000500ceaf2900000000000000"),
        bytes.fromhex("7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000501000000000000"),
        bytes.fromhex("7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000503000000000000"),
        bytes.fromhex("7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000504000000000000"),
        bytes.fromhex("7b00132700000300000005000000200000000200000000000000010000000000000000000000000000000500000000000000"),
    )


class RaidStage:
    """Pure generated host-side application flow, analogous to ``TradeStage``.

    The host calls the named transition methods after observing the corresponding
    client/session milestone. Reliable IDs are deliberately not stored here.
    """

    def __init__(self, metadata, profile, host_pokemon, bootstrap_application):
        self.metadata = dict(metadata)
        self.profile = dict(profile)
        self.host_pokemon = bytes(host_pokemon)
        self.bootstrap_application = bytes(bootstrap_application)
        if len(self.bootstrap_application) < 2:
            raise ValueError("a raid bootstrap application needs two fragments")
        self._sent = set()

    def _once(self, name, messages):
        if name in self._sent:
            return []
        self._sent.add(name)
        return list(messages)

    def lobby(self):
        values = iter(range(0x0105, 0x010F))
        messages = [
            RaidMessage(0.0, FLAGS_FIRST,
                        streams.compress(descriptor(self.metadata, self.profile,
                                                    value=next(values))), 1),
            RaidMessage(0.0, FLAGS_COMPLETE, state(next(values), 0x18, initial=True), 1),
            RaidMessage(0.0, FLAGS_COMPLETE,
                        pokemon(next(values), self.host_pokemon), 1),
        ]
        for delay, counter in ((0.726, 0x91), (1.758, 0x90), (2.748, 0x8F)):
            messages.append(RaidMessage(delay, FLAGS_COMPLETE,
                                        countdown(next(values), counter)))
        messages.append(RaidMessage(3.192, FLAGS_COMPLETE_ZLIB,
                                    streams.compress(state(next(values), 1))))
        for delay, counter in ((3.757, 0x8E), (4.787, 0x8D)):
            messages.append(RaidMessage(delay, FLAGS_COMPLETE,
                                        countdown(next(values), counter)))
        messages.append(RaidMessage(5.393, FLAGS_COMPLETE_ZLIB,
                                    streams.compress(state(next(values), 12))))
        return self._once("lobby", messages)

    def bootstrap(self):
        boundary = min(BOOTSTRAP_SPLIT, len(self.bootstrap_application) - 1)
        first = self.bootstrap_application[:boundary]
        second = self.bootstrap_application[boundary:]
        return self._once("bootstrap", (
            RaidMessage(0.0, FLAGS_FRAGMENT_START, first),
            RaidMessage(0.0, FLAGS_FRAGMENT_END_ZLIB, streams.compress(second), 11),
        ))

    def loaded(self):
        return self._once("loaded", (
            RaidMessage(0.0, FLAGS_COMPLETE, load_transition("load")),
        ))

    def battle_ready(self):
        return self._once("battle_ready", (
            RaidMessage(0.0, FLAGS_COMPLETE, load_transition("battle")),
        ))

    def handoff(self):
        delays = (0.0, 0.0, 0.101, 0.121, 0.161, 0.181)
        lows = (None, 15, 15, 17, 18, None)
        messages = [RaidMessage(delay, FLAGS_COMPLETE_ZLIB,
                                streams.compress(payload), low)
                    for delay, low, payload in zip(delays, lows, battle_handoff())]
        return self._once("handoff", messages)

    def events(self):
        """Return the complete generated sequence-1..20 compatibility schedule."""
        groups = (self.lobby(), self.bootstrap(), self.loaded(),
                  self.battle_ready(), self.handoff())
        offsets = (0.0, 7.068, 12.180, 22.292, 40.528)
        output = []
        sequence = 1
        for offset, group in zip(offsets, groups):
            for message in group:
                low = sequence if message.lowest_pending is None else message.lowest_pending
                output.append((offset + message.delay, sequence, message.flags,
                               low, message.payload))
                sequence += 1
        if sequence != 21:
            raise AssertionError("generated raid opening must contain sequences 1 through 20")
        return output


class JoinerRaidStage:
    """Generated joiner-side lobby state, Pokémon, Ready, and Start ACK."""

    def __init__(self, party_pk9):
        self.party_pk9 = bytes(party_pk9)
        if len(self.party_pk9) != gen9.SIZE_PARTY:
            raise ValueError(f"a raid player Pokemon must be {gen9.SIZE_PARTY} bytes")
        self._sent = set()

    def _once(self, name, messages):
        if name in self._sent:
            return []
        self._sent.add(name)
        return list(messages)

    def lobby(self):
        """Return the initial state and selected-Pokémon messages (reliable IDs 1/2)."""
        return self._once("lobby", (
            RaidMessage(0.0, FLAGS_FIRST,
                        streams.compress(state(1, 0x18))),
            RaidMessage(0.0, FLAGS_COMPLETE, pokemon(2, self.party_pk9)),
        ))

    def ready(self):
        """Return the state-1 Ready message following the two lobby records."""
        return self._once("ready", (
            RaidMessage(0.0, FLAGS_COMPLETE_ZLIB,
                        streams.compress(state(3, 0x01))),
        ))

    def start_ack(self):
        """Return state 0x0d after the retail host publishes state 0x0c."""
        return self._once("start_ack", (
            RaidMessage(0.0, FLAGS_COMPLETE_ZLIB,
                        streams.compress(state(4, 0x0D))),
        ))

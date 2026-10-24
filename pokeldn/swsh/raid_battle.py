"""A Max Raid guest's side of the battle on 0x7C, as an emulated Shield guest played it
(docs/swsh_raid.md, The battle). The host is the battle server; the guest answers.

    port 0  sync 80 (ping, pingReply, pingSynced), 10000 (our seat), 20000 (the battle commands)
    port 1  40000, the content-0 framework: base 10000 / 20000 state pairs
"""
import struct

from pokeldn.swsh.trade import field, field_varint, message, _read_fields

SYNC = 80
SEAT = 10000
BATTLE = 20000
FRAMEWORK = 40000
PING, PING_REPLY, PING_SYNCED = 1, 2, 3

# The command types read from a won emulated raid: 2 asks for the guest's action, 0x21 ends.
ACTION_REQUEST, FAINTED, BATTLE_END = 0x02, 0x04, 0x21
# A Max Lair guest's action: entry 1 `01` then 0xff, entry 2 the move, the rest 0xff. Its answer to a
# type 4 carrying `01 00 ff ff ff ff`, after its Pokemon fainted, is that action with entry 2 zero.
LAIR_ACTION = bytes.fromhex("01ffffffffffffff") + bytes(8) + b"\xff" * 72
FAINTED_ASK = bytes.fromhex("0100ffffffff")

# The emulated guest's action, both turns the same: 11 eight-byte entries (docs/swsh_raid.md).
ACTION = bytes.fromhex(
    "0102000000000000c1e806000000000002010000000800000201000020000000020100020000000002010000"
    "0008000002020000000000000201008000000000020200000000000002020000000000000201010000000000")

# Entry 2 of the action: move id << 13 | target << 8 | 0xc1. Water Gun, Pound and Bind against the
# boss used target 8, Growl 2 (docs/swsh_raid.md, The action).
SINGLE_TARGET = 8


def action(move, target=SINGLE_TARGET, template=ACTION):
    """-> the 88-byte action using `move` (a move id) against `target`; `template` LAIR_ACTION in a
    Dynamax Adventure."""
    if not 0 < move < 1 << 11:
        raise ValueError(f"move id {move} out of range")
    entry = struct.pack("<I", move << 13 | target << 8 | 0xC1).ljust(8, b"\0")
    return template[:8] + entry + template[16:]


def sync(which):
    return message(SYNC, field(which, b""))


def framework(base, station, clock, body):
    inner = b""
    if base:
        inner += field_varint(2, base)
    if station is not None:
        inner += field_varint(3, station)
    inner += field_varint(4, clock) + field(5, body)
    return message(FRAMEWORK, field(1, inner))


def parse_framework(payload):
    """-> {base, station, clock, body} of a 40000 message, or None."""
    if len(payload) < 4 or struct.unpack_from("<I", payload, 0)[0] != FRAMEWORK:
        return None
    outer = _read_fields(payload[4:])
    if not isinstance(outer.get(1), bytes):
        return None
    f = _read_fields(outer[1])
    return {"base": f.get(2, 0), "station": f.get(3), "clock": f.get(4, 0), "body": f.get(5, b"")}


def seat(station, slot, version):
    return message(SEAT, field(3, field_varint(1, station) + field_varint(2, slot)
                               + field_varint(3, version)))


def battle_message(sender, slot, counter, data):
    inner = field_varint(1, sender)
    if slot:
        inner += field_varint(2, slot)
    if counter:
        inner += field_varint(3, counter)
    return message(BATTLE, field(1, inner + field(4, data)))


def parse_battle(payload):
    """-> ("command", sender, counter, data) or ("state", fields) for a 20000 message, or None."""
    if len(payload) < 4 or struct.unpack_from("<I", payload, 0)[0] != BATTLE:
        return None
    outer = _read_fields(payload[4:])
    if isinstance(outer.get(1), bytes):
        f = _read_fields(outer[1])
        return ("command", f.get(1, 0), f.get(3, 0), f.get(4, b""))
    if isinstance(outer.get(3), bytes):
        return ("state", _read_fields(outer[3]))
    return None


class Guest:
    """Feed every host 0x7C message to `receive(port, payload)`; it returns [(port, payload)] to send.
    `clock()` gives our framework clock; `slot` is our seat (the host is 0)."""

    def __init__(self, station, slot=1, clock=None, action=ACTION):
        self.station, self.slot, self.action = station, slot, action
        self.clock = clock or (lambda: self.host_clock)
        self.host_clock = 0x680
        self.started = False
        self.seat_sent = False
        self.ping_sent = False

    def _pairs(self, advance=0):
        c = self.clock() + advance
        return [(1, framework(SEAT, self.station, c, bytes(4))),
                (1, framework(BATTLE, self.station, c, bytes.fromhex("000018fc")))]

    def receive(self, port, payload):
        out = []
        if payload == sync(PING):
            out += [(0, sync(PING)), (0, sync(PING_REPLY))]
        elif payload == sync(PING_SYNCED):
            # The pairs follow our pingSynced; the emulated guest sent three, its clock 2 apart.
            out.append((0, sync(PING_SYNCED)))
            if not self.started:
                self.started = True
                for step in range(3):
                    out += self._pairs(2 * step)
        fw = parse_framework(payload)
        if fw is not None:
            self.host_clock = max(self.host_clock, fw["clock"])
            body = fw["body"]
            if fw["base"] == 0 and len(body) == 16 and not self.seat_sent:
                # The host lists its own seat: constant id, slot, then the version byte we echo.
                self.seat_sent = True
                out.append((0, seat(self.station, self.slot, body[9])))
            elif fw["base"] == 8 and not self.ping_sent:
                self.ping_sent = True
                out.append((0, message(SEAT, field(1, b""))))
            elif (fw["base"] == BATTLE and fw["station"] is not None and len(body) == 4
                  and body not in (bytes(4), bytes.fromhex("000018fc"))):
                out.append((1, framework(BATTLE, self.station, self.clock(), body)))
        got = parse_battle(payload)
        if got and got[0] == "command" and got[1] == 1 and len(got[3]) >= 8:
            counter, data = got[2], got[3]
            serial, kind, _, x = struct.unpack_from("<HHHH", data, 0)
            if kind == ACTION_REQUEST:
                out.append((0, message(BATTLE, field(3, field_varint(1, 2)
                                                     + field_varint(2, self.slot)))))
                out.append((0, battle_message(2, self.slot, counter,
                                              struct.pack("<HHHH", serial, kind, len(self.action), x)
                                              + self.action)))
            elif kind == FAINTED and data[8:14] == FAINTED_ASK:
                out.append((0, battle_message(2, self.slot, counter,
                                              struct.pack("<HHHH", serial, kind, len(LAIR_ACTION), x)
                                              + LAIR_ACTION)))
            elif kind == BATTLE_END:
                out.append((0, battle_message(1, self.slot, 0,
                                              struct.pack("<HHHH", 0, 0x1e, 0, 0x2f))))
            else:
                out.append((0, battle_message(2, self.slot, counter,
                                              struct.pack("<HHHH", serial, kind, 4, x) + bytes(4))))
        return out


SERVER_VERSION = 0x6E                 # every copy's ServerVersion version (main 0x8b1778)


def server_record(station, client_id, version=SERVER_VERSION):
    """A framework object 0..7 body as the emulated host published it: station, client id, version,
    valid, then `0a` and four zero bytes (docs/swsh_raid.md, Which station serves)."""
    return struct.pack("<QBBBB", station, client_id, version, 1, 0x0A) + bytes(4)


class Master:
    """The station that publishes the framework objects, here a battle client: object k is console
    k's record, so `consoles[0]` serves and we answer as the last client. The steps follow the
    recorded host's framework; the battle itself is answered by a `Guest`. `receive` returns
    (port, payload, destination), destination None for every console."""

    def __init__(self, station, consoles, clock=None, log=print, action=ACTION):
        self.station, self.consoles = station, list(consoles)
        self.server, self.slot = self.consoles[0], len(self.consoles)
        self.log = log
        self.t_clock = clock or (lambda: 0x680)
        self.guest = Guest(station, self.slot, clock=self.t_clock, action=action)
        self.guest.started = self.guest.seat_sent = self.guest.ping_sent = True
        self.replied = set()              # consoles that answered our ping
        self.synced = False
        self.step = 0                     # the anonymous base-20000 counter we published
        self.ours = None                  # our station's last base-20000 body
        self.mirrors = {}                 # console -> its last base-20000 body
        self.mirrored = {bytes(4), bytes.fromhex("000018fc")}
        self.empty_sent = False

    def start(self):
        return [(0, sync(PING), None)]

    def _ours(self, body):
        self.ours = body
        return (1, framework(BATTLE, self.station, self.t_clock(), body), None)

    def _anon(self, step):
        self.step = step
        return (1, framework(BATTLE, None, self.t_clock(), struct.pack("<H", step)), None)

    def _setup(self):
        c = self.t_clock()
        out = [self._anon(0), (1, framework(SEAT, self.station, c, bytes(4)), None),
               self._ours(bytes.fromhex("000018fc"))]
        for k, console in enumerate(self.consoles):
            out.append((1, framework(k, None, c, server_record(console, k)), None))
        out += [self._ours(bytes.fromhex("00000100")),
                (1, framework(self.slot, None, c, server_record(self.station, self.slot)), None),
                (0, seat(self.station, self.slot, SERVER_VERSION), None)]
        self.log(f"[raid] -> framework objects 0..{self.slot - 1} (the consoles) and {self.slot} (us)")
        return out

    def receive(self, port, payload, src=None):
        src = self.server if src is None else src
        out = []
        if payload == sync(PING_REPLY) and src not in self.replied:
            self.replied.add(src)
            out.append((0, sync(PING_SYNCED), src))
            if not self.synced and self.replied >= set(self.consoles):
                self.synced = True
                out += self._setup()
            return out
        fw = parse_framework(payload)
        if fw is not None:
            self.log(f"[raid] <- fw base={fw['base']} station={fw['station'] and hex(fw['station'])} "
                     f"body={fw['body'].hex()}")
            # The server publishes object 8 (24 bytes, a seed); a client answers EmptyCommand.
            if fw["base"] == 8 and fw["station"] is None and not self.empty_sent:
                self.empty_sent = True
                out.append((0, message(SEAT, field(1, b"")), src))
            if fw["station"] in self.consoles and fw["base"] == BATTLE and len(fw["body"]) == 4:
                body = fw["body"]
                self.mirrors[fw["station"]] = body
                if body != self.ours and body not in self.mirrored:
                    self.mirrored.add(body)
                    out.append((1, framework(BATTLE, self.station, self.t_clock(), body), None))
                # The recorded host's barrier: once every console mirrors our body, the next step.
                if all(self.mirrors.get(c) == self.ours for c in self.consoles):
                    nxt = {"00000100": lambda: [self._anon(1), self._ours(bytes.fromhex("01000100"))],
                           "01000100": lambda: [self._ours(bytes.fromhex("01000200"))],
                           "01000200": lambda: [self._anon(2), self._ours(bytes.fromhex("02000200"))]}
                    out += nxt.get(self.ours.hex(), list)()
            return out
        if parse_battle(payload) is None and payload not in (sync(PING), sync(PING_SYNCED)):
            self.log(f"[raid] <- {port} {payload.hex()[:80]}")
        return out + [(p, x, src) for p, x in self.guest.receive(port, payload)]

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
ACTION_REQUEST, BATTLE_END = 0x02, 0x21

# The emulated guest's action, both turns the same: 11 eight-byte entries (docs/swsh_raid.md).
ACTION = bytes.fromhex(
    "0102000000000000c1e806000000000002010000000800000201000020000000020100020000000002010000"
    "0008000002020000000000000201008000000000020200000000000002020000000000000201010000000000")

# Entry 2 of the action: move id << 13 | target << 8 | 0xc1. Water Gun, Pound and Bind against the
# boss used target 8, Growl 2 (docs/swsh_raid.md, The action).
SINGLE_TARGET = 8


def action(move, target=SINGLE_TARGET):
    """-> the 88-byte action using `move` (a move id) against `target`."""
    if not 0 < move < 1 << 11:
        raise ValueError(f"move id {move} out of range")
    entry = struct.pack("<I", move << 13 | target << 8 | 0xC1).ljust(8, b"\0")
    return ACTION[:8] + entry + ACTION[16:]


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
            elif kind == BATTLE_END:
                out.append((0, battle_message(1, self.slot, 0,
                                              struct.pack("<HHHH", 0, 0x1e, 0, 0x2f))))
            else:
                out.append((0, battle_message(2, self.slot, counter,
                                              struct.pack("<HHHH", serial, kind, 4, x) + bytes(4))))
        return out

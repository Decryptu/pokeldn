"""A joiner leaving a Let's Go session the way a retail console does, against a scripted host
(docs/lgpe_session.md, "A joiner leaving")."""
import struct

from pokeldn.ldn import clone, reliable3, station9
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn.station_protocol import DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE
from pokeldn.lgpe.leave import Leaver


def words(data):
    return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]


def make():
    part = clone.Participant(100.0, dest=1, own=2, station=1)
    part.held.update({1, 2, 3})
    part.shared[3] = b"\x01\0\0\0\x02\0\0\0\x02\0\0\0" + struct.pack("<I", 10) + b"\x02\0\0\0"
    return part, Leaver(part, 3, 11, 2, 2, station=1, host_bit=1)


def run(leaver, t_from, t_to, step=0.005):
    out = []
    t = t_from
    while t < t_to:
        out += leaver.poll(t)
        t += step
    return out


def test_the_two_state_4_records_then_the_releases_then_the_leave_request():
    part, lv = make()
    out = run(lv, 100.0, 100.5)
    recs = [clone.parse_data_message(p) for p, proto, port in out if proto == clone.PROTOCOL]
    assert len(recs) == 1 and words(recs[0]["record"]["data"]) == [4, 0, 3, 11, 2]
    out = run(lv, 100.5, 101.2)
    recs = [clone.parse_data_message(p) for p, proto, port in out if proto == clone.PROTOCOL]
    assert len(recs) == 1 and words(recs[0]["record"]["data"]) == [4, 3, 4, 11, 2]
    out = run(lv, 101.2, 101.6)
    ends = [clone.parse_command(p) for p, proto, port in out if proto == clone.PROTOCOL]
    assert [(c["ctype"], c["station"], c["clone_id"], c["dest"]) for c in ends] == \
        [(4, 0xFD, 1, 1), (3, 0xFD, 0, 1), (4, 0xFD, 2, 1), (4, 0xFD, 3, 1)]
    # unacknowledged, each goes again every 100 ms; acknowledged, it stops
    out = run(lv, 101.6, 101.65)
    ends = [clone.parse_command(p)["clone_id"] for p, proto, port in out if proto == clone.PROTOCOL]
    assert sorted(ends) == [0, 1, 2, 3]
    for cid in (1, 0, 2, 3):
        lv.receive(clone.PROTOCOL, clone.build_command(clone.COMMAND_END_ACK, 4, 0xFD, cid, 9, 2),
                   101.65)
    out = run(lv, 101.65, 104.05)
    assert [p for p, proto, port in out if proto == clone.PROTOCOL] == []
    assert [p for p, proto, port in out if proto == mp.PROTOCOL] == []
    out = run(lv, 104.1, 104.3)
    leaves = [(p, port) for p, proto, port in out if proto == mp.PROTOCOL]
    assert len(leaves) == 1 and leaves[0][1] == 1
    r = reliable3.parse(leaves[0][0])
    assert r["payload"] == bytes([mp.LEAVE_REQUEST, 1]) and r["sequence"] == reliable3.FIRST_SEQUENCE
    # repeated every half second until the response
    out = run(lv, 104.3, 105.3)
    assert len([1 for p, proto, port in out if proto == mp.PROTOCOL]) == 2
    lv.receive(mp.PROTOCOL, bytes([mp.LEAVE_RESPONSE, 1]), 105.3)
    out = run(lv, 105.3, 106.3)
    assert [p for p, proto, port in out if proto == mp.PROTOCOL] == []
    assert not lv.done
    # the host closes the connection: answered, done
    ans = lv.receive(station9.PROTOCOL, bytes([DISCONNECTION_REQUEST]), 106.3)
    assert ans == [(bytes([DISCONNECTION_RESPONSE]), station9.PROTOCOL, 0)]
    assert lv.done


def test_a_host_that_never_closes_gets_our_disconnection_request_after_five_seconds():
    part, lv = make()
    run(lv, 100.0, 101.8)
    for cid in (1, 0, 2, 3):
        lv.receive(clone.PROTOCOL, clone.build_command(clone.COMMAND_END_ACK, 4, 0xFD, cid, 9, 2),
                   101.8)
    run(lv, 101.8, 104.4)
    lv.receive(mp.PROTOCOL, bytes([mp.LEAVE_RESPONSE, 1]), 104.4)
    out = run(lv, 104.4, 109.3)
    assert [p for p, proto, port in out if proto == station9.PROTOCOL] == []
    out = run(lv, 109.3, 109.5)
    assert [p for p, proto, port in out if proto == station9.PROTOCOL] == [bytes([DISCONNECTION_REQUEST])]
    lv.receive(station9.PROTOCOL, bytes([DISCONNECTION_RESPONSE]), 109.5)
    assert lv.done

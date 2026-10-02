"""A joiner leaving a Let's Go session the way a retail console does, against a scripted host
(docs/lgpe_session.md, "A joiner leaving")."""
import struct

from pokeldn.ldn import clone, reliable3, station9
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn.station_protocol import DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE
from pokeldn.lgpe.leave import Leaver, host_departure


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
    out = run(lv, 104.3, 105.3)
    assert len([1 for p, proto, port in out if proto == mp.PROTOCOL]) == 2
    lv.receive(mp.PROTOCOL, bytes([mp.LEAVE_RESPONSE, 0]), 105.3)
    out = run(lv, 105.3, 105.4)
    assert [p for p, proto, port in out if proto == mp.PROTOCOL] == []
    # Our disconnection request follows the leave response at once; the host's own is answered.
    assert [p for p, proto, port in out if proto == station9.PROTOCOL] == [bytes([DISCONNECTION_REQUEST])]
    assert not lv.done
    ans = lv.receive(station9.PROTOCOL, bytes([DISCONNECTION_REQUEST]), 105.4)
    assert ans == [(bytes([DISCONNECTION_RESPONSE]), station9.PROTOCOL, 0)]
    assert lv.done


def test_a_host_that_never_answers_the_disconnection_is_given_two_seconds():
    part, lv = make()
    run(lv, 100.0, 101.8)
    for cid in (1, 0, 2, 3):
        lv.receive(clone.PROTOCOL, clone.build_command(clone.COMMAND_END_ACK, 4, 0xFD, cid, 9, 2),
                   101.8)
    run(lv, 101.8, 104.4)
    lv.receive(mp.PROTOCOL, bytes([mp.LEAVE_RESPONSE, 0]), 104.4)
    out = run(lv, 104.4, 106.3)
    assert [p for p, proto, port in out if proto == station9.PROTOCOL] == [bytes([DISCONNECTION_REQUEST])]
    assert not lv.done
    run(lv, 106.3, 106.6)
    assert lv.done


# A Let's Go host leaving, as an emulated pair recorded it: its migration start on the mesh reliable
# port, and the joiner's two answers (docs/lgpe_session.md, A host leaving).
HOST_MIGRATION_START = bytes.fromhex("0003000300000000fffff82ffffff82f0000000000000000440001")
JOINER_ACK = bytes.fromhex("000000000000000000000000fffff8300000000000000000")
# A retail host's START_HOST_MIGRATION, repeated every 0.3 s until no station is left.
START_HOST_MIGRATION = bytes.fromhex("01130000000000000000000000000000")


def test_a_leaving_hosts_migration_start_gets_the_emulated_joiners_answers():
    replies, leave = host_departure(mp.PROTOCOL, HOST_MIGRATION_START, 1)
    assert replies == [(JOINER_ACK, mp.PROTOCOL, 1), (b"\x48\x01", mp.PROTOCOL, 0)]
    assert not leave


def test_start_host_migration_leaves_the_network_and_nothing_else_does():
    from pokeldn.ldn import local_protocol as lp
    assert host_departure(lp.PROTOCOL, START_HOST_MIGRATION, 1) == ([], True)
    update = bytes.fromhex("011149000000000000000000040000004d461bb5")
    assert host_departure(lp.PROTOCOL, update, 1) == ([], False)
    leave_request = reliable3.build(b"\x04\x01", reliable3.FIRST_SEQUENCE, reliable3.FIRST_SEQUENCE)
    assert host_departure(mp.PROTOCOL, leave_request, 1) == ([], False)
    assert host_departure(mp.PROTOCOL, b"\x08\x00", 1) == ([], False)


def test_a_leave_response_naming_the_leaver_is_ignored_as_the_console_ignores_it():
    part, lv = make()
    lv.leave_sent = lv.leave_next = 100.0
    lv.receive(mp.PROTOCOL, bytes([mp.LEAVE_RESPONSE, 1]), 100.0)
    assert not lv.leave_answered
    lv.receive(mp.PROTOCOL, bytes([mp.LEAVE_RESPONSE, 0]), 100.0)
    assert lv.leave_answered


def test_after_the_consoles_clone_0_release_its_shared_copies_are_acked_not_answered():
    # Retail lgh76, host role: the console's release of clone 0, then its clone type 2 copy of
    # clone 6. Answered with our own copy, the console resent it every 100 ms and waited the 150
    # frames of main 0x116d38; acked, it released the clone and left in 0.11 s.
    release = bytes.fromhex("03830f6f03fd0000000000000000008b0001")
    copy = bytes.fromhex("03f30f7002010000000000060001785e52506260636664606000e27f71409a8119c2"
                         "61e081d200000000ffff0300283801bb")
    part = clone.Participant(100.0, dest=2, own=1, station=0)
    part.host_role = True
    before = part.receive(copy, 100.5)
    assert [m[1] for m in before] == [clone.STATE_DATA]
    part.receive(release, 101.0)
    after = part.receive(copy, 101.1)
    assert [m[1] for m in after] == [clone.STATE_ACK]
    ack = clone.parse_data_message(after[0])
    sent = clone.parse_data_message(copy)
    assert (ack["ctype"], ack["station"], ack["clone_id"]) == (1, 0xFD, 6)
    assert ack["record"]["station"] == sent["record"]["station"] == 1
    assert ack["record"]["clock"] == sent["record"]["clock"]


def test_a_vote_the_console_host_never_agrees_is_seen_and_an_agreed_one_is_not():
    # Retail lgp37: both stations at 1 1 1 on commit clone 4 and the console host's type 4 copy
    # left at A 0 until the player was locked out. Retail lgp35: the same vote, then its A 1 copy.
    from pokeldn.lgpe.leave import unagreed_vote
    zeros_t4 = bytes.fromhex("03f3281d04fd0000000000040002785e52d0636061660002260686ca3d0c0400"
                             "000000ffff030037c6018d")
    vote_37 = bytes.fromhex("03f3281f02000000000000040003785e52506260616600022051f99f11c880615e"
                            "060800000000ffff030029ce01d5")
    vote_35 = bytes.fromhex("03f311bb02000000000000040003785e52506260616600022011a4cc0864c03017"
                            "030400000000ffff0300145000cf")
    agreed_t4 = bytes.fromhex("03f311bd04fd0000000000040003785e52d06360616600022011a4ccc8801d70"
                              "0131480e000000ffff03001f7800da")
    stalled = clone.Participant(100.0, dest=1, own=2, station=1)
    stalled.receive(zeros_t4, 100.1)
    assert unagreed_vote(stalled) is None
    stalled.receive(vote_37, 100.2)
    assert unagreed_vote(stalled) == 4
    agreed = clone.Participant(100.0, dest=1, own=2, station=1)
    agreed.receive(vote_35, 100.2)
    assert unagreed_vote(agreed) == 4
    agreed.receive(agreed_t4, 100.25)
    assert unagreed_vote(agreed) is None


def test_a_new_copy_within_one_mesh_clock_tick_still_carries_a_newer_clock():
    # Retail lgp37: the console's zeros then its vote on commit clone 4, answered in one mesh clock
    # tick. Our vote went out under the clock of our zeros; the console keeps its stored copy for a
    # clock that is not newer (main 0x52184c), so its authority never saw our vote.
    zeros = bytes.fromhex("03f3281d02000000000000040003785e52506260616600022051b9970109f0426900"
                          "000000ffff030024340190")
    vote = bytes.fromhex("03f3281f02000000000000040003785e52506260616600022051f99f11c880615e06"
                         "0800000000ffff030029ce01d5")
    part = clone.Participant(100.0, dest=1, own=2, station=1)
    part.mesh_ms = 31231
    first = clone.parse_data_message(part.receive(zeros, 100.1)[0])["record"]
    second = clone.parse_data_message(part.receive(vote, 100.12)[0])["record"]
    assert words(second["data"])[:3] == [1, 1, 1]
    assert second["clock"] > first["clock"]

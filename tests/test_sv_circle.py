"""The Union Circle guest (docs/sv_union_circle.md): which network it takes and how it sits."""

import math
import random
import struct

import pytest
import trio

import sv_join
from pokeldn.ldn import channel_table, reliable5
from pokeldn.sv import circle, raid, streams
from test_sv_raid import HOST_IP, HOST_MAC, JOIN_IP, JOIN_MAC, Clock, RaidHostConsole


def test_a_circle_guest_takes_only_a_hosting_circle_s_scene_and_keeps_its_seat_for_the_run():
    ap = sv_join.build_parser()
    for argv, scene, hold in (([], circle.SCENE, 900), (["--scene-id", "4", "--hold", "30"], 4, 30)):
        args = ap.parse_args(["--union-circle", "--seconds", "900", *argv])
        sv_join.circle_guest(ap, args)
        assert (args.scene_id, args.hold) == (scene, hold)


def test_a_retail_host_s_first_circle_message_is_lua_message_100():
    # The first game message a retail Scarlet hosting a circle sent its new member.
    raw = bytes.fromhex("3201640001000000000018000000000000000c000000000006000c000400060000004e61bc"
                        "0000000000")
    assert circle.lua_message_id(raw) == 100
    assert circle.lua_message_id(raid.CONSOLE_STATE) is None


# What a retail host opens on 0x7c port 1 when its field is up: its player's keys, 0x1E to 0x2A.
FIELD_KEYS = bytes.fromhex(
    "b9010eb902b902290001b902b902230001b902b9022a0001b902b9021f0001b902b9021f0101b902b902200001b902"
    "b902240001b902b902250001b902b902260001b902b902260101b902b902210001b902b902210101b902b9021e0001"
    "b902b9021e0101")
# A retail host's declaration of its type-2 object and that object's state, on 0x7c port 0.
HOST_DECLARES = bytes.fromhex("1f0024000200")
HOST_STATE = bytes.fromhex("1e00020024000000000000000000b5170000000000000000803f0000803f0000803f00000000"
                           "00000000f593293f0000000084c73f3f1bedb144cc0c1643112f39c500000000")


class CircleHostConsole(RaidHostConsole):
    """The raid host's join, then a retail circle host's field: its field keys open on port 1 a
    second after the station list's ack, and on port 0 each of the guest's declarations answered
    with an ask, the guest's asks with its type-2 object's declaration and state."""

    def sendto(self, packet, addr):
        acked = self.list_acked
        super().sendto(packet, addr)
        if self.list_acked and not acked:
            self.data(1.0, 0x7C, 1, FIELD_KEYS, compressed=True)
        row = self.got[-1]
        if (row["protocol"], row["port"]) != (0x7C, 0) or "data" not in row:
            return
        body = row["data"]
        if body[:2] == bytes.fromhex("1f00"):
            self.data(0.05, 0x7C, 0, bytes.fromhex("1e000000") + body[2:4])
            if body[2:4] == bytes.fromhex("0100"):
                self.data(0.05, 0x7C, 0, HOST_DECLARES)
        elif body[:4] == bytes.fromhex("1e000000"):
            self.data(0.05, 0x7C, 0, HOST_STATE, compressed=True)


def run_guest(monkeypatch, host, hold, *extra):
    clock = host.clock

    async def wait_readable(_):
        host.tick()
        await trio.lowlevel.checkpoint()

    monkeypatch.setattr(sv_join, "time", clock)
    monkeypatch.setattr(sv_join, "make_socket", lambda *a: host)
    monkeypatch.setattr(trio.lowlevel, "wait_readable", wait_readable)
    ap = sv_join.build_parser()
    args = ap.parse_args(["--union-circle", "--ip-join", "--rtt-period", "0", "--hold", str(hold), *extra])
    sv_join.circle_guest(ap, args)
    assert not args.take_host
    return trio.run(sv_join.run_session, args, host.keys, HOST_IP, HOST_MAC, JOIN_IP, JOIN_MAC,
                    lambda **row: None)


def test_a_circle_guest_mirrors_the_host_s_table_and_sends_no_raid_lobby(monkeypatch):
    host = RaidHostConsole(Clock())
    seat = run_guest(monkeypatch, host, 12)
    assert not seat["raided"] and not seat["handed"]
    got = host.got
    assert any(r["protocol"] == 0x98 and r["payload"][0] == 0 for r in got)
    tables = [r for r in got if (r["protocol"], r["port"]) == (0x7C, 1) and "data" in r]
    # The whole table in one message: a circle guest does not split off the raid's keys.
    assert len(tables) == 1
    assert channel_table.parse(tables[0]["data"]) == channel_table.parse(raid.channel_table())
    # No port-2 join until the host announces on 0x80 port 2, which this one never does.
    assert not [r for r in got if (r["protocol"], r["port"]) == (0x7C, 2) and "data" in r]
    assert not [r for r in got if (r["protocol"], r["port"]) == (0x80, 0) and "data" in r]
    assert not [r for r in got if r["protocol"] == 0x98 and r["payload"][0] == 3]


def test_a_circle_guest_puts_its_player_on_the_host_s_field(monkeypatch):
    host = CircleHostConsole(Clock())
    run_guest(monkeypatch, host, 12)
    got = host.got
    tables = [r for r in got if (r["protocol"], r["port"]) == (0x7C, 1) and "data" in r]
    # The field keys sent back compressed, as they came.
    assert tables[1]["rflags"] & reliable5.FLAG_ZLIB and tables[1]["data"] == FIELD_KEYS
    port0 = {r["seq"]: r["data"] for r in got if (r["protocol"], r["port"]) == (0x7C, 0) and "data" in r}
    assert [port0[seq].hex() for seq in sorted(port0)] == [
        "1f0001000000", "1f0005000200", "1f0009000300", "1f000d000a00", "1e0000002400",
        HOST_STATE[:4].hex() + "0500" + HOST_STATE[6:].hex()]
    # Nothing on the broadcast streams: no Lua message unasked, no mirrored player.
    assert not [r for r in got if r["protocol"] in (0x68, 0x80) and "data" in r]


def test_a_circle_guest_prints_its_object_traffic_only_when_verbose(monkeypatch, capsys):
    run_guest(monkeypatch, CircleHostConsole(Clock()), 12)
    assert "circle declares object" not in capsys.readouterr().out
    run_guest(monkeypatch, CircleHostConsole(Clock()), 12, "--verbose-circle")
    assert "circle declares object 0x0001, type 0" in capsys.readouterr().out


# A retail Scarlet's start, its own state and its first sync point, as it sent them to its new member.
HOST_START = bytes.fromhex("3201640001000000000018000000000000000c000000000006000c000400060000004e61bc"
                           "0000000000")
HOST_MEMBER = bytes.fromhex("320165000200000000002000000000000000bcf7ddf70f00000001000000000000000100"
                            "0000000000000000000001000000")
HOST_SYNC = bytes.fromhex("3201670003000000000018000000000000000c000000000006000c00040006000000a708"
                          "000000000000")


def lua_sent(member):
    return [(label, flags, streams.decompress(payload)) for label, flags, payload in member.tick(0.0)]


def test_a_member_answers_the_start_with_the_host_s_own_state():
    member = circle.Member()
    assert member.on_lua(HOST_START) == circle.START
    assert lua_sent(member) == []
    member.on_lua(HOST_MEMBER)
    (label, flags, plain), = lua_sent(member)
    assert label == "message 101" and flags == raid.FIRST
    assert plain == circle.message(circle.MEMBER, 1, raid.payload_of(HOST_MEMBER))
    member.on_lua(HOST_MEMBER)
    assert lua_sent(member) == []


def test_a_member_reaches_every_sync_point_the_host_reaches():
    member = circle.Member()
    for raw in (HOST_START, HOST_MEMBER, HOST_SYNC):
        member.on_lua(raw)
    _, (label, flags, plain) = lua_sent(member)
    assert label == "message 103" and flags == raid.COMPLETE_ZLIB
    assert plain == circle.message(circle.SYNC, 2, raid.payload_of(HOST_SYNC))


def test_a_member_answers_the_host_s_crystals_with_an_empty_world():
    member = circle.Member()
    crystals = bytes.fromhex("01010211000001010a030001") + circle.NO_CRYSTAL * (circle.CRYSTAL_SLOTS - 2)
    member.on_lua(circle.message(circle.CRYSTALS, 13, crystals))
    member.on_lua(circle.message(circle.CRYSTALS, 14, crystals))
    (label, _, plain), = lua_sent(member)
    assert label == "message 106"
    # LZ4 in one fragment, as the host's own: unfragmented, 1818 plain bytes went unacknowledged.
    assert plain[6:10] == raid.COMPRESSION_LZ4.to_bytes(4, "little") and len(plain) <= circle.FRAGMENT
    assert raid.payload_of(plain) == circle.NO_CRYSTAL * circle.CRYSTAL_SLOTS


def test_a_member_follows_the_host_s_field():
    member = circle.Member()
    field = circle.message(circle.FIELD, 20, bytes.fromhex("0c000000000006000c000400060000002100000000000000"))
    member.on_lua(field)
    (label, _, plain), = lua_sent(member)
    assert label == "message 110"
    assert plain == circle.message(circle.FIELD, 1, raid.payload_of(field))


def sent(member):
    return [(label, flags, streams.decompress(payload) if flags & reliable5.FLAG_ZLIB else payload)
            for label, flags, payload in member.objects()]


def test_a_member_declares_its_objects_once_the_host_opens_the_field_keys():
    member = circle.Member()
    member.on_table(channel_table.build([(bytes.fromhex("8000000046000000"), True)]))
    assert sent(member) == []
    member.on_table(FIELD_KEYS)
    member.on_table(FIELD_KEYS)
    # What a retail station 1 declared, word for word.
    assert [(flags, plain.hex()) for _, flags, plain in sent(member)] == [
        (raid.COMPLETE, "1f0001000000"), (raid.COMPLETE, "1f0005000200"),
        (raid.COMPLETE, "1f0009000300"), (raid.COMPLETE, "1f000d000a00")]


def test_a_member_asks_for_each_object_the_host_declares():
    member = circle.Member()
    member.on_object(HOST_DECLARES)
    member.on_object(bytes.fromhex("1f002c000a00"))
    assert [plain.hex() for _, _, plain in sent(member)] == ["1e0000002400", "1e0000002c00"]


def test_a_member_answers_an_ask_with_the_host_s_state_under_our_id():
    member = circle.Member()
    member.on_object(HOST_DECLARES)
    member.on_object(bytes.fromhex("1e0000000500"))     # asked before the host's state is here
    sent(member)
    member.on_object(HOST_STATE)
    (_, flags, plain), = sent(member)
    assert flags == raid.COMPLETE_ZLIB
    assert plain == HOST_STATE[:4] + bytes.fromhex("0500") + HOST_STATE[6:]
    member.on_object(bytes.fromhex("1e0000000d00"))     # our type-10 object: never answered
    member.on_object(bytes.fromhex("1e0000002400"))     # not ours
    assert sent(member) == []
    member.on_object(bytes.fromhex("1e0000000500"))     # asked again: answered again
    assert [plain for _, _, plain in sent(member)] == [
        HOST_STATE[:4] + bytes.fromhex("0500") + HOST_STATE[6:]]


def test_a_member_answers_by_the_state_s_kind_whatever_type_the_host_declares():
    # A second retail host declared its kind-2 object as type 1, where the member's is type 2.
    member = circle.Member()
    member.on_object(bytes.fromhex("1f0024000100"))
    member.on_object(HOST_STATE)
    member.on_object(bytes.fromhex("1e0000000500"))
    assert [plain for _, _, plain in sent(member)][-1] == (
        HOST_STATE[:4] + bytes.fromhex("0500") + HOST_STATE[6:])


# A retail host's own BBQ clear, as its member got it: quest 29, Normal, 20 BP, from station
# 0x86d438ce451c0000, its message sequence 4 and its status record after the clear.
HOST_CLEAR = bytes.fromhex(
    "480003b9121d0000020014b9018300001c45ce38d486b90a021d0001140a00000088000000410000b9010002b90422"
    "88000000000000b90a01220001140a0000008800008841b90a00000085ff7f0000000000880000000000b90a000000"
    "85ff7f000000000088000000000004b90b01b9040188000000000000b9040988000000000000b90422880000000000"
    "00bc0101b9040088000000000000b904008800000000000006000600")


def test_the_tagged_encoding_writes_a_retail_clear_word_for_word():
    station = circle.U64(0x86D438CE451C0000)
    event = (29, 0, 0, 2, circle.NORMAL, 20, (station,), (2, 29, 0, 1, 20, 10, 0, 0, 0, 8.0), 0, 0,
             (0,), 2, (34, 0.0, 0, 0), (1, 34, 0, 1, 20, 10, 0, 0, 0, 17.0), circle.EMPTY_ROW, 0,
             circle.EMPTY_ROW, 0)
    record = (1, (1, 0.0, 0, 0), (9, 0.0, 0, 0), (34, 0.0, 0, 0), b"\x01", circle.NO_QUEST,
              circle.NO_QUEST, 6, 0, 6, 0)
    assert (bytes.fromhex("480003") + circle.encode(event) + circle.encode(4)
            + circle.encode(record)) == HOST_CLEAR


def test_a_clear_names_its_bp_and_our_station():
    plain = circle.clear_message(29, 1, 0x0200AABBCCDD0200, 1)
    assert plain[:3] == bytes.fromhex("480003")
    assert plain[3:11] == bytes.fromhex("b9121d0000020001")        # quest 29, Normal, 1 BP
    assert plain[11:22] == bytes.fromhex("b901830002ddccbbaa0002")


def test_a_member_sends_its_bp_clear_a_second_after_the_demo():
    member = circle.Member(station_id=0x0200AABBCCDD0200, bp=1)
    for raw in (HOST_START, HOST_MEMBER, HOST_SYNC):
        member.on_lua(raw)
    lua_sent(member)
    sync = lambda n: HOST_SYNC[:-8] + n.to_bytes(4, "little") + HOST_SYNC[-4:]
    member.on_lua(sync(1))
    assert [label for label, _, _ in lua_sent(member)] == ["message 103"]
    member.on_lua(sync(2))
    (_, _, plain), = (one for one in member.tick(100.0))
    assert circle.sync_id(streams.decompress(plain)) == circle.DEMO_ENDED
    assert member.tick(100.9) == [] and not member.finished
    sent_at = lambda now: [(label, flags, streams.decompress(payload))
                           for label, flags, payload in member.tick(now)]
    (label, flags, plain), = sent_at(101.0)
    assert label == "BBQ Normal clear of quest 29, 1 BP" and flags == raid.COMPLETE_ZLIB
    assert plain == circle.clear_message(29, 1, 0x0200AABBCCDD0200, 1, cleared=1)
    assert member.notes == ["sent a clear paying the host 1 BP; it shows once the host's player closes "
                            "the BP side bar"]
    assert member.finished and sent_at(130.0) == []
    member.on_lua(sync(2))
    assert [label for label, _, _ in member.tick(200.0)] == ["message 103"]


def test_a_drawn_team_quest_clears_with_its_quest_and_bp():
    rng = random.Random(7)
    clears = [circle.team_clear(rng) for _ in range(300)]
    assert {(row[1], bp) for _, bp, row in clears} == {(q, bp) for q, bp, _ in circle.TEAM_QUESTS}
    grade, bp, row = clears[0]
    plain = circle.clear_message(row[1], bp, 0x0200AABBCCDD0200, 1, grade=grade, row=row)
    event = circle.bbq_values(plain)[1][0]
    assert event[:6] == (row[1], 0, 0, circle.CLEAR_SLOT, circle.TEAM, bp)
    assert event[7] == (circle.CLEAR_CATEGORY, row[1], 0, 1, bp, 10, 0, circle.TEAM, 0, 8.0)


def host_status(solo, team, sequence=1):
    """-> a host's status message holding quests 1, 9 and 29 and these totals."""
    record = (1, (1, 0.0, 0, 0), (9, 0.0, 0, 0), (29, 0.0, 0, 0), b"", circle.NO_QUEST,
              circle.NO_QUEST, solo, 0, solo, team)
    return (bytes([0x48, 0, circle.BBQ_STATUS]) + circle.encode(sequence)
            + circle.encode(record))


def snacking(solo, team):
    member = circle.Member(station_id=0x0200AABBCCDD0200, snacksworth=True, rng=random.Random(3))
    for raw in (HOST_START, HOST_MEMBER, HOST_SYNC, host_status(solo, team)):
        member.on_lua(raw)
    member.on_lua(HOST_SYNC[:-8] + (2).to_bytes(4, "little") + HOST_SYNC[-4:])
    return member


def snacks_sent(member, now):
    return [(label, circle.bbq_values(streams.decompress(payload)))
            for label, _, payload in member.tick(now) if label.startswith("BBQ")]


def test_a_snacksworth_run_gives_the_team_clears_then_the_host_s_quests_one_a_second():
    member = snacking(128, 10)
    assert member.snacks == (0, 4)
    team = snacks_sent(member, 100.0) + snacks_sent(member, 100.9) + snacks_sent(member, 101.0)
    assert [values[0] for _, values in team] == [circle.BBQ_CLEAR] * 2
    assert all(values[1][0][4] == circle.TEAM for _, values in team)
    member.on_lua(host_status(128, 12, 2))
    assert member.snacks == (2, 4)
    (label, values), = snacks_sent(member, 102.0)
    assert label == "BBQ progress on the host's quest 1 (slot 1, value -1)"
    assert values[1][:5] == [1, -1, -1, circle.PROGRESS_COUNT, 3]
    assert [v[1][0] for _, v in snacks_sent(member, 103.0)] == [9]
    member.on_lua(host_status(130, 12, 3))
    assert member.snacks == (4, 4) and member.finished
    assert snacks_sent(member, 104.0) == []


def test_a_snacksworth_run_tops_up_a_team_clear_the_host_did_not_count():
    member = snacking(130, 11)
    assert [v[1][0][4] for _, v in snacks_sent(member, 0.0)] == [circle.TEAM]
    assert [v[1][0][4] for _, v in snacks_sent(member, 1.0)] == [circle.TEAM]
    member.on_lua(host_status(130, 12, 2))
    assert member.finished and snacks_sent(member, 2.0) == []


def test_a_snacksworth_run_stops_once_the_host_s_totals_ignore_its_sends():
    member = snacking(128, 12)
    sends = [snacks_sent(member, float(n)) for n in range(circle.STALL_SENDS - 1)]
    assert all(sends) and not member.finished
    member.on_lua(host_status(129, 12, 2))          # the host counted one: the count starts again
    for n in range(circle.STALL_SENDS - 1):
        snacks_sent(member, 100.0 + n)
    assert not member.finished
    snacks_sent(member, 200.0)
    assert member.finished and member.notes[-1].endswith("with 1 solo and 0 Team still to go")
    assert snacks_sent(member, 201.0) == []


def test_a_snacksworth_run_waits_for_the_host_s_totals_and_sends_nothing_past_them():
    member = circle.Member(snacksworth=True)
    assert member.snacks is None and not member.finished
    member = snacking(200, 30)
    assert member.snacks == (0, 0) and member.finished and snacks_sent(member, 0.0) == []


def test_a_team_clear_carries_the_team_grade():
    plain = circle.clear_message(29, 1, 0x0200AABBCCDD0200, 1, grade=circle.TEAM)
    assert plain[3:11] == bytes.fromhex("b9121d0000020201")        # quest 29, Team, 1 BP


def test_decode_reads_a_retail_clear_back_as_encode_wrote_it():
    event, pos = circle.decode(HOST_CLEAR, 3)
    assert event[:6] == (29, 0, 0, 2, circle.NORMAL, 20)
    assert event[6] == (0x86D438CE451C0000,)
    assert event[7] == (2, 29, 0, 1, 20, 10, 0, 0, 0, 8.0)
    assert event[12:14] == ((34, 0.0, 0, 0), (1, 34, 0, 1, 20, 10, 0, 0, 0, 17.0))
    sequence, pos = circle.decode(HOST_CLEAR, pos)
    record, pos = circle.decode(HOST_CLEAR, pos)
    assert sequence == 4 and record[4] == b"\x01" and pos == len(HOST_CLEAR)
    assert circle.decode(bytes.fromhex("c0")) == (-64, 1)
    assert circle.decode(bytes.fromhex("85ff7f")) == (32767, 3)
    with pytest.raises(ValueError):
        circle.decode(bytes.fromhex("8600"))


# A retail host's status record as it sent it to its retail member (sniffed): quests 1, 9 and 34,
# 6 solo clears, 3 Team clears.
HOST_STATUS = bytes.fromhex(
    "48000101b90b01b9040188000000000000b9040988000000000000b9042288000000000000bc0101b904008800"
    "0000000000b904008800000000000006000603")


def test_a_status_message_reads_as_the_players_quests_and_totals():
    status = circle.bbq_record(HOST_STATUS)
    assert [(slot.quest, slot.progress, slot.row) for slot in status.quests] == [
        (1, 0.0, 0), (9, 0.0, 0), (34, 0.0, 0)]
    assert (status.solo, status.team) == (6, 3)
    assert circle.bbq_record(HOST_START) is None


# A retail member's (Violet's) progress on its host's quest 9, sniffed: the quest, no values, a
# count of 1.0, its message sequence 3 and its own status record (quests 22, 33 in variant 3, 31).
MEMBER_PROGRESS = bytes.fromhex(
    "48000209ffff880000803f03b90b01b9041688000000000001b9042188000000000301b9041f8800000000000"
    "0bc0101b9040088000000000000b90400880000000000000400810c010d")
# The host's answer: its clear of quest 9 crediting the member's station, quest 23 taking the slot.
HOST_CLEAR_FOR_MEMBER = bytes.fromhex(
    "480003b912090000010014b9018300003ca9065335abb90a01090001140a00000088000088410000b9010002b904"
    "1788000000000000b90a031700011e0a000000880000e040b90a00000085ff7f0000000000880000000000b90a00"
    "000085ff7f000000000088000000000004b90b01b9040188000000000000b9041788000000000000b9041d880000"
    "00000000bc0101b9040088000000000000b904008800000000000006000600")


def test_our_progress_is_word_for_word_a_retail_members_but_its_record():
    ours = circle.progress_message(9, 3, count=1.0)
    record_at = MEMBER_PROGRESS.index(bytes.fromhex("b90b"))
    assert ours[:record_at] == MEMBER_PROGRESS[:record_at]
    kind, values = circle.bbq_values(MEMBER_PROGRESS)
    assert kind == circle.BBQ_PROGRESS and values[:5] == [9, -1, -1, 1.0, 3]
    assert circle.bbq_record(MEMBER_PROGRESS).quests[1].variant == 3


def test_a_hosts_clear_carries_its_new_quests():
    assert [slot.quest for slot in circle.bbq_record(HOST_CLEAR_FOR_MEMBER).quests] == [1, 23, 29]


def test_a_snacksworth_run_reports_on_the_host_s_quests_as_its_slots_refill():
    member = snacking(100, 12)
    reports = lambda now: [v[1][:5] for _, v in snacks_sent(member, now)]
    assert reports(100.0) == [[1, -1, -1, circle.PROGRESS_COUNT, 1]]
    assert [v[0] for v in reports(101.0)] == [9]
    # The host clears quest 1 for us; its record (as clear_message builds one) holds quest 1 alone,
    # in its third slot. Another station's record is not the host's.
    member.on_lua(circle.clear_message(9, 20, 0x1234, 6), host=False)
    assert [v[0] for v in reports(102.0)] == [29]
    member.on_lua(circle.clear_message(1, 20, 0x0200AABBCCDD0200, 5))
    assert [v[:5] for v in reports(103.0)] == [[1, -1, -1, circle.PROGRESS_COUNT, 4]]
    assert [v[0] for v in reports(104.0)] == [1]


def test_our_clear_carries_a_status_record_that_reads_back():
    plain = circle.clear_message(29, 20, 0x0200AABBCCDD0200, 3, cleared=3)
    event, pos = circle.decode(plain, 3)
    sequence, pos = circle.decode(plain, pos)
    record, _ = circle.decode(plain, pos)
    assert sequence == 3 and circle.status_of(record) == circle.bbq_record(plain)
    status = circle.bbq_record(plain)
    assert status.quests[circle.CLEAR_SLOT].quest == 29 and status.solo == 3


# A retail host's player walking (object 0x30) and mounting its ride (0x34), on 0x68, and the four
# objects it declared.
HOST_WALK = bytes.fromhex("1e010400300000000000fb9f1dbf00000000f3b7493f03528045295c2b4289282ec5"
                          "00000000")
HOST_MOUNT = bytes.fromhex("1e010600300003000000000000000000000000000000000000000000003f0000003f"
                           "340008000000")
HOST_OBJECTS = [bytes.fromhex(h) for h in ("1f0030000000", "1f0034000100", "1f0038000300",
                                           "1f003c000a00")]


def position(frame):
    return struct.unpack_from("<3f", frame, circle.POSITION_AT)


def test_behind_moves_a_transform_back_along_its_heading():
    moved = circle.behind(HOST_WALK, 5.0)
    assert moved[:circle.POSITION_AT] == HOST_WALK[:circle.POSITION_AT]
    (x, y, z), (mx, my, mz) = position(HOST_WALK), position(moved)
    assert my == y and math.isclose(math.hypot(mx - x, mz - z), 5.0, rel_tol=1e-4)
    _, qy, _, qw = struct.unpack_from("<4f", HOST_WALK, circle.ROTATION_AT)
    yaw = 2 * math.atan2(qy, qw)
    assert math.isclose((mx - x) * math.sin(yaw) + (mz - z) * math.cos(yaw), -5.0, rel_tol=1e-4)
    riding = HOST_WALK[:circle.POSITION_AT] + bytes(12) + HOST_WALK[circle.POSITION_AT + 12:]
    assert circle.behind(riding, 5.0) == riding


def following(distance=5.0):
    member = circle.Member(follow=distance)
    member.on_table(FIELD_KEYS)
    for declaration in HOST_OBJECTS:
        member.on_object(declaration)
    sent(member)
    return member


def after(member, frame, t):
    """-> our frames once the host's `frame`, come at `t`, is due."""
    member.on_frame(frame, t)
    return member.frames_due(t + circle.FRAME_DELAY)


def test_a_following_member_copies_the_host_s_frames_under_its_own_objects():
    member = following()
    (walk,) = after(member, HOST_WALK, 0.0)
    assert circle.object_of(walk) == 0x01
    assert walk == circle.behind(HOST_WALK[:4] + bytes.fromhex("0100") + HOST_WALK[6:], 5.0)
    member.on_frame(HOST_MOUNT, 0.5)    # our player mounts our ride, once it comes due
    assert HOST_MOUNT[2] not in [f[2] for f in member.frames_due(0.5 + circle.FRAME_DELAY - 0.02)]
    (mount, walk) = member.frames_due(0.5 + circle.FRAME_DELAY)
    assert circle.object_of(mount) == 0x01 and mount[circle.PARENT_AT:circle.PARENT_AT + 2] == (
        bytes.fromhex("0500"))
    assert mount[6:circle.PARENT_AT] == HOST_MOUNT[6:circle.PARENT_AT]
    wild = HOST_WALK[:4] + bytes.fromhex("9400") + HOST_WALK[6:]
    member.on_frame(wild, 0.7)
    assert all(circle.object_of(f) == 0x01 for f in member.frames_due(0.7 + circle.FRAME_DELAY))


def test_a_member_copies_nothing_unless_following_and_declared():
    member = circle.Member()
    member.on_table(FIELD_KEYS)
    for declaration in HOST_OBJECTS:
        member.on_object(declaration)
    assert after(member, HOST_WALK, 0.0) == [] and member.frame_wait(0.0) is None
    undeclared = circle.Member(follow=5.0)
    for declaration in HOST_OBJECTS:
        undeclared.on_object(declaration)
    assert after(undeclared, HOST_WALK, 0.0) == []


def test_a_following_member_sends_on_its_own_clock_between_the_host_s_frames():
    member = following()
    member.on_frame(HOST_WALK, 0.0)
    member.on_frame(moved(HOST_WALK, 2.0, 0.0), 0.1)    # a gap: frames dropped between
    member.on_frame(moved(HOST_WALK, 4.0, 0.0), 0.2)
    sent_at, xs = [], []
    t = 0.0
    while t < 0.2 + circle.FRAME_DELAY:
        wait = member.frame_wait(t)
        if wait == 0:
            for frame in member.frames_due(t):
                sent_at.append(t)
                xs.append(position(frame)[0])
        t = round(t + 0.001, 3)
    gaps = [b - a for a, b in zip(sent_at, sent_at[1:])]
    assert all(abs(g - circle.FRAME_PERIOD) < 0.002 for g in gaps)
    steps = [b - a for a, b in zip(xs, xs[1:])]
    assert max(steps) < 0.5 and min(steps) >= -1e-6      # it glides, never jumps or backs up


def test_between_interpolates_and_holds_across_a_ride():
    a, b = HOST_WALK, moved(HOST_WALK, 2.0, -1.0)
    track = [(1.0, a), (2.0, b)]
    assert circle.between(track, 0.5) is None
    assert circle.between(track, 1.0) == a and circle.between(track, 3.0) == b
    (x, y, z), (ax, ay, az) = position(circle.between(track, 1.5)), position(a)
    assert math.isclose(x, ax + 1.0, abs_tol=1e-3) and y == ay and math.isclose(z, az - 0.5,
                                                                               abs_tol=1e-3)
    riding = HOST_WALK[:circle.POSITION_AT] + bytes(12) + HOST_WALK[circle.POSITION_AT + 12:]
    assert circle.between([(1.0, a), (2.0, riding)], 1.5) == a


# A retail host's animation state for its player 0x84 on 0x80 port 0 (kind 5).
HOST_ANIMATION = bytes.fromhex("1e000500840012000000011900011b00010b01020200000000040d01546f702f70"
                               "635f6669656c642f6d6f76652f64656661756c7477616974303100")


def test_a_following_member_sends_the_host_s_animation_as_its_player_s():
    member = circle.Member(follow=5.0)
    member.on_table(FIELD_KEYS)
    member.on_object(bytes.fromhex("1f0084000000"))
    sent(member)
    assert member.on_lua(HOST_ANIMATION, 0.0) is None
    assert member.tick(0.0) == []                     # it waits for the frames of its moment
    member.frames_due(circle.FRAME_DELAY)
    (label, flags, payload), = member.tick(circle.FRAME_DELAY)
    assert label == "host object kind 5 as ours 0x0001" and flags == raid.FIRST
    assert streams.decompress(payload) == (
        HOST_ANIMATION[:4] + bytes.fromhex("0100") + HOST_ANIMATION[6:])
    still = circle.Member()
    still.on_table(FIELD_KEYS)
    still.on_object(bytes.fromhex("1f0084000000"))
    still.on_lua(HOST_ANIMATION)
    assert still.tick(0.0) == []


def moved(frame, dx, dz):
    x, y, z = position(frame)
    return frame[:circle.POSITION_AT] + struct.pack("<3f", x + dx, y, z + dz) + frame[
        circle.POSITION_AT + 12:]


def facing(ours, host):
    _, qy, _, qw = struct.unpack_from("<4f", ours, circle.ROTATION_AT)
    yaw = 2 * math.atan2(qy, qw)
    (hx, _, hz), (ox, _, oz) = position(host), position(ours)
    gap = math.hypot(hx - ox, hz - oz)
    return (math.isclose(math.sin(yaw) * gap, hx - ox, abs_tol=1e-3)
            and math.isclose(math.cos(yaw) * gap, hz - oz, abs_tol=1e-3))


def test_a_following_member_stays_put_within_its_distance_and_is_pulled_beyond_facing_it():
    member = following()
    (first,) = after(member, HOST_WALK, 0.0)
    (hx, _, hz), (x, _, z) = position(HOST_WALK), position(first)
    away = (x - hx) / 5, (z - hz) / 5             # from the host towards us
    host = moved(HOST_WALK, -away[0] * 2, -away[1] * 2)   # the host walks off 2 m: we follow
    (ours,) = after(member, host, 0.1)
    (hx, hy, hz), (ox, oy, oz) = position(host), position(ours)
    assert oy == hy and math.isclose(math.hypot(ox - hx, oz - hz), 5.0, rel_tol=1e-4)
    assert math.isclose(math.hypot(ox - x, oz - z), 2.0, rel_tol=1e-3) and facing(ours, host)
    stood = position(ours)
    # It comes 3 m back, then sidesteps, within 5 m: we stand where we stood, turned to it.
    for n, (dx, dz) in enumerate(((away[0] * 3, away[1] * 3), (0.7, -0.4)), 2):
        host = moved(host, dx, dz)
        (ours,) = after(member, host, n * 0.1)
        assert position(ours) == stood and facing(ours, host)


def walking(member, start, step, t0, t1):
    """Feeds the host's frames from `start`, `step` metres a 60th of a second, from t0 to t1."""
    host, t = start, t0
    while t < t1:
        host = moved(host, *step)
        member.on_frame(host, t)
        t += circle.FRAME_PERIOD
    return host


def speed_of(payload):
    found = circle.numbers(streams.decompress(payload))
    return next(v for (_, n), v in found.items() if n == circle.SPEED)


def test_a_following_member_scales_the_host_s_speed_to_its_own_pace():
    member = following()
    (first,) = after(member, HOST_WALK, 0.0)
    member.tick(0.0)
    (hx, _, hz), (x, _, z) = position(HOST_WALK), position(first)
    away = (x - hx) / 5, (z - hz) / 5
    step = (away[0] * 0.05, away[1] * 0.05)         # 3 m/s
    # The host walks off for a second, its speed number 1.0: we are pulled along at its pace.
    host = walking(member, HOST_WALK, (-step[0], -step[1]), 0.1, 1.1)
    member.on_lua(HOST_ANIMATION[:4] + bytes.fromhex("3000") + bytes.fromhex("06000000") + bytes([2, circle.SPEED])
                  + struct.pack("<f", 1.0), 0.5)
    # Then it walks back towards us for a second: we stand.
    walking(member, host, step, 1.1, 2.1)
    sent = []
    t = 0.2
    while t < 2.1 + circle.FRAME_DELAY:
        member.frames_due(t)
        sent += [(t, label, payload) for label, _, payload in member.tick(t)]
        t = round(t + 0.005, 3)
    (_, _, walk), = [s for s in sent if s[1].startswith("host object")]
    assert math.isclose(speed_of(walk), 1.0, abs_tol=0.15)
    ours = [(t, speed_of(p)) for t, label, p in sent if label.startswith("our speed")]
    assert ours and ours[-1][1] < 0.2 and all(t >= 1.1 + circle.FRAME_DELAY - 1e-6 for t, _ in ours)


def test_scaled_scales_only_the_move_blend():
    message = HOST_ANIMATION[:6] + bytes.fromhex("0f000000") + bytes([2, 1]) + struct.pack(
        "<f", 1.5) + bytes([2, 2]) + struct.pack("<f", -10.0) + bytes.fromhex("010b01")
    numbers = circle.numbers(circle.scaled(message, 0.5))
    assert sorted((n, v) for (_, n), v in numbers.items()) == [(1, 0.75), (2, -5.0)]
    assert circle.scaled(HOST_ANIMATION[:6] + bytes.fromhex("0300000009ffff"), 0.5) == (
        HOST_ANIMATION[:6] + bytes.fromhex("0300000009ffff"))     # an op we do not know: as is
    assert speed_of(streams.compress(circle.speed_message(0x01, 0.25))) == 0.25


# A retail host's spawn record (object 0x138): Rabsca (dev 954), level 27, not shiny.
RETAIL_SPAWN = bytes.fromhex(
    "38018881ba03803fc006e03100893f038e07000000000000000000000000000000000000ffffffff5b0200b90183f476"
    "d51a1d44334da94218a046c5000000000000000000000000000000000000803f0000000002b9018345262284e49cf2cb")


def test_a_spawn_record_reads_and_writes_a_retail_record_s_fields():
    fields = circle.record_fields(RETAIL_SPAWN)
    position = fields.pop("position")
    assert fields == {"species": 954, "item": 0, "scale": 127, "sex": 0, "shiny": 0, "form": 0,
                      "level": 27, "ribbon": 0, "nature": 15, "tera": 12,
                      "ivs": (9, 28, 15, 14, 28, 6), "ability": 1}
    ours = circle.spawn_record(0x138, position, **fields)
    # All but the padding the game leaves unset.
    for start, end in ((0, 2), (4, 0x28), (0x30, 0x50)):
        assert ours[start:end] == RETAIL_SPAWN[start:end]
    shiny = circle.spawn_record(0x138, position, **dict(fields, shiny=1))
    assert int.from_bytes(shiny[4:12], "little") ^ int.from_bytes(ours[4:12], "little") == 1 << 32


DEMO_ENDED = HOST_SYNC[:-8] + circle.DEMO_ENDED.to_bytes(4, "little") + HOST_SYNC[-4:]


def spawning(**kw):
    """-> a member whose shiny Rayquaza spawner starts as the demo ends at 100, the host's player
    standing where HOST_WALK has it."""
    member = circle.Member(spawner=circle.Spawner(384, 70, True, tera=15, rng=random.Random(1),
                                                  **kw))
    member.on_table(FIELD_KEYS)
    for declaration in HOST_OBJECTS:
        member.on_object(declaration)
    sent(member)
    member.on_lua(DEMO_ENDED)
    assert [label for label, _, _ in member.tick(100.0)] == ["message 103"]
    stands(member, HOST_WALK, 100.0)
    return member


def stands(member, frame, now):
    """The host's player stands where `frame` puts it from `now`: as a retail console does, its
    transform keeps coming (spawn_out sends it again)."""
    member.test_host_frame = frame
    member.on_frame(frame, now)


def spawn_out(member, now):
    """-> ([(label, plain)] on 0x80 port 0, [frame] on 0x68) at `now`, the host's transform come again."""
    if getattr(member, "test_host_frame", None) is not None:
        member.on_frame(member.test_host_frame, now)
    messages = [(label, streams.decompress(payload)) for label, _, payload in member.tick(now)]
    return messages, member.frames_due(now)


def test_a_member_spawns_from_ten_seconds_after_the_demo_one_a_second_around_the_host():
    """Up to SPAWN_COPIES: the first three come a second apart."""
    member = spawning()
    assert spawn_out(member, 109.9) == ([], [])
    station = streams.JOINER_INDEX
    first = station + 4 * circle.SPAWN_FIRST
    messages, (attach, scale, transform) = spawn_out(member, 110.0)
    assert messages == []           # the record follows its object's frames
    assert attach == circle.object_frame(first, circle.ATTACH, circle.UNATTACHED)
    assert scale == circle.object_frame(first, circle.SCALE_FRAME, struct.pack("<f", 1.0))
    assert circle.object_of(transform) == first and transform[2] == circle.TRANSFORM
    ((label, plain),) = spawn_out(member, 110.05)[0]
    assert label.startswith(f"spawn ({station}, {circle.SPAWN_FIRST}) species 384 level 70 shiny")
    assert plain[:5] == bytes.fromhex("260001bc60") and len(plain) == 5 + circle.RECORD_SIZE
    record = plain[5:]
    assert int.from_bytes(record[:2], "little") == first
    fields = circle.record_fields(record)
    assert (fields["species"], fields["level"], fields["shiny"], fields["tera"]) == (384, 70, 1, 15)
    host, at = position(HOST_WALK), fields["position"]
    assert at[1] == host[1] and 15.0 <= math.hypot(at[0] - host[0], at[2] - host[2]) <= 25.0
    assert position(transform) == at
    _, qy, _, qw = struct.unpack_from("<4f", transform, circle.ROTATION_AT)
    yaw = 2 * math.atan2(qy, qw)
    ahead = ((host[0] - at[0]) * math.sin(yaw) + (host[2] - at[2]) * math.cos(yaw))
    assert math.isclose(ahead, math.hypot(at[0] - host[0], at[2] - host[2]), rel_tol=1e-4)
    assert spawn_out(member, 110.5) == ([], [])
    messages, frames = spawn_out(member, 111.0)
    assert messages == [] and [circle.object_of(f) for f in frames] == [first + 4] * 3
    # Its transform and a settled state every two seconds: the id (1, 256) as a retail one is
    # written, unsigned (260103 b902 00 25 ... from a retail host), then the state.
    messages, frames = spawn_out(member, 112.0)
    assert (None, bytes.fromhex("260103b902018100" "01b90588") + struct.pack("<f", 0.001)
            + bytes.fromhex("880000000088000000000000")) in messages
    assert [circle.object_of(f) for f in frames] == [first + 8] * 3 + [first]
    assert frames[-1] == transform


def test_a_spawn_id_is_written_as_retail_consoles_write_theirs():
    # A retail host's kind 2 for (0, 37) and a retail member's state for (1, 145).
    assert circle.spawn_id(0, 37) == bytes.fromhex("b9020025")
    assert circle.spawn_id(1, 145) == bytes.fromhex("b902018091")


def test_a_member_hands_its_spawn_to_the_console_that_asks_to_battle_it():
    member = spawning()
    spawn_out(member, 110.0)
    spawn_out(member, 110.05)
    station, n = streams.JOINER_INDEX, circle.SPAWN_FIRST
    # The host asks for (1, 256) as (0, 6) on 0x7c port 0, as a retail host did ours; the answer
    # goes to every station on 0x80 port 0, as a retail owner's kind 7 went.
    ask = bytes.fromhex("260005b902b90201810001b9020006")
    body = ask[3:]
    member.on_object(ask)
    assert sent(member) == []
    messages, _ = spawn_out(member, 110.1)
    assert messages == [(f"spawn ({station}, {n}) handed over as (0, 6)",
                         bytes.fromhex("260007") + body)]
    assert member.spawner.live == []        # the host's now: no more states, never let go
    assert not [m for m in spawn_out(member, 112.0)[0] if m[1][:2] == bytes.fromhex("2601")]
    # One it no longer has, or never had, it refuses, back to the asker alone.
    member.on_object(ask)
    assert sent(member) == [(f"spawn ({station}, {n}) refused", raid.COMPLETE_ZLIB,
                             bytes.fromhex("260006") + body)]
    assert not [m for m in spawn_out(member, 112.1)[0] if m[1][:3] == bytes.fromhex("260006")]


def test_a_member_spawns_only_once_it_knows_where_the_host_stands():
    member = circle.Member(spawner=circle.Spawner(384, 70, rng=random.Random(1)))
    member.on_lua(DEMO_ENDED)
    member.tick(100.0)
    assert spawn_out(member, 110.0) == ([], [])


def test_the_app_s_union_circle_entry_runs_a_task_per_choice():
    from pokeldn.app import catalog, command
    from pokeldn.app.introspect import parser_of
    from pokeldn.app.settings import Settings
    tool = next(t for t in catalog.SV.tools if t.key == "sv-circle-join")
    values = {"--code": "1826"}
    args = command.build(tool, values, {}, Settings())
    parsed = parser_of(tool.script).parse_args(args)
    assert parsed.union_circle and parsed.code == "1826" and parsed.circle_task == "snacksworth"
    assert parsed.bbq_clear is None and command.problems(tool, values) == []
    values.update({"--circle-task": "bp", "--bbq-clear": "5000"})
    parsed = parser_of(tool.script).parse_args(command.build(tool, values, {}, Settings()))
    assert parsed.circle_task == "bp" and parsed.bbq_clear == 5000
    for refused in ("0", "10000000", "", "1e3"):
        values["--bbq-clear"] = refused
        assert command.problems(tool, values) == ["BP: a whole number from 1 to 9,999,999."]
    values["--bbq-clear"], values["--code"] = str(circle.BP_MAX), "18"
    assert command.problems(tool, values) == ["Link Code: all four digits."]


@pytest.mark.parametrize("argv, why", [
    (["--union-circle", "--circle-task", "bp"], "needs the BP to give"),
    (["--union-circle", "--circle-task", "bp", "--bbq-clear", "10000000"], "1 to 9999999 BP"),
    (["--union-circle", "--bbq-clear", "0"], "1 to 9999999 BP"),
    (["--circle-task", "snacksworth"], "need --union-circle"),
    (["--spawn", "25:11"], "need --union-circle")])
def test_a_circle_task_refuses_bp_a_player_cannot_hold(argv, why, capsys):
    with pytest.raises(SystemExit):
        sv_join.main(argv)
    assert why in capsys.readouterr().err


def test_the_union_circle_entry_shows_each_task_its_own_steps():
    from pokeldn.app import catalog, command
    tool = next(t for t in catalog.SV.tools if t.key == "sv-circle-join")
    snacks = command.steps(tool, {})
    bp = command.steps(tool, {"--circle-task": "bp"})
    assert len(snacks) == 5 and len(bp) == 4
    assert not any("Snacksworth" in step for step in bp)
    assert any("one a second" in step for step in snacks) and any("BP clear" in step for step in bp)
    assert snacks[:2] == bp[:2]


def test_a_spawn_draws_its_ivs_and_ability_at_random_as_the_host_s_wild_ones_come():
    """The host's own spawns in the captures carried six random IVs, mostly none at 31, and ability
    slot 0 or 1, never the hidden one."""
    spawner = circle.Spawner(25, 10, rng=random.Random(7))
    fields = [circle.record_fields(spawner._record(0x100, (0.0, 0.0, 0.0))) for _ in range(40)]
    ivs = [f["ivs"] for f in fields]
    assert all(len(i) == 6 and all(0 <= v <= 31 for v in i) for i in ivs)
    assert sum(i.count(31) == 0 for i in ivs) > 20 and len(set(ivs)) == 40
    assert {f["ability"] for f in fields} == {0, 1}

"""BDSP's Union Room messages above Pia; fixtures off a console, names from TeamLumi/opendpr's
NetDataParser."""

import pathlib
import struct
import subprocess
import sys

import pytest

from pokeldn.bdsp import netdata, room


JOIN_SP43 = bytes.fromhex("0100110800315a00487615c1000000003a0be640")
JOIN_SP36 = bytes.fromhex("0100110800310000c3f5e0c00000000000002841")
POS_SP36 = bytes.fromhex("0200488c00cf00b4008c00cd00b4008e00c800ca009000c400ce009400bb00cc00"
                         "96")
SMALL_A = bytes.fromhex("12000123")
SMALL_B = bytes.fromhex("23000100")


def test_the_framing_is_an_id_and_a_big_endian_length():
    for raw, data_id, length in ((JOIN_SP43, room.JOIN, 17), (JOIN_SP36, room.JOIN, 17),
                                 (SMALL_A, 0x12, 1), (SMALL_B, 0x23, 1)):
        out = room.parse(raw)
        assert out["data_id"] == data_id
        assert out["length"] == length == len(out["body"])
        assert out["truncated"] is False


def test_the_twenty_byte_message_is_a_JOIN_and_not_a_position():
    out = room.parse(JOIN_SP43)
    assert out["data_id"] == room.JOIN == 1 and out["name"] == "NetJoinData"
    j = out["join"]
    assert (j["avatar_id"], j["color_id"], j["casset_version"]) == (8, 0, 0x31)
    assert j["rot_y"] == 90
    assert round(j["x"], 3) == -9.341 and j["y"] == 0.0 and round(j["z"], 3) == 7.189


def test_a_join_round_trips():
    j = room.parse(JOIN_SP43)["join"]
    assert room.build_join(j["x"], j["y"], j["z"], rot_y=j["rot_y"]) == JOIN_SP43
    assert room.build_join(-7.03, 0.0, 10.5, rot_y=0) == JOIN_SP36


def test_pos_data_is_halfwords_at_a_twentieth_of_a_unit_with_x_negated():
    out = room.parse(POS_SP36)
    assert out["data_id"] == room.POS == 2 and out["name"] == "NetPosData"
    assert out["length"] == 72 and out["truncated"] is True     # the fixture is a short capture
    first = out["points"][0]
    assert first["raw"] == (140, 207)
    assert round(first["x"], 2) == -7.00 and round(first["z"], 2) == 10.35
    assert abs(first["x"] - room.parse(JOIN_SP36)["join"]["x"]) < 0.1
    assert abs(first["z"] - room.parse(JOIN_SP36)["join"]["z"]) < 0.2


def test_pos_round_trips_through_the_games_own_scaling():
    raw = room.build_pos([(-7.00, 10.35, 180)])
    pts = room.parse(raw)["points"]
    assert pts[0]["raw"] == (140, 207) and pts[0]["rot_y"] == 180
    assert room.parse(room.build_pos([(-1.0, 2.0, 0)]))["points"][0]["raw"] == (20, 40)


def test_several_points_go_in_one_message():
    raw = room.build_pos([(-1.0, 2.0, 0), (-1.5, 2.5, 90), (-2.0, 3.0, 180)])
    out = room.parse(raw)
    assert out["length"] == 3 * room.POS_POINT_SIZE == 18
    assert len(out["points"]) == 3
    assert out["points"][2]["rot_y"] == 180


def test_a_short_message_is_refused():
    with pytest.raises(ValueError):
        room.parse(b"\x01\x00")
    with pytest.raises(ValueError):
        room.parse_join_body(b"\x00" * 16)


def test_what_was_called_a_keepalive_is_a_message():
    """`04 00 02 00 00` is data id 4, length 2, body 00 00 - the console's own character state."""
    assert room.KEEPALIVE == room.STATE_NONE_MESSAGE == bytes.fromhex("0400020000")
    out = room.parse(room.STATE_NONE_MESSAGE)
    assert out["data_id"] == room.STATE and out["name"] == "NetCharacterStateData"
    assert out["length"] == 2 and out["truncated"] is False
    assert out["fields"] == {"state": room.STATE_NONE, "isRecruiment": 0}
    # The console broadcasts this message every 2 s.
    assert room.build_state() == room.STATE_NONE_MESSAGE


def test_every_message_the_game_speaks_is_named_and_the_ids_are_nibble_grouped():
    assert len(netdata.NAMES) == 65                     # NetDataParser registers exactly 65
    assert netdata.NAMES[room.JOIN][0] == "NetJoinData"
    assert netdata.NAMES[room.POS][0] == "NetPosData"
    # No id's low nibble reaches 0xA: gaps are the grouping.
    assert all(ident & 0x0F <= 9 for ident in netdata.NAMES)
    assert max(netdata.NAMES) == 0x66 and min(netdata.NAMES) == 0x01


def test_the_packed_layout_is_what_the_wire_says_and_not_c_sharp_alignment():
    # JoinData is byte, byte, byte, short, Vector3: 17 packed, 20 aligned. The console sends 17.
    assert struct.calcsize(room.layout(room.JOIN)) == room.JOIN_BODY_SIZE == 17
    assert room.parse(JOIN_SP43)["length"] == 17


def test_the_two_repeated_small_messages_are_a_request_and_its_own_answer():
    req = room.parse(SMALL_A)
    assert req["name"] == "NetRequestData"
    assert req["fields"]["RequestDataID"] == room.MATCH_WAIT == 0x23
    ans = room.parse(SMALL_B)
    assert ans["name"] == "NetDataIsMatchWaitData"
    assert ans["fields"]["isMatchWait"] == 0
    assert room.answer(req) == SMALL_B


def test_the_match_wait_answer_carries_the_value_the_trade_is_gated_on():
    """isMatchWait is the byte UnionRoomManager$$SetNetData compares with 1 [main.bin 0x01fd56e4]."""
    req = room.parse(SMALL_A)
    assert req["fields"]["RequestDataID"] == room.MATCH_WAIT
    assert room.answer(req) == SMALL_B
    assert room.parse(room.answer(req))["fields"]["isMatchWait"] == 0
    waiting = room.answer(req, match_wait=True)
    assert room.parse(waiting)["fields"]["isMatchWait"] == 1
    assert waiting[0] == room.MATCH_WAIT and len(waiting) == len(SMALL_B)


def test_the_approach_reproduces_the_console_s_own_talk_reserve_bytes():
    """NetDataTalkReserveData has no layout in the table; the check is the console's own bytes."""
    assert room.build_talk_reserve() == bytes.fromhex("63000100")
    parsed = room.parse(room.build_talk_reserve())
    assert parsed["name"] == "NetDataTalkReserveData"
    assert parsed["data_id"] == room.TALK_RESERVE == 0x63
    assert parsed["length"] == 1


# the console's own NetDataTradeTranerData, sent when its player entered the trade
TRADE_TRANER_SP82 = bytes.fromhex(
    "50006c0061007900650072000000000018a4010014a401000000b2adf00f3103")


def test_the_trade_trainer_record_reads_and_agrees_with_the_pokemon_it_came_with():
    """TID 44466 SID 4080 in the clear match the encrypted PB8 of the same trade."""
    r = room.parse_trade_traner(TRADE_TRANER_SP82)
    assert r["name"] == "Player"
    assert r["trainer_id"] == 44466
    assert r["secret_id"] == 4080
    assert len(TRADE_TRANER_SP82) == room.TRADE_TRANER_SIZE == 32
    with pytest.raises(ValueError):
        room.parse_trade_traner(TRADE_TRANER_SP82[:-1])


def test_a_payload_whose_struct_is_not_blittable_has_no_layout_and_says_so():
    # NetPlayerNameData carries a C# string and NetPosData an array; neither size is in the source
    for data_id in (room.PLAYER_NAME, room.POS):
        assert data_id in netdata.OPAQUE
        assert room.layout(data_id) is None
        with pytest.raises(ValueError):
            room.build_fields(data_id, 0)
    assert room.parse(room.build(0x29, b"\x00"))["opaque"] is True
    assert room.parse(room.build(room.PLAYER_NAME, b"\x00"))["opaque"] is False


def test_the_generic_packer_agrees_with_the_hand_written_builders():
    assert room.build_request(room.MATCH_WAIT) == SMALL_A
    assert room.build_match_wait(False) == SMALL_B
    assert room.parse(room.build_state(2, 1))["fields"] == {"state": 2, "isRecruiment": 1}


def test_a_pos_span_covers_the_whole_stride_rather_than_creeping():
    span = room.pos_span((0.0, 0.0), (1.2, 0.0), 90)
    assert len(span) == room.POS_POINTS == 12
    assert span[0][:2] == (0.0, 0.0)
    assert round(span[-1][0], 6) == 1.2                 # the endpoint IS sent, so nothing is skipped
    steps = {round(span[i + 1][0] - span[i][0], 6) for i in range(len(span) - 1)}
    assert len(steps) == 1                              # evenly spaced, no jump at the seam
    assert all(rot == 90 for _, _, rot in span)


def test_a_span_of_one_point_is_the_start_and_does_not_divide_by_zero():
    assert room.pos_span((1.0, 2.0), (3.0, 4.0), 0, points=1) == [(1.0, 2.0, 0)]
    with pytest.raises(ValueError):
        room.pos_span((0, 0), (1, 1), 0, points=0)


OPENDPR = [pathlib.Path("~/opendpr").expanduser(),
           pathlib.Path(__file__).resolve().parent.parent / "scratchpad" / "opendpr_repo"]


def test_the_generator_still_reproduces_the_committed_table():
    checkout = next((p for p in OPENDPR if (p / "Assets" / "Scripts").is_dir()), None)
    if checkout is None:
        pytest.skip("no opendpr checkout to regenerate the table from")
    gen = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "gen_bdsp_netdata.py"
    done = subprocess.run([sys.executable, str(gen), str(checkout), "--check"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_trainer_card_is_seventy_five_blittable_bytes():
    """`NetDataTranerCardData` has no capture behind it - the layout is opendpr's alone."""
    card = room.build_trainer_card(fashion_id=3, body_type=1, gender_id=1, trainer_id=41000)
    parsed = room.parse(card)
    assert parsed["data_id"] == room.TRAINER_CARD
    assert parsed["length"] == 75 and not parsed["truncated"]
    assert parsed["fields"]["fashionId"] == 3
    assert parsed["fields"]["bodyType"] == 1
    assert parsed["fields"]["genderid"] == 1
    assert parsed["fields"]["cardData.tranerId"] == 41000


def test_the_ready_ok_we_send_is_the_console_s_own_message_byte_for_byte():
    """`21 00 02 00 02` on the wire; `ReciveReadyOk` [main.bin 0x1cd4860] reads only `[netdata + 0x11]`."""
    msg = room.build_trade_ready_ok()
    assert msg == bytes.fromhex("2100020002")
    parsed = room.parse(msg)
    assert parsed["data_id"] == room.TRADE_READY_OK
    assert parsed["fields"] == {"isTradeOk": 0, "tradeState": room.TRADE_STATE_WAIT}
    # WAIT is 2 in TradeStateModel.TradeState.
    assert room.TRADE_STATE_WAIT == 2
    assert room.TRADE_STATE_START_WRITE_SAVE == 7 and room.TRADE_STATE_WRITEING_SAVE == 8


def test_the_ready_ok_is_the_only_trade_message_that_needs_a_flag_of_its_own():
    """The launcher's parser is built inside `main()`, so the source is read."""
    source = (pathlib.Path(__file__).resolve().parent.parent
              / "bin" / "bdsp_connect.py").read_text()
    assert '"--complete-trade", action=argparse.BooleanOptionalAction, default=False' in source
    assert "WRITES THE CONSOLE'S SAVE" in source
    assert "if not args.complete_trade:" in source


def test_the_security_phase_answer_mirrors_the_state_that_advances_theirs():
    """StateProc advances on `targetState`, so what we claim decides whether it moves at all."""
    m = room.mirror_trade_state
    # INIT is answered with WAIT: ReciveState's INIT case moves theirs to WAIT in the same call.
    assert m(room.TRADE_STATE_NONE) == room.TRADE_STATE_WAIT
    assert m(room.TRADE_STATE_INIT) == room.TRADE_STATE_WAIT
    assert m(room.TRADE_STATE_WAIT) == room.TRADE_STATE_WAIT
    assert m(room.TRADE_STATE_SEND_POKE) == room.TRADE_STATE_SEND_POKE
    # A CHILD console waits in SEND_READYOK for a peer state of 5 or 6; an echoed WAIT_POKE
    # deadlocks it.
    for theirs in (4, 5, 6, 7, 8, 9, 10):
        assert m(theirs) == room.TRADE_STATE_SEND_READYOK
    assert room.build_trade_ready_ok(room.TRADE_STATE_WAIT, is_trade_ok=1) \
        == bytes.fromhex("2100020102")
    assert room.TRADE_STATE_NAMES[room.TRADE_STATE_START_WRITE_SAVE] == "START_WRITE_SAVE"


def test_the_post_trade_question_is_built_the_way_the_console_asks_it():
    """`45 00 01 00`, repeated once a second: the shape from the wire, the value from opendpr's
    parameter name."""
    assert room.name(room.RETURN_SELECT) == "NetDataReturnSelectData"
    theirs = bytes.fromhex("45000100")
    assert room.parse(theirs)["fields"] == {"isReturnSelect": 0}
    ours = room.build_fields(room.RETURN_SELECT, 1)
    assert ours == bytes.fromhex("45000101")
    assert room.parse(ours)["fields"] == {"isReturnSelect": 1}

"""Sword/Shield application messages: the id, the protobuf body, and the sync conversation."""
import pytest

from pokeldn.swsh import pokemon, trade
from pokeldn import gen8


def test_the_five_payloads_this_project_measured_are_built_exactly():
    """Five payloads measured off a console capture."""
    assert trade.sync(trade.SYNC_PING, trade.PING).hex() == "610000000a00"
    assert trade.sync(trade.SYNC_PING, trade.PING_REPLY).hex() == "610000001200"
    assert trade.sync(trade.SYNC_PING, trade.PING_SYNCED).hex() == "610000001a00"
    assert trade.result().hex() == "60ea00000a00"
    assert trade.im_ready().hex() == "60ea000012020801"


def test_a_message_is_a_little_endian_id_and_a_body():
    assert trade.message(97, b"\x0a\x00") == bytes.fromhex("610000000a00")
    assert trade.parse(bytes.fromhex("610000000a00")) == (97, b"\x0a\x00")
    assert trade.parse(trade.im_ready()) == (60000, bytes.fromhex("12020801"))
    with pytest.raises(ValueError, match="message id"):
        trade.parse(b"\x61\x00\x00")


def test_im_ready_carries_a_bool_and_can_say_no():
    assert trade.im_ready(False).hex() == "60ea000012020800"
    assert trade.parse(trade.im_ready(False))[0] == trade.BLOCK


def test_varints_and_fields_follow_the_protobuf_wire_format():
    assert trade.varint(0) == b"\x00"
    assert trade.varint(1) == b"\x01"
    assert trade.varint(127) == b"\x7f"
    assert trade.varint(128) == b"\x80\x01"
    assert trade.varint(300) == b"\xac\x02"
    assert trade.field(1, b"") == b"\x0a\x00"
    assert trade.field(2, b"\xff") == b"\x12\x01\xff"
    assert trade.field_varint(1, 1) == b"\x08\x01"
    with pytest.raises(ValueError):
        trade.varint(-1)


def test_a_trade_message_refuses_anything_that_is_not_a_pk8():
    with pytest.raises(ValueError, match="not a PK8"):
        trade.pokemon_trade(b"\x00" * 100)


def test_the_sync_answers_are_keyed_and_valued_by_whole_payloads():
    for received, replies in trade.SYNC_ANSWERS.items():
        mid, _ = trade.parse(received)
        assert mid in trade.SYNC_IDS, f"{mid} answers a holder that is not a sync holder"
        assert replies, "an entry with no reply should not be an entry"
        for reply in replies:
            trade.parse(reply)                       # every reply is a well-formed message


def test_the_ping_answer_is_the_one_the_hardware_confirmed():
    """answering the ping walks the game forward; sending pingReply first stops it."""
    replies = trade.answers_for(bytes.fromhex("610000000a00"))
    assert [r.hex() for r in replies] == ["610000001200", "610000000a00"]
    assert trade.answers_for(bytes.fromhex("610000001a00"))[1] == trade.result()


def test_a_payload_with_no_rule_answers_nothing_and_is_reported():
    unknown = trade.sync(999, trade.PING)
    assert trade.answers_for(unknown) == ()
    assert trade.unanswered([unknown, bytes.fromhex("610000000a00")]) == [unknown]
    assert trade.unanswered([bytes.fromhex("610000000a00")]) == []


# the four distinct payloads the console sent on 0x7C, in the order it first sent them
SW70_ON_7C = ["610000000a00", "610000001200", "610000001a00", "60ea00000a00"]


def test_the_answer_policy_never_falls_silent_where_the_mirror_spoke():
    for hexed in SW70_ON_7C:
        said = bytes.fromhex(hexed)
        payload, queue = trade.next_answer(said)
        assert payload, f"nothing to say to {hexed}"
        if not trade.answers_for(said):
            assert payload == said, "with no rule the policy must still mirror"
            assert queue == []


def test_a_multi_payload_rule_goes_out_in_order_one_per_sequence():
    said = bytes.fromhex("610000000a00")
    first, queue = trade.next_answer(said)
    assert first.hex() == "610000001200"                  # pingReply
    second, queue = trade.next_answer(said, queue)
    assert second.hex() == "610000000a00"                 # then ping
    assert queue == []
    third, queue = trade.next_answer(said, queue)
    assert third.hex() == "610000001200"


def test_the_policy_changes_exactly_two_things_against_sw70s_mirror():
    """Against the mirror, only the first reply to `ping` changes, and `pingSynced` gains a `result{}`."""
    first_differs = [h for h in SW70_ON_7C
                     if trade.next_answer(bytes.fromhex(h))[0] != bytes.fromhex(h)]
    assert first_differs == ["610000000a00"], "only the answer to ping changes what we say first"

    follow_ups = {h: trade.next_answer(bytes.fromhex(h))[1] for h in SW70_ON_7C}
    assert follow_ups["610000001a00"] == [trade.result()], "pingSynced gains a result{} behind it"
    assert follow_ups["610000000a00"] == [bytes.fromhex("610000000a00")]
    assert follow_ups["610000001200"] == [] and follow_ups["60ea00000a00"] == []


# Off the wire: the trade RPC pair the console sent when the trade screen opened.
SW75_RPC_10000 = bytes.fromhex(
    "5e9c00000a19081e10904e188080a08a8fc4c8cdeb0120c0502a0400000000")
SW75_RPC_20000 = bytes.fromhex(
    "5e9c00000a1a081e10a09c01188080a08a8fc4c8cdeb0120c0502a04000018fc")
SW75_HOST_STATION = 16977200745185542144
OUR_STATION = 1317762632229847040


def test_the_consoles_own_rpcs_are_read_and_rebuilt_byte_for_byte():
    for raw, base, body in ((SW75_RPC_10000, 10000, "00000000"),
                            (SW75_RPC_20000, 20000, "000018fc")):
        got = trade.parse_rpc(raw)
        assert got["offset"] == 30, "40030 is 40000 + 30 and the message says so"
        assert got["base"] == base
        assert got["station_id"] == SW75_HOST_STATION, "field 3 is the SENDER's station id"
        assert got["clock"] == 10304
        assert got["body"].hex() == body
        assert trade.build_rpc(got["offset"], got["base"], got["station_id"],
                               got["clock"], got["body"]) == raw


def test_the_pair_carries_both_bases_and_the_same_clock():
    a, b = trade.parse_rpc(SW75_RPC_10000), trade.parse_rpc(SW75_RPC_20000)
    assert (a["base"], b["base"]) == trade.RPC_BASES == (10000, 20000)
    assert a["clock"] == b["clock"], "a pair shares its clock"
    assert a["station_id"] == b["station_id"]


def test_our_answer_carries_our_station_id_and_advances_the_clock():
    answer = trade.answer_rpc(SW75_RPC_10000, OUR_STATION, clock_delta=5)
    got = trade.parse_rpc(answer)
    assert got["station_id"] == OUR_STATION, "it must not be the console's own id"
    assert got["clock"] == 10304 + 5
    assert (got["offset"], got["base"], got["body"]) == (30, 10000, b"\x00\x00\x00\x00")


def test_answering_something_that_is_not_an_rpc_gives_nothing():
    assert trade.answer_rpc(trade.im_ready(), OUR_STATION) is None
    assert trade.parse_rpc(bytes.fromhex("610000000a00")) is None
    assert trade.parse_rpc(trade.message(trade.RPC_ENVELOPE, b"\x08\x01")) is None


def test_the_policy_answers_a_trade_rpc_by_rebuilding_it_not_by_echoing_it():
    """Echoing an RPC would hand the console its own station id back - the one field that moves."""
    payload, queue = trade.next_answer(SW75_RPC_10000, station_id=OUR_STATION)
    assert payload != SW75_RPC_10000, "an echo is exactly what must not happen here"
    assert trade.parse_rpc(payload)["station_id"] == OUR_STATION
    assert queue == []
    assert trade.next_answer(SW75_RPC_10000)[0] == SW75_RPC_10000
    assert trade.next_answer(bytes.fromhex("610000000a00"),
                             station_id=OUR_STATION)[0].hex() == "610000001200"


def test_an_offer_is_read_and_rebuilt_from_the_record_it_carries():
    """A console message: 20030, PokemonTradeDataHolder{pokemon{serializePokemonParam}}."""
    plain = bytearray(bytes(range(256)) * 2)[:gen8.SIZE_PARTY]
    plain[0x04:0x06] = b"\x00\x00"
    pk8 = pokemon.encrypt(bytes(plain))

    offer = trade.pokemon_trade(pk8)
    assert trade.parse(offer)[0] == trade.POKEMON_TRADE == 20030
    assert trade.offered_pokemon(offer) == pk8
    assert len(offer) == len(pk8) + 10, "four bytes of id and two nested length-delimited fields"


def test_an_offer_is_answered_with_an_offer_and_never_with_an_echo():
    def a_pk8(species):
        plain = bytearray(bytes(range(256)) * 2)[:gen8.SIZE_PARTY]
        plain[0x04:0x06] = b"\x00\x00"
        struct_pack = __import__("struct").pack_into
        struct_pack("<H", plain, gen8.OFF_SPECIES, species)
        return pokemon.encrypt(bytes(plain))

    theirs, ours = a_pk8(841), a_pk8(94)
    offer = trade.pokemon_trade(theirs)
    reply, queue = trade.next_answer(offer, offer_pk8=ours)
    assert reply != offer, "echoing would offer the console back its own Pokemon"
    assert trade.offered_pokemon(reply) == ours
    assert queue == []
    assert trade.next_answer(offer)[0] == offer


def test_something_that_is_not_an_offer_yields_no_pokemon():
    assert trade.offered_pokemon(trade.im_ready()) is None
    assert trade.offered_pokemon(trade.message(trade.POKEMON_TRADE, b"\x08\x01")) is None
    assert trade.offered_pokemon(trade.message(trade.POKEMON_TRADE,
                                               trade.field(1, trade.field(1, b"short")))) is None


def test_no_reader_raises_on_a_short_message():
    """A reader on a live run returns None on a short message; the console sends three bytes at the
    confirmation prompt."""
    for payload in (b"", b"\x00", b"\x3e\x4e\x00", b"\x5e\x9c\x00"):
        assert trade.offered_pokemon(payload) is None
        assert trade.parse_rpc(payload) is None
        assert trade.answer_rpc(payload, OUR_STATION) is None
        assert trade.answers_for_offer(payload, b"x" * 0x158) == ()
        assert trade.next_answer(payload, station_id=OUR_STATION)[0] == payload


SW83_RPC_PAIR = (
    "5e9c00000a1a081e10904e188080a08a8fc4c8cdeb0120fef6012a0400000000",
    "5e9c00000a1b081e10a09c01188080a08a8fc4c8cdeb0120fef6012a04000018fc",
)


@pytest.mark.parametrize("hexed", SW83_RPC_PAIR)
def test_the_generalised_builder_still_rebuilds_the_consoles_own_pair(hexed):
    """The envelope id is 40000 + offset, and offset 30 has to keep giving 40030 exactly."""
    raw = bytes.fromhex(hexed)
    got = trade.parse_rpc(raw)
    assert got["offset"] == trade.OFFER_OFFSET
    assert trade.build_rpc(got["offset"], got["base"], got["station_id"], got["clock"],
                           got["body"]) == raw


def test_a_selection_pair_is_the_same_envelope_at_offset_fifty():
    station, clock = 0x1249A221D8580000, 31614
    pair = trade.build_rpc_pair(trade.SELECTION_OFFSET, station, clock)
    assert len(pair) == 2
    for member, base, body in zip(pair, trade.RPC_BASES, trade.RPC_PAIR_BODIES):
        mid, _ = trade.parse(member)
        assert mid == trade.RPC_ENVELOPE_BASE + trade.SELECTION_OFFSET == 40050
        fields = trade._read_fields(trade._read_fields(member[4:])[1])
        assert fields[trade.RPC_OFFSET] == trade.SELECTION_OFFSET
        assert fields[trade.RPC_BASE] == base
        assert fields[trade.RPC_STATION] == station
        assert fields[trade.RPC_CLOCK] == clock
        assert fields[trade.RPC_BODY] == body


def test_the_pair_bodies_are_the_consoles_own():
    # nxldn-lab's 40050 pair carries the same two bodies: they belong to the envelope.
    assert [trade.parse_rpc(bytes.fromhex(h))["body"] for h in SW83_RPC_PAIR] == \
        list(trade.RPC_PAIR_BODIES)


def test_the_confirmation_opener_rebuilds_nxldn_labs_bytes_from_our_own_registry():
    """`382700000a00` is nxldn-lab's confirmation opener: 10000 + 40 with `ping`, derived from the
    registry at 0x10dc150."""
    assert trade.open_content(trade.CONFIRMATION_OFFSET) == bytes.fromhex("382700000a00")
    assert trade.CONTENT_BASE_LOW + trade.CONFIRMATION_OFFSET == 10040
    mid, body = trade.parse(trade.open_content(trade.SELECTION_OFFSET))
    assert mid == 10050 and body == trade.field(trade.PING, b"")


def test_a_content_fifty_envelope_carries_the_pk8_in_field_five():
    pk8 = bytes(range(256)) * 2
    pk8 = pk8[:0x158]
    m = trade.build_rpc_pokemon(trade.SELECTION_OFFSET, 20000, 0x1249A221D8580000, 1234, pk8)
    assert trade.parse(m)[0] == 40050
    inner = trade._read_fields(trade._read_fields(trade.parse(m)[1])[1])
    assert inner[trade.RPC_POKEMON_FIELD] == pk8
    assert inner[trade.RPC_OFFSET] == trade.SELECTION_OFFSET


def test_the_content_fifty_offer_carries_our_owner_id():
    """Content 50's receive handler `0x010d5e40` drops an offer whose ownerId (field 3) names no station."""
    pk8 = (bytes(range(256)) * 2)[:0x158]
    owner = 0x1249A221D8580000
    m = trade.build_rpc_pokemon(trade.SELECTION_OFFSET, 20000, owner, 1234, pk8)
    inner = trade._read_fields(trade._read_fields(trade.parse(m)[1])[1])
    assert inner[trade.RPC_STATION] == owner
    assert trade.parse_rpc(m)["station_id"] == owner
    holder = trade.pokemon_offer(trade.SELECTION_OFFSET, pk8)
    assert trade.RPC_STATION not in trade._read_fields(trade.parse(holder)[1])


def test_the_mirror_offer_has_the_consoles_own_field_set():
    """The console's own offer `729c00000ae002083220e2202ad802<344 bytes>` carries fields 1, 4 and 5."""
    theirs = bytes.fromhex("729c00000ae002083220e2202ad802") + bytes(0x158)
    assert sorted(trade._read_fields(trade._read_fields(trade.parse(theirs)[1])[1])) == [1, 4, 5]
    ours = trade.mirror_pokemon_offer(trade.SELECTION_OFFSET, 4194, bytes(0x158))
    assert sorted(trade._read_fields(trade._read_fields(trade.parse(ours)[1])[1])) == [1, 4, 5]
    assert len(ours) == len(theirs)


def test_the_high_base_offer_is_the_box_phases_own_shape_one_content_over():
    """The box Pokemon rides 20030 (`3e4e00000adb020ad802<344>`); this is the same message at offset 50."""
    pk8 = bytes(0x158)
    m = trade.pokemon_offer_high(trade.SELECTION_OFFSET, pk8)
    assert trade.parse(m)[0] == 20050
    box = trade.pokemon_trade(pk8)
    assert m[4:] == box[4:]            # the same body, only the id differs
    assert trade.offered_pokemon(box) == pk8


def test_a_content_fifty_envelope_refuses_anything_that_is_not_a_pk8():
    with pytest.raises(ValueError):
        trade.build_rpc_pokemon(trade.SELECTION_OFFSET, 20000, 1, 1, bytes(100))


def test_answer_rpc_refuses_a_member_with_no_base():
    """A 40050 member with no base field is not answered; `answer_rpc` never raises."""
    no_base = bytes.fromhex("729c00000a0a08322a0400000000")
    assert trade.parse_rpc(no_base)["base"] is None
    assert trade.answer_rpc(no_base, 0x1234, 5) is None


def test_the_confirmation_content_takes_a_command_and_not_a_pokemon():
    """Content 40 takes `SyncSaveDataHolder{1 SyncCommand}` over `SyncCommand{1 int32 data}`
    [`0x010df6d0`, `0x010debc0`]."""
    assert trade.sync_command(trade.CONFIRMATION_OFFSET, 1) == bytes.fromhex("382700000a020801")
    mid, body = trade.parse(trade.sync_command(trade.CONFIRMATION_OFFSET, 0))
    assert mid == 10040
    assert body == trade.field(trade.SYNC_SAVE_COMMAND,
                               trade.field_varint(trade.SYNC_COMMAND_DATA, 0))


def test_every_command_the_consoles_own_machine_sends_round_trips():
    """`0x010dae70` is the only caller of the send `0x010db840`, and it passes 0, 1, 2 and 3."""
    assert sorted(trade.SYNC_COMMANDS) == [0, 1, 2, 3]
    for data in trade.SYNC_COMMANDS:
        assert trade.parse_sync_command(trade.sync_command(trade.CONFIRMATION_OFFSET, data)) == data


def test_the_ladder_needs_every_command_and_the_fourth_one_ends_it():
    """`0x010dbf40` maps phase 0..4 onto the state that sends the next command; phase 4 is the teardown."""
    assert sorted(trade.SYNC_LADDER) == [0, 1, 2, 3, 4]
    for data in sorted(trade.SYNC_COMMANDS):
        assert trade.sync_announced_phase(data) == data + 1
        assert trade.sync_announced_phase(data) in trade.SYNC_LADDER
        assert trade.SYNC_LADDER[data] != trade.SYNC_LADDER[4]
    assert trade.sync_announced_phase(3) == 4
    assert trade.SYNC_LADDER[4] == 13
    assert 4 not in trade.SYNC_COMMANDS


def test_the_three_steps_sx52e_and_sx53_measured_read_as_a_phase_and_an_announcement():
    """Console elementId-20000 bodies: the low u16 is the adopted phase (`element+0xac`), the high
    the announced one."""
    measured = [("00000100", (0, 1)), ("01000100", (1, 1)), ("01000200", (1, 2))]
    for body, want in measured:
        got = trade.parse_sync_step(bytes.fromhex(body))
        assert got == want
        assert got[1] in trade.SYNC_LADDER
        assert got[1] >= got[0]
    phases = [trade.parse_sync_step(bytes.fromhex(b))[0] for b, _ in measured]
    assert phases == [0, 1, 1]


def test_the_phase_answer_writes_the_low_half_and_keeps_the_high_one():
    """`--confirm-phase` writes the low u16 only; the high half is the announcement `0x006d3690` publishes."""
    measured = bytes.fromhex("01000200")                       # phase 1, announced 2
    payload = trade.build_rpc(trade.CONFIRMATION_OFFSET, trade.RPC_BASES[1],
                              0x1249A221D8580000, 0x25A0, measured)
    reply = trade.answer_rpc_with_phase(payload, 0x1249A221D8580000, 2, clock_delta=5)
    got = trade.parse_rpc(reply)
    assert trade.parse_sync_step(got["body"]) == (2, 2)
    assert got["clock"] == 0x25A0 + 5
    assert got["offset"] == trade.CONFIRMATION_OFFSET and got["base"] == trade.RPC_BASES[1]
    echoed = trade.parse_rpc(trade.answer_rpc(payload, 0x1249A221D8580000))
    assert trade.parse_sync_step(echoed["body"]) == (1, 2)


def test_the_phase_answer_refuses_anything_that_is_not_a_four_byte_step():
    """Two-byte step bodies are real (`0000`, `0100`); the console's handler drops them at `cmp x2, #4`."""
    short = trade.build_rpc(trade.CONFIRMATION_OFFSET, trade.RPC_BASES[1], 1, 2,
                            bytes.fromhex("0100"))
    assert trade.answer_rpc_with_phase(short, 1, 3) is None
    assert trade.answer_rpc_with_phase(b"", 1, 3) is None
    assert trade.sync_step(1, 0xFC18) == bytes.fromhex("010018fc")


def test_a_step_reader_takes_only_four_bytes_and_never_raises():
    """A step reader never raises on a live run."""
    assert trade.parse_sync_step(None) is None
    assert trade.parse_sync_step(b"") is None
    assert trade.parse_sync_step(b"\x00\x00\x01") is None
    assert trade.parse_sync_step(bytearray.fromhex("01000200")) == (1, 2)


def test_a_negative_command_is_refused_rather_than_encoded():
    """A negative int32 is ten varint bytes, a shape the console has never sent."""
    with pytest.raises(ValueError):
        trade.sync_command(trade.CONFIRMATION_OFFSET, -1)


def test_the_command_reader_takes_any_content_and_no_reader_raises():
    """The holder shape is the content's; a reader never raises."""
    assert trade.parse_sync_command(trade.sync_command(trade.SELECTION_OFFSET, 2)) == 2
    assert trade.parse_sync_command(trade.open_content(trade.CONFIRMATION_OFFSET)) is None
    assert trade.parse_sync_command(trade.im_ready()) is None
    assert trade.parse_sync_command(b"\x38\x27") is None
    assert trade.parse_sync_command(b"") is None

"""The launcher's own send path, offline - the exact function a hardware run will call.

`tests/test_pia4.py` proves the framing against the console's own packets; this proves that
`swsh_connect.wrap` puts a Local Protocol ack inside it correctly, so the run spends its association
on a question rather than on a typo. There is no capture of one of our version-4 packets yet, so
this is a self-consistency check with the receiver's derivation on the other side of it.
"""

import struct

import pytest

import swsh_connect

from pokeldn.ldn import (local_protocol as lp, mesh_protocol as mesh, pia4, reliable5,
                        rtt_protocol as rtt, station_protocol as stp)
from pokeldn import gen8
from pokeldn.swsh import trade as swsh_trade
from pokeldn.swsh.session import packet_iv, session_keys

APP_DATA = bytes.fromhex("0330112400000000051800008b718ac6")     # A run's own advertisement
OUR_MAC = bytes.fromhex("7e5f4c3b2a19")


class _Net:
    application_data = APP_DATA


def _read_back(packet, mac=OUR_MAC):
    """Everything the console does with a packet of ours, in its order."""
    keys = session_keys(_Net())
    h = pia4.PiaHeader4.parse(packet)
    plain = pia4.decrypt_payload(keys.session_key, packet_iv(keys, mac, h.nonce8, h.station),
                                 pia4.ciphertext(packet), h.tag)
    assert plain is not None, "the tag did not verify"
    header, body = pia4.parse_messages(plain)[0]
    return h, pia4.parse_message_header(header), body


def _ack(station=0, nonce8=b"\x01" * 8, seq=7):
    keys = session_keys(_Net())
    return swsh_connect.wrap(keys, OUR_MAC, stp.ldn_constant_id(OUR_MAC), nonce8,
                             lp.build_ack(seq), lp.PROTOCOL, station)


def test_the_ack_the_run_sends_reads_back_as_an_ack():
    h, fields, body = _read_back(_ack())
    assert h.version == 4 and h.encrypted and len(h.tag) == pia4.TAG_SIZE
    assert fields["protocol"] == lp.PROTOCOL and fields["flags"] == pia4.MESSAGE_FLAGS
    assert fields["source"] == stp.ldn_constant_id(OUR_MAC)
    assert lp.parse_ack(body) == 7


def test_the_station_byte_reaches_the_header_and_the_iv_together():
    """The sweep only reads if the two move as one; a header saying 1 and an IV built on 0 would
    fail the tag and look exactly like the console ignoring us."""
    for station in (0, 1, 2):
        h, _, body = _read_back(_ack(station=station))
        assert h.station == station
        assert lp.parse_ack(body) == 7


def test_the_packet_is_padded_the_way_the_console_pads_its_own():
    """0xFF to a multiple of sixteen, which is what a run's 160-byte ciphertext measures."""
    packet = _ack()
    assert (len(packet) - pia4.HEADER_SIZE) % 16 == 0
    keys = session_keys(_Net())
    h = pia4.PiaHeader4.parse(packet)
    plain = pia4.decrypt_payload(keys.session_key, packet_iv(keys, OUR_MAC, h.nonce8, h.station),
                                 pia4.ciphertext(packet), h.tag)
    used = pia4.MESSAGE_HEADER_SIZE + 0x14                       # the ack is twenty bytes
    assert set(plain[used:]) <= {0xFF}


def _join(ack_id=0x11223344, station=0, nonce8=b"\x02" * 8, port=0):
    keys = session_keys(_Net())
    return swsh_connect.wrap(keys, OUR_MAC, stp.ldn_constant_id(OUR_MAC), nonce8,
                             mesh.build_join_request(ack_id), mesh.PROTOCOL, station, port=port)


def test_the_join_request_the_run_sends_is_what_0x017c1700_checks():
    """Sword's type-1 handler reads byte [1] and the last four bytes, and nothing else."""
    h, fields, body = _read_back(_join())
    assert fields["protocol"] == mesh.PROTOCOL == 0x18
    assert body == bytes([mesh.JOIN_REQUEST, 0xFD]) + struct.pack(">I", 0x11223344)
    assert mesh.read_ack_id(body) == 0x11223344


def test_the_join_travels_on_the_unreliable_port_by_default():
    # `--join-port` exists because the update mesh uses the reliable one and the join does not;
    # the default has to be the port the request is actually sent on.
    args = swsh_connect.build_parser().parse_args([])
    assert args.join_port == mesh.PORT_UNRELIABLE == 0
    assert args.join_station_index == mesh.STATION_INDEX_INVALID == 0xFD
    _, fields, _ = _read_back(_join(port=args.join_port))
    assert fields["port"] == 0


# --------------------------------------------------------------------------- answering a run
# The two protocols the console left unanswered. Both send paths are checked as BYTES, decrypted
# back through the console's own derivation, because that is what a run will actually put on the air.

SW29_RTT = bytes.fromhex("000000000000000000000e7840e6df87")


def _data(payload, protocol, station=0, nonce8=b"\x03" * 8, destination=1, flags=0x01):
    keys = session_keys(_Net())
    return swsh_connect.wrap(keys, OUR_MAC, stp.ldn_constant_id(OUR_MAC), nonce8, payload,
                             protocol, station, message_flags=flags, destination=destination)


def test_the_rtt_answer_is_sixteen_bytes_and_echoes_what_we_do_not_read():
    h, fields, body = _read_back(_data(rtt.response_for_v4(SW29_RTT), rtt.PROTOCOL))
    assert fields["protocol"] == rtt.PROTOCOL == 0x58
    assert len(body) == rtt.SIZE_V4 == 16
    assert body[0] == rtt.RESPONSE and body[1:] == SW29_RTT[1:]
    assert rtt.parse_v4(body)["timestamp"] == rtt.parse_v4(SW29_RTT)["timestamp"]


def test_our_data_messages_carry_the_bitmap_bit_for_the_console():
    # the console sends 2 to us at station index 1; the bit for station 0 is 1
    _, fields, _ = _read_back(_data(rtt.response_for_v4(SW29_RTT), rtt.PROTOCOL))
    assert fields["destination"] == 1
    assert swsh_connect.build_parser().parse_args([]).data_destination == 1


def test_replaying_sw29s_own_stream_acks_it_through_sequence_twenty():
    """The 1637 messages a run received are 20 sequence ids. One ack per advance, never a re-ack."""
    seen, acks, through = set(), [], 0
    for seq in [1] + list(range(2, 21)) * 8:          # the retransmit train, in arrival order
        seen.add(seq)
        nxt = reliable5.contiguous_through(seen, through)
        if nxt != through:
            through = nxt
            acks.append(reliable5.build_ack_message(through + 1, lowest_pending=1))
    assert through == 20
    assert len(acks) == 20                            # one per advance, not one per message
    last = reliable5.parse(acks[-1])
    assert last["is_ack"] and last["sequence_id"] == reliable5.ACK_SEQUENCE == 0xFFFF
    entry = reliable5.parse_ack_payload(last["payload"])["entries"][0]
    assert entry["ack_id"] == 21 and entry["field_0x50"] == 20
    assert entry["mask"] == b"\0" * 16                # a contiguous run leaves nothing in the mask


def test_a_gap_stops_the_run_rather_than_being_skipped():
    assert reliable5.contiguous_through({1, 2, 4, 5}) == 2
    assert reliable5.contiguous_through({2, 3}) == 0   # nothing contiguous from the start
    assert reliable5.contiguous_through({2, 3}, start=1) == 3


def test_the_openers_and_the_commands_are_different_ids():
    assert swsh_trade.parse(swsh_trade.open_content(40))[0] == 10040
    assert swsh_trade.parse(swsh_trade.box_sync_state(4))[0] == swsh_trade.POKEMON_TRADE


# --- Selection phase messages -------------------------------

def test_advancing_the_pair_moves_the_clock_and_nothing_else():
    """The second copy of a pair member must differ from the first in the clock alone - that is
    what makes it a new state rather than a retransmission."""
    member = swsh_trade.build_rpc(50, 10000, 0xdeadbeef, 0x1cb4)
    first = swsh_trade.answer_rpc(member, 0x1249a221d8580000, 5)
    again = swsh_trade.answer_rpc(member, 0x1249a221d8580000, 5 + 2)
    assert first is not None and again is not None and first != again
    a, b = swsh_trade.parse_rpc(first), swsh_trade.parse_rpc(again)
    assert b["clock"] - a["clock"] == 2
    for key in ("envelope", "offset", "base", "station_id", "body"):
        assert a[key] == b[key], key


def test_the_selection_start_cue_is_the_console_payload_we_capture():
    """The trigger is id 130's pingSynced, byte for byte - the payload sx45r1_6 records at t=31.30,
    0.3 s ahead of the console's own 40050 burst."""
    assert swsh_trade.sync(130, swsh_trade.PING_SYNCED) == bytes.fromhex("820000001a00")


def test_the_selection_start_pair_is_the_shape_nxldn_lab_sends():
    """Two members on 40050, elementId 10000 then 20000, our ownerId in both, and the console's own
    two four-byte bodies."""
    pair = swsh_trade.build_rpc_pair(swsh_trade.SELECTION_OFFSET, 0x1249a221d8580000, 1511)
    assert len(pair) == 2
    got = [swsh_trade.parse_rpc(p) for p in pair]
    assert [g["envelope"] for g in got] == [40050, 40050]
    assert [g["offset"] for g in got] == [50, 50]
    assert [g["base"] for g in got] == list(swsh_trade.RPC_BASES)
    assert all(g["station_id"] == 0x1249a221d8580000 for g in got)
    assert [bytes(g["body"]) for g in got] == list(swsh_trade.RPC_PAIR_BODIES)


def test_the_content_opener_can_carry_the_pokemon():
    """the empty opener on content 50's 10000-base holder was accepted AS our Pokemon - the
    console reached the confirmation phase and offered the player an Oeuf. Same holder, same
    moment; the flag decides whether the body is empty or a PK8."""
    args = swsh_connect.build_parser().parse_args([])
    assert args.open_content_offer is False
    assert swsh_connect.build_parser().parse_args(["--open-content-offer"]).open_content_offer
    pk8 = bytes(0x158)
    empty, carried = swsh_trade.open_content(50), swsh_trade.pokemon_offer(50, pk8)
    assert empty == bytes.fromhex("422700000a00")
    assert carried[:4] == empty[:4] and len(carried) > len(empty)


def test_the_confirmation_cue_is_the_selection_cue_one_content_along():
    """A run's last unanswered message is a 40040/20000 member whose four-byte body ends `0100` -
    the same shape that, on 40050, was the cue to send our Pokemon. The two differ in the envelope
    alone, which is why the branch keys on it and why one shared latch swallowed the second."""
    body = bytes.fromhex("00000100")
    selection = swsh_trade.build_rpc(swsh_trade.SELECTION_OFFSET, swsh_trade.RPC_BASES[1],
                                     0x1249a221d8580000, 0x14c4, body)
    confirmation = swsh_trade.build_rpc(swsh_trade.CONFIRMATION_OFFSET, swsh_trade.RPC_BASES[1],
                                        0x1249a221d8580000, 0x14c4, body)
    a, b = swsh_trade.parse_rpc(selection), swsh_trade.parse_rpc(confirmation)
    assert a["envelope"] == 40050 and b["envelope"] == 40040
    assert bytes(a["body"]) == bytes(b["body"]) == body
    assert a["base"] == b["base"] == swsh_trade.RPC_BASES[1]


def test_the_confirmation_answer_rides_the_content_holder_and_the_status_the_envelope():
    """Two windows, as the selection phase uses: the command goes on the content's 10000-base
    holder on port 0, and the status answer is a 40040 envelope on port 1."""
    command = swsh_trade.sync_command(swsh_trade.CONFIRMATION_OFFSET, 1)
    assert swsh_trade.parse(command)[0] == 10040
    member = swsh_trade.build_rpc(swsh_trade.CONFIRMATION_OFFSET, swsh_trade.RPC_BASES[1],
                                  0x1249a221d8580000, 0x14c4, bytes.fromhex("00000100"))
    status = swsh_trade.answer_rpc(member, 0x1249a221d8580000, 5)
    assert status is not None and swsh_trade.parse_rpc(status)["envelope"] == 40040


# A run's own 40040 traffic, out of `scratchpad/sx51b_1_cx.log.gz`. The first two are the cue - a
# four-byte body ending `0100` on elementId 20000 - and the third is the `18fc` every other member
# of the pair carries. Real bytes, so the condition is tested against what the console actually
# sent rather than against a reconstruction of it.
SX51B_CONFIRMATION_CUES = (
    "689c00000a19082810a09c01188080e0c29dc4e8a41220c9142a0400000100",
    "689c00000a1a082810a09c01188080a08a8fc4c8cdeb0120c4142a0400000100")
SX51B_CONFIRMATION_PAIR = "689c00000a19082810a09c01188080e0c29dc4e8a41220a5142a04000018fc"


def _is_confirmation_cue(payload):
    """The launcher's `--confirm-command` condition, transcribed."""
    member = swsh_trade.parse_rpc(bytes.fromhex(payload))
    return (member is not None
            and member["envelope"] == (swsh_trade.RPC_ENVELOPE_BASE
                                       + swsh_trade.CONFIRMATION_OFFSET)
            and member["base"] == swsh_trade.RPC_BASES[1]
            and len(member["body"]) == 4 and bytes(member["body"])[-2:] == b"\x01\x00")


def test_the_condition_fires_on_sx51bs_own_confirmation_cues():
    """Both of the run's `0100` members on 40040 match, and the pair's `18fc` member does not."""
    assert all(_is_confirmation_cue(p) for p in SX51B_CONFIRMATION_CUES)
    assert not _is_confirmation_cue(SX51B_CONFIRMATION_PAIR)
    first = swsh_trade.parse_rpc(bytes.fromhex(SX51B_CONFIRMATION_CUES[0]))
    assert first["offset"] == swsh_trade.CONFIRMATION_OFFSET and first["clock"] == 2633


def test_the_confirmation_hash_is_a_four_byte_body_on_the_40040_envelope():
    """A run's own bytes: the hash arrives on elementId 10000 of 40040, four bytes, and it is
    neither of the pair's two constants - which is what the re-arm has to trigger on."""
    hashed = swsh_trade.parse_rpc(bytes.fromhex(
        "689c00000a1a082810904e188080a08a8fc4c8cdeb01208e80022a04b22d6f50"))
    assert hashed["envelope"] == swsh_trade.RPC_ENVELOPE_BASE + swsh_trade.CONFIRMATION_OFFSET
    assert hashed["base"] == swsh_trade.RPC_BASES[0]
    assert len(hashed["body"]) == 4
    assert bytes(hashed["body"]) not in swsh_trade.RPC_PAIR_BODIES


def test_the_stall_abort_is_off_until_the_ladder_has_started():
    """A run that never reaches the confirmation content holds for its full time.

    two runs both ended with the console penalised, and both times the cause was the same:
    the ladder stalled and we kept the transport alive and acking until the GAME's own timeout
    declared the trade failed. A link that stops instead is a dropped connection, which is a
    different thing for the console to report.
    """
    assert swsh_connect.stall_abort(None, 100.0, 10.0) is False   # never started
    assert swsh_connect.stall_abort(40.0, 45.0, 10.0) is False    # started, still moving
    assert swsh_connect.stall_abort(40.0, 50.0, 10.0) is True     # started, then quiet
    assert swsh_connect.stall_abort(40.0, 500.0, 0.0) is False    # the flag is off
    assert swsh_connect.stall_abort(None, 500.0, 0.0) is False


def test_a_finished_ladder_is_not_a_stalled_one():
    """A run climbed the whole ladder, traded, and then the abort dropped the link on it.

    Phase 4 is the teardown rung - `0x010dbf40` sends nothing from it - so the console goes quiet
    the moment it succeeds, which is byte for byte what a stall looks like from outside. The run
    has to hold through whatever follows: the save, the summary, the migration.
    """
    assert swsh_connect.stall_abort(40.0, 60.0, 15.0) is True
    assert swsh_connect.stall_abort(40.0, 60.0, 15.0, final_phase_seen=True) is False
    assert swsh_connect.LADDER_FINAL_PHASE == 4


class _OfferArgs:
    """The four flags `offer_edits` reads, with the launcher's own defaults."""

    def __init__(self, **over):
        self.offer_slot = 1
        self.offer_species = self.offer_nickname = self.offer_ot = self.offer_ivs = None
        self.offer_ability = self.offer_moves = self.offer_level = self.offer_experience = None
        self.__dict__.update(over)


def test_no_offer_flags_means_the_record_goes_as_it_came():
    assert swsh_connect.offer_edits(_OfferArgs()) == {}


def test_the_offer_flags_become_gen8_write_fields():
    args = _OfferArgs(offer_species=25, offer_nickname="PKCAMP", offer_ot="PkCamp",
                      offer_ivs="31,31,31,31,31,31")
    assert swsh_connect.offer_edits(args) == {"species": 25, "nickname": "PKCAMP",
                                              "ot_name": "PkCamp", "ivs": [31] * 6}


def test_an_ability_and_four_moves_ride_with_the_species():
    args = _OfferArgs(offer_species=93, offer_ability=26, offer_moves="164,247,0,0")
    assert swsh_connect.offer_edits(args) == {"species": 93, "ability": 26,
                                              "moves": [164, 247, 0, 0]}
    for bad in ("164,247,482", "164,247,482,411,1", "70000,0,0,0"):
        with pytest.raises(ValueError):
            swsh_connect.offer_edits(_OfferArgs(offer_moves=bad))


def test_the_level_byte_and_the_experience_word_are_separate_edits():
    args = _OfferArgs(offer_level=50, offer_experience=1059860)
    assert swsh_connect.offer_edits(args) == {"level": 50, "experience": 1059860}
    for bad in (0, 101):
        with pytest.raises(ValueError):
            swsh_connect.offer_edits(_OfferArgs(offer_level=bad))


def test_a_built_record_without_a_slot_is_refused_before_the_radio():
    with pytest.raises(ValueError):
        swsh_connect.offer_edits(_OfferArgs(offer_slot=0, offer_species=25))


def test_six_ivs_of_0_to_31_or_nothing():
    for bad in ("31,31,31", "31,31,31,31,31,32", "-1,0,0,0,0,0"):
        with pytest.raises(ValueError):
            swsh_connect.offer_edits(_OfferArgs(offer_ivs=bad))


def test_a_name_that_will_not_fit_is_refused_before_the_radio():
    with pytest.raises(ValueError):
        swsh_connect.offer_edits(_OfferArgs(offer_nickname="X" * 13))
    assert swsh_connect.offer_edits(_OfferArgs(offer_nickname="X" * 12))["nickname"] == "X" * 12


def test_a_record_loads_from_any_of_the_four_shapes_a_pk8_file_takes():
    """Stored or party, encrypted or PKHeX's plain export, all become one plain party record."""
    plain = bytearray(gen8.SIZE_PARTY)
    struct.pack_into("<I", plain, 0, 0x8580A635)
    struct.pack_into("<H", plain, gen8.OFF_SPECIES, 841)
    plain[gen8.OFF_NICKNAME:gen8.OFF_NICKNAME + 4] = "Po".encode("utf-16-le")
    struct.pack_into("<H", plain, 6, gen8.checksum(plain))
    plain = bytes(plain)
    party_plain, stored_plain = plain, plain[:gen8.SIZE_STORED]
    for shape in (party_plain, stored_plain, gen8.encrypt(party_plain), gen8.encrypt(stored_plain)):
        loaded = gen8.load(shape)
        assert len(loaded) == gen8.SIZE_PARTY
        assert gen8.read(loaded)["species"] == 841
    assert gen8.load(stored_plain)[:gen8.SIZE_STORED] == stored_plain

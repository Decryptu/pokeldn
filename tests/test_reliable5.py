"""Pia 5.29-5.43's reliable sliding window (protocol 0x7c); the fixtures are one capture's whole
reliable side."""

import os

import pytest

from pokeldn.ldn import reliable5 as rl


SP35_FIRST = bytes.fromhex("0f00001400010001000100110800315a005a611fc1cad38132e7ddb840")
SP35_SECOND = bytes.fromhex("07000004000200010012000123")


def test_the_first_captured_message_is_a_whole_application_message():
    out = rl.parse(SP35_FIRST)
    assert out["flags"] == 0x0F
    assert out["flag_names"] == ["APPLICATION_DATA", "START", "END", "INITIALIZED"]
    assert out["stream_id"] == 0
    assert out["payload_size"] == 20 and len(out["payload"]) == 20
    assert out["sequence_id"] == 1 and out["lowest_pending"] == 1
    assert out["destination_bits"] == 0 and out["bitmap"] == []
    assert out["header_size"] == 9 and out["truncated"] is False and out["is_ack"] is False
    assert out["payload"].hex() == "01001108 00315a00 5a611fc1 cad38132 e7ddb840".replace(" ", "")


def test_the_second_captured_message_is_the_next_sequence_id():
    out = rl.parse(SP35_SECOND)
    assert out["flag_names"] == ["APPLICATION_DATA", "START", "END"]   # no INITIALIZED this time
    assert out["sequence_id"] == 2 and out["lowest_pending"] == 1
    assert out["payload"] == bytes.fromhex("12000123")


def test_the_header_round_trips():
    head = rl.build_header(0x0F, sequence_id=1, payload_size=20, lowest_pending=1)
    assert head == SP35_FIRST[:9]
    assert rl.parse(head + SP35_FIRST[9:])["payload"] == SP35_FIRST[9:]
    with_bits = rl.build_header(0x08, 5, 0, destination_bits=3, bitmap=[0b101])
    assert len(with_bits) == 13
    assert rl.parse(with_bits)["bitmap"] == [0b101]


def test_what_the_console_refuses_is_refused_here_too():
    with pytest.raises(ValueError):
        rl.parse(SP35_FIRST[:8])                          # cmp w2, #8 / b.ls
    with pytest.raises(ValueError):
        rl.parse(bytes([0x0F, 0, 0x05, 0xA1, 0, 1, 0, 1, 0]))     # payload size 0x5a1
    with pytest.raises(ValueError):
        rl.parse(bytes([0x0F, 0, 0, 0, 0, 1, 0, 1, 0x20]))        # 32 destination bits
    with pytest.raises(ValueError):
        rl.build_header(0x0F, 1, 0, destination_bits=32)


def test_an_ack_payload_round_trips_at_two_plus_twenty_one_per_entry():
    entries = [{"stream_id": 0, "ack_id": 2, "field_0x50": 3, "mask": bytes(range(16))},
               {"stream_id": 1, "ack_id": 9, "field_0x50": 0, "mask": b""}]
    raw = rl.build_ack_payload(entries)
    assert len(raw) == 2 + rl.ACK_ENTRY_SIZE * 2 == 44     # 0x0159716c: n * 0x14 + n + 2
    out = rl.parse_ack_payload(raw)
    assert out["count"] == 2 and out["unknown0"] == 0
    assert out["entries"][0]["ack_id"] == 2 and out["entries"][0]["field_0x50"] == 3
    assert out["entries"][0]["mask"] == bytes(range(16))
    assert out["entries"][1]["stream_id"] == 1 and out["entries"][1]["mask"] == bytes(16)
    with pytest.raises(ValueError):
        rl.build_ack_payload([entries[0]] * 33)            # cmp #0x21 / b.lo


# The console's own bulk acknowledgement of our sequences 0 and 1.
SP44_ACK = bytes.fromhex(
    "00000017ffff0003000001000002000100000000000000000000000000000000")


def test_the_captured_ack_reads_back_the_way_the_console_built_it():
    out = rl.parse(SP44_ACK)
    assert out["is_ack"] is True and out["flags"] == 0 and out["flag_names"] == []
    assert out["sequence_id"] == rl.ACK_SEQUENCE == 0xFFFF   # a control message has no sequence
    assert out["lowest_pending"] == 3 and out["payload_size"] == 23
    body = rl.parse_ack_payload(out["payload"])
    assert body == {"unknown0": 0, "count": 1,
                    "entries": [{"stream_id": 0, "ack_id": 2, "field_0x50": 1, "mask": bytes(16)}]}


def test_build_ack_message_reproduces_it_byte_for_byte():
    assert rl.build_ack_message(2, lowest_pending=3) == SP44_ACK
    # the halfword before the mask defaults to ack_id - 1, which is what the console sent
    assert rl.parse_ack_payload(rl.parse(rl.build_ack_message(9))["payload"]
                                )["entries"][0]["field_0x50"] == 8


# Sword/Shield version 4 uses a fixed ACK payload table.

def test_the_version_four_ack_payload_is_the_size_the_handler_demands():
    from pokeldn.ldn import reliable4 as r4
    assert r4.ACK_PAYLOAD_SIZE == 0x260 == r4.ACK_ENTRIES * r4.ACK_ENTRY_SIZE == 32 * 19
    assert len(r4.build_ack_payload(21)) == r4.ACK_PAYLOAD_SIZE
    # It is not the 5.29 size, which the console refused unread.
    five = rl.build_ack_payload([{"stream_id": 0, "ack_id": 21, "field_0x50": 20, "mask": b""}])
    assert len(five) == 2 + rl.ACK_ENTRY_SIZE == 23 != r4.ACK_PAYLOAD_SIZE


def test_a_version_four_entry_is_a_stream_an_ack_id_and_a_mask_and_nothing_else():
    from pokeldn.ldn import reliable4 as r4
    body = r4.build_ack_payload(0x1234, stream_id=7, mask=bytes(range(16)), slots=[3])
    entries = r4.parse_ack_payload(body)
    assert len(entries) == r4.ACK_ENTRIES == 32
    assert entries[3] == {"slot": 3, "stream_id": 7, "ack_id": 0x1234, "mask": bytes(range(16))}
    assert body[3 * 19:3 * 19 + 3] == bytes([7, 0x12, 0x34])       # ack id is big-endian at [1]
    # every other slot is inert: 0xFF cannot match a real stream id
    assert all(e["stream_id"] == 0xFF for e in entries if e["slot"] != 3)


def test_filling_every_slot_answers_both_readings_of_which_one_is_read():
    from pokeldn.ldn import reliable4 as r4
    entries = r4.parse_ack_payload(r4.build_ack_payload(21))
    assert {e["ack_id"] for e in entries} == {21}
    assert {e["stream_id"] for e in entries} == {0}


def test_the_version_four_ack_message_is_this_modules_header_over_that_payload():
    from pokeldn.ldn import reliable4 as r4
    msg = r4.build_ack_message(21, lowest_pending=1)
    got = rl.parse(msg)
    assert got["is_ack"] and got["flags"] == 0
    assert got["sequence_id"] == rl.ACK_SEQUENCE == 0xFFFF
    assert got["payload_size"] == r4.ACK_PAYLOAD_SIZE and got["header_size"] == 9
    assert len(msg) == 9 + 0x260 == 617
    assert msg[:9].hex() == "00000260ffff000100"
    assert r4.parse_ack_payload(got["payload"])[0]["ack_id"] == 21


def test_a_wrongly_sized_ack_payload_is_refused_here_the_way_the_console_refuses_it():
    from pokeldn.ldn import reliable4 as r4
    with pytest.raises(ValueError, match="0x260"):
        r4.parse_ack_payload(b"\0" * 23)          # exactly what was sent, 96 times


def test_the_broadcast_reliable_message_is_a_seventeen_byte_header_over_the_same_ack():
    """A protocol-0x80 body, decompressed: the console's own ack."""
    import zlib
    from pokeldn.ldn import reliable4 as r4
    raw = bytes.fromhex("484b6260604af8ff9f819151c87391e28d0806206064c000834268140c07"
                        "00000000ffff03005fb204b9")
    body = zlib.decompress(raw)
    assert len(body) == 625
    got = r4.parse_broadcast_message(body)
    assert got["is_ack"] and got["flags"] == 0 and got["stream_id"] == 0
    assert got["sequence_id"] == 0xFFFF and got["lowest_pending"] == 1
    assert got["destination_count"] == 1
    assert got["destinations"] == [0x1249A221D8580000]        # our own station constant id
    # the length is what settles the header: 5.29's bitmap rule would give 13 and the message 621
    assert got["header_size"] == 17 == r4.BROADCAST_HEADER + r4.BROADCAST_ID_SIZE
    assert 17 + got["payload_size"] == len(body) == 625
    assert rl.header_size(1) == 13 and 13 + 608 != 625


def test_the_console_fills_one_slot_per_STATION_and_zeroes_the_rest():
    """The console fills slots 0..7 (the join response's `max_total`) and zeroes 8..31: the table is
    indexed by station."""
    import zlib
    from pokeldn.ldn import reliable4 as r4
    body = zlib.decompress(bytes.fromhex(
        "484b6260604af8ff9f819151c87391e28d0806206064c000834268140c07"
        "00000000ffff03005fb204b9"))
    theirs = r4.parse_broadcast_message(body)["payload"]
    assert len(theirs) == r4.ACK_PAYLOAD_SIZE
    entries = r4.parse_ack_payload(theirs)
    assert [e["slot"] for e in entries if e["ack_id"] == 1] == list(range(8))
    assert all(e["stream_id"] == 0 for e in entries)          # even the unused ones
    assert all(e["mask"] == b"\0" * 16 for e in entries)
    # ours fills all 32 with the real entry, which is a superset - and is what slid the window
    assert r4.build_ack_payload(1)[:8 * r4.ACK_ENTRY_SIZE] == theirs[:8 * r4.ACK_ENTRY_SIZE]


# The byte at 0x8 counts eight-byte station ids, not a bitmap width.

def test_the_version_four_header_grows_eight_bytes_per_destination_not_a_bitmap():
    from pokeldn.ldn import reliable4 as r4
    ids = [0x1249A221D8580000, 0xEB9B2220F1480000]
    assert r4.header_size([]) == 9 == rl.header_size(0)
    assert r4.header_size(ids[:1]) == 17 and rl.header_size(1) == 13     # where they part
    assert r4.header_size(ids) == 25 == 9 + 8 * 2
    head = r4.build_header(0, 1, 0, destinations=ids)
    assert len(head) == 25 and head[8] == 2
    assert r4.parse_message(head)["destinations"] == ids


def test_our_first_data_message_is_the_consoles_own_first_message_byte_for_byte():
    """`build_data_message` reproduces sequence 1 of the console's 0x7C stream."""
    from pokeldn.ldn import reliable4 as r4
    theirs = bytes.fromhex("0f0000060001000100" "610000000a00")
    assert r4.build_data_message(bytes.fromhex("610000000a00")) == theirs
    got = r4.parse_message(theirs)
    assert got["flags"] == r4.FIRST_DATA_FLAGS == 0x0F
    assert got["sequence_id"] == got["lowest_pending"] == r4.FIRST_SEQUENCE == 1
    assert got["destination_count"] == 0 and got["payload_size"] == 6


def test_only_the_first_message_carries_the_flag_that_opens_the_stream():
    """0x01859ca0 drops a message on an unopened stream (`tbz w9, #3`); the console sends 0x0F once,
    then 0x07."""
    from pokeldn.ldn import reliable4 as r4
    first = r4.parse_message(r4.build_data_message(b"ab"))
    later = r4.parse_message(r4.build_data_message(b"ab", sequence_id=2))
    assert first["flags"] & r4.FLAG_IS_INITIALIZED
    assert not later["flags"] & r4.FLAG_IS_INITIALIZED
    assert later["flags"] == r4.DATA_FLAGS == 0x07
    assert r4.parse_message(r4.build_data_message(b"ab", sequence_id=9, first=True))["flags"] == 0x0F


def test_the_payload_bound_is_the_receivers_and_it_shrinks_with_the_destination_list():
    """The deserialiser refuses 0x589 and above (0x0184e3cc); the receive path refuses over 0x57F -
    8 * count (0x0185952c)."""
    from pokeldn.ldn import reliable4 as r4
    assert r4.MAX_PAYLOAD == 0x588 and r4.max_payload_for([]) == 0x57F
    assert r4.max_payload_for([1]) == 0x57F - 8 and r4.max_payload_for([1, 2]) == 0x57F - 16
    r4.build_data_message(b"\0" * r4.max_payload_for([1]), destinations=[1])
    with pytest.raises(ValueError, match="0185952c"):
        r4.build_data_message(b"\0" * (r4.max_payload_for([1]) + 1), destinations=[1])
    with pytest.raises(ValueError, match="0x20 and above"):
        r4.build_header(0, 1, 0, destinations=range(32))


def test_we_can_rebuild_the_consoles_own_broadcast_ack_byte_for_byte():
    """The console's 625-byte broadcast ack, rebuilt by `build_ack_message`."""
    import zlib
    from pokeldn.ldn import reliable4 as r4
    theirs = zlib.decompress(bytes.fromhex(
        "484b6260604af8ff9f819151c87391e28d0806206064c000834268140c07"
        "00000000ffff03005fb204b9"))
    ours = r4.build_ack_message(1, slots=range(8), filler=0, lowest_pending=1,
                                destinations=[0x1249A221D8580000])
    assert ours == theirs and len(ours) == 625


def test_a_resent_check_ok_is_delivered_once():
    """A resent check-ok is answered once; a second answer resets the round (`0x1c34290`,
    docs/bdsp_trade.md)."""
    import gzip
    import json
    capture = os.path.join(os.path.dirname(__file__), "..", "scratchpad", "sp110_pia.jsonl.gz")
    if not os.path.exists(capture):
        pytest.skip("the retail capture is not here")
    rx, copies, delivered = rl.Reassembler(), [], []
    with gzip.open(capture, "rt") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("rec") != "reliable" or not row["flags"] & rl.FLAG_APPLICATION_DATA:
                continue
            d = {"stream_id": row["stream"], "sequence_id": row["seq"], "flags": row["flags"],
                 "payload": bytes.fromhex(row["payload"])}
            if d["payload"] == bytes.fromhex("46000101"):
                copies.append(row["seq"])
            kind, payload = rx.take(d)
            if kind == "message" and payload == bytes.fromhex("46000101"):
                delivered.append(row["seq"])
    assert copies == [9, 24, 24]
    assert delivered == [9, 24]


def test_fragments_join_in_order_and_a_repeated_fragment_changes_nothing():
    rx = rl.Reassembler()
    first = {"stream_id": 0, "sequence_id": 7, "flags": 0x03, "payload": b"ab"}
    last = {"stream_id": 0, "sequence_id": 8, "flags": 0x05, "payload": b"cd"}
    assert rx.take(first) == ("partial", None)
    assert rx.take(dict(first)) == ("partial", None)
    assert rx.take(last) == ("message", b"abcd")
    assert rx.take(dict(last))[0] == "repeat" and rx.take(dict(first))[0] == "repeat"
    rx.reset()
    assert rx.take(dict(first)) == ("partial", None)

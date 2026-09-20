"""The channel table on port 1, against the three messages a console sent and the binary's writer.

The bytes are a retail console's (`docs/pla.md`, The channel table on port 1); the encoding is the
game's own writer at `0x2ca83dc`.
"""

import pytest

from pokeldn.pla import channel_table, game_channel

TRADE_BOX_KEY = bytes(8)
PHASE_KEY = bytes([1]) + bytes(7)


def test_the_joiner_open_announces_the_trade_box_key():
    msg = channel_table.build([(TRADE_BOX_KEY, True)])
    assert msg == bytes.fromhex("b90101b902b902000001")
    assert msg == game_channel.JOINER_OPEN_PAYLOAD
    assert channel_table.parse(msg) == [(TRADE_BOX_KEY, True)]


def test_the_phase_key_opens_and_closes():
    opened = channel_table.build([(PHASE_KEY, True)])
    closed = channel_table.build([(PHASE_KEY, False)])
    assert opened == bytes.fromhex("b90101b902b902010001")
    assert closed == bytes.fromhex("b90101b902b902010000")
    assert channel_table.parse(opened) == [(PHASE_KEY, True)]
    assert channel_table.parse(closed) == [(PHASE_KEY, False)]


def test_several_entries_in_one_message():
    msg = channel_table.build([(TRADE_BOX_KEY, True), (PHASE_KEY, True)])
    assert msg == bytes.fromhex("b90102" "b902b902000001" "b902b902010001")
    assert channel_table.parse(msg) == [(TRADE_BOX_KEY, True), (PHASE_KEY, True)]


def test_the_integer_encoding_is_the_writers():
    assert channel_table.encode_uint(0x7F) == bytes([0x7F])
    assert channel_table.encode_uint(0x80) == bytes([0x80, 0x80])
    assert channel_table.encode_uint(0x1234) == bytes.fromhex("813412")
    assert channel_table.encode_uint(0x12345678) == bytes.fromhex("8278563412")
    for v in (0, 0x7F, 0x80, 0xFF, 0x100, 0xFFFF, 0x10000, 0xFFFFFFFF, 0x100000000):
        assert channel_table.decode_uint(channel_table.encode_uint(v), 0) == (
            v, len(channel_table.encode_uint(v)))


def test_a_wide_key_word_takes_a_tagged_integer():
    key = bytes.fromhex("0000010000000000")
    msg = channel_table.build([(key, True)])
    assert msg == bytes.fromhex("b90101b902b902" "82000001000001")
    assert channel_table.parse(msg) == [(key, True)]


@pytest.mark.parametrize("bad", [
    "",
    "b90101",                          # no entries
    "b90101b902b90200",                # cut before the state
    "b90101b902b902000002",            # a state that is neither open nor closed
    "b90101b902b90200000100",          # a byte after the last entry
    "0000000000000000" "0100",         # a port-0 game message
])
def test_anything_else_is_refused(bad):
    assert not channel_table.is_announcement(bytes.fromhex(bad))
    with pytest.raises((ValueError, IndexError)):
        channel_table.parse(bytes.fromhex(bad))

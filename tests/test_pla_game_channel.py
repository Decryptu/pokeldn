"""The game's reliable channel, against the bytes a reference pair sent on 0x7c.

Every constant here is a capture of a Ryujinx pair that reached the trade screen. `docs/pla.md`,
The game's reliable channel.
"""

from pokeldn.ldn import reliable5
from pokeldn.pla import game_channel

HOST_OPEN = bytes.fromhex("0f00000a000100010000000000000000000100")
JOINER_OPEN = bytes.fromhex("0f00000a0001000100b90101b902b902000001")
ACK = bytes.fromhex("00000017ffff0001000001000002000100000000000000000000000000000000")


def test_the_two_opens_are_the_reference_byte_for_byte():
    assert game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD) == HOST_OPEN
    assert game_channel.build_open(game_channel.JOINER_OPEN_PAYLOAD) == JOINER_OPEN


def test_the_acknowledgement_is_the_reference_byte_for_byte():
    assert game_channel.build_ack(2, lowest_pending=1) == ACK


def test_a_channel_message_is_a_handler_key_and_a_body():
    key, body = game_channel.split_message(game_channel.HOST_OPEN_PAYLOAD)
    assert key == bytes(8) and body == bytes.fromhex("0100")
    key, body = game_channel.split_message(game_channel.JOINER_OPEN_PAYLOAD)
    assert key == bytes.fromhex("b90101b902b90200") and body == bytes.fromhex("0001")


def test_the_channel_declares_no_destination_bitmap():
    """0x7c is addressed to the peer's variable id, so the message carries no bitmap, where the
    0x81 stream declares one destination bit."""
    for message in (HOST_OPEN, JOINER_OPEN, ACK):
        assert reliable5.parse(message)["destination_bits"] == 0
        assert reliable5.parse(message)["header_size"] == 9


# What a console sends on port 1 once the trade is confirmed: the same key family as the channel
# open with a different last byte, and the same two-byte body, without the initialized flag.
CONSOLE_SECOND_KEY = bytes.fromhex("0700000a0002000200b90101b902b902010001")


def test_the_second_key_on_a_port_is_the_consoles_byte_for_byte():
    assert game_channel.build_message(bytes.fromhex("b90101b902b90201"), bytes.fromhex("0001"),
                                      sequence_id=2, flags=0x07) == CONSOLE_SECOND_KEY



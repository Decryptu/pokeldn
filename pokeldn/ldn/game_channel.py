"""The game's own reliable channel, protocol 0x7c: an eight-byte handler key and a body per message.

Port 0 carries the game's messages (the trade box among them); port 1 is the channel table,
`pokeldn.ldn.channel_table` (docs/pla.md, The game's reliable channel).
"""

from pokeldn.ldn import reliable5

PROTOCOL = 0x7C
HOST_PORT = 0
JOINER_PORT = 1
SEQUENCE_ID = 1

KEY_SIZE = 8

def build_open(payload, sequence_id=SEQUENCE_ID, initialized=True):
    """-> the message that opens a channel; a later update drops INITIALIZED (flags 0x07)."""
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END
             | (reliable5.FLAG_IS_INITIALIZED if initialized else 0))
    return (reliable5.build_header(flags, sequence_id, len(payload), lowest_pending=sequence_id,
                                   stream_id=0) + bytes(payload))


def build_ack(ack_id, lowest_pending=1, station_index=0, mask=b""):
    """-> the one-entry acknowledgement: the id one past the sequence received, the window field at
    the lowest pending id, a nine-byte header with no destination bitmap."""
    payload = reliable5.build_ack_payload(
        [dict(stream_id=station_index, ack_id=ack_id, field_0x50=lowest_pending, mask=mask)])
    return (reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                   lowest_pending=lowest_pending, stream_id=0) + payload)


def split_message(payload):
    """-> (key, body) of a channel message's payload."""
    payload = bytes(payload)
    return payload[:KEY_SIZE], payload[KEY_SIZE:]


def build_payload_message(payload, sequence_id, flags=None):
    """-> a reliable message carrying `payload`; port 0: key and body, port 1: the table."""
    if flags is None:
        flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
                 | reliable5.FLAG_MESSAGE_END
                 | (reliable5.FLAG_IS_INITIALIZED if sequence_id == 1 else 0))
    payload = bytes(payload)
    return (reliable5.build_header(flags, sequence_id, len(payload), lowest_pending=sequence_id,
                                   stream_id=0) + payload)


def build_message(key, body, sequence_id, flags=None):
    """-> a channel message carrying `key` and `body` at `sequence_id`."""
    key = bytes(key)
    if len(key) != KEY_SIZE:
        raise ValueError(f"a handler key is {KEY_SIZE} bytes, not {len(key)}")
    return build_payload_message(key + bytes(body), sequence_id, flags)

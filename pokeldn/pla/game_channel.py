"""The game's own reliable channel, protocol 0x7c, and the messages that open it.

Once the 0x81 data exchange completes, the trade flow leaves the step that waits on it and reaches
the step that ticks the game's own network object. That object advances on messages the game reads
here, not on anything the transport does: this is where the game's registered handlers receive, and
the trade box crosses here as one 390-byte message.

A message is an eight-byte handler key and a body. The dispatcher compares the key against the
registered handler's own two words and passes the body through unexamined, so the key is what
routes and the body is the game's. The handler the game registers on reaching this step carries
eight zero bytes, which is the key the port-0 channel uses.

Two channels open, each a `pokeldn.ldn.reliable5` stream with no destination bitmap, addressed to
the peer's variable id the way the session and clock messages are:

    port 0    key eight zero bytes, body `0100`      the host opens, the peer sends the same back
    port 1    key `b90101b902b90200`, body `0001`    the joiner opens, the peer sends the same back

Each open is sequence 1 with the message-start, message-end and initialized flags, and is answered
with a one-entry acknowledgement. `docs/pla.md`, The game's reliable channel.
"""

from pokeldn.ldn import reliable5

PROTOCOL = 0x7C
HOST_PORT = 0
JOINER_PORT = 1
SEQUENCE_ID = 1

KEY_SIZE = 8

# The two opens, off a reference pair that reached the trade screen. Each is a key and a body.
HOST_OPEN_PAYLOAD = bytes.fromhex("00000000000000000100")
JOINER_OPEN_PAYLOAD = bytes.fromhex("b90101b902b902000001")


def build_open(payload, sequence_id=SEQUENCE_ID):
    """-> the message that opens a channel: the payload under the initialized flags, sequence 1."""
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END | reliable5.FLAG_IS_INITIALIZED)
    return (reliable5.build_header(flags, sequence_id, len(payload), lowest_pending=sequence_id,
                                   stream_id=0) + bytes(payload))


def build_ack(ack_id, lowest_pending=1, station_index=0):
    """-> the one-entry acknowledgement a station answers a channel message with.

    The reference acknowledges the id one past the sequence received, with the window's own field at
    the lowest pending id and an empty mask, under a nine-byte header with no destination bitmap.
    """
    payload = reliable5.build_ack_payload(
        [dict(stream_id=station_index, ack_id=ack_id, field_0x50=lowest_pending)])
    return (reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                   lowest_pending=lowest_pending, stream_id=0) + payload)


def split_message(payload):
    """-> (key, body) of a channel message's payload."""
    payload = bytes(payload)
    return payload[:KEY_SIZE], payload[KEY_SIZE:]


def build_message(key, body, sequence_id, flags=None):
    """-> a channel message carrying `key` and `body` at `sequence_id`."""
    key = bytes(key)
    if len(key) != KEY_SIZE:
        raise ValueError(f"a handler key is {KEY_SIZE} bytes, not {len(key)}")
    if flags is None:
        flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
                 | reliable5.FLAG_MESSAGE_END
                 | (reliable5.FLAG_IS_INITIALIZED if sequence_id == 1 else 0))
    payload = key + bytes(body)
    return (reliable5.build_header(flags, sequence_id, len(payload), lowest_pending=sequence_id,
                                   stream_id=0) + payload)

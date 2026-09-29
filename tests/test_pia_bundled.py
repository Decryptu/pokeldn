"""Presence byte 0x00 opens a message whose whole header is inherited, in every band (docs/pia.md,
Message framing)."""
import json
import os

import pytest

from pokeldn import pla, sv
from pokeldn.ldn import pia5, pia6
from pokeldn.ldn import reliable5 as r5

PACKETS = json.load(open(os.path.join(os.path.dirname(__file__), "data",
                                      "pia_bundled_packets.json")))

RTT, RELIABLE_5, RELIABLE_6, SESSION = 0x58, 0x7C, 0x81, 0x98

# One entry per packet in the data file: (protocol, port, reliable sequence id or None).
EXPECTED = [
    # Scarlet's first burst: 1 with a full header, 25 with its own size, 26 to 36 behind presence
    # 0x00, 46 with its own size. The sniffer saw 25 to 36 and 46 in this frame.
    [(RELIABLE_6, 0, 1), (RELIABLE_6, 0, 25)] + [(RELIABLE_6, 0, s) for s in range(26, 37)]
    + [(RELIABLE_6, 0, 46)],
    # A retransmission round: an RTT response, every record not yet acknowledged, and a Session
    # message after the last presence-0x00 one.
    [(RTT, 0, None)] + [(RELIABLE_6, 0, s) for s in (33, 34, 35, 36, *range(38, 47))]
    + [(SESSION, 0, None)],
    # Arceus: records 1 and 2 of a stream, the second behind presence 0x00.
    [(RELIABLE_6, 0, 1), (RELIABLE_6, 0, 2)],
    # BDSP, four-byte aligned: record 3 opens at offset 64 with presence 0x00.
    [(RELIABLE_5, 0, 1), (RELIABLE_5, 0, 2), (RELIABLE_5, 0, 3)],
]


def _messages(case):
    data = bytes.fromhex(case["datagram"])
    if case["game"] == "bdsp":
        h = pia5.PiaHeader5.parse(data)
        crc = pia5.ldn_nonce_crc(bytes.fromhex(case["network_id_le"]),
                                 bytes.fromhex(case["src_mac"]))
        plain = pia5.decrypt_payload(bytes.fromhex(case["session_key"]),
                                     pia5.gcm_iv(crc, h.src_var, h.nonce8),
                                     pia5.ciphertext(data, h.footer_size), h.tag)
        assert plain is not None
        return pia5.parse_messages(plain)
    keys = (sv if case["game"] == "scarlet" else pla).session_keys(bytes.fromhex(case["ssid"]))
    _, plain, _ = pia6.parse_packet(keys.session_key, case["src_ip"], keys.network_id, data)
    assert plain is not None
    return pia6.parse_messages(plain)


def _sequence(m):
    return r5.parse(m.payload)["sequence_id"] if m.protocol in (RELIABLE_5, RELIABLE_6) else None


@pytest.mark.parametrize("case,expected", list(zip(PACKETS, EXPECTED)),
                         ids=[f"{c['game']}-{i}" for i, c in enumerate(PACKETS)])
def test_a_presence_byte_of_zero_is_a_message(case, expected):
    got = [(m.protocol, m.port, _sequence(m)) for m in _messages(case)]
    assert got == expected



def test_the_version_16_walk_reads_the_byte_bit_0x10_states():
    """Z-A's header size `0x256dfc8` counts one byte each for flag bits 4, 8 and 0x10."""
    from pokeldn.ldn import reliable
    first = bytes([0x1F, 0x00, 0x00, 0x03, 0x81, 0xFD, 0x02]) + b"abc"
    second = bytes([0x00]) + b"xyz"
    msgs, end = reliable.parse_messages(first + second + b"\xff")
    assert [(m.proto, m.payload) for m in msgs] == [(0x81, b"abc"), (0x81, b"xyz")]
    assert end == len(first + second)

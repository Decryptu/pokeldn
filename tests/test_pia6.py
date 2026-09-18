"""Pia version 11, the band Legends Arceus speaks.

No console packet has been captured yet, so the pins here are what can be checked without one: the
header layout and the constants Arceus's own parser enforces, the key and IV against
`crypto.PiaCrypto`, which runs the same 6.16-6.42 derivation and is proven on retail at 6.32, and
the game package against the band module. The binary checks run only where the extracted `main` is
on disk, which is untracked.
"""
import os
import struct

import pytest
from Crypto.Cipher import AES

from pokeldn.ldn import pia6
from pokeldn.ldn.crypto import PiaCrypto

MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "scratchpad", "pla", "main_111.bin")

SSID = bytes.fromhex("8ec1f0d34a6b2159b7043e8c95df6a27")
GAME_KEY = b"p1frXqxmeCZWFv0X"
SRC_IP = "169.254.7.42"


def test_header_constants():
    assert (pia6.VERSION, pia6.HEADER_SIZE, pia6.TAG_SIZE) == (11, 0x1C, 8)
    assert (pia6.NONCE_OFF, pia6.TAG_OFF, pia6.CT_OFF) == (0x0C, 0x14, 0x1C)
    assert pia6.FOOTER_SIZE_OFF == 0x0B
    assert pia6.MAX_PAYLOAD + pia6.HEADER_SIZE == 0x5C1


def test_header_round_trip():
    h = pia6.PiaHeader6(dst_var=0x1234, src_var=0xC493, packet_id=7, footer_size=4,
                        nonce8=bytes(range(8)), tag=bytes(range(8, 16)))
    raw = h.pack()
    assert len(raw) == pia6.HEADER_SIZE
    assert raw[:4] == struct.pack(">I", pia6.MAGIC)
    assert raw[4] == 0x80 | 11
    assert struct.unpack_from(">HHH", raw, 5) == (0x1234, 0xC493, 7)
    assert raw[0x0B] == 4
    back = pia6.PiaHeader6.parse(raw)
    assert (back.dst_var, back.src_var, back.packet_id, back.footer_size) == (0x1234, 0xC493, 7, 4)
    assert back.encrypted and back.version == 11
    assert back.nonce8 == bytes(range(8)) and back.tag == bytes(range(8, 16))
    assert pia6.is_pia6(raw)


def test_version_byte_separates_the_bands():
    v9 = bytearray(pia6.PiaHeader6().pack())
    v9[4] = 0x80 | 9
    assert not pia6.is_pia6(bytes(v9))


def test_session_key_and_network_id_match_the_proven_band_rule():
    ref = PiaCrypto(SSID, game_key=GAME_KEY)
    assert pia6.ldn_session_key(GAME_KEY, SSID) == ref.session_key
    assert pia6.ldn_network_id(SSID) == ref.net_id
    nonce8 = bytes.fromhex("0000000000000001")
    assert pia6.gcm_iv(ref.net_id, SRC_IP, nonce8) == ref.nonce(SRC_IP, nonce8)


def test_short_ssid_is_repeated_to_fill_the_block():
    key = pia6.ldn_session_key(GAME_KEY, b"\x01\x02\x03\x04")
    assert key == AES.new(GAME_KEY, AES.MODE_ECB).encrypt(b"\x01\x02\x03\x04" * 4)


def test_packet_round_trip_with_a_footer():
    session_key = pia6.ldn_session_key(GAME_KEY, SSID)
    net_id = pia6.ldn_network_id(SSID)
    body = pia6.build_message(b"hello arceus", protocol=0x14, port=0)
    pkt = pia6.build_packet(session_key, net_id, SRC_IP, body, dst_var=0x7620, src_var=0xC493,
                            packet_id=3, nonce8=bytes.fromhex("000000000000002a"),
                            footer_ids=(0x7620, 0x1111))
    assert pkt[0x0B] == 4
    assert pkt[-4:] == struct.pack(">HH", 0x7620, 0x1111)
    header, plain, ids = pia6.parse_packet(session_key, SRC_IP, net_id, pkt)
    assert ids == [0x7620, 0x1111]
    assert header.packet_id == 3 and header.footer_size == 4
    assert plain is not None
    assert plain.startswith(body)
    assert len(plain) % 16 == 0 and set(plain[len(body):]) <= {0xFF}
    msgs = pia6.parse_messages(plain)
    assert len(msgs) == 1 and msgs[0].payload == b"hello arceus" and msgs[0].protocol == 0x14


def test_the_footer_is_outside_the_tag():
    """A footer byte may be changed without breaking authentication; a ciphertext byte may not."""
    session_key = pia6.ldn_session_key(GAME_KEY, SSID)
    net_id = pia6.ldn_network_id(SSID)
    pkt = bytearray(pia6.build_packet(session_key, net_id, SRC_IP, b"\x00" * 16,
                                      nonce8=b"\x00" * 7 + b"\x05", footer_ids=(0x7620,)))
    pkt[-1] ^= 0xFF
    assert pia6.parse_packet(session_key, SRC_IP, net_id, bytes(pkt))[1] is not None
    pkt[pia6.CT_OFF] ^= 0xFF
    assert pia6.parse_packet(session_key, SRC_IP, net_id, bytes(pkt))[1] is None


def test_a_wrong_source_address_fails_the_tag():
    session_key = pia6.ldn_session_key(GAME_KEY, SSID)
    net_id = pia6.ldn_network_id(SSID)
    pkt = pia6.build_packet(session_key, net_id, SRC_IP, b"\x01" * 16, nonce8=b"\x00" * 8)
    assert pia6.parse_packet(session_key, "169.254.7.43", net_id, pkt)[1] is None


@pytest.mark.skipif(not os.path.exists(MAIN), reason="scratchpad/pla/main_111.bin is untracked")
def test_the_constants_are_the_ones_arceus_enforces():
    """The header initializer at 0x6f0744 and the validator at 0x6f07d0, read back word by word."""
    img = open(MAIN, "rb").read()

    def word(addr):
        return struct.unpack_from("<I", img, addr)[0]

    assert (word(0x6F0748) >> 5) & 0xFFFF == 0x9864     # mov w8, #0x9864
    assert (word(0x6F074C) >> 5) & 0xFFFF == 0x32AB     # movk w8, #0x32ab, lsl #16
    assert (word(0x6F0754) >> 5) & 0xFFFF == 0x0B       # mov w8, #0xb, the version
    assert (word(0x6F07EC) >> 10) & 0xFFF == 0x0B       # cmp w8, #0xb
    assert (word(0x6F07F8) >> 10) & 0xFFF == pia6.HEADER_SIZE      # sub w8, w8, #0x1c
    assert (word(0x6F07FC) >> 10) & 0xFFF == pia6.MAX_PAYLOAD      # cmp w8, #0x5a5
    assert (word(0x6F0B24) >> 5) & 0xFFFF == pia6.TAG_SIZE         # mov w4, #8, the tag length


def test_the_game_package_agrees_with_the_band_module():
    from pokeldn import pla

    keys = pla.session_keys(SSID)
    assert keys.session_key == pia6.ldn_session_key(pla.GAME_KEY, SSID)
    assert keys.network_id == pia6.ldn_network_id(SSID)
    assert pla.packet_iv(keys, SRC_IP, b"\x00" * 8) == pia6.gcm_iv(keys.network_id, SRC_IP,
                                                                   b"\x00" * 8)
    assert (pla.PIA_VERSION, pla.PIA_HEADER_SIZE, pla.PIA_TAG_SIZE) == (
        pia6.VERSION, pia6.HEADER_SIZE, pia6.TAG_SIZE)
    assert pla.GAME_KEY == GAME_KEY and len(pla.PASSPHRASE) == 64
    assert pla.COMM_ID == 0x01001F5010DFA000


@pytest.mark.skipif(not os.path.exists(MAIN), reason="scratchpad/pla/main_111.bin is untracked")
def test_the_constants_come_out_of_the_binary():
    from pokeldn import pla

    img = open(MAIN, "rb").read()
    assert img[0x3985308:0x3985308 + 16] == pla.GAME_KEY
    assert img[0x3985319:0x3985319 + 64] == pla.PASSPHRASE
    assert img[0x3985319 + 64] == 0                     # NUL-terminated, and 0x40 is the length
    parts = [(struct.unpack_from("<I", img, a)[0] >> 5) & 0xFFFF
             for a in (0x264082C, 0x2640830, 0x2640834, 0x2640838)]
    assert sum(p << (16 * i) for i, p in enumerate(parts)) == pla.COMM_ID


# Two advertisements a retail Legends Arceus broadcast while waiting on its local-trade search
# screen, with the eight-digit codes 0000 0000 and 1234 5678. Different sessions: the SSIDs differ
# and so do the channels.
PLA_ADVERTISE = {
    "00000000": bytes.fromhex(
        "005c150000d59b29dd441b5d70885998bf968aa1660101000000010120000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        "000000003030303030303030000000000000000008000000"),
    "12345678": bytes.fromhex(
        "005c150000d4992ad9411d5a78885998bf968aa1660101000000010120000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        "000000003132333435363738000000000000000008000000"),
}


def test_the_advertisement_decodes_and_the_code_is_in_the_clear():
    from pokeldn import pla

    for code, app in PLA_ADVERTISE.items():
        assert len(app) == 112
        d = pla.parse_advertise_data(app)
        assert (d["size"], d["sys_comm_ver"], d["app_comm_ver"]) == (0x5C, 21, 0)
        assert (d["player_limit_enabled"], d["num_players"]) == (1, 1)
        assert (d["name_size"], d["name_encoding"], d["nickname"]) == (1, 1, " ")
        assert d["code"] == code and d["code_size"] == 8
        assert d["password_code"] == code
        assert d["game_data"] == pla.build_game_data(code)


def test_the_password_field_is_the_code_xored_into_one_constant():
    """Two sessions, two codes, one mask. A per-session value could not survive this."""
    from pokeldn import pla

    for code, app in PLA_ADVERTISE.items():
        assert pla.user_password(code) == app[0x05:0x15]
        assert pla.link_code(app[0x05:0x15]) == code
    assert pla.user_password("\0" * 8) == pla.LINK_CODE_MASK


def test_the_advertisement_is_reproduced_byte_for_byte():
    """Both captures rebuild from the code alone, which is what hosting one needs."""
    from pokeldn import pla

    for code, app in PLA_ADVERTISE.items():
        assert pla.build_advertise_data(code) == app


def test_the_host_decodes_a_packet_the_way_a_console_would_send_one():
    """The whole host read path, offline: build a version-11 packet, then decode it as the host."""
    import pla_host

    from pokeldn import pla

    keys = pla.session_keys(SSID)
    console_ip = "169.254.9.9"
    body = pia6.build_message(bytes([0, 2, 0x2C, 0, 0x58, 5]), protocol=0x98, port=0)
    pkt = pia6.build_packet(keys.session_key, keys.network_id, console_ip, body,
                            dst_var=1, src_var=0xC493, packet_id=1, nonce8=b"\x00" * 7 + b"\x01")
    assert pia6.is_pia6(pkt)
    header, plain, ids = pia6.parse_packet(keys.session_key, console_ip, keys.network_id, pkt)
    assert plain is not None and ids == []
    msgs = pia6.parse_messages(plain)
    assert len(msgs) == 1 and msgs[0].protocol == 0x98
    line = pla_host._describe(msgs[0])
    assert "session" in line and "join request(0)" in line
    assert pla_host.PROTOCOL_NAMES[0x7C] == "reliable"


def test_the_host_finds_every_constant_it_reads_off_the_game_package():
    """The host names these before it touches the radio; a missing one aborts the run."""
    import pla_host

    from pokeldn import pla

    for name in ("LINK_CODE_LEN", "ADVERTISE_NAME", "PASSPHRASE", "COMM_ID", "SCENE_ID",
                 "MAX_PARTICIPANTS", "LDN_PROTOCOL", "build_advertise_data", "session_keys"):
        assert hasattr(pla, name), name
    assert pla.LINK_CODE_LEN == 8
    assert set(pla_host.SESSION_MESSAGE_NAMES) >= {0, 2, 5, 7}


def test_the_host_opens_the_net_exchange_and_the_probe_decodes():
    """The host speaks first. The probe it sends must authenticate and parse as a Net 0x11."""
    import pla_host

    from pokeldn import pla
    from pokeldn.ldn import pia_connect

    keys = pla.session_keys(SSID)
    our_ip, joiner_ip = "169.254.9.1", "169.254.9.2"
    our_mac = bytes.fromhex("58d8122149a2")
    pkt = pla_host.build_net_probe(keys, our_ip, our_mac, [our_ip, joiner_ip], 3,
                                   b"\x00" * 7 + b"\x03", pla.MAX_PARTICIPANTS)
    header, plain, ids = pia6.parse_packet(keys.session_key, our_ip, keys.network_id, pkt)
    assert plain is not None, "the host's own probe must authenticate"
    assert (header.dst_var, header.src_var, header.packet_id) == (0, pla_host.PIA_HOST_VAR, 0)
    msgs = pia6.parse_messages(plain)
    assert len(msgs) == 1 and msgs[0].protocol == pla_host.PROTO_NET
    parsed = pia_connect.parse_net_conn_request(msgs[0].payload)
    assert parsed is not None
    host_var, host_mac, seqid = parsed
    assert host_var == pla_host.PIA_HOST_VAR
    assert host_mac == pia_connect.ldn_constant_id(our_mac)[:6]
    assert seqid == 3
    assert pla_host.PROTO_NET == 0x2C


def test_the_rtt_probe_is_a_well_formed_request():
    """A peer answers RTT with no state, so it separates the crypto from the Net layout."""
    import pla_host

    from pokeldn import pla
    from pokeldn.ldn import pia_connect

    keys = pla.session_keys(SSID)
    our_ip = "169.254.9.1"
    pkt = pla_host.build_rtt_probe(keys, our_ip, 0x1234, b"\x00" * 7 + b"\x07", version=5)
    header, plain, _ = pia6.parse_packet(keys.session_key, our_ip, keys.network_id, pkt)
    assert plain is not None
    msgs = pia6.parse_messages(plain)
    assert len(msgs) == 1 and msgs[0].protocol == pla_host.PROTO_RTT == 0x58
    r = pia_connect.parse_rtt(msgs[0].payload)
    assert r["type"] == 0 and r["version"] == 5
    assert int.from_bytes(r["systime"], "little") == 0x1234
    assert r["subject"] == pla_host.PIA_HOST_VAR.to_bytes(2, "big")


def test_the_net_protocol_id_is_selectable():
    import pla_host

    from pokeldn import pla

    keys = pla.session_keys(SSID)
    pkt = pla_host.build_net_probe(keys, "169.254.9.1", bytes(6), ["169.254.9.1"], 2,
                                   b"\x00" * 8, 2, protocol=1)
    _, plain, _ = pia6.parse_packet(keys.session_key, "169.254.9.1", keys.network_id, pkt)
    assert pia6.parse_messages(plain)[0].protocol == 1


def test_a_message_ends_where_its_payload_ends_and_the_packet_pads_with_ff():
    """This band does not align a message: a reference station starts the next one on the byte after
    the last payload, and only the packet pads, to sixteen and with 0xFF. A zero there is a legal
    message header and would reject the packet."""
    m = pia6.build_message(b"A" * 74, protocol=0x2C, port=0)
    assert len(m) == 90                                    # a sixteen-byte header and the payload
    packed = pia6.pad_payload(m)
    assert len(packed) == 96 and set(packed[90:]) == {0xFF}
    assert 0 not in packed[90:]


def test_the_whole_plaintext_after_the_message_is_ff():
    """What the console's parser walks: one message, then nothing but the stop byte."""
    from pokeldn import pla

    keys = pla.session_keys(SSID)
    body = pia6.build_message(b"B" * 74, protocol=0x2C, port=0)
    pkt = pia6.build_packet(keys.session_key, keys.network_id, "169.254.9.1", body)
    _, plain, _ = pia6.parse_packet(keys.session_key, "169.254.9.1", keys.network_id, pkt)
    msgs = pia6.parse_messages(plain)
    assert len(msgs) == 1 and msgs[0].payload == b"B" * 74
    stated = 16 + 74
    assert set(plain[stated:]) == {0xFF}


def test_both_probes_carry_the_skip_source_check_flag():
    """The dispatch keys on the source variable id, which the peer has never heard from a host."""
    import pla_host

    from pokeldn import pla

    keys = pla.session_keys(SSID)
    ip = "169.254.9.1"
    for pkt in (pla_host.build_net_probe(keys, ip, bytes(6), [ip], 2, b"\x00" * 8, 2),
                pla_host.build_rtt_probe(keys, ip, 1, b"\x00" * 8)):
        _, plain, _ = pia6.parse_packet(keys.session_key, ip, keys.network_id, pkt)
        msg = pia6.parse_messages(plain)[0]
        assert msg.message_flags & pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK
    assert pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK == 0x01


def test_the_joiner_answers_a_connection_request_and_can_build_its_join():
    """The joiner's two outbound messages, offline, against a request shaped like a host's."""
    import pla_join

    from pokeldn import pla
    from pokeldn.ldn import pia_connect

    keys = pla.session_keys(SSID)
    our_ip, host_ip = "172.16.86.128", "172.16.86.1"
    host_mac = bytes.fromhex("0200ac105601")
    request = pia_connect.build_net_conn_request(7, 0x00C6, host_mac, keys.network_id,
                                                 [host_ip, our_ip], max_stations=2)
    parsed = pia_connect.parse_net_conn_request(request)
    assert parsed is not None
    host_var, seen_mac, seqid = parsed
    assert (host_var, seqid) == (0x00C6, 7)

    response = pia6.build_message(pia_connect.build_net_response(seqid), protocol=pla_join.PROTO_NET,
                                  port=0, message_flags=pla_join.ESTABLISHING_FLAGS)
    pkt = pia6.build_packet(keys.session_key, keys.network_id, our_ip, response,
                            dst_var=0, src_var=pla_join.OUR_VAR, packet_id=0, nonce8=b"\x00" * 8)
    header, plain, _ = pia6.parse_packet(keys.session_key, our_ip, keys.network_id, pkt)
    assert plain is not None and header.src_var == pla_join.OUR_VAR
    msg = pia6.parse_messages(plain)[0]
    assert msg.protocol == 0x2C and msg.message_flags & pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK
    assert msg.payload[1] == pia_connect.NET_CONN_RESPONSE

    join = pia_connect.build_session_join(bytes.fromhex("0200ac105680"),
                                          pla_join.OUR_VAR.to_bytes(2, "big"), our_ip, seen_mac,
                                          host_var.to_bytes(2, "big"), "PkCamp", b"\x01\x02\x03\x04")
    assert join[0] == pia_connect.SESSION_JOIN_REQUEST
    parsed_join = pia_connect.parse_session_join(join)
    assert parsed_join is not None and parsed_join["ip"] == our_ip
    assert pla_join.PROTO_SESSION == 0x98


def test_the_update_network_host_message_matches_the_console_serializer():
    """0x6fe03c writes u64 at +4, u64 at +0xc, u16 at +0x14 and states the size as 0x16."""
    import pla_join

    from pokeldn.ldn import pia_connect

    constant = pia_connect.ldn_constant_id(bytes.fromhex("0200ac105680"))
    m = pla_join.build_update_network_host(constant, 0x4F264487, 0xC493)
    assert len(m) == 0x16
    assert m[0] == 1 and m[1] == pla_join.NET_UPDATE_NETWORK_HOST
    assert int.from_bytes(m[2:4], "big") == 0x12
    assert m[4:12] == constant
    assert int.from_bytes(m[12:20], "big") == 0x4F264487
    assert int.from_bytes(m[20:22], "big") == 0xC493
    swapped = pla_join.build_update_network_host(constant, 0x4F264487, 0xC493, swap=True)
    assert swapped[4:12] == (0x4F264487).to_bytes(8, "big") and swapped[12:20] == constant

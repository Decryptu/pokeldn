"""Legends Z-A constants, pinned to a retail console's own advertisement.

Two sessions of a retail Legends Z-A on the local search screen, one per link code.
"""
import pytest

from pokeldn import za

SCAN_0000 = bytes.fromhex(
    "005c160006205897729c0ab7b7ab6066a161f5d5e10101000000010120"
    + "00" * 63 + "3030303030303030" + "00" * 8 + "08000000")
SCAN_1234 = bytes.fromhex(
    "005c160006215a9476990cb0bfab6066a161f5d5e10101000000010120"
    + "00" * 63 + "3132333435363738" + "00" * 8 + "08000000")


@pytest.mark.parametrize("code,scan", [("00000000", SCAN_0000), ("12345678", SCAN_1234)])
def test_advertisement_rebuilds_from_the_code_alone(code, scan):
    assert za.build_advertise_data(code) == scan


@pytest.mark.parametrize("code,scan", [("00000000", SCAN_0000), ("12345678", SCAN_1234)])
def test_the_password_field_and_the_game_bytes_agree(code, scan):
    parsed = za.parse_advertise_data(scan)
    assert parsed["code"] == code
    assert parsed["password_code"] == code
    assert parsed["code_size"] == 8


def test_the_mask_is_the_game_key_derivation():
    assert za.link_code_keystream() == bytes.fromhex("1068a742ac3a8787ab6066a161f5d5e1")
    assert za.LINK_CODE_MASK != bytes(16)


def test_the_system_block_fields():
    parsed = za.parse_advertise_data(SCAN_0000)
    assert parsed["sys_comm_ver"] == za.SYS_COMM_VERSION == 22
    assert parsed["app_comm_ver"] == za.APP_COMM_VERSION == 6
    assert parsed["num_players"] == 1
    assert parsed["nickname"] == za.ADVERTISE_NAME


def test_a_packet_composed_for_this_title_decodes_back():
    """The band's header, crypto and framing compose for Z-A's game key, offline."""
    import os

    from pokeldn.ldn import crypto, host_pia, pia_connect, reliable

    ssid = bytes.fromhex("94c5f72afd9a5f4846a07748a04cfa0c")
    keys = za.session_keys(ssid)
    pia = crypto.PiaCrypto(ssid, za.GAME_KEY)
    net = pia_connect.build_net_conn_request(2, 0xC493, bytes.fromhex("020011223344"),
                                             keys.network_id, ["169.254.1.2", "169.254.1.1"],
                                             max_stations=2)
    body = reliable.build_message(pia_connect.PROTO_NET, net)
    pad = (-len(body)) % 16
    header = crypto.PiaHeader(dst=0, src=0xC493, pktid=0, nonce8=os.urandom(8),
                              flags=(pad << 4) | 0x02, footer=0)
    packet = pia.encrypt(body + b"\xff" * pad, "169.254.1.2", header)
    assert packet[:4] == crypto.PIA_MAGIC
    assert packet[4] & 0x7F == za.PIA_VERSION
    decoded, why = host_pia.decode_datagram(packet, "169.254.1.2", pia)
    assert decoded is not None, why
    assert [m.proto for m in decoded[1]] == [pia_connect.PROTO_NET]


def test_the_record_round_trips_through_an_offer():
    """A record composed here survives the offer's framing, the shuffle and the checksum."""
    from pokeldn.za import pokemon as zp

    plain = bytearray(zp.SIZE_PARTY)
    plain[0:4] = (0x9C96AA87).to_bytes(4, "little")           # the encryption constant
    plain[zp.OFF_SPECIES:zp.OFF_SPECIES + 2] = (716).to_bytes(2, "little")
    plain[zp.OFF_NICKNAME:zp.OFF_NICKNAME + 10] = "哲爾尼亞斯".encode("utf-16-le")
    plain[zp.OFF_OT_NAME:zp.OFF_OT_NAME + 12] = "Player".encode("utf-16-le")
    plain[zp.OFF_LEVEL] = 100

    offer = zp.build_offer(bytes.fromhex("0101b90300bc815801"), bytes(plain))
    assert len(offer) == zp.OFFER_SIZE == 354

    header, back, trailer = zp.parse_offer(offer)
    assert header == bytes.fromhex("0101b90300bc815801")
    info = zp.read(back)
    assert info["species"] == 716
    assert info["level"] == 100
    assert info["nickname"] == "哲爾尼亞斯"
    assert info["ot_name"] == "Player"


def test_the_offer_framing_is_the_measured_one():
    from pokeldn.za import pokemon as zp

    assert zp.OFFER_HEADER_SIZE == 9
    assert zp.SIZE_PARTY == 0x158
    assert (zp.OFF_SPECIES, zp.OFF_NICKNAME, zp.OFF_HT_NAME, zp.OFF_OT_NAME, zp.OFF_LEVEL) \
        == (8, 0x58, 0xA8, 0xF8, 0x148)


def test_the_broadcast_acknowledgement_is_the_reference_shape():
    """A reference joiner's protocol-11 acknowledgement: the prefix and four whole entries."""
    from pokeldn.za import streams

    ack = streams.build_broadcast_ack(0xFFF2)
    assert ack.hex() == (
        "000000010004fff2" + "00" * 16 + ("fff0" + "00" * 16) * 3)
    assert len(ack) == 78
    frame = streams.frame(0xFFF0, 0xFFF3, ack, 0x00, 3)
    assert frame.hex() == ("00004afff0fff303" + ack.hex())


def test_a_broadcast_frame_declares_the_length_after_the_prefix():
    """The reference joiner's protocol-11 opening, frame for frame."""
    from pokeldn.za import streams

    assert streams.frame(0xFFF0, 0xFFF0, bytes.fromhex("000000011402b900"), 0x0F, 3).hex() \
        == "0f0004fff0fff003000000011402b900"
    nine = bytes.fromhex("000000011403b9018269fb308f")
    frame = streams.frame(0xFFF2, 0xFFF0, nine, 0x07, 3)
    assert frame.hex() == "070009fff2fff003000000011403b9018269fb308f"
    assert streams.frame_payload(frame) == nine


def test_the_session_update_acknowledgement_is_the_reference_shape():
    """A joiner's answer to a type-5 update session, as a reference pair sends it."""
    constant_id = bytes.fromhex("7f00030000020000")
    assert za.build_session_update_ack(constant_id, 0).hex() == "067f00030000020000000000000001"
    assert za.build_session_update_ack(constant_id, 1).hex() == "067f00030000020000000000010001"
    assert za.session_update_sequence(bytes.fromhex("050001010000037f")) == 1

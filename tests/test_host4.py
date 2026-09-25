"""The Pia version-4 host messages, rebuilt from fields against a retail Sword's own bytes."""
import struct

from pokeldn.ldn import host4
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mesh
from pokeldn.ldn import station4
from pokeldn.ldn import station_protocol as stp

HOST_MAC = bytes.fromhex("48f1eb209b22")
JOINER_MAC = bytes.fromhex("2ead99470f22")
HOST_VAR, JOINER_VAR = 0x31704293, 0xF7A08DE0

# A retail Sword hosting, one of each message it sent a joiner at 169.254.2.2.
UPDATE_SESSION = bytes.fromhex(
    "0111490000000000000000000200000049570bc193427031a3c27b5900000000000048f120229beb0100000000"
    "000000a9fe02013039000000a9fe020230390000010000000000000000ff0000000000000000ff00000000000000"
    "00ff0000000000000000ff0000000000000000ff0000000000000000ff00")
HOST_REQUEST = bytes.fromhex(
    "01de0901990f2247ad2e0000f7a08de00002060000a9fe02013039000000000000eb9b2220f148000031704293"
    "597bc2a3000000016980253f")
JOIN_RESPONSE = bytes.fromhex(
    "0202000101000200020008000000000002060000a9fe02013039000000000000eb9b2220f148000031704293597b"
    "c2a300000001000000000000000000000000000000000000000000000000000000000606a9fe02023039a9fe0202"
    "3039000000000000990f2247ad2e0000f7a08de0e3b6f682050100010000000000000000000000000000000000"
    "0000000000010069802541")


def host_location():
    return stp.station_location("169.254.2.1", 12345, stp.ldn_constant_id(HOST_MAC), HOST_VAR,
                                stp.ldn_service_variable_id(HOST_MAC), nat_flags=0,
                                nat_location=0, probeinit=0, private_available=1, public=False)


def joiner_location():
    return stp.station_location("169.254.2.2", 12345, stp.ldn_constant_id(JOINER_MAC),
                                JOINER_VAR, stp.ldn_service_variable_id(JOINER_MAC))


def test_update_session_rebuilds():
    u = lp.parse_update_session(UPDATE_SESSION)
    got = lp.build_update_session(u.sequence_id, u.network_id, u.host_variable_id,
                                  u.host_service_variable_id, stp.ldn_constant_id(HOST_MAC),
                                  [(n.ip, n.port, n.ranking) for n in u.occupied])
    assert got == UPDATE_SESSION


def test_host_request_rebuilds():
    got = station4.build_connection_request(stp.ldn_constant_id(JOINER_MAC), JOINER_VAR,
                                            host_location(), nat_flags=host4.REQUEST_NAT_FLAGS,
                                            nat_location=0)
    assert got + struct.pack(">I", 0x6980253F) == HOST_REQUEST


def test_join_response_rebuilds():
    got = mesh.build_join_response_v4(0, 1, [(host_location(), 0), (joiner_location(), 1)],
                                      0x69802541)
    assert got == JOIN_RESPONSE
    parsed = mesh.parse_join_response(got, version4=True)
    assert (parsed["stations"], parsed["host_index"], parsed["our_index"]) == (2, 0, 1)


def test_update_mesh_is_the_join_table_at_full_size():
    got = mesh.build_update_mesh_v4(0, [(host_location(), 0), (joiner_location(), 1)], 1)
    assert len(got) == mesh.UPDATE_MESH_SIZE_V4
    assert got[12:12 + 128] == JOIN_RESPONSE[16:16 + 128]
    parsed = mesh.parse_update_mesh(got, version4=True)
    assert parsed["update_counter"] == 1 and parsed["entries"] == 2


def test_host_response_layout():
    got = host4.build_host_response(stp.ldn_constant_id(JOINER_MAC), JOINER_VAR, 0x69802540,
                                    account=bytes(16), session=bytes(4), token=bytes(52),
                                    name="PkCamp")
    assert len(got) == host4.RESPONSE_SIZE
    assert got[:0x11].hex() == "0200090400990f2247ad2e0000f7a08de0"
    assert got[station4.OFF_RESPONSE_GATE] < station4.RESPONSE_GATE_MAX
    assert got[0x88:0x8f] == b"\x01PkCamp"
    assert station4.ack_id_of(got) == 0x69802540


def test_a_scripted_joiner_is_seated_and_heard():
    """The whole seat, driven the way a joining Sword drives it, over an in-memory wire."""
    from pokeldn.ldn import pia4, reliable4
    from pokeldn.ldn import station4 as s4

    key, net = bytes(range(16)), bytes.fromhex("11223344")
    sent, heard = [], []
    host = host4.Pia4Host(net, key, "169.254.2.1", HOST_MAC, lambda d, ip: sent.append((d, ip)),
                          log=lambda *a: None, on_data=lambda st, p, port, b: heard.append(b))
    st = host.seat("169.254.2.2", JOINER_MAC, 1)

    def from_joiner(payload, protocol, port=0):
        msg = pia4.build_message(payload, protocol=protocol, source=st.constant, port=port,
                                 message_flags=0x01, destination=1)
        nonce = bytes(8)
        iv = host4.packet_iv(net, JOINER_MAC, nonce)
        host.on_packet(pia4.build_packet(key, iv, msg, nonce8=nonce), "169.254.2.2")

    def replies():
        out = []
        for data, _ip in sent:
            h = pia4.PiaHeader4.parse(data)
            iv = host4.packet_iv(net, HOST_MAC, h.nonce8)
            plain = pia4.decrypt_payload(key, iv, pia4.ciphertext(data), h.tag)
            out += [(m["protocol"], m["payload"]) for m in pia4.parse_packet(plain)]
        sent.clear()
        return out

    req = s4.build_connection_request(host.constant, host.variable, joiner_location(),
                                      nat_flags=0, nat_location=0, with_variable_id=False)
    from_joiner(req, s4.PROTOCOL)
    (proto, ours), = replies()
    got = s4.parse_incoming_request(ours)
    assert proto == s4.PROTOCOL and got["constant_id"] == st.constant
    assert got["variable_id"] == JOINER_VAR and got["station"]["variable_id"] == host.variable

    from_joiner(s4.build_connection_response(0, host.constant, host.variable), s4.PROTOCOL)
    out = replies()
    assert out[0] == (s4.PROTOCOL, s4.build_ack(host.variable))
    assert len(out[1][1]) == host4.RESPONSE_SIZE

    from_joiner(mesh.build_join_request(0xEC9F100E), mesh.PROTOCOL)
    out = replies()
    assert out[0] == (s4.PROTOCOL, s4.build_ack(0xEC9F100E))
    parsed = mesh.parse_join_response(out[1][1], version4=True)
    assert (parsed["stations"], parsed["our_index"]) == (2, 1)

    host.tick(1e9)
    kinds = {p for p, _ in replies()}
    assert {lp.PROTOCOL, mesh.PROTOCOL, 0x58, reliable4.BROADCAST_PROTOCOL} <= kinds

    from_joiner(reliable4.build_data_message(bytes.fromhex("610000000a00")), reliable4.PROTOCOL)
    assert heard == [bytes.fromhex("610000000a00")]
    (proto, ack), = replies()
    assert proto == reliable4.PROTOCOL
    assert reliable4.parse_ack_payload(reliable4.parse_message(ack)["payload"])[0]["ack_id"] == 2

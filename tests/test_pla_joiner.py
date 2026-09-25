"""The Legends Arceus joiner against a scripted console host, message by message.

The host's side is what a hosting station sends, in the reference pair's order; the joiner's
answers are checked against what the retail joiner sent a host of ours (`docs/pla.md`, Joining a
console's network). Nothing here touches a socket.
"""

from pokeldn import pla
from pokeldn.ldn import pia6, pia_connect, reliable5
from pokeldn.pla import channel_table, data_exchange, game_channel, joiner, pokemon, trade_box

SSID = bytes.fromhex("00112233445566778899aabbccddeeff")
HOST_IP, OUR_IP = "169.254.1.1", "169.254.1.2"
HOST_MAC, OUR_MAC = bytes.fromhex("0200a9fe0101"), bytes.fromhex("0200a9fe0102")
HOST_VAR = 0x2FEE


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _msg(body, protocol, port=0, flags=0):
    return pia6.parse_messages(pia6.build_message(body, protocol=protocol, port=port,
                                                  message_flags=flags))[0]


def _open(keys, packets):
    """-> [(protocol, port, flags, payload)] of the joiner's packets, and each packet's header."""
    out = []
    for pkt in packets:
        header, plain, footer = pia6.parse_packet(keys.session_key, OUR_IP, keys.network_id, pkt)
        assert plain is not None
        for m in pia6.parse_messages(plain):
            out.append((m.protocol, m.port, m.message_flags, m.payload, header, footer))
    return out


def _data(sent, protocol, port):
    """-> the reliable data messages among `sent` on one protocol and port."""
    found = []
    for proto, p, _, payload, _, _ in sent:
        if proto == protocol and p == port:
            m = reliable5.parse(payload)
            if m["flags"] & reliable5.FLAG_APPLICATION_DATA:
                found.append(m)
    return found


def _game(body, port, seq, flags=None):
    return _msg(game_channel.build_payload_message(body, seq, flags), game_channel.PROTOCOL, port)


def _session():
    keys = pla.session_keys(SSID)
    clock = Clock()
    exchange = data_exchange.build_record(player_id=bytes.fromhex("504b4c44"), name="PkCamp")
    offer = trade_box.build_our_record(**data_exchange.read_record(exchange))
    s = joiner.JoinerSession(keys, OUR_IP, OUR_MAC, offer, exchange, our_var=0x687E,
                             log=lambda *a: None, clock=clock)
    return keys, clock, s


def _seat(keys, s):
    """Net request, join response and station list: -> what the joiner sent."""
    req = pia_connect.build_net_conn_request(2, HOST_VAR, HOST_MAC, keys.network_id,
                                             [HOST_IP, OUR_IP], max_stations=2, station_size=21)
    sent = _open(keys, s.receive([_msg(req, joiner.PROTO_NET, flags=0x31)]))
    host_cid = pia_connect.ldn_constant_id(HOST_MAC)
    our_cid = pia_connect.ldn_constant_id(OUR_MAC)
    response = pia_connect.build_session_join_response_v11(host_cid, HOST_VAR, our_cid, 0x687E,
                                                           sequence_id=0)
    update = bytes([5, 0, 0]) + host_cid
    sent += _open(keys, s.receive([_msg(response, joiner.PROTO_SESSION),
                                   _msg(update, joiner.PROTO_SESSION)]))
    return sent


def test_the_joiner_answers_the_net_request_and_joins_as_the_retail_joiner_does():
    keys, _, s = _session()
    sent = _seat(keys, s)
    net, join = sent[0], sent[1]
    assert net[0] == 0x2C and net[2] == 0x11 and net[3] == bytes.fromhex("0112000000000002")
    assert join[0] == 0x98 and join[2] == 0x01 and len(join[3]) == 115
    parsed = pia_connect.parse_session_join_v11(join[3])
    assert parsed["source_var"] == 0x687E and parsed["destination_var"] == HOST_VAR
    assert join[4].src_var == 0x687E and join[4].dst_var == HOST_VAR
    # Seated: the type 6 carries the update's sequence, then the 0x81 stream opens on port 0.
    ack = [m for m in sent if m[0] == 0x98 and m[3][0] == 6][0]
    assert ack[3] == bytes([6]) + pia_connect.ldn_constant_id(OUR_MAC) + bytes(4)
    opened = [m for m in sent if m[0] == 0x81]
    assert opened[0][3] == bytes.fromhex("0f00000b0001000101000000010000000000008000000000")
    assert opened[0][4].dst_var == joiner.MESH_DESTINATION and opened[0][5] == [HOST_VAR]


def test_the_stream_acknowledgement_is_the_retail_joiners():
    keys, _, s = _session()
    _seat(keys, s)
    content = data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x02)
    sent = _open(keys, s.receive([_msg(content, joiner.PROTO_STREAM, port=0)]))
    ack = [m for m in sent if m[0] == 0x81 and m[1] == 0][0]
    assert ack[3] == bytes.fromhex(
        "0000002cffff00020100000001" "0002" "000002000100000000000000000000000000000000"
        "000001000100000000000000000000000000000000")
    record = [m for m in sent if m[0] == 0x81 and m[1] == 1][0]
    rm = reliable5.parse(record[3])
    assert rm["flags"] == 0x1F and rm["sequence_id"] == 1 and rm["bitmap"] == [1]
    assert data_exchange.read_record(data_exchange.decompress(rm["payload"]))["name"] == "PkCamp"
    announce = _data(sent, 0x7C, 1)[0]
    assert announce["flags"] == 0x0F
    assert announce["payload"] == game_channel.JOINER_OPEN_PAYLOAD


def test_a_whole_trade_against_a_scripted_console_host():
    keys, clock, s = _session()
    _seat(keys, s)
    s.receive([_msg(data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x02),
                    joiner.PROTO_STREAM, port=0)])
    zero = bytes(game_channel.KEY_SIZE)

    # The host announces the trade box key and opens port 0: the joiner mirrors, then shows.
    sent = _open(keys, s.receive([_game(channel_table.build([(zero, True)]), 1, 1)]))
    assert not _data(sent, 0x7C, 1)          # already announced; announced once
    sent = _open(keys, s.receive([_msg(game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD),
                                       0x7C, 0)]))
    port0 = _data(sent, 0x7C, 0)
    assert port0[0]["sequence_id"] == 1 and port0[0]["flags"] == 0x0F
    assert port0[0]["payload"] == game_channel.HOST_OPEN_PAYLOAD
    shown = trade_box.read_payload(port0[1]["payload"])
    assert shown["selector"] == trade_box.SELECTOR_SHOWING and shown["record"] == s.offer
    # A host that mirrors the mirror back is acknowledged and not mirrored a second time.
    again = game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD, sequence_id=2)
    assert not _data(_open(keys, s.receive([_msg(again, 0x7C, 0)])), 0x7C, 0)

    # The console's player offers; the joiner offers back under the same selector and counter.
    theirs = pokemon.encrypt(pokemon.write(pokemon.decrypt(trade_box.REFERENCE_RECORD), level=33))
    sent = _open(keys, s.receive([_msg(trade_box.build_message(theirs, sequence_id=3), 0x7C, 0)]))
    back = trade_box.read_payload(_data(sent, 0x7C, 0)[0]["payload"])
    assert back["selector"] == trade_box.SELECTOR_OFFERING and back["counter"] == 0
    assert s.received == theirs
    # Its retransmission is acknowledged and not answered twice.
    sent = _open(keys, s.receive([_msg(trade_box.build_message(theirs, sequence_id=3), 0x7C, 0)]))
    assert not _data(sent, 0x7C, 0)

    # Confirmation and selector 7 are mirrored; after 7 the phase key opens on port 1.
    for seq, body in ((4, b"\x05\x00"), (5, b"\x07\x00")):
        sent = _open(keys, s.receive([_game(zero + body, 0, seq, flags=0x07)]))
        assert _data(sent, 0x7C, 0)[0]["payload"] == zero + body
    table = channel_table.parse(_data(sent, 0x7C, 1)[0]["payload"])
    assert table == [(trade_box.PHASE_KEY, True)]

    # Once the host announces the phase key, the joiner walks its phases, each after the host's
    # answer to the one before and the retail joiner's wait.
    sent = _open(keys, s.receive([_game(channel_table.build([(trade_box.PHASE_KEY, True)]),
                                        1, 2, flags=0x07)]))
    phases, host_seq, tables = [], 6, []
    for _ in range(40):
        clock.t += 0.5
        for m in _data(_open(keys, s.poll()), 0x7C, 0):
            phase = trade_box.read_phase(m["payload"])
            if phase is not None and phase not in phases:
                phases.append(phase)
                answer = trade_box.build_phase(trade_box.PHASE_SELECTOR_HOST, phase[1], host_seq)
                sent = _open(keys, s.receive([_msg(answer, 0x7C, 0)]))
                tables += [channel_table.parse(m["payload"]) for m in _data(sent, 0x7C, 1)]
                host_seq += 1
    assert phases == [(1, 3), (1, 6), (1, 11), (1, 14)]
    assert s.traded and s.phase_closed
    assert tables == [[(trade_box.PHASE_KEY, False)]]


def test_unacknowledged_messages_are_sent_again_and_acknowledged_ones_are_not():
    keys, clock, s = _session()
    _seat(keys, s)
    clock.t += 1.1
    again = [m for m in _open(keys, s.poll()) if m[0] == 0x81 and m[1] == 0]
    assert any(reliable5.parse(m[3])["sequence_id"] == 1 for m in again)
    host_ack = data_exchange.build_ack_message([2, 2], 0x02)
    s.receive([_msg(host_ack, joiner.PROTO_STREAM, port=0)])
    assert not [k for k in s.outstanding if k[0] == 0x81]


def test_the_rtt_answer_names_the_requester():
    keys, _, s = _session()
    _seat(keys, s)
    sent = _open(keys, s.receive([_msg(bytes.fromhex("0000000000b3c6975c0000"), 0x58)]))
    assert sent[0][3] == bytes.fromhex("0100000000b3c6975c") + HOST_VAR.to_bytes(2, "big")


def test_the_leave_is_the_retail_joiners():
    keys, _, s = _session()
    _seat(keys, s)
    leaves = _open(keys, s.leave())
    assert len(leaves) == 4
    body = leaves[0][3]
    assert body[0] == 3 and len(body) == 24
    assert body[5:17] == pia_connect.ldn_constant_id(OUR_MAC) + bytes(2) + (0x687E).to_bytes(2, "big")
    assert body[18:22] == bytes([169, 254, 1, 2]) and body[22:24] == (12345).to_bytes(2, "big")


def test_driving_offers_once_and_confirms_after_the_host_offers():
    keys, clock, s = _session()
    s.drive = True
    _seat(keys, s)
    s.receive([_msg(data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x02),
                    joiner.PROTO_STREAM, port=0)])
    zero = bytes(game_channel.KEY_SIZE)
    s.receive([_game(channel_table.build([(zero, True)]), 1, 1)])
    s.receive([_msg(game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD), 0x7C, 0)])
    theirs = pokemon.encrypt(pokemon.write(pokemon.decrypt(trade_box.REFERENCE_RECORD), level=33))
    sent = _open(keys, s.receive([_msg(trade_box.build_message(
        theirs, sequence_id=2, selector=trade_box.SELECTOR_SHOWING), 0x7C, 0)]))
    selectors = [trade_box.read_payload(m["payload"])["selector"] for m in _data(sent, 0x7C, 0)]
    assert selectors == [trade_box.SELECTOR_SHOWING, trade_box.SELECTOR_OFFERING]
    sent = _open(keys, s.receive([_msg(trade_box.build_message(theirs, sequence_id=3), 0x7C, 0)]))
    bodies = [game_channel.split_message(m["payload"])[1] for m in _data(sent, 0x7C, 0)]
    assert bodies == [b"\x05\x00"]           # no second offer; the confirmation
    sent = _open(keys, s.receive([_game(zero + b"\x05\x00", 0, 4, flags=0x07)]))
    assert not _data(sent, 0x7C, 0)          # our 5 is already out; not mirrored
    clock.t += 1.6
    sent = _open(keys, s.poll())
    fresh = [m for m in _data(sent, 0x7C, 0) if m["sequence_id"] > 5]   # past the resends
    assert [game_channel.split_message(m["payload"])[1] for m in fresh] == [b"\x07\x00"]
    assert channel_table.parse(_data(sent, 0x7C, 1)[-1]["payload"]) == [(trade_box.PHASE_KEY, True)]


def test_the_console_s_migration_request_is_noted_and_left_unanswered():
    """The retail console's Net request, then after our ack the same request with is-migrating set
    and a bare NetStartHostMigration: the joiner notes the request once and answers only the Net
    request, as a console that is handed the host role owes the old host nothing."""
    keys, clock, s = _session()
    req = pia_connect.build_net_conn_request(2, HOST_VAR, HOST_MAC, keys.network_id,
                                             [HOST_IP, OUR_IP], max_stations=2, station_size=21)
    s.receive([_msg(req, joiner.PROTO_NET, flags=0x31)])
    assert s.migration_asked is None
    migrating = bytearray(pia_connect.build_net_conn_request(
        3, HOST_VAR, HOST_MAC, keys.network_id, [HOST_IP, OUR_IP], max_stations=2,
        station_size=21))
    clock.t += 0.5
    sent = _open(keys, s.receive([_msg(bytes(migrating), joiner.PROTO_NET, flags=0x31),
                                  _msg(bytes.fromhex("01400000"), joiner.PROTO_NET, flags=0x31)]))
    assert s.migration_asked == clock.t
    assert [m[0] for m in sent] == [0x2C]
    clock.t += 0.5
    s.receive([_msg(bytes.fromhex("01400000"), joiner.PROTO_NET, flags=0x31)])
    assert s.migration_asked == clock.t - 0.5

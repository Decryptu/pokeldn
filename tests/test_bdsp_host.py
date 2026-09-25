"""The BDSP room host: its builders against a retail host's own messages, and a scripted joiner.

The references are a French Shining Pearl 1.3.0 hosting the Union Room, decrypted off the air, with
the joiner's connection request it accepted. Each is zlib-compressed, base64.
"""
import base64
import struct
import zlib

from pokeldn.bdsp import host, room
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn import reliable5 as rl
from pokeldn.ldn import station_protocol as stp


def _ref(b64):
    return zlib.decompress(base64.b64decode(b64))


UPDATE_SESSION = _ref("eNpjFPRkgAEmIH6RwmCwJNLh+uJD1ZEQUY+PCkqzXzNC1az8V8BoYAlhMIEYMAmG/6QxAEm/FCc=")
REQUEST = _ref("eNpjZGB5PVtJ4aMHA8N1h8glnP8Z0CGDBhvbyn8FTAaWEJIBDCI6e168OMXAoF1f77FPKMqYlZGBkYEIwAgEAdnO"
               "ibkFDFQDjFRXSIxZAE50HHI=")
RESPONSE = _ref("eNpjYmCJ6Ox58eIUA4N2fb0HpwiTBLMMgwpDBHMGYw3zFMYlDAwqTGwMDCv/FTAaWDKAwevZSgofPRgYrjtE"
                "LomsPrQYKMTIQADk6dzvZwQC99KissQ8BvoDZoZRMAqGPritFGwGAIs2GHk=")
JOIN_RESPONSE = _ref("eNpjYmJgZGRgYuAAQhBgYmNgWPmvgNHAEsxleD1bSeGjBwPDdYfIJZHVhxYDhRgZCAA2NqAJTAaWEBIi"
                     "FtHZ8+LFKQYG7fp6j31CUcasjLjNAUndVgo2BwA/Mhdm")
UPDATE_MESH = _ref("eNpTYGIAAUZGBiYGJjYGhpX/ChgNLMFiDK9nKyl89GBguO4QuSSy+tBikDoGAoCNDWgCk4ElhISIRXT2"
                   "vHhxioFBu77eY59QlDErI25zGAlbMQoGCAAA3vEV7Q==")

HOST_MAC = bytes.fromhex("48f1eb209b22")
JOINER_MAC = bytes.fromhex("cae858e8898c")
HOST_VAR = 0xD74059A4
JOINER_VAR = 0x2B7F7F48


def _host_location():
    return host.host_location("169.254.112.1", stp.ldn_constant_id(HOST_MAC), HOST_VAR,
                              stp.ldn_service_variable_id(HOST_MAC))


def _joiner_location(request=REQUEST):
    off = 16 + 2 * request[15]
    size = struct.unpack_from(">H", request, off)[0]
    return request[off + 2:off + 2 + size]


def test_update_session_is_the_retail_hosts():
    us = lp.parse_update_session(UPDATE_SESSION)
    assert lp.build_update_session(
        us.sequence_id, us.network_id, HOST_VAR, stp.ldn_service_variable_id(HOST_MAC),
        stp.ldn_constant_id(HOST_MAC),
        [("169.254.112.1", 12345, 0), ("169.254.112.2", 12345, 1)]) == UPDATE_SESSION


def test_connection_response_is_the_retail_hosts():
    assert host.build_connection_response(stp.ldn_constant_id(JOINER_MAC), JOINER_VAR,
                                          _host_location(), 0x6E2CDF8F, ["Gurvan"],
                                          0xDB225336) == RESPONSE


def test_join_response_and_update_mesh_are_the_retail_hosts():
    entries = [(_host_location(), 0, 0), (_joiner_location(), 1, 1)]
    assert host.build_join_response(entries, 1, 0xDB225337, 0) == JOIN_RESPONSE
    assert host.build_update_mesh(entries, 1) == UPDATE_MESH


def test_advertisement_layout():
    data = host.build_advertise_data(0xF85CC8B4, 0x36DEE059)
    assert data == bytes.fromhex("b4c85cf8000000000810000059e0de3600")


def test_connection_request_parses():
    req = host.parse_connection_request(REQUEST)
    assert req["target_variable_id"] == HOST_VAR
    assert req["location"]["variable_id"] == JOINER_VAR
    assert req["player_names"] == ["PkCamp"]


class Console:
    """A joining console, sending what a retail joiner sends and reading the host with its keys."""

    def __init__(self, session, ip="169.254.112.2", mac=JOINER_MAC, var=JOINER_VAR):
        self.s, self.ip, self.mac, self.var = session, ip, mac, var
        self.nonce = 0
        self.seen = []

    def send(self, messages, now, dst_var=0):
        self.nonce += 1
        pkt = host.wrap(self.s.keys, self.mac, self.var, dst_var, self.nonce.to_bytes(8, "big"),
                        messages)
        return self.read(self.s.receive(pkt, self.ip, now))

    def read(self, out):
        got = []
        for pkt, ip in out:
            h, msgs = host.unwrap(self.s.keys, self.s.our_mac, pkt)
            assert msgs is not None, "a host packet did not authenticate"
            got += [(h, m) for m in msgs]
        self.seen += got
        return got

    def request(self, host_const, host_var):
        """The retail-accepted request, retargeted to this host."""
        loc = stp.station_location(self.ip, 12345, stp.ldn_constant_id(self.mac), self.var,
                                   stp.ldn_service_variable_id(self.mac))
        return stp.build_connection_request(host_const, host_var, host.PROTOCOLS, loc,
                                            player_infos=[stp.player_info("Gurvan", "", 3)],
                                            ack_id=7)


def _session(record=None):
    adv = host.Advertisement(0x6E2CDF8F, 0x03326B15)
    return host.HostSession(adv.keys, adv, "169.254.112.1", HOST_MAC, HOST_VAR, name="PkCamp",
                            record=record)


def test_a_scripted_console_joins_and_is_answered():
    s = _session()
    c = Console(s)
    first = c.read(s.seat(c.ip, c.mac, 0.0))
    [(h, m)] = first
    assert m.protocol == lp.PROTOCOL
    us = lp.parse_update_session(m.payload)
    assert [n.ip for n in us.nodes[:2]] == ["169.254.112.1", "169.254.112.2"]
    assert h.src_var == HOST_VAR and us.host_variable_id == HOST_VAR

    # until acknowledged it repeats; after, it stops
    assert c.read(s.tick(0.15))
    c.send([(lp.build_ack(us.sequence_id), lp.PROTOCOL, 0, lp.MESSAGE_FLAGS, 0)], 0.2)
    assert not c.read(s.tick(0.5))

    got = c.send([(c.request(s.constant_id, s.variable_id), stp.PROTOCOL, 0, 1, 0)], 1.0)
    [(_, resp)] = got
    r = stp.parse_connection_response(resp.payload)
    assert r["result"] == stp.RESULT_ACCEPTED and len(resp.payload) == 949
    assert r["target_variable_id"] == JOINER_VAR
    assert r["location"]["variable_id"] == HOST_VAR
    assert r["protocols"] == list(host.PROTOCOLS)
    c.send([(stp.build_ack(r["ack_id"]), stp.PROTOCOL, 0, 1, 0)], 1.1)
    assert not c.read(s.tick(1.7))

    got = c.send([(mp.build_join_request(1), mp.PROTOCOL, 0, 1, 0)], 2.0)
    kinds = [(m.protocol, m.payload[0]) for _, m in got]
    assert kinds == [(stp.PROTOCOL, stp.ACK), (mp.PROTOCOL, mp.JOIN_RESPONSE)]
    assert stp.parse_ack(got[0][1].payload) == 1
    jr = mp.parse_join_response(got[1][1].payload)
    assert (jr["stations"], jr["our_index"], jr["max_active"]) == (2, 1, 8)
    assert jr["station_info"][1]["location"]["variable_id"] == JOINER_VAR

    got = c.send([(stp.build_ack(jr["ack_id"]), stp.PROTOCOL, 0, 1, 0)], 2.1)
    game = [m for _, m in got if m.protocol == rl.PROTOCOL]
    assert len(game) == 1
    d = rl.parse(game[0].payload)
    assert d["sequence_id"] == 1 and d["flags"] == 0x0F
    assert room.parse(d["payload"])["data_id"] == room.JOIN

    got = c.read(s.tick(2.2))
    protos = sorted({m.protocol for _, m in got})
    assert protos == [mp.PROTOCOL, 0x58, host.UNRELIABLE_PROTOCOL]

    # a request for the character state is acknowledged and answered
    msg = rl.build_header(0x0F, 1, 4, lowest_pending=1) + room.build_request(room.STATE)
    got = c.send([(msg, rl.PROTOCOL, 0, 1, 2)], 2.5, dst_var=HOST_VAR)
    acks = [rl.parse(m.payload) for _, m in got if m.protocol == rl.PROTOCOL]
    assert acks[0]["is_ack"]
    assert rl.parse_ack_payload(acks[0]["payload"])["entries"][0]["ack_id"] == 2
    answer = [a for a in acks if not a["is_ack"]]
    assert room.parse(answer[0]["payload"])["data_id"] == room.STATE
    assert s.counters["state_requests"] == 1

    # our NetJoinData is repeated until acknowledged, then dropped
    assert any(m.protocol == rl.PROTOCOL for _, m in c.read(s.tick(3.0)))
    ack = rl.build_ack_message(3)
    c.send([(ack, rl.PROTOCOL, 0, 1, 2)], 3.1, dst_var=HOST_VAR)
    assert not s.joiner.tx_pending


def test_the_joiners_clock_request_is_answered_with_its_tick():
    """A joiner leaves about ten seconds after its sync clock requests go unanswered."""
    from pokeldn.ldn import sync_clock
    s = _session()
    c = Console(s)
    c.read(s.seat(c.ip, c.mac, 0.0))
    c.send([(c.request(s.constant_id, s.variable_id), stp.PROTOCOL, 0, 1, 0)], 0.1)
    got = c.send([(bytes.fromhex("00002529e0aa3ed10000000000000000"), sync_clock.PROTOCOL, 0, 1,
                   1)], 1.0, dst_var=HOST_VAR)
    [(h, m)] = got
    tick, clock = sync_clock.parse_message(m.payload)
    assert (m.protocol, tick, h.dst_var) == (sync_clock.PROTOCOL, 0x2529E0AA3ED1, JOINER_VAR)
    assert clock > 0


def test_a_reassociation_starts_the_handshake_over():
    s = _session()
    c = Console(s)
    c.read(s.seat(c.ip, c.mac, 0.0))
    c.send([(c.request(s.constant_id, s.variable_id), stp.PROTOCOL, 0, 1, 0)], 0.1)
    s.leave(5.0)
    [(_, m)] = c.read(s.seat(c.ip, c.mac, 6.0))
    assert m.protocol == lp.PROTOCOL and s.joiner.variable_id is None


def _joined(partner):
    """A session whose console has finished the mesh join, and its reliable sequence counter."""
    s = _session()
    s.on_game, s.on_tick = partner.game, partner.tick
    c = Console(s)
    c.read(s.seat(c.ip, c.mac, 0.0))
    [(_, resp)] = c.send([(c.request(s.constant_id, s.variable_id), stp.PROTOCOL, 0, 1, 0)], 0.1)
    c.send([(stp.build_ack(stp.parse_connection_response(resp.payload)["ack_id"]), stp.PROTOCOL, 0,
             1, 0)], 0.2)
    got = c.send([(mp.build_join_request(1), mp.PROTOCOL, 0, 1, 0)], 0.3)
    jr = mp.parse_join_response(got[1][1].payload)
    c.send([(stp.build_ack(jr["ack_id"]), stp.PROTOCOL, 0, 1, 0)], 0.4)
    c.send([(rl.build_ack_message(2), rl.PROTOCOL, 0, 1, 2)], 0.5, dst_var=HOST_VAR)
    return s, c


def _game_out(got):
    out = []
    for _, m in got:
        if m.protocol == rl.PROTOCOL:
            d = rl.parse(m.payload)
            if not d["is_ack"]:
                out.append(d["payload"])
    return out


def test_a_scripted_trade_is_answered_through_the_save():
    offer = bytes(328)
    p = host.TradePartner(offer, complete=True, approach_delay=3.0)
    s, c = _joined(p)
    seq = [0]

    def say(message, now):
        seq[0] += 1
        msg = rl.build_header(0x07 | (0x08 if seq[0] == 1 else 0), seq[0], len(message),
                              lowest_pending=seq[0]) + message
        got = _game_out(c.send([(msg, rl.PROTOCOL, 0, 1, 2)], now, dst_var=HOST_VAR))
        # acknowledge what the host sent, so its window drains
        c.send([(rl.build_ack_message(s.joiner.tx_seq), rl.PROTOCOL, 0, 1, 2)], now,
               dst_var=HOST_VAR)
        return got

    say(room.build_state(room.STATE_RECRUITMENT_TRADE, 1), 1.0)
    assert not _game_out(c.read(s.tick(3.5)))
    [approach] = _game_out(c.read(s.tick(4.1)))
    assert approach == room.build_talk_reserve()
    c.send([(rl.build_ack_message(s.joiner.tx_seq), rl.PROTOCOL, 0, 1, 2)], 4.1, dst_var=HOST_VAR)

    [talk] = say(room.build_talk_reserve_result(can_talk=0, is_recruitment=1, emoticon_state=4),
                 4.2)
    assert talk == bytes.fromhex("0600050001000000")
    [traner] = say(room.build_trade_traner("Gurvan", 44466, 4080), 5.0)
    assert traner[0] == room.TRADE_TRANER and len(traner) == 35
    [poke] = say(room.build_trade_poke(bytes(328)), 5.5)
    assert poke == room.build_trade_poke(offer)
    [ok] = say(room.build_fields(room.TRADE_POKE_CHECK_OK, 1), 6.0)
    assert ok == room.build_fields(room.TRADE_POKE_CHECK_OK, 1)
    [ready] = say(room.build_trade_ready_ok(room.TRADE_STATE_WAIT, 0), 7.0)
    assert ready == room.build_trade_ready_ok()

    # the security phase: each of the console's states is mirrored, and repeated once a second
    for t, theirs in ((8.0, 1), (8.2, 2), (8.4, 3), (8.6, 4)):
        [mine] = say(room.build_trade_ready_ok(theirs, 1), t)
        assert mine == room.build_trade_ready_ok(room.mirror_trade_state(theirs), 1)
    assert _game_out(c.read(s.tick(9.7)))
    say(room.build_fields(room.RETURN_SELECT, 0), 30.0)
    assert p.trades == 1
    assert not _game_out(c.read(s.tick(32.0)))


def test_the_ready_ok_is_not_answered_without_complete():
    p = host.TradePartner(bytes(328), complete=False)
    assert p.game(None, {"data_id": room.TRADE_READY_OK,
                         "fields": {"isTradeOk": 0, "tradeState": 2}},
                  room.build_trade_ready_ok(), 1.0) == []


def test_an_ack_names_our_own_lowest_pending_not_theirs():
    """The console advances its receive window to the lowest-pending an ack carries. With the
    console's messages outnumbering ours, an ack carrying its own next id made it discard our
    trainer record and our Pokemon as repeats."""
    s, c = _joined(host.TradePartner(bytes(328)))
    for seq in range(1, 7):
        msg = rl.build_header(0x07 | (0x08 if seq == 1 else 0), seq, 4, lowest_pending=seq) \
            + room.build_request(0x77)
        got = c.send([(msg, rl.PROTOCOL, 0, 1, 2)], 1.0 + seq / 10, dst_var=HOST_VAR)
    acks = [rl.parse(m.payload) for _, m in got if m.protocol == rl.PROTOCOL]
    ack = [a for a in acks if a["is_ack"]][-1]
    entry = rl.parse_ack_payload(ack["payload"])["entries"][0]
    assert entry["ack_id"] == 7
    assert ack["lowest_pending"] == entry["field_0x50"] == s.joiner.tx_seq == 2

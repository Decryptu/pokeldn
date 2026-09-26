"""The Legends Z-A host against an emulated pair's host and against a scripted joiner.

Every hex string below is a message an emulated Z-A host or joiner sent in one reference session:
session id 9e9c14c2238b018697293395cba1e6d2, host 127.0.0.2 id 0xefb0, joiner 127.0.0.3 id 0x5ad2.
"""
import pytest

from pokeldn import za
from pokeldn.ldn import crypto, esp32, esp32_sim, esp32_wlan, host_pia, pia_connect, reliable
from pokeldn.za import host as za_host
from pokeldn.za import streams

SSID = bytes.fromhex("9e9c14c2238b018697293395cba1e6d2")
HOST_IP, JOINER_IP = "127.0.0.2", "127.0.0.3"
HOST_MAC = bytes.fromhex("02007f000002")
HOST_VAR, JOINER_VAR = 0xEFB0, 0x5AD2
NETWORK_ID = 0xA6E37B59

JOIN = bytes.fromhex(
    "000a010003050501060009010a030b040c040d070f000006ac9dd2c27f000300000200005ad2000006000000"
    "000000000000000000000000000000000000000000000000000000007f00020000020000efb00101007f0000"
    "03303900000000000000010000000000000000000000010120")
STATION_TAIL = ("00000000000000000000000000000000000000000000000000000000000000000101000000000000"
                "000000010000000000000000000000010120")
UPDATE = ("05{seq}010000037f00020000020000efb002000001{seq}000000007f00020000020000efb07f000002"
          "3039000000000006" + STATION_TAIL[2:] + "7f000300000200005ad27f00000330390100010000"
          "06" + STATION_TAIL[2:])
NET_STATUS = bytes.fromhex(
    "0111005800000002efb07f0002000002000000000000a6e37b5901000400000000007f0000020000000000000000"
    "000000003039000100007f000003000000000000000000000000303900ff00000000000000000000000000000000"
    "0000000000ff0000000000000000000000000000000000000000")
NET_PROPERTY = bytes.fromhex(
    "015000700000000100000000a6e37b5900020004000000000000000102010000005c00000014005c160006205897"
    "729c0ab7b7ab6066a161f5d5e1010200000001012000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000000000003030303030303030"
    "000000000000000008000000")


@pytest.mark.parametrize("seq", [0, 1])
def test_the_update_session_is_the_reference_hosts(seq):
    join = pia_connect.parse_session_join(JOIN)
    update = pia_connect.build_session_update(
        join, pia_connect.ldn_constant_id(HOST_MAC), HOST_VAR, HOST_IP, " ",
        host_token=za_host.HOST_TOKEN, update_sequence=seq)
    assert update.hex() == UPDATE.format(seq=f"{seq:04x}")


def test_the_net_messages_are_the_reference_hosts():
    assert pia_connect.build_net_conn_request(
        2, HOST_VAR, HOST_MAC, NETWORK_ID, [HOST_IP, JOINER_IP], max_stations=4) == NET_STATUS

    class Network:
        ssid, participants, max_participants, SCENE_ID = SSID, [(1, JOINER_IP)], 4, za.SCENE_ID
    assert host_pia.build_net_property_update(
        Network, za.build_advertise_data("00000000", num_players=2),
        property_byte=za_host.PROPERTY_BYTE) == NET_PROPERTY


class ScriptedJoiner:
    """A joiner that sends what the reference joiner sent, framed by the same codecs, and reads
    back every message the host puts on the wire."""

    def __init__(self, host):
        self.host = host
        self.pia = crypto.PiaCrypto(SSID, za.GAME_KEY)
        self.network = type("N", (), {"our_ip": JOINER_IP})
        self.seq = {streams.PROTO_RELIABLE: 1}
        self.heard = []

    def send(self, proto, payload, dst=HOST_VAR, now=0.0):
        data = host_pia.build_messages(self.network, self.pia, [(proto, payload)], dst_var=dst,
                                       src_var=JOINER_VAR, footer_var=HOST_VAR)
        self.host.receive(data, JOINER_IP, now=now)

    def game(self, inner, now):
        seq = self.seq[streams.PROTO_RELIABLE]
        self.seq[streams.PROTO_RELIABLE] = seq + 1
        self.send(streams.PROTO_RELIABLE,
                  reliable.build_reliable(seq, seq, inner, flagsA=reliable.FLAGSA_GBA), now=now)

    def run(self, until, now):
        t = now
        while t <= until:
            for data, ip in self.host.tick(now=t):
                assert ip == JOINER_IP
                decoded, why = host_pia.decode_datagram(data, HOST_IP, self.pia)
                assert decoded is not None, why
                for m in decoded[1]:
                    self.heard.append((t, m.proto, m.payload))
            t += 0.01
        return t

    def game_heard(self):
        """Each data frame once: a retransmission carries the sequence it first went out under."""
        out, seen = [], set()
        for t, proto, payload in self.heard:
            if proto not in (streams.PROTO_RELIABLE, streams.PROTO_BROADCAST):
                continue
            r = reliable.parse_reliable(payload)
            if r.flagsA == reliable.FLAGSA_CTRL or (proto, r.seq) in seen:
                continue
            seen.add((proto, r.seq))
            inner = streams.frame_payload(payload) if proto == streams.PROTO_BROADCAST \
                else r.payload
            out.append((t, proto, inner))
        return out


def test_a_whole_trade_against_a_scripted_joiner(monkeypatch):
    """The preview goes out marked 1, the pick marked 0 and only after the joiner's own pick, the
    confirmation and commit after the joiner's, and every step is answered with its own byte. The
    board's LED shows the done look once, on the fourth step."""
    board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    radio = esp32.Radio(board.host_stream())
    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    monkeypatch.setattr(esp32_wlan, "_radio", radio)
    offer = bytes.fromhex("0101b90300bc815801") + bytes(range(256)) + bytes(88) + b"\x01"
    host = za_host.HostSession(
        ssid=SSID, our_ip=HOST_IP, our_mac=HOST_MAC, guest_ip=JOINER_IP, code="00000000",
        identity=bytes.fromhex("1400") + bytes(104), identity_tail=bytes.fromhex("1403b9018269fb308f"),
        selection=bytes.fromhex("0100") + bytes(1209), offer=offer, host_var=HOST_VAR,
        clock=lambda: 0.0)
    joiner = ScriptedJoiner(host)
    t = joiner.run(0.1, 0.0)
    assert any(p == pia_connect.PROTO_NET and m[:2] == b"\x01\x11" for _, p, m in joiner.heard)
    joiner.send(pia_connect.PROTO_NET, bytes.fromhex("0112000000000002"), dst=0, now=t)
    joiner.send(pia_connect.PROTO_SESSION, JOIN, dst=0, now=t)
    joiner.send(pia_connect.PROTO_SESSION, bytes.fromhex("067f00030000020000000000000001"), now=t)
    t = joiner.run(t + 1.3, t)
    joiner.send(pia_connect.PROTO_SESSION, bytes.fromhex("067f00030000020000000000010001"), now=t)
    t = joiner.run(t + 3.0, t)
    preview = [x for x in joiner.game_heard() if x[2][:2] == b"\x01\x01"]
    assert len(preview) == 1 and preview[0][2][-1] == za_host.OFFER_PREVIEW

    joiner.game(offer, t)                           # a retail joiner previews every cursor move
    t = joiner.run(t + 2.0, t)
    joiner.game(offer[:9] + bytes(344) + b"\x01", t)
    t = joiner.run(t + 2.0, t)
    assert len([x for x in joiner.game_heard() if x[2][:2] == b"\x01\x01"]) == 1
    joiner.game(offer[:-1] + b"\x00", t)            # the joiner's pick
    t = joiner.run(t + 2.0, t)
    offers = [x[2] for x in joiner.game_heard() if x[2][:2] == b"\x01\x01"]
    assert len(offers) == 2 and offers[1][-1] == za_host.OFFER_PICK
    assert offers[1][:-1] == offer[:-1]

    joiner.game(bytes.fromhex("0102b90100"), t)
    t = joiner.run(t + 3.0, t)
    tail = [x[2].hex() for x in joiner.game_heard() if x[2][:1] == b"\x01"][-2:]
    assert tail == ["0102b90100", "0104b90100"]
    joiner.game(bytes.fromhex("0104b90100"), t)
    for step in ("03", "06", "0b", "0e"):
        radio.drain()
        assert board.led_looks == []
        joiner.game(bytes.fromhex("0200b901" + step), t)
        t = joiner.run(t + 0.2, t)
    answers = [x[2].hex() for x in joiner.game_heard() if x[1] == streams.PROTO_BROADCAST
               and x[2][4:6] == b"\x02\x01"]
    assert answers == ["000000020201b901" + s for s in ("03", "06", "0b", "0e")]
    assert host.trade_complete
    t = joiner.run(t + 1.0, t)
    radio.drain()
    radio.close()
    assert board.led_looks == [bytes.fromhex("06ff2003b80b")]   # ramp-up, peak 255, 800 ms, 3000 ms


def test_the_joiner_answers_the_hosts_pick_and_not_its_cursor(tmp_path):
    """`bin/za_join.py` against a scripted host that previews three cursor moves before its pick:
    the joiner's preview goes out marked 1, and its pick, marked 0, only after the host's pick."""
    import argparse

    import za_join
    offer = bytes.fromhex("0101b90300bc815801") + bytes(344) + b"\x01"
    (tmp_path / "offer.bin").write_bytes(offer)
    args = argparse.Namespace(game_dir=str(tmp_path), trade_offer=str(tmp_path / "offer.bin"),
                              selection_count=0,
                              selection_delay=0.0, selection_period=1.0, offer_delay=1.0)
    sent = []
    game = za_join.GameStreams(args, lambda proto, body, **kw: sent.append((proto, body)),
                               lambda *a, **kw: None, None)

    def offers():
        out = []
        for proto, body in sent:
            r = reliable.parse_reliable(body)
            if proto == za_join.GAME_RELIABLE and r.flagsA != reliable.FLAGSA_CTRL \
                    and r.payload[:2] == b"\x01\x01":
                out.append(r.payload)
        return out

    t, seq = 0.0, 1
    for mark in (1, 1, 1, 0):
        if mark == 0:
            assert [o[-1] for o in offers()] == [za_host.OFFER_PREVIEW]
        host_offer = offer[:-1] + bytes([mark])
        game.on_message(za_join.GAME_RELIABLE,
                        reliable.build_reliable(seq, seq, host_offer, flagsA=reliable.FLAGSA_GBA), t)
        seq += 1
        for _ in range(100):
            t += 0.02
            game.pump(HOST_VAR, JOINER_VAR, t)
    assert [o[-1] for o in offers()] == [za_host.OFFER_PREVIEW, za_host.OFFER_PICK]
    assert offers()[1][:-1] == offer[:-1]

    # The host's commit starts the four steps; the joiner marks the trade done on the last one.
    assert game.traded_at is None
    commit_at = t
    game.on_message(za_join.GAME_RELIABLE,
                    reliable.build_reliable(seq, seq, bytes.fromhex("0104b90100"),
                                            flagsA=reliable.FLAGSA_GBA), t)
    while t < commit_at + 16.0:
        t += 0.02
        game.pump(HOST_VAR, JOINER_VAR, t)
    assert game.traded_at is not None and abs(game.traded_at - (commit_at + 14.6)) < 0.05

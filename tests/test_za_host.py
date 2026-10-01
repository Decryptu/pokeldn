"""The Legends Z-A host against a scripted joiner, with messages from one emulated reference session."""
import pytest

from pokeldn import za
from pokeldn.app import received
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


@pytest.mark.parametrize("cancel, queue", [(False, False), (True, False), (False, True)])
def test_a_whole_trade_against_a_scripted_joiner(monkeypatch, cancel, queue):
    """Preview marked 1, pick marked 0 after the joiner's, every step answered; 0103 moves the round
    on (0xc8dda0, 0x2dc52b4). A queue's second trade previews and picks the next record."""
    board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    radio = esp32.Radio(board.host_stream())
    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    monkeypatch.setattr(esp32_wlan, "_radio", radio)
    offer = bytes.fromhex("0101b90300bc815801") + bytes(range(256)) + bytes(88) + b"\x01"
    second = bytes.fromhex("0101b90300bc815801") + bytes(range(255, -1, -1)) + bytes(88) + b"\x01"
    host = za_host.HostSession(
        ssid=SSID, our_ip=HOST_IP, our_mac=HOST_MAC, guest_ip=JOINER_IP, code="00000000",
        identity=bytes.fromhex("1400") + bytes(104), identity_tail=bytes.fromhex("1403b9018269fb308f"),
        selection=bytes.fromhex("0100") + bytes(1209), offer=[offer, second] if queue else offer,
        host_var=HOST_VAR,
        clock=lambda: 0.0, renew_offer=lambda o: o[:9] + bytes([o[9] ^ 0xFF]) + o[10:])
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
    assert host.console_pick == offer[:-1] + b"\x00"

    rnd = "00"
    if cancel:
        joiner.game(bytes.fromhex("0103b9020100"), t)   # an emulated Z-A's Cancel: round 1, reason 0
        t = joiner.run(t + 1.0, t)
        joiner.game(offer[:-1] + b"\x00", t)            # the joiner picks again
        t = joiner.run(t + 2.0, t)
        offers = [x[2] for x in joiner.game_heard() if x[2][:2] == b"\x01\x01"]
        assert len(offers) == 3 and offers[2][-1] == za_host.OFFER_PICK
        rnd = "01"
    joiner.game(bytes.fromhex("0102b901" + rnd), t)
    t = joiner.run(t + 3.0, t)
    tail = [x[2].hex() for x in joiner.game_heard() if x[2][:1] == b"\x01"][-2:]
    assert tail == ["0102b901" + rnd, "0104b901" + rnd]
    joiner.game(bytes.fromhex("0104b901" + rnd), t)
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

    if queue:
        t = joiner.run(t + za_host.PREVIEW_DELAY, t)
        offers = [x[2] for x in joiner.game_heard() if x[2][:2] == b"\x01\x01"]
        assert offers[-1] == second[:-1] + bytes([za_host.OFFER_PREVIEW])
        joiner.game(offer[:-1] + b"\x00", t)
        t = joiner.run(t + 2.0, t)
        offers = [x[2] for x in joiner.game_heard() if x[2][:2] == b"\x01\x01"]
        assert offers[-1] == second[:-1] + bytes([za_host.OFFER_PICK])
        joiner.game(bytes.fromhex("0102b90100"), t)
        t = joiner.run(t + 3.0, t)
        joiner.game(bytes.fromhex("0104b90100"), t)
        for step in ("03", "06", "0b", "0e"):
            joiner.game(bytes.fromhex("0200b901" + step), t)
            t = joiner.run(t + 0.2, t)
        assert host.trades == 2
        offer = second

    # A retail Z-A returning to its box in the same seat draws our last offer again, renewed.
    joiner.game(offer[:-1] + b"\x00", t)
    t = joiner.run(t + 2.0, t)
    offers = [x[2] for x in joiner.game_heard() if x[2][:2] == b"\x01\x01"]
    assert offers[-1][-1] == za_host.OFFER_PICK and offers[-1][9] == offer[9] ^ 0xFF
    assert host.trades == (2 if queue else 1)
    joiner.game(offer[:9] + bytes(344) + b"\x01", t)    # its cursor, back on the box
    joiner.run(t + 1.0, t)
    assert host.console_pick == offer[:-1] + b"\x00"


def test_the_joiner_answers_the_hosts_pick_and_not_its_cursor(tmp_path, capsys):
    """`bin/za_join.py` against a scripted host that previews three cursor moves before its pick:
    the joiner's preview goes out marked 1, and its pick, marked 0, only after the host's pick. The
    second queued record is previewed after the trade and picked for the host's next pick."""
    import argparse

    import za_join
    offer = bytes.fromhex("0101b90300bc815801") + bytes(344) + b"\x01"
    second = bytes.fromhex("0101b90300bc815801") + bytes(range(255, 0, -1)) + bytes(89) + b"\x01"
    (tmp_path / "offer.bin").write_bytes(offer)
    (tmp_path / "second.bin").write_bytes(second)
    args = argparse.Namespace(game_dir=str(tmp_path),
                              trade_offer=[str(tmp_path / "offer.bin"), str(tmp_path / "second.bin")],
                              selection_count=0, offer_out=str(tmp_path / "theirs.pa9"),
                              selection_delay=0.0, selection_period=1.0, offer_delay=1.0)

    def theirs(species, mark):
        plain = bytearray(za.pokemon.SIZE_PARTY)
        plain[8] = species
        return za.pokemon.build_offer(offer[:9], bytes(plain), bytes([mark]))
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
    for species, mark in ((1, 1), (2, 1), (3, 1), (3, 0)):
        if mark == 0:
            assert [o[-1] for o in offers()] == [za_host.OFFER_PREVIEW]
        host_offer = theirs(species, mark)
        game.on_message(za_join.GAME_RELIABLE,
                        reliable.build_reliable(seq, seq, host_offer, flagsA=reliable.FLAGSA_GBA), t)
        seq += 1
        for _ in range(100):
            t += 0.02
            game.pump(HOST_VAR, JOINER_VAR, t)
    assert [o[-1] for o in offers()] == [za_host.OFFER_PREVIEW, za_host.OFFER_PICK]
    assert offers()[1][:-1] == offer[:-1]

    assert game.traded_at is None
    commit_at = t
    game.on_message(za_join.GAME_RELIABLE,
                    reliable.build_reliable(seq, seq, bytes.fromhex("0104b90100"),
                                            flagsA=reliable.FLAGSA_GBA), t)
    while t < commit_at + 16.0:
        t += 0.02
        game.pump(HOST_VAR, JOINER_VAR, t)
    assert game.traded_at is not None and abs(game.traded_at - (commit_at + 14.6)) < 0.05
    assert not game.queue_done

    # Back on its box, the host's cursor previews another Pokemon; the file keeps the one it traded.
    seq += 1
    game.on_message(za_join.GAME_RELIABLE,
                    reliable.build_reliable(seq, seq, theirs(4, 1), flagsA=reliable.FLAGSA_GBA), t)
    assert za.pokemon.read((tmp_path / "theirs.pa9").read_bytes())["species"] == 3
    while t < commit_at + 16.0 + za_host.PREVIEW_DELAY:
        t += 0.02
        game.pump(HOST_VAR, JOINER_VAR, t)
    assert offers()[-1] == second[:-1] + bytes([za_host.OFFER_PREVIEW])

    seq += 1
    game.on_message(za_join.GAME_RELIABLE,
                    reliable.build_reliable(seq, seq, theirs(4, 0), flagsA=reliable.FLAGSA_GBA), t)
    for _ in range(200):
        t += 0.02
        game.pump(HOST_VAR, JOINER_VAR, t)
    assert offers()[-1] == second[:-1] + bytes([za_host.OFFER_PICK])
    seq += 1
    game.on_message(za_join.GAME_RELIABLE,
                    reliable.build_reliable(seq, seq, bytes.fromhex("0104b90000"),
                                            flagsA=reliable.FLAGSA_GBA), t)
    for _ in range(800):
        t += 0.02
        game.pump(HOST_VAR, JOINER_VAR, t)
    assert game.trades == 2 and game.queue_done
    assert za.pokemon.read((tmp_path / "theirs-2.pa9").read_bytes())["species"] == 4
    # the app ticks its queue off by the line each completed trade prints
    counts = [n for line in capsys.readouterr().out.splitlines()
              if (n := received.trades_done(line)) is not None]
    assert counts == [1, 2]


def test_the_host_answers_a_leave_as_the_console_reads_it():
    """A retail joiner leaving sends type 3 every 0.5 s and gives up after four (`0x2557e54`); a
    host owes the 15-byte type 4 that `0x25474f8` takes: its own location at +5, big-endian."""
    host = za_host.HostSession(
        ssid=SSID, our_ip=HOST_IP, our_mac=HOST_MAC, guest_ip=JOINER_IP, code="00000000",
        identity=bytes(106), identity_tail=bytes(9), selection=bytes(1211), offer=None,
        host_var=HOST_VAR, clock=lambda: 0.0)
    joiner = ScriptedJoiner(host)
    t = joiner.run(0.1, 0.0)
    joiner.send(pia_connect.PROTO_NET, bytes.fromhex("0112000000000002"), dst=0, now=t)
    joiner.send(pia_connect.PROTO_SESSION, JOIN, dst=0, now=t)
    t = joiner.run(t + 0.5, t)
    # The retail leave's layout (type, random word, location, address type 0, IPv4, port).
    leave = bytes.fromhex("03b584a8be" "7f00030000020000" "5ad2" "00" "7f000003" "3039")
    joiner.send(pia_connect.PROTO_SESSION, leave, now=t)
    joiner.run(t + 0.1, t)
    answers = [m for _, p, m in joiner.heard if p == pia_connect.PROTO_SESSION and m[:1] == b"\x04"]
    assert len(answers) == 1 and len(answers[0]) == 0xF
    assert int.from_bytes(answers[0][5:13], "big") == int.from_bytes(
        pia_connect.ldn_constant_id(bytes.fromhex("02007f000003")), "big")
    assert int.from_bytes(answers[0][13:15], "big") == JOINER_VAR
    assert host.leave_requests == 1


# An emulated pair's departure: the host's type 9 naming the joiner, the joiner's type 10, then the
# host's Net 0x11 sequence 3 and the joiner's 0x12. The host's network closed 0.25 s after its type 9.
PAIR_START_MIGRATION = bytes.fromhex("097f00020000020000905c007f00000230397f00030000020000b7010001")
PAIR_MIGRATION_ACK = bytes.fromhex("0a7f00030000020000b7017f00020000020000905c")
PAIR_NET_STATUS_3 = bytes.fromhex(
    "0111005800000003905c7f000200000200000000000091a31a6d02000401000000007f00000200000000000000"
    "00000000003039000100007f000003000000000000000000000000303900ff000000000000000000000000000000"
    "000000000000ff0000000000000000000000000000000000000000")


def run_joiner(monkeypatch, argv, script, answer):
    """`bin/za_join.py` seated with a scripted host from the emulated pair (0x905c, our id 0xb701):
    `script` is (seconds, proto, payload) the host sends; `answer(proto, payload)` -> what it sends
    back to each message of ours. -> (seconds, header, proto, payload) for everything we sent, and
    the seconds the seat lasted."""
    import trio

    import za_join
    our_mac, our_var, pair_host = bytes.fromhex("02007f000003"), 0xB701, 0x905C
    host_ip, our_ip = "127.0.0.2", "127.0.0.3"
    pia = crypto.PiaCrypto(SSID, za.GAME_KEY)
    network = type("N", (), {"our_ip": host_ip})
    clock = [100.0]
    start = clock[0]
    script, heard, inbox = list(script), [], []

    class Clock:
        @staticmethod
        def monotonic():
            return clock[0]
        time = monotonic

    class Socket:
        def sendto(self, data, _):
            decoded, why = host_pia.decode_datagram(data, our_ip, pia)
            assert decoded is not None, why
            header, messages = decoded
            for m in messages:
                heard.append((clock[0] - start, header, m.proto, m.payload))
                inbox.extend(answer(m.proto, m.payload))

        def recvfrom(self, _):
            due = [x for x in script if start + x[0] <= clock[0]]
            for x in due:
                script.remove(x)
                inbox.append((x[1], x[2], our_var))
            if inbox:
                proto, payload, dst = inbox.pop(0)
                data = host_pia.build_messages(network, pia, [(proto, payload)], dst_var=dst,
                                               src_var=0 if dst == 0 else pair_host,
                                               footer_var=None if dst == 0 else our_var)
                return data, (host_ip, za.PIA_PORT)
            clock[0] += 0.01
            raise BlockingIOError

        def close(self):
            pass

    async def sleep(_):
        await trio.lowlevel.checkpoint()

    monkeypatch.setattr(za_join, "time", Clock)
    monkeypatch.setattr(za_join, "make_socket", lambda *a: Socket())
    monkeypatch.setattr(trio, "sleep", sleep)
    args = za_join.build_parser().parse_args(["--unicast", "--our-var", "0xb701"] + argv)
    trio.run(za_join.run_session, args, za.session_keys(SSID), host_ip,
             bytes.fromhex("02007f000002"), our_ip, our_mac, lambda **row: None)
    return heard, clock[0] - start


def test_the_joiner_hands_a_leaving_console_its_acknowledgement(monkeypatch):
    """A host leaving names us its next host: the pair's own type 10 and 0x12 go back, framed as the
    reference joiner framed them, and the seat ends once the host is gone. Unanswered, a retail host
    repeats the type 9 for 5 s (`0x255a91c`) and leaves 11 s after its first."""
    # A retail host then repeats Net 0x40 every 0.3 s for 4 s (za67); the seat ends on the first.
    script = [(1.0, pia_connect.PROTO_SESSION, PAIR_START_MIGRATION)]
    script += [(1.1 + 0.3 * i, pia_connect.PROTO_NET, bytes.fromhex("01400000")) for i in range(14)]

    def answer(proto, payload):
        if proto == pia_connect.PROTO_SESSION and payload[:1] == b"\x0a":
            return [(pia_connect.PROTO_NET, PAIR_NET_STATUS_3, 0)]
        return []
    heard, lasted = run_joiner(monkeypatch, ["--hold", "30"], script, answer)
    acks = [h for _, h, p, m in heard if p == pia_connect.PROTO_SESSION and m == PAIR_MIGRATION_ACK]
    nets = [h for _, h, p, m in heard
            if p == pia_connect.PROTO_NET and m == bytes.fromhex("0112000000000003")]
    assert len(acks) == 1 and len(nets) == 1
    for h in acks + nets:
        assert (h.dst, h.src, h.pktid, h.footer, h.flags & 0x0F) == (0, 0xB701, 0, 0, 0x02)
    assert lasted < 1.3                 # on the first 0x40, not on the host's silence or --hold
    assert not [m for _, _, p, m in heard if p == pia_connect.PROTO_SESSION and m[:1] == b"\x03"]


def test_the_leave_request_is_a_retail_consoles():
    assert za.build_leave_request(bytes.fromhex("eb9b2220f1480000"), 0x2583, "169.254.97.2",
                                  bytes.fromhex("b584a8be")) == bytes.fromhex(
        "03b584a8beeb9b2220f1480000258300a9fe61023039")


@pytest.mark.parametrize("answered", [True, False])
def test_the_joiner_leaves_as_a_console_leaves(monkeypatch, answered):
    """At the end of its hold the joiner sends type 3 to the host, every 0.5 s and at most four
    times (`0x2558098`), and goes once a type 4 naming it comes back (`0x25474f8`)."""
    script = [(0.3 * i, pia_connect.PROTO_RTT, bytes(21)) for i in range(1, 12)]

    def answer(proto, payload):
        if answered and proto == pia_connect.PROTO_SESSION and payload[:1] == b"\x03":
            return [(pia_connect.PROTO_SESSION, b"\x04" + bytes(4) + payload[5:15], 0xB701)]
        return []
    heard, lasted = run_joiner(monkeypatch, ["--hold", "2"], script, answer)
    leaves = [(t, h, m) for t, h, p, m in heard if p == pia_connect.PROTO_SESSION and m[:1] == b"\x03"]
    assert len(leaves) == (1 if answered else 4)
    t, h, m = leaves[0]
    assert (h.dst, h.src) == (0x905C, 0xB701) and h.footer == 2
    assert m[5:] == bytes.fromhex("7f00030000020000b701007f0000033039") and len(m) == 22
    assert [round(b[0] - t, 1) for b in leaves] == [0.0, 0.5, 1.0, 1.5][:len(leaves)]
    assert lasted < (2.2 if answered else 4.2)

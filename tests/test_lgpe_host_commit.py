"""The Let's Go host's commit and result stages against a scripted console (docs/lgpe_session.md).
A console left on its confirmation screen refuses trades for about half an hour."""
from pathlib import Path
import importlib.util
import os
import struct

import pytest

from pokeldn.ldn import clone, reliable3
from pokeldn.lgpe import pb7, reference
from pokeldn.lgpe.trade import _send_step

ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("lgpe_host", os.path.join(ROOT, "bin", "lgpe_host.py"))
lgpe_host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lgpe_host)

JOINER = 1
ONES = b"\x01\0\0\0" * 3


class Clock:
    """time.monotonic under test control."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Radio:
    """The HostTransport a Session drives, with nothing behind it."""
    our_ip = "169.254.38.1"
    our_mac = bytes.fromhex("58d8122149a2")
    participants = []

    def recv(self):
        return []

    def send(self, pkt, ip):
        pass


def words(data):
    return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]


@pytest.fixture
def stage(tmp_path, monkeypatch):
    """A host session at the trade screen: identities and offers exchanged, the offered clone 3
    walked to its trailing word 2, our step at 10, the console's at 11."""
    clk = Clock()
    monkeypatch.setattr(lgpe_host.time, "monotonic", clk)
    plain = bytearray(pb7.BOX_SIZE)
    struct.pack_into("<I", plain, 0, 0x5a1c33e7)
    struct.pack_into("<H", plain, 8, 16)
    offer = tmp_path / "offer.bin"
    offer.write_bytes(pb7.encrypt(bytes(plain)))
    args = lgpe_host.build_parser().parse_args(
        ["--first", "echo", "--offer", str(offer), "--our-trainer", "41234:12345"])
    adv = lgpe_host.Advertisement(0x2952124b, 0xe28ef1be)
    s = lgpe_host.Session(Radio(), adv, args, lambda **kw: None)
    s.peer_ip, s.peer_mac = "169.254.38.2", bytes.fromhex("48f1eb209b22")
    s.joined = True
    s.new_clone()
    sent = []
    monkeypatch.setattr(s, "send", lambda payload, protocol, **kw: sent.append((protocol, payload, kw)))
    s.trade["step"] = 10
    s.clone.state_word = 10
    s.window.expected = reliable3.FIRST_SEQUENCE + 11
    for cid in (1, 2, 3):
        s.clone.held.add(cid)
    s.clone.flags[3] = b"\x01\0\0\0" + b"\x02\0\0\0" * 2
    s.clone.tail[3] = 2
    lgpe_host.TRADE_IN_PROGRESS["offer"] = True
    lgpe_host.TRADE_IN_PROGRESS["commit"] = False

    def console_publishes(cid, data, step=11):
        rec = clone.build_state_record(cid, JOINER, 3, s.clone.ms(clk()),
                                       data + struct.pack("<I", step) + bytes(4) if len(data) == 12
                                       else data)
        s.handle(clone.PROTOCOL, clone.build_data_message(
            clone.STATE_DATA, 2, JOINER, cid, s.clone.frame(clk()), rec, flags=3))

    def console_says(kind, body, step=12):
        seq = s.window.expected
        s.handle(reliable3.PROTOCOL, reliable3.build(pb7.build_message(kind, body, step=step),
                                                     seq, reliable3.FIRST_SEQUENCE))

    def published(cid, ctype=2):
        out = []
        for protocol, payload, _ in sent:
            if protocol != clone.PROTOCOL:
                continue
            d = clone.parse_data_message(payload)
            if (d and d["type"] == clone.STATE_DATA and d["clone_id"] == cid
                    and d["ctype"] == ctype and d["record"]):
                out.append(words(d["record"]["data"]))
        return out

    def game_messages():
        out = []
        for protocol, payload, _ in sent:
            if protocol != reliable3.PROTOCOL:
                continue
            r = reliable3.parse(payload)
            if r and r["size"]:
                m = pb7.parse_message(r["payload"])
                out.append((m["kind"], m["step"], m["body"][:4]))
        return out

    def run(seconds, ack=True):
        """Advance the clock; pending game messages are acknowledged within 30 ms, as in every capture."""
        end = clk.t + seconds
        while clk.t < end:
            clk.t += 0.005
            if ack and s.window.pending and clk.t - s.window.pending[0][2] >= 0.03:
                s.handle(reliable3.PROTOCOL, reliable3.build_ack(s.window.sequence))
            s.tick()

    return {"s": s, "clk": clk, "sent": sent, "console_publishes": console_publishes,
            "console_says": console_says, "published": published, "game": game_messages,
            "run": run}


def test_the_commit_clone_walks_to_the_trailing_word_1_and_no_further(stage):
    """The host answers 1 1 1 with trailing word 1 after 30 ms, then waits; walking on to 01 02 02
    strands the console."""
    stage["console_publishes"](4, bytes(12))
    stage["console_publishes"](4, ONES)
    stage["sent"].clear()
    stage["run"](0.02)
    assert stage["published"](4) == [], "the trailing word came before 30 ms"
    stage["run"](0.02)
    assert stage["published"](4)[-1] == [1, 1, 1, 10, 1]
    assert stage["published"](4, ctype=4)[-1] == [1, 0, 0, 0, 0, 0, 10, 1]
    stage["run"](5.0)
    assert stage["published"](4)[-1] == [1, 1, 1, 10, 1]
    assert stage["game"]() == []
    assert stage["s"].commit_clone == 4


def test_the_consoles_zero_first_word_brings_the_first_commit_in_one_frame(stage):
    """The console's 0 1 1 brings, in one frame, 0 1 1 on the commit clone, 0 2 2 on the offered
    one, and kind 3 carrying 1."""
    stage["console_publishes"](4, bytes(12))
    stage["console_publishes"](4, ONES)
    stage["run"](0.05)
    stage["sent"].clear()
    stage["console_publishes"](4, b"\0\0\0\0" + b"\x01\0\0\0" * 2 + struct.pack("<I", 11) + b"\x01\0\0\0")
    assert stage["published"](4)[-1] == [0, 1, 1, 11, 1]
    assert stage["published"](3)[-1] == [0, 2, 2, 11, 2]
    assert stage["game"]() == [(pb7.COMMIT_MESSAGE, 11, b"\x01\0\0\0")]
    stage["console_publishes"](4, b"\0\0\0\0" + b"\x01\0\0\0" * 2 + struct.pack("<I", 11) + b"\x01\0\0\0")
    stage["run"](1.0)
    assert stage["game"]() == [(pb7.COMMIT_MESSAGE, 11, b"\x01\0\0\0")]


def test_the_consoles_own_first_publish_of_the_commit_clone_is_not_an_answer(stage):
    """The console's first copy (0 0 0, trailing 0) is not an answer."""
    stage["console_publishes"](4, bytes(12))
    stage["run"](1.0)
    assert stage["game"]() == []
    assert not stage["s"].committed


def test_the_second_commit_follows_the_consoles_own_by_four_frames(stage):
    """The second commit follows 65 ms after the first; the references sent it 63 to 66 ms after,
    behind the peer's."""
    stage["console_publishes"](4, bytes(12))
    stage["console_publishes"](4, ONES)
    stage["run"](0.05)
    stage["console_publishes"](4, b"\0\0\0\0" + b"\x01\0\0\0" * 2 + struct.pack("<I", 11) + b"\x01\0\0\0")
    stage["run"](0.003)
    stage["console_says"](pb7.COMMIT_MESSAGE, b"\x01\0\0\0")
    stage["run"](0.04)
    assert stage["game"]() == [(pb7.COMMIT_MESSAGE, 11, b"\x01\0\0\0")]
    stage["run"](0.04)
    assert stage["game"]() == [(pb7.COMMIT_MESSAGE, 11, b"\x01\0\0\0"),
                               (pb7.COMMIT_MESSAGE, 12, b"\x02\0\0\0")]
    assert stage["published"](4)[-1] == [0, 1, 1, 12, 1]
    assert stage["published"](3)[-1] == [0, 2, 2, 12, 2]
    stage["run"](5.0)
    assert len(stage["game"]()) == 2, "a commit was sent twice"


def test_the_second_commit_waits_for_the_consoles_kind_3(stage):
    """Without the console's own kind 3 the second commit is not sent: on both references it
    followed the peer's."""
    stage["console_publishes"](4, bytes(12))
    stage["console_publishes"](4, ONES)
    stage["run"](0.05)
    stage["console_publishes"](4, b"\0\0\0\0" + b"\x01\0\0\0" * 2 + struct.pack("<I", 11) + b"\x01\0\0\0")
    stage["run"](2.0)
    assert stage["game"]() == [(pb7.COMMIT_MESSAGE, 11, b"\x01\0\0\0")]
    stage["console_says"](pb7.COMMIT_MESSAGE, b"\x01\0\0\0")
    stage["run"](0.1)
    assert stage["game"]()[-1] == (pb7.COMMIT_MESSAGE, 12, b"\x02\0\0\0")


def commit(stage):
    stage["console_publishes"](4, bytes(12))
    stage["console_publishes"](4, ONES)
    stage["run"](0.05)
    stage["console_publishes"](4, b"\0\0\0\0" + b"\x01\0\0\0" * 2 + struct.pack("<I", 11) + b"\x01\0\0\0")
    stage["console_says"](pb7.COMMIT_MESSAGE, b"\x01\0\0\0")
    stage["run"](0.1)
    assert stage["game"]()[-1] == (pb7.COMMIT_MESSAGE, 12, b"\x02\0\0\0")


def test_the_result_goes_once_after_the_animation_with_two_clones_before_it(stage):
    """27 s after the second commit: two result clones announced half a second before, then the
    kind 4 under the next step, once. The console's own kind 4 arriving later changes nothing."""
    commit(stage)
    stage["run"](26.0)
    assert stage["game"]()[-1][0] == pb7.COMMIT_MESSAGE
    assert stage["published"](5, ctype=4) == []
    stage["run"](0.6)
    assert stage["published"](5, ctype=4) == [[0] * 8]
    assert stage["published"](6, ctype=4) == [[0] * 8]
    assert stage["game"]()[-1][0] == pb7.COMMIT_MESSAGE
    stage["run"](0.5)
    kind, step, _ = stage["game"]()[-1]
    assert (kind, step) == (pb7.RESULT_MESSAGE, 13)
    assert stage["published"](4)[-1] == [0, 1, 1, 13, 1]
    stage["console_says"](pb7.RESULT_MESSAGE, bytes(pb7.BOX_SIZE))
    stage["run"](5.0)
    assert [g for g in stage["game"]() if g[0] == pb7.RESULT_MESSAGE] == [(pb7.RESULT_MESSAGE, 13, stage["game"]()[-1][2])]
    assert stage["s"].trade.get("done")


def test_the_consoles_result_arriving_first_brings_ours_at_once(stage):
    """A console whose animation ends first sends its kind 4; ours answers it rather than waiting
    the timer out, and the timer then sends nothing."""
    commit(stage)
    stage["run"](20.0)
    stage["console_says"](pb7.RESULT_MESSAGE, bytes(pb7.BOX_SIZE))
    assert stage["game"]()[-1][:2] == (pb7.RESULT_MESSAGE, 13)
    stage["run"](15.0)
    assert len([g for g in stage["game"]() if g[0] == pb7.RESULT_MESSAGE]) == 1


def test_the_result_carries_our_own_structure(stage, tmp_path):
    """A reference host's kind 4 is its own first party slot, unchanged: the structure it offered
    at step 2. Ours is the --offer structure."""
    commit(stage)
    stage["run"](28.0)
    kind, _, _ = stage["game"]()[-1]
    body = [r for p, payload, _ in stage["sent"] if p == reliable3.PROTOCOL
            for r in [reliable3.parse(payload)] if r["size"]][-1]["payload"][16:]
    assert body == Path(stage['s'].args.offer).read_bytes()
    assert pb7.valid(body)


@pytest.mark.parametrize("later", [2, 5])
def test_each_later_trade_offers_the_next_record_on_its_own_kinds_and_clones(stage, tmp_path, later):
    """Round r answers offers on kind 2 + 2r, commits on 3 + 2r on clone 4 + 3r, and ends on kind
    4 + 2r; it offers the r-th --next-offer and writes what it received to a numbered file."""
    def record(ec, species):
        plain = bytearray(pb7.BOX_SIZE)
        struct.pack_into("<I", plain, 0, ec)
        struct.pack_into("<H", plain, 8, species)
        return pb7.encrypt(bytes(plain))

    s = stage["s"]
    offers = []
    for n in range(1, later + 1):
        path = tmp_path / f"next{n}.bin"
        path.write_bytes(record(0x1000 + n, 25 + n))
        offers.append(str(path))
    s.args.next_offer = offers
    s.args.received = s.received = str(tmp_path / "got.pb7")
    first = Path(s.args.offer).read_bytes()
    commit(stage)
    stage["run"](27.1)
    stage["console_says"](pb7.RESULT_MESSAGE, first, step=13)
    step = 14
    for r, path in enumerate(offers, start=1):
        assert s.round == r and s.trade["done"] and s.commit_clone is None
        theirs = record(0x2000 + r, 130 + r)
        stage["sent"].clear()
        stage["console_says"](2 + 2 * r, theirs, step=step)
        assert stage["game"]()[-1][0] == 2 + 2 * r
        assert not s.trade["done"]
        sent = [reliable3.parse(p)["payload"][16:] for proto, p, _ in stage["sent"]
                if proto == reliable3.PROTOCOL and reliable3.parse(p)["size"]]
        assert sent[-1] == Path(path).read_bytes()
        assert Path(tmp_path / f"got-{r + 1}.pb7").read_bytes()[:pb7.BOX_SIZE] == theirs
        stage["console_publishes"](3 + 3 * r, ONES)
        stage["run"](0.04)
        assert s.commit_clone is None
        stage["console_publishes"](4 + 3 * r, ONES)
        stage["run"](0.04)
        assert s.commit_clone == 4 + 3 * r
        stage["console_publishes"](4 + 3 * r, b"\0\0\0\0" + b"\x01\0\0\0" * 2 +
                                   struct.pack("<I", step + 1) + b"\x01\0\0\0")
        assert stage["game"]()[-1][0] == 3 + 2 * r
        stage["console_says"](3 + 2 * r, b"\x01\0\0\0", step=step + 1)
        stage["run"](0.1)
        assert stage["game"]()[-1][::2] == (3 + 2 * r, b"\x02\0\0\0")
        stage["run"](27.1)
        assert stage["game"]()[-1][0] == 4 + 2 * r
        stage["console_says"](4 + 2 * r, theirs, step=step + 2)
        assert s.trade["done"]
        step += 3
    assert s.round == later


def test_the_offered_clone_walks_on_to_01_02_02_and_the_trailing_word_2(stage):
    """The offered clone walks 1 1 1 (trailing 1), 1 2 2, then trailing 2, one --drive-delay apart."""
    s = stage["s"]
    del s.clone.flags[3], s.clone.tail[3]
    stage["console_publishes"](3, ONES)
    stage["sent"].clear()
    stage["run"](0.04)
    assert stage["published"](3)[-1] == [1, 1, 1, 10, 1]
    assert stage["published"](3, ctype=4)[-1] == [1, 0, 0, 0, 0, 0, 10, 1]
    stage["run"](s.args.drive_delay)
    assert stage["published"](3)[-1] == [1, 2, 2, 10, 1]
    assert stage["published"](3, ctype=4)[-1] == [2, 0, 0, 0, 0, 0, 10, 1]
    stage["run"](s.args.drive_delay)
    assert stage["published"](3)[-1] == [1, 2, 2, 10, 2]
    assert stage["published"](3, ctype=4)[-1] == [2, 0, 0, 0, 0, 0, 10, 2]
    assert s.commit_clone is None
    assert stage["game"]() == []


def test_an_unacknowledged_game_message_goes_again_after_half_a_second(stage):
    """An unacknowledged game message is resent byte for byte every half second."""
    s = stage["s"]
    commit(stage)
    step = _send_step(s.trade, s.send, pb7.COMMIT_MESSAGE, b"\x02\0\0\0")
    first = [payload for p, payload, _ in stage["sent"] if p == reliable3.PROTOCOL][-1:]
    stage["sent"].clear()
    stage["run"](0.45, ack=False)
    assert [payload for p, payload, _ in stage["sent"] if p == reliable3.PROTOCOL] == []
    stage["run"](0.1, ack=False)
    again = [payload for p, payload, _ in stage["sent"] if p == reliable3.PROTOCOL]
    assert again == first
    s.handle(reliable3.PROTOCOL, reliable3.build_ack(s.window.sequence))
    stage["sent"].clear()
    stage["run"](2.0, ack=False)
    assert [payload for p, payload, _ in stage["sent"] if p == reliable3.PROTOCOL] == []


def test_the_window_holds_nothing_without_a_clock():
    w = reliable3.Window()
    w.send(b"x")
    assert w.pending == [] and w.due(10.0) == []


def test_the_consoles_release_of_a_clone_is_acknowledged_on_the_same_clone(stage):
    """The console's 0x83 releases on clone type 4 are acked with 0x84 on that clone; type 2 is
    acked on type 1."""
    s = stage["s"]
    commit(stage)
    stage["sent"].clear()
    for cid in (3, 2, 4):
        end = clone.build_command(clone.COMMAND_END, 4, 0xFD, cid, 0x478, 1)
        s.handle(clone.PROTOCOL, end)
        acks = [clone.parse_command(payload) for p, payload, _ in stage["sent"]
                if p == clone.PROTOCOL and payload[1] == clone.COMMAND_END_ACK]
        assert (acks[-1]["ctype"], acks[-1]["station"], acks[-1]["clone_id"]) == (4, 0xFD, cid)
        assert cid not in s.clone.held
    stage["sent"].clear()
    stage["run"](1.0)
    assert stage["published"](3) == [] and stage["published"](4) == []
    assert 1 in s.clone.held
    s.handle(clone.PROTOCOL, clone.build_command(clone.COMMAND_END, 2, JOINER, 1, 0x480, 1))
    ack = [clone.parse_command(payload) for p, payload, _ in stage["sent"]
           if p == clone.PROTOCOL and payload[1] == clone.COMMAND_END_ACK][-1]
    assert (ack["ctype"], ack["station"], ack["clone_id"]) == (1, 0xFD, 1)


def test_the_consoles_state_word_4_is_its_player_leaving_and_is_acknowledged(stage):
    """State word 4 is the peer's player leaving; answered after 30 ms with zeros and the trailing
    word advanced."""
    stage["sent"].clear()
    stage["console_publishes"](3, b"\x04\0\0\0" + b"\x03\0\0\0" + b"\x02\0\0\0"
                               + struct.pack("<I", 14) + b"\x02\0\0\0")
    stage["run"](0.02)
    assert stage["published"](3)[-1] == [1, 2, 2, 10, 2]
    stage["run"](0.02)
    assert stage["published"](3)[-1] == [0, 0, 0, 10, 3]
    assert stage["published"](3, ctype=4)[-1] == [3, 0, 0, 0, 0, 0, 10, 3]
    stage["run"](1.0)
    assert stage["published"](3)[-1] == [0, 0, 0, 10, 3]


def test_a_second_state_word_4_under_a_fresh_counter_is_answered_again(stage):
    """Each state word 4 under a fresh counter is answered; a pending walk is dropped."""
    s = stage["s"]
    del s.clone.flags[3], s.clone.tail[3]
    stage["console_publishes"](3, ONES)
    stage["run"](0.04)
    assert stage["published"](3)[-1] == [1, 1, 1, 10, 1]
    stage["console_publishes"](3, b"\x04\0\0\0" + b"\0\0\0\0" + b"\x02\0\0\0"
                               + struct.pack("<I", 12) + b"\x01\0\0\0")
    stage["run"](0.04)
    assert stage["published"](3)[-1] == [0, 0, 0, 10, 2]
    assert stage["published"](3, ctype=4)[-1] == [0, 0, 0, 0, 0, 0, 10, 2]
    stage["run"](3.0)
    assert stage["published"](3)[-1] == [0, 0, 0, 10, 2], "the walk went on after the cancel"
    stage["console_publishes"](3, b"\x04\0\0\0" + b"\x03\0\0\0" + b"\x03\0\0\0"
                               + struct.pack("<I", 12) + b"\x02\0\0\0")
    stage["run"](0.04)
    assert stage["published"](3)[-1] == [0, 0, 0, 10, 3]
    assert stage["published"](3, ctype=4)[-1] == [3, 0, 0, 0, 0, 0, 10, 3]


def test_the_consoles_leave_request_is_acknowledged_and_answered(stage):
    """A leave request on the reliable port is acked there and answered on the unreliable port with
    the host's index, twice, as a console host answers it; mesh and session shrink to one node."""
    from pokeldn.ldn import mesh_protocol as mp
    s = stage["s"]
    stage["sent"].clear()
    leave = reliable3.build(b"\x04\x01", reliable3.FIRST_SEQUENCE, reliable3.FIRST_SEQUENCE)
    s.handle(mp.PROTOCOL, leave)
    mesh = [(payload, kw) for p, payload, kw in stage["sent"] if p == mp.PROTOCOL]
    acks = [(payload, kw) for payload, kw in mesh if payload[0] == 0]
    assert len(acks) == 1 and acks[0][1].get("port") == 1
    assert reliable3.parse(acks[0][0])["expected"] == reliable3.FIRST_SEQUENCE + 1
    responses = [(payload, kw) for payload, kw in mesh if payload[0] == mp.LEAVE_RESPONSE]
    assert [r[0] for r in responses] == [b"\x08\x00"] * 2
    assert all(r[1].get("port", 0) == 0 for r in responses)
    assert not s.joined and s.session_nodes() == ((s.host.our_ip, lgpe_host.PIA_PORT, 0),)
    updates = [payload for payload, kw in mesh if payload[0] == mp.UPDATE_MESH]
    assert updates and updates[-1][1] == 1, "the mesh update still lists the console"
    s.handle(mp.PROTOCOL, leave)
    assert len([1 for p, payload, kw in stage["sent"] if p == mp.PROTOCOL
                and payload[0] == mp.LEAVE_RESPONSE]) == 2


def test_a_leaving_console_takes_the_hosts_leave_response(stage):
    """The leave request a leaving console sends, through the host, back into the console's own
    check (0x591bf4: [1] must be the host's index, else it waits 5000 ms and deauthenticates)."""
    from pokeldn.ldn import mesh_protocol as mp
    from pokeldn.lgpe.leave import Leaver
    s = stage["s"]
    part = clone.Participant(100.0, dest=1, own=2, station=JOINER)
    lv = Leaver(part, 3, 11, 2, 2, station=JOINER, host_bit=1)
    lv.leave_sent = lv.leave_next = 100.0
    request = [p for p, proto, port in lv.poll(100.0) if proto == mp.PROTOCOL and port == 1]
    assert len(request) == 1
    stage["sent"].clear()
    s.handle(mp.PROTOCOL, request[0])
    for p, payload, kw in stage["sent"]:
        lv.receive(p, payload, 100.01)
    assert lv.leave_answered


def test_the_consoles_disconnection_request_is_answered(stage):
    """Unanswered, the console repeats it every half second, eight times, and deauthenticates."""
    from pokeldn.ldn import station9
    from pokeldn.ldn.station_protocol import DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE
    s = stage["s"]
    stage["sent"].clear()
    s.handle(station9.PROTOCOL, bytes([DISCONNECTION_REQUEST]))
    answers = [payload for p, payload, kw in stage["sent"] if p == station9.PROTOCOL]
    assert answers == [bytes([DISCONNECTION_RESPONSE])]


def test_the_host_releases_its_own_copy_after_the_consoles(stage):
    """30 ms after the console's 0x83 the host releases its own copies, as the emulated pair did."""
    s = stage["s"]
    stage["sent"].clear()
    s.handle(clone.PROTOCOL, clone.build_command(clone.COMMAND_END, 4, 0xFD, 3, 0x478, 1))
    s.handle(clone.PROTOCOL, clone.build_command(clone.COMMAND_END, 3, 0xFD, 0, 0x479, 1))
    stage["run"](0.02)
    ends = [clone.parse_command(payload) for p, payload, _ in stage["sent"]
            if p == clone.PROTOCOL and payload[1] == clone.COMMAND_END]
    assert ends == []
    stage["run"](0.02)
    ends = [(c["ctype"], c["station"], c["clone_id"], c["dest"]) for c in
            (clone.parse_command(payload) for p, payload, _ in stage["sent"]
             if p == clone.PROTOCOL and payload[1] == clone.COMMAND_END)]
    assert ends == [(2, 0, 3, 3), (4, 0xFD, 3, 2), (3, 0xFD, 0, 2)]
    s.handle(clone.PROTOCOL, clone.build_command(clone.COMMAND_END, 4, 0xFD, 3, 0x47a, 1))
    stage["run"](0.1)
    assert len([1 for p, payload, _ in stage["sent"]
                if p == clone.PROTOCOL and payload[1] == clone.COMMAND_END]) == 3


def test_a_lost_request_for_the_commit_clone_is_drawn_again(stage):
    """A retail host run stalled on the confirmation screen: the console announced the commit clone,
    acked our take-over, and its 0x82 never reached us, so the type 4 copy that draws its 1 1 1 never
    went out. The peer-only re-announcement repeats until the 0x82 arrives."""
    s, sent = stage["s"], stage["sent"]

    def console(kind, ctype, station, dest, payload=b""):
        s.handle(clone.PROTOCOL, clone.build_command(kind, ctype, station, 4, 1, dest, payload))

    def announces():
        return [1 for protocol, payload, _ in sent if protocol == clone.PROTOCOL
                and (c := clone.parse_command(payload)) and c["type"] == clone.COMMAND_ANNOUNCE]

    console(clone.COMMAND_ANNOUNCE, 2, JOINER, 0x3)
    for ctype in (4, 1):
        console(clone.CLOCK_AND_COUNT, ctype, 0xFD, 0x1, b"\0\0\x10\0" + b"\x01\x28\x08\xab")
    stage["run"](0.06)
    console(clone.CLOCK_AND_COUNT_2, 2, JOINER, 0x1, b"\0\0\x10\0\0\0\0\0")
    sent.clear()
    stage["run"](0.05)
    assert len(announces()) == 1
    stage["run"](0.12)                       # the 0x82 is lost
    assert len(announces()) == 2
    console(clone.COMMAND_REQUEST, 1, 0xFD, 0x1)
    assert stage["published"](4, ctype=4)[-1] == [0] * 8
    sent.clear()
    stage["run"](1.0)
    assert announces() == []


def test_an_unanswered_clone_0_pair_is_repeated_until_the_console_answers(stage):
    """A retail host stalled on "vous allez bientôt être connecté" when its one clone 0 pair went
    unanswered; a retail console host repeats its own pair about 110 ms later."""
    s, sent, clk = stage["s"], stage["sent"], stage["clk"]
    s.clone_0_announced, s.publish_clone_0_at = False, None
    s.announce_clone_0_at = clk.t

    def pairs():
        return sum(1 for protocol, payload, _ in sent if protocol == clone.PROTOCOL
                   and (c := clone.parse_command(payload)) and c["type"] == clone.CLOCK_AND_PARTICIPANT
                   and (c["ctype"], c["clone_id"]) == (3, 0))

    stage["run"](0.05)
    assert pairs() == 1
    stage["run"](0.12)
    assert pairs() == 2
    s.handle(clone.PROTOCOL, clone.build_command(clone.CLOCK_AND_COUNT_2, 3, 0xFD, 0, 9, 0x1,
                                                 b"\0\0\x10\0\x01\0\0\0"))
    sent.clear()
    stage["run"](1.0)
    assert pairs() == 0


def test_the_echoed_identity_names_our_trainer(monkeypatch):
    """The host answers the console's kind 1 with that message under our trainer's name and ids,
    the rest of it the console's own."""
    monkeypatch.setattr(lgpe_host.time, "monotonic", Clock())
    args = lgpe_host.build_parser().parse_args(
        ["--first", "echo", "--trainer-name", "ASH", "--our-trainer", "41234:12345"])
    s = lgpe_host.Session(Radio(), lgpe_host.Advertisement(0x2952124b, 0xe28ef1be), args, lambda **kw: None)
    s.peer_ip, s.peer_mac, s.joined = "169.254.38.2", bytes.fromhex("48f1eb209b22"), True
    s.new_clone()
    sent = []
    monkeypatch.setattr(s, "send", lambda payload, protocol, **kw: sent.append((protocol, payload)))
    console = pb7.parse_message(Path(reference.IDENTITY).read_bytes())["body"]
    console = pb7.set_trainer_id(pb7.set_trainer_name(console, "CONSOLE"), 1, 2)
    s.handle(reliable3.PROTOCOL, reliable3.build(pb7.build_message(pb7.FIRST_MESSAGE, console),
                                                 reliable3.FIRST_SEQUENCE, reliable3.FIRST_SEQUENCE))
    ours = [pb7.parse_message(r["payload"]) for p, payload in sent if p == reliable3.PROTOCOL
            for r in [reliable3.parse(payload)] if r and r["size"]]
    assert [m["kind"] for m in ours] == [pb7.FIRST_MESSAGE]
    body = ours[0]["body"]
    assert pb7.trainer_name(body) == "ASH" and pb7.trainer_id(body) == (41234, 12345)
    assert pb7.set_trainer_id(pb7.set_trainer_name(body, "CONSOLE"), 1, 2) == console

"""The commit and result stages a Let's Go host runs, pinned to the walk two reference hosts
took (docs/lgpe_session.md, "The two clone records a trade walks"): a retail console hosting and
an emulated one. The whole stage runs against a scripted console with no radio.

A host that gets this stage wrong leaves the console on its confirmation screen, and a retail save
answers that with about half an hour of refused trades. Everything here runs before a console does."""
import importlib.util
import os
import struct

import pytest

from pokeldn.ldn import clone, reliable3
from pokeldn.lgpe import pb7
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

    def console_says(kind, body):
        seq = s.window.expected
        s.handle(reliable3.PROTOCOL, reliable3.build(pb7.build_message(kind, body, step=12),
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
        """Let the clock run. The console acknowledges every game message within 30 ms in every
        capture, so by default the pending ones are acknowledged as the clock passes."""
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
    """The console announces the commit clone and publishes 1 1 1 on it. The host answers with
    the trailing word 1, 30 ms later, its type 4 copy carrying 1 in its first word; then nothing
    until the console answers. A host that walks it on to 01 02 02 leaves the console on its
    confirmation screen."""
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
    """The console answers the trailing word 1 with 0 1 1. In one frame the host publishes 0 1 1
    on the commit clone and 0 2 2 on the offered one, both under its next step, and sends its
    kind 3 carrying 1 under that step."""
    stage["console_publishes"](4, bytes(12))
    stage["console_publishes"](4, ONES)
    stage["run"](0.05)
    stage["sent"].clear()
    stage["console_publishes"](4, b"\0\0\0\0" + b"\x01\0\0\0" * 2 + struct.pack("<I", 11) + b"\x01\0\0\0")
    assert stage["published"](4)[-1] == [0, 1, 1, 11, 1]
    assert stage["published"](3)[-1] == [0, 2, 2, 11, 2]
    assert stage["game"]() == [(pb7.COMMIT_MESSAGE, 11, b"\x01\0\0\0")]
    # the same answer again is a retransmit
    stage["console_publishes"](4, b"\0\0\0\0" + b"\x01\0\0\0" * 2 + struct.pack("<I", 11) + b"\x01\0\0\0")
    stage["run"](1.0)
    assert stage["game"]() == [(pb7.COMMIT_MESSAGE, 11, b"\x01\0\0\0")]


def test_the_consoles_own_first_publish_of_the_commit_clone_is_not_an_answer(stage):
    """The console's first copy of the commit clone carries 0 0 0 with a trailing word of 0. It
    precedes the 1 1 1 and is no answer: the host sends no commit off it."""
    stage["console_publishes"](4, bytes(12))
    stage["run"](1.0)
    assert stage["game"]() == []
    assert not stage["s"].committed


def test_the_second_commit_follows_the_consoles_own_by_four_frames(stage):
    """The console's kind 3 carrying 1 answers the host's. The host echoes nothing and sends its
    second, carrying 2, 65 ms after its first: both reference hosts sent it 63 to 66 ms after the
    first and behind the peer's."""
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
    assert body == open(stage["s"].args.offer, "rb").read()
    assert pb7.valid(body)


def test_the_offered_clone_walks_on_to_01_02_02_and_the_trailing_word_2(stage):
    """The offered party clone is the one the host walks the whole way: 1 1 1 with the trailing
    word 1 after 30 ms, then 1 2 2 with it still 1, then the trailing word 2, one --drive-delay
    apart. The console's buttons come up on the last."""
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
    """The console acknowledges every game message with the next id it expects. One it never
    acknowledges is sent again, byte for byte, every half second until it does; one it does is
    not."""
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
    # the console's acknowledgement names the id after the last one, and both stop
    s.handle(reliable3.PROTOCOL, reliable3.build_ack(s.window.sequence))
    stage["sent"].clear()
    stage["run"](2.0, ack=False)
    assert [payload for p, payload, _ in stage["sent"] if p == reliable3.PROTOCOL] == []


def test_the_window_holds_nothing_without_a_clock():
    w = reliable3.Window()
    w.send(b"x")
    assert w.pending == [] and w.due(10.0) == []


def test_the_consoles_release_of_a_clone_is_acknowledged_on_the_same_clone(stage):
    """After the trade the console releases clones 4, 3 and 2 with a 0x83 on clone type 4,
    station 0xFD, every 100 ms until each is acknowledged with a 0x84 on that clone; unanswered,
    its player waits on "interruption de la connexion" until the session dies. The released clone
    is no longer republished. A release on clone type 2 is acknowledged on clone type 1."""
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
    """A record whose state word is 4 is the peer's player backing out. The host answers 30 ms
    later on that clone with zeros in the first three words, the trailing word one further on,
    and the peer's argument in the type 4 copy's first word, which is what an emulated host did
    before the peer released its clones."""
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
    """A retail console backing out sends argument 0 first and argument 3 as it leaves, under
    successive counters. Each is answered, with the trailing word one further on each time, and
    a walk still pending on the clone is dropped."""
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
    """The console leaves the mesh with a leave request on the mesh protocol's reliable port,
    under the 24-byte reliable header. The host acknowledges that header on the same port,
    answers with a leave response on the unreliable port, and its mesh and session go back to
    one node. Unanswered, the console repeats the request every 40 ms for five seconds."""
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
    assert len(responses) == 1 and responses[0][0] == b"\x08\x01"
    assert responses[0][1].get("port", 0) == 0
    assert not s.joined and s.session_nodes() == ((s.host.our_ip, lgpe_host.PIA_PORT, 0),)
    updates = [payload for payload, kw in mesh if payload[0] == mp.UPDATE_MESH]
    assert updates and updates[-1][1] == 1, "the mesh update still lists the console"
    # the same request again is a retransmit
    s.handle(mp.PROTOCOL, leave)
    assert len([1 for p, payload, kw in stage["sent"] if p == mp.PROTOCOL
                and payload[0] == mp.LEAVE_RESPONSE]) == 1


def test_the_consoles_disconnection_request_is_answered(stage):
    """One byte each way on the station protocol. Unanswered, the console repeats it every half
    second, eight times, and deauthenticates."""
    from pokeldn.ldn import station9
    from pokeldn.ldn.station_protocol import DISCONNECTION_REQUEST, DISCONNECTION_RESPONSE
    s = stage["s"]
    stage["sent"].clear()
    s.handle(station9.PROTOCOL, bytes([DISCONNECTION_REQUEST]))
    answers = [payload for p, payload, kw in stage["sent"] if p == station9.PROTOCOL]
    assert answers == [bytes([DISCONNECTION_RESPONSE])]

"""The structure Let's Go trades, pinned to a message a host sent over LDN."""
import os
import struct

import pytest

from pokeldn.lgpe import pb7

OFFER = os.path.join(os.path.dirname(__file__), "..", "scratchpad",
                     "ip18_pia.jsonl.payload2.bin")


@pytest.fixture
def message():
    """An offer a host sent over LDN. The captures live outside the repository, so the tests that
    need one skip rather than fail on a fresh checkout; the ones that do not need one still run."""
    if not os.path.exists(OFFER):
        pytest.skip("the captured offer is not here")
    with open(OFFER, "rb") as fh:
        return fh.read()


def test_a_trade_message_is_a_header_and_a_body_of_the_stated_length(message):
    m = pb7.parse_message(message)
    assert m["kind"] == pb7.OFFER_MESSAGE
    assert m["size"] == pb7.BOX_SIZE == len(m["body"])
    assert m["flags"] == pb7.FLAGS
    assert len(message) == pb7.HEADER_SIZE + m["size"]


def test_the_offer_body_carries_the_pokemon_the_host_was_holding(message):
    plain = pb7.decrypt(pb7.parse_message(message)["body"])
    assert struct.unpack_from("<H", plain, 4)[0] == 0            # the sanity word
    assert struct.unpack_from("<H", plain, 6)[0] == pb7.checksum(plain)
    assert struct.unpack_from("<H", plain, 8)[0] == 25           # Pikachu
    assert plain[0x14] == 9                                      # Static
    assert plain[0x40:0x4E].decode("utf-16le") == "Pikachu"
    assert plain[0xB0:0xBE].decode("utf-16le") == "Ryujinx"


def test_encrypting_a_decrypted_structure_returns_the_bytes_that_arrived(message):
    body = pb7.parse_message(message)["body"]
    assert pb7.encrypt(pb7.decrypt(body)) == body
    assert pb7.valid(body)


def test_a_message_built_around_a_body_parses_back(message):
    body = pb7.parse_message(message)["body"]
    built = pb7.build_message(pb7.OFFER_MESSAGE, body)
    m = pb7.parse_message(built)
    assert m["kind"] == pb7.OFFER_MESSAGE and m["body"] == body
    assert built == message


def test_a_body_that_is_not_the_box_size_is_refused():
    with pytest.raises(ValueError):
        pb7.decrypt(b"\0" * 100)
    with pytest.raises(ValueError):
        pb7.encrypt(b"\0" * 100)
    assert not pb7.valid(b"\0" * 100)


def test_every_shuffle_value_round_trips():
    """The permutation depends on the encryption constant, so every one of the 24 must invert."""
    seen = set()
    for ec in range(0, 1 << 20, 977):
        plain = bytearray(bytes(pb7.BOX_SIZE))
        struct.pack_into("<I", plain, 0, ec)
        struct.pack_into("<H", plain, 8, 25)
        seen.add(pb7.shuffle_value(ec))
        assert pb7.decrypt(pb7.encrypt(bytes(plain)))[8:] == bytes(plain)[8:]
    assert seen == set(range(24))


def test_the_joiner_answers_an_offer_once_with_a_structure_the_game_accepts(message, tmp_path):
    """`--offer echo` returns the host's own structure, so a refusal is about the protocol rather
    than the contents. It goes once: the host retransmits its offer until it is answered."""
    import types
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "lgpe_join", os.path.join(os.path.dirname(__file__), "..", "bin", "lgpe_join.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sent = []

    class Window:
        def send(self, body):
            return body

    state = {"window": Window()}
    args = types.SimpleNamespace(offer="echo")
    msg = pb7.parse_message(message)
    mod._answer_offer(args, state, msg, lambda b, p: sent.append(b))
    assert len(sent) == 1
    assert pb7.parse_message(sent[0])["body"] == msg["body"]

    # the same step again is a retransmit and is not answered twice
    mod._answer_offer(args, state, msg, lambda b, p: sent.append(b))
    assert len(sent) == 1

    # a fresh step is the peer offering something else, and is owed an answer of its own
    later = dict(msg, step=msg["step"] + 1)
    mod._answer_offer(args, state, later, lambda b, p: sent.append(b))
    assert len(sent) == 2
    assert [pb7.parse_message(m)["step"] for m in sent] == [2, 3]

    # and with no --offer it stays quiet
    state2, sent2 = {"window": Window()}, []
    mod._answer_offer(types.SimpleNamespace(offer=None), state2, msg,
                      lambda b, p: sent2.append(b))
    assert sent2 == []


def test_the_first_message_a_capture_gives_us_carries_the_hosts_own_trainer(message):
    """The marker payload was captured between two emulators sharing a save, so its trainer id pair
    is the host's. A joiner replaying it presents itself as the station it is trading with."""
    marker = os.path.join(os.path.dirname(__file__), "..", "scratchpad",
                          "lgpe_joiner_first_named.bin")
    if not os.path.exists(marker):
        pytest.skip("the marker payload is not here")
    with open(marker, "rb") as fh:
        ours = pb7.parse_message(fh.read())
    offer = pb7.decrypt(pb7.parse_message(message)["body"])
    assert pb7.trainer_id(ours["body"]) == pb7.trainer_id(offer, pb7.BOX_TRAINER_ID)


def test_a_replaced_trainer_id_changes_four_bytes_and_nothing_else():
    body = bytes(range(256)) * 2
    out = pb7.set_trainer_id(body, 41234, 12345)
    assert pb7.trainer_id(out) == (41234, 12345)
    assert out[4:] == body[4:] and len(out) == len(body)


def test_the_commit_is_answered_with_a_commit_of_our_own():
    """A station's player agreeing sends kind 3, one u32 holding 1. The peer sits on a screen with a
    spinner and no button until it has ours, so the answer cannot come from its side."""
    import types
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "lgpe_join", os.path.join(os.path.dirname(__file__), "..", "bin", "lgpe_join.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sent = []

    class Window:
        def send(self, body):
            return body

    state = {"window": Window(), "step": 4, "answered_step": 4}
    commit = pb7.parse_message(pb7.build_message(pb7.COMMIT_MESSAGE, b"\1\0\0\0", step=5))
    assert commit["kind"] == pb7.COMMIT_MESSAGE and commit["size"] == 4

    mod._answer_commit(types.SimpleNamespace(offer="echo"), state, commit,
                       lambda b, p: sent.append(b))
    assert len(sent) == 1
    ours = pb7.parse_message(sent[0])
    assert ours["kind"] == pb7.COMMIT_MESSAGE and ours["body"] == b"\1\0\0\0"
    assert ours["step"] == 5

    # a repeat of the same step is not answered twice
    mod._answer_commit(types.SimpleNamespace(offer="echo"), state, commit,
                       lambda b, p: sent.append(b))
    assert len(sent) == 1


def test_the_completed_trade_sends_the_pokemon_we_built_back_to_us():
    """Kind 4 is the result: the party once the trade has gone through. The second one carries the
    Pokemon the host received, so it comes back under our own trainer id and OT — the wire's own
    proof that a structure built outside the game is in a save inside it."""
    import struct
    result = os.path.join(os.path.dirname(__file__), "..", "scratchpad",
                          "ip23_pia.jsonl.payload8.bin")
    if not os.path.exists(result):
        pytest.skip("the completed trade capture is not here")
    with open(result, "rb") as fh:
        m = pb7.parse_message(fh.read())
    assert m["kind"] == pb7.RESULT_MESSAGE and m["step"] == 8
    plain = pb7.decrypt(m["body"])
    assert struct.unpack_from("<H", plain, 8)[0] == 16                  # Pidgey
    assert pb7.trainer_id(plain, pb7.BOX_TRAINER_ID) == (41234, 12345)  # ours, not the host's
    assert plain[0xB0:0xBE].decode("utf-16le") == "POKELDN"


def test_a_run_that_ends_mid_trade_says_so(capsys, monkeypatch):
    """A run that stops after the peer has offered leaves it mid-exchange, which a console answers
    by refusing the next trade for about half an hour. Reading a run's end as one's own doing rather
    than checking why it ended is what made that cost a lockout."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "lgpe_join", os.path.join(os.path.dirname(__file__), "..", "bin", "lgpe_join.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.TRADE_IN_PROGRESS.update(offer=False, commit=False)
    mod._warn_if_mid_trade()
    assert capsys.readouterr().out == ""

    mod.TRADE_IN_PROGRESS["offer"] = True
    mod._warn_if_mid_trade()
    out = capsys.readouterr().out
    assert "MID-TRADE" in out and "during the offers" in out

    mod.TRADE_IN_PROGRESS["commit"] = True
    mod._warn_if_mid_trade()
    assert "after the commit" in capsys.readouterr().out

    # the console's kind 4 ends the trade: once, whatever copies follow, and the exit is clean
    import pokeldn.lgpe.trade as trade_mod
    done = []
    monkeypatch.setattr(trade_mod, "show_done", lambda: done.append(1))
    assert mod._note_result() and not mod._note_result()
    assert done == [1]
    mod._warn_if_mid_trade()
    assert "MID-TRADE" not in capsys.readouterr().out


def test_a_fresh_offer_moves_only_its_pid_and_constant(message, tmp_path):
    """`--fresh-pid` on a console's own structure: the game's sanity check still passes, every byte
    but the two ids and the checksum decodes back, and the shiny xor is unchanged."""
    import argparse
    from pokeldn.lgpe import trade

    body = pb7.parse_message(message)["body"]
    (tmp_path / "offer.pb7").write_bytes(body)
    args = argparse.Namespace(offer=str(tmp_path / "offer.pb7"), fresh_pid=True)
    trade.fresh_offer(args)
    made = open(args.offer, "rb").read()
    assert args.offer.endswith("_fresh.pb7") and pb7.valid(made)
    before, after = pb7.decrypt(body), pb7.decrypt(made)
    changed = {i for i in range(pb7.BOX_SIZE) if before[i] != after[i]}
    assert changed <= {0, 1, 2, 3, 6, 7, 0x18, 0x19, 0x1A, 0x1B} and {0, 0x18} & changed

    def shiny(p):
        pid = struct.unpack_from("<I", p, pb7.OFF_PID)[0]
        tid, sid = struct.unpack_from("<HH", p, pb7.BOX_TRAINER_ID)
        return tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)
    assert shiny(after) == shiny(before)

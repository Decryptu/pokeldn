"""A Let's Go console withdrawing its trade vote, and voting again, against our host.

The console's records are the ones a retail Let's Go Pikachu published when its player pressed A
onto Retour as the confirmation greyed the buttons: 1 1 1, 0 1 1, 1 2 2, then state 2 with counter
3. The host that answered it with the vote agreed held the console on a warning and locked the
save's trading for 30 minutes. What our host publishes back is run through the game's own record
code under unicorn: the console's reader 0x11ba20, the status 0x3488b0 its screens branch on, and
the host-side authority 0x11b6c0 whose answer ours must equal (docs/lgpe_session.md)."""
import os
import struct

import pytest

from test_lgpe_host_commit import JOINER, ONES, stage, words  # noqa: F401  (the fixture)

IMAGE = "scratchpad/lgpe/main.bin"      # Let's Go Pikachu 1.0.2
needs_image = pytest.mark.skipif(not os.path.exists(IMAGE), reason="needs the Let's Go main")


def record(state, arg, counter, tail, step=11):
    return struct.pack("<5I", state, arg, counter, step, tail)


def withdraw(stage):
    """The offered clone from the console's first 1 1 1 to its state 2, at lgh65's spacing."""
    s = stage["s"]
    s.clone.flags.pop(3, None)
    s.clone.tail.pop(3, None)
    stage["console_publishes"](3, record(1, 1, 1, 0))
    stage["run"](0.07)
    stage["console_publishes"](3, record(0, 1, 1, 1))
    stage["run"](0.37)
    stage["console_publishes"](3, record(1, 2, 2, 1))
    stage["run"](0.37)
    stage["console_publishes"](3, record(2, 2, 3, 1))
    stage["run"](3.0)


def test_a_withdrawn_vote_keeps_the_agreed_word_and_takes_the_counter(stage):
    """Within a tick the host publishes type 4 with the agreed word still 1, the console's counter
    3 in the joiner's slot and the trailing word on by one, and its own type 2 under that trailing
    word. It never publishes the withdrawn 2 as agreed."""
    withdraw(stage)
    t4 = stage["published"](3, ctype=4)
    assert all(w[0] != 2 for w in t4), "the withdrawn vote went out as agreed"
    assert t4[-1] == [1, 0, 0, 3, 0, 0, 10, 2]
    assert stage["published"](3)[-1] == [1, 1, 1, 10, 2]


def test_a_second_vote_after_a_withdrawal_is_agreed_in_one_publish(stage):
    """The console republishes 0 2 3 on the new trailing word, then votes 2 again under counter 4.
    The host votes 2 under its next counter and moves the agreed word and the trailing word
    together, as the authority does when every station votes the same."""
    withdraw(stage)
    stage["console_publishes"](3, record(0, 2, 3, 2))
    stage["run"](1.0)
    assert stage["published"](3, ctype=4)[-1][0] == 1
    stage["console_publishes"](3, record(1, 2, 4, 2))
    stage["run"](0.1)
    assert stage["published"](3)[-1] == [1, 2, 2, 10, 3]
    assert stage["published"](3, ctype=4)[-1] == [2, 0, 0, 3, 0, 0, 10, 3]


# The game's own record code. Globals 0x15fc910 / 0x15fc980 point at these after relocation.
G910, G980 = 0x1614098, 0x163c8d0


def game(host, rec, type4, slots=(), my_index=1, step=10):
    from nso_run import Runner, SCRATCH
    from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_X0, UC_ARM64_REG_X8
    mgr, sess, trade, elem = (SCRATCH + n * 0x10000 for n in (2, 3, 4, 5))

    class R(Runner):
        def _code(self, uc, addr, size, _):
            fake = {0x59e9c0: 0, 0x59e920: 1 if host else 0, 0x59ea70: 2, 0x521030: 0}
            if addr not in fake:
                return super()._code(uc, addr, size, _)
            if addr == 0x521030:                 # the clone send fails: the record stays local
                uc.mem_write(uc.reg_read(UC_ARM64_REG_X8), bytes(8))
            uc.reg_write(UC_ARM64_REG_X0, fake[addr])
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    r = R(IMAGE)
    r.write(G910, struct.pack("<Q", mgr))
    r.write(G980, struct.pack("<Q", sess))
    r.write(mgr + 0x1288, struct.pack("<I", my_index))
    r.write(mgr + 0x274, struct.pack("<I", step))
    r.write(mgr + 0x278, struct.pack("<4I", step, step, 0, 0))
    r.write(trade + 0x70, struct.pack("<6I8xQ", *rec, elem))
    r.write(elem + 0x1430, b"\x00")
    r.write(elem + 0x8cc, struct.pack("<I", step))
    r.write(elem + 0x1638, struct.pack("<8I", *type4))
    for i, slot in enumerate(slots):
        r.write(elem + 0x918 + i * 0x260, bytes([i]))
        r.write(elem + 0xb20 + i * 0x260, struct.pack("<5I", *slot))

    def read(addr, n):
        return list(struct.unpack(f"<{n}I", bytes(r.uc.mem_read(addr, 4 * n))))
    if host:
        r.call(0x11b6c0, (trade + 0x70,))
        return read(elem + 0x1638, 8)
    r.call(0x11ba20, (trade + 0x70,))
    status, _ = r.call(0x3488b0, (trade,))
    return read(trade + 0x70, 6), read(elem + 0x8c0, 5), status


@needs_image
def test_the_games_authority_answers_the_withdrawal_as_our_host_does(stage):
    """0x11b6c0 as the session host, holding our 1 1 1 and the console's 2 2 3 on trailing word 1,
    writes the same type 4 our host published."""
    withdraw(stage)
    ours = stage["published"](3, ctype=4)[-1]
    theirs = game(True, (1, 1, 1, 1, 0, 1), (1, 0, 0, 0, 0, 0, 10, 1),
                  slots=[(1, 1, 1, 10, 1), (2, 2, 3, 10, 1)], my_index=0)
    assert theirs == ours


@needs_image
@pytest.mark.parametrize("answer, status", [
    ("ours", 2),                                 # the screen's exit: the vote is withdrawn
    ((2, 0, 0, 0, 0, 0, 10, 2), 4),              # the vote agreed under it, as the locked run had
])
def test_the_console_leaves_its_confirmation_only_on_our_answer(stage, answer, status):
    """The console's reader takes our type 4 over its record 2 2 3 (agreed word 1, trailing 1):
    state 0, the agreed word kept, 0 2 3 republished on trailing word 2, status 2. The locked run's
    answer gives status 4, which the confirmation loop at 0x9c3300 has no case for."""
    withdraw(stage)
    type4 = stage["published"](3, ctype=4)[-1] if answer == "ours" else answer
    rec, republished, got = game(False, (2, 1, 2, 3, 0, 1), type4)
    assert got == status
    assert republished == [0, 2, 3, 10, 2]


@needs_image
def test_the_console_takes_the_agreed_second_vote(stage):
    """After the re-vote the console's reader, holding 1 2 4 on trailing word 2, takes our type 4:
    the agreed word 2, and it republishes 0 2 4 on trailing word 3, the answer a console gives
    the agreed vote on a trade that goes through."""
    withdraw(stage)
    stage["console_publishes"](3, record(0, 2, 3, 2))
    stage["run"](0.5)
    stage["console_publishes"](3, record(1, 2, 4, 2))
    stage["run"](0.1)
    rec, republished, _ = game(False, (1, 1, 2, 4, 0, 2), stage["published"](3, ctype=4)[-1])
    assert rec[1] == 2
    assert republished == [0, 2, 4, 10, 3]

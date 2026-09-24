"""The BDSP security phase against a model of the console's own state machine, in both roles.

The model is `TradeParentStateModel$$StateProc` [0x1c23350] and `TradeSecurityController$$ReciveState`
[0x1c24f10] as `docs/bdsp_trade.md` (Who leads) reads them. The client side is bin/bdsp_connect.py's
policy: answer each state with `room.mirror_trade_state`, answer the Pokemon with ours, and repeat
our state once a second. A console is CHILD when the client offers the rarer Pokemon.
"""

import heapq
import random

import pytest

from pokeldn.bdsp import room

INIT, WAIT, SEND_POKE, WAIT_POKE, SEND_READYOK, WAIT_READYOK, START_WRITE_SAVE = 1, 2, 3, 4, 5, 6, 7
PARENT, CHILD = 1, 2
FRAME = 1 / 30


class Console:
    """One console's security phase. `send(kind, value)` puts a message on the wire."""

    def __init__(self, role, send, rng):
        self.role, self.send = role, send
        self.state, self.target_state = INIT, None
        self.target_poke = self.ready_ok = False
        self.wait_rnd = rng.uniform(0.0, 2.0)          # waitRndTime, counted down in SEND_POKE
        self.send("state", INIT)

    def tick(self, dt):
        if self.state == WAIT and self.target_state == WAIT:
            self.state = SEND_POKE
        elif self.state == SEND_POKE:
            self.wait_rnd -= dt
            if self.wait_rnd <= 0:
                self.send("poke", None)
                self.state = WAIT_POKE
        elif self.state == WAIT_POKE and self.target_poke:
            self.state = SEND_READYOK
        elif self.state == SEND_READYOK and self.role == PARENT:
            self.send("state", SEND_READYOK)
            self.state = WAIT_READYOK
        elif self.state == WAIT_READYOK and self.ready_ok:
            if self.role == PARENT:
                self.send("state", WAIT_READYOK)
            self.state = START_WRITE_SAVE

    def receive_state(self, theirs):
        if self.state == INIT:
            self.state = WAIT
            self.send("state", WAIT)
        elif self.state == SEND_POKE:
            self.send("state", SEND_POKE)
        elif self.state == SEND_READYOK and self.role == CHILD and theirs in (5, 6):
            self.send("state", SEND_READYOK)
            self.state = WAIT_READYOK
            if theirs == 6:
                self.ready_ok = True
        elif self.state == WAIT_READYOK:
            self.ready_ok = True
        self.target_state = theirs

    def receive_poke(self):
        # SetTragetPokeData ends by sending the console's state, WAIT_POKE at that moment.
        self.target_poke = True
        self.send("state", self.state)


def run(role, mirror, seed, repeat=1.0, seconds=60.0):
    """-> the time the console reached START_WRITE_SAVE, or None."""
    rng = random.Random(seed)
    now, wire, seq = 0.0, [], 0

    def post(to, kind, value):
        nonlocal seq
        seq += 1
        heapq.heappush(wire, (now + rng.uniform(0.02, 0.25), seq, to, kind, value))

    client = {"ours": 0, "theirs": None, "last_repeat": 0.0}
    console = Console(role, lambda k, v: post("client", k, v), rng)
    while now < seconds:
        now += FRAME
        while wire and wire[0][0] <= now:
            _, _, to, kind, value = heapq.heappop(wire)
            if to == "console":
                console.receive_state(value) if kind == "state" else console.receive_poke()
            elif kind == "poke":
                post("console", "poke", None)
            else:
                client["theirs"] = value
                client["ours"] = mirror(value)
                post("console", "state", client["ours"])
        if client["theirs"] is not None and client["ours"] and now - client["last_repeat"] >= repeat:
            client["last_repeat"] = now
            post("console", "state", client["ours"])
        console.tick(FRAME)
        if console.state == START_WRITE_SAVE:
            return now
    return None


def echo(theirs):
    """The client before the fix: every state answered with itself."""
    return theirs


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("role", [PARENT, CHILD])
def test_the_mirror_reaches_the_save_in_both_roles(role, seed):
    assert run(role, room.mirror_trade_state, seed) is not None


@pytest.mark.parametrize("seed", range(5))
def test_echoing_wait_poke_deadlocks_a_child_console(seed):
    """The reported fault, reproduced: a CHILD console sits in SEND_READYOK forever."""
    assert run(CHILD, echo, seed) is None


@pytest.mark.parametrize("seed", range(5))
def test_echoing_still_completes_as_parent(seed):
    """Every completed retail trade had the console as PARENT, which is why the echo worked."""
    assert run(PARENT, echo, seed) is not None


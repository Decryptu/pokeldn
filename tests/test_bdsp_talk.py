"""The talk answer and each --after-talk message against the console's receive window
(docs/bdsp_protocol.md, The console approaching)."""

import trio

import bdsp_connect

TALK_ANSWER = bytes.fromhex("640003000104")
TRANSITION = bytes.fromhex("0700021200")


class Window:
    """The console's receive window: in-order delivery, an ack 20 ms after each new id."""

    def __init__(self, nursery, next_id, lose=()):
        self.nursery, self.lose = nursery, set(lose)
        self.st = {"their_ack_id": next_id, "our_next_seq": 0}
        self.sent, self.delivered = [], []

    def send_at(self, seq, payload):
        self.sent.append((seq, payload))
        if (seq, payload) in self.lose:
            self.lose.discard((seq, payload))
            return
        if seq == self.st["their_ack_id"]:
            self.delivered.append(payload)
            self.nursery.start_soon(self._ack, seq + 1)

    async def _ack(self, next_id):
        await trio.sleep(0.02)
        self.st["their_ack_id"] = max(self.st["their_ack_id"], next_id)


async def _talk(lose=()):
    async with trio.open_nursery() as nursery:
        window = Window(nursery, next_id=13, lose=lose)
        first = await bdsp_connect.send_acked(window.st, window.send_at, TALK_ANSWER, retry=0.1)
        second = await bdsp_connect.send_acked(window.st, window.send_at, TRANSITION, retry=0.1)
    return window, first, second


def test_the_answer_and_the_transition_take_consecutive_ids_and_both_arrive():
    window, first, second = trio.run(_talk)
    assert (first, second) == (13, 14)
    assert window.delivered == [TALK_ANSWER, TRANSITION]


def test_a_lost_copy_is_resent_under_its_own_id():
    window, first, second = trio.run(_talk, [(14, TRANSITION)])
    assert second == 14
    assert [seq for seq, payload in window.sent if payload == TRANSITION] == [14, 14]
    assert window.delivered == [TALK_ANSWER, TRANSITION]

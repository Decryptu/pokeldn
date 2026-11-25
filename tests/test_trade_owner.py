"""Console OT uses the current seat's trainer and leaves trade-back records intact."""
from threading import Thread

import pytest

from pokeldn import pokemon, trade_owner


@pytest.mark.parametrize("return_each", [False, True])
def test_host_waits_for_a_checked_queue_and_returns_the_console_record_unchanged(monkeypatch, return_each):
    workers = []

    def thread(**kwargs):
        worker = Thread(**kwargs)
        workers.append(worker)
        return worker

    def prepare(game, raw, *, fresh, fields):
        trainer = fields["trainer"]
        assert (trainer["tid"], trainer["sid"], trainer["gender"]) == (10, 20, 1)
        return trainer["ot"].encode() + raw

    monkeypatch.setattr(trade_owner, "Thread", thread)
    monkeypatch.setattr(pokemon, "prepare", prepare)
    partner = trade_owner.ReceiverTrade("pla", [b"a", b"b"], bytes, return_each=return_each)
    partner.offer(b"return")
    assert partner.theirs().offer is None

    partner.hear({"ot": "First", "tid": 10, "sid": 20, "gender": 1})
    workers[-1].join(2)
    assert partner.theirs().offer == b"Firsta"
    partner.done()
    if return_each:
        assert partner.theirs().offer == b"return"
        partner.done()
    assert partner.theirs().offer == b"Firstb"

    partner.reset()
    assert partner.theirs().offer is None
    partner.hear({"ot": "Second", "tid": 10, "sid": 20, "gender": 1})
    workers[-1].join(2)
    assert partner.theirs().offer == b"Seconda"


def test_bdsp_uses_gender_from_the_console_record_when_its_ot_matches_the_session(monkeypatch):
    trainer = {"ot": "Link", "tid": 10, "sid": 20}
    monkeypatch.setattr(pokemon.SERVICE, "owner", lambda game, raw: {**trainer, "gender": 1, "handler": 0})

    def prepare(game, raw, *, fresh, fields):
        assert fields["trainer"] == {**trainer, "gender": 1}
        return raw

    monkeypatch.setattr(pokemon, "prepare", prepare)
    assert trade_owner.rewrite("bdsp", [b"offer"], trainer, bytes, shown=b"console") == [b"offer"]

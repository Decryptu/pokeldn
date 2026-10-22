"""bin/sv_join.py --trade-back: the trade after a queued one offers what the console sent in it,
byte for byte, with no --fresh-pid; replayed against a pair host's own trade (tests/data/sv_pair_trade.txt)."""
import os
from pathlib import Path

import sv_join
from pokeldn.sv import pokemon, trade

PAIR = os.path.join(os.path.dirname(__file__), "data", "sv_pair_trade.txt")


def test_a_scarlet_joiner_returns_the_console_record(tmp_path):
    rows = [line.split() for line in Path(PAIR).read_text(encoding="utf-8").splitlines() if line.strip()]
    ours = bytes.fromhex(rows[3][2])[4:]
    theirs = pokemon.to_wire(pokemon.fresh_identity(pokemon.from_wire(ours)))
    assert theirs != ours
    (tmp_path / "ours.bin").write_bytes(ours)
    args = sv_join.build_parser().parse_args(
        ["--trade-offer", str(tmp_path / "ours.bin"), "--fresh-pid", "--trade-back"])
    stage = sv_join.trade_stage(args)
    console_offer = trade.build(trade.KEY_TRADE, trade.KIND_OFFER, 0, theirs).hex()

    def trade_once(rows):
        """-> the records our joiner offered while the console offered `theirs`."""
        offered = []
        for direction, port, hx in rows:
            if direction != "TX":
                continue
            if hx.startswith("80000200"):
                hx = console_offer
            for _delay, out_port, payload in stage.on_message(int(port), bytes.fromhex(hx)):
                m = trade.parse(payload) if out_port == 0 else None
                if m and m[:2] == (trade.KEY_TRADE, trade.KIND_OFFER):
                    offered.append(m[3])
        return offered

    first = trade_once(rows)
    assert stage.trades == 1 and not stage.done
    assert len(first) == 1 and first[0] != ours            # --fresh-pid on the queued record
    species = [pokemon.read(pokemon.from_wire(r))["species"] for r in (first[0], ours)]
    assert species[0] == species[1]
    assert trade_once(rows[2:]) == [theirs]                 # the console's bytes, untouched
    assert stage.trades == 2 and stage.done                 # the queue went out and came back
    assert stage.host_offers == [theirs, theirs]

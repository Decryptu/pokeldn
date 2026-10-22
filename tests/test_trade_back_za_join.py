"""`bin/za_join.py --trade-back` against a scripted Legends Z-A host (pokeldn/trade_back.py)."""
import argparse

from pokeldn import za
from pokeldn.ldn import reliable
from pokeldn.za import host as za_host

HOST_VAR, JOINER_VAR = 0xEFB0, 0x5AD2
HEADER = bytes.fromhex("0101b90300bc815801")


def test_the_joiner_offers_back_the_record_the_console_traded(tmp_path):
    """Trade 1 offers the queued record; trade 2 offers, byte for byte, the record the console picked
    in trade 1, after a cursor that previewed another Pokemon and was not traded."""
    import za_join
    plain = bytearray(za.pokemon.SIZE_PARTY)
    plain[8] = 25
    ours = za.pokemon.build_offer(HEADER, bytes(plain), b"\x01")
    (tmp_path / "offer.bin").write_bytes(ours)
    args = argparse.Namespace(game_dir=str(tmp_path), trade_offer=[str(tmp_path / "offer.bin")],
                              selection_count=0, offer_out=None, selection_delay=0.0,
                              selection_period=1.0, offer_delay=1.0, trade_back=True)

    def theirs(species, mark):
        rec = bytearray(za.pokemon.SIZE_PARTY)
        rec[8] = species
        rec[0x1C:0x20] = (0x1234_0000 + species).to_bytes(4, "little")    # its PID
        return za.pokemon.build_offer(HEADER, bytes(rec), bytes([mark]))
    sent = []
    game = za_join.GameStreams(args, lambda proto, body, **kw: sent.append((proto, body)),
                               lambda *a, **kw: None, None)

    def picks():
        out = []
        for proto, body in sent:
            r = reliable.parse_reliable(body)
            if (proto == za_join.GAME_RELIABLE and r.flagsA != reliable.FLAGSA_CTRL
                    and r.payload[:2] == b"\x01\x01" and r.payload[-1] == za_host.OFFER_PICK):
                out.append(r.payload)
        return out

    state = {"t": 0.0, "seq": 1}

    def host(msg, steps):
        game.on_message(za_join.GAME_RELIABLE, reliable.build_reliable(
            state["seq"], state["seq"], msg, flagsA=reliable.FLAGSA_GBA), state["t"])
        state["seq"] += 1
        for _ in range(steps):
            state["t"] += 0.02
            game.pump(HOST_VAR, JOINER_VAR, state["t"])

    def trade(cursor, pick, round_):
        host(theirs(cursor, 1), 50)
        host(theirs(pick, 0), 200)
        host(bytes.fromhex("0104b901") + bytes([round_]), 800)

    host(theirs(1, 1), 100)                     # the streams open, our preview goes out
    trade(2, 3, 0)
    assert game.trades == 1 and not game.queue_done
    trade(4, 5, 0)
    assert game.trades == 2 and game.queue_done

    first, second = picks()
    body = slice(za.pokemon.OFFER_HEADER_SIZE, -1)
    assert first[body] == ours[body]
    assert second[body] == theirs(3, 0)[body]
    assert za.pokemon.parse_offer(second)[1] == za.pokemon.parse_offer(theirs(3, 0))[1]

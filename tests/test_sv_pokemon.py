"""The Gen-9 record a Scarlet trade message carries.

The sample is the offer in `tests/data/sv_pair_trade.txt`, the message the emulated pair put on
0x7C port 0. A retail Scarlet's own offer is a capture and stays out of the repository
(CLAUDE.md rule 7); what it read out is on `docs/sv.md`.
"""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import gen8
from pokeldn.sv import pokemon, trade


def pair_offer():
    """-> the 348-byte trade body the pair's host offered."""
    path = os.path.join(os.path.dirname(__file__), "data", "sv_pair_trade.txt")
    for line in open(path):
        parts = line.split()
        if len(parts) == 3 and parts[2].startswith("80000200"):
            return bytes.fromhex(parts[2])[4:]
    raise AssertionError("no offer in the pair's messages")


def test_a_trade_body_is_the_prefix_and_a_party_record():
    body = pair_offer()
    assert len(body) == trade.OFFER_SIZE == pokemon.SIZE_WIRE
    assert body[:4] == pokemon.WIRE_PREFIX
    assert len(body) - len(pokemon.WIRE_PREFIX) == pokemon.SIZE_PARTY == gen8.SIZE_PARTY


def test_the_record_decrypts_under_the_gen8_crypto():
    """The checksum the record carries is the sum of the body the Gen-8 cipher and block order
    produce. A wrong LCG cannot survive it; a wrong block order can, so the fields below are what
    pin the order."""
    plain = pokemon.from_wire(pair_offer())
    assert struct.unpack_from("<H", plain, pokemon.OFF_SANITY)[0] == 0
    assert pokemon.checksum(plain) == struct.unpack_from("<H", plain, pokemon.OFF_CHECKSUM)[0]


def test_the_pair_host_offered_a_level_one_sprigatito():
    fields = pokemon.read(pokemon.from_wire(pair_offer()))
    assert fields["species"] == 906
    assert fields["nickname"] == "Sprigatito"
    assert fields["ot_name"] == "Mattia"
    assert fields["ht_name"] == ""
    assert fields["level"] == 1
    assert fields["experience"] == 0
    assert fields["ball"] == 4
    assert fields["version"] == pokemon.VERSION_SCARLET
    assert fields["moves"][:2] == (10, 39)
    assert fields["stats"] == (12, 6, 6, 6, 5, 6)
    assert fields["stats"][0] == fields["current_hp"]
    assert fields["met_date"] == (23, 7, 21)


def test_the_wire_form_round_trips_byte_for_byte():
    body = pair_offer()
    assert pokemon.to_wire(pokemon.from_wire(body)) == body


def test_a_body_with_a_foreign_prefix_is_refused():
    body = bytearray(pair_offer())
    body[0] ^= 0xFF
    with pytest.raises(ValueError):
        pokemon.from_wire(bytes(body))


def test_the_internal_index_and_the_dex_number_part_at_917():
    for species in (1, 50, 906, 916):
        assert pokemon.internal_index(species) == species
        assert pokemon.national(species) == species
    for species in range(917, 1011):
        assert pokemon.national(pokemon.internal_index(species)) == species
    assert pokemon.internal_index(917) != 917


def test_build_composes_a_record_the_reader_reads_back():
    plain = pokemon.build(species=917, nickname="POKELDN", ot_name="Decryptu", level=50,
                          trainer_id=12345, secret_id=54321, moves=(1, 2, 3, 4),
                          evs=(4, 4, 4, 4, 4, 4), ball=4, met_level=50)
    fields = pokemon.read(plain)
    assert fields["species"] == 917
    assert fields["species_internal"] == pokemon.internal_index(917)
    assert fields["nickname"] == "POKELDN"
    assert fields["ot_name"] == "Decryptu"
    assert fields["level"] == 50
    assert fields["ivs"] == (31,) * 6
    assert fields["met_level"] == 50
    assert not fields["is_shiny"]
    assert pokemon.from_wire(pokemon.to_wire(plain)) == plain


def test_a_shiny_personality_value_reads_back_shiny():
    pid = pokemon.shiny_pid(12345, 54321)
    plain = pokemon.build(species=906, trainer_id=12345, secret_id=54321, pid=pid)
    assert pokemon.read(plain)["is_shiny"]


def test_a_composed_offer_runs_the_trade_the_pair_ran():
    """A record composed here goes through the stage the pair's messages drive, and the host's
    side comes out the pair host's byte for byte apart from the offer itself. Nothing reaches a
    console that this has not run first (CLAUDE.md, prove it offline)."""
    path = os.path.join(os.path.dirname(__file__), "data", "sv_pair_trade.txt")
    rows = [line.split() for line in open(path) if line.strip()][2:]
    pair_body = bytes.fromhex(rows[0][2])[4:]
    composed = pokemon.to_wire(pokemon.write(pokemon.from_wire(pair_body),
                                             nickname="POKELDN", is_nicknamed=1,
                                             ivs=(31, 31, 31, 31, 31, 31)))
    assert composed != pair_body and len(composed) == len(pair_body)

    stage = trade.TradeStage(composed)
    sent = []
    for direction, port, hx in rows:
        if direction != "RX":
            continue
        for _delay, out_port, payload in stage.on_message(int(port), bytes.fromhex(hx)):
            sent.append((out_port, payload))
    expected = [(int(port), bytes.fromhex(hx)) for direction, port, hx in rows if direction == "TX"]
    assert len(sent) == len(expected)
    for (got_port, got), (want_port, want) in zip(sent, expected):
        assert got_port == want_port
        if want == bytes.fromhex(rows[0][2]):
            assert got == trade.build(trade.KEY_TRADE, trade.KIND_OFFER, 0, composed)
        else:
            assert got == want
    assert stage.done
    assert pokemon.read(pokemon.from_wire(stage.joiner_offer))["species"] == 906


def test_every_field_a_retail_record_uses_has_a_name():
    """A record built from zero and then given every field `read` reports from a real one comes
    out byte for byte that record: the map covers the whole structure, with nothing left over."""
    body = pair_offer()
    real = pokemon.from_wire(body)
    fields = pokemon.read(real)
    for key in ("species_internal", "is_shiny"):        # both are read from other fields
        fields.pop(key, None)
    rebuilt = pokemon.build(**fields)
    assert rebuilt == real


def test_build_defaults_are_a_level_one_record_that_agrees_with_itself():
    fields = pokemon.read(pokemon.build(species=906))
    assert fields["level"] == 1 and fields["experience"] == 0
    assert fields["met_level"] == 1 and fields["obedience_level"] == 1
    assert fields["ball"] == 4
    assert fields["ht_name"] == "" and fields["current_handler"] == 0

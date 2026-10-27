"""A player name written into each title's recorded identity carries a language that draws it: a
retail Scarlet drew a kana name under the recorded English (2) record in half-width glyphs."""

from pathlib import Path

import pytest

from pokeldn.bdsp import room
from pokeldn.lgpe import pb7, reference as lgpe_reference
from pokeldn.pla import data_exchange
from pokeldn.sv import reference as sv_reference, streams
from pokeldn.swsh import trade_payload
from pokeldn.za import reference as za_reference
from test_swsh_trade_payload import a_payload_with_the_profile


def _sv(name):
    record = sv_reference.named_record(open(sv_reference.RECORDS + "/001.bin", "rb").read(), name)
    return sv_reference.identity_trainer(streams.decompress(record))["language"]


def _za(name):
    return za_reference.identity_trainer(za_reference.named(za_reference.load("identity10"), name))["language"]


def _lgpe(name):
    body = pb7.parse_message(Path(lgpe_reference.IDENTITY).read_bytes())["body"]
    return pb7.first_trainer(pb7.set_trainer_name(body, name))["language"]


def _pla(name):
    return data_exchange.read_trainer(data_exchange.build_record(name=name))["language"]


def _swsh(name):
    out = trade_payload.rewrite(a_payload_with_the_profile(), trainer_name=name)
    tail = trade_payload.read_tail(out)["language"]
    card = out[trade_payload.TRAINER_CARD_OFFSET + trade_payload.TRAINER_CARD_LANGUAGE]
    status = out[trade_payload.MY_STATUS_OFFSET + trade_payload.MY_STATUS_LANGUAGE]
    return tail if tail == card == status else (tail, card, status)


def _bdsp(name):
    return room.traner_trainer(room.build_trade_traner(name, 1, 2)[-32:])["language"]


@pytest.mark.parametrize("title", [_sv, _za, _lgpe, _pla, _swsh, _bdsp])
@pytest.mark.parametrize("name, language", [("キリコ", 1), ("키리코", 8), ("小明", 1)])
def test_a_cjk_name_is_written_with_its_language(title, name, language):
    assert title(name) == language


@pytest.mark.parametrize("title", [_sv, _za, _lgpe, _pla, _swsh, _bdsp])
def test_a_latin_name_keeps_the_recorded_language(title):
    assert title("POKELDN") == title("Player")

"""The console's trainer, from the link to Settings' Find mine (docs/gui.md, Find your trainer)."""
import pytest

from pokeldn import console_trainer
from pokeldn.app import settings as settings_mod


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(console_trainer, "_shown", set())
    monkeypatch.setattr(settings_mod, "PATH", tmp_path / "settings.json")
    return settings_mod.Settings()


def found(capsys, settings):
    for line in capsys.readouterr().out.splitlines():
        if message := console_trainer.read(line):
            settings.found(message)


def test_a_firered_host_trade_fills_the_gba_row_from_the_consoles_link_player(fresh, capsys):
    from tests.test_host_end_to_end import _run_full_stack
    _run_full_stack(2)
    found(capsys, fresh)
    took = fresh.take_found("gba")
    # The scripted console's LinkPlayer: "SWITCH", trainerId 0x47ED8822, FireRed.
    assert (took["ot"], took["version"]) == ("SWITCH", 4)
    assert (fresh.tid, fresh.sid, fresh.ot) == (0x8822, 0x47ED, "SWITCH")
    assert fresh.take_found("switch") is None


def test_a_za_host_with_no_gift_fills_the_switch_row_from_the_consoles_identity(fresh, capsys):
    from pokeldn.za import reference
    from tests.test_online import za_seat
    host, console = za_seat(None)
    console.game(reference.named(reference.load("identity10"), "Florian"), 5.0)
    console.run(5.5, 5.0)
    found(capsys, fresh)
    fresh.take_found("switch")
    assert fresh.ot == "Florian" and fresh.gender == 1
    assert fresh.ids("za") == (5071, 14217)


def test_find_mine_for_one_game_fills_only_that_games_trainer(fresh, capsys):
    """With a trainer per game, the Z-A console's identity becomes Z-A's trainer; the other games keep theirs."""
    from pokeldn.za import reference
    from tests.test_online import za_seat
    fresh.per_game_trainer = True
    host, console = za_seat(None)
    console.game(reference.named(reference.load("identity10"), "Florian"), 5.0)
    console.run(5.5, 5.0)
    found(capsys, fresh)
    assert fresh.take_found("sv") is None
    fresh.take_found("za")
    assert fresh.ids("za") == (5071, 14217) and fresh.trainer("za")["gender"] == 1
    assert fresh.name("za") == "Florian" and fresh.ot == fresh.name("sv") == "POKELDN"
    assert fresh.ids("sv") == settings_mod.Settings(**{k: getattr(fresh, k) for k in ("tid", "sid", "switch_tid", "switch_sid")}).ids("sv")
    fresh.per_game_trainer = False
    assert fresh.name("za") == "POKELDN"


def test_a_switch_id_pair_shows_as_the_console_displayed_it():
    # A Legends Z-A Pokemon with TID 12345, SID 54321 showed ID 993401 (docs/za.md).
    shown_id, secret = console_trainer.shown("za", 12345, 54321)
    assert shown_id == 993401
    assert settings_mod.Settings(switch_tid=shown_id, switch_sid=secret).ids("za") == (12345, 54321)
    assert console_trainer.shown("frlg", 12345, 54321) == (12345, 54321)

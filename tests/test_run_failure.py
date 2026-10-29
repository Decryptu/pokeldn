"""A run's end in the player's words (pokeldn.app.failure), fed the lines real code prints: tracebacks of the
exceptions the radio and the key derivation raise, and the `[link]` lines pokeldn.ldn.show_link prints."""
import json
import traceback

import ldn
import pytest

import pokeldn.ldn
from pokeldn.app import failure, settings
from pokeldn.ldn import esp32

KEY_NAMES = ("aes_kek_generation_source", "aes_key_generation_source", "master_key_00", "master_key_12")


def lines_of(error: BaseException) -> list[str]:
    try:
        raise error
    except BaseException as raised:
        return "".join(traceback.format_exception(raised)).splitlines()


def watched(lines, linking=True) -> failure.Watch:
    watch = failure.Watch(linking)
    for line in lines:
        watch.line(line)
    return watch


@pytest.fixture
def links(monkeypatch, capsys):
    """The `[link]` lines a managed run prints, as the app reads them from its output."""
    monkeypatch.setenv("POKELDN_MANAGED_RUN", "1")
    monkeypatch.setattr(pokeldn.ldn, "_waiting", False)

    def say(*states):
        for state in states:
            pokeldn.ldn.show_link(state)
        return capsys.readouterr().out.splitlines()
    return say


def test_a_console_that_never_joined_is_named_and_one_that_traded_is_not(links):
    waited = links("waiting", "waiting")
    assert waited == ["[link] waiting"]       # printed once, however often the radio scans
    verdict = watched(waited).verdict(0, stopped=False)
    assert verdict is not None and "never joined" in verdict.text
    traded = watched([*links("joined"), "[done] trade 1 complete", *links("left")]).verdict(0, stopped=False)
    assert traded is None
    assert watched(waited, linking=False).verdict(0, stopped=False) is None   # a beacon: no console joins
    assert watched(waited).verdict(0, stopped=True) is None                    # the player's Stop


def test_a_run_that_never_opened_a_network_is_not_blamed_on_the_console():
    """An export or a save to the board prints no `[link] waiting`."""
    assert watched(["[gift] wrote the card"]).verdict(0, stopped=False) is None


def test_old_firmware_and_a_dropped_board_send_the_player_to_the_board_page():
    old = watched(lines_of(esp32.RadioError(f"board speaks protocol 1, host speaks {esp32.PROTOCOL_VERSION}")))
    assert old.verdict(1, False).action == "board" and "firmware" in old.verdict(1, False).text
    lost = watched(["[esp32] The board's USB connection failed (gone). Unplug it and plug it back in.",
                    *lines_of(esp32.RadioError("the board left USB: gone"))])
    assert "dropped" in lost.verdict(1, False).text      # the first cause stays the one shown


def test_a_keys_file_without_a_protocol_key_names_it_and_sends_the_player_to_settings(tmp_path):
    path = tmp_path / "prod.keys"
    path.write_text("".join(f"{name} = {'00' * 16}\n" for name in KEY_NAMES if name != "master_key_12"))
    derivation = ldn.KeyDerivation(ldn.load_keys(str(path)), 3)
    with pytest.raises(ldn.MissingKey) as raised:
        derivation.derive_advertise_key(b"advertisement")
    verdict = watched(lines_of(raised.value)).verdict(1, False)
    assert verdict.action == "settings" and "master_key_12" in verdict.text


def test_an_unknown_crash_asks_for_the_log():
    verdict = watched(lines_of(ZeroDivisionError("division by zero")), linking=False).verdict(1, False)
    assert verdict.action == "copy"


def test_a_keys_file_with_comments_and_a_typo_still_loads(tmp_path):
    """The parser before this crashed on any line without exactly one '='."""
    path = tmp_path / "prod.keys"
    path.write_text("﻿; dumped by Lockpick_RCM\n\n" + "".join(f"{n} = {'11' * 16}\n" for n in KEY_NAMES)
                    + f"broken_key = {'2' * 34}\n", encoding="utf-8")
    keys = ldn.load_keys(str(path))
    assert ldn.missing_keys(keys) == [] and "broken_key" not in keys


def test_a_damaged_settings_file_is_kept_and_its_good_fields_survive(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "BAD", tmp_path / "settings.json.bad")
    monkeypatch.setattr(settings, "damaged", None)
    original = {"ot": "RED", "tid": 1234, "sid": "oops", "tool_values": {"sv-host": {"values": {}}}}
    settings.PATH.write_text(json.dumps(original))
    loaded = settings.load()
    assert (loaded.ot, loaded.tid, loaded.tool_values) == ("RED", 1234, original["tool_values"])
    assert settings.damaged["fields"] == ["sid"] and json.loads(settings.BAD.read_text()) == original

    settings.PATH.write_text("{ truncated")
    settings.load()
    assert settings.damaged["fields"] == [] and settings.BAD.read_text() == "{ truncated"
    settings.load()                       # the app loads twice at launch; the notice must survive it
    assert settings.damaged is not None

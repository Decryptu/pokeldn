import os
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeldn.app import storage
from pokeldn.app.settings import Settings


@pytest.fixture
def local(tmp_path, monkeypatch):
    for name, folder in (("SESSION", "session"), ("LOGS", "logs"), ("POKEMON", "pokemon")):
        monkeypatch.setattr(storage, name, tmp_path / folder)
    monkeypatch.setattr(storage, "PATH", tmp_path / "settings.json")
    return Settings(received=str(tmp_path / "Received"), keys=str(tmp_path / "prod.keys"))


def put(path, data=b"saved", old=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if old:
        os.utime(path, (1, 1))
    return path


@pytest.mark.parametrize("received_folder", ["Received", "session/custom-received", "pokemon/received"])
def test_cleanup_reclaims_app_files_and_keeps_received_keys_firmware_and_saved_queues(local, received_folder):
    root = storage.PATH.parent
    local.received = str(root / received_folder)
    selected = put(storage.POKEMON / "sv/Pikachu-20260101-120000-11111111.pk9", b"queued")
    second = put(storage.POKEMON / "lgpe/Eevee-20260101-120000-22222222.pb7", b"second queued")
    gift = put(storage.SESSION / "selected.wc8", b"selected card")
    local.tool_values = {
        "sv-host": {"values": {"--trade-offer": [{"file": str(selected)}, {"file": str(second)}]},
                    "extra": {"--record": str(gift)}}}
    local.keys = str(put(storage.SESSION / "keys/custom.dat", b"keys"))
    local.firmware = str(put(storage.LOGS / "chosen.bin", b"firmware"))
    kept = [selected, second, gift, Path(local.keys), Path(local.firmware),
            put(Path(local.received) / "nested/received.pk9", b"received"),
            put(storage.SESSION / "other.keys", b"other keys"),
            put(storage.PATH, b"settings"), put(root / "sprites/normal/25.png", b"sprite"),
            put(storage.POKEMON / "sv/Onix-20260101-120000-33333333.pk9", b"recent build", old=False)]
    disposable = [put(storage.SESSION / "captures/session.jsonl", b"a" * 1200),
                  put(storage.SESSION / "captures/session.trace", b"b" * 3500),
                  put(storage.SESSION / "offers/sv-0123456789abcdef0123456789abcdef.pk9", b"c" * 344),
                  put(storage.SESSION / "lgpe_net_facts.json", b"facts"),
                  put(storage.LOGS / "old/session.log", b"d" * 700),
                  put(storage.POKEMON / "sv/Ditto-20260101-120000-44444444.pk9", b"e" * 344)]
    saved = {path: path.read_bytes() for path in kept}
    total = sum(p.stat().st_size for p in disposable)
    inventory = storage.scan(local)
    assert inventory.size == total and inventory.errors == 0
    cleared = storage.clear(inventory, local)
    assert (cleared.files, cleared.size, cleared.errors, cleared.skipped) == (6, total, 0, 0)
    assert not any(path.exists() for path in disposable)
    assert {path: path.read_bytes() for path in kept} == saved
    assert storage.SESSION.is_dir() and not (storage.SESSION / "captures").exists()
    assert storage.scan(local).files == ()


def test_cleanup_skips_symlinks_changed_files_and_selections_added_after_the_check(local):
    root = storage.PATH.parent
    outside = put(root / "personal/log.txt", b"personal file")
    storage.SESSION.mkdir()
    (storage.SESSION / "linked-folder").symlink_to(outside.parent, target_is_directory=True)
    (storage.SESSION / "linked.log").symlink_to(outside)
    storage.LOGS.symlink_to(outside.parent, target_is_directory=True)
    changed = put(storage.SESSION / "changed.log", b"old")
    selected = put(storage.POKEMON / "sv/Pikachu-20260101-120000-11111111.pk9", b"new selection")
    swapped = put(storage.SESSION / "swapped/log.txt", b"old log")
    inventory = storage.scan(local)
    assert len(inventory.files) == 3
    changed.write_bytes(b"appended after the space check")
    local.tool_values = {"sv-host": {"values": {"--trade-offer": {"file": str(selected)}}}}
    swapped.unlink()
    swapped.parent.rmdir()
    swapped.parent.symlink_to(outside.parent, target_is_directory=True)
    cleared = storage.clear(inventory, local)
    assert cleared.files == 0 and cleared.skipped == 3 and cleared.errors == 0
    assert outside.read_bytes() == b"personal file"
    assert changed.read_bytes() == b"appended after the space check"
    assert selected.read_bytes() == b"new selection"


def test_cleanup_reports_failed_deletions_and_can_retry_without_counting_missing_files(local, monkeypatch):
    blocked = put(storage.SESSION / "captures/locked.jsonl", b"record")
    gone = put(storage.LOGS / "gone.log", b"gone")
    inventory = storage.scan(local)
    gone.unlink()
    unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("file in use")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    result = storage.clear(inventory, local)
    assert result.errors == 1 and result.files == 0 and result.size == 0
    assert blocked.read_bytes() == b"record"
    monkeypatch.setattr(Path, "unlink", unlink)
    result = storage.clear(storage.scan(local), local)
    assert result.files == 1 and result.size == 6 and result.errors == 0


def test_missing_app_folders_need_no_cleanup(local):
    assert storage.scan(local) == storage.Inventory()
    assert storage.clear(storage.scan(local), local) == storage.Cleared()
    assert not storage.SESSION.exists()


def test_old_received_records_and_personal_files_survive_a_change_of_output_folder(local):
    saved = [put(storage.SESSION / "previous-received/pokemon.pk9", b"received"),
             put(storage.LOGS / "previous-dumps/save.bin", b"dump"),
             put(storage.POKEMON / "personal.pb7", b"personal"),
             put(storage.SESSION / "offers/received.pk9", b"received in offers")]
    record = put(storage.SESSION / "captures/old.jsonl", b"record")
    result = storage.clear(storage.scan(local), local)
    assert result.files == 1 and not record.exists()
    assert all(path.exists() for path in saved)


def test_every_format_written_by_the_builder_and_launcher_can_be_reclaimed(local, monkeypatch):
    from pokeldn import pokemon

    monkeypatch.setattr(pokemon, "POKEMON", storage.POKEMON)
    monkeypatch.setattr(pokemon, "SESSION", storage.SESSION)
    monkeypatch.setattr(pokemon, "prepare", lambda game, data, **_: data)
    monkeypatch.setattr(pokemon, "offer_bytes", lambda game, data: data)
    service = pokemon.Service()
    created = []
    for game in pokemon.EXTENSIONS:
        built = Path(service._save(game, {"species": "Pikachu", "data": base64.b64encode(b"record").decode()}))
        created.extend([built, Path(pokemon.prepare_file(game, str(built)))])
        os.utime(built, (1, 1))
    inventory = storage.scan(local)
    assert len(inventory.files) == 14
    result = storage.clear(inventory, local)
    assert result.files == 14 and result.size == 84
    assert not any(path.exists() for path in created)


def test_a_link_to_the_app_data_parent_keeps_the_custom_received_folder(local, monkeypatch):
    root = storage.PATH.parent
    alias = root / "linked-data"
    actual = root / "actual-data"
    actual.mkdir()
    alias.symlink_to(actual, target_is_directory=True)
    monkeypatch.setattr(storage, "SESSION", alias / "session")
    local.received = str(alias / "session/received")
    received = put(Path(local.received) / "pokemon.pk9", b"received")
    record = put(storage.SESSION / "captures/session.jsonl", b"record")
    result = storage.clear(storage.scan(local), local)
    assert result.files == 1 and result.size == 6
    assert received.read_bytes() == b"received" and not record.exists()


def test_settings_cleanup_requires_confirmation_and_rechecks_the_active_run(local, monkeypatch):
    pytest.importorskip("flet")
    from gui.app import App
    from gui.views.settings import SettingsView
    from gui.views import settings as settings_view

    dialogs = []
    app = App.__new__(App)
    app.settings, app.process, app.board_busy = local, None, False
    app.page = SimpleNamespace(show_dialog=dialogs.append, pop_dialog=lambda: dialogs.pop())
    app.ui = lambda fn: fn()
    view = SettingsView.__new__(SettingsView)
    view.app, view.shown, view.storage_work = app, True, False
    control = lambda: SimpleNamespace(value="", disabled=False, update=lambda: None)
    view.storage_state, view.storage_result, view.clear_button, view.control = [control() for _ in range(4)]
    record = put(storage.SESSION / "captures/session.jsonl", b"record")
    view.storage_inventory = storage.scan(local)
    view._clear_local(None)
    assert len(dialogs) == 1 and record.exists()
    dialogs[-1].actions[0].on_click(None)
    assert not dialogs and record.exists()
    view._clear_local(None)
    app.process = SimpleNamespace(running=True)
    dialogs[-1].actions[1].on_click(None)
    assert not dialogs and record.exists() and "Finish the current run" in view.storage_result.value
    view._clear_local(None)
    assert not dialogs and record.exists()
    app.process = None
    view._clear_local(None)

    class Worker:
        def __init__(self, target, **_):
            self.target = target

        def start(self):
            self.target()

    clear = storage.clear

    def guarded(inventory, settings):
        assert app.busy
        return clear(inventory, settings)

    monkeypatch.setattr(settings_view.threading, "Thread", Worker)
    monkeypatch.setattr(storage, "clear", guarded)
    dialogs[-1].actions[1].on_click(None)
    assert not record.exists() and not dialogs and not app.busy
    assert view.clear_button.disabled and "Freed 6 B" in view.storage_result.value

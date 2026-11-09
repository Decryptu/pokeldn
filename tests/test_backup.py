"""pokeldn.app.backup: a backup restored on a changed computer brings the player's files back, never
carries the console keys or plugin code, and a crafted zip is refused before anything is written."""
import json
import stat
import zipfile

import pytest

from pokeldn.app import backup, paths
from pokeldn.app import settings as settings_module


@pytest.fixture
def home(tmp_path, monkeypatch):
    folders = {}
    for name in ("POKEMON", "RECEIVED", "BANK", "SAVES", "GTS", "MACROS"):
        folders[name] = tmp_path / "home" / name.lower()
        folders[name].mkdir(parents=True)
        monkeypatch.setattr(paths, name, folders[name])
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "DATA", data)
    monkeypatch.setattr(settings_module, "PATH", data / "settings.json")
    monkeypatch.setattr(settings_module, "STAGED", data / "settings.restore.json")
    (data / "settings.json").write_text(json.dumps({"ot_name": "ASH", "keys": "/k/prod.keys"}))
    (folders["BANK"] / "frlg").mkdir()
    (folders["BANK"] / "frlg" / "Mew.pk3").write_bytes(b"\x01" * 80)
    (folders["SAVES"] / "FireRed.sav").write_bytes(b"\x02" * 131072)
    (folders["RECEIVED"] / "Pikachu.pk8").write_bytes(b"\x03" * 344)
    (folders["GTS"] / "listing").mkdir()
    (folders["GTS"] / "listing" / "key.json").write_text("{}")
    (folders["MACROS"] / "egg.pokemacro").write_text("A 100")
    (folders["SAVES"] / "prod.keys").write_text("header_key = 00")   # a player's keys in a save folder
    (data / "plugins" / "evil").mkdir(parents=True)
    (data / "plugins" / "evil" / "plugin.py").write_text("import os")
    return tmp_path, folders, data


def test_a_restore_brings_back_every_file_and_the_settings_at_next_launch(home):
    tmp, folders, data = home
    made = backup.create(tmp / "b.zip")
    with zipfile.ZipFile(tmp / "b.zip") as archive:
        names = set(archive.namelist())
    assert names == {backup.MANIFEST, backup.SETTINGS, "bank/frlg/Mew.pk3", "saves/FireRed.sav",
                     "received/Pikachu.pk8", "gts/listing/key.json", "macros/egg.pokemacro"}
    assert made.files == 6
    # The computer changes: a file is lost, one is edited, one is new, the settings move on.
    (folders["BANK"] / "frlg" / "Mew.pk3").unlink()
    (folders["SAVES"] / "FireRed.sav").write_bytes(b"\xff" * 10)
    (folders["BANK"] / "Eevee.pb7").write_bytes(b"\x04")
    (data / "settings.json").write_text(json.dumps({"ot_name": "GARY"}))
    restored = backup.restore(tmp / "b.zip", safety=tmp / "before.zip")
    assert restored.files == 6
    assert (folders["BANK"] / "frlg" / "Mew.pk3").read_bytes() == b"\x01" * 80
    assert (folders["SAVES"] / "FireRed.sav").read_bytes() == b"\x02" * 131072
    assert (folders["BANK"] / "Eevee.pb7").read_bytes() == b"\x04"            # files it does not hold stay
    assert json.loads((data / "settings.json").read_text())["ot_name"] == "GARY"   # the running app's
    assert settings_module.apply_staged()
    assert json.loads((data / "settings.json").read_text())["ot_name"] == "ASH"
    assert not settings_module.apply_staged()
    # The safety copy holds what the computer had before the restore.
    with zipfile.ZipFile(tmp / "before.zip") as archive:
        assert archive.read("saves/FireRed.sav") == b"\xff" * 10
        assert "bank/Eevee.pb7" in archive.namelist()


def evil(tmp, name, data=b"x", link=False):
    path = tmp / "evil.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(backup.MANIFEST, json.dumps({"format": backup.FORMAT}))
        info = zipfile.ZipInfo(name)
        info.compress_type = zipfile.ZIP_STORED
        if link:
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, data)
    return path


@pytest.mark.parametrize("name, link", [
    ("bank/../../escaped.pk3", False),
    ("/etc/escaped", False),
    ("plugins/evil/plugin.py", False),              # plugin code is never restored
    ("settings/other.json", False),
    ("bank\\..\\escaped.pk3", False),
    ("C:/escaped.pk3", False),
    ("bank/link.pk3", True),
    ("escaped.pk3", False),
])
def test_a_crafted_backup_is_refused_before_anything_is_written(home, name, link):
    tmp, folders, data = home
    before = sorted(p for p in tmp.rglob("*"))
    with pytest.raises(backup.BackupError):
        backup.restore(evil(tmp, name, link=link), safety=tmp / "before.zip")
    assert sorted(p for p in tmp.rglob("*") if p.name != "evil.zip") == before   # no safety copy either


def test_a_zip_bomb_a_damaged_file_and_a_foreign_zip_are_refused(home, monkeypatch):
    tmp, folders, _ = home
    monkeypatch.setattr(backup, "MAX_BYTES", 1_000_000)
    with pytest.raises(backup.BackupError, match="larger"):
        backup.inspect(evil(tmp, "bank/big.pk3", b"\0" * 5_000_000))
    damaged = bytearray(evil(tmp, "bank/Mew.pk3", b"\x05" * 80).read_bytes())
    damaged[damaged.index(b"bank/Mew.pk3") + 12] ^= 0xFF          # the member's first data byte
    (tmp / "damaged.zip").write_bytes(damaged)
    with pytest.raises(backup.BackupError):
        backup.restore(tmp / "damaged.zip")
    assert not (folders["BANK"] / "Mew.pk3").exists()
    assert not list(folders["BANK"].glob(".*restoring"))
    plain = tmp / "plain.zip"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("bank/a.pk3", b"x")
    with pytest.raises(backup.BackupError, match="not a pokeldn backup"):
        backup.inspect(plain)


def test_keys_in_a_backup_are_never_written(home):
    tmp, folders, _ = home
    backup.restore(evil(tmp, "saves/prod.keys", b"header_key = 11"))
    assert (folders["SAVES"] / "prod.keys").read_text() == "header_key = 00"


def test_a_restore_keeps_three_safety_copies(home, monkeypatch):
    tmp, _, data = home
    stamps = iter(f"before-restore-2026010{i}-000000.zip" for i in range(1, 7))
    monkeypatch.setattr(backup.time, "strftime", lambda fmt: next(stamps))
    for _ in range(5):
        backup.safety_path().write_bytes(b"z")
    assert sorted(p.name for p in (data / "backups").iterdir()) == [
        "before-restore-20260103-000000.zip", "before-restore-20260104-000000.zip",
        "before-restore-20260105-000000.zip"]

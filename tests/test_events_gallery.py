"""The app's EventsGallery copy (pokeldn.app.events_gallery): a git copy against a local repository
standing in for GitHub's, a zip copy against an archive laid out as GitHub's, the index of its raid
events, and where it lives. Nothing here reaches the network."""
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from pokeldn.app import events_gallery as gallery
from pokeldn.sv import raid_event

EVENT = f"{gallery.RAID_EVENTS}/001 Eevee Spotlight"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=pokeldn", "-c", "user.email=pokeldn@example.com",
                           "-c", "commit.gpgsign=false", "-c", "core.longpaths=true", *args], cwd=folder,
                          check=True, capture_output=True, text=True).stdout.strip()


def commit(remote: Path, path: str, data: bytes) -> None:
    target = remote / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    git(remote, "add", "-A")
    git(remote, "commit", "-q", "-m", f"change {path}")


def make_remote(remote: Path) -> Path:
    """A repository laid out as EventsGallery: a raid event's tables, text and JSON, another folder."""
    remote.mkdir(parents=True)
    git(remote, "init", "-q", "-b", gallery.BRANCH)
    git(remote, "config", "uploadpack.allowFilter", "true")         # a partial clone's, as GitHub's
    git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    for path, data in ((f"{EVENT}/Files/raid_enemy_array", b"v1"), (f"{EVENT}/Encounters.txt", b"text"),
                       (f"{EVENT}/Json/raid_enemy_array.json", b"{}"), ("Released/Gen 8/card.wc8", b"card")):
        (remote / path).parent.mkdir(parents=True, exist_ok=True)
        (remote / path).write_bytes(data)
    git(remote, "add", "-A")
    git(remote, "commit", "-q", "-m", "first")
    return remote


@needs_git
def test_a_git_copy_holds_the_raid_events_and_follows_their_changes_on_master(tmp_path, monkeypatch):
    remote = make_remote(tmp_path / "remote")
    monkeypatch.setattr(gallery, "GIT_URL", remote.as_uri())
    root = tmp_path / "app" / gallery.FOLDER
    found = gallery.download(root, use_git=True)
    assert (found.present, found.method, found.commit) == (True, "git", git(remote, "rev-parse", "HEAD"))
    assert (root / EVENT / "Files/raid_enemy_array").read_bytes() == b"v1"
    assert (root / EVENT / "Encounters.txt").is_file()
    # The JSON copies and the rest of the gallery stay on the remote.
    assert not (root / EVENT / "Json").exists() and not (root / "Released/Gen 8").exists()
    assert not gallery.check(root).available
    commit(remote, "Released/Gen 8/card.wc8", b"another card")
    assert not gallery.check(root).available
    commit(remote, f"{EVENT}/Files/raid_enemy_array", b"v2")
    newer = gallery.check(root)
    assert newer.available and newer.commit == git(remote, "rev-parse", "HEAD")
    gallery.take_update(root)
    assert (root / EVENT / "Files/raid_enemy_array").read_bytes() == b"v2"
    assert gallery.state(root).commit == newer.commit and not gallery.check(root).available


def test_a_zip_copy_keeps_the_tables_and_texts_and_downloads_again_to_update(tmp_path, monkeypatch):
    archive = tmp_path / "master.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for path, data in ((f"{EVENT}/Files/raid_enemy_array", b"v1"), (f"{EVENT}/Encounters.txt", b"text"),
                           (f"{EVENT}/Json/raid_enemy_array.json", b"{}"), ("Released/Gen 8/card.wc8", b"c")):
            z.writestr(f"EventsGallery-abc/{path}", data)
    latest, fetched = ["abc", "2026-09-06T21:05:05Z"], []

    def fetch(url, dest, progress, cancelled):
        fetched.append(url)
        shutil.copy(archive, dest)
        progress(10, 10)
        return ""
    monkeypatch.setattr(gallery, "_latest", lambda: tuple(latest))
    monkeypatch.setattr(gallery.update, "fetch", fetch)
    monkeypatch.setattr(gallery.paths, "DATA", tmp_path / "data")
    root = tmp_path / "app" / gallery.FOLDER
    found = gallery.download(root, use_git=False)
    assert (found.method, found.commit, found.date) == ("zip", "abc", "2026-09-06T21:05:05Z")
    assert fetched == [gallery.ZIP.format(commit="abc")]
    assert (root / EVENT / "Files/raid_enemy_array").read_bytes() == b"v1"
    assert (root / EVENT / "Encounters.txt").is_file()
    assert not (root / EVENT / "Json").exists() and not (root / "Released/Gen 8").exists()
    assert not (tmp_path / "data" / "gallery-download").exists()
    assert not gallery.check(root).available
    latest[:] = ["def", "2026-10-01T10:00:00Z"]
    assert gallery.check(root).available
    assert gallery.take_update(root).commit == "def" and len(fetched) == 2


def test_a_download_with_no_raid_events_leaves_the_copy_as_it_was(tmp_path, monkeypatch):
    archive = tmp_path / "master.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("EventsGallery-abc/README.md", "")
    monkeypatch.setattr(gallery, "_latest", lambda: ("abc", "2026-09-06T21:05:05Z"))
    monkeypatch.setattr(gallery.update, "fetch", lambda url, dest, progress, cancelled: shutil.copy(archive, dest))
    monkeypatch.setattr(gallery.paths, "DATA", tmp_path / "data")
    root = tmp_path / "app" / gallery.FOLDER
    (root / EVENT / "Files").mkdir(parents=True)
    with pytest.raises(OSError, match="no raid events"):
        gallery.download(root, use_git=False)
    assert (root / EVENT / "Files").is_dir()


def rows(*species):
    return tuple({"species": s, "rate": 1, "capture_rate": 2 if s == 6 else 1, "group": 1, "stars": 5,
                  "rom": 0} for s in species)


def test_the_index_lists_every_delivery_oldest_first_and_leaves_the_games_placeholder(tmp_path, monkeypatch):
    base = tmp_path / gallery.FOLDER / gallery.RAID_EVENTS
    for key in ("000 Base Data", "002 Charizard the Unrivaled", "001 Eevee Spotlight",
                "023 Great Tusk Spotlight/Round 2 (Fixed)", "023 Great Tusk Spotlight/Round 1 (Rewards bug)"):
        (base / key / "Files").mkdir(parents=True)
    (base / "024 Unreadable" / "Json").mkdir(parents=True)
    events = {"001": rows(133), "002": rows(6, 671, 778), "023": rows(984, 990)}
    # Each event's rows by its number; the placeholder and the unreadable folder are never read.
    monkeypatch.setattr(gallery.raid_event, "load", lambda folder: raid_event.Event(
        1, "", events[os.path.relpath(folder, gallery.long_path(base))[:3]], {}, {}, (1,) + (0,) * 9))
    found = gallery.index(tmp_path / gallery.FOLDER)
    assert [(e.key, e.title, e.number) for e in found] == [
        ("001 Eevee Spotlight", "Eevee Spotlight", 1),
        ("002 Charizard the Unrivaled", "Charizard the Unrivaled", 2),
        ("023 Great Tusk Spotlight/Round 1 (Rewards bug)", "Great Tusk Spotlight · Round 1 (Rewards bug)", 23),
        ("023 Great Tusk Spotlight/Round 2 (Fixed)", "Great Tusk Spotlight · Round 2 (Fixed)", 23)]
    assert (found[1].species, found[1].catch_once) == (("Charizard", "Florges", "Mimikyu"), ("Charizard",))


def test_the_gallery_lives_beside_the_packed_app_unless_it_cannot(tmp_path, monkeypatch):
    bundle, data = tmp_path / "_internal", tmp_path / "data"
    bundle.mkdir()
    monkeypatch.setattr(gallery.paths, "ROOT", str(bundle))
    monkeypatch.setattr(gallery.paths, "DATA", data)
    assert gallery.location(frozen=False) == bundle / gallery.FOLDER
    assert gallery.location(frozen=True, system="win32") == bundle / gallery.FOLDER
    assert gallery.location(frozen=True, system="darwin") == data / gallery.FOLDER   # a signed bundle
    monkeypatch.setattr(gallery.update, "writable", lambda folder: False)
    assert gallery.location(frozen=True, system="linux") == data / gallery.FOLDER
    (data / gallery.FOLDER).mkdir(parents=True)
    monkeypatch.setattr(gallery.update, "writable", lambda folder: True)
    assert gallery.location(frozen=True, system="win32") == data / gallery.FOLDER     # the copy there stays


def test_an_event_folder_is_named_past_windows_260_characters(tmp_path):
    deep = tmp_path / ("x" * 120) / ("y" * 120)
    named = gallery.event_path("108 Round 2", deep)
    if os.name == "nt":
        assert named.startswith("\\\\?\\") and named.endswith(os.path.join(gallery.RAID_EVENTS.replace("/", os.sep),
                                                                           "108 Round 2"))
    else:
        assert named == os.path.abspath(deep / gallery.RAID_EVENTS / "108 Round 2")

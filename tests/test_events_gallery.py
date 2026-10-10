"""The app's copy of the EventsGallery's raid events (pokeldn.app.events_gallery): unpacked from an
archive laid out as GitHub's zip of the gallery, updated, and indexed. Nothing here reaches the network."""
import os
import shutil
import zipfile

import pytest

from pokeldn.app import events_gallery as gallery
from pokeldn.app import update
from pokeldn.sv import raid_event

EVENTS = gallery.RAID_EVENTS
EEVEE, ROUND = "001 Eevee Spotlight", "023 Great Tusk Spotlight/Round 2 (Fixed)"


def archive(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(f"EventsGallery-abc/{name}", data)
    return path


def serve(monkeypatch, latest, zips):
    """GitHub answering `latest` (commit, date) and the zip of each commit; -> the URLs fetched."""
    fetched = []

    def fetch(url, dest, progress, cancelled):
        fetched.append(url)
        if cancelled():
            raise update.Cancelled
        shutil.copy(zips[url.rsplit("/", 1)[1]], dest)
        progress(10, 10)
        return ""
    monkeypatch.setattr(gallery, "_latest", lambda: tuple(latest))
    monkeypatch.setattr(gallery.update, "fetch", fetch)
    return fetched


def test_a_copy_keeps_each_event_s_newest_tables_and_follows_master(tmp_path, monkeypatch):
    tables = {f"{EVENTS}/{EEVEE}/Files/{t}{p}": f"{t}{p}".encode()
              for t in gallery.TABLES for p in ("", "_1_3_0")}
    first = archive(tmp_path / "abc.zip", {
        **tables, f"{EVENTS}/{EEVEE}/Files/event_raid_identifier_1_3_0": b"id",
        f"{EVENTS}/{EEVEE}/Encounters.txt": b"text", f"{EVENTS}/{EEVEE}/Json/raid_enemy_array.json": b"{}",
        f"{EVENTS}/{ROUND}/Files/raid_enemy_array": b"round", f"{EVENTS}/000 Base Data/Files/raid_enemy_array": b"",
        "Released/Gen 8/card.wc8": b"card"})
    latest = ["abc", "2026-09-06T21:05:05Z"]
    fetched = serve(monkeypatch, latest, {"abc": first})
    root = tmp_path / "data" / gallery.FOLDER
    found = gallery.download(root)
    assert (found.present, found.commit, found.date) == (True, "abc", "2026-09-06T21:05:05Z")
    assert fetched == [gallery.ZIP.format(commit="abc")]
    kept = sorted(str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*") if p.is_file())
    assert kept == sorted([gallery.MANIFEST, f"{ROUND}/Files/raid_enemy_array",
                           *(f"{EEVEE}/Files/{t}_1_3_0" for t in gallery.TABLES)])
    assert gallery.holds(EEVEE, root) and gallery.holds(ROUND, root) and not gallery.holds("000 Base Data", root)
    assert sorted(p.name for p in root.parent.iterdir()) == [gallery.FOLDER]
    assert not gallery.check(root).available
    latest[:] = ["def", "2026-10-01T10:00:00Z"]
    assert gallery.check(root).available
    serve(monkeypatch, latest, {"def": archive(tmp_path / "def.zip", {
        f"{EVENTS}/{EEVEE}/Files/raid_enemy_array_2_0_0": b"newer"})})
    assert gallery.download(root).commit == "def" and not gallery.check(root).available
    assert not gallery.holds(ROUND, root)
    assert (root / EEVEE / "Files/raid_enemy_array_2_0_0").read_bytes() == b"newer"


@pytest.mark.parametrize("cancel", [False, True])
def test_a_failed_download_leaves_the_copy_as_it_was(tmp_path, monkeypatch, cancel):
    empty = archive(tmp_path / "abc.zip", {"README.md": b""})
    serve(monkeypatch, ("abc", "2026-09-06T21:05:05Z"), {"abc": empty})
    root = tmp_path / "data" / gallery.FOLDER
    (root / EEVEE / "Files").mkdir(parents=True)
    with pytest.raises(update.Cancelled if cancel else OSError):
        gallery.download(root, cancelled=lambda: cancel)
    assert gallery.holds(EEVEE, root) and sorted(p.name for p in root.parent.iterdir()) == [gallery.FOLDER]


def rows(*species):
    return tuple({"species": s, "rate": 1, "capture_rate": 2 if s == 6 else 1, "group": 1, "stars": 5,
                  "rom": 0} for s in species)


def test_the_index_lists_every_delivery_oldest_first(tmp_path, monkeypatch):
    root = tmp_path / gallery.FOLDER
    for key in ("002 Charizard the Unrivaled", EEVEE, ROUND, "023 Great Tusk Spotlight/Round 1 (Rewards bug)"):
        (root / key / "Files").mkdir(parents=True)
    (root / "024 Unreadable" / "Json").mkdir(parents=True)
    events = {"001": rows(133), "002": rows(6, 671, 778), "023": rows(984, 990)}
    # Each event's rows by its number; the folder without Files is never read.
    monkeypatch.setattr(gallery.raid_event, "load", lambda folder: raid_event.Event(
        1, "", events[os.path.relpath(folder, gallery.long_path(root))[:3]], {}, {}, (1,) + (0,) * 9))
    found = gallery.index(root)
    assert [(e.key, e.title, e.number) for e in found] == [
        (EEVEE, "Eevee Spotlight", 1),
        ("002 Charizard the Unrivaled", "Charizard the Unrivaled", 2),
        ("023 Great Tusk Spotlight/Round 1 (Rewards bug)", "Great Tusk Spotlight · Round 1 (Rewards bug)", 23),
        (ROUND, "Great Tusk Spotlight · Round 2 (Fixed)", 23)]
    assert (found[1].species, found[1].catch_once) == (("Charizard", "Florges", "Mimikyu"), ("Charizard",))


def test_an_event_folder_is_named_past_windows_260_characters(tmp_path):
    deep = tmp_path / ("x" * 120) / ("y" * 120)
    named = gallery.event_path(ROUND, deep)
    if os.name == "nt":
        assert named.startswith("\\\\?\\") and named.endswith(ROUND.replace("/", os.sep))
    else:
        assert named == os.path.abspath(deep / ROUND)

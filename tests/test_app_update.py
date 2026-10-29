import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from pokeldn.app import update

ROOT = Path(__file__).resolve().parent.parent


def test_every_platform_points_at_an_archive_the_release_workflow_publishes():
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    published = set(re.findall(r"^\s+asset: (\S+)$", workflow, re.M))
    assert set(update.ASSETS.values()) == published


def release(tag, **extra):
    return {"tag_name": tag, "html_url": f"https://github.com/Decryptu/pokeldn/releases/tag/{tag}",
            "assets": [{"name": n, "browser_download_url": f"https://example.invalid/{tag}/{n}"}
                       for n in update.ASSETS.values()], **extra}


@pytest.mark.parametrize("tag, current, offered", [
    ("v0.10.0", "0.9.9", "0.10.0"),     # numeric, not string, order
    ("v1.0.0", "0.2.2", "1.0.0"),
    ("v0.2.2", "0.2.2", None),
    ("v0.2.1", "0.2.2", None),
    ("v0.3.0-rc1", "0.2.2", None),      # a pre-release tag is never offered
    ("nightly", "0.2.2", None),
    ("v0.3.0", "0.3.0.dev1", None),     # a source checkout with an odd version is never nagged
])
def test_only_a_higher_stable_version_is_offered(tag, current, offered):
    found = update.newer(release(tag), current, "pokeldn-windows-x64.zip")
    assert (found.version if found else None) == offered


def test_a_release_github_marks_prerelease_or_draft_is_not_offered():
    assert update.newer(release("v9.0.0", prerelease=True), "0.2.2", "") is None
    assert update.newer(release("v9.0.0", draft=True), "0.2.2", "") is None


@pytest.mark.parametrize("system, machine, name", [
    ("darwin", "arm64", "pokeldn-macos-arm64.zip"),
    ("win32", "AMD64", "pokeldn-windows-x64.zip"),
    ("linux", "x86_64", "pokeldn-linux-x64.tar.gz"),
    ("darwin", "x86_64", ""),           # no Intel Mac build: the release page instead
])
def test_the_download_is_this_machines_file_or_the_release_page(system, machine, name):
    found = update.newer(release("v9.0.0"), "0.2.2", update.asset_name(system, machine))
    assert found.download == (f"https://example.invalid/v9.0.0/{name}" if name else found.page)


@pytest.fixture
def github():
    """A local stand-in for the releases endpoint; set .reply to (status, body bytes)."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = server.reply
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True).start()
    server.url = f"http://127.0.0.1:{server.server_port}/releases/latest"
    yield server
    server.shutdown()
    server.server_close()


def test_check_reads_githubs_reply(github):
    github.reply = (200, json.dumps(release("v9.0.0")).encode())
    assert update.check(github.url, "0.2.2").version == "9.0.0"
    assert update.check(github.url, "9.0.0") is None


@pytest.mark.parametrize("status, body", [(404, b"{}"), (403, b"rate limited"), (200, b"<html>"),
                                          (200, b"[]")])
def test_no_usable_answer_is_an_error_not_up_to_date(github, status, body):
    github.reply = (status, body)
    with pytest.raises(OSError):
        update.check(github.url, "0.2.2")


# --- Installing in place: a release served locally, downloaded, checked, unpacked and swapped in. ---

def packed_app(folder: Path, system: str, version: str) -> Path:
    """A stand-in for scripts/pack_app.py's output: the layout the release workflow archives."""
    root = folder / ("pokeldn.app" if system == "darwin" else "pokeldn")
    exe = update.executable_in(root, system)
    exe.parent.mkdir(parents=True)
    exe.write_text(f"#!/bin/sh\necho {version}\n")
    exe.chmod(0o755)
    (root / "VERSION").write_text(version)
    if system == "darwin":
        (root / "Contents/Frameworks").mkdir()
        (root / "Contents/Frameworks/Current").symlink_to("../MacOS")
    return root


def archive(folder: Path, system: str, version: str) -> Path:
    """The archive the release workflow makes: ditto --keepParent, Compress-Archive, tar -C dist ."""
    dist = folder / "dist"
    root = packed_app(dist, system, version)
    name = update.ASSETS[{"darwin": ("darwin", "arm64"), "win32": ("win32", "x64"),
                          "linux": ("linux", "x64")}[system]]
    out = folder / name
    if system == "darwin":
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(root), str(out)], check=True)
    elif system == "win32":
        with zipfile.ZipFile(out, "w") as z:
            for path in sorted(root.rglob("*")):
                z.write(path, path.relative_to(dist).as_posix())
    else:
        with tarfile.open(out, "w:gz") as tar:
            tar.add(dist, ".")
    return out


SYSTEMS = ["win32", "linux"] + (["darwin"] if sys.platform == "darwin" else [])


@pytest.fixture
def files():
    """A local file server; set .files to {path: bytes}."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = server.files.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.files = {}
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True).start()
    server.base = f"http://127.0.0.1:{server.server_port}"
    yield server
    server.shutdown()
    server.server_close()


def serve(files, tmp_path, system, sums=None) -> update.Release:
    built = archive(tmp_path / "release", system, "9.0.0")
    data = built.read_bytes()
    files.files[f"/{built.name}"] = data
    files.files["/SHA256SUMS"] = (sums if sums is not None else
                                  f"{hashlib.sha256(data).hexdigest()}  {built.name}\n".encode())
    return update.Release("9.0.0", files.base + "/page", f"{files.base}/{built.name}", files.base + "/SHA256SUMS")


def exited_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


@pytest.mark.parametrize("system", SYSTEMS)
def test_a_release_replaces_the_installed_app_and_opens_it(files, tmp_path, system):
    release = serve(files, tmp_path, system)
    target = packed_app(tmp_path / "Applications", system, "0.1.0")
    (target / "stale-from-0.1.0").write_text("")
    work, outcome, opened = tmp_path / "data/update", tmp_path / "data/update/outcome.json", []
    seen = []
    new = update.prepare(release, lambda done, total: seen.append((done, total)), work=work, system=system)
    assert seen[-1][0] == seen[-1][1] == len(files.files[release.download[len(files.base):]])

    assert update.apply(new, target, exited_pid(), "9.0.0", system, outcome, opened.append)
    assert opened == [target]
    assert (target / "VERSION").read_text() == "9.0.0"
    assert not (target / "stale-from-0.1.0").exists()
    assert os.access(update.executable_in(target, system), os.X_OK) or system == "win32"
    if system == "darwin":
        assert (target / "Contents/Frameworks/Current").is_symlink()
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]   # no .old left behind
    (work / update.READY.name).touch()
    assert update.finish(target, outcome, work) == {"version": "9.0.0", "error": "", "helper": None}
    assert not (work / update.READY.name).exists()
    assert update.finish(target, outcome, work) is None                      # shown once
    assert not (work / "new").exists()


@pytest.mark.parametrize("sums", [b"", b"0" * 64 + b"  pokeldn-other.zip\n", b"f" * 64 + b"  NAME\n"])
def test_an_archive_sha256sums_does_not_vouch_for_is_never_unpacked(files, tmp_path, sums):
    name = update.ASSETS[("linux", "x64")]
    release = serve(files, tmp_path, "linux", sums.replace(b"NAME", name.encode()))
    with pytest.raises(OSError, match="SHA256SUMS|SHA-256"):
        update.prepare(release, work=tmp_path / "update", system="linux")
    assert not (tmp_path / "update/new").exists() and not (tmp_path / "update" / name).exists()


def test_a_failed_copy_puts_the_old_app_back_and_says_why(files, tmp_path):
    new = packed_app(tmp_path / "update/new", "linux", "9.0.0")
    update.executable_in(new, "linux").unlink()       # a copy that lands without its executable
    target = packed_app(tmp_path / "Applications", "linux", "0.1.0")
    outcome, opened = tmp_path / "outcome.json", []
    assert not update.apply(new, target, exited_pid(), "9.0.0", "linux", outcome, opened.append)
    assert opened == [target] and (target / "VERSION").read_text() == "0.1.0"
    assert update.executable_in(target, "linux").is_file()
    assert "could not copy" in json.loads(outcome.read_text())["error"]


def test_the_helper_waits_for_the_old_app_to_quit(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "EXIT_WAIT", 0.5)
    running = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        target = packed_app(tmp_path / "Applications", "linux", "0.1.0")
        new = packed_app(tmp_path / "update/new", "linux", "9.0.0")
        assert not update.apply(new, target, running.pid, "9.0.0", "linux", tmp_path / "o.json", lambda r: None)
        assert (target / "VERSION").read_text() == "0.1.0"
    finally:
        running.kill()
        running.wait()


@pytest.mark.parametrize("executable, system, root", [
    ("/Applications/pokeldn.app/Contents/MacOS/pokeldn", "darwin", "/Applications/pokeldn.app"),
    ("/Users/x/Downloads/pokeldn/pokeldn", "darwin", None),
    ("/opt/pokeldn/pokeldn", "linux", "/opt/pokeldn"),
])
def test_the_installed_app_is_the_folder_the_archive_unpacked(executable, system, root):
    found = update.install_root(executable, True, system)
    assert (str(found) if found else None) == (str(Path(root).resolve()) if root else None)
    assert update.install_root(executable, False, system) is None


def test_a_copy_that_cannot_replace_itself_falls_back_to_the_download(tmp_path):
    assert update.blocker(None)
    assert "Applications" in update.blocker(Path("/private/var/folders/x/AppTranslocation/y/d/pokeldn.app"))
    root = packed_app(tmp_path, "linux", "0.1.0")
    assert update.blocker(root) == ""
    if os.name == "posix" and os.geteuid() != 0:
        tmp_path.chmod(0o555)
        try:
            assert "cannot write" in update.blocker(root)
        finally:
            tmp_path.chmod(0o755)


def test_a_drive_root_that_refuses_files_updates_without_the_administrator(tmp_path, monkeypatch):
    """The root of a fresh NTFS volume lets users create folders, not files; the swap needs only folders."""
    root = packed_app(tmp_path, "win32", "0.1.0")
    write = Path.write_bytes

    def refuse_in_root(path, data):
        if path.parent == tmp_path:
            raise PermissionError(13, "Access is denied", str(path))
        return write(path, data)
    monkeypatch.setattr(Path, "write_bytes", refuse_in_root)
    assert not update.needs_admin(root, "win32")
    assert update.blocker(root, "win32") == ""
    assert not list(tmp_path.glob(".pokeldn-write-*"))


def test_a_release_without_sha256sums_is_not_installed_in_place():
    reply = release("v9.0.0")
    assert not update.newer(reply, "0.2.2", "pokeldn-linux-x64.tar.gz").installable
    reply["assets"].append({"name": "SHA256SUMS", "browser_download_url": "https://example.invalid/SHA256SUMS"})
    assert update.newer(reply, "0.2.2", "pokeldn-linux-x64.tar.gz").installable
    assert not update.newer(reply, "0.2.2", "").installable                 # no file for this machine


def test_the_new_app_leaves_the_helpers_folder_until_the_helper_has_closed(tmp_path):
    work = tmp_path / "update"
    new = packed_app(work / "new", "linux", "9.0.0")
    target = packed_app(tmp_path / "Applications", "linux", "0.1.0")
    helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert update.apply(new, target, exited_pid(), "9.0.0", "linux", work / "outcome.json",
                            lambda r: None, helper=helper.pid)
        assert update.finish(target, work / "outcome.json", work)["helper"] == helper.pid
        assert not (work / "outcome.json").exists()          # the helper's signal to close its window
        assert new.exists()
    finally:
        helper.kill()
        helper.wait()
    assert update.wait_for(lambda: not new.exists(), 5.0)


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in app is a shell script")
@pytest.mark.filterwarnings("ignore::ResourceWarning", "ignore::pytest.PytestUnraisableExceptionWarning")
def test_the_helper_never_runs_inside_the_folder_it_renames(tmp_path, monkeypatch):
    # Windows refuses to rename a folder that is any process's working folder; Explorer starts the
    # old app with its own folder as one, and the helper inherited it.
    target = packed_app(tmp_path / "Applications", "linux", "0.1.0")
    new = packed_app(tmp_path / "data/update/new", "linux", "9.0.0")
    seen = tmp_path / "helper_cwd"
    update.executable_in(new, "linux").write_text(f"#!/bin/sh\npwd -P > '{seen}'\n")
    monkeypatch.chdir(target)
    update.start_swap(new, target, "9.0.0", "linux")
    assert update.wait_for(lambda: seen.exists() and seen.read_text().strip(), 10.0)
    helper_cwd = Path(seen.read_text().strip())
    assert target.resolve() not in (helper_cwd, *helper_cwd.parents)


def test_the_administrators_helper_gets_the_folder_behind_a_drive_letter(tmp_path, monkeypatch):
    # A subst or mapped letter exists only in the user's logon session, not the elevated one; a
    # symlink stands in for the letter here.
    real = packed_app(tmp_path / "real", "win32", "0.1.0")
    (tmp_path / "S").symlink_to(tmp_path / "real")
    new = packed_app(tmp_path / "data/update/new", "win32", "9.0.0")
    started = []
    monkeypatch.setattr(update, "_run_as_admin", lambda exe, args, cwd, folder: started.append(args))
    update.start_swap(new, tmp_path / "S" / real.name, "9.0.0", "win32", admin=True)
    assert started[0][2] == str(real.resolve())


@pytest.mark.parametrize("system", SYSTEMS)
@pytest.mark.parametrize("limit", ["bytes", "files", "file"])
def test_update_archives_are_bounded_before_extraction(tmp_path, monkeypatch, system, limit):
    built = archive(tmp_path / "release", system, "9.0.0")
    monkeypatch.setattr(update, {"bytes": "MAX_UNPACKED", "files": "MAX_FILES", "file": "MAX_FILE"}[limit], 1)
    output = tmp_path / "unpacked"
    with pytest.raises(OSError, match="large|oversized|many files"):
        update.unpack(built, output, system)
    assert not output.exists()


@pytest.mark.parametrize("name", ["../outside", "..\\outside", "C:/outside", "pokeldn/CON.exe"])
def test_update_zip_paths_cannot_escape_on_any_platform(tmp_path, name):
    built = tmp_path / "hostile.zip"
    with zipfile.ZipFile(built, "w") as z:
        z.writestr(name, b"test")
    with pytest.raises(OSError, match="unsafe path"):
        update.unpack(built, tmp_path / "unpacked", "win32")
    assert not (tmp_path / "outside").exists()


def test_update_tar_links_cannot_redirect_extraction_outside_the_folder(tmp_path):
    import io
    built = tmp_path / "hostile.tar.gz"
    with tarfile.open(built, "w:gz") as tar:
        link = tarfile.TarInfo("pokeldn/link")
        link.type, link.linkname = tarfile.SYMTYPE, "../../outside"
        tar.addfile(link)
        child = tarfile.TarInfo("pokeldn/link/file")
        child.size = 4
        tar.addfile(child, io.BytesIO(b"test"))
    with pytest.raises(OSError, match="unsafe path|through a link"):
        update.unpack(built, tmp_path / "unpacked", "linux")
    assert not (tmp_path / "outside").exists()


def test_update_links_cannot_form_a_cycle_or_hide_a_child_write(tmp_path):
    for child in (False, True):
        built = tmp_path / "hostile.zip"
        with zipfile.ZipFile(built, "w") as z:
            for name, target in [("pokeldn.app/a", "b"), ("pokeldn.app/b", "a")]:
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o120777 << 16)
                z.writestr(info, target)
            if child:
                z.writestr("pokeldn.app/a/file", b"test")
        with pytest.raises(OSError, match="link cycle|through a link"):
            update.unpack(built, tmp_path / "unpacked", "darwin")


def test_update_rejects_files_from_a_different_release_source_before_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "_open", lambda *a: pytest.fail("must not download"))
    release = update.Release("9.0.0", "https://github.com/Decryptu/pokeldn/releases/tag/v9.0.0",
                             "https://evil.example/pokeldn-windows-x64.zip", "https://evil.example/SHA256SUMS")
    with pytest.raises(OSError, match="not from"):
        update.prepare(release, work=tmp_path / "update", system="win32")
    assert not (tmp_path / "update").exists()


@pytest.mark.parametrize("url", ["file:///tmp/file", "http://example.com/file", "ftp://example.com/file"])
def test_downloads_require_https_or_loopback_http(url):
    with pytest.raises(OSError, match="HTTPS"):
        update._open(url)


def test_response_size_and_total_time_are_bounded(monkeypatch):
    import io
    with pytest.raises(OSError, match="too large"):
        update.read_bytes(io.BytesIO(b"x" * 11), 10)
    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(update.time, "monotonic", lambda: next(times))
    with pytest.raises(OSError, match="too long"):
        update.read_bytes(io.BytesIO(b"small"), 100, timeout=1)


def test_download_redirects_cannot_downgrade_to_external_http(files):
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/unsafe")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True).start()
    try:
        with pytest.raises(OSError, match="unsafe address"):
            update._open(f"http://127.0.0.1:{server.server_port}/redirect")
    finally:
        server.shutdown()
        server.server_close()


def test_zip_directory_limits_apply_before_python_builds_the_file_index(tmp_path, monkeypatch):
    from pokeldn.app import archives
    built = tmp_path / "many.zip"
    with zipfile.ZipFile(built, "w") as z:
        for i in range(5):
            z.writestr(str(i), b"")
    monkeypatch.setattr(archives.zipfile, "ZipFile", lambda *a: pytest.fail("must reject before indexing"))
    with pytest.raises(OSError, match="many files"):
        archives.open_zip(built, 2)

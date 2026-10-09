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
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
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

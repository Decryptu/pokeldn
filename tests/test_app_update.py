import json
import re
import threading
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
    found = update.newer(release(tag), current, "pokeldn-windows-x64.exe")
    assert (found.version if found else None) == offered


def test_a_release_github_marks_prerelease_or_draft_is_not_offered():
    assert update.newer(release("v9.0.0", prerelease=True), "0.2.2", "") is None
    assert update.newer(release("v9.0.0", draft=True), "0.2.2", "") is None


@pytest.mark.parametrize("system, machine, name", [
    ("darwin", "arm64", "pokeldn-macos-arm64.zip"),
    ("win32", "AMD64", "pokeldn-windows-x64.exe"),
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

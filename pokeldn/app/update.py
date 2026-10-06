"""Whether GitHub has a newer pokeldn release than this app, and which of its files fits this machine.

Never waits longer than TIMEOUT; no answer from GitHub raises OSError. docs/gui.md (Updates).
"""
import json
import os
import platform
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from pokeldn import __version__
from pokeldn.app.sprites import _context

LATEST = os.environ.get("POKELDN_UPDATE_URL",
                        "https://api.github.com/repos/Decryptu/pokeldn/releases/latest")
TIMEOUT = 5.0
MAX_BYTES = 1_000_000
# The archive names .github/workflows/release.yml publishes; tests/test_app_update.py pins them.
ASSETS = {("darwin", "arm64"): "pokeldn-macos-arm64.zip",
          ("win32", "x64"): "pokeldn-windows-x64.zip",
          ("linux", "x64"): "pokeldn-linux-x64.tar.gz"}


@dataclass(frozen=True)
class Release:
    version: str
    page: str        # the release page, with its notes
    download: str    # this machine's file, or the release page when none fits


def parse(version: str) -> tuple[int, ...] | None:
    """(0, 10, 2) for "v0.10.2"; None for a pre-release ("0.3.0-rc1") or anything else."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def asset_name(system: str = sys.platform, machine: str = platform.machine()) -> str:
    arch = "arm64" if machine.lower() in ("arm64", "aarch64") else "x64"
    return ASSETS.get(("linux" if system.startswith("linux") else system, arch), "")


def newer(reply: dict, current: str = __version__, name: str | None = None) -> Release | None:
    """The release GitHub described, if it is a stable version above current."""
    tag, page = reply.get("tag_name"), reply.get("html_url")
    if not isinstance(tag, str) or not isinstance(page, str) or reply.get("draft") or reply.get("prerelease"):
        return None
    theirs, ours = parse(tag), parse(current)
    if theirs is None or ours is None or theirs <= ours:
        return None
    name = asset_name() if name is None else name
    files = {a.get("name"): a.get("browser_download_url") for a in reply.get("assets") or []
             if isinstance(a, dict)}
    download = files.get(name)
    return Release(".".join(map(str, theirs)), page, download if isinstance(download, str) else page)


def check(url: str = LATEST, current: str = __version__) -> Release | None:
    """A newer release, or None when this app is the latest."""
    request = urllib.request.Request(url, headers={"User-Agent": "pokeldn-desktop",
                                                   "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=_context()) as reply:
            data = json.loads(reply.read(MAX_BYTES))
    except urllib.error.HTTPError as error:
        error.close()   # an HTTPError keeps its socket open until closed
        raise
    except ValueError as error:
        raise OSError(f"GitHub sent no release: {error}") from error
    if not isinstance(data, dict):
        raise OSError("GitHub sent no release")
    return newer(data, current)

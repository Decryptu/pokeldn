"""Whether GitHub has a newer pokeldn release than this app, and installing it in place.

Never waits longer than TIMEOUT for the check; no answer from GitHub raises OSError. The install
downloads this machine's archive, checks it against the release's SHA256SUMS, unpacks it, and hands
the swap to the new app (`--apply-update`) once this one has quit. docs/gui.md (Updates).
"""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pokeldn import __version__
from pokeldn.app.paths import DATA
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
    checksums: str = ""   # the release's SHA256SUMS; without it nothing is installed in place

    @property
    def installable(self) -> bool:
        return bool(self.checksums) and self.download != self.page


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
    download, sums = files.get(name), files.get("SHA256SUMS")
    return Release(".".join(map(str, theirs)), page, download if isinstance(download, str) else page,
                   sums if isinstance(sums, str) else "")


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


# --- Installing in place -----------------------------------------------------------------------------

WORK = DATA / "update"           # the download, the unpacked app and the helper's log and outcome
OUTCOME = WORK / "outcome.json"
READY = WORK / "helper.ready"    # the helper's window is up; the old app may close its own
MAX_ARCHIVE = 600_000_000
EXIT_WAIT = 120.0                # how long the helper waits for the old app to quit
RENAME_WAIT = 30.0               # Windows keeps a quitting exe's folder locked for a moment


class Cancelled(Exception):
    pass


def install_root(executable: str = sys.executable, frozen: bool = bool(getattr(sys, "frozen", False)),
                 system: str = sys.platform) -> Path | None:
    """The folder a packed app was unpacked as: pokeldn.app on macOS, the pokeldn folder elsewhere."""
    if not frozen:
        return None
    exe = Path(executable).resolve()
    if system == "darwin":
        root = exe.parents[2]
        return root if root.suffix == ".app" and exe.parent.name == "MacOS" else None
    return exe.parent


def executable_in(root: Path, system: str = sys.platform) -> Path:
    if system == "darwin":
        return root / "Contents" / "MacOS" / "pokeldn"
    return root / ("pokeldn.exe" if system == "win32" else "pokeldn")


def _writable(folder: Path) -> bool:
    # os.access on Windows reads only the read-only attribute, never the folder's ACL: create a file.
    probe = folder / f".pokeldn-write-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def blocker(root: Path | None) -> str:
    """Why this copy of the app cannot replace itself, or "" when it can."""
    if root is None:
        return "Only the packed app updates itself."
    if "AppTranslocation" in root.parts:
        # macOS runs a quarantined app from Downloads out of a random read-only copy.
        return "Move pokeldn to your Applications folder, open it from there, then update."
    if not (_writable(root.parent) and _writable(root)):
        return f"pokeldn cannot write to {root.parent}."
    return ""


def checksums(text: str) -> dict[str, str]:
    """sha256sum's lines, "<hex>  <name>" (a "*" before the name marks binary mode)."""
    found = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](\S.*)", line.strip())
        if match:
            found[match.group(2)] = match.group(1).lower()
    return found


def _open(url: str, timeout: float = 30.0):
    request = urllib.request.Request(url, headers={"User-Agent": "pokeldn-desktop"})
    return urllib.request.urlopen(request, timeout=timeout, context=_context())


def fetch(url: str, dest: Path, progress: Callable[[int, int], None] = lambda done, total: None,
          cancelled: Callable[[], bool] = lambda: False) -> str:
    """Downloads url to dest; returns its SHA-256. A partial file is removed."""
    digest, done = hashlib.sha256(), 0
    try:
        with _open(url) as reply, dest.open("wb") as out:
            total = int(reply.headers.get("Content-Length") or 0)
            if total > MAX_ARCHIVE:
                raise OSError(f"the download is {total} bytes")
            while chunk := reply.read(1 << 18):
                if cancelled():
                    raise Cancelled
                done += len(chunk)
                if done > MAX_ARCHIVE:
                    raise OSError("the download is too large")
                digest.update(chunk)
                out.write(chunk)
                progress(done, total)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def unpack(archive: Path, folder: Path, system: str = sys.platform) -> Path:
    """Unpacks the release archive into an empty folder; returns the app inside it."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as tar:
            tar.extractall(folder, filter="data")
    elif system == "darwin":
        # ditto wrote the zip; it alone restores the bundle's symlinks and modes.
        subprocess.run(["ditto", "-x", "-k", str(archive), str(folder)], check=True, capture_output=True)
    else:
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)
    root = folder / ("pokeldn.app" if system == "darwin" else "pokeldn")
    if not executable_in(root, system).is_file():
        raise OSError(f"the archive holds no {executable_in(root, system).relative_to(folder)}")
    return root


def prepare(release: Release, progress: Callable[[int, int], None] = lambda done, total: None,
            cancelled: Callable[[], bool] = lambda: False, work: Path = WORK,
            system: str = sys.platform) -> Path:
    """Downloads, checks and unpacks the release; returns the new app, ready for start_swap."""
    if not release.installable:
        raise OSError("the release has no file for this computer or no SHA256SUMS")
    name = release.download.rsplit("/", 1)[-1]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    with _open(release.checksums) as reply:
        expected = checksums(reply.read(MAX_BYTES).decode("utf-8", "replace")).get(name)
    if not expected:
        raise OSError(f"SHA256SUMS does not list {name}")
    archive = work / name
    if fetch(release.download, archive, progress, cancelled) != expected:
        archive.unlink(missing_ok=True)
        raise OSError(f"{name} does not match its SHA-256 in SHA256SUMS")
    try:
        return unpack(archive, work / "new", system)
    finally:
        archive.unlink(missing_ok=True)


def _detach() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def start_swap(new: Path, target: Path, version: str, system: str = sys.platform) -> None:
    """Starts the new app as the helper that replaces target once this process (os.getpid()) exits."""
    log = (new.parent.parent / "helper.log").open("ab")
    # Launched from Explorer, this app's working folder is target: inherited, Windows refuses the rename.
    subprocess.Popen([str(executable_in(new, system)), "--apply-update", str(new), str(target),
                      str(os.getpid()), version], cwd=str(new.parent), stdin=subprocess.DEVNULL, stdout=log,
                     stderr=log, close_fds=True, **_detach())
    log.close()


def wait_for_exit(pid: int, timeout: float) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if not handle:
            return True
        try:
            return kernel.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            kernel.CloseHandle(handle)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)          # never on Windows: there os.kill terminates the process
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        time.sleep(0.2)
    return False


def running_from(root: Path) -> list[int]:
    """Windows: the processes whose executable lies under root (the old app's PKHeX service outlives
    it); each one keeps root from being renamed. Elsewhere a running file never blocks a rename."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    pids = (wintypes.DWORD * 4096)()
    size = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(size)):
        return []
    prefix = os.path.normcase(str(root.resolve())) + os.sep
    found = []
    for pid in pids[:size.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            name, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)) and \
                    os.path.normcase(name.value).startswith(prefix) and pid != os.getpid():
                found.append(pid)
        finally:
            kernel.CloseHandle(handle)
    return found


def end_processes_from(root: Path, timeout: float) -> None:
    """Waits for the processes running from root to end, then terminates the rest."""
    if wait_for(lambda: not running_from(root), timeout):
        return
    for pid in running_from(root):
        try:
            os.kill(pid, 9)           # TerminateProcess on Windows
        except OSError:
            pass
    wait_for(lambda: not running_from(root), 5.0)


def _copy(source: Path, dest: Path, system: str) -> None:
    if system == "darwin":
        subprocess.run(["ditto", str(source), str(dest)], check=True, capture_output=True)
    else:
        shutil.copytree(source, dest, symlinks=True)


def launch(root: Path, system: str = sys.platform) -> None:
    if system == "darwin":
        subprocess.Popen(["open", str(root)], **_detach())
    else:
        subprocess.Popen([str(executable_in(root, system))], cwd=str(root), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **_detach())


def wait_for(condition: Callable[[], bool], timeout: float) -> bool:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.1)
    return True


def apply(new: Path, target: Path, pid: int, version: str, system: str = sys.platform,
          outcome: Path = OUTCOME, relaunch: Callable[[Path], None] | None = None,
          helper: int | None = None) -> bool:
    """The helper: waits for the old app to quit, puts new in target's place, then opens target.
    Any failure puts the old app back. The outcome file tells the app that opens what happened;
    `helper` is the process that app waits for before removing `new`."""
    relaunch = relaunch or (lambda root: launch(root, system))

    def _record(outcome: Path, version: str, error: str = "") -> None:
        outcome.write_text(json.dumps({"version": version, "error": error, "helper": helper}))

    old = target.parent / f".{target.name}.old"
    if not wait_for_exit(pid, EXIT_WAIT):
        _record(outcome, version, "the old app did not quit")
        return False
    end_processes_from(target, 10.0)
    shutil.rmtree(old, ignore_errors=True)
    end = time.monotonic() + RENAME_WAIT
    while True:
        try:
            os.rename(target, old)
            break
        except OSError as error:
            if time.monotonic() > end:
                _record(outcome, version, f"could not move the old app aside ({error})")
                relaunch(target)
                return False
            time.sleep(0.5)
    try:
        _copy(new, target, system)
        if not executable_in(target, system).is_file():
            raise OSError("the copied app has no executable")
    except (OSError, subprocess.CalledProcessError) as error:
        shutil.rmtree(target, ignore_errors=True)
        os.rename(old, target)
        _record(outcome, version, f"could not copy the new app ({error})")
        relaunch(target)
        return False
    shutil.rmtree(old, ignore_errors=True)
    _record(outcome, version)
    relaunch(target)
    return True


def finish(root: Path | None, outcome: Path = OUTCOME, work: Path = WORK) -> dict | None:
    """At launch from the installed app: the last update's outcome, once, and its leftovers removed."""
    if root is None or work in root.parents:
        return None
    try:
        found = json.loads(outcome.read_text())
    except (OSError, ValueError):
        found = None
    found = found if isinstance(found, dict) else None
    outcome.unlink(missing_ok=True)      # the helper closes its window when this file goes
    (work / READY.name).unlink(missing_ok=True)
    shutil.rmtree(root.parent / f".{root.name}.old", ignore_errors=True)
    helper = found.get("helper") if found else None

    def remove_new():
        # The helper runs from work/new; Windows keeps a running exe's folder.
        if isinstance(helper, int):
            wait_for_exit(helper, 30.0)
        shutil.rmtree(work / "new", ignore_errors=True)
    if isinstance(helper, int):
        threading.Thread(target=remove_new, daemon=True).start()
    else:
        remove_new()
    return found

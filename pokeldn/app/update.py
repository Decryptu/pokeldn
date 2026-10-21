"""Whether GitHub has a newer pokeldn release than this app, and installing it in place.

Never waits longer than TIMEOUT for the check; no answer from GitHub raises OSError. The install
downloads this machine's archive, checks it against the release's SHA256SUMS, unpacks it, and hands
the swap to the new app (`--apply-update`) once this one has quit. docs/gui.md (Updates).
"""
import hashlib
import json
import os
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pokeldn import __version__
from pokeldn.app.paths import DATA
from pokeldn.app.sprites import _context
from pokeldn.app import archives

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
    match = re.fullmatch(r"v?([0-9]{1,9})\.([0-9]{1,9})\.([0-9]{1,9})", version.strip())
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
    assets = reply.get("assets")
    files = {a["name"]: a.get("browser_download_url") for a in assets if isinstance(a, dict)
             and isinstance(a.get("name"), str)} if isinstance(assets, list) else {}
    download, sums = files.get(name), files.get("SHA256SUMS")
    return Release(".".join(map(str, theirs)), page, download if isinstance(download, str) else page,
                   sums if isinstance(sums, str) else "")


def github_json(url: str, timeout: float = TIMEOUT, what: str = "release", limit: int = MAX_BYTES):
    """-> what GitHub's API answers at url; an HTTPError (an OSError) for a refusal, an OSError
    naming `what` for an answer that is not JSON."""
    try:
        with _open(url, timeout) as reply:
            data = read_bytes(reply, limit, timeout)
            return json.loads(data)
    except urllib.error.HTTPError as error:
        error.close()   # an HTTPError keeps its socket open until closed
        raise
    except (ValueError, RecursionError) as error:
        raise OSError(f"GitHub sent no {what}: {error}") from error


def check(url: str = LATEST, current: str = __version__) -> Release | None:
    """A newer release, or None when this app is the latest."""
    data = github_json(url)
    if not isinstance(data, dict):
        raise OSError("GitHub sent no release")
    return newer(data, current)


# --- Installing in place -----------------------------------------------------------------------------

WORK = DATA / "update"           # the download, the unpacked app and the helper's log and outcome
OUTCOME = WORK / "outcome.json"
READY = WORK / "helper.ready"    # the helper's window is up; the old app may close its own
MAX_ARCHIVE = 600_000_000
MAX_UNPACKED = 3_000_000_000
MAX_FILES = 30_000
MAX_FILE = 600_000_000
EXIT_WAIT = 120.0                # how long the helper waits for the old app to quit
RENAME_WAIT = 30.0               # Windows keeps a quitting exe's folder locked for a moment
# Takes the administrator path in a folder the user can write (CI runners); scripts/check_update.py.
FORCE_ADMIN = os.environ.get("POKELDN_UPDATE_ADMIN") == "1"


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


def blocker(root: Path | None, system: str = sys.platform) -> str:
    """Why this copy of the app cannot replace itself, or "" when it can."""
    if root is None:
        return "Only the packed app updates itself."
    if "AppTranslocation" in root.parts:
        # macOS runs a quarantined app from Downloads out of a random read-only copy.
        return "Move pokeldn to your Applications folder, open it from there, then update."
    if not needs_admin(root, system) and not (_writable(root.parent) and _writable(root)):
        return f"pokeldn cannot write to {root.parent}."
    return ""


def needs_admin(root: Path | None, system: str = sys.platform) -> bool:
    """Windows: a folder only an administrator may change (C:\\Program Files); the swap asks Windows."""
    if system != "win32" or root is None:
        return False
    return FORCE_ADMIN or not (_writable(root.parent) and _writable(root))


def checksums(text: str) -> dict[str, str]:
    """sha256sum's lines, "<hex>  <name>" (a "*" before the name marks binary mode)."""
    found = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](\S.*)", line.strip())
        if match:
            found[match.group(2)] = match.group(1).lower()
    return found


def _open(url: str, timeout: float = 30.0):
    def allowed(address):
        parts = urllib.parse.urlsplit(address)
        return (parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password
                or parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost"))

    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not allowed(newurl):
                raise OSError("the download redirected to an unsafe address")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    if not allowed(url):
        raise OSError("the download is not an HTTPS address")
    request = urllib.request.Request(url, headers={"User-Agent": "pokeldn-desktop"})
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_context()), Redirect())
    return opener.open(request, timeout=timeout)


def release_asset(page: str, url: str, name: str) -> bool:
    if not isinstance(page, str) or not isinstance(url, str):
        return False
    origin = urllib.parse.urlsplit(page)
    if origin.scheme == "http" and origin.hostname in ("127.0.0.1", "localhost"):
        asset = urllib.parse.urlsplit(url)
        return asset.scheme == "http" and asset.netloc == origin.netloc and asset.path == "/" + name
    prefix = "https://github.com/Decryptu/pokeldn/releases/tag/"
    if not page.startswith(prefix):
        return False
    tag = page[len(prefix):]
    return parse(tag) is not None and url == f"https://github.com/Decryptu/pokeldn/releases/download/{tag}/{name}"


def chunks(reply, timeout: float):
    deadline = time.monotonic() + timeout
    read = getattr(reply, "read1", reply.read)
    while True:
        if time.monotonic() > deadline:
            raise OSError("the download took too long")
        chunk = read(65536)
        if not chunk:
            return
        yield chunk


def read_bytes(reply, limit: int, timeout: float = 30.0) -> bytes:
    data = bytearray()
    for chunk in chunks(reply, timeout):
        if len(data) + len(chunk) > limit:
            raise OSError("the response is too large")
        data.extend(chunk)
    return bytes(data)


def fetch(url: str, dest: Path, progress: Callable[[int, int], None] = lambda done, total: None,
          cancelled: Callable[[], bool] = lambda: False) -> str:
    """Downloads url to dest; returns its SHA-256. A partial file is removed."""
    digest, done = hashlib.sha256(), 0
    try:
        with _open(url) as reply, dest.open("wb") as out:
            total = int(reply.headers.get("Content-Length") or 0)
            if total > MAX_ARCHIVE:
                raise OSError(f"the download is {total} bytes")
            for chunk in chunks(reply, 600):
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


def _links_safe(names, links):
    links = {name.casefold(): target.casefold() for name, target in links.items()}
    for name in names:
        parts = name.casefold().split("/")
        if any("/".join(parts[:i]) in links for i in range(1, len(parts))):
            raise OSError("the archive writes through a link")
    for name in links:
        pending = name.split("/")
        resolved, hops = [], 0
        while pending:
            resolved.append(pending.pop(0))
            path = "/".join(resolved)
            if path in links:
                hops += 1
                if hops > 40:
                    raise OSError("the archive holds a link cycle")
                pending = links[path].split("/") + pending
                resolved = []


def _target(name, target, hard=False):
    if not target or target.startswith("/") or "\\" in target:
        raise OSError("the archive holds an unsafe link")
    return archives.relative(posixpath.normpath(target if hard else posixpath.join(posixpath.dirname(name), target)))


def unpack(archive: Path, folder: Path, system: str = sys.platform) -> Path:
    """Unpacks the release archive into an empty folder; returns the app inside it."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    try:
        if archive.name.endswith(".tar.gz"):
            with tarfile.open(archive) as tar:
                members = archives.bounded(((m.name, m.size, m) for m in tar),
                                           MAX_FILES, MAX_UNPACKED, MAX_FILE)
                links = {}
                for m in members:
                    if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
                        raise OSError("the archive holds a special file")
                    if m.issym() or m.islnk():
                        name = archives.relative(m.name)
                        links[name] = _target(name, m.linkname, m.islnk())
                _links_safe([archives.relative(m.name) for m in members], links)
                tar.extractall(folder, members=members, filter="data")
        else:
            with archives.open_zip(archive, MAX_FILES) as z:
                members = archives.bounded(((m.filename, m.file_size, m) for m in z.infolist()),
                                           MAX_FILES, MAX_UNPACKED, MAX_FILE)
                links = {}
                for m in members:
                    mode = stat.S_IFMT(m.external_attr >> 16)
                    if mode == stat.S_IFLNK:
                        if system != "darwin" or m.file_size > 4096:
                            raise OSError("the archive holds an unsafe link")
                        name = archives.relative(m.filename)
                        links[name] = _target(name, z.read(m).decode("utf-8"))
                    elif mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise OSError("the archive holds a special file")
                _links_safe([archives.relative(m.filename) for m in members], links)
                if system != "darwin":
                    z.extractall(folder, members=members)
                else:
                    for m in members:
                        out = archives.destination(folder, m.filename)
                        out.parent.mkdir(parents=True, exist_ok=True)
                        if m.is_dir():
                            out.mkdir(exist_ok=True)
                        elif stat.S_ISLNK(m.external_attr >> 16):
                            os.symlink(z.read(m).decode("utf-8"), out)
                        else:
                            with z.open(m) as source, out.open("wb") as target:
                                archives.copy(source, target, m.file_size)
                            mode = (m.external_attr >> 16) & 0o777
                            if mode:
                                out.chmod(mode)
        root = folder / ("pokeldn.app" if system == "darwin" else "pokeldn")
        if not executable_in(root, system).is_file():
            raise OSError(f"the archive holds no {executable_in(root, system).relative_to(folder)}")
        return root
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def prepare(release: Release, progress: Callable[[int, int], None] = lambda done, total: None,
            cancelled: Callable[[], bool] = lambda: False, work: Path = WORK,
            system: str = sys.platform) -> Path:
    """Downloads, checks and unpacks the release; returns the new app, ready for start_swap."""
    if not release.installable:
        raise OSError("the release has no file for this computer or no SHA256SUMS")
    name = release.download.rsplit("/", 1)[-1]
    if (name not in ASSETS.values() or not release_asset(release.page, release.download, name)
            or not release_asset(release.page, release.checksums, "SHA256SUMS")):
        raise OSError("the release files are not from the pokeldn release")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    with _open(release.checksums) as reply:
        data = read_bytes(reply, MAX_BYTES)
        expected = checksums(data.decode("utf-8", "replace")).get(name)
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


def start_swap(new: Path, target: Path, version: str, system: str = sys.platform, admin: bool = False) -> None:
    """Starts the new app as the helper that replaces target once this process (os.getpid()) exits."""
    args = ["--apply-update", str(new), str(target), str(os.getpid()), version]
    if admin:
        _run_as_admin(executable_in(new, system), args, new.parent, target.parent)
        return
    # Launched from Explorer, this app's working folder is target: inherited, Windows refuses the rename.
    with (new.parent.parent / "helper.log").open("ab") as log:
        subprocess.Popen([str(executable_in(new, system)), *args], cwd=str(new.parent), stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, close_fds=True, **_detach())


def _run_as_admin(exe: Path, args: list[str], cwd: Path, folder: Path) -> None:
    """ShellExecuteExW with the runas verb: Windows asks the user (UAC) before the helper starts."""
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):     # SHELLEXECUTEINFOW
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    info = Info(cbSize=ctypes.sizeof(Info), fMask=0x40 | 0x400,   # SEE_MASK_NOCLOSEPROCESS | FLAG_NO_UI
                lpVerb="runas", lpFile=str(exe), lpParameters=subprocess.list2cmdline(args),
                lpDirectory=str(cwd), nShow=1)
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:             # ERROR_CANCELLED: the user said no on the UAC prompt
            raise OSError(f"Windows did not give pokeldn permission to change {folder}")
        raise ctypes.WinError(error)
    if info.hProcess:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)


def _elevated() -> bool:
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


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
    elif system == "win32" and _elevated():
        # Explorer opens it at the user's own level; a child of this helper would run as administrator.
        subprocess.Popen(["explorer.exe", str(executable_in(root, system))], **_detach())
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
        # One pass left the helper's exe and loaded DLLs on Windows runners: retry until they go.
        end = time.monotonic() + 120.0
        while True:
            shutil.rmtree(work / "new", ignore_errors=True)
            if not (work / "new").exists() or time.monotonic() > end:
                break
            time.sleep(1.0)
    if isinstance(helper, int):
        threading.Thread(target=remove_new, daemon=True).start()
    else:
        remove_new()
    return found

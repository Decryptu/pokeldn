"""Pokemon pixel-art sprites from PokeAPI's sprite repository, kept in a local cache.

The app never needs a sprite: every call returns bytes or None, never raises, and never waits longer
than TIMEOUT on a dead network. docs/gui.md (Pokemon sprites) describes the cache layout.
"""
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from pokeldn.app.paths import DATA

# The files behind `sprites.front_default` / `front_shiny` of https://pokeapi.co/api/v2/pokemon/{id}.
BASE = os.environ.get("POKELDN_SPRITE_BASE",
                      "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon")
TIMEOUT = 5.0
OFFLINE_COOLDOWN = 60.0         # after a network failure, no request for this long
MISSING_TTL = 7 * 86400.0       # a 404 is remembered this long, then asked again
MAX_BYTES = 200_000
PNG = b"\x89PNG\r\n\x1a\n"


def _context() -> ssl.SSLContext:
    # A frozen macOS build has no system certificate store that Python can read; certifi ships with flet.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def valid(data: bytes) -> bool:
    return data[:8] == PNG and data[12:16] == b"IHDR" and len(data) <= MAX_BYTES


class SpriteCache:
    def __init__(self, folder: Path | None = None, base: str | None = None, online: bool = True):
        self.folder = Path(folder) if folder else DATA / "sprites"
        self.base = (base or BASE).rstrip("/")
        self.online = online            # False reads the cache and never touches the network
        self.offline_until = 0.0
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(4)
        self.memory: dict[tuple[int, bool], bytes | None] = {}

    def _path(self, species: int, shiny: bool) -> Path:
        return self.folder / ("shiny" if shiny else "normal") / f"{species}.png"

    def cached(self, species: int, shiny: bool = False) -> bytes | None:
        """The sprite on disk, or None. Never touches the network; a damaged file is removed."""
        key = (species, shiny)
        if self.memory.get(key):
            return self.memory[key]
        path = self._path(species, shiny)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if valid(data):
            self.memory[key] = data
            return data
        try:
            path.unlink()
        except OSError:
            pass
        return None

    def known_missing(self, species: int, shiny: bool = False) -> bool:
        try:
            return time.time() - self._path(species, shiny).with_suffix(".none").stat().st_mtime < MISSING_TTL
        except OSError:
            return False

    def get(self, species: int, shiny: bool = False) -> bytes | None:
        """The cached sprite, else one download. Blocks for at most TIMEOUT: call it from a worker thread."""
        if not isinstance(species, int) or species < 1:
            return None
        data = self.cached(species, shiny)
        if data is not None or not self.online or self.known_missing(species, shiny):
            return data
        if time.monotonic() < self.offline_until:
            return None
        with self.slots:
            return self._download(species, shiny)

    def _download(self, species: int, shiny: bool) -> bytes | None:
        path = self._path(species, shiny)
        url = f"{self.base}/{'shiny/' if shiny else ''}{species}.png"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "pokeldn-desktop"})
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=_context()) as reply:
                data = reply.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                self._remember_missing(path)
            elif exc.code >= 500 or exc.code == 429:
                self.offline_until = time.monotonic() + OFFLINE_COOLDOWN
            return None
        except (OSError, ValueError):   # URLError, timeouts, resets, DNS: the machine has no network
            self.offline_until = time.monotonic() + OFFLINE_COOLDOWN
            return None
        if not valid(data):
            return None
        self.offline_until = 0.0
        self.memory[(species, shiny)] = data
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{species}.{threading.get_ident()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            path.with_suffix(".none").unlink(missing_ok=True)
        except OSError:
            pass                        # a read-only data folder still shows the sprite this session
        return data

    def _remember_missing(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".none").touch()
        except OSError:
            pass

    def clear(self) -> int:
        """Delete every cached sprite; returns the number of files removed."""
        self.memory.clear()
        removed = 0
        for path in self.folder.rglob("*"):
            if path.is_file() and path.suffix in (".png", ".none", ".tmp"):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


CACHE = SpriteCache()

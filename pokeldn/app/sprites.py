"""Pokemon pixel-art sprites from PokeAPI's sprite repository, kept in a local cache.

The app never needs a sprite: every call returns bytes or None, never raises, and never waits longer
than TIMEOUT on a dead network. docs/gui.md (Pokemon sprites) describes the cache layout.
"""
import os
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request
import zlib
from functools import lru_cache
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


CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


@lru_cache(maxsize=64)
def pixels(data: bytes) -> tuple[int, int, tuple[tuple[tuple[int, int, int, int], ...], ...]] | None:
    """(width, height, rows of (r, g, b, a)) of a PNG; None for one this does not read (16-bit,
    interlaced). Pillow is not in the packaged app."""
    try:
        chunks, pos = {}, 8
        while pos < len(data):
            size = struct.unpack(">I", data[pos:pos + 4])[0]
            kind = data[pos + 4:pos + 8]
            chunks[kind] = chunks.get(kind, b"") + data[pos + 8:pos + 8 + size]
            pos += 12 + size
        width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
        if depth > 8 or interlace or color not in CHANNELS:
            return None
        raw = zlib.decompress(chunks[b"IDAT"])
    except (KeyError, struct.error, zlib.error):
        return None
    channels = CHANNELS[color]
    step, stride = max(1, channels * depth // 8), (width * channels * depth + 7) // 8
    trns, palette = chunks.get(b"tRNS", b""), chunks.get(b"PLTE", b"")
    # A pixel is clear when its alpha is 0, or it is the colour (or palette entry) tRNS marks clear.
    clear_key = struct.unpack(">H", trns[:2])[0] if color == 0 and len(trns) >= 2 else None
    rgb_key = struct.unpack(">HHH", trns[:6]) if color == 2 and len(trns) >= 6 else None
    previous = bytearray(stride)
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if len(line) < stride:
            return None
        for i in range(stride):
            a = line[i - step] if i >= step else 0
            b, c = previous[i], previous[i - step] if i >= step else 0
            if kind == 1:
                line[i] = (line[i] + a) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + b) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        previous = line
        row = []
        for x in range(width):
            if color == 6:
                row.append(tuple(line[x * 4:x * 4 + 4]))
            elif color == 4:
                row.append((line[x * 2],) * 3 + (line[x * 2 + 1],))
            elif color == 2:
                rgb = tuple(line[x * 3:x * 3 + 3])
                row.append(rgb + (0 if rgb == rgb_key else 255,))
            else:
                bit = x * depth
                value = (line[bit // 8] >> (8 - depth - bit % 8)) & ((1 << depth) - 1)
                if color == 3:
                    rgb = tuple(palette[value * 3:value * 3 + 3]) or (0, 0, 0)
                    row.append(rgb + (trns[value] if value < len(trns) else 255,))
                else:
                    grey = value * 255 // ((1 << depth) - 1)
                    row.append((grey, grey, grey, 0 if value == clear_key else 255))
        rows.append(tuple(row))
    return width, height, tuple(rows)


@lru_cache(maxsize=512)
def bounds(data: bytes) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) around a PNG's visible pixels, x1 and y1 exclusive; None for an empty image or
    one this does not read."""
    image = pixels(data)
    if image is None:
        return None
    xs, ys = [], []
    for y, row in enumerate(image[2]):
        for x, pixel in enumerate(row):
            if pixel[3]:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


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

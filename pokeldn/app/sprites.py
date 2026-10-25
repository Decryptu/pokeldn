"""Pokemon pixel-art sprites from PokeAPI's sprite repository, kept in a local cache.

The app never needs a sprite: every call returns bytes or None, never raises, and never waits longer
than TIMEOUT on a dead network. docs/gui.md (Pokemon sprites) describes the cache layout.
"""
import hashlib
import json
import os
import re
import ssl
import struct
import threading
import time
import urllib.error
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
MAX_DIMENSION = 256
MAX_PIXELS = 65536
PNG = b"\x89PNG\r\n\x1a\n"
# Each file this cache cleaned, by SHA-256, with its bounds: a file read again is not decoded again.
INDEX = "index.json"


def _context() -> ssl.SSLContext:
    # A frozen macOS build has no system certificate store that Python can read; certifi ships with flet.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def valid(data: bytes) -> bool:
    return pixels(data) is not None


KEPT = (b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND")    # the chunks that draw a sprite, in file order


def clean(data: bytes) -> bytes | None:
    """A PNG this reads, rebuilt from its KEPT chunks alone, so a colour profile, text or any other
    ancillary chunk never reaches the app's image decoder; None for one this does not read."""
    chunks = _chunks(data)
    if chunks is None or pixels(data) is None:
        return None
    return PNG + b"".join(struct.pack(">I", len(chunks[kind])) + kind + chunks[kind]
                          + struct.pack(">I", zlib.crc32(kind + chunks[kind])) for kind in KEPT if kind in chunks)


def _chunks(data: bytes) -> dict[bytes, bytes] | None:
    """A PNG's KEPT chunks, IDAT joined; None for a damaged or animated PNG. The other ancillary chunks are
    checked against their CRC and skipped unread."""
    try:
        if len(data) > MAX_BYTES or data[:8] != PNG:
            return None
        chunks, pos = {}, 8
        while pos < len(data):
            size = struct.unpack(">I", data[pos:pos + 4])[0]
            kind = data[pos + 4:pos + 8]
            end = pos + 12 + size
            if end > len(data) or (pos == 8 and kind != b"IHDR"):
                return None
            if (len(kind) != 4 or any(not (65 <= c <= 90 or 97 <= c <= 122) for c in kind)
                    or (not kind[0] & 32 and kind not in (b"IHDR", b"PLTE", b"IDAT", b"IEND"))
                    or kind in (b"acTL", b"fcTL", b"fdAT")):
                return None
            body = data[pos + 8:pos + 8 + size]
            if zlib.crc32(kind + body) != struct.unpack(">I", data[end - 4:end])[0]:
                return None
            if kind in chunks and kind != b"IDAT":
                return None
            if kind == b"IEND" and (size or end != len(data)):
                return None
            if kind in KEPT:
                chunks[kind] = chunks.get(kind, b"") + body
            pos += 12 + size
    except struct.error:
        return None
    return chunks


CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


@lru_cache(maxsize=8)
def pixels(data: bytes) -> tuple[int, int, tuple[tuple[tuple[int, int, int, int], ...], ...]] | None:
    """(width, height, rows of (r, g, b, a)) of a PNG; None for one this does not read (16-bit,
    interlaced). Pillow is not in the packaged app."""
    chunks = _chunks(data)
    if chunks is None:
        return None
    try:
        width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
        depths = {0: (1, 2, 4, 8), 2: (8,), 3: (1, 2, 4, 8), 4: (8,), 6: (8,)}
        if (not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION
                or width * height > MAX_PIXELS or depth not in depths.get(color, ())
                or compression or filtering or interlace or b"IEND" not in chunks):
            return None
        expected = height * (1 + (width * CHANNELS[color] * depth + 7) // 8)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(chunks[b"IDAT"], expected + 1)
        if len(raw) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
            return None
    except (KeyError, struct.error, zlib.error):
        return None
    channels = CHANNELS[color]
    step, stride = max(1, channels * depth // 8), (width * channels * depth + 7) // 8
    trns, palette = chunks.get(b"tRNS", b""), chunks.get(b"PLTE", b"")
    if color == 3 and (not palette or len(palette) % 3 or len(palette) > 768 or len(trns) > len(palette) // 3):
        return None
    # A pixel is clear when its alpha is 0, or it is the colour (or palette entry) tRNS marks clear.
    clear_key = struct.unpack(">H", trns[:2])[0] if color == 0 and len(trns) >= 2 else None
    rgb_key = struct.unpack(">HHH", trns[:6]) if color == 2 and len(trns) >= 6 else None
    previous = bytearray(stride)
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if kind > 4 or len(line) < stride:
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
                    if value * 3 + 3 > len(palette):
                        return None
                    rgb = tuple(palette[value * 3:value * 3 + 3])
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


def _box(value) -> bool:
    return (isinstance(value, list) and len(value) == 4 and all(type(v) is int for v in value)
            and 0 <= value[0] < value[2] <= MAX_DIMENSION and 0 <= value[1] < value[3] <= MAX_DIMENSION)


class SpriteCache:
    def __init__(self, folder: Path | None = None, base: str | None = None, online: bool = True):
        self.folder = Path(folder) if folder else DATA / "sprites"
        self.base = (base or BASE).rstrip("/")
        self.online = online            # False reads the cache and never touches the network
        self.offline_until = 0.0
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(4)
        self.memory: dict[tuple[int | str, bool], bytes | None] = {}
        self.crops: dict[tuple[int | str, bool], tuple[int, int, int, int] | None] = {}
        self.index: dict | None = None

    def _path(self, species: int | str, shiny: bool) -> Path:
        return self.folder / ("shiny" if shiny else "normal") / f"{species}.png"

    @staticmethod
    def _valid_key(species: int | str) -> bool:
        return ((type(species) is int and species > 0) or
                (isinstance(species, str) and
                 re.fullmatch(r"[1-9][0-9]*-[a-z][a-z0-9-]*", species) is not None))

    def cached(self, species: int | str, shiny: bool = False) -> bytes | None:
        """The sprite on disk, or None. Never touches the network; a damaged file is removed."""
        if not self._valid_key(species):
            return None
        key = (species, shiny)
        if self.memory.get(key):
            return self.memory[key]
        path = self._path(species, shiny)
        try:
            with path.open("rb") as source:
                raw = source.read(MAX_BYTES + 1)
        except OSError:
            return None
        known = self._indexed().get(self._name(species, shiny))
        if (isinstance(known, dict) and known.get("sha256") == hashlib.sha256(raw).hexdigest()
                and (known.get("bounds") is None or _box(known["bounds"]))):
            self.crops[key] = tuple(known["bounds"]) if known["bounds"] else None
            self.memory[key] = raw
            return raw
        data = clean(raw)
        if data is not None:
            self.memory[key] = data
            self._remember(species, shiny, data)
            return data
        try:
            path.unlink()
        except OSError:
            pass
        return None

    def crop(self, species: int | str, shiny: bool, data: bytes) -> tuple[int, int, int, int] | None:
        """bounds() of the sprite this cache returned for (species, shiny), read from the index when it has it."""
        found = self.crops.get((species, shiny), False)
        return bounds(data) if found is False or self.memory.get((species, shiny)) is not data else found

    @staticmethod
    def _name(species: int | str, shiny: bool) -> str:
        return f"{'shiny' if shiny else 'normal'}/{species}"

    def _indexed(self) -> dict:
        if self.index is None:
            try:
                index = json.loads((self.folder / INDEX).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                index = {}
            self.index = index if isinstance(index, dict) else {}
        return self.index

    def _remember(self, species: int | str, shiny: bool, data: bytes) -> None:
        crop = bounds(data)
        self.crops[(species, shiny)] = crop
        with self.lock:
            self._indexed()[self._name(species, shiny)] = {"sha256": hashlib.sha256(data).hexdigest(),
                                                          "bounds": list(crop) if crop else None}
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                tmp = self.folder / f".{INDEX}.{threading.get_ident()}.tmp"
                tmp.write_text(json.dumps(self.index), encoding="utf-8")
                os.replace(tmp, self.folder / INDEX)
            except OSError:
                pass

    def known_missing(self, species: int | str, shiny: bool = False) -> bool:
        if not self._valid_key(species):
            return False
        try:
            return time.time() - self._path(species, shiny).with_suffix(".none").stat().st_mtime < MISSING_TTL
        except OSError:
            return False

    def get(self, species: int | str, shiny: bool = False) -> bytes | None:
        """The cached sprite, else one download. Blocks for at most TIMEOUT: call it from a worker thread."""
        if not self._valid_key(species):
            return None
        data = self.cached(species, shiny)
        if data is not None or not self.online or self.known_missing(species, shiny):
            return data
        if time.monotonic() < self.offline_until:
            return None
        with self.slots:
            if (data := self.cached(species, shiny)) is not None or self.known_missing(species, shiny):
                return data
            if time.monotonic() < self.offline_until or not self.online:
                return None
            return self._download(species, shiny)

    def _download(self, species: int | str, shiny: bool) -> bytes | None:
        from pokeldn.app import update
        path = self._path(species, shiny)
        url = f"{self.base}/{'shiny/' if shiny else ''}{species}.png"
        try:
            with update._open(url, TIMEOUT) as reply:
                data = update.read_bytes(reply, MAX_BYTES, TIMEOUT)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (403, 404):
                self._remember_missing(path)
            elif exc.code >= 500 or exc.code == 429:
                self.offline_until = time.monotonic() + OFFLINE_COOLDOWN
            return None
        except (OSError, ValueError):   # URLError, timeouts, resets, DNS: the machine has no network
            self.offline_until = time.monotonic() + OFFLINE_COOLDOWN
            return None
        data = clean(data)
        if data is None:
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
        self._remember(species, shiny, data)
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
        self.crops.clear()
        self.index = None
        removed = 0
        for index in self.folder.rglob(INDEX):
            index.unlink(missing_ok=True)
        for path in self.folder.rglob("*"):
            if path.is_file() and path.suffix in (".png", ".none", ".tmp"):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


CACHE = SpriteCache()

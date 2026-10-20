"""The sprite cache against a local stand-in for PokeAPI's sprite host, including no network at all."""
import http.server
import os
import socket
import struct
import threading
import time
import zlib

import pytest

from pokeldn.app import sprites


def png(seed: int = 0) -> bytes:
    """A 1x1 PNG built from the format's own chunk layout (the PNG specification, section 5)."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes([0, seed, 0, 0, 255]))) + chunk(b"IEND", b""))


class Host:
    """Serves /pokemon/{id}.png and /pokemon/shiny/{id}.png; `routes` maps a path to (status, body)."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                status, body = owner.routes.get(self.path, (404, b"Not Found"))
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/pokemon"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def host():
    h = Host()
    yield h
    try:
        h.stop()
    except Exception:
        pass


def dead_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}/pokemon"   # nothing listens on it


def test_download_once_then_cache_serves_with_the_host_gone(host, tmp_path):
    host.routes = {"/pokemon/25.png": (200, png(1)), "/pokemon/shiny/25.png": (200, png(2))}
    first = sprites.SpriteCache(tmp_path, host.url)
    assert first.get(25) == png(1)
    assert first.get(25, shiny=True) == png(2)
    assert host.requests == ["/pokemon/25.png", "/pokemon/shiny/25.png"]
    host.stop()
    later = sprites.SpriteCache(tmp_path, host.url)          # a new launch, no network
    assert later.cached(25) == png(1)
    assert later.get(25, shiny=True) == png(2)
    assert len(host.requests) == 2


def test_no_network_and_no_cache_returns_none_quickly(tmp_path):
    cache = sprites.SpriteCache(tmp_path, dead_url())
    start = time.monotonic()
    assert [cache.get(n) for n in (1, 25, 150)] == [None, None, None]
    assert time.monotonic() - start < sprites.TIMEOUT
    assert not list(tmp_path.rglob("*.none"))                # an offline failure is not "no such sprite"
    assert cache.offline_until > time.monotonic()            # later calls do not retry at once


def test_offline_switch_never_touches_the_host(host, tmp_path):
    host.routes = {"/pokemon/25.png": (200, png())}
    cache = sprites.SpriteCache(tmp_path, host.url, online=False)
    assert cache.get(25) is None
    assert host.requests == []


def test_missing_sprite_is_remembered_then_asked_again(host, tmp_path):
    cache = sprites.SpriteCache(tmp_path, host.url)
    assert cache.get(9999) is None and cache.known_missing(9999)
    assert cache.get(9999) is None
    assert host.requests == ["/pokemon/9999.png"]
    marker = tmp_path / "normal" / "9999.none"
    old = time.time() - sprites.MISSING_TTL - 1
    os.utime(marker, (old, old))
    host.routes = {"/pokemon/9999.png": (200, png(3))}
    assert cache.get(9999) == png(3) and not marker.exists()


@pytest.mark.parametrize("body", [b"<html>captive portal</html>", png() + b"\0" * 300_000, b""],
                         ids=["captive-portal", "oversize", "empty"])
def test_a_reply_that_is_not_a_sprite_is_never_cached(host, tmp_path, body):
    host.routes = {"/pokemon/25.png": (200, body)}
    cache = sprites.SpriteCache(tmp_path, host.url)
    assert cache.get(25) is None
    assert not list(tmp_path.rglob("*.png"))


def with_extras(data: bytes) -> bytes:
    """`data` with the ancillary chunks PokeAPI's Gen 9 sprites carry (iCCP, zTXt, iTXt, tEXt, tIME), some twice."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    profile = chunk(b"iCCP", b"ICC Profile\0\0" + zlib.compress(b"\0" * 400))
    text = (chunk(b"zTXt", b"Raw profile type exif\0\0" + zlib.compress(b"x" * 200)) * 2
            + chunk(b"iTXt", b"XML:com.adobe.xmp\0\0\0\0\0<x/>") + chunk(b"tEXt", b"Software\0GIMP") * 2)
    ihdr = 8 + 25
    return data[:ihdr] + profile + text + data[ihdr:-12] + chunk(b"tIME", bytes(7)) + data[-12:]


def test_a_sprite_with_a_colour_profile_and_text_is_kept_without_them(host, tmp_path):
    """26 of PokeAPI's 2,050 sprites, Sprigatito, Quaxly and Miraidon among them, carry iCCP, zTXt or iTXt
    chunks: the cache keeps the image and drops those unread."""
    host.routes = {"/pokemon/906.png": (200, with_extras(png(6)))}
    cache = sprites.SpriteCache(tmp_path, host.url)
    assert cache.get(906) == png(6) == (tmp_path / "normal" / "906.png").read_bytes()
    (tmp_path / "shiny").mkdir()
    (tmp_path / "shiny" / "906.png").write_bytes(with_extras(png(7)))       # saved by an older version
    assert sprites.SpriteCache(tmp_path, dead_url()).get(906, shiny=True) == png(7)
    assert sprites.pixels(with_extras(png(6))) == sprites.pixels(png(6))


def test_damaged_cache_file_is_replaced(host, tmp_path):
    (tmp_path / "normal").mkdir()
    (tmp_path / "normal" / "25.png").write_bytes(b"half a fi")
    host.routes = {"/pokemon/25.png": (200, png(4))}
    cache = sprites.SpriteCache(tmp_path, host.url)
    assert cache.cached(25) is None
    assert cache.get(25) == png(4)
    assert (tmp_path / "normal" / "25.png").read_bytes() == png(4)


def test_damaged_cache_file_offline_is_just_absent(tmp_path):
    (tmp_path / "normal").mkdir()
    (tmp_path / "normal" / "25.png").write_bytes(b"half a fi")
    assert sprites.SpriteCache(tmp_path, dead_url()).get(25) is None


def test_unwritable_folder_still_returns_the_sprite(host, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    host.routes = {"/pokemon/25.png": (200, png(5))}
    cache = sprites.SpriteCache(blocker / "sprites", host.url)
    assert cache.get(25) == png(5)
    assert cache.get(25) == png(5) and len(host.requests) == 1     # kept in memory


@pytest.mark.parametrize("species", [0, -3, "25", None, 2.5])
def test_nonsense_species_never_raises(tmp_path, species):
    assert sprites.SpriteCache(tmp_path, dead_url()).get(species) is None


def test_clear_empties_the_cache(host, tmp_path):
    host.routes = {"/pokemon/25.png": (200, png())}
    cache = sprites.SpriteCache(tmp_path, host.url)
    cache.get(25)
    cache.get(26)
    assert cache.clear() == 2 and cache.cached(25) is None


@pytest.mark.parametrize("species,form,key", [
    (146, 0, 146), (146, 1, 10171), (52, 1, 10107), (52, 2, 10161),
    (25, 1, 10094), (25, 6, 10099), (25, 7, 10148), (25, 9, 10160),
    (423, 1, "423-east"), (854, 1, "854-antique"), (25, 99, None),
])
def test_game_forms_resolve_to_their_own_sprite(species, form, key):
    from pokeldn.app.sprite_forms import sprite_key
    assert sprite_key(species, form) == key


def test_every_gigantamax_den_boss_has_its_own_gigantamax_sprite():
    """The den tables' Gigantamax bosses (pokeldn/swsh/data), each drawn in its own shape, and an
    Alcremie of any cream in the one shape."""
    import json
    from pokeldn.app.sprite_forms import sprite_key
    from pokeldn.swsh import raid
    slots = json.loads(raid.NEST_SLOTS.read_text())["slots"]
    bosses = {(row[2], row[3]) for rows in slots.values() for row in rows if row[4]}
    assert len(bosses) == 25
    keys = {boss: sprite_key(*boss, gigantamax=True) for boss in bosses}
    assert all(isinstance(key, int) and key > 10000 for key in keys.values())
    assert len(set(keys.values())) == len(bosses)
    assert sprite_key(869, 5, gigantamax=True) == keys[(869, 0)]


def test_form_sprites_keep_separate_normal_and_shiny_cache_entries(host, tmp_path):
    host.routes = {f"/pokemon/{name}.png": (200, png(n)) for n, name in enumerate(
        ("423", "423-east", "shiny/423-east"), start=1)}
    cache = sprites.SpriteCache(tmp_path, host.url)
    assert cache.get(423) == png(1)
    assert cache.get("423-east") == png(2)
    assert cache.get("423-east", True) == png(3)
    offline = sprites.SpriteCache(tmp_path, host.url, online=False)
    assert offline.get(423) == png(1)
    assert offline.get("423-east") == png(2)
    assert offline.get("423-east", True) == png(3)
    assert len(host.requests) == 3


@pytest.mark.parametrize("key", ["../25", "25/other", "25-../../secret", "25-east.png"])
def test_form_sprite_names_cannot_escape_the_cache(host, tmp_path, key):
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep this file")
    cache = sprites.SpriteCache(tmp_path / "cache", host.url)
    (cache.folder / "normal").mkdir(parents=True)
    for bad in (key, "../../outside"):
        assert cache.cached(bad) is None
        assert cache.get(bad) is None
        assert not cache.known_missing(bad)
    assert outside.read_bytes() == b"keep this file"
    assert not host.requests


def _figure(bits: int):
    """96x96 values: 0 outside the box (13, 20)-(71, 89), noise inside, its four edges touched."""
    import random
    rng = random.Random(bits)
    top = (1 << bits) - 1
    grid = [[0] * 96 for _ in range(96)]
    for y in range(20, 89):
        for x in range(13, 71):
            if rng.random() < 0.6:
                grid[y][x] = rng.randint(1, top)
    for x, y in ((13, 50), (70, 51), (40, 20), (41, 88)):
        grid[y][x] = top
    return grid


@pytest.mark.parametrize("mode, bits", [("RGBA", 8), ("LA", 8), ("RGB", 8), ("L", 8),
                                        ("P", 8), ("P", 4), ("P", 2), ("P", 1)])
def test_bounds_matches_pillow_on_every_colour_type_and_palette_depth(mode, bits):
    Image = pytest.importorskip("PIL.Image")
    import io
    grid = _figure(bits)
    image = Image.new(mode, (96, 96))
    colour = {"RGBA": lambda v: (v, 255 - v, v // 2, 255 if v else 0), "LA": lambda v: (v, 255 if v else 0),
              "RGB": lambda v: (v, 255 - v, v // 2) if v else (0, 255, 0), "L": lambda v: v, "P": lambda v: v}[mode]
    image.putdata([colour(v) for row in grid for v in row])
    options = {"RGB": {"transparency": (0, 255, 0)}, "L": {"transparency": 0}, "P": {"transparency": 0, "bits": bits}}
    if mode == "P":
        image.putpalette([c for i in range(1 << bits) for c in (i, 255 - i, i)])
    out = io.BytesIO()
    image.save(out, "PNG", **options.get(mode, {}))
    data = out.getvalue()
    assert data[24] == bits                         # the IHDR bit depth this case is about
    assert sprites.bounds(data) == Image.open(io.BytesIO(data)).convert("RGBA").getbbox() == (13, 20, 71, 89)


@pytest.mark.parametrize("kind", range(5))
def test_bounds_undoes_each_scanline_filter(kind):
    """Each row stored with one PNG filter (section 9.2); Pillow reads the same file as the reference."""
    Image = pytest.importorskip("PIL.Image")
    import io
    grid = _figure(8)
    rows = [bytes(v for value in row for v in ((value, value, 255 - value, 255) if value else (0, 0, 0, 0)))
            for row in grid]
    raw, previous = b"", bytes(len(rows[0]))
    for line in rows:
        out = bytearray()
        for i, x in enumerate(line):
            a, b, c = (line[i - 4] if i >= 4 else 0), previous[i], (previous[i - 4] if i >= 4 else 0)
            p = a + b - c
            paeth = a if abs(p - a) <= abs(p - b) and abs(p - a) <= abs(p - c) else b if abs(p - b) <= abs(p - c) else c
            out.append((x - (0, a, b, (a + b) // 2, paeth)[kind]) & 0xFF)
        raw += bytes([kind]) + out
        previous = line

    def chunk(name: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + name + body + struct.pack(">I", zlib.crc32(name + body))
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 96, 96, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    assert Image.open(io.BytesIO(data)).convert("RGBA").getbbox() == (13, 20, 71, 89)
    assert sprites.bounds(data) == (13, 20, 71, 89)


@pytest.mark.parametrize("data", [b"", b"\x89PNG\r\n\x1a\n", png()[:40], png()[:33] + png()[-12:]])
def test_bounds_of_a_broken_png_is_none(data):
    assert sprites.bounds(png()) == (0, 0, 1, 1)
    assert sprites.bounds(data) is None


def hostile_png(width=1, height=1, raw=b"", depth=8, color=6):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (sprites.PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.mark.parametrize("data", [
    hostile_png(raw=b""), hostile_png(raw=b"\0" * 1_000_000),
    hostile_png(width=0, raw=b"\0"), hostile_png(width=1000000, raw=b"\0"),
    hostile_png(depth=0, raw=b"\0" * 5), hostile_png(raw=b"\x05\0\0\0\0"),
    hostile_png(color=3, raw=b"\0\xff"), png()[:-1], png() + b"junk",
    with_extras(png())[:45] + b"\xff" + with_extras(png())[46:],            # a skipped chunk still has its CRC
])
def test_hostile_pngs_are_rejected_without_rendering_or_caching(host, tmp_path, data):
    assert not sprites.valid(data)
    assert sprites.pixels(data) is None and sprites.bounds(data) is None
    host.routes = {"/pokemon/25.png": (200, data)}
    cache = sprites.SpriteCache(tmp_path, host.url)
    assert cache.get(25) is None and not list(tmp_path.rglob("*.png"))

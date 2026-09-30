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

"""Plugin sources: a JSON listing of plugins a player follows, from which they install, update and
remove plugins in one press. A listing only names packages; every download still goes through the
package checks and the risk screen (docs/plugins.md, Sources).
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from pokeldn import plugins
from pokeldn.app import plugin_store

SCHEMA = 1
FILE = "pokeldn-source.json"
MAX_BYTES = 1 << 20
MAX_ENTRIES = 500
BUILT_IN = "https://raw.githubusercontent.com/Decryptu/pokeldn-decrypt-plugins/main/" + FILE
BUILT_IN_NAME = "Decrypt's plugins"
SLUG = re.compile(r"([A-Za-z0-9-]{1,39})/([\w.-]{1,100})")
GITHUB = re.compile(r"https://github\.com/([A-Za-z0-9-]{1,39})/([\w.-]{1,100}?)(?:\.git)?(?:/.*)?")
SHA256 = re.compile(r"[0-9a-f]{64}")
_lock = threading.Lock()


class SourceError(Exception):
    """A source address or listing that cannot be used; the message is shown as it is."""


@dataclass(frozen=True)
class Entry:
    id: str
    name: str
    version: str
    download: str
    sha256: str
    description: str = ""
    author: str = ""
    api: tuple | None = None
    icon: str = ""
    homepage: str = ""
    size: int = 0


@dataclass
class Source:
    url: str
    name: str = ""
    homepage: str = ""
    entries: list = field(default_factory=list)
    fetched: float = 0.0        # when the listing was read, 0 when never
    error: str = ""             # why the last read failed; the cached listing still shows

    @property
    def built_in(self) -> bool:
        return self.url == BUILT_IN

    def entry(self, plugin_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == plugin_id), None)


def allowed(url: str) -> bool:
    from pokeldn.app.plugin_updates import allowed as https
    return https(url)


def resolve(text: str) -> str:
    """The listing's address for what a player pasted: OWNER/REPO, a GitHub repository page, a folder
    address or the JSON file itself."""
    text = text.strip()
    slug = SLUG.fullmatch(text) or GITHUB.fullmatch(text)
    if slug:
        return f"https://raw.githubusercontent.com/{slug[1]}/{slug[2]}/HEAD/{FILE}"
    if not text:
        raise SourceError("Type a source address.")
    if not allowed(text):
        raise SourceError("A source must be an HTTPS address, or OWNER/REPO for a GitHub repository.")
    path = urllib.parse.urlsplit(text).path
    return text if path.endswith(".json") else text.rstrip("/") + "/" + FILE


def _text(value, limit: int = 2000) -> str:
    return value[:limit] if isinstance(value, str) else ""


def parse(url: str, data: bytes) -> Source:
    """Reads a listing; an entry that does not check is left out, a listing that does not is refused."""
    try:
        reply = json.loads(data)
    except (ValueError, RecursionError) as error:
        raise SourceError(f"The source is not a plugin listing ({error}).") from None
    if not isinstance(reply, dict) or not isinstance(reply.get("plugins"), list):
        raise SourceError("The source is not a plugin listing.")
    if reply.get("schema") != SCHEMA:
        raise SourceError("The source is written for another pokeldn. Update pokeldn.")
    entries, seen = [], set()
    for item in reply["plugins"][:MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue
        plugin_id, version = _text(item.get("id"), 64), _text(item.get("version"), 96)
        download, sha256 = _text(item.get("download"), 4096), _text(item.get("sha256"), 64).lower()
        if not plugin_store.ID.fullmatch(plugin_id) or plugin_id in seen or not plugin_store._version(version) \
                or not allowed(download) or not SHA256.fullmatch(sha256):
            continue
        icon, homepage = _text(item.get("icon"), 4096), _text(item.get("homepage"), 4096)
        size = item.get("size")
        seen.add(plugin_id)
        entries.append(Entry(plugin_id, _text(item.get("name"), 200) or plugin_id, version, download, sha256,
                             _text(item.get("description")), _text(item.get("author"), 200),
                             plugins.parse_api(item.get("api")), icon if allowed(icon) else "",
                             homepage if allowed(homepage) else "",
                             size if isinstance(size, int) and 0 < size <= plugin_store.MAX_BYTES else 0))
    homepage = _text(reply.get("homepage"), 4096)
    return Source(url, _text(reply.get("name"), 200), homepage if allowed(homepage) else "", entries)


# The followed sources and their cached listings live beside the plugins.

def _list_file() -> Path:
    return plugins.folder() / ".sources.json"


def _cache_file(url: str) -> Path:
    return plugins.folder() / ".source-cache" / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")


def followed() -> list[str]:
    """The built-in source first, then the ones the player added, in the order added."""
    try:
        added = json.loads(_list_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        added = []
    added = [u for u in added if isinstance(u, str) and allowed(u) and u != BUILT_IN] \
        if isinstance(added, list) else []
    return [BUILT_IN, *dict.fromkeys(added)]


def _write(urls: list[str]) -> None:
    path = _list_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([u for u in urls if u != BUILT_IN], indent=1), encoding="utf-8")
    os.replace(tmp, path)


def add(text: str) -> Source:
    """Reads the listing at what the player typed and follows it once it reads."""
    url = resolve(text)
    if url in followed():
        raise SourceError("That source is already in the list.")
    source = fetch(url)
    if source.error:
        raise SourceError(source.error)
    with _lock:
        _write([*followed(), url])
    return source


def remove(url: str) -> None:
    """Stops following a source; the plugins installed from it stay installed."""
    if url == BUILT_IN:
        raise SourceError("The built-in source cannot be removed.")
    with _lock:
        _write([u for u in followed() if u != url])
    _cache_file(url).unlink(missing_ok=True)


def cached(url: str) -> Source:
    """The listing read last time, or an empty one never read."""
    try:
        stored = json.loads(_cache_file(url).read_text(encoding="utf-8"))
        source = parse(url, json.dumps(stored["listing"]).encode())
        source.fetched = float(stored.get("fetched", 0))
        return source
    except (OSError, ValueError, KeyError, TypeError, SourceError):
        return Source(url, BUILT_IN_NAME if url == BUILT_IN else "")


def fetch(url: str) -> Source:
    """Reads the listing from the network and caches it; when that fails, the cached one with `error`."""
    from pokeldn.app import update
    try:
        with update._open(url, 20) as reply:
            data = update.read_bytes(reply, MAX_BYTES, 20)
        source = parse(url, data)
    except (OSError, SourceError) as error:
        source = cached(url)
        source.error = str(error) if isinstance(error, SourceError) else \
            f"There is no plugin listing at {url}." if getattr(error, "code", None) == 404 else \
            f"The source did not answer ({error})."
        return source
    source.fetched = time.time()
    path = _cache_file(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched": source.fetched, "listing": json.loads(data)}), encoding="utf-8")
    os.replace(tmp, path)
    return source


def label(source: Source) -> str:
    if source.name:
        return source.name
    parts = urllib.parse.urlsplit(source.url)
    slug = re.fullmatch(r"/([^/]+)/([^/]+)/[^/]+/" + re.escape(FILE), parts.path) \
        if parts.hostname == "raw.githubusercontent.com" else None
    return f"{slug[1]}/{slug[2]}" if slug else parts.netloc + parts.path.removesuffix("/" + FILE)


def state(entry: Entry, installed: plugins.Plugin | None) -> str:
    """install, update, installed, newer (the installed copy is newer than the listing) or
    incompatible (the listing names an API this pokeldn does not serve)."""
    if entry.api is not None and plugins.compatibility(entry.api)[0] in ("newer", "older"):
        return "incompatible"
    if installed is None:
        return "install"
    new, old = plugin_store._version(entry.version), plugin_store._version(installed.version)
    return "update" if new > old else "newer" if new < old else "installed"


def updates(found: list[plugins.Plugin], listings: list[Source]):
    """The installed plugins a followed source lists newer: each one's own source when it came from
    one, else the first source that lists it."""
    from pokeldn.app.plugin_updates import Available
    by_url = {s.url: s for s in listings}
    out = {}
    for plugin in found:
        if plugin.folder is None or plugin.folder.parent != plugins.folder():
            continue
        home = by_url.get(plugin_store.origin(plugin))
        candidates = [home] if home is not None else listings
        for source in candidates:
            entry = source.entry(plugin.id)
            if entry is not None and state(entry, plugin) == "update":
                out[plugin.id] = Available(plugin.id, entry.version, entry.download, source.homepage,
                                           entry.sha256, source.url)
                break
    return out

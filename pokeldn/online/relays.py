"""Nostr events (NIP-01) and a pool of public relays, one thread per relay, that publishes every
event to all of them and hands each received event on once (docs/online.md, The relays)."""
import hashlib
import json
import os
import random
import ssl
import threading
import time

from pokeldn.online import schnorr

# Relays that took and delivered 8 of 8 ephemeral events at one per 2 s (docs/online.md, The relays);
# POKELDN_RELAYS (comma-separated) replaces them.
DEFAULT_RELAYS = ("wss://relay.primal.net", "wss://relay.snort.social", "wss://offchain.pub",
                  "wss://relay.nostr.net", "wss://nostr.oxtr.dev", "wss://nostr-pub.wellorder.net")
RECONNECT_MIN, RECONNECT_MAX = 2.0, 30.0


def relay_urls() -> tuple[str, ...]:
    configured = os.environ.get("POKELDN_RELAYS", "")
    urls = tuple(u.strip() for u in configured.split(",") if u.strip())
    return urls or DEFAULT_RELAYS


class Identity:
    """A throwaway signing key: one per session, so nothing links two sessions."""

    def __init__(self, secret: bytes | None = None):
        while secret is None:
            candidate = os.urandom(32)
            if 0 < int.from_bytes(candidate, "big") < schnorr.N:
                secret = candidate
        self.secret = secret
        self.public = schnorr.public_key(secret).hex()

    def event(self, kind: int, tags: list, content: str, created_at: int | None = None) -> dict:
        created_at = int(time.time()) if created_at is None else created_at
        serial = json.dumps([0, self.public, created_at, kind, tags, content],
                            separators=(",", ":"), ensure_ascii=False)
        event_id = hashlib.sha256(serial.encode()).digest()
        return {"id": event_id.hex(), "pubkey": self.public, "created_at": created_at, "kind": kind,
                "tags": tags, "content": content, "sig": schnorr.sign(self.secret, event_id).hex()}


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class Relay(threading.Thread):
    def __init__(self, url, pool):
        super().__init__(name=f"relay {url}", daemon=True)
        self.url, self.pool = url, pool
        self.ws = None
        self.lock = threading.Lock()
        self.connected = False
        self.accepted = self.refused = 0
        self.reasons = set()

    def send(self, message) -> bool:
        with self.lock:
            ws = self.ws
        if ws is None:
            return False
        try:
            ws.send(json.dumps(message, separators=(",", ":"), ensure_ascii=False))
            return True
        except Exception:
            return False

    def run(self):
        from websockets.sync.client import connect
        delay = RECONNECT_MIN
        while not self.pool.closed.is_set():
            try:
                with connect(self.url, ssl=_ssl_context(), open_timeout=8, close_timeout=2,
                             proxy=None, max_size=1 << 20) as ws:
                    with self.lock:
                        self.ws = ws
                    for sub_id, filters in self.pool.subscriptions():
                        self.send(["REQ", sub_id, *filters])
                    self.connected = True
                    delay = RECONNECT_MIN
                    self.pool.changed(self)
                    while not self.pool.closed.is_set():
                        try:
                            raw = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        self._on_message(raw)
            except Exception as exc:
                if not self.pool.closed.is_set():
                    self.pool.log(f"[online] {self.url}: {type(exc).__name__} {exc}".rstrip())
            finally:
                with self.lock:
                    self.ws = None
                if self.connected:
                    self.connected = False
                    self.pool.changed(self)
            if self.pool.closed.wait(delay + random.random()):
                return
            delay = min(delay * 2, RECONNECT_MAX)

    def _on_message(self, raw):
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, list) or not message:
            return
        if message[0] == "EVENT" and len(message) >= 3 and isinstance(message[2], dict):
            self.pool.received(message[2])
        elif message[0] == "OK" and len(message) >= 3:
            if message[2]:
                self.accepted += 1
            else:
                self.refused += 1
                reason = str(message[3]) if len(message) > 3 else ""
                if reason not in self.reasons:
                    self.reasons.add(reason)
                    self.pool.log(f"[online] {self.url} refused an event: {reason}")
        elif message[0] == "NOTICE" and len(message) >= 2:
            self.pool.log(f"[online] {self.url}: {message[1]}")


class RelayPool:
    """Publishes to every connected relay; on_event(event) sees each event id once, on a relay thread."""

    def __init__(self, urls, on_event, log=print, on_change=None):
        self.on_event, self.log, self.on_change = on_event, log, on_change
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.subs: dict[str, list] = {}
        self.seen: dict[str, float] = {}
        self.relays = [Relay(url, self) for url in urls]

    def start(self):
        for relay in self.relays:
            relay.start()

    def close(self):
        self.closed.set()
        for relay in self.relays:
            relay.join(timeout=3)

    def connected(self) -> int:
        return sum(relay.connected for relay in self.relays)

    def changed(self, relay):
        if self.on_change:
            self.on_change(relay)

    def subscriptions(self):
        with self.lock:
            return list(self.subs.items())

    def subscribe(self, sub_id, *filters):
        with self.lock:
            self.subs[sub_id] = list(filters)
        for relay in self.relays:
            relay.send(["REQ", sub_id, *filters])

    def publish(self, event) -> int:
        with self.lock:
            self.seen[event["id"]] = time.time()
        return sum(relay.send(["EVENT", event]) for relay in self.relays)

    def received(self, event):
        event_id = event.get("id")
        if not isinstance(event_id, str):
            return
        now = time.time()
        with self.lock:
            if event_id in self.seen:
                return
            self.seen[event_id] = now
            if len(self.seen) > 4096:
                self.seen = {k: t for k, t in self.seen.items() if now - t < 120}
        try:
            self.on_event(event)
        except Exception as exc:
            self.log(f"[online] an event handler failed: {type(exc).__name__} {exc}")

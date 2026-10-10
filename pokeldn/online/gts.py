"""The GTS: a listing any app reads from public relays, and the sealed wraps that trade against it
(docs/online.md, The GTS). Nothing here reads a record: the bank hands records in as bytes with what
PKHeX said of them."""
import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass

from pokeldn.online import relays, schnorr
from pokeldn.online.link import _open, _seal

PROTOCOL = 1
LISTING = 30402        # NIP-99 classified listing: addressable, a relay keeps the newest per key and d
WRAP = 1059            # NIP-59 gift wrap: stored, read by its p key
DELETION = 5
TAG = "pokeldn-gts"
LIFETIME = 30 * 86400
SKEW = 3600            # clocks disagree; an ended listing is believed ended this much later
# Relays that kept a listing and a wrap from a fresh key and served them back (docs/online.md, Stored
# events); relay.snort.social keeps nothing. POKELDN_GTS_RELAYS (comma-separated) replaces them.
DEFAULT_RELAYS = ("wss://relay.primal.net", "wss://nostr.oxtr.dev", "wss://nos.lol", "wss://nostr.mom",
                  "wss://offchain.pub", "wss://nostr-pub.wellorder.net", "wss://relay.nostr.net")
SHOWN = ("species", "species_id", "form", "level", "shiny", "nickname", "nature", "ability", "ball",
         "held_item", "moves", "ot", "legal")


def relay_urls() -> tuple[str, ...]:
    urls = tuple(u.strip() for u in os.environ.get("POKELDN_GTS_RELAYS", "").split(",") if u.strip())
    return urls or DEFAULT_RELAYS


def has_tag(species: int) -> str:
    return f"{TAG}-has-{int(species)}"


def wants_tag(species: int) -> str:
    return f"{TAG}-wants-{int(species)}"


def _tag(event, name):
    return next((t[1] for t in event.get("tags") or [] if len(t) >= 2 and t[0] == name), None)


def _key(identity: relays.Identity, public: str) -> bytes:
    return hashlib.sha256(b"pokeldn gts|" + schnorr.shared_x(identity.secret, bytes.fromhex(public))).digest()


def digest(record: bytes) -> str:
    return hashlib.sha256(record).hexdigest()


@dataclass(frozen=True)
class Wants:
    species: int
    name: str
    min_level: int = 1
    max_level: int = 100

    def refusal(self, species: int, level: int) -> str:
        """Why a Pokemon does not answer the listing, or ""."""
        if species != self.species:
            return f"the lister asks for {self.name}"
        if not self.min_level <= level <= self.max_level:
            return f"the lister asks for level {self.min_level} to {self.max_level}"
        return ""

    def text(self) -> str:
        if (self.min_level, self.max_level) == (1, 100):
            return self.name
        return f"{self.name}, level {self.min_level} to {self.max_level}"


@dataclass(frozen=True)
class Listing:
    key: str               # the listing's own signing key, made for it alone
    d: str
    created: int
    expires: int
    status: str            # active, traded, withdrawn
    game: str              # the catalog key of the game the record is in
    pokemon: dict          # SHOWN fields
    sha256: str
    wants: Wants
    trainer: str
    winner: str            # the offer event a traded listing took
    event: dict

    @property
    def address(self) -> str:
        return f"{LISTING}:{self.key}:{self.d}"

    def open(self, now: float) -> bool:
        return self.status == "active" and now < self.expires


def listing_event(identity, d, game, info, record, wants: Wants, trainer, app, expires, status="active",
                  winner="", created_at=None) -> dict:
    pokemon = {k: info.get(k) for k in SHOWN}
    title = f"{pokemon['species']} for {wants.name}"
    content = {"v": PROTOCOL, "game": game, "pokemon": pokemon, "sha256": digest(record),
               "wants": {"species": wants.species, "name": wants.name, "min_level": wants.min_level,
                         "max_level": wants.max_level},
               "trainer": trainer[:24], "app": app, "status": status, "winner": winner}
    tags = [["d", d], ["t", TAG], ["t", has_tag(pokemon["species_id"])], ["t", wants_tag(wants.species)],
            ["title", title], ["summary", f"pokeldn GTS: {title}"], ["status", status],
            ["published_at", str(int(time.time()))], ["expiration", str(int(expires))]]
    return identity.event(LISTING, tags, json.dumps(content, separators=(",", ":"), ensure_ascii=False),
                          created_at=created_at)


def parse_listing(event) -> Listing | None:
    """A listing read from a relay, or None for anything else or anything forged."""
    if event.get("kind") != LISTING or ["t", TAG] not in (event.get("tags") or []) or not relays.valid(event):
        return None
    try:
        body = json.loads(event["content"])
        wants = body["wants"]
        return Listing(event["pubkey"], str(_tag(event, "d")), int(event["created_at"]),
                       int(_tag(event, "expiration") or 0), str(body.get("status", "active")),
                       str(body["game"]), {k: body["pokemon"].get(k) for k in SHOWN}, str(body["sha256"]),
                       Wants(int(wants["species"]), str(wants["name"])[:32], int(wants.get("min_level", 1)),
                             int(wants.get("max_level", 100))),
                       str(body.get("trainer", ""))[:24], str(body.get("winner", "")), event)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def wrap(identity, to: str, body: dict, expires: int) -> dict:
    """A stored event only `to` can open: AES-GCM under the two keys' shared secret."""
    content = _seal(_key(identity, to), dict(body, v=PROTOCOL))
    return identity.event(WRAP, [["p", to], ["expiration", str(int(expires))]], content)


def unwrap(identity, event) -> dict | None:
    """-> the body of a wrap addressed to `identity`, with "from" and "id" added, or None."""
    if event.get("kind") != WRAP or _tag(event, "p") != identity.public or not relays.valid(event):
        return None
    try:
        body = _open(_key(identity, event["pubkey"]), event["content"])
    except ValueError:
        return None
    if body is None or body.get("v") != PROTOCOL:
        return None
    return dict(body, **{"from": event["pubkey"], "id": event["id"]})


def offer_body(listing: Listing, game, record, trainer) -> dict:
    return {"t": "offer", "listing": listing.d, "game": game,
            "record": base64.b64encode(record).decode(), "trainer": trainer[:24]}


def trade_body(listing_d, offer_id, game, record) -> dict:
    return {"t": "trade", "listing": listing_d, "offer": offer_id, "game": game,
            "record": base64.b64encode(record).decode()}


def refusal_body(listing_d, offer_id, why) -> dict:
    return {"t": "refused", "listing": listing_d, "offer": offer_id, "why": str(why)[:200]}


def record_of(body) -> bytes | None:
    try:
        return base64.b64decode(body.get("record", ""), validate=True) or None
    except (ValueError, TypeError):
        return None


def deletion(identity, events) -> dict:
    """NIP-09: asks every relay to drop these events, all signed by `identity`."""
    tags = [["e", e["id"]] for e in events]
    tags += [["a", f"{e['kind']}:{e['pubkey']}:{_tag(e, 'd')}"] for e in events if _tag(e, "d") is not None]
    return identity.event(DELETION, tags, "")

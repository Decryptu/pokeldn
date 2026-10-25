"""The GTS: a listing any app reads from public relays, and the sealed wraps that trade against it
(docs/online.md, The GTS). Nothing here reads a record: the bank hands records in as bytes with what
PKHeX said of them."""
import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

from pokeldn.online import relays, schnorr
from pokeldn.online.link import _open, _seal
from pokeldn.pokemon import EXTENSIONS, RECORD_LIMIT

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
EVENT_LIMIT = 8192
MAX_WANTS = 3          # "wants" plus up to two in "also"; an app before "also" reads only "wants"


def _text(value, limit):
    return isinstance(value, str) and len(value) <= limit


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _event(event, kind):
    if not isinstance(event, dict) or event.get("kind") != kind:
        return False
    tags = event.get("tags")
    if (not isinstance(tags, list) or len(tags) > 32
            or not all(isinstance(tag, list) and 1 <= len(tag) <= 4
                       and all(_text(s, 256) for s in tag) for tag in tags)
            or not _text(event.get("content"), EVENT_LIMIT)
            or not _integer(event.get("created_at"), 0, 4102444800)):
        return False
    for name in ("d", "p", "expiration"):
        if sum(tag[0] == name for tag in tags) > 1:
            return False
    try:
        return len(json.dumps(event).encode()) <= EVENT_LIMIT and relays.valid(event)
    except (ValueError, TypeError, RecursionError):
        return False


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
    shiny: bool = False

    def refusal(self, species: int, level: int, shiny: bool = False) -> str:
        """Why a Pokemon does not answer the listing, or ""."""
        if species != self.species:
            return f"the lister asks for {self.name}"
        if not self.min_level <= level <= self.max_level:
            return f"the lister asks for level {self.min_level} to {self.max_level}"
        if self.shiny and not shiny:
            return f"the lister asks for a shiny {self.name}"
        return ""

    def text(self) -> str:
        name = f"shiny {self.name}" if self.shiny else self.name
        if (self.min_level, self.max_level) == (1, 100):
            return name
        return f"{name}, level {self.min_level} to {self.max_level}"

    def wire(self) -> dict:
        """The listing's form: "shiny" only when asked, so a plain want reads as before it existed."""
        body = {"species": self.species, "name": self.name, "min_level": self.min_level,
                "max_level": self.max_level}
        return {**body, "shiny": True} if self.shiny else body


def refusal(wanted, species: int, level: int, shiny: bool = False) -> str:
    """Why a Pokemon answers none of a listing's wants, or "": the first want's reason, or all names."""
    reasons = [w.refusal(species, level, shiny) for w in wanted]
    if all(reasons):
        return reasons[0] if len(wanted) == 1 else "the lister asks for " + " or ".join(w.text() for w in wanted)
    return ""


def _wants(value) -> Wants:
    low, high, shiny = value.get("min_level", 1), value.get("max_level", 100), value.get("shiny", False)
    if (not _integer(value["species"], 1, 2048) or not _text(value["name"], 32)
            or not _integer(low, 1, 100) or not _integer(high, low, 100) or type(shiny) is not bool):
        raise ValueError("a want out of range")
    return Wants(value["species"], value["name"], low, high, shiny)


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
    wants: Wants           # the first want: all an app before "also" reads
    trainer: str
    winner: str            # the offer event a traded listing took
    event: dict
    also: tuple = ()       # further Wants, any of which answers too

    @property
    def wanted(self) -> tuple:
        return (self.wants, *self.also)

    @property
    def address(self) -> str:
        return f"{LISTING}:{self.key}:{self.d}"

    def open(self, now: float) -> bool:
        return self.status == "active" and now < self.expires


def listing_event(identity, d, game, info, record, wants, trainer, app, expires, status="active",
                  winner="", created_at=None) -> dict:
    """`wants` is one Wants or up to MAX_WANTS of them, the first read by every app."""
    wanted = (wants,) if isinstance(wants, Wants) else tuple(wants)
    if not 1 <= len(wanted) <= MAX_WANTS:
        raise ValueError(f"a listing asks for 1 to {MAX_WANTS} Pokemon")
    pokemon = {k: info.get(k) for k in SHOWN}
    title = f"{pokemon['species']} for {' or '.join(w.text() for w in wanted)}"
    content = {"v": PROTOCOL, "game": game, "pokemon": pokemon, "sha256": digest(record),
               "wants": wanted[0].wire(),
               "trainer": trainer[:24], "app": app, "status": status, "winner": winner}
    if len(wanted) > 1:
        content["also"] = [w.wire() for w in wanted[1:]]
    species = list(dict.fromkeys(w.species for w in wanted))
    tags = [["d", d], ["t", TAG], ["t", has_tag(pokemon["species_id"])],
            *(["t", wants_tag(s)] for s in species),
            ["title", title], ["summary", f"pokeldn GTS: {title}"], ["status", status],
            ["published_at", str(int(time.time()))], ["expiration", str(int(expires))]]
    return identity.event(LISTING, tags, json.dumps(content, separators=(",", ":"), ensure_ascii=False),
                          created_at=created_at)


def parse_listing(event) -> Listing | None:
    """A listing read from a relay, or None for anything else or anything forged."""
    if not _event(event, LISTING) or ["t", TAG] not in event["tags"]:
        return None
    try:
        body = json.loads(event["content"])
        wanted = [_wants(w) for w in [body["wants"], *body.get("also", [])]]
        pokemon = body["pokemon"]
        d, expires = _tag(event, "d"), int(_tag(event, "expiration") or 0)
        if (type(body.get("v")) is not int or body["v"] != PROTOCOL
                or not _text(d, 64) or not d or not 0 < expires <= 4102444800
                or not isinstance(body["game"], str) or body["game"] not in EXTENSIONS
                or not _hash(body["sha256"])
                or body.get("status", "active") not in ("active", "traded", "withdrawn")
                or not _integer(pokemon["species_id"], 1, 2048)
                or not _integer(pokemon["level"], 1, 100)
                or not all(_text(pokemon.get(k), 96) for k in SHOWN
                           if k not in ("species_id", "level", "shiny", "legal", "moves"))
                or type(pokemon.get("shiny")) is not bool or type(pokemon.get("legal")) is not bool
                or not isinstance(pokemon.get("moves"), list) or len(pokemon["moves"]) > 4
                or not all(_text(move, 96) for move in pokemon["moves"])
                or not isinstance(body.get("also", []), list) or len(wanted) > MAX_WANTS
                or not _text(body.get("trainer", ""), 24)
                or not _text(body.get("app", ""), 64)
                or not (body.get("winner", "") == "" or _hash(body["winner"]))):
            return None
        return Listing(event["pubkey"], d, event["created_at"], expires, body.get("status", "active"),
                       body["game"], {k: pokemon[k] for k in SHOWN}, body["sha256"],
                       wanted[0], body.get("trainer", ""), body.get("winner", ""), event, tuple(wanted[1:]))
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return None


def wrap(identity, to: str, body: dict, expires: int) -> dict:
    """A stored event only `to` can open: AES-GCM under the two keys' shared secret."""
    content = _seal(_key(identity, to), dict(body, v=PROTOCOL))
    return identity.event(WRAP, [["p", to], ["expiration", str(int(expires))]], content)


def unwrap(identity, event) -> dict | None:
    """-> the body of a wrap addressed to `identity`, with "from" and "id" added, or None."""
    if not _event(event, WRAP) or _tag(event, "p") != identity.public:
        return None
    try:
        body = _open(_key(identity, event["pubkey"]), event["content"])
    except (ValueError, TypeError, RecursionError):
        return None
    if (body is None or type(body.get("v")) is not int or body.get("v") != PROTOCOL
            or body.get("t") not in ("offer", "trade", "refused")
            or not _text(body.get("listing"), 64) or not body["listing"]):
        return None
    if body["t"] in ("offer", "trade"):
        if (not isinstance(body.get("game"), str) or body["game"] not in EXTENSIONS
                or not _text(body.get("record"), 4 * ((RECORD_LIMIT + 2) // 3))
                or not _text(body.get("trainer", ""), 24)):
            return None
    if body["t"] in ("trade", "refused") and not _hash(body.get("offer")):
        return None
    if body["t"] == "refused" and not _text(body.get("why", ""), 200):
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
        encoded = body.get("record", "")
        if not _text(encoded, 4 * ((RECORD_LIMIT + 2) // 3)):
            return None
        record = base64.b64decode(encoded, validate=True)
        return record if 0 < len(record) <= RECORD_LIMIT else None
    except (ValueError, TypeError):
        return None


def deletion(identity, events) -> dict:
    """NIP-09: asks every relay to drop these events, all signed by `identity`."""
    tags = [["e", e["id"]] for e in events]
    tags += [["a", f"{e['kind']}:{e['pubkey']}:{_tag(e, 'd')}"] for e in events if _tag(e, "d") is not None]
    return identity.event(DELETION, tags, "")

"""The GTS as the app runs it: a banked Pokemon deposited against a wanted species, offers on other
players' listings, and the answers. Each listing and offer is a folder in the GTS folder holding its
key, its record and its signed events, so an app opened later answers and settles where it stopped
[pokeldn.online.gts, docs/online.md, The GTS]."""
import json
import os
import shutil
import threading
import time
from pathlib import Path

from pokeldn.app import bank
from pokeldn.app.paths import GTS
from pokeldn.online import gts, relays
from pokeldn.pokemon import EXTENSIONS

TICK = 5.0
REPUBLISH = 6 * 3600
PURGE_AFTER = 60 * 86400
LISTINGS_SHOWN = 300


class GtsError(Exception):
    pass


def check(game, record):
    """-> (why the GTS refuses it or "", what PKHeX said). Nobody watches an answer go out, so only a
    Pokemon PKHeX finds legal is deposited, offered or taken."""
    from pokeldn import pokemon
    try:
        reply = pokemon.SERVICE.check_bytes(game, record)
    except pokemon.BuilderError as exc:
        return f"PKHeX could not read it ({exc})", {}
    if not reply.get("legal"):
        report = [line.strip() for line in str(reply.get("report", "")).splitlines() if line.strip()]
        return f"PKHeX finds it not legal ({report[0] if report else 'not legal'})", reply
    return "", reply


class Service:
    """States: each one a dict saved as <folder>/<id>/state.json.

    listing: status active, traded, withdrawn or ended; answers maps each offer id to the signed wrap
    that answered it. offer: status waiting, traded or returned."""

    def __init__(self, folder=None, bank_dir=None, trainer="", app="", validate=check, log=print,
                 pool_factory=None, clock=time.time):
        self.folder = Path(folder or GTS)
        self.bank_dir = bank_dir
        self.trainer, self.app, self.validate, self.log, self.clock = trainer, app, validate, log, clock
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.states: dict[str, dict] = {}
        self.listings: dict[tuple, gts.Listing] = {}   # (key, d) -> the newest seen
        self.browsed: set[str] = set()                  # relays that finished sending stored listings
        self.caught_up = 0.0                            # when a relay last finished sending our wraps
        self.held: list[tuple] = []                     # offers stored before that, answered oldest first
        self.listeners: list = []
        self.last_republish = 0.0
        factory = pool_factory or (lambda on_event, on_eose, on_change: relays.RelayPool(
            gts.relay_urls(), on_event, log=log, on_eose=on_eose, on_change=on_change))
        self.pool = factory(self._on_event, self._on_eose, self._on_relay)
        self.thread = threading.Thread(target=self._run, name="gts", daemon=True)

    # Lifetime

    def start(self, thread=True):
        self._load()
        self._subscribe()
        self.pool.start()
        if thread:
            self.thread.start()

    def close(self):
        self.closed.set()
        threading.Thread(target=self.pool.close, name="gts close", daemon=True).start()

    def connected(self) -> int:
        return self.pool.connected()

    def _load(self):
        if not self.folder.is_dir():
            return
        for path in self.folder.glob("*/state.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(state, dict) and state.get("id") == path.parent.name:
                self.states[state["id"]] = state

    def _save(self, state):
        state["changed"] = self.clock()
        home = self.folder / state["id"]
        home.mkdir(parents=True, exist_ok=True)
        tmp = home / "state.tmp"
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, home / "state.json")

    def _changed(self):
        for listener in list(self.listeners):
            try:
                listener()
            except Exception as exc:
                self.log(f"[gts] a listener failed: {type(exc).__name__} {exc}")

    # What the page shows

    def mine(self) -> list[dict]:
        with self.lock:
            return sorted((dict(s) for s in self.states.values()), key=lambda s: s.get("created", 0),
                          reverse=True)

    def browse(self, has: int | None = None, wants: int | None = None):
        """Ask the relays for open listings, all of them or those with or wanting one species."""
        tag = gts.has_tag(has) if has else gts.wants_tag(wants) if wants else gts.TAG
        with self.lock:
            self.browsed = set()
        self.pool.subscribe("gts-browse", {"kinds": [gts.LISTING], "#t": [tag], "limit": LISTINGS_SHOWN})

    def open_listings(self, has: int | None = None, wants: int | None = None) -> list[gts.Listing]:
        now = self.clock()
        with self.lock:
            own = {s["key"] for s in self.states.values() if s["role"] == "listing"}
            found = [x for x in self.listings.values() if x.open(now) and x.key not in own
                     and (not has or x.pokemon.get("species_id") == has)
                     and (not wants or x.wants.species == wants)]
        return sorted(found, key=lambda x: x.created, reverse=True)

    def loaded(self) -> int:
        """Relays that finished sending the stored listings asked for."""
        with self.lock:
            return len(self.browsed)

    # The player's actions

    def deposit(self, entry: bank.Entry, wants: gts.Wants) -> dict:
        """Take a banked Pokemon out of the bank and list it until LIFETIME passes or a matching offer
        arrives."""
        record = bank.data(entry)
        reason, info = self.validate(entry.game, record)
        if reason:
            raise GtsError(reason)
        identity = relays.Identity()
        now = self.clock()
        d = os.urandom(8).hex()
        expires = int(now + gts.LIFETIME)
        event = gts.listing_event(identity, d, entry.game, info, record, wants, self.trainer, self.app,
                                  expires, created_at=int(now))
        state = {"role": "listing", "id": d, "secret": identity.secret.hex(), "key": identity.public,
                 "game": entry.game, "entry": entry.id, "info": {k: info.get(k) for k in gts.SHOWN},
                 "wants": vars(wants), "expires": expires, "status": "active", "event": event,
                 "answers": {}, "winner": "", "received": "", "partner": "", "created": now}
        with self.lock:
            self._take(state, entry)
            self.states[d] = state
            self._save(state)
        self.pool.publish(event)
        self._subscribe()
        self.log(f"[gts] listed {info.get('species')} for {wants.text()}")
        self._changed()
        return state

    def withdraw(self, state_id: str):
        """Take a listing down and put its Pokemon back in the bank. An offer that arrives later is
        refused."""
        with self.lock:
            state = self.states[state_id]
            if state["status"] != "active":
                raise GtsError("This listing is no longer open.")
            event = self._relist(state, "withdrawn", expires=min(state["expires"], int(self.clock()) + 3 * 86400))
            state["status"] = "withdrawn"
            self._give_back(state)
            self._save(state)
        self.pool.publish(event)
        self._changed()

    def offer(self, listing: gts.Listing, entry: bank.Entry) -> dict:
        """Send a banked Pokemon to a listing. It waits outside the bank until the lister's app answers:
        their Pokemon comes back, or a refusal and ours comes back."""
        now = self.clock()
        if not listing.open(now):
            raise GtsError("This listing is no longer open.")
        record = bank.data(entry)
        reason, info = self.validate(entry.game, record)
        if reason:
            raise GtsError(reason)
        why = listing.wants.refusal(int(info.get("species_id") or 0), int(info.get("level") or 0))
        if why:
            raise GtsError(why[0].upper() + why[1:] + ".")
        identity = relays.Identity()
        event = gts.wrap(identity, listing.key, gts.offer_body(listing, entry.game, record, self.trainer),
                         expires=listing.expires + gts.SKEW)
        state = {"role": "offer", "id": "o" + event["id"][:16], "secret": identity.secret.hex(),
                 "key": identity.public, "game": entry.game, "entry": entry.id,
                 "info": {k: info.get(k) for k in gts.SHOWN}, "listing": listing.event,
                 "expires": listing.expires, "status": "waiting", "event": event, "why": "",
                 "received": "", "created": now}
        with self.lock:
            self._take(state, entry)
            self.states[state["id"]] = state
            self._save(state)
        self.pool.publish(event)
        self._subscribe()
        self.log(f"[gts] offered {info.get('species')} for {listing.pokemon.get('species')}")
        self._changed()
        return state

    def forget(self, state_id: str):
        """Drop a finished listing or offer from the page; its Pokemon is wherever it ended."""
        with self.lock:
            state = self.states.get(state_id)
            if state is None or state["status"] in ("active", "waiting"):
                return
            self.states.pop(state_id)
            shutil.rmtree(self.folder / state_id, ignore_errors=True)
        self._subscribe()
        self._changed()

    # Moving the record between the bank and the GTS folder

    def _take(self, state, entry):
        home = self.folder / state["id"]
        home.mkdir(parents=True, exist_ok=True)
        extension = Path(entry.path).suffix
        shutil.move(entry.path, home / f"record{extension}")
        meta = Path(entry.path).with_suffix(".json")
        if meta.exists():
            shutil.move(str(meta), home / "record.json")
        state["file"] = f"record{extension}"

    def _record(self, state) -> bytes:
        return (self.folder / state["id"] / state["file"]).read_bytes()

    def _give_back(self, state):
        home = self.folder / state["id"]
        target = Path(self.bank_dir or bank.BANK)
        target.mkdir(parents=True, exist_ok=True)
        record = home / state["file"]
        if record.exists():
            shutil.move(str(record), target / f"{state['entry']}{record.suffix}")
        if (home / "record.json").exists():
            shutil.move(str(home / "record.json"), target / f"{state['entry']}.json")

    def _let_go(self, state):
        """The Pokemon went to the other player."""
        for name in (state["file"], "record.json"):
            (self.folder / state["id"] / name).unlink(missing_ok=True)

    def _bank_received(self, state, game, record, info) -> str:
        path = self.folder / state["id"] / f"received.{EXTENSIONS[game]}"
        path.write_bytes(record)
        entry = bank.deposit(game, str(path), info, folder=self.bank_dir)
        return entry.id if entry else ""

    def _relist(self, state, status, expires=None, winner=""):
        identity = relays.Identity(bytes.fromhex(state["secret"]))
        state["expires"] = expires or state["expires"]
        state["event"] = gts.listing_event(
            identity, state["id"], state["game"], state["info"], self._record(state),
            gts.Wants(**state["wants"]), self.trainer, self.app, state["expires"], status=status,
            winner=winner, created_at=max(int(self.clock()), state["event"]["created_at"] + 1))
        return state["event"]

    # Relays

    def _subscribe(self):
        with self.lock:
            keys = [s["key"] for s in self.states.values()
                    if (s["role"] == "listing" and s["status"] != "ended") or s["status"] == "waiting"]
            waiting = [gts.parse_listing(s["listing"]) for s in self.states.values()
                       if s["role"] == "offer" and s["status"] == "waiting"]
        filters = [{"kinds": [gts.WRAP], "#p": keys}] if keys else []
        if any(waiting):
            filters.append({"kinds": [gts.LISTING], "authors": sorted({x.key for x in waiting if x}),
                            "#d": sorted({x.d for x in waiting if x})})
        if filters:
            self.pool.subscribe("gts-mine", *filters)

    def _live(self) -> list[dict]:
        """Every event of ours a relay should still hold."""
        now = self.clock()
        events = []
        with self.lock:
            for state in self.states.values():
                if state["role"] == "listing":
                    if state["status"] != "ended" and now < state["expires"]:
                        events.append(state["event"])
                    events += list(state["answers"].values())
                elif state["status"] == "waiting":
                    events.append(state["event"])
                if state.get("deletion"):
                    events.append(state["deletion"])
        return events

    def _on_relay(self, relay):
        if relay.connected:
            for event in self._live():
                relay.send(["EVENT", event])

    def _on_eose(self, url, sub_id):
        with self.lock:
            if sub_id == "gts-browse":
                self.browsed.add(url)
            elif sub_id == "gts-mine":
                self.caught_up = self.clock()
                held, self.held = sorted(self.held, key=lambda h: h[0]), []
                for _, state_id, body in held:
                    if state_id in self.states:
                        self._answer(self.states[state_id], body)
        self._changed()

    def _on_event(self, event):
        kind = event.get("kind")
        if kind == gts.LISTING:
            listing = gts.parse_listing(event)
            if listing is None:
                return
            with self.lock:
                known = self.listings.get((listing.key, listing.d))
                if known is None or listing.created > known.created:
                    self.listings[(listing.key, listing.d)] = listing
                for state in list(self.states.values()):
                    if (state["role"] == "offer" and state["status"] == "waiting"
                            and state["listing"]["pubkey"] == listing.key):
                        self._listing_moved(state, listing)
            self._changed()
        elif kind == gts.WRAP:
            to = next((t[1] for t in event.get("tags") or [] if len(t) >= 2 and t[0] == "p"), None)
            with self.lock:
                state = next((s for s in self.states.values() if s["key"] == to), None)
                if state is None:
                    return
                body = gts.unwrap(relays.Identity(bytes.fromhex(state["secret"])), event)
                if body is None:
                    return
                if state["role"] == "listing" and body.get("t") == "offer":
                    if self.caught_up:
                        self._answer(state, body)
                    else:       # a relay sends stored events newest first; the first offer made wins
                        self.held.append((event.get("created_at", 0), state["id"], body))
                elif (state["role"] == "offer" and body.get("t") in ("trade", "refused")
                      and body.get("offer") == state["event"]["id"] and body["from"] == state["listing"]["pubkey"]):
                    self._settle(state, body)
            self._changed()

    # The lister's app answers an offer

    def _answer(self, state, body):
        offer_id = body["id"]
        identity = relays.Identity(bytes.fromhex(state["secret"]))
        if offer_id in state["answers"]:
            self.pool.publish(state["answers"][offer_id])
            return
        now = self.clock()
        record, game = gts.record_of(body), body.get("game")
        info = {}
        if state["status"] == "traded":
            why = "another offer was taken first"
        elif state["status"] != "active" or now >= state["expires"]:
            why = "the listing has ended"
        elif game not in EXTENSIONS or record is None:
            why = "the offer carries no Pokemon"
        else:
            why, info = self.validate(game, record)
            why = why or gts.Wants(**state["wants"]).refusal(int(info.get("species_id") or 0),
                                                             int(info.get("level") or 0))
        expires = int(now + gts.LIFETIME)
        if why:
            reply = gts.wrap(identity, body["from"], gts.refusal_body(state["id"], offer_id, why), expires)
            state["answers"][offer_id] = reply
            self._save(state)
            self.pool.publish(reply)
            self.log(f"[gts] refused an offer on {state['info'].get('species')}: {why}")
            return
        reply = gts.wrap(identity, body["from"],
                         gts.trade_body(state["id"], offer_id, state["game"], self._record(state)), expires)
        sold = self._relist(state, "traded", winner=offer_id)
        state.update(status="traded", winner=offer_id, partner=str(body.get("trainer", ""))[:24])
        state["answers"][offer_id] = reply
        self._save(state)           # before anything leaves: a restart publishes the same answer again
        self.pool.publish(reply)
        self.pool.publish(sold)
        state["received"] = self._bank_received(state, game, record, info)
        self._let_go(state)
        self._save(state)
        self.log(f"[gts] traded {state['info'].get('species')} for {info.get('species')}")

    # The offering app learns the answer

    def _settle(self, state, body):
        if state["status"] != "waiting":
            return
        identity = relays.Identity(bytes.fromhex(state["secret"]))
        if body["t"] == "refused":
            self._return(state, str(body.get("why", ""))[:200] or "refused")
        else:
            record, game = gts.record_of(body), body.get("game")
            listing = gts.parse_listing(state["listing"])
            if record is None or game not in EXTENSIONS:
                state["why"] = "the lister's answer carries no Pokemon"
                info = {}
            else:
                why, info = self.validate(game, record)
                if listing and gts.digest(record) != listing.sha256:
                    why = why or "it is not the Pokemon the listing showed"
                state["why"] = why
                (self.folder / state["id"] / f"received.{EXTENSIONS[game]}").write_bytes(record)
                if info:
                    state["received"] = self._bank_received(state, game, record, info)
            state["status"] = "traded"
            self._let_go(state)
            self._save(state)
            self.log(f"[gts] received {info.get('species', 'a Pokemon')} for {state['info'].get('species')}")
        self._delete(state, identity)
        self._subscribe()

    def _delete(self, state, identity):
        """Kept, and sent again to each relay that connects: a relay down now still drops the event."""
        state["deletion"] = gts.deletion(identity, [state["event"]])
        self._save(state)
        self.pool.publish(state["deletion"])

    def _listing_moved(self, state, listing):
        if listing.status == "traded" and listing.winner and listing.winner != state["event"]["id"]:
            self._return(state, "another offer was taken first")
        elif listing.status == "withdrawn":
            self._return(state, "the lister took the listing down")

    def _return(self, state, why):
        state.update(status="returned", why=why)
        self._give_back(state)
        self._save(state)
        self.log(f"[gts] {state['info'].get('species')} is back in the bank: {why}")

    # The clock

    def _run(self):
        while not self.closed.wait(TICK):
            self.tick()

    def tick(self):
        try:
            changed = self._tick()
        except Exception as exc:
            self.log(f"[gts] {type(exc).__name__}: {exc}")
            return
        if changed:
            self._changed()

    def _tick(self) -> bool:
        now = self.clock()
        changed = False
        with self.lock:
            for state in list(self.states.values()):
                if state["role"] == "listing" and state["status"] == "active" and now >= state["expires"]:
                    # Ended unanswered: no offer is taken after this, whatever arrives.
                    state["status"] = "ended"
                    self._give_back(state)
                    self._save(state)
                    self._delete(state, relays.Identity(bytes.fromhex(state["secret"])))
                    changed = True
                elif (state["role"] == "offer" and state["status"] == "waiting"
                      and self.caught_up > state["expires"] + gts.SKEW):
                    # The relays sent every stored answer after the listing ended, and none was ours.
                    self._return(state, "the listing ended with no answer")
                    changed = True
                elif (state["status"] not in ("active", "waiting")
                      and now - state.get("changed", now) > PURGE_AFTER):
                    self.states.pop(state["id"])
                    shutil.rmtree(self.folder / state["id"], ignore_errors=True)
                    changed = True
        if now - self.last_republish > REPUBLISH:
            self.last_republish = now
            for event in self._live():
                self.pool.publish(event)
        if changed:
            self._subscribe()
        return changed

"""The GTS between three players' apps, each with its own bank, over a relay that stores events the way
the measured relays did (docs/online.md, Stored events), with records PKHeX built and checks."""
import base64
import json

import pytest

from pokeldn.app import bank
from pokeldn.app.gts import GtsError, Service
from pokeldn.online import gts, relays
from test_pokemon_service import TRAINER, service  # noqa: F401  (the PKHeX helper, built once)

DAY = 86400.0


def _matches(f, event):
    if "kinds" in f and event["kind"] not in f["kinds"]:
        return False
    if "authors" in f and event["pubkey"] not in f["authors"]:
        return False
    for name, wanted in f.items():
        if name.startswith("#"):
            values = {t[1] for t in event["tags"] if len(t) >= 2 and t[0] == name[1:]}
            if not values & set(wanted):
                return False
    return True


class Relay:
    """One stored relay: addressable events replaced by (kind, key, d), NIP-09 deletions, NIP-40 expiry,
    stored events then EOSE on a subscription, live events after it. Delivery waits for pump()."""

    def __init__(self, clock):
        self.clock = clock
        self.events: dict[str, dict] = {}
        self.pools: list = []
        self.queue: list = []
        self.drop = lambda event: False      # an event the relay never receives

    def _expired(self, event):
        expiry = next((t[1] for t in event["tags"] if t[0] == "expiration"), None)
        return expiry is not None and self.clock() >= int(expiry)

    def store(self, event):
        if self.drop(event):
            return
        assert relays.valid(event)
        if event["id"] in self.events:
            return
        if 30000 <= event["kind"] < 40000:
            d = next(t[1] for t in event["tags"] if t[0] == "d")
            for old in [e for e in self.events.values() if e["kind"] == event["kind"]
                        and e["pubkey"] == event["pubkey"] and ["d", d] in e["tags"]]:
                if old["created_at"] >= event["created_at"]:
                    return
                del self.events[old["id"]]
        if event["kind"] == gts.DELETION:
            gone = {t[1] for t in event["tags"] if t[0] == "e"}
            for old in [e for e in self.events.values() if e["id"] in gone and e["pubkey"] == event["pubkey"]]:
                del self.events[old["id"]]
        self.events[event["id"]] = event
        for pool in self.pools:
            for sub_id, filters in pool.subs.items():
                if any(_matches(f, event) for f in filters):
                    self.queue.append((pool, "EVENT", event))

    def subscribe(self, pool, sub_id, filters):
        found = [e for e in self.events.values() if not self._expired(e) and any(_matches(f, e) for f in filters)]
        for event in sorted(found, key=lambda e: -e["created_at"]):
            self.queue.append((pool, "EVENT", event))
        self.queue.append((pool, "EOSE", sub_id))

    def pool(self, on_event, on_eose, on_change):
        relay = self

        class Pool:
            url = "wss://fake"

            def __init__(self):
                self.subs = {}
                self.up = False

            def subscribe(self, sub_id, *filters):
                self.subs[sub_id] = list(filters)
                if self.up:
                    relay.subscribe(self, sub_id, filters)

            def start(self):
                self.up = True
                relay.pools.append(self)
                on_change(self)
                for sub_id, filters in self.subs.items():
                    relay.subscribe(self, sub_id, filters)

            def send(self, message):
                relay.store(message[1])

            def close(self):
                self.up = False
                relay.pools.remove(self)

            def connected(self):
                return 1

            def publish(self, event):
                relay.store(event)
                return 1

            def deliver(self, what, payload):
                if self.up:
                    (on_event if what == "EVENT" else lambda e: on_eose(self.url, e))(payload)
        return Pool()

    def pump(self):
        while self.queue:
            pool, what, payload = self.queue.pop(0)
            pool.deliver(what, payload)


@pytest.fixture
def world(tmp_path, service):  # noqa: F811
    now = [1_800_000_000.0]
    clock = lambda: now[0]   # noqa: E731
    relay = Relay(clock)

    def app(name):
        def opened():
            gts_app = Service(folder=tmp_path / name / "GTS", bank_dir=tmp_path / name / "Bank", trainer=name,
                              app="test", log=lambda line: None, pool_factory=relay.pool, clock=clock)
            gts_app.start(thread=False)
            relay.pump()
            return gts_app
        return opened

    def receive(name, game, species, level):
        built = service.make(game, species, TRAINER, level=level)
        path = tmp_path / f"{name}-{game}-{species}.bin"
        path.write_bytes(base64.b64decode(built["data"]))
        return bank.deposit(game, str(path), service.check(game, str(path)), folder=tmp_path / name / "Bank")

    def banked(name):
        return {(e.game, e.species_id) for e in bank.entries(tmp_path / name / "Bank")}

    return {"now": now, "relay": relay, "app": app, "receive": receive, "banked": banked, "tmp": tmp_path}


def _browse(gts_app, relay):
    gts_app.browse()
    relay.pump()
    return gts_app.open_listings()


def test_a_listing_trades_while_each_app_is_closed_in_turn(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    pikachu = receive("alice", "sv", 25, 30)
    original = bank.data(pikachu)
    alice = world["app"]("alice")()
    alice.deposit(pikachu, gts.Wants(133, "Eevee", 10, 50))
    alice.close()
    assert banked("alice") == set()

    eevee = receive("bob", "swsh", 133, 20)         # a Sword record answers a Scarlet listing
    bob = world["app"]("bob")()
    (listing,) = _browse(bob, relay)
    assert (listing.pokemon["species"], listing.wants.text()) == ("Pikachu", "Eevee, level 10 to 50")
    bob.offer(listing, eevee)
    bob.close()
    assert banked("bob") == set()

    world["now"][0] += DAY
    world["app"]("alice")()                  # the stored offer is answered when Alice opens the app
    assert banked("alice") == {("swsh", 133)}

    world["now"][0] += DAY
    bob = world["app"]("bob")()
    assert banked("bob") == {("sv", 25)}
    (received,) = bank.entries(world["tmp"] / "bob" / "Bank")
    assert bank.data(received) == original
    (state,) = bob.mine()
    assert (state["status"], state["why"]) == ("traded", "")
    assert _browse(bob, relay) == []          # the listing now says traded


def test_an_offer_the_listing_does_not_ask_for_comes_back(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    alice = world["app"]("alice")()
    alice.deposit(receive("alice", "sv", 25, 30), gts.Wants(133, "Eevee", 10, 50))
    bob = world["app"]("bob")()
    (listing,) = _browse(bob, relay)
    low = receive("bob", "sv", 133, 5)
    with pytest.raises(GtsError, match="level 10 to 50"):
        bob.offer(listing, low)
    # A modified app sends it anyway: the lister's app refuses it and the record comes back.
    honest = bob.validate
    bob.validate = lambda game, record: ("", dict(honest(game, record)[1], level=20))
    bob.offer(listing, low)
    relay.pump()
    assert banked("alice") == set() and banked("bob") == {("sv", 133)}
    (state,) = bob.mine()
    assert (state["status"], state["why"]) == ("returned", "the lister asks for level 10 to 50")
    assert [x.d for x in _browse(bob, relay)] == [listing.d]        # still open


def test_the_first_offer_wins_and_the_second_comes_back(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    alice = world["app"]("alice")()
    alice.deposit(receive("alice", "sv", 25, 30), gts.Wants(133, "Eevee"))
    alice.close()
    bob, carol = world["app"]("bob")(), world["app"]("carol")()
    (listing,) = _browse(bob, relay)
    bob.offer(listing, receive("bob", "sv", 133, 20))
    world["now"][0] += 60
    carol.offer(listing, receive("carol", "bdsp", 133, 30))
    world["app"]("alice")()
    relay.pump()
    assert banked("alice") == {("sv", 133)}
    assert banked("bob") == {("sv", 25)}
    assert banked("carol") == {("bdsp", 133)}
    (state,) = carol.mine()
    assert state["why"] == "another offer was taken first"


def test_a_withdrawn_listing_returns_both_pokemon(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    alice = world["app"]("alice")()
    mine = alice.deposit(receive("alice", "sv", 25, 30), gts.Wants(133, "Eevee"))
    alice.close()
    bob = world["app"]("bob")()
    (listing,) = _browse(bob, relay)
    alice = world["app"]("alice")()
    alice.withdraw(mine["id"])
    relay.pump()
    with pytest.raises(GtsError, match="no longer open"):
        alice.withdraw(mine["id"])
    bob.offer(listing, receive("bob", "sv", 133, 20))      # the page still showed it
    relay.pump()
    assert banked("alice") == {("sv", 25)} and banked("bob") == {("sv", 133)}


def test_an_ended_listing_trades_nothing(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    alice = world["app"]("alice")()
    alice.deposit(receive("alice", "sv", 25, 30), gts.Wants(133, "Eevee"))
    alice.close()
    bob = world["app"]("bob")()
    (listing,) = _browse(bob, relay)
    bob.offer(listing, receive("bob", "sv", 133, 20))
    bob.close()
    world["now"][0] += gts.LIFETIME + 2 * gts.SKEW
    alice = world["app"]("alice")()          # opened after the end: no offer is taken
    alice.tick()
    relay.pump()
    assert banked("alice") == {("sv", 25)}
    bob = world["app"]("bob")()
    bob.tick()
    assert banked("bob") == {("sv", 133)}


def test_an_answer_lost_on_its_way_is_sent_again_when_the_app_opens(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    alice = world["app"]("alice")()
    alice.deposit(receive("alice", "sv", 25, 30), gts.Wants(133, "Eevee"))
    bob = world["app"]("bob")()
    (listing,) = _browse(bob, relay)
    relay.drop = lambda event: event["kind"] == gts.WRAP and event["pubkey"] == listing.key
    bob.offer(listing, receive("bob", "sv", 133, 20))
    relay.pump()
    alice.close()
    assert banked("alice") == {("sv", 133)} and banked("bob") == set()
    relay.drop = lambda event: False
    world["app"]("alice")()
    relay.pump()
    assert banked("bob") == {("sv", 25)}


def test_a_forged_or_foreign_listing_is_not_shown(world):
    relay = world["relay"]
    me = relays.Identity()
    forged = gts.listing_event(me, "x", "sv", {"species": "Mew", "species_id": 151, "level": 5}, b"\0" * 344,
                               gts.Wants(25, "Pikachu"), "MALLORY", "test", world["now"][0] + DAY)
    relay.events[forged["id"]] = dict(forged, content=forged["content"].replace("Mew", "Mewtwo"))
    other = me.event(gts.LISTING, [["d", "y"], ["t", "shop"]], json.dumps({"title": "a lamp"}))
    relay.store(other)
    bob = world["app"]("bob")()
    assert _browse(bob, relay) == []


def test_a_deletion_a_relay_missed_is_sent_again_when_the_app_opens(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    alice = world["app"]("alice")()
    alice.deposit(receive("alice", "sv", 25, 30), gts.Wants(133, "Eevee"))
    bob = world["app"]("bob")()
    (listing,) = _browse(bob, relay)
    relay.drop = lambda event: event["kind"] == gts.DELETION
    offer = bob.offer(listing, receive("bob", "sv", 133, 20))
    relay.pump()
    assert banked("bob") == {("sv", 25)} and offer["event"]["id"] in relay.events
    bob.close()
    relay.drop = lambda event: False
    world["app"]("bob")()
    assert offer["event"]["id"] not in relay.events

"""The GTS between three players' apps, each with its own bank, over a relay that stores events the way
the measured relays did (docs/online.md, Stored events), with records PKHeX built and checks."""
import base64
import json
from pathlib import Path

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


def test_a_listing_takes_any_of_its_wants_and_a_shiny_want_only_a_shiny(world):
    relay, receive, banked = world["relay"], world["receive"], world["banked"]
    alice = world["app"]("alice")()
    alice.deposit(receive("alice", "sv", 25, 30), gts.Wants(133, "Eevee", shiny=True), gts.Wants(37, "Vulpix", 10, 50))
    bob, carol = world["app"]("bob")(), world["app"]("carol")()
    bob.browse(wants=37)
    relay.pump()
    (listing,) = bob.open_listings(wants=37)
    assert bob.open_listings(shiny=True) == []                  # the offered Pikachu is not shiny
    plain = receive("bob", "sv", 133, 20)
    with pytest.raises(GtsError, match="shiny Eevee or Vulpix, level 10 to 50"):
        bob.offer(listing, plain)
    honest = bob.validate                                        # a modified app sends it anyway
    bob.validate = lambda game, record: ("", dict(honest(game, record)[1], shiny=True))
    bob.offer(listing, plain)
    relay.pump()
    (state,) = bob.mine()
    assert (state["status"], banked("bob")) == ("returned", {("sv", 133)})
    carol.offer(listing, receive("carol", "swsh", 37, 20))
    relay.pump()
    assert banked("alice") == {("swsh", 37)} and banked("carol") == {("sv", 25)}


def test_a_listing_an_earlier_app_published_still_shows(world):
    # Signed by pokeldn 0.40.0's listing_event: one want, no "shiny", no "also".
    event = json.loads((Path(__file__).parent / "data" / "gts_listing_0_40.json").read_text())
    world["relay"].store(event)
    (listing,) = _browse(world["app"]("bob")(), world["relay"])
    assert listing.wanted == (gts.Wants(133, "Eevee", 10, 50),)


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
    assert bob.offered(listing)["status"] == "waiting" and carol.offered(listing) is None
    with pytest.raises(GtsError, match="already waiting"):
        bob.offer(listing, receive("bob", "swsh", 133, 25))
    assert banked("bob") == {("swsh", 133)}                         # the second never left the bank
    world["now"][0] += 60
    carol.offer(listing, receive("carol", "bdsp", 133, 30))
    world["app"]("alice")()
    relay.pump()
    assert bob.offered(listing) is None
    assert banked("alice") == {("sv", 133)}
    assert banked("bob") == {("sv", 25), ("swsh", 133)}
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


@pytest.mark.parametrize('field,value', [
    ('species_id', 'not-a-number'), ('species_id', True), ('species_id', -1),
    ('level', 101), ('form', {}), ('moves', [123]), ('moves', ['A'] * 5),
    ('nickname', 'x' * 1000), ('legal', 'yes'),
])
def test_signed_malformed_listing_never_reaches_the_page(world, field, value):
    relay, receive = world['relay'], world['receive']
    alice = world['app']('alice')()
    state = alice.deposit(receive('alice', 'sv', 25, 30), gts.Wants(133, 'Eevee'))
    alice.close()
    event = state['event']
    body = json.loads(event['content'])
    body['pokemon'][field] = value
    identity = relays.Identity(bytes.fromhex(state['secret']))
    relay.store(identity.event(gts.LISTING, event['tags'], json.dumps(body),
                               created_at=event['created_at'] + 1))
    bob = world['app']('bob')()
    assert _browse(bob, relay) == []


@pytest.mark.parametrize('attack', ['illegal', 'hash', 'game', 'missing', 'listing', 'oversized'])
def test_hostile_signed_reply_preserves_the_offered_pokemon(world, service, attack):
    relay, receive, banked = world['relay'], world['receive'], world['banked']
    pikachu = receive('alice', 'sv', 25, 30)
    promised = bank.data(pikachu)
    incoming = promised
    if attack == 'illegal':
        reply = service.check_bytes('sv', promised, fields={'moves': [150]})
        assert reply['legal'] is False
        incoming = base64.b64decode(reply['data'])
    alice = world['app']('alice')()
    mine = alice.deposit(pikachu, gts.Wants(133, 'Eevee'))
    alice.close()
    identity = relays.Identity(bytes.fromhex(mine['secret']))
    if attack == 'illegal':
        body = json.loads(mine['event']['content'])
        body['sha256'] = gts.digest(incoming)
        mine['event'] = identity.event(gts.LISTING, mine['event']['tags'], json.dumps(body),
                                       created_at=mine['event']['created_at'] + 1)
        relay.store(mine['event'])
    bob = world['app']('bob')()
    (listing,) = _browse(bob, relay)
    eevee = receive('bob', 'sv', 133, 20)
    original = bank.data(eevee)
    state = bob.offer(listing, eevee)
    if attack == 'hash':
        incoming = original
    elif attack == 'missing':
        incoming = b''
    elif attack == 'oversized':
        incoming = b'MZ' + bytes(65536)
    body = gts.trade_body('wrong-listing' if attack == 'listing' else listing.d,
                          state['event']['id'], 'bdsp' if attack == 'game' else 'sv', incoming)
    relay.store(gts.wrap(identity, state['key'], body, int(world['now'][0] + DAY)))
    relay.pump()
    assert not list(bob.folder.glob('*/received.*'))
    if attack in ('listing', 'oversized'):
        assert state['status'] == 'waiting' and banked('bob') == set()
        assert bob._record(state) == original
    else:
        assert state['status'] == 'returned' and state['why']
        assert banked('bob') == {('sv', 133)}
        assert bank.data(bank.find(eevee.id, bob.bank_dir)) == original
    bob.close()
    reopened = world['app']('bob')()
    assert reopened.states[state['id']]['status'] == state['status']
    assert not list(reopened.folder.glob('*/received.*'))


def test_invalid_record_size_is_rejected_before_the_parser(monkeypatch):
    from pokeldn import pokemon
    instance = pokemon.Service()
    monkeypatch.setattr(instance, '_ask', lambda _: pytest.fail('untrusted size reached PKHeX'))
    for game in pokemon.EXTENSIONS:
        for payload in (b'', b'MZ' + bytes(1000), bytes(65536)):
            with pytest.raises(pokemon.BuilderError):
                instance.check_bytes(game, payload)
    assert gts.record_of({'record': base64.b64encode(bytes(65536)).decode()}) is None


def test_listing_cache_and_held_offers_have_local_limits(world, monkeypatch):
    from pokeldn.app import gts as app_gts
    relay, receive = world['relay'], world['receive']
    alice = world['app']('alice')()
    state = alice.deposit(receive('alice', 'sv', 25, 30), gts.Wants(133, 'Eevee'))
    monkeypatch.setattr(app_gts, 'LISTINGS_SHOWN', 3)
    monkeypatch.setattr(app_gts, 'OFFERS_HELD', 2)
    identity = relays.Identity(bytes.fromhex(state['secret']))
    alice.caught_up = 0
    for n in range(10):
        event = dict(state['event'])
        event['tags'] = [[*tag] if tag[0] != 'd' else ['d', str(n)] for tag in event['tags']]
        alice._on_event(identity.event(gts.LISTING, event['tags'], event['content'],
                                       created_at=event['created_at'] + n))
        sender = relays.Identity()
        wrap = gts.wrap(sender, state['key'],
                        {'t': 'offer', 'listing': state['id'], 'game': 'sv',
                         'record': base64.b64encode(bytes(344)).decode()},
                        int(world['now'][0] + DAY))
        alice._on_event(wrap)
        alice._on_event(wrap)
    assert len(alice.listings) == 3 and len(alice.held) == 2


def test_refusal_limits_keep_the_listing_available_for_a_valid_offer(world, monkeypatch):
    from pokeldn.app import gts as app_gts
    monkeypatch.setattr(app_gts, 'ANSWERS_KEPT', 1)
    monkeypatch.setattr(app_gts, 'CHECKS_PER_MINUTE', 2)
    alice = world['app']('alice')()
    state = alice.deposit(world['receive']('alice', 'sv', 25, 30), gts.Wants(133, 'Eevee'))
    world['relay'].pump()
    listing = gts.parse_listing(state['event'])
    for _ in range(2):
        identity = relays.Identity()
        body = gts.offer_body(listing, 'sv', bytes(344), 'MALLORY')
        alice._on_event(gts.wrap(identity, state['key'], body, int(world['now'][0] + DAY)))
    assert state['status'] == 'active' and len(state['answers']) == 1
    eevee = world['receive']('bob', 'sv', 133, 20)
    identity = relays.Identity()
    body = gts.offer_body(listing, 'sv', bank.data(eevee), 'BOB')
    event = gts.wrap(identity, state['key'], body, int(world['now'][0] + DAY))
    alice._on_event(event)
    assert state['status'] == 'active' and world['banked']('alice') == set()
    world['now'][0] += 61
    alice.tick()
    assert state['status'] == 'traded' and state['winner'] == event['id']
    assert len(state['answers']) == 1 and event['id'] in state['answers']
    assert world['banked']('alice') == {('sv', 133)}

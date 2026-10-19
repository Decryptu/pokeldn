"""A Dynamax Adventure guest against the bytes an emulated Shield guest sent in a won adventure
(docs/swsh_raid.md, Dynamax Adventures)."""
import collections
import json
from pathlib import Path

from pokeldn.swsh import lair, raid_battle

DATA = json.loads((Path(__file__).parent / "data" / "swsh_lair_emulated.json").read_text())
STATION = 0x7F00030000020000


def test_guest_answers_the_recorded_host_as_the_emulated_guest_did():
    recorded = [bytes.fromhex(h) for h in DATA["guest"]]
    rental = lair.parse(next(m for m in recorded if lair.parse(m)[:2] == (lair.CHIKA, lair.SELECT_POKEMON)))
    guest = lair.Guest(STATION, rental[2][12:12 + lair.PK8_PARTY], name="Guest", rental_choice=2,
                       log=lambda _: None)
    ours = guest.start()
    for h in DATA["host"]:
        ours += guest.receive(bytes.fromhex(h))
    # The emulated guest sent its first three twice; its player swapped for the caught Pokemon once.
    theirs = recorded[:3] + recorded[6:]
    swap = [i for i, m in enumerate(theirs) if lair.parse(m)[1] == lair.TRADE_WANT and m != ours[i]]
    assert swap and all(lair.parse_choice(lair.parse(theirs[i])[2])[2] == 1 for i in swap)
    assert [m for i, m in enumerate(ours) if i not in swap] == [m for i, m in enumerate(theirs) if i not in swap]
    assert guest.index == 1 and guest.legendary == 480


def test_rental_is_the_emulated_guests_choice():
    recorded = [bytes.fromhex(h) for h in DATA["guest"]]
    sent = next(m for m in recorded if lair.parse(m)[:2] == (lair.CHIKA, lair.SELECT_POKEMON))
    assert lair.select_pokemon(lair.RENTAL.read_bytes(), 2) == sent


def _shape(port, payload):
    fw = raid_battle.parse_framework(payload)
    return (port, "fw", fw["base"], fw["station"], fw["body"]) if fw else (port, payload)


def test_battle_guest_answers_the_first_lair_battle():
    # The emulated guest used Dark Pulse (399) every turn; it pinged first, so order is not compared.
    guest = raid_battle.Guest(STATION, slot=1, action=raid_battle.action(399, template=raid_battle.LAIR_ACTION))
    ours = []
    for m in DATA["battle"]:
        if m["dir"] == "rx":
            ours += [_shape(p, x) for p, x in guest.receive(m["port"], bytes.fromhex(m["payload"]))]
    theirs = [_shape(m["port"], bytes.fromhex(m["payload"])) for m in DATA["battle"] if m["dir"] == "tx"]
    assert collections.Counter(ours) == collections.Counter(theirs)


def test_fainted_guest_answers_as_the_emulated_guest_did():
    ask = raid_battle.battle_message(1, 0, 16, bytes.fromhex("11000400060012000100ffffffff"))
    guest = raid_battle.Guest(STATION, slot=1)
    (port, sent), = guest.receive(0, ask)
    assert port == 0 and raid_battle.parse_battle(sent)[3].hex() == (
        "110004005800120001ffffffffffffff0000000000000000" + "ff" * 72)


def test_host_messages_are_the_emulated_hosts():
    from pokeldn.swsh import lair_host

    recorded = {lair.parse(bytes.fromhex(h))[1]: bytes.fromhex(h) for h in DATA["host"]
                if lair.parse(bytes.fromhex(h))[0] == lair.CHIKA}
    host, guest = 0x7F00020000020000, STATION
    assert recorded[lair.PLAYER_INFO] == lair.player_info("Player")
    assert recorded[lair.BIG_BOSS] == lair.big_boss()
    assert recorded[lair.BATTLE_START] == lair_host.battle_start([guest, host])
    assert recorded[lair.PLAYER_NUMBER] == lair_host.player_number([host, guest])
    assert recorded[lair.BATTLE_SEED] == lair_host.scalar(lair.BATTLE_SEED, 173502832)
    assert recorded[lair.RENTAL_SEED] == lair_host.scalar(lair.RENTAL_SEED, 492089669869851380)
    assert recorded[lair.BIG_BOSS_FIXED] == lair_host.big_boss_fixed(480)


def test_the_seed_gives_the_recorded_offer_and_first_encounter():
    # The host took place 0 (Alcremie), the guest place 2 (Grimmsnarl); the first battle was Rotom.
    offer, encounters = lair.adventure(173502832, partners=2)
    assert [offer[0][0], offer[2][0]] == [869, 861] and encounters[0][0] == 479
    assert 226 in [row[0] for row in encounters]
    assert len(lair.legendaries()) == 47 and 480 in lair.legendaries()


def test_our_guest_takes_our_hosts_adventure_to_the_legendary():
    from pokeldn.swsh import lair_host

    host_id, sent = 0x7F00020000020000, []
    host = lair_host.LairHost(host_id, STATION, None, None, lambda *a: sent.append(a[2]), None, None,
                              legendary=144, seed=173502832, rental_seed=1, ready_after=0,
                              log=lambda _: None, record=lambda **_: None)
    host.stage = "lobby"
    guest = lair.Guest(STATION, log=lambda _: None)
    pending = guest.start()
    for t in range(40):
        for payload in pending:
            host.on_data(0x80, 0, payload)
        host.tick(float(t))
        pending = [out for payload in sent for out in guest.receive(payload)]
        sent.clear()
        if host.finished:
            break
    # Our host leaves before the rental turns, so the guest has nothing to answer there.
    assert host.finished and host.guest["pk8"] is None
    assert guest.index == 1 and guest.legendary == 144 and guest.host == host_id


def test_a_built_rental_is_made_as_the_game_made_the_recorded_ones():
    import random

    from pokeldn import gen8
    from pokeldn.sv import raid_encounter as encounter
    from pokeldn.swsh import raid_event

    recorded = [lair.parse(bytes.fromhex(h)) for h in DATA["host"] + DATA["guest"]]
    rentals = [gen8.decrypt(p[2][12:12 + lair.PK8_PARTY]) for p in recorded if p[:2] == (lair.CHIKA, lair.SELECT_POKEMON)]
    fixed = ("species", "form", "level", "experience", "moves", "move_pp", "ot_name", "ball", "met_location",
             "met_level", "version", "language", "evs", "held_item", "ot_friendship")
    rows = {row[0]: row for row in lair.table() if not row[2]}
    for plain in rentals:
        want = gen8.read(plain)
        base, *_ = raid_event.personal(want["species"], want["form"])
        # The recorded party stats follow from their own IVs and nature at level 65.
        assert tuple(want["stats"].values()) == encounter.stats(base, want["ivs"], 65, want["nature"])
        assert sum(iv == 31 for iv in want["ivs"]) >= lair.RENTAL_FLAWLESS_IVS
        built = gen8.read(gen8.decrypt(lair.rental_pk8(rows[want["species"]], random.Random(1))))
        assert {k: built[k] for k in fixed} == {k: want[k] for k in fixed}
        assert tuple(built["stats"].values()) == encounter.stats(base, built["ivs"], 65, built["nature"])


def test_guest_takes_the_first_offer_place_the_host_left():
    import random

    host_id = 0x7F00020000020000
    guest = lair.Guest(STATION, log=lambda _: None, rand=random.Random(2))
    for payload in (lair_host_messages(host_id) + [lair.select_pokemon(lair.RENTAL.read_bytes(), 0)]):
        sent = guest.receive(payload)
    which_id, which, value = lair.parse(sent[0])
    assert (which_id, which, value[8]) == (lair.CHIKA, lair.SELECT_POKEMON, 1)
    from pokeldn import gen8
    assert gen8.read(gen8.decrypt(value[12:12 + lair.PK8_PARTY]))["species"] == lair.adventure(173502832)[0][1][0]


def lair_host_messages(host_id):
    from pokeldn.swsh import lair_host

    return [lair_host.scalar(lair.BATTLE_SEED, 173502832),
            lair_host.player_number([host_id, STATION])]

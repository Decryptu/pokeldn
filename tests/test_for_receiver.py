"""A Mystery Gift Pokemon made for the receiving player (pokeldn.for_receiver, docs/gift_simulated.md)."""

from types import SimpleNamespace

import pytest

from pokeldn import for_receiver, gen9
from pokeldn.sv import trade

SAVE = {"ot": "Nemona", "tid": 0x1234, "sid": 0x0042, "language": 5, "gender": 1}


def record(**fields):
    """A 348-byte trade body: by default a Pokemon the Scarlet save above caught."""
    merged = dict(species=906, ot_name=SAVE["ot"], trainer_id=SAVE["tid"], secret_id=SAVE["sid"],
                  language=SAVE["language"], ot_gender=SAVE["gender"], version=gen9.VERSION_SCARLET,
                  current_handler=0)
    merged.update(fields)
    return gen9.to_wire(gen9.build(**merged))


CAUGHT = record()
TRADED = record(ot_name="Arven", trainer_id=7, current_handler=1)
PREVIEW = record(species=25, ot_name="POKELDN")
MADE = record(species=25, nickname="MADE")


def owner(version, **fields):
    """The owner fields `Service.owner` reads off a console's offer: by default a Pokemon the save above
    caught on `version`."""
    return {"species": 25, "shiny": False, "egg": False, "ot": SAVE["ot"], "tid": SAVE["tid"], "sid": SAVE["sid"],
            "gender": SAVE["gender"], "language": SAVE["language"], "handler": 0, "version": version, **fields}


@pytest.fixture
def builds(monkeypatch):
    """The builds a ReceiverGift started, run when the test says, as its worker thread would."""
    pending = []

    class Thread:
        def __init__(self, target, args, daemon):
            self.call = lambda: target(*args)

        def start(self):
            pending.append(self.call)

    monkeypatch.setattr(for_receiver.threading, "Thread", Thread)

    def run():
        while pending:
            pending.pop(0)()
    return run


def gift_for(game, rounds, made, read=None, make=None, said=None, copy=MADE):
    """A ReceiverGift whose maker logs its requests in `made` and answers `copy`; its pop-ups, (title, text),
    are `gift.popups`."""
    popups = []

    def maker(key, trainer, version, body=b""):
        made.append((key, trainer, version))
        return copy, "the made copy"
    gift = for_receiver.ReceiverGift(game, rounds, make or maker, read=read,
                                      log=(said.append if said is not None else lambda line: None),
                                      notify=lambda title="", text="": popups.append((title, text)))
    gift.popups = popups
    return gift


@pytest.mark.parametrize("game, version, name", [("lgpe", 42, "GP"), ("lgpe", 43, "GE"), ("bdsp", 48, "BD"),
                                                 ("bdsp", 49, "SP"), ("pla", 47, "PLA"), ("sv", 50, "SL"),
                                                 ("sv", 51, "VL"), ("za", 52, "ZA")])
def test_a_pokemon_the_save_caught_names_its_trainer_and_version(game, version, name):
    assert for_receiver.own_trainer(game, owner(version)) == (SAVE, name)
    assert for_receiver.NAMES[name]


@pytest.mark.parametrize("game, version", [("lgpe", 50), ("bdsp", 47), ("pla", 52), ("sv", 44), ("za", 50)])
def test_a_pokemon_from_another_game_names_no_one(game, version):
    assert for_receiver.unknown(game, owner(version)) == "it came from another game"
    assert for_receiver.own_trainer(game, owner(version)) is None


def test_a_scarlet_violet_offer_is_read_here():
    assert for_receiver.own_trainer("sv", for_receiver.sv_owner(CAUGHT)) == (SAVE, "SL")
    assert for_receiver.own_trainer("sv", for_receiver.sv_owner(record(version=gen9.VERSION_VIOLET)))[1] == "VL"
    assert for_receiver.shown_id(SAVE) == f"{(0x42 << 16 | 0x1234) % 1_000_000:06d}"
    with pytest.raises(ValueError):
        for_receiver.sv_owner(b"\x00" * 348)


@pytest.mark.parametrize("body, why", [
    (TRADED, "it came from another trainer, Arven"), (record(version=44), "it came from another game"),
    (record(is_egg=1), "it is an egg"), (record(ot_name=""), "it names no trainer"), (CAUGHT, "")])
def test_a_pokemon_that_names_no_one_says_why(body, why):
    f = for_receiver.sv_owner(body)
    assert for_receiver.unknown("sv", f) == why
    assert (for_receiver.own_trainer("sv", f) is None) == bool(why)


def test_only_a_host_made_for_the_receiver_with_a_card_that_names_them_stands_in(monkeypatch):
    asked = []
    real = for_receiver.rounds
    monkeypatch.setattr(for_receiver, "rounds", lambda game, keys, offers, log, marked: [
        (key if key.startswith("15") else "", body) for key, body in zip(keys, offers)] if keys else
        real(game, keys, offers, log, marked))
    monkeypatch.setattr(for_receiver, "maker", lambda game, load, **check: asked.append((game, load, check)) or "make")

    def setup(keys, on=True, owns=(), back=False, count=0):
        args = SimpleNamespace(for_receiver=on, gift_event=keys, receiver_owns=list(owns), trade_back=back)
        return for_receiver.setup("lgpe", args, [PREVIEW] * (count or len(keys)), bytes, log=lambda line: None,
                              fresh=True)
    assert setup(["1501-808-0"]) == ([("1501-808-0", PREVIEW)], "make") and asked == [("lgpe", bytes, {"fresh": True})]
    assert setup(["0002-150-0"]) is None
    assert setup(["1501-808-0"], on=False) is None
    # A trade's offers marked as the receiver's own (--receiver-owns), counted from 1; Send it back keeps ours.
    assert setup([], on=False, owns=[2], count=3) == ([("", PREVIEW), (for_receiver.OWN, PREVIEW), ("", PREVIEW)], "make")
    assert setup([], on=False, owns=[2], count=3, back=True) is None


def test_a_copy_made_during_the_trade_takes_the_checks_the_host_offers_took(monkeypatch):
    """The host's `check` (its --fresh-pid and edits) goes to the offer check every offer takes, PKHeX's among
    them, and the host's own loader runs on what it gives."""
    import base64
    from pokeldn import pokemon
    asked = []
    monkeypatch.setattr(pokemon.SERVICE, "gift_event", lambda game, key, trainer, version="", keep=True: asked.append(
        (game, key, trainer, version, keep)) or {"data": base64.b64encode(b"made").decode(), "species": "Pikachu",
                                                "level": 5, "refused": ""})
    monkeypatch.setattr(pokemon, "prepare_offer", lambda game, data, **check: asked.append((game, data, check))
                        or b"checked")

    def edit(raw):
        return raw
    make = for_receiver.maker("sv", lambda raw: asked.append(raw) or b"sent", fresh=True, transform=edit)
    assert make("1501-25-0-2", SAVE, "SL") == (b"sent", "Pikachu · level 5")
    assert asked == [("sv", "1501-25-0-2", SAVE, "SL", False), ("sv", b"made", {"fresh": True, "transform": edit}),
                     b"checked"]


def test_a_host_never_rebinds_a_helper_its_closures_call():
    """A host's main defines helpers that closures call later, the gift's loader among them; a name assigned
    anywhere in main is main's one variable, so a later assignment replaces the helper for every closure (Legends
    Arceus once called the trade box's payload, a dict, as the loader)."""
    import ast
    from pathlib import Path
    scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

    def own(fn):
        stack = list(fn.body)
        while stack:
            node = stack.pop()
            yield node
            if not isinstance(node, scopes):
                stack.extend(ast.iter_child_nodes(node))
    for path in sorted(Path(__file__).resolve().parent.parent.joinpath("bin").glob("*_host.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nodes = list(own(fn))
                helpers = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                rebound = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                assert not helpers & rebound, f"{path.name} {fn.name}: {sorted(helpers & rebound)}"


def test_a_host_loader_refuses_what_it_would_not_send():
    """Let's Go's and Legends Z-A's loaders raise for a record the host would not send, so the gift goes under
    the trainer from Settings instead."""
    import lgpe_host
    import za_host
    for load, raw in ((lgpe_host.boxed, bytes(10)), (za_host.gift_offer, bytes(10)),
                      (za_host.gift_offer, bytes.fromhex("0101b90300bc815801") + bytes(345))):
        with pytest.raises(ValueError):
            load(raw)


# Scarlet/Violet (pokeldn.sv.trade).

def sv_host(rounds, make=None):
    """-> (stage, gift, made: the maker's requests, said: the log, send: console message -> host's)."""
    made, said = [], []
    gift = gift_for("sv", rounds, made, make=make, said=said)
    stage = trade.TradeStage([body for _, body in rounds], partner=gift)

    def send(kind, body=b"", step=0, key=trade.KEY_TRADE, port=0):
        return [payload for _, _, payload in stage.on_message(port, trade.build(key, kind, step, body))]
    return stage, gift, made, said, send


def our_offers(messages):
    return [trade.parse(m)[3] for m in messages if trade.parse(m)[:2] == (trade.KEY_TRADE, trade.KIND_OFFER)]


def confirms(messages):
    return [m for m in messages if trade.parse(m)[:2] == (trade.KEY_TRADE, trade.KIND_CONFIRM)]


def complete(stage, send):
    send(trade.KIND_COMMIT)
    stage.on_message(1, trade.table_update(trade.KEY_EXCHANGE, True))
    for step in trade.STEPS:
        send(trade.KIND_STEP_OPEN, step=step, key=trade.KEY_EXCHANGE)


def ticked(stage):
    return [payload for _, _, payload in stage.tick()]


def given(species):
    """An offer as the app made it, under the trainer from Settings."""
    return record(species=species, ot_name="POKELDN")


def traded(stage, send):
    send(trade.KIND_CONFIRM)
    ticked(stage)
    complete(stage, send)


def test_a_pokemon_that_names_no_one_gets_the_gift_under_the_trainer_from_settings(builds):
    """Each round asks again: a Pokemon the save caught has the next gift made for it. The pop-up comes once
    for each reason."""
    rounds = [("1501-25-0-2", given(808)), ("1502-25-0-2", given(809)), ("2001-25-0-2", given(151))]
    stage, gift, made, said, send = sv_host(rounds)
    send(trade.KIND_OFFER, TRADED)
    builds()
    assert our_offers(ticked(stage)) == [given(808)] and made == []
    why = "it came from another trainer, Arven"
    assert said == [for_receiver.unnamed(for_receiver.sv_owner(TRADED), why)]
    assert said[0] == (f"[gift] the console's Pokemon [species 906] cannot name the save: {why}, so the gift goes "
                       "with your trainer from Settings")
    assert gift.popups == [(for_receiver.FALLBACK_TITLE, for_receiver.unnamed_text(why))]
    traded(stage, send)
    builds()
    assert made == []                                # the save is still unknown
    send(trade.KIND_OFFER, TRADED)
    builds()
    assert our_offers(ticked(stage)) == [given(809)] and len(gift.popups) == 1
    traded(stage, send)
    send(trade.KIND_OFFER, CAUGHT)
    builds()
    assert made == [("2001-25-0-2", SAVE, "SL")] and our_offers(ticked(stage)) == [MADE]
    traded(stage, send)
    assert stage.trades == 3 and not stage.done


def test_the_gift_is_made_for_the_save_when_it_offers_a_pokemon_it_caught(builds):
    stage, gift, made, said, send = sv_host([("1501-25-0-2", PREVIEW)])
    assert send(trade.KIND_OFFER, CAUGHT) == []
    assert ticked(stage) == [] and said == []        # nothing goes up while it is read and the copy made
    builds()
    assert said[0] == f"[gift] making the gift for Nemona, ID {for_receiver.shown_id(SAVE)}, Scarlet"
    assert made == [("1501-25-0-2", SAVE, "SL")] and said[-1] == "[gift] made for Nemona: the made copy"
    assert our_offers(ticked(stage)) == [MADE] and ticked(stage) == []
    assert confirms(ticked(stage)) == []             # ours waits for the console's confirm
    send(trade.KIND_CONFIRM)
    assert confirms(ticked(stage)) and stage.confirmed
    complete(stage, send)
    assert stage.trades == 1 and not stage.done
    assert stage.joiner_offers == [CAUGHT] and gift.popups == []


def test_six_mixed_gifts_trade_in_order_and_a_withdrawn_offer_keeps_its_round(builds):
    copies = {"mew": record(species=151), "pikachu": record(species=25), "charizard": record(species=6)}
    fixed = given(964)
    rounds = [("", fixed), ("mew", PREVIEW), ("pikachu", PREVIEW), ("mew", PREVIEW),
              ("", fixed), ("charizard", PREVIEW)]
    made = []

    def make(key, trainer, version, body=b""):
        made.append((key, trainer, version))
        return copies[key], key
    stage, gift, _, _, send = sv_host(rounds, make=make)
    sent = []
    for n in range(6):
        if n == 1:
            send(trade.KIND_OFFER, CAUGHT)
            send(trade.KIND_CANCEL, b"\x00", step=1)
            builds()
            assert ticked(stage) == [] and stage.trades == 1
        send(trade.KIND_OFFER, CAUGHT)
        builds()
        sent.extend(our_offers(ticked(stage)))
        traded(stage, send)
        builds()
    assert sent == [fixed, copies["mew"], copies["pikachu"], copies["mew"], fixed, copies["charizard"]]
    assert stage.trades == 6 and stage.joiner_offers == [CAUGHT] * 7
    assert made[:4] == [(key, SAVE, "SL") for key in ("mew", "pikachu", "mew", "charizard")]
    assert gift.popups == []


def test_a_copy_made_after_the_console_backed_out_waits_for_its_next_offer(builds):
    stage, gift, made, said, send = sv_host([("1501-25-0-2", PREVIEW)])
    send(trade.KIND_OFFER, CAUGHT)
    send(trade.KIND_CANCEL, b"\x00", step=1)
    builds()
    assert ticked(stage) == []
    send(trade.KIND_OFFER, TRADED)                   # the save is known now: any Pokemon will do
    assert our_offers(ticked(stage)) == [MADE] and len(made) == 1


def test_a_gift_the_save_cannot_receive_goes_under_the_trainer_from_settings(builds):
    """The pop-up names the save and says why its copy was not made (`maker`)."""
    why = "the save cannot have received the card: card 1540 gave it to Violet alone, never to Scarlet"

    def refuse(key, trainer, version, body=b""):
        raise ValueError(why)
    stage, gift, made, said, send = sv_host([("1540-1007-0-1", PREVIEW)], make=refuse)
    send(trade.KIND_OFFER, CAUGHT)
    assert ticked(stage) == []                       # while it is tried
    builds()
    assert our_offers(ticked(stage)) == [PREVIEW]
    assert said[-1] == f"[gift] could not be made for Nemona, so it goes with your trainer from Settings: {why}"
    assert gift.popups == [(for_receiver.FALLBACK_TITLE, f"The gift could not be made for Nemona, ID "
                                                          f"{for_receiver.shown_id(SAVE)}, on Scarlet: {why}. It goes "
                                                          "with the trainer from Settings instead.")]


def test_a_trade_offer_marked_as_the_receivers_goes_up_made_for_the_save_that_caught_its_offer(builds):
    """--receiver-owns on a host: the round waits for the console's offer like a gift's, then goes up retrained
    for the save it names (`maker`'s OWN branch gets the round's own record)."""
    bodies = []

    def make(key, trainer, version, body=b""):
        bodies.append((key, trainer, version, body))
        return MADE, f"{trainer['ot']}'s own"
    stage, gift, made, said, send = sv_host([(for_receiver.OWN, PREVIEW)], make=make)
    send(trade.KIND_OFFER, CAUGHT)
    assert ticked(stage) == []                       # while it is made
    builds()
    assert our_offers(ticked(stage)) == [MADE] and bodies == [(for_receiver.OWN, SAVE, "SL", PREVIEW)]
    assert said[-2:] == [f"[receiver] making the offers for Nemona, ID {for_receiver.shown_id(SAVE)}, Scarlet",
                         "[receiver] made for Nemona: Nemona's own"]


def test_a_trade_offer_that_cannot_take_the_receiver_goes_as_given(builds):
    why = "it is legal only with its own trainer"

    def refuse(key, trainer, version, body=b""):
        raise ValueError(why)
    stage, gift, made, said, send = sv_host([(for_receiver.OWN, PREVIEW)], make=refuse)
    send(trade.KIND_OFFER, CAUGHT)
    builds()
    assert our_offers(ticked(stage)) == [PREVIEW]
    text = for_receiver.own_text("Offer 1", f"for Nemona, {why}")
    assert said[-1] == f"[receiver] {text}" and gift.popups == [(for_receiver.OWN_TITLE, text)]


@pytest.mark.parametrize("stage, why", [
    ("refused", "the save cannot have received the card: card 1502 gave it in Simplified Chinese alone, never to a "
                "save in English"),
    ("check", "the copy fails the host's offer check: Invalid: Encounter Type PID mismatch."),
    ("load", "the host cannot send the copy: an offer is 354 bytes, not 10")])
def test_a_copy_not_made_for_the_save_says_where_it_stopped(monkeypatch, stage, why):
    import base64
    from pokeldn import pokemon
    reason = why.split(": ", 1)[1]
    monkeypatch.setattr(pokemon.SERVICE, "gift_event", lambda game, key, trainer, version="", keep=True: {
        "data": base64.b64encode(b"made").decode(), "species": "Melmetal", "level": 1,
        "refused": reason if stage == "refused" else ""})

    def check(game, data, **_):
        if stage == "check":
            raise pokemon.BuilderError(reason)
        return data

    def load(raw):
        if stage == "load":
            raise ValueError(reason)
        return raw
    monkeypatch.setattr(pokemon, "prepare_offer", check)
    with pytest.raises(ValueError) as caught:
        for_receiver.maker("lgpe", load)("1502-809-0", SAVE, "GE")
    assert str(caught.value) == why


def test_the_host_loop_never_waits_on_the_service(builds):
    """Brilliant Diamond's, Let's Go's, Legends Arceus's and Legends Z-A's hosts call `offer` on their frame-timed
    loop; the service reads the console's Pokemon and this round's record on a worker, never there."""
    read, made = [], []
    gift = gift_for("bdsp", [("9015-387-0", b"given")], made, read=lambda body: read.append(body) or owner(48))
    gift.offer(b"caught")
    assert read == [] and gift.theirs().offer is None
    builds()
    assert read == [b"caught", b"given"] and gift.theirs().offer == MADE and made == [("9015-387-0", SAVE, "BD")]


def test_a_card_with_its_own_trainer_goes_up_as_made_once_the_console_offers(builds):
    stage, gift, made, said, send = sv_host([("", PREVIEW)])
    assert ticked(stage) == []
    send(trade.KIND_OFFER, TRADED)
    assert our_offers(ticked(stage)) == [PREVIEW] and made == [] and said == []


def test_the_next_round_is_made_for_the_known_save_as_the_trade_closes(builds):
    stage, gift, made, said, send = sv_host([("1501-25-0-2", PREVIEW), ("0050-133-0-0", PREVIEW)])
    send(trade.KIND_OFFER, CAUGHT)
    builds()
    ticked(stage)
    send(trade.KIND_CONFIRM)
    ticked(stage)
    complete(stage, send)
    assert stage.trades == 1 and not stage.done
    builds()
    assert [key for key, _, _ in made] == ["1501-25-0-2", "0050-133-0-0"]
    send(trade.KIND_OFFER, TRADED)
    assert our_offers(ticked(stage)) == [MADE]
    send(trade.KIND_CONFIRM)
    ticked(stage)
    complete(stage, send)
    builds()                                         # the last gift serves every later trade, made afresh
    assert [key for key, _, _ in made] == ["1501-25-0-2", "0050-133-0-0", "0050-133-0-0"]
    send(trade.KIND_OFFER, TRADED)
    assert our_offers(ticked(stage)) == [MADE] and not stage.done


# The other games' hosts read the console's offer through the service (Service.owner); `read` stands in.

def reader(caught, version):
    """The owner fields of `caught`, a Pokemon the save caught on `version`; any other is a traded one."""
    return lambda body: owner(version) if body == caught else owner(version, ot="Arven", handler=1)


@pytest.mark.parametrize("caught", [True, False])
def test_a_brilliant_diamond_host_answers_the_console_offer_with_the_gift(builds, caught):
    """BDSP's room: the console's 0x13 gets the copy made for its save when that save caught the Pokemon, and
    the offer as given, under the trainer from Settings, when it did not."""
    from pokeldn.bdsp import host as bdsp, room
    mine, theirs, given_, copy = (bytes([b]) * 328 for b in (0xA1, 0xB2, 0xD4, 0xC3))
    made = []
    gift = gift_for("bdsp", [("9015-387-0", given_)], made, read=reader(mine, 49), copy=copy)
    partner = bdsp.TradePartner(bytes(0), complete=True, remote=gift)
    joiner = SimpleNamespace(join_acked=True, tx_pending={})
    message = room.build_trade_poke(mine if caught else theirs)
    assert partner.game(joiner, room.parse(message), message, 10.0) == []
    builds()
    assert made == ([("9015-387-0", SAVE, "SP")] if caught else [])
    assert partner.tick(joiner, 10.1) == [room.build_trade_poke(copy if caught else given_)]
    assert partner.tick(joiner, 20.0) == []


@pytest.mark.parametrize("caught", [True, False])
def test_an_arceus_box_answers_the_console_offer_with_the_gift(builds, caught):
    from pokeldn.pla import trade_box
    mine, theirs, given_, copy = (bytes([b]) * 376 for b in (0xA1, 0xB2, 0xD4, 0xC3))
    made = []
    box = trade_box.OnlineBox(gift_for("pla", [("9018-722-0", given_)], made, read=reader(mine, 47), copy=copy))
    offered = {"selector": trade_box.SELECTOR_OFFERING, "counter": 1, "record": mine if caught else theirs}
    assert box.on_box(offered) == []
    builds()
    assert made == ([("9018-722-0", SAVE, "PLA")] if caught else [])
    assert box.tick() == ([(trade_box.SELECTOR_OFFERING, 1, copy if caught else given_)], [])
    # Our confirmation waits for the console's alone.
    assert box.on_selector(trade_box.SELECTOR_CONFIRMING, b"\x05\x01") == [b"\x05\x01"]


@pytest.mark.parametrize("caught", [True, False])
def test_a_za_host_previews_and_picks_the_gift_for_the_console(builds, caught):
    """The host's own copy, made under the trainer from Settings, waits on the gift: the console sees the one made
    for its save."""
    from tests.test_online import za_player, za_seat
    head = bytes.fromhex("0101b90300bc815801")
    pick, given_, copy = (head + bytes([b]) * 344 + b"\x00" for b in (0xA1, 0xD4, 0xC3))
    made = []
    gift = gift_for("za", [("9031-152-0", given_)], made, read=reader(pick if caught else None, 52), copy=copy)
    host, console = za_seat(gift, offers=[given_])
    play = za_player(console, pick)
    t = 10.0
    while host.trades == 0 and t < 30.0:
        play(t)
        builds()
        console.run(t + 0.05, t)
        t += 0.1
    # A copy for the next trade is made as this one closes.
    assert host.trades == 1 and made[:1] == ([("9031-152-0", SAVE, "ZA")] if caught else [])
    shown = [x[2] for x in console.game_heard() if x[2][:2] == b"\x01\x01"]
    assert [m[-1] for m in shown] == [1, 0] and shown[1] == (copy if caught else given_)


# The console's own session data names its save when its Pokemon cannot (for_receiver.hear).

HEARD = {"ot": "Florian", "tid": 0x0BAD, "sid": 0x0F00, "version": 51, "gender": 0, "language": 2}
FLORIAN = {"ot": "Florian", "tid": 0x0BAD, "sid": 0x0F00, "gender": 0, "language": 2}


def test_the_session_names_the_save_with_what_it_carries():
    settings = owner(50)
    assert for_receiver.from_session("sv", HEARD, for_receiver.sv_owner(TRADED), settings) == ((FLORIAN, "VL"), [])
    assert for_receiver.from_session("sv", None, None, settings) is None
    assert for_receiver.from_session("sv", {**HEARD, "ot": ""}, None, settings) is None


def test_what_the_session_lacks_comes_from_the_handler_when_it_is_this_save_and_from_settings_otherwise():
    settings = owner(49)                                   # Nemona's gender 1 and language 5
    bdsp = {"ot": "Florian", "tid": 0x0BAD, "sid": 0x0F00, "version": 48, "language": 2}
    handled = owner(48, ot="Arven", handler=1, ht_name="Florian", ht_gender=0, ht_language=3)
    assert for_receiver.from_session("bdsp", bdsp, handled, settings) == (
        (FLORIAN, "BD"), ["gender from the Pokemon's handler"])
    for other in (owner(48, ot="Arven", handler=1, ht_name="Penny", ht_gender=0), owner(48, handler=0), None):
        assert for_receiver.from_session("bdsp", bdsp, other, settings) == (
            ({**FLORIAN, "gender": 1}, "BD"), ["gender from Settings"])
    # A value the game cannot hold is no value.
    assert for_receiver.from_session("lgpe", {**HEARD, "version": 7, "language": 6}, None, owner(43)) == (
        ({**FLORIAN, "language": 5}, "GE"), ["language from Settings", "version from Settings"])
    # Latin American Spanish (11) is a Z-A save's language only.
    latam = {**FLORIAN, "language": 11}
    assert for_receiver.from_session("za", latam, None, settings) == ((latam, "ZA"), [])
    assert for_receiver.from_session("sv", {**HEARD, "language": 11}, None, settings) == (
        ({**FLORIAN, "language": 5}, "VL"), ["language from Settings"])
    assert for_receiver.from_session("bdsp", bdsp, None, {}) is None


BRED = owner(48, egg=True, ot="Florian", tid=0x0BAD, sid=0x0F00, gender=0, language=2)


def test_what_the_session_lacks_comes_from_an_egg_the_save_bred():
    """An egg is still with the trainer who bred it (handler 0): when that trainer's name and id pair are the
    session's, its OT gender is the save's. A received egg has a handler (docs/bdsp_trade.md)."""
    settings = owner(49)                                   # Nemona's gender 1 and language 5
    bdsp = {"ot": "Florian", "tid": 0x0BAD, "sid": 0x0F00, "version": 48, "language": 2}
    assert for_receiver.unknown("bdsp", BRED) == "it is an egg"
    assert for_receiver.from_session("bdsp", bdsp, BRED, settings) == (
        (FLORIAN, "BD"), ["gender from the Pokemon's original trainer"])
    for other in ({**BRED, "ot": "Arven"}, {**BRED, "sid": 0x0F01}, {**BRED, "handler": 1}):
        assert for_receiver.from_session("bdsp", bdsp, other, settings) == (
            ({**FLORIAN, "gender": 1}, "BD"), ["gender from Settings"])


def test_a_brilliant_diamond_egg_the_save_bred_has_the_gift_made_for_the_save_the_session_names(builds):
    said, made = [], []
    gift = gift_for("bdsp", [("9015-387-0", b"given")], made, said=said,
                    read=lambda body: BRED if body == b"egg" else owner(49))
    gift.hear({"ot": "Florian", "tid": 0x0BAD, "sid": 0x0F00, "version": 48, "language": 2})
    gift.offer(b"egg")
    builds()
    assert made == [("9015-387-0", FLORIAN, "BD")] and gift.theirs().offer == MADE and gift.popups == []
    assert said[1] == ("[gift] the console's Pokemon [species 25] cannot name the save: it is an egg; the session "
                       "does (gender from the Pokemon's original trainer)")


def test_a_pokemon_that_names_no_one_has_the_gift_made_for_the_save_the_session_names(builds):
    stage, gift, made, said, send = sv_host([("1501-25-0-2", given(808)), ("1502-25-0-2", given(809))])
    gift.hear(HEARD)
    gift.hear(dict(HEARD))                               # the same again says nothing
    send(trade.KIND_OFFER, TRADED)
    builds()
    assert made == [("1501-25-0-2", FLORIAN, "VL")] and our_offers(ticked(stage)) == [MADE]
    shown = for_receiver.shown_id(FLORIAN)
    assert said == [f"[gift] the session names the console's trainer Florian, ID {shown}",
                    "[gift] the console's Pokemon [species 906] cannot name the save: it came from another trainer, "
                    "Arven; the session does",
                    f"[gift] making the gift for Florian, ID {shown}, Violet",
                    "[gift] made for Florian: the made copy"]
    assert gift.popups == []
    traded(stage, send)
    builds()
    assert made[-1] == ("1502-25-0-2", FLORIAN, "VL")      # the next round is made as the trade closes


def test_the_session_heard_after_a_round_names_the_save_for_the_next(builds):
    stage, gift, made, said, send = sv_host([("1501-25-0-2", given(808)), ("1502-25-0-2", given(809))])
    send(trade.KIND_OFFER, TRADED)
    builds()
    assert our_offers(ticked(stage)) == [given(808)] and len(gift.popups) == 1
    gift.hear(HEARD)
    traded(stage, send)
    send(trade.KIND_OFFER, TRADED)
    builds()
    assert made == [("1502-25-0-2", FLORIAN, "VL")] and our_offers(ticked(stage)) == [MADE]


@pytest.mark.parametrize("made_yet", [True, False])
def test_a_pokemon_the_save_caught_outranks_the_session(builds, made_yet):
    """The next round's copy made for the session's save, done or still under way, is made again for the save
    a Pokemon it caught names."""
    stage, gift, made, said, send = sv_host([("1501-25-0-2", given(808)), ("1502-25-0-2", given(809))])
    gift.hear(HEARD)
    send(trade.KIND_OFFER, TRADED)
    builds()
    ticked(stage)
    traded(stage, send)
    if made_yet:
        builds()
    send(trade.KIND_OFFER, CAUGHT)
    builds()
    assert made == [("1501-25-0-2", FLORIAN, "VL"), ("1502-25-0-2", FLORIAN, "VL"), ("1502-25-0-2", SAVE, "SL")]
    assert our_offers(ticked(stage)) == [MADE] and gift.named_by == "pokemon"
    assert said[-2:] == [f"[gift] making the gift for Nemona, ID {for_receiver.shown_id(SAVE)}, Scarlet",
                         "[gift] made for Nemona: the made copy"]


def test_a_session_that_does_not_read_is_passed_over():
    said, heard = [], []
    partner = SimpleNamespace(hear=heard.append)
    for_receiver.hear(partner, lambda body: {"ot": "Florian", "tid": 1, "sid": 2}, b"x", log=said.append)
    for_receiver.hear(partner, lambda body: [][1], b"x", log=said.append)
    for_receiver.hear(object(), lambda body: 1 / 0, b"x", log=said.append)     # an online partner hears none
    assert heard == [{"ot": "Florian", "tid": 1, "sid": 2}]
    assert said == ["[gift] the session's trainer does not read: list index out of range"]


# Each game's session data: what it names, and the host that passes it on.

def lets_go_first():
    """A first message's body for the save above, on Let's Go Eevee."""
    from pokeldn.lgpe import pb7
    body = bytearray(0x168)
    body[pb7.TRAINER_VERSION], body[pb7.TRAINER_GENDER], body[pb7.TRAINER_LANGUAGE] = 43, 1, 5
    return pb7.set_trainer_name(pb7.set_trainer_id(bytes(body), 0x1234, 0x0042), "Nemona")


def test_a_lets_go_first_message_names_the_save():
    from pokeldn.lgpe import pb7
    assert pb7.first_trainer(lets_go_first()) == {**SAVE, "version": 43}
    with pytest.raises(ValueError):
        pb7.first_trainer(lets_go_first()[:0x40])


def test_a_lets_go_host_passes_on_the_console_first_message():
    from pokeldn.lgpe import pb7
    from tests import test_lgpe_host_commit as ref
    lgpe_host = ref.lgpe_host
    gift = gift_for("lgpe", [("1501-25-0-2", PREVIEW)], [])
    args = lgpe_host.build_parser().parse_args([])
    s = lgpe_host.Session(ref.Radio(), lgpe_host.Advertisement(0x2952124b, 0xe28ef1be), args, lambda **kw: None,
                          partner=gift)
    body = lets_go_first()
    s.game({"kind": pb7.FIRST_MESSAGE, "step": 1, "size": len(body), "body": body})
    assert gift.heard == {**SAVE, "version": 43}


def test_a_brilliant_diamond_host_passes_on_the_console_trainer_record():
    from pokeldn.bdsp import host as bdsp, room
    gift = gift_for("bdsp", [("9015-387-0", bytes(328))], [])
    partner = bdsp.TradePartner(bytes(0), remote=gift)
    message = room.build_trade_traner("Florian", 0x0BAD, 0x0F00, casset_version=48, lang_id=2)
    assert partner.game(SimpleNamespace(), room.parse(message), message, 1.0) == [partner.trainer]
    assert gift.heard == {"ot": "Florian", "tid": 0x0BAD, "sid": 0x0F00, "version": 48, "language": 2}


def test_an_arceus_record_names_the_save():
    from pokeldn.pla import data_exchange
    assert data_exchange.read_trainer(data_exchange.REFERENCE_RECORD) == {
        "ot": "FreeShkreli", "tid": 0x9D87, "sid": 0x06F3, "version": 47, "gender": 0, "language": 2}
    payload = data_exchange.compress(data_exchange.build_record(player_id=0x0F000BAD, name="Florian"))
    assert data_exchange.read_trainer(data_exchange.decompress(payload))["ot"] == "Florian"


def test_a_scarlet_identity_record_names_the_save():
    import os
    from pokeldn.sv import reference, streams
    with open(os.path.join(reference.RECORDS, "001.bin"), "rb") as fh:
        record = streams.decompress(fh.read())
    assert reference.identity_trainer(record) == {"ot": "Player", "tid": 8131, "sid": 64817, "version": 50,
                                                  "gender": 0, "language": 2}
    assert reference.identity_trainer(b"\x02\x00" + record[2:]) is None


def test_a_scarlet_host_hears_the_identity_on_the_consoles_own_port():
    """A station sends its records on the 0x81 port of its station index (docs/sv.md, The records): a trading
    console's identity is on port 1, record 1 compressed; its port 0 carries only the stream opening."""
    import sv_host
    assert sv_host.identity_chunk(0x81, 1, 0x1F, 1)
    assert sv_host.identity_chunk(0x81, 3, 0x1F, 3)
    assert not sv_host.identity_chunk(0x81, 0, 0x0F, 1)       # its stream opening, retail
    assert not sv_host.identity_chunk(0x81, 1, 0x0F, 1)
    assert not sv_host.identity_chunk(0x81, 2, 0x1F, 1)       # another station's records


def test_a_za_identity_names_the_save_and_its_host_passes_it_on():
    from pokeldn.za import reference
    from tests.test_online import za_seat
    identity = reference.load("identity10")
    assert reference.identity_trainer(identity) == {"ot": "Player", "tid": 5071, "sid": 14217, "gender": 1,
                                                    "language": 2}
    gift = gift_for("za", [("9031-152-0", bytes(354))], [])
    host, console = za_seat(gift)
    console.game(reference.named(identity, "Florian"), 5.0)
    console.run(5.5, 5.0)
    assert gift.heard == {"ot": "Florian", "tid": 5071, "sid": 14217, "gender": 1, "language": 2}


def test_a_host_s_pop_up_is_one_warning_per_console_a_newer_reason_replacing_it(monkeypatch):
    """for_receiver.pop_up: the run's pop-up (pokeldn.popup) under the console's own id."""
    from pokeldn import popup
    sent = []
    monkeypatch.setattr(popup, "_live", {})
    monkeypatch.setattr(popup, "_sink", sent.append)
    tell = for_receiver.pop_up("gift-169.254.1.2")
    tell(for_receiver.FALLBACK_TITLE, "The save names no one.")
    tell(for_receiver.FALLBACK_TITLE, "PKHeX refused the card.")
    for_receiver.pop_up("gift-169.254.1.3")(for_receiver.FALLBACK_TITLE, "The save names no one.")
    assert [(m["id"], m["kind"], m["tone"], m["text"]) for m in sent] == [
        ("gift-169.254.1.2", "ack", "warning", "The save names no one."),
        ("gift-169.254.1.2", "ack", "warning", "PKHeX refused the card."),
        ("gift-169.254.1.3", "ack", "warning", "The save names no one.")]
    assert set(popup._live) == {"gift-169.254.1.2", "gift-169.254.1.3"}

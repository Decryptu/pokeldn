"""Every tool the app offers must build an argument list its entry point's own parser accepts, so a
flag renamed in bin/ fails here instead of in a user's session."""
import pytest

from pokeldn.app.catalog import GAMES
from pokeldn.app.command import accepted, build, missing_offer
from pokeldn.app.introspect import parser_of
from pokeldn.app.settings import Settings

TOOLS = [tool for game in GAMES for tool in game.tools if not tool.unavailable]


def _check(tool, values):
    parser = parser_of(tool.script)
    args = build(tool, values, {}, Settings())
    parser.parse_args(args)
    options = {o for action in parser._actions for o in action.option_strings}
    # argparse takes an unambiguous prefix of an option, so a misspelled flag could still parse.
    assert [a for a in args if a.startswith("--") and a not in options] == []
    assert not [a for a in args if "scratchpad" in a]


@pytest.mark.parametrize("tool", TOOLS, ids=[t.key for t in TOOLS])
def test_the_tool_builds_arguments_its_entry_point_accepts(tool):
    base = {f.key: {"file": "offer.bin"} for f in tool.fields if f.kind == "pokemon"}
    _check(tool, base)
    for choice in (f for f in tool.fields if f.kind == "choice"):
        for key, _ in choice.choices:   # every option of every dropdown
            _check(tool, {**base, choice.key: key})


LINKED = [tool for tool in TOOLS if tool.key != "swsh-gift"]   # the gift host advertises a card, no player


@pytest.mark.parametrize("tool", LINKED, ids=[t.key for t in LINKED])
def test_every_linked_tool_presents_the_apps_trainer(tool):
    """Every title is built the same: the console sees the trainer named in Settings, never a
    recorded one."""
    args = build(tool, {f.key: {"file": "/tmp/offer.bin"} for f in tool.fields if f.kind == "pokemon"},
                 {}, Settings(ot="ASH"))
    parser_of(tool.script).parse_args(args)
    assert "ASH" in args or any(a.startswith("ASH:") for a in args)


def test_sword_host_uses_the_apps_trainer_and_a_built_offer():
    tool = next(t for game in GAMES for t in game.tools if t.key == "swsh-host")
    settings = Settings(ot="POKELDN", tid=41234, sid=12345)
    args = build(tool, {"--offer-file": {"file": "/tmp/chosen.pk8"}}, {}, settings,
                 stamp="fixed")
    assert args[args.index("--player-name") + 1] == "POKELDN"
    assert args[args.index("--trainer-name") + 1] == "POKELDN"
    assert args[args.index("--trainer-tid") + 1] == "41234"
    assert args[args.index("--trainer-sid") + 1] == "12345"
    assert args[args.index("--offer-file") + 1] == "/tmp/chosen.pk8"
    assert "--advert" not in args and "--snapshot" not in args


@pytest.mark.parametrize("key", ["bdsp-join", "bdsp-host"])
def test_bdsp_reports_the_apps_trainer_language_in_both_roles(key):
    """PlayerInfo byte 0x7A sets the name limit on the console's greeting (docs/bdsp_protocol.md)."""
    tool = next(t for game in GAMES for t in game.tools if t.key == key)
    args = build(tool, {f.key: {"file": "/tmp/offer.pb8"} for f in tool.fields if f.kind == "pokemon"},
                 {}, Settings(language=5))
    assert parser_of(tool.script).parse_args(args).language == 5


@pytest.mark.parametrize("key", ["pla-host", "pla-join", "pla-gift-host"])
def test_pla_sends_the_apps_trainer_gender_in_its_data_exchange_record(key):
    """The record's gender and look show the console that player (docs/pla.md)."""
    tool = next(t for game in GAMES for t in game.tools if t.key == key)
    args = build(tool, {}, {}, Settings(gender=1))
    assert parser_of(tool.script).parse_args(args).gender == 1


QUEUES = [(tool, f) for tool in TOOLS for f in tool.fields if f.kind == "pokemon" and f.queue > 1]


@pytest.mark.parametrize("tool, field", QUEUES, ids=[t.key for t, _ in QUEUES])
def test_a_queue_reaches_the_entry_point_as_every_offer_in_order(tool, field):
    files = [f"/tmp/queued-{n}.bin" for n in range(1, field.queue + 1)]
    args = build(tool, {field.key: [{"file": f} for f in files] + [{"file": "/tmp/past-the-limit"}]},
                 {}, Settings())
    parsed = vars(parser_of(tool.script).parse_args(args))
    given = [v for value in parsed.values() for v in (value if isinstance(value, list) else [value])
             if isinstance(v, str) and v.startswith("/tmp/")]
    assert given == files
    if field.count:
        assert parsed[field.count.lstrip("-")] == field.queue


def test_one_offer_from_an_older_settings_file_still_builds():
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-host")
    args = build(tool, {"--trade-offer": {"file": "/tmp/single.pk9"}}, {}, Settings())
    assert args.count("--trade-offer") == 1 and "/tmp/single.pk9" in args


def test_raid_rewards_reach_the_host_as_rows_in_their_order():
    """Duplicates stay separate rows; the raid seed reaches the host as its integer."""
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    rows = [{"item_id": "1125", "quantity": "3"}, {"item_id": "50", "quantity": "10"},
            {"item_id": "1125", "quantity": "1"}]
    args = build(tool, {"--raid-pokemon": {"file": "/tmp/host.pk9"}, "--raid-seed": "000F34C3",
                        "--raid-reward": rows}, {}, Settings())
    parsed = parser_of(tool.script).parse_args(args)
    assert parsed.raid_reward == [(1125, 3), (50, 10), (1125, 1)] and parsed.raid_seed == 0xF34C3


def test_a_setting_kept_off_the_basic_tab_still_reaches_the_entry_point():
    """New PID and the time limit live on Advanced; their defaults must still be passed."""
    tool = next(t for game in GAMES for t in game.tools if t.key == "za-host")
    args = build(tool, {"--trade-offer": {"file": "/tmp/offer.pa9"}}, {}, Settings())
    parsed = parser_of(tool.script).parse_args(args)
    assert parsed.fresh_pid and parsed.seconds == 900
    args = build(tool, {"--trade-offer": {"file": "/tmp/offer.pa9"}, "--fresh-pid": False,
                        "--seconds": "1800"}, {}, Settings())
    parsed = parser_of(tool.script).parse_args(args)
    assert not parsed.fresh_pid and parsed.seconds == 1800


SAVING = [(game, tool) for game in GAMES for tool in game.tools
          if not tool.unavailable and any("{received}" in arg and not arg.endswith(".bin") for arg in tool.fixed)]


@pytest.mark.parametrize("game, tool", SAVING, ids=[tool.key for _, tool in SAVING])
def test_the_session_panel_finds_every_file_a_run_saves_and_none_from_another_run(game, tool, tmp_path):
    """A launcher names trade n with pokemon.trade_path or trade_runtime.received_paths, or writes
    under the prefix or folder its {received} argument names."""
    import os
    from types import SimpleNamespace
    from pokeldn.app.received import POKEMON, session_files
    from pokeldn.frlg.link.trade_runtime import received_paths
    from pokeldn.pokemon import EXTENSIONS, trade_path

    def saved(stamp: str) -> list[str]:
        args = build(tool, {}, {}, Settings(received=str(tmp_path)), stamp=stamp)
        paths = []
        for out in (a for a in args if a.startswith(str(tmp_path))):
            if POKEMON.search(out):
                mons = [SimpleNamespace(species_name="Mr. Mime", species=122)] * 2
                paths += [trade_path(out, 1), trade_path(out, 2), *received_paths(mons, out, "pk3", 2)]
            elif not out.endswith(".bin"):
                paths += [f"{out}_1.{EXTENSIONS[game.key]}", os.path.join(out, f"0a1b2c3d_1.{EXTENSIONS[game.key]}")]
        for path in paths:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").close()
        return paths

    ours = saved("20261001-120000")
    saved("20261001-115959")
    found = session_files(str(tmp_path), "20261001-120000")
    assert ours and sorted(map(os.path.normpath, found)) == sorted(map(os.path.normpath, ours))   # Windows mixes / and \


def test_an_event_raid_reaches_the_host_as_its_folder_den_and_catch_override():
    """The crystal choice gives way to the event's den; the override goes only with an event."""
    from pokeldn.app import events_gallery
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    base = {"--raid-pokemon": {"file": "/tmp/host.pk9"}, "--raid-seed": "52E6B438", "--raid-content": "black"}
    event = {**base, "--raid-event": "002 Charizard the Unrivaled", "--raid-event-group": "1",
             "--raid-catch-normal": True}
    parsed = parser_of(tool.script).parse_args(build(tool, event, {}, Settings()))
    assert parsed.raid_event == events_gallery.event_path("002 Charizard the Unrivaled")
    assert (parsed.raid_event_group, parsed.raid_catch_normal, parsed.raid_content) == (1, True, "standard")
    standard = parser_of(tool.script).parse_args(build(tool, {**base, "--raid-catch-normal": True,
                                                              "--raid-event-group": "2"}, {}, Settings()))
    assert (standard.raid_event, standard.raid_event_group, standard.raid_catch_normal,
            standard.raid_content) == (None, None, False, "black")


def test_an_event_the_gallery_lacks_is_refused_before_the_host_starts(tmp_path, monkeypatch):
    from pokeldn.app import events_gallery
    from pokeldn.app.command import problems
    monkeypatch.setattr(events_gallery, "location", lambda: tmp_path / "EventsGallery")
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    values = {"--raid-pokemon": {"file": "/tmp/host.pk9"}, "--raid-seed": "52E6B438",
              "--raid-event": "002 Charizard the Unrivaled"}
    assert problems(tool, values) == ["Download the event gallery in Raid event, or choose no event."]
    events = tmp_path / "EventsGallery"
    (events / "001 Eevee Spotlight" / "Files").mkdir(parents=True)
    (events / events_gallery.MANIFEST).write_text('{"commit": "abc", "date": "2026-09-06T21:05:05Z"}')
    assert problems(tool, values) == ["The chosen event is not in the event gallery any more."]
    (events / "002 Charizard the Unrivaled" / "Files").mkdir(parents=True)
    assert problems(tool, values) == []


def test_the_simulated_mystery_gift_trades_its_event_pokemon_as_the_trade_host_does():
    """Scarlet/Violet's Mystery Gift - Simulated is the trade host offering the event Pokemon picked."""
    tools = {t.key: t for game in GAMES for t in game.tools}
    gift, host = tools["sv-gift-host"], tools["sv-host"]
    assert (gift.script, gift.fixed) == (host.script, host.fixed)
    args = build(gift, {"--trade-offer": {"file": "/tmp/palafin.pk9", "event": "0503-964-0-10"}}, {}, Settings(),
                 stamp="fixed")
    assert args[args.index("--trade-offer") + 1] == "/tmp/palafin.pk9" and "--fresh-pid" in args
    assert args[args.index("--gift-event") + 1] == "0503-964-0-10" and "--for-receiver" in args
    off = build(gift, {"--trade-offer": {"file": "/tmp/palafin.pk9", "event": "0503-964-0-10"},
                       "--for-receiver": False}, {}, Settings(), stamp="fixed")
    assert "--for-receiver" not in off and "--gift-event" in off
    assert "--gift-event" not in build(host, {"--trade-offer": [{"file": "/tmp/palafin.pk9"}]}, {}, Settings(),
                                       stamp="fixed")
    assert accepted(gift.script) >= {"--gift-event", "--for-receiver"}
    assert missing_offer(gift, {}) == "Choose the Mystery Gift Pokemon first."


@pytest.mark.parametrize("game, attribute", [("lgpe", "offer"), ("bdsp", "offer"),
                                             ("pla", "trade_box_record"), ("sv", "trade_offer"),
                                             ("za", "trade_offer")])
def test_the_simulated_gift_queue_reaches_each_hosts_parser_in_trade_order(game, attribute):
    gift = next(t for g in GAMES for t in g.tools if t.key == f"{game}-gift-host")
    chosen = [{"file": f"gift-{n}.bin", "event": f"event-{n}", "your_ot": True}
              for n in range(1, 8)]
    args = parser_of(gift.script).parse_args(build(gift, {gift.fields[0].key: chosen}, {}, Settings(),
                                                  stamp="fixed"))
    offers = [args.offer, *args.next_offer] if game == "lgpe" else getattr(args, attribute)
    assert offers == [f"gift-{n}.bin" for n in range(1, 7)]
    assert args.gift_event == [f"event-{n}" for n in range(1, 7)] and args.for_receiver


def test_a_gift_with_its_own_trainer_holds_made_for_the_receiving_player_off():
    """A card that fixes its trainer goes as made: Made for the receiving player is held off and says why. A
    gift that names its receiver, or one picked before the app kept which it is, leaves it as set."""
    from pokeldn.app.command import locked
    gift = next(t for game in GAMES for t in game.tools if t.key == "sv-gift-host")
    receiver = next(f for f in gift.fields if f.key == "--for-receiver")
    palafin = {"file": "/tmp/palafin.pk9", "event": "0503-964-0-10", "ot": "Gavin", "your_ot": False}
    pikachu = {"file": "/tmp/pikachu.pk9", "event": "1501-25-0-2", "ot": "ASH", "your_ot": True}
    assert locked(receiver, gift, {"--trade-offer": palafin}) == (
        "This gift has its card's own trainer, OT Gavin, and goes as made.")
    args = build(gift, {"--trade-offer": palafin}, {}, Settings(), stamp="fixed")
    assert "--for-receiver" not in args and args[args.index("--gift-event") + 1] == "0503-964-0-10"
    assert locked(receiver, gift, {"--trade-offer": [palafin, palafin]}) == (
        "These gifts have their cards' own trainers, OT Gavin, and go as made.")
    for chosen in (pikachu, [palafin, pikachu], {k: v for k, v in palafin.items() if k != "your_ot"}, {}):
        assert locked(receiver, gift, {"--trade-offer": chosen}) == ""
        assert "--for-receiver" in build(gift, {"--trade-offer": chosen}, {}, Settings(), stamp="fixed")
    assert locked(next(f for f in gift.fields if f.key == "--fresh-pid"), gift, {"--trade-offer": palafin}) == ""


@pytest.mark.parametrize("game, offer", [("lgpe", "--offer"), ("bdsp", "--offer"), ("pla", "--trade-box-record"),
                                         ("za", "--trade-offer")])
def test_the_other_switch_games_simulate_their_mystery_gifts_through_their_trade_host(game, offer):
    """Let's Go, Brilliant Diamond/Shining Pearl, Legends Arceus and Legends Z-A take no Mystery Gift over local
    wireless: their Mystery Gift - Simulated is the trade host offering up to six event Pokemon in order,
    made for the receiving player as Scarlet/Violet's (docs/gift_simulated.md)."""
    tools = next(g for g in GAMES if g.key == game).tools
    gift, host = next(t for t in tools if t.key == f"{game}-gift-host"), tools[0]
    assert host.key == f"{game}-host" and tools[-1] is gift and gift.name == "Mystery Gift - Simulated"
    assert (gift.script, gift.fixed, gift.doc) == (host.script, host.fixed, "gift_simulated.md")
    field, receiver = gift.fields[:2]
    assert (field.key, field.events, field.required, field.queue) == (offer, True, True, 6)
    assert (receiver.key, receiver.kind, receiver.default) == ("--for-receiver", "switch", True)
    assert [f.key for f in gift.fields[2:]] == [f.key for f in host.fields if f.kind != "pokemon"]
    args = build(gift, {offer: {"file": "/tmp/gift.bin", "event": "9028-808-0"}}, {}, Settings(), stamp="fixed")
    assert args.count(offer) == 1 and args[args.index(offer) + 1] == "/tmp/gift.bin"
    # The host makes a card that names its receiver again for the console's save (pokeldn.receiver_gift).
    assert args[args.index("--gift-event") + 1] == "9028-808-0" and "--for-receiver" in args
    assert accepted(gift.script) >= {"--gift-event", "--for-receiver"}
    off = build(gift, {offer: {"file": "/tmp/gift.bin", "event": "9028-808-0"}, "--for-receiver": False}, {},
                Settings(), stamp="fixed")
    assert "--for-receiver" not in off
    assert "--gift-event" not in build(host, {offer: {"file": "/tmp/mon.bin"}}, {}, Settings(), stamp="fixed")
    assert missing_offer(gift, {}) == "Choose the Mystery Gift Pokemon first."


def test_every_game_lists_its_tools_in_one_order():
    """Trade (Host), Trade (Join), Trade (Online), Mystery Gift, then raids, host before join, then the
    Union Circle."""
    def rank(key):
        kind = key.split("-", 1)[1]
        for part in ("circle", "raid-host", "raid-join", "online", "join", "gift", "host"):
            if part in kind:
                return {"host": 0, "join": 1, "online": 2, "gift": 3, "raid-host": 4, "raid-join": 5,
                        "circle": 6}[part]
        raise AssertionError(key)
    for game in GAMES:
        ranks = [rank(t.key) for t in game.tools if t.key.startswith(game.key + "-")]
        assert ranks == sorted(ranks), (game.key, [t.key for t in game.tools])

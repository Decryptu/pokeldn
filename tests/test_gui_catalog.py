"""Every tool the app offers must build an argument list its entry point's own parser accepts, so a
flag renamed in bin/ fails here instead of in a user's session."""
import pytest

from pokeldn.app.catalog import GAMES
from pokeldn.app.command import build
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


LINKED = [tool for tool in TOOLS if tool.key not in ("swsh-gift", "sv-raid-host")]
# The gift host advertises a card, and the raid host replays a validated blank retail identity.


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


def test_sv_raid_builds_an_ordered_reward_list():
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    values = {"--raid-player-pokemon": {"file": "/tmp/host.pk9"},
              "--raid-seed": "000F34C3", "--reward": [
        {"item_id": "1", "quantity": "1"},
        {"item_id": "50", "quantity": "10"},
    ]}
    args = build(tool, values, {}, Settings())
    parsed = parser_of(tool.script).parse_args(args)
    assert parsed.raid_seed == 0x000F34C3
    assert parsed.raid_player_pokemon == "/tmp/host.pk9"
    assert parsed.reward == [(1, 1), (50, 10)]
    assert args.count("--reward") == 2


def test_sv_raid_join_uses_the_bundled_fixture():
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-join")
    args = build(tool, {}, {}, Settings(ot="POKELDN"))
    parsed = parser_of(tool.script).parse_args(args)
    assert parsed.raid_guest_replay and parsed.scene_id == 7
    assert parsed.record_trace is None and parsed.raid_lobby_trace is None
    assert parsed.raid_guest_ready_delay == 2
    assert parsed.raid_pokemon is None


def test_sv_raid_join_passes_the_legal_pokemon_builders_file():
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-join")
    args = build(tool, {"--raid-pokemon": {"file": "/tmp/raid.pk9"}}, {},
                 Settings(ot="POKELDN"))
    parsed = parser_of(tool.script).parse_args(args)
    assert parsed.raid_pokemon == "/tmp/raid.pk9"


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

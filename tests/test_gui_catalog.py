"""Every tool the app offers must build an argument list its entry point's own parser accepts, so a
flag renamed in bin/ fails here instead of in a user's session."""
import pytest

from gui.catalog import GAMES
from gui.command import build
from gui.introspect import parser_of
from gui.settings import Settings

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


def test_sword_host_uses_the_apps_trainer_and_a_built_offer():
    tool = next(t for game in GAMES for t in game.tools if t.key == "swsh-host")
    settings = Settings(ot="PkCamp", tid=41234, sid=12345)
    args = build(tool, {"--offer-file": {"file": "/tmp/chosen.pk8"}}, {}, settings,
                 stamp="fixed")
    assert args[args.index("--player-name") + 1] == "PkCamp"
    assert args[args.index("--trainer-name") + 1] == "PkCamp"
    assert args[args.index("--trainer-tid") + 1] == "41234"
    assert args[args.index("--trainer-sid") + 1] == "12345"
    assert args[args.index("--offer-file") + 1] == "/tmp/chosen.pk8"
    assert "--advert" not in args and "--snapshot" not in args

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

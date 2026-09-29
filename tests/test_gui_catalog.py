"""Every tool the app offers must build an argument list its entry point's own parser accepts, so a
flag renamed in bin/ fails here instead of in a user's session."""
import pytest

from gui.catalog import GAMES
from gui.command import build
from gui.introspect import parser_of
from gui.settings import Settings

TOOLS = [tool for game in GAMES for tool in game.tools]


def _values(tool, work):
    values = {}
    for field in tool.fields:
        if field.kind == "files":
            values[field.key] = ["a.pk3", "b.pk3"]
        elif field.kind == "argsfile":
            (work / "identity.txt").write_text("--code 12345678\n")
            values[field.key] = "identity.txt"
        elif field.required and not field.default:
            values[field.key] = "offer.bin"
    return values


@pytest.mark.parametrize("tool", TOOLS, ids=[t.key for t in TOOLS])
def test_the_tool_builds_arguments_its_entry_point_accepts(tool, tmp_path):
    for choice in [None] + [f for f in tool.fields if f.kind == "choice"]:
        values = _values(tool, tmp_path)
        if choice:   # every option of every dropdown, one at a time
            for key, _ in choice.choices:
                values[choice.key] = key
                parser_of(tool.script).parse_args(build(tool, values, {}, Settings(work_dir=str(tmp_path))))
        else:
            parser_of(tool.script).parse_args(build(tool, values, {}, Settings(work_dir=str(tmp_path))))

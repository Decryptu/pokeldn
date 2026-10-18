"""Literal template matching must remain bounded and preserve captured user data."""
import json
from string import Formatter

import pytest

from pokeldn.app import i18n


@pytest.mark.parametrize("source,text,expected", [
    ("Open {path}: {reason}", "Open C:\\Pikachu.txt: failed {x}", {"path": "C:\\Pikachu.txt", "reason": "failed {x}"}),
    ("{name} meets {name}.", "Red meets Red.", {"name": "Red"}),
    ("{name} meets {name}.", "Red meets Blue.", None),
    ("{{{text}}}", "{hello}", {"text": "hello"}),
    ("{a}x{b}x{c}x{d}z", "x" * 4096 + "w", None),
])
def test_bounded_matching_with_literal_delimiters(source, text, expected):
    assert i18n._match_template(tuple(Formatter().parse(source)), text) == expected


def test_ambiguous_source_fields_are_rejected_but_target_may_join_fields():
    def read(source, target):
        content = f"{json.dumps(source)} = {json.dumps(target)}".encode()
        return i18n.read_resources({"templates": "templates.toml"}, lambda _: content)
    with pytest.raises(ValueError, match="Separate"):
        read("{first}{last}", "{first} {last}")
    assert read("{first} {last}", "{first}{last}")["templates"]


def test_existing_language_packs_may_use_unicode_resource_filenames():
    content = b'"hello" = "bonjour"'
    assert i18n.read_pack({"locale": "fr", "strings": "\u7ffb\u8bd1.toml"}, lambda _: content) == {"hello": "bonjour"}

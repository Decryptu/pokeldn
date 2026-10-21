"""English/Chinese display audits, including mounted controls switching back to English."""
from dataclasses import fields, is_dataclass
from datetime import datetime
import re
import string
from types import SimpleNamespace

import flet as ft
import pytest

from gui.localization import localize_controls
from pokeldn.app import i18n
from pokeldn.app.catalog import GAMES

HAN = re.compile(r"[\u3400-\u9fff]")
TOOLS = [tool for game in GAMES for tool in game.tools if not tool.unavailable]


@pytest.fixture(autouse=True)
def language():
    previous = i18n.identity()
    i18n.select()
    yield
    i18n.select(previous[0], previous[1])


def display_strings(root):
    seen = set()
    def walk(value):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, (list, tuple)):
            for item in value:
                yield from walk(item)
        elif is_dataclass(value):
            for field in fields(value):
                if field.name.startswith("_") or field.name in ("data", "key"):
                    continue
                item = getattr(value, field.name)
                if isinstance(item, str) and (field.name in ("text", "label", "hint_text", "tooltip", "error", "content")
                                             or field.name == "value" and isinstance(value, ft.Text)):
                    yield str(item)
                else:
                    yield from walk(item)
    return list(walk(root))


def test_every_catalog_template_renders_in_both_languages_and_english_has_no_chinese():
    for selected in ("", i18n.BUILTIN_CHINESE, ""):
        i18n.select(selected, strict=True)
        for key, english in i18n._catalog.items():
            types = i18n._parameter_types.get(key, {})
            params = {field: datetime(2026, 1, 2) if types.get(field) in ("date", "datetime") else
                      2 if types.get(field) in ("number", "percent") or
                      isinstance(english, dict) and field == english["plural"] else
                      2 if any(spec for _, name, spec, _ in string.Formatter().parse(
                          english if isinstance(english, str) else english["other"]) if name == field) else
                      "Literal Player {name} C:/Save 00123456" for field in i18n._entry_fields(english)}
            rendered = i18n.text(key, **params)
            assert not rendered.startswith("⟦"), (selected, key, rendered)
            if not selected:
                assert not HAN.search(rendered), (key, rendered)
        assert not [d for d in i18n._diagnostics if d[3] in ("missing-text", "invalid-parameters", "undeclared-key")]


@pytest.mark.parametrize("tool", TOOLS, ids=[tool.key for tool in TOOLS])
def test_each_advanced_tab_relabels_both_directions_without_changing_values(tool):
    from gui.views.games import GamesView
    view = SimpleNamespace(tool=tool, search="", values={}, extra={}, flag_list=ft.Column())
    view.flag_row = lambda flag: GamesView.flag_row(view, flag)
    i18n.select(i18n.BUILTIN_CHINESE, strict=True)
    GamesView._fill_flags(view)
    original = display_strings(view.flag_list)
    assert original and any(HAN.search(value) for value in original)
    for selected in ("", i18n.BUILTIN_CHINESE, ""):
        i18n.select(selected, strict=True)
        localize_controls(view.flag_list)
        values = display_strings(view.flag_list)
        assert not any("⟦" in value for value in values), (tool.key, selected)
        if not selected:
            assert not any(HAN.search(value) for value in values), (tool.key, values)
        else:
            assert values == original
    assert view.values == view.extra == {}


def test_dynamic_raid_and_gts_names_follow_ids_in_both_languages():
    from gui.views.gts import wanted_text
    from gui.views.lair_seed import LairSeedPicker
    from gui.views.raid_event import den_label, swsh_boss_label
    from pokeldn.online.gts import Wants
    picker = LairSeedPicker.__new__(LairSeedPicker)
    boss = SimpleNamespace(species=146, form=1, gigantamax=False, level=70)
    den = SimpleNamespace(stars=(4, 5), species=(6, 25))
    i18n.select(i18n.BUILTIN_CHINESE, strict=True)
    labels = [picker._name(25), wanted_text(Wants(7, "Squirtle")), den_label(den),
              swsh_boss_label("sword", 5, "Isle of Armor", boss)]
    assert all(HAN.search(label) for label in labels)
    assert "伽勒尔" in labels[-1] and "铠之孤岛" in labels[-1]
    assert "喷火龙" in labels[2] and "皮卡丘" in labels[2]
    i18n.select()
    english = [i18n.render(label) for label in labels]
    assert all(not HAN.search(label) for label in english)
    assert english[0] == "Pikachu" and english[1] == "Squirtle"
    assert "Moltres" in english[-1] and "Isle of Armor" in english[-1]


def test_connected_controller_keeps_its_state_after_switching_language():
    from gui.views.controller import ControllerView
    view = ControllerView.__new__(ControllerView)
    view.client, view.connecting, view.error, view.board = object(), False, "", {"link": "serial COM7"}
    view.state = i18n.ref("core.controller.connected_229655")
    view.status = ft.Column()
    view.where = lambda board: ft.Text("COM7")
    view.render_footer = lambda: None
    for selected, label in ((i18n.BUILTIN_CHINESE, "断开连接"), ("", "Disconnect")):
        i18n.select(selected, strict=True)
        view.render_status(update=False)
        assert label in display_strings(view.status)
        assert view.state == "Connected"

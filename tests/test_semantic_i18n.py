"""Localization contracts, identity preservation and real-provider integration."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tomllib

import flet as ft
import pytest

from gui.localization import error_message, localize_controls
from pokeldn.app import i18n
from pokeldn.app.i18n import EntityKind, EntityRef, Game, MessageRef
from scripts.check_localization import check


@pytest.fixture(autouse=True)
def language(monkeypatch, semantic_pack):
    previous = i18n.identity()
    i18n.select()
    monkeypatch.setattr(i18n, "_providers", dict(i18n._providers))
    yield
    i18n.select(previous[0], previous[1])


def test_declared_calls_and_example_resources_are_valid():
    assert check() == []


def test_text_and_plural_keep_literal_parameters():
    path = r"C:\Save\Pikachu {count}.pk9"
    assert i18n.text("core.gift.egg.description", species=path) == f"Gives an Egg containing {path}."
    assert i18n.text("core.queue.count", count=1) == "1 Pokémon queued."
    assert i18n.text("core.plugins.source_count", count=1) == "1 plugin"
    assert i18n.text("core.plugins.source_count", count=2) == "2 plugins"
    i18n.select("semantic-test-language", strict=True)
    assert i18n.text("core.gift.egg.description", species=path) == f"赠送{path}的蛋。"
    assert i18n.text("core.queue.count", count=2) == "已将 2 只宝可梦加入队列。"
    assert i18n.text("core.plugins.source_count", count=2) == "2 个插件"
    assert "parameters" in i18n.text("core.queue.count", count="2")
    assert i18n.text("undeclared.key").startswith("⟦")


def test_missing_entry_falls_back_as_a_complete_english_entry(monkeypatch, caplog):
    i18n.select("semantic-test-language", strict=True)
    monkeypatch.setattr(i18n, "_strings", {})
    assert i18n.text("core.queue.count", count=1) == "1 Pokémon queued."
    assert "missing-text" in caplog.text


def test_typed_numbers_dates_and_finite_plural_counts():
    from datetime import datetime
    assert "12,345" in i18n.text("core.gift.money.description", quantity=12345, maximum=9999999)
    i18n.select("semantic-test-language", strict=True)
    assert "12,345" in i18n.text("core.gift.money.description", quantity=12345, maximum=9999999)
    assert "2020年" in i18n.text("core.presentation.timestamp", value=datetime(2020, 6, 15, 12))
    assert "parameters" in i18n.text("core.queue.count", count=float("nan"))


def test_resources_reject_wrong_fields_unknown_kinds_and_unsafe_paths(semantic_pack):
    root = semantic_pack.folder
    meta = tomllib.loads((root / "plugin.toml").read_text(encoding="utf-8"))
    strings = meta["locales"]["zh-Hans"]["strings"]
    def read(path):
        if path == strings:
            return b'[strings]\n"core.gift.egg.description" = "{other}"\n'
        return (root / path).read_bytes()
    with pytest.raises(ValueError, match="parameters"):
        i18n.read_resources(meta, read)
    bad = copy.deepcopy(meta)
    bad["localization_format"] = 999
    with pytest.raises(ValueError, match="format"):
        i18n.read_resources(bad, read)
    bad = copy.deepcopy(meta)
    bad["locales"]["zh-Hans"]["strings"] = "../strings.toml"
    with pytest.raises(ValueError, match="inside"):
        i18n.read_resources(bad, lambda p: b"")
    with pytest.raises(ValueError, match="width"):
        i18n._fields("{number:999999999999999}")
    with pytest.raises(ValueError, match="Typed parameters"):
        i18n._validate_typed_formats("typed.number", "{number:d}", {"number": "number"})


def test_failed_switch_is_atomic():
    i18n.select("semantic-test-language", strict=True)
    before = i18n.identity()
    with pytest.raises(ValueError, match="Cannot load"):
        i18n.select("missing-language", strict=True)
    assert i18n.identity() == before
    assert i18n.text("core.common.save") == "保存"


def test_entity_fallback_and_immutable_tables(monkeypatch):
    i18n.register_name_provider("demo", lambda kind, locale: {
        "version": "1", "names": {94: "Psychic", 45: "Growl"} if locale == "en" else {94: "精神强念"},
        "forms": {128: {0: "Tauros", 2: "Tauros (Blaze)"}}})
    monkeypatch.setattr(i18n, "_locale", "zh-Hans")
    monkeypatch.setattr(i18n, "_resources", {"entities": {"demo": {"move": {"94": "覆盖名称"}, "species": {"128": "肯泰罗"}}}})
    assert i18n.name(EntityKind.MOVE, 94, game="demo") == "覆盖名称"
    assert i18n.name(EntityKind.MOVE, 45, game="demo") == "Growl"
    assert i18n.name(EntityKind.MOVE, 99999, game="demo") == "move #99999"
    assert i18n.name(EntityRef("demo", EntityKind.SPECIES, 128)) == "肯泰罗"
    assert i18n.name(EntityRef("demo", EntityKind.SPECIES, 128, 2)) == "Tauros (Blaze)"
    with pytest.raises(TypeError):
        i18n.names(EntityKind.MOVE, game="demo").by_id[94] = "changed"


def test_same_locale_different_pack_never_reuses_overrides(monkeypatch):
    i18n.register_name_provider("demo", lambda kind, language: {"version": "v1", "names": {1: "Base"}})
    monkeypatch.setattr(i18n, "_locale", "zh-Hans")
    monkeypatch.setattr(i18n, "_selected", "one")
    monkeypatch.setattr(i18n, "_resources", {"entities": {"demo": {"ability": {"1": "甲"}}}})
    assert i18n.name(EntityKind.ABILITY, 1, game="demo") == "甲"
    monkeypatch.setattr(i18n, "_selected", "two")
    monkeypatch.setattr(i18n, "_resources", {"entities": {"demo": {"ability": {"1": "乙"}}}})
    assert i18n.name(EntityKind.ABILITY, 1, game="demo") == "乙"


def test_language_change_during_name_request_cannot_publish_old_labels():
    asked = []
    def provider(kind, language):
        asked.append(language)
        if len(asked) == 1:
            i18n.select("semantic-test-language", strict=True)
        return {"version": "v1", "names": {94: "精神强念" if language == "zh-Hans" else "Psychic"}}
    i18n.register_name_provider("demo", provider)
    assert i18n.name(EntityKind.MOVE, 94, game="demo") == "精神强念"


def test_temporary_name_service_failure_does_not_cache_english_fallback():
    available = False
    def provider(kind, language):
        if language == "zh-Hans" and not available:
            raise OSError("temporary failure")
        return {"version": "v1", "names": {94: "精神强念" if language == "zh-Hans" else "Psychic"}}
    i18n.register_name_provider("temporary", provider)
    i18n.select("semantic-test-language", strict=True)
    assert i18n.name(EntityKind.MOVE, 94, game="temporary") == "Psychic"
    available = True
    assert i18n.name(EntityKind.MOVE, 94, game="temporary") == "精神强念"


def test_mounted_controls_relabel_without_changing_input_or_selected_id():
    label = ft.Text(i18n.text("core.common.save"))
    field = ft.TextField(value="Save 皮卡丘 {name} 00123456", hint_text=i18n.text("core.common.save"))
    selected = ft.Dropdown(value="94", options=[ft.DropdownOption(key="94", text=i18n.text("core.common.save"))])
    root = ft.Column([label, field, selected])
    localize_controls(root)
    i18n.select("semantic-test-language", strict=True)
    localize_controls(root)
    assert label.value == field.hint_text == selected.options[0].text == "保存"
    assert selected.value == selected.options[0].key == "94"
    assert field.value == "Save 皮卡丘 {name} 00123456"
    # A transport may normalize subclasses to plain strings; bindings retain the key.
    label._values["value"] = str(label.value)
    i18n.select()
    localize_controls(root)
    assert label.value == "Save"


def test_dynamic_catalog_assignment_resolves_at_control_update():
    from gui import theme
    control = theme.text("initial")
    control.value = i18n.ref("core.common.save")
    i18n.select("semantic-test-language", strict=True)
    control.before_update()
    assert control.value == "保存"


def test_structured_messages_round_trip_and_do_not_translate_names():
    value = MessageRef("core.gift.egg.description", {"species": EntityRef("sv", EntityKind.SPECIES, 25)})
    decoded = MessageRef.from_wire(json.loads(json.dumps(value.to_wire())))
    assert decoded == value
    assert copy.deepcopy(decoded) == value
    i18n.select("semantic-test-language", strict=True)
    assert i18n.render(decoded) == "赠送皮卡丘的蛋。"


def test_documents_fallback_body_title_and_sections_together():
    english = {doc.id: doc for doc in i18n.documents()}
    i18n.select("semantic-test-language", strict=True)
    for doc in i18n.documents():
        if doc.id not in i18n._resources["documents"]:
            assert doc == english[doc.id]
        else:
            assert doc.locale == "zh-Hans"
            body = doc.path.read_text(encoding="utf-8")
            assert all(f'id="{section.id}"' in body for section in doc.sections)


def test_document_search_uses_localized_content():
    from gui.views import docs
    i18n.select("semantic-test-language", strict=True)
    sections = docs.index(docs.pages(), i18n.document("core.guide.guide").title)
    assert docs.search(sections, "礼物")


def test_frlg_application_ids_are_national_and_adapter_is_reversible():
    from pokeldn.frlg.gift import builder
    original = {"steps": [{"type": "egg", "species": 277}], "card": {"icon": 277}}
    normalized = builder.entity_state(original)
    assert normalized["steps"][0]["species"] == normalized["card"]["icon"] == 252
    assert builder.cartridge_state(normalized) == original
    assert original["steps"][0]["species"] == 277
    assert builder.entity_state(normalized) == normalized


def test_npc_records_resolve_real_form_moves_and_ability():
    from pokeldn.sv import raid_partners
    partner = raid_partners.pool(4)[6]
    assert partner.trainer_key == "6"
    assert (partner.species, partner.form) == (128, 1)
    assert partner.move_ids == (873, 526, 372)
    assert partner.ability_id == 22


def test_real_pkhex_names_preserve_ids_and_do_not_filter_availability():
    from pokeldn import pokemon
    i18n.select("semantic-test-language", strict=True)
    assert i18n.name(EntityKind.MOVE, 94, game=Game.SV) == "精神强念"
    assert i18n.name(EntityKind.SPECIES, 252, game=Game.FRLG) == "木守宫"
    assert i18n.name(EntityKind.ITEM, 68, game=Game.FRLG) == "神奇糖果"
    assert i18n.name(EntityKind.NATURE, 0, game=Game.SV) == "勤奋"
    assert i18n.name(EntityKind.SPECIES, 128, game=Game.SV, form=1) == "肯泰罗（帕底亚的样子·斗战种）"
    assert i18n.name(EntityKind.SPECIES, 479, game=Game.SV, form=1) == "洛托姆（加热）"
    all_ids = set(i18n.names(EntityKind.MOVE, game=Game.SV).by_id)
    allowed = {n["id"] for n in pokemon.SERVICE.names("sv", "moves")}
    assert allowed < all_ids


def test_real_helper_errors_carry_a_semantic_message():
    from pokeldn import pokemon
    i18n.select("semantic-test-language", strict=True)
    with pytest.raises(pokemon.BuilderError) as error:
        pokemon.SERVICE._ask({"cmd": "name_table", "game": "sv", "kind": "missing"})
    assert error.value.message.key.startswith("core.pkhex.")
    assert error_message(error.value) == "未知实体类别 missing。"


def test_gift_event_facts_keep_entity_ids_across_language_switches(monkeypatch):
    from gui.localization import DisplayService
    from gui.views.event_gifts import facts
    from pokeldn import pokemon
    original = pokemon.SERVICE._ask
    def ask(request):
        if request["cmd"] == "gift_events":
            return {"events": [{"species_id": 25, "form_id": 0, "level": 50, "shiny": "never",
                                "ball_id": 4, "held_item_id": 0, "move_ids": [94], "tera_type_id": 13}]}
        return original(request)
    monkeypatch.setattr(pokemon.SERVICE, "_ask", ask)
    event = DisplayService()._ask({"cmd": "gift_events", "game": "sv"})["events"][0]
    message = facts(event)
    assert "Pikachu" in message and event["held_item"] == ""
    i18n.select("semantic-test-language", strict=True)
    assert "皮卡丘" in i18n.render(message) and "超能力" in i18n.render(message)
    assert i18n.render(event["moves"][0]) == "精神强念"
    assert (event["species_id"], event["move_ids"]) == (25, [94])


def test_plugin_catalog_registers_after_a_language_pack_is_selected():
    from pokeldn import plugins
    import importlib.util
    folder = Path(__file__).resolve().parents[1] / "examples/plugins/hello_localized"
    plugin = plugins.Plugin("hello-localized", "Example", folder=folder)
    spec = importlib.util.spec_from_file_location("localized_example", folder / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    i18n.select("semantic-test-language", strict=True)
    try:
        module.register(plugins.API(plugin))
        assert i18n.text("hello-localized.result", name="Pikachu Save") == "你好，Pikachu Save！"
        assert i18n.render(plugin.tools[0][1].name) == "本地化示例"
    finally:
        i18n.unregister_namespace(plugin.id)


def test_advanced_help_and_choice_labels_have_semantic_contracts(monkeypatch):
    from scripts.check_localization import check_display_sources
    i18n.select("semantic-test-language", strict=True)
    assert "训练家" in i18n.help_text("frlg-trade-host", "--language", "untranslated")
    assert i18n.choice_text("frlg-trade-host", "--language", "english") == "英语"
    key = "core.help.frlg-trade-host.language"
    monkeypatch.delitem(i18n._catalog, key)
    assert any(key in error for error in check_display_sources())


def test_gift_metadata_is_translated_without_changing_its_identity():
    from pokeldn.frlg.gift import builder as frlg
    from pokeldn.rse import gift_builder as rse
    from pokeldn.swsh import events, gift_builder as swsh
    card = events.load()[0]
    original = events.record(card["key"])
    i18n.select("semantic-test-language", strict=True)
    assert dict((key, i18n.render(label)) for key, label in frlg.STEPS)["item"] == "道具"
    assert dict((key, i18n.render(label)) for key, label in frlg.STEPS)["egg"] == "蛋"
    assert "关闭所有" in i18n.render(frlg.STOPS_BOOSTS)
    assert "妈妈" in i18n.render(frlg.MOM_STEPS)
    assert "火红（法语）" in [i18n.render(label) for label in frlg.CARTRIDGES.values()]
    assert i18n.render(rse.PRESET["aurora-ticket"].label) == "极光船票"
    assert "代欧奇希斯" in i18n.render(rse.PRESET["aurora-ticket"].summary)
    assert i18n.render(events.GROUP_LABELS["Items"]) == "道具"
    assert "火焰鸟" in i18n.render(card["label"]) and "国际挑战赛" in i18n.render(card["label"])
    assert events.record(card["key"]) == original
    assert dict((key, i18n.render(label)) for key, label, _ in swsh.KINDS)["items"] == "道具"


def test_official_swsh_preview_uses_ids_and_form_in_the_current_language():
    from gui.views.gifts import GiftBuilder
    from pokeldn.swsh import gift_builder
    picker = GiftBuilder.__new__(GiftBuilder)
    picker.game, picker.module = "swsh", gift_builder
    i18n.select("semantic-test-language", strict=True)
    card = gift_builder.OFFICIAL.load()[0]
    description = i18n.render(picker._event_summary(card))
    assert "火焰鸟" in description and "伽勒尔" in description and "70" in description
    i18n.select()
    assert "Moltres" in i18n.render(picker._event_summary(card))


def test_tooltip_theme_uses_the_cjk_font_and_fallback():
    from gui import theme
    i18n.select("semantic-test-language", strict=True)
    style = theme.app_theme().tooltip_theme.text_style
    assert style.font_family == theme.CJK_FONT
    assert theme.CJK_FONT in style.font_family_fallback

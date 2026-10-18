"""Display adapters must preserve the upstream English behavior and user-owned text."""
from types import SimpleNamespace
from copy import deepcopy
import json
from pathlib import Path

import pytest

from gui import localization
from pokeldn.app import i18n


def test_english_presentation_keeps_module_text_and_identifiers():
    i18n.select()
    summary = "Pikachu · level 50 · shiny · 'Eevee' · Hardy · holding Light Ball"
    assert localization.summary_text(summary) == summary
    assert localization.raid_label("7 stars: Pikachu the Unrivaled") == "7 stars: Pikachu the Unrivaled"
    assert localization.import_note("Left its Light Ball behind · Forgot Thunderbolt") == (
        "Left its Light Ball behind · Forgot Thunderbolt")
    assert localization.error_message(ValueError("unknown button 'Eevee'")) == "unknown button 'Eevee'"
    assert localization.translate_app_log("[done] trade 1 complete") == "[done] trade 1 complete"
    assert localization.translate_app_log("[app] Exited with code 0.") == "[app] Exited with code 0."


def test_game_metadata_and_event_records_are_not_mutated():
    card = {"group": "Items", "label": "Test title", "record": b"unread"}
    assert localization.event_label("swsh", card) == "Test title"
    assert card == {"group": "Items", "label": "Test title", "record": b"unread"}


def test_translated_document_keeps_original_fragment_ids():
    pytest.importorskip("flet")
    from gui.views.widgets import heading_sections
    original = "# Guide\nStart.\n## Shared heading\nOne.\n## Shared heading\nTwo."
    translated = "# Manuel\nDebut.\n## Section\nUn.\n## Section\nDeux."
    sections = list(heading_sections(translated, reference=original))
    assert [(key, title) for key, title, _ in sections if title] == [
        ("guide", "Manuel"), ("shared-heading", "Section"), ("shared-heading-1", "Section")]


def test_unrecognized_errors_and_os_errors_keep_literal_values(monkeypatch):
    monkeypatch.setattr(i18n, "message", lambda text: "translated" if text == "known error" else text)
    assert localization.error_message("known error") == "translated"
    assert localization.error_message("new error in Pikachu.pk9") == "new error in Pikachu.pk9"
    error = FileNotFoundError(2, "known error", "Eevee.pk9")
    assert localization.error_message(error) == str(error)


def test_explicit_anchors_work_when_a_translation_adds_sections():
    from gui.views.widgets import heading_sections
    translated = '<a id="guide"></a>\n# Manuel\nTexte.\n<a id="setup"></a>\n## Installation\nAutre.\n## Extra'
    found = [(key, title) for key, title, _ in heading_sections(translated, reference="# Guide\n## Setup") if title]
    assert found == [("guide", "Manuel"), ("setup", "Installation"), ("extra", "Extra")]


def test_english_document_heading_anchors_keep_existing_fragment_ids():
    from gui.views.widgets import anchor
    assert anchor("Pokémon preparation") == "pokmon-preparation"
    assert anchor("## 2. [Ending a run](architecture.md)") == "ending-a-run"
    assert anchor("使用说明") == "使用说明"


def test_frlg_gift_species_keep_working_without_pkhex(french_copy, monkeypatch):
    from gui.views import gifts
    from pokeldn import pokemon
    def unavailable(*args):
        raise pokemon.BuilderError("PKHeX is missing")
    monkeypatch.setattr(gifts.SERVICE, "names", unavailable)
    expected = dict(gifts.frlg.species_names())
    localized = {n["id"]: n["name"] for n in gifts.species_frlg()}
    assert localized.keys() == expected.keys() and localized[7] == "Carapuce"
    assert localized[277] == expected[277]
    monkeypatch.setattr(i18n, "_pack", None)
    assert gifts.species_frlg() == [{"id": n, "name": name} for n, name in gifts.frlg.species_names()]


def test_frlg_gift_species_load_on_picker_worker_and_keep_cartridge_ids(french_copy, monkeypatch):
    from gui.views import gifts, pokemon
    workers, calls = [], []
    class DeferredThread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): workers.append(self.target)
    monkeypatch.setattr(pokemon.threading, "Thread", DeferredThread)
    def names(game, kind):
        calls.append((game, kind))
        return [{"id": 277, "name": "Arcko"}]
    monkeypatch.setattr(gifts.SERVICE, "names", names)
    picker = pokemon.NamePicker(SimpleNamespace(ui=lambda fn: fn()), "frlg", "species", "277",
                                lambda value: None, names=gifts.species_frlg)
    assert not calls and picker.dropdown.disabled
    workers.pop()()
    assert calls == [("frlg", "species3")]
    assert picker.dropdown.value == "277" and not picker.dropdown.disabled
    assert any(option.key == "277" and option.text == "Arcko" for option in picker.dropdown.options)


@pytest.fixture
def french_copy(monkeypatch):
    """Exercise display boundaries without depending on a separately distributed language pack."""
    messages = {"Growlithe": "Caninos", "Intimidate": "Intimidation", "Fire": "Feu",
                "Ember": "Flammèche", "Leer": "Groz'Yeux", "Bite": "Morsure",
                "level 50": "niveau 50", "Hardy": "Hardi", "East": "Est"}
    monkeypatch.setattr(i18n, "_pack", SimpleNamespace(locale="fr", resources={
        "messages": messages, "terms": {"Squirtle": "Carapuce"}}))
    monkeypatch.setattr(i18n, "_strings", {})
    monkeypatch.setattr(i18n, "_terms_pattern", None)
    monkeypatch.setattr(i18n, "_message_rules", [])


@pytest.mark.parametrize("localized", [False, True])
def test_received_bank_deposit_keeps_canonical_names_and_the_original_reply(tmp_path, localized):
    from pokeldn import pokemon
    from pokeldn.app import bank

    source = tmp_path / "received.pk9"
    source.write_bytes(b"received record")
    english = dict(species="Squirtle", species_id=7, level=50, nature="Hardy", legal=True,
                   nickname="East", is_nicknamed=True)
    info = {**english, "species": "Carapuce", "nature": "Hardi",
            "canonical": {"species": "Squirtle", "nature": "Hardy"}} if localized else english
    original = deepcopy(info)
    folder = tmp_path / "Bank"
    entry = bank.deposit("sv", str(source), info, folder=folder)
    meta = json.loads(Path(entry.path).with_suffix(".json").read_text(encoding="utf-8"))

    assert Path(entry.path).name.startswith("Squirtle-")
    assert meta["species"] == "Squirtle" and meta["species_id"] == 7
    assert entry.summary == meta["summary"] == pokemon.summary(english)
    assert bank.data(entry) == source.read_bytes() == b"received record"
    assert info == original
    assert bank.deposit("sv", str(source), info, folder=folder) is None


def _walk(control):
    import flet as ft
    yield control
    for child in [*(getattr(control, "controls", None) or []), getattr(control, "content", None)]:
        if isinstance(child, ft.Control):
            yield from _walk(child)


def _texts(control):
    import flet as ft
    return [c.value for c in _walk(control) if isinstance(c, ft.Text)]


def test_gts_localized_selection_publishes_canonical_wants(french_copy, monkeypatch):
    ft = pytest.importorskip("flet")
    from gui.views import gts as view_gts
    from pokeldn.online import gts

    monkeypatch.setattr(view_gts.SERVICE, "species", lambda game: [{"id": 7, "name": "Carapuce"}])
    monkeypatch.setattr(view_gts.pokemon.SERVICE, "species", lambda game: [{"id": 7, "name": "Squirtle"}])
    entry = SimpleNamespace(id="received", legal=True, game="sv", summary="Squirtle · level 50")
    monkeypatch.setattr(view_gts.bank, "entries", lambda: [entry])
    monkeypatch.setattr(view_gts.bank, "queued", lambda *args: False)
    dialogs, deposited = [], []
    view = view_gts.GtsView.__new__(view_gts.GtsView)
    view.app = SimpleNamespace(settings=None, ui=lambda action: action(),
        page=SimpleNamespace(show_dialog=dialogs.append, pop_dialog=lambda: None),
        gts=SimpleNamespace(deposit=lambda entry, wants: deposited.append((entry, wants))))
    view.species, view.canonical_species, view.visible, view.picker = [], {}, False, ft.Dropdown()
    view._work = lambda status, action, done: action()
    view._load_species()
    assert any(option.key == "7" and option.text == "Carapuce" for option in view.picker.options)
    view._deposit_dialog()
    wanted = next(c for c in _walk(dialogs[0].content) if isinstance(c, ft.Dropdown)
                  and any(option.key == "7" for option in c.options))
    assert next(option.text for option in wanted.options if option.key == "7") == "Carapuce"
    own = next(c for c in _walk(dialogs[0].content) if isinstance(c, ft.Dropdown)
               and any(option.key == "received" for option in c.options))
    assert own.options[0].text.startswith("Carapuce, niveau 50")
    wanted.value = "7"
    dialogs[0].actions[-1].on_click(None)

    selected, wants = deposited[0]
    assert selected is entry and wants == gts.Wants(7, "Squirtle")
    assert view_gts.wanted_text(wants) == "Carapuce"
    # Inspect the real wire serializer without signing or publishing to a relay.
    identity = SimpleNamespace(event=lambda kind, tags, content, **kw: json.loads(content))
    payload = gts.listing_event(identity, "listing", "sv", {"species": "Pikachu", "species_id": 25},
                                b"record", wants, "East", "test", 123456)
    assert payload["wants"] == {"species": 7, "name": "Squirtle", "min_level": 1, "max_level": 100}
    monkeypatch.setattr(i18n, "_pack", None)
    assert view_gts.wanted_text(wants) == "Squirtle"


def test_raid_partner_translates_moves_and_type_without_changing_game_data(french_copy, monkeypatch):
    ft = pytest.importorskip("flet")
    from gui.views import raid_partners as view_partners
    from pokeldn.sv.raid_partners import Partner

    monkeypatch.setattr(view_partners, "Sprite", lambda *args, **kw: SimpleNamespace(control=ft.Container()))
    view = view_partners.RaidPartnersPicker.__new__(view_partners.RaidPartnersPicker)
    view.app, view.picks, view.free, view.level = None, [], 3, 16
    partner = Partner("East", 58, "Growlithe", 16, "Intimidate", ("Ember", "Leer", "Bite"), "Fire")
    original = deepcopy(partner)

    texts = _texts(view._card(partner))
    assert {"East", "Caninos", "Intimidation", "Feu", "Flammèche", "Groz'Yeux", "Morsure"} <= set(texts)
    assert not {"Est", "Fire", "Ember", "Leer", "Bite"} & set(texts)
    assert partner == original
    monkeypatch.setattr(i18n, "_pack", None)
    assert {"Growlithe", "Fire", "Ember", "Leer", "Bite"} <= set(_texts(view._card(partner)))


@pytest.mark.parametrize("number", [None, 1])
def test_queued_gift_renders_translated_summary_without_changing_saved_values(french_copy, monkeypatch, number):
    ft = pytest.importorskip("flet")
    from gui.views import event_gifts

    monkeypatch.setattr(event_gifts, "Sprite", lambda *args, **kw: SimpleNamespace(control=ft.Container()))
    view = event_gifts.EventGiftPicker.__new__(event_gifts.EventGiftPicker)
    view.app = None
    value = dict(legal=True, species=7, title="East", ot="East", moves=["Ember"],
                 summary="Squirtle · level 50 · 'East' · Hardy")
    original = deepcopy(value)

    texts = _texts(view._result_card(value, number))
    assert "Carapuce · niveau 50 · 'East' · Hardi" in texts
    assert "Flammèche · OT East" in texts
    assert ("East" if number is None else "1. East") in texts
    assert value == original
    monkeypatch.setattr(i18n, "_pack", None)
    assert value["summary"] in _texts(view._result_card(value, number))


@pytest.fixture
def desktop_copy(french_copy, monkeypatch):
    i18n._pack.resources["messages"].update({"english": "anglais", "The delivery man": "Livreur",
        "any Pokemon Center, after the card is saved": "au centre", "Item": "Objet",
        "Asking GitHub for the latest raid events...": "Lecture des événements..."})
    monkeypatch.setattr(i18n, "_strings", {"games.default_choice": "défaut",
        "widgets.choose_file": "Choisir un fichier", "widgets.choose_folder": "Choisir un dossier",
        "presentation.date_time_format": "%Y/%m/%d %H:%M"})


def test_advanced_choice_translates_labels_but_keeps_argument_values(desktop_copy):
    ft = pytest.importorskip("flet")
    from gui.views.games import GamesView
    view = GamesView.__new__(GamesView)
    view.tool = SimpleNamespace(fields=[], key="frlg-trade-host")
    view.stored = lambda: {"values": {}, "extra": {}}
    flag = SimpleNamespace(option="--language", kind="choice", choices=["english"], default="english",
                           help="Trainer language", required=False)
    row = view.flag_row(flag)
    dropdown = next(c for c in _walk(row) if isinstance(c, ft.Dropdown))
    assert [(o.key, o.text) for o in dropdown.options] == [(dropdown.options[0].key, "défaut"),
                                                         ("english", "anglais")]
    assert flag.choices == ["english"] and not view.extra


def test_gift_giver_and_steps_translate_labels_without_changing_card_payload(desktop_copy):
    ft = pytest.importorskip("flet")
    from gui.views.gifts import GiftBuilder
    view = GiftBuilder.__new__(GiftBuilder)
    view.value = {"build": {"card": {"title": "Pokemon", "body": ["Item", "", "", ""]},
                  "steps": [{"type": "item", "item": 1, "quantity": 1}]}}
    for method in ("text_field", "name_field", "number_field", "switch_row"):
        setattr(view, method, lambda *a, **kw: ft.Container())
    before = deepcopy(view.state)
    control = view.frlg_card()
    giver = next(c for c in _walk(control) if isinstance(c, ft.Dropdown))
    assert giver.options[0].key == "deliveryman" and giver.options[0].text == "Livreur, au centre"
    assert "1. Objet" in _texts(control)
    assert any(getattr(c, "content", None) == "Objet" for c in _walk(control))
    assert view.state == before


def test_gts_tile_and_own_rows_translate_species_only(desktop_copy, monkeypatch):
    ft = pytest.importorskip("flet")
    from gui.views import gts as views
    from pokeldn.online.gts import Wants
    monkeypatch.setattr(views, "Sprite", lambda *a, **kw: SimpleNamespace(control=ft.Container()))
    view = views.GtsView.__new__(views.GtsView)
    view.app, view.selected = None, ""
    listing = SimpleNamespace(key="key", d="d", game="sv", wants=Wants(7, "Squirtle"),
                              pokemon={"species": "Growlithe", "species_id": 58, "level": 50})
    before = deepcopy(listing.pokemon)
    assert view._tile(listing).tooltip == "Caninos level 50 for Carapuce"
    state = {"id": "own", "info": listing.pokemon, "status": "active", "role": "listing",
             "wants": {"species": 7, "name": "Squirtle"}}
    assert "Caninos for Carapuce" in _texts(view._mine_row(state))
    assert listing.pokemon == before and state["wants"]["name"] == "Squirtle"


@pytest.mark.parametrize("mode", ["file", "dir"])
def test_path_picker_passes_translated_title_and_original_extensions(desktop_copy, tmp_path, mode):
    import asyncio
    from gui.views.widgets import PathField
    called = []
    async def choose(**kwargs):
        called.append(kwargs)
        return [] if mode == "file" else None
    picker = SimpleNamespace(pick_files=choose, get_directory_path=choose)
    field = PathField(picker, lambda: str(tmp_path), mode=mode, exts=("pokegift", "wc3"))
    asyncio.run(field._browse(None))
    assert called[0]["dialog_title"] == ("Choisir un fichier" if mode == "file" else "Choisir un dossier")
    assert called[0]["initial_directory"] == str(tmp_path)
    if mode == "file":
        assert called[0]["allowed_extensions"] == ["pokegift", "wc3"]
    assert field.field.value == ""


@pytest.mark.parametrize("done,total", [(0, 0), (10, 0), (10, 20)])
def test_raid_download_callback_translates_progress_before_formatting(desktop_copy, monkeypatch, done, total):
    import threading
    ft = pytest.importorskip("flet")
    from gui.views import raid_event
    class InlineThread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(raid_event.threading, "Thread", InlineThread)
    monkeypatch.setattr(raid_event.time, "monotonic", lambda: 1)
    view = raid_event.RaidEventPicker.__new__(raid_event.RaidEventPicker)
    view.stop = threading.Event()
    view._working = lambda *a, **kw: None
    view.status = SimpleNamespace(value="", update=lambda: None)
    view.bar = SimpleNamespace(value=None, update=lambda: None)
    view.actions = ft.Row()
    view.control = SimpleNamespace(update=lambda: None)
    view.app = SimpleNamespace(ui=lambda fn: fn())
    view.view = SimpleNamespace(gallery_changed=lambda: None)
    view._run(lambda progress: progress("Asking GitHub for the latest raid events...", done, total), "Download")
    assert view.status.value.startswith("Lecture des événements...")
    assert "Asking GitHub" not in view.status.value


def test_timestamp_formatting_uses_pack_copy_and_preserves_timestamp(desktop_copy):
    import time
    seconds = 1234567890
    assert localization.date_time(seconds) == time.strftime("%Y/%m/%d %H:%M", time.localtime(seconds))
    i18n._strings = {}
    assert localization.date_time(seconds) == time.strftime("%d %b %Y, %H:%M", time.localtime(seconds))

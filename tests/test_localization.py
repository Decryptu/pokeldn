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
    assert localization.summary_lines(summary) == ("Pikachu · level 50 · shiny", "'Eevee' · Hardy · holding Light Ball")
    assert localization.translate("Left its Light Ball behind.") == "Left its Light Ball behind."
    assert localization.error_message(ValueError("unknown button 'Eevee'")) == "unknown button 'Eevee'"
    assert localization.app_log("[done] trade 1 complete") == "[done] trade 1 complete"


def test_translated_document_keeps_original_fragment_ids():
    pytest.importorskip("flet")
    from gui.views.widgets import heading_sections
    original = "# Guide\nStart.\n## Shared heading\nOne.\n## Shared heading\nTwo."
    translated = "# Manuel\nDebut.\n## Section\nUn.\n## Section\nDeux."
    sections = list(heading_sections(translated, reference=original))
    assert [(key, title) for key, title, _ in sections if title] == [
        ("guide", "Manuel"), ("shared-heading", "Section"), ("shared-heading-1", "Section")]


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


def test_a_pack_translates_a_whole_message_then_each_sentence_then_its_game_terms(french_copy):
    i18n._pack.resources["messages"]["Turns off any game boost that is on."] = "Coupe les boosts."
    assert localization.translate("Growlithe") == "Caninos"
    assert localization.translate("It walks behind you. Turns off any game boost that is on.") == (
        "It walks behind you. Coupe les boosts.")
    assert localization.translate("A Squirtle appears") == "A Carapuce appears"
    assert localization.summary_lines("Squirtle · level 50 · shiny · 'Squirtle' · Hardy") == (
        "Carapuce · niveau 50 · shiny", "'Squirtle' · Hardi")


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



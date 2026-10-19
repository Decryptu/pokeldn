"""Resource packs remain data-only and fall back per resource, not per language."""
from pathlib import Path

import pytest

from pokeldn import plugins
from pokeldn.app import i18n, paths, plugin_store


@pytest.fixture
def pack(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    folder = tmp_path / "language"
    folder.mkdir()
    (folder / "plugin.toml").write_text('id = "test-language"\napi = "1.9"\nlocale = "fr"\n'
        'strings = "strings.toml"\nmessages = "messages.toml"\nterms = "terms.toml"\n'
        'help = "help.toml"\ntemplates = "templates.toml"\ndocuments = "docs"\n', encoding="utf-8")
    for name, content in {
        "strings": '"hello" = "Bonjour {name}"',
        "messages": '"Mystery Gift" = "Cadeau Mystere"\n"literal {x}" = "texte {x}"',
        "terms": '"Pikachu" = "PIKACHU"',
        "help": '"one:--mode" = "Mode un"\n"two:--mode" = "Mode deux"',
        "templates": '"Cannot open {path}: {term_reason}" = "Impossible: {path}, {term_reason}"',
    }.items():
        (folder / f"{name}.toml").write_text(content, encoding="utf-8")
    (folder / "docs").mkdir()
    (folder / "docs/guide.md").write_text("# Guide traduit\nTexte localise", encoding="utf-8")
    monkeypatch.setenv("POKELDN_PLUGINS", str(folder))
    plugins._reset()
    i18n.select("test-language")
    yield folder
    plugins._reset()
    i18n.select()


def test_install_resources_and_reset_to_english(pack, tmp_path):
    package = plugin_store.pack(str(pack), str(tmp_path / "language.pokeplugin"))
    assert package.id == "test-language" and not package.findings
    assert i18n.locale() == "fr"
    assert i18n.t("hello", "Hello {name}", name="Red") == "Bonjour Red"
    assert i18n.message("literal {x}") == "texte {x}"
    assert i18n.message("unknown {x}") == "unknown {x}"
    assert i18n.message("Cannot open Pikachu.txt: Mystery Gift") == "Impossible: Pikachu.txt, Cadeau Mystere"
    assert i18n.terms("Pikachu, Pikachus") == "PIKACHU, Pikachus"
    assert i18n.help_text("one", "--mode", "mode") == "Mode un"
    assert i18n.help_text("two", "--mode", "mode") == "Mode deux"
    assert i18n.help_text("three", "--mode", "mode") == "mode"
    assert i18n.document("guide", "english.md") == pack / "docs/guide.md"
    assert i18n.document("missing.md", "english.md") == Path("english.md")
    i18n.select("missing")
    assert i18n.locale() == "en" and i18n.message("Mystery Gift") == "Mystery Gift"
    assert i18n.terms("Pikachu") == "Pikachu"
    assert i18n.help_text("one", "--mode", "mode") == "mode"
    assert i18n.document("guide", "english.md") == Path("english.md")


@pytest.mark.parametrize("source,target", [("Hello {name}", "Hi {other}"),
    ("Hello {name.__class__}", "Hi {name.__class__}"), ("{name!r}", "{name!r}"),
    ("{name:{size}}", "{name:{size}}")])
def test_unsafe_or_incompatible_message_templates_are_refused(source, target):
    import json
    content = f"{json.dumps(source)} = {json.dumps(target)}".encode()
    with pytest.raises(ValueError, match="Language pack"):
        i18n.read_resources({"templates": "templates.toml"}, lambda _: content)


@pytest.mark.parametrize("field,value", [("messages", "../outside.toml"), ("help", "C:outside.toml"),
    ("terms", "x\\outside.toml"), ("documents", "../outside"), ("documents", "/tmp")])
def test_resource_paths_rejected_before_install_and_by_loader(pack, tmp_path, field, value):
    manifest = pack / "plugin.toml"
    import tomllib
    meta = tomllib.loads(manifest.read_text(encoding="utf-8"))
    meta[field] = value
    import json
    manifest.write_text("\n".join(f"{k} = {json.dumps(v)}" for k, v in meta.items()), encoding="utf-8")
    with pytest.raises(plugin_store.PackageError, match="Language pack"):
        plugin_store.pack(str(pack), str(tmp_path / "bad.pokeplugin"))
    plugins._reset()
    i18n.select("test-language")
    assert plugins.discover()[0].error and i18n.locale() == "en"


def test_document_reader_and_search_use_the_same_pack(pack):
    pytest.importorskip("flet")
    from gui.views import docs
    sections = docs.index([], "Guide")
    assert any("localise" in s.text for s in sections)
    assert docs.search(sections, "localise")
    assert docs.document_path("guide") == pack / "docs/guide.md"
    assert i18n.document("../messages.toml", "english.md") == Path("english.md")


def test_symlinked_documents_cannot_escape_pack(pack, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    target = pack / "docs/outside.md"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable")
    assert i18n.document("outside.md", "english.md") == Path("english.md")


def test_display_names_follow_the_selected_pack_over_one_process(pack, monkeypatch):
    from gui.localization import DisplayService
    from pokeldn import pokemon
    asked = []

    def reply(request):
        asked.append(request.get("display_language", "en"))
        return {"names": [{"id": 25, "name": asked[-1]}]}

    monkeypatch.setattr(pokemon.SERVICE, "_ask", reply)
    service = DisplayService()
    assert service.names("sv", "species") == service.names("sv", "species") == [{"id": 25, "name": "fr"}]
    i18n.select()
    assert service.names("sv", "species") == [{"id": 25, "name": "en"}]
    assert asked == ["fr", "en"]

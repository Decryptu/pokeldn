"""Language packs use the installer and loader, with English fallback at the view boundary."""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeldn import plugins
from pokeldn.app import i18n, paths, plugin_store
from scripts.extract_strings import ROOT, TEMPLATE, extract, render

SAMPLE = ROOT / "examples/plugins/pseudo"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setenv("POKELDN_PLUGINS", "")
    plugins._reset()
    i18n.select()
    yield tmp_path
    plugins._reset()
    i18n.select()


def test_template_matches_source():
    assert TEMPLATE.read_text(encoding="utf-8") == render(extract())


def test_conflicting_defaults_are_refused(tmp_path):
    (tmp_path / "gui/views").mkdir(parents=True)
    (tmp_path / "pokeldn/app").mkdir(parents=True)
    (tmp_path / "pokeldn/app/catalog.py").write_text('t("a.b", "First")\nt("a.b", "Second")')
    with pytest.raises(ValueError, match="two English defaults"):
        extract(tmp_path)


def test_signed_pack_install_selection_and_views(isolated, monkeypatch):
    pytest.importorskip("flet")
    from gui.views.bank import BankView
    from gui.views.docs import DocsView
    from gui.views.settings import SettingsView
    from pokeldn.app import settings
    key = plugin_store.signing_key(str(isolated / "signing.pem"), create=True)
    package = plugin_store.pack(str(SAMPLE), str(isolated / "sample.pokeplugin"), key)
    assert package.key
    plugin_store.install(package)
    monkeypatch.setattr(settings, "PATH", paths.DATA / "settings.json")
    chosen = settings.Settings()
    app = SimpleNamespace(settings=chosen)
    SettingsView._language(SimpleNamespace(app=app, save=lambda k, v: (setattr(chosen, k, v), chosen.save())),
                           "pseudo-language")
    assert settings.load().app_language == "pseudo-language"
    assert plugins.reload()[0].loaded
    i18n.select(chosen.app_language)
    assert i18n.t("bank.bank_676c47", "Bank") == "[Bank]"
    assert i18n.t("missing.key", "Hello {name}", name="Blue") == "Hello Blue"
    # Build real views. Their controls hold the pack text and an omitted English default.
    bank_view = BankView(app)
    docs_view = DocsView(app)
    import flet as ft
    from dataclasses import fields

    def texts(control):
        if isinstance(control, ft.Text):
            yield control.value
        for field in fields(control):
            if field.name.startswith("_"):
                continue
            value = getattr(control, field.name)
            if isinstance(value, ft.Control):
                yield from texts(value)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, ft.Control):
                        yield from texts(child)
    assert "[Bank]" in list(texts(bank_view.control))
    assert "Start here" in list(texts(docs_view.control))
    assert i18n.t("docs.start_here_2adc96", "Start here") == "Start here"
    i18n.select("uninstalled-pack")
    assert i18n.t("bank.bank_676c47", "Bank") == "Bank"


@pytest.mark.parametrize("text", ['bad = [', '"bank.title" = 3', '"bank.title" = "Hello {name"',
                                      '"bank.title" = "{name.__class__}"', '"bank.title" = "{name:>999999999}"',
                                      pytest.param("bad = " + "[" * 5000 + "]" * 5000, id="deep")])
def test_bad_pack_refused_by_installer_and_loader(isolated, monkeypatch, text):
    folder = isolated / "bad"
    folder.mkdir()
    (folder / "plugin.toml").write_text((SAMPLE / "plugin.toml").read_text())
    (folder / "strings.toml").write_text(text)
    with pytest.raises(plugin_store.PackageError, match="Language pack"):
        plugin_store.pack(str(folder), str(isolated / "bad.pokeplugin"))
    monkeypatch.setenv("POKELDN_PLUGINS", str(folder))
    found = plugins.reload()[0]
    assert found.error and not found.loaded
    i18n.select(found.id)
    assert i18n.t("bank.title", "Bank") == "Bank"


def test_bad_placeholder_falls_back(isolated, monkeypatch):
    monkeypatch.setattr(i18n, "_strings", {"hello": "Hello {missing}", "extra.unused": "ignored"})
    assert i18n.t("hello", "Welcome {name}", name="Blue") == "Welcome Blue"
    assert i18n.t("other", "English {name}", name="Blue") == "English Blue"


def test_catalog_import_after_pack_selection(isolated):
    code = '''
from pokeldn.app.i18n import select
select("pseudo-language")
from pokeldn import plugins
plugins.load()
from pokeldn.app.catalog import GAMES
assert GAMES[0].tools[0].name == "[Trade (Host)]"
from gui.views.controller import KEYBOARD, STICK_DIRECTIONS
assert KEYBOARD["Arrow Up"] == "UP"
assert STICK_DIRECTIONS[1][0] == "UP"
'''
    # A fresh process checks startup ordering before any module-level labels are built.
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                            env={**os.environ, "POKELDN_DATA": str(isolated / "child"),
                                 "POKELDN_PLUGINS": str(SAMPLE)})
    assert result.returncode == 0, result.stderr


def test_bundled_font_covers_cjk():
    import struct
    font = (ROOT / "gui/assets/fonts/NotoSansCJKsc-Regular.otf").read_bytes()
    tables = struct.unpack_from(">H", font, 4)[0]
    cmap = next(struct.unpack_from(">I", font, at + 8)[0] for at in range(12, 12 + tables * 16, 16)
                if font[at:at + 4] == b"cmap")
    count = struct.unpack_from(">H", font, cmap + 2)[0]
    subtables = [cmap + struct.unpack_from(">I", font, cmap + 4 + n * 8 + 4)[0] for n in range(count)]
    full = next(at for at in subtables if struct.unpack_from(">H", font, at)[0] == 12)
    groups = struct.unpack_from(">I", font, full + 12)[0]
    ranges = [struct.unpack_from(">III", font, full + 16 + n * 12) for n in range(groups)]
    for character in "简体中文繁體日本語ひらがなカタカナ한국어":
        assert any(start <= ord(character) <= end and glyph + ord(character) - start
                   for start, end, glyph in ranges), character


def test_punctuation_font_draws_latin_width_ahead_of_cjk():
    """The CJK font's ’ is a 1000-unit cell: "Reveler’s Road" read as "Reveler’ s Road"."""
    import struct
    from gui import theme
    assert theme.FALLBACK_FONTS.index(theme.PUNCTUATION_FONT) < theme.FALLBACK_FONTS.index(theme.CJK_FONT)
    font = (ROOT / "gui/assets" / theme.FONT_ASSETS[theme.PUNCTUATION_FONT]).read_bytes()
    tables = {font[at:at + 4]: struct.unpack_from(">I", font, at + 8)[0]
              for at in range(12, 12 + struct.unpack_from(">H", font, 4)[0] * 16, 16)}
    cmap, hmtx = tables[b"cmap"], tables[b"hmtx"]
    metrics = struct.unpack_from(">H", font, tables[b"hhea"] + 34)[0]
    per_em = struct.unpack_from(">H", font, tables[b"head"] + 18)[0]
    count = struct.unpack_from(">H", font, cmap + 2)[0]
    at = next(cmap + struct.unpack_from(">I", font, cmap + 4 + n * 8 + 4)[0] for n in range(count)
              if struct.unpack_from(">H", font, cmap + struct.unpack_from(">I", font, cmap + 4 + n * 8 + 4)[0])[0] == 4)
    segments = struct.unpack_from(">H", font, at + 6)[0] // 2
    ends, starts, deltas, offsets = (struct.unpack_from(f">{segments}H", font, base) for base in
                                     (at + 14, at + 16 + segments * 2, at + 16 + segments * 4, at + 16 + segments * 6))
    for character in "‘’“”·":
        code = ord(character)
        n = next(n for n in range(segments) if starts[n] <= code <= ends[n])
        assert offsets[n] == 0, character
        glyph = (code + deltas[n]) & 0xFFFF
        assert glyph, character
        advance = struct.unpack_from(">H", font, hmtx + min(glyph, metrics - 1) * 4)[0]
        assert advance < per_em // 2, (character, advance)


def test_translations_do_not_change_catalog_arguments(isolated):
    code = '''
import json, os
from pokeldn.app import i18n
from scripts.extract_strings import extract
if os.environ["TRANSLATE"] == "yes":
    i18n._strings = {k: "[简体中文 " + v + "]" for k, v in extract().items()}
from pokeldn.app.catalog import GAMES
print(json.dumps([(g.key, [(t.key, t.script, t.fixed,
    [(f.key, f.flag, f.default, [c[0] for c in f.choices], f.when, f.unless, f.requires,
      f.template, f.unset) for f in t.fields]) for t in g.tools]) for g in GAMES]))
'''
    outputs = []
    for mode in ("yes", "no"):
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, "TRANSLATE": mode, "POKELDN_PLUGINS": ""})
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_code_plugin_importing_catalog_during_startup_uses_pack(isolated):
    folder = isolated / "a-code-plugin"
    folder.mkdir()
    (folder / "plugin.toml").write_text('id = "code-plugin"\napi = 1\n')
    (folder / "plugin.py").write_text('from pokeldn.plugins import Tool\ndef register(api):\n    pass\n')
    result = subprocess.run([sys.executable, "-c", '''
from pokeldn.app.i18n import select
select("pseudo-language")
from pokeldn import plugins
plugins.load()
from pokeldn.app.catalog import GAMES
assert GAMES[0].tools[0].name == "[Trade (Host)]"
'''], cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "POKELDN_DATA": str(isolated / "child"),
             "POKELDN_PLUGINS": os.pathsep.join((str(folder), str(SAMPLE)))})
    assert result.returncode == 0, result.stderr


def test_pack_check_reports_against_this_release(tmp_path):
    from scripts.check_language_pack import check
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "plugin.toml").write_text('id = "checked"\napi = "1.9"\nlocale = "fr"\nstrings = "strings.toml"\n'
                                        'help = "help.toml"\n')
    (folder / "strings.toml").write_text('"bank.bank_676c47" = "Banque"\n"gone.key" = "Parti"\n'
                                         '"games.of_ca6c5e" = "{value0} sur {total}"\n')
    (folder / "help.toml").write_text('"frlg-gift:--news" = "Nouvelles"\n"frlg-gift:--gone" = "Parti"\n')
    report = check(folder)
    assert report["unknown strings"] == ["gone.key"] and report["placeholders differ"] == ["games.of_ca6c5e"]
    assert "bank.bank_676c47" not in report["missing strings"] and "docs.no_page_matches" in report["missing strings"]
    assert report["unknown help"] == ["frlg-gift:--gone"]
    assert "frlg-gift:--news" not in report["missing help"] and "frlg-gift:--gift" in report["missing help"]

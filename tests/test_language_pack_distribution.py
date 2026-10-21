"""Language choices and developer tools work with independently installed packs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pokeldn import plugins
from pokeldn.app import i18n, paths, plugin_store, settings
from scripts.build_language_pack import build
from scripts.check_localization import check

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/plugins/language_pack"


def test_language_choices_follow_installed_plugins_and_partial_overrides(tmp_path, monkeypatch):
    from gui.views.settings import SettingsView
    previous = i18n.identity()
    monkeypatch.setattr(paths, "DATA", tmp_path / "app-data")
    monkeypatch.setattr(settings, "PATH", paths.DATA / "settings.json")
    monkeypatch.setenv("POKELDN_PLUGINS", "")
    monkeypatch.setattr(plugins.metadata, "entry_points", lambda **kwargs: [])
    i18n.select()
    try:
        assert SettingsView.language_choices(None) == [("", "English")]
        output = build(EXAMPLE, tmp_path / "french.pokeplugin")
        assert output.with_suffix(".pokeplugin.sha256").read_text().split()[0] == hashlib.sha256(output.read_bytes()).hexdigest()
        package = plugin_store.read(str(output))
        assert not package.findings
        plugin_store.install(package)
        assert SettingsView.language_choices(None) == [("", "English"), ("example-french|fr", "Français")]
        selected = settings.load()
        selected.plugins = [package.id]
        selected.save()
        i18n.select("example-french", "fr", strict=True)
        assert i18n.text("core.common.save") == "Enregistrer"
        assert i18n.text("core.gift.egg.description", species="Player {name}") == "Donne un Œuf contenant Player {name}."
        assert i18n.text("core.plugins.source_count", count=1) == "1 plugin"
        assert i18n.name(i18n.EntityKind.MOVE, 94, game=i18n.Game.SV) == "Psyko"
        i18n.select()
        plugin_store.remove(package.id)
        assert SettingsView.language_choices(None) == [("", "English")]
    finally:
        i18n.select(previous[0], previous[1])


def test_checker_distinguishes_partial_packs_from_complete_translations(tmp_path):
    assert check(language_packs=[EXAMPLE]) == []
    assert any("missing" in error for error in check(language_packs=[EXAMPLE], require_complete=True))
    assert check(language_packs=[tmp_path])


@pytest.mark.parametrize("from_source", [True, False], ids=["source", "package"])
def test_preview_installs_external_language_in_isolated_data(tmp_path, from_source):
    source = EXAMPLE if from_source else build(EXAMPLE, tmp_path / "french.pokeplugin")
    data = tmp_path / "preview"
    environment = dict(os.environ, POKELDN_DATA=str(tmp_path / "normal-data"))
    result = subprocess.run([sys.executable, "scripts/preview_language.py", str(source),
                             "--data", str(data), "--prepare-only"], cwd=ROOT,
                            env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verified installed pack example-french" in result.stdout
    settings = json.loads((data / "settings.json").read_text(encoding="utf-8"))
    assert settings["app_language"] == "example-french" and settings["app_locale"] == "fr"
    assert settings["plugins"] == ["example-french"]
    assert settings["check_updates"] is False and settings["sprites"] is False
    assert (data / "plugins/example-french/plugin.toml").is_file()
    assert not (tmp_path / "normal-data").exists()

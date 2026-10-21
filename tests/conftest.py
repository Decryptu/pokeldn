"""Small synthetic language plugin for self-contained semantic localization tests."""
import json
import os
from pathlib import Path
import tomllib

import pytest


@pytest.fixture(scope="session")
def semantic_pack_source(tmp_path_factory):
    from pokeldn.app import i18n
    external = os.environ.get("POKELDN_TEST_LANGUAGE_PACK")
    if external:
        root = Path(external).resolve()
        assert (root / "plugin.toml").is_file(), root
        return root
    root = tmp_path_factory.mktemp("semantic-language")
    strings = {key: "测试：" + entry if isinstance(entry, str) else
               {branch: value if branch == "plural" else "测试：" + value for branch, value in entry.items()}
               for key, entry in i18n._catalog.items()}
    strings.update(json.loads((Path(__file__).parent / "data/semantic-translations.json").read_text(encoding="utf-8")))
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    (root / "strings.toml").write_text("[strings]\n" + "\n".join(
        f"{quote(key)} = " + (quote(entry) if isinstance(entry, str) else
            "{ " + ", ".join(f"{branch} = {quote(value)}" for branch, value in entry.items()) + " }")
        for key, entry in strings.items()), encoding="utf-8")
    (root / "plugin.toml").write_text('id = "semantic-test-language"\napi = "1.10"\n'
        'localization_format = 1\n[locales.zh-Hans]\nname = "测试语言"\n'
        'strings = "strings.toml"\nentities = "entities.toml"\ndocuments = "documents.toml"\n', encoding="utf-8")
    (root / "entities.toml").write_text('[entities.sv.species_forms."128"]\n'
        '"1" = "肯泰罗（帕底亚的样子·斗战种）"\n', encoding="utf-8")
    (root / "guide.md").write_text('<a id="start-here"></a>\n# 指南\n'
        '<a id="what-you-need"></a>\n## 礼物\n礼物示例。\n', encoding="utf-8")
    (root / "documents.toml").write_text('[documents."core.guide.guide"]\ntitle = "指南"\npath = "guide.md"\n'
        '[[documents."core.guide.guide".sections]]\nid = "start-here"\ntitle = "指南"\nlevel = 1\n'
        '[[documents."core.guide.guide".sections]]\nid = "what-you-need"\ntitle = "礼物"\nlevel = 2\n', encoding="utf-8")
    return root


@pytest.fixture
def semantic_pack(semantic_pack_source, monkeypatch):
    from pokeldn import plugins
    from pokeldn.app import i18n
    root = semantic_pack_source
    meta = tomllib.loads((root / "plugin.toml").read_text(encoding="utf-8"))
    resources = i18n.read_resources(meta, lambda path: (root / path).read_bytes())
    plugin = plugins.Plugin("semantic-test-language", "Test language", folder=root, api=(1, 10),
                            locale="zh-Hans", resources=resources)
    monkeypatch.setattr(plugins, "discover", lambda: [plugin])
    monkeypatch.setattr(plugins, "enabled", lambda: [plugin.id])
    return plugin

"""Deterministic resource writers shared by development commands."""
import json
from pathlib import Path
import shutil
import tomllib

ROOT = Path(__file__).resolve().parents[1]
ENGLISH = ROOT / "pokeldn/app/data/strings.en.toml"
PACK = ROOT / "examples/plugins/zh_hans"
BUILTIN = ROOT / "pokeldn/app/data/language-packs/zh-Hans"


def write_strings(path, values, parameters=None):
    quote = lambda v: json.dumps(v, ensure_ascii=False)
    lines = ["# UTF-8. Stable semantic keys.", "[strings]"]
    for key, value in sorted(values.items()):
        entry = quote(value) if isinstance(value, str) else "{ " + ", ".join(f"{k} = {quote(v)}" for k, v in value.items()) + " }"
        lines.append(f"{quote(key)} = {entry}")
    for key, fields in sorted((parameters or {}).items()):
        lines.append(f"[parameters.{quote(key)}]")
        lines.extend(f"{quote(k)} = {quote(v)}" for k, v in fields.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add(entries):
    en = tomllib.loads(ENGLISH.read_text(encoding="utf-8"))
    zh_path = PACK / "locales/zh-Hans/strings.toml"
    zh = tomllib.loads(zh_path.read_text(encoding="utf-8"))["strings"]
    for key, (source, translated) in entries.items():
        en["strings"][key] = source
        if translated is not None:
            zh[key] = translated
    write_strings(ENGLISH, en["strings"], en.get("parameters"))
    write_strings(zh_path, zh)


def bundle():
    BUILTIN.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PACK / "locales", BUILTIN / "locales", dirs_exist_ok=True)
    source = (PACK / "plugin.toml").read_text(encoding="utf-8").replace('id = "community-zh-hans"', 'id = "builtin-zh-hans"')
    (BUILTIN / "plugin.toml").write_text(source, encoding="utf-8")

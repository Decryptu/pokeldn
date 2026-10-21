"""What a language pack lacks or keeps from older releases, against this checkout [docs/plugins.md, Language packs].

    python scripts/check_language_pack.py PACK_FOLDER

Lists strings and tool help the pack does not translate, keys this release no longer has, and
translations whose placeholders differ from English. Exits 1 when a placeholder differs."""
import string
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def help_keys() -> dict[str, str]:
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.introspect import flags_of
    keys = {}
    for tool in (tool for game in GAMES for tool in game.tools):
        for flag in flags_of(tool.script):
            if flag.help:
                keys[f"{tool.key}:{flag.option}"] = flag.help
    return keys


def check(folder: Path) -> dict[str, list[str]]:
    from pokeldn import plugins
    plugin = plugins._read_folder(folder)
    if plugin.error or not plugin.locale:
        raise SystemExit(f"{folder}: not a language pack: {plugin.error or 'no locale'}")
    english = tomllib.loads((ROOT / "pokeldn/app/data/strings.en.toml").read_text(encoding="utf-8"))
    report = {"missing strings": sorted(english.keys() - plugin.translations.keys()),
              "unknown strings": sorted(plugin.translations.keys() - english.keys()),
              "placeholders differ": sorted(key for key, value in plugin.translations.items()
                                            if key in english and fields(value) != fields(english[key]))}
    flags, translated = help_keys(), plugin.resources.get("help", {})
    report["missing help"] = sorted(flags.keys() - translated.keys())
    report["unknown help"] = sorted(translated.keys() - flags.keys())
    return report


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    result = check(Path(sys.argv[1]).resolve())
    for heading, keys in result.items():
        print(f"{heading}: {len(keys)}")
        for key in keys:
            print(f"  {key}")
    sys.exit(1 if result["placeholders differ"] else 0)

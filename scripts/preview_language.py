"""Install any language plugin in an isolated, offline app preview.

Usage: python scripts/preview_language.py path/to/language.pokeplugin --web 8815
Only the requested preview directory is written. Radio, updates and sprites are
disabled in this developer preview; the production application's behavior is unchanged.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", nargs="?", type=Path, default=ROOT / "examples/plugins/language_pack",
                        help="A .pokeplugin file or language-plugin source folder.")
    parser.add_argument("--locale", help="One of the plugin's locale tags; defaults to its first locale.")
    parser.add_argument("--data", type=Path, default=ROOT / "build/i18n-package-preview")
    parser.add_argument("--web", type=int)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    os.environ["POKELDN_DATA"] = str(args.data.resolve())
    os.environ["POKELDN_PLUGINS"] = ""
    os.environ.pop("POKELDN_RADIO", None)
    if args.web:
        os.environ["POKELDN_GUI_WEB"] = str(args.web)
        os.environ["FLET_FORCE_WEB_SERVER"] = "true"
        os.environ["FLET_SERVER_IP"] = "127.0.0.1"
        os.environ["FLET_SERVER_PORT"] = str(args.web)
    from scripts.build_language_pack import build
    from pokeldn.app import i18n, plugin_store, settings
    output = build(args.package) if args.package.is_dir() else args.package.resolve()
    package = plugin_store.read(str(output))
    plugin_store.install(package)
    installed = plugin_store.installed(package.id)
    if installed is None or not installed.resources.get("locales"):
        raise ValueError("The package must provide at least one language locale.")
    selected = settings.load()
    language = args.locale or next(iter(installed.resources["locales"]))
    selected.app_language, selected.app_locale = package.id, language
    selected.plugins = [package.id]
    selected.check_updates, selected.sprites = False, False
    selected.save()
    i18n.select(package.id, language, strict=True)
    print(f"Verified installed pack {package.id} {package.version}: {output}", flush=True)
    if args.prepare_only:
        return
    from gui import board, main as application
    board.ports = lambda: []
    board.controllers = lambda: 0
    application.run()


if __name__ == "__main__":
    main()

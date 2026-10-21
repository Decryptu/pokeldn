"""Validate and package a data-only language plugin from any source folder."""
import argparse
import hashlib
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_localization import check
from pokeldn.app import plugin_store


def build(source, output=None, *, require_complete=False):
    source = Path(source).resolve()
    errors = check(language_packs=[source], require_complete=require_complete)
    if errors:
        raise ValueError("\n".join(errors))
    meta = tomllib.loads((source / "plugin.toml").read_text(encoding="utf-8"))
    output = output or ROOT / "dist" / f"{meta['id']}-{meta['version']}.pokeplugin"
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    package = plugin_store.pack(str(source), str(output))
    if package.findings:
        raise ValueError("A data-only language pack must not contain executable findings.")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=ROOT / "examples/plugins/language_pack")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    print(build(args.source, args.output, require_complete=args.require_complete))

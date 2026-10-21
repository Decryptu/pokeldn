"""Validate, bundle and package the Simplified Chinese localization resources."""
import argparse
import hashlib
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.localization_resources import PACK, bundle
from scripts.check_localization import check
from pokeldn.app import plugin_store


def build(output=None):
    bundle()
    errors = check()
    if errors:
        raise ValueError("\n".join(errors))
    meta = tomllib.loads((PACK / "plugin.toml").read_text(encoding="utf-8"))
    output = output or ROOT / "dist" / f"{meta['id']}-{meta['version']}.pokeplugin"
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    package = plugin_store.pack(str(PACK), str(output))
    if package.findings:
        raise ValueError("A data-only language pack must not contain executable findings.")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path)
    print(build(parser.parse_args().output))

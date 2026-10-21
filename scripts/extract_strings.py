"""Write the English language-pack template from literal translation calls."""
import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMPLATE = ROOT / "pokeldn/app/data/strings.en.toml"


def extract(root=ROOT):
    catalog = root / "pokeldn/app/data/strings.en.toml"
    if catalog.is_file():
        values = tomllib.loads(catalog.read_text(encoding="utf-8"))
        return values.get("strings", values)
    strings = {}
    paths = [*sorted((root / "gui").glob("*.py")), *sorted((root / "gui/views").glob("*.py")),
             root / "pokeldn/app/catalog.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id not in ("tr", "t"):
                continue
            if len(node.args) < 2 or not all(isinstance(a, ast.Constant) and isinstance(a.value, str)
                                           for a in node.args[:2]):
                raise ValueError(f"{path}:{node.lineno}: translation needs a literal key and English default")
            key, default = (a.value for a in node.args[:2])
            if key in strings and strings[key] != default:
                raise ValueError(f"{key} has two English defaults")
            strings[key] = default
    return dict(sorted(strings.items()))


def render(strings, parameters=None):
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ["# UTF-8. Stable semantic keys.", "[strings]"]
    for key, value in sorted(strings.items()):
        entry = quote(value) if isinstance(value, str) else "{ " + ", ".join(f"{k} = {quote(v)}" for k, v in value.items()) + " }"
        lines.append(f"{quote(key)} = {entry}")
    for key, fields in sorted((parameters or {}).items()):
        lines.append(f"[parameters.{quote(key)}]")
        lines.extend(f"{quote(k)} = {quote(v)}" for k, v in fields.items())
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from scripts.check_localization import check
    errors = check()
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Validated the authoritative English catalog: {len(extract())} keys.")

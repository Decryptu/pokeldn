"""Validate semantic call sites, English contracts, bundled packs and documents."""
import ast
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokeldn.app import i18n


def check(root=ROOT):
    errors = []
    for path in [*root.glob("gui/**/*.py"), *root.glob("pokeldn/**/*.py")]:
        if path.name.startswith("i18n"):
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "pokeldn.app.i18n":
                imports.update({a.asname or a.name: a.name for a in node.names})
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = imports.get(node.func.id) if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "i18n" else None)
            location = f"{path.relative_to(root)}:{node.lineno}"
            if function in ("message", "terms", "t"):
                errors.append(f"{location}: application code cannot use legacy source-text lookup")
            if function not in ("text", "message_ref", "ref"):
                continue
            if len(node.args) != 1:
                errors.append(f"{location}: pass one semantic key and named parameters")
                continue
            key = node.args[0]
            if isinstance(key, ast.Constant):
                if key.value not in i18n._catalog:
                    errors.append(f"{location}: undeclared key {key.value!r}")
                    continue
                if not any(k.arg is None for k in node.keywords):
                    expected = i18n._entry_fields(i18n._catalog[key.value])
                    if expected != {k.arg for k in node.keywords}:
                        errors.append(f"{location}: parameter names differ from {key.value}")
            if function == "text":
                current, in_function = node, False
                while current in parents:
                    current = parents[current]
                    if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                        if isinstance(current, ast.Lambda) or node.lineno >= current.body[0].lineno:
                            in_function = True
                            break
                if not in_function:
                    errors.append(f"{location}: store a ref or entity ID in module/class constants")
    packs = [root / "examples/plugins/zh_hans", root / "pokeldn/app/data/language-packs/zh-Hans"]
    for folder in packs:
        meta = tomllib.loads((folder / "plugin.toml").read_text(encoding="utf-8"))
        try:
            resources = i18n.read_resources(meta, lambda p: (folder / p).read_bytes())
            for locale, spec in resources["locales"].items():
                missing = {k for k in i18n._catalog if k.startswith("core.")} - set(spec["strings"])
                if missing:
                    errors.append(f"{folder}: {locale} missing {len(missing)} declared strings")
        except ValueError as exc:
            errors.append(f"{folder}: {exc}")
    for doc_id, spec in i18n._documents.items():
        try:
            base = i18n._document_roots.get(doc_id, root)
            i18n._validate_document(doc_id, spec, lambda p: (base / p).read_bytes())
        except ValueError as exc:
            errors.append(str(exc))
    return errors


if __name__ == "__main__":
    errors = check()
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Validated {len(i18n._catalog)} English keys, both Chinese packs and {len(i18n._documents)} documents.")

"""Validate semantic call sites, English contracts, bundled packs and documents."""
import ast
import re
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pokeldn.app import i18n


def check_display_sources():
    """Audit the providers that do not appear as literal text() calls in GUI source."""
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.introspect import flags_of
    from pokeldn.app import gift_builder
    from pokeldn.swsh import events
    errors = []
    for game in GAMES:
        for tool in game.tools:
            for flag in flags_of(tool.script):
                if flag.help:
                    key = f"core.help.{tool.key}.{flag.option.lstrip('-')}"
                    source = flag.help.replace("{", "{{").replace("}", "}}")
                    if i18n._catalog.get(key) != source:
                        errors.append(f"{tool.key} {flag.option}: missing or stale English help entry {key}")
                for value in flag.choices:
                    key = f"core.choice.{tool.key}.{flag.option.lstrip('-')}.{value.encode().hex()}"
                    if key not in i18n._catalog:
                        errors.append(f"{tool.key} {flag.option}: undeclared choice label {value!r}")
    def reference(identity, value):
        if value and not isinstance(value, (i18n.TextRef, i18n.DisplayText, i18n.MessageRef)):
            # Numeric speed indicators are literal units, with no language-dependent words.
            if not isinstance(value, str) or not re.fullmatch(r"x\d+", value):
                errors.append(f"{identity}: display metadata must retain a semantic reference")
    for game in ("frlg", "rse", "swsh"):
        module = gift_builder.module(game)
        for code, label in getattr(module, "CARTRIDGES", {}).items():
            reference(f"{game}.cartridge.{code}", label)
        for option in module.KINDS:
            reference(f"{game}.kind.{option[0]}", option[1])
        for option in getattr(module, "STEPS", ()):
            reference(f"{game}.step.{option[0]}", option[1])
        for preset in module.PRESETS:
            for attr in ("label", "group", "summary", "when"):
                reference(f"{game}.{preset.key}.{attr}", getattr(preset, attr, ""))
            for boost in getattr(preset, "members", ()):
                for attr in ("label", "summary"):
                    reference(f"{game}.{boost.key}.{attr}", getattr(boost, attr, ""))
                for option in getattr(boost, "options", ()):
                    for attr in ("label", "help"):
                        reference(f"{game}.{boost.key}.{option.key}.{attr}", getattr(option, attr, ""))
                    for key, label in option.choices:
                        reference(f"{game}.{boost.key}.{option.key}.{key}", label)
    for card in events.load():
        reference(f"swsh.event.{card['key']}.title", card["label"])
    for group in events.GROUPS:
        reference(f"swsh.event.group.{group}", events.GROUP_LABELS.get(group))
        if group not in events.GROUP_LABELS:
            errors.append(f"swsh.event.group.{group}: undeclared group label")
    return errors


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
    if root == ROOT:
        errors.extend(check_display_sources())
    return errors


if __name__ == "__main__":
    errors = check()
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Validated {len(i18n._catalog)} English keys, both Chinese packs and {len(i18n._documents)} documents.")

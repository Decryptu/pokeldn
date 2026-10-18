"""Community language packs and English fallback; docs/plugins.md, Language packs."""
import os
import re
import string
import tomllib
from pathlib import Path, PurePosixPath

_strings: dict[str, str] = {}
_selected = ""
_pack = None
_terms_pattern = None
_message_rules = []


def _basename(value):
    return isinstance(value, str) and value not in ("", ".", "..") and not any(
        char in value for char in ("/", "\\", ":", "\0"))


def _table(name: str, read, *, formatted=False) -> dict[str, str]:
    if not _basename(name):
        raise ValueError("Language pack resources must name a TOML file beside plugin.toml.")
    try:
        values = tomllib.loads(read(name).decode("utf-8"))
    except (OSError, KeyError, UnicodeError, ValueError) as error:
        raise ValueError(f"Language pack {name} does not parse: {error}") from None
    if any(not isinstance(value, str) for value in values.values()):
        raise ValueError("Language pack resources must be quoted keys and text values.")
    if formatted:
        for value in values.values():
            try:
                for _, field, spec, _ in string.Formatter().parse(value):
                    if field is not None and (not field.isidentifier() or '{' in spec):
                        raise ValueError("Use named placeholders without attribute or index access.")
            except ValueError as error:
                raise ValueError(f"Language pack has an invalid format string: {error}") from None
    return values


def read_resources(meta: dict, read) -> dict:
    """Optional API 1.9 resources. Literal text is never interpreted as a format string."""
    result = {kind: _table(meta[kind], read) if kind in meta else {}
              for kind in ("messages", "terms", "help")}
    templates = _table(meta["templates"], read, formatted=True) if "templates" in meta else {}
    for source, target in templates.items():
        fields = _template_fields(source, delimited=True)
        if fields != _template_fields(target) or not fields or len(fields) > 8 or len(source) > 2048:
            raise ValueError("Language pack templates must keep 1 to 8 named fields and fit in 2048 characters.")
    result["templates"] = templates
    if any(not key or len(key) > 200 for key in result["terms"]) or len(result["terms"]) > 10000:
        raise ValueError("Language pack terms need 1 to 200 characters, at most 10000 terms.")
    documents = meta.get("documents", "")
    if not isinstance(documents, str) or (documents and not _basename(documents)):
        raise ValueError("Language pack documents must name a folder beside plugin.toml.")
    result["documents"] = documents
    font = meta.get("font_family", "")
    if not isinstance(font, str) or len(font) > 100:
        raise ValueError("Language pack font_family must be a font name of at most 100 characters.")
    result["font_family"] = font
    return result


def _template_fields(text, *, delimited=False):
    try:
        fields, previous_field = set(), False
        for literal, name, spec, conversion in string.Formatter().parse(text):
            if name is not None:
                if not name.isidentifier() or spec or conversion:
                    raise ValueError("Use plain named fields in message templates.")
                if delimited and previous_field and not literal:
                    raise ValueError("Separate message-template fields with literal text.")
                fields.add(name)
            previous_field = name is not None
        return fields
    except ValueError as error:
        raise ValueError(f"Language pack has an invalid message template: {error}") from None


def _match_template(parts, value):
    """Match literal delimiters without regex backtracking on untrusted pack data."""
    position, values = 0, {}
    for index, (literal, name, _, _) in enumerate(parts):
        if not value.startswith(literal, position):
            return None
        position += len(literal)
        if name is not None:
            following = parts[index + 1][0] if index + 1 < len(parts) else ""
            if not following:
                end = len(value)
            elif index + 1 == len(parts) - 1 and parts[index + 1][1] is None:
                if not value.endswith(following):
                    return None
                end = len(value) - len(following)
            else:
                end = value.find(following, position)
            if end < position:
                return None
            captured = value[position:end]
            if name in values and values[name] != captured:
                return None
            values[name] = captured
            position = end
    return values if position == len(value) else None


def read_pack(meta: dict, read) -> dict[str, str]:
    locale = meta.get("locale")
    if not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", locale):
        raise ValueError("Language pack needs a locale such as zh-Hans.")
    return _table(meta.get("strings"), read, formatted=True)


def select(plugin_id: str = "") -> None:
    """Select an enabled language plugin by id; an absent or broken pack selects English."""
    global _strings, _selected, _pack, _terms_pattern, _message_rules
    from pokeldn import plugins
    _selected = plugin_id
    _strings = {}
    _pack = None
    _terms_pattern = None
    _message_rules = []
    if plugin_id:
        on = plugins.enabled()
        candidate = next((p for p in plugins.discover() if p.id == plugin_id and p.locale and not p.error
                          and (plugins.named(p) or p.id in on)
                          and plugins.compatibility(p.api)[0] in ("ok", "deprecated")), None)
        if candidate is not None:
            _strings = candidate.translations
            _pack = candidate
            _message_rules = [(tuple(string.Formatter().parse(source)), target)
                              for source, target in sorted(candidate.resources.get("templates", {}).items(),
                                                           key=lambda pair: len(pair[0]), reverse=True)]


def locale() -> str:
    """The selected pack's BCP 47 tag, or English after any fallback."""
    return _pack.locale if _pack else "en"


def font_family() -> str | None:
    """A bundled/system font requested by a pack; the normal fallback fonts still apply."""
    return (_pack.resources.get("font_family") or None) if _pack else None


def message(value: str, _depth=0) -> str:
    """Literal legacy/module text, including braces; new app copy should use t with stable keys."""
    if not _pack:
        return value
    table = _pack.resources.get("messages", {})
    if value in table:
        return table[value]
    if len(value) <= 4096 and _depth < 4:
        for parts, target in _message_rules:
            if (matched := _match_template(parts, value)) is not None:
                # Explicitly named term fields may contain game names or nested app messages.
                # All other fields are literal: paths, nicknames, trainer names and diagnostics.
                values = {name: message(terms(part), _depth + 1) if name.startswith("term") else
                          message(part, _depth + 1) if name.startswith("message") else part
                          for name, part in matched.items()}
                return target.format(**values)
    return value


def terms(value: str) -> str:
    """Translate known game terms at a display boundary, never IDs, paths or player input."""
    global _terms_pattern
    table = _pack.resources.get("terms", {}) if _pack else {}
    if not table:
        return value
    if _terms_pattern is None:
        _terms_pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(s) for s in sorted(table, key=len, reverse=True))
                                    + r")(?![\w])")
    return _terms_pattern.sub(lambda match: table[match[0]], value)


def help_text(tool: str, option: str, default: str) -> str:
    """A tool-specific parser description; the same flag in another tool is independent."""
    table = _pack.resources.get("help", {}) if _pack else {}
    return table.get(f"{tool}:{option}", message(" ".join(default.split())))


def document(file: str, default: str | Path) -> Path:
    """Resolve the displayed/searchable Markdown, with per-page fallback and containment checks."""
    relative = PurePosixPath("guide.md" if file == "guide" else file)
    if (_pack and _pack.folder and _pack.resources.get("documents") and not relative.is_absolute()
            and ".." not in relative.parts and "\\" not in file and ":" not in file):
        root = (_pack.folder / _pack.resources["documents"]).resolve()
        candidate = (root / relative).resolve()
        if root.is_relative_to(_pack.folder.resolve()) and candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    return Path(default)


# The English strings name the device the app runs on; on Android it is a phone (examples/android).
_PHONE = re.compile(r"\b(this|your|the) computer\b")


def _device(text: str) -> str:
    return _PHONE.sub(r"\1 phone", text) if os.environ.get("POKELDN_PLATFORM") == "android" else text


def t(key: str, default: str, **fmt) -> str:
    """Look up a string and format named values; malformed translations fall back to English."""
    default = _device(default)
    value = _strings.get(key, default)
    try:
        return value.format(**fmt)
    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
        return default.format(**fmt)

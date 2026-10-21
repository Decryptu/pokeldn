"""Semantic text, entity names and documents. See docs/localization.md."""
import logging
import math
import re
import string
import threading
import tomllib
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from babel import Locale, UnknownLocaleError
from babel.dates import format_datetime, format_date
from babel.numbers import format_decimal, format_percent
from .i18n_types import (DisplayText, DocumentSection, EntityKind, EntityRef, Game, LocalizedDocument,
                         MessageError, MessageRef, NameTable, TextRef)

DATA = Path(__file__).with_name("data")
FORMAT_VERSION = 1
BUILTIN_CHINESE = "builtin-zh-hans"
_log = logging.getLogger(__name__)
_diagnostics, _catalog, _parameter_types = set(), {}, {}
_strings, _selected, _locale, _pack, _resources = {}, "", "en", None, {}
_revision, _listeners = 0, []
_lock, _name_cache, _providers = threading.RLock(), {}, {}
_provider_owners, _document_roots = {}, {}
_builtin = DATA / "language-packs" / "zh-Hans"


def _diagnostic(reason, identity):
    item = (_selected, _locale, _revision, reason, str(identity))
    if item not in _diagnostics:
        _diagnostics.add(item)
        _log.warning("localization pack=%s locale=%s revision=%s reason=%s resource=%s", *item)


def _fields(template):
    if not isinstance(template, str):
        raise ValueError("A message branch must be text.")
    if len(template) > 16384:
        raise ValueError("A message exceeds the 16384 character limit.")
    fields = set()
    for _, name, spec, conversion in string.Formatter().parse(template):
        if name is not None:
            if not name.isidentifier() or conversion not in (None, "s", "r") or "{" in spec:
                raise ValueError("Use named fields without attribute, index or nested format access.")
            if spec and not re.fullmatch(r"[<>=^+\- 0#,.\d%efgEFGdsxXobn]*", spec):
                raise ValueError("Unsupported parameter format.")
            if len(spec) > 12 or any(int(n) > 1000 for n in re.findall(r"\d+", spec)):
                raise ValueError("Parameter format width or precision is too large.")
            fields.add(name)
    return fields


def _entry_fields(entry):
    if isinstance(entry, str):
        return _fields(entry)
    if not isinstance(entry, dict) or not isinstance(entry.get("plural"), str) or "other" not in entry:
        raise ValueError("A plural entry needs a plural parameter and an other branch.")
    if set(entry) - {"plural", "zero", "one", "two", "few", "many", "other"}:
        raise ValueError("Unknown plural branch.")
    fields = [_fields(v) for k, v in entry.items() if k != "plural"]
    if any(f != fields[0] for f in fields) or entry["plural"] not in fields[0]:
        raise ValueError("Plural branches must carry the same fields, including the count.")
    return fields[0]


def _validate_translation(key, translated, english):
    if isinstance(translated, dict) != isinstance(english, dict) or _entry_fields(translated) != _entry_fields(english):
        raise ValueError(f"Template parameters or structure differ from English: {key}")
    if isinstance(english, dict) and translated["plural"] != english["plural"]:
        raise ValueError(f"Plural parameter differs from English: {key}")


def _validate_typed_formats(key, entry, fields):
    branches = [entry] if isinstance(entry, str) else [v for k, v in entry.items() if k != "plural"]
    for branch in branches:
        for _, name, spec, conversion in string.Formatter().parse(branch):
            if fields.get(name) in {"number", "percent", "date", "datetime"} and (spec or conversion):
                raise ValueError(f"Typed parameters use locale formatting without a format specifier: {key}")


def register_catalog(namespace, entries, *, parameters=None):
    """Register a namespace's English catalog; plugins own their namespace."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", namespace) or any(not k.startswith(namespace + ".") for k in entries):
        raise ValueError("Catalog keys must belong to their registered namespace.")
    if any(k in _catalog for k in entries):
        raise ValueError("A localization key already has an owner.")
    if any(k.startswith(namespace + ".") for k in _catalog):
        raise ValueError("A localization namespace already has an owner.")
    for key, entry in entries.items():
        _entry_fields(entry)
        if key in _strings:
            _validate_translation(key, _strings[key], entry)
    for key, fields in (parameters or {}).items():
        if key not in entries or set(fields) != _entry_fields(entries[key]):
            raise ValueError(f"Parameter declaration does not match {key}.")
        if set(fields.values()) - {"text", "literal", "number", "percent", "date", "datetime"}:
            raise ValueError(f"Unknown parameter type in {key}.")
        _validate_typed_formats(key, entries[key], fields)
        if key in _strings:
            _validate_typed_formats(key, _strings[key], fields)
    _catalog.update(entries)
    _parameter_types.update(parameters or {})


def unregister_namespace(namespace):
    if namespace == "core":
        raise ValueError("The core namespace cannot be unregistered.")
    for key in [k for k in _catalog if k.startswith(namespace + ".")]:
        _catalog.pop(key)
        _parameter_types.pop(key, None)
    for key in [k for k in _documents if k.startswith(namespace + ".")]:
        _documents.pop(key)
        _document_roots.pop(key, None)
    for game in [g for g, owner in _provider_owners.items() if owner == namespace]:
        _providers.pop(game, None)
        _provider_owners.pop(game, None)
    _name_cache.clear()


def register_documents(namespace, documents, root):
    root = Path(root).resolve()
    def read(path):
        path = (root / _safe_path(path)).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Document path leaves its plugin.")
        return path.read_bytes()
    for key, spec in documents.items():
        if not key.startswith(namespace + ".") or key in _documents:
            raise ValueError("A document must have a unique ID in its owner's namespace.")
        _validate_document(key, spec, read)
    _documents.update(documents)
    _document_roots.update({key: root for key in documents})


def _safe_path(value):
    if not isinstance(value, str) or not value or any(c in value for c in ("\\", ":", "\0")):
        raise ValueError("Resource paths must be relative POSIX paths inside the plugin.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Resource paths must remain inside the plugin.")
    return value


def _resource_id(value, maximum=2147483647):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or len(value) > 10 or (len(value) > 1 and value.startswith("0")) or int(value) > maximum):
        raise ValueError("Entity IDs must be canonical nonnegative decimal integers in range.")
    return int(value)


def _validate_document(doc_id, spec, read):
    if not isinstance(spec, dict) or not isinstance(spec.get("title"), str) or not spec["title"]:
        raise ValueError(f"Invalid document metadata: {doc_id}")
    try:
        body = read(_safe_path(spec.get("path"))).decode("utf-8")
    except (OSError, KeyError, UnicodeError) as exc:
        raise ValueError(f"Cannot read document {doc_id}: {exc}") from None
    anchors = re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)["\']\s*>\s*</a>', body)
    if len(anchors) != len(set(anchors)):
        raise ValueError(f"Duplicate document anchor: {doc_id}")
    ids = []
    if not isinstance(spec.get("sections", []), list):
        raise ValueError(f"Document sections must be an array: {doc_id}")
    if not isinstance(spec.get("parent", ""), str) or type(spec.get("order", 99)) is not int:
        raise ValueError(f"Invalid document navigation metadata: {doc_id}")
    for section in spec.get("sections", []):
        if not isinstance(section, dict) or set(section) != {"id", "title", "level"} or not isinstance(section["title"], str):
            raise ValueError(f"Invalid section metadata: {doc_id}")
        if type(section["level"]) is not int or not 1 <= section["level"] <= 6:
            raise ValueError(f"Invalid section level: {doc_id}")
        if section["id"] not in anchors or section["id"] in ids:
            raise ValueError(f"Missing or duplicate section anchor: {doc_id}#{section['id']}")
        ids.append(section["id"])
    headings = re.findall(r"(?m)^#{1,6}\s+.+$", re.sub(r"(?ms)^```.*?^```[^\n]*", "", body))
    if len(ids) != len(headings):
        raise ValueError(f"Document headings and metadata differ: {doc_id}")


def read_resources(meta, read):
    """Validate package bytes both before installation and on load."""
    if "localization_format" not in meta:
        from . import i18n_legacy
        return i18n_legacy.read_resources(meta, read)
    if type(meta["localization_format"]) is not int or meta["localization_format"] != FORMAT_VERSION:
        raise ValueError(f"Unsupported localization resource format: {meta['localization_format']!r}")
    locales = meta.get("locales")
    if not isinstance(locales, dict) or not locales:
        raise ValueError("A language pack needs a locales table.")
    result = {"format": FORMAT_VERSION, "locales": {}}
    def table(path):
        try:
            return tomllib.loads(read(_safe_path(path)).decode("utf-8"))
        except (OSError, KeyError, UnicodeError, ValueError) as exc:
            raise ValueError(f"Language pack resource {path}: {exc}") from None
    for tag, spec in locales.items():
        if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", tag) or not isinstance(spec, dict):
            raise ValueError("Invalid locale declaration.")
        if not isinstance(spec.get("name"), str) or not spec["name"]:
            raise ValueError("Every locale needs a display name.")
        strings = table(spec.get("strings")).get("strings", {})
        if not isinstance(strings, dict):
            raise ValueError("strings.toml needs a strings table.")
        namespaces = {k.split(".", 1)[0] for k in _catalog}
        for key, entry in strings.items():
            _entry_fields(entry)
            if key in _catalog:
                _validate_translation(key, entry, _catalog[key])
                _validate_typed_formats(key, entry, _parameter_types.get(key, {}))
            elif key.split(".", 1)[0] in namespaces:
                raise ValueError(f"Unknown catalog key: {key}")
        entities = table(spec["entities"]).get("entities", {}) if spec.get("entities") else {}
        if not isinstance(entities, dict):
            raise ValueError("entities.toml needs an entities table.")
        for game, kinds in entities.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", game) or not isinstance(kinds, dict):
                raise ValueError("Invalid entity game declaration.")
            for kind, entries in kinds.items():
                if kind not in {str(k) for k in EntityKind} | {"species_forms"}:
                    raise ValueError(f"Unknown entity kind: {kind}")
                if not isinstance(entries, dict):
                    raise ValueError("An entity category must be an ID-to-name table.")
                for number, value in entries.items():
                    _resource_id(number)
                    if kind == "species_forms":
                        if not isinstance(value, dict) or any(not isinstance(v, str) or not v for v in value.values()):
                            raise ValueError("Invalid species form override.")
                        for form in value:
                            _resource_id(form, 255)
                    elif not isinstance(value, str) or not value:
                        raise ValueError("Entity names must be nonempty text.")
        documents = table(spec["documents"]).get("documents", {}) if spec.get("documents") else {}
        if not isinstance(documents, dict):
            raise ValueError("documents.toml needs a documents table.")
        for doc_id, document in documents.items():
            if doc_id.startswith("core.") and doc_id not in _documents:
                raise ValueError(f"Unknown core document: {doc_id}")
            _validate_document(doc_id, document, read)
        font, fonts = spec.get("font_family", ""), spec.get("fonts", {})
        if not isinstance(font, str) or not isinstance(fonts, dict):
            raise ValueError("Invalid font declaration.")
        for family, path in fonts.items():
            try:
                if not isinstance(family, str) or not read(_safe_path(path)):
                    raise ValueError("Empty font file.")
            except (OSError, KeyError) as exc:
                raise ValueError(f"Cannot read font {path}: {exc}") from None
        result["locales"][tag] = {"name": spec["name"], "strings": strings, "entities": entities,
                "documents": documents, "font_family": font, "fonts": fonts}
    return result


def read_pack(meta, read):
    if "localization_format" in meta:
        return next(iter(read_resources(meta, read)["locales"].values()))["strings"]
    from . import i18n_legacy
    return i18n_legacy.read_pack(meta, read)


def locale():
    return _pack.locale if _pack and not _pack.resources.get("format") else _locale


def revision():
    return _revision


def identity():
    return (_selected, locale(), _revision)


def subscribe(callback):
    _listeners.append(callback)
    return lambda: _listeners.remove(callback) if callback in _listeners else None


def select(plugin_id="", language=None, *, strict=False):
    """Load completely before committing. Strict failures preserve the active selection."""
    global _strings, _selected, _locale, _pack, _resources, _revision
    resources, pack, selected_locale = {}, None, "en"
    try:
        if plugin_id == BUILTIN_CHINESE:
            from types import SimpleNamespace
            meta = tomllib.loads((_builtin / "plugin.toml").read_text(encoding="utf-8"))
            loaded = read_resources(meta, lambda p: (_builtin / _safe_path(p)).read_bytes())
            pack = SimpleNamespace(folder=_builtin, id=plugin_id, resources=loaded)
        elif plugin_id:
            from pokeldn import plugins
            pack = next((p for p in plugins.discover() if p.id == plugin_id and p.locale and not p.error
                        and (plugins.named(p) or p.id in plugins.enabled())
                        and plugins.compatibility(p.api)[0] in ("ok", "deprecated")), None)
            if pack is None:
                raise ValueError(f"Language pack is unavailable: {plugin_id}")
        if pack and pack.resources.get("format") == FORMAT_VERSION:
            selected_locale = language or next(iter(pack.resources["locales"]))
            resources = pack.resources["locales"][selected_locale]
            strings = resources["strings"]
        elif pack:
            selected_locale, strings = pack.locale, {"core." + k: v for k, v in pack.translations.items()}
            resources = pack.resources
        else:
            strings = {}
    except (ValueError, OSError, KeyError) as exc:
        if strict:
            raise ValueError(f"Cannot load language pack {plugin_id}: {exc}") from None
        _diagnostic("pack-unavailable", plugin_id)
        plugin_id, resources, pack, selected_locale, strings = "", {}, None, "en", {}
    with _lock:
        _selected, _locale, _strings, _pack, _resources = plugin_id, selected_locale, strings, pack, resources
        _revision += 1
        _name_cache.clear()
        _diagnostics.clear()
    # API 1 resource handling stays isolated from semantic application lookups.
    from . import i18n_legacy
    i18n_legacy.select(plugin_id if pack and not resources.get("strings") and not pack.resources.get("format") else "")
    for listener in tuple(_listeners):
        try:
            listener(_revision)
        except Exception:
            _log.exception("Language change listener failed")


def font_family():
    return _resources.get("font_family") or None


def font_assets():
    return {family: str((_pack.folder / path).resolve()) for family, path in _resources.get("fonts", {}).items()} if _pack else {}


def _babel_locale(language):
    try:
        return Locale.parse(language.replace("-", "_"))
    except (ValueError, LookupError, UnknownLocaleError):
        return Locale.parse("en")


def text(key, **params):
    english = _catalog.get(key)
    if english is None:
        _diagnostic("undeclared-key", key)
        return f"⟦{key}⟧"
    entry, language = _strings.get(key, english), locale() if key in _strings else "en"
    if _pack and not _pack.resources.get("format"):
        from . import i18n_legacy
        entry = _strings.get(key, _strings.get(key.removeprefix("core."), english))
        if isinstance(entry, str):
            entry = i18n_legacy.display(entry, _pack)
    if language == "en" and _locale != "en" and key not in _strings:
        _diagnostic("missing-text", key)
    try:
        if set(params) != _entry_fields(english):
            raise ValueError("Call parameters differ from the catalog.")
        current = _babel_locale(language)
        if isinstance(entry, dict):
            count = params[entry["plural"]]
            if isinstance(count, bool) or not isinstance(count, (int, float)):
                raise TypeError("Plural count must be numeric.")
            if isinstance(count, float) and not math.isfinite(count):
                raise ValueError("Plural count must be finite.")
            entry = entry.get(str(current.plural_form(count)), entry["other"])
        converted = {}
        for field, value in params.items():
            kind = _parameter_types.get(key, {}).get(field, "text")
            if isinstance(value, (DisplayText, MessageRef, EntityRef, TextRef)):
                value = render(value)
            if kind in ("number", "percent"):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError("Expected a numeric parameter.")
                value = (format_percent if kind == "percent" else format_decimal)(value, locale=current)
            elif kind in ("date", "datetime"):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = datetime.fromtimestamp(value)
                if not isinstance(value, (date, datetime)):
                    raise TypeError("Expected a date parameter.")
                value = (format_datetime if kind == "datetime" else format_date)(value, locale=current)
            converted[field] = value
        return DisplayText(entry.format(**converted), MessageRef(key, params))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, OSError):
        _diagnostic("invalid-parameters", key)
        return f"⟦{key}: parameters⟧"


def ref(key):
    entry = _catalog.get(key)
    if not isinstance(entry, str) or _entry_fields(entry):
        raise ValueError(f"A static reference needs a parameterless English entry: {key}")
    return TextRef(key, entry)


def message_ref(key, **params):
    """A structured message with canonical English for CLI and persisted diagnostics."""
    entry = _catalog.get(key)
    if not isinstance(entry, str) or set(params) != _entry_fields(entry):
        raise ValueError(f"Invalid structured message: {key}")
    return DisplayText(entry.format(**params), MessageRef(key, params))


def render(value):
    if value is None:
        return ""
    if isinstance(value, DisplayText):
        reference = value.reference
        if isinstance(reference, tuple):
            if reference[0] == "split":
                _, original, separator, index, limit = reference
                values = str(render(original)).split(separator, limit)
                return DisplayText(values[index] if index < len(values) else "", reference)
            if reference[0] == "literal":
                return value
            if reference[0] == "entity":
                entity = reference[1]
                return name(entity.kind, entity.id, game=entity.game, form=entity.form if reference[2] else None)
            if reference[0] == "concat":
                return DisplayText(str(render(reference[1])) + str(render(reference[2])), reference)
            return DisplayText(str(render(reference[1])).join(str(render(p)) for p in reference[2]), reference)
        return render(reference)
    if isinstance(value, TextRef):
        return text(value.key)
    if isinstance(value, MessageRef):
        return text(value.key, **value.params)
    if isinstance(value, EntityRef):
        return name(value)
    if isinstance(value, dict) and "$message" in value:
        return render(MessageRef.from_wire(value))
    if isinstance(value, str) and _pack and not _pack.resources.get("format"):
        from . import i18n_legacy
        return i18n_legacy.display(value, _pack)
    return str(value)


def join(values, separator=None):
    values = tuple(values)
    separator = text("core.presentation.list_separator") if separator is None else separator
    return DisplayText(str(render(separator)).join(str(render(v)) for v in values), ("join", separator, values))


def error_ref(error):
    if hasattr(error, "message"):
        return error.message
    if isinstance(error, Exception) and error.args and isinstance(error.args[0], (DisplayText, MessageRef, TextRef)):
        return error.args[0]
    return str(error)


def register_name_provider(game, provider, *, owner=None):
    if game in _providers:
        raise ValueError(f"A name provider is already registered for {game}.")
    _providers[str(game)] = provider
    if owner:
        _provider_owners[str(game)] = owner
    _name_cache.clear()


def _pkhex_names(game, kind, language):
    from pokeldn import pokemon
    try:
        reply = pokemon.SERVICE._ask({"cmd": "name_table", "game": str(game), "kind": str(kind), "display_language": language})
    except pokemon.BuilderError:
        if game != "frlg" or kind != EntityKind.SPECIES:
            raise
        from pokeldn.frlg.gift import builder
        return {"version": "frlg-offline", "language": "en", "names": {
            builder.national_species(number): label for number, label in builder.species_names()}}
    if kind == EntityKind.SPECIES:
        for species, forms in reply.get("form_labels", {}).items():
            base = reply["names"].get(species)
            if not base:
                continue
            for form, label in forms.items():
                if int(form) and label:
                    if language != "en" and reply.get("language") != "en":
                        value = text("core.entity.species_form", species=base, form=label)
                    else:
                        value = _catalog["core.entity.species_form"].format(species=base, form=label)
                    reply["forms"][species][form] = value
    return reply


def names(kind, *, game):
    kind, game, token = EntityKind(kind), str(game), identity()
    from pokeldn import pokemon
    version = getattr(pokemon.SERVICE, "name_data_version", "unknown")
    lookup = (version, token, game, kind)
    if lookup in _name_cache:
        return _name_cache[lookup][1]
    provider = _providers.get(game, lambda k, lang: _pkhex_names(game, k, lang))
    overrides = _resources.get("entities", {}).get(game, {})
    english, localized = {}, {}
    for language, target in (("en", english), (token[1], localized)):
        if language == "en" and target is localized:
            target.update(english)
            continue
        try:
            target.update(provider(kind, language))
        except Exception:
            _diagnostic("name-service-unavailable", (game, kind, language))
    def ids(source):
        values = source.get("names", {})
        if not isinstance(values, dict):
            _diagnostic("invalid-name-table", (game, kind))
            return {}
        return {int(k): v for k, v in values.items() if str(k).isascii() and str(k).isdecimal()
                and len(str(k)) <= 10 and isinstance(v, str) and v.strip()}
    def forms(source):
        values = source.get("forms", {})
        if not isinstance(values, dict):
            _diagnostic("invalid-form-table", (game, kind))
            return {}
        return {(int(s), int(f)): label for s, entries in values.items() if str(s).isdecimal()
                and len(str(s)) <= 10 and isinstance(entries, dict) for f, label in entries.items()
                if str(f).isdecimal() and len(str(f)) <= 3 and int(f) <= 255 and isinstance(label, str) and label.strip()}
    by_id, by_form = {**ids(english), **ids(localized)}, {**forms(english), **forms(localized)}
    by_id.update({int(k): v for k, v in overrides.get(str(kind), {}).items()})
    if _pack and not _pack.resources.get("format"):
        from . import i18n_legacy
        by_id = {number: i18n_legacy.display(label, _pack) for number, label in by_id.items()}
    if kind == EntityKind.SPECIES:
        by_form.update({(int(k), 0): v for k, v in overrides.get("species", {}).items()})
        by_form.update(forms({"forms": overrides.get("species_forms", {})}))
    table = NameTable(by_id, by_form)
    if identity() != token:
        return names(kind, game=game)
    version = getattr(pokemon.SERVICE, "name_data_version", version)
    _name_cache[(version, token, game, kind)] = (version, table)
    return table


def name(kind, id=None, *, game=None, form=None):
    if isinstance(kind, EntityRef):
        game, kind, id, form = kind.game, kind.kind, kind.id, kind.form
    entity = EntityRef(str(game), EntityKind(kind), id, 0 if form is None else form)
    table = names(entity.kind, game=entity.game)
    found = table.by_form.get((id, form)) if form is not None and entity.kind == EntityKind.SPECIES else table.by_id.get(id)
    if not found and entity.kind == EntityKind.SPECIES and form == 0:
        found = table.by_id.get(id)
    if found:
        return DisplayText(found, ("entity", entity, form is not None))
    _diagnostic("unresolved-entity", entity)
    placeholder = f"{entity.kind} #{id}" + (f" form #{form}" if form is not None and entity.kind == EntityKind.SPECIES else "")
    return DisplayText(placeholder, ("entity", entity, form is not None))


def document(doc_id, default=None):
    if default is not None:
        if _pack and not _pack.resources.get("format"):
            from . import i18n_legacy
            return i18n_legacy.document(doc_id, default, _pack)
        key = "core.guide." + Path(doc_id).stem
        return document(key).path if key in _resources.get("documents", {}) else Path(default)
    english = _documents.get(doc_id)
    if english is None:
        raise KeyError(f"Undeclared document: {doc_id}")
    if _pack and not _pack.resources.get("format"):
        from . import i18n_legacy
        default = _document_roots.get(doc_id, Path(__file__).resolve().parents[2]) / english["path"]
        file = "guide" if doc_id == "core.guide.guide" else Path(english["path"]).name
        path = i18n_legacy.document(file, default)
        return LocalizedDocument(doc_id, _locale if path != default else "en", english["title"], path,
                tuple(DocumentSection(**s) for s in english.get("sections", [])), english.get("parent", ""), english.get("order", 99))
    localized = _resources.get("documents", {}).get(doc_id)
    spec = localized or english
    base = _pack.folder if localized else _document_roots.get(doc_id, Path(__file__).resolve().parents[2])
    path = (base / _safe_path(spec["path"])).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError(f"Document path is unavailable or outside its package: {doc_id}")
    return LocalizedDocument(doc_id, _locale if localized else "en", spec["title"], path,
            tuple(DocumentSection(**s) for s in spec.get("sections", [])), english.get("parent", ""), english.get("order", 99))


def documents():
    return tuple(document(key) for key in _documents)


def t(key, default, **fmt):
    """API 1 compatibility. Application code uses text(key, **params)."""
    value = _strings.get(key, _strings.get("core." + key, default))
    if isinstance(value, str):
        try:
            return value.format(**fmt)
        except (ValueError, KeyError, TypeError, IndexError):
            pass
    return default.format(**fmt)


def message(value, _depth=0):
    if _pack and not _pack.resources.get("format") and isinstance(value, str) and not isinstance(value, (TextRef, DisplayText)):
        from . import i18n_legacy
        return i18n_legacy.message(value, _depth)
    return render(value)


def terms(value):
    if _pack and not _pack.resources.get("format") and isinstance(value, str) and not isinstance(value, (TextRef, DisplayText)):
        from . import i18n_legacy
        return i18n_legacy.terms(value)
    return render(value)


def help_text(tool, option, default):
    if _pack and not _pack.resources.get("format"):
        from . import i18n_legacy
        return i18n_legacy.help_text(tool, option, default)
    key = f"core.help.{tool}.{option.lstrip('-')}"
    return text(key) if key in _catalog else render(default)


def choice_text(tool, option, value):
    """CLI choice identities remain invariant; their labels have an explicit catalog contract."""
    key = f"core.choice.{tool}.{option.lstrip('-')}.{str(value).encode().hex()}"
    if _pack and not _pack.resources.get("format"):
        return render(str(value))
    return text(key) if key in _catalog else str(value)


_english = tomllib.loads((DATA / "strings.en.toml").read_text(encoding="utf-8"))
register_catalog("core", _english.get("strings", {"core." + k: v for k, v in _english.items()}),
                 parameters=_english.get("parameters", {}))
_documents_path = DATA / "documents.en.toml"
_documents = tomllib.loads(_documents_path.read_text(encoding="utf-8")).get("documents", {}) if _documents_path.exists() else {}

# Private API 1 test/extension compatibility, never used by semantic application copy.
from .i18n_legacy import _match_template

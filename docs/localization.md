---
title: Localization API and resource format
parent: Plugins
nav_order: 10
---
<a id="localization"></a>
# Localization API and resource format

<a id="interfaces"></a>
## Interfaces

Import `pokeldn.app.i18n`. English is the complete catalog; every display language uses
the same interfaces. UI code passes stable semantic keys and named parameters:

```python
i18n.text("core.common.save")
i18n.text("core.gift.egg.description", species=species_name)
i18n.name(EntityKind.MOVE, 94, game=Game.SV)
i18n.name(EntityKind.SPECIES, 128, game=Game.SV, form=1)
i18n.names(EntityKind.MOVE, game=Game.SV).by_id[94]
i18n.document("core.guide.gifts")
```

`NameTable.by_id` is an immutable sparse mapping. Species tables also expose
`by_form[(species_id, form_id)]`. `name(..., form=...)` returns a complete display name;
omitting `form` requests the base species name. A name does not establish availability.
Business services filter allowed IDs; controls store those IDs and resolve labels at display time.

Store `ref("core.some.label")`, `MessageRef(key, params)` or entity identities in module
catalogs. `TextRef` retains a canonical English string payload for public catalog and CLI
compatibility; UI display resolves its semantic key. Do not derive translations from that payload.
Runtime controls retain bindings when rendered strings cross the Flet transport.

<a id="identity"></a>
## Entity identity

`EntityRef(game, kind, id, form=0)` supports species, move, item, ability, type, nature and
ball enums. Game constants are string identifiers; plugins may register additional games.
Species IDs are National Dex numbers. Form IDs use the selected game's context. Moves,
abilities, types, natures and balls use PKHeX's respective IDs. Items use its game-context
item IDs. A ball ID and an item ID are different identities.

FRLG application gift state has `entity_schema = 1` and stores national species IDs.
`entity_state()` upgrades native state; `cartridge_state()` copies it into cartridge IDs
at the compilation boundary. Gen 3 item IDs remain game-context IDs. Nature zero is valid;
use `None` for an unset selection.

NPC choices save a stable trainer key. Their species, form, ability, moves and Tera type
come from the same native partner table as the generated record. The CLI adapter emits
the invariant trainer token required by the launcher.

<a id="messages"></a>
## Messages and formatting

```toml
[strings]
"core.gift.egg.description" = "Gives an Egg containing {species}."

[strings."core.queue.count"]
plural = "count"
one = "{count} Pokémon queued."
other = "{count} Pokémon queued."
```

The English entry declares named parameters. Translation branches must preserve the
parameter set and plural selector. Each locale may supply its own CLDR plural categories;
`other` is required. Babel selects the branch using the language of the resolved resource,
including English fallback. Plain fields cannot access attributes, indices or expressions.
Double braces are literal. Numeric format width and precision are bounded.

An English catalog may declare `[parameters."key"]` with parameter names and types:
`text`, `literal`, `number`, `percent`, `date` and `datetime`. Typed numbers and dates use
locale formatting. Do not combine typed numeric formatting with a Python numeric format
specifier. Keep names, nicknames, paths, URLs, codes and identifiers literal. Parameters
are substituted once; braces inside a parameter are not reparsed.

`MessageRef` serializes with `to_wire()` and `from_wire()`. Parameters may contain scalars,
entity references and nested messages. `message_ref()` retains canonical diagnostic text
for CLI consumers while preserving a semantic reference for display. Application errors
cross the PKHeX JSON boundary with a message key and parameters. PKHeX's own legality
reports and operating-system diagnostics remain provider text.

<a id="packages"></a>
## Packages and plugin namespaces

Resource format version 1 requires plugin API 1.10:

```toml
id = "community-zh-hans"
name = "简体中文"
version = "2.0.0"
api = "1.10"
localization_format = 1

[locales.zh-Hans]
name = "简体中文"
strings = "locales/zh-Hans/strings.toml"
entities = "locales/zh-Hans/entities.toml"
documents = "locales/zh-Hans/documents.toml"
font_family = "Noto Sans CJK SC"
```

Each pack may contain multiple locales. Selection saves both plugin ID and locale.
One selected pack supplies overrides; packs are not implicitly stacked. Every resource
path stays inside its package, including symlinks. Invalid format versions, duplicate TOML
keys, unknown core keys, mismatched fields and invalid entity kinds are rejected before install.

Functional plugins call `api.register_localization(english, parameters=...)` for their own
plugin-ID namespace. They may call `api.register_documents(documents)` and register a name
provider for a game they own with `api.register_names(game, provider)`. Providers return
`version`, an ID-to-label `names` mapping, and nested species-to-form `forms` mappings.
Disabled plugins' catalogs are unregistered. Translation namespaces without an installed
functional owner remain inactive and are validated when that owner registers.

See `examples/plugins/hello_localized`. API 1 language-pack adapters remain isolated in
`i18n_legacy`; application code uses semantic APIs.

<a id="fallback"></a>
## Fallback and diagnostics

Names resolve in this order: selected-pack override, PKHeX requested language, PKHeX
English, then `kind #id` with the form when applicable. Unknown text keys and invalid call
parameters display diagnostic placeholders. Missing translations use the complete English
entry. Diagnostics include pack, language, revision and key/reference, and are deduplicated.
They do not log user parameter values by default.

Raw name caches include provider data version, pack identity, locale, resource revision,
game and kind. Language changes clear derived caches. A name request crossing a language
change is retried as a read-only lookup before publishing labels.

<a id="documents"></a>
## Documents and live switching

Document IDs and parent IDs are stable. Metadata declares title, relative path and sections
with `id`, `title` and `level`. Each Markdown heading has an explicit HTML anchor. The
reader, table of contents and search resolve the same document. A missing translation uses
its English body, title and section metadata together.

Language switching validates resources before committing, relabels mounted controls and
cached views, refreshes document search, changes Flet locale/fonts, and preserves selected
IDs, editable text, focus and running sessions. Failed switches preserve the active language.
Trainer language and record text are independent from display language.

<a id="validation"></a>
## Build and verification

```bash
python scripts/check_localization.py
python scripts/build_language_pack.py
python scripts/preview_language.py --prepare-only
python scripts/preview_language.py --web 8815
python -m pytest tests/test_semantic_i18n.py
```

The Chinese pack ships under `pokeldn/app/data/language-packs/zh-Hans`, and Settings always
offers it. `build_language_pack.py` also creates an installable `.pokeplugin` and SHA-256 file.
The preview installs that package into a separate data directory and disables radio access,
updates and sprite downloads. It does not modify the user's normal app settings.

The checker rejects source-text lookups in application code, undeclared literal keys,
incorrect named arguments and translations evaluated in module constants. English is
authoritative; `extract_strings.py --check` validates it without overwriting it from call sites.
It also checks dynamic display sources: CLI help and choice labels, gift metadata,
cartridge labels, and bundled event titles and groups. CLI tokens, entity IDs and card
records retain their original values; localized labels are presentation metadata.

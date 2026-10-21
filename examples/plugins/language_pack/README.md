# Minimal language-pack example

This data-only plugin demonstrates resource format 1: a locale, semantic text,
a named parameter, and an entity-name override. Missing entries use English.
It is an API example, not a complete French translation.

From the repository root:

```bash
python scripts/build_language_pack.py examples/plugins/language_pack
python scripts/preview_language.py dist/example-french-0.1.0.pokeplugin --web 8815
```

Install the package on the Plugins page and select Français in Settings → App language.
Complete translations are distributed and maintained independently as language plugins.

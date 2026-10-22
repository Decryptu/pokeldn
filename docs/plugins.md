---
title: Plugins
---
# Plugins

A plugin adds tools, games, radios and battle servers to pokeldn, and can join or host an LDN network
of its own. It is a folder of Python files with a `plugin.toml`, shipped as one `.pokeplugin` file.
Third-party plugins are not distributed, reviewed or supported by pokeldn.

Code: `pokeldn/plugins.py` (loader and API), `pokeldn/app/plugin_store.py` (packages),
`pokeldn/ldn/radios.py` (radio lookup), `gui/views/plugins.py` (the page). Examples:
`examples/plugins/hello` (one tool) and `examples/plugins/test_kit` (every part of the API).

## Installing a plugin

On **Plugins** (bottom of the side menu), press **Install** under **Browse**, or drop a `.pokeplugin`
on **Installed** or press **Add a plugin**; then accept the risk screen. Its tools appear on the Games
page marked "Plugin: ...". A card per plugin turns it on and off, updates it from a file, shows its
folder and page, and removes it (optionally with its saved data). Every install and update shows the
risk screen; a plugin copied in by hand asks for it when first turned on. A plugin that closes or
freezes the app while starting is turned off at the next start.

A plugin runs as Python inside pokeldn with full access to files, keys, the network and the board.
Nothing in a package runs before it is installed and turned on.

### Sources

A source is a published JSON listing of plugins. **Sources** follows them; **Browse** lists their
plugins. `Decryptu/pokeldn-decrypt-plugins` is always followed. Removing a source keeps its plugins.

| typed under Sources | the listing read |
|---|---|
| `OWNER/REPO` or `https://github.com/OWNER/REPO` | `https://raw.githubusercontent.com/OWNER/REPO/HEAD/pokeldn-source.json` |
| an HTTPS address ending in `.json` | that file |
| any other HTTPS address | `pokeldn-source.json` in that folder |

```json
{"schema": 1, "name": "My plugins", "homepage": "https://github.com/me/my-plugins",
 "plugins": [{"id": "my-plugin", "name": "My plugin", "version": "1.0.0", "api": "1.6",
   "description": "...", "author": "me", "download": "https://.../my-plugin-1.0.0.pokeplugin",
   "sha256": "64 hex digits", "size": 46302, "icon": "https://.../icon.png", "homepage": "https://..."}]}
```

An entry lacking `id`, `version`, an HTTPS `download` or `sha256`, or repeating an id, is left out; a
`schema` other than 1 is refused; a download whose SHA-256 differs is refused before it is read; a
package whose id differs from the entry's is refused. The risk screen and signature check still run.
Sources are read at start (Settings, Updates on) and on refresh; the last listing is cached in
`plugins/.source-cache/`, the followed list is `plugins/.sources.json`. A plugin updates from the
source it came from; one installed from a file, from the first source listing it, else its `updates`.

```bash
python scripts/plugin_source.py my-plugin-1.0.0.pokeplugin -o pokeldn-source.json --name "My plugins" \
    --download "https://github.com/me/my-plugins/releases/download/{id}-{version}/{file}"
```

An entry already listed at a higher version is kept.

### Guardrails

Two checks stop obvious harm; neither is a sandbox. The install screen lists what the Python files do:
network, other programs, deleting files, native code (`ctypes`, `cffi`), runtime code (`exec`, `eval`,
`compile`, `marshal`), naming `prod.keys`, or compiled files it cannot read. While a plugin's code is
on the call stack, an audit hook (`pokeldn/plugin_guard.py`) raises `PermissionError` on:

| refused | allowed |
|---|---|
| deleting, emptying, moving or overwriting a file outside the plugin's folders | the same in its folder, data folder, library, the session, logs and temporary folders |
| starting `rm`, `del`, `rd`, `Remove-Item`, `shred`, `dd`, `format`, `mkfs`, `diskutil`, `diskpart`, `sudo`, `su` and similar, directly or in a shell, or any command with `-delete` or `--no-preserve-root` | any other program; creating a file anywhere |

pokeldn code a plugin calls is checked; code with no plugin on the stack never is.

## Making a plugin

    my-plugin/
        plugin.toml        what the plugin is
        plugin.py          register(api): what it adds
        hello.py           a tool's script
        icon.png           optional, square, 96 x 96
        mylib_common.py    optional shared module (the folder is on sys.path: use a unique name)

```toml
id = "my-plugin"            # required: lowercase letters, digits, dots, dashes, underscores
name = "My plugin"
version = "1.0.0"           # compared on update
author = "Your name"
description = "Shown on the install screen and the card."
homepage = "https://example.org/my-plugin"   # optional
updates = "https://github.com/you/my-plugin" # optional, see Updates
api = "1.1"                 # required: lowest API needed; 1 means 1.0
icon = "icon.png"           # optional
library = "My files"        # optional (1.7), see A library
library_sort = "name"       # optional (1.8)
module = "plugin"           # optional; the module holding register()
exclude = ["tests"]         # optional; left out by pack_plugin.py
```

A `plugin.toml` or language pack file nested deeper than 64 arrays or tables is refused unparsed
(`pokeldn.plugins.toml_loads`); brackets inside strings and comments do not count.

`register(api)` runs when the plugin is on, in the app and in every run it starts:

```python
from pokeldn.plugins import Field, Game, Tool

def register(api):
    api.add_tool("frlg", Tool(
        "my-hello", "Hello", "hello.py", "Says hello.",       # key, name, script, summary
        ("Nothing to do on the console.", "Press Start."),    # console steps
        fields=(Field("--name", "Your name", default="Red"),),
        fixed=("--trainer", "{ot}"),                          # always passed
    ))
```

### A tool's script

The app imports the script for `build_parser()` (the Advanced tab), then runs it as a child process
in the session folder. Work belongs under `if __name__ == "__main__"`; top-level work breaks the Games
page.

| the script | the app |
|---|---|
| prints a line | shows it in the output |
| prints `[done] trade N complete` (`pokeldn.ldn.show_done()`) | ticks one queued trade off |
| exits 0 / non-zero or raises | done / failed with the traceback |
| receives `KeyboardInterrupt` | Stop was pressed; leave within 15 s or the process is ended |
| `pokeldn.popup` (1.2), `popup.choose` (1.7) | a pop-up over any page; the answer comes back |
| `pokeldn.progress.show(done, total, title, unit)` (1.7) | a bar with rate and time left ([Progress](gui.md#progress)) |
| `pokeldn.panel` (1.8) | status cards and library notes ([Status cards](#status-cards-18)) |

A pop-up returns its id at once; the answer arrives later as a callback, on any thread:

```python
answers = queue.Queue()
popup.set_dispatcher(answers.put)       # run callbacks from the loop below
asked = popup.confirm("Trade the shiny?", "Your partner offers a shiny Gholdengo.", "Trade", "Skip",
                      on_agree=lambda: print("trading"), on_disagree=lambda: print("skipping"),
                      tone="warning")
while not finished():
    try:
        answers.get(timeout=0.5)()
    except queue.Empty:
        pass
popup.cancel(asked)                     # closes it; no callback fires
```

### What a plugin can import

The released app carries Python 3.13 and no `pip`:

| what | from |
|---|---|
| the standard library | bundled, except `multiprocessing`, `tkinter`, `curses`, `venv`, `ensurepip`, `profile`, `cProfile`, `pstats`, `trace`, `compileall`, `modulefinder`, `pyclbr`, `tabnanny` and other platforms' modules (`scripts/pack_app.py`, `PLUGIN_STDLIB`) |
| `trio`, `pycryptodome` (`Crypto`), `zstandard`, `pyserial` (`serial`), `websockets`, `certifi`, `bleak`, `unicorn`, `flet` | pokeldn's own dependencies, at the versions in `requirements.txt` |
| `ldn`, `pokeldn` | only the tables below are stable |
| pure-Python modules | the plugin's folder |

Compiled packages (`numpy`, `Pillow`) work only in a source run that has them.

### Fields

| `kind` | the input | passed as |
|---|---|---|
| `text` (default) | a text box | `--flag VALUE` |
| `number` | a number box | `--flag VALUE` |
| `choice` | a dropdown of `choices=((value, label), ...)` | `--flag VALUE` |
| `switch` | an on/off switch | `--flag` when on |
| `file` | a file chooser, `exts=("bin",)` | `--flag PATH` |

`help=`, `default=` and `hidden=True` (Advanced tab) apply to any field; the rest is in
`pokeldn/app/catalog.py`. `Field.identity` (1.5) is a stable settings key for a translated positional
field. `fixed` may carry `{ot}`, `{tid}`, `{sid}`, `{language}`, `{gender}`, `{received}`, `{stamp}` and
`{keys}` (1.7, Settings' `prod.keys`; a parser taking `--keys` gets it regardless).

### What a plugin keeps

An update replaces the folder. Lasting files go in `api.data` or, from a script,
`pokeldn.plugins.data_folder("my-plugin")`: `plugin-data/<id>`, deleted on removal only if asked.

### A library (1.7)

`library = "My files"` is `Documents/pokeldn/My files` (under `POKELDN_DATA` when set), returned by
`api.library` or `pokeldn.plugins.library_folder("my-plugin")`, created on first use. The guardrails
allow any write in it, the install screen names it, and removing the plugin leaves it. The Games page
lists its files under the plugin's tools, where the player adds, renames and deletes them; names
starting with `.` or ending in `.part` are hidden (write under one, then rename). Order is the
player's pick, else `library_sort` (`name`, `name-desc`, `date`, `date-desc`, `size`, `size-desc`),
else `date-desc`; names sort naturally. A name is up to 40 letters, digits, spaces, `.`, `-`, `_`;
pokeldn's own folders (`Bank`, `Saves`, `Received`...), Windows device names and another plugin's
library are refused.

### Status cards (1.8)

`pokeldn.panel` prints `[panel]` lines; the app draws cards on the tool's page and notes on library
files, keeps them in `plugin-panels/<id>.json` and deletes them with the plugin.

```python
panel.show("console", "Pokémon: Let's Go, Pikachu!", ["System version\t23.0.1"],
           image=icon, chips=[("Version", "1.0.2")], tone="ok")
panel.annotate("Game 1.0.2.nsp", state="ok", text="Every signature checks", image=icon)
```

| call | shows |
|---|---|
| `panel.show(id, title, lines=(), *, image=None, chips=(), tone="info")` | card `id`, replacing the last; a line is text or `label<TAB>value`; `tone` is `info`, `ok`, `warning`, `error` |
| `panel.clear(id)` | removes it |
| `panel.annotate(name, *, state="ok", text="", image=None)` | marks a library file `ok`, `bad` or `checking` |
| `panel.unannotate(name)` | removes the note |

Limits: id of 1 to 32 `[a-z0-9_-]`; 8 cards per plugin; title 80 chars, 12 lines of 200, 6 chips of
40; image a PNG or JPEG up to 2 MB in the data folder or library. A note follows the file name.
Exceeding a limit raises `ValueError`; an unreadable `[panel]` line shows in the output.

### A game of its own

```python
api.add_game(Game("my-game", "My game", "Mine", "", (tool_one, tool_two)), icon="icon.png")
```

`Game(key, name, short, doc, tools)`; `api.add_tool("my-game", tool)` adds more.

### A radio

`api.add_radio(scheme, install, label)` lists a radio under Plugins, **Radio**; a run calls
`install(argument, log)` before its first wireless call. `install` calls
`ldn.wlan.set_factory(factory)` with an async context manager yielding an `ldn.wlan.Factory`;
`pokeldn/ldn/esp32_wlan.py` is the reference. The app runs it as `POKELDN_RADIO=myradio:`; on the
command line the argument follows the colon.

### LDN networks (1.7)

`pokeldn.ldn.network` joins or hosts a network with the radio's IPv4 stack (ESP32 board or ldnrs).

```python
with network.join(COMM_ID, keys=args.keys, password=PASSPHRASE, name="My game") as net:
    net.add_protocol(6, lambda src, dst, segment: segments.put((src, segment)))
    while not net.send_ip(6, net.host_ip, first_segment):    # False until ARP resolves
        time.sleep(0.1)
```

| name | what it is |
|---|---|
| `join(comm_id, *, keys, password, nickname, app_version, name, log, timeout)` | joins the network advertising `comm_id`; `RuntimeError` when none answers |
| `host(comm_id, *, keys, password, nickname, application_data, scene_id, app_version, max_participants, channel, protocol, log, timeout)` | opens a network consoles join |
| `Network.ip`, `.mac`, `.host_ip`, `.broadcast`, `.ssid`, `.comm_id`, `.application_data` | addresses and advertisement |
| `Network.participants` | seated stations: `.index`, `.ip`, `.mac`, `.name` |
| `Network.add_protocol(number, handler)`, `.remove_protocol(number)` | `handler(src_ip, dst_ip, payload)` per reassembled IPv4 packet, on the radio loop; UDP (17) stays the stack's; exceptions drop the packet |
| `Network.send_ip(protocol, dst_ip, payload)` | one packet, fragmented at 1500; `False` while ARP is pending |
| `Network.udp_socket(port)` | `sendto`, `recvfrom`, `setblocking`, `settimeout`, `fileno`, `close` |
| `Network.set_application_data(data)` | a new advertisement |
| `Network.error`, `.close()` | why it ended; leaves. A context manager |
| `pokeldn.ldn.radio_lost()` | why the radio left, which tells it apart from Stop |

Throughput over the board is about 0.5 MB/s.

### A battle server

A battle server runs a Scarlet / Violet raid battle for `bin/sv_host.py --raid-serve [NAME]`
([Serving the battle](sv_raid.md#serving-the-battle)). `api.add_battle_server("sv", name, factory,
label)` registers it; `factory(bootstrap, partners)` is called off the network loop with the
bootstrap bytes and the two partners' 0x158-byte records.

| member | does |
|---|---|
| `start(now)` | first frame; returns frames that moved the battle |
| `run(until)` | frames at 30/s up to `until` (at least one); same return |
| `t` | the server clock, seconds |
| `receive(slot, message)` | a 32-byte header plus body from `slot` |
| `sent(slot)` | messages queued for `slot` since the last call |

Slots: 0 the program's Pokemon, 1 the boss, 2 the console, 3 and 4 the partners. An exception stops
serving and the console fights its own battle.

### Packing, testing, signing and updates

```bash
python scripts/pack_plugin.py my-plugin --key ~/my-plugin-signing.pem
POKELDN_PLUGINS=~/my-plugin python -m pokeldn --plugins            # lists plugins and load errors
POKELDN_PLUGINS=~/my-plugin python -m pokeldn my-hello -- --name Blue
POKELDN_PLUGINS=~/my-plugin python gui/main.py
```

`pack_plugin.py` writes `my-plugin-1.0.0.pokeplugin` and checks it as the app does; hidden files and
`exclude` stay out. Any zip works with `plugin.toml` at its top or in one top folder, no escaping path
and no symlink. `POKELDN_PLUGINS` turns a folder on for that process and its runs. A plugin that
raises in `register`, needs another API or reuses a key adds nothing and its card shows why. A Python
package can also register through the `pokeldn.plugins` entry point group.

`--key` signs with an Ed25519 key (created on first use) and prints its fingerprint
(`ABCD-EFGH-IJKL-MNOP`). `plugin.sig` holds the public key and a signature over the id, version and
every file's SHA-256. Keep the key private and backed up, and publish the fingerprint.

| the app sees | it |
|---|---|
| a signature that does not match | refuses the file |
| a new signed plugin | shows the fingerprint and remembers the key per id |
| an update with the remembered key | shows "Signed by the same author" |
| another key, or unsigned after signed | warns in red and asks a second acknowledgement |
| unsigned, never signed | shows "Not signed" |

| `updates` | the app reads |
|---|---|
| `https://github.com/OWNER/REPO` | the latest release's tag (`v1.3.0` or `1.3.0`) and first `.pokeplugin` |
| any other HTTPS address | `{"version": "1.3.0", "url": "https://.../my-plugin-1.3.0.pokeplugin", "page": "..."}` |

With Settings, Updates on, these are checked at start and on refresh; a newer version shows
**Update to 1.3.0**, which downloads and opens the install screen. HTTP is accepted only for
`127.0.0.1` and `localhost`.

## Language packs (1.5)

A language pack is a data-only plugin; `name` shows in Settings, App language, and `locale` is its tag.

```toml
id = "community-zh-hans"
name = "简体中文"
version = "1.0.0"
api = "1.5"
locale = "zh-Hans"
strings = "strings.toml"
```

`strings.toml` holds text values under quoted keys (`"bank.bank_676c47" = "宝可梦银行"`). Bad TOML,
non-text values and bad format syntax are refused at install; a damaged pack falls back to English.
Choosing a pack turns it on and needs a restart. A missing key uses its inline English default.
Placeholders like `{value0}` may move but keep their names and specs; `{{` and `}}` are literal braces;
a translation that fails to format uses English.

```bash
python scripts/extract_strings.py [--check]     # writes pokeldn/app/data/strings.en.toml
python scripts/pack_plugin.py examples/plugins/pseudo -o pseudo.pokeplugin
python scripts/check_language_pack.py PACK_FOLDER   # what the pack lacks against this release
```

`check_language_pack.py` lists untranslated strings and tool help, keys the release no longer has,
and translations whose placeholders differ from English; it exits 1 on a placeholder difference.

Tests check the template matches the source and refuse a key with two defaults. A pack starts as a
translated copy of the template; `examples/plugins/pseudo` is a partial pseudo-locale.

### Additional resources (1.9)

```toml
api = "1.9"
messages = "messages.toml"
templates = "templates.toml"
terms = "terms.toml"
help = "help.toml"
documents = "docs"
font_family = "Noto Sans CJK SC"
```

| entry | key | value |
|---|---|---|
| `messages` | a module's English text, verbatim | its translation |
| `templates` | `"Could not open {path}: {reason}"` | the translation with the same fields |
| `terms` | a game term (1 to 200 chars, at most 10000) | its translation |
| `help` | `"TOOL-KEY:--option"` | the flag's Advanced-tab description |
| `documents` | a folder of `guide.md` and `docs/` pages by name | |
| `font_family` | a font, at most 100 chars | the text font; CJK fallback stays |

Paths stay inside the plugin folder. These translate text from game modules, PKHeX and plugins: a
message is tried whole in `messages`, then `templates`, then per sentence, then with `terms` replaced
at word boundaries. A template has 1 to 8 plain named fields separated by literal text, at most 2048
chars, matched literally, longest first, on messages up to 4096 chars; a field named `term...` or
`message...` is itself translated, to depth 4. A value that is one species, move, ability, nature,
type or ball name whole, and that no term covers, takes PKHeX's name. PKHeX names and legality
reports follow the locale for `ja`, `fr`, `it`, `de`, `es`, `ko`, `zh-Hans`, `zh-Hant` (`zh` with
`TW`, `HK`, `MO` is `zh-Hant`).
Translated pages keep the English anchors when heading counts match, else `<a id="NAME"></a>` sets
one; a front-matter `title` renames a page in the sidebar.

File names, Bank and queue summaries, GTS listings, settings, the session log, radio output and
`[done]` lines stay English. Trainer language in Settings sets the language of built Pokemon.

## The Plugin Test Kit

`examples/plugins/test_kit` adds Self-test (checks every API part, prints PASS or FAIL, leaves a Last
self-test card), Simulated session (trade steps and `[done]` lines), Fail on purpose, "Hello from a
plugin" under FireRed & LeafGreen, and the Test Kit radio, which carries nothing.

## Versions

The API is `major.level`; a plugin's `api` is the lowest it needs. An addition raises the level (a
higher need is refused with "Update pokeldn"); a removal or change of meaning raises the major. An old
major still served is listed in `DEPRECATED` with its last release; one dropped falls below
`API_OLDEST` and is refused. A plugin's own `version` only decides update, reinstall or downgrade.

| API | added |
|---|---|
| 1.0 | `add_tool`, `add_game`, `add_radio`, `folder`, `version` |
| 1.1 | `api.data`, `api.level`, `pokeldn.plugins.data_folder(plugin_id)` |
| 1.2 | `pokeldn.popup` |
| 1.3 | the program surface: builders, gift files, PKHeX and the board |
| 1.4 | Bank imports, records, destinations, offers and trade completion |
| 1.5 | language-pack plugins and string lookup |
| 1.6 | `add_battle_server` |
| 1.7 | `pokeldn.ldn.network`, `pokeldn.ldn.radio_lost`, `library` and `api.library`, `pokeldn.popup.choose`, `pokeldn.progress`, the `{keys}` token |
| 1.8 | `pokeldn.panel`, `library_sort` |
| 1.9 | language-pack messages, templates, terms, tool help, documents and font preference |

## The API, version 1

| name | what it is |
|---|---|
| `api.add_tool(game, tool)` | a `Tool` under `frlg`, `lgpe`, `swsh`, `bdsp`, `pla`, `sv`, `za` or a plugin's game |
| `api.add_game(game, icon="")` | a game section |
| `api.add_radio(scheme, install, label="")` | a radio |
| `api.add_battle_server(game, name, factory, label="")` | a raid battle server (1.6) |
| `api.folder` | the plugin's folder, or None for a package |
| `api.version`, `api.level` | the app's API, `1` and `8` |
| `api.data` | the kept data folder (1.1) |
| `pokeldn.plugins.data_folder(plugin_id)` | the same from a script (1.1) |
| `api.library`, `pokeldn.plugins.library_folder(plugin_id)` | the library folder (1.7, [A library](#a-library-17)) |
| `Tool`, `Field`, `Game` | catalog types from `pokeldn.plugins` |
| `pokeldn.ldn.show_done()` | prints the trade-done line |
| `pokeldn.popup.acknowledge(title, text="", *, id, label="OK", on_ack, tone)` | a one-button pop-up; -> id (1.2, [Pop-ups](gui.md#pop-ups)) |
| `pokeldn.popup.confirm(title, text, agree, disagree, *, id, on_agree, on_disagree, on_dismiss, tone)` | two buttons; Esc or outside dismisses; -> id (1.2) |
| `pokeldn.popup.choose(title, text, options, *, id, on_choice, on_dismiss, tone)` | 2 to 8 options, `on_choice(index)`; -> id (1.7) |
| `pokeldn.progress.show(done, total, title, unit="bytes")` | a progress bar; `unit` `bytes` or `items` (1.7) |
| `pokeldn.panel.show(id, title, lines=(), *, image, chips, tone)`, `clear(id)`, `annotate(name, *, state, text, image)`, `unannotate(name)` | status cards (1.8, [Status cards](#status-cards-18)) |
| `pokeldn.ldn.network` | LDN networks (1.7, [LDN networks](#ldn-networks-17)) |
| `pokeldn.ldn.radio_lost()` | why the radio left, or empty (1.7) |
| `pokeldn.popup.cancel(id)`, `available()`, `set_dispatcher(dispatch)` | close a pop-up; whether pop-ups show; where callbacks run (1.2) |

This table and the next are the supported surface; any other import can change in any release.

## The program surface (1.3, Bank added in 1.4, language packs in 1.5)

A plugin or a separate program on a pokeldn checkout can use these; `tests/test_plugin_surface.py`
resolves each.

| name | what it is |
|---|---|
| `python -m pokeldn --list`, `python -m pokeldn TOOL -- ARGS` | tool keys; a run with Settings' trainer |
| `pokeldn.app.i18n.t(key, default, **fmt)`, `select(plugin_id)` | string lookup; select a pack, or English with `""` (1.5) |
| `pokeldn.app.catalog.GAMES` | built-in games and their `Tool`s; a flag the app passes keeps its name |
| `pokeldn.pokemon.SERVICE.species(game)`, `.names(game, kind)` | species, `moves`, `items`, `bag`, `held`, `balls` as `{"id", "name"}` lists |
| `pokeldn.pokemon.SERVICE.options(game, species, trainer)` | forms, natures, abilities, items and balls for an offer |
| `pokeldn.pokemon.SERVICE.make(game, species, trainer, level, shiny, nickname, version, options)` | a legal Pokemon; -> values and `"file"` |
| `pokeldn.pokemon.SERVICE.paste(game, text, trainer)` | Showdown sets as `make` values with `errors` |
| `pokeldn.pokemon.BuilderError` | PKHeX refused or missing, with a sentence for the player |
| `pokeldn.pokemon.NATURES` | the 25 nature names by index |
| `pokeldn.gifts.load(path, game=)`, `pokeldn.gifts.save(path, gift)` | `.pokegift`, `.wc3`, `.wc8` ([Mystery Gift files](gifts.md)) |
| `pokeldn.swsh.gift_builder.KINDS`, `PRESETS`, `PRESET`, `OUTFITS` | Sword/Shield gift kinds, presets and outfits |
| `pokeldn.swsh.gift_builder.blank(**changes)`, `record(state)`, `compile(state)`, `describe(state, name)` | form state, 720-byte record, gift, player lines; `ValueError` names a bad field |
| `pokeldn.swsh.events.load()`, `by_key()`, `gift(key)` | official Sword/Shield event cards |
| `pokeldn.frlg.gift.builder.KINDS`, `PRESETS`, `PRESET`, `GIVERS`, `CARTRIDGES` | FireRed/LeafGreen kinds, presets, givers, cartridges |
| `pokeldn.frlg.gift.builder.blank()`, `compile(state)`, `describe(state, name)` | the same for a Wonder Card, News or console code; `name` gets a species by its cartridge id |
| `gui.board.ports()`, `identify(port, blink=)`, `detect_chip(port)` | serial ports and a board's `.firmware`, `.firmware_version`, `.protocol`, `.current` |
| `gui.board.download_firmware(say=)`, `image_for(kind, chip)`, `image_version(path)`, `flash(port, kind=)` | checked release images and flashing |
| `pokeldn.app.bank.library()` | the default Bank folder; listing never creates it (1.4) |
| `pokeldn.app.bank.Entry`, `Imported`, `ImportedPokemon` | Bank result types (1.4) |
| `pokeldn.app.bank.Imported.count(state)` | results in a state (1.4) |
| `pokeldn.app.bank.entries(folder=)`, `find(entry_id, folder=)`, `data(entry)` | records newest first, one or `None`, its bytes (1.4) |
| `pokeldn.app.bank.import_file(path, trainers, folder=)` | import a Pokemon file or save; -> `Imported` (1.4) |
| `pokeldn.app.bank.deposit(game, source, info, folder=)` | bank a received file; -> `Entry` or `None` if already banked (1.4) |
| `pokeldn.pokemon.SERVICE.check(game, path)` | PKHeX inspection, the `info` for `deposit` (1.4) |
| `pokeldn.app.bank.destinations(entry, trainer)`, `offer(entry, game, trainer)` | conversions per game; a converted offer (1.4) |
| `pokeldn.app.bank.edit(entry, fields)`, `remove(entry_id, folder=)` | edit nickname, level up, moves, held item; delete a record (1.4) |
| `pokeldn.app.bank.TradeSession(offers, folder=)` | the run's ordered offers (1.4) |
| `pokeldn.app.bank.TradeSession.advance(count)` | apply a cumulative trade count; `.completed` is the highest seen (1.4) |
| `pokeldn.app.received.trades_done(line)` | the count in a `[done] trade N complete` line, or `None` (1.4) |

Stop a launcher run with SIGINT to its PID, then SIGTERM after 15 s; never `pkill -f`.

## Bank integrations (1.4)

An external frontend uses `pokeldn.app.bank` and owns its own queue and processes; conversion needs
the PKHeX helper (`dotnet build -c Release services/pkhex` from source).

| type | fields |
|---|---|
| `Entry` | `id`, `path` (native record), `game`, `species_id`, `shiny`, `summary`, `legal`, `tracker`, `created` (Unix s), `origin`, `home_tracker` (`empty`, `made` or `""`, [The HOME tracker setting](gui.md#the-home-tracker-setting)) |
| `Imported` | `name`, `save`, `pokemon` |
| `ImportedPokemon` | `where`, `species`, `species_id`, `shiny`, `state` (`banked`, `already`, `refused`), `game`, `detail` |
| `destinations` value | per game: `ok`, `reason`, `home_tracker` |
| `offer` value | `file`, `summary`, `species`, `shiny`, `legal`, `encounter`, `moves`, `report`, `home_tracker`, `bank` (source id) |

`trainers` maps game keys to `{ot, tid, sid, language, gender}`. Imports remember every record ever
imported. An offer leaves the Bank record in place; pass its `file` as the launcher's `--offer-file`
without `--fresh-pid`, and keep it until the run ends. Run the catalog tool's script directly, since
`python -m pokeldn TOOL` does not take an offer.

```python
from pokeldn.app import bank, received

trainer = {"ot": "ASH", "tid": 1111, "sid": 2222, "language": 2, "gender": 0}
bank.import_file("main", {g: trainer for g in ("frlg", "lgpe", "swsh", "bdsp", "pla", "sv", "za")},
                 folder="tradebox-bank")
entry = next(iter(bank.entries(folder="tradebox-bank")), None)
if entry is None:
    raise ValueError("No Pokemon available in the Bank.")
if not bank.destinations(entry, trainer)["swsh"]["ok"]:
    raise ValueError("cannot go to Sword/Shield")
session = bank.TradeSession([bank.offer(entry, "swsh", trainer)], folder="tradebox-bank")

def on_launcher_line(line):
    if (count := received.trades_done(line)) is not None:
        session.advance(count)
```

One `TradeSession` per run, in exact offer order, built offers included. Feed it confirmed counts only;
uncompleted records stay. `advance` raises `ValueError` on a bad count and can be retried after
`OSError`. File errors raise `OSError`; PKHeX failures raise `BuilderError`. `deposit` trusts
`SERVICE.check`; player files enter through `import_file`. `folder` defaults to `library()`. Set
`POKELDN_DATA` before import to isolate all files. Calls are synchronous: keep PKHeX off the UI
thread. One writer per Bank folder; a frontend beside the desktop app uses its own folder.
`TradeSession` changes only the Bank.

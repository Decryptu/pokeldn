---
title: Plugins
---
# Plugins

A plugin adds tools, games and radios to pokeldn without changing it, and can join or host an LDN
network of its own. It is a folder of Python files
with a `plugin.toml`, shipped as one `.pokeplugin` file that players add on the app's Plugins page.
The project does not distribute, review or support third-party plugins.

Code: `pokeldn/plugins.py` (the loader and the API), `pokeldn/app/plugin_store.py` (packages),
`pokeldn/ldn/radios.py` (the radio lookup), `gui/views/plugins.py` (the page).

Two examples are a base to start from: `examples/plugins/hello` is the smallest plugin, one tool in
two files; `examples/plugins/test_kit` uses every part of the API.

## Installing a plugin

1. Open **Plugins** at the bottom of the side menu.
2. Under **Browse**, press **Install** on a plugin a followed source lists; or drop a `.pokeplugin`
   file on the **Installed** tab, or press **Add a plugin** and choose it.
3. Read what the plugin is and the risks, tick the acknowledgement, and press **Install**.

The plugin's tools appear on the Games page at once, marked with a plug and "Plugin: ...".
Each plugin's card has a switch to turn it off and on, and a menu to open its tools, update it from a
newer file, show its folder, visit its page and remove it. Every install and update shows the risk
screen again. A plugin copied into the plugins folder by hand shows "Added by hand" and asks for the
same acceptance the first time it is turned on.

A plugin that closes or freezes the app while it starts is turned off at the next start, and the app
names it. Removing a plugin asks whether to delete what it saved as well.

A plugin runs as Python inside pokeldn, with the same access to files, keys, the network and the
board. Nothing in a package runs before it is installed and turned on.

### Sources

A source is a JSON listing of plugins that someone publishes. The Plugins page's **Sources** tab
follows sources; **Browse** lists every plugin they name with **Install**, **Update to N** or
**Installed**, and a remove button. The app follows `Decryptu/pokeldn-decrypt-plugins` from the start,
and that source cannot be removed. Removing another source keeps the plugins installed from it.

| typed under Sources | the listing read |
|---|---|
| `OWNER/REPO` or `https://github.com/OWNER/REPO` | `https://raw.githubusercontent.com/OWNER/REPO/HEAD/pokeldn-source.json` |
| an HTTPS address ending in `.json` | that file |
| any other HTTPS address | `pokeldn-source.json` in that folder |

```json
{
  "schema": 1,
  "name": "My plugins",
  "homepage": "https://github.com/me/my-plugins",
  "plugins": [
    {"id": "my-plugin", "name": "My plugin", "version": "1.0.0", "api": "1.6",
     "description": "...", "author": "me",
     "download": "https://github.com/me/my-plugins/releases/download/my-plugin-1.0.0/my-plugin-1.0.0.pokeplugin",
     "sha256": "64 hex digits", "size": 46302,
     "icon": "https://.../icon.png", "homepage": "https://..."}
  ]
}
```

`id`, `version`, an HTTPS `download` and the package's `sha256` are required; an entry missing one,
or repeating an id, is left out. A listing with another `schema` is refused. A download whose SHA-256
differs from the listing is refused before it is read, and a package whose id differs from the entry's
is refused before the risk screen. The listing proves nothing about the author: the risk screen and
the signature check run as for a file.

The app reads every followed source at start (with Settings, Updates on) and on the page's refresh,
and keeps the last listing in `plugins/.source-cache/`, shown when a source does not answer. The
followed list is `plugins/.sources.json`. An installed plugin records the source it came from and takes
its updates from that source; a plugin installed from a file takes them from the first source that
lists it, then from its own `updates` address.

`scripts/plugin_source.py` writes a listing from packages, reading each as the app would:

```bash
python scripts/plugin_source.py my-plugin-1.0.0.pokeplugin -o pokeldn-source.json --name "My plugins" \
    --download "https://github.com/me/my-plugins/releases/download/{id}-{version}/{file}"
```

An entry already listed at a higher version is kept.

### Guardrails

Two checks stop the obvious harm. Neither is a sandbox: a plugin written to get around them can.

The install screen reads the package's Python files and lists what they do: use the network, start
other programs, delete files, call native code (`ctypes`, `cffi`), run code built at run time
(`exec`, `eval`, `compile`, `marshal`), name `prod.keys`, or ship compiled files the reading cannot
see into. An empty list means none was found, not that the plugin is safe.

While a plugin's code is on the call stack, in the app and in every run, an audit hook
(`pokeldn/plugin_guard.py`) refuses with `PermissionError`:

| refused | allowed |
|---|---|
| deleting, emptying, moving or overwriting a file outside the plugin's folders | the same inside its folder, its data folder, its library, the session folder, the logs folder and the temporary folder |
| starting `rm`, `del`, `rd`, `Remove-Item`, `shred`, `dd`, `format`, `mkfs`, `diskutil`, `diskpart`, `sudo`, `su` and similar, directly or inside a shell command, or any command with `-delete` or `--no-preserve-root` | starting any other program |
| | creating a new file anywhere |

Code with no plugin on its call stack, pokeldn's own included, is never refused; pokeldn code a
plugin calls is. A plugin that needs a refused action asks the player to do it.

## Making a plugin

### The folder

    my-plugin/
        plugin.toml        what the plugin is
        plugin.py          register(api): what it adds
        hello.py           a tool's script
        icon.png           optional, shown on the Plugins page and the Games page
        mylib_common.py    optional, any module the scripts share

### plugin.toml

```toml
id = "my-plugin"            # required: lowercase letters, digits, dots, dashes, underscores
name = "My plugin"          # shown in the app
version = "1.0.0"           # compared on update: 1.2.0 updates 1.0.0
author = "Your name"
description = "One or two sentences shown on the install screen and the plugin's card."
homepage = "https://example.org/my-plugin"   # optional, opened from the plugin's menu
updates = "https://github.com/you/my-plugin" # optional, where newer versions are published (Updates)
api = "1.1"                 # required: the plugin API it needs (see Versions); 1 means 1.0
icon = "icon.png"           # optional; a square PNG, 96 x 96 looks sharp
library = "My files"        # optional (1.7): a folder the player sees, see A library
library_sort = "name"       # optional (1.8): its order until the player picks one, see A library
module = "plugin"           # optional; the module holding register()
exclude = ["tests"]         # optional; folders and files pack_plugin.py leaves out of the package
```

### plugin.py

`register(api)` runs when the plugin is turned on, in the app and in every run the app starts.

```python
from pokeldn.plugins import Field, Game, Tool


def register(api):
    api.add_tool("frlg", Tool(
        "my-hello",                                   # a key no other tool uses
        "Hello",                                      # the name on the Games page
        "hello.py",                                   # the script, relative to the plugin folder
        "Says hello.",                                # the line under the tool's name
        ("Nothing to do on the console.", "Press Start."),   # the console steps the app lists
        fields=(Field("--name", "Your name", default="Red"),),
        fixed=("--trainer", "{ot}"),                  # always passed; {ot} is the trainer name in Settings
    ))
```

### A tool's script

The app imports the script to read its options for the Advanced tab, then runs it as its own child
process in the session folder. The script defines `build_parser()` and does its work under
`if __name__ == "__main__"`; work at the top level runs on import and breaks the Games page.

```python
import argparse


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name")
    parser.add_argument("--trainer")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    print(f"Hello {args.name}, from {args.trainer}'s pokeldn.")
```

| the script | the app |
|---|---|
| prints a line | shows it in the session's output |
| prints `[done] trade N complete` (`pokeldn.ldn.show_done()`) | ticks one queued trade off |
| exits with code 0 | ends the session as done |
| exits with another code or raises | shows the session as failed, with the traceback in the output |
| receives `KeyboardInterrupt` | the player pressed Stop; leave cleanly within 15 s or the process is ended |
| opens a pop-up (`pokeldn.popup`, 1.2) | shows it over whatever page the app shows, and sends the player's answer back |
| asks for one of several options (`pokeldn.popup.choose`, 1.7) | shows a button per option and sends back the index pressed |
| reports progress (`pokeldn.progress.show(done, total, title, unit)`, 1.7) | draws a bar with the rate and the time left in the Session panel, in place of the line ([Progress](gui.md#progress)) |
| shows a status card or marks a library file (`pokeldn.panel`, 1.8) | draws it on the tool's page and keeps it after the run ([Status cards](#status-cards-18)) |

A pop-up never waits for the player: `acknowledge` and `confirm` return its id at once, and the answer
comes later as a callback, which may fire at any time, on another thread. A script keeps its own state
and reacts to the answer whenever it comes, instead of stopping until it does:

```python
import queue
from pokeldn import popup

answers = queue.Queue()
popup.set_dispatcher(answers.put)       # callbacks wait for the loop below instead of running on their own thread
asked = popup.confirm("Trade the shiny?", "Your partner offers a shiny Gholdengo.", "Trade", "Skip",
                      on_agree=lambda: print("trading"), on_disagree=lambda: print("skipping"),
                      tone="warning")
while not finished():                   # the script's own work goes on meanwhile
    try:
        answers.get(timeout=0.5)()
    except queue.Empty:
        pass
popup.cancel(asked)                     # no use for the answer any more: the pop-up closes, no callback fires
```

Give shared modules a name no other package uses (`mylib_common`, not `utils`): the plugin's folder
is added to Python's search path.

### What a plugin can import

The released app carries its own Python 3.13 and no `pip`. A plugin can import:

| what | where it comes from |
|---|---|
| the standard library | bundled, except `multiprocessing`, `tkinter`, `curses`, `venv`, `ensurepip`, `profile`, `cProfile`, `pstats`, `trace`, `compileall`, `modulefinder`, `pyclbr`, `tabnanny` and the modules of another platform (`scripts/pack_app.py`, `PLUGIN_STDLIB`) |
| `trio`, `pycryptodome` (`Crypto`), `zstandard`, `pyserial` (`serial`), `websockets`, `certifi`, `bleak`, `unicorn`, `flet` | pokeldn's own dependencies, at the versions in `requirements.txt` |
| `ldn` and `pokeldn` | pokeldn itself; only the API table below is stable |
| any pure-Python module | shipped in the plugin's folder |

A package with compiled code (`numpy`, `Pillow`) works only from source runs where it is installed.
Test a plugin in a released app before publishing it: the Plugin Test Kit's self-test runs the same
way there.

### Fields

A `Field` is one input on the tool's Basic tab; the app passes its value after its flag.

| `kind` | the input | passed as |
|---|---|---|
| `text` (default) | a text box | `--flag VALUE` |
| `number` | a number box | `--flag VALUE` |
| `choice` | a dropdown of `choices=((value, label), ...)` | `--flag VALUE` |
| `switch` | an on/off switch | `--flag` when on |
| `file` | a file chooser, `exts=("bin",)` | `--flag PATH` |

### What a plugin keeps

An update replaces the plugin's folder. Settings, caches and anything else meant to last go in
`api.data` from `register`, or `pokeldn.plugins.data_folder("my-plugin")` from a tool's script: the
data folder's `plugin-data/<id>`, kept across updates and deleted on removal only if the player
asks.

### A library (1.7)

A plugin that keeps files the player looks after (backups, downloads) names a library in
`plugin.toml`: `library = "My files"` is `Documents/pokeldn/My files` (the data folder's `My files`
under `POKELDN_DATA`). `api.library` from `register`, or `pokeldn.plugins.library_folder("my-plugin")`
from a tool's script, returns it, created on first use.

| the library | |
|---|---|
| the guardrails | allow writing, replacing, renaming and deleting in it, as in the data folder |
| the install screen | names it |
| removing the plugin | leaves it and every file in it |
| the Games page | lists its files under the plugin's tools; the player adds a file (a button or a drop), renames and deletes. Names starting with `.` and ending in `.part` are left out: write a file under such a name and replace it with the whole one |
| its order | by name, date or size, ascending or descending, picked by the player and kept per plugin; until then `plugin.toml`'s `library_sort` (1.8: `name`, `name-desc`, `date`, `date-desc`, `size`, `size-desc`), else `date-desc`, newest first. Names sort naturally: digit runs compare as numbers and case is ignored, so `v65536` comes before `v131072` and `20.5.0` before `23.0.1` |
| a file's note | `pokeldn.panel.annotate` (1.8, [Status cards](#status-cards-18)) |
| its name | up to 40 letters, digits, spaces, dots, dashes and underscores; a folder of pokeldn's own (`Bank`, `Saves`, `Received`...), a Windows device name and another loaded plugin's library are refused |

`help=` puts a line under the input, `default=` fills it, and `hidden=True` moves it to the
Advanced tab. The fields the built-in tools use, and the
rest of `Field`, are in `pokeldn/app/catalog.py`. API 1.5 adds `Field.identity`, a stable settings
key for a positional field whose label is translated. A tool's `fixed` arguments may carry `{ot}`,
`{tid}`, `{sid}`, `{language}` and `{gender}` (the trainer in Settings), `{received}` (the Received
folder), `{stamp}` (the run's start time) and, from 1.7, `{keys}` (the `prod.keys` file Settings names).
A script whose parser takes `--keys` receives that file's path even without the token.

### Status cards (1.8)

A run leaves cards at the top of its tool's page, above the fields, and notes on its library's files.
`pokeldn.panel` prints them as `[panel]` lines, so they work the same from source and in the released
app; the app keeps them in the data folder's `plugin-panels/<id>.json` after the run ends and
deletes them with the plugin. Outside the app the line is printed and nothing else.

```python
from pokeldn import panel, plugins

icon = plugins.data_folder("my-plugin") / "icons" / "0100abcd.png"
panel.show("console", "Pokémon: Let's Go, Pikachu!", [
    "Group\tcapito27's Switch · 1 of 8 consoles",
    "System version\t23.0.1",
], image=icon, chips=[("Version", "1.0.2")], tone="ok")
panel.annotate("Game 1.0.2.nsp", state="ok", text="Every signature checks", image=icon)
```

| call | what the app shows |
|---|---|
| `panel.show(id, title, lines=(), *, image=None, chips=(), tone="info")` | the card `id`, replacing the one last shown under it. A line is plain text, or `label<TAB>value` for two columns; a chip is a `(label, value)` pair; `tone` is `info`, `ok`, `warning` or `error`, an icon beside the title |
| `panel.clear(id)` | removes the card |
| `panel.annotate(name, *, state="ok", text="", image=None)` | marks the library file `name`: `ok`, `bad` or `checking`, a line of text under it and the image in place of its file icon |
| `panel.unannotate(name)` | removes the note |

| limit | |
|---|---|
| a card id | 1 to 32 lower-case letters, digits, `-` and `_` |
| cards per plugin | 8; a new id past them is dropped |
| a card | a title of up to 80 characters, 12 lines of up to 200, 6 chips of up to 40 a side |
| an image | a PNG or JPEG of at most 2 MB in the plugin's data folder or library; any other is not drawn |
| a note | belongs to the file name: renaming or deleting the file drops it |

A call outside these limits raises ValueError in the script; a `[panel]` line the app cannot read is
shown in the session's output.

### A game of its own

```python
api.add_game(Game("my-game", "My game", "Mine", "", (tool_one, tool_two)), icon="icon.png")
```

`Game(key, name, short, doc, tools)`; the game's section lists its tools in order, under the built-in
games. `api.add_tool("my-game", tool)` adds more to it.

### A radio

A radio carries the wireless messages in place of the ESP32 board. `api.add_radio(scheme, install,
label)` lists it on the Plugins page under **Radio**; a run started with that radio calls
`install(argument, log)` before its first wireless call.

```python
import contextlib
from ldn import wlan


def install(argument, log):
    @contextlib.asynccontextmanager
    async def factory():
        yield MyFactory()           # the interface of ldn.wlan.Factory
    wlan.set_factory(factory)


def register(api):
    api.add_radio("myradio", install, "My radio")
```

`pokeldn/ldn/esp32_wlan.py` is the board's factory and the reference for one with no kernel
interface. The app runs a plugin radio as `POKELDN_RADIO=myradio:` with an empty argument; from the
command line the argument is what follows the colon.

### LDN networks (1.7)

`pokeldn.ldn.network` joins or hosts an LDN network for a plugin and hands it the radio's IPv4 stack.
It needs a radio with no kernel interface: the ESP32 board or ldnrs.

```python
from pokeldn.ldn import network

with network.join(COMM_ID, keys=args.keys, password=PASSPHRASE, name="My game") as net:
    net.add_protocol(6, lambda src, dst, segment: segments.put((src, segment)))   # TCP, say
    while not net.send_ip(6, net.host_ip, first_segment):    # False until ARP finds the host
        time.sleep(0.1)
```

| name | what it is |
|---|---|
| `join(comm_id, *, keys, password, nickname, app_version, name, log, timeout)` | scans and joins the network advertising `comm_id`, and no other; `name` is what the player's messages call it. Raises `RuntimeError` when none answers |
| `host(comm_id, *, keys, password, nickname, application_data, scene_id, app_version, max_participants, channel, protocol, log, timeout)` | opens a network consoles join |
| `Network.ip`, `.mac`, `.host_ip`, `.broadcast`, `.ssid`, `.comm_id`, `.application_data` | the addresses and the advertisement: the host's when joined, ours when hosting |
| `Network.participants` | the stations seated on a hosted network, each `.index`, `.ip`, `.mac`, `.name` |
| `Network.add_protocol(number, handler)`, `.remove_protocol(number)` | `handler(src_ip, dst_ip, payload)` takes every reassembled IPv4 packet of `number` sent to us, on the radio's loop: queue it and return. UDP (17) stays the stack's. An exception from the handler is logged and the packet dropped |
| `Network.send_ip(protocol, dst_ip, payload)` | one IPv4 packet, fragmented at 1500 bytes; `False`, with an ARP request sent, while `dst_ip`'s address is unknown |
| `Network.udp_socket(port)` | a UDP socket on the network: `sendto`, `recvfrom`, `setblocking`, `settimeout`, `fileno`, `close` |
| `Network.set_application_data(data)` | a hosted network's new advertisement |
| `Network.error`, `.close()` | why the network ended (empty while up); leaves it. A `Network` is a context manager |
| `pokeldn.ldn.radio_lost()` | why the radio left the process, or empty. The run then ends with the same `KeyboardInterrupt` as the player's Stop; this tells them apart |

A transfer over the board runs at about 0.5 MB/s; report it with `pokeldn.progress.show`.

### A battle server

A battle server runs a raid battle for a host launcher, so the console and the program's Pokemon
fight one battle ([Serving the battle](sv_raid.md#serving-the-battle)). Scarlet / Violet (`"sv"`) is
the only game that takes one. `api.add_battle_server(game, name, factory, label)` registers it; a run
of `bin/sv_host.py --raid-serve NAME` (or `--raid-serve` alone, the first one loaded) calls
`factory(bootstrap, partners)` once the console sends the battle bootstrap, off the network loop.
`bootstrap` is the battle bootstrap's bytes, `partners` the two NPC partners' 0x158-byte party
records. The object it returns:

| member | what it does |
|---|---|
| `start(now)` | the server's first frame at `now` seconds; returns the number of frames that moved the battle |
| `run(until)` | frames at 30 a second up to `until` seconds (at least one); returns the number that moved the battle |
| `t` | the server's clock, in seconds |
| `receive(slot, message)` | a station's message, 32-byte header then body, from battle slot `slot` |
| `sent(slot)` | the messages queued for `slot` since the last call, each a 32-byte header then body |

Slot 0 is the program's Pokemon, 1 the boss, 2 the console, 3 and 4 the partners. An exception from
any member stops the serving; the console then fights its own battle.

```python
def register(api):
    api.add_battle_server("sv", "mine", MyServer, "My raid battle")
```

### Packing and testing

```bash
python scripts/pack_plugin.py my-plugin --key ~/my-plugin-signing.pem
```

writes `my-plugin-1.0.0.pokeplugin`, signed, and checks it the way the app does before installing.
Hidden files and the folders `exclude = ["tests", "tools"]` in `plugin.toml` names stay out of the package. Any zip
works if `plugin.toml` sits at its top or inside one top folder, with no path leaving that folder
and no symbolic link.

While writing, skip the package: name the folder in `POKELDN_PLUGINS` and the plugin is on in that
process and the runs it starts, whatever the Plugins page says.

```bash
POKELDN_PLUGINS=~/my-plugin python -m pokeldn --plugins
POKELDN_PLUGINS=~/my-plugin python -m pokeldn my-hello -- --name Blue
POKELDN_PLUGINS=~/my-plugin python gui/main.py
```

`--plugins` lists every plugin found and why one failed to load. A plugin that raises in
`register`, targets another API version or takes a key in use adds nothing; its card shows the
error and the other plugins still load. A plugin can also ship as a Python package with an entry
point in the `pokeldn.plugins` group naming the module that holds `register`.

### Signing

`--key FILE` signs the package with the author's Ed25519 key, made in `FILE` the first time, and
prints the key's fingerprint (`ABCD-EFGH-IJKL-MNOP`). The package carries `plugin.sig`: the public
key and a signature over the plugin's id, its version and the SHA-256 of every other file.

| the app sees | it shows |
|---|---|
| a signature that does not match the files | refuses the file: it was changed after its author signed it |
| a signed plugin it has not seen before | the fingerprint, and remembers the key for that plugin id |
| an update signed with the remembered key | "Signed by the same author" |
| an update signed with another key, or unsigned where the earlier copy was signed | a red warning and a second acknowledgement before Install works |
| an unsigned plugin never seen signed | "Not signed" |

Keep the key file private and backed up: a lost key makes every later version look like someone
else's, and anyone holding it can sign as the author. Publish the fingerprint on the plugin's page,
so players can compare it with the one the install screen shows. The first install cannot prove who
the author is; signing proves that later versions come from the same one.

### Updates

`updates` in `plugin.toml` names where newer versions are published:

| `updates` | the app reads |
|---|---|
| `https://github.com/OWNER/REPO` | the latest release: its tag (`v1.3.0` or `1.3.0`) and its first `.pokeplugin` asset |
| any other HTTPS address | a JSON file `{"version": "1.3.0", "url": "https://.../my-plugin-1.3.0.pokeplugin", "page": "..."}` |

With Settings, Updates on, the app asks each installed plugin's address at start and when the
Plugins page's refresh is pressed. A newer version turns the Plugins menu entry green and puts
**Update to 1.3.0** on the plugin's card; pressing it downloads the file and opens the install
screen with its signature check. Nothing installs without the player's acceptance. HTTP is accepted
for `127.0.0.1` and `localhost` only, to test a release locally.

## Language packs (1.5)

A language pack is a data-only folder plugin. Its `name` is the display name in Settings,
App language. Its `locale` is a language tag; the saved selection identifies the plugin by `id`.

```toml
id = "community-zh-hans"
name = "简体中文"
version = "1.0.0"
api = "1.5"
locale = "zh-Hans"
strings = "strings.toml"
```

`strings.toml` sits beside `plugin.toml`. Quote each dotted key so TOML reads a flat table:

```toml
"bank.bank_676c47" = "宝可梦银行"
```

The file contains text values only. A pack needs no Python module or `register` function.
Installation, signatures, author keys, removal and `updates` use the same package path as other
plugins. Invalid TOML, non-text values and invalid format syntax are refused before installation.
A damaged installed pack shows its loading error and falls back to English.

Install the pack on the Plugins page, then choose it in Settings, App language and restart pokeldn.
Choosing a pack enables its plugin. English is always available. A missing, disabled or removed pack
uses English. Trainer language still controls the Pokemon the app builds.

Every lookup has an inline English default. Missing keys use that default; unused keys have no
effect. Named placeholders such as `{value0}` can move within a translation. Keep their names,
conversions and format specifications; `{{` and `}}` produce literal braces. A translation whose
placeholders cannot be formatted uses the English default for that lookup.

```bash
python scripts/extract_strings.py
python scripts/extract_strings.py --check
python scripts/pack_plugin.py examples/plugins/pseudo -o pseudo.pokeplugin
```

The extractor writes `pokeldn/app/data/strings.en.toml`, sorted by key. Tests check that it matches
the source and refuse a key with two English defaults. Keys remain unchanged when wording changes.
Copy the template into a separate plugin repository and translate its values; omitted keys need no
maintenance. The partial pseudo-locale in `examples/plugins/pseudo` brackets selected strings and
leaves others to exercise fallback. Examples are excluded from desktop packages.

### Additional resources (1.9)

A pack at API 1.9 can name these optional files and folder beside `plugin.toml`. A 1.5 pack stays
valid. Installation, signatures and updates cover them as they cover `strings.toml`, and none may name
a path outside the plugin folder.

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
| `messages` | a module's English text, verbatim, braces literal | its translation |
| `templates` | an English message with named fields, `"Could not open {path}: {reason}"` | the translation with the same fields |
| `terms` | a game term (1 to 200 characters, at most 10000 terms), `"Squirtle"` | its translation |
| `help` | `"TOOL-KEY:--option"`, one tool's flag | that flag's description on the Advanced tab |
| `documents` | a folder holding `guide.md` and the pages of `docs/` under their names | |
| `font_family` | a bundled or installed font, at most 100 characters | the app's text font; the CJK fallback stays |

`strings.toml` still carries the app's own controls through `t(key, English)`. The other tables
translate English text that game modules, PKHeX and plugins produce, where a control shows it:
labels, summaries, errors, gift and raid descriptions. A message is looked up whole in `messages`,
then against `templates`, then sentence by sentence, then with each `terms` entry replaced at word
boundaries. A missing entry shows the English.

A template's source keeps 1 to 8 plain named fields in at most 2048 characters, each followed by
literal text before the next field; it holds no conversion, format specification or attribute access.
Matching is literal, without regular expressions, longest source first, on messages of at most 4096
characters. A captured value is shown as it is, unless its field name starts with `term` (translated
as game terms and as a message) or `message` (translated as a message), to a depth of 4.

PKHeX names species, moves, items, abilities, natures and balls in the pack's locale when it has that
language (`ja`, `fr`, `it`, `de`, `es`, `ko`, `zh-Hans`, `zh-Hant`; `zh` with `TW`, `HK` or `MO` reads
`zh-Hant`), and gives legality reports in it. Flet's own dialogs and file pickers follow the locale.

The documents reader and its search read a pack's page where the pack has one and the English page
otherwise. A translated page keeps the English page's heading anchors when it has as many headings;
an `<a id="NAME"></a>` line before a heading sets its anchor otherwise. A front-matter `title`
renames the page in the sidebar; the tree itself is the English one.

What a record, a file or another app reads stays English: file names, bank and queue summaries, GTS
listings, settings, the session log (its `[app]` lines are shown translated), radio script output and
`[done]` lines. Trainer language, in Settings, still sets the language of the Pokemon the app builds.

## The Plugin Test Kit

`examples/plugins/test_kit`, packed with `scripts/pack_plugin.py`, adds:

| where | tool | what it does |
|---|---|---|
| Plugin Test Kit | Self-test | checks the API version, its own loading, its imports, every field kind, the trainer token, the session folder, its data folder (a run counter that survives updates), its library and a note on its file, and its radio; prints PASS or FAIL for each and leaves a Last self-test card on its page |
| Plugin Test Kit | Simulated session | prints a trade's steps and a `[done]` line per trade; Stop ends it cleanly |
| Plugin Test Kit | Fail on purpose | raises, or exits with code 3 |
| FireRed & LeafGreen | Hello from a plugin | a plugin tool among the built-in ones |
| Radio | Test Kit radio | installs and carries nothing; a session started with it says so |

## Versions

The plugin API has a major and a level, written `1.1`. A plugin's `api` names the lowest version it
needs; the app shows its own on the Plugins page and in `python -m pokeldn --plugins`.

| change to the API | the app |
|---|---|
| an addition | raises the level; a plugin needing a higher level is refused with "Update pokeldn" |
| a removal or a change of meaning | raises the major |
| an old major still served | `DEPRECATED` in `pokeldn/plugins.py` names the release that drops it; the plugin loads, and its card and install screen say so |
| an old major dropped | `API_OLDEST` passes it; the plugin is refused with "Ask its author for a newer version" |

A plugin's own `version` is only compared with its installed copy, to show an update, a reinstall
or a downgrade.

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
| `api.add_tool(game, tool)` | adds a `Tool` under the game whose key is `game`: `frlg`, `lgpe`, `swsh`, `bdsp`, `pla`, `sv`, `za`, or one the plugin added |
| `api.add_game(game, icon="")` | adds a game section with its tools |
| `api.add_radio(scheme, install, label="")` | adds a radio |
| `api.add_battle_server(game, name, factory, label="")` | adds a raid battle server (1.6) |
| `api.folder` | the plugin's folder (a `Path`), or None for a Python package |
| `api.version`, `api.level` | the major and level the app runs, `1` and `8` |
| `api.data` | a folder kept across updates, created on first use (1.1) |
| `pokeldn.plugins.data_folder(plugin_id)` | the same folder from a tool's script (1.1) |
| `api.library`, `pokeldn.plugins.library_folder(plugin_id)` | the player-visible folder `plugin.toml`'s `library` names, created on first use (1.7, [A library](#a-library-17)) |
| `Tool`, `Field`, `Game` | the app's catalog types, imported from `pokeldn.plugins` |
| `pokeldn.ldn.show_done()` | prints the line that ticks a trade off |
| `pokeldn.popup.acknowledge(title, text="", *, id, label="OK", on_ack, tone)` | a pop-up with one button; -> its id (1.2, [Pop-ups](gui.md#pop-ups)) |
| `pokeldn.popup.confirm(title, text, agree, disagree, *, id, on_agree, on_disagree, on_dismiss, tone)` | a pop-up with the agree and disagree buttons the caller names, Esc or a click outside dismissing it; -> its id (1.2) |
| `pokeldn.popup.choose(title, text, options, *, id, on_choice, on_dismiss, tone)` | a pop-up with 2 to 8 option buttons; `on_choice(index)` gets the one pressed, Esc or a click outside fires `on_dismiss`; -> its id (1.7) |
| `pokeldn.progress.show(done, total, title, unit="bytes")` | a progress bar in the Session panel; `unit` is `bytes` or `items` (1.7) |
| `pokeldn.panel.show(id, title, lines=(), *, image, chips, tone)`, `clear(id)`, `annotate(name, *, state, text, image)`, `unannotate(name)` | status cards on the tool's page and notes on library files (1.8, [Status cards](#status-cards-18)) |
| `pokeldn.ldn.network` | joining and hosting an LDN network with its IPv4 stack (1.7, [LDN networks](#ldn-networks-17)) |
| `pokeldn.ldn.radio_lost()` | why the radio left the run, or empty (1.7) |
| `pokeldn.popup.cancel(id)`, `available()`, `set_dispatcher(dispatch)` | closes a pop-up, dropping its callbacks; whether an app shows them; where callbacks run (1.2) |

This table and the next one are the supported surface. Anything else a plugin imports from pokeldn
can change in any release.

## The program surface (1.3, Bank added in 1.4, language packs in 1.5)

A plugin, or a separate program built on a pokeldn checkout (a touchscreen front end, a script), can
build gifts and Pokemon and manage the board with the same code the app uses. These names keep their
meaning within API major 1; `tests/test_plugin_surface.py` resolves every one.

| name | what it is |
|---|---|
| `python -m pokeldn --list`, `python -m pokeldn TOOL -- ARGS` | every tool's key, and a run of one with the trainer in Settings and the arguments after `--` |
| `pokeldn.app.i18n.t(key, default, **fmt)`, `select(plugin_id)` | string lookup with an inline English default and named formatting; select an enabled language pack by plugin id, or English with an empty id (1.5) |
| `pokeldn.app.catalog.GAMES` | the built-in games, each `Game`'s `.tools` holding its `Tool`s: the script under `bin/` and its fields; a flag the app passes keeps its name |
| `pokeldn.pokemon.SERVICE.species(game)`, `.names(game, kind)` | the species, and the `moves`, `items`, `bag`, `held` or `balls` a game has, as `{"id", "name"}` lists |
| `pokeldn.pokemon.SERVICE.options(game, species, trainer)` | the forms, natures, abilities, items and balls an offer of that species can carry |
| `pokeldn.pokemon.SERVICE.make(game, species, trainer, level, shiny, nickname, version, options)` | a legal Pokemon for that game; `options` takes nature, ability, gender, held item, ball, friendship, moves, IVs and EVs; -> its values and `"file"`, the path written |
| `pokeldn.pokemon.SERVICE.paste(game, text, trainer)` | the Showdown sets in `text`, each as `make`'s values with its `errors` |
| `pokeldn.pokemon.BuilderError` | raised with a sentence for the player when PKHeX refuses or is missing |
| `pokeldn.pokemon.NATURES` | the 25 nature names by the index every record stores |
| `pokeldn.gifts.load(path, game=)`, `pokeldn.gifts.save(path, gift)` | read and write a `.pokegift`, `.wc3` or `.wc8` ([Mystery Gift files](gifts.md)) |
| `pokeldn.swsh.gift_builder.KINDS`, `PRESETS`, `PRESET`, `OUTFITS` | the Sword/Shield builder's gift kinds `(key, label, icon)`, presets (`.key`, `.label`, `.group`, `.summary`, `.state`) and outfits |
| `pokeldn.swsh.gift_builder.blank(**changes)`, `record(state)`, `compile(state)`, `describe(state, name)` | a form state, its sealed 720-byte record, its gift for `gifts.save`, and its lines for the player; a bad state raises `ValueError` naming the field. A Pokemon's state takes `nature` (0 to 24; absent, the game rolls one) |
| `pokeldn.swsh.events.load()`, `by_key()`, `gift(key)` | the official Sword/Shield event cards and the gift for one |
| `pokeldn.frlg.gift.builder.KINDS`, `PRESETS`, `PRESET`, `GIVERS`, `CARTRIDGES` | the FireRed/LeafGreen builder's kinds, presets, the people who hand a card over and the cartridges a console code can target |
| `pokeldn.frlg.gift.builder.blank()`, `compile(state)`, `describe(state, name)` | the same for a Wonder Card, Wonder News or console code |
| `gui.board.ports()`, `identify(port, blink=)`, `detect_chip(port)` | the serial ports, and what a board runs: `.firmware`, `.firmware_version`, `.protocol`, `.current` (its protocol is this pokeldn's) |
| `gui.board.download_firmware(say=)`, `image_for(kind, chip)`, `image_version(path)`, `flash(port, kind=)` | the release's images checked against their SHA-256, the image a chip takes, its version, and flashing it after checking the chip |
| `pokeldn.app.bank.library()` | the default Bank folder as a `Path`; listing never creates it (1.4) |
| `pokeldn.app.bank.Entry`, `Imported`, `ImportedPokemon` | the Bank result types described below (1.4) |
| `pokeldn.app.bank.Imported.count(state)` | the number of import results in that state (1.4) |
| `pokeldn.app.bank.entries(folder=)`, `find(entry_id, folder=)`, `data(entry)` | records newest first, a record or `None`, and its native bytes (1.4) |
| `pokeldn.app.bank.import_file(path, trainers, folder=)` | import a Pokemon file or save, leaving the source untouched; -> `Imported` (1.4) |
| `pokeldn.app.bank.deposit(game, source, info, folder=)` | bank a copy of a received file and its PKHeX inspection result; -> `Entry`, or `None` for bytes already banked (1.4) |
| `pokeldn.pokemon.SERVICE.check(game, path)` | inspect a received native record with PKHeX; -> the `info` dictionary for `bank.deposit`, including its legality verdict (1.4) |
| `pokeldn.app.bank.destinations(entry, trainer)`, `offer(entry, game, trainer)` | conversion availability per game, and a converted offer for one game (1.4) |
| `pokeldn.app.bank.edit(entry, fields)`, `remove(entry_id, folder=)` | edit nickname, upward level, moves or held item; -> the updated `Entry`; explicitly delete a record and its metadata (1.4) |
| `pokeldn.app.bank.TradeSession(offers, folder=)` | snapshot ordered offer dictionaries for one run, including offers without a Bank ID (1.4) |
| `pokeldn.app.bank.TradeSession.advance(count)` | apply a cumulative confirmed-trade count; -> `.completed`, the greatest count processed; repeated or older counts leave records alone (1.4) |
| `pokeldn.app.received.trades_done(line)` | the cumulative count in a launcher's `[done] trade N complete` line, or `None` (1.4) |

A launcher run, from the app or from `python -m pokeldn`, is one process: stop it with SIGINT to its
own PID, then SIGTERM after 15 s. Never match launchers by name (`pkill -f`): that also ends a run
another program started.

## Bank integrations (1.4)

An external Python frontend uses `pokeldn.app.bank`, the same module the desktop Bank uses. It owns
its offer queue and process lifecycle. The app's settings, queue helpers and Bank metadata files
remain internal. Conversion uses the existing PKHeX helper; source installations build it with
`dotnet build -c Release services/pkhex`.

`Entry` exposes `id`, `path`, `game`, `species_id`, `shiny`, `summary`, `legal`, `tracker`, `created`,
`origin` and `home_tracker`. `game` is a catalog key; `created` is Unix time in seconds; `path` is
the native record. `home_tracker` is `empty`, `made` or an empty string, as described in
[The HOME tracker setting](gui.md#the-home-tracker-setting).

`Imported` exposes `name`, `save` and `pokemon`, plus `count(state)`. Each `ImportedPokemon` has
`where`, `species`, `species_id`, `shiny`, `state`, `game` and `detail`. The state is `banked`,
`already` or `refused`. Refusals are per record: one refused Pokemon does not prevent other records
in a save from being imported. `trainers` maps game keys to trainer dictionaries with `ot`, `tid`,
`sid`, `language` and `gender`, as the Pokemon builder takes. Imports remember records already
imported, including those subsequently traded away.

`destinations` returns a dictionary keyed by game, each value containing `ok`, `reason` and
`home_tracker`. `offer` returns a dictionary with `file`, `summary`, `species`, `shiny`, `legal`,
`encounter`, `moves`, `report`, `home_tracker` and `bank`. `file` names the prepared native record;
`bank` is the source entry ID. Preparing an offer leaves the original Bank record in place.
Keep the offer file until its run has ended, and pass it to the launcher's `--offer-file` argument.
Run a banked offer without `--fresh-pid` so its identity is preserved. The desktop command builder
handles this automatically; `python -m pokeldn TOOL` assembles defaults and does not receive the
Bank offer dictionary, so a frontend launching Bank trades uses the catalog tool's script directly.

```python
from pokeldn.app import bank, received

trainer = {"ot": "ASH", "tid": 1111, "sid": 2222, "language": 2, "gender": 0}
games = ("frlg", "lgpe", "swsh", "bdsp", "pla", "sv", "za")
result = bank.import_file("main", {game: trainer for game in games}, folder="tradebox-bank")
entry = next(iter(bank.entries(folder="tradebox-bank")), None)
if entry is None:
    raise ValueError("No Pokemon available in the Bank.")
routes = bank.destinations(entry, trainer)
if not routes["swsh"]["ok"]:
    raise ValueError(routes["swsh"]["reason"])
offer = bank.offer(entry, "swsh", trainer)
session = bank.TradeSession([offer], folder="tradebox-bank")

def on_launcher_line(line):
    count = received.trades_done(line)
    if count is not None:
        session.advance(count)
```

Create one `TradeSession` per run with the exact offer order, including built offers without a
`bank` key. Feed it confirmed completion counts, never a process exit code or a queued-trade count.
An unsuccessful or stopped run leaves uncompleted records in the Bank. A cumulative count can skip
intermediate messages; generated trades beyond the snapshotted offers are counted without removing
additional records. `advance` rejects a negative or non-integer count with `ValueError`. Its progress
advances after each successful removal, so an `OSError` can be retried with the same count.

File access errors raise `OSError`; PKHeX failures and refused conversions or edits raise
`pokeldn.pokemon.BuilderError`. `deposit` takes inspection data from `pokeldn.pokemon.SERVICE.check`
and performs no additional
legality check; user-supplied saves and Pokemon files enter through `import_file`.
Methods with `folder` accept a path or use `library()` by default. `data`, `edit`, `destinations` and
`offer` use the path carried by `Entry`. Set `POKELDN_DATA` before importing pokeldn to isolate the
helper's output and the frontend's other application files too.

Bank operations are synchronous. Run PKHeX work outside a frontend's UI thread. One writer owns a
Bank folder at a time; simultaneous imports, edits and trades from separate apps are unsupported.
Use a separate folder for TradeBox when the desktop app is active. External queues discard a
completed offer themselves; `TradeSession` changes the Bank only.

"""Plugins (pokeldn.plugins): a folder plugin's tool runs through the app's own child-process path,
its radio carries the LDN calls, and a broken or unwanted plugin adds nothing."""
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import trio

from pokeldn import plugins
from pokeldn.app import paths

ROOT = Path(__file__).resolve().parents[1]

TOOL_PLUGIN = '''
from pokeldn.plugins import Field, Tool

def register(api):
    api.add_tool("frlg", Tool("example-echo", "Echo", "echo.py", "Writes its arguments.", ("Nothing to press.",),
                              fields=(Field("--word", "Word", default="hello"),),
                              fixed=("--out", "echo.json", "--keys-file", "{keys}")))
'''
ECHO = '''
import argparse, json, sys

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--word")
    parser.add_argument("--extra")
    parser.add_argument("--keys-file")
    return parser

if __name__ == "__main__":
    args = build_parser().parse_args()
    json.dump(sys.argv[1:], open(args.out, "w"))
'''
RADIO_PLUGIN = '''
import contextlib
from ldn import wlan

SEEN = []

class FakeFactory:
    pass

def install(arg, log):
    SEEN.append(arg)
    @contextlib.asynccontextmanager
    async def factory():
        yield FakeFactory()
    wlan.set_factory(factory)

def register(api):
    api.add_radio("fake", install, "Fake radio")
'''


def make(base: Path, name: str, source: str, api: int = 1, **files) -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "plugin.toml").write_text(f'id = "{name}"\nname = "{name.title()}"\napi = {api}\n')
    (folder / "plugin.py").write_text(textwrap.dedent(source))
    for filename, text in files.items():
        (folder / filename.replace("_", ".")).write_text(textwrap.dedent(text))
    return folder


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(paths, "DATA", data)
    monkeypatch.delenv("POKELDN_PLUGINS", raising=False)
    monkeypatch.delenv("POKELDN_RADIO", raising=False)
    plugins._reset()
    from ldn import wlan
    yield data
    plugins._reset()
    wlan.set_factory(None)


def test_a_folder_plugin_tool_runs_through_the_cli_child_path(tmp_path):
    folder = make(tmp_path / "elsewhere", "echo", TOOL_PLUGIN, echo_py=ECHO)
    env = dict(os.environ, POKELDN_PLUGINS=str(folder), POKELDN_DATA=str(tmp_path / "data"), PYTHONPATH=str(ROOT))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings.json").write_text(json.dumps({"keys": "~/Switch keys/prod.keys"}))
    run = lambda *a: subprocess.run([sys.executable, "-m", "pokeldn", *a], cwd=tmp_path, env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    listed = run("--list")
    assert "example-echo" in listed.stdout and "FireRed & LeafGreen: Echo" in listed.stdout
    assert "echo                 Echo, API 1.0: loaded" in run("--plugins").stdout
    done = run("example-echo", "--", "--extra", "1")
    assert done.returncode == 0, done.stderr
    assert json.loads((tmp_path / "echo.json").read_text()) == [
        "--out", "echo.json", "--keys-file", os.path.expanduser("~/Switch keys/prod.keys"), "--word", "hello",
        "--extra", "1"]


def test_a_plugin_radio_carries_the_ldn_calls(isolated, tmp_path, monkeypatch):
    folder = make(tmp_path, "fakeradio", RADIO_PLUGIN)
    monkeypatch.setenv("POKELDN_PLUGINS", str(folder))
    monkeypatch.setenv("POKELDN_RADIO", "fake:port-7")
    from ldn import wlan
    from pokeldn.ldn import transport

    async def factory_type():
        async with wlan.create_factory() as factory:
            return type(factory).__name__

    assert trio.run(factory_type) == "FakeFactory"
    assert sys.modules["pokeldn_plugin_fakeradio"].SEEN == ["port-7"]
    assert transport.board_radio()                       # no iw, no vif cleanup
    assert transport.find_ap_phy(log=lambda _: None) == "fake"


def test_an_unknown_radio_is_refused_before_any_ldn_call(isolated, monkeypatch):
    monkeypatch.setenv("POKELDN_RADIO", "nothing:x")
    from ldn import wlan

    async def open_factory():
        async with wlan.create_factory():
            pass

    with pytest.raises(RuntimeError, match="names no radio"):
        trio.run(open_factory)


def test_a_plugin_toml_that_does_not_parse_runs_no_code(isolated, tmp_path, monkeypatch):
    folder = make(tmp_path, "badtoml", "raise SystemExit('imported')")
    (folder / "plugin.toml").write_text('id = "badtoml"\napi = \n')
    monkeypatch.setenv("POKELDN_PLUGINS", str(folder))
    [plugin] = plugins.load()
    assert plugin.error.startswith("plugin.toml:") and not plugin.loaded


def test_a_plugin_in_the_data_folder_loads_only_once_enabled(isolated):
    make(isolated / "plugins", "echo", TOOL_PLUGIN, echo_py=ECHO)
    assert [p.id for p in plugins.discover()] == ["echo"]
    assert plugins.load() == []
    assert "example-echo" not in {t.key for g in plugins.games() for t in g.tools}
    (isolated / "settings.json").write_text(json.dumps({"plugins": ["echo"]}))
    plugins._reset()
    tool = next(t for g in plugins.games() if g.key == "frlg" for t in g.tools if t.key == "example-echo")
    assert tool.script == str(isolated / "plugins" / "echo" / "echo.py")


@pytest.mark.parametrize("source, api, error", [
    (TOOL_PLUGIN, 2, "needs plugin API 2.0"),
    (TOOL_PLUGIN, f'"{plugins.API_VERSION}.{plugins.API_LEVEL + 1}"',
     f"needs plugin API {plugins.API_VERSION}.{plugins.API_LEVEL + 1}"),
    (TOOL_PLUGIN.replace('"example-echo"', '"frlg-trade-host"'), 1, "already taken"),
    (TOOL_PLUGIN.replace('add_tool("frlg"', 'add_tool("snes"'), 1, "no game 'snes'"),
    (RADIO_PLUGIN.replace('"fake"', '"esp32"'), 1, "already taken"),
    (RADIO_PLUGIN + "\n    raise ValueError('half done')\n", 1, "half done"),
    (TOOL_PLUGIN + "\n    raise SystemExit(3)\n", 1, "SystemExit: 3"),
], ids=["api-major", "api-level", "tool-key-taken", "unknown-game", "radio-taken", "raises-after-a-radio", "exits"])
def test_a_broken_plugin_keeps_its_error_and_adds_nothing(isolated, tmp_path, monkeypatch, source, api, error):
    broken = make(tmp_path, "broken", source, api=api)
    good = make(tmp_path, "good", TOOL_PLUGIN.replace("example-echo", "good-echo"))
    monkeypatch.setenv("POKELDN_PLUGINS", os.pathsep.join(map(str, (broken, good))))
    state = {p.id: p for p in plugins.load()}
    assert error in state["broken"].error and not state["broken"].loaded
    assert state["good"].loaded
    keys = {t.key for g in plugins.games() for t in g.tools}
    assert "good-echo" in keys and "example-echo" not in keys
    assert plugins.radios() == []


KIT = ROOT / "examples" / "plugins" / "test_kit"
KIT_VERSION = re.search(r'^version = "(.+)"', (KIT / "plugin.toml").read_text(), re.M)[1]
HELLO = ROOT / "examples" / "plugins" / "hello"


def zipped(path: Path, files: dict, links: tuple = ()) -> Path:
    import stat
    import zipfile
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return path


GOOD_TOML = 'id = "ok"\nname = "Ok"\napi = 1\n'


@pytest.mark.parametrize("files, links, error", [
    ({"plugin.py": ""}, (), "no plugin.toml"),
    ({"plugin.toml": GOOD_TOML, "plugin.py": "", "../evil.py": ""}, (), "unsafe path"),
    ({"plugin.toml": GOOD_TOML, "plugin.py": ""}, ("link.py",), "unsafe path"),
    ({"plugin.toml": GOOD_TOML.replace("api = 1", "api = 2"), "plugin.py": ""}, (), "plugin API 2"),
    ({"plugin.toml": GOOD_TOML.replace('"ok"', '"../Up"'), "plugin.py": ""}, (), "needs an id"),
    ({"plugin.toml": GOOD_TOML}, (), "no plugin.py"),
    ({"a/plugin.toml": GOOD_TOML, "a/plugin.py": "", "b/plugin.toml": GOOD_TOML}, (), "several plugins"),
    ({"a/plugin.toml": GOOD_TOML, "a/plugin.py": "", "stray.txt": ""}, (), "at the top"),
], ids=["no-toml", "traversal", "symlink", "api", "bad-id", "no-module", "two-plugins", "stray-file"])
def test_a_package_that_is_not_a_safe_plugin_is_refused_before_anything_runs(tmp_path, files, links, error):
    from pokeldn.app import plugin_store
    with pytest.raises(plugin_store.PackageError, match=error):
        plugin_store.read(str(zipped(tmp_path / "x.pokeplugin", files, links)))


@pytest.mark.parametrize("example", [KIT, HELLO], ids=["test_kit", "hello"])
def test_every_example_packs_into_an_installable_package(tmp_path, example):
    from pokeldn.app import plugin_store
    package = plugin_store.pack(str(example), str(tmp_path / "x.pokeplugin"))
    assert plugins.compatibility(package.api) == ("ok", "") and package.version and package.author


def test_the_hello_example_greets_through_the_cli(tmp_path):
    env = dict(os.environ, POKELDN_PLUGINS=str(HELLO), POKELDN_DATA=str(tmp_path / "data"), PYTHONPATH=str(ROOT))
    run = subprocess.run([sys.executable, "-m", "pokeldn", "hello-greet", "--", "--greeting", "Bonjour"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert "Bonjour, POKELDN! This line comes from a plugin." in run.stdout, run.stdout + run.stderr


def test_a_file_that_is_not_a_zip_is_refused(tmp_path):
    from pokeldn.app import plugin_store
    (tmp_path / "x.pokeplugin").write_text("hello")
    with pytest.raises(plugin_store.PackageError, match="not a plugin package"):
        plugin_store.read(str(tmp_path / "x.pokeplugin"))


def test_the_test_kit_installs_from_its_package_and_passes_its_self_test(isolated, tmp_path):
    """The kit packed as a user receives it, installed and turned on the way the Plugins page does, then its
    self-test run through the CLI child path with nothing but the data folder pointing at it."""
    from pokeldn.app import plugin_store
    package = plugin_store.pack(str(KIT), str(tmp_path / "test-kit.pokeplugin"))
    assert (package.id, plugin_store.compare(package, plugin_store.installed("test-kit"))) == ("test-kit", "install")
    target = plugin_store.install(package)
    assert plugin_store.consented(plugins._read_folder(target))
    (isolated / "settings.json").write_text(json.dumps({"plugins": ["test-kit"]}))
    games = {g.key: g for g in plugins.reload() and plugins.games()}
    assert [t.key for t in games["test-kit"].tools] == ["test-kit-selftest", "test-kit-session", "test-kit-fail"]
    assert "test-kit-hello" in {t.key for t in games["frlg"].tools}
    assert plugins.owner("test-kit-hello").name == "Plugin Test Kit" and plugins.owner("frlg-gift") is None
    env = dict(os.environ, POKELDN_DATA=str(isolated), PYTHONPATH=str(ROOT))
    env.pop("POKELDN_PLUGINS", None)
    run = subprocess.run([sys.executable, "-m", "pokeldn", "test-kit-selftest"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    assert "13 of 13 checks passed." in run.stdout, run.stdout + run.stderr
    from pokeldn import panel
    from pokeldn.app import panels
    for line in run.stdout.splitlines():
        if line.startswith(panel.PREFIX):
            assert panels.apply("test-kit", panel.read(line)), line
    kit = plugins.owner("test-kit-selftest")
    kept = panels.load("test-kit")
    card, note = kept["cards"]["self-test"], kept["notes"]["self-test.txt"]
    assert (card["tone"], card["lines"][0], card["chips"]) == (
        "ok", ["Result", "13 of 13 checks passed"], [["API", f"{plugins.API_VERSION}.{plugins.API_LEVEL}"]])
    assert panels.image(kit, card["image"]) == panels.image(kit, note["image"]) == str(
        (isolated / "plugin-data/test-kit/icon.png").resolve())
    assert (note["state"], panels.sort(kit)) == ("ok", "name")      # plugin.toml's library_sort
    plugin_store.remove("test-kit")
    assert panels.load("test-kit")["cards"] == {}


def test_an_update_replaces_the_files_and_remove_deletes_only_the_apps_own(isolated, tmp_path):
    from pokeldn.app import plugin_store
    source = tmp_path / "src"
    shutil_copy(KIT, source)
    (source / "old.txt").write_text("from 1.0.0")
    plugin_store.install(plugin_store.pack(str(source), str(tmp_path / "a.pokeplugin")))
    (source / "old.txt").unlink()
    (source / "plugin.toml").write_text((source / "plugin.toml").read_text().replace(KIT_VERSION, "5.2.0"))
    (plugins.data_folder("test-kit") / "runs.txt").parent.mkdir(parents=True)
    (plugins.data_folder("test-kit") / "runs.txt").write_text("4")
    newer = plugin_store.pack(str(source), str(tmp_path / "b.pokeplugin"))
    assert plugin_store.compare(newer, plugin_store.installed("test-kit")) == "update"
    target = plugin_store.install(newer)
    assert not (target / "old.txt").exists() and plugin_store.installed("test-kit").version == "5.2.0"
    assert plugin_store.compare(plugin_store.read(str(tmp_path / "a.pokeplugin")),
                                plugin_store.installed("test-kit")) == "downgrade"
    assert sorted(p.name for p in plugins.folder().iterdir()) == ["test-kit"]     # no staging left behind
    with pytest.raises(plugin_store.PackageError):
        plugin_store.remove("..")
    plugin_store.remove("test-kit")
    assert not target.exists() and (plugins.data_folder("test-kit") / "runs.txt").read_text() == "4"
    plugin_store.install(newer)
    plugin_store.remove("test-kit", data=True)
    assert not plugins.data_folder("test-kit").exists()


def shutil_copy(src: Path, dst: Path) -> None:
    import shutil
    shutil.copytree(src, dst)


@pytest.mark.parametrize("before", [None, "other-author"], ids=["first-install", "other-author"])
def test_the_install_screen_installs_nothing_until_the_risks_are_accepted(isolated, tmp_path, monkeypatch, before):
    pytest.importorskip("flet")
    import flet as ft
    from types import SimpleNamespace
    from gui.views import plugins as view
    from pokeldn.app import plugin_store
    from pokeldn.app.settings import Settings
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    if before:      # a copy signed by one author is installed; the new file is signed by another
        old = plugin_store.pack(str(KIT), str(tmp_path / "old.pokeplugin"),
                                plugin_store.signing_key(str(tmp_path / "a.pem"), create=True))
        plugin_store.install(old)
    package = plugin_store.pack(str(KIT), str(tmp_path / "test-kit.pokeplugin"),
                                plugin_store.signing_key(str(tmp_path / "b.pem"), create=True))
    assert plugin_store.trust(package) == ("changed" if before else "new")
    shown, closed = [], []
    settings = Settings()
    from pokeldn.app import settings as settings_module
    monkeypatch.setattr(settings_module, "PATH", isolated / "settings.json")
    app = SimpleNamespace(settings=settings, navigate=lambda *a, **k: None, ui=lambda f: f(), plugin_updates={},
                          plugin_update_listeners=[],
                          page=SimpleNamespace(show_dialog=shown.append, pop_dialog=lambda: closed.append(1)))
    page = view.PluginsView(app)
    page.open_file(package.source)

    def walk(control):
        yield control
        for name in ("content", "controls", "actions"):
            child = getattr(control, name, None)
            for c in (child if isinstance(child, list) else [child] if child is not None else []):
                yield from walk(c)
    controls = list(walk(shown[0]))
    action = "Reinstall" if before else "Install"
    install = next(c for c in controls if isinstance(c, ft.Button) and c.content == action)
    ticks = [c for c in controls if isinstance(c, ft.Container) and c.on_click and any(
        isinstance(x, ft.Text) and x.value.startswith(("I understand", "I know this file")) for x in walk(c))]
    assert len(ticks) == (2 if before else 1)
    for tick in ticks:
        assert install.disabled
        install.on_click(None)
        assert plugin_store.known_key("test-kit") != package.key
        tick.on_click(None)
    assert not install.disabled
    install.on_click(None)
    assert plugin_store.known_key("test-kit") == package.key
    assert settings.plugins == ["test-kit"] and "test-kit" in {p.id for p in plugins.load() if p.loaded}


def test_a_future_pokeldn_runs_a_deprecated_api_and_refuses_a_dropped_one(isolated, tmp_path, monkeypatch):
    monkeypatch.setattr(plugins, "API_VERSION", 3)
    monkeypatch.setattr(plugins, "API_LEVEL", 0)
    monkeypatch.setattr(plugins, "API_OLDEST", 2)
    monkeypatch.setattr(plugins, "DEPRECATED", {2: "pokeldn 9.0"})
    old = make(tmp_path, "old", TOOL_PLUGIN, api=1)
    kept = make(tmp_path, "kept", TOOL_PLUGIN.replace("example-echo", "kept-echo"), api='"2.4"')
    monkeypatch.setenv("POKELDN_PLUGINS", os.pathsep.join(map(str, (old, kept))))
    state = {p.id: p for p in plugins.load()}
    assert "no longer supports" in state["old"].error and not state["old"].loaded
    assert state["kept"].loaded and plugins.compatibility(state["kept"].api)[0] == "deprecated"
    from pokeldn.app import plugin_store
    with pytest.raises(plugin_store.PackageError, match="no longer supports"):
        plugin_store.pack(str(old), str(tmp_path / "old.pokeplugin"))
    assert plugin_store.pack(str(kept), str(tmp_path / "kept.pokeplugin")).api == (2, 4)


def test_a_plugin_that_kills_the_app_while_starting_is_turned_off_at_the_next_start(isolated, tmp_path):
    from types import SimpleNamespace
    killer = make(tmp_path, "killer", "import os\n\ndef register(api):\n    os._exit(9)\n")
    code = ("import sys; from pokeldn import plugins; from pokeldn.app import paths; "
            f"paths.DATA = __import__('pathlib').Path({str(isolated)!r}); plugins.watch = True; plugins.load()")
    env = dict(os.environ, POKELDN_PLUGINS=str(killer), PYTHONPATH=str(ROOT))
    assert subprocess.run([sys.executable, "-c", code], env=env, timeout=60).returncode == 9
    saved = []
    app = SimpleNamespace(settings=SimpleNamespace(plugins=["killer", "other"], save=lambda: saved.append(1)))
    try:
        assert plugins.turn_off_the_one_that_stopped(app.settings) == "killer"
        assert app.settings.plugins == ["other"] and saved
        assert plugins.turn_off_the_one_that_stopped(app.settings) == ""        # named once
    finally:
        plugins.watch = False


VANDAL = '''
import os, shutil, subprocess, sys
from pathlib import Path

from pokeldn.plugins import Tool

def attempt(label, fn):
    try:
        fn()
        print(label, "ALLOWED")
    except PermissionError:
        print(label, "STOPPED")

def register(api):
    v = os.environ["VICTIM"]                      # a folder in the test's own temporary directory
    gone = os.path.join(v, "no-such-file")         # the commands name a missing file: harmless if they ran
    attempt("rmtree", lambda: shutil.rmtree(v))
    attempt("remove", lambda: os.remove(os.path.join(v, "a.txt")))
    attempt("unlink", lambda: Path(v, "a.txt").unlink())
    attempt("overwrite", lambda: open(os.path.join(v, "a.txt"), "w").close())
    attempt("append", lambda: Path(v, "a.txt").open("a").close())
    attempt("move-away", lambda: os.replace(os.path.join(v, "a.txt"), api.data / "a.txt"))
    attempt("move-over", lambda: os.replace(api.folder / "plugin.toml", os.path.join(v, "a.txt")))
    attempt("rm", lambda: subprocess.run(["rm", "-f", gone]))
    attempt("shell", lambda: subprocess.run(f"echo hi && rm -f {gone}", shell=True))
    attempt("system", lambda: os.system(f"rm -f {gone}"))
    attempt("sudo", lambda: subprocess.run(["/usr/bin/sudo", "-n", "true"]))
    attempt("new-file", lambda: open(os.path.join(v, f"new-{os.getpid()}.txt"), "w").close())
    attempt("own-data", lambda: ((api.data / "x").write_text("1"), (api.data / "x").write_text("2"), (api.data / "x").unlink()))
    attempt("own-folder", lambda: ((api.folder / "y").write_text("1"), (api.folder / "y").unlink()))
    attempt("python", lambda: subprocess.run([sys.executable, "-c", "pass"], check=True))
    api.add_tool("frlg", Tool("vandal-wipe", "Wipe", "wipe.py", "", ()))
'''
WIPE = '''
import os

def build_parser():
    import argparse
    return argparse.ArgumentParser()

if __name__ == "__main__":
    try:
        os.remove(os.path.join(os.environ["VICTIM"], "a.txt"))
        print("script ALLOWED")
    except PermissionError as error:
        print("script STOPPED", error)
'''


def test_the_guardrails_stop_a_plugin_deleting_or_overwriting_the_players_files(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "a.txt").write_text("precious")
    (tmp_path / "tmp").mkdir()
    folder = make(tmp_path, "vandal", VANDAL, wipe_py=WIPE)
    env = dict(os.environ, POKELDN_PLUGINS=str(folder), POKELDN_DATA=str(tmp_path / "data"), PYTHONPATH=str(ROOT),
               VICTIM=str(victim), TMPDIR=str(tmp_path / "tmp"), TEMP=str(tmp_path / "tmp"), TMP=str(tmp_path / "tmp"))
    loaded = subprocess.run([sys.executable, "-m", "pokeldn", "--plugins"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=60)
    verdicts = dict(line.split() for line in loaded.stdout.splitlines() if line.endswith(("ALLOWED", "STOPPED")))
    stopped = ("rmtree", "remove", "unlink", "overwrite", "append", "move-away", "move-over", "rm", "shell",
               "system", "sudo")
    assert verdicts == {**dict.fromkeys(stopped, "STOPPED"),
                        **dict.fromkeys(("new-file", "own-data", "own-folder", "python"), "ALLOWED")}, loaded.stdout
    assert "vandal               Vandal, API 1.0: loaded" in loaded.stdout
    script = subprocess.run([sys.executable, "-m", "pokeldn", "vandal-wipe"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=60)
    assert "script STOPPED pokeldn's plugin guardrails stopped the deletion of" in script.stdout, script.stdout + script.stderr
    assert (victim / "a.txt").read_text() == "precious"


@pytest.mark.parametrize("files, findings", [
    ({"plugin.py": "def register(api):\n    pass\n"}, []),
    ({"plugin.py": VANDAL}, ["Starts other programs", "Deletes files"]),
    ({"plugin.py": "import socket, ctypes\nexec(__import__('base64').b64decode('cGFzcw=='))\nK = 'prod.keys'\n",
      "helper.dylib": "\0"},
     ["Uses the internet or the network", "Calls native code directly, which the guardrails cannot watch",
      "Runs code it builds while running, which this check cannot read", "Names your Switch keys file",
      "Ships 1 compiled file this check cannot read"]),
    ({"plugin.py": "def register(api):\n  ret urn\n"}, ["Has Python files pokeldn cannot read"]),
], ids=["clean", "deletes-and-runs", "network-native-hidden-keys", "unreadable"])
def test_the_install_screen_lists_what_a_plugins_code_does(tmp_path, files, findings):
    from pokeldn.app import plugin_store
    package = plugin_store.read(str(zipped(tmp_path / "x.pokeplugin", {"plugin.toml": GOOD_TOML, **files})))
    assert package.findings == findings



def test_a_signed_package_names_its_author_and_any_change_to_a_file_refuses_it(isolated, tmp_path):
    import zipfile
    from pokeldn.app import plugin_store
    key = plugin_store.signing_key(str(tmp_path / "author.pem"), create=True)
    signed = plugin_store.pack(str(KIT), str(tmp_path / "signed.pokeplugin"), key)
    assert signed.key and plugin_store.trust(signed) == "new"
    assert plugin_store.signing_key(str(tmp_path / "author.pem")).public_key() == key.public_key()
    plugin_store.install(signed)
    assert plugin_store.trust(plugin_store.read(signed.source)) == "same"
    assert plugin_store.trust(plugin_store.pack(str(KIT), str(tmp_path / "plain.pokeplugin"))) == "dropped"
    for change in ("edit", "add", "remove", "version"):
        out = tmp_path / f"{change}.pokeplugin"
        with zipfile.ZipFile(signed.source) as source, zipfile.ZipFile(out, "w") as copy:
            for name in source.namelist():
                data = source.read(name)
                if name == "hello.py" and change == "edit":
                    data += b"\nimport shutil\n"
                if name == "plugin.toml" and change == "version":
                    data = data.replace(f'version = "{KIT_VERSION}"'.encode(), b'version = "9.0.0"')
                if not (name == "fail.py" and change == "remove"):
                    copy.writestr(name, data)
            if change == "add":
                copy.writestr("extra.py", "import os\n")
        with pytest.raises(plugin_store.PackageError, match="changed after its author signed it"):
            plugin_store.read(str(out))


def test_an_update_address_offers_the_newer_version_and_the_download_installs_through_the_same_checks(
        isolated, tmp_path):
    import http.server
    import threading
    from pokeldn.app import plugin_store, plugin_updates
    key = plugin_store.signing_key(str(tmp_path / "author.pem"), create=True)
    source = tmp_path / "src"
    shutil_copy(KIT, source)
    toml = (source / "plugin.toml").read_text()
    served = tmp_path / "served"
    served.mkdir()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(served), **k)

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        (source / "plugin.toml").write_text(toml + f'updates = "{base}/latest.json"\n')
        plugin_store.install(plugin_store.pack(str(source), str(tmp_path / "old.pokeplugin"), key))
        (source / "plugin.toml").write_text(toml.replace(KIT_VERSION, "5.3.0") + f'updates = "{base}/latest.json"\n')
        plugin_store.pack(str(source), str(served / "kit.pokeplugin"), key)
        (served / "latest.json").write_text(json.dumps({"version": "5.3.0", "url": f"{base}/kit.pokeplugin"}))
        found = plugin_updates.check(plugins.discover())
        assert found["test-kit"].version == "5.3.0"
        package = plugin_store.read(str(plugin_updates.download(found["test-kit"], tmp_path / "dl")))
        assert (package.version, plugin_store.trust(package)) == ("5.3.0", "same")
        (served / "latest.json").write_text(json.dumps({"version": KIT_VERSION, "url": f"{base}/kit.pokeplugin"}))
        assert plugin_updates.check(plugins.discover()) == {}
    finally:
        server.shutdown()
        server.server_close()
    assert not plugin_updates.allowed("http://example.org/x.json") and plugin_updates.allowed("https://example.org/x")


def test_a_github_repository_address_reads_its_latest_release(monkeypatch):
    from pokeldn.app import plugin_updates, update
    asked = []
    reply = {"tag_name": "v1.3.0", "html_url": "https://github.com/someone/kit/releases/tag/v1.3.0",
             "assets": [{"name": "SHA256SUMS", "browser_download_url": "https://github.com/x/SHA256SUMS"},
                        {"name": "kit-1.3.0.pokeplugin", "browser_download_url": "https://github.com/x/kit.pokeplugin"}]}
    monkeypatch.setattr(update, "github_json", lambda url, **k: asked.append(url) or reply)
    assert plugin_updates.latest("https://github.com/someone/kit.git") == (
        "1.3.0", "https://github.com/x/kit.pokeplugin", reply["html_url"])
    assert asked == ["https://api.github.com/repos/someone/kit/releases/latest"]


@pytest.mark.parametrize("name", ["..\\outside.py", "a/..\\outside.py", "a\\..\\outside.py",
                                  "C:/outside.py", "CON.py", "a./x.py", "a /x.py"])
def test_plugin_paths_are_safe_on_windows_as_well_as_posix(tmp_path, name):
    from pokeldn.app import plugin_store
    package = zipped(tmp_path / "x.pokeplugin", {"plugin.toml": GOOD_TOML, "plugin.py": "", name: ""})
    with pytest.raises(plugin_store.PackageError, match="unsafe path"):
        plugin_store.read(str(package))


def test_plugin_install_rechecks_a_package_changed_after_preview(isolated, tmp_path):
    from pokeldn.app import plugin_store
    path = zipped(tmp_path / "x.pokeplugin", {"plugin.toml": GOOD_TOML, "plugin.py": ""})
    preview = plugin_store.read(str(path))
    zipped(path, {"plugin.toml": GOOD_TOML, "plugin.py": "raise SystemExit('changed')"})
    with pytest.raises(plugin_store.PackageError, match="changed"):
        plugin_store.install(preview)
    assert not (plugins.folder() / "ok").exists()


def test_plugin_version_metadata_never_becomes_a_download_path(tmp_path, monkeypatch):
    import io
    from pokeldn.app import plugin_updates, update
    monkeypatch.setattr(update, "_open", lambda *a: io.BytesIO(b"package"))
    metadata = plugin_updates.Available("ok", "/../../outside", "https://example.org/ok.pokeplugin")
    downloaded = plugin_updates.download(metadata, tmp_path / "download")
    assert downloaded.parent == tmp_path / "download" and downloaded.read_bytes() == b"package"


def test_plugin_source_review_is_bounded_before_parsing(tmp_path):
    from pokeldn.app import plugin_store
    path = zipped(tmp_path / "x.pokeplugin", {"plugin.toml": GOOD_TOML,
                                             "plugin.py": "#" * (plugin_store.MAX_SOURCE + 1)})
    with pytest.raises(plugin_store.PackageError, match="source"):
        plugin_store.read(str(path))


def test_a_source_lists_plugins_that_install_update_and_stay_when_the_source_goes(isolated, tmp_path, monkeypatch):
    """A followed listing on a local server: the built-in source comes first, a download that is not
    the file the listing hashes is refused, an install records its source, a newer listing offers the
    update, and removing the source keeps the plugin."""
    import http.server
    import threading
    from pokeldn.app import plugin_sources, plugin_store, plugin_updates
    from scripts import plugin_source
    key = plugin_store.signing_key(str(tmp_path / "author.pem"), create=True)
    source = tmp_path / "src"
    shutil_copy(KIT, source)
    toml = (source / "plugin.toml").read_text()
    served = tmp_path / "served"
    served.mkdir()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(served), **k)

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    listing = served / plugin_sources.FILE

    def publish(version):
        (source / "plugin.toml").write_text(toml.replace(KIT_VERSION, version))
        path = served / f"test-kit-{version}.pokeplugin"
        plugin_store.pack(str(source), str(path), key)
        assert plugin_source.main([str(path), "-o", str(listing), "--name", "Local",
                                   "--download", base + "/{file}"]) == 0
    try:
        publish(KIT_VERSION)
        assert plugin_sources.followed() == [plugin_sources.BUILT_IN]
        added = plugin_sources.add(base + "/")
        assert (added.url, added.name, [e.id for e in added.entries]) == (f"{base}/{plugin_sources.FILE}", "Local", ["test-kit"])
        assert plugin_sources.followed() == [plugin_sources.BUILT_IN, added.url]
        with pytest.raises(plugin_sources.SourceError, match="already"):
            plugin_sources.add(added.url)
        entry = added.entry("test-kit")
        assert plugin_sources.state(entry, None) == "install"
        offer = plugin_updates.Available(entry.id, entry.version, entry.download, "", entry.sha256, added.url)
        wrong = plugin_updates.Available(entry.id, entry.version, entry.download, "", "0" * 64, added.url)
        with pytest.raises(OSError, match="not the file its source lists"):
            plugin_updates.download(wrong, tmp_path / "dl")
        assert not list((tmp_path / "dl").iterdir())
        package = plugin_store.read(str(plugin_updates.download(offer, tmp_path / "dl")))
        plugin_store.install(package, added.url)
        kit = plugin_store.installed("test-kit")
        assert plugin_store.origin(kit) == added.url and plugin_sources.state(entry, kit) == "installed"
        assert plugin_updates.check(plugins.discover(), [plugin_sources.fetch(added.url)]) == {}
        publish("5.3.0")
        publish("5.2.0")       # an older package never replaces a newer listing
        fresh = plugin_sources.fetch(added.url)
        assert [e.version for e in fresh.entries] == ["5.3.0"]
        found = plugin_updates.check(plugins.discover(), [fresh])
        assert (found["test-kit"].version, found["test-kit"].source) == ("5.3.0", added.url)
        update = plugin_store.read(str(plugin_updates.download(found["test-kit"], tmp_path / "dl")))
        assert (update.version, plugin_store.trust(update)) == ("5.3.0", "same")
        server.shutdown()
        server.server_close()
        offline = plugin_sources.fetch(added.url)       # the cached listing still shows
        assert offline.error and [e.version for e in offline.entries] == ["5.3.0"]
        plugin_sources.remove(added.url)
        assert plugin_sources.followed() == [plugin_sources.BUILT_IN]
        assert plugin_store.installed("test-kit") is not None
        with pytest.raises(plugin_sources.SourceError):
            plugin_sources.remove(plugin_sources.BUILT_IN)
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("typed, feed", [
    ("Decryptu/pokeldn-decrypt-plugins",
     "https://raw.githubusercontent.com/Decryptu/pokeldn-decrypt-plugins/HEAD/pokeldn-source.json"),
    ("https://github.com/Decryptu/pokeldn-decrypt-plugins.git",
     "https://raw.githubusercontent.com/Decryptu/pokeldn-decrypt-plugins/HEAD/pokeldn-source.json"),
    ("https://github.com/Decryptu/pokeldn-decrypt-plugins/tree/main",
     "https://raw.githubusercontent.com/Decryptu/pokeldn-decrypt-plugins/HEAD/pokeldn-source.json"),
    ("https://example.org/plugins/", "https://example.org/plugins/pokeldn-source.json"),
    ("https://example.org/list.json", "https://example.org/list.json"),
    ("http://example.org/list.json", None), ("file:///etc/passwd", None), ("", None),
])
def test_a_typed_source_resolves_to_its_listing(typed, feed):
    from pokeldn.app import plugin_sources
    if feed is None:
        with pytest.raises(plugin_sources.SourceError):
            plugin_sources.resolve(typed)
    else:
        assert plugin_sources.resolve(typed) == feed


def test_a_listing_keeps_only_entries_it_can_check():
    from pokeldn.app import plugin_sources
    good = {"id": "a", "version": "1.0", "download": "https://x/a.pokeplugin", "sha256": "a" * 64, "api": "1.6"}
    listing = {"schema": 1, "plugins": [
        good, dict(good),                                         # a duplicate id
        {**good, "id": "b", "sha256": ""}, {**good, "id": "c", "download": "http://x/c"},
        {**good, "id": "../d"}, {**good, "id": "e", "version": "latest"}, "junk",
        {**good, "id": "f", "icon": "javascript:alert(1)", "api": "9.0"}]}
    source = plugin_sources.parse("https://x/l.json", json.dumps(listing).encode())
    assert [e.id for e in source.entries] == ["a", "f"]
    assert source.entry("f").icon == "" and plugin_sources.state(source.entry("f"), None) == "incompatible"
    with pytest.raises(plugin_sources.SourceError, match="another pokeldn"):
        plugin_sources.parse("https://x", json.dumps({**listing, "schema": 2}).encode())


def test_the_browse_tab_installs_a_listed_plugin_through_the_risk_screen(isolated, tmp_path, monkeypatch):
    pytest.importorskip("flet")
    import hashlib
    import time
    import flet as ft
    from types import SimpleNamespace
    from gui.views import plugins as view
    from pokeldn.app import plugin_sources, plugin_store, plugin_updates
    from pokeldn.app.settings import Settings
    from pokeldn.app import settings as settings_module
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    monkeypatch.setattr(settings_module, "PATH", isolated / "settings.json")
    package = plugin_store.pack(str(KIT), str(tmp_path / "kit.pokeplugin"))
    digest = hashlib.sha256(Path(package.source).read_bytes()).hexdigest()
    listed = plugin_sources.parse("https://x/l.json", json.dumps({"schema": 1, "name": "Mine", "plugins": [
        {"id": "test-kit", "name": "Kit", "version": package.version, "api": "1.0",
         "download": "https://x/kit.pokeplugin", "sha256": digest}]}).encode())
    asked = []
    monkeypatch.setattr(plugin_updates, "download", lambda a, folder: asked.append(a) or Path(package.source))
    monkeypatch.setattr(plugin_sources, "followed", lambda: [listed.url])
    shown = []
    app = SimpleNamespace(settings=Settings(), navigate=lambda *a, **k: None, ui=lambda f: f(), plugin_updates={},
                          plugin_update_listeners=[], plugin_sources=[listed],
                          page=SimpleNamespace(show_dialog=shown.append, pop_dialog=lambda: None))
    page = view.PluginsView(app)
    page._tab("browse")

    def walk(control):
        yield control
        for name in ("content", "controls", "actions"):
            child = getattr(control, name, None)
            for c in (child if isinstance(child, list) else [child] if child is not None else []):
                yield from walk(c)
    install = next(c for c in walk(page.column) if isinstance(c, ft.Button) and c.content == "Install")
    install.on_click(None)
    for _ in range(100):
        if shown:
            break
        time.sleep(0.05)
    assert asked[0].sha256 == digest and asked[0].source == listed.url
    controls = list(walk(shown[0]))
    tick = next(c for c in controls if isinstance(c, ft.Container) and c.on_click and any(
        isinstance(x, ft.Text) and x.value.startswith("I understand") for x in walk(c)))
    tick.on_click(None)
    next(c for c in controls if isinstance(c, ft.Button) and c.content == "Install").on_click(None)
    assert plugin_store.origin(plugin_store.installed("test-kit")) == listed.url
    page.render()
    assert not any(isinstance(c, ft.Button) and c.content == "Install" for c in walk(page.column))


SAVER = '''
from pokeldn.plugins import Tool

def register(api):
    api.add_tool("frlg", Tool("saver-save", "Save", "save.py", "", ()))
'''
SAVE = '''
import os, shutil, sys
from pathlib import Path
from pokeldn import plugins

def build_parser():
    import argparse
    return argparse.ArgumentParser()

def attempt(label, fn):
    try:
        fn()
        print(label, "ALLOWED")
    except PermissionError:
        print(label, "STOPPED")

if __name__ == "__main__":
    lib = plugins.library_folder("saver")
    (lib / "stale.nsp.part").write_bytes(b"half")
    (lib / ".staging").mkdir(exist_ok=True)
    (lib / "update.nsp.part").write_bytes(b"whole")
    attempt("finish", lambda: os.replace(lib / "update.nsp.part", lib / "update.nsp"))
    attempt("clear-part", lambda: (lib / "stale.nsp.part").unlink())
    attempt("clear-staging", lambda: shutil.rmtree(lib / ".staging"))
    attempt("rename", lambda: os.rename(lib / "update.nsp", lib / "Game 1.1.0.nsp"))
    attempt("delete", lambda: (lib / "Game 1.1.0.nsp").unlink())
    attempt("other-library", lambda: (plugins.library_path("Other") / "x.nsp").unlink())
'''


def test_a_plugins_library_takes_its_whole_file_workflow_and_nothing_beside_it(tmp_path):
    """Writing a partial file, replacing it with the whole one, clearing what a crash left, renaming and
    deleting are allowed in the plugin's library; another folder beside it stays guarded."""
    folder = make(tmp_path, "saver", SAVER, save_py=SAVE)
    (folder / "plugin.toml").write_text('id = "saver"\nname = "Saver"\napi = "1.7"\nlibrary = "Switch updates"\n')
    data = tmp_path / "data"
    (data / "Other").mkdir(parents=True)
    (data / "Other" / "x.nsp").write_text("someone else's")
    (tmp_path / "tmp").mkdir()
    env = dict(os.environ, POKELDN_PLUGINS=str(folder), POKELDN_DATA=str(data), PYTHONPATH=str(ROOT),
               TMPDIR=str(tmp_path / "tmp"), TEMP=str(tmp_path / "tmp"), TMP=str(tmp_path / "tmp"))
    run = subprocess.run([sys.executable, "-m", "pokeldn", "saver-save"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60)
    verdicts = dict(line.split() for line in run.stdout.splitlines() if line.endswith(("ALLOWED", "STOPPED")))
    assert verdicts == {**dict.fromkeys(("finish", "clear-part", "clear-staging", "rename", "delete"), "ALLOWED"),
                        "other-library": "STOPPED"}, run.stdout + run.stderr
    assert sorted(p.name for p in (data / "Switch updates").iterdir()) == []
    assert (data / "Other" / "x.nsp").read_text() == "someone else's"


def test_a_library_sorts_names_as_a_player_reads_them(tmp_path):
    """The Switch updates plugin's names: each game's updates group together in version order, system
    updates in version order, case aside; -desc reverses, size and date order by their own field."""
    from pokeldn.app import library
    names = ["System update 23.0.1.zip", "game [0100A][v131072](1.0.2).nsp", "Game [0100A][v65536](1.0.1).nsp",
             "System update 20.5.0.zip", "Game [0100B][v65536](1.0.1).nsp"]
    for i, name in enumerate(names):
        (tmp_path / name).write_bytes(b"x" * (10 - i))
        os.utime(tmp_path / name, (1_000_000 + i, 1_000_000 + i))
    wanted = ["Game [0100A][v65536](1.0.1).nsp", "game [0100A][v131072](1.0.2).nsp", "Game [0100B][v65536](1.0.1).nsp",
              "System update 20.5.0.zip", "System update 23.0.1.zip"]
    assert [e.name for e in library.entries(tmp_path, "name")] == wanted
    assert [e.name for e in library.entries(tmp_path, "name-desc")] == wanted[::-1]
    assert [e.name for e in library.entries(tmp_path, "date-desc")] == names[::-1]
    assert [e.name for e in library.entries(tmp_path, "size")] == names[::-1]
    with pytest.raises(ValueError):
        library.entries(tmp_path, "random")


def test_the_players_sort_wins_over_plugin_tomls_and_a_bad_one_refuses_the_plugin(isolated, tmp_path, monkeypatch):
    from pokeldn.app import panels
    good = make(tmp_path, "sorted", "def register(api):\n    pass\n")
    bad = make(tmp_path, "unsorted", "def register(api):\n    pass\n")
    for path, sort in ((good, "name-desc"), (bad, "newest")):
        (path / "plugin.toml").write_text((path / "plugin.toml").read_text() + f'library = "{path.name}"\nlibrary_sort = "{sort}"\n')
    monkeypatch.setenv("POKELDN_PLUGINS", os.pathsep.join(map(str, (good, bad))))
    loaded = {p.id: p for p in plugins.load()}
    assert "library_sort is one of" in loaded["unsorted"].error
    assert panels.sort(loaded["sorted"]) == "name-desc"
    panels.set_sort("sorted", "size")
    assert panels.sort(loaded["sorted"]) == "size"
    with pytest.raises(ValueError):
        panels.set_sort("sorted", "random")


def test_status_cards_keep_to_their_limits_and_draw_only_the_plugins_own_images(isolated, tmp_path, monkeypatch, capsys):
    """What a plugin prints is untrusted: an image outside its folders, a renamed file posing as a PNG, a ninth
    card and a line past the limits are kept out; a line the app reads is the one the call printed."""
    from pokeldn import panel
    from pokeldn.app import panels
    folder = make(tmp_path, "carded", "def register(api):\n    pass\n")
    monkeypatch.setenv("POKELDN_PLUGINS", str(folder))
    (plugin,) = plugins.load()
    data = plugins.data_folder("carded")
    data.mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\n" + bytes(32)
    (data / "icon.png").write_bytes(png)
    (data / "fake.png").write_bytes(b"GIF89a" + bytes(32))
    (tmp_path / "outside.png").write_bytes(png)
    (data / "big.png").write_bytes(png + bytes(panel.IMAGE_BYTES))
    for name in ("icon.png", "fake.png", "big.png"):
        panel.show("c", "Card", image=data / name)
    panel.show("c", "Card", image=data / ".." / ".." / ".." / "outside.png")
    shown = [panel.read(line) for line in capsys.readouterr().out.splitlines()]
    assert [panels.image(plugin, s["image"]) for s in shown] == [str((data / "icon.png").resolve()), None, None, None]

    for n in range(panel.CARDS):
        assert panels.apply("carded", panel._card(f"card-{n}", "Card"))
    assert not panels.apply("carded", panel._card("one-more", "Card"))
    assert not panels.apply("carded", panel._card("card-0", "Card"))       # the same card again
    assert panels.apply("carded", {"id": "card-0", "clear": True})
    assert panels.apply("carded", panel._note("a.nsp", "bad", "Signature refused"))
    assert panels.load("carded")["notes"]["a.nsp"]["state"] == "bad"

    for bad in ('{"id":"../x","title":"T"}', '{"id":"x","title":"T","tone":"pink"}',
                '{"id":"x","title":"T","lines":' + json.dumps(["l"] * 13) + '}',
                '{"id":"x","title":"' + "T" * 81 + '"}', '{"file":"../x.nsp"}', '[1]', 'not json'):
        assert panel.read(panel.PREFIX + bad) is None, bad
    with pytest.raises(ValueError):
        panel.show("x", "T", image="icon.gif")
    with pytest.raises(ValueError):
        panel.annotate("x.nsp", state="great")


@pytest.mark.parametrize("name, refused", [
    ("Switch updates", ""), ("NSP_backups-2.0", ""), ("saves", "pokeldn's own"), ("Bank", "pokeldn's own"),
    ("Received", "pokeldn's own"), ("NUL", "device name"), ("com1.backup", "device name"), ("../Bank", "folder name"),
    ("a/b", "folder name"), (".hidden", "folder name"), ("ends.", "folder name"), ("x" * 41, "folder name"), (3, "folder name"),
])
def test_a_library_is_a_plain_folder_name_no_feature_of_pokeldn_uses(name, refused):
    if not refused:
        assert plugins.library_name(name) == name
        return
    with pytest.raises(ValueError, match=refused):
        plugins.library_name(name)


def test_a_package_with_a_bad_library_is_refused_and_two_plugins_never_share_one(isolated, tmp_path, monkeypatch):
    from pokeldn.app import plugin_store
    with pytest.raises(plugin_store.PackageError, match="pokeldn's own"):
        plugin_store.read(str(zipped(tmp_path / "x.pokeplugin", {"plugin.toml": GOOD_TOML + 'library = "Saves"\n',
                                                                 "plugin.py": ""})))
    good = plugin_store.read(str(zipped(tmp_path / "y.pokeplugin", {
        "plugin.toml": GOOD_TOML + 'library = "Updates"\n', "plugin.py": "def register(api):\n    pass\n"})))
    assert good.library == "Updates"
    first = make(tmp_path, "first", "def register(api):\n    api.library\n")
    second = make(tmp_path, "second", "def register(api):\n    pass\n")
    for path in (first, second):
        (path / "plugin.toml").write_text((path / "plugin.toml").read_text() + 'library = "updates"\n')
    monkeypatch.setenv("POKELDN_PLUGINS", os.pathsep.join(map(str, (first, second))))
    loaded = {p.id: p for p in plugins.load()}
    assert loaded["first"].loaded and plugins.library_folder("first").is_dir()
    assert loaded["second"].error == "its library 'updates' is already the plugin 'first''s"


def test_the_library_lists_names_and_copies_files_and_survives_the_plugins_removal(isolated, tmp_path):
    from pokeldn.app import library, plugin_store
    lib = tmp_path / "lib"
    lib.mkdir()
    for name, age in (("old.nsp", 30), ("new.nsp", 10), (".x.part", 0), ("y.nsp.part", 0)):
        (lib / name).write_text(name)
        os.utime(lib / name, (1_000_000 - age, 1_000_000 - age))
    (lib / "folder").mkdir()
    assert [e.name for e in library.entries(lib)] == ["new.nsp", "old.nsp"]
    newest = library.entries(lib)[0]
    assert library.rename(lib, newest, "  Game   1.2.0 ").name == "Game 1.2.0.nsp"   # the extension stays
    for bad in ("", ".hidden", "a/b", "c:d"):
        with pytest.raises(ValueError):
            library.rename(lib, library.entries(lib)[0], bad)
    with pytest.raises(FileExistsError):
        library.rename(lib, library.entries(lib)[0], "old.nsp")
    with pytest.raises(ValueError):
        library.delete(lib, library.Entry(tmp_path / "outside.nsp", 0, 0))
    source = tmp_path / "old.nsp"
    source.write_text("dropped")
    assert library.add(lib, str(source)).name == "old (2).nsp"
    assert sorted(e.name for e in library.entries(lib)) == ["Game 1.2.0.nsp", "old (2).nsp", "old.nsp"]
    assert not [p for p in lib.iterdir() if p.name.startswith(".") and p.name != ".x.part"]   # no copy left half
    plugin_store.install(plugin_store.pack(str(KIT), str(tmp_path / "kit.pokeplugin")))
    kept = plugins.library_folder("test-kit")
    (kept / "backup.nsp").write_text("hours of work")
    plugin_store.remove("test-kit", data=True)
    assert (kept / "backup.nsp").read_text() == "hours of work"

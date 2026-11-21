"""The real app, started as a player starts it, with every page opened. Unit tests build views from stand-ins;
a clash only a real view has (0.66.1: GamesView's own `sprites` dict over the sprite pool) stopped every
packaged app at launch and passed them all."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("flet")

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = r'''
import sys
import flet as ft
sys.path.insert(0, sys.argv[1])
built = []
for kind in (ft.Row, ft.Column):
    def init(self, *a, _init=kind.__init__, **k):
        _init(self, *a, **k)
        built.append(self)
    kind.__init__ = init


class Page:
    """Answers every attribute and call the way a page with nothing on it does."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = Page()
        object.__setattr__(self, name, value)
        return value

    def __call__(self, *a, **k):
        return None

    def __bool__(self):
        return False


from gui import main
apps = []


class App(main.App):
    def __init__(self, page):
        super().__init__(page)
        apps.append(self)


main.App = App
page = Page(width=1440.0, height=900.0, web=False, platform=ft.PagePlatform.MACOS, controls=[], overlay=[],
            services=[])
main.main(page)
for key, *_ in (*main.PAGES, main.PLUGINS, main.SETTINGS):
    apps[0].navigate(key)
    print("opened", key)
from pokeldn.app.catalog import GAMES
apps[0].ui = lambda fn: fn()
ft.BaseControl.update = lambda self: None      # off the page: every tool's form is only built
for game in GAMES:
    for tool in game.tools:
        if not tool.unavailable:
            apps[0].navigate("games", game=game.key, tool=tool.key)
# Flutter's Wrap takes no Expanded child; a release build draws the error as a grey box (0.66.10).
for box in built:
    if box.wrap:
        for child in box.controls:
            if getattr(child, "expand", None):
                name = getattr(child, "hint_text", None) or getattr(child, "label", None)
                print("expand in wrap", type(box).__name__, type(child).__name__, name, file=sys.stderr)
'''


def test_the_app_starts_and_opens_every_page(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData"),
           "LOCALAPPDATA": str(home / "Local"), "XDG_DATA_HOME": str(home / ".local"),
           "XDG_CONFIG_HOME": str(home / ".config")}
    done = subprocess.run([sys.executable, "-c", LAUNCH, str(ROOT)], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "expand in wrap" not in done.stderr, done.stderr[-3000:]
    assert "opened settings" in done.stdout and "opened gts" in done.stdout, done.stdout

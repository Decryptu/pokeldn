from types import SimpleNamespace

import pytest

pytest.importorskip("flet")

from gui.views import pokemon
from gui.views.games import GamesView
from gui.views.pokemon import OfferOptions, OfferQueue
from pokeldn.app.catalog import Field, offer


def test_saved_pokemon_offer_keeps_its_card_description():
    field = offer()
    view = SimpleNamespace(values={field.key: {"file": "pikachu.pk3", "species": 25, "legal": True}})
    assert GamesView.description(view, field) == field.help


def test_choice_card_includes_help_for_the_saved_selection():
    field = Field("--mode", "Mode", "choice", help="Choose a mode.",
                  choice_help=(("trade", "Trades Pokemon."),))
    view = SimpleNamespace(values={field.key: "trade"})
    assert GamesView.description(view, field) == "Choose a mode. Trades Pokemon."


def test_options_the_new_species_cannot_have_are_dropped_before_a_build():
    picker = SimpleNamespace(value={"species": 132, "options": {"ability": 31, "ball": 2, "gender": 1,
                                                                 "held_item": 236, "nature": 3, "form": 2}})
    options = OfferOptions(picker)
    options._form({"natures": [], "abilities": [{"id": 7, "name": "Limber"}], "gendered": False,
                   "forms": [{"id": 0, "name": ""}], "move_names": [],
                   "balls": [{"id": 2, "name": "Ultra Ball"}], "held": [{"id": 236, "name": "Light Ball"}],
                   "effort": {"kind": "evs", "max": 252, "total": 510}})
    assert picker.value["options"] == {"ball": 2, "held_item": 236, "nature": 3}


FOUND = {"natures": [], "abilities": [], "gendered": True, "balls": [], "held": [], "forms": [], "move_names": []}


@pytest.mark.parametrize("effort, values, refused", [
    ({"kind": "evs", "max": 252, "total": 510}, {"hp": 252, "atk": 252, "spe": 8}, True),
    ({"kind": "evs", "max": 252, "total": 510}, {"hp": 252, "atk": 252, "spe": 6}, False),
    ({"kind": "avs", "max": 200}, {s: 200 for s in ("hp", "atk", "def", "spa", "spd", "spe")}, False),
])
def test_effort_over_the_games_total_is_refused_before_the_builder_is_asked(effort, values, refused):
    options = OfferOptions(SimpleNamespace(value={"options": {"effort": dict(values)}}))
    options._form({**FOUND, "effort": effort})
    assert bool(options.problem()) == refused


def test_a_queue_keeps_each_trades_pokemon_in_order_through_add_and_remove(monkeypatch):
    class Picker:
        def __init__(self, app, game, value, on_change, version=""):
            self.on_change, self.control = on_change, SimpleNamespace()
    monkeypatch.setattr(pokemon, "PokemonPicker", Picker)
    saved = []
    queue = OfferQueue(None, "sv", {"file": "a.pk9"}, 3, saved.append)
    queue.control = SimpleNamespace(update=lambda: None)
    assert not queue.slots[0]["header"].visible
    for name in ("b.pk9", "c.pk9"):
        queue._add(None)
        queue.slots[-1]["picker"].on_change({"file": name})
    assert saved[-1] == [{"file": "a.pk9"}, {"file": "b.pk9"}, {"file": "c.pk9"}]
    assert queue.add_button.disabled
    queue._add(None)
    assert len(queue.slots) == 3
    queue._remove(queue.slots[1])
    assert saved[-1] == [{"file": "a.pk9"}, {"file": "c.pk9"}]
    assert [s["title"].value for s in queue.slots] == ["Trade 1", "Trade 2"]
    assert not queue.add_button.disabled
    queue._remove(queue.slots[0])
    queue._remove(queue.slots[0])
    assert saved[-1] == [{"file": "c.pk9"}]


from pokeldn.app.catalog import GAMES  # noqa: E402

TOOLS = [tool for game in GAMES for tool in game.tools if not tool.unavailable]


@pytest.mark.parametrize("tool", TOOLS, ids=[t.key for t in TOOLS])
def test_every_tools_all_options_tab_renders_with_the_hidden_settings_first(tool):
    """A repeatable flag's default is a list; the tab must still draw every row."""
    import flet as ft
    view = SimpleNamespace(tool=tool, search="", values={}, extra={}, flag_list=ft.Column())
    view.flag_row = lambda flag: GamesView.flag_row(view, flag)
    GamesView._fill_flags(view)
    rows = view.flag_list.controls
    assert not (len(rows) == 1 and str(getattr(rows[0], "value", "")).startswith("Could not"))
    hidden = {f.label for f in tool.fields if f.hidden}
    assert {row.content.controls[0].controls[0].controls[0].value for row in rows[:len(hidden)]} == hidden


from gui import board as board_module  # noqa: E402
from gui.app import NO_FIRMWARE, App  # noqa: E402
from gui.views.games import SessionPanel  # noqa: E402

UART = board_module.Port("/dev/cu.usbserial-1", "WCH CH343", "1")
NATIVE = board_module.Port("/dev/cu.usbmodem1", "Espressif USB (S3, C3, C6)", "2", native=True)
CURRENT = board_module.Identity("02:00:00:00:00:01", "02:00:00:00:00:02", 3, "pokeldn-radio", 1, "1.0.0")
OLD = board_module.Identity("02:00:00:00:00:01", "02:00:00:00:00:02", 3, "pokeldn-radio", 0)


def _app(port, ident, chip=""):
    app = App.__new__(App)
    app.settings = SimpleNamespace(radio_port="", keys="")
    app.identities = {port.device: ident} if ident is not None else {}
    app.chips = {port.device: chip} if chip else {}
    return app


@pytest.mark.parametrize("port, ident, chip, state", [
    (UART, NO_FIRMWARE, "ESP32-S3", "wrong-port"),   # flashed through the UART socket: it never answers there
    (UART, NO_FIRMWARE, "ESP32-C3", "wrong-port"),
    (NATIVE, NO_FIRMWARE, "ESP32-S3", "flash"),      # the right socket: reset or flash, never "move the cable"
    (UART, NO_FIRMWARE, "ESP32", "flash"),           # a classic ESP32 talks over its bridge
    (UART, NO_FIRMWARE, "", "flash"),                # nothing flashed this session: no guess about the socket
    (UART, OLD, "", "flash"),
    (NATIVE, CURRENT, "ESP32-S3", "ready"),
    (UART, None, "", "checking"),
])
def test_the_board_status_names_the_fix_for_what_the_board_answered(port, ident, chip, state):
    assert _app(port, ident, chip).board_status([port]).state == state


def test_a_board_unplugged_is_checked_again_when_it_returns():
    app = _app(UART, CURRENT)
    assert app.board_status([]).state == "missing"
    assert app.board_status([UART]).state == "checking"


@pytest.mark.parametrize("ident, keys, offer, blocked", [
    (CURRENT, True, True, False),
    (None, True, True, False),          # still checking: the check holds the port, Start follows it
    (NO_FIRMWARE, True, True, False),   # a warning; a mistaken check must not lock the player out
    (CURRENT, False, True, True),
    (CURRENT, True, False, True),
])
def test_start_waits_for_keys_and_a_built_offer_but_not_for_a_doubtful_board(tmp_path, monkeypatch, ident,
                                                                              keys, offer, blocked):
    monkeypatch.setattr(board_module, "ports", lambda: [UART])
    app = _app(UART, ident)
    keyfile = tmp_path / "prod.keys"
    if keys:
        keyfile.write_text("")
    app.settings.keys = str(keyfile)
    pk = tmp_path / "offer.pk9"
    pk.write_bytes(b"")
    tool = next(t for t in TOOLS if t.key == "sv-host")
    values = {"--trade-offer": {"file": str(pk)}} if offer else {}
    panel = SimpleNamespace(app=app, tool=tool, games=SimpleNamespace(values=values))
    states = [state for state, *_ in SessionPanel.checklist(panel)]
    assert ("block" in states) == blocked
    assert ("ok" in states) and len(states) >= 2


def test_a_board_that_never_answers_on_a_bridge_is_named_by_its_rom_and_sent_to_the_usb_socket(monkeypatch):
    """No flash this session: the ROM bootloader still says S3, which never answers on a UART socket."""
    import time
    monkeypatch.setattr(board_module, "ports", lambda: [UART])
    monkeypatch.setattr(board_module, "identify", lambda port, blink=False: (_ for _ in ()).throw(
        RuntimeError("no answer")))
    monkeypatch.setattr(board_module, "detect_chip", lambda port: "ESP32-S3")
    app = _app(UART, None)
    app.process, app.board_busy, app.board_listeners = None, False, []
    app.ui = lambda fn: fn()
    app.check_board(UART.device)
    deadline = time.monotonic() + 5
    while app.board_busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app.board_status([UART]).state == "wrong-port"


def _release_server(routes: dict):
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.mark.parametrize("tamper", [False, True])
def test_the_released_firmware_lands_only_when_every_image_matches_its_checksum(tmp_path, monkeypatch, tamper):
    import hashlib
    import json
    names = ["pokeldn-radio.bin", "pokeldn-radio-s3.bin", "pokeldn-radio-c3.bin"]
    images = {n: n.encode() * 100 for n in names}
    sums = "".join(f"{hashlib.sha256(images[n]).hexdigest()}  {n}\n" for n in names).encode()
    routes = {f"/{n}": images[n] for n in names} | {"/SHA256SUMS": sums}
    if tamper:
        routes["/pokeldn-radio-s3.bin"] = b"swapped in transit"
    server, base = _release_server(routes)
    asset = lambda n: {"name": n, "browser_download_url": f"{base}/{n}"}   # noqa: E731
    every = [asset(n) for n in [*names, "SHA256SUMS"]]
    routes["/releases"] = json.dumps([{"tag_name": "v9.0.0", "draft": True, "assets": every},
                                      {"tag_name": "v8.0.0", "assets": [asset("pokeldn-macos-arm64.zip")]},
                                      {"tag_name": "v7.0.0", "assets": every}]).encode()
    monkeypatch.setattr(board_module, "RELEASES", f"{base}/releases")
    try:
        if tamper:
            with pytest.raises(OSError, match="SHA256SUMS"):
                board_module.download_firmware(lambda line: None, str(tmp_path))
            assert list(tmp_path.iterdir()) == []
        else:
            assert board_module.download_firmware(lambda line: None, str(tmp_path)) == "v7.0.0"
            assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == images
    finally:
        server.shutdown()
        server.server_close()


def test_a_pokemon_file_shows_its_own_species_and_shininess(monkeypatch):
    import asyncio
    monkeypatch.setattr(pokemon.builder.SERVICE, "species", lambda game: [{"id": 25, "name": "Pikachu"}])
    monkeypatch.setattr(pokemon.builder.SERVICE, "import_file", lambda game, path: {
        "file": path, "species": "Charizard", "species_id": 6, "level": 50, "shiny": True, "legal": True,
        "encounter": "", "moves": [], "report": ""})

    async def pick_files(**_):
        return [SimpleNamespace(path="charizard.pk8")]
    app = SimpleNamespace(settings=SimpleNamespace(sprites=False), ui=lambda fn: None,
                          picker=SimpleNamespace(pick_files=pick_files))
    saved = []
    picker = pokemon.PokemonPicker(app, "swsh", {"species": 25}, saved.append)
    picker.species.options = [object()]
    picker.control = SimpleNamespace(update=lambda: None)
    shown = []
    picker.sprite.show = lambda species, shiny, update=True: shown.append((species, shiny))
    asyncio.run(picker._use_file(None))
    assert shown == [(6, True)]
    assert (saved[-1]["species"], saved[-1]["shiny"], picker.species.value, picker.shiny.value) == (6, True, "6", True)


@pytest.mark.parametrize("key", ["frlg-gift", "swsh-gift"])
def test_the_gift_builder_renders_every_mode_and_kind_and_exports_what_it_shows(tmp_path, monkeypatch, key):
    import asyncio
    from gui.views import gifts as view_module
    from pokeldn import gifts
    from pokeldn.app import gift_builder
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.settings import Settings

    monkeypatch.setattr(pokemon.NamePicker, "_load", lambda self: None)
    tool = next(tool for game in GAMES for tool in game.tools if tool.key == key)
    field = next(field for field in tool.fields if field.kind == "builder")
    path = tmp_path / "gift.pokegift"

    async def save_file(**kwargs):
        assert kwargs["allowed_extensions"] == ["pokegift"]
        return str(path)

    view = SimpleNamespace(tool=tool, values={}, extra={},
        app=SimpleNamespace(settings=Settings(), picker=SimpleNamespace(save_file=save_file), ui=lambda f: None))
    view.set_value = lambda field, value, rebuild=False: view.values.__setitem__(field.key, value)
    module = gift_builder.module(gift_builder.GAMES[key])
    builder = view_module.GiftBuilder(view, field)
    for mode, *_ in gift_builder.MODES:
        builder.value["mode"] = mode
        assert len(builder.cards()) == 2
    builder.value["mode"] = "build"
    for kind, *_ in module.KINDS:
        builder.state["kind"] = kind
        builder.cards()
        assert builder.status.color != view_module.t.RED or kind == "code", builder.status.value
    builder.state["kind"] = module.KINDS[0][0]
    builder.commit = lambda rebuild=False: None
    for control in (builder.status, builder.save_button):
        control.update = lambda: None
    asyncio.run(builder._save(None))
    assert gifts.dumps(gifts.load(path)) == gifts.dumps(module.compile(builder.state))


def test_a_worker_answering_after_its_picker_left_the_page_is_dropped():
    """Picking another tool before the species list loads replaces the picker the worker answers."""
    import asyncio
    import flet as ft
    from gui.views.widgets import on_ui
    ran = []

    def run_task(task):
        asyncio.run(task())
    page = SimpleNamespace(run_task=run_task)
    on_ui(page, lambda: (ran.append(1), ft.Column().update()))
    assert ran == [1]
    with pytest.raises(RuntimeError):
        on_ui(page, lambda: (_ for _ in ()).throw(RuntimeError("another failure")))


def test_start_on_another_tool_stops_the_running_session_then_starts(tmp_path, monkeypatch):
    """One board, one session: the running launcher leaves the network before the next opens the port."""
    from gui.views import games
    from pokeldn.app.settings import Settings
    events = []

    class Process:
        def __init__(self, argv, cwd, env, on_line, on_exit):
            self.script, self.on_exit, self.running = argv[1], on_exit, True
            events.append(("start", self.script))

        def stop(self):
            events.append(("stop", self.script))
            self.running = False
            self.on_exit(0)

    class FakeApp:
        process, process_label = None, ""
        settings = Settings(keys=str(tmp_path / "prod.keys"), received=str(tmp_path), board_trace=False)

        @property
        def busy(self):
            return bool(self.process and self.process.running)

        def radio_port(self):
            return "/dev/cu.usbserial-1"

        def ui(self, fn):
            fn()
    (tmp_path / "prod.keys").write_text("")
    monkeypatch.setattr(games.runner, "Process", Process)
    monkeypatch.setattr(games.runner, "base_env", lambda *a: {})
    monkeypatch.setattr(games, "SESSION", tmp_path)
    monkeypatch.setattr(SessionPanel, "_tick", lambda self: None)
    first, second = (next(t for t in TOOLS if t.key == key) for key in ("swsh-join", "pla-host"))
    panel = SessionPanel.__new__(SessionPanel)
    panel.__dict__.update(app=FakeApp(), games=SimpleNamespace(values={}, extra={}, game=SimpleNamespace(
        name="game", key="swsh")), log=SimpleNamespace(add=lambda line: None, clear=lambda: None),
        received=SimpleNamespace(), run=None, running_tool=None, restart=False, stopping=False, traded=0)
    panel.set_status = panel.refresh = lambda *a, **k: None
    panel.tool = first
    panel._start(None)
    panel.tool = second
    panel._start(None)
    assert events == [("start", first.script), ("stop", first.script), ("start", second.script)]
    assert panel.running_tool is second and panel.app.process.running and not panel.restart


def test_the_link_code_slots_fill_in_order_and_give_the_host_its_scene(monkeypatch):
    """Three empty slots block Start; picks land in the slot clicked, then the next empty one, and the
    value is what bin/lgpe_host.py turns into the console's scene id."""
    from gui.views import pokemon as views
    from pokeldn.app import command
    from pokeldn.lgpe.session import scene_id
    monkeypatch.setattr(views, "Sprite", lambda app, species, shiny=False, size=0: SimpleNamespace(
        control=__import__("flet").Container()))
    tool = next(t for t in TOOLS if t.key == "lgpe-host")
    field = next(f for f in tool.fields if f.kind == "linkcode")
    values = {}
    assert "Pick three Pokemon for the link code." in command.problems(tool, values)
    picker = views.LinkCodePicker(SimpleNamespace(), command.value_of(field, values),
                                  lambda v: values.__setitem__(field.key, v))
    assert picker.picks == [None, None, None]
    picker._toggle(0)
    picker._choose(1)                       # Eevee in slot 1; slot 2 opens
    assert picker.open == 1
    picker._choose(9)
    picker._choose(0)
    assert picker.open is None
    assert values[field.key] == "eevee,diglett,pikachu"
    assert command.problems(tool, values) == []
    assert scene_id(values[field.key].split(",")) == 1901
    picker._toggle(1)
    picker._choose(4)                       # a filled slot is replaced, nothing else moves
    assert values[field.key] == "eevee,squirtle,pikachu"
    assert views.parse_code("evoli,taupiqueur,") == [1, 9, None]

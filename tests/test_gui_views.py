import os
import sys
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


class StubPicker:
    def __init__(self, app, game, value, on_change, version="", on_team=None, on_more=None, glow=None):
        self.on_change, self.on_team, self.on_more = on_change, on_team, on_more
        self.control, self.applied = SimpleNamespace(), None

    def _apply_set(self, found, notes):
        self.applied = found
        self.on_change({"species": found["species_id"]})

    def load(self, path):
        self.on_change({"species": 1, "file": path})


def stub_queue(value, limit, on_change):
    queue = OfferQueue(None, "sv", value, limit, on_change)
    queue.control = queue.rows = queue.footer = queue.count = SimpleNamespace(update=lambda: None)
    return queue


def test_a_pasted_team_fills_the_trades_after_its_picker_up_to_the_limit(monkeypatch):
    """An untouched trade after the picker is reused, a chosen one is kept, and the rest are counted."""
    monkeypatch.setattr(pokemon, "PokemonPicker", StubPicker)
    saved = []
    queue = stub_queue([{"species": 1}, {}, {"species": 4}], 4, saved.append)
    sets = [{"species_id": n, "notes": []} for n in (25, 133, 150)]
    message = queue.slots[0]["picker"].on_team(sets)
    assert saved[-1] == [{"species": 1}, {"species": 25}, {"species": 133}, {"species": 4}]
    assert [s["title"].value for s in queue.slots] == ["Trade 1", "Trade 2", "Trade 3", "Trade 4"]
    assert "trades 2, 3" in message and "1 did not fit" in message
    assert queue.add_box.disabled


def test_a_queue_keeps_each_trades_pokemon_in_order_through_add_and_remove(monkeypatch):
    monkeypatch.setattr(pokemon, "PokemonPicker", StubPicker)
    saved = []
    queue = stub_queue({"file": "a.pk9"}, 3, saved.append)
    assert not queue.slots[0]["header"].visible
    for name in ("b.pk9", "c.pk9"):
        queue._add(None)
        queue.slots[-1]["picker"].on_change({"file": name})
    assert saved[-1] == [{"file": "a.pk9"}, {"file": "b.pk9"}, {"file": "c.pk9"}]
    assert queue.add_box.disabled
    queue._add(None)
    assert len(queue.slots) == 3
    queue._remove(queue.slots[1])
    assert saved[-1] == [{"file": "a.pk9"}, {"file": "c.pk9"}]
    assert [s["title"].value for s in queue.slots] == ["Trade 1", "Trade 2"]
    assert not queue.add_box.disabled
    queue._remove(queue.slots[0])
    queue._remove(queue.slots[0])
    assert saved[-1] == [{"file": "c.pk9"}]


def test_files_dropped_on_a_trade_or_on_add_a_trade_fill_untouched_trades_then_new_ones(monkeypatch):
    """Files after the first on a trade go to the trades after it; on Add a trade they start at the
    untouched trades at the end. What does not fit is counted, never dropped silently."""
    monkeypatch.setattr(pokemon, "PokemonPicker", StubPicker)
    saved = []
    queue = stub_queue([{"species": 1}, {}, {"species": 4}], 5, saved.append)
    queue.slots[0]["picker"].on_more(["b.pk9"])
    assert [v.get("file") for v in saved[-1]] == [None, "b.pk9", None]
    queue._append(["c.pk9", "d.pk9", "e.pk9"])
    assert [v.get("file") for v in saved[-1]] == [None, "b.pk9", None, "c.pk9", "d.pk9"]
    assert queue.count.value.startswith("1 did not fit")

    queue = stub_queue([{"species": 1}, {}, {}], 6, saved.append)
    queue._append(["f.pk9"])
    assert [v.get("file") for v in saved[-1]] == [None, "f.pk9", None]


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
    app.hidden_bridges = []
    return app


@pytest.mark.parametrize("port, ident, chip, state", [
    (UART, NO_FIRMWARE, "ESP32-S3", "wrong-port"),   # flashed through the UART socket: it never answers there
    (UART, NO_FIRMWARE, "ESP32-C3", "wrong-port"),
    (UART, NO_FIRMWARE, "ESP32-C6", "wrong-port"),
    (NATIVE, NO_FIRMWARE, "ESP32-S3", "flash"),      # the right socket: reset or flash, never "move the cable"
    (UART, NO_FIRMWARE, "ESP32", "flash"),           # a classic ESP32 talks over its bridge
    (UART, NO_FIRMWARE, "", "flash"),                # nothing flashed this session: no guess about the socket
    (UART, OLD, "", "flash"),
    (NATIVE, CURRENT, "ESP32-S3", "ready"),
    (UART, None, "", "checking"),
])
def test_the_board_status_names_the_fix_for_what_the_board_answered(port, ident, chip, state):
    assert _app(port, ident, chip).board_status([port]).state == state


@pytest.mark.parametrize("platform", ["darwin", "win32"])   # Windows reads the bridges with no driver
def test_a_board_unplugged_is_checked_again_when_it_returns(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
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


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a POSIX user without root")
def test_a_port_the_user_may_not_open_names_the_group_not_a_busy_port(tmp_path, monkeypatch):
    """pyserial's own EACCES, from a node this user cannot open: on Linux that is a missing dialout
    group, which "another program holds the port" would send the player the wrong way."""
    import time
    node = tmp_path / "ttyUSB0"
    node.write_bytes(b"")
    node.chmod(0)
    denied = board_module.Port(str(node), "WCH CH340", "3")
    monkeypatch.setattr(board_module, "ports", lambda: [denied])
    monkeypatch.setattr(sys, "platform", "linux")
    app = _app(denied, None)
    app.process, app.board_busy, app.board_listeners = None, False, []
    app.ui = lambda fn: fn()
    app.check_board(denied.device)
    deadline = time.monotonic() + 5
    while app.board_busy and time.monotonic() < deadline:
        time.sleep(0.01)
    status = app.board_status([denied])
    assert status.state == "denied" and "usermod -aG" in status.detail


@pytest.mark.skipif(sys.platform == "win32", reason="a sysfs interface name carries ':', not a Windows file name")
@pytest.mark.parametrize("tty, title", [
    (None, "Board found without a serial port"),          # brltty took it: no tty under the interface
    ("ttyUSB0", "No board plugged in"),                    # usb-serial: <interface>/ttyUSB0
    ("tty/ttyACM0", "No board plugged in"),                # cdc-acm: <interface>/tty/ttyACM0
])
def test_a_ch340_on_usb_with_no_tty_names_brltty_on_linux(tmp_path, monkeypatch, tty, title):
    device = tmp_path / "1-1"
    (device / "1-1:1.0").mkdir(parents=True)
    (device / "idVendor").write_text("1a86\n")
    (device / "idProduct").write_text("7523\n")
    (tmp_path / "usb1").mkdir()                            # a root hub: no known ids
    (tmp_path / "usb1" / "idVendor").write_text("1d6b\n")
    (tmp_path / "usb1" / "idProduct").write_text("0002\n")
    if tty:
        (device / "1-1:1.0" / tty).mkdir(parents=True)
    real = board_module.bridges_without_port
    monkeypatch.setattr(board_module, "bridges_without_port", lambda: real(str(tmp_path)))
    monkeypatch.setattr(sys, "platform", "linux")
    status = _app(UART, None).board_status([])
    assert status.state == "missing" and status.title == title
    assert ("apt remove brltty" in status.detail) == (tty is None)


@pytest.mark.parametrize("devices, title, step", [
    ("USB\\VID_10C4&PID_EA60\\0001\r\n", "Board found without a driver", "silabser.inf"),
    ("USB\\VID_1A86&PID_7523\\5&2A1B&0&2\r\n", "Board found without a driver", "CH341SER.EXE"),
    ("USB\\VID_046D&PID_C52B\\6&3&0&1\r\n", "No board plugged in", None),   # a mouse receiver
    ("", "No board plugged in", None),
])
def test_a_bridge_with_no_driver_names_its_install_steps_on_windows(monkeypatch, devices, title, step):
    """A CP210x or CH340 with no Windows driver gets no COM port; Device Manager lists it with a
    problem code, and the status names the driver to install."""
    import subprocess
    calls = []

    def powershell(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, devices, "")

    app = _app(UART, None)
    app.hidden_bridges = board_module.bridges_without_driver(run=powershell)
    monkeypatch.setattr(sys, "platform", "win32")
    status = app.board_status([])
    assert calls[0][0] == "powershell" and "ConfigManagerErrorCode" in calls[0][-1]
    assert status.state == "missing" and status.title == title
    assert step is None or step in status.detail


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
@pytest.mark.parametrize("names", [   # a release from before the C6 image, and one carrying it
    ["pokeldn-radio.bin", "pokeldn-radio-s3.bin", "pokeldn-radio-c3.bin"],
    ["pokeldn-radio.bin", "pokeldn-radio-s3.bin", "pokeldn-radio-c3.bin", "pokeldn-radio-c6.bin"]])
def test_the_released_firmware_lands_only_when_every_image_matches_its_checksum(tmp_path, monkeypatch, tamper,
                                                                                names):
    import hashlib
    import json
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


@pytest.mark.parametrize("assembler", [True, False])   # a computer without the Arm toolchain sees the install hint
@pytest.mark.parametrize("key", ["frlg-gift", "swsh-gift"])
def test_the_gift_builder_renders_every_mode_and_kind_and_exports_what_it_shows(tmp_path, monkeypatch, key,
                                                                                assembler):
    import asyncio
    from gui.views import gifts as view_module
    if not assembler:
        monkeypatch.setattr(view_module.custom_code, "toolchain", lambda: None)
    from pokeldn import gifts
    from pokeldn.app import gift_builder
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.settings import Settings

    monkeypatch.setattr(pokemon.NamePicker, "_load", lambda self: None)
    # A Sword card draws its gender per build; the export and the compile below must draw alike.
    from pokeldn.swsh import gift_builder as swsh_builder
    monkeypatch.setattr(swsh_builder, "card_gender", lambda species, form=0: 0)
    tool = next(tool for game in GAMES for tool in game.tools if tool.key == key)
    field = next(field for field in tool.fields if field.kind == "builder")
    native = "wc8" if key == "swsh-gift" else "wc3"
    path = tmp_path / "gift.pokegift"

    async def save_file(**kwargs):
        assert kwargs["allowed_extensions"] == ["pokegift", native]
        return str(path)

    view = SimpleNamespace(tool=tool, values={}, extra={},
        app=SimpleNamespace(settings=Settings(), picker=SimpleNamespace(save_file=save_file), ui=lambda f: None,
                          page=SimpleNamespace(run_task=lambda *a: None)))
    view.set_value = lambda field, value, rebuild=False: view.values.__setitem__(field.key, value)
    module = gift_builder.module(gift_builder.GAMES[key])
    builder = view_module.GiftBuilder(view, field)

    async def select_native_build(gift):
        return next(iter(gift.variants))

    builder.select_native_build = select_native_build
    for mode, *_ in gift_builder.modes(gift_builder.GAMES[key]):
        builder.value["mode"] = mode
        assert len(builder.cards()) == 2
    if key == "swsh-gift":
        builder.value["mode"] = "event"
        for event in module.OFFICIAL.load():
            builder.value["event"] = event["key"]
            builder.cards()
            assert builder.status.color != view_module.t.RED, (event["key"], builder.status.value)
    builder.value["mode"] = "preset"
    for preset in module.PRESETS:
        builder.value["preset"] = preset.key
        builder.cards()
        for member in getattr(preset, "members", ()):   # every boost ticked: refused, still drawn
            builder.value["options"][preset.key]["on"].append(member.key)
            builder.cards()
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
    path = tmp_path / f"gift.{native}"                # the native file the extension names
    asyncio.run(builder._save(None))
    built = next(iter(module.compile(builder.state).variants.values())).data
    loaded = next(iter(gifts.load(path).variants.values())).data
    # A .wc3 carries the script padded to its 995-byte slot.
    assert {k: v.rstrip(b"\0") for k, v in loaded.items()} == {k: v.rstrip(b"\0") for k, v in built.items()}


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
    panel.__dict__.update(app=FakeApp(), games=SimpleNamespace(values={}, extra={}, visible=False, game=SimpleNamespace(
        name="game", key="swsh")), log=SimpleNamespace(add=lambda line: None, clear=lambda: None),
        received=SimpleNamespace(), transfer=SimpleNamespace(), partner=SimpleNamespace(), run=None,
        running_tool=None, restart=False, stopping=False, traded=0)
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


CODES = [(tool, f) for tool in TOOLS for f in tool.fields if f.kind == "code"]


@pytest.mark.parametrize("tool, field", CODES, ids=[f"{t.key}{f.flag}" for t, f in CODES])
def test_a_console_code_is_typed_box_by_box_and_only_a_whole_one_reaches_the_launcher(tool, field):
    """Each digit moves to the next box, a paste fills from where it lands, Backspace on an empty box
    clears the one before; a partial code blocks Start, the whole one parses as the launcher's flag."""
    from gui.views import widgets
    from pokeldn.app import command
    from pokeldn.app.introspect import parser_of
    from pokeldn.app.settings import Settings
    values = {f.key: {"file": "offer.bin"} for f in tool.fields if f.kind == "pokemon"}
    code = widgets.DigitCode(command.value_of(field, values), lambda v: values.__setitem__(field.key, v))
    assert code.value == field.default
    for n in range(8):                      # clear whatever the default put there
        code._typed(n, "")
    assert bool(command.problems(tool, values)) == bool(field.default)
    code._typed(0, "1")
    code._typed(code.at, "x2")              # a letter never lands
    assert code.at == 2 and values[field.key] == "12"
    assert command.problems(tool, values) == [f"{field.label}: all eight digits" +
                                              ("." if field.default else ", or none.")]
    code._typed(2, "x")
    assert values[field.key] == "12" and code.at == 2
    code._typed(2, "34 5-678")              # a pasted code keeps its digits only
    assert values[field.key] == "12345678" and code.at == 7
    assert command.problems(tool, values) == []
    args = command.build(tool, values, {}, Settings())
    assert args[args.index(field.flag) + 1] == "12345678"
    parser_of(tool.script).parse_args(args)
    code._typed(3, "")                      # a hole keeps the digits after it in their boxes
    assert values[field.key] == "123 5678" and command.problems(tool, values)
    code._typed(3, "9")
    code.at = 7
    code._typed(7, "")
    code.key("Backspace")                   # the Backspace that emptied box 8 is not a second one
    assert values[field.key] == "1239567"
    code.cleared = (None, 0.0)
    code.key("Backspace")
    assert values[field.key] == "123956" and code.at == 6
    assert widgets.DigitCode(values[field.key], lambda v: None).digits[:6] == list("123956")


def test_settings_keep_a_six_digit_switch_id_beside_the_five_digit_one(tmp_path, monkeypatch):
    """A Switch title shows its trainer id as six digits; FireRed shows five (docs/gui.md, Your trainer)."""
    import flet as ft
    from gui.views.settings import SettingsView
    from pokeldn.app import settings as settings_module

    monkeypatch.setattr(settings_module, "PATH", tmp_path / "settings.json")
    app = SimpleNamespace(settings=settings_module.Settings(tid=1, sid=2), update=None, update_state="",
                          update_listeners=[], picker=None, page=None, ui=lambda fn: fn())
    view = SettingsView(app)

    def walk(control):
        yield control
        inner = getattr(control, "controls", None) or [getattr(control, "content", None)]
        for child in inner:
            if isinstance(child, ft.Control):
                yield from walk(child)

    fields = {}
    for column in walk(view.column):
        if isinstance(column, ft.Column) and len(column.controls) == 2 \
                and isinstance(column.controls[1], ft.TextField):
            fields.setdefault(column.controls[0].value, []).append(column.controls[1])

    def type_into(label, text, at=0):
        fields[label][at].on_change(SimpleNamespace(control=SimpleNamespace(value=text)))

    type_into("ID, Switch games", "967295")
    type_into("Secret ID", "4294", at=1)
    type_into("ID, Switch games", "1000000")      # seven digits
    type_into("Secret ID", "4295", at=1)          # past 32 bits
    type_into("ID, FireRed and LeafGreen", "65536")
    saved = settings_module.load()
    assert (saved.tid, saved.sid, saved.switch_tid, saved.switch_sid) == (1, 2, 967295, 4294)
    assert saved.ids("frlg") == (1, 2) and saved.ids("za") == (0xFFFF, 0xFFFF)


def test_the_boost_settings_leave_with_the_last_unticked_boost(monkeypatch):
    from gui.views import gifts as view_module
    from pokeldn.app import gift_builder
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.settings import Settings
    from pokeldn.frlg.gift import builder as frlg_builder

    def texts(control):
        if isinstance(getattr(control, "value", None), str):
            yield control.value
        for child in [*(getattr(control, "controls", None) or []), getattr(control, "content", None)]:
            if child is not None:
                yield from texts(child)

    monkeypatch.setattr(pokemon.NamePicker, "_load", lambda self: None)
    tool = next(tool for game in GAMES for tool in game.tools if tool.key == "frlg-gift")
    field = next(field for field in tool.fields if field.kind == "builder")
    view = SimpleNamespace(tool=tool, values={}, extra={},
                           app=SimpleNamespace(settings=Settings(), picker=None, ui=lambda f: None))
    view.set_value = lambda field, value, rebuild=False: view.values.__setitem__(field.key, value)
    builder = view_module.GiftBuilder(view, field)
    builder.commit = lambda rebuild=False: None
    builder.value["mode"] = "preset"
    preset = next(p for p in gift_builder.module(gift_builder.GAMES["frlg-gift"]).PRESETS if hasattr(p, "members"))
    member = preset.members[0]
    builder._toggle(preset, member.key)
    assert frlg_builder.KEEP.label in texts(builder.presets())
    builder._toggle(preset, member.key)
    assert frlg_builder.KEEP.label not in texts(builder.presets())


def test_viewer_cleanup_removes_only_this_apps_older_viewers(tmp_path, monkeypatch):
    import flet_desktop
    from gui import flet_client
    folders = {name: tmp_path / name for name in ("current", "marked", "legacy-mac", "other-app", "vanilla")}
    for folder in folders.values():
        folder.mkdir()
    (folders["marked"] / flet_client.MARKER).touch()
    (folders["legacy-mac"] / "pokeldn.app").mkdir()
    (folders["other-app"] / "Other.app").mkdir()
    (folders["vanilla"] / "Flet.app").mkdir()
    monkeypatch.setattr(flet_desktop, "ensure_client_cached", lambda: folders["current"])
    removed = flet_client.prune_cache()
    assert sorted(p.name for p in removed) == ["legacy-mac", "marked"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["current", "other-app", "vanilla"]
    assert (folders["current"] / flet_client.MARKER).is_file()


# flet_desktop's own extractall passes no filter.
@pytest.mark.filterwarnings("ignore:Python 3.14 will:DeprecationWarning")
def test_flet_unpacks_the_xz_viewer_the_packer_writes(tmp_path, monkeypatch):
    import tarfile
    import flet_desktop
    from gui import flet_client
    bundle = tmp_path / "view" / "Flet.app"
    bundle.mkdir(parents=True)
    (bundle / "App").write_bytes(b"package:flet_drop")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # scripts/pack_flet.py: xz under the name flet_desktop looks for.
    with tarfile.open(bin_dir / "flet-macos.tar.gz", "w:xz") as archive:
        archive.add(bundle, arcname="Flet.app")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(flet_desktop, "get_package_bin_dir", lambda: str(bin_dir))
    monkeypatch.setattr(flet_desktop, "get_artifact_filename", lambda: "flet-macos.tar.gz")
    monkeypatch.setattr(flet_desktop, "tarfile", tarfile)
    with pytest.raises(tarfile.ReadError):
        flet_desktop.ensure_client_cached()
    flet_client.read_any_compression()
    cache = flet_desktop.ensure_client_cached()
    assert (cache / "Flet.app" / "App").read_bytes() == b"package:flet_drop"


def test_an_event_narrows_the_raid_card_to_what_it_spawns():
    """Walking Wake's spotlight: Scarlet's den only, Paldea, the progresses its five stars draw at."""
    from pokeldn.app.catalog import GAMES
    from pokeldn.sv import raid_event
    rows = tuple(dict(species=s, rate=1, rom=rom, group=g, stars=5, capture_rate=2)
                 for s, rom, g in ((1009, 1, 1), (1010, 2, 2)))
    spotlight = raid_event.Event(20230228, "", rows, {}, {}, (1, 1) + (0,) * 8)
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    saved = []
    view = SimpleNamespace(tool=tool, app=SimpleNamespace(settings=SimpleNamespace(save=lambda: saved.append(1))),
                           values={"--raid-event": "013 Walking Wake", "--raid-version": "scarlet",
                                   "--raid-event-group": "2", "--raid-progress": "tera", "--raid-map": "kitakami"})
    view.raid_event = lambda: spotlight
    view.raid_context = lambda: GamesView.raid_context(view)
    GamesView.constrain_raid(view)
    assert [view.values[k] for k in ("--raid-event-group", "--raid-progress", "--raid-map")] == ["1", "6star", "paldea"]
    assert saved
    field = {f.key: f for f in tool.fields}
    assert GamesView.raid_choices(view, field["--raid-progress"]) == (
        ("5star", "5-star raids"), ("6star", "6-star raids"))
    assert GamesView.raid_choices(view, field["--raid-map"]) == (("paldea", "Paldea"),)
    assert GamesView.raid_choices(view, field["--raid-version"]) == (("scarlet", "Scarlet"), ("violet", "Violet"))
    assert GamesView.raid_choices(view, field["--raid-seed"]) is None
    assert GamesView.raid_context(view)["den"] == "5★ Walking Wake"


def test_folding_the_raid_event_card_sets_its_event_aside_until_it_unfolds():
    """Folded, the host, the raid card and its finder are a standard raid's; the catch override
    and den go with the event; unfolding brings them back."""
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.command import build
    from pokeldn.app.introspect import parser_of
    from pokeldn.app.settings import Settings
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    redrawn = []
    view = SimpleNamespace(tool=tool, raid_event_open=True, redraw=lambda: redrawn.append(1),
                           values={"--raid-pokemon": {"file": "/tmp/host.pk9"}, "--raid-seed": "52E6B438",
                                   "--raid-event": "002 Charizard the Unrivaled", "--raid-event-group": "1",
                                   "--raid-catch-normal": True})
    view.raid_event = lambda: GamesView.raid_event(view)

    def hosted():
        return parser_of(tool.script).parse_args(build(tool, view.values, {}, Settings()))
    GamesView.show_raid_event(view, False)
    assert not view.raid_event_open and redrawn
    assert GamesView.raid_event(view) is None and "event" not in GamesView.raid_context(view)
    folded = hosted()
    assert (folded.raid_event, folded.raid_event_group, folded.raid_catch_normal) == (None, None, False)
    GamesView.show_raid_event(view, True)
    unfolded = hosted()
    assert view.raid_event_open and view.values["--raid-event"] == "002 Charizard the Unrivaled"
    assert unfolded.raid_event and (unfolded.raid_event_group, unfolded.raid_catch_normal) == (1, True)
    # With no event chosen, the card folds and unfolds with nothing to set aside.
    view.values["--raid-event"] = ""
    GamesView.show_raid_event(view, False)
    GamesView.show_raid_event(view, True)
    assert view.values["--raid-event"] == "" and "#raid-event-folded" not in view.values


def test_the_finder_wants_the_rewards_its_unfolded_list_names():
    """Rows of one item add up; folded or empty, the search wants nothing; a row without an item, one
    the raids searched cannot give, or a list still being made stops the search."""
    from gui.views.reward_filter import RewardFilter
    wants = RewardFilter(SimpleNamespace(ui=lambda f: f()), lambda: ([], {}))
    wants.names = {1606: "Ability Patch", 795: "Bottle Cap"}
    wants.choices, wants.open = {1606: (1, 2, 3)}, True
    assert wants.wanted() is None
    wants.rows = [{"item": 1606, "least": 1}, {"item": 1606, "least": 2}]
    assert wants.wanted() == {1606: 3}
    wants.open = False
    assert wants.wanted() is None
    wants.open = True
    for rows, choices, error in (([{"item": None, "least": 1}], {1606: (1,)}, "Choose an item"),
                                 ([{"item": 795, "least": 1}], {1606: (1,)}, "No raid searched gives Bottle Cap"),
                                 ([{"item": 1606, "least": 1}], None, "still being listed")):
        wants.rows, wants.choices = rows, choices
        with pytest.raises(ValueError, match=error):
            wants.wanted()
    # A row kept from a wider search names its item as one these raids do not give.
    wants.rows, wants.choices = [{"item": 795, "least": 2}], {1606: (1,)}
    wants._render(update=False)
    picker = wants.list.controls[0].controls[0].controls[0].controls[1]
    assert [o.text for o in picker.options] == ["Bottle Cap (not given here)", "Ability Patch"]


def test_find_a_raid_searches_ten_million_seeds_from_any_first_seed(monkeypatch):
    """The finder offers the compiled scan's ten million seeds, and its shuffle picks a random first seed."""
    import flet as ft
    from gui.views import raid_seed
    from pokeldn.sv import raid_search
    shown = []
    app = SimpleNamespace(page=SimpleNamespace(show_dialog=shown.append, pop_dialog=lambda: None),
                          ui=lambda f: f())
    monkeypatch.setattr(raid_search, "FAST", False)       # no warm-up thread
    picker = raid_seed.RaidSeedPicker(app, "", lambda _v: None,
                                      lambda: {"version": "violet", "map_name": "paldea", "progress": "6star",
                                               "content": "standard"}, lambda _c: None)
    picker._open(None)

    def walk(control):
        yield control
        for name in ("content", "controls"):
            child = getattr(control, name, None)
            for c in child if isinstance(child, list) else [child] if isinstance(child, ft.Control) else []:
                yield from walk(c)
    controls = list(walk(shown[0].content))
    labels = [c for c in controls if isinstance(c, ft.Column) and c.controls and isinstance(c.controls[0], ft.Container)
              and isinstance(c.controls[0].content, ft.Text)]
    first = next(c.controls[1] for c in labels if c.controls[0].content.value == "First seed")
    count = next(c.controls[1] for c in labels if c.controls[0].content.value == "Seeds to search")
    import importlib.util
    assert count.value == str(raid_search.DEFAULT_COUNT)
    assert raid_search.DEFAULT_COUNT == (10_000_000 if importlib.util.find_spec("numba") else 100_000)
    start, shuffle = first.controls
    assert start.value == "00000000" and shuffle.tooltip == "Start at a random seed"
    monkeypatch.setattr(type(start), "update", lambda self: None)
    values = set()
    for _ in range(5):
        shuffle.on_click(None)
        assert raid_seed.seed_of(start.value) is not None and len(start.value) == 8
        values.add(start.value)
    assert len(values) > 1


def test_the_finder_tells_how_far_a_search_is_and_how_long_it_has_left():
    from gui.views.raid_seed import duration, searching
    assert [duration(s) for s in (0, 59.9, 60, 200, 3600, 7500)] == [
        "0 s", "59 s", "1 min 0 s", "3 min 20 s", "1 h 0 min", "2 h 5 min"]
    assert searching(0, 1000, 0) == "Searching 0 of 1,000 seeds..."
    assert searching(500, 1000, 2) == "Searching 500 of 1,000 seeds, 250 a second, 2 s left..."
    assert searching(50_000_000, 1 << 32, 2) == (
        "Searching 50,000,000 of 4,294,967,296 seeds, 25.0 million a second, 2 min 49 s left...")


def test_the_finder_s_checkboxes_flip_and_tell(monkeypatch):
    import flet as ft
    from gui.views.raid_seed import Check
    monkeypatch.setattr(ft.Container, "update", lambda self: None)
    told = []
    box = Check("Every seed", "tip", told.append)
    assert not box.value and box.icon.src.endswith("checkbox.svg") and box.control.tooltip == "tip"
    box.control.on_click(None)
    assert box.value and box.icon.src == "icons/checkbox-on.svg" and told == [True]
    box.control.on_click(None)
    assert not box.value and told == [True, False]


@pytest.mark.parametrize("downloaded", [True, False])
def test_an_event_missing_from_the_gallery_stays_chosen_and_shows_missing(monkeypatch, tmp_path, downloaded):
    """The card keeps an event the gallery lacks (the run refuses it) and says so in red, rather than
    quietly hosting a standard raid."""
    from gui import theme as t
    from gui.views import raid_event as card
    from pokeldn.app import events_gallery as gallery
    from pokeldn.app.catalog import GAMES
    key = "013 Walking Wake"
    if downloaded:
        (tmp_path / key / "Files").mkdir(parents=True)
    monkeypatch.setattr(gallery, "event_path", lambda k, root=None: str(tmp_path / k))
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    field = next(f for f in tool.fields if f.key == "--raid-event")
    saved = []
    view = SimpleNamespace(tool=tool, raid_event_open=False, values={"--raid-event": key, card.CATCH: True},
                           app=SimpleNamespace(settings=SimpleNamespace(save=lambda: saved.append(1))),
                           raid_event=lambda: None)
    picker = card.RaidEventPicker(view, field)
    assert view.values == {"--raid-event": key, card.CATCH: True} and not saved
    if downloaded:
        assert (picker.summary.value, picker.summary.color) == ("Walking Wake", t.BLUE)
    else:
        assert (picker.summary.value, picker.summary.color) == ("Missing: Walking Wake", t.RED)

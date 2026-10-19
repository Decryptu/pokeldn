import os
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("flet")

import flet as ft

from gui import theme as t
from gui.localization import SERVICE as DISPLAY_SERVICE
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
    shown = []
    picker = SimpleNamespace(value={"species": 132, "options": {"ability": 31, "ball": 2, "gender": 1,
                                                                 "held_item": 236, "nature": 3, "form": 2}},
                             show_sprite=lambda: shown.append(dict(picker.value["options"])))
    options = OfferOptions(picker)
    options._form({"natures": [], "abilities": [{"id": 7, "name": "Limber"}], "gendered": False,
                   "forms": [{"id": 0, "name": ""}], "move_names": [],
                   "balls": [{"id": 2, "name": "Ultra Ball"}], "held": [{"id": 236, "name": "Light Ball"}],
                   "effort": {"kind": "evs", "max": 252, "total": 510}})
    assert picker.value["options"] == {"ball": 2, "held_item": 236, "nature": 3}
    assert shown == [picker.value["options"]]


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


@pytest.mark.parametrize("typed, sent", [("220", 220), ("256", None), ("", None)])
def test_a_friendship_past_255_or_empty_is_not_sent(typed, sent):
    options = OfferOptions(SimpleNamespace(value={"options": {"friendship": 70}}))
    options.control.update = lambda: None
    box = options._number("friendship", 255)
    box.value = typed
    box.on_change(SimpleNamespace(control=box))
    assert options.chosen.get("friendship") == sent
    assert (box.border[ft.ControlState.DEFAULT].side.color == t.RED) == (typed == "256")


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
    app.settings = SimpleNamespace(radio_port="", radio="", keys="")
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
                                      {"tag_name": "v7.0.0", "html_url": f"{base}/page", "assets": every}]).encode()
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


@pytest.mark.parametrize("form", [0, 1])
def test_a_pokemon_file_shows_its_own_species_and_shininess(monkeypatch, form):
    import asyncio
    monkeypatch.setattr(pokemon.SERVICE, "species", lambda game: [{"id": 25, "name": "Pikachu"}])
    monkeypatch.setattr(pokemon.SERVICE, "import_file", lambda game, path: {
        "file": path, "species": "Charizard", "species_id": 6, "form_id": form,
        "level": 50, "shiny": True, "legal": True,
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
    picker.sprite.show = lambda species, shiny, update=True, form=0: shown.append((species, shiny, form))
    asyncio.run(picker._use_file(None))
    assert shown == [(6, True, form)]
    assert picker.options.label.value == "1 set"
    assert (saved[-1]["species"], saved[-1]["shiny"], picker.species.value, picker.shiny.value) == (6, True, "6", True)


@pytest.mark.parametrize("assembler", [True, False])   # a computer without the Arm toolchain sees the install hint
@pytest.mark.parametrize("key", ["frlg-gift", "swsh-gift"])
def test_the_gift_builder_renders_every_mode_and_kind_and_exports_what_it_shows(tmp_path, monkeypatch, key,
                                                                                assembler):
    import asyncio
    from gui.views import gifts as view_module
    if not assembler:
        monkeypatch.setattr(view_module.custom_code, "toolchain", lambda: None)
    import time
    from types import SimpleNamespace
    from pokeldn.swsh import wc8
    # A WC8 carries the second it was built; the export and the recompile below may straddle one.
    monkeypatch.setattr(wc8, "time", SimpleNamespace(time=lambda: 1_700_000_000.0, gmtime=time.gmtime))
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
    events, shown_by = [], []

    class Process:
        def __init__(self, argv, cwd, env, on_line, on_exit, popups=None, label=""):
            self.script, self.on_exit, self.running = argv[1], on_exit, True
            events.append(("start", self.script))
            shown_by.append((popups, label))

        def stop(self):
            events.append(("stop", self.script))
            self.running = False
            self.on_exit(0)

    class FakeApp:
        process, process_label = None, ""
        popups = "the app's pop-ups"
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
    panel.__dict__.update(app=FakeApp(), games=SimpleNamespace(values={}, extra={}, visible=False, show_run_cards=lambda: None, panes=SimpleNamespace(show=lambda *a, **k: None), game=SimpleNamespace(
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
    assert shown_by == [("the app's pop-ups", first.name), ("the app's pop-ups", second.name)]


def popup_page(monkeypatch):
    """A page whose dialogs open and close as Flet's do, and the app's pop-ups over it (gui.popups)."""
    from gui.popups import Dialogs
    from pokeldn.app import popups
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    page = SimpleNamespace(_dialogs=SimpleNamespace(controls=[]))
    page.show_dialog = lambda d: (setattr(d, "open", True), page._dialogs.controls.append(d))
    manager, answers = popups.Manager(Dialogs(page)), []
    return page, manager, manager.program("Trade host", answers.append), answers


def labels(dialog):
    return [button.content for button in dialog.actions]


def test_a_pop_up_is_a_dialog_naming_its_program_with_the_callers_buttons(monkeypatch):
    page, manager, run, answers = popup_page(monkeypatch)
    run.take({"op": "open", "id": "ask", "n": 1, "kind": "confirm", "title": "Trade the shiny?", "text": "A Gholdengo.",
              "agree": "Trade", "disagree": "Skip", "tone": "warning"})
    run.take({"op": "open", "id": "note", "n": 2, "kind": "ack", "title": "Saved", "text": "", "label": "Close",
              "tone": "error"})
    ask, note = page._dialogs.controls
    assert ask.open and note.open and not ask.modal
    header = ask.title.controls[1].controls
    assert [c.value for c in header] == ["Trade host", "Trade the shiny?"]
    assert ask.content.content.value == "A Gholdengo." and ask.content.content.selectable
    assert ask.title.controls[0].src == "icons/warning-diamond.svg" and ask.title.controls[0].color == t.AMBER
    assert labels(ask) == ["Skip", "Trade"] and labels(note) == ["Close"] and note.content is None
    note.actions[0].on_click(None)
    assert not note.open and answers == [{"id": "note", "n": 2, "answer": "ack"}]
    note.on_dismiss(None)                       # Flet reports the close the manager made: nothing more
    ask.on_dismiss(None)                        # Esc, or a click outside
    assert answers[1:] == [{"id": "ask", "n": 1, "answer": "dismiss"}]


def test_a_choice_is_a_dialog_with_one_button_per_option_and_no_actions(monkeypatch):
    page, manager, run, answers = popup_page(monkeypatch)
    run.take({"op": "open", "id": "update", "n": 1, "kind": "choose", "title": "Update found",
              "text": "Version 1.1.0 is installed.", "options": ["Save it", "Send 1.2.0", "Leave"], "tone": "info"})
    (dialog,) = page._dialogs.controls
    text, *buttons = dialog.content.content.controls
    assert text.value == "Version 1.1.0 is installed." and dialog.actions == []
    assert [b.content for b in buttons] == ["Save it", "Send 1.2.0", "Leave"]
    buttons[1].on_click(None)
    assert answers == [{"id": "update", "n": 1, "answer": "1"}] and not dialog.open


def test_a_runs_progress_lines_draw_a_bar_with_rate_and_time_left_and_stay_out_of_the_log(monkeypatch):
    from gui.views import games
    clock = iter([100.0, 110.0])
    monkeypatch.setattr(games.time, "monotonic", lambda: next(clock))
    logged = []
    panel = SessionPanel.__new__(SessionPanel)
    panel.__dict__.update(app=SimpleNamespace(ui=lambda fn: fn()), log=SimpleNamespace(add=logged.append),
                          transfer=ft.Container(visible=False), rates={}, partner_state=None, traded=0)
    panel.transfer.update = lambda: None
    panel._line("[progress] 1000000000 5200000000 bytes Sending the update")
    panel._line("[progress] 1047000000 5200000000 bytes Sending the update")
    panel._line("[lcs] the console sent its version")
    bar, detail = panel.transfer.content.controls[1].controls
    assert panel.transfer.visible and round(bar.value, 3) == round(1047 / 5200, 3)
    assert detail.value == "1.05 of 5.20 GB · 4.70 MB/s · 15 min left"
    assert logged == ["[lcs] the console sent its version"]


def test_a_runs_panel_lines_are_kept_for_its_plugin_and_drawn_on_its_page(monkeypatch, tmp_path):
    """A `[panel]` line from a plugin's run is stored for that plugin, stays out of the log and redraws the
    card and the library note on the page; one the app cannot read is shown in the log instead."""
    from gui.views import library as library_view
    from gui.views.panels import StatusCards
    from pokeldn import panel as cards, plugins
    from pokeldn.app import paths
    monkeypatch.setattr(paths, "DATA", tmp_path)
    owner = plugins.Plugin(id="updates", name="Updates", library="Updates")
    monkeypatch.setattr(plugins, "owner", lambda key: owner if key == "updates-tool" else None)
    monkeypatch.setattr(plugins, "library_path", lambda name: tmp_path / name)
    (tmp_path / "Updates").mkdir()
    (tmp_path / "Updates" / "Game 1.0.2.nsp").write_bytes(b"nsp")
    changed, logged = [], []
    session = SessionPanel.__new__(SessionPanel)
    session.__dict__.update(app=SimpleNamespace(ui=lambda fn: fn()), log=SimpleNamespace(add=logged.append),
                            running_tool=SimpleNamespace(key="updates-tool"),
                            games=SimpleNamespace(plugin_changed=changed.append))
    session._line(cards.PREFIX + '{"id":"console","title":"Let\'s Go, Pikachu!","lines":[["System version","23.0.1"]],'
                  '"chips":[["Version","1.0.2"]],"tone":"ok"}')
    session._line(cards.PREFIX + '{"file":"Game 1.0.2.nsp","state":"bad","text":"A signature does not check"}')
    session._line(cards.PREFIX + '{"id":"x","tone":"pink"}')
    assert changed == ["updates", "updates"]
    assert len(logged) == 1 and "cannot read" in logged[0]

    column = StatusCards(owner).control()
    (card,) = column.controls
    texts = [c.value for c in walk(card) if isinstance(c, ft.Text)]
    assert texts[:2] == ["Let's Go, Pikachu!", "Version 1.0.2"] and texts[2:] == ["System version", "23.0.1"]
    view = library_view.LibraryCard(SimpleNamespace(), owner)
    view.control()
    (row,) = view.listing.controls
    assert "A signature does not check" in [c.value for c in walk(row) if isinstance(c, ft.Text)]


def walk(control):
    yield control
    for name in ("content", "controls"):
        child = getattr(control, name, None)
        for c in (child if isinstance(child, list) else [child] if isinstance(child, ft.Control) else []):
            yield from walk(c)


def test_a_pop_up_opened_again_under_its_id_redraws_its_dialog(monkeypatch):
    page, manager, run, answers = popup_page(monkeypatch)
    message = {"op": "open", "id": "gift", "n": 1, "kind": "ack", "title": "The gift carries the trainer from "
               "Settings", "text": "The save names no one.", "tone": "warning"}
    run.take(message)
    run.take({**message, "n": 2, "text": "PKHeX refused the card."})
    (dialog,) = page._dialogs.controls
    assert dialog.content.content.value == "PKHeX refused the card."
    dialog.actions[0].on_click(None)
    assert answers == [{"id": "gift", "n": 2, "answer": "ack"}] and not dialog.open


def test_an_app_dialog_closes_itself_never_a_pop_up_above_it(monkeypatch):
    page, manager, run, answers = popup_page(monkeypatch)
    welcome = t.dialog(title=t.text("Welcome"))
    page.show_dialog(welcome)
    run.take({"op": "open", "id": "note", "n": 1, "kind": "ack", "title": "Note", "text": "",
              "tone": "info"})
    note = page._dialogs.controls[1]
    assert page.pop_dialog() is welcome and not welcome.open and note.open
    assert page.pop_dialog() is None and note.open and answers == []


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
    values |= {f.key: {"species": 25, "level": 10} for f in tool.fields if f.kind == "encounter"}
    n = field.length
    code = widgets.DigitCode(command.value_of(field, values), lambda v: values.__setitem__(field.key, v),
                             length=n)
    assert code.value == field.default
    for box in range(n):                    # clear whatever the default put there
        code._typed(box, "")
    assert bool(command.problems(tool, values)) == bool(field.default or field.required)
    code._typed(0, "1")
    code._typed(code.at, "x2")              # a letter never lands
    assert code.at == 2 and values[field.key] == "12"
    assert command.problems(tool, values) == [f"{field.label}: all {dict({4: 'four', 8: 'eight'})[n]} digits" +
                                              ("." if field.default or field.required else ", or none.")]
    code._typed(2, "x")
    assert values[field.key] == "12" and code.at == 2
    whole = "12345678"[:n]
    code._typed(2, "34 5-678"[:2 * n - 6] if n < 8 else "34 5-678")   # a pasted code keeps its digits only
    assert values[field.key] == whole and code.at == n - 1
    assert command.problems(tool, values) == []
    args = command.build(tool, values, {}, Settings())
    assert args[args.index(field.flag) + 1] == whole
    parser_of(tool.script).parse_args(args)
    code._typed(1, "")                      # a hole keeps the digits after it in their boxes
    assert values[field.key] == whole[0] + " " + whole[2:] and command.problems(tool, values)
    code._typed(1, "9")
    code.at = n - 1
    code._typed(n - 1, "")
    code.key("Backspace")                   # the Backspace that emptied the last box is not a second one
    assert values[field.key] == "19" + whole[2:n - 1]
    code.cleared = (None, 0.0)
    code.key("Backspace")
    assert values[field.key] == "19" + whole[2:n - 2] and code.at == n - 2
    assert widgets.DigitCode(values[field.key], lambda v: None, length=n).digits[:n - 2] == list("19" + whole[2:n - 2])


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


@pytest.mark.parametrize("game,key,species", [
    ("frlg", "event-wishmkr-jirachi", 385),
    ("frlg", "event-doel-deoxys", 386),
    ("frlg", "event-rocks-metang", 375),
    ("frlg", "celebi", 251),
    ("frlg", "mattle-ho-oh", 250),
    ("frlg", "master-ball", 0),
    ("swsh", "pikachu", 25),
    ("swsh", "egg", 25),
    ("swsh", "pikachu-uniform", 0),
])
def test_gift_presets_show_the_pokemon_species_and_still_select_it(monkeypatch, game, key, species):
    """Hoenn's National Dex ids differ from FR/LG's internal ids; a named outfit isn't a Pokemon."""
    from gui.views import gifts as view_module
    from pokeldn.app import gift_builder

    monkeypatch.setattr(view_module, "Sprite", lambda app, n, shiny, size, form=0:
                        SimpleNamespace(control=ft.Container(data=(n, shiny), width=size)))
    builder = view_module.GiftBuilder.__new__(view_module.GiftBuilder)
    builder.app = None
    builder.game, builder.module = game, gift_builder.module(game)
    builder.value = gift_builder.normalized(game, {})
    builder.commit = lambda rebuild=False: None
    preset = builder.module.PRESET[key]
    tile = next(c for c in raid_controls(builder.presets())
                if isinstance(c, ft.Container) and c.on_click and preset.label in gift_texts(c))
    sprites = [c.data for c in tile.content.controls if isinstance(c.data, tuple)]
    assert sprites == ([(species, False)] if species else [])
    tile.on_click(None)
    assert builder.value["preset"] == key


@pytest.mark.parametrize("species,shiny_type,form", [
    (25, 0, 0), (25, 1, 0), (25, 2, 0), (25, 3, 0), (0, 0, 0), (146, 2, 1), (25, 0, 9),
])
def test_official_gift_icons_follow_the_record_and_keep_selection(monkeypatch, species, shiny_type, form):
    from gui.views import gifts as view_module
    from pokeldn.swsh import gift_builder, wc8

    monkeypatch.setattr(view_module, "Sprite", lambda app, n, shiny, size, form=0:
                        SimpleNamespace(control=ft.Container(data=(n, shiny, form), width=size)))
    builder = view_module.GiftBuilder.__new__(view_module.GiftBuilder)
    builder.app, builder.module, builder.game = None, gift_builder, "swsh"
    builder.value = {"event": "other"}
    builder.commit = lambda rebuild=False: None
    raw = (wc8.pokemon_card(species, shiny_type=shiny_type, form=form) if species else
           gift_builder.record(gift_builder.blank(kind="items")))
    card = {"key": "test", "label": "Test gift", "summary": "A gift", "record": raw}
    tile = builder._event_tile(card)
    sprites = [c.data for c in tile.content.controls if isinstance(c.data, tuple)]
    assert sprites == ([(species, shiny_type in (2, 3), form)] if species else [])
    tile.on_click(None)
    assert builder.value["event"] == "test"


@pytest.mark.parametrize("game,key,initial,changed,national", [
    ("frlg", "species", 25, 409, 385), ("frlg", "icon", 251, 277, 252),
    ("swsh", "species", 25, 146, 146),
])
def test_custom_gift_previews_follow_species_form_and_shiny_edits(monkeypatch, game, key, initial,
                                                                changed, national):
    from gui.views import gifts as view_module

    class Preview:
        def __init__(self, app, species, shiny, size, form):
            self.control = ft.Container()
            self.show(species, shiny, form)

        def show(self, species, shiny, form=0):
            self.control.data = (species, shiny, form)

    monkeypatch.setattr(view_module, "Sprite", Preview)
    monkeypatch.setattr(view_module, "NamePicker", lambda *a, **kw: SimpleNamespace(control=ft.Container()))
    builder = view_module.GiftBuilder.__new__(view_module.GiftBuilder)
    builder.game, builder.app, builder.previews = game, None, []
    builder.value = {"build": {"kind": "pokemon", key: initial}}
    builder.commit = lambda rebuild=False: None
    field = builder.name_field("Pokemon", "species", key, preview=True)
    builder.edit(key, changed)
    assert field.controls[1].data == (national, False, 0)
    if game == "swsh":
        builder.edit("form", 1)
        builder.edit("shiny", True)
        assert field.controls[1].data == (146, True, 1)
        builder.state["kind"] = "egg"
        builder.edit("shiny", True)
        assert field.controls[1].data == (146, False, 1)


def test_trade_preview_keeps_the_selected_form_when_shiny_changes_and_resets_on_clear(monkeypatch):
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    picker = pokemon.PokemonPicker.__new__(pokemon.PokemonPicker)
    picker.value = {"species": 25, "shiny": False, "options": {}}
    shown = []
    picker.sprite = SimpleNamespace(show=lambda species, shiny, **kw: shown.append((species, shiny, kw["form"])))
    picker.options = OfferOptions(picker)
    choice = picker.options._choice("form", [{"id": 0, "name": "Normal"}, {"id": 9, "name": "World"}])
    choice.on_select(SimpleNamespace(control=SimpleNamespace(value="9")))
    picker._shiny(SimpleNamespace(control=SimpleNamespace(value=True)))
    picker.options._clear(None)
    assert shown == [(25, False, 9), (25, True, 9), (25, True, 0)]


def test_gift_form_replies_cannot_change_another_editor_or_a_newer_request(monkeypatch):
    from gui.views import gifts as view_module
    from pokeldn.swsh import gift_builder

    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    work, replies = [], []
    monkeypatch.setattr(view_module.threading, "Thread", lambda target, daemon: SimpleNamespace(
        start=lambda: work.append(target)))
    monkeypatch.setattr(view_module.SERVICE, "options", lambda *a: {
        "forms": [{"id": 0, "name": "Kanto"}, {"id": 1, "name": "Galar"}]})
    builder = view_module.GiftBuilder.__new__(view_module.GiftBuilder)
    builder.game = "swsh"
    builder.app = SimpleNamespace(settings=SimpleNamespace(trainer=lambda game: {}), ui=replies.append)
    builder.value = {"build": gift_builder.blank(species=146, form=1)}
    builder.forms, builder.previews = ft.Container(), []
    builder.commit = lambda rebuild=False: None
    builder._load_forms()
    builder._load_forms()
    work[0]()
    work[1]()
    loading = builder.forms.content
    replies[0]()
    assert builder.forms.content is loading
    replies[1]()
    dropdown = next(c for c in raid_controls(builder.forms) if isinstance(c, ft.Dropdown))
    assert dropdown.value == "1"
    dropdown.on_select(SimpleNamespace(control=SimpleNamespace(value="0")))
    assert gift_builder.record(builder.state)[0x242] == 0

    builder._load_forms()
    work[-1]()
    builder.value["build"] = gift_builder.blank(kind="items", species=146)
    loading = builder.forms.content
    replies[-1]()
    assert builder.forms.content is loading


def test_offline_gift_catalog_rebuilds_never_start_sprite_workers(monkeypatch, tmp_path):
    from gui.views import gifts as view_module, sprites as sprite_view
    from pokeldn.app.sprites import SpriteCache
    from pokeldn.swsh import gift_builder

    monkeypatch.setattr(sprite_view, "CACHE", SpriteCache(tmp_path, online=False))
    def unexpected(*args, **kwargs):
        pytest.fail("An offline sprite started a worker")
    monkeypatch.setattr(sprite_view, "WORKERS", SimpleNamespace(submit=unexpected), raising=False)
    monkeypatch.setattr(view_module.threading, "Thread", unexpected)
    builder = view_module.GiftBuilder.__new__(view_module.GiftBuilder)
    builder.app = SimpleNamespace(settings=SimpleNamespace(sprites=False))
    builder.module, builder.game = gift_builder, "swsh"
    builder.value = {"event": ""}
    for _ in range(3):
        for card in gift_builder.OFFICIAL.load():
            builder._event_tile(card)


def test_a_pokemon_home_card_is_outlined_in_amber_and_says_why(monkeypatch):
    """The Pokemon a HOME card gives carries no HOME tracker, whatever the HOME tracker setting: its tile and
    summary give the "empty" warning [docs/swsh_gift.md, Official event cards]."""
    from gui.views import gifts as view_module
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.settings import Settings
    from pokeldn.swsh import events

    def walk(control):
        yield control
        for child in [*(getattr(control, "controls", None) or []), getattr(control, "content", None)]:
            if child is not None:
                yield from walk(child)

    def texts(control):
        return [c.value for c in walk(control) if isinstance(getattr(c, "value", None), str)]

    monkeypatch.setattr(pokemon.NamePicker, "_load", lambda self: None)
    tool = next(tool for game in GAMES for tool in game.tools if tool.key == "swsh-gift")
    field = next(field for field in tool.fields if field.kind == "builder")
    view = SimpleNamespace(tool=tool, values={}, extra={},
                           app=SimpleNamespace(settings=Settings(), picker=None, ui=lambda f: None))
    view.set_value = lambda field, value, rebuild=False: view.values.__setitem__(field.key, value)
    builder = view_module.GiftBuilder(view, field)
    warning = pokemon.builder.HOME_TRACKER_WARNINGS["empty"]
    reason = f"{warning}. {events.HOME_WHY}"
    for group, home in ((events.HOME, True), ("Pokemon", False)):
        card = next(e for e in events.load() if e["group"] == group)
        builder.value.update(mode="event", event=card["key"], event_search=card["label"])
        builder.cards()
        assert (reason in texts(builder.effects)) == home, group
        tile = next(c for c in walk(builder.events()) if isinstance(c, ft.Container) and c.on_click
                    and card["label"] in texts(c))
        assert (warning in texts(tile)) == home, group
        assert (tile.border.top.color == view_module.t.AMBER) == home, group


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
    assert GamesView.raid_context(view)["den"] == "5 stars: Walking Wake"


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


def test_folding_the_raid_partners_card_keeps_its_choice():
    """Folded or not, the host seats the trainers chosen, in order, from the progress chosen; with
    none chosen it passes nothing and draws them itself."""
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.command import build
    from pokeldn.app.introspect import parser_of
    from pokeldn.app.settings import Settings
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    redrawn = []
    view = SimpleNamespace(tool=tool, raid_partners_open=True, redraw=lambda: redrawn.append(1),
                           values={"--raid-pokemon": {"file": "/tmp/host.pk9"}, "--raid-seed": "52E6B438",
                                   "--raid-partner": {"progress": "tera", "picks": ["Logan", "Ava"]}})

    def hosted():
        return parser_of(tool.script).parse_args(build(tool, view.values, {}, Settings()))
    for unfolded in (False, True):
        GamesView.show_raid_partners(view, unfolded)
        args = hosted()
        assert view.raid_partners_open == unfolded and redrawn
        assert (args.raid_partner, args.raid_partner_progress) == (["Logan", "Ava"], "tera")
    del view.values["--raid-partner"]
    assert (hosted().raid_partner, hosted().raid_partner_progress) == ([], None)


def test_the_raid_partners_card_shows_its_progress_s_pool_and_seats_two_at_most():
    """The pool follows the story progress unless one is chosen; a trainer it lacks leaves the choice,
    a third pick none, and choosing the story progress's own stage follows it again."""
    from gui.views.raid_partners import RaidPartnersPicker
    from pokeldn.app.catalog import GAMES
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    field = next(f for f in tool.fields if f.kind == "raidpartners")
    values = {"--raid-partner": {"progress": "3star", "picks": ["Dylan", "Ava"]}}

    def set_value(f, value, rebuild=False):
        values[f.key] = value
    view = SimpleNamespace(tool=tool, raid_partners_open=True, raid_partners_width=0,
                           values=values, set_value=set_value,
                           raid_context=lambda: {"progress": "6star", "content": "standard"},
                           app=SimpleNamespace(settings=SimpleNamespace(save=lambda: None, sprites=False),
                                               ui=lambda work: None))
    picker = RaidPartnersPicker(view, field)
    assert (picker.stage, picker.default, len(picker.pool)) == (1, 4, 16)
    assert values["--raid-partner"]["picks"] == ["Ava"]
    assert picker._summary() == "Ava, one drawn · 3-star raids"
    picker._pick("Zoe")
    assert values["--raid-partner"]["picks"] == ["Ava", "Zoe"]
    picker = RaidPartnersPicker(view, field)
    picker._pick("Eli")
    assert values["--raid-partner"]["picks"] == ["Ava", "Zoe"]
    picker._pick("Ava")
    assert values["--raid-partner"]["picks"] == ["Zoe"]
    picker._progress(SimpleNamespace(control=SimpleNamespace(value="6star")))
    assert values["--raid-partner"]["progress"] == ""
    picker = RaidPartnersPicker(view, field)
    assert (picker.stage, len(picker.pool), picker.pool[16].name) == (4, 18, "Haxorus")


def test_each_console_joining_takes_a_partner_s_slot():
    """Consoles joining sets how many partners there are to pick: one with two consoles, a second
    pick leaving; none with three, the start refused while a pick stands."""
    from gui.views.raid_partners import RaidPartnersPicker
    from pokeldn.app import command
    from pokeldn.app.catalog import GAMES
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    field = next(f for f in tool.fields if f.kind == "raidpartners")
    values = {"--raid-pokemon": {"file": "/tmp/host.pk9"}, "--raid-seed": "52E6B438",
              "--raid-players": "2", "--raid-partner": {"progress": "", "picks": ["Eli", "Gianna"]}}

    def set_value(f, value, rebuild=False):
        values[f.key] = value
    view = SimpleNamespace(tool=tool, raid_partners_open=True, raid_partners_width=0,
                           values=values, set_value=set_value,
                           raid_context=lambda: {"progress": "6star", "content": "standard"},
                           app=SimpleNamespace(settings=SimpleNamespace(save=lambda: None, sprites=False),
                                               ui=lambda work: None))
    picker = RaidPartnersPicker(view, field)
    assert (picker.free, values["--raid-partner"]["picks"], picker._summary()) == (1, ["Eli"], "Eli")
    picker._pick("Gianna")
    assert values["--raid-partner"]["picks"] == ["Eli"]
    assert not [e for e in command.problems(tool, values) if "consoles joining" in e]
    values["--raid-players"] = "3"
    assert "With 3 consoles joining, the raid seats no partner." in command.problems(tool, values)
    picker = RaidPartnersPicker(view, field)
    assert (picker.free, values["--raid-partner"]["picks"]) == (0, [])
    assert picker._summary() == "None, 3 consoles fill the slots"


def test_a_favoured_raid_partner_s_card_shows_a_star_and_why(tmp_path):
    """The level-80 cards of the partners raiders want end on a star and its reason, gold for the
    favoured and silver for the next tier; a pool without any, such as level 40's, shows neither. Each
    card names the Pokemon and, on a line of its own, its level: four fifths of Our Pokemon's, unknown
    until Our Pokemon is built."""
    import flet as ft
    from gui import theme
    from gui.views.raid_partners import RaidPartnersPicker
    from pokeldn import gen9
    from pokeldn.app.catalog import GAMES
    from pokeldn.sv import raid_partners
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    field = next(f for f in tool.fields if f.kind == "raidpartners")
    ours = tmp_path / "ours.pk9"
    ours.write_bytes(gen9.encrypt(gen9.build(species=184, level=37)))
    for progress, wanted, values in (("6star", raid_partners.RECOMMENDED[80], {}),
                                     ("4star", {}, {"--raid-pokemon": {"file": str(ours)}})):
        view = SimpleNamespace(tool=tool, raid_partners_open=True, raid_partners_width=0,
                               values=values, set_value=None,
                               raid_context=lambda: {"progress": progress, "content": "standard"},
                               app=SimpleNamespace(settings=SimpleNamespace(save=lambda: None, sprites=False),
                                                   ui=lambda work: None))
        card = list(raid_controls(RaidPartnersPicker(view, field).control))
        for rank, ink, tier in ((1, theme.AMBER, "Favoured by raiders"),
                                (2, theme.SILVER, "Next tier for raiders")):
            reasons = [why for r, why, _ in wanted.values() if r == rank]
            assert [c.value for c in card if isinstance(c, ft.Text) and c.color == ink] == reasons
            assert ([c.tooltip for c in card if isinstance(c, ft.Container) and str(c.tooltip).startswith(tier)]
                    == [f"{tier}: {detail}." for r, _, detail in wanted.values() if r == rank])
        texts = {c.value for c in card if isinstance(c, ft.Text)}
        if values:
            assert {"Camerupt", "Lv. 29"} <= texts and "Lv. —" not in texts
            assert any(str(text).startswith("Level 29 partners, four fifths of Our Pokemon's level 37.")
                       for text in texts)
        else:
            assert {"Gardevoir", "Lv. —"} <= texts


def test_a_narrow_window_stands_the_raid_partners_two_to_a_row():
    """Three cards to a row while each is CARD_WIDTH wide, two in a narrower window, such as the
    smallest the app allows; a redraw starts on the last width's columns."""
    import flet as ft
    from gui.views.raid_partners import RaidPartnersPicker, columns
    from pokeldn.app.catalog import GAMES
    assert (columns(0), columns(500), columns(380)) == (3, 3, 2)
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    field = next(f for f in tool.fields if f.kind == "raidpartners")
    view = SimpleNamespace(tool=tool, raid_partners_open=True, raid_partners_width=0,
                           values={}, set_value=None,
                           raid_context=lambda: {"progress": "6star", "content": "standard"},
                           app=SimpleNamespace(settings=SimpleNamespace(save=lambda: None, sprites=False),
                                               ui=lambda work: None))

    def rows(picker):
        cards = next(c for c in raid_controls(picker.control)
                     if isinstance(c, ft.Container) and c.on_size_change == picker._spread)
        return cards, [len(row.controls) for row in cards.content.controls]
    picker = RaidPartnersPicker(view, field)
    cards, shape = rows(picker)
    assert shape == [3] * 6
    cards.content.update = lambda: None
    picker._spread(SimpleNamespace(control=cards, width=380))
    assert [len(row.controls) for row in cards.content.controls] == [2] * 9
    assert view.raid_partners_width == 380 and rows(RaidPartnersPicker(view, field))[1] == [2] * 9


def test_the_raid_partners_level_follows_our_pokemon(tmp_path):
    """Building or dropping Our Pokemon saves it without a redraw; the partners' card reads its level
    again, its note and cards showing the new one."""
    import flet as ft
    from gui.views.raid_partners import RaidPartnersPicker
    from pokeldn import gen9
    from pokeldn.app.catalog import GAMES
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    field = next(f for f in tool.fields if f.kind == "raidpartners")
    ours = next(f for f in tool.fields if f.key == "--raid-pokemon")
    records = {}
    for level in (100, 90):
        records[level] = tmp_path / f"lv{level}.pk9"
        records[level].write_bytes(gen9.encrypt(gen9.build(species=184, level=level)))
    view = SimpleNamespace(tool=tool, raid_partners_open=True, raid_partners_width=0,
                           values={"--raid-pokemon": {"file": str(records[100])}}, set_value=None,
                           raid_context=lambda: {"progress": "6star", "content": "standard"},
                           session=SimpleNamespace(refresh=lambda: None),
                           app=SimpleNamespace(settings=SimpleNamespace(save=lambda: None, sprites=False),
                                               ui=lambda work: None))

    def shown():
        texts = [c.value for c in raid_controls(view.raid_partners.control) if isinstance(c, ft.Text)]
        return {text for text in texts if str(text).startswith(("Lv.", "Level "))}
    view.raid_partners = RaidPartnersPicker(view, field)
    view.raid_partners.body.update = lambda: None
    assert view.raid_partners.level == 80 and "Lv. 80" in shown()
    GamesView.set_value(view, ours, {"file": str(records[90])})
    assert view.raid_partners.level == 72
    assert shown() == {"Lv. 72", "Level 72 partners, four fifths of Our Pokemon's level 90. Pick up to two, "
                                  "in the order they take the empty slots; a partner you leave is drawn when "
                                  "the host starts."}


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


def raid_controls(control):
    """-> the control and every one inside it: the raid finder's dialog and cards."""
    import flet as ft
    yield control
    for name in ("content", "controls"):
        child = getattr(control, name, None)
        for c in child if isinstance(child, list) else [child] if isinstance(child, ft.Control) else []:
            yield from raid_controls(c)


def test_a_raid_card_tells_a_shiny_jumbo_boss_by_its_title_and_tags():
    """Both cards put the sparkles and the Jumbo mark beside the name; the raid's own card also tags
    them, while the finder's compact card keeps its facts to one row."""
    import flet as ft
    from gui.views import raid_seed
    from pokeldn.sv import raid_encounter, raid_search
    app = SimpleNamespace(settings=SimpleNamespace(sprites=False), page=None, ui=lambda fn: fn())
    context = raid_search.contexts("scarlet", "paldea", "5star", "standard")[0]
    row, stars = raid_search._drawer(context)(0)
    boss = dict(raid_encounter.boss_fields(0, row), trainer_id=0, secret_id=0, pid=0, scale=0xFF)
    for compact, tags in ((True, []), (False, ["Shiny", "Jumbo mark"])):
        card = list(raid_controls(raid_seed.boss_card(app, 0, stars, boss, context, compact=compact)))
        assert [c.value for c in card if isinstance(c, ft.Text) and c.value in ("Shiny", "Jumbo mark")] == tags
        assert [c.tooltip for c in card if isinstance(c, ft.Image) and c.tooltip] == ["Shiny", "Jumbo mark"]


def test_the_raid_card_lists_its_scripted_actions_after_its_rewards(monkeypatch):
    """Under the rewards, the boss's scripted actions: the shield, then each action with the HP or time
    left that brings it, its moves named once the builder answers."""
    import flet as ft
    from gui.views import raid_seed
    from pokeldn import pokemon as builder
    from pokeldn.sv import raid_event, raid_search
    app = SimpleNamespace(settings=SimpleNamespace(sprites=False), page=None, ui=lambda fn: fn())
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    naming = []
    monkeypatch.setattr(raid_seed.threading, "Thread",
                        lambda target, args, daemon: SimpleNamespace(start=lambda: naming.append((target, args))))
    monkeypatch.setattr(DISPLAY_SERVICE, "names", lambda game, kind: {
        "bag": [{"id": 1127, "name": "Exp. Candy XL"}], "moves": [{"id": 315, "name": "Overheat"}]}[kind])
    desc = [2500, 65, 55, 9999, 40, 0, 0, 20, 70, 30, 3, 1, 99, 315, 2, 2, 70, 0] + [0] * 19
    charizard = dict(species=6, form=0, ability=4, flawless_ivs=0, level=100, capture_level=100,
                     moves=[406, 0, 0, 0], tera=17, stars=7, rate=1, identifier=1, fixed_rewards="1",
                     lottery_rewards="1", boss_desc=desc, evs=[0] * 6, rom=0, group=1, capture_rate=1,
                     ivs=[31] * 6, gender=None, nature=None, shiny=1, scale_type=0, scale=0, held_item=0, time=None)
    event = raid_event.Event(1, "", (charizard,), {"1": [dict(category=0, item=1127, amount=3, probability=100,
                                                              subject=0)]}, {"1": []}, (1,) + (0,) * 9)
    context = raid_search.contexts(event=event)[0]
    picker = raid_seed.RaidSeedPicker(app, "00000001", lambda _v: None, lambda: context, lambda _c: None)
    texts = lambda: [c.value for c in raid_controls(picker.preview) if isinstance(c, ft.Text)]
    shown = texts()
    assert shown.index("The raid's own rewards") < shown.index("Scripted actions")
    assert "Naming the moves..." in shown
    target, args = naming.pop()
    target(*args)
    shown = texts()
    actions = shown[shown.index("Scripted actions") + 1:]
    assert actions == ["Shield activation", "65%", "HP remaining", "55%", "time remaining",
                       "Charizard uses Overheat", "99%", "time remaining",
                       "Players' stats & status reset", "70%", "HP remaining"]
    assert "Exp. Candy XL" in shown
    no_actions = dict(charizard, boss_desc=[500] + [0] * 36)
    picker.context = lambda: raid_search.contexts(event=raid_event.Event(
        1, "", (no_actions,), event.fixed, event.lottery, event.dens))[0]
    picker._show("00000001", update=False)
    assert texts()[-1] == "No scripted actions."


GIFT_EVENTS = [
    {"key": "0503-964-0-10", "card_id": 503, "title": "Gavin’s Palafin Gift", "date": "2023-04-13",
     "species": "Palafin", "species_id": 964, "form": "", "level": 50, "shiny": "never", "tera": "Water",
     "ot": "Gavin", "language": 0, "ball": "Cherish Ball", "held_item": "Mystic Water",
     "moves": ["Jet Punch", "Wave Crash", "Haze", "Protect"], "legal": True, "home_tracker": ""},
    {"key": "9021-906-0-11", "card_id": 9021, "title": "Pokémon HOME Gift", "date": "2023-05-30",
     "species": "Sprigatito", "species_id": 906, "form": "", "level": 5, "shiny": "never", "tera": "Grass",
     "ot": "", "language": 0, "ball": "Poke Ball", "held_item": "", "moves": ["Scratch", "Tail Whip", "Leafage"],
     "legal": True, "home_tracker": "empty"},
    {"key": "1501-25-0-2", "card_id": 1501, "title": "Flying Tera Type Pikachu Gift", "date": "2022-11-17",
     "species": "Pikachu", "species_id": 25, "form": "", "level": 5, "shiny": "never", "tera": "Flying",
     "ot": "", "language": 0, "ball": "Poke Ball", "held_item": "", "moves": ["Fly", "Tail Whip"],
     "legal": True, "home_tracker": ""},
]
GIFT_COPIES = {
    "0503-964-0-10": {"file": "palafin.pk9", "title": "Gavin’s Palafin Gift", "species": "Palafin",
                      "species_id": 964, "form": "", "level": 50, "shiny": False, "nature": "Adamant",
                      "ability": "Zero to Hero", "ball": "Cherish Ball", "held_item": "Mystic Water", "legal": True,
                      "home_tracker": "", "encounter": "Event Gift (WC9)",
                      "moves": ["Jet Punch", "Wave Crash", "Haze", "Protect"], "ot": "Gavin", "your_ot": False,
                      "refused": ""},
    "9021-906-0-11": {"file": "sprigatito.pk9", "title": "Pokémon HOME Gift", "species": "Sprigatito",
                      "species_id": 906, "form": "", "level": 5, "shiny": False, "nature": "Jolly",
                      "ability": "Protean", "ball": "Poke Ball", "held_item": "", "legal": True,
                      "home_tracker": "empty", "encounter": "Event Gift (WC9)",
                      "moves": ["Scratch", "Tail Whip", "Leafage"], "ot": "ASH", "your_ot": True, "refused": ""},
}
GIFT_TRAINER = {"ot": "ASH", "tid": 1, "sid": 2, "language": 2, "gender": 0}


def gift_picker(monkeypatch, value=None, view=None):
    """The Mystery Gift - Simulated card the Games view draws, its events listed, over a stubbed builder:
    -> (card, a call that runs the worker it started last, the builder's requests, the values it saved)."""
    import flet as ft
    from gui.views import event_gifts
    from pokeldn import pokemon as builder
    from pokeldn.app.catalog import GAMES
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)

    async def scrolled(self, **_):
        return None
    monkeypatch.setattr(ft.Column, "scroll_to", scrolled)
    work = []   # the picker's own workers; the sprites' (they take args) never run
    monkeypatch.setattr(event_gifts.threading, "Thread", lambda target, daemon, args=None: SimpleNamespace(
        start=lambda: args is None and work.append(target)))
    asked = []
    monkeypatch.setattr(DISPLAY_SERVICE, "gift_events",
                        lambda game, who: asked.append((game, who)) or GIFT_EVENTS)
    monkeypatch.setattr(DISPLAY_SERVICE, "gift_event", lambda game, key, who:
                        asked.append((game, key, who)) or GIFT_COPIES[key])
    app = SimpleNamespace(settings=SimpleNamespace(sprites=False, trainer=lambda game: GIFT_TRAINER),
                          page=None, ui=lambda fn: fn())
    saved = []
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-gift-host")
    view = view or SimpleNamespace(app=app, game=SimpleNamespace(key="sv"),
                                   values={tool.fields[0].key: value},
                                   set_value=lambda field, value: saved.append(value))
    view.app = app
    app.settings.save = lambda: saved.append(dict(view.values))
    control = GamesView.input(view, tool.fields[0])
    work.pop()()
    return control, lambda: work.pop()(), asked, saved


def gift_texts(control) -> list[str]:
    import flet as ft
    return [c.value for c in raid_controls(control) if isinstance(c, ft.Text)]


def gift_tile(control, species: str):
    """The tile of the gift whose Pokemon line starts with `species`."""
    import flet as ft
    return next(c for c in raid_controls(control) if isinstance(c, ft.Container) and c.on_click
                and any(x.value.startswith(f"{species} ·") for x in raid_controls(c) if isinstance(x, ft.Text)))


def gift_search(control, typed: str) -> None:
    import asyncio
    import flet as ft
    search = next(c for c in raid_controls(control) if isinstance(c, ft.TextField))
    search.value = typed
    asyncio.run(search.on_change(None))


def test_the_mystery_gift_card_finds_an_event_pokemon_and_offers_a_fresh_copy(monkeypatch):
    """Mystery Gift - Simulated: the game's event Pokemon as tiles, found by anything a tile shows; the
    one picked is made for the app's trainer and becomes the trade's offer."""
    control, run, asked, saved = gift_picker(monkeypatch)
    assert asked == [("sv", GIFT_TRAINER)]
    assert {"Gavin’s Palafin Gift", "Palafin · Lv 50 · Tera Water · Mystic Water",
            "OT Gavin · 13 Apr 2023", "Your OT · 17 Nov 2022",
            "3 of 3 event Pokemon, newest first"} <= set(gift_texts(control))
    for typed, count in (("gavin haze", 1), ("tera flying 2022", 1), ("shiny", 0)):
        gift_search(control, typed)
        assert f"{count} of 3 event Pokemon, newest first" in gift_texts(control)
    gift_search(control, "")
    gift_tile(control, "Palafin").on_click(None)
    run()
    assert asked[-1] == ("sv", "0503-964-0-10", GIFT_TRAINER)
    assert {k: saved[-1][0][k] for k in ("file", "event", "species", "legal", "your_ot")} == {
        "file": "palafin.pk9", "event": "0503-964-0-10", "species": 964, "legal": True, "your_ot": False}
    assert {"Legal", "Jet Punch, Wave Crash, Haze, Protect · OT Gavin"} <= set(gift_texts(control))
    assert gift_tile(control, "Palafin").border.top.color == t.BLUE


def test_a_gift_the_trainer_could_not_receive_says_why_and_is_not_picked(monkeypatch):
    """A card no save in the trainer's language received (pokeldn.pokemon.Service.gift_event, refused): its tile
    is illegal and says why, and picking it leaves the offer as it was, saying why."""
    why = "card 1501 gave it in Japanese alone, never to a save in English"
    pikachu = next(e for e in GIFT_EVENTS if e["key"] == "1501-25-0-2")
    monkeypatch.setitem(pikachu, "legal", False)
    monkeypatch.setitem(pikachu, "refused", why)
    monkeypatch.setitem(GIFT_COPIES, "1501-25-0-2", {"title": pikachu["title"], "legal": True, "your_ot": True,
                                                     "refused": why})
    control, run, asked, saved = gift_picker(monkeypatch)
    assert f"Illegal: {why}" in gift_texts(control)
    gift_tile(control, "Pikachu").on_click(None)
    run()
    assert asked[-1] == ("sv", "1501-25-0-2", GIFT_TRAINER) and saved == []
    assert f"Your trainer from Settings cannot receive this gift: {why}." in gift_texts(control)


def remove_gift(control, at=0):
    buttons = [c for c in raid_controls(control) if getattr(c, "tooltip", None) == "Remove this gift"]
    buttons[at].on_click(None)


def test_event_queue_restores_a_single_saved_gift_and_keeps_duplicates_in_trade_order(monkeypatch):
    from pokeldn import pokemon as builder
    legacy = dict(GIFT_COPIES["0503-964-0-10"], species=964, event="0503-964-0-10")
    control, run, asked, saved = gift_picker(monkeypatch, legacy)
    calls = []

    def make(game, key, who):
        calls.append(key)
        return dict(GIFT_COPIES[key], file=f"copy-{len(calls)}.pk9")
    monkeypatch.setattr(DISPLAY_SERVICE, "gift_event", make)
    for name in ("Sprigatito", "Palafin", "Palafin", "Sprigatito", "Palafin"):
        gift_tile(control, name).on_click(None)
        run()
    assert [v["file"] for v in saved[-1]] == ["palafin.pk9", *[f"copy-{n}.pk9" for n in range(1, 6)]]
    assert "6 of 6 gifts queued, traded in this order · queue full" in gift_texts(control)
    assert gift_tile(control, "Palafin").disabled
    gift_tile(control, "Palafin").on_click(None)
    assert len(calls) == 5
    remove_gift(control, 2)
    assert [v["file"] for v in saved[-1]] == ["palafin.pk9", "copy-1.pk9", "copy-3.pk9",
                                              "copy-4.pk9", "copy-5.pk9"]
    assert not gift_tile(control, "Palafin").disabled
    gift_tile(control, "Sprigatito").on_click(None)
    run()
    assert saved[-1][-1]["file"] == "copy-6.pk9"
    for _ in range(6):
        remove_gift(control)
    assert saved[-1] == [] and "Choose up to 6 gifts; they trade in this order." in gift_texts(control)


def test_removing_a_gift_while_another_is_being_made_keeps_the_progress_visible(monkeypatch):
    control, run, asked, saved = gift_picker(monkeypatch)
    gift_tile(control, "Palafin").on_click(None)
    run()
    gift_tile(control, "Sprigatito").on_click(None)
    remove_gift(control)
    assert "Making a fresh copy..." in gift_texts(control)
    assert gift_tile(control, "Palafin").disabled
    run()
    assert [v["event"] for v in saved[-1]] == ["9021-906-0-11"]
    assert "Making a fresh copy..." not in gift_texts(control)


def test_a_gift_build_finishing_after_navigation_saves_to_its_original_tool(monkeypatch):
    original, other = {}, {"--trade-offer": {"file": "other.pk9"}}
    view = SimpleNamespace(game=SimpleNamespace(key="sv"), values=original)
    view.set_value = lambda field, value: view.values.__setitem__(field.key, value)
    control, run, asked, saved = gift_picker(monkeypatch, view=view)
    gift_tile(control, "Palafin").on_click(None)
    view.values = other
    run()
    assert original["--trade-offer"][0]["event"] == "0503-964-0-10"
    assert other == {"--trade-offer": {"file": "other.pk9"}}


def test_a_gifts_form_reaches_its_browser_queue_and_session_preview(monkeypatch):
    from gui.views import games, sprites
    asked = []
    monkeypatch.setattr(sprites.CACHE, "cached", lambda species, shiny=False: asked.append(species))
    monkeypatch.setitem(GIFT_EVENTS[0], "species_id", 423)
    monkeypatch.setitem(GIFT_EVENTS[0], "form_id", 1)
    monkeypatch.setitem(GIFT_COPIES["0503-964-0-10"], "species_id", 423)
    monkeypatch.setitem(GIFT_COPIES["0503-964-0-10"], "form_id", 1)
    control, run, _, saved = gift_picker(monkeypatch)
    assert "423-east" in asked
    asked.clear()
    gift_tile(control, "Palafin").on_click(None)
    run()
    assert saved[-1][0]["form_id"] == 1 and "423-east" in asked
    panel = SimpleNamespace(offered_entries=lambda: saved[-1], offered=None, traded=0,
                            offering=ft.Container(), app=SimpleNamespace(settings=SimpleNamespace(sprites=False)))
    for entries in (saved[-1], saved[-1] * 2):
        panel.offered_entries = lambda: entries
        asked.clear()
        games.SessionPanel.render_offering(panel)
        assert asked == ["423-east"] * len(entries)


@pytest.mark.parametrize("mode", ["empty", "made"])
def test_a_home_gift_shows_what_the_home_tracker_setting_gave_it(monkeypatch, tmp_path, mode):
    """A gift HOME gave has the tracker the HOME tracker setting gives it (docs/gui.md, The HOME tracker
    setting): its tile is outlined in amber with the setting's warning, which the chosen copy shows too, and a
    trade takes it as any legal Pokemon."""
    import flet as ft
    from pokeldn import pokemon as builder
    from pokeldn.app import command
    from pokeldn.app.catalog import GAMES
    monkeypatch.setitem(GIFT_EVENTS[1], "home_tracker", mode)
    monkeypatch.setitem(GIFT_COPIES["9021-906-0-11"], "home_tracker", mode)
    warning = builder.HOME_TRACKER_WARNINGS[mode]
    control, run, asked, saved = gift_picker(monkeypatch)
    sprigatito, palafin = gift_tile(control, "Sprigatito"), gift_tile(control, "Palafin")
    assert (sprigatito.border.top.color, palafin.border.top.color) == (t.AMBER, t.BORDER)
    assert [x.value for x in raid_controls(sprigatito) if isinstance(x, ft.Text)][-1] == warning
    assert gift_texts(control).count(warning) == 1
    gift_search(control, {"empty": "tracker", "made": "deposited"}[mode])     # a word of the warning alone
    assert "1 of 3 event Pokemon, newest first" in gift_texts(control)
    gift_tile(control, "Sprigatito").on_click(None)
    run()
    assert (saved[-1][0]["legal"], saved[-1][0]["home_tracker"]) == (True, mode)
    assert {"Legal", warning} <= set(gift_texts(control))
    copy = tmp_path / "sprigatito.pk9"
    copy.write_bytes(b"")
    tools = {t.key: t for game in GAMES for t in game.tools}
    entry = dict(saved[-1][0], file=str(copy))
    assert command.missing_offer(tools["sv-gift-host"], {"--trade-offer": entry}) == ""
    entry["legal"] = False
    assert command.missing_offer(tools["sv-host"], {"--trade-offer": [entry]}) == "The Pokemon is not legal."


def test_made_for_the_receiving_player_follows_the_gift_picked(monkeypatch):
    """A gift with its card's own trainer holds Made for the receiving player off, disabled and faded, its note
    saying why; one that names its receiver gives the switch back as it was set. Picking redraws nothing."""
    import flet as ft
    from pokeldn.app.catalog import GAMES
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-gift-host")
    offer, receiver = tool.fields[:2]
    redrawn = []
    view = SimpleNamespace(tool=tool, values={}, raid_partners=None, locks=[],
                           app=SimpleNamespace(settings=SimpleNamespace(save=lambda: None)),
                           session=SimpleNamespace(refresh=lambda: None), render_body=lambda: redrawn.append(1))
    view.description = lambda f: GamesView.description(view, f)
    view.follow_locks = lambda: GamesView.follow_locks(view)
    switch, note = GamesView.input(view, receiver), t.text(GamesView.description(view, receiver), 12, t.MUTED)
    view.locks.append((receiver, switch, note))
    assert (switch.value, switch.disabled, note.value) == (True, False, receiver.help)

    GamesView.set_value(view, offer, dict(GIFT_COPIES["0503-964-0-10"], event="0503-964-0-10"))
    why = "This gift has its card's own trainer, OT Gavin, and goes as made."
    assert (switch.value, switch.disabled, switch.opacity) == (False, True, 0.45)
    assert note.value == f"{receiver.help} {why}"
    assert GamesView.input(view, receiver).disabled                  # a redraw draws it locked too
    GamesView.set_value(view, offer, dict(GIFT_COPIES["9021-906-0-11"], event="9021-906-0-11"))
    assert (switch.value, switch.disabled, switch.opacity, note.value) == (True, False, 1.0, receiver.help)
    assert redrawn == [] and receiver.key not in view.values         # the switch keeps its own setting


def test_a_switch_redraws_the_cards_only_when_another_field_follows_it(monkeypatch):
    """Made for the receiving player turns without a redraw, which would load the gift list again; a switch
    another field shows or hides with redraws the cards, and a Shiny switch turns the sprite in place."""
    from pokeldn.app.catalog import Tool
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    gift = next(t for game in GAMES for t in game.tools if t.key == "sv-gift-host")
    egg, shiny = Field("--egg", "Egg", "switch"), Field("--shiny", "Shiny", "switch", shiny=True)
    species = Field("--species", "Species", "species", default="25")
    own = Tool("own", "Own", "own.py", "", (), (egg, Field("--steps", "Hatch steps", requires="--egg"), shiny,
                                                 species))
    redrawn, shown = [], []

    def view_of(tool):
        view = SimpleNamespace(tool=tool, values={}, raid_partners=None, locks=[], app=SimpleNamespace(
            settings=SimpleNamespace(save=lambda: None)), session=SimpleNamespace(refresh=lambda: None),
            render_body=lambda: redrawn.append(tool.key), cards=SimpleNamespace(update=lambda: None),
            sprites={species.key: SimpleNamespace(show=lambda *a: shown.append(a))})
        for name in ("set_value", "switched", "shiny", "description", "follow_locks"):
            setattr(view, name, getattr(GamesView, name).__get__(view))
        return view

    def turn(view, field, on):
        GamesView.input(view, field).on_change(SimpleNamespace(control=SimpleNamespace(value=on)))
        return view.values[field.key]
    view = view_of(gift)
    assert (turn(view, gift.fields[1], False), turn(view, gift.fields[1], True), redrawn) == (False, True, [])
    view = view_of(own)
    assert (turn(view, shiny, True), redrawn, shown) == (True, [], [(25, True)])
    assert (turn(view, egg, True), redrawn) == (True, ["own"])


def test_a_short_gift_list_shows_whole_and_a_long_one_scrolls(monkeypatch):
    """Ten gifts or fewer show whole, as Legends Z-A's eight do; more scroll in a box of their own, until a
    search narrows them."""
    from gui.views import event_gifts

    def boxed(control) -> bool:
        return any(isinstance(c, ft.Container) and c.height == event_gifts.BOX for c in raid_controls(control))
    assert not boxed(gift_picker(monkeypatch)[0])
    many = [dict(GIFT_EVENTS[2], key=f"1501-25-0-{n}") for n in range(event_gifts.FIT)]
    monkeypatch.setitem(globals(), "GIFT_EVENTS", GIFT_EVENTS + many)
    control = gift_picker(monkeypatch)[0]
    assert boxed(control)
    gift_search(control, "gavin")
    assert not boxed(control)


def test_find_a_raid_offers_its_default_seeds_from_any_first_seed(monkeypatch):
    """The finder offers its default count of seeds (a hundred million with the compiled scan), and its
    shuffle picks a random first seed."""
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
    controls = list(raid_controls(shown[0].content))
    labels = [c for c in controls if isinstance(c, ft.Column) and c.controls and isinstance(c.controls[0], ft.Container)
              and isinstance(c.controls[0].content, ft.Text)]
    first = next(c.controls[1] for c in labels if c.controls[0].content.value == "First seed")
    count = next(c.controls[1] for c in labels if c.controls[0].content.value == "Seeds to search")
    assert count.value == str(raid_search.DEFAULT_COUNT)
    start, shuffle = first.controls
    assert start.value == "00000000" and shuffle.tooltip == "Start at a random seed"
    monkeypatch.setattr(type(start), "update", lambda self: None)
    values = set()
    for _ in range(5):
        shuffle.on_click(None)
        assert raid_seed.seed_of(start.value) is not None and len(start.value) == 8
        values.add(start.value)
    assert len(values) > 1


def test_the_finder_greys_out_the_size_marks_an_event_rules_out(monkeypatch):
    """A five-star Pikachu drawn between 240 and 255 can take the Jumbo mark, never the Mini mark; a
    six-star Charizard always 128 neither, so picking six stars greys both out and lets Jumbo go."""
    import flet as ft
    from gui.views import raid_seed
    from pokeldn.sv import raid_event, raid_search
    shown = []
    app = SimpleNamespace(page=SimpleNamespace(show_dialog=shown.append, pop_dialog=lambda: None),
                          ui=lambda f: f())
    monkeypatch.setattr(raid_search, "FAST", False)
    monkeypatch.setattr(ft.Dropdown, "update", lambda self: None)
    base = dict(form=0, ability=0, flawless_ivs=0, level=12, capture_level=12, moves=[33, 0, 0, 0], tera=1,
                rate=1, fixed_rewards="1", lottery_rewards="1", boss_desc=[500] + [0] * 36, evs=[0] * 6, rom=0,
                group=1, capture_rate=1, ivs=None, gender=None, nature=None, shiny=0, held_item=0, time=None)
    event = raid_event.Event(1, "", (dict(base, identifier=1, species=25, stars=5, scale_type=5, scale=0),
                                     dict(base, identifier=2, species=6, stars=6, scale_type=6, scale=128)),
                             {"1": []}, {"1": []}, (1,) + (0,) * 9)
    context = raid_search.contexts(event=event)[0]
    picker = raid_seed.RaidSeedPicker(app, "", lambda _v: None, lambda: context, lambda _c: None)
    picker._open(None)
    dropdowns = [c for c in raid_controls(shown[0].content) if isinstance(c, ft.Dropdown)]
    size = next(d for d in dropdowns if d.options[0].text == "Eligible or not")
    stars = next(d for d in dropdowns if d.options[0].text == "Any stars")
    greyed = lambda: [o.text for o in size.options if o.disabled]
    assert greyed() == ["Mini mark"]
    size.value = "jumbo"
    stars.value = "6"
    stars.on_select(None)
    assert greyed() == ["Any mark", "Mini mark", "Jumbo mark"] and size.value == "any"
    stars.value = "any"
    stars.on_select(None)
    assert greyed() == ["Mini mark"]


def test_the_finder_s_bar_shows_how_far_a_search_is(monkeypatch):
    """Under the status, a bar moves until the first seeds are counted, then fills with the share
    searched, and goes once the search is done. Most desired rewards with no wanted reward is refused
    before any search starts."""
    import flet as ft
    from gui.views import raid_seed
    from pokeldn.sv import raid_search
    shown = []
    app = SimpleNamespace(page=SimpleNamespace(show_dialog=shown.append, pop_dialog=lambda: None),
                          ui=lambda f: f())
    monkeypatch.setattr(raid_search, "FAST", False)
    monkeypatch.setattr(ft.BaseControl, "update", lambda self: None)
    monkeypatch.setattr(raid_seed.threading, "Thread", lambda target, daemon: SimpleNamespace(start=target))
    picker = raid_seed.RaidSeedPicker(app, "", lambda _v: None,
                                      lambda: {"version": "violet", "map_name": "paldea", "progress": "6star",
                                               "content": "standard"}, lambda _c: None)
    picker._open(None)
    bar = next(c for c in raid_controls(shown[0].content) if isinstance(c, ft.ProgressBar))
    seen = []

    def search(*_args, progress, **_kwargs):
        seen.append((bar.visible, bar.value))
        progress(25, 100)
        seen.append((bar.visible, bar.value))
        return []
    monkeypatch.setattr(raid_search, "search", search)
    count = next(c for c in raid_controls(shown[0].content)
                 if isinstance(c, ft.TextField) and c.value == str(raid_search.DEFAULT_COUNT))
    count.value = "1000"
    assert not bar.visible
    rank = next(c for c in raid_controls(shown[0].content)
                if isinstance(c, ft.Dropdown) and c.options[0].text == "Lowest overall bulk")
    rank.value = "rewards"
    shown[0].actions[-1].on_click(None)
    status = next(c for c in raid_controls(shown[0].content) if isinstance(c, ft.Text)
                  and c.value.startswith("Most desired rewards"))
    assert not seen and not bar.visible and status.color == raid_seed.t.RED
    rank.value = "overall"
    shown[0].actions[-1].on_click(None)
    assert seen == [(True, None), (True, 0.25)] and not bar.visible


def test_the_finder_tells_how_far_a_search_is_and_how_long_it_has_left():
    from gui.views.raid_seed import duration, searching
    assert [duration(s) for s in (0, 59.9, 60, 200, 3600, 7500)] == [
        "0 s", "59 s", "1 min 0 s", "3 min 20 s", "1 h 0 min", "2 h 5 min"]
    assert searching(0, 1000, 0) == "Searching 0 of 1,000 seeds..."
    assert searching(500, 1000, 2) == "Searching 500 of 1,000 seeds, 250 a second, 2 s left..."
    assert searching(50_000_000, 1 << 32, 2) == (
        "Searching 50,000,000 of 4,294,967,296 seeds, 25.0 million a second, 2 min 49 s left...")
    assert searching(28_448_764_162, 180_388_626_432, 28.209) == (
        "Searching 28,448,764,162 of 180,388,626,432 seeds, 1.01 billion a second, 2 min 30 s left...")
    assert "1.00 billion a second" in searching(999_960_000, 1 << 32, 1)
    assert "999.9 million a second" in searching(999_900_000, 1 << 32, 1)


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


def test_every_docs_fragment_link_scrolls_to_a_keyed_heading():
    """A heading renamed without its links leaves a link that opens the page and scrolls nowhere."""
    import re
    from gui.views import docs
    from gui.views.widgets import MarkdownDocument
    keys, bodies = {}, {}
    for name in os.listdir(docs.DOCS):
        if name.endswith(".md"):
            with open(os.path.join(docs.DOCS, name), encoding="utf-8") as f:
                _, bodies[name] = docs.split_front_matter(f.read())
            document = MarkdownDocument(None, None)
            document.set_value(bodies[name])
            keys[name] = {c.key.value for c in document.control.controls if isinstance(c.key, ft.ScrollKey)}
    missing = [(name, link) for name, body in bodies.items()
               for target, fragment in re.findall(r"\]\((?!https?://)([^)#\s]*)#([^)\s]+)\)", body)
               if (os.path.basename(target) or name) in keys and fragment not in keys[os.path.basename(target) or name]
               for link in [f"{target}#{fragment}"]]
    assert missing == []


def test_docs_search_finds_a_section_under_its_heading():
    from gui.views import docs
    found = docs.search(docs.index(docs.pages(), "Start here"), "host watchdog")
    assert (found[0].file, found[0].anchor) == ("hardware_esp32.md", "the-host-watchdog")
    runs = docs.snippet(found[0].text, ["host", "watchdog"])
    assert any(hit and part.lower() in ("host", "watchdog") for part, hit in runs)

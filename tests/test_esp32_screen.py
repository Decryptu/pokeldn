"""The board's screen: the host's DISPLAY payloads run through the firmware's own scene code
(firmware/esp32/main/scene.c, built for this machine), and the sprite conversion run on PNG bytes."""
import shutil
import struct
import zlib

import pytest

from pokeldn.app import screen
from pokeldn.ldn import esp32

needs_cc = pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from screen_preview import Scene
    return Scene(str(tmp_path_factory.mktemp("scene"))).lib


@pytest.fixture
def scene(built):
    from screen_preview import Radio, Scene
    s = Scene.__new__(Scene)
    s.lib, s.radio, s.now = built, Radio(), 1000
    built.scene_reset()
    return s


def lit(fb, x, y):
    from screen_preview import pixel
    return pixel(fb, x, y)


@needs_cc
def test_a_sprite_lands_bit_for_bit_where_the_trade_scene_draws_it(scene):
    # Odd width and a pattern in each row: a wrong bit order, stride or row order moves pixels.
    rows = [[(x * 3 + y * 5) % 7 < 3 for x in range(13)] for y in range(9)]
    assert scene.command(esp32.display_sprite_payload("ours", rows))
    assert scene.command(esp32.display_show_payload("trade", 0, "Sw/Sh", "Pikachu"))
    fb = scene.frame()            # now 1000: the bob is at rest
    x0, y0 = 96 - 13 // 2, 64 - 9
    assert [[lit(fb, x0 + x, y0 + y) for x in range(13)] for y in range(9)] == rows
    assert not any(lit(fb, x, y) for x in range(x0 - 3, x0 + 16) for y in range(y0 - 3, y0))


@pytest.fixture
def small(scene, built):
    built.scene_panel(1)          # PANEL_72X40
    yield scene
    built.scene_panel(0)


@needs_cc
def test_the_72x40_panel_draws_a_sprite_at_half_size_inside_its_window(small):
    # Uniform 2x2 blocks halve exactly; a wrong bit order, block or window offset moves pixels.
    half = [[(x * 3 + y * 5) % 7 < 3 for x in range(7)] for y in range(5)]
    rows = [[half[y // 2][x // 2] for x in range(14)] for y in range(10)]
    assert small.command(esp32.display_sprite_payload("ours", rows))
    assert small.command(esp32.display_show_payload("trade", 0, "Sw/Sh", "Pikachu"))
    fb = small.frame()            # now 1000: the bob is at rest
    x0, y0 = 30 + 36 - 7 // 2, 12 + 40 - 5
    assert [[lit(fb, x0 + x, y0 + y) for x in range(7)] for y in range(5)] == half


@needs_cc
def test_the_72x40_panel_draws_inside_its_window_whenever_the_full_one_draws(small, built):
    from screen_preview import Radio, session
    frames = session(small, 25, 150, 151)
    built.scene_panel(0)
    built.scene_reset()
    small.radio, small.now = Radio(), 1000
    full = session(small, 25, 150, 151)
    inside = {(x, y) for x in range(30, 102) for y in range(12, 52)}
    for fb, whole in zip(frames, full, strict=True):
        assert not any(lit(fb, x, y) for x in range(128) for y in range(64) if (x, y) not in inside)
        assert any(lit(fb, x, y) for x, y in inside) == any(whole)


@needs_cc
def test_malformed_commands_are_refused(scene):
    good = esp32.display_sprite_payload("theirs", [[True] * 8] * 2)
    assert scene.command(good)
    assert not scene.command(good[:-1])                               # rows cut short
    assert not scene.command(bytes([1, 1, 65, 1]) + bytes(9))         # wider than 64
    assert not scene.command(bytes([1, 3, 8, 1, 0]))                  # no such slot
    assert not scene.command(bytes([0, 6, 0, 0]))                     # no such show
    assert not scene.command(b"")
    with pytest.raises(ValueError):
        esp32.display_sprite_payload("ours", [[True] * 65])


def frame_of(built, show_payloads, now):
    from screen_preview import Radio, Scene
    s = Scene.__new__(Scene)
    s.lib, s.radio, s.now = built, Radio(), now
    built.scene_reset()
    for p in show_payloads:
        s.command(p)
    return s.frame()


@needs_cc
def test_a_next_offer_waits_for_the_received_animation(scene, built):
    traded = esp32.display_show_payload("traded", 10, "Sw/Sh", "Mewtwo")    # reveal at 10 s
    trade = esp32.display_show_payload("trade", 0, "Sw/Sh", "Eevee")
    scene.command(traded)
    scene.advance(2000)
    scene.command(trade)              # the launcher's next queued offer, sent at once
    scene.advance(17000)              # the received Pokemon is on screen
    assert scene.frame() != frame_of(built, [trade], scene.now)
    scene.advance(3000)               # past the reveal, 1.6 s of ball and 10 s of the Pokemon
    assert scene.frame() == frame_of(built, [trade], scene.now)


def played(built, payloads_at, until):
    """The frame at `until` ms of a scene given each payload at its own ms."""
    from screen_preview import Radio, Scene
    s = Scene.__new__(Scene)
    s.lib, s.radio, s.now = built, Radio(), 1000
    built.scene_reset()
    for at, payload in payloads_at:
        s.now = 1000 + at
        s.command(payload)
    s.now = 1000 + until
    return s.frame()


@needs_cc
def test_the_console_finishing_early_brings_the_pokemon_in_at_once(built):
    def traded(wait):
        return esp32.display_show_payload("traded", wait, "BD/SP", "Zubat")
    arrived = esp32.display_show_payload("arrived")
    # A 20 s wait cut at 5 s shows at 7 s what a 5 s wait shows; uncut, it is still trading.
    assert played(built, [(0, traded(20)), (5000, arrived)], 7000) == played(built, [(0, traded(5))], 7000)
    assert played(built, [(0, traded(20))], 7000) != played(built, [(0, traded(5))], 7000)
    # After the reveal it changes nothing.
    assert played(built, [(0, traded(5)), (9000, arrived)], 9500) == played(built, [(0, traded(5))], 9500)


@needs_cc
def test_a_trade_scene_ends_when_the_session_does_and_not_before_it_starts(scene, built):
    trade = esp32.display_show_payload("trade", 0, "Sc/Vi", "Sprigatito")
    scene.command(trade)              # a launcher shows its offer before starting the radio
    assert scene.frame() == frame_of(built, [trade], scene.now)
    scene.radio.mode = 3              # hosting
    scene.advance(1000)
    scene.frame()
    scene.radio.mode = 0              # the launcher stopped the radio
    scene.advance(1000)
    assert scene.frame() == frame_of(built, [], scene.now)


ON, DIM, OFF = 0, 1, 2


def power_after(scene, ms):
    scene.advance(ms)
    scene.frame()
    return scene.power


@needs_cc
def test_an_idle_screen_dims_after_a_minute_and_goes_dark_after_ten(scene):
    assert power_after(scene, 0) == ON
    assert power_after(scene, 59_000) == ON
    assert power_after(scene, 2_000) == DIM
    assert power_after(scene, 538_000) == DIM
    assert power_after(scene, 2_000) == OFF


@needs_cc
def test_a_running_radio_keeps_the_screen_lit_for_a_minute_past_its_session(scene):
    scene.radio.mode = 3              # a host waiting twenty minutes for a console
    for _ in range(20):
        assert power_after(scene, 60_000) == ON
    scene.radio.mode = 0
    assert power_after(scene, 59_000) == ON
    assert power_after(scene, 2_000) == DIM


@pytest.mark.parametrize("wake", ["command", "session", "button", "radio"])
@needs_cc
def test_anything_happening_wakes_a_dark_screen_on_its_next_frame(scene, wake):
    scene.frame()
    assert power_after(scene, 700_000) == OFF
    if wake == "command":
        scene.command(esp32.display_show_payload("trade", 0, "FR/LG", "Pikachu"))
    elif wake == "session":
        scene.lib.scene_reset()       # HELLO
    elif wake == "button":
        scene.radio.presses += 1
    else:
        scene.radio.mode = 1
    assert power_after(scene, 50) == ON
    scene.radio.mode = 0
    assert power_after(scene, 59_000) == ON


@needs_cc
def test_the_idle_scene_moves_two_pixels_a_minute_and_a_trade_does_not(scene, built):
    first = scene.frame()
    scene.advance(60_000)             # the Poke Ball's bob is in the same phase
    moved = scene.frame()
    assert moved != first
    assert all(lit(moved, x + 2, y) == lit(first, x, y) for x in range(126) for y in range(64))
    trade = esp32.display_show_payload("trade", 0, "FR/LG", "Pikachu")
    assert frame_of(built, [trade], 1000) == frame_of(built, [trade], 61_000)


def png(rows, palette):
    """An 8-bit palette PNG with entry 0 clear."""
    raw = b"".join(b"\0" + bytes(r) for r in rows)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 3, 0, 0, 0))
            + chunk(b"PLTE", b"".join(bytes(c) for c in palette)) + chunk(b"tRNS", b"\0")
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def body(width, height, fill, outline=1, line_row=None, line=3, pad=6):
    """A filled box with a one-pixel outline, a dark inner line, on a clear margin."""
    rows = [[0] * (width + 2 * pad) for _ in range(height + 2 * pad)]
    for y in range(height):
        for x in range(width):
            edge = x in (0, width - 1) or y in (0, height - 1)
            rows[pad + y][pad + x] = outline if edge else line if y == line_row else fill
    return rows


@pytest.mark.parametrize("colour", [(250, 210, 60), (60, 60, 80)], ids=["bright", "dark"])
def test_a_sprite_is_lit_inside_its_outline_and_dark_on_its_inner_lines(colour):
    palette = [(0, 0, 0), (16, 16, 16), colour, (24, 20, 20)]
    bits = screen.to_bits(png(body(20, 12, 2, line_row=5), palette))
    assert (len(bits[0]), len(bits)) == (20, 12)                       # cropped to the box
    assert not any(bits[0]) and not any(r[0] for r in bits)            # the outline is dark
    assert all(bits[3][1:-1]) and all(bits[8][1:-1])                   # the body is lit, dark or not
    assert not any(bits[5])                                            # the inner line is dark


def test_a_large_sprite_is_scaled_to_fit_and_keeps_its_outline():
    palette = [(0, 0, 0), (16, 16, 16), (200, 200, 220)]
    bits = screen.to_bits(png(body(90, 70, 2), palette))
    assert len(bits[0]) <= 64 and len(bits) <= 64 and len(bits[0]) >= 60
    assert not any(bits[0]) and all(bits[len(bits) // 2][2:-2])


def test_text_is_reduced_to_the_screens_ascii():
    assert screen.ascii_text("Salamèche") == "Salameche"
    payload = esp32.display_show_payload("trade", 0, "A" * 40, screen.ascii_text("Évoli"))
    assert payload == struct.pack("<BBH", 0, 1, 0) + b"A" * 21 + b"\0Evoli\0"


@needs_cc
def test_an_offer_reaches_the_screen_through_the_launchers_radio(monkeypatch, scene):
    from pokeldn.ldn import esp32_sim, esp32_wlan
    rows = [[x == y for x in range(10)] for y in range(10)]
    monkeypatch.setattr(screen, "sprite_bits", lambda species, size=64: rows if species == 25 else None)
    monkeypatch.setenv("POKELDN_RADIO", "esp32:sim")
    board = esp32_sim.SimulatedBoard(esp32_sim.Air())
    monkeypatch.setattr(esp32_wlan, "_radio", esp32.Radio(board.host_stream()))
    try:
        assert screen.offer("swsh", species=25, name="Pikachû")
        assert screen.drain(5)
        esp32_wlan._radio.drain()
    finally:
        esp32_wlan._radio.close()
    assert board.displays == [esp32.display_sprite_payload("ours", rows),
                              esp32.display_show_payload("trade", 0, "Sw/Sh", "Pikachu")]
    for payload in board.displays:
        assert scene.command(payload)
    fb = scene.frame()
    assert all(lit(fb, 91 + i, 54 + i) for i in range(10)) and not lit(fb, 92, 54)

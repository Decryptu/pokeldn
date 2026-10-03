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
    assert scene.command(esp32.display_show_payload("trade", 0, "Sword/Shield", "Pikachu"))
    fb = scene.frame()            # now 1000: the bob is at rest
    x0, y0 = 96 - 13 // 2, 64 - 9
    assert [[lit(fb, x0 + x, y0 + y) for x in range(13)] for y in range(9)] == rows
    assert not any(lit(fb, x, y) for x in range(x0 - 3, x0 + 16) for y in range(y0 - 3, y0))


@needs_cc
def test_malformed_commands_are_refused(scene):
    good = esp32.display_sprite_payload("theirs", [[True] * 8] * 2)
    assert scene.command(good)
    assert not scene.command(good[:-1])                               # rows cut short
    assert not scene.command(bytes([1, 1, 65, 1]) + bytes(9))         # wider than 64
    assert not scene.command(bytes([1, 3, 8, 1, 0]))                  # no such slot
    assert not scene.command(bytes([0, 5, 0, 0]))                     # no such show
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
    traded = esp32.display_show_payload("traded", 10, "Sword/Shield", "Mewtwo")
    trade = esp32.display_show_payload("trade", 0, "Sword/Shield", "Eevee")
    scene.command(traded)
    scene.advance(2000)
    scene.command(trade)              # the launcher's next queued offer, sent at once
    scene.advance(3000)
    assert scene.frame() != frame_of(built, [trade], scene.now)
    scene.advance(5500)               # past the 10 s hold
    assert scene.frame() == frame_of(built, [trade], scene.now)


@needs_cc
def test_a_trade_scene_ends_when_the_session_does_and_not_before_it_starts(scene, built):
    trade = esp32.display_show_payload("trade", 0, "Scarlet/Violet", "Sprigatito")
    scene.command(trade)              # a launcher shows its offer before starting the radio
    assert scene.frame() == frame_of(built, [trade], scene.now)
    scene.radio.mode = 3              # hosting
    scene.advance(1000)
    scene.frame()
    scene.radio.mode = 0              # the launcher stopped the radio
    scene.advance(1000)
    assert scene.frame() == frame_of(built, [], scene.now)


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
                              esp32.display_show_payload("trade", 0, "Sword/Shield", "Pikachu")]
    for payload in board.displays:
        assert scene.command(payload)
    fb = scene.frame()
    assert all(lit(fb, 91 + i, 54 + i) for i in range(10)) and not lit(fb, 92, 54)

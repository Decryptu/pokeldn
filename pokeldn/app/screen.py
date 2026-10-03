"""The ESP32 board's optional screen: the Pokemon a trade sends and receives, and the card a Mystery
Gift delivers. docs/hardware_esp32.md, The screen.

Every call returns at once and never raises: the work (PKHeX reading a record, a sprite download)
runs in order on one daemon thread, so a trio loop may call it. A board without a screen ignores it.
"""
import os
import queue
import threading
import unicodedata

from pokeldn.app.sprites import BASE, SpriteCache, pixels
from pokeldn.app.paths import DATA

# At most 10 characters: the title shares the top row with a 64-pixel sprite.
TITLES = {"frlg": "FR/LG", "lgpe": "Let's Go", "bdsp": "BD/SP", "swsh": "Sw/Sh", "pla": "Arceus",
          "sv": "Sc/Vi", "za": "Legends ZA"}
TRADED_HOLD_S = 10          # the exchange animation takes 4.7 s; the received Pokemon stays after it
GIFTED_HOLD_S = 6
GBA_LAST = 386              # FireRed/LeafGreen draw every species to Deoxys, 64x64

# The GBA sprites suit a one-bit 64-row screen best; later species come from the default set.
GBA = SpriteCache(DATA / "sprites" / "screen-gba", f"{BASE}/versions/generation-iii/firered-leafgreen")
LATER = SpriteCache(DATA / "sprites" / "screen")

_jobs: queue.Queue = queue.Queue()
_worker: threading.Thread | None = None


def ascii_text(text: str) -> str:
    """The screen's font is ASCII: accents dropped, anything else a '?'."""
    flat = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in flat if not unicodedata.combining(c)).encode("ascii", "replace").decode()


def _luma(p) -> int:
    return (299 * p[0] + 587 * p[1] + 114 * p[2]) // 1000


def to_bits(png: bytes, size: int = 64) -> list[list[bool]] | None:
    """A sprite as one-bit rows at most `size` square: cropped to its visible pixels, scaled down by
    area when larger, lit where it is brighter than its own outline, dark along its inner lines."""
    image = pixels(png)
    if image is None:
        return None
    rows = image[2]
    seen = [(x, y) for y, row in enumerate(rows) for x, p in enumerate(row) if p[3]]
    if not seen:
        return None
    x0, x1 = min(x for x, _ in seen), max(x for x, _ in seen) + 1
    y0, y1 = min(y for _, y in seen), max(y for _, y in seen) + 1
    rows = [row[x0:x1] for row in rows[y0:y1]]
    height, width = len(rows), len(rows[0])
    if max(height, width) > size:
        f = max(height, width) / size
        scaled = []
        for ty in range(int(height / f)):
            row = []
            for tx in range(int(width / f)):
                box = [rows[y][x] for y in range(int(ty * f), max(int(ty * f) + 1, int((ty + 1) * f)))
                       for x in range(int(tx * f), max(int(tx * f) + 1, int((tx + 1) * f)))]
                shown = sorted(_luma(p) for p in box if p[3])
                # A dark third keeps an outline that crosses the box.
                row.append((shown[len(shown) // 3],) * 3 + (255,) if len(shown) * 2 >= len(box) else (0, 0, 0, 0))
            scaled.append(row)
        rows = scaled
    # The threshold follows the sprite: a dark Pokemon (Umbreon, Darkrai) keeps its body lit.
    lumas = sorted(_luma(p) for row in rows for p in row if p[3])
    cut = min(60, max(20, lumas[len(lumas) // 8] + 6))
    bits = [[bool(p[3]) and _luma(p) > cut for p in row] for row in rows]
    # Inner lines (eyes, mouth, limbs): a lit pixel well darker than its brightest neighbour goes dark.
    height, width = len(rows), len(rows[0])
    lines = [row[:] for row in bits]
    for y in range(height):
        for x in range(width):
            if not bits[y][x]:
                continue
            here = _luma(rows[y][x])
            near = [_luma(rows[j][i]) for i, j in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                    if 0 <= i < width and 0 <= j < height and rows[j][i][3]]
            if near and max(near) - here > 40 and here < 0.72 * max(near):
                lines[y][x] = False
    return lines


def sprite_bits(species: int, size: int = 64) -> list[list[bool]] | None:
    if not isinstance(species, int) or species < 1:
        return None
    from pokeldn.app import settings
    try:
        online = bool(settings.load().sprites)
    except Exception:
        online = True
    cache = GBA if species <= GBA_LAST else LATER
    cache.online = online
    data = cache.get(species) or (LATER.get(species) if cache is GBA else None)
    return to_bits(data, size) if data else None


def describe(game: str, record: bytes) -> dict:
    """{species_id, species, nickname, shiny} from PKHeX, or {} when it cannot read the record."""
    try:
        from pokeldn.pokemon import SERVICE
        return SERVICE.check_bytes(game, record)
    except Exception:
        return {}


def _name(info: dict) -> str:
    nickname, species = ascii_text(info.get("nickname", "")), ascii_text(info.get("species", ""))
    return nickname if nickname and "?" not in nickname else species


def _send(payload: bytes) -> None:
    from pokeldn.ldn import esp32_wlan
    esp32_wlan.display(payload)


def _run() -> None:
    while True:
        job = _jobs.get()
        try:
            job()
        except Exception:
            pass                # the screen is a nicety: a trade never stops for it


def _submit(job) -> bool:
    global _worker
    if not os.environ.get("POKELDN_RADIO", "").startswith("esp32:"):
        return False
    if _worker is None:
        _worker = threading.Thread(target=_run, name="esp32-screen", daemon=True)
        _worker.start()
    _jobs.put(job)
    return True


def _pokemon(slot: str, show: str, hold_s: int, game: str, record: bytes | None, species: int | None,
             name: str) -> None:
    from pokeldn.ldn import esp32
    info = describe(game, record) if record else {}
    species = species or info.get("species_id")
    bits = sprite_bits(species) if species else None
    _send(esp32.display_sprite_payload(slot, bits or []))   # an empty slot draws a Poke Ball
    _send(esp32.display_show_payload(show, hold_s, TITLES.get(game, game), name or _name(info)))


def offer(game: str, record: bytes | None = None, *, species: int | None = None, name: str = "") -> bool:
    """The Pokemon this session offers, shown until the trade completes."""
    return _submit(lambda: _pokemon("ours", "trade", 0, game, record, species, ascii_text(name)))


def received(game: str, record: bytes | None = None, *, species: int | None = None, name: str = "") -> bool:
    """A completed trade: the exchange animation, then the Pokemon that arrived."""
    return _submit(lambda: _pokemon("theirs", "traded", TRADED_HOLD_S, game, record, species,
                                    ascii_text(name)))


def gift(title: str, line: str, *, species: int | None = None) -> bool:
    """A Mystery Gift on offer: its card, with the Pokemon it carries when it carries one."""
    def job():
        from pokeldn.ldn import esp32
        bits = sprite_bits(species, 40) if species else None
        _send(esp32.display_sprite_payload("gift", bits or []))     # an empty slot draws a gift box
        _send(esp32.display_show_payload("gift", 0, ascii_text(title), ascii_text(line)))
    return _submit(job)


def delivered(line: str = "") -> bool:
    from pokeldn.ldn import esp32
    return _submit(lambda: _send(esp32.display_show_payload("gifted", GIFTED_HOLD_S, "", ascii_text(line))))


def drain(timeout: float = 10.0) -> bool:
    """Waits for the queued work: a launcher about to close its board calls it first."""
    done = threading.Event()
    if not _submit(done.set):
        return True
    return done.wait(timeout)

"""The board's screen drawn in Python: a frame-for-frame mirror of firmware/esp32/main/scene.c and
screen.c, so the app shows what the OLED shows. docs/hardware_esp32.md, The screen.
"""
import struct
from pathlib import Path

W, H = 128, 64
LIT_RGB, DARK_RGB = 0x47AEFA, 0x0B0B0D   # screen.h SCREEN_LIT_RGB and SCREEN_DARK_RGB
SCREEN_BYTES = W * H // 8
IDLE, JOINING, JOINED, HOSTING, SNIFFING = range(5)
ON, DIM, OFF = range(3)
OP_SHOW, OP_SPRITE, OP_LOBBY, OP_JOINED = range(4)
AUTO, TRADE, TRADED, GIFT, GIFTED, ARRIVED, SHOWS, LOBBY = range(8)
OURS, THEIRS, GIFT_SLOT, SLOTS = range(4)
SPRITE_W = SPRITE_H = 64
SMALL_X, SMALL_Y, SMALL_W, SMALL_H = 30, 24, 72, 40
TEXT_MAX = 22
DOTS = 24
DOT_MS, DOT_GAP_MS, LEAVE_MS, REVEAL_MS, RECEIVED_MS = 900, 70, 2100, 1600, 10000
LAND_MS, DATA_MS, WOBBLE_MS = 600, 1000, 900
TILT = (-1, -2, -1, 0, 2, 1, 0, -1, 0)
(SOUND_NONE, SOUND_LINKED, SOUND_RECALL, SOUND_SEND, SOUND_DATA, SOUND_ARRIVE, SOUND_WOBBLE, SOUND_OPEN,
 SOUND_RECEIVED, SOUND_DELIVERED) = range(10)
DIM_MS, OFF_MS, ORBIT_MS = 60000, 600000, 60000
U32 = 0xFFFFFFFF
ORBIT = ((-1, -1), (1, -1), (1, 1), (-1, 1))
RAYS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
SPOTS = ((4, 40), (98, 14), (2, 72), (100, 80), (56, 2), (40, 96))
BIT_ROWS = ((7, 5, 5, 5, 7), (2, 6, 2, 2, 7))

# screen.c FONT: ASCII 0x20..0x7e, five columns each, bit 0 at the top.
FONT = bytes.fromhex(
    "000000000000005f00000007000700147f147f14242a7f2a12231308646236495522500005030000001c224100"
    "0041221c0014083e081408083e080800503000000808080808006060000020100804023e5149453e00427f4000"
    "42615149462141454b311814127f1027454545393c4a49493001710905033649494936064949291e0036360000"
    "00563600000814224100141414141400412214080201510906324979413e7e1111117e7f494949363e41414122"
    "7f4141221c7f494949417f090909013e4149497a7f0808087f00417f41002040413f017f081422417f40404040"
    "7f020c027f7f0408107f3e4141413e7f090909063e4151215e7f09192946464949493101017f01013f4040403f"
    "1f2040201f3f4038403f631408146307087008076151494543007f41410002040810200041417f000402010204"
    "4040404040000102040020545454787f484444383844444420384444487f3854545418087e0901020c5252523e"
    "7f0804047800447d40002040443d007f1028440000417f40007c041804787c0804047838444444387c14141408"
    "081414187c7c080404084854545420043f4440203c4040207c1c2040201c3c4030403c44281028440c5050503c"
    "4464544c44000836410000007f000000413608001008081008"
)

_VERSION_FILE = Path(__file__).resolve().parents[2] / "firmware/esp32/version.txt"


def _f32(v: float) -> float:
    return struct.unpack("<f", struct.pack("<f", v))[0]


def _ease(x: float) -> float:
    x = 0.0 if x < 0 else 1.0 if x > 1 else x
    return _f32(_f32(x * x) * _f32(3 - _f32(2 * x)))


def _lerp(a: int, b: int, x: float) -> int:
    return a + int(_f32((b - a) * _ease(x)))


def _cdiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _i16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def _cut(text: bytes, n: int) -> bytes:
    return text[:n]


class _View:
    """scene.c view_t: where each scene puts its parts on one panel."""

    def __init__(self, **k):
        self.__dict__.update(k)


VIEWS = (
    _View(w=W, h=H, compact=False, cx=64, cy=36, ball=10, small_ball=6, bottom=64, link_x=2, link_y=22,
          link_r=7, cable_x0=27, cable_x1=108, cable_y=34, ring_min=8, ring_span=26, splash_x=14, splash_y=15,
          splash_r=9, logo_x=30, logo_y=9, logo_scale=2, rule_y=28, text_y=36, text_step=10),
    _View(w=SMALL_W, h=SMALL_H, compact=True, cx=36, cy=25, ball=8, small_ball=5, bottom=40, link_x=0,
          link_y=14, link_r=5, cable_x0=24, cable_x1=59, cable_y=20, ring_min=6, ring_span=14, splash_x=8,
          splash_y=8, splash_r=6, logo_x=19, logo_y=5, logo_scale=1, rule_y=17, text_y=21, text_step=10),
)


def _wobble(t: int) -> int:
    return TILT[t * 9 // WOBBLE_MS] if t < WOBBLE_MS else 0


def pixels(frame: bytes) -> list[list[bool]]:
    """The frame as 64 rows of 128 pixels."""
    return [[bool(frame[x + W * (y >> 3)] >> (y & 7) & 1) for x in range(W)] for y in range(H)]


class _Show:
    __slots__ = ("show", "hold_s", "title", "line")

    def __init__(self, show=AUTO, hold_s=0, title=b"", line=b""):
        self.show, self.hold_s, self.title, self.line = show, hold_s, title, line

    def copy(self):
        return _Show(self.show, self.hold_s, self.title, self.line)


class Scene:
    """scene.c's state and drawing; one instance stands for one board."""

    def __init__(self, version: str | None = None):
        if version is None:
            try:
                version = _VERSION_FILE.read_text(encoding="ascii").strip()
            except OSError:
                version = "unknown"
        self.version = version.encode("ascii", "replace")
        self._panel = 0
        self.wake_seen = self.wake_pending = False
        self.wake_presses = self.wake_last = 0
        self.d_at = [0] * DOTS
        self.d_dir = [0] * DOTS
        self.d_bit = [0] * DOTS
        self.d_rx = self.d_tx = self.d_last = self.d_rx_ms = self.d_tx_ms = self.d_seed = 0
        self.fb = bytearray(SCREEN_BYTES)
        self._clear_state()

    def _clear_state(self):
        self.now = _Show()
        self.next = _Show()
        self.has_next = False
        self.radio_mode = 0
        self.started = 0
        self.reveal = 0
        self.heard = -1
        self.sound = SOUND_NONE
        self.linked = False
        self.sprite = [(0, 0, b"")] * SLOTS
        self.stars = self.joined = self.seats = 0
        self.code = b""

    # ---- screen.c ----

    def pixel(self, x, y, on=True):
        if x < 0 or y < 0 or x >= W or y >= H:
            return
        i = x + W * (y >> 3)
        if on:
            self.fb[i] |= 1 << (y & 7)
        else:
            self.fb[i] &= ~(1 << (y & 7)) & 0xFF

    def fill(self, x, y, w, h, on=True):
        for j in range(y, y + h):
            for i in range(x, x + w):
                self.pixel(i, j, on)

    def rect(self, x, y, w, h):
        self.fill(x, y, w, 1)
        self.fill(x, y + h - 1, w, 1)
        self.fill(x, y, 1, h)
        self.fill(x + w - 1, y, 1, h)

    def line(self, x0, y0, x1, y1):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.pixel(x0, y0)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def circle(self, cx, cy, r, filled, on):
        for y in range(-r, r + 1):
            for x in range(-r, r + 1):
                d = x * x + y * y
                if d <= r * r + r and (filled or d >= r * r - r):
                    self.pixel(cx + x, cy + y, on)

    def text(self, x, y, text: bytes, scale=1):
        for c in text:
            g = (c - 0x20 if 0x20 <= c <= 0x7E else ord("?") - 0x20) * 5
            for col in range(5):
                bits = FONT[g + col]
                for row in range(7):
                    if bits >> row & 1:
                        self.fill(x + col * scale, y + row * scale, scale, scale, True)
            x += 6 * scale
        return x

    @staticmethod
    def text_width(text: bytes, scale=1):
        return (6 * len(text) - 1) * scale if text else 0

    def text_centered(self, y, text, scale=1):
        self.text(_cdiv(W - self.text_width(text, scale), 2), y, text, scale)

    # ---- shapes ----

    def poke_ball(self, cx, cy, r, tilt=0):
        self.circle(cx, cy, r, True, False)
        self.circle(cx, cy, r, False, True)
        for y in range(-r, r + 1):
            for x in range(-r, r + 1):
                if x * x + y * y <= r * r and 4 * y < tilt * x:
                    self.pixel(cx + x, cy + y)
        self.line(cx - r, cy - _cdiv(r * tilt, 4), cx + r, cy + _cdiv(r * tilt, 4))
        button = r // 3 + 1 if r > 5 else 1
        bx, by = cx + tilt, cy + _cdiv(tilt * tilt, 4)
        self.circle(bx, by, button, True, False)
        self.circle(bx, by, button, False, True)

    def open_ball(self, cx, cy, r, lift):
        for y in range(-r, r + 1):
            for x in range(-r, r + 1):
                dd = x * x + y * y
                if dd > r * r + r:
                    continue
                if y < 0:
                    self.pixel(cx + x, cy + y - lift)
                elif dd >= r * r - r or y == 0:
                    self.pixel(cx + x, cy + y)

    def console_icon(self, x, y):
        self.fill(x, y + 1, 4, 10)
        self.fill(x + 18, y + 1, 4, 10)
        self.pixel(x, y + 1, False)
        self.pixel(x + 21, y + 1, False)
        self.pixel(x, y + 10, False)
        self.pixel(x + 21, y + 10, False)
        self.rect(x + 4, y, 14, 12)
        self.fill(x + 6, y + 2, 10, 8)
        self.pixel(x + 1, y + 4, False)
        self.pixel(x + 20, y + 7, False)

    def gift_box(self, cx, cy):
        self.rect(cx - 10, cy - 3, 21, 14)
        self.fill(cx - 12, cy - 8, 25, 5)
        self.fill(cx - 1, cy - 8, 3, 19, False)
        self.fill(cx, cy - 8, 1, 19)
        self.circle(cx - 4, cy - 11, 3, False, True)
        self.circle(cx + 4, cy - 11, 3, False, True)

    def sparkle(self, x, y, size):
        for i in range(-size - 1, size + 2):
            for k in (-1, 0, 1):
                self.pixel(x + i, y + k, False)
                self.pixel(x + k, y + i, False)
        for i in range(-size, size + 1):
            self.pixel(x + i, y)
            self.pixel(x, y + i)

    def sparkles(self, x, y, w, h, t):
        for i, (sx, sy) in enumerate(SPOTS):
            phase = ((t + i * 377) & U32) % 1200
            size = phase // 100 if phase < 300 else (600 - phase) // 100 if phase < 600 else -1
            if size >= 0:
                self.sparkle(x + sx * w // 100, y + sy * h // 100, size + 1)

    def bit_glyph(self, x, y, one):
        rows = BIT_ROWS[1 if one else 0]
        for r in range(5):
            for c in range(3):
                if rows[r] >> (2 - c) & 1:
                    self.pixel(x + c, y + r)

    def sprite_draw(self, v, slot, cx, bottom):
        pw, ph, bits = self.sprite[slot]
        if not pw:
            return False
        stride = (pw + 7) // 8
        if not v.compact:
            x0, y0 = cx - pw // 2, bottom - ph
            for y in range(ph):
                for x in range(pw):
                    if bits[y * stride + x // 8] >> (7 - x % 8) & 1:
                        self.pixel(x0 + x, y0 + y)
            return True
        w, h = (pw + 1) // 2, (ph + 1) // 2
        for y in range(h):
            for x in range(w):
                count = 0
                for k in range(4):
                    sx, sy = 2 * x + (k & 1), 2 * y + (k >> 1)
                    if sx < pw and sy < ph:
                        count += bits[sy * stride + sx // 8] >> (7 - sx % 8) & 1
                if count >= 2:
                    self.pixel(cx - w // 2 + x, bottom - h + y)
        return True

    def text_wrapped(self, x, y, cols, text):
        if len(text) <= cols:
            self.text(x, y, text)
            return
        cut = cols
        while cut > 0 and text[cut] != 0x20:
            cut -= 1
        if cut == 0:
            cut = cols
        self.text(x, y, _cut(text[:cut], TEXT_MAX))
        while cut < len(text) and text[cut] == 0x20:
            cut += 1
        self.text(x, y + 9, _cut(text[cut:cut + cols], TEXT_MAX))

    # ---- packets ----

    def dot_spawn(self, direction):
        for i in range(DOTS):
            if not self.d_dir[i]:
                self.d_seed = (self.d_seed * 1103515245 + 12345) & U32
                self.d_dir[i] = direction
                self.d_at[i] = 0
                self.d_bit[i] = self.d_seed >> 16 & 1
                return

    def dots_step(self, rx, tx, now):
        dt = (now - self.d_last) & U32 if self.d_last else 0
        self.d_last = now
        step = _i16(((dt * 1000) & U32) // DOT_MS)
        for i in range(DOTS):
            if self.d_dir[i]:
                self.d_at[i] = _i16(self.d_at[i] + step)
                if self.d_at[i] >= 1000:
                    self.d_dir[i] = 0
        if rx != self.d_rx and (now - self.d_rx_ms) & U32 >= DOT_GAP_MS:
            self.dot_spawn(1)
            self.d_rx_ms, self.d_rx = now, rx
        if tx != self.d_tx and (now - self.d_tx_ms) & U32 >= DOT_GAP_MS:
            self.dot_spawn(-1)
            self.d_tx_ms, self.d_tx = now, tx

    def cable(self, x0, x1, y):
        for x in range(x0, x1 + 1, 2):
            self.pixel(x, y)
        for i in range(DOTS):
            if not self.d_dir[i]:
                continue
            along = self.d_at[i] if self.d_dir[i] > 0 else 1000 - self.d_at[i]
            x = x0 + _cdiv((x1 - x0) * along, 1000) - 1
            self.bit_glyph(x, y - 7 if self.d_dir[i] > 0 else y + 2, self.d_bit[i])

    def link_strip(self, v):
        self.console_icon(v.link_x, v.link_y)
        self.poke_ball(v.w - 10 + (4 if v.compact else 0), v.link_y + 6, v.link_r)
        self.cable(v.cable_x0, v.cable_x1, v.cable_y)

    # ---- text ----

    def line_centered(self, v, dx, y, text):
        cut = text[:SMALL_W // 6 if v.compact else 31]
        self.text(_cdiv(v.w - self.text_width(cut), 2) + dx, y, cut)

    def title(self, v, left, right):
        if v.compact:
            self.line_centered(v, 0, 0, right if right is not None else left)
            return
        self.text(0, 0, left)
        if right:
            self.text(W - self.text_width(right), 0, right)
        self.fill(0, 9, W, 1)

    def half_title(self, v, text, fallback):
        if v.compact:
            self.line_centered(v, 0, 0, fallback)
            return
        self.text(0, 0, text[:10])
        self.fill(0, 9, 62, 1)

    # ---- scenes ----

    def elapsed(self, now):
        return (now - self.started) & U32

    def radio_scene(self, v, r, now):
        mode, stations, rx, tx = r
        if mode == JOINED or (mode == HOSTING and stations):
            self.title(v, b"joined" if mode == JOINED else b"hosting", b"linked")
            self.link_strip(v)
            text = b"%d/%d" % (rx, tx) if v.compact else b"in %d  out %d" % (rx, tx)
            self.line_centered(v, 0, v.h - 8 - (0 if v.compact else 4), text)
            return
        if mode in (JOINING, HOSTING):
            t = now % 1500
            cy = v.cy - (0 if v.compact else 2)
            for k in range(3):
                self.circle(v.cx, cy, v.ring_min + ((t + k * 500) % 1500) * v.ring_span // 1500, False, True)
            r_ball = 6 if v.compact else 9
            self.circle(v.cx, cy, r_ball + 1, True, False)
            self.poke_ball(v.cx, cy, r_ball, _wobble(now % 3000))
            self.fill(0, 0, v.w, 10, False)
            self.title(v, b"pokeldn", b"joining" if mode == JOINING else b"hosting")
            if not v.compact:
                self.fill(0, 54, W, 10, False)
                self.line_centered(v, 0, 56, b"looking for a console" if mode == JOINING else b"waiting for a console")
            return
        o = ORBIT[now // ORBIT_MS % 4]
        self.poke_ball(v.splash_x + o[0], v.splash_y + o[1], v.splash_r, _wobble(now % 4000))
        self.text(v.logo_x + o[0], v.logo_y + o[1], b"pokeldn", v.logo_scale)
        self.fill(0, v.rule_y + o[1], v.w, 1)
        y = v.text_y + o[1]
        if mode == SNIFFING:
            self.line_centered(v, o[0], y, b"sniffing")
            self.line_centered(v, o[0], y + v.text_step + (0 if v.compact else 4),
                               (b"%d fr" if v.compact else b"%d frames") % rx)
            return
        self.line_centered(v, o[0], y, b"radio ready")
        if not v.compact:
            self.line_centered(v, o[0], y + v.text_step, b"start a trade or gift")
        self.line_centered(v, o[0], y + v.text_step * (1 if v.compact else 2), b"v" + self.version)

    def trade_scene(self, v, now):
        bob = now // 500 % 2
        if v.compact:
            self.line_centered(v, 0, 0, self.now.line or b"offering")
            if not self.sprite_draw(v, OURS, v.cx, v.bottom - bob):
                self.poke_ball(v.cx, v.cy, 9)
            return
        self.half_title(v, self.now.title or b"trade", b"")
        if not self.sprite_draw(v, OURS, 96, 64 - bob):
            self.poke_ball(96, 34, 12)
        self.text(0, 14, b"offering")
        self.text_wrapped(0, 24, 10, self.now.line)
        self.console_icon(0, 47)
        self.cable(24, 62, 53)

    def lobby_lines(self):
        lines = []
        if self.now.line:
            lines.append(self.now.line[:TEXT_MAX - 1])
        if self.stars:
            lines.append(b"*******"[:self.stars])
        lines.append((b"%d/%d joined" % (self.joined, self.seats))[:TEXT_MAX - 1])
        if self.code:
            lines.append(self.code[:TEXT_MAX - 1])
        return lines

    def lobby_scene(self, v, now):
        lines = self.lobby_lines()
        if v.compact:
            for i, line in enumerate(lines):
                self.line_centered(v, 0, 10 * i, line)
            return
        self.half_title(v, self.now.title, b"")
        if not self.sprite_draw(v, OURS, 96, 64 - now // 500 % 2):
            self.poke_ball(96, 34, 12)
        for i, line in enumerate(lines):
            self.text(0, 14 + 12 * i, line[:10])

    def traded_scene(self, v, now):
        t = self.elapsed(now)
        reveal = self.reveal
        cx, cy, sb = v.cx, v.cy, v.small_ball
        if t < 1100:
            if t < 400 or (t < 700 and t // 80 % 2 == 0):
                if not self.sprite_draw(v, OURS, cx, v.bottom):
                    self.poke_ball(cx, cy, v.ball)
            elif t >= 700:
                self.poke_ball(cx, cy, sb)
                ray = (t - 700) // (60 if v.compact else 40)
                inner, outer = sb + 2, sb + (4 if v.compact else 5)
                for dx, dy in RAYS:
                    self.line(cx + dx * (inner + ray), cy + dy * (inner + ray),
                              cx + dx * (outer + ray), cy + dy * (outer + ray))
            self.line_centered(v, 0, 0, b"go!")
        elif t < LEAVE_MS:
            x = _f32((t - 1100) / 1000.0)
            bx, by = _lerp(cx, v.w + 12, x), _lerp(cy, 4 if v.compact else 6, x)
            self.poke_ball(bx, by, sb)
            for k in range(1, 4):
                self.bit_glyph(bx - (8 if v.compact else 10) * k, by + (3 if v.compact else 4) * k, (t // 90 + k) % 2)
        elif t < reveal:
            self.title(v, b"trading...", None)
            if t // 60 % 2:
                self.dot_spawn(1 if t // 120 % 2 else -1)
            self.link_strip(v)
        elif t < (reveal + LAND_MS) & U32:
            x = _f32(((t - reveal) & U32) / _f32(float(LAND_MS)))
            self.poke_ball(_lerp(-12, cx, x), _lerp(4 if v.compact else 6, cy, x), sb)
        elif t < (reveal + 1000) & U32:
            k = (t - reveal - LAND_MS) & U32
            self.poke_ball(cx, cy, sb, _wobble(k * WOBBLE_MS // (1000 - LAND_MS)))
        elif t < (reveal + REVEAL_MS) & U32:
            k = (t - reveal - 1000) & U32
            self.open_ball(cx, cy + (3 if v.compact else 4), sb + 2, k // (80 if v.compact else 60))
            flash = k * (40 if v.compact else 70) // 600
            ring = 4 if v.compact else 6
            self.circle(cx, cy, flash, True, True)
            if flash > ring:
                self.circle(cx, cy, flash - ring, True, False)
        elif v.compact:
            self.line_centered(v, 0, 0, self.now.line or b"received")
            if not self.sprite_draw(v, THEIRS, cx, v.bottom):
                self.poke_ball(cx, cy, 9)
            self.sparkles(14, 10, 44, 30, t)
        else:
            self.half_title(v, self.now.title or b"trade", b"")
            if not self.sprite_draw(v, THEIRS, 96, 64):
                self.poke_ball(96, 34, 12)
            self.sparkles(68, 4, 56, 56, t)
            self.text(0, 18, b"received")
            self.text_wrapped(0, 30, 10, self.now.line)

    def card(self, v, x, y):
        w, h = (38, 31) if v.compact else (58, 48)
        self.fill(x, y, w, h, False)
        self.rect(x, y, w, h)
        if not v.compact:
            self.rect(x + 2, y + 2, w - 4, h - 4)
        if not self.sprite_draw(v, GIFT_SLOT, x + w // 2, y + h - (2 if v.compact else 4)):
            self.gift_box(x + w // 2, y + (18 if v.compact else 26))

    def gift_scene(self, v, now):
        bob = now // 600 % 2
        if v.compact:
            self.line_centered(v, 0, 0, self.now.line or self.now.title or b"Mystery Gift")
            self.card(v, 17, 9 - bob)
            return
        self.title(v, self.now.title or b"Mystery Gift", b"gift")
        self.card(v, 0, 14 - bob)
        self.text_wrapped(63, 16, 10, self.now.line)
        self.console_icon(105, 50)
        self.cable(103, 62, 56)

    def gifted_scene(self, v, now):
        t = self.elapsed(now)
        if t < 900:
            self.card(v, _lerp(17 if v.compact else 0, v.w + 4, _f32(t / 900.0)), 9 if v.compact else 14)
            for k in range(3 if v.compact else 4):
                self.bit_glyph(t // (10 if v.compact else 6) - (16 if v.compact else 20) * k,
                               (12 if v.compact else 20) + 9 * k, (t // 70 + k) % 2)
            return
        if v.compact:
            self.line_centered(v, 0, 0, b"delivered!")
            self.gift_box(v.cx, 27)
            self.sparkles(8, 12, 56, 28, t)
            return
        self.text_centered(6, b"delivered!", 2)
        self.gift_box(64, 40)
        self.sparkles(34, 22, 60, 36, t)
        self.text_centered(56, self.now.line)

    def to_window(self):
        drawn = bytes(self.fb)
        self.fb = bytearray(SCREEN_BYTES)
        for y in range(SMALL_H):
            for x in range(SMALL_W):
                if drawn[x + W * (y >> 3)] >> (y & 7) & 1:
                    self.pixel(SMALL_X + x, SMALL_Y + y)

    # ---- sounds ----

    def _due(self, at, t):
        return self.heard < at <= t

    def _show_sound(self, t):
        cue = SOUND_NONE
        if self.now.show == TRADED:
            if self._due(700, t):
                cue = SOUND_RECALL
            if self._due(1100, t):
                cue = SOUND_SEND
            first, last = LEAVE_MS + 500, self.reveal - 300
            if t >= first and self.heard < last:
                start = 0 if self.heard < first else (self.heard - first) // DATA_MS + 1
                at = first + start * DATA_MS
                if at <= t and at <= last:
                    cue = SOUND_DATA
            if self._due(self.reveal, t):
                cue = SOUND_ARRIVE
            if self._due(self.reveal + LAND_MS, t):
                cue = SOUND_WOBBLE
            if self._due(self.reveal + 1000, t):
                cue = SOUND_OPEN
            if self._due(self.reveal + REVEAL_MS, t):
                cue = SOUND_RECEIVED
        elif self.now.show == GIFTED:
            if self._due(0, t):
                cue = SOUND_SEND
            if self._due(900, t):
                cue = SOUND_DELIVERED
        return cue

    # ---- commands ----

    @staticmethod
    def _copy_text(p: bytes, i: int) -> tuple[bytes, int]:
        end = p.find(0, i)
        if end < 0:
            return p[i:][:TEXT_MAX - 1], len(p)
        return p[i:end][:TEXT_MAX - 1], end + 1

    def _ends(self):
        if self.now.show == TRADED:
            return (self.reveal + REVEAL_MS + RECEIVED_MS) & U32
        return self.now.hold_s * 1000

    def _start(self, show: _Show, now):
        self.now = show.copy()
        self.started = now
        self.heard = -1
        wait = show.hold_s * 1000
        self.reveal = wait if wait > LEAVE_MS + 1000 else LEAVE_MS + 1000

    def command(self, p: bytes, now_ms: int) -> bool:
        """scene_command: False for a malformed command."""
        now = now_ms & U32
        p = bytes(p)
        n = len(p)
        self.wake_pending = True
        if n < 1:
            return False
        if p[0] == OP_SPRITE:
            if n < 4 or p[1] >= SLOTS or p[2] > SPRITE_W or p[3] > SPRITE_H:
                return False
            size = (p[2] + 7) // 8 * p[3]
            if n != 4 + size:
                return False
            self.sprite[p[1]] = (p[2], p[3], p[4:])
            return True
        if p[0] == OP_LOBBY:
            if n < 7 or p[1] > 7 or p[3] < 1 or p[3] > 3 or p[2] > p[3]:
                return False
            title, i = self._copy_text(p, 4)
            line, i = self._copy_text(p, i)
            self.code, i = self._copy_text(p, i)
            self.stars, self.joined, self.seats = p[1], p[2], p[3]
            self.has_next = False
            self._start(_Show(LOBBY, 0, title, line), now)
            return True
        if p[0] == OP_JOINED:
            if n != 2 or self.now.show != LOBBY or p[1] > self.seats:
                return False
            self.joined = p[1]
            return True
        if p[0] != OP_SHOW or n < 4 or p[1] >= SHOWS:
            return False
        if p[1] == ARRIVED:
            e = self.elapsed(now)
            if self.now.show == TRADED and e < self.reveal:
                self.reveal = e if e > LEAVE_MS else LEAVE_MS
            return True
        title, i = self._copy_text(p, 4)
        line, i = self._copy_text(p, i)
        show = _Show(p[1], p[2] | p[3] << 8, title, line)
        timed = show.show in (TRADED, GIFTED)
        if self._ends() and not timed and self.elapsed(now) < self._ends():
            self.next = show
            self.has_next = True
        else:
            self.has_next = False
            self._start(show, now)
        return True

    def panel(self, p: int) -> None:
        """scene_panel: 0 the 128x64 panel, 1 the 72x40 window."""
        self._panel = p & 0xFF

    def reset(self) -> None:
        """scene_reset: the radio's own scenes and no sprites; the panel and the wake clock stay."""
        self._clear_state()
        self.wake_pending = True

    def _power(self, mode, presses, now):
        if (not self.wake_seen or self.wake_pending or presses != self.wake_presses or mode != IDLE
                or self.now.show in (TRADED, GIFTED)):
            self.wake_last = now
        self.wake_seen = True
        self.wake_pending = False
        self.wake_presses = presses
        quiet = (now - self.wake_last) & U32
        return ON if quiet < DIM_MS else DIM if quiet < OFF_MS else OFF

    def draw(self, mode: int, stations: int, rx: int, tx: int, presses: int, now_ms: int) -> tuple[bytes, int]:
        """scene_draw: the frame in the SSD1306 page order and the panel's power (0 on, 1 dim, 2 off);
        `sound` then holds the cue the frame starts (scene_sound)."""
        now, mode, stations = now_ms & U32, mode & 0xFF, stations & 0xFF
        rx, tx, presses = rx & U32, tx & U32, presses & U32
        ends = self._ends()
        if ends and self.elapsed(now) >= ends:
            self._start(self.next if self.has_next else _Show(), now)
            self.has_next = False
        if self.now.show in (TRADE, GIFT, LOBBY) and mode == IDLE and self.radio_mode != IDLE:
            self.now.show = AUTO
        self.radio_mode = mode
        linked = mode == JOINED or (mode == HOSTING and stations)
        timed = self.now.show in (TRADED, GIFTED)
        self.sound = self._show_sound(self.elapsed(now)) if timed else SOUND_NONE
        if linked and not self.linked and self.sound == SOUND_NONE:
            self.sound = SOUND_LINKED
        self.linked = bool(linked)
        self.heard = self.elapsed(now) if timed else -1
        self.dots_step(rx, tx, now)
        self.fb = bytearray(SCREEN_BYTES)
        v = VIEWS[1 if self._panel == 1 else 0]
        radio = (mode, stations, rx, tx)
        {TRADE: lambda: self.trade_scene(v, now), TRADED: lambda: self.traded_scene(v, now),
         GIFT: lambda: self.gift_scene(v, now), GIFTED: lambda: self.gifted_scene(v, now),
         LOBBY: lambda: self.lobby_scene(v, now)}.get(self.now.show, lambda: self.radio_scene(v, radio, now))()
        if v.compact:
            self.to_window()
        return bytes(self.fb), self._power(mode, presses, now)

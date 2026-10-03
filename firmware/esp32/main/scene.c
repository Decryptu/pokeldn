#include <stdio.h>
#include <string.h>

#include "scene.h"
#include "screen.h"

#define STRIDE (SPRITE_W / 8)
#define TEXT_MAX 22
#define DOTS 24
#define DOT_MS 900          /* a packet's time from one end of a cable to the other */
#define DOT_GAP_MS 70       /* at most one packet drawn per direction per gap */

typedef struct {
    uint8_t w, h;
    uint8_t bits[STRIDE * SPRITE_H];
} sprite_t;

typedef struct {
    uint8_t show;
    uint16_t hold_s;
    char title[TEXT_MAX], line[TEXT_MAX];
} show_t;

static struct {
    show_t now, next;       /* next: a lasting show that waits for a timed one to end */
    bool has_next;
    uint8_t radio_mode;     /* the last frame's, to see a session end */
    uint32_t started;
    sprite_t sprite[SLOTS];
} s;

/* Packets on a cable: progress 0..1000 from the console's end (dir 1) or from ours (dir -1). */
static struct {
    int16_t at[DOTS];
    int8_t dir[DOTS];
    uint8_t bit[DOTS];
    uint32_t rx, tx, last_ms, rx_ms, tx_ms, seed;
} d;

static uint32_t elapsed(uint32_t now) { return now - s.started; }

static float ease(float x)
{
    x = x < 0 ? 0 : x > 1 ? 1 : x;
    return x * x * (3 - 2 * x);
}

static int lerp(int a, int b, float x) { return a + (int)((b - a) * ease(x)); }

/* ---- shapes ---------------------------------------------------------------------------------- */

static void poke_ball(uint8_t *fb, int cx, int cy, int r)
{
    fb_circle(fb, cx, cy, r, true, false);
    fb_circle(fb, cx, cy, r, false, true);
    for (int y = cy - r; y < cy; ++y)
        for (int x = cx - r; x <= cx + r; ++x)
            if ((x - cx) * (x - cx) + (y - cy) * (y - cy) <= r * r) fb_pixel(fb, x, y, true);
    fb_fill(fb, cx - r, cy, 2 * r + 1, 1, true);
    const int button = r > 5 ? r / 3 + 1 : 1;
    fb_circle(fb, cx, cy, button, true, false);
    fb_circle(fb, cx, cy, button, false, true);
}

/* The ball split at its seam, the top `lift` pixels up. */
static void open_ball(uint8_t *fb, int cx, int cy, int r, int lift)
{
    for (int y = -r; y <= r; ++y)
        for (int x = -r; x <= r; ++x) {
            const int dd = x * x + y * y;
            if (dd > r * r + r) continue;
            const bool edge = dd >= r * r - r;
            if (y < 0) fb_pixel(fb, cx + x, cy + y - lift, true);
            else if (edge || y == 0) fb_pixel(fb, cx + x, cy + y, true);
        }
}

static void console_icon(uint8_t *fb, int x, int y)   /* 22x12: a handheld with its controllers */
{
    fb_fill(fb, x, y + 1, 4, 10, true);
    fb_fill(fb, x + 18, y + 1, 4, 10, true);
    fb_pixel(fb, x, y + 1, false);
    fb_pixel(fb, x + 21, y + 1, false);
    fb_rect(fb, x + 4, y, 14, 12);
    fb_fill(fb, x + 6, y + 2, 10, 8, true);
    fb_pixel(fb, x + 1, y + 4, false);
    fb_pixel(fb, x + 20, y + 7, false);
}

static void gift_box(uint8_t *fb, int cx, int cy)   /* 24x22 */
{
    fb_rect(fb, cx - 10, cy - 3, 21, 14);
    fb_fill(fb, cx - 12, cy - 8, 25, 5, true);
    fb_fill(fb, cx - 1, cy - 8, 3, 19, false);
    fb_fill(fb, cx, cy - 8, 1, 19, true);
    fb_circle(fb, cx - 4, cy - 11, 3, false, true);
    fb_circle(fb, cx + 4, cy - 11, 3, false, true);
}

/* A star with a dark rim, so it shows over a lit sprite. */
static void sparkle(uint8_t *fb, int x, int y, int size)
{
    for (int i = -size - 1; i <= size + 1; ++i)
        for (int k = -1; k <= 1; ++k) {
            fb_pixel(fb, x + i, y + k, false);
            fb_pixel(fb, x + k, y + i, false);
        }
    for (int i = -size; i <= size; ++i) {
        fb_pixel(fb, x + i, y, true);
        fb_pixel(fb, x, y + i, true);
    }
}

/* Twinkling stars around a box: each one grows and fades on its own phase. */
static void sparkles(uint8_t *fb, int x, int y, int w, int h, uint32_t t)
{
    static const int8_t SPOTS[6][2] = {{4, 40}, {98, 14}, {2, 72}, {100, 80}, {56, 2}, {40, 96}};
    for (int i = 0; i < 6; ++i) {
        const int phase = (int)((t + i * 377) % 1200);
        const int size = phase < 300 ? phase / 100 : phase < 600 ? (600 - phase) / 100 : -1;
        if (size >= 0) sparkle(fb, x + SPOTS[i][0] * w / 100, y + SPOTS[i][1] * h / 100, size + 1);
    }
}

static void bit_glyph(uint8_t *fb, int x, int y, bool one)
{
    static const uint8_t ROWS[2][5] = {{7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}};
    for (int r = 0; r < 5; ++r)
        for (int c = 0; c < 3; ++c)
            if (ROWS[one][r] >> (2 - c) & 1) fb_pixel(fb, x + c, y + r, true);
}

static bool sprite_draw(uint8_t *fb, int slot, int cx, int bottom)
{
    const sprite_t *p = &s.sprite[slot];
    if (!p->w) return false;
    const int stride = (p->w + 7) / 8;
    const int x0 = cx - p->w / 2, y0 = bottom - p->h;
    for (int y = 0; y < p->h; ++y)
        for (int x = 0; x < p->w; ++x)
            if (p->bits[y * stride + x / 8] >> (7 - x % 8) & 1) fb_pixel(fb, x0 + x, y0 + y, true);
    return true;
}

/* Up to two lines of `cols` characters, broken at a space. */
static void text_wrapped(uint8_t *fb, int x, int y, int cols, const char *text)
{
    char line[TEXT_MAX + 1];
    const int n = (int)strlen(text);
    if (n <= cols) { fb_text(fb, x, y, text, 1); return; }
    int cut = cols;
    while (cut > 0 && text[cut] != ' ') --cut;
    if (cut == 0) cut = cols;
    snprintf(line, sizeof(line), "%.*s", cut, text);
    fb_text(fb, x, y, line, 1);
    while (text[cut] == ' ') ++cut;
    snprintf(line, sizeof(line), "%.*s", cols, text + cut);
    fb_text(fb, x, y + 9, line, 1);
}

/* ---- packets --------------------------------------------------------------------------------- */

static void dot_spawn(int dir)
{
    for (int i = 0; i < DOTS; ++i)
        if (!d.dir[i]) {
            d.seed = d.seed * 1103515245u + 12345u;
            d.dir[i] = (int8_t)dir;
            d.at[i] = 0;
            d.bit[i] = d.seed >> 16 & 1;
            return;
        }
}

/* One packet per frame the radio counted, thinned to one per DOT_GAP_MS per direction. */
static void dots_step(uint32_t rx, uint32_t tx, uint32_t now)
{
    const uint32_t dt = d.last_ms ? now - d.last_ms : 0;
    d.last_ms = now;
    for (int i = 0; i < DOTS; ++i)
        if (d.dir[i] && (d.at[i] += (int16_t)(dt * 1000 / DOT_MS)) >= 1000) d.dir[i] = 0;
    if (rx != d.rx && now - d.rx_ms >= DOT_GAP_MS) { dot_spawn(1); d.rx_ms = now; d.rx = rx; }
    if (tx != d.tx && now - d.tx_ms >= DOT_GAP_MS) { dot_spawn(-1); d.tx_ms = now; d.tx = tx; }
}

/* A dotted cable from the console's end (x0) to ours (x1), with the packets on it. */
static void cable(uint8_t *fb, int x0, int x1, int y)
{
    for (int x = x0; x <= x1; x += 2) fb_pixel(fb, x, y, true);
    for (int i = 0; i < DOTS; ++i) {
        if (!d.dir[i]) continue;
        const int along = d.dir[i] > 0 ? d.at[i] : 1000 - d.at[i];
        const int x = x0 + (x1 - x0) * along / 1000 - 1;
        bit_glyph(fb, x, d.dir[i] > 0 ? y - 7 : y + 2, d.bit[i]);
    }
}

/* ---- scenes ---------------------------------------------------------------------------------- */

static void header(uint8_t *fb, const char *left, const char *right)
{
    fb_text(fb, 0, 0, left, 1);
    if (right) fb_text(fb, SCREEN_W - fb_text_width(right, 1), 0, right, 1);
    fb_fill(fb, 0, 9, SCREEN_W, 1, true);
}

static void radio_scene(uint8_t *fb, const scene_radio_t *r, uint32_t now)
{
    char text[32];
    const bool linked = r->mode == SCENE_JOINED || (r->mode == SCENE_HOSTING && r->stations);
    if (linked) {
        header(fb, r->mode == SCENE_JOINED ? "joined" : "hosting", "linked");
        console_icon(fb, 2, 22);
        poke_ball(fb, 118, 28, 7);
        cable(fb, 27, 108, 34);
        snprintf(text, sizeof(text), "in %lu  out %lu", (unsigned long)r->rx, (unsigned long)r->tx);
        fb_text_centered(fb, 52, text, 1);
        return;
    }
    if (r->mode == SCENE_JOINING || r->mode == SCENE_HOSTING) {
        header(fb, "pokeldn", r->mode == SCENE_JOINING ? "joining" : "hosting");
        const uint32_t t = now % 1500;
        for (int k = 0; k < 3; ++k) {
            const int radius = 8 + (int)((t + k * 500) % 1500) * 26 / 1500;
            fb_circle(fb, 64, 34, radius, false, true);
        }
        fb_fill(fb, 50, 22, 29, 25, false);
        poke_ball(fb, 64, 34, 9);
        fb_fill(fb, 0, 54, SCREEN_W, 10, false);
        fb_text_centered(fb, 56, r->mode == SCENE_JOINING ? "looking for a console" : "waiting for a console", 1);
        return;
    }
    poke_ball(fb, 14, 15 + (int)(now / 400 % 2), 9);
    fb_text(fb, 30, 9, "pokeldn", 2);
    fb_fill(fb, 0, 28, SCREEN_W, 1, true);
    if (r->mode == SCENE_SNIFFING) {
        fb_text_centered(fb, 36, "sniffing", 1);
        snprintf(text, sizeof(text), "%lu frames", (unsigned long)r->rx);
        fb_text_centered(fb, 50, text, 1);
    } else {
        fb_text_centered(fb, 36, "radio ready", 1);
        fb_text_centered(fb, 50, "start a trade or gift", 1);
    }
}

/* A title over the left half: the right half is the sprite's, all 64 rows of it. */
static void half_header(uint8_t *fb, const char *title)
{
    char cut[11];
    snprintf(cut, sizeof(cut), "%s", title);   /* 10 characters stop at the sprite's half */
    fb_text(fb, 0, 0, cut, 1);
    fb_fill(fb, 0, 9, 62, 1, true);
}

static void trade_scene(uint8_t *fb, uint32_t now)
{
    half_header(fb, s.now.title[0] ? s.now.title : "trade");
    if (!sprite_draw(fb, SLOT_OURS, 96, 64 - (int)(now / 500 % 2))) poke_ball(fb, 96, 34, 12);
    fb_text(fb, 0, 14, "offering", 1);
    text_wrapped(fb, 0, 24, 10, s.now.line);
    console_icon(fb, 0, 47);
    cable(fb, 24, 62, 53);
}

static void traded_scene(uint8_t *fb, uint32_t now)
{
    const uint32_t t = elapsed(now);
    if (t < 1100) {   /* ours flashes, then goes back into its ball */
        if (t < 400 || (t < 700 && t / 80 % 2 == 0)) {
            if (!sprite_draw(fb, SLOT_OURS, 64, 64)) poke_ball(fb, 64, 36, 10);
        } else if (t >= 700) {
            poke_ball(fb, 64, 36, 6);
            const int ray = (int)(t - 700) / 40;
            for (int k = 0; k < 8; ++k) {
                static const int8_t DIR[8][2] = {{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}};
                fb_line(fb, 64 + DIR[k][0] * (8 + ray), 36 + DIR[k][1] * (8 + ray),
                        64 + DIR[k][0] * (11 + ray), 36 + DIR[k][1] * (11 + ray));
            }
        }
        fb_text_centered(fb, 0, "go!", 1);
    } else if (t < 2100) {   /* up and away through the link */
        const float x = (t - 1100) / 1000.0f;
        const int bx = lerp(64, 140, x), by = lerp(36, 6, x);
        poke_ball(fb, bx, by, 6);
        for (int k = 1; k < 4; ++k) bit_glyph(fb, bx - 10 * k, by + 4 * k, (t / 90 + k) % 2);
    } else if (t < 3100) {   /* the exchange: packets both ways */
        fb_text_centered(fb, 6, "trading...", 1);
        console_icon(fb, 2, 26);
        poke_ball(fb, 118, 32, 7);
        if (t / 60 % 2) dot_spawn(t / 120 % 2 ? 1 : -1);
        cable(fb, 27, 108, 38);
    } else if (t < 4100) {   /* theirs comes in */
        const float x = (t - 3100) / 1000.0f;
        poke_ball(fb, lerp(-12, 64, x), lerp(6, 36, x), 6);
    } else if (t < 4700) {   /* and opens */
        const int k = (int)(t - 4100);
        open_ball(fb, 64, 40, 8, k / 60);
        const int flash = k * 70 / 600;
        fb_circle(fb, 64, 36, flash, true, true);
        if (flash > 6) fb_circle(fb, 64, 36, flash - 6, true, false);
    } else {
        half_header(fb, s.now.title[0] ? s.now.title : "trade");
        if (!sprite_draw(fb, SLOT_THEIRS, 96, 64)) poke_ball(fb, 96, 34, 12);
        sparkles(fb, 68, 4, 56, 56, t);
        fb_text(fb, 0, 18, "received", 1);
        text_wrapped(fb, 0, 30, 10, s.now.line);
    }
}

static void card(uint8_t *fb, int x, int y)   /* a Wonder Card, 58x48 */
{
    fb_fill(fb, x, y, 58, 48, false);
    fb_rect(fb, x, y, 58, 48);
    fb_rect(fb, x + 2, y + 2, 54, 44);
    for (int i = 4; i < 54; i += 4) fb_pixel(fb, x + i, y + 4, true);
    if (!sprite_draw(fb, SLOT_GIFT, x + 29, y + 44)) gift_box(fb, x + 29, y + 26);
}

static void gift_scene(uint8_t *fb, uint32_t now)
{
    header(fb, s.now.title[0] ? s.now.title : "Mystery Gift", "gift");
    card(fb, 0, 14 - (int)(now / 600 % 2));
    text_wrapped(fb, 63, 16, 10, s.now.line);
    console_icon(fb, 105, 50);
    cable(fb, 103, 62, 56);
}

static void gifted_scene(uint8_t *fb, uint32_t now)
{
    const uint32_t t = elapsed(now);
    if (t < 900) {
        card(fb, lerp(0, 132, t / 900.0f), 14);
        for (int k = 0; k < 4; ++k) bit_glyph(fb, (int)(t / 6) - 20 * k, 20 + 9 * k, (t / 70 + k) % 2);
        return;
    }
    fb_text_centered(fb, 6, "delivered!", 2);
    gift_box(fb, 64, 40);
    sparkles(fb, 34, 22, 60, 36, t);
    fb_text_centered(fb, 56, s.now.line, 1);
}

/* ---- commands -------------------------------------------------------------------------------- */

static void copy_text(char *dst, const char **p, const char *end)
{
    size_t n = 0;
    while (*p < end && **p) {
        if (n < TEXT_MAX - 1) dst[n++] = **p;
        ++*p;
    }
    dst[n] = 0;
    if (*p < end) ++*p;
}

static bool timed(uint8_t show) { return show == SHOW_TRADED || show == SHOW_GIFTED; }

static void start(const show_t *show, uint32_t now)
{
    s.now = *show;
    s.started = now;
}

bool scene_command(const uint8_t *p, size_t n, uint32_t now)
{
    if (n < 1) return false;
    if (p[0] == DISPLAY_OP_SPRITE) {
        if (n < 4 || p[1] >= SLOTS || p[2] > SPRITE_W || p[3] > SPRITE_H) return false;
        const size_t size = (size_t)(p[2] + 7) / 8 * p[3];
        if (n != 4 + size) return false;
        sprite_t *sprite = &s.sprite[p[1]];
        sprite->w = p[2];
        sprite->h = p[3];
        memcpy(sprite->bits, p + 4, size);
        return true;
    }
    if (p[0] != DISPLAY_OP_SHOW || n < 4 || p[1] >= SHOWS) return false;
    show_t show = {.show = p[1], .hold_s = (uint16_t)(p[2] | p[3] << 8)};
    const char *text = (const char *)p + 4, *end = (const char *)p + n;
    copy_text(show.title, &text, end);
    copy_text(show.line, &text, end);
    /* A lasting show waits for a timed one to finish rather than cutting its animation short. */
    if (timed(s.now.show) && !timed(show.show) && s.now.hold_s && elapsed(now) < s.now.hold_s * 1000u) {
        s.next = show;
        s.has_next = true;
    } else {
        s.has_next = false;
        start(&show, now);
    }
    return true;
}

void scene_reset(void)
{
    memset(&s, 0, sizeof(s));
}

void scene_draw(uint8_t *fb, const scene_radio_t *radio, uint32_t now)
{
    if (s.now.hold_s && elapsed(now) >= s.now.hold_s * 1000u) {
        if (s.has_next) start(&s.next, now);
        else s.now.show = SHOW_AUTO;
        s.has_next = false;
        s.now.hold_s = s.now.show == SHOW_AUTO ? 0 : s.now.hold_s;
    }
    /* A lasting show belongs to a session: a radio going back to idle has ended it. A show sent
       before the radio started stays. */
    if ((s.now.show == SHOW_TRADE || s.now.show == SHOW_GIFT) && radio->mode == SCENE_IDLE &&
        s.radio_mode != SCENE_IDLE)
        s.now.show = SHOW_AUTO;
    s.radio_mode = radio->mode;
    dots_step(radio->rx, radio->tx, now);
    fb_clear(fb);
    switch (s.now.show) {
    case SHOW_TRADE: trade_scene(fb, now); break;
    case SHOW_TRADED: traded_scene(fb, now); break;
    case SHOW_GIFT: gift_scene(fb, now); break;
    case SHOW_GIFTED: gifted_scene(fb, now); break;
    default: radio_scene(fb, radio, now); break;
    }
}

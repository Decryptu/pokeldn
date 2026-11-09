#include <stdio.h>
#include <string.h>

#include "scene.h"
#include "screen.h"

#define STRIDE (SPRITE_W / 8)
#define TEXT_MAX 22
#define DOTS 24
#define DOT_MS 900          /* a packet's time from one end of a cable to the other */
#define DOT_GAP_MS 70       /* at most one packet drawn per direction per gap */
#define LEAVE_MS 2100       /* ours flashes, returns to its ball and leaves */
#define LAND_MS 600         /* theirs drops in and lands; it wobbles until the ball opens */
#define REVEAL_MS 1600      /* theirs comes in and its ball opens */
#define RECEIVED_MS 10000   /* then it stays */
#define DATA_MS 1000        /* one data blip a second while the console runs its animation */
#define WOBBLE_MS 900       /* three rocks of a ball, as one being caught */
#define DIM_MS 60000        /* an idle radio's screen dims after a minute with nothing happening */
#define OFF_MS 600000       /* and goes dark after ten */
#define ORBIT_MS 60000      /* the idle scene moves one step of ORBIT a minute: no pixel lit for hours */
#ifndef POKELDN_FIRMWARE_VERSION
#define POKELDN_FIRMWARE_VERSION "unknown"
#endif

typedef struct {
    uint8_t w, h;
    uint8_t bits[STRIDE * SPRITE_H];
} sprite_t;

typedef struct {
    uint8_t show;
    uint16_t hold_s;
    char title[TEXT_MAX], line[TEXT_MAX];
} show_t;

/* Where each scene puts its parts on a panel. Every scene is drawn by one function for both panels;
   only these numbers differ. docs/hardware_esp32.md, The screen. */
typedef struct {
    int w, h;
    bool compact;           /* one title line and half-size sprites */
    int cx, cy;             /* the centre of the trade's ball */
    int ball, small_ball;   /* a ball's radius in the open, and while it travels */
    int bottom;             /* a sprite's bottom row */
    int link_x, link_y;     /* the console icon of the link: console, cable, our ball */
    int link_r;
    int cable_x0, cable_x1, cable_y;
    int ring_min, ring_span;    /* the search rings around the ball */
    int splash_x, splash_y, splash_r, logo_x, logo_y, logo_scale, rule_y, text_y, text_step;
} view_t;

static const view_t VIEWS[] = {
    [PANEL_128X64] = {
        .w = SCREEN_W, .h = SCREEN_H, .compact = false, .cx = 64, .cy = 36, .ball = 10, .small_ball = 6,
        .bottom = 64, .link_x = 2, .link_y = 22, .link_r = 7, .cable_x0 = 27, .cable_x1 = 108, .cable_y = 34,
        .ring_min = 8, .ring_span = 26, .splash_x = 14, .splash_y = 15, .splash_r = 9, .logo_x = 30,
        .logo_y = 9, .logo_scale = 2, .rule_y = 28, .text_y = 36, .text_step = 10,
    },
    [PANEL_72X40] = {
        .w = SMALL_W, .h = SMALL_H, .compact = true, .cx = 36, .cy = 25, .ball = 8, .small_ball = 5,
        .bottom = 40, .link_x = 0, .link_y = 14, .link_r = 5, .cable_x0 = 24, .cable_x1 = 59, .cable_y = 20,
        .ring_min = 6, .ring_span = 14, .splash_x = 8, .splash_y = 8, .splash_r = 6, .logo_x = 19,
        .logo_y = 5, .logo_scale = 1, .rule_y = 17, .text_y = 21, .text_step = 10,
    },
};

static struct {
    show_t now, next;       /* next: a lasting show that waits for a timed one to end */
    bool has_next;
    uint8_t radio_mode;     /* the last frame's, to see a session end */
    bool linked;            /* the last frame's, to hear a console seat */
    uint32_t started;
    uint32_t reveal;        /* a traded show: ms after its start when theirs starts coming in */
    int32_t heard;          /* the show's ms at the last frame, for its sounds; -1 before the first */
    uint8_t sound;          /* enum scene_sound the last frame started */
    sprite_t sprite[SLOTS];
    struct {
        uint8_t stars, joined, seats;
        char code[TEXT_MAX];
    } lobby;                /* a lobby show's: its title and name are the show's title and line */
} s;

/* Packets on a cable: progress 0..1000 from the console's end (dir 1) or from ours (dir -1). */
static struct {
    int16_t at[DOTS];
    int8_t dir[DOTS];
    uint8_t bit[DOTS];
    uint32_t rx, tx, last_ms, rx_ms, tx_ms, seed;
} d;

static uint8_t s_panel;   /* enum scene_panel: the hardware's, kept across scene_reset */

/* Kept across scene_reset: a new host session is activity, not a new boot. */
static struct {
    bool seen, pending;
    uint32_t presses, last_ms;
} wake;

static uint32_t elapsed(uint32_t now) { return now - s.started; }

static float ease(float x)
{
    x = x < 0 ? 0 : x > 1 ? 1 : x;
    return x * x * (3 - 2 * x);
}

static int lerp(int a, int b, float x) { return a + (int)((b - a) * ease(x)); }

/* A ball's tilt `t` ms into a wobble: three rocks, left, right, left, each one smaller. */
static int wobble(uint32_t t)
{
    static const int8_t TILT[] = {-1, -2, -1, 0, 2, 1, 0, -1, 0};
    return t < WOBBLE_MS ? TILT[t * 9 / WOBBLE_MS] : 0;
}

/* ---- shapes ---------------------------------------------------------------------------------- */

/* The seam leans `tilt` quarters of a pixel per pixel; tilt 0 is a ball at rest. */
static void poke_ball(uint8_t *fb, int cx, int cy, int r, int tilt)
{
    fb_circle(fb, cx, cy, r, true, false);
    fb_circle(fb, cx, cy, r, false, true);
    for (int y = -r; y <= r; ++y)
        for (int x = -r; x <= r; ++x)
            if (x * x + y * y <= r * r && 4 * y < tilt * x) fb_pixel(fb, cx + x, cy + y, true);
    fb_line(fb, cx - r, cy - r * tilt / 4, cx + r, cy + r * tilt / 4);
    /* The button rolls with the tilt, along the seam: the rock reads even on a small ball. */
    const int button = r > 5 ? r / 3 + 1 : 1, bx = cx + tilt, by = cy + tilt * tilt / 4;
    fb_circle(fb, bx, by, button, true, false);
    fb_circle(fb, bx, by, button, false, true);
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
    fb_pixel(fb, x, y + 1, false);           /* the controllers' rounded outer corners */
    fb_pixel(fb, x + 21, y + 1, false);
    fb_pixel(fb, x, y + 10, false);
    fb_pixel(fb, x + 21, y + 10, false);
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

/* A sprite with its bottom centre at (cx, bottom); a compact view draws it at half size, a pixel lit
   when two of its 2x2 block are. */
static bool sprite_draw(uint8_t *fb, const view_t *v, int slot, int cx, int bottom)
{
    const sprite_t *p = &s.sprite[slot];
    if (!p->w) return false;
    const int stride = (p->w + 7) / 8;
    if (!v->compact) {
        const int x0 = cx - p->w / 2, y0 = bottom - p->h;
        for (int y = 0; y < p->h; ++y)
            for (int x = 0; x < p->w; ++x)
                if (p->bits[y * stride + x / 8] >> (7 - x % 8) & 1) fb_pixel(fb, x0 + x, y0 + y, true);
        return true;
    }
    const int w = (p->w + 1) / 2, h = (p->h + 1) / 2;
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            int count = 0;
            for (int k = 0; k < 4; ++k) {
                const int sx = 2 * x + (k & 1), sy = 2 * y + (k >> 1);
                if (sx < p->w && sy < p->h) count += p->bits[sy * stride + sx / 8] >> (7 - sx % 8) & 1;
            }
            if (count >= 2) fb_pixel(fb, cx - w / 2 + x, bottom - h + y, true);
        }
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

/* The console, the cable with its packets, and our ball. */
static void link_strip(uint8_t *fb, const view_t *v)
{
    console_icon(fb, v->link_x, v->link_y);
    poke_ball(fb, v->w - 10 + (v->compact ? 4 : 0), v->link_y + 6, v->link_r, 0);
    cable(fb, v->cable_x0, v->cable_x1, v->cable_y);
}

/* ---- text ------------------------------------------------------------------------------------ */

/* One line centred across the view, moved `dx` pixels; the compact view cuts it to its 12 characters. */
static void line_centered(uint8_t *fb, const view_t *v, int dx, int y, const char *text)
{
    char cut[32];
    snprintf(cut, sizeof(cut), "%.*s", v->compact ? SMALL_W / 6 : 31, text);
    fb_text(fb, (v->w - fb_text_width(cut, 1)) / 2 + dx, y, cut, 1);
}

/* The scene's title: a header with a rule on the full panel, the word that matters on the compact one
   (`right` when there is one). */
static void title(uint8_t *fb, const view_t *v, const char *left, const char *right)
{
    if (v->compact) {
        line_centered(fb, v, 0, 0, right ? right : left);
        return;
    }
    fb_text(fb, 0, 0, left, 1);
    if (right) fb_text(fb, SCREEN_W - fb_text_width(right, 1), 0, right, 1);
    fb_fill(fb, 0, 9, SCREEN_W, 1, true);
}

/* A title over the left half, the right half the sprite's; the compact panel shows `fallback`. */
static void half_title(uint8_t *fb, const view_t *v, const char *text, const char *fallback)
{
    if (v->compact) {
        line_centered(fb, v, 0, 0, fallback);
        return;
    }
    char cut[11];
    snprintf(cut, sizeof(cut), "%s", text);   /* 10 characters stop at the sprite's half */
    fb_text(fb, 0, 0, cut, 1);
    fb_fill(fb, 0, 9, 62, 1, true);
}

/* ---- scenes ---------------------------------------------------------------------------------- */

static void radio_scene(uint8_t *fb, const view_t *v, const scene_radio_t *r, uint32_t now)
{
    char text[32];
    const bool linked = r->mode == SCENE_JOINED || (r->mode == SCENE_HOSTING && r->stations);
    if (linked) {
        title(fb, v, r->mode == SCENE_JOINED ? "joined" : "hosting", "linked");
        link_strip(fb, v);
        if (v->compact) snprintf(text, sizeof(text), "%lu/%lu", (unsigned long)r->rx, (unsigned long)r->tx);
        else snprintf(text, sizeof(text), "in %lu  out %lu", (unsigned long)r->rx, (unsigned long)r->tx);
        line_centered(fb, v, 0, v->h - 8 - (v->compact ? 0 : 4), text);
        return;
    }
    if (r->mode == SCENE_JOINING || r->mode == SCENE_HOSTING) {
        const uint32_t t = now % 1500;
        for (int k = 0; k < 3; ++k)
            fb_circle(fb, v->cx, v->cy - 2 * !v->compact,
                      v->ring_min + (int)((t + k * 500) % 1500) * v->ring_span / 1500, false, true);
        const int r_ball = v->compact ? 6 : 9, cy = v->cy - 2 * !v->compact;
        fb_circle(fb, v->cx, cy, r_ball + 1, true, false);   /* the rings stop at the ball's outline */
        poke_ball(fb, v->cx, cy, r_ball, wobble(now % 3000));
        fb_fill(fb, 0, 0, v->w, 10, false);
        title(fb, v, "pokeldn", r->mode == SCENE_JOINING ? "joining" : "hosting");
        if (!v->compact) {
            fb_fill(fb, 0, 54, SCREEN_W, 10, false);
            line_centered(fb, v, 0, 56, r->mode == SCENE_JOINING ? "looking for a console" : "waiting for a console");
        }
        return;
    }
    static const int8_t ORBIT[][2] = {{-1, -1}, {1, -1}, {1, 1}, {-1, 1}};
    const int8_t *o = ORBIT[now / ORBIT_MS % 4];
    poke_ball(fb, v->splash_x + o[0], v->splash_y + o[1], v->splash_r, wobble(now % 4000));
    fb_text(fb, v->logo_x + o[0], v->logo_y + o[1], "pokeldn", v->logo_scale);
    fb_fill(fb, 0, v->rule_y + o[1], v->w, 1, true);
    const int y = v->text_y + o[1];
    if (r->mode == SCENE_SNIFFING) {
        line_centered(fb, v, o[0], y, "sniffing");
        snprintf(text, sizeof(text), v->compact ? "%lu fr" : "%lu frames", (unsigned long)r->rx);
        line_centered(fb, v, o[0], y + v->text_step + 4 * !v->compact, text);
        return;
    }
    line_centered(fb, v, o[0], y, "radio ready");
    if (!v->compact) line_centered(fb, v, o[0], y + v->text_step, "start a trade or gift");
    line_centered(fb, v, o[0], y + v->text_step * (v->compact ? 1 : 2), "v" POKELDN_FIRMWARE_VERSION);
}

static void trade_scene(uint8_t *fb, const view_t *v, uint32_t now)
{
    const int bob = (int)(now / 500 % 2);
    if (v->compact) {
        line_centered(fb, v, 0, 0, s.now.line[0] ? s.now.line : "offering");
        if (!sprite_draw(fb, v, SLOT_OURS, v->cx, v->bottom - bob)) poke_ball(fb, v->cx, v->cy, 9, 0);
        return;
    }
    half_title(fb, v, s.now.title[0] ? s.now.title : "trade", "");
    if (!sprite_draw(fb, v, SLOT_OURS, 96, 64 - bob)) poke_ball(fb, 96, 34, 12, 0);
    fb_text(fb, 0, 14, "offering", 1);
    text_wrapped(fb, 0, 24, 10, s.now.line);
    console_icon(fb, 0, 47);
    cable(fb, 24, 62, 53);
}

/* The lobby's text, one line each: the name, its stars, the seats taken, the Link Code. */
static int lobby_lines(char lines[4][TEXT_MAX])
{
    int n = 0;
    if (s.now.line[0]) snprintf(lines[n++], TEXT_MAX, "%s", s.now.line);
    if (s.lobby.stars) {
        snprintf(lines[n], TEXT_MAX, "%.*s", s.lobby.stars, "*******");
        ++n;
    }
    snprintf(lines[n++], TEXT_MAX, "%u/%u joined", (unsigned)s.lobby.joined, (unsigned)s.lobby.seats);
    if (s.lobby.code[0]) snprintf(lines[n++], TEXT_MAX, "%s", s.lobby.code);
    return n;
}

static void lobby_scene(uint8_t *fb, const view_t *v, uint32_t now)
{
    char lines[4][TEXT_MAX], cut[11];
    const int n = lobby_lines(lines);
    if (v->compact) {
        for (int i = 0; i < n; ++i) line_centered(fb, v, 0, 10 * i, lines[i]);
        return;
    }
    half_title(fb, v, s.now.title, "");
    if (!sprite_draw(fb, v, SLOT_OURS, 96, 64 - (int)(now / 500 % 2))) poke_ball(fb, 96, 34, 12, 0);
    for (int i = 0; i < n; ++i) {
        snprintf(cut, sizeof(cut), "%.10s", lines[i]);   /* the left half: 10 characters */
        fb_text(fb, 0, 14 + 12 * i, cut, 1);
    }
}

static void traded_scene(uint8_t *fb, const view_t *v, uint32_t now)
{
    static const int8_t DIR[8][2] = {{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}};
    const uint32_t t = elapsed(now);
    const int cx = v->cx, cy = v->cy, sb = v->small_ball;
    if (t < 1100) {   /* ours flashes, then goes back into its ball */
        if (t < 400 || (t < 700 && t / 80 % 2 == 0)) {
            if (!sprite_draw(fb, v, SLOT_OURS, cx, v->bottom)) poke_ball(fb, cx, cy, v->ball, 0);
        } else if (t >= 700) {
            poke_ball(fb, cx, cy, sb, 0);
            const int ray = (int)(t - 700) / (v->compact ? 60 : 40), in = sb + 2, out = sb + (v->compact ? 4 : 5);
            for (int k = 0; k < 8; ++k)
                fb_line(fb, cx + DIR[k][0] * (in + ray), cy + DIR[k][1] * (in + ray),
                        cx + DIR[k][0] * (out + ray), cy + DIR[k][1] * (out + ray));
        }
        line_centered(fb, v, 0, 0, "go!");
    } else if (t < LEAVE_MS) {   /* up and away through the link */
        const float x = (t - 1100) / 1000.0f;
        const int bx = lerp(cx, v->w + 12, x), by = lerp(cy, v->compact ? 4 : 6, x);
        poke_ball(fb, bx, by, sb, 0);
        for (int k = 1; k < 4; ++k)
            bit_glyph(fb, bx - (v->compact ? 8 : 10) * k, by + (v->compact ? 3 : 4) * k, (t / 90 + k) % 2);
    } else if (t < s.reveal) {   /* the exchange, for as long as the console's animation runs */
        title(fb, v, "trading...", NULL);
        if (t / 60 % 2) dot_spawn(t / 120 % 2 ? 1 : -1);
        link_strip(fb, v);
    } else if (t < s.reveal + LAND_MS) {   /* theirs drops in from the link */
        const float x = (t - s.reveal) / (float)LAND_MS;
        poke_ball(fb, lerp(-12, cx, x), lerp(v->compact ? 4 : 6, cy, x), sb, 0);
    } else if (t < s.reveal + 1000) {   /* lands, and wobbles */
        const uint32_t k = t - s.reveal - LAND_MS;
        poke_ball(fb, cx, cy, sb, wobble(k * WOBBLE_MS / (1000 - LAND_MS)));
    } else if (t < s.reveal + REVEAL_MS) {   /* and opens */
        const int k = (int)(t - s.reveal - 1000);
        open_ball(fb, cx, cy + (v->compact ? 3 : 4), sb + 2, k / (v->compact ? 80 : 60));
        const int flash = k * (v->compact ? 40 : 70) / 600, ring = v->compact ? 4 : 6;
        fb_circle(fb, cx, cy, flash, true, true);
        if (flash > ring) fb_circle(fb, cx, cy, flash - ring, true, false);
    } else if (v->compact) {
        line_centered(fb, v, 0, 0, s.now.line[0] ? s.now.line : "received");
        if (!sprite_draw(fb, v, SLOT_THEIRS, cx, v->bottom)) poke_ball(fb, cx, cy, 9, 0);
        sparkles(fb, 14, 10, 44, 30, t);
    } else {
        half_title(fb, v, s.now.title[0] ? s.now.title : "trade", "");
        if (!sprite_draw(fb, v, SLOT_THEIRS, 96, 64)) poke_ball(fb, 96, 34, 12, 0);
        sparkles(fb, 68, 4, 56, 56, t);
        fb_text(fb, 0, 18, "received", 1);
        text_wrapped(fb, 0, 30, 10, s.now.line);
    }
}

/* A Wonder Card: 58x48, or 38x31 on the compact panel. */
static void card(uint8_t *fb, const view_t *v, int x, int y)
{
    const int w = v->compact ? 38 : 58, h = v->compact ? 31 : 48;
    fb_fill(fb, x, y, w, h, false);
    fb_rect(fb, x, y, w, h);
    if (!v->compact) fb_rect(fb, x + 2, y + 2, w - 4, h - 4);
    if (!sprite_draw(fb, v, SLOT_GIFT, x + w / 2, y + h - (v->compact ? 2 : 4)))
        gift_box(fb, x + w / 2, y + (v->compact ? 18 : 26));
}

static void gift_scene(uint8_t *fb, const view_t *v, uint32_t now)
{
    const int bob = (int)(now / 600 % 2);
    if (v->compact) {
        line_centered(fb, v, 0, 0, s.now.line[0] ? s.now.line : s.now.title[0] ? s.now.title : "Mystery Gift");
        card(fb, v, 17, 9 - bob);
        return;
    }
    title(fb, v, s.now.title[0] ? s.now.title : "Mystery Gift", "gift");
    card(fb, v, 0, 14 - bob);
    text_wrapped(fb, 63, 16, 10, s.now.line);
    console_icon(fb, 105, 50);
    cable(fb, 103, 62, 56);
}

static void gifted_scene(uint8_t *fb, const view_t *v, uint32_t now)
{
    const uint32_t t = elapsed(now);
    if (t < 900) {   /* the card flies off through the link */
        const int x0 = v->compact ? 17 : 0, y = v->compact ? 9 : 14;
        card(fb, v, lerp(x0, v->w + 4, t / 900.0f), y);
        for (int k = 0; k < (v->compact ? 3 : 4); ++k)
            bit_glyph(fb, (int)(t / (v->compact ? 10 : 6)) - (v->compact ? 16 : 20) * k,
                      (v->compact ? 12 : 20) + 9 * k, (t / 70 + k) % 2);
        return;
    }
    if (v->compact) {
        line_centered(fb, v, 0, 0, "delivered!");
        gift_box(fb, v->cx, 27);
        sparkles(fb, 8, 12, 56, 28, t);
        return;
    }
    fb_text_centered(fb, 6, "delivered!", 2);
    gift_box(fb, 64, 40);
    sparkles(fb, 34, 22, 60, 36, t);
    fb_text_centered(fb, 56, s.now.line, 1);
}

/* The compact view drawn at the origin, moved into the panel's window; what fell outside it is dropped. */
static void to_window(uint8_t *fb)
{
    static uint8_t drawn[SCREEN_BYTES];
    memcpy(drawn, fb, SCREEN_BYTES);
    fb_clear(fb);
    for (int y = 0; y < SMALL_H; ++y)
        for (int x = 0; x < SMALL_W; ++x)
            if (fb_get(drawn, x, y)) fb_pixel(fb, SMALL_X + x, SMALL_Y + y, true);
}

/* ---- sounds ---------------------------------------------------------------------------------- */

/* True when `at` ms into the show falls in this frame: after the last frame's ms, up to `t`. */
static bool due(int64_t at, uint32_t t) { return at > s.heard && at <= (int64_t)t; }

/* The cue a show's frame at `t` ms starts, the latest when two fall in one frame. */
static uint8_t show_sound(uint32_t t)
{
    uint8_t cue = SOUND_NONE;
    if (s.now.show == SHOW_TRADED) {
        if (due(700, t)) cue = SOUND_RECALL;
        if (due(1100, t)) cue = SOUND_SEND;
        /* The data blips run from half a second into the exchange to 300 ms before theirs comes in. */
        const int64_t first = LEAVE_MS + 500, last = (int64_t)s.reveal - 300;
        if (t >= first && s.heard < last) {
            const int64_t from = s.heard < first ? 0 : (s.heard - first) / DATA_MS + 1;
            const int64_t at = first + from * DATA_MS;
            if (at <= t && at <= last) cue = SOUND_DATA;
        }
        if (due(s.reveal, t)) cue = SOUND_ARRIVE;
        if (due(s.reveal + LAND_MS, t)) cue = SOUND_WOBBLE;
        if (due(s.reveal + 1000, t)) cue = SOUND_OPEN;
        if (due(s.reveal + REVEAL_MS, t)) cue = SOUND_RECEIVED;
    } else if (s.now.show == SHOW_GIFTED) {
        if (due(0, t)) cue = SOUND_SEND;
        if (due(900, t)) cue = SOUND_DELIVERED;
    }
    return cue;
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

/* When the current show ends, in ms after its start; 0 while it lasts until the next show. */
static uint32_t ends(void)
{
    if (s.now.show == SHOW_TRADED) return s.reveal + REVEAL_MS + RECEIVED_MS;
    return s.now.hold_s * 1000u;
}

static void start(const show_t *show, uint32_t now)
{
    s.now = *show;
    s.started = now;
    s.heard = -1;
    /* A traded show's hold is the wait before theirs comes in: the console's animation. */
    const uint32_t wait = show->hold_s * 1000u;
    s.reveal = wait > LEAVE_MS + 1000 ? wait : LEAVE_MS + 1000;
}

bool scene_command(const uint8_t *p, size_t n, uint32_t now)
{
    wake.pending = true;
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
    if (p[0] == DISPLAY_OP_LOBBY) {
        if (n < 7 || p[1] > 7 || p[3] < 1 || p[3] > 3 || p[2] > p[3]) return false;
        show_t show = {.show = SHOW_LOBBY};
        const char *text = (const char *)p + 4, *end = (const char *)p + n;
        copy_text(show.title, &text, end);
        copy_text(show.line, &text, end);
        copy_text(s.lobby.code, &text, end);
        s.lobby.stars = p[1];
        s.lobby.joined = p[2];
        s.lobby.seats = p[3];
        s.has_next = false;
        start(&show, now);
        return true;
    }
    if (p[0] == DISPLAY_OP_JOINED) {
        if (n != 2 || s.now.show != SHOW_LOBBY || p[1] > s.lobby.seats) return false;
        s.lobby.joined = p[1];
        return true;
    }
    if (p[0] != DISPLAY_OP_SHOW || n < 4 || p[1] >= SHOWS) return false;
    if (p[1] == SHOW_ARRIVED) {   /* the console's animation is over: theirs comes in now */
        if (s.now.show == SHOW_TRADED && elapsed(now) < s.reveal)
            s.reveal = elapsed(now) > LEAVE_MS ? elapsed(now) : LEAVE_MS;
        return true;
    }
    show_t show = {.show = p[1], .hold_s = (uint16_t)(p[2] | p[3] << 8)};
    const char *text = (const char *)p + 4, *end = (const char *)p + n;
    copy_text(show.title, &text, end);
    copy_text(show.line, &text, end);
    /* A lasting show waits for a timed one to finish rather than cutting its animation short. */
    const bool timed = show.show == SHOW_TRADED || show.show == SHOW_GIFTED;
    if (ends() && !timed && elapsed(now) < ends()) {
        s.next = show;
        s.has_next = true;
    } else {
        s.has_next = false;
        start(&show, now);
    }
    return true;
}

void scene_panel(uint8_t panel) { s_panel = panel; }

void scene_reset(void)
{
    memset(&s, 0, sizeof(s));
    s.heard = -1;
    wake.pending = true;
}

/* Anything happening restarts the clock: a running radio, a trade or gift animation, a host
   command or session, a BOOT press. */
static uint8_t power(const scene_radio_t *radio, uint32_t now)
{
    if (!wake.seen || wake.pending || radio->presses != wake.presses || radio->mode != SCENE_IDLE ||
        s.now.show == SHOW_TRADED || s.now.show == SHOW_GIFTED)
        wake.last_ms = now;
    wake.seen = true;
    wake.pending = false;
    wake.presses = radio->presses;
    const uint32_t quiet = now - wake.last_ms;
    return quiet < DIM_MS ? SCENE_ON : quiet < OFF_MS ? SCENE_DIM : SCENE_OFF;
}

uint8_t scene_draw(uint8_t *fb, const scene_radio_t *radio, uint32_t now)
{
    if (ends() && elapsed(now) >= ends()) {
        const show_t none = {.show = SHOW_AUTO};
        start(s.has_next ? &s.next : &none, now);
        s.has_next = false;
    }
    /* A lasting show belongs to a session: a radio going back to idle has ended it. A show sent
       before the radio started stays. */
    if ((s.now.show == SHOW_TRADE || s.now.show == SHOW_GIFT || s.now.show == SHOW_LOBBY) &&
        radio->mode == SCENE_IDLE && s.radio_mode != SCENE_IDLE)
        s.now.show = SHOW_AUTO;
    s.radio_mode = radio->mode;
    const bool linked = radio->mode == SCENE_JOINED || (radio->mode == SCENE_HOSTING && radio->stations);
    s.sound = show_sound(elapsed(now));
    if (linked && !s.linked && s.sound == SOUND_NONE) s.sound = SOUND_LINKED;
    s.linked = linked;
    s.heard = s.now.show == SHOW_TRADED || s.now.show == SHOW_GIFTED ? (int32_t)elapsed(now) : -1;
    dots_step(radio->rx, radio->tx, now);
    fb_clear(fb);
    const view_t *v = &VIEWS[s_panel == PANEL_72X40 ? PANEL_72X40 : PANEL_128X64];
    switch (s.now.show) {
    case SHOW_TRADE: trade_scene(fb, v, now); break;
    case SHOW_TRADED: traded_scene(fb, v, now); break;
    case SHOW_GIFT: gift_scene(fb, v, now); break;
    case SHOW_GIFTED: gifted_scene(fb, v, now); break;
    case SHOW_LOBBY: lobby_scene(fb, v, now); break;
    default: radio_scene(fb, v, radio, now); break;
    }
    if (v->compact) to_window(fb);
    return power(radio, now);
}

uint8_t scene_sound(void) { return s.sound; }

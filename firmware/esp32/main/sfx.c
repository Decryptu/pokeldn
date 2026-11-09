#include "scene.h"
#include "sfx.h"

#define PEAK 9000           /* full volume; two notes never sound together, so no sum can clip */
#define RELEASE_MS 12       /* every note fades out over its last ms, so none ends in a click */

/* One note: a square wave of `duty` eighths sliding from f0 to f1 Hz, or noise (f0 0), at `volume`
   sixteenths, fading to `fade` sixteenths of that by its end. */
typedef struct {
    uint16_t f0, f1, ms;
    uint8_t duty, volume, fade;
} note_t;

#define REST(ms) {0, 1, ms, 0, 0, 0}
#define NOISE(ms, v) {0, 0, ms, 0, v, 0}

/* Note values: C6 1047, D6 1175, E6 1319, G6 1568, A6 1760, C7 2093. Original sequences, written here. */
static const note_t LINKED[] = {{1319, 1319, 55, 2, 10, 8}, {1976, 1976, 110, 2, 10, 0}};
static const note_t RECALL[] = {{1800, 500, 170, 4, 9, 4}, NOISE(30, 5)};
static const note_t SEND[] = {{350, 1900, 260, 2, 9, 3}};
static const note_t DATA[] = {{2093, 2093, 28, 4, 5, 2}};
static const note_t ARRIVE[] = {{1900, 700, 280, 2, 9, 5}};
static const note_t WOBBLE[] = {NOISE(14, 9), REST(116), NOISE(14, 7), REST(116), NOISE(14, 5)};
static const note_t OPEN[] = {NOISE(25, 10), {1568, 1568, 40, 2, 10, 8}, {2093, 2637, 90, 2, 10, 0}};
static const note_t RECEIVED[] = {
    {784, 784, 90, 2, 10, 9}, {1047, 1047, 90, 2, 10, 9}, {1319, 1319, 90, 2, 10, 9},
    REST(30), {1175, 1175, 90, 2, 10, 9}, {1568, 1568, 380, 2, 11, 0},
};
static const note_t DELIVERED[] = {{1568, 1568, 90, 2, 10, 9}, {2093, 2093, 90, 2, 10, 9},
                                   {2637, 2637, 320, 4, 10, 0}};

static const struct {
    const note_t *notes;
    uint8_t count;
} SEQUENCES[SOUNDS] = {
#define SEQ(name) {name, sizeof(name) / sizeof(name[0])}
    [SOUND_LINKED] = SEQ(LINKED), [SOUND_RECALL] = SEQ(RECALL), [SOUND_SEND] = SEQ(SEND),
    [SOUND_DATA] = SEQ(DATA), [SOUND_ARRIVE] = SEQ(ARRIVE), [SOUND_WOBBLE] = SEQ(WOBBLE),
    [SOUND_OPEN] = SEQ(OPEN), [SOUND_RECEIVED] = SEQ(RECEIVED), [SOUND_DELIVERED] = SEQ(DELIVERED),
#undef SEQ
};

static size_t samples(uint16_t ms) { return (size_t)ms * SFX_RATE / 1000; }

size_t sfx_length(uint8_t cue)
{
    if (cue >= SOUNDS) return 0;
    size_t n = 0;
    for (int i = 0; i < SEQUENCES[cue].count; ++i) n += samples(SEQUENCES[cue].notes[i].ms);
    return n;
}

/* Sample `k` of note `n`; the phase is computed from k alone, so rendering in chunks changes nothing. */
static int16_t sample(const note_t *n, size_t k)
{
    const size_t len = samples(n->ms), release = samples(RELEASE_MS);
    if (!n->volume) return 0;
    /* volume, fading linearly to fade/16 of itself, then to 0 over the release */
    int32_t level = PEAK * n->volume / 16;
    level -= (int32_t)((int64_t)level * (16 - n->fade) / 16 * (int64_t)k / (int64_t)len);
    if (k + release > len) level = (int32_t)((int64_t)level * (int64_t)(len - k) / (int64_t)release);
    bool high;
    if (!n->f0) {
        /* noise: a hashed bit per 1/4000 s, a function of k alone */
        uint32_t x = (uint32_t)(k / 4) * 2654435761u;
        x ^= x >> 15;
        high = x >> 7 & 1;
    } else {
        /* the phase of a linear slide f0 -> f1: f0 k + (f1 - f0) k^2 / 2 len, in cycles of 1/SFX_RATE */
        const int64_t f0 = n->f0, df = (int64_t)n->f1 - n->f0, kk = (int64_t)k;
        const int64_t cycles_x8 = (8 * f0 * kk + 4 * df * kk * kk / (int64_t)len) / SFX_RATE;   /* eighths */
        high = cycles_x8 % 8 < n->duty;
    }
    return (int16_t)(high ? level : -level);
}

size_t sfx_render(uint8_t cue, size_t from, int16_t *out, size_t max)
{
    if (cue >= SOUNDS || !SEQUENCES[cue].notes) return 0;
    size_t written = 0, start = 0;
    for (int i = 0; i < SEQUENCES[cue].count && written < max; ++i) {
        const note_t *n = &SEQUENCES[cue].notes[i];
        const size_t len = samples(n->ms);
        while (written < max && from + written < start + len) {
            out[written] = sample(n, from + written - start);
            ++written;
        }
        start += len;
    }
    return written;
}

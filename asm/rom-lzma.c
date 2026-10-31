/* LZMA decoder for asm/rom-transfer.s, built Thumb by scripts/gen_buffer_scripts.py
 * [docs/rse_switch_build.md, The LZMA stream]. The dictionary is the ROM copy itself: virtual
 * position v < base is the console's own byte at 0x08000000 + v; past it, block k of the stream is
 * ROM block ORDER[k] (or its staging slot when live), the block being decoded is STAGING. The host
 * writes ORDER, a u16 a block, to ROM blocks 0xFFD and 0xFFE before the stream.
 * lc = 0, lp = 0, pb = 2. Entry: lz_call(message) -> 1 when the message is consumed, 0 to be called
 * again next frame. */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define ROM ((volatile u8 *)0x08000000)
#define STAGING ((u8 *)0x0201C800)
#define ORDER ((const volatile u16 *)0x08FFD000)
#define STATUS ((u32 *)0x0201D800)
#define S ((struct state *)0x0201E000)
#define BLOCK 0x1000
#define OP_LZ_START 6
#define OP_LZ_DATA 7
#define BUDGET 1000            /* per frame: a copied byte costs 1, a symbol SYMBOL_COST */
#define SYMBOL_COST 6
#define LOOKAHEAD 20           /* LZMA_REQUIRED_INPUT_MAX */
#define IN_SIZE 1280

enum { P_MATCH = 0, P_REP = 192, P_REPG0 = 204, P_REPG1 = 216, P_REPG2 = 228, P_REP0LONG = 240,
       P_SLOT = 432, P_SPEC = 688, P_ALIGN = 802, P_LEN = 818, P_REPLEN = 1332, P_LIT = 1846,
       N_PROBS = 1846 + 0x300 };
enum { L_CHOICE = 0, L_CHOICE2 = 1, L_LOW = 2, L_MID = 130, L_HIGH = 258 };

struct state {
    u32 range, code, st, rep[4];
    u32 base, e, left;                 /* stream base, bytes emitted, bytes left in chunk */
    u32 pending, final, seq, primed;
    u32 in_len, in_pos;
    u32 staging0, nlive;
    u16 live[160];
    u8 in[IN_SIZE];
    u16 p[N_PROBS];
};

static u32 slot(u32 b)
{
    struct state *s = S;
    u32 lo = 0, hi = s->nlive;
    while (lo < hi) {
        u32 mid = (lo + hi) >> 1;
        if (s->live[mid] < b)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo < s->nlive && s->live[lo] == b ? s->staging0 + lo : b;
}

static u32 at(u32 v)
{
    struct state *s = S;
    u32 here = s->base + (s->e & ~(BLOCK - 1));
    if (v >= here)
        return STAGING[v - here];
    if (v < s->base)
        return ROM[v];
    v -= s->base;
    return ROM[(slot(ORDER[v >> 12]) << 12) + (v & (BLOCK - 1))];
}

static void norm(struct state *s)
{
    if (s->range < (1u << 24)) {
        s->range <<= 8;
        s->code = (s->code << 8) | s->in[s->in_pos++];
    }
}

static u32 bit(struct state *s, u16 *p)
{
    u32 bound = (s->range >> 11) * *p, b;
    if (s->code < bound) {
        s->range = bound;
        *p += (2048 - *p) >> 5;
        b = 0;
    } else {
        s->code -= bound;
        s->range -= bound;
        *p -= *p >> 5;
        b = 1;
    }
    norm(s);
    return b;
}

static u32 tree(struct state *s, u16 *p, u32 n)
{
    u32 m = 1, k;
    for (k = 0; k < n; k++)
        m = (m << 1) | bit(s, p + m);
    return m - (1u << n);
}

static u32 rtree(struct state *s, u16 *p, u32 n)
{
    u32 m = 1, sym = 0, k;
    for (k = 0; k < n; k++) {
        u32 b = bit(s, p + m);
        m = (m << 1) | b;
        sym |= b << k;
    }
    return sym;
}

static u32 length(struct state *s, u16 *l, u32 ps)
{
    if (!bit(s, l + L_CHOICE))
        return tree(s, l + L_LOW + (ps << 3), 3) + 2;
    if (!bit(s, l + L_CHOICE2))
        return tree(s, l + L_MID + (ps << 3), 3) + 10;
    return tree(s, l + L_HIGH, 8) + 18;
}

static void sw48(u32 sector, void *source)
{
    register u32 r0 asm("r0") = sector;
    register void *r1 asm("r1") = source;
    asm volatile("swi 0x48" : "+r"(r0), "+r"(r1) : : "r2", "r3", "memory");
}

static void finish_block(struct state *s)
{
    u32 b = ORDER[(s->e >> 12) - 1], phys = slot(b), k, diff = 0;
    const u32 *a = (const u32 *)(0x08000000 + (phys << 12)), *c = (const u32 *)STAGING;
    sw48(0xFA000 + phys, STAGING);
    for (k = 0; k < BLOCK / 4; k++)
        diff |= a[k] ^ c[k];
    if (diff) {
        STATUS[0]++;
        if (STATUS[1] == 0xFFFFFFFFu)
            STATUS[1] = phys;
    }
}

static const u8 next_lit[12] = {0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 4, 5};

static void put(struct state *s, u32 byte)
{
    STAGING[s->e & (BLOCK - 1)] = byte;
    s->e++;
    s->left--;
    if (!(s->e & (BLOCK - 1)))
        finish_block(s);
}

/* One symbol; -> bytes decoded. */
static u32 symbol(struct state *s)
{
    u32 ps = s->e & 3, st = s->st, len, dist;
    if (!bit(s, s->p + P_MATCH + (st << 4) + ps)) {
        u16 *probs = s->p + P_LIT;
        u32 sym = 1;
        if (st >= 7) {
            u32 mb = at(s->base + s->e - s->rep[0] - 1), offs = 0x100;
            while (sym < 0x100) {
                u32 b;
                mb <<= 1;
                b = bit(s, probs + offs + (mb & offs) + sym);
                sym = (sym << 1) | b;
                offs &= b ? (mb & offs) : ~(mb & offs);
            }
        } else {
            while (sym < 0x100)
                sym = (sym << 1) | bit(s, probs + sym);
        }
        s->st = next_lit[st];
        put(s, sym & 0xFF);
        return 1;
    }
    if (bit(s, s->p + P_REP + st)) {
        u32 r;
        if (!bit(s, s->p + P_REPG0 + st)) {
            bit(s, s->p + P_REP0LONG + (st << 4) + ps);         /* the encoder never codes a short rep */
        } else {
            if (!bit(s, s->p + P_REPG1 + st)) {
                r = s->rep[1];
            } else {
                if (!bit(s, s->p + P_REPG2 + st)) {
                    r = s->rep[2];
                } else {
                    r = s->rep[3];
                    s->rep[3] = s->rep[2];
                }
                s->rep[2] = s->rep[1];
            }
            s->rep[1] = s->rep[0];
            s->rep[0] = r;
        }
        len = length(s, s->p + P_REPLEN, ps);
        s->st = st < 7 ? 8 : 11;
    } else {
        u32 slot_, nd;
        len = length(s, s->p + P_LEN, ps);
        slot_ = tree(s, s->p + P_SLOT + ((len - 2 < 3 ? len - 2 : 3) << 6), 6);
        if (slot_ < 4) {
            dist = slot_;
        } else {
            nd = (slot_ >> 1) - 1;
            dist = (2 | (slot_ & 1)) << nd;
            if (slot_ < 14) {
                dist += rtree(s, s->p + P_SPEC + dist - slot_ - 1, nd);
            } else {
                u32 k, v = 0;
                for (k = 0; k < nd - 4; k++) {
                    s->range >>= 1;
                    if (s->code >= s->range) {
                        s->code -= s->range;
                        v = (v << 1) | 1;
                    } else {
                        v <<= 1;
                    }
                    norm(s);
                }
                dist += (v << 4) + rtree(s, s->p + P_ALIGN, 4);
            }
        }
        s->rep[3] = s->rep[2];
        s->rep[2] = s->rep[1];
        s->rep[1] = s->rep[0];
        s->rep[0] = dist;
        s->st = st < 7 ? 7 : 10;
    }
    s->pending = len;
    return 0;
}

/* Copies the pending match a run at a time: a run stays inside one source block and one STAGING. */
static u32 copy(struct state *s, u32 budget)
{
    u32 n = 0;
    while (s->pending && n < budget) {
        u32 v = s->base + s->e - s->rep[0] - 1, here = s->base + (s->e & ~(BLOCK - 1));
        u32 run = BLOCK - (s->e & (BLOCK - 1)), k;
        const volatile u8 *src;
        if (v >= here) {
            src = STAGING + (v - here);
        } else if (v < s->base) {
            src = ROM + v;
            if (s->base - v < run)
                run = s->base - v;
        } else {
            u32 w = v - s->base;
            src = ROM + (slot(ORDER[w >> 12]) << 12) + (w & (BLOCK - 1));
            if (BLOCK - (w & (BLOCK - 1)) < run)
                run = BLOCK - (w & (BLOCK - 1));
        }
        if (v < here && (v & (BLOCK - 1)) + run > BLOCK)
            run = BLOCK - (v & (BLOCK - 1));        /* a ROM source block ends; the next may move */
        if (run > s->pending)
            run = s->pending;
        if (run > budget - n)
            run = budget - n;
        for (k = 0; k < run; k++)
            STAGING[(s->e + k) & (BLOCK - 1)] = src[k];
        s->e += run;
        s->left -= run;
        s->pending -= run;
        n += run;
        if (!(s->e & (BLOCK - 1)))
            finish_block(s);
    }
    return n;
}

__attribute__((section(".text.entry"))) int lz_call(u8 *msg)
{
    struct state *s = S;
    u32 done = 0, k;
    if (msg[4] == OP_LZ_START) {
        s->left = (msg[8] | msg[9] << 8) << 12;
        s->staging0 = msg[10] | msg[11] << 8;
        s->base = msg[12] | msg[13] << 8 | msg[14] << 16 | msg[15] << 24;
        s->e = msg[16] | msg[17] << 8 | msg[18] << 16 | msg[19] << 24;
        s->nlive = msg[20] | msg[21] << 8;
        for (k = 0; k < s->nlive; k++)
            s->live[k] = msg[22 + 2 * k] | msg[23 + 2 * k] << 8;
        for (k = 0; k < N_PROBS; k++)
            s->p[k] = 1024;
        s->st = s->rep[0] = s->rep[1] = s->rep[2] = s->rep[3] = 0;
        s->pending = s->in_len = s->in_pos = s->final = s->primed = 0;
        s->seq = 0xFFFFFFFFu;
        return 1;
    }
    if (msg[4] != OP_LZ_DATA)
        return 1;
    k = msg[6] | msg[7] << 8;
    if (k != s->seq) {                            /* first call for this message: take its bytes */
        u32 n = msg[8] | msg[9] << 8, i, j = 0;
        for (i = s->in_pos; i < s->in_len; i++)
            s->in[j++] = s->in[i];
        for (i = 0; i < n; i++)
            s->in[j++] = msg[10 + i];
        s->in_len = j;
        s->in_pos = 0;
        s->seq = k;
        s->final = msg[5] & 1;
    }
    if (!s->primed) {
        if (s->in_len < 5)
            return 1;
        s->range = 0xFFFFFFFFu;
        s->code = s->in[1] << 24 | s->in[2] << 16 | s->in[3] << 8 | s->in[4];
        s->in_pos = 5;
        s->primed = 1;
    }
    while (s->left && done < BUDGET) {
        if (s->pending) {
            done += copy(s, BUDGET - done);
            continue;
        }
        if (!s->final && s->in_len - s->in_pos < LOOKAHEAD)
            return 1;
        symbol(s);
        done += SYMBOL_COST;
    }
    if (!s->left)
        return 1;
    return s->final ? 0 : s->in_len - s->in_pos < LOOKAHEAD;
}

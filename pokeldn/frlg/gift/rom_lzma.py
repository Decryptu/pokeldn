"""The ROM transfer's LZMA stream: what asm/rom-lzma.c decodes [docs/rse_switch_build.md, The LZMA
stream]. lc = 0, lp = 0, pb = 2, greedy parse, a model reset every chunk.

The dictionary is the console's ROM copy as it stands while the stream decodes: virtual position
v < BLOCKS * BLOCK is the copy's byte v, and past it the stream's own output, block k of it being ROM
block order[k]. A copy block is a source only while it still holds what the host knows of it: not
yet overwritten by the stream, and known from the survey. The order puts a block before the copy
blocks it would copy from [order]."""

import heapq

import struct
from array import array


BLOCK = 0x1000
BLOCKS = 0x1000
BASE = BLOCKS * BLOCK
PB_MASK = 3
MATCH_MAX = 273
CHAIN = 24
HASH_BITS = 22
# asm/rom-lzma.c's per-frame accounting: a symbol costs SYMBOL_COST, a copied byte 1, BUDGET a frame
# (tests/test_rom_transfer.py reads both from the source).
SYMBOL_COST = 6
BUDGET = 1000
MARK_STEP = 256

NEXT_LIT = (0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 4, 5)
UNKNOWN, EMITTED, LIVE, SLOT, STILL = range(5)


class _Encoder:
    def __init__(self):
        self.low, self.range, self.cache, self.csize, self.out = 0, 0xFFFFFFFF, 0, 1, bytearray()

    def _shift(self):
        if self.low < 0xFF000000 or self.low >= 1 << 32:
            carry, temp = self.low >> 32, self.cache
            while True:
                self.out.append((temp + carry) & 0xFF)
                temp = 0xFF
                self.csize -= 1
                if not self.csize:
                    break
            self.cache = (self.low >> 24) & 0xFF
        self.csize += 1
        self.low = (self.low & 0x00FFFFFF) << 8

    def bit(self, probs, i, b):
        p = probs[i]
        bound = (self.range >> 11) * p
        if b:
            self.low += bound
            self.range -= bound
            probs[i] = p - (p >> 5)
        else:
            self.range = bound
            probs[i] = p + ((2048 - p) >> 5)
        while self.range < 1 << 24:
            self.range <<= 8
            self._shift()

    def direct(self, value, n):
        for k in range(n - 1, -1, -1):
            self.range >>= 1
            if (value >> k) & 1:
                self.low += self.range
            while self.range < 1 << 24:
                self.range <<= 8
                self._shift()

    def tree(self, probs, base, nbits, sym):
        m = 1
        for k in range(nbits - 1, -1, -1):
            b = (sym >> k) & 1
            self.bit(probs, base + m, b)
            m = (m << 1) | b

    def rtree(self, probs, base, nbits, sym):
        m = 1
        for _ in range(nbits):
            b = sym & 1
            sym >>= 1
            self.bit(probs, base + m, b)
            m = (m << 1) | b

    def flush(self):
        for _ in range(5):
            self._shift()


class _Model:
    def __init__(self):
        self.match, self.rep0long = [1024] * 192, [1024] * 192
        self.rep, self.repg0, self.repg1, self.repg2 = ([1024] * 12 for _ in range(4))
        self.slot, self.spec, self.align, self.lit = [1024] * 256, [1024] * 114, [1024] * 16, [1024] * 0x300
        self.lens = [[1024] * 514, [1024] * 514]            # choice, choice2, low[16][8], mid[16][8], high


def _length(enc, probs, n, ps):
    n -= 2
    if n < 8:
        enc.bit(probs, 0, 0)
        enc.tree(probs, 2 + (ps << 3), 3, n)
    elif n < 16:
        enc.bit(probs, 0, 1)
        enc.bit(probs, 1, 0)
        enc.tree(probs, 130 + (ps << 3), 3, n - 8)
    else:
        enc.bit(probs, 0, 1)
        enc.bit(probs, 1, 1)
        enc.tree(probs, 258, 8, n - 16)


def _distance(enc, model, dist, n):
    if dist < 4:
        slot = dist
    else:
        top = dist.bit_length() - 1
        slot = (top << 1) | ((dist >> (top - 1)) & 1)
    enc.tree(model.slot, min(n - 2, 3) << 6, 6, slot)
    if slot >= 4:
        nd = (slot >> 1) - 1
        base = (2 | (slot & 1)) << nd
        rest = dist - base
        if slot < 14:
            enc.rtree(model.spec, base - slot - 1, nd, rest)
        else:
            enc.direct(rest >> 4, nd - 4)
            enc.rtree(model.align, 0, 4, rest & 15)


def order(refs, blocks, live, least=8):
    """-> an emission order for `blocks`: a block that copies at least `least` bytes from copy block m
    goes before m (Kahn's sort, the highest block first among the free; a cycle is broken at the
    highest block left). `refs`: block -> {copy block: bytes}, from Stream.references()."""
    blocks, live = set(blocks), set(live)
    after = {b: set() for b in blocks}
    indeg = dict.fromkeys(blocks, 0)
    for c, d in refs.items():
        for m, n in d.items():
            if n >= least and m != c and c in blocks and m in blocks and m not in live and m not in after[c]:
                after[c].add(m)
                indeg[m] += 1
    ready = [-b for b in blocks if not indeg[b]]
    heapq.heapify(ready)
    out, done = [], set()
    while len(out) < len(blocks):
        if ready:
            b = -heapq.heappop(ready)
            if b in done:
                continue
        else:
            b = max(blocks - done)
        done.add(b)
        out.append(b)
        for m in after[b]:
            indeg[m] -= 1
            if not indeg[m] and m not in done:
                heapq.heappush(ready, -m)
    return out


class Stream:
    """`copy`: the host's model of the console's 16 MB copy; `known[m]`: whether block m of it is
    what the copy holds. `targets`: block -> its 4 KB; `order`: the blocks in emission order;
    `slots`: live block -> its staging block. `free=True` ignores what the stream overwrites, for
    references()."""

    def __init__(self, copy, known, targets, order, slots, free=False):
        self.order, self.slots, self.free = list(order), dict(slots), free
        self.pos = {b: k for k, b in enumerate(self.order)}
        self.owner = {slot: block for block, slot in self.slots.items()}
        self.kind = bytearray(BLOCKS)
        for m in range(BLOCKS):
            if not known[m]:
                self.kind[m] = UNKNOWN
            elif m in self.owner:
                self.kind[m] = SLOT
            elif m in self.slots:
                self.kind[m] = LIVE
            elif m in self.pos:
                self.kind[m] = EMITTED
            else:
                self.kind[m] = STILL
        self.refs = {}
        self.v = bytes(copy) + b"".join(targets[b] for b in self.order)
        self._index()

    def _index(self):
        """Hash chains over every 4-byte key, copy and stream alike; a chain skips 0xFF runs."""
        v, mask = self.v, (1 << HASH_BITS) - 1
        head = array("i", [-1]) * (1 << HASH_BITS)
        prev = array("i", [-1]) * len(v)
        unpack = struct.Struct("<I").unpack_from
        for i in range(len(v) - 3):
            word = unpack(v, i)[0]
            if word == 0xFFFFFFFF:
                continue
            h = ((word * 2654435761) & 0xFFFFFFFF) >> (32 - HASH_BITS) & mask
            prev[i] = head[h]
            head[h] = i
        self.prev = prev

    def _available(self, m, current):
        """`current`: the emission position being decoded."""
        kind = self.kind[m]
        if kind == UNKNOWN:
            return False
        if self.free:
            return True
        if kind == EMITTED:
            return self.pos[m] >= current
        if kind == SLOT:
            return self.pos[self.owner[m]] >= current
        return True

    def references(self):
        """-> {block: {copy block: bytes}} its matches take from the copy, the stream unconstrained."""
        self.free, self.refs = True, {}
        self.chunks()
        self.free = False
        return self.refs

    def _limit(self, src, current):
        """How far a match from copy byte `src` may run before a block it may not read."""
        m = src >> 12
        while m < BLOCKS and self._available(m, current):
            if (m << 12) - src >= MATCH_MAX + 1:
                return MATCH_MAX
            m += 1
        # A literal after the match is coded against the next byte: it must be one the host knows.
        return (m << 12) - src - (m < BLOCKS and self.kind[m] == UNKNOWN)

    def chunks(self, size=64):
        """-> [(bytes emitted before the chunk, blocks in it, its LZMA bytes, marks)]; a mark (byte,
        cost) says decoding needs the stream up to `byte` to have spent `cost` units of the
        decoder's budget, one mark per MARK_STEP units."""
        out, total = [], len(self.order)
        for first in range(0, total, size):
            count = min(size, total - first)
            out.append((first * BLOCK, count, *self._chunk(BASE + first * BLOCK, BASE + (first + count) * BLOCK)))
        return out

    def _chunk(self, begin, end):
        enc, model, v, prev = _Encoder(), _Model(), self.v, self.prev
        state, reps, i = 0, [0, 0, 0, 0], begin
        cost, marks = 0, []
        while i < end:
            if cost >= (len(marks) + 1) * MARK_STEP:
                marks.append((len(enc.out) + enc.csize, cost))
            current = (i - BASE) >> 12
            room = min(MATCH_MAX, end - i)

            def run(src):
                limit = room if src >= BASE else min(room, self._limit(src, current))
                n = 0
                while n < limit and v[src + n] == v[i + n]:
                    n += 1
                return n

            def usable(src):
                return 0 <= src < i and (src >= BASE or self._available(src >> 12, current))

            rep_k, rep_n = -1, 0
            for k, r in enumerate(reps):
                src = i - r - 1
                if usable(src):
                    n = run(src)
                    if n > rep_n:
                        rep_k, rep_n = k, n
            best_n, best_d, c, tries = 0, 0, prev[i] if i < len(prev) else -1, 0
            while c >= 0 and tries < CHAIN:
                if usable(c):
                    n = run(c)
                    if n > best_n:
                        best_n, best_d = n, i - c - 1
                        if n == room:
                            break
                c, tries = prev[c], tries + 1
            ps = (i - BASE) & PB_MASK
            if rep_n >= 2 and rep_n + 1 >= best_n:
                enc.bit(model.match, (state << 4) + ps, 1)
                enc.bit(model.rep, state, 1)
                if rep_k == 0:
                    enc.bit(model.repg0, state, 0)
                    enc.bit(model.rep0long, (state << 4) + ps, 1)
                else:
                    enc.bit(model.repg0, state, 1)
                    enc.bit(model.repg1, state, rep_k != 1)
                    if rep_k > 1:
                        enc.bit(model.repg2, state, rep_k - 2)
                    reps.insert(0, reps.pop(rep_k))
                _length(enc, model.lens[1], rep_n, ps)
                state = 8 if state < 7 else 11
                i += rep_n
                cost += SYMBOL_COST + rep_n
            elif best_n >= 3 or (best_n == 2 and best_d < 128):
                if self.free and i - best_d - 1 < BASE:
                    taken = self.refs.setdefault(self.order[current], {})
                    m = (i - best_d - 1) >> 12
                    taken[m] = taken.get(m, 0) + best_n
                enc.bit(model.match, (state << 4) + ps, 1)
                enc.bit(model.rep, state, 0)
                _length(enc, model.lens[0], best_n, ps)
                _distance(enc, model, best_d, best_n)
                reps = [best_d] + reps[:3]
                state = 7 if state < 7 else 10
                i += best_n
                cost += SYMBOL_COST + best_n
            else:
                enc.bit(model.match, (state << 4) + ps, 0)
                byte = v[i]
                if state >= 7:                  # a matched literal against what the console holds
                    src = i - reps[0] - 1
                    mb, offs, sym = self._held(src, current), 0x100, byte | 0x100
                    while sym < 0x10000:
                        mb <<= 1
                        enc.bit(model.lit, offs + (mb & offs) + (sym >> 8), (sym >> 7) & 1)
                        sym <<= 1
                        offs &= ~(mb ^ sym)
                else:
                    enc.tree(model.lit, 0, 8, byte)
                state = NEXT_LIT[state]
                i += 1
                cost += SYMBOL_COST
        enc.flush()
        return bytes(enc.out), marks

    def _held(self, src, current):
        """The byte the console reads at virtual `src`, where the stream may have replaced the copy."""
        if src >= BASE or self._available(src >> 12, current):
            return self.v[src]
        m = src >> 12                          # overwritten: by its own target, or a staged block
        return self.v[BASE + self.pos[self.owner.get(m, m)] * BLOCK + (src & (BLOCK - 1))]

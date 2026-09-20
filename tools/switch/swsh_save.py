#!/usr/bin/env python3
"""Read a Sword/Shield save (`main`) into its blocks: the xorpad and per-block XorShift PKHeX's
SwishCrypto/SCBlock describe. Keys are PKHeX's SaveBlockAccessor8SWSH names where known.
Usage: swsh_save.py <main> [--key HEX] [--out FILE] [--grep HEX] [--patch KEY OFF HEX --write OUT]
    no flag     every block: key, type, size, and whether the file's SHA-256 checks
    --key       hexdump that block (or --out FILE to write it)
    --grep      the blocks and offsets holding those bytes
    --patch     write HEX over that block at OFF, in place, and reseal the hash into OUT"""
import struct, sys, hashlib

INTRO = bytes.fromhex("9EC99CD70ED33C44FB9303DCEB39B42A1947E9634BA2334416BF82A2BA6355B6"
                      "3D9DF24B5F7B6AB2621DC21B68E5C8B53A059000E8A8103DE2ECF00CB2ED4F6D")
OUTRO = bytes.fromhex("D6C01C598BC8B8CB46E153FC828C757513E045DF32693C75F059F8D9A25FB217"
                      "E08052DBEA89739975 79AFCB2E8007E6F126E0030AE66FF641BF7E59C2AE55FD".replace(" ", ""))

STATIC_XORPAD = bytes.fromhex(
    "A092D10607DB32A1AE01F5C51E844FE353CA37F4A7B04DA018B7C297DA5F532B"
    "75FA4816F8D48A6F6105F4E2FD04B5A30FFC4492CB32E61BB9B12E01B0565336"
    "D2D1503DDE5B2E0E52FDDF2F7BCA6350A4675D2317C052E1A6307C2BB670365B"
    "2A276933F5637B363F269BA3ED7A5300A448B3509E14A052DE7E102B1B776E")   # 0x7F bytes
SIZES = {3: 1, 8: 1, 9: 2, 10: 4, 11: 8, 12: 1, 13: 2, 14: 4, 15: 8, 16: 4, 17: 8}
NAMES = {0x112d5141: "MysteryGift", 0x16aaa7fa: "Coordinates", 0xf25c070e: "MyStatus",
         0x874da6fa: "TrainerCard", 0x1177c2c4: "MyItem", 0x2985fe5d: "Party", 0x0d66012c: "Box",
         0x37da95a3: "Record"}


class XorShift32:
    def __init__(self, seed):
        s = seed & 0xFFFFFFFF
        for _ in range(bin(s).count("1")):
            s = self.advance(s)
        self.state, self.counter = s, 0

    @staticmethod
    def advance(s):
        s ^= (s << 2) & 0xFFFFFFFF
        s ^= s >> 15
        s ^= (s << 13) & 0xFFFFFFFF
        return s

    def next(self):
        r = (self.state >> (self.counter << 3)) & 0xFF
        if self.counter == 3:
            self.state, self.counter = self.advance(self.state), 0
        else:
            self.counter += 1
        return r

    def next32(self):
        return self.next() | self.next() << 8 | self.next() << 16 | self.next() << 24

    def xor(self, data):
        return bytes(b ^ self.next() for b in data)


def file_hash(payload):
    return hashlib.sha256(INTRO + payload + OUTRO).digest()


def hash_ok(data):
    return file_hash(data[:-0x20]) == data[-0x20:]


def decrypt(data, where=None):
    """-> [(key, type, subtype, bytes)] out of a whole `main` (the SHA-256 at the end ignored).
    `where`, a dict, receives key -> (offset of the data in the file, the XorShift state there)."""
    body = bytearray(data[:-0x20])
    for i in range(len(body)):
        body[i] ^= STATIC_XORPAD[i % 0x7F]
    blocks, off = [], 0
    while off < len(body):
        key = struct.unpack_from("<I", body, off)[0]; off += 4
        xk = XorShift32(key)
        t = body[off] ^ xk.next(); off += 1
        if t in (1, 2, 3):
            blocks.append((key, t, None, b"")); continue
        sub = None
        if t == 4:
            size = struct.unpack_from("<I", body, off)[0] ^ xk.next32(); off += 4
        elif t == 5:
            n = struct.unpack_from("<I", body, off)[0] ^ xk.next32(); off += 4
            sub = body[off] ^ xk.next(); off += 1
            size = n * SIZES[sub]
        else:
            size = SIZES[t]
        if where is not None:
            where[key] = (off, (xk.state, xk.counter))
        blocks.append((key, t, sub, xk.xor(body[off:off + size]))); off += size
    return blocks


def encrypt(blocks):
    """-> a whole `main` out of [(key, type, subtype, bytes)], the inverse of `decrypt`."""
    body = bytearray()
    for key, t, sub, d in blocks:
        xk = XorShift32(key)
        body += struct.pack("<I", key) + bytes([t ^ xk.next()])
        if t in (1, 2, 3):
            continue
        if t == 4:
            body += struct.pack("<I", len(d) ^ xk.next32())
        elif t == 5:
            body += struct.pack("<I", (len(d) // SIZES[sub]) ^ xk.next32()) + bytes([sub ^ xk.next()])
        body += xk.xor(d)
    for i in range(len(body)):
        body[i] ^= STATIC_XORPAD[i % 0x7F]
    return bytes(body) + file_hash(bytes(body))


def patch(data, key, at, new):
    """-> the file with `new` written over block `key` at `at`, the two XOR layers kept, resealed."""
    where = {}
    decrypt(data, where)
    off, (state, counter) = where[key]
    xk = XorShift32(key); xk.state, xk.counter = state, counter
    stream = bytes(xk.next() for _ in range(at + len(new)))[at:]
    out = bytearray(data)
    for i, b in enumerate(new):
        pos = off + at + i
        out[pos] = b ^ stream[i] ^ STATIC_XORPAD[pos % 0x7F]
    out[-0x20:] = file_hash(bytes(out[:-0x20]))
    return bytes(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    raw = open(args[0], "rb").read()
    blocks = decrypt(raw)
    by_key = {b[0]: b for b in blocks}
    if "--patch" in args:
        i = args.index("--patch")
        key, at, new = int(args[i + 1], 16), int(args[i + 2], 0), bytes.fromhex(args[i + 3])
        out = patch(raw, key, at, new)
        open(args[args.index("--write") + 1], "wb").write(out)
        check = {b[0]: b for b in decrypt(out)}[key][3]
        print("written; block reads back", "as patched" if check[at:at + len(new)] == new else "WRONG",
              "; hash", "ok" if hash_ok(out) else "BAD")
    elif "--key" in args:
        key = int(args[args.index("--key") + 1], 16)
        k, t, sub, d = by_key[key]
        if "--out" in args:
            open(args[args.index("--out") + 1], "wb").write(d); print(len(d), "bytes")
        else:
            for o in range(0, min(len(d), 0x400), 16):
                print(f"{o:06x}  {d[o:o+16].hex(' ')}")
    elif "--grep" in args:
        pat = bytes.fromhex(args[args.index("--grep") + 1])
        for k, t, sub, d in blocks:
            i = d.find(pat)
            while i >= 0:
                print(f"{k:08x} {NAMES.get(k, '')} +{i:#x} of {len(d):#x}"); i = d.find(pat, i + 1)
    else:
        print(len(blocks), "blocks; file hash", "ok" if hash_ok(raw) else "BAD")
        for k, t, sub, d in blocks:
            if len(d) >= 0x20 or k in NAMES:
                print(f"{k:08x} type {t:2}{'' if sub is None else f'[{sub}]'} {len(d):8}  {NAMES.get(k, '')}")

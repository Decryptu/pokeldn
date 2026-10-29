"""A Switch container (XCI/HFS0 or NSP/PFS0) and its NCAs, read in place: header and section
decryption, a section's PartitionFS (ExeFS), and an update's BKTR RomFS over the base game's.
Header and key rules: docs/switch_re.md "Do not unpack the NSP"; BKTR layouts are hactool's (nca.h,
bktr.c), docs/switch_re.md "Reading a game update's RomFS".
"""

import struct

from Crypto.Cipher import AES
from ldn import load_keys  # noqa: F401  re-exported for tools/switch

from pokeldn.switch.romfs import RomFs

CONTENT_TYPES = {0: "Program", 1: "Meta", 2: "Control", 3: "Manual", 4: "Data", 5: "PublicData"}
FS_TYPES = {0: "RomFS", 1: "PartitionFS"}
HASH_TYPES = {0: "auto", 1: "none", 2: "sha256(pfs0)", 3: "ivfc(romfs)"}
CRYPT_TYPES = {0: "auto", 1: "none", 2: "XTS", 3: "CTR", 4: "BKTR"}
SECTOR = 0x10


def _gf_mul(t):
    n = int.from_bytes(t, "little") << 1
    if n >> 128:
        n = (n ^ 0x87) & ((1 << 128) - 1)
    return n.to_bytes(16, "little")


def xts_decrypt(key, data, sector=0, sector_size=0x200):
    """Nintendo XTS: the tweak is the sector index BIG-endian, not little."""
    data_ecb = AES.new(key[:16], AES.MODE_ECB)
    tweak_ecb = AES.new(key[16:], AES.MODE_ECB)
    out = bytearray()
    for i in range(0, len(data), sector_size):
        tweak = tweak_ecb.encrypt(struct.pack(">QQ", 0, sector + i // sector_size))
        for j in range(i, min(i + sector_size, len(data)), 16):
            block = bytes(a ^ b for a, b in zip(data[j:j + 16], tweak))
            out += bytes(a ^ b for a, b in zip(data_ecb.decrypt(block), tweak))
            tweak = _gf_mul(tweak)
    return bytes(out)


class Container:
    """The file, and the partition trees inside it. Yielded offsets are ABSOLUTE."""

    def __init__(self, path):
        self.fh = open(path, "rb")
        self.path = path

    def read(self, off, size):
        self.fh.seek(off)
        return self.fh.read(size)

    def close(self):
        self.fh.close()

    def partitions(self):
        head = self.read(0, 0x200)
        if head[0x100:0x104] == b"HEAD":
            root = struct.unpack_from("<Q", head, 0x130)[0]
            for name, off, size in self._hfs0(root):
                yield f"rootpt:{name}", off, size
                for sub, soff, ssize in self._hfs0(off):
                    yield f"{name}:{sub}", soff, ssize
        elif head[:4] == b"PFS0":
            yield from self._pfs0(0)
        else:
            raise ValueError(f"{self.path}: not an XCI (HEAD) or NSP (PFS0)")

    def _hfs0(self, base):
        hdr = self.read(base, 0x10)
        if hdr[:4] != b"HFS0":
            return
        count, str_size = struct.unpack_from("<II", hdr, 4)
        table = self.read(base + 0x10, count * 0x40)
        strings = self.read(base + 0x10 + count * 0x40, str_size)
        data = base + 0x10 + count * 0x40 + str_size
        for i in range(count):
            off, size, name_off = struct.unpack_from("<QQI", table, i * 0x40)
            name = strings[name_off:strings.index(b"\0", name_off)].decode()
            yield name, data + off, size

    def _pfs0(self, base):
        hdr = self.read(base, 0x10)
        if hdr[:4] != b"PFS0":
            return
        count, str_size = struct.unpack_from("<II", hdr, 4)
        table = self.read(base + 0x10, count * 0x18)
        strings = self.read(base + 0x10 + count * 0x18, str_size)
        data = base + 0x10 + count * 0x18 + str_size
        for i in range(count):
            off, size, name_off = struct.unpack_from("<QQI", table, i * 0x18)
            name = strings[name_off:strings.index(b"\0", name_off)].decode()
            yield name, data + off, size


class CtrSection:
    """A seekable window onto one AES-128-CTR NCA section, decrypting on read."""

    def __init__(self, container, nca_offset, section, key):
        self.c = container
        self.base = nca_offset + section["offset"]
        self.key = key
        self.ctr_high = section["ctr"]
        self.section = section

    def read(self, offset, size):
        """`offset` is relative to the SECTION; the counter is NCA-relative."""
        if size <= 0:
            return b""
        nca_off = self.section["offset"] + offset
        pad = nca_off % SECTOR
        aligned = nca_off - pad
        raw = self.c.read(self.base - self.section["offset"] + aligned, pad + size)
        ctr = self.ctr_high + struct.pack(">Q", aligned >> 4)
        clear = AES.new(self.key, AES.MODE_CTR, nonce=b"", initial_value=ctr).decrypt(raw)
        return clear[pad:pad + size]


def parse_fs_header(fs):
    """One 0x200 FS header. Offsets per hactool nca.h: 0x2 fs, 0x3 hash, 0x4 crypt."""
    s = {"fs_type": fs[2], "hash_type": fs[3], "crypt": fs[4], "ctr": fs[0x140:0x148][::-1],   # hactool nca.c: the 8 CTR bytes are used REVERSED
         "data_offset": None, "data_size": None}
    sb = fs[0x8:0x140]
    if s["hash_type"] == 3 and sb[:4] == b"IVFC":
        num_levels = struct.unpack_from("<I", sb, 0xC)[0]
        best = None
        for i in range(min(num_levels, 6)):
            off, size, _blk, _r = struct.unpack_from("<QQII", sb, 0x10 + i * 0x18)
            if size:
                best = (off, size)
        if best:
            s["data_offset"], s["data_size"] = best
    elif s["hash_type"] == 2:
        # pfs0_superblock_t: master_hash 0x20, block_size, always_2, hash tbl off/size, pfs0 off/size
        s["data_offset"], s["data_size"] = struct.unpack_from("<QQ", sb, 0x38)
    if s["crypt"] == 4:
        # bktr_superblock_t: the IVFC header (0xE0), 0x18 of padding, then two bktr_header_t
        # {u64 offset, u64 size, "BKTR", u32, u32 num_entries, u32}: relocation, subsection.
        # Both offsets are section-relative; BktrSection reads them.
        for name, at in (("relocation", 0xF8), ("subsection", 0x118)):
            off, size, magic, _v, count, _r = struct.unpack_from("<QQ4sIII", sb, at)
            if magic == b"BKTR":
                s[name] = {"offset": off, "size": size, "entries": count}
    return s


def nca_header(container, off, header_key):
    clear = xts_decrypt(header_key, container.read(off, 0xC00))
    if clear[0x200:0x203] != b"NCA":
        return None
    h = {
        "magic": clear[0x200:0x204].decode(errors="replace"),
        "content_type": clear[0x205],
        "kaek_index": clear[0x207],
        "size": struct.unpack_from("<Q", clear, 0x208)[0],
        "title_id": struct.unpack_from("<Q", clear, 0x210)[0],
        "sdk": tuple(clear[0x21F:0x21B:-1]),
        "rights_id": clear[0x230:0x240],
        "key_area": clear[0x300:0x340],
        "sections": [],
    }
    gen = max(clear[0x206], clear[0x220])
    h["keygen"] = gen - 1 if gen else 0
    for i in range(4):
        start, end = struct.unpack_from("<II", clear, 0x240 + i * 0x10)
        if not end:
            continue
        s = parse_fs_header(clear[0x400 + i * 0x200:0x600 + i * 0x200])
        s.update(index=i, offset=start * 0x200, size=(end - start) * 0x200)
        h["sections"].append(s)
    return h


def section_key(h, keys, tickets=None):
    """The body key: key area slot 2 under key_area_key_application_<keygen>, or the `<rights id>.tik`
    title key (+0x180) under titlekek_<keygen>. docs/switch_re.md."""
    rights = h["rights_id"]
    if rights != bytes(16):
        name = f"titlekek_{h['keygen']:02x}"
        tik = (tickets or {}).get(rights.hex())
        kek = keys.get(name)
        if tik is None or kek is None:
            return None, name if kek is None else f"ticket {rights.hex()}.tik"
        return AES.new(kek, AES.MODE_ECB).decrypt(tik[0x180:0x190]), name
    name = f"key_area_key_application_{h['keygen']:02x}"
    kaek = keys.get(name)
    if kaek is None:
        return None, name
    area = AES.new(kaek, AES.MODE_ECB).decrypt(h["key_area"])
    return area[0x20:0x30], name


BUCKET = 0x4000
RELOC_ENTRY = struct.Struct("<QQI")        # virt_offset, phys_offset, is_patch
SUBSEC_ENTRY = struct.Struct("<QII")       # offset, _, ctr_val


def _buckets(raw, entry):
    """-> (keys, [entries]) for one BKTR block: a header bucket of keys then one bucket per key."""
    _z, num_buckets, _total = struct.unpack_from("<IIQ", raw, 0)
    keys = struct.unpack_from(f"<{num_buckets}Q", raw, 0x10)
    per_bucket = (BUCKET - 0x10) // entry.size
    out = []
    for b in range(num_buckets):
        at = BUCKET * (1 + b)
        _z, count, end = struct.unpack_from("<IIQ", raw, at)
        entries = [entry.unpack_from(raw, at + 0x10 + i * entry.size)
                   for i in range(min(count, per_bucket))]
        out.append((end, entries))
    return keys, out


def _lookup(keys, buckets, offset):
    """hactool bktr.c: the last bucket whose key <= offset, then the last entry whose offset <= offset;
    an entry reaches to the next entry or the bucket's end."""
    b = 0
    for i in range(1, len(keys)):
        if keys[i] > offset:
            break
        b = i
    end, entries = buckets[b]
    e = 0
    for i in range(1, len(entries)):
        if entries[i][0] > offset:
            break
        e = i
    reach = entries[e + 1][0] if e + 1 < len(entries) else end
    return entries[e], reach


class BktrSection:
    """The virtual RomFS section of an update NCA, readable at section-relative offsets."""

    def __init__(self, patch, base):
        self.patch = patch          # CtrSection over the update's BKTR section
        self.base = base            # CtrSection over the base game's RomFS section
        sec = patch.section
        reloc = patch.read(sec["relocation"]["offset"], sec["relocation"]["size"])
        subsec = patch.read(sec["subsection"]["offset"], sec["subsection"]["size"])
        self.reloc = _buckets(reloc, RELOC_ENTRY)
        self.subsec = _buckets(subsec, SUBSEC_ENTRY)
        self.size = struct.unpack_from("<Q", reloc, 8)[0]

    def close(self):
        self.patch.c.close()
        self.base.c.close()

    def read(self, offset, size):
        out = bytearray()
        while size > 0:
            (virt, phys, is_patch), reach = _lookup(*self.reloc, offset)
            n = min(size, reach - offset)
            at = offset - virt + phys
            if is_patch:
                out += self._read_patch(at, n)
            else:
                out += self.base.read(at, n)
            offset += n
            size -= n
        return bytes(out)

    def _read_patch(self, offset, size):
        out = bytearray()
        while size > 0:
            (start, _z, ctr_val), reach = _lookup(*self.subsec, offset)
            n = min(size, reach - offset)
            ctr_high = self.patch.ctr_high[:4] + struct.pack(">I", ctr_val)
            out += self._ctr_read(offset, n, ctr_high)
            offset += n
            size -= n
        return bytes(out)

    def _ctr_read(self, offset, size, ctr_high):
        saved = self.patch.ctr_high
        self.patch.ctr_high = ctr_high
        try:
            return self.patch.read(offset, size)
        finally:
            self.patch.ctr_high = saved


def nca_files(container):
    """-> (name, offset) of every NCA in the container, and the tickets by rights id."""
    entries = list(container.partitions())
    tickets = {name.split(":")[-1][:-4]: container.read(off, size)
               for name, off, size in entries if name.endswith(".tik")}
    return [(name.split(":")[-1], off) for name, off, _ in entries if name.endswith(".nca")], tickets


def program_nca(container_path, keys, want=None, title_id=None, section=None):
    """-> (container, nca offset, header, section key) of the Program NCA: the first whose name starts
    with `want`, whose title is `title_id` and that has a section `section(s)` accepts."""
    c = Container(container_path)
    try:
        return _program_nca(c, container_path, keys, want, title_id, section)
    except BaseException:
        c.close()
        raise


def _program_nca(c, container_path, keys, want, title_id, section):
    ncas, tickets = nca_files(c)
    for base, off in ncas:
        if want and not base.startswith(want):
            continue
        h = nca_header(c, off, keys["header_key"])
        if h is None or CONTENT_TYPES.get(h["content_type"]) != "Program":
            continue
        if title_id is not None and h["title_id"] != title_id:
            continue
        if section is not None and not any(section(s) for s in h["sections"]):
            continue
        key, keyname = section_key(h, keys, tickets)
        if key is None:
            raise ValueError(f"{base}: no {keyname}")
        return c, off, h, key
    raise ValueError(f"{container_path}: no Program NCA"
                     + (f" of title {title_id:016x}" if title_id is not None else ""))


def _bktr(s):
    return s["crypt"] == 4


def _ctr_romfs(s):
    return s["fs_type"] == 0 and s["crypt"] == 3


def open_update_romfs(update_path, base_path, keys, update_nca=None, base_nca=None, title_id=None):
    """-> (BktrSection, RomFs) for the update's virtual RomFS, over the base game's Program NCA of the
    same title (an XCI's update partition holds system titles' Program NCAs too)."""
    uc, uoff, uh, ukey = program_nca(update_path, keys, update_nca, title_id, _bktr)
    try:
        bc, boff, bh, bkey = program_nca(base_path, keys, base_nca, uh["title_id"], _ctr_romfs)
    except BaseException:
        uc.close()
        raise
    usec = next(s for s in uh["sections"] if _bktr(s))
    bsec = next(s for s in bh["sections"] if _ctr_romfs(s))
    virt = BktrSection(CtrSection(uc, uoff, usec, ukey), CtrSection(bc, boff, bsec, bkey))
    return virt, RomFs(virt, usec["data_offset"])


def partition_fs(sec, at):
    """-> {name: (offset, size)} of the PFS0 at `at` in a section, offsets section-relative."""
    hdr = sec.read(at, 0x10)
    if hdr[:4] != b"PFS0":
        raise ValueError(f"no PFS0 at section+{at:#x}: {hdr[:4]!r}")
    count, str_size = struct.unpack_from("<II", hdr, 4)
    table = sec.read(at + 0x10, count * 0x18)
    strings = sec.read(at + 0x10 + count * 0x18, str_size)
    data = at + 0x10 + count * 0x18 + str_size
    out = {}
    for i in range(count):
        foff, fsize, name_off = struct.unpack_from("<QQI", table, i * 0x18)
        out[strings[name_off:strings.index(b"\0", name_off)].decode()] = (data + foff, fsize)
    return out


def exefs(container_path, keys, title_id=None):
    """-> {name: bytes} of the Program NCA's ExeFS (the CTR PartitionFS holding `main`)."""
    def has_exefs(s):
        return s["fs_type"] == 1 and s["crypt"] == 3
    c, off, h, key = program_nca(container_path, keys, None, title_id, has_exefs)
    try:
        for s in h["sections"]:
            if not has_exefs(s):
                continue
            sec = CtrSection(c, off, s, key)
            files = partition_fs(sec, s["data_offset"])
            if "main" in files:
                return {name: sec.read(o, n) for name, (o, n) in files.items()}
    finally:
        c.close()
    raise ValueError(f"{container_path}: no ExeFS with a main module")

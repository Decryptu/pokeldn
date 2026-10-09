"""A whole FireRed/LeafGreen save, the 128 KiB flash image: its two 14-sector slots, which one the
game loads, the sectors a restore writes and the token coding the save payloads use
[decomp:src/save.c, include/save.h; docs/frlg_gift.md, Save backup and restore]."""

from dataclasses import dataclass

from pokeldn.frlg.save import readout
from pokeldn.frlg.save.save_inject import (
    NUM_SECTORS_PER_SLOT, SECTOR_CHECKSUM_OFF, SECTOR_COUNTER_OFF, SECTOR_ID_OFF, SECTOR_SIGNATURE,
    SECTOR_SIGNATURE_OFF, SECTOR_SIZE, SECTORS_COUNT, sector_checksum,
)

SAVE_SIZE = SECTORS_COUNT * SECTOR_SIZE              # 0x20000
EMULATOR_FOOTER = 16                                 # some emulators append a 16-byte RTC footer
SLOT_SECTORS = NUM_SECTORS_PER_SLOT
EXTRA_SECTORS = range(2 * SLOT_SECTORS, SECTORS_COUNT)   # Hall of Fame, Trainer Tower, unused
FOOTER_BYTES = 12                                    # id, checksum, signature, counter at +0xFF4
SECTOR_ID_SAVEBLOCK2 = 0

# Bytes each sector id checksums [sSaveSlotLayout]; read off all twelve cartridges, only id 4 (the end
# of SaveBlock1) differs: 3816 on the Latin builds, 3776 on the Japanese ones.
CHUNK_SIZES = {"latin": (3876, 3968, 3968, 3968, 3816, 3968, 3968, 3968, 3968, 3968, 3968, 3968, 3968, 2000),
               "japanese": (3876, 3968, 3968, 3968, 3776, 3968, 3968, 3968, 3968, 3968, 3968, 3968, 3968, 2000)}


class SaveError(ValueError):
    """Not a FireRed/LeafGreen save this host can read or write."""


def _u16(data, at):
    return int.from_bytes(data[at:at + 2], "little")


def _u32(data, at):
    return int.from_bytes(data[at:at + 4], "little")


def normalize(data):
    """-> the 128 KiB flash image, an emulator's 16-byte footer dropped; SaveError for any other size."""
    data = bytes(data)
    if len(data) == SAVE_SIZE + EMULATOR_FOOTER:
        data = data[:SAVE_SIZE]
    if len(data) != SAVE_SIZE:
        raise SaveError(f"a FireRed or LeafGreen save is 128 KB; this file is {len(data)} bytes")
    return data


def sector(data, n):
    return data[n * SECTOR_SIZE:(n + 1) * SECTOR_SIZE]


def footer(data, n):
    """-> (id, checksum, signature, counter) of physical sector n."""
    at = n * SECTOR_SIZE
    return (_u16(data, at + SECTOR_ID_OFF), _u16(data, at + SECTOR_CHECKSUM_OFF),
            _u32(data, at + SECTOR_SIGNATURE_OFF), _u32(data, at + SECTOR_COUNTER_OFF))


def sector_layouts(data, n):
    """-> the layouts ("latin", "japanese") under which physical sector n is valid: its signature,
    its id below 14, and its checksum over that id's chunk [save.c GetSaveValidStatus]."""
    ident, checksum, signature, _counter = footer(data, n)
    if signature != SECTOR_SIGNATURE or ident >= SLOT_SECTORS:
        return ()
    raw = sector(data, n)
    return tuple(layout for layout, sizes in CHUNK_SIZES.items()
                 if sector_checksum(raw, sizes[ident]) == checksum)


@dataclass(frozen=True)
class Slot:
    index: int
    sound: bool          # all 14 ids present and valid
    counter: int | None  # the last valid sector's counter, as GetSaveValidStatus assigns it
    layouts: tuple       # the layouts every sector of the slot is valid under

    @property
    def first(self):
        return self.index * SLOT_SECTORS


def slot(data, index):
    ids, counter, layouts = set(), None, {"latin", "japanese"}
    for n in range(index * SLOT_SECTORS, (index + 1) * SLOT_SECTORS):
        valid = sector_layouts(data, n)
        if not valid:
            continue
        ids.add(footer(data, n)[0])
        counter = footer(data, n)[3]
        layouts &= set(valid)
    sound = len(ids) == SLOT_SECTORS and bool(layouts)
    return Slot(index, sound, counter, tuple(sorted(layouts)) if sound else ())


def _newer(a, b):
    """The slot the game loads of two sound ones: the higher counter, wrapping as save.c compares."""
    return b if ((b.counter + 1) & 0xFFFFFFFF) > ((a.counter + 1) & 0xFFFFFFFF) else a


@dataclass(frozen=True)
class Summary:
    slots: tuple
    newest: Slot | None

    @property
    def sound(self):
        return self.newest is not None

    @property
    def japanese(self):
        """Only the id-4 checksum can tell, and only when the Latin tail is not zero: see language()."""
        return self.newest is not None and self.newest.layouts == ("japanese",)


def describe(data):
    """-> Summary: each slot's soundness and the one the game would load."""
    data = normalize(data)
    slots = (slot(data, 0), slot(data, 1))
    sound = [s for s in slots if s.sound]
    newest = None
    for candidate in sound:
        newest = candidate if newest is None else _newer(newest, candidate)
    return Summary(slots, newest)


def block(data, ident, summary=None):
    """-> the 3968-byte data of sector `ident` in the slot the game loads."""
    summary = summary or describe(data)
    if not summary.sound:
        raise SaveError("neither of the save's two copies is whole")
    for n in range(summary.newest.first, summary.newest.first + SLOT_SECTORS):
        if footer(data, n)[0] == ident:
            return sector(data, n)[:SECTOR_ID_OFF]
    raise SaveError(f"the loaded copy has no sector {ident}")


def trainer(data):
    """-> {name, gender, tid, sid, hours, minutes} from the loaded copy's SaveBlock2."""
    data = normalize(data)
    summary = describe(data)
    return readout.trainer(block(data, SECTOR_ID_SAVEBLOCK2, summary),
                           language=1 if summary.japanese else None)


SB1_PARTY_COUNT, SB1_PARTY = 0x34, 0x38               # [include/global.h:772]
STORAGE_BOXES = 4                                     # PokemonStorage: currentBox, then 420 BoxPokemon
MON_OTID, MON_LANGUAGE = 4, 0x12                      # unencrypted header [include/pokemon.h]
LANGUAGE_JAPANESE = 1


def language(data):
    """-> the language id the player's own Pokemon carry (OT ID equal to the trainer's), the
    cartridge's, or None with none to read. The Japanese and Latin layouts differ only in the length of
    SaveBlock1, which the zero-filled sectors hide [save.c HandleWriteSector]."""
    data = normalize(data)
    summary = describe(data)
    if not summary.sound:
        return None
    trainer_id = block(data, SECTOR_ID_SAVEBLOCK2, summary)[readout.TRAINER_ID_OFFSET:][:4]
    first = block(data, 1, summary)
    records = [first[SB1_PARTY + i * 100:SB1_PARTY + (i + 1) * 100] for i in range(min(first[SB1_PARTY_COUNT], 6))]
    layout = CHUNK_SIZES[summary.newest.layouts[0]]
    storage = b"".join(block(data, ident, summary)[:layout[ident]] for ident in range(5, SLOT_SECTORS))
    records += [storage[STORAGE_BOXES + i * 80:STORAGE_BOXES + (i + 1) * 80] for i in range(420)]
    votes = {}
    for record in records:
        if len(record) >= 80 and record[MON_OTID:MON_OTID + 4] == trainer_id and record[:4] != b"\0\0\0\0":
            votes[record[MON_LANGUAGE]] = votes.get(record[MON_LANGUAGE], 0) + 1
    return max(votes, key=votes.get) if votes else None


def check_restorable(data, *, japanese):
    """SaveError unless `data` holds a whole copy for a cartridge of that layout."""
    summary = describe(data)
    if not summary.sound:
        raise SaveError("the save has no whole copy of a game in it")
    spoken = language(data)
    if spoken is not None and (spoken == LANGUAGE_JAPANESE) != bool(japanese) or (
            ("japanese" if japanese else "latin") not in summary.newest.layouts):
        raise SaveError("this save is from a Latin-alphabet cartridge; the console runs a Japanese one"
                        if japanese else
                        "this save is from a Japanese cartridge; the console runs another language")
    return summary


def chip_newest(footers):
    """-> (slot, counter) of the chip's newest copy from the 28 footers save-restore.s reads, or
    None. A slot counts when its 14 sectors carry the signature and distinct ids."""
    best = None
    for index in (0, 1):
        ids, counter = set(), None
        for n in range(index * SLOT_SECTORS, (index + 1) * SLOT_SECTORS):
            at = n * FOOTER_BYTES
            if _u32(footers, at + 4) != SECTOR_SIGNATURE:
                break
            ids.add(_u16(footers, at))
            counter = _u32(footers, at + 8)
        else:
            if len(ids) == SLOT_SECTORS and (
                    best is None or ((counter + 1) & 0xFFFFFFFF) > ((best[1] + 1) & 0xFFFFFFFF)):
                best = (index, counter)
    return best


def sectors_to_write(data, footers):
    """-> [(physical sector, 4096 bytes)] in write order.

    The file's loaded copy goes in the slot beside the chip's newest, its counter one past that copy's,
    so the game's next load takes it [save.c:174]; then the four sectors past the slots. The game takes
    a slot whose 14 ids all pass, whatever their counters, so a half-written slot could load: the old
    copy's id 0 there is erased first and the new id 0 written last."""
    data = normalize(data)
    summary = describe(data)
    if not summary.sound:
        raise SaveError("the save has no whole copy of a game in it")
    newest = chip_newest(footers)
    counter = 0 if newest is None else (newest[1] + 1) & 0xFFFFFFFF
    target = counter % 2
    copy = []
    for i in range(SLOT_SECTORS):
        raw = bytearray(sector(data, summary.newest.first + i))
        raw[SECTOR_COUNTER_OFF:SECTOR_COUNTER_OFF + 4] = counter.to_bytes(4, "little")
        copy.append((target * SLOT_SECTORS + i, bytes(raw)))
    out = []
    for i in range(SLOT_SECTORS):
        at = (target * SLOT_SECTORS + i) * FOOTER_BYTES
        if _u32(footers, at + 4) == SECTOR_SIGNATURE and _u16(footers, at) == 0:
            out.append((target * SLOT_SECTORS + i, b"\xff" * SECTOR_SIZE))
    out += [s for s in copy if _u16(s[1], SECTOR_ID_OFF) != 0]
    out += [s for s in copy if _u16(s[1], SECTOR_ID_OFF) == 0]
    out += [(n, sector(data, n)) for n in EXTRA_SECTORS]
    return out


# The token coding of save-backup.s and save-restore.s: n < 0x80 then n + 1 literal bytes; n >= 0x80
# then one byte repeated n - 0x80 + 3 times.
MAX_RUN = 130
MAX_LITERAL = 128


def deflate(data):
    """-> [(token bytes, how many bytes it stands for)], runs of three or more taken whole."""
    data = bytes(data)
    tokens, i = [], 0
    while i < len(data):
        run = 1
        while i + run < len(data) and run < MAX_RUN and data[i + run] == data[i]:
            run += 1
        if run >= 3:
            tokens.append((bytes((0x80 + run - 3, data[i])), run))
            i += run
            continue
        start = i
        while i < len(data) and i - start < MAX_LITERAL:
            if i > start and i + 2 < len(data) and data[i + 1] == data[i] == data[i + 2]:
                break
            i += 1
        tokens.append((bytes((i - start - 1,)) + data[start:i], i - start))
    return tokens


def inflate(tokens, out, at):
    """Write one message's tokens into bytearray `out` from `at`; -> where the next one goes on."""
    i = 0
    while i < len(tokens):
        n = tokens[i]
        i += 1
        length = n + 1 if n < 0x80 else n - 0x80 + 3
        need = length if n < 0x80 else 1
        if at + length > len(out) or i + need > len(tokens):
            raise SaveError("the console sent a save block that does not fit")
        if n < 0x80:
            out[at:at + length] = tokens[i:i + length]
            i += length
        else:
            out[at:at + length] = bytes((tokens[i],)) * length
            i += 1
        at += length
    return at

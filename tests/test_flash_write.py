"""flash-write: composing a sector on the console and writing it with swi 0x48.

The expectations here are the measurements from the FR emulator, not a reading of the wrapper:
a rejected call writes nothing and returns no status, an accepted one copies 0x1000 bytes and
touches nothing else, and swi 0x56 voids the destination's signature and aborts outright when the
destination is rejected [docs/frlg_rom.md, the Sloop syscall boundary].
"""

import pytest

from pokeldn.frlg.rom import buffer_script as bs

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

ERASED = b"\xFF" * bs.FLASH_SECTOR_SIZE


def run(code):
    machine = bs._Machine(code)
    result = machine.call()
    flash = bytes(machine.uc.mem_read(bs.FLASH_BASE, bs.FLASH_SIZE))
    return result, machine.flash_writes, flash


def sector(flash, index):
    start = index * bs.FLASH_SECTOR_SIZE
    return flash[start:start + bs.FLASH_SECTOR_SIZE]


def test_the_console_composes_the_sector_and_the_syscall_writes_it():
    result, writes, flash = run(bs.build_flash_write(30))
    assert result.returned == 1                      # one frame, no hang in the gift menu
    assert sector(flash, 30) == bs.flash_write_source()
    assert [(w[1], w[3]) for w in writes] == [(30, True)]


def test_it_writes_only_the_sector_it_was_asked_for():
    _, _, flash = run(bs.build_flash_write(30))
    assert sector(flash, 29) == ERASED and sector(flash, 31) == ERASED


def test_the_status_proves_the_fill_reached_the_end_and_survived_the_write():
    result, _, _ = run(bs.build_flash_write(30, fill_base=0x11110000, fill_step=1))
    assert result.param == 0x111103FF                # fill_base + (words - 1)


def test_a_rejected_sector_writes_nothing_and_reports_nothing():
    # Step 1's shape, past the builder's guard: 0x800 folds outside flash.
    code = bytearray(bs.build_flash_write(30))
    code[bs.FLASH_WRITE_SECTOR_OFFSET:bs.FLASH_WRITE_SECTOR_OFFSET + 4] = (0x800).to_bytes(4, "little")
    result, writes, flash = run(bytes(code))
    assert flash == b"\xFF" * bs.FLASH_SIZE
    assert result.returned == 1                      # it returns; the refusal is silent
    assert writes[0][3] is False


def test_replace_sector_voids_the_signature_it_just_wrote():
    _, _, flash = run(bs.build_flash_write(30, number=bs.SWI_REPLACE_SECTOR, unsafe=True))
    written = sector(flash, 30)
    assert written[:0xFF8] == bs.flash_write_source()[:0xFF8]
    assert written[0xFF8] == 0xFF


def test_replace_sector_with_a_rejected_destination_aborts():
    code = bytearray(bs.build_flash_write(30, number=bs.SWI_REPLACE_SECTOR, unsafe=True))
    code[bs.FLASH_WRITE_SECTOR_OFFSET:bs.FLASH_WRITE_SECTOR_OFFSET + 4] = (0x800).to_bytes(4, "little")
    with pytest.raises(bs.BufferScriptError, match="aborts"):
        run(bytes(code))


def test_a_save_band_sector_needs_the_override():
    with pytest.raises(bs.BufferScriptError, match="save band"):
        bs.build_flash_write(12)
    assert bs.build_flash_write(12, unsafe=True)     # meant, and allowed


def test_the_source_may_not_overlap_the_payloads_own_image():
    with pytest.raises(bs.BufferScriptError, match="overlaps"):
        bs.build_flash_write(30, source=bs.GDECOMPRESSION_BUFFER)


def test_replace_sector_needs_the_override_too():
    with pytest.raises(bs.BufferScriptError, match="0x56"):
        bs.build_flash_write(30, number=bs.SWI_REPLACE_SECTOR)


# --- composing a well-formed save sector ---------------------------------------------------------

def test_the_console_computes_the_games_own_checksum():
    code = bs.build_flash_write(30, footer=True, sector_id=1, counter=99, fill_base=0x41310000)
    result, _, flash = run(code)
    reference = bs.flash_write_source(fill_base=0x41310000, footer=True, sector_id=1, counter=99)
    # *param carries the chosen sector in its high half and the checksum in its low half, so one
    # word says both where it went and whether the arithmetic agreed.
    assert result.param & 0xFFFF == bs.sector_checksum(reference)
    assert result.param >> 16 == 30
    assert sector(flash, 30) == reference


def test_a_composed_sector_carries_a_well_formed_footer():
    _, _, flash = run(bs.build_flash_write(30, footer=True, sector_id=4, counter=0x1234))
    written = sector(flash, 30)
    assert int.from_bytes(written[0xFF4:0xFF6], "little") == 4
    assert int.from_bytes(written[0xFF8:0xFFC], "little") == bs.SECTOR_SIGNATURE
    assert int.from_bytes(written[0xFFC:0x1000], "little") == 0x1234
    # The checksum in the footer recomputes over the data, which is what the loader checks.
    assert int.from_bytes(written[0xFF6:0xFF8], "little") == bs.sector_checksum(written)


def test_everything_between_the_pattern_and_the_footer_is_zeroed():
    _, _, flash = run(bs.build_flash_write(30, footer=True, words=4, sector_id=0))
    written = sector(flash, 30)
    assert written[16:0xFF4] == b"\x00" * (0xFF4 - 16)


def test_the_checksum_matches_the_real_saves_on_disk():
    """The reference is the game's, so it must reproduce a save this project did not compute."""
    import pathlib
    sav = pathlib.Path("scratchpad/hgfs/Switch/frlg_bridge/dumps/055_backup_pre_step2.sav")
    if not sav.exists():
        pytest.skip("no reference save on this machine")
    blob = sav.read_bytes()
    checked = 0
    for index in range(len(blob) // bs.FLASH_SECTOR_SIZE):
        sec = blob[index * bs.FLASH_SECTOR_SIZE:(index + 1) * bs.FLASH_SECTOR_SIZE]
        if int.from_bytes(sec[0xFF8:0xFFC], "little") != bs.SECTOR_SIGNATURE:
            continue
        assert bs.sector_checksum(sec) == int.from_bytes(sec[0xFF6:0xFF8], "little")
        checked += 1
    assert checked == 28


def test_an_id_without_a_footer_is_refused():
    with pytest.raises(bs.BufferScriptError, match="footer"):
        bs.build_flash_write(30, sector_id=3)


# --- deriving the position from the game's own save globals --------------------------------------

def globals_at(lws, counter):
    return {bs.GLASTWRITTENSECTOR: int(lws).to_bytes(2, "little"),
            bs.GSAVECOUNTER: int(counter).to_bytes(4, "little")}


def rotation(lws, counter, sector_id):
    """The game's own [decomp:src/save.c:174]; the payload must agree with this, not with a table."""
    return ((lws + sector_id) % bs.SECTORS_PER_BAND) + bs.SECTORS_PER_BAND * (counter % 2)


@pytest.mark.parametrize("lws,counter,sector_id", [
    (3, 129, 13), (3, 129, 0), (2, 128, 0), (0, 130, 7), (13, 131, 13), (13, 130, 1),
])
def test_the_console_derives_the_sector_the_id_actually_occupies(lws, counter, sector_id):
    code = bs.build_flash_write(0, footer=True, sector_id=sector_id, derive=True, unsafe=True)
    machine = bs._Machine(code, memory=globals_at(lws, counter))
    result = machine.call()
    want = rotation(lws, counter, sector_id)
    assert result.param >> 16 == want                     # reported back, so a miss is visible
    assert [w[1] for w in machine.flash_writes] == [want]  # and that is where the syscall went


def test_a_derived_sector_carries_the_live_counter_unchanged():
    code = bs.build_flash_write(0, footer=True, sector_id=13, derive=True, unsafe=True)
    machine = bs._Machine(code, memory=globals_at(3, 129))
    machine.call()
    flash = bytes(machine.uc.mem_read(bs.FLASH_BASE, bs.FLASH_SIZE))
    written = sector(flash, rotation(3, 129, 13))
    assert int.from_bytes(written[0xFFC:0x1000], "little") == 129     # its own band, not 130


def test_a_counter_bias_outranks_by_exactly_that_much():
    code = bs.build_flash_write(0, footer=True, sector_id=13, derive=True, unsafe=True,
                                counter_bias=2)
    machine = bs._Machine(code, memory=globals_at(3, 129))
    machine.call()
    flash = bytes(machine.uc.mem_read(bs.FLASH_BASE, bs.FLASH_SIZE))
    assert int.from_bytes(sector(flash, rotation(3, 129, 13))[0xFFC:0x1000], "little") == 131


def test_the_checksum_is_unaffected_by_a_runtime_counter():
    """The counter sits at +0xFFC, outside the summed data area, so it stays build-time knowable."""
    a = bs._Machine(bs.build_flash_write(0, footer=True, sector_id=13, derive=True, unsafe=True),
                    memory=globals_at(3, 129)).call()
    b = bs._Machine(bs.build_flash_write(0, footer=True, sector_id=13, derive=True, unsafe=True),
                    memory=globals_at(7, 200)).call()
    assert a.param & 0xFFFF == b.param & 0xFFFF
    assert a.param >> 16 != b.param >> 16


def test_a_derived_write_must_be_meant():
    with pytest.raises(bs.BufferScriptError, match="unsafe"):
        bs.build_flash_write(0, footer=True, sector_id=13, derive=True)
    with pytest.raises(bs.BufferScriptError, match="counter"):
        bs.build_flash_write(0, footer=True, sector_id=13, counter=5, derive=True, unsafe=True)
    with pytest.raises(bs.BufferScriptError, match="composed sector"):
        bs.build_flash_write(30, derive=True, unsafe=True)


# --- the chunk size the game actually checksums ---------------------------------------------------
# Ids 0, 4 and 13 carry less than a full data area. In a sector the GAME wrote, everything past the
# chunk is zero, so summing the full 3968 gives the same answer and the distinction is invisible
# against any real save. A composed sector that fills the whole data area breaks that equivalence,
# and the game, which sums the chunk, rejects it. This is the case no real save can exercise.

def test_a_composed_sector_is_checksummed_the_way_the_game_will_checksum_it():
    for sector_id in sorted(bs.SECTOR_CHUNK_SIZES):
        built = bs.flash_write_source(footer=True, sector_id=sector_id, counter=1)
        size = bs.sector_chunk_size(sector_id)
        stored = int.from_bytes(built[0xFF6:0xFF8], "little")
        assert stored == bs.sector_checksum(built, size), sector_id      # the game's rule
        assert stored == bs.sector_checksum(built), sector_id            # and the shortcut agrees


def test_a_composed_sector_leaves_its_tail_zero_like_a_real_one():
    for sector_id in (0, 4, 13):
        built = bs.flash_write_source(footer=True, sector_id=sector_id, counter=1)
        size = bs.sector_chunk_size(sector_id)
        assert built[size:bs.SECTOR_DATA_SIZE] == b"\x00" * (bs.SECTOR_DATA_SIZE - size)


def test_filling_past_the_chunk_would_be_rejected_by_the_game():
    """The regression: this is what a full-fill sector for a short id looks like to the loader."""
    full = bs.flash_write_source(words=bs.SECTOR_DATA_WORDS, footer=True, sector_id=13, counter=1)
    # Its stored checksum is the one computed over the chunk, as the game computes it...
    stored = int.from_bytes(full[0xFF6:0xFF8], "little")
    assert stored == bs.sector_checksum(full, bs.sector_chunk_size(13))
    # ...but the data past the chunk is not zero, so the full-area sum no longer agrees. A payload
    # that stored THAT value would be refused by the game.
    assert bs.sector_checksum(full) != stored


def test_the_console_composes_the_short_chunk_too():
    code = bs.build_flash_write(30, footer=True, sector_id=13, counter=129, fill_base=0x41320000)
    result, _, flash = run(code)
    reference = bs.flash_write_source(fill_base=0x41320000, footer=True, sector_id=13, counter=129)
    assert sector(flash, 30) == reference
    assert result.param & 0xFFFF == bs.sector_checksum(reference, bs.sector_chunk_size(13))


def test_the_chunk_sizes_are_the_ones_in_the_cartridge():
    """sSaveSlotLayout is const data in the ROM; if it is on disk, read it rather than trust me."""
    import pathlib
    import struct
    rom = pathlib.Path("scratchpad/FireRed_f.gba")
    if not rom.exists():
        pytest.skip("no cartridge image on this machine")
    blob = rom.read_bytes()
    at = bs.SAVE_SLOT_LAYOUT_ADDRESS - 0x08000000
    table = struct.unpack_from("<28H", blob, at)
    assert [table[i * 2 + 1] for i in range(14)] == \
        [bs.SECTOR_CHUNK_SIZES[i] for i in range(14)]
    # The offsets are the SAVEBLOCK_CHUNK pattern: one chunk, then four, then nine.
    assert [table[i * 2] for i in range(14)] == \
        [0] + [n * bs.SECTOR_DATA_SIZE for n in range(4)] + [n * bs.SECTOR_DATA_SIZE for n in range(9)]


# --- aiming at a band position, and deriving the id from it ---------------------------------------
# GetSaveValidStatus assigns the slot's counter on every valid sector in physical order, so the LAST
# valid sector's counter is the slot's. A sector meant to change which slot loads must sit at
# position 13, and the id that belongs there depends on gLastWrittenSector, which is only known on
# the console.

@pytest.mark.parametrize("lws,counter", [(3, 131), (0, 130), (13, 129), (7, 200), (1, 4)])
def test_the_console_derives_the_id_from_the_position(lws, counter):
    code = bs.build_flash_write(0, footer=True, derive=True, unsafe=True,
                                position=bs.COUNTER_BEARING_POSITION, counter_bias=2)
    machine = bs._Machine(code, memory=globals_at(lws, counter))
    result = machine.call()
    want_phys = bs.COUNTER_BEARING_POSITION + bs.SECTORS_PER_BAND * (counter % 2)
    want_id = (bs.COUNTER_BEARING_POSITION - lws) % bs.SECTORS_PER_BAND
    assert result.param >> 16 == want_phys
    flash = bytes(machine.uc.mem_read(bs.FLASH_BASE, bs.FLASH_SIZE))
    written = sector(flash, want_phys)
    assert int.from_bytes(written[0xFF4:0xFF6], "little") == want_id
    assert int.from_bytes(written[0xFFC:0x1000], "little") == counter + 2
    # Valid under the id that actually landed there, which is the one the loader will use.
    assert int.from_bytes(written[0xFF6:0xFF8], "little") == \
        bs.sector_checksum(written, bs.sector_chunk_size(want_id))


def test_a_position_aimed_sector_is_valid_under_every_id():
    """The id is only decided on the console, so the sector must checksum under any of them."""
    built = bs.flash_write_source(footer=True, sector_id=0, counter=1,
                                  position=bs.COUNTER_BEARING_POSITION)
    stored = int.from_bytes(built[0xFF6:0xFF8], "little")
    assert {bs.sector_checksum(built, bs.sector_chunk_size(i)) for i in range(14)} == {stored}
    assert built[bs.SECTOR_CHUNK_MIN:bs.SECTOR_DATA_SIZE] == \
        b"\x00" * (bs.SECTOR_DATA_SIZE - bs.SECTOR_CHUNK_MIN)


def test_the_counter_lands_one_above_the_band_the_session_save_will_write():
    """Our band is gSaveCounter % 2, the save's is (gSaveCounter + 1) % 2: always opposite."""
    for counter in (129, 130, 131, 200):
        code = bs.build_flash_write(0, footer=True, derive=True, unsafe=True,
                                    position=bs.COUNTER_BEARING_POSITION, counter_bias=2)
        machine = bs._Machine(code, memory=globals_at(3, counter))
        ours = machine.call().param >> 16
        session_band = bs.SECTORS_PER_BAND * ((counter + 1) % 2)
        assert not session_band <= ours < session_band + bs.SECTORS_PER_BAND


def test_a_position_needs_the_derivation_and_refuses_an_explicit_id():
    with pytest.raises(bs.BufferScriptError, match="derive"):
        bs.build_flash_write(0, footer=True, position=13, unsafe=True)
    with pytest.raises(bs.BufferScriptError, match="ignored"):
        bs.build_flash_write(0, footer=True, derive=True, unsafe=True, position=13, sector_id=5)

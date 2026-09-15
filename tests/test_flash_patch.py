"""flash-patch: read a save sector out of flash, change one field, write it back.

The point of reading rather than composing: a sector built from a live save block is not what the
game's save routine writes, because the routine serializes at save time. Two fields have already
been lost that way, the encryption key and the saved map view. Here nothing is rebuilt, so the test
that matters is that NOTHING outside the patch moves.
"""

import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.text import charmap

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

LWS, COUNTER = 3, 135


def band(lws=LWS, counter=COUNTER, name="ASH"):
    """A flash image whose two sectors of interest were written by a plausible real save."""
    flash = bytearray(b"\xFF" * bs.FLASH_SIZE)
    places = {}
    # The target id, and whichever id the rotation puts at position 13 this generation. They are the
    # same sector when lws is 13, which the payload handles by re-reading what it just wrote.
    at_thirteen = (13 - lws) % 14
    for sector_id, fill in ((0, 0x11110000), (at_thirteen, 0x22220000)):
        phys = ((lws + sector_id) % 14) + 14 * (counter % 2)
        chunk = bs.sector_chunk_size(sector_id)
        sec = bytearray(bs.FLASH_SECTOR_SIZE)
        for i in range(chunk // 4):
            sec[i * 4:i * 4 + 4] = ((fill + i) & 0xFFFFFFFF).to_bytes(4, "little")
        if sector_id == 0:
            sec[0:8] = charmap.encode(name, width=8)
        sec[0xFF4:0xFF6] = sector_id.to_bytes(2, "little")
        sec[0xFF6:0xFF8] = bs.sector_checksum(sec, chunk).to_bytes(2, "little")
        sec[0xFF8:0xFFC] = bs.SECTOR_SIGNATURE.to_bytes(4, "little")
        sec[0xFFC:0x1000] = counter.to_bytes(4, "little")
        flash[phys * bs.FLASH_SECTOR_SIZE:(phys + 1) * bs.FLASH_SECTOR_SIZE] = sec
        places[sector_id] = phys
    places["counter_bearer"] = places[at_thirteen]
    return bytes(flash), places


def run(code, flash, lws=LWS, counter=COUNTER):
    machine = bs._Machine(code, memory={
        bs.GLASTWRITTENSECTOR: int(lws).to_bytes(2, "little"),
        bs.GSAVECOUNTER: int(counter).to_bytes(4, "little"),
        bs.FLASH_BASE: flash})
    result = machine.call()
    after = bytes(machine.uc.mem_read(bs.FLASH_BASE, bs.FLASH_SIZE))
    return result, machine, after


def sector(image, phys):
    return image[phys * bs.FLASH_SECTOR_SIZE:(phys + 1) * bs.FLASH_SECTOR_SIZE]


def patched(name="POKELDN"):
    return bs.build_flash_patch(0, 0x00, charmap.encode(name, width=8), unsafe=True)


def test_nothing_outside_the_patch_moves():
    flash, places = band()
    result, _, after = run(patched(), flash)
    before, now = sector(flash, places[0]), sector(after, places[0])
    moved = [i for i in range(bs.FLASH_SECTOR_SIZE) if before[i] != now[i]]
    # the name bytes that differ, the checksum, and the counter. Nothing else in 4096 bytes.
    assert moved == [0, 1, 2, 3, 4, 5, 6, 0xFF6, 0xFF7, 0xFFC]
    assert charmap.decode(now[0:8]) == "POKELDN"
    assert result.returned == 1


def test_the_patched_sector_is_still_valid_by_the_games_rule():
    flash, places = band()
    _, _, after = run(patched(), flash)
    now = sector(after, places[0])
    assert int.from_bytes(now[0xFF6:0xFF8], "little") == \
        bs.sector_checksum(now, bs.sector_chunk_size(0))
    assert int.from_bytes(now[0xFF8:0xFFC], "little") == bs.SECTOR_SIGNATURE


def test_the_counter_bearer_changes_only_its_counter():
    """+0xFFC is outside the summed data area, so it needs no checksum work at all."""
    flash, places = band()
    _, _, after = run(patched(), flash)
    before, now = sector(flash, places['counter_bearer']), sector(after, places['counter_bearer'])
    assert [i for i in range(bs.FLASH_SECTOR_SIZE) if before[i] != now[i]] == [0xFFC]
    assert int.from_bytes(now[0xFFC:0x1000], "little") == COUNTER + 2
    assert int.from_bytes(now[0xFF6:0xFF8], "little") == \
        bs.sector_checksum(now, bs.sector_chunk_size((13 - LWS) % 14))


def test_both_sectors_carry_the_winning_counter():
    flash, places = band()
    _, _, after = run(patched(), flash)
    for where in (places[0], places["counter_bearer"]):
        assert int.from_bytes(sector(after, where)[0xFFC:0x1000], "little") == COUNTER + 2


def test_it_reads_and_writes_exactly_the_two_sectors_it_derived():
    flash, places = band()
    _, machine, _ = run(patched(), flash)
    assert [r[0] for r in machine.flash_reads] == [places[0], places['counter_bearer']]
    assert [(w[1], w[3]) for w in machine.flash_writes] == \
        [(places[0], True), (places['counter_bearer'], True)]


@pytest.mark.parametrize("lws,counter", [(3, 135), (0, 134), (13, 129), (7, 200)])
def test_the_placement_follows_the_live_globals(lws, counter):
    flash, places = band(lws, counter)
    result, _, _ = run(patched(), flash, lws, counter)
    assert result.param >> 24 == places[0]
    assert (result.param >> 16) & 0xFF == 13 + 14 * (counter % 2)


def test_the_status_witness_is_a_live_value_not_a_constant():
    """It reports the counter sector B already held, which a payload that read nothing could not
    invent; a constant like the signature could be produced without reading anything."""
    for counter in (129, 131, 137):
        flash, _ = band(LWS, counter)
        result, _, _ = run(patched(), flash, LWS, counter)
        assert result.param & 0xFFFF == counter


def test_a_sector_without_a_signature_is_reported_rather_than_written_blind():
    flash = bytearray(band()[0])
    phys = ((LWS + 0) % 14) + 14 * (COUNTER % 2)
    flash[phys * bs.FLASH_SECTOR_SIZE + 0xFF8:phys * bs.FLASH_SECTOR_SIZE + 0xFFC] = b"\x00" * 4
    result, _, _ = run(patched(), bytes(flash))
    assert result.param & 0xFFF00000 == bs.FLASH_PATCH_BAD_MARK


def test_a_patch_past_the_ids_chunk_is_refused():
    with pytest.raises(bs.BufferScriptError, match="chunk"):
        bs.build_flash_patch(0, bs.sector_chunk_size(0) - 2, b"\x01\x02\x03\x04", unsafe=True)


def test_editing_a_live_sector_must_be_meant():
    with pytest.raises(bs.BufferScriptError, match="unsafe"):
        bs.build_flash_patch(0, 0, b"\x01")

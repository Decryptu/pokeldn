"""flash-read: select the bank, byte-copy the flash window into EWRAM, send the copy.

Two things are tested separately because they fail differently. The bank arithmetic is arithmetic
and is checked against the decomp's own formula; the payload's mechanics are checked by running it.
Pointing the send at flash itself is not tested because it does not work: measured at two addresses
and two lengths, the console sent content belonging to neither.
"""

import pytest

from pokeldn.frlg.rom import buffer_script as bs

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")


# --- the bank arithmetic -------------------------------------------------------------------------

@pytest.mark.parametrize("sector", range(32))
def test_the_window_address_is_the_games_own(sector):
    """[decomp:src/agb_flash.c ReadFlash] SwitchFlashBank(n / 16) then n % 16."""
    bank, window = bs.flash_window_address(sector)
    assert bank == sector // 16
    assert window == bs.FLASH_WINDOW_BASE + (sector % 16) * bs.FLASH_SECTOR_SIZE
    assert bs.FLASH_WINDOW_BASE <= window < bs.FLASH_WINDOW_BASE + bs.FLASH_WINDOW_SIZE


def test_the_far_bank_does_not_get_an_address_above_the_window():
    """The trap: 0x0E01E000 for sector 30 aliases to 0x0E00E000 and returns sector 14 instead."""
    bank, window = bs.flash_window_address(30)
    assert (bank, window) == (1, 0x0E00E000)
    naive = bs.FLASH_BASE + 30 * bs.FLASH_SECTOR_SIZE
    assert naive == 0x0E01E000
    assert bs.FLASH_WINDOW_BASE | (naive & 0xFFFF) == window       # it aliases onto the same place
    assert bs.flash_window_address(14)[1] == window                # which is sector 14 in bank 0


def test_a_read_may_not_run_off_the_end_of_the_window():
    with pytest.raises(bs.BufferScriptError, match="window"):
        bs.build_flash_read(31, offset=0xF00, length=512)


# --- the payload ---------------------------------------------------------------------------------

def test_it_copies_the_window_into_the_scratch_and_sends_the_copy():
    code = bs.build_flash_read(30, length=252)
    _, window = bs.flash_window_address(30)
    # The engine maps flash flat, so lay the bytes where the payload will read them.
    marker = bytes((0x41 + (i % 7)) for i in range(252))
    # The chip is addressed linearly; the payload reaches it through bank 1's window.
    flash = bytearray(b"\x00" * bs.FLASH_SIZE)
    flash[30 * bs.FLASH_SECTOR_SIZE:30 * bs.FLASH_SECTOR_SIZE + 252] = marker
    machine = bs._Machine(code, memory={bs.FLASH_BASE: bytes(flash)})
    result = machine.call()
    assert result.returned == 1
    scratch = bs.FLASH_WRITE_SCRATCH
    assert bytes(machine.uc.mem_read(scratch, 252)) == marker      # the CPU copy landed
    assert result.client.send_buffer == scratch                    # and the send points at EWRAM
    assert result.client.send_size == 252
    assert result.pending_send == marker                           # which is what goes out


def test_the_send_is_never_pointed_at_flash():
    code = bs.build_flash_read(30, length=252)
    result = bs._Machine(code).call()
    assert not (bs.FLASH_BASE <= result.client.send_buffer
                < bs.FLASH_BASE + bs.FLASH_SIZE)


def test_the_bank_select_writes_the_games_command_sequence():
    """0xAA to 0x5555, 0x55 to 0x2AAA, 0xB0 to 0x5555, then the bank to 0x0000."""
    code = bs.build_flash_read(30, length=16)
    machine = bs._Machine(code)
    machine.call()
    assert machine.flash_bank == 1                                  # sector 30 is in the far bank
    machine0 = bs._Machine(bs.build_flash_read(14, length=16))       # sector 14 is in bank 0
    machine0.call()
    assert machine0.flash_bank == 0


# --- the config path, which is the one the host actually uses -------------------------------------

def test_config_returns_a_patched_image_not_the_raw_payload():
    """The failure this guards cost a console run and was blamed on the ROM function it calls.

    A build dispatch placed in __post_init__ instead of build_code returns early during validation
    and build_code then falls through to `payload(name)` - the UNPATCHED image, every operand zero.
    For flash-patch that meant a ReadFlash pointer of 0 and a `bx` to 0x00000000, which hung the
    console; the payload builder was correct and the tests that called it directly all passed.
    """
    from pokeldn import config as configmod
    from pokeldn.frlg.text import charmap

    cases = (
        dict(script=bs.FLASH_READ, flash_sector=30, dump_size=252),
        dict(script=bs.FLASH_PATCH, flash_id=0, flash_patch_offset=0,
             flash_patch_data=charmap.encode("POKELDN", width=8), write_unsafe=True),
        dict(script=bs.FLASH_WRITE, flash_sector=30, flash_footer=True),
    )
    for kwargs in cases:
        name = kwargs["script"]
        built = configmod.BufferScriptPayload(**kwargs).build_code()
        assert built != bs.payload(name), f"{name}: config handed back the unpatched image"
        assert len(built) == len(bs.payload(name)), name


def test_no_build_dispatch_hides_in_post_init():
    """The structural version of the same bug: __post_init__ validates, build_code builds."""
    import inspect
    from pokeldn import config as configmod
    source = inspect.getsource(configmod.BufferScriptPayload.__post_init__)
    assert "return buffer_script.build_" not in source, \
        "a build dispatch in __post_init__ returns early and skips the rest of validation"

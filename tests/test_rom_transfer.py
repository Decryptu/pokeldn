"""The ROM transfer, whole stack: our Mystery Gift host against the scripted console, whose ROM copy
outlives the session and whose asm/rom-transfer.s runs under unicorn [docs/rse_switch_build.md,
Delivery without Atmosphere]."""

import random

import pytest

from pokeldn.frlg.gift import rom_transfer
from pokeldn.frlg.rom import buffer_script, builds
from test_save_transfer import ROMS, drive, session

pytestmark = pytest.mark.skipif(not buffer_script.emulation_available(), reason="needs unicorn")

LIVE = {0, 5, 40, 60}           # 60 is past the new image: it becomes 0xFF and is never staged
SIO32ID = 0x08010000            # where the test images keep the scripted console's (BPRF) librfu
CARTRIDGES = dict(builds.SIO32ID)


@pytest.fixture(autouse=True)
def small_librfu(monkeypatch):
    monkeypatch.setattr(builds, "SIO32ID", {**builds.SIO32ID, "BPRF": SIO32ID})


def image(seed, kb, side):
    """Runs and noise, as a ROM has, ending short of a block, with librfu's patch sites as the
    cartridge (side 1) or the ROM copy (side 2) holds them."""
    rng, data = random.Random(seed), bytearray()
    while len(data) < kb * 1024:
        data += rng.choice((rng.randbytes(rng.randrange(1, 300)), bytes([rng.randrange(256)]) * rng.randrange(3, 400)))
    data = data[:kb * 1024 - 7]
    for at, *sides in builds.WRAPPER_PATCHES:
        at += SIO32ID - 0x08000000
        data[at:at + len(sides[0])] = sides[side - 1]
    return bytes(data)


OLD, NEW, NEW_COPY = image(1, 300, 2), image(2, 200, 1), image(2, 200, 2)


def run(server, rom, stop=lambda: False):
    host, client = session(server, b"\xff" * 0x20000)
    client.rom_stubs = {buffer_script.ROM_BASE: rom.ljust(rom_transfer.BLOCKS * rom_transfer.BLOCK, b"\xff")}
    drive(host, client, ticks=3_000_000, stop=lambda: client.rebooted or stop())
    return client


def rom_of(client):
    return bytes(client.machine.uc.mem_read(buffer_script.ROM_BASE, rom_transfer.BLOCKS * rom_transfer.BLOCK))


def test_the_console_boots_the_new_rom_and_its_live_blocks_change_only_at_the_boot():
    server = rom_transfer.RomTransferServer(NEW, live=LIVE)
    client = run(server, OLD)
    assert server.outcome == "booted" and client.rebooted and client.machine.soft_resets == 1
    assert rom_of(client) == NEW_COPY.ljust(len(rom_of(client)), b"\xff")
    writes = [n for n, _ in client.machine.rom_writes]
    boot = len(writes) - (len(LIVE & set(range(50))) + rom_transfer.BLOCKS - 50)
    assert not LIVE & set(writes[:boot])
    assert sorted(writes[boot:boot + 3]) == [0, 5, 40]


def test_without_the_boot_every_block_is_written_and_checked_and_the_live_ones_hold_the_old_bytes():
    server = rom_transfer.RomTransferServer(NEW, live=LIVE, boot=False)
    client = run(server, OLD)
    assert server.outcome == "written" and not client.rebooted
    rom, blocks = rom_of(client), rom_transfer.blocks_of(NEW)
    old = OLD.ljust(len(rom), b"\xff")
    for n in range(len(blocks)):
        expected = old if n in LIVE else NEW_COPY.ljust(len(rom), b"\xff")
        assert rom[n * 4096:(n + 1) * 4096] == expected[n * 4096:(n + 1) * 4096], n
    _, _, start, moved = server.plan([0] * rom_transfer.BLOCKS)
    assert [rom[(start + i) * 4096:(start + i + 1) * 4096] for i in range(len(moved))] == [blocks[n] for n in moved]
    assert 0x10 not in LIVE and rom[0x10 * 4096:0x11 * 4096] == rom_transfer.blocks_of(NEW_COPY)[0x10]


def test_a_transfer_the_link_cut_goes_on_with_only_the_blocks_still_missing():
    seen = []
    first = rom_transfer.RomTransferServer(NEW, live=LIVE, progress=lambda d, n: seen.append((d, n)))
    client = run(first, OLD, stop=lambda: bool(seen) and seen[-1][0] >= 20)
    assert first.outcome is None
    totals = []
    second = rom_transfer.RomTransferServer(NEW, live=LIVE, progress=lambda d, n: totals.append(n))
    client = run(second, rom_of(client)[:len(OLD)])
    assert second.outcome == "booted"
    assert totals[0] <= seen[0][1] - 20
    assert rom_of(client) == NEW_COPY.ljust(len(rom_of(client)), b"\xff")


def test_a_block_that_reads_back_wrong_ends_the_session_with_no_boot(monkeypatch):
    real = buffer_script._Machine._on_swi

    def unreliable(machine, uc, intno, user_data=None):
        real(machine, uc, intno, user_data)
        if machine.rom_writes and machine.rom_writes[-1][0] == 7:
            uc.mem_write(buffer_script.ROM_BASE + 7 * 4096, b"\x00")
    monkeypatch.setattr(buffer_script._Machine, "_on_swi", unreliable)
    server = rom_transfer.RomTransferServer(NEW, live=LIVE)
    host, client = session(server, b"\xff" * 0x20000)
    client.rom_stubs = {buffer_script.ROM_BASE: OLD.ljust(rom_transfer.BLOCKS * rom_transfer.BLOCK, b"\xff")}
    assert drive(host, client, ticks=3_000_000)
    assert server.outcome == "not-written" and server.failed == 7 and not client.rebooted


def test_an_image_with_no_librfu_where_the_cartridge_has_it_is_refused_with_nothing_written():
    """The application's link patches go at the cartridge's librfu; a ROM built for another cartridge
    would have them land on other code."""
    server = rom_transfer.RomTransferServer(image(2, 200, 1)[:SIO32ID - 0x08000000] + bytes(4096), live=LIVE)
    client = run(server, OLD)
    assert server.outcome == "refused" and client.machine is None


@pytest.mark.parametrize("code", sorted(builds.SIO32ID))
def test_the_wrapper_patch_sites_hold_the_cartridges_own_instructions(code, monkeypatch):
    """The table's cartridge bytes, read at each site of each cartridge [docs/frlg_rom.md, The
    breakpoint hooks]."""
    monkeypatch.setattr(builds, "SIO32ID", CARTRIDGES)
    build = builds.BUILDS[code]
    path = ROMS / f"{'FireRed' if build.version == 'firered' else 'LeafGreen'}_{code[3].lower()}.gba"
    if not path.exists():
        pytest.skip(f"{path} is not on this machine")
    rom = path.read_bytes()
    assert [rom[at:at + len(original)] for at, original, _ in builds.wrapper_patches(code)] == \
        [original for _, original, _ in builds.WRAPPER_PATCHES]


def test_a_live_set_with_no_room_past_the_image_is_refused():
    with pytest.raises(ValueError):
        rom_transfer.staging_start(10, rom_transfer.BLOCKS - 5, ())
    assert rom_transfer.staging_start(3, 50, {50, 52, 60}) == 53


def test_the_survey_hash_is_the_payloads():
    """block_hash against the payload's own OP_SURVEY over a ROM it hashes."""
    blocks = rom_transfer.blocks_of(OLD)[:3]
    machine = buffer_script.session_machine(rom_transfer.code(), memory={buffer_script.ROM_BASE: b"".join(blocks)})
    machine.call()
    machine.load(rom_transfer.survey_message(0, 3, 9), param=0)
    run = machine.call()
    assert [int.from_bytes(run.pending_send[at:at + 4], "little") for at in range(0, 12, 4)] == \
        [rom_transfer.block_hash(raw) for raw in blocks]


def test_blocks_of_one_byte_go_as_fills_and_the_sound_engine_stops_at_install():
    """A run of one-byte blocks is a single OP_FILL message; install zeroes gSoundInfo.ident, so
    SoundMain reads no song or wave data from the ROM being replaced."""
    build = builds.BUILDS["BPRF"]
    blocks = rom_transfer.blocks_of(NEW)
    new = b"".join(blocks[:20]) + bytes(40 * 4096) + b"\x5a" * 4096 + b"".join(blocks[20:])
    copy = image(2, 200, 2)
    expected = b"".join(rom_transfer.blocks_of(copy)[:20]) + bytes(40 * 4096) + b"\x5a" * 4096 \
        + b"".join(rom_transfer.blocks_of(copy)[20:])
    server = rom_transfer.RomTransferServer(new, live=set())
    host, client = session(server, b"\xff" * 0x20000)
    client.rom_stubs = {buffer_script.ROM_BASE: OLD.ljust(rom_transfer.BLOCKS * rom_transfer.BLOCK, b"\xff"),
                        build.sound_info: b"Smsh"}
    fills = []
    real = rom_transfer.fill_message
    rom_transfer.fill_message = lambda *a: fills.append(a) or real(*a)
    try:
        drive(host, client, ticks=3_000_000, stop=lambda: client.rebooted)
    finally:
        rom_transfer.fill_message = real
    assert server.outcome == "booted"
    assert (0, 20, 8) in fills and (0, 52, 8) in fills and (0x5A, 60, 1) in fills
    rom = rom_of(client)
    assert rom == expected.rstrip(b"\xff").ljust(len(rom), b"\xff")
    assert client.machine.uc.mem_read(build.sound_info, 4) == bytes(4)

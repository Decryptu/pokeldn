"""The ROM transfer, whole stack: our Mystery Gift host against the scripted console, whose ROM copy
outlives the session and whose asm/rom-transfer.s runs under unicorn [docs/rse_switch_build.md,
Delivery without Atmosphere]."""

import random

import pytest

from pokeldn.frlg.gift import rom_transfer
from pokeldn.frlg.rom import buffer_script
from test_save_transfer import drive, session

pytestmark = pytest.mark.skipif(not buffer_script.emulation_available(), reason="needs unicorn")

LIVE = {0, 5, 40, 60}           # 60 is past the new image: it becomes 0xFF and is never staged


def image(seed, kb):
    """Runs and noise, as a ROM has, ending short of a block."""
    rng, data = random.Random(seed), bytearray()
    while len(data) < kb * 1024:
        data += rng.choice((rng.randbytes(rng.randrange(1, 300)), bytes([rng.randrange(256)]) * rng.randrange(3, 400)))
    return bytes(data[:kb * 1024 - 7])


OLD, NEW = image(1, 300), image(2, 200)


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
    assert rom_of(client) == NEW.ljust(len(rom_of(client)), b"\xff")
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
        expected = old if n in LIVE else NEW.ljust(len(rom), b"\xff")
        assert rom[n * 4096:(n + 1) * 4096] == expected[n * 4096:(n + 1) * 4096], n
    _, _, start, moved = server.plan([0] * rom_transfer.BLOCKS)
    assert [rom[(start + i) * 4096:(start + i + 1) * 4096] for i in range(len(moved))] == [blocks[n] for n in moved]


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
    assert rom_of(client) == NEW.ljust(len(rom_of(client)), b"\xff")


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

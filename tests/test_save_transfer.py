"""Save backup and restore, whole stack: our Mystery Gift host against the scripted console, whose save
chip and memory persist through the session and whose payloads run under unicorn
[docs/frlg_gift.md, Save backup and restore]."""

import pathlib
import random

import pytest

from pokeldn.frlg.gift import host_mystery_gift, mg_client, mg_script, save_transfer
from pokeldn.frlg.link import linkplayer
from pokeldn.frlg.rom import buffer_script, builds
from pokeldn.frlg.save import sav
from pokeldn.frlg.save.save_inject import sector_checksum
from pokeldn.frlg.text import charmap
from pokeldn.gba import rfu

pytestmark = pytest.mark.skipif(not buffer_script.emulation_available(), reason="needs unicorn")

ROMS = pathlib.Path("scratchpad/frlg_languages")


def synthetic_save(counter, *, seed, name="ASH", layout="latin"):
    """Both slots whole, the newer at `counter`; data with runs and noise, as a real save has."""
    rng = random.Random(seed)
    image = bytearray(b"\xff" * sav.SAVE_SIZE)
    for slot, count in ((counter % 2, counter), (1 - counter % 2, counter - 1)):
        rotate = rng.randrange(14)
        for position in range(14):
            ident = (position + 14 - rotate) % 14
            size = sav.CHUNK_SIZES[layout][ident]
            data = bytearray(rng.choice((0, 0xFF)) for _ in range(size))
            for _ in range(40):
                at = rng.randrange(size - 64)
                data[at:at + 64] = rng.randbytes(64)
            if ident == 0:
                data[0:8] = charmap.encode(name).ljust(8, b"\xff")
                data[0x0A:0x0E] = (0xBEEF1234 + seed).to_bytes(4, "little")
            if ident == 1:      # one of the player's own Pokemon: its OT ID and language are in the clear
                data[0x34] = 1
                data[0x38:0x3C] = rng.randbytes(4)
                data[0x3C:0x40] = (0xBEEF1234 + seed).to_bytes(4, "little")
                data[0x38 + 0x12] = 1 if layout == "japanese" else 2
            raw = bytearray(4096)
            raw[:size] = data
            raw[0xFF4:0xFF6] = ident.to_bytes(2, "little")
            raw[0xFF6:0xFF8] = sector_checksum(raw, size).to_bytes(2, "little")
            raw[0xFF8:0xFFC] = (0x08012025).to_bytes(4, "little")
            raw[0xFFC:0x1000] = count.to_bytes(4, "little")
            n = slot * 14 + position
            image[n * 4096:(n + 1) * 4096] = raw
    for n in sav.EXTRA_SECTORS:
        image[n * 4096:n * 4096 + 512] = rng.randbytes(512)
    return bytes(image)


def session(server, flash, game_code=b"BPRF"):
    host = host_mystery_gift.HostMysteryGiftEngine(
        server=server, link_player=linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED),
        timing=host_mystery_gift.MysteryGiftTiming(client_ready_idle_frames=10))
    client = mg_client.MysteryGiftClientEngine(
        linkplayer.LinkPlayer(name="POKELDN", version=linkplayer.VERSION_FIRE_RED),
        version="firered", game_code=game_code, flash=flash)
    return host, client


def drive(host, client, ticks=400_000, stop=lambda: False):
    """-> True when the link closed, False when `stop()` cut it first."""
    slot, child = rfu.SlotBuilder(), rfu.idle_slot()
    for t in range(ticks):
        if stop():
            return False
        table = rfu.pack_recv_cmds([rfu.serialize(host.tick()), child])
        record = {"type": "T", "ts": t, "slot_len": 73, "llsf_state": 4,
                  "slots": [(m, table[m * 14:(m + 1) * 14]) for m in range(2)], "payload": table}
        record["positional"] = record["slots"]
        client.feed_in_frame(record)
        child = slot.build(client.tick() or [0] * 7)
        host.feed_child_slot(child)
        if host.disconnect_requested:
            host.mark_disconnect_sent()
            return True
    raise AssertionError(f"flow did not finish: host={host.state} client={client.status()}")


def loaded_blocks(image):
    summary = sav.describe(image)
    return summary.newest.counter, [sav.block(image, ident, summary) for ident in range(14)]


@pytest.mark.parametrize("game_code", [code.encode() for code in sorted(builds.BUILDS)])
def test_a_backup_returns_the_chip_byte_for_byte_and_the_console_saves_nothing(game_code):
    chip = synthetic_save(51, seed=1, layout="japanese" if game_code.endswith(b"J") else "latin")
    server = save_transfer.SaveBackupServer()
    host, client = session(server, chip, game_code)
    assert drive(host, client)
    assert server.save == chip and server.outcome == "backed-up"
    assert client.result == mg_script.CLI_MSG_BUFFER_FAILURE      # the exit that does not save
    assert client.flash == chip


def test_a_backup_the_link_cut_goes_on_from_where_it_stopped(tmp_path):
    chip = synthetic_save(9, seed=2)
    seen = []
    first = save_transfer.SaveBackupServer(resume_dir=str(tmp_path), progress=lambda d, n: seen.append(d))
    host, client = session(first, chip)
    assert not drive(host, client, stop=lambda: bool(seen) and seen[-1] > 40_000)
    kept = seen[-1]
    assert first.save is None

    starts = []
    second = save_transfer.SaveBackupServer(resume_dir=str(tmp_path), progress=lambda d, n: starts.append(d))
    host, client = session(second, chip)
    assert drive(host, client)
    assert starts[0] == kept
    assert second.save == chip
    assert not list(tmp_path.glob("*.partial"))


def test_a_restore_puts_the_file_on_the_chip_and_the_game_loads_it():
    chip, wanted = synthetic_save(205, seed=3), synthetic_save(1377, seed=4, name="MISTY")
    server = save_transfer.SaveRestoreServer(wanted)
    host, client = session(server, chip)
    assert drive(host, client)
    assert server.outcome == "restored"
    assert client.result == mg_script.CLI_MSG_BUFFER_SUCCESS       # the console saves what it loaded
    after = client.flash
    counter, blocks = loaded_blocks(after)
    assert counter == 206 and blocks == loaded_blocks(wanted)[1]
    assert client.machine.loads == [(1, 206)]
    assert all(sav.sector(after, n) == sav.sector(wanted, n) for n in sav.EXTRA_SECTORS)
    assert sav.trainer(after)["name"] == "MISTY"
    # The console's own copy stays whole in the other slot until the game's save replaces it.
    old = sav.describe(chip).newest
    assert sav.slot(after, old.index).sound and sav.slot(after, old.index).counter == 205


def test_a_restore_cut_short_leaves_the_console_loading_its_own_save():
    chip, wanted = synthetic_save(205, seed=5), synthetic_save(1377, seed=6)
    reports = []
    server = save_transfer.SaveRestoreServer(wanted, progress=lambda d, n: reports.append(d))
    host, client = session(server, chip)
    assert not drive(host, client, stop=lambda: bool(reports) and reports[-1] >= 8)
    assert loaded_blocks(client.flash) == loaded_blocks(chip)


@pytest.mark.parametrize("game_code, layout", [(b"BPRF", "japanese"), (b"BPRJ", "latin")])
def test_a_save_of_the_other_layout_is_refused_with_nothing_written(game_code, layout):
    chip = synthetic_save(7, seed=7, layout="japanese" if layout == "latin" else "latin")
    server = save_transfer.SaveRestoreServer(synthetic_save(8, seed=8, layout=layout))
    host, client = session(server, chip, game_code)
    assert drive(host, client)
    assert server.outcome == "refused" and client.buffer_scripts == []
    assert client.flash == chip
    assert client.result == mg_script.CLI_MSG_BUFFER_FAILURE


@pytest.mark.parametrize("code", sorted(builds.BUILDS))
def test_the_save_addresses_are_the_functions_on_each_cartridge(code):
    """LoadGameSave opens `push {r4-r6,lr}; lsls r0,#24` and pools gDecompressionBuffer; the queue count
    is read by `ldr r0,=gRfu; ldr r1,=0x8D2; adds; ldrb` [decomp:src/save.c:803, link_rfu_2.c:3131]."""
    build = builds.BUILDS[code]
    names = {"E": "e", "F": "f", "D": "d", "I": "i", "S": "s", "J": "j"}
    path = ROMS / f"{'FireRed' if build.version == 'firered' else 'LeafGreen'}_{names[code[3]]}.gba"
    if not path.exists():
        pytest.skip(f"{path} is not on this machine")
    rom = path.read_bytes()
    at = build.load_game_save - 0x08000000
    assert rom[at:at + 4] == bytes.fromhex("70b50006")
    assert (0x0201C000).to_bytes(4, "little") in rom[at:at + 0x90]
    rfu_base = (build.rfu_send_queue - 0x8D2).to_bytes(4, "little")
    reader = bytes.fromhex("024803494018007870470000") + rfu_base + (0x8D2).to_bytes(4, "little")
    assert rom.count(reader) == 1


@pytest.mark.parametrize("code", sorted(builds.BUILDS))
def test_the_backup_runs_through_each_cartridges_own_client_and_waits_on_its_send_queue(code):
    """Every pass through the retail image's Client_RunBufferScript [mystery_gift_client.c:276], one
    frame per call; nothing moves while gRfu.sendQueue.count, as the cartridge's own 12-byte reader
    finds it [link_rfu_2.c:3131], is not zero."""
    import re
    from unicorn import arm_const as a
    build = builds.BUILDS[code]
    path = ROMS / f"{'FireRed' if build.version == 'firered' else 'LeafGreen'}_{code[3].lower()}.gba"
    if not path.exists():
        pytest.skip(f"{path} is not on this machine")
    rom = path.read_bytes()
    [reader] = re.finditer(re.escape(bytes.fromhex("024803494018007870470000")) + b"(....)" + re.escape(
        (0x8D2).to_bytes(4, "little")), rom, re.S)
    queue = int.from_bytes(reader.group(1), "little") + 0x8D2
    chip = synthetic_save(51, seed=12, layout="japanese" if code.endswith("J") else "latin")
    payload = save_transfer.backup_code(build)
    machine = buffer_script._Machine(payload, rom=rom, build=build,
                                     memory={buffer_script.FLASH_BASE: chip})
    uc = machine.uc

    def word(offset, size=4):
        return int.from_bytes(uc.mem_read(buffer_script._CLIENT_ADDRESS + offset, size), "little")

    def frame():
        uc.reg_write(a.UC_ARM_REG_R0, buffer_script._CLIENT_ADDRESS)
        uc.reg_write(a.UC_ARM_REG_SP, buffer_script.STACK_POINTER)
        uc.reg_write(a.UC_ARM_REG_LR, buffer_script._RETURN_ADDRESS | 1)
        uc.emu_start(build.client_run_buffer_script | 1, buffer_script._RETURN_ADDRESS, count=2_000_000)
        assert uc.reg_read(a.UC_ARM_REG_PC) == buffer_script._RETURN_ADDRESS
        return word(buffer_script.CLIENT_FUNC_ID) == 4         # FUNC_RUN once the payload returns 1

    image, at, param = bytearray(sav.SAVE_SIZE), 0, 0
    uc.mem_write(queue, b"\x05")
    while at < sav.SAVE_SIZE:
        machine.load(payload, param=param)
        uc.mem_write(buffer_script._CLIENT_ADDRESS + buffer_script.CLIENT_FUNC_ID, bytes(4))
        if at == 0:
            assert not any(frame() for _ in range(3))
            assert uc.mem_read(buffer_script.GDECOMPRESSION_BUFFER + 0x2800, 4) == bytes(4)   # nothing staged
            uc.mem_write(queue, b"\x00")
        assert any(frame() for _ in range(8))
        param = word(buffer_script.CLIENT_PARAM)
        send = uc.mem_read(word(buffer_script.CLIENT_LINK + buffer_script.LINK_SEND_BUFFER),
                           word(buffer_script.CLIENT_LINK + buffer_script.LINK_SEND_SIZE, 2))
        at = sav.inflate(bytes(send), image, at)
    assert bytes(image) == chip


def test_the_apps_backup_lands_in_its_library_named_for_the_trainer_and_cartridge(monkeypatch, tmp_path):
    import frlg_mg_host
    from pokeldn.app import catalog, command, saves
    from pokeldn.app.settings import Settings
    monkeypatch.setattr(saves, "SAVES", tmp_path)
    tool = next(t for g in catalog.GAMES for t in g.tools if t.key == "frlg-gift")
    values = {"--gift-file": {"mode": "save", "save": {"action": "backup"}}}
    assert command.problems(tool, values) == []
    args = command.build(tool, values, {}, Settings(), stamp="20261006-120000")
    parsed = frlg_mg_host.build_parser().parse_args(args)
    assert parsed.save_backup == str(tmp_path / "backup-20261006-120000.sav")

    chip = synthetic_save(77, seed=9, name="LEAF")
    server = save_transfer.SaveBackupServer(resume_dir=parsed.save_resume_dir)
    host, client = session(server, chip, b"BPGF")
    assert drive(host, client)
    save_transfer.write_backup(parsed.save_backup, server)
    [entry] = saves.entries()
    assert (entry.name, entry.cartridge, entry.trainer["name"]) == ("LEAF's LeafGreen", "LeafGreen", "LEAF")


def test_the_app_will_not_start_a_restore_of_a_save_with_no_whole_copy(tmp_path):
    from pokeldn.app import catalog, command
    tool = next(t for g in catalog.GAMES for t in g.tools if t.key == "frlg-gift")
    broken = bytearray(synthetic_save(5, seed=10))
    for n in range(28):
        broken[n * 4096] ^= 0xFF          # every sector's checksum now fails
    path = tmp_path / "broken.sav"
    path.write_bytes(bytes(broken))
    values = {"--gift-file": {"mode": "save", "save": {"action": "restore", "file": str(path)}}}
    assert command.problems(tool, values) == ["This save has no whole copy of a game in it."]


@pytest.mark.parametrize("backup, done, total, shown", [
    ("x.sav", 40960, sav.SAVE_SIZE, ("backup", 40, 128)), (None, 7, 19, ("restore", 7, 19))])
def test_the_launchers_progress_lines_are_the_ones_the_app_draws(backup, done, total, shown, capsys):
    from types import SimpleNamespace
    from pokeldn.app import received
    from pokeldn.frlg.gift.host_mg_app import SaveTransferHostApplication
    SaveTransferHostApplication._progress(SimpleNamespace(backup_path=backup, _shown=-1), done, total)
    assert received.save_progress(capsys.readouterr().out) == shown


def test_a_restore_waits_for_pkhex_and_then_for_restore_anyway_over_an_illegal_party(tmp_path, monkeypatch):
    from pokeldn.app import catalog, command, saves
    tool = next(t for g in catalog.GAMES for t in g.tools if t.key == "frlg-gift")
    path = tmp_path / "chosen.sav"
    path.write_bytes(synthetic_save(5, seed=11))
    chosen = {"action": "restore", "file": str(path)}
    values = {"--gift-file": {"mode": "save", "save": chosen}}
    assert command.problems(tool, values) == ["Checking the save's party with PKHeX..."]
    from pokeldn import pokemon
    monkeypatch.setattr(pokemon.SERVICE, "save_read", lambda data: {"party": [{"species": "Mew", "legal": False}]})
    saves.party_check(str(path))
    assert "Mew" in command.problems(tool, values)[0]
    chosen["anyway"] = True
    assert command.problems(tool, values) == []

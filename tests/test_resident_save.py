"""A resident hook kept in the save: one gift session writes it to filler_B20 and installs it from
there; after a boot, MOM's RAM script runs the same install-kept out of its body."""

import pytest

from pokeldn.frlg.config import BufferScriptPayload
from pokeldn.frlg.gift import host_mystery_gift, mg_client, mg_script
from pokeldn.frlg.gift import wonder_card_events as wce
from pokeldn.frlg.link import linkplayer
from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import builds
from pokeldn.frlg.rom import native_script as ns
from pokeldn.gba import rfu

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

BUILD = builds.BPRF
SB1, SB2 = 0x02025734, 0x02024584
STOP = 0x02030000
COUNTER = 0x02030100
NOENCOUNTER_FLAG = 0x020386D8


def _session(name, ticks=20000, payload=None):
    payload = payload or (BufferScriptPayload(script=bs.INSTALL_KEPT) if name is None else
                          BufferScriptPayload(script=bs.SAVE_WRITE, write_resident=(name, ())))
    distribution = payload.build_distribution()
    host = host_mystery_gift.HostMysteryGiftEngine(
        distribution=distribution,
        link_player=linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED),
        timing=host_mystery_gift.MysteryGiftTiming(client_ready_idle_frames=10))
    client = mg_client.MysteryGiftClientEngine(
        linkplayer.LinkPlayer(name="POKELDN", version=linkplayer.VERSION_FIRE_RED))
    slot, child_slot = rfu.SlotBuilder(), rfu.idle_slot()
    for t in range(ticks):
        table = rfu.pack_recv_cmds([rfu.serialize(host.tick()), child_slot])
        rec = {"type": "T", "ts": t, "slot_len": 73, "llsf_state": 4,
               "slots": [(m, table[m * 14:(m + 1) * 14]) for m in range(2)], "payload": table}
        rec["positional"] = rec["slots"]
        client.feed_in_frame(rec)
        child_slot = slot.build(client.tick() or [0] * 7)
        host.feed_child_slot(child_slot)
        if host.disconnect_requested:
            return host, client
    raise AssertionError(f"the session did not finish: host={host.state} client={client.status()}")


@pytest.mark.parametrize("name", ["follower", "shiny", "noencounter", "noclip"])
def test_one_session_keeps_the_hook_in_the_save_and_installs_it(name):
    host, client = _session(name)
    blob = bs.build_resident_save_blob(name)
    writes = -(-len(blob) // bs.MAX_SAVE_WRITE_BYTES)
    assert [bs.describe(code).split()[0] for code in client.buffer_scripts] == (
        [bs.SAVE_WRITE] * writes + [bs.INSTALL_KEPT])
    assert client.sav2[0xB20:0xB20 + len(blob)] == blob
    assert host.server.buffer_status == BUILD.vblank_intr | 1     # summed right, installed
    assert client.result == mg_script.CLI_MSG_BUFFER_SUCCESS     # the success exit saves


def test_a_write_past_one_payload_fills_filler_b20_in_one_session():
    data = bytes((i * 7 + 1) & 0xFF for i in range(bs.RESIDENT_SAVE_SIZE))
    host, client = _session(None, payload=BufferScriptPayload(
        script=bs.SAVE_WRITE, write_data=data, dump_offset=0xB20))
    assert [bs.describe(code).split()[0] for code in client.buffer_scripts] == [bs.SAVE_WRITE] * 2
    assert client.sav2[0xB20:0xF20] == data
    assert host.server.buffer_dump == data[bs.MAX_SAVE_WRITE_BYTES:]    # what the save holds
    assert client.result == mg_script.CLI_MSG_BUFFER_SUCCESS


def test_install_kept_with_nothing_kept_fails_and_does_not_save():
    host, client = _session(None)
    assert host.server.buffer_status == bs.INSTALL_REFUSED
    assert client.result == mg_script.CLI_MSG_BUFFER_FAILURE


def _booted_console(filler):
    """A console after a boot: the kept blob in filler_B20, VBlankIntr in gIntrTable[4] counting
    frames, MOM's RAM script in SaveBlock1 behind its magic, the trampoline staged."""
    tail = bytes([ns.SCR_END])
    body = ns.build_body_script(bs.build_install_kept(BUILD)[bs.INSTALL_KEPT_THUMB_ENTRY:], tail)
    prefix = ns.body_prefix_size(len(tail))
    counter = bytes.fromhex("024801680131016070470000") + COUNTER.to_bytes(4, "little")
    machine = bs._Machine(b"\x00" * 4, memory={
        BUILD.sb1ptr: SB1.to_bytes(4, "little"),
        BUILD.sb2ptr: SB2.to_bytes(4, "little"),
        SB2 + 0xB20: bytes(filler),
        SB1 + ns.RAMSCRIPT_MAGIC_OFFSET: bytes([ns.RAM_SCRIPT_MAGIC, 0, 0, 0]) + body,
        ns.SCRATCH: ns.ram_jump_stub(prefix),
        BUILD.intr_vblank: (BUILD.vblank_intr | 1).to_bytes(4, "little"),
        BUILD.vblank_intr: counter,
        0x04000208: (1).to_bytes(2, "little")})
    return machine.uc, body


def _talk_to_mom(uc):
    """ScrCmd_callnative: a THUMB call into the staged trampoline, returning to its caller."""
    from unicorn import arm_const as a
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
    uc.reg_write(a.UC_ARM_REG_CPSR, uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
    uc.emu_start(ns.SCRATCH | 1, STOP, count=200000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
    assert uc.reg_read(a.UC_ARM_REG_CPSR) & (1 << 5)
    assert int.from_bytes(uc.mem_read(0x04000208, 2), "little") == 1   # REG_IME back


def _frame(uc):
    from unicorn import arm_const as a
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP)
    uc.emu_start(_read(uc, BUILD.intr_vblank), STOP, count=100000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP


def _read(uc, at):
    return int.from_bytes(uc.mem_read(at, 4), "little")


@pytest.mark.parametrize("name, params", [("noencounter", {}), ("ivs", {}), ("follower", {}),
                                          ("shiny", {}), ("noclip", {}),
                                          ("turbo", {"field": 1, "hold": 0x100, "budget": 228})])
def test_mom_installs_the_hook_from_the_save(name, params):
    uc, _ = _booted_console(bs.build_resident_save_blob(name, **params))
    _talk_to_mom(uc)
    hook, entry, original = bs.resident_blob(name, **params)
    assert _read(uc, BUILD.intr_vblank) == ns.RESIDENT_BASE + entry + 1
    installed = bytearray(uc.mem_read(ns.RESIDENT_BASE, len(hook)))
    assert _read(uc, ns.RESIDENT_BASE + original) == BUILD.vblank_intr | 1
    installed[original:original + 4] = hook[original:original + 4]
    assert bytes(installed) == hook
    assert _read(uc, ns.RESIDENT_BASE - 4) == BUILD.vblank_intr | 1  # the game's handler, kept
    if name == "noencounter":
        _frame(uc)
        assert uc.mem_read(NOENCOUNTER_FLAG, 1)[0] == 1 and _read(uc, COUNTER) == 1


def test_a_second_visit_still_chains_to_the_game():
    uc, _ = _booted_console(bs.build_resident_save_blob("noencounter"))
    _talk_to_mom(uc)
    _talk_to_mom(uc)
    _, _, original = bs.resident_blob("noencounter")
    assert _read(uc, ns.RESIDENT_BASE + original) == BUILD.vblank_intr | 1
    _frame(uc)
    assert _read(uc, COUNTER) == 1


@pytest.mark.parametrize("damage", ["byte", "short", "length", "older"])
def test_a_blob_that_did_not_all_arrive_installs_nothing(damage):
    blob = bytearray(bs.build_resident_save_blob("follower"))
    if damage == "byte":
        blob[700] ^= 0x40
    elif damage == "short":
        blob = blob[:bs.MAX_SAVE_WRITE_BYTES] + bytes(len(blob) - bs.MAX_SAVE_WRITE_BYTES)
    elif damage == "length":
        blob[4:8] = (0x10000).to_bytes(4, "little")             # a sum that would leave filler_B20
    else:
        blob = bytearray(ns.build_save_payload())               # PKLD, the older payload
    uc, _ = _booted_console(blob)
    _talk_to_mom(uc)
    assert _read(uc, BUILD.intr_vblank) == BUILD.vblank_intr | 1


@pytest.mark.parametrize("name", sorted(bs.RESIDENT_HOOKS))
def test_every_hook_fits_filler_b20(name):
    assert len(bs.build_resident_save_blob(name)) <= bs.RESIDENT_SAVE_SIZE


@pytest.mark.parametrize("code", builds.GAME_CODES)
def test_the_card_binds_this_body(code):
    build = builds.for_game_code(code)
    kept = bs.build_install_kept(build)
    assert kept[-8:] == build.sb2ptr.to_bytes(4, "little") + build.intr_vblank.to_bytes(4, "little")
    assert kept[bs.INSTALL_KEPT_THUMB_ENTRY:] in wce.build_resident_save_script(build=build)

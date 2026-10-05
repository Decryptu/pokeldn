"""The English and Spanish builds' payloads on their retail cartridge images under unicorn, through their
own Client_RunBufferScript [mystery_gift_client.c:276]."""

import pathlib

import pytest

from pokeldn import config
from pokeldn.frlg.gift import wonder_card_events as wce
from pokeldn.frlg.rom import buffer_script as bs, builds, native_script as ns
from pokeldn.frlg.save import mon as monlib

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

CARTRIDGES = [pytest.param(builds.BPRE, "scratchpad/frlg_en/FireRed_e.gba", id="BPRE"),
              pytest.param(builds.BPGE, "scratchpad/frlg_en/LeafGreen_e.gba", id="BPGE"),
              pytest.param(builds.BPRS, "scratchpad/frlg_es/FireRed_s.gba", id="BPRS")]
TRAINER_ID = 0x0AE73039
FUNC_RUN = 4                        # client->funcId once the payload returns 1 [mystery_gift_client.c:17]
FRENCH_INTR_VBLANK = builds.BPRF.intr_vblank
NOENCOUNTER_FLAG = 0x020386D8
STOP = 0x02030000
BIOS_SIZE = 0x4000                  # mapped as zeros: VBlankIntr's sound code reads it


def _image(path):
    rom = pathlib.Path(path)
    if not rom.exists():
        pytest.skip("no cartridge image on this machine")
    return rom.read_bytes()


def _payload(build, **fields):
    return config.BufferScriptPayload(**fields).build_code(build)


def _console(code, build, rom, memory=None):
    """The payload in gDecompressionBuffer, the save blocks behind this build's pointers."""
    sav2 = bytearray(0xF24)
    sav2[0:8] = bytes([0xCA, 0xC9, 0xC5, 0xBF, 0xC6, 0xBE, 0xC8, 0xFF])  # POKELDN
    sav2[0x0A:0x0E] = TRAINER_ID.to_bytes(4, "little")
    memory = {build.sb2ptr: bs.SAV2_ADDRESS.to_bytes(4, "little"),
              build.sb1ptr: bs.SAV1_ADDRESS.to_bytes(4, "little"),
              build.rng: (0x0BADF00D).to_bytes(4, "little"), **(memory or {})}
    return bs._Machine(code, rom=rom, build=build, sav2=bytes(sav2), sav1=bytes(0x3D68),
                       memory=memory)


def _client_frame(machine, build):
    """One frame of the cartridge's own Client_RunBufferScript -> (funcId, param, pending send)."""
    from unicorn import arm_const as a
    uc = machine.uc
    uc.reg_write(a.UC_ARM_REG_R0, bs._CLIENT_ADDRESS)
    uc.reg_write(a.UC_ARM_REG_SP, bs.STACK_POINTER)
    uc.reg_write(a.UC_ARM_REG_LR, bs._RETURN_ADDRESS | 1)
    uc.emu_start(build.client_run_buffer_script | 1, bs._RETURN_ADDRESS, count=2_000_000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == bs._RETURN_ADDRESS

    def word(offset, size=4):
        return int.from_bytes(uc.mem_read(bs._CLIENT_ADDRESS + offset, size), "little")
    send = bytes(uc.mem_read(word(bs.CLIENT_LINK + bs.LINK_SEND_BUFFER),
                             word(bs.CLIENT_LINK + bs.LINK_SEND_SIZE, 2)))
    return word(bs.CLIENT_FUNC_ID), word(bs.CLIENT_PARAM), send


def _word(machine, address):
    return int.from_bytes(machine.uc.mem_read(address, 4), "little")


def _create_mon(build):
    return _payload(build, script=bs.CREATE_MON, create_mon_species=25, create_mon_level=5,
                    create_mon_fixed_iv=31, create_mon_personality=0x12345678)


@pytest.mark.parametrize("build, path", CARTRIDGES)
def test_the_trainer_id_probe_returns_through_the_cartridges_client(build, path):
    machine = _console(bs.payload(bs.TRAINER_ID_PROBE), build, _image(path))
    func_id, param, _ = _client_frame(machine, build)
    assert (func_id, param) == (FUNC_RUN, TRAINER_ID)


@pytest.mark.parametrize("build, path", CARTRIDGES)
def test_create_mon_makes_a_pikachu_in_the_cartridges_language(build, path):
    machine = _console(_create_mon(build), build, _image(path))
    func_id, _, send = _client_frame(machine, build)
    result = bs.read_create_mon(send)
    info = monlib.decode_mon(result["mon"])
    assert func_id == FUNC_RUN and result["calls"] == 1
    assert (info["pid"], info["otid"], info["checksum_ok"], info["species"]) == \
        (0x12345678, TRAINER_ID, True, 25)
    assert result["mon"][18] == build.language_id     # struct BoxPokemon.language


@pytest.mark.parametrize("build, path", CARTRIDGES)
def test_the_french_create_mon_makes_nothing_on_another_cartridge(build, path):
    """French CreateMon's address is inside another cartridge function; no Pokemon comes back."""
    from unicorn import UcError
    machine = _console(_create_mon(builds.BPRF), build, _image(path))
    try:
        _, _, send = _client_frame(machine, build)
    except UcError:
        return
    info = monlib.decode_mon(bs.read_create_mon(send)["mon"])
    assert info is None or not info["checksum_ok"] or info["species"] != 25


@pytest.mark.parametrize("build, path", CARTRIDGES)
def test_the_chain_calls_the_cartridges_getvarpointer(build, path):
    var = bs.SAV1_ADDRESS + 0x1000 + 2 * 0x24       # SaveBlock1.vars[0x4024 - VARS_START] [global.h:791]
    code = _payload(build, script=bs.CALL_CHAIN, chain_steps=(
        bs.parse_chain_step("call:GetVarPointer,0x4024"), bs.parse_chain_step("read16:prev")))
    machine = _console(code, build, _image(path), {var: (0xBEEF).to_bytes(2, "little")})
    func_id, _, send = _client_frame(machine, build)
    answer = bs.read_call_chain(send)
    assert func_id == FUNC_RUN
    assert (answer["executed"], answer["values"][:2]) == (2, [var, 0xBEEF])


@pytest.mark.parametrize("build, path", CARTRIDGES)
def test_install_resident_patches_the_cartridges_gintrtable(build, path):
    """noencounter installed through the client, then one V-blank dispatched through gIntrTable[4]:
    the flag is set and the cartridge's own VBlankIntr runs once behind the hook."""
    from unicorn import UC_HOOK_CODE
    from unicorn import arm_const as a
    marker = 0x0A0B0C0D
    other_intr = (builds.BPRE.intr_vblank if build.intr_vblank == FRENCH_INTR_VBLANK
                  else FRENCH_INTR_VBLANK)
    code = _payload(build, script=bs.INSTALL_RESIDENT, resident_name="noencounter",
                    write_unsafe=True)
    machine = _console(code, build, _image(path), {
        build.intr_vblank: (build.vblank_intr | 1).to_bytes(4, "little"),
        other_intr: marker.to_bytes(4, "little")})
    func_id, original, _ = _client_frame(machine, build)
    assert (func_id, original) == (FUNC_RUN, build.vblank_intr | 1)
    assert _word(machine, build.intr_vblank) == ns.RESIDENT_BASE | 1
    assert _word(machine, other_intr) == marker

    uc = machine.uc
    uc.mem_map(0, BIOS_SIZE)
    uc.mem_write(build.gmain + 4, (build.cb2_overworld | 1).to_bytes(4, "little"))
    uc.mem_write(build.intr_check, b"\x00\x00")
    entered = []
    uc.hook_add(UC_HOOK_CODE, lambda uc_, address, size, user: entered.append(address),
                begin=build.vblank_intr, end=build.vblank_intr)
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP)
    uc.emu_start(_word(machine, build.intr_vblank), STOP, count=2_000_000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
    assert (uc.mem_read(NOENCOUNTER_FLAG, 1)[0], len(entered)) == (1, 1)


def _unstage(field_script):
    """-> (address, code, callnative target) of a `setptr` run followed by one `callnative`."""
    staged, at = {}, 0
    while field_script[at] == ns.SCR_SETPTR:
        staged[int.from_bytes(field_script[at + 2:at + 6], "little")] = field_script[at + 1]
        at += ns.SETPTR_SIZE
    assert field_script[at] == ns.SCR_CALLNATIVE
    base = min(staged)
    return (base, bytes(staged[base + i] for i in range(len(staged))),
            int.from_bytes(field_script[at + 1:at + 5], "little"))


@pytest.mark.parametrize("build, path", CARTRIDGES)
def test_moms_script_installs_the_hook_kept_in_the_save(build, path):
    """The field script the resident-save card binds to MOM, run on a save holding the noencounter
    blob that save-write --resident puts at SaveBlock2 + 0xB20: the staged trampoline reads
    gSaveBlock1Ptr and branches into install-kept in the RAM script's body."""
    from unicorn import arm_const as a
    tail = bytes([ns.SCR_PLAYSE]) + ns.SE_SUCCESS.to_bytes(2, "little") + bytes([ns.SCR_WAITSE,
                                                                                 ns.SCR_END])
    field = ns.build_body_script(
        bs.build_install_kept(build)[bs.INSTALL_KEPT_THUMB_ENTRY:], tail, build=build)
    assert field in wce.build_resident_save_script(build=build)
    base, stub, target = _unstage(field)
    machine = _console(b"\x00" * 4, build, _image(path), {
        build.intr_vblank: (build.vblank_intr | 1).to_bytes(4, "little"),
        bs.SAV2_ADDRESS + 0xB20: bs.build_resident_save_blob("noencounter", build=build),
        bs.SAV1_ADDRESS + ns.RAMSCRIPT_MAGIC_OFFSET: bytes([ns.RAM_SCRIPT_MAGIC, 0, 0, 0]) + field,
        base: stub})
    uc = machine.uc
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
    uc.reg_write(a.UC_ARM_REG_CPSR, uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
    uc.emu_start(target, STOP, count=2_000_000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
    assert _word(machine, build.intr_vblank) == ns.RESIDENT_BASE | 1

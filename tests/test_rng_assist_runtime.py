import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import builds, native_script as ns


def test_rng_assist_is_a_standalone_bounded_resident_hook():
    destination = ns.RESIDENT_BASE + 0x20
    params = {"state": 0x0203FF80, "offset": 7, "auto_a": 0}
    blob, entry, original = bs.resident_blob("rng-assist", build=builds.BPRE, dest=destination, **params)
    from pokeldn.frlg.rom.resident_stubs import STUBS
    symbols = STUBS["rng-assist"][2]
    assert len(blob) % 4 == 0 and len(blob) < 0x400
    assert entry == symbols["rng_assist_hook"]
    assert original == symbols["p_original"]
    shim = int.from_bytes(blob[symbols["p_input_shim"]:symbols["p_input_shim"] + 4], "little")
    assert shim == destination + symbols["rng_assist_input_shim"]
    with pytest.raises(bs.BufferScriptError, match="0..255"):
        bs.resident_blob("rng-assist", offset=256)
    installed = bs.build_install_resident("rng-assist", build=builds.BPRE, **params)
    assert len(installed) <= bs.MAX_BUFFER_SCRIPT_SIZE


def test_rng_assist_cannot_be_added_to_the_legacy_chain():
    with pytest.raises(bs.BufferScriptError, match="runs alone"):
        bs.build_install_resident("rng-assist+turbo")


@pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")
def test_rng_assist_tracks_a_seed_and_injects_one_a_then_restores_callback():
    from unicorn import arm_const as a
    from pokeldn.frlg.rom import lcg

    build = builds.BPRE
    vblank_counter = 0x02030100
    callback_counter = 0x02030110
    counting_stub = bytes.fromhex("024801680131016070470000") + vblank_counter.to_bytes(4, "little")
    callback_stub = bytes.fromhex("024801680131016070470000") + callback_counter.to_bytes(4, "little")
    memory = {
        build.intr_vblank: (build.vblank_intr | 1).to_bytes(4, "little"),
        build.vblank_intr: counting_stub,
        build.gmain: ((build.cb1_overworld | 1).to_bytes(4, "little")
                      + (build.cb2_overworld | 1).to_bytes(4, "little")),
        build.intr_check: (0).to_bytes(2, "little"),
        build.gmain + 0x2C: bytes(8),
        build.rng: (0).to_bytes(4, "little"),
        build.cb1_overworld: callback_stub,
    }
    code = bs.build_install_resident(
        "rng-assist", build=build, auto_a=1, trigger_index=1, offset=0,
        target_pid=0x12345678, target_nature=3, state=0x0203FF80)
    machine = bs._Machine(code, memory=memory, build=build)
    machine.call()
    entry = int.from_bytes(machine.uc.mem_read(build.intr_vblank, 4), "little")
    stop = 0x02030020

    def frame(seed):
        machine.uc.mem_write(build.rng, int(seed).to_bytes(4, "little"))
        machine.uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        machine.uc.reg_write(a.UC_ARM_REG_LR, stop)
        machine.uc.reg_write(a.UC_ARM_REG_CPSR,
                             machine.uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
        machine.uc.emu_start(entry, stop, count=100000)

    def word(address):
        return int.from_bytes(machine.uc.mem_read(address, 4), "little")

    frame(0)
    assert word(0x0203FF84) == 0
    frame(lcg.step(0))
    shim = word(build.gmain)
    assert shim != (build.cb1_overworld | 1)
    assert word(0x0203FF84) == 1
    assert word(0x0203FFB4) & 0x13 == 0x13  # initialized + armed + pending A

    machine.uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    machine.uc.reg_write(a.UC_ARM_REG_LR, stop)
    machine.uc.reg_write(a.UC_ARM_REG_CPSR,
                         machine.uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
    machine.uc.emu_start(shim, stop, count=100000)
    assert int.from_bytes(machine.uc.mem_read(build.gmain + 0x2E, 2), "little") & 1
    assert int.from_bytes(machine.uc.mem_read(build.gmain + 0x30, 2), "little") & 1
    assert word(build.gmain) == (build.cb1_overworld | 1)
    assert word(callback_counter) == 1
    assert word(0x0203FFB4) & 0x1D == 0x1D  # initialized + fired + hit-locked + armed


@pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")
def test_rng_assist_does_not_arm_on_a_lag_frame():
    from unicorn import arm_const as a
    from pokeldn.frlg.rom import lcg

    build = builds.BPRE
    vblank_counter = 0x02030200
    callback_counter = 0x02030210
    counting_stub = bytes.fromhex("024801680131016070470000") + vblank_counter.to_bytes(4, "little")
    callback_stub = bytes.fromhex("024801680131016070470000") + callback_counter.to_bytes(4, "little")
    memory = {
        build.intr_vblank: (build.vblank_intr | 1).to_bytes(4, "little"),
        build.vblank_intr: counting_stub,
        build.intr_check: (1).to_bytes(2, "little"),
        build.gmain: ((build.cb1_overworld | 1).to_bytes(4, "little")
                      + (build.cb2_overworld | 1).to_bytes(4, "little")),
        build.gmain + 0x2C: bytes(8),
        build.rng: (0).to_bytes(4, "little"),
        build.cb1_overworld: callback_stub,
    }
    code = bs.build_install_resident(
        "rng-assist", build=build, auto_a=1, trigger_index=1, offset=0,
        state=0x0203FF80)
    machine = bs._Machine(code, memory=memory, build=build)
    machine.call()
    entry = int.from_bytes(machine.uc.mem_read(build.intr_vblank, 4), "little")
    stop = 0x02030020

    def frame(seed):
        machine.uc.mem_write(build.rng, int(seed).to_bytes(4, "little"))
        machine.uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        machine.uc.reg_write(a.UC_ARM_REG_LR, stop)
        machine.uc.reg_write(a.UC_ARM_REG_CPSR,
                             machine.uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
        machine.uc.emu_start(entry, stop, count=100000)

    def word(address):
        return int.from_bytes(machine.uc.mem_read(address, 4), "little")

    frame(0)
    frame(lcg.step(0))
    assert word(build.gmain) == (build.cb1_overworld | 1)
    assert not (word(0x0203FFB4) & 0x2)  # no pending A from the lag frame
    machine.uc.mem_write(build.intr_check, (0).to_bytes(2, "little"))
    frame(lcg.step(lcg.step(0)))
    assert word(0x0203FFB4) & 0x40  # the missed trigger is explicit on the next safe frame

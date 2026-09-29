"""sloop-svc: Sloop syscalls from the Mystery Gift menu, answered through a result block."""

import pytest

from pokeldn import config as configmod
from pokeldn.frlg.rom import buffer_script as bs

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

COPY = bs.FLASH_WRITE_SCRATCH + bs.SLOOP_HEADER_SIZE


def _run_with_scripted_syscalls(code):
    """Run the payload; each `swi` masks the string the way swi 0x4D does and sets r0..r3."""
    import unicorn
    from unicorn import arm_const as a
    machine = bs._Machine(code)
    seen = []

    def on_swi(uc, intno, user_data):
        pc = uc.reg_read(a.UC_ARM_REG_PC)
        regs = [uc.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                                         a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)]
        number = uc.mem_read(pc - 2, 2)[0]
        text = bytes(uc.mem_read(regs[0], 257)).split(b"\0")[0]
        seen.append({"thumb": bool(uc.reg_read(a.UC_ARM_REG_CPSR) & (1 << 5)),
                     "number": number, "regs": regs, "text": text})
        uc.mem_write(regs[0], text.replace(b"fuck", b"****"))
        for reg, value in zip((a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2,
                               a.UC_ARM_REG_R3), (len(seen), 0xA1, 0xA2, number)):
            uc.reg_write(reg, value)
    machine.uc.hook_add(unicorn.UC_HOOK_INTR, on_swi)
    return machine.call(), seen


def test_each_call_sees_a_fresh_copy_and_the_answer_carries_what_each_left():
    code = bs.build_sloop_svc([0x4D, 0x4D, 0x53], (0, 0), b"what the fuck",
                              flags=bs.SLOOP_R0_IS_DATA)
    result, seen = _run_with_scripted_syscalls(code)
    assert result.done
    assert [s["number"] for s in seen] == [0x4D, 0x4D, 0x53]      # the rewritten byte ran
    assert all(s["thumb"] for s in seen)
    assert all(s["regs"][:2] == [COPY, 0] for s in seen)
    assert all(s["text"] == b"what the fuck" for s in seen)       # re-copied, terminated
    assert result.client.send_buffer == bs.FLASH_WRITE_SCRATCH
    assert result.client.send_size == bs.sloop_svc_answer_size(13)
    got = bs.parse_sloop_svc(result.pending_send)
    assert got == {"returned": True,
                   "calls": [(0x4D, (1, 0xA1, 0xA2, 0x4D)), (0x4D, (2, 0xA1, 0xA2, 0x4D)),
                             (0x53, (3, 0xA1, 0xA2, 0x53))],
                   "data": b"what the ****"}


def test_r1_can_carry_the_copy_and_r0_keeps_its_word():
    code = bs.build_sloop_svc(0x53, (0x1234, 0, 0x55, 0x66), b"x", flags=bs.SLOOP_R1_IS_DATA)
    machine = bs._Machine(code)                 # an unmodelled swi leaves every register alone
    got = bs.parse_sloop_svc(machine.call().pending_send)
    assert got["calls"] == [(0x53, (0x1234, COPY, 0x55, 0x66))]


@pytest.mark.parametrize("numbers, kwargs, match", [
    ([0x48], {}, "flash-write"),
    ([0x53, 0x4C], {"unsafe": True}, "flash-write"),
    ([0x57], {}, "write-unsafe"),
    ([0x4D], {}, "rewrites the string"),
    ([0x30], {}, "not a Sloop syscall"),
    ([0x53] * 9, {}, "numbers per session"),
])
def test_the_numbers_that_reach_beyond_the_session_are_refused(numbers, kwargs, match):
    with pytest.raises(bs.BufferScriptError, match=match):
        bs.build_sloop_svc(numbers, (0x0203FC00,), **kwargs)


def test_the_config_path_builds_the_patched_image_and_sizes_the_answer():
    payload = configmod.BufferScriptPayload(
        script=bs.SLOOP_SVC, svc_numbers=(0x4D, 0x54), svc_data=b"hello",
        svc_data_in=bs.SLOOP_R0_IS_DATA)
    code = payload.build_code()
    assert code == bs.build_sloop_svc([0x4D, 0x54], (), b"hello", flags=bs.SLOOP_R0_IS_DATA)
    assert payload.dump_size == bs.sloop_svc_answer_size(5)
    assert bs.describe(code).startswith("sloop-svc")


def test_a_bkpt_goes_out_as_a_thumb_bkpt_and_the_rfu_slot_is_refused():
    code = bs.build_sloop_svc(bs.SLOOP_BKPT_APP, (1, 2, 3, 4), unsafe=True, bkpt=True)
    machine = bs._Machine(code)
    got = bs.parse_sloop_svc(machine.call().pending_send)
    assert machine.bkpts == [0xFF]
    assert got["calls"] == [(0xFF, (1, 2, 3, 4))]
    with pytest.raises(bs.BufferScriptError, match="re-keys"):
        bs.build_sloop_svc(bs.SLOOP_BKPT_RFU, unsafe=True, bkpt=True)
    with pytest.raises(bs.BufferScriptError, match="write-unsafe"):
        bs.build_sloop_svc(bs.SLOOP_BKPT_APP, bkpt=True)

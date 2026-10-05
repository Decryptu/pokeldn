"""The noclip hook installed through each cartridge's own client, then judged by the cartridge's own
MapGridGetCollisionAt and MapGridGetElevationAt [fieldmap.c:347, 357]."""

import pytest

from pokeldn.frlg.rom import buffer_script as bs, builds, native_script as ns
from tests.test_frlg_english_cartridges import BIOS_SIZE, STOP, _client_frame, _console, _image, _payload

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

# (build, image, MapGridGetElevationAt, MapGridGetCollisionAt)
CARTRIDGES = [
    (builds.BPRS, "scratchpad/frlg_es/FireRed_s.gba", 0x0805C658, 0x0805C6D8),
    (builds.BPRF, "scratchpad/FireRed_f.gba", 0x0805C644, 0x0805C6C4),
    (builds.BPGF, "scratchpad/LeafGreen_f.gba", 0x0805C644, 0x0805C6C4),
    (builds.BPRE, "scratchpad/frlg_en/FireRed_e.gba", 0x0805C4E8, 0x0805C568),
    (builds.BPGE, "scratchpad/frlg_en/LeafGreen_e.gba", 0x0805C4E8, 0x0805C568),
]
GRID = 0x02031DF8                   # gBackupMapData
MAP_HEADER = 0x02036DF8             # gMapHeader; .mapLayout first
AVATAR = 0x02037074                 # gPlayerAvatar; objectEventId at +5
OBJECTS = 0x02036E34                # gObjectEvents; currentCoords at +0x10
SIZE = 20
WALL = 0x3405                       # metatile 5, collision 1, elevation 3
FLOOR = 0x3001                      # metatile 1, elevation 3
UNDEFINED = 0x03FF                  # MAPGRID_UNDEFINED
R, L = 0x100, 0x200


def _grid():
    grid = [WALL] * (SIZE * SIZE)
    grid[10 + SIZE * 10] = FLOOR
    grid[9 + SIZE * 10] = UNDEFINED
    return grid


@pytest.fixture(params=CARTRIDGES, ids=lambda c: c[0].game_code)
def console(request):
    from unicorn import arm_const as a
    build, path, elevation_at, collision_at = request.param
    machine = _console(_payload(build, script=bs.INSTALL_RESIDENT, resident_name="noclip",
                                write_unsafe=True), build, _image(path))
    assert _client_frame(machine, build)[1] == build.vblank_intr | 1
    uc = machine.uc
    uc.mem_map(0, BIOS_SIZE)
    uc.mem_write(build.gmain + 4, (build.cb2_overworld | 1).to_bytes(4, "little"))
    uc.mem_write(build.intr_check, b"\x00\x00")
    uc.mem_write(build.vmap, b"".join(v.to_bytes(4, "little") for v in (SIZE, SIZE, GRID)))
    uc.mem_write(GRID, b"".join(v.to_bytes(2, "little") for v in _grid()))
    uc.mem_write(MAP_HEADER, (0x08400000).to_bytes(4, "little"))
    uc.mem_write(AVATAR + 5, b"\x00")

    def call(function, *args):
        for register, value in zip((a.UC_ARM_REG_R0, a.UC_ARM_REG_R1), args):
            uc.reg_write(register, value)
        uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
        uc.emu_start(function, STOP, count=2_000_000)
        assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
        return uc.reg_read(a.UC_ARM_REG_R0)

    class Console:
        def frame(self, x, y, keys):
            uc.mem_write(OBJECTS + 0x10, x.to_bytes(2, "little") + y.to_bytes(2, "little"))
            uc.mem_write(build.gmain + 0x2C, keys.to_bytes(2, "little"))
            uc.mem_write(build.intr_check, b"\x00\x00")  # WaitForVBlank's; VBlankIntr sets it
            call(int.from_bytes(uc.mem_read(build.intr_vblank, 4), "little"))

        def tile(self, x, y):
            """-> (collision, elevation) as the cartridge reads them."""
            return call(collision_at | 1, x, y) & 0xFF, call(elevation_at | 1, x, y) & 0xFF

        def block(self, x, y):
            return int.from_bytes(uc.mem_read(GRID + 2 * (x + SIZE * y), 2), "little")

        def set_block(self, x, y, value):
            uc.mem_write(GRID + 2 * (x + SIZE * y), value.to_bytes(2, "little"))

        def grid(self):
            raw = uc.mem_read(GRID, 2 * SIZE * SIZE)
            return [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]

        def help_disabled(self):
            return uc.mem_read(0x0203F171, 1)[0]

        def map_changes(self):
            uc.mem_write(MAP_HEADER, (0x08400100).to_bytes(4, "little"))

    assert int.from_bytes(uc.mem_read(build.intr_vblank, 4), "little") == ns.RESIDENT_BASE | 1
    return Console()


def test_held_r_opens_the_four_walls_and_letting_go_closes_them(console):
    assert console.tile(11, 10) == (1, 3)
    console.frame(10, 10, R)
    assert [console.tile(x, y) for x, y in ((11, 10), (10, 9), (10, 11))] == [(0, 15)] * 3
    assert console.tile(9, 10) == (1, 0) and console.block(9, 10) == UNDEFINED  # the map's edge
    assert console.tile(12, 10) == (1, 3) and console.help_disabled() == 1
    console.frame(11, 10, R)                            # a step into the wall
    assert console.tile(10, 9) == (1, 3) and console.tile(11, 10) == (1, 3)
    assert [console.tile(x, y) for x, y in ((12, 10), (11, 9), (11, 11), (10, 10))] == [(0, 15)] * 4
    console.frame(11, 10, R | L)                        # more buttons still hold R
    assert console.tile(12, 10) == (0, 15)
    console.frame(11, 10, L)
    assert console.grid() == _grid()


def test_a_block_the_game_rewrote_or_a_new_map_is_left_alone(console):
    console.frame(10, 10, R)
    console.set_block(11, 10, 0x3007)                   # the game's own metatile change
    console.frame(10, 10, 0)
    assert console.block(11, 10) == 0x3007 and console.block(10, 11) == WALL
    console.frame(10, 10, R)
    console.map_changes()                               # a warp: a new layout under the same grid
    console.frame(10, 10, 0)
    assert console.block(10, 11) == 0xF005

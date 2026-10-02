"""The follower hook on each cartridge's own code: install-kept puts it in gIntrTable[4], and every
frame it reads the lead through the game's GetMonData, draws the cartridge's own overworld frame or
the game's party icon, and keeps it a tile behind the player. docs/frlg_rom.md, `follower`."""

import pathlib

import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import builds
from pokeldn.frlg.save.mevent_pokemon import build_party_mon
from pokeldn.frlg.text import charmap

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

CARTRIDGES = {"BPRF": "scratchpad/FireRed_f.gba", "BPGF": "scratchpad/LeafGreen_f.gba",
              "BPRE": "scratchpad/frlg_en/FireRed_e.gba", "BPGE": "scratchpad/frlg_en/LeafGreen_e.gba"}
STOP = 0x02030000
STUB = 0x02030100                       # the game's VBlankIntr, stood in for by `bx lr`
PARTY = 0x02024280
AVATAR, OBJECTS, SPRITES = 0x02037074, 0x02036E34, 0x0202063C
COORD_OFFSET, PALETTE_FADE = 0x02021BC8, 0x02037AB4
OBJ_TILE_1008, OBJ_PALETTE_15 = 0x06017E00, 0x020379D4
OFFSET_X, OFFSET_Y = 0, -40             # gSpriteCoordOffsetX/Y as a town map leaves them
ANCHOR_X, ANCHOR_Y = -40, -48           # sprite = 16 * tile + anchor, measured on mGBA
HIDDEN = 0x0200                         # attr0 with affine off and bit 9: not displayed
OBJ_PALETTE_15_UNFADED = OBJ_PALETTE_15 - 0x400
NEW_KEYS = 0x2E                         # gMain.newKeys [include/main.h]


def word(data, at):
    return int.from_bytes(data[at - 0x08000000:at - 0x08000000 + 4], "little")


class World:
    """One cartridge's RAM around the installed hook; `frame` runs it once."""

    def __init__(self, code, species):
        from unicorn import arm_const
        self.arm = arm_const
        path = pathlib.Path(CARTRIDGES[code])
        if not path.exists():
            pytest.skip("no cartridge image on this machine")
        self.rom = path.read_bytes()
        self.build = builds.for_game_code(code)
        kept = bytes(0xB20) + bs.build_resident_save_blob("follower", build=self.build)
        machine = bs._Machine(bs.build_install_kept(self.build), rom=self.rom, sav2=kept,
                              build=self.build, memory={
                                  self.build.intr_vblank: (STUB | 1).to_bytes(4, "little"),
                                  STUB: b"\x70\x47"})
        assert machine.call().param == STUB | 1
        self.uc = machine.uc
        self.hook = int.from_bytes(self.uc.mem_read(self.build.intr_vblank, 4), "little")
        gmain = self.build.gmain
        self.put(gmain + 4, (self.build.cb2_overworld | 1).to_bytes(4, "little"))
        self.put(gmain + 0x1C, b"\x00\x00")                 # intrCheck: the main loop is idle
        self.put(PALETTE_FADE + 6, b"\x00\x00")
        self.put(AVATAR, bytes([1, 0, 0, 0, 0, 0]))         # on foot, sprite 0, object 0
        self.put(SPRITES + 4, (0x0800).to_bytes(2, "little"))   # the player's priority 2
        self.put(COORD_OFFSET, OFFSET_X.to_bytes(2, "little", signed=True)
                 + OFFSET_Y.to_bytes(2, "little", signed=True))
        self.put(PARTY, build_party_mon(species, 50, nickname="LEAD",
                                        language=self.build.language_id).raw)
        self.oam = self.build.last_oam
        self.put(self.oam, b"\xEE" * 6)
        self.ax, self.ay = ANCHOR_X, ANCHOR_Y

    def put(self, address, data):
        self.uc.mem_write(address, bytes(data))

    def stand(self, x, y, direction=1):
        self.place((x, y), (x, y), 16 * x + self.ax, 16 * y + self.ay, direction)

    def place(self, current, previous, sprite_x, sprite_y, direction):
        coords = b"".join(v.to_bytes(2, "little", signed=True) for v in (*current, *previous))
        self.put(OBJECTS + 0x10, coords)
        self.put(OBJECTS + 0x18, bytes([direction << 4 | direction]))
        self.put(SPRITES + 0x20, sprite_x.to_bytes(2, "little", signed=True)
                 + sprite_y.to_bytes(2, "little", signed=True))
        self.frame()

    def frame(self):
        a = self.arm
        self.uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        self.uc.reg_write(a.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(self.hook, STOP, count=100000)
        assert self.uc.reg_read(a.UC_ARM_REG_PC) == STOP

    def walk(self, start, step, direction, frames=16):
        """A walking step from tile `start` by `step`, one pixel a frame, as the player's object."""
        (x, y), (dx, dy) = start, step
        target = (x + dx, y + dy)
        for i in range(1, frames):
            self.place(target, start, 16 * x + self.ax + dx * i, 16 * y + self.ay + dy * i,
                       direction)
        self.stand(*target, direction)

    def entry(self):
        a0, a1, a2 = (int.from_bytes(self.uc.mem_read(self.oam + i, 2), "little") for i in (0, 2, 4))
        return a0, a1, a2

    def player_oam(self):
        x, y = (int.from_bytes(self.uc.mem_read(SPRITES + 0x20 + i, 2), "little", signed=True)
                for i in (0, 2))
        return x - 8 + OFFSET_X, y - 16 + OFFSET_Y              # 16x32, centre to corner

    def tiles(self, size):
        return bytes(self.uc.mem_read(OBJ_TILE_1008, size))

    def palette(self):
        return bytes(self.uc.mem_read(OBJ_PALETTE_15, 32))

    def overworld_frame(self, gfx, frame):
        info = word(self.rom, self.build.obj_gfx_info + 4 * gfx)
        image = word(self.rom, info + 0x1C) + 8 * frame
        data, size = word(self.rom, image), word(self.rom, image + 4) & 0xFFFF
        return self.rom[data - 0x08000000:data - 0x08000000 + size]

    def overworld_palette(self, gfx):
        info = word(self.rom, self.build.obj_gfx_info + 4 * gfx)
        tag = int.from_bytes(self.rom[info - 0x08000000 + 2:info - 0x08000000 + 4], "little")
        table = self.build.obj_palettes - 0x08000000
        for i in range(0, 0x100, 8):
            if int.from_bytes(self.rom[table + i + 4:table + i + 6], "little") == tag:
                data = word(self.rom, self.build.obj_palettes + i)
                return self.rom[data - 0x08000000:data - 0x08000000 + 32]
        raise AssertionError(f"no palette for tag {tag:#x}")


@pytest.mark.parametrize("code", CARTRIDGES)
def test_pikachu_walks_one_tile_behind_on_its_own_frames(code):
    world = World(code, 25)
    world.stand(10, 10)
    world.stand(10, 10)
    assert world.entry()[0] == HIDDEN                       # nothing before the first step
    world.walk((10, 10), (0, -1), 2)                         # north
    a0, a1, a2 = world.entry()
    px, py = world.player_oam()
    assert a1 & 0x1FF == px                                 # the same column
    assert (a0 & 0xFF) + 16 == py + 32 + 16                 # its feet on the tile below the player's
    assert a1 >> 14 == 1 and a0 >> 14 == 0                  # 16x16, square
    assert a2 == 0xF3F0 | 0x0800                            # tile 1008, palette 15, priority 2
    assert world.tiles(0x80) == world.overworld_frame(120, 1)       # standing, facing north
    assert world.palette() == world.overworld_palette(120)

    world.place((9, 9), (10, 9), 16 * 10 + ANCHOR_X - 4, 16 * 9 + ANCHOR_Y, 3)   # 4 px into a west step
    # It walks the player's previous step, north: a walking frame facing north, not flipped.
    assert world.tiles(0x80) in (world.overworld_frame(120, 5), world.overworld_frame(120, 6))
    a0, a1, _ = world.entry()
    assert not a1 & 0x1000
    px, py = world.player_oam()
    assert (a1 & 0x1FF, a0 & 0xFF) == (px + 4, py + 32 - 4)  # 4 px up from the tile below


@pytest.mark.parametrize("code", ["BPRF", "BPRE"])
def test_a_species_without_an_overworld_sprite_follows_as_its_party_icon(code):
    world = World(code, 9)                                  # Blastoise
    world.stand(10, 10, 4)
    world.walk((10, 10), (1, 0), 4)                         # east
    world.walk((11, 10), (1, 0), 4)
    a0, a1, _ = world.entry()
    assert a1 >> 14 == 2                                    # 32x32
    assert a1 & 0x1000                                      # walking east: the icon flipped
    px, py = world.player_oam()
    assert (a1 & 0x1FF) + 16 == px + 8 - 16                 # centred on the tile to the west
    assert (a0 & 0xFF) + 32 == py + 32                      # its bottom on the tile's
    a = world.arm
    world.uc.reg_write(a.UC_ARM_REG_R0, 9)
    world.uc.reg_write(a.UC_ARM_REG_R1, int.from_bytes(world.uc.mem_read(PARTY, 4), "little"))
    world.uc.reg_write(a.UC_ARM_REG_R2, 0)
    world.uc.reg_write(a.UC_ARM_REG_LR, STOP)
    world.uc.emu_start(world.build.get_mon_icon | 1, STOP, count=10000)
    icon = world.uc.reg_read(a.UC_ARM_REG_R0)
    assert world.tiles(0x200) == world.rom[icon - 0x08000000:icon - 0x08000000 + 0x200]
    index = world.rom[world.build.mon_icon_pal_indices - 0x08000000 + 9]
    at = world.build.mon_icon_palettes - 0x08000000 + 32 * index
    assert world.palette() == world.rom[at:at + 32]


def test_a_warp_starts_over_and_the_next_step_walks_in_from_behind():
    world = World("BPRF", 25)
    world.stand(10, 10)
    world.walk((10, 10), (0, 1), 1)                         # south
    world.put(world.oam, b"\xEE" * 6)
    world.stand(16, 14)                                     # a warp: every coordinate elsewhere
    world.stand(16, 14)
    assert world.entry()[0] == HIDDEN
    world.place((16, 15), (16, 14), 16 * 16 + ANCHOR_X, 16 * 14 + ANCHOR_Y + 1, 1)  # first pixel south
    a0, a1, _ = world.entry()
    px, py = world.player_oam()
    assert a1 & 0x1FF == px
    assert (a0 & 0xFF) + 16 == py + 32 - 16                 # a tile behind the player, both a pixel on


def test_a_map_connection_keeps_it_one_tile_behind():
    """A connection adds the maps' offset to every object's coordinates; the sprites stay put."""
    world = World("BPRF", 25)
    world.stand(20, 9, 2)
    world.walk((20, 9), (0, -1), 2)                         # north, to (20, 8)
    shift = 39
    world.ay -= 16 * shift
    world.walk((20, 8 + shift), (0, -1), 2)                 # the step across, in the new map's numbers
    a0, a1, _ = world.entry()
    px, py = world.player_oam()
    assert a1 & 0x1FF == px
    assert (a0 & 0xFF) + 16 == py + 32 + 16


@pytest.mark.parametrize("code, gfx", [("BPRF", 149), ("BPGF", 148), ("BPRE", 149), ("BPGE", 148)])
def test_deoxys_follows_in_its_versions_forme(code, gfx):
    world = World(code, 410)                                # Attack on FireRed, Defense on LeafGreen
    world.stand(10, 10)
    world.walk((10, 10), (0, -1), 2)
    a0, a1, _ = world.entry()
    assert a1 >> 14 == 2                                    # 32x32
    assert world.tiles(0x200) == world.overworld_frame(gfx, 1)


def test_a_fade_darkens_it_and_a_black_screen_stays_black():
    """The palette goes to gPlttBufferUnfaded every frame, to gPlttBufferFaded only at blend y 0: a
    finished fade-out clears `active` with y 16 [palette.c], and the follower used to light up."""
    world = World("BPRF", 25)
    world.stand(10, 10)
    world.walk((10, 10), (0, -1), 2)
    colours = world.overworld_palette(120)
    for y, faded in ((16, False), (8, False), (0, True)):
        world.put(OBJ_PALETTE_15, b"\0" * 32)
        world.put(OBJ_PALETTE_15_UNFADED, b"\0" * 32)
        world.put(PALETTE_FADE + 4, (y << 6 | y << 11).to_bytes(2, "little"))
        world.stand(10, 9, 2)
        assert bytes(world.uc.mem_read(OBJ_PALETTE_15_UNFADED, 32)) == colours
        assert world.palette() == (colours if faded else b"\0" * 32)


def test_a_ledge_arc_is_replayed_on_the_next_step():
    """FRLG jumps a ledge as two one-tile steps with the arc in the player sprite's y2; the
    follower walks each of those steps one step later, with the same y2 by progress."""
    world = World("BPRF", 25)
    world.stand(10, 10, 1)
    world.walk((10, 10), (0, 1), 1)
    arc = [-4, -6, -8, -10, -11, -12, -12, -12, -12, -11, -10, -9, -8, -6, -4]
    for i, y2 in enumerate(arc, 1):                         # the player's step, 11 -> 12
        world.put(SPRITES + 0x26, y2.to_bytes(2, "little", signed=True))
        world.place((10, 12), (10, 11), 16 * 10 + ANCHOR_X, 16 * 11 + ANCHOR_Y + i, 1)
    world.put(SPRITES + 0x26, b"\0\0")
    world.stand(10, 12, 1)
    tops = []
    for i in range(1, 16):                                  # the next step: the follower, 11 -> 12
        world.place((10, 13), (10, 12), 16 * 10 + ANCHOR_X, 16 * 12 + ANCHOR_Y + i, 1)
        _, py = world.player_oam()
        tops.append(((world.entry()[0] - py + 128) & 0xFF) - 128)   # its top less the player's
    assert tops == arc


@pytest.mark.parametrize("code", CARTRIDGES)
def test_a_facing_it_runs_the_cry_and_the_line(code):
    world = World(code, 25)
    calls = []
    world.uc.hook_add(__import__("unicorn").UC_HOOK_CODE,
                      lambda uc, address, size, data: calls.append(uc.reg_read(world.arm.UC_ARM_REG_R0)),
                      begin=world.build.setup_script, end=world.build.setup_script)
    world.stand(10, 10, 1)
    world.walk((10, 10), (0, 1), 1)                         # south: it stands north of the player
    world.put(world.build.gmain + NEW_KEYS, b"\x01\x00")    # A
    world.stand(10, 11, 1)                                  # facing away
    assert not calls
    world.put(OBJECTS + 0x18, bytes([1 << 4 | 2]))           # turned north, in place
    world.frame()
    assert len(calls) == 1
    script = bytes(world.uc.mem_read(calls[0], 20))
    assert script[0] == 0x69 and script[5] == 0xA1 and script[11] == 0x67     # lockall, cry, message
    assert int.from_bytes(script[6:8], "little") == 25
    text = int.from_bytes(script[12:16], "little")
    line = bytes(world.uc.mem_read(text, 20))
    first = bs.FOLLOWER_TEXT[world.build.language][0]
    assert line.startswith(b"\xFD\x02") and charmap.decode(line[2:]).startswith(" " + first)
    smiley = world.build.emoticons + 11 * 0x80
    world.put(world.build.gmain + NEW_KEYS, b"\x00\x00")
    world.frame()
    assert bytes(world.uc.mem_read(OBJ_TILE_1008 - 0x80, 0x80)) == world.rom[
        smiley - 0x08000000:smiley - 0x08000000 + 0x80]
    a0, a1, a2 = (int.from_bytes(world.uc.mem_read(world.oam - 8 + i, 2), "little") for i in (0, 2, 4))
    f0, f1, _ = world.entry()
    assert (a0 & 0xFF, a1, a2) == ((f0 - 16) & 0xFF, 0x4000 | f1 & 0x1FF, 0x3EC | 0x0800)

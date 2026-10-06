"""The follower hook on each cartridge's own code, as install-kept installs it: on an idle overworld
frame it spawns an object event of local id 0xF0 with the lead's sprite (or Snorlax's frame wearing
the lead's icon), moves it with the game's movement actions, jumps a ledge only after the player
steps off the landing tile, and runs its script when A is pressed facing it. The game's object
functions are stood in for and their calls recorded. docs/frlg_rom.md, `follower`."""

import pathlib
import struct

import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import builds
from pokeldn.frlg.save.mevent_pokemon import build_party_mon
from pokeldn.frlg.text import charmap

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

CARTRIDGES = {code: f"scratchpad/frlg_languages/{'FireRed' if b.version == 'firered' else 'LeafGreen'}_{code[3].lower()}.gba"
              for code, b in builds.BUILDS.items()}
STOP = 0x02030000
STUB = 0x02030100                       # the game's VBlankIntr, stood in for by `bx lr`
PARTY, AVATAR, OBJECTS, SPRITES = 0x02024280, 0x02037074, 0x02036E34, 0x0202063C
LOCKED, SCRIPT_STATUS = 0x0300109C, 0x03000FA8
FOLLOW_ID = 0xF0
WALK_NORMAL, JUMP_2, WALK_FASTER = 0x10, 0x14, 0x35     # MOVEMENT_ACTION_*_DOWN


class World:
    def __init__(self, code, species):
        from unicorn import UC_HOOK_CODE, arm_const
        self.arm = arm_const
        path = pathlib.Path(CARTRIDGES[code])
        if not path.exists():
            pytest.skip("no cartridge image on this machine")
        self.rom = path.read_bytes()
        self.build = b = builds.for_game_code(code)
        self.party = b.ewram.get("party", PARTY)
        self.avatar = b.ewram.get("avatar", AVATAR)
        self.objects = b.ewram.get("objects", OBJECTS)
        self.sprites = b.ewram.get("sprites", SPRITES)
        kept = bytes(0xB20) + bs.build_resident_save_blob("follower", build=b)
        machine = bs._Machine(bs.build_install_kept(b), rom=self.rom, sav2=kept, build=b, memory={
            b.intr_vblank: (STUB | 1).to_bytes(4, "little"), STUB: b"\x70\x47"})
        assert machine.call().param == STUB | 1
        self.uc = uc = machine.uc
        self.hook = self.word(b.intr_vblank)
        self.put(b.gmain + 4, (b.cb2_overworld | 1).to_bytes(4, "little"))
        self.put(b.gmain + 0x1C, b"\x00\x00")
        self.put(self.avatar, bytes([0, 0, 0, 0, 0, 0]))           # on foot, object 0
        self.put(self.party, build_party_mon(species, 50, nickname="LEAD",
                                        language=b.language_id).raw)
        self.put(LOCKED, b"\x00")
        self.put(SCRIPT_STATUS, b"\x02")                       # CONTEXT_SHUTDOWN
        self.calls = []
        stubs = {b.spawn_object: self._spawn, b.set_held_movement: self._held,
                 b.clear_held_movement: lambda: None, b.move_object_to: self._move,
                 b.remove_object: self._remove, b.setup_script: self._script}
        for address, fake in stubs.items():
            uc.hook_add(UC_HOOK_CODE, self._stub(fake), begin=address, end=address)
        self.player((10, 10), (10, 10), 1)

    def _stub(self, fake):
        def run(uc, address, size, data):
            a = self.arm
            result = fake()
            uc.reg_write(a.UC_ARM_REG_R0, 0 if result is None else result)
            uc.reg_write(a.UC_ARM_REG_PC, uc.reg_read(a.UC_ARM_REG_LR))
        return run

    def reg(self, n):
        return self.uc.reg_read(getattr(self.arm, f"UC_ARM_REG_R{n}"))

    def _spawn(self):
        sp = self.uc.reg_read(self.arm.UC_ARM_REG_SP)
        y, _elevation = struct.unpack("<II", self.uc.mem_read(sp, 8))
        self.calls.append(("spawn", self.reg(0), self.reg(1), self.reg(2), self.reg(3), y))
        self.put(self.objects + 0x24, bytes([1, 0, 0, 0, 0, self.reg(0) & 0xFF, 0, 0, FOLLOW_ID]) +
                 bytes(7) + struct.pack("<hhhh", self.reg(3), y, self.reg(3), y) + bytes(12))
        return 1

    def _held(self):
        self.calls.append(("held", self.reg(1)))
        self.put(self.objects + 0x24, bytes([0x41]))               # active, held movement running

    def _move(self):
        self.calls.append(("move", self.reg(1), self.reg(2)))

    def _remove(self):
        self.calls.append(("remove",))
        self.put(self.objects + 0x24, b"\x00")

    def _script(self):
        self.calls.append(("script", self.reg(0)))

    def put(self, address, data):
        self.uc.mem_write(address, bytes(data))

    def word(self, address):
        return int.from_bytes(self.uc.mem_read(address, 4), "little")

    def player(self, current, previous, facing, action=WALK_NORMAL, moving=None):
        moving = facing if moving is None else moving
        self.put(self.objects, bytes([1, 0, 0, 0, 0, 0, 0, 0, 0xFF]))
        self.put(self.objects + 0x10, struct.pack("<hhhh", *current, *previous))
        self.put(self.objects + 0x18, bytes([moving << 4 | facing]))
        self.put(self.objects + 0x1C, bytes([action + moving - 1]))

    def finish(self):
        self.put(self.objects + 0x24, bytes([0x81]))               # active, held movement finished

    def frame(self):
        a = self.arm
        self.uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        self.uc.reg_write(a.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(self.hook, STOP, count=200000)
        assert self.uc.reg_read(a.UC_ARM_REG_PC) == STOP

    def follower_at(self, x, y):
        self.put(self.objects + 0x24 + 0x10, struct.pack("<hhhh", x, y, x, y))

    def held(self):
        return [call[1] for call in self.calls if call[0] == "held"]


@pytest.mark.parametrize("code", CARTRIDGES)
def test_chansey_spawns_with_its_sprite_and_walks_the_players_steps(code):
    world = World(code, 113)
    world.frame()
    assert world.calls[0] == ("spawn", 117, 0, FOLLOW_ID, 10, 10)  # OBJ_EVENT_GFX_CHANSEY
    assert world.uc.mem_read(world.objects + 0x24 + 0x0B, 1)[0] & 0x0F == 14    # NO_ELEVATION
    world.player((10, 11), (10, 10), 1)                     # a step south: shown where it spawned
    world.frame()
    assert world.held() == []
    world.player((10, 12), (10, 11), 1)
    world.frame()
    assert world.held() == [WALK_NORMAL]                    # down, onto the tile left


@pytest.mark.parametrize("code", ["BPRF", "BPRE"])
def test_a_species_without_a_sprite_wears_its_icon_on_snorlaxs_frame(code):
    world = World(code, 9)                                  # Blastoise
    world.frame()
    assert world.calls[0][1] == 109                         # OBJ_EVENT_GFX_SNORLAX
    a = world.arm
    world.uc.reg_write(a.UC_ARM_REG_R0, 9)
    world.uc.reg_write(a.UC_ARM_REG_R1, world.word(world.party))
    world.uc.reg_write(a.UC_ARM_REG_R2, 0)
    world.uc.reg_write(a.UC_ARM_REG_LR, STOP)
    world.uc.emu_start(world.build.get_mon_icon | 1, STOP, count=10000)
    icon = world.uc.reg_read(a.UC_ARM_REG_R0)
    table = 0x0203FBB4
    frames = [struct.unpack("<II", world.uc.mem_read(table + 8 * i, 8)) for i in range(9)]
    assert frames == [(icon, 0x200)] * 3 + [(icon + 0x200, 0x200)] * 6
    assert world.word(world.sprites + 0x0C) == table              # the follower's sprite reads it
    assert world.uc.mem_read(world.sprites + 5, 1)[0] >> 4 == 15  # on OBJ palette 15
    index = world.rom[world.build.mon_icon_pal_indices - 0x08000000 + 9]
    at = world.build.mon_icon_palettes - 0x08000000 + 32 * index
    assert bytes(world.uc.mem_read(0x020375D4, 32)) == world.rom[at:at + 32]


def test_a_ledge_jump_waits_for_the_player_to_step_off_the_landing_tile():
    world = World("BPRF", 113)
    world.frame()
    world.player((10, 11), (10, 10), 1)                     # shown on 10,10
    world.frame()
    world.player((10, 12), (10, 11), 1, action=JUMP_2)      # the jump, first tile
    world.frame()
    world.frame()                                           # it walks to the edge, 10,11
    world.follower_at(10, 11)
    world.finish()
    world.player((10, 13), (10, 12), 1, action=JUMP_2)      # the jump, second tile
    world.frame()
    world.player((10, 13), (10, 13), 1)                     # landed, standing
    for _ in range(3):
        world.frame()
    assert world.held() == [WALK_NORMAL]                    # it waits at the top
    world.player((10, 14), (10, 13), 1)                     # off the landing tile
    world.frame()
    assert world.held()[-1] == JUMP_2                       # down the ledge, two tiles
    world.follower_at(10, 13)
    world.player((10, 15), (10, 14), 1)
    world.frame()
    world.player((10, 16), (10, 15), 1)
    world.frame()
    world.finish()
    world.frame()
    assert world.held()[-1] == WALK_FASTER                  # it fell behind: no second jump


@pytest.mark.parametrize("code", CARTRIDGES)
def test_a_facing_it_runs_the_cry_the_smile_and_the_line(code):
    world = World(code, 25)
    world.frame()
    world.player((10, 11), (10, 10), 1)
    world.frame()
    world.follower_at(10, 10)
    world.finish()
    world.player((10, 11), (10, 11), 2)                     # turned north, facing it
    world.put(world.build.gmain + 0x2E, b"\x01\x00")          # A
    world.frame()
    script_at = [call[1] for call in world.calls if call[0] == "script"]
    assert len(script_at) == 1
    script = bytes(world.uc.mem_read(script_at[0], 31))
    assert script[:2] == b"\x6A\xA1" and int.from_bytes(script[2:4], "little") == 25
    assert script[6:9] == b"\x5A\x4F" + bytes([FOLLOW_ID])    # faceplayer, applymovement 0xF0
    smile = int.from_bytes(script[10:14], "little")
    assert bytes(world.uc.mem_read(smile, 2)) == b"\x66\xFE"  # MOVEMENT_ACTION_EMOTE_SMILE
    text = int.from_bytes(script[23:27], "little")
    line = bytes(world.uc.mem_read(text, 20))
    first = bs.FOLLOWER_TEXT[world.build.language][0]
    assert line.startswith(b"\xFD\x02") and charmap.decode(line[2:]).startswith(" " + first)
    assert world.uc.mem_read(world.build.selected_object, 1)[0] == 1   # lock, faceplayer: it


def test_a_menu_removes_it_so_no_save_keeps_it():
    world = World("BPRF", 113)
    world.frame()
    world.put(LOCKED, b"\x01")                              # the start menu: locked, no script
    world.frame()
    assert ("remove",) in world.calls

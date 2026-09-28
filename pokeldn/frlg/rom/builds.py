"""The build-dependent addresses of the four FireRed/LeafGreen cartridges the host sends code to.

A payload, a hook or a field stub that names an IWRAM or ROM address is built for one cartridge,
chosen by the game code the console sends in its Mystery Gift game data [mystery_gift.c:369].
EWRAM is the same on all four and stays a module constant where it is used.

French values are the ones `rom_map` records off the consoles; French LeafGreen's are its measured
twins [leafgreen_twins, rom_map.LEAFGREEN]. English values are the decomp's symbols, checked
against the retail English images by bytes and by literal pools. docs/frlg_rom_map.md, The
English cartridges.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

from pokeldn.frlg.rom import rom_map

LANGUAGE_ENGLISH = 2                # include/constants/global.h:21-27
LANGUAGE_FRENCH = 3


class UnknownBuild(KeyError):
    """A game code with no table here: nothing build-dependent may be sent to it."""


@dataclass(frozen=True)
class Build:
    game_code: str                  # the ROM header's, as the console sends it
    version: str                    # "firered" or "leafgreen"
    language: str                   # "french" or "english"
    language_id: int                # gGameLanguage, what CreateMon writes into a Pokemon
    # IWRAM
    rng: int                        # gRngValue
    sb1ptr: int                     # gSaveBlock1Ptr
    sb2ptr: int                     # gSaveBlock2Ptr
    intr_vblank: int                # gIntrTable[4]
    gmain: int                      # gMain
    pcm_dma_counter: int            # gPcmDmaCounter
    sound_info: int                 # gSoundInfo
    last_written_sector: int        # gLastWrittenSector
    save_counter: int               # gSaveCounter
    # ROM functions, without the THUMB bit
    vblank_intr: int
    cb1_overworld: int
    cb2_overworld: int
    battle_cb1: int                 # BattleMainCB1
    battle_cb2: int                 # BattleMainCB2
    run_text_printers: int
    get_mon_data: int               # GetMonData3
    sound_main: int                 # m4aSoundMain
    create_mon: int
    random: int
    seed_rng: int
    read_flash: int
    client_run_buffer_script: int
    standard_wild_encounter: int
    get_header_id: int              # GetCurrentMapWildMonHeaderId
    # ROM data
    save_slot_layout: int           # sSaveSlotLayout
    enigma_desc: tuple              # sBerryDescriptionPart{1,2}_Enigma
    callable: MappingProxyType = field(repr=False)

    @property
    def name(self):
        return (f"{self.language.capitalize()} "
                f"{'FireRed' if self.version == 'firered' else 'LeafGreen'}")

    @property
    def intr_check(self):
        return self.gmain + 0x1C            # gMain.intrCheck [include/main.h:24]

    @property
    def overlay_oam(self):
        return self.gmain + 0x3F8           # gMain.oamBuffer[120] [include/main.h:38]

    @property
    def client_return(self):
        return self.client_run_buffer_script + 0x14     # after `bl _call_via_r3`

    def hook_literals(self):
        """-> {p_name: word} for every build address a resident hook may carry."""
        return {"intr_check": self.intr_check, "gmain": self.gmain,
                "overlay_oam": self.overlay_oam, "rng": self.rng, "sb2ptr": self.sb2ptr,
                "pcm_counter": self.pcm_dma_counter, "sound_info": self.sound_info,
                "cb2_overworld": self.cb2_overworld | 1, "cb1_overworld": self.cb1_overworld | 1,
                "cb1_battle": self.battle_cb1 | 1, "cb2_battle": self.battle_cb2 | 1,
                "run_text": self.run_text_printers | 1, "get_mon_data": self.get_mon_data | 1,
                "sound_main": self.sound_main | 1, "original": self.vblank_intr | 1}

    def callable_function(self, name):
        """-> the THUMB pointer for one of `callable`, by the decomp's name, case-insensitively."""
        for known, address in self.callable.items():
            if known.lower() == str(name).lower():
                return address | 1
        raise KeyError(f"{name!r} is not a function this project names on {self.game_code}; "
                       "known: " + ", ".join(sorted(self.callable)))


def _callable(**addresses):
    return MappingProxyType(dict(addresses))


BPRF = Build(
    game_code="BPRF", version="firered", language="french", language_id=LANGUAGE_FRENCH,
    rng=rom_map.GRNG_VALUE, sb1ptr=rom_map.GSAVEBLOCK1PTR, sb2ptr=rom_map.GSAVEBLOCK2PTR,
    intr_vblank=0x03002730, gmain=0x030022D0, pcm_dma_counter=0x03002F68,
    sound_info=0x03005F80, last_written_sector=0x030045A0, save_counter=0x030045B0,
    vblank_intr=0x0800071C, cb1_overworld=0x08059E48, cb2_overworld=0x08059EC8,
    battle_cb1=0x08015B6C, battle_cb2=0x08014888, run_text_printers=0x08002D50,
    get_mon_data=0x080432E4, sound_main=0x081DF53C, create_mon=rom_map.CREATE_MON,
    random=rom_map.RANDOM, seed_rng=rom_map.SEED_RNG, read_flash=rom_map.READ_FLASH,
    client_run_buffer_script=rom_map.CLIENT_RUN_BUFFER_SCRIPT,
    standard_wild_encounter=0x08086528, get_header_id=0x080861A0,
    save_slot_layout=0x083F58C4, enigma_desc=(0x083D5CE8, 0x083D5CF8),
    callable=MappingProxyType(dict(rom_map.CALLABLE)))

# French LeafGreen: FireRed's RAM; ROM past 0x0807CF68 moves by the measured segment deltas
# [rom_map.LEAFGREEN_DELTA_SEGMENTS]. Every value below is FireRed's bytes found at that address.
BPGF = Build(
    game_code="BPGF", version="leafgreen", language="french", language_id=LANGUAGE_FRENCH,
    rng=BPRF.rng, sb1ptr=BPRF.sb1ptr, sb2ptr=BPRF.sb2ptr, intr_vblank=BPRF.intr_vblank,
    gmain=BPRF.gmain, pcm_dma_counter=BPRF.pcm_dma_counter, sound_info=BPRF.sound_info,
    last_written_sector=BPRF.last_written_sector, save_counter=BPRF.save_counter,
    vblank_intr=BPRF.vblank_intr, cb1_overworld=BPRF.cb1_overworld,
    cb2_overworld=BPRF.cb2_overworld, battle_cb1=BPRF.battle_cb1, battle_cb2=BPRF.battle_cb2,
    run_text_printers=BPRF.run_text_printers, get_mon_data=BPRF.get_mon_data,
    sound_main=0x081DF518, create_mon=0x08041150, random=0x080486B0, seed_rng=0x080486D0,
    read_flash=0x081E0EC8, client_run_buffer_script=0x08148C3C,
    standard_wild_encounter=0x080864FC, get_header_id=0x08086174,
    save_slot_layout=0x083F5700, enigma_desc=(0x083D5B24, 0x083D5B34),
    callable=_callable(
        Random=0x080486B0, SeedRng=0x080486D0, CreateMon=0x08041150, VarGet=0x08071DDC,
        VarSet=0x08071DF8, GetVarPointer=0x08071CC8, AddBagItem=0x0809DA44,
        RemoveBagItem=0x0809DB98, CheckBagHasSpace=0x0809D9C0, CheckBagHasItem=0x0809D900,
        AddPCItem=0x0809DD88, FlagSet=0x08071EF4, FlagClear=0x08071F1C, FlagGet=0x08071F44,
        IncrementGameStat=0x080587A4, GetMoney=0x080A3738, IsEnoughMoney=0x080A3768,
        AddMoney=0x080A3780, RemoveMoney=0x080A37B8, CalcCRC16=0x080489A0, ReadFlash=0x081E0EC8,
        GetSetPokedexFlag=0x0808C834, SpeciesToNationalPokedexNum=0x08046994,
        CompactPartySlots=0x080971D0, ItemIsMail=0x0809BAEC, StringCompare=0x0800C938,
        InitRamScript=0x0806D5F0, RunScriptImmediately=0x0806D438))

# English FireRed: the decomp's pokefirered_switch.elf, which rebuilds the retail image byte for
# byte. IWRAM from gMain up moves +0xB0 against French, +0x110 from gSoundInfo up.
BPRE = Build(
    game_code="BPRE", version="firered", language="english", language_id=LANGUAGE_ENGLISH,
    rng=0x030042D0, sb1ptr=0x030042D8, sb2ptr=0x030042DC, intr_vblank=0x030027E0,
    gmain=0x03002380, pcm_dma_counter=0x03003018, sound_info=0x03006090,
    last_written_sector=0x03004650, save_counter=0x03004660,
    vblank_intr=0x08000734, cb1_overworld=0x08059CEC, cb2_overworld=0x08059D6C,
    battle_cb1=0x08015B80, battle_cb2=0x0801489C, run_text_printers=0x08002D68,
    get_mon_data=0x08043390, sound_main=0x081E07E8, create_mon=0x080411FC,
    random=0x08048670, seed_rng=0x08048690, read_flash=0x081E2198,
    client_run_buffer_script=0x0814895C, standard_wild_encounter=0x08086420,
    get_header_id=0x08086098, save_slot_layout=0x083FC758,
    enigma_desc=(0x083DD2C0, 0x083DD2D0),
    callable=_callable(
        Random=0x08048670, SeedRng=0x08048690, CreateMon=0x080411FC, VarGet=0x08071CD4,
        VarSet=0x08071CF0, GetVarPointer=0x08071BC0, AddBagItem=0x0809D7E8,
        RemoveBagItem=0x0809D93C, CheckBagHasSpace=0x0809D764, CheckBagHasItem=0x0809D6A4,
        AddPCItem=0x0809DB2C, FlagSet=0x08071DEC, FlagClear=0x08071E14, FlagGet=0x08071E3C,
        IncrementGameStat=0x08058648, GetMoney=0x080A34CC, IsEnoughMoney=0x080A34FC,
        AddMoney=0x080A3514, RemoveMoney=0x080A354C, CalcCRC16=0x08048960, ReadFlash=0x081E2198,
        GetSetPokedexFlag=0x0808C5D8, SpeciesToNationalPokedexNum=0x08046A40,
        CompactPartySlots=0x08096F40, ItemIsMail=0x0809B85C, StringCompare=0x0800C950,
        InitRamScript=0x0806D48C, RunScriptImmediately=0x0806D2D4))

# English LeafGreen: pokeleafgreen_switch.elf. RAM is English FireRed's.
BPGE = Build(
    game_code="BPGE", version="leafgreen", language="english", language_id=LANGUAGE_ENGLISH,
    rng=BPRE.rng, sb1ptr=BPRE.sb1ptr, sb2ptr=BPRE.sb2ptr, intr_vblank=BPRE.intr_vblank,
    gmain=BPRE.gmain, pcm_dma_counter=BPRE.pcm_dma_counter, sound_info=BPRE.sound_info,
    last_written_sector=BPRE.last_written_sector, save_counter=BPRE.save_counter,
    vblank_intr=BPRE.vblank_intr, cb1_overworld=BPRE.cb1_overworld,
    cb2_overworld=BPRE.cb2_overworld, battle_cb1=BPRE.battle_cb1, battle_cb2=BPRE.battle_cb2,
    run_text_printers=BPRE.run_text_printers, get_mon_data=BPRE.get_mon_data,
    sound_main=0x081E07C4, create_mon=0x080411FC, random=0x08048670, seed_rng=0x08048690,
    read_flash=0x081E2174, client_run_buffer_script=0x08148938,
    standard_wild_encounter=0x080863F4, get_header_id=0x0808606C,
    save_slot_layout=0x083FC594, enigma_desc=(0x083DD0FC, 0x083DD10C),
    callable=_callable(
        Random=0x08048670, SeedRng=0x08048690, CreateMon=0x080411FC, VarGet=0x08071CD4,
        VarSet=0x08071CF0, GetVarPointer=0x08071BC0, AddBagItem=0x0809D7BC,
        RemoveBagItem=0x0809D910, CheckBagHasSpace=0x0809D738, CheckBagHasItem=0x0809D678,
        AddPCItem=0x0809DB00, FlagSet=0x08071DEC, FlagClear=0x08071E14, FlagGet=0x08071E3C,
        IncrementGameStat=0x08058648, GetMoney=0x080A34A0, IsEnoughMoney=0x080A34D0,
        AddMoney=0x080A34E8, RemoveMoney=0x080A3520, CalcCRC16=0x08048960, ReadFlash=0x081E2174,
        GetSetPokedexFlag=0x0808C5AC, SpeciesToNationalPokedexNum=0x08046A40,
        CompactPartySlots=0x08096F14, ItemIsMail=0x0809B830, StringCompare=0x0800C950,
        InitRamScript=0x0806D48C, RunScriptImmediately=0x0806D2D4))

BUILDS = MappingProxyType({build.game_code: build for build in (BPRF, BPGF, BPRE, BPGE)})
DEFAULT = BPRF
GAME_CODES = tuple(BUILDS)


def for_game_code(code):
    """-> the Build for a header game code (str or bytes). UnknownBuild for any other."""
    if isinstance(code, (bytes, bytearray)):
        code = bytes(code).decode("ascii", "replace")
    try:
        return BUILDS[str(code).upper()]
    except KeyError:
        raise UnknownBuild(
            f"no address table for game code {code!r}; this host has "
            + ", ".join(GAME_CODES)) from None


def resolve(build):
    """-> a Build from a Build, a game code or None (the French FireRed default)."""
    if build is None:
        return DEFAULT
    if isinstance(build, Build):
        return build
    return for_game_code(build)


def for_version(version, language="french"):
    """-> the Build of `version` in `language`."""
    for build in BUILDS.values():
        if build.version == version and build.language == language:
            return build
    raise UnknownBuild(f"no {language} {version} build")

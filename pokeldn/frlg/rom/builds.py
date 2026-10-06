"""The build-dependent addresses of the FireRed/LeafGreen cartridges the host sends code to,
chosen by the game code in the console's Mystery Gift game data [mystery_gift.c:369]. Japanese
builds have their own EWRAM layout. docs/frlg_rom_map.md, The international revision 0x0A cartridges.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

from pokeldn.frlg.rom import rom_map

LANGUAGE_JAPANESE = 1
LANGUAGE_ENGLISH = 2                # include/constants/global.h:21-27
LANGUAGE_FRENCH = 3
LANGUAGE_ITALIAN = 4
LANGUAGE_GERMAN = 5
LANGUAGE_SPANISH = 7


class UnknownBuild(KeyError):
    """A game code with no table here: nothing build-dependent may be sent to it."""


@dataclass(frozen=True)
class Build:
    game_code: str                  # the ROM header's, as the console sends it
    version: str                    # "firered" or "leafgreen"
    language: str                   # cartridge language
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
    obj_gfx_info: int               # gObjectEventGraphicsInfoPointers
    obj_palettes: int               # sObjectEventSpritePalettes
    mon_icon_pal_indices: int       # gMonIconPaletteIndices
    mon_icon_palettes: int          # gMonIconPalettes
    get_mon_icon: int               # GetMonIconPtr, a ROM function
    setup_script: int               # ScriptContext_SetupScript
    selected_object: int            # gSelectedObjectEvent, IWRAM
    vmap: int                       # VMap, the map grid's size and pointer, IWRAM
    spawn_object: int               # SpawnSpecialObjectEventParameterized
    set_held_movement: int          # ObjectEventSetHeldMovement
    clear_held_movement: int        # ObjectEventClearHeldMovement
    move_object_to: int             # MoveObjectEventToMapCoords
    remove_object: int              # RemoveObjectEvent
    callable: MappingProxyType = field(repr=False)

    ewram: MappingProxyType = field(default_factory=lambda: MappingProxyType({}), repr=False)

    @property
    def name(self):
        return (f"{self.language.capitalize()} "
                f"{'FireRed' if self.version == 'firered' else 'LeafGreen'}")

    @property
    def saveblock1_size(self):
        return 0x3D40 if self.language == "japanese" else 0x3D68

    @property
    def intr_check(self):
        return self.gmain + 0x1C            # gMain.intrCheck [include/main.h:24]

    @property
    def overlay_oam(self):
        return self.gmain + 0x3F8           # gMain.oamBuffer[120] [include/main.h:38]

    @property
    def last_oam(self):
        return self.gmain + 0x430           # gMain.oamBuffer[127]

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
                "sound_main": self.sound_main | 1, "original": self.vblank_intr | 1,
                "oam": self.last_oam, "gfx_info": self.obj_gfx_info,
                "obj_palettes": self.obj_palettes, "get_mon_icon": self.get_mon_icon | 1,
                "icon_pal_indices": self.mon_icon_pal_indices,
                "icon_palettes": self.mon_icon_palettes, "setup_script": self.setup_script | 1,
                "selected_object": self.selected_object, "vmap": self.vmap, "spawn_object": self.spawn_object | 1,
                "set_held_movement": self.set_held_movement | 1,
                "clear_held_movement": self.clear_held_movement | 1,
                "move_object_to": self.move_object_to | 1, "remove_object": self.remove_object | 1,
                **self.ewram}

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
    obj_gfx_info=0x083983C8, obj_palettes=0x0839D770, mon_icon_pal_indices=0x083CBEE8,
    mon_icon_palettes=0x083CB7A8, get_mon_icon=0x0809AA74, setup_script=0x0806D3D4,
    selected_object=0x03004294, vmap=0x03004260, spawn_object=0x08062130,
    set_held_movement=0x080675A4, clear_held_movement=0x08067634, move_object_to=0x08063024,
    remove_object=0x08061DB4,
    callable=MappingProxyType(dict(rom_map.CALLABLE)))

# French LeafGreen: FireRed's RAM; ROM past 0x0807CF68 moves by rom_map.LEAFGREEN_DELTA_SEGMENTS.
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
    obj_gfx_info=0x083983A8, obj_palettes=0x0839D750, mon_icon_pal_indices=0x083CBD24,
    mon_icon_palettes=0x083CB5E4, get_mon_icon=0x0809AA48, setup_script=0x0806D3D4,
    selected_object=0x03004294, vmap=0x03004260, spawn_object=0x08062130,
    set_held_movement=0x080675A4, clear_held_movement=0x08067634, move_object_to=0x08063024,
    remove_object=0x08061DB4,
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

# English FireRed: pokefirered_switch.elf rebuilds the retail image byte for byte. IWRAM from gMain
# up moves +0xB0 against French, +0x110 from gSoundInfo up.
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
    obj_gfx_info=0x0839D91C, obj_palettes=0x083A2CC4, mon_icon_pal_indices=0x083D197C,
    mon_icon_palettes=0x083D123C, get_mon_icon=0x0809A7B8, setup_script=0x0806D270,
    selected_object=0x03004344, vmap=0x03004310, spawn_object=0x08061FD4,
    set_held_movement=0x08067448, clear_held_movement=0x080674D8, move_object_to=0x08062EC8,
    remove_object=0x08061C58,
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
    obj_gfx_info=0x0839D8FC, obj_palettes=0x083A2CA4, mon_icon_pal_indices=0x083D17B8,
    mon_icon_palettes=0x083D1078, get_mon_icon=0x0809A78C, setup_script=0x0806D270,
    selected_object=0x03004344, vmap=0x03004310, spawn_object=0x08061FD4,
    set_held_movement=0x08067448, clear_held_movement=0x080674D8, move_object_to=0x08062EC8,
    remove_object=0x08061C58,
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

# Spanish FireRed rev 0x0A: ROM bodies and literal pools [docs/frlg_rom_map.md].
BPRS = Build(
    game_code="BPRS", version="firered", language="spanish", language_id=LANGUAGE_SPANISH,
    rng=0x03004220, sb1ptr=0x03004228, sb2ptr=0x0300422C, intr_vblank=0x03002730, gmain=0x030022D0,
    pcm_dma_counter=0x03002F68, sound_info=0x03005F80, last_written_sector=0x030045A0,
    save_counter=0x030045B0, vblank_intr=0x0800071C, cb1_overworld=0x08059E5C,
    cb2_overworld=0x08059EDC, battle_cb1=0x08015B6C, battle_cb2=0x08014888,
    run_text_printers=0x08002D50, get_mon_data=0x080432F8, sound_main=0x081E089C,
    create_mon=0x08041164, random=0x080486C4, seed_rng=0x080486E4, read_flash=0x081E224C,
    client_run_buffer_script=0x08148CD0, standard_wild_encounter=0x0808653C,
    get_header_id=0x080861B4, save_slot_layout=0x083F7838, obj_gfx_info=0x08399740,
    obj_palettes=0x0839EAE8, mon_icon_pal_indices=0x083CD260, mon_icon_palettes=0x083CCB20,
    get_mon_icon=0x0809AA88, setup_script=0x0806D3E8, selected_object=0x03004294, vmap=0x03004260,
    spawn_object=0x08062144, set_held_movement=0x080675B8, clear_held_movement=0x08067648,
    move_object_to=0x08063038, remove_object=0x08061DC8, enigma_desc=(0x083D7914, 0x083D7924),
    callable=_callable(
        Random=0x080486C4, SeedRng=0x080486E4, CreateMon=0x08041164, VarGet=0x08071DF0,
        VarSet=0x08071E0C, GetVarPointer=0x08071CDC, AddBagItem=0x0809DA84,
        RemoveBagItem=0x0809DBD8, CheckBagHasSpace=0x0809DA00, CheckBagHasItem=0x0809D940,
        AddPCItem=0x0809DDC8, FlagSet=0x08071F08, FlagClear=0x08071F30, FlagGet=0x08071F58,
        IncrementGameStat=0x080587B8, GetMoney=0x080A376C, IsEnoughMoney=0x080A379C,
        AddMoney=0x080A37B4, RemoveMoney=0x080A37EC, CalcCRC16=0x080489B4, ReadFlash=0x081E224C,
        GetSetPokedexFlag=0x0808C874, SpeciesToNationalPokedexNum=0x080469A8,
        CompactPartySlots=0x08097210, ItemIsMail=0x0809BB2C, StringCompare=0x0800C938,
        InitRamScript=0x0806D604, RunScriptImmediately=0x0806D44C))

# Revision 0x0A, matched cartridge functions and literal pools [docs/frlg_rom_map.md].
BPRD = Build(
    game_code="BPRD", version="firered", language="german", language_id=LANGUAGE_GERMAN,
    rng=0x03004220,
    sb1ptr=0x03004228,
    sb2ptr=0x0300422C,
    intr_vblank=0x03002730,
    gmain=0x030022D0,
    pcm_dma_counter=0x03002F68,
    sound_info=0x03005F80,
    last_written_sector=0x030045A0,
    save_counter=0x030045B0,
    vblank_intr=0x08000730,
    cb1_overworld=0x08059D88,
    cb2_overworld=0x08059E08,
    battle_cb1=0x08015B80,
    battle_cb2=0x0801489C,
    run_text_printers=0x08002D64,
    get_mon_data=0x0804330C,
    sound_main=0x081E5000,
    create_mon=0x08041178,
    random=0x080485F0,
    seed_rng=0x08048610,
    read_flash=0x081E69B0,
    client_run_buffer_script=0x08148BA4,
    standard_wild_encounter=0x08086468,
    get_header_id=0x080860E0,
    save_slot_layout=0x083FCEC0,
    obj_gfx_info=0x0839DE9C,
    obj_palettes=0x083A3244,
    mon_icon_pal_indices=0x083D19BC,
    mon_icon_palettes=0x083D127C,
    get_mon_icon=0x0809A9B4,
    setup_script=0x0806D314,
    selected_object=0x03004294,
    vmap=0x03004260,
    spawn_object=0x08062070,
    set_held_movement=0x080674E4,
    clear_held_movement=0x08067574,
    move_object_to=0x08062F64,
    remove_object=0x08061CF4,
    enigma_desc=(0x083DCEDC, 0x083DCEEC),
    callable=_callable(
        Random=0x080485F0,
        SeedRng=0x08048610,
        CreateMon=0x08041178,
        VarGet=0x08071D1C,
        VarSet=0x08071D38,
        GetVarPointer=0x08071C08,
        AddBagItem=0x0809D9B0,
        RemoveBagItem=0x0809DB04,
        CheckBagHasSpace=0x0809D92C,
        CheckBagHasItem=0x0809D86C,
        AddPCItem=0x0809DCF4,
        FlagSet=0x08071E34,
        FlagClear=0x08071E5C,
        FlagGet=0x08071E84,
        IncrementGameStat=0x080586E4,
        GetMoney=0x080A36A4,
        IsEnoughMoney=0x080A36D4,
        AddMoney=0x080A36EC,
        RemoveMoney=0x080A3724,
        CalcCRC16=0x080488E0,
        ReadFlash=0x081E69B0,
        GetSetPokedexFlag=0x0808C7A0,
        SpeciesToNationalPokedexNum=0x080469BC,
        CompactPartySlots=0x0809713C,
        ItemIsMail=0x0809BA58,
        StringCompare=0x0800C94C,
        InitRamScript=0x0806D530,
        RunScriptImmediately=0x0806D378))

# Revision 0x0A, matched cartridge functions and literal pools [docs/frlg_rom_map.md].
BPGD = Build(
    game_code="BPGD", version="leafgreen", language="german", language_id=LANGUAGE_GERMAN,
    rng=0x03004220,
    sb1ptr=0x03004228,
    sb2ptr=0x0300422C,
    intr_vblank=0x03002730,
    gmain=0x030022D0,
    pcm_dma_counter=0x03002F68,
    sound_info=0x03005F80,
    last_written_sector=0x030045A0,
    save_counter=0x030045B0,
    vblank_intr=0x08000730,
    cb1_overworld=0x08059D88,
    cb2_overworld=0x08059E08,
    battle_cb1=0x08015B80,
    battle_cb2=0x0801489C,
    run_text_printers=0x08002D64,
    get_mon_data=0x0804330C,
    sound_main=0x081E4FDC,
    create_mon=0x08041178,
    random=0x080485F0,
    seed_rng=0x08048610,
    read_flash=0x081E698C,
    client_run_buffer_script=0x08148B80,
    standard_wild_encounter=0x0808643C,
    get_header_id=0x080860B4,
    save_slot_layout=0x083FCCFC,
    obj_gfx_info=0x0839DE7C,
    obj_palettes=0x083A3224,
    mon_icon_pal_indices=0x083D17F8,
    mon_icon_palettes=0x083D10B8,
    get_mon_icon=0x0809A988,
    setup_script=0x0806D314,
    selected_object=0x03004294,
    vmap=0x03004260,
    spawn_object=0x08062070,
    set_held_movement=0x080674E4,
    clear_held_movement=0x08067574,
    move_object_to=0x08062F64,
    remove_object=0x08061CF4,
    enigma_desc=(0x083DCD18, 0x083DCD28),
    callable=_callable(
        Random=0x080485F0,
        SeedRng=0x08048610,
        CreateMon=0x08041178,
        VarGet=0x08071D1C,
        VarSet=0x08071D38,
        GetVarPointer=0x08071C08,
        AddBagItem=0x0809D984,
        RemoveBagItem=0x0809DAD8,
        CheckBagHasSpace=0x0809D900,
        CheckBagHasItem=0x0809D840,
        AddPCItem=0x0809DCC8,
        FlagSet=0x08071E34,
        FlagClear=0x08071E5C,
        FlagGet=0x08071E84,
        IncrementGameStat=0x080586E4,
        GetMoney=0x080A3678,
        IsEnoughMoney=0x080A36A8,
        AddMoney=0x080A36C0,
        RemoveMoney=0x080A36F8,
        CalcCRC16=0x080488E0,
        ReadFlash=0x081E698C,
        GetSetPokedexFlag=0x0808C774,
        SpeciesToNationalPokedexNum=0x080469BC,
        CompactPartySlots=0x08097110,
        ItemIsMail=0x0809BA2C,
        StringCompare=0x0800C94C,
        InitRamScript=0x0806D530,
        RunScriptImmediately=0x0806D378))

# Revision 0x0A, matched cartridge functions and literal pools [docs/frlg_rom_map.md].
BPRI = Build(
    game_code="BPRI", version="firered", language="italian", language_id=LANGUAGE_ITALIAN,
    rng=0x03004220,
    sb1ptr=0x03004228,
    sb2ptr=0x0300422C,
    intr_vblank=0x03002730,
    gmain=0x030022D0,
    pcm_dma_counter=0x03002F68,
    sound_info=0x03005F80,
    last_written_sector=0x030045A0,
    save_counter=0x030045B0,
    vblank_intr=0x08000730,
    cb1_overworld=0x08059D74,
    cb2_overworld=0x08059DF4,
    battle_cb1=0x08015B80,
    battle_cb2=0x0801489C,
    run_text_printers=0x08002D64,
    get_mon_data=0x080432F8,
    sound_main=0x081DE1D4,
    create_mon=0x08041164,
    random=0x080485DC,
    seed_rng=0x080485FC,
    read_flash=0x081DFB84,
    client_run_buffer_script=0x08148BE4,
    standard_wild_encounter=0x08086454,
    get_header_id=0x080860CC,
    save_slot_layout=0x083F464C,
    obj_gfx_info=0x08397058,
    obj_palettes=0x0839C400,
    mon_icon_pal_indices=0x083CAB78,
    mon_icon_palettes=0x083CA438,
    get_mon_icon=0x0809A9A0,
    setup_script=0x0806D300,
    selected_object=0x03004294,
    vmap=0x03004260,
    spawn_object=0x0806205C,
    set_held_movement=0x080674D0,
    clear_held_movement=0x08067560,
    move_object_to=0x08062F50,
    remove_object=0x08061CE0,
    enigma_desc=(0x083D48AC, 0x083D48BC),
    callable=_callable(
        Random=0x080485DC,
        SeedRng=0x080485FC,
        CreateMon=0x08041164,
        VarGet=0x08071D08,
        VarSet=0x08071D24,
        GetVarPointer=0x08071BF4,
        AddBagItem=0x0809D99C,
        RemoveBagItem=0x0809DAF0,
        CheckBagHasSpace=0x0809D918,
        CheckBagHasItem=0x0809D858,
        AddPCItem=0x0809DCE0,
        FlagSet=0x08071E20,
        FlagClear=0x08071E48,
        FlagGet=0x08071E70,
        IncrementGameStat=0x080586D0,
        GetMoney=0x080A3684,
        IsEnoughMoney=0x080A36B4,
        AddMoney=0x080A36CC,
        RemoveMoney=0x080A3704,
        CalcCRC16=0x080488CC,
        ReadFlash=0x081DFB84,
        GetSetPokedexFlag=0x0808C78C,
        SpeciesToNationalPokedexNum=0x080469A8,
        CompactPartySlots=0x08097128,
        ItemIsMail=0x0809BA44,
        StringCompare=0x0800C94C,
        InitRamScript=0x0806D51C,
        RunScriptImmediately=0x0806D364))

# Revision 0x0A, matched cartridge functions and literal pools [docs/frlg_rom_map.md].
BPGI = Build(
    game_code="BPGI", version="leafgreen", language="italian", language_id=LANGUAGE_ITALIAN,
    rng=0x03004220,
    sb1ptr=0x03004228,
    sb2ptr=0x0300422C,
    intr_vblank=0x03002730,
    gmain=0x030022D0,
    pcm_dma_counter=0x03002F68,
    sound_info=0x03005F80,
    last_written_sector=0x030045A0,
    save_counter=0x030045B0,
    vblank_intr=0x08000730,
    cb1_overworld=0x08059D74,
    cb2_overworld=0x08059DF4,
    battle_cb1=0x08015B80,
    battle_cb2=0x0801489C,
    run_text_printers=0x08002D64,
    get_mon_data=0x080432F8,
    sound_main=0x081DE1B0,
    create_mon=0x08041164,
    random=0x080485DC,
    seed_rng=0x080485FC,
    read_flash=0x081DFB60,
    client_run_buffer_script=0x08148BC0,
    standard_wild_encounter=0x08086428,
    get_header_id=0x080860A0,
    save_slot_layout=0x083F4488,
    obj_gfx_info=0x08397038,
    obj_palettes=0x0839C3E0,
    mon_icon_pal_indices=0x083CA9B4,
    mon_icon_palettes=0x083CA274,
    get_mon_icon=0x0809A974,
    setup_script=0x0806D300,
    selected_object=0x03004294,
    vmap=0x03004260,
    spawn_object=0x0806205C,
    set_held_movement=0x080674D0,
    clear_held_movement=0x08067560,
    move_object_to=0x08062F50,
    remove_object=0x08061CE0,
    enigma_desc=(0x083D46E8, 0x083D46F8),
    callable=_callable(
        Random=0x080485DC,
        SeedRng=0x080485FC,
        CreateMon=0x08041164,
        VarGet=0x08071D08,
        VarSet=0x08071D24,
        GetVarPointer=0x08071BF4,
        AddBagItem=0x0809D970,
        RemoveBagItem=0x0809DAC4,
        CheckBagHasSpace=0x0809D8EC,
        CheckBagHasItem=0x0809D82C,
        AddPCItem=0x0809DCB4,
        FlagSet=0x08071E20,
        FlagClear=0x08071E48,
        FlagGet=0x08071E70,
        IncrementGameStat=0x080586D0,
        GetMoney=0x080A3658,
        IsEnoughMoney=0x080A3688,
        AddMoney=0x080A36A0,
        RemoveMoney=0x080A36D8,
        CalcCRC16=0x080488CC,
        ReadFlash=0x081DFB60,
        GetSetPokedexFlag=0x0808C760,
        SpeciesToNationalPokedexNum=0x080469A8,
        CompactPartySlots=0x080970FC,
        ItemIsMail=0x0809BA18,
        StringCompare=0x0800C94C,
        InitRamScript=0x0806D51C,
        RunScriptImmediately=0x0806D364))

# Revision 0x0A, matched cartridge functions and literal pools [docs/frlg_rom_map.md].
BPGS = Build(
    game_code="BPGS", version="leafgreen", language="spanish", language_id=LANGUAGE_SPANISH,
    rng=0x03004220,
    sb1ptr=0x03004228,
    sb2ptr=0x0300422C,
    intr_vblank=0x03002730,
    gmain=0x030022D0,
    pcm_dma_counter=0x03002F68,
    sound_info=0x03005F80,
    last_written_sector=0x030045A0,
    save_counter=0x030045B0,
    vblank_intr=0x0800071C,
    cb1_overworld=0x08059E5C,
    cb2_overworld=0x08059EDC,
    battle_cb1=0x08015B6C,
    battle_cb2=0x08014888,
    run_text_printers=0x08002D50,
    get_mon_data=0x080432F8,
    sound_main=0x081E0878,
    create_mon=0x08041164,
    random=0x080486C4,
    seed_rng=0x080486E4,
    read_flash=0x081E2228,
    client_run_buffer_script=0x08148CAC,
    standard_wild_encounter=0x08086510,
    get_header_id=0x08086188,
    save_slot_layout=0x083F7674,
    obj_gfx_info=0x08399720,
    obj_palettes=0x0839EAC8,
    mon_icon_pal_indices=0x083CD09C,
    mon_icon_palettes=0x083CC95C,
    get_mon_icon=0x0809AA5C,
    setup_script=0x0806D3E8,
    selected_object=0x03004294,
    vmap=0x03004260,
    spawn_object=0x08062144,
    set_held_movement=0x080675B8,
    clear_held_movement=0x08067648,
    move_object_to=0x08063038,
    remove_object=0x08061DC8,
    enigma_desc=(0x083D7750, 0x083D7760),
    callable=_callable(
        Random=0x080486C4,
        SeedRng=0x080486E4,
        CreateMon=0x08041164,
        VarGet=0x08071DF0,
        VarSet=0x08071E0C,
        GetVarPointer=0x08071CDC,
        AddBagItem=0x0809DA58,
        RemoveBagItem=0x0809DBAC,
        CheckBagHasSpace=0x0809D9D4,
        CheckBagHasItem=0x0809D914,
        AddPCItem=0x0809DD9C,
        FlagSet=0x08071F08,
        FlagClear=0x08071F30,
        FlagGet=0x08071F58,
        IncrementGameStat=0x080587B8,
        GetMoney=0x080A3740,
        IsEnoughMoney=0x080A3770,
        AddMoney=0x080A3788,
        RemoveMoney=0x080A37C0,
        CalcCRC16=0x080489B4,
        ReadFlash=0x081E2228,
        GetSetPokedexFlag=0x0808C848,
        SpeciesToNationalPokedexNum=0x080469A8,
        CompactPartySlots=0x080971E4,
        ItemIsMail=0x0809BB00,
        StringCompare=0x0800C938,
        InitRamScript=0x0806D604,
        RunScriptImmediately=0x0806D44C))

# Japanese revision 0x0A, paired cartridge code and literals [docs/frlg_rom_map.md].
BPRJ = Build(
    game_code="BPRJ", version="firered", language="japanese", language_id=LANGUAGE_JAPANESE,
    rng=0x03004230,
    sb1ptr=0x03004238,
    sb2ptr=0x0300423C,
    intr_vblank=0x03002740,
    gmain=0x030022E0,
    pcm_dma_counter=0x03002F78,
    sound_info=0x03006020,
    last_written_sector=0x030045C0,
    save_counter=0x030045D0,
    vblank_intr=0x0800071C,
    cb1_overworld=0x08059604,
    cb2_overworld=0x08059684,
    battle_cb1=0x080153B8,
    battle_cb2=0x08014144,
    run_text_printers=0x08002D38,
    get_mon_data=0x08042AE8,
    sound_main=0x081C46C0,
    create_mon=0x08040954,
    random=0x08047C90,
    seed_rng=0x08047CB0,
    read_flash=0x081C6070,
    client_run_buffer_script=0x081490E4,
    standard_wild_encounter=0x080860CC,
    get_header_id=0x08085D44,
    save_slot_layout=0x083BE570,
    obj_gfx_info=0x0835D708,
    obj_palettes=0x08362AB0,
    mon_icon_pal_indices=0x08395C38,
    mon_icon_palettes=0x083954F8,
    get_mon_icon=0x0809A2A4,
    setup_script=0x0806CB8C,
    selected_object=0x030042A4,
    vmap=0x03004270,
    spawn_object=0x080618F0,
    set_held_movement=0x08066D64,
    clear_held_movement=0x08066DF4,
    move_object_to=0x080627E4,
    remove_object=0x08061574,
    enigma_desc=(0x0839E168, 0x0839E178),
    callable=_callable(
        Random=0x08047C90,
        SeedRng=0x08047CB0,
        CreateMon=0x08040954,
        VarGet=0x08071524,
        VarSet=0x08071540,
        GetVarPointer=0x08071410,
        AddBagItem=0x0809D298,
        RemoveBagItem=0x0809D3EC,
        CheckBagHasSpace=0x0809D214,
        CheckBagHasItem=0x0809D154,
        AddPCItem=0x0809D5DC,
        FlagSet=0x0807163C,
        FlagClear=0x08071664,
        FlagGet=0x0807168C,
        IncrementGameStat=0x08057F60,
        GetMoney=0x080A3454,
        IsEnoughMoney=0x080A3484,
        AddMoney=0x080A349C,
        RemoveMoney=0x080A34D4,
        CalcCRC16=0x08047F80,
        ReadFlash=0x081C6070,
        GetSetPokedexFlag=0x0808C274,
        SpeciesToNationalPokedexNum=0x0804611C,
        CompactPartySlots=0x08096A34,
        ItemIsMail=0x0809B30C,
        StringCompare=0x0800C4B4,
        InitRamScript=0x0806CDA8,
        RunScriptImmediately=0x0806CBF0),
    ewram=MappingProxyType({
        "party": 0x020241E0,
        "party_count": 0x02023F85,
        "watch": 0x02023F88,
        "avatar": 0x02036FA8,
        "objects": 0x02036D68,
        "map_header": 0x02036D2C,
        "palette_fade": 0x020379E8,
        "flag": 0x02038624,
        "help": 0x0203F0E5,
        "printers": 0x02020030,
        "sprites": 0x020205B8,
        "pal_unfaded": 0x02037508,
        "pal_faded": 0x02037908,
        "overlay_pal": 0x0203790A,
        "special_var_8000": 0x02036FE8}))

# Japanese revision 0x0A, paired cartridge code and literals [docs/frlg_rom_map.md].
BPGJ = Build(
    game_code="BPGJ", version="leafgreen", language="japanese", language_id=LANGUAGE_JAPANESE,
    rng=0x03004230,
    sb1ptr=0x03004238,
    sb2ptr=0x0300423C,
    intr_vblank=0x03002740,
    gmain=0x030022E0,
    pcm_dma_counter=0x03002F78,
    sound_info=0x03006020,
    last_written_sector=0x030045C0,
    save_counter=0x030045D0,
    vblank_intr=0x0800071C,
    cb1_overworld=0x08059604,
    cb2_overworld=0x08059684,
    battle_cb1=0x080153B8,
    battle_cb2=0x08014144,
    run_text_printers=0x08002D38,
    get_mon_data=0x08042AE8,
    sound_main=0x081C469C,
    create_mon=0x08040954,
    random=0x08047C90,
    seed_rng=0x08047CB0,
    read_flash=0x081C604C,
    client_run_buffer_script=0x081490C0,
    standard_wild_encounter=0x080860A0,
    get_header_id=0x08085D18,
    save_slot_layout=0x083BE3E0,
    obj_gfx_info=0x0835D6E8,
    obj_palettes=0x08362A90,
    mon_icon_pal_indices=0x08395AA8,
    mon_icon_palettes=0x08395368,
    get_mon_icon=0x0809A278,
    setup_script=0x0806CB8C,
    selected_object=0x030042A4,
    vmap=0x03004270,
    spawn_object=0x080618F0,
    set_held_movement=0x08066D64,
    clear_held_movement=0x08066DF4,
    move_object_to=0x080627E4,
    remove_object=0x08061574,
    enigma_desc=(0x0839DFD8, 0x0839DFE8),
    callable=_callable(
        Random=0x08047C90,
        SeedRng=0x08047CB0,
        CreateMon=0x08040954,
        VarGet=0x08071524,
        VarSet=0x08071540,
        GetVarPointer=0x08071410,
        AddBagItem=0x0809D26C,
        RemoveBagItem=0x0809D3C0,
        CheckBagHasSpace=0x0809D1E8,
        CheckBagHasItem=0x0809D128,
        AddPCItem=0x0809D5B0,
        FlagSet=0x0807163C,
        FlagClear=0x08071664,
        FlagGet=0x0807168C,
        IncrementGameStat=0x08057F60,
        GetMoney=0x080A3428,
        IsEnoughMoney=0x080A3458,
        AddMoney=0x080A3470,
        RemoveMoney=0x080A34A8,
        CalcCRC16=0x08047F80,
        ReadFlash=0x081C604C,
        GetSetPokedexFlag=0x0808C248,
        SpeciesToNationalPokedexNum=0x0804611C,
        CompactPartySlots=0x08096A08,
        ItemIsMail=0x0809B2E0,
        StringCompare=0x0800C4B4,
        InitRamScript=0x0806CDA8,
        RunScriptImmediately=0x0806CBF0),
    ewram=MappingProxyType({
        "party": 0x020241E0,
        "party_count": 0x02023F85,
        "watch": 0x02023F88,
        "avatar": 0x02036FA8,
        "objects": 0x02036D68,
        "map_header": 0x02036D2C,
        "palette_fade": 0x020379E8,
        "flag": 0x02038624,
        "help": 0x0203F0E5,
        "printers": 0x02020030,
        "sprites": 0x020205B8,
        "pal_unfaded": 0x02037508,
        "pal_faded": 0x02037908,
        "overlay_pal": 0x0203790A,
        "special_var_8000": 0x02036FE8}))

BUILDS = MappingProxyType({build.game_code: build for build in (BPRF, BPGF, BPRE, BPGE, BPRS, BPGS, BPRD, BPGD, BPRI, BPGI, BPRJ, BPGJ)})
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
    for build in BUILDS.values():
        if build.version == version and build.language == language:
            return build
    raise UnknownBuild(f"no {language} {version} build")

import dataclasses
import argparse
from typing import Mapping
from dataclasses import dataclass, field, replace

from pokeldn.frlg.gift import gift_composer, gift_registry, mg_script, stamp_rally, wonder_card, wonder_news
from pokeldn.frlg.link import linkplayer, uroom_chat
from pokeldn.frlg.rom import buffer_script, builds, rng_script
from pokeldn.frlg.text import charmap
from pokeldn.gba import ni
from pokeldn.config import (LdnConfig, HostFileConfig, BUILTIN_HOST_FILE_CONFIG,
                            HOST_CONFIG_FILENAME, HOST_LOCAL_CONFIG_FILENAME,
                            default_host_config_path, default_host_local_config_path,
                            load_host_file_config, load_project_host_file_config)
from pokeldn.frlg.link import beacon


VERSIONS = {
    "firered": linkplayer.VERSION_FIRE_RED,
    "leafgreen": linkplayer.VERSION_LEAF_GREEN,
}
LANGUAGES = {
    "japanese": linkplayer.LANGUAGE_JAPANESE,
    "english": linkplayer.LANGUAGE_ENGLISH,
    "french": linkplayer.LANGUAGE_FRENCH,
    "italian": linkplayer.LANGUAGE_ITALIAN,
    "german": linkplayer.LANGUAGE_GERMAN,
    "spanish": linkplayer.LANGUAGE_SPANISH,
}

MysteryGiftDistribution = stamp_rally.MysteryGiftDistribution


@dataclass(frozen=True)
class TrainerProfile:
    name: str
    tid: int
    sid: int
    gender: int = 0
    version: str = "leafgreen"
    language: str = "english"
    has_national_dex: bool = True
    has_completed_game: bool = True
    # Offset 96 of the BLOCK_REQ_SIZE_100 exchange; the console arms its card counters when this
    # equals its held card [union_room.c:1777]. 0 arms nothing.
    card_flag_id: int = 0

    def __post_init__(self):
        if not isinstance(self.name, str):
            raise ValueError("trainer name must be a string")
        encoded = charmap.encode(self.name, language=self.language)
        if not self.name or charmap.decode(encoded, language=self.language) != self.name:
            raise ValueError("trainer name contains unsupported Gen III characters")
        limit = 5 if self.language == "japanese" else 7
        if len(encoded) > limit:
            raise ValueError(f"trainer name must encode to at most {limit} Gen III characters")
        if (type(self.tid) is not int or type(self.sid) is not int
                or not 0 <= self.tid <= 0xFFFF or not 0 <= self.sid <= 0xFFFF):
            raise ValueError("TID and SID must each fit in 16 bits")
        if type(self.gender) is not int or self.gender not in (0, 1):
            raise ValueError("gender must be 0 (male) or 1 (female)")
        if self.version not in VERSIONS:
            raise ValueError(f"version must be one of {', '.join(VERSIONS)}")
        if self.language not in LANGUAGES:
            raise ValueError(f"language must be one of {', '.join(LANGUAGES)}")
        if type(self.has_national_dex) is not bool:
            raise ValueError("has_national_dex must be a bool")
        if type(self.has_completed_game) is not bool:
            raise ValueError("has_completed_game must be a bool")
        if type(self.card_flag_id) is not int or not 0 <= self.card_flag_id <= 0xFFFF:
            raise ValueError("card_flag_id must fit in 16 bits")

    @property
    def trainer_id(self):
        return (self.sid << 16) | self.tid

    @property
    def progress_flags(self):
        return ((1 if self.has_national_dex else 0)
                | (0x10 if self.has_completed_game else 0))

    @property
    def discovery_name(self):
        return self.name

    @property
    def discovery_trainer_id(self):
        return self.tid

    @property
    def session_name(self):
        return self.name

    def to_link_player(self):
        return linkplayer.LinkPlayer(
            name=self.name,
            trainer_id=self.trainer_id,
            version=VERSIONS[self.version],
            progress_flags=self.progress_flags,
            progress_flags_copy=self.progress_flags,
            gender=self.gender,
            player_id=0,
            language=LANGUAGES[self.language],
        )

    def build_link_player_block(self, *, name_pad=0x00):
        return linkplayer.build_block(self.to_link_player(), name_pad=name_pad)

    def build_trainer_card(self, mon_species=None, *, name_pad=0x00):
        return linkplayer.build_trainer_card(
            self.to_link_player(), wonder_card_id=self.card_flag_id,
            mon_species=mon_species, name_pad=name_pad)

    def build_rfu_game_data(self, activity, *, started=True):
        return ni.build_game_data(
            VERSIONS[self.version], self.tid, self.name,
            language=LANGUAGES[self.language], activity=activity,
            started=started)


DEFAULT_TRAINER = TrainerProfile(
    name="POKELDN", tid=0x8822, sid=0x47ED, gender=0,
    version="leafgreen", language="english",
    has_national_dex=True, has_completed_game=True)


@dataclass(frozen=True)
class TradePlan:
    party_paths: tuple
    output_path: str = "received.pk3"
    output_size: int = 100
    output_format: str = "pk3"
    trade_slot: int = 1
    offered_slots: tuple | None = None
    trades: int = 1
    anim_delay: int | None = None
    player_ids_repeat_frames: int | None = None
    link_player_idle_frames: int | None = None
    close_grace_frames: int | None = None
    trust_pia: bool = False

    def __post_init__(self):
        if not 1 <= len(self.party_paths) <= 6:
            raise ValueError("party must contain 1..6 Pokemon files")
        if not 1 <= self.trades <= 6 or self.trades > len(self.party_paths):
            raise ValueError("trades must be 1..6 and cannot exceed party size")
        if self.output_size not in (80, 100):
            raise ValueError("output_size must be 80 or 100")
        if self.output_format not in ("pk3", "ek3"):
            raise ValueError("output_format must be pk3 or ek3")
        if type(self.trade_slot) is not int or not 0 <= self.trade_slot < len(self.party_paths):
            raise ValueError("trade_slot must reference the configured party")
        if self.anim_delay is not None \
                and (type(self.anim_delay) is not int or self.anim_delay < 0):
            raise ValueError("anim_delay must be a non-negative integer")
        if (self.player_ids_repeat_frames is not None
                and (type(self.player_ids_repeat_frames) is not int
                     or not 1 <= self.player_ids_repeat_frames <= 600)):
            raise ValueError("player_ids_repeat_frames must be between 1 and 600")
        if (self.link_player_idle_frames is not None
                and (type(self.link_player_idle_frames) is not int
                     or not 0 <= self.link_player_idle_frames <= 600)):
            raise ValueError("link_player_idle_frames must be between 0 and 600")
        if (self.close_grace_frames is not None
                and (type(self.close_grace_frames) is not int
                     or not 1 <= self.close_grace_frames <= 15 * 60)):
            raise ValueError("close_grace_frames must be between 1 and 900")
        if self.offered_slots is not None:
            if len(self.offered_slots) != self.trades:
                raise ValueError("offered_slots must contain one slot per trade")
            if len(set(self.offered_slots)) != len(self.offered_slots):
                raise ValueError("offered_slots must be distinct")
            if any(type(slot) is not int or not 0 <= slot < len(self.party_paths)
                   for slot in self.offered_slots):
                raise ValueError("offered_slots must reference the configured party")


@dataclass(frozen=True)
class JoinerOptions:
    live: bool = True
    replay_path: str | None = None
    self_id: int = 1
    decline: bool = False
    refuse_illegit: bool = False
    compress: bool = False
    pace_ms: int = 0
    connect_id: bytes | None = None

    def __post_init__(self):
        if self.live == bool(self.replay_path):
            raise ValueError("select exactly one of live mode or replay_path")
        if self.self_id != 1:
            raise ValueError("joiner self_id must be 1")
        if self.connect_id is not None and len(self.connect_id) != 2:
            raise ValueError("connect_id must contain exactly two bytes")


@dataclass(frozen=True)
class HostOptions:
    channel: int = 1
    scene_id: int | None = None
    max_participants: int = 6
    skip_preflight: bool = False
    skip_encryption: bool = False
    accept_decrypted_ccmp: bool = False
    native_nonce_sequence: bool = False
    session_response_first: bool = False
    # One RFU slot per VBlank by default; a console pair runs far below it [docs/frlg_link.md].
    protocol_tick_hz: float = 59.727
    # Host the Union Room (middle NPC, Pokemon Center 2F) instead of the trade centre.
    union_room: bool = False
    # Activity --union-room advertises; None is ACTIVITY_SEARCH [docs/frlg_link.md].
    union_room_activity: int | None = None
    # VBlanks of parent NI_START after the child's name NI; 0 never connects, 120 works (the child's
    # NI fail counter is 480 frames) [docs/frlg_link.md].
    union_room_keepalive: int = 0
    # Trading board type asked in return (beacon.TYPE_NAMES); None does not register.
    union_room_board_type: int | None = None
    union_room_board_level: int | None = None
    union_room_chat: bool = False
    chat_messages: tuple = ()
    union_room_battle: bool = False
    battle_forfeit: bool = True
    battle_move_slot: int = 0
    # Host the colosseum instead of the trade centre; only this path increments the card's
    # battlesWon [cable_club.c:792].
    colosseum: bool = False
    chat_file: str | None = None

    def __post_init__(self):
        # LDN channels: 2.4 GHz 1/6/11 and 5 GHz 36/40/44/48 [kinnay LDN wiki, WLAN Channels].
        if type(self.channel) is not int or not (1 <= self.channel <= 14 or self.channel in (36, 40, 44, 48)):
            raise ValueError("channel must be 1..14 or one of 36, 40, 44, 48")
        if type(self.max_participants) is not int or not 2 <= self.max_participants <= 8:
            raise ValueError("max_participants must be 2..8")
        if self.scene_id is not None and (
                type(self.scene_id) is not int or not 0 <= self.scene_id <= 0xFFFF):
            raise ValueError("scene_id must fit in 16 bits")
        for text in self.chat_messages:
            uroom_chat.check_text(text)


# --union-room-activity names [src/union_room.c:2664, src/data/union_room.h:407-418].
UNION_ROOM_ACTIVITIES = {
    "search": beacon.ACTIVITY_SEARCH,
    "in-room": beacon.IN_UNION_ROOM | 0,                      # IN_UNION_ROOM | ACTIVITY_NONE
    "in-room-trade": beacon.IN_UNION_ROOM | beacon.ACTIVITY_TRADE,
    "in-room-chat": beacon.IN_UNION_ROOM | 5,                 # ACTIVITY_CHAT
}


def resolve_board_type(name):
    if name is None:
        return None
    try:
        return beacon.TYPE_NAMES[name]
    except KeyError:
        raise ValueError("board type must be one of " + ", ".join(sorted(beacon.TYPE_NAMES)))


def resolve_union_room_activity(name):
    # The in-room form is the only one measured to pass IsPartnerActivityIncompatible.
    if name is None:
        return UNION_ROOM_ACTIVITIES["in-room"]
    try:
        return UNION_ROOM_ACTIVITIES[name]
    except KeyError:
        raise ValueError(
            "union_room_activity must be one of "
            + ", ".join(sorted(UNION_ROOM_ACTIVITIES)))



@dataclass(frozen=True)
class TradeRunConfig:
    profile: TrainerProfile
    plan: TradePlan
    ldn: LdnConfig
    role: JoinerOptions | HostOptions


@dataclass(frozen=True)
class MysteryGiftPayload:
    gift: str = wonder_card.GIFT_CELEBI
    flag_id: int | None = None
    # The four Easy Chat word ids the console must hold, or nothing is sent
    # [SVR_CHECK_QUESTIONNAIRE].
    questionnaire: tuple | None = None
    denied_message: str | None = None
    # A card already composed in wonder_card_events, sent instead of the registry's.
    definition: object = None

    def __post_init__(self):
        choices = gift_registry.GIFT_REGISTRY.live_choices
        if self.gift not in choices:
            raise ValueError(
                f"gift must be one of {', '.join(choices)}")
        if self.flag_id is None:
            object.__setattr__(self, "flag_id",
                               gift_registry.GIFT_REGISTRY.default_flag_id(self.gift))
        wonder_card.flag_for_flag_id(self.flag_id)
        if self.definition is not None and self.definition.slug != self.gift:
            raise ValueError(
                f"the composed definition is {self.definition.slug!r}, not {self.gift!r}")

    @property
    def receipt_flag(self):
        return wonder_card.flag_for_flag_id(self.flag_id)

    def build(self, build=None):
        distribution = self.build_distribution(build)
        return distribution.card, distribution.ram_script

    def build_distribution(self, build=None):
        """`build` is the cartridge the bytes are for [builds.py]; None is French FireRed."""
        if self.definition is not None:
            distribution = gift_composer.compile_definition(
                self.definition, flag_id=self.flag_id, build=build)
        else:
            distribution = gift_registry.GIFT_REGISTRY.build_distribution(
                self.gift, flag_id=self.flag_id, build=build)
        if self.questionnaire is None:
            return distribution
        return dataclasses.replace(
            distribution, questionnaire=tuple(self.questionnaire),
            denied_message=self.denied_message)


@dataclass(frozen=True)
class BufferScriptPayload:
    """Native ARM code for CLI_RUN_BUFFER_SCRIPT [buffer_script.py], reached through Wonder Cards
    -> Friend; no card, no flag, nothing saved."""
    script: str = buffer_script.TRAINER_ID_PROBE
    expect: object = None
    _expect_explicit: bool = False
    # memory-dump reads an absolute address, save-dump an offset into a save block.
    dump_address: int | None = None
    dump_block: str = buffer_script.SAVE_BLOCK_2
    dump_offset: int = 0
    dump_size: int = buffer_script.MAX_BUFFER_SCRIPT_SIZE
    dump_blocks: int = 1
    # memory-dump-scatter: unrelated addresses, one block each.
    dump_addresses: tuple = ()
    # save-write: the bytes, and the override for the guard that keeps a write in unread space.
    write_data: bytes | None = None
    write_unsafe: bool = False
    # save-write of a resident hook (name, params); `write_data` holds French FireRed's bytes.
    write_resident: tuple | None = None
    # flash-write: straight into save flash, so `write_unsafe` allows a sector in the save bands.
    flash_sector: int | None = None
    flash_fill_base: int = 0x46570000
    flash_fill_step: int = 1
    flash_words: int = buffer_script.FLASH_WRITE_WORDS
    flash_swi: int = buffer_script.SWI_WRITE_SECTOR
    flash_footer: bool = False
    flash_id: int = 0
    flash_counter: int = 0
    flash_derive: bool = False
    flash_counter_bias: int = 0
    flash_position: int | None = None
    flash_patch_offset: int = 0
    flash_patch_data: bytes | None = None
    flash_read_offset: int = 0
    # memory-scan: the needle, the range and the frame budget.
    scan_word: int | None = None
    scan_start: int = buffer_script.SCAN_ROM_START
    scan_end: int = buffer_script.SCAN_ROM_END
    scan_blocks: int = buffer_script.SCAN_DEFAULT_BLOCKS
    scan_max_calls: int | None = None
    # table-scan: a run of `table_runlen` words each `table_delta` above the last.
    table_delta: int | None = None
    table_runlen: int = buffer_script.SPECIAL_VARS_RUN_LENGTH
    table_start: int = buffer_script.SCAN_ROM_START
    table_end: int = buffer_script.SCAN_ROM_END
    table_blocks: int = buffer_script.TABLE_SCAN_DEFAULT_BLOCKS
    table_max_calls: int | None = None
    # Optional image for rom-checksum comparison.
    sum_start: int = buffer_script.SCAN_ROM_START
    sum_end: int = buffer_script.SCAN_ROM_END
    sum_block: int = buffer_script.ROM_CHECKSUM_DEFAULT_BLOCK
    sum_budget: int = buffer_script.ROM_CHECKSUM_DEFAULT_BUDGET
    sum_max_calls: int | None = None
    sum_reference: str | None = None
    # rng-trace: the word sampled once a frame and what to call between two reads.
    trace_address: int | None = None
    trace_call: int = 0
    trace_samples: int = buffer_script.TRACE_SAMPLE_CAPACITY
    trace_max_calls: int | None = None
    # call: `call_watch` is one address read either side of the call.
    call_address: int | None = None
    call_args: tuple = ()
    call_watch: int = 0
    # call-chain: buffer_script.ChainStep list in one frame; `write_unsafe` covers every write step.
    chain_steps: tuple = ()
    # sloop-svc: `svc_data_in` points r0 (1) or r1 (2) at the copy of `svc_data`.
    svc_numbers: tuple = ()
    svc_args: tuple = ()
    svc_data: bytes = b""
    svc_data_in: int = 0
    svc_bkpt: bool = False
    resident_name: str | None = None
    resident_params: tuple = ()
    # string-gather: an array of pointers and their stride.
    gather_address: int | None = None
    gather_count: int = 1
    gather_stride: int = 12
    gather_maxlen: int = buffer_script.GATHER_DEFAULT_MAXLEN
    # create-mon: CreateMon's eight arguments; `create_mon_destination` writes live memory and needs
    # write_unsafe.
    create_mon_call: int | None = None
    create_mon_species: int = 1
    create_mon_level: int = 5
    create_mon_fixed_iv: int = buffer_script.USE_RANDOM_IVS
    create_mon_personality: int | None = None
    create_mon_ot_id_type: int = buffer_script.OT_ID_PLAYER_ID
    create_mon_ot_id: int = 0
    create_mon_destination: int = 0
    create_mon_append: bool = False
    create_mon_append_dry_run: bool = False
    dump_file: str | None = None

    def __post_init__(self):
        choices = buffer_script.script_choices()
        if self.script not in choices:
            raise ValueError(f"buffer script must be one of {', '.join(choices)}")
        if not self._expect_explicit:
            object.__setattr__(self, "expect", self.spec.expect)
        if self.script in (buffer_script.MEMORY_DUMP, buffer_script.MEMORY_DUMP_MULTI):
            if self.dump_address is None:
                raise ValueError(f"{self.script} needs an address to read from")
        elif self.dump_address is not None:
            raise ValueError(
                f"an address to dump is only meaningful with {buffer_script.MEMORY_DUMP} "
                f"and {buffer_script.MEMORY_DUMP_MULTI}")
        if self.script == buffer_script.MEMORY_DUMP_SCATTER:
            if not self.dump_addresses:
                raise ValueError(
                    f"{buffer_script.MEMORY_DUMP_SCATTER} needs the addresses to read "
                    "(--dump-scatter A,B,C)")
            object.__setattr__(self, "dump_blocks", len(self.dump_addresses))
        elif self.dump_addresses:
            raise ValueError(
                f"a list of addresses is only meaningful with {buffer_script.MEMORY_DUMP_SCATTER}")
        if self.dump_blocks != 1 and self.script not in (buffer_script.MEMORY_DUMP_MULTI,
                                                         buffer_script.MEMORY_DUMP_SCATTER):
            raise ValueError(
                f"more than one block per session is only {buffer_script.MEMORY_DUMP_MULTI} and "
                f"{buffer_script.MEMORY_DUMP_SCATTER}; every other payload answers once")
        if not 1 <= self.dump_blocks <= mg_script.MAX_DUMP_BLOCKS:
            raise ValueError(
                f"a session carries 1..{mg_script.MAX_DUMP_BLOCKS} blocks, got {self.dump_blocks}")
        if self.script not in (buffer_script.SAVE_DUMP, buffer_script.SAVE_WRITE) \
                and self.dump_offset:
            raise ValueError(
                f"an offset into a save block is only meaningful with {buffer_script.SAVE_DUMP} "
                f"and {buffer_script.SAVE_WRITE}")
        if self.write_resident is not None:
            if self.script != buffer_script.SAVE_WRITE or self.write_data is not None:
                raise ValueError(
                    f"a resident hook is written by {buffer_script.SAVE_WRITE}, as its only data")
            name, params = self.write_resident
            object.__setattr__(self, "write_data",
                               buffer_script.build_resident_save_blob(name, **dict(params)))
        if self.script == buffer_script.SAVE_WRITE and self.write_resident is None:
            if not self.write_data:
                raise ValueError(
                    f"{buffer_script.SAVE_WRITE} needs the bytes to write (--write-text/--write-hex)")
            object.__setattr__(self, "dump_size", len(self._write_chunks()[-1][1]))
        elif self.write_data is not None and self.write_resident is None:
            raise ValueError(
                f"bytes to write are only meaningful with {buffer_script.SAVE_WRITE}")
        if self.script == buffer_script.FLASH_PATCH:
            if not self.flash_patch_data:
                raise ValueError(
                    f"{buffer_script.FLASH_PATCH} needs the replacement bytes (--flash-patch-hex)")
        elif self.flash_patch_data:
            raise ValueError(
                f"replacement bytes are only meaningful with {buffer_script.FLASH_PATCH}")
        if self.script == buffer_script.FLASH_READ:
            if self.flash_sector is None:
                raise ValueError(
                    f"{buffer_script.FLASH_READ} needs the sector to read (--flash-sector)")
        if self.script == buffer_script.FLASH_WRITE:
            if self.flash_sector is None:
                raise ValueError(
                    f"{buffer_script.FLASH_WRITE} needs the sector to write (--flash-sector)")
        elif self.flash_sector is not None and self.script != buffer_script.FLASH_READ:
            raise ValueError(
                f"a flash sector is only meaningful with {buffer_script.FLASH_WRITE} and "
                f"{buffer_script.FLASH_READ}")
        if self.script == buffer_script.MEMORY_SCAN:
            if self.scan_word is None:
                raise ValueError(
                    f"{buffer_script.MEMORY_SCAN} needs the 32-bit value to look for")
            # A fixed-size answer, so the host's length check proves the payload repointed the send.
            object.__setattr__(self, "dump_size", buffer_script.SCAN_ANSWER_SIZE)
        elif self.scan_word is not None:
            raise ValueError(
                f"a value to search for is only meaningful with {buffer_script.MEMORY_SCAN}")
        if self.script == buffer_script.TABLE_SCAN:
            if self.table_delta is None:
                raise ValueError(
                    f"{buffer_script.TABLE_SCAN} needs the step between entries (--table-delta)")
            object.__setattr__(self, "dump_size", buffer_script.TABLE_ANSWER_SIZE)
        elif self.table_delta is not None:
            raise ValueError(
                f"a table shape is only meaningful with {buffer_script.TABLE_SCAN}")
        if self.script == buffer_script.ROM_CHECKSUM:
            object.__setattr__(self, "dump_size", buffer_script.ROM_CHECKSUM_ANSWER_SIZE)
        elif self.sum_reference is not None:
            raise ValueError(
                f"a reference ROM is only meaningful with {buffer_script.ROM_CHECKSUM}")
        if self.script == buffer_script.RNG_TRACE:
            if self.trace_address is None:
                raise ValueError(f"{buffer_script.RNG_TRACE} needs an address to sample")
            object.__setattr__(self, "dump_size",
                               buffer_script.trace_answer_size(self.trace_samples))
        elif self.trace_address is not None or self.trace_call:
            raise ValueError(
                f"a word to sample is only meaningful with {buffer_script.RNG_TRACE}")
        if self.script == buffer_script.CALL:
            if self.call_address is None:
                raise ValueError(
                    f"{buffer_script.CALL} needs the function to call (--call-address); 0 calls "
                    "nothing, which checks the send path with the ROM left out")
            object.__setattr__(self, "dump_size", buffer_script.CALL_ANSWER_SIZE)
        elif self.call_address is not None or self.call_args or self.call_watch:
            raise ValueError(
                f"a function to call with chosen arguments is only meaningful with "
                f"{buffer_script.CALL}")
        if self.script == buffer_script.CALL_CHAIN:
            if not self.chain_steps:
                raise ValueError(
                    f"{buffer_script.CALL_CHAIN} needs at least one step (--chain-step)")
            object.__setattr__(self, "dump_size", buffer_script.CHAIN_ANSWER_SIZE)
        elif self.chain_steps:
            raise ValueError(
                f"a list of steps is only meaningful with {buffer_script.CALL_CHAIN}")
        if self.script == buffer_script.SLOOP_SVC:
            if not self.svc_numbers:
                raise ValueError(f"{buffer_script.SLOOP_SVC} needs the syscall (--svc-number)")
            object.__setattr__(self, "dump_size",
                               buffer_script.sloop_svc_answer_size(len(self.svc_data)))
        elif self.svc_numbers or self.svc_args or self.svc_data or self.svc_data_in:
            raise ValueError(f"--svc-* is only meaningful with {buffer_script.SLOOP_SVC}")
        if self.script == buffer_script.INSTALL_RESIDENT:
            if not self.resident_name:
                raise ValueError(f"{buffer_script.INSTALL_RESIDENT} needs the hook (--resident)")
            if not self.write_unsafe:
                raise ValueError(
                    f"{buffer_script.INSTALL_RESIDENT} replaces the console's V-blank handler until "
                    "the next reset; that needs --write-unsafe")
        elif self.resident_name or self.resident_params:
            raise ValueError(f"--resident is only meaningful with {buffer_script.INSTALL_RESIDENT}")
        if self.script == buffer_script.STRING_GATHER:
            if self.gather_address is None:
                raise ValueError(
                    f"{buffer_script.STRING_GATHER} needs the array of pointers to follow "
                    "(--gather-address)")
            object.__setattr__(self, "dump_size", buffer_script.GATHER_ANSWER_SIZE)
        elif self.gather_address is not None:
            raise ValueError(
                f"an array of pointers is only meaningful with {buffer_script.STRING_GATHER}")
        if self.script == buffer_script.CREATE_MON:
            object.__setattr__(self, "dump_size", buffer_script.CREATE_MON_ANSWER_SIZE)
            if self.create_mon_destination and not self.write_unsafe:
                raise ValueError(
                    "copying the finished mon to 0x%08X writes the console's live memory; that "
                    "needs --write-unsafe, the same deliberate override an out-of-scratch "
                    "save-write takes" % self.create_mon_destination)
            if self.create_mon_append and self.create_mon_append_dry_run:
                raise ValueError(
                    "--create-mon-append and --create-mon-append-dry-run are the same run with "
                    "and without the two stores that change the save; ask for one of them")
            if self.create_mon_append and not self.write_unsafe:
                raise ValueError(
                    "appending the mon to the player's party writes their LIVE SAVE - 100 bytes "
                    "at playerParty[playerPartyCount] and the count byte - and the console commits "
                    "it to flash afterwards. That needs --write-unsafe, the same deliberate "
                    "override an out-of-scratch save-write takes")
        elif (self.create_mon_call is not None or self.create_mon_destination
                or self.create_mon_append or self.create_mon_append_dry_run):
            raise ValueError(
                f"a function to call with eight arguments is only meaningful with "
                f"{buffer_script.CREATE_MON}")
        if self.script == buffer_script.ANCHORS:
            object.__setattr__(self, "dump_size", buffer_script.ANCHORS_SIZE)
        if self.is_dump:
            self.build_code()

    @property
    def is_dump(self):
        """Anything whose answer comes back as bytes on ident 19 rather than the 4-byte channel. A
        resident hook's save-write ends in install-kept, which answers on the channel."""
        return self.script in buffer_script.DUMP_SCRIPTS and self.write_resident is None

    @property
    def spec(self):
        return buffer_script.SCRIPT_REGISTRY[self.script]

    def build_code(self, build=None):
        """The payload for `build` [builds.py]; None is French FireRed."""
        build = builds.resolve(build)
        if self.script == buffer_script.MEMORY_DUMP:
            return buffer_script.build_memory_dump(self.dump_address, self.dump_size, build=build)
        if self.script == buffer_script.MEMORY_DUMP_MULTI:
            return buffer_script.build_memory_dump_multi(
                self.dump_address, self.dump_size, self.dump_blocks, build=build)
        if self.script == buffer_script.MEMORY_DUMP_SCATTER:
            return buffer_script.build_memory_dump_scatter(
                self.dump_addresses, self.dump_size, build=build)
        if self.script == buffer_script.SAVE_DUMP:
            return buffer_script.build_save_dump(
                self.dump_block, self.dump_offset, self.dump_size)
        if self.script == buffer_script.RNG_TRACE:
            return buffer_script.build_rng_trace(
                self.trace_address, self.trace_call, self.trace_samples, self.trace_max_calls)
        if self.script == buffer_script.MEMORY_SCAN:
            return buffer_script.build_memory_scan(
                self.scan_word, self.scan_start, self.scan_end,
                self.scan_blocks, self.scan_max_calls)
        if self.script == buffer_script.ROM_CHECKSUM:
            return buffer_script.build_rom_checksum(
                self.sum_start, self.sum_end, self.sum_block, self.sum_budget,
                self.sum_max_calls)
        if self.script == buffer_script.TABLE_SCAN:
            return buffer_script.build_table_scan(
                self.table_delta, self.table_runlen, self.table_start, self.table_end,
                self.table_blocks, self.table_max_calls)
        if self.script == buffer_script.CALL:
            return buffer_script.build_call(
                self.call_address, self.call_args, self.call_watch)
        if self.script == buffer_script.CALL_CHAIN:
            return buffer_script.build_call_chain(
                self.chain_steps, unsafe=self.write_unsafe, build=build)
        if self.script == buffer_script.STRING_GATHER:
            return buffer_script.build_string_gather(
                self.gather_address, self.gather_count, self.gather_stride,
                maxlen=self.gather_maxlen)
        if self.script == buffer_script.CREATE_MON:
            has_fixed = self.create_mon_personality is not None
            return buffer_script.build_create_mon(
                build.create_mon | 1 if self.create_mon_call is None
                else self.create_mon_call,
                self.create_mon_species, self.create_mon_level,
                fixed_iv=self.create_mon_fixed_iv,
                has_fixed_personality=int(has_fixed),
                fixed_personality=self.create_mon_personality if has_fixed else 0,
                ot_id_type=self.create_mon_ot_id_type, fixed_ot_id=self.create_mon_ot_id,
                destination=self.create_mon_destination,
                party_base=build.ewram.get("party"), party_count=build.ewram.get("party_count"),
                party_append=(buffer_script.PARTY_APPEND_DRY_RUN
                              if self.create_mon_append_dry_run
                              else buffer_script.PARTY_APPEND_WRITE if self.create_mon_append
                              else buffer_script.PARTY_APPEND_NO))
        if self.script == buffer_script.SAVE_WRITE and self.write_resident is not None:
            return buffer_script.build_install_kept(build)
        if self.script == buffer_script.INSTALL_KEPT:
            return buffer_script.build_install_kept(build)
        if self.script == buffer_script.SAVE_WRITE:
            offset, data = self._write_chunks()[-1]
            return buffer_script.build_save_write(
                data, self.dump_block, offset, unsafe=self.write_unsafe)
        if self.script == buffer_script.INSTALL_RESIDENT:
            return buffer_script.build_install_resident(
                self.resident_name, build=build, **dict(self.resident_params))
        if self.script == buffer_script.SLOOP_SVC:
            return buffer_script.build_sloop_svc(
                self.svc_numbers, self.svc_args, self.svc_data, flags=self.svc_data_in,
                unsafe=self.write_unsafe, bkpt=self.svc_bkpt)
        if self.script == buffer_script.FLASH_READ:
            return buffer_script.build_flash_read(
                self.flash_sector, offset=self.flash_read_offset, length=self.dump_size)
        if self.script == buffer_script.FLASH_PATCH:
            return buffer_script.build_flash_patch(
                self.flash_id, self.flash_patch_offset, self.flash_patch_data,
                counter_bias=self.flash_counter_bias, unsafe=self.write_unsafe, build=build)
        if self.script == buffer_script.FLASH_WRITE:
            return buffer_script.build_flash_write(
                self.flash_sector, fill_base=self.flash_fill_base,
                fill_step=self.flash_fill_step, words=self.flash_words,
                number=self.flash_swi, unsafe=self.write_unsafe,
                footer=self.flash_footer, sector_id=self.flash_id,
                counter=self.flash_counter, derive=self.flash_derive,
                counter_bias=self.flash_counter_bias, position=self.flash_position,
                build=build)
        return buffer_script.payload(self.script)

    def _write_chunks(self):
        """save-write's data as (offset, bytes) pieces of one payload each, in order."""
        size = buffer_script.MAX_SAVE_WRITE_BYTES
        return [(self.dump_offset + at, self.write_data[at:at + size])
                for at in range(0, len(self.write_data), size)]

    def build_lead(self, build=None):
        """The payloads run before build_code's in the same session: a resident hook's
        save-writes, or every piece but the last of a write past one payload."""
        if self.write_resident is not None:
            name, params = self.write_resident
            return buffer_script.build_resident_save_session(name, build=build, **dict(params))[0]
        if self.script == buffer_script.SAVE_WRITE:
            return tuple(buffer_script.build_save_write(data, self.dump_block, offset,
                                                        unsafe=self.write_unsafe)
                         for offset, data in self._write_chunks()[:-1])
        return ()

    def build_distribution(self, build=None):
        return MysteryGiftDistribution(
            None, None, buffer_code=self.build_code(build), buffer_lead=self.build_lead(build),
            buffer_expect=self.expect,
            buffer_dump_size=self.dump_size if self.is_dump else None,
            buffer_dump_blocks=self.dump_blocks,
            buffer_dump_address=(self.dump_address or
                                 (self.dump_addresses[0] if self.dump_addresses else 0)),
            buffer_dump_addresses=tuple(self.dump_addresses or ()),
            buffer_decode=(self.script if self.script in buffer_script.DECODED_SCRIPTS
                           else None),
            buffer_reference=(self.reference_rom(build)
                              if self.script == buffer_script.ROM_CHECKSUM else None))

    def reference_rom(self, build=None):
        """Optional image explicitly supplied with --sum-reference."""
        return self.sum_reference


@dataclass(frozen=True)
class WonderNewsPayload:
    """Wonder News. A console keeps news that differs byte for byte from what it holds
    [decomp:src/mystery_gift.c:140]; `news_id` makes the same text land again."""
    news: str = wonder_news.DEFAULT_NEWS
    news_id: int | None = None

    def __post_init__(self):
        choices = wonder_news.news_choices()
        if self.news not in choices:
            raise ValueError(f"news must be one of {', '.join(choices)}")
        if self.news_id is not None and (type(self.news_id) is not int
                                         or not 0 < self.news_id <= 0xFFFF):
            raise ValueError("news_id must be between 1 and 65535")
        self.build_news()

    @property
    def spec(self):
        return wonder_news.NEWS_REGISTRY[self.news]

    def build_news(self):
        return wonder_news.build_news(self.news, news_id=self.news_id)

    def build_distribution(self, build=None):
        """Text only, encoded for the selected cartridge."""
        return MysteryGiftDistribution(None, None, news=wonder_news.for_build(self.build_news(), build))


def _mystery_gift_host_defaults():
    return HostOptions(
        skip_encryption=True,
        native_nonce_sequence=True,
        session_response_first=True,
    )


@dataclass(frozen=True)
class MysteryGiftRunConfig:
    profile: TrainerProfile = DEFAULT_TRAINER
    payload: MysteryGiftPayload = field(default_factory=MysteryGiftPayload)
    # The cartridge checked against the console's game data; None does not check.
    expect_console: str | None = None
    # A game code, or "auto" for the console's own; an explicit `console_version` holds a
    # build-dependent payload to it [plan_builds].
    console_build: str = "auto"
    console_version: str | None = None
    ldn: LdnConfig = field(default_factory=lambda: LdnConfig(phy="auto"))
    role: HostOptions = field(default_factory=_mystery_gift_host_defaults)
    trust_pia: bool = True
    client_ready_idle_frames: int | None = None
    inter_block_gap_frames: int | None = None
    block_repeat: int | None = None
    ram_script_block_repeat: int | None = None
    end_on_success: bool = False
    idle_timeout_seconds: int | None = None
    attempt_log_dir: str | None = None
    # Card counters are only evidence as a difference between sessions [game_data_log.py].
    game_data_log: str | None = None

    def __post_init__(self):
        if not isinstance(self.profile, TrainerProfile):
            raise ValueError("profile must be a TrainerProfile")
        from pokeldn.frlg.gift.file import FilePayload
        if not isinstance(self.payload,
                          (MysteryGiftPayload, WonderNewsPayload, BufferScriptPayload, FilePayload)):
            raise ValueError(
                "payload must be a MysteryGiftPayload, WonderNewsPayload, BufferScriptPayload or FilePayload")
        if not isinstance(self.ldn, LdnConfig):
            raise ValueError("ldn must be an LdnConfig")
        if not isinstance(self.role, HostOptions):
            raise ValueError("role must be HostOptions")
        if type(self.trust_pia) is not bool:
            raise ValueError("trust_pia must be a bool")
        if (self.client_ready_idle_frames is not None
                and (type(self.client_ready_idle_frames) is not int
                     or not 0 <= self.client_ready_idle_frames <= 600)):
            raise ValueError("client_ready_idle_frames must be between 0 and 600")
        if (self.inter_block_gap_frames is not None
                and (type(self.inter_block_gap_frames) is not int
                     or not 0 <= self.inter_block_gap_frames <= 600)):
            raise ValueError("inter_block_gap_frames must be between 0 and 600")
        if (self.block_repeat is not None
                and (type(self.block_repeat) is not int
                     or not 1 <= self.block_repeat <= 8)):
            raise ValueError("block_repeat must be between 1 and 8")
        if (self.ram_script_block_repeat is not None
                and (type(self.ram_script_block_repeat) is not int
                     or not 1 <= self.ram_script_block_repeat <= 8)):
            raise ValueError("ram_script_block_repeat must be between 1 and 8")
        if type(self.end_on_success) is not bool:
            raise ValueError("end_on_success must be a bool")
        if (self.idle_timeout_seconds is not None
                and (type(self.idle_timeout_seconds) is not int
                     or not 1 <= self.idle_timeout_seconds <= 24 * 60 * 60)):
            raise ValueError("idle_timeout_seconds must be between 1 and 86400")
        if self.attempt_log_dir is not None and not isinstance(self.attempt_log_dir, str):
            raise ValueError("attempt_log_dir must be a string or None")
        if self.game_data_log is not None and not isinstance(self.game_data_log, str):
            raise ValueError("game_data_log must be a string or None")
        if self.console_build not in CONSOLE_BUILD_CHOICES:
            raise ValueError(f"console_build must be one of {', '.join(CONSOLE_BUILD_CHOICES)}")
        if self.console_version not in (None, *VERSIONS):
            raise ValueError(f"console_version must be one of {', '.join(VERSIONS)} or None")


CONSOLE_BUILD_AUTO = "auto"
CONSOLE_BUILD_CHOICES = (CONSOLE_BUILD_AUTO, *builds.GAME_CODES)


@dataclass(frozen=True)
class BuildPlan:
    """`per_build` is {game code: distribution, or the refusal reason}; None when every build gets
    the same bytes."""
    distribution: MysteryGiftDistribution
    per_build: Mapping | None
    build: object = None

    @property
    def codes(self):
        return tuple(code for code, chosen in (self.per_build or {}).items()
                     if not isinstance(chosen, str))


def plan_builds(payload, console_build=CONSOLE_BUILD_AUTO, version=None):
    """-> the BuildPlan for `payload`. An explicit `version` holds a build-dependent payload to
    that version's cartridges; `console_build` names the only one to serve."""
    if console_build not in CONSOLE_BUILD_CHOICES:
        raise ValueError(f"console_build must be one of {', '.join(CONSOLE_BUILD_CHOICES)}")
    codes = builds.GAME_CODES if console_build == CONSOLE_BUILD_AUTO else (console_build,)
    built = {}
    for code in codes:
        try:
            built[code] = payload.build_distribution(builds.BUILDS[code])
        except (ValueError, rng_script.RngScriptError) as exc:
            built[code] = f"its payload cannot be built for {code}: {exc}"
    usable = [chosen for chosen in built.values() if not isinstance(chosen, str)]
    if not usable:
        raise ValueError(next(iter(built.values())))
    if console_build == CONSOLE_BUILD_AUTO and len(usable) == len(built) \
            and all(chosen == usable[0] for chosen in usable) \
            and not getattr(payload, "requires_build_selection", False):
        return BuildPlan(usable[0], None)
    if version is not None:
        for code in built:
            if builds.BUILDS[code].version != version and not isinstance(built[code], str):
                built[code] = (f"--version {version} holds this build-dependent payload to "
                               f"{version} cartridges")
        usable = [chosen for chosen in built.values() if not isinstance(chosen, str)]
        if not usable:
            raise ValueError(f"--console-build {console_build} is not a {version} cartridge; "
                             f"drop --version or name a {version} build")
    only = builds.BUILDS[console_build] if console_build != CONSOLE_BUILD_AUTO else None
    return BuildPlan(usable[0], built, only)


def parse_trainer_id(value):
    parts = value.split(":")
    if len(parts) not in (1, 2) or any(not part or not part.isdecimal() for part in parts):
        raise ValueError("ID must be decimal TID or TID:SID")
    values = tuple(int(part, 10) for part in parts)
    if any(number > 0xFFFF for number in values):
        raise ValueError("TID and SID must each be between 0 and 65535")
    return values[0], values[1] if len(values) == 2 else None


def trainer_id_argument(value):
    try:
        return parse_trainer_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def add_identity_arguments(parser):
    parser.add_argument("--ot", default=None, help="trainer name; defaults to DEFAULT_TRAINER")
    parser.add_argument("--version", choices=tuple(VERSIONS), default=None,
                        help="game version; defaults to DEFAULT_TRAINER")
    parser.add_argument("--language", choices=tuple(LANGUAGES), default=None,
                        help="trainer language; defaults to DEFAULT_TRAINER")
    parser.add_argument("--id", type=trainer_id_argument, metavar="TID[:SID]", default=None,
                        help="decimal trainer ID, optionally followed by decimal secret ID")
    parser.add_argument("--card-flag-id", type=lambda v: int(v, 0), metavar="N", default=None,
                        help="the Wonder Card flag id our trainer card claims in the Union Room "
                             "card exchange. A console holding the card with that id arms its own "
                             "card counters, so a trade or cable-club battle with us increments "
                             "them [union_room.c:1777]; default 0, which arms nothing")


def profile_from_overrides(*, ot=None, version=None, language=None, trainer_id=None,
                           card_flag_id=None, base=DEFAULT_TRAINER):
    changes = {}
    if card_flag_id is not None:
        changes["card_flag_id"] = card_flag_id
    if ot is not None:
        changes["name"] = ot
    if version is not None:
        changes["version"] = version
    if language is not None:
        changes["language"] = language
        if language == "japanese" and ot is None:
            changes["name"] = base.name[:5]
    if trainer_id is not None:
        tid, sid = trainer_id
        changes["tid"] = tid
        if sid is not None:
            changes["sid"] = sid
    return replace(base, **changes)

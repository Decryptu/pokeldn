"""French cartridges get the bytes recorded in tests/data/frlg_french_payloads.json before builds.py.

Three differences are intended: the flash images' asm range guard, French LeafGreen's callable names
past 0x0807CF68 (AddBagItem 0x0809DA44), and LeafGreen's own Enigma berry description pointers.
"""

import dataclasses
import hashlib
import json
import pathlib

import pytest

from pokeldn import config
from pokeldn.frlg.gift import gift_registry, wonder_card_events as wce, wonder_news
from pokeldn.frlg.gift.gift_composer import compile_definition
from pokeldn.frlg.rom import buffer_script as bs, builds, native_script as ns, rom_map

REFERENCE = json.loads(
    (pathlib.Path(__file__).parent / "data" / "frlg_french_payloads.json").read_text())
FRENCH = (builds.BPRF, builds.BPGF)


# Fields added after the recording; at their default they are left out of the digest.
NEWER_FIELDS = {"buffer_reference": None}


def digest(value):
    """The recorder's digest: a byte string, or a dataclass's fields in order."""
    if isinstance(value, (bytes, bytearray)):
        blob = bytes(value)
    elif dataclasses.is_dataclass(value):
        blob = b"\x00".join(
            f.name.encode() + b"=" + (bytes(v) if isinstance(v, (bytes, bytearray))
                                      else repr(v).encode())
            for f in dataclasses.fields(value) for v in (getattr(value, f.name),)
            if not (f.name in NEWER_FIELDS and v == NEWER_FIELDS[f.name]))
    else:
        raise TypeError(type(value))
    return f"{len(blob)}:{hashlib.sha256(blob).hexdigest()}"


def _payload(**fields):
    return lambda build: config.BufferScriptPayload(**fields).build_code(build)


def _cases():
    """{case: build -> bytes or distribution}, the recorder's case list on today's API."""
    cases = {}
    for slug in gift_registry.GIFT_REGISTRY.live_choices:
        cases[f"gift:{slug}"] = (lambda build, slug=slug:
                                 gift_registry.GIFT_REGISTRY.build_distribution(slug, build=build))
    criteria = ns.MonCriteria(natures=(3,), iv_minimums=(0, 10, 0, 0, 0, 0))
    for name, compose in (("rng-mon-hunt", wce.build_rng_mon_hunt_gift),
                          ("rng-mon-hunt-far", wce.build_rng_mon_hunt_far_gift),
                          ("rng-mon-hunt-both", wce.build_rng_mon_hunt_both_gift),
                          ("rng-mon-hunt-log", wce.build_rng_mon_hunt_log_gift)):
        cases[f"composed:{name}"] = (lambda build, compose=compose: compile_definition(
            compose(criteria, species=25, level=9), build=build))
    for news in wonder_news.news_choices():
        cases[f"news:{news}"] = lambda build, news=news: wonder_news.build_news(news)

    step = bs.parse_chain_step
    cases.update({
        "buffer:trainer-id-probe": _payload(script=bs.TRAINER_ID_PROBE),
        "buffer:anchors": _payload(script=bs.ANCHORS),
        "buffer:save-dump": _payload(script=bs.SAVE_DUMP, dump_block="sav1", dump_offset=0x34,
                                     dump_size=608),
        "buffer:memory-dump": _payload(script=bs.MEMORY_DUMP, dump_address=0x0201C000),
        "buffer:memory-dump-multi": _payload(script=bs.MEMORY_DUMP_MULTI,
                                             dump_address=0x08000000, dump_blocks=16),
        "buffer:memory-dump-scatter": _payload(script=bs.MEMORY_DUMP_SCATTER,
                                               dump_addresses=(0x08000000, 0x02024000)),
        "buffer:save-write": _payload(script=bs.SAVE_WRITE, dump_offset=0xB20, write_data=b"TEXT"),
        "buffer:flash-read": _payload(script=bs.FLASH_READ, flash_sector=3, dump_size=252),
        "buffer:flash-write": _payload(script=bs.FLASH_WRITE, flash_sector=30),
        "buffer:flash-write-derive": _payload(script=bs.FLASH_WRITE, flash_sector=0,
                                              flash_footer=True, flash_id=4, flash_derive=True,
                                              write_unsafe=True),
        "buffer:flash-write-derive-position": _payload(
            script=bs.FLASH_WRITE, flash_sector=0, flash_footer=True, flash_derive=True,
            flash_position=13, flash_counter_bias=1, write_unsafe=True),
        "buffer:flash-patch": _payload(script=bs.FLASH_PATCH, flash_id=0, flash_patch_offset=0x10,
                                       flash_patch_data=b"\x01\x02", write_unsafe=True),
        "buffer:sloop-svc": _payload(script=bs.SLOOP_SVC, svc_numbers=(0x4D,), svc_data=b"hello",
                                     svc_data_in=1),
        "buffer:memory-scan": _payload(script=bs.MEMORY_SCAN, scan_word=0x41C64E6D),
        "buffer:table-scan": _payload(script=bs.TABLE_SCAN, table_delta=2),
        "buffer:string-gather": _payload(script=bs.STRING_GATHER, gather_address=0x083E0000,
                                         gather_count=10),
        # These two carry French FireRed's addresses as explicit operands, as recorded.
        "buffer:rng-trace": _payload(script=bs.RNG_TRACE, trace_address=rom_map.GRNG_VALUE,
                                     trace_call=rom_map.thumb(rom_map.RANDOM)),
        "buffer:call": _payload(script=bs.CALL, call_address=rom_map.thumb(rom_map.SEED_RNG),
                                call_args=(0xC0DE,), call_watch=rom_map.GRNG_VALUE),
        "buffer:call-chain": _payload(script=bs.CALL_CHAIN, write_unsafe=True, chain_steps=(
            step("call:GetVarPointer,0x4024"), step("read16+keep:prev"), step("write16:prev,7"))),
        "buffer:call-chain-addbagitem": _payload(script=bs.CALL_CHAIN,
                                                 chain_steps=(step("call:AddBagItem,1,1"),)),
        "buffer:create-mon": _payload(script=bs.CREATE_MON, create_mon_species=25,
                                      create_mon_level=5),
        "buffer:create-mon-append": _payload(
            script=bs.CREATE_MON, create_mon_species=59, create_mon_level=30,
            create_mon_fixed_iv=31, create_mon_personality=0x12345678, create_mon_append=True,
            write_unsafe=True),
        "native:install-hook-script": lambda build: ns.build_install_hook_script(build=build),
        "native:loader-script": lambda build: ns.build_loader_script(build=build),
        "native:save-payload": lambda build: ns.build_save_payload(build=build),
        "native:shiny-hunt": lambda build: ns.build_shiny_hunt_script(132, 50, build=build),
    })
    for name, params in (("turbo", ()), ("turbo", (("field", 1), ("hold", 0x100), ("budget", 228))),
                         ("shiny", ()), ("ivs", ()), ("noencounter", ())):
        label = name + "".join(f",{k}={v}" for k, v in params)
        cases[f"buffer:install-resident:{label}"] = (
            lambda build, name=name, params=params: config.BufferScriptPayload(
                script=bs.INSTALL_RESIDENT, resident_name=name, resident_params=params,
                write_unsafe=True).build_code(build))
        if name != "shiny":             # 1080 bytes: past one save-write
            cases[f"save-blob:{label}"] = (
                lambda build, name=name, params=params:
                bs.build_resident_save_blob(name, build=build, **dict(params)))
    for case, script in FLASH_IMAGES.items():
        cases[f"operands:{case}"] = (
            lambda build, case=case, script=script: b"".join(
                cases[case](build)[offset:offset + length]
                for offset, length in bs.PATCHED_SPANS[script]))
    return cases


# The images the asm range guard changed: only their operand rows are held to the reference.
FLASH_IMAGES = {"buffer:flash-write": bs.FLASH_WRITE,
                "buffer:flash-write-derive": bs.FLASH_WRITE,
                "buffer:flash-write-derive-position": bs.FLASH_WRITE,
                "buffer:flash-patch": bs.FLASH_PATCH}


def _words(mapping):
    return {old.to_bytes(4, "little"): new.to_bytes(4, "little") for old, new in mapping.items()}


def _enigma_words():
    return _words(dict(zip(builds.BPRF.enigma_desc, builds.BPGF.enigma_desc)))


def _addbagitem_words():
    return _words({builds.BPRF.callable_function("AddBagItem"):
                   builds.BPGF.callable_function("AddBagItem")})


# Case -> the old French FireRed words each French LeafGreen word replaces, and in which field.
CORRECTED_ON_LEAFGREEN = {
    "gift:mevent-opcode-sweep": ("mevent", _enigma_words),
    "buffer:call-chain-addbagitem": (None, _addbagitem_words),
}

CASES = _cases()


def _substitute(blob, words):
    """-> blob with every aligned occurrence of each old word replaced, and how many were."""
    out, count = bytearray(blob), 0
    for at in range(0, len(out) - 3, 4):
        new = words.get(bytes(out[at:at + 4]))
        if new is not None:
            out[at:at + 4] = new
            count += 1
    return bytes(out), count


def test_every_recorded_case_has_a_builder():
    assert sorted(set(REFERENCE) - set(CASES)) == []
    assert len(REFERENCE) == 69 + len(FLASH_IMAGES)


# Every recorded row but the three intended changes, which the two tests below hold instead.
HELD_TO_THE_REFERENCE = [
    pytest.param(case, build, id=f"{case}-{build.game_code}")
    for case in sorted(REFERENCE) if case not in FLASH_IMAGES
    for build in FRENCH if not (build is builds.BPGF and case in CORRECTED_ON_LEAFGREEN)]


@pytest.mark.parametrize("case, build", HELD_TO_THE_REFERENCE)
def test_the_french_bytes_are_the_recorded_ones(case, build):
    assert digest(CASES[case](build)) == REFERENCE[case][build.game_code]


@pytest.mark.parametrize("case", sorted(FLASH_IMAGES))
def test_the_guarded_flash_images_changed_and_nothing_else_is_new(case):
    """The guarded image differs from the recorded one; only its operand row is held."""
    for build in FRENCH:
        assert digest(CASES[case](build)) != REFERENCE[case][build.game_code]


@pytest.mark.parametrize("case", sorted(CORRECTED_ON_LEAFGREEN))
def test_french_leafgreen_differs_only_by_its_corrected_addresses(case):
    field, words = CORRECTED_ON_LEAFGREEN[case]
    firered, leafgreen = CASES[case](builds.BPRF), CASES[case](builds.BPGF)
    assert digest(firered) == REFERENCE[case]["BPGF"]          # what French LeafGreen got before
    if field is None:
        expected, count = _substitute(firered, words())
    else:
        corrected, count = _substitute(getattr(firered, field), words())
        expected = dataclasses.replace(firered, **{field: corrected})
    assert count == len(words())
    assert expected == leafgreen

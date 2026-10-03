"""Gift files preserve the bytes delivered by the existing full game stacks."""

import json
from pathlib import Path

import pytest

import frlg_mg_host
import swsh_gift_host
from pokeldn import gifts
from pokeldn.app import command, gift_files
from pokeldn.app.catalog import GAMES
from pokeldn.app.settings import Settings
from pokeldn.frlg import config
from pokeldn.frlg.gift import gift_to_bin, mg_server, mystery_gift
from pokeldn.frlg.gift import builder as frlg_builder, file as frlg_file
from pokeldn.frlg.rom import builds
from pokeldn.frlg.rom import buffer_script, scrcmd
from pokeldn.swsh import beacon, wc8
from tests.test_frlg_build_selection import _drive, _session
from tests.test_mystery_gift_end_to_end import _run_full_stack

TOOLS = {tool.key: tool for game in GAMES for tool in game.tools}


@pytest.mark.parametrize("code,version", [("BPRF", "firered"), ("BPGE", "leafgreen")])
def test_exported_frlg_gift_reaches_the_correct_cartridge_unchanged(tmp_path, code, version):
    path = tmp_path / "celebi.pokegift"
    original = config.MysteryGiftPayload(gift="celebi")
    expected = original.build_distribution(builds.BUILDS[code])
    assert frlg_mg_host.main(["--gift", "celebi", "--console-build", code,
                              "--export-gift", str(path)]) == 0
    parser = frlg_mg_host.build_parser()
    run = frlg_mg_host.build_run_config(parser, parser.parse_args(["--gift-file", str(path)]))
    host, console = _session(run, game_code=code.encode(), version=version)
    _drive(host, console)
    assert console.error is None
    assert console.saved_card == expected.card
    assert console.saved_ram_script == expected.ram_script.ljust(1024, b"\0")
    assert host.server.build.game_code == code


def test_native_frlg_pair_round_trips_through_the_impaired_radio(tmp_path):
    source = config.MysteryGiftPayload(gift="celebi").build_distribution(builds.BPRF)
    card, script = gift_to_bin.build_gift_bins(source.card, source.ram_script)
    gift = frlg_file.from_bins(card, script, build="BPRF", name="Celebi")
    path = tmp_path / "celebi.pokegift"
    gifts.save(path, gift)
    loaded = gifts.load(path, game="frlg")
    distribution = frlg_file.FilePayload(loaded).build_distribution(builds.BPRF)
    run = _run_full_stack(payload=distribution)
    assert run.console.saved_card == source.card
    assert run.console.saved_ram_script == source.ram_script.ljust(995, b"\0")
    exported = frlg_file.export_native(loaded, tmp_path / "native")
    assert [Path(p).read_bytes() for p in exported] == [card, script]
    # Declaring a cartridge is required; bytes for another ROM cannot leak through.
    parser = frlg_mg_host.build_parser()
    config_ = frlg_mg_host.build_run_config(parser, parser.parse_args(["--gift-file", str(path)]))
    host, console = _session(config_, game_code=b"BPGE", version="leafgreen")
    with pytest.raises(mg_server.MysteryGiftServerError, match="NOTHING WAS SENT"):
        _drive(host, console)
    assert console.saved_card is None and console.saved_ram_script is None


def test_equal_frlg_variants_still_refuse_an_undeclared_cartridge(tmp_path):
    path = tmp_path / "gift.pokegift"
    gifts.save(path, frlg_file.from_payload(config.MysteryGiftPayload(gift="celebi")))
    parser = frlg_mg_host.build_parser()
    run = frlg_mg_host.build_run_config(parser, parser.parse_args(["--gift-file", str(path)]))
    host, console = _session(run, game_code=b"BPRD", version="firered")
    with pytest.raises(mg_server.MysteryGiftServerError, match="NOTHING WAS SENT"):
        _drive(host, console)
    assert console.saved_card is None and console.saved_ram_script is None


@pytest.mark.parametrize("gift", [p.args[1] for p in frlg_builder.PRESETS if p.args[0] == "--gift"])
def test_every_gui_frlg_preset_preserves_all_distribution_components(gift, tmp_path):
    payload = config.MysteryGiftPayload(gift=gift, questionnaire=(1, 2, 3, 4), denied_message="HELLO")
    saved = gifts.loads(gifts.dumps(frlg_file.from_payload(payload)))
    for code, variant in saved.variants.items():
        assert frlg_file.distribution(variant) == payload.build_distribution(builds.BUILDS[code])
    original = payload.build_distribution(builds.BPRF)
    if original.is_stamp or original.has_trainer or original.has_mevent:
        with pytest.raises(ValueError, match="cannot preserve"):
            frlg_file.export_native(saved, tmp_path, build="BPRF")


def test_news_file_selects_the_news_flow_and_preserves_the_message(tmp_path):
    path = tmp_path / "news.pokegift"
    assert frlg_mg_host.main(["--news", "berry", "--export-gift", str(path)]) == 0
    loaded = gifts.load(path, game="frlg")
    distribution = frlg_file.FilePayload(loaded).build_distribution(builds.BPRF)
    run = _run_full_stack(payload=distribution)
    assert run.console.saved_news == distribution.news
    assert run.console.saved_card is None


def test_wc8_round_trip_reassembles_the_original_record(tmp_path, monkeypatch):
    from pokeldn import pokemon
    raw = wc8.pokemon_card(25, level=45, nickname="POKELDN", ot="POKELDN", date=1539879960)
    native = tmp_path / "event.wc8"
    native.write_bytes(raw)
    path = tmp_path / "event.pokegift"
    # This case pins transport bytes; PKHeX validation has its own integration tests.
    monkeypatch.setattr(pokemon.SERVICE, "validate_gift", lambda rec: None)
    assert swsh_gift_host.main(["--record", str(native), "--export-gift", str(path)]) == 0
    args = swsh_gift_host.build_parser().parse_args(["--gift-file", str(path)])
    record = swsh_gift_host.build_record(args)
    assert beacon.reassemble(beacon.build_message(record)) == raw
    paths = gifts.adapter("swsh").export_native(gifts.load(path), tmp_path / "native")
    assert paths[0].read_bytes() == raw


@pytest.mark.parametrize("change,message", [
    (lambda root: root.update(version=99), "version"),
    (lambda root: root.update(game="sv"), "support"),
    (lambda root: root["variants"]["BPRF"]["data"]["card"].update(hex="00"), "SHA-256"),
    (lambda root: root["variants"]["BPRF"]["options"].update(questionnaire=[True, 2, 3, 4]), "integers"),
    (lambda root: root["variants"]["BPRF"]["options"].update(buffer_code="anything"), "Unknown"),
])
def test_bad_files_are_refused_before_a_launcher_can_use_them(change, message):
    root = json.loads(gifts.dumps(frlg_file.from_payload(config.MysteryGiftPayload(gift="celebi"))))
    change(root)
    with pytest.raises(ValueError, match=message):
        gifts.loads(json.dumps(root))


def test_cross_game_and_duplicate_fields_are_refused():
    text = gifts.dumps(frlg_file.from_payload(config.MysteryGiftPayload(gift="celebi")))
    with pytest.raises(ValueError, match="not swsh"):
        gifts.loads(text, game="swsh")
    with pytest.raises(ValueError, match="Duplicate"):
        gifts.loads(text.replace('"version": 2', '"version": 2, "version": 2'))
    with pytest.raises(ValueError, match="256 KiB"):
        gifts.loads(" " * (gifts.MAX_FILE_SIZE + 1))


def test_corrupt_native_pairs_cannot_be_imported():
    source = config.MysteryGiftPayload(gift="celebi").build_distribution(builds.BPRF)
    card, script = gift_to_bin.build_gift_bins(source.card, source.ram_script)
    for bad_card, bad_script in ((card[:-1], script), (bytes(336), script), (card, bytes(1004))):
        with pytest.raises(ValueError):
            frlg_file.from_bins(bad_card, bad_script, build="BPRF")


def _wc3(card, script):
    """A .wc3 laid out as Project Pokemon's gallery files are: card bin, 0x50 metadata bytes, then
    the RamScript with its CRC16 over 1000 bytes."""
    card_bin, script_bin = gift_to_bin.build_gift_bins(card, script)
    script_bin = mystery_gift.crc16(script_bin[4:1004]).to_bytes(2, "little") + script_bin[2:]
    return card_bin + bytes(0x50) + script_bin


@pytest.mark.parametrize("code,version", [("BPRF", "firered"), ("BPGE", "leafgreen")])
def test_wc3_file_reaches_any_cartridge_through_the_launcher(tmp_path, code, version):
    source = config.MysteryGiftPayload(gift="celebi").build_distribution(builds.BPRF)
    path = tmp_path / "celebi.wc3"
    path.write_bytes(_wc3(source.card, source.ram_script))
    parser = frlg_mg_host.build_parser()
    run = frlg_mg_host.build_run_config(parser, parser.parse_args(["--gift-file", str(path)]))
    host, console = _session(run, game_code=code.encode(), version=version)
    _drive(host, console)
    assert console.error is None
    assert console.saved_card == source.card
    assert console.saved_ram_script == source.ram_script.ljust(1024, b"\0")
    assert host.server.build.game_code == code


def test_wc3_refuses_japanese_files_corruption_and_cartridge_addresses():
    source = config.MysteryGiftPayload(gift="celebi").build_distribution(builds.BPRF)
    raw = _wc3(source.card, source.ram_script)
    with pytest.raises(ValueError, match="Japanese"):
        frlg_file.from_wc3(raw[:frlg_file.WC3_JAPANESE_SIZE])
    with pytest.raises(ValueError, match="script checksum"):
        frlg_file.from_wc3(raw[:-1] + b"\1")
    rom_goto = bytes([scrcmd.OP_GOTO]) + (0x08160000).to_bytes(4, "little")
    tied = _wc3(source.card, rom_goto)
    with pytest.raises(ValueError, match="0x08160000"):
        frlg_file.from_wc3(tied)
    assert set(frlg_file.from_wc3(tied, build="BPRE").variants) == {"BPRE"}


def test_gui_card_icon_reaches_the_console_and_changes_only_the_icon(tmp_path, monkeypatch):
    from pokeldn.app import gift_builder
    monkeypatch.setattr(gift_builder, "SESSION", tmp_path)
    source = config.MysteryGiftPayload(gift="celebi").build_distribution(builds.BPRF)
    path = tmp_path / "celebi.wc3"
    path.write_bytes(_wc3(source.card, source.ram_script))
    tool, values = TOOLS["frlg-gift"], {"--gift-file": {"mode": "file", "file": str(path), "icon": 6}}
    command.prepare(tool, values)
    args = command.build(tool, values, {}, Settings())
    parser = frlg_mg_host.build_parser()
    run = frlg_mg_host.build_run_config(parser, parser.parse_args(args[args.index("--gift-file"):][:2]))
    host, console = _session(run, game_code=b"BPRF", version="firered")
    _drive(host, console)
    assert console.saved_card == source.card[:2] + (6).to_bytes(2, "little") + source.card[4:]
    assert console.saved_ram_script == source.ram_script.ljust(1024, b"\0")
    with pytest.raises(ValueError, match="species from 0 to 411"):
        frlg_file.with_icon(frlg_file.from_wc3(path.read_bytes()), 412)


def test_gui_file_source_omits_the_previous_preset_and_uses_the_same_exporter(tmp_path):
    tool = TOOLS["frlg-gift"]
    settings = Settings()
    gift = gift_files.build(tool, {"--gift-file": {"mode": "preset", "preset": "celebi"}}, {}, settings)
    path = tmp_path / "gift.pokegift"
    gifts.save(path, gift)
    values = {"--gift-file": {"mode": "file", "preset": "master-ball", "file": str(path)}}
    args = command.build(tool, values, {}, settings)
    assert not {"--gift", "--news"}.intersection(args)
    assert command.problems(tool, values) == []
    assert gifts.dumps(gift_files.build(tool, values, {}, settings)) == gifts.dumps(gift)
    assert command.problems(TOOLS["swsh-gift"], {"--gift-file": str(path)})


@pytest.mark.parametrize("flag_id,message", [
    ("10001", "card flagId 10001 out of range"),
    ("abc", "argument --flag-id: invalid int value"),
])
def test_gui_export_reports_the_invalid_card_id_and_recovers(tmp_path, flag_id, message):
    tool, settings = TOOLS["frlg-gift"], Settings()
    values = {"--gift-file": {"mode": "preset", "preset": "beast-cutscene"}}
    with pytest.raises(ValueError, match=message):
        gift_files.build(tool, values, {"--flag-id": flag_id}, settings)
    path = tmp_path / "beast.pokegift"
    gifts.save(path, gift_files.build(tool, values, {}, settings))
    parser = frlg_mg_host.build_parser()
    run = frlg_mg_host.build_run_config(parser, parser.parse_args(["--gift-file", str(path)]))
    host, console = _session(run, game_code=b"BPRF", version="firered")
    _drive(host, console)
    expected = config.MysteryGiftPayload(gift="beast-cutscene").build_distribution(builds.BPRF)
    assert console.error is None
    assert console.saved_card == expected.card
    assert console.saved_ram_script == expected.ram_script.ljust(1024, b"\0")


def test_old_wc8_gui_settings_still_reach_the_launcher(tmp_path):
    native = tmp_path / "gift.wc8"
    native.write_bytes(wc8.pokemon_card(25))
    args = command.build(TOOLS["swsh-gift"], {"--record": str(native)}, {}, Settings())
    parsed = swsh_gift_host.build_parser().parse_args(args)
    assert parsed.record == str(native)
    assert "--species" not in args


@pytest.mark.skipif(not buffer_script.emulation_available(), reason="offline execution needs Unicorn")
def test_custom_arm_file_executes_and_returns_its_result_over_the_impaired_radio(tmp_path):
    # ARMv4T: mov r3,#66; str r3,[r0]; mov r0,#1; bx lr. No registry entry.
    code = bytes.fromhex("4230a0e3003080e50100a0e31eff2fe1")
    binary, path = tmp_path / "payload.bin", tmp_path / "custom.pokegift"
    binary.write_bytes(code)
    assert gifts.main(["import", "--game", "frlg", "--code", str(binary), "--build", "BPRF",
                       "--expect", "66", "-o", str(path)]) == 0
    parser = frlg_mg_host.build_parser()
    config_ = frlg_mg_host.build_run_config(parser, parser.parse_args(["--gift-file", str(path)]))
    run = _run_full_stack(payload=config_.payload.build_distribution(builds.BPRF))
    assert run.engine.server.buffer_status == 66 and run.engine.server.buffer_matched
    assert run.console.saved_card is None and run.radio.dropped
    host, console = _session(config_, game_code=b"BPGE", version="leafgreen")
    with pytest.raises(mg_server.MysteryGiftServerError, match="NOTHING WAS SENT"):
        _drive(host, console)
    assert console.buffer_scripts == []


@pytest.mark.skipif(not buffer_script.emulation_available(), reason="offline execution needs Unicorn")
def test_saved_console_payload_keeps_its_dump_protocol_and_output_path(tmp_path):
    path, dump = tmp_path / "save.pokegift", tmp_path / "returned.bin"
    assert frlg_mg_host.main(["--buffer-script", "save-dump", "--dump-size", "4", "--dump-offset",
                             str(buffer_script.SAV2_PLAYER_TRAINER_ID), "--export-gift", str(path)]) == 0
    parser = frlg_mg_host.build_parser()
    config_ = frlg_mg_host.build_run_config(parser, parser.parse_args(
        ["--gift-file", str(path), "--dump-file", str(dump)]))
    run = _run_full_stack(payload=config_.payload.build_distribution(builds.BPRF))
    assert run.engine.server.buffer_dump == run.console.save_trainer_id.to_bytes(4, "little")
    from pokeldn.frlg.gift.host_mg_app import BufferScriptHostApplication
    from types import SimpleNamespace
    BufferScriptHostApplication._write_dump(SimpleNamespace(
        config=config_, session=SimpleNamespace(activity=run.engine)))
    assert dump.read_bytes() == run.console.save_trainer_id.to_bytes(4, "little")


@pytest.mark.parametrize("script,options", [
    ("install-resident", {"resident_name": "noencounter", "write_unsafe": True}),
    ("memory-dump-scatter", {"dump_addresses": (0x080CE040, 0x0804A2A0), "dump_size": 64}),
    ("rng-trace", {"trace_address": 0x03005000, "trace_samples": 4}),
    ("save-write", {"write_resident": ("follower", ())}),             # two leads, then install-kept
])
def test_shared_code_files_preserve_built_payloads_and_response_metadata(script, options):
    source = config.BufferScriptPayload(script=script, **options)
    loaded = gifts.loads(gifts.dumps(frlg_file.from_payload(source)))
    for code, variant in loaded.variants.items():
        assert frlg_file.distribution(variant) == source.build_distribution(builds.BUILDS[code])


def test_console_code_files_refuse_bad_protocol_options_and_mixed_gift_data():
    code = bytes.fromhex("0100a0e31eff2fe1")  # mov r0,#1; bx lr
    for data, options in [({"buffer_code": b"123"}, {}),
                          ({"buffer_code": code}, {"buffer_dump_size": "4"}),
                          ({"buffer_code": code}, {"buffer_expect": -1}),
                          ({"buffer_code": code}, {"buffer_dump_blocks": 2}),
                          ({"buffer_code": code}, {"buffer_decode": "unknown"}),
                          ({"buffer_code": code}, {"buffer_reference": "/local/image.gba"}),
                          ({"buffer_code": code, "card": bytes(332)}, {}),
                          ({"buffer_code": code, "buffer_lead_2": code}, {}),
                          ({"card": bytes(332), "buffer_lead_1": code}, {})]:
        with pytest.raises(ValueError):
            gifts.Gift("frlg", "Bad payload", {"BPRF": gifts.Variant(data, options)})


def test_a_saved_console_code_file_replaces_the_preset_and_old_gift_files_still_load(tmp_path):
    tool = TOOLS["frlg-gift"]
    gift = gift_files.build(tool, {"--gift-file": {"mode": "preset", "preset": "trainer-id"}}, {}, Settings())
    path = tmp_path / "code.pokegift"
    gifts.save(path, gift)
    values = {"--gift-file": {"mode": "file", "preset": "hook-turbo", "file": str(path)}}
    assert "--buffer-script" not in command.build(tool, values, {}, Settings())
    assert command.problems(tool, values) == []
    assert gifts.dumps(gift_files.build(tool, values, {}, Settings())) == gifts.dumps(gift)
    parser = frlg_mg_host.build_parser()
    with pytest.raises(SystemExit):
        frlg_mg_host.build_run_config(parser, parser.parse_args(
            ["--gift-file", str(path), "--dump-size", "32"]))
    source = gifts.dumps(frlg_file.from_payload(config.MysteryGiftPayload(gift="celebi")))
    assert gifts.loads(source.replace('"version": 2', '"version": 1')).name == "celebi"
    with pytest.raises(ValueError, match="version 2"):
        gifts.loads(gifts.dumps(gift).replace('"version": 2', '"version": 1'))

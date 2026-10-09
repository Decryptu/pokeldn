"""The app's gift builder: what it builds reaches the simulated console through the real launcher."""

import random
import struct

import pytest

import frlg_mg_host
import swsh_gift_host
from pokeldn import gifts
from pokeldn.app import command, gift_builder
from pokeldn.app.catalog import GAMES
from pokeldn.app.settings import Settings
from pokeldn.frlg.gift import builder as frlg, gift_composer as gc
from pokeldn.frlg.rom import buffer_script, builds, custom_code, mystery_event
from pokeldn.swsh import gift_builder as swsh, wc8
from tests.test_frlg_build_selection import _drive, _session
from tests.test_mystery_gift_end_to_end import _run_full_stack

TOOLS = {tool.key: tool for game in GAMES for tool in game.tools}
# ARMv4T: mov r3,#66; str r3,[r0]; mov r0,#1; bx lr
ANSWER_66 = bytes.fromhex("4230a0e3003080e50100a0e31eff2fe1")


def _launch(tool, value, monkeypatch, tmp_path, version="firered"):
    monkeypatch.setattr(gift_builder, "SESSION", tmp_path)
    values = {"--gift-file": value, "--version": version}
    assert command.problems(tool, values) == []
    command.prepare(tool, values)
    return command.build(tool, values, {}, Settings(), stamp="T")


def _frlg_run(args):
    parser = frlg_mg_host.build_parser()
    return frlg_mg_host.build_run_config(parser, parser.parse_args(args))


@pytest.mark.parametrize("code,version", [("BPRF", "firered"), ("BPGF", "leafgreen"),
                                          ("BPRE", "firered"), ("BPGE", "leafgreen")])
def test_a_built_card_reaches_every_cartridge_as_compiled(code, version, monkeypatch, tmp_path):
    state = frlg.blank()
    state["steps"].append({"type": "item", "item": 1, "quantity": 2})
    args = _launch(TOOLS["frlg-gift"], {"mode": "build", "build": state}, monkeypatch, tmp_path, version)
    host, console = _session(_frlg_run(args), game_code=code.encode(), version=version)
    _drive(host, console)
    expected = gc.compile_definition(frlg.definition(state), build=builds.BUILDS[code])
    assert console.error is None
    assert console.saved_card == expected.card
    assert console.saved_ram_script == expected.ram_script.ljust(1024, b"\0")


def test_a_person_in_the_world_holds_the_built_steps(monkeypatch, tmp_path):
    state = frlg.blank()
    state["giver"] = "mom"
    args = _launch(TOOLS["frlg-gift"], {"mode": "build", "build": state}, monkeypatch, tmp_path)
    host, console = _session(_frlg_run(args), game_code=b"BPRF", version="firered")
    _drive(host, console)
    bound = [effect for result in console.mevent_results for effect in result.effects
             if effect[0] == "initramscript"]
    assert console.error is None and len(bound) == 1
    assert bound[0][1:4] == (4, 0, 1)   # the player's house, Mom
    script = gc.build_bound_script(tuple(frlg._action(step) for step in state["steps"]), slug="mystery-event-npc")
    assert mystery_event.describe(console.activation_scripts[0]).count("initramscript") == 1
    assert script in console.activation_scripts[0]


def test_built_news_is_saved_by_the_console(monkeypatch, tmp_path):
    state = frlg.blank()
    state.update(kind="news", news={"title": "HELLO", "lines": ["One", "Two"], "id": 7})
    args = _launch(TOOLS["frlg-gift"], {"mode": "build", "build": state}, monkeypatch, tmp_path, "leafgreen")
    host, console = _session(_frlg_run(args), game_code=b"BPGE", version="leafgreen")
    _drive(host, console)
    assert console.saved_news[:2] == (7).to_bytes(2, "little")


@pytest.mark.skipif(not buffer_script.emulation_available(), reason="offline execution needs Unicorn")
def test_a_prebuilt_binary_runs_and_answers_over_the_impaired_radio(monkeypatch, tmp_path):
    binary = tmp_path / "answer.bin"
    binary.write_bytes(ANSWER_66)
    state = frlg.blank()
    state.update(kind="code", code={"source": "", "binary": str(binary), "expect": "66", "dump_size": ""})
    assert custom_code.check(ANSWER_66).param == 66
    args = _launch(TOOLS["frlg-gift"], {"mode": "build", "build": state}, monkeypatch, tmp_path)
    run = _run_full_stack(payload=_frlg_run(args).payload.build_distribution(builds.BPGE))
    assert run.engine.server.buffer_status == 66 and run.engine.server.buffer_matched


@pytest.mark.skipif(not buffer_script.emulation_available(), reason="offline execution needs Unicorn")
def test_code_that_never_returns_is_refused_before_it_is_sent():
    with pytest.raises(custom_code.CodeError, match="hang"):
        custom_code.check(bytes.fromhex("feffffea"))   # b .


@pytest.mark.skipif(custom_code.toolchain() is None, reason="no GNU Arm toolchain")
def test_the_template_assembles_and_reads_the_trainer_id_and_errors_name_their_line():
    result = custom_code.check(custom_code.assemble(custom_code.TEMPLATE))
    assert result.param == custom_code.SAMPLE_TRAINER_ID & 0xFFFF
    with pytest.raises(custom_code.CodeError) as error:
        custom_code.assemble("    mov r0, #1\n    nonsense r1\n")
    assert error.value.line == 2


PRESETS = [("frlg-gift", p.key) for p in frlg.PRESETS] + [("swsh-gift", p.key) for p in swsh.PRESETS]


@pytest.mark.parametrize("key,preset", PRESETS, ids=[f"{k}:{p}" for k, p in PRESETS])
def test_every_preset_is_accepted_by_its_launcher(key, preset, monkeypatch, tmp_path):
    args = _launch(TOOLS[key], {"mode": "preset", "preset": preset}, monkeypatch, tmp_path)
    if key == "frlg-gift":
        _frlg_run(args)
    else:
        assert wc8.sealed(swsh_gift_host.build_record(swsh_gift_host.build_parser().parse_args(args)))


def test_a_customized_preset_keeps_what_the_registered_card_gives():
    state = frlg.PRESET["celebi"].state
    assert state["card"]["title"] == "CELEBI GIFT"
    assert [s for s in state["steps"] if s["type"] == "pokemon"] == [
        {"type": "pokemon", "species": 251, "level": 50, "item": 0, "moves": [73, 105, 215, 219]}]
    assert frlg.PRESET["beast-cutscene"].state is None   # conditional sprites: no form for them


def test_form_errors_name_the_field_to_fix():
    state = frlg.blank()
    state["card"]["title"] = "X" * 40
    with pytest.raises(ValueError, match="^Card title"):
        frlg.compile(state)
    state = frlg.blank()
    state["steps"][0]["level"] = 101
    with pytest.raises(ValueError, match="^Step 1"):
        frlg.compile(state)


def test_the_sword_pikachu_preset_is_the_record_the_launcher_builds():
    args = swsh_gift_host.build_parser().parse_args(
        ["--species", "25", "--level", "25", "--move1", "84", "--move2", "45", "--move3", "86",
         "--move4", "98", "--nickname", "POKELDN", "--ot", "POKELDN"])
    random.seed(7)
    built = swsh.record(swsh.PRESET["pikachu"].state)
    random.seed(7)
    assert built[8:] == swsh_gift_host.build_record(args)[8:]   # +0x00 is the date


def _pkhex_available():
    from pokeldn import pokemon
    try:
        pokemon._command()
    except pokemon.BuilderError:
        return False
    return True


@pytest.mark.skipif(not _pkhex_available(), reason="needs the PKHeX helper")
def test_a_built_card_fixes_the_gender_so_the_reveal_and_the_party_agree():
    """Gender 3 rolls once for the reveal and once for the party: a retail Sword showed a female and
    gave a male. A card that fixes 0 or 1 skips both rolls."""
    from pokeldn.swsh import wc8
    off = wc8.POKEMON["gender"][0]
    pikachu = {swsh.record(dict(swsh.PRESET["pikachu"].state))[off] for _ in range(40)}
    assert pikachu == {0, 1}
    chansey = swsh.record(dict(swsh.PRESET["pikachu"].state, species=113))[off]
    assert chansey == 0          # female only: the game's build forces it


def test_sword_item_and_egg_cards_carry_the_bytes_a_retail_sword_redeemed():
    # Three Master Balls: kind 2, title index 3, (1, 3) at +0x20; an egg: +0x245 = 1, title index 1.
    items = swsh.record(swsh.PRESET["master-balls"].state)
    assert (items[0x11], items[0x15], items[0x20:0x24]) == (2, 3, bytes.fromhex("01000300"))
    egg = swsh.record(swsh.PRESET["egg"].state)
    assert (egg[0x11], egg[0x15], egg[0x244], egg[0x245]) == (1, 1, 1, 1)
    # Battle Points: the EventsGallery "Battle Points x10" card carries kind 3, title 39, 10 at +0x20
    # and zero at +0x1C; with title 1 a retail Sword listed the card as a Pokemon egg.
    bp = swsh.record(swsh.PRESET["bp"].state)
    assert (bp[0x11], bp[0x15], bp[0x1C], struct.unpack_from("<I", bp, 0x20)[0]) == (3, 39, 0, 10)


def test_a_stored_path_and_a_bad_file_are_read_as_an_opened_file(tmp_path):
    tool = TOOLS["swsh-gift"]
    native = tmp_path / "card.wc8"
    native.write_bytes(wc8.pokemon_card(25))
    assert command.build(tool, {"--record": str(native)}, {}, Settings())[:2] == ["--gift-file", str(native)]
    frlg_file = tmp_path / "frlg.pokegift"
    gifts.save(frlg_file, frlg.compile(frlg.blank()))
    assert "swsh" in command.problems(tool, {"--gift-file": str(frlg_file)})[0]


@pytest.mark.skipif(not buffer_script.emulation_available(), reason="offline execution needs Unicorn")
def test_a_code_gift_that_hangs_cannot_start_and_a_chosen_cartridge_is_its_only_target(tmp_path):
    tool, binary = TOOLS["frlg-gift"], tmp_path / "loop.bin"
    binary.write_bytes(bytes.fromhex("feffffea"))
    state = frlg.blank()
    state.update(kind="code", code={"source": "", "binary": str(binary), "expect": "", "dump_size": "",
                                    "build": "BPGE"})
    assert "hang" in command.problems(tool, {"--gift-file": {"mode": "build", "build": state}})[0]
    binary.write_bytes(ANSWER_66)
    assert set(frlg.compile(state).variants) == {"BPGE"}



B, SELECT = 0x2, 0x4


def _boosts(on, keep=None, **settings):
    chosen = {"on": on, **settings}
    if keep is not None:
        chosen["keep"] = keep
    return {"mode": "preset", "preset": "boosts", "options": {"boosts": chosen}}


@pytest.mark.skipif(not buffer_script.emulation_available(), reason="offline execution needs Unicorn")
@pytest.mark.parametrize("value,name,params", [
    (_boosts(["hook-turbo"], True, **{"hook-turbo": {"speed": "3", "button": "0x2"}}), "turbo-lite",
     {"extra": 4, "field": 2, "battle": 2, "hold": B, "budget": 228}),
    (_boosts(["hook-turbo"], True, **{"hook-turbo": {"speed": "4", "where": "battle", "text": False,
                                                    "button": "always"}}), "turbo-lite",
     {"extra": 0, "field": 0, "battle": 3, "hold": 0, "budget": 228}),
    (_boosts(["hook-shiny"], True, **{"hook-shiny": {"button": "0x4", "slower": "7"}}), "shiny",
     {"slow": SELECT, "slow_frames": 7}),
    (_boosts(["hook-noclip", "hook-turbo"], True, **{"hook-noclip": {"button": "0x2"}}), "turbo-lite+noclip",
     {"turbo-lite.extra": 4, "turbo-lite.field": 1, "turbo-lite.battle": 1, "turbo-lite.hold": 0x100,
      "noclip.hold": B}),
    ({"mode": "preset", "preset": "save-noclip"}, "noclip", {"hold": 0x100}),   # an older settings file
    (_boosts(["hook-follower"], False), "follower", {}),        # too large for one session: always kept
])
def test_boosts_kept_in_the_save_carry_their_settings(value, name, params, monkeypatch, tmp_path):
    from tests.test_resident_save import _session as kept_session
    args = _launch(TOOLS["frlg-gift"], value, monkeypatch, tmp_path)
    host, client = kept_session(None, payload=_frlg_run(args).payload)
    blob = buffer_script.build_resident_save_blob(name, **params)
    assert client.sav2[0xB20:0xB20 + len(blob)] == blob
    assert host.server.buffer_status == builds.BPRF.vblank_intr | 1


@pytest.mark.skipif(not buffer_script.emulation_available(), reason="offline execution needs Unicorn")
def test_three_boosts_left_out_of_the_save_install_together_in_one_session(monkeypatch, tmp_path):
    value = _boosts(["hook-noencounter", "hook-noclip", "hook-turbo"],
                    **{"hook-turbo": {"speed": "2", "where": "field"}})
    payload = _frlg_run(_launch(TOOLS["frlg-gift"], value, monkeypatch, tmp_path)).payload
    code = buffer_script.build_install_resident("turbo-lite+noclip+noencounter", build=builds.BPRF, **{
        "turbo-lite.extra": 4, "turbo-lite.field": 1, "turbo-lite.battle": 0, "turbo-lite.hold": 0x100,
        "noclip.hold": 0x100})
    assert payload.build_distribution(builds.BPRF).buffer_code == code
    run = _run_full_stack(payload=payload.build_distribution(builds.BPRF))
    assert run.engine.server.buffer_status == builds.BPRF.vblank_intr | 1   # the game's handler, chained


def _combinations(options):
    import itertools
    choices = [[(o.key, v) for v in ((True, False) if not o.choices else [k for k, _ in o.choices])]
               for o in options]
    return [dict(combo) for combo in itertools.product(*choices)]


def test_every_set_of_boosts_is_sent_or_refused_with_a_reason():
    import itertools
    boosts = frlg.PRESET["boosts"]
    keys = [b.key for b in frlg.BOOST_LIST]
    sent = set()
    for count in range(1, len(keys) + 1):
        for on in itertools.combinations(keys, count):
            for keep in (False, True):
                chosen = {"on": list(on), "keep": keep}
                if boosts.problem(chosen):
                    continue
                config = _frlg_run([*boosts.arguments(chosen), "--version", "firered"]).payload
                for code in frlg.CARTRIDGES:
                    config.build_distribution(builds.BUILDS[code])
                sent.add(on)
    assert ("hook-turbo", "hook-noclip", "hook-noencounter") in sent
    assert all(len(on) == 1 for on in sent if "hook-follower" in on)
    assert not any({"hook-shiny", "hook-ivs"} <= set(on) for on in sent)


@pytest.mark.parametrize("boost", [b for b in frlg.BOOST_LIST if b.options], ids=lambda b: b.key)
def test_every_setting_of_a_boost_fits_every_cartridge_and_the_launcher(boost):
    boosts = frlg.PRESET["boosts"]
    for settings in _combinations(boost.options):
        chosen = {"on": [boost.key], boost.key: settings}
        if boost.key == "hook-turbo" and settings["speed"] == "1" and not settings["text"]:
            assert boosts.problem(chosen)              # nothing would change: refused
            continue
        assert boosts.problem(chosen) == "", settings
        config = _frlg_run([*boosts.arguments(chosen), "--version", "firered"]).payload
        for code in frlg.CARTRIDGES:
            config.build_distribution(builds.BUILDS[code])


@pytest.mark.skipif(not _pkhex_available(), reason="needs the PKHeX helper")
def test_pkhex_takes_every_sword_preset_and_refuses_what_the_game_cannot_hold():
    from pokeldn import pokemon
    for preset in swsh.PRESETS:
        pokemon.SERVICE.validate_gift(swsh.record(preset.state))
    gmax = swsh.record(swsh.PRESET["gmax-pikachu"].state)
    assert (gmax[0x15], gmax[wc8.POKEMON["gigantamax"][0]], gmax[wc8.POKEMON["dynamax_level"][0]]) == (21, 1, 10)
    with pytest.raises(pokemon.BuilderError, match="Gigantamax"):
        pokemon.SERVICE.validate_gift(swsh.record(dict(swsh.PRESET["gmax-pikachu"].state, species=26)))
    cape = bytearray(swsh.record(swsh.PRESET["gold-backpack"].state))
    struct.pack_into("<II", cape, 0x20, 15, 0)                # the setter 0x0143a450 takes categories 0..14
    with pytest.raises(pokemon.BuilderError, match="clothing"):
        pokemon.SERVICE.validate_gift(wc8.seal(cape))


@pytest.mark.skipif(not _pkhex_available(), reason="needs the PKHeX helper")
def test_the_sword_item_picker_offers_exactly_what_the_validator_accepts():
    """The picker once listed the whole item table: 790 refused ids, 51 of them "???" placeholders."""
    from pokeldn import pokemon
    offered = {e["id"]: e["name"] for e in pokemon.SERVICE.names("swsh", "bag")}
    accepted = set()
    for item in range(1, swsh.MAX_ITEM + 1):
        try:
            pokemon.SERVICE.validate_gift(swsh.record(swsh.blank(kind="items", items=[[item, 1]])))
            accepted.add(item)
        except pokemon.BuilderError:
            pass
    assert set(offered) == accepted
    assert "???" not in offered.values()


@pytest.mark.parametrize("preset, stale, sent", [
    ("event-wishmkr-jirachi", {"--gift": "celebi"}, "event-pokemon"),   # "--event-pokemon belongs to --gift"
    ("celebi", {"--buffer-script": "trainer-id-probe"}, "celebi"),       # "not allowed with argument --gift"
    ("celebi", {"--gift": "worlds-xp"}, "celebi"),                        # the stale card, sent silently
])
def test_an_all_options_value_for_a_flag_the_gift_card_sets_never_reaches_the_launcher(
        preset, stale, sent, monkeypatch, tmp_path):
    """A player's saved All options value came after the Gift card's flags; the launcher refused the
    run or sent the other card. The real launcher parses what the app builds."""
    assert preset in frlg.PRESET
    monkeypatch.setattr(gift_builder, "SESSION", tmp_path)
    values = {"--gift-file": {"mode": "preset", "preset": preset}, "--version": "firered"}
    args = command.build(TOOLS["frlg-gift"], values, stale, Settings(), stamp="T")
    run = _frlg_run(args)
    assert run.payload.gift == sent

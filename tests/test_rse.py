"""Ruby, Sapphire and Emerald, prepared from the decomps ahead of a Switch release (docs/rse.md).

The official gift scripts are pinned to pokeemerald's own sources when ~/pokeemerald is present;
the Mystery Gift host serves an Emerald console through the whole leader stack."""
import pathlib
import re

import pytest

from pokeldn.frlg.gift import mg_client, mg_script, mg_server, wonder_card
from pokeldn.frlg.gift import gift_composer as gc
from pokeldn.frlg.link import linkplayer
from pokeldn.rse import constants as em, gifts
from pokeldn.rse.scripts import Script, VMESSAGE

DECOMP = pathlib.Path("~/pokeemerald").expanduser()
needs_decomp = pytest.mark.skipif(not (DECOMP / "data/scripts/gift_old_sea_map.inc").exists(),
                                  reason="pret/pokeemerald is not checked out at ~/pokeemerald")


def _decomp_constants():
    values = {"TRUE": 1, "FALSE": 0}
    defines = []
    for name in ("opponents.h", "flags.h", "vars.h"):
        path = DECOMP / "include/constants" / name
        if path.exists():
            defines += re.findall(r"^#define (\w+)\s+([^/\n]+)", path.read_text(), re.M)
    defines += re.findall(r"^#define (\w+)\s+([^/\n]+)",
                          (DECOMP / "src/data/wild_encounters.constants.json.txt").read_text(), re.M)
    items = (DECOMP / "include/constants/items.h").read_text()
    for index, name in enumerate(re.findall(r"^\s+(ITEM_\w+),", items[items.index("enum"):], re.M)):
        values[name] = index
    pending = dict(defines)
    for _ in range(8):
        for name, expression in list(pending.items()):
            try:
                values[name] = int(eval(expression.strip(), {}, dict(values)))
                del pending[name]
            except (NameError, SyntaxError, TypeError):
                pass
    values["VAR_RESULT"] = 0x800D
    return values


def _assemble_decomp(name, constants):
    """A gift_*.inc through pokeldn.rse.scripts.Script, its text left out: the bytecode a
    pokeldn script must match op for op."""
    s = Script()
    s.code.clear()
    for line in (DECOMP / "data/scripts" / name).read_text().splitlines():
        line = line.split("@")[0].strip()
        if not line or line.startswith(".string"):
            continue
        if line.endswith(":"):
            label = line.rstrip(":")
            s.labels[label] = len(s.code)
            continue
        macro, _, rest = line.partition(" ")
        args = [a.strip() for a in rest.split(",")] if rest else []
        value = lambda a: constants[a] if a in constants else int(eval(a, {}, dict(constants)))
        if macro == "setvaddress":
            s.setvaddress()
        elif macro in ("lock", "faceplayer", "release", "end", "waitmessage", "waitbuttonpress"):
            s.code.append({"lock": 0x6A, "faceplayer": 0x5A, "release": 0x6C, "end": 0x02,
                           "waitmessage": 0x66, "waitbuttonpress": 0x6D}[macro])
        elif macro in ("vgoto_if_set", "vgoto_if_eq", "vgoto_if_ne"):
            *operands, label = args
            getattr(s, macro)(*map(value, operands), label)
        elif macro == "vmessage":
            s.code.append(VMESSAGE)
            s.code += b"\x00" * 4
        elif macro in ("checkitem", "checkitemspace", "giveitem"):
            getattr(s, macro)(*map(value, args))
        elif macro in ("setflag",):
            s.op(0x29, value(args[0]))
        elif macro in ("addvar", "setvar"):
            s.op(0x17 if macro == "addvar" else 0x16, *map(value, args))
        else:
            raise AssertionError(f"{name}: macro {macro} is not in pokeldn.rse.scripts")
    return s.assemble()


def _without_text(script):
    """The bytecode up to its first text, every vmessage operand zeroed."""
    code = bytearray(script)
    out, i = bytearray(), 0
    while i < len(code):
        op = code[i]
        size = {0xB8: 5, 0x6A: 1, 0x5A: 1, 0x6C: 1, 0x02: 1, 0x66: 1, 0x6D: 1, 0x2B: 3, 0xBB: 6,
                0x21: 5, 0x47: 5, 0x46: 5, 0x1A: 5, 0x09: 2, 0x29: 3, 0x17: 5, 0x16: 5, 0xBD: 5}.get(op)
        if size is None:
            break
        chunk = code[i:i + size]
        if op == 0xBD:
            chunk = bytes([op]) + b"\x00" * 4
        out += chunk
        i += size
    return bytes(out)


@needs_decomp
@pytest.mark.parametrize("key,source", [("aurora-ticket", "gift_aurora_ticket.inc"),
                                        ("mystic-ticket", "gift_mystic_ticket.inc"),
                                        ("old-sea-map", "gift_old_sea_map.inc"),
                                        ("altering-cave", "gift_altering_cave.inc")])
def test_each_official_gift_is_the_decomps_bytecode(key, source):
    ours = _without_text(gifts.official(key).ram_script)
    theirs = _without_text(_assemble_decomp(source, _decomp_constants()))
    # Branch targets land after a vmessage whose text sits elsewhere: compare opcodes and operands,
    # vgoto targets only as offsets inside the code.
    assert len(ours) == len(theirs)
    assert ours == theirs


@needs_decomp
def test_the_emerald_numbers_are_the_decomps():
    c = _decomp_constants()
    for name in ("FLAG_RECEIVED_AURORA_TICKET", "FLAG_MYSTERY_GIFT_DONE", "FLAG_CAUGHT_MEW",
                 "FLAG_BATTLED_DEOXYS", "FLAG_ENABLE_SHIP_BIRTH_ISLAND", "FLAG_ENABLE_SHIP_NAVEL_ROCK",
                 "FLAG_ENABLE_SHIP_FARAWAY_ISLAND", "FLAG_SYS_NATIONAL_DEX", "VAR_ALTERING_CAVE_WILD_SET",
                 "VAR_GIFT_UNUSED_1", "VAR_STARTER_MON", "ITEM_OLD_SEA_MAP", "ITEM_AURORA_TICKET",
                 "ITEM_MYSTIC_TICKET", "ITEM_EON_TICKET", "NUM_ALTERING_CAVE_TABLES"):
        assert getattr(em, name) == c[name], name
    specials = re.findall(r"^\s*def_special (\w+)", (DECOMP / "data/specials.inc").read_text(), re.M)
    assert len(specials) == em.NUM_SPECIALS
    assert specials[em.SPECIAL_HAS_ALL_HOENN_MONS] == "HasAllHoennMons"
    assert specials[em.SPECIAL_START_LEGENDARY_BATTLE] == "BattleSetup_StartLegendaryBattle"
    assert specials[em.SPECIAL_GET_MYSTERY_GIFT_CARD_STAT] == "GetMysteryGiftCardStat"
    assert specials[em.SPECIAL_ENABLE_NATIONAL_POKEDEX] == "EnableNationalPokedex"


def _emerald_game_data(news=False):
    lp = linkplayer.LinkPlayer(name="MAY", version=linkplayer.VERSION_EMERALD, trainer_id=0x12345678)
    return mg_client.build_link_game_data(lp, version_code=0, game_code=b"BPEE", news=news)


def test_emerald_game_data_passes_emeralds_check_and_fails_firereds():
    """+0x0C/+0x10 carry 4/0x200 for a card [pokeemerald mystery_gift.c:358]; FireRed's check wants
    bit 0 and a version nibble, so it would turn every Emerald card session away."""
    card = mg_script.parse_link_game_data(_emerald_game_data())
    assert card.version_name == "Emerald"
    assert mg_script.validate_link_game_data(card)
    assert not mg_script.validate_link_game_data(
        mg_script.parse_link_game_data(_emerald_game_data()[:0x5C] + b"BPRE" + b"\x00" * 8))
    tampered = bytearray(_emerald_game_data())
    tampered[0x0C] = 1
    assert not mg_script.validate_link_game_data(mg_script.parse_link_game_data(bytes(tampered)))
    assert mg_script.validate_link_game_data(mg_script.parse_link_game_data(bytes(tampered)), news=True)


@pytest.mark.parametrize("gift_game,console,refused", [
    ("frlg", b"BPEE", True), ("emerald", b"BPRF", True), ("emerald", b"BPEF", False)])
def test_a_gift_is_sent_only_to_its_own_game(gift_game, console, refused):
    """A gift names its game's flags and variables; another game's console gets nothing."""
    lp = linkplayer.LinkPlayer(name="MAY", version=linkplayer.VERSION_EMERALD)
    raw = mg_client.build_link_game_data(lp, version_code=mg_script.VERSION_CODE_FIRERED, game_code=console)
    distribution = (gifts.official("old-sea-map") if gift_game == "emerald"
                    else None)
    card, script = (distribution.card, distribution.ram_script) if distribution else wonder_card.build_default_gift()
    server = mg_server.MysteryGiftServer(card, script, game=gift_game)
    server._received = raw
    if refused:
        with pytest.raises(mg_server.MysteryGiftServerError, match="Nothing was sent"):
            server._do_svr_copy_game_data()
    else:
        server._do_svr_copy_game_data()
        assert server.console_mismatch is None


def test_an_emerald_console_saves_an_emerald_card_through_the_whole_stack():
    from tests.test_mystery_gift_end_to_end import _run_full_stack
    from tests.test_mystery_gift_flow import ConsoleClientModel
    console = ConsoleClientModel(flag_id=0)
    console.game_data = _emerald_game_data()
    gift = gifts.official("aurora-ticket")
    run = _run_full_stack(console=console, payload=gift)
    assert run.console.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert run.console.saved_card == gift.card
    assert run.console.saved_ram_script.startswith(gift.ram_script)


def test_a_composed_gift_names_emeralds_flags_and_vars():
    definition = gc.WonderGift(
        slug="rare-candy", card=gc.WonderCardSpec(icon_species=25, title="RARE CANDY"),
        intro_message="A gift for you.", event=gc.GiftSpec(),
        delivery=gc.DeliveryPlan(delivery=(gc.DeliveryStage(gc.GiveItem(68)),)))
    frlg = gc.compile_definition(definition, flag_id=1004)
    emerald = gifts.composed(definition, flag_id=1004)
    assert emerald.game == "emerald"
    for value in (em.FLAG_MYSTERY_GIFT_DONE, em.VAR_GIFT_UNUSED_1):
        assert value.to_bytes(2, "little") in emerald.ram_script
    for value in (gc.FLAG_MYSTERY_GIFT_DONE, gc.VAR_MYSTERY_GIFT_1):
        assert value.to_bytes(2, "little") in frlg.ram_script
        assert value.to_bytes(2, "little") not in emerald.ram_script
    with pytest.raises(gc.GiftValidationError):
        gifts.composed(gc.WonderGift(
            slug="bad", card=gc.WonderCardSpec(icon_species=25, title="X"), intro_message="X",
            event=gc.GiftSpec(), delivery=gc.DeliveryPlan(delivery=(gc.DeliveryStage(
                gc.ReadSpecial(0x8004, em.NUM_SPECIALS)),))), flag_id=1004)


@pytest.mark.parametrize("version", ["emerald", "leafgreen"])
def test_the_host_advertises_the_national_flags_emerald_reads(version):
    """Emerald lists a host of another version as "not ready" unless canLinkNationally is set
    [pokeemerald union_room.c:1270]; a host posing as Emerald sets them, FireRed's bytes stay."""
    from dataclasses import replace
    from pokeldn.frlg import config
    from pokeldn.frlg.link import beacon, host_beacon
    profile = replace(config.DEFAULT_TRAINER, version=version)
    inactive, _ = host_beacon.build_trade_app_data(profile, b"\xb7\xf1")
    record = beacon.b85_decode(inactive[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]
    word = int.from_bytes(record[16:20], "little")
    assert (word & beacon.SEARCH_VERSION_MASK) >> beacon.SEARCH_VERSION_SHIFT == config.VERSIONS[version] & 7
    national = beacon.SEARCH_NATIONAL_LINK | beacon.SEARCH_NATIONAL_DEX | beacon.SEARCH_GAME_CLEAR
    assert word & national == (national if version == "emerald" else 0)
    compat = int.from_bytes(profile.build_rfu_game_data(beacon.ACTIVITY_TRADE)[2:4], "little")
    assert bool(compat & 0x80) == (version == "emerald")     # the NI game data's canLinkNationally


@needs_decomp
def test_the_hoenn_dex_is_the_decomps():
    text = (DECOMP / "include/constants/pokedex.h").read_text()
    national, hoenn = (re.findall(r"(\w+_DEX_\w+)", block) for block in re.findall(r"enum\s*\{(.*?)\}", text, re.S)[:2])
    number = {name.split("_DEX_")[1]: index for index, name in enumerate(national)}
    names = [name.split("_DEX_")[1] for name in hoenn[1:hoenn.index("HOENN_DEX_DEOXYS") + 1]]
    assert em.HOENN_DEX == tuple(number[name] for name in names)


@pytest.mark.parametrize("species,egg,national_dex,refused", [
    (25, False, False, False),     # Pikachu is #156 in the Hoenn dex
    (1, False, False, True),       # Bulbasaur is not
    (1, False, True, False),
    (277, False, False, False),    # internal 277 is Treecko
    (25, True, False, True),
])
def test_an_emerald_console_without_the_national_dex_refuses_what_its_trade_c_refuses(species, egg, national_dex, refused):
    assert em.refuses_offer(int(national_dex), species, egg) is refused


def test_a_banked_pk3_stays_a_firered_pokemon():
    """`rse` shares the .pk3 format and comes after `frlg`; a bank that read the extension backwards
    would file every FireRed Pokemon as Emerald, release builds included."""
    from pokeldn.app import bank
    assert bank.GAME_OF["pk3"] == "frlg"


def _pkhex_available():
    from pokeldn import pokemon
    try:
        pokemon._command()
    except pokemon.BuilderError:
        return False
    return True


def test_emerald_gift_file_round_trips_mevent_and_refuses_malformed_mevent():
    from pokeldn import gifts as giftmod
    from pokeldn.frlg.gift import wonder_card_events as events
    from pokeldn.rse import gift_file

    dist = gifts.composed(events.EVENT_POKEMON_GIFT)
    assert dist.game == "emerald" and dist.has_mevent
    saved = gift_file.from_distribution(dist, name="WISHMKR Jirachi")
    loaded = giftmod.loads(giftmod.dumps(saved), game="rse")
    rebuilt = gift_file.distribution(loaded.variants[gift_file.TARGET])
    assert rebuilt == dist

    base = dict(saved.variants[gift_file.TARGET].data)
    for bad in (b"", b"\x00", b"\x00" * 1025):
        with pytest.raises(ValueError):
            giftmod.Gift("rse", "Bad mevent", {gift_file.TARGET: giftmod.Variant({**base, "mevent": bad})})
    with pytest.raises(ValueError):
        giftmod.Gift("rse", "Extra component", {
            gift_file.TARGET: giftmod.Variant({**base, "trainer": b"\x00" * 188})})


def test_an_emerald_console_receives_an_event_pokemon_through_the_whole_stack():
    import frlg_mg_host
    from pokeldn.frlg.save.mon import decode_mon
    from tests.test_frlg_build_selection import _drive, _session

    parser = frlg_mg_host.build_parser()
    config = frlg_mg_host.build_run_config(
        parser, parser.parse_args(["--version", "emerald", "--gift", "event-pokemon"]))
    host, console = _session(config, game_code=b"BPEE", version="emerald")
    _drive(host, console)
    assert console.error is None
    assert console.saved_card == config.payload.distribution.card
    assert len(console.mevent_results) == 1
    assert console.mevent_results[0].status == 2
    mon = decode_mon(console.mevent_results[0].effects[0][1])
    assert (mon["species_name"], mon["otName"], mon["otid"] & 0xFFFF) == ("JIRACHI", "WISHMKR", 20043)


def test_every_compiled_emerald_preset_builds_valid_rse_gift_with_emerald_numbers():
    from pokeldn import gifts as giftmod
    from pokeldn.rse import gift_builder, gift_file

    compiled = [p for p in gift_builder.PRESETS if not p.args]
    assert {p.key for p in compiled} >= {
        "aurora-ticket", "mystic-ticket", "old-sea-map", "eon-ticket", "altering-cave",
        "wish-egg", "pokepark-egg", "pc-japan-egg", "battle-count-card",
        "box-swablu", "box-zigzagoon", "box-skitty", "surf-pichu",
        "national-dex", "rare-berries", "starter-egg", "master-ball", "rare-candy",
    }
    for preset in compiled:
        gift = gift_builder.compile(preset.state)
        loaded = giftmod.loads(giftmod.dumps(gift), game="rse")
        dist = gift_file.distribution(loaded.variants[gift_file.TARGET])
        assert dist.game == "emerald", preset.key
        assert gc.FLAG_MYSTERY_GIFT_DONE.to_bytes(2, "little") not in dist.ram_script, preset.key
        assert gc.VAR_MYSTERY_GIFT_1.to_bytes(2, "little") not in dist.ram_script, preset.key


def test_emerald_launcher_accepts_event_pokemon_and_refuses_firered_payloads():
    import frlg_mg_host

    parser = frlg_mg_host.build_parser()
    run = frlg_mg_host.build_run_config(
        parser, parser.parse_args(["--version", "emerald", "--gift", "event-pokemon"]))
    assert isinstance(run.payload, gifts.EmeraldPayload)
    assert run.payload.distribution.game == "emerald"
    assert run.payload.distribution.has_mevent

    for bad_args in (
        ["--version", "emerald"],
        ["--version", "emerald", "--gift", "celebi"],
        ["--version", "emerald", "--news", "pokeldn"],
        ["--version", "emerald", "--buffer-script", "trainer-id-probe"],
        ["--version", "emerald", "--gift", "event-pokemon", "--questionnaire", "1,2,3,4"],
        *(["--version", "emerald", "--gift", "event-pokemon", "--flag-id", str(i)] for i in gifts.TICKET_FLAG_IDS),
    ):
        with pytest.raises(SystemExit):
            frlg_mg_host.build_run_config(parser, parser.parse_args(bad_args))


def test_emerald_gift_files_export_works_for_compiled_and_event_presets():
    from pokeldn.app import gift_files
    from pokeldn.app.catalog import GAMES
    from pokeldn.app.settings import Settings

    tool = next(t for g in GAMES for t in g.tools if t.key == "rse-gift")
    compiled = gift_files.build(tool, {"--gift-file": {"mode": "preset", "preset": "old-sea-map"}}, {}, Settings())
    assert compiled.game == "rse" and set(compiled.variants) == {"emerald"}

    if _pkhex_available():
        event_gift = gift_files.build(
            tool, {"--gift-file": {"mode": "preset", "preset": "event-wishmkr-jirachi"}}, {}, Settings())
        assert event_gift.game == "rse"
        assert "mevent" in event_gift.variants["emerald"].data

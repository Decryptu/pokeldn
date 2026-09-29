"""The 328-byte PB8 a NetTradePokeData carries, on synthetic bodies."""
import struct

import pytest

from pokeldn.bdsp import netdata, pokemon, room


def a_body(ec=0xCDBEB642, species=41, nickname="Nosferapti", ot="Player", tid=44466, sid=4080):
    """A plain 328-byte body; the patterned filler catches block permutations and off-by-one offsets."""
    plain = bytearray(bytes(range(256)) * 2)[:pokemon.SIZE_STORED]
    struct.pack_into("<I", plain, 0x00, ec)
    struct.pack_into("<H", plain, 0x04, 0)
    struct.pack_into("<H", plain, pokemon.OFF_SPECIES, species)
    struct.pack_into("<H", plain, pokemon.OFF_TID, tid)
    struct.pack_into("<H", plain, pokemon.OFF_SID, sid)
    for offset, value in ((pokemon.OFF_NICKNAME, nickname), (pokemon.OFF_OT_NAME, ot)):
        plain[offset:offset + pokemon.NAME_LENGTH] = \
            value.encode("utf-16-le").ljust(pokemon.NAME_LENGTH, b"\x00")
    return bytes(plain)


def test_encrypt_is_the_inverse_of_decrypt_and_the_checksum_is_written_from_the_body():
    raw = pokemon.encrypt(a_body())
    assert len(raw) == pokemon.SIZE_STORED == 328
    plain = pokemon.decrypt(raw)
    assert plain[8:] == a_body()[8:]
    assert struct.unpack_from("<H", raw, 6)[0] == pokemon.checksum(plain)
    assert pokemon.encrypt(plain) == raw


def test_a_corrupted_body_is_refused_by_its_own_checksum():
    """The checksum sums the DECRYPTED body, so nothing wrong about a decryption can pass it."""
    raw = bytearray(pokemon.encrypt(a_body()))
    raw[100] ^= 0xFF
    with pytest.raises(ValueError, match="checksum"):
        pokemon.decrypt(bytes(raw))


def test_a_block_order_that_is_not_its_own_inverse_still_round_trips():
    """Every EC's block order round-trips; the checksum cannot catch a wrong permutation."""
    def sv_of(ec):
        return (ec >> 13) & 31

    self_inverse = [ec for ec in range(0, 1 << 20, 0x2000)
                    if pokemon.BLOCK_ORDER[sv_of(ec)] == pokemon.invert(pokemon.BLOCK_ORDER[sv_of(ec)])]
    assert self_inverse, "the old bug needs at least one of these to have hidden behind"

    for ec in range(0, 1 << 20, 0x2000):                      # every one of the 32 sv values
        raw = pokemon.encrypt(a_body(ec=ec))
        r = pokemon.read(raw)
        assert (r["nickname"], r["ot_name"]) == ("Nosferapti", "Player"), \
            f"sv={sv_of(ec)} put the names in the wrong blocks"
        assert r["species"] == 41

    # 24-31 repeat 0-7, as PKHeX writes it.
    assert len(pokemon.BLOCK_ORDER) == 32
    assert pokemon.BLOCK_ORDER[24:] == pokemon.BLOCK_ORDER[:8]


def test_the_block_order_follows_the_encryption_constant():
    """(EC >> 13) & 31 picks one of 24 orderings, so two ECs shuffle the same body differently."""
    body = bytearray(a_body())
    struct.pack_into("<I", body, 0, 0x00000000)
    first = pokemon.encrypt(bytes(body))
    struct.pack_into("<I", body, 0, 0x0000E000)          # (>> 13) & 31 lands on a different order
    second = pokemon.encrypt(bytes(body))
    assert pokemon.BLOCK_ORDER[(0 >> 13) & 31] != pokemon.BLOCK_ORDER[(0xE000 >> 13) & 31]
    assert first[8:] != second[8:]
    assert pokemon.decrypt(first)[8:] == pokemon.decrypt(second)[8:]


def test_building_from_a_template_changes_only_what_was_asked_for():
    """A Pokemon we send is a real one with named fields moved - every other byte stays a console's."""
    template = pokemon.encrypt(a_body())
    made = pokemon.build_from(template, species=25, nickname="PIKA", ot_name="PkCamp",
                              ivs=(31, 31, 31, 31, 31, 31))
    r = pokemon.read(made)
    assert (r["species"], r["nickname"], r["ot_name"]) == (25, "PIKA", "PkCamp")
    assert r["ivs"] == (31, 31, 31, 31, 31, 31)
    assert r["trainer_id"] == 44466 and r["secret_id"] == 4080
    before, after = pokemon.decrypt(template), pokemon.decrypt(made)
    untouched = [i for i in range(0xA0, 0xF8) if before[i] != after[i]]
    assert untouched == [], f"bytes changed that nothing asked for: {untouched}"
    with pytest.raises(ValueError, match="unknown field"):
        pokemon.build_from(template, sparkly=1)


def test_a_fresh_pb8_moves_only_its_pid_and_constant():
    """`--fresh-pid`: all but the two ids and the checksum decode back to the template; the shiny
    xor holds."""
    template = pokemon.encrypt(a_body())
    made = pokemon.fresh(template)
    before, after = pokemon.decrypt(template), pokemon.decrypt(made)
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    assert set(changed) <= {0, 1, 2, 3, 6, 7, 0x1C, 0x1D, 0x1E, 0x1F}
    assert after[:4] != before[:4] and after[0x1C:0x20] != before[0x1C:0x20]
    shiny = lambda r: r["trainer_id"] ^ r["secret_id"] ^ (r["pid"] >> 16) ^ (r["pid"] & 0xFFFF)
    assert shiny(pokemon.read(made)) == shiny(pokemon.read(template))


def test_a_nickname_sets_the_flag_that_makes_the_console_draw_it():
    """The name field shows only with IV32 bit 31 set."""
    template = pokemon.encrypt(a_body())
    plain = bytearray(a_body())
    struct.pack_into("<I", plain, pokemon.OFF_IVS, 0x14A65C08)      # flag clear, as the console's was
    template = pokemon.encrypt(bytes(plain))
    assert pokemon.read(template)["is_nicknamed"] is False

    made = pokemon.build_from(template, nickname="PKCAMP")
    r = pokemon.read(made)
    assert r["nickname"] == "PKCAMP" and r["is_nicknamed"] is True
    assert r["ivs"] == pokemon.read(template)["ivs"], "the IVs share the word with the flag"

    # An explicit value after the nickname still wins.
    quiet = pokemon.read(pokemon.build_from(template, nickname="PKCAMP", is_nicknamed=False))
    assert quiet["nickname"] == "PKCAMP" and quiet["is_nicknamed"] is False


def test_the_fields_pkhex_names_survive_a_round_trip():
    """The offsets beyond the twelve measured come from PKHeX's G8PKM, where all twelve agree."""
    template = pokemon.encrypt(a_body())
    edits = dict(moves=(71, 48, 0, 0), move_pp=(25, 20, 0, 0), relearn=(1, 2, 3, 4),
                 ball=4, met_level=4, met_location=357, egg_location=65535, language=3,
                 version=49, ot_friendship=50, met_date=(21, 11, 21), gender=1,
                 current_handler=0, is_egg=False)
    r = pokemon.read(pokemon.build_from(template, **edits))
    for key, value in edits.items():
        assert r[key] == value, f"{key} did not survive"
    # met_level and ot_gender share a byte and must not tread on each other
    both = pokemon.read(pokemon.build_from(template, met_level=100, ot_gender=1))
    assert (both["met_level"], both["ot_gender"]) == (100, 1)


def test_a_name_too_long_for_its_field_is_refused_rather_than_truncated():
    template = pokemon.encrypt(a_body())
    with pytest.raises(ValueError, match="too long"):
        pokemon.build_from(template, nickname="A" * 13)
    with pytest.raises(ValueError, match="too long"):
        room.build_trade_traner("A" * 13, 1, 2)


def test_the_trade_messages_wrap_the_payloads_the_console_wraps_them_in():
    raw = pokemon.encrypt(a_body())
    msg = room.build_trade_poke(raw)
    assert msg[:3].hex() == "130148"                     # id 0x13, length 0x148 = 328
    assert room.parse(msg)["name"] == "NetTradePokeData"
    assert msg[3:] == raw
    with pytest.raises(ValueError, match="328-byte"):
        room.build_trade_poke(raw[:-1])
    rec = room.build_trade_traner("Player", 44466, 4080)
    assert room.parse_trade_traner(rec[3:])["trainer_id"] == 44466


# The two trainer records seen on the wire; they differ at 0x18.
TRADE_TRANER_SP82 = bytes.fromhex(
    "50006c0061007900650072000000000018a4010014a401000000b2adf00f3103")
TRADE_TRANER_SP83 = bytes.fromhex(
    "50006c0061007900650072000000000018a4010014a401006e3db2adf00f3103")


def test_the_trainer_record_is_parsed_from_the_game_message_not_the_reliable_frame():
    """The parser takes the game message alone and refuses a wrong length."""
    message = room.build(room.TRADE_TRANER, TRADE_TRANER_SP83)
    assert room.parse(message)["data_id"] == room.TRADE_TRANER
    body = message[room.HEADER_SIZE:]
    assert len(body) == room.TRADE_TRANER_SIZE
    assert room.parse_trade_traner(body)["name"] == "Player"
    with pytest.raises(ValueError, match="expected 32"):
        room.parse_trade_traner(b"\x00" * 9 + body)


def test_the_bytes_behind_the_name_vary_between_sessions_and_no_field_is_read_out_of_them():
    """What follows the name's terminator is `AllocHGlobal` heap residue: carried, not read."""
    sp82 = room.parse_trade_traner(TRADE_TRANER_SP82)
    sp83 = room.parse_trade_traner(TRADE_TRANER_SP83)
    assert sp82["slack"] != sp83["slack"]
    assert sp82["name"] == sp83["name"] == "Player"
    assert sp82["trainer_id"] == sp83["trainer_id"] == 44466
    assert sp82["secret_id"] == sp83["secret_id"] == 4080
    assert sp82["casset_version"] == sp83["casset_version"] == 0x31
    assert sp82["lang_id"] == sp83["lang_id"] == 3


def test_the_trainer_record_we_build_is_the_console_s_own_bytes():
    """Byte-identical to the console's own: the layout is readable and reproducible."""
    assert room.build_trade_traner("Player", 44466, 4080)[3:] == TRADE_TRANER_SP82
    parsed = room.parse(room.build(room.TRADE_TRANER, TRADE_TRANER_SP83))
    assert parsed["traner"]["name"] == "Player"


def test_the_measured_layouts_are_no_longer_reported_opaque():
    """Eleven of the twelve OPAQUE ids have been on the wire and are decided; 0x29 never has."""
    for data_id in room.MEASURED:
        assert data_id in netdata.OPAQUE
        assert room.parse(room.build(data_id, b"\x00" * 32))["opaque"] is False
    assert set(netdata.OPAQUE) - set(room.MEASURED) == {0x29}
    assert room.parse(room.build(0x29, b"\x00" * 8))["opaque"] is True


def test_the_ball_capsule_and_the_record_read_off_the_wire():
    """A capsule with 19 stickers: every one at distance 100 from the origin; slot 19 empty.
    A record: thirty counters, the group and player names, the trainer id twice, version 0x31."""
    deco = room.parse(room.build(room.BALL_DECO, bytes.fromhex(
        "130000d7ff2f004e001c29002f004e001c0000d1ff58001c00000000640003d1ff000058000d2f00000058"
        "000d00002f0058000d000063000a0023a8ffd1ff0900235800d1ff090023d2ff53001f00252e0053001f00"
        "2500009dff0a0025b7ff2f0031002b49002f0031002b0000adff38002bb7ffd1ff3100354900d1ff310035"
        "000053003800370000000000000000")))["ball_deco"]
    assert deco["count"] == 19 and len(deco["seals"]) == 20
    for seal in deco["seals"][:19]:
        assert seal["seal_id"] and round((seal["x"] ** 2 + seal["y"] ** 2 + seal["z"] ** 2) ** 0.5) in (99, 100)
    assert deco["seals"][19] == {"x": 0, "y": 0, "z": 0, "seal_id": 0}
    body = bytearray(694)
    body[0x78:0x78 + 16] = "Ape Gang".encode("utf-16-le")
    body[0x98:0x98 + 12] = "Player".encode("utf-16-le")
    struct.pack_into("<I", body, 0xf8, 0x0ff0adb2)
    struct.pack_into("<I", body, 0x280, 0x0ff0adb2)
    body[0x2b0] = 0x31
    rec = room.parse(room.build(room.RECODE, bytes(body)))["recode"]
    assert rec["group_name"] == "Ape Gang" and rec["name"] == "Player"
    assert rec["user_id"] == rec["unique_id"] == 0x0ff0adb2 and rec["version"] == 0x31


def test_a_selected_team_member_reads_its_slot_and_its_pokemon():
    """Six of these came off a console, index 0..5 of num 6, each a PB8 with a good checksum."""
    body = bytearray(481)
    body[:328] = pokemon.encrypt(pokemon.build(species=484)) if hasattr(pokemon, "build") else bytes(328)
    struct.pack_into("<IIBBBBB", body, 0x1d4, 0, 0, 2, 6, 0, 0, 0)
    sel = room.parse(room.build(room.SELECT_POKEMON, bytes(body)))["select_pokemon"]
    assert sel["index"] == 2 and sel["num"] == 6 and len(sel["pb8"]) == 328 and len(sel["seals"]) == 20


def test_the_standby_list_reads_the_record_the_console_sent_back():
    """`22 0014 01 00 01 03` + 16 zero bytes: station 1, French, in slot 0, after it was added."""
    msg = room.parse(bytes.fromhex("2200140100010300000000000000000000000000000000"))
    assert msg["standby"][0] == {"is_add_player": 1, "host_index": 0, "my_index": 1, "lang_id": 3}
    assert msg["standby"][1]["is_add_player"] == 0 and len(msg["standby"]) == 5


def test_the_handler_block_is_readable_and_settable():
    """Traded back: handler name 0xA8, language 0xC3, CurrentHandler 0xC4, friendship 0xC8; 0xC6
    stays zero."""
    # IsUntraded is an empty handler name field.
    template = pokemon.encrypt(a_body())
    template = pokemon.build_from(template, ht_name="")
    assert pokemon.read(template)["is_untraded"] is True

    traded = pokemon.build_from(template, ht_name="Player", ht_language=3,
                                current_handler=1, ht_friendship=50)
    r = pokemon.read(traded)
    assert (r["ht_name"], r["ht_language"], r["current_handler"], r["ht_friendship"]) \
        == ("Player", 3, 1, 50)
    assert r["is_untraded"] is False
    assert r["ot_name"] == "Player", "the OT is not the handler and must not move"

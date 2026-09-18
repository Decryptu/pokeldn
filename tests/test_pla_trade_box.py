"""The trade box, against the message a console sent.

The reference is one 399-byte message a console put on the wire twice: once in a pair capture of two
emulated consoles that reached the trade screen, and once against this project's own host, in a
different session with different keys. The two are byte for byte the same. `docs/pla.md`, The trade
box.
"""

import struct

import pytest

from pokeldn.ldn import reliable5
from pokeldn.pla import game_channel, pokemon, trade_box

# The whole 0x7c message, header included, as the console sent it.
CONSOLE_SHOWING = bytes.fromhex(
    "07000186000200020000000000000000000200bc817801") + trade_box.REFERENCE_RECORD
# The same console, in the same place, after the player offered the Pokemon up.
CONSOLE_OFFERING = bytes.fromhex(
    "07000186000200020000000000000000000400bc817801") + trade_box.REFERENCE_RECORD
CONSOLE_MESSAGE = CONSOLE_OFFERING


def test_both_selectors_are_the_consoles_byte_for_byte():
    assert trade_box.build_message(selector=trade_box.SELECTOR_SHOWING) == CONSOLE_SHOWING
    assert trade_box.build_message(selector=trade_box.SELECTOR_OFFERING) == CONSOLE_OFFERING


def test_the_two_selectors_differ_in_one_byte():
    differences = [i for i in range(len(CONSOLE_SHOWING))
                   if CONSOLE_SHOWING[i] != CONSOLE_OFFERING[i]]
    assert differences == [9 + 8]   # the header, the key, then the selector


def test_the_message_is_application_data_at_sequence_two_with_no_bitmap():
    message = reliable5.parse(CONSOLE_MESSAGE)
    assert message["flags"] == (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
                                | reliable5.FLAG_MESSAGE_END)
    assert not message["flags"] & reliable5.FLAG_IS_INITIALIZED   # the opens carry it, this does not
    assert not message["flags"] & reliable5.FLAG_ZLIB             # the record is not compressed
    assert message["sequence_id"] == trade_box.SEQUENCE_ID == 2
    assert message["lowest_pending"] == 2
    assert message["destination_bits"] == 0
    assert message["header_size"] == 9


def test_the_payload_routes_by_the_channels_zero_key():
    key, _ = game_channel.split_message(reliable5.parse(CONSOLE_MESSAGE)["payload"])
    assert key == bytes(game_channel.KEY_SIZE)


def test_the_header_is_the_selector_the_counter_and_a_tagged_length():
    body = reliable5.parse(CONSOLE_MESSAGE)["payload"][game_channel.KEY_SIZE:]
    assert body[0] == trade_box.SELECTOR_OFFERING
    assert body[1] == 0
    assert body[2] == trade_box.BLOB_TAG
    assert body[3] == trade_box.HALFWORD_TAG
    assert struct.unpack_from("<H", body, 4)[0] == pokemon.SIZE_PARTY \
        == len(trade_box.REFERENCE_RECORD)


def test_the_payload_reads_back_as_what_was_built():
    read = trade_box.read_payload(reliable5.parse(CONSOLE_MESSAGE)["payload"])
    assert read == dict(selector=trade_box.SELECTOR_OFFERING, counter=0,
                        record=trade_box.REFERENCE_RECORD)


def test_a_channel_open_is_not_read_as_a_trade_box():
    assert trade_box.read_payload(game_channel.HOST_OPEN_PAYLOAD) is None
    assert trade_box.read_payload(game_channel.JOINER_OPEN_PAYLOAD) is None


def test_the_record_decrypts_to_the_pokemon_the_console_offered():
    fields = pokemon.read(pokemon.decrypt(trade_box.REFERENCE_RECORD))
    assert fields["species"] == 482
    assert fields["nickname"] == "Azelf"
    assert fields["ot_name"] == "FreeShkreli"
    assert fields["level"] == 70
    # 428750 is 1.25 * 70**3: the slow curve at the level the party tail carries.
    assert fields["experience"] == 428750


def test_the_trainer_id_is_the_player_id_the_data_exchange_carries():
    from pokeldn.pla import data_exchange

    plain = pokemon.decrypt(trade_box.REFERENCE_RECORD)
    ids = struct.pack("<HH", *struct.unpack_from("<HH", plain, pokemon.OFF_TID))
    assert ids == data_exchange.read_record(data_exchange.REFERENCE_RECORD)["player_id"]


def test_the_record_re_encrypts_to_the_bytes_the_console_sent():
    assert pokemon.encrypt(pokemon.decrypt(trade_box.REFERENCE_RECORD)) \
        == trade_box.REFERENCE_RECORD


def test_the_block_order_is_read_directly_and_the_names_say_so():
    """The checksum cannot tell a permutation from its inverse, so the layout has to. Read directly
    the nickname is the second block's first field and the trainer name the fourth's; read inverted
    both strings still decode, one block earlier, against a record that carries neither."""
    from pokeldn import gen8

    raw = trade_box.REFERENCE_RECORD
    ec = struct.unpack_from("<I", raw, 0)[0]
    out = bytearray(raw)
    out[8:pokemon.SIZE_STORED] = gen8.crypt(raw[8:pokemon.SIZE_STORED], ec)
    out[pokemon.SIZE_STORED:] = gen8.crypt(raw[pokemon.SIZE_STORED:], ec)
    order = gen8.BLOCK_ORDER[(ec >> 13) & 31]
    inverted = pokemon.permute(bytes(out), gen8.invert(order))
    assert order != gen8.invert(order), "this record's permutation is not its own inverse"
    assert pokemon.checksum(inverted) == pokemon.checksum(pokemon.decrypt(raw))
    assert pokemon.text(inverted, pokemon.OFF_NICKNAME) != "Azelf"


def test_a_record_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError):
        trade_box.build_payload(trade_box.REFERENCE_RECORD[:-1])


def test_a_selector_that_carries_no_record_is_refused():
    """1, 3, 5, 6 and 7 are selectors the handler knows and none of them deserialises a record."""
    for selector in (1, 3, 5, 6, 7):
        with pytest.raises(ValueError):
            trade_box.build_payload(trade_box.REFERENCE_RECORD, selector=selector)


def test_a_written_field_survives_the_round_trip_and_nothing_else_moves():
    plain = pokemon.decrypt(trade_box.REFERENCE_RECORD)
    renamed = pokemon.write(plain, nickname="POKELDN")
    assert pokemon.read(renamed)["nickname"] == "POKELDN"
    assert pokemon.read(pokemon.decrypt(pokemon.encrypt(renamed)))["ot_name"] == "FreeShkreli"
    for offset in range(len(plain)):
        in_name = pokemon.OFF_NICKNAME <= offset < pokemon.OFF_NICKNAME + pokemon.NAME_LENGTH
        if not in_name:
            assert renamed[offset] == plain[offset], hex(offset)


def test_a_record_of_our_own_is_not_the_one_the_console_holds():
    """The console offers a record it is itself holding, so a host that replays it offers the
    console its own Pokemon. A record of the host's own carries the player the data exchange names
    and an identity of its own, and everything else stays the template's."""
    ours = trade_box.build_our_record(bytes.fromhex("11223344"), "POKELDN")
    assert ours != trade_box.REFERENCE_RECORD
    fields = pokemon.read(pokemon.decrypt(ours))
    assert fields["ot_name"] == "POKELDN"
    assert (fields["trainer_id"], fields["secret_id"]) == struct.unpack("<HH",
                                                                       bytes.fromhex("11223344"))
    assert fields["pid"] == trade_box.OUR_PID
    assert struct.unpack_from("<I", pokemon.decrypt(ours), pokemon.OFF_ENCRYPTION_CONSTANT)[0] \
        == trade_box.OUR_ENCRYPTION_CONSTANT
    for key in ("species", "level", "experience", "ability", "nature", "nickname", "stats"):
        assert fields[key] == pokemon.read(pokemon.decrypt(trade_box.REFERENCE_RECORD))[key], key


def test_our_record_goes_on_the_wire_in_the_same_message_shape():
    ours = trade_box.build_our_record(bytes.fromhex("11223344"), "POKELDN")
    message = trade_box.build_message(ours)
    assert len(message) == len(CONSOLE_MESSAGE)
    assert trade_box.read_payload(reliable5.parse(message)["payload"])["record"] == ours


def test_the_player_the_data_exchange_names_is_the_records_trainer():
    from pokeldn.pla import data_exchange

    exchange = data_exchange.build_record(player_id=bytes.fromhex("11223344"), name="POKELDN")
    ours = trade_box.build_our_record(**data_exchange.read_record(exchange))
    plain = pokemon.decrypt(ours)
    assert plain[pokemon.OFF_TID:pokemon.OFF_TID + 4] == bytes.fromhex("11223344")
    assert pokemon.text(plain, pokemon.OFF_OT_NAME) == "POKELDN"


# What a console sends when the player confirms the trade, off the wire: selector 5 and a counter.
CONSOLE_CONFIRMING = bytes.fromhex("0700000a000300030000000000000000000500")


def test_the_confirmation_is_the_consoles_byte_for_byte():
    assert game_channel.build_message(bytes(game_channel.KEY_SIZE),
                                      bytes([trade_box.SELECTOR_CONFIRMING, 0]),
                                      sequence_id=3) == CONSOLE_CONFIRMING


def test_a_record_less_selector_reads_back_as_itself():
    payload = reliable5.parse(CONSOLE_CONFIRMING)["payload"]
    assert trade_box.read_payload(payload) is None
    assert trade_box.read_selector(payload) == (trade_box.SELECTOR_CONFIRMING, b"\x05\x00")


def test_the_mirrored_selectors_are_the_ones_that_carry_no_record():
    for selector in trade_box.MIRRORED_SELECTORS:
        assert selector not in trade_box.RECORD_SELECTORS
    # 1 is the channel open, which `game_channel` answers on its own before any of this.
    assert trade_box.SELECTOR_READY not in trade_box.MIRRORED_SELECTORS
    assert trade_box.SELECTOR_CONFIRMING in trade_box.MIRRORED_SELECTORS


def test_the_channel_open_is_a_selector_too():
    """The open the host sends is selector 1 under the same key, which is the same handler's case
    that sets [net+0x78]. The channel and the trade are one message stream."""
    assert trade_box.read_selector(game_channel.HOST_OPEN_PAYLOAD) \
        == (trade_box.SELECTOR_READY, b"\x01\x00")


# What a console announces on the phase key once the job exists: selector 1 and the phase.
CONSOLE_PHASE = bytes.fromhex("0700000a000500050001000000000000000103")


def test_the_phase_announcement_is_the_consoles_byte_for_byte():
    assert trade_box.build_phase(trade_box.PHASE_SELECTOR_MINE, 3, sequence_id=5) == CONSOLE_PHASE


def test_a_phase_message_reads_back_as_its_selector_and_phase():
    assert trade_box.read_phase(reliable5.parse(CONSOLE_PHASE)["payload"]) == (1, 3)


def test_the_host_answers_with_the_other_selector_and_the_same_phase():
    ours = trade_box.build_phase(trade_box.PHASE_SELECTOR_HOST, 3, sequence_id=6)
    assert trade_box.read_phase(reliable5.parse(ours)["payload"]) == (2, 3)
    # The two differ in the selector alone: same key, same phase, same shape.
    mine = reliable5.parse(CONSOLE_PHASE)["payload"]
    theirs = reliable5.parse(ours)["payload"]
    assert mine[:game_channel.KEY_SIZE] == theirs[:game_channel.KEY_SIZE] == trade_box.PHASE_KEY
    assert mine[game_channel.KEY_SIZE + 1:] == theirs[game_channel.KEY_SIZE + 1:]


def test_the_phase_key_is_not_the_trade_handlers_key():
    assert trade_box.PHASE_KEY != bytes(game_channel.KEY_SIZE)
    # So the trade handler's readers do not claim a phase message and the other way round.
    assert trade_box.read_selector(reliable5.parse(CONSOLE_PHASE)["payload"]) is None
    assert trade_box.read_payload(reliable5.parse(CONSOLE_PHASE)["payload"]) is None
    assert trade_box.read_phase(reliable5.parse(CONSOLE_CONFIRMING)["payload"]) is None


def test_a_phase_past_a_single_byte_is_refused():
    with pytest.raises(ValueError):
        trade_box.build_phase(trade_box.PHASE_SELECTOR_HOST, 0x80, sequence_id=6)


def test_the_level_and_experience_are_writable_and_nothing_else_moves():
    """The panel shows a level, so the level is the cheapest proof that the offered record is the
    host's to write rather than a capture to replay."""
    plain = pokemon.decrypt(trade_box.REFERENCE_RECORD)
    # 428750 is 1.25 * 70**3 in the captured record, so 1.25 * 50**3 is the same curve at 50.
    edited = pokemon.write(plain, level=50, experience=156250)
    fields = pokemon.read(edited)
    assert (fields["level"], fields["experience"]) == (50, 156250)
    assert fields["species"] == 482 and fields["nickname"] == "Azelf"
    moved = [i for i in range(len(plain)) if plain[i] != edited[i]]
    assert moved == [pokemon.OFF_EXPERIENCE, pokemon.OFF_EXPERIENCE + 1,
                     pokemon.OFF_EXPERIENCE + 2, pokemon.OFF_LEVEL]
    # It still round-trips, so the checksum is rewritten from the edited body.
    assert pokemon.read(pokemon.decrypt(pokemon.encrypt(edited)))["level"] == 50


def test_the_level_is_refused_on_a_stored_record():
    stored = pokemon.decrypt(trade_box.REFERENCE_RECORD)[:pokemon.SIZE_STORED]
    with pytest.raises(ValueError):
        pokemon.write(stored, level=50)

# The same record, shown back by the console out of its own box one trade later.
STORED_BACK = bytes.fromhex(
    "444c4b50000017c3066049eff5822da73022662916a1b12be6efe9606d1c4cd75bc78078f87f5036"
    "32d4b187a28b19d8109d590612b2b0f7e670fdf0bda3c3e00997e6288b374815345aaf94137b9d0b"
    "9b8a7bc589923aaba405eb22e612ee236745bae245ff00339ac4345ab70b9f75f6cc62528982c600"
    "561b2d83099cc2136e46f55e49c218450c5611d5e2cd88210ae86196d0adedaa007dfe1d87340858"
    "25b3789adefb117d5b9168494a94303b762425074e73b5609d1bab165755ffdab3209866f205429c"
    "530b39d479c5e6214443c4350ebbb0f027e3a42a0e2c84b9e16fe0f8db69db01d1395dfae85c1649"
    "21bbe65f0544044f5f87af4860f23d5d4ba0177bfdffa0fa1cf1d279ffc1c02dab873aff23f406a6"
    "0c562f20e13c5e889f9e489bbf304d9412d24f97610a259cfdfa9a5abb282b7bc706f8b1bd0cc867"
    "ab14ba1ba462c626cfddf7319e571d8a968abd138808025931891adc915799a27c39f862312cecea"
    "d66189ef28a06fe3d040a8298ba1b32b")


def test_the_block_starts_are_the_gen8_ones_widened():
    """A field at the head of a block sits at the Gen-8 offset plus eight bytes per block before it,
    because a block is 0x58 here and 0x50 there."""
    from pokeldn import gen8

    assert pokemon.BLOCK_SIZE - gen8.BLOCK_SIZE == 8
    assert pokemon.OFF_NICKNAME == gen8.OFF_NICKNAME + 8
    assert pokemon.OFF_HT_NAME == gen8.OFF_HT_NAME + 0x10
    assert pokemon.OFF_OT_NAME == gen8.OFF_OT_NAME + 0x18
    assert pokemon.OFF_LEVEL == gen8.OFF_STAT_LEVEL + 0x20
    assert pokemon.OFF_STATS == gen8.OFF_STATS + 0x20
    # And the three handler fields inside the third block keep their Gen-8 positions plus 0x10.
    assert pokemon.OFF_HT_LANGUAGE == gen8.OFF_HT_LANGUAGE + 0x10
    assert pokemon.OFF_CURRENT_HANDLER == gen8.OFF_CURRENT_HANDLER + 0x10
    assert pokemon.OFF_HT_FRIENDSHIP == gen8.OFF_HT_FRIENDSHIP + 0x10


def test_a_traded_record_comes_back_with_the_receivers_own_fields_filled_in():
    """The console showed the record it had been sent, out of its own box, one trade later. What
    differs is the checksum, the current HP, the six party stats, the handler's name and the three
    handler fields - and nothing else. `docs/pla.md`, What a trade rewrites."""
    sent = pokemon.write(
        pokemon.decrypt(trade_box.build_our_record(bytes.fromhex("11223344"), "POKELDN")),
        level=50, experience=156250)
    back = pokemon.decrypt(STORED_BACK)
    moved = {i for i in range(len(sent)) if sent[i] != back[i]}
    expected = {6, 7, pokemon.OFF_CURRENT_HP}
    expected |= {pokemon.OFF_HT_LANGUAGE, pokemon.OFF_CURRENT_HANDLER, pokemon.OFF_HT_FRIENDSHIP}
    expected |= {pokemon.OFF_HT_NAME + 2 * i for i in range(len("FreeShkreli"))}
    expected |= {pokemon.OFF_STATS + 2 * i for i in range(6)}
    assert moved == expected
    assert pokemon.text(back, pokemon.OFF_HT_NAME) == "FreeShkreli"
    assert back[pokemon.OFF_CURRENT_HANDLER] == 1
    assert pokemon.read(back)["level"] == 50
    # The stats it stored are the level-50 ones, not the level-70 tail it was sent.
    assert pokemon.read(back)["stats"] != pokemon.read(sent)["stats"]
    assert pokemon.read(back)["stats"] == (192, 204, 113, 186, 204, 135)


def test_the_moves_are_in_the_first_block_where_gen8_has_none():
    """Placed against 46 records off a console's own box: one species always carries one move set.
    Gen 8's move offsets read zero in every one of them. `docs/pla.md`, The trade box."""
    from pokeldn import gen8

    plain = pokemon.decrypt(trade_box.REFERENCE_RECORD)
    assert pokemon.OFF_MOVES == 0x54 and pokemon.OFF_MOVE_PP == 0x5C
    assert pokemon.OFF_MOVES < pokemon.OFF_NICKNAME     # the first block, not the second
    assert struct.unpack_from("<4H", plain, gen8.OFF_MOVES) == (0, 0, 0, 0)
    fields = pokemon.read(plain)
    assert fields["moves"] == (129, 458, 326, 832)
    assert fields["move_pp"] == (20, 10, 15, 10)
    assert all(0 < m < 950 for m in fields["moves"])


def test_the_field_map_reads_the_reference_record_whole():
    """Every field PKHeX's PA8 names, read off the one record a console sent, and every value in
    range for it. `docs/pla.md`, The trade box."""
    fields = pokemon.read(pokemon.decrypt(trade_box.REFERENCE_RECORD))
    assert fields["version"] == pokemon.VERSION_LEGENDS_ARCEUS == 47
    assert fields["language"] == 2                  # the save's language, English
    assert fields["sanity"] == 0
    assert fields["affixed_ribbon"] == -1           # none selected
    assert fields["current_handler"] == 0 and fields["ht_name"] == ""
    assert fields["gender"] == 2                    # Azelf is genderless
    assert fields["ability_number"] in (1, 2, 4)
    assert all(0 <= v <= 31 for v in fields["ivs"])
    assert all(0 <= v <= 10 for v in fields["gvs"])
    assert fields["met_level"] <= fields["level"]
    assert fields["met_date"] == (22, 1, 23)   # January 2022, on every captured record
    assert fields["ball"] == 28
    assert fields["scale"] == fields["height_scalar"]       # equal on all 47 captured records
    assert not fields["is_alpha"] and fields["alpha_move"] == 0


def test_the_individual_values_share_a_word_with_two_flag_bits():
    """`docs/pla.md`, The trade box."""
    plain = pokemon.decrypt(trade_box.REFERENCE_RECORD)
    assert struct.unpack_from("<I", plain, pokemon.OFF_IVS)[0] >> 30 == 0
    flagged = bytearray(plain)
    flagged[pokemon.OFF_IVS + 3] |= 0xC0
    written = pokemon.write(bytes(flagged), ivs=(31, 0, 31, 0, 31, 0))
    assert pokemon.read(written)["ivs"] == (31, 0, 31, 0, 31, 0)
    assert written[pokemon.OFF_IVS + 3] & 0xC0 == 0xC0, "the two flag bits above them are untouched"


def test_the_shiny_rule_is_the_gen6_one():
    """The record ph40 offered read shiny by this rule and the console drew the sparkle.
    `docs/pla.md`, Choosing what to offer."""
    ours = {"trainer_id": 8721, "secret_id": 17459, "pid": 711543883}
    assert pokemon.shiny_xor(ours) == 0
    assert (ours["secret_id"] << 16 | ours["trainer_id"]) % 1000000 == 201745, "the panel's ID No."
    pid = pokemon.shiny_pid(ours["trainer_id"], ours["secret_id"])
    assert pokemon.shiny_xor(dict(ours, pid=pid)) == 0
    assert not pokemon.read(pokemon.decrypt(trade_box.REFERENCE_RECORD))["is_shiny"]


def test_a_record_built_from_zero_bytes_carries_only_what_it_was_given():
    """`build` copies nothing from a console's record: a field the map does not cover stays zero.
    `docs/pla.md`, Choosing what to offer."""
    built = pokemon.build(species=94, level=68, experience=322272, moves=(247, 412, 188, 399),
                          trainer_id=0x2211, secret_id=0x4433, ot_name="POKELDN", nickname="Gengar")
    assert len(built) == pokemon.SIZE_PARTY
    fields = pokemon.read(built)
    assert fields["species"] == 94 and fields["level"] == 68
    assert fields["moves"] == (247, 412, 188, 399)
    assert fields["nickname"] == "Gengar" and fields["ot_name"] == "POKELDN"
    assert fields["version"] == 47 and fields["language"] == 2
    assert fields["ivs"] == (31,) * 6 and fields["gvs"] == (10,) * 6
    assert fields["evs"] == (0,) * 6 and fields["held_item"] == 0
    assert fields["stats"] == (0,) * 6, "the receiving game rebuilds the tail"
    # The round trip through the wire form gives the same bytes back.
    assert pokemon.is_plain(built), "it carries its own checksum"
    assert pokemon.decrypt(pokemon.encrypt(built)) == built

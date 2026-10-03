"""Sword and Shield's constants, read off a Shield 1.3.2 image."""

import pytest

from pokeldn.swsh import COMM_ID, GAME_KEY, PASSPHRASE, session_key, session_keys


def test_the_passphrase_is_not_the_arceus_one():
    # The wiki's Scarlet/Violet row is this string; its Legends Arceus row differs in one character.
    arceus = b"W3GoSMEn7RIIUQ89rzqBHGHGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
    assert PASSPHRASE != arceus
    assert sum(a != b for a, b in zip(PASSPHRASE, arceus)) == 1


def test_a_game_key_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError):
        session_key(1, game_key=b"short")


def test_the_advertisement_carries_the_seed_twelve_bytes_in():
    """A console's advertisement, and the key that authenticated all 484 of its packets."""
    class _Net:
        application_data = bytes.fromhex("0330112400000000051800008b718ac6")

    k = session_keys(_Net())
    assert k.session_param == 0xC68A718B
    assert k.network_id_le.hex() == "03301124"
    assert k.session_key.hex() == "e421f24ecd7166e3e13dc7ea8c379dd9"
    assert k.game_key == GAME_KEY          # a literal: the advertisement contributes the seed only


def test_a_short_advertisement_is_refused_rather_than_read_past():
    class _Net:
        application_data = b"\x01\x02\x03"

    with pytest.raises(ValueError):
        session_keys(_Net())


def test_the_local_communication_id_is_swords_not_shields():
    # Read off the advertisement; the binary read is a Shield image.
    assert COMM_ID == 0x0100ABF008968000


# A retail Sword searching for a Link Trade with code 12345678, read off the air with ldn_scan.py;
# its player's name replaced by POKELDN and the record's CRC recomputed.
SWORD_CODE_ADVERT = bytes.fromhex(
    "85a74f37afdae09a05180000a63e7a2a00000000000000000765700d000002c8536f0b06a95bcb953b778dba186a95e0"
    "4355a2d47b0410a2f2b11ac7e5ce57733612624ec1cbda50004f004b0045004c0044004e000000e04355a2d47b04100c"
    "11011c610000040400801540dc80830e5c745004020320020250074d20b64447d35cd84294025e472ccdb6bf4c20b644"
    "47d35cd84294025e472ccdb6bf4b20b64447d35cd84294025e472ccdb6bf010d00000000000000000000000000000000"
    "0000000000000000000000000000000000aa000100000000000000000000000000000000000000000000000000000000"
    "000000000000000000e001e4004e070000460000001c000400ac00b80004003e00f60f0b009c05f80200000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")


def test_the_host_rebuilds_a_retail_advert_under_a_link_code():
    import struct
    import swsh_host
    adv = SWORD_CODE_ADVERT
    rebuilt = swsh_host.build_advert(adv, network_id=adv[0:4],
                                     session_param=struct.unpack("<I", adv[12:16])[0], code="12345678")
    assert rebuilt == adv
    assert swsh_host.build_advert(adv, network_id=adv[0:4])[4:8] == bytes(4)


def test_the_host_builds_a_station_advert_without_a_saved_console_record():
    import swsh_host
    from pokeldn.swsh import beacon, trade_payload

    advert = swsh_host.build_advert(network_id=bytes.fromhex("0102ffff"),
                                   session_param=0x12345678, player_name="POKELDN")
    record = beacon.decode(advert)
    assert advert[:4] == bytes.fromhex("0102ffff")
    assert advert[4:8] == bytes(4)
    assert record["stored_crc"] == record["computed_crc"]
    assert record["network_id"] == beacon.NETWORK_ID
    assert advert[0x1C:0x1F] == bytes((0, 0, 1))
    profile = advert[0x1F:0x1F + trade_payload.PROFILE_LENGTH]
    assert any(profile[:16]) and any(profile[16:32])
    assert profile[trade_payload.TAIL_NAME_OFFSET:
                   trade_payload.TAIL_NAME_OFFSET + 14] == "POKELDN".encode("utf-16-le")
    assert profile[trade_payload.TAIL_ACTIVITY] == 13


def test_the_host_uses_the_live_snapshot_and_replaces_the_offered_slot(tmp_path, monkeypatch):
    import swsh_host
    from test_swsh_trade_payload import a_payload
    from pokeldn import gen8
    from pokeldn.swsh import pokemon, trade_payload

    peer = a_payload(count=2)
    chosen = peer[gen8.SIZE_PARTY:2 * gen8.SIZE_PARTY]
    fresh = gen8.fresh_identity
    monkeypatch.setattr(swsh_host.gen8, "fresh_identity",
                        lambda plain: fresh(plain, rand=lambda n: bytes(range(1, n + 1))))
    offer_path = tmp_path / "chosen.pk8"
    offer_path.write_bytes(chosen[:gen8.SIZE_STORED])
    args = swsh_host.build_parser().parse_args(["--offer-file", str(offer_path),
                                                "--trainer-name", "POKELDN", "--trainer-tid", "12345",
                                                "--trainer-sid", "54321", "--fresh-pid"])
    advert = swsh_host.build_advert(player_name="POKELDN")
    snapshot, offer = swsh_host.prepare_snapshot(peer, args, advert, args.offer_file[0])
    fields = trade_payload.read(snapshot)
    profile = trade_payload.read_tail(snapshot)
    assert fields["trainer_name"] == fields["card_name"] == "POKELDN"
    assert (fields["trainer_id"], fields["secret_id"]) == (12345, 54321)
    assert fields["party_count"] == 2
    assert fields["party"][1]["species"] == trade_payload.read(peer)["party"][1]["species"]
    assert offer == snapshot[:gen8.SIZE_PARTY]
    assert pokemon.read(offer)["species"] == pokemon.read(chosen)["species"]
    assert pokemon.read(offer)["ot_name"] == pokemon.read(chosen)["ot_name"]
    assert pokemon.read(offer)["pid"] != pokemon.read(chosen)["pid"]
    assert profile["device_id"] == advert[0x1F:0x2F]
    assert profile["account_uid"] == advert[0x2F:0x3F]

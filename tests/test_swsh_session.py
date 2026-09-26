"""Sword and Shield's constants, pinned to what the binary says rather than to a published table.

Every value here was read off a Shield 1.3.2 cartridge image offline; none of it has been on the
air. The point of pinning them is that the next person to touch this cannot quietly "fix" the
passphrase to the wiki's Legends Arceus row - the differences are the findings.
"""

import pytest

from pokeldn.swsh import COMM_ID, GAME_KEY, PASSPHRASE, session_key, session_keys


def test_the_passphrase_is_not_the_arceus_one():
    # The wiki has no Sword/Shield row at all. Its Scarlet/Violet row is this string exactly; its
    # Legends: Arceus row differs in ONE character, and reading one as the other's typo is the
    # mistake this test exists to prevent.
    arceus = b"W3GoSMEn7RIIUQ89rzqBHGHGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
    assert PASSPHRASE != arceus
    assert sum(a != b for a, b in zip(PASSPHRASE, arceus)) == 1


def test_a_game_key_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError):
        session_key(1, game_key=b"short")


def test_the_advertisement_carries_the_seed_twelve_bytes_in():
    """A run's own advertisement, and the key that authenticated all 484 of its packets."""
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
    # Read off the advertisement. The binary this project reads is a SHIELD image, so
    # nothing about this id can be assumed to hold for the other cartridge.
    assert COMM_ID == 0x0100ABF008968000


# A retail Sword searching for a Link Trade with code 12345678, read off the air with ldn_scan.py.
SWORD_CODE_ADVERT = bytes.fromhex(
    "85a74f37afdae09a05180000a63e7a2a00000000000000000f2d700d000002c8536f0b06a95bcb953b778dba186a95e0"
    "4355a2d47b0410a2f2b11ac7e5ce57733612624ec1cbda470075007200760061006e0000006a95e04355a2d47b04100c"
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

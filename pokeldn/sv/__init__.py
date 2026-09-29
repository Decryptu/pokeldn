"""Scarlet / Violet, native Switch titles on Pia header version 11 (`pokeldn.ldn.pia6`).

Belongs here: each cartridge's local communication id, the searching console's advertisement and the
game's messages. The passphrase and game key equal Sword's and Arceus's (docs/sv.md).
"""

from pokeldn.sv.session import (ADVERTISE_NAME, ADVERTISE_VERSION, APP_COMM_VERSION, APP_VERSION,
                                COMM_ID_SCARLET, COMM_ID_VIOLET, GAME_DATA_SIZE, GAME_KEY,
                                LDN_PROTOCOL, MAX_PARTICIPANTS, PASSPHRASE, PIA_HEADER_SIZE,
                                PIA_PORT, PIA_TAG_SIZE, PIA_VERSION, PLATFORM, SCENE_ID, SYS_COMM_VERSION,
                                SessionKeys, build_advertise_data, build_game_data, link_code,
                                packet_iv, parse_advertise_data, session_keys, user_password)

__all__ = ["ADVERTISE_NAME", "ADVERTISE_VERSION", "APP_COMM_VERSION", "APP_VERSION",
           "COMM_ID_SCARLET", "COMM_ID_VIOLET", "GAME_DATA_SIZE", "GAME_KEY", "LDN_PROTOCOL",
           "MAX_PARTICIPANTS", "PASSPHRASE", "PIA_HEADER_SIZE", "PIA_PORT", "PIA_TAG_SIZE",
           "PIA_VERSION", "PLATFORM", "SCENE_ID", "SYS_COMM_VERSION", "SessionKeys", "build_advertise_data",
           "build_game_data", "link_code", "packet_iv", "parse_advertise_data", "session_keys",
           "user_password"]

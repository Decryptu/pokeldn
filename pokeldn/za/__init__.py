"""Legends Z-A, a native Switch title on Pia header version 16 (`pokeldn.ldn.crypto`).

Belongs here: its LDN passphrase, Pia game key, local communication id, the searching console's
advertisement and the game's messages (docs/za.md).
"""

from pokeldn.za import pokemon, streams
from pokeldn.za.session import (ADVERTISE_NAME, ADVERTISE_VERSION, APP_COMM_VERSION, APP_VERSION,
                                COMM_ID, GAME_DATA_SIZE, GAME_KEY, LDN_PROTOCOL,
                                LINK_CODE_IV_BYTES, LINK_CODE_LEN, LINK_CODE_MASK,
                                MAX_PACKET_SIZE, MAX_PARTICIPANTS, PASSPHRASE, PIA_HEADER_SIZE,
                                PIA_PORT, PIA_TAG_SIZE, PIA_VERSION, SCENE_ID, SYS_COMM_VERSION,
                                SessionKeys, build_advertise_data, build_game_data, build_session_update_ack, link_code,
                                link_code_keystream, packet_iv, parse_advertise_data,
                                session_keys, session_update_sequence, user_password)

__all__ = ["pokemon", "streams", "ADVERTISE_NAME", "ADVERTISE_VERSION", "APP_COMM_VERSION", "APP_VERSION", "COMM_ID",
           "GAME_DATA_SIZE", "GAME_KEY", "LDN_PROTOCOL", "LINK_CODE_IV_BYTES", "LINK_CODE_LEN",
           "LINK_CODE_MASK", "MAX_PACKET_SIZE", "MAX_PARTICIPANTS", "PASSPHRASE",
           "PIA_HEADER_SIZE", "PIA_PORT", "PIA_TAG_SIZE", "PIA_VERSION", "SCENE_ID",
           "SYS_COMM_VERSION", "SessionKeys", "build_advertise_data", "build_game_data",
           "build_session_update_ack", "session_update_sequence", "link_code", "link_code_keystream", "packet_iv", "parse_advertise_data",
           "session_keys", "user_password"]

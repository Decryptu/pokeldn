"""Legends Arceus, a native Switch title on Pia header version 11 (`pokeldn.ldn.pia6`).

Belongs here: its LDN passphrase, Pia game key, local communication id and session keys (docs/pla.md).
"""

from pokeldn.pla.session import (ADVERTISE_NAME, ADVERTISE_VERSION, APP_COMM_VERSION, COMM_ID,
                                 GAME_KEY, LDN_PROTOCOL, LINK_CODE_IV_BYTES, LINK_CODE_LEN, LINK_CODE_MASK,
                                 MAX_PARTICIPANTS, PASSPHRASE, PIA_HEADER_SIZE, PIA_PORT,
                                 PIA_TAG_SIZE, PIA_VERSION, SCENE_ID, SYS_COMM_VERSION,
                                 SessionKeys, build_advertise_data, build_game_data, link_code,
                                 link_code_keystream, packet_iv, parse_advertise_data, session_keys, user_password)

__all__ = ["ADVERTISE_NAME", "ADVERTISE_VERSION", "APP_COMM_VERSION", "COMM_ID", "GAME_KEY",
           "LDN_PROTOCOL", "LINK_CODE_IV_BYTES", "LINK_CODE_LEN", "LINK_CODE_MASK", "MAX_PARTICIPANTS", "PASSPHRASE",
           "PIA_HEADER_SIZE", "PIA_PORT", "PIA_TAG_SIZE", "PIA_VERSION", "SCENE_ID",
           "SYS_COMM_VERSION", "SessionKeys", "build_advertise_data", "build_game_data",
           "link_code", "link_code_keystream", "packet_iv", "parse_advertise_data", "session_keys", "user_password"]

__all__ = ["ADVERTISE_NAME", "ADVERTISE_VERSION", "APP_COMM_VERSION", "COMM_ID", "GAME_KEY",
           "LDN_PROTOCOL", "LINK_CODE_IV_BYTES", "LINK_CODE_LEN", "LINK_CODE_MASK", "MAX_PARTICIPANTS", "PASSPHRASE", "PIA_HEADER_SIZE", "PIA_PORT",
           "PIA_TAG_SIZE", "PIA_VERSION", "SCENE_ID", "SYS_COMM_VERSION", "SessionKeys",
           "build_advertise_data", "build_game_data", "link_code", "link_code_keystream", "packet_iv",
           "parse_advertise_data", "session_keys", "user_password"]

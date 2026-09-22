"""Legends Z-A, a native Switch title on Pia header version 16.

What belongs here is what is true of Legends Z-A and of nothing else: its LDN passphrase, its Pia
game key, its local communication id, the advertisement a console waiting on the local search
screen puts up, and the game's own messages once they are read. The packet header of its band is
`pokeldn.ldn.crypto`, which the GBA application already uses, because a header band is true of
every title in it.

`docs/za.md` has the addresses and the unresolved list.
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

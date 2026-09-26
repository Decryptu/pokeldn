"""Scarlet / Violet, native Switch titles on Pia header version 11.

What belongs here is what is true of Scarlet and Violet and of nothing else: the local
communication id each cartridge advertises, the advertisement a searching console puts up, and
the game's own messages once they are read. The Pia band is `pokeldn.ldn.pia6`; the passphrase and
the game key are Sword's and Arceus's byte for byte, so they are restated here as the title's own
values rather than imported from another game's package.

`docs/sv.md` has the addresses and the unresolved list.
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

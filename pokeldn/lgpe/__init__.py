"""Let's Go Pikachu and Eevee, on Pia header version 3 (`pokeldn.ldn.pia4`), with a link code.

Belongs here: the header version, the link code and its advertisement, and the passphrase and game
key (Sword's literals, restated as this title's values). Addresses: docs/lgpe_session.md.
"""

from pokeldn.lgpe.session import (APPLICATION_VERSION, CODE_POKEMON, COMM_ID_PIKACHU, GAME_KEY,
                                  MAX_PARTICIPANTS, PASSPHRASE, PIA_HEADER_SIZE, PIA_PORT,
                                  PIA_TAG_SIZE, PIA_VERSION, SCENE_ID, SSID, build_advertise_data,
                                  code_picks, scene_id, search_channel, packet_iv, parse_advertise_data, session_key,
                                  session_keys)

__all__ = ["APPLICATION_VERSION", "CODE_POKEMON", "COMM_ID_PIKACHU", "GAME_KEY",
           "MAX_PARTICIPANTS", "PASSPHRASE", "PIA_HEADER_SIZE", "PIA_PORT", "PIA_TAG_SIZE",
           "PIA_VERSION", "SCENE_ID", "SSID", "build_advertise_data", "code_picks", "scene_id", "search_channel", "packet_iv",
           "parse_advertise_data", "session_key", "session_keys"]

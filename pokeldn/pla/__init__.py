"""Legends Arceus, a native Switch title on Pia header version 11.

What belongs here is what is true of Legends Arceus and of nothing else: its LDN passphrase, its
Pia game key, its local communication id and the way a scanned network becomes session keys. Pia
and LDN themselves are `pokeldn.ldn` and carry no game's constants; the version-11 packet header is
`pokeldn.ldn.pia6`, because a header band is true of every title in it. Like `bdsp` and `swsh`,
this sits directly on `ldn` with no link layer of its own.

`docs/pla.md` has the addresses and the unresolved list. The constants are read off the binary and
the advertisement is measured on a retail console; no Pia packet has been captured yet.
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

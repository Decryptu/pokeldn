"""Everything a Let's Go session is keyed on, read off Let's Go Pikachu 1.0.2's `main`
(docs/lgpe_session.md has the address behind each value)."""

import struct
from dataclasses import dataclass

from pokeldn.ldn.pia5 import gcm_iv, ldn_nonce_crc, ldn_session_key

# 64 bytes used raw [main.bin 0xf73a50] (docs/lgpe_session.md "The LDN passphrase").
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# Sixteen ASCII bytes at main.bin 0xefd659.
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# docs/lgpe_session.md "The Pia header": pia4's shape, version byte 3.
PIA_VERSION = 3
PIA_HEADER_SIZE = 0x20
PIA_TAG_SIZE = 16
PIA_PORT = 12345

# Let's Go Pikachu's title id; the comm id is read off the advertisement at runtime.
COMM_ID_PIKACHU = 0x010003F003A34000

# Three Pokemon picked in order from ten; sets the scene id, CRC stays 0 (docs/lgpe_session.md).
CODE_POKEMON = ("pikachu", "pikachu", "pikachu")
CODE_PICKER = ("pikachu", "eevee", "bulbasaur", "charmander", "squirtle",
               "pidgey", "caterpie", "rattata", "jigglypuff", "diglett")
CODE_PICKER_FR = ("pikachu", "evoli", "bulbizarre", "salameche", "carapuce",
                  "roucool", "chenipan", "rattata", "rondoudou", "taupiqueur")


def code_picks(code):
    """-> the three picker indices of a code given as names (English or French) or digits."""
    picks = []
    for name in code:
        name = str(name).strip().lower().replace("\u00e8", "e").replace("\u00e9", "e")
        if name.isdigit() and int(name) < len(CODE_PICKER):
            picks.append(int(name))
        elif name in CODE_PICKER:
            picks.append(CODE_PICKER.index(name))
        elif name in CODE_PICKER_FR:
            picks.append(CODE_PICKER_FR.index(name))
        else:
            raise ValueError(f"{name!r} is not in the link code picker: {', '.join(CODE_PICKER)}")
    if len(picks) != 3:
        raise ValueError(f"a link code is three Pokemon, got {len(picks)}")
    return picks


def scene_id(code=CODE_POKEMON):
    """The scene id a session advertises for a link code: the picks as decimal digits, then 1."""
    a, b, c = code_picks(code)
    return 1000 * a + 100 * b + 10 * c + 1


# main.bin 0xf73a44, indexed at 0x4db248 by scene % 3.
SEARCH_CHANNELS = (1, 6, 11)


def search_channel(code=CODE_POKEMON):
    """The channel a console searching on `code` hosts its own network on, the only one it joins."""
    return SEARCH_CHANNELS[scene_id(code) % 3]


def session_key(seed, game_key=GAME_KEY):
    """The LDN session key: AES-128-ECB(game key) over sixteen bytes of SEAD output, seeded from
    `seed`. main.bin 0x5cd560; the same derivation `pokeldn.ldn.pia5.ldn_session_key` implements."""
    return ldn_session_key(game_key, seed)


# The 5.9-5.18 application-data header: network id at 0, password CRC32 at 4, session param at 12.
NETWORK_ID_OFF = 0
PASSWORD_CRC_OFF = 4
SESSION_PARAM_OFF = 12
APP_HEADER_SIZE = 0x18
SYSTEM_COMM_VERSION_OFF = 8         # a u8 version and a u8 header size, then two zero bytes
SYSTEM_COMM_VERSION = 4

# A trade session's advertisement, measured on retail and in emulation: the NetworkInfo reports
# scene id 0, no application version, two seats, a fixed SSID.
SCENE_ID = scene_id()
APPLICATION_VERSION = 0
MAX_PARTICIPANTS = 2
SSID = bytes.fromhex("01000000000000000000000000000000")


def build_advertise_data(network_id, session_param, password_crc=0):
    """The 24 bytes a Let's Go station advertises."""
    return struct.pack("<IIBBHI", network_id & 0xFFFFFFFF, password_crc & 0xFFFFFFFF,
                       SYSTEM_COMM_VERSION, APP_HEADER_SIZE, 0,
                       session_param & 0xFFFFFFFF) + bytes(8)


def parse_advertise_data(data):
    """-> dict of the advertisement's fields, or None if it is shorter than the header."""
    if len(data) < APP_HEADER_SIZE:
        return None
    network_id, crc, version, header_size, _, param = struct.unpack_from("<IIBBHI", data, 0)
    return {"network_id": network_id, "password_crc": crc, "system_comm_version": version,
            "header_size": header_size, "session_param": param}


@dataclass
class SessionKeys:
    session_key: bytes
    game_key: bytes
    network_id_le: bytes
    session_param: int
    password_crc: int

    def __repr__(self):
        return (f"SessionKeys(session={self.session_key.hex()} game={self.game_key.hex()} "
                f"network_id_le={self.network_id_le.hex()} param={self.session_param:#010x} "
                f"password_crc={self.password_crc:#010x})")


def session_keys(net, game_key=GAME_KEY):
    """-> SessionKeys, from a scanned network. `net` needs `application_data`."""
    app = bytes(getattr(net, "application_data", b"") or b"")
    if len(app) < SESSION_PARAM_OFF + 4:
        raise ValueError(f"application data is {len(app)} bytes, need at least "
                         f"{SESSION_PARAM_OFF + 4}")
    param = struct.unpack_from("<I", app, SESSION_PARAM_OFF)[0]
    crc = struct.unpack_from("<I", app, PASSWORD_CRC_OFF)[0]
    return SessionKeys(ldn_session_key(game_key, param), bytes(game_key),
                       app[NETWORK_ID_OFF:NETWORK_ID_OFF + 4], param, crc)


def packet_iv(keys, source_mac, nonce8, source_id=0):
    """The twelve-byte GCM IV: three bytes of crc32(network id || sender MAC), one byte of source
    id, the packet's own nonce. `pia5`'s construction, measured on Sword's version 4."""
    return gcm_iv(ldn_nonce_crc(keys.network_id_le, source_mac), source_id, nonce8)

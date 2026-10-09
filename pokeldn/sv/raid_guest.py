"""Bundled retail Scarlet/Violet raid-guest identity and lobby fixture."""
from functools import lru_cache
import json
from pathlib import Path

from pokeldn.ldn import reliable5
from pokeldn.sv import pokemon, streams


FORMAT = "pokeldn.sv.raid-guest.v1"
FIXTURE = Path(__file__).with_name("data") / "raid_guest.json"
LOBBY_POKEMON_PREFIX = bytes.fromhex("80332e01")
LOBBY_POKEMON_HEADER_SIZE = 18
LOBBY_POKEMON_SIZE_OFFSET = 10


@lru_cache(maxsize=1)
def load_fixture():
    with FIXTURE.open(encoding="utf-8") as source:
        fixture = json.load(source)
    if fixture.get("format") != FORMAT:
        raise ValueError(f"unsupported raid guest fixture {fixture.get('format')!r}")
    identity = fixture.get("identity", ())
    if [row.get("seq") for row in identity] != list(range(1, 47)):
        raise ValueError("raid guest fixture identity must contain sequences 1 through 46")
    return fixture


def player_id():
    return bytes.fromhex(load_fixture()["player_id"])


def station_mac():
    return load_fixture()["station_mac"]


def identity_records():
    return [(row["seq"], bytes.fromhex(row["payload"]))
            for row in load_fixture()["identity"]]


def lobby_records():
    lobby = load_fixture().get("lobby", ())
    if [row.get("seq") for row in lobby] != [1, 2]:
        raise ValueError("raid guest fixture lobby must contain sequences 1 and 2")
    return [(row["seq"], row["flags"], bytes.fromhex(row["payload"])) for row in lobby]


def _plain(flags, payload):
    return streams.decompress(payload) if flags & reliable5.FLAG_ZLIB else bytes(payload)


def _pokemon_message(records):
    """Return (index, flags, plaintext) for the guest's 0x80332e Pokemon record."""
    found = []
    for index, (sequence, flags, payload) in enumerate(records):
        plain = _plain(flags, payload)
        if plain[:4] == LOBBY_POKEMON_PREFIX:
            found.append((index, sequence, flags, plain))
    if len(found) != 1:
        raise ValueError(f"raid guest lobby needs one Pokemon record, found {len(found)}")
    index, sequence, flags, plain = found[0]
    declared = int.from_bytes(
        plain[LOBBY_POKEMON_SIZE_OFFSET:LOBBY_POKEMON_SIZE_OFFSET + 4], "little")
    expected = LOBBY_POKEMON_HEADER_SIZE + pokemon.SIZE_PARTY
    if sequence != 2 or len(plain) != expected or declared != pokemon.SIZE_PARTY:
        raise ValueError(
            f"unrecognized raid guest Pokemon record: sequence {sequence}, "
            f"{len(plain)} bytes, declared size {declared}")
    return index, flags, plain


def lobby_pokemon(records=None):
    """Return the decrypted party PK9 announced by the guest's initial lobby record."""
    _, _, plain = _pokemon_message(records or lobby_records())
    return pokemon.load(plain[LOBBY_POKEMON_HEADER_SIZE:])


def with_lobby_pokemon(records, raw):
    """Return lobby records with only the encrypted party PK9 in 0x80332e replaced."""
    raw = bytes(raw)
    if len(raw) != pokemon.SIZE_PARTY:
        raise ValueError(
            f"a raid Pokemon must be a {pokemon.SIZE_PARTY}-byte party PK9, not {len(raw)} bytes")
    sealed = pokemon.encrypt(pokemon.load(raw))
    out = list(records)
    index, flags, plain = _pokemon_message(out)
    updated = plain[:LOBBY_POKEMON_HEADER_SIZE] + sealed
    payload = streams.compress(updated) if flags & reliable5.FLAG_ZLIB else updated
    sequence, _, _ = out[index]
    out[index] = (sequence, flags, payload)
    return out


def state_payload(state, records=None, *, previous_counter=None):
    """Build the next 0x80332d guest state from the initial lobby records."""
    records = records or lobby_records()
    if len(records) != 2:
        raise ValueError("raid guest state requires two initial lobby records")
    _, first_flags, first_payload = records[0]
    _, second_flags, second_payload = records[1]
    first = bytearray(_plain(first_flags, first_payload))
    second = _plain(second_flags, second_payload)
    if (len(first) != 42 or first[:4] != bytes.fromhex("80332d01")
            or first[34:38] != bytes.fromhex("18000000")
            or second[:4] != bytes.fromhex("80332e01")):
        raise ValueError("unrecognized raid guest lobby fixture")
    counter = (int.from_bytes(second[4:8], "little") if previous_counter is None
               else previous_counter)
    counter = (counter + 1) & 0xffffffff
    first[4:8] = counter.to_bytes(4, "little")
    first[34:38] = int(state).to_bytes(4, "little")
    return bytes(first)

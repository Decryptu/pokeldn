"""The trainer of the console's save, as a run learns it (docs/gui.md, Find your trainer): `show` prints
`[trainer] {json}` once per trainer, `read` is the app's side. A record's id pair is 16-bit TID and SID;
`shown` gives the ID and secret ID the game displays.
"""
import json

PREFIX = "[trainer] "
GBA = ("frlg", "rse")
# PKHeX's version numbers; a GBA LinkPlayer's version is 0x4000 plus the same number [pokeemerald link.c:331].
VERSIONS = {1: "Sapphire", 2: "Ruby", 3: "Emerald", 4: "FireRed", 5: "LeafGreen",
            42: "Let's Go Pikachu", 43: "Let's Go Eevee", 44: "Sword", 45: "Shield", 47: "Legends Arceus",
            48: "Brilliant Diamond", 49: "Shining Pearl", 50: "Scarlet", 51: "Violet", 52: "Legends Z-A"}
GAMES = {"frlg": "FireRed or LeafGreen", "rse": "Ruby, Sapphire or Emerald", "lgpe": "Let's Go",
         "swsh": "Sword or Shield", "pla": "Legends Arceus", "bdsp": "Brilliant Diamond or Shining Pearl",
         "sv": "Scarlet or Violet", "za": "Legends Z-A"}
GAME_VERSIONS = {"lgpe": (42, 43), "swsh": (44, 45), "pla": (47,), "bdsp": (48, 49), "sv": (50, 51), "za": (52,)}

_shown: set = set()


def shown(game: str, tid: int, sid: int) -> tuple[int, int]:
    """(ID, secret ID) as `game` displays the 16-bit pair: the halves on a GBA game, the 32-bit id's last six
    decimal digits and the rest on a Switch game."""
    if game in GBA:
        return tid, sid
    return divmod(sid << 16 | tid, 1_000_000)[::-1]


def show(game: str, fields: dict, source: str) -> None:
    """The console's save is `fields`' trainer (ot, tid, sid, and gender, language, version when known);
    `source` is "session" (the console's own link data) or "pokemon" (a Pokemon its save caught)."""
    if not fields or not fields.get("ot"):
        return
    message = {"game": game, "source": source, "ot": str(fields["ot"]), "tid": int(fields["tid"]),
               "sid": int(fields["sid"])}
    for key in ("gender", "language", "version"):
        if fields.get(key) is not None:
            message[key] = int(fields[key])
    key = json.dumps(message, sort_keys=True)
    if key in _shown:
        return
    _shown.add(key)
    print(PREFIX + json.dumps(message, ensure_ascii=False), flush=True)


def from_link_player(game: str, lp) -> None:
    """A GBA console's LinkPlayer (pokeldn.frlg.link.linkplayer) names its save, secret ID included."""
    show(game, {"ot": lp.name, "tid": lp.trainer_id & 0xFFFF, "sid": lp.trainer_id >> 16 & 0xFFFF,
                "gender": lp.gender if lp.gender in (0, 1) else None, "language": lp.language,
                "version": lp.version & 0xFF if lp.version >> 8 == 0x40 else None}, "session")


def own(game: str, f: dict) -> dict | None:
    """The trainer of a Pokemon a Switch console traded, as `pokeldn.pokemon.Service.owner` reads it, when its
    save caught it: still with its original trainer (handler 0), from one of the game's versions, hatched."""
    if game not in GAME_VERSIONS or f.get("egg") or f.get("handler") != 0 or not f.get("ot"):
        return None
    if f.get("version") not in GAME_VERSIONS[game]:
        return None
    return {k: f[k] for k in ("ot", "tid", "sid", "gender", "language", "version")}


def title(message: dict) -> str:
    """The game a message's trainer plays: its version, else the game."""
    return VERSIONS.get(message.get("version")) or GAMES.get(message["game"], message["game"])


def read(line: str) -> dict | None:
    """The message of a `[trainer]` line, or None."""
    if not line.startswith(PREFIX):
        return None
    try:
        message = json.loads(line[len(PREFIX):])
        int(message["tid"]), int(message["sid"]), str(message["ot"]), str(message["game"])
    except (ValueError, KeyError, TypeError):
        return None
    return message

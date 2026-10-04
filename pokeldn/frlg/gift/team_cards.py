"""The GB-Link Team Wonder Cards, prebuilt for the four cartridges by scripts/gen_team_cards.py
[docs/frlg_gift.md, GB-Link Team cards]."""

import functools
import json
import pathlib
from dataclasses import dataclass

from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
from pokeldn.frlg.rom import builds
from pokeldn.frlg.text import charmap

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "team_cards.json"
PREFIX = "custom-"


@dataclass(frozen=True)
class TeamCard:
    slug: str                       # the card's id without "custom-", e.g. "nature-mint"
    card: bytes
    scripts: dict                   # game code -> RAM script

    @property
    def title(self):
        return charmap.decode(self.card[10:50]).strip()

    @property
    def subtitle(self):
        return charmap.decode(self.card[50:90]).strip()

    @property
    def default_flag_id(self):
        # Their ids run past 1019, where sReceivedGiftFlags ends [wonder_card.flag_for_flag_id].
        flag_id = int.from_bytes(self.card[:2], "little")
        return flag_id if flag_id < 1020 else 1000 + int.from_bytes(self.card[4:8], "little") % 20

    def distribution(self, flag_id=None, build=None):
        flag_id = self.default_flag_id if flag_id is None else flag_id
        card = bytearray(self.card)
        card[:2] = flag_id.to_bytes(2, "little")
        card[4:8] = (flag_id % 100).to_bytes(4, "little")      # as every composed card [_build_card]
        return MysteryGiftDistribution(bytes(card), self.scripts[builds.resolve(build).game_code])


@functools.cache
def cards():
    """-> {slug: TeamCard}, in the generator's order."""
    raw = json.loads(DATA.read_text())
    return {key.removeprefix(PREFIX): TeamCard(key.removeprefix(PREFIX), bytes.fromhex(entry["card"]),
                                               {code: bytes.fromhex(s) for code, s in entry["scripts"].items()})
            for key, entry in raw.items()}

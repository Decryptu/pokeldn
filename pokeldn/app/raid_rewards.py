"""How many reward rows a hosted raid's record holds, per game; the rewards editor's bundles are in
gui/views/rewards.py."""
from pokeldn.sv.raid import REWARD_ROWS as SV_ROWS
from pokeldn.swsh.raid import REWARD_SLOTS as SWSH_ROWS

ROWS = {"sv": SV_ROWS, "swsh": SWSH_ROWS}


def rows(game: str) -> int:
    return ROWS.get(game, SV_ROWS)

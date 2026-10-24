"""How many reward rows a hosted raid's record holds, per game, and the rewards a hosted Sword/Shield
den can give; the rewards editor's bundles are in gui/views/rewards.py."""
from pathlib import Path

from pokeldn.sv.raid import REWARD_ROWS as SV_ROWS
from pokeldn.swsh.raid import REWARD_SLOTS as SWSH_ROWS

ROWS = {"sv": SV_ROWS, "swsh": SWSH_ROWS}


def rows(game: str) -> int:
    return ROWS.get(game, SV_ROWS)


def swsh_den(boss_file: str = "", gigantamax: bool = False, event=None, event_boss: str = ""):
    """-> {item: count or None} a guest accepts from the den a hosted Sword/Shield raid shows, as
    `bin/swsh_host.py` builds it (docs/swsh_raid.md, The boss record); a count of None is any count.
    `event` and `event_boss` ("version:stars:number:area") name an event boss in place of `boss_file`.
    None when no boss is chosen or no base den holds it: a guest then refuses the raid at its boss."""
    from pokeldn import gen8
    from pokeldn.swsh import pokemon, raid, raid_event
    try:
        if event is not None:
            version, stars, number, area = event_boss.split(":", 3)
            rank = int(stars) - 1
            versions = {name.lower(): n for n, name in raid_event.VERSIONS.items()}
            boss = event.choices(versions[version], rank, area)[int(number) - 1]
            boss_pk8 = raid_event.boss_pk8(boss)
        elif boss_file:
            rank = None
            plain = bytearray(gen8.load(Path(boss_file).expanduser().read_bytes()))
            if gigantamax:
                plain[raid.PK8_GIGANTAMAX] |= 0x10
            boss_pk8 = raid.boss_record(pokemon.encrypt(bytes(plain)))
        else:
            return None
        row, rank = raid.boss_den(boss_pk8, rank)
    except (OSError, ValueError, KeyError, IndexError):
        return None
    return None if row is None else raid.reward_choices(row, rank)

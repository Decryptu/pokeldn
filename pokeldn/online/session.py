"""The online partner as a host launcher takes it: its flags, and a partner that refuses a record
PKHeX does not pass (docs/online.md, In a launcher)."""
from pokeldn import __version__
from pokeldn.online.link import Partner


def add_arguments(ap):
    ap.add_argument("--online", action="store_true",
                    help="trade with a player far away: their console's offer is offered here, and "
                         "each side confirms only once both consoles have (docs/online.md)")
    ap.add_argument("--online-code", default=None, metavar="CODE",
                    help="the room both players enter; default the link code, and no code meets "
                         "anyone else trading online without one")


def checker(game):
    """-> validate(record) -> (the reason it is refused or None, what it is). A record PKHeX cannot
    read is refused: a bad checksum, a species absent from the game, a move or item id past the
    game's tables or one it never released. One its legality check flags otherwise reaches the
    player with the flag
    (docs/online.md, What crosses)."""
    def validate(record):
        from pokeldn import pokemon
        try:
            reply = pokemon.SERVICE.check_bytes(game, record)
        except pokemon.BuilderError as exc:
            return f"PKHeX could not read it ({exc})", ""
        shiny = " shiny" if reply.get("shiny") else ""
        what = f"{pokemon.summary(reply)} [species {int(reply.get('species_id') or 0)}{shiny}]"
        report = [line.strip() for line in str(reply.get("report", "")).splitlines() if line.strip()]
        # An item or move the game never released may lie past its own tables (Sword stops at
        # item 1607): never hand one to a console.
        unreleased = [line for line in report if "unreleased" in line.lower()]
        if unreleased:
            return f"PKHeX finds something the game never released ({unreleased[0]})", ""
        if not reply.get("legal"):
            what += f" (PKHeX flags it: {report[0] if report else 'not legal'})"
        return None, what
    return validate


def partner(game, args, code="", name="", log=print):
    """-> a started Partner when the launcher runs with --online, else None."""
    if not getattr(args, "online", False):
        return None
    room = args.online_code if args.online_code is not None else code
    found = Partner(game, room or "", name=name, app=__version__, log=log, validate=checker(game))
    found.start()
    return found

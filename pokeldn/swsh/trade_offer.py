"""Original trainer of a Sword/Shield Link Trade offer."""
from pathlib import Path

from pokeldn import console_trainer, gen8, pokemon as pokemon_service, trade_owner
from pokeldn.swsh import trade_payload


def console_offers(snapshot, paths, *, fresh=False):
    """Revalidate every queued record against the trainer of this live session."""
    try:
        trainer = trade_payload.trainer(snapshot)
    except ValueError as error:
        raise pokemon_service.BuilderError(f"Invalid Sword/Shield trade snapshot: {error}") from error
    if (not trainer["ot"] or trainer["version"] not in console_trainer.GAME_VERSIONS["swsh"]
            or trainer["gender"] not in (0, 1)):
        raise pokemon_service.BuilderError("The Sword/Shield snapshot did not contain a valid console trainer.")
    console_trainer.show("swsh", trainer, "session")
    offers = trade_owner.rewrite("swsh", [Path(path).read_bytes() for path in paths], trainer,
                                 lambda data: gen8.encrypt(gen8.load(data)), fresh=fresh)
    return dict(zip(paths, offers))

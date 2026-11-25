"""Original trainer selection for a local trade."""
from pathlib import Path
from threading import Thread

from pokeldn import console_trainer, pokemon, trade_back


MODE = "--offer-owner"
TRAINER = "--offer-trainer"


class TrainerError(pokemon.BuilderError):
    """A trade refused before sending an offer with the wrong trainer."""


def failed(error):
    """A rejected offer can be wrapped in the link nursery's exception group."""
    return isinstance(error, TrainerError) or any(failed(child) for child in getattr(error, "exceptions", ()))


def add_arguments(parser):
    parser.add_argument(MODE, choices=("original", "settings", "console"), default="original",
                        help="keep the Pokemon's OT, use --offer-trainer, or use the receiving save's OT")
    parser.add_argument(TRAINER, nargs=4, metavar=("NAME", "TID", "SID", "GENDER"),
                        help="OT name, raw 16-bit trainer IDs and gender for --offer-owner settings")


def mode(args):
    return getattr(args, "offer_owner", "original")


def check(parser, args, offers, *, local=True):
    """Validate the choice before touching the radio."""
    if mode(args) == "original":
        return
    if not local or not offers:
        parser.error(f"{MODE} {mode(args)} needs a local trade with a Pokemon file")
    if mode(args) == "settings":
        try:
            name, tid, sid, gender = args.offer_trainer
            if not name or not all(0 <= int(value) <= 65535 for value in (tid, sid)) or gender not in ("0", "1"):
                raise ValueError
        except (TypeError, ValueError):
            parser.error(f"{MODE} settings needs {TRAINER} NAME TID SID GENDER")


def prepare_file(game, path, args, *, fields=None, **check):
    """Apply a configured OT during the usual preflight. A live OT is applied by the session."""
    if mode(args) == "settings":
        name, tid, sid, gender = args.offer_trainer
        fields = {**(fields or {}), "trainer": {"ot": name, "tid": int(tid), "sid": int(sid),
                                                "gender": int(gender)}}
    if fields is not None:
        check["fields"] = fields
    return pokemon.prepare_file(game, path, **check)


def read_trainer(game, parse, *data):
    """Read the peer's session data, reporting it to the app when it names a trainer."""
    try:
        trainer = parse(*data)
    except ValueError:
        return None
    if trainer and trainer.get("ot"):
        console_trainer.show(game, trainer, "session")
        return trainer
    return None


def rewrite(game, records, trainer, load, *, fresh=False, shown=None):
    """Check each offer for one receiving save, then encode it in the trade's wire form."""
    if not trainer or not trainer.get("ot"):
        raise TrainerError("The console did not send its original trainer. No Pokemon was offered.")
    owner = {key: trainer[key] for key in ("ot", "tid", "sid")}
    if shown is not None and trainer.get("gender") not in (0, 1):
        try:
            peer = pokemon.SERVICE.owner(game, pokemon.entity_bytes(game, shown))
        except (pokemon.BuilderError, ValueError):
            peer = {}
        if peer.get("handler") == 0 and all(peer.get(k) == value for k, value in owner.items()):
            trainer = {**trainer, "gender": peer.get("gender")}
        elif peer.get("handler") == 1 and peer.get("ht_name") == owner["ot"]:
            trainer = {**trainer, "gender": peer.get("ht_gender")}
    out = []
    for i, raw in enumerate(records, 1):
        try:
            data = pokemon.entity_bytes(game, raw)
            gender = trainer.get("gender")
            if gender not in (0, 1):
                gender = pokemon.SERVICE.owner(game, data)["gender"]
            checked = pokemon.prepare(game, data, fresh=fresh, fields={"trainer": {**owner, "gender": gender}})
            out.append(load(pokemon.offer_bytes(game, checked)))
        except (pokemon.BuilderError, ValueError) as error:
            raise TrainerError(f"Offer {i} cannot use the console's OT ({owner['ot']}): {error}") from error
    return out


def rewrite_files(game, paths, trainer):
    """Let a trade that takes filenames use the same checked records without touching its input files."""
    from pokeldn.app.paths import SESSION
    from uuid import uuid4

    changed = rewrite(game, [Path(path).read_bytes() for path in paths], trainer, bytes)
    folder = SESSION / "offers"
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    for path, body in zip(paths, changed):
        target = folder / f"{game}-{uuid4().hex}{Path(path).suffix}"
        target.write_bytes(body)
        result.append(str(target))
    return result

class ReceiverTrade(trade_back.TradeBack):
    """A host's local partner waits for checked offers for this seat's trainer."""

    def __init__(self, game, records, load, *, return_each=False):
        super().__init__(game, records, return_each=return_each)
        self.records = tuple(records)
        self.load = load
        self.trainer = None
        self.pending = False
        self.generation = 0
        self.theirs_now = trade_back.Offer()

    def reset(self):
        with self.lock:
            self.generation += 1
            self.trainer = None
            self.pending = False
            self.last = None
            self.rounds = trade_back.Rounds(self.records, log=self.log, return_each=self.rounds.return_each)
            self.theirs_now = trade_back.Offer()

    def hear(self, trainer):
        if not trainer.get("ot"):
            return
        with self.lock:
            if self.trainer is None:
                self.trainer = trainer
                self._start()

    def offer(self, body):
        with self.lock:
            self.last = bytes(body)
            self._start()

    def _start(self):
        if self.pending or self.trainer is None or self.theirs_now.offer is not None:
            return
        if self.trainer.get("gender") not in (0, 1) and self.last is None:
            return
        self.pending = True
        Thread(target=self._prepare, args=(self.generation, self.trainer, self.last), daemon=True).start()

    def _prepare(self, generation, trainer, shown):
        try:
            offers = rewrite(self.game, self.records, trainer, self.load, shown=shown)
        except pokemon.BuilderError as error:
            with self.lock:
                if generation != self.generation:
                    return
                self.log(f"[trainer] {error}")
            from pokeldn import popup
            try:
                popup.acknowledge("Could not use the console's trainer", str(error), tone="warning")
            except RuntimeError:
                pass
            return
        with self.lock:
            if generation == self.generation:
                self.rounds.offers = offers
                self.theirs_now = self._next()

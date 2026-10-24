"""A Mystery Gift Pokemon made for the player who receives it (docs/gift_simulated.md, Made for the receiving
player). A card that gives the receiver's own trainer is made again during the trade, under the trainer of
the console's save: the Pokemon the console offers names it, when that save caught it; otherwise the trainer
the console's own session data names (`hear`). When neither does, or the card cannot be made for that save,
the copy the app made under the trainer from Settings goes instead.

`ReceiverGift` takes an online partner's place (pokeldn.online.link.Partner) in a trade host, which then waits
for the console's offer before putting ours up and confirms once the console has. It logs `[gift]` lines, and
asks the app for a pop-up (`pop_up`) when the gift goes with the trainer from Settings.
"""

import base64
import threading

from pokeldn import console_trainer

# PKHeX's numbers and names for the versions a save of each game can be.
VERSIONS = {"lgpe": {42: "GP", 43: "GE"}, "bdsp": {48: "BD", 49: "SP"}, "pla": {47: "PLA"},
            "sv": {50: "SL", 51: "VL"}, "za": {52: "ZA"}}
NAMES = {"GP": "Let's Go Pikachu", "GE": "Let's Go Eevee", "BD": "Brilliant Diamond", "SP": "Shining Pearl",
         "PLA": "Legends Arceus", "SL": "Scarlet", "VL": "Violet", "ZA": "Legends Z-A"}
# A trainer no card names: a card that fixes its trainer gives a copy made for it the card's own.
PROBE = {"ot": "Receiver", "tid": 0x5EED, "sid": 0x0C0D, "language": 2, "gender": 0}
READY = ("[gift] waiting for the console's offer: a Pokemon caught in this save names the trainer, and the "
         "console's session data names it for any other; failing both, the gift goes with your trainer from "
         "Settings")
LANGUAGES = {1, 2, 3, 4, 5, 7, 8, 9, 10}    # PKHeX's LanguageID a save can be
FALLBACK_TITLE = "The gift carries the trainer from Settings"


def sv_owner(body):
    """`Service.owner` for a Scarlet/Violet 348-byte trade body, read here: that host serves several consoles in
    one loop, which never waits on the service."""
    from pokeldn import gen9
    f = gen9.read(gen9.from_wire(body))
    return {"species": f["species"], "shiny": f["is_shiny"], "egg": bool(f["is_egg"]), "ot": f["ot_name"],
            "tid": f["trainer_id"], "sid": f["secret_id"], "gender": f["ot_gender"], "language": f["language"],
            "handler": f["current_handler"], "ht_name": f["ht_name"], "ht_gender": f["ht_gender"],
            "ht_language": f["ht_language"], "version": f["version"]}


def owner_reader(game):
    """-> owner(body): whose the Pokemon a console offers is (`pokeldn.pokemon.Service.owner`); ValueError for
    a body that is not a record."""
    if game == "sv":
        return sv_owner
    from pokeldn import pokemon

    def owner(body):
        try:
            return pokemon.SERVICE.owner(game, body)
        except pokemon.BuilderError as exc:
            raise ValueError(str(exc)) from exc
    return owner


def own_trainer(game, f):
    """-> (trainer, version) of the save offering a Pokemon whose owner fields are `f`, as `gift_event` takes
    them, when that save caught it: still with its original trainer (handler 0), from one of the game's
    versions, and hatched. None otherwise."""
    if unknown(game, f):
        return None
    trainer = {"ot": f["ot"], "tid": f["tid"], "sid": f["sid"], "language": f["language"], "gender": f["gender"]}
    return trainer, VERSIONS[game][f["version"]]


def unknown(game, f):
    """-> why the Pokemon whose owner fields are `f` names no trainer of the offering save, as "it ...", ""
    when it does."""
    if f["egg"]:
        return "it is an egg"
    if f["handler"] != 0:
        return f"it came from another trainer, {f['ot']}"
    if f["version"] not in VERSIONS[game]:
        return "it came from another game"
    return "" if f["ot"] else "it names no trainer"


def from_session(game, heard, f, given):
    """-> ((trainer, version), [what came from where]) for the save the console's session data `heard` names
    (`hear`), None when it names none. The fields it lacks come from the offered Pokemon, `f`, when it is this
    save's: from its original trainer while it is still with that trainer, whose name and id pair are the
    session's (an egg the save bred), and from its handler once it came from another trainer, handled last by
    the trainer the session names (docs/bdsp_trade.md, What the console does to a received Pokemon). Failing
    both, they come from the trainer from Settings: `given`, the owner fields of the round's record made under
    it."""
    if not heard or not heard.get("ot"):
        return None
    given = given or {}
    own_ot = bool(f) and f.get("handler") == 0 and all(f.get(k) == heard[k] for k in ("ot", "tid", "sid"))
    handled = bool(f) and f.get("handler") == 1 and f.get("ht_name") == heard["ot"]
    trainer, notes = {"ot": heard["ot"], "tid": heard["tid"], "sid": heard["sid"]}, []
    languages = LANGUAGES | {11} if game == "za" else LANGUAGES     # Z-A adds Latin American Spanish
    for field, valid in (("gender", {0, 1}), ("language", languages)):
        if heard.get(field) in valid:
            trainer[field] = heard[field]
        elif own_ot and f.get(field) in valid:
            trainer[field] = f[field]
            notes.append(f"{field} from the Pokemon's original trainer")
        elif handled and f.get(f"ht_{field}") in valid:
            trainer[field] = f[f"ht_{field}"]
            notes.append(f"{field} from the Pokemon's handler")
        elif given.get(field) in valid:
            trainer[field] = given[field]
            notes.append(f"{field} from Settings")
        else:
            return None
    versions = VERSIONS[game]
    if heard.get("version") in versions:
        version = versions[heard["version"]]
    elif len(versions) == 1:
        version = next(iter(versions.values()))
    elif given.get("version") in versions:
        version = versions[given["version"]]
        notes.append("version from Settings")
    else:
        return None
    return (trainer, version), notes


def species_tag(f):
    """An offered Pokemon's species, tagged as an online offer's is (pokeldn.app.online)."""
    return f" [species {f['species']}{' shiny' if f['shiny'] else ''}]" if f else ""


def unnamed(f, why):
    """The line about a Pokemon that names no trainer of the save, when the session names none either."""
    return (f"[gift] the console's Pokemon{species_tag(f)} cannot name the save: {why}, so the gift goes with "
            "your trainer from Settings")


def unnamed_text(why):
    """What the app's pop-up says about a Pokemon that names no trainer of the save."""
    return (f"Neither the Pokemon the console offered nor the session can say whose save this is: {why}. The "
            "gift goes with the trainer from Settings instead. Offer a Pokemon caught in this save to receive "
            "one made for its own trainer.")


def shown_id(trainer):
    """The six-digit trainer ID the Switch games show."""
    return f"{((trainer['sid'] << 16) | trainer['tid']) % 1_000_000:06d}"


def add_arguments(ap, offer_flag):
    """A trade host's flags for a gift made for the receiving player; `offer_flag` names its offers."""
    ap.add_argument("--gift-event", action="append", default=[], metavar="KEY",
                    help=f"the Mystery Gift card each {offer_flag} was made from, in the same order: its key in "
                         "PKHeX's event database (pokeldn.pokemon.Service.gift_events)")
    ap.add_argument("--for-receiver", action="store_true",
                    help="make each --gift-event card that gives the receiver's own trainer again for the "
                         "console's save, during the trade: the console offers first, a Pokemon its save "
                         "caught names the trainer, and ours goes up made for it; for any other, the "
                         "trainer the console's session data names. Failing both, the offer goes as given, "
                         "under the trainer from Settings (pokeldn.receiver_gift, docs/gift_simulated.md)")


def setup(game, args, offers, load, log=print, **check):
    """-> (rounds, make) for a ReceiverGift, when a host runs with --for-receiver and one of its `offers` was
    made from a card that gives the receiver's own trainer; None otherwise. `check` is what the host gave
    `pokeldn.pokemon.prepare_file` for its `offers`, and `load` what it runs on each of them after, its own
    checks and the form it sends: a copy made during the trade takes both (`maker`)."""
    if not getattr(args, "for_receiver", False) or not offers:
        return None
    found = rounds(game, args.gift_event, offers, log)
    if not any(key for key, _ in found):
        return None
    log(READY)
    return found, maker(game, load, **check)


def rounds(game, keys, offers, log=print):
    """-> a ReceiverGift's rounds for a host's `offers`, each made from the card `keys` names in the same order.
    A card that gives the receiver's own trainer keeps its key, to be made for the console's save; the others
    go as made. Each keeps its offer, made under the trainer from Settings, to go when the save names no one.
    Asking now also starts the service before the console arrives."""
    from pokeldn import pokemon
    out = []
    for n, body in enumerate(offers):
        key = keys[n] if n < len(keys) else ""
        if key:
            try:
                info = pokemon.SERVICE.gift_event(game, key, PROBE, keep=False)
            except pokemon.BuilderError as exc:
                log(f"[gift] offer {n + 1}: card {key} is not in this PKHeX ({exc}), so it goes as made")
                out.append(("", bytes(body)))
                continue
            if info["your_ot"]:
                log(f"[gift] offer {n + 1}: {info['title']} is made for the console's save when its offer or "
                    "session names it, and goes with your trainer from Settings otherwise")
            elif info.get("handled"):
                log(f"[gift] offer {n + 1}: {info['title']} is legal only with a handler, which its own trainer's "
                    "save clears, so it goes with your trainer from Settings")
                key = ""
            else:
                log(f"[gift] offer {n + 1}: {info['title']} gives its own trainer and goes as made")
                key = ""
        out.append((key, bytes(body)))
    return out


def maker(game, load, **check):
    """-> make(key, trainer, version) -> (the record the host offers, what it is): the card made for the save on
    that version alone, with the HOME tracker the setting gives it (docs/gui.md, The HOME tracker setting). A
    card no save like it received, on its version or in its language, is refused
    (`pokeldn.pokemon.Service.gift_event`). The copy then takes the checks the host's own offers took at launch:
    the offer check with the host's `check` (`pokeldn.pokemon.prepare_offer`: its --fresh-pid and edits, PKHeX's
    legality check), and the host's `load`. A copy refused or failing any of them raises, saying which and why,
    and the host offers the one made under the trainer from Settings."""
    from pokeldn import pokemon

    def make(key, trainer, version):
        info = pokemon.SERVICE.gift_event(game, key, trainer, version=version, keep=False)
        if info["refused"]:
            raise ValueError(f"the save cannot have received the card: {info['refused']}")
        try:
            checked = pokemon.prepare_offer(game, base64.b64decode(info["data"]), **check)
        except (pokemon.BuilderError, ValueError) as exc:
            raise ValueError(f"the copy fails the host's offer check: {exc}") from exc
        try:
            return load(checked), pokemon.summary(info)
        except (pokemon.BuilderError, ValueError) as exc:
            raise ValueError(f"the host cannot send the copy: {exc}") from exc
    return make


def hear(partner, parse, *data, log=print, game=None):
    """A host passes what the console's session data says of its trainer, `parse(*data)`, to `partner` when
    it is a ReceiverGift; an online partner takes none. With `game`, the app is told of it too
    (pokeldn.console_trainer)."""
    take = getattr(partner, "hear", None)
    if take is None and game is None:
        return
    try:
        fields = parse(*data)
    except Exception as exc:    # the console's bytes, in a shape not measured
        if take is not None:
            log(f"[gift] the session's trainer does not read: {exc}")
        return
    if fields:
        if game is not None:
            console_trainer.show(game, fields, "session")
        if take is not None:
            take(fields)


class Offer:
    """One round's record as a host reads an online partner's: put up once set, never changed."""

    def __init__(self):
        self.offer = None
        self.accepted = True        # our confirm waits for the console's alone


def pop_up(key="gift"):
    """A ReceiverGift's `notify` in a run: the app's pop-up (pokeldn.popup), one per `key`, a newer reason
    replacing the one still open. Hosts with one seat per console key it by the console."""
    from pokeldn import popup
    return lambda title, text: popup.acknowledge(title, text, id=key, tone="warning")


class ReceiverGift:
    """The records one console trades for, in rounds. `rounds` is [(key, body)]: a round with a card key is
    made by `make(key, trainer, version) -> (body, what)` for the console's save, on a worker thread so the
    host's loop never waits; one without goes up as `body` is, and so does one whose save names no one or
    whose card cannot be made for it. A record goes up only after the console has offered in that round, and
    once up it stays: a host's cancel is unmeasured (docs/online.md).
    `read(body)` gives a Pokemon's owner fields (`owner_reader`), on a worker thread too. `notify(title, text)` asks for the app's
    pop-up (`pop_up`). The host passes on what the console's session data says of its trainer with `hear`."""

    def __init__(self, game, rounds, make, read=None, log=print, shown=None, notify=None):
        self.game = game
        self.rounds = [(key or "", bytes(body)) for key, body in rounds]
        self.make, self.log = make, log
        self.read = read or owner_reader(game)
        self.shown = shown or (lambda body: None)
        self.notify = notify or (lambda title, text: None)
        self.lock = threading.Lock()
        self.round = 0
        self.save = None            # (trainer, version), once the console's offer or session named them
        self.named_by = ""          # "pokemon" or "session": a Pokemon the save caught outranks the session
        self.heard = None           # the trainer fields the console's session data gave (`hear`)
        self.made = {}              # round -> the record made for that save
        self.building = None        # the round a build runs for
        self.reading = False        # a worker reads the console's offer
        self.asked = False          # the console has offered in this round and not backed out
        self.told = ""              # the last pop-up's text: the same again stays closed
        self.current = Offer()

    def theirs(self):
        with self.lock:
            return self.current

    def offer(self, body):
        """The console offers `body`."""
        with self.lock:
            self.asked = True
            if self.current.offer is not None or self.reading:
                return
            key, record = self.rounds[self.round]
            if not key:
                self._release(record)
            elif self.named_by == "pokemon":
                self._use(self.round)
            else:       # the service reads the Pokemon: never on the host's loop
                self.reading = True
                threading.Thread(target=self._read_offer, args=(self.round, body), daemon=True).start()

    def _use(self, n):
        if n in self.made:
            self._release(self.made[n])
        else:
            self._build(n)

    def _read_offer(self, n, body):
        try:
            f = self.read(body)
            why = unknown(self.game, f)
        except Exception as exc:    # not a record, or the service is missing
            f, why = None, f"it does not read as a Pokemon ({exc})"
        given = self._given(n)
        with self.lock:
            self.reading = False
            if n != self.round:
                return
            named = self._learn(f, why, given)
            if self.asked and self.current.offer is None:
                self._use(n) if named else self._release(self.rounds[n][1])
            elif named and n not in self.made:      # backed out meanwhile: ready for its next offer
                self._build(n)

    def hear(self, fields):
        """The console's session data names its trainer: `fields` as `from_session` takes them, the id pair and
        name with what of version, gender and language the game's data carries."""
        with self.lock:
            if fields != self.heard:
                self.heard = dict(fields)
                self.log(f"[gift] the session names the console's trainer {fields['ot']}, ID {shown_id(fields)}")

    def _learn(self, f, why, given):
        """Whether the console's save is named, kept for the next rounds: by the offered Pokemon's owner fields
        `f`, when the save caught it (`why` empty), and otherwise by the session (`hear`), `given` filling what
        it lacks. A Pokemon the save caught replaces what the session named. When neither names it, this round's
        gift goes with the trainer from Settings, and the next round asks again."""
        if not why:
            self._named(own_trainer(self.game, f), "pokemon")
            return True
        if self.named_by:
            return True
        found = from_session(self.game, self.heard, f, given) if self.heard else None
        if found is None:
            self.log(unnamed(f, why))
            self._tell(unnamed_text(why))
            return False
        save, notes = found
        self.log(f"[gift] the console's Pokemon{species_tag(f)} cannot name the save: {why}; the session does"
                 + (f" ({', '.join(notes)})" if notes else ""))
        self._named(save, "session")
        return True

    def _given(self, n):
        """-> the owner fields of round `n`'s record, made under the trainer from Settings; {} unread."""
        try:
            return self.read(self.rounds[n][1])
        except Exception:
            return {}

    def _named(self, save, by):
        """The console's save is `save`; a record made for another save before it is made again."""
        self.named_by = by
        if save == self.save:
            return
        self.save = save
        self.made = {n: body for n, body in self.made.items() if n < self.round}
        trainer, version = save
        self.log(f"[gift] making the gift for {trainer['ot']}, ID {shown_id(trainer)}, {NAMES[version]}")

    def _tell(self, text):
        """The app's pop-up saying the gift carries the trainer from Settings, once for each reason."""
        if text != self.told:
            self.told = text
            try:
                self.notify(FALLBACK_TITLE, text)
            except RuntimeError as exc:     # pokeldn.popup's LIMIT: the log line says it already
                self.log(f"[gift] no pop-up: {exc}")

    def withdraw(self):
        """The console backed out of the wait."""
        with self.lock:
            self.asked = False

    def accept(self):
        pass

    def unaccept(self):
        pass

    def done(self):
        """This round's trade completed; the next round's record is made at once for the save. The last round
        serves every later trade, as a host's last offer does, made afresh."""
        with self.lock:
            self.asked = False
            self.current = Offer()
            if self.round + 1 < len(self.rounds):
                self.round += 1
            else:
                self.made.pop(self.round, None)
            if self.rounds[self.round][0] and self.save is not None:
                self._build(self.round)

    def close(self):
        pass

    def _build(self, n):
        if self.building is None:
            self.building = n
            threading.Thread(target=self._run, args=(n, self.save), daemon=True).start()

    def _run(self, n, save):
        trainer, version = save
        try:
            (body, what), why = self.make(self.rounds[n][0], trainer, version), ""
        except Exception as exc:    # the service refused the card for this save, or is missing
            body, what, why = None, "", str(exc) or type(exc).__name__
        with self.lock:
            self.building = None
            if save != self.save:   # named again meanwhile: made again for the save named last
                if n == self.round and self.asked and self.current.offer is None:
                    self._build(n)
                return
            if body is None:
                body = self.rounds[n][1]
                self.log(f"[gift] could not be made for {trainer['ot']}, so it goes with your trainer from "
                         f"Settings: {why}")
                self._tell(f"The gift could not be made for {trainer['ot']}, ID {shown_id(trainer)}, on "
                           f"{NAMES[version]}: {why.rstrip('.')}. It goes with the trainer from Settings instead.")
            else:
                self.log(f"[gift] made for {trainer['ot']}: {what}")
            self.made[n] = body
            if n == self.round and self.asked and self.current.offer is None:
                self._release(body)

    def _release(self, body):
        self.current.offer = body
        self.shown(body)

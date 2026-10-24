"""Scarlet and Violet's wild encounters for the Union Circle's crafted spawns (docs/sv_union_circle.md,
Crafted encounters). PKHeX names every wild slot by the location a catch there names (`areas`); a crafted
spawn is legal where PKHeX accepts it caught (`legal_at`). `Locator` finds which of those locations the
host stands in from the wild Pokemon the host's console shares."""
import math
from dataclasses import dataclass

ANY_FORM = -1           # a slot that draws its form, as Scatterbug's pattern
SPREAD = 100.0          # metres: a host this far from one of the spawns we weigh starts over
HOLD = 50.0             # metres: an area found holds while the host stays this near where it was found
LEFT, SPREAD_OUT = "left", "spread"     # Locator.moved: past HOLD, past SPREAD
GAME, SPAWNS, LOST = "game", "spawns", "lost"    # Locator.source: where the host's position comes from
ESTIMATE_ERROR = 50     # metres: 9 in 10 estimates from the host's spawns fell this near its player in
                        # the captures where both were known (circle.ESTIMATE_SPAWNS)
IV_MAX = 31


@dataclass(frozen=True)
class Slot:
    species: int        # National Dex
    form: int           # ANY_FORM: any
    low: int
    high: int

    def fits(self, species, form, level=None):
        return (self.species == species and self.form in (ANY_FORM, form)
                and (level is None or self.low <= level <= self.high))


@dataclass(frozen=True)
class Area:
    location: int
    name: str
    slots: tuple[Slot, ...]

    def fits(self, species, form, level=None):
        return any(slot.fits(species, form, level) for slot in self.slots)

    def levels(self, species, form):
        """-> the levels this area's slots give `species` in `form`, lowest first."""
        return sorted({level for slot in self.slots if slot.fits(species, form)
                       for level in range(slot.low, slot.high + 1)})


@dataclass(frozen=True)
class Table:
    areas: tuple[Area, ...]
    types: tuple[str, ...] = ()     # the Tera Types' names, Normal to Fairy

    def where(self, species, form, level=None):
        """-> the areas a wild `species` in `form` (at `level`) appears in."""
        return [area for area in self.areas if area.fits(species, form, level)]

    def levels(self, species, form):
        """-> every level a wild `species` in `form` appears at somewhere, lowest first."""
        return sorted({level for area in self.where(species, form)
                       for level in area.levels(species, form)})

    def name(self, location):
        found = [area.name for area in self.areas if area.location == location]
        return found[0] if found and found[0] else f"location {location}"


def table(reply):
    """-> the Table of PKHeX's `wild_areas` reply."""
    return Table(tuple(Area(a["location"], a["name"], tuple(Slot(*slot) for slot in a["slots"]))
                       for a in reply["areas"]), tuple(reply.get("types", ())))


def areas(service):
    """-> PKHeX's wild areas, through `service` (pokeldn.pokemon.Service), read once."""
    key = "sv:wild_areas"
    if key not in service.species_cache:
        service.species_cache[key] = table(service._ask({"cmd": "wild_areas", "game": "sv"}))
    return service.species_cache[key]


def species(service, number, form=0):
    """-> what a crafted spawn of `number` (National Dex) in `form` can hold: {"forms", "types",
    "abilities" (by slot, 2 the hidden one), "gender" ratio, "natures"}."""
    key = f"sv:wild_species:{number}:{form}"
    if key not in service.species_cache:
        service.species_cache[key] = service._ask({"cmd": "wild_species", "game": "sv",
                                                   "species": number, "form": form})
    return service.species_cache[key]


def scan(service, spawn):
    """-> PKHeX's verdict on `spawn` (a dict: species, form, level, tera, shiny, nature, gender, scale,
    ivs, ability, item; None for one drawn at random) caught at each location with a wild slot for its
    species, form and level: [{"location", "name", "teras" (every Tera Type PKHeX accepts there),
    "problems" (with its own Tera Type, none when legal)}]."""
    request = {"cmd": "wild_legal", "game": "sv",
               **{key: value for key, value in spawn.items() if value is not None}}
    return service._ask(request)["locations"]


def legal_at(service, spawn):
    """-> ([locations PKHeX accepts `spawn` caught at], {location: its problems} for the rest with a
    wild slot for its species, form and level)."""
    tera = spawn.get("tera") or 0
    found = scan(service, spawn)
    return ([f["location"] for f in found if tera in f["teras"]],
            {f["location"]: f["problems"] for f in found if tera not in f["teras"]})


class Locator:
    """Which of `wild`'s areas the host stands in, from the wild Pokemon its console shares: each spawn
    narrows the areas to those with a slot for its species, form and level. Found once every area left
    is among `wanted` (where our crafted spawn is legal), where the host stood then; lost when the host
    goes more than HOLD metres from there. Before that, a host more than SPREAD metres from one of the
    spawns weighed starts over, and so does a spawn no area left holds, from that spawn alone; a spawn
    no area holds at all (a raid's, an outbreak's) is left out. `notes` -> what changed (found, started
    over), `details` -> each spawn's narrowing, in order;
    `moved` -> why the host's moving last started over (LEFT or SPREAD), until the next spawn is weighed."""

    def __init__(self, wild, wanted):
        self.wild, self.wanted = wild, set(wanted)
        self.spawns = []        # (species, form, level, position) weighed, in order
        self.candidates = None  # the locations left; None before the first spawn
        self.found_at = None    # where the host stood when its area was found
        self.host_at = None
        self.source = GAME      # where host_at comes from: the host's console, estimated from its spawns, or lost
        self.notes = []
        self.details = []
        self.moved = None

    @property
    def found(self):
        return self.found_at is not None

    def _names(self, locations):
        return ", ".join(sorted(self.wild.name(loc) for loc in locations))

    def _restart(self, why):
        self.spawns, self.candidates, self.found_at = [], None, None
        self.notes.append(why)

    def host_spawn(self, species, form, level, position):
        """Weighs one of the host's spawns (National Dex species) at `position`."""
        if self.found:
            return
        fits = {area.location for area in self.wild.where(species, form, level)}
        if not fits:
            self.details.append(f"the host's spawn of species {species} form {form} level {level} "
                              "fits no wild slot; left out")
            return
        if self.candidates is not None and not self.candidates & fits:
            self._restart(f"the host's spawn of species {species} level {level} fits none of "
                          f"{self._names(self.candidates)}; starting over from it")
        self.moved = None
        before = self.candidates
        self.spawns.append((species, form, level, tuple(position)))
        self.candidates = fits if self.candidates is None else self.candidates & fits
        if self.candidates != before:
            self.details.append(f"the host is in one of {len(self.candidates)} area(s): "
                              f"{self._names(self.candidates)}; our spawn is legal in "
                              f"{len(self.candidates & self.wanted)} of them")
        self._judge()

    def host_moved(self, position):
        self.host_at = tuple(position)
        if self.found:
            if math.dist(self.host_at, self.found_at) > HOLD:
                self._restart(f"the host went more than {HOLD:g} m from where its area was found; "
                              "finding it again")
                self.moved = LEFT
            return
        if any(math.dist(self.host_at, spawn[3]) > SPREAD for spawn in self.spawns):
            self._restart(f"the host went more than {SPREAD:g} m from a spawn weighed; starting over")
            self.moved = SPREAD_OUT
        self._judge()

    def _judge(self):
        if self.found or not self.candidates or self.host_at is None:
            return
        if self.candidates <= self.wanted:
            self.found_at = self.host_at
            self.notes.append(f"the host's area is found: {self._names(self.candidates)}, where our "
                              "spawn is legal")


PICNIC = ("Where you can, start a picnic and pack it up again: the wild Pokemon around you spawn afresh, "
          "which narrows your area faster.")
CARD_NAMES = 160        # characters of area names a card line holds (pokeldn.panel.TEXT is 200)


def _listed(names):
    """-> `names` joined, cut to what a card line holds with how many more there are."""
    names, shown = sorted(names), ""
    for n, name in enumerate(names):
        more = f" and {len(names) - n} more"
        if len(shown) + len(name) + 2 + len(more) > CARD_NAMES:
            return shown + more
        shown = f"{shown}, {name}" if shown else name
    return shown


def _position(locator):
    """-> the card's line on where the host's position comes from; none while its console shows it."""
    if locator.source == SPAWNS:
        return [f"Your position\tEstimated from the wild Pokemon your game spawns around you, give or take "
                f"{ESTIMATE_ERROR} m: your game stopped sharing where you stand."]
    if locator.source == LOST:
        return ["Your position\tYour game stopped sharing where you stand: the next wild Pokemon that spawn "
                "around you place you again."]
    return []


def card(locator, step=5):
    """-> the zone search's status card for pokeldn.panel.show: {"title", "lines", "chips", "tone"}. The
    host's distance from where its area was found goes in `step` metres, so it changes only as often."""
    names = lambda locations: _listed(locator.wild.name(loc) for loc in locations)    # noqa: E731
    legal = names(locator.wanted)
    position = _position(locator)
    if locator.found:
        hold = f"Stay within\t{HOLD:g} m of where it was found"
        if locator.source != LOST:
            hold += f": now {int(math.dist(locator.host_at, locator.found_at) // step * step)} m"
        return {"title": "Area found: spawning", "tone": "ok",
                "chips": [("Areas", str(len(locator.candidates))), ("Pokemon weighed", str(len(locator.spawns)))],
                "lines": [f"You are in\t{names(locator.candidates)}", *position, hold]}
    lines = list(position)
    if locator.moved == LEFT:
        title, tone = "Moved too far: finding your area again", "warning"
        lines.append(f"Why\tYou went more than {HOLD:g} m from where your area was found.")
    elif locator.moved == SPREAD_OUT:
        title, tone = "Moved too far: finding your area again", "warning"
        lines.append(f"Why\tYou went more than {SPREAD:g} m from a wild Pokemon it had read.")
    elif locator.candidates is None:
        title, tone = "Finding your area", "info"
        lines.append("Walk where wild Pokemon spawn: each one your game shows narrows where you are.")
    elif not locator.candidates & locator.wanted:
        return {"title": "Not in an area where it is legal", "tone": "error",
                "chips": [("Areas left", str(len(locator.candidates))), ("Pokemon weighed", str(len(locator.spawns)))],
                "lines": [f"You seem to be in\t{names(locator.candidates)}", *position,
                          f"Go to\t{legal}",
                          "Once there, the wild Pokemon around you confirm the area.", PICNIC]}
    else:
        title, tone = "Narrowing down your area", "info"
    chips = []
    if locator.candidates is not None:
        chips = [("Areas left", str(len(locator.candidates))),
                 ("Legal in", str(len(locator.candidates & locator.wanted))),
                 ("Pokemon weighed", str(len(locator.spawns)))]
        lines.append(f"You may be in\t{names(locator.candidates)}")
    lines += [f"Legal at\t{legal}", PICNIC]
    return {"title": title, "tone": tone, "chips": chips, "lines": lines}

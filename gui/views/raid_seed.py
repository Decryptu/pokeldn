"""The raid seed field: the boss and rewards the seed gives in the chosen context, and a finder that
searches seeds by what the boss is and the rewards it gives (pokeldn.sv.raid_search). An event's
context (its `event`, `group` and `den`) draws from the event and narrows the finder to what the
event spawns."""

import re
import threading

import flet as ft

from gui import theme as t
from gui.views.pokemon import NamePicker
from gui.views.reward_filter import RewardFilter
from gui.views.sprites import MINI, SIZE, Sprite
from gui.views.widgets import PixelActivity
from pokeldn import pokemon as builder
from pokeldn.sv import raid_encounter, raid_event, raid_search
from pokeldn.sv.raid_encounter import NATURES, TERA_TYPES
GENDERS = ("Male", "Female", "Genderless")
STATS = ("HP", "Atk", "Def", "Spe", "SpA", "SpD")
PROGRESS = (("beginning", "Beginning"), ("tera", "Tera Raids unlocked"), ("3star", "3-star raids"),
            ("4star", "4-star raids"), ("5star", "5-star raids"), ("6star", "6-star raids"))


def seed_of(text: str) -> int | None:
    return int(text, 16) if re.fullmatch(r"[0-9A-Fa-f]{8}", text or "") else None


def iv_range(text: str) -> tuple[int, int]:
    """'' any, '31' exactly, '20-31' a range."""
    text = (text or "").strip()
    if not text:
        return 0, 31
    match = re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?", text)
    low, high = (int(match.group(1)), int(match.group(2) or match.group(1))) if match else (1, 0)
    if not 0 <= low <= high <= 31:
        raise ValueError("An IV is blank, a value from 0 to 31, or a range such as 20-31.")
    return low, high


CRYSTALS = {"standard": "Standard crystal", "black": "Black crystal", "event": "Event crystal",
            "might": "Seven-star event crystal"}


def crystal_colors(context) -> tuple[str, str]:
    return t.BRAND_RED if context["content"] in ("black", "might") else t.BRAND_BLUE


def stars_row(count: int, context) -> ft.ShaderMask:
    """The raid's stars as pixel stars in the crystal's brand gradient: blue standard, red black."""
    return t.tinted(ft.Row([t.pixel_icon("star", color="#FFFFFF") for _ in range(count)], spacing=1,
                           tight=True), crystal_colors(context))


def framed_sprite(app, species: int, shiny: bool, size: int, context) -> ft.Container:
    """The sprite inside a ring of the crystal's gradient."""
    sprite = Sprite(app, species, shiny, size=size)
    sprite.frame.border = None
    radius = 12 if size >= SIZE else 10
    return ft.Container(sprite.control, padding=1.5, border_radius=radius + 1.5,
                        gradient=ft.LinearGradient(begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
                                                   colors=list(crystal_colors(context))),
                        shadow=ft.BoxShadow(blur_radius=18, spread_radius=-6,
                                            color=ft.Colors.with_opacity(0.45, crystal_colors(context)[1])))


def iv_tile(label: str, iv: int, stat: int, compact: bool) -> ft.Container:
    """One stat: its IV large (blue at 31, red at 0), a bar of IV out of 31, the stat at the boss's level."""
    color = t.BLUE if iv == 31 else t.RED if iv == 0 else t.TEXT
    bar = ft.ProgressBar(value=iv / 31, color=t.BLUE, bgcolor=ft.Colors.with_opacity(0.08, "#FFFFFF"),
                         bar_height=3, border_radius=2)
    rows = [t.text(label, 10, t.MUTED, weight=ft.FontWeight.W_600),
            t.text(str(iv), 13 if compact else 17, color, weight=ft.FontWeight.W_700), bar]
    if not compact:
        rows.append(t.text(f"{stat}", 10, t.FAINT, tooltip="The stat at the boss's level"))
    return ft.Container(ft.Column(rows, spacing=3 if compact else 4, tight=True,
                                  horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        width=46 if compact else 62, padding=ft.Padding(6, 6, 6, 8), border_radius=10,
                        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"))


def reward_chips(names: dict[int, str] | None, rewards) -> ft.Control:
    """The rewards as item chips, one per item with the quantities summed, in the raid's order."""
    if names is None:
        return ft.Row([PixelActivity("Naming the rewards"), t.text("Naming the rewards...", 12, t.MUTED)],
                      spacing=8)
    totals: dict[int, int] = {}
    for item, quantity in rewards:
        totals[item] = totals.get(item, 0) + quantity
    return ft.Row([ft.Container(ft.Row([
        t.text(names.get(item, f"Item {item}"), 12, t.SOFT),
        t.text(f"×{quantity}", 12, t.BLUE, weight=ft.FontWeight.W_700)], spacing=6, tight=True),
        padding=ft.Padding(10, 4, 10, 4), border_radius=999, bgcolor=ft.Colors.with_opacity(0.06, "#FFFFFF"))
        for item, quantity in totals.items()], spacing=6, run_spacing=6, wrap=True)


def boss_card(app, seed, stars, boss, context, *, compact=False, rewards=None, on_use=None):
    """The boss a seed gives: sprite, stars, level, Tera type, IVs over stats, nature, context."""
    shiny = (boss["trainer_id"] ^ boss["secret_id"] ^ (boss["pid"] >> 16) ^ (boss["pid"] & 0xFFFF)) < 16
    name = raid_encounter.tables()["species_names"][str(boss["species"])]
    title = [t.text(name, 14 if compact else 17, weight=ft.FontWeight.W_700)]
    if shiny:
        title.append(t.tinted(t.pixel_icon("sparkles", color="#FFFFFF", tooltip="Shiny"), crystal_colors(context)))
    title.append(stars_row(stars, context))
    accent = t.RED if context["content"] in ("black", "might") else t.BLUE
    facts = ft.Row([
        t.chip(f"Level {boss['level']}", "sword", accent),
        t.chip(f"{TERA_TYPES[boss['tera_type_original']]} Tera", "diamond-gem", accent),
        t.chip(NATURES[boss["nature"]]), t.chip(GENDERS[boss["gender"]]),
        *([t.chip("Shiny", "sparkles", accent)] if shiny and not compact else []),
    ], spacing=6, run_spacing=6, wrap=True)
    where = (f"{context['version'].title()} · {context['map_name'].title()} · "
             f"{dict(PROGRESS)[context['progress']]} · {CRYSTALS[context['content']]}"
             + (f" · {context['den']}" if context.get("den") else ""))
    ivs = ft.Row([iv_tile(label, iv, stat, compact)
                  for label, iv, stat in zip(STATS, boss["ivs"], boss["stats"])], spacing=6, wrap=True)
    column = [ft.Row(title, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), facts, ivs]
    if compact:
        column.append(ft.Row([t.text(f"{seed:08X}", 11, t.SOFT, font_family=t.MONO, selectable=True),
                              t.text(where, 11, t.FAINT)], spacing=10, wrap=True))
    else:
        column.append(ft.Row([t.pixel_icon("map-pin", size=12, color=t.FAINT), t.text(where, 12, t.MUTED)],
                             spacing=6))
    row = [framed_sprite(app, boss["species"], shiny, MINI if compact else SIZE, context),
           ft.Column(column, spacing=8 if compact else 10, expand=True)]
    if on_use:
        row.append(t.secondary_button("Use", lambda _e: on_use(seed, context), "check"))
    body = ft.Row(row, spacing=14 if compact else 18, vertical_alignment=ft.CrossAxisAlignment.START)
    if rewards is not None:
        body = ft.Column([body, ft.Container(height=1, bgcolor=t.DIVIDER),
                          ft.Row([t.pixel_icon("gift", size=12, color=t.MUTED),
                                  t.text("The raid's own rewards", 12, t.MUTED, weight=ft.FontWeight.W_600)], spacing=6),
                          rewards], spacing=10, tight=True)
    return ft.Container(body, padding=12 if compact else 16, border_radius=14,
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.08, "#FFFFFF")),
                        gradient=ft.LinearGradient(begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
                                                   colors=[ft.Colors.with_opacity(0.08, accent), t.FIELD],
                                                   stops=[0, 0.55]))


class RaidSeedPicker:
    """The seed, what it gives in the tool's raid context, and Find a raid."""

    def __init__(self, app, value: str, on_change, context, on_context_change):
        self.app, self.on_change = app, on_change
        self.context, self.on_context_change = context, on_context_change
        self.seed = t.field(value=str(value or ""), mono=True, expand=True, on_change=self._typed)
        self.preview = ft.Container()
        self.control = ft.Column([
            ft.Row([self.seed, t.secondary_button("Find a raid", self._open, "search")], spacing=8),
            self.preview], spacing=8, tight=True)
        self._show(str(value or ""), update=False)

    def _show(self, text: str, update: bool = True) -> None:
        seed = seed_of(text)
        self.seed.error = None if seed is not None else "Eight hexadecimal digits."
        self.preview.content = None
        if seed is not None:
            context = self.context()
            try:
                raid = raid_search.generate(seed, context)
            except ValueError as exc:       # an event this context cannot spawn
                self.seed.error, raid = str(exc), None
            if raid is not None:
                rewards = ft.Container(reward_chips(None, raid.rewards))
                self.preview.content = boss_card(self.app, seed, raid.stars, raid.boss,
                                                 {**context, **raid.context}, rewards=rewards)
                threading.Thread(target=self._name_rewards, args=(rewards, raid.rewards), daemon=True).start()
        if update:
            self.control.update()

    def _name_rewards(self, holder, rewards) -> None:
        try:
            names = {n["id"]: n["name"] for n in builder.SERVICE.names("sv", "bag")}
        except Exception:
            names = {}
        holder.content = reward_chips(names, rewards)
        self.app.ui(lambda: self._update(holder))

    @staticmethod
    def _update(control) -> None:
        try:
            control.update()
        except RuntimeError:        # the card was redrawn while the names loaded
            pass

    def _typed(self, event) -> None:
        event.control.value = event.control.value.upper()
        self.on_change(event.control.value)
        self._show(event.control.value)

    def _use(self, seed: int, context: dict) -> None:
        self.app.page.pop_dialog()
        self.seed.value = f"{seed:08X}"
        self.on_change(self.seed.value)
        self.on_context_change(context)

    def _open(self, _event) -> None:
        current = self.context()
        event = current.get("event")
        pick = lambda control: None if control.value in (None, "any", "-", "") else control.value

        def reward_scope():
            """-> the contexts searched and the boss filters that narrow the rewards listed."""
            scope = raid_search.contexts(version.value, region.value, story.value, crystal.value,
                                         event=event, group=crystal.value)
            if not scope:
                raise ValueError("No den of the event spawns in that game at that progress.")
            return scope, dict(stars=pick(stars) and int(stars.value),
                               species_id=pick(species) and int(species.value),
                               tera_type=pick(tera) and int(tera.value))
        wants = RewardFilter(self.app, reward_scope)
        if raid_search.FAST:          # the compiled scan loads while the filters are chosen
            threading.Thread(target=lambda: raid_search.raid_kernel().warm(), daemon=True).start()
        choose = lambda options, value: t.dropdown(options, value, on_select=lambda _e: wants.changed())
        if event is None:
            version = choose([("any", "Any game"), ("scarlet", "Scarlet"), ("violet", "Violet")],
                             current["version"])
            region = choose([("any", "Any region"), ("paldea", "Paldea"), ("kitakami", "Kitakami"),
                             ("blueberry", "Blueberry")], current["map_name"])
            story = choose([("any", "Any progress"), *PROGRESS], current["progress"])
            crystal = choose([("any", "Any crystal"), ("standard", "Standard"), ("black", "Black")], "any")
            star_levels = range(1, 7)
        else:
            # Only what the event spawns: its games, Paldea, its dens and the progresses they draw at.
            games = raid_event.versions(event)
            version = choose(([("any", "Any game")] if len(games) > 1 else [])
                             + [(v, v.title()) for v in games], current["version"])
            region = choose([("paldea", "Paldea")], "paldea")
            region.disabled = True
            dens = raid_event.dens(event)
            stages = {p for v in games for d in raid_event.dens(event, v)
                      for p in raid_event.progresses(event, v, d.group)}
            story = choose([("any", "Any progress"),
                            *((key, label) for key, label in PROGRESS if key in stages)], current["progress"])
            crystal = choose(([("any", "Any den")] if len(dens) > 1 else [])
                             + [(str(d.group), d.label) for d in dens], str(current["group"]))
            star_levels = sorted({s for d in dens for s in d.stars})
        species = NamePicker(self.app, "sv", "species", "", lambda _v: wants.changed(),
                             names=[{"id": s, "name": n} for s, n in raid_search.species(event)]).control
        stars = choose([("any", "Any stars"), *((str(n), f"{n} stars") for n in star_levels)], "any")
        tera = choose([("any", "Any Tera type"), *((str(i), n) for i, n in enumerate(TERA_TYPES))], "any")
        nature = choose([("any", "Any nature"), *((str(i), n) for i, n in enumerate(NATURES))], "any")
        gender = choose([("any", "Any gender"), *((str(i), n) for i, n in enumerate(GENDERS))], "any")
        shiny = choose([("any", "Shiny or not"), ("yes", "Shiny only"), ("no", "Not shiny")], "any")
        rank = choose([(key, label) for key, (label, _, _) in raid_search.OBJECTIVES.items()], "overall")
        ivs = [t.field(hint="any", mono=True, expand=True, text_align=ft.TextAlign.CENTER,
                       content_padding=ft.Padding(4, 8, 4, 8)) for _ in STATS]
        start = t.field(value=self.seed.value if seed_of(self.seed.value) is not None else "00000000",
                        mono=True)
        count = t.field(value="100000", mono=True, keyboard_type=ft.KeyboardType.NUMBER)
        results = ft.ListView(spacing=8, expand=True)
        results.controls = [empty_results()]
        status = t.text("Choose what the raid should be, then Search.", 12, t.MUTED)
        busy = ft.Container(PixelActivity("Searching"), visible=False)
        run = t.button("Search", None, "search")
        stop = t.secondary_button("Stop", None)
        stop.disabled = True
        cancel, closed = threading.Event(), threading.Event()

        def close(_=None):
            cancel.set()
            closed.set()
            self.app.page.pop_dialog()

        def done(found, stopped):
            if closed.is_set():
                return
            results.controls = [boss_card(self.app, f.seed, f.stars, f.boss, f.context, compact=True,
                                          rewards=reward_chips(wants.names, f.rewards) if f.rewards else None,
                                          on_use=self._use) for f in found] or [empty_results(True)]
            status.value = (f"{len(found)} {'raid' if len(found) == 1 else 'raids'}"
                            + (" before the search stopped." if stopped else ".") if found else "No raid matches.")
            run.disabled, stop.disabled, busy.visible = False, True, False
            for control in (results, status, run, stop, busy):
                control.update()

        def submit(_):
            try:
                scope = raid_search.contexts(version.value, region.value, story.value, crystal.value,
                                             event=event, group=crystal.value)
                if not scope:
                    raise ValueError("No den of the event spawns in that game at that progress.")
                first, amount = seed_of(start.value), int(count.value)
                if first is None or not 1 <= amount * len(scope) <= raid_search.MAX_WORK:
                    raise ValueError(f"Start at an eight-digit seed and search up to "
                                     f"{raid_search.MAX_WORK // len(scope):,} seeds in this scope.")
                ranges = tuple(iv_range(field.value) for field in ivs)
                filters = dict(stars=pick(stars) and int(stars.value),
                               species_id=pick(species) and int(species.value),
                               tera_type=pick(tera) and int(tera.value),
                               nature=pick(nature) and int(nature.value),
                               gender=pick(gender) and int(gender.value),
                               shiny=None if pick(shiny) is None else shiny.value == "yes",
                               ivs=None if ranges == ((0, 31),) * 6 else ranges,
                               rewards=wants.wanted())
            except ValueError as exc:
                status.value, status.color = str(exc), t.RED
                status.update()
                return
            cancel.clear()
            status.value, status.color = "Searching...", t.MUTED
            results.controls, run.disabled, stop.disabled, busy.visible = [], True, False, True
            for control in (status, results, run, stop, busy):
                control.update()

            def progress(done_count, total):
                status.value = f"Searching {done_count:,} of {total:,} seeds..."
                self.app.ui(lambda: self._update(status))

            def work():
                try:
                    found = raid_search.search(first, amount, scope, rank.value,
                                               one_per_species=filters["species_id"] is None, limit=30,
                                               progress=progress, cancelled=cancel.is_set, **filters)
                    self.app.ui(lambda: done(found, cancel.is_set()))
                except Exception as exc:
                    message = str(exc)

                    def failed():
                        if not closed.is_set():
                            status.value, status.color, run.disabled = message, t.RED, False
                            stop.disabled, busy.visible = True, False
                            for control in (status, run, stop, busy):
                                control.update()
                    self.app.ui(failed)
            threading.Thread(target=work, daemon=True).start()

        run.on_click = submit
        stop.on_click = lambda _e: cancel.set()
        pair = lambda *controls: ft.Row(list(controls), spacing=8)
        filters = ft.Column([
            heading("map-pin", "Where the raid is"),
            pair(t.labeled_control("Game", version, expand=True), t.labeled_control("Region", region, expand=True)),
            pair(t.labeled_control("Story progress", story, expand=True),
                 t.labeled_control("Crystal", crystal, expand=True)),
            heading("sword", "The boss"),
            pair(t.labeled_control("Species", species, expand=True), t.labeled_control("Stars", stars, expand=True)),
            pair(t.labeled_control("Tera type", tera, expand=True), t.labeled_control("Nature", nature, expand=True)),
            pair(t.labeled_control("Gender", gender, expand=True), t.labeled_control("Shiny", shiny, expand=True)),
            heading("sliders-horizontal", "IVs"),
            pair(*(t.labeled_control(label, field, expand=True) for label, field in zip(STATS, ivs))),
            t.text("Blank for any, a value, or a range such as 20-31.", 11, t.FAINT),
            wants.control,
            heading("search", "Search"),
            t.labeled_control("Rank by", rank),
            t.text("Bulk and offense estimate how hard the boss is from its stats alone.", 11, t.FAINT),
            pair(t.labeled_control("First seed", start, expand=True),
                 t.labeled_control("Seeds to search", count, expand=True)),
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        found = ft.Column([
            ft.Row([busy, status], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            t.fade(results)], spacing=10, expand=True)
        self.app.page.show_dialog(t.dialog(
            title=t.text("Find a Tera Raid", 17, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Row([
                ft.Container(t.fade(filters), width=360, padding=ft.Padding(0, 0, 12, 0)),
                ft.Container(width=1, bgcolor=t.DIVIDER),
                ft.Container(found, expand=True, padding=ft.Padding(8, 0, 0, 0)),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.STRETCH), width=1000, height=600),
            actions=[t.secondary_button("Close", close), stop, run]))


def heading(icon: str, title: str) -> ft.Container:
    return ft.Container(ft.Row([t.pixel_icon(icon, size=12, color=t.BLUE),
                                t.text(title, 12, t.SOFT, weight=ft.FontWeight.W_600)], spacing=8),
                        padding=ft.Padding(0, 6, 0, 0))


def empty_results(searched: bool = False) -> ft.Container:
    return ft.Container(ft.Column([
        t.tinted(t.pixel_icon("diamond-gem", size=48, color="#FFFFFF"), t.BRAND_BLUE),
        t.text("No raid matches. Widen a filter or search more seeds." if searched else
               "The raids the search finds appear here.", 13, t.MUTED, text_align=ft.TextAlign.CENTER),
    ], spacing=12, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER, padding=ft.Padding(0, 120, 0, 0))

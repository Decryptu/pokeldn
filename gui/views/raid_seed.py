"""The raid seed field: the boss and rewards the seed gives in the chosen context, and a finder that
searches seeds by what the boss is (pokeldn.sv.raid_search)."""

import re
import threading

import flet as ft

from gui import theme as t
from gui.views.pokemon import NamePicker
from gui.views.sprites import MINI, SIZE, Sprite
from pokeldn import pokemon as builder
from pokeldn.sv import raid_encounter, raid_search

TERA_TYPES = ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost", "Steel",
              "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon", "Dark", "Fairy")
NATURES = ("Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish",
           "Lax", "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful",
           "Rash", "Calm", "Gentle", "Sassy", "Careful", "Quirky")
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


def boss_card(app, seed, stars, boss, context, *, compact=False, rewards=None, on_use=None):
    """The boss a seed gives: sprite, stars, level, Tera type, IVs over stats, nature, context."""
    shiny = (boss["trainer_id"] ^ boss["secret_id"] ^ (boss["pid"] >> 16) ^ (boss["pid"] & 0xFFFF)) < 16
    name = raid_encounter.tables()["species_names"][str(boss["species"])]
    cells = ft.Row([ft.Container(ft.Column([
        t.text(label, 9, t.MUTED), t.text(str(iv), 14 if compact else 16, t.GREEN if iv == 31 else t.TEXT,
                                          weight=ft.FontWeight.W_700),
        t.text(str(stat), 9, t.FAINT)], spacing=0, tight=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER), width=48 if compact else 58,
        padding=4, border_radius=8, bgcolor=t.FIELD)
        for label, iv, stat in zip(STATS, boss["ivs"], boss["stats"])], spacing=4, wrap=True)
    head = ft.Row([
        t.text(name + (" (shiny)" if shiny else ""), 13 if compact else 16, t.AMBER if shiny else t.TEXT,
               weight=ft.FontWeight.W_700),
        t.text("★" * stars, 13 if compact else 16, t.AMBER),
        t.badge(f"Level {boss['level']}", t.BLUE, "zap"),
        t.badge(f"{TERA_TYPES[boss['tera_type_original']]} Tera", t.SOFT, "shield"),
    ], spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    facts = (f"{NATURES[boss['nature']]} · {GENDERS[boss['gender']]} · seed {seed:08X} · "
             f"{context['version'].title()}, {context['map_name'].title()}, "
             f"{dict(PROGRESS)[context['progress']]}, {context['content']} crystal")
    column = [head, t.text(facts, 10, t.FAINT), cells]
    if rewards is not None:
        column.append(rewards)
    row = [Sprite(app, boss["species"], shiny, size=MINI if compact else SIZE).control,
           ft.Column(column, spacing=6, expand=True)]
    if on_use:
        row.append(t.secondary_button("Use", lambda _e: on_use(seed, context)))
    return ft.Container(ft.Row(row, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=10 if compact else 12, bgcolor=t.FIELD, border_radius=12)


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
            raid = raid_encounter.generate(seed, **self.context())
            rewards = t.text("", 10, t.MUTED)
            self.preview.content = boss_card(self.app, seed, raid.stars, raid.boss, raid.context,
                                             rewards=rewards)
            threading.Thread(target=self._name_rewards, args=(rewards, raid.rewards), daemon=True).start()
        if update:
            self.control.update()

    def _name_rewards(self, label, rewards) -> None:
        try:
            names = {n["id"]: n["name"] for n in builder.SERVICE.names("sv", "bag")}
        except Exception:
            names = {}
        label.value = "Rewards: " + ", ".join(f"{names.get(item, f'item {item}')} ×{quantity}"
                                              for item, quantity in rewards)
        self.app.ui(lambda: self._update(label))

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
        choose = lambda options, value: t.dropdown(options, value)
        version = choose([("any", "Any game"), ("scarlet", "Scarlet"), ("violet", "Violet")], current["version"])
        region = choose([("any", "Any region"), ("paldea", "Paldea"), ("kitakami", "Kitakami"),
                         ("blueberry", "Blueberry")], current["map_name"])
        story = choose([("any", "Any progress"), *PROGRESS], current["progress"])
        crystal = choose([("any", "Standard or black"), ("standard", "Standard"), ("black", "Black")], "any")
        species = NamePicker(self.app, "sv", "species", "", lambda _v: None,
                             names=[{"id": s, "name": n} for s, n in raid_search.species()]).control
        stars = choose([("any", "Any stars"), *((str(n), f"{n} stars") for n in range(1, 7))], "any")
        tera = choose([("any", "Any Tera type"), *((str(i), n) for i, n in enumerate(TERA_TYPES))], "any")
        nature = choose([("any", "Any nature"), *((str(i), n) for i, n in enumerate(NATURES))], "any")
        gender = choose([("any", "Any gender"), *((str(i), n) for i, n in enumerate(GENDERS))], "any")
        shiny = choose([("any", "Shiny or not"), ("yes", "Shiny only"), ("no", "Not shiny")], "any")
        rank = choose([(key, label) for key, (label, _, _) in raid_search.OBJECTIVES.items()], "overall")
        ivs = [t.field(hint="0-31", mono=True, width=66) for _ in STATS]
        start = t.field(value=self.seed.value if seed_of(self.seed.value) is not None else "00000000",
                        mono=True)
        count = t.field(value="100000", mono=True, keyboard_type=ft.KeyboardType.NUMBER)
        results = ft.ListView(spacing=8, height=300)
        status = t.text("", 12, t.MUTED)
        run = t.button("Search", None, "search")
        stop = t.secondary_button("Stop", None)
        stop.disabled = True
        cancel, closed = threading.Event(), threading.Event()
        pick = lambda control: None if control.value in (None, "any", "-", "") else control.value

        def close(_=None):
            cancel.set()
            closed.set()
            self.app.page.pop_dialog()

        def done(found, stopped):
            if closed.is_set():
                return
            results.controls = [boss_card(self.app, f.seed, f.stars, f.boss, f.context, compact=True,
                                          on_use=self._use) for f in found]
            status.value = (f"{len(found)} raid(s)" + (" before the search stopped." if stopped else ".")
                            if found else "No raid matches.")
            run.disabled, stop.disabled = False, True
            for control in (results, status, run, stop):
                control.update()

        def submit(_):
            try:
                first, amount = seed_of(start.value), int(count.value)
                scope = raid_search.contexts(version.value, region.value, story.value, crystal.value)
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
                               ivs=None if ranges == ((0, 31),) * 6 else ranges)
            except ValueError as exc:
                status.value, status.color = str(exc), t.RED
                status.update()
                return
            cancel.clear()
            status.value, status.color = "Searching…", t.MUTED
            results.controls, run.disabled, stop.disabled = [], True, False
            for control in (status, results, run, stop):
                control.update()

            def progress(done_count, total):
                status.value = f"Searching {done_count:,} of {total:,}…"
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
                            status.update()
                            run.update()
                    self.app.ui(failed)
            threading.Thread(target=work, daemon=True).start()

        run.on_click = submit
        stop.on_click = lambda _e: cancel.set()
        self.app.page.show_dialog(t.dialog(
            title=t.text("Find a Tera Raid", 17, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Column([
                t.text("Search seeds for the raid you want. Ranking by bulk or offense estimates "
                       "how hard the boss is from its stats alone.", 12, t.MUTED),
                ft.Row([version, region, story, crystal], spacing=8),
                ft.Row([t.labeled_control("Species", species, expand=True),
                        t.labeled_control("Stars", stars, expand=True),
                        t.labeled_control("Tera type", tera, expand=True)], spacing=8),
                ft.Row([t.labeled_control("Nature", nature, expand=True),
                        t.labeled_control("Gender", gender, expand=True),
                        t.labeled_control("Shiny", shiny, expand=True),
                        t.labeled_control("Rank by", rank, expand=True)], spacing=8),
                t.text("IVs: blank for any, a value, or a range such as 20-31", 11, t.MUTED),
                ft.Row([t.labeled_control(label, field) for label, field in zip(STATS, ivs)], spacing=6),
                ft.Row([t.labeled_control("First seed", start, expand=True),
                        t.labeled_control("Seeds to search", count, expand=True)], spacing=8),
                status, results,
            ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO), width=860, height=600),
            actions=[t.secondary_button("Close", close), stop, run]))

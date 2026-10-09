"""Seed preview and local encounter finder for the Scarlet/Violet raid host."""

from __future__ import annotations

import re
import threading

import flet as ft

from gui import theme as t
from gui.views.pokemon import NamePicker
from gui.views.sprites import MINI, SIZE, Sprite
from pokeldn.sv.raid_search import (MAX_SEARCH_WORK, OBJECTIVES, VALIDATED_CONTEXT, candidate,
                                    context_combinations, raid_species, search)


TERA_TYPES = ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost",
              "Steel", "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon",
              "Dark", "Fairy")
STAT_LABELS = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
NATURES = ("Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed",
           "Impish", "Lax", "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest",
           "Mild", "Quiet", "Bashful", "Rash", "Calm", "Gentle", "Sassy", "Careful", "Quirky")
GENDERS = ("Male", "Female", "Genderless")


def _seed(text: str) -> int | None:
    return int(text, 16) if re.fullmatch(r"[0-9A-Fa-f]{8}", text or "") else None


def _tera(found) -> str:
    return TERA_TYPES[found.tera_type] if 0 <= found.tera_type < len(TERA_TYPES) else str(found.tera_type)


def _iv_range(value: str) -> tuple[int, int]:
    """Parse a blank, exact IV, or inclusive range from a compact search field."""
    text = (value or "").strip()
    if not text:
        return 0, 31
    match = re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?", text)
    if not match:
        raise ValueError("IVs must be blank, an exact value, or a range such as 20-31.")
    low = int(match.group(1))
    high = int(match.group(2)) if match.group(2) is not None else low
    if not 0 <= low <= high <= 31:
        raise ValueError("IV values must be between 0 and 31, with the lower value first.")
    return low, high


def _stars(count: int, compact: bool = False) -> ft.Control:
    return t.text(" ".join("★" for _ in range(count)), 14 if compact else 18, t.AMBER,
                  weight=ft.FontWeight.W_700)


def _shiny(found) -> ft.Control:
    return (ft.Container(t.text("✦ SHINY", 10, t.AMBER, weight=ft.FontWeight.W_700),
                         padding=ft.Padding(8, 3, 8, 3), border_radius=10,
                         bgcolor=ft.Colors.with_opacity(0.13, t.AMBER))
            if found.shiny else
            ft.Container(t.text("Not shiny", 10, t.FAINT), padding=ft.Padding(8, 3, 8, 3),
                         border_radius=10, bgcolor=ft.Colors.with_opacity(0.05, "#FFFFFF")))


def _stat_cell(label: str, iv: int, stat: int, compact: bool) -> ft.Control:
    perfect = iv == 31
    return ft.Container(ft.Column([
        t.text(label, 9 if compact else 10, t.MUTED, weight=ft.FontWeight.W_600),
        t.text(str(iv), 14 if compact else 17, t.GREEN if perfect else t.TEXT,
               weight=ft.FontWeight.W_700),
        t.text(f"Stat {stat}", 9, t.FAINT),
    ], spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        width=48 if compact else 62, padding=ft.Padding(4, 5, 4, 5), border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.07, t.GREEN if perfect else "#FFFFFF"))


def encounter_card(app, found, *, compact: bool = False, on_use=None) -> ft.Control:
    """A visual generated encounter shared by the live preview and search results."""
    form = f" · form {found.form}" if found.form else ""
    stats = ft.Row([_stat_cell(label, iv, stat, compact)
                    for label, iv, stat in zip(STAT_LABELS, found.ivs, found.stats)],
                   spacing=4 if compact else 6, wrap=True)
    headline = ft.Row([
        t.text(f"{found.name}{form}", 13 if compact else 17, t.TEXT,
               weight=ft.FontWeight.W_700),
        _shiny(found),
    ], spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    facts = ft.Row([
        _stars(found.stars, compact),
        t.badge(f"Level {found.level}", t.BLUE, "zap"),
        t.badge(f"{_tera(found)} Tera", t.SOFT, "shield"),
        t.text(f"Seed {found.seed:08X}", 10 if compact else 11, t.FAINT,
               style=ft.TextStyle(height=1.4, font_family=t.MONO)),
    ], spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    attributes = t.text(
        f"{NATURES[found.nature]} · ability #{found.ability} · {GENDERS[found.gender]} · "
        f"{found.version.title()} / {found.map_name.title()} / {found.progress} / {found.content}",
        9 if compact else 10, t.FAINT)
    detail = ft.Column([headline, facts, attributes, stats], spacing=6 if compact else 9, expand=True)
    controls = [Sprite(app, found.species, found.shiny, size=MINI if compact else SIZE).control,
                detail]
    if on_use:
        controls.append(t.secondary_button("Use", lambda _e: on_use(found)))
    return ft.Container(ft.Row(controls, spacing=10 if compact else 14,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=10 if compact else 12, bgcolor=t.FIELD, border_radius=12)


class RaidSeedPicker:
    """An eight-digit seed field with decoded preview and a ranked local search."""

    def __init__(self, app, value: str, on_change, context=None, on_context_change=None):
        self.app, self.on_change = app, on_change
        self.context = context or (lambda: dict(VALIDATED_CONTEXT))
        self.on_context_change = on_context_change
        self.seed = t.field(value=str(value or ""), mono=True, expand=True, on_change=self._changed)
        self.preview = ft.Container()
        self.control = ft.Column([
            ft.Row([self.seed, t.secondary_button("Find a raid", self._open, "search")], spacing=8),
            self.preview,
        ], spacing=8, tight=True)
        self._preview(str(value or ""), update=False)

    def _preview(self, value: str, update: bool = True) -> None:
        parsed = _seed(value)
        self.seed.error = None if parsed is not None else "Enter exactly eight hexadecimal digits."
        if parsed is None:
            self.preview.content = None
        else:
            try:
                self.preview.content = encounter_card(
                    self.app, candidate(parsed, context=self.context()))
            except ValueError as exc:
                self.preview.content = t.text(str(exc), 12, t.RED)
        if update:
            self.control.update()

    def _changed(self, event) -> None:
        value = event.control.value.upper()
        event.control.value = value
        self.on_change(value)
        self._preview(value)

    def _choose(self, found) -> None:
        value = f"{found.seed:08X}"
        self.seed.value = value
        self.app.page.pop_dialog()
        self.on_change(value)
        if self.on_context_change:
            self.on_context_change(found.context)
        else:
            self._preview(value)

    def _open(self, _event) -> None:
        objective = t.dropdown([(key, label) for key, (label, _minimize) in OBJECTIVES.items()],
                               "overall")
        stars = t.dropdown([("any", "Any (1–6 stars)"), ("1", "1 star"), ("2", "2 stars"),
                            ("3", "3 stars"), ("4", "4 stars"), ("5", "5 stars"),
                            ("6", "6 stars")], "any")
        shiny = t.dropdown([("any", "Any"), ("yes", "Shiny only"), ("no", "Not shiny")], "any")
        species = NamePicker(self.app, "sv", "species", "", lambda _value: None,
                             names=raid_species()).control
        tera = t.dropdown([("any", "Any Tera type"),
                           *((str(index), name) for index, name in enumerate(TERA_TYPES))], "any")
        nature = t.dropdown([("any", "Any nature"),
                             *((str(index), name) for index, name in enumerate(NATURES))], "any")
        gender = t.dropdown([("any", "Any gender"), ("0", "Male"), ("1", "Female"),
                             ("2", "Genderless")], "any")
        ability = t.field(hint="Any ability ID", mono=True)
        selected = self.context()
        version = t.dropdown([("any", "Any game"), ("scarlet", "Scarlet"),
                              ("violet", "Violet")], selected["version"])
        map_name = t.dropdown([("any", "Any region"), ("paldea", "Paldea"),
                               ("kitakami", "Kitakami"), ("blueberry", "Blueberry")],
                              selected["map_name"])
        story = t.dropdown([("any", "Any progress"), ("beginning", "Beginning"),
                            ("tera", "Tera unlocked"), ("3star", "3-star unlocked"),
                            ("4star", "4-star unlocked"), ("5star", "5-star unlocked"),
                            ("6star", "6-star unlocked")], selected["progress"])
        content = t.dropdown([("any", "Standard or black"), ("standard", "Standard"),
                              ("black", "Black crystal")], "any")
        ivs = [t.field(hint="0-31", mono=True, width=66) for _ in STAT_LABELS]
        start = t.field(value=self.seed.value if _seed(self.seed.value) is not None else "00000000",
                        mono=True)
        count = t.field(value="100000", mono=True, keyboard_type=ft.KeyboardType.NUMBER)
        hits = t.field(value="12", mono=True, keyboard_type=ft.KeyboardType.NUMBER)
        status = t.text("", 12, t.MUTED)
        results = ft.ListView(spacing=8, height=300)
        run = t.button("Search seeds", None, "search")
        stop = t.secondary_button("Cancel search", None)
        stop.disabled = True
        cancellation = threading.Event()
        closed = threading.Event()

        def close(_=None):
            cancellation.set()
            closed.set()
            self.app.page.pop_dialog()

        def render(found):
            if closed.is_set():
                return
            results.controls = [ft.Column([
                encounter_card(self.app, row, compact=True, on_use=self._choose),
                t.text(f"Rank score: {row.score}", 10, t.FAINT),
            ], spacing=2) for row in found]
            stopped = cancellation.is_set()
            status.value = (f"Search stopped with {len(found)} matching candidates."
                            if stopped else
                            f"Found {len(found)} best candidates. Lower scores are easier except for highest stats.")
            run.disabled = False
            stop.disabled = True
            results.update()
            status.update()
            run.update()
            stop.update()

        def submit(_):
            parsed = _seed(start.value)
            try:
                amount = int(count.value)
                result_limit = int(hits.value)
            except ValueError:
                amount, result_limit = 0, 0
            if parsed is None or not 1 <= amount <= 1_000_000 or not 1 <= result_limit <= 100:
                status.value = ("Use an eight-digit starting seed, a search size from 1 to "
                                "1,000,000, and a result count from 1 to 100.")
                status.color = t.RED
                status.update()
                return
            try:
                chosen_contexts = context_combinations(
                    version=version.value, map_name=map_name.value,
                    progress=story.value, content=content.value)
                combinations = amount * len(chosen_contexts)
                if combinations > MAX_SEARCH_WORK:
                    raise ValueError(f"This scope covers {combinations:,} seed/context combinations. "
                                     f"Reduce the seed count below {MAX_SEARCH_WORK // len(chosen_contexts):,}.")
                iv_ranges = tuple(_iv_range(field.value) for field in ivs)
                ability_id = None if not ability.value.strip() else int(ability.value)
                if ability_id is not None and ability_id < 0:
                    raise ValueError("Ability ID cannot be negative.")
            except ValueError as exc:
                status.value, status.color = str(exc), t.RED
                status.update()
                return
            cancellation.clear()
            status.color = t.MUTED
            status.value = f"Searching 0 / {combinations:,} seed/context combinations…"
            results.controls = []
            run.disabled = True
            stop.disabled = False
            status.update()
            results.update()
            run.update()
            stop.update()

            def progress(done, total):
                self.app.ui(lambda: (setattr(
                                         status, "value",
                                         f"Searching {done:,} / {total:,} seed/context combinations…"),
                                     status.update()))

            def work():
                try:
                    species_filter = "" if species.value in (None, "-") else species.value
                    found = search(parsed, amount, objective.value,
                                   stars=None if stars.value == "any" else int(stars.value),
                                   shiny=None if shiny.value == "any" else shiny.value == "yes",
                                   contexts=chosen_contexts, species=species_filter,
                                   tera_type=None if tera.value == "any" else int(tera.value),
                                   nature=None if nature.value == "any" else int(nature.value),
                                   gender=None if gender.value == "any" else int(gender.value),
                                   ability=ability_id, iv_ranges=iv_ranges,
                                   unique_species=not species_filter, limit=result_limit,
                                   progress=progress, cancelled=cancellation.is_set)
                    self.app.ui(lambda: render(found))
                except Exception as exc:
                    def failed():
                        if closed.is_set():
                            return
                        status.value, status.color, run.disabled = str(exc), t.RED, False
                        status.update()
                        run.update()
                    self.app.ui(failed)
            threading.Thread(target=work, daemon=True).start()

        run.on_click = submit
        stop.on_click = lambda _: (cancellation.set(), setattr(status, "value", "Stopping search…"),
                                   status.update())
        context = (f"{selected['version'].title()} · {selected['map_name'].title()} · "
                   f"{selected['progress']} story progress · {selected['content']} raids")
        self.app.page.show_dialog(t.dialog(
            title=t.text("Find a Tera Raid seed", 17, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Column([
                t.text(f"Host context: {context}. Difficulty is an estimate based on generated stats.",
                       12, t.MUTED),
                t.text("Search context (the current host selections are the template; choose Any to broaden it)",
                       12, t.MUTED, weight=ft.FontWeight.W_600),
                ft.Row([version, map_name, story, content], spacing=8),
                ft.Row([t.labeled_control("Species", species, expand=True),
                        t.labeled_control("Tera type", tera, expand=True),
                        t.labeled_control("Nature", nature, expand=True)], spacing=8),
                ft.Row([t.labeled_control("Rank by", objective, expand=True),
                        t.labeled_control("Star level", stars, expand=True),
                        t.labeled_control("Shininess", shiny, expand=True)], spacing=8),
                ft.Row([t.labeled_control("Gender", gender, expand=True),
                        t.labeled_control("Ability", ability, expand=True)], spacing=8),
                t.text("IV filters — leave blank for Any; enter an exact value or range", 11, t.MUTED),
                ft.Row([t.labeled_control(label, field) for label, field in zip(STAT_LABELS, ivs)],
                       spacing=6),
                ft.Row([t.labeled_control("Starting seed", start, expand=True),
                        t.labeled_control("Seeds to scan", count, expand=True),
                        t.labeled_control("Results to show", hits, expand=True)], spacing=8),
                status, results,
            ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO), width=860, height=580),
            actions=[t.secondary_button("Close", close), stop, run],
        ))

"""Seed preview and local encounter finder for the Scarlet/Violet raid host."""

from __future__ import annotations

import re
import threading

import flet as ft

from gui import theme as t
from gui.views.sprites import MINI, SIZE, Sprite
from pokeldn.sv.raid_search import OBJECTIVES, VALIDATED_CONTEXT, candidate, search


TERA_TYPES = ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost",
              "Steel", "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon",
              "Dark", "Fairy")
STAT_LABELS = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")


def _seed(text: str) -> int | None:
    return int(text, 16) if re.fullmatch(r"[0-9A-Fa-f]{8}", text or "") else None


def _tera(found) -> str:
    return TERA_TYPES[found.tera_type] if 0 <= found.tera_type < len(TERA_TYPES) else str(found.tera_type)


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
    detail = ft.Column([headline, facts, stats], spacing=6 if compact else 9, expand=True)
    controls = [Sprite(app, found.species, found.shiny, size=MINI if compact else SIZE).control,
                detail]
    if on_use:
        controls.append(t.secondary_button("Use", lambda _e: on_use(found)))
    return ft.Container(ft.Row(controls, spacing=10 if compact else 14,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=10 if compact else 12, bgcolor=t.FIELD, border_radius=12)


class RaidSeedPicker:
    """An eight-digit seed field with decoded preview and a ranked local search."""

    def __init__(self, app, value: str, on_change):
        self.app, self.on_change = app, on_change
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
                self.preview.content = encounter_card(self.app, candidate(parsed))
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
        self.on_change(value)
        self._preview(value, update=False)
        self.app.page.pop_dialog()
        self.control.update()

    def _open(self, _event) -> None:
        objective = t.dropdown([(key, label) for key, (label, _minimize) in OBJECTIVES.items()],
                               "overall")
        stars = t.dropdown([("any", "Any (1–4 stars)"), ("1", "1 star"), ("2", "2 stars"),
                            ("3", "3 stars"), ("4", "4 stars")], "any")
        shiny = t.dropdown([("any", "Any"), ("yes", "Shiny only"), ("no", "Not shiny")], "any")
        start = t.field(value=self.seed.value if _seed(self.seed.value) is not None else "00000000",
                        mono=True)
        count = t.field(value="100000", mono=True, keyboard_type=ft.KeyboardType.NUMBER)
        status = t.text("", 12, t.MUTED)
        results = ft.ListView(spacing=8, height=360)
        run = t.button("Search seeds", None, "search")

        def close(_=None):
            self.app.page.pop_dialog()

        def render(found):
            results.controls = [ft.Column([
                encounter_card(self.app, row, compact=True, on_use=self._choose),
                t.text(f"Rank score: {row.score}", 10, t.FAINT),
            ], spacing=2) for row in found]
            status.value = f"Found {len(found)} best candidates. Lower scores are easier except for highest stats."
            run.disabled = False
            results.update()
            status.update()
            run.update()

        def submit(_):
            parsed = _seed(start.value)
            try:
                amount = int(count.value)
            except ValueError:
                amount = 0
            if parsed is None or not 1 <= amount <= 1_000_000:
                status.value = "Use an eight-digit starting seed and a search size from 1 to 1,000,000."
                status.color = t.RED
                status.update()
                return
            status.color = t.MUTED
            status.value = f"Searching 0 / {amount:,} seeds…"
            results.controls = []
            run.disabled = True
            status.update()
            results.update()
            run.update()

            def progress(done, total):
                self.app.ui(lambda: (setattr(status, "value", f"Searching {done:,} / {total:,} seeds…"),
                                     status.update()))

            def work():
                try:
                    found = search(parsed, amount, objective.value,
                                   stars=None if stars.value == "any" else int(stars.value),
                                   shiny=None if shiny.value == "any" else shiny.value == "yes",
                                   progress=progress)
                    self.app.ui(lambda: render(found))
                except Exception as exc:
                    def failed():
                        status.value, status.color, run.disabled = str(exc), t.RED, False
                        status.update()
                        run.update()
                    self.app.ui(failed)
            threading.Thread(target=work, daemon=True).start()

        run.on_click = submit
        context = (f"{VALIDATED_CONTEXT['version'].title()} · {VALIDATED_CONTEXT['map_name'].title()} · "
                   "4-star story progress · standard raids")
        self.app.page.show_dialog(t.dialog(
            title=t.text("Find a Tera Raid seed", 17, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Column([
                t.text(f"Validated host context: {context}. Difficulty is an estimate based on generated stats.",
                       12, t.MUTED),
                ft.Row([t.labeled_control("Rank by", objective, expand=True),
                        t.labeled_control("Star level", stars, expand=True),
                        t.labeled_control("Shininess", shiny, expand=True)], spacing=8),
                ft.Row([t.labeled_control("Starting seed", start, expand=True),
                        t.labeled_control("Seeds to scan", count, expand=True)], spacing=8),
                status, results,
            ], spacing=10, tight=True), width=680),
            actions=[t.secondary_button("Close", close), run],
        ))

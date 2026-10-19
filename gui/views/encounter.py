"""The Union Circle - Encounters card: the wild Pokemon pokeldn spawns in the host's world, crafted from
what a shared spawn's record carries (docs/sv_union_circle.md, Crafted encounters). With Legal encounters
only, the species, level and Tera Type keep to what PKHeX's wild slots give, and the card lists every
location where PKHeX accepts the spawn caught. The value is a dict (pokeldn.app.command.encounter_args)."""
import threading

import flet as ft

from gui import theme as t
from gui.localization import SERVICE, error_message
from gui.views.pokemon import STATS, NamePicker, pokemon_header
from gui.views.sprites import Sprite
from gui.views.widgets import PixelActivity
from pokeldn.app.i18n import t as tr
from pokeldn.sv import wild

RANDOM = "-"
MALE, FEMALE = 0, 1
MALE_ONLY, FEMALE_ONLY, GENDERLESS = 0, 254, 255


def genders(ratio: int) -> list[int]:
    """-> the record's sex values a species with gender `ratio` takes."""
    return [FEMALE] if ratio == FEMALE_ONLY else [MALE] if ratio in (MALE_ONLY, GENDERLESS) else [MALE, FEMALE]


class EncounterPicker:
    """`view` is the GamesView holding the values; `field` the encounter field."""

    def __init__(self, view, field):
        self.view, self.app, self.field = view, view.app, field
        stored = view.values.get(field.key)
        self.value = dict(stored) if isinstance(stored, dict) else {"legal": True, "level": 1}
        self.table = None           # wild.Table once read
        self.species_names = []     # [{"id", "name"}] of every Scarlet / Violet species
        self.info = None            # wild.species of the chosen species and form
        self.scanned = None         # wild.scan of the spawn as last checked
        self.check_token = 0
        self.sprite = Sprite(self.app, int(self.value.get("species") or 0), bool(self.value.get("shiny")),
                             form=int(self.value.get("form") or 0))
        self.legal = t.switch(bool(self.value.get("legal")), self._legal)
        self.species = t.dropdown([], None, on_select=self._species, enable_filter=True, editable=True,
                                  menu_height=320, hint_text=tr('encounter.loading_species_ef998d', 'Loading species...'),
                                  disabled=True)
        self.species.trailing_icon = PixelActivity(tr('encounter.loading_species_90a6a5', 'Loading species'))
        self.shiny = t.switch(bool(self.value.get("shiny")), self._shiny)
        self.details = ft.Column(spacing=10)
        self.places = ft.Column(spacing=4)
        top = ft.Row([t.labeled_control(tr('encounter.species_56205e', 'Species'), self.species, expand=True),
                      t.labeled_control(tr('encounter.shiny_039a0a', 'Shiny'), ft.Container(
                          self.shiny, width=64, height=t.CONTROL_HEIGHT, alignment=ft.Alignment.CENTER))],
                     spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)
        self.control = ft.Column([
            ft.Row([t.text(tr('encounter.legal_encounters_only_6d37c0', 'Legal encounters only'), 13, expand=True), self.legal],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            t.text(tr('encounter.offers_only_what_the_game_s_own_wild_pokemon_can_be_and_456583',
                      "Offers only what the game's own wild Pokemon can be, and spawns it only while you stand "
                      "where PKHeX finds it legal once caught."), 12, t.MUTED),
            pokemon_header(self.sprite.control, [top, self.details]),
            self.places,
        ], spacing=10)
        threading.Thread(target=self._load, daemon=True).start()

    # Values

    def _save(self, redraw: bool = True) -> None:
        self.view.values[self.field.key] = dict(self.value)
        self.app.settings.save()
        self.view.session.refresh()
        if redraw:
            self._draw()
            self.control.update()

    def _number(self, key: str) -> int:
        return int(self.value.get(key) or 0)

    def _fit(self) -> None:
        """Keeps the value within what the species takes and, with Legal encounters only, what its wild slots
        give."""
        info, species, form = self.info, self._number("species"), self._number("form")
        if info is None:
            return
        if all(f["id"] != form for f in info["forms"]):
            self.value["form"] = form = info["forms"][0]["id"] if info["forms"] else 0
        if self.value.get("gender") not in genders(info["gender"]):
            self.value["gender"] = genders(info["gender"])[0]
        if self.value.get("tera") is None:
            self.value["tera"] = info["types"][0]
        if not self.value.get("legal") or self.table is None:
            return
        levels = self.table.levels(species, form)
        if levels and self._number("level") not in levels:
            level = self._number("level")
            self.value["level"] = min(levels, key=lambda n: (abs(n - level), n))

    def forms(self) -> list[dict]:
        """-> the species' forms to offer: with Legal encounters only, those a wild slot gives."""
        forms = self.info["forms"] if self.info else []
        if self.value.get("legal") and self.table is not None:
            species = self._number("species")
            forms = [f for f in forms if self.table.levels(species, f["id"])]
        return forms

    def teras(self) -> list[int]:
        """-> the Tera Types to offer: with Legal encounters only, every one PKHeX accepts the spawn caught
        with somewhere, once checked."""
        if self.value.get("legal") and self.scanned:
            found = sorted({tera for place in self.scanned for tera in place["teras"]})
            if found:
                return found
        return list(range(len(self.table.types))) if self.table else []

    # Loading

    def _load(self) -> None:
        try:
            self.table = wild.areas(SERVICE)
            self.species_names = SERVICE.species("sv")
            error = ""
        except Exception as exc:
            error = error_message(exc)

        def show():
            self.species.trailing_icon = t.pixel_icon("chevron-down", color=t.MUTED)
            if error:
                self.species.hint_text = tr('encounter.unavailable_ca1844', 'Unavailable')
                self.places.controls = [t.text(error, 12, t.RED)]
                self.control.update()
                return
            self.species.disabled = False
            self.species.hint_text = tr('encounter.search_a_species_1ea995', 'Search a species')
            self._fill_species()
            self._load_species()
        self.app.ui(show)

    def _fill_species(self) -> None:
        names = self.species_names
        if self.value.get("legal") and self.table is not None:
            found = {slot.species for area in self.table.areas for slot in area.slots}
            names = [n for n in names if n["id"] in found]
        self.species.options = [ft.DropdownOption(key=str(n["id"]), text=n["name"]) for n in names]
        chosen = str(self.value.get("species") or "")
        self.species.value = chosen if any(o.key == chosen for o in self.species.options) else None

    def _load_species(self) -> None:
        species, form = self._number("species"), self._number("form")
        if not species:
            self.info = None
            self._draw()
            self.control.update()
            return

        def work():
            try:
                info, error = wild.species(SERVICE, species, form), ""
            except Exception as exc:
                info, error = None, error_message(exc)

            def show():
                if (species, form) != (self._number("species"), self._number("form")):
                    return
                self.info = info
                offered = self.forms()
                if info and offered and all(f["id"] != form for f in offered):
                    self.value["form"] = offered[0]["id"]      # its own types and abilities
                    self._load_species()
                    return
                if error:
                    self.places.controls = [t.text(error, 12, t.RED)]
                self._fit()
                self._save()
                self._check()
            self.app.ui(show)
        threading.Thread(target=work, daemon=True).start()

    def _check(self) -> None:
        """Asks PKHeX where the spawn is legal, with Legal encounters only."""
        self.check_token += 1
        token = self.check_token
        if not self.value.get("legal") or self.table is None or self.info is None or not self.forms():
            self.scanned = None
            self._draw_places()
            self.places.update()
            return
        self.places.controls = [ft.Row([PixelActivity(tr('encounter.checking_0dfe1d', 'Checking')),
                                        t.text(tr('encounter.pkhex_is_checking_where_this_pokemon_is_legal_5a24ff', 'PKHeX is checking where this Pokemon is legal...'),
                                               12, t.MUTED)], spacing=8)]
        self.places.update()
        spawn = self.spawn()

        def work():
            try:
                found, error = wild.scan(SERVICE, spawn), ""
            except Exception as exc:
                found, error = None, error_message(exc)

            def show():
                if token != self.check_token:
                    return
                before = self.teras()
                self.scanned = found
                offered = self.teras()
                if self._number("tera") not in offered:
                    self.value["tera"] = offered[0]
                    self._save(redraw=False)
                if offered != before:       # a redraw would take the focus from a field being typed in
                    self._draw()
                self._draw_places(error)
                self.control.update()
            self.app.ui(show)
        threading.Thread(target=work, daemon=True).start()

    def spawn(self) -> dict:
        """-> the value as wild.scan takes it."""
        ivs = self.value.get("ivs") or ""
        parts = ivs.split("/") if ivs else []
        return {"species": self._number("species"), "form": self._number("form"), "level": self._number("level"),
                "tera": self._number("tera"), "shiny": bool(self.value.get("shiny")),
                "nature": self.value.get("nature"), "gender": self.value.get("gender"),
                "scale": self.value.get("scale"), "ability": self.value.get("ability"),
                "item": self.value.get("item") or None,
                # PKHeX's order (HP Atk Def Spe SpA SpD) from the card's (HP Atk Def SpA SpD Spe)
                "ivs": [int(parts[i]) for i in (0, 1, 2, 5, 3, 4)] if len(parts) == 6 else None}

    # Drawing

    def _draw(self) -> None:
        info = self.info
        self.sprite.show(self._number("species"), bool(self.value.get("shiny")), update=False,
                         form=self._number("form"))
        if info is None:
            self.details.controls = [t.text(tr('encounter.pick_a_species_981ca3', 'Pick a species.'), 12, t.MUTED)]
            return
        species, form = self._number("species"), self._number("form")
        legal = bool(self.value.get("legal")) and self.table is not None
        if legal and not self.forms():
            self.details.controls = [t.text(tr('encounter.no_wild_slot_gives_this_species_pick_another_or_turn_of_06cce5', 'No wild slot gives this species: pick another, or '
                                                                       'turn off Legal encounters only.'), 12, t.RED)]
            return
        first = []
        if len(self.forms()) > 1:
            first.append(self._choice(tr('encounter.form_2e0e96', 'Form'), "form",
                                      [(str(f["id"]), f["name"]) for f in self.forms()], reload=True))
        if legal:
            levels = self.table.levels(species, form)
            first.append(self._choice(tr('encounter.level_170930', 'Level'), "level", [(str(n), str(n)) for n in levels]))
        else:
            first.append(self._entry(tr('encounter.level_170930', 'Level'), "level", 1, 100, width=90))
        teras = self.teras()
        first.append(self._choice(tr('encounter.tera_type_f65f71', 'Tera Type'), "tera", [(str(n), self.table.types[n]) for n in teras]))
        second = [self._choice(tr('encounter.nature_c71ce8', 'Nature'), "nature",
                               [(str(n["id"]), n["name"]) for n in info["natures"]], random=True)]
        if len(genders(info["gender"])) > 1:
            second.append(self._choice(tr('encounter.gender_a04630', 'Gender'), "gender",
                                       [(str(MALE), tr('encounter.male_03f8c1', 'Male')), (str(FEMALE), tr('encounter.female_e8cca8', 'Female'))]))
        abilities = info["abilities"]
        second.append(self._choice(tr('encounter.ability_9c40ae', 'Ability'), "ability", [
            (str(a["slot"]), a["name"] + (tr('encounter.hidden_b8bab1', ' (hidden)') if a["slot"] == 2 else ""))
            for a in abilities], random=True))
        third = [t.labeled_control(tr('encounter.held_item_6af4a4', 'Held item'), NamePicker(
                     self.app, "sv", "item", str(self.value.get("item") or ""), self._item).control, expand=True),
                 self._entry(tr('encounter.scale_0_255_e4b57a', 'Scale (0-255)'), "scale", 0, 255, width=130, empty=True)]
        self.details.controls = [ft.Row(first, spacing=10), ft.Row(second, spacing=10), ft.Row(third, spacing=10),
                                 self._ivs(),
                                 t.text(tr('encounter.empty_means_random_each_iv_0_to_31_as_the_game_draws_a__3e6ed1', 'Empty means random: each IV 0 to 31, as the '
                                                                     'game draws a wild one.'), 12, t.FAINT)]

    def _choice(self, label: str, key: str, options: list[tuple[str, str]], random: bool = False,
                reload: bool = False) -> ft.Control:
        current = self.value.get(key)

        def picked(e):
            self.value[key] = None if e.control.value == RANDOM else int(e.control.value)
            if reload:
                self._load_species()
                return
            self._fit()
            self._save()
            self._check()
        if random:
            options = [(RANDOM, tr('encounter.random_67bc48', 'Random'))] + options
        return t.labeled_control(label, t.dropdown(options, RANDOM if current is None else str(current),
                                                   on_select=picked, menu_height=320), expand=True)

    def _entry(self, label: str, key: str, low: int, high: int, width: int, empty: bool = False) -> ft.Control:
        current = self.value.get(key)

        def changed(e):
            raw = e.control.value.strip()
            good = raw.isdigit() and low <= int(raw) <= high
            if good:
                self.value[key] = int(raw)
            elif empty and not raw:
                self.value[key] = None
            t.mark_invalid(e.control, not good and not (empty and not raw))
            e.control.update()
            self._save(redraw=False)
            self._check()
        return t.labeled_control(label, t.field(value="" if current is None else str(current), hint="-", mono=True,
                                                digits=True, limit=len(str(high)), width=width, on_change=changed))

    def _ivs(self) -> ft.Control:
        parts = (self.value.get("ivs") or "").split("/")
        parts = parts if len(parts) == 6 else [""] * 6
        boxes = []

        def changed(e, at):
            parts[at] = e.control.value.strip()
            good = parts[at].isdigit() and int(parts[at]) <= wild.IV_MAX
            t.mark_invalid(e.control, bool(parts[at]) and not good)
            e.control.update()
            whole = all(p.isdigit() and int(p) <= wild.IV_MAX for p in parts)
            self.value["ivs"] = "/".join(parts) if whole else None
            self._save(redraw=False)
            self._check()
        for at, (_, name) in enumerate(STATS):
            boxes.append(t.labeled_control(name, t.field(value=parts[at], hint="-", mono=True, digits=True, limit=2,
                                                         on_change=lambda e, at=at: changed(e, at)), expand=True))
        return ft.Column([t.text(tr('encounter.ivs_all_six_or_empty_227216', 'IVs (all six, or empty)'), 12, t.MUTED),
                          ft.Row(boxes, spacing=6)], spacing=4)

    def _draw_places(self, error: str = "") -> None:
        if error:
            self.places.controls = [t.text(error, 12, t.RED)]
            return
        if not self.value.get("legal") or self.scanned is None:
            self.places.controls = []
            return
        tera = self._number("tera")
        names = sorted(place["name"] or f"location {place['location']}" for place in self.scanned
                       if tera in place["teras"])
        if names:
            self.places.controls = [
                t.text(tr('encounter.pkhex_accepts_it_caught_at_count_location_s_91683c', 'PKHeX accepts it caught at {count} location(s):', count=len(names)),
                       12, t.MUTED),
                t.text(" · ".join(names), 13, t.TEXT)]
            return
        problems = sorted({p for place in self.scanned for p in place["problems"]})
        self.places.controls = [t.text(tr('encounter.pkhex_accepts_it_caught_nowhere_45f7f3', 'PKHeX accepts it caught nowhere.'), 12, t.RED),
                                *[t.text(p, 12, t.MUTED) for p in problems[:4]]]

    # Events

    def _legal(self, e) -> None:
        self.value["legal"] = bool(e.control.value)
        self._fill_species()
        self._load_species()

    def _species(self, e) -> None:
        """A new species starts over from a wild one: its first form, its lowest wild level with Legal
        encounters only, its first type as its Tera Type, and random or empty values below."""
        self.value["species"] = int(e.control.value)
        self.value["form"] = 0
        for key in ("tera", "nature", "gender", "ability", "scale", "item", "ivs"):
            self.value.pop(key, None)
        if self.value.get("legal"):
            self.value.pop("level", None)
        self.info = self.scanned = None
        self._save(redraw=False)
        self._load_species()

    def _item(self, value: str) -> None:
        self.value["item"] = int(value) if str(value).isdigit() else None
        self._save(redraw=False)
        self._check()

    def _shiny(self, e) -> None:
        self.value["shiny"] = bool(e.control.value)
        self.sprite.show(self._number("species"), self.value["shiny"], form=self._number("form"))
        self._save(redraw=False)
        self._check()

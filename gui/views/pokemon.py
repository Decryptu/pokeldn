import threading

import flet as ft

from pokeldn import pokemon as builder
from pokeldn.app.command import offers
from gui import theme as t
from gui.views.sprites import EDGE, SIZE as SPRITE_SIZE, Sprite
from gui.views.widgets import PixelActivity

VERSIONS = {"firered": "FR", "leafgreen": "LG"}
ROW_GAP = SPRITE_SIZE + 2 * EDGE - 2 * t.CONTROL_HEIGHT   # the species and nickname boxes and the gap match the tile


class PokemonPicker:
    """Pick a species and PKHeX builds a legal one for the game; or check a file someone brings."""

    def __init__(self, app, game: str, value: dict | None, on_change, version: str = ""):
        self.app, self.game, self.on_change, self.version = app, game, on_change, version
        self.value = dict(value or {})
        self.species = t.dropdown([], None, on_select=self._pick, enable_filter=True, editable=True,
                                  menu_height=320, hint_text="Loading species...", disabled=True)
        self.species.trailing_icon = PixelActivity("Loading species")
        self.level = t.field(value=str(self.value.get("level") or ""), hint="auto", mono=True, width=90,
                             on_change=lambda e: self._set("level", e.control.value))
        self.sprite = Sprite(app, int(self.value.get("species") or 0), bool(self.value.get("shiny")))
        self.shiny = t.switch(bool(self.value.get("shiny")), self._shiny)
        self.nickname = t.field(value=self.value.get("nickname", ""), hint="Nickname (optional)", expand=True,
                                on_change=lambda e: self._set("nickname", e.control.value))
        self.build_button = t.button("Build", self._build, "sparkles", disabled=True)
        self.options = OfferOptions(self)
        self.result = ft.Container()
        form = ft.Column([
            ft.Row([t.labeled_control("Species", self.species, expand=True),
                    t.labeled_control("Level", self.level),
                    t.labeled_control("Shiny", ft.Container(
                        self.shiny, width=64, height=t.CONTROL_HEIGHT,
                        alignment=ft.Alignment.CENTER))],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row([self.nickname, self.build_button], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=ROW_GAP, expand=True)
        # The tile runs from the top of the species box to the bottom of the nickname box, below the 20 px label.
        tile = ft.Container(self.sprite.control, margin=ft.Margin(0, 20, 0, 0))
        self.control = ft.Column([
            ft.Row([tile, form], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
            self.options.control,
            self.result,
            t.secondary_button("Or use a Pokemon file", self._use_file, "file"),
        ], spacing=10)
        self._show_result()
        threading.Thread(target=self._load_species, daemon=True).start()

    def _set(self, key, value) -> None:
        self.value[key] = value

    def _pick(self, e) -> None:
        self.value["species"] = int(e.control.value)
        self.sprite.show(self.value["species"], bool(self.value.get("shiny")))
        self.options.species_changed()

    def _shiny(self, e) -> None:
        self._set("shiny", e.control.value)
        self.sprite.show(int(self.value.get("species") or 0), bool(e.control.value))

    def _load_species(self) -> None:
        try:
            species = builder.SERVICE.species(self.game)
            error = ""
        except Exception as exc:
            species, error = [], str(exc)

        def show():
            self.species.trailing_icon = t.pixel_icon("chevron-down", color=t.MUTED)
            if error:
                self.species.hint_text = "Unavailable"
                self._message(error, t.RED)
            else:
                self.species.options = [ft.DropdownOption(key=str(s["id"]), text=s["name"]) for s in species]
                self.species.value = str(self.value["species"]) if self.value.get("species") else None
                self.species.hint_text = "Search a species"
                self.species.disabled = self.build_button.disabled = False
            self.control.update()
        self.app.ui(show)

    def _build(self, e) -> None:
        if not self.value.get("species"):
            self._message("Pick a species first.", t.RED)
            self.control.update()
            return
        if problem := self.options.problem():
            self._message(problem, t.RED)
            self.control.update()
            return
        self.build_button.disabled = True
        self._message("Finding a legal encounter...", t.MUTED, busy=True)
        self.control.update()
        try:
            level = int(self.value.get("level") or 0)
        except ValueError:
            level = 0

        def work():
            try:
                info = builder.SERVICE.make(self.game, self.value["species"], self.app.settings.trainer(),
                                            level, bool(self.value.get("shiny")),
                                            self.value.get("nickname", ""), VERSIONS.get(self.version, ""),
                                            self.value.get("options"))
                self.value.update(file=info["file"], summary=builder.summary(info), legal=info["legal"],
                                  encounter=info["encounter"], moves=info["moves"])
                self.on_change(dict(self.value))
                done = self._show_result
            except Exception as exc:
                message = str(exc)
                done = lambda: self._message(message, t.RED)   # noqa: E731
            self.app.ui(lambda: (done(), setattr(self.build_button, "disabled", False), self.control.update()))

        threading.Thread(target=work, daemon=True).start()

    async def _use_file(self, e) -> None:
        files = await self.app.picker.pick_files(
            allowed_extensions=[builder.EXTENSIONS[self.game], "bin", "hex", "ek3"],
            file_type=ft.FilePickerFileType.CUSTOM)
        if not files or not files[0].path:
            return
        path = files[0].path
        try:
            info = builder.SERVICE.import_file(self.game, path)
        except Exception as exc:
            self._message(f"Not a Pokemon this game can take: {exc}", t.RED)
            self.control.update()
            return
        self.value.update(file=info["file"], summary=builder.summary(info), legal=info["legal"],
                          encounter=info["encounter"], moves=info["moves"],
                          report="" if info["legal"] else info["report"],
                          species=info["species_id"], shiny=info["shiny"])
        if self.species.options:
            self.species.value = str(info["species_id"])
        self.shiny.value = info["shiny"]
        self.sprite.show(info["species_id"], info["shiny"], update=False)
        self.options.species_changed()
        self.on_change(dict(self.value))
        self._show_result()
        self.control.update()

    def _message(self, text: str, color: str, busy: bool = False) -> None:
        message = t.text(text, 12, color, selectable=True, expand=True if busy else None)
        self.result.content = (ft.Row([PixelActivity("Building Pokemon"), message], spacing=8)
                               if busy else message)

    def _show_result(self) -> None:
        if not self.value.get("file"):
            self.result.content = None
            return
        legal = self.value.get("legal", False)
        lines = [ft.Row([
            t.pixel_icon("shield" if legal else "warning-diamond",
                    color=t.GREEN if legal else t.RED),
            t.text(self.value.get("summary", ""), 13, weight=ft.FontWeight.W_600, expand=True),
            t.badge("Legal" if legal else "Not legal", t.GREEN if legal else t.RED,
                    "check" if legal else "warning-diamond"),
        ], spacing=8)]
        detail = " · ".join(x for x in (self.value.get("encounter", ""), ", ".join(self.value.get("moves", []))) if x)
        if detail:
            lines.append(t.text(detail, 12, t.MUTED))
        if self.value.get("report"):
            lines.append(t.text(self.value["report"], 11.5, t.RED, selectable=True))
        self.result.content = ft.Container(ft.Column(lines, spacing=4), bgcolor=t.BG, border_radius=10, padding=10)


class OfferQueue:
    """The Pokemon one session trades, in order: one picker per trade, up to `limit`."""

    def __init__(self, app, game: str, value, limit: int, on_change, version: str = ""):
        self.app, self.game, self.limit, self.on_change, self.version = app, game, limit, on_change, version
        self.slots: list[dict] = []
        self.rows = ft.Column(spacing=10)
        self.add_button = t.secondary_button("Add a trade", self._add, "plus")
        self.count = t.text("", 12, t.MUTED)
        self.control = ft.Column([self.rows, ft.Row([self.add_button, self.count], spacing=12)], spacing=12)
        for entry in (offers(value)[:limit] or [{}]):
            self._slot(entry)
        self._render()

    def _slot(self, entry: dict) -> None:
        slot = {"value": dict(entry), "title": t.text("", 12.5, weight=ft.FontWeight.W_600, expand=True)}
        slot["picker"] = PokemonPicker(self.app, self.game, entry, lambda v, s=slot: self._changed(s, v),
                                       version=self.version)
        slot["remove"] = t.icon_button("close", lambda e, s=slot: self._remove(s), "Remove this trade")
        slot["header"] = ft.Row([slot["title"], slot["remove"]], spacing=8)
        slot["box"] = ft.Container(ft.Column([slot["header"], slot["picker"].control], spacing=8))
        self.slots.append(slot)

    def _render(self) -> None:
        several = len(self.slots) > 1
        for n, slot in enumerate(self.slots, start=1):
            slot["title"].value = f"Trade {n}"
            slot["header"].visible = several
            slot["box"].border = ft.Border.all(1, t.BORDER) if several else None
            slot["box"].border_radius = 12 if several else None
            slot["box"].padding = ft.Padding(12, 6, 6, 12) if several else None
        self.rows.controls = [slot["box"] for slot in self.slots]
        self.add_button.disabled = len(self.slots) >= self.limit
        self.count.value = (f"{len(self.slots)} of {self.limit}, traded in this order" if several
                            else f"Up to {self.limit} Pokemon in one session")

    def _save(self) -> None:
        self.on_change([dict(slot["value"]) for slot in self.slots])

    def _changed(self, slot: dict, value: dict) -> None:
        slot["value"] = value
        self._save()

    def _add(self, e) -> None:
        if len(self.slots) >= self.limit:
            return
        self._slot({})
        self._render()
        self._save()
        self.control.update()

    def _remove(self, slot: dict) -> None:
        if len(self.slots) > 1:
            self.slots.remove(slot)
            self._render()
            self._save()
            self.control.update()


STATS = (("hp", "HP"), ("atk", "Atk"), ("def", "Def"), ("spa", "SpA"), ("spd", "SpD"), ("spe", "Spe"))
EFFORT = {"evs": "EVs", "avs": "AVs", "gvs": "Effort levels"}
GENDERS = (("0", "Male"), ("1", "Female"))
ANY = "-"


class OfferOptions:
    """Nature, ability, gender, held item, ball, IVs and effort for the built Pokemon, folded under the form.

    The choices offered are the ones PKHeX permits for the species (services/pkhex Options); the build is
    still checked for legality as a whole."""

    def __init__(self, picker: "PokemonPicker"):
        self.picker = picker
        self.chosen: dict = picker.value.setdefault("options", {})
        self.open = False
        self.loaded_for = None
        self.total = None    # the game's cap on all six effort values together, once the options are read
        self.body = ft.Column([], spacing=10, visible=False)
        self.chevron = t.pixel_icon("chevron-right", color=t.FAINT)
        self.label = t.text("", 12, t.MUTED)
        header = ft.Container(ft.Row([self.chevron, t.text("More options", 12.5, t.TEXT, weight=ft.FontWeight.W_600),
                                      self.label], spacing=8),
                              padding=ft.Padding(2, 4, 2, 4), border_radius=8, on_click=self._toggle)
        self.control = ft.Column([header, self.body], spacing=8)
        self._label()

    def _label(self) -> None:
        count = sum(1 for k, v in self.chosen.items() if (v if isinstance(v, dict) else v is not None))
        self.label.value = f"{count} set" if count else "random"

    def _toggle(self, e) -> None:
        self.open = not self.open
        self.chevron.src = f"icons/chevron-{'down' if self.open else 'right'}.svg"
        self.body.visible = self.open
        if self.open:
            self._load()
        self.control.update()

    def species_changed(self) -> None:
        self.loaded_for = None
        if self.open:
            self._load()
            self.control.update()

    def _load(self) -> None:
        species = int(self.picker.value.get("species") or 0)
        if not species:
            self.body.controls = [t.text("Pick a species first.", 12, t.MUTED)]
            return
        if self.loaded_for == species:
            return
        self.loaded_for = species
        self.body.controls = [ft.Row([PixelActivity("Loading options"),
                                      t.text("Reading what this species can have...", 12, t.MUTED)], spacing=8)]
        app = self.picker.app

        def work():
            try:
                found, error = builder.SERVICE.options(self.picker.game, species, app.settings.trainer(),
                                                       VERSIONS.get(self.picker.version, "")), ""
            except Exception as exc:
                found, error = None, str(exc)

            def show():
                if self.loaded_for != species:
                    return
                self.body.controls = [t.text(error, 12, t.RED)] if error else self._form(found)
                self._label()
                self.control.update()
            app.ui(show)
        threading.Thread(target=work, daemon=True).start()

    def _form(self, found: dict) -> list[ft.Control]:
        # A choice the new species cannot have is dropped rather than sent.
        for key, names in (("ability", found["abilities"]), ("ball", found["balls"]), ("held_item", found["held"])):
            if self.chosen.get(key) is not None and all(n["id"] != self.chosen[key] for n in names):
                self.chosen.pop(key)
        if not found["gendered"]:
            self.chosen.pop("gender", None)
        first = [t.labeled_control("Nature", self._choice("nature", found["natures"]), expand=True)]
        if len(found["abilities"]) > 1:
            first.append(t.labeled_control("Ability", self._choice("ability", found["abilities"]), expand=True))
        if found["gendered"]:
            first.append(t.labeled_control("Gender", self._choice(
                "gender", [{"id": int(k), "name": n} for k, n in GENDERS]), expand=True))
        second = [t.labeled_control("Ball", self._choice("ball", found["balls"]), expand=True)]
        if found["held"]:
            second.insert(0, t.labeled_control("Held item", self._choice("held_item", found["held"], search=True),
                                               expand=True))
        effort = found["effort"]
        self.total = effort.get("total")
        limit = f"0-{effort['max']}" + (f", {effort['total']} in all" if effort.get("total") else "")
        return [
            ft.Row(first, spacing=10),
            ft.Row(second, spacing=10),
            self._stats("ivs", "IVs", 31, "0-31"),
            self._stats("effort", EFFORT[effort["kind"]], effort["max"], limit, effort.get("total")),
            ft.Row([t.text("Empty means random. The build is checked by PKHeX's legality analysis.", 11.5, t.FAINT,
                           expand=True),
                    t.link_button("Clear", self._clear)]),
        ]

    def _choice(self, key: str, names: list[dict], search: bool = False) -> ft.Dropdown:
        current = self.chosen.get(key)

        def picked(e):
            if e.control.value == ANY:
                self.chosen.pop(key, None)
            else:
                self.chosen[key] = int(e.control.value)
            self._label()
            self.label.update()
        options = [(ANY, "Random")] + [(str(n["id"]), n["name"]) for n in
                                       (sorted(names, key=lambda n: n["name"]) if search else names)]
        return t.dropdown(options, ANY if current is None else str(current), on_select=picked,
                          enable_filter=search, editable=search, menu_height=320)

    def _stats(self, group: str, title: str, top: int, limit: str, total: int | None = None) -> ft.Control:
        values = self.chosen.setdefault(group, {})
        boxes = []

        def changed(e, stat):
            raw = e.control.value.strip()
            if not raw:
                values.pop(stat, None)
                e.control.error = None
            elif raw.isdigit() and int(raw) <= top:
                values[stat] = int(raw)
                e.control.error = None
            else:
                values.pop(stat, None)
                e.control.error = ""
            if not values:
                self.chosen.pop(group, None)
            else:
                self.chosen[group] = values
            self._label()
            self.control.update()

        for stat, name in STATS:
            box = t.field(value=str(values.get(stat, "")), hint="-", mono=True, expand=True,
                          on_change=lambda e, stat=stat: changed(e, stat))
            boxes.append(t.labeled_control(name, box, expand=True))
        if not values:
            self.chosen.pop(group, None)
        return ft.Column([t.text(f"{title} ({limit})", 11.5, t.MUTED), ft.Row(boxes, spacing=6)], spacing=4)

    def _clear(self, e) -> None:
        self.chosen.clear()
        species, self.loaded_for = self.loaded_for, None
        if species:
            self._load()
        self._label()
        self.control.update()

    def problem(self) -> str:
        """Why the options cannot be sent as they stand, or an empty string."""
        if self.total and sum(self.chosen.get("effort", {}).values()) > self.total:
            return f"EVs add up to at most {self.total}."
        return ""


NAME_LISTS = {"species": "species", "move": "moves", "item": "items", "ball": "balls"}
EMPTY = "-"


class NamePicker:
    """A searchable list of the species, moves, items or balls a game has, by name; the value is the id."""

    def __init__(self, app, game: str, kind: str, value: str, on_change, optional: bool = True):
        self.app, self.game, self.kind, self.optional = app, game, NAME_LISTS[kind], optional
        self.dropdown = t.dropdown([], None, on_select=lambda e: on_change("" if e.control.value == EMPTY
                                                                           else e.control.value),
                                   enable_filter=True, editable=True, menu_height=320,
                                   hint_text="Loading...", disabled=True)
        self.value = value
        self.dropdown.trailing_icon = PixelActivity("Loading names")
        self.control = self.dropdown
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            names = builder.SERVICE.names(self.game, self.kind)
        except Exception:
            names = None

        def show():
            self.dropdown.trailing_icon = t.pixel_icon("chevron-down", color=t.MUTED)
            if names is None:
                self.dropdown.hint_text = "Unavailable"
            else:
                options = [ft.DropdownOption(key=str(n["id"]), text=n["name"]) for n in names]
                if self.optional:
                    options.insert(0, ft.DropdownOption(key=EMPTY, text="Not set"))
                self.dropdown.options = options
                self.dropdown.value = str(self.value) if self.value else (EMPTY if self.optional else None)
                self.dropdown.hint_text = "Search"
                self.dropdown.disabled = False
            self.dropdown.update()
        self.app.ui(show)

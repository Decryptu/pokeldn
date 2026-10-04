import threading
from pathlib import Path

import flet as ft

from pokeldn import pokemon as builder
from pokeldn.app.command import offers
from pokeldn.lgpe.session import CODE_PICKER, code_picks
from gui import drop, theme as t
from gui.views.sprites import EDGE, MINI, SIZE as SPRITE_SIZE, Sprite
from gui.views.widgets import PixelActivity

VERSIONS = {"firered": "FR", "leafgreen": "LG"}
ROW_GAP = SPRITE_SIZE + 2 * EDGE - 2 * t.CONTROL_HEIGHT   # the species and nickname boxes and the gap match the tile


class PokemonPicker:
    """Pick a species and PKHeX builds a legal one for the game; or check a file someone brings."""

    def __init__(self, app, game: str, value: dict | None, on_change, version: str = "", on_team=None,
                 on_more=None, glow=None):
        """`on_team(sets)` places the sets after the first of a pasted team and says where they went;
        `on_more(paths)` places the files dropped with the first. `glow()` is what lights under a drag."""
        self.app, self.game, self.on_change, self.version = app, game, on_change, version
        self.on_team, self.on_more = on_team, on_more
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
        self.build_button = t.button("Build", self._build, disabled=True)
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
        self.body = ft.Container(ft.Column([
            ft.Row([tile, form], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
            self.options.control,
            self.result,
            ft.Row([t.secondary_button("Or use a Pokemon file", self._use_file, "file"),
                    t.secondary_button("Import paste", self._paste, "bulletlist"),
                    *([t.text("or drop either here", 12, t.FAINT)] if drop.AVAILABLE else [])],
                   spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=10), border_radius=12)
        self.control = drop.target(self.body, self._dropped, glow=glow or self.body)
        self._show_result()
        threading.Thread(target=self._load_species, daemon=True).start()

    def _set(self, key, value) -> None:
        self.value[key] = value

    def _pick(self, e) -> None:
        self.value["species"] = int(e.control.value)
        # A form or moveset chosen for the previous species rarely fits this one.
        self.options.chosen.pop("form", None)
        self.options.chosen.pop("moves", None)
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
                info = builder.SERVICE.make(self.game, self.value["species"], self.app.settings.trainer(self.game),
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
        if files and files[0].path:
            self.load(files[0].path)

    def _dropped(self, paths: list[str]) -> None:
        self.load(paths[0])
        if len(paths) > 1:
            if self.on_more:
                self.on_more(paths[1:])
            else:
                self.result.content = t.text(f"{len(paths)} files dropped; the first was used.", 12, t.AMBER)
                self.control.update()

    def load(self, path: str) -> None:
        """A Pokemon file, or a text file of Showdown sets (a team fills the trades after this one)."""
        if drop.suffix(path) == "txt":
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                self._message(f"Could not read {Path(path).name}: {exc}", t.RED)
                self.control.update()
                return
            self._paste(None, text)
            return
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

    def _paste(self, e, text: str = "") -> None:
        """A Showdown or Smogon set fills the form; Build then makes it. In a queue a team fills the trades
        after this one; anywhere else a team gives its first set. A `text` given is read at once."""
        editor = t.field(value=text, multiline=True, min_lines=12, max_lines=18, mono=True, autofocus=True,
                         hint="Garchomp @ Choice Scarf\nAbility: Rough Skin\nEVs: 252 Atk / 4 SpD / 252 Spe\n"
                              "Jolly Nature\n- Earthquake\n- Outrage")
        status = ft.Container()
        apply = t.button("Apply", None)

        def close(_=None):
            self.app.page.pop_dialog()

        def show(lines: list[str], color: str):
            status.content = ft.Column([t.text(line, 12, color, selectable=True) for line in lines], spacing=2)

        def submit(_):
            text = editor.value or ""
            if not text.strip():
                show(["Paste a set first."], t.RED)
                status.update()
                return
            apply.disabled = True
            status.content = ft.Row([PixelActivity("Reading the set"), t.text("Reading the set...", 12, t.MUTED)],
                                    spacing=8)
            status.update()
            apply.update()

            def work():
                try:
                    sets, error = builder.SERVICE.paste(self.game, text, self.app.settings.trainer(self.game),
                                                        VERSIONS.get(self.version, "")), ""
                except Exception as exc:
                    sets, error = [], str(exc)

                def done():
                    apply.disabled = False
                    used = sets if self.on_team else sets[:1]
                    problems = [error] if error else [
                        f"{found.get('species') or f'Set {n}'}: {problem}" if len(used) > 1 else problem
                        for n, found in enumerate(used, start=1) for problem in found["errors"]]
                    if problems:
                        show(problems, t.RED)
                        status.update()
                        apply.update()
                        return
                    close()
                    notes = list(sets[0]["notes"])
                    if len(sets) > 1:
                        notes.insert(0, self.on_team(sets[1:]) if self.on_team else
                                     f"The paste holds {len(sets)} Pokemon; the first was imported.")
                    self._apply_set(sets[0], notes)
                self.app.ui(done)
            threading.Thread(target=work, daemon=True).start()

        apply.on_click = submit
        self.app.page.show_dialog(t.dialog(
            title=t.text("Import a Showdown set", 17, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Column([
                t.text("Paste a set exported from Pokemon Showdown, Smogon or PKHeX. Its values fill the form; "
                       "press Build to make a legal Pokemon from them.", 13, t.MUTED),
                editor, status], spacing=10, tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH), width=520),
            actions=[t.secondary_button("Cancel", close), apply],
        ))
        if text.strip():
            submit(None)

    def _apply_set(self, found: dict, notes: list[str]) -> None:
        for key in ("file", "summary", "legal", "encounter", "moves", "report"):
            self.value.pop(key, None)
        self.value.update(species=found["species_id"], level=str(found["level"]), shiny=found["shiny"],
                          nickname=found["nickname"])
        self.options.chosen.clear()
        self.options.chosen.update(found["options"])
        if self.species.options:
            self.species.value = str(found["species_id"])
        self.level.value = self.value["level"]
        self.shiny.value = found["shiny"]
        self.nickname.value = found["nickname"]
        self.sprite.show(found["species_id"], found["shiny"], update=False)
        self.options.reveal()
        self.on_change(dict(self.value))
        name = f"{found['species']}-{found['form']}" if found["form"] else found["species"]
        lines = [t.text(f"Imported {name}. Check the options below, then press Build.", 12, t.MUTED)]
        lines += [t.text(note, 12, t.AMBER) for note in notes]
        self.result.content = ft.Column(lines, spacing=2)
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
            lines.append(t.text(self.value["report"], 12, t.RED, selectable=True))
        self.result.content = ft.Column(lines, spacing=4)


class OfferQueue:
    """The Pokemon one session trades, in order: one picker per trade, up to `limit`."""

    def __init__(self, app, game: str, value, limit: int, on_change, version: str = ""):
        self.app, self.game, self.limit, self.on_change, self.version = app, game, limit, on_change, version
        self.slots: list[dict] = []
        self.rows = ft.Column(spacing=10)
        self.count = t.text("", 12, t.MUTED)
        self.add_icon = t.pixel_icon("plus", color=t.BLUE)
        self.add_box = t.surface(ft.Container(ft.Row([
            self.add_icon,
            ft.Column([t.text("Add a trade", 13, weight=ft.FontWeight.W_600), self.count], spacing=0, tight=True),
        ], spacing=12, tight=True), padding=ft.Padding(16, 10, 22, 10)), on_click=self._add, ink=True)
        self.control = self.rows
        self.card: ft.Container | None = None    # the caller's card around `control`; it lights for one trade
        # Placed by the caller under that card.
        self.footer = ft.Row([drop.target(self.add_box, self._append)], alignment=ft.MainAxisAlignment.CENTER)
        for entry in (offers(value)[:limit] or [{}]):
            self._slot(entry)
        self._render()

    def _slot(self, entry: dict, at: int | None = None) -> dict:
        slot = {"value": dict(entry), "title": t.text("", 13, weight=ft.FontWeight.W_600, expand=True)}
        slot["picker"] = PokemonPicker(self.app, self.game, entry, lambda v, s=slot: self._changed(s, v),
                                       version=self.version, on_team=lambda sets, s=slot: self._team(s, sets),
                                       on_more=lambda paths, s=slot: self._more(s, paths),
                                       glow=lambda s=slot: s["box"] if len(self.slots) > 1 else self.card)
        slot["remove"] = t.icon_button("close", lambda e, s=slot: self._remove(s), "Remove this trade")
        slot["header"] = ft.Row([slot["title"], slot["remove"]], spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER)
        slot["box"] = ft.Container(ft.Column([slot["header"], slot["picker"].control], spacing=8))
        self.slots.insert(len(self.slots) if at is None else at, slot)
        return slot

    def _render(self) -> None:
        several = len(self.slots) > 1
        for n, slot in enumerate(self.slots, start=1):
            slot["title"].value = f"Trade {n}"
            slot["header"].visible = several
            slot["box"].border = ft.Border.all(1, t.DIVIDER) if several else None
            slot["box"].border_radius = 12 if several else None
            slot["box"].padding = ft.Padding(12, 6, 6, 12) if several else None
        self.rows.controls = [slot["box"] for slot in self.slots]
        full = len(self.slots) >= self.limit
        self.add_box.disabled = full
        self.add_box.opacity = 0.5 if full else 1.0
        self.count.value = (f"{len(self.slots)} of {self.limit}, traded in this order" if several
                            else f"Up to {self.limit} Pokemon in one session")
        if drop.AVAILABLE and not full:
            self.count.value += "; or drop files here"
        self.count.color = t.MUTED

    def _spread(self, at: int, items: list) -> list[tuple[dict, object]]:
        """Places `items` from trade `at` on: an untouched trade is filled, otherwise a new one is inserted,
        up to the session's limit. Redraws the queue."""
        placed = []
        for item in items:
            following = self.slots[at] if at < len(self.slots) else None
            if following is not None and not following["value"].get("species"):
                placed.append((following, item))
            elif len(self.slots) < self.limit:
                placed.append((self._slot({}, at), item))
            else:
                break
            at += 1
        self._render()
        self._save()
        self.rows.update()
        self.footer.update()
        return placed

    def _more(self, first: dict, paths: list[str]) -> None:
        self._load(self._spread(self.slots.index(first) + 1, paths), len(paths))

    def _append(self, paths: list[str]) -> None:
        """Files dropped on "Add a trade" fill the untouched trades at the end, then new ones."""
        at = len(self.slots)
        while at > 0 and not self.slots[at - 1]["value"].get("species"):
            at -= 1
        self._load(self._spread(at, paths), len(paths))

    def _load(self, placed: list[tuple[dict, str]], dropped: int) -> None:
        for slot, path in placed:
            slot["picker"].load(path)
        if len(placed) < dropped:
            self.count.value = f"{dropped - len(placed)} did not fit: one session trades at most {self.limit}."
            self.count.color = t.AMBER
            self.count.update()

    def _team(self, first: dict, sets: list[dict]) -> str:
        """The rest of a pasted team goes into the trades after `first`."""
        placed = self._spread(self.slots.index(first) + 1, sets)
        for slot, found in placed:
            slot["picker"]._apply_set(found, list(found["notes"]))
        numbers = [self.slots.index(slot) + 1 for slot, _ in placed]
        message = (f"The paste holds {len(sets) + 1} Pokemon; the others went to "
                   f"{'trade' if len(numbers) == 1 else 'trades'} {', '.join(map(str, numbers))}." if numbers else
                   f"The paste holds {len(sets) + 1} Pokemon; only the first fit.")
        if len(placed) < len(sets):
            message += f" {len(sets) - len(placed)} did not fit: one session trades at most {self.limit}."
        return message

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
        self.footer.update()

    def _remove(self, slot: dict) -> None:
        if len(self.slots) > 1:
            self.slots.remove(slot)
            self._render()
            self._save()
            self.control.update()
            self.footer.update()


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
        header = ft.Container(ft.Row([self.chevron, t.text("More options", 13, t.TEXT, weight=ft.FontWeight.W_600),
                                      self.label], spacing=8),
                              padding=ft.Padding(2, 4, 2, 4), border_radius=8, on_click=self._toggle)
        self.control = ft.Column([header, self.body], spacing=8)
        self._label()

    def _label(self) -> None:
        count = sum(1 for k, v in self.chosen.items() if (v if isinstance(v, dict) else v is not None))
        self.label.value = f"{count} set" if count else "random"

    def _toggle(self, e) -> None:
        self._show(not self.open)
        self.control.update()

    def _show(self, open: bool) -> None:
        self.open = open
        self.chevron.src = f"icons/chevron-{'down' if self.open else 'right'}.svg"
        self.body.visible = self.open
        if self.open:
            self._load()

    def reveal(self) -> None:
        """Opens the options on what an import chose."""
        self.loaded_for = None
        self._show(True)
        self._label()

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
        target = (species, int(self.chosen.get("form") or 0))
        if self.loaded_for == target:
            return
        self.loaded_for = target
        self.body.controls = [ft.Row([PixelActivity("Loading options"),
                                      t.text("Reading what this species can have...", 12, t.MUTED)], spacing=8)]
        app = self.picker.app

        def work():
            try:
                found = builder.SERVICE.options(self.picker.game, species, app.settings.trainer(self.picker.game),
                                                VERSIONS.get(self.picker.version, ""), target[1])
                found["move_names"], error = builder.SERVICE.names(self.picker.game, "moves"), ""
            except Exception as exc:
                found, error = None, str(exc)

            def show():
                if self.loaded_for != target:
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
        if all(f["id"] != self.chosen.get("form", 0) for f in found["forms"]):
            self.chosen.pop("form", None)
        first = [t.labeled_control("Nature", self._choice("nature", found["natures"]), expand=True)]
        if len(found["forms"]) > 1:
            first.insert(0, t.labeled_control("Form", self._choice("form", found["forms"], reload=True),
                                              expand=True))
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
            self._moves(found["move_names"]),
            self._stats("ivs", "IVs", 31, "0-31"),
            self._stats("effort", EFFORT[effort["kind"]], effort["max"], limit, effort.get("total")),
            ft.Row([t.text("Empty means random. The build is checked by PKHeX's legality analysis.", 12, t.FAINT,
                           expand=True),
                    t.link_button("Clear", self._clear)]),
        ]

    def _choice(self, key: str, names: list[dict], search: bool = False, reload: bool = False) -> ft.Dropdown:
        current = self.chosen.get(key)

        def picked(e):
            if e.control.value == ANY:
                self.chosen.pop(key, None)
            else:
                self.chosen[key] = int(e.control.value)
            self._label()
            if reload:      # a form has its own abilities
                self._load()
                self.control.update()
            else:
                self.label.update()
        options = [(ANY, "Random")] + [(str(n["id"]), n["name"]) for n in
                                       (sorted(names, key=lambda n: n["name"]) if search else names)]
        return t.dropdown(options, ANY if current is None else str(current), on_select=picked,
                          enable_filter=search, editable=search, menu_height=320)

    def _moves(self, names: list[dict]) -> ft.Control:
        moves = (list(self.chosen.get("moves", [])) + [0] * 4)[:4]
        options = [(ANY, "Any")] + [(str(n["id"]), n["name"]) for n in names]

        def picked(e, slot):
            moves[slot] = 0 if e.control.value == ANY else int(e.control.value)
            if any(moves):
                self.chosen["moves"] = [m for m in moves if m]
            else:
                self.chosen.pop("moves", None)
            self._label()
            self.label.update()
        boxes = [t.dropdown(options, str(m) if m else ANY, on_select=lambda e, n=n: picked(e, n),
                            enable_filter=True, editable=True, menu_height=320)
                 for n, m in enumerate(moves)]
        for box in boxes:
            box.expand = True
        return ft.Column([t.text("Moves (empty means the encounter's own)", 12, t.MUTED),
                          ft.Row(boxes[:2], spacing=6), ft.Row(boxes[2:], spacing=6)], spacing=4)

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
        return ft.Column([t.text(f"{title} ({limit})", 12, t.MUTED), ft.Row(boxes, spacing=6)], spacing=4)

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

    def __init__(self, app, game: str, kind: str, value: str, on_change, optional: bool = True,
                 names: list[dict] | None = None):
        """`names` ([{"id", "name"}]) replaces the PKHeX list, for a game whose ids differ from it."""
        self.app, self.game, self.kind, self.optional = app, game, NAME_LISTS[kind], optional
        self.names = names
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
            names = self.names if self.names is not None else builder.SERVICE.names(self.game, self.kind)
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


# The Let's Go link code picker, in its order (pokeldn.lgpe.session.CODE_PICKER): national dex numbers
# for the sprites and the names shown under them.
CODE_SPECIES = (25, 133, 1, 4, 7, 16, 10, 19, 39, 50)
CODE_NAMES = ("Pikachu", "Eevee", "Bulbasaur", "Charmander", "Squirtle",
              "Pidgey", "Caterpie", "Rattata", "Jigglypuff", "Diglett")
CODE_TILE = MINI + 2 * EDGE


class LinkCodePicker:
    """Let's Go's link code: three slots, each filled from the ten Pokemon of the console's picker.
    The value is the three English names, comma-separated, as `--code` takes them."""

    def __init__(self, app, value: str, on_change):
        self.app, self.on_change = app, on_change
        self.picks = parse_code(value)
        self.open: int | None = None
        self.slots = ft.Row(spacing=10)
        self.grid = ft.Column(spacing=6, visible=False, tight=True)
        self.control = ft.Column([self.slots, self.grid], spacing=12, tight=True)
        self._render(update=False)

    def _tile(self, index: int | None, label: str, on_click, selected: bool = False) -> ft.Control:
        # The name stays under the sprite: a sprite never downloaded shows only a placeholder.
        species = CODE_SPECIES[index] if index is not None else 0
        art = (Sprite(self.app, species, size=MINI).control if index is not None else
               ft.Container(t.pixel_icon("plus", color=t.FAINT), width=CODE_TILE, height=CODE_TILE,
                            alignment=ft.Alignment.CENTER, border=ft.Border.all(EDGE, t.DIVIDER),
                            border_radius=10))
        return ft.Container(
            ft.Column([art, t.text(label, 11, t.TEXT if index is not None else t.FAINT,
                                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                      spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=CODE_TILE + 28, padding=ft.Padding(4, 6, 4, 6), border_radius=10,
            bgcolor=t.SELECTED if selected else None, on_click=on_click, ink=True)

    def _render(self, update: bool = True) -> None:
        self.slots.controls = [
            self._tile(pick, CODE_NAMES[pick] if pick is not None else f"Slot {n + 1}",
                       lambda e, n=n: self._toggle(n), selected=self.open == n)
            for n, pick in enumerate(self.picks)]
        self.grid.visible = self.open is not None
        # Two rows of five, as the console lays its picker out.
        tiles = [] if self.open is None else [
            self._tile(i, name, lambda e, i=i: self._choose(i), selected=self.picks[self.open] == i)
            for i, name in enumerate(CODE_NAMES)]
        self.grid.controls = [ft.Row(tiles[r:r + 5], spacing=6) for r in range(0, len(tiles), 5)]
        if update:
            try:
                self.control.update()
            except RuntimeError:    # not on the page yet
                pass

    def _toggle(self, slot: int) -> None:
        self.open = None if self.open == slot else slot
        self._render()

    def _choose(self, index: int) -> None:
        self.picks[self.open] = index
        empty = [n for n, pick in enumerate(self.picks) if pick is None]
        self.open = empty[0] if empty else None
        self._render()
        self.on_change(code_value(self.picks))


def parse_code(value) -> list[int | None]:
    """The three slots of a saved `--code` value; a slot that does not read is empty."""
    parts = [p for p in str(value or "").split(",")][:3]
    picks: list[int | None] = []
    for part in parts + [""] * (3 - len(parts)):
        try:
            picks.append(code_picks([part, 0, 0])[0] if part.strip() else None)
        except ValueError:
            picks.append(None)
    return picks


def code_value(picks: list[int | None]) -> str:
    return ",".join(CODE_PICKER[p] if p is not None else "" for p in picks)

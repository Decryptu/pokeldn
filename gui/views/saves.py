"""The FireRed/LeafGreen Mystery Gift tool's save mode: back the console's save up into the library, or
put one from the library back on the console; the library lists, names, imports, exports and edits them
[pokeldn.app.saves, docs/gui.md, Your saves]."""

import os
import threading

import flet as ft

from gui import drop, theme as t
from gui.views.pokemon import PokemonPicker
from gui.views.sprites import MINI, Sprite
from gui.views.widgets import open_folder
from pokeldn import pokemon
from pokeldn.app import saves
from pokeldn.frlg.save import sav

CHECKING: set[str] = set()     # saves PKHeX is reading
ACTIONS = [("backup", "Back up from the Switch", "upload"), ("restore", "Put a save on the Switch", "download")]
BACKUP_HELP = ("The console sends its whole save to this computer and keeps it as it was. It takes one to "
               "four minutes: keep the Switch near the board until the console shows the message.")
RESTORE_HELP = ("The chosen save goes beside the console's own. The console checks every part of it, "
                "loads it and saves. If anything goes wrong, it keeps the save it had.")


def _trainer_line(entry: saves.Entry) -> str:
    if not entry.sound:
        return "Neither of its two copies is whole"
    who = entry.trainer
    parts = [who["name"], f"ID {who['tid']:05d}", f"{who['hours']} h {who['minutes']:02d}", entry.cartridge]
    return " · ".join(p for p in parts if p)


def _mon_title(mon: dict) -> str:
    """Nickname, species and level; the nickname only when it is not the species' own name."""
    named = mon["nickname"] and mon["nickname"].casefold() != mon["species"].casefold()
    return f"{mon['nickname'] + ' · ' if named else ''}{mon['species']} · Lv {mon['level']}"


class SavePanel:
    """The body of the Gift card in save mode; `builder` is the tool's GiftBuilder."""

    def __init__(self, builder):
        self.builder, self.app = builder, builder.app
        self.chosen = builder.value["save"]
        self.listing = ft.Column(spacing=6)
        self.legality = ft.Container()
        self.note = t.text("", 12, t.MUTED)

    def control(self) -> ft.Control:
        action = self.chosen["action"]
        actions = t.segmented(ACTIONS, action, self._action, wrap=True)
        tools = ft.Row([t.icon_button("plus", self._import, "Add a .sav file"),
                        t.icon_button("folder", lambda e: open_folder(str(saves.library())), "Open the folder"),
                        t.icon_button("refresh", lambda e: self.refresh(), "Refresh")], spacing=0)
        body = [actions, t.text(BACKUP_HELP if action == "backup" else RESTORE_HELP, 12, t.MUTED)]
        if action == "backup" and saves.has_partial():
            body.append(t.badge("A backup the link cut short goes on from where it stopped.", t.BLUE))
        self.refresh(update=False)
        library = t.section("Your saves", ft.Column([self.listing, self.legality, self.note], spacing=8),
                            trailing=tools)
        return drop.target(ft.Column([*body, library], spacing=14), self._dropped)

    # The library

    def refresh(self, update: bool = True) -> None:
        items = saves.entries()
        restoring = self.chosen["action"] == "restore"
        if restoring and self.chosen["file"] not in {e.path for e in items}:
            self.chosen["file"] = ""
        self.listing.controls = [self._row(e, restoring) for e in items] or [t.text(
            "No saves yet. Back one up from the Switch, or add a .sav file"
            + (" (drop it here)." if drop.AVAILABLE else "."), 12, t.FAINT)]
        self._show_legality()
        if update:
            self.listing.update()
            self.legality.update()

    def _row(self, entry: saves.Entry, restoring: bool) -> ft.Control:
        selected = restoring and entry.path == self.chosen["file"]
        lead = [t.pixel_icon("checkbox-on" if selected else "checkbox",
                             color=t.BLUE if selected else t.FAINT)] if restoring else []
        line = t.text(_trainer_line(entry), 12, t.MUTED if entry.sound else t.AMBER, max_lines=1,
                      overflow=ft.TextOverflow.ELLIPSIS)
        def item(label, icon, action):
            return ft.PopupMenuItem(ft.Row([t.pixel_icon(icon, color=t.MUTED), t.text(label, 13)], spacing=10),
                                    on_click=action, height=40)
        menu = ft.PopupMenuButton(
            content=ft.Container(t.pixel_icon("more-vertical", color=t.MUTED), width=32, height=32,
                                 alignment=ft.Alignment.CENTER),
            tooltip="More", bgcolor=t.PANEL, menu_position=ft.PopupMenuPosition.UNDER, items=[
                item("Rename", "label", lambda e, x=entry: self._rename(x)),
                item("Export .sav", "save", lambda e, x=entry: self.app.page.run_task(self._export, x)),
                item("Delete", "trash", lambda e, x=entry: self._delete(x))])
        tools = ft.Row([t.icon_button("edit", lambda e, x=entry: SaveEditor(self, x).open(),
                                      "View and edit", disabled=not entry.sound), menu], spacing=0)
        return ft.Container(ft.Row([
            *lead,
            ft.Column([t.text(entry.name, 13, weight=ft.FontWeight.W_600, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS), line,
                       t.text(entry.when, 11, t.FAINT)], spacing=1, expand=True),
            tools,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(10, 6, 4, 6), border_radius=10,
            border=ft.Border.all(1, t.BLUE if selected else t.BORDER), bgcolor=t.SELECTED if selected else None,
            on_click=(lambda e, x=entry: self._pick(x)) if restoring and entry.sound else None)

    def _action(self, key) -> None:
        self.chosen["action"] = key
        self.builder.commit(rebuild=True)

    def _pick(self, entry: saves.Entry) -> None:
        """The selection shows at once; Start's checks run once PKHeX has read the party."""
        self.chosen["file"], self.chosen["anyway"] = entry.path, False
        if saves.cached_check(entry.path) is not None:
            self.builder.commit(rebuild=True)
            return
        self.refresh()

    def _check_party(self, path: str) -> None:
        """PKHeX reads the party once per file version, off the UI thread; the panel redraws when it has."""
        if saves.cached_check(path) is not None or path in CHECKING:
            return
        CHECKING.add(path)

        def work():
            saves.party_check(path)
            CHECKING.discard(path)
            self.app.ui(lambda: self.builder.commit(rebuild=True) if self.chosen.get("file") == path else None)
        threading.Thread(target=work, daemon=True).start()

    def _show_legality(self) -> None:
        path = self.chosen.get("file", "")
        if self.chosen["action"] != "restore" or not path:
            self.legality.content = None
            return
        check = saves.cached_check(path)
        if check is None:
            self.legality.content = t.badge("Checking the party with PKHeX...", t.BLUE, "refresh")
            self._check_party(path)
        elif check["error"]:
            self.legality.content = t.badge(f"PKHeX could not read the party: {check['error']}", t.AMBER,
                                            "warning-diamond")
        elif not check["illegal"]:
            self.legality.content = t.badge("Every Pokemon in the party is legal.", t.GREEN, "check")
        else:
            self.legality.content = ft.Row([
                ft.Column([t.text("Restore anyway", 13),
                           t.text(f"PKHeX finds {', '.join(check['illegal'])} not legal.", 12, t.AMBER)],
                          spacing=1, expand=True),
                t.switch(bool(self.chosen.get("anyway")), self._anyway)])

    def _anyway(self, e) -> None:
        self.chosen["anyway"] = bool(e.control.value)
        self.builder.commit()

    # Files

    def _dropped(self, paths: list[str]) -> None:
        for path in paths:
            if drop.suffix(path) == "sav":
                self._add(path)

    async def _import(self, e) -> None:
        files = await self.app.picker.pick_files(allowed_extensions=["sav"],
                                                 file_type=ft.FilePickerFileType.CUSTOM, allow_multiple=True)
        for file in files or ():
            self._add(file.path)

    def _add(self, path: str) -> None:
        try:
            added = saves.import_file(path)
            self._say(f"Added {added.name}." if added.sound else
                      f"Added {added.name}, but neither of its two copies is whole.", t.MUTED)
        except (OSError, sav.SaveError) as exc:
            self._say(f"{os.path.basename(path)}: {exc}", t.RED)
        self.refresh()

    async def _export(self, entry: saves.Entry) -> None:
        path = await self.app.picker.save_file(dialog_title="Export save", file_name=saves.file_name(entry),
                                               file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["sav"])
        if not path:
            return
        path += "" if path.lower().endswith(".sav") else ".sav"
        try:
            saves.export(entry, path)
            self._say(f"Exported to {path}", t.MUTED)
        except OSError as exc:
            self._say(str(exc), t.RED)

    def _rename(self, entry: saves.Entry) -> None:
        box = t.field(value=entry.name, autofocus=True, width=360)

        def done(e):
            saves.rename(entry, box.value)
            self.app.page.pop_dialog()
            self.refresh()

        box.on_submit = done
        self.app.page.show_dialog(t.dialog(
            title=t.text("Rename the save", 18), content=box,
            actions=[t.button("Cancel", lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button("Rename", done)]))

    def _delete(self, entry: saves.Entry) -> None:
        def done(e):
            saves.delete(entry)
            self.app.page.pop_dialog()
            self.refresh()

        self.app.page.show_dialog(t.dialog(
            title=t.text("Delete this save?", 18),
            content=t.text(f"{entry.name} is removed from this computer. The Switch keeps its own save.",
                           13, t.MUTED, width=380),
            actions=[t.button("Cancel", lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button("Delete", done, color=t.RED)]))

    def _say(self, text: str, color: str) -> None:
        self.note.value, self.note.color = text, color
        self.note.update()


class SaveEditor:
    """A dialog over one save: its trainer, party and boxes as PKHeX reads them. Changes are kept as a new
    save in the library, the original untouched."""

    def __init__(self, panel: SavePanel, entry: saves.Entry):
        self.panel, self.app, self.entry = panel, panel.app, entry
        self.data = open(entry.path, "rb").read()
        self.info: dict | None = None
        self.party: list[dict] = []      # {"keep": n} or {"data": base64}, each with its PKHeX description
        self.trainer: dict = {}
        self.body = ft.Column([t.badge("Reading the save with PKHeX...", t.BLUE, "refresh")], spacing=18,
                              scroll=ft.ScrollMode.AUTO, width=640, height=560)
        self.status = t.text("", 12, t.MUTED)
        self.save_button = t.button("Keep as a new save", self._save, disabled=True)

    def open(self) -> None:
        self.app.page.show_dialog(t.dialog(
            title=t.text(self.entry.name, 18), content=self.body,
            actions=[self.status, t.button("Close", lambda e: self.app.page.pop_dialog(), filled=False),
                     self.save_button]))
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            info = pokemon.SERVICE.save_read(self.data)
        except Exception as exc:
            message = str(exc)
            self.app.ui(lambda: self._fail(message))
            return

        def show():
            self.info = info
            self.party = [{"keep": n, "info": m} for n, m in enumerate(info["party"])]
            self.trainer = {"name": info["name"], "gender": info["gender"], "money": info["money"],
                            "coins": info["coins"]}
            self.save_button.disabled = False
            self.render()
        self.app.ui(show)

    def _fail(self, message: str) -> None:
        self.body.controls = [t.text(f"PKHeX could not read this save: {message}", 13, t.RED)]
        self.body.update()

    def render(self) -> None:
        self.body.controls = [self._trainer(), self._party(), self._boxes()]
        self.body.update()
        self.save_button.update()

    # Trainer

    def _trainer(self) -> ft.Control:
        info = self.info

        def number(key, limit):
            def changed(e):
                try:
                    self.trainer[key] = max(0, min(int(e.control.value or 0), limit))
                    e.control.error = None
                except ValueError:
                    e.control.error = "A number"
                e.control.update()
            return t.field(value=str(self.trainer[key]), mono=True, width=130, digits=True,
                           limit=len(str(limit)), on_change=changed)

        name = t.field(value=self.trainer["name"], width=150, limit=7,
                       on_change=lambda e: self.trainer.__setitem__("name", e.control.value))
        gender = t.dropdown([("0", "Boy"), ("1", "Girl")], str(self.trainer["gender"]),
                            on_select=lambda e: self.trainer.__setitem__("gender", int(e.control.value)), width=110)
        facts = (f"ID {info['trainer_id']:05d} · secret ID {info['secret_id']:05d} · {info['hours']} h "
                 f"{info['minutes']:02d} · {info['badges']} badges · Pokedex {info['caught']} caught, "
                 f"{info['seen']} seen")
        return t.section("Trainer", ft.Column([
            ft.Row([t.labeled_control("Name", name), t.labeled_control("Gender", gender),
                    t.labeled_control("Money", number("money", info["max_money"])),
                    t.labeled_control("Coins", number("coins", info["max_coins"]))], spacing=10),
            t.text(facts, 12, t.MUTED)], spacing=8))

    # Party

    def _party(self) -> ft.Control:
        rows = [self._party_row(n, slot) for n, slot in enumerate(self.party)]
        adder = ([t.secondary_button("Add a Pokemon", self._add, "plus")] if len(self.party) < 6 else [])
        return t.section("Party", ft.Column([*rows, *adder], spacing=6),
                         trailing=t.text(f"{len(self.party)} of 6", 12, t.MUTED))

    def _party_row(self, n: int, slot: dict) -> ft.Control:
        mon = slot["info"]
        legal = mon["legal"]
        verdict = (t.pixel_icon("check", color=t.GREEN, tooltip="Legal") if legal else
                   t.pixel_icon("warning-diamond", color=t.AMBER, tooltip=mon["report"][:600]))
        moves = ", ".join(mon["moves"])
        last = len(self.party) - 1
        tools = ft.Row([
            t.icon_button("chevron-up", lambda e: self._move(n, -1), "Earlier", disabled=n == 0),
            t.icon_button("chevron-down", lambda e: self._move(n, 1), "Later", disabled=n == last),
            t.icon_button("trash", lambda e: self._remove(n), "Remove", disabled=last == 0),
        ], spacing=0)
        return ft.Container(ft.Row([
            Sprite(self.app, int(mon["species_id"]), bool(mon["shiny"]), size=MINI).control,
            ft.Column([ft.Row([t.text(_mon_title(mon), 13, weight=ft.FontWeight.W_600), verdict], spacing=6),
                       t.text(moves or "No moves", 12, t.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                      spacing=1, expand=True),
            tools], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(8, 4, 4, 4), border_radius=10, border=ft.Border.all(1, t.BORDER))

    def _move(self, n: int, delta: int) -> None:
        self.party[n], self.party[n + delta] = self.party[n + delta], self.party[n]
        self.render()

    def _remove(self, n: int) -> None:
        del self.party[n]
        self.render()

    def _add(self, e) -> None:
        info = self.info
        owner = {"ot": info["name"], "tid": info["trainer_id"], "sid": info["secret_id"],
                 "language": self.entry.language or self.app.settings.language, "gender": info["gender"]}
        version = {"BPG": "leafgreen"}.get(self.entry.game_code[:3], "firered")

        def built(value: dict) -> None:
            data = open(value["file"], "rb").read()
            try:
                described = pokemon.SERVICE.check_bytes("frlg", data)
            except Exception as exc:
                message = str(exc)
                self.app.ui(lambda: self._say(message, t.RED))
                return
            self.party.append({"data": described["data"], "info": described})
            self.app.ui(self.render)

        picker = PokemonPicker(self.app, "frlg", {}, built, version=version, trainer=owner)
        self.body.controls = [self._trainer(), self._party(),
                              t.section("New Pokemon, for the trainer of this save", picker.control),
                              self._boxes()]
        self.body.update()

    # Boxes

    def _boxes(self) -> ft.Control:
        boxes = self.info["boxes"]
        grid = ft.Row(spacing=4, run_spacing=4, wrap=True)
        verdicts = ft.Column(spacing=2)
        chosen = {"box": 0}

        def show(index: int, update: bool = True) -> None:
            chosen["box"] = index
            grid.controls = [ft.Container(Sprite(self.app, int(m["species_id"]), bool(m["shiny"]), size=MINI).control,
                                          tooltip=_mon_title(m) + (" · egg" if m["egg"] else ""))
                             for m in boxes[index]["mons"]] or [t.text("Empty", 12, t.FAINT)]
            verdicts.controls = []
            if update:
                grid.update()
                verdicts.update()

        def check(e) -> None:
            index = chosen["box"]
            verdicts.controls = [t.badge("Checking with PKHeX...", t.BLUE, "refresh")]
            verdicts.update()

            def work():
                try:
                    mons = pokemon.SERVICE.save_box(self.data, index)
                    bad = [m for m in mons if m and not m["legal"]]
                    lines = [t.badge(f"{m['species']} (Lv {m['level']}) is not legal", t.AMBER, "warning-diamond")
                             for m in bad] or [t.badge("Every Pokemon in this box is legal.", t.GREEN, "check")]
                except Exception as exc:
                    lines = [t.text(str(exc), 12, t.RED)]
                self.app.ui(lambda: (setattr(verdicts, "controls", lines), verdicts.update())
                            if chosen["box"] == index else None)
            threading.Thread(target=work, daemon=True).start()

        picker = t.dropdown([(str(i), f"{b['name']} ({len(b['mons'])})") for i, b in enumerate(boxes)], "0",
                            on_select=lambda e: show(int(e.control.value)), width=220)
        show(0, update=False)
        return t.section("PC boxes", ft.Column([
            ft.Row([picker, t.secondary_button("Check legality", check, "shield")], spacing=10),
            grid, verdicts], spacing=8))

    # Save

    def _save(self, e) -> None:
        self.save_button.disabled = True
        self._say("Writing the save...", t.MUTED)
        self.save_button.update()
        party = [{"keep": s["keep"]} if "keep" in s else {"data": s["data"]} for s in self.party]
        trainer = dict(self.trainer)

        def work():
            try:
                data, _info = pokemon.SERVICE.save_edit(self.data, trainer=trainer, party=party)
                if not sav.describe(data).sound:
                    raise sav.SaveError("the edited save did not pass the game's own sector checks")
                added = saves.add(data, source="edit", name=f"{self.entry.name} (edited)",
                                  game_code=self.entry.game_code)
                done = lambda: self._saved(added)   # noqa: E731
            except Exception as exc:
                message = str(exc)
                done = lambda: (self._say(message, t.RED), setattr(self.save_button, "disabled", False),  # noqa: E731
                                self.save_button.update())
            self.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

    def _saved(self, added: saves.Entry) -> None:
        self.app.page.pop_dialog()
        self.panel.refresh()
        self.panel._say(f"Kept as {added.name}. The original is unchanged.", t.GREEN)

    def _say(self, text: str, color: str) -> None:
        self.status.value, self.status.color = text, color
        self.status.update()

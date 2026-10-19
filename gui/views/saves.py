"""The FireRed/LeafGreen Mystery Gift tool's save mode: back the console's save up into the library, or
put one from the library back on the console; the library lists, names, imports, exports and edits them
[pokeldn.app.saves, docs/gui.md, Your saves]."""
from pokeldn.app.i18n import t as tr

import os
import threading

import flet as ft

from gui import drop, theme as t
from gui.views.pokemon import PokemonPicker
from gui.views.sprites import MINI, Sprite
from gui.views.widgets import open_folder
from gui.localization import SERVICE, date_time
from pokeldn.app import saves
from pokeldn.frlg.save import sav

CHECKING: set[str] = set()     # saves PKHeX is reading
ACTIONS = [("backup", tr('saves.back_up_from_the_switch_0fbca5', 'Back up from the Switch'), "upload"), ("restore", tr('saves.put_a_save_on_the_switch_f7f0e9', 'Put a save on the Switch'), "download")]
BACKUP_HELP = (tr('saves.the_console_sends_its_whole_save_to_this_computer_and_k_53ba6d', 'The console sends its whole save to this computer and keeps it as it was. It takes one to four minutes: keep the Switch near the board until the console shows the message.'))
RESTORE_HELP = (tr('saves.the_chosen_save_goes_beside_the_console_s_own_the_conso_f807d8', "The chosen save goes beside the console's own. The console checks every part of it, loads it and saves. If anything goes wrong, it keeps the save it had."))


def _trainer_line(entry: saves.Entry) -> str:
    if not entry.sound:
        return tr('saves.neither_of_its_two_copies_is_whole_c69bdd', 'Neither of its two copies is whole')
    who = entry.trainer
    parts = [who["name"], tr('saves.id_0228f0', 'ID {value0:05d}', value0=who['tid']), tr('saves.h_49204f', '{value0} h {value1:02d}', value0=who['hours'], value1=who['minutes']), entry.cartridge]
    return " · ".join(p for p in parts if p)


def _mon_title(mon: dict) -> str:
    """Nickname, species and level; the nickname only when it is not the species' own name."""
    named = mon["nickname"] and mon["nickname"].casefold() != mon["species"].casefold()
    return tr('saves.lv_1d0a5f', '{value0}{value1} · Lv {value2}', value0=mon['nickname'] + ' · ' if named else '', value1=mon['species'], value2=mon['level'])


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
        tools = ft.Row([t.icon_button("plus", self._import, tr('saves.add_a_sav_file_7a1fae', 'Add a .sav file')),
                        t.icon_button("folder", lambda e: open_folder(str(saves.library())), tr('saves.open_the_folder_e241ab', 'Open the folder')),
                        t.icon_button("refresh", lambda e: self.refresh(), tr('saves.refresh_0e9161', 'Refresh'))], spacing=0)
        body = [actions, t.text(BACKUP_HELP if action == "backup" else RESTORE_HELP, 12, t.MUTED)]
        if action == "backup" and saves.has_partial():
            body.append(t.badge(tr('saves.a_backup_the_link_cut_short_goes_on_from_where_it_stopp_75fbed', 'A backup the link cut short goes on from where it stopped.'), t.BLUE))
        self.refresh(update=False)
        library = t.section(tr('saves.your_saves_a6a8a1', 'Your saves'), ft.Column([self.listing, self.legality, self.note], spacing=8),
                            trailing=tools)
        return drop.target(ft.Column([*body, library], spacing=14), self._dropped)

    # The library

    def refresh(self, update: bool = True) -> None:
        items = saves.entries()
        restoring = self.chosen["action"] == "restore"
        if restoring and self.chosen["file"] not in {e.path for e in items}:
            self.chosen["file"] = ""
        self.listing.controls = [self._row(e, restoring) for e in items] or [t.text(
            tr('saves.no_saves_yet_back_one_up_from_the_switch_or_add_a_sav_f_f68500', 'No saves yet. Back one up from the Switch, or add a .sav file')
            + (tr('saves.drop_it_here_9e09cb', ' (drop it here).') if drop.AVAILABLE else "."), 12, t.FAINT)]
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
            tooltip=tr('saves.more_d47d7c', 'More'), bgcolor=t.PANEL, menu_position=ft.PopupMenuPosition.UNDER, items=[
                item(tr('saves.rename_3064d7', 'Rename'), "label", lambda e, x=entry: self._rename(x)),
                item(tr('saves.export_sav_787996', 'Export .sav'), "save", lambda e, x=entry: self.app.page.run_task(self._export, x)),
                item(tr('saves.delete_e2d0a5', 'Delete'), "trash", lambda e, x=entry: self._delete(x))])
        tools = ft.Row([t.icon_button("edit", lambda e, x=entry: SaveEditor(self, x).open(),
                                      tr('saves.view_and_edit_183ce1', 'View and edit'), disabled=not entry.sound), menu], spacing=0)
        return ft.Container(ft.Row([
            *lead,
            ft.Column([t.text(entry.name, 13, weight=ft.FontWeight.W_600, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS), line,
                       t.text(date_time(entry.created), 11, t.FAINT)], spacing=1, expand=True),
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
            self.legality.content = t.badge(tr('saves.checking_the_party_with_pkhex_43d89c', 'Checking the party with PKHeX...'), t.BLUE, "refresh")
            self._check_party(path)
        elif check["error"]:
            self.legality.content = t.badge(tr('saves.pkhex_could_not_read_the_party_ca773e', 'PKHeX could not read the party: {value0}', value0=check['error']), t.AMBER,
                                            "warning-diamond")
        elif not check["illegal"]:
            self.legality.content = t.badge(tr('saves.every_pokemon_in_the_party_is_legal_b333ee', 'Every Pokemon in the party is legal.'), t.GREEN, "check")
        else:
            self.legality.content = ft.Row([
                ft.Column([t.text(tr('saves.restore_anyway_1ea70a', 'Restore anyway'), 13),
                           t.text(tr('saves.pkhex_finds_not_legal_0614f6', 'PKHeX finds {value0} not legal.', value0=', '.join(check['illegal'])), 12, t.AMBER)],
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
            self._say(tr('saves.added_29e842', 'Added {value0}.', value0=added.name) if added.sound else
                      tr('saves.added_but_neither_of_its_two_copies_is_whole_a72f5f', 'Added {value0}, but neither of its two copies is whole.', value0=added.name), t.MUTED)
        except (OSError, sav.SaveError) as exc:
            self._say(tr('saves._6a7768', '{value0}: {value1}', value0=os.path.basename(path), value1=exc), t.RED)
        self.refresh()

    async def _export(self, entry: saves.Entry) -> None:
        path = await self.app.picker.save_file(dialog_title=tr('saves.export_save_caac5b', 'Export save'), file_name=saves.file_name(entry),
                                               file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["sav"])
        if not path:
            return
        path += "" if path.lower().endswith(".sav") else ".sav"
        try:
            saves.export(entry, path)
            self._say(tr('saves.exported_to_58eb1e', 'Exported to {value0}', value0=path), t.MUTED)
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
            title=t.text(tr('saves.rename_the_save_42e82e', 'Rename the save'), 18), content=box,
            actions=[t.button(tr('saves.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('saves.rename_3064d7', 'Rename'), done)]))

    def _delete(self, entry: saves.Entry) -> None:
        def done(e):
            saves.delete(entry)
            self.app.page.pop_dialog()
            self.refresh()

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('saves.delete_this_save_7e73ab', 'Delete this save?'), 18),
            content=t.text(tr('saves.is_removed_from_this_computer_the_switch_keeps_its_own__409942', '{value0} is removed from this computer. The Switch keeps its own save.', value0=entry.name),
                           13, t.MUTED, width=380),
            actions=[t.button(tr('saves.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('saves.delete_e2d0a5', 'Delete'), done, color=t.RED)]))

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
        self.body = ft.Column([t.badge(tr('saves.reading_the_save_with_pkhex_bd9a31', 'Reading the save with PKHeX...'), t.BLUE, "refresh")], spacing=18,
                              scroll=ft.ScrollMode.AUTO, width=640, height=560)
        self.status = t.text("", 12, t.MUTED)
        self.save_button = t.button(tr('saves.keep_as_a_new_save_3655df', 'Keep as a new save'), self._save, disabled=True)

    def open(self) -> None:
        self.app.page.show_dialog(t.dialog(
            title=t.text(self.entry.name, 18), content=self.body,
            actions=[self.status, t.button(tr('saves.close_7d9eb7', 'Close'), lambda e: self.app.page.pop_dialog(), filled=False),
                     self.save_button]))
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            info = SERVICE.save_read(self.data)
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
        self.body.controls = [t.text(tr('saves.pkhex_could_not_read_this_save_c2d483', 'PKHeX could not read this save: {value0}', value0=message), 13, t.RED)]
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
                    e.control.error = tr('saves.a_number_a3c9df', 'A number')
                e.control.update()
            return t.field(value=str(self.trainer[key]), mono=True, width=130, digits=True,
                           limit=len(str(limit)), on_change=changed)

        name = t.field(value=self.trainer["name"], width=150, limit=7,
                       on_change=lambda e: self.trainer.__setitem__("name", e.control.value))
        gender = t.dropdown([("0", tr('saves.boy_96c58b', 'Boy')), ("1", tr('saves.girl_1499a1', 'Girl'))], str(self.trainer["gender"]),
                            on_select=lambda e: self.trainer.__setitem__("gender", int(e.control.value)), width=110)
        facts = (tr('saves.id_secret_id_h_badges_pokedex_caught_seen_7c4989', 'ID {value0:05d} · secret ID {value1:05d} · {value2} h {value3:02d} · {value4} badges · Pokedex {value5} caught, {value6} seen', value0=info['trainer_id'], value1=info['secret_id'], value2=info['hours'], value3=info['minutes'], value4=info['badges'], value5=info['caught'], value6=info['seen']))
        return t.section(tr('saves.trainer_9f085e', 'Trainer'), ft.Column([
            ft.Row([t.labeled_control(tr('saves.name_dcd1d5', 'Name'), name), t.labeled_control(tr('saves.gender_a04630', 'Gender'), gender),
                    t.labeled_control(tr('saves.money_5ccc2e', 'Money'), number("money", info["max_money"])),
                    t.labeled_control(tr('saves.coins_7ae57d', 'Coins'), number("coins", info["max_coins"]))], spacing=10),
            t.text(facts, 12, t.MUTED)], spacing=8))

    # Party

    def _party(self) -> ft.Control:
        rows = [self._party_row(n, slot) for n, slot in enumerate(self.party)]
        adder = ([t.secondary_button(tr('saves.add_a_pokemon_4efc62', 'Add a Pokemon'), self._add, "plus")] if len(self.party) < 6 else [])
        return t.section(tr('saves.party_dfa82f', 'Party'), ft.Column([*rows, *adder], spacing=6),
                         trailing=t.text(tr('saves.of_6_e4f06a', '{value0} of 6', value0=len(self.party)), 12, t.MUTED))

    def _party_row(self, n: int, slot: dict) -> ft.Control:
        mon = slot["info"]
        legal = mon["legal"]
        verdict = (t.pixel_icon("check", color=t.GREEN, tooltip=tr('saves.legal_4787ea', 'Legal')) if legal else
                   t.pixel_icon("warning-diamond", color=t.AMBER, tooltip=mon["report"][:600]))
        moves = ", ".join(mon["moves"])
        last = len(self.party) - 1
        tools = ft.Row([
            t.icon_button("chevron-up", lambda e: self._move(n, -1), tr('saves.earlier_e10ae9', 'Earlier'), disabled=n == 0),
            t.icon_button("chevron-down", lambda e: self._move(n, 1), tr('saves.later_73b6e4', 'Later'), disabled=n == last),
            t.icon_button("trash", lambda e: self._remove(n), tr('saves.remove_c3812f', 'Remove'), disabled=last == 0),
        ], spacing=0)
        return ft.Container(ft.Row([
            Sprite(self.app, int(mon["species_id"]), bool(mon["shiny"]), size=MINI).control,
            ft.Column([ft.Row([t.text(_mon_title(mon), 13, weight=ft.FontWeight.W_600), verdict], spacing=6),
                       t.text(moves or tr('saves.no_moves_6dbf63', 'No moves'), 12, t.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
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
                described = SERVICE.check_bytes("frlg", data)
            except Exception as exc:
                message = str(exc)
                self.app.ui(lambda: self._say(message, t.RED))
                return
            self.party.append({"data": described["data"], "info": described})
            self.app.ui(self.render)

        picker = PokemonPicker(self.app, "frlg", {}, built, version=version, trainer=owner)
        self.body.controls = [self._trainer(), self._party(),
                              t.section(tr('saves.new_pokemon_for_the_trainer_of_this_save_b2b47e', 'New Pokemon, for the trainer of this save'), picker.control),
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
                                          tooltip=_mon_title(m) + (tr('saves.egg_3e6a6c', ' · egg') if m["egg"] else ""))
                             for m in boxes[index]["mons"]] or [t.text(tr('saves.empty_c6c094', 'Empty'), 12, t.FAINT)]
            verdicts.controls = []
            if update:
                grid.update()
                verdicts.update()

        def check(e) -> None:
            index = chosen["box"]
            verdicts.controls = [t.badge(tr('saves.checking_with_pkhex_ddfdee', 'Checking with PKHeX...'), t.BLUE, "refresh")]
            verdicts.update()

            def work():
                try:
                    mons = SERVICE.save_box(self.data, index)
                    bad = [m for m in mons if m and not m["legal"]]
                    lines = [t.badge(tr('saves.lv_is_not_legal_079587', '{value0} (Lv {value1}) is not legal', value0=m['species'], value1=m['level']), t.AMBER, "warning-diamond")
                             for m in bad] or [t.badge(tr('saves.every_pokemon_in_this_box_is_legal_acd21c', 'Every Pokemon in this box is legal.'), t.GREEN, "check")]
                except Exception as exc:
                    lines = [t.text(str(exc), 12, t.RED)]
                self.app.ui(lambda: (setattr(verdicts, "controls", lines), verdicts.update())
                            if chosen["box"] == index else None)
            threading.Thread(target=work, daemon=True).start()

        picker = t.dropdown([(str(i), tr('saves._e11f55', '{value0} ({value1})', value0=b['name'], value1=len(b['mons']))) for i, b in enumerate(boxes)], "0",
                            on_select=lambda e: show(int(e.control.value)), width=220)
        show(0, update=False)
        return t.section(tr('saves.pc_boxes_8d864a', 'PC boxes'), ft.Column([
            ft.Row([picker, t.secondary_button(tr('saves.check_legality_ee0177', 'Check legality'), check, "shield")], spacing=10),
            grid, verdicts], spacing=8))

    # Save

    def _save(self, e) -> None:
        self.save_button.disabled = True
        self._say(tr('saves.writing_the_save_2b5979', 'Writing the save...'), t.MUTED)
        self.save_button.update()
        party = [{"keep": s["keep"]} if "keep" in s else {"data": s["data"]} for s in self.party]
        trainer = dict(self.trainer)

        def work():
            try:
                data, _info = SERVICE.save_edit(self.data, trainer=trainer, party=party)
                if not sav.describe(data).sound:
                    raise sav.SaveError(tr('saves.the_edited_save_did_not_pass_the_game_s_own_sector_chec_831cd5', "the edited save did not pass the game's own sector checks"))
                added = saves.add(data, source="edit", name=tr('saves.edited_ab28e1', '{value0} (edited)', value0=self.entry.name),
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
        self.panel._say(tr('saves.kept_as_the_original_is_unchanged_4e9261', 'Kept as {value0}. The original is unchanged.', value0=added.name), t.GREEN)

    def _say(self, text: str, color: str) -> None:
        self.status.value, self.status.color = text, color
        self.status.update()

"""The gift builder shared by the Mystery Gift tools: a preset, a gift built in a form, or an opened
file, then a summary of what the console gets. Each game's form lives in its builder module."""
from pokeldn.app.i18n import t as tr
from pokeldn.app import i18n

import asyncio
import copy
import os
import threading

import flet as ft

from gui import drop, theme as t
from gui.views.pokemon import NamePicker, pokemon_header
from gui.views.saves import SavePanel
from gui.views.sprites import MINI, SIZE, Sprite
from gui.views.widgets import PathField, PixelActivity
from gui.localization import SERVICE, error_message, gift_description, translate
from pokeldn import gifts, pokemon
from pokeldn.app import command, gift_builder, gift_files, saves
from pokeldn.frlg.gift import builder as frlg
from pokeldn.frlg.rom import custom_code
from pokeldn.swsh import gift_builder as swsh, wc8

def species_frlg():
    """FRLG's species by cartridge id: PKHeX's names in the pack's language, else the offline list."""
    if i18n.locale() != "en":
        try:
            return SERVICE.names("frlg", "species3")
        except (pokemon.BuilderError, OSError):
            pass
    return [{"id": n, "name": translate(name)} for n, name in frlg.species_names()]


def _number(value, default=0):
    # Decimal first: base 0 refuses a leading zero ("025").
    text = str(value).strip() or str(default)
    for base in (10, 0):
        try:
            return int(text, base)
        except ValueError:
            pass
    return default


def _chips(choices, value, on_change) -> ft.Row:
    """A row of pickable capsules, one per (value, label)."""
    row = ft.Row(spacing=6, wrap=True, run_spacing=6)

    def render(selected):
        row.controls = [ft.Container(
            t.text(translate(label), 12, t.TEXT if key == selected else t.MUTED, weight=ft.FontWeight.W_600),
            padding=ft.Padding(12, 6, 12, 6), border_radius=15,
            border=ft.Border.all(1, t.BLUE if key == selected else t.BORDER),
            bgcolor=t.SELECTED if key == selected else None, on_click=lambda e, k=key: pick(k))
            for key, label in choices]

    def pick(key):
        render(key)
        row.update()
        on_change(key)

    render(value)
    return row


class GiftBuilder:
    def __init__(self, games, field):
        self.games, self.field = games, field
        self.app, self.tool = games.app, games.tool
        self.game = gift_builder.GAMES[self.tool.key]
        self.module = gift_builder.module(self.game)
        self.value = gift_builder.normalized(self.game, command.value_of(field, games.values))
        self.when = t.text("", 12, t.MUTED)
        self.effects = ft.Column(spacing=4)
        self.status = t.text("", 12, t.MUTED)
        self.save_button = t.secondary_button(tr('gifts.save_gift_file_982b49', 'Save gift file'), self._save, "download")
        self.previews = []
        self.forms = None

    # State

    @property
    def state(self) -> dict:
        return self.value["build"]

    def commit(self, rebuild=False) -> None:
        self.games.set_value(self.field, self.value, rebuild=rebuild)
        if not rebuild:
            self.show_summary(update=True)

    def edit(self, key, value, rebuild=False, target=None) -> None:
        (self.state if target is None else target)[key] = value
        if not rebuild and key in ("species", "icon", "form", "shiny"):
            for sprite, values in self.previews:
                species, shiny, form = values()
                sprite.show(species, shiny, form=form)
        self.commit(rebuild)

    # Cards

    def cards(self) -> list[ft.Control]:
        self.previews = []
        self.forms = None
        mode = self.value["mode"]
        modes = t.segmented([(key, translate(label), icon) for key, label, icon in gift_builder.modes(self.game)],
                            mode, self._mode, wrap=True)
        body = {"preset": self.presets, "event": self.events, "build": self.editor, "file": self.file,
                "save": lambda: SavePanel(self).control()}[mode]()
        self.show_summary()
        if mode == "save":
            summary = ft.Column([self.when, self.effects, self.status], spacing=10)
            return [t.card(tr('gifts.gift_1a596a', 'Gift'), ft.Column([modes, body], spacing=14)), t.card(tr('gifts.before_you_start_74e492', 'Before you start'), summary)]
        actions = [self.save_button]
        if (mode == "preset" and self.module.PRESET[self.value["preset"]].state is not None
                and any(m[0] == "build" for m in gift_builder.modes(self.game))):
            actions.insert(0, t.secondary_button(tr('gifts.customize_c5276e', 'Customize'), self._customize, "sliders-horizontal"))
        summary = ft.Column([self.when, self.effects, self.status,
                             ft.Row(actions, alignment=ft.MainAxisAlignment.END)], spacing=10)
        gift = drop.target(t.card(tr('gifts.gift_1a596a', 'Gift'), ft.Column([modes, body], spacing=14)), self._dropped)
        return [gift, t.card(tr('gifts.before_you_send_c1a8a2', 'Before you send'), summary)]

    def exts(self) -> tuple[str, ...]:
        return ("pokegift", "wc8") if self.game == "swsh" else ("pokegift", "wc3")

    def _dropped(self, paths: list[str]) -> None:
        """A gift file dropped anywhere on the card opens it."""
        path = next((p for p in paths if drop.suffix(p) in self.exts()), "")
        if path:
            self.value["mode"], self.value["file"] = "file", path
            self.commit(rebuild=True)

    def _mode(self, key) -> None:
        self.value["mode"] = key
        self.commit(rebuild=True)

    def presets(self) -> ft.Control:
        groups: dict[str, list] = {}
        for preset in self.module.PRESETS:
            groups.setdefault(preset.group, []).append(preset)
        selected = self.module.PRESET[self.value["preset"]]
        sections = []
        for group, items in groups.items():
            tiles, body = [], []
            for preset in items:
                if not hasattr(preset, "members"):
                    tiles.append(self._tile(translate(preset.label), translate(preset.summary), preset is selected,
                                            lambda e, k=preset.key: self._pick(k),
                                            species_id=preset.species_id, shiny=getattr(preset, "shiny", False),
                                            form=preset.state.get("form", 0) if self.game == "swsh" else 0))
                    continue
                on = preset.settings(self.value["options"].get(preset.key))["on"] if preset is selected else []
                tiles += [self._tile(translate(b.label), translate(b.summary), b.key in on, lambda e, p=preset, k=b.key: self._toggle(p, k),
                                     settings=bool(b.options)) for b in preset.members]
                if on:
                    body.append(self.boost_settings(preset))
            body.insert(0, t.grid(tiles))
            intro = getattr(self.module, "GROUP_INTROS", {}).get(group, "")
            if intro:
                body.insert(0, t.text(translate(intro), 12, t.MUTED))
            sections.append(t.section(translate(group), ft.Column(body, spacing=10)))
        return ft.Column(sections, spacing=14)

    def _tile(self, label, summary, active, on_click, settings=False, warning="", species_id=0,
              shiny=False, form=0) -> ft.Control:
        """The preset's name and full description, including any steps needed to use it. A `warning`
        tile has an amber outline, chosen or not, and says why."""
        head = [t.text(translate(label), 13, weight=ft.FontWeight.W_600, expand=True)]
        if settings:
            head.append(t.pixel_icon("sliders-horizontal", color=t.BLUE if active else t.FAINT,
                                     tooltip=tr('gifts.has_settings_8e00a4', 'Has settings')))
        lines = [ft.Row(head, spacing=6), t.text(translate(summary), 12, t.MUTED)]
        if warning:
            lines.append(ft.Row([t.pixel_icon("warning-diamond", size=12, color=t.AMBER),
                                 t.text(translate(warning), 12, t.AMBER, expand=True)], spacing=6))
        return ft.Container(ft.Row([
            t.pixel_icon("checkbox-on" if active else "checkbox", color=t.BLUE if active else t.FAINT),
            *([Sprite(self.app, species_id, shiny, size=MINI, form=form).control] if species_id else []),
            ft.Column(lines, spacing=1, expand=True),
        ], spacing=10), padding=ft.Padding(10, 8, 10, 8), border_radius=10,
            tooltip=translate(summary), border=ft.Border.all(1, t.AMBER if warning else t.BLUE if active else t.BORDER),
            bgcolor=t.SELECTED if active else None, on_click=on_click)

    def _toggle(self, preset, key) -> None:
        """Tick or untick a boost; the first tick from another gift starts the set with that one."""
        chosen = preset.settings(self.value["options"].get(preset.key))
        if self.value["preset"] != preset.key:
            chosen["on"] = [key]
        elif key in chosen["on"]:
            chosen["on"].remove(key)
        else:
            chosen["on"].append(key)
        self.value["preset"], self.value["options"][preset.key] = preset.key, chosen
        self.commit(rebuild=True)

    def boost_settings(self, preset) -> ft.Control:
        """A panel per ticked boost with settings, then the save switch and the room they take."""
        chosen = preset.settings(self.value["options"].get(preset.key))
        self.value["options"][preset.key] = chosen
        panels = []
        for boost in preset.members:
            if boost.key not in chosen["on"] or not boost.options:
                continue
            mine = chosen[boost.key]
            rows = []
            for option in boost.options:
                if not option.choices:
                    rows.append(self.switch_row(translate(option.label), option.key, translate(option.help), mine))
                elif all(len(label) <= 24 for _, label in option.choices):
                    rows.append(t.labeled_control(translate(option.label), _chips(
                        option.choices, mine[option.key], lambda v, k=option.key, m=mine: self.edit(k, v, target=m))))
                else:
                    rows.append(t.labeled_control(translate(option.label), t.dropdown(
                        [(key, translate(label)) for key, label in option.choices], mine[option.key],
                        on_select=lambda e, k=option.key, m=mine: self.edit(k, e.control.value, target=m))))
            panels.append(ft.Container(ft.Column([t.text(translate(boost.label), 13, weight=ft.FontWeight.W_600), *rows],
                                                 spacing=12),
                                       padding=14, border_radius=10, border=ft.Border.all(1, t.BORDER)))
        used, room = preset.size(chosen), frlg.RESIDENT_AREA
        try:
            too_large = preset.built(chosen)[2]
        except ValueError:
            too_large = False
        keep = (t.text(tr('gifts.these_boosts_are_always_saved_in_your_game_926042', 'These boosts are always saved in your game. ') + translate(frlg.MOM_STEPS), 12, t.MUTED)
                if too_large or "hook-follower" in chosen["on"]
                else self.switch_row(translate(frlg.KEEP.label), "keep", translate(frlg.KEEP.help), chosen))
        meter = ft.Column([
            ft.Row([t.text(tr('gifts.room_on_the_console_3abe6a', 'Room on the console'), 12, t.MUTED, expand=True),
                    t.text(tr('gifts.of_bytes_b7e7e0', '{value0} of {value1} bytes', value0=used, value1=room), 12, t.RED if used > room else t.MUTED)]),
            ft.ProgressBar(value=min(used / room, 1), color=t.RED if used > room else t.BLUE,
                           bgcolor=t.BORDER, bar_height=4, border_radius=2)], spacing=4)
        common = ft.Container(ft.Column([keep, meter, t.text(
            tr('gifts.the_selected_boosts_run_together_sending_a_new_selectio_2e5352', 'The selected boosts run together. Sending a new selection replaces the boosts already running.'),
            12, t.MUTED)],
            spacing=12), padding=14, border_radius=10, border=ft.Border.all(1, t.BORDER))
        return ft.Column([*panels, common], spacing=10)

    def _pick(self, key) -> None:
        self.value["preset"] = key
        self.commit(rebuild=True)

    # Official events

    def events(self) -> ft.Control:
        """Every official card the game's builder ships, filtered by a search and a group."""
        official = self.module.OFFICIAL
        cards = official.load()
        tiles = ft.Column(spacing=6, tight=True)
        search = t.field(hint=tr('gifts.search_pikachu_master_ball_shiny_297ed3', 'Search: Pikachu, Master Ball, shiny...'), value=self.value.get("event_search", ""))
        group = {"value": self.value.get("event_group", "")}

        def render(update=True):
            words = translate(search.value).casefold().split()
            shown = [c for c in cards if (not group["value"] or c["group"] == group["value"])
                     and all(w in tr('gifts._8320f6', '{value0} {value1} {value2}', value0=translate(c['label']), value1=translate(c['group']), value2=translate(c['summary'])).casefold() for w in words)]
            tiles.controls = t.grid_rows([self._event_tile(c) for c in shown])
            count.value = tr('gifts.of_cards_d600f0', '{value0} of {value1} cards', value0=len(shown), value1=len(cards))
            if update:
                tiles.update()
                count.update()

        def filtered(key, value):
            self.value[key] = value
            if key == "event_group":
                group["value"] = value
            render()

        search.on_change = lambda e: filtered("event_search", search.value)
        count = t.text("", 12, t.MUTED)
        render(update=False)
        groups = _chips([("", tr('gifts.all_a52ace', 'All'))] + [(g, translate(g)) for g in official.GROUPS], group["value"],
                        lambda k: filtered("event_group", k))
        intro = t.text(tr('gifts.real_event_cards_from_the_projectpokemon_eventsgallery__1172ec', "Real event cards from the projectpokemon EventsGallery archive, and under Pokemon HOME the community's cards of the gifts Pokemon HOME gave. Each one passed the game's own card check."), 12, t.MUTED)
        listing = ft.Container(ft.Column([tiles], scroll=ft.ScrollMode.AUTO), height=440)
        return ft.Column([intro, search, groups, count, listing, self._event_card_id()], spacing=10)

    def _event_card_id(self) -> ft.Control:
        """The chosen card's id: a save takes a once-only card once per id, so cards sharing one need
        their own [docs/swsh_gift.md, Cards that share an id]."""
        key, official = self.value["event"], self.module.OFFICIAL
        ids = self.value["event_ids"]
        shown = ids.get(key, official.card_id(official.by_key()[key]["record"]))

        def changed(e):
            ids[key] = _number(e.control.value)
            self.commit()

        box = t.field(value=str(shown), mono=True, width=96, digits=True, on_change=changed)
        return ft.Row([t.labeled_control(tr('gifts.card_id_30f8dc', 'Card id'), box),
                       t.text(tr('gifts.change_it_to_receive_a_card_that_shares_its_id_with_one_aad698', 'Change it to receive a card that shares its id with one the save already took.'),
                              12, t.MUTED, expand=True)], spacing=10,
                      vertical_alignment=ft.CrossAxisAlignment.END)

    def _event_tile(self, card) -> ft.Control:
        raw = card["record"]
        mon = wc8.read(raw) if raw[wc8.GIFT_KIND_AT] == wc8.GIFT_KIND_POKEMON else {}
        return self._tile(translate(card["label"]), card["summary"], card["key"] == self.value["event"],
                          lambda e: self._event(card["key"]),
                          warning=pokemon.HOME_TRACKER_WARNINGS["empty"]
                          if self.module.OFFICIAL.from_home(raw) else "",
                          species_id=mon.get("species", 0), shiny=mon.get("shiny_type") in (2, 3),
                          form=mon.get("form", 0))

    def _event(self, key) -> None:
        self.value["event"] = key
        self.commit(rebuild=True)

    def _customize(self, e) -> None:
        self.value["build"] = copy.deepcopy(self.module.PRESET[self.value["preset"]].state)
        self.value["mode"] = "build"
        self.commit(rebuild=True)

    def file(self) -> ft.Control:
        path = PathField(self.app.picker, lambda: os.path.expanduser("~"), self.value["file"], "file",
                         self.exts(), self._file, single_line=True, droppable=False)
        controls = [t.text(tr('gifts.a_pokegift_someone_shared_or_a_8f64fa', 'A .pokegift someone shared, or a ') + (tr('gifts.sword_shield_wc8_b6cb88', 'Sword/Shield .wc8') if self.game == "swsh"
                                                                  else ".wc3") + tr('gifts.wonder_card_c0de36', ' Wonder Card.'), 12, t.MUTED),
                    path.control]
        if self.game == "frlg":
            icon = NamePicker(self.app, self.game, "species", str(self.value.get("icon") or ""),
                              self._icon, optional=True, names=species_frlg)
            controls.append(t.labeled_control(tr('gifts.card_icon_ff0491', 'Card icon'), icon.control))
            controls.append(t.text(tr('gifts.leave_empty_to_keep_the_file_s_own_icon_ada4a7', "Leave empty to keep the file's own icon."), 12, t.MUTED))
        return ft.Column(controls, spacing=8)

    def _icon(self, value) -> None:
        number = _number(value)
        self.value["icon"] = number if number else None
        self.commit()

    def _file(self, path) -> None:
        self.value["file"] = path
        self.commit()

    # Build your own

    def editor(self) -> ft.Control:
        self.previews = []
        kind = self.state.get("kind")
        kinds = t.segmented([(key, translate(label), icon) for key, label, icon in self.module.KINDS],
                            kind, lambda k: self.edit("kind", k, rebuild=True))
        form = getattr(self, f"{self.game}_{kind}")()
        return ft.Column([kinds, form], spacing=14)

    def text_field(self, label, key, target=None, width=None, **kwargs) -> ft.Control:
        target = self.state if target is None else target
        box = t.field(value=str(target.get(key, "")), on_change=lambda e: self.edit(key, e.control.value,
                                                                                     target=target),
                      expand=width is None, width=width, **kwargs)
        return t.labeled_control(label, box, expand=width is None)

    def number_field(self, label, key, target=None, width=96) -> ft.Control:
        target = self.state if target is None else target
        box = t.field(value=str(target.get(key, "")), mono=True, width=width, digits=True,
                      on_change=lambda e: self.edit(key, _number(e.control.value), target=target))
        return t.labeled_control(label, box)

    def name_field(self, label, kind, key, target=None, optional=True, preview=False) -> ft.Control:
        target = self.state if target is None else target
        names = species_frlg if self.game == "frlg" and kind == "species" else None

        def changed(value):
            if self.game == "swsh" and kind == "species":
                target["form"] = 0
                self.edit(key, _number(value), target=target)
                self._load_forms()
            else:
                self.edit(key, _number(value), target=target)

        picker = NamePicker(self.app, self.game, kind, str(target.get(key) or ""),
                            changed, optional=optional, names=names)
        field = t.labeled_control(label, picker.control, expand=True)
        if kind != "species" or not preview:
            return field
        return ft.Row([field, self.pokemon_preview(target, key)], spacing=10, expand=True,
                      vertical_alignment=ft.CrossAxisAlignment.END)

    def pokemon_preview(self, target, key="species", size=MINI) -> ft.Control:
        def values():
            species = _number(target.get(key))
            if self.game == "frlg":
                return frlg.national_species(species), False, 0
            return species, target.get("kind") == "pokemon" and bool(target.get("shiny")), _number(target.get("form"))

        species, shiny, form = values()
        sprite = Sprite(self.app, species, shiny, size=size, form=form)
        self.previews.append((sprite, values))
        return sprite.control

    def switch_row(self, label, key, help_, target=None) -> ft.Control:
        target = self.state if target is None else target
        return ft.Row([ft.Column([t.text(label, 13), t.text(help_, 12, t.MUTED)], spacing=1, expand=True),
                       t.switch(bool(target.get(key)), lambda e: self.edit(key, e.control.value, target=target))])

    def moves(self, target) -> ft.Control:
        target.setdefault("moves", [0, 0, 0, 0])

        def picker(n):
            def changed(v):
                target["moves"][n] = _number(v)
                self.commit()
            return t.labeled_control(tr('gifts.move_74d4b9', 'Move {value0}', value0=n + 1), NamePicker(
                self.app, self.game, "move", str(target["moves"][n] or ""), changed).control, expand=True)
        return ft.Column([ft.Row([picker(0), picker(1)], spacing=10), ft.Row([picker(2), picker(3)], spacing=10)],
                         spacing=10)

    # FireRed / LeafGreen

    def frlg_card(self) -> ft.Control:
        card = self.state["card"]
        body = card.setdefault("body", ["", "", "", ""])

        def line(n):
            def changed(e):
                body[n] = e.control.value
                self.commit()
            return t.field(value=body[n], hint=tr('gifts.line_751dfd', 'Line {value0}', value0=n + 1), on_change=changed)
        giver = t.dropdown([(key, tr('gifts._c55f6a', '{value0}, {value1}', value0=translate(who), value1=translate(where))) for key, who, where, *_ in frlg.GIVERS],
                           self.state.get("giver", "deliveryman"),
                           on_select=lambda e: self.edit("giver", e.control.value, rebuild=True))
        card_form = ft.Column([
            ft.Row([self.text_field(tr('gifts.title_7e8cd2', 'Title'), "title", card), self.text_field(tr('gifts.subtitle_383cd6', 'Subtitle'), "subtitle", card)],
                   spacing=10),
            t.labeled_control(tr('gifts.text_on_the_card_62dee6', 'Text on the card'), ft.Column([line(n) for n in range(4)], spacing=6,
                                                            horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            ft.Row([self.name_field(tr('gifts.icon_a35abc', 'Icon'), "species", "icon", card, optional=False, preview=True),
                    self.number_field(tr('gifts.card_id_30f8dc', 'Card id'), "flag_id", card)], spacing=10),
            self.switch_row(tr('gifts.can_be_received_again_485c28', 'Can be received again'), "repeatable", tr('gifts.otherwise_once_per_save_5be50f', 'Otherwise once per save.'), card),
            self.switch_row(tr('gifts.the_player_can_share_it_7fc5a1', 'The player can share it'), "shareable", tr('gifts.mystery_gift_wonder_cards_send_ffe082', 'Mystery Gift, Wonder Cards, Send.'), card),
        ], spacing=10)
        return ft.Column([
            t.section(tr('gifts.the_card_f658d7', 'The card'), card_form),
            t.section(tr('gifts.who_hands_it_over_8dadaf', 'Who hands it over'), giver),
            t.section(tr('gifts.what_happens_70fbb5', 'What happens'), self.frlg_steps()),
        ], spacing=18)

    def frlg_steps(self) -> ft.Control:
        steps = self.state["steps"]
        rows = [self.frlg_step(n, step) for n, step in enumerate(steps)]
        adders = ft.Row([t.secondary_button(translate(label), lambda e, k=key: self._add_step(k), "plus")
                         for key, label in frlg.STEPS], spacing=6, wrap=True, run_spacing=6)
        return ft.Column([*rows, adders], spacing=10)

    def frlg_step(self, n, step) -> ft.Control:
        kind = step["type"]
        label = translate(dict(frlg.STEPS)[kind])
        if kind in ("pokemon", "battle"):
            fields = [ft.Row([self.name_field(tr('gifts.species_56205e', 'Species'), "species", "species", step, optional=False),
                              self.number_field(tr('gifts.level_170930', 'Level'), "level", step, 72),
                              self.name_field(tr('gifts.held_item_6af4a4', 'Held item'), "item", "item", step)], spacing=10)]
            if kind == "pokemon":
                fields.append(self.moves(step))
        elif kind == "egg":
            fields = [self.name_field(tr('gifts.species_56205e', 'Species'), "species", "species", step, optional=False)]
        elif kind == "item":
            fields = [ft.Row([self.name_field(tr('gifts.item_652bcc', 'Item'), "item", "item", step, optional=False),
                              self.number_field(tr('gifts.how_many_e2a6ff', 'How many'), "quantity", step, 72)], spacing=10)]
        else:
            fields = [self.text_field(tr('gifts.message_2f7766', 'Message'), "text", step, multiline=True, min_lines=2, max_lines=4,
                                      hint=tr('gifts.is_the_player_s_name_a_box_holds_two_lines_092815', "{{PLAYER}} is the player's name. A box holds two lines."))]
        if kind in ("pokemon", "battle", "egg"):
            fields = [pokemon_header(self.pokemon_preview(step, size=SIZE), fields, spacing=10)]
        tools = ft.Row([t.icon_button("chevron-up", lambda e: self._move_step(n, -1), tr('gifts.earlier_e10ae9', 'Earlier'), disabled=n == 0),
                        t.icon_button("chevron-down", lambda e: self._move_step(n, 1), tr('gifts.later_73b6e4', 'Later'),
                                      disabled=n == len(self.state["steps"]) - 1),
                        t.icon_button("close", lambda e: self._remove_step(n), tr('gifts.remove_c3812f', 'Remove'))], spacing=0)
        head = ft.Row([t.text(tr('gifts._04903a', '{value0}. {value1}', value0=n + 1, value1=label), 12, t.SOFT, weight=ft.FontWeight.W_600, expand=True), tools],
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)
        return ft.Container(ft.Column([head, *fields], spacing=8), padding=12, border_radius=10,
                            border=ft.Border.all(1, t.BORDER))

    def _add_step(self, kind) -> None:
        defaults = {"pokemon": {"species": 25, "level": 5, "item": 0, "moves": [0, 0, 0, 0]},
                    "battle": {"species": 25, "level": 5, "item": 0}, "egg": {"species": 25},
                    "item": {"item": 1, "quantity": 1}, "message": {"text": tr('gifts.here_you_go_fdf6dd', 'Here you go!')}}
        self.state["steps"].append({"type": kind, **defaults[kind]})
        self.commit(rebuild=True)

    def _move_step(self, n, delta) -> None:
        steps = self.state["steps"]
        steps[n], steps[n + delta] = steps[n + delta], steps[n]
        self.commit(rebuild=True)

    def _remove_step(self, n) -> None:
        del self.state["steps"][n]
        self.commit(rebuild=True)

    def frlg_news(self) -> ft.Control:
        news = self.state["news"]

        def lines(e):
            news["lines"] = e.control.value.split("\n")[:10]
            self.commit()
        return ft.Column([
            ft.Row([self.text_field(tr('gifts.title_7e8cd2', 'Title'), "title", news), self.number_field(tr('gifts.news_id_2db350', 'News id'), "id", news)], spacing=10),
            t.labeled_control(tr('gifts.text_up_to_ten_lines_0286f4', 'Text, up to ten lines'), t.field(value="\n".join(news.get("lines", ())),
                                                               multiline=True, min_lines=4, max_lines=10,
                                                               on_change=lines)),
            t.text(tr('gifts.a_console_keeps_news_only_when_it_differs_from_the_one__1cae11', 'A console keeps news only when it differs from the one it holds; change the id to send the same text again.'), 12, t.MUTED),
        ], spacing=10)

    def frlg_code(self) -> ft.Control:
        code = self.state["code"]
        self.check_line = t.text("", 12, t.MUTED)
        self.hex_view = t.text("", 11, t.SOFT, font_family=t.MONO, selectable=True)
        source = t.field(value=code.get("source", ""), mono=True, multiline=True, min_lines=10, max_lines=24,
                         on_change=lambda e: code.__setitem__("source", e.control.value),
                         on_blur=lambda e: self.commit())
        binary = PathField(self.app.picker, lambda: os.path.expanduser("~"), code.get("binary", ""), "file",
                           ("bin",), lambda v: self.edit("binary", v, target=code), single_line=True)
        return ft.Column([
            t.text(tr('gifts.arm_code_runs_on_the_console_while_it_receives_every_fr_bdf000', 'ARM code runs on the console while it receives, every frame until it returns 1. A fault or a loop hangs the Mystery Gift menu, so it is run offline first.'), 12, t.MUTED),
            t.labeled_control(tr('gifts.assembly_44e7d4', 'Assembly'), source, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            self._toolchain_status(),
            t.labeled_control(tr('gifts.or_a_prebuilt_bin_used_instead_of_the_assembly_6adf72', 'Or a prebuilt .bin (used instead of the assembly)'), binary.control),
            ft.Row([t.labeled_control(tr('gifts.built_for_0ae12b', 'Built for'), t.dropdown(
                        [("any", tr('gifts.any_cartridge_2415bb', 'Any cartridge'))] + [(key, translate(label)) for key, label in frlg.CARTRIDGES.items()], code.get("build") or "any",
                        on_select=lambda e: self.edit("build", "" if e.control.value == "any" else e.control.value,
                                                      target=code)), expand=True),
                    self.text_field(tr('gifts.expected_answer_1b00cc', 'Expected answer'), "expect", code, width=140, hint=tr('gifts.any_d6a7cd', 'any')),
                    self.text_field(tr('gifts.bytes_sent_back_ae5ec8', 'Bytes sent back'), "dump_size", code, width=140, hint="4")], spacing=10),
            ft.Row([t.secondary_button(tr('gifts.check_offline_cf1ff9', 'Check offline'), self._check, "play"), ft.Container(self.check_line,
                                                                                            expand=True)]),
            self.hex_view,
        ], spacing=10)

    def _toolchain_status(self) -> ft.Control:
        if custom_code.toolchain():
            return t.text(tr('gifts.assembled_with_the_gnu_arm_toolchain_on_this_computer_4aacfc', 'Assembled with the GNU Arm toolchain on this computer.'), 12, t.MUTED)
        command, page = custom_code.install_hint()
        run = self.app.page.run_task
        if command:
            how = ft.Row([ft.Container(t.text(command, 12, t.TEXT, font_family=t.MONO, selectable=True),
                                       expand=True),
                          t.icon_button("copy", lambda e: run(self.app.copy, command), tr('gifts.copy_e21f93', 'Copy'))],
                         vertical_alignment=ft.CrossAxisAlignment.CENTER)
            steps = tr('gifts.paste_this_in_a_terminal_then_check_again_e7a94c', 'paste this in a terminal, then check again')
        else:
            how, steps = None, tr('gifts.download_it_from_arm_s_page_then_check_again_0aaf5e', "download it from Arm's page, then check again")
        actions = ft.Row([t.secondary_button(tr('gifts.check_again_fb7099', 'Check again'), lambda e: self.commit(rebuild=True), "refresh"),
                          t.link_button(tr('gifts.homebrew_bc49b9', 'Homebrew') if page == "https://brew.sh" else tr('gifts.arm_s_download_page_2fdb32', "Arm's download page"),
                                        lambda e: run(self.app.open_url, page))], spacing=8)
        return t.surface(ft.Column([
            t.text(tr('gifts.assembler_install_hint', 'Typing assembly here needs the free GNU Arm assembler. Install it once: {value0}. A prebuilt .bin works without it.', value0=steps), 12, t.AMBER),
            *([how] if how else []), actions], spacing=8), padding=12)

    def _check(self, e) -> None:
        self.check_line.value, self.check_line.color = tr('gifts.checking_ec963f', 'Checking…'), t.MUTED
        self.check_line.update()
        code_state = dict(self.state["code"])

        def run():
            try:
                code = frlg.code_bytes(code_state)
                result, color = translate(frlg.checked(code).describe()), t.GREEN
                dump = "\n".join(code[i:i + 16].hex(" ") for i in range(0, min(len(code), 256), 16))
            except (OSError, ValueError) as exc:
                result, color, dump = error_message(exc), t.RED, ""

            def show():
                self.check_line.value, self.check_line.color, self.hex_view.value = result, color, dump
                self.check_line.update()
                self.hex_view.update()
            self.app.ui(show)
        threading.Thread(target=run, daemon=True).start()

    # Sword / Shield

    def swsh_pokemon(self, egg=False) -> ft.Control:
        self.forms = ft.Container()
        fields = [self.name_field(tr('gifts.species_56205e', 'Species'), "species", "species", optional=False)]
        if not egg:
            fields += [self.number_field(tr('gifts.level_170930', 'Level'), "level", width=90),
                       t.labeled_control(tr('gifts.shiny_039a0a', 'Shiny'), ft.Container(
                           t.switch(bool(self.state.get("shiny")),
                                    lambda e: self.edit("shiny", e.control.value)),
                           width=64, height=t.CONTROL_HEIGHT, alignment=ft.Alignment.CENTER))]
        header = [ft.Row(fields, spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)]
        if not egg:
            header.append(ft.Row([self.text_field(tr('gifts.nickname_d720f6', 'Nickname'), "nickname", limit=12),
                                  self.text_field(tr('gifts.ot_c2d4fe', 'OT'), "ot", limit=12)], spacing=10))
        rows = [pokemon_header(self.pokemon_preview(self.state, size=SIZE), header, spacing=10), self.forms]
        self._load_forms()
        if not egg:
            rows += [ft.Row([self.name_field(tr('gifts.held_item_6af4a4', 'Held item'), "bag", "item"), self.name_field(tr('gifts.ball_ae5859', 'Ball'), "ball", "ball")],
                            spacing=10),
                     t.labeled_control(tr('gifts.nature_c71ce8', 'Nature'), t.dropdown(
                         [("random", tr('gifts.random_67bc48', 'Random'))] + [(str(n), name) for n, name in enumerate(pokemon.NATURES)],
                         "random" if self.state.get("nature") is None else str(self.state["nature"]),
                         on_select=lambda e: self.edit("nature", None if e.control.value == "random"
                                                       else int(e.control.value)))),
                     self.switch_row(tr('gifts.gigantamax_b91de1', 'Gigantamax'), "gigantamax", tr('gifts.it_can_gigantamax_a_species_with_a_gigantamax_form_or_o_b3bf91', 'It can Gigantamax: a species with a Gigantamax form, or one that evolves into one.'))]
        rows += [self.moves(self.state), self.number_field(tr('gifts.card_id_30f8dc', 'Card id'), "card_id")]
        return ft.Column(rows, spacing=10)

    def _load_forms(self) -> None:
        """Read game form choices off the UI thread; discard replies for an old editor or species."""
        box, state = self.forms, self.state
        species = _number(state.get("species"))
        request = box.data = object()
        if not species:
            box.content = None
            return
        box.content = ft.Row([PixelActivity(tr('gifts.loading_forms_e3b50e', 'Loading forms')),
                              t.text(tr('gifts.reading_what_this_species_can_have_bdcc50', 'Reading what this species can have...'), 12, t.MUTED)], spacing=8)
        try:
            box.update()
        except RuntimeError:
            pass

        def work():
            try:
                forms = SERVICE.options(self.game, species, self.app.settings.trainer(self.game))["forms"]
                error = ""
            except Exception as exc:
                forms, error = [], error_message(exc) or type(exc).__name__

            def show():
                if (self.forms is not box or box.data is not request or self.state is not state
                        or _number(state.get("species")) != species):
                    return
                if error:
                    box.content = t.text(error, 12, t.RED, selectable=True)
                else:
                    if forms and _number(state.get("form")) not in {f["id"] for f in forms}:
                        self.edit("form", forms[0]["id"])
                    box.content = (t.labeled_control(tr('gifts.form_2e0e96', 'Form'), t.dropdown(
                        [(str(f["id"]), f["name"] or tr('gifts.normal_a7248e', 'Normal')) for f in forms],
                        str(_number(state.get("form"))),
                        on_select=lambda e: self.edit("form", int(e.control.value))))
                        if len(forms) > 1 else None)
                try:
                    box.update()
                except RuntimeError:
                    pass
            self.app.ui(show)
        threading.Thread(target=work, daemon=True).start()

    def swsh_egg(self) -> ft.Control:
        return self.swsh_pokemon(egg=True)

    def swsh_items(self) -> ft.Control:
        items = self.state.setdefault("items", [[1, 1]])

        def row(n):
            def item(v):
                items[n][0] = _number(v)
                self.commit()

            def quantity(e):
                items[n][1] = _number(e.control.value)
                self.commit()

            def remove(e):
                del items[n]
                self.commit(rebuild=True)
            return ft.Row([t.labeled_control(tr('gifts.item_652bcc', 'Item'), NamePicker(self.app, "swsh", "bag", str(items[n][0] or ""),
                                                                item, optional=False).control, expand=True),
                           t.labeled_control(tr('gifts.how_many_e2a6ff', 'How many'), t.field(value=str(items[n][1]), mono=True, width=72, digits=True,
                                                                 on_change=quantity)),
                           ft.Container(t.icon_button("close", remove, tr('gifts.remove_c3812f', 'Remove')), height=t.CONTROL_HEIGHT,
                                        alignment=ft.Alignment.CENTER)],
                          spacing=10, vertical_alignment=ft.CrossAxisAlignment.END)

        def add(e):
            items.append([1, 1])
            self.commit(rebuild=True)
        adder = [t.secondary_button(tr('gifts.add_an_item_d94420', 'Add an item'), add, "plus")] if len(items) < 6 else []
        return ft.Column([*(row(n) for n in range(len(items))), *adder, self.number_field(tr('gifts.card_id_30f8dc', 'Card id'), "card_id")],
                         spacing=10)

    def swsh_clothing(self) -> ft.Control:
        chosen = self.state.setdefault("outfits", [])

        def toggle(key, on):
            if on and key not in chosen:
                chosen.append(key)
            elif not on and key in chosen:
                chosen.remove(key)
            self.commit()
        rows = [ft.Row([t.text(translate(o.label), 13, expand=True),
                        t.switch(o.key in chosen, lambda e, k=o.key: toggle(k, e.control.value))])
                for o in swsh.OUTFITS]
        return ft.Column([t.text(tr('gifts.official_outfits_a_card_holds_six_pieces_for_each_gende_160ef4', 'Official outfits. A card holds six pieces for each gender; the player gets the version for their own.'), 12, t.MUTED), *rows,
                          self.number_field(tr('gifts.card_id_30f8dc', 'Card id'), "card_id")], spacing=8)

    def swsh_money(self) -> ft.Control:
        return ft.Row([self.number_field(tr('gifts.money_5ccc2e', 'Money'), "money", width=120), self.number_field(tr('gifts.card_id_30f8dc', 'Card id'), "card_id")],
                      spacing=10)

    def swsh_bp(self) -> ft.Control:
        return ft.Row([self.number_field(tr('gifts.battle_points_c484f8', 'Battle Points'), "bp"), self.number_field(tr('gifts.card_id_30f8dc', 'Card id'), "card_id")],
                      spacing=10)

    # Summary

    def name(self, kind, n) -> str:
        """The name PKHeX gives an id; the first miss loads the list and redraws the summary."""
        if self.game == "frlg" and kind == "species" and i18n.locale() == "en":
            return frlg.species_name(n)
        names = "species3" if self.game == "frlg" and kind == "species" else "items" if kind == "item" else kind
        cached = SERVICE.species_cache.get(f"{self.game}:{names}")
        if cached is None:
            def load():
                try:
                    SERVICE.names(self.game, names)
                except Exception:
                    return
                if self.games.tool is self.tool:
                    self.app.ui(lambda: self.show_summary(update=True))
            threading.Thread(target=load, daemon=True).start()
        fallback = (frlg.species_name(n) if names == "species3" else
                    tr('gifts._4eed26', '{value0} #{value1}', value0=kind, value1=n))
        return next((entry["name"] for entry in cached or () if entry["id"] == _number(n)), fallback)

    def show_summary(self, update=False) -> None:
        mode = self.value["mode"]
        self.status.value, self.status.color = "", t.MUTED
        warnings = []
        if mode == "build":
            when, lines = gift_description(self.game, self.state, self.name)
        elif mode == "preset":
            preset = self.module.PRESET[self.value["preset"]]
            when, lines = getattr(preset, "when", ""), [preset.summary]
            if hasattr(preset, "members"):
                when = tr('gifts.starts_on_the_console_as_soon_as_it_is_received_2ccf0e', 'Starts on the console as soon as it is received.')
                lines = preset.effects(self.value["options"].get(preset.key))
            elif preset.state is not None:
                when, lines = gift_description(self.game, preset.state, self.name)
        elif mode == "save":
            when, lines = self.save_summary()
        elif mode == "event":
            official, key = self.module.OFFICIAL, self.value["event"]
            try:
                record = official.record(key, self.value["event_ids"].get(key))
            except ValueError:
                record = None                   # the status line says what to fix
            when, lines = official.describe(record, self.name) if record else ("", [])
            if record and official.from_home(record):
                warnings = [tr('gifts._04903a', '{value0}. {value1}', value0=pokemon.HOME_TRACKER_WARNINGS['empty'], value1=official.HOME_WHY)]
            if record and (shared := official.sharing(key, official.card_id(record))):
                names = tr("presentation.list_separator", ", ").join(translate(label) for label in shared[:3]) + (tr('gifts.and_more_247aa1', ' and {value0} more', value0=len(shared) - 3) if len(shared) > 3 else "")
                warnings.append(tr('gifts.shares_card_id_with_a_save_that_took_one_of_them_refuse_152890', 'Shares card id {value0} with {value1}. A save that took one of them refuses this card: give it another card id.', value0=official.card_id(record), value1=names))
        else:
            when, lines = "", []
        problem = gift_builder.problem(self.tool, self.value)
        if problem:
            self.status.value, self.status.color = translate(problem), t.RED
        elif mode == "save":
            pass
        elif mode != "preset" or self.module.PRESET[self.value["preset"]].args == ():
            gift = gift_builder.compile(self.tool, self.value)
            targets = [translate(frlg.CARTRIDGES.get(code) or (tr('gifts.emerald', 'Emerald') if code == "emerald"
                       else tr('gifts.sword_and_shield_769780', 'Sword and Shield'))) for code in gift.variants]
            self.status.value = tr('gifts.works_on_8e9709', 'Works on ') + ", ".join(targets) + "."
            if mode == "file":
                lines = [gift.name]
        self.when.value = translate(when)
        self.when.visible = bool(when)
        self.effects.controls = [ft.Row([t.pixel_icon("check", color=t.GREEN), t.text(translate(line), 13, expand=True)],
                                        spacing=8) for line in lines]
        self.effects.controls += [ft.Row([t.pixel_icon("warning-diamond", color=t.AMBER),
                                          t.text(translate(line), 13, t.AMBER, expand=True)], spacing=8) for line in warnings]
        if update:
            for control in (self.when, self.effects, self.status):
                control.update()

    def save_summary(self) -> tuple[str, list[str]]:
        chosen = self.value["save"]
        if chosen["action"] == "backup":
            return (tr('gifts.on_the_console_mystery_gift_wonder_cards_friend_then_po_bcca2b', 'On the console: Mystery Gift, Wonder Cards, Friend, then POKELDN.'),
                    [tr('gifts.the_whole_save_comes_to_your_saves_named_after_the_trai_abdade', 'The whole save comes to Your saves, named after the trainer.'),
                     tr('gifts.the_console_shows_a_message_and_keeps_its_save_as_it_wa_f479a7', 'The console shows a message and keeps its save as it was.')])
        entry = saves.entry(chosen["file"]) if chosen["file"] else None
        if entry is None:
            return "", []
        return (tr('gifts.on_the_console_mystery_gift_wonder_cards_friend_then_po_409459', 'On the console: Mystery Gift, Wonder Cards, Friend, then POKELDN. Back its save up first.'),
                [tr('gifts.replaces_the_console_s_save_d358ee', "{value0} replaces the console's save.", value0=entry.name),
                 tr('gifts.the_console_checks_every_part_loads_it_and_saves_anythi_fa40d6', 'The console checks every part, loads it and saves; anything short of that keeps its save.'),
                 tr('gifts.then_choose_continue_on_the_title_screen_79208d', 'Then choose CONTINUE on the title screen.')])

    async def select_native_build(self, gift):
        loop = asyncio.get_running_loop()
        chosen = loop.create_future()
        options = [(code, translate(frlg.CARTRIDGES[code])) for code in gift.variants]
        picker = t.dropdown(options, options[0][0])

        async def finish(e):
            if not chosen.done():
                chosen.set_result(picker.value)
            self.app.page.pop_dialog()

        async def cancel(e):
            if not chosen.done():
                chosen.set_result(None)
            self.app.page.pop_dialog()

        async def dismissed(e):
            if not chosen.done():
                chosen.set_result(None)

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('gifts.export_for_which_cartridge_70087a', 'Export for which cartridge?'), 18, t.TEXT),
            content=ft.Column([
                t.text(tr('gifts.a_wc3_holds_one_cartridge_s_gift_choose_its_version_and_756cde', "A .wc3 holds one cartridge's gift. Choose its version and language. A .pokegift keeps every supported cartridge together."), 13, t.MUTED),
                t.labeled_control(tr('gifts.cartridge_af8536', 'Cartridge'), picker),
            ], tight=True, spacing=12, width=420),
            actions=[t.button(tr('gifts.cancel_19766e', 'Cancel'), cancel, filled=False), t.button(tr('gifts.export_366489', 'Export'), finish)],
            on_dismiss=dismissed))
        return await chosen

    async def _save(self, e) -> None:
        self.save_button.disabled = True
        self.status.value, self.status.color = tr('gifts.preparing_gift_file_96cb56', 'Preparing gift file…'), t.MUTED
        self.save_button.update()
        self.status.update()
        tool, extra = self.tool, dict(self.games.extra)
        values = {**self.games.values, self.field.key: copy.deepcopy(self.value)}
        try:
            gift = await asyncio.to_thread(gift_files.build, tool, values, extra, self.app.settings)
            native = "wc8" if self.game == "swsh" else "wc3"
            path = await self.app.picker.save_file(
                dialog_title=tr('gifts.save_mystery_gift_fa0080', 'Save Mystery Gift'), file_name=f"{tool.key}.pokegift",
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=[gifts.EXTENSION, native])
            if path:
                path += "" if path.lower().endswith((".pokegift", f".{native}")) else ".pokegift"
                build = None
                if self.game == "frlg" and path.lower().endswith(".wc3") and len({
                        (v.data.get("card"), v.data.get("ram_script")) for v in gift.variants.values()}) > 1:
                    build = await self.select_native_build(gift)
                    if build is None:
                        self.show_summary()
                        return
                gifts.save(path, gift, build=build)
                self.status.value = tr('gifts.saved_af6b8a', 'Saved {value0}', value0=path)
            else:
                self.show_summary()
        except (OSError, ValueError, pokemon.BuilderError) as exc:
            self.status.value, self.status.color = error_message(exc), t.RED
        finally:
            self.save_button.disabled = False
            if self.games.tool is tool:
                self.save_button.update()
                self.status.update()

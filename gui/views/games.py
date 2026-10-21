import os
import shlex
import threading
import time

from pathlib import Path

import flet as ft

from gui.app import keys_found
from pokeldn import panel, progress
from pokeldn.app import bank, command, panels, events_gallery, gift_builder, online, received, runner
from pokeldn.swsh import raid_event as swsh_raid_event
from pokeldn.sv import raid_event as raid_events
from gui import theme as t
from pokeldn import plugins
from pokeldn.app.catalog import Field, Game, Tool
from pokeldn.app.introspect import flags_of
from pokeldn.app.paths import SESSION
from gui.views.event_gifts import EventGiftPicker
from gui.views.pokemon import NAME_LISTS, LinkCodePicker, NamePicker, OfferQueue, PokemonPicker
from gui.views.raid_event import FOLDED, RaidEventPicker
from gui.views.encounter import EncounterPicker
from gui.views.raid_partners import RaidPartnersPicker
from gui.views.raid_seed import RaidSeedPicker
from gui.views.lair_seed import LairSeedPicker
from gui.views.rewards import RewardPicker
from gui.views.gifts import GiftBuilder
from gui.views.library import LibraryCard
from gui.views.panels import StatusCards, card_control
from gui.views.sprites import MINI, Sprite
from gui.views.widgets import CodeBlock, DigitCode, Log, PathField, open_folder
from gui.localization import SERVICE, summary as pokemon_summary, summary_lines, summary_text, translate
from pokeldn.app.i18n import help_text, t as tr

EMPTY = "-"   # a dropdown option cannot carry an empty key
# The Tera Raid host's event fields (pokeldn/app/catalog.py) and the context fields an event narrows.
RAID_EVENT, RAID_DEN, RAID_CATCH = "--raid-event", "--raid-event-group", "--raid-catch-normal"
REWARD_DEN_KEYS = ("--raid-boss", "--raid-gigantamax")   # a Max Raid's den follows its boss
RAID_CONTEXT = {"--raid-version": ("version", "violet"), "--raid-map": ("map_name", "paldea"),
                "--raid-progress": ("progress", "4star"), "--raid-content": ("content", "standard")}
ADVANCED_NOTE = (tr('games.the_tested_defaults_work_for_most_players_change_these__1815f2', 'The tested defaults work for most players. Change these only when a guide or a bug report asks you to. A value set here overrides the Basic tab.'))


def tool_icon(tool: Tool):
    if plugins.owner(tool.key):
        return "plug"
    if tool.key.endswith("-online"):
        return "globe"
    if "circle" in tool.key:
        return "users"
    # "Trade (Host)" and "Mystery Gift - Simulated" take their kind's icon.
    return "gift" if "gift" in tool.key else "diamond-gem" if "raid" in tool.key else "arrows-horizontal"


def tool_role(tool: Tool) -> str:
    """Who looks for whom, said from the console's side; a plugin's tool names its plugin."""
    if owner := plugins.owner(tool.key):
        return tr('games.plugin_c37b59', 'Plugin: {value0}', value0=owner.name)
    if tool.key.endswith("-host"):
        return tr('games.your_console_joins_pokeldn_269e96', 'Your console joins pokeldn')
    if tool.key.endswith("-join"):
        return tr('games.pokeldn_joins_your_console_7e1f2f', 'pokeldn joins your console')
    if tool.key.endswith("-online"):
        return tr('games.your_console_joins_pokeldn_which_reaches_your_partner_0a41b2', 'Your console joins pokeldn, which reaches your partner')
    return ""


def game_of(view) -> str:
    """-> the shown game's key; a raid view without one is Scarlet/Violet's."""
    return getattr(getattr(view, "game", None), "key", "sv")


def forget_unremembered(tool_values: dict, catalog: list[Game]) -> None:
    """Empties each field that is not `remembered` in the stored tool values, at launch."""
    for tool in (tool for game in catalog for tool in game.tools):
        for field in tool.fields:
            if not field.remembered:
                tool_values.get(tool.key, {}).get("values", {}).pop(field.key, None)


def translated_card(card: dict) -> dict:
    """A built-in run's English `[panel]` card in the selected pack's words."""
    return {**card, "title": translate(card["title"]),
            "chips": [(translate(label), value) for label, value in card["chips"]],
            "lines": [[translate(part) for part in line] if isinstance(line, list) else translate(line)
                      for line in card["lines"]]}


class GamesView:
    def __init__(self, app):
        self.app = app
        self.catalog = plugins.games()   # the catalog with the enabled plugins' tools
        self.generation = plugins.generation
        self.game: Game = self.catalog[0]
        self.tool: Tool = self.game.tools[0]
        self.tab = "basic"
        self.search = ""
        self.sprites: dict[str, Sprite] = {}   # a species field's key -> the sprite on its card
        self.visible = False
        # The Tera Raid host's Raid event card is unfolded while its event is in use (show_raid_event).
        self.raid_event_open = False
        # Its Raid NPC partners card only folds: the choice stays in force (show_raid_partners). The
        # width its cards last had lets a redraw start on the columns that fit.
        self.raid_partners_open = False
        self.raid_partners_width = 0
        self.raid_partners = None              # the card shown, whose level follows Our Pokemon
        self.locks = []                        # (field, switch, note) the chosen gift can lock (command.locked)
        # The override of a boss a save catches once starts unchecked at every launch.
        for stored in app.settings.tool_values.values():
            stored.get("values", {}).pop(RAID_CATCH, None)
            self.raid_event_open = self.raid_event_open or bool(stored.get("values", {}).get(RAID_EVENT))
        forget_unremembered(app.settings.tool_values, self.catalog)
        self.tree = ft.ListView(spacing=2, padding=ft.Padding(8, 8, 8, 8), expand=True)
        self.summary = t.text("", 12, t.MUTED, text_align=ft.TextAlign.CENTER)
        self.cards = ft.Column(spacing=t.GAP)
        self.run_panel = ft.Column(spacing=t.GAP, visible=False)    # show_run_cards
        # The cards start below the toolbar and scroll under its glass.
        self.body = ft.ListView([ft.Container(self.summary, alignment=ft.Alignment.CENTER,
                                              padding=ft.Padding(12, 0, 12, 4)), self.run_panel, self.cards],
                                spacing=t.GAP, padding=ft.Padding(0, 62, 0, 24), expand=True)
        self.tabs = ft.Container()
        self.session = SessionPanel(app, self)
        center = ft.Stack([
            t.fade(self.body, 48),
            ft.Container(t.notch(self.tabs,
                                 t.icon_button("book-open", self._open_doc, tr('games.read_the_docs_for_this_game_ca6165', 'Read the docs for this game'))),
                         top=0, left=0, right=0),
        ], expand=True)
        self.panes = t.Panes(
            (tr('games.pane_games', 'Games'), "gamepad", t.panel(ft.Column([t.panel_header(tr('games.games_d9dae7', 'Games')), t.fade(self.tree)], spacing=0, expand=True), width=t.SIDEBAR_WIDTH)),
            (tr('games.pane_options', 'Options'), "sliders-horizontal", center),
            (tr('games.pane_session', 'Session'), "play", self.session.control))
        self.control = self.panes.control
        self.select(self.game, self.tool, update=False)

    def enter(self, game: str = "", tool: str = "", **_) -> None:
        """`game` and `tool` are catalog keys: the bank opens the trade it queued a Pokemon for."""
        self.visible = True
        if self.generation != plugins.generation:     # a plugin was turned on, off, added or removed
            self.generation, self.catalog = plugins.generation, plugins.games()
            game_now = next((g for g in self.catalog if g.key == self.game.key), self.catalog[0])
            tool_now = next((x for x in game_now.tools if x.key == self.tool.key), game_now.tools[0])
            self.app.ui(lambda: self.select(game_now, tool_now))
        chosen = next(((g, x) for g in self.catalog for x in g.tools if g.key == game and x.key == tool), None)
        if chosen:   # once the view is back on the page: a list rebuilt off it shows empty
            self.app.ui(lambda: self.select(*chosen))
        self.session.refresh(update=False)
        self.app.check_if_unknown()

    def leave(self) -> None:
        self.visible = False

    # State

    def stored(self) -> dict:
        return self.app.settings.tool_values.setdefault(self.tool.key, {"values": {}, "extra": {}})

    @property
    def values(self) -> dict:
        return self.stored()["values"]

    @property
    def extra(self) -> dict:
        return self.stored()["extra"]

    def set_value(self, field: Field, value, rebuild: bool = False) -> None:
        self.values[field.key] = value
        self.app.settings.save()
        picker = getattr(self, "reward_picker", None)
        if picker is not None and picker.den_of is not None and field.key in REWARD_DEN_KEYS and not rebuild:
            try:
                picker.follow()
            except RuntimeError:   # the card was redrawn away
                pass
        if rebuild:
            self.render_body()
            self.cards.update()
        elif field.kind == "pokemon" and self.raid_partners:
            self.raid_partners.follow_host()
        elif field.events:
            self.follow_locks()
        self.session.refresh()

    def switched(self, field: Field, on: bool) -> None:
        """A switch redraws the cards only when another field shows, hides or changes with it: a redraw reads
        a Mystery Gift card's gift list again. A Shiny switch turns the sprites in place."""
        drives = any(field.key in (f.unless, f.requires) or f.when[:1] == (field.key,) for f in self.tool.fields)
        self.set_value(field, on, rebuild=drives)
        if field.shiny and not drives:
            for f in self.tool.fields:
                if f.key in self.sprites:
                    species = str(command.value_of(f, self.values) or "")
                    self.sprites[f.key].show(int(species) if species.isdigit() else 0, self.shiny())

    def follow_locks(self) -> None:
        """The switches the chosen Mystery Gift Pokemon locks follow it without a redraw, which would read the
        gift list again: off and disabled, their note saying why, while it has its own trainer."""
        for field, control, note in self.locks:
            why = command.locked(field, self.tool, self.values)
            control.value = bool(command.value_of(field, self.values)) and not why
            control.disabled, control.opacity = bool(why), 0.45 if why else 1.0
            note.value = self.description(field)
            for shown in (control, note):
                try:
                    shown.update()
                except RuntimeError:    # the card was redrawn away
                    pass

    def redraw(self) -> None:
        """Saves the values and redraws the cards and the session on them."""
        self.app.settings.save()
        self.render_body()
        self.cards.update()
        self.session.refresh()

    def set_raid_context(self, context: dict) -> None:
        """The raid finder's choice brings its version, region, progress and crystal with it; an
        event raid's, its den's delivery group in place of the crystal."""
        self.values.update({
            "--raid-version": context["version"],
            "--raid-map": context["map_name"],
            "--raid-progress": context["progress"],
        })
        if "event" in context:
            self.values[RAID_DEN] = str(context["group"])
        else:
            self.values["--raid-content"] = context["content"]
        self.redraw()

    # Event raids

    def show_raid_event(self, unfolded: bool) -> None:
        """Unfolds or folds the Raid event card. Folding sets its event aside, and the raid, its finder
        and the command are a standard raid's; unfolding brings the event back."""
        self.raid_event_open = unfolded
        if unfolded and not self.values.get(RAID_EVENT) and self.values.get(FOLDED):
            self.values[RAID_EVENT] = self.values.pop(FOLDED)
        elif not unfolded and self.values.get(RAID_EVENT):
            self.values[FOLDED] = self.values.pop(RAID_EVENT)
        self.redraw()

    # NPC partners

    def show_raid_partners(self, unfolded: bool) -> None:
        """Unfolds or folds the Raid NPC partners card; its choice goes to the raid either way."""
        self.raid_partners_open = unfolded
        self.redraw()

    def raid_event(self):
        """-> the event the Raid event card chose, or None: none chosen, folded, or not in the gallery."""
        key = self.values.get(RAID_EVENT)
        if not key:
            return None
        try:
            return events_gallery.load(key, game=game_of(self))
        except (OSError, ValueError):
            return None

    def raid_context(self) -> dict:
        """-> the raid the tool's fields describe; an event's carries the event, its group and den."""
        context = {name: str(self.values.get(key, default)) for key, (name, default) in RAID_CONTEXT.items()}
        event = self.raid_event()
        if event is None:
            return context
        context = raid_events.constrain(event, {**context, "group": self.values.get(RAID_DEN)})
        den = next(d for d in raid_events.dens(event, context["version"]) if d.group == context["group"])
        return {**context, "event": event, "den": den.label}

    def constrain_raid(self) -> None:
        """Keeps the stored version, region, progress and den ones the chosen event spawns."""
        if game_of(self) != "sv" or self.raid_event() is None:
            return
        context = self.raid_context()
        wanted = {"--raid-version": context["version"], "--raid-map": context["map_name"],
                  "--raid-progress": context["progress"], RAID_DEN: str(context["group"])}
        if any(self.values.get(key) != value for key, value in wanted.items()):
            self.values.update(wanted)
            self.app.settings.save()

    def raid_choices(self, field: Field) -> tuple | None:
        """-> the choices of a raid context field the chosen event allows, or None to keep them all."""
        if game_of(self) != "sv":
            return None
        event = self.raid_event()
        if event is None or field.key not in ("--raid-version", "--raid-map", "--raid-progress"):
            return None
        context = self.raid_context()
        allowed = {"--raid-version": raid_events.versions(event), "--raid-map": ["paldea"],
                   "--raid-progress": raid_events.progresses(event, context["version"], context["group"])}
        return tuple((key, label) for key, label in field.choices if key in allowed[field.key])

    def gallery_changed(self) -> None:
        """The event gallery was downloaded or updated: the card and the raid redraw on it."""
        events_gallery.forget()
        self.redraw()

    # Rendering

    def select(self, game: Game, tool: Tool, update: bool = True) -> None:
        if tool is not self.tool:
            self.tab, self.search = "basic", ""
        self.game, self.tool = game, tool
        self.summary.value = tool.summary
        self.tabs.content = t.segmented([("basic", tr('games.basic_0e35f6', 'Basic'), "sliders-horizontal"),
                                          ("all", tr('games.advanced_9f088d', 'Advanced'), "bulletlist")], self.tab, self._tab)
        self.render_tree()
        self.render_body()
        self.session.show(tool)
        if update:
            self.control.update()

    def pick(self, game: Game, tool: Tool) -> None:
        """A tool chosen in the list; on a phone its options come forward."""
        self.panes.show(1, update=False)
        self.select(game, tool)

    def render_tree(self) -> None:
        rows = []
        for game in self.catalog:
            open_ = game is self.game
            rows.append(ft.Container(ft.Row([
                ft.Container(ft.Image(src=t.image_src(Path(game.icon).read_bytes()) if game.icon else f"games/{game.key}.png", width=36, height=36,
                                      fit=ft.BoxFit.CONTAIN, filter_quality=ft.FilterQuality.NONE,
                                      semantics_label=game.name),
                             width=40, height=36, alignment=ft.Alignment.CENTER),
                t.text(game.name, 13, t.TEXT if open_ else t.SOFT, weight=ft.FontWeight.W_600, expand=True),
            ], spacing=10), padding=ft.Padding(8, 6, 8, 6), border_radius=12,
                on_click=lambda e, g=game: self.select(g, g.tools[0])))
            if open_:
                for tool in game.tools:
                    active = tool is self.tool
                    name = t.text(tool.name, 13, t.TEXT if active else (t.FAINT if tool.unavailable else t.MUTED))
                    role = tool_role(tool)
                    rows.append(ft.Container(ft.Row([
                        t.pixel_icon(tool_icon(tool), color=t.BLUE if active else t.FAINT),
                        ft.Column([name, t.text(role, 11, t.FAINT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)],
                                  spacing=0, expand=True) if role else
                        ft.Container(name, expand=True),
                        t.badge(tr('games.soon_cf0ee3', 'Soon'), t.FAINT) if tool.unavailable else ft.Container(),
                    ], spacing=10), padding=ft.Padding(24, 7, 8, 7), border_radius=12, tooltip=tool.summary,
                        bgcolor=t.SELECTED if active else None,
                        on_click=lambda e, g=game, x=tool: self.pick(g, x)))
                rows.append(ft.Container(height=6))
        self.tree.controls = rows

    def show_run_cards(self, update: bool = True) -> None:
        """A built-in run's `[panel]` cards, above its tool's options while it runs and that tool is
        shown (SessionPanel.show_card)."""
        session = self.session
        running = bool(self.app.process and self.app.process.running)
        cards = session.run_cards if running and self.tool is session.running_tool else {}
        self.run_panel.controls = [card_control(translated_card(c)) for c in cards.values()]
        self.run_panel.visible = bool(cards)
        if update:
            try:
                self.run_panel.update()
            except RuntimeError:    # not on the page: the next render_body draws it
                pass

    def render_body(self) -> None:
        self.raid_partners = self.reward_picker = None
        self.show_run_cards(update=False)
        if self.tool.unavailable:
            self.tabs.visible = False
            self.cards.controls = [t.card(tr('games.not_available_yet_787406', 'Not available yet'), None, self.tool.unavailable)]
            return
        self.tabs.visible = True
        self.cards.controls = self.basic_cards() if self.tab == "basic" else self.all_rows()

    def _tab(self, key: str) -> None:
        self.tab = key
        self.render_body()
        self.cards.update()

    def _open_doc(self, e) -> None:
        self.app.navigate("docs", doc=self.tool.doc or self.game.doc or "plugins.md")

    # Basic tab

    def basic_cards(self) -> list[ft.Control]:
        cards, groups = [], {}
        self.constrain_raid()
        for field in self.tool.fields:
            if field.hidden or not command.applies(field, self.tool, self.values):
                continue
            if field.group:
                if field.group not in groups:
                    groups[field.group] = []
                    cards.append(("group", field.group))
                groups[field.group].append(field)
            else:
                cards.append(("field", field))
        out = []
        self.sprites = {}
        self.locks = []
        for kind, item in cards:
            if kind == "field" and item.kind == "builder":
                out.extend(GiftBuilder(self, item).cards())
            elif kind == "field" and item.kind == "raidevent":
                out.append(RaidEventPicker(self, item).control)
            elif kind == "field" and item.kind == "encounter":
                out.append(t.card(item.label, EncounterPicker(self, item).control, self.description(item)))
            elif kind == "field" and item.kind == "raidpartners":
                self.raid_partners = RaidPartnersPicker(self, item)
                out.append(self.raid_partners.control)
            elif kind == "field" and item.kind == "switch" and item.your_ot:
                control, note = self.input(item), t.text(self.description(item), 12, t.MUTED)
                self.locks.append((item, control, note))
                out.append(t.card(item.label, note, trailing=control))
            elif kind == "field" and item.kind == "switch":
                out.append(t.card(item.label, None, item.help, trailing=self.input(item)))
            elif kind == "field" and item.kind == "pokemon" and item.queue > 1 and not item.events:
                # "Add a trade" sits under the card, outside it.
                queue = self.offer_queue(item)
                queue.card = t.card(item.label, queue.control, self.description(item))
                out.append(queue.card)
                out.append(queue.footer)
            elif kind == "field":
                out.append(t.card(item.label, self.input(item), self.description(item),
                                  trailing=self.species_sprite([item])))
            else:
                fields = groups[item]
                per_row = 2 if len(fields) > 3 else len(fields)
                sprite = self.species_sprite(fields)
                rows = [ft.Row([
                    t.labeled_control(f.label, self.input(f, grouped=True), expand=True)
                    for f in fields[i:i + per_row]], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)
                    for i in range(0, len(fields), per_row)]
                if item == tr('catalog.console_29a408', 'Console') and self.tool.key == "frlg-gift":
                    rows.append(ft.Column([
                        t.text(tr('games.game_language_233497', 'Game language'), 12, t.MUTED),
                        t.text(tr('games.detected_automatically_ff4f09', 'Detected automatically'), 13, t.TEXT),
                        t.text(tr('games.english_french_german_italian_spanish_japanese_54bc86', 'English · French · German · Italian · Spanish · Japanese'), 12, t.MUTED),
                        t.text(tr('games.after_you_choose_pokeldn_in_the_friend_list_your_game_r_1fb839', 'After you choose pokeldn in the Friend list, your game reports its language.'),
                               12, t.MUTED),
                    ], spacing=4))
                out.append(t.card(item, ft.Column(rows, spacing=10),
                                  " ".join(f.help for f in fields if f.help), trailing=sprite))
        if not self.tool.fields:
            out.append(t.text(tr('games.nothing_to_fill_in_10f2c5', 'Nothing to fill in.'), 13, t.MUTED))
        owner = plugins.owner(self.tool.key)
        self.plugin_cards = StatusCards(owner) if owner is not None else None
        self.library_card = LibraryCard(self.app, owner) if owner is not None and owner.library else None
        if self.plugin_cards:
            out.insert(0, self.plugin_cards.control())
        if self.library_card:
            out.append(self.library_card.control())
        return out

    def plugin_changed(self, plugin_id: str) -> None:
        """A run's `[panel]` line changed what plugin `plugin_id` shows; redraws it if it is on the page."""
        if not self.visible or self.tab != "basic":
            return
        for part in (getattr(self, "plugin_cards", None), getattr(self, "library_card", None)):
            if part is not None and part.plugin.id == plugin_id:
                part.refresh()

    def shiny(self) -> bool:
        return any(bool(command.value_of(f, self.values)) for f in self.tool.fields
                   if f.shiny and command.applies(f, self.tool, self.values))

    def species_sprite(self, fields: list[Field]) -> ft.Control | None:
        field = next((f for f in fields if f.kind == "species"), None)
        if field is None:
            return None
        value = str(command.value_of(field, self.values) or "")
        sprite = Sprite(self.app, int(value) if value.isdigit() else 0, self.shiny(), size=MINI)
        self.sprites[field.key] = sprite
        return sprite.control

    def description(self, field: Field) -> str:
        selected = command.value_of(field, self.values)
        detail = dict(field.choice_help).get(selected, "") if field.kind == "choice" else ""
        why = command.locked(field, self.tool, self.values) if field.your_ot else ""
        return " ".join(part for part in (field.help, detail, translate(why)) if part)

    def offer_queue(self, field: Field) -> OfferQueue:
        return OfferQueue(self.app, self.game.key, command.value_of(field, self.values), field.queue,
                          lambda v: self.set_value(field, v), version=str(self.values.get("--version", "")))

    def input(self, field: Field, grouped: bool = False) -> ft.Control:
        value = command.value_of(field, self.values)
        if field.kind == "switch":
            why = command.locked(field, self.tool, self.values) if field.your_ot else ""
            control = t.switch(bool(value) and not why, lambda e: self.switched(field, e.control.value))
            control.disabled, control.opacity = bool(why), 0.45 if why else 1.0   # follow_locks
            return control
        if field.kind == "choice":
            choices = self.raid_choices(field) or field.choices
            control = t.dropdown([(k or EMPTY, translate(label)) for k, label in choices], value or EMPTY,
                                 on_select=lambda e: self.set_value(
                                     field, "" if e.control.value == EMPTY else e.control.value, rebuild=True))
            control.disabled = len(choices) == 1 and len(field.choices) > 1   # an event leaves one
            return control
        if field.kind == "raideventboss":
            event = self.raid_event()
            bosses = swsh_raid_event.hostable(event) if event is not None else []
            options = [(f"{v}:{stars}:{n}:{area}",
                        f"{'★' * stars} {b.name} · Lv {b.level} · {v.title()}" + (f" · {area}" if area != "Wild Area" else ""))
                       for v, stars, n, area, b in bosses]
            keys = [k for k, _ in options]
            chosen = value if value in keys else (keys[-1] if keys else "")
            if chosen != value and chosen:
                self.values[field.key] = chosen
            options = [(key, translate(label)) for key, label in options]
            control = t.dropdown(options or [(EMPTY, tr('games.no_boss_of_this_event_shows_in_a_den_8a4b1e', 'No boss of this event shows in a den'))],
                                 chosen or EMPTY, on_select=lambda e: self.set_value(field, e.control.value, rebuild=True))
            control.disabled = not options
            return control
        if field.kind == "raidden":
            event, context = self.raid_event(), self.raid_context()
            dens = raid_events.dens(event, context["version"]) if event is not None else []
            control = t.dropdown([(str(d.group), translate(d.label)) for d in dens], str(context.get("group", "")),
                                 on_select=lambda e: self.set_value(field, e.control.value, rebuild=True))
            control.disabled = len(dens) == 1
            return control
        if field.kind in NAME_LISTS:
            def picked(v):
                self.set_value(field, v)
                if field.key in self.sprites:
                    self.sprites[field.key].show(int(v) if str(v).isdigit() else 0, self.shiny())
            return NamePicker(self.app, self.game.key, field.kind, value, picked,
                              optional=not field.default).control
        if field.kind == "pokemon" and field.events:
            values = self.values

            def picked(chosen):
                if self.values is values:
                    self.set_value(field, chosen)
                else:
                    values[field.key] = chosen
                    self.app.settings.save()

            return EventGiftPicker(self.app, self.game.key, value, picked,
                                   limit=field.queue).control
        if field.kind == "pokemon" and field.queue > 1:
            return self.offer_queue(field).control
        if field.kind == "pokemon":
            first = command.offers(value)
            return PokemonPicker(self.app, self.game.key, first[0] if first else {},
                                 lambda v: self.set_value(field, v),
                                 version=str(self.values.get("--version", ""))).control
        if field.kind == "rewards":
            den = (lambda: command.reward_den(self.tool, self.values)) if self.tool.key == "swsh-raid-host" else None
            self.reward_picker = RewardPicker(self.app, self.game.key, value, lambda v: self.set_value(field, v), den=den)
            return self.reward_picker.control
        if field.kind == "raidseed":
            return RaidSeedPicker(self.app, value, lambda v: self.set_value(field, v),
                                  context=self.raid_context, on_context_change=self.set_raid_context).control
        if field.kind == "lairseed":
            return LairSeedPicker(self.app, value, lambda v: self.set_value(field, v)).control
        if field.kind == "linkcode":
            return LinkCodePicker(self.app, value, lambda v: self.set_value(field, v)).control
        if field.kind == "code":
            return DigitCode(value, lambda v: self.set_value(field, v), length=field.length).control
        if field.kind == "file":
            return PathField(self.app.picker, lambda: os.path.expanduser("~"), value or "", "file", field.exts,
                             lambda v: self.set_value(field, v)).control
        def refused(value) -> str:
            return (command.limit_error(field, value) if field.limits
                    else command.code_error(field, value) if field.bounds else "")

        def changed(e):
            if field.limits or field.bounds:
                e.control.error = refused(e.control.value) or None
                e.control.update()
            self.set_value(field, e.control.value)

        box = t.field(value=str(value), mono=field.kind == "number", error_max_lines=2,
                      digits=field.kind == "number",
                      width=180 if field.kind == "number" and not grouped else None,
                      error=refused(value) or None, on_change=changed,
                      expand=field.kind != "number" or grouped)
        return box if grouped or field.kind == "number" else ft.Row([box])

    # All tab

    def all_rows(self) -> list[ft.Control]:
        search = t.field(value=self.search, hint=tr('games.search_the_options_596033', 'Search the options'), autofocus=False,
                         prefix_icon=ft.Container(t.pixel_icon("search", color=t.FAINT),
                                                  width=40, alignment=ft.Alignment.CENTER),
                         on_change=self._search)
        self.flag_list = ft.Column(spacing=0)
        self._fill_flags()
        return [t.card(tr('games.advanced_options_9443ff', 'Advanced options'), ft.Column([search, self.flag_list], spacing=10,
                                                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                       ADVANCED_NOTE)]

    def _search(self, e) -> None:
        self.search = e.control.value
        self._fill_flags()
        self.flag_list.update()

    def _fill_flags(self) -> None:
        try:
            flags = flags_of(self.tool.script)
        except Exception as error:
            self.flag_list.controls = [t.text(tr('games.could_not_read_the_options_8d9eb8', 'Could not read the options: {value0}', value0=error), 12, t.RED)]
            return
        query = self.search.lower().strip()
        hidden = {f.key: f for f in self.tool.fields if f.hidden}
        if any(f.kind == "builder" for f in self.tool.fields):   # the Gift card sets these
            owned = gift_builder.owned_flags(self.tool)
            flags = [f for f in flags if f.option not in owned]
        rows = []
        # The settings kept off the Basic tab come first.
        for flag in sorted(flags, key=lambda f: f.option not in hidden):
            field = hidden.get(flag.option)
            localized = help_text(self.tool.key, flag.option, flag.help)
            text = " ".join((flag.option, flag.help, localized, field.label, field.help) if field else (flag.option, flag.help, localized))
            if query and query not in text.lower():
                continue
            rows.append(self.flag_row(flag))
        empty = tr('games.no_option_matches_278e25', 'No option matches.') if flags else tr('games.this_tool_takes_no_options_beyond_its_basic_fields_260710', 'This tool takes no options beyond its Basic fields.')
        self.flag_list.controls = rows[:200] or [t.text(empty, 12, t.MUTED)]

    def flag_row(self, flag) -> ft.Control:
        # A field kept off the Basic tab is set here, on its own value, default included.
        bound = next((f for f in self.tool.fields if f.hidden and f.key == flag.option), None)
        value = command.value_of(bound, self.values) if bound else self.extra.get(flag.option)

        def store(v):
            if bound:
                self.set_value(bound, v if v not in (None, "") else bound.default)
                return
            if v in (None, "", False):
                self.extra.pop(flag.option, None)
            else:
                self.extra[flag.option] = v
            self.app.settings.save()
            self.session.refresh()
            if flag.kind == "choice":
                self._fill_flags()
                self.flag_list.update()

        if flag.kind == "switch":
            control = t.switch(bool(value), lambda e: store(e.control.value))
        elif flag.kind == "choice":
            control = ft.Container(t.dropdown([(EMPTY, tr("games.default_choice", "default"))] + [(c, translate(c)) for c in flag.choices],
                                              value or EMPTY,
                                              on_select=lambda e: store("" if e.control.value == EMPTY else e.control.value)),
                                   width=220)
        else:
            default = "" if flag.default in (None, [], "") else str(flag.default)
            control = ft.Container(t.field(value=value or "", hint=default, mono=True,
                                           on_change=lambda e: store(e.control.value)), width=220)
        detail = ""
        for field in self.tool.fields:
            if field.flag == flag.option and field.choice_help:
                detail = dict(field.choice_help).get(value or flag.default, "")
                break
        lines = ([bound.help] if bound and bound.help else [help_text(self.tool.key, flag.option, flag.help)])
        if detail:
            lines.append(detail)
        help_ = t.text("\n".join(l for l in lines if l) or tr('games.no_description_06a694', 'No description.'), 12, t.MUTED, max_lines=4,
                       overflow=ft.TextOverflow.ELLIPSIS)

        def toggle(e):
            help_.max_lines = None if help_.max_lines else 4
            help_.update()

        return ft.Container(ft.Row([
            ft.Column([ft.Row([t.text(bound.label, 13, weight=ft.FontWeight.W_600),
                               t.text(flag.option, 12, t.BLUE if value != bound.default else t.MUTED,
                                      font_family=t.MONO)], spacing=8) if bound else
                       t.text(flag.option, 13, t.BLUE if value else t.TEXT, font_family=t.MONO),
                       ft.Container(help_, on_click=toggle, tooltip=tr('games.show_all_2150d8', 'Show all') if len(lines) > 4 else None)],
                      spacing=3, expand=True),
            control,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            border=ft.Border(top=ft.BorderSide(1, t.DIVIDER)), padding=ft.Padding(0, 12, 0, 12))


def pokemon_row(app, species: int, shiny: bool, summary: str, tip: str = "", form: int = 0) -> ft.Control:
    """A small sprite, then pokeldn.pokemon.summary on two lines: species, level and shininess, then the rest."""
    head, rest = summary_lines(summary)
    lines = [t.text(head, 13, weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
    if rest:
        lines.append(t.text(rest, 12, t.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
    return ft.Container(ft.Row([Sprite(app, species, shiny, size=MINI, form=form).control,
                                ft.Column(lines, spacing=0, expand=True)],
                               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        tooltip=tip or None)


def amount_of(done: int, total: int, unit: str) -> str:
    """'1.20 of 5.20 GB' in the unit the total reads best in, or '3 of 12'."""
    if unit != "bytes":
        return tr('games.of_ca6c5e', '{value0} of {value1}', value0=done, value1=total)
    scale, name = next(((s, n) for s, n in ((1e9, "GB"), (1e6, "MB"), (1e3, "KB")) if total >= s), (1, "B"))
    return tr('games.of_75b2ec', '{value0:.2f} of {value1:.2f} {value2}',
              value0=done / scale, value1=total / scale, value2=name)


def per_second(rate: float, unit: str) -> str:
    if unit != "bytes":
        return tr('games.a_second_5442a7', '{value0:.1f} a second', value0=rate)
    scale, name = (1e6, "MB/s") if rate >= 1e6 else (1e3, "KB/s")
    return f"{rate / scale:.2f} {name}"


def time_left(seconds: float | None) -> str:
    if seconds is None:
        return ""
    minutes = round(seconds / 60)
    if minutes < 1:
        return tr('games.under_a_minute_left_782d1a', 'under a minute left')
    if minutes < 60:
        return tr('games.min_left_5a8279', '{value0} min left', value0=minutes)
    return tr('games.h_min_left_2f1238', '{value0} h {value1:02d} min left', value0=minutes // 60,
              value1=minutes % 60)


class SessionPanel:
    def __init__(self, app, games: GamesView):
        self.app, self.games = app, games
        self.tool: Tool | None = None
        self.stopping = False
        self.pulsing = False
        self.status_dot = ft.Container(width=10, height=10, border_radius=5, bgcolor=t.MUTED,
                                       animate_opacity=ft.Animation(800, ft.AnimationCurve.EASE_IN_OUT),
                                       on_animation_end=self._pulse)
        self.status_label = ft.Semantics(content=self.status_dot, label=tr('games.idle_ab0171', 'Idle'))
        self.status = ft.Container(self.status_label, width=24, height=24,
                                   alignment=ft.Alignment.CENTER, tooltip=tr('games.idle_ab0171', 'Idle'))
        self.board_line = ft.Container()   # the checklist before Start, or one line once all is set
        self.offering = ft.Container(visible=False)
        self.transfer = ft.Container(visible=False)   # a save transfer's or a `[progress]` line's bar
        self.rates: dict[str, progress.Rate] = {}     # each `[progress]` title's rate
        self.partner = ft.Container(visible=False)    # an online trade's partner
        self.partner_state = None                     # pokeldn.app.online.Partner
        self.run_cards: dict[str, dict] = {}          # a built-in run's `[panel]` cards by id
        self.offered = None                # what the offering card shows, to rebuild it only on a change
        self.traded = 0                    # the run's completed trades, from its `[done] trade N` lines
        self.bank_trades = bank.TradeSession([])
        self.running_tool: Tool | None = None
        self.restart = False               # Start on another tool: stop this run, then start that one
        self.received = ft.Container(visible=False)
        self.run = None                    # (process, stamp, game) of the last run started
        self.seen: dict[str, tuple] = {}   # a received file -> (size, mtime, what PKHeX read, or None)
        self.steps = ft.Container()
        self.shown_steps = None     # the steps last drawn
        self.action = ft.Container()
        command_block = CodeBlock(app)
        self.command_text = command_block.text
        self.command_box = command_block.control
        self.command_box.visible = False
        self.log = Log(app.page, tr('games.the_session_s_output_appears_here_07c340', "The session's output appears here."),
                       private=lambda: [app.settings.ot] if app.settings.private_logs else None)
        tools = ft.Row([
            t.icon_button("code", self._toggle_command, tr('games.show_the_command_324bde', 'Show the command')),
            t.icon_button("copy", self._copy_log, tr('games.copy_the_log_e01862', 'Copy the log')),
            t.icon_button("folder", self._open_received, tr('games.open_the_received_folder_aae612', 'Open the Received folder')),
        ], spacing=0)
        self.control = t.panel(ft.Column([
            t.panel_header(tr('games.session_6959b4', 'Session'), self.status),
            # The checklist and the steps scroll; Start stays in view below them.
            ft.Container(t.fade(ft.Column([self.board_line, self.partner, self.offering, self.transfer, self.received,
                                                     self.steps],
                                          spacing=24,
                                          scroll=ft.ScrollMode.AUTO)),
                         padding=ft.Padding(18, 8, 18, 0), expand=3),
            ft.Container(ft.Column([
                self.action,
                ft.Row([t.text(tr('games.output_b2439b', 'Output'), 12, t.MUTED, weight=ft.FontWeight.W_600, expand=True), tools]),
                self.command_box,
            ], spacing=12), padding=ft.Padding(18, 14, 18, 8)),
            ft.Container(self.log.control, padding=ft.Padding(12, 0, 12, 12), expand=2),
        ], spacing=0, expand=True), width=t.SESSION_WIDTH)
        self.set_status(tr('games.ready_5fa7aa', 'Ready'), t.MUTED)
        app.board_listeners.append(lambda: self.refresh() if games.visible else None)

    def set_status(self, label: str, color: str) -> None:
        description = tr('games.idle_ab0171', 'Idle') if label == tr("games.ready_5fa7aa", "Ready") else label
        running = label.startswith(tr('games.running_f4ccae', 'Running'))
        self.status_dot.bgcolor = color
        self.status.tooltip = description
        self.status_label.label = description
        if running and not self.pulsing:
            self.status_dot.opacity = 0.35
        elif not running:
            self.status_dot.opacity = 1
        self.pulsing = running

    def _pulse(self, e) -> None:
        if self.pulsing:
            self.status_dot.opacity = 1 if self.status_dot.opacity < 1 else 0.35
            self.status_dot.update()

    def show(self, tool: Tool) -> None:
        if tool is not self.tool and not (self.app.process and self.app.process.running):
            self.log.clear()
            self.set_status(tr('games.ready_5fa7aa', 'Ready'), t.MUTED)
            self.seen, self.received.content, self.received.visible = {}, None, False
            self.transfer.content, self.transfer.visible = None, False
            self.partner.content, self.partner.visible, self.partner_state = None, False, None
            self.run_cards = {}
            self.traded = 0
        self.tool, self.shown_steps = tool, None
        self.refresh(update=False)

    def render_steps(self) -> None:
        """The console steps as the tool's fields stand: a task's own steps follow its choice."""
        steps = command.steps(self.tool, self.games.values)
        if steps != self.shown_steps:
            self.shown_steps = steps
            self.steps.content = t.section(tr('games.on_the_console_b01a90', 'On the console'), t.step_list(steps))

    def checklist(self) -> list[tuple[str, str, str, str]]:
        """(state, what, how to fix it, the page that fixes it) for each thing Start needs.
        state is ok, wait, warn (Start still allowed) or block."""
        items = [
            ("ok", tr('games.switch_keys_added_0e91df', 'Switch keys added'), "", "") if keys_found(self.app.settings.keys) else
            ("block", tr('games.add_your_switch_keys_c4f190', 'Add your Switch keys'), tr('games.choose_prod_keys_in_settings_259956', 'Choose prod.keys in Settings.'), "settings"),
        ]
        if self.app.settings.radio:
            radio = self.app.plugin_radio()
            items.append(("ok", tr('games.radio_78fa73', 'Radio: {value0}', value0=radio.label), "", "") if radio else
                         ("block", tr('games.radio_plugin_not_loaded_199762', 'Radio plugin not loaded'), tr('games.turn_its_plugin_on_or_pick_the_board_d49846', 'Turn its plugin on, or pick the board.'),
                          "plugins"))
        else:
            status = self.app.board_status()
            board_state = ("ok" if status.ready else "wait" if status.state == "checking" else
                           "block" if status.state in ("missing", "choose", "controller") else "warn")
            items.append((board_state, status.title, "" if status.ready else status.detail, "board"))
        if missing := translate(command.missing_offer(self.tool, self.games.values)):
            hint = tr('games.pick_a_species_then_press_build_e1b97f', ' Pick a species, then press Build.') if missing.startswith(tr('games.build_bdd254', 'Build')) else ""
            items.append(("block", tr('games.pokemon_to_offer_585ae1', 'Pokemon to offer'), missing + hint, ""))
        items += [("block", tr('games.check_the_options_c715a0', 'Check the options'), translate(problem), "") for problem in
                  command.problems(self.tool, self.games.values)]
        return items

    def render_checklist(self, items) -> ft.Control:
        if all(state == "ok" for state, *_ in items):
            return ft.Row([t.pixel_icon("checkbox-on", color=t.GREEN),
                           t.text(tr('games.ready_to_start_bc403c', 'Ready to start'), 13, t.TEXT, expand=True),
                           t.secondary_button(tr('games.board_4816cb', 'Board'), lambda e: self.app.navigate("board"), "cpu")], spacing=8)
        looks = {"ok": ("checkbox-on", t.GREEN), "wait": ("refresh", t.BLUE),
                 "warn": ("warning-diamond", t.AMBER), "block": ("warning-diamond", t.RED)}
        labels = {"settings": tr('games.settings_74a883', 'Settings'), "board": tr('games.board_4816cb', 'Board'), "plugins": tr('games.plugins_9514b7', 'Plugins')}
        rows = []
        for state, what, how, page in items:
            icon, color = looks[state]
            rows.append(ft.Row([
                ft.Container(t.pixel_icon(icon, color=color), padding=ft.Padding(0, 1, 0, 0)),
                ft.Column([t.text(what, 13, weight=ft.FontWeight.W_600)] +
                          ([t.text(how, 12, t.MUTED)] if how else []), spacing=1, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START))
            if page and state != "ok":
                rows.append(ft.Row([t.secondary_button(labels[page], lambda e, k=page: self.app.navigate(k))],
                                   alignment=ft.MainAxisAlignment.END))
        return t.section(tr('games.before_you_start_74e492', 'Before you start'), ft.Column(rows, spacing=10))

    def refresh(self, update: bool = True) -> None:
        tool, s = self.tool, self.app.settings
        running = bool(self.app.process and self.app.process.running)
        session = running and self.run is not None and self.run[0] is self.app.process
        here = session and self.running_tool is tool
        items = self.checklist()
        self.board_line.content = None if here else self.render_checklist(items)
        blocked = any(state == "block" for state, *_ in items)
        if here:
            action = t.button(tr('games.stop_cae7d5', 'Stop'), self._stop, "stop", t.RED, expand=True)
        elif session:
            action = t.button(tr('games.stop_and_start_7d52f6', 'Stop {value0} and start', value0=self.running_tool.name), self._start, "play", expand=True,
                              disabled=self.restart or blocked or bool(tool.unavailable))
        else:
            action = t.button(tr('games.start_e4bb9f', 'Start'), self._start, "play", expand=True,
                              disabled=self.app.busy or blocked or bool(tool.unavailable))
        self.action.content = ft.Row([action])
        self.render_steps()
        self.render_offering()
        try:
            self.command_text.value = shlex.join([tool.script, *command.build(
                tool, self.games.values, self.games.extra, s, stamp="STAMP")])
        except OSError as error:
            self.command_text.value = f"{error}"
        if update:
            self.control.update()

    def offered_entries(self) -> list[dict]:
        """The queued offers in the order the launcher trades them."""
        return [entry for field in self.tool.fields
                if field.kind == "pokemon" and command.applies(field, self.tool, self.games.values)
                for entry in command.offers(command.value_of(field, self.games.values))[:field.queue]
                if entry.get("file")]

    def render_offering(self) -> None:
        entries = self.offered_entries()
        shown = [(int(e.get("species") or 0), bool(e.get("shiny")), e.get("summary", ""),
                  int(e.get("form_id", e.get("options", {}).get("form", 0)))) for e in entries]
        if (shown, self.traded) == self.offered:
            return
        self.offered = (shown, self.traded)
        self.offering.visible = bool(shown)
        done = t.text(tr('games.traded_55a859', '{value0} traded', value0=self.traded), 12, t.GREEN) if self.traded else None
        if not shown:
            self.offering.content = None
        elif len(shown) == 1:
            species, shiny, summary, form = shown[0]
            self.offering.content = t.section(tr('games.offering_300e2b', 'Offering'), pokemon_row(self.app, species, shiny, summary, form=form),
                                              trailing=done)
        else:
            tiles = []
            for n, (species, shiny, summary, form) in enumerate(shown, start=1):
                sprite = Sprite(self.app, species, shiny, size=MINI, form=form)
                traded = n <= self.traded
                sprite.frame.tooltip = tr('games.trade_f2b1e2', 'Trade {value0}{value1}: {value2}', value0=n, value1=tr('games.done_28c78e', ' (done)') if traded else '', value2=summary_text(summary))
                tiles.append(ft.Stack([sprite.control, ft.Container(
                    t.pixel_icon("checkbox-on", color=t.GREEN), right=0, bottom=0, visible=traded)]))
            progress = (tr('games.of_traded_639878', '{value0} of {value1} traded', value0=min(self.traded, len(shown)), value1=len(shown)) if self.traded
                        else tr('games.trades_in_order_398ee7', '{value0} trades, in order', value0=len(shown)))
            self.offering.content = t.section(tr('games.offering_300e2b', 'Offering'), ft.Row(tiles, spacing=6, run_spacing=6, wrap=True),
                                              trailing=t.text(progress, 12, t.GREEN if self.traded else t.MUTED))

    def show_transfer(self, what: str, done: int, total: int) -> None:
        unit = tr('games.kb_59281a', 'KB') if what == "backup" else tr('games.parts', 'parts')
        title = tr('games.backing_up_the_save_caed94', 'Backing up the save') if what == "backup" else tr('games.putting_the_save_on_the_console_1871fd', 'Putting the save on the console')
        self.show_bar(title, done, total, tr('games.of_keep_the_switch_near_the_board_2c1cac', '{value0} of {value1} {value2}. Keep the Switch near the board.', value0=done, value1=total, value2=unit))

    def show_progress(self, done: int, total: int, unit: str, title: str) -> None:
        """A run's `[progress]` line (pokeldn.progress): the bar, how much, the rate and the time left."""
        rate = self.rates.setdefault(title, progress.Rate())
        rate.add(done, time.monotonic())
        parts = [amount_of(done, total, unit)]
        if rate.per_second and done < total:
            parts.append(per_second(rate.per_second, unit))
            parts.append(time_left(rate.left(total)))
        self.show_bar(title, done, total, " · ".join(parts))

    def show_bar(self, title: str, done: int, total: int, detail: str) -> None:
        self.transfer.visible = True
        self.transfer.content = t.section(title, ft.Column([
            ft.ProgressBar(value=min(done / total, 1) if total else None, color=t.BLUE, bgcolor=t.BORDER,
                           bar_height=6, border_radius=3),
            t.text(detail, 12, t.MUTED)], spacing=6))
        self.transfer.update()

    def show_card(self, card: dict) -> None:
        """A built-in run's `[panel]` card, as the run updates it, kept while it runs
        (GamesView.show_run_cards)."""
        if card.get("clear"):
            self.run_cards.pop(card["id"], None)
        else:
            self.run_cards[card["id"]] = card
        self.games.show_run_cards()

    def show_partner(self, partner) -> None:
        """Who the online trade meets, what they offer and whether they confirmed."""
        self.partner_state = partner
        looks = {"looking": ("refresh", t.BLUE, tr('games.connecting_to_the_relays_0fd3c0', 'Connecting to the relays')),
                 "waiting": ("refresh", t.BLUE, tr('games.looking_for_a_partner_597a66', 'Looking for a partner')),
                 "paired": ("user", t.GREEN, tr('games.trading_with_c3ae73', 'Trading with {value0}', value0=partner.name)),
                 "lost": ("warning-diamond", t.RED, tr('games.left_11e34c', '{value0} left', value0=partner.name or tr('games.your_partner_95514f', 'Your partner')))}
        icon, color, title = looks[partner.state]
        if partner.state in ("looking", "waiting"):
            code = partner.code.removeprefix("code ")
            detail = (tr('games.anyone_trading_this_game_online_without_a_code_can_be_y_409f57', 'Anyone trading this game online without a code can be your partner.')
                      if partner.code == tr('games.no_code_c08cc4', 'no code') else tr('games.your_partner_enters_the_same_code_c721c6', 'Your partner enters the same code: {value0}.', value0=code))
        elif partner.state == "lost":
            detail = tr('games.back_out_of_the_trade_on_the_console_start_again_to_fin_0e7c9d', 'Back out of the trade on the console. Start again to find a partner.')
        elif partner.offer:
            detail = tr('games.they_confirmed_confirm_on_your_console_to_trade_ca2f53', 'They confirmed. Confirm on your console to trade.') if partner.confirmed else \
                tr('games.waiting_for_them_to_confirm_43192a', 'Waiting for them to confirm.')
        else:
            detail = tr('games.offer_a_pokemon_on_your_console_theirs_appears_here_onc_55e467', 'Offer a Pokemon on your console; theirs appears here once they choose.')
        rows = [ft.Row([t.pixel_icon(icon, color=color),
                        ft.Column([t.text(title, 13, weight=ft.FontWeight.W_600),
                                   t.text(detail, 12, t.MUTED)], spacing=1, expand=True)],
                       spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)]
        if partner.offer and partner.state == "paired":
            species, shiny, summary = partner.offer
            rows.append(pokemon_row(self.app, species, shiny, summary))
            if partner.flag:
                rows.append(t.text(tr('games.pkhex_flags_it_a53261', 'PKHeX flags it: {value0}', value0=partner.flag), 12, t.AMBER))
        if partner.note:
            rows.append(t.text(partner.note, 12, t.AMBER))
        trailing = t.text(tr('games.traded_55a859', '{value0} traded', value0=partner.trades), 12, t.GREEN) if partner.trades else None
        self.partner.content = t.section(tr('games.partner_29035e', 'Partner'), ft.Column(rows, spacing=10), trailing=trailing)
        self.partner.visible = True
        self.partner.update()

    def scan_received(self, run: tuple) -> None:
        """Read each Pokemon file the run has saved so far; a file still growing is read again."""
        process, stamp, game = run
        changed = False
        for path in received.session_files(self.app.settings.received, stamp):
            try:
                size, mtime = os.path.getsize(path), os.path.getmtime(path)
            except OSError:
                continue
            if path in self.seen and self.seen[path][:2] == (size, mtime):
                continue
            try:
                info = SERVICE.check(game, path)
            except Exception:
                info = None
            if self.run is not run:
                return
            self.seen[path] = (size, mtime, info)
            changed = True
            if info is not None:
                try:
                    bank.deposit(game, path, info)
                except OSError as error:
                    self.app.ui(lambda m=f'[app] Not banked: {error}': self.log.add(m))
        if changed:
            self.app.ui(lambda: self.render_received(process))

    def render_received(self, process) -> None:
        if self.run is None or self.run[0] is not process:
            return
        rows = []
        for path, (_, _, info) in list(self.seen.items()):
            name = os.path.basename(path)
            if info is None:
                rows.append(pokemon_row(self.app, 0, False, tr('games.not_read_by_pkhex_ba6380', 'Not read by PKHeX · {value0}', value0=name), path))
            else:
                rows.append(pokemon_row(self.app, int(info.get("species_id") or 0), bool(info.get("shiny")),
                                        pokemon_summary(info), path))
        self.received.visible = True
        self.received.content = t.section(tr('games.received_49f19b', 'Received'), ft.Column(rows, spacing=8),
                                       trailing=t.icon_button("folder", self._open_received,
                                                              tr('games.open_the_received_folder_aae612', 'Open the Received folder')))
        self.received.update()

    def _toggle_command(self, e) -> None:
        self.command_box.visible = not self.command_box.visible
        self.command_box.update()

    async def _copy_log(self, e) -> None:
        await self.app.copy(self.log.text())

    def _open_received(self, e) -> None:
        open_folder(os.path.expanduser(self.app.settings.received))

    def _start(self, e) -> None:
        tool, s = self.tool, self.app.settings
        process = self.app.process
        if (process and process.running and self.run is not None and self.run[0] is process
                and self.running_tool is not tool):
            # one board, one session: the running one leaves the network first
            self.restart = True
            self._stop(e)
            self.refresh()
            return
        if self.app.busy:
            return
        radio = self.app.plugin_radio() if s.radio else None
        port = radio.scheme if radio else "" if s.radio else self.app.radio_port()
        problems = [p for p in (
            "" if port else tr('games.the_radio_plugin_is_not_loaded_3f5a2c', 'The radio plugin is not loaded.') if s.radio else
            tr('games.no_board_found_plug_it_in_or_pick_one_on_the_board_page_39a182', 'No board found. Plug it in, or pick one on the Board page.'),
            "" if os.path.isfile(os.path.expanduser(s.keys)) else tr('games.choose_your_prod_keys_in_settings_eb3db2', 'Choose your prod.keys in Settings.'),
            command.missing_offer(tool, self.games.values), *command.problems(tool, self.games.values)) if p]
        self.log.clear()
        if problems:
            for p in problems:
                self.log.add(f'[app] {p}')
            self.set_status(tr('games.not_started_ba35f0', 'Not started'), t.RED)
            self.refresh()
            return
        try:
            command.prepare(tool, self.games.values)
        except (OSError, ValueError) as error:
            self.log.add(f'[app] {error}')
            self.set_status(tr('games.not_started_ba35f0', 'Not started'), t.RED)
            self.refresh()
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        args = command.build(tool, self.games.values, self.games.extra, s, stamp)
        for folder in (SESSION / "captures", os.path.expanduser(s.received)):
            os.makedirs(folder, exist_ok=True)
        trace = f"captures/{tool.key}-{stamp}_esp32.trace" if s.board_trace else None
        self.log.add(f'[app] {tool.name} · {self.games.game.name} · radio {port}')
        self.seen, self.received.content, self.received.visible = {}, None, False
        self.transfer.content, self.transfer.visible, self.rates = None, False, {}
        self.partner.content, self.partner.visible, self.partner_state = None, False, None
        self.run_cards = {}
        self.traded = 0
        self.bank_trades = bank.TradeSession(self.offered_entries())
        self.stopping = False
        self.app.process_label = tool.name
        self.running_tool = tool
        self.app.process = runner.Process(["--run", tool.script, *args], str(SESSION),
                                          runner.base_env(s, port, trace), self._line, self._exited,
                                          popups=self.app.popups, label=tool.name)
        self.run = (self.app.process, stamp, self.games.game.key)
        self.games.panes.show(2)
        threading.Thread(target=self._tick, daemon=True).start()
        self.refresh()

    def _line(self, line: str) -> None:
        if moved := progress.read(line):
            self.app.ui(lambda: self.show_progress(*moved))
            return
        if line.startswith(panel.PREFIX):
            owner = plugins.owner(self.running_tool.key) if self.running_tool else None
            shown = panel.read(line)
            if shown is None:
                self.log.add(f"[app] {tr('games.panel_unreadable', 'A [panel] line the app cannot read:')} {line[:160]}")
            if owner is not None and shown is not None and panels.apply(owner.id, shown):
                self.app.ui(lambda: self.games.plugin_changed(owner.id))
            elif owner is None and shown is not None and "id" in shown:
                self.app.ui(lambda: self.show_card(shown))
            return
        self.log.add(line)
        if saving := received.save_progress(line):
            self.app.ui(lambda: self.show_transfer(*saving))
        partner = online.update(self.partner_state, line)
        if partner is not self.partner_state:
            self.partner_state = partner
            self.app.ui(lambda p=partner: self.show_partner(p) if self.partner_state is p else None)
        n = received.trades_done(line)
        if n is not None and n > self.traded:
            bank_trades = self.bank_trades
            def mark():
                if self.bank_trades is not bank_trades:
                    return
                try:
                    bank_trades.advance(n)
                except OSError as error:
                    self.log.add(f'[app] Bank completion failed: {error}')
                self.traded = bank_trades.completed
                self.render_offering()
                self.offering.update()
            self.app.ui(mark)

    def _tick(self) -> None:
        run = self.run
        process = run[0]
        while process.running:
            elapsed = int(time.monotonic() - process.started)
            self.app.ui(lambda e=elapsed: (self.set_status(tr('games.running_f261eb', 'Running {value0:02d}:{value1:02d}', value0=e // 60, value1=e % 60), t.BLUE),
                                           self.status.update())
                        if self.app.process is process and process.running else None)
            self.scan_received(run)
            time.sleep(1)
        self.scan_received(run)   # a launcher may write its last file as it closes

    def _stop(self, e) -> None:
        self.stopping = True
        self.log.add('[app] Stopping: the entry point leaves the network and closes the board.')
        self.app.process.stop()

    def _exited(self, code: int) -> None:
        def done():
            if self.stopping:
                self.set_status(tr('games.stopped_1a4f63', 'Stopped'), t.MUTED)
            elif code == 0:
                self.set_status(tr('games.finished_7804f7', 'Finished'), t.GREEN)
            else:
                self.set_status(tr('games.failed_1df702', 'Failed ({value0})', value0=code), t.RED)
            self.log.add(f'[app] Exited with code {code}.')
            self.run_cards = {}
            self.games.show_run_cards()
            bank.prune(self.app.settings)     # the traded ones leave the queue too
            if self.games.visible and self.games.tool is self.running_tool:
                self.games.render_body()      # a backup has joined the save library
                self.games.cards.update()
            if self.restart:
                self.restart = False
                self._start(None)
                return
            self.refresh()
        self.app.ui(done)

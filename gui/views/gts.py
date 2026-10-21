from pokeldn.app import i18n
"""The GTS: banked Pokemon listed against a wanted species on public relays, other players' listings,
and offers on them [pokeldn.app.gts, docs/online.md, The GTS]."""
from pokeldn.app.i18n import ref as _ref
from pokeldn.app.i18n import text as tr, ref
import re
import threading
import time

import flet as ft

from gui import theme as t
from gui.views.bank import NAMES, game_icon
from gui.views.sprites import MINI, SIZE, Sprite
from gui.localization import SERVICE, display_summary, summary_text, translate
from pokeldn import __version__, pokemon
from pokeldn.app import bank
from pokeldn.app.gts import GtsError, Service
from pokeldn.app.paths import GTS
from pokeldn.online import gts

ANY = "-"
STATUS = {"active": (ref('core.gts.listed_78797a'), t.BLUE, "globe"), "traded": (ref('core.gts.traded_834b40'), t.GREEN, "checkbox-on"),
          "withdrawn": (ref('core.gts.taken_down_70e371'), t.MUTED, "close"), "ended": (ref('core.gts.ended_7cdc80'), t.MUTED, "clock"),
          "waiting": (ref('core.gts.waiting_for_the_lister_bcc6f9'), t.BLUE, "clock"), "returned": (ref('core.gts.back_in_the_bank_10c0de'), t.AMBER, "repeat")}


def service(app) -> Service:
    """The app's one GTS client, started on first use; it answers offers while the app is open."""
    if getattr(app, "gts", None) is None:
        app.gts = Service(trainer=app.settings.ot, app=__version__)
        app.gts.start()
    return app.gts


def resume(app) -> None:
    """Start the client when an earlier session left a listing or an offer to settle."""
    if GTS.is_dir() and any(GTS.glob("*/state.json")):
        service(app)


def level_of(entry: bank.Entry) -> int:
    found = re.search(r"level (\d+)", entry.summary)
    return int(found.group(1)) if found else 0


def _when(seconds: float) -> str:
    return i18n.text("core.presentation.date", value=seconds)


class GtsView:
    def __init__(self, app):
        self.app = app
        self.visible = False
        self.species: list[tuple[str, str]] = []      # (id, name), every game's
        self.canonical_species: dict[str, str] = {}  # English names for persisted/published Wants
        self.search = "has"
        self.chosen = ANY
        self.selected: tuple | str = ""                 # a listing's (key, d), or one of ours by id
        self.working = False
        self.pending = False
        self.status = t.text("", 12, t.MUTED)
        self.mine = ft.Column(spacing=2)
        self.grid = ft.Row(spacing=8, run_spacing=8, wrap=True)
        self.heading = t.text("", 12, t.MUTED)
        self.detail = ft.Column(spacing=24, scroll=ft.ScrollMode.AUTO, expand=True)
        self.note = t.text("", 12, t.MUTED)
        self.picker = t.dropdown([(ANY, tr('core.gts.any_pokemon_b21058'))], ANY, self._pick, enable_filter=True, editable=True,
                                 menu_height=320)
        self.panes = t.Panes(
            (tr('core.gts.pane_gts'), "globe", t.panel(ft.Column([
                t.panel_header(tr('core.gts.gts_c530c8'), t.icon_button("refresh", lambda e: self._browse(), tr('core.gts.look_again_d36fee'))),
                ft.Container(ft.Column([
                    self.status,
                    t.segmented([("has", tr('core.gts.offered_95e700'), "package"), ("wants", tr('core.gts.wanted_c29683'), "search")], self.search,
                                self._mode),
                    self.picker,
                    t.button(tr('core.gts.deposit_a_pokemon_69907e'), lambda e: self._deposit_dialog(), "upload"),
                    t.section(tr('core.gts.yours_54b26f'), self.mine),
                ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True), padding=ft.Padding(14, 4, 14, 14),
                    expand=True),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH)),
            (tr('core.gts.pane_listings'), "search", t.fade(ft.ListView([ft.Container(self.heading, padding=ft.Padding(4, 14, 4, 0)), self.grid],
                               spacing=12, padding=ft.Padding(0, 0, 0, 24), expand=True))),
            (tr('core.gts.pane_listing'), "label", t.panel(ft.Column([
                t.panel_header(tr('core.gts.listing_fc7f1a')),
                ft.Container(ft.Column([self.detail, self.note], spacing=8, expand=True),
                             padding=ft.Padding(18, 8, 18, 18), expand=True),
            ], spacing=0, expand=True), width=t.SESSION_WIDTH)))
        self.control = self.panes.control

    @property
    def client(self) -> Service:
        return service(self.app)

    def enter(self, **_) -> None:
        self.visible = True
        if self._changed not in self.client.listeners:
            self.client.listeners.append(self._changed)
        if not self.species:
            threading.Thread(target=self._load_species, daemon=True).start()
        self._browse(update=False)
        self.render()

    def leave(self) -> None:
        self.visible = False

    def _load_species(self) -> None:
        names: dict[int, str] = {}
        canonical: dict[str, str] = {}
        for game in NAMES:
            try:
                canonical.update((str(s["id"]), s["name"]) for s in pokemon.SERVICE.species(game))
                names.update((s["id"], s["name"]) for s in SERVICE.species(game))
            except (OSError, pokemon.BuilderError):
                continue

        def done():
            self.species = sorted(((str(k), v) for k, v in names.items()), key=lambda s: s[1])
            self.canonical_species = canonical
            self.picker.options = [ft.DropdownOption(key=ANY, text=tr('core.gts.any_pokemon_b21058'))] + [
                ft.DropdownOption(key=k, text=v) for k, v in self.species]
            if self.visible:
                self.picker.update()
        self.app.ui(done)

    def _changed(self) -> None:
        """From a relay thread: draw again once, however many events arrive together."""
        if self.pending or not self.visible:
            return
        self.pending = True

        def draw():
            self.pending = False
            if self.visible:
                self.render()
                self.control.update()
        self.app.ui(draw)

    # Searching

    def _filters(self) -> dict:
        species = int(self.chosen) if self.chosen not in (None, ANY) else None
        return {"has": species} if self.search == "has" else {"wants": species}

    def _browse(self, update=True) -> None:
        self.client.browse(**self._filters())
        if update:
            self.render()
            self.control.update()

    def _mode(self, key: str) -> None:
        self.search = key
        self._browse()

    def _pick(self, e) -> None:
        self.chosen = e.control.value or ANY
        self._browse()

    # Drawing

    def render(self) -> None:
        client = self.client
        relays = client.connected()
        listings = client.open_listings(**self._filters())
        self.status.value = (tr('core.gts.of_relays_connected_e3c2ac', value0=relays, value1=len(gts.relay_urls())) if relays
                             else tr('core.gts.connecting_to_the_relays_ee096f'))
        if listings:
            self.heading.value = (tr('core.gts.open_listing_count', count=len(listings)) if len(listings) == 1 else
                                  tr('core.gts.open_listings_count', count=len(listings)))
        elif client.loaded():
            self.heading.value = tr('core.gts.no_open_listing_matches_deposit_one_of_yours_from_the_l_cd97a2')
        else:
            self.heading.value = tr('core.gts.reading_the_listings_from_the_relays_49620c')
        self.grid.controls = [self._tile(x) for x in listings]
        self.mine.controls = [self._mine_row(s) for s in client.mine()] or [
            t.text(tr('core.gts.nothing_listed_or_offered_df021f'), 12, t.FAINT)]
        self.render_detail(listings)

    def _tile(self, listing: gts.Listing) -> ft.Control:
        active = self.selected == (listing.key, listing.d)
        shown = listing.pokemon
        return ft.Container(ft.Row([
            ft.Stack([Sprite(self.app, int(shown.get("species_id") or 0), bool(shown.get('shiny')), size=MINI).control,
                      ft.Container(game_icon(listing.game, 16), right=0, bottom=0)]),
            t.pixel_icon("arrows-horizontal", size=12, color=t.FAINT),
            Sprite(self.app, listing.wants.species, size=MINI).control,
        ], spacing=4, tight=True), padding=4, border_radius=14,
            tooltip=tr('core.gts.level_for_4ade2a', value0=translate(shown.get('species', '')), value1=shown.get('level'), value2=wanted_text(listing.wants)),
            border=ft.Border.all(2, t.BLUE if active else ft.Colors.TRANSPARENT),
            on_click=lambda e, k=(listing.key, listing.d): self._select(k))

    def _mine_row(self, state: dict) -> ft.Control:
        label, color, icon = STATUS[state["status"]]
        title = translate(state["info"].get("species", ""))
        if state["role"] == "listing":
            title += tr('core.gts.for_76b8cb', value0=wanted_text(gts.Wants(**state['wants'])))
        else:
            title += tr('core.gts.offered_for_a2a379', value0=translate(gts.parse_listing(state['listing']).pokemon.get('species', '')) if state['listing'] else '')
        active = self.selected == state["id"]
        return ft.Container(ft.Row([
            Sprite(self.app, int(state["info"].get("species_id") or 0), bool(state["info"].get('shiny')),
                   size=MINI).control,
            ft.Column([t.text(title, 12, t.TEXT, weight=ft.FontWeight.W_600, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS),
                       t.badge(label, color, icon)], spacing=2, expand=True),
        ], spacing=8), padding=ft.Padding(4, 4, 6, 4), border_radius=12,
            bgcolor=t.SELECTED if active else None, on_click=lambda e, i=state["id"]: self._select(i))

    def _select(self, key) -> None:
        self.panes.show(1, update=False)
        self.selected = key
        self.note.value = ""
        self.render()
        self.control.update()

    def render_detail(self, listings: list[gts.Listing]) -> None:
        if isinstance(self.selected, str) and self.selected:
            state = next((s for s in self.client.mine() if s["id"] == self.selected), None)
            if state:
                self.detail.controls = self._mine_detail(state)
                return
        listing = next((x for x in listings if (x.key, x.d) == self.selected), None)
        if listing is None:
            self.detail.controls = [t.text(
                tr('core.gts.pick_a_listing_to_see_the_pokemon_and_what_its_trainer__d09e48'), 13, t.MUTED)]
            return
        self.detail.controls = [self._about(listing.pokemon, listing.game),
                                t.section(tr('core.gts.asks_for_f07bf1'), ft.Row([Sprite(self.app, listing.wants.species, size=MINI).control,
                                                              t.text(wanted_text(listing.wants), 13)], spacing=10)),
                                t.text(tr('core.gts.from_open_until_d81849', value0=listing.trainer or tr('core.gts.a_trainer_bda66d'), value1=_when(listing.expires)),
                                       12, t.FAINT),
                                t.section(tr('core.gts.your_pokemon_that_answer_it_2c53fc'), self._answers(listing))]

    def _about(self, shown: dict, game: str) -> ft.Control:
        shown = {**shown, **{key: translate(shown.get(key, "")) for key in ("species", "nature", "ability", "ball", "held_item")},
                 "moves": [translate(move) for move in shown.get("moves", ())]}
        facts = [shown.get("nature"), shown.get("ability"), shown.get("ball")]
        if shown.get("held_item"):
            facts.append(tr('core.gts.holding_b3a475', value0=shown['held_item']))
        return ft.Row([
            Sprite(self.app, int(shown.get("species_id") or 0), bool(shown.get('shiny')), size=SIZE).control,
            ft.Column([
                t.text(tr('core.gts.level_dcff87', value0=shown['species'], value1=shown.get('level')) + (tr('core.gts.shiny_3e4562') if shown.get('shiny') else ""),
                       15, weight=ft.FontWeight.W_600),
                t.text(i18n.join(((str(f) for f in facts if f)), " · "), 12, t.MUTED),
                t.text(tr('core.presentation.list_separator').join(shown.get("moves") or []), 12, t.MUTED),
                ft.Row([game_icon(game), t.text(tr('core.gts.in_ot_abad3b', value0=NAMES.get(game, game), value1=shown.get('ot')), 12, t.SOFT)],
                       spacing=6),
            ], spacing=4, expand=True),
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START)

    def _answers(self, listing: gts.Listing) -> ft.Control:
        held = [e for e in bank.entries() if e.species_id == listing.wants.species and e.legal
                and not listing.wants.refusal(e.species_id, level_of(e))
                and not bank.queued(self.app.settings, e.id)]
        if not held:
            return t.text(tr('core.gts.your_bank_holds_no_legal_that_is_not_queued_for_a_trade_66b4ef', value0=wanted_text(listing.wants)),
                          12, t.FAINT)
        return ft.Column([ft.Row([
            Sprite(self.app, e.species_id, e.shiny, size=MINI).control,
            ft.Column([t.text(e.summary, 12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                       ft.Row([game_icon(e.game, 16), t.text(NAMES[e.game], 11, t.MUTED)], spacing=4)],
                      spacing=2, expand=True),
            t.button(tr('core.gts.offer_0cf57c'), lambda ev, x=e: self._confirm_offer(listing, x), "arrows-horizontal",
                     disabled=self.working),
        ], spacing=8) for e in held], spacing=8)

    def _mine_detail(self, state: dict) -> list[ft.Control]:
        label, color, icon = STATUS[state["status"]]
        controls = [self._about(state["info"], state["game"]), t.badge(label, color, icon)]
        if state["role"] == "listing":
            wants = gts.Wants(**state["wants"])
            controls.append(t.text(tr('core.gts.asks_for_open_until_offer_answered_7137e1', value0=wanted_text(wants), value1=_when(state['expires']), value2=len(state['answers']), value3='s' * (len(state['answers']) != 1)),
                                   12, t.MUTED))
            if state["status"] == "traded":
                controls.append(t.text(tr('core.gts.traded_with_what_came_back_is_in_the_bank_d8f8bc', value0=state['partner'] or tr('core.gts.a_trainer_bda66d')),
                                       12, t.SOFT))
            if state["status"] == "active":
                controls.append(t.secondary_button(tr('core.gts.take_it_down_9ed702'), lambda e: self._withdraw(state), "close"))
        else:
            listing = gts.parse_listing(state["listing"])
            if listing:
                controls.append(t.text(tr('core.gts.offered_for_level_from_6f5c29', value0=translate(listing.pokemon.get('species', '')), value1=listing.pokemon.get('level'), value2=listing.trainer or tr('core.gts.a_trainer_bda66d')), 12, t.MUTED))
            if state["status"] == "waiting":
                controls.append(t.text(tr('core.gts.the_trade_happens_the_next_time_the_lister_s_app_is_ope_23acca'), 12, t.FAINT))
            if state["why"]:
                controls.append(t.text(state["why"][0].upper() + state["why"][1:] + ".", 12,
                                       t.AMBER if state["status"] == "returned" else t.SOFT))
        if state["status"] not in ("active", "waiting"):
            controls.append(t.secondary_button(tr('core.gts.clear_from_the_list_13c20d'), lambda e: self._forget(state), "trash"))
        return controls

    # Actions

    def _work(self, label: str, action, done_text: str) -> None:
        self.working = True
        self._say(label, t.BLUE)

        def work():
            try:
                action()
                problem = ""
            except (OSError, GtsError, pokemon.BuilderError) as error:
                problem = str(error)

            def done():
                self.working = False
                self.render()
                self.control.update()
                self._say(problem or done_text, t.RED if problem else t.MUTED)
            self.app.ui(done)
        threading.Thread(target=work, daemon=True).start()

    def _confirm_offer(self, listing: gts.Listing, entry: bank.Entry) -> None:
        def go(e):
            self.app.page.pop_dialog()
            self._work(tr('core.gts.pkhex_is_checking_it_e51442'), lambda: self.client.offer(listing, entry),
                       tr('core.gts.offered_yours_lists_the_answer_once_the_lister_s_app_se_e8e078'))

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('core.gts.offer_e4293e', value0=display_summary(entry).split(' · ')[0]), 18),
            content=t.text(tr('core.gts.it_leaves_your_bank_and_waits_for_the_lister_s_app_you__ff4ccc', value0=translate(listing.pokemon.get('species', ''))), 13, t.MUTED, width=400),
            actions=[t.button(tr('core.gts.cancel_19766e'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('core.gts.offer_0cf57c'), go, "arrows-horizontal")]))

    def _withdraw(self, state: dict) -> None:
        self._work(tr('core.gts.taking_it_down_921e7c'), lambda: self.client.withdraw(state["id"]),
                   tr('core.gts.taken_down_the_pokemon_is_back_in_the_bank_e3069b'))

    def _forget(self, state: dict) -> None:
        self.client.forget(state["id"])
        self.selected = ""
        self.render()
        self.control.update()

    def _deposit_dialog(self) -> None:
        held = [e for e in bank.entries() if e.legal and not bank.queued(self.app.settings, e.id)]
        if not held:
            self._say(tr('core.gts.the_bank_holds_no_legal_pokemon_that_is_not_queued_for__a9b617'), t.AMBER)
            return
        if not self.species:
            self._say(tr('core.gts.pkhex_is_still_reading_the_species_list_try_again_in_a__9f683f'), t.AMBER)
            return
        choice = t.dropdown([(e.id, tr('core.gts._99a2ff', value0=display_summary(e).split(' · ')[0], value1=display_summary(e).split(' · ')[1] if len(display_summary(e).split(' · ')) > 1 else "", value2=NAMES[e.game])) for e in held], held[0].id, enable_filter=True,
                            editable=True, menu_height=320)
        wanted = t.dropdown(self.species, None, enable_filter=True, editable=True, menu_height=320)
        low = t.field(value="1", mono=True, width=80, digits=True, limit=3)
        high = t.field(value="100", mono=True, width=80, digits=True, limit=3)
        message = t.text("", 12, t.RED)

        def go(e):
            entry = next((x for x in held if x.id == choice.value), None)
            name = self.canonical_species.get(wanted.value or "")
            levels = (low.value or "").strip(), (high.value or "").strip()
            if entry is None or not name:
                message.value = tr('core.gts.pick_your_pokemon_and_the_one_you_ask_for_536386')
            elif not all(v.isdigit() for v in levels) or not 1 <= int(levels[0]) <= int(levels[1]) <= 100:
                message.value = tr('core.gts.the_levels_go_from_1_to_100_the_first_no_higher_than_th_e48832')
            else:
                self.app.page.pop_dialog()
                wants = gts.Wants(int(wanted.value), name, int(levels[0]), int(levels[1]))
                self._work(tr('core.gts.pkhex_is_checking_it_e51442'), lambda: self.client.deposit(entry, wants),
                           tr('core.gts.listed_for_30_days_your_app_trades_it_when_it_is_open_a_cd4947'))
                return
            message.update()

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('core.gts.deposit_a_pokemon_69907e'), 18),
            content=ft.Column([
                t.labeled_control(tr('core.gts.your_pokemon_232a04'), choice),
                t.labeled_control(tr('core.gts.ask_for_2b1a7d'), wanted),
                ft.Row([t.labeled_control(tr('core.gts.lowest_level_44ad69'), low), t.labeled_control(tr('core.gts.highest_level_5cabfc'), high)], spacing=10),
                t.text(tr('core.gts.it_leaves_the_bank_while_listed_the_first_offer_that_an_d65652'), 12, t.FAINT),
                message,
            ], spacing=14, tight=True, width=420),
            actions=[t.button(tr('core.gts.cancel_19766e'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('core.gts.deposit_0da00b'), go, "upload")]))

    def _say(self, text: str, color: str) -> None:
        self.note.value, self.note.color = text, color
        try:
            self.note.update()
        except RuntimeError:
            pass


def wanted_text(wants: gts.Wants) -> str:
    name = translate(wants.name)
    if (wants.min_level, wants.max_level) == (1, 100):
        return name
    return tr('core.presentation.wanted_levels', name=name, low=wants.min_level, high=wants.max_level)

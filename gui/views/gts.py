"""The GTS: banked Pokemon listed against a wanted species on public relays, other players' listings,
and offers on them [pokeldn.app.gts, docs/online.md, The GTS]."""
from pokeldn.app.i18n import t as tr
import re
import threading
import time

import flet as ft

from gui import theme as t
from gui.views.bank import NAMES, game_icon
from gui.views.sprites import MINI, SIZE, Sprite
from gui.localization import SERVICE, summary_text, translate
from pokeldn import __version__, pokemon
from pokeldn.app import bank
from pokeldn.app.gts import GtsError, Service, wanted
from pokeldn.app.paths import GTS
from pokeldn.online import gts

ANY = "-"
SORTS = {"newest": lambda x: -x.created, "ending": lambda x: x.expires,
         "dex": lambda x: (x.pokemon.get("species_id") or 0, -x.created),
         "level": lambda x: (-(x.pokemon.get("level") or 0), -x.created)}
STATUS = {"active": (tr('gts.listed_78797a', 'Listed'), t.BLUE, "globe"), "traded": (tr('gts.traded_834b40', 'Traded'), t.GREEN, "checkbox-on"),
          "withdrawn": (tr('gts.taken_down_70e371', 'Taken down'), t.MUTED, "close"), "ended": (tr('gts.ended_7cdc80', 'Ended'), t.MUTED, "clock"),
          "waiting": (tr('gts.waiting_for_the_lister_bcc6f9', 'Waiting for the lister'), t.BLUE, "clock"), "returned": (tr('gts.back_in_the_bank_10c0de', 'Back in the bank'), t.AMBER, "repeat")}


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


def answers(entry: bank.Entry, asked) -> bool:
    return not gts.refusal(asked, entry.species_id, level_of(entry), entry.shiny)


def sparkles(size: int = 12) -> ft.Control:
    return t.pixel_icon("sparkles", size=size, color=t.AMBER, tooltip=tr('gts.shiny_039a0a', 'Shiny'))


def _when(seconds: float) -> str:
    return time.strftime(tr('gts.d_b_y_ede2cc', '%d %b %Y'), time.localtime(seconds))


class GtsView:
    def __init__(self, app):
        self.app = app
        self.visible = False
        self.species: list[tuple[str, str]] = []      # (id, name), every game's
        self.canonical_species: dict[str, str] = {}  # English names for persisted/published Wants
        self.search = "has"
        self.chosen = ANY
        self.shiny_only = False
        self.answerable = False
        self.sort = "newest"
        self.selected: tuple | str = ""                 # a listing's (key, d), or one of ours by id
        self.working = False
        self.pending = False
        self.status = t.text("", 12, t.MUTED)
        self.mine = ft.Column(spacing=2)
        self.grid = ft.Row(spacing=8, run_spacing=8, wrap=True)
        self.heading = t.text("", 12, t.MUTED)
        self.detail = ft.Column(spacing=24, scroll=ft.ScrollMode.AUTO, expand=True)
        self.note = t.text("", 12, t.MUTED)
        self.picker = t.dropdown([(ANY, tr('gts.any_pokemon_b21058', 'Any Pokemon'))], ANY, self._pick, enable_filter=True, editable=True,
                                 menu_height=320)
        self.panes = t.Panes(
            (tr('gts.pane_gts', 'GTS'), "globe", t.panel(ft.Column([
                t.panel_header(tr('gts.gts_c530c8', 'GTS'), t.icon_button("refresh", lambda e: self._browse(), tr('gts.look_again_d36fee', 'Look again'))),
                ft.Container(ft.Column([
                    self.status,
                    t.segmented([("has", tr('gts.offered_95e700', 'Offered'), "package"), ("wants", tr('gts.wanted_c29683', 'Wanted'), "search")], self.search,
                                self._mode),
                    self.picker,
                    ft.Row([t.switch(self.shiny_only, self._shiny), t.text(tr('gts.shiny_only_6b3a0f', 'Shiny only'), 13, t.SOFT)],
                           spacing=6, tight=True),
                    ft.Row([t.switch(self.answerable, self._answerable),
                            t.text(tr('gts.my_bank_can_answer_2d7c1e', 'My bank can answer'), 13, t.SOFT)], spacing=6, tight=True),
                    t.button(tr('gts.deposit_a_pokemon_69907e', 'Deposit a Pokemon'), lambda e: self._deposit_dialog(), "upload"),
                    t.section(tr('gts.yours_54b26f', 'Yours'), self.mine),
                ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True), padding=ft.Padding(14, 4, 14, 14),
                    expand=True),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH)),
            (tr('gts.pane_listings', 'Listings'), "search", t.fade(ft.ListView([ft.Container(ft.Row([
                ft.Container(self.heading, expand=True),
                ft.Container(t.dropdown([("newest", tr('gts.sort_newest', 'Newest first')),
                                         ("ending", tr('gts.sort_ending', 'Ending soonest')),
                                         ("dex", tr('gts.sort_dex', 'Pokedex number')),
                                         ("level", tr('gts.sort_level', 'Highest level'))], self.sort,
                                        on_select=lambda e: self._sorted(e.control.value)), width=200),
            ], spacing=8), padding=ft.Padding(4, 14, 4, 0)), self.grid],
                               spacing=12, padding=ft.Padding(0, 0, 0, 24), expand=True))),
            (tr('gts.pane_listing', 'Listing'), "label", t.panel(ft.Column([
                t.panel_header(tr('gts.listing_fc7f1a', 'Listing')),
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
            self.picker.options = [ft.DropdownOption(key=ANY, text=tr('gts.any_pokemon_b21058', 'Any Pokemon'))] + [
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

    def _shiny(self, e) -> None:
        self.shiny_only = bool(e.control.value)
        self.render()
        self.control.update()

    def _answerable(self, e) -> None:
        self.answerable = bool(e.control.value)
        self.render()
        self.control.update()

    def _sorted(self, key: str) -> None:
        self.sort = key
        self.render()
        self.control.update()

    def _held(self) -> list[bank.Entry]:
        """Banked Pokemon free to offer: legal and not queued for a trade."""
        return [e for e in bank.entries() if e.legal and not bank.queued(self.app.settings, e.id)]

    def _shown(self) -> list[gts.Listing]:
        listings = self.client.open_listings(**self._filters(), shiny=self.shiny_only)
        if self.answerable:
            held = self._held()
            listings = [x for x in listings if any(answers(e, x.wanted) for e in held)]
        return sorted(listings, key=SORTS[self.sort])

    # Drawing

    def render(self) -> None:
        client = self.client
        relays = client.connected()
        listings = self._shown()
        self.status.value = (tr('gts.of_relays_connected_e3c2ac', '{value0} of {value1} relays connected', value0=relays, value1=len(gts.relay_urls())) if relays
                             else tr('gts.connecting_to_the_relays_ee096f', 'Connecting to the relays...'))
        if listings:
            self.heading.value = (tr('gts.open_listing_count', '{count} open listing', count=len(listings)) if len(listings) == 1 else
                                  tr('gts.open_listings_count', '{count} open listings', count=len(listings)))
        elif client.loaded():
            self.heading.value = tr('gts.no_open_listing_matches_deposit_one_of_yours_from_the_l_cd97a2', 'No open listing matches. Deposit one of yours from the left.')
            if self.shiny_only or self.answerable:
                self.heading.value = tr('gts.no_open_listing_matches_these_filters_4f1c2b', 'No open listing matches these filters.')
        else:
            self.heading.value = tr('gts.reading_the_listings_from_the_relays_49620c', 'Reading the listings from the relays...')
        self.grid.controls = [self._tile(x) for x in listings]
        self.mine.controls = [self._mine_row(s) for s in client.mine()] or [
            t.text(tr('gts.nothing_listed_or_offered_df021f', 'Nothing listed or offered.'), 12, t.FAINT)]
        self.render_detail(listings)

    def _tile(self, listing: gts.Listing) -> ft.Control:
        active = self.selected == (listing.key, listing.d)
        offered = self.client.offered(listing) is not None
        shown = listing.pokemon
        first, more = listing.wants, len(listing.also)
        name = translate(shown.get('species', ''))
        if shown.get("shiny"):
            name = tr('gts.shiny_name_8e2f7a', 'shiny {name}', name=name)
        tip = tr('gts.level_for_4ade2a', '{value0} level {value1} for {value2}', value0=name, value1=shown.get('level'), value2=wanted_list_text(listing.wanted))
        if offered:
            tip += "\n" + tr('gts.you_offered_waiting_for_the_lister_5e1b0c', 'You offered; waiting for the lister.')
        return ft.Container(ft.Row([
            ft.Stack([Sprite(self.app, int(shown.get("species_id") or 0), bool(shown.get("shiny")), size=MINI).control,
                      ft.Container(game_icon(listing.game, 16), right=0, bottom=0),
                      *([ft.Container(sparkles(), left=0, top=0)] if shown.get("shiny") else [])]),
            t.pixel_icon("arrows-horizontal", size=12, color=t.FAINT),
            ft.Stack([Sprite(self.app, first.species, first.shiny, size=MINI).control,
                      *([ft.Container(sparkles(), left=0, top=0)] if first.shiny else []),
                      *([ft.Container(t.text(f"+{more}", 11, t.SOFT, weight=ft.FontWeight.W_600), right=0, bottom=0)]
                        if more else []),
                      *([ft.Container(t.pixel_icon("clock", size=12, color=t.BLUE), right=0, top=0)] if offered else [])]),
        ], spacing=4, tight=True), padding=4, border_radius=14, tooltip=tip,
            bgcolor=t.SELECTED if offered else None,
            border=ft.Border.all(2, t.BLUE if active else ft.Colors.TRANSPARENT),
            on_click=lambda e, k=(listing.key, listing.d): self._select(k))

    def _mine_row(self, state: dict) -> ft.Control:
        label, color, icon = STATUS[state["status"]]
        title = translate(state["info"].get("species", ""))
        if state["role"] == "listing":
            title += tr('gts.for_76b8cb', ' for {value0}', value0=wanted_list_text(wanted(state)))
        else:
            title += tr('gts.offered_for_a2a379', ' offered for {value0}', value0=translate(gts.parse_listing(state['listing']).pokemon.get('species', '')) if state['listing'] else '')
        active = self.selected == state["id"]
        return ft.Container(ft.Row([
            ft.Stack([Sprite(self.app, int(state["info"].get("species_id") or 0), bool(state["info"].get("shiny")),
                             size=MINI).control,
                      *([ft.Container(sparkles(), left=0, top=0)] if state["info"].get("shiny") else [])]),
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
                tr('gts.pick_a_listing_to_see_the_pokemon_and_what_its_trainer__d09e48', "Pick a listing to see the Pokemon and what its trainer asks for. A trade happens the next time the lister's app is open; until then your offer waits outside your bank."), 13, t.MUTED)]
            return
        self.detail.controls = [self._about(listing.pokemon, listing.game),
                                t.section(tr('gts.asks_for_f07bf1', 'Asks for') if not listing.also else
                                          tr('gts.asks_for_any_of_5b0d3e', 'Asks for any of'), self._asked(listing.wanted)),
                                t.text(tr('gts.from_open_until_d81849', 'From {value0}, open until {value1}', value0=listing.trainer or tr('gts.a_trainer_bda66d', 'a trainer'), value1=_when(listing.expires)),
                                       12, t.FAINT),
                                self._yours(listing)]

    def _yours(self, listing: gts.Listing) -> ft.Control:
        state = self.client.offered(listing)
        if state is None:
            return t.section(tr('gts.your_pokemon_that_answer_it_2c53fc', 'Your Pokemon that answer it'), self._answers(listing))
        info = state["info"]
        return t.section(tr('gts.your_offer_7b2e41', 'Your offer'), ft.Column([
            ft.Row([Sprite(self.app, int(info.get("species_id") or 0), bool(info.get("shiny")), size=MINI).control,
                    ft.Column([t.text(tr('gts.level_dcff87', '{value0} · level {value1}', value0=translate(info.get('species', '')), value1=info.get('level')), 13),
                               t.badge(*STATUS["waiting"])], spacing=4, expand=True)], spacing=10),
            t.text(tr('gts.other_players_can_still_offer_on_it_the_lister_s_app_tr_9c4d2a', "Other players can still offer on it. The lister's app trades the first offer that answers it, the next time it is open; if that is not yours, yours comes back to the bank."), 12, t.FAINT),
        ], spacing=10))

    def _about(self, shown: dict, game: str) -> ft.Control:
        shown = {**shown, **{key: translate(shown.get(key, "")) for key in ("species", "nature", "ability", "ball", "held_item")},
                 "moves": [translate(move) for move in shown.get("moves", ())]}
        facts = [shown.get("nature"), shown.get("ability"), shown.get("ball")]
        if shown.get("held_item"):
            facts.append(tr('gts.holding_b3a475', 'holding {value0}', value0=shown['held_item']))
        return ft.Row([
            Sprite(self.app, int(shown.get("species_id") or 0), bool(shown.get("shiny")), size=SIZE).control,
            ft.Column([
                t.text(tr('gts.level_dcff87', '{value0} · level {value1}', value0=shown['species'], value1=shown.get('level')) + (tr('gts.shiny_3e4562', ' · shiny') if shown.get("shiny") else ""),
                       15, weight=ft.FontWeight.W_600),
                t.text(" · ".join(str(f) for f in facts if f), 12, t.MUTED),
                t.text(tr("presentation.list_separator", ", ").join(shown.get("moves") or []), 12, t.MUTED),
                ft.Row([game_icon(game), t.text(tr('gts.in_ot_abad3b', 'In {value0}, OT {value1}', value0=NAMES.get(game, game), value1=shown.get('ot')), 12, t.SOFT)],
                       spacing=6),
            ], spacing=4, expand=True),
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START)

    def _asked(self, asked) -> ft.Control:
        return ft.Column([ft.Row([Sprite(self.app, w.species, w.shiny, size=MINI).control,
                                  t.text(wanted_text(w), 13),
                                  *([sparkles()] if w.shiny else [])], spacing=10) for w in asked], spacing=6)

    def _answers(self, listing: gts.Listing) -> ft.Control:
        held = [e for e in self._held() if answers(e, listing.wanted)]
        if not held:
            return t.text(tr('gts.your_bank_holds_no_legal_that_is_not_queued_for_a_trade_66b4ef', 'Your bank holds no legal {value0} that is not queued for a trade.', value0=wanted_list_text(listing.wanted)),
                          12, t.FAINT)
        return ft.Column([ft.Row([
            Sprite(self.app, e.species_id, e.shiny, size=MINI).control,
            ft.Column([t.text(e.summary, 12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                       ft.Row([game_icon(e.game, 16), t.text(NAMES[e.game], 11, t.MUTED)], spacing=4)],
                      spacing=2, expand=True),
            t.button(tr('gts.offer_0cf57c', 'Offer'), lambda ev, x=e: self._confirm_offer(listing, x), "arrows-horizontal",
                     disabled=self.working),
        ], spacing=8) for e in held], spacing=8)

    def _mine_detail(self, state: dict) -> list[ft.Control]:
        label, color, icon = STATUS[state["status"]]
        controls = [self._about(state["info"], state["game"]), t.badge(label, color, icon)]
        if state["role"] == "listing":
            controls.append(self._asked(wanted(state)))
            controls.append(t.text(tr('gts.open_until_offer_answered_3c9d1f', 'Open until {value0}; {value1} offer{value2} answered.', value0=_when(state['expires']), value1=len(state['answers']), value2='s' * (len(state['answers']) != 1)),
                                   12, t.MUTED))
            if state["status"] == "traded":
                controls.append(t.text(tr('gts.traded_with_what_came_back_is_in_the_bank_d8f8bc', 'Traded with {value0}; what came back is in the bank.', value0=state['partner'] or tr('gts.a_trainer_bda66d', 'a trainer')),
                                       12, t.SOFT))
            if state["status"] == "active":
                controls.append(t.secondary_button(tr('gts.take_it_down_9ed702', 'Take it down'), lambda e: self._withdraw(state), "close"))
        else:
            listing = gts.parse_listing(state["listing"])
            if listing:
                controls.append(t.text(tr('gts.offered_for_level_from_6f5c29', 'Offered for {value0} level {value1} from {value2}.', value0=translate(listing.pokemon.get('species', '')), value1=listing.pokemon.get('level'), value2=listing.trainer or tr('gts.a_trainer_bda66d', 'a trainer')), 12, t.MUTED))
            if state["status"] == "waiting":
                controls.append(t.text(tr('gts.the_trade_happens_the_next_time_the_lister_s_app_is_ope_23acca', "The trade happens the next time the lister's app is open. If it ends unanswered, your Pokemon comes back to the bank."), 12, t.FAINT))
            if state["why"]:
                controls.append(t.text(state["why"][0].upper() + state["why"][1:] + ".", 12,
                                       t.AMBER if state["status"] == "returned" else t.SOFT))
        if state["status"] not in ("active", "waiting"):
            controls.append(t.secondary_button(tr('gts.clear_from_the_list_13c20d', 'Clear from the list'), lambda e: self._forget(state), "trash"))
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
            self._work(tr('gts.pkhex_is_checking_it_e51442', 'PKHeX is checking it...'), lambda: self.client.offer(listing, entry),
                       tr('gts.offered_yours_lists_the_answer_once_the_lister_s_app_se_e8e078', "Offered. Yours lists the answer once the lister's app sends it."))

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('gts.offer_e4293e', 'Offer {value0}?', value0=summary_text(entry.summary).split(' · ')[0]), 18),
            content=t.text(tr('gts.it_leaves_your_bank_and_waits_for_the_lister_s_app_you__ff4ccc', "It leaves your bank and waits for the lister's app. You get {value0} if your offer is the first that answers the listing; otherwise it comes back. Nothing on the relays can make the lister send theirs: a trade depends on the other app being the real one.", value0=translate(listing.pokemon.get('species', ''))), 13, t.MUTED, width=400),
            actions=[t.button(tr('gts.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('gts.offer_0cf57c', 'Offer'), go, "arrows-horizontal")]))

    def _withdraw(self, state: dict) -> None:
        self._work(tr('gts.taking_it_down_921e7c', 'Taking it down...'), lambda: self.client.withdraw(state["id"]),
                   tr('gts.taken_down_the_pokemon_is_back_in_the_bank_e3069b', 'Taken down. The Pokemon is back in the bank.'))

    def _forget(self, state: dict) -> None:
        self.client.forget(state["id"])
        self.selected = ""
        self.render()
        self.control.update()

    def _deposit_dialog(self) -> None:
        held = self._held()
        if not held:
            self._say(tr('gts.the_bank_holds_no_legal_pokemon_that_is_not_queued_for__a9b617', 'The bank holds no legal Pokemon that is not queued for a trade.'), t.AMBER)
            return
        if not self.species:
            self._say(tr('gts.pkhex_is_still_reading_the_species_list_try_again_in_a__9f683f', 'PKHeX is still reading the species list; try again in a moment.'), t.AMBER)
            return
        choice = t.dropdown([(e.id, own_text(e)) for e in held], held[0].id, enable_filter=True,
                            editable=True, menu_height=320)
        for option, entry in zip(choice.options, held):
            if entry.shiny:
                option.trailing_icon = sparkles()
        asked: list[tuple[ft.Dropdown, ft.Switch]] = []
        rows = ft.Column(spacing=8, tight=True)
        more = t.link_button(tr('gts.add_another_d41a6c', 'Add another'), lambda e: add())
        low = t.field(value="1", mono=True, width=80, digits=True, limit=3)
        high = t.field(value="100", mono=True, width=80, digits=True, limit=3)
        message = t.text("", 12, t.RED)

        def draw():
            rows.controls = [ft.Row([
                pick, ft.Row([shiny, t.text(tr('gts.shiny_039a0a', 'Shiny'), 13, t.SOFT)], spacing=6, tight=True),
                t.icon_button("close", lambda e, n=n: remove(n), tr('gts.remove_3bd8f2', 'Remove'),
                              visible=len(asked) > 1),
            ], spacing=10) for n, (pick, shiny) in enumerate(asked)]
            more.visible = len(asked) < gts.MAX_WANTS

        def add(update=True):
            # A select handler makes t.dropdown take typed text plus Enter as the option it names.
            asked.append((t.dropdown(self.species, None, lambda e: None, enable_filter=True, editable=True,
                                     menu_height=320),
                          t.switch(False, None)))
            draw()
            if update:
                rows.update()
                more.update()

        def remove(n):
            asked.pop(n)
            draw()
            rows.update()
            more.update()

        add(update=False)

        def go(e):
            entry = next((x for x in held if x.id == choice.value), None)
            names = [(pick.value, self.canonical_species.get(pick.value or ""), bool(shiny.value)) for pick, shiny in asked]
            levels = (low.value or "").strip(), (high.value or "").strip()
            if entry is None or not all(name for _, name, _ in names):
                message.value = tr('gts.pick_your_pokemon_and_the_one_you_ask_for_536386', 'Pick your Pokemon and the one you ask for.')
            elif len({key for key, _, _ in names}) < len(names):
                message.value = tr('gts.each_pokemon_you_ask_for_once_7a0e55', 'Ask for each Pokemon once.')
            elif not all(v.isdigit() for v in levels) or not 1 <= int(levels[0]) <= int(levels[1]) <= 100:
                message.value = tr('gts.the_levels_go_from_1_to_100_the_first_no_higher_than_th_e48832', 'The levels go from 1 to 100, the first no higher than the second.')
            else:
                self.app.page.pop_dialog()
                wants = [gts.Wants(int(key), name, int(levels[0]), int(levels[1]), shiny) for key, name, shiny in names]
                self._work(tr('gts.pkhex_is_checking_it_e51442', 'PKHeX is checking it...'), lambda: self.client.deposit(entry, *wants),
                           tr('gts.listed_for_30_days_your_app_trades_it_when_it_is_open_a_cd4947', 'Listed for 30 days. Your app trades it when it is open and a matching offer arrives.'))
                return
            message.update()

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('gts.deposit_a_pokemon_69907e', 'Deposit a Pokemon'), 18),
            content=ft.Column([
                t.labeled_control(tr('gts.your_pokemon_232a04', 'Your Pokemon'), choice),
                t.labeled_control(tr('gts.ask_for_2b1a7d', 'Ask for'), ft.Column([rows, more], spacing=4, tight=True)),
                ft.Row([t.labeled_control(tr('gts.lowest_level_44ad69', 'Lowest level'), low), t.labeled_control(tr('gts.highest_level_5cabfc', 'Highest level'), high)], spacing=10),
                t.text(tr('gts.it_leaves_the_bank_while_listed_the_first_offer_that_an_d65652', 'It leaves the bank while listed. The first offer that answers it is traded, by this app, the next time it is open. Take it down from Yours to get it back.'), 12, t.FAINT),
                message,
            ], spacing=14, tight=True, width=420),
            actions=[t.button(tr('gts.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog(), filled=False),
                     t.button(tr('gts.deposit_0da00b', 'Deposit'), go, "upload")]))

    def _say(self, text: str, color: str) -> None:
        self.note.value, self.note.color = text, color
        try:
            self.note.update()
        except RuntimeError:
            pass


def own_text(entry: bank.Entry) -> str:
    name, level = summary_text(entry.summary).split(' · ')[:2]
    if entry.shiny:
        return tr('gts.own_shiny_7d21c4', '{value0}, {value1}, shiny ({value2})', value0=name, value1=level, value2=NAMES[entry.game])
    return tr('gts._99a2ff', '{value0}, {value1} ({value2})', value0=name, value1=level, value2=NAMES[entry.game])


def wanted_text(wants: gts.Wants, levels: bool = True) -> str:
    name = translate(wants.name)
    if wants.shiny:
        name = tr('gts.shiny_name_8e2f7a', 'shiny {name}', name=name)
    if not levels or (wants.min_level, wants.max_level) == (1, 100):
        return name
    return tr("presentation.wanted_levels", "{name}, level {low} to {high}",
              name=name, low=wants.min_level, high=wants.max_level)


def wanted_list_text(asked) -> str:
    """Several wants read as one phrase; a level range they share is said once, at the end."""
    joined = lambda texts: tr('gts.or_separator_2f61a4', ' or ').join(texts)   # noqa: E731
    first = asked[0]
    if not all((w.min_level, w.max_level) == (first.min_level, first.max_level) for w in asked):
        return joined(wanted_text(w) for w in asked)
    names = joined(wanted_text(w, levels=False) for w in asked)
    if (first.min_level, first.max_level) == (1, 100):
        return names
    return tr("presentation.wanted_levels", "{name}, level {low} to {high}",
              name=names, low=first.min_level, high=first.max_level)

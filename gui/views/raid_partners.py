"""The Tera Raid host's Raid NPC partners card: the progress the partners come from and one of that
pool's trainers for each slot the consoles joining leave empty, in slot order (pokeldn.sv.raid_partners);
the host draws a partner seed that seats them when it starts, and draws a partner left unpicked as the
game does. Folding only hides the card: the choice goes to the raid."""
from pokeldn.app.i18n import t as tr

import flet as ft

from gui import theme as t
from gui.views.sprites import MINI, Sprite
from gui.localization import translate
from pokeldn.app import command
from pokeldn.sv import raid_partners

COLUMNS = 3
# A card narrower than this cuts the trainer's, the Pokemon's and the moves' names, so a narrow window
# shows two to a row.
CARD_WIDTH = 150
GAP = 8
REASON_HEIGHT = 48                          # two 11 px lines at the theme's 1.4 line height, padded
RANKS = {1: (t.AMBER, tr('raid_partners.favoured_by_raiders_ebd6ac', 'Favoured by raiders')), 2: (t.SILVER, tr('raid_partners.next_tier_for_raiders_4c1d2f', 'Next tier for raiders'))}


def columns(width: float) -> int:
    """-> the cards to a row in `width` px: COLUMNS while each is CARD_WIDTH wide, else two; COLUMNS
    before the width is known."""
    return COLUMNS if not width or (width - GAP * (COLUMNS - 1)) / COLUMNS >= CARD_WIDTH else 2


class RaidPartnersPicker:
    """`view` is the GamesView: it keeps the card open across redraws, holds the values and gives the
    raid's context, whose progress and crystal set the partners' progress unless one is chosen. Its
    Consoles joining sets how many partners there are to pick."""

    def __init__(self, view, field):
        self.view, self.app, self.field = view, view.app, field
        self.open = view.raid_partners_open
        stored = view.values.get(field.key)
        self.value = dict(stored) if isinstance(stored, dict) else {"progress": "", "picks": []}
        context = view.raid_context()
        self.default = raid_partners.stage_of(context["progress"], context.get("content", "standard"))
        chosen = self.value.get("progress")
        self.stage = raid_partners.STAGES.index(chosen) if chosen in raid_partners.STAGES else self.default
        self.pool = raid_partners.pool(self.stage)
        self.consoles = command.raid_consoles(view.tool, view.values)
        self.free = raid_partners.slots(self.consoles)
        # Partners take four fifths of the level of Our Pokemon, the host's; 0 until it is built.
        self.host = command.raid_pokemon_level(view.values)
        self.level = raid_partners.level_for(self.host)
        # A trainer this progress's pool lacks (Dylan and Luke below four stars) leaves the choice, and
        # a console joining takes the last pick's slot.
        names = {p.trainer for p in self.pool}
        picks = [name for name in self.value.get("picks", ()) if name in names][:self.free]
        if isinstance(stored, dict) and picks != list(self.value.get("picks", ())):
            self.value["picks"] = picks
            view.values[field.key] = self.value
            self.app.settings.save()
        self.picks = picks
        self.chevron = t.pixel_icon("chevron-down" if self.open else "chevron-right", color=t.FAINT)
        summary = self._summary()
        header = ft.Container(ft.Row([
            self.chevron, t.text(field.label, 13, weight=ft.FontWeight.W_600),
            ft.Container(t.text(summary, 12, t.BLUE if picks or chosen else t.MUTED, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS), expand=True,
                         alignment=ft.Alignment.CENTER_RIGHT),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), on_click=self._toggle,
            tooltip=tr('raid_partners.show_or_hide_the_raid_s_partners_2e7cda', "Show or hide the raid's partners"))
        self.body = ft.Column([], spacing=10, visible=self.open)
        if self.open:
            self.body.controls = self._body()
        self.control = t.surface(ft.Container(ft.Column([header, self.body], spacing=10, tight=True),
                                              padding=16))

    def _summary(self) -> str:
        labels = dict(next(f for f in self.view.tool.fields if f.key == "--raid-progress").choices)
        stage = tr('raid_partners._940234', ' · {value0}', value0=labels.get(self.value['progress'], '')) if self.value.get("progress") else ""
        if not self.free:
            return tr('raid_partners.none_consoles_fill_the_slots_5b1d52', 'None, {value0} consoles fill the slots', value0=self.consoles)
        if not self.picks:
            return tr('raid_partners.drawn_as_the_game_draws_them_83bcc1', 'Drawn as the game draws them{value0}', value0=stage)
        names = ", ".join(translate(name) for name in self.picks)
        return (names if len(self.picks) == self.free else tr('raid_partners.one_drawn_5e7b66', '{value0}, one drawn', value0=names)) + stage

    def _body(self) -> list[ft.Control]:
        labels = dict(next(f for f in self.view.tool.fields if f.key == "--raid-progress").choices)
        options = [(key, labels.get(key, key) + (tr('raid_partners.story_progress_8ce859', ' (story progress)') if n == self.default else ""))
                   for n, key in enumerate(raid_partners.STAGES)]
        progress = t.dropdown(options, raid_partners.STAGES[self.stage], on_select=self._progress)
        lead = (tr('raid_partners.level_partners_four_fifths_of_our_pokemon_s_level_3d0f9c', "Level {value0} partners, four fifths of Our Pokemon's level {value1}.", value0=self.level, value1=self.host)
                if self.level else tr('raid_partners.partners_take_four_fifths_of_our_pokemon_s_level_f0d679', "Partners take four fifths of Our Pokemon's level."))
        if not self.free:
            note = (tr('raid_partners.with_consoles_joining_no_slot_is_left_empty_a_partner_t_9fbd0c', '{value0} With {value1} consoles joining no slot is left empty: a partner takes the slot of a console that does not join.', value0=lead, value1=self.consoles))
        elif self.free == 1:
            note = (tr('raid_partners.pick_one_for_the_slot_the_consoles_leave_empty_or_leave_44312f', '{value0} Pick one for the slot the consoles leave empty, or leave it to be drawn when the host starts.', value0=lead))
        else:
            note = (tr('raid_partners.pick_up_to_two_in_the_order_they_take_the_empty_slots_a_b946f1', '{value0} Pick up to two, in the order they take the empty slots; a partner you leave is drawn when the host starts.', value0=lead))
        # The cards' width sets how many stand to a row.
        cards = ft.Container(ft.Column(self._rows(), spacing=GAP), size_change_interval=100,
                             on_size_change=self._spread)
        return [t.text(self.field.help, 12, t.MUTED),
                t.labeled_control(tr('raid_partners.partners_progress_b4087b', "Partners' progress"), progress),
                t.text(note, 12, t.MUTED),
                cards]

    def _rows(self) -> list[ft.Control]:
        count = columns(self.view.raid_partners_width)
        rows = []
        for i in range(0, len(self.pool), count):
            partners = self.pool[i:i + count]
            # A row with a favoured partner gives every card the reason's room, so they stand level.
            footer = any(p.why for p in partners)
            row = [self._card(p, footer) for p in partners]
            row += [ft.Container(expand=True) for _ in range(count - len(row))]
            rows.append(ft.Row(row, spacing=GAP, vertical_alignment=ft.CrossAxisAlignment.START))
        return rows

    def _card(self, partner, footer=False) -> ft.Control:
        picked = partner.trainer in self.picks
        full = len(self.picks) >= self.free
        order = ft.Container(t.text(str(self.picks.index(partner.trainer) + 1), 11, t.BG,
                                    weight=ft.FontWeight.W_700),
                             width=20, height=20, border_radius=10, bgcolor=t.BLUE,
                             alignment=ft.Alignment.CENTER) if picked else ft.Container()
        title = ft.Row([
            Sprite(self.app, partner.species, size=MINI).control,
            ft.Column([t.text(translate(partner.trainer), 13, weight=ft.FontWeight.W_600, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS),
                       t.text(translate(partner.name), 12, t.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                      spacing=0, expand=True),
            order,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        facts = ft.Row([t.chip(tr('raid_partners.lv_1b4f67', 'Lv. {value0}', value0=self.level) if self.level else tr('raid_partners.lv_3e543b', 'Lv. —')),
                        t.chip(translate(partner.tera), "diamond-gem", t.FAINT)], spacing=6, tight=True)
        # Every partner has three moves, one to a line, so every card of a pool stands as tall.
        moves = ft.Column([t.text(translate(partner.ability), 12, t.SOFT, weight=ft.FontWeight.W_500, max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS)]
                          + [t.text(translate(move), 12, t.MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
                             for move in partner.moves], spacing=1)
        column = [title, facts, moves]
        if footer:
            # Wanted by raiders: a strip tinted gold for the favoured, silver for the next tier; its
            # tooltip says why at more length. A card without one keeps the strip's room.
            strip = ft.Container(height=REASON_HEIGHT)
            if partner.why:
                ink, tier = RANKS[partner.rank]
                strip = ft.Container(ft.Row([
                    t.pixel_icon("star", 12, color=ink),
                    ft.Container(t.text(translate(partner.why), 11, ink, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                 expand=True),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
                    height=REASON_HEIGHT, padding=ft.Padding(8, 6, 8, 6), border_radius=8,
                    bgcolor=ft.Colors.with_opacity(0.10, ink), tooltip=tr('raid_partners._bbee01', '{value0}: {value1}.', value0=tier, value1=translate(partner.detail)))
            column.append(strip)
        return ft.Container(
            ft.Column(column, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), expand=True,
            padding=12, border_radius=12,
            bgcolor=t.SELECTED if picked else t.FIELD,
            border=ft.Border.all(1, t.BLUE if picked else t.OUTLINE),
            opacity=0.45 if full and not picked else 1.0,
            on_click=None if full and not picked else (lambda _e, name=partner.trainer: self._pick(name)),
            tooltip=None if full and not picked else (tr('raid_partners.leave_to_the_draw_667226', 'Leave to the draw') if picked else tr('raid_partners.seat_this_partner_affeab', 'Seat this partner')))

    # Changes

    def _toggle(self, _e) -> None:
        self.view.show_raid_partners(not self.open)

    def _spread(self, e) -> None:
        before = columns(self.view.raid_partners_width)
        self.view.raid_partners_width = e.width
        if columns(e.width) != before:
            e.control.content.controls = self._rows()
            e.control.content.update()

    def follow_host(self) -> None:
        """Our Pokemon changed, which the view saves without a redraw: the partners' level follows."""
        host = command.raid_pokemon_level(self.view.values)
        if host != self.host:
            self.host, self.level = host, raid_partners.level_for(host)
            if self.open:
                self.body.controls = self._body()
                self.body.update()

    def _progress(self, e) -> None:
        # The story progress's own stage follows the story progress, rather than holding it.
        chosen = e.control.value
        self.value["progress"] = "" if raid_partners.STAGES.index(chosen) == self.default else chosen
        self.view.set_value(self.field, self.value, rebuild=True)

    def _pick(self, name: str) -> None:
        picks = [p for p in self.picks if p != name]
        if name not in self.picks:
            picks.append(name)
        self.value["picks"] = picks[:self.free]
        self.view.set_value(self.field, self.value, rebuild=True)

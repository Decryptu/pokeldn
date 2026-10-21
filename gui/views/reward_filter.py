"""The raid finder's wanted rewards: a foldable list of items, each with the least quantity a raid
must give of it, chosen among what the raids searched can give (pokeldn.sv.raid_search). Folded,
the list is kept and leaves the search alone."""
from pokeldn.app.i18n import t as tr

import threading

import flet as ft

from gui import theme as t
from gui.views.widgets import PixelActivity
from gui.localization import SERVICE, error_message
from pokeldn.sv import raid_search
from pokeldn.sv.raid import REWARD_ROWS


def item_names() -> dict[int, str]:
    """-> the bag's item names by id, from PKHeX; empty when it cannot say."""
    try:
        return {int(n["id"]): n["name"] for n in SERVICE.names("sv", "bag")}
    except Exception:
        return {}


class RewardFilter:
    """`scope()` -> (the contexts searched, the stars, species and Tera type narrowing them), or
    ValueError when none can be searched."""

    def __init__(self, app, scope):
        self.app, self.scope = app, scope
        self.open = False
        self.rows: list[dict] = []          # {"item": id or None, "least": quantity}
        self.choices: dict | None = None    # item -> its totals, lowest first; None until listed
        self.names: dict[int, str] = {}
        self.error = ""
        self.listing = 0                    # the newest listing; an older one's answer is dropped
        self.chevron = t.pixel_icon("chevron-right", size=12, color=t.FAINT)
        self.summary = t.text("", 11, t.MUTED)
        header = ft.Container(ft.Row([
            self.chevron, t.pixel_icon("gift", size=12, color=t.BLUE),
            t.text(tr('reward_filter.rewards_59afe4', 'Rewards'), 12, t.SOFT, weight=ft.FontWeight.W_600),
            ft.Container(self.summary, expand=True, alignment=ft.Alignment.CENTER_RIGHT),
        ], spacing=8), padding=ft.Padding(0, 6, 0, 0), on_click=self._toggle,
            tooltip=tr('reward_filter.unfold_to_want_rewards_folded_the_search_leaves_them_al_0be515', 'Unfold to want rewards; folded, the search leaves them alone'))
        self.busy = ft.Row([PixelActivity(tr('reward_filter.listing_the_rewards_3cf5eb', 'Listing the rewards')),
                            t.text(tr('reward_filter.listing_what_these_raids_give_25e326', 'Listing what these raids give...'), 11, t.MUTED)], spacing=8, visible=False)
        self.list = ft.Column(spacing=8)
        self.add = t.secondary_button(tr('reward_filter.add_reward_974066', 'Add reward'), self._add, "plus")
        self.body = ft.Column([
            t.text(tr('reward_filter.find_raids_that_give_at_least_these_only_what_the_raids_ba25c5', 'Find raids that give at least these. Only what the raids searched can give is listed.'),
                   11, t.FAINT),
            self.busy, self.list, self.add], spacing=8, visible=False)
        self.control = ft.Column([header, self.body], spacing=8, tight=True)
        self._render(update=False)

    # What the search wants

    def wanted(self) -> dict | None:
        """-> {item: least quantity} to search for, or None: folded or empty. ValueError for a row
        the search cannot take."""
        rows = self.rows if self.open else []
        if not rows:
            return None
        if self.choices is None:
            raise ValueError(tr('reward_filter.the_rewards_are_still_being_listed_8e2654', 'The rewards are still being listed.'))
        out = {}
        for row in rows:
            if row["item"] is None:
                raise ValueError(tr('reward_filter.choose_an_item_for_each_wanted_reward_or_remove_it_831fac', 'Choose an item for each wanted reward, or remove it.'))
            if row["item"] not in self.choices:
                raise ValueError(tr('reward_filter.no_raid_searched_gives_change_the_reward_or_where_the_r_645c80', 'No raid searched gives {value0}; change the reward or where the raid is.', value0=self._name(row['item'])))
            out[row["item"]] = out.get(row["item"], 0) + row["least"]
        return out

    # Listing

    def changed(self) -> None:
        """Where the raid is or what the boss is changed: the choices are listed again."""
        if self.open:
            self._list()
        else:
            self.choices = None

    def _list(self) -> None:
        self.listing += 1
        listing, self.choices, self.error = self.listing, None, ""
        self.busy.visible = True
        self._render()

        def work():
            try:
                scope, narrow = self.scope()
                choices, error = raid_search.reward_choices(scope, **narrow), ""
            except ValueError as exc:
                choices, error = {}, error_message(exc)
            names = self.names or item_names()

            def show():
                if listing != self.listing:
                    return
                self.choices, self.names, self.error = choices, names, error
                self.busy.visible = False
                self._render()
            self.app.ui(show)
        threading.Thread(target=work, daemon=True).start()

    # Editing

    def _toggle(self, _e) -> None:
        self.open = not self.open
        self.body.visible = self.open
        self.chevron.src = f"icons/chevron-{'down' if self.open else 'right'}.svg"
        if self.open and self.choices is None:
            self._list()
        else:
            self._render()

    def _add(self, _e) -> None:
        if len(self.rows) < REWARD_ROWS:
            self.rows.append({"item": None, "least": 1})
            self._render()

    def _remove(self, index: int) -> None:
        self.rows.pop(index)
        self._render()

    def _item(self, index: int, value) -> None:
        item = int(value) if value not in (None, "") else None
        totals = (self.choices or {}).get(item, (1,))
        self.rows[index] = {"item": item, "least": totals[0]}
        self._render()

    def _least(self, index: int, value) -> None:
        self.rows[index]["least"] = int(value)
        self._render()

    def _name(self, item: int) -> str:
        return self.names.get(item, tr("presentation.item_number", "Item {number}", number=item))

    def _render(self, update: bool = True) -> None:
        count = len(self.rows)
        wanted = tr('reward_filter.wanted_16af7a', '{value0} wanted', value0=count) if count else tr('reward_filter.any_rewards_4b6ba5', 'Any rewards')
        self.summary.value = wanted if self.open or not count else tr('reward_filter.off_d2834c', 'Off: {value0}', value0=wanted)
        self.summary.color = t.BLUE if self.open and count else t.MUTED
        rows = []
        choices = self.choices or {}
        listed = sorted(choices, key=lambda i: self._name(i).casefold())
        for index, row in enumerate(self.rows):
            item, here = row["item"], row["item"] in choices
            options = [(str(i), self._name(i)) for i in listed]
            if item is not None and not here:      # kept from a wider search, shown as such
                options.insert(0, (str(item), tr('reward_filter.not_given_here_f8a380', '{value0} (not given here)', value0=self._name(item))))
            picker = t.dropdown(options, str(item) if item is not None else None, enable_filter=True,
                                editable=True, menu_height=300, hint_text=tr('reward_filter.search_an_item_ebd2df', 'Search an item'),
                                disabled=self.choices is None,
                                on_select=lambda e, n=index: self._item(n, e.control.value))
            totals = choices.get(item, (row["least"],)) if item is not None else (1,)
            least = t.dropdown([(str(n), f"×{n}") for n in totals], str(row["least"]),
                               disabled=item is None or not here,
                               on_select=lambda e, n=index: self._least(n, e.control.value))
            line = [ft.Row([
                t.labeled_control(tr('reward_filter.item_652bcc', 'Item'), picker, expand=True),
                t.labeled_control(tr('reward_filter.at_least_325198', 'At least'), ft.Container(least, width=96)),
                t.icon_button("close", lambda _e, n=index: self._remove(n), tr('reward_filter.remove_reward_242188', 'Remove reward')),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.END)]
            if item is not None and not here and self.choices is not None:
                line.append(t.text(tr('reward_filter.no_raid_searched_gives_it_e1cce4', 'No raid searched gives it.'), 11, t.RED))
            rows.append(ft.Column(line, spacing=4, tight=True))
        if self.error:
            rows.append(t.text(self.error, 11, t.RED))
        elif not rows:
            rows.append(t.text(tr('reward_filter.any_rewards_add_one_to_look_for_raids_that_give_it_33a45d', 'Any rewards. Add one to look for raids that give it.'), 11, t.MUTED))
        self.list.controls = rows
        self.add.disabled = count >= REWARD_ROWS or self.choices is None
        if update:
            try:
                self.control.update()
            except RuntimeError:        # the dialog closed while the rewards were listed
                pass

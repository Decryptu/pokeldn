"""The raid finder's wanted rewards: a foldable list of items, each with the least quantity a raid
must give of it, chosen among what the raids searched can give (pokeldn.sv.raid_search). Folded,
the list is kept and leaves the search alone."""

import threading

import flet as ft

from gui import theme as t
from gui.views.widgets import PixelActivity
from pokeldn import pokemon as builder
from pokeldn.sv import raid_search
from pokeldn.sv.raid import REWARD_ROWS


def item_names() -> dict[int, str]:
    """-> the bag's item names by id, from PKHeX; empty when it cannot say."""
    try:
        return {int(n["id"]): n["name"] for n in builder.SERVICE.names("sv", "bag")}
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
            t.text("Rewards", 12, t.SOFT, weight=ft.FontWeight.W_600),
            ft.Container(self.summary, expand=True, alignment=ft.Alignment.CENTER_RIGHT),
        ], spacing=8), padding=ft.Padding(0, 6, 0, 0), on_click=self._toggle,
            tooltip="Unfold to want rewards; folded, the search leaves them alone")
        self.busy = ft.Row([PixelActivity("Listing the rewards"),
                            t.text("Listing what these raids give...", 11, t.MUTED)], spacing=8, visible=False)
        self.list = ft.Column(spacing=8)
        self.add = t.secondary_button("Add reward", self._add, "plus")
        self.body = ft.Column([
            t.text("A raid found gives at least these, its quantities of an item summed. The items and "
                   "quantities are those the raids searched can give.", 11, t.FAINT),
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
            raise ValueError("The rewards are still being listed.")
        out = {}
        for row in rows:
            if row["item"] is None:
                raise ValueError("Choose an item for each wanted reward, or remove it.")
            if row["item"] not in self.choices:
                raise ValueError(f"No raid searched gives {self._name(row['item'])}; change the reward "
                                 "or where the raid is.")
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
                choices, error = {}, str(exc)
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
        return self.names.get(item, f"Item {item}")

    def _render(self, update: bool = True) -> None:
        count = len(self.rows)
        wanted = f"{count} wanted" if count else "Any rewards"
        self.summary.value = wanted if self.open or not count else f"Off: {wanted}"
        self.summary.color = t.BLUE if self.open and count else t.MUTED
        rows = []
        choices = self.choices or {}
        listed = sorted(choices, key=lambda i: self._name(i).casefold())
        for index, row in enumerate(self.rows):
            item, here = row["item"], row["item"] in choices
            options = [(str(i), self._name(i)) for i in listed]
            if item is not None and not here:      # kept from a wider search, shown as such
                options.insert(0, (str(item), f"{self._name(item)} (not given here)"))
            picker = t.dropdown(options, str(item) if item is not None else None, enable_filter=True,
                                editable=True, menu_height=300, hint_text="Search an item",
                                disabled=self.choices is None,
                                on_select=lambda e, n=index: self._item(n, e.control.value))
            totals = choices.get(item, (row["least"],)) if item is not None else (1,)
            least = t.dropdown([(str(n), f"×{n}") for n in totals], str(row["least"]),
                               disabled=item is None or not here,
                               on_select=lambda e, n=index: self._least(n, e.control.value))
            line = [ft.Row([
                t.labeled_control("Item", picker, expand=True),
                t.labeled_control("At least", ft.Container(least, width=96)),
                t.icon_button("close", lambda _e, n=index: self._remove(n), "Remove reward"),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.END)]
            if item is not None and not here and self.choices is not None:
                line.append(t.text("No raid searched gives it.", 11, t.RED))
            rows.append(ft.Column(line, spacing=4, tight=True))
        if self.error:
            rows.append(t.text(self.error, 11, t.RED))
        elif not rows:
            rows.append(t.text("Any rewards. Add one to look for raids that give it.", 11, t.MUTED))
        self.list.controls = rows
        self.add.disabled = count >= REWARD_ROWS or self.choices is None
        if update:
            try:
                self.control.update()
            except RuntimeError:        # the dialog closed while the rewards were listed
                pass

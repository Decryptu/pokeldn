import flet as ft

from gui import theme as t
from gui.views.pokemon import NamePicker
from pokeldn.app import raid_rewards
from pokeldn.app.i18n import t as tr




TEMPLATES = {
    "sv": (
        ("training", tr('rewards.training_bundle_514868', 'Training bundle'), (1128, 50, 53, 795, 796, 1606)),
        ("shards", tr('rewards.tera_shard_bundle_6365de', 'Tera shard bundle'), tuple(range(1862, 1880)) + (2549,)),
        ("herba", tr('rewards.herba_mystica_bundle_2f20ef', 'Herba Mystica bundle'), (1904, 1905, 1906, 1907, 1908)),
        ("treasure", tr('rewards.treasure_bundle_c68d29', 'Treasure bundle'), (92, 581, 91, 583)),
        ("balls", tr('rewards.ball_bundle_5f0879', 'Ball bundle'), (2, 3, 6, 7, 9, 10, 11, 12, 13, 15)),
    ),
}




def quantity_error(value: str) -> str | None:
    return None if value.isascii() and value.isdigit() and 1 <= int(value) <= 999 else tr('rewards.1_to_999_08214e', '1 to 999')


class RewardPicker:
    """A raid's reward rows in order, each an item from the game's bag list and a quantity. The value
    is [{"item_id", "quantity"}]; an empty list keeps the raid's own rewards. `den`, for a Sword/Shield
    den, returns the den's (item, count or None) pairs or None: only those items are offered, each at
    the count the den fixes (docs/swsh_raid.md, The boss record)."""

    def __init__(self, app, game: str, value, on_change, den=None):
        self.app, self.game, self.on_change, self.den_of = app, game, on_change, den
        self.den = self._den()
        self._set_templates()
        self.max_rows = raid_rewards.rows(game)
        self.value = [dict(row) for row in value] if isinstance(value, (list, tuple)) else []
        self.template = self._template_of()
        self.template_quantity = self._template_quantity()
        self.rows = ft.Column(spacing=8)
        self.templates = t.dropdown(self._template_options(), self.template, on_select=self._choose_template)
        self.quantity = t.field(value=self.template_quantity, mono=True, width=110,
                                keyboard_type=ft.KeyboardType.NUMBER,
                                tooltip=tr('rewards.quantity_for_every_item_from_1_to_999_dc645d', 'Quantity for every item, from 1 to 999'),
                                on_change=self._set_template_quantity)
        self.template_quantity_control = t.labeled_control(tr('rewards.quantity_each_e0ea04', 'Quantity each'), self.quantity)
        self.template_controls = ft.Row([
            t.labeled_control(tr('rewards.template_0575f2', 'Template'), self.templates, expand=True),
            self.template_quantity_control,
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
        self.problem = t.text("", 12, t.RED)
        self.add = t.secondary_button(tr('rewards.add_reward_974066', 'Add reward'), self._add, "plus")
        self.control = ft.Column([self.template_controls, self.problem, self.rows, self.add],
                                 spacing=10, tight=True)
        self._render(update=False)

    def _den(self):
        return None if self.den_of is None else (lambda den: None if den is None else dict(den))(self.den_of())

    def _set_templates(self) -> None:
        if self.den_of is None:
            self.templates_of = TEMPLATES.get(self.game, TEMPLATES["sv"])
        else:
            self.templates_of = ((("den", tr('rewards.every_reward_of_this_den_3f0b1a', 'Every reward of this den'),
                                   tuple(self.den)[:raid_rewards.rows(self.game)]),) if self.den else ())
        self.template_items = {key: items for key, _, items in self.templates_of}

    def _fixed(self, item) -> int | None:
        """-> the count the den gives `item` at, or None where the count is free."""
        if not self.den or not str(item).isdigit():
            return None
        return self.den.get(int(item))

    def _free(self) -> list[dict]:
        return [row for row in self.value if self._fixed(row.get("item_id", "")) is None]

    def _template_of(self) -> str:
        items = tuple(str(row.get("item_id", "")) for row in self.value)
        if not items:
            return "seed"
        if any(self._fixed(row.get("item_id", "")) not in (None, int(row["quantity"]) if str(
                row.get("quantity", "")).isdigit() else -1) for row in self.value):
            return "custom"
        quantities = {str(row.get("quantity", "")) for row in self._free()}
        if len(quantities) > 1 or any(quantity_error(q) for q in quantities):
            return "custom"
        return next((key for key, expected in self.template_items.items()
                     if items == tuple(map(str, expected))), "custom")

    def _template_quantity(self) -> str:
        quantities = {str(row.get("quantity", "")) for row in self._free()}
        if len(quantities) == 1:
            quantity = quantities.pop()
            if quantity_error(quantity) is None:
                return quantity
        return "50"

    def _set(self, index: int, key: str, value: str) -> None:
        self.value[index][key] = value
        self.template = "custom"
        fixed = self._fixed(value) if key == "item_id" else None
        if fixed is not None:
            self.value[index]["quantity"] = str(fixed)
            self._render(update=False)
        self._show_template()
        self.control.update()
        self.on_change([dict(row) for row in self.value])

    def follow(self) -> None:
        """The boss changed: offer the new den's rewards; a den template follows it."""
        self.den = self._den()
        self._set_templates()
        for row in self.value:
            if (fixed := self._fixed(row.get("item_id", ""))) is not None:
                row["quantity"] = str(fixed)
        self.templates.options = [ft.DropdownOption(key=k, text=label) for k, label in self._template_options()]
        if self.template in self.template_items:
            self._apply_template()
        elif self.template not in ("seed", "custom"):
            self.template = "custom"
        if self.template != "seed":
            self.on_change([dict(row) for row in self.value])
        self._render()

    def _template_options(self) -> list[tuple[str, str]]:
        return ([("seed", tr('rewards.raid_s_own_rewards_31b68b', "Raid's own rewards")),
                 ("custom", tr('rewards.custom_rewards_2d9083', 'Custom rewards'))]
                + [(key, label) for key, label, _ in self.templates_of])

    def _choose_template(self, event) -> None:
        self.template = event.control.value
        if self.template == "seed":
            self.value = []
            self.on_change([])
        elif self.template != "custom":
            self._apply_template()
        self._render()

    def _set_template_quantity(self, event) -> None:
        text = event.control.value
        self.template_quantity = text
        if self.template in self.template_items:
            self._apply_template()
            for field in self.quantities:
                if not field.disabled:
                    field.value = text
                    t.mark_invalid(field, bool(quantity_error(text)))
        self._show_template()
        self.control.update()

    def _apply_template(self) -> None:
        self.value = [{"item_id": str(item), "quantity": str(fixed) if (fixed := self._fixed(item)) is not None
                       else self.template_quantity} for item in self.template_items[self.template]]
        self.on_change([dict(row) for row in self.value])

    def _quantity(self, event, index: int) -> None:
        text = event.control.value
        t.mark_invalid(event.control, bool(quantity_error(text)))
        self._set(index, "quantity", text)

    def _add(self, _event) -> None:
        if len(self.value) < self.max_rows and (self.den_of is None or self.den):
            self.value.append({"item_id": "", "quantity": "1"})
            self.template = "custom"
            self.on_change([dict(row) for row in self.value])
            self._render()

    def _remove(self, index: int) -> None:
        self.value.pop(index)
        self.template = self._template_of()
        self.template_quantity = self._template_quantity()
        self.on_change([dict(row) for row in self.value])
        self._render()

    def _render(self, update: bool = True) -> None:
        rows = []
        self.quantities = []
        for index, row in enumerate(self.value):
            item = NamePicker(self.app, self.game, "bag", str(row.get("item_id", "")),
                              lambda value, n=index: self._set(n, "item_id", value),
                              optional=False, only=None if self.den_of is None else set(self.den or ())).control
            fixed = self._fixed(row.get("item_id", ""))
            quantity = t.field(value=str(row.get("quantity", "1")), mono=True, width=110,
                               keyboard_type=ft.KeyboardType.NUMBER,
                               tooltip=tr('rewards.quantity_from_1_to_999_1e5f8e', 'Quantity from 1 to 999'),
                               on_change=lambda event, n=index: self._quantity(event, n))
            t.mark_invalid(quantity, bool(quantity_error(quantity.value)))
            if fixed is not None:
                quantity.disabled = True
                quantity.tooltip = tr('rewards.this_den_gives_this_item_at_this_count_8d2c41', 'This den gives this item at this count.')
            self.quantities.append(quantity)
            rows.append(ft.Row([
                ft.Container(t.text(str(index + 1), 11, t.BLUE, weight=ft.FontWeight.W_700), width=24, height=24,
                             margin=ft.Margin(0, 25, 0, 0), alignment=ft.Alignment.CENTER, border_radius=12,
                             bgcolor=ft.Colors.with_opacity(0.12, t.BLUE)),
                t.labeled_control(tr('rewards.item_652bcc', 'Item'), item, expand=True),
                t.labeled_control(tr('rewards.quantity_822bab', 'Quantity'), quantity),
                ft.Container(t.icon_button("close", lambda _e, n=index: self._remove(n), tr('rewards.remove_reward_242188', 'Remove reward')),
                             margin=ft.Margin(0, 20, 0, 0)),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START))
        if not rows:
            note = (tr('rewards.choose_a_boss_a_den_holds_to_choose_its_rewards_5be1d7', 'Choose a boss a den holds to choose its rewards.')
                    if self.den_of is not None and not self.den
                    else tr('rewards.the_raid_s_own_rewards_shown_with_the_raid_above_c9a3cd', "The raid's own rewards, shown with the raid above.")
                    if self.den_of is None
                    else tr('rewards.the_den_s_own_rewards_7a91c0', "The den's own rewards."))
            rows.append(ft.Row([t.pixel_icon("gift", color=t.FAINT), t.text(note, 12, t.MUTED)], spacing=8))
        self.rows.controls = rows
        self._show_template()
        self.add.disabled = len(self.value) >= self.max_rows or (self.den_of is not None and not self.den)
        if update:
            self.control.update()

    def _show_template(self) -> None:
        self.templates.value = self.template
        self.quantity.value = self.template_quantity
        t.mark_invalid(self.quantity, bool(quantity_error(self.template_quantity)))
        self.template_quantity_control.visible = self.template in self.template_items
        self.problem.value = self._problem()
        self.problem.visible = bool(self.problem.value)

    def _problem(self) -> str:
        if self.den_of is not None and self.value:
            if not self.den:
                return tr('rewards.choose_a_boss_a_den_holds_to_choose_its_rewards_5be1d7', 'Choose a boss a den holds to choose its rewards.')
            items = [str(row.get("item_id", "")) for row in self.value]
            if any(i and (not i.isdigit() or int(i) not in self.den) for i in items):
                return tr('rewards.some_rewards_are_not_this_den_s_choose_them_again_2c6e0f', "Some rewards are not this den's: choose them again.")
        if any(quantity_error(str(row.get("quantity", ""))) for row in self.value):
            return tr('rewards.quantities_must_be_from_1_to_999_18998d', 'Quantities must be from 1 to 999.')
        return ""

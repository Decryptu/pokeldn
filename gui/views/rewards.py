import flet as ft

from gui import theme as t
from gui.views.pokemon import NamePicker
from pokeldn.sv.raid import REWARD_ROWS


class RewardPicker:
    """A raid's reward rows in order, each an item from the game's bag list and a quantity. The value
    is [{"item_id", "quantity"}]; an empty list keeps the raid's own rewards."""

    def __init__(self, app, game: str, value, on_change):
        self.app, self.game, self.on_change = app, game, on_change
        self.value = [dict(row) for row in value] if isinstance(value, (list, tuple)) else []
        self.rows = ft.Column(spacing=8)
        self.add = t.secondary_button("Add reward", self._add, "plus")
        self.control = ft.Column([self.rows, self.add], spacing=10, tight=True)
        self._render(update=False)

    def _set(self, index: int, key: str, value: str) -> None:
        self.value[index][key] = value
        self.on_change([dict(row) for row in self.value])

    def _quantity(self, event, index: int) -> None:
        text = event.control.value
        event.control.error = None if text.isdigit() and 1 <= int(text) <= 999 else "1 to 999"
        event.control.update()
        self._set(index, "quantity", text)

    def _add(self, _event) -> None:
        if len(self.value) < REWARD_ROWS:
            self.value.append({"item_id": "", "quantity": "1"})
            self.on_change([dict(row) for row in self.value])
            self._render()

    def _remove(self, index: int) -> None:
        self.value.pop(index)
        self.on_change([dict(row) for row in self.value])
        self._render()

    def _render(self, update: bool = True) -> None:
        rows = []
        for index, row in enumerate(self.value):
            item = NamePicker(self.app, self.game, "bag", str(row.get("item_id", "")),
                              lambda value, n=index: self._set(n, "item_id", value),
                              optional=False).control
            quantity = t.field(value=str(row.get("quantity", "1")), mono=True, width=110,
                               keyboard_type=ft.KeyboardType.NUMBER,
                               on_change=lambda event, n=index: self._quantity(event, n))
            rows.append(ft.Row([
                ft.Container(t.text(str(index + 1), 12, t.MUTED), width=22, alignment=ft.Alignment.CENTER),
                ft.Column([t.text("Item", 11, t.MUTED), item], spacing=4, expand=True),
                ft.Column([t.text("Quantity", 11, t.MUTED), quantity], spacing=4),
                t.icon_button("close", lambda _e, n=index: self._remove(n), "Remove reward"),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.END))
        if not rows:
            rows.append(t.text("The raid's own rewards.", 12, t.MUTED))
        self.rows.controls = rows
        self.add.disabled = len(self.value) >= REWARD_ROWS
        if update:
            self.control.update()

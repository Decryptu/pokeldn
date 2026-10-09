import flet as ft

from gui import theme as t
from gui.views.pokemon import NamePicker
from pokeldn.sv.raid_catalog import load_catalog
from pokeldn.sv.raid_generation import MAX_REWARD_ROWS


# PKHeX's Scarlet/Violet entity type reports this as its highest item ID.  The
# shared name table also contains later games, which are not valid SV rewards.
SV_MAX_ITEM_ID = 2557


def reward_items() -> list[dict]:
    """The bundled SV item list, independent of the optional PKHeX service."""
    names = load_catalog()["item_names"]
    return [{"id": item_id, "name": names[item_id]}
            for item_id in range(1, min(len(names), SV_MAX_ITEM_ID + 1))
            if names[item_id].strip()]


class RewardPicker:
    """An ordered exact raid-reward list: a searchable item and quantity per row."""

    LIMIT = MAX_REWARD_ROWS

    def __init__(self, app, game: str, value, on_change):
        self.app, self.game, self.on_change = app, game, on_change
        self.items = reward_items()
        self.value = [dict(row) for row in value] if isinstance(value, (list, tuple)) else []
        self.rows = ft.Column(spacing=8)
        self.add = t.secondary_button("Add reward", self._add, "plus")
        self.control = ft.Column([self.rows, self.add], spacing=10, tight=True)
        self._render(update=False)

    def _save(self) -> None:
        self.on_change([dict(row) for row in self.value])

    def _set(self, index: int, key: str, value: str) -> None:
        while len(self.value) <= index:
            self.value.append({"item_id": "", "quantity": "1"})
        self.value[index][key] = value
        self._save()

    def _quantity(self, event, index: int) -> None:
        value = event.control.value
        try:
            number = int(value)
        except ValueError:
            number = 0
        event.control.error = None if 1 <= number <= 999 else "1 to 999"
        event.control.update()
        self._set(index, "quantity", value)

    def _add(self, _event) -> None:
        if len(self.value) >= self.LIMIT:
            return
        self.value.append({"item_id": "", "quantity": "1"})
        self._save()
        self._render()

    def _remove(self, index: int) -> None:
        self.value.pop(index)
        self._save()
        self._render()

    def _render(self, update: bool = True) -> None:
        shown = self.value or [{"item_id": "", "quantity": "1"}]
        controls = []
        for index, row in enumerate(shown):
            item = NamePicker(
                self.app, self.game, "item", str(row.get("item_id", "")),
                lambda value, n=index: self._set(n, "item_id", value), optional=False,
                names=self.items).control
            quantity = t.field(
                value=str(row.get("quantity", "1")), mono=True,
                width=110, keyboard_type=ft.KeyboardType.NUMBER,
                error=(None if str(row.get("quantity", "1")).isdigit()
                       and 1 <= int(row.get("quantity", "1")) <= 999 else "1 to 999"),
                on_change=lambda event, n=index: self._quantity(event, n))
            controls.append(ft.Row([
                ft.Container(t.text(str(index + 1), 12, t.MUTED), width=22,
                             alignment=ft.Alignment.CENTER),
                ft.Column([t.text("Item", 11, t.MUTED), item], spacing=4, expand=True),
                ft.Column([t.text("Quantity", 11, t.MUTED), quantity], spacing=4),
                t.icon_button("close", lambda _event, n=index: self._remove(n), "Remove reward",
                              disabled=not self.value),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.END))
        self.rows.controls = controls
        self.add.disabled = len(self.value) >= self.LIMIT
        if update:
            try:
                self.control.update()
            except RuntimeError:  # The picker may be populated before its card reaches the page.
                pass

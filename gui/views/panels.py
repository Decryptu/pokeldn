"""A plugin's status cards at the top of its tool's page, as its runs left them [pokeldn.panel,
pokeldn.app.panels, docs/plugins.md, Status cards]."""
from pathlib import Path

import flet as ft

from gui import theme as t
from pokeldn import plugins
from pokeldn.app import panels

TONES = {"ok": ("check", t.GREEN), "warning": ("warning-diamond", t.AMBER), "error": ("close", t.RED)}


def image(path: str | None, size: int) -> ft.Control | None:
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return ft.Container(ft.Image(src=t.image_src(data), width=size, height=size, fit=ft.BoxFit.COVER),
                        width=size, height=size, border_radius=size // 6, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


class StatusCards:
    def __init__(self, plugin: plugins.Plugin):
        self.plugin = plugin
        self.column = ft.Column(spacing=t.GAP)

    def control(self) -> ft.Control:
        self.refresh(update=False)
        return self.column

    def refresh(self, update: bool = True) -> None:
        cards = panels.load(self.plugin.id)["cards"]
        self.column.controls = [self._card(c) for c in cards.values()]
        self.column.visible = bool(cards)
        if update:
            self.column.update()

    def _card(self, card: dict) -> ft.Control:
        return card_control(card, image(panels.image(self.plugin, card.get("image")), 96))


def card_control(card: dict, art: ft.Control | None = None) -> ft.Control:
    """A `[panel]` card (pokeldn.panel.read) at the top of its tool's page."""
    head = [t.text(card["title"], 18, weight=ft.FontWeight.W_600, expand=True)]
    if card["tone"] in TONES:
        icon, color = TONES[card["tone"]]
        head.insert(0, t.pixel_icon(icon, color=color))
    chips = [t.chip(f"{label} {value}".strip(), color=t.BLUE) for label, value in card["chips"]]
    rows = []
    for line in card["lines"]:
        if isinstance(line, list):
            rows.append(ft.Row([t.text(line[0], 12, t.MUTED, width=128), t.text(line[1], 13, expand=True)],
                               spacing=12, vertical_alignment=ft.CrossAxisAlignment.START))
        else:
            rows.append(t.text(line, 13, t.SOFT))
    body = ft.Column([ft.Row(head, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                      *([ft.Row(chips, spacing=6, wrap=True, run_spacing=6)] if chips else []),
                      *([ft.Column(rows, spacing=4)] if rows else [])], spacing=10, expand=True, tight=True)
    content = ft.Row([art, body], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START) if art else body
    return t.surface(ft.Container(content, padding=16))

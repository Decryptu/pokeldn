import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui import paths  # noqa: E402,F401  (puts the repository and vendor/LDN on sys.path)

if len(sys.argv) > 2 and sys.argv[1] in ("--run", "--module"):
    from gui.runner import child
    child(sys.argv[1:])
    sys.exit(0)

# The app's own process never drives a board: an inherited POKELDN_RADIO would open the port as
# soon as pokeldn.ldn is imported.
os.environ.pop("POKELDN_RADIO", None)

import flet as ft  # noqa: E402

from gui import theme as t  # noqa: E402
from gui.app import App  # noqa: E402
from gui.paths import ROOT  # noqa: E402

PAGES = (
    ("games", "Games", ft.Icons.SPORTS_ESPORTS_OUTLINED, ft.Icons.SPORTS_ESPORTS),
    ("board", "Board", ft.Icons.MEMORY_OUTLINED, ft.Icons.MEMORY),
    ("docs", "Docs", ft.Icons.MENU_BOOK_OUTLINED, ft.Icons.MENU_BOOK),
)
SETTINGS = ("settings", "Settings", ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS)


def main(page: ft.Page) -> None:
    page.title = "pokeldn"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = page.dark_theme = t.app_theme()
    page.bgcolor = t.BG
    page.padding = 12
    page.window.min_width, page.window.min_height = 1180, 720
    page.window.width, page.window.height = 1440, 900
    page.window.bgcolor = t.BG

    app = App(page)
    views: dict[str, object] = {}
    content = ft.Container(expand=True)
    rail = ft.Column(spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    bottom = ft.Column(spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    current = {"key": "games"}

    def build(key: str):
        if key == "games":
            from gui.views.games import GamesView
            return GamesView(app)
        if key == "board":
            from gui.views.boards import BoardView
            return BoardView(app)
        if key == "docs":
            from gui.views.docs import DocsView
            return DocsView(app)
        from gui.views.settings import SettingsView
        return SettingsView(app)

    def item(entry) -> ft.Control:
        key, label, icon, selected_icon = entry
        active = key == current["key"]
        color = t.RED if active else t.MUTED
        return ft.Container(ft.Stack([
            ft.Container(ft.Column([
                ft.Icon(selected_icon if active else icon, size=22, color=color),
                t.text(label, 10.5, color, weight=ft.FontWeight.W_600),
            ], spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                width=72, padding=ft.Padding(0, 9, 0, 9)),
            ft.Container(width=3, height=34, bgcolor=t.RED if active else None, border_radius=2,
                         left=0, top=12),
        ]), on_click=lambda e, k=key: navigate(k), tooltip=label)

    def render_rail() -> None:
        rail.controls = [item(p) for p in PAGES]
        bottom.controls = [item(SETTINGS)]

    def navigate(key: str, **kwargs) -> None:
        previous = views.get(current["key"])
        if previous is not None and hasattr(previous, "leave"):
            previous.leave()
        current["key"] = key
        if key not in views:
            views[key] = build(key)
        view = views[key]
        if hasattr(view, "enter"):
            view.enter(**kwargs)
        content.content = view.control
        render_rail()
        page.update()

    app.navigate = navigate
    side = ft.Container(ft.Column([
        ft.Container(ft.Image(src="logo.svg", width=34, height=38), padding=ft.Padding(0, 10, 0, 18)),
        rail,
        ft.Container(expand=True),
        bottom,
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0), width=72)
    page.add(ft.Row([side, content], spacing=12, expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    navigate("games")


def run() -> None:
    assets = os.path.join(ROOT, "gui", "assets")
    if os.environ.get("POKELDN_GUI_WEB"):   # a browser preview, for screenshots
        ft.run(main, assets_dir=assets, view=ft.AppView.WEB_BROWSER, no_cdn=True,
               port=int(os.environ["POKELDN_GUI_WEB"]))
    else:
        ft.run(main, assets_dir=assets)


if __name__ == "__main__":
    run()

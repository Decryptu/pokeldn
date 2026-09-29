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
    page.padding = 0
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
                width=70, padding=ft.Padding(0, 9, 0, 9)),
            ft.Container(width=3, height=30, bgcolor=t.RED if active else None,
                         border_radius=ft.BorderRadius(0, 3, 0, 3), left=0, top=14),
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
    side = t.panel(ft.Column([
        ft.Container(ft.Image(src="logo.svg", width=32, height=36), padding=ft.Padding(0, 14, 0, 14)),
        ft.Container(height=1, width=36, bgcolor=t.BORDER, margin=ft.Margin(0, 0, 0, 10)),
        rail,
        ft.Container(expand=True),
        bottom,
        ft.Container(height=8),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0), width=72)
    page.add(t.backdrop(ft.Row([side, content], spacing=14, expand=True,
                               vertical_alignment=ft.CrossAxisAlignment.STRETCH)))
    navigate("games")
    if not os.path.isfile(os.path.expanduser(app.settings.keys)):
        welcome(app)


def welcome(app: App) -> None:
    """The one file the app cannot ship: the user's own Switch keys."""
    async def choose(e):
        files = await app.picker.pick_files(allowed_extensions=["keys"], file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            app.settings.keys = files[0].path
            app.settings.save()
            app.page.pop_dialog()

    app.page.show_dialog(ft.AlertDialog(
        modal=True, bgcolor=t.PANEL, shape=ft.RoundedRectangleBorder(radius=16),
        title=t.text("Welcome to pokeldn", 18, weight=ft.FontWeight.W_700),
        content=ft.Container(ft.Column([
            ft.Image(src="logo.svg", width=44, height=48),
            t.text("pokeldn needs your Switch's prod.keys, dumped from your own console. It decrypts the "
                   "local wireless messages and never leaves this computer.", 13, t.MUTED),
            t.text("Everything else is included.", 13, t.MUTED),
        ], spacing=10, tight=True), width=420),
        actions=[ft.TextButton("Later", on_click=lambda e: app.page.pop_dialog(),
                               style=ft.ButtonStyle(color=t.MUTED)),
                 t.button("Choose prod.keys", choose, ft.Icons.KEY_ROUNDED)],
    ))


def run() -> None:
    assets = os.path.join(ROOT, "gui", "assets")
    if os.environ.get("POKELDN_GUI_WEB"):   # a browser preview, for screenshots
        ft.run(main, assets_dir=assets, view=ft.AppView.WEB_BROWSER, no_cdn=True,
               port=int(os.environ["POKELDN_GUI_WEB"]))
    else:
        ft.run(main, assets_dir=assets)


if __name__ == "__main__":
    run()

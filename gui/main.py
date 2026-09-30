import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.app import paths  # noqa: E402,F401  (puts the repository and vendor/LDN on sys.path)

if len(sys.argv) > 2 and sys.argv[1] in ("--run", "--module"):
    from pokeldn.app.runner import child
    child(sys.argv[1:])
    sys.exit(0)

# The app's own process never drives a board: an inherited POKELDN_RADIO would open the port as
# soon as pokeldn.ldn is imported.
os.environ.pop("POKELDN_RADIO", None)

import flet as ft  # noqa: E402

from gui import theme as t  # noqa: E402
from gui.app import App  # noqa: E402
from pokeldn.app.paths import ROOT  # noqa: E402

PAGES = (
    ("games", "Games", "gamepad"),
    ("board", "Board", "cpu"),
    ("docs", "Docs", "book-open"),
)
SETTINGS = ("settings", "Settings", "gear")


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
        key, label, icon = entry
        active = key == current["key"]
        color = t.RED if active else t.MUTED
        return ft.Semantics(selected=active, button=True, label=label, exclude_semantics=True,
                            on_tap=lambda e, k=key: navigate(k), content=ft.Container(ft.Stack([
            ft.Container(ft.Column([
                t.pixel_icon(icon, size=24, color=color),
                t.text(label, 10.5, color, weight=ft.FontWeight.W_600),
            ], spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                width=70, padding=ft.Padding(0, 9, 0, 9)),
            ft.Container(width=3, height=30, bgcolor=t.RED if active else None,
                         border_radius=ft.BorderRadius(0, 3, 0, 3), left=0, top=14),
        ]), on_click=lambda e, k=key: navigate(k), tooltip=label))

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
    page.add(t.backdrop(ft.Row([side, content], spacing=t.GAP, expand=True,
                               vertical_alignment=ft.CrossAxisAlignment.STRETCH)))
    navigate("games")
    if not os.path.isfile(os.path.expanduser(app.settings.keys)):
        welcome(app)


def welcome(app: App) -> None:
    """The one file the app cannot ship: the user's own Switch keys."""
    def close(e):
        app.page.pop_dialog()

    async def choose(e):
        files = await app.picker.pick_files(allowed_extensions=["keys"], file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            app.settings.keys = files[0].path
            app.settings.save()
            app.page.pop_dialog()
            app.navigate("games")

    def instructions(e):
        app.page.pop_dialog()
        app.navigate("docs", doc="guide")

    def ready(icon, title, description):
        return ft.Row([
            ft.Container(t.pixel_icon(icon, size=24, color=t.MUTED), width=44, height=44,
                         alignment=ft.Alignment.CENTER, bgcolor=t.FIELD, border_radius=10),
            ft.Column([t.text(title, 13, weight=ft.FontWeight.W_600),
                       t.text(description, 12, t.MUTED)], spacing=3, expand=True),
        ], spacing=14)

    body = ft.Column([
        t.text("Connect your games", 24, weight=ft.FontWeight.W_600),
        t.text("Trade and send gifts over local wireless, right from your computer.", 13, t.MUTED),
        ft.Container(height=4),
        t.surface(ft.Container(ft.Column([
            ft.Row([
                ft.Container(t.pixel_icon("key", size=24, color=t.BLUE), width=44, height=44,
                             alignment=ft.Alignment.CENTER,
                             bgcolor=ft.Colors.with_opacity(0.1, t.BLUE), border_radius=10),
                ft.Column([t.text("Add your Switch keys", 14, weight=ft.FontWeight.W_600),
                           t.text("The only file you need to bring.", 12, t.MUTED)], spacing=3, expand=True),
                t.pill("Required", t.BLUE),
            ], spacing=14),
            t.text("Choose prod.keys dumped from your own console. These keys decrypt local wireless "
                   "messages and stay on this computer.", 13, t.MUTED),
            t.link_button("Read the setup guide", instructions),
        ], spacing=12, tight=True), padding=18), stroke=ft.Colors.with_opacity(0.45, t.BLUE), radius=28),
        ft.Container(height=4),
        ready("usb", "Plug in your ESP32", "Connect your radio with a USB data cable."),
        ready("gamepad", "Pick a game", "Choose a tool and follow the console steps."),
    ], spacing=12, tight=True)
    app.page.show_dialog(ft.AlertDialog(
        modal=True, bgcolor=t.PANEL, elevation=24,
        shape=ft.ContinuousRectangleBorder(radius=36, side=ft.BorderSide(1, t.OUTLINE)),
        barrier_color=ft.Colors.with_opacity(0.65, "#000000"),
        content_padding=0, actions_padding=0, inset_padding=32,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        semantics_label="Welcome to pokeldn",
        content=ft.Container(ft.Column([
            ft.Container(ft.Row([
                ft.Image(src="logo.svg", width=28, height=32),
                t.text("Welcome to pokeldn", 16, weight=ft.FontWeight.W_600, expand=True),
                t.icon_button("close", close, "Close welcome"),
            ], spacing=12), padding=ft.Padding(24, 18, 18, 18),
                border=ft.Border(bottom=ft.BorderSide(1, t.DIVIDER))),
            ft.Container(body, padding=24),
            ft.Container(ft.Row([
                t.text("Add keys later in Settings.", 12, t.MUTED, expand=True),
                t.secondary_button("Later", close),
                t.button("Choose prod.keys", choose, "key"),
            ], spacing=10), padding=ft.Padding(24, 18, 24, 22),
                border=ft.Border(top=ft.BorderSide(1, t.DIVIDER))),
        ], spacing=0, tight=True), width=540),
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

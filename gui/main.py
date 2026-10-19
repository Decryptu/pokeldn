import os
import subprocess
import sys
import tarfile
import threading
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.app import paths  # noqa: E402,F401  (puts the repository and vendor/LDN on sys.path)

if len(sys.argv) > 2 and sys.argv[1] in ("--run", "--module"):
    from pokeldn.app.runner import child
    child(sys.argv[1:])
    sys.exit(0)

if len(sys.argv) == 6 and sys.argv[1] == "--apply-update":
    # The new app, unpacked by the old one, replaces it; pokeldn.app.update.start_swap passes these.
    from pathlib import Path
    from gui.updating import run
    new, target, pid, version = sys.argv[2:]
    os.chdir(Path(new).parent)   # an older app started this helper in target; Windows then refuses the rename
    sys.exit(run(Path(new), Path(target), int(pid), version))

# The app's own process never drives a board: an inherited POKELDN_RADIO would open the port as
# soon as pokeldn.ldn is imported.
os.environ.pop("POKELDN_RADIO", None)

from pokeldn.app.i18n import select, t as tr  # noqa: E402
from pokeldn.app.settings import load as load_settings  # noqa: E402
select(load_settings().app_language)

import flet as ft  # noqa: E402

from gui import drop, flet_client, screen, theme as t  # noqa: E402
from gui.app import App  # noqa: E402
from gui.localization import flet_locale  # noqa: E402
from gui.views.widgets import page_key  # noqa: E402
from pokeldn import __version__, popup  # noqa: E402
from pokeldn.app import update  # noqa: E402
from pokeldn.app.paths import ROOT  # noqa: E402

PAGES = (
    ("games", tr('main.games_d9dae7', 'Games'), "gamepad"),
    ("board", tr('main.board_4816cb', 'Board'), "cpu"),
    ("bank", tr('main.bank_676c47', 'Bank'), "package"),
    ("gts", tr('main.gts_c530c8', 'GTS'), "globe"),
    ("controller", tr('main.control_32d7e8', 'Control'), "joystick"),
    ("docs", tr('main.docs_7af023', 'Docs'), "book-open"),
)
PLUGINS = ("plugins", tr('main.plugins_9514b7', 'Plugins'), "plug")
SETTINGS = ("settings", tr('main.settings_74a883', 'Settings'), "gear")
UPDATE = ("update", tr('main.update_c1c100', 'Update'), "download")


ANDROID = os.environ.get("POKELDN_PLATFORM") == "android"
IOS = os.environ.get("POKELDN_PLATFORM") == "ios"
if ANDROID or IOS:   # no Bluetooth controller and no self-update on a phone (examples/android, examples/ios)
    PAGES = tuple(p for p in PAGES if p[0] != "controller")


def main(page: ft.Page) -> None:
    t.compact = bool(page.width) and page.width < t.COMPACT_WIDTH
    page.title = "pokeldn"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = page.dark_theme = t.app_theme()
    page.locale_configuration = flet_locale()
    page.bgcolor = t.BG
    page.padding = 0
    # 1440 x 900 overflows a 13-inch MacBook Air (1440 x 932 points less the menu bar): fit, then center.
    (width, height), (min_width, min_height) = screen.fit((1440, 900), (1180, 720), screen.size())
    page.window.min_width, page.window.min_height = min_width, min_height
    page.window.width, page.window.height = width, height
    page.window.bgcolor = t.BG
    if not page.web:
        page.window.title_bar_hidden = True
        page.window.title_bar_buttons_hidden = False

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
        if key == "bank":
            from gui.views.bank import BankView
            return BankView(app)
        if key == "gts":
            from gui.views.gts import GtsView
            return GtsView(app)
        if key == "controller":
            from gui.views.controller import ControllerView
            return ControllerView(app)
        if key == "docs":
            from gui.views.docs import DocsView
            return DocsView(app)
        if key == "plugins":
            from gui.views.plugins import PluginsView
            return PluginsView(app)
        from gui.views.settings import SettingsView
        return SettingsView(app)

    def item(entry) -> ft.Control:
        key, label, icon = entry
        active = key == current["key"]
        if t.compact:
            color = t.RED if active else t.MUTED
            return ft.Container(ft.Column([
                t.pixel_icon(icon, size=24, color=color),
                t.text(label, 10, color, weight=ft.FontWeight.W_500, no_wrap=True),
            ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER), expand=True,
                padding=ft.Padding(0, 7, 0, 6), border_radius=12, on_click=lambda e, k=key: navigate(k),
                bgcolor=ft.Colors.with_opacity(0.12, t.RED) if active else None)
        fresh = key == "update" or (key == "plugins" and bool(app.plugin_updates))
        color = t.RED if active else t.GREEN if fresh else t.MUTED
        return ft.Semantics(selected=active, button=True, label=label, exclude_semantics=True,
                            on_tap=lambda e, k=key: navigate(k), content=ft.Container(ft.Column([
            t.pixel_icon(icon, size=24, color=color),
            t.text(label, 11, color, weight=ft.FontWeight.W_500),
        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=56, padding=ft.Padding(0, 8, 0, 7), border_radius=12,
            bgcolor=ft.Colors.with_opacity(0.12, t.RED) if active else None,
            on_click=lambda e, k=key: navigate(k),
            tooltip=tr('main.plugin_updates_1cc5ea', 'Plugin updates') if key == "plugins" and app.plugin_updates else label))

    def render_rail() -> None:
        if t.compact:
            tabs.controls = [item(p) for p in (*PAGES, PLUGINS, SETTINGS)]
            return
        rail.controls = [item(p) for p in PAGES]
        bottom.controls = [item(UPDATE)] * bool(app.update and not (ANDROID or IOS)) + [item(PLUGINS), item(SETTINGS)]

    def navigate(key: str, **kwargs) -> None:
        if key == "update":
            offer_update(app)
            return
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
    page.on_keyboard_event = page_key     # set once, before a code box takes the focus
    tabs = ft.Row(spacing=2)
    if t.compact:
        bar = t.glass(ft.Container(tabs, padding=4), radius=18)
        window = t.backdrop(ft.Column([content, bar], spacing=8, expand=True))
        window.padding = ft.Padding(8, 8, 8, 8)
        page.add(window)
        navigate("games")
        compact_start(app)
        return
    side = t.panel(ft.Column([
        ft.Container(ft.Image(src="logo.svg", width=28, height=32), padding=ft.Padding(0, 16, 0, 18)),
        rail,
        ft.Container(expand=True),
        bottom,
        ft.Container(height=8),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0), width=72)
    body = ft.Row([side, content], spacing=t.GAP, expand=True,
                  vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    # The header sits on the checkerboard so the grid runs under the hidden title bar too.
    window = t.backdrop(ft.Column([window_header(page), body], spacing=0, expand=True))
    window.padding = ft.Padding(t.GAP, 0, t.GAP, t.GAP)
    page.add(window)
    navigate("games")
    if not page.web:
        page.run_task(page.window.center)
    outcome = update.finish(update.install_root())
    if not os.path.isfile(os.path.expanduser(app.settings.keys)):
        welcome(app)
    elif outcome:
        updated_notice(app, outcome)
    elif app.plugin_stopped:
        plugin_stopped_notice(app)

    def updated() -> None:
        render_rail()
        page.update()
    app.update_listeners.append(updated)
    app.plugin_update_listeners.append(updated)
    if getattr(sys, "frozen", False):
        threading.Thread(target=prune_viewers, daemon=True).start()
    if app.settings.check_updates:
        app.check_update()
        app.check_plugin_updates()
    from gui.views.gts import resume
    resume(app)      # a listing or an offer left open is answered while the app runs


def compact_start(app: App) -> None:
    """The phone's start: the same first-run notices, without the desktop's update and viewer housekeeping."""
    if not os.path.isfile(os.path.expanduser(app.settings.keys)):
        welcome(app)
    elif app.plugin_stopped:
        plugin_stopped_notice(app)
    if app.settings.check_updates:
        app.check_plugin_updates()
    from gui.views.gts import resume
    resume(app)


def prune_viewers() -> None:
    try:
        flet_client.prune_cache()
    except Exception:   # housekeeping: a locked or vanished folder waits for the next launch
        pass


def offer_update(app: App) -> None:
    """A newer release on GitHub: installed in place when this copy can replace itself, else its file."""
    release = app.update
    root = update.install_root()
    reason = update.blocker(root) if release.installable else "manual"
    admin = not reason and update.needs_admin(root)

    def close(e):
        app.page.pop_dialog()

    def open_(url):
        def go(e):
            app.page.pop_dialog()
            app.page.run_task(app.open_url, url)
        return go

    def install(e):
        if app.busy:
            note.value, note.color = tr('main.finish_the_running_session_flash_or_cleanup_first_4771cf', 'Finish the running session, flash or cleanup first.'), t.RED
            note.update()
            return
        app.page.pop_dialog()
        install_update(app, release, admin)

    note = t.text(tr('main.you_have_c04a93', 'You have {value0}. ', value0=__version__)
                  + (tr('main.pokeldn_downloads_it_checks_it_and_restarts_in_the_new__d1543b', 'pokeldn downloads it, checks it and restarts in the new version. ') if not reason else
                     tr('main.download_the_new_version_then_replace_this_app_with_it_880281', 'Download the new version, then replace this app with it. ') if release.download != release.page else
                     tr('main.download_the_new_version_for_your_computer_from_the_rel_47361e', 'Download the new version for your computer from the release page, then replace this app with it. '))
                  + (f"{reason} " if reason and reason != "manual" else "")
                  + (tr('main.windows_asks_for_permission_to_change_5b8fb6', 'Windows asks for permission to change {value0}. ', value0=root.parent) if admin else "")
                  + tr('main.your_settings_keys_and_received_pokemon_stay_where_they_d5360a', 'Your settings, keys and received Pokemon stay where they are.'), 13, t.MUTED)
    main = (t.button(tr('main.update_now_63bf04', 'Update now'), install, "download") if not reason else
            t.button(tr('main.download_d6eafe', 'Download'), open_(release.download), "download"))
    app.page.show_dialog(t.dialog(
        semantics_label=tr('main.update_available_ff8b55', 'Update available'),
        title=t.text(tr('main.pokeldn_is_available_005454', 'pokeldn {value0} is available', value0=release.version), 17, weight=ft.FontWeight.W_600),
        content=ft.Container(note, width=460),
        actions=[t.link_button(tr('main.what_s_new_135e91', "What's new"), open_(release.page)),
                 t.secondary_button(tr('main.later_73b6e4', 'Later'), close), main],
    ))
    app.page.update()   # also shown from a background check, where Flet does not flush on its own


def install_update(app: App, release: update.Release, admin: bool = False) -> None:
    """Downloads and checks the release, then quits so the new app can take this one's place."""
    stop = threading.Event()
    status = t.text(tr('main.downloading_f976eb', 'Downloading...'), 13, t.MUTED)
    bar = ft.ProgressBar(value=None, color=t.BLUE, bgcolor=t.FIELD, height=4)
    cancel = t.secondary_button(tr('main.cancel_19766e', 'Cancel'), lambda e: stop.set())
    app.page.show_dialog(t.dialog(
        semantics_label=tr('main.updating_0b5260', 'Updating'), modal=True,
        title=t.text(tr('main.updating_to_47aca3', 'Updating to {value0}', value0=release.version), 17, weight=ft.FontWeight.W_600),
        content=ft.Container(ft.Column([status, bar], spacing=12, tight=True), width=460),
        actions=[cancel]))
    app.page.update()
    shown = [0.0]

    def progress(done: int, total: int) -> None:
        now = time.monotonic()
        if now - shown[0] < 0.2 and done != total:
            return
        shown[0] = now

        def show():
            mb = 1 << 20
            status.value = (tr('main.downloading_of_mb_797da4', 'Downloading {value0:.0f} of {value1:.0f} MB', value0=done / mb, value1=total / mb) if total else
                            tr('main.downloading_mb_3d82fe', 'Downloading {value0:.0f} MB', value0=done / mb))
            bar.value = done / total if total else None
            app.page.update()
        app.ui(show)

    def failed(message: str) -> None:
        app.page.pop_dialog()
        app.page.show_dialog(t.dialog(
            semantics_label=tr('main.update_failed_e58282', 'Update failed'),
            title=t.text(tr('main.the_update_did_not_install_d79712', 'The update did not install'), 17, weight=ft.FontWeight.W_600),
            content=ft.Container(t.text(tr('main.this_app_is_unchanged_you_can_download_the_new_version__8f43d1', '{value0}{value1}. This app is unchanged; you can download the new version yourself.', value0=message[:1].upper(), value1=message[1:]), 13, t.MUTED), width=460),
            actions=[t.secondary_button(tr('main.close_7d9eb7', 'Close'), lambda e: app.page.pop_dialog()),
                     t.button(tr('main.download_d6eafe', 'Download'), lambda e: (app.page.pop_dialog(),
                                                     app.page.run_task(app.open_url, release.download)), "download")]))
        app.page.update()

    def restart() -> None:
        status.value, bar.value, cancel.disabled = tr('main.restarting_in_the_new_version_d1dfd3', 'Restarting in the new version...'), None, True
        app.page.update()

        async def quit_():
            await app.page.window.destroy()
        app.page.run_task(quit_)
        # The helper waits for this process to end; a window that never closes must not hold it.
        threading.Timer(5.0, lambda: os._exit(0)).start()

    def work():
        root = update.install_root()
        try:
            new = update.prepare(release, progress, stop.is_set)
            if stop.is_set():
                raise update.Cancelled
            update.start_swap(new, root, release.version, admin=admin)
            # This window stays until the helper's own is up, so one is always on screen.
            update.wait_for(update.READY.exists, 15.0)
        except update.Cancelled:
            app.ui(app.page.pop_dialog)
            return
        except (OSError, subprocess.CalledProcessError, tarfile.TarError, zipfile.BadZipFile) as error:
            message = str(error) or type(error).__name__
            app.ui(lambda: failed(message))
            return
        app.ui(restart)

    threading.Thread(target=work, daemon=True).start()


def updated_notice(app: App, outcome: dict) -> None:
    """What the last update did, shown once by the app it opened."""
    error, version = outcome.get("error") or "", str(outcome.get("version") or "")
    if not error and version == __version__:
        app.page.show_dialog(ft.SnackBar(ft.Text(tr('main.pokeldn_updated_to_1f62a1', 'pokeldn updated to {value0}', value0=__version__)), duration=4000))
        return
    popup.acknowledge(tr('main.the_update_did_not_install_d79712', 'The update did not install'),
                      tr('main.pokeldn_could_not_replace_this_app_this_app_is_unchange_23fff0', 'pokeldn {value0} could not replace this app: {value1}. This app is unchanged.', value0=version, value1=error or tr('main.it_opened_the_old_version_6f6d59', 'it opened the old version')), id="update-failed", label=tr('main.close_7d9eb7', 'Close'), tone="error")


def plugin_stopped_notice(app: App) -> None:
    """A plugin froze or closed the app last time while it started; App turned it off."""
    popup.confirm(tr('main.a_plugin_was_turned_off_ed25fc', 'A plugin was turned off'),
                  tr('main.pokeldn_closed_or_stopped_answering_last_time_while_sta_bc8a75', 'pokeldn closed or stopped answering last time while starting the plugin {value0}. It is off now; turn it on again on the Plugins page once its author has a fix.', value0=app.plugin_stopped),
                  tr('main.open_plugins_2faa63', 'Open Plugins'), tr('main.not_now_a0e63d', 'Not now'), id="plugin-stopped", tone="warning",
                  on_agree=lambda: app.ui(lambda: app.navigate("plugins")))


def welcome(app: App) -> None:
    """The one file the app cannot ship: the user's own Switch keys."""
    def close(e):
        app.page.pop_dialog()

    def use(path: str) -> None:
        app.settings.keys = path
        app.settings.save()
        app.page.pop_dialog()
        app.navigate("games")

    async def choose(e):
        files = await app.picker.pick_files(allowed_extensions=["keys"], file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            use(files[0].path)

    def dropped(paths: list[str]) -> None:
        if path := next((p for p in paths if drop.suffix(p) == "keys"), ""):
            use(path)

    def instructions(e):
        app.page.pop_dialog()
        app.navigate("docs", doc="guide")

    body = ft.Column([
        ft.Row([ft.Image(src="logo.svg", width=28, height=32), ft.Container(expand=True),
                t.icon_button("close", close, tr('main.close_welcome_dcd26c', 'Close welcome'))],
               vertical_alignment=ft.CrossAxisAlignment.START),
        t.text(tr('main.welcome_to_pokeldn_319d9e', 'Welcome to pokeldn'), 22, weight=ft.FontWeight.W_600),
        t.text(tr('main.trade_and_send_gifts_over_local_wireless_right_from_you_11fb42', 'Trade and send gifts over local wireless, right from your computer.'), 13, t.MUTED),
        ft.Container(height=6),
        t.step_list([
            tr('main.choose_prod_keys_dumped_from_your_own_console_the_keys__07399e', 'Choose prod.keys dumped from your own console. The keys decrypt local wireless messages and stay on this computer.'),
            tr('main.android_board_step', 'Plug an ESP32-S3, C3 or C6 into the phone with a USB data cable.') if ANDROID else
            tr('main.ios_board_step', 'Power an ESP32-C6, S3 or C3 running the Bluetooth radio firmware; the app finds it on its own.') if IOS else
            tr('main.plug_in_your_esp32_with_a_usb_data_cable_0b0ddf', 'Plug in your ESP32 with a USB data cable.'),
            tr('main.pick_a_game_choose_a_tool_and_follow_the_console_steps_a4a338', 'Pick a game, choose a tool and follow the console steps.'),
        ]),
        ft.Row([t.link_button(tr('main.read_the_setup_guide_d201fc', 'Read the setup guide'), instructions)]),
    ], spacing=8, tight=True)
    note = t.text(tr('main.drop_prod_keys_here_or_add_keys_later_in_settings_b49b46', 'Drop prod.keys here, or add keys later in Settings.') if drop.AVAILABLE else
                  tr('main.add_keys_later_in_settings_8bc2f9', 'Add keys later in Settings.'), 12, t.FAINT, expand=not t.compact)
    buttons = [t.secondary_button(tr('main.later_73b6e4', 'Later'), close),
               t.button(tr('main.choose_prod_keys_782614', 'Choose prod.keys'), choose, "key")]
    footer = (ft.Column([note, ft.Row(buttons, spacing=8, alignment=ft.MainAxisAlignment.END)], spacing=10) if t.compact
              else ft.Row([note, *buttons], spacing=8))
    app.page.show_dialog(t.dialog(
        modal=True, content_padding=0, actions_padding=0, inset_padding=14 if t.compact else 32,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        semantics_label=tr('main.welcome_to_pokeldn_319d9e', 'Welcome to pokeldn'),
        content=drop.target(ft.Container(ft.Column([
            ft.Container(body, padding=ft.Padding(28, 22, 18, 8)),
            ft.Container(footer, padding=ft.Padding(28, 12, 24, 24)),
        ], spacing=0, tight=True), width=500, border_radius=20), dropped),
    ))


def window_header(page: ft.Page) -> ft.Control:
    mac = sys.platform == "darwin"
    title = ft.Container(height=40)
    drag = title if page.web else ft.WindowDragArea(title)
    drag.expand = True
    controls = [drag]
    if not page.web and not mac:
        async def close(e):
            await page.window.close()

        def minimize(e):
            page.window.minimized = True
            page.update()

        def maximize(e):
            page.window.maximized = not page.window.maximized
            page.update()

        controls.extend([
            ft.IconButton(ft.Icons.REMOVE, tooltip=tr('main.minimize_d72e31', 'Minimize'), on_click=minimize, icon_size=16),
            ft.IconButton(ft.Icons.CROP_SQUARE, tooltip=tr('main.maximize_or_restore_9e47a6', 'Maximize or restore'), on_click=maximize, icon_size=14),
            ft.IconButton(ft.Icons.CLOSE, tooltip=tr('main.close_7d9eb7', 'Close'), on_click=close, icon_size=16),
        ])
    return ft.Container(ft.Row(controls, spacing=0), height=40)


def run() -> None:
    assets = os.path.join(ROOT, "gui", "assets")
    drop.use_client()
    if os.environ.get("POKELDN_GUI_WEB"):   # a browser preview, for screenshots
        ft.run(main, assets_dir=assets, view=ft.AppView.WEB_BROWSER, no_cdn=True,
               port=int(os.environ["POKELDN_GUI_WEB"]))
    else:
        ft.run(main, assets_dir=assets)


if __name__ == "__main__":
    run()

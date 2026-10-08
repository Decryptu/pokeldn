"""The small window the new app shows while it replaces the old one (pokeldn.app.update.apply).

The old app closes its window once this one is up (update.READY); this one closes once the new app
has opened (it removes update.OUTCOME). docs/gui.md (Updates).
"""
import os
import threading
from pathlib import Path

from pokeldn.app import update
from pokeldn.app.paths import ROOT


def run(new: Path, target: Path, pid: int, version: str) -> None:
    def work():
        ok = update.apply(new, target, pid, version, helper=os.getpid())
        update.wait_for(lambda: not update.OUTCOME.exists(), 60.0)
        os._exit(0 if ok else 1)

    # The window is a courtesy: the swap never waits on it, and runs to its end if the window fails.
    worker = threading.Thread(target=work)
    worker.start()
    try:
        import flet as ft
        from gui import drop, theme as t

        def main(page: ft.Page) -> None:
            page.title = "pokeldn"
            page.theme_mode = ft.ThemeMode.DARK
            page.theme = page.dark_theme = t.app_theme()
            page.bgcolor = page.window.bgcolor = t.BG
            page.padding = 24
            page.window.width, page.window.height = 400, 150
            page.window.resizable = page.window.maximizable = False
            page.add(ft.Row([
                ft.ProgressRing(width=24, height=24, stroke_width=3, color=t.BLUE),
                ft.Column([t.text(f"Updating pokeldn to {version}", 15, weight=ft.FontWeight.W_600),
                           t.text("pokeldn opens again in a moment.", 12, t.MUTED)], spacing=4, tight=True),
            ], spacing=18, vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True))
            page.run_task(page.window.center)
            update.READY.touch()

        drop.use_client()
        ft.run(main, assets_dir=os.path.join(ROOT, "gui", "assets"))
    except Exception:   # no window: the swap goes on without one
        pass
    worker.join()       # work() ends the process; a window closed early waits for it here

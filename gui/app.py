import flet as ft

from gui import board
from pokeldn.app import settings
from pokeldn.app.paths import SESSION
from gui.views.widgets import on_ui


class App:
    """State shared by the pages: settings, the one child process a board allows, and services."""

    def __init__(self, page: ft.Page):
        self.page = page
        SESSION.mkdir(parents=True, exist_ok=True)
        self.settings = settings.load()
        self.picker = ft.FilePicker()
        self.clipboard = ft.Clipboard()
        self.launcher = ft.UrlLauncher()
        self.process = None        # the running session or flash
        self.process_label = ""
        self.board_busy = False    # an identify holds the port
        self.navigate = None       # set by the shell: navigate(page_key, **kwargs)

    def ui(self, fn) -> None:
        on_ui(self.page, fn)

    @property
    def busy(self) -> bool:
        return self.board_busy or bool(self.process and self.process.running)

    def radio_port(self) -> str:
        """The chosen radio if it is plugged in, else the only board present."""
        present = [p.device for p in board.ports() if p.supported]
        if self.settings.radio_port in present:
            return self.settings.radio_port
        return present[0] if len(present) == 1 else ""

    async def open_url(self, url: str) -> None:
        await self.launcher.launch_url(url)

    async def copy(self, value: str) -> None:
        await self.clipboard.set(value)
        self.page.show_dialog(ft.SnackBar(ft.Text("Copied"), duration=1500))

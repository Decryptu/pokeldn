import os
import threading
from collections import deque
from typing import Callable

import flet as ft

from gui import theme as t


def on_ui(page: ft.Page, fn: Callable[[], None]) -> None:
    """Runs fn on the page's event loop; control updates are not safe from worker threads."""
    async def call():
        fn()
    page.run_task(call)


class Log:
    """A monospace log that takes lines from any thread and redraws at most four times a second."""

    MAX = 1500

    def __init__(self, page: ft.Page, placeholder: str = ""):
        self.page = page
        self.lines: deque[str] = deque(maxlen=self.MAX)
        self.pending: list[str] = []
        self.lock = threading.Lock()
        self.flush_scheduled = False
        self.list = ft.ListView(expand=True, spacing=1, auto_scroll=True, padding=ft.Padding(12, 10, 12, 10))
        self.placeholder = t.text(placeholder, 12, t.FAINT)
        self.control = ft.Container(ft.Stack([self.list, ft.Container(self.placeholder, padding=12)],
                                             expand=True),
                                    expand=True, bgcolor=t.BG, border_radius=10,
                                    border=ft.Border.all(1, t.BORDER))

    @staticmethod
    def _line(line: str) -> ft.Text:
        lower = line.lower()
        color = t.RED if ("traceback" in lower or "error" in lower or "failed" in lower) else \
            t.GREEN if ("complete" in lower or "success" in lower) else \
            t.BLUE if line.startswith("[app]") else "#B9BCC4"
        return ft.Text(line, size=11.5, color=color, font_family=t.MONO, selectable=True)

    def add(self, line: str) -> None:
        with self.lock:
            self.pending.append(line)
            if self.flush_scheduled:
                return
            self.flush_scheduled = True
        threading.Timer(0.25, lambda: on_ui(self.page, self._flush)).start()

    def _flush(self) -> None:
        with self.lock:
            pending, self.pending, self.flush_scheduled = self.pending, [], False
        self.lines.extend(pending)
        self.list.controls.extend(self._line(l) for l in pending)
        del self.list.controls[:-self.MAX]
        self.placeholder.visible = not self.lines
        self.list.update()
        self.placeholder.update()

    def clear(self) -> None:
        self.lines.clear()
        self.list.controls = []
        self.placeholder.visible = True

    def text(self) -> str:
        return "\n".join(self.lines)


class PathField:
    """A path text field with a browse button. Paths inside the work folder are kept relative."""

    def __init__(self, picker: ft.FilePicker, work_dir: Callable[[], str], value: str = "",
                 mode: str = "file", exts: tuple = (), on_change: Callable[[str], None] | None = None,
                 hint: str = ""):
        self.picker, self.work_dir, self.mode, self.exts = picker, work_dir, mode, exts
        self.on_change = on_change
        many = mode == "files"
        self.field = t.field(value="\n".join(value) if many else value, hint=hint, mono=True,
                             expand=True, multiline=many, min_lines=2 if many else None,
                             on_change=lambda e: self._changed(e.control.value))
        icon = ft.Icons.FOLDER_OPEN_OUTLINED if mode == "dir" else \
            ft.Icons.SAVE_OUTLINED if mode == "save" else ft.Icons.FILE_OPEN_OUTLINED
        self.control = ft.Row([self.field, t.icon_button(icon, self._browse, "Browse")], spacing=6)

    def _changed(self, value: str) -> None:
        if self.on_change:
            self.on_change([l.strip() for l in value.splitlines() if l.strip()]
                           if self.mode == "files" else value)

    def _relative(self, path: str) -> str:
        work = os.path.abspath(os.path.expanduser(self.work_dir()))
        path = os.path.abspath(path)
        return os.path.relpath(path, work) if path.startswith(work + os.sep) else path

    async def _browse(self, e) -> None:
        start = os.path.expanduser(self.work_dir())
        start = start if os.path.isdir(start) else None
        if self.mode == "dir":
            path = await self.picker.get_directory_path(initial_directory=start)
        elif self.mode == "save":
            path = await self.picker.save_file(initial_directory=start,
                                               file_name=os.path.basename(self.field.value or ""))
        else:
            files = await self.picker.pick_files(
                initial_directory=start, allowed_extensions=list(self.exts) or None,
                file_type=ft.FilePickerFileType.CUSTOM if self.exts else ft.FilePickerFileType.ANY,
                allow_multiple=self.mode == "files")
            paths = [self._relative(f.path) for f in files if f.path]
            path = "\n".join(paths) if self.mode == "files" else (paths[0] if paths else None)
        if path:
            self.field.value = path if self.mode == "files" else self._relative(path)
            self.field.update()
            self._changed(self.field.value)


def open_folder(path: str) -> None:
    import subprocess
    import sys
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])

import asyncio
import os
import re
import threading
import time
from collections import deque
from typing import Callable

import flet as ft

from gui import drop, theme as t


class PixelActivity(ft.Container):
    def __init__(self, label: str = "Loading"):
        positions = [(6, 0), (12, 0), (12, 6), (12, 12), (6, 12), (0, 12), (0, 6), (0, 0)]
        self._pixels = [ft.Container(width=3, height=3, left=x, top=y, bgcolor=t.BLUE,
                                     opacity=1 if i == 0 else 0.2)
                        for i, (x, y) in enumerate(positions)]
        self._task = None
        super().__init__(ft.Semantics(content=ft.Stack(self._pixels, width=15, height=15),
                                      label=label, container=True, exclude_semantics=True),
                         width=24, height=24, alignment=ft.Alignment.CENTER)

    def did_mount(self):
        self._task = self.page.run_task(self._animate)

    def will_unmount(self):
        if self._task:
            self._task.cancel()

    async def _animate(self):
        phase = 0
        while True:
            await asyncio.sleep(0.14)
            phase = (phase + 1) % len(self._pixels)
            for i, pixel in enumerate(self._pixels):
                pixel.opacity = max(0.18, 1 - ((phase - i) % 8) * 0.22)
            self.update()


class CodeBlock:
    def __init__(self, app, value: str = "", content: ft.Control | None = None):
        self.app = app
        self.text = t.text(value, 12, t.MUTED, font_family=t.MONO, selectable=True)
        self.control = ft.Container(ft.Row([
            ft.Container(content if content is not None else self.text, expand=True,
                         padding=ft.Padding(0, 6, 0, 6)),
            t.icon_button("copy", self._copy, "Copy code"),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
            bgcolor=t.BG, border_radius=10, padding=10)

    async def _copy(self, e) -> None:
        await self.app.copy(self.text.value)


def fenced_blocks(source: str):
    """Keep Markdown around top-level fenced examples and copy their literal contents."""
    opening = re.compile(r"(?m)^ {0,3}(`{3,}|~{3,})[^\n]*\n")
    cursor = 0
    while match := opening.search(source, cursor):
        fence = match[1]
        closing = re.compile(r"(?m)^ {0,3}" + re.escape(fence[0]) +
                             "{" + str(len(fence)) + r",}[ \t]*(?:\n|$)").search(source, match.end())
        if closing is None:
            break
        if match.start() > cursor:
            yield source[cursor:match.start()], None
        yield source[match.start():closing.end()], source[match.end():closing.start()]
        cursor = closing.end()
    if cursor < len(source):
        yield source[cursor:], None


class MarkdownDocument:
    def __init__(self, app, on_link):
        self.app, self.on_link = app, on_link
        self.control = ft.Column(spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def set_value(self, value: str) -> None:
        self.control.controls = [self._markdown(source) if code is None else
                                 CodeBlock(self.app, code, self._markdown(source)).control
                                 for source, code in fenced_blocks(value)]

    def _markdown(self, value: str) -> ft.Markdown:
        return ft.Markdown(
            value, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, on_tap_link=self.on_link,
            md_style_sheet=ft.MarkdownStyleSheet(
                p_text_style=ft.TextStyle(size=14, color=t.SOFT, height=1.55),
                h1_text_style=ft.TextStyle(size=26, weight=ft.FontWeight.W_600, color=t.TEXT),
                h2_text_style=ft.TextStyle(size=19, weight=ft.FontWeight.W_600, color=t.TEXT),
                h3_text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_600, color=t.TEXT),
                a_text_style=ft.TextStyle(color=t.BLUE),
                code_text_style=ft.TextStyle(font_family=t.MONO, size=12, color=t.TEXT, bgcolor=t.FIELD),
                codeblock_decoration=ft.BoxDecoration(bgcolor=t.BG, border_radius=10),
                codeblock_padding=0,
                table_head_text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600, color=t.TEXT),
                table_body_text_style=ft.TextStyle(size=13, color=t.SOFT),
                table_cells_padding=ft.Padding(8, 6, 8, 6),
                block_spacing=14,
            ))


def on_ui(page: ft.Page, fn: Callable[[], None]) -> None:
    """Runs fn on the page's event loop; control updates are not safe from worker threads."""
    async def call():
        try:
            fn()
        except RuntimeError as error:
            # A worker that answers after its view was replaced (another tool picked) updates nothing.
            if "must be added to the page" not in str(error):
                raise
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
        self.control = ft.Container(ft.Stack([t.fade(self.list, 16), ft.Container(self.placeholder, padding=12)],
                                             expand=True),
                                    expand=True, bgcolor=ft.Colors.with_opacity(0.45, "#000000"),
                                    border_radius=12)

    @staticmethod
    def _line(line: str) -> ft.Text:
        lower = line.lower()
        color = t.RED if ("traceback" in lower or "error" in lower or "failed" in lower) else \
            t.GREEN if ("complete" in lower or "success" in lower) else \
            t.BLUE if line.startswith("[app]") else t.SOFT
        return ft.Text(line, size=11, color=color, font_family=t.MONO, selectable=True)

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
    """A path text field with a browse button, for a file or a folder."""

    def __init__(self, picker: ft.FilePicker, start_dir: Callable[[], str], value: str = "",
                 mode: str = "file", exts: tuple = (), on_change: Callable[[str], None] | None = None,
                 *, single_line: bool = False, droppable: bool = True):
        """`droppable=False` leaves file drops to an enclosing target."""
        self.picker, self.start_dir, self.mode, self.exts = picker, start_dir, mode, exts
        self.on_change = on_change
        # A single-line field does not fill its height; the padding brings it to the button row's 34 px.
        options = {"height": t.CONTROL_HEIGHT, "fit_parent_size": False, "max_lines": 1, "multiline": False,
                   "content_padding": ft.Padding(12, 11, 12, 11)} if single_line else {}
        self.field = t.field(value=value, mono=True, expand=True,
                             on_change=lambda e: self._changed(e.control.value), **options)
        icon = "folder" if mode == "dir" else "file"
        row = ft.Row([self.field, t.icon_button(icon, self._browse, "Browse")], spacing=6,
                     vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.control = (drop.target(ft.Container(row, border_radius=t.CONTROL_RADIUS), self._dropped)
                        if droppable else row)

    def _dropped(self, paths: list[str]) -> None:
        """The first dropped file this field takes; a folder field takes a file's folder."""
        if self.mode == "dir":
            path = next((p if os.path.isdir(p) else os.path.dirname(p) for p in paths), "")
        else:
            path = next((p for p in paths if not self.exts or drop.suffix(p) in self.exts), "")
        if path:
            self.set(path)

    def _changed(self, value: str) -> None:
        if self.on_change:
            self.on_change(value)

    async def _browse(self, e) -> None:
        start = os.path.expanduser(self.start_dir())
        start = start if os.path.isdir(start) else None
        if self.mode == "dir":
            path = await self.picker.get_directory_path(initial_directory=start)
        else:
            files = await self.picker.pick_files(
                initial_directory=start, allowed_extensions=list(self.exts) or None,
                file_type=ft.FilePickerFileType.CUSTOM if self.exts else ft.FilePickerFileType.ANY)
            path = files[0].path if files else None
        if path:
            self.set(path)

    def set(self, path: str) -> None:
        self.field.value = path
        self.field.update()
        self._changed(path)


def open_folder(path: str) -> None:
    import subprocess
    import sys
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class DigitCode:
    """An eight-digit console code as eight boxes: a digit moves to the next box, Backspace on an empty
    box clears the previous one (page_key), a pasted code fills from the box it lands in. The value
    keeps a cleared box as a space; command.code_error refuses anything but the full code."""

    focused: "DigitCode | None" = None     # the code whose box has the focus; page key events go to it

    def __init__(self, value: str, on_change: Callable[[str], None], length: int = 8):
        self.on_change, self.length = on_change, length
        self.digits = [c if c.isdigit() else " " for c in str(value or "")[:length].ljust(length)]
        self.at, self.cleared = 0, (None, 0.0)
        self.boxes = [self._box(n) for n in range(length)]
        half = length // 2
        self.control = ft.Row([*self.boxes[:half], ft.Container(width=6), *self.boxes[half:]],
                              spacing=6, tight=True)

    def _box(self, n: int) -> ft.TextField:
        return t.field(value=self.digits[n].strip(), mono=True, width=36, text_align=ft.TextAlign.CENTER,
                       content_padding=ft.Padding(0, 8, 0, 8), keyboard_type=ft.KeyboardType.NUMBER,
                       on_change=lambda e, n=n: self._typed(n, e.control.value),
                       on_focus=lambda e, n=n: self._focused(n), on_blur=self._blurred)

    @property
    def value(self) -> str:
        return "".join(self.digits).rstrip()

    def _typed(self, n: int, text: str) -> None:
        # No input_filter: Flet's refuses a whole paste over one space, so "1234 5678" is cleaned here.
        typed = list(text)
        if len(typed) > 1 and self.digits[n] in typed:
            typed.remove(self.digits[n])    # the caret sat beside the old digit: keep the new one
        new = [c for c in typed if c.isdigit()]
        if not typed:
            self.digits[n] = " "
            self.cleared = (n, time.monotonic())
        elif not new:
            pass                            # a letter: the box keeps its digit
        else:
            for k, c in enumerate(new[:self.length - n]):
                self.digits[n + k] = c
            self.at = min(n + len(new), self.length - 1)
        self._commit()

    def key(self, key: str) -> None:
        n = self.at
        if key == "Backspace" and not self.digits[n].strip() and n > 0:
            # The same Backspace that just emptied this box is not a second one.
            if self.cleared[0] == n and time.monotonic() - self.cleared[1] < 0.2:
                return
            self.at = n - 1
            self.digits[self.at] = " "
            self._commit()
        elif key == "Arrow Left" and n > 0:
            self.at = n - 1
            self._focus()
        elif key == "Arrow Right" and n < self.length - 1:
            self.at = n + 1
            self._focus()

    def _commit(self) -> None:
        for box, digit in zip(self.boxes, self.digits):
            box.value = digit.strip()
        self.on_change(self.value)
        self._focus()

    def _focused(self, n: int) -> None:
        self.at = n
        DigitCode.focused = self
        box = self.boxes[n]
        box.selection = ft.TextSelection(0, len(box.value or ""))
        box.update()

    def _blurred(self, e) -> None:
        if DigitCode.focused is self:
            DigitCode.focused = None

    def _focus(self) -> None:
        try:
            page = self.control.page
        except RuntimeError:            # not on a page yet
            return
        self.control.update()
        page.run_task(self.boxes[self.at].focus)


KEY_TARGET: list = [None]    # the shown view that takes keys, such as the controller


def page_key(e) -> None:
    """The page's key handler (gui/main.py): Backspace and arrows reach the focused code, the rest the
    view in KEY_TARGET."""
    if DigitCode.focused is not None:
        DigitCode.focused.key(e.key)
    elif KEY_TARGET[0] is not None:
        KEY_TARGET[0].key(e)

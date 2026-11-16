import asyncio
import dataclasses
import os
import re
import sys
import threading
import time
from collections import deque
from typing import Callable

import flet as ft
import flet.canvas as cv

from gui import drop, theme as t
from gui.localization import summary_text
from pokeldn.app.i18n import t as tr
from pokeldn.windowless import NO_WINDOW


WAITING = "waiting"   # the data of a placeholder reloading() put in place, or of a notice()


def notice(text: str, color: str, **kwargs) -> ft.Control:
    """A hint or an error standing in for a list's content: reloading() replaces it with its placeholder."""
    line = t.text(text, 12, color, **kwargs)
    line.data = WAITING
    return line


LOADING = tr('widgets.loading_dc3808', 'Loading')


def _bar(height: float, width: float | None = None, radius: float | None = None) -> ft.Container:
    return ft.Container(height=height, width=width, bgcolor=t.FIELD,
                        border_radius=radius if radius is not None else min(height / 2, 8))


def _shimmer(content: ft.Control, label: str) -> ft.Control:
    """Skeleton shapes under one moving highlight, read out as `label`."""
    # WAITING: reloading() and a stepped drawing take any skeleton for a placeholder, never for content.
    return ft.Semantics(content=ft.Shimmer(content, base_color=t.FIELD, highlight_color=t.HOVER, period=1400),
                        label=label, container=True, exclude_semantics=True, data=WAITING)


def skeleton(rows: tuple[int, ...] = (3, 3, 3), label: str = LOADING) -> ft.Control:
    """A form of labelled fields standing in while its choices load: `rows` gives each row's field count."""
    field = lambda: ft.Column([_bar(10, 64), _bar(t.CONTROL_HEIGHT)], spacing=8, expand=True,  # noqa: E731
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    return _shimmer(ft.Column([ft.Row([field() for _ in range(n)], spacing=10) for n in rows], spacing=14), label)


def _chip_row(count: int) -> ft.Control:
    return ft.Row([_bar(26, 70 + 28 * (n % 3)) for n in range(count)], spacing=6, run_spacing=6, wrap=True)


def skeleton_chips(count: int = 8, label: str = LOADING) -> ft.Control:
    """A row of chips standing in while a set of chips loads."""
    return _shimmer(_chip_row(count), label)


def _list_rows(rows: int, lead: bool) -> ft.Control:
    def row(n: int) -> ft.Control:
        lines = ft.Column([_bar(12, 120 + 40 * (n % 3)), _bar(10, 200 + 30 * (n % 2))], spacing=8)
        return ft.Row([*([_bar(40, 40, 10)] if lead else []), lines], spacing=12)
    return ft.Column([row(n) for n in range(rows)], spacing=14)


def _tiles(count: int, size: float, height: float | None = None) -> ft.Control:
    return ft.Row([_bar(height or size, size, 12) for _ in range(count)], spacing=8, run_spacing=8, wrap=True)


def skeleton_list(rows: int = 3, lead: bool = True, label: str = LOADING) -> ft.Control:
    """Rows of an optional square and two lines of text, standing in while a list loads."""
    return _shimmer(_list_rows(rows, lead), label)


def skeleton_tiles(count: int = 24, size: float = 56, label: str = LOADING, height: float | None = None) -> ft.Control:
    """A wrapped grid of tiles, `size` wide and `height` (default `size`) tall, standing in while a grid loads."""
    return _shimmer(_tiles(count, size, height), label)


FRAME = 0.03      # between two steps: the window paints the last patch before the next arrives
_STEPS: dict[int, object] = {}


def draw_in_steps(app, holder, items: list, step: int | None,
                  filler: Callable[[int], list] | None = None, done: Callable[[], None] | None = None,
                  first: int | None = None) -> None:
    """Puts `items` in `holder.controls` `step` at a time, one frame apart: a long list in one patch made the
    window lay it all out in one frame and freeze (docs/gui.md, Performance). `filler(n)` is the skeleton
    standing for the n not drawn yet. `first` (default `step`) are set now, for the caller's own update;
    `step=None` sets every item now and stops a drawing still running. `done` runs after the last step."""
    token = _STEPS[id(holder)] = object()

    def lay(n: int) -> None:
        rest = len(items) - n
        holder.controls = list(items[:n]) + (filler(rest) if rest > 0 and filler else [])

    n = len(items) if step is None else min(len(items), step if first is None else first)
    lay(n)
    if n >= len(items):
        _STEPS.pop(id(holder), None)
        if done:
            done()
        return

    async def run():
        count = n
        while count < len(items):
            await asyncio.sleep(FRAME)
            if _STEPS.get(id(holder)) is not token:
                return
            count += step
            lay(count)
            try:
                # The page diffs from what the window holds; the holder's own update() did not always
                # (a stepped Bank grid logged IndexErrors in the window and lost its tiles).
                app.page.update()
            except RuntimeError:    # the page closed
                return
        _STEPS.pop(id(holder), None)
        if done:
            done()
    app.page.run_task(run)


def after_frame(app, call: Callable[[], None]) -> None:
    """Runs `call` on the UI loop a frame from now, from any thread: the patches already sent are painted first."""
    async def run():
        await asyncio.sleep(FRAME)
        try:
            call()
        except RuntimeError as error:    # its view left the page
            if "must be added to the page" not in str(error):
                raise
    app.page.run_task(run)


def one_per_frame(app, calls: list[Callable[[], None]]) -> None:
    """Runs each call a frame after the last, so each one's patch is laid out on its own."""
    async def run():
        for call in calls:
            await asyncio.sleep(FRAME)
            call()
    if calls:
        app.page.run_task(run)


def shiny_icon(size: int = 12) -> ft.Control:
    return t.pixel_icon("sparkles", size=size, color=t.AMBER, tooltip=tr('widgets.shiny', 'Shiny'))


def summary_line(summary: str, size: float = 13, color: str = t.TEXT, weight=None, gender=None,
                 **kwargs) -> ft.Control:
    """pokeldn.pokemon.summary on one line, its shininess as the sparkles icon and its gender as a coloured
    sign after the species (PKHeX's gender 2 is genderless). `kwargs` go to the line's last text."""
    parts = summary.split(" · ")
    at = parts.index("shiny") if "shiny" in parts else -1
    if at > 0:
        del parts[at]
    shown = summary_text(" · ".join(parts)).split(" · ") if summary else [""]
    spans = [ft.TextSpan(shown[0])]
    if gender in (0, 1):
        spans.append(ft.TextSpan(" ♂" if gender == 0 else " ♀", ft.TextStyle(color=t.BLUE if gender == 0 else t.PINK)))
    if at <= 0:
        spans += [ft.TextSpan(" · " + part) for part in shown[1:]]
        return t.text("", size, color, weight, spans=spans, **kwargs)
    spans += [ft.TextSpan(" · " + part) for part in shown[1:at]]
    after = " · ".join(shown[at:])
    return ft.Row([t.text("", size, color, weight, spans=spans), shiny_icon(12 if size < 18 else 18),
                   *([t.text("· " + after, size, color, weight, **kwargs)] if after else [])],
                  spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                  expand=kwargs.get("expand"))


class DropZone(ft.Container):
    """A dashed box saying what can be dropped. The whole surrounding target still takes the drop; the box only
    shows players where to aim. Flet borders draw no dashes, so a canvas draws them at the box's size."""

    def __init__(self, text: str, icon: str = "upload"):
        self.canvas = cv.Canvas(on_resize=self._resize, resize_interval=50,
                                       left=0, top=0, right=0, bottom=0)
        label = ft.Row([t.pixel_icon(icon, color=t.FAINT), t.text(text, 12, t.MUTED)], spacing=8, tight=True,
                       alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        super().__init__(ft.Stack([self.canvas, ft.Container(label, padding=ft.Padding(16, 14, 16, 14),
                                                             alignment=ft.Alignment.CENTER)]),
                         bgcolor=ft.Colors.with_opacity(0.03, "#FFFFFF"), border_radius=10)

    def _resize(self, e) -> None:
        w, h, r, i = e.width, e.height, 10, 0.5
        P = cv.Path
        self.canvas.shapes = [P([
            P.MoveTo(r, i), P.LineTo(w - r, i), P.QuadraticTo(w - i, i, w - i, r),
            P.LineTo(w - i, h - r), P.QuadraticTo(w - i, h - i, w - r, h - i),
            P.LineTo(r, h - i), P.QuadraticTo(i, h - i, i, h - r),
            P.LineTo(i, r), P.QuadraticTo(i, i, r, i)],
            paint=ft.Paint(color=t.EDGE, stroke_width=1, style=ft.PaintingStyle.STROKE, stroke_dash_pattern=[6, 4]))]
        self.canvas.update()


def reloading(shown: list, placeholder: ft.Control) -> list:
    """What a list shows while its content reloads: what it already shows, so a filled view never blinks to a
    placeholder and back; the placeholder while nothing has loaded yet or a notice() stands in for it."""
    if shown and getattr(shown[0], "data", None) != WAITING:
        return shown
    placeholder.data = WAITING
    return [placeholder]


class PixelActivity(ft.Container):
    def __init__(self, label: str = tr('widgets.loading_dc3808', 'Loading')):
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

    def _attached(self) -> bool:
        """Whether every parent up to the page still holds its child. Flet 1.0.2 never unmounts a control
        replaced in a one-control property (a dropdown's trailing_icon, a container's content): its parent
        link survives, so update() keeps patching a control the client dropped ("unknown control")."""
        child, parent = self, self.parent
        while parent is not None:
            if not any(value is child or isinstance(value, list) and any(x is child for x in value)
                       for value in (getattr(parent, f.name, None) for f in dataclasses.fields(parent))):
                return False
            child, parent = parent, parent.parent
        return isinstance(child, ft.Page)

    async def _animate(self):
        phase = 0
        while True:
            await asyncio.sleep(0.14)
            if not self._attached():
                return
            phase = (phase + 1) % len(self._pixels)
            for i, pixel in enumerate(self._pixels):
                pixel.opacity = max(0.18, 1 - ((phase - i) % 8) * 0.22)
            try:
                self.update()
            except RuntimeError as error:
                # An async list can replace its loading icon between the wake-up and update.
                if "must be added to the page" not in str(error):
                    raise
                return


class Check:
    """A pixel checkbox and its label; `value` is whether it is checked."""

    def __init__(self, label: str, tooltip: str = "", on_change=None, value: bool = False, size: int = 12):
        self.value, self.on_change = value, on_change
        self.icon = t.pixel_icon("checkbox", color=t.MUTED)
        self._show()
        self.control = ft.Container(ft.Row([self.icon, t.text(label, size, t.TEXT)], spacing=8, tight=True),
                                    on_click=self._flip, tooltip=tooltip or None, padding=ft.Padding(2, 4, 2, 4),
                                    border_radius=8)

    def _show(self) -> None:
        self.icon.src = f"icons/{'checkbox-on' if self.value else 'checkbox'}.svg"
        self.icon.color = t.BLUE if self.value else t.MUTED

    def _flip(self, _e) -> None:
        self.value = not self.value
        self._show()
        self.control.update()
        if self.on_change:
            self.on_change(self.value)


class CodeBlock:
    def __init__(self, app, value: str = "", content: ft.Control | None = None):
        self.app = app
        self.text = t.text(value, 12, t.MUTED, font_family=t.MONO, selectable=True)
        self.control = ft.Container(ft.Row([
            ft.Container(content if content is not None else self.text, expand=True,
                         padding=ft.Padding(0, 6, 0, 6)),
            t.icon_button("copy", self._copy, tr('widgets.copy_code_49a005', 'Copy code')),
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


HEADING = re.compile(r"(?m)^ {0,3}#{1,6}[ \t]+(.+?)[ \t#]*$")
EXPLICIT_ANCHOR = re.compile(r'''<a\s+(?:id|name)=["']([^"']+)["']\s*>\s*</a>\s*$''', re.I)


def anchor(heading: str) -> str:
    """Keep kramdown's English IDs and support non-ASCII headings without an English reference."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    if not re.search(r"[a-zA-Z]", text) and any(char.isalpha() for char in text):
        return re.sub(r"[^\w -]", "", text.lower()).strip().replace(" ", "-")
    text = re.sub(r"^[^a-zA-Z]+", "", text)
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).replace(" ", "-")


def heading_sections(source: str, *, reference: str | None = None):
    """(anchor, heading, markdown) per heading, outside fenced examples, with the text before the first
    heading under ('', ''). Repeated anchors take kramdown's -1, -2 suffixes. A translated document
    with the same heading structure can keep the original document's fragment IDs. An explicit
    HTML anchor before a heading also preserves IDs when a translation adds or removes sections."""
    reference_keys = [key for key, title, _ in heading_sections(reference) if title] if reference else []
    count = sum(len(list(HEADING.finditer(block))) for block, code in fenced_blocks(source) if code is None)
    if len(reference_keys) != count:
        reference_keys = []
    seen: dict[str, int] = {}
    number = 0
    current, heading, parts = "", "", []
    for block, code in fenced_blocks(source):
        cursor = 0
        for match in HEADING.finditer(block) if code is None else ():
            prefix = block[cursor:match.start()]
            explicit = EXPLICIT_ANCHOR.search(prefix)
            parts.append(prefix[:explicit.start()] if explicit else prefix)
            yield current, heading, "".join(parts)
            heading, base = match[1], anchor(match[1])
            current = f"{base}-{seen[base]}" if base in seen else base
            if reference_keys:
                current = reference_keys[number]
            elif explicit:
                current = explicit[1]
            number += 1
            seen[base] = seen.get(base, 0) + 1
            parts, cursor = [], match.start()
        parts.append(block[cursor:])
    yield current, heading, "".join(parts)


class MarkdownDocument:
    def __init__(self, app, on_link):
        self.app, self.on_link = app, on_link
        self.control = ft.Column(spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def set_value(self, value: str, *, reference: str | None = None) -> None:
        """Each heading starts its own control keyed by its anchor, so a link or a search result scrolls to it."""
        controls = []
        for key, _, section in heading_sections(value, reference=reference):
            first = True
            for source, code in fenced_blocks(section):
                if not source.strip():
                    continue
                control = self._markdown(source) if code is None else CodeBlock(self.app, code, self._markdown(source)).control
                if first and key:
                    control.key = ft.ScrollKey(key)
                first = False
                controls.append(control)
        self.control.controls = controls

    def _markdown(self, value: str) -> ft.Markdown:
        return ft.Markdown(
            value, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, on_tap_link=self.on_link,
            md_style_sheet=ft.MarkdownStyleSheet(
                p_text_style=ft.TextStyle(size=t.scaled(14), color=t.SOFT, height=1.55),
                h1_text_style=ft.TextStyle(size=t.scaled(26), weight=ft.FontWeight.W_600, color=t.TEXT),
                h2_text_style=ft.TextStyle(size=t.scaled(19), weight=ft.FontWeight.W_600, color=t.TEXT),
                h3_text_style=ft.TextStyle(size=t.scaled(16), weight=ft.FontWeight.W_600, color=t.TEXT),
                a_text_style=ft.TextStyle(color=t.BLUE),
                code_text_style=ft.TextStyle(font_family=t.MONO, size=t.scaled(12), color=t.TEXT, bgcolor=t.FIELD),
                codeblock_decoration=ft.BoxDecoration(bgcolor=t.BG, border_radius=10),
                codeblock_padding=0,
                table_head_text_style=ft.TextStyle(size=t.scaled(13), weight=ft.FontWeight.W_600, color=t.TEXT),
                table_body_text_style=ft.TextStyle(size=t.scaled(13), color=t.SOFT),
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
    """A monospace log that takes lines from any thread and redraws at most four times a second (once
    on a phone)."""

    MAX = 1500
    # On a phone the run shares the interface's interpreter, and each redraw diffs every line kept:
    # an iPhone run fell from 41 to 12 link slots per second (examples/ios/README.md).
    PHONE = os.environ.get("POKELDN_PLATFORM") in ("android", "ios")
    if PHONE:
        MAX = 300
    FLUSH = 1.0 if PHONE else 0.25

    def __init__(self, page: ft.Page, placeholder: str = "", private=None):
        """`private`: a callable that returns the names to mask from the start (the user's trainer), or
        None while Settings shows full logs; each clear starts a new run's Redactor."""
        self.page = page
        self.private = private
        self.lines: deque[str] = deque(maxlen=self.MAX)
        self.pending: list[str] = []
        self.lock = threading.Lock()
        self.flush_scheduled = False
        self.redactor = None
        self._new_redactor()
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
        from gui.localization import app_log
        return ft.Text(app_log(line), size=t.scaled(11), color=color, font_family=t.MONO, selectable=True)

    def add(self, line: str) -> None:
        if self.redactor is not None:
            line = self.redactor(line)
        with self.lock:
            self.pending.append(line)
            if self.flush_scheduled:
                return
            self.flush_scheduled = True
        threading.Timer(self.FLUSH, lambda: on_ui(self.page, self._flush)).start()

    def _flush(self) -> None:
        with self.lock:
            pending, self.pending, self.flush_scheduled = self.pending, [], False
        self.lines.extend(pending)
        self.list.controls.extend(self._line(l) for l in pending)
        del self.list.controls[:-self.MAX]
        self.placeholder.visible = not self.lines
        self.list.update()
        self.placeholder.update()

    def _new_redactor(self) -> None:
        from pokeldn.app.redact import Redactor
        names = self.private() if self.private else None
        self.redactor = Redactor(names) if names is not None else None

    def clear(self) -> None:
        self._new_redactor()
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
        row = ft.Row([self.field, t.icon_button(icon, self._browse, tr('widgets.browse_3227aa', 'Browse'))], spacing=6,
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
            path = await self.picker.get_directory_path(
                dialog_title=tr("widgets.choose_folder", "Choose folder"), initial_directory=start)
        else:
            files = await self.picker.pick_files(
                dialog_title=tr("widgets.choose_file", "Choose file"),
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
    from pokeldn.app import android
    if android.active():   # no file manager to show it in: the folder goes, zipped, where the player saves it
        android.save_folder(path)
        return
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path], **NO_WINDOW)


class DigitCode:
    """An eight-digit console code as eight boxes: a digit moves to the next box, Backspace on an empty
    box clears the previous one (page_key), a pasted code fills from the box it lands in. The value
    keeps a cleared box as a space; command.code_error refuses anything but the full code."""

    focused: 'DigitCode | None' = None     # the code whose box has the focus; page key events go to it

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
SHORTCUTS: list = [None]     # gui/main.py's handler for Cmd (macOS) or Ctrl shortcuts: (key) -> True if taken


def page_key(e) -> None:
    """The page's key handler (gui/main.py): Cmd or Ctrl shortcuts first, then Backspace and arrows reach the
    focused code, the rest the view in KEY_TARGET."""
    command = e.meta if sys.platform == "darwin" else e.ctrl
    if command and not e.alt and SHORTCUTS[0] is not None and SHORTCUTS[0](e.key):
        return
    if DigitCode.focused is not None:
        DigitCode.focused.key(e.key)
    elif KEY_TARGET[0] is not None:
        KEY_TARGET[0].key(e)
    else:
        # Every key press reaches here, typing included; Flet's automatic update would diff the whole page.
        ft.context.disable_auto_update()
